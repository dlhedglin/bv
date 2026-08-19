---
# bv-ndrn
title: Filtering on the board leaves focus on the hidden table
status: completed
type: bug
priority: high
tags:
    - ux
created_at: 2026-08-17T04:59:24Z
updated_at: 2026-08-17T04:59:24Z
---

## Reproduce

1. `b` to show the board.
2. `/`, type anything, `enter`.
3. `h` / `j` / `k` / `l` do nothing. The board is unreachable without a mouse.

`escape` to clear the filter leaves it in the same state.

## Cause, confirmed

Both filter exits hand the keyboard back to the table by name:

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        # Keep the filter, hand the keyboard back so motions work again.
        self.query_one(DataTable).focus()

    def action_clear_filter(self) -> None:
        ...
        self.query_one(DataTable).focus()

That comment was true when the table was the only view. The table is still
*mounted* while the board shows — deliberately, because nearly every action in
`app.py` reaches for it with a bare `query_one` and removing it would raise
`NoMatches` — but it is hidden. So focus goes to a widget that is not on
screen, and every keypress after that is swallowed by something invisible.

Instrumented, on the board, after `/test` + `enter`:

    focus is DataTable (table hidden=True)
    board navigation after filter+enter: moved=False

Nothing is broken or corrupted; the keyboard is simply pointed at the wrong
widget. Focus reaches the board again by pressing `b` twice.

## Why the existing tests missed it

`pilot_board` filters *and* checks navigation, but never in that order — it
filters, presses `escape`, and then only asserts the view toggles back. The
filter path and the navigation path were each covered, and the seam between
them was not.

## Fix

The two `query_one(DataTable).focus()` calls must focus whichever view is
active. `self._board` already tracks that. This is the same class of bug as
`_sync_preview` writing over the board's selection — an app-level handler that
still assumes one view — so it is worth a look for any other bare
`query_one(DataTable)` that means "the thing the user is looking at" rather
than "the table".

Related, and deliberately separate: `bv-te9w` covers the tree-only keys still
firing on the hidden table while the board shows. That one is cosmetic; this
one leaves the user stuck.


## Shipped

`on_input_submitted` and `action_clear_filter` both called
`query_one(DataTable).focus()` by name. They now go through
`_focus_active_view()`, which asks `self._board` which view is on screen. The
board toggle uses the same helper rather than focusing a widget directly, so
there is one place that answers "what is the user looking at".

Audited the other twelve `query_one(DataTable)` calls in `app.py`: every one of
them genuinely means the table -- cursor position, row count, page height -- and
only these two meant "the focused view". No other instance of the bug.

## A second bug, found while fixing the first

Running the archive pilot repeatedly surfaced an intermittent
`NoMatches: No nodes match 'BeanPreview'`, about one run in three. A
`RowHighlighted` still fires while the table is being torn down, so
`_sync_preview` ran against a screen whose widgets were already gone -- a
traceback on the way out of a clean session.

Guarding on `App.is_running` was not enough; the event still arrives with the
app nominally running. `_preview()` now returns `BeanPreview | None` via a
query that is allowed to come back empty, which is the honest shape for
something that outlives its widget. `_render` and `_poll_for_changes` also bail
when the app has stopped. Eight consecutive clean runs after, from one-in-three
before.

## Regression cover

`tests/test_app.py` is new -- the first tests of the app shell itself, since
the two views only exist together there. It covers both filter exits on the
board, the tree's original behaviour (which the fix must not trade away), the
table staying mounted-but-hidden, and the tree-only keys not raising.

Verified they actually catch it: with the fix stashed, exactly the two
board-focus tests fail with `focus went to DataTable, not the board`, and the
three covering unbroken behaviour still pass.
