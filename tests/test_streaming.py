"""Streaming append: columns and stable-domain tile pyramids update in place;
Figure.append re-emits a screen-bounded refresh; domain growth invalidates the
pyramid, and drill state always exits so the next view decision is fresh."""

from __future__ import annotations

import numpy as np
import pytest

from xy import kernels
from xy._figure import SCATTER_DENSITY_THRESHOLD, Figure
from xy.columns import ZONE_CHUNK, ColumnStore

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
    # Split layout, like first paint: borrowed per-column views, no join copy.
    assert msg["spec"]["buffer_layout"] == "split"
    assert len(buffers) == len(msg["spec"]["columns"])
    assert all(isinstance(b, memoryview) for b in buffers)
    # The spec names the append so trait-transported hosts can apply it.
    tag = msg["spec"]["append"]
    assert tag["affected"] == [tid]
    assert isinstance(tag["seq"], int) and tag["seq"] >= 1
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
    fig = Figure().scatter(values, values + 0.5, color=values, size=values)
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
    fig = Figure().scatter(values, values + 0.5, color=values)
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


def test_append_updates_pyramid_in_place_when_domain_is_stable():
    from xy.config import PYRAMID_MIN_POINTS
    from xy.interaction import _ensure_pyramid

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(31)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    t = fig.traces[0]
    assert _ensure_pyramid(t) is not None
    old_handle = t._pyr_handle
    fig.append(0, [50.0], [50.0])
    assert t._pyr_handle == old_handle
    assert _ensure_pyramid(t) == old_handle
    assert kernels.pyramid_count(old_handle, 0.0, 100.0, 0.0, 100.0) == n + 1


def test_append_invalidates_pyramid_when_domain_grows():
    from xy.config import PYRAMID_MIN_POINTS
    from xy.interaction import _ensure_pyramid

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(32)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    t = fig.traces[0]
    old_handle = _ensure_pyramid(t)
    assert old_handle is not None

    fig.append(0, [200.0], [50.0])
    assert t._pyr_handle is None
    assert kernels.pyramid_count(old_handle, 0.0, 100.0, 0.0, 100.0) is None
    assert _ensure_pyramid(t) not in (None, 0, old_handle)


def test_pyramid_handle_freed_when_trace_is_garbage_collected():
    """§27: a discarded Figure (notebook cell re-run) must not leak its
    native pyramid in the process-lifetime registry."""
    import gc

    from xy import kernels
    from xy.config import PYRAMID_MIN_POINTS
    from xy.interaction import _ensure_pyramid

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


def test_incremental_pyramid_keeps_gc_finalizer_armed():
    import gc

    from xy import kernels
    from xy.config import PYRAMID_MIN_POINTS
    from xy.interaction import _ensure_pyramid

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(43)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    t = fig.traces[0]
    assert _ensure_pyramid(t) is not None
    old_handle = t._pyr_handle

    # A stable-domain append retains both handle and finalizer; dropping the
    # figure must still release that incrementally updated native cache once.
    fig.append(0, [50.0], [50.0])
    assert t._pyr_handle == old_handle
    del fig, t
    gc.collect()
    assert not kernels.pyramid_free(old_handle)


def test_memory_report_itemizes_pyramid_bytes():
    from xy.config import PYRAMID_MIN_POINTS
    from xy.interaction import _ensure_pyramid, _pyramid_resident_bytes

    n = max(PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD + 1)
    rng = np.random.default_rng(47)
    fig = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    assert fig.memory_report()["pyramid_bytes"] == 0  # not built yet
    assert _ensure_pyramid(fig.traces[0]) is not None
    assert fig.memory_report()["pyramid_bytes"] == _pyramid_resident_bytes()


# --------------------------------------------------------------------------
# Append reuse (§4): emit cache + cid wire omission
# --------------------------------------------------------------------------


