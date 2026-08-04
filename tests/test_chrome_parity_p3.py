"""Static-chrome parity, phase 3: annotation chrome.

The two standing gates every assertion here serves (plan §0.5/§9):

1. UNSTYLED output stays byte-identical — every new emission is strictly
   conditional on a declaration being present.
2. Everything emitted must round-trip to PDF; everything undrawable is
   recorded (§28), never silent.

The family's named risks are pinned executable: the two-vocabulary collision
between the pyplot text-box style keys and the slot CSS vocabulary (the
merge is group-wise, narrower wins), and the labels-container stacking
conflict (flag D).
"""

from __future__ import annotations

import re
import struct

import numpy as np
import pytest

import xy
from xy import _raster
from xy._pdf import svg_to_pdf


def _line() -> object:
    return xy.line([0.0, 1.0, 2.0], [0.0, 2.0, 1.0], name="series")


def _svg_of(chart: xy.Chart) -> str:
    return chart.figure().to_svg()


def _raster_of(chart: xy.Chart) -> np.ndarray:
    return _raster.render_raster(*chart.figure().build_payload(), scale=1)


def _rects(svg: str) -> list[str]:
    return re.findall(r"<rect[^>]*/>", svg)


def _strokes(buf: bytes) -> list[dict[str, object]]:
    """Every STROKE command in a raw display list, decoded."""
    out: list[dict[str, object]] = []
    offset = 0
    while offset < len(buf):
        op = buf[offset]
        if op == _raster._STROKE:
            (count,) = struct.unpack_from("<I", buf, offset + 1)
            base = offset + 5 + count * 8
            (width,) = struct.unpack_from("<f", buf, base)
            rgba = tuple(buf[base + 4 : base + 8])
            closed = buf[base + 8]
            (dash_len,) = struct.unpack_from("<I", buf, base + 9)
            dashes = struct.unpack_from(f"<{dash_len}f", buf, base + 13)
            out.append({"width": width, "rgba": rgba, "closed": closed, "dash": list(dashes)})
            offset = base + 13 + dash_len * 4 + 1
        elif op == _raster._FILL:
            (count,) = struct.unpack_from("<I", buf, offset + 1)
            offset += 5 + count * 8 + 4
        elif op == _raster._CLIP:
            offset += 17
        else:
            # Anything else ends the region these tests decode.
            break
    return out


# -- annotation_label ---------------------------------------------------------


def test_annotation_label_slot_leaves_a_trace_in_both_writers() -> None:
    # The verified zero-trace bug: styles={'annotation_label': ...} used to
    # reach neither writer.
    plain = xy.line_chart(_line(), xy.text(0.5, 0.5, "note"))
    styled = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={"annotation_label": {"fill": "#123456"}},
    )
    svg = _svg_of(styled)
    label = next(t for t in re.findall(r"<text[^>]*>.*?</text>", svg) if ">note<" in t)
    assert 'fill="#123456"' in label
    assert not (_raster_of(plain) == _raster_of(styled)).all()


def test_unstyled_annotation_output_is_byte_identical() -> None:
    # The standing gate at this family's door: an empty slot declaration and
    # no declaration at all produce the same bytes in both writers.
    def chart(**kwargs):
        return xy.line_chart(
            _line(),
            xy.text(0.5, 0.5, "note"),
            xy.hline(1.5, text="target"),
            **kwargs,
        )

    assert _svg_of(chart()) == _svg_of(chart(styles={"annotation_label": {}}))
    assert (_raster_of(chart()) == _raster_of(chart(styles={"annotation_label": {}}))).all()


def test_the_annotation_own_style_wins_over_the_slot_per_group() -> None:
    # Browser order: _applySlot runs before the per-annotation inline styles,
    # so the annotation's own declaration is the narrower selector — in BOTH
    # directions of the paint group (`color` as well as `label_color`).
    slot = {"annotation_label": {"fill": "#0000ff", "background": "#0000ee"}}
    own_color = xy.line_chart(_line(), xy.text(0.5, 0.5, "note", color="#ff0000"), styles=slot)
    svg = _svg_of(own_color)
    label = next(t for t in re.findall(r"<text[^>]*>.*?</text>", svg) if ">note<" in t)
    assert 'fill="#ff0000"' in label and "#0000ff" not in label

    own_box = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note", style={"background": "#00ff00"}),
        styles=slot,
    )
    boxes = [r for r in _rects(_svg_of(own_box)) if "#00ff00" in r]
    assert boxes and not any("#0000ee" in r for r in _rects(_svg_of(own_box)))


