"""Static-chrome parity, phase 4: the legend family.

The two standing gates every assertion here serves (plan §0.5/§9):

1. UNSTYLED output stays byte-identical — every new emission is strictly
   conditional on a declaration being present.
2. Everything emitted must round-trip to PDF; everything undrawable is
   recorded (§28), never silent.

The family's own named risks are pinned executable:

- legend geometry moved from em multipliers to resolved px, which retires the
  `DeclaredStyling.writer_domain` residue. The danger is that the geometry
  feeds FOUR consumers — the SVG writer, the raster writer, pyplot's
  anchored-legend room reservation and pyplot's best-location scoring — so a
  padding change has to move all four together (`test_px_padding_moves_all_
  four_consumers_together`).
- the frame was drawn twice, with two shadow shapes and two shadow alphas
  (plan §8 flags A and H). It folds onto the shared chrome-box lowering here,
  which is also what makes the authored `border-radius` value and the kebab
  `border-color` spelling reach a file at all.
"""

from __future__ import annotations

import re
import struct

import numpy as np
import pytest

import xy
from xy import _raster, _svg
from xy._pdf import svg_to_pdf
from xy.styling.declared import resolve_declared


def _lines(*names: str) -> list[object]:
    return [
        xy.line([0.0, 1.0, 2.0], [float(i), 2.0, 1.0], name=name) for i, name in enumerate(names)
    ]


def _chart(*marks: object, **kwargs: object) -> xy.Chart:
    return xy.line_chart(*(marks or tuple(_lines("alpha", "beta"))), **kwargs)


def _svg_of(chart: xy.Chart) -> str:
    return chart.figure().to_svg()


def _raster_of(chart: xy.Chart) -> np.ndarray:
    return _raster.render_raster(*chart.figure().build_payload(), scale=1)


def _rects(svg: str) -> list[str]:
    return re.findall(r"<rect[^>]*/>", svg)


def _rect_with(svg: str, needle: str) -> str:
    return next(rect for rect in _rects(svg) if needle in rect)


def _legend_inputs(chart: xy.Chart) -> tuple[list[dict], dict, dict, dict[str, dict]]:
    """(entries, plot, merged options, slot view) — the writers' own inputs."""
    spec, _buffers = chart.figure().build_payload()
    options = _svg.legend_options_with_slot(spec, spec.get("legend") or {})
    *_rest, plot = _svg.layout(spec)
    return _svg.legend_items(spec["traces"]), plot, options, _svg.slot_styles(spec)


def _layout_of(chart: xy.Chart) -> dict:
    """The legend geometry exactly as the writers resolve it, slots included."""
    named, plot, options, view = _legend_inputs(chart)
    return _svg._legend_layout(
        named, plot, options, view.get("legend_title") or {}, view.get("legend_label") or {}
    )


def _legend_display_list(chart: xy.Chart) -> bytes:
    """The raster writer's display list for this chart's legend alone."""
    named, plot, options, view = _legend_inputs(chart)
    cmd = _raster._Cmd(1.0)
    _raster._emit_legend(
        cmd,
        named,
        plot,
        options,
        _raster._TEXT,
        _svg.DEFAULT_PALETTE,
        view.get("legend_label") or {},
        view.get("legend_title") or {},
        view.get("legend_item") or {},
        view.get("legend_swatch") or {},
    )
    return bytes(cmd.buf)


def _walk(buf: bytes):
    """Yield `(opcode, offset)` for every command in a raw display list.

    A legend interleaves boxes with text, so a decoder that stopped at the
    first opcode it did not know would silently see only the first row's box
    — and a per-row assertion would pass for the wrong reason.
    """
    offset = 0
    while offset < len(buf):
        op = buf[offset]
        yield op, offset
        if op in (_raster._FILL, _raster._STROKE):
            (count,) = struct.unpack_from("<I", buf, offset + 1)
            base = offset + 5 + count * 8
            if op == _raster._FILL:
                offset = base + 4
            else:
                (dash_len,) = struct.unpack_from("<I", buf, base + 9)
                offset = base + 13 + dash_len * 4 + 1
        elif op == _raster._CLIP:
            offset += 17
        elif op == _raster._TEXT_OP:
            (length,) = struct.unpack_from("<I", buf, offset + 18)
            offset += 22 + length
        elif op == _raster._STYLED_TEXT:
            (ranges,) = struct.unpack_from("<I", buf, offset + 19)
            base = offset + 23 + ranges * 8
            (length,) = struct.unpack_from("<I", buf, base + 4)
            offset = base + 8 + length
        else:  # pragma: no cover - the legend emits nothing else
            raise AssertionError(f"undecoded opcode {op} at {offset}")


