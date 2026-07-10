"""Multi-panel composition — the shim-owned replacement for an engine grid.

HTML: one self-contained document, panels in a CSS grid, each panel embedded
as a sandboxed ``srcdoc`` iframe of its own standalone chart document (same
zero-dependency offline story as `Chart.to_html`).

PNG: each panel renders through the engine's native rasterizer to an RGBA
array; NumPy pastes them onto one canvas and the engine's PNG encoder writes
the file. This module and `_mplfig.savefig` are the only places the shim
reaches past the public API (via `Chart.figure()` + the `_raster`/`_png`
modules); everything else goes through `fastcharts`' public surface.
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
        panels.append(
            f'<iframe class="fc-panel" sandbox="allow-scripts" srcdoc="{_html.escape(doc, quote=True)}"></iframe>'
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
  .fc-grid {{ display: grid; grid-template-columns: repeat({ncols}, 1fr); gap: 4px; padding: 4px; }}
  .fc-panel {{ border: 0; width: 100%; aspect-ratio: auto; min-height: 240px; }}
</style>
</head>
<body>
{title_html}
<div class="fc-grid">
{grid}
</div>
</body>
</html>"""


def stitch_png(charts: list[Any], nrows: int, ncols: int, suptitle: Optional[str]) -> bytes:
    from fastcharts import _png, _raster  # sanctioned escape hatch (see module doc)

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
        spec, blob = fig.build_payload(px_width=max(256, int(fig.width)))
        img = _raster.render_raster(spec, blob, scale)
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
