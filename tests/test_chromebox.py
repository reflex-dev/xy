"""The shared chrome-box model: one lowering, two emitters, zero drift.

Every box the parity phases draw goes through `lower_box` and one of the
two emitters, so these tests are the floor under all of them: parsing
edge cases, the §28 unrepresentable ledger, emitter output shape, PDF
round-trip, and the emit-nothing-when-unstyled gate.
"""

from __future__ import annotations

from xy import _raster, _svg
from xy._chromebox import (
    ChromeBox,
    box_at,
    box_room,
    box_template,
    lower_box,
    padding_sides,
    parse_padding,
    text_box,
)
from xy._pdf import svg_to_pdf


def _box(decl, **geom):
    geom = {"x": 10.0, "y": 20.0, "w": 100.0, "h": 40.0, **geom}
    return lower_box("legend", decl, **geom)


# -- lowering -----------------------------------------------------------------


def test_full_declaration_lowers_every_field() -> None:
    box = _box(
        {
            "background": "#0f172a",
            "border-color": "#334155",
            "border-width": "2px",
            "border-style": "dashed",
            "border-radius": "6px",
            "box-shadow": "2px 3px rgba(0, 0, 0, 0.22)",
            "opacity": 0.9,
            "fill-opacity": 0.8,
        }
    )
    assert box.fill == "#0f172a"
    assert box.border_color == "#334155"
    assert box.border_width == 2.0
    assert box.border_dash == (7.4, 3.2)
    assert box.radius == 6.0
    assert box.shadow == (2.0, 3.0, "rgba(0, 0, 0, 0.22)")
    assert box.opacity == 0.9
    assert box.fill_opacity == 0.8
    assert box.unrepresentable == ()


def test_radius_clamps_to_the_box_like_css() -> None:
    assert _box({"background": "#111", "border-radius": "500px"}).radius == 20.0


def test_transparent_and_none_fills_paint_nothing() -> None:
    for fill in ("transparent", "none", ""):
        box = _box({"background": fill})
        assert box.fill is None
        assert not box.paints_anything


def test_border_color_alone_implies_the_one_px_chrome_border() -> None:
    box = _box({"border-color": "#ccc"})
    assert box.border_width == 1.0
    assert box.paints_anything


def test_unrepresentable_requests_are_ledgered_with_reasons() -> None:
    box = _box(
        {
            "background": "linear-gradient(#000, #fff)",
            "border-style": "double",
            "border-radius": "4px 8px",
            "box-shadow": "0 4px 12px rgba(0, 0, 0, 0.3)",
        }
    )
    assert box.fill is None and box.radius == 0.0 and box.shadow is None
    reasons = " | ".join(box.unrepresentable)
    assert "gradient" in reasons
    assert "border-style 'double'" in reasons
    assert "asymmetric border-radius" in reasons
    assert "blur" in reasons


def test_shadow_parses_zero_blur_and_rejects_multiples() -> None:
    ok = _box({"box-shadow": "1px 2px 0 0 #000"})
    assert ok.shadow == (1.0, 2.0, "#000")
    multi = _box({"box-shadow": "1px 2px #000, 3px 4px #111"})
    assert multi.shadow is None
    assert any("multiple" in u for u in multi.unrepresentable)


# -- emitters -----------------------------------------------------------------


def test_svg_emitter_shape_and_attribute_uniqueness() -> None:
    svg = _svg._slot_box_svg(
        _box(
            {
                "background": "#0f172a",
                "border-color": "#334155",
                "border-width": "2px",
                "border-radius": "6px",
                "box-shadow": "2px 2px rgba(0, 0, 0, 0.22)",
                "opacity": 0.9,
            }
        )
    )
    import re

    rects = svg.split("<rect")[1:]
    assert len(rects) == 2  # shadow under the frame
    for rect in rects:
        names = re.findall(r'([\w-]+)="', rect)
        # every attribute exactly once per rect — the duplicate-attr trap:
        # the XML parser keeps the first value and drops the author's.
        assert len(names) == len(set(names)), rect
    shadow, frame = rects
    assert 'fill="rgba(0, 0, 0, 0.22)"' in shadow and "stroke" not in shadow
    for attr in ("stroke=", "stroke-width=", "rx=", "opacity="):
        assert attr in frame, (attr, frame)


def test_svg_emitter_is_silent_for_a_paintless_box() -> None:
    assert _svg._slot_box_svg(_box({})) == ""
    assert _svg._slot_box_svg(_box({"background": "transparent"})) == ""