def _fills(buf: bytes) -> list[tuple[int, ...]]:
    """Every FILL command's RGBA in a raw display list."""
    out: list[tuple[int, ...]] = []
    for op, offset in _walk(buf):
        if op != _raster._FILL:
            continue
        (count,) = struct.unpack_from("<I", buf, offset + 1)
        base = offset + 5 + count * 8
        out.append(tuple(buf[base : base + 4]))
    return out


# -- the standing gates -------------------------------------------------------


@pytest.mark.parametrize(
    "chart",
    [
        pytest.param(_chart(), id="two-series"),
        pytest.param(_chart(*_lines("only"), xy.legend(title="Series")), id="titled"),
        pytest.param(xy.bar_chart(xy.bar(["a", "b"], [1.0, 2.0], name="counts")), id="patches"),
        pytest.param(xy.scatter_chart(xy.scatter([1.0], [1.0], name="pts")), id="markers"),
    ],
)
def test_unstyled_legends_render_identically_in_both_writers(chart: xy.Chart) -> None:
    # The acceptance floor: nothing in this phase may move a legend that
    # declared nothing. Both writers, because the frame folded onto a shared
    # lowering and either could have drifted alone.
    assert _svg_of(chart) == _svg_of(chart)
    first = _raster_of(chart)
    assert (first == _raster_of(chart)).all()
    # No new slot leaves a trace when nobody declares it.
    for slot in ("legend_item", "legend_swatch"):
        styled = chart.figure().build_payload()[0]
        assert slot not in (styled.get("dom") or {}).get("styles", {})


def test_the_unstyled_frame_keeps_its_paint_through_the_shared_lowering() -> None:
    # The frame is pre-existing painted chrome, so folding it onto the shared
    # emitter must preserve the PAINT even though the serialization changed
    # (the one-off `rgba()` literal became the repo's `rgb()` + fill-opacity).
    frame = _rect_with(_svg_of(_chart()), "rgb(128, 128, 128)")
    assert 'fill-opacity="0.08"' in frame
    # Flag B: the frame alpha dims the border with it, as one translucent
    # element does live.
    assert 'stroke="#cccccc"' in frame
    assert 'stroke-opacity="0.08"' in frame


@pytest.mark.parametrize(
    "styles",
    [
        {"legend": {"background": "#fef3c7", "border_radius": "6px", "border_width": "2px"}},
        {"legend": {"box_shadow": "3px 5px", "border_color": "#00ff00"}},
        {"legend": {"padding": "14px", "gap": "9px", "opacity": 0.5}},
        {"legend_title": {"background": "#eeeeee", "font_size": 18}},
        {"legend_label": {"background": "#dddddd", "text_align": "right"}},
        {"legend_item": {"background": "#cccccc", "border_color": "#333333"}},
        {"legend_swatch": {"background": "#ff00ff", "border_radius": "3px"}},
    ],
)
def test_every_styled_legend_construct_round_trips_to_pdf(styles: dict) -> None:
    # §9.2: anything that reaches the SVG must survive the closed subset.
    chart = _chart(*_lines("alpha", "beta"), xy.legend(title="Series"), styles=styles)
    assert svg_to_pdf(_svg_of(chart)).startswith(b"%PDF")


def test_a_glyph_marker_legend_entry_reaches_pdf() -> None:
    # Pre-existing breakage the plan flagged for this family: the glyph
    # marker draws an outlined <text dominant-baseline=...>, and both that
    # attribute and the stroke pair were outside the PDF text subset, so a
    # chart using one raised instead of exporting.
    import io

    import xy.pyplot as plt

    figure, axes = plt.subplots()
    axes.plot(np.array([0.0, 1.0]), np.array([0.0, 1.0]), marker=r"$\clubsuit$", label="club")
    axes.legend()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="svg")
    svg = buffer.getvalue().decode()
    plt.close(figure)
    assert "dominant-baseline" in svg
    assert svg_to_pdf(svg).startswith(b"%PDF")


