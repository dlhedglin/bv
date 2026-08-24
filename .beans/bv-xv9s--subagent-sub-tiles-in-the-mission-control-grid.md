---
# bv-xv9s
title: Subagent sub-tiles in the mission-control grid
status: completed
type: task
priority: normal
tags:
    - ui
    - agents
created_at: 2026-08-21T18:55:23Z
updated_at: 2026-08-21T19:01:49Z
parent: bv-9gnt
---

Break each in-process subagent (Task/local_agent) of a session into its own
nested tile inside the parent panel of the mission-control grid.

## Data source (researched)

Durable, in the tree bv already reads (verified on Claude Code v2.1.238):

    ~/.claude/projects/<projhash>/<sessionId>/subagents/agent-<agentId>.jsonl

One JSONL per subagent, `isSidechain:true`, full user/assistant/tool
messages. Map: `session.short` -> `sessionId` (from state.json; add
`session_id` to `Session`) -> glob
`~/.claude/projects/*/<sessionId>/subagents/agent-*.jsonl` (glob by sessionId
to dodge the cwd-hash directory encoding).

Chosen over: the volatile `/tmp/.../tasks/*.output` copies (undocumented),
and `--forward-subagent-text` (launch-only, and bv observes *existing*
background sessions). `SubagentStart`/`SubagentStop` hooks are the
official-stable alternative but need a settings.json install and only catch
sessions started after; keep as a later optional upgrade.

## Caveat / robustness

Official docs mark this JSONL format internal ("may change between
releases"). Parse defensively and degrade to the existing "N subagents"
count line (from state.json `inFlight.tasks`) when the dir is absent or
unparseable -- the same layout-drift robustness agents.py already practices
and its CLI-agreement test guards.

## Build

- agents.py: `session_id` on `Session` (read from state.json); `Subagent`
  dataclass + `load_subagents(session_id, home, tail)` reading each
  `agent-*.jsonl` into {id, kind, last events/text}.
- mission.py: `AgentPanel` gains a nested `Grid` of `SubagentCell` tiles;
  reconcile like the parent grid (rebuild on id-set change, update in place
  otherwise). Fallback to the count line.
- tests: `load_subagents` parsing + a screen test that a session with
  subagent files renders nested tiles.

## Prior art (research)

The TUI niche is nearly empty -- only `tail-claude` does subagent
drill-down. Web/desktop dashboards (Codeman, claude-view, agents-observe)
solved it; all read `~/.claude/projects` subagent jsonl or hooks. A tiled
subagent fleet in a TUI is a green field.
