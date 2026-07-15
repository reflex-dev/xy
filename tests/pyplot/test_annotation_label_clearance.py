"""Annotation arrows attach at the label like matplotlib's, measurably.

matplotlib draws every annotation arrow from the text patch CENTER (relpos
default (0.5, 0.5)), clipped at the patch edge plus the 2pt shrink. The
shim's arrows carry that as two shape-style keys resolved by the shared
geometry (python/xy/_arrowgeom.py + js/src/51_annotations.js):
``start_offset`` (anchor → text-box center, px) and ``label_clear`` (the
box extents around that center).

The reference test below asserts the *rendered pixel relations* recorded
from Matplotlib 3.11.0 — not screenshots — by running the real pipeline
(entries → spec → px transform → arrow geometry).
"""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy._arrowgeom import arrow_geometry
from xy._svg import layout
from xy.pyplot._axes import _label_attach_styles


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def _arrow_entry(ax):
    return next(e for e in ax._entries if e["kind"] == "@arrow")


def _callout_child(ax):
    return next(c for c in ax._chart_children() if c.kind == "callout")


def _annotation_px(fig):
    """(arrow start px, text anchor px) through the real spec pipeline —
    the same transform + shared geometry the client and exporters run."""
    spec, _ = fig._single().figure().build_payload()
    _, _, _, plot = layout(spec)
    (x0, x1), (y0, y1) = spec["x_axis"]["range"], spec["y_axis"]["range"]

    def px(x, y):
        return (
            plot["x"] + (x - x0) / (x1 - x0) * plot["w"],
            plot["y"] + (1 - (y - y0) / (y1 - y0)) * plot["h"],
        )

    arrow = next(a for a in spec["annotations"] if a["kind"] == "arrow")
    text = next(a for a in spec["annotations"] if a["kind"] == "text")
    geometry = arrow_geometry(
        *px(float(arrow["x0"]), float(arrow["y0"])),
        *px(float(arrow["x1"]), float(arrow["y1"])),
        arrow["style"],
    )
    return geometry["p0"], px(float(text["x"]), float(text["y"]))


def test_arrow_attaches_at_matplotlib_text_patch_relations():
    # The PDSH "local minimum" annotation at 640x480 / 13.89px font.
    # Matplotlib 3.11.0 reference (Text.get_window_extent +
    # arrow_patch._get_path_in_displaycoord, y down, relative to the text
    # anchor): text box spans x [+0, +106.0], y [-11.0, +3.3]; the arrow
    # starts at (+111.6, -5.5) — past the box edge, at its vertical CENTER
    # (anchor - 3.8px), NOT at the baseline anchor.
    fig, ax = plt.subplots()
    x = np.linspace(0, 20, 100)
    ax.plot(x, np.cos(x))
    ax.annotate(
        "local minimum",
        xy=(5 * np.pi, -1),
        xytext=(2, -6),
        arrowprops=dict(arrowstyle="->", connectionstyle="angle3,angleA=0,angleB=-90"),
    )
    (start_x, start_y), (anchor_x, anchor_y) = _annotation_px(fig)
    assert start_x - anchor_x == pytest.approx(111.6, abs=6.0)
    assert start_y - anchor_y == pytest.approx(-5.5, abs=3.5)


def test_up_left_arrow_exits_through_the_box_top():
    # Mirrored target up-left of the text. Matplotlib 3.11.0 reference: the
    # ray from the box center exits through the box TOP, so the start lands
    # at anchor + (+48.8, -16.4) — right of the anchor, above the text.
    fig, ax = plt.subplots()
    x = np.linspace(0, 20, 100)
    ax.plot(x, np.cos(x))
    ax.annotate(
        "local minimum",
        xy=(2.0, -1),
        xytext=(12, -6),
        arrowprops=dict(arrowstyle="->"),
    )
    (start_x, start_y), (anchor_x, anchor_y) = _annotation_px(fig)
    assert start_x - anchor_x == pytest.approx(48.8, abs=8.0)
    assert start_y - anchor_y == pytest.approx(-16.4, abs=6.0)


def test_empty_label_and_shrink_emit_no_clearance():
    fig, ax = plt.subplots()
    ax.plot([0, 20], [0, 1])
    ax.annotate("", xy=(10, 0.5), xytext=(2, 0.1), arrowprops=dict(arrowstyle="->"))
    style = _arrow_entry(ax)["kwargs"]["style"]
    assert "label_clear" not in style and "start_offset" not in style

    fig, ax = plt.subplots()
    ax.plot([0, 20], [0, 1])
    ax.annotate(
        "shrunk", xy=(10, 0.5), xytext=(2, 0.1), arrowprops=dict(facecolor="black", shrink=0.05)
    )
    # shrink moves the endpoints in data space; layering the text clearance on
    # top would double-clip.
    style = _arrow_entry(ax)["kwargs"]["style"]
    assert "label_clear" not in style and "start_offset" not in style


def test_offset_callout_attaches_at_its_box_center():
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
    offset_x, offset_y = (float(part) for part in style["start_offset"].split(","))
    left, right, up, down = (float(part) for part in style["label_clear"].split(","))
    assert offset_x > 0  # anchor "start": the box center is to the right
    assert offset_y < 0  # baseline default: the box center is above
    assert left == right and up == down  # extents are box-centered
    assert style["gap_start"] > 0  # 2pt shrink floor


def test_end_anchored_centered_callout_offsets_left_only():
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
    offset_x, offset_y = (float(part) for part in style["start_offset"].split(","))
    assert offset_x < 0  # anchor "end": box center left of the anchor
    assert offset_y == 0  # va="center": anchor already at box-center height


def test_label_attach_estimates():
    assert _label_attach_styles("", 14.0, "start", None) is None
    styles = _label_attach_styles("abcd", 10.0, "start", None)
    offset_x, offset_y = (float(part) for part in styles["start_offset"].split(","))
    width, height = 0.58 * 10.0 * 4, 1.2 * 10.0
    assert offset_x == pytest.approx(width / 2, abs=0.1)
    # baseline anchor: descent (~0.35em) hangs below, so the center is above
    assert offset_y == pytest.approx(-(height / 2 - 3.5), abs=0.1)
    left, right, up, down = (float(part) for part in styles["label_clear"].split(","))
    assert left == right == pytest.approx(width / 2 + 2.8 + 3.5, abs=0.1)
    assert up == down == pytest.approx(height / 2 + 2.8 + 3.5, abs=0.1)
    bottom = _label_attach_styles("abcd", 10.0, "middle", "bottom")
    offset_x, offset_y = (float(part) for part in bottom["start_offset"].split(","))
    assert offset_x == 0.0  # centered text: anchor already at center
    assert offset_y == pytest.approx(-height / 2, abs=0.1)  # box above anchor
