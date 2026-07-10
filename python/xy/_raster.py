"""Native PNG export: build a display-list command buffer from a chart spec and
paint it with the Rust rasterizer (`kernels.rasterize`, `src/raster.rs`), then
encode PNG. Browser-free and screen-bounded — the same decimated payload the SVG
exporter consumes.

Reuses `_svg`'s layout/scale/tick/colormap math and `_scene`'s tessellated
geometry so the raster matches the SVG (and the live chart). The one thing the
SVG path never needed — a CSS-color → RGBA8 parser — lives here, since the
browser did that resolution for the SVG/widget.
"""

from __future__ import annotations

import struct
from os import PathLike
from typing import Any, Optional

import numpy as np

from . import _png, _scene
from ._svg import (
    _AXIS,
    _GRID,
    _TEXT,
    DEFAULT_PALETTE,
    _column,
    _corner_radii,
    _css,
    _fmt_axis,
    _lut,
    _Scale,
    axis_ticks,
    layout,
)

# Opcodes — must match src/raster.rs.
_CLIP, _FILL, _GRAD, _STROKE, _POINT, _IMAGE, _TEXT_OP, _POINTS = 0, 1, 2, 3, 4, 5, 6, 7
_SYMBOLS = {"circle": 0, "square": 1, "diamond": 2, "triangle": 3, "cross": 4}


