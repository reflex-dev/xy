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
    _colormap_stops,
    _column,
    _corner_radii,
    _css,
    _lut,
    _resolve_static_css_vars,
    _Scale,
    _step_arrays,
    _tick_text,
    axis_ticks,
    layout,
)

# Opcodes — must match src/raster.rs.
(
    _CLIP,
    _FILL,
    _GRAD,
    _STROKE,
    _POINT,
    _IMAGE,
    _TEXT_OP,
    _POINTS,
    _SEGMENTS,
    _RECTS,
    _TRIANGLES,
    _SMOOTH_STROKE,
    _DENSITY_IMAGE,
    _HEATMAP_IMAGE,
    _AFFINE_POINTS,
    _AFFINE_CHANNEL_POINTS,
    _STROKED_TRIANGLES,
) = range(17)
_SYMBOLS = {
    "circle": 0,
    "square": 1,
    "diamond": 2,
    "triangle": 3,
    "cross": 4,
    "hexagon": 5,
    "pentagon": 6,
    "star": 7,
    "triangle_down": 8,
    "triangle_left": 9,
    "triangle_right": 10,
    "x": 11,
    "point": 12,
    "pixel": 13,
    "thin_diamond": 14,
    "plus_line": 15,
    "x_line": 16,
}


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


def _fill_opacity(style: dict[str, Any], default: float = 1.0) -> float:
    return float(style.get("opacity", default)) * float(style.get("fill_opacity", 1.0))


