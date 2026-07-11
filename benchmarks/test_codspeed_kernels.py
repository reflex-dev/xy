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
EXPORT_N = 100_000
APPEND_N = 100_000
APPEND_BATCH = 1_000
STACK_ROWS = 8
STACK_COLS = 100_000


@pytest.fixture(scope="session", autouse=True)
def require_native_backend() -> None:
    assert k.BACKEND == "native", (
        "CodSpeed benchmarks must run against the native Rust backend; "
        f"got {k.BACKEND!r}. Build the native core before running them."
    )


@pytest.fixture(scope="session", autouse=True)
def warm_lazy_modules() -> None:
    """Pull xy's lazily-imported submodules in before any measured region.

    CodSpeed simulation measures each benchmark as a one-shot region, and CI
    runs from a fresh checkout with no __pycache__. xy defers importing its
    heavy submodules (marks, components, _payload, the export stack) until the
    first figure build, so without this warmup the first figure-building
    benchmark pays CPython source->bytecode compilation and module exec for
    whatever those files have grown to — its number then tracks package source
    size, not its own workload (a ~26% phantom regression on scatter_small when
    the plot families landed).
    """
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    fig = fc.chart(fc.scatter(x=x, y=y), fc.line(x=x, y=y)).figure()
    fig.build_payload(N_BUCKETS)
    fig.to_svg(width=64, height=48)
    fig.to_png(engine="native", scale=1.0)
    fig.to_html()


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
def export_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(23)
    x = np.arange(EXPORT_N, dtype=np.float64)
    y = (np.sin(x * 0.001) + rng.normal(0.0, 0.08, EXPORT_N)).astype(np.float64, copy=False)
    return x, y


