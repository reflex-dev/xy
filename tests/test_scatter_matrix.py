"""Exhaustive scatter combination matrix — production-readiness sweep.

Every combination a user is likely to hit: color/size modes and input dtypes,
NaN/inf/empty/degenerate data, tier boundaries, multi-trace, and the pick/select
interactions across tiers. Runs under both backends (native + NumPy fallback)
via the FASTCHARTS_FORCE_FALLBACK matrix in CI.
"""

from __future__ import annotations

import numpy as np
import pytest

import fastcharts as fc
from fastcharts import Figure
from fastcharts.figure import DIRECT_SOFT_CEILING, SCATTER_DENSITY_THRESHOLD


def _payload(fig):
    spec, blob = fig.build_payload()
    return spec, blob


def _col(spec, blob, ref, dtype=np.float32):
    m = spec["columns"][ref]
    return np.frombuffer(blob, dtype=dtype, count=m["len"], offset=m["byte_offset"])


# --------------------------------------------------------------------------
# Input dtypes for x/y
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mk",
    [
        lambda: ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),  # python lists
        lambda: (np.arange(3), np.arange(3)),  # int arrays
        lambda: (np.arange(3.0), np.arange(3.0)),  # float arrays
        lambda: (np.arange(3, dtype=np.float32), np.arange(3.0)),  # f32 x
        lambda: (list(range(3)), np.arange(3.0)),  # mixed list/array
        lambda: (np.array([1, 2, 3], dtype=np.int8), np.arange(3.0)),  # small int
    ],
)
def test_xy_input_dtypes(mk):
    x, y = mk()
    spec, blob = _payload(Figure().scatter(x, y))
    assert spec["traces"][0]["n_points"] == 3
    assert _col(spec, blob, spec["traces"][0]["x"]).shape == (3,)


def test_datetime_x_becomes_time_axis():
    t = np.arange("2024-01-01", "2024-01-04", dtype="datetime64[D]")
    fig = Figure().scatter(t, np.arange(3.0))
    spec, _ = _payload(fig)
    assert spec["x_axis"]["kind"] == "time"
    assert fig.traces[0].x.kind == "time_ms"


class Series:
    """pandas-Series-like: exposes .to_numpy() (no pandas dependency in tests)."""

    def __init__(self, a):
        self._a = np.asarray(a)

    def to_numpy(self):
        return self._a


def test_series_like_input():
    fig = Figure().scatter(Series([1.0, 2.0]), Series([3.0, 4.0]))
    assert fig.traces[0].n_points == 2


# --------------------------------------------------------------------------
# Color modes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("color", ["#ff0000", "red", "rgb(10,20,30)", "#abc"])
def test_color_constant_forms(color):
    spec, _ = _payload(Figure().scatter(np.arange(5.0), np.arange(5.0), color=color))
    assert spec["traces"][0]["color"] == {"mode": "constant", "color": color}


@pytest.mark.parametrize("cm", ["viridis", "magma", "plasma", "cividis", "turbo"])
def test_all_colormaps(cm):
    vals = np.linspace(0, 1, 20)
    spec, _ = _payload(Figure().scatter(np.arange(20.0), np.arange(20.0), color=vals, colormap=cm))
    assert spec["traces"][0]["color"]["colormap"] == cm


def test_continuous_int_and_float_color():
    for vals in (np.arange(10), np.linspace(-5, 5, 10)):
        spec, blob = _payload(Figure().scatter(np.arange(10.0), np.arange(10.0), color=vals))
        buf = _col(spec, blob, spec["traces"][0]["color"]["buf"])
        assert buf.min() >= 0.0 and buf.max() <= 1.0


def test_categorical_many_categories_cycle_palette():
    # More categories than the base palette (10) → palette entries cycle, no crash.
    cats = np.array([f"c{i}" for i in range(25)] * 2)
    fig = Figure().scatter(np.arange(50.0), np.arange(50.0), color=cats)
    spec, _ = _payload(fig)
    assert len(spec["traces"][0]["color"]["categories"]) == 25
    assert len(spec["traces"][0]["color"]["palette"]) == 25


