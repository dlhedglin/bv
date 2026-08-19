---
# bv-q2kp
title: Vim navigation in the bean table
status: completed
type: feature
priority: normal
tags:
    - ux
    - keybindings
created_at: 2026-08-14T21:36:34Z
updated_at: 2026-08-15T19:35:00Z
---

The table is currently arrow-keys-only, inherited from `DataTable`'s defaults.
Add vim motions so navigating 215 rows doesn't require reaching for the arrows.

Minimum set:

- `j` / `k` — row down / up
- `g` `g` / `G` — first / last row
- `ctrl+d` / `ctrl+u` — half-page down / up
- `/` — filter or search, `n` / `N` to step through matches
- `Esc` — clear the filter

Notes:

- `g` `g` is a two-key sequence, which Textual's `Binding` does not model
  directly. Either track a pending-`g` flag in the app and clear it on any other
  key, or bind `g` to "top" alone and accept the divergence from vim.
- `DataTable` already binds `j`/`k`-adjacent keys in some versions — check
  `DataTable.BINDINGS` before adding, and override rather than duplicate.
- Keep the arrow keys working. This is additive, not a replacement.

## Shipped

`j`/`k`, `G`, `ctrl+d`/`ctrl+u` for a half page, `/` to filter, `esc` to clear.
The arrow keys still work — this is additive.

`gg` uses the pending-flag option, disarmed by a 0.6s timer rather than by
watching for the next key. A timer sidesteps the ordering question of whether
`on_key` or the binding runs first, and matches vim's `timeoutlen`. Tested three
ways: a lone `g` must not move, `gg` must jump to the top, and `g` then `j` then
`g` must not.

`/` filters rather than search-and-step, so `n`/`N` are moot and were not built.
Filtering the tree lives in `tree.py` as `filter_forest`, which keeps the
ancestors of a match — a hit shown without its epic and project reads as an
orphan — and drops a project heading only when nothing under it survived. It
returns new nodes, so the unfiltered board is intact when you press escape.

Two things the filter forced, both found by looking at the rendered output:

* A filter overrides the fold state, so headings must draw as expanded. The
  marker read `▸` while the children were plainly visible.
* Folding is refused while a filter is active. It would otherwise have silently
  changed, and persisted, fold state that is not on screen.

This also closes the deferred item from bv-scx8: auto-refresh now skips a tick
whenever the filter input has focus, so the board cannot be redrawn under
someone mid-word.
