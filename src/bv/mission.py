"""A project-scoped mission-control grid of live Claude sessions.

The board answers *which session is on which bean*; this answers *what is
every session on this project doing right now*, all at once, tmux-style. One
auto-sized panel per session running under the project root, each tailing the
same `~/.claude/jobs/<short>/` files the Agent column already trusts.

Observe-only, like `agents`: the grid reads `state.json` and `timeline.jsonl`,
never attaches to a session and never writes. A live agent is a running
process under Claude Code's daemon; bv watches it, it does not own it.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Grid, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from .agents import (
	Activity,
	Session,
	load_activity,
	load_sessions,
	sessions_within,
)

# States that get their own border colour (see `MissionControl.DEFAULT_CSS`,
# where `.agent--<state>` carries the accent). Anything else falls to the
# muted default. Live-first: `working`/`blocked` are what a watcher is here
# for, so they get the loud accents; finished sessions fade to grey.
_STATE_CLASSES = frozenset({"working", "blocked", "failed", "stopped", "done"})

# Rich style names for the inline state badge. Kept parallel to the CSS above
# but resolved by Rich, which does not read Textual's theme vars.
_BADGE_STYLE = {
	"working": "bold green",
	"blocked": "bold yellow",
	"failed": "bold red",
	"stopped": "dim",
	"done": "dim",
}

_EVENTS_SHOWN = 8
"""Timeline lines per panel. Enough to read the shape of what a session is
doing without the panel needing to scroll on a normal terminal."""


def _state_class(state: str) -> str:
	"""The CSS class carrying a panel's state colour (see `MissionControl.CSS`)."""
	return f"agent--{state}" if state in _STATE_CLASSES else "agent--unknown"


def _tokens(count: int) -> str:
	"""`23127` as `23.1k`; small counts stay exact so early activity is legible."""
	if count >= 1000:
		return f"{count / 1000:.1f}k"
	return str(count)


_LINE_CAP = 240
"""Characters kept per feed line. Agent replies run to paragraphs; a panel is a
glance, so each turn is flattened to one capped line and the panel scrolls."""


def _flatten(text: str) -> str:
	"""Collapse a multi-paragraph message to one line, capped.

	Timeline `text` carries the agent's real reply, blank lines and all. The
	grid shows the shape of the conversation, not the whole of it.
	"""
	one = " ".join(text.split())
	return one if len(one) <= _LINE_CAP else one[: _LINE_CAP - 1] + "…"


def render_panel(session: Session, activity: Activity | None) -> RenderableType:
	"""The contents of one agent panel: a header line, then the recent feed.

	`activity` is None when the session's state file cannot be read this tick
	(mid-write, just gone) -- the panel keeps its frame and says so rather than
	vanishing, because a session blinking out of the grid every few polls is
	worse than one stale line.
	"""
	state = activity.state if activity else session.state
	badge = Text()
	badge.append(session.name or session.short, style="bold")
	badge.append("  ")
	badge.append(state or "?", style=_BADGE_STYLE.get(state, "dim"))
	if not session.live:
		badge.append("  (ended)", style="dim")

	if activity is None:
		return Group(badge, Text("…", style="dim"))

	meta = Text()
	meta.append(f"{_tokens(activity.tokens)} tok", style="dim")
	if activity.subagents:
		kinds = ", ".join(activity.child_kinds) or "task"
		meta.append(f"  ·  {activity.subagents} subagent", style="cyan")
		meta.append("s" if activity.subagents != 1 else "", style="cyan")
		meta.append(f" ({kinds})", style="dim cyan")
	if activity.tempo and activity.tempo != "active":
		meta.append(f"  ·  {activity.tempo}", style="dim")

	lines: list[RenderableType] = [badge, meta]
	if activity.detail:
		lines.append(Text(activity.detail, style="italic"))

	feed = activity.events[-_EVENTS_SHOWN:]
	for event in feed:
		clock = event.at[11:16] if len(event.at) >= 16 else ""
		row = Text()
		row.append(f"{clock} ", style="dim")
		# `text` is the agent's actual reply; `detail` is only its status
		# headline (and is where a user's own typed message lands). Lead with
		# what the agent said, so the feed reads as output, not an echo of the
		# prompts. A text-less tick keeps its status line, dimmed.
		if event.text:
			row.append("› ", style="dim")
			row.append(_flatten(event.text))
		else:
			row.append(event.detail or event.state, style="dim")
		lines.append(row)

	if not feed and activity.result:
		lines.append(Text(activity.result, style="dim"))

	return Group(*lines)


