---
# bv-45c8
title: Turn on the ruff rules left out of the initial select
status: scrapped
type: task
priority: low
tags:
    - tooling
    - lint
created_at: 2026-08-17T06:33:31Z
updated_at: 2026-08-17T14:15:55Z
parent: bv-10rr
---

`[tool.ruff.lint].select` in `pyproject.toml` was set to the largest set the
tree was already clean under (bv-vwk4). Two families were left out rather than
suppressed with a blanket `ignore`, so the omission stays visible:

- `ARG` — 31 findings, 24 `ARG001` and 7 `ARG005`. Nearly all are Textual event
  handlers and test doubles that have to keep a parameter they never read in
  order to match the signature they are standing in for. Turning `ARG` on means
  either renaming those parameters to a leading underscore across `bv/` and
  `tests/`, or a per-file ignore for the widget modules. Worth deciding, but it
  is a real refactor and not part of landing the target.
- `PTH` — 2 findings, both in `bv/config.py`'s atomic settings write.
  `PTH123` wants `Path.open()` in place of `open(handle, "w")`, where `handle`
  is the file descriptor from `mkstemp`. `Path.open()` cannot take a descriptor,
  so following the rule would mean restructuring the write. The adjacent
  `PTH105` on `os.replace` is a fair hit and would be a one-line change.

Anything added here should be added the same way: confirm the tree is clean
under the new rule first, since a target that fails on a fresh clone stops
being run.


## Scrapped

The `[tool.ruff.lint].select` this bean was written against no longer exists.
The hand-written 11-family list was dropped in favour of ruff's own default
rule set, so there is no longer a curated selection with visible omissions to
close -- there is a default, and `ARG`/`PTH` sit outside it the same way the
other ~650 non-default rules do. Reopening the question would mean arguing for
two specific opt-ins on their own merits, not finishing a list.

For the record, the counts have not moved: `ruff check --select ARG,PTH` still
reports 34 findings (24 ARG001, 7 ARG005, 1 ARG002, 1 PTH123, 1 PTH105), and
the reasons they were skipped -- Textual handler signatures, and `mkstemp`
returning a descriptor `Path.open()` cannot take -- still hold.
