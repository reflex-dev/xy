import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._rc import rcParams


def teardown_function():
    plt.close("all")
    plt.rcdefaults()


def test_autoscale_bounds_and_relim_helpers():
    fig, ax = plt.subplots()
    ax.plot([0, 10], [2, 4])
    ax.margins(0.1)
    assert ax.get_xbound() == pytest.approx((-1, 11))

    ax.set_xbound(1, 3)
    assert ax.get_xlim() == (1, 3)
    ax.relim()
    ax.autoscale(axis="x")
    assert ax.get_xlim() == pytest.approx((-1, 11))

    plt.set_ybound(0, 8)
    assert plt.get_ybound() == (0, 8)
    plt.autoscale(axis="y", tight=True)
    assert ax.get_ylim() == (2, 4)


def test_ticklabel_minor_label_axis_and_legend_helpers():
    _, ax = plt.subplots()
    line = ax.plot([0, 1], [1, 2], label="series")[0]
    ax.set_xlabel("x label")
    ax.set_ylabel("y label")
    ax.set_title("title")
    ax.ticklabel_format(axis="x", style="sci", scilimits=(-2, 3), useOffset=False)
    ax.minorticks_on()
    ax.legend()

    assert ax.get_xlabel() == "x label"
    assert ax.get_ylabel() == "y label"
    assert ax.get_title() == "title"
    assert ax.get_xaxis() is ax.xaxis
    assert ax.get_yaxis() is ax.yaxis
    assert ax._axis_props("x")["tick_label_format"]["style"] == "sci"
    assert ax._axis_props("x")["minor_ticks"] is True
    assert ax.get_legend() is ax
    handles, labels = ax.get_legend_handles_labels()
    assert len(handles) == 1
    assert labels == ["series"]
    assert line.get_label() == "series"

    ax.minorticks_off()
    assert ax._axis_props("x")["minor_ticks"] is False


def test_prop_cycle_setp_getp_rc_context_and_colormap_helpers():
    _, ax = plt.subplots()
    ax.set_prop_cycle(color=["red", "blue"])
    first = ax.plot([0, 1], [0, 1])[0]
    second = ax.plot([0, 1], [1, 2])[0]
    assert first.get_color() == "red"
    assert second.get_color() == "blue"

    plt.setp(first, color="green", label="renamed")
    assert plt.getp(first, "label") == "renamed"
    assert plt.get(first, "color") == "green"

    with plt.rc_context({"image.cmap": "plasma"}):
        assert rcParams["image.cmap"] == "plasma"
    assert rcParams["image.cmap"] == "viridis"

    assert plt.plasma().name == "plasma"
    assert rcParams["image.cmap"] == "plasma"
    assert plt.gray().name == "gray"


def test_subplot2grid_box_and_secondary_axes_contract():
    fig = plt.figure()
    ax = plt.subplot2grid((2, 2), (1, 0))
    assert fig.axes[2] is ax
    plt.box(False)
    assert ax._box is False

    with pytest.raises(NotImplementedError):
        plt.subplot2grid((2, 2), (0, 0), colspan=2)
    with pytest.raises(NotImplementedError):
        ax.secondary_xaxis("top")
    with pytest.raises(NotImplementedError):
        ax.secondary_yaxis("right")


def test_imread_imsave_png_roundtrip_and_jpeg_exclusion(tmp_path):
    image = np.array(
        [
            [[255, 0, 0, 255], [0, 255, 0, 128]],
            [[0, 0, 255, 255], [255, 255, 255, 0]],
        ],
        dtype=np.uint8,
    )
    path = tmp_path / "image.png"
    plt.imsave(path, image)

    loaded = plt.imread(path)

    np.testing.assert_array_equal(loaded, image)
    with pytest.raises(NotImplementedError):
        plt.imsave(tmp_path / "image.jpg", image)
    jpeg = tmp_path / "image.jpeg"
    jpeg.write_bytes(b"\xff\xd8not really jpeg")
    with pytest.raises(NotImplementedError):
        plt.imread(jpeg)
