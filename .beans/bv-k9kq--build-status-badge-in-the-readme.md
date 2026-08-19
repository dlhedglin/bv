---
# bv-k9kq
title: Build status badge in the README
status: todo
type: task
priority: normal
tags:
    - docs
    - ci
created_at: 2026-08-17T17:51:35Z
updated_at: 2026-08-18T22:24:08Z
blocked_by:
    - bv-cyu8
---

A build badge at the top of the README, so the state of `make check` on main is
visible without opening the Actions tab.

Blocked on bv-a4we: a badge renders a workflow result and there is no workflow
yet.

Also gated on the repo's visibility, which is the part worth deciding before any
of this is written. Measured against the repo as it stands today, private:

- shields.io returns a rendered badge reading **"build: repo or workflow not
  found"**. It does not fail quietly or return nothing -- it draws a broken
  badge into the README. Same URL shape against a public repo (astral-sh/uv)
  returns "build: failing" correctly, so the difference is access, not the URL.
- GitHub's own badge, `/actions/workflows/<file>.yml/badge.svg`, returns 404
  unauthenticated.

The native badge is documented to render for viewers who have repo access, which
would make it the right choice for a private repo -- but that is the one claim
here I could not test, since testing it needs an authenticated render of the
README. Confirm it before writing it in; if it also renders broken, the honest
options are to leave the badge out while the repo is private, or to make the
repo public, which is not a call to make as a side effect of adding a badge.

Prefer GitHub's native badge over shields.io either way. It needs no third party
in the path, and shields.io is the one that demonstrably renders a broken state
here.
