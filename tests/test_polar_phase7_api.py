"""Phase-7 polar API and wire contracts (geometry is tested by renderer suites)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import xy
import xy.pyplot as plt
from xy.config import POLAR_MARK_KINDS, PROTOCOL_VERSION


@pytest.fixture(autouse=True)
def _close_pyplot_figures():
    yield
    plt.close("all")


def _line() -> xy.Mark:
    return xy.line([0.0, math.pi / 2.0, math.pi], [1.0, 2.0, 3.0])


def _spec(*children: xy.Component) -> dict:
    spec, _buffers = xy.polar_chart(*children).figure().build_payload_split()
    return spec


def test_protocol_v13_is_locked_to_the_client() -> None:
    header = Path(__file__).parents[1] / "js" / "src" / "00_header.ts"
    assert PROTOCOL_VERSION == 13
    assert f"PROTOCOL = {PROTOCOL_VERSION};" in header.read_text()


def test_phase7_marks_are_legal_polar_primitives() -> None:
    assert {
        "line",
        "scatter",
        "area",
        "bar",
        "column",
        "heatmap",
        "contour",
        "errorbar",
    } == POLAR_MARK_KINDS


def test_theta_sector_and_grid_shape_reach_the_wire() -> None:
    spec = _spec(
        _line(),
        xy.theta_axis(sector=(0.0, math.pi), grid_shape="linear"),
    )
    assert spec["x_axis"]["sector"] == pytest.approx([0.0, math.pi])
    assert spec["x_axis"]["grid_shape"] == "linear"
    # Numeric theta keeps its independent full-turn data/tick range.
    assert spec["x_axis"]["range"] == pytest.approx([0.0, 2.0 * math.pi])


def test_theta_domain_is_a_sector_alias_not_the_data_range() -> None:
    spec = _spec(
        xy.line([0.0, 90.0, 180.0], [1.0, 2.0, 3.0]),
        xy.theta_axis(unit="degrees", domain=(30.0, 150.0)),
    )
    assert spec["x_axis"]["sector"] == pytest.approx([30.0, 150.0])
    assert spec["x_axis"]["range"] == pytest.approx([0.0, 360.0])
    assert "domain" not in spec["x_axis"]


def test_polar_defaults_are_resolved_on_the_wire() -> None:
    spec = _spec(_line())
    assert spec["x_axis"]["sector"] == pytest.approx([0.0, 2.0 * math.pi])
    assert spec["x_axis"]["grid_shape"] == "circular"
    assert spec["y_axis"]["hole"] == 0.0
    assert "r_origin" not in spec["y_axis"]


@pytest.mark.parametrize(
    ("axis", "match"),
    [
        (lambda: xy.theta_axis(grid_shape="polygon"), "grid_shape"),
        (lambda: xy.r_axis(hole=-0.01), "at least 0"),
        (lambda: xy.r_axis(hole=1.0), "less than 1"),
        (lambda: xy.r_axis(hole=0.2, origin=-1.0), "mutually exclusive"),
    ],
)
def test_polar_axis_options_validate_eagerly(axis, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        axis()


@pytest.mark.parametrize(
    ("unit", "sector"),
    [
        ("radians", (0.0, 2.0 * math.pi + 0.01)),
        ("degrees", (0.0, 360.01)),
    ],
)
def test_sector_must_not_exceed_one_turn(unit: str, sector: tuple[float, float]) -> None:
    chart = xy.polar_chart(_line(), xy.theta_axis(unit=unit, sector=sector))
    with pytest.raises(ValueError, match="one full turn"):
        chart.figure()


def test_categorical_theta_keeps_category_index_range() -> None:
    spec = _spec(
        xy.scatter(["north", "east", "south"], [1.0, 2.0, 3.0]),
        xy.theta_axis(sector=(0.0, math.pi)),
    )
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["north", "east", "south"]
    assert spec["x_axis"]["range"] == pytest.approx([0.0, 2.0])
    assert spec["x_axis"]["sector"] == pytest.approx([0.0, math.pi])


def test_radial_hole_and_origin_reach_the_wire() -> None:
    hole = _spec(_line(), xy.r_axis(domain=(0.0, 4.0), hole=0.25))
    assert hole["y_axis"]["hole"] == pytest.approx(0.25)
    assert "r_origin" not in hole["y_axis"]

    origin = _spec(_line(), xy.r_axis(domain=(0.0, 4.0), origin=-1.0))
    assert origin["y_axis"]["hole"] == 0.0
    assert origin["y_axis"]["r_origin"] == pytest.approx(-1.0)


@pytest.mark.parametrize(
    ("origin", "match"),
    [
        (1.5, "must not exceed the resolved radial minimum"),
        (4.0, "less than the resolved radial maximum"),
    ],
)
def test_radial_origin_must_not_invert_visible_radius(origin: float, match: str) -> None:
    chart = xy.polar_chart(_line(), xy.r_axis(domain=(1.0, 4.0), origin=origin))
    with pytest.raises(ValueError, match=match):
        chart.figure().build_payload_split()


def test_reversed_radial_origin_extends_from_the_center_side_limit() -> None:
    spec = _spec(
        _line(),
        xy.r_axis(domain=(1.0, 4.0), reverse=True, origin=5.0),
    )
    assert spec["y_axis"]["range"] == pytest.approx([4.0, 1.0])
    assert spec["y_axis"]["r_origin"] == pytest.approx(5.0)

    inside = xy.polar_chart(
        _line(),
        xy.r_axis(domain=(1.0, 4.0), reverse=True, origin=3.0),
    )
    with pytest.raises(ValueError, match="must not be less than the resolved radial maximum"):
        inside.figure().build_payload_split()

    beyond_outer = xy.polar_chart(
        _line(),
        xy.r_axis(domain=(1.0, 4.0), reverse=True, origin=1.0),
    )
    with pytest.raises(ValueError, match="must be greater than the resolved radial minimum"):
        beyond_outer.figure().build_payload_split()


def test_log_radial_origin_must_be_positive() -> None:
    chart = xy.polar_chart(_line(), xy.r_axis(type_="log", origin=0.0))
    with pytest.raises(ValueError, match="must be positive"):
        chart.figure()


def test_log_radial_autorange_never_reintroduces_zero() -> None:
    spec = _spec(
        xy.line([0.0, math.pi / 2.0, math.pi], [1.0, 10.0, 100.0]),
        xy.r_axis(type_="log"),
    )
    assert spec["y_axis"]["scale"] == "log"
    assert spec["y_axis"]["range"] == pytest.approx([1.0, 100.0])
    assert spec["y_axis"]["range"][0] > 0.0


def test_large_polar_heatmap_is_not_subject_to_point_trace_ceiling() -> None:
    # 451² cells exceed POLAR_DIRECT_CEILING while remaining a compact grid
    # payload; the ceiling protects point primitives, not raster cells.
    grid = np.zeros((451, 451), dtype=np.float64)
    spec = _spec(xy.heatmap(grid))
    assert spec["traces"][0]["kind"] == "heatmap"
    assert spec["traces"][0]["n_marks"] == grid.size


@pytest.mark.parametrize("annotation", [xy.hline(1.5), xy.x_band(0.2, 0.8)])
def test_polar_rule_and_band_annotations_fail_loudly(annotation: xy.Annotation) -> None:
    chart = xy.polar_chart(_line(), annotation)
    with pytest.raises(ValueError, match="does not support rule/band annotations"):
        chart.figure().build_payload_split()


def test_pyplot_sector_and_rorigin_route_to_core_wire() -> None:
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    ax.plot([0.0, math.pi / 2.0, math.pi], [0.0, 1.0, 2.0])
    ax.set_thetamin(30.0)
    ax.set_thetamax(270.0)
    ax.set_rlim(0.0, 3.0)
    ax.set_rorigin(-1.0)

    assert ax.get_thetamin() == pytest.approx(30.0)
    assert ax.get_thetamax() == pytest.approx(270.0)
    assert ax.get_rorigin() == pytest.approx(-1.0)

    spec, _buffers = fig._charts()[0].figure().build_payload_split()
    assert spec["x_axis"]["sector"] == pytest.approx([math.radians(30.0), math.radians(270.0)])
    assert spec["y_axis"]["r_origin"] == pytest.approx(-1.0)


def test_pyplot_theta_limits_share_xlim_state_and_last_call_wins() -> None:
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    ax.plot([0.0, math.pi / 2.0, math.pi], [1.0, 2.0, 3.0])

    assert ax.get_xlim() == pytest.approx((0.0, 2.0 * math.pi))
    assert (ax.get_thetamin(), ax.get_thetamax()) == pytest.approx((0.0, 360.0))
    ax.set_thetagrids([0.0, 90.0, 180.0, 270.0])
    assert ax.get_xlim() == pytest.approx((0.0, 2.0 * math.pi))
    spec, _buffers = fig._charts()[0].figure().build_payload_split()
    assert spec["x_axis"]["sector"] == pytest.approx([0.0, 2.0 * math.pi])

    ax.set_thetamin(30.0)
    ax.set_thetamax(120.0)
    assert ax.get_xlim() == pytest.approx((math.radians(30.0), math.radians(120.0)))
    spec, _buffers = fig._charts()[0].figure().build_payload_split()
    assert spec["x_axis"]["sector"] == pytest.approx(ax.get_xlim())

    # set_xlim is the same polar view state and, as the later call, wins.
    ax.set_xlim(0.0, math.pi)
    assert (ax.get_thetamin(), ax.get_thetamax()) == pytest.approx((0.0, 180.0))
    spec, _buffers = fig._charts()[0].figure().build_payload_split()
    assert spec["x_axis"]["sector"] == pytest.approx([0.0, math.pi])

    # The degree-spelled setter likewise becomes the latest x-domain edit.
    ax.set_thetamin(45.0)
    assert ax.get_xlim() == pytest.approx((math.radians(45.0), math.pi))
    spec, _buffers = fig._charts()[0].figure().build_payload_split()
    assert spec["x_axis"]["sector"] == pytest.approx(ax.get_xlim())


@pytest.mark.parametrize("method", ["clear", "cla"])
def test_pyplot_clear_resets_polar_theta_and_radial_options(method: str) -> None:
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    ax.plot([0.0, math.pi], [1.0, 2.0])
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_thetamin(30.0)
    ax.set_thetamax(120.0)
    ax.set_rorigin(-1.0)

    getattr(ax, method)()
    ax.plot([0.0, math.pi], [1.0, 2.0])

    assert ax.get_xlim() == pytest.approx((0.0, 2.0 * math.pi))
    assert (ax.get_thetamin(), ax.get_thetamax()) == pytest.approx((0.0, 360.0))
    spec, _buffers = fig._charts()[0].figure().build_payload_split()
    assert spec["x_axis"]["sector"] == pytest.approx([0.0, 2.0 * math.pi])
    assert spec["x_axis"]["theta_zero"] == "E"
    assert spec["x_axis"]["theta_direction"] == "counterclockwise"
    assert "r_origin" not in spec["y_axis"]
