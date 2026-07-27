"""Annotation bbox/text fidelity against Matplotlib, on real emitted output.

Measured against matplotlib 3.11.1 rendering cell 23 of
``examples/pdsh/pdsh_04_09_text_and_annotation.ipynb`` with the real
``examples/pdsh/data/births.csv``. The reference values quoted in the
assertions come from that figure's own SVG/PNG, not from taste:

- ``bbox=dict(boxstyle="round", alpha=0.1)`` → Matplotlib emits
  ``style="fill: #1f77b4; opacity: 0.1; stroke: #000000"``. ``opacity`` is
  *element* opacity, so face and edge are dimmed together.
- an arrow-less ``annotate`` ("Labor Day Weekend") → Matplotlib paints it
  with ``rcParams["text.color"]``, i.e. pure black; its PNG's darkest
  glyph pixel is ``(0, 0, 0)``.
- ``boxstyle="round"`` at 10 pt → a 3.00 pt (4.17 px at 96 dpi) corner
  radius in Matplotlib's own path; ``round4`` curves rather than arcs.
"""

from __future__ import annotations

import struct
from typing import Any
from xml.etree import ElementTree

import pytest

import xy.pyplot as plt
from xy import _raster


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def _annotation_rects(fig, ax) -> list[dict[str, str]]:
    """Every stroked ``<rect>`` in the emitted SVG, as raw attributes."""
    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    root = ElementTree.fromstring(svg)
    return [e.attrib for e in root.iter() if e.tag.endswith("rect") and "stroke" in e.attrib]


def _annotation_texts(fig, ax) -> dict[str, dict[str, str]]:
    """Emitted SVG ``<text>`` attributes, keyed by the rendered string."""
    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    root = ElementTree.fromstring(svg)
    out: dict[str, dict[str, str]] = {}
    for e in root.iter():
        if not e.tag.endswith("text"):
            continue
        text = "".join(e.itertext()).strip()
        if text:
            out[text] = e.attrib
    return out


def _svg_root(fig, ax) -> ElementTree.Element:
    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    return ElementTree.fromstring(svg)


def _clip_rect(root: ElementTree.Element) -> dict[str, str]:
    clip = next(e for e in root.iter() if e.tag.endswith("clipPath"))
    return next(e.attrib for e in clip if e.tag.endswith("rect"))


def _first_fill(cmd: _raster._Cmd) -> tuple[int, list[tuple[float, float]], tuple[int, ...]]:
    """Decode the first FILL command out of a raw native display list.

    Layout (little-endian, must match ``src/raster.rs``): opcode byte,
    u32 vertex count, 2 f32 per vertex, then 4 bytes of RGBA.
    """
    buf = bytes(cmd.buf)
    assert buf[0] == _raster._FILL, f"expected a FILL opcode, got {buf[0]}"
    (count,) = struct.unpack_from("<I", buf, 1)
    coords = struct.unpack_from(f"<{count * 2}f", buf, 5)
    pts = list(zip(coords[0::2], coords[1::2], strict=True))
    rgba = tuple(buf[5 + count * 8 : 9 + count * 8])
    return count, pts, rgba


def _first_stroke_rgba(cmd: _raster._Cmd) -> tuple[int, ...]:
    """RGBA of the first STROKE command in a raw native display list."""
    buf = bytes(cmd.buf)
    offset = 0
    while offset < len(buf):
        if buf[offset] == _raster._STROKE:
            (count,) = struct.unpack_from("<I", buf, offset + 1)
            base = offset + 5 + count * 8 + 4  # points, then f32 width
            return tuple(buf[base : base + 4])
        if buf[offset] == _raster._FILL:
            (count,) = struct.unpack_from("<I", buf, offset + 1)
            offset += 5 + count * 8 + 4
            continue
        raise AssertionError(f"unexpected opcode {buf[offset]} at {offset}")
    raise AssertionError("no STROKE command emitted")


# --- D1: bbox alpha dims the edge as well as the face ------------------------


def test_bbox_alpha_composites_into_the_edge_like_matplotlib() -> None:
    """Matplotlib's patch ``alpha`` dims face *and* edge (element opacity)."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Christmas",
        xy=(0.9, 0.1),
        xytext=(-30, 0),
        textcoords="offset points",
        ha="right",
        va="center",
        bbox=dict(boxstyle="round", alpha=0.1),
        arrowprops=dict(arrowstyle="wedge,tail_width=0.5", alpha=0.1),
    )

    (rect,) = _annotation_rects(fig, ax)
    # Face keeps the alpha it always had; the edge now carries it too, so the
    # default black edge is as invisible as Matplotlib's.
    assert rect["fill"] == "rgba(31,119,180,0.1)"
    assert rect["stroke"] == "rgba(0,0,0,0.1)"


def test_bbox_without_alpha_keeps_an_opaque_edge() -> None:
    """No ``alpha`` means no compositing — Matplotlib draws a solid edge."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Thanksgiving",
        xy=(0.5, 0.5),
        xytext=(-40, -30),
        textcoords="offset points",
        bbox=dict(boxstyle="round4,pad=.5", fc="0.9"),
        arrowprops=dict(arrowstyle="->"),
    )

    (rect,) = _annotation_rects(fig, ax)
    assert rect["fill"] == "rgb(230,230,230)"  # fc="0.9"
    assert rect["stroke"] == "black"


