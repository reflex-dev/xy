"""Drill-to-points at any N: the v2 spatial index (LOD doc §4.5 / dossier §32b).

Past the no-rescan bound the O(N) window scan a drill needs is forbidden, so
`ensure_drill_index` builds a cell-sorted disk index carrying canonical row
ids and the wire's own quantized channel planes. These tests pin the whole
contract: the builder's layout, byte-identical drill replies (the index is a
row FINDER — the reply itself is the ordinary `_drill_points`), exact picks,
T13 padding through the index's row finder, the mean-color spatial-exact
grid, append invalidation with temp-file cleanup, and the headline: a trace
in the no-rescan regime drills to points.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

import xy
from xy import _spatial, channels, interaction
from xy._figure import Figure
from xy.config import SCATTER_DENSITY_THRESHOLD

N = SCATTER_DENSITY_THRESHOLD * 3


@pytest.fixture()
def cloud():
    rng = np.random.default_rng(7)
    x = rng.normal(0, 1, N)
    y = rng.normal(0, 0.55, N) + 0.55 * x
    color = np.hypot(x, y)
    size = rng.uniform(2, 16, N)
    return x, y, color, size


def _figure(cloud) -> Figure:
    x, y, color, size = cloud
    return xy.scatter_chart(
        xy.scatter(x, y, color=color, size=size, colormap="viridis", opacity=0.72, density=True)
    ).figure()


def _no_rescan(monkeypatch, rows: int) -> None:
    monkeypatch.setattr(interaction, "PYRAMID_NO_RESCAN_ROWS", rows)


# --- builder ----------------------------------------------------------------


def test_builder_layout_planes_and_nan_rows(tmp_path, cloud):
    x, y, color, size = cloud
    x = x.copy()
    x[::97] = np.nan  # §19: non-finite rows never enter the index
    c8 = channels.quantize_unit_u8(color, (0.0, 4.0))
    s8 = channels.quantize_unit_u8(size, (2.0, 16.0))
    idx = _spatial.build(str(tmp_path / "t"), x, y, color_u8=c8, size_u8=s8, g=64)
    finite = np.isfinite(x) & np.isfinite(y)
    assert idx.n == int(finite.sum())

    win = (-0.5, 0.7, -0.3, 0.4)
    planes = idx.gather_planes(*win)
    inside = (
        (planes["lon"] >= win[0])
        & (planes["lon"] <= win[1])
        & (planes["lat"] >= win[2])
        & (planes["lat"] <= win[3])
    )
    rows = np.sort(planes["rows"][inside])
    xf, yf = x.astype(np.float32), y.astype(np.float32)
    brute = np.flatnonzero(
        finite & (xf >= win[0]) & (xf <= win[1]) & (yf >= win[2]) & (yf <= win[3])
    )
    assert np.array_equal(rows, brute)
    take = planes["rows"][inside]
    assert np.array_equal(planes["color_u8"][inside], c8[take])
    assert np.array_equal(planes["size_u8"][inside], s8[take])
    assert idx.window_count(*win) >= len(rows)  # whole-cell upper bound
    # Ascending canonical order within every cell (drill ships sorted rows).
    for b in range(idx.g * idx.g):
        lo, hi = int(idx.offsets[b]), int(idx.offsets[b + 1])
        if hi - lo > 1:
            assert np.all(np.diff(idx.rows[lo:hi].astype(np.int64)) > 0)


def test_builder_empty_and_v1_reader_still_load(tmp_path):
    empty = _spatial.build(str(tmp_path / "e"), np.empty(0), np.empty(0), g=4)
    assert empty.n == 0 and empty.window_count(0, 1, 0, 1) == 0
    planes = empty.gather_planes(0.0, 1.0, 0.0, 1.0)
    assert all(len(v) == 0 for v in planes.values())
    # v1 files (external osm-sort) keep loading: no rows, no channel planes —
    # covered in depth by tests/test_spatial.py; here just the plane surface.
    assert "rows" in planes  # v2 always carries rows


# --- drill parity: the index is a row finder, the reply is the scan's -------


@pytest.mark.parametrize(
    "win",
    [(0.4, 0.8, 0.25, 0.55), (-0.05, 0.12, -0.03, 0.09), (2.4, 3.4, 1.4, 2.6)],
)
def test_index_drill_is_byte_identical_to_scan_drill(monkeypatch, cloud, win):
    scan_fig = _figure(cloud)
    scan_upd, scan_bufs = scan_fig.density_view(0, *win, 512, 384)
    assert scan_upd["traces"][0]["mode"] == "points"

    _no_rescan(monkeypatch, N - 1)
    idx_fig = _figure(cloud)
    idx_fig.ensure_drill_index(0)
    idx_upd, idx_bufs = idx_fig.density_view(0, *win, 512, 384)
    it = idx_upd["traces"][0]
    assert it["mode"] == "points"
    # Same rows, same shipped (T13-padded) window, same bytes in every buffer.
    assert np.array_equal(scan_fig.traces[0].shipped_sel, idx_fig.traces[0].shipped_sel)
    assert len(scan_bufs) == len(idx_bufs)
    assert all(bytes(a) == bytes(b) for a, b in zip(scan_bufs, idx_bufs, strict=True))
    st = scan_upd["traces"][0]
    for key in ("visible", "x_range", "y_range", "color", "size", "lod_blend", "tier"):
        assert st[key] == it[key], key


def test_index_drill_pick_reads_exact_canonical_rows(monkeypatch, cloud):
    x, y, color, size = cloud
    _no_rescan(monkeypatch, N - 1)
    fig = _figure(cloud)
    fig.ensure_drill_index(0)
    upd, _ = fig.density_view(0, 2.4, 3.4, 1.4, 2.6, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "points"
    row = fig.pick(0, 5, tr["drill_seq"])
    canon = int(fig.traces[0].shipped_sel[5])
    assert row is not None and row["index"] == canon
    assert row["x"] == float(x[canon]) and row["y"] == float(y[canon])
    assert row["color_value"] == float(color[canon])
    assert row["size_value"] == float(size[canon])


# --- the headline: the no-rescan regime drills ------------------------------


def test_no_rescan_trace_drills_with_index_and_floors_without(monkeypatch, cloud):
    _no_rescan(monkeypatch, N - 1)
    win = (0.4, 0.8, 0.25, 0.55)

    blocked = _figure(cloud)
    b, _ = blocked.density_view(0, *win, 512, 384)
    assert b["traces"][0]["mode"] == "density"  # the pre-index 200M cliff

    fig = _figure(cloud)
    fig.ensure_drill_index(0)
    upd, _ = fig.density_view(0, *win, 512, 384)
    assert upd["traces"][0]["mode"] == "points"
    # Re-calling is a no-op while attached.
    assert fig.ensure_drill_index(0) is fig.traces[0]._spatial_index


def test_no_rescan_mid_band_gets_mean_color_spatial_exact_grid(monkeypatch, cloud):
    _no_rescan(monkeypatch, N - 1)
    fig = _figure(cloud)
    fig.ensure_drill_index(0)
    # A window over the drill budget but affordable to gather: exact grid at
    # screen resolution wearing the mean point color from the index's plane.
    upd, bufs = fig.density_view(0, -0.6, 1.2, -0.5, 0.9, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "density" and tr["binning"] == "spatial-exact"
    d = tr["density"]
    assert d["color_agg"] == "mean" and d["filter"] == "nearest"
    rgba = np.frombuffer(bufs[d["rgba"]], dtype=np.uint8)
    assert rgba.any()


# --- lifecycle ---------------------------------------------------------------


def test_append_detaches_index_and_removes_temp_planes(cloud):
    fig = _figure(cloud)
    sidx = fig.ensure_drill_index(0)
    prefix_dir = os.path.dirname(sidx.lon.filename)
    assert os.path.exists(sidx.lon.filename)
    fig.append(0, [0.5], [0.5], color=[1.0], size=[4.0])
    t = fig.traces[0]
    assert t._spatial_index is None
    assert not os.path.exists(prefix_dir)  # temp planes deleted on detach


def test_memory_report_itemizes_mapped_index_bytes(cloud):
    fig = _figure(cloud)
    before = fig.memory_report()
    assert before["spatial_index_mapped_bytes"] == 0
    sidx = fig.ensure_drill_index(0)
    report = fig.memory_report()
    per_point = 4 + 4 + 4 + 1 + 1  # lon f32 + lat f32 + rows u32 + color + size
    assert report["spatial_index_mapped_bytes"] == sidx.n * per_point + sidx.offsets.nbytes
    # Disk-backed, reclaimable: never folded into resident_array_bytes.
    assert report["resident_array_bytes"] == before["resident_array_bytes"]
