---
# bv-pg4k
title: Have a dispatched agent open and close its own bean
status: completed
type: feature
priority: normal
tags:
    - agents
created_at: 2026-08-17T06:09:31Z
updated_at: 2026-08-17T06:15:26Z
---

## What to change

`prompt_for` in `bv/dispatch.py` should tell a dispatched agent to set its bean
to `in-progress` when it starts, and to `completed` when the work is actually
done.

Today it deliberately says nothing about writing. From its own docstring:

> Deliberately absent: any instruction to run `beans update`. bv is read-only
> because beans 0.4.2 ships #205 and #208 unpatched, and whether an agent writes
> is the agent's call, not something bv puts in its mouth.

That was a reasonable default while nothing depended on it. What it produces on
the real board is a bean that stays `todo` for the entire life of the agent
working it, and is still `todo` after the work lands. The only evidence anything
happened is the Agent column and the session name, and both disappear when the
session ends — so a board read the next morning cannot distinguish "nobody has
started this" from "an agent finished this last night". bv-te9w was written,
reviewed and only then closed by hand, which is the whole problem in one bean.

## Why this is not a reversal of "bv is read-only"

The distinction is worth keeping sharp, because it is what made the old decision
look settled. bv the process still never runs `beans update`. Every write here
is the agent's own, in the agent's own repo, through the agent's own CLI, and bv
never learns whether it happened. What changes is what bv *asks for*, which is
text in a prompt.

Say that in the module docstring as well as in `prompt_for`. Otherwise the next
reader finds two statements about writing and has no way to tell which is
current.

## What #205 and #208 mean for this

- **#208** (`beans update` strips unknown frontmatter keys) has nothing to strip
  today: every bv bean carries only keys beans itself owns. But it turns the
  README's sidecar rule from a precaution into a load-bearing one — the moment
  bv writes metadata into bean frontmatter, a dispatched agent's own status
  update deletes it.
- **#205** (`--if-match` CAS loses one of two concurrent writes) now has a live
  path to it. Two agents on one bean is exactly the case bv-te9w decided not to
  lock against, and it is now the case where two `beans update` calls can race.
  The advisory warning on `S` stays advisory; this is a failure mode worth
  naming in the docstring rather than a reason to build a lock.

## Details worth deciding

- **When `in-progress` is set.** Immediately on start is what makes attribution
  survive the session, and it is honest about "something is on this". The cost is
  a bean stuck `in-progress` when an agent dies. Leaning to immediate: a stale
  `in-progress` is visible and correctable, a silent `todo` is neither.
- **What "done" means.** Closing on "I made the edits" is wrong when tests fail
  or the work was partial. The prompt should say `completed` only when the work
  is genuinely finished, and otherwise to leave it `in-progress` and say what is
  left. An agent that closes a bean it half-did is worse than one that never
  touches the status.
- **Never `scrapped`.** Deciding a bean is not worth doing is not a dispatched
  agent's call.
- **The existing stop rule extends to the update.** The prompt already tells the
  agent to halt rather than guess when `beans show` fails. A failed `beans
  update` should be reported the same way, not retried into some other status.

## Testing

`prompt_for` is a pure function over a `Bean`, and `tests/test_dispatch.py`
already asserts what the prompt says, so this is assertions on the new
sentences alongside the existing "the prompt does not scale with the body"
guard. Nothing here goes near a real `claude` or a real `beans update`.
