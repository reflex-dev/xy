"""Zero-copy Arrow ingest (§4 / §29: copies are counted, never folklore).

pyarrow is an optional *input* format — fastcharts never imports it (module-
name duck typing in columns._arrow_to_numpy), so these tests importorskip and
run only where pyarrow is installed (CI's dev environment).
"""

from __future__ import annotations

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")

from fastcharts import Figure  # noqa: E402
from fastcharts.columns import ColumnStore  # noqa: E402


def _buf_addr(arr: "pa.Array") -> int:
    return arr.buffers()[1].address


def test_null_free_float64_array_is_zero_copy():
    data = np.arange(10_000, dtype=np.float64)
    arrow = pa.array(data)
    col = ColumnStore().ingest(arrow)
    assert col.kind == "float"
    assert col.ingest_copies == 0
    # The canonical column reads the Arrow buffer itself, not a copy.
    assert col.values.__array_interface__["data"][0] == _buf_addr(arrow)
    np.testing.assert_array_equal(col.values, data)


def test_zero_copy_column_is_read_only_but_fully_usable():
    n = 50_000
    rng = np.random.default_rng(5)
    ax = pa.array(rng.uniform(0, 100, n))
    ay = pa.array(rng.uniform(0, 100, n))
    fig = Figure().scatter(ax, ay)
    assert fig.traces[0].x.ingest_copies == 0
    assert not fig.traces[0].x.values.flags.writeable  # arrow buffer view
    # The read path never writes canonical values: spec build, selection,
    # pick all work over the read-only view.
    spec, blob = fig.build_payload()
    assert spec["traces"][0]["tier"] == "direct"
    sel = fig.select_range(10.0, 20.0, 0.0, 100.0)
    assert len(sel[0]) > 0
    assert fig.pick(0, 0) is not None


def test_nulls_materialize_as_nan_with_counted_copy():
    arrow = pa.array([1.0, None, 3.0, None, 5.0])
    col = ColumnStore().ingest(arrow)
    assert col.ingest_copies >= 1  # §29: the null copy is on the books
    np.testing.assert_array_equal(np.isnan(col.values), [False, True, False, True, False])
    assert col.zone.null_count == 2
    assert col.zone.count == 3


def test_int_array_with_nulls_becomes_float64_nan():
    arrow = pa.array([1, None, 3], type=pa.int64())
    col = ColumnStore().ingest(arrow)
    assert col.values.dtype == np.float64
    np.testing.assert_array_equal(col.values[[0, 2]], [1.0, 3.0])
    assert np.isnan(col.values[1])


def test_null_free_int_array_ingests():
    arrow = pa.array(np.arange(100, dtype=np.int32))
    col = ColumnStore().ingest(arrow)
    assert col.values.dtype == np.float64
    np.testing.assert_array_equal(col.values, np.arange(100.0))


def test_single_chunk_table_column_is_zero_copy():
    data = np.arange(1_000, dtype=np.float64)
    table = pa.table({"x": data, "y": data * 2.0})
    col = ColumnStore().ingest(table["x"])  # ChunkedArray, one chunk
    assert col.ingest_copies == 0
    assert col.values.__array_interface__["data"][0] == _buf_addr(table["x"].chunk(0))


def test_multi_chunk_column_concatenates_with_counted_copy():
    a = pa.chunked_array([pa.array([1.0, 2.0]), pa.array([3.0, 4.0])])
    col = ColumnStore().ingest(a)
    assert col.ingest_copies >= 1
    np.testing.assert_array_equal(col.values, [1.0, 2.0, 3.0, 4.0])


def test_timestamp_array_takes_the_time_path():
    ts = np.array(["2024-01-01T00:00:00", "2024-01-01T00:00:01", "NaT"], dtype="datetime64[ms]")
    arrow = pa.array(ts)
    col = ColumnStore().ingest(arrow)
    assert col.kind == "time_ms"
    assert col.values[1] - col.values[0] == pytest.approx(1000.0)  # ms since epoch
    assert np.isnan(col.values[2])  # NaT -> NaN (§19)


def test_sliced_array_offset_is_respected():
    data = np.arange(100, dtype=np.float64)
    arrow = pa.array(data).slice(10, 20)
    col = ColumnStore().ingest(arrow)
    np.testing.assert_array_equal(col.values, data[10:30])


def test_arrow_channels_and_full_scatter_wire():
    n = 2_000
    rng = np.random.default_rng(7)
    x = rng.uniform(0, 10, n)
    c = rng.uniform(0, 1, n)
    fig = Figure().scatter(pa.array(x), pa.array(x * 2), color=pa.array(c), size=pa.array(c))
    spec, _blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["color"]["mode"] == "continuous"
    # end-to-end: payload builds and the arrays round-trip through the store
    assert fig.traces[0].x.zone.count == n


def test_string_arrow_array_is_rejected_cleanly():
    arrow = pa.array(["a", "b"])
    with pytest.raises(ValueError, match="real numeric or datetime-like"):
        ColumnStore().ingest(arrow)
