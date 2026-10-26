"""Polar charts end to end: wire shape, refusals, and cross-renderer agreement.

The transform itself is pinned by `test_polar_transform.py` against shared
fixtures. This file checks that each renderer actually *uses* it — the failure
mode two export-parity audits have already found in this repo is a renderer
quietly keeping its own geometry while the others move.
"""

from __future__ import annotations

import math
import re
import typing
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

import xy
from xy import components
from xy._svg import _PolarProjection, axis_ticks, layout, minor_axis_ticks
from xy.config import POLAR_DIRECT_CEILING

ROOT = Path(__file__).resolve().parent.parent


def _rose(n: int = 120):
    theta = np.linspace(0.0, 2.0 * math.pi, n)
    return theta, 1.0 + 0.5 * np.sin(5.0 * theta)


def _chart(**kwargs):
    theta, r = _rose()
    children = kwargs.pop("children", None) or [xy.line(theta, r, color="#2563eb", width=2.0)]
    return xy.polar_chart(*children, width=520, height=520, **kwargs)


# -- wire ------------------------------------------------------------------


def test_polar_spec_carries_coords_and_angular_descriptors() -> None:
    spec, _ = _chart(children=[xy.line(*_rose())]).figure().build_payload_split()
    assert spec["coords"] == "polar"
    assert spec["x_axis"]["theta_unit"] == "radians"
    assert spec["x_axis"]["theta_zero"] == "E"
    assert spec["x_axis"]["theta_direction"] == "counterclockwise"


def test_cartesian_spec_omits_coords_entirely() -> None:
    """Existing specs must stay byte-identical when polar is not in play."""
    spec, _ = xy.line_chart(xy.line([0, 1], [0, 1])).figure().build_payload_split()
    assert "coords" not in spec
    assert "theta_unit" not in spec["x_axis"]


def test_theta_axis_options_reach_the_wire() -> None:
    chart = _chart(
        children=[xy.line(*_rose()), xy.theta_axis(unit="degrees", zero="N", direction="clockwise")]
    )
    spec, _ = chart.figure().build_payload_split()
    assert spec["x_axis"]["theta_unit"] == "degrees"
    assert spec["x_axis"]["theta_zero"] == "N"
    assert spec["x_axis"]["theta_direction"] == "clockwise"


# -- ranges ----------------------------------------------------------------


def test_radial_axis_starts_at_the_centre() -> None:
    """A radial axis padded away from zero puts the smallest datum at the
    centre and makes a 5%-variation series look like it radiates from nothing.
    Matplotlib pins rmin=0 for the same reason."""
    spec, _ = _chart().figure().build_payload_split()
    assert spec["y_axis"]["range"][0] == 0.0


def test_explicit_radial_domain_still_wins() -> None:
    chart = _chart(children=[xy.line(*_rose()), xy.r_axis(domain=(0.5, 2.0))])
    spec, _ = chart.figure().build_payload_split()
    assert spec["y_axis"]["range"] == [0.5, 2.0]


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("radians", 2.0 * math.pi), ("degrees", 360.0)],
)
def test_angular_axis_spans_a_full_turn(unit: str, expected: float) -> None:
    """Theta is used directly as an angle, never rescaled into the axis range,
    so autoscaling it to the data would put spokes at arbitrary angles."""
    theta, r = _rose()
    if unit == "degrees":
        theta = np.degrees(theta)
    chart = _chart(children=[xy.line(theta, r), xy.theta_axis(unit=unit)])
    spec, _ = chart.figure().build_payload_split()
    assert spec["x_axis"]["range"] == pytest.approx([0.0, expected])


# -- refusals --------------------------------------------------------------


@pytest.mark.parametrize("mark", ["histogram", "box", "hexbin"])
def test_unsupported_marks_are_refused_not_approximated(mark: str) -> None:
    """These kinds expand geometry in pixel space after the coordinate map, so
    under polar they draw chord-edged shapes where arcs belong. A plausible
    wrong picture is worse than an error (dossier §28)."""
    builders = {
        "histogram": lambda: xy.hist(np.array([1.0, 2.0, 3.0])),
        "box": lambda: xy.box(np.array([1.0, 2.0, 3.0, 4.0])),
        "hexbin": lambda: xy.hexbin(np.array([1.0, 2.0]), np.array([1.0, 2.0])),
    }
    chart = xy.polar_chart(builders[mark]())
    with pytest.raises(ValueError, match=r"coords='polar' does not support"):
        chart.figure().build_payload_split()


def test_refusal_names_the_supported_set() -> None:
    with pytest.raises(ValueError) as excinfo:
        xy.polar_chart(xy.hist(np.array([1.0, 2.0]))).figure().build_payload_split()
    message = str(excinfo.value)
    for supported in ("area", "bar", "column", "line", "scatter"):
        assert repr(supported) in message


def test_polar_forces_direct_tier() -> None:
    """M4 buckets on a monotonic screen-x column and density bins an
    axis-aligned grid; neither survives the polar transform."""
    from xy.config import DECIMATION_THRESHOLD

    theta = np.linspace(0.0, 2.0 * math.pi, DECIMATION_THRESHOLD * 2)
    spec, _ = _chart(children=[xy.line(theta, np.sin(theta) + 2.0)]).figure().build_payload_split()
    assert spec["traces"][0]["tier"] == "direct"


def test_theta_options_rejected_on_the_radial_axis() -> None:
    with pytest.raises(ValueError, match="belong on an x axis"):
        xy.polar_chart(xy.line(*_rose())).figure().set_axis("y", theta_unit="degrees")


# -- renderers -------------------------------------------------------------


def _svg(chart) -> str:
    return chart.figure().to_image(format="svg").decode()


def test_svg_draws_rings_spokes_and_one_outer_frame() -> None:
    doc = _svg(_chart())
    assert doc.count('data-xy-grid="ring"') >= 3
    assert doc.count('data-xy-grid="spoke"') >= 3
    assert doc.count('data-xy-frame="polar"') == 1


def test_svg_clips_marks_to_the_disc_but_not_the_legend() -> None:
    """Two clip paths, deliberately.

    The rect clip also bounds every legend, so reusing one disc clip for both
    made a legend sitting outside the circle vanish from the SVG while the
    raster still drew it.
    """
    doc = _svg(_chart())
    clips = re.findall(r"<clipPath[^>]*>(.*?)</clipPath>", doc, re.S)
    assert any("<circle" in c for c in clips), "marks need a disc clip"
    assert any("<rect" in c for c in clips), "the legend still needs a rect clip"


def test_polar_legend_survives_the_disc_clip() -> None:
    theta, r = _rose()
    doc = _svg(_chart(children=[xy.line(theta, r, name="series one")]))
    assert "series one" in doc


def test_svg_angular_labels_use_pi_notation() -> None:
    doc = _svg(_chart())
    assert "π/2" in doc or "π" in doc


def test_svg_degree_labels_carry_the_degree_sign() -> None:
    theta, r = _rose()
    doc = _svg(_chart(children=[xy.line(np.degrees(theta), r), xy.theta_axis(unit="degrees")]))
    assert "°" in doc


def test_svg_line_geometry_matches_the_shared_projection() -> None:
    """The rendered path must be the projection's output, not a lookalike."""
    theta, r = _rose(16)
    chart = xy.polar_chart(xy.line(theta, r), width=520, height=520)
    fig = chart.figure()
    spec, blob = fig.build_payload_split()
    _w, _h, _compact, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    want_x, want_y = project(theta, r)

    doc = _svg(chart)
    path = re.search(r'<path d="M ([^"]+)"', doc)
    assert path is not None
    numbers = [float(v) for v in re.findall(r"-?\d+\.?\d*", path.group(1))]
    got_x, got_y = numbers[0], numbers[1]
    # Payload geometry is offset-encoded f32, so allow a little slack.
    assert got_x == pytest.approx(float(want_x[0]), abs=0.05)
    assert got_y == pytest.approx(float(want_y[0]), abs=0.05)


def test_raster_and_svg_agree_on_where_the_data_lands() -> None:
    """Cross-renderer check: the PNG must have ink where the projection says,
    and none at the cartesian location the same columns would produce.

    This is the check that catches an exporter silently keeping its own
    geometry — the failure two export-parity audits found in this repo.
    """
    # Constant r once autoranged to a padded band; it now centre-origins
    # (constant-radius singleton fix), which would park these marks exactly on
    # the outer ring and under the frame stroke. An explicit domain keeps them
    # mid-disc so the negative probe below samples genuinely empty canvas.
    theta = np.array([0.0, math.pi / 2, math.pi])
    r = np.array([1.0, 1.0, 1.0])
    chart = xy.polar_chart(
        xy.scatter(theta, r, size=9.0, color="#000000"),
        xy.r_axis(domain=(0.0, 2.0)),
        width=400,
        height=400,
    )
    fig = chart.figure()
    spec, _blob = fig.build_payload_split()
    _w, _h, _compact, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    px, py = project(theta, r)

    from test_png_export import _decode_rgba

    # scale=1 so PNG pixels are in the same units as the layout rect.
    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    height, width, _ = pixels.shape

    def darkest_near(x: float, y: float) -> int:
        ix, iy = int(round(x)), int(round(y))
        assert 0 <= ix < width and 0 <= iy < height, f"({ix},{iy}) outside {width}x{height}"
        window = pixels[
            max(0, iy - 3) : min(height, iy + 4), max(0, ix - 3) : min(width, ix + 4), 0
        ]
        return int(window.min())

    for i in range(len(theta)):
        assert darkest_near(float(px[i]), float(py[i])) < 128, (
            f"raster has no ink at the projected position of point {i}"
        )

    # And nothing where a cartesian reading of the same columns would land.
    # theta=pi, r=1 would sit far right on an x axis spanning [0, 2pi]; under
    # polar it belongs on the left. If this fires, the raster path ignored
    # `coords` and drew the columns as x/y.
    from xy._svg import _Scale

    cart_x = _Scale(spec["x_axis"], plot["x"], plot["x"] + plot["w"])(math.pi)
    cart_y = _Scale(spec["y_axis"], plot["y"] + plot["h"], plot["y"])(1.0)
    assert darkest_near(float(cart_x), float(cart_y)) >= 128, (
        "raster drew a mark at the cartesian position — it ignored coords='polar'"
    )


# -- area and radar (P3) ---------------------------------------------------


def test_area_renders_under_polar() -> None:
    theta, r = _rose(24)
    doc = _svg(_chart(children=[xy.area(theta, r, color="#2563eb")]))
    assert "<path" in doc and "fill-opacity" in doc


