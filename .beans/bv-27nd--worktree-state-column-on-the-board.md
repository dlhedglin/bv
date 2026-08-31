---
# bv-27nd
title: Worktree state column on the board
status: todo
type: task
tags:
    - ui
    - worktree
created_at: 2026-08-25T18:47:52Z
updated_at: 2026-08-25T18:47:52Z
parent: bv-clrs
---

## Why

Worktree-dispatched work is invisible after dispatch. A `W` agent commits
`completed` to its branch, so the board — reading the main checkout's `.beans`
— still shows the bean todo or in-progress until the branch merges. Nothing
tells you a branch is finished and waiting, so pending merges pile up unseen.

## Description

Add a per-bean column (board, and/or the agents view) showing worktree state:

- none — no `worktree-<id>` branch
- in-worktree — branch exists, not yet ahead of its base / agent still working
- ready — branch is ahead of its base and not in main: work done, awaiting merge
- merged — branch is an ancestor of main

Compute it once per poll from a single `git worktree list --porcelain` plus
`git branch`, never per-bean. Reconstruct `worktree-<id>` from the bean id via
`branch_for`.

## Non-goals

- Showing the diff or branch contents; that is the review's job.
- Triggering the merge from the column. This is display only.

## Tasks

- [ ] One git read per poll collecting worktree branches and their ahead/merged
      state
- [ ] Map each bean id to a worktree state
- [ ] Render the state as a column or badge, colour-coded like the board
- [ ] Treat the no-worktree case as blank, not an error

## Acceptance criteria

- A bean with a finished, unmerged `worktree-<id>` branch shows "ready" on the
  board.
- The state refreshes on the existing 0.5s poll with no per-bean git calls.
- Beans with no worktree show nothing in the column.

## Notes

"merged" is transient — it vanishes once the branch is deleted at cleanup — and
is partly redundant with the bean's own status flipping to completed on merge.
"ready" is the load-bearing state; prioritise it if the four-way proves noisy.
