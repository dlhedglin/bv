---
# bv-4pli
title: Preview render makes navigation laggy
status: completed
type: bug
priority: high
tags:
    - ux
created_at: 2026-08-17T05:45:05Z
updated_at: 2026-08-17T06:17:08Z
---

## The symptom

With the preview open, `j`/`k` are not snappy. Holding a motion key feels like
the board is dragging.

## Measured

`BeanPreview.show()` to a settled frame, median of 6 alternating runs each, on
the real board:

    body     50 chars     79.5 ms   demo-a-x48e
    body   2499 chars     84.7 ms   demo-c-xe1b   (median bean)
    body   6964 chars    122.8 ms   demo-b-s7c5       (p90)
    body  23783 chars    156.3 ms   demo-b-j6nx       (largest)

Every cursor move pays that synchronously on the event loop. At the median
bean that is ~85 ms per keypress, which is squarely in the range a person
reads as lag.

## The important part: it is not the loading

Fit the numbers and it is roughly **76 ms fixed + ~3.2 ms per KiB**. A 50-char
body still costs 79.5 ms. So the expense is rebuilding the `Markdown` widget,
not fetching or parsing the text.

The body is already in memory — it arrives with the board, measured at +1.2 ms
across all 229 beans, and is exactly why fetching bodies lazily per row was
rejected in bv-ax9v. **There is nothing to lazy-load.** A bean whose body is
already a Python string is not the bottleneck.

So "lazy load the preview" as literally stated would not help. What is actually
needed:

## Debounce the render, and say so while it is pending

Do not render on every cursor move. Start a short timer on selection change,
reset it if the cursor moves again, and only render once the cursor has settled.
Navigation then costs nothing regardless of how fast the user scrolls, and the
preview catches up once they stop.

The spinner earns its place here: with a debounce, the pane is deliberately
stale for a moment, and a reader needs to know the difference between "still
rendering" and "this bean really is empty". Without the debounce a spinner
would just be a 85 ms flash — worse than nothing.

## Things to get right

- **The existing no-op guard must survive.** `show()` already returns early when
  the bean has not changed, which is what stops a fold or an auto-refresh from
  throwing away the reader's scroll position. A debounce must not re-render an
  unchanged bean when the timer fires.
- **Pick the interval from the numbers above, not from taste.** It has to be
  longer than a fast key repeat and shorter than a deliberate pause.
- **`ctrl+f`/`ctrl+b` must still scroll the pane** while a render is pending,
  or the spinner becomes a lock.
- Toggling the pane off with `p` should cancel any pending render rather than
  leave a timer pointing at a hidden widget.
- The teardown hazard from bv-ndrn applies: a timer that fires after the app
  stops must not paint into a screen that is gone.

## Worth checking while in there

Whether `Markdown.update()` on the existing widget is cheaper than whatever the
current path does. If most of the 76 ms fixed cost is remount rather than parse,
updating in place would cut the floor for everyone and make the debounce a
smaller win — measure before assuming.
