"""Tests for the preview pane.

The widget half runs inside Textual's `run_test` harness, driven through
`asyncio.run` rather than an async pytest plugin: the venv has plain pytest
and nothing else, and the preview is not worth a new dependency. The
`preview_test` decorator hides that, so the tests below read as if they were
async.
"""

import asyncio
from datetime import UTC, datetime

from textual.app import App, ComposeResult
from textual.geometry import Region
from textual.widgets import Static

from bv.beans import Bean
from bv.preview import (
	EMPTY_TITLE,
	NO_BODY,
	NOTHING,
	PENDING,
	BeanPreview,
	body_markdown,
	clean_body,
	header_text,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)

BODY = """# Why

The board only has room for a title.

- one
- two
"""


def bean(
	id="bv-ax9v",
	*,
	title="Preview pane for the highlighted bean",
	body=BODY,
	tags=("ux",),
	parent="bv-root",
	blocking=("bv-1111",),
	blocked_by=("bv-2222",),
):
	return Bean(
		project="bv",
		id=id,
		title=title,
		status="todo",
		type="feature",
		priority="high",
		tags=tags,
		updated_at=T0,
		parent_id=parent,
		body=body,
		blocking_ids=blocking,
		blocked_by_ids=blocked_by,
	)


class PreviewApp(App):
	"""Throwaway host so the widget can be exercised headlessly."""

	def compose(self) -> ComposeResult:
		yield BeanPreview()


def rendered(preview: BeanPreview) -> str:
	"""Everything the preview actually paints, as text.

	Goes through `render_lines` rather than reading the renderables back, so
	an assertion fails if content is built but never reaches the screen.
	Regions come from `outer_size`: `size` excludes padding, and rendering at
	that height silently drops the last line.
	"""
	lines: list[str] = []
	for widget in preview.query(Static):
		width, height = widget.outer_size
		if not width or not height:
			continue
		lines.extend(strip.text for strip in widget.render_lines(Region(0, 0, width, height)))
	return "\n".join(lines)


TEST_DELAY = 0.02
"""What the render delay is shortened to for most tests.

The real one is 150 ms and every widget test would wait it out. Two tests
below run against the shipped `RENDER_DELAY` instead, because what it is worth
is the thing they are checking."""


async def pump(pilot) -> None:
	"""Two message-pump turns, which is what a mount takes to land."""
	await pilot.pause()
	await pilot.pause()


async def settle(preview, pilot) -> str:
	"""Let the delayed render fire and mount, then read the pane back.

	`show` only starts a timer now, and `Markdown.update` then parses in an
	executor and mounts in batches -- so the content lands a couple of
	message-pump turns after the delay, not after `show` returns.
	"""
	if preview.is_pending:
		await asyncio.sleep(preview.RENDER_DELAY + 0.02)
	await pump(pilot)
	return rendered(preview)


def preview_test(scenario, *, delay=TEST_DELAY):
	"""Run an async test body against a freshly mounted preview.

	Deliberately not `functools.wraps`: that would leave `__wrapped__` behind,
	and pytest follows it to collect the *scenario's* signature, then fails
	hunting for `preview` and `pilot` fixtures.
	"""

	def run() -> None:
		async def main() -> None:
			app = PreviewApp()
			async with app.run_test(size=(80, 40)) as pilot:
				preview = app.query_one(BeanPreview)
				if delay is not None:
					preview.RENDER_DELAY = delay
				await scenario(preview, pilot)

		asyncio.run(main())

	run.__name__ = scenario.__name__
	run.__doc__ = scenario.__doc__
	return run


def real_delay_test(scenario):
	"""`preview_test`, but against the delay the app actually ships with."""
	return preview_test(scenario, delay=None)


UNRACEABLE_DELAY = 5.0
"""A delay no layout pass can outrun.

For a test whose subject is what happens *while* a render is pending. The
shipped 150 ms is that window on this machine and not on a loaded CI runner,
where laying out a long body takes longer than the timer -- the render fires
in the middle of the test and the assertion about the pending state fails on
the slow machine only, which is worse than not testing the timing at all.
Nothing such a test checks depends on the delay being any particular length,
only on it outlasting the layout in between, so it names a length nothing can
race rather than the shipped one. No test waits this out: the pending render is
always cancelled or flushed before the timer would fire."""


def pending_window_test(scenario):
	"""`preview_test`, but with a delay nothing can race (`UNRACEABLE_DELAY`)."""
	return preview_test(scenario, delay=UNRACEABLE_DELAY)


