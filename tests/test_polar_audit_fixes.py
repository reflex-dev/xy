"""Regressions for the polar/responsive audit round.

One module per audit rather than per subsystem, because each of these is a
*specific* reported failure and the point is that it stays fixed: an unlabelled
mobile colorbar, a clipped Wind Rose title, a legend on top of the disc, four
axis keywords that shipped and were ignored, dates squeezed onto the rim, and a
wedge paying full-turn vertex cost for a 22.5-degree sweep.

Client-only behaviour is pinned against the TypeScript source: these are layout
and teardown rules the browser owns, and the alternative — asserting them only
through a headless WebGL probe — leaves them unpinned wherever the probe is
skipped for want of a browser.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

import xy
from xy import _svg, _textblock, components
from xy._svg import layout
from xy.config import (
    POLAR_BAR_SEGMENTS,
    POLAR_BAR_SEGMENTS_MIN,
    polar_bar_segments,
)

ROOT = Path(__file__).resolve().parents[1]
CHARTVIEW = (ROOT / "js/src/50_chartview.ts").read_text(encoding="utf-8")


def _wind_rose(*children, **props):
    rng = np.random.default_rng(11)
    return xy.wind_rose(
        rng.uniform(0.0, 360.0, 400),
        rng.gamma(2.0, 3.0, 400),
        *children,
        **props,
    )


# -- wedge subdivision ------------------------------------------------------


def test_wedge_subdivision_follows_the_authored_span() -> None:
    """194 vertices for a 22.5-degree sector was the 50k-bar cliff.

    The count is proportional, so the per-segment angle — and therefore the
    chord sagitta the constant is sized against — is unchanged for every span.
    """
    turn = 2.0 * math.pi
    assert polar_bar_segments(turn, turn) == POLAR_BAR_SEGMENTS
    assert polar_bar_segments(turn / 2, turn) == POLAR_BAR_SEGMENTS // 2
    # A 16-sector wind rose: six segments, 14 vertices per bar, not 194.
    assert polar_bar_segments(math.radians(22.5), turn) == 6

    per_segment = [
        math.radians(degrees) / polar_bar_segments(math.radians(degrees), turn)
        for degrees in (360, 180, 90, 45, 22.5)
    ]
    worst = math.radians(360) / POLAR_BAR_SEGMENTS
    assert max(per_segment) <= worst + 1e-12


def test_wedge_subdivision_never_degenerates_or_overpays() -> None:
    turn = 2.0 * math.pi
    for span in (0.0, 1e-9, math.radians(0.5)):
        assert polar_bar_segments(span, turn) == POLAR_BAR_SEGMENTS_MIN
    # Clamped at the full-turn count even for a nonsense span, and a zero turn
    # falls back rather than dividing by it.
    assert polar_bar_segments(10 * turn, turn) == POLAR_BAR_SEGMENTS
    assert polar_bar_segments(1.0, 0.0) == POLAR_BAR_SEGMENTS


def test_client_wedge_subdivision_mirrors_the_python_formula() -> None:
    assert "function xyPolarBarSegments(span, turn)" in CHARTVIEW
    assert "Math.ceil(POLAR_BAR_SEGMENTS * (Math.abs(span) / turn))" in CHARTVIEW
    # Both draw paths must use it: the compact scalar-width path and the
    # four-edge path, which takes the widest span in the trace.
    assert "xyPolarBarSegments(Number(g.width) * barGeom.dirUnit, 2 * Math.PI)" in CHARTVIEW
    assert (
        "xyPolarBarSegments(this._polarRectMaxSpan(g) * rectGeom.dirUnit, 2 * Math.PI)" in CHARTVIEW
    )
    # Cached on the trace, so the count cannot become view-dependent.
    assert "if (g._polarMaxSpan !== undefined) return g._polarMaxSpan;" in CHARTVIEW


def test_flattened_wedge_polygon_shrinks_with_the_span() -> None:
    """The raster twin flattens per wedge, so it pays per wedge."""
    chart = xy.polar_bar_chart(
        xy.bar([0.0, 90.0, 180.0, 270.0], [1.0, 2.0, 3.0, 4.0], width=22.5),
        xy.theta_axis(unit="degrees"),
        width=520,
        height=520,
    )
    spec, blob = chart.figure().build_payload()
    _w, _h, _compact, plot = layout(spec)
    polar = _svg._PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    narrow = _svg.polar_wedge_points(polar, 0.0, 22.5, 0.0, 4.0)
    wide = _svg.polar_wedge_points(polar, 0.0, 360.0, 0.0, 4.0)
    assert 0 < len(narrow) < len(wide)
    # Pinning an explicit count still overrides the per-wedge default.
    pinned = _svg.polar_wedge_points(polar, 0.0, 22.5, 0.0, 4.0, steps=POLAR_BAR_SEGMENTS)
    assert len(pinned) > len(narrow)
    assert blob is not None


# -- radial autorange -------------------------------------------------------


def test_time_radius_autoranges_from_the_data_not_epoch_zero() -> None:
    """Pinning a time radius to r=0 puts 1970 at the centre, so every modern
    instant lands in a hairline ring at the rim."""
    days = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(12)]
    theta = np.linspace(0.0, 300.0, 12)
    spec, _blob = (
        xy.polar_chart(
            xy.line(theta, days),
            xy.theta_axis(unit="degrees"),
        )
        .figure()
        .build_payload()
    )
    lo, hi = spec["y_axis"]["range"]
    assert lo > 0.0, "a time radius must not autorange from epoch zero"
    # The data occupies most of the radius instead of a sliver at the rim.
    first, last = float(spec["y_axis"]["range"][0]), float(spec["y_axis"]["range"][1])
    span = last - first
    data_span = (days[-1] - days[0]).total_seconds() * 1000.0
    assert data_span / span > 0.5

    # A numeric radius keeps the centre origin: this is an exemption, not a
    # change to the default.
    numeric, _blob = (
        xy.polar_chart(xy.line(theta, np.linspace(100.0, 140.0, 12)), xy.theta_axis(unit="degrees"))
        .figure()
        .build_payload()
    )
    assert numeric["y_axis"]["range"][0] == 0.0


def test_radial_margin_is_honoured_instead_of_discarded() -> None:
    """`margin=` asks for exactly the outer pad the centre-origin default drops."""
    values = np.linspace(10.0, 20.0, 8)
    theta = np.linspace(0.0, 300.0, 8)

    def radial_range(**axis):
        spec, _blob = (
            xy.polar_chart(
                xy.line(theta, values),
                xy.theta_axis(unit="degrees"),
                xy.r_axis(**axis),
            )
            .figure()
            .build_payload()
        )
        return spec["y_axis"]["range"]

    default_lo, default_hi = radial_range()
    assert default_lo == 0.0
    assert default_hi == pytest.approx(20.0)

    margin_lo, margin_hi = radial_range(margin=0.2)
    assert margin_lo == 0.0, "the centre origin is not what margin controls"
    assert margin_hi > default_hi


# -- inert axis keywords ----------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"minor_tick_values": [0.5]}, "no minor rings or spokes"),
        ({"tick_label_min_gap": 12.0}, "collision pass"),
        ({"tick_label_anchor": "start"}, "anchors radially"),
        ({"minor_style": {"tick_color": "#f00"}}, "minor_style"),
        ({"tick_label_strategy": "auto"}, "collision pass"),
        ({"tick_label_strategy": "stagger"}, "collision pass"),
    ),
)
@pytest.mark.parametrize("axis", ("theta", "r"))
def test_polar_refuses_axis_options_no_renderer_implements(axis, kwargs, message) -> None:
    """Each of these rode the wire and was dropped by all three renderers, so
    the documented polar axis surface advertised controls that did nothing."""
    factory = xy.theta_axis if axis == "theta" else xy.r_axis
    with pytest.raises(ValueError, match=message):
        factory(**kwargs)


@pytest.mark.parametrize("strategy", ("off", "none"))
@pytest.mark.parametrize("axis", ("theta", "r"))
def test_polar_keeps_the_tick_label_strategies_it_honours(axis, strategy) -> None:
    factory = xy.theta_axis if axis == "theta" else xy.r_axis
    theta = np.linspace(0.0, 300.0, 8)
    values = np.linspace(1.0, 8.0, 8)
    chart = xy.polar_chart(xy.line(theta, values), factory(tick_label_strategy=strategy))
    chart.figure().build_payload_split()


def test_the_pyplot_adapter_drops_what_a_hand_authored_axis_refuses() -> None:
    """`projection="polar"` must keep working: every pyplot Axes carries an
    rcParam-derived `minor_style`, and `minorticks_on()`/`ha=` add more. Refusing
    a default nobody asked for would turn the whole projection into an error, so
    the adapter drops instead — which is what the renderers already do.
    """
    props = {
        "minor_style": {"tick_color": "#f00"},
        "minor_tick_values": [0.5],
        "tick_label_anchor": "start",
        "tick_label_min_gap": 12.0,
        "tick_label_strategy": "preserve",
        "theta_unit": "degrees",
        "label": "bearing",
    }
    stripped = components._polar_axis_kwargs(props)
    assert stripped == {"theta_unit": "degrees", "label": "bearing"}
    # `off`/`none` survive the strip, because polar honours them.
    assert components._polar_axis_kwargs({"tick_label_strategy": "none"}) == {
        "tick_label_strategy": "none"
    }


def test_cartesian_axes_keep_every_refused_keyword() -> None:
    """The refusals are polar-only; nothing about a Cartesian axis changed."""
    chart = xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]),
        xy.x_axis(minor_tick_values=[0.5, 1.5], tick_label_min_gap=12.0),
        xy.y_axis(tick_label_anchor="start", tick_label_strategy="stagger"),
    )
    chart.figure().build_payload_split()


def test_polar_axes_keep_every_keyword_they_do_honour() -> None:
    """The refusal must not have caught anything that works."""
    xy.theta_axis(
        unit="degrees",
        zero="N",
        direction="clockwise",
        sector=(0.0, 270.0),
        grid_shape="linear",
        label="bearing",
        format=".0f°",
        tick_values=[0.0, 90.0, 180.0],
        tick_labels=["N", "E", "S"],
        tick_count=4,
        tick_label_angle=15.0,
        style={"grid_color": "#eee"},
    )
    xy.r_axis(
        hole=0.3,
        label="speed",
        type_="log",
        domain=(1.0, 100.0),
        reverse=True,
        margin=0.1,
        tick_label_angle=15.0,
    )


def test_authored_theta_format_wins_over_the_angular_default() -> None:
    """`format=` shipped on the wire and was then overwritten by the built-in
    degree text in every renderer."""
    axis = {"theta_unit": "degrees", "format": ".0f°", "kind": "linear"}
    assert _svg._fmt_axis(axis, 90.0, 45.0) == "90°"
    # Without a format the angular default still applies.
    assert "deg" not in _svg._fmt_axis({"theta_unit": "degrees", "kind": "linear"}, 90.0, 45.0)
    # And the client checks the authored spec before the angular branch.
    ticks = (ROOT / "js/src/30_ticks.ts").read_text(encoding="utf-8")
    assert "const authored = fmtNumberSpec(v, axis.format);" in ticks
    assert "return authored || fmtAngle(v, axis.theta_unit, tickStep);" in ticks


# -- zero-size wedges -------------------------------------------------------


def test_a_zero_width_wedge_draws_nothing_instead_of_raising() -> None:
    """0% is a data state: a progress ring at zero, an empty aggregated
    category, the first frame of a grow animation."""
    chart = xy.polar_bar_chart(
        xy.bar([0.0], [1.0], base=0.6, width=0.0),
        xy.theta_axis(unit="degrees"),
        xy.r_axis(domain=(0.0, 1.0)),
    )
    spec, _blob = chart.figure().build_payload()
    assert spec["traces"]

    # The hand-rolled gauge recipe, swept from 0% to 100%.
    for percent in (0, 1, 50, 100):
        xy.polar_bar_chart(
            xy.bar([percent * 3.6 / 2.0], [1.0], base=0.7, width=percent * 3.6),
            xy.theta_axis(unit="degrees", zero="N", direction="clockwise"),
            xy.r_axis(domain=(0.0, 1.0)),
        ).figure().build_payload()

    # `pie_chart` reaches 0% too, and drops the row rather than showing a
    # swatch that highlights nothing.
    spec, _blob = xy.pie_chart(["done", "left"], [0.0, 8.0]).figure().build_payload()
    assert len([t for t in spec["traces"] if t.get("name")]) == 1


@pytest.mark.parametrize("width", (-1.0, float("nan"), float("inf")))
def test_meaningless_bar_widths_are_still_refused(width) -> None:
    with pytest.raises(ValueError, match="width"):
        xy.bar_chart(xy.bar(["a"], [1.0], width=width)).figure().build_payload()


# -- title wrapping ---------------------------------------------------------


def test_wrapped_titles_reserve_the_lines_they_occupy() -> None:
    long_title = "Wind rose — Fastnet Rock lighthouse, hourly observations 2024"
    narrow = xy.polar_chart(
        xy.line([0.0, 90.0, 180.0], [1.0, 2.0, 3.0]),
        xy.theta_axis(unit="degrees"),
        title=long_title,
        width=380,
        height=460,
    )
    spec, _blob = narrow.figure().build_payload()
    _w, _h, compact, plot = layout(spec)
    assert compact

    wrap_width = plot["title_wrap_width"]
    block = _textblock.measure(long_title, 14.0, max_width=wrap_width)
    assert block.line_count > 1, "this title must wrap at a phone width"
    # The reserved band holds the whole wrapped block, not one line of it.
    assert plot["title_room"] >= block.height


def test_single_line_titles_reserve_exactly_what_they_did() -> None:
    """The wrap rule must not move any chart whose title already fitted."""
    chart = xy.line_chart(xy.line([0.0, 1.0], [0.0, 1.0]), title="Latency", width=900, height=420)
    spec, _blob = chart.figure().build_payload()
    _w, _h, compact, plot = layout(spec)
    assert not compact
    block = _textblock.measure("Latency", 14.0, max_width=plot["title_wrap_width"])
    assert block.line_count == 1
    assert plot["title_room"] == pytest.approx(30.0)


def test_wrap_only_breaks_at_spaces_and_keeps_authored_newlines() -> None:
    # An authored newline is a hard break: "delta" cannot join the line above it
    # even though it would fit there.
    lines = _textblock.wrap_lines(("alpha beta gamma", "delta"), 14.0, 60.0)
    assert lines[-1] == "delta"
    # Every multi-word line fits the limit.
    assert all(
        len(line.split()) == 1 or _textblock.measure(line, 14.0).width <= 60.0 for line in lines
    )
    # A single word wider than the limit keeps its own line and overflows,
    # which is what a browser does without an explicit overflow-wrap.
    assert _textblock.wrap_lines(("unbreakablesupercalifragilistic",), 14.0, 10.0) == (
        "unbreakablesupercalifragilistic",
    )


def test_client_caps_the_title_box_at_the_measured_wrap_width() -> None:
    assert (
        "this._titleWrapWidth = Math.max(40, this.size.w - authoredLeft - baseRight);" in CHARTVIEW
    )
    assert "entry.text, titleFontSize, this._titleWrapWidth," in CHARTVIEW
    assert "title.style.maxWidth = " in CHARTVIEW
    assert "function xyWrapLines(lines, advance, maxWidth)" in CHARTVIEW


# -- legend overflow --------------------------------------------------------


def test_a_long_legend_row_wraps_instead_of_scrolling_sideways() -> None:
    """A pie legend grew a horizontal scrollbar, hiding the label it was showing.

    The box is capped at `--xy-legend-max-width`, but its grid columns were
    `max-content` — they refused to shrink — so an over-wide row overflowed and
    `overflow:auto` answered with a sideways scrollbar. Shrinkable columns let the
    label wrap inside its column instead, so nothing needs to scroll sideways and
    no text is dropped. Block-axis scrolling stays: it is what the browser legend
    has over the static exporters, which can only ellipsize.

    The row deliberately stays a BLOCK, not a flex line. A flex container
    blockifies its children's computed `display`, which would turn an author's
    `inline-flex` swatch utility into `flex`
    (`test_tailwind_root_customization.py`), and a nowrap label removes the very
    wrapping that keeps a narrow chart's legend scrollable rather than clipped
    (`test_legend_resize_regression.py`). The swatch keeps aligning through the
    `vertical-align` it already carries.
    """
    # Columns that can shrink, and no horizontal scroll axis.
    assert "minmax(0,max-content)" in CHARTVIEW
    assert "overflow-x:hidden;overflow-y:auto;" in CHARTVIEW
    theme = (ROOT / "js/src/20_theme.ts").read_text(encoding="utf-8")
    assert 'data-xy-slot="legend_item"]){' not in theme
    assert 'data-xy-slot="legend_label"]){' not in theme
    assert 'data-xy-slot="legend_swatch"]){display:inline-block;width:' in theme
    # Clipping must never make text unreachable: same full-text-in-title/ARIA
    # rule the categorical tick labels use.
    assert "row.title = String(it.name);" in CHARTVIEW
    assert 'row.setAttribute("aria-label", String(it.name));' in CHARTVIEW


# -- polar legend gutter ----------------------------------------------------


def test_a_polar_legend_gets_a_gutter_beside_the_disc() -> None:
    spec, _blob = _wind_rose(width=720, height=520).figure().build_payload()
    _w, _h, compact, plot = layout(spec)
    assert not compact
    assert "legend_box_w" in plot, "a polar legend must reserve its own box"
    # The box is outside the plot rect, on the right, and the disc no longer
    # reaches into it.
    assert plot["legend_box_x"] >= plot["x"] + plot["w"]
    assert plot["legend_box_w"] == pytest.approx(_svg._polar_legend_room(720))


def test_a_compact_polar_legend_takes_a_band_under_the_disc() -> None:
    spec, _blob = _wind_rose(width=380, height=520).figure().build_payload()
    _w, _h, compact, plot = layout(spec)
    assert compact
    assert plot["legend_box_h"] == pytest.approx(_svg._POLAR_LEGEND_BAND)
    assert plot["legend_box_y"] >= plot["y"] + plot["h"]


def test_the_static_legend_places_itself_in_the_polar_gutter() -> None:
    spec, _blob = _wind_rose(width=720, height=520).figure().build_payload()
    _w, _h, _compact, plot = layout(spec)
    named = _svg.legend_items(spec["traces"])
    assert named
    placed = _svg._legend_layout(named, plot, spec.get("legend") or {})
    assert placed["x"] >= plot["x"] + plot["w"], "the legend must clear the disc"


def test_the_legend_clip_covers_the_polar_gutter() -> None:
    """Bounding a legend to the plot rect erases one that sits beside the disc.

    Both exporters clip their legend so an oversized one ellipsizes instead of
    escaping the file, and both read this rect — the raster kept clipping to the
    plot alone and dropped every polar legend from the PNG while the SVG kept
    its own.
    """
    spec, _blob = _wind_rose(width=720, height=520).figure().build_payload()
    _w, _h, _compact, plot = layout(spec)
    x, y, w, h = _svg.legend_clip_rect(plot)
    assert (x, y) == (plot["x"], plot["y"])
    assert x + w >= plot["legend_box_x"] + plot["legend_box_w"]
    assert y + h >= plot["legend_box_y"] + plot["legend_box_h"]
    # Union, not replacement: in-plot chrome is still bounded by the plot rect.
    assert w >= plot["w"] and h >= plot["h"]


def test_a_cartesian_legend_clip_is_still_the_plot_rect() -> None:
    spec, _blob = (
        xy.line_chart(xy.line([0.0, 1.0], [0.0, 1.0], name="a"), xy.legend())
        .figure()
        .build_payload()
    )
    _w, _h, _compact, plot = layout(spec)
    assert _svg.legend_clip_rect(plot) == (plot["x"], plot["y"], plot["w"], plot["h"])


def test_the_native_png_carries_the_polar_legend() -> None:
    """The pixels, not just the rect: the swatch has to survive the clip."""
    from test_png_export import _decode_rgba

    chart = xy.polar_chart(
        xy.scatter([45.0], [1.0], color="#0f766e", size=12.0, name="one"),
        width=520,
        height=520,
    )
    figure = chart.figure()
    spec, _blob = figure.build_payload()
    _w, _h, _compact, plot = layout(spec)
    assert "legend_box_w" in plot
    # scale=1 so PNG pixels are in the same units as the layout rect.
    pixels = _decode_rgba(figure.to_image(format="png", scale=1))
    box = pixels[
        int(plot["legend_box_y"]) : int(plot["legend_box_y"] + plot["legend_box_h"]),
        int(plot["legend_box_x"]) : int(plot["legend_box_x"] + plot["legend_box_w"]),
        :3,
    ]
    target = np.array([0x0F, 0x76, 0x6E], dtype=np.int16)
    swatch = np.all(np.abs(box.astype(np.int16) - target) <= 24, axis=2)
    assert int(swatch.sum()) >= 10, "the raster clipped the polar legend swatch away"


def test_an_authored_anchor_reserves_no_polar_gutter() -> None:
    """An anchor is an explicit plot-relative placement the author owns;
    relocating it would be the same class of bug as ignoring a keyword."""
    spec, _blob = (
        _wind_rose(xy.legend(anchor=(0.9, 0.9)), width=720, height=520).figure().build_payload()
    )
    _w, _h, _compact, plot = layout(spec)
    assert "legend_box_w" not in plot


def test_authored_padding_reserves_no_polar_gutter() -> None:
    """A four-tuple `padding` already states the box the plot should occupy, and
    is the documented way to hand-reserve a caption band under a donut."""
    spec, _blob = (
        _wind_rose(width=720, height=520, padding=(20, 20, 140, 20)).figure().build_payload()
    )
    _w, _h, _compact, plot = layout(spec)
    assert "legend_box_w" not in plot


def test_a_cartesian_legend_still_overlays_its_plot() -> None:
    spec, _blob = (
        xy.line_chart(
            xy.line([0.0, 1.0], [0.0, 1.0], name="a"),
            xy.legend(),
            width=720,
            height=420,
        )
        .figure()
        .build_payload()
    )
    _w, _h, _compact, plot = layout(spec)
    assert "legend_box_w" not in plot


def test_client_legend_places_in_the_reserved_box() -> None:
    assert "_polarLegendReserve(compact)" in CHARTVIEW
    assert "function xyPolarLegendRoom(width)" in CHARTVIEW
    assert "const POLAR_LEGEND_ROOM_FRACTION = 0.22;" in CHARTVIEW
    assert "room: xyPolarLegendRoom(this.size.w)," in CHARTVIEW
    assert "const POLAR_LEGEND_BAND = 64;" in CHARTVIEW
    # Placement and the responsive max-width both read the legend box, and an
    # authored anchor still resolves against the plot.
    assert "const plot = anchor ? this.plot : (this._legendRect || this.plot);" in CHARTVIEW
    assert "const lb = this._legendRect || p;" in CHARTVIEW


# -- compact colorbar -------------------------------------------------------


def test_compact_colorbars_keep_their_endpoint_labels() -> None:
    """Hiding every tick left a gradient with no numbers on it.

    The two extremes survive, restacked above and below the gradient. Beside the
    bar they would need a gutter wide enough for `0.25`, which costs 36 px of the
    plot width the compact collapse exists to protect; centred on the 18 px bar
    they fit in the gap already reserved, so the fix is free.
    """
    assert (
        "const endpoint = !Number.isFinite(fraction) "
        "|| fraction === lowest || fraction === highest;" in CHARTVIEW
    )
    assert "node.hidden = compactVertical && !endpoint;" in CHARTVIEW
    # Restacked, and the beside-the-bar placement is restored on the way out.
    assert "tick._xyBesideCss = tick.style.cssText;" in CHARTVIEW
    assert "node.style.cssText = node._xyBesideCss;" in CHARTVIEW
    assert "const COMPACT_COLORBAR_LABEL_GAP = 3;" in CHARTVIEW
    # The reservation is unchanged, which is what keeps the plot space the
    # collapse was collapsing for.
    assert "COMPACT_COLORBAR_GAP + COLORBAR_THICKNESS + 8" in CHARTVIEW
    # The rotated title and the text-free minor ticks are what a phone cannot
    # spend; `box.title` keeps the scale name reachable.
    assert "'[data-xy-slot=\"colorbar_title\"], [data-xy-colorbar-minor]'" in CHARTVIEW


# -- dpr-baked buffers and animation cadence --------------------------------


def test_a_dpr_change_rescales_the_buffers_baked_in_device_pixels() -> None:
    assert "_rescaleDprBakedBuffers()" in CHARTVIEW
    # Widths ride component 2 of the style row; radii are their own buffer.
    assert "for (let i = 2; i < style.length; i += 4) style[i] *= factor;" in CHARTVIEW
    assert "g._cpuRadius = values;" in CHARTVIEW
    # Run before the layout/paint of the same frame.
    assert "this._rescaleDprBakedBuffers();\n    this._layout();" in CHARTVIEW


def test_the_dpr_rescale_defers_to_the_append_rebuild_on_a_short_mirror() -> None:
    """The rescale re-uploads whole buffers from `_cpuStyle`/`_cpuRadius`, but the
    streaming-append fast path extends `styleBuf` with a tail `bufferSubData` and
    advances `n` without growing those mirrors (54_kernel.ts). Re-uploading a short
    mirror would shrink the store out from under the appended rows, and scaling it
    would leave that tail at the old dpr regardless. Leaving `_styleDpr` stale
    hands the repair back to the append guard's rebuild — the fallback
    `scripts/append_stream_smoke.py` asserts via `dprChangeRebuilds`.
    """
    assert "const rows = Number(record.n);" in CHARTVIEW
    assert "if (record._cpuStyle && record._cpuStyle.length !== rows * 4) return;" in CHARTVIEW
    assert "if (record._cpuRadius && record._cpuRadius.length !== rows * 2) return;" in CHARTVIEW
    # The guard the fallback runs through must stay in place.
    kernel = (ROOT / "js/src/54_kernel.ts").read_text(encoding="utf-8")
    assert "if (g.styleBuf && g._styleDpr !== this.dpr) return false;" in kernel


def test_a_dpr_change_stays_synchronous() -> None:
    """`render_smoke_nonumpy.py`'s `dprw` probe calls `_onDprChange()` and reads
    `dpr`/`canvas.width`/`chrome.width` on the next line: a DPR change with no
    container resize has no later event to piggyback on. Deferring it into
    `_queueResize` would read a stale `dpr` there, and it saved nothing anyway —
    the ResizeObserver's queued pass already early-returns when width, height
    and dpr are all unchanged, so the redundant second frame it was meant to
    avoid does not exist.
    """
    assert "this._resize(this.size.w, this.size.h); // re-reads devicePixelRatio" in CHARTVIEW
    assert (
        "this._queueResize(this.size.w, this.size.h, this.fluid || this.fluidH);" not in CHARTVIEW
    )


def test_data_animations_throttle_the_label_dom_rebuild() -> None:
    animation = (ROOT / "js/src/56_animation.ts").read_text(encoding="utf-8")
    assert "const labelCadenceMs = (this._viewAnim || this._dataAnim) ? 80 : 0;" in CHARTVIEW
    # And the settled labels always land when the transition ends.
    assert "this._lastLabelDraw = null;" in animation


def test_categorical_theta_labels_widen_the_disc_gutter() -> None:
    """A category axis carries its names in `categories`, not `tick_labels`.

    `_polar_label_room` measured only `tick_labels`, so a categorical angular
    axis fell back to the uniform default and long names spilled over the disc.
    `radar_chart` hid this because it authors `tick_labels` explicitly.
    """
    names = ["EAST-NORTH-EAST", "SOUTH-SOUTH-WEST", "WEST-NORTH-WEST", "NORTH-NORTH-EAST"]
    chart = xy.polar_bar_chart(xy.bar(names, [3.0, 5.0, 2.0, 4.0]), width=460, height=440)
    spec, _blob = chart.figure().build_payload_split()
    theta_axis = spec["x_axis"]
    assert theta_axis["kind"] == "category"
    assert theta_axis.get("tick_labels") is None, "guard: names must ride `categories`"
    assert _svg._polar_label_room(theta_axis) > _svg._POLAR_LABEL_ROOM

    # And the client measures the same source.
    assert 'axis.kind === "category" ? axis.categories : null' in CHARTVIEW


def test_hiding_angular_labels_keeps_the_legend_gutter() -> None:
    """`tick_label_strategy="none"` removes the LABEL inset, not the recut.

    The early return skipped `_polar_legend_reserve` outright, so the legend
    fell back to the plain plot rect and drew over the marks — and the disc
    kept the cartesian gutters it should have given back.
    """
    theta = np.linspace(0.0, 2.0 * math.pi, 60)
    chart = xy.polar_chart(
        xy.line(theta, np.ones(60), name="series one"),
        xy.theta_axis(tick_label_strategy="none"),
        width=460,
        height=420,
    )
    spec, _blob = chart.figure().build_payload_split()
    _w, _h, _compact, plot = _svg.layout(spec)
    assert "legend_box_w" in plot, "legend gutter was dropped with the label inset"
    assert plot["legend_box_w"] > 0

    # The recut still ran: the cartesian left gutter is given back.
    cartesian = xy.line_chart(xy.line(theta, np.ones(60)), width=460, height=420)
    cart_spec, _ = cartesian.figure().build_payload_split()
    _cw, _ch, _cc, cart_plot = _svg.layout(cart_spec)
    assert plot["x"] < cart_plot["x"]

    # The client tracks the same flag rather than returning early.
    assert 'const labelsHidden = this._axisTickLabelStrategy(xAxisSpec) === "none";' in CHARTVIEW
    assert "labelsHidden ? 0 : this._polarLabelRoom(xAxisSpec)" in CHARTVIEW


def test_horizontal_bars_are_refused_under_polar() -> None:
    """A polar bar's position IS its angle and its value IS its radius.

    `orientation="horizontal"` swaps those roles, which a disc has no meaning
    for — every renderer reads `pos` as theta regardless, so the bar came out
    transposed rather than rotated. `POLAR_MARK_KINDS` admits `bar`, so nothing
    else was catching it.
    """
    angles = np.arange(4.0)
    values = np.arange(1.0, 5.0)
    with pytest.raises(ValueError, match="does not support bar orientation='horizontal'"):
        xy.polar_bar_chart(xy.bar(angles, values, orientation="horizontal")).figure()

    # Vertical polar bars and cartesian horizontal bars are both untouched.
    spec, _blob = xy.polar_bar_chart(xy.bar(angles, values)).figure().build_payload_split()
    assert spec["traces"][0]["bar"]["orientation"] == "vertical"
    cartesian = xy.bar_chart(xy.bar(["a", "b"], [1.0, 2.0], orientation="horizontal"))
    cart_spec, _ = cartesian.figure().build_payload_split()
    assert cart_spec["traces"][0]["bar"]["orientation"] == "horizontal"
