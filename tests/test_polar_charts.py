"""Polar charts end to end: wire shape, refusals, and cross-renderer agreement.

The transform itself is pinned by `test_polar_transform.py` against shared
fixtures. This file checks that each renderer actually *uses* it — the failure
mode two export-parity audits have already found in this repo is a renderer
quietly keeping its own geometry while the others move.
"""

from __future__ import annotations

import math
import re
from itertools import pairwise

import numpy as np
import pytest

import xy
from xy._svg import _PolarProjection, layout


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
    # One point at theta=0, r=max: due right of centre, on the outer ring.
    theta = np.array([0.0, math.pi / 2, math.pi])
    r = np.array([1.0, 1.0, 1.0])
    chart = xy.polar_chart(xy.scatter(theta, r, size=9.0, color="#000000"), width=400, height=400)
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
    counted = sum(float(np.asarray(b.y).sum() - np.asarray(b.props["base"]).sum()) for b in bars)
    assert counted == pytest.approx(500.0)


def test_wind_rose_bands_stack_without_gaps() -> None:
    rng = np.random.default_rng(4)
    chart = xy.wind_rose(rng.uniform(0, 360, 300), rng.gamma(2.0, 2.0, 300), sectors=8)
    bars = [c for c in chart.children if getattr(c, "kind", None) == "bar"]
    for lower, upper in pairwise(bars):
        assert np.asarray(upper.props["base"]) == pytest.approx(np.asarray(lower.y))


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