@pytest.fixture(scope="module")
def append_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = np.arange(APPEND_N, dtype=np.float64)
    y = np.sin(x * 0.001)
    tail_x = np.arange(APPEND_N, APPEND_N + APPEND_BATCH, dtype=np.float64)
    tail_y = np.sin(tail_x * 0.001)
    return x, y, tail_x, tail_y


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
def compatibility_kernel_data() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(101)
    stacked = rng.uniform(0.0, 10.0, size=(STACK_ROWS, STACK_COLS))
    x = rng.normal(size=N)
    y = 0.4 * x + rng.normal(size=N)
    weights = rng.uniform(0.1, 2.0, size=N)
    x_edges = np.quantile(x, np.linspace(0.0, 1.0, 257))
    y_edges = np.quantile(y, np.linspace(0.0, 1.0, 193))
    stream_x = np.linspace(-2.0, 2.0, 128)
    stream_y = np.linspace(-2.0, 2.0, 96)
    stream_xx, stream_yy = np.meshgrid(stream_x, stream_y)
    mesh_x, mesh_y = np.meshgrid(np.linspace(-3.0, 3.0, 321), np.linspace(-2.0, 2.0, 257))
    mesh_x += 0.08 * np.sin(mesh_y * 2.0)
    mesh_y += 0.05 * np.cos(mesh_x * 1.5)
    mesh_z = np.sin(mesh_x[:-1, :-1]) * np.cos(mesh_y[:-1, :-1])
    tri_x = rng.uniform(-1.0, 1.0, size=512)
    tri_y = rng.uniform(-1.0, 1.0, size=512)
    tri_topology = k.delaunay_triangles(tri_x, tri_y)
    spectral_time = np.arange(65_536, dtype=np.float64) / 4096.0
    spectral_x = np.sin(2.0 * np.pi * 127.0 * spectral_time) + 0.08 * rng.normal(
        size=len(spectral_time)
    )
    spectral_y = np.sin(2.0 * np.pi * 127.0 * spectral_time + 0.35)
    return {
        "stacked": stacked,
        "x": x,
        "y": y,
        "weights": weights,
        "x_edges": x_edges,
        "y_edges": y_edges,
        "stream_x": stream_x,
        "stream_y": stream_y,
        "stream_u": -stream_yy,
        "stream_v": stream_xx,
        "mesh_x": mesh_x,
        "mesh_y": mesh_y,
        "mesh_z": mesh_z,
        "tri_x": tri_x,
        "tri_y": tri_y,
        "tri_z": np.sin(tri_x * 4.0) + np.cos(tri_y * 3.0),
        "tri_topology": tri_topology,
        "spectral_x": spectral_x,
        "spectral_y": spectral_y,
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


def test_stacked_bounds_weighted_wiggle(benchmark, compatibility_kernel_data):
    """Native stacked-area layout; no Python cumulative allocation."""
    lower, upper = benchmark(
        k.stacked_bounds, compatibility_kernel_data["stacked"], "weighted_wiggle"
    )
    assert lower.shape == upper.shape == (STACK_ROWS, STACK_COLS)


def test_histogram2d_weighted_arbitrary_edges(benchmark, compatibility_kernel_data):
    """Native irregular-bin weighted 2-D histogram compatibility path."""
    grid = benchmark(
        k.histogram2d,
        compatibility_kernel_data["x"],
        compatibility_kernel_data["y"],
        compatibility_kernel_data["x_edges"],
        compatibility_kernel_data["y_edges"],
        compatibility_kernel_data["weights"],
    )
    assert grid.shape == (256, 192)


def test_weighted_ecdf_native(benchmark, compatibility_kernel_data):
    """Million-row weighted sort and aggregation never falls back to NumPy."""
    values, cumulative = benchmark(
        k.weighted_ecdf,
        compatibility_kernel_data["x"],
        compatibility_kernel_data["weights"],
    )
    assert len(values) == len(cumulative) == N
    assert cumulative[-1] == pytest.approx(1.0)


def test_quad_mesh_triangle_expansion(benchmark, compatibility_kernel_data):
    """Native warped-quad expansion feeds the generic triangle renderer."""
    triangles = benchmark(
        k.quad_mesh_triangles,
        compatibility_kernel_data["mesh_x"],
        compatibility_kernel_data["mesh_y"],
        compatibility_kernel_data["mesh_z"],
    )
    assert len(triangles[0]) == 2 * 256 * 320


def test_delaunay_unstructured_topology(benchmark, compatibility_kernel_data):
    """Native dependency-free topology construction for triangular plots."""
    topology = benchmark(
        k.delaunay_triangles,
        compatibility_kernel_data["tri_x"],
        compatibility_kernel_data["tri_y"],
    )
    assert len(topology) > 0


def test_indexed_triangle_expansion(benchmark, compatibility_kernel_data):
    """Indexed unstructured faces expand without Python advanced indexing."""
    mesh = benchmark(
        k.indexed_triangles,
        compatibility_kernel_data["tri_x"],
        compatibility_kernel_data["tri_y"],
        compatibility_kernel_data["tri_topology"],
        compatibility_kernel_data["tri_z"],
        values_at="vertex",
    )
    assert len(mesh[0]) == len(compatibility_kernel_data["tri_topology"])


def test_sector_triangle_tessellation(benchmark):
    """Pie/donut sector geometry is tessellated in the native core."""
    values = np.arange(1.0, 25.0)
    mesh = benchmark(k.sector_triangles, values, inner_radius=0.55, start_degrees=90.0)
    assert len(mesh[0]) > 0


def test_streamlines_regular_grid(benchmark, compatibility_kernel_data):
    """Bounded native streamline integration for scientific vector fields."""
    segments = benchmark(
        k.streamlines,
        compatibility_kernel_data["stream_x"],
        compatibility_kernel_data["stream_y"],
        compatibility_kernel_data["stream_u"],
        compatibility_kernel_data["stream_v"],
        density=1.0,
        max_steps=1024,
    )
    assert len(segments[0]) > 0


def test_rfft_arbitrary_length_native(benchmark, compatibility_kernel_data):
    """Bluestein FFT keeps non-power-of-two spectral work in Rust."""
    result = benchmark(
        k.rfft,
        compatibility_kernel_data["spectral_x"][:60_000],
        nfft=60_000,
        sample_rate=4096.0,
    )
    assert len(result[0]) == 30_001


def test_welch_spectra_native(benchmark, compatibility_kernel_data):
    """Windowing, FFTs, and spectral accumulation execute in one native call."""
    result = benchmark(
        k.welch_spectra,
        compatibility_kernel_data["spectral_x"],
        compatibility_kernel_data["spectral_y"],
        nfft=1024,
        noverlap=512,
        sample_rate=4096.0,
    )
    assert len(result[0]) == 513


def test_spectrogram_native(benchmark, compatibility_kernel_data):
    result = benchmark(
        k.spectrogram,
        compatibility_kernel_data["spectral_x"],
        nfft=1024,
        noverlap=768,
        sample_rate=4096.0,
    )
    assert result[0].shape[1] == 513


def test_correlation_native(benchmark, compatibility_kernel_data):
    result = benchmark(
        k.correlation,
        compatibility_kernel_data["spectral_x"],
        compatibility_kernel_data["spectral_y"],
        max_lags=2048,
        normalize=True,
    )
    assert len(result[0]) == 4097


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


def _statistical_payload(values: list[np.ndarray]) -> int:
    fig = fc.chart(
        fc.box(values=values, name="box"),
        fc.violin(values=values, bins=64, name="violin"),
    ).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _hexbin_payload(x: np.ndarray, y: np.ndarray) -> int:
    fig = fc.chart(fc.hexbin(x=x, y=y, gridsize=128)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _contour_payload(z: np.ndarray) -> int:
    fig = fc.chart(fc.contour(z=z, levels=12, filled=True)).figure()
    _spec, blob = fig.build_payload(N_BUCKETS)
    return len(blob)


def _errorbar_payload(x: np.ndarray, y: np.ndarray) -> int:
    fig = fc.chart(fc.errorbar(x=x, y=y, yerr=1.0)).figure()
    spec, blob = fig.build_payload(N_BUCKETS)
    # The point of this bench is the segment-emission decimation branch.
    assert spec["traces"][0]["tier"] == "decimated"
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


def test_first_payload_scatter_categorical_color(benchmark, medium_data):
    """Categorical palette factorization and code shipping for scatter."""
    x, y = medium_data
    categories = np.array([f"group-{i % 24:02d}" for i in range(len(x))])

    def build():
        fig = fc.chart(fc.scatter(x=x, y=y, color=categories)).figure()
        return fig.build_payload(N_BUCKETS)

    spec, blob = benchmark(build)
    assert spec["traces"][0]["n_points"] == len(x)
    assert blob


def test_first_payload_scatter_continuous_channels(benchmark, medium_data):
    """Continuous color and size channels through the direct payload path."""
    x, y = medium_data
    color = np.sin(x * 0.0007)
    size = 4.0 + 3.0 * np.abs(np.cos(x * 0.0003))

    def build():
        fig = fc.chart(fc.scatter(x=x, y=y, color=color, size=size)).figure()
        return fig.build_payload(N_BUCKETS)

    spec, blob = benchmark(build)
    assert spec["traces"][0]["n_points"] == len(x)
    assert blob


def test_first_payload_line_unsorted_x(benchmark, medium_data):
    """Large line ingestion through the sort-and-reingest branch."""
    x, y = medium_data
    shuffled = np.random.default_rng(47).permutation(len(x))
    unsorted_x = x[shuffled]
    unsorted_y = y[shuffled]

    def build():
        fig = fc.chart(fc.line(x=unsorted_x, y=unsorted_y)).figure()
        return fig.build_payload(N_BUCKETS)

    spec, blob = benchmark(build)
    assert spec["traces"][0]["n_points"] == len(x)
    assert blob


@pytest.mark.parametrize("kind", ["datetime64", "python_list"])
def test_first_payload_ingest_flavors(benchmark, kind):
    """Non-contiguous public input forms must retain their ingestion paths."""
    n = 100_000
    values = np.sin(np.arange(n, dtype=np.float64) * 0.001)
    if kind == "datetime64":
        x = np.datetime64("2026-01-01T00:00:00", "ms") + np.arange(n).astype("timedelta64[ms]")
    else:
        x = np.arange(n, dtype=np.float64).tolist()

    def build():
        fig = fc.chart(fc.line(x=x, y=values)).figure()
        return fig.build_payload(N_BUCKETS)

    spec, blob = benchmark(build)
    assert spec["traces"][0]["n_points"] == n
    assert blob


def test_density_view_exact_pan(benchmark):
    """Steady-state exact pan below the pyramid activation threshold."""
    n = 200_000
    rng = np.random.default_rng(53)
    x = rng.uniform(0.0, 100.0, n).astype(np.float64, copy=False)
    y = rng.uniform(-2.0, 2.0, n).astype(np.float64, copy=False)
    fig = fc.chart(fc.scatter(x=x, y=y, density=True)).figure()
    fig.density_view(0, 0.0, 100.0, -2.0, 2.0, GRID_W, GRID_H)

    def pan():
        return fig.density_view(0, 10.0, 90.0, -1.5, 1.5, GRID_W, GRID_H)

    update, buffers = benchmark(pan)
    assert update["traces"][0]["mode"] in {"density", "points"}
    assert buffers


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


def test_first_payload_statistical_core_2d(benchmark, medium_data):
    """Distribution summaries reduce raw observations to compact geometry."""
    _x, y = medium_data
    values = [y, y + 0.75]
    payload_bytes = benchmark(_statistical_payload, values)
    assert payload_bytes > 0


def test_first_payload_hexbin_core_2d(benchmark, medium_data):
    """Hexbin scans source points through the native screen-sized bin kernel."""
    x, y = medium_data
    payload_bytes = benchmark(_hexbin_payload, x, y)
    assert 0 < payload_bytes < x.nbytes + y.nbytes


def test_first_payload_errorbar_large(benchmark, data):
    """Large error bars ship per-point decimated segment groups, not 3N marks."""
    x, y = data
    payload_bytes = benchmark(_errorbar_payload, x, y)
    assert 0 < payload_bytes < x.nbytes + y.nbytes


def test_first_payload_contour_core_2d(benchmark, core_2d_data):
    """Contour extraction is bounded by the regular input grid, not source rows."""
    z = core_2d_data["heatmap_z"]
    assert isinstance(z, np.ndarray)
    payload_bytes = benchmark(_contour_payload, z)
    assert payload_bytes > 0


# Grouped with the other plot-family benchmarks (not next to bin_2d): the
# pre-existing suite must keep its fixture materialization order — CodSpeed
# measures one-shot regions, so pulling the module-scoped core_2d_data fixture
# forward changes process state under the first figure build and breaks
# baseline comparability for the untouched benchmarks.
def test_marching_squares(benchmark, core_2d_data):
    """Regular-grid isolines over a bounded contour workload."""
    z = core_2d_data["heatmap_z"]
    x = core_2d_data["heatmap_x"]
    y = core_2d_data["heatmap_y"]
    levels = np.linspace(float(z.min()), float(z.max()), 11, dtype=np.float64)[1:-1]
    result = benchmark(k.marching_squares, z, x, y, levels)
    assert len(result) == 5


def test_native_png_export_scatter(benchmark, export_data):
    """Native raster export after screen-bounded payload preparation."""
    x, y = export_data
    fig = fc.chart(fc.scatter(x=x, y=y)).figure()
    png = benchmark(fig.to_png, engine="native", scale=1.0)
    assert png.startswith(b"\x89PNG")


def test_svg_export_line(benchmark, export_data):
    """Static SVG export shares decimation but exercises XML serialization."""
    x, y = export_data
    fig = fc.chart(fc.line(x=x, y=y)).figure()
    svg = benchmark(fig.to_svg, width=720, height=420)
    assert svg.startswith("<svg")


def test_html_export_line(benchmark, export_data):
    """Standalone HTML export, including embedded spec and buffers."""
    x, y = export_data
    fig = fc.chart(fc.line(x=x, y=y)).figure()
    html = benchmark(fig.to_html)
    assert "<html" in html.lower()


def test_stream_line_append(benchmark, append_data):
    """Append refresh cost for a warmed 100k-row line chart."""
    x, y, tail_x, tail_y = append_data
    fig = fc.chart(fc.line(x=x, y=y)).figure()
    fig.build_payload(N_BUCKETS)

    def append_next():
        # CodSpeed invokes the target repeatedly; advance the x origin so each
        # iteration remains a valid continuation of the line.
        start = float(fig.traces[0].n_points)
        next_x = start + (tail_x - tail_x[0])
        next_y = np.sin(next_x * 0.001)
        return fig.append(0, next_x, next_y)

    update, buffers = benchmark(append_next)
    assert update["spec"]["traces"][0]["n_points"] >= APPEND_N + APPEND_BATCH
    assert buffers


def test_stream_density_append_then_rebuild(benchmark, pyramid_data):
    """Append invalidation plus warm pyramid rebuild for dense scatter."""
    x, y = pyramid_data
    fig = fc.chart(fc.scatter(x=x, y=y, density=True)).figure()
    fig.build_payload(N_BUCKETS)
    tail_x = np.full(APPEND_BATCH, 50.0, dtype=np.float64)
    tail_y = np.linspace(45.0, 55.0, APPEND_BATCH, dtype=np.float64)

    def append_and_rebuild():
        fig.append(0, tail_x, tail_y)
        return fig.density_view(0, 0.0, 100.0, 0.0, 100.0, GRID_W, GRID_H)

    update, buffers = benchmark(append_and_rebuild)
    assert update["traces"][0]["mode"] == "density"
    assert buffers


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


def test_stratified_sample_mask(benchmark):
    """ABI-v10 category-stratified sampler used by density overlays."""
    n = 1_000_000
    ids = np.arange(n, dtype=np.uint64)
    groups = (np.arange(n, dtype=np.uint32) % 12).astype(np.uint32, copy=False)
    mask = benchmark(k.stratified_sample_mask, ids, groups, 12, 17, 1.0 / 256.0, 2)
    assert mask.dtype == np.bool_
    assert mask.shape == (n,)


@pytest.mark.parametrize(
    ("n", "w", "h"),
    [(100_000, 512, 384), (1_000_000, 512, 384), (1_000_000, 2048, 2048)],
)
def test_bin_2d_thread_cap_scaling(benchmark, n, w, h):
    """Exercise sparse, screen-sized, and cell-heavy fan-out regimes."""
    rng = np.random.default_rng(101 + n + w + h)
    x = rng.uniform(0.0, 100.0, n).astype(np.float64, copy=False)
    y = rng.uniform(0.0, 100.0, n).astype(np.float64, copy=False)
    grid = benchmark(k.bin_2d, x, y, 0.0, 100.0, 0.0, 100.0, w, h)
    assert grid.shape == (h, w)
