"""Start a background Claude session on the bean under the cursor.

The point is attribution as much as convenience. bv chooses `--name` for every
session it starts, and `agents.session_name_for` puts the bean id in it, so a
session bv dispatched is matched back to its bean exactly rather than guessed at
from a working directory. Sessions bv did not start stay in the coarse tier.

**Confirm, then dispatch.** `enter` on a bean does not spawn anything; it opens
`ConfirmDispatch`, which shows the working directory, the session name and the
whole prompt, and only then spends tokens. Firing on a single keypress was
considered and rejected: there is no undo beyond `claude stop`, and the cost of
a wrong row is an agent editing the wrong repo. While the sibling bean was being
written, probing `claude --bg --name` in a shell spawned a real idle session by
accident -- the confirmation exists because that failure has already happened to
someone who knew exactly what the flag did.

**Advisory, never a lock.** The confirmation says when a session is already
working the bean, and then dispatches anyway if you press enter. beans has no
assignee field to hold a claim, so there is nothing a second bv -- or a `claude`
typed by hand -- would have to respect. See `ALREADY_WORKING`.

**bv still never writes; the prompt asks the agent to.** The prompt tells a
dispatched agent to set its own bean to `in-progress` on start and `completed`
when the work is genuinely done -- see `prompt_for`. That is not a reversal of
"bv is read-only": every write is the agent's own, in the agent's own repo,
through the agent's own CLI, and this process never issues `beans update` nor
learns whether one ran. What changed is what bv *asks for*, which is text in a
prompt.

Two consequences of beans 0.4.2 shipping #205 and #208 unpatched, now that
something does write:

- #208 (`beans update` strips unknown frontmatter keys) has nothing to strip
  today, since every bv bean carries only keys beans itself owns. It does make
  the README's sidecar rule load-bearing rather than precautionary: the moment
  bv writes metadata into bean frontmatter, a dispatched agent's own status
  update deletes it.
- #205 (`--if-match` CAS loses one of two concurrent writes) now has a live path
  to it, because two agents on one bean is exactly the case `ALREADY_WORKING`
  declines to lock against. That stays advisory. Named here as a failure mode,
  not as an argument for a mutex bv cannot enforce anyway.

**The screen dismisses with a request; it does not run it.** The app owns the
side effect, because dispatch is ~170 ms of blocking subprocess -- the same
order as `claude agents --json` -- and has to happen off the event loop. A
screen that shelled out in its own action handler would stall the UI for a
sixth of a second at the exact moment the user is watching it.

Everything that decides *what* gets run is a module-level function over a
`Bean`, so the prompt, the command and the failure messages are all testable
without standing up an app. The widget is plumbing. Nothing here is exercised
against a real `claude`: every test passes a fake runner, which is why `dispatch`
takes one.

Open, and deliberately not answered here: whether `--permission-mode` should be
pinned rather than inherited. A dispatched agent currently lands in whatever
mode the daemon defaults to. See bv-9sxj.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, TypeGuard

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from .agents import session_name_for
from .beans import Bean

CLAUDE = "claude"

COMMAND_FLAGS = ("--bg", "--name")
"""`--bg, --background` and `-n, --name`, both confirmed present in
`claude --help` on 2.1.233. The long spellings are used so the command reads
the same in the confirmation dialog as it would typed by hand."""

WORKTREE_FLAG = "--worktree"
"""`-w, --worktree [name]`, confirmed present in `claude --help` on 2.1.234.
Added to the command only when a dispatch asks for isolation (the `W` binding,
not `S`); `claude` then creates `.claude/worktrees/<name>/` on branch
`worktree-<name>`, branched fresh from origin/main, and starts the agent in it.
The name bv passes is the bean id, so the branch and directory carry the same
id the session name and the Agent column already match on. Long spelling for
the same reason as `COMMAND_FLAGS`: the confirmation reads like a typed line."""

DISPATCH_TIMEOUT = 30.0
"""Backstop, not a budget. The call itself is ~170 ms because `--bg` hands the
job to the supervisor daemon and returns; this only exists so a daemon that is
wedged fails the dispatch instead of pinning the worker thread forever."""

IN_PROGRESS = "in-progress"
COMPLETED = "completed"
SCRAPPED = "scrapped"
"""The three beans statuses the prompt names, spelled as `beans update
--status` accepts them -- confirmed against `beans update --help` on 0.4.2,
which lists in-progress, todo, draft, completed and scrapped. `scrapped`
appears only to be forbidden."""

TITLE = "spawn a background agent?"
HINT = "[enter] dispatch   [esc] cancel"

ALREADY_WORKING = "{label} is already working this bean"
"""Said, not enforced.

