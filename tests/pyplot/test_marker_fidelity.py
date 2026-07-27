from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _raster, _svg, marks


def teardown_function():
    plt.close("all")


def test_matplotlib_marker_family_keeps_distinct_symbols_in_payload():
    fig, ax = plt.subplots()
    markers = (
        "o",
        ".",
        ",",
        "x",
        "+",
        "|",
        "_",
        "v",
        "^",
        "<",
        ">",
        "s",
        "d",
        "D",
        "P",
        "X",
    )
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
        "vertical_line",
        "horizontal_line",
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


@pytest.mark.parametrize(
    ("symbol", "expected_path"),
    (
        ("horizontal_line", '<path d="M 5 20 H 15" fill="none"'),
        ("vertical_line", '<path d="M 10 15 V 25" fill="none"'),
    ),
)
def test_svg_line_markers_have_one_point_space_orientation(
    symbol: str,
    expected_path: str,
) -> None:
    path = _svg._SYMBOL_BUILDERS[symbol](10.0, 20.0, 5.0)
    assert path == expected_path


def test_line_marker_codes_stay_aligned_across_renderers() -> None:
    root = Path(__file__).resolve().parents[2]
    chartview = (root / "js/src/50_chartview.ts").read_text(encoding="utf-8")
    shader = (root / "js/src/40_gl.ts").read_text(encoding="utf-8")
    raster = (root / "src/raster.rs").read_text(encoding="utf-8")

    assert marks._SYMBOL_CODES["horizontal_line"] == _raster._SYMBOLS["horizontal_line"] == 17
    assert marks._SYMBOL_CODES["vertical_line"] == _raster._SYMBOLS["vertical_line"] == 18
    assert "horizontal_line: 17" in chartview
    assert "vertical_line: 18" in chartview
    assert "symbol == 17 || symbol == 18" in shader
    assert "17 => (px.abs() - r).max(py.abs())" in raster
    assert "18 => px.abs().max(py.abs() - r)" in raster
