---
# bv-a4we
title: CI running make check on GitHub Actions
status: completed
type: task
priority: high
tags:
    - tooling
    - ci
created_at: 2026-08-17T17:51:23Z
updated_at: 2026-08-17T19:12:03Z
---

Nothing currently proves this builds on a machine that is not mine. Every gate
exists and passes locally -- `make check` runs ty, ruff and 285 tests -- but it
has only ever run against one working tree, one Python and one set of
already-warm caches.

A workflow that runs `make check` on push and on pull requests, across the
Python versions the project actually claims. `requires-python = ">=3.11"` is a
tested claim as of the src/bv move: the full suite passes on 3.11 as well as the
3.13 used day to day, and the matrix is what keeps that true rather than a thing
verified once by hand.

Shape:

- `astral-sh/setup-uv` with the cache enabled, then `make check`. No pip, no
  manually activated virtualenv -- the targets already go through `uv run`, so
  the workflow is the same three commands a contributor runs.
- Matrix over 3.11, 3.12 and 3.13. `uv python install` fetches whichever the
  runner lacks.
- Ubuntu is enough. The suite drives Textual through `run_test`, which needs no
  terminal, and the only platform-specific code is the clipboard path, which the
  tests stub.

Worth checking rather than assuming: `tests/test_watch.py` has a timing check
guarded by `skipif(not REAL_ROOT.is_dir())` against a path only my machine has,
so it will skip on a runner. Confirm the skip reads as a skip in the summary and
not as a silent pass -- `-ra` in addopts already summarises skips, which is what
that flag is there for.

This blocks the three badge beans. A badge is a rendering of a workflow result,
so there is nothing for one to point at until this exists.
