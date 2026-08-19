---
# bv-vppj
title: make coverage warns module-not-measured under the src layout
status: completed
type: bug
priority: normal
tags:
    - tooling
    - testing
created_at: 2026-08-17T17:02:11Z
updated_at: 2026-08-17T17:02:11Z
---

Moving the package to `src/bv` in bv-go45 made every `make coverage` run print,
partway through the suite:

    CoverageWarning: Module bv was previously imported, but not measured
    (module-not-measured)

Reproduced against a flat-layout copy of the same working tree -- the warning is
absent there and present here, so the layout is the cause rather than anything
in the suite.

The recipe passed `--cov=bv`. pytest-cov hands that value to coverage as
`source`, and coverage resolves a `source` entry that is not an existing
directory by importing it to find its files. Under the flat layout `bv/` *was* a
directory in the invocation directory, so the entry was taken as a path and
nothing was imported. Under `src/` it is not, so coverage imported the package
after measurement had already started -- which is exactly what
`module-not-measured` reports.

The fix is a bare `--cov`. With no value pytest-cov enables instrumentation and
leaves the selection to `source_pkgs = ["bv"]` in `[tool.coverage.run]`, where it
was already declared; the `--cov=bv` on the Makefile line had been restating it.
Bare `--cov` still keeps instrumentation off in the default `make test`, which is
the reason the flag lives on the command line rather than in the config.

Nothing measured changed: 1521 statements, 166 missed, 348 branches, 37 partial,
87% total, identical before and after and identical to the flat-layout run.

Not fixed by deleting `source_pkgs` and keeping `--cov=bv` instead. That would
put the selection back on the Makefile line, where a bare `uv run pytest --cov`
would no longer measure the same thing the target does -- the property
[tool.coverage.*] exists to hold.
