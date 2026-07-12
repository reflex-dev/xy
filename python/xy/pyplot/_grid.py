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
import warnings
from typing import Any, Optional

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


def stitch_png(charts: list[Any], nrows: int, ncols: int, suptitle: Optional[str]) -> bytes:
    from xy import _png, _raster  # sanctioned escape hatch (see module doc)

    if suptitle:
        warnings.warn(
            "suptitle is not drawn in stitched multi-panel PNGs yet; "
            "use savefig('...html') to keep it",
            stacklevel=3,
        )
    scale = 2.0
    tiles: list[np.ndarray] = []
    for chart in charts:
        fig = chart.figure()
        spec, blob, borrowed = fig._build_raster_payload(px_width=max(256, int(fig.width)))
        img = _raster.render_raster(spec, blob, scale, borrowed=borrowed)
        if isinstance(img, bytes):
            raise RuntimeError("pyplot grid rasterizer unexpectedly returned encoded PNG bytes")
        tiles.append(img)
    if not tiles:
        raise ValueError("figure has no axes to save")

    tile_h = max(t.shape[0] for t in tiles)
    tile_w = max(t.shape[1] for t in tiles)
    canvas = np.full((tile_h * nrows, tile_w * ncols, 4), 255, dtype=np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, ncols)
        canvas[r * tile_h : r * tile_h + tile.shape[0], c * tile_w : c * tile_w + tile.shape[1]] = (
            tile
        )
    return _png.encode(canvas)
