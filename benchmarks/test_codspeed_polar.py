"""CodSpeed attribution for the polar coordinate system.

The polar increment shipped a whole coordinate system — a new payload-build
validation pass, and the most expensive mark in the codebase — with no CodSpeed
row anywhere near it, so the report read "103 untouched benchmarks" for a change
that rewrote wedge geometry in three renderers. A performance cliff at ~50k
polar bars was found by hand, not by CI, precisely because nothing here could
see it.

These rows isolate the *Python* cost, which is what simulation mode measures:

- payload build for the three shapes with materially different validation and
  emit paths (a plain polar line, a stacked wind rose, an unequal-width pie);
- static SVG and native-PNG export of wedges, where `polar_wedge_points` /
  `_polar_wedge_path` flatten one arc per wedge. This is the row that tracks
  the span-proportional subdivision in `config.polar_bar_segments`: a
  16-sector rose flattens six segments per wedge rather than the full-turn
  worst case of 96, and a regression back to a flat count shows up here as
  roughly a 10x arc-flattening increase rather than as a bug report;
- static export of a polar heatmap, whose bounded inverse raster resolves
  screen pixels back through the transform and has no Cartesian twin.

Browser-side wedge vertex counts, GPU buffer lifetime, and radial-zoom frame
pacing are wall-clock/WebGL measurements and stay out of simulation mode —
`benchmarks/bench_interaction.py` and the polar smokes cover those.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import xy
from xy import kernels as k

#: Angular samples for the line row: enough to make the projection and the
#: per-vertex cull the dominant term rather than figure setup.
LINE_N = 100_000

#: Sector count for the rose. Sixteen compass points is the dense end of what
#: real wind roses use, and it is the case the subdivision formula was sized
#: against (22.5 degrees per wedge).
ROSE_SECTORS = 16
ROSE_OBSERVATIONS = 50_000

#: Pie slices. Unequal widths ship four edge columns rather than one scalar
#: width, which is a different emit path and a different flattening call.
PIE_SLICES = 24

#: Polar heatmap grid. Cell count, not point count, drives the inverse raster.
HEATMAP_THETA = 96
HEATMAP_R = 48

N_BUCKETS = 2048


@pytest.fixture(scope="session", autouse=True)
def require_native_backend() -> None:
    assert k.BACKEND == "native", (
        "CodSpeed benchmarks must run against the native Rust backend; "
        f"got {k.BACKEND!r}. Build the native core before running them."
    )


@pytest.fixture(scope="session", autouse=True)
def warm_lazy_modules() -> None:
    """Warm the polar build and export stacks before any measured region.

    Same phantom-regression guard the other modules carry: without it the first
    row pays lazy submodule import for the payload and export stacks and tracks
    package source size instead of its own workload. Warmed through the polar
    paths specifically, so `_validate_coords`, the wedge emitters and the
    projection are all resident.
    """
    theta = np.array([0.0, 90.0, 180.0, 270.0])
    radius = np.array([1.0, 2.0, 3.0, 2.0])
    figure = xy.polar_chart(
        xy.line(theta, radius),
        xy.theta_axis(unit="degrees"),
        width=240,
        height=240,
    ).figure()
    figure.build_payload_split(N_BUCKETS)
    figure.to_svg(width=240, height=240)
    xy.polar_bar_chart(
        xy.bar(theta, radius, width=22.5),
        xy.theta_axis(unit="degrees"),
        width=240,
        height=240,
    ).figure().to_png(engine=xy.Engine.default, scale=1.0)


@pytest.fixture(scope="module")
def polar_data() -> dict[str, object]:
    rng = np.random.default_rng(19)
    theta = np.linspace(0.0, 360.0, LINE_N, dtype=np.float64)
    # A five-lobe rose: the radius varies over the whole turn, so no vertex run
    # is culled wholesale and the projection runs on every point.
    radius = (1.0 + 0.5 * np.sin(np.radians(5.0 * theta))).astype(np.float64, copy=False)
    return {
        "theta": theta,
        "radius": radius,
        "directions": rng.uniform(0.0, 360.0, ROSE_OBSERVATIONS),
        "speeds": rng.gamma(2.0, 3.0, ROSE_OBSERVATIONS),
        "pie_labels": [f"S{index:02d}" for index in range(PIE_SLICES)],
        "pie_values": (10.0 + 6.0 * np.cos(np.linspace(0.0, 9.0, PIE_SLICES))).astype(
            np.float64, copy=False
        ),
        "grid_theta": np.linspace(0.0, 2.0 * math.pi, HEATMAP_THETA, dtype=np.float64),
        "grid_r": np.linspace(0.5, 4.0, HEATMAP_R, dtype=np.float64),
    }


def _polar_line_payload(theta: np.ndarray, radius: np.ndarray) -> int:
    figure = xy.polar_chart(
        xy.line(theta, radius),
        xy.theta_axis(unit="degrees"),
    ).figure()
    _spec, buffers = figure.build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _wind_rose_payload(directions: np.ndarray, speeds: np.ndarray) -> int:
    figure = xy.wind_rose(directions, speeds, sectors=ROSE_SECTORS).figure()
    _spec, buffers = figure.build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _pie_payload(labels: list[str], values: np.ndarray) -> int:
    figure = xy.pie_chart(labels, values).figure()
    _spec, buffers = figure.build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def test_first_payload_polar_line(benchmark, polar_data):
    """Polar payload prep: coordinate validation plus the angular axis contract.

    A polar figure carries the same raw f32 geometry a cartesian one does — the
    projection happens in the renderer — so the payload must stay bounded by the
    f32 encoding of two columns, never grow a pre-projected third.
    """
    theta = polar_data["theta"]
    radius = polar_data["radius"]
    assert isinstance(theta, np.ndarray)
    assert isinstance(radius, np.ndarray)
    payload_bytes = benchmark(_polar_line_payload, theta, radius)
    assert 0 < payload_bytes <= (theta.nbytes + radius.nbytes) // 2


def test_first_payload_wind_rose(benchmark, polar_data):
    """Wind rose payload prep: Python-side binning plus stacked wedge columns.

    Binning happens in Python, exactly as `hist` does it, so the shipped bytes
    must be bounded by sector count and band count — never by observation count.
    That bound is the whole reason a rose over 50k observations is cheap.
    """
    directions = polar_data["directions"]
    speeds = polar_data["speeds"]
    assert isinstance(directions, np.ndarray)
    payload_bytes = benchmark(_wind_rose_payload, directions, speeds)
    assert 0 < payload_bytes < directions.nbytes // 8


def test_first_payload_pie(benchmark, polar_data):
    """Pie payload prep: one wedge bar per slice, each with its own width.

    Unequal widths take the four-edge column path rather than the compact
    scalar-width one, so this row tracks per-slice emit cost — the thing that
    grows when a composition gains a slice, not when it gains a data point.
    """
    labels = polar_data["pie_labels"]
    values = polar_data["pie_values"]
    assert isinstance(labels, list)
    payload_bytes = benchmark(_pie_payload, labels, values)
    assert payload_bytes > 0


def test_svg_export_polar_wedges(benchmark, polar_data):
    """Static SVG export of a dense rose: one real `A` arc pair per wedge.

    SVG needs no flattening count, so this row is the arc-emission and chrome
    cost with the subdivision term removed — the control for the PNG row below.
    """
    directions = polar_data["directions"]
    speeds = polar_data["speeds"]
    figure = xy.wind_rose(directions, speeds, sectors=ROSE_SECTORS).figure()
    document = benchmark(figure.to_svg, width=720, height=720)
    assert document.startswith("<svg")
    # The wedges really are arcs, not chord-edged polygons: an `A` command per
    # wedge boundary is what makes this row the no-flattening control.
    assert " A " in document


def test_native_png_export_polar_wedges(benchmark, polar_data):
    """Native PNG export of a dense rose: the flattening path.

    The raster display list has no arc opcode, so every wedge ships as a polygon
    from `polar_wedge_points`. The vertex count per wedge is
    `config.polar_bar_segments(span, turn)` — six segments for a 22.5-degree
    sector, not the full-turn 96 — so a regression back to a flat count lands
    here as an arc-flattening step change.
    """
    directions = polar_data["directions"]
    speeds = polar_data["speeds"]
    figure = xy.wind_rose(directions, speeds, sectors=ROSE_SECTORS).figure()
    png = benchmark(figure.to_png, engine=xy.Engine.default, scale=1.0)
    assert png.startswith(b"\x89PNG")


def test_native_png_export_polar_heatmap(benchmark, polar_data):
    """Static polar heatmap: the bounded screen-space inverse raster.

    Work is bounded by the requested output surface rather than the source grid
    (the inverse resolves visible output pixels, then gathers source cells), so
    this row is the one that would show that bound being lost.
    """
    grid_theta = polar_data["grid_theta"]
    grid_r = polar_data["grid_r"]
    assert isinstance(grid_theta, np.ndarray)
    assert isinstance(grid_r, np.ndarray)
    values = (np.sin(grid_theta[None, :]) + np.asarray(grid_r)[:, None]).astype(
        np.float64, copy=False
    )
    figure = xy.polar_chart(xy.heatmap(values, x=grid_theta, y=grid_r)).figure()
    png = benchmark(figure.to_png, engine=xy.Engine.default, scale=1.0)
    assert png.startswith(b"\x89PNG")