def test_four_value_css_padding_reads_top_right_bottom_left() -> None:
    # Both historical parsers read tokens [0]/[1] only, silently misreading
    # 4-value CSS. The shared lowering reads the real sides.
    def box(padding: str) -> dict[str, float]:
        chart = xy.line_chart(
            _line(),
            xy.text(0.5, 0.5, "pad", style={"background": "#ffee88", "padding": padding}),
        )
        rect = next(r for r in _rects(_svg_of(chart)) if "#ffee88" in r)
        return {
            key: float(re.search(rf'{key}="([-\d.]+)"', rect).group(1))
            for key in ("x", "y", "width", "height")
        }

    base = box("0")
    padded = box("1px 2px 3px 4px")
    assert padded["x"] == base["x"] - 4  # left
    assert padded["y"] == base["y"] - 1  # top
    assert padded["width"] == base["width"] + 4 + 2  # left + right
    assert padded["height"] == base["height"] + 1 + 3  # top + bottom
    # The 2-value spelling keeps its historical (vertical, horizontal) read.
    two = box("6px 10px")
    assert two["x"] == base["x"] - 10 and two["height"] == base["height"] + 12


def test_dashed_border_style_renders_dasharray_in_svg_and_dash_in_raster() -> None:
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="s"),
        xy.text(
            0.5,
            0.5,
            "note",
            style={"background": "#fff", "border": "2px dashed #123456"},
        ),
    )
    rect = next(r for r in _rects(_svg_of(chart)) if "#123456" in r)
    assert 'stroke-dasharray="7.4 3.2"' in rect

    style = {"background": "#fff", "border": "2px dashed #123456"}
    cmd = _raster._Cmd(1.0)
    _raster._emit_text_box(cmd, style, ["note"], 100.0, 100.0, 13.2, 11.0, 0)
    (stroke,) = _strokes(bytes(cmd.buf))
    assert stroke["dash"] == [pytest.approx(7.4), pytest.approx(3.2)]
    assert stroke["closed"] == 1


def test_slot_box_shadow_draws_the_offset_rect_under_the_frame() -> None:
    chart = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={
            "annotation_label": {
                "background": "#ffee88",
                "box_shadow": "2px 3px rgba(0,0,0,0.3)",
            }
        },
    )
    rects = _rects(_svg_of(chart))
    shadow = next(r for r in rects if "rgba(0,0,0,0.3)" in r)
    frame = next(r for r in rects if "#ffee88" in r)
    assert rects.index(shadow) == rects.index(frame) - 1  # under the frame
    dx = float(re.search(r'x="([-\d.]+)"', shadow).group(1)) - float(
        re.search(r'x="([-\d.]+)"', frame).group(1)
    )
    assert dx == 2.0
    # Blur is not representable; it must be dropped LOUDLY, not approximated.
    from xy._svg import annotation_text_box

    box = annotation_text_box(
        {"background": "#fff", "box-shadow": "0 4px 12px #000"},
        ["x"],
        0.0,
        0.0,
        13.2,
        11.0,
        "start",
    )
    assert box.shadow is None
    assert any("blur" in reason for reason in box.unrepresentable)


def test_em_slot_values_are_honored_via_the_merged_view() -> None:
    # Schema v1 refuses relative units, so em declarations ride the writer
    # view; the merge resolves them in the label's own unit domain (11px
    # base) instead of silently dropping them — invariant §9.10.
    chart = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={"annotation_label": {"font_size": "1.2em", "padding": "1em"}},
    )
    svg = _svg_of(chart)
    label = next(t for t in re.findall(r"<text[^>]*>.*?</text>", svg) if ">note<" in t)
    assert 'font-size="13.2"' in label  # 1.2 x 11px


