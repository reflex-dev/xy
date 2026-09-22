"""`show=False` collapses the axis's layout slot (dossier §33, axes docs).

The visibility shorthands compile to transparent axis paints rather than to a
flag, so layout has to ask the paint whether any text will be seen. The static
exporters already do (`_axis_text_paint_visible`, whose docstring names the
edge-to-edge sparkline as the reason); the browser did not, so the same chart
rendered flush in an SVG and inset in a canvas. These tests pin the two to each
other.

Browser probes drive the real client; they skip (never fail) without Chromium,
like the repo's others.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

WIDTH = 1088
HEIGHT = 200
PADDING = (8, 0, 28, 0)


def _chart(**axes):
    """The reported repro: a line with both axes switched off, no padding to
    spare, and a fluid width so the plot can reach the container edge."""
    return xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(**axes.get("x", {})),
        xy.y_axis(**axes.get("y", {})),
        width=WIDTH,
        height=HEIGHT,
        padding=PADDING,
    )


def _svg_plot_rect(chart) -> tuple[float, float, float, float]:
    """The exporter's plot rect (x, y, width, height), read from the clip path
    it draws marks into. All four, not just the horizontal pair: collapsing a
    gutter on one axis while the other renderer keeps it is exactly the class
    of divergence this fixes, and it can happen vertically too."""
    svg = chart.to_svg()
    match = re.search(r"<clipPath[^>]*>\s*<rect ([^/]*)/>", svg)
    assert match is not None, "SVG clip path shape changed; update this helper"
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group(1)))
    return tuple(round(float(attrs[k]), 1) for k in ("x", "y", "width", "height"))


def test_export_collapses_the_slot_for_show_false() -> None:
    """The contract the exporters already keep: nothing drawn, nothing
    reserved, on either side."""
    off = {"show": False}
    assert _svg_plot_rect(_chart(x=off, y=off))[:3] == (0.0, PADDING[0], WIDTH)
    flush_right = _chart(x=off, y={"show": False, "side": "right"})
    assert flush_right and _svg_plot_rect(flush_right)[2] == WIDTH
    # A grid needs no gutter, so `show=False, grid=True` is flush as well.
    grid_only = _chart(x=off, y={"show": False, "grid": True})
    assert _svg_plot_rect(grid_only)[2] == WIDTH
    # An axis that draws its labels still reserves its room.
    x0, _y, w, _h = _svg_plot_rect(_chart())
    assert x0 > 0 and w < WIDTH, (x0, w)


def test_an_axis_title_keeps_its_gutter_without_tick_labels() -> None:
    """Tick labels and the axis title are separate paints, so either one
    showing keeps the band. Gating the whole gutter on the tick labels drew an
    opaque title into a gutter that no longer existed — over the plot, for a
    right-side axis."""
    titled_right = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(show=False),
        xy.y_axis(show=False, side="right", label="Value", style={"label_color": "#000000"}),
        width=WIDTH,
        height=HEIGHT,
        padding=(0, 0, 0, 0),
    )
    # The title is drawn, so the flat right-side reservation stands.
    assert _svg_plot_rect(titled_right)[2] < WIDTH
    # With no title to draw, it does not.
    untitled_right = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(show=False),
        xy.y_axis(show=False, side="right"),
        width=WIDTH,
        height=HEIGHT,
        padding=(0, 0, 0, 0),
    )
    assert _svg_plot_rect(untitled_right)[2] == WIDTH


_PLOT_RECT_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    view._drawNow();
    document.body.setAttribute("data-xy-plotrect", JSON.stringify({
      x: view.plot.x, y: view.plot.y, w: view.plot.w, h: view.plot.h,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-plotrect-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def _browser_plot_rect(chart, label: str) -> tuple[float, float, float, float]:
    """The client's plot rect (x, y, width, height), in the same order as
    `_svg_plot_rect`."""
    chromium = find_chromium()
    if not chromium:
        # `run_browser_probe` turns an unlaunchable browser into a failure under
        # XY_REQUIRE_BROWSER; skipping before that call would slip past it.
        if os.environ.get("XY_REQUIRE_BROWSER"):
            pytest.fail(f"{label}: XY_REQUIRE_BROWSER is set but no chromium was found")
        pytest.skip(f"no chromium available for the {label} probe")
    document = probe_document(chart, _PLOT_RECT_PROBE)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium, document, Path(td) / "axis.html", "data-xy-plotrect", label=label
        )
    return tuple(round(float(payload[k]), 1) for k in ("x", "y", "w", "h"))


def test_browser_show_false_reaches_the_edge_like_the_export() -> None:
    """The divergence this fixes: the browser reserved a gutter for text the
    shorthands had already made invisible, so a chart that exported flush
    rendered inset. Both sides now answer the same question about the paint."""
    off = {"show": False}
    assert _browser_plot_rect(_chart(x=off, y=off), "axes off")[:3] == (
        0.0,
        float(PADDING[0]),
        float(WIDTH),
    )

    # The right side was the worse case: a flat 54 px reservation that no style
    # zeroing could reach.
    right = _chart(x=off, y={"show": False, "side": "right"})
    assert _browser_plot_rect(right, "right axis off")[2] == float(WIDTH)

    # `show=False, grid=True` keeps the grid and still claims no gutter.
    grid = _chart(x=off, y={"show": False, "grid": True})
    assert _browser_plot_rect(grid, "grid only")[2] == float(WIDTH)


def test_browser_visible_axes_keep_their_room() -> None:
    """The other half of the contract: an axis whose text is drawn reserves the
    room it needs, and the browser agrees with the exporter about how much."""
    chart = _chart()
    browser = _browser_plot_rect(chart, "axes on")
    assert browser[0] > 0 and browser[2] < WIDTH, browser
    export = _svg_plot_rect(chart)
    # The two measure text with different engines, so they are close rather
    # than identical; a whole gutter's worth of difference is the regression.
    assert abs(browser[0] - export[0]) <= 8, (browser, export)
    assert abs(browser[2] - export[2]) <= 8, (browser, export)


def test_browser_and_export_agree_on_every_side() -> None:
    """Parity in all four coordinates, not just the horizontal pair: collapsing
    a gutter in one renderer and not the other is the bug this fixes, and it
    can happen vertically.

    Titled axes join the sweep: the browser used to measure only a title's
    overflow past one line, so a one-line title reserved nothing while the
    exporter fitted it. `test_a_title_reserves_the_band_it_is_drawn_in` covers
    that case directly."""
    off = {"show": False}
    for label, axes in (
        ("both off", {"x": off, "y": off}),
        ("x off, y on", {"x": off, "y": {}}),
        ("x on, y off", {"x": {}, "y": off}),
        ("titled x", {"x": {"label": "Time"}, "y": off}),
        ("titled both", {"x": {"label": "Time"}, "y": {"label": "Value"}}),
        ("right axis off", {"x": off, "y": {"show": False, "side": "right"}}),
        ("grid only", {"x": off, "y": {"show": False, "grid": True}}),
    ):
        chart = xy.line_chart(
            xy.line([0.0, 1.0], [0.0, 1.0]),
            xy.x_axis(**axes["x"]),
            xy.y_axis(**axes["y"]),
            width=WIDTH,
            height=HEIGHT,
            padding=(0, 0, 0, 0),
        )
        _assert_parity(
            f"parity: {label}",
            _browser_plot_rect(chart, f"parity: {label}"),
            _svg_plot_rect(chart),
        )


# The two renderers measure text with different engines, so a coordinate pair
# is "the same" within a few pixels; a whole gutter's worth apart is the
# regression these tests exist for. Never `==`: exact equality holds only while
# the rounding in the helpers above happens to mask a sub-0.05 px difference,
# and it would flake on another font stack or platform.
_PARITY_TOLERANCE_PX = 8.0


def _assert_parity(label: str, browser, export) -> None:
    for axis_name, index in (("x", 0), ("y", 1), ("width", 2), ("height", 3)):
        assert abs(browser[index] - export[index]) <= _PARITY_TOLERANCE_PX, (
            label,
            axis_name,
            browser,
            export,
        )


def _parity_chart(**axes):
    return xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(**axes.get("x", {})),
        xy.y_axis(**axes.get("y", {})),
        width=WIDTH,
        height=HEIGHT,
        padding=(0, 0, 0, 0),
    )


def test_browser_measures_no_band_for_labels_it_will_not_draw() -> None:
    """The gutter eligibility check is not the only place the room is decided.

    The bottom margin takes the *measured* x-axis room directly, so an axis
    that was ruled ineligible could still claim a band through the measuring
    path — `show=False` plus an angle sent every label through rotation layout
    and reserved the extent of text nobody can see. A 45 degree hidden axis
    lost 41.7 px of plot height that the exporter kept."""
    hidden = _parity_chart(x={"show": False, "tick_label_angle": 45}, y={"show": False})
    assert _browser_plot_rect(hidden, "rotated hidden x")[3] == float(HEIGHT)
    assert _svg_plot_rect(hidden)[3] == float(HEIGHT)
    # The same axis with its paint left alone still reserves its rotated band,
    # in both renderers, to within their text-measurement difference.
    shown = _parity_chart(x={"tick_label_angle": 45}, y={"show": False})
    browser = _browser_plot_rect(shown, "rotated visible x")
    export = _svg_plot_rect(shown)
    assert browser[3] < HEIGHT and export[3] < HEIGHT, (browser, export)
    assert abs(browser[3] - export[3]) <= 8, (browser, export)


def test_tick_label_strategy_off_claims_no_gutter() -> None:
    """`off` and `none` both draw no tick label, so both claim no room.

    Only `none` was excluded, so an axis switched off through the strategy kept
    a 25.5 px left inset in the browser that the exporter had already dropped —
    the same divergence as the transparent paint, reached by the other door."""
    off = {"tick_label_strategy": "off"}
    chart = _parity_chart(x=off, y=off)
    assert _browser_plot_rect(chart, "strategy off")[:3] == (0.0, 0.0, float(WIDTH))
    assert _svg_plot_rect(chart)[:3] == (0.0, 0.0, float(WIDTH))
    # A right-side axis reaches the same answer through the flat 42/54 band.
    right = _parity_chart(x={"show": False}, y={**off, "side": "right"})
    assert _browser_plot_rect(right, "right strategy off")[2] == float(WIDTH)
    assert _svg_plot_rect(right)[2] == float(WIDTH)


def test_a_title_answers_to_label_color_alone() -> None:
    """Both renderers paint an axis title from `label_color` and nothing else.

    Reading the title's visibility through a `tick_color` fallback dropped the
    gutter out from under a title that is still drawn: blanking only the tick
    paints left the right-side title with nowhere to sit."""
    titled = _parity_chart(
        x={"show": False},
        y={
            "side": "right",
            "label": "Value",
            "style": {"tick_label_color": "#00000000", "tick_color": "#00000000"},
        },
    )
    assert _browser_plot_rect(titled, "tick paint off, title on")[2] < WIDTH
    assert _svg_plot_rect(titled)[2] < WIDTH
    # `show=False` blanks `label_color` too, so that chart is still flush.
    hidden = _parity_chart(x={"show": False}, y={"show": False, "side": "right", "label": "Value"})
    assert _browser_plot_rect(hidden, "title off")[2] == float(WIDTH)
    assert _svg_plot_rect(hidden)[2] == float(WIDTH)


def test_tick_label_strategy_none_suppresses_the_title_and_its_gutter() -> None:
    """`none` switches the title off too, so it cannot keep the gutter open.

    Crediting a title for gutter eligibility has to ask whether the title is
    actually drawn. Both renderers suppress it under `tick_label_strategy`
    `"none"` (`axis.label && strategy !== "none"` in the two browser title
    branches; `_axis_label_geometry` in the exporter), so counting it there
    reserved 54 px in the browser that nothing was ever drawn into. `"off"` is
    the narrower switch and keeps the title, and its band with it."""
    for side in ("left", "right"):
        hidden = _parity_chart(
            x={"show": False},
            y={"side": side, "label": "Value", "tick_label_strategy": "none"},
        )
        assert _browser_plot_rect(hidden, f"{side}: none + title")[2] == float(WIDTH)
        assert _svg_plot_rect(hidden)[2] == float(WIDTH)

        kept = _parity_chart(
            x={"show": False},
            y={"side": side, "label": "Value", "tick_label_strategy": "off"},
        )
        browser = _browser_plot_rect(kept, f"{side}: off + title")
        export = _svg_plot_rect(kept)
        assert browser[2] < WIDTH and export[2] < WIDTH, (side, browser, export)
        assert abs(browser[2] - export[2]) <= 8, (side, browser, export)


def test_an_inside_title_claims_no_gutter() -> None:
    """A title placed inside the plot is drawn over it and needs no band.

    It is the third condition the gutter asks about, alongside the strategy and
    the paint; `_x_axis_title_room` and `_y_axis_left_room` already skipped it,
    so the browser agreeing is what keeps the two renderers together."""
    blanked_ticks = {"tick_label_color": "#00000000", "tick_color": "#00000000"}
    inside = _parity_chart(
        x={"show": False},
        y={
            "side": "right",
            "label": "Value",
            "label_position": "inside_center",
            "style": blanked_ticks,
        },
    )
    assert _browser_plot_rect(inside, "inside title")[2] == float(WIDTH)
    assert _svg_plot_rect(inside)[2] == float(WIDTH)
    # The same title placed outside does claim the band, so the assertion above
    # is about the position and not about the blanked tick paints.
    outside = _parity_chart(
        x={"show": False},
        y={"side": "right", "label": "Value", "style": blanked_ticks},
    )
    assert _browser_plot_rect(outside, "outside title")[2] < WIDTH
    assert _svg_plot_rect(outside)[2] < WIDTH


def test_off_does_not_zero_the_title_it_still_draws() -> None:
    """The tick-label strategy decides tick-label room, not the title's.

    `"off"` keeps the axis title — that is what separates it from `"none"` —
    but `_xAxisRoom` re-tested the strategy after the eligibility check and
    returned no room at all. The exporter has always measured it
    (`_x_tick_label_room` returns `title_room` for exactly that case), so the
    two renderers disagreed by the whole band.
    """
    wrapped = _WRAPPED_TITLE
    for label, x_axis in (
        ("wrapped", {"tick_label_strategy": "off", "label": wrapped}),
        ("one line", {"tick_label_strategy": "off", "label": "Time"}),
        ("top side", {"tick_label_strategy": "off", "label": "Time", "side": "top"}),
    ):
        chart = _parity_chart(x=x_axis, y={"show": False})
        browser = _browser_plot_rect(chart, f"off + title, {label}")
        assert browser[3] < HEIGHT, (label, browser)
        _assert_parity(f"off + title, {label}", browser, _svg_plot_rect(chart))

    # `none` suppresses the title, so it keeps the full canvas — in both.
    none = _parity_chart(x={"tick_label_strategy": "none", "label": wrapped}, y={"show": False})
    assert _browser_plot_rect(none, "none + wrapped title")[3] == float(HEIGHT)
    assert _svg_plot_rect(none)[3] == float(HEIGHT)

    # Tick-label geometry stays off: a rotation angle on an axis that draws no
    # label claims nothing, in either renderer.
    rotated = _parity_chart(
        x={"tick_label_strategy": "off", "tick_label_angle": 45}, y={"show": False}
    )
    assert _browser_plot_rect(rotated, "off + rotated")[3] == float(HEIGHT)
    assert _svg_plot_rect(rotated)[3] == float(HEIGHT)


_WRAPPED_TITLE = "Trade settlement window\nsecond line\nthird line"


def test_a_title_reserves_the_band_it_is_drawn_in() -> None:
    """The browser measured only a title's overflow past one line, so an
    ordinary one-line title reserved nothing and was drawn at
    `p.y + p.h + 24` — past the canvas edge at a small authored padding, while
    the exporter's `_x_axis_title_room` fitted it. This was not specific to any
    visibility switch: a plain titled axis reproduced it, and it is the gap the
    parity sweep's docstring used to record as known and unfixed."""
    for label, x_axis in (
        ("bottom", {"label": "Time"}),
        ("top", {"label": "Time", "side": "top"}),
        ("wrapped", {"label": _WRAPPED_TITLE}),
        ("offset", {"label": "Time", "label_offset": 12}),
        ("large", {"label": "Time", "style": {"label_size": 22}}),
        # Both renderers place an x title from its line-box top, so extra lines
        # grow toward the plot on the top side and away from it on the bottom.
        # Measuring the block height on both put a three-line top title 41 px
        # further out than the exporter.
        ("top wrapped", {"label": _WRAPPED_TITLE, "side": "top"}),
        (
            "top wrapped, large",
            {
                "label": _WRAPPED_TITLE,
                "side": "top",
                "style": {"label_size": 24},
            },
        ),
        ("top large", {"label": "Time", "side": "top", "style": {"label_size": 28}}),
        (
            "bottom wrapped, large",
            {
                "label": _WRAPPED_TITLE,
                "style": {"label_size": 24},
            },
        ),
    ):
        chart = _parity_chart(x=x_axis, y={"show": False})
        browser = _browser_plot_rect(chart, f"x title: {label}")
        assert browser[3] < HEIGHT, (label, browser)
        _assert_parity(f"x title: {label}", browser, _svg_plot_rect(chart))

    # An `inside_*` title is drawn over the plot and still claims nothing.
    inside = _parity_chart(
        x={"label": "Time", "label_position": "inside_center"}, y={"show": False}
    )
    assert _browser_plot_rect(inside, "inside x title")[3] == float(HEIGHT)
    assert _svg_plot_rect(inside)[3] == float(HEIGHT)


