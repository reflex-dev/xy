from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import xy.pyplot as plt


class _Cycle:
    def by_key(self):
        return {"color": ["red", "blue"]}


@pytest.fixture(autouse=True)
def _reset():
    plt.close("all")
    plt.rcdefaults()
    yield
    plt.close("all")
    plt.rcdefaults()


def test_rc_axes_font_label_tick_and_cycle_values_reach_chart_state() -> None:
    with plt.rc_context(
        {
            "axes.facecolor": "#102030",
            "axes.edgecolor": "red",
            "axes.labelcolor": "blue",
            "axes.titlesize": 18,
            "axes.labelsize": 14,
            "font.family": ["serif"],
            "font.size": 12,
            "xtick.color": "green",
            "xtick.labelsize": 9,
            "axes.prop_cycle": _Cycle(),
        }
    ):
        _fig, ax = plt.subplots()
        first, second = ax.plot([0, 1], [0, 1], [0, 1], [1, 0])
        ax.set_title("title")
        ax.set_xlabel("x")
        built = ax._build_chart(640, 480).figure()

    assert first.get_color() == "red"
    assert second.get_color() == "blue"
    assert built.style["--chart-bg"] == "#102030"
    assert built.style["--chart-axis"] == "red"
    assert built.style["font-family"] == "serif"
    assert built.style["font-size"] == "16.6667px"
    assert built.chrome_styles["title"]["font-size"] == "25px"
    assert built.chrome_styles["axis_title"] == {"font-size": "19.4444px", "color": "blue"}
    assert built.chrome_styles["tick_label"]["font-size"] == "12.5px"
    assert built.axis_options["x"]["style"]["tick_color"] == "green"


def test_legend_rc_defaults_reach_legend_component() -> None:
    with plt.rc_context(
        {
            "legend.loc": "upper right",
            "legend.fontsize": 13,
            "legend.facecolor": "yellow",
            "legend.edgecolor": "blue",
            "legend.frameon": True,
        }
    ):
        _fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1], label="line")
        ax.legend()
    assert ax._legend_options["loc"] == "upper right"
    assert ax._legend_options["style"] == {
        "fontSize": "18.0556px",
        "background": "yellow",
        "borderColor": "blue",
        "borderStyle": "solid",
        "borderWidth": "1px",
        "--xy-legend-frame-alpha": 0.8,
        "padding": "0.4em",
        "rowGap": "0.5em",
    }


def test_rc_fonts_and_axis_strokes_scale_with_figure_dpi() -> None:
    fig = plt.figure(dpi=144)
    ax = fig.add_subplot()
    built = ax._build_chart(640, 480).figure()

    assert built.style["font-size"] == "20px"
    assert built.chrome_styles["tick_label"]["font-size"] == "20px"
    assert built.axis_options["x"]["style"]["axis_width"] == pytest.approx(1.6)
    assert built.axis_options["x"]["style"]["tick_length"] == pytest.approx(7.0)
    assert built.axis_options["x"]["style"]["tick_padding"] == pytest.approx(7.0)


def test_rc_tick_padding_accepts_negative_values() -> None:
    plt.rcParams["xtick.major.pad"] = -4
    plt.rcParams["ytick.major.pad"] = -2

    _fig, ax = plt.subplots()
    built = ax._build_chart(640, 480).figure()

    assert built.axis_options["x"]["style"]["tick_padding"] == pytest.approx(-4 * ax._point_scale())
    assert built.axis_options["y"]["style"]["tick_padding"] == pytest.approx(-2 * ax._point_scale())


def test_spine_controls_and_invalid_cycle_boundaries() -> None:
    plt.rcParams["axes.spines.left"] = False
    plt.rcParams["axes.spines.top"] = True
    with pytest.raises(ValueError, match="non-empty color cycle"):
        plt.rcParams["axes.prop_cycle"] = object()

    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.spines[["top", "right"]].set_visible(False)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["frame_sides"] == ["bottom"]


def test_title_and_label_weight_rc_defaults_match_matplotlib() -> None:
    # Matplotlib 3.11: axes.titleweight and axes.labelweight are both "normal".
    assert plt.rcParams["axes.titleweight"] == "normal"
    assert plt.rcParams["axes.labelweight"] == "normal"

    _fig, ax = plt.subplots()
    ax.set_title("title")
    ax.set_xlabel("x")
    built = ax._build_chart(640, 480).figure()

    # "normal" is every renderer's own default, so it needs nothing on the
    # wire — the browser, SVG, and raster paths all land on 400 unaided.
    assert "font-weight" not in built.chrome_styles["title"]
    assert "font-weight" not in built.chrome_styles["axis_title"]
    assert "label_font_weight" not in built.axis_options["x"]["style"]


def test_title_and_label_weight_rc_overrides_reach_every_renderer() -> None:
    with plt.rc_context({"axes.titleweight": "bold", "axes.labelweight": 700}):
        _fig, ax = plt.subplots()
        ax.set_title("title")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        built = ax._build_chart(640, 480).figure()
        svg = built.to_svg()

    # browser: the chrome slot styles the render client applies
    assert built.chrome_styles["title"]["font-weight"] == "bold"
    assert built.chrome_styles["axis_title"]["font-weight"] == "700"
    # SVG + native raster read the weight off the axis style, not the chrome
    # slots, so axes.labelweight has to be published in both places.
    assert built.axis_options["x"]["style"]["label_font_weight"] == "700"
    assert built.axis_options["y"]["style"]["label_font_weight"] == "700"
    assert 'font-weight="bold"' in svg
    assert 'font-weight="700"' in svg


def test_explicit_set_title_weight_still_beats_the_rc_default() -> None:
    _fig, ax = plt.subplots()
    ax.set_title("title", fontweight="bold")
    ax.set_xlabel("x", fontweight="light")
    built = ax._build_chart(640, 480).figure()

    assert built.chrome_styles["title"]["font-weight"] == "bold"
    assert built.axis_options["x"]["style"]["label_font_weight"] == "light"


def test_quoted_font_families_remain_well_formed_in_svg() -> None:
    _fig, ax = plt.subplots()
    ax.set_title("title", fontfamily='"Foo Bar", serif')
    ax.set_xlabel("x", fontfamily='"Foo Bar", serif')
    ax.set_ylabel("y", fontfamily='"Foo Bar", serif')

    svg = ax._build_chart(640, 480).figure().to_svg()

    ET.fromstring(svg)
    assert svg.count('font-family="&quot;Foo Bar&quot;, serif"') == 3


def test_spine_open_slice_targets_every_side_like_matplotlib() -> None:
    _fig, ax = plt.subplots()

    ax.spines[:].set_visible(False)

    assert ax._hidden_spines == {"left", "bottom", "top", "right"}


def test_spine_tuple_and_partial_slice_raise_matplotlib_errors() -> None:
    _fig, ax = plt.subplots()

    with pytest.raises(ValueError, match="single list"):
        ax.spines["left", "right"]
    with pytest.raises(ValueError, match=r"fully open slice \[:\]"):
        ax.spines[1:]
