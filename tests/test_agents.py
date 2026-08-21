"""Tests for the Claude session join.

The hazards here fail silently rather than loudly: a layout change in
`~/.claude` empties the column, a dead session keeps claiming a bean forever,
and a coarse match attributes work to an agent that is merely in the
neighbourhood. Each gets a named test.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bv.agents import (
	Session,
	attribute,
	attribute_all,
	claude_home,
	load_activity,
	load_sessions,
	session_name_for,
	session_within,
	sessions_within,
)


def write_job(home: Path, short: str, **fields) -> None:
	job = home / "jobs" / short
	job.mkdir(parents=True, exist_ok=True)
	payload = {"name": short, "cwd": "/tmp", "state": "working", **fields}
	(job / "state.json").write_text(json.dumps(payload))


def write_timeline(home: Path, short: str, *lines: str) -> None:
	job = home / "jobs" / short
	job.mkdir(parents=True, exist_ok=True)
	(job / "timeline.jsonl").write_text("\n".join(lines) + "\n")


def event(**fields: Any) -> str:
	base = {"at": "2026-08-21T17:20:03.293Z", "state": "working", "detail": "", "text": ""}
	return json.dumps({**base, **fields})


def write_roster(home: Path, *shorts: str) -> None:
	daemon = home / "daemon"
	daemon.mkdir(parents=True, exist_ok=True)
	(daemon / "roster.json").write_text(json.dumps({"workers": {s: {"pid": 1} for s in shorts}}))


def session(**kwargs: Any) -> Session:
	base: dict[str, Any] = {
		"short": "aaaa",
		"name": "a",
		"state": "working",
		"cwd": "/tmp",
		"live": True,
	}
	return Session(**{**base, **kwargs})


# -- activity (the mission-control feed) ----------------------------------


def test_activity_reads_the_snapshot_and_the_tail(tmp_path):
	write_job(
		tmp_path,
		"abcd",
		state="blocked",
		detail="awaiting review",
		tempo="idle",
		tokens=23127,
		inFlight={"tasks": 2, "kinds": ["local_agent"]},
		output={"result": "shipped"},
	)
	write_timeline(
		tmp_path,
		"abcd",
		event(detail="reading beans"),
		event(state="blocked", detail="awaiting review", text="what next?"),
	)

	activity = load_activity("abcd", tmp_path)

	assert activity is not None
	assert activity.state == "blocked"
	assert activity.detail == "awaiting review"
	assert activity.tempo == "idle"
	assert activity.tokens == 23127
	assert activity.subagents == 2
	assert activity.child_kinds == ("local_agent",)
	assert activity.result == "shipped"
	assert [e.detail for e in activity.events] == ["reading beans", "awaiting review"]
	assert activity.events[-1].text == "what next?"


def test_activity_of_a_job_with_no_state_is_none(tmp_path):
	assert load_activity("ghost", tmp_path) is None


def test_a_job_with_no_timeline_still_reads_its_state(tmp_path):
	write_job(tmp_path, "abcd", tokens=5)
	activity = load_activity("abcd", tmp_path)
	assert activity is not None
	assert activity.events == ()
	assert activity.tokens == 5


def test_the_tail_skips_corrupt_lines_and_caps_length(tmp_path):
	write_job(tmp_path, "abcd")
	lines = ["{not json"] + [event(detail=f"step {i}") for i in range(20)]
	write_timeline(tmp_path, "abcd", *lines)

	activity = load_activity("abcd", tmp_path, tail=5)

	assert activity is not None
	# The garbage line is dropped and only the last five good lines survive.
	assert [e.detail for e in activity.events] == [f"step {i}" for i in range(15, 20)]


def test_missing_inflight_and_output_degrade_to_empty(tmp_path):
	write_job(tmp_path, "abcd")  # no inFlight, no output
	activity = load_activity("abcd", tmp_path)
	assert activity is not None
	assert activity.subagents == 0
	assert activity.child_kinds == ()
	assert activity.result == ""


def test_sessions_within_lists_a_projects_sessions_live_first(tmp_path):
	root = tmp_path / "proj"
	root.mkdir()
	(root / "sub").mkdir()
	inside_live = session(short="a", name="a", cwd=str(root), state="working", live=True)
	inside_sub = session(short="b", name="b", cwd=str(root / "sub"), state="working", live=True)
	inside_dead = session(short="c", name="c", cwd=str(root), state="working", live=False)
	outside = session(short="d", name="d", cwd=str(tmp_path / "other"), live=True)

	within = sessions_within([outside, inside_dead, inside_live, inside_sub], root)

	shorts = [s.short for s in within]
	assert outside.short not in shorts
	# Live sessions (busy) lead; the dead one trails.
	assert shorts[-1] == "c"
	assert set(shorts[:2]) == {"a", "b"}


# -- reading --------------------------------------------------------------


def test_a_session_is_read_from_its_state_file(tmp_path):
	write_job(tmp_path, "abcd", name="demo-a", cwd="/repo", state="working")
	write_roster(tmp_path, "abcd")
	(found,) = load_sessions(tmp_path)
	assert (found.short, found.name, found.cwd, found.state) == (
		"abcd",
		"demo-a",
		"/repo",
		"working",
	)
	assert found.live


def test_a_session_missing_from_the_roster_is_not_live(tmp_path):
	# The state file can say `working` for a process that died without
	# updating it. Believing the file alone shows a ghost agent forever.
	write_job(tmp_path, "abcd", state="working")
	write_roster(tmp_path)
	(found,) = load_sessions(tmp_path)
	assert found.state == "working"
	assert not found.live
	assert not found.is_busy


def test_a_finished_session_is_never_busy(tmp_path):
	for state in ("done", "failed", "stopped"):
		write_job(tmp_path, "abcd", state=state)
		write_roster(tmp_path, "abcd")
		(found,) = load_sessions(tmp_path)
		assert not found.is_busy, state


def test_a_blocked_session_is_still_busy(tmp_path):
	# Blocked means waiting on the human, not finished -- it still owns its
	# bean, and that is exactly when you want to see who to go unblock.
	write_job(tmp_path, "abcd", state="blocked")
	write_roster(tmp_path, "abcd")
	(found,) = load_sessions(tmp_path)
	assert found.is_busy


def test_corrupt_and_missing_files_degrade_to_nothing(tmp_path):
	(tmp_path / "jobs" / "broken").mkdir(parents=True)
	(tmp_path / "jobs" / "broken" / "state.json").write_text("{not json")
	(tmp_path / "jobs" / "empty").mkdir(parents=True)
	write_job(tmp_path, "good")
	write_roster(tmp_path, "good")
	assert [s.short for s in load_sessions(tmp_path)] == ["good"]


def test_no_claude_directory_at_all_is_not_an_error(tmp_path):
	# The Agent column is an enrichment; it must not take the board down.
	assert load_sessions(tmp_path / "nowhere") == []


def test_a_session_without_a_name_is_skipped(tmp_path):
	# Interactive sessions can lack both name and state.
	write_job(tmp_path, "abcd", name=None)
	write_roster(tmp_path, "abcd")
	assert load_sessions(tmp_path) == []


def test_claude_home_ignores_a_relative_override(monkeypatch):
	monkeypatch.setenv("CLAUDE_CONFIG_DIR", "relative/path")
	assert claude_home() == Path.home() / ".claude"
	monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/absolute/path")
	assert claude_home() == Path("/absolute/path")


# -- attribution ----------------------------------------------------------


def test_the_bean_id_in_a_session_name_is_an_exact_match():
	found = attribute([session(name="bv-57zz · Show which agent")], "bv-57zz", None, in_progress=True)
	assert found is not None
	assert found.exact


def test_an_exact_match_wins_over_a_coarse_one(tmp_path):
	sessions = [
		session(short="near", name="something else", cwd=str(tmp_path)),
		session(short="named", name="bv-57zz · the real one", cwd="/elsewhere"),
	]
	found = attribute(sessions, "bv-57zz", tmp_path, in_progress=True)
	assert found is not None and found.exact
	assert found.session.short == "named"


def test_a_session_in_the_project_is_a_coarse_match(tmp_path):
	found = attribute([session(cwd=str(tmp_path / "src"))], "bv-1111", tmp_path, in_progress=True)
	assert found is not None
	assert not found.exact


def test_a_bean_that_is_not_in_progress_gets_no_coarse_match(tmp_path):
	assert attribute([session(cwd=str(tmp_path))], "bv-1111", tmp_path, in_progress=False) is None


def test_a_dead_session_attributes_nothing(tmp_path):
	dead = session(live=False, name="bv-57zz · finished long ago")
	assert attribute([dead], "bv-57zz", tmp_path, in_progress=True) is None


def test_a_symlinked_project_still_matches(tmp_path):
	# `demo-d` is a symlink into an iCloud vault; a string compare misses it.
	real = tmp_path / "real"
	real.mkdir()
	link = tmp_path / "link"
	link.symlink_to(real)
	assert session_within(session(cwd=str(real)), link.resolve())
	found = attribute([session(cwd=str(real))], "b-1", link, in_progress=True)
	assert found is not None and not found.exact


def test_a_session_above_the_project_does_not_match(tmp_path):
	# A session at the portfolio root is not working any one project.
	project = tmp_path / "proj"
	project.mkdir()
	assert not session_within(session(cwd=str(tmp_path)), project)


def test_attribute_all_keys_by_bean_id(tmp_path):
	sessions = [session(name="bv-aaaa · one"), session(short="b", name="bv-bbbb · two")]
	found = attribute_all(
		sessions,
		[("bv-aaaa", None, False), ("bv-bbbb", None, False), ("bv-cccc", None, False)],
	)
	assert set(found) == {"bv-aaaa", "bv-bbbb"}


# -- the name bv gives a session it dispatches ----------------------------


def test_a_dispatched_session_name_round_trips_to_an_exact_match():
	# The whole point: bv sets --name, so attribution is free afterwards.
	name = session_name_for("bv-9sxj", "Spawn a background agent from the cursor")
	found = attribute([session(name=name)], "bv-9sxj", None, in_progress=False)
	assert found is not None and found.exact


def test_a_long_title_is_trimmed_but_keeps_the_id():
	name = session_name_for("bv-9sxj", "x" * 200)
	assert name.startswith("bv-9sxj")
	assert len(name) <= 60
	found = attribute([session(name=name)], "bv-9sxj", None, in_progress=False)
	assert found is not None and found.exact


def test_an_empty_title_still_gives_a_usable_name():
	assert session_name_for("bv-9sxj", "   ") == "bv-9sxj"


# -- the contract ---------------------------------------------------------


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH")
def test_the_job_files_agree_with_claude_agents_json():
	"""`claude agents --json` is the documented interface; the files are not.

	bv reads the files because the CLI costs ~172 ms against their ~0.26 ms,
	which is too slow for a 0.5 s poll. That trade is only safe while the two
	agree, so this fails loudly if a Claude Code upgrade moves the layout --
	the alternative is the column silently going blank.
	"""
	proc = subprocess.run(
		["claude", "agents", "--json", "--all"],
		capture_output=True,
		text=True,
		timeout=60,
		check=False,
	)
	if proc.returncode != 0 or not proc.stdout.strip():
		pytest.skip("claude agents --json returned nothing")
	reported = json.loads(proc.stdout)
	# Interactive sessions have no `id`; bv only claims to see background ones.
	expected = {row["id"]: row.get("name") for row in reported if row.get("id") and row.get("name")}
	if not expected:
		pytest.skip("no background sessions to compare against")

	from_files = {s.short: s.name for s in load_sessions()}
	missing = set(expected) - set(from_files)
	assert not missing, f"job files missed sessions the CLI reports: {missing}"
	for short, name in expected.items():
		assert from_files[short] == name, short
