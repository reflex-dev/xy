"""CodSpeed benchmarks for the backend interaction/selection handlers.

The browser rows in ``bench_interaction.py`` measure client input-to-pixel
latency; these rows isolate the Python/kernel work each gesture message
resolves to (§17/§34): hover pick readout, zone-pruned and full-scan box
select, lasso ray casting, and the cross-filter row-mask encoding the
view-state layer ships (view-state.md §5.1). None of them existed as CodSpeed
rows before, so a selection regression could only surface as browser
wall-clock noise; here it is attributed to the handler that caused it.

Collection order matters: this module sorts after ``test_codspeed_kernels.py``
and ``test_codspeed_pyplot.py``, so their fixture materialization order — and
therefore their baselines — is unchanged (see the ordering note in
test_codspeed_kernels.py).

Run locally with:

    codspeed run --mode simulation -- pytest benchmarks/test_codspeed_selection.py --codspeed
"""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy import channel
from xy import kernels as k
from xy._figure import Figure  # harness type annotations only

N_BUCKETS = 2048
SELECT_N = 1_000_000
PICK_N = 100_000
CROSSFILTER_N = 100_000
LASSO_VERTICES = 64


@pytest.fixture(scope="session", autouse=True)
def require_native_backend() -> None:
    assert k.BACKEND == "native", (
        "CodSpeed benchmarks must run against the native Rust backend; "
        f"got {k.BACKEND!r}. Build the native core before running them."
    )


@pytest.fixture(scope="session", autouse=True)
def warm_lazy_modules() -> None:
    """Run every measured handler once, untimed, before any measured region.

    CodSpeed simulation measures one-shot regions from a fresh checkout, and
    running this module standalone would otherwise charge the first row for
    lazy submodule imports and bytecode compilation instead of its own
    workload (the phantom regression documented in test_codspeed_kernels.py).
    """
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    fig = xy.chart(xy.scatter(x=x, y=y)).figure()
    fig.build_payload_split(N_BUCKETS)
    fig.pick(0, 0)
    channel.handle_message(fig, {"type": "select", "x0": 0.0, "x1": 3.0, "y0": 0.0, "y1": 1.0})
    channel.handle_message(
        fig,
        {"type": "select_polygon", "points": [[0.0, -1.0], [3.0, -1.0], [1.5, 2.0]]},
    )
    fig.selection_rows_message({0: np.array([0, 2], dtype=np.int64)})


@pytest.fixture(scope="module")
def sorted_x_figure() -> Figure:
    """1M scatter with monotone x: tight zone maps, so pruning has real work."""
    rng = np.random.default_rng(61)
    x = np.arange(SELECT_N, dtype=np.float64)
    y = rng.normal(0.0, 1.0, SELECT_N)
    fig = xy.chart(xy.scatter(x=x, y=y)).figure()
    fig.build_payload_split(N_BUCKETS)
    return fig


@pytest.fixture(scope="module")
def uniform_figure() -> Figure:
    """1M uniform scatter: every zone chunk overlaps, the full-scan path."""
    rng = np.random.default_rng(67)
    x = rng.uniform(0.0, 100.0, SELECT_N).astype(np.float64, copy=False)
    y = rng.uniform(0.0, 100.0, SELECT_N).astype(np.float64, copy=False)
    fig = xy.chart(xy.scatter(x=x, y=y)).figure()
    fig.build_payload_split(N_BUCKETS)
    return fig


@pytest.fixture(scope="module")
def pick_figure() -> Figure:
    """100k exact scatter with a categorical channel for the hover readout."""
    rng = np.random.default_rng(71)
    x = np.arange(PICK_N, dtype=np.float64)
    y = rng.normal(0.0, 1.0, PICK_N)
    categories = np.asarray([f"group-{i % 24:02d}" for i in range(PICK_N)])
    fig = xy.chart(xy.scatter(x=x, y=y, color=categories)).figure()
    fig.build_payload_split(N_BUCKETS)
    return fig


@pytest.fixture(scope="module")
def crossfilter_figure() -> Figure:
    """100k exact scatter whose NaN rows were dropped at ship time (§19), so
    canonical row ids and shipped vertex positions are distinct index spaces
    and the rows-selection path must actually translate between them."""
    rng = np.random.default_rng(73)
    x = np.arange(CROSSFILTER_N, dtype=np.float64)
    y = rng.normal(0.0, 1.0, CROSSFILTER_N)
    y[::100] = np.nan
    fig = xy.chart(xy.scatter(x=x, y=y)).figure()
    fig.build_payload_split(N_BUCKETS)
    return fig


def test_pick_hover_categorical_readout(benchmark, pick_figure):
    """Per-mousemove exact f64 row readout, including channel projection."""
    row = benchmark(pick_figure.pick, 0, 54_321)
    assert row is not None
    assert row["index"] == 54_321
    assert row["color_category"] == f"group-{54_321 % 24:02d}"


def test_select_box_zone_pruned_1m(benchmark, sorted_x_figure):
    """Box select over a 1% x-window: zone-map pruning plus candidate scan."""
    x0, x1 = SELECT_N * 0.495, SELECT_N * 0.505
    selected = benchmark(sorted_x_figure.select_range, x0, x1, -2.0, 2.0)
    # ~10k rows in the window, ~95.4% of a unit normal within +/-2 sigma.
    assert 8_000 < len(selected[0]) < 10_500


def test_select_box_message_full_scan_1m(benchmark, uniform_figure):
    """Full box-select gesture unit: dispatch, full scan, wire mask reply."""
    message = {"type": "select", "x0": 30.0, "x1": 60.0, "y0": 30.0, "y1": 60.0, "seq": 3}
    reply = benchmark(channel.handle_message, uniform_figure, message)
    assert reply is not None
    spec, buffers = reply
    # A 30x30 box over the 100x100 uniform domain holds ~9% of 1M points.
    assert 80_000 < spec["total"] < 100_000
    assert len(buffers[0]) == 4 * spec["traces"][0]["count"]


def test_select_lasso_message_1m(benchmark, uniform_figure):
    """Lasso gesture unit: bbox prune, ray casting, wire mask reply."""
    theta = np.linspace(0.0, 2.0 * np.pi, LASSO_VERTICES, endpoint=False)
    polygon = [[50.0 + 20.0 * np.cos(t), 50.0 + 20.0 * np.sin(t)] for t in theta]
    message = {"type": "select_polygon", "points": polygon, "seq": 4}
    reply = benchmark(channel.handle_message, uniform_figure, message)
    assert reply is not None
    spec, buffers = reply
    # A radius-20 disc covers ~12.6% of the 100x100 uniform domain.
    assert 115_000 < spec["total"] < 137_000
    assert len(buffers[0]) == 4 * spec["traces"][0]["count"]


def test_selection_rows_message_crossfilter(benchmark, crossfilter_figure):
    """Cross-filter rows -> validated, deduplicated, shipped-space wire mask."""
    rows = np.arange(0, CROSSFILTER_N, 2, dtype=np.int64)
    spec, buffers = benchmark(crossfilter_figure.selection_rows_message, {0: rows})
    trace = spec["traces"][0]
    assert spec["total"] == len(rows)
    # Strictly fewer shipped positions than canonical rows proves the NaN-
    # dropped translation path ran, not the identity fast path.
    assert 0 < trace["count"] < len(rows)
    assert len(buffers[0]) == 4 * trace["count"]
