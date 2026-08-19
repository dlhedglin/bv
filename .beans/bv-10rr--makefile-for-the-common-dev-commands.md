---
# bv-10rr
title: Makefile for the common dev commands
status: completed
type: epic
priority: normal
tags:
    - tooling
    - dx
created_at: 2026-08-17T06:25:48Z
updated_at: 2026-08-17T06:53:51Z
---

Every routine command in this repo is currently typed out by hand: `uv run
pytest`, `uvx ruff check`, and so on. Nothing records the canonical invocation,
so the flags drift between a human running it, an agent running it, and CI (once
CI exists).

Add a `Makefile` at the repo root as the single entry point for the four things
done constantly while working on `bv`:

- `make typecheck` — ty
- `make lint` / `make fmt` — ruff
- `make test` — pytest
- `make coverage` — pytest with coverage

Conventions for every target under this epic:

- The project is uv-managed, so targets run through `uv run` (or `uvx` for tools
  deliberately kept out of the dependency tree). No assumption of an activated
  virtualenv.
- Targets are `.PHONY` — none of them produce a file named after themselves.
- A target exits non-zero when its check fails, so the same target works locally
  and in CI without a wrapper.
- `make` with no arguments prints the target list rather than silently running
  the first target.
- Add `make check` last, running typecheck + lint + test in that order, as the
  one command to run before committing.

Build order: typecheck and lint first, then test and coverage.


## Shipped

`Makefile` at the repo root, `.DEFAULT_GOAL := help`, everything `.PHONY`:

    help        List the available targets
    typecheck   Type-check bv/ and tests/ with ty
    lint        Report lint and formatting problems with ruff
    fmt         Reformat and auto-fix with ruff
    test        Run the test suite (make test ARGS="-k board")
    coverage    Run the suite under coverage and write htmlcov/
    check       Typecheck, lint and test -- run this before committing

Landed one target per child bean: bv-x2h1 (typecheck), bv-vwk4 (lint/fmt),
bv-4q06 (test), bv-vbem (coverage). Their Shipped notes hold the per-target
detail; what belongs to the epic:

**Every convention in the scope holds.** Targets run through `uv run`, so no
activated virtualenv is assumed and every machine gets the version pinned in
`uv.lock`. Each target exits non-zero on failure, so the same target serves
locally and in CI without a wrapper. A bare `make` prints the target list
rather than running the first target.

**`help` is generated from the targets, not maintained separately.** It greps
`MAKEFILE_LIST` for `^target:.*## description` and formats the pairs, so a new
target that carries a `##` comment shows up with no second edit — and one that
forgets the comment is invisible, which is the intended nudge. The convention
is documented in the file header.

**`check` uses recursive `$(MAKE)`, not prerequisites.** Prerequisite order is
not guaranteed under `make -j`, and the ordering is the point of the target:
typecheck and lint fail in seconds on an exact line, while the suite takes ~40s,
so a type error surfaced after the tests is time already spent. Make stops at
the first non-zero recipe line, so a lint failure is never buried under test
output. Verified: `make check` exits 0 on a clean tree, and
`make check ARGS=-kzzznope` exits 2 at the `test` step.

`coverage` stays out of `check` — it re-runs the same suite slower, and it is a
number to read rather than a gate to pass. `fmt` stays out because a check
target that rewrites the tree is unusable in CI.

**`ARGS` is forwarded to `test` and `coverage`** (`make test ARGS="-k board"`),
and because make passes command-line variables down through `$(MAKE)`, it
reaches `make check ARGS=...` too.

Config lives in `pyproject.toml` — `[tool.pytest.ini_options]`,
`[tool.ruff]`, `[tool.coverage.*]` — never in a recipe, so a bare
`uv run pytest` or `uv run ruff check .` behaves the same as the target.

Verified: `make`, `make typecheck`, `make lint`, `make test` (285 passed),
`make coverage` (87%), and `make check` all pass on a clean tree.

**Left open deliberately:** bv-45c8, turning on the `ARG` and `PTH` ruff
families. It is a source refactor across `bv/` and `tests/` plus a decision
about `config.py`'s `open(fd)`, not a Makefile deliverable — the targets are
what this epic is for, and they are all in.
