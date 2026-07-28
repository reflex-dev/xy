from __future__ import annotations

import math

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")


def test_subplots_routes_polar_projection_before_axes_properties() -> None:
    fig, axes = plt.subplots(
        1,
        2,
        subplot_kw={
            "projection": "polar",
            "xticks": [0.0, math.pi / 2.0],
            "yticks": [0.5, 1.0],
        },
    )

    for ax in axes:
        ax.plot([0.0, math.pi / 2.0], [0.5, 1.0])
        assert ax._projection == "polar"

    figures = [chart.figure() for chart in fig._charts()]
    assert [figure.coords for figure in figures] == ["polar", "polar"]
    assert figures[0].axis_options["x"]["tick_values"] == pytest.approx([0.0, math.pi / 2.0])
    assert figures[0].axis_options["y"]["tick_values"] == pytest.approx([0.5, 1.0])


@pytest.mark.parametrize(
    "factory",
    [
        lambda: plt.subplot(111, projection="polar"),
        lambda: plt.figure().add_subplot(111, polar=True),
        lambda: plt.axes(projection="polar"),
        lambda: plt.axes([0.1, 0.1, 0.8, 0.8], projection="polar"),
    ],
)
def test_polar_projection_routes_through_axes_factories(factory) -> None:
    ax = factory()
    ax.plot([0.0, math.pi], [0.5, 1.0])
    assert ax._build_chart(320, 320).figure().coords == "polar"


def test_polar_options_and_supported_marks_reach_the_core_figure() -> None:
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    theta = np.linspace(0.0, 2.0 * math.pi, 9)
    radius = np.linspace(0.2, 1.0, 9)

    ax.plot(theta, radius)
    ax.scatter(theta[::2], radius[::2])
    ax.fill(theta, radius, alpha=0.2)
    ax.bar(theta[::2], radius[::2], width=0.4, bottom=0.1)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_thetagrids([0, 90, 180, 270], ["N", "E", "S", "W"])
    ax.set_rlim(0.0, 1.25)
    ax.set_rticks([0.25, 0.5, 1.0])

    core = fig._charts()[0].figure()
    spec, _buffers = core.build_payload_split()
    assert spec["coords"] == "polar"
    assert spec["x_axis"]["theta_unit"] == "radians"
    assert spec["x_axis"]["theta_zero"] == "N"
    assert spec["x_axis"]["theta_direction"] == "clockwise"
    assert spec["x_axis"]["tick_values"] == pytest.approx(
        [0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0]
    )
    assert spec["y_axis"]["range"] == pytest.approx([0.0, 1.25])
    assert spec["y_axis"]["tick_values"] == pytest.approx([0.25, 0.5, 1.0])
    assert [trace.kind for trace in core.traces] == ["line", "scatter", "area", "bar"]
