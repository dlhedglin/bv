"""Persist bv's user settings to a JSON file under the XDG config directory.

This is deliberately a general settings store rather than a single theme
string: the collapsed-node set and the active filter belong here too, and
retro-fitting a schema onto a bare string later is more work than starting
with one.

JSON, not TOML, because the stdlib only *reads* TOML (`tomllib`) -- writing
it back would mean a new dependency for a file that holds three keys.

Two rules shape everything below:

* `load_settings` never raises. A config file is not user-facing, nobody
  hand-edits it, and a truncated or hand-mangled one must not stop bv from
  starting. Every failure -- missing, unreadable, corrupt, wrong shape,
  wrong value type -- degrades to defaults.
* `save_settings` writes atomically. The theme is written on every switch,
  including ones made from the command palette, so a crash mid-write is a
  real possibility; a half-written file would then brick the next launch.

Validation of the *meaning* of a value stays with the caller. This module
never imports textual, so it cannot know whether `"dracula"` is still a
real theme -- it hands back whatever string it stored, and the caller falls
back to its own default when the name no longer resolves.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

APP_NAME = "bv"
CONFIG_FILENAME = "config.json"


@dataclass(frozen=True)
class Settings:
	"""One user's stored preferences.

	`theme` is the name of a Textual theme, or None when the user has never
	chosen one. The name is stored verbatim and is *not* checked against the
	themes that exist -- Textual's theme list changes between releases, so
	the caller must treat an unknown name as "use the default".

	`extra` holds every top-level key we did not recognise, so a config
	written by a newer bv survives a round-trip through an older one instead
	of being silently truncated. It is exposed as a read-only mapping.

	Frozen, but not hashable: `extra` is a mapping. Use
	`dataclasses.replace(settings, theme=...)` to derive a changed copy.
	"""

	theme: str | None = None
	collapsed: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
	show_archived: bool = False
	extra: Mapping[str, Any] = field(default_factory=dict)

	def __post_init__(self) -> None:
		# Defend the immutability the frozen dataclass promises: without
		# this, a caller holding the original dict could still mutate it.
		object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))
		object.__setattr__(
			self,
			"collapsed",
			MappingProxyType({k: tuple(v) for k, v in self.collapsed.items()}),
		)


DEFAULTS = Settings()

# Keys this version understands. Anything else round-trips through `extra`.
_KNOWN_KEYS = frozenset({"theme", "collapsed", "show_archived"})


def config_dir() -> Path:
	"""The directory bv keeps its config in.

	`$XDG_CONFIG_HOME/bv`, falling back to `~/.config/bv`. Per the XDG base
	directory spec a relative `$XDG_CONFIG_HOME` is invalid and must be
	ignored, which also stops a stray relative value from scattering config
	files into whatever directory bv was launched from.
	"""
	raw = os.environ.get("XDG_CONFIG_HOME", "")
	base = Path(raw) if raw and Path(raw).is_absolute() else Path.home() / ".config"
	return base / APP_NAME


def config_path() -> Path:
	"""Full path to the config file, `<config_dir()>/config.json`."""
	return config_dir() / CONFIG_FILENAME


def _coerce_theme(value: Any) -> str | None:
	if not isinstance(value, str):
		return None
	name = value.strip()
	return name or None


def _coerce_collapsed(value: Any) -> dict[str, tuple[str, ...]]:
	"""Collapsed node keys per board root, discarding anything malformed.

	Shape is `{"<root path>": ["<node key>", ...]}`. The root is part of the
	key because bv can be pointed at different directories and a node key
	from one board means nothing on another.
	"""
	if not isinstance(value, dict):
		return {}
	boards: dict[str, tuple[str, ...]] = {}
	for root, keys in value.items():
		if not isinstance(root, str) or not isinstance(keys, list):
			continue
		boards[root] = tuple(k for k in keys if isinstance(k, str))
	return boards


def _from_mapping(payload: Mapping[str, Any]) -> Settings:
	return Settings(
		theme=_coerce_theme(payload.get("theme")),
		collapsed=_coerce_collapsed(payload.get("collapsed")),
		# Anything non-boolean means the file was hand-edited into a shape
		# bv does not understand; showing less is the safer reading.
		show_archived=payload.get("show_archived") is True,
		extra={k: v for k, v in payload.items() if k not in _KNOWN_KEYS},
	)


def load_settings(path: Path | None = None) -> Settings:
	"""Read settings from `path` (default: `config_path()`).

	Never raises. A missing file, an unreadable one, invalid JSON, a JSON
	document that is not an object, or a key holding the wrong type all
	yield defaults for whatever could not be understood -- a bad `theme`
	does not discard the rest of the file.
	"""
	target = path or config_path()

	try:
		raw = target.read_text(encoding="utf-8")
	except (OSError, ValueError):
		# Missing, a directory, no permission, undecodable bytes.
		return DEFAULTS

	try:
		payload = json.loads(raw)
	except (ValueError, RecursionError):
		return DEFAULTS

	# A list, a bare string, `null` -- anything but an object is not a
	# config we can read keys out of.
	if not isinstance(payload, dict):
		return DEFAULTS

	return _from_mapping(payload)


def _to_mapping(settings: Settings) -> dict[str, Any]:
	# Unknown keys first so the keys this version owns always win, even if a
	# future bv ever moved one of them.
	payload: dict[str, Any] = dict(settings.extra)
	if settings.theme is not None:
		payload["theme"] = settings.theme
	else:
		payload.pop("theme", None)
	if settings.collapsed:
		payload["collapsed"] = {root: sorted(keys) for root, keys in settings.collapsed.items()}
	else:
		payload.pop("collapsed", None)
	if settings.show_archived:
		payload["show_archived"] = True
	else:
		# False is the default; storing it just grows the file.
		payload.pop("show_archived", None)
	return payload


def save_settings(settings: Settings, path: Path | None = None) -> None:
	"""Write settings to `path` (default: `config_path()`), atomically.

	The payload goes to a temp file in the destination directory, is flushed
	to disk, and is then moved into place with `os.replace`, which is atomic
	on every platform bv runs on. A crash at any point leaves either the old
	file or the new one -- never a truncated one. Parent directories are
	created as needed.

	Unlike `load_settings`, this *can* raise `OSError` (read-only home, full
	disk). Callers that write on every theme switch should swallow it: a
	preference that failed to save is not worth taking the UI down for.
	"""
	target = path or config_path()
	target.parent.mkdir(parents=True, exist_ok=True)

	# Same directory as the target, because `os.replace` is only atomic
	# within a single filesystem.
	handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
	temp = Path(temp_name)
	try:
		with open(handle, "w", encoding="utf-8") as stream:
			json.dump(_to_mapping(settings), stream, indent=2, sort_keys=True)
			stream.write("\n")
			stream.flush()
			os.fsync(stream.fileno())
		os.replace(temp, target)
	except BaseException:
		temp.unlink(missing_ok=True)
		raise


def save_theme(name: str | None, path: Path | None = None) -> None:
	"""Store `name` as the theme, preserving every other stored setting.

	A read-modify-write, so this is the call to use from a `watch_theme`
	handler -- writing a bare `Settings(theme=...)` would drop any view
	state saved alongside it.
	"""
	target = path or config_path()
	save_settings(replace(load_settings(target), theme=name), target)


def _live_roots(boards: Mapping[str, tuple[str, ...]], keep: str) -> dict[str, tuple[str, ...]]:
	"""Drop fold state for board roots that are no longer directories.

	Fold state is keyed by board root, and the root is now wherever bv was run
	rather than one fixed path -- so without this the file gains a key per
	directory anyone ever folded in and never loses one. The entries are not
	small either: `C` on a 200-bean project stores 200 node keys under its
	root. Pruning here bounds the file by the number of roots that still
	exist rather than by the number that ever did.

	`keep` is never pruned. It is the root being written, and a board can
	legitimately be pointed at a directory that does not exist.

	A root on an unmounted volume reads as missing and loses its folds. That
	is a preference rather than data, and it costs one re-fold.
	"""
	live: dict[str, tuple[str, ...]] = {}
	for root, keys in boards.items():
		if root == keep:
			live[root] = keys
			continue
		try:
			if Path(root).is_dir():
				live[root] = keys
		except (OSError, ValueError):
			# Not a path this platform can even stat -- a hand-edited key, or
			# one written on another OS.
			continue
	return live


def save_collapsed(root: str, keys: Iterable[str], path: Path | None = None) -> None:
	"""Store the collapsed node keys for one board root, preserving the rest.

	Also a read-modify-write, for the same reason as `save_theme`: the two
	are written from different places at different times and must not
	clobber each other. Roots that have since disappeared are dropped on the
	way through -- see `_live_roots`.
	"""
	target = path or config_path()
	settings = load_settings(target)
	boards = _live_roots(settings.collapsed, root)
	collapsed = tuple(sorted(keys))
	if collapsed:
		boards[root] = collapsed
	else:
		# An empty set is the default; storing it just grows the file.
		boards.pop(root, None)
	save_settings(replace(settings, collapsed=boards), target)


def save_show_archived(show: bool, path: Path | None = None) -> None:
	"""Store whether archived beans are shown, preserving the rest.

	Read-modify-write, for the same reason as `save_theme`.
	"""
	target = path or config_path()
	save_settings(replace(load_settings(target), show_archived=show), target)
