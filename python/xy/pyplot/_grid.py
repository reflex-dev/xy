"""Multi-panel composition — the shim-owned replacement for an engine grid.

HTML: one self-contained document (same zero-dependency offline story as
`Chart.to_html`): the render client ships once and every panel hydrates into
a host div, so all panels share the page-level WebGL context governor. A
panel-per-iframe composition put each panel in its own document with its own
governor, and a dense subplot grid exceeded the browser's per-page context
cap — only the first ~dozen panels ever rendered. The shared governor
snapshots and releases over-budget panels instead; pointer entry revives
them.

PNG: each panel renders through the engine's native rasterizer to an RGBA
array; NumPy composites them onto one canvas and the engine's PNG encoder
writes the file. Absolutely placed panels are rendered on a transparent canvas
and alpha-composited, because a panel is wider than its gridspec cell — its
tick labels and title live outside the plot rect — and an opaque paste made
each column erase the one to its left. This module and `_mplfig.savefig` are
the only places the shim
reaches past the public API (via `Chart.figure()` + the `_raster`/`_png`
modules); everything else goes through `xy`' public surface.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

import numpy as np

from .. import _textblock


def _svg_text_lines(text: object, x: float, line_step: float) -> str:
    lines = []
    for index, line in enumerate(_textblock.split_lines(text)):
        dy = f' dy="{line_step:g}"' if index else ""
        lines.append(f'<tspan x="{x:g}"{dy}>{_html.escape(line)}</tspan>')
    return "".join(lines)


def _suptitle_baseline(
    canvas_height: float,
    title_band_height: float,
    style: dict[str, Any],
    block: Optional[_textblock.TextBlock],
    size: float,
) -> float:
    """First baseline at the authored figure fraction, contained by its band."""
    ascent = block.ascent if block is not None else 0.75 * size
    descent = block.descent if block is not None else 0.25 * size
    trailing = (block.line_count - 1) * block.line_step if block is not None else 0.0
    desired = (1.0 - float(style.get("y", 0.98))) * canvas_height + ascent
    # The reserved band owns the complete text block, not only its first
    # baseline. Clamp both the leading ascent and final descender inside it.
    maximum = max(ascent, title_band_height - trailing - descent - 2.0)
    return min(max(ascent, desired), maximum)


def _figure_label_baseline(
    canvas_height: float,
    label: dict[str, Any],
    block: _textblock.TextBlock,
) -> float:
    desired = (1.0 - float(label.get("y", 0.5))) * canvas_height
    trailing = (block.line_count - 1) * block.line_step
    alignment = str(label.get("vertical_align", "center"))
    if alignment == "top":
        return desired + block.ascent
    if alignment == "baseline":
        return desired
    if alignment == "bottom":
        return desired - trailing - block.descent
    return desired + (block.ascent - trailing - block.descent) / 2.0


def _svg_figure_labels(labels: list[dict[str, Any]], width: float, height: float) -> str:
    body = []
    for label in labels:
        size = float(label.get("size", 12.0))
        block = _textblock.measure(label.get("text", ""), size)
        x = width * float(label.get("x", 0.5))
        y = _figure_label_baseline(height, label, block)
        anchor = str(label.get("anchor", "middle"))
        angle = -float(label.get("rotation", 0.0))
        transform = f' transform="rotate({angle:g} {x:g} {y:g})"' if angle else ""
        body.append(
            f'<text x="{x:g}" y="{y:g}" text-anchor="{_html.escape(anchor)}"'
            f'{transform} font-family="{_html.escape(str(label.get("family", "system-ui,sans-serif")))}"'
            f' font-size="{size:g}" font-style="{_html.escape(str(label.get("font_style", "normal")))}"'
            f' font-weight="{_html.escape(str(label.get("weight", "normal")))}"'
            f' fill="{_html.escape(str(label.get("color", "#262626")))}"'
            f' fill-opacity="{float(label.get("opacity", 1.0)):g}">'
            f"{_svg_text_lines(label.get('text', ''), x, block.line_step)}</text>"
        )
    return "".join(body)


def _html_figure_labels(labels: list[dict[str, Any]]) -> str:
    body = []
    for label in labels:
        anchor = str(label.get("anchor", "middle"))
        shift_x = {"start": "0%", "middle": "-50%", "end": "-100%"}.get(anchor, "-50%")
        alignment = str(label.get("vertical_align", "center"))
        shift_y = {
            "top": "0%",
            "baseline": "-100%",
            "bottom": "-100%",
            "center": "-50%",
            "center_baseline": "-50%",
        }.get(alignment, "-50%")
        angle = -float(label.get("rotation", 0.0))
        body.append(
            "<div class='xy-figure-label' style='position:absolute;"
            f"left:{float(label.get('x', 0.5)) * 100:g}%;"
            f"top:{(1.0 - float(label.get('y', 0.5))) * 100:g}%;"
            f"transform:translate({shift_x},{shift_y}) rotate({angle:g}deg);"
            f"font-size:{float(label.get('size', 12.0)):g}px;"
            f"font-family:{_html.escape(str(label.get('family', 'system-ui,sans-serif')))};"
            f"font-style:{_html.escape(str(label.get('font_style', 'normal')))};"
            f"font-weight:{_html.escape(str(label.get('weight', 'normal')))};"
            f"color:{_html.escape(str(label.get('color', '#262626')))};"
            f"opacity:{float(label.get('opacity', 1.0)):g}'>"
            f"{_html.escape(str(label.get('text', '')))}</div>"
        )
    return "".join(body)


def _html_figure_legend(legend: Optional[dict[str, Any]]) -> str:
    if not legend or not legend.get("items"):
        return ""
    options = legend.get("style") or {}
    rows = []
    for item in legend["items"]:
        item_style = item.get("style") or {}
        color = _html.escape(str(item_style.get("color", "#4c78a8")))
        kind = str(item.get("kind", "line"))
        if kind in {"line", "segments", "step", "stairs", "errorbar"}:
            swatch_style = (
                "height:0;background:transparent;"
                f"border-top:{float(item_style.get('width', 2.0)):g}px "
                f"{'dashed' if item_style.get('dash') else 'solid'} {color}"
            )
        elif kind == "scatter":
            swatch_style = f"width:9px;height:9px;border-radius:50%;background:{color}"
        else:
            swatch_style = f"height:9px;background:{color}"
        rows.append(
            "<div class='xy-figure-legend-row'>"
            f"<span class='xy-figure-legend-swatch' style='{swatch_style}'></span>"
            f"<span>{_html.escape(str(item.get('name', '')))}</span></div>"
        )
    ncols = max(1, int(legend.get("ncols", 1)))
    loc = (
        "upper right"
        if legend.get("figure_loc") == "outside right upper"
        else str(legend.get("loc", "upper right"))
    )
    transforms = []
    if "left" in loc:
        horizontal = "left:6px;"
    elif "right" in loc:
        horizontal = "right:6px;"
    else:
        horizontal = "left:50%;"
        transforms.append("translateX(-50%)")
    vertical = "top:6px;" if "upper" in loc else "bottom:6px;" if "lower" in loc else "top:50%;"
    if "upper" not in loc and "lower" not in loc:
        transforms.append("translateY(-50%)")
    transform = f"transform:{' '.join(transforms)};" if transforms else ""
    title = legend.get("title")
    title_html = (
        "<div class='xy-figure-legend-title' "
        f"style='grid-column:1/{ncols + 1}'>{_html.escape(str(title))}</div>"
        if title
        else ""
    )
    return (
        "<div class='xy-figure-legend' style='position:absolute;"
        f"{horizontal}{vertical}{transform}"
        f"grid-template-columns:repeat({ncols},max-content);"
        f"font-size:{_html.escape(str(options.get('fontSize', '11px')))};"
        f"color:{_html.escape(str(options.get('color', '#262626')))};"
        f"background:{_html.escape(str(options.get('background', 'rgba(255,255,255,.92)')))};"
        f"border-color:{_html.escape(str(options.get('borderColor', '#cccccc')))}'>"
        f"{title_html}{''.join(rows)}</div>"
    )


def _composite_rgba(destination: np.ndarray, source: np.ndarray) -> None:
    """Composite a straight-alpha RGBA tile over ``destination`` in place.

    Matplotlib draws every axes onto one canvas, so a panel's chrome may hang
    over a neighbour's without erasing it. Alpha compositing is the equivalent
    for panel-per-render composition; an opaque paste is not.
    """
    source_alpha = source[:, :, 3]
    opaque = source_alpha == 255
    destination[opaque] = source[opaque]
    partial = (source_alpha != 0) & ~opaque
    if not np.any(partial):
        return
    src = source[partial].astype(np.float32)
    dst = destination[partial].astype(np.float32)
    src_alpha_f = src[:, 3:4] / 255.0
    dst_alpha_f = dst[:, 3:4] / 255.0
    out_alpha = src_alpha_f + dst_alpha_f * (1.0 - src_alpha_f)
    out_rgb = np.divide(
        src[:, :3] * src_alpha_f + dst[:, :3] * dst_alpha_f * (1.0 - src_alpha_f),
        out_alpha,
        out=np.zeros_like(src[:, :3]),
        where=out_alpha != 0,
    )
    destination[partial, :3] = np.rint(out_rgb).astype(np.uint8)
    destination[partial, 3] = np.rint(out_alpha[:, 0] * 255.0).astype(np.uint8)


def _compose_canvas(
    tiles: list[np.ndarray],
    positions: list[tuple[float, float, float, float]],
    canvas_size: tuple[int, int],
    facecolor: str,
    scale: float,
) -> np.ndarray:
    """Alpha-composite absolutely placed panel tiles onto one RGBA figure canvas.

    `positions` are whole-panel [left, bottom, width, height] figure fractions,
    bottom-origin like matplotlib; document order stacks later axes above
    earlier ones, as matplotlib draws.
    """
    from xy import _raster

    background = np.asarray(_raster._parse_color(facecolor), dtype=np.uint8)
    canvas = np.empty(
        (round(canvas_size[1] * scale), round(canvas_size[0] * scale), 4), dtype=np.uint8
    )
    canvas[...] = background
    for tile, (left, bottom, _width, height) in zip(tiles, positions, strict=True):
        x = round(left * canvas.shape[1])
        y = round((1.0 - bottom - height) * canvas.shape[0])
        dest_x0, dest_y0 = max(0, x), max(0, y)
        src_x0, src_y0 = max(0, -x), max(0, -y)
        dest_x1 = min(canvas.shape[1], x + tile.shape[1])
        dest_y1 = min(canvas.shape[0], y + tile.shape[0])
        if dest_x1 > dest_x0 and dest_y1 > dest_y0:
            _composite_rgba(
                canvas[dest_y0:dest_y1, dest_x0:dest_x1],
                tile[
                    src_y0 : src_y0 + dest_y1 - dest_y0,
                    src_x0 : src_x0 + dest_x1 - dest_x0,
                ],
            )
    return canvas


def compose_html(
    charts: list[Any],
    nrows: int,
    ncols: int,
    suptitle: Optional[str],
    suptitle_style: Optional[dict[str, Any]] = None,
    *,
    figure_labels: Optional[list[dict[str, Any]]] = None,
    figure_legend: Optional[dict[str, Any]] = None,
    positions: Optional[list[tuple[float, float, float, float]]] = None,
    canvas_size: Optional[tuple[int, int]] = None,
) -> str:
    """Compose panel documents into one page.

    Default: a CSS grid of panels. With ``positions`` (whole-panel
    [left, bottom, width, height] figure fractions, bottom-origin like
    matplotlib) and ``canvas_size`` px, panels are absolutely placed on a
    fixed-size canvas instead — the add_axes/subplots_adjust layout path.
    Document order stacks later axes above earlier ones, as matplotlib draws.
    """
    from xy import export

    absolute = positions is not None and canvas_size is not None
    panels = []
    payloads = []
    for index, chart in enumerate(charts):
        figure = chart.figure()
        spec, blob = figure.build_payload()
        # Exact chart size: absolute placement relies on the panel's plot box
        # landing on its matplotlib rect, so a dense grid's sub-120px panels
        # must not be inflated here (the client honors small explicit sizes).
        width = int(figure.width)
        height = int(figure.height)
        placement = ""
        if absolute:
            left, bottom, _width, panel_height = positions[index]
            x = round(left * canvas_size[0])
            y = round((1.0 - bottom - panel_height) * canvas_size[1])
            placement = f"position:absolute;left:{x}px;top:{y}px;"
        panels.append(
            '<div class="xy-panel" data-xy-pyplot-panel '
            f'style="{placement}width:{width}px;height:{height}px"></div>'
        )
        payloads.append(
            "{" + f'"spec":{export._json_for_inline_script(spec)},'
            f'"chunks":{export._json_for_inline_script(export._base64_chunks(blob))},'
            f'"n":{len(blob)}' + "}"
        )
    style = suptitle_style or {}
    title_css = (
        f"font-size:{float(style.get('size', 16)):g}px;font-weight:{_html.escape(str(style.get('weight', 'normal')))};"
        f"font-family:{_html.escape(str(style.get('family', 'system-ui, sans-serif')))};"
        f"color:{_html.escape(str(style.get('color', '#262626')))}"
    )
    if not suptitle:
        title_html = ""
    elif absolute:
        # The suptitle anchors at figure-fraction (x, y) on the canvas itself.
        shift = {"left": "0%", "center": "-50%", "right": "-100%"}.get(
            str(style.get("ha", "center")), "-50%"
        )
        title_html = (
            "<div class='xy-suptitle' style='position:absolute;"
            f"left:{float(style.get('x', 0.5)) * 100:g}%;"
            f"top:{(1.0 - float(style.get('y', 0.98))) * 100:g}%;"
            f"transform:translate({shift},0);margin:0;{title_css}'>"
            f"{_html.escape(suptitle)}</div>"
        )
    else:
        title_html = f"<h2 class='xy-suptitle' style='{title_css}'>{_html.escape(suptitle)}</h2>"
    if absolute:
        grid_css = (
            f".xy-grid {{ position: relative; width: {canvas_size[0]}px; "
            f"height: {canvas_size[1]}px; overflow: hidden; }}"
        )
        decorations = (
            title_html
            + _html_figure_labels(figure_labels or [])
            + _html_figure_legend(figure_legend)
        )
        grid = "\n".join(panels) + ("\n" + decorations if decorations else "")
        title_html = ""
    else:
        grid_css = (
            f".xy-grid {{ display: grid; grid-template-columns: repeat({ncols}, max-content); "
            "gap: 4px; padding: 4px; overflow-x: auto; }}"
        )
        grid = "\n".join(panels)
    client_js = export._javascript_for_inline_script(export._bundled_js("standalone"))
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{export._STANDALONE_CSP}">
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #ffffff; }}
  .xy-suptitle {{ text-align: center; margin: 8px 0 0; font-size: 16px; color: #262626; white-space: pre-line; line-height: 1.2; }}
  {grid_css}
  .xy-panel {{ position: relative; }}
  .xy-figure-label {{ z-index: 4; white-space: pre-line; line-height: 1.2; pointer-events: none; }}
  .xy-figure-legend {{ z-index: 4; display: grid; gap: 5px; padding: 5px 7px; border: 1px solid; border-radius: 4px; }}
  .xy-figure-legend-row {{ display: flex; align-items: center; gap: 7px; white-space: nowrap; }}
  .xy-figure-legend-title {{ font-weight: 600; }}
  .xy-figure-legend-swatch {{ box-sizing: border-box; display: inline-block; width: 18px; height: 3px; }}
</style>
</head>
<body>
{title_html}
<div class="xy-grid">
{grid}
</div>
<script>{client_js}</script>
<script>
{export._DECODE_B64_JS}
const panels = [{",".join(payloads)}];
const hosts = document.querySelectorAll("[data-xy-pyplot-panel]");
panels.forEach((p, i) => {{
  xy.renderStandalone(hosts[i], p.spec, xyDecodeB64(p.chunks, p.n));
}});
</script>
</body>
</html>"""