def _two_trace_fig():
    rng = np.random.default_rng(11)
    fig = Figure()
    fig.scatter(np.arange(100.0), rng.normal(size=100))
    fig.scatter(np.arange(100.0) * 2.0, rng.normal(size=100))
    return fig


def test_append_omits_unchanged_trace_buffers():
    fig = _two_trace_fig()
    tid0, tid1 = fig.traces[0].id, fig.traces[1].id
    # First paint establishes the client baseline.
    fig.build_payload_split()

    msg, buffers = fig.append(tid0, [100.0], [0.0])
    cols = msg["spec"]["columns"]
    by_trace = {t["id"]: t for t in msg["spec"]["traces"]}
    # The affected trace re-ships its geometry.
    assert "buf" in cols[by_trace[tid0]["x"]]
    # The unchanged trace's columns are cid-only addressing: no bytes.
    for idx in (by_trace[tid1]["x"], by_trace[tid1]["y"]):
        assert "buf" not in cols[idx]
        assert isinstance(cols[idx]["cid"], str)
    # The wire carries fewer buffers than the table has columns.
    assert len(buffers) < len(cols)
    shipped = sum(1 for c in cols if "buf" in c)
    assert len(buffers) == shipped


def test_append_emit_cache_skips_reencode_for_unchanged_traces():
    fig = _two_trace_fig()
    tid0 = fig.traces[0].id
    tid1 = fig.traces[1].id
    # NaN tails keep every tick on the full build path (delta-ineligible),
    # which is the machinery under test here.
    fig.append(tid0, [np.nan], [0.0])
    first = fig._append_emit_cache[tid1]
    fig.append(tid0, [np.nan], [0.0])
    second = fig._append_emit_cache[tid1]
    # Cache hit: the unchanged trace's capture (records incl. encoded chunks)
    # is the SAME object — its emitter never ran on the second tick.
    assert second is first
    # The affected trace's capture was rebuilt both ticks.
    assert fig._append_emit_cache[tid0]["records"] is not None
    assert fig._append_emit_cache[tid0]["key"][0] == fig.traces[0].data_rev


def test_append_reuse_reships_after_full_split_build_resets_baseline():
    fig = _two_trace_fig()
    tid0 = fig.traces[0].id
    fig.append(tid0, [100.0], [0.0])
    # A fresh full build (new subscriber / reopen sync) resets the baseline
    # to exactly what it shipped — the next append may still omit unchanged
    # columns because their cids are unchanged.
    fig.build_payload_split()
    msg, buffers = fig.append(tid0, [101.0], [0.0])
    cols = msg["spec"]["columns"]
    assert any("buf" not in c for c in cols)  # reuse survives the reset


def test_append_cache_busts_on_affected_shape_change_and_stays_correct():
    # Crossing the density threshold changes the affected trace's column
    # count; the positional splice must fall back to a full rebuild.
    n = SCATTER_DENSITY_THRESHOLD - 5
    rng = np.random.default_rng(13)
    fig = Figure()
    fig.scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    fig.scatter(np.arange(50.0), np.arange(50.0))
    tid0 = fig.traces[0].id
    fig.append(tid0, [1.0], [1.0])  # seeds the cache, still direct
    assert fig.traces[0].use_density() is False
    msg, buffers = fig.append(tid0, rng.uniform(0, 100, 10), rng.uniform(0, 100, 10))
    assert fig.traces[0].use_density() is True
    entry = next(t for t in msg["spec"]["traces"] if t["id"] == tid0)
    assert entry["tier"] == "density"
    # The spliced neighbor stays addressable and correct.
    cols = msg["spec"]["columns"]
    other = next(t for t in msg["spec"]["traces"] if t["id"] != tid0)
    assert cols[other["x"]]["len"] == 50


