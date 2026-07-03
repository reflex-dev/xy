"""Figure / spec / payload contracts: data-less spec (§9), single-copy store
(§4), decimation tiering with no silent reductions (§28), NaN never in vertex
buffers (§19), memory report honesty (§27)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from fastcharts import Figure
from fastcharts.figure import PROTOCOL_VERSION


def _payload_col(spec, blob, ref):
    meta = spec["columns"][ref]
    start = meta["byte_offset"]
    return np.frombuffer(blob, dtype=np.float32, count=meta["len"], offset=start), meta


def test_spec_is_dataless_json():
    fig = Figure(title="t").scatter(np.arange(1000.0), np.arange(1000.0))
    spec, blob = fig.build_payload()
    # The spec must be tiny and JSON-serializable; data rides in the blob.
    text = json.dumps(spec)
    assert len(text) < 4096
    assert spec["protocol"] == PROTOCOL_VERSION
    assert len(blob) == 2 * 1000 * 4  # two f32 columns


def test_offset_encoding_roundtrip():
    x = 1.6e12 + np.arange(5000, dtype=np.float64)  # ms timestamps
    y = np.sin(np.arange(5000) * 0.01)
    fig = Figure().scatter(x, y)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    xe, xm = _payload_col(spec, blob, tr["x"])
    decoded = xe.astype(np.float64) / xm["scale"] + xm["offset"]
    assert np.abs(decoded - x).max() < 1e-3
    assert spec["x_axis"]["kind"] == "linear"  # plain floats, not datetime64


def test_time_axis_detection():
    t = np.arange("2024-01-01", "2024-03-01", dtype="datetime64[h]")
    fig = Figure().line(t, np.arange(len(t), dtype=np.float64))
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["kind"] == "time"
    xm = spec["columns"][spec["traces"][0]["x"]]
    assert xm["kind"] == "time_ms"


def test_long_line_ships_decimated():
    n = 200_000
    x = np.arange(n, dtype=np.float64)
    y = np.sin(x * 0.001)
    y[123_456] = 99.0
    fig = Figure().line(x, y)
    spec, blob = fig.build_payload(px_width=1024)
    tr = spec["traces"][0]
    assert tr["tier"] == "decimated"  # reduction recorded, never silent (§28)
    assert tr["n_points"] == n  # canonical count still reported
    ye, ym = _payload_col(spec, blob, tr["y"])
    assert len(ye) <= 4096  # ≤ 4 per pixel column
    # The spike survived decimation (M4 guarantee).
    assert np.isclose(ye.astype(np.float64).max() + ym["offset"], 99.0, atol=1e-3)


def test_short_line_ships_direct():
    fig = Figure().line(np.arange(100.0), np.arange(100.0))
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "direct"


def test_nan_never_reaches_vertex_buffers():
    x = np.arange(1000.0)
    y = np.arange(1000.0)
    y[[10, 500, 990]] = np.nan
    fig = Figure().scatter(x, y)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    ye, _ = _payload_col(spec, blob, tr["y"])
    assert not np.isnan(ye).any()  # §19
    assert len(ye) == 997


def test_unsorted_line_sorted_at_ingest():
    x = np.array([3.0, 1.0, 2.0])
    y = np.array([30.0, 10.0, 20.0])
    fig = Figure().line(x, y)
    tr = fig.traces[0]
    np.testing.assert_array_equal(tr.x.values, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(tr.y.values, [10.0, 20.0, 30.0])


def test_column_store_dedup():
    x = np.arange(10_000.0)
    y1 = np.sin(x)
    y2 = np.cos(x)
    fig = Figure().line(x, y1).line(x, y2)
    # x ingested once: 3 columns, not 4 (§18 shared-columns).
    assert len(fig.store) == 3


def test_decimate_view_recenters_offset():
    n = 100_000
    x = 1.6e12 + np.arange(n, dtype=np.float64)
    y = np.sin(np.arange(n) * 1e-3)
    fig = Figure().line(x, y)
    x0, x1 = 1.6e12 + 40_000, 1.6e12 + 41_000  # deep-zoom window
    update, buffers = fig.decimate_view(x0, x1, 512)
    assert len(update["traces"]) == 1
    upd = update["traces"][0]
    assert upd["x"]["offset"] == (x0 + x1) / 2  # §16 re-centering
    xe = np.frombuffer(buffers[upd["x"]["buf"]], dtype=np.float32)
    decoded = xe.astype(np.float64) + upd["x"]["offset"]
    assert decoded.min() >= x0 - 1
    assert decoded.max() <= x1 + 1
    # Sub-ms precision inside the window even though |x| ~ 1.6e12.
    assert np.abs(np.diff(decoded) - np.round(np.diff(decoded))).max() < 1e-3


def test_autorange_from_zone_maps():
    x = np.linspace(-5, 5, 1000)
    fig = Figure().scatter(x, x * 2)
    (lo, hi) = fig.x_range()
    assert lo < -5 < 5 < hi
    (ylo, yhi) = fig.y_range()
    assert ylo < -10 < 10 < yhi


def test_memory_report_accounts_for_bytes():
    n = 100_000
    x = np.arange(n, dtype=np.float64)
    fig = Figure().scatter(x, x + 1)
    report = fig.memory_report()
    assert report["canonical_bytes"] == 2 * n * 8
    # Direct scatter transport: 8 bytes/point (x,y f32) — the §2 target's payload.
    assert report["transport_bytes_per_point"] == pytest.approx(8.0)


def test_scatter_soft_ceiling_warns():
    n = 2_000_001
    x = np.zeros(n)
    with pytest.warns(RuntimeWarning, match="soft ceiling"):
        Figure().scatter(x, x)


def test_to_html_standalone():
    fig = Figure(title="export").line(np.arange(100.0), np.arange(100.0))
    html = fig.to_html()
    assert "renderStandalone" in html
    assert "webgl2" in html or "fastcharts" in html


def test_responsive_width_in_spec():
    # width="100%" rides the spec verbatim; the client measures the container
    # and re-requests decimation/density at the new pixel width on resize.
    x = np.arange(10.0)
    fig = Figure(width="100%").scatter(x, x)
    spec, _ = fig.build_payload()
    assert spec["width"] == "100%"
    assert spec["height"] == 420
    json.dumps(spec)  # still plain JSON


def test_responsive_width_rejects_other_strings():
    with pytest.raises(ValueError, match="100%"):
        Figure(width="50vw")