def _stroke_opacity(style: dict[str, Any], default: float = 1.0) -> float:
    return float(style.get("opacity", default)) * float(style.get("stroke_opacity", 1.0))


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

    def _raw_d(self, v: float) -> None:
        self.buf += struct.pack("<d", v)

    def _u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v)

    def _u64(self, v: int) -> None:
        self.buf += struct.pack("<Q", v)

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
        if isinstance(pts, np.ndarray):
            scaled = np.asarray(pts, dtype=np.float64) * self.s
            self.buf += scaled.astype("<f4").tobytes()
        else:
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

    def affine_points(self, x_meta, y_meta, sx, sy, radius, fill, symbol, sw, stroke) -> None:
        """Borrow offset-encoded f32 x/y columns and project them in Rust.

        This private static-export command is the zero-copy counterpart of
        :meth:`points` for constant-style marks on affine axes.  The native
        reader repeats the exact f64 decode/project/f32 conversion order used
        by ``_column`` + ``_Scale`` + ``points``; the general command remains
        the fallback for log axes and data-driven color/size channels.
        """
        n = int(x_meta["len"])
        if n == 0:
            return
        if int(y_meta["len"]) != n:
            raise ValueError("scatter x/y payload columns must have equal lengths")
        self.buf.append(_AFFINE_POINTS)
        self._u32(n)
        self.buf.append(symbol)
        self._f(sw)
        self._rgba(stroke)
        self._f(radius)
        self._rgba(fill)
        for meta in (x_meta, y_meta):
            self._u32(int(meta.get("span", 0)))
            self._u64(int(meta["byte_offset"]))
            self._raw_d(float(meta.get("scale") or 1.0))
            self._raw_d(float(meta.get("offset", 0.0)))
        for axis in (sx, sy):
            for value in (axis.lo, axis.hi, axis.px0, axis.px1):
                self._raw_d(float(value))
        self._raw_d(float(self.s))

    def affine_channel_points(
        self,
        x_meta,
        y_meta,
        sx,
        sy,
        color_channel,
        size_channel,
        fill,
        symbol,
        sw,
        stroke,
        columns,
    ) -> None:
        """Borrow affine geometry plus data-driven color/size channels.

        Rust materializes only compact screen-space scratch arrays for the
        synchronous paint. Log axes and unsupported channel modes stay on the
        expanded ``points`` command, preserving one general fallback.
        """
        n = int(x_meta["len"])
        if n == 0:
            return
        if int(y_meta["len"]) != n:
            raise ValueError("scatter x/y payload columns must have equal lengths")

        self.buf.append(_AFFINE_CHANNEL_POINTS)
        self._u32(n)
        self.buf.append(symbol)
        self._f(sw)
        self._rgba(stroke)
        for meta in (x_meta, y_meta):
            self._u32(int(meta.get("span", 0)))
            self._u64(int(meta["byte_offset"]))
            self._raw_d(float(meta.get("scale") or 1.0))
            self._raw_d(float(meta.get("offset", 0.0)))
        for axis in (sx, sy):
            for value in (axis.lo, axis.hi, axis.px0, axis.px1):
                self._raw_d(float(value))
        self._raw_d(float(self.s))

        color_mode = color_channel.get("mode")
        encoded_color_mode = {"continuous": 1, "categorical": 2}.get(color_mode, 0)
        self.buf.append(encoded_color_mode)
        self._rgba(fill)
        if encoded_color_mode:
            meta = columns[color_channel["buf"]]
            if int(meta["len"]) != n:
                raise ValueError("scatter color payload must match geometry length")
            # Private display-list tag: categorical browser payloads may now
            # borrow lossless u8 codes, while continuous and >256-category
            # channels retain f32.  Rust consumes either without expansion.
            color_encoding = 1 if meta.get("dtype") == "u8" else 0
            if encoded_color_mode == 1 and color_encoding != 0:
                raise ValueError("continuous scatter color payload must be f32")
            self.buf.append(color_encoding)
            self._u32(int(meta.get("span", 0)))
            self._u64(int(meta["byte_offset"]))
            if encoded_color_mode == 1:
                entries = _colormap_stops(color_channel.get("colormap", "viridis"))
            else:
                entries = [
                    _parse_color(entry)[:3]
                    for entry in color_channel.get("palette") or DEFAULT_PALETTE
                ]
            self._u32(len(entries))
            self.buf += np.ascontiguousarray(entries, dtype=np.uint8).reshape(-1).tobytes()

        size_mode = size_channel.get("mode")
        self.buf.append(1 if size_mode == "continuous" else 0)
        if size_mode == "continuous":
            meta = columns[size_channel["buf"]]
            if int(meta["len"]) != n:
                raise ValueError("scatter size payload must match geometry length")
            self._u32(int(meta.get("span", 0)))
            self._u64(int(meta["byte_offset"]))
            r0, r1 = size_channel.get("range_px", [2, 18])
            self._raw_d(float(r0))
            self._raw_d(float(r1))
        else:
            self._f(float(size_channel.get("size", 4.0)) / 2)

    def segments(self, x0, y0, x1, y1, width, colors) -> None:
        n = len(x0)
        if n == 0 or width <= 0:
            return
        self.buf.append(_SEGMENTS)
        self._u32(n)
        self._f(width)
        for arr in (x0, y0, x1, y1):
            scaled = np.asarray(arr, dtype=np.float64) * self.s
            self.buf += scaled.astype("<f4").tobytes()
        self.buf += np.ascontiguousarray(colors, dtype=np.uint8).tobytes()

    def rects(self, x0, y0, x1, y1, fills) -> None:
        n = len(x0)
        if n == 0:
            return
        self.buf.append(_RECTS)
        self._u32(n)
        for arr in (x0, y0, x1, y1):
            scaled = np.asarray(arr, dtype=np.float64) * self.s
            self.buf += scaled.astype("<f4").tobytes()
        self.buf += np.ascontiguousarray(fills, dtype=np.uint8).tobytes()

    def triangles(self, x0, y0, x1, y1, x2, y2, fills, sw=0.0, stroke=None) -> None:
        n = len(x0)
        if n == 0:
            return
        stroked = sw > 0
        self.buf.append(_STROKED_TRIANGLES if stroked else _TRIANGLES)
        self._u32(n)
        if stroked:
            self._f(sw)
            self._rgba(stroke or (0, 0, 0, 0))
        for arr in (x0, y0, x1, y1, x2, y2):
            scaled = np.asarray(arr, dtype=np.float64) * self.s
            self.buf += scaled.astype("<f4").tobytes()
        self.buf += np.ascontiguousarray(fills, dtype=np.uint8).tobytes()

    def smooth_stroke(self, xv, yv, sx, sy, width, color, dash=None) -> None:
        """Native monotone-Hermite flattening + stroke for affine axes."""
        n = len(xv)
        if n < 2 or width <= 0:
            return
        self.buf.append(_SMOOTH_STROKE)
        self._u32(n)
        for value in (
            sx.lo,
            sx.hi,
            sx.px0 * self.s,
            sx.px1 * self.s,
            sy.lo,
            sy.hi,
            sy.px0 * self.s,
            sy.px1 * self.s,
        ):
            self.buf += struct.pack("<d", value)
        self.buf += np.ascontiguousarray(xv, dtype="<f8").tobytes()
        self.buf += np.ascontiguousarray(yv, dtype="<f8").tobytes()
        self._f(width)
        self._rgba(color)
        dash = dash or []
        self._u32(len(dash))
        for value in dash:
            self._f(value)

    def image(self, dx, dy, dw, dh, iw, ih, rgba_bytes, *, nearest=False) -> None:
        self.buf.append(_IMAGE)
        self._f(dx)
        self._f(dy)
        self._f(dw)
        self._f(dh)
        self._u32(iw)
        self._u32(ih)
        self.buf.append(1 if nearest else 0)
        self.buf += rgba_bytes

    def density_image(
        self, dx, dy, dw, dh, iw, ih, byte_offset, maximum, stops, opacity, *, span=0
    ) -> None:
        """Reference a compact log-u8 density grid in the payload data arena."""
        self.buf.append(_DENSITY_IMAGE)
        self._f(dx)
        self._f(dy)
        self._f(dw)
        self._f(dh)
        self._u32(iw)
        self._u32(ih)
        self._u32(span)
        self._u64(byte_offset)
        self._raw_d(maximum)
        self._raw_d(opacity)
        stops = np.ascontiguousarray(stops, dtype=np.uint8).reshape(-1, 3)
        self._u32(len(stops))
        self.buf += stops.tobytes()

    def heatmap_image(
        self,
        dx,
        dy,
        dw,
        dh,
        iw,
        ih,
        byte_offset,
        stops,
        alpha,
        *,
        span=0,
        canonical=False,
        domain=(0.0, 1.0),
    ) -> None:
        """Reference normalized f32 heatmap values in the payload data arena."""
        self.buf.append(_HEATMAP_IMAGE)
        self._f(dx)
        self._f(dy)
        self._f(dw)
        self._f(dh)
        self._u32(iw)
        self._u32(ih)
        self._u32(span)
        self._u64(byte_offset)
        self.buf.append(1 if canonical else 0)
        self._raw_d(domain[0])
        self._raw_d(domain[1])
        self.buf.append(alpha)
        stops = np.ascontiguousarray(stops, dtype=np.uint8).reshape(-1, 3)
        self._u32(len(stops))
        self.buf += stops.tobytes()

    def text(self, x, y, anchor, size, color, s) -> None:
        data = str(s).encode("utf-8")
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