def test_categorical_single_category():
    cats = np.array(["only"] * 8)
    spec, blob = _payload(Figure().scatter(np.arange(8.0), np.arange(8.0), color=cats))
    codes = _col(spec, blob, spec["traces"][0]["color"]["buf"])
    assert set(codes.astype(int)) == {0}


def test_too_many_categories_warns():
    cats = np.array([f"c{i}" for i in range(300)])
    with pytest.warns(RuntimeWarning, match="categories"):
        Figure().scatter(np.arange(300.0), np.arange(300.0), color=cats)


def test_categorical_bool_array():
    flags = np.array([True, False, True, True, False])
    fig = Figure().scatter(np.arange(5.0), np.arange(5.0), color=flags)
    assert fig.traces[0].color_ch.mode == "categorical"
    assert fig.traces[0].color_ch.categories == ["False", "True"]


# --------------------------------------------------------------------------
# Size modes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [1.0, 4, 20.0])
def test_size_constant(size):
    spec, _ = _payload(Figure().scatter(np.arange(3.0), np.arange(3.0), size=size))
    assert spec["traces"][0]["size"] == {"mode": "constant", "size": float(size)}


def test_size_continuous_and_range():
    sz = np.array([1.0, 5.0, 10.0, 2.0])
    spec, blob = _payload(
        Figure().scatter(np.arange(4.0), np.arange(4.0), size=sz, size_range=(1.0, 30.0))
    )
    assert spec["traces"][0]["size"]["range_px"] == [1.0, 30.0]
    buf = _col(spec, blob, spec["traces"][0]["size"]["buf"])
    assert buf.min() == 0.0 and buf.max() == pytest.approx(1.0)


def test_color_and_size_both_per_point():
    n = 30
    fig = Figure().scatter(
        np.arange(n * 1.0),
        np.arange(n * 1.0),
        color=np.arange(n),
        size=np.abs(np.sin(np.arange(n))),
    )
    spec, blob = _payload(fig)
    t = spec["traces"][0]
    assert "buf" in t["color"] and "buf" in t["size"]
    # x, y, color, size all shipped, all length n
    for ref in (t["x"], t["y"], t["color"]["buf"], t["size"]["buf"]):
        assert spec["columns"][ref]["len"] == n


# --------------------------------------------------------------------------
# Degenerate / edge data
# --------------------------------------------------------------------------


def test_empty_scatter():
    fig = Figure().scatter(np.array([]), np.array([]))
    spec, blob = _payload(fig)
    assert spec["traces"][0]["n_points"] == 0
    assert fig.x_range()[0] < fig.x_range()[1]  # sane fallback range


def test_single_point():
    fig = Figure().scatter(np.array([5.0]), np.array([7.0]))
    spec, _ = _payload(fig)
    x0, x1 = spec["x_axis"]["range"]
    assert x0 < 5.0 < x1  # degenerate range gets padded


def test_all_same_x():
    fig = Figure().scatter(np.full(10, 3.0), np.arange(10.0))
    x0, x1 = fig.x_range()
    assert x0 < 3.0 < x1


def test_all_same_color_value_degenerate_domain():
    # Continuous color where every value is identical → no divide-by-zero.
    spec, blob = _payload(
        Figure().scatter(np.arange(10.0), np.arange(10.0), color=np.full(10, 42.0))
    )
    buf = _col(spec, blob, spec["traces"][0]["color"]["buf"])
    assert np.all(np.isfinite(buf))


def test_all_same_size_value():
    spec, blob = _payload(Figure().scatter(np.arange(5.0), np.arange(5.0), size=np.full(5, 9.0)))
    buf = _col(spec, blob, spec["traces"][0]["size"]["buf"])
    assert np.all(np.isfinite(buf))


