---
# bv-9spt
title: Genericize private project and machine names in docstrings before going public
status: completed
type: task
priority: normal
tags:
    - security
    - quality
created_at: 2026-08-18T20:27:36Z
updated_at: 2026-08-18T20:37:36Z
---

Several docstrings use the author's real private project names and machine layout
as illustrative examples. No secret or credential, but publishing the repo leaks
the author's portfolio composition and home-directory structure to every reader.

Sites (from the pre-publication review, bv-6t3w):

- board.py:5 -- "spread across demo-d 6, demo-a 5, demo-c 4 and demo-b 3"
- watch.py:12 -- "demo-a today has 39 beans"
- watch.py:20 -- "demo-d is a symlink into an iCloud vault"
- agents.py:135 -- "demo-d is one into an iCloud vault"
- app.py:373 -- "third of demo-a rendered as completed history"
- app.py:800 -- "three unrelated demo-b beans at once"

`dispatch.py:169` (`/Users/.../projects/bv`) is already a genericized placeholder
and is fine.

Fix: replace the real names with generic stand-ins (e.g. "project-a", "a synced
folder such as iCloud or Dropbox") while keeping the illustrative point. Behaviour
unchanged; docstrings only.
