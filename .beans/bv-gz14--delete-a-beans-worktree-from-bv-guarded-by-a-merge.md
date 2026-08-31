---
# bv-gz14
title: Delete a bean's worktree from bv, guarded by a merged check
status: completed
type: task
priority: normal
tags:
    - worktree
    - ui
created_at: 2026-08-29T18:54:23Z
updated_at: 2026-08-31T15:56:23Z
parent: bv-clrs
blocked_by:
    - bv-swjd
---

## Why

bv cuts worktrees (`git worktree add` in `dispatch`) but gives no way to remove
one. After a `W` agent finishes — merged by the skill, merged as a PR on GitHub,
or abandoned — the `worktree-<id>` branch and its `.claude/worktrees/` directory
sit on disk forever. The only cleanup today is a side effect of the
`/merge-worktrees` skill (bv-qlay), which deletes *only* what it merges itself.
Nothing removes a worktree merged elsewhere or one the user wants to throw away,
and nothing tells the user whether removing it would lose unmerged work.

## Description

A bv key (proposed `D`) on the bean under the cursor that removes that bean's
worktree and branch: `git worktree remove <path>` then `git branch -d
worktree-<id>`, using `worktree_path_for` / `branch_for` so the convention stays
in one place. This is symmetric with the `add` bv already runs — worktree
housekeeping, not a code merge — so it stays inside the observe-only line.

The delete is guarded by a merged check computed against the worktree's recorded
base (bv-swjd's `branch.worktree-<id>.bvBase`, default main):

- merged / no unmerged commits — remove freely.
- has commits not in its base, or a dirty/uncommitted tree — this would lose
  work: refuse by default, offer a force confirm before doing `git worktree
  remove --force` + `git branch -D`.

"Merged" must catch squash- and rebase-merges (a GitHub PR), where the branch is
not an ancestor of its base but its patch is already applied. Ancestor-of-base
(`git merge-base --is-ancestor`) is the fast path; fall back to patch-equivalence
(`git cherry <base> worktree-<id>` reporting no unmerged `+` commits, or
`git log <base>..worktree-<id>` empty) so a merged PR reads as merged. Expose
this as a small helper so the board's worktree-state column (bv-27nd) can reuse
the same "merged" verdict instead of its own coarser ancestor-of-main test.

No worktree for the bean — the key is a no-op with a notify, never an error.

## Non-goals

- Merging. This only removes; the merge stays the agent's write (bv-qlay).
- Bulk delete of every merged worktree at once. One bean under the cursor per
  invocation; a sweep can come later.
- Deleting the remote branch. Local worktree + local branch only.
- Recording the base — consumed here, owned by bv-swjd.

## Tasks

- [ ] Merged helper: ancestor-of-base fast path, patch-equivalence fallback for
      squash/rebase-merged branches, read base from `branch.worktree-<id>.bvBase`
      defaulting to main
- [ ] Detect a dirty/uncommitted worktree tree as "would lose work"
- [ ] `git worktree remove` + `git branch -d`, paths/names via
      `worktree_path_for` / `branch_for`
- [ ] bv key: merged -> remove; unmerged or dirty -> refuse, then force-confirm
      (`--force` + `git branch -D`)
- [ ] No-worktree case is a no-op notify, not an error
- [ ] Point bv-27nd's state column at the shared merged helper
- [ ] Tests: merged (ancestor), merged (squash/patch-equiv), unmerged refuse,
      dirty refuse, force path, no-worktree no-op — runner injected, no real git

## Acceptance criteria

- Pressing the key on a bean with a merged `worktree-<id>` removes its worktree
  directory and deletes the branch.
- A bean whose branch was squash-merged as a PR is treated as merged and removes
  cleanly without a force.
- A bean with unmerged commits or an uncommitted tree is refused by default and
  only removed after an explicit force confirm.
- A bean with no worktree does nothing and says so.
- bv runs no merge; deletion is local worktree/branch housekeeping only.

## Notes

Symmetry argument: `dispatch` already runs `git worktree add`, so `git worktree
remove` is the matching lifecycle write and does not cross the observe-only line
(which is specifically "bv never runs `git merge`" — bv-clrs Non-goals). Depends
on bv-swjd for the base record; composes with bv-qlay (skill cleans up what it
merges; this key handles abandon and PR-merged-elsewhere) and bv-27nd (shares
the merged verdict). Proposed key `D` — free in `App.BINDINGS`; confirm at
implementation it does not collide.



## Notes (shipped)

`D` key -> `action_delete_worktree`, guarded. `_worktree_delete_plan` combines `worktree.merged_verdict` (squash/rebase-aware) and `worktree.worktree_dirty`: merged+clean removes without force; unmerged commits or a dirty tree require a force confirm (`ConfirmWorktreeDelete`, stark red face) that runs `git worktree remove --force` + `git branch -D`. No worktree = no-op notify. Removal via `worktree.remove_worktree` (tree then branch). bv-27nd's column reuses the same `merged_verdict`. Keys `R`/`D` confirmed free in `App.BINDINGS`.
