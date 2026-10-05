---
# bv-2m1d
title: New worktrees read as merged before any work lands
status: completed
type: bug
priority: high
tags:
    - worktree
    - ui
created_at: 2026-09-22T15:22:33Z
updated_at: 2026-09-22T15:22:33Z
parent: bv-clrs
---

## Why

The `WT` column called every freshly dispatched worktree `merged`, seconds after
`W` cut it and before its agent had written a line. The column exists to surface
`ready`; a state that reads `merged` on sight makes the whole column untrustworthy
and invites deleting a worktree whose work has not started.

## Description

`worktree_states` asked `merged_verdict` first. A branch cut moments ago is
trivially an ancestor of its base, so `merge-base --is-ancestor` exits 0 and the
fast path returned merged. The `git cherry` fallback agrees for the same reason:
no commits means no `+` lines. The same reading hit any worktree whose base moved
while it was idle.

Fix is a reordering plus the fact that makes it possible:

- `dispatch` pins the fork point at creation as `branch.<branch>.bvBaseSha`,
  read back from the just-cut branch's tip. Recorded for a HEAD cut too, which
  has no base *name* to record.
- `worktree.has_own_commits` counts `<forkpoint>..<branch>` -- the branch's own
  commits, immune to the base moving. Falls back to a `<base>..<branch>` count
  for worktrees cut before the sha was recorded.
- `worktree_states` asks it first: no commits -> `in-worktree`, whatever the
  ancestry says. Merged is only reachable downstream of a yes.
- The delete dialog's safe face splits the same way, so a never-committed
  worktree is not described to the user as "Merged and clean".

`merged_verdict` itself is unchanged: "is there unmerged work here" is the right
question for the delete guard, and its answer for a commitless branch (no) is
correct.

## Non-goals

- Backfilling `bvBaseSha` onto worktrees cut before this. The fork point is not
  recoverable after the fact; the base-relative fallback covers them.
- Any change to `merged_verdict`'s two-tier ancestor/cherry logic.
- bv still never runs `git merge`.

## Tasks

- [x] Record `bvBaseSha` at `git worktree add`, best-effort
- [x] `recorded_base_sha` reader, None when unrecorded
- [x] `has_own_commits` counting from the fork point, base-relative fallback
- [x] Reorder `worktree_states` to ask it before merged
- [x] Split the delete dialog's safe reason: merged vs nothing committed
- [x] Regression tests for each

## Acceptance criteria

- A worktree cut seconds ago reads `in-worktree`, not `merged`, and the ancestry
  reads are never run for it.
- A worktree that committed nothing still reads `in-worktree` after its base
  gains commits.
- A fast-forward-merged and a squash-merged branch both still read `merged`.
- A branch with unmerged commits still reads `ready`.

## Notes

Reproduced on a scratch repo: `git merge-base --is-ancestor worktree-x main`
exits 0 immediately after `git worktree add -b worktree-x <path> main`, and
`git cherry main worktree-x` prints nothing -- both tiers of `merged_verdict`
say merged for a branch with no commits.

Verified end to end against a real repo across five worktrees (fresh, working,
ff-merged, squash-merged, idle-while-main-advanced): all five classify correctly
after the fix; the fresh and idle ones read `merged` before it.

The fallback for sha-less worktrees cannot see a fast-forward-merged branch as
merged -- it reads `in-worktree`. Chosen direction: under-claiming progress is
safer than announcing work as landed before it exists, and the delete guard
still reads merged correctly through `merged_verdict`.

## Summary of Changes

`src/bv/dispatch.py`: `BASE_SHA_CONFIG_KEY`, the post-cut `rev-parse` + config
write, `recorded_base_sha`. `src/bv/worktree.py`: `_count_since`,
`_has_own_commits`, public `has_own_commits`, reordered `worktree_states`
(`_ahead_of_base` is gone, subsumed). `src/bv/app.py`: delete-plan reason split
and the dialog body that shows it. Tests: `Router` gained `config:<leaf>` keys;
6 new tests across test_worktree/test_dispatch/test_app.
