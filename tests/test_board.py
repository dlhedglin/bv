"""Tests for the kanban board.

Split the way the module is: the bucketing and the card text are plain
functions and are tested as such, and only the parts that need a running
message pump go through `run_test`. That harness is driven through
`asyncio.run` rather than an async pytest plugin, for the reason
`test_preview.py` gives -- the venv has plain pytest and nothing else.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from textual.app import App, ComposeResult

from bv.beans import STATUS_ORDER, Bean, resolve_dependencies
from bv.board import (
	COLUMNS,
	EMPTY_COLUMN,
	MIN_CARD_WIDTH,
	TITLE_LINES,
	UNTITLED,
	BeanBoard,
	BeanCard,
	BoardColumn,
	build_columns,
	card_text,
	column_of,
	heading_text,
	meta_text,
	wrap_title,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def bean(
	id="zl4j",
	*,
	project="bv",
	title="Kanban board view",
	status="todo",
	priority="normal",
	blocked=0,
	unblocks=0,
	updated=T0,
):
	return Bean(
		project=project,
		id=f"{project}-{id}",
		title=title,
		status=status,
		type="feature",
		priority=priority,
		tags=(),
		updated_at=updated,
		parent_id=None,
		blocked_by_open=blocked,
		unblocks=unblocks,
	)


def column(columns, status):
	return next(c for c in columns if c.status == status)


# -- bucketing ------------------------------------------------------------


def test_every_status_beans_knows_about_lands_in_a_column():
	# A status with nowhere to go would drop its beans off the board without
	# any error -- the exact failure tree.py guards against for orphaned
	# parents. All five of beans' statuses have to resolve.
	for status in STATUS_ORDER:
		assert column_of(status) in COLUMNS


def test_both_views_paint_a_status_from_the_same_table():
	# There were two copies -- one here, one in app.py, which could not import
	# this module's because app.py imports it. Two definitions of one colour
	# scheme drift, and nobody notices until a theme change leaves one of them
	# unreadable. `beans.py` owns it now; both views import it.
	from bv import app, beans, board

	assert board.STATUS_STYLES is beans.STATUS_STYLES
	assert app.STATUS_STYLES is beans.STATUS_STYLES
	assert set(beans.STATUS_STYLES) == set(STATUS_ORDER)


def test_scrapped_beans_share_the_completed_column():
	columns = build_columns([bean(status="scrapped"), bean("aaaa", status="completed")])
	assert [c.status for c in columns] == list(COLUMNS)
	assert len(column(columns, "completed")) == 2


def test_a_status_outside_the_vocabulary_is_shown_rather_than_dropped():
	# beans.py substitutes "unknown" when the GraphQL row has no status. If that
	# bean had no column it would vanish silently, and the counts in the column
	# headings would quietly stop adding up to the board.
	columns = build_columns([bean(status="unknown")])
	assert sum(len(c) for c in columns) == 1
	assert len(column(columns, "todo")) == 1


def test_a_column_orders_its_beans_by_the_shared_rank():
	# Ready work -- unblocked and holding something else up -- above blocked
	# work, which is beans.rank's contract. A second sort in the board would
	# silently outrank it, the way tree.py's copy used to.
	blocked = bean("blkd", title="blocked", blocked=1, unblocks=2)
	ready = bean("redy", title="ready", unblocks=2)
	plain = bean("plan", title="plain")
	columns = build_columns([blocked, plain, ready])
	assert [b.title for b in column(columns, "todo").beans] == [
		"ready",
		"plain",
		"blocked",
	]


def test_completed_sorts_above_scrapped_inside_the_folded_column():
	columns = build_columns([bean("scrp", status="scrapped"), bean("done", status="completed")])
	assert [b.status for b in column(columns, "completed").beans] == [
		"completed",
		"scrapped",
	]


def test_two_identical_boards_compare_equal():
	# set_beans skips the whole rebuild on this comparison, so if Column or Bean
	# ever stops comparing structurally the board silently starts remounting
	# every card twice a second and loses the reader's scroll position.
	assert build_columns([bean(), bean("aaaa")]) == build_columns([bean(), bean("aaaa")])
	assert build_columns([bean()]) != build_columns([bean(title="edited")])


def test_the_board_does_not_filter_archived_beans_itself():
	# Archive hiding is the caller's decision, exactly as it already is for the
	# tree -- app.py drops them before building either view. Filtering here as
	# well would make `a` (show archived) silently do nothing on the board.
	archived = replace(bean(status="completed"), path="archive/bv-zl4j.md")
	assert archived.is_archived
	assert sum(len(c) for c in build_columns([archived])) == 1


def test_an_empty_board_still_produces_every_column():
	assert [c.status for c in build_columns([])] == list(COLUMNS)
	assert sum(len(c) for c in build_columns([])) == 0


# -- headings -------------------------------------------------------------


def test_a_column_heading_carries_its_status_and_its_count():
	columns = build_columns([bean(), bean("aaaa"), bean("bbbb", status="draft")])
	assert heading_text(column(columns, "todo")).plain == "TODO  2"


def test_an_empty_column_still_states_a_count_of_zero():
	assert heading_text(column(build_columns([]), "draft")).plain == "DRAFT  0"


# -- card text ------------------------------------------------------------


def test_a_short_title_is_padded_so_meta_lines_stay_aligned():
	assert wrap_title("short", 24) == ["short", ""]


def test_a_long_title_wraps_to_two_lines_and_says_it_was_cut():
	# Titles run to a median of 53 characters and 96 at the longest, against a
	# card ~23 wide -- truncation is the normal case, not the edge one.
	lines = wrap_title("word " * 40, 20)
	assert len(lines) == TITLE_LINES
	assert lines[-1].endswith("…")


def test_a_title_far_wider_than_the_column_still_produces_two_lines():
	lines = wrap_title("x" * 400, 14)
	assert len(lines) == TITLE_LINES
	assert all(len(line) <= 14 for line in lines)


def test_a_bean_with_no_title_gets_a_placeholder_not_a_blank_card():
	assert wrap_title("", 24)[0] == UNTITLED
	assert wrap_title("   ", 24)[0] == UNTITLED


def test_a_card_is_always_exactly_as_tall_as_the_layout_reserves():
	# The card's CSS height is fixed. An extra line would be clipped away, and
	# the line that gets clipped is the meta line -- the project and the id.
	for title in ("", "short", "word " * 40, "x" * 400):
		assert card_text(bean(title=title), 20).plain.count("\n") == TITLE_LINES


def test_a_card_names_its_project_and_the_bare_id():
	plain = meta_text(bean(project="demo-a", id="ax9v"), 40).plain
	assert "demo-a" in plain
	assert "ax9v" in plain
	# The project sits right beside it, so repeating it in the id is waste.
	assert "demo-a-ax9v" not in plain


def test_a_blocked_bean_and_a_critical_one_are_badged():
	assert "⊘" in meta_text(bean(blocked=1), 40).plain
	assert "!" in meta_text(bean(priority="critical"), 40).plain
	plain = meta_text(bean(priority="high"), 40).plain
	# 84 of 219 beans on the real board are `high`; badging them would paint
	# 38% of the board and stop meaning anything.
	assert "!" not in plain and "⊘" not in plain


def test_a_card_in_a_column_that_is_not_its_status_says_so():
	# The scrapped-into-completed fold has to be visible on the card, otherwise
	# the board reports a scrapped bean as finished work.
	assert "scrapped" in meta_text(bean(status="scrapped"), 40).plain
	assert "unknown" in meta_text(bean(status="unknown"), 40).plain
	assert "todo" not in meta_text(bean(status="todo"), 40).plain


def test_badges_survive_a_column_too_narrow_to_hold_the_project():
	# Badges lead the meta line for this reason: a clipped project name is
	# still legible, but a blocked bean whose badge got truncated away reads as
	# unblocked. Same argument app.py makes for tags against titles.
	plain = meta_text(bean(project="demo-c", blocked=1, priority="critical"), 8)
	assert "⊘" in plain.plain and "!" in plain.plain


def test_meta_text_never_exceeds_the_width_it_was_given():
	assert meta_text(bean(project="demo-c"), 12).cell_len <= 12


# -- single-project board --------------------------------------------------
#
# bv run from inside one repo. The project half of every card's meta line is
# then the same string on every card, spending the card's narrowest resource
# on nothing.


def test_a_single_project_card_drops_the_project_and_keeps_the_id():
	plain = meta_text(bean(project="demo-a", id="ax9v"), 40, show_project=False).plain
	assert "demo-a" not in plain
	assert "ax9v" in plain


def test_a_single_project_card_keeps_its_badges():
	plain = meta_text(bean(blocked=1, priority="critical"), 40, show_project=False).plain
	assert "⊘" in plain and "!" in plain


def test_card_text_passes_the_choice_through():
	assert "demo-a" not in card_text(bean(project="demo-a"), 40, show_project=False).plain
	assert "demo-a" in card_text(bean(project="demo-a"), 40).plain


# -- widget ---------------------------------------------------------------


class BoardApp(App):
	"""Throwaway host so the board can be exercised headlessly."""

	def compose(self) -> ComposeResult:
		yield BeanBoard()


def board_test(scenario):
	"""Run an async test body against a freshly mounted board.

	Deliberately not `functools.wraps`, for the reason test_preview.py gives:
	pytest follows `__wrapped__` and then hunts for fixtures named after the
	scenario's parameters.
	"""

	def run() -> None:
		async def main() -> None:
			app = BoardApp()
			async with app.run_test(size=(120, 40)) as pilot:
				await scenario(app.query_one(BeanBoard), pilot)

		asyncio.run(main())

	run.__name__ = scenario.__name__
	run.__doc__ = scenario.__doc__
	return run


def many(count, *, status="todo", project="bv"):
	"""A column's worth of beans that rank in the order they are written.

	Every field `beans.rank` looks at is identical, so the tie breaks on title
	-- which is why the titles are zero-padded. Unpadded, "Bean 10" sorts
	between "Bean 1" and "Bean 2" and every positional assertion below lies.
	"""
	return [
		Bean(
			project=project,
			id=f"{project}-{index:04d}",
			title=f"Bean number {index:04d}",
			status=status,
			type="task",
			priority="normal",
			tags=(),
			updated_at=T0,
			parent_id=None,
		)
		for index in range(count)
	]


def cards(board, status):
	return next(c for c in board.query(BoardColumn) if c.status == status).cards


@board_test
async def test_the_board_mounts_one_column_per_status(board, pilot):
	board.set_beans([])
	await pilot.pause()
	assert [c.status for c in board.query(BoardColumn)] == list(COLUMNS)


@board_test
async def test_an_empty_column_still_renders_its_heading(board, pilot):
	board.set_beans([bean(status="in-progress")])
	await pilot.pause()
	draft = next(c for c in board.query(BoardColumn) if c.status == "draft")
	assert draft.cards == []
	assert "DRAFT  0" in draft._heading.content.plain
	# A blank column and a column that has not loaded yet must not look alike.
	assert draft._empty.display
	assert str(draft._empty.content) == EMPTY_COLUMN


@board_test
async def test_a_column_with_a_card_hides_the_empty_placeholder(board, pilot):
	board.set_beans([bean()])
	await pilot.pause()
	todo = next(c for c in board.query(BoardColumn) if c.status == "todo")
	assert not todo._empty.display
	assert len(todo.cards) == 1


@board_test
async def test_the_first_bean_of_the_first_column_is_selected_on_load(board, pilot):
	board.set_beans([bean("aaaa", status="in-progress"), bean("bbbb")])
	await pilot.pause()
	assert board.selected.id == "bv-aaaa"


@board_test
async def test_j_and_k_move_within_a_column_and_stop_at_its_ends(board, pilot):
	board.set_beans(many(3))
	await pilot.pause()
	assert board.selected.id == "bv-0000"
	await pilot.press("j", "j")
	assert board.selected.id == "bv-0002"
	# Clamped, not wrapped: falling off the bottom of a column into the top of
	# the next one is disorienting in a spatial layout.
	await pilot.press("j", "j")
	assert board.selected.id == "bv-0002"
	await pilot.press("k", "k", "k", "k")
	assert board.selected.id == "bv-0000"


@board_test
async def test_h_and_l_move_between_columns(board, pilot):
	board.set_beans([bean("aaaa", status="in-progress"), bean("bbbb"), bean("cccc", status="draft")])
	await pilot.pause()
	await pilot.press("l")
	assert board.selected.id == "bv-bbbb"
	await pilot.press("l")
	assert board.selected.id == "bv-cccc"
	await pilot.press("h", "h")
	assert board.selected.id == "bv-aaaa"
	await pilot.press("h")
	assert board.selected.id == "bv-aaaa"


@board_test
async def test_each_column_remembers_where_you_were_in_it(board, pilot):
	# in-progress has 18 cards on the real board and todo has 107. Carrying one
	# row index across both would clamp the todo position to 17 on every trip
	# to in-progress and back.
	board.set_beans(many(3, status="in-progress") + many(30))
	await pilot.pause()
	await pilot.press("l")
	for _ in range(20):
		await pilot.press("j")
	assert board.selected.id == "bv-0020"
	await pilot.press("h")
	assert board.selected.id == "bv-0000"
	await pilot.press("l")
	assert board.selected.id == "bv-0020"


@board_test
async def test_moving_into_an_empty_column_selects_nothing_rather_than_refusing(board, pilot):
	board.set_beans([bean(status="in-progress"), bean("aaaa", status="completed")])
	await pilot.pause()
	await pilot.press("l")
	assert board.selected is None
	await pilot.press("l", "l")
	assert board.selected.id == "bv-aaaa"


@board_test
async def test_the_selected_card_is_the_only_one_marked(board, pilot):
	board.set_beans(many(5))
	await pilot.pause()
	await pilot.press("j", "j")
	marked = [c for c in board.query(BeanCard) if c.has_class("-selected")]
	assert [c.bean.id for c in marked] == ["bv-0002"]


@board_test
async def test_the_cursor_follows_a_bean_that_changes_column(board, pilot):
	# A watch refresh can land while you are looking at the bean that moved.
	# Restoring by position would leave the cursor on whatever slid into its
	# old slot, which is a different bean with no warning.
	parked = bean("zzzz", title="Already in progress", status="in-progress")
	moving = bean("aaaa", title="About to be picked up")
	board.set_beans([parked, moving])
	await pilot.pause()
	await pilot.press("l")
	assert board.selected.id == "bv-aaaa"

	board.set_beans([parked, replace(moving, status="in-progress")])
	await pilot.pause()
	assert board.selected.id == "bv-aaaa"
	assert cards(board, "todo") == []


@board_test
async def test_a_bean_that_disappears_leaves_the_cursor_on_its_neighbour(board, pilot):
	board.set_beans(many(5))
	await pilot.pause()
	await pilot.press("j", "j", "j", "j")
	assert board.selected.id == "bv-0004"
	board.set_beans(many(3))
	await pilot.pause()
	# Clamped into the shortened column rather than snapped back to the top.
	assert board.selected.id == "bv-0002"


@board_test
async def test_a_rebuild_deep_in_a_column_does_not_move_the_reader(board, pilot):
	# The board is rebuilt on every auto-refresh, roughly twice a second while
	# files are changing. Clearing and remounting the cards would reset every
	# column's scroll offset to zero each time and make a 107-card column
	# unreadable. This is the same bug preview.py already fixed once.
	items = many(60)
	board.set_beans(items)
	await pilot.pause()
	for _ in range(40):
		await pilot.press("j")
	await pilot.pause()
	scrolled = cards(board, "todo")[0].parent.scroll_offset.y
	assert scrolled > 0

	# A real refresh: one bean somewhere else in the column picked up an edit.
	edited = [*items[:5], replace(items[5], body="now has a body"), *items[6:]]
	board.set_beans(edited)
	await pilot.pause()
	assert board.selected.id == "bv-0040"
	assert cards(board, "todo")[0].parent.scroll_offset.y == scrolled


@board_test
async def test_an_unchanged_board_is_not_rebuilt_at_all(board, pilot):
	board.set_beans(many(60))
	await pilot.pause()
	before = list(board.query(BeanCard))
	board.set_beans(many(60))
	await pilot.pause()
	# Same widget objects, so nothing was remounted and no scroll was reset.
	assert list(board.query(BeanCard)) == before


@board_test
async def test_the_selected_card_is_scrolled_into_view(board, pilot):
	board.set_beans(many(60))
	await pilot.pause()
	container = cards(board, "todo")[0].parent
	assert container.scroll_offset.y == 0
	for _ in range(30):
		await pilot.press("j")
	await pilot.pause()
	assert container.scroll_offset.y > 0


@board_test
async def test_a_column_of_a_hundred_cards_mounts_and_stays_navigable(board, pilot):
	# todo holds 107 cards on the real board; that is the column that decides
	# whether the design works at all.
	board.set_beans(many(107))
	await pilot.pause()
	assert len(cards(board, "todo")) == 107
	await pilot.press("j")
	assert board.selected.id == "bv-0001"


@board_test
async def test_clicking_a_card_selects_it(board, pilot):
	board.set_beans(many(4))
	await pilot.pause()
	await pilot.click(cards(board, "todo")[2])
	assert board.selected.id == "bv-0002"


class RecordingApp(App):
	"""Host that logs the board's Selected messages under the handler name
	app.py will actually implement."""

	def __init__(self) -> None:
		super().__init__()
		self.seen: list[str | None] = []

	def compose(self) -> ComposeResult:
		yield BeanBoard()

	def on_bean_board_selected(self, message: BeanBoard.Selected) -> None:
		self.seen.append(message.bean.id if message.bean else None)


def test_the_board_announces_a_selection_only_when_it_changes():
	# The app hangs the preview pane off this message, and the board is
	# re-applied twice a second. Announcing on every apply would have the
	# preview re-checking an unmoved bean continuously.
	async def main() -> None:
		app = RecordingApp()
		async with app.run_test(size=(120, 40)) as pilot:
			board = app.query_one(BeanBoard)
			items = many(3)
			board.set_beans(items)
			await pilot.pause()
			assert app.seen == ["bv-0000"]

			await pilot.press("j")
			await pilot.pause()
			assert app.seen == ["bv-0000", "bv-0001"]

			board.set_beans([*items[:2], replace(items[2], body="edited")])
			await pilot.pause()
			assert app.seen == ["bv-0000", "bv-0001"]

	asyncio.run(main())


def test_beans_set_before_mount_are_rendered_on_mount():
	# app.py loads in a worker; the first set_beans can land before the widget
	# has been composed.
	class Preloaded(App):
		def compose(self) -> ComposeResult:
			board = BeanBoard()
			board.set_beans([bean(status="in-progress")])
			yield board

	async def main() -> None:
		app = Preloaded()
		async with app.run_test(size=(120, 40)) as pilot:
			await pilot.pause()
			board = app.query_one(BeanBoard)
			assert board.selected is not None
			assert board.selected.id == "bv-zl4j"
			assert len(cards(board, "in-progress")) == 1

	asyncio.run(main())


def test_a_narrow_terminal_still_renders_cards():
	# Four columns in 40 characters leaves each card below the width textwrap
	# will accept; the floor has to catch it rather than raising.
	async def main() -> None:
		app = BoardApp()
		async with app.run_test(size=(40, 20)) as pilot:
			board = app.query_one(BeanBoard)
			board.set_beans([bean(title="A title far wider than this column")])
			await pilot.pause()
			assert len(cards(board, "todo")) == 1

	asyncio.run(main())


def test_dependencies_resolved_by_beans_reach_the_card():
	# is_blocked is filled in by resolve_dependencies across the whole board,
	# not by a single bean, so the badge depends on the caller having run it.
	blocker = bean("blkr", status="todo")
	blocked = Bean(
		project="bv",
		id="bv-blkd",
		title="Blocked",
		status="todo",
		type="task",
		priority="normal",
		tags=(),
		updated_at=T0,
		parent_id=None,
		blocked_by_ids=("bv-blkr",),
	)
	resolved = {b.id: b for b in resolve_dependencies([blocker, blocked])}
	assert "⊘" in meta_text(resolved["bv-blkd"], 40).plain
	assert "⊘" not in meta_text(resolved["bv-blkr"], 40).plain


@board_test
async def test_flipping_to_a_single_project_board_repaints_the_cards(board, pilot):
	"""The skip-if-nothing-moved check has to count `show_project`.

	A root that gains a `.beans` directory mid-session becomes a flat board
	without a single bean changing, and the cards would otherwise go on naming
	a project that the rest of the app has stopped showing.
	"""
	beans = [bean(project="demo-a")]
	board.set_beans(beans)
	await pilot.pause()
	assert "demo-a" in cards(board, "todo")[0].content.plain

	board.set_beans(beans, show_project=False)
	await pilot.pause()
	assert "demo-a" not in cards(board, "todo")[0].content.plain


@board_test
async def test_a_resize_does_not_bring_the_project_back(board, pilot):
	# `refit` re-renders every card, so it has to be told the same thing
	# `set_beans` was.
	board.set_beans([bean(project="demo-a")], show_project=False)
	await pilot.pause()
	board._width = 0  # force on_resize past its own no-op check
	board.on_resize()
	await pilot.pause()
	assert "demo-a" not in cards(board, "todo")[0].content.plain


@board_test
async def test_cards_mounted_after_the_first_paint_follow_the_same_rule(board, pilot):
	# The mount path and the reuse path are separate lines in `BoardColumn.show`.
	board.set_beans([bean(project="demo-a")], show_project=False)
	await pilot.pause()
	board.set_beans(many(4, project="demo-a"), show_project=False)
	await pilot.pause()
	assert all("demo-a" not in card.content.plain for card in cards(board, "todo"))


@board_test
async def test_cards_re_expand_after_the_terminal_grows_back(board, pilot):
	# bv-41rc's grow-back case for the kanban board: shrink the terminal, then
	# grow it, and assert the cards reclaim their width rather than staying
	# pinned narrow -- the existing suite only proved the no-op guard can be
	# bypassed, not that a real grow is honoured. The board tracks this off its
	# own (settled-size) resize, unlike the tree's DataTable; see test_app.
	async def settle(width):
		# resize_terminal takes a couple of frames to reach the board; pump
		# until the re-wrap has run.
		await pilot.resize_terminal(width, 40)
		for _ in range(3):
			await pilot.pause()

	board.set_beans(many(4), show_project=False)
	await pilot.pause()
	full = board._width
	assert full > MIN_CARD_WIDTH  # the 120-col harness has room to spare

	await settle(60)
	assert board._width < full

	await settle(120)
	assert board._width == full
