---
# bv-rnfg
title: Security scan badge in the README
status: completed
type: task
priority: normal
tags:
    - docs
    - ci
    - security
created_at: 2026-08-18T15:00:53Z
updated_at: 2026-08-19T17:06:34Z
blocked_by:
    - bv-4jdr
---

A security-scan status badge at the top of the README, so the result of the
dependency/static scan on main is visible without opening the Actions tab.

Split out of bv-4jdr, which scopes the scan itself and names the badge as its
"smaller half". This bean is only the badge; it is blocked on bv-4jdr because
there is no scan result to render until that lands, and transitively on bv-a4we
for the CI workflow the badge reads.

Same visibility caveat as bv-k9kq and bv-l0zp: measured against this repo while
private, shields.io renders a "repo or workflow not found" broken badge rather
than nothing, and GitHub's native `/actions/workflows/<file>.yml/badge.svg`
returns 404 unauthenticated. Settle that question before writing the badge in,
exactly as bv-k9kq lays out -- do not make the repo public as a side effect of
adding a badge (see the "bv repo stays private" standing constraint).

Prefer GitHub's native workflow badge over shields.io once bv-4jdr has decided
which scanner runs and under what workflow filename, so the badge URL points at
a real workflow result.
