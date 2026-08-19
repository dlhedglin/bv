---
# bv-4jdr
title: Security scanning, and a badge for it
status: completed
type: task
priority: normal
tags:
    - docs
    - ci
    - security
created_at: 2026-08-17T17:52:05Z
updated_at: 2026-08-19T17:06:34Z
blocked_by:
    - bv-a4we
---

Nothing currently checks this project for known-vulnerable dependencies or for
the classes of bug a static scanner catches. The dependency surface is small --
textual and rich, plus their transitive tree -- but "small" is an argument for
the check being cheap, not for skipping it.

Blocked on bv-a4we, since the scan should run in CI rather than on my machine.

The badge is the smaller half and carries the same visibility caveat as bv-k9kq
and bv-l0zp; measured against this repo while private, shields.io renders
"repo or workflow not found" rather than nothing.

What to actually run, in the order they are worth having:

- **Dependency audit.** `uv-secure` or `pip-audit` against the locked resolution,
  failing the job on a known advisory. This is the one with real signal for a
  project whose own code touches no network and no credentials: the risk arrives
  through the lockfile.
- **Dependabot.** Config-only, no workflow, and it opens the update pull request
  rather than just reporting. Free on private repos for security updates.
- **CodeQL.** GitHub's own static analysis. Free on public repositories; on a
  private one it needs GitHub Advanced Security, which is paid. Verify against
  GitHub's current pricing page before planning on it -- this is exactly the
  detail that a year-old blog post gets wrong.

Check each against its primary source rather than a listicle before committing
to it. Half the "best Python security scanner" results are written by one of the
scanners they rank.

Out of scope: a secrets scanner. The history was already swept for credential
patterns across all 19 commits when the repo was briefly public and came back
clean, and the project handles no keys of its own -- so a recurring secrets scan
is guarding against a risk this codebase does not currently have. Reconsider if
that changes.