def compose_svg(
    charts: list[Any],
    nrows: int,
    ncols: int,
    suptitle: Optional[str],
    suptitle_style: Optional[dict[str, Any]] = None,
    *,
    figure_labels: Optional[list[dict[str, Any]]] = None,
    figure_legend: Optional[dict[str, Any]] = None,
    positions: Optional[list[tuple[float, float, float, float]]] = None,
    canvas_size: Optional[tuple[int, int]] = None,
) -> str:
    """Compose subplot SVGs with isolated ids into one portable SVG document.

    Panels tile a uniform grid by default; with ``positions`` (whole-panel
    figure fractions, bottom-origin) and ``canvas_size`` px they are placed
    absolutely on a fixed canvas — the add_axes/subplots_adjust layout path.
    """
    from xy import _svg

    figures = [chart.figure() for chart in charts]
    if not figures:
        raise ValueError("figure has no axes to save")
    if positions is not None and canvas_size is not None:
        title_h = 0
        offsets = [
            (
                round(position[0] * canvas_size[0]),
                round((1.0 - position[1] - position[3]) * canvas_size[1]),
            )
            for position in positions
        ]
        total_size: tuple[int, int] = (int(canvas_size[0]), int(canvas_size[1]))
    else:
        col_widths = [
            max(int(figures[index].width) for index in range(col, len(figures), ncols))
            for col in range(ncols)
        ]
        row_heights = [
            max(
                int(figures[index].height)
                for index in range(row * ncols, min((row + 1) * ncols, len(figures)))
            )
            for row in range(nrows)
        ]
        style = suptitle_style or {}
        size = float(style.get("size", 16))
        title_h = round(_textblock.measure(suptitle, size).height + 12) if suptitle else 0
        offsets = []
        for index in range(len(figures)):
            row, col = divmod(index, ncols)
            offsets.append((sum(col_widths[:col]), title_h + sum(row_heights[:row])))
        total_size = (sum(col_widths), title_h + sum(row_heights))
    body: list[str] = []
    for index, figure in enumerate(figures):
        svg = _svg.to_svg(figure, id_prefix=f"xy-panel-{index}-")
        inner = svg[svg.find(">") + 1 : svg.rfind("</svg>")]
        body.append(
            f'<svg x="{offsets[index][0]}" y="{offsets[index][1]}" '
            f'width="{int(figure.width)}" height="{int(figure.height)}" '
            f'viewBox="0 0 {int(figure.width)} {int(figure.height)}">{inner}</svg>'
        )
    style = suptitle_style or {}
    anchor = {"left": "start", "center": "middle", "right": "end"}.get(
        str(style.get("ha", "center")), "middle"
    )
    width, height = total_size
    size = float(style.get("size", 16))
    block = _textblock.measure(suptitle, size) if suptitle else None
    # y is a figure fraction measured from the bottom, like matplotlib. Grid
    # composition reserves ``title_h``; absolute composition overlays the full
    # canvas and therefore uses that as the available title band.
    baseline = _suptitle_baseline(
        height,
        float(title_h or height),
        style,
        block,
        size,
    )
    title = (
        f'<text x="{width * float(style.get("x", 0.5)):g}" y="{baseline:g}" text-anchor="{anchor}" '
        f'font-family="{_html.escape(str(style.get("family", "system-ui,sans-serif")))}" font-size="{size:g}" font-weight="{_html.escape(str(style.get("weight", "normal")))}" fill="{_html.escape(str(style.get("color", "#262626")))}">'
        f"{_svg_text_lines(suptitle, width * float(style.get('x', 0.5)), block.line_step)}</text>"
        if suptitle
        else ""
    )
    labels = _svg_figure_labels(figure_labels or [], width, height)
    legend = ""
    if figure_legend and figure_legend.get("items"):
        loc = (
            "upper right"
            if figure_legend.get("figure_loc") == "outside right upper"
            else figure_legend.get("loc", "upper right")
        )
        options = {**figure_legend, "loc": loc}
        legend = _svg._legend(
            list(figure_legend["items"]),
            {"x": 0.0, "y": 0.0, "w": float(width), "h": float(height)},
            options,
            "xy-figure-legend",
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{title}{"".join(body)}{labels}{legend}</svg>'
    )


