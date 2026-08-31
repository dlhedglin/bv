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

**The dispatch path never writes; the prompt asks the agent to.** The prompt
tells a dispatched agent to set its own bean to `in-progress` on start and
`completed` when the work is genuinely done -- see `prompt_for`. Every write on
*this* path is the agent's own, in the agent's own repo, through the agent's own
CLI, and dispatch never issues `beans update` nor learns whether one ran. What
changed is what bv *asks for*, which is text in a prompt. (The one place bv
itself writes is `edit.py`, behind the `e` key and its #208 guard -- a separate
path from anything here.)

Two consequences of beans 0.4.2 shipping #205 and #208 unpatched, now that
something does write:

- #208 (`beans update` strips unknown frontmatter keys) has nothing to strip
  today, since every bv bean carries only keys beans itself owns. It does make
  the README's sidecar rule load-bearing rather than precautionary: the moment
  bv writes metadata into bean frontmatter, a dispatched agent's own status
  update deletes it. The interactive editor guards its own writes against this
  by refusing a bean that carries an unknown key; the dispatch prompt cannot,
  since the write is the agent's.
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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar, TypeGuard

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .agents import session_name_for
from .beans import Bean

CLAUDE = "claude"
GIT = "git"

COMMAND_FLAGS = ("--bg", "--name")
"""`--bg, --background` and `-n, --name`, both confirmed present in
`claude --help` on 2.1.233. The long spellings are used so the command reads
the same in the confirmation dialog as it would typed by hand."""

ADD_DIR_FLAG = "--add-dir"
"""`--add-dir <directories...>`, confirmed present in `claude --help` on 2.1.245.
Added to a `W` command with the project's own `.beans` directory, so a worktree
agent can reach the board even when `.beans` is git-ignored.

`claude --worktree` was the earlier mechanism and is gone: it only ever branched
from `worktree.baseRef` (fresh -> origin/main, or head), which is not a base a
`W` dispatch can pick per spawn. bv now cuts the worktree itself with `git
worktree add -b <branch> <path> <base>` -- see `dispatch` -- so the branch it
forks from is the one the user chose in `PickBase`. The claude command that
follows runs in that worktree with no `--worktree` of its own.

Why `.beans` needs saying at all: Claude Code confines a session's tools to its
working directory and below, and a worktree lives beside the main checkout, not
under it. A tracked `.beans` is checked out into the worktree and needs nothing.
A git-ignored one is not -- the agent's `beans update` resolves the real store
by walking up to the main checkout, but writing there is outside the worktree
and blocked without this. Pointed at `.beans` rather than the whole root so the
grant is the board and not the main checkout's code -- isolation is the point of
`W`."""

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
NOTE_PLACEHOLDER = "extra instructions for the agent (optional)"

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

