"""Full scatter: color/size channels (§36c), Tier-2 density aggregation (§5),
hover pick with exact f64 readout (§16/§17)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from fastcharts import Figure
from fastcharts import channels as ch
from fastcharts.config import MAX_SCREEN_DIM
from fastcharts.figure import DENSITY_GRID, SCATTER_DENSITY_THRESHOLD
from fastcharts.interaction import _decode_log_u8


def _col(spec, blob, ref, dtype=np.float32):
    m = spec["columns"][ref]
    return np.frombuffer(blob, dtype=dtype, count=m["len"], offset=m["byte_offset"])


# -- channel resolution ------------------------------------------------------


def test_color_constant():
    c = ch.resolve_color("#ff0000", 10, default_constant="#000")
    assert c.mode == "constant" and c.constant == "#ff0000"
    c2 = ch.resolve_color(None, 10, default_constant="#123456")
    assert c2.mode == "constant" and c2.constant == "#123456"


def test_color_continuous():
    vals = np.linspace(0, 100, 50)
    c = ch.resolve_color(vals, 50, colormap="magma", default_constant="#000")
    assert c.mode == "continuous"
    assert c.domain == (0.0, 100.0)
    assert c.colormap == "magma"


def test_color_categorical():
    cats = np.array(["b", "a", "b", "c", "a"])
    c = ch.resolve_color(cats, 5, default_constant="#000")
    assert c.mode == "categorical"
    assert c.categories == ["a", "b", "c"]  # sorted unique
    # codes index the sorted categories
    np.testing.assert_array_equal(c.codes, [1, 0, 1, 2, 0])


def test_color_categorical_handles_missing_and_mixed_objects():
    cats = np.array(["b", None, "a", np.nan, 1], dtype=object)
    c = ch.resolve_color(cats, 5, default_constant="#000")
    assert c.mode == "categorical"
    assert c.categories == ["(missing)", "1", "a", "b"]
    np.testing.assert_array_equal(c.codes, [3, 0, 2, 0, 1])


def test_numeric_object_color_with_missing_is_continuous():
    vals = np.array([1, None, 2.5, np.nan], dtype=object)
    c = ch.resolve_color(vals, 4, default_constant="#000")
    assert c.mode == "continuous"
    assert c.domain == (1.0, 2.5)
    np.testing.assert_allclose(c.values, [1.0, np.nan, 2.5, np.nan])


def test_numeric_string_object_color_stays_categorical():
    vals = np.array(["1", "2", None], dtype=object)
    c = ch.resolve_color(vals, 3, default_constant="#000")
    assert c.mode == "categorical"
    assert c.categories == ["(missing)", "1", "2"]


def test_color_bad_length():
    with pytest.raises(ValueError, match="length 10"):
        ch.resolve_color(np.arange(5.0), 10, default_constant="#000")


def test_color_unknown_colormap():
    with pytest.raises(ValueError, match="colormap"):
        ch.resolve_color(np.arange(10.0), 10, colormap="nope", default_constant="#000")


def test_size_modes():
    assert ch.resolve_size(6.0, 10).mode == "constant"
    assert ch.resolve_size(6.0, 10).constant == 6.0
    s = ch.resolve_size(np.arange(10.0), 10, range_px=(1.0, 9.0))
    assert s.mode == "continuous"
    assert s.range_px == (1.0, 9.0)
    assert s.domain == (0.0, 9.0)


def test_object_numeric_size_with_missing_is_continuous():
    vals = np.array([1, None, 3.0], dtype=object)
    s = ch.resolve_size(vals, 3, range_px=(2.0, 12.0))
    assert s.mode == "continuous"
    assert s.domain == (1.0, 3.0)
    np.testing.assert_allclose(s.values, [1.0, np.nan, 3.0])


def test_complex_or_non_numeric_channels_rejected():
    with pytest.raises(ValueError, match="real numeric"):
        ch.resolve_color(np.array([1 + 2j, 3 + 4j]), 2, default_constant="#000")
    with pytest.raises(ValueError, match="real numeric"):
        ch.resolve_size(np.array([1 + 2j, 3 + 4j]), 2)
    with pytest.raises(ValueError, match="real numeric"):
        ch.resolve_size(np.array(["1", "2"], dtype=object), 2)
    with pytest.raises(ValueError, match="boolean"):
        ch.resolve_size(np.array([True, False]), 2)
    with pytest.raises(ValueError, match="real numeric"):
        ch.resolve_size(np.array([True, None], dtype=object), 2)
    with pytest.raises(ValueError, match="size"):
        ch.resolve_size(True, 1)


@pytest.mark.parametrize(
    "range_px",
    [
        (1.0,),
        (1.0, 2.0, 3.0),
        (-1.0, 2.0),
        (4.0, 2.0),
        (np.nan, 2.0),
        (1.0, np.inf),
    ],
)
def test_size_range_validation(range_px):
    with pytest.raises(ValueError, match="size_range"):
        ch.resolve_size(np.arange(3.0), 3, range_px=range_px)


def test_normalize_to_unit():
    out = ch.normalize_to_unit(np.array([0.0, 5.0, 10.0, np.nan]), (0.0, 10.0))
    np.testing.assert_allclose(out[:3], [0.0, 0.5, 1.0])
    assert out[3] == 0.0  # NaN → domain low → 0 (never poisons a vertex, §19)


# -- payload: channels shipped as ≤4 B/pt scalars ----------------------------


def test_continuous_color_shipped_normalized():
    n = 1000
    x = np.arange(n, dtype=np.float64)
    val = np.linspace(-50, 50, n)
    fig = Figure().scatter(x, x, color=val, colormap="viridis")
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["color"]["mode"] == "continuous"
    assert tr["color"]["colormap"] == "viridis"
    cbuf = _col(spec, blob, tr["color"]["buf"])
    assert cbuf.min() >= 0.0 and cbuf.max() <= 1.0
    assert np.isclose(cbuf[0], 0.0) and np.isclose(cbuf[-1], 1.0)
    # one f32 per point — the ≤4 B/pt channel budget (§2)
    assert len(cbuf) == n


def test_categorical_color_palette():
    n = 30
    cats = np.array(["red", "green", "blue"] * 10)
    fig = Figure().scatter(np.arange(n, dtype=float), np.arange(n, dtype=float), color=cats)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["color"]["mode"] == "categorical"
    assert tr["color"]["categories"] == ["blue", "green", "red"]
    assert len(tr["color"]["palette"]) == 3
    codes = _col(spec, blob, tr["color"]["buf"])
    assert set(np.round(codes).astype(int)) == {0, 1, 2}


def test_categorical_color_payload_handles_missing_and_mixed_objects():
    color = np.array(["a", None, "b", np.nan, 1], dtype=object)
    fig = Figure().scatter(np.arange(5.0), np.arange(5.0), color=color)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["color"]["categories"] == ["(missing)", "1", "a", "b"]
    codes = _col(spec, blob, tr["color"]["buf"])
    np.testing.assert_array_equal(codes.astype(int), [2, 0, 3, 0, 1])


def test_numeric_object_color_payload_is_continuous():
    color = np.array([1.0, None, 3.0, np.nan], dtype=object)
    fig = Figure().scatter(np.arange(4.0), np.arange(4.0), color=color)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["color"]["mode"] == "continuous"
    assert tr["color"]["domain"] == [1.0, 3.0]
    cbuf = _col(spec, blob, tr["color"]["buf"])
    np.testing.assert_allclose(cbuf, [0.0, 0.0, 1.0, 0.0])


def test_numeric_object_size_payload_is_continuous():
    size = np.array([1.0, None, 3.0, np.nan], dtype=object)
    fig = Figure().scatter(np.arange(4.0), np.arange(4.0), size=size, size_range=(2.0, 20.0))
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["size"]["mode"] == "continuous"
    assert tr["size"]["range_px"] == [2.0, 20.0]
    assert tr["size"]["domain"] == [1.0, 3.0]
    sbuf = _col(spec, blob, tr["size"]["buf"])
    np.testing.assert_allclose(sbuf, [0.0, 0.0, 1.0, 0.0])


def test_variable_size_shipped():
    n = 500
    x = np.arange(n, dtype=np.float64)
    sz = np.abs(np.sin(x * 0.1))
    fig = Figure().scatter(x, x, size=sz, size_range=(2.0, 20.0))
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["size"]["mode"] == "continuous"
    assert tr["size"]["range_px"] == [2.0, 20.0]
    assert tr["size"]["domain"] == [float(sz.min()), float(sz.max())]
    sbuf = _col(spec, blob, tr["size"]["buf"])
    assert sbuf.min() >= 0.0 and sbuf.max() <= 1.0


def test_constant_numeric_color_and_size_channels_ship_midpoint_values():
    fig = Figure().scatter(
        np.arange(4.0),
        np.arange(4.0),
        color=np.full(4, 7.0),
        size=np.full(4, 5.0),
    )
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    cbuf = _col(spec, blob, tr["color"]["buf"])
    sbuf = _col(spec, blob, tr["size"]["buf"])
    np.testing.assert_allclose(cbuf, np.full(4, 0.5, dtype=np.float32))
    np.testing.assert_allclose(sbuf, np.full(4, 0.5, dtype=np.float32))
    lo, hi = tr["color"]["domain"]
    assert lo < 7.0 < hi


def test_numpy_scalar_size_range_is_json_serializable():
    fig = Figure().scatter(
        np.arange(4.0),
        np.arange(4.0),
        size=np.arange(4.0),
        size_range=(np.float32(1.5), np.float64(12.0)),
    )
    spec, _blob = fig.build_payload()
    assert spec["traces"][0]["size"]["range_px"] == [1.5, 12.0]
    json.dumps(spec)


def test_constant_color_and_size_no_channel_buffers():
    fig = Figure().scatter(np.arange(100.0), np.arange(100.0), color="#abcdef", size=7.0)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["color"] == {"mode": "constant", "color": "#abcdef"}
    assert tr["size"] == {"mode": "constant", "size": 7.0}
    # only x and y shipped
    assert len(spec["columns"]) == 2


def test_channels_follow_nan_drop():
    # When NaN rows are dropped from the shipped copy, channels must match length.
    n = 100
    x = np.arange(n, dtype=np.float64)
    y = x.copy()
    y[[5, 50]] = np.nan
    color = np.linspace(0, 1, n)
    fig = Figure().scatter(x, y, color=color)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    xbuf = _col(spec, blob, tr["x"])
    cbuf = _col(spec, blob, tr["color"]["buf"])
    assert len(xbuf) == len(cbuf) == n - 2  # aligned after drop


# -- Tier-2 density ----------------------------------------------------------


def test_large_scatter_uses_density():
    n = SCATTER_DENSITY_THRESHOLD + 1
    rng = np.random.default_rng(0)
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    fig = Figure().scatter(x, y)
    assert fig.traces[0].use_density()
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["tier"] == "density"
    w, h = DENSITY_GRID
    grid = _col(spec, blob, tr["density"]["buf"])
    assert len(grid) == w * h
    # total count conserved for in-range points
    xr, yr = tr["density"]["x_range"], tr["density"]["y_range"]
    inrange = np.sum((x >= xr[0]) & (x < xr[1]) & (y >= yr[0]) & (y < yr[1]))
    assert grid.sum() == pytest.approx(inrange)
    assert tr["density"]["max"] == grid.max()


def test_small_scatter_stays_direct():
    fig = Figure().scatter(np.arange(1000.0), np.arange(1000.0))
    assert not fig.traces[0].use_density()
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "direct"


def test_force_density():
    fig = Figure().scatter(np.arange(100.0), np.arange(100.0), density=True)
    assert fig.traces[0].use_density()
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "density"


def test_density_view_rebins():
    # Window must hold more than the drill budget or the adaptive tier ships
    # points instead (§5: tier follows the visible count) — see drill tests.
    n = 450_000
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y)
    update, buffers = fig.density_view(0, 10.0, 90.0, 20.0, 80.0, 64, 48)
    assert len(update["traces"]) == 1
    assert update["traces"][0]["mode"] == "density"
    d = update["traces"][0]["density"]
    assert d["w"] == 64 and d["h"] == 48
    # Quantized wire (§29): density updates ship log-encoded u8, one byte per
    # cell, with `max` restoring the scale on decode.
    assert d["enc"] == "log-u8"
    assert len(buffers[0]) == 64 * 48
    grid = _decode_log_u8(buffers[0], d["max"])
    assert len(grid) == 64 * 48
    assert grid.max() == pytest.approx(d["max"])  # grid max survives exactly
    # only points inside the requested window are counted; the 8-bit log
    # round-trip is lossy per cell (sub-percent), so the total gets a band
    inwin = np.sum((x >= 10) & (x < 90) & (y >= 20) & (y < 80))
    assert inwin > SCATTER_DENSITY_THRESHOLD  # really over budget
    assert grid.sum() == pytest.approx(inwin, rel=0.05)


def test_density_view_coarsens_sparse_screen_grid():
    # A viewport just over the direct-point budget should not request a
    # near-empty one-cell-per-pixel density texture; coarser bins make drill-out
    # look continuous and reduce update size.
    n = SCATTER_DENSITY_THRESHOLD + 90_000
    rng = np.random.default_rng(12)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y, density=True)
    update, buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 1200, 800)
    tr = update["traces"][0]
    assert tr["mode"] == "density"
    d = tr["density"]
    assert d["w"] < 1200 and d["h"] < 800
    assert d["w"] * d["h"] < 1200 * 800
    grid = _decode_log_u8(buffers[0], d["max"])
    assert grid.sum() == pytest.approx(n, rel=0.05)  # 8-bit log wire (§29)


def test_density_view_drills_to_points_when_window_fits():
    # §5: the tier is a function of the *visible* count. Zooming a Tier-2
    # scatter into a window under the budget ships real points with the
    # color channel restored, in the direct-scatter wire shape.
    n = SCATTER_DENSITY_THRESHOLD + 50_000
    rng = np.random.default_rng(2)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    c = rng.uniform(0, 1, n)
    fig = Figure().scatter(x, y, color=c, density=True)
    upd, bufs = fig.density_view(0, 0.0, 10.0, 0.0, 10.0, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "points"
    inwin = int(np.sum((x >= 0) & (x <= 10) & (y >= 0) & (y <= 10)))
    assert 0 < inwin <= SCATTER_DENSITY_THRESHOLD
    assert tr["visible"] == inwin and tr["x"]["len"] == inwin
    xs = np.frombuffer(bufs[tr["x"]["buf"]], dtype=np.float32)
    assert len(xs) == inwin
    assert tr["x"]["offset"] == pytest.approx(5.0)  # §16 window-centered
    assert tr["color"]["mode"] == "continuous"
    cbuf = np.frombuffer(bufs[tr["color"]["buf"]], dtype=np.float32)
    assert len(cbuf) == inwin and cbuf.min() >= 0.0 and cbuf.max() <= 1.0
    assert fig.traces[0].drill_mode is True
    # pick speaks drilled indices: shipped 0 -> a canonical row in the window
    row = fig.pick(0, 0)
    assert row is not None and 0.0 <= row["x"] <= 10.0
    assert "color_value" in row
    # Color-continuous handoff: per-point local log-density in [0,1], a blend
    # weight = visible/budget, and the colormap the density surface uses —
    # so freshly drilled points wear the density ramp (§5, never a palette jump).
    dbuf = np.frombuffer(bufs[tr["density_val"]["buf"]], dtype=np.float32)
    assert len(dbuf) == inwin
    assert dbuf.min() >= 0.0 and dbuf.max() <= 1.0
    assert dbuf.max() == pytest.approx(1.0)  # the hottest cell hits the ramp top
    assert tr["lod_blend"] == pytest.approx(inwin / SCATTER_DENSITY_THRESHOLD)
    assert tr["density_colormap"] == "viridis"  # continuous channel's colormap
    # Channels are normalized over the *global* domain after slicing (staff
    # review: slice-first must not change values — colors stay view-stable).
    cbuf2 = np.frombuffer(bufs[tr["color"]["buf"]], dtype=np.float32)
    vis = (x >= 0) & (x <= 10) & (y >= 0) & (y <= 10)
    expected = (c[vis] - c.min()) / (c.max() - c.min())
    np.testing.assert_allclose(cbuf2, expected.astype(np.float32), rtol=1e-5, atol=1e-6)


def test_interaction_windows_reject_nonfinite_bounds():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    with pytest.raises(ValueError, match="view window"):
        fig.select_range(np.nan, 1.0, 0.0, 1.0)
    with pytest.raises(ValueError, match="view window"):
        fig.select_range(True, 1.0, 0.0, 1.0)


def test_density_view_rejects_bad_inputs_without_mutating_drill_state():
    n = SCATTER_DENSITY_THRESHOLD + 50_000
    rng = np.random.default_rng(22)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y, density=True)
    fig.density_view(0, 0.0, 1.0, 0.0, 1.0, 64, 48)
    t = fig.traces[0]
    assert t.drill_mode is True
    seq = t.drill_seq
    shipped = t.shipped_sel.copy()

    with pytest.raises(ValueError, match="trace_id"):
        fig.density_view(-1, 0.0, 1.0, 0.0, 1.0, 64, 48)
    with pytest.raises(ValueError, match="view window"):
        fig.density_view(0, 0.0, np.inf, 0.0, 1.0, 64, 48)
    with pytest.raises(ValueError, match="view window"):
        fig.density_view(0, "left", 1.0, 0.0, 1.0, 64, 48)
    with pytest.raises(ValueError, match="view window"):
        fig.density_view(0, True, 1.0, 0.0, 1.0, 64, 48)
    with pytest.raises(ValueError, match="screen dimensions"):
        fig.density_view(0, 0.0, 1.0, 0.0, 1.0, np.nan, 48)
    with pytest.raises(ValueError, match="screen dimensions"):
        fig.density_view(0, 0.0, 1.0, 0.0, 1.0, "wide", 48)
    with pytest.raises(ValueError, match="screen dimensions"):
        fig.density_view(0, 0.0, 1.0, 0.0, 1.0, True, 48)

    assert t.drill_mode is True
    assert t.drill_seq == seq
    np.testing.assert_array_equal(t.shipped_sel, shipped)


def test_density_view_clamps_huge_frontend_screen_shape(monkeypatch):
    from fastcharts import interaction

    n = SCATTER_DENSITY_THRESHOLD + 1
    x = np.linspace(0.0, 100.0, n)
    fig = Figure().scatter(x, x, density=True)
    seen_shapes = []

    def fake_bin_2d(_x, _y, _lo_x, _hi_x, _lo_y, _hi_y, w, h):
        seen_shapes.append((w, h))
        return np.zeros(1, dtype=np.float64)

    monkeypatch.setattr(interaction.kernels, "bin_2d", fake_bin_2d)
    update, buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 10**12, 10**12)
    shape = seen_shapes[0]
    density = update["traces"][0]["density"]
    assert 16 <= shape[0] <= MAX_SCREEN_DIM
    assert 16 <= shape[1] <= MAX_SCREEN_DIM
    assert density["w"] == shape[0]
    assert density["h"] == shape[1]
    assert len(buffers[0]) == 1  # log-u8 wire: one byte per grid cell (§29)


def test_drill_seq_guards_stale_picks():
    # A pick that raced a drill update must return None — never a row read
    # through the wrong index space (§16: exact or nothing).
    # n chosen so the full window (n visible) clears the 1.15x hysteresis exit.
    n = SCATTER_DENSITY_THRESHOLD + 50_000
    rng = np.random.default_rng(11)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y, density=True)
    upd1, _ = fig.density_view(0, 0.0, 10.0, 0.0, 10.0, 512, 384)
    seq1 = upd1["traces"][0]["drill_seq"]
    assert seq1 == 1
    assert fig.pick(0, 0, drill_seq=seq1) is not None  # matching subset: exact row
    assert fig.pick(0, 0) is not None  # legacy caller without seq still works
    assert fig.pick(0, 0, drill_seq=True) is None  # bool must not alias seq 1

    upd2, _ = fig.density_view(0, 20.0, 30.0, 20.0, 30.0, 512, 384)
    seq2 = upd2["traces"][0]["drill_seq"]
    assert seq2 == seq1 + 1
    assert fig.pick(0, 0, drill_seq=seq1) is None  # stale subset: dropped
    assert fig.pick(0, 0, drill_seq=seq2) is not None

    # Drill-out bumps the version too: a drilled-index pick arriving after the
    # subset died must not be read as a *canonical* index.
    upd3, _ = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 512, 384)
    assert upd3["traces"][0]["mode"] == "density"
    assert fig.pick(0, 0, drill_seq=seq2) is None
    # out-of-range trace ids are rejected, not wrapped pythonically
    assert fig.pick(-1, 0) is None
    assert fig.pick(99, 0) is None


def test_drill_lod_blend_shrinks_as_zoom_deepens():
    # The density-ramp blend eases out with the visible count, so colors morph
    # gradually toward native channel colors instead of stepping at the boundary.
    n = SCATTER_DENSITY_THRESHOLD + 50_000
    rng = np.random.default_rng(7)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y, density=True)
    upd_wide, _ = fig.density_view(0, 0.0, 60.0, 0.0, 60.0, 512, 384)
    upd_deep, _ = fig.density_view(0, 0.0, 5.0, 0.0, 5.0, 512, 384)
    assert upd_wide["traces"][0]["mode"] == "points"
    assert upd_deep["traces"][0]["mode"] == "points"
    assert upd_deep["traces"][0]["lod_blend"] < upd_wide["traces"][0]["lod_blend"]
    # constant-color scatter still gets the default density ramp for the handoff
    assert upd_deep["traces"][0]["density_colormap"] == ch.DEFAULT_COLORMAP


def test_density_view_returns_to_density_on_zoom_out():
    n = 450_000
    rng = np.random.default_rng(3)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    fig = Figure().scatter(x, y)
    fig.density_view(0, 0.0, 1.0, 0.0, 1.0, 64, 48)  # drill in
    assert fig.traces[0].drill_mode is True
    upd, _ = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 64, 48)  # zoom out
    assert upd["traces"][0]["mode"] == "density"
    assert fig.traces[0].drill_mode is False
    assert fig.traces[0].shipped_sel is None


def test_drill_hysteresis_holds_points_mode_near_boundary():
    # §5 "tier transitions hysteresis-guarded": once drilled, a window just
    # over the threshold stays in points mode; entered cold, it aggregates.
    n = 450_000
    rng = np.random.default_rng(4)
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    side = 69.9  # ~0.489 of the area -> ~220k points: inside the 1.15x guard
    inwin = int(np.sum((x >= 0) & (x <= side) & (y >= 0) & (y <= side)))
    assert SCATTER_DENSITY_THRESHOLD < inwin < 1.15 * SCATTER_DENSITY_THRESHOLD

    fig = Figure().scatter(x, y)
    fig.density_view(0, 0.0, 10.0, 0.0, 10.0, 64, 48)  # enter points mode
    assert fig.traces[0].drill_mode is True
    upd, _ = fig.density_view(0, 0.0, side, 0.0, side, 64, 48)
    assert upd["traces"][0]["mode"] == "points"  # held by hysteresis

    fig2 = Figure().scatter(x, y)
    upd2, _ = fig2.density_view(0, 0.0, side, 0.0, side, 64, 48)
    assert upd2["traces"][0]["mode"] == "density"  # cold entry aggregates


def test_huge_scatter_with_channels_warns_and_drops():
    from fastcharts.figure import DIRECT_SOFT_CEILING

    n = DIRECT_SOFT_CEILING + 1
    x = np.zeros(n)
    color = np.arange(n, dtype=np.float64)
    with pytest.warns(RuntimeWarning, match="dropped"):
        fig = Figure().scatter(x, x, color=color)
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "density"
    assert spec["traces"][0]["density"]["channels_dropped"] is True


# -- pick / hover drill ------------------------------------------------------


def test_pick_returns_exact_row():
    x = np.array([10.0, 20.0, 30.0])
    y = np.array([1.5, 2.5, 3.5])
    color = np.array([100.0, 200.0, 300.0])
    size = np.array([1.0, 2.0, 3.0])
    fig = Figure().scatter(x, y, color=color, size=size)
    row = fig.pick(0, 1)
    assert row["x"] == 20.0
    assert row["y"] == 2.5
    assert row["color_value"] == 200.0
    assert row["size_value"] == 2.0


def test_pick_categorical():
    cats = np.array(["cat", "dog", "cat"])
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0), color=cats)
    row = fig.pick(0, 1)
    assert row["color_category"] == "dog"


def test_pick_time_axis_exact():
    # Exact ms timestamp from f64 canonical, not through f32 (§16).
    t = np.array(["2024-06-01T00:00:00", "2024-06-01T00:00:01"], dtype="datetime64[s]")
    fig = Figure().scatter(t, np.array([1.0, 2.0]))
    row = fig.pick(0, 1)
    assert row["x_kind"] == "time_ms"
    assert row["x"] == float(
        np.datetime64("2024-06-01T00:00:01").astype("datetime64[ms]").astype(np.int64)
    )


def test_pick_out_of_range():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    assert fig.pick(0, 99) is None
    assert fig.pick(0, -1) is None
    assert fig.pick(-1, 0) is None
    assert fig.pick(0.0, 0) is None
    assert fig.pick(True, 0) is None
    assert fig.pick(0, 1.0) is None
    assert fig.pick(0, True) is None


# -- shipped↔canonical translation (staff-review regressions) ----------------


def test_pick_translates_shipped_index_after_nan_drop():
    # Rows 1 and 3 are dropped at ship time; the client's shipped index 1 is
    # canonical row 2. Without translation, pick reported the wrong row.
    x = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    y = np.array([10.0, 11.0, 12.0, np.nan, 14.0])
    fig = Figure().scatter(x, y)
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "direct"
    row = fig.pick(0, 1)  # shipped index 1 == canonical row 2
    assert row["x"] == 2.0 and row["y"] == 12.0
    row_last = fig.pick(0, 2)  # shipped index 2 == canonical row 4
    assert row_last["x"] == 4.0 and row_last["y"] == 14.0
    assert fig.pick(0, 3) is None  # only 3 shipped vertices


def test_pick_translates_nan_drop_before_payload_build():
    x = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    y = np.array([10.0, 11.0, 12.0, np.nan, 14.0])
    fig = Figure().scatter(x, y)
    row = fig.pick(0, 1)  # shipped index 1 == canonical row 2
    assert row is not None
    assert row["index"] == 2
    assert row["x"] == 2.0 and row["y"] == 12.0
    assert fig.pick(0, 3) is None


def test_selection_translates_to_shipped_positions():
    x = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    y = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    fig = Figure().scatter(x, y)
    fig.build_payload()  # establishes shipped_sel = [0, 2, 3, 4]
    canonical = fig.select_range(1.5, 3.5, 0.0, 100.0)[0]  # rows 2, 3
    np.testing.assert_array_equal(canonical, [2, 3])
    shipped = fig.to_shipped_indices(0, canonical)
    np.testing.assert_array_equal(shipped, [1, 2])  # positions in shipped buffer


def test_to_shipped_indices_translates_nan_drop_before_payload_build():
    x = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    y = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    fig = Figure().scatter(x, y)
    canonical = fig.select_range(1.5, 3.5, 0.0, 100.0)[0]
    np.testing.assert_array_equal(canonical, [2, 3])
    np.testing.assert_array_equal(fig.to_shipped_indices(0, canonical), [1, 2])


def test_density_pick_before_payload_build_has_no_point_space():
    n = SCATTER_DENSITY_THRESHOLD + 1
    x = np.arange(n, dtype=np.float64)
    fig = Figure().scatter(x, x, density=True)
    assert fig.pick(0, 0) is None
    np.testing.assert_array_equal(fig.to_shipped_indices(0, np.array([0], dtype=np.uint32)), [])


def test_selection_helpers_reject_invalid_trace_ids():
    fig = Figure().scatter(np.arange(5.0), np.arange(5.0))
    fig.build_payload()
    idx = np.array([1, 2], dtype=np.uint32)

    with pytest.raises(ValueError, match="trace_id"):
        fig.to_shipped_indices(-1, idx)
    with pytest.raises(ValueError, match="trace_id"):
        fig.to_shipped_indices(1.0, idx)
    with pytest.raises(ValueError, match="trace_id"):
        fig.select_range(0.0, 4.0, 0.0, 4.0, trace_id=-1)
    with pytest.raises(ValueError, match="trace_id"):
        fig.select_range(0.0, 4.0, 0.0, 4.0, trace_id=True)


def test_to_shipped_indices_identity_without_drop():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    fig.build_payload()
    idx = np.array([3, 7], dtype=np.uint32)
    np.testing.assert_array_equal(fig.to_shipped_indices(0, idx), idx)


def test_density_false_is_honored():
    # density=False must force direct draw (it was silently ignored before).
    n = SCATTER_DENSITY_THRESHOLD + 1
    x = np.zeros(n)
    fig = Figure().scatter(x, x, density=False)
    assert not fig.traces[0].use_density()
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "direct"


def test_density_false_above_ceiling_warns():
    from fastcharts.figure import DIRECT_SOFT_CEILING

    n = DIRECT_SOFT_CEILING + 1
    x = np.zeros(n)
    with pytest.warns(RuntimeWarning, match="direct draw above the ceiling"):
        Figure().scatter(x, x, density=False)


def test_to_html_escapes_user_strings():
    # User text crosses into both <title> and an inline JSON literal. Escape the
    # full HTML-sensitive set, not only the obvious lowercase </script> case.
    evil = "</ScRiPt><!--<img src=x onerror=alert(1)>&"
    fig = Figure(title=evil, x_label=evil, y_label=evil).bar([evil, "safe"], [1.0, 2.0], name=evil)
    html = fig.to_html()
    body = html.split("<body>", 1)[1]
    assert "</script><img" not in body  # broken-out tag never appears verbatim
    spec_literal = body.rsplit("const spec = ", 1)[1].split(";\n  const b64", 1)[0]
    assert "<" not in spec_literal
    assert ">" not in spec_literal
    assert "&" not in spec_literal
    assert "\\u003c/ScRiPt\\u003e" in spec_literal
    assert "\\u0026" in spec_literal
    head = html.split("<body>", 1)[0]
    assert "&lt;/ScRiPt&gt;" in head  # <title> is entity-escaped


def test_line_with_nan_x_sorts_and_excludes():
    # NaN in x must not defeat the sorted-x check (any(diff<0) is NaN-blind);
    # after the fix the trace sorts, NaNs land last, and m4 excludes them.
    n = 20_000
    x = np.arange(n, dtype=np.float64)
    x[[100, 5000]] = np.nan
    y = np.sin(np.arange(n) * 0.01)
    fig = Figure().line(x, y)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    xbuf = np.frombuffer(
        blob,
        dtype=np.float32,
        count=spec["columns"][tr["x"]]["len"],
        offset=spec["columns"][tr["x"]]["byte_offset"],
    )
    assert not np.isnan(xbuf).any()  # §19: NaN never reaches a vertex buffer
