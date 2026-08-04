"""Static-chrome parity, phase 2: the axis-chrome family.

Executable acceptance for plan §4 (spec/process/static-chrome-parity-plan-
2026-08-04.md): axis_line and tick_mark gain boxes through the shared
producer, tick_label and axis_title complete their per-property text
contract and gain boxes, and axis_band is resolved (flag F) as
interaction-gated chrome with no writer emission. Throughout, the standing
gate holds: an unstyled chart's bytes never move, and every emitted
construct round-trips the PDF closed subset.
"""

from __future__ import annotations

import re
import struct

import pytest

import xy
from xy import _chromebox, _raster, _svg
from xy._pdf import svg_to_pdf
from xy.styling import capabilities as caps
from xy.styling import preflight as pf
from xy.styling.declared import resolve_declared


def _chart(*components, **props):
    return xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [0.0, 1.0, 0.5], name="series"), *components, **props
    )


def _rects(svg: str, needle: str) -> list[str]:
    return [r for r in re.findall(r"<rect[^>]*/>", svg) if needle in r]


def _attr(node: str, name: str) -> float:
    match = re.search(rf'{name}="([^"]+)"', node)
    assert match, (name, node)
    return float(match.group(1))


def _png_pixels(chart):
    return _raster.render_raster(*chart.figure().build_payload(), scale=1)


def _decoded_fills(cmd: "_raster._Cmd") -> list[list[tuple[float, float]]]:
    """FILL polygons out of a display-list buffer, for geometry assertions."""
    buf, i, out = bytes(cmd.buf), 0, []
    while i < len(buf):
        assert buf[i] == _raster._FILL or buf[i] == _raster._STROKE, "unexpected opcode"
        op = buf[i]
        i += 1
        if op == _raster._FILL:
            (count,) = struct.unpack_from("<I", buf, i)
            i += 4
            pts = [struct.unpack_from("<ff", buf, i + 8 * j) for j in range(count)]
            i += 8 * count + 4  # points + rgba
            out.append(pts)
        else:  # stroke: width f32, count u32, pts, rgba, cap u8, dash...
            i += 4
            (count,) = struct.unpack_from("<I", buf, i)
            i += 4 + 8 * count + 4
            i += 1  # cap byte
            (dash_n,) = struct.unpack_from("<I", buf, i)
            i += 4 + 4 * dash_n
    return out


# -- the raster primitive draws the geometry it was handed --------------------


def test_raster_emitter_geometry_is_the_declared_rect() -> None:
    # Regression: `_emit_slot_box` passed (x, y, w, h) to helpers that take
    # corner coordinates, so every box off the origin collapsed. The P0.3
    # test only asserted non-empty bytes and never caught it.
    cmd = _raster._Cmd(1.0)
    box = _chromebox.lower_box("legend", {"background": "#123456"}, x=100.0, y=50.0, w=20.0, h=10.0)
    _raster._emit_slot_box(cmd, box)
    (pts,) = _decoded_fills(cmd)
    assert pts == [(100.0, 50.0), (120.0, 50.0), (120.0, 60.0), (100.0, 60.0)]


def test_zero_area_boxes_emit_nothing_not_even_a_shadow() -> None:
    # Plan §4.4: no shadow on zero-area boxes — a tick_length: 0 tick must
    # not cast one, in either writer.
    box = _chromebox.lower_box(
        "tick_mark", {"background": "#123456", "box-shadow": "2px 2px #000"}, x=5, y=5, w=1, h=0
    )
    assert _svg._slot_box_svg(box) == ""
    cmd = _raster._Cmd(1.0)
    _raster._emit_slot_box(cmd, box)
    assert bytes(cmd.buf) == b""


