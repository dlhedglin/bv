---
# bv-4alh
title: Basic in-place bean editing (status, priority, type, title, tags, parent, blockers, archive)
status: completed
type: feature
priority: normal
tags:
    - ui
    - edit
created_at: 2026-08-26T17:47:14Z
updated_at: 2026-08-29T16:34:30Z
---

## Why

bv is read-only: it can view every bean but changes nothing. The one common
loop it can't close is the small edit — mark a bean `completed`, re-parent a
stray, add a blocker you just discovered. Today that means leaving bv for a
terminal and typing `beans update` by hand. bv already knows the bean, the
project path, and builds the exact `beans update` command string
(`dispatch.update_command`, `dispatch.py:390`) — it just never runs it.

bv was made read-only on purpose (`beans.py:1`, `dispatch.py:23`) because
beans 0.4.2 ships two unpatched write bugs. Both are still OPEN upstream and
0.4.2 is still the latest release (verified 2026-08-26):

- hmans/beans#208 — `beans update` rewrites the file and strips any
  frontmatter key outside beans' own schema. Reproduced on installed 0.4.2:
  a `custom_key` injected into a bean vanished after `beans update --status`.
- hmans/beans#205 — `--if-match` CAS silently loses one of two concurrent
  writes.

This bean opens a write path while keeping bv safe against both.

## Description

Add basic in-place editing of the bean under the cursor, driven by a key that
opens a picker (mirror `PickBase`, `dispatch.py:672`) or a single-line input
(mirror the filter `Input`, `app.py:304`). Each edit shells out one
`beans update <id> ...` (or `beans archive`) against the bean's
`--beans-path`, run in a `@work` thread like `run_dispatch` (`dispatch.py:724`),
then reloads (`load_beans`) so the change lands on the board.

Fields to support, all via `beans update` flags confirmed against
`beans update --help` on 0.4.2:

- **status** — `-s` (in-progress/todo/draft/completed/scrapped)
- **priority** — `-p` (critical/high/normal/low/deferred, empty clears)
- **type** — `-t` (milestone/epic/bug/feature/task)
- **title** — `--title` (single-line input)
- **tags** — `--tag` / `--remove-tag`
- **parent** — `--parent` / `--remove-parent` (pick from loaded beans)
- **blockers** — `--blocked-by` / `--remove-blocked-by`, and the
  `--blocking` / `--remove-blocking` mirror (pick from loaded beans)
- **archive** — the separate `beans archive` verb, natural pair with
  `completed`

Vocabularies for the pickers already exist: `beans.STATUS_ORDER` (`:50`),
`PRIORITY_ORDER` (`:68`), `app.TYPE_STYLES` (`:79`). Parent/blocker candidates
come from the loaded `self._beans` list.

### The #208 guard (load-bearing)

Before running any `beans update`, read the target `.md`
(`project.beans_dir / bean.path`), parse its frontmatter keys, and compare
against beans' known schema
(`id,title,status,type,priority,tags,parent,blocked_by,blocking,created_at,updated_at`).
If any key falls outside that set, **refuse the edit** and tell the user which
key would be lost and why (beans#208). bv's own beans and most users carry no
custom keys, so edits proceed normally; the guard only trips where a real edit
would silently destroy data. `archive` moves the file untouched, so it needs no
guard.

For #205: pass `--if-match` with the bean's etag as best-effort. Interactive
single-field edits are low-concurrency; document the residual risk rather than
block on an upstream fix that does not exist.

## Non-goals

- **No inline body editing.** The prose body is large; hand it to `$EDITOR` or
  a dispatched agent in a later bean, not an inline TUI widget.
- **No create / delete.** New-bean and delete flows are separate scope.
- **No multi-select / bulk edit.** One bean under the cursor at a time.
- **No new dependency-graph UI.** Blocker editing reuses the existing picker;
  it does not add a graph editor.
- **Do not touch the dispatch prompt path.** `update_command` stays the string
  bv hands agents; this bean adds a *separately executed* write, it does not
  rewire dispatch.
- **Do not lift the read-only stance for the fetch path.** `beans.py`'s query
  layer stays read-only; writes live in their own function.

## Tasks

- [x] Add a frontmatter-key guard: read the bean's `.md`, reject an edit that
      would drop a key outside beans' schema (beans#208), with a clear message
- [x] Add a write function mirroring `dispatch.update_command` that actually
      runs `beans update <id> ...` with `--if-match`, in a `@work` thread
- [x] Add an `archive` write calling `beans archive`
- [x] Wire an edit key + picker (`PickBase`) for status, priority, type
- [x] Wire parent + blocker pickers sourced from the loaded bean list
      (set + remove for parent, blocked-by, blocking)
- [x] Wire a single-line input for title, and add/remove for tags
- [x] Reload the board after each successful write; surface CLI errors the way
      dispatch failures are surfaced
- [x] Gate the edit key per view in `check_action` if needed
- [x] Update the README key table and the `beans.py`/`dispatch.py` read-only
      notes to record the new, guarded write path
- [x] Tests: guard trips on a custom key and passes without one; each field
      builds the right `beans update` argv (runner-injection pattern from
      `tests/test_dispatch.py`)

## Acceptance criteria

- With the cursor on a bean, the edit key changes status/priority/type/title/
  tags/parent/blockers and the board reflects it after reload.
- Archiving a bean moves it to the archive and the board hides it (or shows it
  under `a`).
- Editing a bean that carries a custom frontmatter key is refused with a
  message naming the key and beans#208 — the file is left untouched (verified
  by reading the file after the refused edit).
- A malformed edit (bad id, CLI nonzero exit) surfaces the CLI's first error
  line, same as a failed dispatch, and does not crash bv.
- `make check` passes.

## Notes

- 2026-08-26: beans 0.4.2 is still the latest release; #205 and #208 both OPEN
  upstream. #208 reproduced locally — injected `custom_key` stripped by
  `beans update --status`. This is why the guard, not just best-effort, is the
  chosen mitigation.
- `beans update` flags confirmed against `--help` on 0.4.2: `-s/-p/-t/--title/
  --tag/--remove-tag/--parent/--remove-parent/--blocked-by/--remove-blocked-by/
  --blocking/--remove-blocking/--if-match`.
- Scope decided with the maintainer: guard-and-ship (not version-gate), and all
  fields above including archive. Body editing and create/delete excluded.



## Summary of Changes (shipped 2026-08-26)

- New pure module `src/bv/edit.py`: `custom_frontmatter_keys` (#208 guard),
  `update_argv`/`archive_argv`, `run_edit` (runner-injected).
- New `src/bv/editui.py`: generic `ChoiceScreen` + `PromptScreen` modals.
- `app.py`: `e` binding, `action_edit` + field menu covering status, priority,
  type, title, tags (add/remove), parent (set/remove), blocked-by & blocking
  (add/remove), and a project-wide archive sweep; `_apply` runs the guard,
  `run_bean_edit` @work runner reloads on success.
- Decided: no `--if-match` -- matches `dispatch.update_command`'s reasoning that
  a bare update fails loudly where buggy #205 CAS would drop a write silently.
  (Overrides the bean's earlier best-effort note.)
- `beans archive` has no per-bean form; archive is a project sweep with a
  confirm showing the count.
- Docs: README key table + 'Editing a bean' section; read-only notes updated in
  beans.py and dispatch.py.
- 46 new tests in tests/test_edit.py; full `make check` green (417 passed).
