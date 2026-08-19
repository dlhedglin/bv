---
# bv-go45
title: Move the package to src/bv, the layout uv scaffolds
status: completed
type: task
priority: normal
tags:
    - tooling
    - packaging
created_at: 2026-08-17T06:47:23Z
updated_at: 2026-08-17T16:31:11Z
---

The package lives at `bv/` in the repo root — the flat layout. uv scaffolds the
src layout for anything with a `[build-system]`, and this repo matches neither
of its shapes. Verified against uv 0.11.32:

- `uv init` (app) — `main.py` at the root, no package directory and no
  `[build-system]` at all.
- `uv init --package` — `src/<name>/__init__.py`, backend `uv_build`.
- `uv init --lib` — the same plus `py.typed`.

Nothing is broken today. Flat layout predates uv and hatchling supports it
fine. The one real cost is that a package directory sitting in the repo root is
on the import path, so `import bv` can resolve to the source tree rather than
the built artifact and the suite can pass against files that would not ship.
That is currently moot — `.venv` holds `_editable_impl_bv.pth` pointing back at
`bv/__init__.py`, so both routes reach the same files — but it stops being moot
the first time something is excluded from the wheel.

Scope:

- `git mv bv src/bv`, so the move is a rename in history rather than a
  delete-and-add and `git log --follow` still works on every module.
- Drop `packages = ["bv"]` from `[tool.hatch.build.targets.wheel]`. Hatchling
  is documented to auto-detect `src/<name>` for a project named `<name>`, which
  is the whole reason the line can go — but confirm it rather than assume, with
  `uv build` and an actual look inside the wheel. If the section ends up empty,
  delete the header too.
- `uv sync` to regenerate the editable install; the existing `.pth` points at
  the old path and will keep resolving to a directory that no longer exists.
- Fix the path references the move invalidates. There are few, and only two are
  load-bearing: `packages = ["bv"]` above, and the `make typecheck` comment in
  the `Makefile` that says "Type-check bv/ and tests/". The rest are prose
  inside comments (`bv/dispatch.py`, `bv/clipboard.py`, `bv/agents.py` in
  `app.py`). Every other hit for "bv" in the tree is the project *name* — the
  `bv` in `~/.config/bv/`, `project="bv"` in the test fixtures — and must not be
  touched.

Watch for, because each is a silent failure rather than a loud one:

- `make typecheck` runs `uv run ty check` with no path argument and there is no
  `[tool.ty]` section, so what it checks is whatever ty discovers. Confirm it
  still reaches the package under `src/` and has not quietly narrowed to
  `tests/`. If discovery no longer finds it, add an explicit `src` setting
  rather than passing a path on the Makefile line, so a bare `uv run ty check`
  and the target stay in agreement.
- `bv/app.tcss` is a non-Python file inside the package. Textual resolves
  `CSS_PATH = "app.tcss"` relative to the module, so the move itself is safe,
  but the wheel check above should confirm the `.tcss` is still packaged.
- `make test`, `make lint` and `make typecheck` all clean afterwards, and
  `uv run bv` actually starts — the console script goes through the reinstalled
  entry point, which is the part a stale editable install breaks.

Explicitly out of scope: switching the build backend from `hatchling` to
`uv_build`. That is uv's scaffold default now, but hatchling is mainstream, the
project builds today, and bundling a backend swap into a directory move makes
any resulting packaging failure ambiguous. Separate bean if it is wanted at all.

This has no bearing on the `testpaths` limitation recorded in bv-4q06. That one
is pytest's `invocation_dir == rootpath` rule; a bare `uv run pytest` from
`src/` will collect `src/` and find nothing, exactly as it does from `bv/`
today. The layout is orthogonal — do not expect this bean to fix it.
