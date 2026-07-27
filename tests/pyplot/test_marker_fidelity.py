from __future__ import annotations

import io
import re

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _svg


def teardown_function():
    plt.close("all")


def test_matplotlib_marker_family_keeps_distinct_symbols_in_payload():
    fig, ax = plt.subplots()
    markers = ("o", ".", ",", "x", "+", "v", "^", "<", ">", "s", "d", "D", "P", "X")
    for index, marker in enumerate(markers):
        ax.plot([index], [index], marker=marker, linestyle="none")

    payload, _blob = ax._build_chart(640, 480).figure().build_payload()
    symbols = [
        trace["style"].get("symbol", "circle")
        for trace in payload["traces"]
        if trace["kind"] == "scatter"
    ]
    assert symbols == [
        "circle",
        "point",
        "pixel",
        "x_line",
        "plus_line",
        "triangle_down",
        "triangle",
        "triangle_left",
        "triangle_right",
        "square",
        "thin_diamond",
        "diamond",
        "cross",
        "x",
    ]

    for format in ("png", "svg"):
        output = io.BytesIO()
        fig.savefig(output, format=format)
        assert output.tell() > 100


@pytest.mark.parametrize(
    ("symbol", "expected_width"),
    (("diamond", 2**0.5 * 10), ("thin_diamond", 0.6 * 2**0.5 * 10)),
)
def test_svg_diamond_markers_match_matplotlib_path_extents(
    symbol: str, expected_width: float
) -> None:
    path = _svg._SYMBOL_BUILDERS[symbol](10.0, 20.0, 5.0)
    coordinates = np.asarray(
        [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path)]
    ).reshape(-1, 2)

    assert np.ptp(coordinates[:, 0]) == pytest.approx(expected_width, abs=0.01)
    assert np.ptp(coordinates[:, 1]) == pytest.approx(2**0.5 * 10, abs=0.01)
