---
# bv-te9w
title: Gate tree-only keys while the board is showing
status: completed
type: bug
priority: normal
tags:
    - ux
created_at: 2026-08-17T04:50:49Z
updated_at: 2026-08-17T06:05:26Z
---

## What is wrong

With the board showing (`b`), the footer still advertises the tree's keys and
they still fire — `space`, `C`, `E`, `P`, `g`, `G` all act on the `DataTable`
that is mounted but hidden underneath. They do not crash (there is a pilot
assertion on that), and they do not corrupt anything, but they are invisible
no-ops: the footer promises "Fold" and "Collapse all" while the board cannot
fold.

The table is deliberately kept mounted rather than removed — nearly every
action in `app.py` reaches for it with a bare `query_one`, so removing it turns
every fold key into a `NoMatches` traceback. That decision is right; what is
missing is gating the actions and the footer on which view is active.

## Also, a duplication

`STATUS_STYLES` exists in both `app.py` and `board.py`. `board.py` cannot
import it from `app.py` because `app.py` imports `board`. It belongs in
`beans.py` next to `STATUS_ORDER`, which both already import.

Two definitions of a colour scheme drift, and the board and the tree
disagreeing about what `in-progress` looks like is the kind of thing nobody
notices until a theme change makes one of them unreadable.

## Also, no guard against two agents on one bean

`S` does not check whether a session is already working the bean. The Agent
column shows it and the confirmation names the bean, but nothing stops two
agents landing on the same row. beans has no assignee field to lock against —
probed and confirmed — so any guard here is advisory and lives in bv.

Worth deciding whether the confirmation should simply say "an agent is already
on this bean" rather than pretending to be a lock.
