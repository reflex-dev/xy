"""Object-dtype columns holding real numbers are numeric, not categorical.

A list with a `None`, an object ndarray, a CSV column read as `object`, or a
column of Decimals used to turn into a category axis with labels
'1', '(missing)', '3' at positions 0, 1, 2 — silently — while the color
channel classified the very same input as continuous. Both now apply
`channels._object_array_is_real_numeric`; missing entries become NaN (§19).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy._figure import Figure  # noqa: E402


def _x_axis(chart):
    spec, _ = chart.figure().build_payload()
    return spec["axes"]["x"]


def test_object_numeric_column_is_a_numeric_axis() -> None:
    for values in (
        [1, None, 3],
        np.array([1, 2, 3], dtype=object),
        [Decimal("1.5"), Decimal("2"), Decimal("3")],
        [1.0, float("nan"), 3.0],
    ):
        axis = _x_axis(xy.scatter_chart(xy.scatter(x=values, y=[1, 2, 3])))
        assert axis["kind"] == "linear", (values, axis)
        assert "categories" not in axis, (values, axis)


def test_object_numeric_missing_values_are_nan_not_categories() -> None:
    pd = pytest.importorskip("pandas")
    fig = Figure()
    fig.scatter(np.array([1, None, 3], dtype=object), [1.0, 2.0, 3.0])
    col = fig.traces[0].x
    assert col.kind == "float"
    assert np.isnan(col.values[1]) and col.values[0] == 1.0 and col.values[2] == 3.0
    # §29: the hole-filling pass is a copy and is reported as one, on top of
    # the object->f64 cast every object column pays.
    clean = Figure()
    clean.scatter(np.array([1, 2, 3], dtype=object), [1.0, 2.0, 3.0])
    assert col.ingest_copies == clean.traces[0].x.ingest_copies + 1
    # pandas' NA scalar is a hole too, not a category or a TypeError.
    fig2 = Figure()
    fig2.scatter(np.array([1, pd.NA, 3], dtype=object), [1.0, 2.0, 3.0])
    assert np.isnan(fig2.traces[0].x.values[1])
    # A pandas object Series of numbers with a NaN hole (the common
    # `df["x"].astype(object)` / mixed-source idiom) is numeric too.
    series = pd.Series([1, np.nan, 3], dtype=object)
    axis = _x_axis(xy.scatter_chart(xy.scatter(x=series, y=[1, 2, 3])))
    assert axis["kind"] == "linear" and "categories" not in axis


def test_strings_bools_and_mixed_object_columns_stay_categorical() -> None:
    # Bools are excluded from "real number" on purpose, so a bool-bearing
    # object column is categories too (as it was before).
    for values in (
        ["1", "2", "3"],
        ["a", None, "c"],
        [1, "a", 3],
        [b"a", b"b", b"c"],
        np.array([True, 1, 2], dtype=object),
    ):
        axis = _x_axis(xy.bar_chart(xy.bar(x=values, y=[1, 2, 3])))
        assert axis["kind"] == "category", (values, axis)


def test_axis_and_color_channel_agree_on_object_numeric_input() -> None:
    values = [1, None, 3]
    spec, _ = (
        xy.scatter_chart(xy.scatter(x=values, y=[1, 2, 3], color=values)).figure().build_payload()
    )
    assert spec["axes"]["x"]["kind"] == "linear"
    assert spec["traces"][0]["color"]["mode"] == "continuous"