# --------------------------------------------------------------------------
# Non-finite handling (§19) — the production hardening
# --------------------------------------------------------------------------


def test_nan_in_xy_dropped_from_wire():
    x = np.array([0.0, 1.0, np.nan, 3.0])
    y = np.array([0.0, np.nan, 2.0, 3.0])
    spec, blob = _payload(Figure().scatter(x, y))
    xbuf = _col(spec, blob, spec["traces"][0]["x"])
    assert len(xbuf) == 2 and np.all(np.isfinite(xbuf))


def test_inf_in_xy_dropped_and_range_finite():
    x = np.array([0.0, np.inf, 2.0, -np.inf, 4.0])
    y = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    fig = Figure().scatter(x, y)
    # autorange must ignore inf, not collapse to the (0,1) fallback
    x0, x1 = fig.x_range()
    assert np.isfinite(x0) and np.isfinite(x1)
    assert x0 <= 0.0 and x1 >= 4.0
    spec, blob = _payload(fig)
    xbuf = _col(spec, blob, spec["traces"][0]["x"])
    assert np.all(np.isfinite(xbuf)) and len(xbuf) == 3


def test_inf_in_color_channel_stays_unit():
    x = np.arange(6.0)
    color = np.array([0.0, 1.0, np.inf, 2.0, -np.inf, 3.0])
    # x/y finite so all 6 ship; color inf must normalize into [0,1]
    spec, blob = _payload(Figure().scatter(x, x, color=color))
    buf = _col(spec, blob, spec["traces"][0]["color"]["buf"])
    assert np.all((buf >= 0.0) & (buf <= 1.0))


def test_all_nan_column():
    fig = Figure().scatter(np.full(5, np.nan), np.arange(5.0))
    spec, blob = _payload(fig)
    xbuf = _col(spec, blob, spec["traces"][0]["x"])
    assert len(xbuf) == 0  # nothing plottable


# --------------------------------------------------------------------------
# Length mismatch validation
# --------------------------------------------------------------------------


def test_xy_length_mismatch_raises():
    with pytest.raises(ValueError, match="equal length"):
        Figure().scatter(np.arange(5.0), np.arange(3.0))
    with pytest.raises(ValueError, match="equal length"):
        Figure().line(np.arange(5.0), np.arange(3.0))


def test_color_length_mismatch_raises():
    with pytest.raises(ValueError, match="length 5"):
        Figure().scatter(np.arange(5.0), np.arange(5.0), color=np.arange(3.0))


def test_size_length_mismatch_raises():
    with pytest.raises(ValueError, match="length 5"):
        Figure().scatter(np.arange(5.0), np.arange(5.0), size=np.arange(3.0))


# --------------------------------------------------------------------------
# Tier boundaries
# --------------------------------------------------------------------------


def test_tier_just_below_and_above_threshold():
    lo = Figure().scatter(
        np.arange(SCATTER_DENSITY_THRESHOLD * 1.0), np.arange(SCATTER_DENSITY_THRESHOLD * 1.0)
    )
    assert not lo.traces[0].use_density()
    hi = Figure().scatter(
        np.arange((SCATTER_DENSITY_THRESHOLD + 1) * 1.0),
        np.arange((SCATTER_DENSITY_THRESHOLD + 1) * 1.0),
    )
    assert hi.traces[0].use_density()


def test_force_density_on_small():
    fig = Figure().scatter(np.arange(100.0), np.arange(100.0), density=True)
    spec, blob = _payload(fig)
    assert spec["traces"][0]["tier"] == "density"
    grid = _col(spec, blob, spec["traces"][0]["density"]["buf"])
    assert grid.sum() > 0