class AgentPanel(VerticalScroll):
	"""One session's live cell. A scroll so a long feed never breaks the grid."""

	def __init__(self, session: Session) -> None:
		super().__init__(id=f"agent-{session.short}", classes=_state_class(session.state))
		self._short = session.short
		self._body = Static()

	def compose(self) -> ComposeResult:
		yield self._body

	def update(self, session: Session, activity: Activity | None) -> None:
		"""Repaint in place; keep the widget so focus and scroll survive a poll."""
		self._body.update(render_panel(session, activity))
		self.set_classes(_state_class(activity.state if activity else session.state))


class MissionControl(ModalScreen[None]):
	"""The grid. Opens over the board, refreshes on the app's own cadence.

	One panel per session under `project_root`, tiled so the count decides the
	shape -- roughly square, columns first, the way `tmux select-layout tiled`
	fills. Empty when nothing runs there, which is the honest answer, not an
	error.
	"""

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("escape,q", "close", "Close"),
	]

	DEFAULT_CSS = """
    MissionControl {
        align: center middle;

        & > #agents-dialog {
            width: 92%;
            height: 90%;
            background: $surface;
            border: round $accent;
            padding: 0 1;
        }

        & #agents-title {
            height: 1;
            text-style: bold;
            padding: 0 1;
        }

        & #agents-grid {
            grid-gutter: 1;
            padding: 1 0 0 0;
        }

        & #agents-empty {
            height: 1fr;
            content-align: center middle;
            color: $text-muted;
        }

        & AgentPanel {
            height: 100%;
            padding: 0 1;
            /* grey37, not $text-muted: border rejects a derived alpha colour,
               and only the live states earn a theme accent anyway. */
            border: round #5f5f5f;
        }

        & .agent--working { border: round $success; }
        & .agent--blocked { border: round $warning; }
        & .agent--failed  { border: round $error; }
        & .agent--stopped { border: round #5f5f5f; }
        & .agent--done    { border: round #5f5f5f; }
        & .agent--unknown { border: round #5f5f5f; }
    }
    """

	def __init__(
		self,
		project_name: str,
		project_root: Path,
		*,
		poll_interval: float = 0.5,
	) -> None:
		super().__init__()
		self._project_name = project_name
		self._project_root = project_root
		self._poll_interval = poll_interval
		# Shorts currently mounted, in grid order. When the running set changes
		# the grid is rebuilt; when it holds, panels update in place. `None`,
		# not `()`: an empty project must still build its notice on first pass,
		# and `() != ()` would skip it.
		self._mounted: tuple[str, ...] | None = None

	def compose(self) -> ComposeResult:
		from textual.containers import Vertical

		with Vertical(id="agents-dialog"):
			yield Static(self._title_text(), id="agents-title")
			yield Grid(id="agents-grid")

	async def on_mount(self) -> None:
		await self._refresh()
		self.set_interval(self._poll_interval, self._refresh)

	def action_close(self) -> None:
		self.dismiss(None)

	def _title_text(self) -> Text:
		# Plain Rich styles: theme vars are CSS-only, and Rich cannot parse
		# `$accent`. The dialog border already carries the accent.
		text = Text("agents · ", style="dim")
		text.append(self._project_name, style="bold")
		return text

	def _current(self) -> list[Session]:
		return sessions_within(load_sessions(), self._project_root)

	async def _refresh(self) -> None:
		"""Reconcile the grid with what is running under the project now."""
		sessions = self._current()
		shorts = tuple(s.short for s in sessions)
		grid = self.query_one("#agents-grid", Grid)

		if shorts != self._mounted:
			await self._rebuild(grid, sessions)
			self._mounted = shorts
		else:
			for session in sessions:
				panel = self.query_one(f"#agent-{session.short}", AgentPanel)
				panel.update(session, load_activity(session.short))

		self.query_one("#agents-title", Static).update(self._title_text())

	async def _rebuild(self, grid: Grid, sessions: list[Session]) -> None:
		"""Tear down and re-lay the grid; only runs when the session set moves.

		Awaits the mounts so a following in-place update finds real widgets, and
		so removal completes before the new children land rather than racing it.
		"""
		await grid.remove_children()
		if not sessions:
			# A Grid lays out nothing until it has a column count, so the empty
			# notice would mount at zero height without this.
			grid.styles.grid_size_columns = 1
			await grid.mount(Static("no active agents on this project", id="agents-empty"))
			return
		grid.styles.grid_size_columns = math.ceil(math.sqrt(len(sessions)))
		panels = [AgentPanel(session) for session in sessions]
		await grid.mount(*panels)
		for panel, session in zip(panels, sessions):
			panel.update(session, load_activity(session.short))