There is nothing to lock against: beans has no assignee field -- probed and
confirmed -- so a claim cannot be written where another bv, or a `claude` typed
by hand, would see it. Any guard is advisory and lives entirely in this
process, and the honest shape for that is a sentence in the confirmation rather
than a refusal that pretends to be a mutex it is not.

Phrased as a fact for the same reason it is not a block: wanting a second agent
is legitimate. The first may be wedged, or finished without saying so, or on
the wrong half of the bean. What the user needs is to know before spending the
tokens, which is exactly what a dialog they are already reading can give them.

Only ever exact attribution -- see `app._agent_on`."""

CHROME_HEIGHT = 10
"""What the dialog spends on everything that is not the prompt: two rows of
border, two of padding, one title, two for the cwd/name pair, two for the
prompt's own margins and one for the hint. Measured off the rendered widget
regions rather than counted off the CSS, and used to keep the prompt from
pushing the hint out of the dialog on a short terminal."""

WARNING_HEIGHT = 1
"""The extra row of chrome a warning line costs, added to CHROME_HEIGHT only
when there is one. Left out, a warned dialog fits its prompt to a height one
row taller than it has, and the row it overflows by is the hint."""

MIN_PROMPT_HEIGHT = 3
"""Floor for the prompt pane. Below a terminal of about `CHROME_HEIGHT +
MIN_PROMPT_HEIGHT` rows the dialog is taller than the screen and clips, which
is preferred to a prompt pane shrunk to nothing -- a confirmation you cannot
read is not a confirmation."""

# subprocess.run's signature, loosely. A Protocol pinning every keyword would
# have to be updated in two places whenever the call changes, and would make
# every fake in the tests longer than the test using it.
Runner = Callable[..., subprocess.CompletedProcess[str]]


def can_dispatch(bean: Bean | None) -> TypeGuard[Bean]:
	"""Whether there is anything to dispatch on the row under the cursor.

	Project headings carry no bean, and they are a third of the rows on a
	folded board, so the caller needs to ask before offering the action.

	Status is deliberately not consulted. Spawning an agent on a completed bean
	is probably a mistake, but it is a legible one -- the confirmation names the
	bean -- and refusing it here would also refuse the case where a completed
	bean turned out not to be finished after all.

	A `TypeGuard`, not a plain `bool`, so the caller's `if not can_dispatch(...)`
	guard actually narrows the `Bean | None` it is guarding.
	"""
	return bean is not None


def already_working(label: str | None) -> str:
	"""The warning line for the confirmation, or empty when nobody is on it.

	Takes the session's label rather than an `Attribution` so this module stays
	clear of the session layer, the same way `agents.attribute_all` takes
	triples rather than Beans.
	"""
	return ALREADY_WORKING.format(label=label) if label else ""


def display_path(path: Path) -> str:
	"""`~/projects/bv` rather than `/Users/…/projects/bv`.

	The dialog is read at a glance to answer "is this the right repo", and a
	home prefix repeated on every line is the part that is never in question.
	"""
	try:
		return f"~/{path.relative_to(Path.home())}"
	except ValueError:
		return str(path)


def prompt_for(bean: Bean, *, worktree: bool = False) -> str:
	"""The prompt handed to the dispatched agent.

	`worktree` swaps the tail, not the head. The header and the read-it-first
	block are identical either way; what changes is what the agent does with the
	result.

	The direct form (default, the `S` binding) tells the agent to move its bean
	to `in-progress` on start and `completed` when done -- the writes land in the
	one checkout everyone reads, so the board sees them live.

	The worktree form (the `W` binding) cannot do that: the agent is isolated in
	`.claude/worktrees/<id>` and Claude Code blocks it from touching the main
	checkout, so a status write there lands in the worktree's own copy of
	`.beans` and reaches the board only when the branch merges. Two consequences
	shape the worktree tail:

	- `in-progress` is dropped. It would write a copy nobody reads and be
	  overwritten by `completed` at merge anyway; the board shows the bean moving
	  from the session itself (the Agent column, which is not a git fact), so the
	  live signal does not need the file.
	- the agent is told to **commit**. An uncommitted worktree carries nothing
	  into a merge and blocks `git worktree remove`; the `completed` status has to
	  be in that commit so it travels with the code. Order matters and is spelled
	  out: mark completed, then commit, so the status change is in the commit.

	Everything below about the direct form still holds for it.

	The id, the title, and how to read the rest. The body is deliberately not
	inlined -- see bv-x62m.

	Inlining was the first shape and it was 98% of the prompt by volume
	(median 2501 chars, p90 6875, max 23879 across 222 live beans, against 66
	for id and title). Volume was the least of the problem:

	An inlined body is a **snapshot** taken at dispatch and never refreshed, so
	an agent works stale text the moment anyone edits the bean -- and bodies in
	this repo get rewritten routinely. It is also **not the whole bean**: no
	status, no priority, no blockers, no parent, no children. And the agent
	needs the CLI regardless, to close the bean or file what it finds, so
	naming the command costs nothing it was not going to pay.

	`--json` rather than plain `beans show`: the rendered form hard-wraps
	markdown at ~78 columns, which mangles any code block in the body. The JSON
	form returns `body` verbatim alongside status, priority, tags and etag.

	The stop instruction is the whole reason this is safe. A query that fails
	-- no `beans` on PATH, a cwd that resolves no `.beans.yml` -- otherwise
	leaves an agent holding a title and an inclination to guess. Inlining
	guaranteed the body arrived; this has to replace that guarantee with an
	explicit halt, or it is a downgrade.

	Title is kept even though the agent will fetch it again: it is what makes
	the session name and the `claude agents` list readable, and it is 66 chars.

	The status instructions are the agent's own writes, not bv's -- see the
	module docstring. Without them a bean stays `todo` for the whole life of the
	agent working it, and is still `todo` after the work lands, so a board read
	the next morning cannot tell "nobody has started this" from "an agent
	finished this last night": the Agent column and the session name are the
	only evidence either way, and both die with the session.

	`in-progress` immediately on start rather than at the first edit. That is
	the point where attribution starts outliving the session, and it is honest
	about something being on the bean. The cost is a bean stuck `in-progress`
	when an agent dies -- which is visible and correctable, where a silent
	`todo` is neither.

	`completed` only when the work is genuinely finished. An agent that closes a
	bean it half-did is worse than one that never touches the status, so the
	partial case is named explicitly and left `in-progress`.

	Never `scrapped`: deciding a bean is not worth doing is not a dispatched
	agent's call.

	The stop rule extends to the write. A failed `beans update` is reported the
	way a failed `beans show` is, rather than retried into some other status.
	"""
	header = f"Work bean {bean.id}"
	title = _argv_safe(bean.title)
	if title:
		header = f"{header}: {title}"
	head = (
		f"{header}\n"
		f"\n"
		f"Read it first:\n"
		f"\n"
		f"    {' '.join(show_command(bean.id))}\n"
		f"\n"
		f"That gives you the body, status, priority, tags and blockers. If the\n"
		f"command fails, stop and say so -- do not infer the task from the title.\n"
	)
	if worktree:
		return head + (
			f"\n"
			f"You are running in an isolated git worktree on branch\n"
			f"{branch_for(bean.id)}. Your edits do not touch the main checkout; they\n"
			f"reach it only when this branch is merged, so nothing you do is visible\n"
			f"on the board until then.\n"
			f"\n"
			f"Do the work here. When it is genuinely done -- finished and passing,\n"
			f"not merely edited -- mark the bean completed:\n"
			f"\n"
			f"    {' '.join(update_command(bean.id, COMPLETED))}\n"
			f"\n"
			f"Then commit everything, including that status change, so it travels\n"
			f"with the merge:\n"
			f"\n"
			f'    git add -A && git commit -m "<what you did> ({bean.id})"\n'
			f"\n"
			f"If the work is partial, or something is failing, commit what you\n"
			f"have, leave the bean {IN_PROGRESS}, and say what is left.\n"
			f"Never set it to {SCRAPPED} -- that is not a call for you to make.\n"
			f"If a `beans update` or the commit fails, stop and say so -- do not\n"
			f"retry it into a different status. A human merges {branch_for(bean.id)}\n"
			f"into the main checkout; do not merge it yourself."
		)
	return head + (
		f"\n"
		f"Then mark it started, before doing any of the work:\n"
		f"\n"
		f"    {' '.join(update_command(bean.id, IN_PROGRESS))}\n"
		f"\n"
		f"Close it yourself when the work is genuinely done -- finished and\n"
		f"passing, not merely edited:\n"
		f"\n"
		f"    {' '.join(update_command(bean.id, COMPLETED))}\n"
		f"\n"
		f"If the work is partial, or something is failing, leave the bean\n"
		f"{IN_PROGRESS} and say what is left. Never set it to {SCRAPPED} -- that\n"
		f"is not a call for you to make. If a `beans update` fails, stop and\n"
		f"say so, the same as above -- do not retry it into a different status."
	)


def _argv_safe(text: str) -> str:
	"""Strip what would corrupt the prompt at the `execve` boundary.

	Specific to argv rather than to markdown: a NUL anywhere in the string
	truncates the argument, delivering a prompt that stops mid-sentence with
	nothing reporting a problem. A newline in a title would break the shape of
	the prompt below it.

	The body used to carry this risk and no longer reaches argv at all, but the
	title still does.
	"""
	return "".join(ch for ch in text if ch == " " or ch.isprintable()).strip()


def show_command(bean_id: str) -> tuple[str, ...]:
	"""How the agent reads its own bean.

	A tuple so the test suite compares the real thing rather than a string it
	also had to build. Run from the project root, which is the `cwd` bv sets,
	so `beans` resolves the right `.beans.yml` by searching upward.
	"""
	return ("beans", "show", bean_id, "--json")


def update_command(bean_id: str, status: str) -> tuple[str, ...]:
	"""How the agent moves its own bean.

	Never run by bv -- this only ever renders into a prompt. Same shape as
	`show_command` for the same reason, and `--status` in its long spelling so
	the line reads the same in the confirmation dialog as it would typed by
	hand.

	No `--if-match`: the etag the agent would have to pass comes from its own
	`beans show`, and beans 0.4.2 ships #205, where CAS loses one of two
	concurrent writes anyway. A bare update at least fails loudly rather than
	appearing to succeed.
	"""
	return ("beans", "update", bean_id, "--status", status)


@dataclass(frozen=True)
class DispatchRequest:
	"""One dispatch, fully decided and not yet run.

	This is what `ConfirmDispatch` dismisses with, so the caller can hand it
	straight to `dispatch` on a thread. Everything the user was shown is on it,
	which means the thing that runs is the thing that was confirmed rather than
	something rebuilt from the cursor after the fact -- the board reloads on a
	0.5 s poll, and the cursor can have moved by then.
	"""

	bean_id: str
	session_name: str
	cwd: Path
	prompt: str
	worktree: str | None = None
	"""The `--worktree` name when this dispatch is isolated, else None. Set to
	the bean id by `request_for`, so it is None on an `S` dispatch and `bv-xxx`
	on a `W` one. Kept as the name rather than a bare bool so `command` and
	`summary_text` render the exact string `claude` will act on."""

	@property
	def command(self) -> list[str]:
		flags = [CLAUDE, "--bg"]
		if self.worktree:
			flags += [WORKTREE_FLAG, self.worktree]
		flags += ["--name", self.session_name]
		return [*flags, self.prompt]


def branch_for(worktree: str) -> str:
	"""The branch `claude --worktree <name>` creates: `worktree-<name>`.

	Named here, not hardcoded at the call sites, because the confirmation shows
	it and the merge-back instructions in `prompt_for` name it -- the two must
	agree, and this is the one place the convention lives."""
	return f"worktree-{worktree}"


def request_for(bean: Bean, project_root: Path, *, worktree: bool = False) -> DispatchRequest:
	"""Everything needed to spawn an agent for `bean`, decided up front.

	`project_root` is passed in rather than derived: a `Bean` carries its
	project's *name*, and only the app knows the board root it was discovered
	under.

	`worktree` is the `S`/`W` difference and nothing else routes it: `S` calls
	with the default and the agent edits the project's checkout directly; `W`
	passes True and the agent lands in an isolated worktree whose edits reach
	the board only when its branch is merged. The prompt changes with it -- see
	`prompt_for` -- because an agent that cannot touch the main checkout has to
	commit its work for a merge to carry, where one editing the checkout does
	not.
	"""
	return DispatchRequest(
		bean_id=bean.id,
		session_name=session_name_for(bean.id, bean.title),
		cwd=project_root,
		prompt=prompt_for(bean, worktree=worktree),
		worktree=bean.id if worktree else None,
	)


@dataclass(frozen=True)
class DispatchResult:
	"""How it went, phrased for `App.notify`."""

	ok: bool
	message: str


def dispatch(request: DispatchRequest, runner: Runner = subprocess.run) -> DispatchResult:
	"""Spawn the background session. Blocking -- call it off the event loop.

	Returns rather than raises, because the only caller is a thread worker and
	an exception crossing that boundary is more plumbing than a flag. Every
	failure has to arrive as a sentence a user can act on: `claude` missing from
	PATH is the likeliest one on a fresh machine, and it surfaces from
	`subprocess` as a bare FileNotFoundError that reads like a bug in bv.

	A missing project root is checked before the spawn rather than after. It
	fails inside `subprocess` too, but as the same FileNotFoundError the missing
	binary raises -- indistinguishable from the outside, and the two want
	completely different answers from the user.

	`runner` exists so tests never spawn anything. `claude --bg` starts a real
	agent that spends tokens and can edit a real repo, so nothing in this
	package's test suite is allowed near the default.
	"""
	if not request.cwd.is_dir():
		return DispatchResult(False, f"{display_path(request.cwd)} is not a directory")

	try:
		proc = runner(
			request.command,
			cwd=str(request.cwd),
			capture_output=True,
			text=True,
			timeout=DISPATCH_TIMEOUT,
			# check=False so a nonzero exit is inspected below and reported in
			# claude's own words, rather than as a CalledProcessError repr.
			check=False,
		)
	except FileNotFoundError:
		return DispatchResult(False, f"`{CLAUDE}` not found on PATH -- is Claude Code installed?")
	except subprocess.TimeoutExpired:
		return DispatchResult(False, f"`{CLAUDE}` did not return within {DISPATCH_TIMEOUT:g}s")
	except OSError as error:
		# Not executable, out of processes, cwd vanished between the check
		# above and the spawn.
		return DispatchResult(False, f"could not start `{CLAUDE}`: {error}")

	if proc.returncode != 0:
		detail = (proc.stderr or proc.stdout or "").strip().splitlines()
		first = detail[0] if detail else f"exit {proc.returncode}"
		return DispatchResult(False, f"{CLAUDE}: {first}")

	return DispatchResult(True, f"dispatched {request.session_name}")


def summary_text(request: DispatchRequest) -> Text:
	"""The two lines above the prompt: where it runs, and what it will be called.

	A `Text`, not a markup string. So is the prompt itself, and that one is not
	cosmetic: bean bodies contain markdown links and pasted terminal output, so
	`[broken](` and `[bold]` both occur, and Textual would read them as markup.
	Measured on 8.2.8, `Static("[broken]( and [bold]unclosed")` paints
	`( and unclosed` -- silently, with no error anywhere. A dialog whose whole
	job is to show the prompt before it is sent must not show a different one.
	"""
	rows = [
		("cwd", display_path(request.cwd)),
		("name", request.session_name),
	]
	# Only when isolated: on an `S` dispatch there is no branch, and a line
	# saying so would be noise on the common path. When present it is the one
	# fact that tells the two dispatch kinds apart in the dialog.
	if request.worktree:
		rows.append(("branch", branch_for(request.worktree)))
	text = Text()
	for label, value in rows:
		if text:
			text.append("\n")
		text.append(f"{label:<7}", style="dim")
		text.append(value)
	return text


class ConfirmDispatch(ModalScreen[DispatchRequest | None]):
	"""Show what is about to happen, and wait.

	Dismisses with the request on `enter` and with None on `escape`, so the
	caller's callback is the single place that decides to spend anything:

	    self.push_screen(ConfirmDispatch(request), self._spawn)
	"""

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("enter", "confirm", "Dispatch"),
		Binding("escape", "cancel", "Cancel"),
	]

	DEFAULT_CSS = """
    ConfirmDispatch {
        align: center middle;

        & > #dispatch-dialog {
            width: 76;
            max-width: 90%;
            height: auto;
            max-height: 90%;
            padding: 1 2;
            background: $surface;
            border: round $accent;
        }

        /* No cap here: `max-height` is set from `_fit_prompt`, because the
           right value depends on the terminal. `height: 1fr` was tried in its
           place and does nothing -- the dialog is auto-height, so a fr child
           resolves to its own content and overflows exactly as before. */
        & #dispatch-prompt {
            height: auto;
            margin: 1 0;
            padding: 0 1;
            background: $panel;
        }

        & .dispatch--title {
            text-style: bold;
        }

        & .dispatch--warning {
            color: $warning;
            text-style: bold;
        }

        & .dispatch--hint {
            color: $text-muted;
        }
    }
    """

	def __init__(
		self,
		request: DispatchRequest,
		*,
		warning: str = "",
		name: str | None = None,
		# `id` shadows the builtin; it is Textual's own widget kwarg name.
		id: str | None = None,
		classes: str | None = None,
	) -> None:
		super().__init__(name=name, id=id, classes=classes)
		self.request = request
		# Not a field on the request: the request is what will run, and this is
		# a fact about the world at the moment it was offered. It also comes
		# from the session layer, which nothing else on the request touches.
		self.warning = warning

	def compose(self) -> ComposeResult:
		with Vertical(id="dispatch-dialog"):
			yield Static(Text(TITLE), classes="dispatch--title")
			yield Static(summary_text(self.request))
			# Above the prompt, not below it: on a short terminal the prompt is
			# the pane that scrolls, and a warning under it could be scrolled
			# past without ever being seen.
			if self.warning:
				yield Static(Text(self.warning), classes="dispatch--warning")
			with VerticalScroll(id="dispatch-prompt"):
				yield Static(Text(self.request.prompt))
			yield Static(Text(HINT), classes="dispatch--hint")

	def on_mount(self) -> None:
		self._fit_prompt()
		# Focus the prompt, not the dialog: the body is the part worth reading
		# before saying yes, and this makes the arrow keys scroll it without a
		# tab first. `enter` and `escape` still reach the screen, because keys
		# bubble from the focused widget and neither is bound below it.
		self.query_one("#dispatch-prompt").focus()

	def on_resize(self) -> None:
		self._fit_prompt()

	def _fit_prompt(self) -> None:
		"""Give the prompt whatever the rest of the dialog does not need.

		A pure-CSS cap cannot do this: the dialog is auto-height, so a prompt
		clamped at a constant keeps that height on a short terminal and the
		dialog overflows downwards -- silently, taking the hint line with it,
		since the dialog does not scroll. Measured at 14 rows with a
		23,783-character body, the hint landed 15 rows below the screen.

		There is no constant ceiling any more. One existed at 20 rows while the
		prompt carried the bean body and could be thousands; since bv-x62m it
		is a fixed block of instructions around a title, so a cap is a number
		that has to be kept above the prompt's own length by hand -- and
		bv-pg4k, which added the status lines, is exactly the edit that would
		silently push past it. The room the dialog has is the only real bound.
		"""
		chrome = CHROME_HEIGHT + (WARNING_HEIGHT if self.warning else 0)
		room = max(MIN_PROMPT_HEIGHT, self.size.height - chrome)
		self.query_one("#dispatch-prompt").styles.max_height = room

	def action_confirm(self) -> None:
		self.dismiss(self.request)

	def action_cancel(self) -> None:
		self.dismiss(None)
