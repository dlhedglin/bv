"""Tests for editing a bean's properties.

Nothing here mutates a real store. The pure layer (`bv.edit`) is runner-injected
like `bv.dispatch`, so every `run_edit` test passes a fake `subprocess.run`. The
app layer is exercised by stubbing the two screen helpers (`_choose`/`_prompt`)
so a field's value is chosen without a Textual harness, and by recording what
reaches `_apply` / `run_bean_edit` -- so a test proves the argv a field builds
without ever spawning `beans`.

The one thing that must never regress is the #208 guard: a bean carrying a
frontmatter key beans does not know must be refused before any `beans update`,
because that command rewrites the file and drops the key. It is verified both at
the pure level and end-to-end through `_apply`.
"""

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from textual.app import App

from bv.app import BeansViewer
from bv.beans import Bean
from bv.edit import (
	KNOWN_KEYS,
	EditResult,
	archive_argv,
	custom_frontmatter_keys,
	run_edit,
	update_argv,
)
from bv.editui import CLEAR, ChoiceScreen, PromptScreen

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def bean(
	id="bv-9sxj",
	*,
	project="bv",
	status="todo",
	type="feature",
	priority="normal",
	title="Edit the bean under the cursor",
	tags=("ui",),
	parent_id=None,
	blocked_by_ids=(),
	blocking_ids=(),
	path="bv-9sxj--edit-the-bean-under-the-cursor.md",
) -> Bean:
	return Bean(
		project=project,
		id=id,
		title=title,
		status=status,
		type=type,
		priority=priority,
		tags=tags,
		updated_at=T0,
		parent_id=parent_id,
		blocked_by_ids=blocked_by_ids,
		blocking_ids=blocking_ids,
		path=path,
	)


CLEAN_FRONTMATTER = """---
# bv-9sxj
title: Edit the bean under the cursor
status: todo
type: feature
priority: normal
tags:
    - ui
created_at: 2026-01-01T00:00:00Z
updated_at: 2026-01-01T00:00:00Z
parent: bv-clrs
blocked_by:
    - bv-abcd
---

## Why

Body text the guard must not mistake for a frontmatter key: status: not-a-key.
"""


class FakeRunner:
	"""Stands in for `subprocess.run`, and records what it was asked to do."""

	def __init__(self, returncode=0, stdout="", stderr="", raises=None):
		self.calls: list[tuple[list[str], dict]] = []
		self._result = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
		self._raises = raises

	def __call__(self, command, **kwargs):
		self.calls.append((list(command), kwargs))
		if self._raises is not None:
			raise self._raises
		return self._result

	@property
	def command(self) -> list[str]:
		(command, _), *_ = self.calls
		return command


# -- the #208 guard -------------------------------------------------------


def test_a_clean_bean_has_no_keys_to_lose(tmp_path):
	# Every key in a normal beans file is one beans itself writes, so editing it
	# drops nothing and the guard stays out of the way.
	file = tmp_path / "bean.md"
	file.write_text(CLEAN_FRONTMATTER, encoding="utf-8")
	assert custom_frontmatter_keys(file) == ()


def test_a_custom_key_is_flagged_as_a_loss(tmp_path):
	# The whole reason bv reads the file before writing: `beans update` would
	# rewrite it without this key. Verified against 0.4.2, where it does.
	file = tmp_path / "bean.md"
	file.write_text(CLEAN_FRONTMATTER.replace("status: todo\n", "status: todo\nassignee: me\n"), encoding="utf-8")
	assert custom_frontmatter_keys(file) == ("assignee",)


def test_the_id_comment_and_body_are_not_mistaken_for_keys(tmp_path):
	# The `# bv-9sxj` first line is a YAML comment, and the body below the
	# closing fence has a `status:`-looking line -- neither is a frontmatter key.
	file = tmp_path / "bean.md"
	file.write_text(CLEAN_FRONTMATTER, encoding="utf-8")
	keys = custom_frontmatter_keys(file)
	assert "bv-9sxj" not in keys and "not-a-key" not in keys


