---
# bv-7no3
title: Resolve the board root from where bv was run, not a hardcoded ~/projects
status: completed
type: feature
priority: high
tags:
    - ux
    - packaging
created_at: 2026-08-17T17:52:44Z
updated_at: 2026-08-17T18:57:12Z
---

`DEFAULT_ROOT = Path.home() / "projects"` in `app.py` is my machine's layout
written into the program. It is invisible while the author is the only user and
becomes the first thing a stranger hits: `uv tool install
git+https://github.com/dlhedglin/bv` puts `bv` on their PATH, they run it, and
it reads a directory they do not have.

`bv [path]` is not part of this. It already works -- `main()` takes an optional
positional `root`, `type=Path`, and calls `.expanduser()` on it, so
`bv ~/some/other/dir` has been supported since the argument was added. What is
missing is a sensible answer when the argument is absent.

**Default to the current working directory**, and decide what to show from what
is actually there:

- **The directory is itself a beans project** -- run from inside a repo that
  holds `.beans`. Show its beans flat, with no project layer at all.
- **It is not** -- run from somewhere like `~/projects`. Scan one level down for
  beans projects and group by project, which is exactly what
  `discover_projects` does today.

One level down, not a recursive walk. The existing function already stops at
immediate subdirectories, and that limit is worth keeping deliberately: a
recursive scan of an arbitrary working directory can wander into `node_modules`
or a home directory and stat its way through a very large tree before drawing
anything.

Flat mode is not just skipping the heading rows. Every place the project is
currently surfaced becomes noise when there is exactly one:

- `tree.build_forest` groups into one tree per project and gives each a heading
  `Node` at depth 0. One project means one redundant heading with every bean
  indented beneath it for no reason.
- Board cards label themselves `f"{bean.project} · {bean.id}"`. The project half
  is the same string on every card.
- The status bar reads `... · {projects} projects · ...`, which would say
  "1 projects".
- `P`, "collapse to project headings", has nothing to collapse to.

Decisions, as resolved:

- **What counts as "a beans project".** `discover_projects` requires both a
  `.beans.yml` config and the `.beans` directory it points at. Detecting the
  flat case should use the same test, or the two paths disagree about what a
  project is and a directory with `.beans` but no config becomes visible one way
  and invisible the other.
- **Whether a bare `bv` in a directory with neither keeps any fallback to
  `~/projects`.** Decided: no fallback. `resolve_root` returns `Path.cwd()`
  resolved, and nothing substitutes a different directory when that one holds
  neither a project nor any beneath it -- such a directory is an empty board
  saying so. This does change what a bare `bv` does for me: it used to work from
  anywhere and now works from a beans project or a directory of them. That is
  the point, since the old behaviour was a path that exists on one machine.
- **Fold state is keyed by board root** in the config file. Cwd-relative roots
  mean many more keys than the handful there are now. Harmless, but confirm the
  file does not grow without bound over time.

Also in scope, since it is the same hardcoded path: `tests/test_watch.py` pins
`REAL_ROOT = Path("~/projects")` for a timing check. It is
`skipif`-guarded so it skips cleanly elsewhere and is not a bug, but it should
key off the same resolution as the app rather than a literal.
