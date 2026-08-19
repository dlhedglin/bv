"""Tests for the change-detection half of auto-refresh.

Everything runs against throwaway project trees under `tmp_path`. Nothing
here reads or writes real repos except the one explicitly read-only timing
check, which is skipped when the board it would measure is empty.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bv.app import resolve_root
from bv.beans import projects_under
from bv.watch import Watcher, fingerprint

BOARD_ROOT = resolve_root(None)
"""Whatever board a bare `bv` would show from here, resolved exactly as the
app resolves it rather than pinned to one machine's layout. Running the suite
from the repo measures bv's own `.beans`; running it from a directory of repos
measures all of them."""


def make_project(root: Path, name: str, files: dict[str, str]) -> Path:
	"""Create a fake beans project: `.beans.yml` plus a `.beans/` tree.

	`files` maps a path relative to `.beans/` (so `archive/x.md` works) to
	its contents.
	"""
	project = root / name
	(project / ".beans").mkdir(parents=True)
	(project / ".beans.yml").write_text(f"name: {name}\n")
	for relative, body in files.items():
		path = project / ".beans" / relative
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(body)
	return project


@pytest.fixture
def board(tmp_path: Path) -> Path:
	make_project(
		tmp_path,
		"demo-a",
		{
			"aaa--one.md": "one\n",
			"bbb--two.md": "two\n",
			"archive/ccc--done.md": "done\n",
		},
	)
	make_project(tmp_path, "demo-b", {"ddd--three.md": "three\n"})
	return tmp_path


class FakeClock:
	"""A monotonic clock the test moves by hand."""

	def __init__(self) -> None:
		self.now = 1000.0

	def __call__(self) -> float:
		return self.now

	def advance(self, seconds: float) -> None:
		self.now += seconds


# --- fingerprint -----------------------------------------------------------


def test_stable_when_nothing_changes(board: Path) -> None:
	assert fingerprint(board) == fingerprint(board)


def test_content_edit_changes_digest(board: Path) -> None:
	before = fingerprint(board)
	(board / "demo-a" / ".beans" / "aaa--one.md").write_text("edited\n")
	assert fingerprint(board) != before


def test_file_add_changes_digest(board: Path) -> None:
	before = fingerprint(board)
	(board / "demo-a" / ".beans" / "eee--new.md").write_text("new\n")
	assert fingerprint(board) != before


def test_file_delete_changes_digest(board: Path) -> None:
	before = fingerprint(board)
	(board / "demo-a" / ".beans" / "bbb--two.md").unlink()
	assert fingerprint(board) != before


def test_rename_changes_digest(board: Path) -> None:
	"""A title change is a delete plus a create with identical body bytes.

	Content alone would not move; the path has to be in the hash.
	"""
	beans_dir = board / "demo-a" / ".beans"
	before = fingerprint(board)
	(beans_dir / "aaa--one.md").rename(beans_dir / "aaa--one-renamed.md")
	assert fingerprint(board) != before


def test_archive_edit_is_detected(board: Path) -> None:
	"""The regression that matters: `.beans/archive/` is live data.

	A flat `glob("*.md")` passes every other test in this file and fails
	this one, silently missing a third of demo-a.
	"""
	before = fingerprint(board)
	(board / "demo-a" / ".beans" / "archive" / "ccc--done.md").write_text("x\n")
	assert fingerprint(board) != before


def test_archive_add_is_detected(board: Path) -> None:
	"""`beans archive` moving a bean is a delete plus a create in a subdir."""
	beans_dir = board / "demo-a" / ".beans"
	before = fingerprint(board)
	(beans_dir / "bbb--two.md").rename(beans_dir / "archive" / "bbb--two.md")
	assert fingerprint(board) != before


def test_deep_nesting_is_walked(board: Path) -> None:
	before = fingerprint(board)
	deep = board / "demo-a" / ".beans" / "archive" / "2025" / "q1"
	deep.mkdir(parents=True)
	(deep / "old.md").write_text("old\n")
	assert fingerprint(board) != before


def test_new_project_appears_without_restart(board: Path) -> None:
	before = fingerprint(board)
	make_project(board, "bv", {"fff--four.md": "four\n"})
	assert fingerprint(board) != before


def test_non_project_directory_is_ignored(board: Path) -> None:
	"""No `.beans.yml` means not a project, per `discover_projects`."""
	before = fingerprint(board)
	stray = board / "not-a-project" / ".beans"
	stray.mkdir(parents=True)
	(stray / "ghost.md").write_text("ghost\n")
	assert fingerprint(board) == before


def test_non_markdown_files_are_ignored(board: Path) -> None:
	before = fingerprint(board)
	(board / "demo-a" / ".beans" / "index.bleve").write_text("binary-ish")
	assert fingerprint(board) == before


def test_a_root_that_is_itself_a_project_is_watched(board: Path) -> None:
	"""bv run from inside a repo. Hashing only one level down would watch the
	repo's *subdirectories* and never notice its own beans changing -- an
	auto-refresh that silently never fires."""
	repo = board / "demo-a"
	before = fingerprint(repo)
	(repo / ".beans" / "aaa--one.md").write_text("edited\n")
	assert fingerprint(repo) != before


def test_empty_root_is_hashable(tmp_path: Path) -> None:
	assert isinstance(fingerprint(tmp_path), str)


def test_missing_root_does_not_raise(tmp_path: Path) -> None:
	assert isinstance(fingerprint(tmp_path / "nope"), str)


def test_file_vanishing_mid_walk_does_not_raise(board: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""The walk runs while other processes write; a race is the normal case."""
	doomed = board / "demo-a" / ".beans" / "bbb--two.md"
	real_read_bytes = Path.read_bytes

	def racy_read_bytes(self: Path) -> bytes:
		if self == doomed:
			doomed.unlink()  # deleted between the listing and the read
		return real_read_bytes(self)

	monkeypatch.setattr(Path, "read_bytes", racy_read_bytes)
	assert isinstance(fingerprint(board), str)
	assert not doomed.exists()