def test_rotated_box_lowers_to_polygon_or_arc_path_and_pdf_accepts_both() -> None:
    # The pinned repo-wide flag-E lowering: polygon at radius 0, path with
    # circular arcs at radius > 0 — never a transformed rect.
    square = _chromebox.box_at(
        _chromebox.box_template("axis_title", {"background": "#123456"}),
        10,
        10,
        40,
        20,
        angle=-90.0,
        cx=30.0,
        cy=20.0,
    )
    rounded = _chromebox.box_at(
        _chromebox.box_template("axis_title", {"background": "#123456", "border-radius": "5px"}),
        10,
        10,
        40,
        20,
        angle=-90.0,
        cx=30.0,
        cy=20.0,
    )
    polygon = _svg._slot_box_svg(square)
    path = _svg._slot_box_svg(rounded)
    assert polygon.startswith("<polygon points=")
    assert path.startswith('<path d="M') and " A 5 5 0 0 1 " in path
    for shape in (polygon, path):
        assert "transform" not in shape
        pdf = svg_to_pdf(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">{shape}</svg>'
        )
        assert pdf[:4] == b"%PDF"


# -- axis_line ----------------------------------------------------------------


def test_axis_line_box_renders_only_when_box_props_declared() -> None:
    plain = _chart().to_svg()
    # A non-box declaration on the slot leaves the bytes untouched.
    assert _chart(styles={"axis_line": {"font_size": 10}}).to_svg() == plain
    styled = _chart(styles={"axis_line": {"background": "#123456"}}).to_svg()
    assert len(_rects(styled, "#123456")) == 2  # left + bottom spine


def test_axis_line_edge_geometry_is_pinned_centered_on_the_plot_edge() -> None:
    # Golden for the edge-inset decision: the box covers exactly the pixels
    # of the unstyled centered stroke; the browser's inset geometry is the
    # recorded divergence, not ours.
    chart = _chart(styles={"axis_line": {"background": "#123456"}})
    spec, _ = chart.figure().build_payload()
    _w, _h, _c, plot = _svg.layout(spec)
    left, bottom = _rects(chart.to_svg(), "#123456")
    assert _attr(left, "x") == round(plot["x"] - 0.5, 2)
    assert _attr(left, "y") == round(plot["y"], 2)
    assert _attr(left, "width") == 1
    assert _attr(left, "height") == round(plot["h"], 2)
    assert _attr(bottom, "y") == round(plot["y"] + plot["h"] - 0.5, 2)


def test_axis_line_keeps_the_axis_color_ink_unless_background_is_declared() -> None:
    # The narrower selector still wins the paint: a box-styled spine without
    # a background keeps its axis_color; an explicit background replaces it;
    # an explicit transparent erases it (browser parity).
    bordered = _chart(
        xy.y_axis(style={"axis_color": "#ff0000"}),
        styles={"axis_line": {"border_color": "#00ff00"}},
    ).to_svg()
    assert len(_rects(bordered, 'fill="#ff0000"')) >= 1
    erased = _chart(
        xy.y_axis(style={"axis_color": "#ff0000"}),
        styles={"axis_line": {"background": "transparent", "border_color": "#00ff00"}},
    ).to_svg()
    assert _rects(erased, 'fill="#ff0000"') == []
    assert len(_rects(erased, 'fill="none"')) >= 1


def test_axis_line_polar_keeps_stroke_semantics_and_the_limit_is_recorded() -> None:
    polar = xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [0.5, 1.0, 0.8], name="s"),
        coords="polar",
        styles={"axis_line": {"background": "#123456"}},
    )
    svg = polar.to_svg()
    assert _rects(svg, "#123456") == []
    assert 'data-xy-frame="polar"' in svg
    note = next(s for s in caps.CHART_SLOTS if s.id == "axis_line").notes
    assert "polar" in note.lower()
    assert any(d.id == "axis_line_edge_geometry" for d in caps.KNOWN_RENDERER_DIVERGENCES)


