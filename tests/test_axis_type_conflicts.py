"""Forcing a time/log/symlog type onto a categorical axis is a build error (G3).

`xy.x_axis(type_="time")` on a bar chart with string categories used to ship
`{"kind": "time", "range": [-0.45, 1.45]}` — categories gone, ticks in 1970 —
and `type_="log"` left category 0 off the axis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402


@pytest.mark.parametrize("type_", ["time", "log", "symlog"])
def test_forced_scale_on_category_axis_is_an_error(type_: str) -> None:
    chart = xy.bar_chart(xy.bar(x=["a", "b"], y=[1, 2]), xy.x_axis(type_=type_))
    with pytest.raises(ValueError, match=f"x axis is categorical .*cannot be a {type_} axis"):
        chart.figure().build_payload()


def test_forced_scale_on_numeric_axis_and_linear_on_category_axis_still_work() -> None:
    spec, _ = (
        xy.bar_chart(xy.bar(x=["a", "b"], y=[1, 2]), xy.x_axis(type_="linear"))
        .figure()
        .build_payload()
    )
    assert spec["axes"]["x"]["kind"] == "category" and spec["axes"]["x"]["categories"] == ["a", "b"]
    spec, _ = (
        xy.scatter_chart(xy.scatter(x=[1, 10, 100], y=[1, 2, 3]), xy.x_axis(type_="log"))
        .figure()
        .build_payload()
    )
    assert spec["axes"]["x"].get("scale") == "log"
    # The y axis is untouched by an x-axis conflict.
    spec, _ = (
        xy.bar_chart(xy.bar(x=["a", "b"], y=[1, 10]), xy.y_axis(type_="log"))
        .figure()
        .build_payload()
    )
    assert spec["axes"]["y"].get("scale") == "log" and spec["axes"]["x"]["kind"] == "category"


@pytest.mark.parametrize("type_", ["time", "log", "symlog"])
def test_empty_category_axis_still_rejects_forced_scale(type_: str) -> None:
    # An empty object column registers the axis as categorical with no labels.
    chart = xy.bar_chart(xy.bar(x=np.array([], dtype=object), y=[]), xy.x_axis(type_=type_))
    with pytest.raises(ValueError, match=f"x axis is categorical .*cannot be a {type_} axis"):
        chart.figure().build_payload()
