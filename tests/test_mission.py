"""Tests for the mission-control grid.

The value here is that the grid shows *this project's* live sessions and no
others, and that a panel actually paints what a session is doing rather than
building content that never reaches the screen. Both run the screen headlessly
through Textual's `run_test`, against jobs written to a throwaway `~/.claude`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.geometry import Region
from textual.widgets import Static

from bv.agents import Activity, Session, TimelineEvent
from bv.mission import AgentPanel, MissionControl


def write_job(home: Path, short: str, cwd: str, **fields) -> None:
	job = home / "jobs" / short
	job.mkdir(parents=True, exist_ok=True)
	payload = {"name": short, "cwd": cwd, "state": "working", **fields}
	(job / "state.json").write_text(json.dumps(payload))


def write_timeline(home: Path, short: str, *lines: dict) -> None:
	job = home / "jobs" / short
	job.mkdir(parents=True, exist_ok=True)
	(job / "timeline.jsonl").write_text("\n".join(json.dumps(o) for o in lines) + "\n")


def write_roster(home: Path, *shorts: str) -> None:
	daemon = home / "daemon"
	daemon.mkdir(parents=True, exist_ok=True)
	(daemon / "roster.json").write_text(json.dumps({"workers": {s: {"pid": 1} for s in shorts}}))


class Host(App):
	"""Throwaway host so the screen can be pushed headlessly."""

	def compose(self) -> ComposeResult:
		yield Static()


def painted(screen: MissionControl) -> str:
	"""Everything the screen's panels actually paint, as text.

	Through `render_lines`, so content built but never mounted fails the read.
	"""
	lines: list[str] = []
	for widget in screen.query(Static):
		width, height = widget.outer_size
		if not width or not height:
			continue
		lines.extend(strip.text for strip in widget.render_lines(Region(0, 0, width, height)))
	return "\n".join(lines)


Scenario = Callable[[MissionControl, object], Awaitable[None]]


def drive(home: Path, project_root: Path, scenario: Scenario, monkeypatch) -> None:
	monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

	async def main() -> None:
		app = Host()
		async with app.run_test(size=(100, 40)) as pilot:
			screen = MissionControl("proj", project_root)
			await app.push_screen(screen)
			await pilot.pause()
			await pilot.pause()
			await scenario(screen, pilot)

	asyncio.run(main())


def test_the_grid_shows_only_this_projects_sessions(tmp_path, monkeypatch):
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_job(home, "aaaa", str(root), name="bv-9gnt · Agents view")
	write_job(home, "bbbb", str(tmp_path / "other"), name="elsewhere")
	write_roster(home, "aaaa", "bbbb")

	async def scenario(screen, pilot):
		panels = list(screen.query(AgentPanel))
		ids = {p.id for p in panels}
		assert ids == {"agent-aaaa"}, ids

	drive(home, root, scenario, monkeypatch)


def test_a_panel_paints_the_session_and_its_feed(tmp_path, monkeypatch):
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_job(
		home,
		"aaaa",
		str(root),
		name="bv-9gnt · Agents view",
		state="working",
		detail="editing mission.py",
		tokens=12300,
	)
	write_timeline(
		home,
		"aaaa",
		{"at": "2026-08-21T17:20:03.293Z", "state": "working", "detail": "reading beans", "text": ""},
	)
	write_roster(home, "aaaa")

	async def scenario(screen, pilot):
		text = painted(screen)
		assert "bv-9gnt" in text
		assert "12.3k tok" in text
		assert "reading beans" in text

	drive(home, root, scenario, monkeypatch)


def test_a_panel_shows_the_agents_output_not_just_status(tmp_path, monkeypatch):
	"""bv-9gnt regression: the feed led with `detail` and hid `text`, so a

	watcher saw status headlines and their own prompts but never the agent's
	replies. The agent's `text` must reach the panel.
	"""
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_job(home, "aaaa", str(root), name="bv-9gnt · Agents view")
	write_timeline(
		home,
		"aaaa",
		# A user turn: detail carries the message, text is empty.
		{"at": "2026-08-21T17:20:00.000Z", "state": "blocked", "detail": "what branch are we on?", "text": ""},
		# The agent's reply lands in text.
		{
			"at": "2026-08-21T17:20:09.000Z",
			"state": "working",
			"detail": "confirming branch",
			"text": "We are on main, HEAD abc123.",
		},
	)
	write_roster(home, "aaaa")

	async def scenario(screen, pilot):
		text = painted(screen)
		assert "We are on main, HEAD abc123." in text

	drive(home, root, scenario, monkeypatch)


def test_a_waiting_session_reads_needs_input(tmp_path, monkeypatch):
	"""The badge names the state from the watcher's seat: `blocked` -> the

	agent needs input. The raw word never reaches the panel.
	"""
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_job(home, "aaaa", str(root), name="bv-9gnt · Agents view", state="blocked")
	write_roster(home, "aaaa")

	async def scenario(screen, pilot):
		text = painted(screen)
		assert "needs input" in text
		assert "blocked" not in text

	drive(home, root, scenario, monkeypatch)


def test_a_session_composing_a_reply_reads_working_not_needs_input(tmp_path, monkeypatch):
	"""bv-9gnt regression: a session in a question loop stays state=blocked

	while it composes each reply. When its tempo is active it is working, and
	the badge must say so rather than "needs input".
	"""
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_job(home, "aaaa", str(root), name="agent", state="blocked", tempo="active")
	write_roster(home, "aaaa")

	async def scenario(screen, pilot):
		text = painted(screen)
		assert "working" in text
		assert "needs input" not in text

	drive(home, root, scenario, monkeypatch)


def write_subagent(home: Path, session_id: str, agent_id: str, *entries: dict) -> None:
	sub = home / "projects" / "proj" / session_id / "subagents"
	sub.mkdir(parents=True, exist_ok=True)
	(sub / f"agent-{agent_id}.jsonl").write_text(
		"\n".join(json.dumps({"agentId": agent_id, **e}) for e in entries) + "\n"
	)


def test_a_session_with_subagents_tiles_them(tmp_path, monkeypatch):
	"""bv-xv9s: each in-process subagent gets its own tile inside the parent,

	labelled with its task and showing recent activity.
	"""
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_job(
		home,
		"aaaa",
		str(root),
		name="parent agent",
		state="working",
		sessionId="sess-1",
		inFlight={"tasks": 1, "kinds": ["local_agent"]},
	)
	write_subagent(
		home,
		"sess-1",
		"a1",
		{"type": "user", "message": {"role": "user", "content": "Extract tactics"}},
		{
			"type": "assistant",
			"message": {"role": "assistant", "content": [{"type": "text", "text": "wrote extraction"}]},
		},
	)
	write_roster(home, "aaaa")

	async def scenario(screen, pilot):
		text = painted(screen)
		# The task titles the tile; the recent activity fills its body.
		assert "Extract tactics" in text
		assert "wrote extraction" in text

	drive(home, root, scenario, monkeypatch)


def test_a_panel_pins_to_the_latest_activity(tmp_path):
	"""An overhead glance shows the newest line: a pane taller than its box

	scrolls itself to the bottom rather than stranding the latest activity
	below the fold.
	"""
	session = Session(short="a", name="agent", state="working", cwd="/x", live=True, tempo="active")
	events = tuple(
		TimelineEvent(at=f"2026-08-21T17:0{i}:00Z", state="working", detail="", text=f"line {i}") for i in range(8)
	)
	activity = Activity(
		short="a",
		state="working",
		detail="working",
		tempo="active",
		tokens=100,
		subagents=0,
		child_kinds=(),
		result="",
		events=events,
	)
	panel = AgentPanel(session)

	class Solo(App):
		def compose(self) -> ComposeResult:
			yield panel

	async def main() -> None:
		app = Solo()
		async with app.run_test(size=(40, 30)) as pilot:
			panel.styles.height = 4  # smaller than the content, forcing overflow
			panel.update(session, activity)
			await pilot.pause()
			await pilot.pause()
			assert panel.max_scroll_y > 0, "content did not overflow, test proves nothing"
			assert panel.scroll_offset.y == panel.max_scroll_y, "pane not pinned to the bottom"

	asyncio.run(main())


def test_an_empty_project_says_so_rather_than_crashing(tmp_path, monkeypatch):
	home = tmp_path / "claude"
	root = tmp_path / "proj"
	root.mkdir()
	write_roster(home)  # no workers, no jobs

	async def scenario(screen, pilot):
		assert not list(screen.query(AgentPanel))
		assert "no active agents" in painted(screen)

	drive(home, root, scenario, monkeypatch)