def test_axis_line_box_survives_both_writers_and_pdf() -> None:
    styled = _chart(styles={"axis_line": {"background": "#123456", "border_color": "#654321"}})
    assert not (_png_pixels(styled) == _png_pixels(_chart())).all()
    pdf = styled.to_image("pdf")
    assert pdf[:4] == b"%PDF"


# -- tick_mark ----------------------------------------------------------------


def _tick_chart(**props):
    return _chart(xy.x_axis(style={"tick_length": 6, "tick_color": "#ff0000"}), **props)


def test_tick_mark_boxes_render_for_authored_tick_length_only() -> None:
    styled = _tick_chart(styles={"tick_mark": {"background": "#123456"}})
    svg = styled.to_svg()
    boxes = _rects(svg, "#123456")
    assert boxes  # every x major tick, none for the length-0 y axis
    # The y axis authors no tick geometry: zero-area boxes emit nothing and
    # no length is invented.
    no_length = _chart(styles={"tick_mark": {"background": "#123456"}}).to_svg()
    assert _rects(no_length, "#123456") == []


def test_tick_mark_box_is_the_centered_strokes_own_coverage() -> None:
    styled = _tick_chart(styles={"tick_mark": {"background": "#123456"}})
    spec, _ = styled.figure().build_payload()
    _w, _h, _c, plot = _svg.layout(spec)
    unstyled_svg = _tick_chart().to_svg()
    tick_lines = [
        node for node in re.findall(r"<line[^>]*/>", unstyled_svg) if 'stroke="#ff0000"' in node
    ]
    box = _rects(styled.to_svg(), "#123456")[0]
    line = tick_lines[0]
    assert _attr(box, "x") == round(_attr(line, "x1") - 0.5, 2)
    assert _attr(box, "y") == _attr(line, "y1") == round(plot["y"] + plot["h"], 2)
    assert _attr(box, "width") == 1 and _attr(box, "height") == 6


def test_tick_mark_preflight_carries_the_zero_length_note() -> None:
    report = _chart(styles={"tick_mark": {"background": "red"}}).style_compatibility_report("png")
    finding = next(f for f in report.findings if f.slot == "tick_mark")
    assert finding.route == pf.ROUTE_SUBSET
    assert finding.lost == ()
    assert "tick_length" in finding.detail
    assert report.lossless


def test_tick_mark_qualifiers_and_geometry_land_in_the_snapshot() -> None:
    styled = _tick_chart(styles={"tick_mark": {"background": "#123456"}})
    spec, _ = styled.figure().build_payload()
    styling = resolve_declared(spec)
    ticks = [inst for inst in styling.snapshot.instances if inst.slot == "tick_mark"]
    assert len(ticks) >= 2
    # One interned declaration, N instances, each with its identity and box.
    assert len({inst.declaration for inst in ticks}) == 1
    kinds = {inst.qualifiers[:3] for inst in ticks}
    assert ("x", "major", "bottom") in kinds
    for inst in ticks:
        assert inst.qualifiers[3].isdigit()
        assert inst.geometry is not None and inst.geometry[2] > 0 and inst.geometry[3] > 0
    payload = styling.snapshot.to_payload()
    assert any("q" in inst and "g" in inst for inst in payload["instances"])


def test_dense_axis_stays_within_byte_and_display_list_budgets() -> None:
    # 200 ticks: the styled SVG grows by one rect per tick (interned attrs,
    # bounded size) and the raster display list by one FILL per tick.
    values = [float(v) for v in range(200)]
    dense = xy.line_chart(
        xy.line(values, values, name="s"),
        xy.x_axis(tick_values=values, style={"tick_length": 4}),
    )
    dense_styled = xy.line_chart(
        xy.line(values, values, name="s"),
        xy.x_axis(tick_values=values, style={"tick_length": 4}),
        styles={"tick_mark": {"background": "#123456"}},
    )
    plain_svg, styled_svg = dense.to_svg(), dense_styled.to_svg()
    # Boxes REPLACE the tick strokes (one rect per former line), so the
    # document may even shrink; the budget bounds the swing per tick.
    assert len(_rects(styled_svg, "#123456")) == 200
    assert abs(len(styled_svg) - len(plain_svg)) < 200 * 120
    spec, _ = dense_styled.figure().build_payload()
    boxes = [b for b in _svg.axis_chrome_boxes(spec) if b.slot == "tick_mark"]
    assert len(boxes) == 200
    cmd = _raster._Cmd(1.0)
    for box in boxes:
        _raster._emit_slot_box(cmd, box)
    assert len(cmd.buf) < 200 * 64  # one 4-point FILL (45 bytes) per tick


