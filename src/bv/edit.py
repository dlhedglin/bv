"""Write a bean's properties by shelling out to `beans update` / `beans archive`.

The counterpart to `beans.py`, which is read-only on purpose. bv was built to
never mutate a bean because beans 0.4.2 ships two unpatched write bugs
(hmans/beans#205, #208) -- see `beans.py`'s module docstring. This module opens
a narrow, guarded write path anyway, for the small interactive edits that
otherwise force a user out of bv and into a terminal.

Two things keep it safe against the bugs:

- #208 -- `beans update` rewrites the file and drops any frontmatter key
  outside beans' own schema. `custom_frontmatter_keys` reads the target file
  first; the app refuses the edit when it would destroy a key beans does not
  know. Verified against installed 0.4.2: an injected `custom_key` is stripped
  by a plain `beans update --status`.

- #205 -- `--if-match` CAS silently loses one of two concurrent writes, so this
  module does *not* pass `--if-match`: a bare update is last-writer-wins and at
  least fails loudly on a bad id, where buggy CAS would appear to succeed while
  dropping a write. Same reasoning `dispatch.update_command` already records.
  Interactive single-field edits are low-concurrency; the residual race is
  documented, not locked against a fix that upstream has not shipped.

Everything here is pure and runner-injected so the test suite never touches a
real store: no function reads global state, and `run_edit` takes the same
`runner` seam `dispatch` uses.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .dispatch import Runner

BEANS = "beans"

# The complete set of frontmatter keys `beans` 0.4.2 writes and round-trips.
# Any key on a bean outside this set is one #208 would silently drop on the
# next `beans update`, so the guard treats its presence as a reason to refuse.
# Gathered from the keys beans actually emits -- title/status/type/priority/
# tags/created_at/updated_at/parent/blocked_by -- plus `blocking`, the mirror
# beans writes on the other side of a block. The `# <id>` first line of the
# frontmatter is a YAML comment, not a key, and never appears here.
KNOWN_KEYS = frozenset(
	{
		"title",
		"status",
		"type",
		"priority",
		"tags",
		"created_at",
		"updated_at",
		"parent",
		"blocked_by",
		"blocking",
	}
)

EDIT_TIMEOUT = 30.0
"""Seconds a single `beans update`/`archive` may take before bv gives up. The
same order as the read path's 30 s in `fetch_project_beans`; a write is one
process spawn and a small file rewrite, nowhere near it in practice."""


@dataclass(frozen=True)
class EditResult:
	"""How a write went, phrased for `App.notify`. Mirrors `DispatchResult`."""

	ok: bool
	message: str


def custom_frontmatter_keys(bean_file: Path) -> tuple[str, ...]:
	"""Top-level frontmatter keys `beans update` would drop from `bean_file` (#208).

	Reads the YAML frontmatter -- the block between the first two `---` fences --
	and returns, in file order, the keys not in `KNOWN_KEYS`. The `# <id>` line
	beans writes as the first frontmatter line is a YAML comment, not a key, and
	is skipped, as is any blank or nested (indented) line.

	Fails open: an unreadable or frontmatter-less file returns `()`. The caller
	only blocks on a *non-empty* result, so a file that vanished between load and
	edit falls through to `beans update` itself, which errors loudly on it rather
	than bv inventing a block from a read failure.
	"""
	try:
		text = bean_file.read_text(encoding="utf-8")
	except OSError:
		return ()

	lines = text.splitlines()
	if not lines or lines[0].strip() != "---":
		return ()

	keys: list[str] = []
	for line in lines[1:]:
		if line.strip() == "---":
			break
		# Only top-level `key:` lines. Indentation means a list item or nested
		# value under the key above; a leading `#` is beans' id comment.
		if not line or line[0].isspace() or line.lstrip().startswith("#"):
			continue
		name, sep, _ = line.partition(":")
		if not sep:
			continue
		name = name.strip()
		if name and name not in KNOWN_KEYS:
			keys.append(name)
	return tuple(keys)


def update_argv(beans_dir: Path, bean_id: str, *flags: str) -> tuple[str, ...]:
	"""The `beans update` command for one bean, addressed by `--beans-path`.

	`--beans-path` for the same reason the read path uses it: run from anywhere,
	`beans` searches upward for a `.beans.yml` and would resolve to whatever repo
	the process sits in rather than the project the bean belongs to. `flags` is
	the already-built field change, e.g. `("--status", "completed")`.
	"""
	return (BEANS, "--beans-path", str(beans_dir), "update", bean_id, *flags)


def archive_argv(beans_dir: Path) -> tuple[str, ...]:
	"""The `beans archive` command for a whole project.

	beans 0.4.2 has no per-bean archive: `archive` takes no id and moves *every*
	completed/scrapped bean in the project to `.beans/archive/`. So this is a
	project-level sweep, and the caller names the count before running it.
	"""
	return (BEANS, "--beans-path", str(beans_dir), "archive")


def run_edit(argv: tuple[str, ...], runner: Runner = subprocess.run) -> EditResult:
	"""Run one `beans` write and phrase the outcome as a sentence a user can act on.

	Returns rather than raises: the only caller is a thread worker, and every
	failure has to reach `App.notify` as text. The three that matter are beans
	missing from PATH (a bare `FileNotFoundError` that would read like a bug in
	bv), a timeout, and a nonzero exit -- whose first stderr line is beans' own
	reason ("bean not found", a bad status value) and the most useful thing to
	show.

	`runner` is the same injection seam as `dispatch`: the suite passes a fake so
	no test ever mutates a real store.
	"""
	try:
		proc = runner(
			list(argv),
			capture_output=True,
			text=True,
			timeout=EDIT_TIMEOUT,
			check=False,
		)
	except FileNotFoundError:
		return EditResult(
			False,
			"`beans` not found on PATH -- install it with `brew install --cask hmans/beans/beans`",
		)
	except subprocess.TimeoutExpired:
		return EditResult(False, f"`beans` timed out after {EDIT_TIMEOUT:g}s")
	except OSError as error:
		return EditResult(False, f"`beans` failed to start: {error}")

	if proc.returncode != 0:
		detail = (proc.stderr or proc.stdout or "").strip().splitlines()
		first = detail[0] if detail else f"exit {proc.returncode}"
		return EditResult(False, first)

	message = (proc.stdout or "").strip().splitlines()
	return EditResult(True, message[0] if message else "done")
