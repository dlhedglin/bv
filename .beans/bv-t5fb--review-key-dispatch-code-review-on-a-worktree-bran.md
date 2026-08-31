---
# bv-t5fb
title: 'Review key: dispatch code-review on a worktree branch'
status: completed
type: task
priority: normal
tags:
    - agents
    - review
created_at: 2026-08-25T18:47:52Z
updated_at: 2026-08-31T15:56:23Z
parent: bv-clrs
blocked_by:
    - bv-swjd
---

## Why

Before merging a worktree branch you want to see whether the work is good. bv's
one trick is spawning an agent, and a review is just another dispatch. Today
there is no way to review a worktree branch from bv.

## Description

Add a keybinding on a bean with a ready worktree that dispatches a review as an
S-style job — `cwd` = the main checkout, NOT the worktree. The agent runs
`/code-review` against `worktree-<id>` (diff vs its recorded base, default main)
and appends its findings to the bean with `beans update <id> --body-append`,
landing them in the bean's Notes. It does not merge and does not edit code.
Reuses ConfirmDispatch.

## Non-goals

- Running inside the worktree. A `beans update` there writes the branch's
  isolated `.beans` and is trapped until merge, so the findings must reach
  main's bean — the review runs from the main checkout.
- Merging, or gating the merge on the review result. Review reports; you decide.

## Tasks

- [ ] Keybinding + ConfirmDispatch entry for "review worktree"
- [ ] Build the review prompt: `/code-review` on the branch, diff vs recorded
      base, append findings to the bean Notes, no merge, no edits
- [ ] Dispatch S-style (cwd = main checkout), offered only when a ready worktree
      exists

## Acceptance criteria

- Pressing the key on a ready-worktree bean spawns a review whose findings appear
  in that bean's Notes on the board.
- The review never enters the worktree and never merges.

## Notes

Reuses the existing `/code-review` skill rather than a bespoke prompt.
Blocked-by base-recording for a non-main target, though it can default to main
in the interim.



## Notes (shipped)

`R` key -> `action_review_worktree`. Offered only when the bean's worktree is `ready`; otherwise a no-op notify. Builds an S-style dispatch (`dispatch.review_request_for`, cwd = main checkout, `worktree=None`) whose prompt (`review_prompt_for`) runs `/code-review` on `worktree-<id>` vs its recorded base and appends findings to the bean with `beans update <id> --body-append` -- never merges, never edits code, never enters the worktree. Reuses `ConfirmDispatch`.