def stitch_png(
    charts: list[Any],
    nrows: int,
    ncols: int,
    suptitle: Optional[str],
    colorbar: Optional[dict[str, Any]] = None,
    *,
    suptitle_style: Optional[dict[str, Any]] = None,
    figure_labels: Optional[list[dict[str, Any]]] = None,
    figure_legend: Optional[dict[str, Any]] = None,
    positions: Optional[list[tuple[float, float, float, float]]] = None,
    canvas_size: Optional[tuple[int, int]] = None,
    facecolor: str = "white",
    bbox_tight: bool = False,
    pad_pixels: int = 0,
) -> bytes:
    from xy import _png, _raster  # sanctioned escape hatch (see module doc)

    # pyplot charts are already built at ``figsize * dpi`` logical pixels.
    # Rasterizing those pixels at the core exporter's 2x quality default made
    # savefig silently double both output dimensions and every point-sized
    # artist compared with Matplotlib.  The pyplot compatibility boundary is
    # physical pixels, so keep its raster scale at one; callers that use the
    # native Figure API directly retain that API's explicit 2x default.
    scale = 1.0
    if (
        len(charts) == 1
        and positions is None
        and not suptitle
        and not colorbar
        and not figure_labels
        and not figure_legend
        and not bbox_tight
        and facecolor in ("white", "#ffffff")
    ):
        # A single panel with no chrome to compose is exactly one native
        # render, so fuse rasterization with the Rust PNG encoder (the
        # latency-first default of Figure.to_png) instead of round-tripping
        # RGBA through the Python size-oriented encoder — ~17x on a
        # 100k-point savefig. The fused canvas initializes white, which is
        # why the fast path is gated on the default facecolor.
        fig = charts[0].figure()
        spec, blob, borrowed = fig._build_raster_payload(px_width=max(256, int(fig.width)))
        spec["canvas_background"] = facecolor
        rendered = _raster.render_raster(spec, blob, scale, fast_png=True, borrowed=borrowed)
        if isinstance(rendered, bytes):
            return rendered
        return _png.encode(rendered)

    absolute = positions is not None and canvas_size is not None
    tiles: list[np.ndarray] = []
    for chart in charts:
        fig = chart.figure()
        spec, blob, borrowed = fig._build_raster_payload(px_width=max(256, int(fig.width)))
        # Absolute panels include their own surrounding chrome and therefore
        # overlap in the gutters.  Keep only that outer canvas transparent so
        # a later panel cannot erase an earlier panel's right/bottom spine or
        # terminal tick label.  The axes patch (--chart-bg) remains opaque.
        spec["canvas_background"] = "none" if absolute else facecolor
        img = _raster.render_raster(spec, blob, scale, borrowed=borrowed)
        if isinstance(img, bytes):
            raise RuntimeError("pyplot grid rasterizer unexpectedly returned encoded PNG bytes")
        tiles.append(img)
    if not tiles:
        raise ValueError("figure has no axes to save")

    if absolute:
        assert positions is not None and canvas_size is not None
        canvas = _compose_canvas(tiles, positions, canvas_size, facecolor, scale)
        if suptitle:
            _blend_raster_suptitle(
                canvas,
                suptitle,
                suptitle_style,
                scale=scale,
                title_h=canvas.shape[0],
                absolute=True,
            )
        _blend_raster_figure_decorations(
            canvas,
            figure_labels or [],
            figure_legend,
            scale=scale,
        )
        return _png.encode(canvas)

    col_widths = [
        max(tiles[index].shape[1] for index in range(col, len(tiles), ncols))
        for col in range(ncols)
    ]
    row_heights = [
        max(
            tiles[index].shape[0]
            for index in range(row * ncols, min((row + 1) * ncols, len(tiles)))
        )
        for row in range(nrows)
    ]
    suptitle_size = float((suptitle_style or {}).get("size", 14))
    title_h = round(_textblock.measure(suptitle, suptitle_size).height + 16) if suptitle else 0
    colorbar_h = 52 if colorbar else 0
    background = np.asarray(_raster._parse_color(facecolor), dtype=np.uint8)
    canvas = np.empty((title_h + sum(row_heights) + colorbar_h, sum(col_widths), 4), dtype=np.uint8)
    canvas[...] = background
    for i, tile in enumerate(tiles):
        r, c = divmod(i, ncols)
        y = title_h + sum(row_heights[:r])
        x = sum(col_widths[:c])
        canvas[y : y + tile.shape[0], x : x + tile.shape[1]] = tile
    if suptitle:
        _blend_raster_suptitle(
            canvas,
            suptitle,
            suptitle_style,
            scale=scale,
            title_h=title_h,
        )
    if colorbar:
        from xy._svg import _lut

        x0, x1 = int(canvas.shape[1] * 0.15), int(canvas.shape[1] * 0.85)
        y0 = title_h + sum(row_heights) + 12
        gradient = _lut(colorbar.get("colormap", "viridis"), np.linspace(0.0, 1.0, max(2, x1 - x0)))
        canvas[y0 : y0 + 16, x0:x1, :3] = gradient[None, :, :]
        canvas[y0 : y0 + 16, x0:x1, 3] = 255
    _blend_raster_figure_decorations(
        canvas,
        figure_labels or [],
        figure_legend,
        scale=scale,
    )
    if bbox_tight:
        # Crop the figure-colored margin, retaining a Matplotlib-like pad.  Do
        # this on the composed RGBA buffer so it works for subplot grids and
        # absolute axes without asking each renderer for a separate bbox.
        delta = np.any(canvas != background, axis=2)
        ys, xs = np.nonzero(delta)
        if len(xs):
            x0 = max(0, int(xs.min()) - pad_pixels)
            x1 = min(canvas.shape[1], int(xs.max()) + pad_pixels + 1)
            y0 = max(0, int(ys.min()) - pad_pixels)
            y1 = min(canvas.shape[0], int(ys.max()) + pad_pixels + 1)
            canvas = canvas[y0:y1, x0:x1]
    return _png.encode(canvas)


