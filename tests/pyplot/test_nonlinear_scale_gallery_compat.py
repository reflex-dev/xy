"""Source-backed coverage for Matplotlib's six built-in scale examples."""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._ticker import AsinhLocator, LogitFormatter, SymmetricalLogLocator


def teardown_function() -> None:
    plt.close("all")


def _axis_payload(ax, width: int = 640, height: int = 480):
    return ax._build_chart(width, height).figure().axis_options


def test_asinh_demo_accepts_rounding_options_and_installs_source_locators() -> None:
    _, axes = plt.subplots(1, 3)
    for ax, (linear_width, base) in zip(
        axes,
        ((0.2, 2), (1.0, 0), (5.0, 10)),
        strict=True,
    ):
        ax.plot([-3.0, 0.0, 6.0], [-300.0, 0.0, 600.0])
        ax.set_yscale("asinh", linear_width=linear_width, base=base)
        assert isinstance(ax.yaxis.get_major_locator(), AsinhLocator)
        assert ax.yaxis.get_transform().linear_width == linear_width

    assert axes[0]._scale_specs["y"]["base"] == 2
    assert axes[1]._scale_specs["y"]["base"] == 0
    assert axes[2]._scale_specs["y"]["subs"] == (2, 5)


def test_aspect_loglog_uses_transformed_spans_and_exposes_adjustable() -> None:
    fig, (box, datalim) = plt.subplots(1, 2)
    box.set_xscale("log")
    box.set_yscale("log")
    box.set_xlim(1e1, 1e3)
    box.set_ylim(1e2, 1e3)
    box.set_aspect(1)

    position = box.get_position()
    figure_width, figure_height = fig.get_size_inches()
    physical_ratio = position.width * figure_width / (position.height * figure_height)
    assert physical_ratio == pytest.approx(2.0)

    datalim.set_xscale("log")
    datalim.set_yscale("log")
    datalim.set_adjustable("datalim")
    datalim.plot([1, 3, 10], [1, 9, 100], "o-")
    datalim.set_xlim(1e-1, 1e2)
    datalim.set_ylim(1e-1, 1e3)
    datalim.set_aspect(1)
    assert datalim.get_adjustable() == "datalim"
    axes = _axis_payload(datalim, 320, 480)
    assert axes["x"]["domain"][0] > 0
    assert axes["y"]["domain"][0] > 0


def test_shared_aspect_options_fail_before_mutating_axes() -> None:
    _, shared = plt.subplots(1, 2, sharex=True)
    left, right = shared
    initial = [
        (
            ax._aspect_equal,
            ax._aspect_value,
            ax._aspect_adjustable,
            getattr(ax, "_anchor", None),
        )
        for ax in shared
    ]

    with pytest.raises(NotImplementedError, match=r"set_adjustable\(share=True\)"):
        left.set_adjustable("datalim", share=True)
    assert [
        (
            ax._aspect_equal,
            ax._aspect_value,
            ax._aspect_adjustable,
            getattr(ax, "_anchor", None),
        )
        for ax in shared
    ] == initial

    with pytest.raises(NotImplementedError, match=r"set_aspect\(share=True\)"):
        left.set_aspect("equal", adjustable="datalim", anchor="SW", share=True)
    assert [
        (
            ax._aspect_equal,
            ax._aspect_value,
            ax._aspect_adjustable,
            getattr(ax, "_anchor", None),
        )
        for ax in shared
    ] == initial

    left.set_adjustable("datalim")
    assert left.get_adjustable() == "datalim"
    assert right.get_adjustable() == "box"


@pytest.mark.parametrize("axis", ["x", "y"])
def test_nonpositive_log_limit_keeps_the_previous_positive_bound(axis: str) -> None:
    _, ax = plt.subplots()
    ax.plot([1.0, 10.0], [1.0, 10.0])
    getattr(ax, f"set_{axis}scale")("log")
    before = getattr(ax, f"get_{axis}lim")()

    with pytest.warns(UserWarning, match="non-positive"):
        getattr(ax, f"set_{axis}lim")(0.0, 100.0)

    after = getattr(ax, f"get_{axis}lim")()
    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(100.0)
    ax.set_aspect("equal")
    assert np.isfinite(ax.get_position().bounds).all()


def test_nonpositive_reversed_log_limits_preserve_display_sides() -> None:
    _, ax = plt.subplots()
    ax.set_xscale("log")
    ax.set_xlim(100.0, 1.0)

    with pytest.warns(UserWarning, match="non-positive"):
        ax.set_xlim(0.0, None)
    assert ax.get_xlim() == pytest.approx((100.0, 1.0))

    with pytest.warns(UserWarning, match="non-positive"):
        ax.set_xlim(None, 0.0)
    assert ax.get_xlim() == pytest.approx((100.0, 1.0))


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("base", [0.5, 1.0, 0.0, np.nan])
def test_unsupported_log_bases_fail_at_the_scale_setter(axis: str, base: float) -> None:
    _, ax = plt.subplots()

    with pytest.raises(ValueError, match="base must be greater than 1"):
        getattr(ax, f"set_{axis}scale")("log", base=base)

    key = axis
    assert ax._scale_specs[key]["name"] == "linear"


