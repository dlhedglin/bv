---
# bv-4q06
title: make test for the unit suite
status: completed
type: task
priority: normal
tags:
    - tooling
    - testing
created_at: 2026-08-17T06:26:27Z
updated_at: 2026-08-17T06:41:12Z
parent: bv-10rr
blocked_by:
    - bv-x2h1
---

There are ten test modules under `tests/` and pytest is already in the `dev`
group, but the invocation lives only in muscle memory.

Scope:

- `make test` runs `uv run pytest`.
- Add `[tool.pytest.ini_options]` to `pyproject.toml` with `testpaths = ["tests"]`
  and a sensible `addopts`, so a bare `uv run pytest` behaves the same as the
  make target and neither depends on the working directory.
- `make test ARGS="-k board"` should pass through to pytest, so the target is
  usable for a single failing test and not just the full sweep. Forward `$(ARGS)`
  rather than adding a second target.
- Confirm `.pytest_cache/` is in `.gitignore`.

Textual has an async test story (`run_test()`, pilot); if the suite already
relies on it, whatever plugin makes that work belongs in the `dev` group and
pinned too, not assumed present.

## Shipped

`make test` runs `uv run pytest $(ARGS)`, so the one target covers the sweep and
a single test: `make test ARGS="-k board"` (73 selected), `make test ARGS="-k
'board and column' -q"` (21 selected), `make test ARGS=-x`. Quoting survives
because make passes the variable through to the shell untouched. Full sweep is
285 passed.

`[tool.pytest.ini_options]` in `pyproject.toml`:

- `testpaths = ["tests"]`
- `addopts = "-ra --strict-markers --strict-config"`. `-ra` spells out skips and
  xfails instead of leaving them a single character in the progress line —
  `test_watch.py` has a `skipif` on the real board being present, which is worth
  seeing rather than guessing at. The two `--strict` flags turn a typo into an
  error: an unregistered marker otherwise means the test it decorates quietly
  does nothing, and an unknown ini key means this section is not doing what it
  says. The suite only uses builtin markers (`parametrize`, `skipif`), so
  `--strict-markers` costs nothing today and catches the first `@pytest.mark.slow`
  someone invents.

`.pytest_cache/` added to `.gitignore` — it was not there, only `.ruff_cache/`.

**No async plugin, and the bean's conditional does not fire.** The suite uses
`run_test()` and pilot heavily (41 async test bodies across `test_board.py`,
`test_preview.py`, `test_dispatch.py`) but reaches them through its own
module-level decorators — `board_test` and its siblings — which wrap each async
body into a sync function driving `asyncio.run`. Nothing imports anyio or
pytest-asyncio, so there is no unpinned dependency hiding here. That style is
also self-policing on pytest 9: an `async def test_` that reaches the collector
unwrapped now *fails* with "async def functions are not natively supported"
rather than warning and skipping, so a new one added without the decorator is
loud rather than silently green. Verified against a throwaway module. Nothing to
add to the `dev` group.

**One deviation from the scope, and it is pytest's rule, not a shortcut.**
`testpaths` cannot make a bare `uv run pytest` working-directory independent:
pytest only consults it when the invocation directory *is* the rootdir
(`Config._decide_args`: `if invocation_dir == rootpath`). From `bv/` a bare
`uv run pytest` finds `pyproject.toml` and applies `addopts`, but collects `bv/`
and reports `collected 0 items`. What the section does buy is that the rootdir
and every setting resolve from anywhere, and `make` is always run from the root
— directly or via `make -C` — so the *target* is genuinely
working-directory independent. The comment in `pyproject.toml` says this rather
than overclaiming.

Verified: `make` lists the new target, `make test` is 285 passed, ARGS forwards,
`uv run pytest` from the root matches the target, `git check-ignore
.pytest_cache/` hits, and `make lint` and `make typecheck` are still clean.
