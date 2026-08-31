---
# bv-swjd
title: Record the worktree base at creation
status: completed
type: task
priority: normal
tags:
    - worktree
    - agents
created_at: 2026-08-25T18:47:52Z
updated_at: 2026-08-31T14:58:30Z
parent: bv-clrs
---

## Why

bv discards the base a worktree was cut from — `DispatchRequest.base` is
ephemeral, never persisted. After dispatch, nothing knows what branch
`worktree-<id>` should merge back into. Review and merge both need that target;
without it they can only assume main, which is wrong whenever a worktree was cut
from a feature branch in PickBase.

## Description

At worktree creation, alongside `git worktree add` in `dispatch`, record the
chosen base git-natively: `git config branch.worktree-<id>.bvBase <base>`. Read
it back where review and merge need the target, falling back to main when unset
(a worktree cut from HEAD with no explicit base).

## Non-goals

- A bv state file or any persistence outside git. The record lives in the
  branch's git config.
- Changing how the base is chosen. PickBase stays as-is.

## Tasks

- [ ] Write `branch.worktree-<id>.bvBase` when the worktree is cut
- [ ] Helper to read it back, defaulting to main
- [ ] Cover the no-base (cut from HEAD) case

## Acceptance criteria

- After a `W` dispatch, the base is recoverable from git config alone.
- A worktree cut from a non-main branch reports that branch as its base; one cut
  from HEAD reports main (or the resolved default).

## Notes

git-native so it survives with no bv bookkeeping and needs no cleanup of its own
— deleting the branch drops its config. Blocks the merge skill (needs the exact
target) and informs the review (diff base).
