---
# bv-avvq
title: 'Dead code in agents.py: unused Session fields and summarize()'
status: completed
type: task
priority: low
tags:
    - refactor
    - quality
created_at: 2026-08-18T20:27:36Z
updated_at: 2026-08-18T20:35:02Z
---

Two dead things in agents.py, surfaced by the pre-publication review (bv-6t3w).
Grouped because both are unused code in the same module.

1. `Session.session_id` and `Session.detail` are populated in `load_sessions`
   (`session_id=payload.get("sessionId")`, `detail=payload.get("detail")`) but
   never read anywhere in `src/` or `tests/`. Dead state that reads as if it
   drives something and costs a maintainer a search to confirm it does not.

2. `agents.summarize` (agents.py:241) is imported by nothing in production --
   app.py imports `Attribution, Session, attribute_all, load_sessions, resolved,
   session_within` from agents, not `summarize`, and the `summarize` it uses at
   app.py:767 is `tree.summarize`, a different function. `agents.summarize` is
   kept alive solely by test_agents.py.

Fix: remove the two unused fields and the unused function (and the test that only
exists to exercise it). If `summarize` was meant to feed the status bar, that is a
missing feature -- file it separately rather than keeping dead code as a
placeholder.
