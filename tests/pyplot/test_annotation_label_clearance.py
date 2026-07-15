"""Annotation arrows must not strike through their own labels.

matplotlib clips every annotation arrow at the text patch (patchA + 2pt
shrink). The shim's arrows carry a `label_clear` rectangle — the label's
estimated extents around the arrow start — and the shared geometry
(python/xy/_arrowgeom.py + js/src/51_annotations.js) trims the start to
where the departure tangent exits it.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._axes import _label_clear_box


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def _arrow_entry(ax):
    return next(e for e in ax._entries if e["kind"] == "@arrow")


def _callout_child(ax):
    return next(c for c in ax._chart_children() if c.kind == "callout")


def test_data_coordinate_annotate_arrow_clears_its_label():
    # The PDSH "local minimum" case: text at xytext (data coords), arrow
    # departing horizontally through where the label renders.
    fig, ax = plt.subplots()
    ax.plot(np.linspace(0, 20, 5), np.cos(np.linspace(0, 20, 5)))
    ax.annotate(
        "local minimum",
        xy=(5 * np.pi, -1),
        xytext=(2, -6),
        arrowprops=dict(arrowstyle="->", connectionstyle="angle3,angleA=0,angleB=-90"),
    )
    style = _arrow_entry(ax)["kwargs"]["style"]
    clear = [float(part) for part in style["label_clear"].split(",")]
    assert len(clear) == 4
    left, right, up, down = clear
    # Anchor "start": the text extends to the right; the baseline default
    # puts the ascent above the start point.
    assert right > left and up > down
    assert right > 0.5 * 13 * 10  # ~13 chars at >=10px each side of an em


def test_empty_label_and_shrink_emit_no_clearance():
    fig, ax = plt.subplots()
    ax.plot([0, 20], [0, 1])
    ax.annotate("", xy=(10, 0.5), xytext=(2, 0.1), arrowprops=dict(arrowstyle="->"))
    assert "label_clear" not in _arrow_entry(ax)["kwargs"]["style"]

    fig, ax = plt.subplots()
    ax.plot([0, 20], [0, 1])
    ax.annotate(
        "shrunk", xy=(10, 0.5), xytext=(2, 0.1), arrowprops=dict(facecolor="black", shrink=0.05)
    )
    # shrink moves the endpoints in data space; layering the text clearance on
    # top would double-clip.
    assert "label_clear" not in _arrow_entry(ax)["kwargs"]["style"]


def test_offset_callout_carries_label_clearance():
    fig, ax = plt.subplots()
    ax.plot([0, 20], [0, 1])
    ax.annotate(
        "Thanksgiving",
        xy=(10, 0.5),
        xytext=(-120, -60),
        textcoords="offset points",
        bbox=dict(boxstyle="round4,pad=.5", fc="0.9"),
        arrowprops=dict(arrowstyle="->", connectionstyle="angle,angleA=0,angleB=80,rad=20"),
    )
    style = _callout_child(ax).style
    clear = [float(part) for part in style["label_clear"].split(",")]
    left, right, _, _ = clear
    assert right > left  # anchor "start": text extends rightward
    assert style["gap_start"] > 0  # radial floor stays for away-side exits


def test_end_anchored_callout_clears_to_the_left():
    fig, ax = plt.subplots()
    ax.plot([0, 20], [0, 1])
    ax.annotate(
        "Christmas",
        xy=(10, 0.5),
        xytext=(-30, 0),
        textcoords="offset points",
        size=13,
        ha="right",
        va="center",
        arrowprops=dict(arrowstyle="wedge,tail_width=0.5"),
    )
    style = _callout_child(ax).style
    left, right, up, down = (float(part) for part in style["label_clear"].split(","))
    assert left > right  # text extends left of its end anchor
    assert up == down  # va="center" splits the height


def test_label_clear_box_estimates():
    assert _label_clear_box("", 14.0, "start", None) is None
    margin = 2.8 + 0.35 * 10.0  # 2pt shrink + matplotlib's visible bbox gap
    start = _label_clear_box("abcd", 10.0, "start", None)
    left, right, up, down = (float(part) for part in start.split(","))
    assert left == pytest.approx(margin, abs=0.1)  # margin-only away side
    assert right == pytest.approx(0.58 * 10.0 * 4 + margin, abs=0.1)
    assert up > down  # baseline default: ascent above the anchor
    middle = _label_clear_box("abcd", 10.0, "middle", "bottom")
    left, right, up, down = (float(part) for part in middle.split(","))
    assert left == right  # centered text splits the width
    assert up > down  # bottom-anchored label sits above the anchor