def test_force_direct_on_large_warns_but_works():
    n = DIRECT_SOFT_CEILING + 1
    with pytest.warns(RuntimeWarning):
        fig = Figure().scatter(np.zeros(n), np.zeros(n), density=False)
    spec, _ = _payload(fig)
    assert spec["traces"][0]["tier"] == "direct"


# --------------------------------------------------------------------------
# Multi-trace and mixed
# --------------------------------------------------------------------------


def test_multi_scatter_distinct_default_colors():
    fig = Figure()
    fig.scatter(np.arange(3.0), np.arange(3.0))
    fig.scatter(np.arange(3.0), np.arange(3.0) + 1)
    spec, _ = _payload(fig)
    c0 = spec["traces"][0]["color"]["color"]
    c1 = spec["traces"][1]["color"]["color"]
    assert c0 != c1  # palette cycles per trace


def test_scatter_and_line_mixed():
    fig = Figure()
    fig.line(np.arange(100.0), np.sin(np.arange(100.0)), name="wave")
    fig.scatter(np.arange(50.0), np.cos(np.arange(50.0)), name="pts")
    spec, _ = _payload(fig)
    kinds = {t["kind"] for t in spec["traces"]}
    assert kinds == {"line", "scatter"}


# --------------------------------------------------------------------------
# Interactions across tiers
# --------------------------------------------------------------------------


def test_pick_direct_and_translated():
    x = np.array([0.0, np.nan, 2.0, 3.0])
    y = np.array([9.0, 9.0, 8.0, 7.0])
    fig = Figure().scatter(x, y)
    fig.build_payload()
    row = fig.pick(0, 1)  # shipped 1 == canonical 2 (row 1 dropped for NaN x)
    assert row["x"] == 2.0 and row["y"] == 8.0


def test_select_and_translate_roundtrip():
    x = np.arange(100.0)
    fig = Figure().scatter(x, x)
    fig.build_payload()
    sel = fig.select_range(10.0, 20.0, 0.0, 1000.0)
    assert len(sel[0]) == 11
    shipped = fig.to_shipped_indices(0, sel[0])
    np.testing.assert_array_equal(shipped, sel[0])  # no drops → identity


def test_density_view_rebin_matches_range():
    # Keep this viewport over the adaptive drill budget; smaller windows now
    # return exact points instead of a density grid.
    n = 550_000
    rng = np.random.default_rng(3)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y)
    update, buffers = fig.density_view(0, 10.0, 90.0, 20.0, 80.0, 32, 32)
    assert update["traces"][0]["mode"] == "density"
    grid = np.frombuffer(buffers[0], dtype=np.float32)
    expect = np.sum((x >= 10) & (x < 90) & (y >= 20) & (y < 80))
    assert expect > SCATTER_DENSITY_THRESHOLD
    assert grid.sum() == pytest.approx(expect)


# --------------------------------------------------------------------------
# Component API parity + export
# --------------------------------------------------------------------------


def test_component_api_matrix():
    df = {"x": np.arange(20.0), "y": np.arange(20.0), "g": np.array(["a", "b"] * 10)}
    chart = fc.scatter_chart(
        fc.scatter(x="x", y="y", color="g", size=6.0, data=df),
        fc.x_axis(label="X"),
        fc.y_axis(label="Y"),
        fc.legend(),
        title="matrix",
    )
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["color"]["mode"] == "categorical"
    assert spec["x_axis"]["label"] == "X"


def test_to_html_roundtrips_for_every_tier():
    for fig in (
        Figure().scatter(np.arange(50.0), np.arange(50.0)),  # direct
        Figure().scatter(np.arange(50.0), np.arange(50.0), color=np.arange(50)),  # channels
        Figure().scatter(np.arange(50.0), np.arange(50.0), density=True),  # density
        Figure().line(np.arange(20000.0), np.sin(np.arange(20000.0))),  # decimated
    ):
        html = fig.to_html()
        assert "fastcharts.renderStandalone" in html
        assert '<div id="chart">' in html
        assert len(html) > 1000