# -- pure content ---------------------------------------------------------


def test_clean_body_normalizes_line_endings_and_trims_blank_edges():
	assert clean_body("\r\n\r\nfirst\r\nsecond\n\n\n") == "first\nsecond"


def test_clean_body_drops_control_characters_but_keeps_tabs():
	# A NUL or a bare ESC from pasted terminal output is the one kind of input
	# that can make rendering fail rather than merely look odd.
	assert clean_body("a\x00b\x1b[31mc\td\x7f") == "ab[31mc\td"


def test_clean_body_of_nothing_is_nothing():
	assert clean_body("") == ""
	assert clean_body("\n\n   \n") == ""


def test_body_markdown_substitutes_a_placeholder_for_an_empty_body():
	assert body_markdown(bean(body="")) == NO_BODY
	assert body_markdown(bean(body="\n\n")) == NO_BODY
	assert body_markdown(bean(body="real")) == "real"


def test_body_markdown_of_no_bean_is_blank():
	assert body_markdown(None) == ""


def test_header_shows_every_field_the_table_cannot():
	plain = header_text(bean()).plain
	assert "bv-ax9v" in plain
	for label in ("type", "priority", "status", "tags", "parent", "blocked by"):
		assert label in plain
	assert "bv-1111" in plain and "bv-2222" in plain


def test_header_marks_missing_fields_rather_than_leaving_gaps():
	plain = header_text(bean(tags=(), parent=None, blocking=(), blocked_by=())).plain
	assert plain.count(NOTHING) == 4


def test_header_of_no_bean_is_the_empty_state():
	assert EMPTY_TITLE in header_text(None).plain


# -- widget ---------------------------------------------------------------


@preview_test
async def test_a_normal_bean_renders_its_metadata_and_body(preview, pilot):
	preview.show(bean())
	out = await settle(preview, pilot)
	assert "bv-ax9v" in out
	assert "feature" in out and "high" in out and "todo" in out
	assert "bv-root" in out and "bv-1111" in out and "bv-2222" in out
	# The body arrives rendered as markdown, not echoed as source.
	assert "Why" in out and "#" not in out
	assert "The board only has room for a title." in out
	assert preview.bean.id == "bv-ax9v"


@preview_test
async def test_an_empty_body_says_so_instead_of_rendering_blank(preview, pilot):
	preview.show(bean(body=""))
	out = await settle(preview, pilot)
	assert "This bean has no body." in out
	assert "bv-ax9v" in out


@preview_test
async def test_a_bean_with_no_tags_and_no_parent_still_renders(preview, pilot):
	preview.show(bean(tags=(), parent=None, blocking=(), blocked_by=()))
	out = await settle(preview, pilot)
	assert "bv-ax9v" in out
	assert NOTHING in out
	assert "The board only has room for a title." in out


@preview_test
async def test_switching_beans_replaces_the_previous_one(preview, pilot):
	preview.show(bean())
	await settle(preview, pilot)
	preview.show(bean(id="bv-zzzz", title="Second", body="Totally different prose."))
	out = await settle(preview, pilot)
	assert "bv-zzzz" in out and "Totally different prose." in out
	assert "bv-ax9v" not in out
	assert "The board only has room for a title." not in out
	assert preview.bean.id == "bv-zzzz"


@preview_test
async def test_showing_none_returns_to_the_empty_state(preview, pilot):
	preview.show(bean())
	await settle(preview, pilot)
	preview.show(None)
	out = await settle(preview, pilot)
	assert EMPTY_TITLE in out
	assert "bv-ax9v" not in out
	assert preview.bean is None


@preview_test
async def test_an_unset_preview_shows_the_empty_state(preview, pilot):
	assert EMPTY_TITLE in await settle(preview, pilot)
	assert preview.bean is None


def test_a_bean_set_before_mount_is_rendered_on_mount():
	# show() has to be safe while the pane is still composing: Markdown.update
	# needs an app, and there is not one yet.
	class Preloaded(App):
		def compose(self) -> ComposeResult:
			widget = BeanPreview()
			widget.show(bean(body="Set before the app existed."))
			yield widget

	async def main() -> None:
		app = Preloaded()
		async with app.run_test(size=(80, 40)) as pilot:
			preview = app.query_one(BeanPreview)
			assert "Set before the app existed." in await settle(preview, pilot)

	asyncio.run(main())


