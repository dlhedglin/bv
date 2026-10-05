---
# bv-clrs
title: Worktree merge-back workflow
status: completed
type: feature
priority: normal
tags:
    - worktree
    - agents
created_at: 2026-08-25T18:47:52Z
updated_at: 2026-08-31T16:13:20Z
---

## Why

bv dispatches `W` (worktree) agents that commit their work to a `worktree-<id>`
branch and are told a human merges it. But bv gives that human no tooling: no
list of what is finished and pending, no diff, no merge, no cleanup. Worktree
work is invisible on the board — the agent's `completed` status is trapped on
the unmerged branch — and the branch and worktree accumulate with no lifecycle.
The create side of `W` exists; the close side does not.

## Description

Close the loop on the `W` path with a surface plus two dispatched actions,
holding bv's observe-only line: bv surfaces and spawns, agents do every write.
Four pieces, each its own child bean:

- a board column showing each bean's worktree state (in-worktree / ready /
  merged),
- recording the base a worktree was cut from, so review and merge know the
  target,
- a key that spawns a code-review on the branch, writing findings back to the
  bean,
- a `/merge-worktrees` skill an agent runs to merge ready branches and clean up.

## Non-goals

- bv running `git merge` itself. The merge is the agent's write, via the skill
  — the same principle as the agent writing its own bean status.
- Auto-merging when an agent finishes. Every merge is human-triggered.
- Resolving merge conflicts automatically. On conflict the skill stops and
  reports.

## Tasks

Tracked as child beans:

- [ ] Worktree state column on the board
- [ ] Record the worktree base at creation
- [ ] Review key: dispatch code-review on a worktree branch
- [ ] `/merge-worktrees` skill

## Acceptance criteria

- The board shows, per bean, whether a worktree exists and whether it is ready
  to merge.
- From bv you can spawn a review of a worktree branch whose findings land on the
  bean.
- An agent can merge the ready worktrees into their bases, stopping on conflict,
  and clean up the merged branches and worktrees.
- bv itself still never runs a merge; every write is an agent's own.

## Notes

Design worked out 2026-08-25. Division of labor: bv = surface + spawn
(observe-only preserved); agents = review + merge (the writes). Both the review
and the merge run from the main checkout, never inside the worktree — a `beans
update` run inside a worktree writes the branch's isolated `.beans` and is
trapped until merge, the same trap as the `W` status write. Base recovery: bv
records `git config branch.worktree-<id>.bvBase <base>` at creation and falls
back to main when unset.



## Notes

Closed 2026-08-31. W merge-back loop shipped: worktree state column (bv-27nd), base recorded at creation (bv-swjd), review key dispatching code-review on the branch (bv-t5fb), and a merged-guarded delete-worktree key (bv-gz14). The /merge-worktrees skill (bv-qlay) was scrapped — the review + delete keys from bv cover the close side without a separate merge skill. bv still runs no merge; agents own every write.