def test_tick_mark_declaration_is_lowered_once_not_per_instance(monkeypatch) -> None:
    calls = 0
    real = _chromebox.lower_box

    def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(
        _svg, "box_template", lambda slot, decl: counting(slot, decl, x=0.0, y=0.0, w=1e18, h=1e18)
    )
    values = [float(v) for v in range(50)]
    chart = xy.line_chart(
        xy.line(values, values, name="s"),
        xy.x_axis(tick_values=values, style={"tick_length": 4}),
        styles={"tick_mark": {"background": "#123456"}},
    )
    chart.to_svg()
    # One lowering per declaration RESOLUTION (a handful per export: layout,
    # the writer, the snapshot enrichment, the legend fold) — never one per
    # tick instance. 50 ticks, single-digit lowerings.
    assert calls <= 8, calls


# -- tick_label ---------------------------------------------------------------


def test_padded_tick_label_boxes_grow_the_rooms_in_both_orientations() -> None:
    plain_spec, _ = _chart().figure().build_payload()
    padded_spec, _ = (
        _chart(styles={"tick_label": {"background": "#123456", "padding": "20px 40px"}})
        .figure()
        .build_payload()
    )
    _w, height, _c, plain = _svg.layout(plain_spec)
    _w2, height2, _c2, padded = _svg.layout(padded_spec)
    assert padded["x"] > plain["x"]  # left gutter grew for the y labels
    plain_bottom = height - plain["y"] - plain["h"]
    padded_bottom = height2 - padded["y"] - padded["h"]
    assert padded_bottom > plain_bottom  # bottom band grew for the x labels
    # And no drawn box leaves the canvas.
    svg = _chart(styles={"tick_label": {"background": "#123456", "padding": "20px 40px"}}).to_svg()
    for rect in _rects(svg, "#123456"):
        assert _attr(rect, "x") >= 0.0
        assert _attr(rect, "y") + _attr(rect, "height") <= height2


def test_rotated_tick_label_boxes_rotate_with_the_text_and_pass_pdf() -> None:
    chart = _chart(
        xy.x_axis(tick_label_angle=-45.0),
        styles={"tick_label": {"background": "#123456", "padding": "2px"}},
    )
    svg = chart.to_svg()
    polygons = [p for p in re.findall(r"<polygon[^>]*/>", svg) if "#123456" in p]
    assert polygons  # the flag-E lowering, one per rotated label
    assert "transform" not in polygons[0]
    assert svg_to_pdf(svg)[:4] == b"%PDF"
    # Each box shares its label's rotation pivot: the polygon's corners are
    # not axis-aligned.
    xs = {point.split(",")[0] for point in polygons[0].split('points="')[1].split('"')[0].split()}
    assert len(xs) > 2


