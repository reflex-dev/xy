"""CodSpeed benchmarks for the xy native compute core.

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

import xy as fc
from xy import kernels as k
from xy._figure import Figure  # harness type annotations only

# Small/medium/large sizes keep CodSpeed honest across normal dashboard charts,
# exact WebGL workloads, and screen-bounded large-data paths without turning it
# into the full cross-library benchmark suite.
SMALL_N = 10_000
MEDIUM_N = 100_000
N = LARGE_N = 1_000_000
GRID_W, GRID_H = 512, 384
N_BUCKETS = 2048
PYRAMID_N = 2_100_000
DRILL_N = PYRAMID_N
HIST_N = 100_000
AREA_N = 100_000
BAR_N = 1_000
HEATMAP_W, HEATMAP_H = 160, 120


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
def small_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    x = np.arange(SMALL_N, dtype=np.float64)
    y = rng.normal(0.0, 1.0, SMALL_N)
    return x, y


@pytest.fixture(scope="module")
def medium_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(11)
    x = np.arange(MEDIUM_N, dtype=np.float64)
    y = rng.normal(0.0, 1.0, MEDIUM_N)
    return x, y


@pytest.fixture(scope="module")
def pyramid_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(19)
    x = rng.uniform(0.0, 100.0, PYRAMID_N).astype(np.float64, copy=False)
    y = rng.uniform(0.0, 100.0, PYRAMID_N).astype(np.float64, copy=False)
    return x, y


@pytest.fixture(scope="module")
def pyramid_handle(pyramid_data):
    x, y = pyramid_data
    handle = k.pyramid_build(x, y, 0.0, 100.0, 0.0, 100.0, 2048)
    assert handle
    yield handle
    assert k.pyramid_free(handle)


@pytest.fixture(scope="module")
def core_2d_data() -> dict[str, object]:
    rng = np.random.default_rng(31)
    hist_values = np.concatenate(
        [
            rng.normal(-1.1, 0.52, HIST_N // 2),
            rng.normal(1.35, 0.68, HIST_N - HIST_N // 2),
        ]
    ).astype(np.float64, copy=False)
    categories = [f"C{i:04d}" for i in range(BAR_N)]
    bar_values = (
        42.0 + 18.0 * np.sin(np.linspace(0.0, 18.0, BAR_N)) + rng.normal(0.0, 3.0, BAR_N)
    ).astype(np.float64, copy=False)
    target_values = (
        46.0 + 12.0 * np.cos(np.linspace(0.0, 14.0, BAR_N)) + rng.normal(0.0, 1.5, BAR_N)
    ).astype(np.float64, copy=False)
    sample_values = (0.62 * bar_values + 0.38 * target_values).astype(np.float64, copy=False)
    area_x = np.arange(AREA_N, dtype=np.float64)
    area_y = (
        35.0
        + 4.0 * np.sin(np.linspace(0.0, 18.0, AREA_N))
        + np.cumsum(rng.normal(0.0, 0.018, AREA_N))
    ).astype(np.float64, copy=False)
    hx = np.linspace(-3.0, 3.0, HEATMAP_W, dtype=np.float64)
    hy = np.linspace(-2.4, 2.4, HEATMAP_H, dtype=np.float64)
    xx, yy = np.meshgrid(hx, hy)
    heatmap = (
        np.exp(-((xx - 0.85) ** 2 + (yy + 0.3) ** 2))
        + 0.72 * np.exp(-((xx + 1.2) ** 2 + (yy - 0.65) ** 2) / 0.52)
    ).astype(np.float64, copy=False)
    return {
        "hist_values": hist_values,
        "area_x": area_x,
        "area_y": area_y,
        "bar_categories": categories,
        "bar_values": bar_values,
        "composed_data": {
            "category": categories,
            "actual": bar_values,
            "target": target_values,
            "sample": sample_values,
        },
        "heatmap_x": hx,
        "heatmap_y": hy,
        "heatmap_z": heatmap,
    }


@pytest.fixture(scope="module")
def drilldown_figure() -> Figure:
    rng = np.random.default_rng(17)
    x = rng.uniform(0.0, 100.0, DRILL_N).astype(np.float64, copy=False)
    y = rng.uniform(0.0, 100.0, DRILL_N).astype(np.float64, copy=False)
    fig = fc.chart(fc.scatter(x=x, y=y, density=True)).figure()
    fig._benchmark_deep_expected = int(np.count_nonzero((x < 10.0) & (y < 10.0)))

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


def test_bin_2d_indices(benchmark, data):
    """Production first-density pass: grid plus visible indices in one scan."""
    x, y = data
    grid, indices = benchmark(k.bin_2d_indices, x, y, 0.0, float(N), -6.0, 6.0, GRID_W, GRID_H)
    assert grid.size == GRID_W * GRID_H
    assert len(indices) == N


def test_min_max(benchmark, data):
    """Autorange and channel-domain scan used by every numeric chart."""
    _, y = data
    assert benchmark(k.min_max, y) is not None


def test_sample_mask(benchmark, data):
    """Deterministic density-overlay sampling over stable row ids."""
    x, _ = data
    row_ids = np.arange(len(x), dtype=np.uint64)
    mask = benchmark(k.sample_mask, row_ids, 0, np.iinfo(np.uint64).max // 100)
    assert mask.dtype == np.bool_


def test_pyramid_build(benchmark, pyramid_data):
    """Cold Tier-3 index construction at the real activation threshold."""
    x, y = pyramid_data

    def build_and_free() -> int:
        handle = k.pyramid_build(x, y, 0.0, 100.0, 0.0, 100.0, 2048)
        assert handle
        assert k.pyramid_free(handle)
        return handle

    assert benchmark(build_and_free)


def test_pyramid_count(benchmark, pyramid_handle):
    """Warm viewport cardinality estimate used before every pyramid compose."""
    count = benchmark(k.pyramid_count, pyramid_handle, 10.0, 90.0, 10.0, 90.0)
    assert count is not None and count > 0


def test_pyramid_compose(benchmark, pyramid_handle):
    """Warm screen-sized density composition without rescanning source rows."""
    result = benchmark(k.pyramid_compose, pyramid_handle, 10.0, 90.0, 10.0, 90.0, GRID_W, GRID_H)
    assert result is not None


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


def _scatter_payload(x: np.ndarray, y: np.ndarray, *, density: bool | None = None) -> int:
    fig = fc.chart(fc.scatter(x=x, y=y, density=density)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _line_payload(x: np.ndarray, y: np.ndarray) -> int:
    fig = fc.chart(fc.line(x=x, y=y)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _density_memory_report(x: np.ndarray, y: np.ndarray) -> dict[str, object]:
    fig = fc.chart(fc.scatter(x=x, y=y, density=True)).figure()
    return fig.memory_report()


def _histogram_payload(values: np.ndarray) -> int:
    fig = fc.chart(fc.histogram(values, bins=200)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _area_payload(x: np.ndarray, y: np.ndarray) -> int:
    fig = fc.chart(fc.area(x, y)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _bar_payload(categories: list[str], values: np.ndarray) -> int:
    fig = fc.chart(fc.bar(categories, values)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _heatmap_payload(z: np.ndarray, x: np.ndarray, y: np.ndarray) -> int:
    fig = fc.chart(fc.heatmap(z, x=x, y=y)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _composed_layered_payload(data: dict[str, object]) -> int:
    chart = fc.chart(
        fc.bar(x="category", y="actual", data=data, name="actual", color="#f59e0b"),
        fc.scatter(x="category", y="sample", data=data, name="sample", color="#2563eb", size=8),
        fc.line(x="category", y="target", data=data, name="target", color="#dc2626", width=2),
        fc.x_band("C0200", "C0400", text="campaign", color="#7c3aed", opacity=0.12),
        fc.vline("C0500", text="release", color="#7c3aed"),
        fc.x_axis(label="category", tick_label_strategy="auto", tick_label_min_gap=28),
        fc.y_axis(label="pipeline"),
        fc.tooltip(
            fields=["category", "actual", "sample", "target"],
            title="{category}",
            format={"actual": ".1f", "sample": ".1f", "target": ".1f"},
        ),
        fc.legend(),
        title="CodSpeed layered core 2D",
        width=720,
        height=420,
        class_name="fc-chart",
        class_names={"legend": "fc-legend", "tooltip": "fc-tooltip"},
        style={"--fc-accent": "#2563eb"},
    )
    _spec, blob = chart.figure().build_payload(N_BUCKETS)
    return len(blob)


def _composed_layered_memory_report(data: dict[str, object]) -> dict[str, object]:
    chart = fc.chart(
        fc.bar(x="category", y="actual", data=data, name="actual", color="#f59e0b"),
        fc.scatter(x="category", y="sample", data=data, name="sample", color="#2563eb", size=8),
        fc.line(x="category", y="target", data=data, name="target", color="#dc2626", width=2),
        fc.x_axis(label="category", tick_label_strategy="auto", tick_label_min_gap=28),
        fc.y_axis(label="pipeline"),
        fc.tooltip(fields=["category", "actual", "sample", "target"]),
        fc.legend(),
        title="CodSpeed layered core 2D memory",
    )
    return chart.memory_report()


def test_first_payload_scatter_small(benchmark, small_data):
    """Small-data first payload: everyday exact scatter startup."""
    x, y = small_data
    payload_bytes = benchmark(_scatter_payload, x, y)
    assert payload_bytes > 0


def test_first_payload_scatter_medium(benchmark, medium_data):
    """Medium exact scatter first payload before aggregation is needed."""
    x, y = medium_data
    payload_bytes = benchmark(_scatter_payload, x, y)
    assert payload_bytes > 0


def test_first_payload_line_large(benchmark, data):
    """Large line first payload, including M4 decimation and binary transport."""
    x, y = data
    payload_bytes = benchmark(_line_payload, x, y)
    assert 0 < payload_bytes < x.nbytes + y.nbytes


def test_first_payload_density_large(benchmark, data):
    """Large scatter overview first payload through the density tier."""
    x, y = data
    payload_bytes = benchmark(_scatter_payload, x, y, density=True)
    assert 0 < payload_bytes < x.nbytes + y.nbytes


def test_memory_report_density_medium(benchmark, medium_data):
    """Memory/payload accounting path for screen-bounded density charts."""
    x, y = medium_data
    report = benchmark(_density_memory_report, x, y)
    assert report["backend"] == "native"
    assert report["transport_bytes_first_paint"] > 0
    assert report["transport_bytes_per_point"] > 0


def test_first_payload_histogram_core_2d(benchmark, core_2d_data):
    """Core 2D payload prep: histogram binning plus rectangle transport."""
    values = core_2d_data["hist_values"]
    assert isinstance(values, np.ndarray)
    payload_bytes = benchmark(_histogram_payload, values)
    assert 0 < payload_bytes < values.nbytes


def test_first_payload_area_core_2d(benchmark, core_2d_data):
    """Core 2D payload prep: filled area series and binary transport."""
    x = core_2d_data["area_x"]
    y = core_2d_data["area_y"]
    assert isinstance(x, np.ndarray)
    assert isinstance(y, np.ndarray)
    payload_bytes = benchmark(_area_payload, x, y)
    assert 0 < payload_bytes < x.nbytes + y.nbytes


def test_first_payload_bar_core_2d(benchmark, core_2d_data):
    """Core 2D payload prep: categorical rectangles and category axis metadata."""
    categories = core_2d_data["bar_categories"]
    values = core_2d_data["bar_values"]
    assert isinstance(categories, list)
    assert isinstance(values, np.ndarray)
    payload_bytes = benchmark(_bar_payload, categories, values)
    assert 0 < payload_bytes < values.nbytes * 2


def test_first_payload_heatmap_core_2d(benchmark, core_2d_data):
    """Core 2D payload prep: dense cell grid normalization and binary transport."""
    z = core_2d_data["heatmap_z"]
    x = core_2d_data["heatmap_x"]
    y = core_2d_data["heatmap_y"]
    assert isinstance(z, np.ndarray)
    assert isinstance(x, np.ndarray)
    assert isinstance(y, np.ndarray)
    payload_bytes = benchmark(_heatmap_payload, z, x, y)
    assert 0 < payload_bytes < z.nbytes


def test_first_payload_composed_layered_core_2d(benchmark, core_2d_data):
    """Core 2D payload prep through the public declarative layered API."""
    data = core_2d_data["composed_data"]
    assert isinstance(data, dict)
    payload_bytes = benchmark(_composed_layered_payload, data)
    assert payload_bytes > 0


def test_memory_report_composed_layered_core_2d(benchmark, core_2d_data):
    """Core 2D memory accounting through the public declarative layered API."""
    data = core_2d_data["composed_data"]
    assert isinstance(data, dict)
    report = benchmark(_composed_layered_memory_report, data)
    assert report["backend"] == "native"
    assert report["canonical_bytes"] > 0
    assert len(report["columns"]) >= 6
    assert report["transport_bytes_first_paint"] > 0


def test_build_payload(benchmark, data):
    """End-to-end: figure build -> binary columnar payload on the wire."""
    x, y = data

    def build():
        fig = fc.chart(fc.line(x=x, y=y)).figure()
        return fig.build_payload(N_BUCKETS)

    benchmark(build)


def test_decimate_view(benchmark, data):
    """Zoom interaction: kernel-side re-decimation of a 1% window."""
    x, y = data
    fig = fc.chart(fc.line(x=x, y=y)).figure()
    x0, x1 = N * 0.495, N * 0.505
    benchmark(fig.decimate_view, x0, x1, N_BUCKETS)


def _adaptive_drilldown_cycle(fig: Figure) -> int:
    wide, wide_buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)
    deep, deep_buffers = fig.density_view(0, 0.0, 10.0, 0.0, 10.0, GRID_W, GRID_H)

    wide_trace = wide["traces"][0]
    deep_trace = deep["traces"][0]
    assert wide_trace["mode"] == "density"
    assert deep_trace["mode"] == "points"
    assert str(wide_trace.get("binning", "")).startswith("pyramid-L")
    assert deep_trace["visible"] == fig._benchmark_deep_expected
    drill_seq = deep_trace["drill_seq"]
    row = fig.pick(0, 0, drill_seq)
    assert row is not None
    canonical_index = int(fig.traces[0].shipped_sel[0])
    assert row["index"] == canonical_index
    assert row["x"] == float(fig.traces[0].x.values[canonical_index])
    assert row["y"] == float(fig.traces[0].y.values[canonical_index])

    back, back_buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)
    back_trace = back["traces"][0]
    assert back_trace["mode"] == "density"
    assert str(back_trace.get("binning", "")).startswith("pyramid-L")
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