def test_radar_chart_closes_across_the_seam() -> None:
    """Closing with the first *angle* would sweep the final segment backwards
    through the whole circle; the closing sample sits at a full turn instead."""
    chart = xy.radar_chart(["a", "b", "c", "d"], xy.area([1.0, 2.0, 3.0, 4.0]))
    mark = next(c for c in chart.children if getattr(c, "kind", None) == "area")
    assert mark.x[-1] == pytest.approx(2.0 * math.pi)
    assert mark.x[0] == pytest.approx(0.0)
    assert mark.y[-1] == mark.y[0] == pytest.approx(1.0)


def test_radar_chart_labels_spokes_with_the_categories() -> None:
    cats = ["speed", "power", "range", "agility"]
    doc = xy.radar_chart(cats, xy.area([0.9, 0.7, 0.5, 0.8])).figure().to_image(format="svg")
    text = doc.decode()
    for name in cats:
        assert name in text


def test_radar_chart_authored_theta_axis_wins() -> None:
    chart = xy.radar_chart(["a", "b", "c"], xy.area([1.0, 2.0, 3.0]), xy.theta_axis(label="custom"))
    axes = [c for c in chart.children if isinstance(c, xy.Axis) and c.which == "x"]
    assert len(axes) == 1 and axes[0].label == "custom"


def test_radar_chart_rejects_a_value_count_mismatch() -> None:
    with pytest.raises(ValueError, match="but there are 4 categories"):
        xy.radar_chart(["a", "b", "c", "d"], xy.area([1.0, 2.0]))


def test_radar_chart_needs_three_categories() -> None:
    with pytest.raises(ValueError, match="at least 3 categories"):
        xy.radar_chart(["a", "b"], xy.area([1.0, 2.0]))


def test_authored_tick_labels_beat_the_angle_format() -> None:
    """Radar category names must win over pi notation on the theta axis."""
    doc = _svg(
        _chart(
            children=[
                xy.line(*_rose()),
                xy.theta_axis(tick_values=[0.0, math.pi], tick_labels=["north", "south"]),
            ]
        )
    )
    assert "north" in doc and "south" in doc


# -- bars and wind rose (P4) -----------------------------------------------


def test_polar_bars_render_as_wedge_paths_in_svg() -> None:
    """A polar bar is an annular sector: SVG expresses the arcs with `A`.

    A 180-degree bar with chorded ends would read as a triangle.
    """
    chart = xy.polar_bar_chart(
        xy.bar([0.0, math.pi / 2, math.pi], [1.0, 2.0, 3.0], width=0.8),
        width=420,
        height=420,
    )
    doc = chart.figure().to_image(format="svg").decode()
    wedges = [d for d in re.findall(r'<path d="([^"]+)"', doc) if " A " in d]
    assert len(wedges) >= 3, "expected one arc path per bar"


def test_polar_wedge_points_close_the_sector() -> None:
    from xy._svg import polar_wedge_points

    project = _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    # A ring segment with a hole: both arcs, so 2*(steps+1) points.
    poly = polar_wedge_points(project, 0.0, math.pi / 2, 0.5, 1.0, steps=8)
    assert len(poly) == 18
    outer = math.hypot(poly[0][0] - 200.0, poly[0][1] - 200.0)
    inner = math.hypot(poly[-1][0] - 200.0, poly[-1][1] - 200.0)
    assert outer == pytest.approx(200.0, abs=1e-6)
    assert inner == pytest.approx(100.0, abs=1e-6)


def test_polar_wedge_from_the_centre_is_a_fan() -> None:
    from xy._svg import polar_wedge_points

    project = _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    poly = polar_wedge_points(project, 0.0, math.pi / 2, 0.0, 1.0, steps=8)
    assert poly[0] == pytest.approx((200.0, 200.0))
    assert len(poly) == 10


def test_wind_rose_counts_every_observation() -> None:
    rng = np.random.default_rng(3)
    directions = rng.uniform(0, 360, 500)
    speeds = rng.gamma(2.0, 2.0, 500)
    chart = xy.wind_rose(directions, speeds, sectors=12)
    bars = [c for c in chart.children if getattr(c, "kind", None) == "bar"]
    # `y` is each band's own count (a HEIGHT above its base), so the totals sum
    # directly. This assertion used to read `sum(y) - sum(base)`, which is what
    # let the double-stacking bug through: it happened to cancel out.
    counted = sum(float(np.asarray(b.y).sum()) for b in bars)
    assert counted == pytest.approx(500.0)


def test_wind_rose_bands_stack_without_gaps() -> None:
    rng = np.random.default_rng(4)
    chart = xy.wind_rose(rng.uniform(0, 360, 300), rng.gamma(2.0, 2.0, 300), sectors=8)
    bars = [c for c in chart.children if getattr(c, "kind", None) == "bar"]
    for lower, upper in pairwise(bars):
        # A band starts where the one below it ENDS: base + height, since the
        # value is a height above the base rather than an absolute radius.
        below_top = np.asarray(lower.props["base"], dtype=float) + np.asarray(lower.y, dtype=float)
        assert np.asarray(upper.props["base"], dtype=float) == pytest.approx(below_top)


def test_wind_rose_uses_the_compass_convention() -> None:
    """0 degrees is north and angles increase clockwise, or the rose is a
    mirror image of the weather it describes."""
    rng = np.random.default_rng(5)
    chart = xy.wind_rose(rng.uniform(0, 360, 100), rng.gamma(2.0, 2.0, 100))
    axis = next(c for c in chart.children if isinstance(c, xy.Axis) and c.which == "x")
    assert axis.theta_zero == "N"
    assert axis.theta_direction == "clockwise"
    assert axis.theta_unit == "degrees"


def test_wind_rose_bins_bearings_centred_on_each_sector() -> None:
    """A bearing of exactly 0 belongs to the sector centred on north, not to
    the one starting there."""
    chart = xy.wind_rose(np.array([0.0, 0.0, 90.0]), np.array([1.0, 1.0, 1.0]), sectors=4)
    bars = [c for c in chart.children if getattr(c, "kind", None) == "bar"]
    totals = np.zeros(4)
    for b in bars:
        totals += np.asarray(b.y) - np.asarray(b.props["base"])
    assert totals[0] == pytest.approx(2.0)  # sector centred on 0 degrees
    assert totals[1] == pytest.approx(1.0)  # sector centred on 90 degrees


def test_wind_rose_rejects_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="same length"):
        xy.wind_rose(np.array([0.0, 90.0]), np.array([1.0]))


def test_wind_rose_band_labels_are_readable() -> None:
    """Raw quantiles make a legend like '<= 2.76651'."""
    rng = np.random.default_rng(6)
    chart = xy.wind_rose(rng.uniform(0, 360, 400), rng.gamma(3.0, 2.0, 400))
    for bar_mark in [c for c in chart.children if getattr(c, "kind", None) == "bar"]:
        value = bar_mark.name.split()[-1]
        assert len(value.split(".")[-1]) <= 3, f"unreadable band label {bar_mark.name!r}"


def test_polar_bars_reach_the_raster_export() -> None:
    chart = xy.polar_bar_chart(
        xy.bar([0.0, math.pi], [1.0, 1.0], width=1.0, color="#000000"),
        width=400,
        height=400,
    )
    fig = chart.figure()
    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    from test_png_export import _decode_rgba

    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    height, width, _ = pixels.shape
    # Mid-radius along theta=0 must be inside the first wedge.
    px, py = project(0.0, 0.5)
    window = pixels[max(0, int(py) - 2) : int(py) + 3, max(0, int(px) - 2) : int(px) + 3, 0]
    assert int(window.min()) < 128, "raster drew no wedge at theta=0"


# -- styling parity --------------------------------------------------------


def _styled(theta_style=None, r_style=None, **axis_kwargs):
    theta_kw = axis_kwargs.get("theta", {})
    r_kw = axis_kwargs.get("r", {})
    if theta_style:
        theta_kw = {**theta_kw, "style": theta_style}
    if r_style:
        r_kw = {**r_kw, "style": r_style}
    theta, r = _rose()
    return xy.polar_chart(
        xy.line(theta, r),
        xy.theta_axis(**theta_kw),
        xy.r_axis(**r_kw),
        width=400,
        height=400,
    )


def test_grid_colour_separates_rings_from_spokes() -> None:
    """The radial axis owns the rings, the angular axis owns the spokes.

    Conflating them is the easy mistake here: the cartesian code hides grid
    lines and labels together through one hideX/hideY pair.
    """
    doc = _styled(theta_style={"grid_color": "#00ffff"}, r_style={"grid_color": "#ff00ff"})
    doc = doc.figure().to_image(format="svg").decode()
    ring = re.search(r'<circle data-xy-grid="ring"[^/]*?stroke="([^"]+)"', doc)
    spoke = re.search(r'<line data-xy-grid="spoke"[^/]*?stroke="([^"]+)"', doc)
    assert ring is not None and spoke is not None
    assert ring.group(1) == "#ff00ff"
    assert spoke.group(1) == "#00ffff"


@pytest.mark.parametrize(
    ("which", "theta_fill", "r_fill"),
    [("theta", "#00000000", None), ("r", None, "#00000000")],
)
def test_text_shorthand_hides_only_its_own_axis_labels(
    which: str, theta_fill: str | None, r_fill: str | None
) -> None:
    """`text=False` works by setting tick_label_color transparent.

    The polar label writers originally read only the chart-level slot, so the
    shorthand — and any explicit tick_label_color — silently did nothing while
    the browser client honoured both.
    """
    chart = _styled(**{which: {"text": False}})
    doc = chart.figure().to_image(format="svg").decode()
    theta = re.search(r'<text data-xy-tick="theta"[^>]*fill="([^"]*)"', doc)
    radial = re.search(r'<text data-xy-tick="r"[^>]*fill="([^"]*)"', doc)
    assert theta is not None and radial is not None
    if theta_fill:
        assert theta.group(1) == theta_fill
        assert radial.group(1) != theta_fill
    if r_fill:
        assert radial.group(1) == r_fill
        assert theta.group(1) != r_fill


def test_explicit_tick_label_colour_beats_the_chart_slot() -> None:
    doc = _styled(
        theta_style={"tick_label_color": "#ff0000"},
        r_style={"tick_label_color": "#00ff00"},
    )
    doc = doc.figure().to_image(format="svg").decode()
    assert re.search(r'<text data-xy-tick="theta"[^>]*fill="#ff0000"', doc)
    assert re.search(r'<text data-xy-tick="r"[^>]*fill="#00ff00"', doc)


def test_raster_honours_axis_styling_too() -> None:
    """The exporters share geometry but not text placement, so the raster path
    needs its own assertion — this is where styling has silently diverged."""
    from test_png_export import _decode_rgba

    chart = _styled(
        theta_style={"tick_label_color": "#ff0000"},
        r_style={"grid_color": "#ff00ff"},
    )
    pixels = _decode_rgba(chart.figure().to_image(format="png", scale=1))

    def count(rgb: tuple[int, int, int]) -> int:
        delta = np.abs(pixels[:, :, :3].astype(int) - np.array(rgb)).sum(axis=2)
        return int((delta < 30).sum())

    assert count((255, 0, 0)) > 0, "angular tick labels ignored tick_label_color"
    assert count((255, 0, 255)) > 0, "rings ignored the radial grid_color"


