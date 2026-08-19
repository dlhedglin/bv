"""Detect when bean files change on disk, so the board can refresh itself.

This module is pure and synchronous: it walks files, hashes bytes, and
answers one question -- "has the data changed and stopped changing?" It
knows nothing about Textual and starts no threads or timers of its own.
The caller owns the clock.

Two decisions here are load-bearing, and both are easy to undo by accident:

**The walk is recursive.** `beans archive` moves completed and scrapped
beans into `.beans/archive/`, and they remain live data -- GraphQL still
returns them, so the board still shows them. A project can carry dozens of
beans at the top level and dozens more under `archive/`. A flat `glob("*.md")`
would be blind to a large fraction of that project, and blind to the exact moment
`beans archive` runs and a third of it moves. Hence `rglob`.

**The fingerprint is a content hash, not an mtime.** mtime answers "was
this file written", which is a different question and wrong in both
directions. False positives: a `git checkout` or branch switch rewrites
mtimes with no content change, and a board root can be a symlink into a
synced folder (iCloud, Dropbox) where sync rewrites timestamps on its own
schedule -- sometimes
*backwards*, which would defeat a `max(mtime)` fingerprint compared with
`>`. False negatives: any writer that preserves or restores mtime is
invisible. A content hash has neither failure mode, and it matches what
beans itself does (`Bean.etag` is a content hash used for CAS).

Hashing every byte was measured against stat-ing every byte on the real
board (222 files, 705 KiB): 3.21 ms to walk+read+hash versus 1.04 ms to
walk+stat. The 2.2 ms difference at 1 Hz is 0.3% of one core, against a
~100 ms reload it exists to avoid, so a stat-first-hash-later fast path
buys a second code path for nothing. Deliberately not implemented.
Revisit only if the file count grows by an order of magnitude, and
re-measure rather than guessing.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

from .beans import BeansError, projects_under

# Long enough to sit out a `beans update`, which is not atomic from the
# outside -- a title change is a delete plus a create, and reloading between
# the two yields a torn view. Short enough that a settled edit still feels
# immediate.
DEFAULT_QUIET_PERIOD = 0.4

# Only these are bean data. Anything else beans drops in `.beans/` (indexes,
# lockfiles, config) churns on read and would make the digest never settle.
BEAN_SUFFIX = ".md"


def fingerprint(root: Path) -> str:
	"""Hash every bean file under `root` into one digest.

	Discovery goes through `beans.projects_under` so that "what counts as a
	project" -- and whether the root is one itself -- has exactly one
	definition; the root listing is part of the hash input by construction,
	which means a newly `beans init`'d project shifts the digest and appears
	without a restart.

	Paths are fed into the hash alongside the bytes. Content alone would
	miss a pure rename -- `beans update` on a title is a delete plus a
	create, and the two files can have identical bodies.

	The walk tolerates its own raciness on purpose: this runs while Claude
	sessions are writing beans, so a file can vanish between the listing and
	the read. That is not an error, it is the normal case, and it resolves
	itself on the next tick.
	"""
	digest = hashlib.blake2b()

	try:
		projects = projects_under(root)
	except BeansError:
		# An unreadable root is a stable state, not a change. Report it as a
		# constant digest and let the caller's real load surface the error.
		return "unreadable"

	for project in projects:
		try:
			paths = sorted(project.beans_dir.rglob(f"*{BEAN_SUFFIX}"))
		except OSError:
			# Project directory disappeared or turned unreadable mid-walk.
			continue

		for path in paths:
			try:
				data = path.read_bytes()
			except (OSError, ValueError):
				# Deleted, replaced by a directory, or a broken symlink
				# between the listing and this read.
				continue
			# Length-prefixing the path keeps the stream unambiguous: without
			# it, a rename could shuffle bytes between the path field and the
			# content field and land on the same digest.
			encoded = str(path).encode("utf-8", "surrogateescape")
			digest.update(len(encoded).to_bytes(8, "big"))
			digest.update(encoded)
			digest.update(len(data).to_bytes(8, "big"))
			digest.update(data)

	return digest.hexdigest()


class Watcher:
	"""Track the bean-file digest and report *settled* changes.

	Reporting on the first difference would refresh mid-write. Instead the
	watcher latches a pending digest and only reports once that digest has
	held still for `quiet_period` seconds -- so a `beans update`, which
	touches disk several times, produces one report at the end rather than
	one per write.

	The clock is injected so tests can drive it, and so the module never
	sleeps: `poll` returns immediately and the caller decides the tick rate.
	"""

	def __init__(
		self,
		root: Path,
		quiet_period: float = DEFAULT_QUIET_PERIOD,
		clock: Callable[[], float] = time.monotonic,
	) -> None:
		self.root = root
		self.quiet_period = quiet_period
		self._clock = clock
		# Seed from the current state so that starting the watcher is not
		# itself reported as a change.
		self._settled = fingerprint(root)
		self._pending: str | None = None
		self._pending_since = 0.0

	@property
	def digest(self) -> str:
		"""The last digest reported as settled."""
		return self._settled

	@property
	def pending(self) -> bool:
		"""True while a change has been seen but has not yet gone quiet."""
		return self._pending is not None

	def poll(self) -> bool:
		"""Re-hash and return True exactly once per settled change.

		Returns False while the digest is still moving, so the caller can
		tick as fast as it likes without ever reloading a torn view.
		"""
		current = fingerprint(self.root)
		now = self._clock()

		if current == self._settled:
			# Whatever was in flight ended up back where it started -- a
			# write-then-revert, or a temp file that came and went. Nothing
			# to reload.
			self._pending = None
			return False

		if current != self._pending:
			# Still moving. Restart the quiet timer against the new state.
			self._pending = current
			self._pending_since = now
			return False

		if now - self._pending_since < self.quiet_period:
			return False

		self._settled = current
		self._pending = None
		return True

	def reset(self) -> None:
		"""Adopt the current on-disk state without reporting a change.

		For a manual reload (`r`), which reads the files itself and should
		not leave a change queued up behind it.
		"""
		self._settled = fingerprint(self.root)
		self._pending = None
