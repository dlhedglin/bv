"""Yank the bean under the cursor onto the system clipboard.

The id is the join key for everything outside bv -- `beans show`, a commit
message, a prompt to an agent, a message to a person -- so handing it over is
the one thing a board is best placed to do.

**Not `App.copy_to_clipboard` first.** Textual 8.2.8 has it, and its own
docstring says it "does not work on macOS Terminal, but will work on most other
terminals". It emits OSC 52 and returns; whether the terminal honours the
sequence is unknowable from here, and when it does not, nothing happens and
nothing says so. The user finds out at the paste, which is the worst possible
place. A clipboard binary -- `pbcopy` on macOS, `wl-copy`/`xclip`/`xsel` on
Linux -- talks to the clipboard directly and reports an exit code, so it is
tried first and OSC 52 is what is left when there is none.

**Measured, not assumed.** `dispatch.py` refuses to shell out on the event loop
because its subprocess is ~170 ms. `pbcopy` is nowhere near that -- 6.8 ms
median over 12 runs on this machine -- but 6.8 ms is still a third of a 60 Hz
frame spent blocking, and the app already has the `to_thread` idiom for exactly
this. The caller runs `copy` on a thread.

Everything that decides *what* is yanked is a plain function over a `Bean`, and
`copy` takes a runner, so none of this needs an app -- or the real clipboard --
to test. The tests must never leave anything on the clipboard of whoever is
running them, which is why the default runner is only ever reached from the app.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .beans import Bean

COMMANDS: tuple[tuple[str, ...], ...] = (
	("pbcopy",),
	("wl-copy",),
	("xclip", "-selection", "clipboard"),
	("xsel", "--clipboard", "--input"),
)
"""Clipboard writers, in the order they are tried.

`pbcopy` is macOS and is present on every install of it. The other three are
the Linux ones a terminal user is likely to already have -- Wayland first,
because a Wayland session can still have `xclip` installed and pointed at an
Xwayland clipboard nobody is reading. Nothing is installed on the user's
behalf; a machine with none of them falls back to OSC 52.
"""

COPY_TIMEOUT = 5.0
"""Backstop, not a budget. The call is ~7 ms; this exists so a wedged clipboard
daemon fails the yank instead of pinning the worker thread forever."""

SEPARATOR = " — "
"""Between the id and the title on the human-readable yank. An em dash rather
than a hyphen because titles contain hyphens, and the point of the line is that
a reader can tell where the id stops."""

UNTITLED = "(untitled)"
"""A bean with no title still yanks to something a human can act on -- the id
is right there beside it. Spelled the same as `board.UNTITLED`, and duplicated
for the reason `board.STATUS_STYLES` is: `app.py` imports both of these
modules, so the dependency cannot run the other way."""

# subprocess.run's signature, loosely -- the same shape, and the same reason,
# as dispatch.Runner.
Runner = Callable[..., subprocess.CompletedProcess[str]]


def yank_id(bean: Bean) -> str:
	"""`bv-4pli`. What gets pasted into a command.

	The project prefix stays. On screen it is redundant -- the tree groups by
	project and every card names one -- but the moment the id leaves bv it is
	the only context there is, and `beans show 4pli` resolves nothing.
	"""
	return bean.id


def yank_line(bean: Bean) -> str:
	"""`bv-4pli — Preview render makes navigation laggy (todo)`.

	What gets pasted into a message, so it is one line rather than a block:
	the paste target is a chat message, a commit subject or a PR title, and
	every one of those is somewhere a four-line block has to be reflowed by
	hand. Anything longer than a line is a bean body, and `beans show` already
	prints that better than bv could.

	Status is on it because the id and the title together still do not say
	whether the thing is done, which is the first question anyone reading the
	line asks.
	"""
	return f"{bean.id}{SEPARATOR}{one_line(bean.title) or UNTITLED} ({bean.status})"


def one_line(text: str) -> str:
	"""Flatten to something safe to paste anywhere.

	A NUL is dropped for the reason `dispatch._argv_safe` drops it: it
	truncates the string at whatever consumes it, silently. Newlines and tabs
	collapse to spaces because a yank that pastes as two lines turns a chat
	message into two, and a tab pasted into a terminal fires its completion.
	"""
	kept = (ch if ch.isprintable() else " " for ch in text)
	return " ".join("".join(kept).split())


@dataclass(frozen=True)
class CopyResult:
	"""How the copy went, phrased for `App.notify`.

	`unavailable` is not a failure: it means no clipboard binary was found and
	the caller should fall back to OSC 52, which it has to do itself because
	that writes through the app's driver rather than through a subprocess.
	"""

	ok: bool
	message: str = ""
	unavailable: bool = False


def copy_command(which: Callable[[str], str | None] = shutil.which) -> tuple[str, ...]:
	"""The first clipboard writer on PATH, or `()` if there is none.

	`which` is injected so the tests can pin the answer instead of asking the
	machine they happen to run on -- a test that only passes on macOS is not a
	test of this function.
	"""
	for command in COMMANDS:
		if which(command[0]):
			return command
	return ()


def copy(
	text: str,
	runner: Runner = subprocess.run,
	which: Callable[[str], str | None] = shutil.which,
) -> CopyResult:
	"""Put `text` on the clipboard. Blocking -- call it off the event loop.

	Returns rather than raises, matching `dispatch.dispatch`: the only caller is
	a thread worker, and every failure has to arrive as a sentence a user can
	act on rather than as a traceback in a TUI that has just repainted over it.

	Both seams are injected so the tests reach neither the PATH of the machine
	they run on nor the clipboard of whoever is running them.
	"""
	command = copy_command(which)
	if not command:
		return CopyResult(False, unavailable=True)

	try:
		proc = runner(
			command,
			input=text,
			capture_output=True,
			text=True,
			timeout=COPY_TIMEOUT,
			# check=False so a nonzero exit is reported in the tool's own words
			# rather than as a CalledProcessError repr.
			check=False,
		)
	except FileNotFoundError:
		# `which` said yes and the exec said no: the binary went away between
		# the two calls, or it is a dangling symlink.
		return CopyResult(False, f"`{command[0]}` disappeared from PATH")
	except subprocess.TimeoutExpired:
		return CopyResult(False, f"`{command[0]}` did not return within {COPY_TIMEOUT:g}s")
	except OSError as error:
		return CopyResult(False, f"could not run `{command[0]}`: {error}")

	if proc.returncode != 0:
		detail = (proc.stderr or proc.stdout or "").strip().splitlines()
		first = detail[0] if detail else f"exit {proc.returncode}"
		return CopyResult(False, f"{command[0]}: {first}")

	return CopyResult(True)