def test_bbox_alpha_dims_an_explicit_edge_colour() -> None:
    """``alpha`` applies to whatever ``ec`` resolves to, not just to black."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    # "0.4" is Matplotlib's grey shorthand, the form the pdsh corpus uses.
    ax.text(0.5, 0.5, "boxed", bbox=dict(boxstyle="round", fc="none", ec="0.4", alpha=0.5))

    (rect,) = _annotation_rects(fig, ax)
    assert rect["fill"] == "none"
    assert rect["stroke"] == "rgba(102,102,102,0.5)"


def test_css_named_edge_colour_receives_the_patch_alpha() -> None:
    """CSS/Matplotlib colour names use the same patch alpha as hex colours."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.text(0.5, 0.5, "boxed", bbox=dict(boxstyle="round", fc="none", ec="gray", alpha=0.5))

    (rect,) = _annotation_rects(fig, ax)
    assert rect["stroke"] == "rgba(128,128,128,0.5)"


def test_bbox_alpha_overrides_embedded_face_and_edge_alpha() -> None:
    """Matplotlib's patch alpha replaces, rather than multiplies, colour alpha."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.text(
        0.5,
        0.5,
        "boxed",
        bbox=dict(
            boxstyle="round",
            fc=(1.0, 0.0, 0.0, 0.25),
            ec=(0.0, 0.0, 1.0, 0.75),
            alpha=0.4,
        ),
    )

    (rect,) = _annotation_rects(fig, ax)
    assert rect["fill"] == "rgba(255,0,0,0.4)"
    assert rect["stroke"] == "rgba(0,0,255,0.4)"


def test_bbox_alpha_reaches_the_native_raster_stroke_colour() -> None:
    """The native display list carries the same composited edge alpha."""
    style: dict[str, Any] = {
        "background": "rgba(31,119,180,0.1)",
        "border": "1px solid rgba(0,0,0,0.1)",
        "padding": "4px",
    }
    cmd = _raster._Cmd(1.0)
    _raster._emit_text_box(cmd, style, ["Christmas"], 100.0, 100.0, 13.2, 11.0, 0)

    # 0.1 alpha -> round(0.1 * 255) == 26 in the RGBA byte quad.
    assert _first_stroke_rgba(cmd) == (0, 0, 0, 26)


# --- D2: an arrow-less annotation is Matplotlib-black, not a design token ----


def test_arrowless_annotation_text_is_matplotlib_black_in_svg() -> None:
    """Matplotlib paints Text with rcParams["text.color"] (black)."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Labor Day Weekend",
        xy=(0.5, 0.9),
        xycoords="data",
        ha="center",
        xytext=(0, -20),
        textcoords="offset points",
    )

    texts = _annotation_texts(fig, ax)
    # Previously "#667085", the SVG exporter's own annotation-label token.
    assert texts["Labor Day Weekend"]["fill"] == "black"


def test_arrowless_annotation_text_is_black_in_the_native_stream(monkeypatch) -> None:
    """The native text command must carry opaque black, not a design token.

    Before, this label reached the rasterizer as ``rgba(32,32,32,.85)`` —
    the ``_TEXT`` token — which composites to (65, 65, 65) on white, while
    Matplotlib's own PNG bottoms out at (0, 0, 0).
    """
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Labor Day Weekend",
        xy=(0.5, 0.9),
        xycoords="data",
        ha="center",
        xytext=(0, -20),
        textcoords="offset points",
    )

    seen: list[tuple[str, tuple[int, ...]]] = []
    original = _raster._Cmd.text

    def spy(self, x, y, anchor, size, color, text, *args, **kwargs):
        seen.append((str(text), tuple(color)))
        return original(self, x, y, anchor, size, color, text, *args, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", spy)
    fig._to_png()

    labels = [color for text, color in seen if text == "Labor Day Weekend"]
    assert labels, f"annotation label never reached the rasterizer; saw {seen}"
    assert labels[0] == (0, 0, 0, 255)


def test_explicit_text_colour_still_wins_over_the_matplotlib_default() -> None:
    """``color=`` must not be overridden by the pinned default (pdsh cell 13)."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.text(0.5, 0.5, "Christmas ", ha="right", size=10, color="gray")

    texts = _annotation_texts(fig, ax)
    assert texts["Christmas"]["fill"] == "gray"


# --- D3: an exported boxstyle="round" box has rounded corners ----------------


def test_axes_fraction_multiline_top_bbox_stays_inside_axes_in_svg() -> None:
    """``va='top'`` aligns the full text block, as in placing_text_boxes.py."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.text(
        0.05,
        0.95,
        "first\nsecond\nthird",
        transform=ax.transAxes,
        fontsize=14,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )

    root = _svg_root(fig, ax)
    clip = _clip_rect(root)
    (bbox,) = _annotation_rects(fig, ax)
    axes_top = float(clip["y"])
    axes_height = float(clip["height"])
    point_scale = fig.dpi / 72.0
    font_size = 14.0 * point_scale
    pad = 0.3 * font_size
    expected_top = axes_top + 0.05 * axes_height - pad

    assert float(bbox["y"]) == pytest.approx(expected_top, abs=0.02)
    assert float(bbox["y"]) > axes_top