def render_raster(
    spec: dict[str, Any],
    blob: bytes,
    scale: float = 2.0,
    *,
    fast_png: bool = False,
    borrowed: tuple[np.ndarray, ...] = (),
) -> np.ndarray | bytes:
    """Paint `spec` into an ``(h, w, 4)`` RGBA8 image via the native rasterizer."""
    spec = _resolve_static_css_vars(spec)
    width, height, compact, plot = layout(spec)
    xa, ya = spec["x_axis"], spec["y_axis"]
    sx = _Scale(xa, plot["x"], plot["x"] + plot["w"])
    sy = _Scale(ya, plot["y"] + plot["h"], plot["y"])
    cols = spec["columns"]
    cmd = _Cmd(scale)

    dom_style = (spec.get("dom") or {}).get("style") or {}

    # The fused PNG path initializes its native canvas white, avoiding a second
    # full-frame memory pass. Raw RGBA callers still receive an explicit fill.
    if not fast_png:
        cmd.fill(
            _rect_pts(0, 0, width, height),
            _parse_color(spec.get("canvas_background", "#ffffff")),
        )

    # Static exports honor the same axes background token as HTML/SVG.  This
    # is deliberately a plot-rect fill rather than a canvas fill: the latter
    # is the Figure patch and is composed by pyplot's grid exporter.
    plot_background = _parse_color(_css(dom_style.get("--chart-bg"), "#ffffff"))
    cmd.fill(
        _rect_pts(plot["x"], plot["y"], plot["x"] + plot["w"], plot["y"] + plot["h"]),
        plot_background,
    )

    xt, xlab, xstep = axis_ticks(xa, plot["w"], True)
    yt, ylab, ystep = axis_ticks(ya, plot["h"], False)
    xstyle, ystyle = xa.get("style") or {}, ya.get("style") or {}
    default_grid = _css(dom_style.get("--chart-grid"), _GRID)
    default_axis = _css(dom_style.get("--chart-axis"), _AXIS)
    default_text = _css(dom_style.get("--chart-text"), _TEXT)
    px0, py0 = plot["x"], plot["y"]
    px1, py1 = plot["x"] + plot["w"], plot["y"] + plot["h"]

    hide_x = xa.get("tick_label_strategy") == "none"
    hide_y = ya.get("tick_label_strategy") == "none"
    hide_x_labels = hide_x or xa.get("tick_label_strategy") == "off"
    hide_y_labels = hide_y or ya.get("tick_label_strategy") == "off"

    cmd.clip(px0, py0, plot["w"], plot["h"])
    for v in [] if hide_x else xt:
        gx = float(sx(v))
        cmd.stroke(
            [(gx, py0), (gx, py1)],
            float(xstyle.get("grid_width", 1)),
            _parse_color(_css(xstyle.get("grid_color"), default_grid)),
        )
    for v in [] if hide_y else yt:
        gy = float(sy(v))
        cmd.stroke(
            [(px0, gy), (px1, gy)],
            float(ystyle.get("grid_width", 1)),
            _parse_color(_css(ystyle.get("grid_color"), default_grid)),
        )

    for palette_i, t in enumerate(spec["traces"]):
        style = t.get("style") or {}
        color = _css(style.get("color"), DEFAULT_PALETTE[palette_i % len(DEFAULT_PALETTE)])
        kind = t["kind"]
        if t.get("tier") == "density" and t.get("density"):
            _emit_grid(cmd, "density", t["density"], blob, cols, sx, sy, style)
        elif kind == "line":
            _emit_line(cmd, t, blob, cols, sx, sy, style, color)
        elif kind in ("area", "error_band"):
            _emit_area(cmd, t, blob, cols, sx, sy, style, color, plot)
        elif kind == "scatter":
            _emit_scatter(cmd, t, blob, cols, sx, sy, style, color)
        elif kind == "hexbin":
            _emit_triangle_mesh(cmd, t, blob, cols, sx, sy, style, color)
        elif kind in {"errorbar", "stem", "box_whisker", "box_median", "contour", "segments"}:
            _emit_segments(cmd, t, blob, cols, sx, sy, style, color)
        elif kind in ("bar", "column") and t.get("bar"):
            _emit_bars(cmd, t, blob, cols, sx, sy, style, color, plot)
        elif kind == "heatmap" and t.get("heatmap"):
            _emit_grid(cmd, "heatmap", t["heatmap"], blob, cols, sx, sy, style)
        elif kind == "triangle_mesh":
            _emit_triangle_mesh(cmd, t, blob, cols, sx, sy, style, color)
        elif all(k in t for k in ("x0", "x1", "y0", "y1")):
            _emit_rects(cmd, t, blob, cols, sx, sy, style, color, plot)

    _emit_annotations(cmd, spec.get("annotations") or [], sx, sy, plot, width, height)

    # Chrome (unclipped): baselines, labels, title, legend.
    cmd.clip(0, 0, width, height)
    # "none" silences the whole axis chrome (sparklines); "off" hides only the
    # label text and keeps baselines and the axis title (mpl shared axes).
    frame_sides = spec.get("frame_sides")
    if frame_sides is None:
        frame_sides = [xa.get("side", "bottom"), ya.get("side", "left")]
    if not hide_y:
        if "left" in frame_sides:
            cmd.stroke(
                [(px0, py0), (px0, py1)],
                float(ystyle.get("axis_width", 1)),
                _parse_color(_css(ystyle.get("axis_color"), default_axis)),
            )
        if "right" in frame_sides:
            cmd.stroke(
                [(px1, py0), (px1, py1)],
                float(ystyle.get("axis_width", 1)),
                _parse_color(_css(ystyle.get("axis_color"), default_axis)),
            )
    if not hide_x:
        if "top" in frame_sides:
            cmd.stroke(
                [(px0, py0), (px1, py0)],
                float(xstyle.get("axis_width", 1)),
                _parse_color(_css(xstyle.get("axis_color"), default_axis)),
            )
        if "bottom" in frame_sides:
            cmd.stroke(
                [(px0, py1), (px1, py1)],
                float(xstyle.get("axis_width", 1)),
                _parse_color(_css(xstyle.get("axis_color"), default_axis)),
            )

    def tick_span(style):
        length = max(0.0, float(style.get("tick_length", 0)))
        direction = str(style.get("tick_direction", "out"))
        if direction == "in":
            return length, 0.0
        if direction == "inout":
            return length / 2, length / 2
        return 0.0, length

    if not hide_x:
        inward, outward = tick_span(xstyle)
        side = xa.get("side", "bottom")
        edge = py0 if side == "top" else py1
        for value in xt:
            x = float(sx(value))
            y0, y1 = (
                (edge - outward, edge + inward)
                if side == "top"
                else (edge - inward, edge + outward)
            )
            cmd.stroke(
                [(x, y0), (x, y1)],
                float(xstyle.get("tick_width", 1)),
                _parse_color(_css(xstyle.get("axis_color"), default_axis)),
            )
    if not hide_y:
        inward, outward = tick_span(ystyle)
        side = ya.get("side", "left")
        edge = px1 if side == "right" else px0
        for value in yt:
            y = float(sy(value))
            x0, x1 = (
                (edge - inward, edge + outward)
                if side == "right"
                else (edge - outward, edge + inward)
            )
            cmd.stroke(
                [(x0, y), (x1, y)],
                float(ystyle.get("tick_width", 1)),
                _parse_color(_css(ystyle.get("axis_color"), default_axis)),
            )

    text_c = _parse_color(default_text)
    if not hide_x_labels:
        x_tick_c = _parse_color(_css(xstyle.get("tick_color"), default_text))
        for v in xlab:
            label_y = py0 - 7 if xa.get("side") == "top" else py1 + 15
            cmd.text(
                float(sx(v)),
                label_y,
                1,
                float(xstyle.get("tick_size", 11)),
                x_tick_c,
                _tick_text(xa, v, xstep),
            )
    if not hide_y_labels:
        y_tick_c = _parse_color(_css(ystyle.get("tick_color"), default_text))
        for v in ylab:
            cmd.text(
                px0 - 8,
                float(sy(v)) + 4,
                2,
                float(ystyle.get("tick_size", 11)),
                y_tick_c,
                _tick_text(ya, v, ystep),
            )
    if spec.get("title"):
        cmd.text(width / 2, plot["y"] - (10 if compact else 12), 1, 14, text_c, str(spec["title"]))
    if xa.get("label") and not hide_x:
        cmd.text(
            px0 + plot["w"] / 2,
            py1 + 33,
            1,
            float(xstyle.get("label_size", 12)),
            _parse_color(_css(xstyle.get("label_color"), default_text)),
            str(xa["label"]),
        )
    if ya.get("label") and not hide_y:
        # Rotated 90° CCW alongside the axis, matching the SVG export.
        cmd.text(
            14,
            plot["y"] + plot["h"] / 2,
            1 | 0x80,
            float(ystyle.get("label_size", 12)),
            _parse_color(_css(ystyle.get("label_color"), default_text)),
            str(ya["label"]),
        )

    named = [t for t in spec["traces"] if t.get("name")]
    if spec.get("show_legend", True) and named:
        _emit_legend(cmd, named, plot, spec.get("legend") or {})
    if spec.get("colorbar"):
        _emit_colorbar(cmd, spec["colorbar"], plot)

    w_px, h_px = max(1, round(width * scale)), max(1, round(height * scale))
    from . import _native

    spans = (blob, *borrowed)
    if fast_png:
        return _native.rasterize_png_spans(bytes(cmd.buf), spans, w_px, h_px)
    return _native.rasterize_spans(bytes(cmd.buf), spans, w_px, h_px)


