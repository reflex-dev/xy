"""Focused Matplotlib parity for subplot edge labels and autoscale margins."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    plt.close("all")
    yield
    plt.close("all")


def _label_every_axis(axes) -> None:
    for index, ax in enumerate(axes.flat):
        ax.set_xlabel(f"x-{index}")
        ax.set_ylabel(f"y-{index}")


def test_label_outer_keeps_only_last_row_and_first_column_labels() -> None:
    _fig, axes = plt.subplots(2, 2)
    _label_every_axis(axes)

    for ax in axes.flat:
        ax.label_outer()

    assert [ax.get_xlabel() for ax in axes.flat] == ["", "", "x-2", "x-3"]
    assert [ax.get_ylabel() for ax in axes.flat] == ["y-0", "", "y-2", ""]
    assert [ax._tick_label_sides["x"] for ax in axes.flat] == [
        {"labelbottom": False, "labeltop": False},
        {"labelbottom": False, "labeltop": False},
        {"labelbottom": True, "labeltop": False},
        {"labelbottom": True, "labeltop": False},
    ]
    assert [ax._tick_label_sides["y"] for ax in axes.flat] == [
        {"labelleft": True, "labelright": False},
        {"labelleft": False, "labelright": False},
        {"labelleft": True, "labelright": False},
        {"labelleft": False, "labelright": False},
    ]


def test_label_outer_respects_top_and_right_label_positions() -> None:
    _fig, axes = plt.subplots(2, 2)
    _label_every_axis(axes)
    for ax in axes.flat:
        ax.xaxis.set_label_position("top")
        ax.yaxis.set_label_position("right")
        ax.tick_params(
            axis="x",
            labelbottom=False,
            labeltop=True,
            bottom=False,
            top=True,
        )
        ax.tick_params(
            axis="y",
            labelleft=False,
            labelright=True,
            left=False,
            right=True,
        )
        ax.label_outer()

    assert [ax.get_xlabel() for ax in axes.flat] == ["x-0", "x-1", "", ""]
    assert [ax.get_ylabel() for ax in axes.flat] == ["", "y-1", "", "y-3"]
    assert [ax._tick_label_sides["x"]["labeltop"] for ax in axes.flat] == [
        True,
        True,
        False,
        False,
    ]
    assert [ax._tick_label_sides["y"]["labelright"] for ax in axes.flat] == [
        False,
        True,
        False,
        True,
    ]


def test_label_outer_can_remove_inner_ticks_without_removing_outer_ticks() -> None:
    _fig, axes = plt.subplots(2, 2)

    for ax in axes.flat:
        ax.label_outer(remove_inner_ticks=True)

    assert [ax._tick_sides["x"]["bottom"] for ax in axes.flat] == [
        False,
        False,
        True,
        True,
    ]
    assert [ax._tick_sides["y"]["left"] for ax in axes.flat] == [
        True,
        False,
        True,
        False,
    ]


def test_label_outer_uses_the_full_gridspec_span() -> None:
    fig = plt.figure()
    grid = fig.add_gridspec(3, 3)
    upper_left = fig.add_subplot(grid[:2, :2])
    lower_right = fig.add_subplot(grid[1:, 1:])
    for index, ax in enumerate((upper_left, lower_right)):
        ax.set_xlabel(f"x-{index}")
        ax.set_ylabel(f"y-{index}")
        ax.label_outer()

    assert upper_left.get_xlabel() == ""
    assert upper_left.get_ylabel() == "y-0"
    assert lower_right.get_xlabel() == "x-1"
    assert lower_right.get_ylabel() == ""


def test_label_outer_is_a_noop_for_free_form_axes() -> None:
    fig = plt.figure()
    ax = fig.add_axes([0.2, 0.2, 0.6, 0.6])
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    labels_before = {axis: dict(sides) for axis, sides in ax._tick_label_sides.items()}
    ticks_before = {axis: dict(sides) for axis, sides in ax._tick_sides.items()}

    ax.label_outer(remove_inner_ticks=True)

    assert ax.get_xlabel() == "x"
    assert ax.get_ylabel() == "y"
    assert ax._tick_label_sides == labels_before
    assert ax._tick_sides == ticks_before


def test_margins_getter_and_mixed_argument_error_are_matplotlib_compatible() -> None:
    _fig, ax = plt.subplots()

    assert ax.margins() == pytest.approx((0.05, 0.05))
    ax.margins(x=0.2, y=-0.1)
    assert ax.margins() == pytest.approx((0.2, -0.1))

    before = ax.margins()
    with pytest.raises(
        TypeError,
        match="Cannot pass both positional and keyword arguments for x and/or y",
    ):
        ax.margins(0.3, x=0.4)
    assert ax.margins() == before


def test_margins_tight_controls_and_preserves_round_number_expansion() -> None:
    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        _fig, ax = plt.subplots()
        ax.plot([0.3, 1.2], [0.3, 1.2])

        ax.margins(0.05)
        tight_default = ax._build_chart(640, 480).figure()
        assert tight_default.x_range() == pytest.approx((0.255, 1.245))

        ax.margins(0.05, tight=False)
        loose = ax._build_chart(640, 480).figure()
        assert loose.x_range() == pytest.approx((0.2, 1.4))

        ax.margins(0.05, tight=None)
        preserved = ax._build_chart(640, 480).figure()
        assert preserved.x_range() == pytest.approx((0.2, 1.4))

        ax.margins(0.05, tight=True)
        tight_explicit = ax._build_chart(640, 480).figure()
        assert tight_explicit.x_range() == pytest.approx((0.255, 1.245))


def test_autoscale_transitions_update_and_preserve_tight_state() -> None:
    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        _fig, ax = plt.subplots()
        ax.plot([0.3, 1.2], [0.3, 1.2])

        ax.margins(0.05)
        ax.autoscale_view(tight=False)
        assert ax._tight is False
        assert ax._build_chart(640, 480).figure().x_range() == pytest.approx((0.2, 1.4))

        ax.margins(0.05, tight=False)
        ax.autoscale_view(tight=True)
        assert ax._tight is True
        ax.autoscale_view(tight=None)
        assert ax._tight is True

        ax.autoscale(tight=False)
        assert ax._tight is False
        ax.autoscale(tight=True)
        assert ax._tight is True

        ax.margins(0.05, tight=False)
        ax.autoscale(False, tight=True)
        assert ax._tight is False
        ax.autoscale(None, tight=True)
        assert ax._tight is True
        assert ax.margins() == (0.0, 0.0)
        ax.autoscale(True, tight=None)
        assert ax._build_chart(640, 480).figure().x_range() == pytest.approx((0.3, 1.2))


def test_autoscale_tight_zeroes_enabled_margins_without_freezing_limits() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 20.0])
    ax.margins(x=0.2, y=0.1)

    ax.autoscale(tight=True)

    assert ax.margins() == (0.0, 0.0)
    assert ax._explicit_domains.isdisjoint({"x", "y"})
    assert ax.get_xlim() == pytest.approx((0.0, 10.0))
    assert ax.get_ylim() == pytest.approx((0.0, 20.0))

    ax.plot([20.0], [40.0])
    assert ax.get_xlim() == pytest.approx((0.0, 20.0))
    assert ax.get_ylim() == pytest.approx((0.0, 40.0))


def test_autoscale_view_tight_preserves_margins_and_disabled_axes() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 20.0])
    ax.margins(x=0.2, y=0.1)
    ax.autoscale(False, axis="y")
    frozen_y = ax.get_ylim()

    ax.autoscale_view(tight=True)

    assert ax.margins() == pytest.approx((0.2, 0.1))
    assert "x" not in ax._explicit_domains
    assert "y" in ax._explicit_domains
    assert ax.get_xlim() == pytest.approx((-2.0, 12.0))
    assert ax.get_ylim() == frozen_y

    ax.plot([20.0], [40.0])
    assert ax.get_xlim() == pytest.approx((-4.0, 24.0))
    assert ax.get_ylim() == frozen_y


def test_autoscale_none_forwards_tight_to_both_axes_without_reenabling() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 20.0])
    ax.margins(x=0.2, y=0.1, tight=False)
    ax.autoscale(False, axis="x")
    frozen_x = ax.get_xlim()

    ax.autoscale(None, axis="x", tight=True)

    assert ax._tight is True
    assert ax.get_xmargin() == 0.0
    assert ax.get_ymargin() == 0.0
    assert "x" in ax._explicit_domains
    assert "y" not in ax._explicit_domains
    assert ax.get_xlim() == frozen_x
    assert ax.get_ylim() == pytest.approx((0.0, 20.0))

    ax.plot([20.0], [40.0])
    assert ax.get_xlim() == frozen_x
    assert ax.get_ylim() == pytest.approx((0.0, 40.0))


def test_autoscale_none_tight_updates_both_disabled_axes_without_reenabling() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 20.0])
    ax.margins(x=0.2, y=0.1, tight=False)
    ax.autoscale(False)
    frozen_x = ax.get_xlim()
    frozen_y = ax.get_ylim()

    ax.autoscale(None, axis="x", tight=True)

    assert ax._tight is True
    assert ax.margins() == (0.0, 0.0)
    assert {"x", "y"}.issubset(ax._explicit_domains)
    assert ax.get_xlim() == frozen_x
    assert ax.get_ylim() == frozen_y

    ax.plot([20.0], [40.0])
    assert ax.get_xlim() == frozen_x
    assert ax.get_ylim() == frozen_y


def test_axis_modes_share_matplotlib_tight_state_transitions() -> None:
    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        _fig, ax = plt.subplots()
        ax.plot([0.3, 1.2], [0.3, 1.2])

        ax.axis("tight")
        assert ax._tight is True
        ax.autoscale(tight=None)
        assert ax._tight is True
        assert ax._build_chart(640, 480).figure().x_range() == pytest.approx((0.255, 1.245))

        ax.axis("auto")
        assert ax._tight is False
        ax.autoscale(tight=None)
        assert ax._build_chart(640, 480).figure().x_range() == pytest.approx((0.2, 1.4))

        ax.axis("image")
        assert ax._tight is True


def test_margins_preserve_explicit_limits_and_allow_negative_clipping() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 20.0])
    ax.set_xlim(-2.0, 12.0)

    ax.margins(x=0.3, y=-0.1)

    assert ax.get_xlim() == (-2.0, 12.0)
    assert ax.get_ylim() == pytest.approx((2.0, 18.0))