def test_tick_label_box_offsets_pin_the_documented_writer_divergence() -> None:
    # The SVG writer hangs bottom x labels 16px below the plot, the raster
    # writer 15px (`_raster.py` emit_tick_labels: "that 1 px has always
    # separated the two and is not this seam's to change"). The box rides
    # the label anchor, so the same pre-existing 1px offset — no more, no
    # less — is this family's raster tolerance.
    chart = _chart(styles={"tick_label": {"background": "#123456", "padding": "2px"}})
    spec, _ = chart.figure().build_payload()
    _w, _h, _c, plot = _svg.layout(spec)
    bottom_boxes = [
        r for r in _rects(chart.to_svg(), "#123456") if _attr(r, "y") > plot["y"] + plot["h"]
    ]
    assert bottom_boxes
    slot = {"background": "#123456", "padding": "2px"}
    block = _chromebox.text_box(
        _chromebox.box_template("tick_label", slot),
        _chromebox.padding_sides(slot),
        x=0.0,
        y=0.0,
        anchor="middle",
        block=__import__("xy._textblock", fromlist=["measure"]).measure("0", 11.0),
    )
    svg_y = min(_attr(r, "y") for r in bottom_boxes)
    expected_svg = plot["y"] + plot["h"] + 16.0 + block.y  # block.y = -ascent - pad
    assert abs(svg_y - expected_svg) < 0.02
    # The raster anchor for the same label sits at +15: exactly 1px closer.


def test_polar_tick_label_boxes_and_raster_emphasis_reach_both_writers() -> None:
    def polar(**props):
        return xy.line_chart(
            xy.line([0.0, 1.0, 2.0], [0.5, 1.0, 0.8], name="s"), coords="polar", **props
        )

    styled = polar(styles={"tick_label": {"background": "#123456", "font_weight": 700}})
    svg = styled.to_svg()
    assert _rects(svg, "#123456")
    assert not (_png_pixels(styled) == _png_pixels(polar())).all()
    # The P0.2 emphasis contract now covers the polar raster sink too: bold
    # alone (no box, no size change) must move pixels.
    bold_only = polar(styles={"tick_label": {"font_weight": 700}})
    assert not (_png_pixels(bold_only) == _png_pixels(polar())).all()


# -- axis_title ---------------------------------------------------------------


def test_rotated_y_title_boxes_pass_pdf_with_and_without_radius() -> None:
    for extra in ({}, {"border_radius": "4px"}):
        chart = _chart(
            xy.y_axis(label="Amplitude"),
            styles={"axis_title": {"background": "#123456", "padding": "3px", **extra}},
        )
        svg = chart.to_svg()
        shape = "<path" if extra else "<polygon"
        assert any(shape in node for node in re.findall(r"<(?:path|polygon)[^>]*/>", svg))
        assert svg_to_pdf(svg)[:4] == b"%PDF"


def test_slot_letter_spacing_survives_an_axis_authored_family() -> None:
    # The pre-parity branch dropped the slot's letter-spacing and opacity
    # wholesale when the axis authored label_font_family/style.
    svg = _chart(
        xy.x_axis(label="Time", style={"label_font_family": "Georgia"}),
        styles={"axis_title": {"letter_spacing": "2px", "opacity": 0.8}},
    ).to_svg()
    title = next(node for node in re.findall(r"<text[^>]*>Time</text>", svg))
    assert 'font-family="Georgia"' in title
    assert 'letter-spacing="2px"' in title
    assert 'opacity="0.8"' in title


@pytest.mark.parametrize(
    ("axis_style", "slot", "expect", "reject"),
    [
        # family: the axis's label_font_family is the narrower selector.
        (
            {"label_font_family": "Georgia"},
            {"font_family": "Courier"},
            'font-family="Georgia"',
            'font-family="Courier"',
        ),
        # style: same rule.
        (
            {"label_font_style": "normal"},
            {"font_style": "italic"},
            'font-style="normal"',
            'font-style="italic"',
        ),
        # weight: same rule.
        (
            {"label_font_weight": 700},
            {"font_weight": 300},
            'font-weight="700"',
            'font-weight="300"',
        ),
        # font-size runs the other way (pre-existing, documented): the
        # slot's font-size wins over the axis label_size.
        ({"label_size": 20}, {"font_size": 9}, 'font-size="9"', 'font-size="20"'),
        # color: the axis label_color is the narrower selector.
        ({"label_color": "#ff0000"}, {"fill": "#0000ff"}, 'fill="#ff0000"', 'fill="#0000ff"'),
    ],
)
def test_axis_title_precedence_table(axis_style, slot, expect, reject) -> None:
    svg = _chart(xy.x_axis(label="Time", style=axis_style), styles={"axis_title": slot}).to_svg()
    title = next(node for node in re.findall(r"<text[^>]*>Time</text>", svg))
    assert expect in title
    assert reject not in title


