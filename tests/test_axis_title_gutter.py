"""The y-axis title must sit clear of the tick labels, on emitted geometry.

`layout()` used to hand every chart a flat 46/62 px left gutter and
`_axis_label_geometry` used to anchor the rotated y title's *baseline* at a
10 px canvas inset — while ChartView centers its rotated line *box* on that same
inset. The two together drew the title one full ascent further left than the
browser does, off the canvas, on top of the tick labels whenever the gutter was
also short. Both are now measured from the DejaVu advances the rasterizer blits
(`python/xy/_fontmetrics.py`, generated from `src/font.rs`).

Every assertion below reads the boxes back out of real emitted output — SVG text
coordinates, plus a pixel-ink scan of the native rasterizer's canvas — never out
of the layout helpers that produced them.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest

import xy
from xy import _fontmetrics, _raster, _svg

_ASCENT = _fontmetrics.ASCENT / _fontmetrics.BASE_PX
_DESCENT = _fontmetrics.DESCENT / _fontmetrics.BASE_PX


def _payload(chart):
    return chart.figure().build_payload()


def _boxes(svg: str, plot: dict[str, float], title: str):
    """(title ink span, [tick ink spans]) in horizontal px, from the SVG itself."""
    root = ElementTree.fromstring(svg)
    title_box = None
    ticks: list[tuple[str, float, float]] = []
    for element in root.iter():
        if not element.tag.endswith("text"):
            continue
        text = "".join(element.itertext())
        size = float(element.attrib.get("font-size", 12))
        x = float(element.attrib.get("x", 0))
        rotation = re.match(r"rotate\((-?[\d.]+)", element.attrib.get("transform", ""))
        angle = float(rotation.group(1)) if rotation else 0.0
        if text == title and abs(abs(angle) - 90) < 0.5:
            # A -90° turn points ascenders toward -x, descenders toward +x.
            span = (
                (x - _ASCENT * size, x + _DESCENT * size)
                if angle < 0
                else (x - _DESCENT * size, x + _ASCENT * size)
            )
            title_box = span
        elif not rotation and element.attrib.get("text-anchor") == "end" and x <= plot["x"]:
            ticks.append((text, x - _fontmetrics.advance(text, size), x))
    assert title_box is not None, f"no rotated {title!r} title in the SVG"
    # Every y tick label shares one anchor x; other end-anchored text left of
    # the plot (annotations, legends) does not.
    pin = max(box[2] for box in ticks)
    ticks = [box for box in ticks if math.isclose(box[2], pin, abs_tol=0.01)]
    return title_box, ticks


def _assert_clear(svg, plot, title, *, canvas_width):
    title_box, ticks = _boxes(svg, plot, title)
    assert ticks, "expected y tick labels"
    tick_lo = min(box[1] for box in ticks)
    tick_hi = max(box[2] for box in ticks)
    overlap = min(title_box[1], tick_hi) - max(title_box[0], tick_lo)
    assert overlap < 0, (
        f"y title {title_box} overlaps tick labels [{tick_lo}, {tick_hi}] by {overlap:.1f}px"
    )
    assert title_box[1] < tick_lo, "the y title must sit outside the tick strip, not inside it"
    assert title_box[0] > 0, f"y title ink starts at x={title_box[0]:.1f}, clipped by the viewport"
    assert tick_lo > 0, f"tick ink starts at x={tick_lo:.1f}, clipped by the viewport"
    assert tick_hi < canvas_width and title_box[1] < canvas_width
    return title_box, (tick_lo, tick_hi)


def _first_ink_column(spec, blob, plot) -> int:
    """Leftmost column of the native raster carrying non-background ink."""
    rgba = _raster.render_raster(spec, blob, 1.0)
    assert isinstance(rgba, np.ndarray)
    gutter = rgba[:, : int(plot["x"]) - 1, :3].astype(np.int16)
    ink = np.abs(gutter - gutter[2, 2]).max(axis=2) > 24
    columns = np.where(ink.any(axis=0))[0]
    assert columns.size, "expected axis text in the left gutter"
    return int(columns.min())


def _chart(*, y_label, y_values, width=760, height=420, padding=None, style=None, **axis):
    """A minimal core (non-pyplot) line chart with a labeled y axis."""
    resolved = {"label_size": 14, "tick_label_size": 14} if style is None else style
    return xy.line_chart(
        xy.line(x=[float(index) for index in range(len(y_values))], y=list(y_values)),
        xy.y_axis(label=y_label, style=resolved, **axis),
        width=width,
        height=height,
        padding=padding,
    )


def test_wide_numeric_tick_labels_keep_the_y_title_clear() -> None:
    chart = _chart(y_label="average daily births", y_values=[3_600_000.0, 5_400_000.5])
    spec, blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    svg = _svg.render_svg(spec, blob)

    title_box, tick_span = _assert_clear(svg, plot, "average daily births", canvas_width=760)
    # The gutter grew past the 62 px default because the ink genuinely needs it.
    assert plot["x"] > 62.0
    # Matplotlib 3.11.1 leaves 5.6 px between the title ink and the tick ink at
    # its 13.89 px default; 0.4 em reproduces that ratio at any size.
    assert tick_span[0] - title_box[1] == pytest.approx(0.4 * 14, abs=0.05)
    assert _first_ink_column(spec, blob, plot) > 0


def test_long_categorical_tick_labels_keep_the_y_title_clear() -> None:
    categories = [f"Questionnaire item {index}" for index in range(1, 7)]
    chart = xy.bar_chart(
        xy.bar(x=categories, y=[10.0, 20.0, 30.0, 40.0, 50.0, 60.0], orientation="horizontal"),
        xy.y_axis(label="survey question", style={"label_size": 14, "tick_label_size": 14}),
        width=640,
        height=480,
    )
    spec, blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    svg = _svg.render_svg(spec, blob)

    _assert_clear(svg, plot, "survey question", canvas_width=640)
    assert plot["x"] > 150.0, "long category names need far more than the 62 px default"
    assert _first_ink_column(spec, blob, plot) > 0


def test_authored_padding_too_narrow_for_the_text_still_reserves_the_gutter() -> None:
    """An explicit `padding` is a floor, not a licence to clip.

    This is the shape of the pyplot notebook path, which pins
    `padding=[15, 20, 34, 41]` to match Matplotlib's inline `bbox_inches`
    footprint — 41 px is 27 px short of the ink it has to hold.
    """
    chart = _chart(
        y_label="average daily births",
        y_values=[3600.0, 5400.0],
        padding=[15.0, 20.0, 34.0, 41.0],
    )
    spec, blob = _payload(chart)
    assert spec["padding"] == [15.0, 20.0, 34.0, 41.0], "the authored padding still ships"
    _width, _height, _compact, plot = _svg.layout(spec)
    assert plot["x"] > 41.0, "the measured gutter has to win over a too-narrow authored one"
    _assert_clear(_svg.render_svg(spec, blob), plot, "average daily births", canvas_width=760)
    assert _first_ink_column(spec, blob, plot) > 0


def test_positive_label_offset_expands_the_gutter_instead_of_clipping() -> None:
    """An explicit title-to-tick gap must reserve the canvas room it consumes."""
    chart = _chart(
        y_label="average daily births",
        y_values=[3600.0, 5400.0],
        label_offset=20.0,
    )
    spec, blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    title_box, tick_span = _assert_clear(
        _svg.render_svg(spec, blob),
        plot,
        "average daily births",
        canvas_width=760,
    )
    assert tick_span[0] - title_box[1] == pytest.approx(20.0, abs=0.05)
    assert title_box[0] > 0


def test_ordinary_numeric_axis_keeps_the_default_gutter() -> None:
    """The measured reservation is a floor: it must not inflate ordinary charts.

    Default 11 px ticks under a 12 px title fit inside 62 px, so a chart that
    was laid out correctly before this change is laid out identically after it.
    """
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0, 2.0], y=[0.0, 1.0, 2.0]),
        xy.y_axis(label="value"),
        width=760,
        height=420,
    )
    spec, blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    assert plot["x"] == 62.0
    _assert_clear(_svg.render_svg(spec, blob), plot, "value", canvas_width=760)


def test_titleless_axis_reserves_only_its_tick_labels() -> None:
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0, 2.0], y=[1e9, 2e9, 3e9]),
        xy.y_axis(style={"tick_label_size": 18}),
        width=760,
        height=420,
    )
    spec, blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    svg = _svg.render_svg(spec, blob)
    root = ElementTree.fromstring(svg)
    lefts = [
        float(element.attrib["x"]) - _fontmetrics.advance("".join(element.itertext()), 18.0)
        for element in root.iter()
        if element.tag.endswith("text")
        and element.attrib.get("text-anchor") == "end"
        and float(element.attrib.get("font-size", 0)) == 18.0
    ]
    assert lefts and min(lefts) > 0, "wide tick labels must not fall off the canvas"


def test_python_font_metrics_match_the_rust_atlas() -> None:
    """A gutter measured from advances the rasterizer does not use is a guess.

    `scripts/gen_font.py` emits `src/font.rs` and `python/xy/_fontmetrics.py`
    from one face in one run. This pins them together so a regenerated atlas
    cannot silently leave the reservation measuring a different font than the
    one being drawn.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "font.rs").read_text()

    def constant(name: str) -> int:
        match = re.search(rf"pub const {name}: (?:u8|i32) = (\d+);", source)
        assert match, f"src/font.rs lost its {name}"
        return int(match.group(1))

    assert constant("BASE_PX") == _fontmetrics.BASE_PX
    assert constant("CELL_H") == _fontmetrics.CELL_H
    assert constant("ASCENT") == _fontmetrics.ASCENT
    assert _fontmetrics.CELL_H - _fontmetrics.ASCENT == _fontmetrics.DESCENT

    body = re.search(r"GLYPHS: \[\(.*?\); \d+\] = \[\s*(.*?)\n\];", source, re.S)
    assert body
    advances = [int(value) for value in re.findall(r"\(\s*(-?\d+),", body.group(1))]
    first, last = constant("FIRST"), constant("LAST")
    ascii_count = last - first + 1
    for index, expected in enumerate(advances[:ascii_count]):
        char = chr(first + index)
        assert _fontmetrics.advance(char, float(_fontmetrics.BASE_PX)) == expected, (
            f"advance drift for {char!r}"
        )

    extra = re.search(r"EXTRA_CODEPOINTS: \[u32; \d+\] = \[\s*(.*?)\s*\];", source, re.S)
    assert extra
    codepoints = [int(v) for v in extra.group(1).replace("\n", "").split(",") if v.strip()]
    assert len(codepoints) + ascii_count == len(advances)
    for offset, codepoint in enumerate(codepoints):
        expected = advances[ascii_count + offset]
        got = _fontmetrics.advance(chr(codepoint), float(_fontmetrics.BASE_PX))
        assert got == expected, f"advance drift for U+{codepoint:04X}"


def test_hidden_tick_labels_do_not_reserve_tick_room() -> None:
    chart = _chart(
        y_label="value",
        y_values=[3600.0, 5400.0],
        style={"label_size": 14, "tick_label_size": 14},
        tick_label_strategy="none",
    )
    spec, _blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    assert plot["x"] == 62.0


def test_transparent_axis_text_does_not_reinflate_zero_padding() -> None:
    """The axis switches and measured gutter must compose."""
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[1_000_000.0, 2_000_000.0]),
        xy.x_axis(show=False),
        xy.y_axis(label="hidden title", show=False),
        width=320,
        height=180,
        padding=0,
    )
    spec, _blob = _payload(chart)
    _width, _height, _compact, plot = _svg.layout(spec)
    assert plot["x"] == 0.0