def test_slot_typography_reaches_both_writers() -> None:
    plain = xy.line_chart(_line(), xy.text(0.5, 0.5, "note"))
    bold = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={"annotation_label": {"font_weight": 700}},
    )
    italic = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={"annotation_label": {"font_style": "italic"}},
    )
    assert 'font-weight="700"' in _svg_of(bold)
    assert 'font-style="italic"' in _svg_of(italic)
    base = _raster_of(plain)
    assert not (base == _raster_of(bold)).all(), "the bold atlas face must be selected"
    assert not (base == _raster_of(italic)).all(), "the italic atlas face must be selected"


def test_styled_annotation_labels_round_trip_to_pdf() -> None:
    # Everything the slot can emit, through the closed subset in one pass:
    # paint, emphasis, letter-spacing (P0.1), box with dashed border, radius
    # and offset shadow.
    chart = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={
            "annotation_label": {
                "fill": "#123456",
                "font_style": "italic",
                "letter_spacing": "2px",
                "background": "#ffee88",
                "border_color": "#334155",
                "border_style": "dashed",
                "border_radius": "6px",
                "padding": "4px",
                "box_shadow": "2px 3px rgba(0,0,0,0.3)",
            }
        },
    )
    pdf = svg_to_pdf(_svg_of(chart))
    assert pdf[:4] == b"%PDF"
    assert b"Helvetica-Oblique" in pdf


def test_mathtext_annotation_pdf_raises_the_documented_fence() -> None:
    # P0.1 fenced nested tspans rather than supporting them: a mathtext
    # annotation must raise the closed-subset error, never emit silently
    # broken text.
    chart = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "x_i", style={"math_italic_ranges": "0:3"}),
    )
    svg = _svg_of(chart)
    assert '<tspan font-style="italic">' in svg
    with pytest.raises(ValueError, match="unsupported SVG feature"):
        svg_to_pdf(svg)


def test_annotation_label_preflight_routes_text_and_box_props() -> None:
    figure = xy.line_chart(
        _line(),
        xy.text(0.5, 0.5, "note"),
        styles={
            "annotation_label": {
                "background": "#fff",
                "border_radius": "4px",
                "fill": "#123456",
                "outline_color": "#badbad",
            }
        },
    ).figure()
    report = figure.style_compatibility_report(target="png")
    (finding,) = [f for f in report.findings if f.slot == "annotation_label"]
    assert set(finding.kept) >= {"background", "border-radius", "fill"}
    assert finding.lost == ("outline-color",)


# -- annotation_layer ---------------------------------------------------------


def test_layer_opacity_wraps_shapes_in_a_group_and_survives_pdf() -> None:
    chart = xy.line_chart(
        _line(),
        xy.hline(1.5, text="target"),
        xy.marker(1.0, 1.0),
        styles={"annotation_layer": {"opacity": 0.5}},
    )
    svg = _svg_of(chart)
    assert '<g opacity="0.5">' in svg
    # The group wraps shapes only — the label rides the labels container.
    group = svg.split('<g opacity="0.5">', 1)[1].split("</g>", 1)[0]
    assert "<line" in group and ">target<" not in group
    assert svg_to_pdf(svg)[:4] == b"%PDF"
    # Strictly declaration-gated in both writers.
    plain = xy.line_chart(_line(), xy.hline(1.5, text="target"), xy.marker(1.0, 1.0))
    empty = xy.line_chart(
        _line(),
        xy.hline(1.5, text="target"),
        xy.marker(1.0, 1.0),
        styles={"annotation_layer": {}},
    )
    assert _svg_of(plain) == _svg_of(empty)
    assert (_raster_of(plain) == _raster_of(empty)).all()