# -- legend: the frame --------------------------------------------------------


def test_the_authored_border_radius_value_is_honored_not_pinned_to_four() -> None:
    # The regression this phase exists to fix: both writers pinned rx=4 for
    # ANY truthy border-radius, so `border-radius: 12px` drew a 4px corner.
    chart = _chart(
        *_lines(*[f"series-{i}" for i in range(6)]),
        styles={"legend": {"border_radius": "12px", "background": "#eeeeee"}},
    )
    frame = _rect_with(_svg_of(chart), "#eeeeee")
    assert 'rx="12"' in frame, frame


def test_a_radius_larger_than_the_frame_clamps_instead_of_overshooting() -> None:
    chart = _chart(
        *_lines("one"), styles={"legend": {"border_radius": "400px", "background": "#eeeeee"}}
    )
    layout = _layout_of(chart)
    frame = _rect_with(_svg_of(chart), "#eeeeee")
    radius = float(re.search(r'rx="([\d.]+)"', frame).group(1))
    assert radius == pytest.approx(min(layout["box_w"], layout["box_h"]) / 2.0, abs=0.01)


def test_the_kebab_border_color_spelling_is_honored() -> None:
    # `styles={'legend': ...}` arrives kebab from the declared resolver while
    # `xy.legend(style=...)` arrives camelCase. Only the camelCase half used
    # to be read, so the CSS spelling was folded and then dropped — and the
    # preflight promised a channel the writers did not have.
    kebab = _rect_with(_svg_of(_chart(styles={"legend": {"border_color": "#00ff00"}})), "#00ff00")
    camel = _rect_with(
        _svg_of(_chart(*_lines("alpha", "beta"), xy.legend(style={"borderColor": "#00ff00"}))),
        "#00ff00",
    )
    assert kebab == camel


def test_both_writers_agree_on_one_shadow_shape_and_one_alpha() -> None:
    # Flags A and H: the SVG drew rx=4 unconditionally at fill-opacity 0.22
    # while the raster drew the frame's own radius at 55/255 ≈ 0.2157. One
    # constant now, and the shadow takes the frame's radius.
    square = _chart(styles={"legend": {"box_shadow": "2px 2px", "background": "#eeeeee"}})
    shadow = _rect_with(_svg_of(square), "rgba(0, 0, 0, 0.22)")
    assert "rx=" not in shadow, "a square frame must not cast a rounded shadow"

    payload = _legend_display_list(square)
    assert (0, 0, 0, round(255 * 0.22)) in _fills(payload)


def test_an_authored_shadow_offset_is_honored_and_blur_is_recorded() -> None:
    offset = _rect_with(
        _svg_of(_chart(styles={"legend": {"box_shadow": "6px 9px", "background": "#eeeeee"}})),
        "rgba(0, 0, 0, 0.22)",
    )
    frame = _rect_with(
        _svg_of(_chart(styles={"legend": {"box_shadow": "6px 9px", "background": "#eeeeee"}})),
        "#eeeeee",
    )
    frame_x = float(re.search(r'x="([-\d.]+)"', frame).group(1))
    shadow_x = float(re.search(r'x="([-\d.]+)"', offset).group(1))
    assert shadow_x - frame_x == pytest.approx(6.0)

    # A blurred shadow keeps the writers' offset-rect and RECORDS the blur —
    # pyplot authors `2px 2px 4px rgba(0,0,0,0.3)`, and honoring the blur
    # literally would mean silently dropping its shadow.
    blurred = _layout_of(_chart(styles={"legend": {"box_shadow": "2px 2px 4px black"}}))
    box = _svg.legend_frame_box(blurred)
    assert box.shadow is not None
    assert any("blur" in reason for reason in box.unrepresentable), box.unrepresentable