def test_a_collapsed_right_gutter_does_not_push_the_colorbar_out() -> None:
    """The colorbar's right-axis room asks the same question layout does.

    `_colorbar_right_axis_room` carried its own spelling of the predicate, so a
    right axis whose gutter layout had just collapsed still stepped the
    vertical colorbar 54 px outward — a bar floating past a plot that reaches
    the canvas edge. The browser reuses the single `_rightAxisRoom` it computed
    in `_layout`, so only the exporter could drift.
    """
    from xy import _svg

    def bar_x(**axis) -> tuple[float, float]:
        chart = xy.chart(
            xy.heatmap([[0.0, 1.0], [2.0, 3.0]], name="field", colormap="viridis"),
            xy.line([0.0, 1.0], [100.0, 200.0], y_axis="y2"),
            xy.y_axis(id="y2", side="right", domain=(100.0, 200.0), **axis),
            xy.colorbar(title="Field"),
            width=560,
            height=300,
        )
        figure = chart.figure()
        spec, _blob = figure.build_payload()
        *_rest, plot = _svg.layout(spec)
        root = ET.fromstring(figure.to_svg())
        bar = next(
            node for node in root.iter() if (node.get("fill") or "").startswith("url(#xy-colorbar-")
        )
        return float(bar.get("x", "nan")), plot["x"] + plot["w"]

    # A drawn right axis keeps its gutter, and the bar clears the rotated title
    # at plot-right + 40.
    x, plot_right = bar_x(label="Secondary")
    assert x > plot_right + 40, (x, plot_right)

    # Switched off, there is no gutter to clear, so the bar sits against the
    # plot rather than 54 px beyond where the axis used to be.
    off_x, off_plot_right = bar_x(show=True, tick_label_strategy="off")
    assert off_x < off_plot_right + 40, (off_x, off_plot_right)
    # An inside-only title is drawn over the plot and reserves nothing either.
    inside_x, inside_plot_right = bar_x(
        label="Secondary", label_position="inside_center", show=False
    )
    assert inside_x < inside_plot_right + 40, (inside_x, inside_plot_right)