@preview_test
async def test_malformed_markdown_renders_instead_of_raising(preview, pilot):
	nasty = (
		"# Unclosed fence\n"
		"```python\n"
		"print('hi')\n"
		"\n"
		"| a | b\n"
		"|---\n"
		"| 1\n"
		"\n"
		"<div><span>raw html\n"
		"\n"
		"[broken](\n"
		"\n"
		"> quote\n"
		">> nested\n"
		"\n"
		"\x00\x1b[31mcontrol chars\n"
		"\n" + "*" * 500 + "\n"
	)
	preview.show(bean(body=nasty))
	out = await settle(preview, pilot)
	# Nothing is asserted about *how* it degrades -- only that the pane
	# survived and is still showing this bean.
	assert "bv-ax9v" in out


@preview_test
async def test_re_showing_the_same_bean_keeps_the_reader_where_they_were(preview, pilot):
	# The table clears and re-adds every row on reload and on every fold, so
	# the highlight event fires repeatedly with an identical bean behind it.
	preview.show(bean(body="paragraph\n\n" * 200))
	await settle(preview, pilot)
	preview.scroll_to(y=30, animate=False)
	await settle(preview, pilot)
	scrolled = preview.scroll_offset.y
	assert scrolled > 0

	preview.show(bean(body="paragraph\n\n" * 200))
	await settle(preview, pilot)
	assert preview.scroll_offset.y == scrolled


@preview_test
async def test_a_different_bean_scrolls_back_to_the_top(preview, pilot):
	preview.show(bean(body="paragraph\n\n" * 200))
	await settle(preview, pilot)
	preview.scroll_to(y=30, animate=False)
	await settle(preview, pilot)
	assert preview.scroll_offset.y > 0

	preview.show(bean(id="bv-other", body="paragraph\n\n" * 200))
	await settle(preview, pilot)
	assert preview.scroll_offset.y == 0


# -- the delayed render ---------------------------------------------------


def count_renders(preview):
	"""Start counting body rebuilds -- the cost the delay exists to avoid.

	Returns a callable giving the count so far. Installed after mount, so the
	first paint is not counted.
	"""
	calls: list[str] = []
	update = preview._body.update

	def counted(markdown: str):
		calls.append(markdown)
		return update(markdown)

	preview._body.update = counted
	return lambda: len(calls)


@real_delay_test
async def test_a_cursor_move_marks_the_pane_rather_than_rendering(preview, pilot):
	# Runs against the shipped delay: draining the message pump twice is not
	# instant, and a 20 ms one would already have fired by the time the pane
	# can be read back.
	preview.show(bean(id="bv-first", body="The first body."))
	await settle(preview, pilot)

	preview.show(bean(id="bv-zzzz", body="The second body."))
	await pump(pilot)
	out = rendered(preview)
	assert preview.is_pending
	# Nothing has moved: the pane is still the previous bean, whole.
	assert "bv-first" in out and "The first body." in out
	assert "The second body." not in out
	# And it names the one it is on its way to, so the reader knows which of
	# the two they are looking at.
	assert "rendering bv-zzzz" in out

	out = await settle(preview, pilot)
	assert PENDING not in out and "rendering bv-zzzz" not in out
	assert "The second body." in out and "The first body." not in out
	assert not preview.is_pending


@preview_test
async def test_a_burst_of_moves_renders_only_where_it_stopped(preview, pilot):
	renders = count_renders(preview)
	for index in range(6):
		preview.show(bean(id=f"bv-{index:04d}", body=f"body number {index}"))
	out = await settle(preview, pilot)
	assert "body number 5" in out
	assert "body number 4" not in out
	assert renders() == 1


@preview_test
async def test_an_unchanged_bean_does_not_restart_the_timer(preview, pilot):
	# The table re-fires its highlight on every fold and every reload. That
	# must not keep pushing the render out of reach while the cursor sits
	# still -- the pane would never catch up.
	preview.show(bean(id="bv-zzzz", body="Second"))
	for _ in range(4):
		preview.show(bean(id="bv-zzzz", body="Second"))
		await asyncio.sleep(preview.RENDER_DELAY / 2)
	await pump(pilot)
	assert "Second" in rendered(preview)


