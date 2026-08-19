---
# bv-j06v
title: Display bean tags in the table
status: completed
type: feature
priority: normal
tags:
    - ux
created_at: 2026-08-14T21:36:34Z
updated_at: 2026-08-15T19:35:00Z
---

Tags are already fetched — `tags` is in the GraphQL query and lands on the
`Bean` dataclass as a `tuple[str, ...]`. They are simply never rendered.

Work is display-only:

- Add a Tags column to the table, or render tags inline after the title.
- Colour them distinctly from the title so they read as metadata. The existing
  `STATUS_STYLES` / `TYPE_STYLES` dicts in `bv/app.py` are the pattern to follow.
- Decide truncation. A bean with six tags should not push the title off screen —
  either elide past N tags with a `+3` marker, or give the column a fixed width.

Once visible, tags become the obvious filter axis, so this pairs naturally with
search/filter from the vim-navigation bean.

## Shipped

Inline after the title, in the theme's `text-secondary`, as `#tag`.

The column option was measured and rejected: only 25 of 229 beans carry tags
and none carry more than two, so a dedicated column would have been ~90% empty
while taking width from the titles. Elision past three tags with a `+N` marker
is implemented anyway, since nothing stops a bean acquiring more later.

Tags are also matched by the filter from bv-q2kp, which is what makes them
useful rather than decorative.