def test_list_items_under_a_key_are_not_keys(tmp_path):
	# `tags:` and `blocked_by:` are multi-line; their indented `- ...` items
	# must not be read as top-level keys.
	file = tmp_path / "bean.md"
	file.write_text(CLEAN_FRONTMATTER, encoding="utf-8")
	assert custom_frontmatter_keys(file) == ()


def test_a_missing_file_fails_open(tmp_path):
	# A bean that vanished between load and edit is not a reason bv invents a
	# block from a read failure; the update falls through and beans errors on it.
	assert custom_frontmatter_keys(tmp_path / "gone.md") == ()


def test_a_file_without_frontmatter_flags_nothing(tmp_path):
	file = tmp_path / "bean.md"
	file.write_text("no fences here\njust prose\n", encoding="utf-8")
	assert custom_frontmatter_keys(file) == ()


def test_every_field_beans_writes_is_known():
	# If beans grows a frontmatter key and KNOWN_KEYS does not, the guard starts
	# refusing every edit of every bean. These are the keys 0.4.2 emits.
	for key in ("title", "status", "type", "priority", "tags", "created_at", "updated_at", "parent", "blocked_by"):
		assert key in KNOWN_KEYS


# -- the commands ---------------------------------------------------------


def test_update_addresses_the_project_by_path():
	# Run from anywhere, `beans` resolves upward to whatever repo the process
	# sits in; `--beans-path` pins it to the bean's own project.
	argv = update_argv(Path("/repos/bv/.beans"), "bv-9sxj", "--status", "completed")
	assert argv == ("beans", "--beans-path", "/repos/bv/.beans", "update", "bv-9sxj", "--status", "completed")


def test_archive_is_a_pathed_sweep_with_no_id():
	# beans 0.4.2 has no per-bean archive: the command takes no id and moves the
	# whole project's finished beans.
	assert archive_argv(Path("/repos/bv/.beans")) == ("beans", "--beans-path", "/repos/bv/.beans", "archive")


# -- the runner -----------------------------------------------------------


def test_a_successful_write_reports_beans_own_line():
	runner = FakeRunner(stdout="Updated bv-9sxj bv-9sxj--edit.md\n")
	result = run_edit(update_argv(Path("/x/.beans"), "bv-9sxj", "--status", "todo"), runner)
	assert result == EditResult(True, "Updated bv-9sxj bv-9sxj--edit.md")


def test_a_rejected_write_carries_beans_first_error_line():
	runner = FakeRunner(returncode=1, stderr="Error: invalid status 'done'\nusage: …")
	result = run_edit(update_argv(Path("/x/.beans"), "bv-9sxj", "--status", "done"), runner)
	assert result.ok is False
	assert result.message == "Error: invalid status 'done'"


def test_a_silent_nonzero_exit_still_says_something():
	result = run_edit(archive_argv(Path("/x/.beans")), FakeRunner(returncode=3))
	assert result.ok is False and result.message == "exit 3"


def test_beans_missing_from_path_is_a_sentence_not_a_traceback():
	result = run_edit(archive_argv(Path("/x/.beans")), FakeRunner(raises=FileNotFoundError()))
	assert result.ok is False and "not found on PATH" in result.message


def test_a_wedged_beans_gives_up_instead_of_hanging():
	timeout = subprocess.TimeoutExpired(cmd="beans", timeout=30.0)
	result = run_edit(archive_argv(Path("/x/.beans")), FakeRunner(raises=timeout))
	assert result.ok is False and "timed out" in result.message


# -- field -> flags, through the app --------------------------------------


def _field_flags(field, monkeypatch, *, choose=None, prompt=None, beans=None):
	"""Drive `_edit_field` for one field with the screen helpers stubbed, and
	return the `(label, flags)` it hands `_apply` -- or None if it bailed.

	`_choose`/`_prompt` are replaced with functions that immediately run the
	callback with a scripted value, so no Textual harness is needed and the test
	sees exactly the flags a real pick would produce.
	"""
	app = BeansViewer(root=Path("/repos/bv"))
	app._flat = True
	app._beans = beans if beans is not None else [subject()]
	captured: list[tuple[str, tuple[str, ...]]] = []
	monkeypatch.setattr(app, "_apply", lambda bean, label, flags: captured.append((label, flags)))
	monkeypatch.setattr(
		app, "_choose", lambda title, options, current, then: then(choose) if choose is not None else None
	)
	monkeypatch.setattr(app, "_prompt", lambda title, initial, then: then(prompt) if prompt is not None else None)
	monkeypatch.setattr(app, "notify", lambda *a, **k: None)
	app._edit_field(subject(beans), field)
	return captured[0] if captured else None


