# bv

> A terminal viewer for [beans](https://github.com/hmans/beans) issues, across every repo at once.

[![check](https://github.com/dlhedglin/bv/actions/workflows/check.yml/badge.svg)](https://github.com/dlhedglin/bv/actions/workflows/check.yml)
[![security](https://github.com/dlhedglin/bv/actions/workflows/security.yml/badge.svg)](https://github.com/dlhedglin/bv/actions/workflows/security.yml)
[![coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fdlhedglin%2Fbv%2Fbadges%2Fcoverage.json)](https://github.com/dlhedglin/bv/actions/workflows/coverage.yml)

`beans tui` searches upward for a single `.beans.yml`, so it only ever shows one
project. bv addresses projects explicitly and puts a whole directory of repos on
one screen — as a folding tree or a kanban board — and shows which Claude Code
session is working which bean.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

bv reads the boards the [`beans`](https://github.com/hmans/beans) CLI writes and
renders them read-only. It exists as a client rather than a fork of beans for two
reasons:

- **Every repo at once.** `beans tui` resolves one `.beans.yml` by searching
  upward from the working directory, so it can only show a single project. bv
  addresses projects explicitly, so a directory of repos becomes one board.
- **Who is working what.** The interesting view — which Claude Code session or
  agent is on which bean — is not a beans concept. It lives in `~/.claude/`, and
  a client can join it in without carrying the beans codebase.

bv never mutates a bean. The only writes it causes are the ones a *dispatched
agent* makes to its own bean through its own CLI (see [Usage](#usage)); the bv
process itself issues no `beans update`.

## Install

bv reads the boards the `beans` CLI writes, so that comes first — without it
there is nothing to view:

```sh
brew install --cask hmans/beans/beans
```

Then bv itself, which needs no clone and no PyPI account:

```sh
uv tool install git+https://github.com/dlhedglin/bv
```

That puts `bv` on `PATH`. Python 3.11 or newer;
[uv](https://docs.astral.sh/uv/) downloads one if the machine has none.
`uv tool upgrade bv` moves to the latest commit, `uv tool uninstall bv` removes
it.

To try it without installing anything:

```sh
uvx --from git+https://github.com/dlhedglin/bv bv
```

## Usage

```sh
bv                 # browse the beans where you are
bv /path/to/repos  # browse somewhere else
```

What bv shows depends on where it runs:

- **A beans project** (a directory holding `.beans.yml` and `.beans/`) is the
  whole board, shown flat.
- **A directory of repos** is scanned one level down and the board is grouped by
  project.

Scanning is one level, never a recursive walk. A directory that is neither is an
empty board that says so.

### Keys

| key | |
| --- | --- |
| `j` / `k`, or the arrows | move down / up |
| `gg` / `G` | first / last row (tree only) |
| `h` / `l` | previous / next column (board only) |
| `ctrl+d` / `ctrl+u` | half a page down / up |
| `space` / `enter` | fold or unfold the row under the cursor (tree only) |
| `C` / `E` | collapse all / expand all (tree only) |
| `P` | collapse to project headings (tree only, multi-project boards) |
| `/` | filter by title, id, tag, type or status |
| `esc` | clear the filter |
| `r` | reload now |
| `a` | show or hide archived beans |
| `b` | switch between the tree and the kanban board |
| `S` | start a background Claude agent on this bean (asks first) |
| `W` | start one in an isolated git worktree (asks first) |
| `y` / `Y` | copy this bean's id / its id, title and status |
| `w` | pause or resume watching |
| `ctrl+p` | command palette, including the theme picker |
| `q` | quit |

The board refreshes itself when bean files change, so it stays current while
agents write to it in the background. Fold state and the chosen theme are
remembered across restarts.

### Starting an agent

`S` opens a confirmation showing the working directory, the session name and the
whole prompt, then dispatches `claude --bg` on the bean; the agent edits the
project's checkout directly. `W` does the same but adds `--worktree`, so the
agent lands in an isolated git worktree on its own branch — its edits reach the
board only when that branch is merged. Either way the dialog asks first, because
there is no undo beyond `claude stop`.

bv chooses the session `--name` and puts the bean id in it, which is what makes
the Agent column an exact match for anything bv started rather than a guess from
a working directory. It is a warning, never a lock: beans has no assignee field,
so a second agent started elsewhere is noted but not prevented.

## Maintainers

[@dlhedglin](https://github.com/dlhedglin)

## Contributing

```sh
uv sync && uv run bv   # run it from the repo
make hooks             # install the pre-commit gate (once per clone)
make check             # typecheck, lint and the test suite — run before committing
make help              # every other target
```

`make hooks` points git at the version-controlled `.githooks/pre-commit`, which
runs `make check` before each commit — the same gate CI enforces. Bypass a
single commit with `git commit --no-verify`.

Issues and pull requests are welcome. Please run `make check` before opening a
PR.

## License

[MIT](LICENSE)