def test_show_false_clears_the_outer_frame() -> None:
    doc = _styled(**{"theta": {"show": False}}).figure().to_image(format="svg").decode()
    frame = re.search(r'<circle data-xy-frame="polar"[^/]*/>', doc)
    assert frame is not None
    assert 'stroke-width="0"' in frame.group(0) or "#00000000" in frame.group(0)


# -- audit round 2: chrome leaks, strategy off, angle, ceiling, pdf --------


def test_no_cartesian_tick_stubs_leak_into_polar_svg() -> None:
    """Edge-anchored tick marks have no polar geometry; they used to leak in
    from the cartesian emission loops (raster never drew them — divergence)."""
    theta, r = _rose()
    chart = xy.polar_chart(
        xy.line(theta, r),
        xy.theta_axis(style={"tick_length": 8.0, "tick_color": "#ff00ff"}),
        width=400,
        height=400,
    )
    doc = chart.figure().to_image(format="svg").decode()
    stubs = [m for m in re.findall(r"<line [^/]*/>", doc) if "ff00ff" in m]
    assert stubs == []


def test_strategy_off_hides_polar_labels_but_keeps_grid() -> None:
    theta, r = _rose()
    chart = xy.polar_chart(
        xy.line(theta, r), xy.theta_axis(tick_label_strategy="off"), width=400, height=400
    )
    doc = chart.figure().to_image(format="svg").decode()
    assert 'data-xy-tick="theta"' not in doc
    assert doc.count('data-xy-grid="spoke"') >= 3  # grid survives "off"
    assert 'data-xy-tick="r"' in doc  # the other axis keeps its labels


def test_tick_label_angle_rotates_polar_labels() -> None:
    theta, r = _rose()
    chart = xy.polar_chart(
        xy.line(theta, r), xy.theta_axis(tick_label_angle=45.0), width=400, height=400
    )
    doc = chart.figure().to_image(format="svg").decode()
    rotated = re.findall(r'<text data-xy-tick="theta"[^>]*transform="rotate\(45 ', doc)
    assert len(rotated) >= 3


def test_theta_axis_title_stays_on_canvas() -> None:
    """The rect re-cut reclaims the bottom gutter — except when the theta axis
    has a title, which is drawn there and was pushed below the canvas edge."""
    theta, r = _rose()
    chart = xy.polar_chart(xy.line(theta, r), xy.theta_axis(label="bearing"), width=400, height=400)
    doc = chart.figure().to_image(format="svg").decode()
    m = re.search(r'<text[^>]*y="(-?[\d.]+)"[^>]*>bearing</text>', doc)
    assert m is not None and 0 <= float(m.group(1)) <= 400


def test_polar_point_ceiling_is_enforced() -> None:
    from xy.config import POLAR_DIRECT_CEILING

    theta = np.zeros(POLAR_DIRECT_CEILING + 1)
    with pytest.raises(ValueError, match="polar ceiling"):
        xy.polar_chart(xy.scatter(theta, theta)).figure().build_payload_split()


def test_radar_merges_categories_into_an_authored_theta_axis() -> None:
    """An authored theta axis customises the spokes; it must not silently
    replace the category labels with numeric angles."""
    chart = xy.radar_chart(
        ["speed", "power", "range"], xy.area([1.0, 2.0, 3.0]), xy.theta_axis(label="custom")
    )
    doc = chart.figure().to_image(format="svg").decode()
    for name in ("speed", "power", "range", "custom"):
        assert name in doc


def test_polar_pdf_export_round_trips() -> None:
    """The PDF converter's clip subset was rect-only, so every polar chart
    raised. The disc clip now lands as four Bezier quarter-arcs."""
    theta, r = _rose()
    pdf = _chart(children=[xy.line(theta, r)]).figure().to_image(format="pdf")
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 800


def test_channel_styled_polar_scatter_stays_inside_the_disc() -> None:
    """A colormapped/sized polar scatter took a second Rust affine fast path
    that projected (theta, r) as cartesian (x, y): a diagonal line of points
    outside the frame ring."""
    rng = np.random.default_rng(5)
    theta = rng.uniform(0, 2 * math.pi, 200)
    r = rng.uniform(0.2, 1.0, 200)
    chart = xy.polar_chart(
        xy.scatter(theta, r, color=r, colormap="viridis", size=6.0), width=400, height=400
    )
    fig = chart.figure()
    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)

    from test_png_export import _decode_rgba

    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    height, width, _ = pixels.shape
    yy, xx = np.mgrid[0:height, 0:width]
    outside = np.hypot(xx - project.cx, yy - project.cy) > project.radius + 12
    # Colormapped marks are saturated colours; chrome text is near-grey. Count
    # strongly-saturated ink outside the disc.
    rgb = pixels[:, :, :3].astype(int)
    saturated = (rgb.max(axis=2) - rgb.min(axis=2)) > 60
    assert int((saturated & outside).sum()) == 0


# -- layout robustness (audit round 2) -------------------------------------


@pytest.mark.parametrize(
    ("width", "height"),
    [(60, 60), (80, 80), (100, 100), (120, 120), (1200, 300), (300, 900), (400, 400)],
)
def test_disc_stays_inside_the_canvas_at_every_size(width: int, height: int) -> None:
    """The cartesian rect has a 40px floor that can exceed a small canvas, and
    a disc centred in it then leaves the page (80x80 drew out to x=86)."""
    theta, r = _rose(30)
    chart = xy.polar_chart(xy.line(theta, r), width=width, height=height)
    spec, _ = chart.figure().build_payload_split()
    canvas_w, canvas_h, _compact, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    assert project.cx - project.radius >= -0.5
    assert project.cx + project.radius <= canvas_w + 0.5
    assert project.cy - project.radius >= -0.5
    assert project.cy + project.radius <= canvas_h + 0.5
    assert project.radius > 0


def test_horizontal_colorbar_keeps_its_gutter() -> None:
    """The rect re-cut extends the plot downward; a horizontal colorbar hangs
    off the plot's bottom edge and was pushed clean off the canvas."""
    rng = np.random.default_rng(3)
    theta = rng.uniform(0, 2 * math.pi, 120)
    r = rng.uniform(0.1, 1.0, 120)
    chart = xy.polar_chart(
        xy.scatter(theta, r, color=r, colormap="viridis"),
        xy.colorbar(orientation="horizontal"),
        width=520,
        height=500,
    )
    doc = chart.figure().to_image(format="svg").decode()
    tops = [float(y) for y in re.findall(r'<rect[^>]*y="([\d.]+)"', doc)]
    assert tops and max(tops) < 500


def test_long_category_labels_reserve_measured_room() -> None:
    """A fixed 30px allowance hard-clipped authored radar category names."""
    cats = ["EAST-NORTH-EAST", "SOUTH-SOUTH-WEST", "NORTH-WEST", "SOUTH-EAST", "WEST"]
    chart = xy.radar_chart(cats, xy.area([0.9, 0.6, 0.7, 0.5, 0.8]), width=600, height=560)
    doc = chart.figure().to_image(format="svg").decode()
    xs = [float(x) for x in re.findall(r'<text data-xy-tick="theta" x="(-?[\d.]+)"', doc)]
    assert xs and min(xs) >= 0 and max(xs) <= 600


def test_radar_fill_false_outlines_instead_of_filling() -> None:
    chart = xy.radar_chart(["a", "b", "c"], xy.area([1.0, 2.0, 3.0]), fill=False)
    kinds = [c.kind for c in chart.children if isinstance(c, xy.Mark)]
    assert kinds == ["line"]


def test_radar_rejects_marks_it_cannot_close() -> None:
    with pytest.raises(ValueError, match="supports area and line marks"):
        xy.radar_chart(["a", "b", "c"], xy.scatter([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]))


def test_radar_rejects_column_names_with_a_readable_error() -> None:
    with pytest.raises(ValueError, match="must carry values directly"):
        xy.radar_chart(["a", "b", "c"], xy.area("speed"))


# -- radial clipping semantics ---------------------------------------------


def test_below_range_scatter_is_culled_not_mirrored() -> None:
    """A radius below an authored r_lo normalizes negative and mirrors through
    the centre to a position INSIDE the disc, where no clip can hide it. The
    client shader NaN-culls the point; both exporters must drop the same row."""
    theta = np.array([0.0, math.pi / 2])
    r = np.array([0.2, 0.75])  # first point below r_lo
    chart = xy.polar_chart(
        xy.scatter(theta, r, size=9.0, color="#000000"),
        xy.r_axis(domain=(0.5, 1.0)),
        width=400,
        height=400,
    )
    fig = chart.figure()
    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    mirrored_x, mirrored_y = (float(v) for v in project(0.0, 0.2))
    kept_x, kept_y = (float(v) for v in project(math.pi / 2, 0.75))

    doc = fig.to_image(format="svg").decode()
    centres = [
        (float(cx), float(cy))
        for cx, cy in re.findall(r'<circle cx="(-?[\d.]+)" cy="(-?[\d.]+)" r="4', doc)
    ]
    assert not any(math.hypot(cx - mirrored_x, cy - mirrored_y) < 2.0 for cx, cy in centres), (
        "SVG drew the below-range point mirrored through the centre"
    )
    assert any(math.hypot(cx - kept_x, cy - kept_y) < 2.0 for cx, cy in centres), (
        "SVG dropped the in-range point too"
    )

    from test_png_export import _decode_rgba

    pixels = _decode_rgba(fig.to_image(format="png", scale=1))

    def darkest_near(x: float, y: float) -> int:
        ix, iy = int(round(x)), int(round(y))
        window = pixels[max(0, iy - 3) : iy + 4, max(0, ix - 3) : ix + 4, 0]
        return int(window.min())

    assert darkest_near(mirrored_x, mirrored_y) >= 128, "raster drew the mirrored point"
    assert darkest_near(kept_x, kept_y) < 128, "raster dropped the in-range point too"


def test_above_range_scatter_leaves_no_ink_beyond_the_ring() -> None:
    """The raster path has no disc clip, so an above-range point used to draw
    past the outer ring into the corner the disc does not cover."""
    chart = xy.polar_chart(
        xy.scatter(np.array([math.pi / 4]), np.array([1.3]), size=10.0, color="#000000"),
        xy.r_axis(domain=(0.0, 1.0)),
        width=400,
        height=400,
    )
    fig = chart.figure()
    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    px, py = (float(v) for v in project(math.pi / 4, 1.3))

    from test_png_export import _decode_rgba

    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    window = pixels[int(py) - 3 : int(py) + 4, int(px) - 3 : int(px) + 4, 0]
    assert int(window.min()) >= 128, "raster drew a mark beyond the outer ring"


