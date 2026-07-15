"""CodSpeed benchmarks for ``xy.pyplot`` shim overhead versus the raw API.

Every workload here is one chart expressed twice over the same input arrays
and ending in the same terminal work: once through the public declarative API
(``xy.chart`` + marks) and once through the identical Matplotlib-style calls
in ``xy.pyplot``. Both arms finish at the engine's split wire payload (or PNG
bytes for the export pair), so the gap between a ``*_pyplot`` row and its
``*_raw`` twin is exactly what the shim adds — Matplotlib-call translation,
fmt-string parsing, and figure-lifecycle bookkeeping. Everything below the
shim is shared engine work and moves both rows together.

``tests/pyplot/test_perf_guardrail.py`` remains the hard relative gate on
this promise; these rows track it continuously so a structural regression in
the shim (an O(n) copy, per-build revalidation) shows up attributed to the
``*_pyplot`` arm instead of surfacing as an unexplained engine slowdown.

Run locally with:

    codspeed run --mode simulation -- pytest benchmarks/test_codspeed_pyplot.py --codspeed
"""

from __future__ import annotations

import io

import numpy as np
import pytest

import xy as fc
import xy.pyplot as plt
from xy import kernels as k

N_BUCKETS = 2048
# plt.subplots() defaults to 6.4 x 4.8 inches at dpi=100; the raw arm pins the
# same 640x480 canvas so chrome layout work is identical on both sides.
WIDTH, HEIGHT = 640, 480
SMALL_N = 10_000
MEDIUM_N = 100_000
LARGE_N = 1_000_000
HIST_N = 100_000
HIST_BINS = 200
BAR_N = 1_000
PANEL_N = 5_000
EXPORT_N = 100_000


@pytest.fixture(scope="session", autouse=True)
def require_native_backend() -> None:
    assert k.BACKEND == "native", (
        "CodSpeed benchmarks must run against the native Rust backend; "
        f"got {k.BACKEND!r}. Build the native core before running them."
    )


@pytest.fixture(scope="session", autouse=True)
def warm_lazy_modules() -> None:
    """Warm both arms' lazily-imported submodules before any measured region.

    CodSpeed simulation measures one-shot regions from a fresh checkout, and
    both xy and the pyplot shim defer heavy imports (marks, _payload, the
    export stack, the shim's translation tables) until first use. Without
    this, the first benchmark of each arm would track package source size
    instead of its own workload — exactly the phantom regression documented
    in test_codspeed_kernels.py.
    """
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    raw = fc.chart(fc.line(x=x, y=y), fc.x_axis(), fc.y_axis()).figure()
    raw.build_payload_split(N_BUCKETS)
    raw_fig = fc.chart(fc.line(x=x, y=y)).figure()
    raw_fig.to_png(engine=fc.Engine.default, scale=1.0)

    plt.close("all")
    fig, ax = plt.subplots()
    ax.plot(x, y, "r--", label="warm")
    ax.legend()
    ax._build_chart(WIDTH, HEIGHT).figure().build_payload_split(N_BUCKETS)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close("all")


@pytest.fixture(scope="module")
def small_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    x = np.arange(SMALL_N, dtype=np.float64)
    return x, rng.normal(0.0, 1.0, SMALL_N)


@pytest.fixture(scope="module")
def medium_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(11)
    x = np.arange(MEDIUM_N, dtype=np.float64)
    return x, rng.normal(0.0, 1.0, MEDIUM_N)


@pytest.fixture(scope="module")
def large_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    x = np.arange(LARGE_N, dtype=np.float64)
    return x, rng.normal(0.0, 1.0, LARGE_N)


