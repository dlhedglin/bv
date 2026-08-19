---
# bv-vwk4
title: make lint and make fmt with ruff
status: completed
type: task
priority: high
tags:
    - tooling
    - lint
created_at: 2026-08-17T06:26:12Z
updated_at: 2026-08-17T06:33:56Z
parent: bv-10rr
blocked_by:
    - bv-x2h1
---

ruff has been run against this repo at least once — there is a `.ruff_cache/` at
the root — but it is not a declared dependency and there is no `[tool.ruff]`
section in `pyproject.toml`, so the rule set is whatever the ambient ruff binary
defaults to that day.

Scope:

- Add `ruff` to the `dev` dependency group and `uv sync`, pinning it in
  `uv.lock` for the same reason ty is pinned.
- `make lint` runs `uv run ruff check .` — reports only, exits non-zero on a
  finding.
- `make fmt` runs `uv run ruff format .` and `uv run ruff check --fix .` — the
  writing counterpart. Keep it separate from `lint`: a check target that quietly
  rewrites files is unusable in CI and surprising in a pre-commit run.
- Add `[tool.ruff]` to `pyproject.toml` with an explicit `line-length` and
  `target-version` matching `requires-python` (3.11), plus a `select` list, so
  the rules come from the repo and not from ruff's defaults drifting between
  releases.
- Check `.ruff_cache/` is in `.gitignore`.

Pick the rule set against what the code passes now, same call as in the ty bean:
start with a set the repo is clean under, and file a follow-up for anything worth
turning on later rather than committing a target that fails on a fresh clone.


## Shipped

`ruff>=0.16,<0.17` in the `dev` group, resolved to 0.16.3 in `uv.lock`.

`[tool.ruff]` sets `line-length = 88` and `target-version = "py311"`, matching
`requires-python`. 88 was not a preference — the tree was already byte-identical
to `ruff format` output at that width, so adopting it made `make fmt` a no-op on
day one instead of a 22-file reformatting commit.

`[tool.ruff.lint].select` is `E, W, F, I, N, UP, B, C4, SIM, RET, RUF`. Baseline
across that set on first run was 1 finding: a `B007` in `bv/beans.py`, a `zip()`
in `load_all_beans` pairing each project with its result where the project half
was never read. Removed the `zip` rather than renaming the variable — `pool.map`
already preserves input order, so the pairing was doing nothing.

`ARG` and `PTH` are the two families deliberately left out, at 31 and 2 findings.
They are excluded from `select` rather than blanket-`ignore`d so the gap is
visible in the config, and the reasoning is in the follow-up, bv-45c8.

`make lint` runs `ruff check .` then `ruff format --check .` — the format check
belongs in `lint` because a formatting drift should fail CI, and `lint` is the
target CI will call. `make fmt` runs `ruff format .` then `ruff check --fix .`.
Verified `make lint` exits 2 on a planted `F401` and 0 on the clean tree.

`.ruff_cache/` added to `.gitignore`.

Landed on the Makefile skeleton from bv-x2h1, which was built concurrently in
the same checkout by another session. 285 tests pass; `make typecheck`, `make
lint` and `make fmt` are all clean. Nothing committed — the working tree holds
both beans' changes.
