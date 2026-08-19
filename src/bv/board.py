"""Show the whole portfolio as a kanban board: one scrollable column per status.

The tree answers "how does this project decompose". This answers "what is in
flight right now", which the tree structurally cannot: the in-progress beans
are spread across several projects, so the tree buries them under their own
epics in separate subtrees.

**Read-only, permanently.** Dragging a card between columns is a status write,
and bv does not write -- beans 0.4.2 ships hmans/beans#205 and #208 unpatched
(see the module docstring in `beans.py`). The board displays status; it never
sets it. That is why there is no drop target, no `enter` action on a card, and
no mutation path in this module at all.

**Four columns, not five.** `in-progress`, `todo`, `draft`, `completed`, with
`scrapped` folded into `completed` -- there is exactly 1 scrapped bean on the
real board and it does not earn a quarter of the screen. A card whose own
status is not its column's name says so on its meta line, so the fold is
visible rather than a lie; the same mechanism catches a status outside beans'
vocabulary, which `beans.py` turns into the literal `"unknown"` and which is
folded into `todo` rather than dropped (tree.py's precedent: a structural
oddity is surfaced at a root, never silently lost).

**Flat inside a column, ordered by `beans.rank`.** Grouping by project was the
alternative and loses on the column that decides it: `todo` holds 107 cards, so
you only ever see the top of it, and grouping would bury the single most
actionable bean of the last project under ~90 cards of the first three. Ranking
is what puts live, unblocked, unblocking, high-priority work at the top -- the
one thing a 107-card column can usefully do. The project is not lost, because
every card carries it.

**What a card shows: title, project, id, and three badges.** Everything else
was measured off. Status is the column. Priority as text or colour was tried
against the real board and rejected: 84 of 219 beans are `high` and 104 are
`normal`, so a badge on "above normal" would paint 38% of the board and read as
decoration -- only `critical` (9 of 219) is rare enough to be a signal.
`blocked` stays (26 of 219, and `rank` sorts on it, so a card sitting low needs
to say why). Tags are on only 28 of 219 and the preview pane already lists
them. The agent working a bean is not here at all: that lives in the session
data `app.py` holds, and taking it would double this widget's input for a
column that is empty on nearly every card.

The project drops off the card when the whole board is one project -- bv run
from inside a single repo -- because the same string on every card is not
information. `show_project` carries that, from `app.py` down to `card_text`.

Anything the badges cannot carry is one keystroke away in `BeanPreview`, which
exists precisely for "the fields that never fit in a column". The board is a
scanning surface; the preview is the reading surface.

Everything that turns a `Bean` into text is a module-level function returning a
value, so card and column content are testable without standing up an app --
the same split `preview.py` uses.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from .beans import STATUS_STYLES, Bean, rank

COLUMNS = ("in-progress", "todo", "draft", "completed")
"""The columns, in the order a human reads a backlog -- the same order as
`beans.STATUS_ORDER`, minus the statuses folded away below."""

FOLDED_INTO = {"scrapped": "completed"}
"""Statuses that share a column with another. 1 scrapped bean on the real
board; a column of one is a column of whitespace."""

FALLBACK_COLUMN = "todo"
"""Where a status outside beans' vocabulary lands. `beans.py` substitutes
`"unknown"` for a missing status field, and a bean of unknown state is
unfinished work a human should look at, not finished work to be filed away."""

TITLE_LINES = 2
"""Lines of the card given to the title.

