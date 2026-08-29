"""Modal screens for editing the bean under the cursor.

Two generic screens cover every field. `ChoiceScreen` is a single-pick list --
the edit menu, the status/priority/type value lists, and the parent/blocker/tag
pick-one-to-add-or-remove lists are all the same widget with different rows.
`PromptScreen` is a single-line text input -- the title and the free-text tag.

Both follow the same contract as `dispatch.PickBase`: they never mutate
anything, they dismiss with the chosen value or `None` on escape, and the app's
callback is the one place a choice turns into a `beans` write. That keeps the
side effect -- and the #208 guard in front of it -- in `app.py`, off the screens.
"""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

# Returned by a `ChoiceScreen` row that clears a field rather than setting it --
# "(clear priority)", "(remove parent)". A distinct sentinel, not "", so an
# empty option id can never be mistaken for it and the app maps it explicitly to
# the right `--remove-*` / empty-value flag.
CLEAR = "\x00clear"

_DIALOG_CSS = """
    align: center middle;

    & > #edit-dialog {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: $surface;
        border: round $accent;
    }

    & #edit-list {
        height: auto;
        max-height: 20;
        margin: 1 0;
        background: $panel;
    }

    & #edit-input {
        margin: 1 0;
    }

    & .edit--title {
        text-style: bold;
    }

    & .edit--hint {
        color: $text-muted;
    }
"""


class ChoiceScreen(ModalScreen[str | None]):
	"""Pick one option from a list. Dismisses with the option id, or None on escape.

	The row's id is the value the app acts on -- a field name in the edit menu, a
	status in the status list, a bean id in a parent/blocker list -- never the
	label the row shows, which may carry a title or a ` · current` mark. `current`
	seeds the highlight so the list opens on the value already set, the way
	`PickBase` opens on the checked-out branch.
	"""

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("escape", "cancel", "Cancel"),
		# Vim motions over the list, mirroring the board's own j/k/g/G -- additive,
		# the arrow keys OptionList already binds keep working. OptionList does not
		# bind these letters, so the screen-level binding reaches the focused list.
		Binding("j", "move(1)", "Down", show=False),
		Binding("k", "move(-1)", "Up", show=False),
		Binding("g", "top", "Top", show=False),
		Binding("G", "bottom", "Bottom", show=False),
	]

	DEFAULT_CSS = "ChoiceScreen {" + _DIALOG_CSS + "}"

	def __init__(
		self,
		title: str,
		options: list[tuple[str, str]],
		current: str | None = None,
		hint: str = "[enter] pick   [esc] cancel",
		*,
		name: str | None = None,
		id: str | None = None,
		classes: str | None = None,
	) -> None:
		super().__init__(name=name, id=id, classes=classes)
		self.title_text = title
		self.options = list(options)
		self.current = current
		self.hint_text = hint

	def compose(self) -> ComposeResult:
		with Vertical(id="edit-dialog"):
			yield Static(Text(self.title_text), classes="edit--title")
			yield OptionList(
				*(Option(label, id=value) for value, label in self.options),
				id="edit-list",
			)
			yield Static(Text(self.hint_text), classes="edit--hint")

	def on_mount(self) -> None:
		option_list = self.query_one(OptionList)
		ids = [value for value, _ in self.options]
		if self.current in ids:
			option_list.highlighted = ids.index(self.current)
		option_list.focus()

	def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
		# Enter and a mouse click both land here; the id is the raw value.
		self.dismiss(event.option.id)

	def action_move(self, delta: int) -> None:
		option_list = self.query_one(OptionList)
		if delta > 0:
			option_list.action_cursor_down()
		else:
			option_list.action_cursor_up()

	def action_top(self) -> None:
		self.query_one(OptionList).action_first()

	def action_bottom(self) -> None:
		self.query_one(OptionList).action_last()

	def action_cancel(self) -> None:
		self.dismiss(None)


class PromptScreen(ModalScreen[str | None]):
	"""Type a single line. Dismisses with the trimmed text on enter, None on escape.

	An empty submission dismisses `None` -- the same "nothing chosen" the escape
	gives -- because no field bv edits here takes an empty value (a title is
	cleared by leaving it, a tag is never blank). `initial` pre-fills the field so
	editing a title starts from the current one rather than a blank line.
	"""

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("escape", "cancel", "Cancel"),
	]

	DEFAULT_CSS = "PromptScreen {" + _DIALOG_CSS + "}"

	def __init__(
		self,
		title: str,
		initial: str = "",
		placeholder: str = "",
		hint: str = "[enter] save   [esc] cancel",
		*,
		name: str | None = None,
		id: str | None = None,
		classes: str | None = None,
	) -> None:
		super().__init__(name=name, id=id, classes=classes)
		self.title_text = title
		self.initial = initial
		self.placeholder = placeholder
		self.hint_text = hint

	def compose(self) -> ComposeResult:
		with Vertical(id="edit-dialog"):
			yield Static(Text(self.title_text), classes="edit--title")
			yield Input(value=self.initial, placeholder=self.placeholder, id="edit-input")
			yield Static(Text(self.hint_text), classes="edit--hint")

	def on_mount(self) -> None:
		self.query_one(Input).focus()

	def on_input_submitted(self, event: Input.Submitted) -> None:
		text = event.value.strip()
		self.dismiss(text or None)

	def action_cancel(self) -> None:
		self.dismiss(None)