def _parse_color(css: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    """Resolve a CSS color string to RGBA8 via the native grammar
    (src/css.rs) — the same parser that validates figure input, so raster
    colors can never drift from the API contract. `none` renders transparent
    (the SVG idiom); browser-only forms that survive `_css`'s fallback (an
    `oklch()` a DOM would resolve) and — defensively — anything unparseable
    fall back to a mid gray so a static export never renders an invisible
    mark."""
    from . import kernels

    s = str(css).strip()
    if s.lower() == "none":
        return (0, 0, 0, 0)
    _status, rgba = kernels.css_check(kernels.CSS_COLOR, s)
    if rgba is None:
        rgba = (100.0 / 255.0, 100.0 / 255.0, 100.0 / 255.0, 1.0)
    r, g, b, a = rgba
    return (
        int(round(r * 255)),
        int(round(g * 255)),
        int(round(b * 255)),
        max(0, min(255, int(round(a * 255 * opacity)))),
    )


def _rgba(css: Any, fallback: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    return _parse_color(_css(css, fallback), opacity)


class _Cmd:
    """Little-endian display-list writer. All coordinates/sizes are multiplied
    by `scale` on emit so a single logical layout renders at any DPI."""

    def __init__(self, scale: float) -> None:
        self.buf = bytearray()
        self.s = scale

    def _f(self, v: float) -> None:
        self.buf += struct.pack("<f", v * self.s)

    def _raw_f(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def _u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v)

    def _rgba(self, c: tuple[int, int, int, int]) -> None:
        self.buf += bytes(c)

    def clip(self, x: float, y: float, w: float, h: float) -> None:
        self.buf.append(_CLIP)
        self._f(x)
        self._f(y)
        self._f(w)
        self._f(h)

    def fill(self, pts, color) -> None:
        if len(pts) < 3:
            return
        self.buf.append(_FILL)
        self._u32(len(pts))
        for x, y in pts:
            self._f(x)
            self._f(y)
        self._rgba(color)

    def grad(self, pts, g0, g1, stops) -> None:
        if len(pts) < 3 or not stops:
            return
        self.buf.append(_GRAD)
        self._u32(len(pts))
        for x, y in pts:
            self._f(x)
            self._f(y)
        self._f(g0[0])
        self._f(g0[1])
        self._f(g1[0])
        self._f(g1[1])
        self._u32(len(stops))
        for off, col in stops:
            self._raw_f(off)
            self._rgba(col)

    def stroke(self, pts, width, color, closed=False, dash=None) -> None:
        if len(pts) < 2 or width <= 0:
            return
        self.buf.append(_STROKE)
        self._u32(len(pts))
        for x, y in pts:
            self._f(x)
            self._f(y)
        self._f(width)
        self._rgba(color)
        self.buf.append(1 if closed else 0)
        dash = dash or []
        self._u32(len(dash))
        for d in dash:
            self._f(d)

    def point(self, cx, cy, r, symbol, fill, sw, stroke) -> None:
        self.buf.append(_POINT)
        self._f(cx)
        self._f(cy)
        self._f(r)
        self.buf.append(symbol)
        self._rgba(fill)
        self._f(sw)
        self._rgba(stroke)

    def points(self, cx, cy, r, fills, symbol, sw, stroke) -> None:
        """Batched marks, struct-of-arrays: whole NumPy columns are packed in
        one shot (`cx`/`cy`/`r` arrays, `fills` as `(n, 4)` RGBA8) and the
        native side loops — pixel-identical to per-mark `point()` calls,
        without the per-point Python byte-packing that dominated PNG export."""
        n = len(cx)
        if n == 0:
            return
        self.buf.append(_POINTS)
        self._u32(n)
        self.buf.append(symbol)
        self._f(sw)
        self._rgba(stroke)
        for arr in (cx, cy, r):
            scaled = np.asarray(arr, dtype=np.float64) * self.s
            self.buf += scaled.astype("<f4").tobytes()
        self.buf += np.ascontiguousarray(fills, dtype=np.uint8).tobytes()

    def image(self, dx, dy, dw, dh, iw, ih, rgba_bytes) -> None:
        self.buf.append(_IMAGE)
        self._f(dx)
        self._f(dy)
        self._f(dw)
        self._f(dh)
        self._u32(iw)
        self._u32(ih)
        self.buf += rgba_bytes

    def text(self, x, y, anchor, size, color, s) -> None:
        data = str(s).encode("ascii", "replace")
        self.buf.append(_TEXT_OP)
        self._f(x)
        self._f(y)
        self.buf.append(anchor)
        self._f(size)
        self._rgba(color)
        self._u32(len(data))
        self.buf += data


def _rect_pts(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _grad_line(space: str, direction: str, bbox, plot):
    """(g0, g1) endpoints for a linear gradient over a mark bbox (mark space) or
    the plot rect (plot space)."""
    x, y, w, h = bbox if space != "plot" else (plot["x"], plot["y"], plot["w"], plot["h"])
    cx, cy = x + w / 2, y + h / 2
    return {
        "down": ((cx, y), (cx, y + h)),
        "up": ((cx, y + h), (cx, y)),
        "right": ((x, cy), (x + w, cy)),
        "left": ((x + w, cy), (x, cy)),
    }.get(direction, ((cx, y), (cx, y + h)))


def _grad_stops(fill_spec: dict, mark_color: str) -> list:
    return [(float(o), _parse_color(_css(c, mark_color))) for o, c in fill_spec.get("stops", [])]


def render_raster(spec: dict[str, Any], blob: bytes, scale: float = 2.0) -> np.ndarray:
    """Paint `spec` into an ``(h, w, 4)`` RGBA8 image via the native rasterizer."""
    from . import kernels

    width, height, compact, plot = layout(spec)
    xa, ya = spec["x_axis"], spec["y_axis"]
    sx = _Scale(xa, plot["x"], plot["x"] + plot["w"])
    sy = _Scale(ya, plot["y"] + plot["h"], plot["y"])
    cols = spec["columns"]
    cmd = _Cmd(scale)

    # White background (matches the Chromium screenshot on a default page).
    cmd.fill(_rect_pts(0, 0, width, height), (255, 255, 255, 255))

    xt, xlab, xstep = axis_ticks(xa, plot["w"], True)
    yt, ylab, ystep = axis_ticks(ya, plot["h"], False)
    grid = _parse_color(_GRID)
    px0, py0 = plot["x"], plot["y"]
    px1, py1 = plot["x"] + plot["w"], plot["y"] + plot["h"]

    cmd.clip(px0, py0, plot["w"], plot["h"])
    for v in xt:
        gx = float(sx(v))
        cmd.stroke([(gx, py0), (gx, py1)], 1.0, grid)
    for v in yt:
        gy = float(sy(v))
        cmd.stroke([(px0, gy), (px1, gy)], 1.0, grid)

    for palette_i, t in enumerate(spec["traces"]):
        style = t.get("style") or {}
        color = _css(style.get("color"), DEFAULT_PALETTE[palette_i % len(DEFAULT_PALETTE)])
        kind = t["kind"]
        if t.get("tier") == "density" and t.get("density"):
            _emit_grid(cmd, "density", t["density"], blob, cols, sx, sy, style)
        elif kind == "line":
            _emit_line(cmd, t, blob, cols, sx, sy, style, color)
        elif kind == "area":
            _emit_area(cmd, t, blob, cols, sx, sy, style, color, plot)
        elif kind == "scatter":
            _emit_scatter(cmd, t, blob, cols, sx, sy, style, color)
        elif kind in ("bar", "column") and t.get("bar"):
            _emit_bars(cmd, t, blob, cols, sx, sy, style, color, plot)
        elif kind == "heatmap" and t.get("heatmap"):
            _emit_grid(cmd, "heatmap", t["heatmap"], blob, cols, sx, sy, style)
        elif all(k in t for k in ("x0", "x1", "y0", "y1")):
            _emit_rects(cmd, t, blob, cols, sx, sy, style, color, plot)

    # Chrome (unclipped): baselines, labels, title, legend.
    cmd.clip(0, 0, width, height)
    axis_c = _parse_color(_AXIS)
    cmd.stroke([(px0, py0), (px0, py1)], 1.0, axis_c)
    cmd.stroke([(px0, py1), (px1, py1)], 1.0, axis_c)

    text_c = _parse_color(_TEXT)
    hide_x = xa.get("tick_label_strategy") == "none"
    hide_y = ya.get("tick_label_strategy") == "none"
    if not hide_x:
        for v in xlab:
            cmd.text(float(sx(v)), py1 + 15, 1, 11, text_c, _fmt_axis(xa, v, xstep))
    if not hide_y:
        for v in ylab:
            cmd.text(px0 - 8, float(sy(v)) + 4, 2, 11, text_c, _fmt_axis(ya, v, ystep))
    if spec.get("title"):
        cmd.text(width / 2, plot["y"] - (10 if compact else 12), 1, 14, text_c, str(spec["title"]))
    if xa.get("label") and not hide_x:
        cmd.text(px0 + plot["w"] / 2, py1 + 33, 1, 12, text_c, str(xa["label"]))
    if ya.get("label") and not hide_y:
        # No text rotation in the raster; place the y-label at top-left instead.
        cmd.text(6, plot["y"] - 4, 0, 12, text_c, str(ya["label"]))

    named = [t for t in spec["traces"] if t.get("name")]
    if spec.get("show_legend", True) and named:
        _emit_legend(cmd, named, plot)

    w_px, h_px = max(1, round(width * scale)), max(1, round(height * scale))
    img = kernels.rasterize(bytes(cmd.buf), w_px, h_px)
    return img


def _emit_line(cmd, t, blob, cols, sx, sy, style, color):
    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    pts = _scene.curve_points(xv, yv, sx, sy, style.get("curve") == "smooth")
    c = _rgba(style.get("color"), color, float(style.get("opacity", 1.0)))
    cmd.stroke(pts.tolist(), float(style.get("width", 1.5)), c, dash=style.get("dash"))


def _emit_area(cmd, t, blob, cols, sx, sy, style, color, plot):
    xv = _column(blob, cols[t["x"]])
    yv = _column(blob, cols[t["y"]])
    bv = _column(blob, cols[t["base"]])
    smooth = style.get("curve") == "smooth"
    top = _scene.curve_points(xv, yv, sx, sy, smooth)
    base = _scene.curve_points(xv[::-1], bv[::-1], sx, sy, smooth)
    poly = np.vstack([top, base])
    op = float(style.get("opacity", 0.35))
    fill_spec = style.get("fill")
    if isinstance(fill_spec, dict):
        xs, ys = poly[:, 0], poly[:, 1]
        bbox = (xs.min(), ys.min(), xs.max() - xs.min(), ys.max() - ys.min())
        g0, g1 = _grad_line(
            fill_spec.get("space", "mark"), fill_spec.get("dir", "down"), bbox, plot
        )
        stops = [(o, (c[0], c[1], c[2], int(c[3] * op))) for o, c in _grad_stops(fill_spec, color)]
        cmd.grad(poly.tolist(), g0, g1, stops)
    else:
        cmd.fill(poly.tolist(), _rgba(style.get("color"), color, op))
    lw = float(style.get("line_width", 1.2))
    if lw > 0:
        lop = float(style.get("line_opacity", 1.0))
        cmd.stroke(top.tolist(), lw, _rgba(style.get("color"), color, lop), dash=style.get("dash"))


def _emit_scatter(cmd, t, blob, cols, sx, sy, style, color):
    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    px, py = sx(xv), sy(yv)
    n = len(xv)
    ch = t.get("color") or {}
    op = float(style.get("opacity", 0.8))
    fills = np.empty((n, 4), dtype=np.uint8)
    fills[:, 3] = max(0, min(255, int(round(op * 255))))
    if ch.get("mode") == "continuous":
        fills[:, :3] = _lut(ch.get("colormap", "viridis"), _column(blob, cols[ch["buf"]]))
    elif ch.get("mode") == "categorical":
        codes = _column(blob, cols[ch["buf"]]).astype(np.int64)
        pal = ch.get("palette") or DEFAULT_PALETTE
        # Resolve each palette entry once; per-point colors are a table gather.
        pal_rgb = np.array([_parse_color(c)[:3] for c in pal], dtype=np.uint8)
        fills[:, :3] = pal_rgb[codes % len(pal)]
    else:
        fills[:, :3] = _parse_color(_css(ch.get("color"), color))[:3]

    size_ch = t.get("size") or {}
    if size_ch.get("mode") == "continuous":
        sv = _column(blob, cols[size_ch["buf"]])
        r0, r1 = size_ch.get("range_px", [2, 18])
        radii = (r0 + (r1 - r0) * np.clip(sv, 0, 1)) / 2
    else:
        radii = np.full(n, float(size_ch.get("size", 4.0)) / 2)

    sw = float(style.get("stroke_width", 0.0))
    sym = _SYMBOLS.get(style.get("symbol", "circle"), 0)
    stroke = _rgba(style.get("stroke"), color) if sw > 0 else (0, 0, 0, 0)
    cmd.points(px, py, radii, fills, sym, sw, stroke)


def _bar_geom(cmd, x, y, w, h, style, fill_cmd, stroke_c, sw, tip_top):
    r_tip, r_base = _corner_radii(style)
    if r_tip or r_base:
        poly = _scene.rounded_rect_poly(x, y, w, h, r_tip, r_base, tip_top)
        fill_cmd(poly)
        if sw > 0:
            cmd.stroke(poly, sw, stroke_c, closed=True)
    else:
        poly = _rect_pts(x, y, x + w, y + h)
        fill_cmd(poly)
        if sw > 0:
            cmd.stroke(poly, sw, stroke_c, closed=True)


def _fill_maker(cmd, style, color, plot):
    """Return (fill_cmd, stroke_c, sw) closure honoring gradient/stroke style."""
    op = float(style.get("opacity", 0.85))
    sw = float(style.get("stroke_width", 0.0))
    stroke_c = _rgba(style.get("stroke"), color) if sw > 0 else (0, 0, 0, 0)
    fill_spec = style.get("fill")
    if isinstance(fill_spec, dict):
        stops = [(o, (c[0], c[1], c[2], int(c[3] * op))) for o, c in _grad_stops(fill_spec, color)]

        def fill_cmd(poly):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            g0, g1 = _grad_line(
                fill_spec.get("space", "mark"), fill_spec.get("dir", "down"), bbox, plot
            )
            cmd.grad(poly, g0, g1, stops)
    else:
        flat = _rgba(style.get("color"), color, op)

        def fill_cmd(poly):
            cmd.fill(poly, flat)

    return fill_cmd, stroke_c, sw


def _emit_bars(cmd, t, blob, cols, sx, sy, style, color, plot):
    b = t["bar"]
    pos = _column(blob, cols[b["pos"]])
    v1 = _column(blob, cols[b["value1"]])
    v0 = (
        _column(blob, cols[b["value0"]])
        if "value0" in b
        else np.full(len(pos), float(b.get("value0_const", 0.0)))
    )
    horizontal = b.get("orientation") == "horizontal"
    half = float(b["width"]) / 2
    fill_cmd, stroke_c, sw = _fill_maker(cmd, style, color, plot)
    for i in range(len(pos)):
        if horizontal:
            x0, x1 = float(sx(min(v0[i], v1[i]))), float(sx(max(v0[i], v1[i])))
            y0, y1 = float(sy(pos[i] + half)), float(sy(pos[i] - half))
            tip_top = True
        else:
            x0, x1 = float(sx(pos[i] - half)), float(sx(pos[i] + half))
            y0, y1 = float(sy(max(v0[i], v1[i]))), float(sy(min(v0[i], v1[i])))
            tip_top = v1[i] >= v0[i]
        x, y = min(x0, x1), min(y0, y1)
        _bar_geom(cmd, x, y, abs(x1 - x0), abs(y1 - y0), style, fill_cmd, stroke_c, sw, tip_top)


def _emit_rects(cmd, t, blob, cols, sx, sy, style, color, plot):
    x0v, x1v = _column(blob, cols[t["x0"]]), _column(blob, cols[t["x1"]])
    y0v, y1v = _column(blob, cols[t["y0"]]), _column(blob, cols[t["y1"]])
    fill_cmd, stroke_c, sw = _fill_maker(cmd, style, color, plot)
    for i in range(len(x0v)):
        xa_, xb = float(sx(x0v[i])), float(sx(x1v[i]))
        ya_, yb = float(sy(y0v[i])), float(sy(y1v[i]))
        x, y = min(xa_, xb), min(ya_, yb)
        _bar_geom(
            cmd, x, y, abs(xb - xa_), abs(yb - ya_), style, fill_cmd, stroke_c, sw, y1v[i] >= y0v[i]
        )


def _emit_grid(cmd, kind, g, blob, cols, sx, sy, style):
    rgba, xr, yr = _scene.grid_rgba(kind, g, blob, cols, style)
    h, w = rgba.shape[0], rgba.shape[1]
    dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
    cmd.image(dx, dy, dw, dh, w, h, rgba.tobytes())


def _emit_legend(cmd, named, plot):
    pad, swatch, line_h = 8, 10, 16
    box_w = max(len(str(t["name"])) for t in named) * 6.2 + swatch + 3 * pad
    box_h = len(named) * line_h + pad
    x = plot["x"] + plot["w"] - box_w - 6
    y = plot["y"] + 6
    cmd.fill(_rect_pts(x, y, x + box_w, y + box_h), (128, 128, 128, 20))
    for i, t in enumerate(named):
        style = t.get("style") or {}
        c = _rgba(
            style.get("color") or (t.get("color") or {}).get("color"),
            DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
        )
        ry = y + pad / 2 + i * line_h
        cmd.fill(_rect_pts(x + pad, ry + 2, x + pad + swatch, ry + 2 + swatch), c)
        cmd.text(x + pad + swatch + 5, ry + swatch, 0, 11, _parse_color(_TEXT), str(t["name"]))


def to_png(
    fig: Any,
    path: Optional[str | PathLike[str]] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
) -> bytes:
    """Render `fig` to PNG bytes with the native rasterizer (no browser)."""
    eff_w = (
        int(width)
        if width is not None
        else (fig.width if isinstance(fig.width, (int, float)) else 900)
    )
    spec, blob = fig.build_payload(px_width=max(256, int(eff_w)))
    if width is not None:
        spec["width"] = int(width)
    if height is not None:
        spec["height"] = int(height)
    img = render_raster(spec, blob, float(scale))
    data = _png.encode(img)
    if path is not None:
        with open(path, "wb") as f:
            f.write(data)
    return data
