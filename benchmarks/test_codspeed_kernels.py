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
