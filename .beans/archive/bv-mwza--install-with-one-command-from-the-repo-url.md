---
# bv-mwza
title: Install with one command from the repo URL
status: completed
type: task
priority: high
tags:
    - packaging
created_at: 2026-08-17T17:41:13Z
updated_at: 2026-08-17T17:45:40Z
---

`uv tool install git+https://github.com/dlhedglin/bv` should be the whole
install. It needs no PyPI account, no release process and no distribution name
-- installing by URL means the `bv` name already taken on PyPI (0.1.4, a
bioinformatics data viewer) never enters it.

Two things are in the way:

- The repo is private, so the URL resolves to nothing for anyone else. Flip it
  public only after the licence lands, so there is no window where the code is
  public and unlicensed.
- The README's Install section is a development instruction --
  `uv tool install --editable ~/projects/bv`, a path only the author has.
  Editable is also the wrong shape to hand a stranger: it leaves the install
  pointing into a working tree, which is exactly what broke when the package
  moved to `src/bv`.

The `beans` CLI is a hard prerequisite -- bv reads the boards it produces and is
inert without it -- so it belongs above the install line, not in a footnote.

Verified before this closes: a clean non-editable install already works. Into a
fresh venv, `bv` runs from site-packages, `app.tcss` ships, the app starts and
loads 112 CSS rules. The suite passes on 3.11, so `requires-python = ">=3.11"`
is a tested claim rather than a guess.

Out of scope: publishing to PyPI (needs a distribution rename to something free
such as `beans-viewer`), a Homebrew tap, and CI. Separate beans if wanted.
