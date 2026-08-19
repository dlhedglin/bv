---
# bv-cyu8
title: Make the repo public
status: completed
type: epic
created_at: 2026-08-18T15:01:00Z
updated_at: 2026-08-19T20:38:28Z
blocking:
    - bv-l0zp
blocked_by:
    - bv-6t3w
---

Make the repository public.

This is a decision bean before it is a work bean. The repo is private today, and
three beans are waiting on the answer rather than on any code: bv-l0zp, bv-k9kq
and bv-4jdr all end in the same place, which is that a badge is a public
rendering of a private fact. Each has a workaround shaped around the repo
staying private -- a gist the badge reads instead of the repo, a graph token in
a Codecov URL -- and each of those workarounds is work that going public deletes
rather than completes. So the order matters: decide this, then build the badges
against whatever visibility is real.

Publishing is effectively permanent. A public repo is cloned, forked, proxied
and indexed within minutes, and flipping back to private removes this copy, not
the ones that left. Nothing under this epic should treat the flip as a step that
can be undone if it looks wrong afterwards.

What has to be true first:

- **A fresh sweep of the history for credentials.** One was already done across
  all 19 commits during the earlier brief public window and came back clean, and
  that result is recorded in bv-4jdr -- but it only covers the tree as it stood
  then, and the history has grown since. The sweep is cheap and its guarantee
  expires with every commit, so re-run it against the full history rather than
  the working tree.
- **The install instructions become true.** The README already documents
  `uv tool install git+https://github.com/dlhedglin/bv` and the `uvx --from`
  variant, and both only resolve today for someone holding access -- they are
  written for a reader who cannot yet follow them. Verify them from a shell with
  no GitHub credentials after the flip, which is the first moment the check
  means anything.
- **Licensing is already settled.** MIT landed in bv-2903, so there is no
  blocking work here. Noted so it is visibly checked rather than assumed.
- **Repo presentation at publish time.** Description, topics, and whether the
  Issues tab should be on at all given that the tracker is beans files in the
  tree. Small, but it is the whole of what a stranger sees first.

What going public unlocks, which is most of the reason to weigh it:

- shields.io and GitHub's native workflow badge both render, which closes the
  visibility caveat in all three badge beans instead of routing around it.
- CodeQL is free on public repositories; on a private one it needs GitHub
  Advanced Security, which is paid (bv-4jdr).
- Codecov's free tier stops being pinched -- unlimited uploads and users rather
  than one user and 250 private uploads a month, and no graph token in the badge
  URL.

Out of scope: publishing to PyPI, and any versioning or release process. Those
are about distributing the package, not about who can read the source, and
neither is a prerequisite for the other.