def test_line_vertices_outside_the_radial_range_split_the_path() -> None:
    """A chord with a culled endpoint is dropped whole in every renderer (§8):
    the path splits into visible runs instead of routing through the mirrored
    position of the out-of-range vertex."""
    theta = np.array([0.0, math.pi / 4, math.pi / 2, 3 * math.pi / 4, math.pi])
    r = np.array([0.75, 0.8, 0.2, 0.8, 0.75])  # middle vertex below r_lo
    chart = xy.polar_chart(
        xy.line(theta, r, color="#2563eb"),
        xy.r_axis(domain=(0.5, 1.0)),
        width=400,
        height=400,
    )
    doc = chart.figure().to_image(format="svg").decode()
    line_path = re.search(r'<path d="(M [^"]+)" stroke="#2563eb"', doc)
    assert line_path is not None
    assert line_path.group(1).count("M ") == 2, "expected two visible runs around the gap"


def test_full_turn_slice_draws_an_annulus_not_nothing() -> None:
    """Arc endpoints coincide at a full turn and SVG omits such segments, so a
    100% donut slice (a progress ring at 100%) rendered as nothing."""
    chart = xy.polar_chart(
        xy.bar([180.0], [1.0], base=0.5, width=360.0, color="#7c3aed"),
        xy.theta_axis(unit="degrees"),
        xy.r_axis(domain=(0.0, 1.0)),
        width=400,
        height=400,
    )
    fig = chart.figure()
    doc = fig.to_image(format="svg").decode()
    wedges = [d for d in re.findall(r'<path d="([^"]+)"', doc) if " A " in d]
    assert len(wedges) == 1
    arcs = re.findall(r"A [\d.]+ [\d.]+ 0 1 \d (-?[\d.]+) (-?[\d.]+)", wedges[0])
    assert len(arcs) == 4, "an annulus needs two half-turn arcs per circle"

    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    from test_png_export import _decode_rgba

    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    for degrees in (0.0, 90.0, 180.0, 270.0):
        px, py = (float(v) for v in project(degrees, 0.75))
        window = pixels[int(py) - 2 : int(py) + 3, int(px) - 2 : int(px) + 3, 1]
        assert int(window.min()) < 200, f"raster annulus missing at {degrees} degrees"


def test_fractional_degree_ticks_keep_their_precision() -> None:
    """`_fmt_angle` used a hardcoded step of 1, so an authored 22.5-degree grid
    labelled itself 22°/68° (round-half-even) instead of 22.5°/67.5°."""
    theta, r = _rose()
    chart = xy.polar_chart(
        xy.line(np.degrees(theta), r),
        xy.theta_axis(unit="degrees", tick_values=[0.0, 22.5, 45.0, 67.5, 90.0]),
        width=400,
        height=400,
    )
    doc = chart.figure().to_image(format="svg").decode()
    assert "22.5°" in doc and "67.5°" in doc


def test_area_fill_clamps_to_the_radial_range_rather_than_vanishing() -> None:
    """A fill's extent at each angle is [base, top] intersected with the radial
    range. Culling an out-of-range endpoint instead made a whole radar polygon
    disappear the moment zoom lifted the minimum above its baseline."""
    theta = np.linspace(0.0, 2.0 * math.pi, 24)
    values = np.full(24, 3.0)
    chart = xy.polar_chart(
        xy.area(theta, values, color="#2563eb"),
        xy.r_axis(domain=(1.0, 2.0)),  # every value sits ABOVE the range
        width=400,
        height=400,
    )
    doc = chart.figure().to_image(format="svg").decode()
    fills = re.findall(r'<path d="([^"]+)" fill="[^"]*" fill-opacity', doc)
    assert fills, "the fill was dropped entirely instead of clamping to the rim"


def test_wedge_beyond_the_outer_ring_clips_instead_of_disappearing() -> None:
    """A bar whose tip crosses the outer ring draws up to the ring."""
    from xy._svg import polar_wedge_points

    project = _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    poly = polar_wedge_points(project, 0.0, math.pi / 4, 0.0, 5.0, steps=8)
    assert poly, "an over-range wedge vanished"
    for px, py in poly:
        assert math.hypot(px - 200.0, py - 200.0) <= 200.0 + 1e-6


def test_wedge_entirely_outside_the_range_draws_nothing() -> None:
    from xy._svg import polar_wedge_points

    project = _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    assert polar_wedge_points(project, 0.0, math.pi / 4, 2.0, 5.0, steps=8) == []


