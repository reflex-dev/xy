from __future__ import annotations

import re

import numpy as np

import xy.pyplot as plt


def _gallery_field() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The scalar field shared by Matplotlib's contour gallery examples."""
    delta = 0.025
    x = np.arange(-3.0, 3.0, delta)
    y = np.arange(-2.0, 2.0, delta)
    X, Y = np.meshgrid(x, y)
    z1 = np.exp(-(X**2) - Y**2)
    z2 = np.exp(-((X - 1) ** 2) - (Y - 1) ** 2)
    return X, Y, (z1 - z2) * 2


def test_contour_demo_cycles_listed_colors_per_level_through_renderers() -> None:
    X, Y, Z = _gallery_field()
    levels = np.arange(-1.2, 1.4, 0.4)
    colors = ("r", "green", "blue", (1, 1, 0), "#afeeee", "0.5")

    _fig, ax = plt.subplots()
    contour = ax.contour(
        X,
        Y,
        Z,
        levels,
        linewidths=np.arange(0.5, 4, 0.5),
        colors=colors,
    )

    expected = np.asarray(
        [
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 128 / 255, 0.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 1.0, 0.0, 1.0],
            [175 / 255, 238 / 255, 238 / 255, 1.0],
            [128 / 255, 128 / 255, 128 / 255, 1.0],
            [1.0, 0.0, 0.0, 1.0],
        ]
    )
    np.testing.assert_allclose(contour._entry["kwargs"]["color"], expected)

    figure = ax._build_chart(640, 480).figure()
    trace = next(trace for trace in figure.traces if trace.kind == "contour")
    assert trace.color_ch is not None and trace.color_ch.mode == "direct_rgba"
    assert trace.color_ch.rgba is not None
    for rgba in expected:
        assert np.any(np.all(np.isclose(trace.color_ch.rgba, rgba), axis=1))

    svg = figure.to_svg()
    strokes = set(re.findall(r'stroke="([^"]+)', svg))
    assert {"rgb(255,0,0)", "rgb(0,128,0)", "rgb(0,0,255)"} <= strokes

    spec, blob = figure.build_payload()
    paint = next(item["color"] for item in spec["traces"] if item["kind"] == "contour")
    assert paint["mode"] == "direct_rgba"
    column = spec["columns"][paint["buf"]]
    packed = np.frombuffer(
        blob,
        dtype=np.uint8,
        count=column["len"],
        offset=column["byte_offset"],
    ).reshape(-1, 4)
    for rgba in np.rint(expected * 255).astype(np.uint8):
        assert np.any(np.all(packed == rgba, axis=1))


def test_contourf_demo_cycles_bands_and_updates_extended_colors() -> None:
    X, Y, Z = _gallery_field()
    levels = [-1.5, -1, -0.5, 0, 0.5, 1]

    _fig, ax = plt.subplots()
    contour = ax.contourf(X, Y, Z, levels, colors=("r", "g", "b"), extend="both")
    contour.cmap.set_under("yellow")
    contour.cmap.set_over("cyan")

    expected = np.asarray(
        [
            [1.0, 1.0, 0.0, 1.0],
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 128 / 255, 0.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 128 / 255, 0.0, 1.0],
            [0.0, 1.0, 1.0, 1.0],
        ]
    )
    np.testing.assert_allclose(contour._entry["kwargs"]["color"], expected)

    figure = ax._build_chart(640, 480).figure()
    heatmap = next(trace for trace in figure.traces if trace.kind == "heatmap")
    assert heatmap.style["truecolor"] is True
    assert heatmap.style["opacity"] == 1.0
    assert heatmap.rgba_grid is not None
    rendered = np.column_stack([column.values for column in heatmap.rgba_grid])
    for rgba in expected:
        assert np.any(np.all(np.isclose(rendered, rgba), axis=1))

    spec, _blob = figure.build_payload()
    shipped = next(item["heatmap"] for item in spec["traces"] if item["kind"] == "heatmap")
    assert len(shipped["rgba_bufs"]) == 4
