---
# bv-57zz
title: Show which agent is working each bean
status: completed
type: feature
priority: high
tags:
    - ux
    - agents
created_at: 2026-08-17T03:31:53Z
updated_at: 2026-08-17T03:31:53Z
---

## Why

Five background Claude sessions are usually live across the portfolio, and the
board cannot say which bean any of them is on. `~/.claude/` already knows —
this is a join bv is uniquely placed to make, and the reason the README gives
for bv existing as a client rather than a fork of beans.

## The data, verified

`claude agents --json` is a supported, documented interface (`--all` for
finished sessions, `--cwd <path>` to scope). Measured on the real machine, 11
sessions, one row per session:

    {"id":"eeac094c","cwd":"~/projects","kind":"background",
     "sessionId":"eeac094c-…","name":"beans viewer","state":"working",
     "pid":52937,"status":"idle"}

`state` is one of working / blocked / done / failed / stopped. `name` is real
and usually human-set — the live ones are "beans viewer", "demo-a", "search
engine", "demo-b". Interactive sessions appear too, with `kind:
"interactive"` and no `id` or `state`, so both fields have to be treated as
optional despite the docs.

**This obsoletes the three-tier attribution scheme in the README** — exact via
`metadata.beanId`, inferred from transcripts, coarse via `cwd`. Only 4 of 44
task files carry `metadata.beanId`, and none of that machinery is needed.

## The one measurement that decides the design

    claude agents --json                     172 ms
    reading ~/.claude/jobs/*/state.json      0.26 ms
    the entire bean load                      21 ms

172 ms is eight times the whole board load, so it cannot sit in the 0.5 s
poll. The job files are ~660× faster and carry strictly more — `intent`,
`detail`, `tokens`, `name`, `nameSource`, `cwd`, `state`, `tempo` — and
`~/.claude/daemon/roster.json` adds live pids and which sessions the
supervisor still owns.

So: read the files on the existing poll, and treat `claude agents --json` as
the contract they are validated against, not as the hot path. The files are
internal format with no stability promise; a test should assert the two agree,
so a Claude Code upgrade that changes the layout fails loudly rather than
silently emptying the column.

## Matching a session to a bean

Two tiers, and only two:

- **Exact** — the bean id appears in the session `name`. This is free once bv
  spawns sessions itself, because bv sets `--name` (see the sibling bean).
- **Coarse** — the session `cwd` resolves inside a project, so every
  `in-progress` bean in that project *might* be the one. Shown dimmed and
  marked, never as fact. Resolve both paths before comparing: `demo-d` is a
  symlink into an iCloud vault, so a string compare misses it.

No third tier. Grepping transcripts to guess is how a board starts lying.

## Scope

- `bv/agents.py`, pure and Textual-free like `tree.py` — read the job files
  and the roster, expose sessions and the match.
- An `Agent` column, blank when nothing matches.
- Refreshed on the existing poll; no new timer.

## Not in scope

Locking a bean to an agent. beans has no assignee field — `assignee`,
`assignedTo`, `owner`, `agent`, `worker` and `claimedBy` were all probed and
all rejected by the schema — and #208 means a sidecar cannot live in
frontmatter. beads has `bd update <id> --claim` ("atomically claim a task,
sets assignee + in_progress"); beans structurally cannot. Tracked separately
if it ever matters.


## Shipped

`bv/agents.py`, pure and Textual-free like `tree.py`. Reads
`~/.claude/jobs/*/state.json` for names and states, and `daemon/roster.json`
for which of them the supervisor still owns.

**The roster matters more than expected.** A state file can say `working` for
a process that died without updating it, so believing the file alone paints a
ghost agent onto a bean forever. `is_busy` requires both a live roster entry
and a state in `working`/`blocked`. `blocked` counts as busy on purpose --
it means waiting on a human, which is exactly when you want to see who to go
unblock.

## The coarse tier was moved, not kept

The plan had two tiers on the bean row: exact by name, coarse by `cwd`. Built
that way, then looked at the real board: the coarse tier put **"Understand
plan mode" against three unrelated demo-b beans at once**, because a
research session happened to be `cwd`'d in that repo. Three beans all claiming
the same agent, none of them true.

A session's `cwd` says which repo it is in, never which bean. So coarse
matches moved to the **project heading**, which is the altitude at which they
are actually true, and which also gives the heading row's empty metadata
columns something to say -- DEMO-A now reads `2 agents`. Bean rows show
exact matches only.

That means the Agent column is empty on bean rows until bv dispatches sessions
itself (bv-9sxj), and that is the honest state: bv cannot know which bean an
externally-started agent is on, and guessing was measurably wrong.

## Contract, not just a read

`claude agents --json` is the documented interface and the job files are not,
so `tests/test_agents.py` runs the CLI and asserts every background session it
reports appears in the files with the same name. A Claude Code upgrade that
moves the layout fails a test instead of silently blanking the column. It
skips cleanly when `claude` is absent.

Why not just call the CLI: measured at **172 ms** against **0.26 ms** for the
files -- eight times a whole board reload, in a 0.5 s poll.

## Also

Sessions are re-read on the existing watch poll rather than a new timer, and
only repaint when the attribution actually moved -- an agent finishing is not
a write to `.beans`, so the bean watcher alone would never notice it.