CHROME_HEIGHT = 15
"""What the dialog spends on everything that is not the prompt: two rows of
border, two of padding, one title, two for the cwd/name pair, two for the
prompt's own margins, one for the hint, and five for the note input (three for
the framed field, two for its margins). Measured off the rendered widget regions
rather than counted off the CSS, and used to keep the prompt from pushing the
hint out of the dialog on a short terminal."""

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

	Before the completed write, the agent checks its work against the bean --
	it reads its own diff and confirms each acceptance criterion is met by what
	actually changed, not by what it set out to do. This is the BMAD build
	step's "judge against the diff, not the report" gate, and it replaces the
	older bare "genuinely done" line, which named the standard without giving
	the agent a way to apply it. The criteria themselves are not restated in the
	prompt -- they live in the bean the agent already reads, and BMAD's own
	dispatch rule is that acceptance criteria belong in the spec, not the
	handoff.

	An epic- or feature-shaped bean, or any bean with children, is told to walk
	those children and order the work itself, fanning out with subagents where
	the children are independent. A `beans query` on the parent id returns the
	children directly -- id, title, status, type, priority -- so this is a query
	the agent can make from the id alone, without first knowing the child ids.

	The prose is caveman-compressed to shrink the per-dispatch prompt, but every
	command, the stop-on-failure line, the never-scrapped line and the
	in-progress-before-completed order are kept verbatim: they are load-bearing
	instructions where an omitted word changes what the agent does.
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
		f"Gives you body, status, priority, tags, blockers. If command\n"
		f"fails, stop and say so -- do not infer the task from the title.\n"
		f"\n"
		f"If it is an epic or feature, or has children, list them:\n"
		f"\n"
		f"    beans query --json '{{ bean(id: \"{bean.id}\") {{ children {{ id title status type priority }} }} }}'\n"
		f"\n"
		f"Read each child, decide what to start first, and fan out with\n"
		f"subagents where the children are independent.\n"
	)
	if worktree:
		return head + (
			f"\n"
			f"You run in an isolated git worktree on branch {branch_for(bean.id)}.\n"
			f"Your edits never touch the main checkout; they reach it only when this\n"
			f"branch merges, so nothing you do is visible on the board until then.\n"
			f"\n"
			f"Do the work here. Before closing, check your work against the bean:\n"
			f"read your diff, confirm every acceptance criterion met by what you\n"
			f"actually changed, not what you set out to do. Then mark completed:\n"
			f"\n"
			f"    {' '.join(update_command(bean.id, COMPLETED))}\n"
			f"\n"
			f"Then commit everything, including that status change, so it travels\n"
			f"with the merge:\n"
			f"\n"
			f'    git add -A && git commit -m "<what you did> ({bean.id})"\n'
			f"\n"
			f"If work partial, or something failing, commit what you have, leave\n"
			f"the bean {IN_PROGRESS}, say what is left. Never set it to {SCRAPPED}\n"
			f"-- not your call. If a `beans update` or the commit fails, stop and\n"
			f"say so -- do not retry it into a different status. A human merges\n"
			f"{branch_for(bean.id)} into the main checkout; do not merge it yourself."
		)
	return head + (
		f"\n"
		f"Then mark it started, before any work:\n"
		f"\n"
		f"    {' '.join(update_command(bean.id, IN_PROGRESS))}\n"
		f"\n"
		f"Before closing, check your work against the bean: read your diff,\n"
		f"confirm every acceptance criterion met by what you actually changed,\n"
		f"not what you set out to do. Only then:\n"
		f"\n"
		f"    {' '.join(update_command(bean.id, COMPLETED))}\n"
		f"\n"
		f"If work partial, or something failing, leave the bean {IN_PROGRESS},\n"
		f"say what is left. Never set it to {SCRAPPED} -- not your call. If\n"
		f"`beans update` fails, stop and say so, same as above --\n"
		f"do not retry it into a different status."
	)


NOTE_HEADER = "Also, from whoever dispatched you:"
"""Introduces the confirm-dialog note before the agent's own bean instructions
have been read, so free text the dispatcher typed is never mistaken for part of
the bean. `prompt_for` owns the standing prompt; this line is the seam a
per-spawn note is glued on at."""


