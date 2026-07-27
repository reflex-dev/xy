from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def teardown_function() -> None:
    plt.close("all")


def _shaft_display_vector(ax, quiver, index: int = 0) -> tuple[float, float]:
    metrics = ax._quiver_metrics()
    x0, y0, x1, y1 = map(np.asarray, quiver._entry["args"])
    return (
        float((x1[index] - x0[index]) * metrics["pixels_per_x"]),
        float((y1[index] - y0[index]) * metrics["pixels_per_y"]),
    )


def _shaft_display_length(ax, quiver, index: int = 0) -> float:
    return float(np.hypot(*_shaft_display_vector(ax, quiver, index)))


def _storage_to_axes_pixels(ax, x: float, y: float) -> tuple[float, float]:
    metrics = ax._quiver_metrics()
    return (
        float((x - metrics["render_xlim"][0]) * metrics["pixels_per_x"]),
        float((y - metrics["render_ylim"][0]) * metrics["pixels_per_y"]),
    )


def test_quiver_uv_and_xy_angles_live_in_distinct_coordinate_spaces() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 1)

    uv = ax.quiver(
        [5.0],
        [0.5],
        [1.0],
        [1.0],
        angles="uv",
        scale_units="dots",
        scale=0.05,
    )
    xy = ax.quiver(
        [5.0],
        [0.5],
        [1.0],
        [1.0],
        angles="xy",
        scale_units="xy",
        scale=1,
    )

    uv_dx, uv_dy = _shaft_display_vector(ax, uv)
    xy_dx, xy_dy = _shaft_display_vector(ax, xy)
    assert uv_dx == pytest.approx(uv_dy)
    assert abs(xy_dy) > 5 * abs(xy_dx)
    x0, y0, x1, y1 = map(np.asarray, xy._entry["args"])
    assert x1[0] - x0[0] == pytest.approx(1.0)
    assert y1[0] - y0[0] == pytest.approx(1.0)


def test_quiver_xy_obeys_an_inverted_axis_while_uv_stays_screen_relative() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.set_xlim(10, 0)
    ax.set_ylim(0, 1)

    uv = ax.quiver([5.0], [0.5], [1.0], [0.0], angles="uv", scale_units="dots", scale=0.05)
    xy = ax.quiver([5.0], [0.5], [1.0], [0.0], angles="xy", scale_units="xy", scale=1)

    assert _shaft_display_vector(ax, uv)[0] > 0
    assert _shaft_display_vector(ax, xy)[0] < 0


@pytest.mark.parametrize(
    ("scale_units", "expected"),
    [
        ("width", 248.0),
        ("height", 184.8),
        ("dots", 0.5),
        ("inches", 50.0),
        ("x", 24.8),
        ("y", 18.48),
    ],
)
def test_quiver_scale_units_use_the_live_axes_dimensions(scale_units: str, expected: float) -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    quiver = ax.quiver(
        [5.0],
        [5.0],
        [1.0],
        [0.0],
        angles="uv",
        scale_units=scale_units,
        scale=2,
    )

    assert _shaft_display_length(ax, quiver) == pytest.approx(expected)


def test_quiver_units_use_live_width_height_data_and_dpi_for_shaft_width() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    width = ax.quiver(
        [5.0], [5.0], [1.0], [0.0], units="width", scale_units="dots", scale=1, width=0.02
    )
    inches = ax.quiver(
        [5.0],
        [5.0],
        [1.0],
        [0.0],
        units="inches",
        scale_units="dots",
        scale=1,
        width=0.02,
    )
    x_units = ax.quiver(
        [5.0], [5.0], [1.0], [0.0], units="x", scale_units="dots", scale=1, width=0.02
    )

    assert width._entry["kwargs"]["width"] == pytest.approx(9.92)
    assert inches._entry["kwargs"]["width"] == pytest.approx(2.0)
    assert x_units._entry["kwargs"]["width"] == pytest.approx(0.992)
    assert _shaft_display_length(ax, width) == pytest.approx(_shaft_display_length(ax, inches))
    assert _shaft_display_length(ax, width) == pytest.approx(_shaft_display_length(ax, x_units))


def test_quiver_auto_scale_cancels_scale_units_constant() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    x = np.arange(12.0)
    y = np.zeros_like(x)
    u = np.linspace(0.5, 2.0, len(x))
    v = np.linspace(1.0, 0.25, len(x))
    width_scaled = ax.quiver(x, y, u, v, units="width", scale_units="width")
    inch_scaled = ax.quiver(x, y, u, v, units="width", scale_units="inches")

    for index in range(len(x)):
        assert _shaft_display_length(ax, width_scaled, index) == pytest.approx(
            _shaft_display_length(ax, inch_scaled, index)
        )


def test_quiver_display_mask_keeps_scalar_colors_aligned_with_segments() -> None:
    _fig, ax = plt.subplots()
    ax.set_xlim(-1, 2)
    ax.set_ylim(-1, 1)
    quiver = ax.quiver(
        [0.0, 1.0],
        [0.0, 0.0],
        [1.0, 1e10],
        [0.0, 0.0],
        [0.25, 0.75],
        scale_units="width",
        scale=1e20,
    )

    np.testing.assert_array_equal(quiver._entry["_quiver_valid"], [False, True])
    assert len(quiver._entry["args"][0]) == 3
    np.testing.assert_allclose(quiver._entry["kwargs"]["color"], [0.75, 0.75, 0.75])


