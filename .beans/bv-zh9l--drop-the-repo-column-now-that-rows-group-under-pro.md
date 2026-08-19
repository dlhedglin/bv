---
# bv-zh9l
title: Drop the Repo column now that rows group under project headings
status: completed
type: feature
priority: normal
tags:
    - ux
created_at: 2026-08-15T18:56:59Z
updated_at: 2026-08-15T19:35:00Z
blocked_by:
    - bv-13sr
---

Now that rows are grouped under a project heading (bv-emo7), the Repo column
repeats on every row what the heading directly above already says. It is the
widest low-information column on the board.

Drop it. Columns become ID, Type, Pri, Status, Title, and the reclaimed width
goes to Title, which is currently the column that truncates.

## Prerequisite

The project name has to survive the removal, so the heading row must carry it —
that is bv-13sr's job, and this should land with or after it rather than
before, otherwise the board briefly has no project name on it at all.

## The one real objection

Scroll far enough into a large project and its heading scrolls off the top, at
which point nothing on screen names the repo. Three ways out, in order of
preference:

1. Accept it. Folding is the answer — `P` collapses to headings, and a project
   you are reading inside is one you just navigated into.
2. Put the current project in the subtitle, driven by the cursor row. Cheap, and
   it doubles as useful context for the preview pane (bv-ax9v).
3. `DataTable` supports fixed rows, but only pinned at the top of the table, not
   a sticky heading that changes as you scroll — so a true sticky project
   heading is not available without building it.

Do not solve this by keeping the column.

## Shipped

Columns are now ID, Type, Pri, Status, Title. The reclaimed width went to
titles, which were the column that truncated.

Took option 1 from above — accept that the heading scrolls off, because `P`
folds to headings and gets your bearings back in one keypress. The subtitle
route stays available if that turns out to be annoying in practice, and the
preview pane (bv-ax9v) will name the bean's project anyway.
