from datetime import UTC, datetime

from bv.beans import Bean, resolve_dependencies
from bv.tree import (
	build_forest,
	collapsible_keys,
	filter_forest,
	project_keys,
	summarize,
	visible_rows,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def bean(id, *, project="p", parent=None, status="todo", title=None, when=T0, **extra):
	return Bean(
		project=project,
		id=id,
		title=title or id,
		status=status,
		type="task",
		priority=extra.pop("priority", "normal"),
		tags=(),
		updated_at=when,
		parent_id=parent,
		**extra,
	)


def keys(nodes):
	return [n.key for n in nodes]


def test_children_nest_under_their_parent():
	forest = build_forest([bean("a"), bean("b", parent="a")])
	(root,) = forest
	assert root.key == "p" and root.is_project
	assert keys(root.children) == ["a"]
	assert keys(root.children[0].children) == ["b"]
	assert root.children[0].children[0].depth == 2


def test_orphan_with_missing_parent_is_promoted_not_dropped():
	# parentId pointing at an archived / filtered / cross-project bean.
	forest = build_forest([bean("a"), bean("orphan", parent="nonexistent")])
	rows = visible_rows(forest, set())
	assert "orphan" in keys(rows)
	assert next(n for n in rows if n.key == "orphan").depth == 1


def test_parent_cycle_still_surfaces_every_bean():
	# a -> b -> a. Neither qualifies as a root; a naive build loses both.
	forest = build_forest([bean("a", parent="b"), bean("b", parent="a")])
	rows = visible_rows(forest, set())
	assert {"a", "b"} <= set(keys(rows))


def test_each_bean_appears_exactly_once():
	beans = [bean("a"), bean("b", parent="a"), bean("c", parent="b"), bean("d")]
	rows = [n for n in visible_rows(build_forest(beans), set()) if not n.is_project]
	assert sorted(keys(rows)) == ["a", "b", "c", "d"]
	assert len(keys(rows)) == len(set(keys(rows)))


def test_projects_are_separate_trees_in_name_order():
	forest = build_forest([bean("x", project="zeta"), bean("y", project="alpha")])
	assert keys(forest) == ["alpha", "zeta"]


def test_parent_in_another_project_does_not_link_across_trees():
	beans = [bean("a", project="one"), bean("b", project="two", parent="a")]
	forest = build_forest(beans)
	two = next(n for n in forest if n.key == "two")
	assert keys(two.children) == ["b"]
	assert two.children[0].depth == 1


def test_collapsing_hides_descendants_but_keeps_the_node():
	beans = [bean("a"), bean("b", parent="a"), bean("c", parent="b")]
	forest = build_forest(beans)
	assert set(keys(visible_rows(forest, set()))) == {"p", "a", "b", "c"}
	assert set(keys(visible_rows(forest, {"a"}))) == {"p", "a"}
	assert set(keys(visible_rows(forest, {"b"}))) == {"p", "a", "b"}


def test_collapsing_a_project_hides_the_whole_tree():
	forest = build_forest([bean("a"), bean("b", parent="a")])
	assert keys(visible_rows(forest, {"p"})) == ["p"]


def test_ordering_is_status_then_recency():
	beans = [
		bean("old", status="in-progress", when=datetime(2026, 1, 1, tzinfo=UTC)),
		bean("new", status="in-progress", when=datetime(2026, 6, 1, tzinfo=UTC)),
		bean("done", status="completed"),
	]
	(root,) = build_forest(beans)
	assert keys(root.children) == ["new", "old", "done"]


def test_collapsible_keys_excludes_leaves():
	forest = build_forest([bean("a"), bean("b", parent="a"), bean("leaf")])
	assert collapsible_keys(forest) == {"p", "a"}
	assert project_keys(forest) == {"p"}


def test_summarize_counts_all_descendants_not_just_children():
	beans = [
		bean("a", status="todo"),
		bean("b", parent="a", status="in-progress"),
		bean("c", parent="b", status="completed"),
	]
	(root,) = build_forest(beans)
	assert summarize(root) == "3 beans · 2 open"


def test_filter_keeps_ancestors_of_a_match():
	beans = [bean("epic"), bean("child", parent="epic", title="find me")]
	kept = filter_forest(build_forest(beans), lambda b: b.title == "find me")
	# The epic does not match but must survive, or the hit reads as an orphan.
	assert set(keys(visible_rows(kept, set()))) == {"p", "epic", "child"}


def test_filter_drops_branches_with_no_match():
	beans = [bean("keep", title="find me"), bean("drop"), bean("also", parent="drop")]
	kept = filter_forest(build_forest(beans), lambda b: b.title == "find me")
	assert set(keys(visible_rows(kept, set()))) == {"p", "keep"}


def test_filter_drops_a_project_with_nothing_left():
	beans = [bean("a", project="one", title="find me"), bean("b", project="two")]
	kept = filter_forest(build_forest(beans), lambda b: b.title == "find me")
	assert keys(kept) == ["one"]


def test_filter_keeps_descendants_of_a_matching_parent_only_if_they_match():
	beans = [bean("epic", title="find me"), bean("child", parent="epic")]
	kept = filter_forest(build_forest(beans), lambda b: b.title == "find me")
	assert set(keys(visible_rows(kept, set()))) == {"p", "epic"}


def test_filter_does_not_mutate_the_original_forest():
	beans = [bean("epic"), bean("child", parent="epic", title="find me"), bean("gone")]
	forest = build_forest(beans)
	before = keys(visible_rows(forest, set()))
	filter_forest(forest, lambda b: b.title == "find me")
	assert keys(visible_rows(forest, set())) == before


def test_filter_matching_nothing_is_an_empty_forest():
	forest = build_forest([bean("a"), bean("b")])
	assert filter_forest(forest, lambda b: False) == []


def test_empty_input_is_an_empty_forest():
	assert build_forest([]) == []
	assert visible_rows([], set()) == []


# -- sibling order --------------------------------------------------------
#
# This module used to carry its own _sort_key, which outranked the sort in
# load_all because siblings are re-sorted here. These pin the shared
# beans.rank to what actually reaches the screen.


def test_blocked_siblings_sink_below_startable_ones():
	forest = build_forest(
		resolve_dependencies(
			[
				bean("epic"),
				bean("stuck", parent="epic", blocked_by_ids=("wall",)),
				bean("go", parent="epic"),
				bean("wall"),
			]
		)
	)
	(epic,) = [n for n in forest[0].children if n.key == "epic"]
	assert keys(epic.children) == ["go", "stuck"]


def test_a_sibling_that_unblocks_more_sorts_first():
	forest = build_forest(
		resolve_dependencies(
			[
				bean("epic"),
				bean("leaf", parent="epic"),
				bean("hub", parent="epic", blocking_ids=("x", "y")),
				bean("x"),
				bean("y"),
			]
		)
	)
	(epic,) = [n for n in forest[0].children if n.key == "epic"]
	assert keys(epic.children) == ["hub", "leaf"]


def test_siblings_sort_on_priority():
	forest = build_forest(
		[
			bean("epic"),
			bean("cold", parent="epic", priority="deferred"),
			bean("hot", parent="epic", priority="critical"),
		]
	)
	(epic,) = [n for n in forest[0].children if n.key == "epic"]
	assert keys(epic.children) == ["hot", "cold"]


# -- flat: no project layer at all -----------------------------------------
#
# The shape for a board run from inside a single repo. A heading there is one
# redundant row naming the same project as every bean indented under it.


def test_flat_returns_the_bean_roots_with_no_heading():
	forest = build_forest([bean("a"), bean("b", parent="a")], flat=True)
	assert keys(forest) == ["a"]
	assert not any(node.is_project for node in forest)


def test_flat_keeps_the_hierarchy_under_the_roots():
	forest = build_forest([bean("a"), bean("b", parent="a")], flat=True)
	assert keys(forest[0].children) == ["b"]


def test_flat_roots_keep_depth_one_so_the_indent_does_not_move():
	# The view derives its indent from `depth - 1`; a root at depth 0 would
	# push every bean one level right of where the grouped board puts it.
	flat = build_forest([bean("a"), bean("b", parent="a")], flat=True)
	(grouped,) = build_forest([bean("a"), bean("b", parent="a")])
	assert [n.depth for n in visible_rows(flat, set())] == [1, 2]
	assert [n.depth for n in visible_rows(grouped.children, set())] == [1, 2]


def test_flat_orders_roots_the_same_way_the_grouped_board_does():
	beans = [bean("late", when=T0), bean("early", when=datetime(2026, 6, 1, tzinfo=UTC))]
	(grouped,) = build_forest(beans)
	assert keys(build_forest(beans, flat=True)) == keys(grouped.children)


def test_flat_has_no_project_headings_to_collapse_to():
	forest = build_forest([bean("a"), bean("b", parent="a")], flat=True)
	assert project_keys(forest) == set()
	# The beans themselves are still foldable; only the project layer is gone.
	assert collapsible_keys(forest) == {"a"}


def test_flat_of_nothing_is_nothing():
	assert build_forest([], flat=True) == []
