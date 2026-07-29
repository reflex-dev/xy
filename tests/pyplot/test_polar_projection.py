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


# -- review round 3: rlim semantics, claimed-subplot projection --------------


def test_set_rmax_keeps_the_centre_origin() -> None:
    """set_rmax froze the cartesian-PADDED preview as rmin: ax.set_rmax(2.0)
    shipped [0.85, 2.0] where matplotlib gives [0, 2]. The radial auto-domain
    preview now matches the engine's polar autorange."""
    plt.close("all")
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="polar")
    ax.plot([0, 1, 2, 3], [1, 2, 3, 4])
    ax.set_rmax(2.0)
    spec, _ = ax._build_chart(400, 360).figure().build_payload_split()
    assert spec["y_axis"]["range"] == [0.0, 2.0]
    assert ax.get_rmin() == 0.0
    assert ax.get_rmax() == 2.0
    plt.close("all")


def test_set_rlim_accepts_matplotlib_rmin_rmax_keywords() -> None:
    plt.close("all")
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="polar")
    ax.plot([0, 1, 2, 3], [1, 2, 3, 4])
    ax.set_rlim(rmin=0.5, rmax=2.0)
    spec, _ = ax._build_chart(400, 360).figure().build_payload_split()
    assert spec["y_axis"]["range"] == [0.5, 2.0]
    with pytest.raises(ValueError, match="either bottom or rmin"):
        ax.set_rlim(0.1, rmin=0.2)
    with pytest.raises(TypeError, match="unexpected keyword"):
        ax.set_rlim(rmax=2.0, emit=False)
    plt.close("all")


def test_subplot_projection_polar_on_a_claimed_slot() -> None:
    """`plt.subplot(111); plt.subplot(111, projection="polar")` is the
    canonical mpl idiom for re-requesting a slot as polar; it used to bounce
    off a stale pre-polar NotImplementedError in Axes.set."""
    plt.close("all")
    plt.subplot(111)
    ax = plt.subplot(111, projection="polar")
    ax.plot([0, 1, 2], [1, 2, 3])
    spec, _ = ax._build_chart(360, 320).figure().build_payload_split()
    assert spec.get("coords") == "polar"
    with pytest.raises(ValueError, match="is not supported"):
        plt.subplot(111, projection="3d")
    plt.close("all")