def _emit_line(cmd, t, blob, cols, sx, sy, style, color):
    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    if style.get("step"):
        xv, yv = _step_arrays(xv, yv, style["step"])
    c = _rgba(style.get("color"), color, _stroke_opacity(style))
    width = float(style.get("width", 1.5))
    if style.get("curve") == "smooth" and len(xv) >= 3 and sx.affine and sy.affine:
        cmd.smooth_stroke(xv, yv, sx, sy, width, c, dash=style.get("dash"))
    else:
        pts = _scene.curve_points(xv, yv, sx, sy, False)
        cmd.stroke(pts, width, c, dash=style.get("dash"))


def _annotation_point(ann, style, sx, sy, plot, width, height):
    space = style.get("coordinate_space")
    x, y = float(ann.get("x", 0.0)), float(ann.get("y", 0.0))
    if space == "axes_fraction":
        return plot["x"] + x * plot["w"], plot["y"] + (1.0 - y) * plot["h"]
    if space == "figure_fraction":
        return x * width, (1.0 - y) * height
    if space == "yaxis_transform":
        return plot["x"] + x * plot["w"], float(sy(y))
    if space == "xaxis_transform":
        return float(sx(x)), plot["y"] + (1.0 - y) * plot["h"]
    return float(sx(x)), float(sy(y))


