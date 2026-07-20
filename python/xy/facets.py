"""Small-multiple composition built from independent screen-bounded figures.

Facets deliberately use one Figure per panel instead of duplicating a second
axis/LOD model inside the WebGL client. Each panel keeps the existing payload
contract, native aggregation, and context governor behavior. The wrapper only
owns grid layout and shared-domain coordination.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Optional

import numpy as np

from . import channels, export
from ._png import encode as encode_png
from ._png import png_truecolor
from ._raster import render_raster


def _subset_data(data: Any, mask: np.ndarray, n: int) -> Any:
    """Row-subset a table for one facet panel.

    Only 1-D columns of exactly `n` rows are masked; scalars and short config
    values pass through untouched. Multi-dimensional columns whose first axis
    happens to equal `n` are ambiguous (row-masking would corrupt e.g. a
    heatmap z matrix), so they raise instead of silently guessing.
    """
    if hasattr(data, "iloc"):
        return data.iloc[mask] if len(data) == n else data
    if isinstance(data, Mapping):
        out: dict[Any, Any] = {}
        for key, value in data.items():
            if hasattr(value, "to_numpy"):
                arr = value.to_numpy()
            elif isinstance(value, np.ndarray):
                arr = value
            elif isinstance(value, (list, tuple)):
                try:
                    arr = np.asarray(value)
                except ValueError as exc:
                    raise ValueError(
                        f"facet data column {key!r} is ragged and cannot be row-subset"
                    ) from exc
            else:
                out[key] = value  # scalar/config value, not row data
                continue
            if arr.ndim == 1 and len(arr) == n:
                out[key] = arr[mask]
            elif arr.ndim >= 2 and arr.shape[0] == n:
                raise ValueError(
                    f"facet data column {key!r} is {arr.ndim}-D with first axis {n}; "
                    "faceting cannot row-subset multi-dimensional columns"
                )
            else:
                out[key] = value
        return out
    raise TypeError("facet data must be a mapping or a pandas-like table")


def _label_codes(labels: Sequence[str]) -> tuple[np.ndarray, list[str]]:
    """Dedupe display labels in first-seen order; codes index the dedup list."""
    unique: list[str] = []
    lookup: dict[str, int] = {}
    codes = np.empty(len(labels), dtype=np.intp)
    for i, label in enumerate(labels):
        code = lookup.get(label)
        if code is None:
            code = len(unique)
            lookup[label] = code
            unique.append(label)
        codes[i] = code
    return codes, unique


def _facet_values(data: Any, by: Any) -> tuple[np.ndarray, list[str]]:
    """Factorize the facet column into per-row codes + first-seen labels.

    One `np.unique` pass instead of a per-label O(k·n) rescan; object columns
    (mixed/unsortable values) fall back to a single Python pass. Rows group by
    their `category_label` display string, matching categorical channels.
    """
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
            raise TypeError("facet_chart by= as a string requires mapping/table data")
    else:
        raw = by
    if hasattr(raw, "to_numpy"):
        raw = raw.to_numpy()
    arr = np.asarray(raw)
    if arr.ndim != 1:
        raise ValueError("facet_chart by= must resolve to a 1-D column")
    if arr.dtype == object:
        return _label_codes([channels.category_label(value) for value in arr])
    uniques, inverse = np.unique(arr, return_inverse=True)
    # np.unique sorts; recover first-seen order to preserve panel ordering.
    first = np.full(len(uniques), len(arr), dtype=np.intp)
    np.minimum.at(first, inverse, np.arange(len(arr), dtype=np.intp))
    order = np.argsort(first, kind="stable")
    remap = np.empty(len(uniques), dtype=np.intp)
    remap[order] = np.arange(len(uniques), dtype=np.intp)
    codes = remap[inverse]
    label_codes, labels = _label_codes([channels.category_label(value) for value in uniques[order]])
    if len(labels) != len(uniques):  # distinct raw values sharing a display label
        codes = label_codes[codes]
    return codes, labels


class FacetGrid:
    """A rendered grid of independent xy figures."""

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
        """Number of grid rows implied by the panel count and ``cols``."""
        return (len(self.figures) + self.cols - 1) // self.cols

    @property
    def panel_width(self) -> int:
        """Width of one panel in pixels (grid width split across columns)."""
        return max(120, (self.width - (self.cols - 1) * self.gap) // self.cols)

    @property
    def panel_height(self) -> int:
        """Height of one panel in pixels."""
        return self.height

    # Grid-level title strip height, shared by the HTML/SVG composers and the
    # chromium PNG viewport math (panel titles carry the facet labels).
    _TITLE_H = 24

    @property
    def _title_height(self) -> int:
        return self._TITLE_H if self.title else 0

    @property
    def grid_height(self) -> int:
        """Total composed height: panels + gaps + the grid title strip."""
        return self.rows * self.panel_height + max(0, self.rows - 1) * self.gap

    def to_html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
    ) -> str:
        """A self-contained HTML document laying the panels out as a grid.

        Writes it to ``path`` when given; returns the HTML either way.
        """
        panels: list[str] = []
        for i, fig in enumerate(self.figures):
            spec, blob = fig.build_payload(px_width=self.panel_width)
            panels.append(
                "{" + f'"id":"xy-facet-{i}",'
                f'"spec":{export._json_for_inline_script(spec)},'
                f'"chunks":{export._json_for_inline_script(export._base64_chunks(blob))},'
                f'"n":{len(blob)}' + "}"
            )
        js = export._javascript_for_inline_script(export._bundled_js("standalone"))
        title = export._html.escape(self.title or "xy facets")
        # Grid title rendered once here; each panel's own chart title is its
        # facet label, so labels are not duplicated in a separate strip.
        heading = (
            f'<div class="xy-facet-title">{export._html.escape(self.title)}</div>'
            if self.title
            else ""
        )
        css = export._custom_css_block(custom_css)
        doc = f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{export._STANDALONE_CSP}">
<title>{title}</title>
<style>
html,body{{margin:0;width:100%;min-height:100%;font-family:system-ui,sans-serif;background:#fff;}}
.xy-facet-title{{height:{self._TITLE_H}px;line-height:{self._TITLE_H}px;font:600 14px system-ui,sans-serif;margin:0;text-align:center;color:#1e293b;}}
.xy-facet-grid{{display:grid;grid-template-columns:repeat({self.cols}, minmax(0, 1fr));gap:{self.gap}px;}}
.xy-facet-panel{{min-width:0;}}
</style>
{css}</head><body>
{heading}<div class="xy-facet-grid" id="xy-facet-grid"></div>
<script>{js}</script>
<script>
{export._DECODE_B64_JS}
const panels=[{",".join(panels)}];
const grid=document.getElementById("xy-facet-grid");
for(const p of panels){{
  const panel=document.createElement("div"); panel.className="xy-facet-panel";
  const host=document.createElement("div"); host.id=p.id; panel.append(host); grid.appendChild(panel);
  const buf=xyDecodeB64(p.chunks,p.n); xy.renderStandalone(host,p.spec,buf);
}}
</script></body></html>"""
        if path is not None:
            export._atomic_write_text(path, doc)
        return doc

    def to_svg(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        background: Optional[str] = None,
    ) -> str:
        """Compose panel SVGs into one nested-SVG document."""
        from . import _svg

        # Per-panel id prefixes keep clipPath/gradient ids unique in the
        # composed document; each panel's title is its facet label, and the
        # grid title is drawn exactly once below.
        panel_svgs = [_svg.to_svg(fig, id_prefix=f"xy{i}-") for i, fig in enumerate(self.figures)]
        total_h = self.grid_height + self._title_height
        body: list[str] = []
        for i, svg in enumerate(panel_svgs):
            row, col = divmod(i, self.cols)
            x = col * (self.panel_width + self.gap)
            y = row * (self.panel_height + self.gap) + self._title_height
            inner = svg[svg.find(">") + 1 : svg.rfind("</svg>")]
            body.append(
                f'<svg x="{x}" y="{y}" width="{self.panel_width}" height="{self.panel_height}" '
                f'viewBox="0 0 {self.panel_width} {self.panel_height}">{inner}</svg>'
            )
        backdrop = (
            f'<rect width="{self.width}" height="{total_h}" fill="{export._html.escape(background)}"/>'
            if background and background not in ("transparent", "none")
            else ""
        )
        title = (
            f'<text x="{self.width / 2:g}" y="16" text-anchor="middle" font-size="14">{export._html.escape(self.title)}</text>'
            if self.title
            else ""
        )
        doc = f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{total_h}" viewBox="0 0 {self.width} {total_h}">{backdrop}{title}{"".join(body)}</svg>'
        if path is not None:
            export._atomic_write_text(path, doc)
        return doc

    def _compose_rgba(self, scale: float, background: Optional[str] = None) -> np.ndarray:
        """Native panel renders composed into one grid RGBA canvas.

        The shared pixel source for the raster formats. No grid title strip:
        the native rasterizer has no free-standing text path, so the composed
        canvas is exactly panels + gaps."""
        from . import _raster

        if scale <= 0 or not np.isfinite(scale):
            raise ValueError("facet export scale must be finite and positive")
        panel_images: list[np.ndarray] = []
        for fig in self.figures:
            spec, blob, borrowed = _raster._export_payload(fig, None, None, background)
            image = render_raster(spec, blob, scale=scale, borrowed=borrowed)
            if isinstance(image, bytes):
                raise RuntimeError("facet rasterizer unexpectedly returned encoded PNG bytes")
            panel_images.append(image)
        panel_h, panel_w = panel_images[0].shape[:2]
        width = int(round(self.width * scale))
        height = int(round(self.grid_height * scale))
        gap_fill = (255, 255, 255, 255) if background is None else _raster._parse_color(background)
        canvas = np.empty((height, width, 4), dtype=np.uint8)
        canvas[:] = np.asarray(gap_fill, dtype=np.uint8)
        for i, image in enumerate(panel_images):
            row, col = divmod(i, self.cols)
            x = int(round(col * (self.panel_width + self.gap) * scale))
            y = int(round(row * (self.panel_height + self.gap) * scale))
            h, w = min(panel_h, height - y), min(panel_w, width - x)
            if h > 0 and w > 0:
                canvas[y : y + h, x : x + w] = image[:h, :w]
        return canvas

    def to_png(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        scale: float = 2.0,
        engine: export.Engine = export.Engine.default,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """A PNG render of the composed grid, returned as bytes.

        ``scale`` multiplies the pixel density; ``engine`` picks the
        raster path (native or headless Chromium). Written to ``path``
        when given.
        """
        optimize = export._bool_option(optimize, "facet PNG optimize")
        resolved_engine = export._png_engine(engine, "facet PNG")
        if resolved_engine == "browser":
            data = export.html_to_png(
                self.to_html(custom_css=custom_css),
                self.width,
                # Match the actual HTML height: panels + gaps + title strip.
                self.grid_height + self._title_height,
                scale=scale,
                sandbox=sandbox,
                gl=gl,
            )
        elif resolved_engine == "native":
            if custom_css is not None:
                raise ValueError("custom_css requires engine=Engine.chromium")
            canvas = self._compose_rgba(scale)
            data = (
                encode_png(canvas)
                if optimize
                else png_truecolor(
                    canvas.shape[1],
                    canvas.shape[0],
                    np.ascontiguousarray(canvas).tobytes(),
                    compression_level=1,
                )
            )
        else:  # `_png_engine` returns only these two internal values.
            raise AssertionError(f"unreachable PNG engine {resolved_engine!r}")
        if path is not None:
            Path(path).write_bytes(data)
        return data

    def to_image(
        self,
        format: str = "png",
        *,
        scale: float = 2.0,
        background: Optional[str] = None,
        engine: "export.Engine | str" = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Unified static export of the composed grid (same matrix as single
        charts): PNG/JPEG/WebP/SVG/PDF bytes.

        The grid's pixel geometry is fixed by its panels, so there are no
        width/height overrides here; `scale` still multiplies raster density.
        Native raster output composes the browser-free panel renders (no grid
        title strip — the native rasterizer has no free-standing text path);
        SVG/PDF compose the vector panels, title included. Engine, quality,
        and background policies match `export.to_image`."""
        fmt = export._normalize_format(format)
        resolved_engine = export._resolve_image_engine(engine, fmt, custom_css)
        quality = export._validated_quality(quality, fmt, resolved_engine)
        background = export._validated_background(background, fmt)
        scale = export._positive_finite_float(scale, "export scale")
        optimize = export._bool_option(optimize, "export optimize")
        sandbox = export._bool_option(sandbox, "export sandbox")
        gl = export._gl_option(gl)
        if resolved_engine == "native":
            if fmt == "svg":
                return self.to_svg(background=background).encode("utf-8")
            if fmt == "pdf":
                from . import _pdf

                return _pdf.svg_to_pdf(self.to_svg(background=background))
            if fmt == "png":
                if background is None:
                    return self.to_png(scale=scale, optimize=optimize)
                canvas = self._compose_rgba(scale, background)
                if optimize:
                    return encode_png(canvas)
                return png_truecolor(
                    canvas.shape[1],
                    canvas.shape[0],
                    np.ascontiguousarray(canvas).tobytes(),
                    compression_level=1,
                )
            canvas = self._compose_rgba(scale, background)
            if fmt == "jpeg":
                from . import _jpeg

                return _jpeg.encode(export._flatten_alpha(canvas), quality=quality or 90)
            from . import _webp

            return _webp.encode(canvas)
        doc = self.to_html(custom_css=custom_css)
        total_h = self.grid_height + self._title_height
        with export._browser_session(gl=gl, sandbox=sandbox) as session:
            if fmt == "pdf":
                return session.render_pdf(doc, self.width, total_h)
            return session.render_image(
                doc,
                self.width,
                total_h,
                format=fmt,
                scale=scale,
                quality=quality,
                transparent=background == "transparent",
            )

    def write_image(
        self,
        path: str | PathLike[str],
        *,
        format: Optional[str] = None,
        scale: float = 2.0,
        background: Optional[str] = None,
        engine: "export.Engine | str" = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Atomic file export with extension-inferred format; ".html" routes
        to `to_html`. Options match `to_image`."""
        fmt = (
            export._normalize_format(format, allow_html=True)
            if format is not None
            else export._infer_format(path)
        )
        if fmt == "html":
            return self.to_html(path, custom_css=custom_css).encode("utf-8")
        data = self.to_image(
            fmt,
            scale=scale,
            background=background,
            engine=engine,
            quality=quality,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )
        export._atomic_write_bytes(path, data)
        return data

    def widget(self) -> list[Any]:
        """Live notebook widgets, one per facet panel."""
        from .widget import FigureWidget

        return [FigureWidget(fig) for fig in self.figures]

    def show(self) -> list[Any]:
        """Display the facet grid: returns the panel widgets."""
        return self.widget()

    def memory_report(self) -> dict[str, Any]:
        """Aggregated data/cache buffer accounting across all panels."""
        reports = [fig.memory_report() for fig in self.figures]
        return {
            "panels": len(reports),
            "transport_bytes_first_paint": sum(r["transport_bytes_first_paint"] for r in reports),
            "store_bytes": sum(r["store_bytes"] for r in reports),
            "backend": "native",
        }
