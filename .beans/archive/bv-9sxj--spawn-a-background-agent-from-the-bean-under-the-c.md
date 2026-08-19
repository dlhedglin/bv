---
# bv-9sxj
title: Spawn a background agent from the bean under the cursor
status: completed
type: feature
priority: normal
tags:
    - ux
    - agents
created_at: 2026-08-17T03:32:15Z
updated_at: 2026-08-17T03:32:15Z
blocked_by:
    - bv-57zz
---

## Why

Once the board can show which agent is on which bean, the natural next move is
to start one from the row you are already looking at, instead of copying a
title into another terminal.

It also closes the attribution loop: bv controls `--name` on the sessions it
starts, so it can put the bean id there and get an exact match back. Every
session bv spawns is attributable by construction. That is why this bean and
the Agent column are worth doing in that order.

## The interface, verified

    claude --bg --name "<name>" "<prompt>"

`--bg, --background` and `-n, --name` both confirmed present in
`claude --help` on 2.1.233. Companions: `claude attach <id>`,
`claude logs <id>`, `claude stop <id>`, `claude rm <id>`,
`claude respawn <id>`.

## Confirm before dispatch — decided, not assumed

A keypress that spends tokens and turns an agent loose on a real repo is not a
keypress to fire on a fat finger. `S` opens a confirmation showing the working
directory, the session name and the exact prompt; enter dispatches, escape
cancels.

    spawn a background agent?
    cwd:  ~/projects/bv
    name: bv-13sr · Project heading rows…
    prompt: Work bean bv-13sr: <title>
            <body>

    [enter] dispatch   [esc] cancel

The alternative — dispatch on a single key — was considered and rejected.
There is no undo beyond `claude stop`, and the cost of a wrong row is an agent
editing the wrong repo.

While writing the sibling bean, probing `claude --bg --name` in a shell
spawned a real idle session by accident. That is the exact failure this
confirmation exists to prevent, and it happened to someone who knew what the
flag did.

## Scope

- `S` on a bean row (not a project heading) opens the confirmation.
- Session name carries the bean id, so the Agent column resolves it exactly.
- `cwd` is the bean's project root, so the agent starts in the right repo.
- The prompt seeds from the bean's title and body.
- Dispatch is a subprocess and must not block the event loop — it is ~170 ms,
  the same order as `claude agents --json`.

## Open

Whether `--permission-mode` should be pinned rather than inherited. A
dispatched agent lands in whatever mode the daemon defaults to, which is worth
being deliberate about before this ships.

## Depends on

The Agent column. Without it, a spawned session vanishes from view the moment
it starts, which is worse than not spawning from bv at all.


## Shipped

`bv/dispatch.py` — a `ConfirmDispatch` modal plus a pure layer (`can_dispatch`,
`prompt_for`, `request_for`, `dispatch`) that decides everything *before* any
Textual is involved, so the command and its failure messages are testable
without standing up an app.

The screen dismisses with a request; it never runs anything. The app owns the
side effect because dispatch is ~170 ms of blocking subprocess and has to go
off the event loop.

**Nothing in the test suite goes near a real `claude --bg`.** The runner is
injectable, every test passes a fake, and one test sabotages
`subprocess.run`/`Popen` while driving the screen so an accidental spawn fails
loudly rather than silently costing tokens.

## Two failure modes found while building it

**A missing project root and a missing `claude` binary are indistinguishable
from outside `subprocess`** — both surface as `FileNotFoundError` — and they
want opposite answers from the user. The root is checked before the spawn.

**Everything in the dialog is a `rich.Text`, never a markup string.** Measured
on Textual 8.2.8: `Static("[broken]( and [bold]unclosed")` renders `( and
unclosed`, silently. A confirmation dialog showing a different prompt from the
one about to be dispatched is the worst bug this feature could have. There is
a test on it.

**The prompt pane's `max-height` is computed in Python, not CSS.** A constant
cap overflowed a short terminal: at 14 rows with a 23,783-char body the hint
line — the only thing naming the escape key — landed 15 rows below the screen,
and the dialog does not scroll. `height: 1fr` does nothing under an auto-height
parent.

No body truncation. ARG_MAX measured at 1,048,576 here; the largest real body
is ~2% of it.

## Integration

`S` on a bean row. A project heading declines with a notification rather than
opening anything. On success the Agent column refreshes immediately instead of
waiting up to half a second for the next poll — and because bv chose `--name`
via `agents.session_name_for`, the new session matches its bean **exactly**,
which is the whole reason bv-57zz came first.

## Still open

`--permission-mode` is not passed, so a dispatched agent inherits the daemon
default. Deliberately not decided here.
