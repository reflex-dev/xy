"""Pins for the composition API's validation timing (facts X1-X3).

The Reflex component API (spec/design/reflex-component-api-options.md §4,
implementation plan in reflex-component-api-implementation.md) compiles
chart *plans* by binding zero-row placeholder columns and calling
``.figure()`` once at page evaluation. That only works while:

- X1: the tree is cheap to build without data; chrome nodes validate
  eagerly; mark config validates at ``.figure()``.
- X2: zero-row columns compile — the probe exercises the full validation
  gate with no real data.
- X3: ``Chart.figure()`` memoizes and is never invalidated — rebinding data
  means a fresh ``Chart``, never mutating one.

A grammar change that moves any of these fails here first, named after the
fact it broke.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy

EMPTY = np.empty(0, dtype=np.float64)

# Every mark kind the flat/composed Reflex factories cover with the zero-row
# probe (Phase 2 kinds first, then the Phase 3 signature-derived set). Kinds
# whose validators require at least one finite value (stairs, ecdf, box,
# violin, hexbin, heatmap, contour) are excluded from the plan/zero-row model
# by the Phase 3 decision recorded in the implementation plan.
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
}


@pytest.mark.parametrize("kind", sorted(ZERO_ROW_CHARTS))
def test_zero_row_construction_compiles(kind):
    """X2: binding empty columns and calling .figure() runs the full mark
    validation gate without any real data."""
    figure = ZERO_ROW_CHARTS[kind]().figure()
    assert figure is not None


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
