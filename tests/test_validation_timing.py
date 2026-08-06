"""Pins for the composition API's validation timing (facts X1-X3).

The Reflex component API (spec/design/reflex-component-api-options.md §4,
implementation plan in reflex-component-api-implementation.md) compiles
chart *plans* by binding zero-row placeholder columns and calling
``.figure()`` once at page evaluation, under the core's
``xy.components.structural_probe()`` mode. That only works while:

- X1: the tree is cheap to build without data; chrome nodes validate
  eagerly; mark config validates at ``.figure()``.
- X2: zero-row columns compile for **every** mark kind — directly for the
  non-aggregating kinds, and under ``structural_probe()`` for the
  aggregating kinds, whose marks then validate configuration and skip
  aggregation instead of refusing empty input. No synthetic data exists
  anywhere in the probe: a probe failure indicts structure, never
  invented values.
- X3: ``Chart.figure()`` memoizes and is never invalidated — rebinding data
  means a fresh ``Chart``, never mutating one.

A grammar change that moves any of these fails here first, named after the
fact it broke.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy.components import structural_probe

EMPTY = np.empty(0, dtype=np.float64)

# Every mark kind the flat/composed Reflex factories cover with the plain
# zero-row build (no probe mode needed: their validators accept empty).
ZERO_ROW_CHARTS = {
    "scatter": lambda: xy.scatter_chart(xy.scatter(EMPTY, EMPTY)),
    "line": lambda: xy.line_chart(xy.line(EMPTY, EMPTY)),
    "histogram": lambda: xy.histogram_chart(xy.histogram(EMPTY)),
    "bar": lambda: xy.bar_chart(xy.bar(EMPTY, EMPTY)),
    "area": lambda: xy.area_chart(xy.area(EMPTY, EMPTY)),
    "step": lambda: xy.step_chart(xy.step(EMPTY, EMPTY)),
    "stem": lambda: xy.stem_chart(xy.stem(EMPTY, EMPTY)),
    "column": lambda: xy.column_chart(xy.column(EMPTY, EMPTY)),
    "errorbar": lambda: xy.errorbar_chart(xy.errorbar(EMPTY, EMPTY, yerr=EMPTY)),
    "error_band": lambda: xy.error_band_chart(xy.error_band(EMPTY, EMPTY, upper=EMPTY)),
    "segments": lambda: xy.segments_chart(xy.segments(EMPTY, EMPTY, x1=EMPTY, y1=EMPTY)),
    "triangle_mesh": lambda: xy.triangle_mesh_chart(
        xy.triangle_mesh(EMPTY, EMPTY, x1=EMPTY, y1=EMPTY, x2=EMPTY, y2=EMPTY)
    ),
}

# The aggregating kinds refuse zero rows in a normal build (their validators
# need at least one finite value) but compile zero-row under the structural
# probe: config validates, aggregation is skipped, no trace is contributed.
AGGREGATING_CHARTS = {
    "box": lambda: xy.box_chart(xy.box(EMPTY, group=EMPTY)),
    "violin": lambda: xy.violin_chart(xy.violin(EMPTY)),
    "hexbin": lambda: xy.hexbin_chart(xy.hexbin(EMPTY, EMPTY)),
    "contour": lambda: xy.contour_chart(xy.contour(EMPTY, x=EMPTY, y=EMPTY)),
    "heatmap": lambda: xy.heatmap_chart(xy.heatmap(EMPTY, x=EMPTY, y=EMPTY)),
    "stairs": lambda: xy.stairs_chart(xy.stairs(EMPTY, EMPTY)),
    "ecdf": lambda: xy.ecdf_chart(xy.ecdf(EMPTY)),
    "histogram_density": lambda: xy.histogram_chart(xy.histogram(EMPTY, density=True)),
}

# Config errors the structural probe must still raise with empty channels:
# no data does not mean no validation. One representative per kind.
AGGREGATING_CONFIG_ERRORS = {
    "box": (lambda: xy.box_chart(xy.box(EMPTY, orientation="diagonal")), "orientation"),
    "violin": (lambda: xy.violin_chart(xy.violin(EMPTY, bins=2)), "bins"),
    "hexbin": (lambda: xy.hexbin_chart(xy.hexbin(EMPTY, EMPTY, gridsize=0)), "gridsize"),
    "hexbin_range": (
        lambda: xy.hexbin_chart(xy.hexbin(EMPTY, EMPTY, range=(0.0, 1.0))),
        "range",
    ),
    "hexbin_mincnt": (lambda: xy.hexbin_chart(xy.hexbin(EMPTY, EMPTY, mincnt=-1)), "mincnt"),
    "contour": (lambda: xy.contour_chart(xy.contour(EMPTY, levels=0)), "levels"),
    "heatmap": (lambda: xy.heatmap_chart(xy.heatmap(EMPTY, colormap="virids")), "colormap"),
    "stairs": (lambda: xy.stairs_chart(xy.stairs(EMPTY, where="diagonal")), "where"),
    "ecdf": (lambda: xy.ecdf_chart(xy.ecdf(EMPTY, bins=-1)), "bins"),
    "histogram": (lambda: xy.histogram_chart(xy.histogram(EMPTY, bins=-1)), "bins"),
}


@pytest.mark.parametrize("kind", sorted(ZERO_ROW_CHARTS))
def test_zero_row_construction_compiles(kind):
    """X2: binding empty columns and calling .figure() runs the full mark
    validation gate without any real data."""
    figure = ZERO_ROW_CHARTS[kind]().figure()
    assert figure is not None


@pytest.mark.parametrize("kind", sorted(AGGREGATING_CHARTS))
def test_aggregating_kinds_compile_zero_row_under_structural_probe(kind):
    """X2 for the aggregating kinds: under structural_probe() an all-empty
    mark validates config and contributes no trace instead of refusing."""
    with structural_probe():
        figure = AGGREGATING_CHARTS[kind]().figure()
    assert figure is not None
    assert figure.traces == []


@pytest.mark.parametrize("kind", sorted(AGGREGATING_CHARTS))
def test_aggregating_kinds_still_refuse_zero_rows_normally(kind):
    """Probe mode never leaks: outside structural_probe() the aggregating
    validators keep their at-least-one-value contract."""
    with pytest.raises(ValueError):
        AGGREGATING_CHARTS[kind]().figure()


@pytest.mark.parametrize("case", sorted(AGGREGATING_CONFIG_ERRORS))
def test_structural_probe_still_raises_config_errors(case):
    """No synthetic data does not mean no validation: configuration errors
    surface in probe mode exactly as they do with real data."""
    build, match = AGGREGATING_CONFIG_ERRORS[case]
    with structural_probe(), pytest.raises((ValueError, TypeError), match=match):
        build().figure()


def test_structural_probe_does_not_change_real_data_builds():
    """Probe mode is a zero-row affordance only: non-empty channels build
    identical figures in and out of it."""
    values = np.linspace(1.0, 8.0, 8)
    with structural_probe():
        probed = xy.ecdf_chart(xy.ecdf(values)).figure()
    normal = xy.ecdf_chart(xy.ecdf(values)).figure()
    assert len(probed.traces) == len(normal.traces) == 1
    assert probed.traces[0].n_points == normal.traces[0].n_points


def test_zero_row_columns_resolve_through_chart_data():
    """X2, the form the plan tier uses: string channels resolved against a
    chart-level table of zero-row columns."""
    data = {"x": EMPTY, "y": EMPTY, "mag": EMPTY}
    figure = xy.scatter_chart(xy.scatter("x", "y", color="mag"), data=data).figure()
    assert figure is not None


def test_mark_config_validates_at_figure_not_construction():
    """X1: mark factories are lazy about config — a bad colormap constructs
    fine and fails only at .figure()."""
    mark = xy.scatter([1.0], [1.0], colormap="bogus")  # constructs
    with pytest.raises(ValueError, match="colormap"):
        xy.scatter_chart(mark).figure()


def test_unknown_mark_kwarg_fails_at_construction():
    """X1: no ``**kwargs`` sinks anywhere — a typo'd mark option is an
    immediate TypeError, before any figure exists."""
    with pytest.raises(TypeError):
        xy.scatter([1.0], [1.0], colormapp="viridis")


def test_chrome_nodes_validate_eagerly():
    """X1: chrome constructors validate every field at call time."""
    with pytest.raises(ValueError, match="type_"):
        xy.x_axis(type_="bogus")


def test_figure_memoizes_and_rebinding_needs_a_fresh_chart():
    """X3: .figure() is built once and cached; swapping the data table on an
    existing Chart does not rebuild — a fresh Chart does."""
    mark = xy.scatter("x", "y")
    chart = xy.scatter_chart(mark, data={"x": [1.0], "y": [2.0]})
    figure = chart.figure()
    assert chart.figure() is figure

    chart.data = {"x": [1.0, 3.0], "y": [2.0, 4.0]}
    assert chart.figure() is figure  # memoized: rebind must not rely on mutation
    assert chart.figure().traces[0].n_points == 1

    rebound = xy.scatter_chart(mark, data={"x": [1.0, 3.0], "y": [2.0, 4.0]})
    assert rebound.figure() is not figure
    assert rebound.figure().traces[0].n_points == 2
