"""Read beans data by shelling out to the `beans` CLI's GraphQL API.

Everything in this module is read-only. beans 0.4.2 ships two unpatched
write bugs -- hmans/beans#205 (`--if-match` CAS silently loses one of two
concurrent writes) and #208 (`beans update` strips unknown frontmatter
keys) -- so bv never mutates a bean. It only queries.

Projects are addressed with `--beans-path` rather than by changing the
working directory, because `beans` otherwise searches upward for a
`.beans.yml` and would resolve to whatever repo the process happens to be
sitting in.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

# `body` is the largest field on the type, so it was measured before being
# added rather than after. Interleaved A/B on the real board (229 beans, 5
# projects, 12 paired runs of `load_all`): median 21.3 ms without `body`,
# 22.5 ms with it -- +1.2 ms for ~670 KiB of markdown. The load is dominated
# by five process spawns, not by payload size, which is why fetching bodies
# lazily for the highlighted row would cost a whole extra spawn (~20 ms) per
# cursor move to save one. Re-measure before changing this.
#
# `blockingIds` / `blockedByIds` ride along because they are plain `[String!]!`
# scalars on the same type -- the resolved `blocking`/`blockedBy` connections
# would be a nested query, but the id lists are not. Measured at +0.4 ms.
#
# `path` is the only way to tell an archived bean from a live one. There is no
# `archived` field on the type, and `beans archive` explicitly leaves archived
# beans "visible in all queries" -- so without the path, bv would show a
# project's whole finished history with nothing marking it as history.
QUERY = "{ beans { id title status type priority tags updatedAt parentId path body blockingIds blockedByIds } }"

ARCHIVE_DIR = "archive"
"""Subdirectory of `.beans` that `beans archive` moves finished beans into.
`path` is relative to the beans directory, so an archived bean's path starts
with this segment."""

# beans' own status vocabulary, ordered the way a human reads a backlog:
# live work first, finished work last.
STATUS_ORDER = ("in-progress", "todo", "draft", "completed", "scrapped")
_STATUS_RANK = {status: rank for rank, status in enumerate(STATUS_ORDER)}

# How a status is painted, wherever it is painted. Here rather than in a view
# module because both views show statuses and neither can import the other --
# `app.py` imports `board.py`, so the board cannot reach back, and the copy it
# kept instead was free to drift. Two definitions of one colour scheme is a
# theme change away from the tree and the board disagreeing about what
# `in-progress` looks like.
STATUS_STYLES = {
	"in-progress": "bold yellow",
	"todo": "cyan",
	"draft": "dim",
	"completed": "green",
	"scrapped": "dim red",
}

# Ordered most- to least-urgent, matching `beans update -p`.
PRIORITY_ORDER = ("critical", "high", "normal", "low", "deferred")
_PRIORITY_RANK = {priority: rank for rank, priority in enumerate(PRIORITY_ORDER)}

# Statuses that still hold up whatever depends on them.
UNFINISHED = frozenset({"in-progress", "todo", "draft"})

_EPOCH = datetime.fromtimestamp(0, tz=UTC)


class BeansError(RuntimeError):
	"""The `beans` CLI was missing, or failed on a particular project."""


@dataclass(frozen=True)
class Project:
	"""A single repo tracking work in beans."""

	name: str
	root: Path

	@property
	def beans_dir(self) -> Path:
		return self.root / ".beans"


@dataclass(frozen=True)
class Bean:
	project: str
	id: str
	title: str
	status: str
	type: str
	priority: str
	tags: tuple[str, ...]
	updated_at: datetime
	parent_id: str | None

	# Preview-pane fields. Declared last and defaulted so that code which only
	# cares about the row fields -- the tree, the table -- can build a Bean
	# without inventing them. Only ids, never titles: resolving a blocker's
	# title means a nested GraphQL selection, and the preview does not need it.
	body: str = ""
	blocking_ids: tuple[str, ...] = ()
	blocked_by_ids: tuple[str, ...] = ()

	# Relative to the project's `.beans` directory.
	path: str = ""

	# Filled by resolve_dependencies once the whole board is loaded, because
	# neither can be known from a single bean -- see that function.
	blocked_by_open: int = 0
	unblocks: int = 0

	@property
	def status_rank(self) -> int:
		return _STATUS_RANK.get(self.status, len(STATUS_ORDER))

	@property
	def is_archived(self) -> bool:
		"""Sitting in `.beans/archive/`.

		Compared on path segments rather than as a string prefix, so a bean
		named `archive-the-old-docs.md` at the top level is not mistaken for
		an archived one.
		"""
		return PurePosixPath(self.path).parts[:1] == (ARCHIVE_DIR,)

	@property
	def is_blocked(self) -> bool:
		"""Waiting on work that is not finished.

		A blocker that is already completed or scrapped is not holding
		anything up, so it does not count -- otherwise every bean whose
		dependency landed would read as blocked forever.
		"""
		return self.blocked_by_open > 0

	@property
	def is_ready(self) -> bool:
		"""Nothing in the way, and finishing it frees something else."""
		return self.unblocks > 0 and not self.is_blocked


def is_project(path: Path) -> bool:
	"""Whether `path` is itself a beans project.

	One definition of "a beans project", used by both the flat and the grouped
	path: a directory holding both a `.beans.yml` config and the `.beans` data
	directory that config points at. Two tests would let the two paths
	disagree -- a directory with `.beans` but no config would be a whole board
	one way and invisible the other.
	"""
	try:
		return (path / ".beans.yml").is_file() and (path / ".beans").is_dir()
	except OSError:
		# Unreadable, or a broken symlink -- not a beans project as far as we
		# are concerned.
		return False


def discover_projects(root: Path) -> list[Project]:
	"""Find every immediate subdirectory of `root` that is a beans project."""
	try:
		entries = sorted(root.iterdir())
	except OSError as exc:
		raise BeansError(f"cannot read {root}: {exc}") from exc

	return [Project(name=entry.name, root=entry) for entry in entries if is_project(entry)]


def projects_under(root: Path) -> list[Project]:
	"""Every project a board rooted at `root` shows.

	Two cases, and only two:

	* `root` is itself a beans project -- bv was run from inside a repo -- and
	  so *is* the board, alone. The caller shows it flat, with no project layer
	  at all; see `tree.build_forest`.
	* It is not, so it is a directory of repos and the projects are one level
	  down.

	One level, never a recursive walk. The root now defaults to wherever bv was
	run, which can be a home directory or hold a `node_modules`, and a
	recursive scan would stat its way through a very large tree before drawing
	anything.
	"""
	if is_project(root):
		return [Project(name=root.name, root=root)]
	return discover_projects(root)


def _parse_time(raw: str | None) -> datetime:
	if not raw:
		return _EPOCH
	try:
		# fromisoformat has handled a trailing "Z" since 3.11, which is the
		# floor in pyproject.toml.
		return datetime.fromisoformat(raw)
	except ValueError:
		return _EPOCH


def fetch_project_beans(project: Project, timeout: float = 30.0) -> list[Bean]:
	"""Query one project. Raises BeansError on anything that isn't clean data."""
	command = [
		"beans",
		"--beans-path",
		str(project.beans_dir),
		"graphql",
		"--json",
		QUERY,
	]

	try:
		# check=False on purpose: a nonzero exit is inspected below so the
		# message can name the project, rather than surfacing as CalledProcessError.
		proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
	except FileNotFoundError as exc:
		raise BeansError(
			"`beans` not found on PATH -- install it with `brew install --cask hmans/beans/beans`"
		) from exc
	except subprocess.TimeoutExpired as exc:
		raise BeansError(f"{project.name}: `beans` timed out after {timeout:g}s") from exc

	if proc.returncode != 0:
		detail = (proc.stderr or proc.stdout).strip().splitlines()
		first = detail[0] if detail else f"exit {proc.returncode}"
		raise BeansError(f"{project.name}: {first}")

	try:
		payload = json.loads(proc.stdout)
	except json.JSONDecodeError as exc:
		raise BeansError(f"{project.name}: unparseable GraphQL response") from exc

	# GraphQL reports failures in-band, with a 0 exit code.
	if errors := payload.get("errors"):
		message = errors[0].get("message", "unknown GraphQL error")
		raise BeansError(f"{project.name}: {message}")

	rows = (payload.get("data") or payload).get("beans") or []
	return [
		Bean(
			project=project.name,
			id=row["id"],
			title=row.get("title") or "",
			status=row.get("status") or "unknown",
			type=row.get("type") or "task",
			priority=row.get("priority") or "normal",
			tags=tuple(row.get("tags") or ()),
			updated_at=_parse_time(row.get("updatedAt")),
			parent_id=row.get("parentId"),
			body=row.get("body") or "",
			blocking_ids=tuple(row.get("blockingIds") or ()),
			blocked_by_ids=tuple(row.get("blockedByIds") or ()),
			path=row.get("path") or "",
		)
		for row in rows
	]