def test_append_range_growth_busts_range_dependent_neighbors_only():
    from xy._figure import DECIMATION_THRESHOLD

    n = DECIMATION_THRESHOLD + 100
    x = np.arange(float(n))
    fig = Figure()
    fig.scatter(np.arange(100.0), np.arange(100.0))  # affected: grows shared x
    fig.line(x, np.sin(x * 1e-3))  # decimated: bins over the shared x range
    fig.scatter(np.arange(50.0), np.arange(50.0))  # direct: range-free
    tid0 = fig.traces[0].id
    fig.append(tid0, [float(n) + 1.0], [0.0])  # seed cache; x range grows past line
    line_key = fig._append_emit_cache[fig.traces[1].id]["key"]
    direct_cache = fig._append_emit_cache[fig.traces[2].id]
    # A NaN row keeps this tick on the full build path while the finite row
    # still grows the shared x range.
    fig.append(tid0, [float(n) + 500.0, np.nan], [0.0, 0.0])
    # The decimated line re-emitted (its M4 window follows the range)...
    assert fig._append_emit_cache[fig.traces[1].id]["key"] != line_key
    # ...while the range-free direct scatter spliced from cache.
    assert fig._append_emit_cache[fig.traces[2].id] is direct_cache


def test_refresh_request_returns_full_append_shaped_payload():
    from xy.channel import handle_message

    fig = _two_trace_fig()
    fig.append(fig.traces[0].id, [100.0], [0.0])
    reply = handle_message(fig, {"type": "refresh"})
    assert reply is not None
    msg, buffers = reply
    assert msg["type"] == "append"
    assert msg["affected"] == [t.id for t in fig.traces]
    cols = msg["spec"]["columns"]
    assert all("buf" in c for c in cols)  # complete: no cid-only entries
    assert len(buffers) == len([c for c in cols if "buf" in c])


# --------------------------------------------------------------------------
# append_rows delta frames (§4): O(K) wire for direct-tier streams
# --------------------------------------------------------------------------


def _delta_fig(n=100):
    x = np.arange(float(n))
    fig = Figure().scatter(x, x + 0.5, color=np.arange(float(n)), size=np.arange(float(n)))
    fig.build_payload_split()
    return fig


def test_append_rejects_xy_aliased_to_one_column():
    # Store dedup aliases scatter(v, v) to a single canonical column; a
    # two-tail append would interleave x and y into it (pre-existing bug,
    # now rejected like cross-trace sharing).
    vals = np.arange(10.0)
    fig = Figure().scatter(vals, vals)
    if fig.traces[0].x is fig.traces[0].y:
        with pytest.raises(ValueError, match="shares one column"):
            fig.append(0, [10.0], [1.0])
        assert len(fig.traces[0].x) == 10  # nothing mutated


def test_append_rows_delta_after_baseline():
    fig = _delta_fig()
    m1, _ = fig.append(0, [100.0], [1.0], color=[5.0], size=[5.0])
    assert m1["type"] == "append"  # first tick seeds the emit-cache baseline
    assert m1["spec"]["append"]["delta_fallback"] == "no-baseline"

    m2, bufs = fig.append(0, [101.0, 102.0], [2.0, 3.0], color=[500.0, 1.0], size=[6.0, 7.0])
    assert m2["type"] == "append_rows"
    assert m2["prev_marks"] == 101 and m2["added"] == 2
    assert m2["n_points"] == 103
    # Tails only: 2 f32 per geometry/channel column.
    assert all(len(b) == 8 for b in bufs)
    # The grown color domain rides the message (a client uniform update).
    assert m2["domains"]["color"] == [0.0, 500.0]
    assert "x" in m2["columns"] and "offset" in m2["columns"]["x"]
    # Kernel state advanced: pick reads the streamed rows exactly.
    row = fig.pick(0, 102)
    assert row["x"] == 102.0 and row["color_value"] == 1.0

    m3, _ = fig.append(0, [103.0], [4.0], color=[2.0], size=[8.0])
    assert m3["type"] == "append_rows"
    assert m3["prev_marks"] == 103  # consecutive deltas track shipped marks


