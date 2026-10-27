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

from ._svg import _column, _density_column, _lut, _monotone_tangents

# Samples per smooth Bézier span when flattening to a polyline for the raster
# filler. The curve is screen-bounded (M4-decimated), so this stays cheap and
# is visually indistinguishable from the SVG's true cubics.
_BEZIER_STEPS = 16

# Segments per ribbon edge. Fixed rather than view-adaptive: a flow diagram has
# tens of links, so the ceiling is free, and a view-dependent count would have
# to be recorded per §28 rather than chosen silently. The client sweeps the same
# count so the live chart and the exports flatten identically. This resolution
# keeps chord error below a visible pixel on wide, high-contrast diagrams.
RIBBON_STEPS = 96


def ribbon_edge(
    x0: float, x1: float, ya: float, yb: float, steps: int = RIBBON_STEPS
) -> np.ndarray:
    """One edge of a flow band, in the caller's coordinate space.

    The cubic of the ribbon contract: both control points sit at the horizontal
    midpoint and hold their own end's y, so the edge leaves and arrives
    horizontally (d3's `curveBumpX`). The function is pure arithmetic with no
    opinion about units — but the contract makes the curve normative in
    **axis-transformed space**, so exporters pass mapped endpoints rather than
    mapping the flattened result (the two orders differ on log/symlog axes).
    Returned flattened because the raster display list has no curve opcode; the
    SVG exporter rebuilds the exact `C` from the same four numbers.
    """
    t = np.linspace(0.0, 1.0, steps + 1)
    u = 1.0 - t
    mid = (x0 + x1) / 2.0
    xs = u**3 * x0 + 3 * u**2 * t * mid + 3 * u * t**2 * mid + t**3 * x1
    ys = u**3 * ya + 3 * u**2 * t * ya + 3 * u * t**2 * yb + t**3 * yb
    return np.column_stack([xs, ys])


def ribbon_polygon(
    x0: float,
    x1: float,
    src_lo: float,
    src_hi: float,
    dst_lo: float,
    dst_hi: float,
    steps: int = RIBBON_STEPS,
) -> np.ndarray:
    """A whole flow band as one closed polygon, in the caller's space.

    One polygon, not two triangles or a mesh: the seam-free fill paths in both
    exporters require a single uniform-alpha shape, and a gradient across a
    triangle mesh is impossible anyway (the contract explains why). This is the
    single reference both static exporters and the golden geometry test consume,
    so SVG and PNG cannot drift from each other.
    """
    upper = ribbon_edge(x0, x1, src_hi, dst_hi, steps)
    lower = ribbon_edge(x0, x1, src_lo, dst_lo, steps)
    return np.vstack([upper, lower[::-1]])


def funnel_quad(
    pos0: float,
    pos1: float,
    lo0: float,
    hi0: float,
    lo1: float,
    hi1: float,
    horizontal: bool,
) -> np.ndarray:
    """One funnel segment as a closed 4-corner polygon, in the caller's space.

    `pos` runs along the stage axis, `lo/hi` are the cross-axis edges at each
    end; `horizontal` maps pos→x/cross→y and vertical the transpose. Corners
    run A=(lo0@pos0) B=(hi0@pos0) C=(hi1@pos1) D=(lo1@pos1) as a closed
    polygon. The client covers the same quad with a 4-vertex TRIANGLE_STRIP
    in the order A, B, D, C — `FUNNEL_VS` takes `t = floor(id/2)` and
    `side = id & 1` — so its two triangles are ABD and BDC. A different
    tessellation of one identical quad, which is exactly why this POLYGON is
    the shared reference rather than a triangle pair. Both static exporters
    and the golden geometry test consume it, so SVG and PNG cannot drift from
    each other or from the client.
    """
    if horizontal:
        corners = [(pos0, lo0), (pos0, hi0), (pos1, hi1), (pos1, lo1)]
    else:
        corners = [(lo0, pos0), (hi0, pos0), (hi1, pos1), (lo1, pos1)]
    return np.array(corners, dtype=np.float64)


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
        grid = _density_column(blob, cols[g["buf"]], g).reshape(h, w)
        gmax = float(g.get("max") or 1.0) or 1.0
        tnorm = np.clip(grid / gmax, 0.0, 1.0)
        rgb = _lut(g.get("colormap", "viridis"), tnorm.reshape(-1)).reshape(h, w, 3)
        alpha = (np.clip(tnorm * 1.35, 0, 1) * 255 * float(style.get("opacity", 0.85))).astype(
            np.uint8
        )
        alpha[tnorm <= 0] = 0
    else:  # heatmap
        raw = _column(blob, cols[g["buf"]]).reshape(h, w)
        t = np.clip(raw, 0.0, 1.0)
        rgb = _lut(g.get("colormap", "viridis"), t.reshape(-1)).reshape(h, w, 3)
        alpha = np.full((h, w), int(255 * float(style.get("opacity", 0.95))), dtype=np.uint8)
        alpha[~np.isfinite(raw)] = 0
    rgba = np.dstack([rgb, alpha])[::-1]  # flip: row 0 is the top of the image
    return np.ascontiguousarray(rgba, dtype=np.uint8), g["x_range"], g["y_range"]


def grid_dest_rect(x_range: list, y_range: list, sx: Any, sy: Any) -> tuple:
    """Pixel destination rect (x, y, w, h) for a grid image, matching
    `_svg._grid_image`."""
    px0, px1 = float(sx(x_range[0])), float(sx(x_range[1]))
    py0, py1 = float(sy(y_range[1])), float(sy(y_range[0]))
    return min(px0, px1), min(py0, py1), abs(px1 - px0), abs(py1 - py0)