def test_axes_fraction_multiline_top_bbox_stays_inside_axes_in_raster_stream() -> None:
    """The native display list uses the same full-block top anchor as SVG."""
    plot = {"x": 80.0, "y": 57.6, "w": 496.0, "h": 369.6}
    font_size = 14.0 * 100.0 / 72.0
    pad = 0.3 * font_size
    annotation = {
        "kind": "text",
        "x": 0.05,
        "y": 0.95,
        "text": "first\nsecond\nthird",
        "style": {
            "coordinate_space": "axes_fraction",
            "vertical_align": "top",
            "font_size": font_size,
            "background": "rgba(245,222,179,0.5)",
            "border": "1px solid rgba(0,0,0,0.5)",
            "padding": f"{pad}px",
        },
    }
    cmd = _raster._Cmd(1.0)
    _raster._emit_annotations(
        cmd,
        [annotation],
        lambda value: value,
        lambda value: value,
        plot,
        640.0,
        480.0,
        phase="text",
    )

    _count, points, _rgba = _first_fill(cmd)
    expected_top = plot["y"] + 0.05 * plot["h"] - pad
    assert min(y for _, y in points) == pytest.approx(expected_top, abs=0.02)
    assert min(y for _, y in points) > plot["y"]


@pytest.mark.parametrize("verticalalignment", (None, "baseline"))
def test_axes_fraction_multiline_baseline_bbox_grows_upward_in_svg(
    verticalalignment: str | None,
) -> None:
    """Default/explicit baseline pins the last line, as in anscombe.py."""
    fig, ax = plt.subplots(figsize=(3, 3))
    ax.plot([0.0, 1.0], [0.0, 1.0])
    kwargs: dict[str, Any] = {}
    if verticalalignment is not None:
        kwargs["verticalalignment"] = verticalalignment
    ax.text(
        0.95,
        0.07,
        "mean = 7.50\nstd = 1.94\nr = 0.82",
        transform=ax.transAxes,
        horizontalalignment="right",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="blanchedalmond", edgecolor="orange"),
        **kwargs,
    )

    root = _svg_root(fig, ax)
    clip = _clip_rect(root)
    (bbox,) = _annotation_rects(fig, ax)
    label = next(
        element
        for element in root.iter()
        if element.tag.endswith("text") and "mean = 7.50" in "".join(element.itertext())
    )
    baselines = [
        float(element.attrib["y"])
        for element in label
        if element.tag.endswith("tspan") and "y" in element.attrib
    ]
    axes_top = float(clip["y"])
    axes_height = float(clip["height"])
    axes_bottom = axes_top + axes_height
    anchor_y = axes_top + 0.93 * axes_height
    font_size = 9.0 * fig.dpi / 72.0
    pad = 0.3 * font_size
    bbox_bottom = float(bbox["y"]) + float(bbox["height"])

    assert baselines[-1] == pytest.approx(anchor_y, abs=0.02)
    assert bbox_bottom == pytest.approx(anchor_y + 0.2 * font_size + pad, abs=0.02)
    assert bbox_bottom < axes_bottom


