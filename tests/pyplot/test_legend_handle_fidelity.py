from __future__ import annotations

import re

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _raster, _svg


def teardown_function() -> None:
    plt.close("all")


def _legend_items(ax) -> tuple[list[dict], str]:
    core = ax._build_chart(640, 480).figure()
    spec, _blob = core.build_payload()
    items = _svg.legend_items(spec["traces"])
    svg = _svg._legend(
        items,
        {"x": 0.0, "y": 0.0, "w": 400.0, "h": 200.0},
        {"style": {"background": "transparent"}},
        "plot",
    )
    return items, svg


def test_patch_legend_keeps_transparent_face_and_authored_edge(monkeypatch) -> None:
    _fig, ax = plt.subplots()
    ax.bar([0, 1], [2, 3], color="none", edgecolor="black", linewidth=2, label="outline")
    ax.legend()

    [item], svg = _legend_items(ax)
    assert item["style"]["color"] == "transparent"
    assert item["style"]["stroke"] == "black"
    assert item["style"]["stroke_width"] == pytest.approx(2.0)
    assert re.search(
        r'<rect [^>]*fill="transparent" stroke="black" stroke-width="2"/>',
        svg,
    )

    strokes = []
    monkeypatch.setattr(
        _raster._Cmd,
        "stroke",
        lambda self, points, width, color, closed=False, dash=None, cap="round": strokes.append(
            (width, color, closed, dash)
        ),
    )
    cmd = _raster._Cmd(1.0)
    _raster._emit_legend(
        cmd,
        [item],
        {"x": 0.0, "y": 0.0, "w": 400.0, "h": 200.0},
        {"style": {"background": "transparent"}},
    )
    assert (2.0, (0, 0, 0, 255), True, None) in strokes


def test_dashed_line_legend_keeps_gap_color_in_every_static_renderer(monkeypatch) -> None:
    _fig, ax = plt.subplots()
    ax.plot(
        [0, 1],
        [0, 1],
        dashes=[4, 4],
        gapcolor="tab:pink",
        color="tab:blue",
        label="alternating",
    )
    ax.legend()

    [item], svg = _legend_items(ax)
    assert item["style"]["legend_gap_color"] == "#e377c2"
    lines = re.findall(r"<line [^>]+/>", svg)
    assert 'stroke="#e377c2"' in lines[0]
    assert "stroke-dasharray" not in lines[0]
    assert 'stroke="#1f77b4"' in lines[1]
    assert 'stroke-dasharray="8.33,8.33"' in lines[1]

    strokes = []
    monkeypatch.setattr(
        _raster._Cmd,
        "stroke",
        lambda self, points, width, color, closed=False, dash=None, cap="round": strokes.append(
            (color, dash)
        ),
    )
    _raster._emit_legend(
        _raster._Cmd(1.0),
        [item],
        {"x": 0.0, "y": 0.0, "w": 400.0, "h": 200.0},
        {"style": {"background": "transparent"}},
    )
    assert strokes[:2] == [
        ((227, 119, 194, 255), None),
        ((31, 119, 180, 255), [8.3333, 8.3333]),
    ]


@pytest.mark.parametrize(
    "values",
    (
        [0.0, 0.5, 1.0],
        [0.0, np.nan, 1.0],
        np.ma.masked_array([0.0, 0.5, 1.0], mask=[False, True, False]),
    ),
)
def test_line_legend_keeps_center_marker_for_clean_nan_and_masked_data(values, monkeypatch) -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1, 2], values, "o-", color="tab:orange", label="marked")
    line.set_markersize(7)
    line.set_markerfacecolor("white")
    line.set_markeredgecolor("tab:orange")
    ax.legend()

    [item], svg = _legend_items(ax)
    marker = item["style"]["legend_marker"]
    assert marker["symbol"] == "circle"
    assert marker["color"] == "white"
    assert marker["stroke"] == "#ff7f0e"
    assert marker["size"] == pytest.approx(11.1111111111)
    assert re.search(
        r'<circle [^>]*fill="white" stroke="#ff7f0e" stroke-width="1.39"/>',
        svg,
    )

    points = []
    monkeypatch.setattr(
        _raster._Cmd,
        "point",
        lambda self, x, y, radius, symbol, fill, stroke_width, stroke: points.append(
            (radius, fill, stroke_width, stroke)
        ),
    )
    _raster._emit_legend(
        _raster._Cmd(1.0),
        [item],
        {"x": 0.0, "y": 0.0, "w": 400.0, "h": 200.0},
        {"style": {"background": "transparent"}},
    )
    assert points == [
        (
            pytest.approx(5.5555555556),
            (255, 255, 255, 255),
            pytest.approx(1.3888888889),
            (255, 127, 14, 255),
        )
    ]


def test_explicit_line_handle_legend_keeps_gap_and_marker_state() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot(
        [0, 1],
        [0, 1],
        "s--",
        gapcolor="tab:pink",
        color="tab:green",
    )
    legend = ax.legend([line], ["proxy"])
    [item] = legend.spec()["items"]

    assert item["style"]["legend_gap_color"] == "#e377c2"
    assert item["style"]["legend_marker"]["symbol"] == "square"
