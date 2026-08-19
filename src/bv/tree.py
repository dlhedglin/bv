"""Arrange a flat list of beans into the hierarchy beans already records.

Beans carry a `parentId` and a type ladder (milestone > epic > feature >
task/bug), but the API hands them back flat. This module does the group-by
locally -- no extra `beans` calls -- and flattens the result back into display
order given a set of collapsed nodes.

It is deliberately free of Textual imports so the shape of the tree can be
tested without standing up an app.

Two structural hazards are handled here rather than in the view, because both
produce *silently missing beans* rather than errors:

- **Orphans.** A `parentId` can point at a bean that is archived, filtered out,
  or in another project. Attaching children only to parents we can see would
  drop those beans off the board entirely, so an unresolvable parent demotes
  the bean to the project root.
- **Cycles.** Nothing in beans stops a -> b -> a. Such beans have a parent that
  *is* present, so they never qualify as roots and would vanish from a naive
  build. Anything left unemitted after the roots are walked is surfaced at the
  project root instead.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from .beans import Bean, rank


@dataclass
class Node:
	"""One row in the tree: either a project heading or a bean."""

	key: str
	"""Stable identity for collapse state -- project name, or bean id."""

	bean: Bean | None
	"""None for a project heading."""

	project: str
	depth: int
	children: list[Node] = field(default_factory=list)

	@property
	def is_project(self) -> bool:
		return self.bean is None

	@property
	def has_children(self) -> bool:
		return bool(self.children)

	def descendants(self) -> list[Node]:
		out: list[Node] = []
		for child in self.children:
			out.append(child)
			out.extend(child.descendants())
		return out


# Siblings are ordered by beans.rank, the one definition of board order. This
# module used to carry its own copy, which silently outranked the sort in
# load_all -- siblings are re-sorted here, so whatever that function decided
# never reached the screen. Project grouping is not part of it: siblings share
# a parent, so they already share a project.
_sort_key = rank


def build_forest(beans: list[Bean], *, flat: bool = False) -> list[Node]:
	"""Group beans into one tree per project, projects in name order.

	`flat` drops the project layer and returns the bean roots directly, with no
	heading `Node` above them. That is the shape for a board run from inside a
	single repo, where a heading is one redundant row naming the same project
	as every bean indented beneath it.

	The roots keep depth 1 either way, so the indent a view derives from depth
	does not have to know which shape it is looking at.
	"""
	by_project: dict[str, list[Bean]] = defaultdict(list)
	for bean in beans:
		by_project[bean.project].append(bean)
	projects = [_build_project(name, by_project[name]) for name in sorted(by_project)]
	if not flat:
		return projects
	return [root for project in projects for root in project.children]


def _build_project(project: str, beans: list[Bean]) -> Node:
	by_id = {bean.id: bean for bean in beans}
	children_of: dict[str, list[Bean]] = defaultdict(list)
	roots: list[Bean] = []

	for bean in beans:
		# An unresolvable parent means root, not dropped -- see module docstring.
		if bean.parent_id and bean.parent_id in by_id:
			children_of[bean.parent_id].append(bean)
		else:
			roots.append(bean)

	emitted: set[str] = set()

	def make(bean: Bean, depth: int) -> Node:
		emitted.add(bean.id)
		node = Node(key=bean.id, bean=bean, project=project, depth=depth)
		for child in sorted(children_of.get(bean.id, ()), key=_sort_key):
			if child.id in emitted:
				continue
			node.children.append(make(child, depth + 1))
		return node

	root_nodes = [make(bean, 1) for bean in sorted(roots, key=_sort_key)]

	# Anything still unemitted is trapped in a parent cycle. Show it rather
	# than lose it.
	for bean in sorted(beans, key=_sort_key):
		if bean.id not in emitted:
			root_nodes.append(make(bean, 1))

	return Node(key=project, bean=None, project=project, depth=0, children=root_nodes)


def visible_rows(forest: list[Node], collapsed: set[str]) -> list[Node]:
	"""Flatten to display order, skipping the children of collapsed nodes."""
	rows: list[Node] = []

	def walk(node: Node) -> None:
		rows.append(node)
		if node.key in collapsed:
			return
		for child in node.children:
			walk(child)

	for root in forest:
		walk(root)
	return rows


def filter_forest(forest: list[Node], match: Callable[[Bean], bool]) -> list[Node]:
	"""Prune to beans satisfying `match`, keeping their ancestors.

	Ancestors are kept even when they do not match themselves, because a hit
	shown without its epic and project reads as an unattributed orphan. A
	project heading survives only if something under it did.

	Returns new nodes; the input forest is not mutated, so the unfiltered
	board is still there when the filter is cleared.
	"""

	def prune(node: Node) -> Node | None:
		kept = [child for child in map(prune, node.children) if child is not None]
		hit = node.bean is not None and match(node.bean)
		if not kept and not hit:
			return None
		return Node(
			key=node.key,
			bean=node.bean,
			project=node.project,
			depth=node.depth,
			children=kept,
		)

	return [pruned for pruned in map(prune, forest) if pruned is not None]


def collapsible_keys(forest: list[Node]) -> set[str]:
	"""Keys of every node that has something to collapse."""
	keys: set[str] = set()
	for root in forest:
		for node in [root, *root.descendants()]:
			if node.has_children:
				keys.add(node.key)
	return keys


def project_keys(forest: list[Node]) -> set[str]:
	"""Keys of the project headings, which a flat forest has none of."""
	return {root.key for root in forest if root.is_project and root.has_children}


def summarize(node: Node) -> str:
	"""Counts for a project heading."""
	beans = [n.bean for n in node.descendants() if n.bean is not None]
	if not beans:
		return "empty"
	open_ = sum(1 for b in beans if b.status in ("todo", "in-progress"))
	return f"{len(beans)} beans · {open_} open"
