---
# bv-2903
title: MIT license, so the code is legally usable
status: completed
type: task
priority: high
tags:
    - packaging
created_at: 2026-08-17T17:41:12Z
updated_at: 2026-08-17T17:45:40Z
---

The repo has no LICENSE file. Without one the default is all rights reserved:
anyone who clones it has no grant to use, modify or redistribute the code, which
makes "share it with others" legally empty regardless of how easy the install is.

MIT, matching `beans` itself, and the shortest permissive licence in common use.

- `LICENSE` at the repo root, standard MIT text, copyright the project author.
- `license = "MIT"` and `license-files = ["LICENSE"]` in `[project]`, the PEP 639
  form, so the SPDX expression and the file both land in wheel metadata rather
  than only sitting in the tree. Confirm with `uv build` and an actual read of
  the wheel's METADATA rather than assuming hatchling picked it up.