def _emit_annotations(cmd, annotations, sx, sy, plot, width, height):
    px0, py0 = plot["x"], plot["y"]
    for ann in annotations:
        style = ann.get("style") or {}
        color = _rgba(style.get("color"), "#667085", float(style.get("opacity", 1.0)))
        start = max(0.0, min(1.0, float(style.get("span_start", 0.0))))
        end = max(start, min(1.0, float(style.get("span_end", 1.0))))
        if ann.get("kind") == "rule":
            if ann.get("axis") == "x":
                pos = float(sx(float(ann["value"])))
                points = [(pos, py0 + (1 - end) * plot["h"]), (pos, py0 + (1 - start) * plot["h"])]
            else:
                pos = float(sy(float(ann["value"])))
                points = [(px0 + start * plot["w"], pos), (px0 + end * plot["w"], pos)]
            cmd.stroke(
                points,
                float(style.get("width", 1.5)),
                color,
                dash=(
                    [float(value) for value in style["dash"].split(",")]
                    if isinstance(style.get("dash"), str)
                    else style.get("dash")
                ),
            )
        elif ann.get("kind") == "band":
            a, b = float(ann["start"]), float(ann["end"])
            if ann.get("axis") == "x":
                x0, x1 = sorted((float(sx(a)), float(sx(b))))
                y0, y1 = py0 + (1 - end) * plot["h"], py0 + (1 - start) * plot["h"]
            else:
                y0, y1 = sorted((float(sy(a)), float(sy(b))))
                x0, x1 = px0 + start * plot["w"], px0 + end * plot["w"]
            cmd.fill(
                _rect_pts(x0, y0, x1, y1),
                _rgba(style.get("color"), "#64748b", float(style.get("opacity", 0.14))),
            )
        elif ann.get("kind") == "arrow":
            x0, y0 = float(sx(float(ann["x0"]))), float(sy(float(ann["y0"])))
            x1, y1 = float(sx(float(ann["x1"]))), float(sy(float(ann["y1"])))
            if all(np.isfinite(v) for v in (x0, y0, x1, y1)):
                angle = np.arctan2(y1 - y0, x1 - x0)
                head = max(7.0, float(style.get("head_size", 8.0)))
                cmd.stroke(
                    [(x0, y0), (x1, y1)],
                    max(0.5, float(style.get("width", 1.5))),
                    color,
                    dash=(
                        [float(value) for value in style["dash"].split(",")]
                        if isinstance(style.get("dash"), str)
                        else style.get("dash")
                    ),
                )
                cmd.fill(
                    [
                        (x1, y1),
                        (
                            x1 - head * float(np.cos(angle - np.pi / 6)),
                            y1 - head * float(np.sin(angle - np.pi / 6)),
                        ),
                        (
                            x1 - head * float(np.cos(angle + np.pi / 6)),
                            y1 - head * float(np.sin(angle + np.pi / 6)),
                        ),
                    ],
                    color,
                )
        if ann.get("kind") == "text" and ann.get("text"):
            x, y = _annotation_point(ann, style, sx, sy, plot, width, height)
            anchor = {"start": 0, "middle": 1, "end": 2}.get(ann.get("anchor"), 0)
            font_size = float(style.get("font_size", 11))
            lines = str(ann["text"]).splitlines() or [""]
            line_height = font_size * 1.2
            first_y = y - (len(lines) - 1) * line_height / 2
            for index, line in enumerate(lines):
                cmd.text(
                    x + float(ann.get("dx", 0.0)),
                    first_y + index * line_height + float(ann.get("dy", 0.0)),
                    anchor,
                    font_size,
                    _rgba(style.get("color"), _TEXT, float(style.get("opacity", 1.0))),
                    line,
                )


def _emit_area(cmd, t, blob, cols, sx, sy, style, color, plot):
    xv = _column(blob, cols[t["x"]])
    yv = _column(blob, cols[t["y"]])
    bv = _column(blob, cols[t["base"]])
    smooth = style.get("curve") == "smooth"
    top = _scene.curve_points(xv, yv, sx, sy, smooth)
    base = _scene.curve_points(xv[::-1], bv[::-1], sx, sy, smooth)
    poly = np.vstack([top, base])
    op = _fill_opacity(style, 0.35)
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
        lop = _stroke_opacity(style, 0.35) * float(style.get("line_opacity", 1.0))
        line_color = _rgba(style.get("line_color"), style.get("color") or color, lop)
        cmd.stroke(top, lw, line_color, dash=style.get("dash"))
        if style.get("stroke_perimeter"):
            cmd.stroke(base, lw, line_color, dash=style.get("dash"))


def _emit_scatter(cmd, t, blob, cols, sx, sy, style, color):
    ch = t.get("color") or {}
    size_ch = t.get("size") or {}
    fill_op = _fill_opacity(style, 0.8)
    stroke_op = _stroke_opacity(style, 0.8)
    sw = float(style.get("stroke_width", 0.0))
    sym = _SYMBOLS.get(style.get("symbol", "circle"), 0)
    # Transparent is the private wire sentinel for edgecolors="face".  The
    # native point painter replaces it with each point's resolved RGBA fill.
    stroke_value = style.get("stroke")
    stroke = (
        _rgba(stroke_value, color, stroke_op)
        if sw > 0 and stroke_value is not None
        else (0, 0, 0, 0)
    )

    color_mode = ch.get("mode")
    size_mode = size_ch.get("mode")
    if (
        sx.affine
        and sy.affine
        and (color_mode in {"continuous", "categorical"} or size_mode == "continuous")
    ):
        alpha = max(0, min(255, int(round(fill_op * 255))))
        rgb = _parse_color(_css(ch.get("color"), color))[:3]
        cmd.affine_channel_points(
            cols[t["x"]],
            cols[t["y"]],
            sx,
            sy,
            ch,
            size_ch,
            (rgb[0], rgb[1], rgb[2], alpha),
            sym,
            sw,
            stroke,
            cols,
        )
        return

    # The dominant static-scatter case needs neither materialized f64 decoded
    # columns nor projected/radius/RGBA arrays.  Rust borrows the two payload
    # spans and applies the same affine math while painting.  Keep the existing
    # command as the full-fidelity fallback for log axes and channel styling.
    if (
        sx.affine
        and sy.affine
        and ch.get("mode") not in {"continuous", "categorical"}
        and size_ch.get("mode") != "continuous"
    ):
        alpha = max(0, min(255, int(round(fill_op * 255))))
        rgb = _parse_color(_css(ch.get("color"), color))[:3]
        fill = (rgb[0], rgb[1], rgb[2], alpha)
        radius = float(size_ch.get("size", 4.0)) / 2
        cmd.affine_points(cols[t["x"]], cols[t["y"]], sx, sy, radius, fill, sym, sw, stroke)
        return

    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    px, py = sx(xv), sy(yv)
    n = len(xv)
    fills = np.empty((n, 4), dtype=np.uint8)
    fills[:, 3] = max(0, min(255, int(round(fill_op * 255))))
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

    if size_ch.get("mode") == "continuous":
        sv = _column(blob, cols[size_ch["buf"]])
        r0, r1 = size_ch.get("range_px", [2, 18])
        radii = (r0 + (r1 - r0) * np.clip(sv, 0, 1)) / 2
    else:
        radii = np.full(n, float(size_ch.get("size", 4.0)) / 2)

    cmd.points(px, py, radii, fills, sym, sw, stroke)