def dependency_edges(beans: Iterable[Bean]) -> set[tuple[str, str]]:
	"""Every `(blocker, blocked)` pair on the board, from both directions.

	beans stores a dependency on whichever side declared it and does *not*
	materialise the inverse: measured on the real board, `blockingIds`
	contributes 4 edges, `blockedByIds` contributes 16, and the two sets do
	not overlap at all. So reading either field alone sees a fraction of the
	graph -- a bean can be blocked without carrying a single entry in its own
	`blockedByIds`.

	Edges pointing at an id that is not loaded are kept. They cost nothing,
	and dropping them would quietly under-report blocking whenever a
	dependency crosses a project the caller did not ask for.
	"""
	edges: set[tuple[str, str]] = set()
	for bean in beans:
		edges.update((bean.id, blocked) for blocked in bean.blocking_ids)
		edges.update((blocker, bean.id) for blocker in bean.blocked_by_ids)
	return edges


def resolve_dependencies(beans: list[Bean]) -> list[Bean]:
	"""Fill in `blocked_by_open` and `unblocks` across the whole board.

	Neither is knowable from one bean: being blocked can be asserted by the
	blocker rather than the blocked, and whether a blocker still counts
	depends on that blocker's status, which lives on a different record.
	"""
	edges = dependency_edges(beans)
	status = {bean.id: bean.status for bean in beans}

	blocked_by_open = Counter[str]()
	unblocks = Counter[str]()
	for blocker, blocked in edges:
		unblocks[blocker] += 1
		# An unknown blocker is one bv did not load, not one that is finished;
		# assume it still counts rather than silently marking work ready.
		if status.get(blocker, "todo") in UNFINISHED:
			blocked_by_open[blocked] += 1

	return [
		replace(
			bean,
			blocked_by_open=blocked_by_open[bean.id],
			unblocks=unblocks[bean.id],
		)
		for bean in beans
	]