@pending_window_test
async def test_moving_off_a_bean_and_back_leaves_it_alone(preview, pilot):
	# Sideways through a fold or a mis-keyed `j` should not cost the reader
	# their place in a body that never left the screen.
	first = bean(body="paragraph\n\n" * 200)
	preview.show(first)
	# Flushed rather than waited out: the delay here is the long one, and the
	# subject of this test only starts once the body is on screen.
	preview.flush()
	await pump(pilot)
	preview.scroll_to(y=30, animate=False)
	await pump(pilot)
	scrolled = preview.scroll_offset.y
	assert scrolled > 0

	renders = count_renders(preview)
	preview.show(bean(id="bv-zzzz", body="Second"))
	assert preview.is_pending
	# A real move away and back is two keypresses apart, so the pane lays out
	# in its pending state in between -- long enough to lose a scroll offset
	# if the pending state took the body out of the layout.
	await pump(pilot)
	preview.show(first)
	assert not preview.is_pending

	out = await settle(preview, pilot)
	assert renders() == 0
	assert "bv-ax9v" in out and "bv-zzzz" not in out
	assert preview.scroll_offset.y == scrolled


@preview_test
async def test_flush_renders_the_pending_bean_now(preview, pilot):
	preview.show(bean(id="bv-zzzz", body="Second"))
	preview.flush()
	assert not preview.is_pending
	await pump(pilot)
	out = rendered(preview)
	assert "Second" in out and PENDING not in out


@preview_test
async def test_flush_with_nothing_pending_leaves_the_reader_alone(preview, pilot):
	preview.show(bean(body="paragraph\n\n" * 200))
	await settle(preview, pilot)
	preview.scroll_to(y=30, animate=False)
	await pump(pilot)
	scrolled = preview.scroll_offset.y

	renders = count_renders(preview)
	preview.flush()
	await pump(pilot)
	assert renders() == 0
	assert preview.scroll_offset.y == scrolled


@preview_test
async def test_cancel_drops_the_pending_render(preview, pilot):
	# What `p` does: the pane is going off screen, so nothing should be left
	# holding a timer pointed at it.
	preview.show(bean())
	await settle(preview, pilot)

	renders = count_renders(preview)
	preview.show(bean(id="bv-zzzz", body="Second"))
	preview.cancel()
	assert not preview.is_pending
	out = await settle(preview, pilot)
	assert renders() == 0
	assert "Second" not in out
	assert "The board only has room for a title." in out
	# And the pane says it is showing the bean it is actually showing, so the
	# next show() of the cursor's bean is not swallowed as a repeat.
	assert preview.bean.id == "bv-ax9v"

	preview.show(bean(id="bv-zzzz", body="Second"))
	assert preview.is_pending
	assert "Second" in await settle(preview, pilot)


@preview_test
async def test_a_render_that_lands_after_teardown_paints_nothing(preview, pilot):
	# bv-ndrn: the timer outlives the app on a quit taken mid-navigation.
	preview.show(bean(id="bv-zzzz", body="Second"))
	assert preview.is_pending
	await preview.app.action_quit()
	# The callback the timer would have run, run by hand -- it has to notice
	# there is no longer a screen to paint into rather than raise.
	preview._render_pending()
	assert preview.bean.id == "bv-zzzz"


def test_the_delay_falls_between_a_key_repeat_and_a_pause():
	# Longer than the slowest macOS key repeat (`KeyRepeat` 8 = 120 ms) so a
	# held key cannot leak a render through mid-scroll, and short enough to be
	# over before a reader who stopped has started reading. Asserted because
	# this is a measured number, not a taste one -- see RENDER_DELAY.
	assert 0.12 < BeanPreview.RENDER_DELAY < 0.3


@real_delay_test
async def test_a_fast_key_repeat_never_renders_on_the_way_past(preview, pilot):
	# 30 ms a key is a common fast macOS repeat rate (`KeyRepeat` 2), and the
	# whole point of the delay is that a scroll at that rate costs nothing.
	renders = count_renders(preview)
	for index in range(8):
		preview.show(bean(id=f"bv-{index:04d}", body=f"body number {index}"))
		await asyncio.sleep(0.03)
	assert renders() == 0

	out = await settle(preview, pilot)
	assert renders() == 1
	assert "body number 7" in out


@real_delay_test
async def test_a_settled_cursor_renders_without_being_asked(preview, pilot):
	preview.show(bean())
	await asyncio.sleep(BeanPreview.RENDER_DELAY + 0.05)
	await pump(pilot)
	assert "The board only has room for a title." in rendered(preview)
