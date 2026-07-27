"""Multiline chart chrome must reserve and render one shared text block."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _raster, _svg, _textblock
from xy.pyplot._mplfig import _panel_chrome


@pytest.fixture(autouse=True)
def _clean_pyplot() -> None:
    plt.close("all")
    yield
    plt.close("all")


def _figure() -> tuple[object, object]:
    fig, ax = plt.subplots(figsize=(5.4, 3.8), dpi=100)
    ax.plot([0, 1, 2], [0, 1, 0])
    ax.set_title("Measured title\nsecond line")
    ax.set_xticks([0, 1, 2], ["north\nregion", "central\nregion", "south\nregion"])
    ax.set_yticks([0, 1], ["low\nband", "high\nband"])
    return fig, ax


def test_svg_and_native_raster_emit_each_chrome_line_separately(monkeypatch) -> None:
    fig, _ax = _figure()
    svg_buffer = BytesIO()
    fig.savefig(svg_buffer, format="svg")
    root = ElementTree.fromstring(svg_buffer.getvalue())
    tspans = [node.text or "" for node in root.iter() if node.tag.endswith("tspan")]

    assert {"Measured title", "second line", "north", "region", "low", "band"} <= set(tspans)

    calls: list[str] = []
    original = _raster._Cmd.text

    def record(self, x, y, anchor, size, color, text, **kwargs):
        calls.append(str(text))
        return original(self, x, y, anchor, size, color, text, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", record)
    png_buffer = BytesIO()
    fig.savefig(png_buffer, format="png")

    assert png_buffer.getvalue().startswith(b"\x89PNG")
    assert {"Measured title", "second line", "north", "region", "low", "band"} <= set(calls)
    assert not any("\n" in text for text in calls)


def test_multiline_gutters_grow_by_measured_line_steps_without_moving_single_lines() -> None:
    # Measurement retains real glyph advances instead of reducing every line
    # to character count, which is essential for labels in proportional fonts.
    assert _textblock.measure("WWWW", 12).width > _textblock.measure("iiii", 12).width

    fig, ax = plt.subplots(figsize=(5.4, 3.8), dpi=100)
    ax.plot([0, 1], [0, 1])
    ax.set_xticks([0, 1], ["north region", "south region"])
    ax.set_title("Measured title")
    single = ax._build_chart(540, 380).figure().build_payload()[0]
    single_plot = _svg.layout(single)[3]

    ax.set_xticklabels(["north\nregion", "south\nregion"])
    ax.set_title("Measured title\nsecond line")
    multi = ax._build_chart(540, 380).figure().build_payload()[0]
    multi_plot = _svg.layout(multi)[3]

    title_size = float(
        str(((multi.get("dom") or {}).get("styles") or {})["title"]["font-size"]).removesuffix("px")
    )
    tick_size = float(multi["x_axis"]["style"]["tick_label_size"])
    single_title = _textblock.measure("Measured title", title_size)
    multi_title = _textblock.measure("Measured title\nsecond line", title_size)
    assert multi_plot["title_room"] - single_plot["title_room"] == pytest.approx(
        max(30.0, multi_title.height + 8.0) - max(30.0, single_title.height + 8.0),
        abs=0.1,
    )
    assert multi_plot["y"] > single_plot["y"]
    assert single_plot["y"] + single_plot["h"] - (
        multi_plot["y"] + multi_plot["h"]
    ) == pytest.approx(tick_size * _textblock.LINE_HEIGHT, abs=0.3)


def test_constrained_layout_reflows_after_late_multiline_chrome_and_suptitle() -> None:
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 4.8), dpi=100, layout="constrained")
    top, bottom = np.asarray(axes).ravel()
    top.plot([0, 1], [0, 1])
    bottom.plot([0, 1], [1, 0])
    before = tuple(fig._effective_rects() or ())

    bottom.set_title("Lower panel\nwith a second title line")
    top.set_xticks([0, 1], ["first\ncategory", "second\ncategory"])
    fig.suptitle("Figure heading\nwith context")

    assert fig._layout_dirty
    after = tuple(fig._effective_rects() or ())
    assert not fig._layout_dirty
    assert after != before

    width, height = 640, 480
    upper, lower = after
    vertical_gap = (upper[1] - lower[1] - lower[3]) * height
    upper_chrome = _panel_chrome(top, round(width * upper[2]))
    lower_chrome = _panel_chrome(bottom, round(width * lower[2]))
    assert vertical_gap >= upper_chrome[3] + lower_chrome[1] - 1.0
    # The multiline suptitle is above the upper panel's own chrome.
    upper_plot_top = (1.0 - upper[1] - upper[3]) * height
    suptitle = _textblock.measure(fig._suptitle, fig._suptitle_style["size"])
    assert upper_plot_top >= suptitle.height + upper_chrome[1]

    svg_buffer = BytesIO()
    fig.savefig(svg_buffer, format="svg")
    root = ElementTree.fromstring(svg_buffer.getvalue())
    assert {"Figure heading", "with context"} <= {
        node.text or "" for node in root.iter() if node.tag.endswith("tspan")
    }
    png_buffer = BytesIO()
    fig.savefig(png_buffer, format="png")
    assert png_buffer.getvalue().startswith(b"\x89PNG")


def test_browser_client_uses_the_same_preline_block_contract() -> None:
    source = (Path(__file__).resolve().parents[2] / "js" / "src" / "50_chartview.ts").read_text()

    assert 'replace(/\\r\\n?/g, "\\n").split("\\n")' in source
    assert "lines.length * fontSize * 1.2" in source
    assert "XY_ASCII_ADVANCES" in source
    assert "xyTextAdvance(line, fontSize)" in source
    assert "white-space:pre-line" in source
    assert "_xAxisMultilineExtra" in source