def test_bar_below_the_radial_minimum_is_clipped_not_mirrored() -> None:
    """A radius below the minimum normalizes negative, which would reflect the
    wedge through the centre into the opposite quadrant."""
    from xy._svg import polar_wedge_points

    project = _PolarProjection({}, {"range": [2.0, 4.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    poly = polar_wedge_points(project, 0.0, math.pi / 4, 0.0, 3.0, steps=8)
    for px, py in poly:
        # theta in [0, pi/4] is the upper-right quadrant; a mirrored point
        # would land left of or below the centre.
        assert px >= 200.0 - 1e-6
        assert py <= 200.0 + 1e-6


# -- unequal-width sectors (pie/donut composition) -------------------------


def test_unequal_slice_widths_render_as_wedges_not_rectangles() -> None:
    """A donut needs per-slice angular width. Unequal widths route to the
    four-edge rect path, which drew Cartesian rectangles inside polar chrome
    until that path learned sectors."""
    slices = [
        xy.bar([45.0], [1.0], base=0.5, width=90.0, color="#7c3aed"),
        xy.bar([200.0], [1.0], base=0.5, width=180.0, color="#0284c7"),
    ]
    doc = (
        xy.polar_chart(
            *slices,
            xy.theta_axis(unit="degrees"),
            xy.r_axis(domain=(0.0, 1.0)),
            width=420,
            height=420,
        )
        .figure()
        .to_image(format="svg")
        .decode()
    )
    assert "<rect" not in doc.split("</defs>")[-1], "slices drew as cartesian rects"
    assert len([d for d in re.findall(r'<path d="([^"]+)"', doc) if " A " in d]) >= 2


def test_point_annotations_project_through_polar() -> None:
    """Centre text is `(any angle, r=0)`. The separable scales would put that
    at the bottom-left corner instead of the middle of the disc."""
    doc = (
        xy.polar_chart(
            xy.bar([45.0], [1.0], base=0.5, width=80.0),
            xy.text(0.0, 0.0, "CENTRE", dx=0, dy=0, anchor="middle"),
            xy.theta_axis(unit="degrees", show=False),
            xy.r_axis(domain=(0.0, 1.0), show=False),
            width=400,
            height=400,
        )
        .figure()
        .to_image(format="svg")
        .decode()
    )
    m = re.search(r'<tspan x="([\d.]+)" y="([\d.]+)">CENTRE</tspan>', doc)
    assert m is not None, "the annotation was dropped"
    assert 180.0 <= float(m.group(1)) <= 220.0
    assert 180.0 <= float(m.group(2)) <= 225.0


# -- customizability probe fixes (evilcharts ECharts pie blocks) ------------


def test_authored_padding_survives_the_polar_recut() -> None:
    """`padding=` is how a donut reserves a band for its legend or caption.

    The recut used to symmetrise the cartesian gutters away and hand the whole
    canvas to the disc, so an authored bottom band silently vanished while the
    same padding on a cartesian chart was honoured.
    """
    theta, r = _rose()
    marks = [xy.line(theta, r), xy.theta_axis(show=False), xy.r_axis(show=False)]
    plain = xy.polar_chart(*marks, width=400, height=420)
    padded = xy.polar_chart(*marks, width=400, height=420, padding=[10, 10, 140, 10])

    bottoms = []
    for chart in (plain, padded):
        spec, _ = chart.figure().build_payload_split()
        _w, _h, _c, plot = layout(spec)
        project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
        bottoms.append(project.cy + project.radius)
    assert bottoms[1] < bottoms[0] - 100, "authored bottom padding was reclaimed by the recut"
    assert bottoms[1] <= 420 - 130


def test_polar_wedge_corner_radius_reaches_every_renderer() -> None:
    """`corner_radius` used to be accepted, shipped on the wire and ignored by
    all three renderers — a silent approximation (§28). Rounding pulls the
    corners in, so a rounded wedge covers strictly less area than a square one.
    """
    from xy._svg import polar_wedge_points

    project = _PolarProjection(
        {"theta_unit": "degrees"}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400}
    )
    square = polar_wedge_points(project, 0.0, 90.0, 0.5, 1.0, steps=24)
    rounded = polar_wedge_points(project, 0.0, 90.0, 0.5, 1.0, steps=24, corner_radius=14.0)
    assert rounded and square

    def area(poly: list[tuple[float, float]]) -> float:
        total = 0.0
        for (x0, y0), (x1, y1) in zip(poly, [*poly[1:], poly[0]], strict=True):
            total += x0 * y1 - x1 * y0
        return abs(total) / 2.0

    assert area(rounded) < area(square), "corner_radius did not round the sector"
    # Rounding removes area near the corners only — never more than a rough
    # bound of four corner squares, or the profile is wrong rather than rounded.
    assert area(square) - area(rounded) < 4 * 14.0 * 14.0


def test_rounded_wedge_stays_within_the_square_wedge() -> None:
    """Rounding must inset the boundary, never bulge past it."""
    from xy._svg import polar_wedge_points

    project = _PolarProjection(
        {"theta_unit": "degrees"}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400}
    )
    poly = polar_wedge_points(project, 0.0, 90.0, 0.5, 1.0, steps=24, corner_radius=14.0)
    for px, py in poly:
        radius = math.hypot(px - 200.0, py - 200.0)
        assert 100.0 - 1e-6 <= radius <= 200.0 + 1e-6
        angle = math.degrees(math.atan2(200.0 - py, px - 200.0))
        assert -1e-6 <= angle <= 90.0 + 1e-6


def test_svg_rounded_slice_differs_from_a_square_one() -> None:
    def slice_path(corner_radius: float) -> str:
        chart = xy.polar_chart(
            xy.bar([45.0], [1.0], base=0.5, width=80.0, corner_radius=corner_radius),
            xy.theta_axis(unit="degrees", show=False),
            xy.r_axis(domain=(0.0, 1.0), show=False),
            width=400,
            height=400,
        )
        doc = chart.figure().to_image(format="svg").decode()
        paths = re.findall(r'<path d="([^"]+)"', doc)
        assert paths
        return paths[0]

    assert slice_path(0.0) != slice_path(14.0)
    assert " A " in slice_path(0.0), "a plain wedge should keep its exact arcs"


def test_raster_polar_wedge_honours_a_gradient_fill() -> None:
    """The gradient reached the SVG (`url(#g)`) and the browser but the raster
    branch painted flat, so the PNG disagreed with both.
    """
    from test_png_export import _decode_rgba

    chart = xy.polar_chart(
        xy.bar(
            [180.0],
            [1.0],
            base=0.4,
            width=340.0,
            color="#7c3aed",
            fill="linear-gradient(to top, #7c3aed, #34d399)",
        ),
        xy.theta_axis(unit="degrees", show=False),
        xy.r_axis(domain=(0.0, 1.0), show=False),
        width=320,
        height=320,
    )
    fig = chart.figure()
    assert "url(#" in fig.to_image(format="svg").decode()

    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    project = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
    # Sample where the gradient actually varies: "to top" runs up the wedge's
    # bounding box, so two points at the same radius but opposite ends of the
    # vertical span must differ. A flat fill gives one colour at both.
    swatches = []
    for degrees in (90.0, 270.0):
        px, py = (float(v) for v in project(degrees, 0.8))
        swatches.append(tuple(int(v) for v in pixels[int(py), int(px), :3]))
    assert swatches[0] != swatches[1], f"raster painted the wedge flat: {swatches}"


def test_client_projects_point_annotations_through_polar() -> None:
    """Source guard: the client annotation layer must not read (theta, r) with
    the separable cartesian scales.

    Every annotation in js/src/51_annotations.ts used to go through
    `_dataPxX`/`_dataPxY`, so the browser strung a polar chart's labels out in
    a horizontal row while both exporters placed them correctly — the exact
    cross-renderer divergence this coordinate system is built to avoid. There
    is no headless-JS harness for the DOM label layer, so the binding is a
    source assertion plus the shared placement contract in polar-axes.md §9.
    """
    source = (ROOT / "js" / "src" / "51_annotations.ts").read_text(encoding="utf-8")
    point_kinds = source.count("_dataPxPoint(")
    assert point_kinds >= 6, "point-anchored annotations must use the joint polar projection"
    # rule/band stay on the separable path on purpose (deferred geometry).
    assert "_dataPxX(Number(ann.value))" in source


# -- review round 3: reversed-r exports, PDF clips, singleton range, area cull


def test_reversed_radial_axis_keeps_wedges_in_static_exports() -> None:
    """The static twin of the client reversed-r regression: `norm_radius` is
    decreasing on a reversed axis, so taking the normalized endpoints
    positionally made outer <= inner and silently dropped every wedge from
    SVG/PNG while the shader (which min/maxes) kept drawing them."""

    def wedge_paths(**rkw) -> int:
        chart = xy.polar_chart(
            xy.bar([0.0, 1.0, 2.0], [3.0, 5.0, 4.0], width=0.5),
            xy.r_axis(**rkw),
            width=360,
            height=340,
        )
        doc = chart.figure().to_image(format="svg").decode()
        return len([d for d in re.findall(r'<path d="([^"]+)"', doc) if " A " in d])

    assert wedge_paths(domain=(1.0, 10.0)) == 3
    assert wedge_paths(domain=(1.0, 10.0), reverse=True) == 3


@pytest.mark.parametrize(
    ("label", "theta_kwargs", "r_kwargs"),
    [
        ("hole", {}, {"hole": 0.3}),
        ("sector", {"sector": (0.0, 90.0)}, {}),
        ("hole+sector", {"sector": (20.0, 160.0)}, {"hole": 0.4}),
    ],
)
def test_pdf_export_supports_hole_and_sector_clips(label, theta_kwargs, r_kwargs) -> None:
    """The marks clip is a <circle> only for the full disc; hole/sector emit a
    <path> clipPath, which the PDF converter refused — so the headline polar
    features crashed `to_image(format="pdf")`. The path clip now lowers to PDF
    ops with the SVG clip-rule mapped onto W/W*."""
    chart = xy.polar_chart(
        xy.bar([30.0, 70.0], [3.0, 5.0], width=8.0),
        xy.theta_axis(unit="degrees", **theta_kwargs),
        xy.r_axis(**r_kwargs),
        width=320,
        height=300,
    )
    pdf = chart.figure().to_image(format="pdf")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 800


def test_constant_radius_series_still_starts_at_the_centre() -> None:
    """The singleton (lo == hi) early-return fired before the polar branch, so
    constant-radius data resolved to a padded [4.75, 5.25] — a unit circle
    rendered as a ring floating mid-disc."""
    spec, _ = (
        xy.polar_chart(xy.line([0.0, 1.0, 2.0, 3.0], [5.0] * 4), width=320, height=300)
        .figure()
        .build_payload_split()
    )
    assert spec["y_axis"]["range"] == [0.0, 5.0]


def test_raster_polar_area_culls_vertices_outside_the_sector() -> None:
    """The raster polar area branch only clamped radii; SVG (via _curve_path's
    position_mask) and the shader cull out-of-sector and NaN vertices. The PNG
    painted the full-turn polygon with chords across the sector boundary and
    let NaN reach the display list (§19)."""
    from xy import _raster

    captured: list[int] = []
    original_fill = _raster._Cmd.fill
    original_grad = _raster._Cmd.grad

    def spy_fill(self, pts, color):
        captured.append(len(pts))
        return original_fill(self, pts, color)

    def spy_grad(self, pts, g0, g1, stops):
        captured.append(len(pts))
        return original_grad(self, pts, g0, g1, stops)

    _raster._Cmd.fill = spy_fill
    _raster._Cmd.grad = spy_grad
    try:
        theta = np.linspace(0.0, 360.0, 40)
        r = 1 + 0.3 * np.sin(np.radians(theta) * 3)
        r_nan = r.copy()
        r_nan[20] = np.nan
        chart = xy.polar_chart(
            xy.area(theta, r_nan),
            xy.theta_axis(unit="degrees", sector=(0.0, 90.0)),
            xy.r_axis(domain=(0.0, 1.5)),
            width=320,
            height=300,
        )
        chart.figure().to_image(format="png", scale=1)
    finally:
        _raster._Cmd.fill = original_fill
        _raster._Cmd.grad = original_grad

    in_sector = int(((theta >= 0.0) & (theta <= 90.0)).sum())
    area_polys = [n for n in captured if n > 8]
    assert area_polys, "the area fill vanished entirely"
    # Every emitted polygon must be bounded by the visible-run size, not the
    # full 2 * 40-vertex turn.
    assert all(n <= 2 * in_sector for n in area_polys), (theta.size, area_polys)


# -- pie_chart composition ---------------------------------------------------


def test_pie_chart_slices_carry_category_value_and_share() -> None:
    # Counts, not shares: the value and the percentage are different numbers, so
    # both earn their place in the row.
    chart = xy.pie_chart(["a", "b", "c"], [27.0, 21.0, 13.0], width=300, height=300)
    spec, _ = chart.figure().build_payload()
    names = [t["name"] for t in spec["traces"]]
    assert names == ["a  27  (44%)", "b  21  (34%)", "c  13  (21%)"]
    # The composition owns its readout: the tooltip is the slice name alone,
    # never theta (layout) or the constant rim radius.
    assert spec["tooltip"] == {"title": "{name}"}
    # Full spans: the gap is carved by the renderer at a constant pixel width
    # rather than by shrinking each angle, so the shares stay exact.
    widths = [t["bar"]["width"] for t in spec["traces"]]
    assert sum(widths) == pytest.approx(360.0, abs=1e-6)


def test_pie_chart_never_prints_the_same_number_twice() -> None:
    """Percentage-shaped values made both defaults render the same digits.

    `[40, 30, 20, 10]` is how most pie data arrives, and it came out as
    "Direct  40  (40%)" — a legend row that reads as repeated text, and long
    enough to overflow the legend box that then grew a horizontal scrollbar.
    """
    chart = xy.pie_chart(
        ["Direct", "Partner", "Organic", "Other"],
        [40.0, 30.0, 20.0, 10.0],
        width=300,
        height=300,
    )
    spec, _ = chart.figure().build_payload()
    names = [t["name"] for t in spec["traces"]]
    assert names == ["Direct  (40%)", "Partner  (30%)", "Organic  (20%)", "Other  (10%)"]

    # The choice is made once for the whole pie, not per slice: a legend where
    # one row carries a bare value and the next does not is worse than either
    # consistent shape. 10.5 does not render as its 10% share, so every row keeps
    # its value even though the other three would have collided.
    mixed = xy.pie_chart(["a", "b", "c", "d"], [40.0, 30.0, 20.0, 10.5], width=300, height=300)
    mixed_spec, _ = mixed.figure().build_payload()
    assert [t["name"] for t in mixed_spec["traces"]] == [
        "a  40  (40%)",
        "b  30  (30%)",
        "c  20  (20%)",
        "d  10.5  (10%)",
    ]

    # A zero slice draws no wedge and gets no row, so it cannot veto the choice.
    zeroed = xy.pie_chart(["a", "b", "c", "d"], [40.0, 30.0, 30.0, 0.0], width=300, height=300)
    zero_spec, _ = zeroed.figure().build_payload()
    assert [t["name"] for t in zero_spec["traces"]] == ["a  (40%)", "b  (30%)", "c  (30%)"]

    # Either switch alone is untouched: with no share to collide with, the value
    # is always shown.
    values_only = xy.pie_chart(["a", "b"], [40.0, 60.0], show_percent=False, width=300, height=300)
    values_spec, _ = values_only.figure().build_payload()
    assert [t["name"] for t in values_spec["traces"]] == ["a  40", "b  60"]


def test_pie_chart_user_tooltip_wins() -> None:
    chart = xy.pie_chart(["a", "b"], [1.0, 1.0], xy.tooltip(title="custom"), width=300, height=300)
    spec, _ = chart.figure().build_payload()
    assert spec["tooltip"]["title"] == "custom"


@pytest.mark.parametrize(
    ("labels", "values", "message"),
    [
        (["a"], [1.0, 2.0], "one value per label"),
        ([], [], "at least one slice"),
        (["a"], [-1.0], "finite and non-negative"),
        (["a", "b"], [0.0, 0.0], "positive total"),
    ],
)
def test_pie_chart_refusals(labels, values, message) -> None:
    with pytest.raises(ValueError, match=message):
        xy.pie_chart(labels, values)


def test_wind_rose_bands_are_their_own_count_not_the_cumulative_top() -> None:
    """`bar` measures its value as a height above `base`, so authoring
    `base + counts` stacked each band on its own offset twice: three
    observations reached radius 5 and every band above the first was too
    thick. The height is the band's count."""
    directions = np.array([0.0, 0.0, 0.0])
    speeds = np.array([1.0, 1.0, 9.0])
    chart = xy.wind_rose(directions, speeds, sectors=4, speed_bins=[2.0, 10.0])
    bars = [c for c in chart.children if getattr(c, "kind", None) == "bar"]
    heights = [float(np.asarray(b.y, dtype=float)[0]) for b in bars]
    bases = [float(np.asarray(b.props["base"], dtype=float)[0]) for b in bars]
    assert heights == [2.0, 1.0]  # two slow observations, one fast
    assert bases == [0.0, 2.0]
    spec, _ = chart.figure().build_payload_split()
    assert spec["y_axis"]["range"][1] == pytest.approx(3.0)


def test_wind_rose_tooltip_reports_band_count_and_direction() -> None:
    """A rose is the one polar composition where the angle IS data (a compass
    bearing), so it names the direction row back in and pairs it with the
    band's own count rather than the cumulative stack radius."""
    rng = np.random.default_rng(7)
    chart = xy.wind_rose(rng.uniform(0, 360, 120), rng.gamma(2.0, 2.0, 120), sectors=8)
    spec, _ = chart.figure().build_payload_split()
    tip = spec["tooltip"]
    assert tip["title"] == "{name}"
    assert tip["fields"] == ["x", "y"]
    assert tip["labels"]["y"] == "count"
    assert "direction" in tip["labels"]["x"]


def test_wedge_gap_is_a_constant_width_not_a_constant_angle() -> None:
    """A constant angular pad makes the seam `r · dtheta` wide, so it tapers to
    nothing at the hole — the spacing visibly narrows toward the centre. The
    gap is a length: the angular inset grows as the radius shrinks, so the arc
    removed per edge is the same number of px at every radius."""
    from xy._svg import _PolarProjection, polar_wedge_points

    project = _PolarProjection(
        {"theta_unit": "degrees"}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400}
    )
    plain = polar_wedge_points(project, 0.0, 90.0, 0.25, 1.0, steps=8)
    gapped = polar_wedge_points(project, 0.0, 90.0, 0.25, 1.0, steps=8, wedge_gap=12.0)
    assert plain and gapped

    def arc_inset(a: list, b: list, index: int) -> float:
        """Arc length (px) the gap removed at one sampled boundary point."""
        ax, ay = a[index]
        bx, by = b[index]
        radius = math.hypot(ax - 200.0, ay - 200.0)
        ta = math.atan2(200.0 - ay, ax - 200.0)
        tb = math.atan2(200.0 - by, bx - 200.0)
        return abs(ta - tb) * radius

    # First sample sits on the outer rim, last on the inner rim: the same 6 px
    # (half the gap) must come off each, or the seam tapers.
    outer = arc_inset(plain, gapped, 0)
    inner = arc_inset(plain, gapped, -1)
    assert outer == pytest.approx(6.0, abs=0.25), outer
    assert inner == pytest.approx(6.0, abs=0.25), inner