@pytest.mark.parametrize(
    ("stride", "kwargs", "expected_scale", "expected_width_px"),
    [
        (1, {"units": "width"}, 55.12158106165288, 1.1904),
        (
            3,
            {"pivot": "middle", "units": "inches"},
            3.813712919859866,
            2.705454545454545,
        ),
        (
            1,
            {"units": "x", "pivot": "tip", "width": 0.022, "scale": 1 / 0.15},
            6.666666666666667,
            1.6,
        ),
    ],
)
def test_quiver_demo_uses_matplotlib_311_scale_and_width(
    stride: int,
    kwargs: dict[str, object],
    expected_scale: float,
    expected_width_px: float,
) -> None:
    x, y = np.meshgrid(np.arange(0, 2 * np.pi, 0.2), np.arange(0, 2 * np.pi, 0.2))
    u, v = np.cos(x), np.sin(y)
    _fig, ax = plt.subplots()
    quiver = ax.quiver(
        x[::stride, ::stride],
        y[::stride, ::stride],
        u[::stride, ::stride],
        v[::stride, ::stride],
        **kwargs,
    )

    assert quiver._entry["vector_scale"] == pytest.approx(expected_scale)
    assert quiver._entry["kwargs"]["width"] == pytest.approx(expected_width_px)


def test_quiver_simple_demo_uses_matplotlib_311_auto_scale() -> None:
    x = np.arange(-10, 10, 1)
    y = np.arange(-10, 10, 1)
    u, v = np.meshgrid(x, y)
    _fig, ax = plt.subplots()
    quiver = ax.quiver(x, y, u, v)

    assert quiver._entry["vector_scale"] == pytest.approx(275.97863477551624)
    assert quiver._entry["kwargs"]["width"] == pytest.approx(1.488)


def test_quiver_autoscale_uses_offsets_not_display_sized_arrow_tips() -> None:
    _fig, ax = plt.subplots()
    ax.quiver(
        [0.0, 1.0],
        [0.0, 1.0],
        [100.0, 100.0],
        [100.0, 100.0],
        angles="xy",
        scale_units="xy",
        scale=1,
    )

    assert ax.get_xlim() == pytest.approx((-0.05, 1.05))
    assert ax.get_ylim() == pytest.approx((-0.05, 1.05))


def test_quiver_width_units_resize_but_inch_units_remain_physical() -> None:
    lengths = {}
    widths = {}
    for figure_width in (4.0, 8.0):
        _fig, ax = plt.subplots(figsize=(figure_width, 4.0), dpi=100)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        width_units = ax.quiver([5.0], [5.0], [1.0], [0.0], scale_units="width", scale=1)
        inch_units = ax.quiver([5.0], [5.0], [1.0], [0.0], scale_units="inches", scale=1)
        lengths[figure_width] = (
            _shaft_display_length(ax, width_units),
            _shaft_display_length(ax, inch_units),
        )
        widths[figure_width] = width_units._entry["kwargs"]["width"]

    assert lengths[8.0][0] == pytest.approx(2 * lengths[4.0][0])
    assert lengths[8.0][1] == pytest.approx(lengths[4.0][1])
    assert widths[8.0] == pytest.approx(2 * widths[4.0])


def test_quiverkey_axes_coordinates_and_labelsep_are_display_space() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=200)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 20)
    quiver = ax.quiver([5.0], [10.0], [1.0], [0.0], scale_units="inches", scale=1)
    key = ax.quiverkey(
        quiver,
        0.25,
        0.75,
        1.0,
        "one",
        coordinates="axes",
        labelpos="E",
        labelsep=0.12,
    )

    _x0, _y0, x1, y1 = map(np.asarray, key._entry["args"])
    tip_x, tip_y = _storage_to_axes_pixels(ax, x1[0], y1[0])
    metrics = ax._quiver_metrics()
    assert tip_x == pytest.approx(0.25 * metrics["plot_width"])
    assert tip_y == pytest.approx(0.75 * metrics["plot_height"])
    text = ax._entries[-1]
    assert text["kwargs"]["dx"] == pytest.approx(24.0)
    assert text["kwargs"]["dy"] == 0.0
    assert text["kwargs"]["anchor"] == "start"


def test_quiverkey_figure_coordinates_use_the_actual_subplot_transform() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    quiver = ax.quiver([5.0], [5.0], [1.0], [0.0], scale_units="inches", scale=1)
    key = ax.quiverkey(
        quiver,
        0.9,
        0.9,
        1.0,
        "one",
        coordinates="figure",
        labelpos="N",
        labelsep=0.1,
    )

    x0, y0, x1, y1 = map(np.asarray, key._entry["args"])
    midpoint = ((x0[0] + x1[0]) * 0.5, (y0[0] + y1[0]) * 0.5)
    local_x, local_y = _storage_to_axes_pixels(ax, *midpoint)
    metrics = ax._quiver_metrics()
    left, bottom, _width, _height = metrics["rect"]
    absolute_x = left * metrics["figure_width"] + local_x
    absolute_y = bottom * metrics["figure_height"] + local_y
    assert absolute_x == pytest.approx(0.9 * metrics["figure_width"])
    assert absolute_y == pytest.approx(0.9 * metrics["figure_height"])
    text = ax._entries[-1]
    assert text["kwargs"]["dx"] == 0.0
    assert text["kwargs"]["dy"] == pytest.approx(10.0)
    assert text["kwargs"]["anchor"] == "middle"
