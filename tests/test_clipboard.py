"""Tests for yanking a bean to the clipboard.

Nothing here touches a real clipboard. `copy` takes both its runner and its
`which`, so every test below pins what is on PATH and records what would have
been run -- a test that shells out to `pbcopy` would silently overwrite
whatever the person running the suite had copied, and would only pass on macOS.
"""

import asyncio
import os
import subprocess
from datetime import UTC, datetime

from textual.widgets import Input

from bv import app as app_module
from bv.app import NOTIFY_WIDTH, BeansViewer
from bv.beans import Bean
from bv.clipboard import (
	COMMANDS,
	SEPARATOR,
	UNTITLED,
	CopyResult,
	copy,
	copy_command,
	one_line,
	yank_id,
	yank_line,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def bean(
	id="y7or",
	*,
	project="bv",
	title="Yank the bean under the cursor to the clipboard",
	status="todo",
) -> Bean:
	return Bean(
		project=project,
		id=f"{project}-{id}",
		title=title,
		status=status,
		type="feature",
		priority="normal",
		tags=(),
		updated_at=T0,
		parent_id=None,
	)


class Recorder:
	"""A runner that records the call and reports success."""

	def __init__(self, returncode=0, stderr="", stdout=""):
		self.calls = []
		self._result = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

	def __call__(self, command, **kwargs):
		self.calls.append((command, kwargs))
		return self._result


def only(*available):
	"""A `which` that finds exactly `available` and nothing else."""
	return lambda name: f"/usr/bin/{name}" if name in available else None


# -- what gets yanked -----------------------------------------------------


def test_the_id_yank_keeps_the_project_prefix():
	# On screen the prefix is redundant -- the heading above the row already
	# names the project. In a paste it is the only context there is, and
	# `beans show y7or` resolves nothing.
	assert yank_id(bean()) == "bv-y7or"


def test_the_line_yank_carries_id_title_and_status():
	line = yank_line(bean())
	assert line == "bv-y7or — Yank the bean under the cursor to the clipboard (todo)"
	assert SEPARATOR in line


def test_the_line_yank_is_one_line():
	"""It gets pasted into a chat message or a commit subject.

	A title with a newline in it would turn one paste into two lines, in a
	place where the second one loses its context entirely.
	"""
	line = yank_line(bean(title="Two\nlines\tand a tab"))
	assert "\n" not in line
	assert "\t" not in line
	assert line == "bv-y7or — Two lines and a tab (todo)"


def test_an_untitled_bean_still_yanks_something_readable():
	# beans defaults a missing title to the empty string, which would yank as
	# `bv-y7or —  (todo)` and read as a rendering failure.
	assert yank_line(bean(title="   ")) == f"bv-y7or{SEPARATOR}{UNTITLED} (todo)"


def test_a_nul_never_reaches_the_clipboard():
	# Same failure `dispatch._argv_safe` guards: a NUL truncates the string at
	# whatever consumes it, with nothing reporting a problem.
	assert "\x00" not in one_line("bv-\x00y7or")
	assert one_line("a\x00b") == "a b"


def test_the_status_is_on_the_line():
	# Id and title together still do not say whether the thing is done.
	assert yank_line(bean(status="completed")).endswith("(completed)")


# -- which tool ------------------------------------------------------------


def test_the_first_available_command_wins():
	assert copy_command(only("pbcopy")) == ("pbcopy",)
	assert copy_command(only("xclip")) == ("xclip", "-selection", "clipboard")


def test_wayland_beats_x11():
	# A Wayland session can still have xclip installed, pointed at an Xwayland
	# clipboard nobody is reading.
	assert copy_command(only("wl-copy", "xclip"))[0] == "wl-copy"


def test_no_clipboard_tool_at_all():
	assert copy_command(only()) == ()


def test_every_candidate_is_resolvable():
	# A typo in COMMANDS would fail as "no clipboard tool" on the one machine
	# that has the tool, which is indistinguishable from the honest case.
	for command in COMMANDS:
		assert copy_command(only(command[0])) == command


# -- copying ---------------------------------------------------------------


def test_the_text_goes_in_on_stdin():
	runner = Recorder()
	result = copy("bv-y7or", runner=runner, which=only("pbcopy"))
	assert result.ok
	command, kwargs = runner.calls[0]
	assert command == ("pbcopy",)
	assert kwargs["input"] == "bv-y7or"
	# A yank must not be able to wedge the worker thread on a stuck clipboard
	# daemon, and a nonzero exit has to be inspected rather than raised.
	assert kwargs["timeout"]
	assert kwargs["check"] is False


def test_nothing_is_run_when_there_is_no_tool():
	"""The caller falls back to OSC 52, which it has to emit itself.

	`unavailable` is deliberately not the same thing as a failure -- reporting
	"could not copy" here would be wrong, because the fallback usually works.
	"""
	runner = Recorder()
	result = copy("bv-y7or", runner=runner, which=only())
	assert not result.ok
	assert result.unavailable
	assert runner.calls == []


def test_a_failing_tool_is_quoted_rather_than_swallowed():
	# The whole point of shelling out is that failure is visible. A yank that
	# reports success on a nonzero exit is the OSC 52 problem again.
	runner = Recorder(returncode=1, stderr="pbcopy: write failed\nmore detail")
	result = copy("bv-y7or", runner=runner, which=only("pbcopy"))
	assert not result.ok
	assert not result.unavailable
	assert result.message == "pbcopy: pbcopy: write failed"


def test_a_silent_failure_still_says_something():
	runner = Recorder(returncode=3)
	result = copy("bv-y7or", runner=runner, which=only("pbcopy"))
	assert "exit 3" in result.message


def test_a_tool_that_vanished_between_which_and_exec():
	def runner(command, **kwargs):
		raise FileNotFoundError(command[0])

	result = copy("bv-y7or", runner=runner, which=only("pbcopy"))
	assert not result.ok
	# Not `unavailable`: there was a tool, so falling back to OSC 52 would be
	# papering over a broken install rather than adapting to a bare one.
	assert not result.unavailable
	assert "pbcopy" in result.message


def test_a_wedged_clipboard_daemon_fails_the_yank():
	def runner(command, **kwargs):
		raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"])

	result = copy("bv-y7or", runner=runner, which=only("pbcopy"))
	assert not result.ok
	assert "did not return" in result.message


def test_an_unrunnable_tool_reports_the_os_error():
	def runner(command, **kwargs):
		raise PermissionError(13, "Permission denied")

	result = copy("bv-y7or", runner=runner, which=only("pbcopy"))
	assert not result.ok
	assert "pbcopy" in result.message


# -- the keys, in both views ----------------------------------------------
#
# `y` has to mean the same thing on the tree and on the board, and the board is
# where that is easy to get wrong: the DataTable stays mounted and keeps its
# cursor while it is hidden, so a yank that reads the table copies whatever row
# the tree happens to be parked on. These drive the real app to prove it does
# not. The harness is local to this file for the reason test_board.py and
# test_preview.py each carry their own -- plain pytest, no async plugin.


class Yanked:
	"""Stands in for `clipboard.copy`, recording what the app handed it.

	Patched over `bv.app.copy` so no test can reach the clipboard of whoever is
	running the suite. `unavailable` makes the app take its OSC 52 path
	instead, which is the branch that has no subprocess to record.
	"""

	def __init__(self, *, unavailable=False, message=""):
		self.texts = []
		self._result = CopyResult(
			ok=not (unavailable or message),
			message=message,
			unavailable=unavailable,
		)

	def __call__(self, text):
		self.texts.append(text)
		return self._result


def drive(tmp_path, beans, scenario):
	"""Run `scenario` against a mounted app showing `beans`.

	The beans are pushed in rather than loaded: `load_all` shells out to the
	`beans` CLI, and what is under test is which bean the keys pick, not how
	they were read. Watching is switched off for the same reason -- a poll
	landing mid-scenario would reload the empty root and take the rows away.

	`XDG_CONFIG_HOME` is redirected because bv persists fold state and the
	theme, and a test suite must never write to the config of whoever runs it.
	"""
	home = tmp_path / "config-home"
	home.mkdir(parents=True, exist_ok=True)
	previous = os.environ.get("XDG_CONFIG_HOME")
	os.environ["XDG_CONFIG_HOME"] = str(home)

	async def main() -> None:
		app = BeansViewer(root=tmp_path)
		async with app.run_test(size=(120, 30)) as pilot:
			await pilot.pause()
			app._watching = False
			app._beans = beans
			app._rebuild_forest()
			app._render()
			await pilot.pause()
			await scenario(app, pilot)

	try:
		asyncio.run(main())
	finally:
		if previous is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = previous


async def press(pilot, key):
	"""Press `key` and wait for the copy worker it starts to finish."""
	await pilot.press(key)
	await pilot.app.workers.wait_for_complete()
	await pilot.pause()


def test_y_on_the_tree_yanks_the_row_under_the_cursor(tmp_path, monkeypatch):
	yanked = Yanked()
	monkeypatch.setattr(app_module, "copy", yanked)

	async def scenario(app, pilot):
		# Row 0 is the project heading; row 1 is the first bean.
		await pilot.press("j")
		await press(pilot, "y")
		assert yanked.texts == ["bv-y7or"]

	drive(tmp_path, [bean()], scenario)


def test_shift_y_on_the_tree_yanks_the_readable_line(tmp_path, monkeypatch):
	yanked = Yanked()
	monkeypatch.setattr(app_module, "copy", yanked)

	async def scenario(app, pilot):
		await pilot.press("j")
		await press(pilot, "Y")
		assert yanked.texts == [yank_line(bean())]

	drive(tmp_path, [bean()], scenario)


def test_a_project_heading_declines_rather_than_copying_nothing(tmp_path, monkeypatch):
	"""A third of the rows on a folded board carry no bean.

	Copying the empty string would look like a successful yank right up until
	the paste, which is the failure this whole module exists to avoid.
	"""
	yanked = Yanked()
	monkeypatch.setattr(app_module, "copy", yanked)

	async def scenario(app, pilot):
		assert app._current_bean() is None  # the cursor opens on the heading
		await press(pilot, "y")
		assert yanked.texts == []

	drive(tmp_path, [bean()], scenario)


def test_y_on_the_board_yanks_the_selected_card(tmp_path, monkeypatch):
	"""Not the table's cursor, which is still sitting on the project heading.

	If this regresses, `y` on the board silently declines -- or worse, copies
	the id of whatever the tree was parked on, which pastes as a real bean id
	from the wrong row.
	"""
	yanked = Yanked()
	monkeypatch.setattr(app_module, "copy", yanked)

	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		await press(pilot, "y")
		assert yanked.texts == ["bv-y7or"]

	drive(tmp_path, [bean()], scenario)


def test_the_board_hands_y_up_to_the_app(tmp_path, monkeypatch):
	"""The board binds its own keys; `y` is not one of them.

	Moving on the board must still leave `y` working, and must yank the card
	the move landed on.
	"""
	yanked = Yanked()
	monkeypatch.setattr(app_module, "copy", yanked)
	beans = [bean(), bean("aaaa", title="Second", status="in-progress")]

	async def scenario(app, pilot):
		await pilot.press("b")
		await pilot.pause()
		# in-progress is the first column, so the cursor opens on `aaaa`; `l`
		# moves to todo.
		await press(pilot, "y")
		await pilot.press("l")
		await pilot.pause()
		await press(pilot, "y")
		assert yanked.texts == ["bv-aaaa", "bv-y7or"]

	drive(tmp_path, beans, scenario)


def test_typing_y_into_the_filter_does_not_yank(tmp_path, monkeypatch):
	"""`y` is a letter before it is a key.

	App bindings only see what the focused widget did not want, and the filter
	wants every printable character -- but a yank firing on the way into
	"yank" would be unusable, so it is asserted rather than assumed.
	"""
	yanked = Yanked()
	monkeypatch.setattr(app_module, "copy", yanked)

	async def scenario(app, pilot):
		await pilot.press("slash")
		await pilot.pause()
		await press(pilot, "y")
		assert yanked.texts == []
		assert app.query_one(Input).value == "y"

	drive(tmp_path, [bean()], scenario)


def test_a_machine_with_no_clipboard_tool_still_falls_back(tmp_path, monkeypatch):
	"""OSC 52 through the terminal, emitted from the event loop.

	It has to happen on this side of the thread boundary -- it writes through
	the app's driver -- so the fallback is the app's job and is tested here
	rather than in `copy`.
	"""
	monkeypatch.setattr(app_module, "copy", Yanked(unavailable=True))

	async def scenario(app, pilot):
		await pilot.press("j")
		await press(pilot, "y")
		assert app._clipboard == "bv-y7or"

	drive(tmp_path, [bean()], scenario)


def test_a_failed_copy_says_so_instead_of_claiming_success(tmp_path, monkeypatch):
	monkeypatch.setattr(app_module, "copy", Yanked(message="pbcopy: write failed"))
	said = []

	async def scenario(app, pilot):
		app.notify = lambda message, **kwargs: said.append((message, kwargs))
		await pilot.press("j")
		await press(pilot, "y")
		assert said == [("pbcopy: write failed", {"severity": "error"})]

	drive(tmp_path, [bean()], scenario)


def test_a_successful_copy_quotes_what_it_copied(tmp_path, monkeypatch):
	"""The keypress must always have visible feedback.

	OSC 52 can be swallowed without a word, so the toast is the only proof the
	key did anything at all.
	"""
	monkeypatch.setattr(app_module, "copy", Yanked())
	said = []

	async def scenario(app, pilot):
		app.notify = lambda message, **kwargs: said.append(message)
		await pilot.press("j")
		await press(pilot, "y")
		assert said == ["copied bv-y7or"]

	drive(tmp_path, [bean()], scenario)


def test_a_long_yank_is_quoted_short(tmp_path, monkeypatch):
	# The longest real title is 96 characters; a toast that wraps to three
	# lines to echo something the user is about to paste is shouting.
	monkeypatch.setattr(app_module, "copy", Yanked())
	said = []
	long_title = "Preview render makes navigation laggy, and here is the rest of it"

	async def scenario(app, pilot):
		app.notify = lambda message, **kwargs: said.append(message)
		await pilot.press("j")
		await press(pilot, "Y")
		assert len(said[0]) <= len("copied ") + NOTIFY_WIDTH
		assert said[0].endswith("…")

	drive(tmp_path, [bean(title=long_title)], scenario)
