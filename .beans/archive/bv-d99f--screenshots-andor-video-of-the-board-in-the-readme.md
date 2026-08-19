---
# bv-d99f
title: Screenshots and/or video of the board in the README
status: completed
type: task
priority: normal
tags:
    - docs
created_at: 2026-08-19T17:05:29Z
updated_at: 2026-08-19T17:25:26Z
---

The README describes bv entirely in prose — a folding tree or kanban board, an agent cell showing which Claude Code session is on which bean, a scrollable preview pane — but never shows any of it. bv is a visual tool whose whole pitch is "a whole directory of repos on one screen," and that claim reads much stronger as a picture than as a sentence. Now that the repo is public (bv-cyu8), the README is the landing page for anyone arriving from the repo URL, so a visual near the top is worth more than any additional paragraph.

## What to capture

- The board itself with several repos loaded, so the "every repo at once" claim is visible rather than asserted.
- The tree/kanban fold in action.
- The agent cell showing which session is working which bean — that is the one view bv has that `beans tui` does not, so it should not be buried.
- The preview pane open on a bean.

## Format

- A still image (PNG) high in the README carries the first impression cheaply and renders everywhere GitHub does.
- A short screen recording (animated GIF or an MP4/webm GitHub can inline) is the honest way to show folding, navigation, and live agent-cell updates, since those are motion, not a frame. A GIF renders inline without a click; an MP4 uploaded to the repo/issue and referenced gets a player but is heavier. Prefer a GIF for the hero and keep it short.

## Things to get right

- Use a board with real-looking but non-sensitive content — no private repo names, paths, or agent session identifiers that should not be public.
- Keep the asset committed to the repo (or the badges branch) rather than hotlinked to something that can rot; the badges already live on a `badges` branch, so there is precedent for a place to park binary assets out of the main tree if size is a concern.
- Pin a terminal size that reads well in the README width; a too-wide capture shrinks to unreadable. This depends on the layout reflowing cleanly at a chosen size — related to the resize bean.