def rank(bean: Bean) -> tuple[object, ...]:
	"""Order within one group of beans, most actionable first.

	1. Status -- live work above finished work. The strongest signal there is;
	   a completed bean's readiness is not interesting.
	2. Not blocked, before blocked. A blocked bean cannot be picked up at all,
	   so it ranks below one that can, regardless of how urgent it looks.
	3. How much it unblocks, descending. Between two things you *can* start,
	   the one that frees other work is worth more than the one that ends in
	   itself. Steps 2 and 3 together float ready work -- unblocked, and
	   holding something else up -- to the top of its group.
	4. Priority. Previously absent from both orderings: the column was
	   displayed but never sorted on, so `critical` and `deferred` interleaved
	   by date.
	5. Most recently updated, then title so the order is stable between runs.

	This is the only definition of board order. It used to be two: a flat one
	here and a separate one in `tree`, which quietly won because the tree
	re-sorts siblings after this module has sorted the list.
	"""
	return (
		bean.status_rank,
		bean.is_blocked,
		-bean.unblocks,
		_PRIORITY_RANK.get(bean.priority, len(PRIORITY_ORDER)),
		-bean.updated_at.timestamp(),
		bean.title,
	)


def sort_key(bean: Bean) -> tuple[object, ...]:
	"""`rank`, grouped by project -- the order of the flat list from load_all."""
	return (bean.project, *rank(bean))


def load_all(root: Path) -> tuple[list[Bean], list[str]]:
	"""Load every bean `root` covers, querying each project concurrently.

	`root` is either a beans project itself or a directory of them -- see
	`projects_under`, which is the only thing here that knows the difference.

	Returns the beans plus a list of human-readable problems. A project that
	fails is reported but does not sink the others -- one broken repo should
	not blank the whole board.
	"""
	projects = projects_under(root)
	if not projects:
		return [], [f"no beans projects in {root} — run bv from a beans repo, or from a directory that holds some"]

	beans: list[Bean] = []
	problems: list[str] = []

	# Each call is a process spawn, and the spawn dominates -- the whole load
	# is ~21ms across five projects, so overlapping them is most of why it is
	# that fast. Serializing would roughly multiply it by the project count.
	with ThreadPoolExecutor(max_workers=min(8, len(projects))) as pool:
		for result in pool.map(_safe_fetch, projects):
			if isinstance(result, BeansError):
				problems.append(str(result))
			else:
				beans.extend(result)

	# Resolved after every project is in, because a dependency can cross
	# projects and the blocker's status decides whether it still counts.
	beans = resolve_dependencies(beans)
	beans.sort(key=sort_key)
	return beans, problems


def _safe_fetch(project: Project) -> list[Bean] | BeansError:
	try:
		return fetch_project_beans(project)
	except BeansError as exc:
		return exc