def append_note(prompt: str, note: str) -> str:
	"""Glue a dispatcher's free-text note onto the end of a spawn prompt.

	The note is whatever the user typed in `ConfirmDispatch`'s input -- a nudge
	that belongs to this one spawn and not to every agent the bean will ever get,
	so it rides the prompt rather than the bean. Empty (the common case: the
	field is optional and usually blank) returns the prompt untouched, so an `S`
	or `W` with no note is byte-for-byte the prompt it always was.

	Sanitised like the title is, and for the same argv reason: the note becomes
	part of the single prompt argument `claude` is handed, and a NUL there
	truncates everything after it silently. The input is single-line, so newlines
	cannot arrive, but the NUL guard is cheap and the failure it prevents is
	invisible. Trailing and leading whitespace is stripped so a stray space bar
	does not count as a note and push the header onto an empty line.
	"""
	clean = note.replace("\x00", "").strip()
	if not clean:
		return prompt
	return f"{prompt}\n\n{NOTE_HEADER}\n\n{clean}"


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
	"""The worktree/branch name when this dispatch is isolated, else None. Set to
	the bean id by `request_for`, so it is None on an `S` dispatch and `bv-xxx`
	on a `W` one. Kept as the name rather than a bare bool so `command`,
	`dispatch` and `summary_text` render the exact strings the worktree is cut
	and named with. On a `W` dispatch `cwd` is the worktree, not the checkout."""

	base: str | None = None
	"""The branch a `W` worktree is cut from, chosen in `PickBase`. None -- on an
	`S` dispatch, or a `W` one the picker was skipped for -- lets `git worktree
	add` default to the checkout's current HEAD."""

	project_root: Path | None = None
	"""The main checkout, on a `W` dispatch only. `cwd` is the worktree there, so
	the root has to be carried separately: `git worktree add` runs in it, and its
	`.beans` is what `--add-dir` grants the isolated agent."""

	@property
	def command(self) -> list[str]:
		flags = [CLAUDE, "--bg"]
		if self.worktree and self.project_root is not None:
			flags += [ADD_DIR_FLAG, str(self.project_root / ".beans")]
		flags += ["--name", self.session_name]
		return [*flags, self.prompt]


def branch_for(worktree: str) -> str:
	"""The branch a `W` dispatch cuts: `worktree-<name>`.

	Named here, not hardcoded at the call sites, because the confirmation shows
	it, the merge-back instructions in `prompt_for` name it, `dispatch` cuts it
	and `worktree_path_for` names the directory after it -- they must all agree,
	and this is the one place the convention lives."""
	return f"worktree-{worktree}"


def worktree_path_for(project_root: Path, worktree: str) -> Path:
	"""Where a `W` dispatch's worktree lands: `.claude/worktrees/<branch>`.

	Under the checkout on purpose. `beans` finds a board by walking up from the
	working directory, so a worktree nested here resolves the main checkout's
	`.beans` for free -- the same directory `--add-dir` then grants write access
	to. It is also the path `claude --worktree` used, so nothing downstream that
	learned to look there has to change."""
	return project_root / ".claude" / "worktrees" / branch_for(worktree)