def test_log_demo_constrained_probe_keeps_an_empty_log_domain_positive() -> None:
    _, empty = plt.subplots(layout="constrained")
    empty.set_yscale("log")
    empty_y_axis = _axis_payload(empty)["y"]
    assert empty_y_axis["domain"][0] > 0

    _, (masked, clipped) = plt.subplots(
        1,
        2,
        layout="constrained",
        figsize=(6, 3),
    )
    x = np.linspace(0.0, 2.0, 10)
    y = 10**x
    yerr = 1.75 + 0.75 * y

    masked.set_yscale("log", nonpositive="mask")
    masked.errorbar(x, y, yerr=yerr, fmt="o", capsize=5)
    clipped.set_yscale("log", nonpositive="clip")
    clipped.errorbar(x, y, yerr=yerr, fmt="o", capsize=5)

    assert masked.get_ylim()[0] > 0
    assert clipped.get_ylim()[0] > 0


def test_logit_demo_options_drive_default_ticks_and_survival_labels() -> None:
    _, ax = plt.subplots()
    x = np.linspace(-10.0, 10.0, 1000)
    probability = np.arctan(x) / np.pi + 0.5
    ax.plot(x, probability)
    ax.set_yscale("logit", one_half="1/2", use_overline=True)
    ax.set_ylim(1e-5, 1 - 1e-5)

    formatter = ax.yaxis.get_major_formatter()
    assert isinstance(formatter, LogitFormatter)
    assert formatter(0.5) == "1/2"
    assert "\N{COMBINING OVERLINE}" in formatter(0.99)
    y_axis = _axis_payload(ax)["y"]
    tick_data = ax.yaxis.get_transform().inverted().transform(y_axis["tick_values"])
    assert np.all((tick_data > 0.0) & (tick_data < 1.0))
    assert 0.5 in tick_data
    assert "1/2" in y_axis["tick_labels"]


def test_scales_overview_supports_a_static_function_scale() -> None:
    _, ax = plt.subplots()
    line = ax.plot(np.arange(5), np.linspace(0.04, 1.0, 5))[0]
    ax.set_yscale(
        "function",
        functions=(np.sqrt, np.square),
    )
    expected_ticks = np.arange(0.0, 1.2, 0.2)
    ax.set_yticks(expected_ticks)

    np.testing.assert_allclose(
        line.get_ydata(),
        np.sqrt(np.linspace(0.04, 1.0, 5)),
    )
    np.testing.assert_allclose(
        ax.yaxis.get_transform().inverted().transform([0.2, 1.0]),
        [0.04, 1.0],
    )
    np.testing.assert_allclose(ax.get_yticks(), expected_ticks)
    y_axis = _axis_payload(ax)["y"]
    assert y_axis["domain"][0] == 0
    np.testing.assert_allclose(y_axis["tick_values"], np.sqrt(expected_ticks))
    assert y_axis["tick_labels"] == ["0", "0.2", "0.4", "0.6", "0.8", "1"]


def test_symlog_demo_has_mutable_minor_locator_and_transform_metadata() -> None:
    _, ax = plt.subplots()
    ax.plot(np.linspace(-60, 60, 201), np.linspace(0, 100, 201))
    ax.set_xscale("symlog", linthresh=1)

    major = ax.xaxis.get_major_locator()
    minor = ax.xaxis.get_minor_locator()
    assert isinstance(major, SymmetricalLogLocator)
    assert isinstance(minor, SymmetricalLogLocator)
    minor.set_params(subs=[2, 3, 4, 5, 6, 7, 8, 9])
    np.testing.assert_allclose(
        major.tick_values(-60, 60),
        [-10, -1, 0, 1, 10],
    )
    minor_ticks = minor.tick_values(-60, 60)
    assert 20 in minor_ticks
    assert np.all(np.diff(minor_ticks) >= 0)
    assert ax.xaxis.get_transform().linthresh == 1
    assert ax.xaxis.get_transform().linscale == 1

    labels = _axis_payload(ax)["x"]["tick_labels"]
    assert labels == [
        "−10²",  # noqa: RUF001 - intentional Matplotlib math minus
        "−10¹",  # noqa: RUF001 - intentional Matplotlib math minus
        "−10⁰",  # noqa: RUF001 - intentional Matplotlib math minus
        "0",
        "10⁰",
        "10¹",
        "10²",
    ]
