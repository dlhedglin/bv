---
# bv-6t3w
title: Full code review before going public
status: completed
type: task
priority: normal
tags:
    - quality
    - security
    - refactor
created_at: 2026-08-18T00:00:00Z
updated_at: 2026-08-18T22:09:19Z
blocking:
    - bv-cyu8
---

Do a full code review of the source before the repo is published, using the
`code-review` Claude skill as the driver. This is a prerequisite for bv-cyu8:
publishing is effectively permanent, so the tree that goes out should be one that
has been read end to end at least once, not just the diffs that happened to pass
through review as they landed.

Scope is the whole package, not a single diff. Run the review broadly enough to
cover every source file rather than only the working-tree changes.

What to audit for:

- **Sensitive information.** Hardcoded secrets, tokens, keys, absolute local
  paths, personal identifiers, internal URLs, or anything that reads as
  private-context leaking into what will become public source. This overlaps the
  history sweep already called for in bv-cyu8 and bv-4jdr, but this pass is about
  the working tree as code a stranger will read, not the commit history as a
  place a credential could hide.
- **Code smells.** Dead code, commented-out blocks, long functions doing several
  jobs, unclear names, magic values, leftover debug output, TODOs that should
  either be beans or be gone.
- **Design pattern issues.** Misplaced responsibilities, leaky abstractions,
  state that should be local held globally, coupling that makes the module hard
  to reason about in isolation.
- **Repeating code.** Duplicated logic that wants a single home. Apply DRY where
  it genuinely reduces surface area, not where it only trades duplication for a
  worse abstraction.

Follow Clean Code Lite as the standard for the pass -- readability, small focused
units, honest names, no cleverness that a reader has to decode -- rather than a
heavier refactor mandate. The goal is source that is clean enough to publish and
maintain in the open, not a rewrite.

Out of scope: behavioural changes and new features. Findings that call for real
redesign should become their own beans rather than being folded into this pass.

---

**Review completed.** The whole package (12 files, ~4100 lines) was read end to
end. Findings were filed as their own beans and each has since been fixed:

- bv-0ejt -- `_summarize` counted archived beans it was hiding (fixed, tests)
- bv-ov50 -- Agent cell went stale on a same-bean state change (fixed, test)
- bv-avvq -- dead code in agents.py: unused Session fields and `summarize()` (removed)
- bv-n3yw -- watch.py used an absolute import where every sibling is relative (fixed)
- bv-9spt -- private project/machine names in docstrings, genericized before publishing

Dismissed after verification (not bugs): two "NUL byte truncates a subprocess
arg" reports (the id is prompt text, not argv, and Python raises on embedded NUL
rather than truncating), and a missing empty-rows guard in `action_goto_top`
(the cursor clamps to 0, same as the guarded `action_goto_bottom`). No hardcoded
secrets or credentials were found.