_POLAR_ANGLES = [0, 60, 120, 180, 240, 300]
_POLAR_RADII = [3.0, 4.5, 2.0, 5.0, 3.5, 4.0]
_POLAR_SIZE = 420


def _polar_chart(**axes):
    return xy.polar_chart(
        xy.line(_POLAR_ANGLES, _POLAR_RADII),
        xy.theta_axis(**axes.get("theta", {})),
        xy.r_axis(**axes.get("r", {})),
        width=_POLAR_SIZE,
        height=_POLAR_SIZE,
    )


def test_polar_asks_the_same_question_about_its_text() -> None:
    """The polar recut reads the same visibility rules as the cartesian gutters.

    It derived its inset from the raw strategy string and its title gutters
    from `axis.label` alone, so `show=False` on a polar chart kept the disc
    inset for angular labels nobody could see, and a hidden or `inside_*`
    radial title kept a left gutter in the browser that the exporter had
    already dropped — the renderers disagreeing about the same chart, which is
    the divergence this change exists to close.
    """
    visible = _polar_chart()
    inset = _browser_plot_rect(visible, "polar: labels on")
    _assert_parity("polar: labels on", inset, _svg_plot_rect(visible))
    assert inset[0] > 8, inset

    # Every way of switching the angular labels off reclaims the same inset,
    # and `"off"` is no longer the odd one out beside `"none"`.
    for label, theta in (
        ("show=False", {"show": False}),
        ('strategy "off"', {"tick_label_strategy": "off"}),
        ('strategy "none"', {"tick_label_strategy": "none"}),
    ):
        chart = _polar_chart(theta=theta)
        browser = _browser_plot_rect(chart, f"polar: {label}")
        assert browser[0] < inset[0], (label, browser, inset)
        _assert_parity(f"polar: {label}", browser, _svg_plot_rect(chart))

    # A drawn radial title keeps the left gutter it is placed in; one that is
    # hidden, or drawn inside the disc, does not.
    off = {"show": False}
    titled = _polar_chart(theta=off, r={"label": "Value"})
    titled_rect = _browser_plot_rect(titled, "polar: radial title")
    _assert_parity("polar: radial title", titled_rect, _svg_plot_rect(titled))

    for label, r_axis in (
        ("hidden title", {"label": "Value", "show": False}),
        ("inside title", {"label": "Value", "label_position": "inside_center"}),
    ):
        chart = _polar_chart(theta=off, r=r_axis)
        browser = _browser_plot_rect(chart, f"polar: {label}")
        assert browser[0] < titled_rect[0], (label, browser, titled_rect)
        _assert_parity(f"polar: {label}", browser, _svg_plot_rect(chart))

    # The theta title holds the bottom band the same way, and only while drawn.
    hidden_theta_title = _polar_chart(theta={**off, "label": "Angle"})
    browser = _browser_plot_rect(hidden_theta_title, "polar: hidden theta title")
    _assert_parity("polar: hidden theta title", browser, _svg_plot_rect(hidden_theta_title))


