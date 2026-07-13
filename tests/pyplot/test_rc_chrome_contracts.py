from __future__ import annotations

import io

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
    assert built.style["font-size"] == "12px"
    assert built.chrome_styles["title"]["font-size"] == "18px"
    assert built.chrome_styles["axis_title"] == {"font-size": "14px", "color": "blue"}
    assert built.chrome_styles["tick_label"]["font-size"] == "9px"
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
        "fontSize": "13px",
        "background": "yellow",
        "borderColor": "blue",
        "borderStyle": "solid",
    }


def test_spine_and_invalid_cycle_boundaries_fail_loudly() -> None:
    with pytest.raises(NotImplementedError, match="cannot hide left"):
        plt.rcParams["axes.spines.left"] = False
    with pytest.raises(NotImplementedError, match="does not render top"):
        plt.rcParams["axes.spines.top"] = True
    with pytest.raises(ValueError, match="non-empty color cycle"):
        plt.rcParams["axes.prop_cycle"] = object()

    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.spines[["top", "right"]].set_visible(False)
    # Hiding only one of left/bottom is inexpressible and fails at build time;
    # hiding both renders with transparent axis lines.
    ax.spines["left"].set_visible(False)
    with pytest.raises(NotImplementedError, match="hiding only the left spine"):
        _fig.savefig(io.BytesIO(), format="png")
    ax.spines["bottom"].set_visible(False)
    buffer = io.BytesIO()
    _fig.savefig(buffer, format="png")
    assert buffer.getvalue()[:4] == b"\x89PNG"
