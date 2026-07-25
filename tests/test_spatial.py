"""SpatialIndex reader (Tier-3 out-of-core windowed query, dossier §28/§32b).

Builds a tiny index by hand (no Rust dependency) and pins the query contract:
per-cell grouping, window counting, windowed gather, and exact windowed density
equal to a direct bin over the in-window points.
"""

from __future__ import annotations

import struct

import numpy as np

import xy
from xy import kernels
from xy._spatial import SpatialIndex

_MAGIC = b"XYSPIDX1"


def _write_index(tmp_path, g, extent, lon, lat):
    """Sort (lon,lat) into row-major cells and write <prefix>.idx/.lon.f32/.lat.f32."""
    x0, x1, y0, y1 = extent
    lon = np.asarray(lon, np.float32)
    lat = np.asarray(lat, np.float32)
    ix = np.clip(((lon.astype(np.float64) - x0) / (x1 - x0) * g).astype(int), 0, g - 1)
    iy = np.clip(((lat.astype(np.float64) - y0) / (y1 - y0) * g).astype(int), 0, g - 1)
    cell = iy * g + ix
    order = np.argsort(cell, kind="stable")
    slon, slat, scell = lon[order], lat[order], cell[order]
    counts = np.bincount(scell, minlength=g * g).astype(np.uint64)
    offsets = np.zeros(g * g + 1, dtype=np.uint64)
    offsets[1:] = np.cumsum(counts)
    prefix = str(tmp_path / "idx")
    with open(prefix + ".idx", "wb") as f:
        f.write(_MAGIC)
        f.write(struct.pack("<II", g, 0))
        f.write(struct.pack("<dddd", *extent))
        f.write(struct.pack("<Q", len(lon)))
        f.write(offsets.tobytes())
    slon.tofile(prefix + ".lon.f32")
    slat.tofile(prefix + ".lat.f32")
    return prefix


def test_load_and_cell_grouping(tmp_path):
    g, extent = 4, (0.0, 4.0, 0.0, 4.0)
    rng = np.random.default_rng(0)
    lon = rng.uniform(0, 4, 5000)
    lat = rng.uniform(0, 4, 5000)
    idx = SpatialIndex.load(_write_index(tmp_path, g, extent, lon, lat))
    assert idx.g == g and idx.n == 5000
    # Every point in cell b's offset range must fall in cell b.
    for b in range(g * g):
        lo, hi = int(idx.offsets[b]), int(idx.offsets[b + 1])
        cx, cy = b % g, b // g
        for k in range(lo, hi):
            assert int(idx.lon[k]) == cx and int(idx.lat[k]) == cy


def test_window_count_and_gather(tmp_path):
    g, extent = 8, (0.0, 8.0, 0.0, 8.0)
    # 3 points per cell → predictable counts.
    xs, ys = np.meshgrid(np.arange(8) + 0.5, np.arange(8) + 0.5)
    lon = np.repeat(xs.ravel(), 3).astype(np.float64)
    lat = np.repeat(ys.ravel(), 3).astype(np.float64)
    idx = SpatialIndex.load(_write_index(tmp_path, g, extent, lon, lat))
    # Window covering cells x in {2,3}, y in {5,6} → 4 cells × 3 pts = 12.
    assert idx.window_count(2.1, 3.9, 5.1, 6.9) == 12
    gl, gt = idx.gather(2.1, 3.9, 5.1, 6.9)
    assert len(gl) == 12
    assert set(gl.astype(int)) <= {2, 3}  # cell centers 2.5, 3.5 → trunc 2, 3
    assert set(gt.astype(int)) <= {5, 6}


def test_density_grid_matches_direct_bin(tmp_path):
    g, extent = 32, (-10.0, 10.0, -10.0, 10.0)
    rng = np.random.default_rng(1)
    n = 200_000
    lon = np.clip(rng.normal(0, 3, n), -10, 9.999)
    lat = np.clip(rng.normal(0, 3, n), -10, 9.999)
    idx = SpatialIndex.load(_write_index(tmp_path, g, extent, lon, lat))
    wx0, wx1, wy0, wy1, w, h = -4.0, 4.0, -3.0, 3.0, 100, 80
    grid = idx.density_grid(wx0, wx1, wy0, wy1, w, h)
    # Oracle: bin the in-window points directly (f32 to match the index dtype).
    gl, gt = idx.gather(wx0, wx1, wy0, wy1)
    oracle = kernels.bin_2d(gl, gt, wx0, wx1, wy0, wy1, w, h)
    assert np.array_equal(grid, oracle)
    assert grid.sum() > 0


def test_density_view_drills_to_crisp_points_then_grids(tmp_path):
    """A spatial-indexed density trace ships real points (crisp drill-in) when
    the *actual* in-window count fits the direct budget, and an exact
    screen-res grid when it exceeds it — the decision keyed on the true count,
    not the whole-cell overhang upper bound."""
    g, extent = 64, (-10.0, 10.0, -10.0, 10.0)
    rng = np.random.default_rng(2)
    n = 400_000
    lon = np.clip(rng.normal(0, 3, n), -10, 9.999)
    lat = np.clip(rng.normal(0, 3, n), -10, 9.999)
    idx = SpatialIndex.load(_write_index(tmp_path, g, extent, lon, lat))
    fig = xy.chart(xy.scatter(x=lon, y=lat, density=True)).figure()
    fig.traces[0]._spatial_index = idx

    # Tight window: a handful of points → crisp drill (mode="points").
    wx0, wx1, wy0, wy1 = -0.1, 0.1, -0.1, 0.1
    spec, bufs = fig.density_view(0, wx0, wx1, wy0, wy1, 1000, 800)
    tr = spec["traces"][0]
    in_window = int(((lon >= wx0) & (lon <= wx1) & (lat >= wy0) & (lat <= wy1)).sum())
    assert tr["mode"] == "points" and tr["binning"] == "spatial-points"
    assert tr["visible"] == in_window
    assert 0 < in_window <= 200_000
    assert bufs  # x/y (+ density_val) vertex buffers shipped

    # Whole domain: well over the direct budget → exact grid, not points.
    spec2, _ = fig.density_view(0, -10.0, 10.0, -10.0, 10.0, 1000, 800)
    tr2 = spec2["traces"][0]
    assert tr2["mode"] == "density" and tr2["binning"] == "spatial-exact"
    assert tr2["visible"] > 200_000