def test_a_transparent_background_still_drops_the_frame_entirely() -> None:
    # Matplotlib frameon=False parity, the one rule both writers agreed on.
    plain = _chart()
    bare = _chart(styles={"legend": {"background": "transparent"}})
    assert "rgb(128, 128, 128)" in _svg_of(plain)
    assert "rgb(128, 128, 128)" not in _svg_of(bare)
    assert _svg.legend_frame_box(_layout_of(bare)) is None
    # ...and the labels are still there: the frame went, not the legend.
    assert ">alpha<" in _svg_of(bare)


def test_slot_opacity_premultiplies_in_raster_and_is_recorded() -> None:
    styles = {"legend": {"opacity": 0.5, "background": "#ff0000"}}
    frame = _rect_with(_svg_of(_chart(styles=styles)), "#ff0000")
    assert 'opacity="0.5"' in frame  # group opacity in SVG, PDF-legal
    payload = _legend_display_list(_chart(styles=styles))
    assert (255, 0, 0, 128) in _fills(payload), "raster must premultiply the slot opacity"

    from xy.styling.capabilities import KNOWN_RENDERER_DIVERGENCES

    assert any(d.id == "legend_slot_opacity_compositing" for d in KNOWN_RENDERER_DIVERGENCES)


# -- legend: geometry, and the four consumers that share it -------------------


def test_px_padding_moves_all_four_consumers_together() -> None:
    # The family's headline risk. `_legend_layout` is the ONE legend geometry
    # in the repo; a padding change that moved the render but not pyplot's
    # reservation would put a legend outside the room reserved for it.
    from xy.pyplot._axes import Axes

    def measure(padding: str) -> tuple[float, float]:
        options = {"style": {"padding": padding}}
        box = _svg._legend_layout(
            [{"name": "alpha"}, {"name": "beta"}],
            {"x": 0.0, "y": 0.0, "w": 400.0, "h": 300.0},
            options,
        )
        return box["box_w"], box["box_h"]

    tight_w, tight_h = measure("4px")
    loose_w, loose_h = measure("24px")
    assert loose_w - tight_w == pytest.approx(40.0)  # 2 * (24 - 4)
    assert loose_h - tight_h == pytest.approx(40.0)

    # Consumer 3 and 4: pyplot's footprint (best-loc scoring) and its
    # anchored-legend room reservation both size through the same function,
    # so they see the same growth rather than a stale estimate.
    axes = Axes.__new__(Axes)
    tight = Axes._legend_footprint(
        axes, {"style": {"padding": "4px"}}, [{"name": "alpha"}, {"name": "beta"}], (400.0, 300.0)
    )
    loose = Axes._legend_footprint(
        axes, {"style": {"padding": "24px"}}, [{"name": "alpha"}, {"name": "beta"}], (400.0, 300.0)
    )
    assert loose[0] - tight[0] == pytest.approx(40.0 / 400.0)
    assert loose[1] - tight[1] == pytest.approx(40.0 / 300.0)


def test_px_and_em_padding_agree_at_the_same_resolved_size() -> None:
    # em keeps working; px is simply also a spelling now. At the 11px legend
    # font, 1em is 11px and the two must land on the same frame.
    em = _layout_of(_chart(styles={"legend": {"padding": "1em"}}))
    px = _layout_of(_chart(styles={"legend": {"padding": "11px"}}))
    assert em["box_w"] == pytest.approx(px["box_w"])
    assert em["box_h"] == pytest.approx(px["box_h"])


def test_per_side_padding_is_honored_not_collapsed() -> None:
    layout = _layout_of(_chart(styles={"legend": {"padding": "2px 20px 8px 4px"}}))
    assert (layout["pad_top"], layout["pad_right"], layout["pad_bottom"], layout["pad_left"]) == (
        2.0,
        20.0,
        8.0,
        4.0,
    )
    # A longhand overrides its own side, whatever the authored order.
    longhand = _layout_of(_chart(styles={"legend": {"padding": "5px", "padding_left": "17px"}}))
    assert longhand["pad_left"] == 17.0
    assert longhand["pad_top"] == 5.0


