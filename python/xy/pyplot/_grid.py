"""Multi-panel composition — the shim-owned replacement for an engine grid.

HTML: one self-contained document, panels in a CSS grid, each panel embedded
as a sandboxed ``srcdoc`` iframe of its own standalone chart document (same
zero-dependency offline story as `Chart.to_html`).  A page-level visibility
governor unloads off-screen panel documents.  This matters in notebooks where
many executed multi-panel cells would otherwise keep enough independent
WebGL contexts alive for the browser to evict arbitrary visible canvases.

PNG: each panel renders through the engine's native rasterizer to an RGBA
array; NumPy pastes them onto one canvas and the engine's PNG encoder writes
the file. This module and `_mplfig.savefig` are the only places the shim
reaches past the public API (via `Chart.figure()` + the `_raster`/`_png`
modules); everything else goes through `xy`' public surface.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional, cast

import numpy as np


def compose_html(charts: list[Any], nrows: int, ncols: int, suptitle: Optional[str]) -> str:
    panels = []
    for chart in charts:
        doc = chart.to_html()
        figure = chart.figure()
        width = max(120, int(figure.width))
        height = max(120, int(figure.height))
        panels.append(
            '<iframe class="fc-panel" data-fc-pyplot-panel '
            'loading="lazy" sandbox="allow-scripts" '
            f'style="width:{width}px;height:{height}px" '
            f'srcdoc="{_html.escape(doc, quote=True)}"></iframe>'
        )
    title_html = f"<h2 class='fc-suptitle'>{_html.escape(suptitle)}</h2>" if suptitle else ""
    grid = "\n".join(panels)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #ffffff; }}
  .fc-suptitle {{ text-align: center; margin: 8px 0 0; font-size: 16px; color: #262626; }}
  .fc-grid {{ display: grid; grid-template-columns: repeat({ncols}, max-content); gap: 4px; padding: 4px; overflow-x: auto; }}
  .fc-panel {{ border: 0; display: block; }}
</style>
</head>
<body>
{title_html}
<div class="fc-grid">
{grid}
</div>
<script>
(() => {{
  const key = "__xyPyplotPanelGovernorV1";
  const blank = "<!doctype html><html><body style='margin:0;background:#fff'></body></html>";
  let governor = window[key];
  if (!governor) {{
    const states = new WeakMap();
    let sequence = 0;
    const observer = new IntersectionObserver((entries) => {{
      for (const entry of entries) {{
        const frame = entry.target;
        const state = states.get(frame);
        if (!state) continue;
        state.visible = entry.isIntersecting || entry.intersectionRatio > 0;
        if (state.visible) {{
          state.seen = ++sequence;
          clearTimeout(state.releaseTimer);
          state.releaseTimer = null;
          if (state.dormant && frame.isConnected) {{
            state.dormant = false;
            frame.srcdoc = state.source;
          }}
          continue;
        }}
        clearTimeout(state.releaseTimer);
        state.releaseTimer = setTimeout(() => {{
          if (state.visible || state.dormant || !frame.isConnected) return;
          state.dormant = true;
          frame.srcdoc = blank;
        }}, 120);
      }}
    }}, {{ rootMargin: "100% 0px 100% 0px" }});
    governor = window[key] = {{
      register(frame) {{
        if (states.has(frame)) return;
        states.set(frame, {{
          source: frame.srcdoc,
          visible: true,
          dormant: false,
          releaseTimer: null,
          seen: ++sequence,
        }});
        observer.observe(frame);
      }},
    }};
  }}
  const script = document.currentScript;
  const panelGrid = script && script.previousElementSibling;
  // Classic Jupyter may evaluate this script after insertion, when
  // document.currentScript is null.  Scanning the document is safe because
  // register() is idempotent through its WeakMap.
  const root = panelGrid || document;
  for (const frame of root.querySelectorAll("iframe[data-fc-pyplot-panel]")) {{
    governor.register(frame);
  }}
}})();
</script>
</body>
</html>"""


