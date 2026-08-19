"""Render one bean in full, beside a table that only has room for a row of it.

The board's five columns answer "what is this and how urgent", but a title is
rarely enough to know what a bean actually *is*. This widget takes the bean
under the cursor and shows the rest of it: the fields that never fit in a
column, then the markdown body.

**`Markdown` inside a `VerticalScroll`, not `MarkdownViewer`.** `MarkdownViewer`
is `VerticalScroll` + `Markdown` + a table-of-contents sidebar and link
history. The sidebar is the problem: bean bodies are a few hundred words with
zero or two headings, so a permanent TOC pane would spend a third of an already
half-width preview on an empty list, and it is a second focusable widget in a
pane the user tabs through. Subclassing `VerticalScroll` and mounting a bare
`Markdown` gives the same scrolling with one focus target, and inherits
`scroll_page_down()` / `scroll_home()` for a caller that wants to drive the
preview by keys while the table keeps focus.

The header is inside the scroll region rather than pinned above it. It is six
short lines, and pinning it would mean an outer container that is not itself
focusable -- a caller would have to reach through to an inner child to scroll.

Everything that turns a `Bean` into text is a module-level function taking a
`Bean | None` and returning a value, so the content can be tested without
standing up an app; the widget class is only plumbing.

Blocking links are rendered as ids, not titles. `Bean` carries `blocking_ids`
and `blocked_by_ids` because those are scalar fields on the same GraphQL query;
resolving them to titles would be a nested selection, and the preview does not
need it.

**The body is rendered on a delay, the header is not.** Every cursor move used
to rebuild the whole `Markdown` document, and that work lands on the event loop
between keystrokes: measured on the real board it is ~14 ms of blocked loop for
a median bean and ~40 ms for the largest, on top of the table's own repaint --
about twice the per-keypress cost of the same navigation with the pane hidden,
which is what a held `j` reads as drag. Nothing here is loading: the body
arrives with the board and is already a string in memory (bv-ax9v), so the fix
is to render less often, not sooner. A move now only restarts a timer, and the
body is rebuilt once the cursor has settled (see `RENDER_DELAY`).

While the timer runs the pane does not change at all: it goes on showing the
previous bean, header and body together, with a marker line saying it is
catching up. Nothing here is a half-state -- a fresh header over a stale body
would be a lie, and blanking the body would be indistinguishable from a bean
that genuinely has no body, which is the one thing the marker exists to tell
apart. Leaving the document in place also keeps what the reader had: their
scroll position, and something for `ctrl+f` to scroll while they wait.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.timer import Timer
from textual.widgets import Markdown, Static

from .beans import Bean

EMPTY_TITLE = "No bean selected"
EMPTY_HINT = "Move the cursor onto a bean to read it here."

NO_BODY = "*This bean has no body.*"
"""Shown in place of the body when a bean has nothing written in it. Markdown
rather than a separate widget, so there is only ever one body code path."""

NOTHING = "—"
"""Placeholder for an empty metadata field. An em dash reads as "deliberately
empty" where a blank reads as "still loading"."""

PENDING = "rendering…"
"""Marks the pane as one bean behind, while a delayed render is outstanding.

Names the bean it is waiting on where there is one, because the pane below it
is still showing a different one -- a bare spinner over a full pane would leave
the reader guessing which of the two they are reading. It is also how "still
rendering" is told apart from "this bean really is empty", which is the whole
reason the marker exists.

Static text rather than an animation. The pane is only ever pending for a
couple of hundred milliseconds at a time, and an animation would spend a
repaint every frame -- on exactly the fast path this delay exists to keep
free -- to say what one line already says."""

LABEL_WIDTH = 11
"""Wide enough for "blocked by" plus a space."""

# Everything below 0x20 except tab and newline, plus DEL. Bean bodies are
# written by humans and by Claude, but they are also pasted into -- a stray NUL
# or a bare ESC from copied terminal output is the one input that can make
# rendering fail rather than just look odd, so it is dropped before the parser
# ever sees it. Carriage returns are handled separately, as line endings.
_STRIP_CONTROL = {code: None for code in range(0x20) if code not in (0x09, 0x0A)}
_STRIP_CONTROL[0x7F] = None