def subject(beans=None) -> Bean:
	# The bean the menu is opened on. When a relational test supplies its own
	# board, the subject is its first entry so ids line up.
	if beans:
		return beans[0]
	return bean(parent_id="bv-clrs", blocked_by_ids=("bv-abcd",), blocking_ids=("bv-ef01",))


def test_status_builds_a_status_flag(monkeypatch):
	assert _field_flags("status", monkeypatch, choose="completed") == ("status → completed", ("--status", "completed"))


def test_priority_builds_a_priority_flag(monkeypatch):
	assert _field_flags("priority", monkeypatch, choose="high") == ("priority → high", ("--priority", "high"))


def test_clearing_priority_sends_an_empty_value(monkeypatch):
	# beans clears a priority with an empty --priority; the CLEAR sentinel keeps
	# that out of the visible option ids.
	assert _field_flags("priority", monkeypatch, choose=CLEAR) == ("priority cleared", ("--priority", ""))


def test_type_builds_a_type_flag(monkeypatch):
	assert _field_flags("type", monkeypatch, choose="bug") == ("type → bug", ("--type", "bug"))


def test_title_builds_a_title_flag(monkeypatch):
	assert _field_flags("title", monkeypatch, prompt="A clearer title") == (
		"title updated",
		("--title", "A clearer title"),
	)


def test_adding_a_tag_builds_a_tag_flag(monkeypatch):
	assert _field_flags("tag_add", monkeypatch, prompt="urgent") == ("tag +urgent", ("--tag", "urgent"))


def test_removing_a_tag_builds_a_remove_tag_flag(monkeypatch):
	assert _field_flags("tag_remove", monkeypatch, choose="ui") == ("tag -ui", ("--remove-tag", "ui"))


def test_removing_a_parent_needs_no_pick(monkeypatch):
	# The only field with no picker: there is one parent, so removing it is a
	# single flag with nothing to choose.
	assert _field_flags("parent_remove", monkeypatch) == ("parent removed", ("--remove-parent",))


def test_setting_a_parent_builds_a_parent_flag(monkeypatch):
	board = [subject(), bean(id="bv-1111", title="A candidate parent")]
	assert _field_flags("parent_set", monkeypatch, choose="bv-1111", beans=board) == (
		"parent → bv-1111",
		("--parent", "bv-1111"),
	)


def test_adding_a_blocker_builds_a_blocked_by_flag(monkeypatch):
	board = [subject(), bean(id="bv-2222", title="The blocker")]
	assert _field_flags("blocked_by_add", monkeypatch, choose="bv-2222", beans=board) == (
		"blocked by bv-2222",
		("--blocked-by", "bv-2222"),
	)


def test_removing_a_blocker_builds_a_remove_blocked_by_flag(monkeypatch):
	assert _field_flags("blocked_by_remove", monkeypatch, choose="bv-abcd") == (
		"unblocked from bv-abcd",
		("--remove-blocked-by", "bv-abcd"),
	)


def test_marking_a_bean_blocking_builds_a_blocking_flag(monkeypatch):
	board = [subject(), bean(id="bv-3333", title="The blocked one")]
	assert _field_flags("blocking_add", monkeypatch, choose="bv-3333", beans=board) == (
		"blocking bv-3333",
		("--blocking", "bv-3333"),
	)


def test_a_relational_add_with_no_candidates_bails_without_applying(monkeypatch):
	# A one-bean project has nothing to point a parent or blocker at, so the
	# field notifies and never reaches `_apply`.
	assert _field_flags("parent_set", monkeypatch, choose="whatever", beans=[bean()]) is None


# -- the guard, end to end through _apply ---------------------------------