def _blend_raster_suptitle(
    canvas: np.ndarray,
    suptitle: str,
    style: Optional[dict[str, Any]],
    *,
    scale: float,
    title_h: int,
    absolute: bool = False,
) -> None:
    """Draw a figure suptitle onto either grid or absolute-position PNGs."""
    from xy import _raster, kernels

    resolved = style or {}
    cmd = _raster._Cmd(scale)
    size = float(resolved.get("size", 14))
    block = _textblock.measure(suptitle, size)
    x = canvas.shape[1] * float(resolved.get("x", 0.5)) / scale
    baseline = _suptitle_baseline(
        canvas.shape[0] / scale,
        (canvas.shape[0] if absolute else title_h) / scale,
        resolved,
        block,
        size,
    )
    color = _raster._parse_color(str(resolved.get("color", "#262626")))
    bold = str(resolved.get("weight", "normal")).lower() in {
        "bold",
        "semibold",
        "demibold",
        "heavy",
        "black",
    }
    for index, line in enumerate(block.lines):
        cmd.text(x, baseline + index * block.line_step, 1, size, color, line, bold=bold)
    overlay = kernels.rasterize(bytes(cmd.buf), canvas.shape[1], title_h)
    _composite_rgba(canvas[:title_h], overlay)


def _blend_raster_figure_decorations(
    canvas: np.ndarray,
    labels: list[dict[str, Any]],
    legend: Optional[dict[str, Any]],
    *,
    scale: float,
) -> None:
    """Paint figure-fraction labels and the figure legend on one overlay."""
    if not labels and not legend:
        return
    from xy import _raster, kernels

    cmd = _raster._Cmd(scale)
    logical_w = canvas.shape[1] / scale
    logical_h = canvas.shape[0] / scale
    for label in labels:
        size = float(label.get("size", 12.0))
        block = _textblock.measure(label.get("text", ""), size)
        x = logical_w * float(label.get("x", 0.5))
        baseline = _figure_label_baseline(logical_h, label, block)
        anchor = {"start": 0, "middle": 1, "end": 2}.get(str(label.get("anchor", "middle")), 1)
        color = _raster._parse_color(str(label.get("color", "#262626")))
        opacity = min(1.0, max(0.0, float(label.get("opacity", 1.0))))
        color = (*color[:3], round(color[3] * opacity))
        italic = str(label.get("font_style", "normal")) in {"italic", "oblique"}
        bold = str(label.get("weight", "normal")).lower() in {
            "bold",
            "semibold",
            "demibold",
            "heavy",
            "black",
        }
        for index, line in enumerate(block.lines):
            cmd.text(
                x,
                baseline + index * block.line_step,
                anchor,
                size,
                color,
                line,
                angle=-float(label.get("rotation", 0.0)),
                italic=italic,
                bold=bold,
            )
    if legend and legend.get("items"):
        loc = (
            "upper right"
            if legend.get("figure_loc") == "outside right upper"
            else legend.get("loc", "upper right")
        )
        _raster._emit_legend(
            cmd,
            list(legend["items"]),
            {"x": 0.0, "y": 0.0, "w": logical_w, "h": logical_h},
            {**legend, "loc": loc},
            "#262626",
        )
    overlay = kernels.rasterize(bytes(cmd.buf), canvas.shape[1], canvas.shape[0])
    _composite_rgba(canvas, overlay)