def test_append_rows_falls_back_and_recovers():
    fig = _delta_fig()
    fig.append(0, [100.0], [1.0], color=[1.0], size=[1.0])  # baseline

    # Offset drift: a tail absurdly far from the shipped offset re-centers
    # via a full re-ship (§4/§16), never a torn delta.
    m, _ = fig.append(0, [1e12], [1.0], color=[1.0], size=[1.0])
    assert m["type"] == "append"
    assert m["spec"]["append"]["delta_fallback"] == "offset-drift"

    # The full build re-seeded the baseline: deltas resume.
    m2, _ = fig.append(0, [1.1e12], [1.0], color=[1.0], size=[1.0])
    assert m2["type"] == "append_rows"


def test_append_rows_fallback_reasons():
    # Non-finite tail rows would fork the shipped row order.
    fig = _delta_fig()
    fig.append(0, [100.0], [1.0], color=[1.0], size=[1.0])
    m, _ = fig.append(0, [np.nan], [1.0], color=[1.0], size=[1.0])
    assert m["type"] == "append"
    assert m["spec"]["append"]["delta_fallback"] == "nonfinite-tail"

    # Keyed transitions need full-payload matching.
    vals = np.arange(10.0)
    keyed = Figure().scatter(vals, vals + 0.5)
    keyed.traces[0].transition_keys = np.zeros((10, 2), dtype=np.uint32)
    keyed.append(0, [10.0], [1.0])
    m, _ = keyed.append(0, [11.0], [1.0])
    assert m["spec"]["append"]["delta_fallback"] == "animation"

    # Crossing the density threshold flips the tier: full re-ship.
    n = SCATTER_DENSITY_THRESHOLD - 2
    rng = np.random.default_rng(17)
    big = Figure().scatter(rng.uniform(0, 100, n), rng.uniform(0, 100, n))
    big.append(0, [1.0], [1.0])
    m, _ = big.append(0, np.full(10, 2.0), np.full(10, 2.0))
    assert m["type"] == "append"
    assert m["spec"]["append"]["delta_fallback"] == "tier-flip"
    assert m["spec"]["traces"][0]["tier"] == "density"


def test_append_rows_then_full_build_stays_coherent():
    fig = _delta_fig()
    fig.append(0, [100.0], [1.0], color=[1.0], size=[1.0])
    fig.append(0, [101.0], [2.0], color=[2.0], size=[2.0])  # delta
    spec, bufs = fig.build_payload_split()
    tr = spec["traces"][0]
    assert tr["n_points"] == 102
    x = np.frombuffer(bytes(bufs[spec["columns"][tr["x"]]["buf"]]), dtype=np.float32)
    assert len(x) == 102


def test_append_rows_then_neighbor_append_reships_streamed_trace():
    # After deltas mutate trace 0, a full append for trace 1 must re-ship
    # trace 0's columns (its data_rev moved, so its cids no longer match the
    # client baseline) — never leave the client resolving stale bytes.
    vals = np.arange(50.0)
    fig = Figure()
    fig.scatter(vals, vals + 0.5)
    fig.scatter(vals * 2.0, vals + 1.0)
    fig.build_payload_split()
    fig.append(0, [50.0], [1.0])  # baseline for trace 0
    m, _ = fig.append(0, [51.0], [2.0])
    assert m["type"] == "append_rows"
    # Force a full build (NaN tail): trace 0 was mutated by deltas since its
    # cache entry, so its columns must re-ship with fresh bytes — its old
    # cids no longer describe what the client holds.
    m2, bufs2 = fig.append(1, [100.0, np.nan], [1.0, 1.0])
    assert m2["type"] == "append"
    cols = m2["spec"]["columns"]
    t0 = next(t for t in m2["spec"]["traces"] if t["id"] == 0)
    assert "buf" in cols[t0["x"]] and "buf" in cols[t0["y"]]
