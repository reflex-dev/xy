"""Engine-neutral geometry producers shared by the raster PNG path.

The SVG exporter (`_svg.py`) bakes coordinates into SVG `d`/arc/`<image>` strings
that its string-marker tests pin, so it stays the home of the pure math
(`_Scale`, `_column`, `_lut`, tick functions, `_monotone_tangents`,
`_corner_radii`, …). This module reuses those and adds the *tessellated* forms
the Rust rasterizer needs — polylines instead of Bézier `d` strings, corner
polygons instead of arcs, and RGBA grid arrays instead of embedded `<image>`
PNGs — so `_raster.py` paints the exact same geometry the SVG shows.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._svg import _column, _lut, _monotone_tangents

# Samples per smooth Bézier span when flattening to a polyline for the raster
# filler. The curve is screen-bounded (M4-decimated), so this stays cheap and
# is visually indistinguishable from the SVG's true cubics.
_BEZIER_STEPS = 16


def curve_points(xv: np.ndarray, yv: np.ndarray, sx: Any, sy: Any, smooth: bool) -> np.ndarray:
    """Pixel-space polyline for a series. Smooth flattens the monotone-cubic
    Hermite (the same tangents `_svg._curve_path` emits as Béziers) into short
    line segments; else it's the mapped polyline."""
    px = np.asarray(sx(xv), dtype=np.float64)
    py = np.asarray(sy(yv), dtype=np.float64)
    if not smooth or len(xv) < 3 or not (sx.affine and sy.affine):
        return np.column_stack([px, py])
    m = _monotone_tangents(np.asarray(xv, float), np.asarray(yv, float))
    ts = np.linspace(0.0, 1.0, _BEZIER_STEPS, endpoint=False)
    out = [(px[0], py[0])]
    for i in range(len(xv) - 1):
        h = xv[i + 1] - xv[i]
        if h <= 0:
            out.append((px[i + 1], py[i + 1]))
            continue
        # Hermite → cubic Bézier control points in data space, then map (affine).
        p0 = (xv[i], yv[i])
        p3 = (xv[i + 1], yv[i + 1])
        c1 = (xv[i] + h / 3.0, yv[i] + m[i] * h / 3.0)
        c2 = (xv[i + 1] - h / 3.0, yv[i + 1] - m[i + 1] * h / 3.0)
        for t in ts[1:]:
            u = 1.0 - t
            bx = u**3 * p0[0] + 3 * u**2 * t * c1[0] + 3 * u * t**2 * c2[0] + t**3 * p3[0]
            by = u**3 * p0[1] + 3 * u**2 * t * c1[1] + 3 * u * t**2 * c2[1] + t**3 * p3[1]
            out.append((float(sx(bx)), float(sy(by))))
        out.append((px[i + 1], py[i + 1]))
    return np.asarray(out, dtype=np.float64)


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, steps: int = 5) -> list:
    if r <= 0:
        return [(cx, cy)]
    return [(cx + r * np.cos(a), cy + r * np.sin(a)) for a in np.linspace(a0, a1, steps)]


def rounded_rect_poly(
    x: float, y: float, w: float, h: float, r_tip: float, r_base: float, tip_top: bool
) -> list:
    """Outline polygon (CW) for a rect with independent tip/base corner radii —
    the raster tessellation of `_svg._rounded_rect_path`. `tip_top` puts the
    value end (tip radius) on the top edge."""
    rt = max(0.0, min(r_tip, w / 2, h / 2))
    rb = max(0.0, min(r_base, w / 2, h / 2))
    top_r, bot_r = (rt, rb) if tip_top else (rb, rt)
    pts: list = []
    pts += _arc(x + top_r, y + top_r, top_r, np.pi, 1.5 * np.pi)  # top-left
    pts += _arc(x + w - top_r, y + top_r, top_r, 1.5 * np.pi, 2 * np.pi)  # top-right
    pts += _arc(x + w - bot_r, y + h - bot_r, bot_r, 0.0, 0.5 * np.pi)  # bottom-right
    pts += _arc(x + bot_r, y + h - bot_r, bot_r, 0.5 * np.pi, np.pi)  # bottom-left
    return pts


def grid_rgba(kind: str, g: dict, blob: bytes, cols: list, style: dict) -> tuple:
    """Density/heatmap grid → `(h, w, 4)` uint8 RGBA (top row first), matching
    `_svg._density_image`/`_heatmap_image`. Returns (rgba, x_range, y_range)."""
    w, h = int(g["w"]), int(g["h"])
    if kind == "density":
        grid = _column(blob, cols[g["buf"]]).reshape(h, w)
        gmax = float(g.get("max") or 1.0) or 1.0
        tnorm = np.clip(grid / gmax, 0.0, 1.0)
        rgb = _lut(g.get("colormap", "viridis"), tnorm.reshape(-1)).reshape(h, w, 3)
        alpha = (np.clip(tnorm * 1.35, 0, 1) * 255 * float(style.get("opacity", 0.85))).astype(
            np.uint8
        )
        alpha[tnorm <= 0] = 0
    else:  # heatmap
        raw = _column(blob, cols[g["buf"]]).reshape(h, w)
        t = np.clip((raw * 255.0 - 1.0) / 254.0, 0.0, 1.0)
        rgb = _lut(g.get("colormap", "viridis"), t.reshape(-1)).reshape(h, w, 3)
        alpha = np.full((h, w), int(255 * float(style.get("opacity", 0.95))), dtype=np.uint8)
        alpha[raw <= 0] = 0
    rgba = np.dstack([rgb, alpha])[::-1]  # flip: row 0 is the top of the image
    return np.ascontiguousarray(rgba, dtype=np.uint8), g["x_range"], g["y_range"]


def grid_dest_rect(x_range: list, y_range: list, sx: Any, sy: Any) -> tuple:
    """Pixel destination rect (x, y, w, h) for a grid image, matching
    `_svg._grid_image`."""
    px0, px1 = float(sx(x_range[0])), float(sx(x_range[1]))
    py0, py1 = float(sy(y_range[1])), float(sy(y_range[0]))
    return min(px0, px1), min(py0, py1), abs(px1 - px0), abs(py1 - py0)
