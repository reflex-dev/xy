"""Full scatter: color/size channels (§36c), Tier-2 density aggregation (§5),
hover pick with exact f64 readout (§16/§17)."""

from __future__ import annotations

import numpy as np
import pytest

from fastcharts import Figure
from fastcharts import channels as ch
from fastcharts.figure import DENSITY_GRID, SCATTER_DENSITY_THRESHOLD


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


def test_variable_size_shipped():
    n = 500
    x = np.arange(n, dtype=np.float64)
    sz = np.abs(np.sin(x * 0.1))
    fig = Figure().scatter(x, x, size=sz, size_range=(2.0, 20.0))
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["size"]["mode"] == "continuous"
    assert tr["size"]["range_px"] == [2.0, 20.0]
    sbuf = _col(spec, blob, tr["size"]["buf"])
    assert sbuf.min() >= 0.0 and sbuf.max() <= 1.0


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
    grid = np.frombuffer(buffers[0], dtype=np.float32)
    assert len(grid) == 64 * 48
    # only points inside the requested window are counted
    inwin = np.sum((x >= 10) & (x < 90) & (y >= 20) & (y < 80))
    assert inwin > SCATTER_DENSITY_THRESHOLD  # really over budget
    assert grid.sum() == pytest.approx(inwin)


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
    grid = np.frombuffer(buffers[0], dtype=np.float32)
    assert grid.sum() == pytest.approx(n)


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


def test_selection_translates_to_shipped_positions():
    x = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    y = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    fig = Figure().scatter(x, y)
    fig.build_payload()  # establishes shipped_sel = [0, 2, 3, 4]
    canonical = fig.select_range(1.5, 3.5, 0.0, 100.0)[0]  # rows 2, 3
    np.testing.assert_array_equal(canonical, [2, 3])
    shipped = fig.to_shipped_indices(0, canonical)
    np.testing.assert_array_equal(shipped, [1, 2])  # positions in shipped buffer


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
    # A title shaped like "</script>…" must not break out of the script block
    # (markup injection in exported HTML) and must be entity-escaped in <title>.
    evil = "</script><img src=x onerror=alert(1)>"
    fig = Figure(title=evil).scatter(np.arange(3.0), np.arange(3.0), name=evil)
    html = fig.to_html()
    body = html.split("<body>", 1)[1]
    assert "</script><img" not in body  # broken-out tag never appears verbatim
    assert "<\\/script>" in body  # escaped inside the JSON spec instead
    head = html.split("<body>", 1)[0]
    assert "&lt;/script&gt;" in head  # <title> is entity-escaped


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
