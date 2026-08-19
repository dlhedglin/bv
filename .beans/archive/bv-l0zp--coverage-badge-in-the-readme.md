---
# bv-l0zp
title: Coverage badge in the README
status: completed
type: task
priority: normal
tags:
    - docs
    - ci
created_at: 2026-08-17T17:51:49Z
updated_at: 2026-08-19T17:06:34Z
blocked_by:
    - bv-a4we
    - bv-cyu8
---

A coverage percentage badge in the README. The number already exists -- `make
coverage` reports 87% across 1521 statements -- but it lives only in whoever ran
it last, so it drifts silently and nobody notices a drop.

Blocked on bv-a4we, and on the same visibility question as bv-k9kq: a private
repo makes shields.io render "repo or workflow not found" rather than nothing,
and third-party coverage services need a token to read a private project.

Two shapes, and the choice matters more here than for the build badge because
this one needs somewhere to *store* the number between runs:

- **A coverage service** (Codecov, Coveralls). Upload from CI, badge from the
  service, and the pull-request diff annotations come free. Costs a third party
  in the path and an upload token in repository secrets. Whether the free tier
  covers a private repo needs checking against the vendor's own pricing page
  rather than a blog post -- that detail moves, and search results for it are
  mostly the vendors ranking themselves.
- **A self-contained badge**: CI writes the percentage to a gist or an orphan
  branch, and shields.io's dynamic endpoint reads it. No account, no token
  beyond one with gist scope, and it keeps working the same way whatever the
  repo's visibility is -- the gist is a separate object with its own visibility.

The second is the smaller commitment and the one to reach for unless the diff
annotations are actually wanted.

Do not add a `fail_under` to `[tool.coverage.report]` as part of this. That was
left out deliberately when coverage was set up -- the baseline was unknown at
the time -- and picking a threshold belongs in its own bean where the number can
be argued about, not smuggled in beside a badge.
