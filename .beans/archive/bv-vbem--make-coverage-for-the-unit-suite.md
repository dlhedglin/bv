---
# bv-vbem
title: make coverage for the unit suite
status: completed
type: task
priority: normal
tags:
    - tooling
    - testing
created_at: 2026-08-17T06:26:27Z
updated_at: 2026-08-17T06:53:21Z
parent: bv-10rr
blocked_by:
    - bv-4q06
---

Follows `make test`. Nothing measures coverage on this repo today, so there is no
number to point at when deciding whether a change is tested.

Scope:

- Add `pytest-cov` to the `dev` dependency group and `uv sync`.
- `make coverage` runs the suite with coverage over the `bv` package only —
  `--cov=bv` — and prints a terminal report with missing lines
  (`--cov-report=term-missing`).
- Also emit `--cov-report=html` into `htmlcov/`, and add `htmlcov/` and
  `.coverage` to `.gitignore`. The terminal report says which files are thin;
  the HTML one is what gets read when actually filling a gap.
- Keep coverage out of `make test`. Coverage instrumentation slows the suite and
  the fast target is the one run on every save.
- Do **not** set `--cov-fail-under` in this bean. Record the baseline percentage
  in the Shipped notes first; picking a threshold before the number is known
  either sets it uselessly low or breaks the target immediately.

Config goes in `[tool.coverage.run]` / `[tool.coverage.report]` in
`pyproject.toml` rather than in the make recipe, so the settings apply to a bare
pytest run as well.


## Shipped

`make coverage` runs the suite under coverage and writes both reports;
`make test` is untouched and stays uninstrumented.

**Baseline: 87% of 1521 statements and 348 branches, 285 tests passing.**
Per-module, the two thin files are `bv/app.py` at 71% (124 statements missed —
mostly action handlers and the key-binding methods that no test drives) and
`bv/beans.py` at 78% (the subprocess error paths and the yank/write helpers).
Everything else is 96% or better, and `clipboard.py`, `config.py` and
`dispatch.py` are at 100%. `bv/__main__.py` reads 0% because its three lines
only execute under `python -m bv`, which the suite never does.

Still no `fail_under`, as the bean asked. 87% is the number to argue from when
someone picks one; the honest floor is lower than the headline because branch
coverage is on and `app.py` drags the total.

Notes on how it is wired:

- `[tool.coverage.run] source_pkgs = ["bv"]` rather than `source = ["bv"]`.
  The project is installed editable into `.venv`, so a path-based source can
  count the same module twice under two names; `source_pkgs` measures the
  package wherever it resolves from.
- `branch = true`. Statement coverage alone calls a half-taken `if` covered,
  which is exactly the case worth seeing in a TUI full of conditional key
  handling. It is why the number is 87% and not a point or two higher.
- `show_missing = true` lives in `[tool.coverage.report]`, so a bare
  `uv run pytest --cov` prints the same missing-line column the target does.
  The recipe still passes `--cov=bv --cov-report=term-missing --cov-report=html`
  explicitly: `--cov` on the command line is what turns instrumentation on at
  all, and keeping it there is what keeps `make test` fast.
- `htmlcov/` is coverage's default output directory, so no `[tool.coverage.html]`
  section. `.coverage` and `htmlcov/` are both in `.gitignore`.
- No `exclude_lines` additions. The tree has no `TYPE_CHECKING` blocks,
  `@overload`s or `NotImplementedError` stubs to exclude, and excluding
  patterns that do not occur only hides the day one appears.

The cost of keeping it separate is real but not dramatic: the full sweep is
about 33-37s under `make test` and about 46s under `make coverage` on this
machine, so instrumentation is roughly a third again on top. That is enough to
notice on every save and not enough to avoid running before a commit.
`make check` deliberately leaves `coverage` out for the same reason — it
re-runs the same suite slower, and it is a number to read rather than a gate to
pass.

Verified: `make coverage` exits 0 with the table above and writes `htmlcov/`,
`make coverage ARGS="-k test_clipboard"` forwards to pytest the same way `test`
does, a bare `uv run pytest --cov` picks up `source_pkgs` and `show_missing`
from `pyproject.toml` and reports `bv` only, `make test` still runs without the
coverage plugin's report, `git check-ignore .coverage htmlcov/` hits both, and
`make lint` and `make typecheck` are clean.
