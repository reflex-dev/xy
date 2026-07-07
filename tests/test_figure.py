"""Figure / spec / payload contracts: data-less spec (§9), single-copy store
(§4), decimation tiering with no silent reductions (§28), NaN never in vertex
buffers (§19), memory report honesty (§27)."""

from __future__ import annotations

import datetime as dt
import json
import warnings
from pathlib import Path

import numpy as np
import pytest

import fastcharts.export as export_module
from fastcharts import Figure
from fastcharts.columns import ColumnStore
from fastcharts.config import MAX_SCREEN_DIM
from fastcharts.export import _javascript_for_inline_script, _json_for_inline_script
from fastcharts.figure import DECIMATION_THRESHOLD, PROTOCOL_VERSION


def _payload_col(spec, blob, ref):
    meta = spec["columns"][ref]
    start = meta["byte_offset"]
    return np.frombuffer(blob, dtype=np.float32, count=meta["len"], offset=start), meta


def _decoded_payload_col(spec, blob, ref):
    vals, meta = _payload_col(spec, blob, ref)
    return vals.astype(np.float64) / meta.get("scale", 1.0) + meta.get("offset", 0.0)


def _bar_payload(spec, blob, tr):
    bar = tr["bar"]
    pos = _decoded_payload_col(spec, blob, bar["pos"])
    value1 = _decoded_payload_col(spec, blob, bar["value1"])
    if "value0" in bar:
        value0 = _decoded_payload_col(spec, blob, bar["value0"])
    else:
        value0 = np.full(len(value1), bar["value0_const"], dtype=np.float64)
    return bar, pos, value0, value1


def _figure_state(fig):
    return (
        len(fig.traces),
        len(fig.store),
        {axis: list(labels) for axis, labels in fig._axis_categories.items()},
    )


class _AppendThenRaiseList(list):
    def append(self, item):
        super().append(item)
        raise ValueError("synthetic trace append failure")


def _inline_spec_literal(html: str) -> str:
    body = html.split("<body>", 1)[1]
    return body.rsplit("const spec = ", 1)[1].split(";\n  const b64", 1)[0]


def test_spec_is_dataless_json():
    fig = Figure(title="t").scatter(np.arange(1000.0), np.arange(1000.0))
    spec, blob = fig.build_payload()
    # The spec must be tiny and JSON-serializable; data rides in the blob.
    text = json.dumps(spec)
    assert len(text) < 4096
    assert spec["protocol"] == PROTOCOL_VERSION
    assert len(blob) == 2 * 1000 * 4  # two f32 columns


def test_offset_encoding_roundtrip():
    x = 1.6e12 + np.arange(5000, dtype=np.float64)  # ms timestamps
    y = np.sin(np.arange(5000) * 0.01)
    fig = Figure().scatter(x, y)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    xe, xm = _payload_col(spec, blob, tr["x"])
    decoded = xe.astype(np.float64) / xm["scale"] + xm["offset"]
    assert np.abs(decoded - x).max() < 1e-3
    assert spec["x_axis"]["kind"] == "linear"  # plain floats, not datetime64


def test_time_axis_detection():
    t = np.arange("2024-01-01", "2024-03-01", dtype="datetime64[h]")
    fig = Figure().line(t, np.arange(len(t), dtype=np.float64))
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["kind"] == "time"
    xm = spec["columns"][spec["traces"][0]["x"]]
    assert xm["kind"] == "time_ms"


def test_column_store_datetime_nat_is_null_and_ignored_by_range():
    t = np.array(["2024-01-01", "NaT", "2024-01-03"], dtype="datetime64[D]")
    col = ColumnStore().ingest(t)
    expected = t.astype("datetime64[ms]").view(np.int64).astype(np.float64)
    assert col.kind == "time_ms"
    assert np.isnan(col.values[1])
    assert col.zone.null_count == 1
    assert col.min == expected[0]
    assert col.max == expected[2]
    assert col.min > 0.0


def test_column_store_accepts_python_datetime_objects_with_none_null():
    t = [dt.datetime(2024, 1, 1), None, dt.datetime(2024, 1, 3)]
    col = ColumnStore().ingest(t)
    assert col.kind == "time_ms"
    assert np.isnan(col.values[1])
    assert col.zone.null_count == 1


def test_python_datetime_objects_become_time_axis():
    t = [dt.datetime(2024, 1, 1), None, dt.datetime(2024, 1, 3)]
    fig = Figure().scatter(t, [1.0, 2.0, 3.0])
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["kind"] == "time"
    assert spec["traces"][0]["n_marks"] == 2


def test_column_store_datetime_copy_accounting_tracks_unit_conversion():
    ms = np.arange("2024-01-01", "2024-01-04", dtype="datetime64[ms]")
    seconds = np.arange("2024-01-01", "2024-01-04", dtype="datetime64[s]")
    assert ColumnStore().ingest(ms).ingest_copies == 1
    assert ColumnStore().ingest(seconds).ingest_copies == 2


def test_column_store_rejects_bad_shape_before_canonical_conversion():
    with pytest.raises(ValueError, match="columns must be 1-D"):
        ColumnStore().ingest(np.array([[1, 2], [3, 4]], dtype=np.int64))


def test_column_store_rejects_complex_and_bad_object_columns():
    with pytest.raises(ValueError, match="real numeric"):
        ColumnStore().ingest(np.array([1 + 2j, 3 + 4j]))
    with pytest.raises(ValueError, match="boolean"):
        ColumnStore().ingest(np.array([True, False]))
    with pytest.raises(ValueError, match="boolean"):
        ColumnStore().ingest(np.array([True, None], dtype=object))
    with pytest.raises(ValueError, match="real numeric"):
        ColumnStore().ingest(np.array(["a", "b"], dtype=object))


def test_long_line_ships_decimated():
    n = 200_000
    x = np.arange(n, dtype=np.float64)
    y = np.sin(x * 0.001)
    y[123_456] = 99.0
    fig = Figure().line(x, y)
    spec, blob = fig.build_payload(px_width=1024)
    tr = spec["traces"][0]
    assert tr["tier"] == "decimated"  # reduction recorded, never silent (§28)
    assert tr["n_points"] == n  # canonical count still reported
    assert tr["n_marks"] <= 4096
    ye, ym = _payload_col(spec, blob, tr["y"])
    assert len(ye) <= 4096  # ≤ 4 per pixel column
    # The spike survived decimation (M4 guarantee).
    assert np.isclose(ye.astype(np.float64).max() + ym["offset"], 99.0, atol=1e-3)


def test_long_line_with_no_finite_points_ships_empty_buffers():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().line(np.arange(n, dtype=np.float64), np.full(n, np.nan, dtype=np.float64))
    spec, blob = fig.build_payload(px_width=512)
    tr = spec["traces"][0]
    assert tr["tier"] == "decimated"
    assert tr["n_points"] == n
    xbuf, _xm = _payload_col(spec, blob, tr["x"])
    ybuf, _ym = _payload_col(spec, blob, tr["y"])
    assert len(xbuf) == 0
    assert len(ybuf) == 0
    assert not np.isnan(xbuf).any()
    assert not np.isnan(ybuf).any()


def test_long_area_with_no_finite_points_ships_empty_buffers():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().area(
        np.arange(n, dtype=np.float64),
        np.full(n, np.nan, dtype=np.float64),
        base=np.zeros(n, dtype=np.float64),
    )
    spec, blob = fig.build_payload(px_width=512)
    tr = spec["traces"][0]
    assert tr["tier"] == "decimated"
    assert tr["n_points"] == n
    assert tr["n_marks"] == 0
    xbuf, _xm = _payload_col(spec, blob, tr["x"])
    ybuf, _ym = _payload_col(spec, blob, tr["y"])
    bbuf, _bm = _payload_col(spec, blob, tr["base"])
    assert len(xbuf) == 0
    assert len(ybuf) == 0
    assert len(bbuf) == 0


def test_short_line_ships_direct():
    fig = Figure().line(np.arange(100.0), np.arange(100.0))
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["tier"] == "direct"


