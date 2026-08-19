"""Tests for bv.config.

The contract worth defending here is negative: `load_settings` must survive
every broken file we can think of, and `save_settings` must never leave a
half-written one behind.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from bv.config import (
	DEFAULTS,
	Settings,
	config_dir,
	config_path,
	load_settings,
	save_collapsed,
	save_settings,
	save_show_archived,
	save_theme,
)


def test_collapsed_round_trips_per_root(cfg, tmp_path):
	# Real directories, because a root that no longer exists is pruned on the
	# next write -- see the growth tests below.
	a, b = tmp_path / "a", tmp_path / "b"
	a.mkdir()
	b.mkdir()
	save_collapsed(str(a), ["demo-a", "bv"], cfg)
	save_collapsed(str(b), ["demo-b"], cfg)
	loaded = load_settings(cfg)
	# Sorted on write so the file does not churn between saves.
	assert loaded.collapsed == {str(a): ("bv", "demo-a"), str(b): ("demo-b",)}


def test_collapsed_and_theme_do_not_clobber_each_other(cfg):
	save_theme("nord", cfg)
	save_collapsed("/a", ["bv"], cfg)
	assert load_settings(cfg).theme == "nord"
	save_theme("dracula", cfg)
	assert load_settings(cfg).collapsed == {"/a": ("bv",)}


def test_empty_collapsed_removes_the_root_rather_than_storing_it(cfg):
	save_collapsed("/a", ["bv"], cfg)
	save_collapsed("/a", [], cfg)
	assert load_settings(cfg).collapsed == {}
	assert "collapsed" not in json.loads(cfg.read_text())


def test_malformed_collapsed_degrades_instead_of_raising(cfg):
	cfg.parent.mkdir(parents=True, exist_ok=True)
	for bad in ["not-a-dict", ["a"], {"/a": "not-a-list"}, {"/a": [1, 2]}, 7]:
		cfg.write_text(json.dumps({"theme": "nord", "collapsed": bad}))
		loaded = load_settings(cfg)
		# A bad collapsed block must not cost you the theme as well.
		assert loaded.theme == "nord"
		assert all(isinstance(v, tuple) for v in loaded.collapsed.values())


# --- the file must not grow without bound ---------------------------------
#
# The board root is now the working directory, so a user who runs bv in many
# repos accumulates a fold-state key per repo -- and `C` on a 200-bean project
# stores 200 node keys under it. Bounded by the roots that still exist.


def test_fold_state_for_a_vanished_root_is_dropped(cfg, tmp_path):
	gone, here = tmp_path / "gone", tmp_path / "here"
	gone.mkdir()
	here.mkdir()
	save_collapsed(str(gone), ["bv"], cfg)
	gone.rmdir()

	save_collapsed(str(here), ["demo-a"], cfg)
	assert load_settings(cfg).collapsed == {str(here): ("demo-a",)}


def test_the_root_being_written_is_never_pruned(cfg, tmp_path):
	# A board can legitimately be pointed at a directory that does not exist.
	missing = tmp_path / "missing"
	save_collapsed(str(missing), ["bv"], cfg)
	assert load_settings(cfg).collapsed == {str(missing): ("bv",)}


def test_a_root_that_is_not_even_a_path_is_dropped_not_raised(cfg, tmp_path):
	here = tmp_path / "here"
	here.mkdir()
	cfg.parent.mkdir(parents=True, exist_ok=True)
	# Hand-edited, or written on another OS: `is_dir` raises rather than
	# answering for an embedded NUL.
	cfg.write_text(json.dumps({"collapsed": {"nul\0byte": ["bv"]}}))

	save_collapsed(str(here), ["demo-a"], cfg)
	assert load_settings(cfg).collapsed == {str(here): ("demo-a",)}


def test_pruning_leaves_the_other_settings_alone(cfg, tmp_path):
	here = tmp_path / "here"
	here.mkdir()
	save_theme("nord", cfg)
	save_show_archived(True, cfg)
	save_collapsed(str(here), ["bv"], cfg)
	loaded = load_settings(cfg)
	assert loaded.theme == "nord"
	assert loaded.show_archived is True


def test_collapsed_is_not_mutable_through_the_dataclass(cfg):
	# Lists, not tuples, on purpose: `__post_init__` normalises whatever
	# sequence it is handed, so the annotation is wider than the field's.
	source: dict[str, Any] = {"/a": ["bv"]}
	settings = Settings(collapsed=source)
	source["/a"] = ["mutated"]
	assert settings.collapsed == {"/a": ("bv",)}
	with pytest.raises(TypeError):
		settings.collapsed["/a"] = ("also mutated",)  # ty: ignore[invalid-assignment]


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
	"""A config path inside tmp_path, in a directory that does not exist yet."""
	return tmp_path / "cfgroot" / "bv" / "config.json"


# --- path resolution -------------------------------------------------------


def test_xdg_config_home_is_honoured(tmp_path, monkeypatch):
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
	assert config_dir() == tmp_path / "xdg" / "bv"
	assert config_path() == tmp_path / "xdg" / "bv" / "config.json"


def test_falls_back_to_dot_config(tmp_path, monkeypatch):
	monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
	monkeypatch.setenv("HOME", str(tmp_path))
	monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
	assert config_path() == tmp_path / ".config" / "bv" / "config.json"


@pytest.mark.parametrize("value", ["", "relative/path"])
def test_unusable_xdg_value_is_ignored(tmp_path, monkeypatch, value):
	# Per the XDG spec a relative (or empty) value is invalid; honouring it
	# would drop config files into the launch directory.
	monkeypatch.setenv("XDG_CONFIG_HOME", value)
	monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
	assert config_path() == tmp_path / ".config" / "bv" / "config.json"


def test_default_path_is_used_when_none_given(tmp_path, monkeypatch):
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
	save_settings(Settings(theme="nord"))
	assert (tmp_path / "xdg" / "bv" / "config.json").is_file()
	assert load_settings().theme == "nord"


# --- round trip ------------------------------------------------------------


def test_round_trip(cfg):
	save_settings(Settings(theme="gruvbox"), cfg)
	assert load_settings(cfg).theme == "gruvbox"


def test_save_creates_parent_directories(cfg):
	assert not cfg.parent.exists()
	save_settings(Settings(theme="nord"), cfg)
	assert cfg.is_file()


def test_written_file_is_a_json_object(cfg):
	save_settings(Settings(theme="nord"), cfg)
	assert json.loads(cfg.read_text()) == {"theme": "nord"}


def test_unknown_keys_survive_a_round_trip(cfg):
	cfg.parent.mkdir(parents=True)
	# Keys only a *newer* bv would write must survive an older one.
	cfg.write_text(json.dumps({"theme": "nord", "kanban": ["wip"], "filter": "todo"}))

	loaded = load_settings(cfg)
	assert loaded.extra == {"kanban": ["wip"], "filter": "todo"}

	save_settings(replace(loaded, theme="dracula"), cfg)
	assert json.loads(cfg.read_text()) == {
		"theme": "dracula",
		"kanban": ["wip"],
		"filter": "todo",
	}


def test_none_theme_is_omitted(cfg):
	save_settings(Settings(theme=None, extra={"filter": "todo"}), cfg)
	assert json.loads(cfg.read_text()) == {"filter": "todo"}
	assert load_settings(cfg).theme is None


def test_save_theme_preserves_other_state(cfg):
	save_settings(
		Settings(theme="nord", collapsed={"/root": ("bv",)}, extra={"filter": "todo"}),
		cfg,
	)
	save_theme("tokyo-night", cfg)
	loaded = load_settings(cfg)
	assert loaded.theme == "tokyo-night"
	assert loaded.collapsed == {"/root": ("bv",)}
	assert loaded.extra == {"filter": "todo"}


def test_extra_is_not_mutable_through_the_dataclass(cfg):
	source = {"filter": ["todo"]}
	settings = Settings(theme="nord", extra=source)
	source["filter"] = ["mutated"]
	assert settings.extra == {"filter": ["todo"]}
	with pytest.raises(TypeError):
		settings.extra["filter"] = ["also mutated"]  # ty: ignore[invalid-assignment]


# --- load_settings never raises -------------------------------------------


def test_missing_file(cfg):
	assert load_settings(cfg) == DEFAULTS


def test_path_is_a_directory(tmp_path):
	assert load_settings(tmp_path) == DEFAULTS


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_file(cfg):
	cfg.parent.mkdir(parents=True)
	cfg.write_text('{"theme": "nord"}')
	cfg.chmod(0o000)
	try:
		assert load_settings(cfg) == DEFAULTS
	finally:
		cfg.chmod(0o600)


@pytest.mark.parametrize(
	"body",
	[
		'{"theme": "nord"',  # truncated mid-write
		"",  # zero-length, e.g. a crash before any bytes landed
		"not json at all",
		"{,}",
	],
)
def test_corrupt_json(cfg, body):
	cfg.parent.mkdir(parents=True)
	cfg.write_text(body)
	assert load_settings(cfg) == DEFAULTS


def test_undecodable_bytes(cfg):
	cfg.parent.mkdir(parents=True)
	cfg.write_bytes(b"\xff\xfe\x00garbage")
	assert load_settings(cfg) == DEFAULTS


@pytest.mark.parametrize("body", ["[1, 2, 3]", '"just a string"', "null", "42"])
def test_json_that_is_not_an_object(cfg, body):
	cfg.parent.mkdir(parents=True)
	cfg.write_text(body)
	assert load_settings(cfg) == DEFAULTS


@pytest.mark.parametrize("theme", ["123", "[]", "{}", "true", "null", '"   "', '""'])
def test_theme_of_the_wrong_type_or_blank(cfg, theme):
	cfg.parent.mkdir(parents=True)
	cfg.write_text(f'{{"theme": {theme}, "filter": "todo"}}')
	loaded = load_settings(cfg)
	assert loaded.theme is None
	# A bad theme must not discard the rest of the file.
	assert loaded.extra == {"filter": "todo"}


def test_deeply_nested_json_does_not_raise(cfg):
	cfg.parent.mkdir(parents=True)
	cfg.write_text("[" * 50_000 + "]" * 50_000)
	assert load_settings(cfg) == DEFAULTS


# --- atomicity -------------------------------------------------------------


def test_failed_write_leaves_the_old_config_intact(cfg, monkeypatch):
	save_settings(Settings(theme="nord"), cfg)

	def boom(*args, **kwargs):
		raise OSError("disk full")

	monkeypatch.setattr(os, "replace", boom)
	with pytest.raises(OSError):
		save_settings(Settings(theme="dracula"), cfg)

	assert load_settings(cfg).theme == "nord"
	assert json.loads(cfg.read_text()) == {"theme": "nord"}


def test_failed_write_leaves_no_temp_file_behind(cfg, monkeypatch):
	save_settings(Settings(theme="nord"), cfg)
	before = sorted(p.name for p in cfg.parent.iterdir())

	monkeypatch.setattr(json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError()))
	with pytest.raises(OSError):
		save_settings(Settings(theme="dracula"), cfg)

	assert sorted(p.name for p in cfg.parent.iterdir()) == before


def test_target_is_never_truncated_in_place(cfg, monkeypatch):
	"""The new bytes must land somewhere else until the rename."""
	save_settings(Settings(theme="nord"), cfg)
	real_replace = os.replace
	seen: dict[str, str] = {}

	def spy(src, dst, *args, **kwargs):
		# At the moment of the rename the target still holds the old config.
		seen["target"] = Path(dst).read_text()
		seen["source"] = str(src)
		return real_replace(src, dst, *args, **kwargs)

	monkeypatch.setattr(os, "replace", spy)
	save_settings(Settings(theme="dracula"), cfg)

	assert json.loads(seen["target"]) == {"theme": "nord"}
	assert Path(seen["source"]).parent == cfg.parent
	assert load_settings(cfg).theme == "dracula"


# --- the module stays free of textual -------------------------------------


def test_module_does_not_import_textual():
	import subprocess
	import sys

	proc = subprocess.run(
		[
			sys.executable,
			"-c",
			"import bv.config, sys; print('textual' in sys.modules)",
		],
		capture_output=True,
		text=True,
		check=True,
	)
	assert proc.stdout.strip() == "False"


def test_show_archived_round_trips(tmp_path):
	path = tmp_path / "config.json"
	save_show_archived(True, path)
	assert load_settings(path).show_archived is True
	save_show_archived(False, path)
	assert load_settings(path).show_archived is False


def test_show_archived_defaults_to_hiding(tmp_path):
	assert load_settings(tmp_path / "missing.json").show_archived is False


def test_a_non_boolean_show_archived_hides(tmp_path):
	# Hand-edited into a shape bv does not understand: showing less is safer
	# than showing a project's whole finished history unannounced.
	path = tmp_path / "config.json"
	path.write_text('{"show_archived": "yes"}')
	assert load_settings(path).show_archived is False


def test_false_show_archived_is_not_stored(tmp_path):
	# It is the default; writing it just grows the file.
	path = tmp_path / "config.json"
	save_show_archived(False, path)
	assert "show_archived" not in json.loads(path.read_text())


def test_show_archived_survives_a_theme_write(tmp_path):
	# The two are written from different places at different times.
	path = tmp_path / "config.json"
	save_show_archived(True, path)
	save_theme("gruvbox", path)
	settings = load_settings(path)
	assert settings.show_archived is True
	assert settings.theme == "gruvbox"
