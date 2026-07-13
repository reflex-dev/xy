import pytest

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_grid_selects_axis_and_records_supported_style():
    _, ax = plt.subplots()
    ax.grid(True, axis="x", which="major", color="red", linewidth=2, linestyle="--", alpha=0.5)

    x_style = ax._axis_props("x")["style"]
    y_style = ax._axis_props("y")["style"]
    assert ax._grid is True
    assert ax._grid_axis == "x"
    assert x_style["grid_color"] == "red"
    assert x_style["grid_width"] == 2.0
    assert x_style["grid_dash"] == "dashed"
    assert x_style["grid_opacity"] == 0.5
    assert y_style["grid_color"] == "transparent"

    ax.grid(False, axis="y", color="blue")
    assert ax._axis_props("y")["style"]["grid_color"] == "transparent"
    with pytest.raises(ValueError):
        ax.grid(True, axis="z")
    with pytest.raises(ValueError):
        ax.grid(True, which="minor")
    with pytest.raises(TypeError):
        ax.grid(True, unsupported=True)


def test_legend_maps_supported_style_and_rejects_unknown_options():
    _, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], label="line")
    ax.legend(
        loc="upper right",
        ncols=2,
        title="Legend",
        fontsize=13,
        labelcolor="green",
        frameon=True,
        facecolor="white",
        edgecolor="black",
    )

    assert ax._legend is True
    assert ax._legend_options["loc"] == "upper right"
    assert ax._legend_options["ncols"] == 2
    assert ax._legend_options["class_name"] == "legend-title:Legend"
    assert ax._legend_options["style"] == {
        "fontSize": "13px",
        "color": "green",
        "background": "white",
        "borderColor": "black",
        "borderStyle": "solid",
    }

    with pytest.raises(TypeError):
        ax.legend(shadow=True)


def test_legend_frameoff_maps_to_transparent_style():
    _, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], label="line")
    ax.legend(frameon=False)

    assert ax._legend_options["style"]["background"] == "transparent"
    assert ax._legend_options["style"]["borderColor"] == "transparent"
