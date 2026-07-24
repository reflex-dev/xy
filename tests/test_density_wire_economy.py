"""Pyramid-served density replies never ship more grid than their source
resolves (§29 wire economy; LOD doc T13; #225 follow-up).

The field HAR behind this: a 100M-point drilldown at 200-450% zoom shipped a
~2.7 MB full-screen grid per pan/zoom step — count plane plus RGBA8 mean-color
plane at one cell per screen pixel — while the pyramid's finest level only
resolves a few hundred cells under such a window. Composing past the source
just upsamples blocky cells the client's own texture filtering reproduces
from the source-resolution grid at a fraction of the bytes. The reply also
records `min_cell`, the finest attainable per-axis cell size, so the client
can elide requests a cached texture already answers.
"""

from __future__ import annotations

import math

import numpy as np

from xy import interaction
from xy._figure import Figure
from xy.config import PYRAMID_BASE_DIM


def test_pyramid_source_shape_math() -> None:
    class _Col:
        def __init__(self, lo, hi):
            self.min, self.max = lo, hi

    class _T:
        _pyr_base_dim = 1024

        def __init__(self):
            self.x = _Col(0.0, 100.0)
            self.y = _Col(0.0, 50.0)

    t = _T()
    # A quarter-extent window resolves ~256 (+1 straddle) source cells.
    cells_x, cells_y = interaction._pyramid_source_shape(t, 10.0, 35.0, 5.0, 17.5)
    assert cells_x == math.ceil(1024 * 0.25) + 1
    assert cells_y == math.ceil(1024 * 0.25) + 1
    # Windows wider than the extent clamp to the full base.
    cells_x, _ = interaction._pyramid_source_shape(t, -50.0, 250.0, 0.0, 50.0)
    assert cells_x == 1024 + 1
    # Degenerate extents refuse rather than divide by zero.
    t.y = _Col(5.0, 5.0)
    assert interaction._pyramid_source_shape(t, 0.0, 1.0, 0.0, 1.0) is None


def test_pyramid_reply_grid_bounded_by_source_cells() -> None:
    n = 2_500_000
    rng = np.random.default_rng(3)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, density=True)
    t = fig.traces[0]

    # Half-extent window: comfortably pyramid territory (~625k in-window).
    upd, _ = fig.density_view(0, 25.0, 75.0, 25.0, 75.0, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "density"
    assert tr["binning"].startswith("pyramid")
    d = tr["density"]
    base = getattr(t, "_pyr_base_dim", 0) or PYRAMID_BASE_DIM
    # The grid never exceeds the source cells under the window (+1 straddle).
    assert d["w"] <= math.ceil(base * 0.5) + 1 + 1
    assert d["h"] <= math.ceil(base * 0.5) + 1 + 1
    # The reply carries the window's count — the fact the client's
    # points-band gate (lodAggregateStands, T13) scales for later zooms.
    assert tr["visible"] > 0

    # A window near the drill budget (~260k in-window: over the budget, under
    # the pyramid-serve margin) takes the exact path: true full-detail bins.
    upd2, _ = fig.density_view(0, 0.0, 35.0, 0.0, 30.0, 512, 384)
    tr2 = upd2["traces"][0]
    assert tr2["mode"] == "density"
    assert tr2["binning"] == "exact"


def test_pyramid_grid_clamped_to_source_resolution() -> None:
    # Large enough that the per-cell target no longer coarsens the grid below
    # the screen, so the source clamp is the binding constraint on x — the
    # regime the 100M field HAR exercised.
    n = 20_000_000
    rng = np.random.default_rng(7)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, density=True)
    t = fig.traces[0]

    frac = 0.6
    upd, bufs = fig.density_view(0, 20.0, 20.0 + 100.0 * frac, 20.0, 80.0, 2000, 348)
    tr = upd["traces"][0]
    assert tr["mode"] == "density"
    assert tr["binning"].startswith("pyramid")
    d = tr["density"]
    base = getattr(t, "_pyr_base_dim", 0) or PYRAMID_BASE_DIM
    source_x = math.ceil(base * frac) + 1
    # x is clamped to source cells; y stays screen/plan-bounded — the grid's
    # aspect visibly departs from the requested screen aspect.
    assert d["w"] <= source_x + 1
    assert d["h"] >= 200
    assert d["w"] / d["h"] < (2000 / 348) * 0.9
    # One byte per cell on the count plane (§29 log-u8 wire).
    assert len(bufs[d["buf"]]) == d["w"] * d["h"]
