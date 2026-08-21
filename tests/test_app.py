"""Tests for the seams between the app's two views.

The table stays mounted while the board is showing -- removing it would turn
every action that reaches for it with a bare `query_one` into a `NoMatches`
traceback -- so it is hidden instead. That makes "focus the table" and "focus
what the user is looking at" two different things, and confusing them fails
invisibly: the keyboard goes to a widget that is not on screen and every
keypress after that is silently swallowed.

These run against an empty board. Nothing here depends on real beans, because
the bugs are in which widget has focus, not in what it contains.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from textual.widgets import DataTable, Input

from bv.agents import Session
from bv.app import BeansViewer, resolve_root
from bv.beans import Bean
from bv.board import BeanBoard, BeanCard
from bv.mission import MissionControl
from bv.preview import BeanPreview

Scenario = Callable[[BeansViewer, object], Awaitable[None]]


def drive(root: Path, scenario: Scenario) -> None:
	"""Run `scenario` against a mounted app rooted at `root`.

	`XDG_CONFIG_HOME` is redirected first. bv persists the theme, fold state
	and the archive toggle, and a test suite must never write to the config of
	whoever is running it.
	"""
	import os

	home = root / "config-home"
	home.mkdir(parents=True, exist_ok=True)
	previous = os.environ.get("XDG_CONFIG_HOME")
	os.environ["XDG_CONFIG_HOME"] = str(home)

	async def main() -> None:
		app = BeansViewer(root=root)
		async with app.run_test(size=(120, 30)) as pilot:
			await pilot.pause()
			await scenario(app, pilot)

	try:
		asyncio.run(main())
	finally:
		if previous is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = previous


def test_filtering_on_the_board_leaves_focus_on_the_board(tmp_path):
	"""bv-ndrn. Focus went to the hidden table, stranding the user.

	If this regresses, `/` on the board silently disables h/j/k/l and the only
	way out is pressing `b` twice.
	"""

	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		assert isinstance(app.focused, BeanBoard)

		await pilot.press("slash")
		await pilot.pause()
		assert isinstance(app.focused, Input)

		await pilot.press("enter")
		await pilot.pause()
		assert isinstance(app.focused, BeanBoard), f"focus went to {type(app.focused).__name__}, not the board"

	drive(tmp_path, scenario)


def test_clearing_a_filter_on_the_board_leaves_focus_on_the_board(tmp_path):
	# escape is the other way out of the filter, and had the same bug.
	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		await pilot.press("slash")
		await pilot.pause()
		await pilot.press("escape")
		await pilot.pause()
		assert isinstance(app.focused, BeanBoard)

	drive(tmp_path, scenario)


def test_filtering_on_the_tree_still_returns_focus_to_the_table(tmp_path):
	# The original behaviour, which the fix must not trade away.
	async def scenario(app, pilot):
		await pilot.press("slash")
		await pilot.pause()
		await pilot.press("enter")
		await pilot.pause()
		assert isinstance(app.focused, DataTable)

	drive(tmp_path, scenario)


def test_the_table_stays_mounted_while_the_board_shows(tmp_path):
	"""Hidden, never removed.

	Nearly every action reaches for the table with a bare `query_one`, so
	removing it would raise NoMatches on the next fold key.
	"""

	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		assert app.query_one(DataTable).has_class("hidden")
		# Keys that only mean something on the tree must not raise while the
		# board is up.
		for key in ("space", "C", "E", "P", "g", "G"):
			await pilot.press(key)
			await pilot.pause()

	drive(tmp_path, scenario)


TREE_ONLY_KEYS = ("space", "C", "E", "P", "g", "G")
"""The keys that drive the table and mean nothing to the board."""


def test_the_board_neither_offers_nor_fires_the_trees_keys(tmp_path):
	"""bv-te9w. They were live no-ops, and the footer went on advertising them.

	Both halves are checked, because either alone is a lie: a key that fires
	invisibly is a broken app, and a footer promising "Fold" to a view with no
	folds is a broken promise.
	"""

	async def scenario(app, pilot):
		for key in TREE_ONLY_KEYS:
			assert key in app.screen.active_bindings, f"{key} missing from the tree"

		await pilot.press("b")
		await pilot.pause()
		for key in TREE_ONLY_KEYS:
			assert key not in app.screen.active_bindings, f"the footer still offers {key} on the board"
		# `check_action` gates the dispatch as well as the display, so the key
		# is refused rather than quietly handled by the hidden table.
		for action in ("fold", "collapse_all", "expand_all", "projects_only"):
			assert await app.run_action(action) is False, f"{action} still fired"

	drive(tmp_path, scenario)


def test_the_keys_come_back_when_the_tree_does(tmp_path):
	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		await pilot.press("b")
		await pilot.pause()
		for key in TREE_ONLY_KEYS:
			assert key in app.screen.active_bindings, f"{key} did not come back"
		assert await app.run_action("fold") is True

	drive(tmp_path, scenario)


def test_the_keys_that_work_in_both_views_survive_the_gate(tmp_path):
	# The gate is per-action, not per-view: filtering, reloading, the archive
	# toggle and spawning all still mean something on the board.
	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		for key in ("slash", "r", "w", "a", "S", "b", "p", "q"):
			assert key in app.screen.active_bindings, f"the board lost {key}"

	drive(tmp_path, scenario)


def test_toggling_back_returns_focus_to_the_table(tmp_path):
	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		await pilot.press("b")
		await pilot.pause()
		assert isinstance(app.focused, DataTable)
		assert not app.query_one(DataTable).has_class("hidden")
		assert app.query_one(BeanBoard).has_class("hidden")

	drive(tmp_path, scenario)


def test_the_title_column_re_expands_after_the_terminal_grows_back(tmp_path):
	"""bv-41rc. Shrink-then-grow left Title pinned at its shrunken width.

	on_resize measured the table before its new size had settled, so a
	grow-back recomputed the old (narrow) room, hit `_fit_title_column`'s no-op
	guard, and never re-widened. Assert the reclaimed width is honoured.
	"""
	from bv.app import MIN_TITLE_WIDTH

	async def settle(pilot, width):
		# resize_terminal takes a couple of frames to reach the DataTable, whose
		# own resize then drives the refit; pump enough for both to land.
		await pilot.resize_terminal(width, 30)
		for _ in range(4):
			await pilot.pause()

	async def scenario(app, pilot):
		# Hide the preview and go wide, so Title has real room past the fixed
		# columns -- the wide-board case the bean is about.
		await pilot.press("p")
		await pilot.pause()
		await settle(pilot, 200)
		full = app._title_width
		assert full > MIN_TITLE_WIDTH

		await settle(pilot, 100)
		assert app._title_width < full

		await settle(pilot, 200)
		assert app._title_width == full

	drive(tmp_path, scenario)


# -- the preview's delayed render -----------------------------------------


def _bean(id: str, body: str = "A body.", project: str = "bv", status: str = "todo") -> Bean:
	return Bean(
		project=project,
		id=id,
		title="A bean",
		status=status,
		type="feature",
		priority="normal",
		tags=(),
		updated_at=datetime(2026, 1, 1, tzinfo=UTC),
		parent_id=None,
		body=body,
	)


# -- which board the root resolves to --------------------------------------
#
# The root is wherever bv was run. A root that is itself a beans project is
# the whole board and is shown flat; a root that is not is a directory of
# repos, grouped by project. Every place the project is surfaced has to agree
# with which of the two it is, or a one-project board repeats the same string
# on every row and offers a `P` with nothing to collapse to.


def make_project(parent: Path, name: str) -> Path:
	project = parent / name
	(project / ".beans").mkdir(parents=True)
	(project / ".beans.yml").write_text(f"name: {name}\n")
	return project


def canned(monkeypatch, beans) -> None:
	"""Stub the load, keeping the on-disk markers real.

	`is_project` reads the filesystem and is the thing under test here, but
	`load_all` shells out to the `beans` CLI -- leaving that live would make
	these tests about whatever is installed on the machine.
	"""
	monkeypatch.setattr("bv.app.load_all", lambda _root: (list(beans), []))


def test_a_root_that_is_a_repo_shows_its_beans_with_no_project_heading(tmp_path, monkeypatch):
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa"), _bean("bv-bbbb")])

	async def scenario(app, pilot):
		assert app._flat
		assert [node.key for node in app._rows] == ["bv-aaaa", "bv-bbbb"]
		assert not any(node.is_project for node in app._rows)

	drive(root, scenario)


def test_a_root_of_repos_still_groups_by_project(tmp_path, monkeypatch):
	make_project(tmp_path, "demo-a")
	canned(monkeypatch, [_bean("demo-a-aaaa", project="demo-a")])

	async def scenario(app, pilot):
		assert not app._flat
		assert [node.key for node in app._rows] == ["demo-a", "demo-a-aaaa"]

	drive(tmp_path, scenario)


def test_a_flat_board_neither_offers_nor_fires_collapse_to_projects(tmp_path, monkeypatch):
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa")])

	async def scenario(app, pilot):
		assert "P" not in app.screen.active_bindings, "the footer offers Projects on a board with none"
		assert await app.run_action("projects_only") is False
		# The other fold keys still mean something: the beans nest under each
		# other whether or not there is a project layer above them.
		for key in ("space", "C", "E"):
			assert key in app.screen.active_bindings

	drive(root, scenario)


def test_a_grouped_board_keeps_collapse_to_projects(tmp_path, monkeypatch):
	make_project(tmp_path, "demo-a")
	canned(monkeypatch, [_bean("demo-a-aaaa", project="demo-a")])

	async def scenario(app, pilot):
		assert "P" in app.screen.active_bindings
		assert await app.run_action("projects_only") is True

	drive(tmp_path, scenario)


def test_a_flat_status_bar_does_not_say_one_projects(tmp_path, monkeypatch):
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa")])

	async def scenario(app, pilot):
		assert "projects" not in app.sub_title
		assert "1 beans" in app.sub_title

	drive(root, scenario)


def test_a_grouped_status_bar_still_counts_projects(tmp_path, monkeypatch):
	make_project(tmp_path, "demo-a")
	canned(monkeypatch, [_bean("demo-a-aaaa", project="demo-a")])

	async def scenario(app, pilot):
		assert "1 projects" in app.sub_title

	drive(tmp_path, scenario)


def test_a_flat_board_drops_the_project_from_its_cards(tmp_path, monkeypatch):
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa")])

	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		card = next(iter(app.query(BeanCard)))
		assert "bv" not in card.content.plain.split("\n")[-1]

	drive(root, scenario)


def test_the_project_root_is_the_board_root_when_the_board_is_flat(tmp_path, monkeypatch):
	"""What a dispatched agent's working directory is built from.

	`self.root / bean.project` pointed at a subdirectory that does not exist on
	a flat board -- a wrong cwd for an agent and a permanently empty Agent
	column, neither of which announces itself.
	"""
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa")])

	async def scenario(app, pilot):
		assert app._project_root("bv") == root

	drive(root, scenario)


def test_the_project_root_is_a_subdirectory_when_the_board_is_grouped(tmp_path, monkeypatch):
	make_project(tmp_path, "demo-a")
	canned(monkeypatch, [_bean("demo-a-aaaa", project="demo-a")])

	async def scenario(app, pilot):
		assert app._project_root("demo-a") == tmp_path / "demo-a"

	drive(tmp_path, scenario)


def test_a_root_that_becomes_a_repo_mid_session_flips_without_a_restart(tmp_path, monkeypatch):
	"""`beans init` in the root. The footer is built from `check_action`, and
	nothing about a new `.beans` directory tells it to ask again."""
	canned(monkeypatch, [_bean("bv-aaaa")])

	async def scenario(app, pilot):
		assert not app._flat
		(tmp_path / ".beans").mkdir()
		(tmp_path / ".beans.yml").write_text("name: bv\n")

		await pilot.press("r")
		await pilot.pause()
		assert app._flat
		assert "P" not in app.screen.active_bindings

	drive(tmp_path, scenario)


# -- resolving the root ----------------------------------------------------


def test_a_bare_bv_uses_the_working_directory(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	assert resolve_root(None) == tmp_path.resolve()


def test_an_explicit_relative_root_resolves_to_the_same_string_as_a_bare_bv(tmp_path, monkeypatch):
	# Fold state is keyed by the root's string; `bv` and `bv .` are one board.
	monkeypatch.chdir(tmp_path)
	assert resolve_root(Path(".")) == resolve_root(None)


def test_a_tilde_root_is_still_expanded(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))
	assert resolve_root(Path("~/repos")) == (tmp_path / "repos").resolve()


# -- the Agent column repaints when a session moves, not only when it appears --


def test_a_same_bean_state_change_repaints_the_agent_cell(tmp_path, monkeypatch):
	"""bv-ov50. `_refresh_sessions` compared only `{bean_id: label}`, so a
	session going working->blocked on the same bean was not detected as a
	change -- the poll skipped the render and the cell kept its stale green
	while `_agent_text` was already colouring blocked sessions yellow."""
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa")])

	state = {"value": "working"}

	def fake_load_sessions(*_args, **_kwargs):
		# The bean id is in the name, so this attributes exactly regardless of
		# cwd or the bean's status.
		return [Session(short="aaaa", name="bv-aaaa work", state=state["value"], cwd=str(root), live=True)]

	monkeypatch.setattr("bv.app.load_sessions", fake_load_sessions)

	async def scenario(app, pilot):
		# The load-time refresh has already attributed the working session.
		assert app._working["bv-aaaa"].session.state == "working"

		state["value"] = "blocked"
		assert app._refresh_sessions() is True, "a same-bean working->blocked move went undetected"
		assert app._working["bv-aaaa"].session.state == "blocked"

	drive(root, scenario)


def test_hiding_the_preview_cancels_a_pending_render(tmp_path):
	"""bv-4pli. `p` must not leave a timer pointed at a pane that is gone."""

	async def scenario(app, pilot):
		preview = app.query_one(BeanPreview)
		preview.show(_bean("bv-zzzz"))
		assert preview.is_pending

		await pilot.press("p")
		await pilot.pause()
		assert preview.has_class("hidden")
		assert not preview.is_pending

	drive(tmp_path, scenario)


# -- the status bar counts the visible beans, not the archived ones -------
#
# `_summarize` is fed a bean list by its caller, and every caller must pass
# `self._visible_beans()`. bv-0ejt: `action_toggle_watch`, `action_clear_filter`
# and `on_input_changed` passed the raw `self._beans` instead, so the summary
# counted archived beans the board hides -- and in the same line called them
# "archived hidden". These guard against that regressing.


def _archived(id: str, **kwargs) -> Bean:
	"""A bean sitting in `.beans/archive/`, hidden until `a` reveals it.

	`is_archived` is read off the path, the only marker an archived bean
	carries -- there is no field for it.
	"""
	return replace(_bean(id, **kwargs), path=f"archive/{id}.md")


def test_pausing_the_watch_counts_only_the_visible_beans(tmp_path, monkeypatch):
	"""bv-6t3w review finding. `action_toggle_watch` summarised over
	`self._beans`, so pausing the watch made the bean count jump to include the
	archived beans the board hides -- while the same line still said they were
	"archived hidden"."""
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa"), _bean("bv-bbbb"), _archived("bv-cccc")])

	async def scenario(app, pilot):
		assert not app._show_archived
		# The load path is already correct: two visible beans, one hidden.
		assert "2 beans" in app.sub_title, app.sub_title

		await pilot.press("w")  # pause -> re-summarise via the buggy caller
		await pilot.pause()
		assert "2 beans" in app.sub_title, app.sub_title
		assert "3 beans" not in app.sub_title, app.sub_title

	drive(root, scenario)


def test_the_filter_denominator_counts_only_the_visible_beans(tmp_path, monkeypatch):
	"""bv-6t3w review finding. `on_input_changed` summarised over `self._beans`,
	so the "N of M" filter denominator counted archived beans the filter can
	never surface."""
	root = make_project(tmp_path, "bv")
	canned(monkeypatch, [_bean("bv-aaaa"), _bean("bv-bbbb"), _archived("bv-cccc")])

	async def scenario(app, pilot):
		await pilot.press("slash")
		await pilot.pause()
		for char in "bean":  # matches the shared "A bean" title of all three
			await pilot.press(char)
		await pilot.pause()
		# Two visible beans match; the archived third is not a candidate.
		assert "2 of 2 beans" in app.sub_title, app.sub_title
		assert "of 3" not in app.sub_title, app.sub_title

	drive(root, scenario)


def test_scrolling_the_preview_renders_whatever_is_waiting(tmp_path):
	"""The delay must not turn ctrl+f into a lock.

	Scrolling a pane that is still a bean behind would page through the wrong
	document and then be undone by the render landing on top of it.
	"""

	async def scenario(app, pilot):
		preview = app.query_one(BeanPreview)
		preview.show(_bean("bv-zzzz", body="paragraph\n\n" * 200))
		assert preview.is_pending

		await pilot.press("ctrl+f")
		await pilot.pause()
		assert not preview.is_pending
		assert preview.bean.id == "bv-zzzz"

		# And the keys still move the pane once it is showing.
		await pilot.press("ctrl+f")
		await pilot.pause()
		assert preview.scroll_offset.y > 0

		await pilot.press("ctrl+b")
		await pilot.pause()
		assert preview.scroll_offset.y == 0

	drive(tmp_path, scenario)


def test_pressing_m_opens_mission_control_for_the_project(tmp_path):
	"""bv-9gnt. `m` opens the agent grid for the project under the cursor."""

	async def scenario(app, pilot):
		# The board is empty here, so stand in for "cursor is on a project".
		app._current_project = lambda: "demo"
		await pilot.press("m")
		await pilot.pause()
		await pilot.pause()
		assert isinstance(app.screen, MissionControl)
		await pilot.press("escape")
		await pilot.pause()
		assert not isinstance(app.screen, MissionControl)

	drive(tmp_path, scenario)


def test_mission_control_bells_when_the_cursor_is_on_no_project(tmp_path):
	"""No project under the cursor is a no-op, not a pushed empty screen."""

	async def scenario(app, pilot):
		app._current_project = lambda: None
		await pilot.press("m")
		await pilot.pause()
		assert not any(isinstance(s, MissionControl) for s in app.screen_stack)

	drive(tmp_path, scenario)
