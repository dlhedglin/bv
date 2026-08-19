"""Which Claude Code session is working which bean.

The join this module makes is the reason bv exists as a client rather than a
fork of beans: the answer lives entirely in `~/.claude/`, and nothing about it
is a beans concept.

Two sources, and the difference between them is the whole design:

`claude agents --json` is the documented interface, and it costs ~172 ms --
eight times a whole board reload, so it cannot sit in bv's 0.5 s poll.
`~/.claude/jobs/<short>/state.json` holds the same facts and more, and reading
every one of them costs ~0.26 ms. So the files are the hot path and the CLI is
the contract they are checked against; `tests/test_agents.py` asserts the two
still agree, so a Claude Code upgrade that moves the layout fails loudly
instead of quietly emptying the column.

Nothing here writes. Sessions are observed, never controlled.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# state.json calls it `state`; these are the values seen in the wild and in
# `claude agents --json`. Ordered live-first, the way the board reads.
STATE_ORDER = ("working", "blocked", "failed", "stopped", "done")
_STATE_RANK = {state: rank for rank, state in enumerate(STATE_ORDER)}

BUSY_STATES = frozenset({"working", "blocked"})
"""States where a session is still attached to its task. `done`, `failed` and
`stopped` sessions are history -- they are read so a finished agent can be
named, but they never claim a bean."""


def claude_home() -> Path:
	"""`~/.claude`, or `$CLAUDE_CONFIG_DIR` when it is set to an absolute path.

	Relative overrides are ignored rather than resolved against the working
	directory, which for bv is wherever the user happened to launch it.
	"""
	raw = os.environ.get("CLAUDE_CONFIG_DIR", "")
	candidate = Path(raw)
	if raw and candidate.is_absolute():
		return candidate
	return Path.home() / ".claude"


@dataclass(frozen=True)
class Session:
	"""One Claude Code session, as far as bv is concerned."""

	short: str
	name: str
	state: str
	cwd: str
	# True when the supervisor daemon still lists it in roster.json. A session
	# can be `working` in its own state file and absent from the roster if it
	# died without updating -- believing the file alone would show a ghost
	# agent working a bean forever.
	live: bool = False

	@property
	def state_rank(self) -> int:
		return _STATE_RANK.get(self.state, len(STATE_ORDER))

	@property
	def is_busy(self) -> bool:
		return self.live and self.state in BUSY_STATES


def _read_json(path: Path) -> dict | None:
	try:
		with path.open(encoding="utf-8") as handle:
			payload = json.load(handle)
	except (OSError, json.JSONDecodeError):
		# A session mid-write, a stale directory, a truncated file. The column
		# degrading to blank beats the board failing to paint.
		return None
	return payload if isinstance(payload, dict) else None


def _live_shorts(home: Path) -> set[str]:
	roster = _read_json(home / "daemon" / "roster.json") or {}
	workers = roster.get("workers")
	return set(workers) if isinstance(workers, dict) else set()


def load_sessions(home: Path | None = None) -> list[Session]:
	"""Every session bv can see, newest state first.

	Never raises. No Claude install, no jobs directory, or a home that is not
	readable all yield an empty list -- the Agent column is an enrichment, and
	it must not be able to take the board down.
	"""
	root = home or claude_home()
	try:
		entries = sorted((root / "jobs").iterdir())
	except OSError:
		return []

	live = _live_shorts(root)
	sessions: list[Session] = []
	for entry in entries:
		payload = _read_json(entry / "state.json")
		if payload is None:
			continue
		name = payload.get("name")
		cwd = payload.get("cwd")
		if not isinstance(name, str) or not isinstance(cwd, str):
			# Interactive sessions carry no `state` and sometimes no name;
			# without a name there is nothing to show in a column anyway.
			continue
		sessions.append(
			Session(
				short=entry.name,
				name=name,
				state=payload.get("state") or "",
				cwd=cwd,
				live=entry.name in live,
			)
		)
	sessions.sort(key=lambda s: (s.state_rank, s.name))
	return sessions


def resolved(path: str | Path) -> Path | None:
	"""Resolve symlinks, because a board root can be one into a synced folder.

	A string compare against `cwd` misses every session running there.
	"""
	try:
		return Path(path).resolve()
	except (OSError, RuntimeError):
		return None


def _within(child: Path, parent: Path) -> bool:
	return child == parent or parent in child.parents


def session_within(session: Session, root: Path) -> bool:
	"""Whether a session is running inside `root` (already resolved)."""
	cwd = resolved(session.cwd)
	return cwd is not None and _within(cwd, root)


@dataclass(frozen=True)
class Attribution:
	"""Who is on a bean, and how confidently."""

	session: Session
	exact: bool

	@property
	def label(self) -> str:
		return self.session.name


def attribute(
	sessions: Iterable[Session],
	bean_id: str,
	project_root: Path | None,
	*,
	in_progress: bool,
) -> Attribution | None:
	"""Best guess at which session is working this bean, or None.

	Exactly two tiers, and the gap between them is stated rather than blurred:

	**Exact** -- the bean id appears in the session name. Free for every
	session bv dispatches, because bv sets `--name` and puts the id in it.

	**Coarse** -- the session is running inside the bean's project and the
	bean is in progress. That is a *maybe*, and it tags every in-progress bean
	in that project with the same agent, so callers must render it as the
	guess it is.

	There is deliberately no third tier. Grepping session transcripts for a
	bean id would attribute on a passing mention, and a board that guesses
	wrong about who owns work is worse than one that says nothing.
	"""
	candidates = [s for s in sessions if s.is_busy]

	for session in candidates:
		if bean_id in session.name:
			return Attribution(session=session, exact=True)

	if not in_progress or project_root is None:
		return None
	root = resolved(project_root)
	if root is None:
		return None
	for session in candidates:
		cwd = resolved(session.cwd)
		if cwd is not None and _within(cwd, root):
			return Attribution(session=session, exact=False)
	return None


def attribute_all(
	sessions: Iterable[Session],
	beans: Iterable[tuple[str, Path | None, bool]],
) -> dict[str, Attribution]:
	"""`attribute` over a whole board, keyed by bean id.

	Takes `(bean_id, project_root, in_progress)` triples rather than Beans, so
	this module stays independent of the data layer.
	"""
	sessions = list(sessions)
	found: dict[str, Attribution] = {}
	for bean_id, root, in_progress in beans:
		hit = attribute(sessions, bean_id, root, in_progress=in_progress)
		if hit is not None:
			found[bean_id] = hit
	return found


def session_name_for(bean_id: str, title: str, limit: int = 60) -> str:
	"""The `--name` bv gives a session it dispatches for a bean.

	The id leads so `attribute` matches on it, and the title follows so the
	session is recognisable in `claude agents` -- where bv is not the only
	thing reading these names.
	"""
	prefix = f"{bean_id} · "
	room = max(0, limit - len(prefix))
	trimmed = title.strip()
	if len(trimmed) > room:
		trimmed = trimmed[: max(0, room - 1)].rstrip() + "…"
	return f"{prefix}{trimmed}" if trimmed else bean_id
