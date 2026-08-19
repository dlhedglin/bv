---
# bv-scx8
title: Watch bean files and auto-refresh
status: completed
type: feature
priority: high
tags:
    - ux
    - live
created_at: 2026-08-14T21:38:15Z
updated_at: 2026-08-14T22:05:00Z
---

Right now the board is a snapshot — it only changes when you press `r`. With
Claude sessions writing beans in the background across four repos, whatever is
on screen is stale within seconds and there is no way to tell. Watch the bean
files and refresh automatically.

## What to watch

Each project's `.beans/` directory, plus the root itself so a newly
`beans init`'d project appears without a restart. (bv's own project was created
mid-session and would have needed a restart to show up.)

Walk it **recursively**. `beans archive` moves completed and scrapped beans
into `.beans/archive/`, and GraphQL still returns them — demo-a today has 39
beans at the top level and 33 more in `archive/`. A non-recursive `*.md` glob
would silently miss every archive write, including the moment `beans archive`
runs and a third of the project moves.

## Fingerprint by content hash, not mtime

Hash the file contents. Walk every `.beans/**/*.md` in sorted order, feed path
and bytes into one `blake2b`, and compare the resulting digest to the previous
tick. Different digest means reload; identical digest means the data is
genuinely unchanged.

The reason not to use mtime is that it answers a different question — "was this
file written" rather than "is the content different" — and it gets that wrong
in both directions:

- **False positives.** A `git checkout` or branch switch rewrites mtimes with
  no content change. `demo-d` is a symlink into an iCloud vault, where sync
  rewrites timestamps on its own schedule and can move them *backwards* — so a
  `max(mtime)` fingerprint compared with `>` would miss a real edit outright.
  (If mtime is used at all, compare fingerprints with `!=`, never `>`.)
- **False negatives.** Any writer that preserves or restores mtime is invisible.

A content hash has neither failure mode, and it is the same thing beans itself
does — `Bean.etag` in the GraphQL schema is a content hash for concurrency
control.

Measured on the real board, all 222 bean files, 705 KiB:

| step | cost |
| --- | --- |
| directory walk alone | 0.82 ms |
| walk + `stat` each file | 1.04 ms |
| walk + read + `blake2b` | 3.21 ms |

So hashing every byte costs 2.2 ms more than stat-ing, and at 1 Hz that is
0.3% of one core. Set against the ~100 ms reload it exists to avoid, the
optimisation of stat-first-hash-later is not worth the second code path — just
hash unconditionally. Revisit only if the file count grows by an order of
magnitude, and re-measure rather than guessing.

## How

`set_interval` driving the hash on a worker thread, via `asyncio.to_thread` as
`load_all` already does, so the walk never blocks the event loop. Only a digest
change triggers `load_all`.

Reach for a real filesystem-event library only if polling proves inadequate.
`watchfiles` is the obvious candidate but is not currently installed and is not
a Textual dependency, so it is a genuine new dep — vet it properly at that
point rather than assuming.

Debounce. A `beans update` is not atomic from the outside, and a title change
is a delete plus a create; refreshing mid-write yields a torn view. Wait for a
quiet period (~300-500ms) after the digest stops moving before reloading.

## The part that makes or breaks it

Auto-refresh is actively hostile if it disturbs the view. A reload that fires
while you are reading must preserve:

- the cursor row (match by bean id, not row index — ids are stable, positions
  are not)
- scroll position
- the collapsed-node set once the tree lands (bv-emo7)
- any active filter or search
- preview pane scroll position if the highlighted bean did not change (bv-ax9v)

Refuse to refresh, or defer it, while the user is mid-interaction — typing in a
filter, for instance.

## Controls

- A key to toggle watching on and off.
- Show state in the subtitle: watching vs paused, and how long ago the data was
  loaded. A dashboard that silently stops updating is worse than one that never
  updated.
- Manual `r` keeps working and forces a reload regardless of fingerprint.
- Surface per-project failures without blanking the board — `load_all` already
  returns a problems list and isolates one broken repo, so a project that goes
  unreadable mid-session should degrade to a warning, not an empty table.

## Shipped

`bv/watch.py`: `fingerprint(root)` blake2b's path + bytes of every
`.beans/**/*.md` in sorted order, and `Watcher.poll()` reports a change only
once the digest has held still for 0.4s. Clock is injected so the debounce is
tested without sleeping. `bv/app.py` polls it every 0.5s on a worker thread.

The recursive walk has a dedicated regression test: swapping `rglob` for `glob`
fails exactly three tests and passes the other 22. `fingerprint` on the real
board measures 3.35ms against the 3.21ms predicted above, so no fast path was
added. 25 tests.

`w` pauses and resumes; resuming re-seeds the digest and reloads, so you come
back to current data rather than replaying what you missed. The subtitle carries
`· paused` whenever watching is off.

Verified end-to-end against a real temp beans project: an external
`beans create` appears without a keypress, an in-place status rewrite is caught
(the case directory mtime would have missed), a write under `.beans/archive/`
moves the fingerprint, and nothing refreshes while paused.

**Deferred, both blocked on unbuilt beans rather than on this one:** preserving
preview-pane scroll needs the preview (bv-ax9v), and refusing to refresh while
the user is typing needs a filter to type into (bv-q2kp). Cursor row, and the
collapsed set from bv-emo7, are already preserved across an auto-refresh.