def clean_body(body: str) -> str:
	"""Make an arbitrary bean body safe to hand to a markdown parser.

	Normalizes line endings, drops control characters, and trims the blank
	lines that beans leaves around a body. Never raises: anything unparseable
	as markdown still renders as *something*, because markdown-it has no
	syntax errors -- unclosed fences, half-written tables and stray angle
	brackets all degrade to text rather than blowing up.
	"""
	if not body:
		return ""
	text = body.replace("\r\n", "\n").replace("\r", "\n")
	return text.translate(_STRIP_CONTROL).strip("\n").rstrip()


def body_markdown(bean: Bean | None) -> str:
	"""The markdown to display for `bean`, including its empty states."""
	if bean is None:
		return ""
	return clean_body(bean.body) or NO_BODY


def pending_text(bean: Bean | None) -> str:
	"""The marker shown while `bean` waits its turn to be rendered."""
	if bean is None:
		return PENDING
	return f"rendering {bean.id}…"


def header_text(bean: Bean | None) -> Text:
	"""The block above the body: id, title, and the fields no column fits."""
	if bean is None:
		empty = Text(EMPTY_TITLE, style="bold dim")
		empty.append(f"\n{EMPTY_HINT}", style="dim")
		return empty

	text = Text(bean.id, style="bold")
	if bean.title:
		text.append(f"\n{bean.title}")
	text.append("\n")

	for label, value in _fields(bean):
		text.append(f"\n{label:<{LABEL_WIDTH}}", style="dim")
		text.append(value, style="dim" if value == NOTHING else "")

	return text


def _fields(bean: Bean) -> list[tuple[str, str]]:
	return [
		("type", bean.type or NOTHING),
		("priority", bean.priority or NOTHING),
		("status", bean.status or NOTHING),
		("tags", _join(bean.tags)),
		("parent", bean.parent_id or NOTHING),
		("blocking", _join(bean.blocking_ids)),
		("blocked by", _join(bean.blocked_by_ids)),
	]


def _join(values: tuple[str, ...]) -> str:
	# Tolerates the None that a hand-built or half-migrated Bean can carry in
	# a field the dataclass types as a tuple.
	return ", ".join(values) if values else NOTHING


