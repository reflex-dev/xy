"""The (theta, r) -> pixel contract, bound to shared fixtures.

`tests/fixtures/polar_transform.json` is authored from
spec/design/polar-axes.md §3 rather than generated from any implementation, so
these assertions are a contract check and not a rubber stamp. The same file is
replayed against the real GLSL by `scripts/polar_parity_smoke.py`; that pairing
is the whole point — prose comments do not bind a shader to an exporter.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from xy._svg import THETA_ZERO, _PolarProjection

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "polar_transform.json").read_text(encoding="utf-8")
)
TOL = FIXTURES["tolerance_px"]
CASES = FIXTURES["cases"]


def _projection(case: dict) -> _PolarProjection:
    cfg = case["config"]
    return _PolarProjection(
        {
            "theta_unit": cfg["unit"],
            "theta_zero": cfg["zero"],
            "theta_direction": cfg["direction"],
        },
        {"range": cfg["r_range"]},
        case["plot"],
    )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_projection_matches_fixture(case: dict) -> None:
    """Every fixture point lands where spec §3 says it does."""
    project = _projection(case)
    for point in case["points"]:
        px, py = project(point["theta"], point["r"])
        assert float(px) == pytest.approx(point["px"], abs=TOL), (
            f"{case['name']}: theta={point['theta']} r={point['r']} x — {case['pins']}"
        )
        assert float(py) == pytest.approx(point["py"], abs=TOL), (
            f"{case['name']}: theta={point['theta']} r={point['r']} y — {case['pins']}"
        )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_projection_is_vectorized(case: dict) -> None:
    """Array input gives the same answer as scalar input, elementwise.

    Every mark helper projects whole columns at once, so a scalar-only
    implementation would pass the test above and still fail in production.
    """
    project = _projection(case)
    thetas = [p["theta"] for p in case["points"]]
    radii = [p["r"] for p in case["points"]]
    xs, ys = project(thetas, radii)
    for i, point in enumerate(case["points"]):
        assert float(xs[i]) == pytest.approx(point["px"], abs=TOL)
        assert float(ys[i]) == pytest.approx(point["py"], abs=TOL)


def test_y_axis_is_flipped_for_screen_space() -> None:
    """Upward angles must DECREASE py.

    The single most likely parity bug: screen space grows downward while GL
    clip space grows upward, so the two implementations of this transform
    legitimately differ by the sign of one term. A mirrored chart is otherwise
    entirely plausible-looking.
    """
    project = _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    _, up = project(math.pi / 2, 1.0)
    _, down = project(-math.pi / 2, 1.0)
    _, centre = project(0.0, 0.0)
    assert float(up) < float(centre) < float(down)


def test_circle_is_round_in_a_non_square_rect() -> None:
    """Radius comes from min(w, h) and the circle is centred, not stretched."""
    plot = {"x": 50.0, "y": 20.0, "w": 600.0, "h": 300.0}
    project = _PolarProjection({}, {"range": [0.0, 1.0]}, plot)
    centre = (plot["x"] + plot["w"] / 2, plot["y"] + plot["h"] / 2)
    for theta in (0.0, math.pi / 3, math.pi / 2, 2.0, math.pi, 4.5):
        px, py = project(theta, 1.0)
        assert math.hypot(float(px) - centre[0], float(py) - centre[1]) == pytest.approx(
            150.0, abs=1e-9
        )


def test_polar_projection_is_never_affine() -> None:
    """The affine fast paths bake a straight-line map into Rust.

    A polar chart on linear axes would otherwise satisfy `sx.affine and
    sy.affine` and get silently projected through that map.
    """
    assert (
        _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 10, "h": 10}).affine
        is False
    )


def test_compass_composition() -> None:
    """zero="N" + clockwise is the wind-rose convention: 90deg reads as East."""
    project = _PolarProjection(
        {"theta_unit": "degrees", "theta_zero": "N", "theta_direction": "clockwise"},
        {"range": [0.0, 1.0]},
        {"x": 0, "y": 0, "w": 400, "h": 400},
    )
    for degrees, want in ((0, (200, 0)), (90, (400, 200)), (180, (200, 400)), (270, (0, 200))):
        px, py = project(degrees, 1.0)
        assert (float(px), float(py)) == pytest.approx(want, abs=1e-9)


def test_theta_zero_table_covers_the_cardinals() -> None:
    assert set(THETA_ZERO) == {"E", "N", "W", "S"}
    assert THETA_ZERO["E"] == 0.0


def test_ring_is_closed_and_on_the_circle() -> None:
    """Grid rings flatten to polylines — the raster path has no arc opcode."""
    project = _PolarProjection({}, {"range": [0.0, 10.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    ring = project.ring(5.0, steps=64)
    assert len(ring) == 64
    # r=5 of range [0, 10] is half the 200 px radius.
    for px, py in ring:
        assert math.hypot(px - 200.0, py - 200.0) == pytest.approx(100.0, abs=1e-9)


def test_negative_radius_falls_inside_the_ring_it_came_from() -> None:
    """Below-range r normalizes negative, which mirrors across the origin.

    Documenting the raw behaviour: the transform itself does not clip, so the
    kernel must drop these rows before they reach a renderer (§7 / D7).
    """
    project = _PolarProjection({}, {"range": [0.0, 1.0]}, {"x": 0, "y": 0, "w": 400, "h": 400})
    px, _ = project(0.0, -1.0)
    assert float(px) < 200.0
