"""Matplotlib 3.11 axis/tick APIs exercised by the upstream gallery."""

from __future__ import annotations

import pytest

import xy.pyplot as plt


def test_set_ticklabels_matches_fixed_locator_and_empty_label_semantics() -> None:
    _fig, ax = plt.subplots()
    ax.set_xticks([0, 1, 2])

    labels = ax.set_xticklabels(["zero", "one", "two"], color="tab:red", fontsize=12, rotation=30)

    assert [label.get_text() for label in labels] == ["zero", "one", "two"]
    assert ax._axis_props("x")["tick_labels"] == ["zero", "one", "two"]
    assert ax._axis_props("x")["tick_label_angle"] == 30.0
    assert ax._axis_props("x")["style"]["tick_label_color"] == "#d62728"
    assert ax._axis_props("x")["style"]["tick_label_size"] == pytest.approx(12 * 100 / 72)

    with pytest.raises(ValueError, match="FixedLocator locations"):
        ax.set_xticklabels(["too", "short"])

    tick_positions = list(ax._axis_props("x")["tick_values"])
    hidden = ax.set_xticklabels([])
    assert [label.get_text() for label in hidden] == ["", "", ""]
    assert ax._axis_props("x")["tick_values"] == tick_positions
    assert ax._axis_props("x")["tick_label_strategy"] == "off"


def test_set_yticklabels_without_fixed_ticks_uses_current_static_tick_set() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 4])
    current = ax.get_yticks()

    labels = ax.set_yticklabels(["low", "high"])

    assert len(labels) == len(current)
    assert [label.get_text() for label in labels[:2]] == ["low", "high"]
    assert all(label.get_text() == "" for label in labels[2:])
    assert ax.get_yticks() == pytest.approx(current)


def test_axis_proxy_grid_targets_only_its_dimension_and_minor_is_accepted() -> None:
    _fig, ax = plt.subplots()

    ax.xaxis.grid(True, color="tab:red", linewidth=2)
    assert ax._axis_props("x")["style"]["grid_color"] == "#d62728"
    assert ax._axis_props("x")["style"]["grid_width"] == 2.0
    assert ax._axis_props("y")["style"]["grid_color"] == "transparent"

    ax.yaxis.grid(True, color="tab:blue")
    assert ax._axis_props("x")["style"]["grid_color"] == "#d62728"
    assert ax._axis_props("y")["style"]["grid_color"] == "#1f77b4"

    ax.xaxis.grid(False)
    assert ax._axis_props("x")["style"]["grid_color"] == "transparent"
    assert ax._axis_props("y")["style"]["grid_color"] == "#1f77b4"

    # Minor ticks are not rendered natively, but Matplotlib's accepted call is
    # a compatibility no-op rather than a gallery-stopping ValueError.
    ax.xaxis.grid(which="minor", color="0.9")
    assert ax._axis_props("y")["style"]["grid_color"] == "#1f77b4"


def test_tick_params_side_flags_and_xtick_rotation_mode() -> None:
    _fig, ax = plt.subplots()
    default_x_length = ax._axis_props("x")["style"]["tick_length"]
    default_y_length = ax._axis_props("y")["style"]["tick_length"]

    ax.tick_params(left=False, bottom=False, labelbottom=False)

    assert ax._axis_props("x")["style"]["tick_length"] == 0.0
    assert ax._axis_props("y")["style"]["tick_length"] == 0.0
    assert ax._axis_props("x")["tick_label_strategy"] == "off"
    assert ax._axis_props("y").get("tick_label_strategy") is None

    ax.tick_params(axis="x", bottom=True, rotation=45, rotation_mode="xtick")
    assert ax._axis_props("x")["style"]["tick_length"] == default_x_length
    assert ax._axis_props("y")["style"]["tick_length"] == 0.0
    assert default_y_length > 0
    assert ax._axis_props("x")["tick_label_angle"] == 45.0
    assert ax._axis_props("x")["tick_label_anchor"] == "end"
    assert ax.get_xticklabels()[0].get_rotation_mode() == "xtick"

    with pytest.raises(ValueError, match="rotation_mode"):
        ax.tick_params(axis="x", rotation_mode="sideways")


def test_set_axis_margins_expand_or_clip_and_validate_matplotlib_bound() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 2], [0, 2])

    ax.set_xmargin(0.1)
    ax.set_ymargin(-0.1)

    assert ax.get_xmargin() == 0.1
    assert ax.get_ymargin() == -0.1
    assert ax.get_xlim() == pytest.approx((-0.2, 2.2))
    assert ax.get_ylim() == pytest.approx((0.2, 1.8))

    ax.set_xmargin(0)
    chart = ax._build_chart(640, 480)
    x_axis = next(child for child in chart.children if getattr(child, "which", None) == "x")
    assert x_axis.domain == pytest.approx((0, 2))

    ax.set(xmargin=0.8, ymargin=0.25)
    assert ax.get_xmargin() == 0.8
    assert ax.get_ymargin() == 0.25

    with pytest.raises(ValueError, match=r"greater than -0\.5"):
        ax.set_xmargin(-0.5)
    with pytest.raises(ValueError, match=r"greater than -0\.5"):
        ax.set_ymargin(float("inf"))