def compose_svg(charts: list[Any], nrows: int, ncols: int, suptitle: Optional[str]) -> str:
    """Compose subplot SVGs with isolated ids into one portable SVG document."""
    from xy import _svg

    figures = [chart.figure() for chart in charts]
    if not figures:
        raise ValueError("figure has no axes to save")
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
    body: list[str] = []
    for index, figure in enumerate(figures):
        svg = _svg.to_svg(figure, id_prefix=f"xy-panel-{index}-")
        inner = svg[svg.find(">") + 1 : svg.rfind("</svg>")]
        row, col = divmod(index, ncols)
        body.append(
            f'<svg x="{sum(col_widths[:col])}" y="{title_h + sum(row_heights[:row])}" '
            f'width="{int(figure.width)}" height="{int(figure.height)}" '
            f'viewBox="0 0 {int(figure.width)} {int(figure.height)}">{inner}</svg>'
        )
    title = (
        f'<text x="{sum(col_widths) / 2:g}" y="19" text-anchor="middle" '
        f'font-family="system-ui,sans-serif" font-size="16">{_html.escape(suptitle)}</text>'
        if suptitle
        else ""
    )
    width, height = sum(col_widths), title_h + sum(row_heights)
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
    positions: Optional[list[tuple[float, float, float, float]]] = None,
    canvas_size: Optional[tuple[int, int]] = None,
    facecolor: str = "white",
) -> bytes:
    from xy import _png, _raster  # sanctioned escape hatch (see module doc)

    scale = 2.0
    tiles: list[np.ndarray] = []
    for chart in charts:
        fig = chart.figure()
        spec, blob = fig.build_payload(px_width=max(256, int(fig.width)))
        img = cast(np.ndarray, _raster.render_raster(spec, blob, scale))
        tiles.append(img)
    if not tiles:
        raise ValueError("figure has no axes to save")

    if positions is not None and canvas_size is not None:
        to_rgba = __import__("matplotlib.colors", fromlist=["to_rgba"]).to_rgba

        rgba = np.asarray(to_rgba(facecolor), dtype=np.float64)
        background = np.round(rgba * 255).astype(np.uint8)
        canvas = np.empty((canvas_size[1] * 2, canvas_size[0] * 2, 4), dtype=np.uint8)
        canvas[...] = background
        for tile, (left, bottom, width, height) in zip(tiles, positions, strict=True):
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
    canvas = np.full(
        (title_h + sum(row_heights) + colorbar_h, sum(col_widths), 4), 255, dtype=np.uint8
    )
    for i, tile in enumerate(tiles):
        r, c = divmod(i, ncols)
        y = title_h + sum(row_heights[:r])
        x = sum(col_widths[:c])
        canvas[y : y + tile.shape[0], x : x + tile.shape[1]] = tile
    if suptitle:
        from xy import kernels

        cmd = _raster._Cmd(scale)
        cmd.text(canvas.shape[1] / (2 * scale), 17, 1, 14, (38, 38, 38, 255), suptitle)
        overlay = kernels.rasterize(bytes(cmd.buf), canvas.shape[1], title_h)
        alpha = overlay[:, :, 3:4].astype(np.float64) / 255.0
        canvas[:title_h, :, :3] = np.round(
            overlay[:, :, :3] * alpha + canvas[:title_h, :, :3] * (1.0 - alpha)
        ).astype(np.uint8)
    if colorbar:
        from xy._svg import _lut

        x0, x1 = int(canvas.shape[1] * 0.15), int(canvas.shape[1] * 0.85)
        y0 = title_h + sum(row_heights) + 12
        gradient = _lut(
            colorbar.get("colormap", "viridis"), np.linspace(0.0, 1.0, max(2, x1 - x0))
        )
        canvas[y0 : y0 + 16, x0:x1, :3] = gradient[None, :, :]
        canvas[y0 : y0 + 16, x0:x1, 3] = 255
    return _png.encode(canvas)