def _emit_segments(cmd, t, blob, cols, sx, sy, style, color):
    x0 = _column(blob, cols[t["x0"]])
    x1 = _column(blob, cols[t["x1"]])
    y0 = _column(blob, cols[t["y0"]])
    y1 = _column(blob, cols[t["y1"]])
    ch = t.get("color") or {}
    opacity = _stroke_opacity(style)
    colors = np.empty((len(x0), 4), dtype=np.uint8)
    colors[:, 3] = max(0, min(255, int(round(255 * opacity))))
    if ch.get("mode") == "continuous":
        colors[:, :3] = _lut(ch.get("colormap", "viridis"), _column(blob, cols[ch["buf"]]))
    elif ch.get("mode") == "categorical":
        codes = _column(blob, cols[ch["buf"]]).astype(np.int64)
        palette = ch.get("palette") or DEFAULT_PALETTE
        palette_rgb = np.array([_parse_color(entry)[:3] for entry in palette], dtype=np.uint8)
        colors[:, :3] = palette_rgb[codes % len(palette_rgb)]
    else:
        colors[:] = _rgba(style.get("color"), color, opacity)
    width = float(style.get("width", 1.2))
    dash = style.get("dash")
    if dash:
        # The batched segments primitive cannot dash; fall back to one dashed
        # stroke per segment (contour negative-level convention, few segments).
        dash_pattern = (
            [float(value) for value in dash.split(",")] if isinstance(dash, str) else list(dash)
        )
        px0, py0, px1, py1 = sx(x0), sy(y0), sx(x1), sy(y1)
        for index in range(len(x0)):
            cmd.stroke(
                [(float(px0[index]), float(py0[index])), (float(px1[index]), float(py1[index]))],
                width,
                tuple(int(v) for v in colors[index]),
                dash=dash_pattern,
            )
        return
    cmd.segments(sx(x0), sy(y0), sx(x1), sy(y1), width, colors)


def _emit_triangle_mesh(cmd, t, blob, cols, sx, sy, style, color):
    vertices = [_column(blob, cols[t[name]]) for name in ("x0", "y0", "x1", "y1", "x2", "y2")]
    n = min(len(values) for values in vertices)
    ch = t.get("color") or {}
    fill_op = _fill_opacity(style)
    stroke_op = _stroke_opacity(style)
    fills = np.empty((n, 4), dtype=np.uint8)
    fills[:, 3] = max(0, min(255, int(round(fill_op * 255))))
    if ch.get("mode") == "continuous":
        fills[:, :3] = _lut(ch.get("colormap", "viridis"), _column(blob, cols[ch["buf"]])[:n])
    elif ch.get("mode") == "categorical":
        codes = _column(blob, cols[ch["buf"]])[:n].astype(np.int64)
        palette = ch.get("palette") or DEFAULT_PALETTE
        palette_rgb = np.array([_parse_color(entry)[:3] for entry in palette], dtype=np.uint8)
        fills[:, :3] = palette_rgb[codes % len(palette_rgb)]
    else:
        fills[:, :3] = _parse_color(_css(ch.get("color"), color))[:3]

    x0, y0, x1, y1, x2, y2 = vertices
    sw = float(style.get("stroke_width", 0.0))
    stroke = _rgba(style.get("stroke"), color, stroke_op) if sw > 0 else (0, 0, 0, 0)
    cmd.triangles(
        sx(x0[:n]),
        sy(y0[:n]),
        sx(x1[:n]),
        sy(y1[:n]),
        sx(x2[:n]),
        sy(y2[:n]),
        fills,
        sw,
        stroke,
    )


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
    fill_op = _fill_opacity(style, 0.85)
    stroke_op = _stroke_opacity(style, 0.85)
    sw = float(style.get("stroke_width", 0.0))
    stroke_c = _rgba(style.get("stroke"), color, stroke_op) if sw > 0 else (0, 0, 0, 0)
    fill_spec = style.get("fill")
    if isinstance(fill_spec, dict):
        stops = [
            (o, (c[0], c[1], c[2], int(c[3] * fill_op))) for o, c in _grad_stops(fill_spec, color)
        ]

        def fill_cmd(poly):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            g0, g1 = _grad_line(
                fill_spec.get("space", "mark"), fill_spec.get("dir", "down"), bbox, plot
            )
            cmd.grad(poly, g0, g1, stops)
    else:
        flat = _rgba(style.get("color"), color, fill_op)

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
    r_tip, r_base = _corner_radii(style)
    sw = float(style.get("stroke_width", 0.0))
    if not isinstance(style.get("fill"), dict) and not (r_tip or r_base or sw > 0):
        if horizontal:
            xa, xb = sx(np.minimum(v0, v1)), sx(np.maximum(v0, v1))
            ya, yb = sy(pos + half), sy(pos - half)
        else:
            xa, xb = sx(pos - half), sx(pos + half)
            ya, yb = sy(np.maximum(v0, v1)), sy(np.minimum(v0, v1))
        x0, x1 = np.minimum(xa, xb), np.maximum(xa, xb)
        y0, y1 = np.minimum(ya, yb), np.maximum(ya, yb)
        fill = _rgba(style.get("color"), color, _fill_opacity(style, 0.85))
        fills = np.tile(np.asarray(fill, dtype=np.uint8), (len(pos), 1))
        cmd.rects(x0, y0, x1, y1, fills)
        return
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
    r_tip, r_base = _corner_radii(style)
    sw = float(style.get("stroke_width", 0.0))
    if not isinstance(style.get("fill"), dict) and not (r_tip or r_base or sw > 0):
        xa, xb = sx(x0v), sx(x1v)
        ya, yb = sy(y0v), sy(y1v)
        fill = _rgba(style.get("color"), color, _fill_opacity(style, 0.85))
        fills = np.tile(np.asarray(fill, dtype=np.uint8), (len(x0v), 1))
        cmd.rects(
            np.minimum(xa, xb),
            np.minimum(ya, yb),
            np.maximum(xa, xb),
            np.maximum(ya, yb),
            fills,
        )
        return
    fill_cmd, stroke_c, sw = _fill_maker(cmd, style, color, plot)
    for i in range(len(x0v)):
        xa_, xb = float(sx(x0v[i])), float(sx(x1v[i]))
        ya_, yb = float(sy(y0v[i])), float(sy(y1v[i]))
        x, y = min(xa_, xb), min(ya_, yb)
        _bar_geom(
            cmd, x, y, abs(xb - xa_), abs(yb - ya_), style, fill_cmd, stroke_c, sw, y1v[i] >= y0v[i]
        )


