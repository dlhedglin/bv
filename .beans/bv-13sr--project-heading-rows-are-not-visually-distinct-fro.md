---
# bv-13sr
title: Project heading rows are not visually distinct from bean rows
status: completed
type: bug
priority: high
tags:
    - ux
created_at: 2026-08-15T18:56:47Z
updated_at: 2026-08-15T19:35:00Z
---

Project heading rows currently differ from bean rows only by being bold. That
is not enough to read as a heading, especially next to `milestone` rows, which
are bold magenta, and `critical` priorities, which are bold red — the headings
recede into the same visual weight as the content they are supposed to be
organising.

Make the heading unmistakably a heading.

## What was already ruled out by rendering it

Filling the row with a background colour — `Text(..., style="on #1e3a5f")` or
`style="reverse"` — **does not work** in a `DataTable`. The style paints only
where there is text, not across the cell's padding or its empty width, so a
heading whose middle columns are blank renders as two disconnected coloured
blocks with a gap between them. It looks broken, not emphatic. This was tried
and rejected on the rendered output; do not re-attempt it expecting a full-width
bar.

Drawing a rule across the empty columns (`─────`) has the same problem in
reverse: the segments do not join across cell padding, so it reads as a dashed
line rather than a rule.

## What did read well

An accent colour plus a `▌` block glyph and an uppercased project name. It is
the only accent-coloured row on the board, so it separates cleanly from both the
dim bean rows and the magenta/red type and priority styling, and it survives a
theme change if the colour comes from the theme rather than a literal.

Vertical space is what actually creates the grouping, though. `DataTable.add_row`
accepts `height`, so a heading added with `height=2` and a leading newline in
its text gets a blank line above it that **belongs to the heading row**. That
gives the visual separation of a spacer row without adding a second, separately
selectable row that the cursor would have to skip over. Worth confirming the
interaction with `zebra_stripes` and with cursor movement before committing to
it.

Take the accent from the active theme (`App.theme_variables` or the design
tokens) rather than hard-coding a hex value, since bv now restores whichever of
the 21 themes was last used (bv-mhbw).

## Shipped

Accent colour from the active theme (`text-accent` via `App.theme_variables`,
never a literal), a `▌` rail, and the project name uppercased. `watch_theme`
re-renders so the heading follows a theme switch instead of going stale.

The separation comes mostly from vertical space: headings are added with
`height=2` and a leading newline, so the blank line belongs to the heading row.
No second selectable row for the cursor to skip, and it composes with
`zebra_stripes` without extra work.

Confirmed on the rendered output at every fold level.
