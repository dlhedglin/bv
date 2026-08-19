---
# bv-emo7
title: Parent/child tree view with collapsing by project, milestone, epic and feature
status: completed
type: feature
priority: high
tags:
    - ux
    - hierarchy
created_at: 2026-08-14T21:36:34Z
updated_at: 2026-08-14T22:05:00Z
---

The flat table loses the structure that beans already records. Beans have
`parentId` and `children`, and types are hierarchical (milestone > epic >
feature > task/bug), but bv renders all 215 rows at one level.

Render the hierarchy and make it collapsible at every level:

- project (the top grouping — 4 repos today)
- milestone
- epic
- feature
- task / bug as leaves

Data is already in hand: `parentId` is in the query and on the `Bean`
dataclass. Building the tree is a local group-by on `(project, parentId)` — no
extra beans calls needed. Beware orphans: a bean whose `parentId` points at a
bean that is filtered out, archived, or in another project must still appear,
parented to the project root rather than dropped.

The open design question is the widget. `Tree`/`TreeControl` gives collapsing
for free but loses the aligned Repo/ID/Type/Pri/Status columns that make the
current view scannable. A hierarchical `DataTable` — indent the title cell,
maintain a collapsed-set, and rebuild rows on toggle — keeps the columns but
means owning the expand/collapse logic. Prefer the second unless the column
alignment turns out not to matter in practice.

Keys: `space` or `Enter` to toggle the node under the cursor, `za` for
vim-style toggle, and something for collapse-all / expand-all. Persist the
collapsed set across refresh (`r`) so reloading doesn't blow away the view — and
ideally across restarts, alongside the theme.

## Shipped

Hierarchical `DataTable`, not `Tree` — the aligned Repo/ID/Type/Pri/Status
columns were worth keeping, so the tree lives in the indented title cell.

`bv/tree.py` holds the shape (pure, no Textual import, 12 tests); `bv/app.py`
renders it. Both hazards the bean called out are covered by named tests, because
both fail by silently dropping beans rather than by raising: an unresolvable
`parentId` demotes to the project root, and beans trapped in a parent cycle are
surfaced at the root after the walk rather than vanishing.

Keys: `space`/`enter` toggle, `C` collapse all, `E` expand all, `P` collapse to
projects. Collapse state is keyed by project name / bean id, never row index, so
it survives a reload that reorders the board; it persists across restarts too,
keyed by board root in the config file from bv-mhbw.

Verified against the real board: 227 rows = 222 beans + 5 project headings,
nesting to depth 3, `C` → 5 rows, `P` → 31, and folding an ancestor moves the
cursor onto that ancestor rather than snapping to the top.