def local_branches(root: Path, runner: Runner = subprocess.run) -> list[str]:
	"""The local branch names in `root`, for `PickBase` to offer as bases.

	Read-only and best-effort: anything that is not a clean git listing -- no
	git, not a repo, a nonzero exit -- comes back empty, and the caller falls
	through to a HEAD-based cut rather than blocking the dispatch on a picker it
	cannot fill. `%(refname:short)` so the names read the way `git worktree add`
	takes them, one per line, no decoration and no current-branch asterisk.
	"""
	try:
		proc = runner(
			[GIT, "branch", "--format=%(refname:short)"],
			cwd=str(root),
			capture_output=True,
			text=True,
			timeout=DISPATCH_TIMEOUT,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return []
	if proc.returncode != 0:
		return []
	return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def current_branch(root: Path, runner: Runner = subprocess.run) -> str | None:
	"""The branch `root` is on, so `PickBase` can start the cursor there.

	None on a detached HEAD (the command prints nothing) or any failure -- the
	picker just opens on its first row instead. Best-effort for the same reason
	`local_branches` is."""
	try:
		proc = runner(
			[GIT, "branch", "--show-current"],
			cwd=str(root),
			capture_output=True,
			text=True,
			timeout=DISPATCH_TIMEOUT,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return None
	if proc.returncode != 0:
		return None
	return proc.stdout.strip() or None


def request_for(bean: Bean, project_root: Path, *, worktree: bool = False, base: str | None = None) -> DispatchRequest:
	"""Everything needed to spawn an agent for `bean`, decided up front.

	`project_root` is passed in rather than derived: a `Bean` carries its
	project's *name*, and only the app knows the board root it was discovered
	under.

	`worktree` is the `S`/`W` difference: `S` runs the agent in the checkout,
	editing it directly; `W` runs it in an isolated worktree bv cuts from `base`,
	whose code edits reach the board only when its branch is merged. `cwd` is the
	checkout for `S` and the worktree for `W` -- the worktree does not exist yet,
	`dispatch` creates it -- so a `W` request also carries `project_root`, which
	`git worktree add` and `--add-dir` both need and `cwd` no longer is. `base`
	is the branch to fork; None lets git default to the checkout's HEAD. The
	prompt changes with `worktree` -- see `prompt_for` -- because an agent that
	cannot touch the main checkout has to commit its work for a merge to carry.
	"""
	name = session_name_for(bean.id, bean.title)
	if worktree:
		return DispatchRequest(
			bean_id=bean.id,
			session_name=name,
			cwd=worktree_path_for(project_root, bean.id),
			prompt=prompt_for(bean, worktree=True),
			worktree=bean.id,
			base=base,
			project_root=project_root,
		)
	return DispatchRequest(
		bean_id=bean.id,
		session_name=name,
		cwd=project_root,
		prompt=prompt_for(bean),
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
	agent that spends tokens and can edit a real repo, and `git worktree add`
	writes to a real repo, so nothing in this package's test suite is allowed
	near the default.

	A `W` dispatch is two subprocesses: bv cuts the worktree, then spawns claude
	in it. If the cut fails -- a dirty base, a branch already taken, not a git
	repo -- claude is never reached and the git error is reported in its own
	words. If the cut lands but claude fails, the worktree is left on disk: a
	human merges or removes it, the same hand the merge-back instructions assume,
	and a retry would want the branch there anyway rather than silently gone.
	"""
	if request.worktree is not None:
		root = request.project_root
		if root is None or not root.is_dir():
			shown = display_path(root) if root is not None else "the project root"
			return DispatchResult(False, f"{shown} is not a directory")
		add = [GIT, "worktree", "add", "-b", branch_for(request.worktree), str(request.cwd)]
		if request.base:
			add.append(request.base)
		try:
			cut = runner(add, cwd=str(root), capture_output=True, text=True, timeout=DISPATCH_TIMEOUT, check=False)
		except FileNotFoundError:
			return DispatchResult(False, f"`{GIT}` not found on PATH -- is git installed?")
		except subprocess.TimeoutExpired:
			return DispatchResult(False, f"`{GIT} worktree add` did not return within {DISPATCH_TIMEOUT:g}s")
		except OSError as error:
			return DispatchResult(False, f"could not start `{GIT}`: {error}")
		if cut.returncode != 0:
			detail = (cut.stderr or cut.stdout or "").strip().splitlines()
			first = detail[0] if detail else f"exit {cut.returncode}"
			return DispatchResult(False, f"{GIT} worktree: {first}")
	elif not request.cwd.is_dir():
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
	# Only when isolated: on an `S` dispatch there is no branch, and these lines
	# would be noise on the common path. When present they are what tells the two
	# dispatch kinds apart -- and `base` is the whole reason the picker exists, so
	# the dialog names the branch the worktree forks from before it is cut.
	if request.worktree:
		rows.append(("branch", branch_for(request.worktree)))
		rows.append(("base", request.base or "HEAD"))
	text = Text()
	for label, value in rows:
		if text:
			text.append("\n")
		text.append(f"{label:<7}", style="dim")
		text.append(value)
	return text


CURRENT_MARK = " · current"
"""Appended to the checked-out branch in the picker. The board's own convention
is a trailing tag, and `git`'s leading `*` would have to be stripped back off
before the name reached `git worktree add`."""


class PickBase(ModalScreen[str | None]):
	"""Pick the branch a `W` worktree forks from.

	Dismisses with the chosen branch, or None on escape, so the app's callback is
	the one place a pick turns into a dispatch:

	    self.push_screen(PickBase(branches, current), self._base_picked)

	Never pushed empty. An empty branch list -- no git, a bare repo -- is the
	app's cue to cut from HEAD without asking, so the picker always has rows and
	its "nothing to pick" state does not have to be designed.

	The whole point over `claude --worktree`: that only ever forked from
	`worktree.baseRef`, a setting, not a per-spawn choice. Here the highlighted
	branch is exactly the base `git worktree add` is handed.
	"""

	BINDINGS: ClassVar[list[BindingType]] = [
		Binding("escape", "cancel", "Cancel"),
	]

	DEFAULT_CSS = """
    PickBase {
        align: center middle;

        & > #base-dialog {
            width: 60;
            max-width: 90%;
            height: auto;
            max-height: 90%;
            padding: 1 2;
            background: $surface;
            border: round $accent;
        }

        & #base-list {
            height: auto;
            max-height: 20;
            margin: 1 0;
            background: $panel;
        }

        & .base--title {
            text-style: bold;
        }

        & .base--hint {
            color: $text-muted;
        }
    }
    """

	TITLE_TEXT = "fork the worktree from which branch?"
	HINT_TEXT = "[enter] pick   [esc] cancel"

	def __init__(
		self,
		branches: list[str],
		current: str | None = None,
		*,
		name: str | None = None,
		id: str | None = None,
		classes: str | None = None,
	) -> None:
		super().__init__(name=name, id=id, classes=classes)
		self.branches = list(branches)
		self.current = current

	def compose(self) -> ComposeResult:
		with Vertical(id="base-dialog"):
			yield Static(Text(self.TITLE_TEXT), classes="base--title")
			options = [
				Option(branch + (CURRENT_MARK if branch == self.current else ""), id=branch) for branch in self.branches
			]
			yield OptionList(*options, id="base-list")
			yield Static(Text(self.HINT_TEXT), classes="base--hint")

	def on_mount(self) -> None:
		# Start the cursor on the branch the checkout is already on: the likeliest
		# base, and the one `claude --worktree`'s `head` default would have used.
		option_list = self.query_one(OptionList)
		if self.current in self.branches:
			option_list.highlighted = self.branches.index(self.current)
		option_list.focus()

	def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
		# Enter on the keyboard and a mouse click both arrive here -- the id is
		# the raw branch name, never the ` · current` label the row may show.
		self.dismiss(event.option.id)

	def action_cancel(self) -> None:
		self.dismiss(None)


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

        & #dispatch-note {
            margin: 1 0;
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
			# Optional free-text the dispatcher can add to this one spawn -- see
			# `append_note`. Below the prompt so it reads as an addition to what
			# the agent is already being told, not a replacement for it.
			yield Input(placeholder=NOTE_PLACEHOLDER, id="dispatch-note")
			yield Static(Text(HINT), classes="dispatch--hint")

	def on_mount(self) -> None:
		self._fit_prompt()
		# Focus the note input, not the prompt: the prompt is a fixed block of
		# instructions since bv-x62m, short enough to take in without scrolling,
		# so the cursor is more use waiting in the one field the user might type
		# in. `enter` in the input submits (see `on_input_submitted`) and `escape`
		# still reaches the screen, since Input binds neither and keys bubble.
		self.query_one("#dispatch-note").focus()

	def on_input_submitted(self, event: Input.Submitted) -> None:
		# Enter in the note field confirms, the same as enter anywhere else on the
		# dialog -- the input consumes the key, so the screen's `enter` binding
		# never sees it and the confirm has to be wired from here too.
		self.action_confirm()

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
		# Fold the note into the prompt only now, at confirm: the request stays the
		# thing the dialog showed, with the one field the dialog let the user add.
		# Empty input leaves the prompt byte-for-byte what `request_for` built.
		note = self.query_one("#dispatch-note", Input).value
		self.dismiss(replace(self.request, prompt=append_note(self.request.prompt, note)))

	def action_cancel(self) -> None:
		self.dismiss(None)
