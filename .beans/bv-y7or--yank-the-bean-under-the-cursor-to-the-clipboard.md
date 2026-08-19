---
# bv-y7or
title: Yank the bean under the cursor to the clipboard
status: completed
type: feature
priority: normal
tags:
    - ux
    - keybindings
created_at: 2026-08-17T05:46:12Z
updated_at: 2026-08-17T06:10:23Z
---

## Why

Getting a bean id out of bv currently means reading it off the screen and
typing it somewhere else. The id is the join key for everything — `beans show`,
a commit message, a prompt to an agent, a message to a person — so the one
thing the board is best placed to hand over is the one thing it does not.

`y` is free, and so is `Y`. Nothing in `app.py` or `board.py` binds either, so
this does not have to displace anything.

## What to copy

Two levels, matching vim's habit of pairing a small and a large yank:

- `y` — the id alone, `bv-4pli`. This is what gets pasted into a command.
- `Y` — a line a human can read: id, title, and probably status. This is what
  gets pasted into a message.

Worth deciding rather than assuming: whether `Y` should be one line or a small
block, and whether it should carry the project. The tree already groups by
project so the id's prefix is redundant on screen — but the moment it leaves
bv, `bv-4pli` is all the context there is, so the prefix is doing real work in
a paste and should stay.

## The hazard, verified

Textual 8.2.8 has `App.copy_to_clipboard(text)`, and its own docstring says:

> This does not work on macOS Terminal, but will work on most other terminals.

It works by emitting OSC 52, which the terminal may or may not honour — and
when it does not, **nothing happens and nothing reports it**. A yank key that
silently does nothing is worse than no yank key, because the user only finds
out at the paste.

`/usr/bin/pbcopy` exists on this machine and is not subject to terminal
support. So: use `pbcopy` where it is available, fall back to
`copy_to_clipboard` elsewhere, and notify what was copied either way so the
keypress always has visible feedback.

Do not shell out on the event loop — dispatch measured ~170 ms for a
subprocess and the same rule applies here, though `pbcopy` should be far
cheaper. Measure it rather than assuming.

## Also

- Must work on both views. On the tree it yanks the row under the cursor; on
  the board, the selected card. A project heading has no bean and should
  decline rather than copy an empty string.
- The board binds its own keys, so `y` needs to reach the app from both.