def test_unreadable_entry_does_not_raise(board: Path) -> None:
	"""A dangling symlink is what a half-finished move looks like."""
	(board / "demo-a" / ".beans" / "broken.md").symlink_to(board / "gone.md")
	assert isinstance(fingerprint(board), str)


# --- Watcher ---------------------------------------------------------------


def test_watcher_quiet_when_nothing_changes(board: Path) -> None:
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	clock.advance(10.0)
	assert watcher.poll() is False


def test_watcher_debounces_then_reports(board: Path) -> None:
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	beans_dir = board / "demo-a" / ".beans"

	(beans_dir / "aaa--one.md").write_text("mid-write\n")
	assert watcher.poll() is False  # first sighting never reports
	assert watcher.pending is True

	clock.advance(0.2)
	assert watcher.poll() is False  # still inside the quiet period

	clock.advance(0.3)
	assert watcher.poll() is True  # settled
	assert watcher.pending is False


def test_watcher_reports_once_per_change(board: Path) -> None:
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	(board / "demo-a" / ".beans" / "aaa--one.md").write_text("edited\n")

	watcher.poll()
	clock.advance(1.0)
	assert watcher.poll() is True
	clock.advance(1.0)
	assert watcher.poll() is False


def test_watcher_restarts_timer_while_digest_moves(board: Path) -> None:
	"""A `beans update` is a delete plus a create; don't reload in between."""
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	beans_dir = board / "demo-a" / ".beans"

	for step in range(5):
		(beans_dir / f"tmp-{step}.md").write_text(f"step {step}\n")
		clock.advance(0.3)  # never quiet for the full period
		assert watcher.poll() is False

	clock.advance(0.5)
	assert watcher.poll() is True


def test_watcher_ignores_write_then_revert(board: Path) -> None:
	"""Back to the original bytes is not a change, however it got there."""
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	target = board / "demo-a" / ".beans" / "aaa--one.md"

	target.write_text("scratch\n")
	assert watcher.poll() is False
	target.write_text("one\n")
	clock.advance(1.0)
	assert watcher.poll() is False
	assert watcher.pending is False


def test_watcher_detects_archive_change(board: Path) -> None:
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	(board / "demo-a" / ".beans" / "archive" / "ccc--done.md").write_text("z\n")
	watcher.poll()
	clock.advance(1.0)
	assert watcher.poll() is True


def test_watcher_reset_swallows_pending_change(board: Path) -> None:
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	(board / "demo-a" / ".beans" / "aaa--one.md").write_text("edited\n")
	watcher.poll()

	watcher.reset()
	clock.advance(1.0)
	assert watcher.poll() is False


def test_watcher_start_is_not_a_change(board: Path) -> None:
	clock = FakeClock()
	watcher = Watcher(board, quiet_period=0.4, clock=clock)
	assert watcher.digest == fingerprint(board)


def test_watcher_uses_monotonic_by_default(board: Path) -> None:
	watcher = Watcher(board)
	assert watcher._clock is time.monotonic


# --- real-board timing (read-only) -----------------------------------------


@pytest.mark.skipif(not projects_under(BOARD_ROOT), reason="no beans projects here")
def test_real_board_fingerprint_is_fast() -> None:
	"""Guards the 3.21 ms benchmark the bean's no-mtime argument rests on."""
	fingerprint(BOARD_ROOT)  # warm the page cache
	start = time.perf_counter()
	for _ in range(5):
		fingerprint(BOARD_ROOT)
	elapsed_ms = (time.perf_counter() - start) / 5 * 1000
	print(f"\nfingerprint({BOARD_ROOT}) = {elapsed_ms:.2f} ms")
	assert elapsed_ms < 100
