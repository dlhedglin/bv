---
# bv-qlay
title: /merge-worktrees skill
status: draft
type: task
priority: normal
tags:
    - agents
    - worktree
created_at: 2026-08-25T18:47:52Z
updated_at: 2026-08-31T15:36:35Z
parent: bv-clrs
blocked_by:
    - bv-swjd
---

## Why

The `W` prompt says a human merges the branch, but merging, testing, and
cleaning up several finished worktrees by hand is the manual gap this whole
feature closes. bv must not run the merge itself (observe-only); the agent does,
through a skill.

## Description

A `/merge-worktrees` skill an agent runs from the main checkout. It lists beans
with a ready `worktree-<id>` branch, and for each: re-checks it is ahead, merges
it into its recorded base (default main), runs the test gate, and on success
removes the worktree (`git worktree remove`) and deletes the branch (`git branch
-d`). On conflict or a failing gate it stops on that worktree, leaves it intact,
and reports — never auto-resolves. Batch and sequential, re-checking ahead-ness
after each since merges interact. Reports what merged, what was skipped, and why.

## Non-goals

- Auto-resolving conflicts. Stop and report, the same halt rule as the dispatch
  prompt.
- Merging work that fails the test gate.
- Being invoked automatically. A human runs the skill, standalone or via a bv
  key that spawns it.

## Tasks

- [ ] Enumerate ready worktree branches and their recorded bases
- [ ] Per branch: merge into base, run the gate, clean up on success
- [ ] Stop-and-report on conflict or gate failure, leaving the worktree intact
- [ ] Sequential batch with a re-check between merges
- [ ] Final report: merged / skipped / conflicted, with reasons

## Acceptance criteria

- Running the skill merges every clean, ahead worktree into its base and removes
  its branch and worktree.
- A conflicting or test-failing worktree is left untouched and named in the
  report.
- bv is not involved in the merge; the writes are the agent's own git.

## Notes

Composes with the review key (review first, read findings on the bean, then run
the skill) and with base-recording (needs the exact target). Blocked-by
base-recording.
