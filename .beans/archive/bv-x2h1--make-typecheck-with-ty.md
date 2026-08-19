---
# bv-x2h1
title: make typecheck with ty
status: completed
type: task
priority: high
tags:
    - tooling
    - types
created_at: 2026-08-17T06:26:02Z
updated_at: 2026-08-17T06:33:25Z
parent: bv-10rr
---

First target under the Makefile epic, so this one also lands the skeleton the
rest hang off.

`ty` is Astral's type checker. It is not currently a dependency of this project
and nothing type-checks `bv/` today.

Scope:

- Create the root `Makefile` with `.PHONY`, and a default goal that prints the
  available targets rather than running one. A `help` target grepping `##`
  comments off the target lines keeps the list from going stale.
- Add `ty` to the `dev` dependency group in `pyproject.toml` and `uv sync`, so
  the version is pinned in `uv.lock` and every machine checks with the same one.
  Prefer this to `uvx ty`, which silently floats to the latest release.
- `make typecheck` runs `uv run ty check`.

Expect the first run to be noisy. `bv` is untyped in places and `textual` is
heavily generic, so decide explicitly rather than by accident:

- If the error count is small, fix them and let the target be clean from day one.
- If it is large, configure `[tool.ty]` in `pyproject.toml` to a rule set the
  code passes today, note in this bean which rules were suppressed, and file a
  follow-up bean for tightening them. A target that has never passed gets
  ignored, which is worse than a narrow one that passes.

Record the actual error count from the first run in the Shipped notes — it is
the baseline any future tightening is measured against.

## Shipped

`ty 0.0.72`, pinned as `ty>=0.0.72,<0.1` in the `dev` group. The range is
narrow on purpose: ty is pre-1.0 and its rule set still moves between `0.0.x`
releases, so a new checker version should be a deliberate bump rather than a
surprise from a fresh `uv sync`.

**Baseline: 16 diagnostics on the first run, all fixed. No `[tool.ty]` section,
no suppressed rules — the target passes on ty's defaults from day one.** There
is nothing here for a follow-up bean to tighten.

The 16 were four distinct problems, not sixteen:

- `bv/app.py` — `check_action` named its second parameter `_parameters` where
  `DOMNode.check_action` calls it `parameters`. A caller passing it by keyword
  would have missed; renaming it is the fix.
- `bv/app.py` — `action_toggle` (fold the row under the cursor) shadowed
  Textual's own `DOMNode.action_toggle`, which is async and takes a reactive
  attribute name. A real collision, not a typing artifact. Renamed to
  `action_fold`, with the `space` binding, `TREE_ONLY_ACTIONS` and the
  `run_action` calls in `tests/test_app.py` moved with it.
- `bv/dispatch.py` — `can_dispatch` returned a plain `bool`, so
  `if not can_dispatch(bean): return` did not narrow `Bean | None` and the
  three uses after the guard each errored. Now returns `TypeGuard[Bean]`;
  runtime behaviour is unchanged.
- The rest were tests: a `**{**base, **kwargs}` splat inferring `str | bool`,
  an unguarded `board.selected.id`, and two `# type: ignore[index]` comments in
  mypy's spelling. ty wants `# ty: ignore[invalid-assignment]`.

`make typecheck` runs `uv run ty check` with no path argument, which picks up
`bv/` and `tests/` both — the tests are where the fixture-shaped type errors
live, so excluding them would have hidden most of this baseline.

The Makefile skeleton landed here too: `.DEFAULT_GOAL := help`, `.PHONY`, and a
`help` target that greps `##` off the target lines. bv-vwk4 appended `lint` and
`fmt` to it in the same working tree.

Verified: `make` lists the targets, `make typecheck` passes, and the 285-test
suite and `ruff check` are still clean after the source renames.