Measured on the real board: titles run to a median of 53 characters, 76 at the
90th percentile and 96 at the longest. A card is ~23 characters wide once four
columns, padding and a scrollbar are taken out of a typical terminal, so one
line would show a quarter of the median title -- not enough to tell two beans
apart. Two lines covers the median outright. Three would cost a card per screen
for the tail alone."""

CARD_HEIGHT = TITLE_LINES + 1
"""Title lines plus the meta line. Fixed, and the title is padded up to
TITLE_LINES, so meta lines align down the column and every card occupies the
same number of rows -- which is what lets a scroll offset survive a rebuild."""

CARD_ROWS = CARD_HEIGHT + 1
"""Rows one card occupies including the margin below it. Used for half-page
motion, which should move in cards rather than in lines."""

CARD_OVERHEAD = 5
"""Columns a card loses to chrome: the column's padding (2), the card's own
padding (2), and one for the vertical scrollbar. The scrollbar is reserved
unconditionally rather than measured, for the reason app.py gives in
`_fit_title_column`: measuring it is circular."""

MIN_CARD_WIDTH = 12
"""Floor for the card's text width, so a very narrow terminal degrades to hard
truncation rather than to a negative width that `textwrap` rejects."""

ELLIPSIS = "…"

UNTITLED = "(untitled)"
"""A bean with no title still has to be selectable and countable. `beans.py`
defaults a missing title to the empty string, which would render as a blank
card indistinguishable from a rendering failure."""

EMPTY_COLUMN = "— nothing here —"
"""Shown in place of cards in a column with no beans. An em dash reads as
"deliberately empty" where a blank reads as "still loading" -- preview.py's
NOTHING, applied to a whole column."""

BLOCKED_MARKER = "⊘"
CRITICAL_MARKER = "!"


def column_of(status: str) -> str:
	"""Which column a bean of `status` belongs in."""
	if status in COLUMNS:
		return status
	return FOLDED_INTO.get(status, FALLBACK_COLUMN)


@dataclass(frozen=True)
class Column:
	"""One column's worth of beans, already ordered.

	Frozen, with a tuple of frozen beans, so two of these compare equal exactly
	when they would render identically. `BeanBoard.set_beans` leans on that to
	skip work -- see the comment there.
	"""

	status: str
	beans: tuple[Bean, ...]

	def __len__(self) -> int:
		return len(self.beans)


def build_columns(beans: Sequence[Bean]) -> list[Column]:
	"""Bucket beans into the four columns, each ordered by `beans.rank`.

	`rank` is the single definition of board order in this codebase; a second
	sort here is what `tree.py` learned not to write. It already puts
	`completed` above `scrapped` within the folded column, because status is
	the first term of the rank.

	Archived beans are not filtered here. The caller decides what is visible --
	`app.py` already hides them before the tree is built, for the same reason.
	"""
	buckets: dict[str, list[Bean]] = {status: [] for status in COLUMNS}
	for bean in beans:
		buckets[column_of(bean.status)].append(bean)
	return [Column(status=status, beans=tuple(sorted(buckets[status], key=rank))) for status in COLUMNS]


def heading_text(column: Column) -> Text:
	"""The pinned line above a column: its status and how many are in it.

	The count is the measurement the board exists to surface -- "18 in
	progress" is the answer you came for, and it is the one thing a column of
	107 cards cannot show you by being looked at.
	"""
	text = Text(column.status.upper(), style=STATUS_STYLES.get(column.status, "bold"))
	text.append(f"  {len(column)}", style="dim")
	return text


def wrap_title(title: str, width: int) -> list[str]:
	"""The title as exactly TITLE_LINES lines, padded and ellipsized to fit.

	Padded rather than trimmed so that every card is the same height and the
	meta lines line up down the column.

	`textwrap` counts characters, not terminal cells. Every title on the real
	board is ASCII, and a full-width glyph degrades to a line that stops short
	rather than to a card that reflows and pushes its own meta line off.
	"""
	width = max(MIN_CARD_WIDTH, width)
	lines = textwrap.wrap(
		title.strip() or UNTITLED,
		width=width,
		max_lines=TITLE_LINES,
		placeholder=ELLIPSIS,
	)
	# `textwrap.wrap` returns [] for a string that is entirely whitespace, which
	# `.strip() or UNTITLED` above already rules out -- but a width small enough
	# to leave no room can do it too.
	return [*lines, *[""] * TITLE_LINES][:TITLE_LINES]


def marker_text(bean: Bean) -> Text:
	"""The badges that lead a card's meta line.

	Leading, not trailing, for the reason app.py gives about tags: the half a
	reader cannot reconstruct must survive truncation. A clipped project name
	is still legible; a badge that got cut off makes a blocked bean look
	unblocked.

	The status badge fires whenever a card's own status is not its column's
	name, which is how the `scrapped`-into-`completed` fold and any unknown
	status announce themselves. Spelled out rather than given a glyph: it is
	rare enough (1 scrapped bean) that a word costs nothing, and an
	unguessable symbol for "this column is not what it says" is worse than
	none.
	"""
	text = Text()
	if bean.priority == "critical":
		text.append(f"{CRITICAL_MARKER} ", style="bold red")
	if bean.is_blocked:
		text.append(f"{BLOCKED_MARKER} ", style="red")
	if bean.status != column_of(bean.status):
		text.append(f"{bean.status} ", style="dim italic")
	return text


def meta_text(bean: Bean, width: int, *, show_project: bool = True) -> Text:
	"""Badges, then the project and the id suffix, truncated to `width`.

	The project is on the card because the board is flat: it is the only place
	the project survives, and "in progress across four repos" is the question
	the board was built to answer. The id keeps its project prefix stripped,
	as app.py does, because the text right beside it already says the project.

	`show_project` is False on a single-project board -- bv run from inside one
	repo -- where the project half is the same string on every card and so
	spends the card's narrowest resource on nothing.
	"""
	text = marker_text(bean)
	suffix = bean.id.removeprefix(f"{bean.project}-")
	label = Text(f"{bean.project} · {suffix}" if show_project else suffix, style="dim")
	label.truncate(max(0, width - text.cell_len), overflow="ellipsis")
	return text + label


def card_text(bean: Bean, width: int, *, show_project: bool = True) -> Text:
	"""The whole card: TITLE_LINES title lines, then one meta line."""
	text = Text()
	for line in wrap_title(bean.title, width):
		text.append(f"{line}\n")
	return text + meta_text(bean, max(MIN_CARD_WIDTH, width), show_project=show_project)


class BeanCard(Static):
	"""One bean, as a fixed-height block of text.

	A card is a single `Static` rather than a container of labelled parts.
	There are 218 visible beans on the real board and every one of them gets a
	card, so the widget count is the cost that matters; three widgets per card
	would be ~650 to mount on the first paint.
	"""

	def __init__(self, bean: Bean, width: int, show_project: bool = True) -> None:
		super().__init__(card_text(bean, width, show_project=show_project), classes="board--card")
		self.bean = bean
		self._width = width
		self._show_project = show_project

	def set_bean(self, bean: Bean, width: int, show_project: bool = True) -> None:
		"""Repoint this card at `bean`, re-rendering only if something moved."""
		if bean == self.bean and width == self._width and show_project == self._show_project:
			return
		self.bean = bean
		self._width = width
		self._show_project = show_project
		self.update(card_text(bean, width, show_project=show_project))


class BoardColumn(Vertical):
	"""A pinned heading above a scrollable stack of cards.

	The heading is outside the scroll region, unlike the header in
	`preview.py`, and for the opposite reason: a preview header is six lines
	and scrolls away harmlessly, whereas a 107-card column scrolls its heading
	out of sight within one screen and takes the status and the count with it.
	"""

	def __init__(self, status: str) -> None:
		super().__init__(classes="board--column")
		self.status = status
		self._heading = Static(classes="board--heading")
		self._cards = VerticalScroll(classes="board--cards")
		# One focus target for the whole board -- BeanBoard itself. A scrollable
		# per column would put four more stops in the tab order for a widget
		# that is driven entirely by h/j/k/l.
		self._cards.can_focus = False
		self._empty = Static(EMPTY_COLUMN, classes="board--empty")

	def compose(self) -> ComposeResult:
		yield self._heading
		with self._cards:
			yield self._empty

	@property
	def cards(self) -> list[BeanCard]:
		return [child for child in self._cards.children if isinstance(child, BeanCard)]

	def show(self, column: Column, width: int, show_project: bool = True) -> None:
		"""Display `column`, reusing the card widgets already mounted.

		Reuse rather than clear-and-remount is the whole trick, and it is here
		because the board is rebuilt on every auto-refresh -- roughly twice a
		second while files are changing. `VerticalScroll` keeps its offset when
		its children are updated in place, so a reader parked 60 cards down a
		column stays there through a refresh that only changed a title. Clearing
		first would reset the offset to zero on every poll and make the view
		unusable. `preview.py` fixed the same class of bug by refusing to
		re-parse a body that had not changed.
		"""
		self._heading.update(heading_text(column))
		self._empty.display = not column.beans

		existing = self.cards
		for card, bean in zip(existing, column.beans, strict=False):
			card.set_bean(bean, width, show_project)
		if len(column.beans) > len(existing):
			self._cards.mount_all([BeanCard(bean, width, show_project) for bean in column.beans[len(existing) :]])
		else:
			# Removal is scheduled, not immediate, but only ever from the tail,
			# so the cards that remain keep their positions and the offset holds.
			for card in existing[len(column.beans) :]:
				card.remove()

	def refit(self, width: int, show_project: bool = True) -> None:
		"""Re-wrap every card for a new width, without remounting any of them."""
		for card in self.cards:
			card.set_bean(card.bean, width, show_project)


class BeanBoard(Horizontal):
	"""Beans as a kanban board, driven by `set_beans`, `selected` and `move`.

	Selection is remembered per column, so `h`/`l` return you to where you were
	in each rather than dragging one row index across four columns of very
	different lengths. Across a rebuild it is restored by bean id, not by
	position: when a bean's status changes under a watch refresh, the cursor
	follows it into its new column instead of pointing at whatever slid into
	its old slot.
	"""

	DEFAULT_CSS = """
    BeanBoard {
        height: 1fr;
        width: 2fr;
        layout: horizontal;

        & > BoardColumn {
            width: 1fr;
            height: 1fr;
            padding: 0 1;
        }

        & .board--heading {
            height: 1;
            text-style: bold;
            background: $panel;
            padding: 0 1;
        }

        & .board--cards {
            height: 1fr;
            scrollbar-size-vertical: 1;
        }

        & .board--empty {
            padding: 1;
            color: $text-muted;
        }

        & .board--card {
            height: 3;
            margin-bottom: 1;
            padding: 0 1;
            /* The text is pre-wrapped to a measured width, so the renderer must
               never re-wrap it -- a reflow would push the meta line out of the
               card's fixed height. */
            text-wrap: nowrap;
            text-overflow: clip;
        }

        /* Matches app.tcss's datatable--cursor, so the cursor reads the same in
           both views. Dimmer when the board does not have focus, because with
           the preview pane beside it there are two things that can be driven. */
        & .board--card.-selected {
            background: $accent 15%;
        }

        &:focus .board--card.-selected {
            background: $accent 30%;
        }
    }
    """

	can_focus = True

	# h/l between columns, j/k within one -- none of these are bound anywhere
	# else, so nothing is displaced. Declared on the widget rather than left to
	# the app so that the board's own bindings win while it has focus.
	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("h", "move(0, -1)", "Left", show=False),
		Binding("l", "move(0, 1)", "Right", show=False),
		Binding("j", "move(1, 0)", "Down", show=False),
		Binding("k", "move(-1, 0)", "Up", show=False),
		Binding("ctrl+d", "half_page(1)", "Half page down", show=False),
		Binding("ctrl+u", "half_page(-1)", "Half page up", show=False),
	]

	class Selected(Message):
		"""The selected bean changed. `bean` is None when nothing is selected."""

		def __init__(self, bean: Bean | None) -> None:
			super().__init__()
			self.bean = bean

	def __init__(
		self,
		*,
		name: str | None = None,
		# `id` shadows the builtin; it is Textual's own widget kwarg name.
		id: str | None = None,
		classes: str | None = None,
	) -> None:
		super().__init__(name=name, id=id, classes=classes)
		self._columns = [BoardColumn(status) for status in COLUMNS]
		self._data = [Column(status=status, beans=()) for status in COLUMNS]
		self._applied = False
		self._column = 0
		# One remembered row per column, so switching columns and coming back
		# lands where you left rather than at a clamped index.
		self._rows = [0] * len(COLUMNS)
		self._selected_card: BeanCard | None = None
		self._announced: Bean | None = None
		self._touched = False
		self._width = MIN_CARD_WIDTH
		self._show_project = True

	def compose(self) -> ComposeResult:
		yield from self._columns

	def on_mount(self) -> None:
		self._apply()

	# -- interface for the app -------------------------------------------

	def set_beans(self, beans: Sequence[Bean], *, show_project: bool = True) -> None:
		"""Replace what the board shows.

		Safe before mount -- the content is applied on mount -- and cheap to
		call with data that has not changed, which is the normal case: the app
		polls twice a second and re-renders on theme change, resize and filter.
		`Column` and `Bean` are frozen, so the equality check below is a
		structural compare that skips the whole rebuild when nothing moved.

		`show_project` is part of that check because it changes what every card
		renders -- a board that becomes single-project mid-session (a `beans
		init` in the root) has to repaint even though no bean moved.
		"""
		data = build_columns(beans)
		if self._applied and data == self._data and show_project == self._show_project:
			return
		# Read before `_data` is replaced -- the cursor is restored by bean id,
		# and after the swap there is nothing left to say what it was on.
		previous = self.selected if self._applied else None
		self._data = data
		self._show_project = show_project
		if self.is_mounted:
			self._apply(previous)

	@property
	def selected(self) -> Bean | None:
		"""The bean under the cursor, or None when its column is empty."""
		beans = self._data[self._column].beans
		row = self._rows[self._column]
		return beans[row] if 0 <= row < len(beans) else None

	def move(self, rows: int = 0, columns: int = 0) -> None:
		"""Move the cursor by `rows` within its column, then `columns` across.

		Both are clamped rather than wrapped: a board is a spatial layout, and
		falling off the end of `completed` into `in-progress` is disorienting
		in a way that falling off the end of a list is not.
		"""
		self._touched = True
		if rows:
			self._rows[self._column] = _clamp(self._rows[self._column] + rows, len(self._data[self._column]))
		if columns:
			self._column = _clamp(self._column + columns, len(COLUMNS))
			self._rows[self._column] = _clamp(self._rows[self._column], len(self._data[self._column]))
		self._refresh_selection()

	# -- actions ---------------------------------------------------------

	def action_move(self, rows: int, columns: int) -> None:
		self.move(rows=rows, columns=columns)

	def action_half_page(self, direction: int) -> None:
		# Measured in cards, not lines: a half page of a column the reader
		# thinks in cards should land on a card boundary.
		visible = max(1, self._columns[self._column].size.height // CARD_ROWS)
		self.move(rows=direction * max(1, visible // 2))

	def on_click(self, event: events.Click) -> None:
		"""Clicking a card selects it. There is no second click action --
		moving a card would be a status write, which bv does not do."""
		for index, column in enumerate(self._columns):
			for row, card in enumerate(column.cards):
				if card is event.widget:
					self._touched = True
					self._column = index
					self._rows[index] = row
					self._refresh_selection()
					return

	# -- rendering -------------------------------------------------------

	def on_resize(self) -> None:
		# Card text is wrapped to a measured width, so a resize has to re-wrap
		# it -- but never remount it, which would throw away the scroll offset
		# of every column on a window drag. This handler is the board widget's
		# own resize, so `self.size` is already the settled new size (unlike the
		# app's screen-level resize, which fires before its DataTable child is
		# re-laid-out -- see BeanTable). A grow-back therefore recomputes the
		# real reclaimed width here rather than getting swallowed by the guard.
		width = self._card_width()
		if width == self._width:
			return
		self._width = width
		for column in self._columns:
			column.refit(width, self._show_project)

	def _card_width(self) -> int:
		width = self.size.width // len(COLUMNS) - CARD_OVERHEAD
		return max(MIN_CARD_WIDTH, width)

	def _apply(self, previous: Bean | None = None) -> None:
		self._applied = True
		self._width = self._card_width()
		for column, data in zip(self._columns, self._data, strict=True):
			column.show(data, self._width, self._show_project)
		self._restore_cursor(previous)
		self._refresh_selection()

	def _restore_cursor(self, previous: Bean | None) -> None:
		"""Put the cursor back on the bean it was on, wherever that now is.

		Falls back to the same slot, clamped, when the bean is gone -- which is
		what happens when a bean is archived or filtered out from under the
		cursor. Landing on its neighbour beats snapping to the top of the board.
		"""
		for index, data in enumerate(self._data):
			self._rows[index] = _clamp(self._rows[index], len(data))
		if previous is not None:
			for index, data in enumerate(self._data):
				for row, bean in enumerate(data.beans):
					if bean.id == previous.id:
						self._column = index
						self._rows[index] = row
						return
			return
		# Nothing has ever been selected, and the leftmost column can easily be
		# empty -- `in-progress` is 18 beans of 218, and a filtered board can
		# empty it entirely. Opening with the cursor nowhere would leave the
		# preview pane blank until the user found a column by hand. Only ever
		# done before the user has moved: after that, parking on an empty
		# column is a choice a rebuild must not overrule.
		if not self._touched:
			self._column = next(
				(index for index, data in enumerate(self._data) if data.beans),
				self._column,
			)

	def _refresh_selection(self) -> None:
		"""Repaint the cursor, keep it on screen, and tell the app about it."""
		card = self._selected_card_widget()
		# Only when the cursor actually landed on a different card. A rebuild
		# that leaves it where it was must not scroll: cards are reused in
		# place, so the cursor's widget is unchanged, and calling
		# `scroll_visible` anyway would drag a reader who had wheeled further
		# down the column back up to the cursor twice a second.
		if card is not self._selected_card:
			if self._selected_card is not None:
				self._selected_card.remove_class("-selected")
			self._selected_card = card
			if card is not None:
				card.add_class("-selected")
				card.scroll_visible(animate=False)
		# Only on an actual change. The board is re-applied on every poll, and a
		# message per poll would have the preview pane re-checking a bean that
		# has not moved twice a second.
		selected = self.selected
		if selected != self._announced:
			self._announced = selected
			self.post_message(self.Selected(selected))

	def _selected_card_widget(self) -> BeanCard | None:
		cards = self._columns[self._column].cards
		row = self._rows[self._column]
		return cards[row] if 0 <= row < len(cards) else None


def _clamp(value: int, length: int) -> int:
	"""Into `[0, length - 1]`, or 0 for an empty column."""
	return max(0, min(value, length - 1))
