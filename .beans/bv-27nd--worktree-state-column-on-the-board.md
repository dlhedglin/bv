---
# bv-27nd
title: Worktree state column on the board
status: completed
type: task
priority: normal
tags:
    - ui
    - worktree
created_at: 2026-08-25T18:47:52Z
updated_at: 2026-08-31T15:56:23Z
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



## Notes (shipped)

Worktree state lives in `src/bv/worktree.py`: `worktree_states(root, bean_ids)` returns a bean-id -> state map (none/in-worktree/ready/merged), one `git branch` per project per poll plus a few reads only for beans that actually have a `worktree-<id>` branch -- cost is O(worktrees), not O(beans). `merged` uses the shared `merged_verdict` (ancestor fast path + `git cherry` patch-equivalence for squash/rebase merges), the same helper bv-gz14's delete guard uses. App wires it in as `self._worktrees`, refreshed on the 0.5s poll (`_refresh_worktrees`), rendered as a `WT` DataTable column and a kanban card badge (`board.worktree_cell` / `WORKTREE_STYLES`, ready = bold green).