def test_layer_opacity_folds_per_primitive_in_raster_with_double_blend() -> None:
    # The recorded divergence made executable: the display list has no group
    # compositing, so two overlapping opaque bands under layer opacity 0.5
    # blend TWICE where they overlap (darker), while the SVG group dims the
    # union once (uniform). Both facts are asserted so the delta cannot rot
    # silently.
    def chart(**styles):
        return xy.line_chart(
            xy.line([0.0, 4.0], [0.0, 4.0], name="s"),
            xy.x_band(1.0, 2.5, style={"color": "#2563eb", "opacity": 1.0}),
            xy.x_band(1.5, 3.0, style={"color": "#2563eb", "opacity": 1.0}),
            **styles,
        )

    dimmed = _raster_of(chart(styles={"annotation_layer": {"opacity": 0.5}}))
    full = _raster_of(chart())
    assert not (dimmed == full).all()
    height, width = dimmed.shape[:2]
    row = dimmed[height // 2]
    full_row = full[height // 2]
    # Sample one single-coverage column and one double-coverage column by
    # walking the fully-opaque render: single-coverage pixels equal the band
    # color exactly; the overlap is identical there (opaque over opaque).
    band = np.array([37, 99, 235, 255])
    on_band = np.where((full_row == band).all(axis=-1))[0]
    assert on_band.size > 4
    single_col, overlap_col = on_band[2], on_band[on_band.size // 2]
    single = row[single_col].astype(float)
    overlap = row[overlap_col].astype(float)
    # Double-blend: the overlap is strictly darker than single coverage in
    # the raster, where a browser-style group composite would keep them
    # equal (KNOWN_RENDERER_DIVERGENCES: annotation_layer_opacity_compositing).
    assert overlap[2] < single[2] < 255.0


def test_layer_background_is_plot_clipped_and_under_the_shapes() -> None:
    # Flagged geometry decision, pinned: the live overlay is full-bleed
    # (inset:0) but the writers paint the plot rect — the only seam that is
    # above the traces and below the annotation shapes in both writers
    # (KNOWN_RENDERER_DIVERGENCES: annotation_layer_background_geometry).
    chart = xy.line_chart(
        _line(),
        xy.hline(1.5),
        styles={"annotation_layer": {"background": "#123456"}},
    )
    svg = _svg_of(chart)
    rect = next(r for r in _rects(svg) if "#123456" in r)
    clip_rect = re.search(r"<clipPath[^>]*><rect ([^/]*)/>", svg).group(1)
    for key in ("x", "y", "width", "height"):
        expected = re.search(rf'{key}="([-\d.]+)"', clip_rect).group(1)
        assert f'{key}="{expected}"' in rect, (key, rect, clip_rect)
    # Inside the clipped marks group, before the annotation shapes.
    clipped = svg.split('<g clip-path="', 1)[1]
    assert clipped.index("#123456") < clipped.index("<line ")
    assert svg_to_pdf(svg)[:4] == b"%PDF"
    # And the raster writer paints it (declaration-gated).
    plain = xy.line_chart(_line(), xy.hline(1.5))
    assert not (_raster_of(plain) == _raster_of(chart)).all()


def test_layer_preflight_routes_opacity_and_background_only() -> None:
    figure = xy.line_chart(
        _line(),
        xy.hline(1.5),
        styles={"annotation_layer": {"opacity": 0.5, "border_radius": "4px"}},
    ).figure()
    report = figure.style_compatibility_report(target="png")
    (finding,) = [f for f in report.findings if f.slot == "annotation_layer"]
    assert finding.kept == ("opacity",)
    assert finding.lost == ("border-radius",)


# -- badge / badge_item: view-gated, excluded from static parity --------------


def test_badge_slots_stay_view_gated_with_no_writer_emission() -> None:
    # The applicability partition (capabilities.py): reduction badges exist
    # only under the view state that triggers them, so a clean static export
    # contains nothing for the slot to style — preflight records, writers
    # stay silent, and the capability partition is unchanged.
    from xy.styling import capabilities as caps

    by_id = {slot.id: slot for slot in caps.CHART_SLOTS}
    assert by_id["badge"].applicability == "view"
    assert by_id["badge_item"].applicability == "view"
    for surface in ("native_raster", "native_vector"):
        assert by_id["badge"].support[surface] == "none"
        assert by_id["badge_item"].support[surface] == "none"

    def chart(**kwargs):
        return xy.line_chart(_line(), xy.text(0.5, 0.5, "note"), **kwargs)

    styled = chart(styles={"badge_item": {"background": "#123456"}})
    assert _svg_of(chart()) == _svg_of(styled).replace("", "")
    assert (_raster_of(chart()) == _raster_of(styled)).all()
    report = styled.figure().style_compatibility_report(target="png")
    (finding,) = [f for f in report.findings if f.slot == "badge_item"]
    assert finding.route == "state-gated"
    assert report.lossless
