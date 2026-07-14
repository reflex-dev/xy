import pytest

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_tight_layout_records_validated_noop_contract():
    fig, _ = plt.subplots(1, 2)
    fig.tight_layout(pad=1.2, h_pad=0.5, w_pad=0.7, rect=(0, 0, 1, 1))

    assert fig._layout_options == {
        "engine": "tight",
        "pad": 1.2,
        "h_pad": 0.5,
        "w_pad": 0.7,
        "rect": (0, 0, 1, 1),
    }
    with pytest.raises(TypeError):
        fig.tight_layout(foo=1)


def test_subplots_adjust_rejects_spacing_it_cannot_render():
    fig, _ = plt.subplots(2, 2)
    with pytest.raises(NotImplementedError, match="subplots_adjust"):
        fig.subplots_adjust(left=0.1, wspace=0.3)
    with pytest.raises(TypeError):
        fig.subplots_adjust(foo=1)


def test_autofmt_xdate_rotates_x_tick_labels_on_all_axes():
    fig, axes = plt.subplots(1, 2)
    fig.autofmt_xdate(rotation=45, ha="center")

    for ax in axes:
        assert ax._axis_props("x")["tick_label_angle"] == 45
        assert ax._axis_props("x")["style"]["tick_label_anchor"] == "center"


def test_suptitle_accepts_supported_font_kwargs_and_rejects_unknown():
    fig, _ = plt.subplots()
    fig.suptitle("title", fontsize=14, fontweight="bold", color="red", x=0.5, y=0.95)
    assert fig._suptitle == "title"
    with pytest.raises(TypeError):
        fig.suptitle("bad", unknown=True)
