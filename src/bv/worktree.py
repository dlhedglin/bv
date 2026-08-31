"""The read side of the `W` worktree lifecycle: what state each bean's branch is
in, and whether one can be safely removed.

`dispatch` owns the *create* side -- `git worktree add`, the `bvBase` record --
and the naming convention (`branch_for`, `worktree_path_for`, `recorded_base`).
This module owns the *observe* side those close-the-loop pieces read from:

- `worktree_states` maps bean ids to a lifecycle state (none / in-worktree /
  ready / merged) for the board column, computed per poll.
- `merged_verdict` is the single "is this branch's work already in its base"
  test -- ancestor-of-base fast path, patch-equivalence fallback so a
  squash- or rebase-merged PR still reads as merged. The board column and the
  delete guard share it rather than each rolling a coarser check.
- `worktree_dirty` and `remove_worktree` back the guarded delete key.

Every git read is best-effort and injected-runner friendly for the same reason
`dispatch`'s are: the tests never touch a real repo, and a board that cannot
reach git shows blanks rather than raising. Cost scales with the number of
*worktree* branches, not the number of beans: a bean with no `worktree-<id>`
branch costs one set lookup and no git at all, so the common board -- no
worktrees -- spends a single `git branch` per poll.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .dispatch import (
	DISPATCH_TIMEOUT,
	GIT,
	Runner,
	branch_for,
	recorded_base,
	worktree_path_for,
)

# The lifecycle states a `worktree-<id>` branch moves through, in order. Plain
# strings, like bean statuses, so they render and compare without unwrapping.
NONE = "none"
"""No `worktree-<id>` branch: this bean was never dispatched with `W`, or its
worktree has already been cleaned up. Rendered blank, not as a word -- most
beans are here and a column of `none` would be the loudest empty thing on the
board."""

IN_WORKTREE = "in-worktree"
"""The branch exists but is not yet ahead of its base: the agent is still
working, or committed nothing. Nothing to merge."""

READY = "ready"
"""Ahead of its base and not merged: the work is done and waiting for a human to
review and merge. The load-bearing state -- this is the one the column exists to
surface."""

MERGED = "merged"
"""Already in its base, directly or as a squash/rebase merge. Transient: it
vanishes when the branch is cleaned up, and the bean's own status flips to
completed on merge, so it is partly redundant -- kept only to distinguish a
merged-but-not-yet-removed branch from one still awaiting merge."""


def _read(root: Path, args: list[str], runner: Runner) -> subprocess.CompletedProcess[str] | None:
	"""Run a read-only git command in `root`, or None if git could not be run.

	Best-effort like `dispatch.local_branches`: a missing git, a missing repo or
	a timeout all come back None so the caller falls through to a safe default
	rather than raising into a 0.5 s poll or a keypress handler.
	"""
	try:
		return runner(
			[GIT, *args],
			cwd=str(root),
			capture_output=True,
			text=True,
			timeout=DISPATCH_TIMEOUT,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return None


def _branch_set(root: Path, runner: Runner) -> set[str]:
	"""Every local branch name in `root`, for existence checks.

	One git call for the whole board: membership answers "does `worktree-<id>`
	exist" for every bean without a call per bean."""
	proc = _read(root, ["branch", "--format=%(refname:short)"], runner)
	if proc is None or proc.returncode != 0:
		return set()
	return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def merged_verdict(root: Path, worktree: str, base: str | None = None, runner: Runner = subprocess.run) -> bool:
	"""Whether `worktree-<worktree>`'s work is already in its base.

	The one place the "merged" question is answered, shared by the board column
	and the delete guard so they never disagree. `base` defaults to the recorded
	`bvBase` (main when unset).

	Two tiers, because a merge is not always a fast-forward:

	- Fast path: the branch is an ancestor of its base (`merge-base
	  --is-ancestor`). True of a plain merge or a branch that never diverged.
	- Fallback: patch-equivalence via `git cherry <base> <branch>`, which marks
	  each branch commit `+` (not in base) or `-` (already applied under a
	  different sha). No `+` line means every commit is already in the base under
	  a rewritten sha -- a rebase- or squash-merged PR, which the ancestor test
	  misses because the branch tip is not in the base's history.

	Best-effort: if git cannot be reached the verdict is False (not merged),
	the conservative answer -- it never reports unmerged work as merged, so the
	delete guard errs toward refusing rather than losing work.
	"""
	branch = branch_for(worktree)
	if base is None:
		base = recorded_base(root, worktree, runner)
	ancestor = _read(root, ["merge-base", "--is-ancestor", branch, base], runner)
	if ancestor is not None and ancestor.returncode == 0:
		return True
	cherry = _read(root, ["cherry", base, branch], runner)
	if cherry is None or cherry.returncode != 0:
		return False
	return not any(line.startswith("+") for line in cherry.stdout.splitlines())


