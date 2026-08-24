---
# bv-9gnt
title: 'Agents view: project-scoped mission-control grid of live sessions'
status: in-progress
type: feature
priority: normal
tags:
    - ui
    - agents
created_at: 2026-08-21T17:25:26Z
updated_at: 2026-08-21T17:28:46Z
---

A project-level "mission control" screen: press a key on a project (or its
heading) and get an auto-tiled grid of panels, tmux/ghostty style, one panel
per active Claude session for that project — including its subagents.

## Why bv can do this cheaply

bv is already observe-only over `~/.claude/`. The data a live grid needs is
written by the Claude Code daemon in the same files bv reads today:

- `~/.claude/jobs/<short>/state.json` — bv already loads this in
  `agents.py:load_sessions`. Beyond the fields it uses (`name`, `cwd`,
  `state`) it also carries: `detail` (short status line), `tempo`
  (`idle`/active), `inFlight.tasks` (live subagent count), `tokens` (int),
  `output.result` (final result blurb), `children` (subagent tree), `intent`
  (the dispatched prompt).
- `~/.claude/jobs/<short>/timeline.jsonl` — append-only event stream, one JSON
  object per line: `{at, state, detail, text}`. `at` is ISO time, `state` is
  working/blocked/done/…, `detail` is the rolling status, `text` is the longer
  message/reply body. This is the tailable feed each panel renders.

Project scoping is free: bv already resolves each session's `cwd` and
attributes it to a project root (`agents.py:session_within` / `attribute`).
The grid filters to sessions whose `cwd` is within the selected project root.

## Scope (Tier 1 — chosen)

Native Textual grid of live rolled-up activity panels. NOT raw terminals.

- New key binding at project level opens a new `Screen` (modal/full-screen).
- Auto-tiled layout: compute rows/cols from panel count (tmux "tiled" style),
  Textual `Grid`. Empty slots left blank.
- One panel per active project session. Each panel tails its `timeline.jsonl`
  and reads `state.json`, showing: session name/bean, state (color-coded like
  the board — green working / yellow blocked), current `detail`, token count,
  elapsed, and the subagent tree from `children` / `inFlight.tasks`.
- Reuse the existing 0.5s poll (`app.py` `_poll_for_changes`) to refresh; no
  new process model, no writing, stays within bv's observe-only architecture.
- Upgrade-safe: consumes the same daemon files bv already depends on; a layout
  change fails the existing `tests/test_agents.py` contract loudly.

## Explicitly out of scope (Tier 2, later spike only)

Real interactive terminal panes via the daemon's per-worker `ptySock` +
`ptyAuth` (what Claude Code Remote Control uses). Rejected for now: it
reverse-engineers a private, undocumented daemon socket protocol, needs a
VT/ANSI emulator embedded in Textual, breaks on `cliVersion` bumps, and
duplicates Remote Control. Revisit only if watching rolled-up state proves
insufficient.

## Acceptance

- A key on a project opens the grid; panels appear for exactly the active
  sessions running under that project's root.
- Each panel shows live state + a rolling activity feed + subagent presence,
  refreshed on the existing poll.
- Layout auto-sizes to panel count and reflows on terminal resize.
- No regressions to the board/tree; sessions are still never controlled, only
  observed.
