---
# bv-zl4j
title: Kanban board view
status: completed
type: feature
priority: normal
tags:
    - ux
created_at: 2026-08-17T03:33:13Z
updated_at: 2026-08-17T03:33:13Z
---

## Why

Asked for directly after seeing `Dicklesworthstone/beads_viewer`, which binds
a board view to `b`. The tree answers "how does this project decompose"; a
board answers "what is in flight right now", and the two do not substitute for
each other.

## The board is worth building — measured

Visible beans today, archived excluded:

    in-progress   18
    todo         107
    draft         11
    completed     81
    scrapped       1

That is five real columns with real occupancy, and the in-progress column is
spread across every project — demo-d 6, demo-a 5, demo-c 4, demo-b
3 — which is exactly the view the tree cannot give, because it buries those 18
under their own epics in four separate subtrees.

Compare with the graph view from the same tool, which was measured and
rejected: 18 dependency edges across the whole board, so a DAG would render
mostly isolated dots. The board is the half of that tool worth copying.

## The row/column view is not in the way

bv is already split so this does not need a rewrite. Of 1901 lines,
`beans.py`, `tree.py`, `watch.py`, `config.py`, `preview.py` carry no table
assumptions at all — `tree.py` does not even import Textual. Only `app.py`
(725 lines) is view-coupled.

A board is a `Horizontal` of `VerticalScroll` columns with card widgets. No
`DataTable` involved, and no data-layer change: fold state, watching,
filtering, archive hiding, the blocked resolution and `beans.rank` all carry
over untouched.

## Design questions to settle first

- **Column set.** Five statuses, or fold draft into todo and scrapped into
  completed to get a three-column board? 11 drafts and 1 scrapped are thin.
- **Grouping inside a column.** By project, or flat and sorted by
  `beans.rank`? Flat loses the project, grouped costs vertical space that a
  107-card column does not have.
- **What a card shows.** Title plus what — project, priority, tags, blocked,
  the agent working it? A card is not a row and cannot carry all five.
- **Does the cursor stay vim-navigable across columns?** `h`/`l` between
  columns and `j`/`k` within one is the obvious mapping and is not currently
  bound.
- **Read-only.** Moving a card between columns is a status write, which bv
  does not do — beans 0.4.2 ships #205 and #208 unpatched. The board shows
  status; it does not set it.

## Scope

- A new module for the board, mounted in place of the table, toggled by a key.
- The existing preview pane should keep working beside it.
- No data-layer change expected. If one turns out to be needed, that is a
  signal the split is wrong and worth stopping over.


## Shipped

`bv/board.py` — `BeanBoard`, a `Horizontal` of four `BoardColumn`s, each a
pinned heading over a `VerticalScroll` of cards. Bucketing and all card text
are Textual-free module functions, so most tests need no app.

Interface the app drives is four things: `set_beans`, `selected`, `move`, and a
`Selected` message. `b` toggles it.

## The open questions, answered with measurements

**Flat, not grouped by project.** `todo` holds 107 cards, so only its top is
ever visible; grouping would bury the most actionable bean of the last project
under ~90 cards of the first three — exactly what `beans.rank` exists to
prevent. The project is not lost, every card carries it.

**Card = two lines of title + `badges · project · id`.** Chosen by re-measuring
rather than taste: priority is `high` on 84 of 219 and `normal` on 104, so an
"above normal" badge would paint 38% of the board — only `critical` (9 of 219)
is rare enough to signal. `blocked` stays, because `rank` sorts on it and a
card low in a column needs to say why. Tags are on 28 of 219 and the preview
lists them anyway. Titles measured median 53 / p90 76 / max 96 chars against a
~20–23 char card, hence two lines, padded to exactly two so meta lines align
down the column. Badges lead the meta line so they survive truncation.

**Selection is remembered per column and restored by bean id**, which means the
cursor follows a bean into its new column when its status changes under a watch
refresh. Columns reuse card widgets in place rather than clear-and-remount, so
a deep scroll survives — the same class of bug already fixed once in
`preview.py`. `scroll_visible` only fires when the cursor lands on a different
card, so a rebuild never yanks a reader who wheeled away.

First mount of all 219 cards measured ≈124 ms; an unchanged `set_beans`
early-returns.

## Integration notes

The `DataTable` stays mounted and is hidden with a class rather than removed:
almost every action in `app.py` reaches for it with a bare `query_one`, so
removing it would turn every fold key into a `NoMatches` traceback the moment
the board was up.

`_sync_preview` now no-ops while the board is showing. Focusing the board makes
the table emit a highlight, which was overwriting the board's selection — the
preview read "no bean selected" while a card was visibly highlighted. Caught by
looking at a rendered screenshot, not by a test.

The filter is now one predicate shared by both views, because a `/` that meant
different things either side of `b` would look like a bug in the filter.

Read-only, as scoped: cards never move between columns. `scrapped` folds into
`completed` (1 bean), and a card whose status differs from its column says so.
