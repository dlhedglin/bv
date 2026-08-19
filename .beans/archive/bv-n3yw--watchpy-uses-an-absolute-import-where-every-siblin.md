---
# bv-n3yw
title: watch.py uses an absolute import where every sibling is relative
status: completed
type: task
priority: low
tags:
    - quality
created_at: 2026-08-18T20:27:36Z
updated_at: 2026-08-18T20:35:49Z
---

`watch.py:43` imports its sibling as an absolute package path:

    from bv.beans import BeansError, projects_under

Every other module in the package imports siblings relatively -- `.beans`,
`.board`, `.agents`, and so on. watch.py alone hardcodes the top-level package
name `bv`.

Once the repo is public and others vendor, re-root, or import the package under a
different name, watch.py breaks while the rest keeps working. Inconsistent and
needlessly fragile.

Fix: `from .beans import BeansError, projects_under`.

Found in the pre-publication review (bv-6t3w).
