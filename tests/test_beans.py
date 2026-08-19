"""Tests for the preview fields added to the data layer.

Only the row -> Bean mapping is covered here. The subprocess, the error paths
and the concurrency in `load_all` are exercised by running bv against real
projects; what is worth pinning down is that a body or a blocking list which
arrives null, missing or the wrong shape produces a usable Bean instead of an
exception on the load path.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bv import beans as beans_module
from bv.beans import (
	QUERY,
	Bean,
	BeansError,
	Project,
	dependency_edges,
	discover_projects,
	fetch_project_beans,
	is_project,
	projects_under,
	resolve_dependencies,
	sort_key,
)

PROJECT = Project(name="bv", root=Path("/tmp/bv"))

ROW = {
	"id": "bv-ax9v",
	"title": "Preview pane",
	"status": "todo",
	"type": "feature",
	"priority": "high",
	"tags": ["ux"],
	"updatedAt": "2026-08-14T21:36:34Z",
	"parentId": "bv-root",
	"body": "# Why\n\nBecause a title is not enough.\n",
	"blockingIds": ["bv-1111"],
	"blockedByIds": ["bv-2222"],
}


@pytest.fixture
def respond(monkeypatch):
	"""Make the `beans` CLI return a canned payload."""

	def install(payload: str) -> None:
		def fake_run(*_args, **_kwargs):
			return subprocess.CompletedProcess([], 0, stdout=payload, stderr="")

		monkeypatch.setattr(beans_module.subprocess, "run", fake_run)

	return install


def one(respond, row) -> Bean:
	respond(json.dumps({"data": {"beans": [row]}}))
	(bean,) = fetch_project_beans(PROJECT)
	return bean


def test_query_asks_for_the_preview_fields():
	# A missing field here is silent: GraphQL returns the rest of the row and
	# the preview just renders blank.
	for field in ("body", "blockingIds", "blockedByIds"):
		assert field in QUERY


def test_the_body_and_blocking_links_come_through(respond):
	bean = one(respond, ROW)
	assert bean.body.startswith("# Why")
	assert bean.blocking_ids == ("bv-1111",)
	assert bean.blocked_by_ids == ("bv-2222",)


def test_a_null_body_becomes_an_empty_string(respond):
	# `body` is `String!` in the schema, so this should not happen -- but a
	# None here would reach the markdown parser as a None.
	assert one(respond, {**ROW, "body": None}).body == ""


def test_missing_preview_fields_fall_back_to_empty(respond):
	# An older `beans` that does not know these fields answers without them.
	row = {key: value for key, value in ROW.items() if key not in {"body", "tags"}}
	row.pop("blockingIds")
	row.pop("blockedByIds")
	bean = one(respond, row)
	assert bean.body == ""
	assert bean.blocking_ids == () and bean.blocked_by_ids == ()
	assert bean.tags == ()


def test_blocking_ids_are_tuples_so_a_bean_stays_hashable(respond):
	bean = one(respond, ROW)
	assert hash(bean)
	assert isinstance(bean.blocking_ids, tuple)


def test_a_bean_can_still_be_built_without_the_preview_fields():
	# The tree and the table construct Beans that have no body; the defaults
	# are what keeps those call sites from having to invent one.
	bean = Bean(
		project="bv",
		id="bv-1",
		title="t",
		status="todo",
		type="task",
		priority="normal",
		tags=(),
		updated_at=datetime(2026, 1, 1, tzinfo=UTC),
		parent_id=None,
	)
	assert bean.body == ""
	assert bean.blocking_ids == () and bean.blocked_by_ids == ()


def test_a_graphql_error_still_names_the_project(respond):
	respond('{"errors": [{"message": "unknown field body"}]}')
	with pytest.raises(BeansError, match="bv: unknown field body"):
		fetch_project_beans(PROJECT)


# -- dependency resolution ------------------------------------------------
#
# beans stores a dependency on whichever side declared it and never
# materialises the inverse. Measured on the real board: `blockingIds` carried
# 4 edges, `blockedByIds` carried 16, and the two sets did not overlap on a
# single edge. Reading either field alone therefore sees a fraction of the
# graph, which is what these tests exist to stop anyone doing again.


def bean(bean_id: str, status: str = "todo", **kwargs) -> Bean:
	return Bean(
		project=bean_id.split("-")[0],
		id=bean_id,
		title=bean_id,
		status=status,
		type="task",
		priority=kwargs.pop("priority", "normal"),
		tags=(),
		updated_at=datetime(2026, 8, 16, tzinfo=UTC),
		parent_id=None,
		**kwargs,
	)


def test_an_edge_declared_by_the_blocker_alone_is_found():
	# `a` says it blocks `b`; `b` says nothing at all. This is the direction
	# that reading only blocked_by_ids misses.
	board = [bean("p-a", blocking_ids=("p-b",)), bean("p-b")]
	assert dependency_edges(board) == {("p-a", "p-b")}

	a, b = resolve_dependencies(board)
	assert b.is_blocked
	assert a.unblocks == 1
	assert not a.is_blocked


def test_an_edge_declared_by_the_blocked_alone_is_found():
	board = [bean("p-a"), bean("p-b", blocked_by_ids=("p-a",))]
	assert dependency_edges(board) == {("p-a", "p-b")}

	a, b = resolve_dependencies(board)
	assert b.is_blocked
	assert a.unblocks == 1


def test_an_edge_declared_from_both_sides_counts_once():
	board = [
		bean("p-a", blocking_ids=("p-b",)),
		bean("p-b", blocked_by_ids=("p-a",)),
	]
	a, b = resolve_dependencies(board)
	assert a.unblocks == 1
	assert b.blocked_by_open == 1


def test_a_finished_blocker_stops_blocking():
	# Otherwise every bean whose dependency landed reads as blocked forever.
	for done in ("completed", "scrapped"):
		board = [bean("p-a", status=done), bean("p-b", blocked_by_ids=("p-a",))]
		_, b = resolve_dependencies(board)
		assert not b.is_blocked, done


def test_an_unfinished_blocker_of_any_live_status_still_blocks():
	for live in ("todo", "in-progress", "draft"):
		board = [bean("p-a", status=live), bean("p-b", blocked_by_ids=("p-a",))]
		_, b = resolve_dependencies(board)
		assert b.is_blocked, live


def test_an_unloaded_blocker_is_assumed_to_still_count():
	# bv can be pointed at one project while a dependency crosses into
	# another. Treating the unknown blocker as finished would mark blocked
	# work ready, which is the more expensive mistake.
	(b,) = resolve_dependencies([bean("p-b", blocked_by_ids=("other-a",))])
	assert b.is_blocked


def test_unblocks_counts_every_dependent():
	board = [
		bean("p-a", blocking_ids=("p-b", "p-c")),
		bean("p-b"),
		bean("p-c"),
	]
	a, _, _ = resolve_dependencies(board)
	assert a.unblocks == 2


def test_is_ready_needs_both_halves():
	# Blocking others is only interesting if the work can actually start.
	board = [
		bean("p-a", blocking_ids=("p-b",), blocked_by_ids=("p-z",)),
		bean("p-b"),
		bean("p-z"),
	]
	a, b, _ = resolve_dependencies(board)
	assert a.unblocks == 1
	assert not a.is_ready, "blocked work is not ready however much it unblocks"
	assert not b.is_ready, "unblocked work that frees nothing is not ready either"


# -- ordering -------------------------------------------------------------


def order(board: list[Bean]) -> list[str]:
	return [b.id for b in sorted(resolve_dependencies(board), key=sort_key)]


def test_unblocked_work_outranks_blocked_work():
	board = [
		bean("p-blocked", blocked_by_ids=("p-free",)),
		bean("p-free"),
	]
	assert order(board) == ["p-free", "p-blocked"]


def test_between_two_startable_beans_the_one_that_frees_more_wins():
	board = [
		bean("p-leaf"),
		bean("p-hub", blocking_ids=("p-x", "p-y")),
		bean("p-x"),
		bean("p-y"),
	]
	assert order(board)[0] == "p-hub"


def test_priority_now_sorts():
	# It was displayed but never sorted on, so critical and deferred
	# interleaved by date.
	board = [bean("p-low", priority="deferred"), bean("p-hot", priority="critical")]
	assert order(board) == ["p-hot", "p-low"]


def test_status_still_outranks_everything_below_it():
	# A critical, unblocked, completed bean stays below live work.
	board = [
		bean("p-done", status="completed", priority="critical"),
		bean("p-live", status="todo", priority="deferred"),
	]
	assert order(board) == ["p-live", "p-done"]


def test_blocked_outranks_priority():
	# You cannot start the critical one, so it sorts below the one you can.
	board = [
		bean("p-stuck", priority="critical", blocked_by_ids=("p-wall",)),
		bean("p-go", priority="low"),
		bean("p-wall"),
	]
	assert order(board).index("p-go") < order(board).index("p-stuck")


def test_projects_stay_grouped():
	board = [bean("z-1"), bean("a-1"), bean("z-2"), bean("a-2")]
	assert [b.split("-")[0] for b in order(board)] == ["a", "a", "z", "z"]


# -- archived detection ---------------------------------------------------
#
# There is no `archived` field on the GraphQL type and `beans archive` leaves
# archived beans "visible in all queries", so `path` is the only signal.


def test_a_bean_in_the_archive_directory_is_archived():
	assert bean("p-a", path="archive/p-a--done.md").is_archived


def test_a_top_level_bean_is_not_archived():
	assert not bean("p-a", path="p-a--live.md").is_archived


def test_a_bean_merely_named_archive_is_not_archived():
	# Segment comparison, not a string prefix.
	assert not bean("p-a", path="archive-the-old-docs.md").is_archived


def test_a_missing_path_is_not_archived():
	# Bean is built with defaults all over the tests; absent must mean live.
	assert not bean("p-a").is_archived


def test_the_query_asks_for_the_path():
	assert "path" in QUERY


def test_the_path_comes_through_from_graphql(respond):
	got = one(respond, {**ROW, "path": "archive/bv-ax9v--preview.md"})
	assert got.path == "archive/bv-ax9v--preview.md"
	assert got.is_archived


# -- what the root resolves to --------------------------------------------
#
# The board root is wherever bv was run, so these decide which of two boards a
# stranger gets: their repo shown flat, or a directory of repos grouped by
# project. One test of what a project is, shared by both, or the two paths
# disagree and a directory with `.beans` but no config is a whole board one way
# and invisible the other.


def make_project(parent: Path, name: str) -> Path:
	project = parent / name
	(project / ".beans").mkdir(parents=True)
	(project / ".beans.yml").write_text(f"name: {name}\n")
	return project


def test_a_repo_holding_both_markers_is_a_project(tmp_path):
	assert is_project(make_project(tmp_path, "bv"))


def test_a_beans_directory_without_a_config_is_not_a_project(tmp_path):
	(tmp_path / ".beans").mkdir()
	assert not is_project(tmp_path)


def test_a_config_without_a_beans_directory_is_not_a_project(tmp_path):
	(tmp_path / ".beans.yml").write_text("name: bv\n")
	assert not is_project(tmp_path)


def test_a_beans_file_that_is_not_a_directory_is_not_a_project(tmp_path):
	(tmp_path / ".beans.yml").write_text("name: bv\n")
	(tmp_path / ".beans").write_text("not a directory")
	assert not is_project(tmp_path)


def test_a_missing_directory_is_not_a_project(tmp_path):
	assert not is_project(tmp_path / "nope")


def test_a_root_that_is_itself_a_project_is_the_whole_board(tmp_path):
	repo = make_project(tmp_path, "bv")
	assert [(p.name, p.root) for p in projects_under(repo)] == [("bv", repo)]


def test_a_directory_of_repos_is_scanned_one_level_down(tmp_path):
	make_project(tmp_path, "demo-b")
	make_project(tmp_path, "demo-a")
	assert [p.name for p in projects_under(tmp_path)] == ["demo-a", "demo-b"]


def test_a_project_root_is_not_also_scanned_for_children(tmp_path):
	# A repo that happens to vendor another beans project shows its own beans,
	# not both -- otherwise `bv` inside a repo quietly widens to a portfolio.
	repo = make_project(tmp_path, "bv")
	make_project(repo, "vendored")
	assert [p.name for p in projects_under(repo)] == ["bv"]


def test_nothing_here_is_an_empty_board_not_a_fallback(tmp_path):
	# The decision the bean asked to be made explicitly: there is no fallback
	# to a hardcoded directory when the root holds neither shape.
	assert projects_under(tmp_path) == []


def test_the_scan_stops_at_immediate_subdirectories(tmp_path):
	# Never a recursive walk: the root is now an arbitrary working directory,
	# which can be a home directory or hold a `node_modules`.
	make_project(tmp_path / "nested", "deep")
	assert projects_under(tmp_path) == []


def test_an_unreadable_root_is_an_error_rather_than_an_empty_board(tmp_path):
	with pytest.raises(BeansError):
		discover_projects(tmp_path / "nope")