def test_apply_refuses_a_bean_that_would_lose_a_key(tmp_path, monkeypatch):
	# The safety-critical path: a custom frontmatter key present, so `_apply`
	# must refuse and never call `run_bean_edit`.
	beans_dir = tmp_path / ".beans"
	beans_dir.mkdir()
	subject_bean = bean(path="bv-9sxj--x.md")
	(beans_dir / subject_bean.path).write_text(
		CLEAN_FRONTMATTER.replace("status: todo\n", "status: todo\nassignee: me\n"), encoding="utf-8"
	)

	app = BeansViewer(root=tmp_path)
	app._flat = True
	ran: list = []
	messages: list[str] = []
	monkeypatch.setattr(app, "run_bean_edit", lambda argv, msg: ran.append((argv, msg)))
	monkeypatch.setattr(app, "notify", lambda message, **k: messages.append(message))

	app._apply(subject_bean, "status → completed", ("--status", "completed"))

	assert ran == [], "a bean with a custom key must not be written"
	assert messages and "assignee" in messages[0] and "#208" in messages[0]


def test_apply_writes_a_clean_bean(tmp_path, monkeypatch):
	beans_dir = tmp_path / ".beans"
	beans_dir.mkdir()
	subject_bean = bean(path="bv-9sxj--x.md")
	(beans_dir / subject_bean.path).write_text(CLEAN_FRONTMATTER, encoding="utf-8")

	app = BeansViewer(root=tmp_path)
	app._flat = True
	ran: list = []
	monkeypatch.setattr(app, "run_bean_edit", lambda argv, msg: ran.append((argv, msg)))
	monkeypatch.setattr(app, "notify", lambda *a, **k: None)

	app._apply(subject_bean, "status → completed", ("--status", "completed"))

	assert ran == [(update_argv(beans_dir, "bv-9sxj", "--status", "completed"), "bv-9sxj: status → completed")]


# -- the screens ----------------------------------------------------------


class Host(App):
	def __init__(self) -> None:
		super().__init__()
		self.result: object = "never dismissed"

	def remember(self, result) -> None:
		self.result = result


def _drive(screen, keys):
	captured: list = []

	async def main() -> None:
		app = Host()
		async with app.run_test(size=(80, 24)) as pilot:
			app.push_screen(screen, app.remember)
			await pilot.pause()
			for key in keys:
				await pilot.press(key)
			await pilot.pause()
		captured.append(app.result)

	asyncio.run(main())
	return captured[0]


def test_a_choice_dismisses_with_the_chosen_id():
	screen = ChoiceScreen("pick", [("a", "Apple"), ("b", "Banana")])
	assert _drive(screen, ["down", "enter"]) == "b"


def test_a_choice_opens_on_the_current_value():
	screen = ChoiceScreen("pick", [("a", "Apple"), ("b", "Banana"), ("c", "Cherry")], current="c")
	assert _drive(screen, ["enter"]) == "c"


def test_escaping_a_choice_dismisses_none():
	screen = ChoiceScreen("pick", [("a", "Apple")])
	assert _drive(screen, ["escape"]) is None


def test_j_and_k_move_the_choice_highlight():
	# Vim motions over the list, mirroring the board's own j/k.
	screen = ChoiceScreen("pick", [("a", "Apple"), ("b", "Banana"), ("c", "Cherry")])
	assert _drive(screen, ["j", "j", "k", "enter"]) == "b"


def test_g_and_shift_g_jump_to_the_choice_ends():
	screen = ChoiceScreen("pick", [("a", "Apple"), ("b", "Banana"), ("c", "Cherry")])
	assert _drive(screen, ["G", "enter"]) == "c"
	screen = ChoiceScreen("pick", [("a", "Apple"), ("b", "Banana"), ("c", "Cherry")])
	assert _drive(screen, ["G", "g", "enter"]) == "a"


def test_a_prompt_dismisses_with_the_typed_text():
	screen = PromptScreen("title", initial="old")
	assert _drive(screen, ["backspace", "backspace", "backspace", "n", "e", "w", "enter"]) == "new"


def test_an_empty_prompt_dismisses_none():
	screen = PromptScreen("title", initial="")
	assert _drive(screen, ["enter"]) is None