@pytest.mark.parametrize("vertical_align", (None, "baseline"))
def test_axes_fraction_multiline_baseline_bbox_grows_upward_in_raster_stream(
    vertical_align: str | None,
) -> None:
    """The native display list shares Matplotlib's last-line baseline anchor."""
    plot = {"x": 37.5, "y": 36.0, "w": 232.5, "h": 231.0}
    font_size = 9.0 * 100.0 / 72.0
    pad = 0.3 * font_size
    style: dict[str, Any] = {
        "coordinate_space": "axes_fraction",
        "font_size": font_size,
        "background": "blanchedalmond",
        "border": "1px solid orange",
        "padding": f"{pad}px",
    }
    if vertical_align is not None:
        style["vertical_align"] = vertical_align
    annotation = {
        "kind": "text",
        "x": 0.95,
        "y": 0.07,
        "text": "mean = 7.50\nstd = 1.94\nr = 0.82",
        "anchor": "end",
        "style": style,
    }
    cmd = _raster._Cmd(1.0)
    _raster._emit_annotations(
        cmd,
        [annotation],
        lambda value: value,
        lambda value: value,
        plot,
        300.0,
        300.0,
        phase="text",
    )

    _count, points, _rgba = _first_fill(cmd)
    anchor_y = plot["y"] + 0.93 * plot["h"]
    expected_bottom = anchor_y + 0.2 * font_size + pad

    assert max(y for _, y in points) == pytest.approx(expected_bottom, abs=0.02)
    assert max(y for _, y in points) < plot["y"] + plot["h"]


def test_round_boxstyle_exports_a_non_zero_corner_radius_in_svg() -> None:
    """``rx`` must be present and non-zero, as CSS border-radius already was."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Independence Day",
        xy=(0.5, 0.5),
        bbox=dict(boxstyle="round", fc="none", ec="gray"),
        xytext=(10, -40),
        textcoords="offset points",
        ha="center",
        arrowprops=dict(arrowstyle="->"),
    )

    (rect,) = _annotation_rects(fig, ax)
    assert float(rect["rx"]) > 0.0
    # Matplotlib's own path radius for boxstyle="round" at 10 pt is 3.00 pt
    # (4.17 px at 96 dpi); the shim's CSS approximation is 5 px.
    assert float(rect["rx"]) == pytest.approx(5.0)


def test_exported_round_box_is_wide_enough_for_a_mixed_width_label() -> None:
    """The static width heuristic must not let ``Thanksgiving`` escape its box."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Thanksgiving",
        xy=(0.5, 0.5),
        bbox=dict(boxstyle="round4,pad=.5", fc="0.9"),
    )

    (rect,) = _annotation_rects(fig, ax)
    # 11 px font with 5.5 px padding per side. The old flat 0.48em estimate
    # produced 74.36 px and visibly clipped the final glyphs.
    assert float(rect["width"]) > 80.0


def test_square_boxstyle_keeps_square_corners_in_svg() -> None:
    """Only the rounded box styles round — ``square`` must emit no ``rx``."""
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.text(0.5, 0.5, "plain", bbox=dict(boxstyle="square", fc="0.9"))

    (rect,) = _annotation_rects(fig, ax)
    assert "rx" not in rect


def test_round_boxstyle_exports_rounded_corners_in_the_native_stream() -> None:
    """The FILL polygon gains arc vertices instead of four square corners."""
    style: dict[str, Any] = {
        "background": "rgb(230,230,230)",
        "border": "1px solid black",
        "padding": "4px",
        "border_radius": 8.0,
    }
    cmd = _raster._Cmd(1.0)
    _raster._emit_text_box(cmd, style, ["Thanksgiving"], 100.0, 100.0, 13.2, 11.0, 0)
    count, pts, _rgba = _first_fill(cmd)

    # 4 corners x (4 arc steps + 1) vertices, versus 4 for a square rect.
    assert count == 20
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    # A rounded corner means no vertex sits at the rect's own corner.
    assert (min(xs), min(ys)) not in pts


def test_square_box_keeps_a_four_vertex_native_polygon() -> None:
    """Without ``border_radius`` the native box is the plain rect it was."""
    style: dict[str, Any] = {
        "background": "rgb(230,230,230)",
        "border": "1px solid black",
        "padding": "4px",
    }
    cmd = _raster._Cmd(1.0)
    _raster._emit_text_box(cmd, style, ["Thanksgiving"], 100.0, 100.0, 13.2, 11.0, 0)

    count, _pts, _rgba = _first_fill(cmd)
    assert count == 4


def test_corner_radius_is_clamped_to_the_box_like_css() -> None:
    """An absurd radius must not invert the polygon or escape the box."""
    style: dict[str, Any] = {
        "background": "rgb(230,230,230)",
        "padding": "2px",
        "border_radius": 500.0,
    }
    cmd = _raster._Cmd(1.0)
    _raster._emit_text_box(cmd, style, ["x"], 100.0, 100.0, 13.2, 11.0, 0)
    _count, pts, _rgba = _first_fill(cmd)

    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert width > 0 and height > 0
    # Clamped to half the shorter side, so the polygon still spans the box.
    assert height == pytest.approx(11.0 + 4.0, abs=1e-3)