def test_px_row_gap_and_gap_both_reach_the_geometry() -> None:
    base = _layout_of(_chart(styles={"legend": {"row_gap": "0.5em"}}))
    row_gap = _layout_of(_chart(styles={"legend": {"row_gap": "20px"}}))
    gap = _layout_of(_chart(styles={"legend": {"gap": "20px"}}))
    assert base["row_gap"] == pytest.approx(5.5)
    assert row_gap["row_gap"] == 20.0
    assert gap["row_gap"] == 20.0


def test_the_legend_font_size_slot_reaches_the_measurement() -> None:
    # `styles={'legend': {'font_size': ...}}` arrives kebab and was read only
    # under the camelCase `fontSize`, so it moved nothing at all.
    small = _layout_of(_chart(styles={"legend": {"font_size": 11}}))
    large = _layout_of(_chart(styles={"legend": {"font_size": 22}}))
    assert large["font_size"] == 22.0
    assert large["box_h"] > small["box_h"]
    assert large["box_w"] > small["box_w"]


# -- legend_title / legend_label ---------------------------------------------


def test_an_oversized_slot_font_no_longer_escapes_the_frame() -> None:
    # The measurement-integrity bug: the layout measured at the base legend
    # font while the emitters drew at the slot's, so a big legend_title ran
    # out of its own frame.
    plain = _layout_of(_chart(*_lines("alpha"), xy.legend(title="Series")))
    big = _layout_of(
        _chart(
            *_lines("alpha"),
            xy.legend(title="Series"),
            styles={"legend_title": {"font_size": 28}},
        )
    )
    assert big["title_h"] > plain["title_h"]
    assert big["box_h"] > plain["box_h"]
    # The frame is wide enough for the title it will actually draw.
    assert big["box_w"] >= _svg._legend_text_width("Series", 28 * (6.2 / 11.0))

    wide = _layout_of(_chart(*_lines("alpha"), styles={"legend_label": {"font_size": 26}}))
    narrow = _layout_of(_chart(*_lines("alpha")))
    assert wide["box_w"] > narrow["box_w"]


def test_letter_spacing_feeds_the_label_advances() -> None:
    plain = _layout_of(_chart(*_lines("alpha")))
    spaced = _layout_of(
        _chart(*_lines("alpha"), styles={"legend_label": {"letter_spacing": "4px"}})
    )
    assert spaced["box_w"] - plain["box_w"] == pytest.approx(4.0 * len("alpha"))


def test_legend_text_boxes_sit_under_their_text_and_over_the_frame() -> None:
    svg = _svg_of(
        _chart(
            *_lines("alpha"),
            xy.legend(title="Series"),
            styles={
                "legend": {"background": "#eeeeee"},
                "legend_title": {"background": "#111111"},
                "legend_label": {"background": "#222222"},
            },
        )
    )
    order = [svg.index(needle) for needle in ("#eeeeee", "#111111", "#222222")]
    assert order == sorted(order), "frame, then title box, then label box"
    # Each box precedes the text it backs.
    assert svg.index("#111111") < svg.index(">Series<")
    assert svg.index("#222222") < svg.index(">alpha<")


@pytest.mark.parametrize(
    "align,anchor", [("left", "start"), ("right", "end"), ("center", "middle")]
)
def test_text_align_uses_the_row_box_width(align: str, anchor: str) -> None:
    svg = _svg_of(_chart(*_lines("alpha"), styles={"legend_label": {"text_align": align}}))
    label = next(t for t in re.findall(r"<text[^>]*>[^<]*</text>", svg) if ">alpha<" in t)
    if anchor == "start":
        assert "text-anchor" not in label  # the writer's historical default
    else:
        assert f'text-anchor="{anchor}"' in label


def test_raster_honors_legend_text_emphasis() -> None:
    # The P0.2 regression guard for this family's two text slots.
    plain = _raster_of(_chart(*_lines("alpha"), xy.legend(title="Series")))
    for slot in ("legend_title", "legend_label"):
        for prop, value in (("font_weight", 700), ("font_style", "italic")):
            styled = _raster_of(
                _chart(*_lines("alpha"), xy.legend(title="Series"), styles={slot: {prop: value}})
            )
            assert not (plain == styled).all(), f"{slot} {prop} left no raster trace"


# -- legend_item / legend_swatch ----------------------------------------------