def _emit_grid(cmd, kind, g, blob, cols, sx, sy, style):
    if kind == "heatmap":
        w, h = int(g["w"]), int(g["h"])
        if "rgba_bufs" in g:
            channels = [_column(blob, cols[index]) for index in g["rgba_bufs"]]
            rgba = np.clip(np.column_stack(channels) * 255.0, 0, 255).astype(np.uint8)
            rgba[:, 3] = (rgba[:, 3].astype(np.float64) * _fill_opacity(style)).astype(np.uint8)
            rgba = rgba.reshape(h, w, 4)[::-1]
            xr, yr = g["x_range"], g["y_range"]
            dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
            cmd.image(dx, dy, dw, dh, w, h, rgba.tobytes(), nearest=True)
            return
        meta = cols[g["buf"]]
        stops = np.asarray(_colormap_stops(g.get("colormap", "viridis")), dtype=np.uint8)
        alpha = int(255 * _fill_opacity(style, 0.95))
        xr, yr = g["x_range"], g["y_range"]
        dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
        canonical = g.get("enc") == "canonical-f64"
        cmd.heatmap_image(
            dx,
            dy,
            dw,
            dh,
            w,
            h,
            meta["byte_offset"],
            stops,
            alpha,
            span=int(meta.get("span", 0)),
            canonical=canonical,
            domain=tuple(g["domain"]) if canonical else (0.0, 1.0),
        )
        return
    elif g.get("enc") == "log-u8":
        w, h = int(g["w"]), int(g["h"])
        meta = cols[g["buf"]]
        paint_alpha = 1.0
        if g.get("color") is not None:
            red, green, blue, alpha = _parse_color(g["color"])
            stops = np.asarray([(red, green, blue), (red, green, blue)], dtype=np.uint8)
            paint_alpha = alpha / 255.0
        else:
            stops = np.asarray(_colormap_stops(g.get("colormap", "viridis")), dtype=np.uint8)
        xr, yr = g["x_range"], g["y_range"]
        dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
        cmd.density_image(
            dx,
            dy,
            dw,
            dh,
            w,
            h,
            meta["byte_offset"],
            float(g.get("max") or 0.0),
            stops,
            _fill_opacity(style, 0.85) * paint_alpha,
            span=int(meta.get("span", 0)),
        )
        return
    else:
        rgba, xr, yr = _scene.grid_rgba(kind, g, blob, cols, style)
        h, w = rgba.shape[0], rgba.shape[1]
    dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
    cmd.image(dx, dy, dw, dh, w, h, rgba.tobytes(), nearest=kind == "heatmap")


# Trace kinds whose legend entry is a short line sample (with dash) rather
# than a marker glyph or a filled patch.
_LEGEND_LINE_KINDS = frozenset({"line", "segments", "step", "stairs", "errorbar"})


def _emit_legend(cmd, named, plot, options):
    style_opts = options.get("style") or {}
    pad, handle, gap, line_h = 8.0, 20, 5, 16.0
    if str(style_opts.get("padding", "")).endswith("em"):
        pad = 11.0 * float(str(style_opts["padding"])[:-2])
    if str(style_opts.get("rowGap", "")).endswith("em"):
        line_h = 11.0 * (1.0 + float(str(style_opts["rowGap"])[:-2]))
    ncols = min(len(named), max(1, int(options.get("ncols", 1))))
    nrows = (len(named) + ncols - 1) // ncols
    title = options.get("title")
    title_h = 16 if title else 0
    cell_w = max(len(str(t["name"])) for t in named) * 6.2 + handle + gap + 2 * pad
    box_w, box_h = ncols * cell_w + pad, nrows * line_h + pad + title_h
    loc = options.get("loc") or "upper right"
    x = plot["x"] + 6 if "left" in loc else plot["x"] + plot["w"] - box_w - 6
    y = plot["y"] + plot["h"] - box_h - 6 if "lower" in loc else plot["y"] + 6
    # frameon=False (background transparent) drops the box entirely (§ mpl parity).
    if style_opts.get("background") != "transparent":
        if style_opts.get("boxShadow"):
            cmd.fill(_rect_pts(x + 2, y + 2, x + box_w + 2, y + box_h + 2), (0, 0, 0, 55))
        alpha = float(style_opts.get("--xy-legend-frame-alpha", 0.08))
        background = style_opts.get("background")
        frame = (
            _rgba(background, "#808080", alpha)
            if background
            else (128, 128, 128, round(255 * alpha))
        )
        cmd.fill(_rect_pts(x, y, x + box_w, y + box_h), frame)
    if title:
        cmd.text(x + pad, y + pad / 2 + 11, 0, 11, _parse_color(_TEXT), str(title))
    for i, t in enumerate(named):
        style = t.get("style") or {}
        color_str = _css(
            style.get("color") or (t.get("color") or {}).get("color"),
            DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
        )
        c = _parse_color(color_str)
        col, row = i % ncols, i // ncols
        rx, ry = x + col * cell_w, y + pad / 2 + title_h + row * line_h
        hx0, hx1, cy = rx + pad, rx + pad + handle, ry + 7
        kind = t.get("kind")
        if kind == "scatter":
            sym = _SYMBOLS.get(style.get("symbol", "circle"), 0)
            sw = float(style.get("stroke_width", 0.0))
            stroke = _rgba(style.get("stroke"), color_str) if sw > 0 else (0, 0, 0, 0)
            cmd.point((hx0 + hx1) / 2, cy, 4.0, sym, c, sw, stroke)
        elif kind in _LEGEND_LINE_KINDS:
            cmd.stroke(
                [(hx0, cy), (hx1, cy)],
                float(style.get("width", 1.5)),
                c,
                dash=style.get("dash"),
            )
        else:
            cmd.fill(_rect_pts(hx0, cy - 4, hx1, cy + 4), c)
        cmd.text(hx1 + gap, ry + 11, 0, 11, _parse_color(_TEXT), str(t["name"]))