def _ahead_of_base(root: Path, worktree: str, base: str, runner: Runner) -> bool:
	"""Whether the branch has any commit its base does not -- work to merge.

	`git rev-list --count <base>..<branch>`: zero means the branch is level with
	or behind its base (the agent committed nothing yet), nonzero means there is
	something to carry. Read only after `merged_verdict` has said not-merged, so
	a nonzero here is genuinely pending rather than already-applied work."""
	proc = _read(root, ["rev-list", "--count", f"{base}..{branch_for(worktree)}"], runner)
	if proc is None or proc.returncode != 0:
		return False
	return (proc.stdout.strip() or "0") != "0"


def worktree_states(root: Path, bean_ids: list[str], runner: Runner = subprocess.run) -> dict[str, str]:
	"""Map each bean id to its worktree lifecycle state, for the board column.

	One `git branch` for the whole set, then a handful of reads *only* for the
	beans that actually have a `worktree-<id>` branch -- so the cost is O(live
	worktrees), not O(beans), and a board with no worktrees spends one git call.
	Beans without a branch map to `NONE`, which the column renders blank.

	`root` is the main checkout: worktree branches live in its shared branch
	namespace, and their `bvBase` config with them, so every read here runs from
	the checkout, never inside a worktree.
	"""
	branches = _branch_set(root, runner)
	states: dict[str, str] = {}
	for bean_id in bean_ids:
		if branch_for(bean_id) not in branches:
			states[bean_id] = NONE
			continue
		base = recorded_base(root, bean_id, runner)
		if merged_verdict(root, bean_id, base, runner):
			states[bean_id] = MERGED
		elif _ahead_of_base(root, bean_id, base, runner):
			states[bean_id] = READY
		else:
			states[bean_id] = IN_WORKTREE
	return states


def worktree_dirty(root: Path, worktree: str, runner: Runner = subprocess.run) -> bool:
	"""Whether the worktree has uncommitted changes that a remove would lose.

	`git status --porcelain` inside the worktree directory: any output means a
	dirty tree. False when the directory is gone or git cannot read it -- there
	is then no live tree to lose work from, and `merged_verdict` still governs
	whether the *committed* history is safe to drop. Only meaningful while a live
	worktree exists; the delete guard pairs it with the merged check.
	"""
	path = worktree_path_for(root, worktree)
	if not path.is_dir():
		return False
	proc = _read(path, ["status", "--porcelain"], runner)
	if proc is None or proc.returncode != 0:
		return False
	return bool(proc.stdout.strip())


def remove_worktree(
	root: Path, worktree: str, *, force: bool = False, runner: Runner = subprocess.run
) -> tuple[bool, str]:
	"""Remove `worktree-<worktree>`'s directory and delete its branch.

	The symmetric close to `dispatch`'s `git worktree add`: worktree
	housekeeping, not a code merge, so it stays inside bv's observe-only line
	(which is specifically "bv never runs `git merge`"). Two steps, in order --
	the tree first, because `git branch -d` refuses a branch that still has a
	checked-out worktree:

	- `git worktree remove <path>` (`--force` when `force`, to drop a dirty tree)
	- `git branch -d <branch>` (`-D` when `force`, to drop unmerged commits)

	Returns `(ok, message)` rather than raising, matching `dispatch`: the caller
	is a keypress handler that turns the message straight into a notify. The
	guard against losing work lives in the caller (a merged/dirty check gates
	whether `force` is even offered); this just executes the decided removal.
	"""
	path = worktree_path_for(root, worktree)
	branch = branch_for(worktree)
	# `_read` prepends `GIT`, so these are bare args like every other call here.
	remove = ["worktree", "remove", str(path)]
	if force:
		remove.append("--force")
	proc = _read(root, remove, runner)
	if proc is None:
		return (False, f"`{GIT}` not found on PATH -- is git installed?")
	if proc.returncode != 0:
		first = (proc.stderr or proc.stdout or "").strip().splitlines()
		return (False, f"{GIT} worktree remove: {first[0] if first else f'exit {proc.returncode}'}")
	delete = ["branch", "-D" if force else "-d", branch]
	proc = _read(root, delete, runner)
	if proc is None:
		return (False, f"`{GIT}` not found on PATH -- is git installed?")
	if proc.returncode != 0:
		first = (proc.stderr or proc.stdout or "").strip().splitlines()
		# The worktree is already gone; only the branch delete failed. Say which,
		# so the user is not left thinking nothing happened.
		return (False, f"{GIT} branch -d: {first[0] if first else f'exit {proc.returncode}'} (worktree removed)")
	return (True, f"removed {branch}")
