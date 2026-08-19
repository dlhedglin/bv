---
# bv-ov50
title: Agent cell goes stale on a same-bean state change
status: completed
type: bug
priority: normal
tags:
    - quality
    - ui
created_at: 2026-08-18T20:27:36Z
updated_at: 2026-08-18T20:33:15Z
---

`_refresh_sessions` (app.py:842) decides whether the board needs a repaint by
comparing only the `{bean_id: label}` map:

    changed = {k: v.label for k, v in working.items()} != {k: v.label for k, v in self._working.items()}

But the Agent column renders on more than the label. `_agent_text` (app.py) colours
the cell by `found.session.state` -- yellow when `blocked`, green otherwise --
and `_project_agents` counts `session.is_busy`. Both read state the label does
not carry.

So a session that transitions working -> blocked on the same bean keeps the same
label and the same bean id, `changed` returns False, `check_for_changes` skips
`_render`, and the cell keeps its stale green (and the coarse "N agents" tier can
stay stale too) until an unrelated reload repaints.

Root cause: the change-detection key is narrower than the set of fields the
render depends on. Fix: fold the rendered state into the comparison, e.g. compare
`(v.label, v.session.state, v.exact)` per bean id, or hash whatever `_agent_text`
and `_project_agents` actually read.

Found in the pre-publication review (bv-6t3w).