def _emit_colorbar(cmd, options, plot):
    from ._svg import _linear_ticks, _lut

    orientation = options.get("orientation", "vertical")
    if orientation == "horizontal":
        x, y, width, height = plot["x"], plot["y"] + plot["h"] + 10, plot["w"], 18
    else:
        x, y, width, height = plot["x"] + plot["w"] + 24, plot["y"], 18, plot["h"]
    # A discrete (resampled) colormap paints N solid bands; otherwise a smooth
    # 64-step gradient approximates the continuous ramp.
    levels = options.get("levels")
    if levels and int(levels) >= 1:
        n_seg = int(levels)
        colors = _lut(
            options.get("colormap", "viridis"),
            (np.arange(n_seg, dtype=np.float64) + 0.5) / n_seg,
        )
    else:
        n_seg = 64
        colors = _lut(options.get("colormap", "viridis"), np.linspace(0.0, 1.0, n_seg))
    for index, color in enumerate(colors):
        if orientation == "horizontal":
            x0, x1 = x + width * index / n_seg, x + width * (index + 1) / n_seg
            cmd.fill(_rect_pts(x0, y, x1 + 0.5, y + height), (*map(int, color), 255))
        else:
            y0 = y + height * (n_seg - 1 - index) / n_seg
            y1 = y + height * (n_seg - index) / n_seg
            cmd.fill(_rect_pts(x, y0, x + width, y1 + 0.5), (*map(int, color), 255))
    domain = options.get("domain", [0.0, 1.0])
    lo, hi = float(domain[0]), float(domain[1])
    span = (hi - lo) or 1.0
    ticks = options.get("ticks")
    extend = options.get("extend")
    if extend in ("max", "both"):
        color = (*map(int, colors[-1]), 255)
        if orientation == "horizontal":
            pts = [(x + width, y), (x + width, y + height), (x + width + 9, y + height / 2)]
        else:
            pts = [(x, y), (x + width, y), (x + width / 2, y - 9)]
        cmd.fill(pts, color)
    if extend in ("min", "both"):
        color = (*map(int, colors[0]), 255)
        if orientation == "horizontal":
            pts = [(x, y), (x, y + height), (x - 9, y + height / 2)]
        else:
            pts = [(x, y + height), (x + width, y + height), (x + width / 2, y + height + 9)]
        cmd.fill(pts, color)
    if orientation == "horizontal":
        h_positions = (
            [float(value) for value in ticks if lo <= float(value) <= hi]
            if ticks is not None
            else (_linear_ticks(lo, hi, 8)[0] or [lo, hi])
        )
        for value in h_positions:
            cmd.text(
                x + width * (value - lo) / span,
                y + height + 13,
                1,
                10,
                _parse_color(_TEXT),
                f"{value:g}",
            )
        if options.get("label"):
            cmd.text(
                x + width / 2,
                y + height + 26,
                1,
                10,
                _parse_color(_TEXT),
                str(options["label"]),
            )
    else:
        tick_positions = (
            [float(value) for value in ticks if lo <= float(value) <= hi]
            if ticks is not None
            else (_linear_ticks(lo, hi, 8)[0] or [lo, hi])
        )
        for value in tick_positions:
            cmd.text(
                x + width + 4,
                y + height * (1 - (value - lo) / span) + 4,
                0,
                10,
                _parse_color(_TEXT),
                f"{value:g}",
            )
        # The native text primitive does not rotate; a compact label above the
        # bar remains legible and, crucially, stays inside the export canvas.
        if options.get("label"):
            cmd.text(
                x,
                y - 5,
                0,
                10,
                _parse_color(_TEXT),
                str(options["label"]),
            )


def to_png(
    fig: Any,
    path: Optional[str | PathLike[str]] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    fast: bool = False,
) -> bytes:
    """Render `fig` to PNG bytes with the native rasterizer (no browser)."""
    eff_w = (
        int(width)
        if width is not None
        else (fig.width if isinstance(fig.width, (int, float)) else 900)
    )
    spec, blob, borrowed = fig._build_raster_payload(px_width=max(256, int(eff_w)))
    if width is not None:
        spec["width"] = int(width)
    if height is not None:
        spec["height"] = int(height)
    rendered = render_raster(spec, blob, float(scale), fast_png=fast, borrowed=borrowed)
    data = rendered if isinstance(rendered, bytes) else _png.encode(rendered)
    if path is not None:
        with open(path, "wb") as f:
            f.write(data)
    return data
