from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean_pyplot_state():
    plt.close("all")
    yield
    plt.close("all")


def test_bar_and_barh_broadcast_scalar_and_vector_positional_inputs() -> None:
    _fig, ax = plt.subplots()

    vertical = ax.bar(2.0, 3.0, width=[0.2, 0.4], bottom=[1.0, 2.0])
    np.testing.assert_array_equal(vertical._entry["x"], [2.0, 2.0])
    np.testing.assert_array_equal(vertical._entry["y"], [3.0, 3.0])
    np.testing.assert_array_equal(vertical._entry["kwargs"]["width"], [0.2, 0.4])
    np.testing.assert_array_equal(vertical._entry["kwargs"]["base"], [1.0, 2.0])
    assert len(vertical) == 2

    horizontal = ax.barh(["A", "B", "C"], 5.0, height=0.5, left=[0.0, 1.0, 2.0])
    np.testing.assert_array_equal(horizontal._entry["x"], ["A", "B", "C"])
    np.testing.assert_array_equal(horizontal._entry["y"], [5.0, 5.0, 5.0])
    assert horizontal._entry["kwargs"]["width"] == 0.5
    np.testing.assert_array_equal(horizontal._entry["kwargs"]["base"], [0.0, 1.0, 2.0])
    assert len(horizontal) == 3


def test_bar_rejects_positional_inputs_that_cannot_broadcast() -> None:
    _fig, ax = plt.subplots()

    with pytest.raises(ValueError, match="shape mismatch"):
        ax.bar([0.0, 1.0], [1.0, 2.0, 3.0])


def test_figure_and_axes_patch_facecolors_mutate_their_host_state() -> None:
    fig, ax = plt.subplots()

    assert fig.patch is fig.patch
    assert ax.patch is ax.patch
    fig.patch.set_facecolor("#fffacd")
    ax.patch.set_fc("#778899")

    assert fig.patch.get_facecolor() == "#fffacd"
    assert fig.get_facecolor() == "#fffacd"
    assert ax.patch.get_facecolor() == "#778899"
    assert ax.get_facecolor() == "#778899"


def test_legend_frame_mutations_stay_synchronized_with_host_options() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [1.0, 2.0], label="line")
    legend = ax.legend(facecolor="white", edgecolor="black", framealpha=0.8)

    frame = legend.get_frame()
    assert frame is legend.get_frame()
    frame.set_facecolor("#123456")
    frame.set_edgecolor("#abcdef")
    frame.set_alpha(0.35)

    style = ax._legend_options["style"]
    assert style["background"] == "#123456"
    assert style["borderColor"] == "#abcdef"
    assert style["--xy-legend-frame-alpha"] == 0.35
    assert legend.spec()["style"] == style
    assert frame.get_facecolor() == "#123456"
    assert frame.get_edgecolor() == "#abcdef"
    assert frame.get_alpha() == 0.35

    frame.set_visible(False)
    assert frame.get_visible() is False
    assert ax._legend_options["style"]["background"] == "transparent"
    assert ax._legend_options["style"]["borderColor"] == "transparent"
    frame.set_visible(True)
    assert frame.get_visible() is True
    assert ax._legend_options["style"]["background"] == "#123456"
    assert ax._legend_options["style"]["borderColor"] == "#abcdef"


def test_spines_support_matplotlib_attribute_visibility_access() -> None:
    _fig, ax = plt.subplots()

    ax.spines.top.set_visible(False)
    ax.spines.right.set_visible(False)

    assert ax.spines.top.get_visible() is False
    assert ax.spines.right.get_visible() is False
    assert ax.spines.left.get_visible() is True
    assert ax._hidden_spines == {"top", "right"}


def test_fill_between_with_no_adjacent_selected_points_has_no_render_entry() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    existing_entries = list(ax._entries)

    collection = ax.fill_between(
        [0.0, 1.0, 2.0],
        [1.0, 2.0, 3.0],
        where=[False, True, False],
        label="empty",
    )

    assert len(ax._entries) == 1
    assert ax._entries[0] is existing_entries[0]
    assert collection in ax.collections
    assert collection._entry["kind"] == "area"
    assert np.asarray(collection._entry["x"]).size == 0
    assert np.asarray(collection._entry["y"]).size == 0
    collection.remove()
    assert collection not in ax.collections
