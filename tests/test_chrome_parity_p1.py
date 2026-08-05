"""Static-chrome parity phase 1: root / title / chrome / canvas boxes.

Every assertion here is an acceptance bullet from
`spec/process/static-chrome-parity-plan-2026-08-04.md` §3. The standing gate
(§2 item 0.5) leads: all emission is strictly declaration-gated, so an
unstyled chart's SVG and PNG bytes cannot move. Then per slot: the box in
both writers, the recorded divergences, the export-background override
contract, and a PDF round-trip of every construct the family emits.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

import xy
from xy import _raster, _svg, export
from xy._pdf import svg_to_pdf
from xy.styling.capabilities import KNOWN_RENDERER_DIVERGENCES
from xy.styling.declared import resolve_declared


def _chart(**props) -> xy.Chart:
    return xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [0.0, 1.0, 0.5], name="series"), title="Chart title", **props
    )


def _raster_pixels(chart: xy.Chart) -> np.ndarray:
    rendered = _raster.render_raster(*chart.figure().build_payload(), scale=1)
    assert isinstance(rendered, np.ndarray)
    return rendered


def _transparent_rgba(fig, **kw) -> np.ndarray:
    """The composited RGBA a transparent-background export paints.

    `_raster.to_rgba` is the raster writer's own pre-encode surface, so this
    asserts against exactly what the PNG encoder receives — and, unlike
    decoding the encoded PNG, it needs no image library: Pillow is absent
    from the 3.11-floor CI environment, and a test that silently depends on
    a dev-only extra is a test that only runs where someone happens to have
    it.
    """
    return _raster.to_rgba(fig, background="transparent", scale=1.0, **kw)


def _pdf_round_trips(svg: str) -> None:
    assert svg_to_pdf(svg)[:4] == b"%PDF"


# -- the standing gate --------------------------------------------------------


def test_unstyled_output_is_unchanged_by_the_p1_paths() -> None:
    # Emission is strictly conditional on a BOX declaration being present:
    # declarations outside every honored subset must leave the SVG and the
    # raster display list byte-identical to a chart with no styles at all.
    plain = _chart().figure()
    decorated = _chart(
        styles={
            "root": {"outline_color": "#123456"},
            "chrome": {"border_width": 2},
            "canvas": {"cursor": "pointer"},
            "title": {"text_decoration": "underline"},
        }
    ).figure()
    assert plain.to_svg() == decorated.to_svg()
    assert plain.to_png() == decorated.to_png()
    # And the unstyled document contains none of this family's constructs:
    # one clipPath (plot/legend) and no full-canvas box rect.
    svg = plain.to_svg()
    assert svg.count("<clipPath") == 1
    assert '<rect x="0" y="0"' not in svg


# -- title --------------------------------------------------------------------

_TITLE_STYLES = {
    "title": {
        "background": "#e2e8f0",
        "padding": "6px 10px",
        "border_color": "#94a3b8",
        "border_radius": "4px",
    }
}


def _title_rect_and_text(svg: str) -> tuple[str, str]:
    text = re.search(r"<text[^>]*>Chart title</text>", svg)
    assert text is not None
    before = svg[: text.start()]
    rect = re.findall(r"<rect[^>]*/>", before)[-1]
    # The box rides immediately before its text: under the title, above all
    # earlier chrome.
    assert before.rstrip().endswith(rect)
    return rect, text.group(0)


def test_title_box_renders_under_the_text_in_svg_and_pdf() -> None:
    svg = _chart(styles=_TITLE_STYLES).figure().to_svg()
    rect, _text = _title_rect_and_text(svg)
    assert 'fill="#e2e8f0"' in rect
    assert 'stroke="#94a3b8"' in rect
    assert 'rx="4"' in rect
    _pdf_round_trips(svg)


def test_title_box_width_is_block_width_plus_padding_not_wrap_width() -> None:
    chart = _chart(styles=_TITLE_STYLES)
    spec, _blob = chart.figure().build_payload()
    width, _height, _compact, plot = _svg.layout(spec)
    svg = chart.figure().to_svg()
    rect, _ = _title_rect_and_text(svg)
    box_w = float(re.search(r'width="([\d.]+)"', rect).group(1))
    from xy import _textblock

    block = _textblock.measure("Chart title", 14.0, max_width=plot["title_wrap_width"])
    assert box_w == pytest.approx(block.width + 10 + 10, abs=0.02)
    assert box_w < plot["title_wrap_width"]


def test_title_room_grows_for_padding_and_border() -> None:
    plain_spec, _ = _chart().figure().build_payload()
    styled_spec, _ = _chart(styles=_TITLE_STYLES).figure().build_payload()
    *_, plain_plot = _svg.layout(plain_spec)
    *_, styled_plot = _svg.layout(styled_spec)
    # The room formula grows by 6px padding top+bottom plus the implied 1px
    # border on both edges: max(30, block.height + 14 + pad) — mirrored by
    # _titleBoxExtent in js/src/50_chartview.ts.
    from xy import _textblock

    block = _textblock.measure("Chart title", 14.0, max_width=plain_plot["title_wrap_width"])
    assert plain_plot["title_room"] == pytest.approx(max(30.0, block.height + 8.0))
    assert styled_plot["title_room"] == pytest.approx(max(30.0, block.height + 14.0 + 8.0))
    grown = styled_plot["title_room"] - plain_plot["title_room"]
    assert grown > 0
    assert styled_plot["y"] == pytest.approx(plain_plot["y"] + grown)
    # The box clears the canvas top: its rect starts at a positive y.
    rect, _ = _title_rect_and_text(_chart(styles=_TITLE_STYLES).figure().to_svg())
    assert float(re.search(r'y="([\d.-]+)"', rect).group(1)) > 0


def test_title_entry_style_merges_over_the_slot() -> None:
    # `_title_metrics` order: the per-entry style is the narrower selector.
    fig = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series"),
        styles={"title": {"background": "#445566", "padding": "4px"}},
    ).figure()
    fig.title_options = [
        {"text": "Entry title", "loc": "center", "style": {"background": "#112233"}}
    ]
    svg = fig.to_svg()
    assert "#112233" in svg
    text = re.search(r"<text[^>]*>Entry title</text>", svg)
    rect = re.findall(r"<rect[^>]*/>", svg[: text.start()])[-1]
    assert 'fill="#112233"' in rect
    # The per-entry-box browser divergence is recorded, not silent (§28).
    assert "title_entry_box_allowlist" in {d.id for d in KNOWN_RENDERER_DIVERGENCES}


def test_title_box_reaches_the_raster_writer() -> None:
    plain = _raster_pixels(_chart())
    styled = _raster_pixels(_chart(styles=_TITLE_STYLES))
    assert not (plain == styled).all()
    # The box paints AT THE TITLE, not somewhere near the origin — the
    # (x, y, w, h)-vs-far-corner regression in the raster emitter.
    spec, _ = _chart(styles=_TITLE_STYLES).figure().build_payload()
    width, _h, compact, plot = _svg.layout(spec)
    placement = _svg.legacy_title_placement(spec, plot, compact, width, plot["title_wrap_width"])
    box = _svg.title_box(placement)
    assert box is not None
    inside = styled[int(box.y + box.h / 2), int(box.x + 3)]
    assert tuple(inside[:3]) == (0xE2, 0xE8, 0xF0)
    assert tuple(styled[2, 2]) == tuple(plain[2, 2])


def test_italic_title_with_a_box_exports_to_pdf() -> None:
    svg = (
        _chart(styles={"title": {**_TITLE_STYLES["title"], "font_style": "italic"}})
        .figure()
        .to_svg()
    )
    _pdf_round_trips(svg)


# -- root ---------------------------------------------------------------------

_ROOT_STYLES = {
    "root": {
        "background": "#0f172a",
        "border_color": "#334155",
        "border_width": 2,
        "border_radius": "12px",
    }
}


def test_root_box_renders_in_both_writers_and_pdf() -> None:
    svg = _chart(styles=_ROOT_STYLES).figure().to_svg()
    # First painted content after the defs (clipPath rects are not paint).
    rect = re.search(r"<rect[^>]*/>", svg[svg.index("</defs>") :]).group(0)
    assert 'fill="#0f172a"' in rect
    assert 'stroke="#334155"' in rect and 'stroke-width="2"' in rect
    assert 'rx="12"' in rect
    _pdf_round_trips(svg)
    pixels = _raster_pixels(_chart(styles=_ROOT_STYLES))
    assert tuple(pixels[30, 450][:3]) == (0x0F, 0x17, 0x2A)


def test_root_radius_corners_show_the_underlay_not_native_white() -> None:
    # Opaque dark root with a big radius: the corner pixel is the white
    # underlay (the browser's host page), the inside is the root fill —
    # so the fast_png full-coverage skip may not fire for a rounded patch.
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series"),
        styles={"root": {"background": "#112233", "border_radius": "40px"}},
    )
    pixels = _raster_pixels(chart)
    assert tuple(pixels[0, 0]) == (255, 255, 255, 255)
    assert tuple(pixels[60, 450][:3]) == (0x11, 0x22, 0x33)
    # And on a transparent fast-path export the corners are transparent,
    # never uninitialized native white.
    png = _transparent_rgba(chart.figure())
    assert tuple(png[0, 0]) == (0, 0, 0, 0)


def test_transparent_export_background_kills_the_root_paint() -> None:
    fig = _chart(styles=_ROOT_STYLES).figure()
    svg = export.to_image(fig, "svg", background="transparent").decode()
    assert "#0f172a" not in svg  # the fill is silenced...
    assert "#334155" in svg  # ...the border is chrome, not backdrop
    png = _transparent_rgba(fig)
    assert png[5, 450][3] == 0
    # The override mutates one export's spec, never the figure: the next
    # un-overridden export keeps the declared root paint.
    assert "#0f172a" in fig.to_svg()


def test_root_shadow_is_a_named_loss_and_never_grows_the_canvas() -> None:
    chart = _chart(styles={"root": {"background": "#111", "box_shadow": "4px 4px #000"}})
    report = chart.style_compatibility_report("png")
    finding = next(f for f in report.findings if f.slot == "root")
    assert "box-shadow" in finding.lost
    svg = chart.figure().to_svg()
    assert 'width="900" height="420"' in svg[:200]  # viewBox untouched
    assert svg.count('width="900" height="420"') >= 2  # svg + the root rect


def test_theme_background_becomes_the_root_box_fill_when_unset() -> None:
    # Same element, one `background` property: a root border/radius rounds
    # the theme figure patch instead of stacking a second paint.
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series"),
        xy.theme(background="#221100"),
        styles={"root": {"border_radius": "16px"}},
    )
    svg = chart.figure().to_svg()
    rect = re.search(r"<rect[^>]*/>", svg[svg.index("</defs>") :]).group(0)
    assert 'fill="#221100"' in rect and 'rx="16"' in rect
    assert svg.count("#221100") == 1  # replaced, not doubled


# -- chrome -------------------------------------------------------------------


def test_chrome_background_sits_above_root_below_grid_in_svg() -> None:
    svg = (
        _chart(
            styles={
                "root": {"background": "#0f172a"},
                "chrome": {"background": "rgba(255, 0, 0, 0.25)"},
            }
        )
        .figure()
        .to_svg()
    )
    root_at = svg.index("#0f172a")
    chrome_at = svg.index("rgba(255, 0, 0, 0.25)")
    grid_at = svg.index("<g>")
    assert root_at < chrome_at < grid_at
    _pdf_round_trips(svg)


def test_chrome_background_composites_in_the_raster_writer() -> None:
    pixels = _raster_pixels(
        _chart(
            styles={
                "root": {"background": "#0000ff"},
                "chrome": {"background": "rgba(255, 0, 0, 0.5)"},
            }
        )
    )
    # 50% red over blue in the margin corner.
    assert tuple(pixels[0, 0][:3]) == (128, 0, 127)
    # The stacking divergence against the browser's DOM order is recorded.
    assert "chrome_slot_title_stacking" in {d.id for d in KNOWN_RENDERER_DIVERGENCES}


# -- canvas -------------------------------------------------------------------

_CANVAS_STYLES = {"canvas": {"background": "#fefce8"}}


def test_canvas_background_paints_at_the_above_grid_seam() -> None:
    svg = _chart(styles=_CANVAS_STYLES).figure().to_svg()
    grid_close = svg.index("</g>")
    marks_open = svg.index('<g clip-path="url(#')
    canvas_at = svg.index("#fefce8")
    assert grid_close < canvas_at < marks_open


def test_canvas_background_hides_the_grid_in_the_raster_writer() -> None:
    plain_chart = _chart()
    styled_chart = _chart(styles=_CANVAS_STYLES)
    spec, _ = plain_chart.figure().build_payload()
    *_, plot = _svg.layout(spec)
    plain = _raster_pixels(plain_chart)
    styled = _raster_pixels(styled_chart)
    # The first vertical gridline, sampled mid-height (the data line for
    # [0,1,2]->[0,1,.5] is far from mid-height at that x).
    unstyled_svg = plain_chart.figure().to_svg()
    grid_x = float(re.search(r'<line x1="([\d.]+)"', unstyled_svg).group(1))
    row, col = int(plot["y"] + plot["h"] / 2), int(grid_x)
    assert tuple(plain[row, col]) != (255, 255, 255, 255)  # grid ink visible
    assert tuple(styled[row, col][:3]) == (0xFE, 0xFC, 0xE8)  # hidden by the box


def test_canvas_radius_clips_the_marks_through_a_third_clippath() -> None:
    styled = {"canvas": {"background": "#fefce8", "border_radius": "10px", "opacity": 0.9}}
    svg = _chart(styles=styled).figure().to_svg()
    # A dedicated clipPath: the plot/legend clip stays untouched (mutating it
    # vanishes polar legends), and the wrapper group carries the clip and the
    # declared opacity around the marks.
    assert svg.count("<clipPath") == 2
    clip_ids = re.findall(r'<clipPath id="([^"]+)"', svg)
    assert re.search(rf'<g clip-path="url\(#{clip_ids[1]}\)" opacity="0.9">', svg)
    _pdf_round_trips(svg)


def test_canvas_border_composes_with_the_spines() -> None:
    svg = (
        _chart(styles={"canvas": {"border_color": "#a16207", "border_width": 2}}).figure().to_svg()
    )
    spec, _ = _chart().figure().build_payload()
    *_, plot = _svg.layout(spec)
    rect = next(r for r in re.findall(r"<rect[^>]*/>", svg) if "#a16207" in r)
    assert f'x="{_svg._num(plot["x"])}"' in rect
    # The default spines still draw afterwards (the border does not replace
    # them): the axis baselines survive byte-identically.
    plain = _chart().figure().to_svg()
    baseline = re.search(r'<line x1="62"[^>]*stroke="rgba\(32,32,32,0\.5', plain)
    assert baseline is not None and baseline.group(0) in svg


def test_transparent_export_background_kills_the_canvas_paint() -> None:
    fig = _chart(styles=_CANVAS_STYLES).figure()
    svg = export.to_image(fig, "svg", background="transparent").decode()
    assert "#fefce8" not in svg


# -- the declared resolver ----------------------------------------------------


def test_box_shorthands_intern_as_longhands_in_the_snapshot() -> None:
    chart = _chart(
        styles={
            "title": {"padding": "4px 8px", "border": "2px dashed #333"},
            "legend": {"padding": "1.2em"},  # stays writer-domain, authored spelling
        }
    )
    spec, _ = chart.figure().build_payload()
    styling = resolve_declared(spec)
    by_slot = {
        inst.slot: styling.snapshot.declarations[inst.declaration]
        for inst in styling.snapshot.instances
    }
    assert by_slot["title"]["padding-top"] == 4.0
    assert by_slot["title"]["padding-right"] == 8.0
    assert by_slot["title"]["border-width"] == 2.0
    assert by_slot["title"]["border-style"] == "dashed"
    assert by_slot["title"]["border-color"] == "#333"
    assert styling.writer_domain["legend"] == {"padding": "1.2em"}


def test_declared_resolver_populates_root_and_chrome_geometry() -> None:
    chart = _chart(styles={"root": {"background": "#111"}, "chrome": {"opacity": 0.5}})
    spec, _ = chart.figure().build_payload()
    styling = resolve_declared(spec)
    geometry = {inst.slot: inst.geometry for inst in styling.snapshot.instances}
    env = styling.snapshot.environment
    assert geometry["root"] == (0.0, 0.0, env.width, env.height)
    assert geometry["chrome"] == (0.0, 0.0, env.width, env.height)
