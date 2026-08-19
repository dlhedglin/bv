---
# bv-41rc
title: Board columns do not re-expand after the terminal grows back
status: completed
type: bug
priority: normal
tags:
    - ux
created_at: 2026-08-19T17:06:59Z
updated_at: 2026-08-19T17:20:56Z
---

Split the terminal to half a monitor and back and the layout does not track the size change cleanly. Two distinct symptoms, both in the shrink-then-grow direction:

1. **Slow to re-sync while resizing.** Dragging the terminal to half-width, the Title column takes a visible beat to settle at the new size rather than tracking the drag.
2. **Does not re-expand on re-maximize.** Growing the terminal back to full width, the columns stay narrow — the Title column keeps its shrunken width instead of re-expanding to fill the reclaimed space.

The whole point of bv is a wide board on a big screen, so a Title column stuck at half-width after re-maximizing is the exact case that has to look right.

## Where it comes from

Resize *is* wired — `BeansViewer.on_resize` (`src/bv/app.py:477`) re-fits the DataTable Title column and `BeanBoard.on_resize` (`src/bv/board.py:529`) re-wraps kanban cards. But both handlers are gated by a "did the width actually change?" no-op guard, and that guard is what makes growth sticky:

- `_fit_title_column()` (`app.py:448-475`) computes `room = table.size.width - taken - 2*cell_padding - scrollbar_size_vertical`, then `width = max(MIN_TITLE_WIDTH, room)`, and **early-returns `False` when `width == self._title_width`**. When it early-returns, `_render()` never re-runs, so the per-cell truncation at `app.py:783,798` never re-widens the visible titles. If `table.size.width` grew but the recomputed `width` lands on the cached value — or an `on_resize` does not fire at the moment the table actually gained its columns back — the column stays narrow.
- The reserved `scrollbar_size_vertical` and `2*cell_padding` are *always* subtracted (`app.py:469`), so `room` is permanently conservative. Good against scrollbar oscillation, but it also means the grow-back target can miss.
- The board view has the same shape: `on_resize` caches `self._width` and early-returns when unchanged (`board.py:534`); the intentionality is even pinned down by a test that force-resets `board._width = 0` to get past the no-op guard (`tests/test_board.py:621-629`).

The "slow to re-sync" half is most likely layout timing: several paths defer the re-fit a tick via `call_after_refresh(self.on_resize)` (`app.py:532`, `app.py:733`), and a fast drag emits a burst of resize events, so the settle lags the drag.

## What "flow dynamically" should mean here

- On any terminal-size change, the visible Title width and card widths should end at the size the *current* `table.size.width` implies — never stay pinned to a previously cached smaller value. The cache guard is a render-skip optimization; it must not be able to swallow a real growth. Options: recompute against actual current width and treat "cached == new" as "already correct" only when the measured available width also matches, or invalidate the cache on the grow edge.
- Track the drag rather than lag it: coalesce the resize burst (debounce/throttle) so it settles promptly once the drag stops, instead of leaving the column mid-resize.
- Keep the anti-oscillation reserve (the scrollbar/padding subtraction exists for a reason — see the preview-lag bean bv-4pli neighborhood of rendering concerns), but make sure it does not cause a stable-state under-fill after a grow.
- Verify all four size-changing entry points end correct: raw terminal resize, preview toggle (`action_toggle_preview`, `app.py:716-733`), board/tree toggle (`app.py:532`), and mount. The toggles already route through the deferred `on_resize`; the raw terminal grow is the one the report says fails.

## Things to get right

- Do not reintroduce the scrollbar oscillation the reserved width guards against — measure at the settled size, not mid-frame.
- The teardown hazard from bv-ndrn applies to any added timer: a debounce that fires after the app stops must not paint into a screen that is gone.
- Add a regression test for the grow-back case specifically — shrink width, then grow, and assert the Title/card width actually increased, since the existing suite only proves the guard can be bypassed, not that growth is honored automatically.