def test_pie_chart_ships_true_shares_and_a_pixel_gap() -> None:
    """The gap is carved by the renderer, so `width` stays the slice's real
    share — which is what makes the hovered share exact."""
    chart = xy.pie_chart(["a", "b", "c", "d"], [40.0, 30.0, 20.0, 10.0], pad=6.0)
    spec, _ = chart.figure().build_payload_split()
    widths = [t["bar"]["width"] for t in spec["traces"]]
    assert widths == pytest.approx([144.0, 108.0, 72.0, 36.0])
    assert sum(widths) == pytest.approx(360.0)
    assert all(t["style"]["wedge_gap"] == 6.0 for t in spec["traces"])


@pytest.mark.parametrize(
    ("axis_kwargs", "turn"),
    [({}, 2.0 * math.pi), ({"unit": "degrees"}, 360.0)],
)
def test_radar_spokes_follow_the_authored_angular_unit(axis_kwargs, turn) -> None:
    """Spokes are derived, so they must be generated in the unit the angular
    axis declares. Hard-coded radians against an authored degrees axis put
    0..2pi samples inside a 0..360 frame, squeezing the whole radar into the
    first 6.28 degrees."""
    chart = xy.radar_chart(
        ["a", "b", "c", "d"], xy.area([1.0, 2.0, 3.0, 2.0]), xy.theta_axis(**axis_kwargs)
    )
    spec, _ = chart.figure().build_payload_split()
    assert spec["x_axis"]["range"][1] == pytest.approx(turn)
    mark = next(c for c in chart.children if getattr(c, "kind", None) in ("area", "line"))
    # Evenly spaced across the turn, closed back at a full turn.
    assert list(mark.x) == pytest.approx([turn * i / 4.0 for i in range(5)])


@pytest.mark.parametrize(
    ("label", "build"),
    [
        (
            "secondary radial",
            lambda: xy.polar_chart(
                xy.line([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]),
                xy.line([0.0, 1.0, 2.0], [2.0, 4.0, 6.0], y_axis="y2"),
                xy.r_axis(id="y2", domain=(0.0, 8.0)),
            ),
        ),
        (
            "secondary angular",
            lambda: xy.polar_chart(
                xy.line([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]),
                xy.line([0.0, 1.0, 2.0], [2.0, 4.0, 6.0], x_axis="x2"),
                xy.x_axis(id="x2"),
            ),
        ),
    ],
)
def test_polar_refuses_a_secondary_axis(label, build) -> None:
    """A second axis bound and validated like a Cartesian one, then every
    renderer read only the primary pair. Overlapping ranges drew the secondary
    series *pixel-identical* to the primary — inviting the reader to decode it
    against a tick ladder it does not belong to — and a disjoint range culled
    it away entirely, while the axis still got a straight Cartesian spine in
    the gutter of a disc. A plausible wrong picture is worse than an error."""
    with pytest.raises(ValueError, match="single angular"):
        build().figure().build_payload_split()