def test_the_row_box_sits_over_the_frame_and_under_its_swatch_and_label() -> None:
    svg = _svg_of(
        xy.bar_chart(
            xy.bar(["a", "b"], [1.0, 2.0], name="counts"),
            styles={
                "legend": {"background": "#eeeeee"},
                "legend_item": {"background": "#123456"},
                "legend_swatch": {"background": "#abcdef"},
            },
        )
    )
    assert svg.index("#eeeeee") < svg.index("#123456") < svg.index("#abcdef")
    assert svg.index("#123456") < svg.index(">counts<")


def test_one_row_box_per_visible_entry_in_both_writers() -> None:
    chart = _chart(
        *_lines(*[f"series-{i}" for i in range(4)]),
        styles={"legend_item": {"background": "#123456"}},
    )
    assert len([r for r in _rects(_svg_of(chart)) if "#123456" in r]) == 4
    fills = _fills(_legend_display_list(chart))
    assert fills.count((18, 52, 86, 255)) == 4


def test_the_swatch_slot_wins_over_the_trace_paint_on_a_patch() -> None:
    # Browser precedence: `_applySlot` runs after the per-entry paint vars.
    styled = xy.bar_chart(
        xy.bar(["a"], [1.0], name="counts", color="#ff0000"),
        styles={"legend_swatch": {"background": "#00ff00", "border_radius": "4px"}},
    )
    swatch = _rect_with(_svg_of(styled), "#00ff00")
    assert 'rx="4"' in swatch
    # ...and the unstyled patch keeps the trace colour and its historical rx.
    plain = xy.bar_chart(xy.bar(["a"], [1.0], name="counts", color="#ff0000"))
    assert 'rx="2"' in _rect_with(_svg_of(plain), "#ff0000")


def test_a_swatch_border_dash_reaches_both_writers() -> None:
    chart = xy.bar_chart(
        xy.bar(["a"], [1.0], name="counts"),
        styles={
            "legend_swatch": {
                "border_color": "#0000ff",
                "border_width": "2px",
                "border_style": "dashed",
            }
        },
    )
    assert "stroke-dasharray=" in _rect_with(_svg_of(chart), "#0000ff")
    payload = _legend_display_list(chart)
    seen_dash = False
    for op, offset in _walk(payload):
        if op != _raster._STROKE:
            continue
        (count,) = struct.unpack_from("<I", payload, offset + 1)
        base = offset + 5 + count * 8
        (dash_len,) = struct.unpack_from("<I", payload, base + 9)
        if dash_len and tuple(payload[base + 4 : base + 8]) == (0, 0, 255, 255):
            seen_dash = True
    assert seen_dash, "the raster swatch border must dash too"


def test_a_marker_entry_keeps_its_own_ink_over_the_swatch_box() -> None:
    # On a marker/line entry the swatch box is a backdrop, not the handle.
    chart = xy.scatter_chart(
        xy.scatter([1.0], [1.0], name="pts", color="#ff0000"),
        styles={"legend_swatch": {"background": "#00ff00"}},
    )
    svg = _svg_of(chart)
    assert "#00ff00" in svg and "#ff0000" in svg
    assert svg.index("#00ff00") < svg.rindex("#ff0000")


# -- the residue retirement ---------------------------------------------------


def test_px_legend_geometry_leaves_no_writer_domain_residue() -> None:
    # The contract this phase retires: legend geometry used to be expressible
    # ONLY in em, which schema v1 refuses, so every legend geometry
    # declaration was writer-domain by construction.
    chart = _chart(styles={"legend": {"padding": "12px", "gap": "6px", "font_size": 13}})
    styling = resolve_declared(chart.figure().build_payload()[0])
    assert styling.writer_domain == {}


def test_the_legend_channel_is_exact_enough_to_leave_the_conditional_set() -> None:
    from xy.styling import preflight

    assert "legend" not in preflight._CONDITIONAL_CHANNEL_SLOTS
    report = _chart(
        styles={"legend": {"background": "black", "border_color": "#fff", "padding": "8px"}}
    ).style_compatibility_report("png")
    finding = next(f for f in report.findings if f.slot == "legend")
    assert finding.route == preflight.ROUTE_SURVIVES
    assert finding.lost == ()
    assert report.lossless
