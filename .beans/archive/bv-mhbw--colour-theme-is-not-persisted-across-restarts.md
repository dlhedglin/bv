---
# bv-mhbw
title: Colour theme is not persisted across restarts
status: completed
type: bug
priority: normal
tags:
    - config
created_at: 2026-08-14T21:36:34Z
updated_at: 2026-08-14T22:05:00Z
---

Textual's command palette (`ctrl+p`) can switch between the 21 built-in themes
(`dracula`, `gruvbox`, `nord`, `catppuccin-*`, `tokyo-night`, ...), and the
change applies immediately. But `App.theme` is in-memory only — bv never writes
it anywhere, so the next launch reverts to the default.

Fix: persist the selection and restore it on mount.

- Watch for the change rather than polling. Textual exposes `theme` as a
  reactive, so a `watch_theme` method on the app fires on every switch,
  including ones made through the palette.
- Write to a normal user config location — `~/.config/bv/config.toml` or
  `$XDG_CONFIG_HOME` — not into the repo, and not into any `.beans` directory.
- Restore in `on_mount`, before the first paint, so there is no visible flash of
  the default theme.
- Validate on read. A config naming a theme that no longer exists must fall back
  to the default, not crash on startup.

This config file is the right home for other view state too — the collapsed-node
set and any active filter — so build it as a small general settings store rather
than a single theme string.

## Shipped

`bv/config.py`, a general settings store at `$XDG_CONFIG_HOME/bv/config.json`
(falling back to `~/.config/bv/`), JSON because stdlib `tomllib` only *reads*
TOML and writing it back would have meant a dependency.

Built as a schema rather than a theme string, which paid off immediately —
bv-emo7's collapsed-node set now lives in the same file, keyed by board root.
Unknown top-level keys round-trip through `Settings.extra`, so a config written
by a newer bv survives an older one.

`load_settings` never raises: missing, unreadable, undecodable, corrupt,
non-object, and wrong-typed all degrade to defaults, and a bad `theme` does not
cost you the rest of the file. `save_settings` writes via temp file + fsync +
`os.replace`, since the theme is written on every palette switch and a
half-written config would brick the next launch. It is the one call here that
can raise `OSError`; the app swallows that rather than dying over a preference.

The module never imports textual — validating that `"dracula"` is still a real
theme is the caller's job, and `_restore_theme` falls back to the default when
the stored name no longer resolves. 41 tests.

End-to-end: switch to gruvbox, restart, comes back gruvbox; a config naming a
theme that no longer exists falls back to `textual-dark`; a corrupt config still
starts.