@pytest.mark.parametrize("scale", ["log", "symlog"])
def test_polar_refuses_a_non_linear_angular_axis(scale) -> None:
    """A non-linear angle was accepted, serialized, and then honoured by
    exactly one renderer: the client scaled theta before projecting while the
    static exporters ignored the scale outright, so one figure pointed the same
    datum at opposite sides of the disc depending on where it was drawn."""
    chart = xy.polar_chart(xy.line([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), xy.theta_axis(type_=scale))
    with pytest.raises(ValueError, match="angular axis"):
        chart.figure().build_payload_split()

    # A log *radial* axis stays supported — only the angle must be linear.
    xy.polar_chart(
        xy.line([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), xy.r_axis(type_="log")
    ).figure().build_payload_split()


@pytest.mark.parametrize(
    ("sector", "requested", "expected"),
    [
        ((300.0, 420.0), [300.0, 330.0, 0.0, 30.0, 60.0], [300.0, 330.0, 0.0, 30.0, 60.0]),
        ((-30.0, 30.0), [330.0, 340.0, 350.0, 0.0, 10.0, 20.0, 30.0], None),
        # A sector that does not cross the seam must still drop what is outside.
        ((0.0, 180.0), [0.0, 45.0, 90.0, 200.0, -10.0], [0.0, 45.0, 90.0]),
    ],
)
def test_seam_crossing_sector_keeps_its_explicit_theta_ticks(sector, requested, expected) -> None:
    """Tick trimming was linear while mark culling is modular, so a sector
    spanning the 0/turn seam threw away every tick authored on the far side of
    it: a *data point* at theta = 20 plotted inside sector (-30, 30) while a
    *tick* at 20 silently vanished."""
    axis = {
        "range": sector,
        "sector": sector,
        "theta_unit": "degrees",
        "kind": "linear",
        "tick_values": requested,
        "minor_tick_values": [315.0, 15.0, 45.0],
    }
    ticks, _labelled, _step = axis_ticks(axis, 400.0, True)
    assert ticks == pytest.approx(expected if expected is not None else requested)
    if sector == (300.0, 420.0):
        # Minor ticks trim through the same window, and were dropped too. This
        # exercises the trimming helper directly: `minor_tick_values` on a polar
        # axis is now refused at payload build (no renderer draws minor rings or
        # spokes), so the branch is correct-but-dormant rather than reachable
        # from a figure. See spec/design/polar-axes.md §9.
        assert minor_axis_ticks(axis) == pytest.approx([315.0, 15.0, 45.0])


def test_cartesian_tick_trimming_is_unchanged_by_the_modular_window() -> None:
    """The modular window is angular-only: a Cartesian axis must still reject
    values outside its range rather than wrap them into it."""
    axis = {"range": (0.0, 10.0), "kind": "linear", "tick_values": [-1.0, 0.0, 5.0, 10.0, 11.0]}
    ticks, _labelled, _step = axis_ticks(axis, 400.0, True)
    assert ticks == pytest.approx([0.0, 5.0, 10.0])


def test_polar_refuses_reverse_on_the_angular_axis() -> None:
    """`reverse` is the Cartesian flip switch; the angular axis spells the same
    idea as `direction`. It rode the wire as `"reverse": true` and every
    renderer ignored it, so the axis silently drew unreversed."""
    with pytest.raises(ValueError, match="reverse=True on the angular axis"):
        xy.polar_chart(
            xy.line([0.0, 1.0], [1.0, 2.0]), xy.theta_axis(reverse=True)
        ).figure().build_payload_split()

    # The switch that does work, and the radial flip, stay supported.
    xy.polar_chart(
        xy.line([0.0, 1.0], [1.0, 2.0]), xy.theta_axis(direction="clockwise")
    ).figure().build_payload_split()
    xy.polar_chart(
        xy.line([0.0, 1.0], [1.0, 2.0]), xy.r_axis(reverse=True)
    ).figure().build_payload_split()


def test_wind_rose_names_a_fractional_sector_count() -> None:
    """A non-integer count reached np.bincount's `minlength` and surfaced as a
    raw NumPy TypeError naming neither the parameter nor the mistake."""
    with pytest.raises(ValueError, match="whole number"):
        xy.wind_rose([10.0, 20.0], [1.0, 2.0], sectors=8.5)
    xy.wind_rose([10.0, 20.0], [1.0, 2.0], sectors=8).figure().build_payload_split()


@pytest.mark.parametrize(
    ("label", "build"),
    [
        (
            "log radial annihilates every row",
            lambda: xy.polar_chart(
                xy.area([0.0, 90.0, 180.0], [1.0, 2.0, 3.0]),
                xy.theta_axis(unit="degrees"),
                xy.r_axis(type_="log"),
            ),
        ),
        (
            "all-NaN radar polygon",
            lambda: xy.radar_chart(["a", "b", "c"], xy.area([float("nan")] * 3)),
        ),
        (
            "area entirely outside the sector",
            lambda: xy.polar_chart(
                xy.area([200.0, 220.0, 240.0], [1.0, 2.0, 3.0]),
                xy.theta_axis(unit="degrees", sector=(0.0, 90.0)),
            ),
        ),
    ],
)
def test_fully_culled_polar_area_exports_without_malformed_path(label, build) -> None:
    """`_curve_path` returned "" for a fully culled trace and the area join
    stitched that into `" L  Z"` — malformed path data that also reached the
    PDF converter's `_parse_path`. An empty vertex array additionally reached
    the native poly-path builder, which rejects a zero-length buffer, so the
    export raised instead of drawing nothing."""
    figure = build().figure()
    doc = figure.to_svg()
    for d in re.findall(r'<path d="([^"]*)"', doc):
        assert d.strip(), f"{label}: empty path data"
        assert not d.strip().startswith("L"), f"{label}: path opens with a lineto: {d[:40]}"
        assert " L  " not in d, f"{label}: malformed join: {d[:60]}"
    assert figure.to_image(format="pdf")[:5] == b"%PDF-"


def test_pie_chart_renders_a_zero_valued_slice() -> None:
    """A zero-valued category is ordinary in aggregated data and `pie_chart`
    accepts it (values are validated finite and non-negative), but a zero span
    reached `bar(width=...)` and died as "bar width must be positive" — an
    error from a layer below naming neither pie_chart nor the label."""
    doc = xy.pie_chart(["Direct", "Partner", "Organic"], [40.0, 0.0, 20.0]).figure().to_svg()
    assert "Direct" in doc and "Organic" in doc
    # The empty category draws no wedge rather than a zero-width one.
    assert "Partner" not in doc
    xy.pie_chart(["a", "b"], [1.0, 0.0]).figure().to_image(format="pdf")


@pytest.mark.parametrize(
    ("label", "build"),
    [
        ("polar_chart", lambda **k: xy.polar_chart(xy.line([0.0, 1.0], [1.0, 2.0]), **k)),
        ("pie_chart", lambda **k: xy.pie_chart(["a", "b"], [1.0, 2.0], **k)),
        ("radar_chart", lambda **k: xy.radar_chart(["a", "b", "c"], xy.area([1.0, 2.0, 3.0]), **k)),
        ("wind_rose", lambda **k: xy.wind_rose([10.0, 20.0], [1.0, 2.0], **k)),
    ],
)
def test_polar_helpers_refuse_a_cartesian_coords_override(label, build) -> None:
    """`coords` is the only thing making these helpers polar — `Chart.kind` is
    inert — so `setdefault` let `coords="cartesian"` return unlabelled rects
    with no axes, silently dropping any authored theta/r axis. It also
    re-opened every refusal `_validate_coords` adds, since that method returns
    early for a non-polar figure."""
    with pytest.raises(ValueError, match="this chart is polar"):
        build(coords="cartesian")
    build().figure().build_payload_split()


def test_polar_refuses_a_time_angular_axis_by_resolved_kind() -> None:
    """The declared spelling `theta_axis(type_="time")` was refused while an
    *inferred* datetime column shipped: kind="time" pinned to a fixed 0..2pi
    range, so consecutive days wrapped the disc billions of times and the
    spokes were labelled as radians."""
    days = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(6)]
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    with pytest.raises(ValueError, match="time angular axis"):
        xy.polar_chart(xy.line(days, values)).figure().build_payload_split()

    # A time *radial* axis stays supported, and cartesian time is untouched.
    xy.polar_chart(xy.line(values, days)).figure().build_payload_split()
    xy.line_chart(xy.line(days, values)).figure().build_payload_split()


@pytest.mark.parametrize("kind", ["bar", "column", "errorbar"])
def test_polar_direct_ceiling_covers_every_capped_mark(kind) -> None:
    """The gate was narrowed to {line, scatter, area} so heatmap/contour cell
    grids could exceed the *point* ceiling, which un-capped bar/column/errorbar
    as collateral — and a polar bar is the most expensive mark there is,
    2*(96+1) verts per wedge against a cartesian quad's 4."""
    n = POLAR_DIRECT_CEILING + 1
    theta = np.linspace(0.0, 360.0, n)
    values = np.ones(n)
    marks = {
        "bar": lambda: xy.bar(theta, values),
        "column": lambda: xy.column(theta, values),
        "errorbar": lambda: xy.errorbar(theta, values, yerr=values * 0.1),
    }
    with pytest.raises(ValueError, match="polar ceiling"):
        xy.polar_chart(marks[kind]()).figure().build_payload_split()


def _text_boxes(doc: str) -> list[tuple[float, float, str, float]]:
    boxes = []
    for match in re.finditer(r"<text([^>]*)>([^<]*)</text>", doc):
        attrs, text = match.group(1), match.group(2)
        x = re.search(r'\bx="([-\d.]+)"', attrs)
        y = re.search(r'\by="([-\d.]+)"', attrs)
        size = re.search(r'font-size="([\d.]+)"', attrs)
        if x and y and text.strip():
            boxes.append(
                (
                    float(x.group(1)),
                    float(y.group(1)),
                    text.strip(),
                    float(size.group(1)) if size else 11.0,
                )
            )
    return boxes


def _overlapping_pairs(boxes) -> int:
    count = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            x1, y1, t1, f1 = boxes[i]
            x2, y2, t2, f2 = boxes[j]
            w1, w2 = len(t1) * f1 * 0.55, len(t2) * f2 * 0.55
            if abs(x1 - x2) < (w1 + w2) / 2 and abs(y1 - y2) < (f1 + f2) / 2:
                count += 1
    return count


@pytest.mark.parametrize(
    ("hole", "size"),
    [(0.7, 390), (0.6, 700), (0.0, 390)],
)
def test_radial_tick_labels_do_not_overlap(hole, size) -> None:
    """Radial labels march along a 22.5-degree spoke, so their usable run is the
    annulus width projected onto it — about a fifth of the plot. Sizing the tick
    request off the full plot height packed a height's worth of labels into that
    fifth, and the polar path skips the collision pass that would thin them.
    Not a narrow-viewport effect: the 700px case overlapped worse than 390px."""
    chart = xy.polar_chart(
        xy.line([0.0, 90.0, 180.0, 270.0], [10.0, 20.0, 30.0, 40.0]),
        xy.theta_axis(unit="degrees"),
        xy.r_axis(hole=hole, domain=(0.0, 60.0)),
        width=size,
        height=size,
    )
    boxes = _text_boxes(chart.figure().to_svg())
    assert boxes, "no tick labels emitted"
    assert _overlapping_pairs(boxes) == 0


def test_negative_radial_autorange_keeps_its_pad() -> None:
    """`min(0.0, lo)` collapsed to `lo` once the data went negative, throwing the
    pad away and producing the picture the branch exists to forbid: four
    readings within 0.7% of each other resolved to [-100.8, -100.1] and drew as
    a full-disc star. Centre origin is only meaningful when zero ends the
    range."""

    def radial_range(values):
        spec, _ = (
            xy.polar_chart(xy.line(list(range(len(values))), values)).figure().build_payload_split()
        )
        return spec["y_axis"]["range"]

    lo, hi = radial_range([-100.5, -100.2, -100.8, -100.1])
    assert lo < -100.8 and hi > -100.1, (lo, hi)

    # Non-negative data keeps the centre-origin contract exactly as before.
    assert radial_range([100.5, 100.2, 100.8, 100.1]) == [0.0, 100.8]
    assert radial_range([1.0, 2.0, 3.0, 4.0]) == [0.0, 4.0]


def test_get_theta_offset_matches_matplotlibs_zero_to_two_pi_mapping() -> None:
    """Matplotlib's mapping is 0..2pi ccw from east, so "S" reads 3*pi/2. The
    getter returned the render tables' -pi/2 — the same angle, but a compat
    getter has to return matplotlib's number, and the negative breaks both
    `get_theta_offset() > 0` and a round-trip through `set_theta_offset`."""
    from xy import pyplot as plt

    expected = {
        "E": 0.0,
        "NE": math.pi / 4,
        "N": math.pi / 2,
        "NW": 3 * math.pi / 4,
        "W": math.pi,
        "SW": 5 * math.pi / 4,
        "S": 3 * math.pi / 2,
        "SE": 7 * math.pi / 4,
    }
    ax = plt.figure().add_subplot(projection="polar")
    for location, radians in expected.items():
        ax.set_theta_zero_location(location)
        assert ax.get_theta_offset() == pytest.approx(radians), location


def test_polar_paths_keep_the_authored_angular_order() -> None:
    """Theta is the order marks are JOINED in, not a domain to be scanned, but
    `Figure.line`/`area` sorted x at ingest for the M4 precondition. A track
    crossing the 0/turn seam (350 -> 10) or doubling back was redrawn as an
    ascending-angle fan. Safe to skip because polar forces tier="direct"."""

    def wire_order(chart, which="x"):
        spec, blob = chart.figure().build_payload_split()
        column = spec["columns"][spec["traces"][0][which]]
        raw = np.frombuffer(
            blob[column["buf"]],
            dtype=np.float32,
            count=column["len"],
            offset=column["byte_offset"],
        )
        return [round(float(v), 3) for v in raw / (column["scale"] or 1.0) + column["offset"]]

    theta = [350.0, 10.0, 30.0, 5.0]
    radius = [1.0, 2.0, 3.0, 4.0]
    for mark in (xy.line, xy.area):
        chart = xy.polar_chart(mark(theta, radius), xy.theta_axis(unit="degrees"))
        assert wire_order(chart) == theta, mark.__name__
        assert wire_order(chart, "y") == radius, mark.__name__

    # Cartesian keeps its sort — the LOD contract still needs it there.
    assert wire_order(xy.line_chart(xy.line(theta, radius))) == sorted(theta)


def test_wind_rose_refuses_bins_that_would_drop_an_observation() -> None:
    """The default path rounds its top edge up so it covers the fastest
    observation; authored edges were taken as given, so `speed_bins=[10, 20]`
    counted 2 of 3 observations when one blew at 25 — the rose under-reported
    its own input silently."""
    with pytest.raises(ValueError, match="below the fastest observation"):
        xy.wind_rose([10.0, 10.0, 10.0], [5.0, 15.0, 25.0], speed_bins=[10.0, 20.0])
    with pytest.raises(ValueError, match="must all be finite"):
        xy.wind_rose([10.0], [5.0], speed_bins=[10.0, float("inf")])

    # Edges that do cover the data still work, and count every observation.
    chart = xy.wind_rose([10.0, 10.0, 10.0], [5.0, 15.0, 25.0], speed_bins=[10.0, 20.0, 30.0])
    counted = sum(
        float(np.nansum(np.asarray(child.y, dtype=float)))
        for child in chart.children
        if getattr(child, "y", None) is not None
    )
    assert counted == pytest.approx(3.0)


@pytest.mark.parametrize("span", [float("nan"), float("inf"), -float("inf")])
def test_polar_bar_segments_matches_the_client_on_a_degenerate_span(span) -> None:
    """The JS mirror guards `!Number.isFinite(span)` and falls back to the
    full-turn count; Python only guarded `turn > 0`, so `math.ceil` raised
    ValueError on NaN and OverflowError on infinity — the two renderers
    disagreed about what a degenerate wedge costs, one drawing it and the other
    crashing."""
    from xy.config import POLAR_BAR_SEGMENTS, polar_bar_segments

    result = polar_bar_segments(span, 360.0)
    assert result == POLAR_BAR_SEGMENTS
    assert isinstance(result, int)


def test_every_polar_public_name_is_typed_for_static_analysis() -> None:
    """The lazy `__getattr__` surface makes `from xy import polar_chart` resolve
    to `Any` unless the name is also in the TYPE_CHECKING import block, which
    silently drops signatures, completion and argument checking."""
    source = (ROOT / "python/xy/__init__.py").read_text()
    start = source.index("    from .components import (")
    block = source[start : source.index(")", start)]
    for name in (
        "pie_chart",
        "polar_bar_chart",
        "polar_chart",
        "r_axis",
        "radar_chart",
        "theta_axis",
        "wind_rose",
    ):
        assert f"        {name},\n" in block, name


def test_time_radius_is_exempt_from_the_centre_origin_default() -> None:
    """Zero is the Unix epoch on a time axis, not a centre. Pinning there
    spanned the disc from 1970 to the data and parked every ring on the rim; a
    singleton instant resolved to [0.0, 1767225600000.0]. Time takes the
    ordinary padded window, exactly as the cartesian axis does."""
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    angles = [0.0, 1.0, 2.0]

    polar, _ = xy.polar_chart(xy.line(angles, [instant] * 3)).figure().build_payload_split()
    cartesian, _ = xy.line_chart(xy.line(angles, [instant] * 3)).figure().build_payload_split()
    assert polar["y_axis"]["range"][0] != 0.0
    assert polar["y_axis"]["range"] == cartesian["y_axis"]["range"]

    # Numeric radii keep the centre-origin contract untouched.
    numeric, _ = xy.polar_chart(xy.line(angles, [5.0, 5.0, 5.0])).figure().build_payload_split()
    assert numeric["y_axis"]["range"] == [0.0, 5.0]


def _polar_zoom_flag(chart) -> object:
    spec, _ = chart.figure().build_payload_split()
    return spec.get("interaction", {}).get("zoom", "absent")


@pytest.mark.parametrize(
    ("label", "build"),
    [
        ("polar_chart", lambda *c, **k: xy.polar_chart(xy.line([0.0, 1.0], [1.0, 2.0]), *c, **k)),
        (
            "polar_bar_chart",
            lambda *c, **k: xy.polar_bar_chart(xy.bar([0.0], [1.0], width=1.0), *c, **k),
        ),
        ("pie_chart", lambda *c, **k: xy.pie_chart(["a", "b"], [1.0, 2.0], *c, **k)),
        (
            "radar_chart",
            lambda *c, **k: xy.radar_chart(["a", "b", "c"], xy.area([1.0, 2.0, 3.0]), *c, **k),
        ),
    ],
)
def test_polar_ships_zoom_disabled_by_default(label, build) -> None:
    """Polar zoom is OFF by default and says so on the wire (§8).

    The centre is a fixed point of the transform and r_lo is pinned, so a
    zoom-in crops the rim while the geometry stays welded to the middle of the
    disc — on a pie, radial bar, or radar (constant rim, or a fixed 0..1 frame)
    that reads as broken rather than as navigation. The flag must be *explicit*
    rather than omitted: the client cannot re-derive it, because `Chart.kind`
    never reaches the payload and every polar figure looks identical to it.
    """
    assert _polar_zoom_flag(build()) is False, label
    # Both opt-in spellings win over the default.
    assert _polar_zoom_flag(build(zoom=True)) is True, label
    assert _polar_zoom_flag(build(xy.interaction_config(zoom=True))) is True, label


def test_wind_rose_is_the_polar_composition_that_keeps_zoom() -> None:
    """A wind rose's radius is a frequency COUNT, so scaling the outer ring
    against a pinned zero is the useful gesture — it magnifies the short
    sectors of a rose dominated by one prevailing direction. It is the one
    exception the polar zoom-off default is written around, and an author can
    still turn it off."""
    directions = [0.0, 45.0, 90.0, 180.0, 270.0]
    speeds = [1.0, 4.0, 9.0, 3.0, 6.0]
    assert _polar_zoom_flag(xy.wind_rose(directions, speeds)) is True
    assert _polar_zoom_flag(xy.wind_rose(directions, speeds, zoom=False)) is False
    assert (
        _polar_zoom_flag(xy.wind_rose(directions, speeds, xy.interaction_config(zoom=False)))
        is False
    )
    # `None` is "unset" everywhere else in the interaction API, so it must keep
    # the rose's own default rather than fall through to the polar one. A wrapper
    # forwarding an `Optional[bool]` would otherwise turn zoom OFF by passing the
    # value that means "I have no opinion".
    assert _polar_zoom_flag(xy.wind_rose(directions, speeds, zoom=None)) is True


#: Every drag action polar refuses, derived from the public `DefaultDragAction`
#: type rather than hand-listed: a hand-written subset had already drifted (it
#: missed `select-y`), and deriving it means a newly added drag action is covered
#: the moment it exists — either polar grows a tool for it or this test fails.
_POLAR_INERT_DRAG_ACTIONS = sorted(
    set(typing.get_args(components.DefaultDragAction)) - {"auto", "none"}
)


def test_the_inert_polar_drag_action_list_is_exhaustive() -> None:
    """Guard the derivation above: `auto`/`none` are the only legal polar values,
    so every other member of the type must be in the refusal list."""
    assert set(_POLAR_INERT_DRAG_ACTIONS) == {
        "pan",
        "zoom",
        "select",
        "select-x",
        "select-y",
        "select-lasso",
    }


@pytest.mark.parametrize("action", _POLAR_INERT_DRAG_ACTIONS)
def test_polar_refuses_every_inert_drag_action(action) -> None:
    """A disc has no drag tools, so only `auto`/`none` are meaningful (§8).

    The client returns `[]` for `pan_axes` and forces `box_zoom`/`select`/`brush`
    off under polar whatever the flags say, so each of these was accepted and
    then resolved to no usable tool. `zoom` was the worst of them: validation
    read an absent `zoom` as enabled while the payload resolved it to `False`,
    so the figure shipped a self-contradicting
    `{"zoom": false, "default_drag_action": "zoom"}`.
    """
    for build in (
        lambda **k: xy.polar_chart(xy.scatter([0.0, 1.0], [1.0, 2.0]), **k),
        lambda **k: xy.pie_chart(["a", "b"], [1.0, 2.0], **k),
        lambda **k: xy.wind_rose([10.0, 20.0, 30.0], [1.0, 2.0, 3.0], **k),
    ):
        with pytest.raises(ValueError, match="does not support default_drag_action"):
            build(default_drag_action=action).figure().build_payload_split()
        # Explicitly enabling the capability does not make the drag tool exist.
        with pytest.raises(ValueError, match="does not support default_drag_action"):
            build(zoom=True, default_drag_action=action).figure().build_payload_split()

    # `auto` and `none` stay legal — they are what polar already resolves to.
    for legal in ("auto", "none"):
        spec, _ = (
            xy.polar_chart(xy.line([0.0, 1.0], [1.0, 2.0]), default_drag_action=legal)
            .figure()
            .build_payload_split()
        )
        assert spec["interaction"]["default_drag_action"] == legal


def test_cartesian_drag_action_validation_is_unchanged() -> None:
    """The polar refusal must not leak into Cartesian charts, whose drag tools
    are real; only a capability the config itself turned off still raises."""
    spec, _ = (
        xy.line_chart(xy.line([0.0, 1.0], [1.0, 2.0]), default_drag_action="zoom")
        .figure()
        .build_payload_split()
    )
    assert spec["interaction"]["default_drag_action"] == "zoom"
    # Absent zoom stays absent on the wire for Cartesian (§5.2).
    assert "zoom" not in spec["interaction"]
    with pytest.raises(ValueError, match="requires navigation and pan"):
        xy.line_chart(
            xy.line([0.0, 1.0], [1.0, 2.0]), pan=False, default_drag_action="pan"
        ).figure().build_payload_split()


def test_explicit_reset_axes_still_grants_polar_reset_without_zoom() -> None:
    """`reset_axes` is the documented escape hatch, and it survives zoom=False.

    `_resetAxisPolicy` returns an authored `reset_axes` verbatim instead of
    deriving pan-axes union zoom-axes, so Fit Data / Reset View render and
    double-click restores those axes even with zoom off — which matters for a
    polar chart whose view moves through linked axes or state-driven updates
    rather than through a gesture. The docs must not promise reset is absent
    outright.
    """
    theta, r = _rose()
    spec, _ = (
        xy.polar_chart(xy.line(theta, r), xy.interaction_config(reset_axes=("y",)))
        .figure()
        .build_payload_split()
    )
    assert spec["interaction"]["zoom"] is False
    assert spec["interaction"]["reset_axes"] == ["y"]


def test_interaction_config_opts_a_polar_chart_back_into_zoom() -> None:
    """The documented escape hatch: an `interaction_config` child is applied
    after chart props, so it is the last word on either side of the default."""
    theta, r = _rose()
    assert _polar_zoom_flag(xy.polar_chart(xy.line(theta, r))) is False
    assert (
        _polar_zoom_flag(xy.polar_chart(xy.line(theta, r), xy.interaction_config(zoom=True)))
        is True
    )
    assert _polar_zoom_flag(xy.pie_chart(["a", "b"], [1.0, 2.0], zoom=True)) is True
    # A cartesian figure is untouched: its zoom stays absent so the client keeps
    # resolving the ordinary `True` default (pan-and-zoom-configuration §5.2).
    assert _polar_zoom_flag(xy.line_chart(xy.line([0.0, 1.0], [1.0, 2.0]))) == "absent"


def test_pyplot_polar_projection_inherits_the_zoom_default() -> None:
    """`coords="polar"` carries the default, not the helper factories, so a
    hand-built `xy.chart(coords="polar")` and the shim's `projection="polar"`
    get it too — the rule belongs to the coordinate system, and there is one of
    it rather than one per factory."""
    import xy.pyplot as plt

    theta, r = _rose()
    assert _polar_zoom_flag(xy.chart(xy.line(theta, r), coords="polar")) is False

    figure, ax = plt.subplots(subplot_kw={"projection": "polar"})
    ax.plot([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    try:
        charts = figure._charts()
        assert charts
        for chart in charts:
            spec, _ = chart.figure().build_payload_split()
            assert spec["interaction"]["zoom"] is False
    finally:
        plt.close(figure)
