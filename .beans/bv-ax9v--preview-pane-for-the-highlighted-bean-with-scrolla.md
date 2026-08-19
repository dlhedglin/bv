---
# bv-ax9v
title: Preview pane for the highlighted bean, with scrollable body
status: completed
type: feature
priority: high
tags:
    - ux
created_at: 2026-08-14T21:36:34Z
updated_at: 2026-08-15T20:10:00Z
---

A bean's title is rarely enough to know what it is. The row under the cursor
should render its markdown body in a preview pane, scrollable independently of
the table.

Work:

- Add `body` to the GraphQL query in `bv/beans.py` and to the `Bean` dataclass.
  The field exists on beans' `Bean` type (`body: String!`) so this is one word
  in `QUERY`, no new round trip.
- Split the screen — table left or top, preview in the other half. `app.tcss`
  already sizes the table `1fr`; a `Horizontal`/`Vertical` container plus a
  second `1fr` gets the split.
- Render the body as markdown. Textual ships a `Markdown` widget; a
  `VerticalScroll` wrapper or `MarkdownViewer` gives the scrolling.
- Drive it off `DataTable.RowHighlighted`, not `RowSelected`, so the preview
  tracks the cursor rather than requiring Enter.
- Scroll keys must not fight the table's cursor keys. Either give the preview
  focus on `tab`, or bind separate keys (e.g. `ctrl+f`/`ctrl+b`) that scroll the
  preview while the table keeps focus.

Also worth showing in the preview header: full bean id, parent, and blocking /
blocked-by, since none of those fit in the table.

Measure the load after adding `body`. 215 beans currently load in ~0.1s; bodies
are the largest field on the type and could change that. If it does, fetch
bodies lazily for the highlighted row instead of in the bulk query.

## Shipped

`bv/preview.py` holds `BeanPreview(VerticalScroll)` — no imports from `bv.app`,
no bindings of its own, styling in `DEFAULT_CSS`. `app.py` mounts it beside the
table in a `Horizontal`, at `1fr` against the table's `2fr` and capped at 72
columns so it cannot swallow a wide terminal.

`Markdown` inside a `VerticalScroll` rather than `MarkdownViewer`: the latter is
the same pair plus a table-of-contents sidebar and link history. Bean bodies are
a few hundred words with zero or two headings, so the sidebar would spend a
third of an already-narrow pane on an empty list and add a second focus target
inside it.

Driven by `RowHighlighted`, not `RowSelected`, so it tracks the cursor rather
than needing Enter. A project heading shows the empty state instead of raising.
`ctrl+f` / `ctrl+b` scroll it while the table keeps focus, so `j`/`k` still
drive the board; `p` hides it to give the titles the full width back.

**The bug this design had to avoid:** `_render` clears and re-adds every row on
every fold and every auto-refresh, which re-fires the highlight with an
identical bean. Re-parsing the markdown there would throw the reader's scroll
position away mid-read — precisely the failure this bean warned about. `show()`
no-ops when the bean has not changed, and a different bean scrolls back to the
top. Verified: scrolled to y=40, forced a full re-render, still y=40.

## The performance question, answered

The concern above was that bodies are the largest field on the type. Measured,
interleaved A/B, 12 paired runs against the real board (229 beans, ~670 KiB of
bodies): **20.5 ms before, 22.4 ms after — +1.9 ms, about 9%.**

So no lazy per-row fetching, and the reasoning is worth keeping: the load is
dominated by five process spawns, not by payload size, so one extra `beans`
spawn per cursor move (~20 ms) would cost more than the entire bulk fetch it
was meant to avoid.

This also corrects a number that had propagated into three files. The full load
is **~21 ms**, not the ~100 ms quoted in earlier notes; the cold first call in a
fresh process is 70–110 ms, but that is interpreter and page-cache warm-up, not
the query.

## One scope change

The bean assumed only blocking *titles* were missing. In fact the dataclass
carried no blocking data at all, so the header was unbuildable as specified.
`blockingIds` and `blockedByIds` are plain scalars on the same GraphQL type — no
nested selection, no extra round trip, +0.4 ms — so they were added alongside
`body` and the header shows them. The resolved `blocking`/`blockedBy`
connections would have cost a round trip; those were not used.