@pytest.fixture(scope="module")
def hist_values() -> np.ndarray:
    rng = np.random.default_rng(31)
    return np.concatenate(
        [
            rng.normal(-1.1, 0.52, HIST_N // 2),
            rng.normal(1.35, 0.68, HIST_N - HIST_N // 2),
        ]
    ).astype(np.float64, copy=False)


@pytest.fixture(scope="module")
def bar_data() -> tuple[list[str], np.ndarray]:
    rng = np.random.default_rng(23)
    categories = [f"C{i:04d}" for i in range(BAR_N)]
    values = (
        42.0 + 18.0 * np.sin(np.linspace(0.0, 18.0, BAR_N)) + rng.normal(0.0, 3.0, BAR_N)
    ).astype(np.float64, copy=False)
    return categories, values


@pytest.fixture(scope="module")
def panel_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(53)
    x = np.arange(PANEL_N, dtype=np.float64)
    actual = 40.0 + 6.0 * np.sin(x * 0.004) + rng.normal(0.0, 0.8, PANEL_N)
    target = 42.0 + 5.0 * np.cos(x * 0.003)
    sample = 0.6 * actual + 0.4 * target
    return x, actual, target, sample


@pytest.fixture(scope="module")
def export_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(29)
    x = np.arange(EXPORT_N, dtype=np.float64)
    y = (np.sin(x * 0.001) + rng.normal(0.0, 0.08, EXPORT_N)).astype(np.float64, copy=False)
    return x, y


# -- paired build arms --------------------------------------------------------
#
# The raw arm mirrors the shim's implicit defaults (explicit x/y axes, the
# 640x480 canvas) so the pair differs only in which API expressed the chart.
# The pyplot arm includes plt.close("all") because figure-registry bookkeeping
# is part of the shim's per-figure cost — the exact cost the guardrail bounds.


def _raw_line_payload(x: np.ndarray, y: np.ndarray) -> int:
    c = fc.chart(
        fc.line(x=x, y=y, color="#1f77b4"),
        fc.x_axis(),
        fc.y_axis(),
        width=WIDTH,
        height=HEIGHT,
    )
    _spec, buffers = c.figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _pyplot_line_payload(x: np.ndarray, y: np.ndarray) -> int:
    plt.close("all")
    _fig, ax = plt.subplots()
    ax.plot(x, y)
    _spec, buffers = ax._build_chart(WIDTH, HEIGHT).figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _raw_scatter_payload(x: np.ndarray, y: np.ndarray) -> int:
    c = fc.chart(
        fc.scatter(x=x, y=y, color="#1f77b4", size=6.0),
        fc.x_axis(),
        fc.y_axis(),
        width=WIDTH,
        height=HEIGHT,
    )
    _spec, buffers = c.figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _pyplot_scatter_payload(x: np.ndarray, y: np.ndarray) -> int:
    plt.close("all")
    _fig, ax = plt.subplots()
    ax.scatter(x, y, c="#1f77b4", s=36.0)
    _spec, buffers = ax._build_chart(WIDTH, HEIGHT).figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _raw_histogram_payload(values: np.ndarray) -> int:
    c = fc.chart(
        fc.histogram(values, bins=HIST_BINS),
        fc.x_axis(),
        fc.y_axis(),
        width=WIDTH,
        height=HEIGHT,
    )
    _spec, buffers = c.figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _pyplot_histogram_payload(values: np.ndarray) -> int:
    plt.close("all")
    _fig, ax = plt.subplots()
    ax.hist(values, bins=HIST_BINS)
    _spec, buffers = ax._build_chart(WIDTH, HEIGHT).figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _raw_bar_payload(categories: list[str], values: np.ndarray) -> int:
    c = fc.chart(
        fc.bar(categories, values),
        fc.x_axis(),
        fc.y_axis(),
        width=WIDTH,
        height=HEIGHT,
    )
    _spec, buffers = c.figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _pyplot_bar_payload(categories: list[str], values: np.ndarray) -> int:
    plt.close("all")
    _fig, ax = plt.subplots()
    ax.bar(categories, values)
    _spec, buffers = ax._build_chart(WIDTH, HEIGHT).figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _raw_styled_panel_payload(
    x: np.ndarray, actual: np.ndarray, target: np.ndarray, sample: np.ndarray
) -> int:
    c = fc.chart(
        fc.line(x=x, y=actual, color="#ff0000", dash="dashed", width=2.0, name="actual"),
        fc.line(x=x, y=target, color="#008000", name="target"),
        fc.scatter(x=x, y=sample, color="#1f77b4", size=6.0, name="sample"),
        fc.x_axis(label="time"),
        fc.y_axis(label="value"),
        fc.legend(),
        title="pipeline",
        width=WIDTH,
        height=HEIGHT,
    )
    _spec, buffers = c.figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


def _pyplot_styled_panel_payload(
    x: np.ndarray, actual: np.ndarray, target: np.ndarray, sample: np.ndarray
) -> int:
    plt.close("all")
    _fig, ax = plt.subplots()
    ax.plot(x, actual, "r--", linewidth=2.0, label="actual")
    ax.plot(x, target, "g-", label="target")
    ax.scatter(x, sample, c="#1f77b4", s=36.0, label="sample")
    ax.set_title("pipeline")
    ax.set_xlabel("time")
    ax.set_ylabel("value")
    ax.legend()
    _spec, buffers = ax._build_chart(WIDTH, HEIGHT).figure().build_payload_split(N_BUCKETS)
    return sum(b.nbytes for b in buffers)


# -- build pairs ---------------------------------------------------------------


def test_build_line_small_raw(benchmark, small_data):
    """Everyday 10k line through the declarative API: the shim pair's baseline."""
    x, y = small_data
    assert benchmark(_raw_line_payload, x, y) > 0


def test_build_line_small_pyplot(benchmark, small_data):
    """Same 10k line via plt.subplots/ax.plot; the gap to *_raw is the shim."""
    x, y = small_data
    payload_bytes = benchmark(_pyplot_line_payload, x, y)
    # Same chart on the wire: identical trace buffers, or the pair is dishonest.
    assert payload_bytes == _raw_line_payload(x, y)


def test_build_line_large_raw(benchmark, large_data):
    """1M-point line: M4 decimation dominates; the pair shows shim cost is flat."""
    x, y = large_data
    payload_bytes = _raw_line_payload(x, y)
    assert 0 < payload_bytes < x.nbytes + y.nbytes
    assert benchmark(_raw_line_payload, x, y) == payload_bytes


def test_build_line_large_pyplot(benchmark, large_data):
    """Same 1M line via the shim; must ship the same decimated payload."""
    x, y = large_data
    payload_bytes = benchmark(_pyplot_line_payload, x, y)
    assert payload_bytes == _raw_line_payload(x, y)


def test_build_scatter_medium_raw(benchmark, medium_data):
    """100k exact scatter through the declarative API."""
    x, y = medium_data
    assert benchmark(_raw_scatter_payload, x, y) > 0


def test_build_scatter_medium_pyplot(benchmark, medium_data):
    """Same 100k scatter via ax.scatter, including mpl s= translation."""
    x, y = medium_data
    payload_bytes = benchmark(_pyplot_scatter_payload, x, y)
    assert payload_bytes == _raw_scatter_payload(x, y)


def test_build_histogram_raw(benchmark, hist_values):
    """100k-observation histogram (200 bins) through the declarative API."""
    assert benchmark(_raw_histogram_payload, hist_values) > 0


def test_build_histogram_pyplot(benchmark, hist_values):
    """Same histogram via ax.hist, including its return-tuple construction.

    ax.hist pre-bins with NumPy (it must return matplotlib's (n, bins,
    patches) tuple) and ships bar geometry, while fc.histogram bins natively
    and ships rect columns — so the two arms' payload layouts differ. Both
    must stay bounded by bin count, never by the observation count.
    """
    payload_bytes = benchmark(_pyplot_histogram_payload, hist_values)
    assert 0 < payload_bytes < hist_values.nbytes


def test_build_bar_categorical_raw(benchmark, bar_data):
    """1k-category bar chart through the declarative API."""
    categories, values = bar_data
    assert benchmark(_raw_bar_payload, categories, values) > 0


def test_build_bar_categorical_pyplot(benchmark, bar_data):
    """Same categorical bars via ax.bar."""
    categories, values = bar_data
    payload_bytes = benchmark(_pyplot_bar_payload, categories, values)
    assert payload_bytes == _raw_bar_payload(categories, values)


def test_build_styled_panel_raw(benchmark, panel_data):
    """Chrome-heavy layered panel (3 series, title/labels/legend), raw API."""
    x, actual, target, sample = panel_data
    assert benchmark(_raw_styled_panel_payload, x, actual, target, sample) > 0


def test_build_styled_panel_pyplot(benchmark, panel_data):
    """Same panel via the shim: fmt strings, label/legend/title translation.

    This is the shim's worst honest case — the workload where translation
    (fmt parsing, prop cycling, chrome mapping) is largest relative to data.
    """
    x, actual, target, sample = panel_data
    payload_bytes = benchmark(_pyplot_styled_panel_payload, x, actual, target, sample)
    assert payload_bytes == _raw_styled_panel_payload(x, actual, target, sample)


# -- export pair ----------------------------------------------------------------


def test_png_export_line_raw(benchmark, export_data):
    """Native PNG export of a warm 100k line figure through the raw API."""
    x, y = export_data
    fig = fc.chart(fc.line(x=x, y=y), width=WIDTH, height=HEIGHT).figure()
    png = benchmark(fig.to_png, engine=fc.Engine.default, scale=1.0)
    assert png.startswith(b"\x89PNG")


def test_png_export_line_pyplot(benchmark, export_data):
    """Same export via figure.savefig: the full public shim static path."""
    x, y = export_data
    plt.close("all")
    fig, ax = plt.subplots()
    ax.plot(x, y)

    def export() -> bytes:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        return buffer.getvalue()

    png = benchmark(export)
    assert png.startswith(b"\x89PNG")
    plt.close("all")
