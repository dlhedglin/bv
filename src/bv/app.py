"""bv -- a terminal viewer for beans issues, across every repo at once.

`beans tui` resolves a single `.beans.yml` by searching upward from the
working directory, so it can only ever show you one project. bv addresses
projects explicitly instead, which lets it put the whole portfolio on one
screen.

The board root is the working directory bv was run from, and what it shows is
decided by what is actually there. A root that is itself a beans project is
the whole board, shown *flat*: no project headings, no project on a card, no
project count in the status bar and nothing for `P` to collapse to, because
every one of those surfaces the same string over and over when there is one
project. A root that is not scans one level down and groups by project. There
is no fallback to a hardcoded directory -- a root holding neither is an empty
board that says so, which is the honest answer for anyone whose machine is not
laid out like the author's.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static

from .agents import Attribution, Session, attribute_all, load_sessions, resolved
from .agents import session_within as _session_within
from .beans import PRIORITY_ORDER, STATUS_ORDER, STATUS_STYLES, Bean, is_project, load_all
from .board import BeanBoard, worktree_cell
from .clipboard import copy, yank_id, yank_line
from .config import (
	Settings,
	load_settings,
	save_collapsed,
	save_show_archived,
	save_theme,
)
from .dispatch import (
	ConfirmDispatch,
	DispatchRequest,
	PickBase,
	already_working,
	branch_for,
	can_dispatch,
	current_branch,
	dispatch,
	local_branches,
	recorded_base,
	request_for,
	review_request_for,
)
from .edit import archive_argv, custom_frontmatter_keys, run_edit, update_argv
from .editui import CLEAR, ChoiceScreen, PromptScreen
from .mission import MissionControl
from .preview import BeanPreview
from .tree import (
	Node,
	build_forest,
	collapsible_keys,
	filter_forest,
	project_keys,
	summarize,
	visible_rows,
)
from .watch import Watcher
from .worktree import NONE as WT_NONE
from .worktree import READY as WT_READY
from .worktree import (
	has_own_commits,
	merged_verdict,
	remove_worktree,
	worktree_dirty,
	worktree_states,
)

PRIORITY_STYLES = {
	"critical": "bold red",
	"high": "red",
	"normal": "",
	"low": "dim",
	"deferred": "dim",
}

FINISHED_STATUSES = frozenset({"completed", "scrapped"})
"""The two statuses `beans archive` sweeps into `.beans/archive/`. Named here so
the archive action can count what a sweep would move before running it."""

TYPE_STYLES = {
	"milestone": "bold magenta",
	"epic": "magenta",
	"feature": "blue",
	"bug": "red",
	"task": "",
}

TYPE_ORDER = tuple(TYPE_STYLES)
"""The bean types `beans update --type` accepts, in the order the type picker
offers them. Derived from `TYPE_STYLES` so the two never drift."""

EXPANDED, COLLAPSED, LEAF = "▾ ", "▸ ", "  "
INDENT = "  "

RAIL = "▌ "
"""Left rail on a project heading. A background fill would be the obvious way
to make headings stand out, but Rich paints a cell's style only where there is
text -- a heading whose other columns are empty renders as disconnected blocks
with gaps. A glyph, an accent colour and a blank line are what actually read."""

G_SEQUENCE_TIMEOUT = 0.6
"""How long a lone `g` waits for its partner before giving up, mirroring vim's
timeoutlen."""

MAX_TAGS = 3
"""Tags shown inline before eliding to a `+N` marker, so a heavily tagged bean
cannot push its own title off the screen."""

NOTIFY_WIDTH = 56
"""How much of a yank the "copied …" toast quotes back.

A `Y` on the longest real title is 96 characters plus the id and status, and a
toast that wraps to three lines to echo something the user is about to paste
anyway is a notification shouting. The head is the half that identifies it."""


def _ellipsize(text: str, width: int) -> str:
	return text if len(text) <= width else f"{text[: width - 1]}…"


TREE_ONLY_ACTIONS = frozenset({"fold", "collapse_all", "expand_all", "projects_only", "goto_top", "goto_bottom"})
"""Actions that only mean something on the tree.

Every one of them drives the `DataTable`, and the table stays mounted while the
board is showing -- see `compose` -- so none of them raise. They were silent
no-ops instead, which is worse in the one way a keyboard UI cannot afford: the
footer went on advertising "Fold" and "Collapse all" to a view that has no
folds, and pressing them looked like a broken app rather than a wrong key.

Gated through `check_action` rather than by an early return in each handler, so
the footer and the key agree by construction. `False` is Textual's
disabled-*and*-hidden verdict (8.2.8), which is the honest one here: these are
not temporarily unavailable, they are not part of this view.

Not listed: `move`, `half_page` and the preview keys. Those exist in both views
-- the board binds its own `j`/`k`/`ctrl+d`/`ctrl+u`, which win while it has
focus because bindings resolve from the focused widget outwards."""

FLAT_ONLY_HIDDEN_ACTIONS = frozenset({"projects_only"})
"""Actions with nothing left to do on a single-project board.

`P` collapses to the project headings, and a flat board has none -- see
`tree.build_forest`. Hidden through the same `check_action` gate as
TREE_ONLY_ACTIONS, and for the same reason: a footer that goes on offering
"Projects" to a view with no projects is a broken promise, and a key that
fires invisibly is a broken app."""


# Type, priority and status are closed vocabularies, so their columns have a
# width that is knowable up front -- and an id is always a 4-character suffix.
# Titles are the only unbounded field. DataTable auto-sizes a column to its
# widest cell, which was harmless while Title ended the row, but Title now leads
# and an unbounded lead column shoves everything after it off the right edge.
# So: pin the four predictable columns to their vocabularies and give Title the
# remainder. Derived rather than hand-counted, so adding a longer status to
# beans.STATUS_ORDER widens the column instead of silently clipping it.
def _widest(words: Iterable[str], label: str) -> int:
	return max(len(word) for word in (*words, label))


BLOCKED_YES, BLOCKED_NO = "yes", "no"

AGENT_WIDTH = 16
"""Width of the Agent column. Session names are free text and run long --
"Analyze photography lighting and aesthetic techniques" is a real one -- so
this is a cap, not a measurement like the other metadata columns."""

META_WIDTHS = {
	"type": _widest(TYPE_STYLES, "Type"),
	"priority": _widest(PRIORITY_ORDER, "Pri"),
	"status": _widest(STATUS_ORDER, "Status"),
	"blocked": _widest((BLOCKED_YES, BLOCKED_NO), "Blocked"),
	"agent": AGENT_WIDTH,
	# The worktree lifecycle states, widest first; blank on the many beans with
	# no worktree. Sized off the state words the column paints (see
	# `worktree.py`), so a renamed state widens the column instead of clipping.
	"worktree": _widest(("in-worktree", "ready", "merged"), "WT"),
	# beans mints ids as `<project>-<4 random base32 chars>`; the project half
	# is stripped because the heading above already names it.
	"id": _widest(("xxxx",), "ID"),
}

MIN_TITLE_WIDTH = 24
"""Floor for the title column, so a very narrow terminal degrades to clipped
titles rather than to a computed negative width."""

HEADING_HEIGHT = 1
"""Project headings are one line, like every other row.

