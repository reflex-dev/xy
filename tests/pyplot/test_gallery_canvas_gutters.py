"""Matplotlib's y-axis title sits clear of its tick labels; so must the shim's.

Measured against Matplotlib 3.11.1 on `examples/pdsh/data/births.csv`
(`examples/pdsh/pdsh_04_09_text_and_annotation.ipynb`, cell 23): the reference
puts the y title's ink at x 10.0..24.3 and the tick ink at 29.9..65.9 — a 5.6 px
gap. The shim used to draw the title at -3.0..13.5 over ticks reaching x -3.4,
because pyplot's rcParam fonts (13.89 px at 100 dpi) overrun the renderer's flat
62 px gutter and the notebook path pins a 41 px one.

The gutter is now measured in `_svg.layout()` from the ink it has to hold, so
these assertions read the emitted SVG geometry rather than a padding constant.
"""

from __future__ import annotations

import math
import re
from io import BytesIO
from xml.etree import ElementTree

import pytest

import xy.pyplot as plt
from xy import _fontmetrics, _svg

_ASCENT = _fontmetrics.ASCENT / _fontmetrics.BASE_PX
_DESCENT = _fontmetrics.DESCENT / _fontmetrics.BASE_PX
# `_mplfig._to_notebook_html` pins these to match Matplotlib's inline
# `bbox_inches="tight", pad_inches=.1` footprint at 100 dpi.
NOTEBOOK_PADDING = [15.0, 20.0, 34.0, 41.0]


def teardown_function() -> None:
    plt.close("all")


def _title_and_tick_boxes(svg: str, plot: dict[str, float], title: str):
    root = ElementTree.fromstring(svg)
    title_box = None
    ticks: list[tuple[float, float]] = []
    for element in root.iter():
        if not element.tag.endswith("text"):
            continue
        text = "".join(element.itertext())
        size = float(element.attrib.get("font-size", 12))
        x = float(element.attrib.get("x", 0))
        rotation = re.match(r"rotate\((-?[\d.]+)", element.attrib.get("transform", ""))
        angle = float(rotation.group(1)) if rotation else 0.0
        if text == title and abs(abs(angle) - 90) < 0.5:
            title_box = (x - _ASCENT * size, x + _DESCENT * size)
        elif not rotation and element.attrib.get("text-anchor") == "end" and x <= plot["x"]:
            ticks.append((x - _fontmetrics.advance(text, size), x))
    assert title_box is not None, f"no rotated {title!r} axis title in the SVG"
    assert ticks, "no y tick labels in the SVG"
    pin = max(box[1] for box in ticks)
    ticks = [box for box in ticks if math.isclose(box[1], pin, abs_tol=0.01)]
    return title_box, (min(box[0] for box in ticks), max(box[1] for box in ticks))


def _assert_clear(svg: str, plot: dict[str, float], title: str) -> tuple[float, float]:
    title_box, tick_span = _title_and_tick_boxes(svg, plot, title)
    overlap = min(title_box[1], tick_span[1]) - max(title_box[0], tick_span[0])
    assert overlap < 0, (
        f"{title!r} at {title_box} overlaps tick labels {tick_span} by {overlap:.1f}px"
    )
    assert title_box[0] > 0, f"{title!r} ink starts at x={title_box[0]:.1f} — clipped"
    assert tick_span[0] > 0, f"tick ink starts at x={tick_span[0]:.1f} — clipped"
    return title_box[1], tick_span[0]


def _svg_geometry(ax, width, height, padding=None):
    if padding is not None:
        ax._padding = list(padding)
    spec, blob = ax._build_chart(width, height).figure().build_payload()
    _w, _h, _compact, plot = _svg.layout(spec)
    return spec, _svg.render_svg(spec, blob), plot


def test_numeric_y_ticks_keep_the_axis_title_clear() -> None:
    """The pdsh cell-23 shape: four-digit ticks under a long rotated title."""
    _fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot([0, 1], [3600, 5400])
    ax.set_ylim(3600, 5400)
    ax.set_ylabel("average daily births")

    _spec, svg, plot = _svg_geometry(ax, 1200, 400)
    title_right, tick_left = _assert_clear(svg, plot, "average daily births")
    # Matplotlib 3.11.1 leaves 5.6 px here, and the shim's title font is the
    # same 13.89 px, so the 0.4 em rule reproduces the reference gap.
    assert abs((tick_left - title_right) - 5.6) < 0.1
    assert plot["x"] > 62.0, "the flat default gutter cannot hold this axis's ink"


def test_notebook_padding_still_reserves_the_measured_gutter() -> None:
    """The reported defect: `padding[3] = 41` is 27 px short of the ink.

    An authored padding is a floor. The notebook path pins one to match
    Matplotlib's inline canvas, and before this change that pin was also the
    effective gutter — so the title landed on top of the 5400/5200/5000 labels.
    """
    _fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot([0, 1], [3600, 5400])
    ax.set_ylim(3600, 5400)
    ax.set_ylabel("average daily births")

    spec, svg, plot = _svg_geometry(ax, 992, 356, padding=NOTEBOOK_PADDING)
    assert spec["padding"] == NOTEBOOK_PADDING, "the authored padding still ships as authored"
    assert plot["x"] > NOTEBOOK_PADDING[3], "the measured gutter has to win over the pin"
    _assert_clear(svg, plot, "average daily births")


def test_long_category_ticks_keep_the_axis_title_clear() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    labels = [f"Question {index}" for index in range(1, 7)]
    ax.barh(labels, [10, 20, 30, 40, 50, 60])
    ax.set_ylabel("survey question")

    spec, svg, plot = _svg_geometry(ax, 640, 480)
    assert spec["axes"]["y"]["categories"] == labels
    _assert_clear(svg, plot, "survey question")
    assert plot["x"] > 100.0

    # The same reservation reaches savefig, not just the in-process layout.
    output = BytesIO()
    fig.savefig(output, format="svg")
    root = ElementTree.fromstring(output.getvalue())
    question = next(
        element
        for element in root.iter()
        if element.tag.endswith("text") and "".join(element.itertext()) == "Question 1"
    )
    ink_left = float(question.attrib["x"]) - _fontmetrics.advance(
        "Question 1", float(question.attrib["font-size"])
    )
    assert ink_left > 0


def test_long_category_ticks_under_notebook_padding_keep_the_title_clear() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8))
    labels = [f"Question {index}" for index in range(1, 7)]
    ax.barh(labels, [10, 20, 30, 40, 50, 60])
    ax.set_ylabel("survey question")

    _spec, svg, plot = _svg_geometry(ax, 536, 404, padding=NOTEBOOK_PADDING)
    _assert_clear(svg, plot, "survey question")


def test_short_category_ticks_keep_the_core_default_gutter() -> None:
    """Short ticks do not widen Matplotlib's default axes rectangle."""
    _fig, ax = plt.subplots()
    ax.barh(["A", "B"], [1, 2])

    spec, _svg_text, plot = _svg_geometry(ax, 640, 480)
    assert spec["padding"] == pytest.approx([57.6, 64.0, 52.8, 80.0])
    assert plot["x"] == 80.0
