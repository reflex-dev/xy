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