def test_area_ships_baseline_column_and_autorange():
    fig = Figure().area([2.0, 0.0, 1.0], [4.0, 1.0, 3.0], base=[-2.0, -1.0, -3.0])
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "area"
    assert tr["tier"] == "direct"
    x, xm = _payload_col(spec, blob, tr["x"])
    base, bm = _payload_col(spec, blob, tr["base"])
    np.testing.assert_allclose(x.astype(np.float64) + xm["offset"], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(base.astype(np.float64) + bm["offset"], [-1.0, -3.0, -2.0])
    assert spec["y_axis"]["range"][0] < -3.0
    assert spec["y_axis"]["range"][1] > 4.0


def test_histogram_ships_rect_columns():
    fig = Figure().histogram([0.1, 0.2, 1.2, 2.4, np.nan], bins=[0.0, 1.0, 2.0, 3.0])
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "histogram"
    assert tr["tier"] == "direct"
    assert tr["n_points"] == 5
    assert tr["n_marks"] == 3
    x0, x0m = _payload_col(spec, blob, tr["x0"])
    x1, x1m = _payload_col(spec, blob, tr["x1"])
    y0, y0m = _payload_col(spec, blob, tr["y0"])
    y1, y1m = _payload_col(spec, blob, tr["y1"])
    np.testing.assert_allclose(x0.astype(np.float64) + x0m["offset"], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(x1.astype(np.float64) + x1m["offset"], [1.0, 2.0, 3.0])
    np.testing.assert_allclose(y0.astype(np.float64) + y0m["offset"], [0.0, 0.0, 0.0])
    np.testing.assert_allclose(y1.astype(np.float64) + y1m["offset"], [2.0, 1.0, 1.0])
    assert spec["y_axis"]["range"][0] == 0.0


def test_histogram_constant_values_auto_expands_range():
    fig = Figure().histogram([5.0, 5.0, 5.0], bins=4)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    x0, x0m = _payload_col(spec, blob, tr["x0"])
    x1, x1m = _payload_col(spec, blob, tr["x1"])
    y1, y1m = _payload_col(spec, blob, tr["y1"])
    left = x0.astype(np.float64) + x0m["offset"]
    right = x1.astype(np.float64) + x1m["offset"]
    heights = y1.astype(np.float64) + y1m["offset"]
    assert left[0] < 5.0 < right[-1]
    assert heights.sum() == 3.0
    assert heights.max() == 3.0


def test_histogram_range_validation_rejects_bool_and_malformed_without_mutation():
    cases = [
        (lambda fig: fig.histogram([0.0, 1.0], bins=4, range=(False, 1.0)), "range\\[0\\]"),
        (lambda fig: fig.histogram([0.0, 1.0], bins="auto", range=(0.0, True)), "range\\[1\\]"),
        (lambda fig: fig.histogram([0.0, 1.0], bins=4, range=(2.0, 1.0)), "increasing"),
        (lambda fig: fig.histogram([0.0, 1.0], bins=4, range=(0.0, np.inf)), "range\\[1\\]"),
        (lambda fig: fig.histogram([0.0, 1.0], bins=4, range=(0.0,)), "exactly two"),
    ]
    for call, match in cases:
        fig = Figure()
        with pytest.raises(ValueError, match=match):
            call(fig)
        assert fig.traces == []
        assert len(fig.store) == 0


def test_statistical_chart_inputs_reject_complex_without_warning_or_mutation():
    cases = [
        lambda fig: fig.histogram(np.array([1.0 + 2.0j])),
        lambda fig: fig.bar(["a"], np.array([1.0 + 2.0j])),
        lambda fig: fig.bar(np.array([1.0 + 2.0j]), [1.0]),
        lambda fig: fig.heatmap(np.array([[1.0 + 2.0j]])),
    ]
    for build in cases:
        fig = Figure()
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            with pytest.raises(ValueError, match="real numeric"):
                build(fig)
        assert seen == []
        assert fig.traces == []
        assert len(fig.store) == 0


def test_numeric_chart_inputs_reject_boolean_without_mutation():
    cases = [
        (lambda fig: fig.line(np.array([False, True]), [0.0, 1.0]), "columns"),
        (lambda fig: fig.scatter([0.0, 1.0], np.array([True, False])), "columns"),
        (lambda fig: fig.histogram(np.array([True, False])), "histogram values"),
        (lambda fig: fig.histogram(np.array([True, None], dtype=object)), "histogram values"),
        (lambda fig: fig.bar(["a", "b"], np.array([True, False])), "bar y"),
        (lambda fig: fig.heatmap(np.array([[True, False]])), "heatmap z"),
    ]
    for build, match in cases:
        fig = Figure().line([0.0, 1.0], [1.0, 2.0], name="existing")
        before = _figure_state(fig)
        with pytest.raises(ValueError, match=match):
            build(fig)
        assert _figure_state(fig) == before


def test_failed_rect_trace_validation_does_not_mutate_store():
    fig = Figure()
    with pytest.raises(ValueError, match="equal length"):
        fig._append_rect_trace(  # noqa: SLF001 - regression for internal atomicity.
            "histogram",
            [0.0, 1.0],
            [1.0, 2.0],
            [0.0],
            [1.0],
            name=None,
            color=None,
            opacity=1.0,
            role="histogram",
        )
    assert fig.traces == []
    assert len(fig.store) == 0


def test_failed_rect_trace_canonicalization_does_not_mutate_store():
    fig = Figure()
    with pytest.raises(ValueError, match="real numeric"):
        fig._append_rect_trace(  # noqa: SLF001 - regression for internal atomicity.
            "histogram",
            [0.0, 1.0],
            ["bad", "edge"],
            [0.0, 0.0],
            [1.0, 2.0],
            name=None,
            color=None,
            opacity=1.0,
            role="histogram",
        )
    assert fig.traces == []
    assert len(fig.store) == 0


def test_histogram_late_append_failure_rolls_back_state(monkeypatch):
    fig = Figure().line([0.0, 1.0], [1.0, 2.0])
    before = _figure_state(fig)

    def fail_append(*args, **kwargs):
        del args, kwargs
        raise ValueError("synthetic histogram append failure")

    monkeypatch.setattr(fig, "_append_rect_trace", fail_append)

    with pytest.raises(ValueError, match="synthetic histogram append failure"):
        fig.histogram([0.0, 0.25, 0.5, 0.75], bins=2)

    assert _figure_state(fig) == before


def test_sorted_line_late_ingest_failure_preserves_existing_figure_state(monkeypatch):
    fig = Figure().line([0.0, 1.0], [1.0, 2.0], name="existing")
    before = _figure_state(fig)
    original = fig.store.ingest
    calls = {"count": 0}

    def flaky_ingest(values):
        calls["count"] += 1
        if calls["count"] == 3:
            raise ValueError("synthetic sorted line ingest failure")
        return original(values)

    monkeypatch.setattr(fig.store, "ingest", flaky_ingest)

    with pytest.raises(ValueError, match="synthetic sorted line ingest failure"):
        fig.line([2.0, 0.0, 1.0], [20.0, 0.0, 10.0], name="new")

    assert _figure_state(fig) == before
    spec, _blob = fig.build_payload()
    assert [trace["name"] for trace in spec["traces"]] == ["existing"]


def test_area_late_base_ingest_failure_preserves_existing_figure_state(monkeypatch):
    fig = Figure().area([0.0, 1.0], [1.0, 2.0], name="existing")
    before = _figure_state(fig)
    original = fig.store.ingest
    calls = {"count": 0}

    def flaky_ingest(values):
        calls["count"] += 1
        if calls["count"] == 3:
            raise ValueError("synthetic area base ingest failure")
        return original(values)

    monkeypatch.setattr(fig.store, "ingest", flaky_ingest)

    with pytest.raises(ValueError, match="synthetic area base ingest failure"):
        fig.area([0.0, 1.0], [3.0, 4.0], base=[0.0, 0.0], name="new")

    assert _figure_state(fig) == before
    spec, _blob = fig.build_payload()
    assert [trace["name"] for trace in spec["traces"]] == ["existing"]


def test_rect_trace_midpoint_avoids_large_domain_overflow():
    x0 = np.array([1.0e308], dtype=np.float64)
    x1 = np.array([np.nextafter(1.0e308, np.inf)], dtype=np.float64)
    fig = Figure()
    fig._append_rect_trace(  # noqa: SLF001 - regression for shared rectangle primitive.
        "histogram",
        x0,
        x1,
        [0.0],
        [1.0],
        name=None,
        color=None,
        opacity=1.0,
        role="histogram",
    )
    assert np.isfinite(fig.traces[0].x.values).all()


def test_bar_with_categories_sets_category_axis():
    fig = Figure().bar(["gold", "silver", "bronze"], [3.0, 2.0, 1.0], name="medals")
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "bar"
    assert tr["name"] == "medals"
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["gold", "silver", "bronze"]
    assert spec["x_axis"]["range"][0] < -0.39
    assert spec["x_axis"]["range"][1] > 2.39
    assert spec["y_axis"]["range"][0] == 0.0
    assert spec["y_axis"]["range"][1] > 3.0
    bar, pos, value0, value1 = _bar_payload(spec, blob, tr)
    assert bar["orientation"] == "vertical"
    assert bar["width"] == pytest.approx(0.8)
    np.testing.assert_allclose(pos, [0.0, 1.0, 2.0])
    np.testing.assert_allclose(value0, [0.0, 0.0, 0.0])
    np.testing.assert_allclose(value1, [3.0, 2.0, 1.0])


def test_bar_category_axis_normalizes_missing_and_bytes_labels():
    labels = np.array(["b", None, np.bytes_("a"), np.nan], dtype=object)
    fig = Figure().bar(labels, [1.0, 2.0, 3.0, 4.0])
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["b", "(missing)", "a"]
    json.dumps(spec)
    _bar, pos, _value0, value1 = _bar_payload(spec, blob, tr)
    np.testing.assert_allclose(pos, [0.0, 1.0, 2.0, 1.0])
    np.testing.assert_allclose(value1, [1.0, 2.0, 3.0, 4.0])


def test_bool_category_axes_remain_label_like():
    fig = Figure().bar(np.array([True, False]), [1.0, 2.0])
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]

    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["True", "False"]
    _bar, pos, _value0, value1 = _bar_payload(spec, blob, tr)
    np.testing.assert_allclose(pos, [0.0, 1.0])
    np.testing.assert_allclose(value1, [1.0, 2.0])


def test_column_alias_and_negative_bars_range_from_baseline():
    fig = Figure().column([0.0, 1.0], [2.0, -3.0], base=1.0)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "column"
    bar, pos, value0, value1 = _bar_payload(spec, blob, tr)
    assert bar["orientation"] == "vertical"
    np.testing.assert_allclose(pos, [0.0, 1.0])
    np.testing.assert_allclose(value0, [1.0, 1.0])
    np.testing.assert_allclose(value1, [3.0, -2.0])
    assert spec["y_axis"]["range"][0] < -2.0
    assert spec["y_axis"]["range"][1] > 3.0


def test_positive_bar_and_histogram_baselines_touch_value_axis():
    bar_spec, _bar_blob = Figure().bar(["A", "B"], [2.0, 4.0]).build_payload()
    hist_spec, _hist_blob = Figure().histogram([0.0, 0.1, 0.2], bins=2).build_payload()
    assert bar_spec["y_axis"]["range"][0] == 0.0
    assert hist_spec["y_axis"]["range"][0] == 0.0


def test_negative_horizontal_bar_baseline_touches_value_axis():
    spec, _blob = Figure().bar(["A", "B"], [-2.0, -4.0], orientation="horizontal").build_payload()
    assert spec["x_axis"]["range"][0] < -4.0
    assert spec["x_axis"]["range"][1] == 0.0


def test_grouped_bar_2d_values_create_one_trace_per_series():
    y = np.array([[1.0, 2.0], [3.0, 4.0]])
    fig = Figure().bar(
        ["Q1", "Q2"],
        y,
        width=0.8,
        series=["actual", "plan"],
        colors=["#111111", "#222222"],
    )
    spec, blob = fig.build_payload()
    assert len(spec["traces"]) == 2
    assert [t["name"] for t in spec["traces"]] == ["actual", "plan"]
    assert [t["style"]["color"] for t in spec["traces"]] == ["#111111", "#222222"]
    assert spec["x_axis"]["categories"] == ["Q1", "Q2"]
    tr0, tr1 = spec["traces"]
    bar0, pos0, base0, val0 = _bar_payload(spec, blob, tr0)
    bar1, pos1, base1, val1 = _bar_payload(spec, blob, tr1)
    assert bar0["width"] == pytest.approx(0.4)
    assert bar1["width"] == pytest.approx(0.4)
    np.testing.assert_allclose(pos0, [-0.2, 0.8])
    np.testing.assert_allclose(pos1, [0.2, 1.2])
    np.testing.assert_allclose(base0, [0.0, 0.0])
    np.testing.assert_allclose(base1, [0.0, 0.0])
    np.testing.assert_allclose(val0, [1.0, 2.0])
    np.testing.assert_allclose(val1, [3.0, 4.0])


def test_grouped_bar_accepts_category_major_matrix():
    y = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])  # categories x series
    fig = Figure().bar(["Q1", "Q2", "Q3"], y, series=["actual", "plan"])
    spec, blob = fig.build_payload()
    _bar0, _pos0, _base0, val0 = _bar_payload(spec, blob, spec["traces"][0])
    _bar1, _pos1, _base1, val1 = _bar_payload(spec, blob, spec["traces"][1])
    np.testing.assert_allclose(val0, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(val1, [10.0, 20.0, 30.0])


def test_stacked_bar_handles_positive_and_negative_series():
    y = np.array([[2.0, -1.0], [3.0, -4.0], [-1.0, 2.0]])
    fig = Figure().bar(["A", "B"], y, mode="stacked", series=["one", "two", "three"])
    spec, blob = fig.build_payload()
    assert [t["style"]["role"] for t in spec["traces"]] == [
        "bar-stacked",
        "bar-stacked",
        "bar-stacked",
    ]
    _bar1, _pos1, base1, val1 = _bar_payload(spec, blob, spec["traces"][1])
    np.testing.assert_allclose(base1, [2.0, -1.0])
    np.testing.assert_allclose(val1, [5.0, -5.0])
    _bar2, _pos2, base2, val2 = _bar_payload(spec, blob, spec["traces"][2])
    np.testing.assert_allclose(base2, [0.0, 0.0])
    np.testing.assert_allclose(val2, [-1.0, 2.0])
    assert spec["y_axis"]["range"][0] < -5.0
    assert spec["y_axis"]["range"][1] > 5.0


def test_horizontal_bar_uses_category_y_axis():
    fig = Figure().bar(["low", "high"], [10.0, 20.0], orientation="horizontal")
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert spec["y_axis"]["kind"] == "category"
    assert spec["y_axis"]["categories"] == ["low", "high"]
    assert spec["x_axis"]["kind"] == "linear"
    bar, pos, value0, value1 = _bar_payload(spec, blob, tr)
    assert bar["orientation"] == "horizontal"
    assert bar["width"] == pytest.approx(0.8)
    np.testing.assert_allclose(pos, [0.0, 1.0])
    np.testing.assert_allclose(value0, [0.0, 0.0])
    np.testing.assert_allclose(value1, [10.0, 20.0])


def test_bar_2d_validation_errors():
    with pytest.raises(ValueError, match="mode"):
        Figure().bar(["a"], [[1.0]], mode="overlay")
    with pytest.raises(ValueError, match="orientation"):
        Figure().bar(["a"], [1.0], orientation="diagonal")
    with pytest.raises(ValueError, match="series"):
        Figure().bar(["a"], [[1.0], [2.0]], series=["one"])
    with pytest.raises(ValueError, match="colors"):
        Figure().bar(["a"], [[1.0], [2.0]], colors=["#111111"])


def test_column_validation_errors_name_column_api():
    with pytest.raises(ValueError, match="column mode"):
        Figure().column(["a"], [[1.0]], mode="overlay")
    with pytest.raises(ValueError, match="column orientation"):
        Figure().column(["a"], [1.0], orientation="diagonal")


def test_bar_length_mismatch_raises():
    with pytest.raises(ValueError, match="equal length"):
        Figure().bar(["a", "b"], [1.0])


def test_failed_bar_does_not_register_category_labels():
    fig = Figure()
    with pytest.raises(ValueError, match="equal length"):
        fig.bar(["bad", "labels"], [1.0])
    fig.bar(["good"], [2.0])
    spec, _blob = fig.build_payload()
    assert spec["x_axis"]["categories"] == ["good"]


def test_failed_bar_preserves_existing_figure_state():
    fig = Figure().bar(["existing"], [1.0])
    cases = [
        (lambda f: f.bar(["new"], [[1.0], [2.0]], series=["only"]), "series"),
        (lambda f: f.bar(["new"], [[1.0], [2.0]], colors=["#111111"]), "colors"),
        (lambda f: f.bar(["new"], [1.0], base=[0.0, 1.0]), "bar base"),
        (lambda f: f.bar(["new", "extra"], [[1.0], [2.0], [3.0]]), "2-D y"),
    ]
    for call, match in cases:
        before = _figure_state(fig)
        with pytest.raises(ValueError, match=match):
            call(fig)
        assert _figure_state(fig) == before
    spec, _blob = fig.build_payload()
    assert spec["x_axis"]["categories"] == ["existing"]


def test_grouped_bar_late_append_failure_rolls_back_state(monkeypatch):
    fig = Figure().bar(["existing"], [1.0])
    before = _figure_state(fig)
    original = Figure._append_rect_trace
    calls = {"count": 0}

    def flaky_append(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise ValueError("synthetic append failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Figure, "_append_rect_trace", flaky_append)

    with pytest.raises(ValueError, match="synthetic append failure"):
        fig.bar(["new"], [[1.0], [2.0]], mode="grouped")

    assert _figure_state(fig) == before
    spec, _blob = fig.build_payload()
    assert spec["x_axis"]["categories"] == ["existing"]


def test_heatmap_ships_compact_grid_and_continuous_color():
    z = np.array([[1.0, 2.0, np.nan], [3.0, 4.0, 5.0]])
    fig = Figure().heatmap(
        z,
        x=["low", "mid", "high"],
        y=["north", "south"],
        name="intensity",
        colormap="magma",
    )
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "heatmap"
    assert tr["n_points"] == 6
    assert tr["n_marks"] == 6
    assert tr["color"]["mode"] == "continuous"
    assert tr["color"]["colormap"] == "magma"
    assert tr["heatmap"]["w"] == 3
    assert tr["heatmap"]["h"] == 2
    assert tr["heatmap"]["x_range"] == [-0.5, 2.5]
    assert tr["heatmap"]["y_range"] == [-0.5, 1.5]
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["low", "mid", "high"]
    assert spec["y_axis"]["kind"] == "category"
    assert spec["y_axis"]["categories"] == ["north", "south"]
    grid, _ = _payload_col(spec, blob, tr["heatmap"]["buf"])
    np.testing.assert_allclose(grid[[0, 1, 3, 4, 5]], [0.0, 0.25, 0.5, 0.75, 1.0])
    assert np.isnan(grid[2])


def test_heatmap_category_axis_normalizes_missing_and_bytes_labels():
    fig = Figure().heatmap(
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        x=np.array([np.bytes_("mon"), None, "fri"], dtype=object),
        y=np.array(["north", np.nan], dtype=object),
    )
    spec, _blob = fig.build_payload()
    tr = spec["traces"][0]
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["mon", "(missing)", "fri"]
    assert spec["y_axis"]["kind"] == "category"
    assert spec["y_axis"]["categories"] == ["north", "(missing)"]
    assert tr["heatmap"]["x_range"] == [-0.5, 2.5]
    assert tr["heatmap"]["y_range"] == [-0.5, 1.5]
    json.dumps(spec)


def test_heatmap_numeric_centers_infer_edges():
    fig = Figure().heatmap([[1.0, 2.0]], x=[10.0, 14.0], y=[5.0])
    spec, _blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["heatmap"]["x_range"] == [8.0, 16.0]
    assert tr["heatmap"]["y_range"] == [4.5, 5.5]
    assert spec["x_axis"]["range"][0] < 8.0
    assert spec["x_axis"]["range"][1] > 16.0


def test_heatmap_constant_values_auto_expands_domain():
    fig = Figure().heatmap([[7.0, 7.0], [7.0, 7.0]])
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["heatmap"]["domain"][0] < 7.0 < tr["heatmap"]["domain"][1]
    grid, _ = _payload_col(spec, blob, tr["heatmap"]["buf"])
    np.testing.assert_allclose(grid, [0.5, 0.5, 0.5, 0.5])


def test_heatmap_validation_errors():
    with pytest.raises(ValueError, match="2-D"):
        Figure().heatmap([1.0, 2.0])
    with pytest.raises(ValueError, match="length 2"):
        Figure().heatmap([[1.0, 2.0]], x=[1.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        Figure().heatmap([[1.0, 2.0]], x=[1.0, 1.0])
    with pytest.raises(ValueError, match="domain"):
        Figure().heatmap([[1.0]], domain=(2.0, 1.0))


def test_heatmap_domain_validation_rejects_bool_and_malformed_without_mutation():
    cases = [
        (lambda fig: fig.heatmap([[1.0]], domain=(False, 1.0)), "domain\\[0\\]"),
        (lambda fig: fig.heatmap([[1.0]], domain=(0.0, np.bool_(True))), "domain\\[1\\]"),
        (lambda fig: fig.heatmap([[1.0]], domain=(0.0, np.inf)), "domain\\[1\\]"),
        (lambda fig: fig.heatmap([[1.0]], domain=(1.0, 1.0)), "increasing"),
        (lambda fig: fig.heatmap([[1.0]], domain=(0.0,)), "exactly two"),
    ]
    for call, match in cases:
        fig = Figure()
        with pytest.raises(ValueError, match=match):
            call(fig)
        assert fig.traces == []
        assert len(fig.store) == 0
        assert fig._axis_categories == {}


def test_heatmap_duplicate_normalized_categories_raise_clear_error_without_mutating_axis():
    fig = Figure()
    with pytest.raises(ValueError, match="heatmap x categories must be unique"):
        fig.heatmap([[1.0, 2.0]], x=[None, np.nan])
    fig.bar(["ok"], [1.0])
    spec, _blob = fig.build_payload()
    assert spec["x_axis"]["categories"] == ["ok"]


def test_failed_heatmap_axis_order_does_not_register_new_categories():
    fig = Figure().bar(["b"], [1.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        fig.heatmap([[1.0, 2.0]], x=["a", "b"])
    fig.bar(["c"], [2.0])
    spec, _blob = fig.build_payload()
    assert spec["x_axis"]["categories"] == ["b", "c"]


def test_failed_heatmap_preserves_existing_figure_state():
    fig = Figure().heatmap([[1.0, 2.0]], x=["existing", "safe"], y=["row"])
    cases = [
        (lambda f: f.heatmap([[1.0, 2.0]], x=[None, np.nan]), "categories"),
        (lambda f: f.heatmap([[1.0, 2.0]], x=["new"]), "length 2"),
        (lambda f: f.heatmap([[1.0, 2.0]], x=[2.0, 1.0]), "strictly increasing"),
        (lambda f: f.heatmap([[1.0, 2.0]], x=["new", "ok"], domain=(0.0, np.inf)), "domain"),
    ]
    for call, match in cases:
        before = _figure_state(fig)
        with pytest.raises(ValueError, match=match):
            call(fig)
        assert _figure_state(fig) == before
    spec, _blob = fig.build_payload()
    assert spec["x_axis"]["categories"] == ["existing", "safe"]
    assert spec["y_axis"]["categories"] == ["row"]


def test_heatmap_late_ingest_failure_rolls_back_axis_categories(monkeypatch):
    fig = Figure().bar(["existing"], [1.0])
    before = _figure_state(fig)

    def fail_ingest(_values):
        raise ValueError("synthetic ingest failure")

    monkeypatch.setattr(fig.store, "ingest", fail_ingest)

    with pytest.raises(ValueError, match="synthetic ingest failure"):
        fig.heatmap([[1.0, 2.0]], x=["new", "labels"], y=["row"])

    assert _figure_state(fig) == before


def test_scatter_rejects_invalid_size_scalars():
    with pytest.raises(ValueError, match="size"):
        Figure().scatter([0.0], [0.0], size=-1.0)
    with pytest.raises(ValueError, match="size"):
        Figure().scatter([0.0], [0.0], size=np.inf)


def test_figure_dimensions_are_strict_positive_integer_pixels_or_full_percent():
    assert Figure(width=np.int64(640), height=np.int32(320)).width == 640
    assert Figure(width="100%", height="100%").height == "100%"

    bad = [
        {"width": 0},
        {"height": -1},
        {"width": True},
        {"height": np.bool_(False)},
        {"width": 640.0},
        {"height": np.nan},
        {"width": "50vw"},
    ]
    for kwargs in bad:
        with pytest.raises(ValueError, match="positive integer pixel count"):
            Figure(**kwargs)


def test_figure_text_metadata_is_string_or_none() -> None:
    assert Figure(title=None, x_label="x", y_label="y").x_label == "x"

    bad = [
        ({"title": 123}, "title"),
        ({"x_label": True}, "x_label"),
        ({"y_label": np.nan}, "y_label"),
    ]
    for kwargs, match in bad:
        with pytest.raises(ValueError, match=rf"{match} must be a string or None"):
            Figure(**kwargs)


def test_trace_names_are_string_or_none_without_mutating_figure() -> None:
    cases = [
        (lambda fig: fig.line([0.0], [1.0], name=123), "line name"),
        (lambda fig: fig.scatter([0.0], [1.0], name=True), "scatter name"),
        (lambda fig: fig.area([0.0], [1.0], name=object()), "area name"),
        (lambda fig: fig.histogram([1.0, 2.0], name=123), "histogram name"),
        (lambda fig: fig.bar(["a"], [1.0], name=False), "bar name"),
        (lambda fig: fig.column(["a"], [1.0], name=123), "column name"),
        (lambda fig: fig.heatmap([[1.0]], name=123), "heatmap name"),
        (lambda fig: fig.bar(["a"], [[1.0], [2.0]], series=["ok", 2]), r"series\[1\]"),
    ]
    for build, match in cases:
        fig = Figure().line([0.0, 1.0], [1.0, 2.0], name="existing")
        before = _figure_state(fig)
        with pytest.raises(ValueError, match=match):
            build(fig)
        assert _figure_state(fig) == before


def test_style_scalars_reject_bad_values_without_mutating_figure():
    cases = [
        (lambda fig: fig.line([0.0], [0.0], width=np.inf), "line width"),
        (lambda fig: fig.line([0.0], [0.0], opacity=1.5), "line opacity"),
        (lambda fig: fig.scatter([0.0], [0.0], opacity=-0.1), "scatter opacity"),
        (lambda fig: fig.scatter([0.0], [0.0], density="yes"), "scatter density"),
        (lambda fig: fig.area([0.0], [1.0], base=True), "area base"),
        (lambda fig: fig.area([0.0], [1.0], line_width=True), "area line_width"),
        (lambda fig: fig.area([0.0], [1.0], line_opacity=np.nan), "area line_opacity"),
        (lambda fig: fig.histogram([1.0, 2.0], density=1), "histogram density"),
        (lambda fig: fig.histogram([1.0, 2.0], opacity=True), "histogram opacity"),
        (lambda fig: fig.bar(["a"], [1.0], width=True), "bar width"),
        (lambda fig: fig.bar(["a"], [1.0], opacity=1.1), "bar opacity"),
        (lambda fig: fig.heatmap([[1.0]], opacity=-0.1), "heatmap opacity"),
    ]
    for call, match in cases:
        fig = Figure()
        with pytest.raises(ValueError, match=match):
            call(fig)
        assert fig.traces == []
        assert len(fig.store) == 0
        assert fig._axis_categories == {}


def test_valid_style_numpy_scalars_ship_standard_json():
    fig = Figure(width=np.int64(640), height=np.int64(320)).line(
        [0.0, 1.0],
        [1.0, 2.0],
        width=np.float32(2.5),
        opacity=np.float64(0.5),
    )
    spec, _blob = fig.build_payload()
    assert spec["width"] == 640
    assert spec["height"] == 320
    assert spec["traces"][0]["style"]["width"] == pytest.approx(2.5)
    assert spec["traces"][0]["style"]["opacity"] == pytest.approx(0.5)
    json.dumps(spec, allow_nan=False)


def test_inline_json_export_rejects_nan_and_infinity():
    with pytest.raises(ValueError, match=r"finite JSON.*NaN or infinity"):
        _json_for_inline_script({"bad": np.nan})
    with pytest.raises(ValueError, match=r"finite JSON.*NaN or infinity"):
        _json_for_inline_script({"bad": np.inf})


def test_inline_json_export_escapes_html_hazards_without_changing_data():
    payload = {
        "title": "</script><script>alert(1)</script>&\u2028\u2029",
        "nested": ["<tag attr='x'>", "Fish & Chips", "\u2028line", "\u2029para"],
    }

    literal = _json_for_inline_script(payload)

    assert json.loads(literal) == payload
    assert "<" not in literal
    assert ">" not in literal
    assert "&" not in literal
    assert "\u2028" not in literal
    assert "\u2029" not in literal
    assert "\\u003c/script\\u003e" in literal
    assert "\\u003cscript" in literal
    assert "\\u0026" in literal
    assert "\\u2028" in literal
    assert "\\u2029" in literal


def test_inline_javascript_export_escapes_closing_script():
    js = 'const label = "</script><img src=x onerror=alert(1)>";'

    escaped = _javascript_for_inline_script(js)

    assert "</script><img" not in escaped
    assert "<\\/script><img src=x onerror=alert(1)>" in escaped


def test_to_html_escapes_closing_script_inside_bundled_client(monkeypatch):
    def hostile_bundle(which: str) -> str:
        assert which == "standalone"
        return (
            "window.fastcharts = { renderStandalone() {} };\n"
            'const userLikeFixture = "</script><img src=x onerror=alert(1)>";'
        )

    monkeypatch.setattr(export_module, "_bundled_js", hostile_bundle)

    html = Figure().line([0.0, 1.0], [1.0, 2.0]).to_html()
    body = html.split("<body>", 1)[1]

    assert body.count("</script>") == 2
    assert "</script><img" not in body
    assert "<\\/script><img src=x onerror=alert(1)>" in body


def test_to_html_includes_defensive_csp_before_scripts():
    html = Figure(title="csp").line([0.0, 1.0], [1.0, 2.0]).to_html()
    head = html.split("</head>", 1)[0]

    assert 'http-equiv="Content-Security-Policy"' in head
    assert f'content="{export_module._STANDALONE_CSP}"' in head
    assert head.index("Content-Security-Policy") < html.index("<script>")
    assert "default-src 'none'" in head
    assert "script-src 'unsafe-inline'" in head
    assert "connect-src 'none'" in head
    assert "base-uri 'none'" in head


def test_to_html_escapes_every_chart_text_surface():
    evil = "</script><svg onload=alert(1)>&\u2028\u2029"
    also_evil = "<b data-x='1'>&</b>"
    fig = Figure(title=evil, x_label=evil, y_label=also_evil)
    fig.line([0.0, 1.0], [1.0, 2.0], name=evil)
    fig.scatter(
        [0.0, 1.0],
        [1.0, 2.0],
        color=np.array([evil, also_evil], dtype=object),
        name=also_evil,
    )
    fig.bar([evil, "safe"], [[1.0, 2.0], [3.0, 4.0]], series=[evil, also_evil])
    fig.heatmap([[1.0, 2.0]], x=[evil, "ok"], y=[also_evil], name=evil)

    html = fig.to_html()
    head = html.split("</head>", 1)[0]
    body = html.split("<body>", 1)[1]
    spec_literal = _inline_spec_literal(html)

    assert "&lt;/script&gt;&lt;svg onload=alert(1)&gt;&amp;" in head
    assert "</script><svg" not in body
    assert "<b data-x=" not in body
    assert "<" not in spec_literal
    assert ">" not in spec_literal
    assert "&" not in spec_literal
    assert "\u2028" not in spec_literal
    assert "\u2029" not in spec_literal
    assert "\\u003c/script\\u003e" in spec_literal
    assert "\\u0026" in spec_literal
    assert "\\u2028" in spec_literal
    assert "\\u2029" in spec_literal

    decoded = json.loads(spec_literal)
    assert decoded["title"] == evil
    assert decoded["x_axis"]["label"] == evil
    assert decoded["y_axis"]["label"] == also_evil
    names = [trace["name"] for trace in decoded["traces"]]
    assert evil in names
    assert also_evil in names
    color_categories = [
        category
        for trace in decoded["traces"]
        for category in trace.get("color", {}).get("categories", [])
    ]
    assert evil in color_categories
    assert also_evil in color_categories
    assert evil in decoded["x_axis"]["categories"]
    assert also_evil in decoded["y_axis"]["categories"]


def test_to_html_path_writes_exact_document(tmp_path: Path):
    target = tmp_path / "chart.html"
    fig = Figure(title='export "quoted" & <safe>').bar(["a", "b"], [1.0, 2.0])

    html = fig.to_html(target)

    assert target.read_text(encoding="utf-8") == html
    assert "<title>export &quot;quoted&quot; &amp; &lt;safe&gt;</title>" in html
    decoded = json.loads(_inline_spec_literal(html))
    assert decoded["title"] == 'export "quoted" & <safe>'


def test_to_html_path_keeps_existing_file_on_atomic_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "chart.html"
    target.write_text("old chart artifact", encoding="utf-8")
    fig = Figure(title="atomic export").line([0.0, 1.0], [1.0, 2.0])

    def fail_replace(src: Path, dst: Path) -> None:
        assert Path(src).name.startswith(".chart.html.")
        assert Path(dst) == target
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(export_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        fig.to_html(target)

    assert target.read_text(encoding="utf-8") == "old chart artifact"
    assert not list(tmp_path.glob(".chart.html.*.tmp"))


def test_figure_dom_slots_are_validated_before_export():
    fig = Figure().line([0.0, 1.0], [1.0, 2.0])
    fig.class_names = {"legend": "ok", "legnd": "typo"}

    with pytest.raises(ValueError, match="class_names has unknown slot"):
        fig.build_payload()

    fig.class_names = {"legend": "ok"}
    fig.chrome_styles = {"tooltip": {"background": "#111827"}, "plot": {"color": "red"}}

    with pytest.raises(ValueError, match="chrome_styles has unknown slot"):
        fig.to_html()

    fig.chrome_styles = {"tooltip": {"background": "#111827"}}
    spec, _ = fig.build_payload()

    assert spec["dom"]["class_names"] == {"legend": "ok"}
    assert spec["dom"]["styles"] == {"tooltip": {"background": "#111827"}}


def test_figure_html_alias_and_repr_use_standalone_export_path(tmp_path: Path):
    target = tmp_path / "chart-alias.html"
    fig = Figure(title="notebook html").line([0.0, 1.0], [1.0, 2.0])

    html = fig.html(target)
    repr_html = fig._repr_html_()

    assert target.read_text(encoding="utf-8") == html
    assert html.startswith("<!doctype html>")
    assert repr_html.startswith("<!doctype html>")
    assert "notebook html" in repr_html
    decoded = json.loads(_inline_spec_literal(repr_html))
    assert decoded["title"] == "notebook html"
    assert decoded["traces"][0]["kind"] == "line"


def test_to_html_path_rejects_invalid_json_metadata_without_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "bad.html"
    fig = Figure(title="bad export")

    def bad_payload():
        return {"protocol": PROTOCOL_VERSION, "bad": np.nan}, b""

    monkeypatch.setattr(fig, "build_payload", bad_payload)

    with pytest.raises(ValueError, match=r"finite JSON.*NaN or infinity"):
        fig.to_html(target)

    assert not target.exists()


def test_to_html_revalidates_mutated_text_metadata_without_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "bad-title.html"
    fig = Figure(title="ok").line([0.0, 1.0], [1.0, 2.0])
    fig.title = object()

    with pytest.raises(ValueError, match="title must be a string or None"):
        fig.to_html(target)

    assert not target.exists()


def test_build_payload_revalidates_mutated_axis_labels() -> None:
    fig = Figure(x_label="ok", y_label="still ok").line([0.0, 1.0], [1.0, 2.0])
    fig.x_label = 42

    with pytest.raises(ValueError, match="x_label must be a string or None"):
        fig.build_payload()


def test_axis_label_position_options_emit_and_revalidate() -> None:
    fig = Figure().line([0.0, 1.0], [1.0, 2.0])
    fig.set_axis(
        "x",
        label="x",
        label_position="inside_start",
        label_offset=6,
        label_angle=-8,
    )
    fig.set_axis(
        "y",
        label="y",
        label_position={"right": 12, "top": "48%", "transform": "rotate(90deg)"},
    )

    spec, _ = fig.build_payload()

    assert spec["x_axis"]["label_position"] == "inside_start"
    assert spec["x_axis"]["label_offset"] == 6.0
    assert spec["x_axis"]["label_angle"] == -8.0
    assert spec["y_axis"]["label_position"] == {
        "right": 12,
        "top": "48%",
        "transform": "rotate(90deg)",
    }

    fig.axis_options["x"]["label_position"] = "middle-ish"
    with pytest.raises(ValueError, match="label_position"):
        fig.build_payload()


def test_axis_tick_layout_options_emit_and_revalidate() -> None:
    fig = Figure().line([0.0, 1.0], [1.0, 2.0])
    fig.set_axis(
        "x",
        tick_count=5,
        tick_label_angle=-30,
        tick_label_strategy="rotate",
        tick_label_min_gap=9,
    )
    fig.set_axis("y", tick_count=4, tick_label_strategy="hide")

    spec, _ = fig.build_payload()

    assert spec["x_axis"]["tick_count"] == 5
    assert spec["x_axis"]["tick_label_angle"] == -30.0
    assert spec["x_axis"]["tick_label_strategy"] == "rotate"
    assert spec["x_axis"]["tick_label_min_gap"] == 9.0
    assert spec["y_axis"]["tick_count"] == 4
    assert spec["y_axis"]["tick_label_strategy"] == "hide"

    fig.axis_options["x"]["tick_label_strategy"] = "pile-up"
    with pytest.raises(ValueError, match="tick_label_strategy"):
        fig.build_payload()


def test_fluent_semantic_annotations_emit_marker_and_aliases() -> None:
    fig = (
        Figure()
        .scatter([1.0, 2.0], [2.0, 3.0])
        .marker(2.0, 3.0, text="peak", symbol="square")
        .label(1.0, 2.0, "start")
        .threshold(2.5)
        .threshold_zone(2.0, 3.0)
    )

    spec, _ = fig.build_payload()

    assert [annotation["kind"] for annotation in spec["annotations"]] == [
        "marker",
        "text",
        "rule",
        "band",
    ]
    assert spec["annotations"][0]["symbol"] == "square"
    assert spec["annotations"][1]["text"] == "start"
    assert spec["annotations"][2]["axis"] == "y"
    assert spec["annotations"][3]["axis"] == "y"


def test_nan_never_reaches_vertex_buffers():
    x = np.arange(1000.0)
    y = np.arange(1000.0)
    y[[10, 500, 990]] = np.nan
    fig = Figure().scatter(x, y)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    ye, _ = _payload_col(spec, blob, tr["y"])
    assert not np.isnan(ye).any()  # §19
    assert len(ye) == 997


def test_unsorted_line_sorted_at_ingest():
    x = np.array([3.0, 1.0, 2.0])
    y = np.array([30.0, 10.0, 20.0])
    fig = Figure().line(x, y)
    tr = fig.traces[0]
    np.testing.assert_array_equal(tr.x.values, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(tr.y.values, [10.0, 20.0, 30.0])


def test_column_store_dedup():
    x = np.arange(10_000.0)
    y1 = np.sin(x)
    y2 = np.cos(x)
    fig = Figure().line(x, y1).line(x, y2)
    # x ingested once: 3 columns, not 4 (§18 shared-columns).
    assert len(fig.store) == 3


def test_column_store_does_not_alias_offset_views():
    edges = np.array([0.0, 1.0, 2.0, 3.0])
    fig = Figure()
    left = fig.store.ingest(edges[:-1])
    right = fig.store.ingest(edges[1:])
    assert left.id != right.id
    np.testing.assert_array_equal(left.values, [0.0, 1.0, 2.0])
    np.testing.assert_array_equal(right.values, [1.0, 2.0, 3.0])


def test_column_store_rollback_restores_dedup_keys():
    store = ColumnStore()
    existing_data = np.arange(3.0)
    existing = store.ingest(existing_data)
    new_data = np.array([10.0, 11.0])
    checkpoint = store.checkpoint()
    staged = store.ingest(new_data)
    assert staged.id == 1
    store.rollback(checkpoint)
    assert len(store) == 1
    assert store.ingest(existing_data).id == existing.id
    fresh = store.ingest(new_data)
    assert fresh.id == 1
    np.testing.assert_array_equal(fresh.values, new_data)


def test_failed_xy_builders_do_not_mutate_store():
    fig = Figure()
    with pytest.raises(ValueError, match="equal length"):
        fig.line([0.0, 1.0], [0.0])
    assert fig.traces == []
    assert len(fig.store) == 0

    with pytest.raises(ValueError, match="size"):
        fig.scatter([0.0, 1.0], [0.0, 1.0], size=[4.0])
    assert fig.traces == []
    assert len(fig.store) == 0

    with pytest.raises(ValueError, match="area base"):
        fig.area([0.0, 1.0], [1.0, 2.0], base=[0.0])
    assert fig.traces == []
    assert len(fig.store) == 0


def test_failed_xy_and_histogram_builders_preserve_existing_figure_state():
    fig = Figure().line([0.0, 1.0], [1.0, 2.0], name="existing")
    cases = [
        (lambda f: f.line([0.0, 1.0, 2.0], [0.0, 1.0]), "equal length"),
        (lambda f: f.scatter([0.0, 1.0], [0.0, 1.0], size=[4.0]), "size"),
        (
            lambda f: f.scatter([0.0, 1.0], [0.0, 1.0], size=np.array([True, False])),
            "boolean",
        ),
        (
            lambda f: f.scatter(
                [0.0, 1.0],
                [0.0, 1.0],
                color=[1.0, 2.0],
                colormap="not-a-map",
            ),
            "colormap",
        ),
        (
            lambda f: f.scatter(
                [0.0, 1.0],
                [0.0, 1.0],
                size=[1.0, 2.0],
                size_range=(2.0, np.nan),
            ),
            "size_range",
        ),
        (lambda f: f.area([0.0, 1.0], [1.0, 2.0], base=[0.0]), "area base"),
        (lambda f: f.histogram([[1.0, 2.0]]), "1-D"),
        (lambda f: f.histogram([1.0, 2.0], bins=0), "positive"),
    ]

    for call, match in cases:
        before = _figure_state(fig)
        with pytest.raises(ValueError, match=match):
            call(fig)
        assert _figure_state(fig) == before

    spec, _blob = fig.build_payload()
    assert [trace["name"] for trace in spec["traces"]] == ["existing"]


def test_trace_append_failures_preserve_existing_figure_state():
    cases = [
        lambda f: f.line([0.0, 1.0], [2.0, 3.0], name="new-line"),
        lambda f: f.scatter([0.0, 1.0], [2.0, 3.0], name="new-scatter"),
        lambda f: f.area([0.0, 1.0], [2.0, 3.0], name="new-area"),
        lambda f: f.histogram([0.0, 0.25, 0.5, 0.75], bins=2, name="new-histogram"),
    ]
    for call in cases:
        fig = Figure().line([0.0, 1.0], [1.0, 2.0], name="existing")
        fig.traces = _AppendThenRaiseList(fig.traces)
        before = _figure_state(fig)

        with pytest.raises(ValueError, match="synthetic trace append failure"):
            call(fig)

        assert _figure_state(fig) == before
        spec, _blob = fig.build_payload()
        assert [trace["name"] for trace in spec["traces"]] == ["existing"]


def test_decimate_view_recenters_offset():
    n = 100_000
    x = 1.6e12 + np.arange(n, dtype=np.float64)
    y = np.sin(np.arange(n) * 1e-3)
    fig = Figure().line(x, y)
    x0, x1 = 1.6e12 + 40_000, 1.6e12 + 41_000  # deep-zoom window
    update, buffers = fig.decimate_view(x0, x1, 512)
    assert len(update["traces"]) == 1
    upd = update["traces"][0]
    assert upd["x"]["offset"] == (x0 + x1) / 2  # §16 re-centering
    xe = np.frombuffer(buffers[upd["x"]["buf"]], dtype=np.float32)
    decoded = xe.astype(np.float64) + upd["x"]["offset"]
    assert decoded.min() >= x0 - 1
    assert decoded.max() <= x1 + 1
    # Sub-ms precision inside the window even though |x| ~ 1.6e12.
    assert np.abs(np.diff(decoded) - np.round(np.diff(decoded))).max() < 1e-3


def test_decimate_view_sends_empty_line_update_for_empty_window():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().line(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))
    update, buffers = fig.decimate_view(float(n + 10), float(n + 100), 512)
    assert len(update["traces"]) == 1
    upd = update["traces"][0]
    assert upd["x"]["len"] == 0
    assert upd["y"]["len"] == 0
    assert buffers == [b"", b""]


def test_decimate_view_updates_area_base_column():
    n = DECIMATION_THRESHOLD + 1
    x = np.arange(n, dtype=np.float64)
    y = np.sin(x * 0.01)
    base = y - 2.0
    fig = Figure().area(x, y, base=base)
    update, buffers = fig.decimate_view(200.0, 800.0, 128)
    assert len(update["traces"]) == 1
    upd = update["traces"][0]
    assert "base" in upd
    assert upd["x"]["len"] == upd["y"]["len"] == upd["base"]["len"]
    assert upd["base"]["buf"] == 2
    decoded_base = (
        np.frombuffer(buffers[upd["base"]["buf"]], dtype=np.float32).astype(np.float64)
        + upd["base"]["offset"]
    )
    assert len(decoded_base) > 0
    assert decoded_base.min() >= base.min() - 1e-3
    assert decoded_base.max() <= base.max() + 1e-3


def test_decimate_view_rejects_invalid_windows_and_screen_width():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().line(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))
    with pytest.raises(ValueError, match="view window"):
        fig.decimate_view(np.nan, 10.0, 512)
    with pytest.raises(ValueError, match="view window"):
        fig.decimate_view("left", 10.0, 512)
    with pytest.raises(ValueError, match="view window"):
        fig.decimate_view(True, 10.0, 512)
    with pytest.raises(ValueError, match="non-zero"):
        fig.decimate_view(10.0, 10.0, 512)
    with pytest.raises(ValueError, match="screen dimensions"):
        fig.decimate_view(0.0, 10.0, np.inf)
    with pytest.raises(ValueError, match="screen dimensions"):
        fig.decimate_view(0.0, 10.0, "wide")
    with pytest.raises(ValueError, match="screen dimensions"):
        fig.decimate_view(0.0, 10.0, True)


def test_decimate_view_clamps_huge_frontend_pixel_width(monkeypatch):
    from fastcharts import interaction

    n = DECIMATION_THRESHOLD * 3
    x = np.arange(n, dtype=np.float64)
    fig = Figure().line(x, np.sin(x * 0.01))
    seen_buckets = []

    def fake_m4_indices(_x, _y, _x0, _x1, n_buckets):
        seen_buckets.append(n_buckets)
        return np.empty(0, dtype=np.uint32)

    monkeypatch.setattr(interaction.kernels, "m4_indices", fake_m4_indices)
    update, buffers = fig.decimate_view(0.0, float(n), 10**12)
    tr = update["traces"][0]
    assert seen_buckets == [MAX_SCREEN_DIM]
    assert tr["x"]["len"] == 0
    assert tr["y"]["len"] == tr["x"]["len"]
    assert len(buffers[tr["x"]["buf"]]) == tr["x"]["len"] * 4


def test_autorange_from_zone_maps():
    x = np.linspace(-5, 5, 1000)
    fig = Figure().scatter(x, x * 2)
    (lo, hi) = fig.x_range()
    assert lo < -5 < 5 < hi
    (ylo, yhi) = fig.y_range()
    assert ylo < -10 < 10 < yhi


def test_memory_report_accounts_for_bytes():
    n = 100_000
    x = np.arange(n, dtype=np.float64)
    fig = Figure().scatter(x, x + 1)
    report = fig.memory_report()
    assert report["canonical_bytes"] == 2 * n * 8
    # Direct scatter transport: 8 bytes/point (x,y f32) — the §2 target's payload.
    assert report["transport_bytes_per_point"] == pytest.approx(8.0)


def test_histogram_memory_report_uses_source_count_not_bin_count():
    values = np.arange(1000.0)
    fig = Figure().histogram(values, bins=10)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["n_points"] == 1000
    assert tr["n_marks"] == 10
    report = fig.memory_report()
    assert report["transport_bytes_per_point"] == pytest.approx(len(blob) / 1000)


def test_scatter_soft_ceiling_warns():
    n = 2_000_001
    x = np.zeros(n)
    with pytest.warns(RuntimeWarning, match="soft ceiling"):
        Figure().scatter(x, x)


def test_to_html_standalone():
    fig = Figure(title="export").line(np.arange(100.0), np.arange(100.0))
    html = fig.to_html()
    assert "renderStandalone" in html
    assert "webgl2" in html or "fastcharts" in html
    assert "margin:24px" not in html
    assert "html,body{margin:0" in html


def test_responsive_size_in_spec():
    # width/height="100%" ride the spec verbatim; the client measures the
    # container and re-requests decimation/density at the new pixel size.
    x = np.arange(10.0)
    fig = Figure(width="100%", height="100%").scatter(x, x)
    spec, _ = fig.build_payload()
    assert spec["width"] == "100%"
    assert spec["height"] == "100%"
    json.dumps(spec)  # still plain JSON


def test_responsive_size_rejects_other_strings():
    with pytest.raises(ValueError, match="width"):
        Figure(width="50vw")
    with pytest.raises(ValueError, match="height"):
        Figure(height="50vh")


def test_huge_magnitudes_encode_finite():
    # §19: finite f64 must never overflow to ±inf in an f32 vertex buffer.
    # 1e300-magnitude domains ship with an f32-safe scale (found by the
    # Hypothesis suite: x=[0, 1e300] encoded y to -inf).
    fig = Figure().line(np.array([0.0, 1e300]), np.array([-1e300, 1e300]))
    spec, blob = fig.build_payload()
    for c in spec["columns"]:
        if "offset" not in c:
            continue
        enc = np.frombuffer(blob, np.float32, count=c["len"], offset=c["byte_offset"])
        assert np.isfinite(enc).all(), "encoded geometry must stay finite"
        # decode round-trips to the original magnitude (f32-relative accuracy)
        dec = enc.astype(np.float64) / c["scale"] + c["offset"]
        assert np.isfinite(dec).all()


def test_normal_magnitudes_keep_unit_scale():
    # The common path is unchanged: normal domains still ship scale == 1.0.
    fig = Figure().line(np.arange(100.0), np.sin(np.arange(100.0)))
    spec, _ = fig.build_payload()
    scales = [c["scale"] for c in spec["columns"] if "scale" in c]
    assert scales and all(s == 1.0 for s in scales)


def test_to_png_full_path(tmp_path):
    # End-to-end Figure.to_png: needs a Chromium binary; skip cleanly without
    # one (the mechanism itself is covered dependency-free by png_export_smoke).
    from fastcharts import export

    if export.find_chromium() is None:
        pytest.skip("no chromium for PNG export")
    fig = Figure(width=320, height=200).line(np.arange(50.0), np.sin(np.arange(50.0)))
    out = tmp_path / "chart.png"
    data = fig.to_png(str(out))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert out.read_bytes() == data
    # 320x200 at default scale=2 -> 640x400
    import struct

    w, h = struct.unpack(">II", data[16:24])
    assert (w, h) == (640, 400)


def test_find_chromium_checks_standard_macos_app_paths(monkeypatch):
    from fastcharts import export

    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.delenv("FASTCHARTS_CHROMIUM", raising=False)
    monkeypatch.setattr(export.shutil, "which", lambda _name: None)
    monkeypatch.setattr(export.Path, "exists", lambda path: str(path) == chrome)

    assert export.find_chromium() == chrome


def test_to_png_missing_chromium_is_clear(monkeypatch):
    # Without a browser, the error names the fix (mirrors plotly needing kaleido)
    # and never silently returns bad bytes.
    from fastcharts import export

    monkeypatch.setattr(export, "find_chromium", lambda explicit=None: None)
    fig = Figure(width=200, height=150).scatter(np.arange(5.0), np.arange(5.0))
    with pytest.raises(RuntimeError, match="Chromium"):
        fig.to_png()


def test_to_png_rejects_bad_export_geometry_before_chromium_lookup(monkeypatch):
    from fastcharts import export

    def fail_lookup(explicit=None):
        del explicit
        raise AssertionError("Chromium lookup should not run for invalid PNG export options")

    monkeypatch.setattr(export, "find_chromium", fail_lookup)
    fig = Figure(width="100%", height="100%").line([0.0, 1.0], [1.0, 2.0])
    cases = [
        ({"width": 0}, "PNG width"),
        ({"width": True}, "PNG width"),
        ({"width": "100%"}, "PNG width"),
        ({"height": -1}, "PNG height"),
        ({"scale": 0}, "PNG scale"),
        ({"scale": np.nan}, "PNG scale"),
        ({"scale": True}, "PNG scale"),
        ({"sandbox": "false"}, "PNG sandbox"),
    ]

    for kwargs, match in cases:
        with pytest.raises(ValueError, match=match):
            fig.to_png(**kwargs)


def test_html_to_png_rejects_bad_mechanism_options_before_chromium_lookup(monkeypatch):
    from fastcharts import export

    def fail_lookup(explicit=None):
        del explicit
        raise AssertionError("Chromium lookup should not run for invalid PNG export options")

    monkeypatch.setattr(export, "find_chromium", fail_lookup)
    cases = [
        ({"width": 0, "height": 200}, "PNG width"),
        ({"width": 320, "height": False}, "PNG height"),
        ({"width": 320, "height": 200, "scale": float("inf")}, "PNG scale"),
        ({"width": 320, "height": 200, "time_budget_ms": 0}, "PNG time_budget_ms"),
        ({"width": 320, "height": 200, "timeout_s": -1.0}, "PNG timeout_s"),
        ({"width": 320, "height": 200, "sandbox": 1}, "PNG sandbox"),
    ]

    for kwargs, match in cases:
        with pytest.raises(ValueError, match=match):
            export.html_to_png("<!doctype html>", **kwargs)


def test_html_to_png_uses_chromium_sandbox_by_default(monkeypatch):
    from fastcharts import export

    seen = []

    monkeypatch.setattr(export, "find_chromium", lambda explicit=None: "/fake/chrome")

    def fake_run(args, **kwargs):
        del kwargs
        seen.append(args)
        shot = next(
            arg.removeprefix("--screenshot=") for arg in args if arg.startswith("--screenshot=")
        )
        Path(shot).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return export_module.subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(export.subprocess, "run", fake_run)

    export.html_to_png("<!doctype html>", 320, 200)
    export.html_to_png("<!doctype html>", 320, 200, sandbox=False)

    assert "--no-sandbox" not in seen[0]
    assert "--no-sandbox" in seen[1]


def test_html_to_png_retries_without_sandbox_when_chromium_crashes(monkeypatch):
    from fastcharts import export

    seen = []

    monkeypatch.setattr(export, "find_chromium", lambda explicit=None: "/fake/chrome")

    def fake_run(args, **kwargs):
        del kwargs
        seen.append(args)
        if len(seen) == 2:
            shot = next(
                arg.removeprefix("--screenshot=") for arg in args if arg.startswith("--screenshot=")
            )
            Path(shot).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return export_module.subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return export_module.subprocess.CompletedProcess(args, -6, stdout="", stderr="crashed")

    monkeypatch.setattr(export.subprocess, "run", fake_run)

    data = export.html_to_png("<!doctype html>", 320, 200)

    assert data == b"\x89PNG\r\n\x1a\nfake"
    assert "--no-sandbox" not in seen[0]
    assert "--no-sandbox" in seen[1]
