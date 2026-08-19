---
# bv-x62m
title: Point a dispatched agent at the bean instead of inlining its body
status: completed
type: feature
priority: normal
tags:
    - agents
created_at: 2026-08-17T05:14:36Z
updated_at: 2026-08-17T05:14:36Z
---

## Why

`prompt_for` inlines the whole bean body into the dispatched prompt. Measured
across the 222 live beans:

    prompt chars   median 2501   p90 6875   max 23879
    the body is 98% of that by volume
    id + title alone would be a median of 66 chars
    57 of 222 bodies are over 4k chars

Size is the least of it. Three things matter more:

**The inlined body is a snapshot.** Taken at dispatch and never refreshed. Edit
the bean while the agent works — or let another agent edit it — and the agent
is working from stale text with no way to notice. Bean bodies in this repo get
rewritten routinely.

**The body is not the whole bean.** The prompt carries no status, no priority,
no blockers, no parent, no children. An agent that queries gets all of it and
can walk to children, which is what an epic-shaped bean needs.

**The agent needs the CLI anyway** — to mark the bean done, to file follow-ups,
to check what blocks it. Naming the command up front is strictly additive.

## Verified

`beans show <id> --json`, run from the project root bv already sets as `cwd`,
returns `body` **verbatim** plus `status`, `priority`, `tags`, `path` and
`etag`.

Use `--json`. The plain form renders the markdown and hard-wraps it at ~78
columns, which mangles any code block in the body.

## The objection, and the answer

A failed query fails quietly. If `beans` is missing from PATH, or the cwd does
not resolve a `.beans.yml`, the agent gets an error and may proceed to invent
the task from the title alone. Inlining at least guarantees the body arrives.

That is a real risk and it is why the *pure* version is wrong — but it is
fixable by instruction rather than by inlining. Tell the agent to stop if the
command fails, and the silent hallucination becomes an explicit halt.

## Scope

`prompt_for` in `bv/dispatch.py`, plus its tests. Keep the id and the title in
the prompt: the title is 66 chars, and it is what makes the session name and
the `claude agents` list readable. Drop the body. Add the command and the
stop-on-failure instruction.

Do **not** instruct the agent to run `beans update`. bv is read-only because
beans 0.4.2 ships #205 and #208 unpatched; whether an agent writes is the
agent's call, not something bv should put in its mouth.

## Not in scope

The `--permission-mode` question, still open on bv-9sxj.


## Shipped

`prompt_for` now hands over the id, the title, and how to read the rest:

    Work bean bv-x62m: Point a dispatched agent at the bean instead of inlining its body

    Read it first:

        beans show bv-x62m --json

    That gives you the body, status, priority, tags and blockers. If the
    command fails, stop and say so -- do not infer the task from the title.

Measured across the 222 live beans: median prompt **2501 -> 272** chars, max
**23879 -> 324**. The prompt no longer scales with the body at all; it is
bounded by the title.

## One thing the change moved rather than removed

The body used to be the only free text reaching `execve`, and `clean_body` was
guarding it against a NUL truncating the argument mid-sentence. The body no
longer reaches argv — but the title still does, so that guard moved onto the
title as `_argv_safe`, which also strips newlines. A title carrying its own
line break could otherwise forge one of the instruction lines below the header;
there is a test on exactly that.

The same applies to the confirmation dialog. Everything in it is a `rich.Text`
because Textual 8.2.8 silently swallows stray markup, and the title is now the
only place that hazard can enter. The bracket test was retargeted from the body
to the title rather than deleted.

## Tests

Eight asserted the old inline shape. Two guarded hazards that still exist and
were retargeted; the rest were rewritten to the new contract, plus three new
ones: that the stop instruction is present (it is what makes not-inlining
safe rather than a downgrade), that the read command asks for `--json`, and
that the prompt no longer grows with the body.

`test_a_huge_prompt_scrolls_inside_the_dialog` became its inverse — nothing
scrolls now. The `_fit_prompt` logic stays anyway, because a very short
terminal can still push the hint line off screen.

28 dispatch tests, 231 in the suite.
