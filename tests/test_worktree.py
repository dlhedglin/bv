"""Tests for the read side of the `W` worktree lifecycle.

`worktree.py` fans a single lifecycle question out across several *different*
git reads -- `git branch`, `merge-base --is-ancestor`, `cherry`, `rev-list`,
`config`, `status`, `worktree remove`, `branch -d/-D` -- and the interesting
behaviour is which of those it runs, in what order, and how it folds their exit
codes into a verdict. The one-result-fits-all `FakeRunner` in `test_dispatch`
cannot express that, so this file carries `Router`: a fake runner that dispatches
on the git subcommand (`command[1]`) and returns a per-subcommand
`CompletedProcess`, recording every call so a test can assert what git actually
ran.

Nothing here touches a real repo: every git read is injected through `Router`.
"""

import subprocess
from pathlib import Path

from bv.dispatch import DEFAULT_BASE, GIT, branch_for, worktree_path_for
from bv.worktree import (
	IN_WORKTREE,
	MERGED,
	NONE,
	READY,
	merged_verdict,
	remove_worktree,
	worktree_dirty,
	worktree_states,
)


def result(returncode=0, stdout="", stderr=""):
	"""A `subprocess.run` return, the shape `Router` hands back."""
	return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class Router:
	"""A fake `subprocess.run` that answers per git subcommand.

	`results` maps a git subcommand (`branch`, `merge-base`, `cherry`,
	`rev-list`, `config`, `status`, `worktree`) to the `CompletedProcess` to
	return for it; anything unlisted gets `default`. `raises` sabotages every
	call, standing in for a missing git. Every call is recorded on `.calls` as
	the `(command, kwargs)` pair `test_dispatch`'s `FakeRunner` records, so a
	test can assert the exact argv git was handed.
	"""

	def __init__(self, results=None, default=None, raises=None):
		self.calls: list[tuple[list[str], dict]] = []
		self._results = results or {}
		self._default = default if default is not None else result()
		self._raises = raises

	def __call__(self, command, **kwargs):
		self.calls.append((list(command), kwargs))
		if self._raises is not None:
			raise self._raises
		return self._results.get(_subcommand(command), self._default)

	def sub_calls(self, sub: str) -> list[list[str]]:
		"""Just the argv lists whose subcommand is `sub`."""
		return [command for command, _ in self.calls if _subcommand(command) == sub]


def _subcommand(command: list[str]) -> str | None:
	"""The git subcommand in an argv: the first token that is not `git`.

	Every caller hands `_read` bare args, so the argv is `[GIT, <sub>, ...]`;
	skipping the leading `git` finds the subcommand.
	"""
	for token in command:
		if token != GIT:
			return token
	return None


# -- worktree_states ------------------------------------------------------


def test_a_branchless_bean_is_none_and_spends_no_git_on_itself():
	# The cost claim in the module docstring: a bean with no `worktree-<id>`
	# branch costs one set lookup and no git at all, so the common all-NONE board
	# spends a single `git branch` for the whole poll.
	router = Router(results={"branch": result(stdout="main\nfeat/x\n")})
	states = worktree_states(Path("/repos/bv"), ["bv-1", "bv-2"], router)
	assert states == {"bv-1": NONE, "bv-2": NONE}
	# One git call total -- the branch listing -- and nothing per bean.
	assert len(router.calls) == 1
	assert router.calls[0][0] == [GIT, "branch", "--format=%(refname:short)"]


def test_a_branch_is_classified_merged_ready_or_in_worktree():
	# The three live states, each a different fold of the same reads: `config`
	# gives the base, then merged_verdict (merge-base/cherry) and, only if
	# unmerged, _ahead_of_base (rev-list --count) decide between them.
	branch = branch_for("bv-1")
	present = result(stdout=f"main\n{branch}\n")
	base = result(stdout="main\n")

	# merged: ancestor of base, so merge-base --is-ancestor exits 0.
	merged = Router(results={"branch": present, "config": base, "merge-base": result(returncode=0)})
	assert worktree_states(Path("/repos/bv"), ["bv-1"], merged) == {"bv-1": MERGED}

	# ready: not merged (is-ancestor fails, cherry shows a `+`) and ahead (count > 0).
	ready = Router(
		results={
			"branch": present,
			"config": base,
			"merge-base": result(returncode=1),
			"cherry": result(stdout="+ abc123\n"),
			"rev-list": result(stdout="2\n"),
		}
	)
	assert worktree_states(Path("/repos/bv"), ["bv-1"], ready) == {"bv-1": READY}

	# in-worktree: not merged, but level with base (count 0) -- nothing to merge.
	working = Router(
		results={
			"branch": present,
			"config": base,
			"merge-base": result(returncode=1),
			"cherry": result(stdout="+ abc123\n"),
			"rev-list": result(stdout="0\n"),
		}
	)
	assert worktree_states(Path("/repos/bv"), ["bv-1"], working) == {"bv-1": IN_WORKTREE}


# -- merged_verdict -------------------------------------------------------


def test_an_ancestor_of_its_base_is_merged_without_consulting_cherry():
	# Fast path: a plain merge (or a branch that never diverged) is an ancestor
	# of its base, so `merge-base --is-ancestor` exits 0 and the expensive
	# patch-equivalence check is never run.
	router = Router(results={"merge-base": result(returncode=0)})
	assert merged_verdict(Path("/repos/bv"), "bv-1", base="main", runner=router) is True
	assert router.sub_calls("cherry") == []


