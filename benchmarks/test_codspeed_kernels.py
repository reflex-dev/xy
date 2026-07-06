"""CodSpeed benchmarks for the fastcharts native compute core.

These exercise the performance-critical kernels the whole engine is built on
(§5 decimation tiers, §4/§16 f32 encoding, §22 zone maps) plus the end-to-end
figure -> wire-payload path. CodSpeed must track the native Rust backend only;
fallback timings are correctness smoke data, not production performance data.

Run locally with:

    codspeed run --mode simulation -- pytest benchmarks/test_codspeed_kernels.py --codspeed
"""

from __future__ import annotations

import numpy as np
import pytest

from fastcharts import Figure
from fastcharts import kernels as k

# One million points: a representative "large dataset" workload where the
# engine's cost-scales-with-pixels design is what keeps interaction fast.
N = 1_000_000
GRID_W, GRID_H = 512, 384
N_BUCKETS = 2048
DRILL_N = 600_000


@pytest.fixture(scope="session", autouse=True)
def require_native_backend() -> None:
    assert k.BACKEND == "native", (
        "CodSpeed benchmarks must run against the native Rust backend; "
        f"got {k.BACKEND!r}. Build the native core before running them."
    )


@pytest.fixture(scope="module")
def data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    x = np.arange(N, dtype=np.float64)
    y = rng.normal(0.0, 1.0, N)
    return x, y


@pytest.fixture(scope="module")
def drilldown_figure() -> Figure:
    rng = np.random.default_rng(17)
    x = rng.uniform(0.0, 100.0, DRILL_N).astype(np.float64, copy=False)
    y = rng.uniform(0.0, 100.0, DRILL_N).astype(np.float64, copy=False)
    fig = Figure()
    fig.scatter(x, y, density=True)

    # Warm the lazily-built pyramid so CodSpeed tracks interactive viewport
    # refresh cost, not one-time index construction.
    fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)
    fig.density_view(0, 0.0, 10.0, 0.0, 10.0, GRID_W, GRID_H)
    fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)
    return fig


def test_zone_maps(benchmark, data):
    x, _ = data
    benchmark(k.zone_maps, x)


def test_encode_f32(benchmark, data):
    _, y = data
    benchmark(k.encode_f32, y, 0.0, 1.0)


def test_m4_indices_full(benchmark, data):
    """M4 decimation over the full range (§5 Tier 1) - the first-paint cost."""
    x, y = data
    benchmark(k.m4_indices, x, y, 0.0, float(N), N_BUCKETS)


def test_m4_indices_zoom(benchmark, data):
    """Re-decimation of a 1% zoom window (§17 interaction budget)."""
    x, y = data
    x0, x1 = N * 0.495, N * 0.505
    benchmark(k.m4_indices, x, y, x0, x1, N_BUCKETS)


def test_bin_2d(benchmark, data):
    """Tier-2 scatter density aggregation (§5) onto a screen-sized grid."""
    x, y = data
    benchmark(k.bin_2d, x, y, 0.0, float(N), -6.0, 6.0, GRID_W, GRID_H)


def test_histogram_uniform(benchmark, data):
    _, y = data
    benchmark(k.histogram_uniform, y, -6.0, 6.0, 512)


def test_normalize_f32(benchmark, data):
    _, y = data
    benchmark(k.normalize_f32, y, (-6.0, 6.0))


def test_range_indices(benchmark, data):
    """Rectangular selection/viewport scan used by drilldown."""
    x, y = data
    benchmark(k.range_indices, x, y, N * 0.45, N * 0.55, -2.0, 2.0)


def test_build_payload(benchmark, data):
    """End-to-end: figure build -> binary columnar payload on the wire."""
    x, y = data

    def build():
        fig = Figure()
        fig.line(x, y)
        return fig.build_payload(N_BUCKETS)

    benchmark(build)


def test_decimate_view(benchmark, data):
    """Zoom interaction: kernel-side re-decimation of a 1% window."""
    x, y = data
    fig = Figure()
    fig.line(x, y)
    x0, x1 = N * 0.495, N * 0.505
    benchmark(fig.decimate_view, x0, x1, N_BUCKETS)


def _adaptive_drilldown_cycle(fig: Figure) -> int:
    wide, wide_buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)
    deep, deep_buffers = fig.density_view(0, 0.0, 10.0, 0.0, 10.0, GRID_W, GRID_H)
    back, back_buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)

    wide_trace = wide["traces"][0]
    deep_trace = deep["traces"][0]
    back_trace = back["traces"][0]
    assert wide_trace["mode"] == "density"
    assert deep_trace["mode"] == "points"
    assert back_trace["mode"] == "density"
    assert 0 < deep_trace["visible"] < wide_trace["visible"]
    return (
        int(wide_trace["visible"])
        + int(deep_trace["visible"])
        + int(back_trace["visible"])
        + sum(len(buffer) for buffer in wide_buffers + deep_buffers + back_buffers)
    )


def test_adaptive_drilldown_cycle(benchmark, drilldown_figure):
    """Adaptive scatter: density overview -> exact visible points -> density out."""
    result = benchmark(_adaptive_drilldown_cycle, drilldown_figure)
    assert result > DRILL_N