They were briefly two, with the first line left blank as a spacer, back when
Title was the last column and a heading began four columns into the row -- it
needed the help. Now that Title leads, the rail glyph sits hard against the left
edge in the accent colour and reads on its own. The spacer cost more than it
gave: the row cursor is as tall as its row, so highlighting a heading painted a
two-line band, and the topmost project opened with a blank line hanging under
the header."""

POLL_INTERVAL = 0.5
"""How often to re-hash the bean files. The hash costs ~3ms against a ~21ms
reload, so polling twice a second is cheap; see bv-scx8."""


class ConfirmWorktreeDelete(ModalScreen[bool]):
	"""Confirm removing a bean's worktree and branch. Dismisses True to remove.

	Two faces on the same dialog. A merged, clean worktree loses nothing, so the
	body just says so and enter removes it. When `needs_force` -- unmerged
	commits, an uncommitted tree, or both, named in `reason` -- the body is a
	stark red warning that removing discards that work, because the removal the
	app then runs is `--force` / `git branch -D`. Escape (or any decline)
	dismisses False and nothing is touched: like every other modal here, the
	screen decides nothing itself, it only reports the choice back to the app.
	"""

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("escape", "cancel", "Cancel"),
		Binding("enter", "confirm", "Remove"),
	]

	DEFAULT_CSS = """
	ConfirmWorktreeDelete {
	    align: center middle;

	    & > #delete-dialog {
	        width: 60;
	        max-width: 90%;
	        height: auto;
	        padding: 1 2;
	        background: $surface;
	        border: round $accent;
	    }

	    & .delete--title { text-style: bold; }
	    & .delete--body { margin: 1 0; }
	    & .delete--hint { color: $text-muted; }
	}
	"""

	def __init__(self, worktree: str, *, needs_force: bool, reason: str) -> None:
		super().__init__()
		self.worktree = worktree
		self.needs_force = needs_force
		self.reason = reason

	def compose(self) -> ComposeResult:
		branch = branch_for(self.worktree)
		with Vertical(id="delete-dialog"):
			yield Static(Text(f"Remove worktree {branch}?"), classes="delete--title")
			if self.needs_force:
				body = Text(f"This would lose work -- {self.reason}. Removing discards it.", style="bold red")
			else:
				# `reason` names *why* nothing is at stake -- merged, or never
				# committed to in the first place -- rather than claiming a merge
				# that a brand-new worktree never had.
				body = Text(f"{self.reason.capitalize()} and clean: nothing is lost.", style="dim")
			yield Static(body, classes="delete--body")
			verb = "force remove" if self.needs_force else "remove"
			yield Static(Text(f"[enter] {verb}   [esc] cancel"), classes="delete--hint")

	def action_confirm(self) -> None:
		self.dismiss(True)

	def action_cancel(self) -> None:
		self.dismiss(False)


class BeanTable(DataTable):
	"""The tree's DataTable, which drives its own Title-column refit.

	The refit has to hang off *this* widget's resize rather than the app's: a
	terminal resize reaches the app (screen) before the table's region has been
	re-laid-out, so an app-level handler measures the old width -- and on a
	grow-back the stale room recomputes to the cached narrow width, which the
	fit's no-op guard swallows, leaving the column pinned (bv-41rc). The table's
	own resize fires once its `size` is settled, so the fit sees the real width.
	"""

	def on_resize(self) -> None:
		app = self.app
		if isinstance(app, BeansViewer):
			app._refit_title()


class BeansViewer(App):
	CSS_PATH = "app.tcss"
	TITLE = "bv"

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("space", "fold", "Fold"),
		Binding("C", "collapse_all", "Collapse all"),
		Binding("E", "expand_all", "Expand all"),
		Binding("P", "projects_only", "Projects"),
		Binding("slash", "start_filter", "Filter"),
		Binding("p", "toggle_preview", "Preview"),
		# The preview scrolls without taking focus, so the table keeps j/k.
		Binding("ctrl+f", "preview_scroll(1)", "Preview down", show=False),
		Binding("ctrl+b", "preview_scroll(-1)", "Preview up", show=False),
		Binding("r", "reload", "Refresh"),
		Binding("w", "toggle_watch", "Watch"),
		Binding("a", "toggle_archived", "Archived"),
		Binding("e", "edit", "Edit bean"),
		Binding("S", "spawn", "Spawn agent"),
		Binding("W", "spawn_worktree", "Worktree agent"),
		Binding("R", "review_worktree", "Review worktree"),
		Binding("D", "delete_worktree", "Delete worktree"),
		Binding("m", "mission_control", "Mission control"),
		Binding("y", "yank_id", "Yank id"),
		# The second half of the pair, hidden for the same reason `G` is: the
		# footer is a reminder of the common keys, not a manual.
		Binding("Y", "yank_line", "Yank line", show=False),
		Binding("b", "toggle_board", "Board"),
		Binding("q", "quit", "Quit"),
		# Vim motions, additive -- the arrow keys keep working.
		Binding("j", "move(1)", "Down", show=False),
		Binding("k", "move(-1)", "Up", show=False),
		Binding("g", "goto_top", "Top", show=False),
		Binding("G", "goto_bottom", "Bottom", show=False),
		Binding("ctrl+d", "half_page(1)", "Half page down", show=False),
		Binding("ctrl+u", "half_page(-1)", "Half page up", show=False),
		Binding("escape", "clear_filter", "Clear filter", show=False),
	]

	def __init__(self, root: Path) -> None:
		super().__init__()
		self.root = root
		# Resolved before the first paint so the footer never advertises `P` to
		# a board that has no project headings, and re-asked on every load --
		# a `beans init` in the root turns a grouped board into a flat one
		# without a restart.
		self._flat = is_project(root)
		self._forest: list[Node] = []
		self._rows: list[Node] = []
		# Collapse state is keyed by project name / bean id rather than row
		# index so it survives a reload that reorders or resizes the board.
		self._collapsed: set[str] = set()
		# Seeded here, before the first paint, so startup is not itself
		# treated as a change.
		self._watcher = Watcher(root)
		self._watching = True
		self._beans: list[Bean] = []
		self._theme_restored = False
		self._filter = ""
		self._pending_g = False
		self._title_width = MIN_TITLE_WIDTH
		self._show_archived = False
		self._sessions: list[Session] = []
		self._working: dict[str, Attribution] = {}
		# Worktree lifecycle state per bean id, recomputed each poll from git --
		# NONE for the many beans with no `worktree-<id>` branch, so the column
		# and the review/delete keys read a state without a git call per bean.
		self._worktrees: dict[str, str] = {}
		# Shorts of sessions under this board that are currently waiting on the
		# user, so a fresh block raises one toast and a still-blocked session
		# stays quiet. `None` until the first read, which seeds without firing
		# -- a session already blocked when bv starts is not news.
		self._needs_input: set[str] | None = None
		self._board = False

	def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
		"""Hide keys that mean nothing in the current view, and refuse them.

		Textual consults this for both halves of the problem: `Footer` builds
		itself from the bindings that survive it, and `run_action` will not
		dispatch one it rejects. So a single answer here stops the key firing
		*and* stops the footer promising it.

		Two independent gates: the board has no folds, and a flat board has no
		project headings.
		"""
		if self._board and action in TREE_ONLY_ACTIONS:
			return False
		return not (self._flat and action in FLAT_ONLY_HIDDEN_ACTIONS)

	def compose(self) -> ComposeResult:
		yield Header()
		with Horizontal():
			yield BeanTable(cursor_type="row", zebra_stripes=True)
			# Mounted, not created on demand, and hidden with a class. Almost
			# every action in this class reaches for the table with a bare
			# query_one, so removing it would turn every fold key into a
			# NoMatches traceback the moment the board is showing.
			yield BeanBoard(id="board", classes="hidden")
			yield BeanPreview(id="preview")
		filter_input = Input(placeholder="filter titles, ids, tags, type, status…")
		filter_input.display = False
		yield filter_input
		yield Footer()

	def on_mount(self) -> None:
		settings = load_settings()
		self._restore_theme(settings)
		# Restored before the first load; load_beans then drops any key whose
		# node no longer exists.
		self._collapsed = set(settings.collapsed.get(str(self.root), ()))
		self._show_archived = settings.show_archived
		table = self.query_one(DataTable)
		# Title leads: it carries the fold marker, the indent and the project
		# heading, so it is the column the tree structure actually lives in.
		# Last, a heading began four columns of padding into the row.
		#
		# No Repo column at all -- every row sits under a heading that names its
		# project, so repeating it per row spent the widest column on the least
		# information. Scrolled deep the heading does go off screen; fold with
		# `P` to get your bearings.
		table.add_column("Title", key="title", width=MIN_TITLE_WIDTH)
		table.add_column("Type", key="type", width=META_WIDTHS["type"])
		table.add_column("Pri", key="priority", width=META_WIDTHS["priority"])
		table.add_column("Status", key="status", width=META_WIDTHS["status"])
		table.add_column("Blocked", key="blocked", width=META_WIDTHS["blocked"])
		table.add_column("Agent", key="agent", width=META_WIDTHS["agent"])
		table.add_column("WT", key="worktree", width=META_WIDTHS["worktree"])
		table.add_column("ID", key="id", width=META_WIDTHS["id"])
		table.focus()
		self.set_interval(POLL_INTERVAL, self._poll_for_changes)
		self.action_reload()

	# -- theme -----------------------------------------------------------

	def _restore_theme(self, settings: Settings) -> None:
		"""Apply the saved theme before the first paint, so there is no flash."""
		stored = settings.theme
		# The config could name a theme that has since been renamed or
		# removed; fall back rather than crash on startup.
		if stored and stored in self.available_themes:
			self.theme = stored
		self._theme_restored = True

	def watch_theme(self, theme: str) -> None:
		# Fires for every switch, including ones made from the command
		# palette, which is the only way to change it today.
		if not self._theme_restored:
			return
		# Headings take their colour from the theme, so they have to be
		# repainted when it changes.
		if self._rows:
			self._render()
		try:
			save_theme(theme)
		except OSError as error:
			# A read-only home or full disk must not take the UI down over a
			# preference.
			self.notify(f"could not save theme: {error}", severity="warning")

	# -- loading ---------------------------------------------------------

	def action_reload(self) -> None:
		self.sub_title = f"loading {self.root}…"
		self.load_beans()

	@work(exclusive=True)
	async def load_beans(self) -> None:
		# load_all shells out to `beans` once per project; keep that off the
		# event loop so the UI stays responsive while it runs.
		beans, problems = await asyncio.to_thread(load_all, self.root)
		self._beans = beans
		# Two stats, so it rides here rather than getting its own thread hop.
		# The footer is built from `check_action`, and nothing about a root
		# gaining a `.beans` directory tells it to ask again.
		if (flat := is_project(self.root)) != self._flat:
			self._flat = flat
			self.refresh_bindings()
		# Attribution is keyed by bean id, so it has to be recomputed
		# whenever the set of beans changes, not just when sessions do. The
		# worktree state is keyed the same way; the git reads ride a thread so a
		# large multi-project board does not stall the load on the event loop.
		self._refresh_sessions()
		await asyncio.to_thread(self._refresh_worktrees)
		self._rebuild_forest()
		# Drop collapse state for nodes that no longer exist, but keep the
		# rest -- a refresh should not blow away how you arranged the board.
		self._collapsed &= collapsible_keys(self._forest)
		self._render()
		self.sub_title = self._summarize(self._visible_beans())

		for problem in problems:
			self.notify(problem, title="beans", severity="warning", timeout=10)

	# -- archive ---------------------------------------------------------

	def _visible_beans(self) -> list[Bean]:
		"""The beans the board is currently willing to show.

		`beans archive` moves finished beans into `.beans/archive/` but leaves
		them "visible in all queries", so hiding them is bv's job or nobody's.
		On a real board that can be scores of beans, often concentrated in one
		project -- a large fraction of it rendered as completed history.
		"""
		if self._show_archived:
			return self._beans
		return [bean for bean in self._beans if not bean.is_archived]

	def _rebuild_forest(self) -> None:
		# Archived beans are dropped before the tree is built, not after, so a
		# live child of an archived parent is promoted to the project root
		# rather than disappearing with it.
		self._forest = build_forest(self._visible_beans(), flat=self._flat)

	def action_toggle_archived(self) -> None:
		self._pending_g = False
		self._show_archived = not self._show_archived
		self._rebuild_forest()
		# Hiding archived beans removes nodes, so their fold state would
		# otherwise be dropped by the next reload and lost on the way back.
		if not self._show_archived:
			self._collapsed &= collapsible_keys(self._forest)
		self._render()
		self.sub_title = self._summarize(self._visible_beans())
		self._persist_show_archived()

	@work(exclusive=True, group="config")
	async def _persist_show_archived(self) -> None:
		try:
			await asyncio.to_thread(save_show_archived, self._show_archived)
		except OSError as error:
			self.notify(f"could not save archive setting: {error}", severity="warning")

	# -- watching --------------------------------------------------------

	def _poll_for_changes(self) -> None:
		# The interval outlives the app: on quit, a tick can land after the
		# widgets are gone and every query_one below it raises NoMatches. The
		# user sees a traceback on the way out of a clean session.
		if not self.is_running:
			return
		if not self._watching:
			return
		# Never redraw the board out from under someone typing a filter.
		if isinstance(self.focused, Input):
			return
		self.check_for_changes()

	@work(exclusive=True, group="watch")
	async def check_for_changes(self) -> None:
		# ~3ms of blocking I/O -- cheap, but still not the event loop's job.
		# poll() only reports once the digest has settled, so a reload never
		# lands mid-write.
		if await asyncio.to_thread(self._watcher.poll):
			self.load_beans()
			return
		# Sessions move without any bean file changing -- an agent finishing is
		# not a write to `.beans`. Cheap enough to check on every poll, and
		# only repaints when the attribution actually moved.
		if await asyncio.to_thread(self._refresh_session_and_worktree_state):
			self._render()
			self._resummarize()

	def action_toggle_watch(self) -> None:
		self._watching = not self._watching
		if self._watching:
			# Resync to disk as it is now, then reload: resuming should leave
			# you looking at current data, not replaying what you missed.
			self._watcher.reset()
			self.action_reload()
		else:
			self.sub_title = self._summarize(self._visible_beans())
		self.notify("watching for changes" if self._watching else "watching paused")

	# -- rendering -------------------------------------------------------

	def _fit_title_column(self) -> bool:
		"""Give Title every column the fixed ones do not want.

		Returns whether the width actually moved, so callers can skip a
		rebuild. Called on resize and on preview toggle, which are the two
		things that change how much room the table has.
		"""
		table = self.query_one(DataTable)
		columns = table.columns
		title = columns.get("title")
		if title is None:  # before on_mount has added the columns
			return False

		taken = sum(column.get_render_width(table) for key, column in columns.items() if key != "title")
		# get_render_width adds the padding for the other columns but not for
		# Title's own. The scrollbar is reserved unconditionally rather than
		# measured: measuring it is circular, because a wider Title makes rows
		# taller, which shows the scrollbar, which narrows the table, which
		# narrows Title again -- a two-column oscillation on every resize. A
		# board that fits on one screen forfeits two columns; one that does not
		# (the normal case) gets a stable layout.
		room = table.size.width - taken - 2 * table.cell_padding - table.styles.scrollbar_size_vertical
		width = max(MIN_TITLE_WIDTH, room)
		if width == self._title_width:
			return False
		self._title_width = width
		title.width = width
		return True

	def _refit_title(self) -> None:
		"""Re-fit the Title column to the table's current width and repaint.

		Driven off the *table's* own resize (`BeanTable.on_resize`), not the
		app's: a terminal resize reaches the app before the DataTable's region
		has been re-laid-out, so an app-level handler measures the old width and
		-- on a grow -- the stale room recomputes to the cached narrow width,
		which `_fit_title_column`'s no-op guard then swallows, leaving Title
		pinned. By the time the table itself is resized its `size` is settled,
		so the fit sees the real reclaimed room. The toggles route here too,
		after a refresh, for the width they hand the table by hiding a pane.
		"""
		# A resize event can still land during teardown; a repaint into a screen
		# that is gone is the same hazard as _poll_for_changes and _render.
		if not self.is_running:
			return
		if self._fit_title_column() and self._rows:
			self._render()

	def _render(self) -> None:
		# Same reason as _poll_for_changes: a worker that resolves after
		# teardown must not paint into a screen that no longer exists.
		if not self.is_running:
			return
		table = self.query_one(DataTable)
		previous = self._cursor_key()
		self._fit_title_column()

		table.clear()
		# A filter overrides the fold state: hiding a match inside a collapsed
		# epic would make the filter look broken.
		forest = self._active_forest()
		self._rows = visible_rows(forest, set() if self._filter else self._collapsed)
		for node in self._rows:
			# Every row is one line, headings included -- see HEADING_HEIGHT.
			table.add_row(*self._cells(node), key=node.key, height=HEADING_HEIGHT)

		# The board is fed from the same call, so a watch refresh, a filter
		# and an archive toggle all reach both views without a second path.
		self.query_one(BeanBoard).set_beans(
			self._board_beans(), show_project=not self._flat, worktree_states=self._worktrees
		)

		self._restore_cursor(previous)
		self._sync_preview()

	# -- board -----------------------------------------------------------

	def action_toggle_board(self) -> None:
		"""Swap between the tree and the kanban board.

		The table stays mounted underneath either way -- see `compose`.
		"""
		self._pending_g = False
		self._board = not self._board
		board = self.query_one(BeanBoard)
		table = self.query_one(DataTable)
		board.set_class(not self._board, "hidden")
		table.set_class(self._board, "hidden")
		if self._board:
			board.set_beans(self._board_beans(), show_project=not self._flat, worktree_states=self._worktrees)
			if (preview := self._preview()) is not None:
				preview.show(board.selected)
		else:
			self._sync_preview()
		self._focus_active_view()
		# The footer is built from whatever `check_action` allows, and nothing
		# about swapping a `hidden` class tells it to ask again.
		self.refresh_bindings()
		# The table's width is settled after the next refresh; refit then.
		self.call_after_refresh(self._refit_title)

	def _board_beans(self) -> list[Bean]:
		"""What the board shows: visible beans, filtered the same way the tree is.

		The board has no tree, so it takes the flat list -- but a filter the
		user typed has to mean the same thing in both views or `/` looks broken
		when you press `b`.
		"""
		beans = self._visible_beans()
		if not self._filter:
			return beans
		needle = self._filter.casefold()
		return [bean for bean in beans if self._matches(bean, needle)]

	def on_bean_board_selected(self, message: BeanBoard.Selected) -> None:
		if (preview := self._preview()) is not None:
			preview.show(message.bean)

	# -- dispatch --------------------------------------------------------

	def action_spawn(self) -> None:
		"""`S` -- start a background agent that edits the project checkout directly."""
		self._offer_dispatch(worktree=False)

	def action_spawn_worktree(self) -> None:
		"""`W` -- start one in an isolated worktree instead.

		Unlike `S`, `W` asks *which branch to fork* before confirming: it opens
		`PickBase` on the project's local branches, and the pick becomes the base
		bv cuts the worktree from. Everything after the confirmation -- the spawn,
		the attribution -- is the shared path. Its code lands on the board only
		when the branch the agent commits to is merged; see `dispatch.request_for`.

		The pick is skipped when there are no branches to offer -- not a git repo,
		or unreadable -- and the cut falls through to HEAD, where `dispatch`
		surfaces any git error in the confirmation the same way a bad base would.
		"""
		self._pending_g = False
		bean = self._current_bean()
		if not can_dispatch(bean):
			self.notify("no bean under the cursor", severity="information")
			return
		root = self._project_root(bean.project)
		branches = local_branches(root)
		if not branches:
			self._confirm_worktree(bean, root, base=None)
			return
		self.push_screen(PickBase(branches, current_branch(root)), partial(self._base_picked, bean, root))

	def _base_picked(self, bean: Bean, root: Path, base: str | None) -> None:
		# None is escape out of the picker: the whole `W` is abandoned, nothing
		# is confirmed and nothing spawns.
		if base is not None:
			self._confirm_worktree(bean, root, base=base)

	def _confirm_worktree(self, bean: Bean, root: Path, *, base: str | None) -> None:
		"""Show the `W` confirmation for a decided base, then spawn on enter."""
		self.push_screen(
			ConfirmDispatch(
				request_for(bean, root, worktree=True, base=base),
				warning=already_working(self._agent_on(bean)),
			),
			self._dispatch_confirmed,
		)

	def _offer_dispatch(self, *, worktree: bool) -> None:
		"""Offer to start a background Claude session on the highlighted bean.

		The `S` path. `W` goes through `action_spawn_worktree` for its base
		picker; this stays the direct-dispatch entry `action_spawn` calls.
		"""
		self._pending_g = False
		bean = self._current_bean()
		if not can_dispatch(bean):
			self.notify("no bean under the cursor", severity="information")
			return
		self.push_screen(
			ConfirmDispatch(
				request_for(bean, self._project_root(bean.project), worktree=worktree),
				warning=already_working(self._agent_on(bean)),
			),
			self._dispatch_confirmed,
		)

	def _project_root(self, project: str) -> Path:
		"""Where a bean's project actually lives on disk.

		Not `self.root / project`. On a flat board the root *is* the project,
		and that expression pointed at a subdirectory that does not exist --
		which is a wrong working directory for a dispatched agent and a
		permanently empty Agent column, neither of which announces itself.
		"""
		return self.root if self._flat else self.root / project

	def _current_bean(self) -> Bean | None:
		"""The bean the user is looking at, in whichever view is up.

		Not `_current_node().bean`. The table keeps its cursor while it is
		hidden, so reading it on the board dispatched an agent at whatever row
		the tree happened to be parked on -- a wrong-repo spawn that the
		confirmation would have named correctly and unrecognisably.
		"""
		if self._board:
			return self.query_one(BeanBoard).selected
		node = self._current_node()
		return node.bean if node else None

	def _current_project(self) -> str | None:
		"""The project the cursor is on, heading or bean, in either view.

		Branches on the view for the same reason as `_current_bean`: the tree's
		`DataTable` keeps a stale cursor while the board is up, so reading its
		row on the board would name whatever project the tree was parked on.
		"""
		if self._board:
			bean = self.query_one(BeanBoard).selected
			return bean.project if bean else None
		node = self._current_node()
		return node.project if node else None

	def action_mission_control(self) -> None:
		"""Open the live agent grid for the project under the cursor."""
		project = self._current_project()
		if project is None:
			self.bell()
			return
		self.push_screen(
			MissionControl(
				project,
				self._project_root(project),
				poll_interval=POLL_INTERVAL,
			)
		)

	def _agent_on(self, bean: Bean) -> str | None:
		"""The session already working `bean`, if bv can see one.

		Exact attributions only. The coarse tier means "some session is running
		in this project", which is true of every in-progress bean there at once
		-- warning on it would put the notice on beans nobody has touched.
		"""
		found = self._working.get(bean.id)
		return found.label if found is not None and found.exact else None

	def _dispatch_confirmed(self, request: DispatchRequest | None) -> None:
		# None is escape. The screen never runs anything itself -- see
		# src/bv/dispatch.py; the side effect belongs to the app.
		if request is not None:
			self.run_dispatch(request)

	@work(exclusive=True, group="dispatch")
	async def run_dispatch(self, request: DispatchRequest) -> None:
		# ~170 ms of blocking subprocess, the same order as
		# `claude agents --json`. Stalling the UI for a sixth of a second at
		# the exact moment the user is watching it is not acceptable.
		result = await asyncio.to_thread(dispatch, request)
		self.notify(result.message, severity="information" if result.ok else "error")
		# The new session should appear in the Agent column immediately rather
		# than up to half a second later. A `W` dispatch also just cut a
		# `worktree-<id>` branch, so refresh the worktree state in the same beat
		# -- the column should show the new worktree without waiting for a poll.
		if result.ok:
			moved = await asyncio.to_thread(self._refresh_session_and_worktree_state)
			if moved:
				self._render()
				self._resummarize()

	# -- worktree review and cleanup -------------------------------------

	def action_review_worktree(self) -> None:
		"""`R` -- dispatch a code-review of the bean's ready worktree branch.

		An S-style job: the review agent runs in the *main checkout*, never inside
		the worktree, so its `beans update --body-append` findings land on the
		board's copy of the bean rather than the branch's trapped `.beans` (the
		same trap the `W` status write hits). The diff is `worktree-<id>` against
		its recorded base. It reviews and reports; it does not merge and does not
		edit code -- see `dispatch.review_prompt_for`.

		Offered only when the worktree is `ready` (finished, unmerged): there is
		nothing to review before the agent has committed, and a merged branch is
		already past this step. Any other state is a no-op with a notify, matching
		`S`/`W` when there is no bean under the cursor. The base is read
		synchronously, as `W` reads its branch list -- one fast `git config`.
		"""
		self._pending_g = False
		bean = self._current_bean()
		if bean is None:
			self.notify("no bean under the cursor", severity="information")
			return
		if self._worktrees.get(bean.id, WT_NONE) != WT_READY:
			self.notify(f"no ready worktree to review for {bean.id}", severity="information")
			return
		root = self._project_root(bean.project)
		base = recorded_base(root, bean.id)
		self.push_screen(
			ConfirmDispatch(
				review_request_for(bean, root, base),
				warning=already_working(self._agent_on(bean)),
			),
			self._dispatch_confirmed,
		)

	def action_delete_worktree(self) -> None:
		"""`D` -- remove the bean's worktree and delete its branch, guarded.

		Symmetric with the `git worktree add` bv runs on `W`: worktree
		housekeeping, not a code merge, so it stays inside the observe-only line
		(which is specifically "bv never runs `git merge`"). Guarded against losing
		work -- a merged, clean worktree removes freely; one with unmerged commits
		or an uncommitted tree is refused by default and only removed after an
		explicit force confirm. `merged` catches squash/rebase-merged PRs, not just
		fast-forwards -- see `worktree.merged_verdict`.

		No worktree for the bean is a no-op with a notify, never an error. The
		merged/dirty reads are synchronous, as `W`'s branch reads are; the actual
		removal rides a thread because a `git worktree remove` can take a moment.
		"""
		self._pending_g = False
		bean = self._current_bean()
		if bean is None:
			self.notify("no bean under the cursor", severity="information")
			return
		if self._worktrees.get(bean.id, WT_NONE) == WT_NONE:
			self.notify(f"no worktree for {bean.id}", severity="information")
			return
		root = self._project_root(bean.project)
		needs_force, reason = self._worktree_delete_plan(root, bean.id)
		self.push_screen(
			ConfirmWorktreeDelete(bean.id, needs_force=needs_force, reason=reason),
			partial(self._delete_confirmed, bean, root, needs_force),
		)

	def _worktree_delete_plan(self, root: Path, bean_id: str) -> tuple[bool, str]:
		"""Whether removing this worktree would lose work, and why.

		`(needs_force, reason)`. A merged branch with a clean tree loses nothing
		and removes without a force. Unmerged commits or an uncommitted tree each
		mean a plain `git worktree remove` / `git branch -d` would refuse or
		discard work, so a force confirm is required; the reason names which, so
		the dialog can say what is at stake rather than a bare "are you sure".

		The safe case splits two ways for the dialog's benefit. `merged_verdict`
		answers "is there unmerged work here", and a worktree whose agent has
		committed nothing passes it trivially -- true, and nothing is at stake,
		but calling that *merged* to the user's face would claim a merge that
		never happened. `has_own_commits` separates the two readings.
		"""
		merged = merged_verdict(root, bean_id)
		dirty = worktree_dirty(root, bean_id)
		if merged and not dirty:
			return (False, "merged" if has_own_commits(root, bean_id) else "nothing committed")
		reasons = []
		if not merged:
			reasons.append("unmerged commits")
		if dirty:
			reasons.append("uncommitted changes")
		return (True, " and ".join(reasons))

	def _delete_confirmed(self, bean: Bean, root: Path, force: bool, proceed: bool | None) -> None:
		# None/False is escape or decline; only an explicit confirm removes.
		if proceed:
			self.remove_worktree_job(bean, root, force)

	@work(exclusive=True, group="dispatch")
	async def remove_worktree_job(self, bean: Bean, root: Path, force: bool) -> None:
		# `git worktree remove` shells out; keep it off the event loop like the
		# dispatch and load do.
		ok, message = await asyncio.to_thread(remove_worktree, root, bean.id, force=force)
		self.notify(message, severity="information" if ok else "error")
		# The removed worktree should leave the column immediately rather than at
		# the next poll; the branch is gone, so its state flips to `none`.
		if ok:
			moved = await asyncio.to_thread(self._refresh_session_and_worktree_state)
			if moved:
				self._render()
				self._resummarize()

	# -- edit ------------------------------------------------------------

	def action_edit(self) -> None:
		"""`e` -- change one property of the bean under the cursor.

		Opens a menu of editable fields; each choice leads to a value picker or a
		single-line prompt, and the pick becomes exactly one `beans update`. Works
		in either view through `_current_bean`, like `S` and the yanks.

		Every write goes through `_apply`, which runs the #208 guard first -- so
		this is the one place bv mutates a bean, and it never does so silently over
		a frontmatter key beans would drop. See src/bv/edit.py.
		"""
		self._pending_g = False
		bean = self._current_bean()
		if bean is None:
			self.notify("no bean under the cursor", severity="information")
			return
		self._choose("edit which field?", self._edit_menu(bean), None, partial(self._edit_field, bean))

	def _edit_menu(self, bean: Bean) -> list[tuple[str, str]]:
		"""The editable-field rows, with the remove/clear rows shown only when they
		would do something -- no "Remove tag" on a bean with no tags."""
		items = [
			("status", "Status"),
			("priority", "Priority"),
			("type", "Type"),
			("title", "Title"),
			("tag_add", "Add tag"),
		]
		if bean.tags:
			items.append(("tag_remove", "Remove tag"))
		items.append(("parent_set", "Set parent"))
		if bean.parent_id:
			items.append(("parent_remove", "Remove parent"))
		items.append(("blocked_by_add", "Add blocker (blocked by)"))
		if bean.blocked_by_ids:
			items.append(("blocked_by_remove", "Remove blocker"))
		items.append(("blocking_add", "Mark as blocking a bean"))
		if bean.blocking_ids:
			items.append(("blocking_remove", "Stop blocking a bean"))
		items.append(("archive", "Archive finished beans (project-wide)"))
		return items

	def _edit_field(self, bean: Bean, field: str) -> None:
		"""Route a chosen field to its value picker or prompt.

		Every branch ends in `_apply(bean, label, flags)` -- the guarded write --
		except the relational adds, which first check there is another bean to
		point at, and archive, which is a project sweep of its own.
		"""
		if field == "status":
			self._choose(
				"new status",
				[(status, status) for status in STATUS_ORDER],
				bean.status,
				lambda value: self._apply(bean, f"status → {value}", ("--status", value)),
			)
		elif field == "priority":
			options = [(priority, priority) for priority in PRIORITY_ORDER] + [(CLEAR, "(clear priority)")]
			self._choose(
				"new priority",
				options,
				bean.priority,
				lambda value: self._apply(
					bean,
					"priority cleared" if value == CLEAR else f"priority → {value}",
					("--priority", "" if value == CLEAR else value),
				),
			)
		elif field == "type":
			self._choose(
				"new type",
				[(bean_type, bean_type) for bean_type in TYPE_ORDER],
				bean.type,
				lambda value: self._apply(bean, f"type → {value}", ("--type", value)),
			)
		elif field == "title":
			self._prompt(
				"new title",
				bean.title,
				lambda value: self._apply(bean, "title updated", ("--title", value)),
			)
		elif field == "tag_add":
			self._prompt(
				"tag to add",
				"",
				lambda value: self._apply(bean, f"tag +{value}", ("--tag", value)),
			)
		elif field == "tag_remove":
			self._choose(
				"remove which tag",
				[(tag, tag) for tag in bean.tags],
				None,
				lambda value: self._apply(bean, f"tag -{value}", ("--remove-tag", value)),
			)
		elif field == "parent_set":
			options = self._bean_options(bean, exclude={bean.id} | ({bean.parent_id} if bean.parent_id else set()))
			if not options:
				self.notify("no other bean in this project to set as parent", severity="information")
				return
			self._choose(
				"set parent to",
				options,
				bean.parent_id,
				lambda value: self._apply(bean, f"parent → {value}", ("--parent", value)),
			)
		elif field == "parent_remove":
			self._apply(bean, "parent removed", ("--remove-parent",))
		elif field == "blocked_by_add":
			options = self._bean_options(bean, exclude={bean.id, *bean.blocked_by_ids})
			if not options:
				self.notify("no other bean in this project to add as a blocker", severity="information")
				return
			self._choose(
				"blocked by which bean",
				options,
				None,
				lambda value: self._apply(bean, f"blocked by {value}", ("--blocked-by", value)),
			)
		elif field == "blocked_by_remove":
			self._choose(
				"remove which blocker",
				self._id_options(bean.blocked_by_ids),
				None,
				lambda value: self._apply(bean, f"unblocked from {value}", ("--remove-blocked-by", value)),
			)
		elif field == "blocking_add":
			options = self._bean_options(bean, exclude={bean.id, *bean.blocking_ids})
			if not options:
				self.notify("no other bean in this project to block", severity="information")
				return
			self._choose(
				"mark as blocking which bean",
				options,
				None,
				lambda value: self._apply(bean, f"blocking {value}", ("--blocking", value)),
			)
		elif field == "blocking_remove":
			self._choose(
				"stop blocking which bean",
				self._id_options(bean.blocking_ids),
				None,
				lambda value: self._apply(bean, f"stopped blocking {value}", ("--remove-blocking", value)),
			)
		elif field == "archive":
			self._edit_archive(bean)

	def _bean_options(self, bean: Bean, exclude: set[str]) -> list[tuple[str, str]]:
		"""Live beans in the same project, minus `exclude`, as `(id, "id  title")`
		rows for a parent/blocker picker. Same project because beans' relations do
		not cross projects, and archived ones are dropped as dead targets."""
		return [
			(other.id, f"{other.id}  {other.title}")
			for other in self._beans
			if other.project == bean.project and other.id not in exclude and not other.is_archived
		]

	def _id_options(self, ids: tuple[str, ...]) -> list[tuple[str, str]]:
		"""`(id, "id  title")` rows for a fixed set of ids -- the current parents,
		blockers or blocked beans -- resolving each title from the loaded board and
		falling back to the bare id for anything not currently loaded."""
		titles = {other.id: other.title for other in self._beans}
		return [(bean_id, f"{bean_id}  {titles[bean_id]}" if bean_id in titles else bean_id) for bean_id in ids]

	def _choose(
		self,
		title: str,
		options: list[tuple[str, str]],
		current: str | None,
		then: Callable[[str], None],
	) -> None:
		"""Push a `ChoiceScreen` and run `then` with the pick, dropping an escape.

		The escape-is-None convention lives here rather than in every caller, so a
		field handler only ever sees a real choice."""
		self.push_screen(
			ChoiceScreen(title, options, current=current),
			lambda value: then(value) if value is not None else None,
		)

	def _prompt(self, title: str, initial: str, then: Callable[[str], None]) -> None:
		"""Push a `PromptScreen` and run `then` with the entered text, dropping an
		escape or an empty line -- neither is a value any edited field accepts."""
		self.push_screen(
			PromptScreen(title, initial=initial),
			lambda value: then(value) if value is not None else None,
		)

	def _apply(self, bean: Bean, label: str, flags: tuple[str, ...]) -> None:
		"""Guard, then run one `beans update`.

		The #208 guard is the whole reason this is a method and not an inline
		shell-out: before mutating, read the bean's file and refuse if `beans
		update` would drop a frontmatter key it does not know, naming the key so
		the loss is a decision rather than a surprise. bv's own beans carry no such
		keys, so the common path falls straight through.
		"""
		beans_dir = self._project_root(bean.project) / ".beans"
		lost = custom_frontmatter_keys(beans_dir / bean.path)
		if lost:
			self.notify(
				f"edit refused -- `beans update` would drop custom frontmatter key {', '.join(lost)} (beans#208)",
				severity="error",
				timeout=10,
			)
			return
		self.run_bean_edit(update_argv(beans_dir, bean.id, *flags), f"{bean.id}: {label}")

	def _edit_archive(self, bean: Bean) -> None:
		"""Confirm, then sweep the project's finished beans into the archive.

		beans 0.4.2 has no per-bean archive: `beans archive` moves *every*
		completed/scrapped bean in the project at once. So this counts them, names
		the count in the confirmation, and is deliberately reached from the edit
		menu of one bean while acting on the whole project.
		"""
		root = self._project_root(bean.project)
		finished = [
			other
			for other in self._beans
			if other.project == bean.project and other.status in FINISHED_STATUSES and not other.is_archived
		]
		if not finished:
			self.notify("no completed or scrapped beans to archive in this project", severity="information")
			return
		count = len(finished)
		plural = "s" if count != 1 else ""

		def confirmed(value: str) -> None:
			# A `def` rather than a lambda so the worker's return value is dropped:
			# `run_bean_edit` is a `@work` method that returns a Worker, and a
			# lambda would leak it where `_choose` wants None.
			if value == "yes":
				self.run_bean_edit(archive_argv(root / ".beans"), f"{bean.project}: archived {count} bean{plural}")

		self._choose(
			f"archive {count} finished bean{plural} in {bean.project}?",
			[("yes", f"yes, archive {count} bean{plural}"), ("no", "no, cancel")],
			None,
			confirmed,
		)

	@work(exclusive=True, group="edit")
	async def run_bean_edit(self, argv: tuple[str, ...], ok_message: str) -> None:
		"""Run one `beans` write off the event loop, report it, and reload on success.

		One process spawn and a small file rewrite -- the same order as a yank's
		shell-out, but on the event loop it would still stall the keypress, so it
		hops a thread like `run_dispatch`. On success the board reloads so the
		change shows without waiting on the file watcher; on failure beans' own
		first error line is what the toast carries.
		"""
		result = await asyncio.to_thread(run_edit, argv)
		self.notify(ok_message if result.ok else result.message, severity="information" if result.ok else "error")
		if result.ok:
			self.load_beans()

	# -- yank ------------------------------------------------------------

	def action_yank_id(self) -> None:
		"""`y` -- the id alone, for pasting into a command."""
		self._yank(yank_id)

	def action_yank_line(self) -> None:
		"""`Y` -- id, title and status, for pasting into a message."""
		self._yank(yank_line)

	def _yank(self, render: Callable[[Bean], str]) -> None:
		# Works in either view: `_current_bean` reads the board's selection
		# while the board is up, and a project heading carries no bean at all.
		self._pending_g = False
		bean = self._current_bean()
		if bean is None:
			self.notify("no bean under the cursor", severity="information")
			return
		self.copy_text(render(bean))

	@work(exclusive=True, group="clipboard")
	async def copy_text(self, text: str) -> None:
		"""Copy, then say what was copied. See src/bv/clipboard.py for the why.

		Off the event loop because it shells out -- 6.8 ms rather than
		dispatch's 170 ms, but still blocking I/O on a keypress. `exclusive`
		so a second yank before the first lands wins, which is the only
		sensible reading of two yanks in a row.
		"""
		result = await asyncio.to_thread(copy, text)
		if result.unavailable:
			# Nothing on PATH to shell out to. OSC 52 is the fallback, and it
			# has to run here rather than on the thread: it writes through the
			# app's own driver.
			self.copy_to_clipboard(text)
		elif not result.ok:
			self.notify(result.message, severity="error")
			return
		# Always, and with the text in it. OSC 52 can be swallowed by the
		# terminal without a word, so the notification is the only proof the
		# key did anything -- and quoting what was copied is what tells a user
		# whose terminal ate it that bv is not the part that is broken.
		self.notify(f"copied {_ellipsize(text, NOTIFY_WIDTH)}")

	# -- preview ---------------------------------------------------------

	def _preview(self) -> BeanPreview | None:
		"""The preview pane, or None once it is gone.

		`query_one` raises during teardown: `RowHighlighted` still fires while
		the table is being removed, and a quit would end on a NoMatches
		traceback rather than an exit. A query that can return nothing is the
		honest shape for something that outlives its widget.
		"""
		return next(iter(self.query(BeanPreview)), None)

	def _sync_preview(self) -> None:
		"""Point the preview at the highlighted row of the *table*.

		Does nothing while the board is up. Focusing the board makes the table
		emit a highlight, which would otherwise immediately overwrite the
		board's selection with the table cursor -- the preview read "no bean
		selected" while a card was visibly highlighted.

		`show` is a no-op when the bean has not changed, which matters because
		every fold and every reload rebuilds the table and re-fires the
		highlight -- without that guard the body would re-parse and throw away
		the reader's scroll position mid-read. When the bean *has* changed,
		`show` only starts a timer; the body renders once the cursor settles,
		so this stays cheap enough to call from a keypress.
		"""
		if self._board:
			return
		preview = self._preview()
		if preview is None:
			return
		node = self._current_node()
		preview.show(node.bean if node else None)

	def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
		self._sync_preview()

	def action_toggle_preview(self) -> None:
		self._pending_g = False
		preview = self.query_one(BeanPreview)
		preview.toggle_class("hidden")
		if preview.has_class("hidden"):
			# Nothing should be left waiting on a timer to paint a pane that is
			# not on screen.
			preview.cancel()
		elif self._board:
			# Coming back: the cursor has probably moved on since the pane was
			# hidden, and it should not open on the bean it left off at.
			preview.show(self.query_one(BeanBoard).selected)
		else:
			self._sync_preview()
		# Hiding the preview hands the table another ~72 columns, all of which
		# should go to the titles. The table has not been re-laid-out yet, so
		# the refit waits a refresh for its new size.
		self.call_after_refresh(self._refit_title)

	async def action_preview_scroll(self, direction: int) -> None:
		preview = self.query_one(BeanPreview)
		if preview.has_class("hidden"):
			return
		# Someone reaching for the pane wants the body now, not in 150 ms;
		# paging a pane that is still showing its pending marker would look
		# like the scroll keys had stopped working.
		await preview.flush()
		# Mounted is not laid out: until the next refresh the pane's scroll
		# range is still the old document's, and a page taken against it is
		# either lost or lands mid-way down the new one.
		preview.call_after_refresh(preview.scroll_page_down if direction > 0 else preview.scroll_page_up)

	@staticmethod
	def _matches(bean: Bean, needle: str) -> bool:
		"""One definition of what `/` searches, shared by the tree and the board.

		A filter that meant different things either side of `b` would look like
		a bug in the filter.
		"""
		haystack = (bean.title, bean.id, bean.type, bean.status, *bean.tags)
		return any(needle in field.casefold() for field in haystack)

	def _active_forest(self) -> list[Node]:
		if not self._filter:
			return self._forest
		needle = self._filter.casefold()
		return filter_forest(self._forest, lambda bean: self._matches(bean, needle))

	def _accent(self) -> str:
		"""Heading colour, taken from the active theme rather than hard-coded.

		bv restores whichever of Textual's themes was last used, so a literal
		would clash on most of them.
		"""
		# Only ever called from _render, which runs after mount, so the theme
		# is resolved by now. An unknown key falls back to no colour rather
		# than to a literal that would clash on most themes.
		return self.theme_variables.get("text-accent", "")

	def _cells(self, node: Node) -> tuple[Text, ...]:
		marker = self._marker(node)

		if node.is_project:
			accent = self._accent()
			heading = Text(f"{RAIL}{marker}", style=f"bold {accent}")
			heading.append(node.project.upper(), style=f"bold {accent}")
			heading.append(f"   {summarize(node)}", style="dim")
			heading.truncate(self._title_width, overflow="ellipsis")
			cells = {key: Text("") for key in META_WIDTHS}
			cells["agent"] = self._heading_agent_text(node.project)
			return (heading, *cells.values())

		bean = node.bean
		assert bean is not None
		indent = INDENT * (node.depth - 1)
		title = Text(f"{indent}{marker}{bean.title}")
		# The title yields to the tags, not the other way round: truncating the
		# whole cell would silently drop the tags off long titles, which is the
		# half a reader cannot reconstruct -- a clipped title is still legible,
		# a missing tag looks like an untagged bean. Truncated here rather than
		# left to the renderer to crop, so a title that ran out of room says so.
		tags = self._tag_text(bean)
		title.truncate(max(len(marker), self._title_width - tags.cell_len), overflow="ellipsis")
		return (
			title + tags,
			Text(bean.type, style=TYPE_STYLES.get(bean.type, "")),
			Text(bean.priority, style=PRIORITY_STYLES.get(bean.priority, "")),
			Text(bean.status, style=STATUS_STYLES.get(bean.status, "")),
			self._blocked_text(bean),
			self._agent_text(bean),
			worktree_cell(self._worktrees.get(bean.id, WT_NONE)),
			Text(bean.id.removeprefix(f"{bean.project}-"), style="dim"),
		)

	def _agent_text(self, bean: Bean) -> Text:
		"""The session working this bean.

		Exact matches only -- the bean id has to be in the session name. A
		session merely running inside the project is *not* shown here: it was
		tried, and on a real board it put one session's title against three
		unrelated beans in a project at once, because a research session
		happened to be cwd'd there. That is a board that lies. Project-level
		sessions go on the project heading instead, where they are true.

		Blank rather than a placeholder: most beans have no agent, and this
		column exists to make the few that do stand out.
		"""
		found = self._working.get(bean.id)
		if found is None or not found.exact:
			return Text("")
		style = "bold yellow" if found.session.display_state == "blocked" else "bold green"
		label = Text(found.label, style=style)
		label.truncate(AGENT_WIDTH, overflow="ellipsis")
		return label

	def _heading_agent_text(self, project: str) -> Text:
		"""Sessions running inside this project, named on its heading.

		This is the coarse tier, shown at the only altitude it is honest at.
		A session's `cwd` says which repo it is in, never which bean, so it
		belongs to the project row.
		"""
		label = Text(self._project_agents(project), style="dim")
		label.truncate(AGENT_WIDTH, overflow="ellipsis")
		return label

	def _project_agents(self, project: str) -> str:
		"""Sessions running inside `project`, as one label, or "".

		The coarse tier of attribution, shared by the project heading and -- on
		a flat board, which has no headings -- the status bar. Without the
		second home, running bv from inside a repo would give no sign that an
		agent is working there at all.
		"""
		root = resolved(self._project_root(project))
		if root is None:
			return ""
		names = [session.name for session in self._sessions if session.is_busy and _session_within(session, root)]
		if not names:
			return ""
		return names[0] if len(names) == 1 else f"{len(names)} agents"

	def _refresh_sessions(self) -> bool:
		"""Re-read the Claude session files. Returns whether anything moved.

		~0.26 ms, which is why this rides the existing poll instead of getting
		a timer -- `claude agents --json` is the documented interface but costs
		~172 ms, eight times a whole board reload. See src/bv/agents.py.
		"""
		previous = self._session_render_state()
		self._sessions = load_sessions()
		# Where the project sits depends on which shape of board this is; see
		# `_project_root`.
		self._working = attribute_all(
			self._sessions,
			((bean.id, self._project_root(bean.project), bean.status == "in-progress") for bean in self._beans),
		)
		self._announce_needs_input()
		return self._session_render_state() != previous

	def _refresh_session_and_worktree_state(self) -> bool:
		"""Re-read both session attribution and worktree state in one thread hop.

		Runs off the poll's `to_thread`. Both are checked -- never short-circuited
		-- so a repaint fires when *either* the Agent column or the Worktree
		column moved, and neither read is skipped because the other already
		reported a change.
		"""
		sessions_moved = self._refresh_sessions()
		worktrees_moved = self._refresh_worktrees()
		return sessions_moved or worktrees_moved

	def _refresh_worktrees(self) -> bool:
		"""Recompute every bean's worktree lifecycle state. Returns whether it moved.

		Grouped by project root -- worktree branches live in each project's own
		repo -- so it is one `git branch` per project per poll, plus a few reads
		only for the projects that actually have live worktrees. Cheap enough to
		ride the existing 0.5 s poll (see `worktree.worktree_states`), and the
		common all-`none` board never pays more than the `git branch`.
		"""
		previous = self._worktrees
		by_root: dict[Path, list[str]] = {}
		for bean in self._beans:
			by_root.setdefault(self._project_root(bean.project), []).append(bean.id)
		states: dict[str, str] = {}
		for root, ids in by_root.items():
			states.update(worktree_states(root, ids))
		self._worktrees = states
		return states != previous

	def _announce_needs_input(self) -> None:
		"""Toast once when a session under this board starts waiting on the user.

		Runs on the 0.5 s poll, so a background agent that blocks for input is
		seen without the grid open. "Waiting" is `Session.needs_input` -- the
		live tempo, not the declared `state` -- so a session composing a reply
		mid-conversation does not count, and each fresh question the agent asks
		raises its own toast. Fires on the transition into waiting, not while it
		stays there. Only sessions inside the board root count -- bv can see
		every job on the machine, and a toast for an unrelated repo's agent is
		noise.
		"""
		root = resolved(self.root)
		blocked = {
			session.short: session
			for session in self._sessions
			if session.needs_input and (root is None or _session_within(session, root))
		}
		if self._needs_input is None:
			# First read: adopt the current set silently. What was already
			# waiting when bv launched is not a new event.
			self._needs_input = set(blocked)
			return
		for short in blocked.keys() - self._needs_input:
			self.bell()
			self.notify(blocked[short].name, title="needs input", severity="warning")
		self._needs_input = set(blocked)

	def _session_render_state(self) -> tuple[object, ...]:
		"""Everything the Agent column and the coarse agent tier paint from the
		sessions, so a poll repaints when -- and only when -- one of those
		inputs moves.

		Comparing labels alone missed a same-bean working->blocked transition:
		the bean id and the session name were both unchanged, so the change went
		undetected and the cell kept its stale green (bv-ov50). `_agent_text`
		colours by `session.state` and the exact/coarse flag; `_project_agents`
		counts the busy sessions, so both feed the signature.
		"""
		attributed = {
			bean_id: (found.label, found.session.state, found.exact) for bean_id, found in self._working.items()
		}
		busy = sorted((session.name, session.state) for session in self._sessions if session.is_busy)
		return (attributed, busy)

	def _blocked_text(self, bean: Bean) -> Text:
		"""Whether anything unfinished is in the way.

		`no` is dimmed rather than omitted. Only a handful of beans are ever
		blocked, so a column of full-strength `no` would be the loudest thing
		on a board where it is the least interesting -- but leaving the cell
		blank makes "not blocked" and "column not populated yet" look alike.
		"""
		if not bean.is_blocked:
			return Text(BLOCKED_NO, style="dim")
		count = bean.blocked_by_open
		label = BLOCKED_YES if count == 1 else f"{BLOCKED_YES} {count}"
		return Text(label, style="bold red")

	def _tag_text(self, bean: Bean) -> Text:
		"""The tag suffix that trails a title, rather than its own column.

		Only a small minority of beans are tagged and none carry more than a
		couple, so a column would be almost entirely empty while costing width
		the titles want. Built separately from the title so the caller can
		measure it and reserve the room before truncating.
		"""
		if not bean.tags:
			return Text("")
		style = self.theme_variables.get("text-secondary", "")
		shown = bean.tags[:MAX_TAGS]
		tags = Text("  " + " ".join(f"#{tag}" for tag in shown), style=style)
		if len(bean.tags) > MAX_TAGS:
			tags.append(f" +{len(bean.tags) - MAX_TAGS}", style="dim")
		return tags

	def _marker(self, node: Node) -> str:
		if not node.has_children:
			return LEAF
		# While filtering, everything is drawn expanded, so the marker has to
		# agree with what is on screen rather than with the stored fold state.
		if self._filter:
			return EXPANDED
		return COLLAPSED if node.key in self._collapsed else EXPANDED

	# -- cursor ----------------------------------------------------------

	def _cursor_key(self) -> str | None:
		"""Identity of the highlighted row, so a rebuild can restore it."""
		table = self.query_one(DataTable)
		if not table.is_mounted or not self._rows:
			return None
		row = table.cursor_row
		if 0 <= row < len(self._rows):
			return self._rows[row].key
		return None

	def _restore_cursor(self, key: str | None) -> None:
		if key is None:
			return
		table = self.query_one(DataTable)
		for index, node in enumerate(self._rows):
			if node.key == key:
				table.move_cursor(row=index)
				return
		# The row is gone -- most likely folded away under an ancestor. Land
		# on that ancestor rather than snapping back to the top of the board.
		for index, node in enumerate(self._rows):
			if key in {n.key for n in node.descendants()}:
				table.move_cursor(row=index)
				return

	# -- folding ---------------------------------------------------------

	# Named `fold`, not `toggle`: `DOMNode.action_toggle` already exists in
	# Textual, takes a reactive attribute name, and does something else
	# entirely. Shadowing it with a different signature is an override error.
	def action_fold(self) -> None:
		if self._filter:
			# Filtered rows are drawn expanded regardless, so folding here
			# would silently change -- and persist -- state you cannot see.
			self.notify("clear the filter (esc) to fold", severity="information")
			return
		node = self._current_node()
		if node is None or not node.has_children:
			return
		if node.key in self._collapsed:
			self._collapsed.discard(node.key)
		else:
			self._collapsed.add(node.key)
		self._render()
		self._persist_collapsed()

	@work(exclusive=True, group="config")
	async def _persist_collapsed(self) -> None:
		"""Remember the fold state for this root, across restarts.

		Off the event loop because saving fsyncs, and this runs on every
		fold keypress.
		"""
		keys = set(self._collapsed)
		try:
			await asyncio.to_thread(save_collapsed, str(self.root), keys)
		except OSError as error:
			self.notify(f"could not save fold state: {error}", severity="warning")

	def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
		# `enter` is DataTable's own binding; fold on it too.
		self.action_fold()

	def action_collapse_all(self) -> None:
		self._collapsed = collapsible_keys(self._forest)
		self._render()
		self._persist_collapsed()

	def action_expand_all(self) -> None:
		self._collapsed = set()
		self._render()
		self._persist_collapsed()

	def action_projects_only(self) -> None:
		"""Collapse everything under each project, but leave projects open."""
		self._collapsed = collapsible_keys(self._forest) - project_keys(self._forest)
		self._render()
		self._persist_collapsed()

	# -- vim motions -----------------------------------------------------

	def _move_by(self, delta: int) -> None:
		table = self.query_one(DataTable)
		if not self._rows:
			return
		target = max(0, min(len(self._rows) - 1, table.cursor_row + delta))
		table.move_cursor(row=target)

	def action_move(self, delta: int) -> None:
		self._pending_g = False
		self._move_by(delta)

	def action_half_page(self, direction: int) -> None:
		self._pending_g = False
		# Half the visible table, matching ctrl+d/ctrl+u rather than a full page.
		self._move_by(direction * max(1, self.query_one(DataTable).size.height // 2))

	def action_goto_top(self) -> None:
		"""`gg`, spelled as two presses.

		Textual's Binding has no notion of a key sequence, so the first `g`
		arms a flag that a timer disarms -- the same shape as vim's timeoutlen,
		and without depending on the order key handlers happen to run in.
		"""
		if self._pending_g:
			self._pending_g = False
			self.query_one(DataTable).move_cursor(row=0)
			return
		self._pending_g = True
		self.set_timer(G_SEQUENCE_TIMEOUT, self._disarm_g)

	def _disarm_g(self) -> None:
		self._pending_g = False

	def action_goto_bottom(self) -> None:
		self._pending_g = False
		if self._rows:
			self.query_one(DataTable).move_cursor(row=len(self._rows) - 1)

	# -- filtering -------------------------------------------------------

	def action_start_filter(self) -> None:
		self._pending_g = False
		field = self.query_one(Input)
		field.display = True
		field.focus()

	def action_clear_filter(self) -> None:
		field = self.query_one(Input)
		field.value = ""
		field.display = False
		self._filter = ""
		self._render()
		self._focus_active_view()
		self.sub_title = self._summarize(self._visible_beans())

	def on_input_changed(self, event: Input.Changed) -> None:
		self._filter = event.value.strip()
		self._render()
		self.sub_title = self._summarize(self._visible_beans())

	def on_input_submitted(self, _event: Input.Submitted) -> None:
		# Keep the filter, hand the keyboard back so motions work again.
		self._focus_active_view()

	def _focus_active_view(self) -> None:
		"""Focus whichever view is on screen.

		Not `query_one(DataTable).focus()`. The table stays mounted while the
		board is up -- removing it would turn every action that reaches for it
		into a NoMatches traceback -- but it is hidden, so focusing it by name
		pointed the keyboard at a widget that was not on screen. Filtering on
		the board left it unreachable without a mouse. See bv-ndrn.
		"""
		if self._board:
			self.query_one(BeanBoard).focus()
		else:
			self.query_one(DataTable).focus()

	def _current_node(self) -> Node | None:
		table = self.query_one(DataTable)
		row = table.cursor_row
		if 0 <= row < len(self._rows):
			return self._rows[row]
		return None

	# -- misc ------------------------------------------------------------

	def _resummarize(self) -> None:
		"""Redraw the status bar after the sessions moved.

		Only a flat board needs it -- that is the one whose status bar carries
		the coarse agent tier, the project headings that normally carry it
		having gone with the project layer.
		"""
		if self._flat:
			self.sub_title = self._summarize(self._visible_beans())

	def _summarize(self, beans: list[Bean]) -> str:
		# A board that has silently stopped updating is worse than one that
		# never did, so the watch state is always on screen.
		suffix = "" if self._watching else " · paused"
		if self._filter:
			shown = sum(1 for node in self._rows if not node.is_project)
			return f"filter “{self._filter}” · {shown} of {len(beans)} beans{suffix}"
		if not beans:
			return f"no beans found{suffix}"
		active = sum(1 for bean in beans if bean.status == "in-progress")
		open_ = sum(1 for bean in beans if bean.status in ("todo", "in-progress"))
		# Hidden beans are stated rather than silently missing: a third of one
		# project is archived, and a count that quietly excludes them reads as
		# data loss.
		archived = sum(1 for bean in self._beans if bean.is_archived)
		if archived and self._show_archived:
			suffix = f" · {archived} archived shown{suffix}"
		elif archived:
			suffix = f" · {archived} archived hidden{suffix}"
		if self._flat:
			# No project count -- it would read "1 projects" -- and this is
			# where the coarse agent tier lands, the heading having gone with
			# the project layer.
			if agents := self._project_agents(beans[0].project):
				suffix = f" · {agents}{suffix}"
			return f"{len(beans)} beans · {open_} open · {active} in progress{suffix}"
		projects = len({bean.project for bean in beans})
		return f"{len(beans)} beans · {projects} projects · {open_} open · {active} in progress{suffix}"


def resolve_root(argument: Path | None) -> Path:
	"""The board root: what was asked for, or where bv was run.

	Resolved rather than merely expanded, because fold state is keyed by the
	root's string -- `bv`, `bv .` and `bv ~/projects/bv` are one board and have
	to agree on one spelling of it, or each spelling accumulates its own entry
	in the config file.
	"""
	return (argument.expanduser() if argument is not None else Path.cwd()).resolve()


def main() -> None:
	parser = argparse.ArgumentParser(prog="bv", description="Browse beans issues across every repo at once.")
	parser.add_argument(
		"root",
		nargs="?",
		type=Path,
		default=None,
		help="a beans repo, or a directory of them (default: the current directory)",
	)
	args = parser.parse_args()
	BeansViewer(root=resolve_root(args.root)).run()


if __name__ == "__main__":
	main()
