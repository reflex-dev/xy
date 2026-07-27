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


def test_scatter_authored_markers_keep_distinct_renderer_specs_and_exports():
    fig, ax = plt.subplots()
    markers = (
        r"$\clubsuit$",
        [[-1, -1], [1, -1], [1, 1], [-1, -1]],
        (5, 0),
        (5, 1),
        (5, 2),
    )
    for index, marker in enumerate(markers):
        ax.scatter([index], [index], s=80, marker=marker, label=f"marker {index}")
    ax.legend()

    payload, _blob = ax._build_chart(640, 480).figure().build_payload()
    styles = [trace["style"] for trace in payload["traces"] if trace["kind"] == "scatter"]
    assert styles[0]["marker_glyph"] == "♣"
    assert styles[1]["marker_path"]["filled"] is True
    assert len(styles[1]["marker_path"]["contours"][0]) == 8
    assert len(styles[2]["marker_path"]["contours"][0]) == 12
    assert len(styles[3]["marker_path"]["contours"][0]) == 22
    assert styles[4]["marker_path"]["filled"] is False
    assert len(styles[4]["marker_path"]["contours"]) == 5
    assert (
        len({repr(style.get("marker_path") or style.get("marker_glyph")) for style in styles}) == 5
    )

    svg = ax._build_chart(640, 480).figure().to_svg()
    assert svg.count(">♣</text>") >= 2  # mark plus legend handle
    assert svg.count("<path d=") >= 8
    png = fig._to_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_authored_marker_grammar_fails_loudly_outside_bounded_contract():
    _, ax = plt.subplots()
    with pytest.raises(NotImplementedError, match="marker mathtext"):
        ax.scatter([0], [0], marker=r"$\frac{1}{2}$")
    with pytest.raises(ValueError, match="shape"):
        ax.scatter([0], [0], marker=[[0, 0, 1]])
    with pytest.raises(ValueError, match="style must be"):
        ax.scatter([0], [0], marker=(5, 7))


def test_numpy_custom_marker_vertices_do_not_require_scalar_truthiness():
    _, ax = plt.subplots()
    ax.scatter([0], [0], marker=np.asarray([[-1, -1], [1, -1], [0, 1]]))
    payload, _blob = ax._build_chart(320, 240).figure().build_payload()
    marker_path = payload["traces"][0]["style"]["marker_path"]
    assert marker_path["filled"] is True
    assert len(marker_path["contours"][0]) == 8


@pytest.mark.parametrize("method", ("axhline", "axvline"))
def test_axis_lines_render_direct_endpoint_markers(method: str):
    _, ax = plt.subplots()
    getattr(ax, method)(
        0.5,
        marker=".",
        ms=9,
        mfc="red",
        mec="black",
        mew=2,
        color="blue",
    )

    payload, _blob = ax._build_chart(640, 480).figure().build_payload()
    scatter = [trace for trace in payload["traces"] if trace["kind"] == "scatter"]
    assert len(scatter) == 1
    assert scatter[0]["style"]["symbol"] == "point"
    assert scatter[0]["color"]["color"] == "red"
    assert scatter[0]["style"]["stroke"] == "black"
    assert scatter[0]["n_marks"] == 2
