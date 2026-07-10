"""Streaming append (rust-engine §5, Phase-0): columns grow in place with
incremental zone maps; Figure.append re-emits a screen-bounded refresh; the
tile pyramid and drill state invalidate so the next view decision is fresh."""

from __future__ import annotations

import numpy as np
import pytest

from fastcharts._figure import SCATTER_DENSITY_THRESHOLD, Figure
from fastcharts.columns import ZONE_CHUNK, ColumnStore

# --------------------------------------------------------------------------
# Column.append — the data layer
# --------------------------------------------------------------------------


def test_column_append_extends_values_and_zone_maps():
    store = ColumnStore()
    col = store.ingest(np.arange(10.0))
    col.append(np.arange(10.0, 25.0))
    np.testing.assert_array_equal(col.values, np.arange(25.0))
    assert col.zone.count == 25
    assert col.min == 0.0 and col.max == 24.0


def test_column_append_zone_maps_match_full_recompute():
    # The incremental splice must be indistinguishable from ingesting the
    # concatenated data from scratch — chunk-exact, all six statistics.
    rng = np.random.default_rng(9)
    first = rng.uniform(-50, 50, ZONE_CHUNK + 137)  # straddles a chunk boundary
    second = rng.uniform(-50, 50, ZONE_CHUNK // 3)
    second[7] = np.nan  # nulls in the tail must be accounted
    col = ColumnStore().ingest(first)
    col.append(second)
    ref = ColumnStore().ingest(np.concatenate([first, second]))
    for field in (
        "mins",
        "maxs",
        "counts",
        "null_counts",
        "sums",
        "sum_sqs",
        "positive_mins",
        "positive_maxs",
    ):
        np.testing.assert_array_equal(
            getattr(col.zone, field), getattr(ref.zone, field), err_msg=field
        )


def test_column_append_amortizes_growth():
    col = ColumnStore().ingest(np.arange(10.0))
    col.append([10.0])
    copies_after_first = col.ingest_copies
    ptr = col.values.__array_interface__["data"][0]
    for v in range(11, 200):  # stays within the first growth buffer
        col.append([float(v)])
    assert col.values.__array_interface__["data"][0] == ptr  # no per-append migration
    assert col.ingest_copies == copies_after_first
    np.testing.assert_array_equal(col.values, np.arange(200.0))


def test_column_append_kind_mismatch_raises():
    col = ColumnStore().ingest(np.arange(5.0))
    with pytest.raises(ValueError, match=r"kind|time_ms"):
        col.append(np.array(["2024-01-01"], dtype="datetime64[ms]"))


def test_time_column_append():
    ts = np.array(["2024-01-01T00:00:00", "2024-01-01T00:00:01"], dtype="datetime64[ms]")
    col = ColumnStore().ingest(ts)
    col.append(np.array(["2024-01-01T00:00:02"], dtype="datetime64[ms]"))
    assert col.kind == "time_ms"
    assert col.values[2] - col.values[1] == pytest.approx(1000.0)


def test_arrow_zero_copy_column_append_migrates_once():
    pa = pytest.importorskip("pyarrow")
    col = ColumnStore().ingest(pa.array(np.arange(100.0)))
    assert col.ingest_copies == 0  # zero-copy view of the Arrow buffer
    col.append([100.0, 101.0])  # read-only view cannot grow in place
    assert col.ingest_copies == 1  # ...so the migration is on the books (§29)
    assert col.values.flags.writeable
    np.testing.assert_array_equal(col.values, np.arange(102.0))


# --------------------------------------------------------------------------
# Figure.append — the trace layer and refresh message
# --------------------------------------------------------------------------


def _msg(fig, tid, x, y, **kw):
    msg, buffers = fig.append(tid, x, y, **kw)
    assert msg["type"] == "append"
    assert msg["affected"] == [tid]
    assert isinstance(buffers[0], bytes)
    return msg, buffers


def test_append_direct_scatter_reships_and_repicks():
    fig = Figure().scatter(np.arange(100.0), np.arange(100.0))
    msg, _ = _msg(fig, 0, [100.0, 101.0], [200.0, 300.0])
    tr = msg["spec"]["traces"][0]
    assert tr["tier"] == "direct"
    assert tr["n_points"] == 102
    assert msg["spec"]["x_axis"]["range"][1] >= 101.0  # domain followed the data
    assert msg["spec"]["y_axis"]["range"][1] >= 300.0
    row = fig.pick(0, 101)
    assert row is not None and row["x"] == 101.0 and row["y"] == 300.0


def test_append_line_requires_monotone_continuation():
    fig = Figure().line(np.arange(50.0), np.arange(50.0))
    with pytest.raises(ValueError, match="continue the series"):
        fig.append(0, [10.0], [1.0])  # starts before the current last x
    with pytest.raises(ValueError, match="ascending"):
        fig.append(0, [60.0, 55.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="finite"):
        fig.append(0, [np.nan], [1.0])
    msg, _ = _msg(fig, 0, [50.0, 51.0], [1.0, 2.0])  # equal-to-last is allowed
    assert msg["spec"]["traces"][0]["n_points"] == 52


def test_append_validation_is_atomic():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    with pytest.raises(ValueError, match="equal length"):
        fig.append(0, [1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="at least one row"):
        fig.append(0, [], [])
    assert len(fig.traces[0].x) == 10  # nothing mutated


def test_append_rejects_unsupported_kinds_and_shared_columns():
    fig = Figure()
    fig.histogram(np.arange(100.0))
    with pytest.raises(ValueError, match="scatter/line"):
        fig.append(0, [1.0], [1.0])

    shared = np.arange(20.0)
    fig2 = Figure()
    fig2.scatter(shared, np.arange(20.0))
    fig2.scatter(shared, np.arange(20.0) * 2)  # store dedups: same Column object
    if fig2.traces[0].x is fig2.traces[1].x:
        with pytest.raises(ValueError, match="share"):
            fig2.append(0, [20.0], [20.0])


def test_append_channel_contract():
    c = np.linspace(0, 1, 30)
    fig = Figure().scatter(np.arange(30.0), np.arange(30.0), color=c, size=c)
    with pytest.raises(ValueError, match="continuous color channel"):
        fig.append(0, [30.0], [30.0], size=[0.5])
    msg, _ = _msg(fig, 0, [30.0], [30.0], color=[0.5], size=[0.5])
    assert len(fig.traces[0].color_ch.values) == 31

    plain = Figure().scatter(np.arange(10.0), np.arange(10.0))
    with pytest.raises(ValueError, match="no per-point color"):
        plain.append(0, [10.0], [10.0], color=[0.5])

    cat = Figure().scatter(np.arange(4.0), np.arange(4.0), color=np.array(["a", "b", "a", "b"]))
    with pytest.raises(ValueError, match="categorical"):
        cat.append(0, [4.0], [4.0], color=["a"])


def test_append_continuous_channels_expand_domains_and_reuse_buffers():
    values = np.arange(8.0)
    fig = Figure().scatter(values, values, color=values, size=values)
    trace = fig.traces[0]

    fig.append(0, [8.0], [8.0], color=[100.0], size=[-50.0])
    assert trace.color_ch.domain[1] >= 100.0
    assert trace.size_ch.domain[0] <= -50.0
    color_ptr = trace.color_ch.values.__array_interface__["data"][0]
    size_ptr = trace.size_ch.values.__array_interface__["data"][0]

    for i in range(9, 200):
        fig.append(0, [float(i)], [float(i)], color=[float(i)], size=[float(i)])

    assert trace.color_ch.values.__array_interface__["data"][0] == color_ptr
    assert trace.size_ch.values.__array_interface__["data"][0] == size_ptr
    assert trace.color_ch.domain[1] >= 199.0
    assert trace.size_ch.domain[1] >= 199.0
    assert len(trace.color_ch.values) == len(trace.size_ch.values) == 200


def test_append_continuous_channels_repairs_rebound_prefix():
    values = np.arange(8.0)
    fig = Figure().scatter(values, values, color=values)
    channel = fig.traces[0].color_ch
    fig.append(0, [8.0], [8.0], color=[8.0])  # initialize the capacity buffer

    rebound = channel.values.copy()
    rebound[0] = 123.0
    channel.values = rebound
    fig.append(0, [9.0], [9.0], color=[9.0])

    assert channel.values[0] == 123.0
    np.testing.assert_array_equal(channel.values[-2:], [8.0, 9.0])


def test_append_density_trace_rebins_with_new_points():
    n = SCATTER_DENSITY_THRESHOLD + 50_000
    rng = np.random.default_rng(21)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    fig.build_payload()
    t = fig.traces[0]
    assert t.use_density()

    # Drill in, then append: the drill must exit so the next view re-decides.
    fig.density_view(0, 0.0, 5.0, 0.0, 5.0, 512, 384)
    assert t.drill_mode is True
    msg, _ = _msg(fig, 0, rng.uniform(0, 100, 1000), rng.uniform(0, 100, 1000))
    assert t.drill_mode is False
    assert msg["spec"]["traces"][0]["tier"] == "density"
    assert msg["spec"]["traces"][0]["n_points"] == n + 1000

    # The next full-window density view counts the appended points.
    update, _ = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 64, 48)
    assert update["traces"][0]["visible"] == n + 1000


def test_append_invalidates_pyramid_for_lazy_rebuild():
    from fastcharts.config import PYRAMID_MIN_POINTS
    from fastcharts.interaction import _ensure_pyramid

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(31)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    t = fig.traces[0]
    assert _ensure_pyramid(t) is not None
    old_handle = t._pyr_handle
    fig.append(0, [50.0], [50.0])
    assert t._pyr_handle is None  # freed; rebuilds lazily on next far-out view
    assert _ensure_pyramid(t) is not None
    assert t._pyr_handle != 0 and t._pyr_handle != old_handle


def test_pyramid_handle_freed_when_trace_is_garbage_collected():
    """§27: a discarded Figure (notebook cell re-run) must not leak its
    native pyramid in the process-lifetime registry."""
    import gc

    from fastcharts import kernels
    from fastcharts.config import PYRAMID_MIN_POINTS
    from fastcharts.interaction import _ensure_pyramid

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(41)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    t = fig.traces[0]
    assert _ensure_pyramid(t) is not None
    handle = t._pyr_handle
    assert handle

    del fig, t
    gc.collect()
    # The finalizer already freed the handle: a second free reports stale.
    assert not kernels.pyramid_free(handle)


def test_explicit_pyramid_free_disarms_gc_finalizer():
    import gc

    from fastcharts import kernels
    from fastcharts.config import PYRAMID_MIN_POINTS
    from fastcharts.interaction import _ensure_pyramid

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(43)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    t = fig.traces[0]
    assert _ensure_pyramid(t) is not None
    old_handle = t._pyr_handle

    # append frees eagerly (lazy rebuild); rebuild, then drop the figure —
    # the rebuilt pyramid must be freed by GC, and the disarmed finalizer of
    # the appended-over handle must not double-free a recycled slot.
    fig.append(0, [50.0], [50.0])
    assert t._pyr_handle is None
    assert not kernels.pyramid_free(old_handle)  # already freed by append
    assert _ensure_pyramid(t) is not None
    new_handle = t._pyr_handle
    del fig, t
    gc.collect()
    assert not kernels.pyramid_free(new_handle)


def test_memory_report_itemizes_pyramid_bytes():
    from fastcharts.config import PYRAMID_MIN_POINTS
    from fastcharts.interaction import _ensure_pyramid, _pyramid_resident_bytes

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(47)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    assert fig.memory_report()["pyramid_bytes"] == 0  # not built yet
    assert _ensure_pyramid(fig.traces[0]) is not None
    assert fig.memory_report()["pyramid_bytes"] == _pyramid_resident_bytes()