def test_emitted_rects_stay_inside_the_pdf_closed_subset() -> None:
    svg = _svg._slot_box_svg(
        _box(
            {
                "background": "rgba(15, 23, 42, 0.9)",
                "border-color": "#334155",
                "border-width": "1px",
                "border-style": "dashed",
                "border-radius": "4px",
            }
        )
    )
    pdf = svg_to_pdf(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">{svg}</svg>'
    )
    assert pdf[:4] == b"%PDF"


def test_raster_emitter_mirrors_the_svg_decisions() -> None:
    cmd = _raster._Cmd(1.0)
    _raster._emit_slot_box(
        cmd,
        _box(
            {
                "background": "#0f172a",
                "border-color": "#334155",
                "border-width": "2px",
                "border-radius": "6px",
                "box-shadow": "2px 2px rgba(0, 0, 0, 0.22)",
            }
        ),
    )
    painted = bytes(cmd.buf)
    assert painted  # shadow fill + background fill + border stroke landed
    empty = _raster._Cmd(1.0)
    _raster._emit_slot_box(empty, _box({}))
    assert bytes(empty.buf) == b""  # the unstyled-bytes gate, at the primitive


def test_direct_chromebox_construction_defaults_paint_nothing() -> None:
    box = ChromeBox(slot="title", x=0, y=0, w=10, h=10)
    assert not box.paints_anything
    assert _svg._slot_box_svg(box) == ""


# -- the phase-2 additions: padding, templates, poses --------------------------


def test_padding_shorthand_expands_all_four_css_forms() -> None:
    # The one correct expansion — the annotation parsers' [0]/[1]-only
    # reading silently misread the 3- and 4-value forms.
    assert parse_padding("6px") == (6.0, 6.0, 6.0, 6.0)
    assert parse_padding("6px 10px") == (6.0, 10.0, 6.0, 10.0)
    assert parse_padding("1px 2px 3px") == (1.0, 2.0, 3.0, 2.0)
    assert parse_padding("1px 2px 3px 4px") == (1.0, 2.0, 3.0, 4.0)
    assert parse_padding(8) == (8.0, 8.0, 8.0, 8.0)
    assert parse_padding("1em") is None  # relative units stay writer-domain


def test_padding_longhands_override_the_shorthand_per_side() -> None:
    sides = padding_sides({"padding": "6px", "padding-left": "20px"})
    assert sides == (6.0, 6.0, 6.0, 20.0)


def test_box_room_is_padding_plus_border_per_side() -> None:
    room = box_room({"padding": "1px 2px 3px 4px", "border-color": "#ccc"})
    assert room == (2.0, 3.0, 4.0, 5.0)  # the 1px implied chrome border
    assert box_room(None) == (0.0, 0.0, 0.0, 0.0)
    assert box_room({"padding": "2px", "border-style": "none", "border-width": "3px"}) == (
        2.0,
        2.0,
        2.0,
        2.0,
    )


def test_template_and_box_at_intern_the_parse_and_clamp_per_instance() -> None:
    template = box_template("tick_mark", {"background": "#123", "border-radius": "8px"})
    assert template.radius == 8.0  # unclamped in the template
    stamped = box_at(template, 5, 5, 4, 20, qualifiers=("x", "major", "bottom", "0"))
    assert stamped.radius == 2.0  # clamped to min(w, h) / 2 per instance
    assert stamped.qualifiers == ("x", "major", "bottom", "0")


def test_box_at_fallback_fill_respects_an_explicit_transparent() -> None:
    # An absent background falls back to the slot's default ink; an explicit
    # transparent must NOT — the browser distinction fill_declared exists for.
    absent = box_at(
        box_template("axis_line", {"border-color": "#ccc"}), 0, 0, 10, 10, fallback_fill="#ff0000"
    )
    assert absent.fill == "#ff0000"
    erased = box_at(
        box_template("axis_line", {"background": "transparent", "border-color": "#ccc"}),
        0,
        0,
        10,
        10,
        fallback_fill="#ff0000",
    )
    assert erased.fill is None


def test_text_box_wraps_the_block_with_padding_in_anchor_space() -> None:
    class Block:
        width, ascent, descent, line_count, line_step = 40.0, 8.0, 2.0, 2, 12.0

    box = text_box(
        box_template("tick_label", {"background": "#123"}),
        (1.0, 2.0, 3.0, 4.0),
        x=100.0,
        y=50.0,
        anchor="middle",
        block=Block(),
        angle=-45.0,
    )
    assert (box.x, box.y) == (100.0 - 20.0 - 4.0, 50.0 - 8.0 - 1.0)
    assert (box.w, box.h) == (40.0 + 4.0 + 2.0, 8.0 + 2.0 + 12.0 + 1.0 + 3.0)
    assert (box.angle, box.cx, box.cy) == (-45.0, 100.0, 50.0)
