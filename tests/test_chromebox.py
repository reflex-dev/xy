"""The shared chrome-box model: one lowering, two emitters, zero drift.

Every box the parity phases draw goes through `lower_box` and one of the
two emitters, so these tests are the floor under all of them: parsing
edge cases, the §28 unrepresentable ledger, emitter output shape, PDF
round-trip, and the emit-nothing-when-unstyled gate.
"""

from __future__ import annotations

from xy import _raster, _svg
from xy._chromebox import ChromeBox, lower_box
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


def _fill_points(cmd: _raster._Cmd) -> list[tuple[float, float]]:
    import struct

    buf = bytes(cmd.buf)
    assert buf[0] == _raster._FILL
    (count,) = struct.unpack_from("<I", buf, 1)
    coords = struct.unpack_from(f"<{count * 2}f", buf, 5)
    return list(zip(coords[0::2], coords[1::2], strict=True))


def test_raster_emitter_treats_w_h_as_extents_like_the_svg_twin() -> None:
    # `w`/`h` are extents (the SVG twin emits width=/height=), not the far
    # corner. The raster emitter briefly read them as absolute corner
    # coordinates, so a box at (50, 40) sized 60x20 filled the rectangle
    # (50, 40)-(60, 20) instead of (50, 40)-(110, 60).
    cmd = _raster._Cmd(1.0)
    _raster._emit_slot_box(cmd, lower_box("legend", {"background": "#f00"}, x=50, y=40, w=60, h=20))
    assert _fill_points(cmd) == [(50.0, 40.0), (110.0, 40.0), (110.0, 60.0), (50.0, 60.0)]


def test_explicit_stroke_keeps_the_pinned_pyplot_bbox_serialization() -> None:
    # The pre-parity text-bbox emitter always wrote a stroke pair; a
    # borderless bbox rect carried the inert `stroke="none" stroke-width="0"`
    # and that output is byte-pinned, so the adapter's boxes reproduce it.
    box = ChromeBox(slot="annotation_label", x=1, y=2, w=30, h=10, fill="#ffee88")
    modern = _svg._slot_box_svg(box)
    assert "stroke" not in modern
    legacy = _svg._slot_box_svg(
        ChromeBox(
            slot="annotation_label",
            x=1,
            y=2,
            w=30,
            h=10,
            fill="#ffee88",
            explicit_stroke=("none", 0.0),
        )
    )
    assert legacy == modern.replace("/>", ' stroke="none" stroke-width="0"/>')
    # An active border wins over the legacy pair — never two stroke attrs.
    bordered = _svg._slot_box_svg(
        ChromeBox(
            slot="annotation_label",
            x=1,
            y=2,
            w=30,
            h=10,
            border_color="#123",
            border_width=2.0,
            explicit_stroke=("none", 0.0),
        )
    )
    assert bordered.count("stroke=") == 1 and 'stroke="#123"' in bordered
    # A zero-width-border-only rect still serializes (the legacy emitter drew
    # it as invisible bytes), while the raster twin paints nothing — exactly
    # the old pair's behavior.
    invisible = ChromeBox(slot="annotation_label", x=0, y=0, w=8, h=8, explicit_stroke=("red", 0.0))
    assert 'stroke="red" stroke-width="0"' in _svg._slot_box_svg(invisible)
    cmd = _raster._Cmd(1.0)
    _raster._emit_slot_box(cmd, invisible)
    assert bytes(cmd.buf) == b""