def test_outward_tick_marks_keep_a_gutter_with_no_text_at_all() -> None:
    """Tick marks are chrome of their own, answering to no text paint.

    Gating the gutter on the text alone collapsed it under an axis whose labels
    are switched off but whose `tick_length` still draws marks into it — so the
    marks ran past the canvas edge, and a vertical colorbar beside them kept
    only its 24 px gap and was overlapped by any outward length beyond that.
    """
    from xy import _svg

    long_ticks = {"tick_length": 40, "tick_width": 2, "tick_direction": "out"}

    def right_gutter(**axis) -> float:
        chart = _parity_chart(x={"show": False}, y={"side": "right", **axis})
        browser = _browser_plot_rect(chart, "outward ticks")
        export = _svg_plot_rect(chart)
        _assert_parity("outward ticks", browser, export)
        return WIDTH - browser[2]

    # Labels off, marks on: the band stays, and matches the one the same axis
    # keeps with its labels drawn.
    assert right_gutter(tick_label_strategy="off", style=long_ticks) > 0
    assert right_gutter(tick_label_strategy="off", style=long_ticks) == right_gutter(
        style=long_ticks
    )
    # No authored tick geometry, no marks, no band.
    assert right_gutter(tick_label_strategy="off") == 0
    # Inward marks draw over the plot and need none either.
    assert (
        right_gutter(
            tick_label_strategy="off",
            style={**long_ticks, "tick_direction": "in"},
        )
        == 0
    )
    # `show=False` zeroes the tick geometry, so the sparkline stays flush.
    assert right_gutter(show=True, tick_label_strategy="off", style=long_ticks) > 0
    assert WIDTH - _svg_plot_rect(_parity_chart(x={"show": False}, y={"show": False}))[2] == 0

    # The colorbar clears the marks rather than sitting on them.
    def bar_gap(**axis) -> float:
        chart = xy.chart(
            xy.heatmap([[0.0, 1.0], [2.0, 3.0]], name="field", colormap="viridis"),
            xy.line([0.0, 1.0], [100.0, 200.0], y_axis="y2"),
            xy.y_axis(id="y2", side="right", domain=(100.0, 200.0), **axis),
            xy.colorbar(title="Field"),
            width=560,
            height=300,
        )
        figure = chart.figure()
        spec, _blob = figure.build_payload()
        *_rest, plot = _svg.layout(spec)
        root = ET.fromstring(figure.to_svg())
        bar = next(
            node for node in root.iter() if (node.get("fill") or "").startswith("url(#xy-colorbar-")
        )
        return float(bar.get("x", "nan")) - (plot["x"] + plot["w"])

    assert bar_gap(tick_label_strategy="off", style=long_ticks) > long_ticks["tick_length"]