class BeanPreview(VerticalScroll):
	"""A scrollable detail view of a single bean.

	Call `show(bean)` to display one, or `show(None)` for the empty state.
	Safe to call before the widget is mounted -- the content is applied on
	mount -- and safe to call repeatedly with the same bean, which is the
	normal case when a table rebuild re-fires its highlight event.

	`show` does not render: it points the pane at a bean and starts a timer.
	Callers that need the body *now* -- because they are about to scroll it, or
	are putting the pane back on screen -- call `flush`; callers taking the pane
	away call `cancel`.
	"""

	RENDER_DELAY = 0.15
	"""Seconds the cursor must sit still before the body is rebuilt.

    Picked to sit in the gap between the two things it has to tell apart. A
    held key repeats every 15--120 ms on macOS (`KeyRepeat` 1--8, defaulting to
    6 = 90 ms), so anything above 120 ms means a held `j` never triggers a
    render it is only going to throw away. A reader who has stopped on a row
    takes several hundred milliseconds to start reading, and the render itself
    is ~14 ms at the median bean, so 150 ms leaves the body on screen well
    inside that pause. Lower and fast repeats leak renders through; higher and
    a deliberate single press starts to feel like waiting."""

	DEFAULT_CSS = """
    BeanPreview {
        padding: 0 1;
        background: $surface;

        & > .preview--header {
            padding: 1 2 0 2;
        }

        & > .preview--pending {
            padding: 1 2 0 2;
            text-style: italic;
            color: $text-muted;
        }

        & > Markdown {
            margin: 0;
        }
    }
    """

	def __init__(
		self,
		bean: Bean | None = None,
		*,
		name: str | None = None,
		# `id` shadows the builtin; it is Textual's own widget kwarg name.
		id: str | None = None,
		classes: str | None = None,
	) -> None:
		super().__init__(name=name, id=id, classes=classes)
		self._bean = bean
		self._shown: Bean | None = None
		self._painted = False
		self._timer: Timer | None = None
		self._header = Static(classes="preview--header")
		self._pending = Static(PENDING, classes="preview--pending")
		self._body = Markdown()

	@property
	def bean(self) -> Bean | None:
		"""The bean the pane is pointed at, or None for the empty state.

		What is on screen, or -- for the moment between a cursor move and the
		render it schedules -- what is about to be.
		"""
		return self._bean

	@property
	def is_pending(self) -> bool:
		"""Whether a render is scheduled but has not run yet."""
		return self._timer is not None

	def compose(self) -> ComposeResult:
		# The marker sits above the header rather than in place of the body:
		# it is a note about the whole pane, and taking the body out of the
		# layout to make room would collapse the scroll region and lose the
		# reader's position for the duration.
		self._pending.display = False
		yield self._pending
		yield self._header
		yield self._body

	def on_mount(self) -> None:
		# The first paint is not debounced. There is no navigation to keep up
		# with yet, and a pane that opens on a marker reads as broken.
		self._apply()

	def show(self, bean: Bean | None) -> None:
		"""Point the pane at `bean`; it catches up once the cursor settles.

		A repeat of the bean already showing is ignored, which matters more
		than it looks: the table clears and re-adds every row on reload and on
		every fold, so the highlight event fires constantly with the same bean
		behind it. Re-parsing the body each time would throw away the reader's
		scroll position mid-read -- and the timer must not smuggle that
		re-render back in, so an unchanged bean does not restart it either.
		"""
		if self._painted and bean == self._bean:
			return
		self._bean = bean
		if not self.is_mounted:
			# Applied on mount instead; Markdown.update needs an app.
			return
		if bean == self._shown:
			# The cursor left and came back inside the window. What is on
			# screen is already right, so drop the pending render rather than
			# rebuilding an identical document under the reader.
			self.cancel()
			return
		self._schedule()

	def flush(self) -> None:
		"""Render a pending bean now rather than when the timer fires.

		For the caller who is about to do something to the body -- scroll it,
		or put the pane back on screen -- and would otherwise be acting on a
		marker.
		"""
		if self._timer is None:
			return
		self._stop_timer()
		self._apply()

	def cancel(self) -> None:
		"""Abandon a pending render; the pane keeps whatever it already shows.

		`bean` reverts to what is on screen, so a later `show` of the bean the
		cursor has since moved to schedules a fresh render rather than being
		swallowed as a repeat.
		"""
		if self._timer is None:
			return
		self._stop_timer()
		self._bean = self._shown
		self._show_pending(False)

	def _schedule(self) -> None:
		self._stop_timer()
		# Nothing else moves. The pane goes on showing the bean it already
		# has -- header, body, scroll position and all -- and only says which
		# one it is on its way to.
		self._pending.update(pending_text(self._bean))
		self._show_pending(True)
		self._timer = self.set_timer(self.RENDER_DELAY, self._render_pending)

	def _render_pending(self) -> None:
		self._timer = None
		# Same hazard as the app's poll timer (see bv-ndrn): a timer can
		# outlive what it paints into. Textual stops a widget's timers when its
		# message pump closes, so this is the belt to those braces -- and
		# `is_running` rather than `is_mounted`, which Textual sets on mount
		# and never clears.
		if not self.is_running:
			return
		self._apply()

	def _stop_timer(self) -> None:
		if self._timer is not None:
			self._timer.stop()
			self._timer = None

	def _show_pending(self, pending: bool) -> None:
		# One line appearing and disappearing, and no markdown blocks mounted
		# or unmounted -- the cost this class exists to keep off a keypress.
		self._pending.display = pending

	def _apply(self) -> None:
		self._painted = True
		self._shown = self._bean
		self._show_pending(False)
		self._header.update(header_text(self._bean))
		# update() parses off the event loop and returns an optionally
		# awaitable; not awaiting it here is deliberate, so that show() stays
		# callable from a synchronous message handler.
		self._body.update(body_markdown(self._bean))
		# A new bean is a new document -- start it at the top rather than
		# wherever the last one was left.
		self.scroll_home(animate=False)
