---
# bv-0ejt
title: Status bar counts archived beans it is hiding
status: completed
type: bug
priority: normal
tags:
    - quality
    - ui
created_at: 2026-08-18T18:05:22Z
updated_at: 2026-08-18T20:29:33Z
---

The status-bar summary counts archived beans it is simultaneously hiding.
Found in the pre-publication review (bv-6t3w).

`BeansViewer._summarize(beans)` is handed the bean list by each caller. Three
callers pass the raw `self._beans` instead of `self._visible_beans()`:

- `action_toggle_watch` (app.py:442) -- pausing the watch
- `action_clear_filter` (app.py:1036) -- leaving a filter
- `on_input_changed` (app.py:1041) -- each keystroke while filtering

`self._beans` includes archived beans, which the board hides unless `a` is
pressed. The canonical callers -- the load path (app.py:360), the archive
toggle (app.py:394) and `_resummarize` (app.py:1078) -- all pass
`self._visible_beans()`.

The result contradicts itself. With two live beans and one archived, pausing
the watch shows:

    3 beans · 3 open · 0 in progress · 1 archived hidden · paused

-- the same line counts the archived bean and says it is hidden. Under a filter
the "N of M" denominator is inflated the same way: "2 of 3 beans" where only
two beans can ever match.

Fix: pass `self._visible_beans()` at all three call sites, matching the other
callers. One line each.

Failing tests are already committed (xfail, strict) in tests/test_app.py:
`test_pausing_the_watch_counts_only_the_visible_beans` and
`test_the_filter_denominator_counts_only_the_visible_beans`. Dropping the two
`@pytest.mark.xfail` markers turns them into the regression guard once fixed.

Out of scope for bv-6t3w's read-only pass; filed as its own bean per that
bean's rule that findings needing a code change become beans.
