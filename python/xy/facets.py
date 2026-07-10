"""Small-multiple composition built from independent screen-bounded figures.

Facets deliberately use one Figure per panel instead of duplicating a second
axis/LOD model inside the WebGL client. Each panel keeps the existing payload
contract, native aggregation, and context governor behavior. The wrapper only
owns grid layout and shared-domain coordination.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Optional

import numpy as np

from . import channels, export
from ._png import encode as encode_png
from ._raster import render_raster


def _subset_data(data: Any, mask: np.ndarray, n: int) -> Any:
    if hasattr(data, "iloc"):
        return data.iloc[mask]
    if isinstance(data, Mapping):
        out: dict[Any, Any] = {}
        for key, value in data.items():
            try:
                arr = np.asarray(value)
            except Exception:
                out[key] = value
                continue
            out[key] = arr[mask] if arr.ndim > 0 and len(arr) == n else value
        return out
    raise TypeError("facet data must be a mapping or a pandas-like table")


def _facet_values(data: Any, by: Any) -> tuple[np.ndarray, list[str]]:
    if isinstance(by, str):
        if isinstance(data, Mapping):
            if by not in data:
                raise KeyError(f"facet column {by!r} not found in data")
            raw = data[by]
        elif hasattr(data, "__getitem__"):
            try:
                raw = data[by]
            except Exception as exc:
                raise KeyError(f"facet column {by!r} not found in data") from exc
        else:
            raise TypeError("facet_by as a string requires mapping/table data")
    else:
        raw = by
    if hasattr(raw, "to_numpy"):
        raw = raw.to_numpy()
    arr = np.asarray(raw, dtype=object)
    if arr.ndim != 1:
        raise ValueError("facet_by must resolve to a 1-D column")
    labels = [channels.category_label(value) for value in arr]
    return arr, labels


class FacetGrid:
    """A rendered grid of independent fastcharts figures."""

    def __init__(
        self,
        figures: Sequence[Any],
        labels: Sequence[str],
        *,
        cols: int,
        width: int,
        height: int,
        gap: int = 12,
        title: Optional[str] = None,
    ) -> None:
        if len(figures) != len(labels) or not figures:
            raise ValueError("FacetGrid needs one label per non-empty panel")
        self.figures = tuple(figures)
        self.labels = tuple(labels)
        self.cols = int(cols)
        self.width = int(width)
        self.height = int(height)
        self.gap = int(gap)
        self.title = title

    @property
    def rows(self) -> int:
        return (len(self.figures) + self.cols - 1) // self.cols

    @property
    def panel_width(self) -> int:
        return max(120, (self.width - (self.cols - 1) * self.gap) // self.cols)

    @property
    def panel_height(self) -> int:
        return self.height

    def to_html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
    ) -> str:
        panels: list[str] = []
        for i, (fig, label) in enumerate(zip(self.figures, self.labels, strict=True)):
            spec, blob = fig.build_payload(px_width=self.panel_width)
            panels.append(
                "{" + f'"id":"fc-facet-{i}","label":{export._json_for_inline_script(label)},'
                f'"spec":{export._json_for_inline_script(spec)},'
                f'"b64":"{base64.b64encode(blob).decode("ascii")}"' + "}"
            )
        js = export._javascript_for_inline_script(export._bundled_js("standalone"))
        title = export._html.escape(self.title or "fastcharts facets")
        css = export._custom_css_block(custom_css)
        doc = f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{export._STANDALONE_CSP}">
<title>{title}</title>
<style>
html,body{{margin:0;width:100%;min-height:100%;font-family:system-ui,sans-serif;background:#fff;}}
.fastcharts-facet-grid{{display:grid;grid-template-columns:repeat({self.cols}, minmax(0, 1fr));gap:{self.gap}px;}}
.fastcharts-facet-panel{{min-width:0;}}
.fastcharts-facet-label{{font:600 12px system-ui,sans-serif;margin:0 0 2px 4px;color:#334155;}}
</style>
{css}</head><body>
<div class="fastcharts-facet-grid" id="fastcharts-facet-grid"></div>
<script>{js}</script>
<script>
const panels=[{",".join(panels)}];
const grid=document.getElementById("fastcharts-facet-grid");
for(const p of panels){{
  const panel=document.createElement("div"); panel.className="fastcharts-facet-panel";
  const label=document.createElement("div"); label.className="fastcharts-facet-label"; label.textContent=p.label;
  const host=document.createElement("div"); host.id=p.id; panel.append(label,host); grid.appendChild(panel);
  const bytes=Uint8Array.from(atob(p.b64),c=>c.charCodeAt(0)); fastcharts.renderStandalone(host,p.spec,bytes.buffer);
}}
</script></body></html>"""
        if path is not None:
            export._atomic_write_text(path, doc)
        return doc

    def to_svg(self, path: Optional[str | PathLike[str]] = None) -> str:
        """Compose panel SVGs into one nested-SVG document."""
        panel_svgs = [fig.to_svg() for fig in self.figures]
        total_h = self.rows * self.panel_height + max(0, self.rows - 1) * self.gap
        if self.title:
            total_h += 24
        body: list[str] = []
        for i, svg in enumerate(panel_svgs):
            row, col = divmod(i, self.cols)
            x = col * (self.panel_width + self.gap)
            y = row * (self.panel_height + self.gap) + (24 if self.title else 0)
            inner = svg[svg.find(">") + 1 : svg.rfind("</svg>")]
            body.append(
                f'<svg x="{x}" y="{y}" width="{self.panel_width}" height="{self.panel_height}" '
                f'viewBox="0 0 {self.panel_width} {self.panel_height}">{inner}</svg>'
            )
        title = (
            f'<text x="{self.width / 2:g}" y="16" text-anchor="middle" font-size="14">{export._html.escape(self.title)}</text>'
            if self.title
            else ""
        )
        doc = f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{total_h}" viewBox="0 0 {self.width} {total_h}">{title}{"".join(body)}</svg>'
        if path is not None:
            export._atomic_write_text(path, doc)
        return doc

    def to_png(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        scale: float = 1.0,
        engine: str = "native",
        chromium: Optional[str] = None,
        sandbox: bool = True,
    ) -> bytes:
        if engine == "chromium":
            data = export.html_to_png(
                self.to_html(),
                self.width,
                self.rows * self.panel_height + (self.rows - 1) * self.gap,
                scale=scale,
                chromium=chromium,
                sandbox=sandbox,
            )
        elif engine == "native":
            if scale <= 0 or not np.isfinite(scale):
                raise ValueError("facet PNG scale must be finite and positive")
            panel_images = [
                render_raster(*fig.build_payload(), scale=scale) for fig in self.figures
            ]
            panel_h, panel_w = panel_images[0].shape[:2]
            width = int(round(self.width * scale))
            height = int(
                round((self.rows * self.panel_height + max(0, self.rows - 1) * self.gap) * scale)
            )
            canvas = np.full((height, width, 4), 255, dtype=np.uint8)
            for i, image in enumerate(panel_images):
                row, col = divmod(i, self.cols)
                x = int(round(col * (self.panel_width + self.gap) * scale))
                y = int(round(row * (self.panel_height + self.gap) * scale))
                h, w = min(panel_h, height - y), min(panel_w, width - x)
                if h > 0 and w > 0:
                    canvas[y : y + h, x : x + w] = image[:h, :w]
            data = encode_png(canvas)
        else:
            raise ValueError("facet PNG engine must be 'native' or 'chromium'")
        if path is not None:
            Path(path).write_bytes(data)
        return data

    def widget(self) -> list[Any]:
        from .widget import FigureWidget

        return [FigureWidget(fig) for fig in self.figures]

    def show(self) -> list[Any]:
        return self.widget()

    def memory_report(self) -> dict[str, Any]:
        reports = [fig.memory_report() for fig in self.figures]
        return {
            "panels": len(reports),
            "transport_bytes_first_paint": sum(r["transport_bytes_first_paint"] for r in reports),
            "store_bytes": sum(r["store_bytes"] for r in reports),
            "backend": "native",
        }
