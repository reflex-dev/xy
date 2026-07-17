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
array; NumPy pastes them onto one canvas and the engine's PNG encoder writes
the file. This module and `_mplfig.savefig` are the only places the shim
reaches past the public API (via `Chart.figure()` + the `_raster`/`_png`
modules); everything else goes through `xy`' public surface.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

import numpy as np


def compose_html(
    charts: list[Any],
    nrows: int,
    ncols: int,
    suptitle: Optional[str],
    suptitle_style: Optional[dict[str, Any]] = None,
    *,
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
        grid = "\n".join(panels) + ("\n" + title_html if title_html else "")
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
  .xy-suptitle {{ text-align: center; margin: 8px 0 0; font-size: 16px; color: #262626; }}
  {grid_css}
  .xy-panel {{ position: relative; }}
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
        title_h = 28 if suptitle else 0
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
    # y is a figure fraction measured from the bottom, like matplotlib.
    baseline = min(height - 2.0, (1.0 - float(style.get("y", 0.98))) * height + 0.75 * size)
    title = (
        f'<text x="{width * float(style.get("x", 0.5)):g}" y="{baseline:g}" text-anchor="{anchor}" '
        f'font-family="{_html.escape(str(style.get("family", "system-ui,sans-serif")))}" font-size="{size:g}" font-weight="{_html.escape(str(style.get("weight", "normal")))}" fill="{_html.escape(str(style.get("color", "#262626")))}">{_html.escape(suptitle)}</text>'
        if suptitle
        else ""
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{title}{"".join(body)}</svg>'
    )


def stitch_png(
    charts: list[Any],
    nrows: int,
    ncols: int,
    suptitle: Optional[str],
    colorbar: Optional[dict[str, Any]] = None,
    *,
    suptitle_style: Optional[dict[str, Any]] = None,
    positions: Optional[list[tuple[float, float, float, float]]] = None,
    canvas_size: Optional[tuple[int, int]] = None,
    facecolor: str = "white",
    bbox_tight: bool = False,
    pad_pixels: int = 0,
) -> bytes:
    from xy import _png, _raster  # sanctioned escape hatch (see module doc)

    scale = 2.0
    if (
        len(charts) == 1
        and positions is None
        and not suptitle
        and not colorbar
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

    tiles: list[np.ndarray] = []
    for chart in charts:
        fig = chart.figure()
        spec, blob, borrowed = fig._build_raster_payload(px_width=max(256, int(fig.width)))
        spec["canvas_background"] = facecolor
        img = _raster.render_raster(spec, blob, scale, borrowed=borrowed)
        if isinstance(img, bytes):
            raise RuntimeError("pyplot grid rasterizer unexpectedly returned encoded PNG bytes")
        tiles.append(img)
    if not tiles:
        raise ValueError("figure has no axes to save")

    if positions is not None and canvas_size is not None:
        background = np.asarray(_raster._parse_color(facecolor), dtype=np.uint8)
        canvas = np.empty((canvas_size[1] * 2, canvas_size[0] * 2, 4), dtype=np.uint8)
        canvas[...] = background
        for tile, (left, bottom, _width, height) in zip(tiles, positions, strict=True):
            x = round(left * canvas.shape[1])
            y = round((1.0 - bottom - height) * canvas.shape[0])
            dest_x0, dest_y0 = max(0, x), max(0, y)
            src_x0, src_y0 = max(0, -x), max(0, -y)
            dest_x1 = min(canvas.shape[1], x + tile.shape[1])
            dest_y1 = min(canvas.shape[0], y + tile.shape[0])
            if dest_x1 > dest_x0 and dest_y1 > dest_y0:
                canvas[dest_y0:dest_y1, dest_x0:dest_x1] = tile[
                    src_y0 : src_y0 + dest_y1 - dest_y0,
                    src_x0 : src_x0 + dest_x1 - dest_x0,
                ]
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
    title_h = 48 if suptitle else 0
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
        from xy import kernels

        cmd = _raster._Cmd(scale)
        style = suptitle_style or {}
        cmd.text(
            canvas.shape[1] * float(style.get("x", 0.5)) / scale,
            17,
            1,
            float(style.get("size", 14)),
            _raster._parse_color(str(style.get("color", "#262626"))),
            suptitle,
        )
        overlay = kernels.rasterize(bytes(cmd.buf), canvas.shape[1], title_h)
        alpha = overlay[:, :, 3:4].astype(np.float64) / 255.0
        canvas[:title_h, :, :3] = np.round(
            overlay[:, :, :3] * alpha + canvas[:title_h, :, :3] * (1.0 - alpha)
        ).astype(np.uint8)
    if colorbar:
        from xy._svg import _lut

        x0, x1 = int(canvas.shape[1] * 0.15), int(canvas.shape[1] * 0.85)
        y0 = title_h + sum(row_heights) + 12
        gradient = _lut(colorbar.get("colormap", "viridis"), np.linspace(0.0, 1.0, max(2, x1 - x0)))
        canvas[y0 : y0 + 16, x0:x1, :3] = gradient[None, :, :]
        canvas[y0 : y0 + 16, x0:x1, 3] = 255
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