def test_a_squash_merged_branch_reads_as_merged_via_cherry():
	# The squash/rebase case the ancestor test misses: the branch tip is not in
	# base history, but `git cherry <base> <branch>` marks every commit `-`
	# (already applied under a rewritten sha) and none `+`, so it is merged. The
	# base is the recorded `bvBase`, read via `config` when caller passes None.
	router = Router(
		results={
			"config": result(stdout="release-2\n"),
			"merge-base": result(returncode=1),
			"cherry": result(stdout="- abc123\n- def456\n"),
		}
	)
	assert merged_verdict(Path("/repos/bv"), "bv-1", runner=router) is True
	# The recorded base flows into both git reads, not a hardcoded main.
	assert router.sub_calls("merge-base") == [[GIT, "merge-base", "--is-ancestor", branch_for("bv-1"), "release-2"]]
	assert router.sub_calls("cherry") == [[GIT, "cherry", "release-2", branch_for("bv-1")]]


def test_the_base_defaults_to_main_when_no_config_is_recorded():
	# A HEAD cut records no `bvBase`, so `git config` exits nonzero and
	# recorded_base answers main -- which is the base cherry is then handed.
	router = Router(
		results={
			"config": result(returncode=1),
			"merge-base": result(returncode=1),
			"cherry": result(stdout="- abc123\n"),
		}
	)
	assert merged_verdict(Path("/repos/bv"), "bv-1", runner=router) is True
	assert router.sub_calls("cherry") == [[GIT, "cherry", DEFAULT_BASE, branch_for("bv-1")]]
	assert DEFAULT_BASE == "main"


def test_a_cherry_plus_line_means_genuinely_unmerged():
	# A `+` line is a commit not yet in the base under any sha -- real pending
	# work, so the verdict is False and the delete guard will refuse.
	router = Router(
		results={
			"merge-base": result(returncode=1),
			"cherry": result(stdout="+ abc123\n- def456\n"),
		}
	)
	assert merged_verdict(Path("/repos/bv"), "bv-1", base="main", runner=router) is False


def test_git_unreachable_conservatively_reads_as_not_merged():
	# Best-effort, erring toward keeping work: if git cannot be run at all, or
	# every read exits nonzero, the answer is False -- never report unmerged work
	# as merged, which would let the delete guard drop it.
	unreachable = Router(raises=FileNotFoundError())
	assert merged_verdict(Path("/repos/bv"), "bv-1", base="main", runner=unreachable) is False

	all_nonzero = Router(default=result(returncode=1))
	assert merged_verdict(Path("/repos/bv"), "bv-1", base="main", runner=all_nonzero) is False


# -- worktree_dirty -------------------------------------------------------


def _make_worktree_dir(root: Path, worktree: str) -> Path:
	"""Create the on-disk worktree dir `worktree_dirty` probes before git."""
	path = worktree_path_for(root, worktree)
	path.mkdir(parents=True)
	return path


def test_a_worktree_with_uncommitted_changes_is_dirty(tmp_path):
	# Any `git status --porcelain` output means a tree a remove would lose work
	# from. The dir has to exist first -- that check gates the git call.
	_make_worktree_dir(tmp_path, "bv-1")
	router = Router(results={"status": result(stdout=" M src/bv/worktree.py\n")})
	assert worktree_dirty(tmp_path, "bv-1", router) is True
	assert router.sub_calls("status") == [[GIT, "status", "--porcelain"]]


def test_a_clean_worktree_is_not_dirty(tmp_path):
	_make_worktree_dir(tmp_path, "bv-1")
	router = Router(results={"status": result(stdout="")})
	assert worktree_dirty(tmp_path, "bv-1", router) is False


def test_a_missing_worktree_dir_is_not_dirty_and_costs_no_git(tmp_path):
	# No directory means no live tree to lose work from; the module returns False
	# without ever reaching for git.
	router = Router()
	assert worktree_dirty(tmp_path, "bv-1", router) is False
	assert router.calls == []


# -- remove_worktree ------------------------------------------------------


def test_a_removal_drops_the_tree_then_the_branch_in_that_order():
	# `git branch -d` refuses a branch with a checked-out worktree, so the tree
	# is removed first and the branch deleted second -- the exact argv of both.
	router = Router()  # everything exits 0
	root = Path("/repos/bv")
	ok, message = remove_worktree(root, "bv-1", runner=router)
	assert ok is True
	assert "worktree-bv-1" in message
	path = worktree_path_for(root, "bv-1")
	assert router.calls[0][0] == [GIT, "worktree", "remove", str(path)]
	assert router.calls[1][0] == [GIT, "branch", "-d", branch_for("bv-1")]
	assert len(router.calls) == 2


def test_forcing_a_removal_uses_force_on_the_tree_and_capital_d_on_the_branch():
	# `--force` drops a dirty tree; `-D` drops unmerged commits. Both are the
	# force spellings, and both are used together.
	router = Router()
	root = Path("/repos/bv")
	ok, _ = remove_worktree(root, "bv-1", force=True, runner=router)
	assert ok is True
	path = worktree_path_for(root, "bv-1")
	assert router.calls[0][0] == [GIT, "worktree", "remove", str(path), "--force"]
	assert router.calls[1][0] == [GIT, "branch", "-D", branch_for("bv-1")]


def test_a_failed_tree_removal_never_deletes_the_branch():
	# If `git worktree remove` fails, the branch delete must not run -- the tree
	# is still there and `-d` would refuse it anyway; the failure is reported.
	router = Router(results={"worktree": result(returncode=1, stderr="fatal: 'x' contains modified content")})
	ok, message = remove_worktree(Path("/repos/bv"), "bv-1", runner=router)
	assert ok is False
	assert "modified content" in message
	# Only the remove ran; no `git branch` behind it.
	assert router.sub_calls("branch") == []
	assert len(router.calls) == 1