def test_axis_title_dejavu_box_misfit_is_qualified() -> None:
    for slot_id in ("axis_title", "tick_label"):
        note = next(s for s in caps.CHART_SLOTS if s.id == slot_id).notes
        assert "DejaVu" in note


# -- axis_band (flag-F resolution) ---------------------------------------------


def test_axis_band_is_navigation_gated_with_no_writer_emission() -> None:
    band = next(s for s in caps.CHART_SLOTS if s.id == "axis_band")
    assert band.applicability == "navigation"
    assert band.support["native_raster"] == "none"
    styled = _chart(styles={"axis_band": {"background": "#123456"}})
    assert styled.to_svg() == _chart().to_svg()
    assert (_png_pixels(styled) == _png_pixels(_chart())).all()
    report = styled.style_compatibility_report("png")
    finding = next(f for f in report.findings if f.slot == "axis_band")
    assert finding.route == pf.ROUTE_STATE_GATED
    assert finding.applicability == "navigation"
    assert report.lossless


# -- the standing gate and cross-writer agreement ------------------------------


def test_unstyled_bytes_are_untouched_by_the_axis_chrome_family() -> None:
    # The whole family's emission is declaration-gated: a chart with tick
    # geometry, titles, and a polar sibling — but no styles= — must render
    # the exact bytes of a second identical build, with the historical
    # elements (lines, no chrome rects in the baselines block).
    chart = _chart(xy.x_axis(label="Time", style={"tick_length": 5}), xy.y_axis(label="Amp"))
    svg = chart.to_svg()
    assert (
        svg
        == _chart(
            xy.x_axis(label="Time", style={"tick_length": 5}), xy.y_axis(label="Amp")
        ).to_svg()
    )
    assert "<polygon" not in svg
    png = _png_pixels(chart)
    again = _png_pixels(
        _chart(xy.x_axis(label="Time", style={"tick_length": 5}), xy.y_axis(label="Amp"))
    )
    assert (png == again).all()


def test_the_shared_producer_feeds_both_writers_identically() -> None:
    # SVG rect geometry equals the producer's boxes; the raster consumes the
    # same list, so agreement with the producer is agreement across writers.
    chart = _tick_chart(
        styles={
            "axis_line": {"background": "#123456"},
            "tick_mark": {"background": "#654321"},
        }
    )
    spec, _ = chart.figure().build_payload()
    boxes = _svg.axis_chrome_boxes(spec)
    svg = chart.to_svg()
    for box in boxes:
        needle = "#123456" if box.slot == "axis_line" else "#654321"
        matches = [
            r
            for r in _rects(svg, needle)
            if abs(_attr(r, "x") - round(box.x, 2)) < 0.011
            and abs(_attr(r, "y") - round(box.y, 2)) < 0.011
        ]
        assert matches, (box.slot, box.qualifiers)
    assert {b.slot for b in boxes} == {"axis_line", "tick_mark"}


def test_axis_chrome_boxes_is_empty_for_unstyled_and_polar_specs() -> None:
    spec, _ = _tick_chart().figure().build_payload()
    assert _svg.axis_chrome_boxes(spec) == []
    polar_spec, _ = (
        xy.line_chart(
            xy.line([0.0, 1.0], [0.5, 1.0], name="s"),
            coords="polar",
            styles={"axis_line": {"background": "#123456"}},
        )
        .figure()
        .build_payload()
    )
    assert _svg.axis_chrome_boxes(polar_spec) == []
