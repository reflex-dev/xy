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

import math
import struct
from collections.abc import Callable, Sequence
from itertools import pairwise
from os import PathLike
from typing import Any, Optional, cast

import numpy as np

from . import _paint, _png, _scene, _textblock
from ._arrowgeom import arrow_shapes as _arrow_shapes
from ._svg import (
    _AXIS,
    _AXIS_GRID_DASHES,
    _GRID,
    _STATIC_COLOR_FALLBACK,
    _TEXT,
    COLORBAR_FONT_SIZE,
    DEFAULT_PALETTE,
    _annotation_connector_unclipped,
    _annotation_first_baseline,
    _axis_label_geometry,
    _axis_scales,
    _axis_tick_font_size,
    _axis_tick_label_baseline_shift,
    _axis_tick_label_layout,
    _axis_tick_label_offset,
    _axis_tick_label_sides,
    _axis_tick_label_strategy,
    _axis_tick_sides,
    _box_corner_radius,
    _colorbar_right_axis_room,
    _colormap_stops,
    _column,
    _corner_radii,
    _css,
    _decode_title_geometry,
    _density_column,
    _estimated_text_width,
    _heatmap_rgba_grid,
    _legend_layout,
    _lut,
    _physical_density_alpha,
    _PolarProjection,
    _px_size,
    _resolve_auto_legend_locations,
    _resolve_static_css_vars,
    _Scale,
    _solid_paint,
    _step_arrays,
    _tick_label_anchor,
    _title_entries,
    _title_metrics,
    affine_fast_path,
    annotation_label_placement,
    apply_export_background,
    axis_ticks,
    hexbin_ring,
    layout,
    legend_clip_rect,
    legend_items,
    legend_options_with_slot,
    minor_axis_ticks,
    polar_heatmap_rgba,
    polar_tick_label_layout,
    polar_wedge_points,
    slot_font_size,
    slot_styles,
    slot_text_color,
    warp_grid_rgba,
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
    _STYLED_TEXT,
    _POLAR_CLIP,
) = range(19)
# Anchor-byte rotation flags — must match TEXT_ROTATED/TEXT_ROTATED_CW in
# src/raster.rs. CCW reads bottom-to-top (y-axis titles), CW top-to-bottom
# (right-margin titles, matplotlib rotation=270).
_TEXT_ROT_CCW = 0x80
_TEXT_ROT_CW = 0x40
_TEXT_ITALIC = 0x01
_TEXT_BOLD = 0x02
# stroke-linecap — must match CAP_* in src/raster.rs. XY's default is round,
# which is the geometry the rasterizer's capsule distance field has always
# drawn. Joins are always round and carry no wire field.
_CAP_CODES = {"butt": 0, "round": 1, "square": 2}
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
    "horizontal_line": 17,
    "vertical_line": 18,
}


def _parse_color(css: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    """Resolve a CSS color string to RGBA8 via the native grammar
    (src/css.rs) — the same parser that validates figure input, so raster
    colors can never drift from the API contract. `none` renders transparent
    (the SVG idiom); browser-only forms that survive `_css`'s fallback (an
    `oklch()` a DOM would resolve) and — defensively — anything unparseable
    use the same blue-gray fallback as the browser renderer so a static export
    never renders an invisible or target-dependent mark."""
    from . import kernels

    s = str(css).strip()
    if s.lower() == "none":
        return (0, 0, 0, 0)
    _status, rgba = kernels.css_check(kernels.CSS_COLOR, s)
    if rgba is None:
        rgba = _STATIC_COLOR_FALLBACK
    r, g, b, a = rgba
    return (
        int(round(r * 255)),
        int(round(g * 255)),
        int(round(b * 255)),
        max(0, min(255, int(round(a * 255 * opacity)))),
    )


def _rgba(css: Any, fallback: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    return _parse_color(_css(css, fallback), opacity)


def _solid_color(css: Any) -> Optional[tuple[int, int, int, int]]:
    """A parseable solid CSS color, or None when unset/unpaintable (var(),
    gradients) — for background fills that must be skipped rather than
    fallback-painted. One policy with the SVG exporter (`_solid_paint`)."""
    s = _solid_paint(css)
    return None if s is None else _parse_color(s)


# cmd.text anchor codes (must match src/raster.rs): start/center/end of string.
_TEXT_ANCHOR_CODES = {"start": 0, "center": 1, "end": 2}


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

    def _rgba(self, c: tuple[int, ...]) -> None:
        self.buf += bytes(c)

    def clip(self, x: float, y: float, w: float, h: float) -> None:
        self.buf.append(_CLIP)
        self._f(x)
        self._f(y)
        self._f(w)
        self._f(h)

    def polar_clip(self, polar: _PolarProjection) -> None:
        """Clip subsequent commands to one annular sector.

        Coordinates/radii follow the display list's device-scale convention;
        angles remain dimensionless. A later rectangular ``clip`` resets this
        state, matching the marks→chrome transition in ``render_raster``.
        """
        self.buf.append(_POLAR_CLIP)
        self._f(polar.cx)
        self._f(polar.cy)
        self._f(polar.inner_radius)
        self._f(polar.radius)
        self._raw_f(polar.sector_a0)
        self._raw_f(polar.sector_a1 - polar.sector_a0)

    def fill(self, pts: Sequence[tuple[float, float]], color: tuple[int, ...]) -> None:
        if len(pts) < 3:
            return
        self.buf.append(_FILL)
        self._u32(len(pts))
        for x, y in pts:
            self._f(x)
            self._f(y)
        self._rgba(color)

    def grad(
        self,
        pts: Sequence[tuple[float, float]],
        g0: tuple[float, float],
        g1: tuple[float, float],
        stops: Sequence[tuple[float, tuple[int, ...]]],
    ) -> None:
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

    def stroke(
        self,
        pts: np.ndarray | Sequence[tuple[float, float]],
        width: float,
        color: tuple[int, ...],
        closed: bool = False,
        dash: Sequence[float] | None = None,
        cap: str = "round",
    ) -> None:
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
        self.buf.append(_CAP_CODES[cap])

    def point(
        self,
        cx: float,
        cy: float,
        r: float,
        symbol: int,
        fill: tuple[int, ...],
        sw: float,
        stroke: tuple[int, ...],
    ) -> None:
        self.buf.append(_POINT)
        self._f(cx)
        self._f(cy)
        self._f(r)
        self.buf.append(symbol)
        self._rgba(fill)
        self._f(sw)
        self._rgba(stroke)

    def points(
        self,
        cx: np.ndarray,
        cy: np.ndarray,
        r: np.ndarray,
        fills: np.ndarray,
        symbol: int,
        sw: float,
        stroke: tuple[int, ...],
    ) -> None:
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

    def affine_points(
        self,
        x_meta: dict[str, Any],
        y_meta: dict[str, Any],
        sx: _Scale,
        sy: _Scale,
        radius: float,
        fill: tuple[int, ...],
        symbol: int,
        sw: float,
        stroke: tuple[int, ...],
    ) -> None:
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
        x_meta: dict[str, Any],
        y_meta: dict[str, Any],
        sx: _Scale,
        sy: _Scale,
        color_channel: dict[str, Any],
        size_channel: dict[str, Any],
        fill: tuple[int, ...],
        symbol: int,
        sw: float,
        stroke: tuple[int, ...],
        columns: list[dict[str, Any]],
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
                # Per-index fallback for browser-only entries (shared with the
                # SVG writer and the density plane), so distinct categories do
                # not collapse onto one static fallback color.
                from . import channels as _channels

                palette = color_channel.get("palette") or DEFAULT_PALETTE
                entries = _channels.palette_rows_rgba8(palette, len(palette))[:, :3].tolist()
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

    def segments(
        self,
        x0: np.ndarray,
        y0: np.ndarray,
        x1: np.ndarray,
        y1: np.ndarray,
        width: float,
        colors: np.ndarray,
    ) -> None:
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

    def rects(
        self,
        x0: np.ndarray,
        y0: np.ndarray,
        x1: np.ndarray,
        y1: np.ndarray,
        fills: np.ndarray,
    ) -> None:
        n = len(x0)
        if n == 0:
            return
        self.buf.append(_RECTS)
        self._u32(n)
        for arr in (x0, y0, x1, y1):
            scaled = np.asarray(arr, dtype=np.float64) * self.s
            self.buf += scaled.astype("<f4").tobytes()
        self.buf += np.ascontiguousarray(fills, dtype=np.uint8).tobytes()

    def triangles(
        self,
        x0: np.ndarray,
        y0: np.ndarray,
        x1: np.ndarray,
        y1: np.ndarray,
        x2: np.ndarray,
        y2: np.ndarray,
        fills: np.ndarray,
        sw: float = 0.0,
        stroke: tuple[int, ...] | None = None,
    ) -> None:
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

    def smooth_stroke(
        self,
        xv: np.ndarray,
        yv: np.ndarray,
        sx: _Scale,
        sy: _Scale,
        width: float,
        color: tuple[int, ...],
        dash: Sequence[float] | None = None,
        cap: str = "round",
    ) -> None:
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
        self.buf.append(_CAP_CODES[cap])

    def image(
        self,
        dx: float,
        dy: float,
        dw: float,
        dh: float,
        iw: int,
        ih: int,
        rgba_bytes: bytes,
        *,
        nearest: bool = False,
    ) -> None:
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
        self,
        dx: float,
        dy: float,
        dw: float,
        dh: float,
        iw: int,
        ih: int,
        byte_offset: int,
        maximum: float,
        stops: np.ndarray,
        opacity: float,
        *,
        span: int = 0,
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
        dx: float,
        dy: float,
        dw: float,
        dh: float,
        iw: int,
        ih: int,
        byte_offset: int,
        stops: np.ndarray,
        alpha: int,
        *,
        span: int = 0,
        canonical: bool = False,
        domain: tuple[float, float] = (0.0, 1.0),
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

    def text(
        self,
        x: float,
        y: float,
        anchor: int,
        size: float,
        color: tuple[int, ...],
        s: str,
        *,
        angle: float = 0.0,
        italic: bool = False,
        bold: bool = False,
        italic_ranges: Sequence[tuple[int, int]] = (),
    ) -> None:
        data = str(s).encode("utf-8")
        if angle or italic or bold or italic_ranges:
            self.buf.append(_STYLED_TEXT)
            self._f(x)
            self._f(y)
            self.buf.append(anchor & 0x03)
            self._f(size)
            self._raw_f(angle)
            self.buf.append((_TEXT_ITALIC if italic else 0) | (_TEXT_BOLD if bold else 0))
            self._u32(len(italic_ranges))
            for start, end in italic_ranges:
                self._u32(start)
                self._u32(end)
            self._rgba(color)
            self._u32(len(data))
            self.buf += data
            return
        self.buf.append(_TEXT_OP)
        self._f(x)
        self._f(y)
        self.buf.append(anchor)
        self._f(size)
        self._rgba(color)
        self._u32(len(data))
        self.buf += data


def _emit_text_block(
    cmd: _Cmd,
    x: float,
    first_baseline: float,
    anchor: int,
    size: float,
    color: tuple[int, ...],
    text: object,
    *,
    angle: float = 0.0,
    italic: bool = False,
    bold: bool = False,
) -> None:
    """Emit lines using the same block geometry SVG and layout measure."""
    block = _textblock.measure(text, size)
    radians = math.radians(float(angle))
    for index, line in enumerate(block.lines):
        local_y = index * block.line_step
        line_x = x - local_y * math.sin(radians)
        line_y = first_baseline + local_y * math.cos(radians)
        args = (line_x, line_y, anchor, size, color, line)
        normalized = float(angle) % 360.0
        quarter_flag = (
            _TEXT_ROT_CW
            if abs(normalized - 90.0) < 1e-9
            else _TEXT_ROT_CCW
            if abs(normalized - 270.0) < 1e-9
            else 0
        )
        if quarter_flag and not italic and not bold:
            cmd.text(line_x, line_y, anchor | quarter_flag, size, color, line)
        elif angle or italic or bold:
            cmd.text(*args, angle=angle, italic=italic, bold=bold)
        else:
            cmd.text(*args)


def _rect_pts(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _round_rect_pts(
    x0: float, y0: float, x1: float, y1: float, radius: float, *, steps: int = 4
) -> list[tuple[float, float]]:
    """A rounded rectangle as a closed polygon, corners arc-approximated.

    The rasterizer draws polygons, not paths, so a `boxstyle="round"` bbox is
    flattened here: `steps` segments per quarter turn is enough that a 5–8 px
    corner reads as round at export scale. Degenerate radii fall back to the
    square rect so callers never special-case it.
    """
    radius = max(0.0, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    if radius <= 0.0:
        return _rect_pts(x0, y0, x1, y1)
    pts: list[tuple[float, float]] = []
    # (center, start angle) per corner, walking clockwise in screen space
    # (y down) from the top-left so the winding matches _rect_pts.
    corners = (
        ((x0 + radius, y0 + radius), math.pi),
        ((x1 - radius, y0 + radius), -math.pi / 2.0),
        ((x1 - radius, y1 - radius), 0.0),
        ((x0 + radius, y1 - radius), math.pi / 2.0),
    )
    for (cx, cy), start in corners:
        for i in range(steps + 1):
            angle = start + (math.pi / 2.0) * (i / steps)
            pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return pts


def _grad_line(
    space: str,
    direction: str,
    bbox: tuple[float, float, float, float],
    plot: dict[str, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
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


def _emit_polar_grid(
    cmd: _Cmd,
    polar: _PolarProjection,
    theta_ticks: list[float],
    r_ticks: list[float],
    theta_style: dict[str, Any],
    r_style: dict[str, Any],
    default_grid: str,
    hide_theta: bool,
    hide_r: bool,
) -> None:
    """Concentric rings and radial spokes, in display-list commands.

    The rasterizer has no arc, wedge or circle opcode — its only curves are
    pre-flattened polylines — so each ring ships as a closed polyline from
    `_PolarProjection.ring`. The SVG exporter draws the same rings as exact
    `<circle>` elements; both read the same tick list, so they agree on which
    rings exist even though the curve is expressed differently.
    """
    theta_ticks = polar.filter_theta_values(theta_ticks)
    r_ticks = [value for value in r_ticks if bool(polar.visible_mask(value))]
    if not hide_r:
        for v in r_ticks:
            radius = float(polar.norm_radius(v)) * polar.radius
            if radius <= 0.0:
                continue
            ring = (
                polar.polygon_ring(v, theta_ticks)
                if polar.grid_shape == "linear"
                else polar.ring(v)
            )
            if len(ring) < 2:
                continue
            cmd.stroke(
                [*ring, ring[0]] if polar.full_sector else ring,
                float(r_style.get("grid_width", 1)),
                _parse_color(
                    _css(r_style.get("grid_color"), default_grid),
                    float(r_style.get("grid_opacity", 1.0)),
                ),
                dash=_AXIS_GRID_DASHES.get(str(r_style.get("grid_dash", "solid"))),
            )
    if hide_theta:
        return
    for v in theta_ticks:
        angle = float(polar.angle(v))
        inner = polar.inner_radius
        cmd.stroke(
            [
                (
                    polar.cx + inner * math.cos(angle),
                    polar.cy - inner * math.sin(angle),
                ),
                (
                    polar.cx + polar.radius * math.cos(angle),
                    polar.cy - polar.radius * math.sin(angle),
                ),
            ],
            float(theta_style.get("grid_width", 1)),
            _parse_color(
                _css(theta_style.get("grid_color"), default_grid),
                float(theta_style.get("grid_opacity", 1.0)),
            ),
            dash=_AXIS_GRID_DASHES.get(str(theta_style.get("grid_dash", "solid"))),
        )


def _polar_label_paint(axis: dict[str, Any], slot_paint: Any, default_text: str) -> tuple[int, ...]:
    """Axis tick_label_color/tick_color first, chart slot second.

    Mirrors `tick_color` inside `_svg._polar_tick_labels`. Without the axis
    lookup the `text=False`/`show=False` shorthands — which work by setting
    tick_label_color transparent — silently did nothing on a polar chart.
    """
    axis_style = axis.get("style") or {}
    own = _css(axis_style.get("tick_label_color", axis_style.get("tick_color")), "")
    return _parse_color(own) if own else slot_paint("tick_label", default_text)


def _emit_polar_tick_labels(
    cmd: _Cmd,
    polar: _PolarProjection,
    theta_values: list[float],
    r_values: list[float],
    theta_step: float,
    r_step: float,
    theta_axis: dict[str, Any],
    r_axis: dict[str, Any],
    theta_size: float,
    r_size: float,
    theta_color: tuple[int, ...],
    r_color: tuple[int, ...],
    hide_theta: bool,
    hide_r: bool,
) -> None:
    """Emit polar tick labels as display-list text, from the shared placement.

    Placement lives in `_svg.polar_tick_label_layout`; this is only the sink,
    so the two exporters cannot drift on rim offsets, quadrant anchors or the
    radial spoke angle.
    """
    angular, radial = polar_tick_label_layout(
        polar,
        theta_values,
        r_values,
        theta_step,
        r_step,
        theta_axis,
        r_axis,
        theta_size,
        r_size,
        hide_theta,
        hide_r,
    )
    for placed, paint in ((angular, theta_color), (radial, r_color)):
        for item in placed:
            cmd.text(
                item.x,
                item.y,
                # The layout speaks SVG's anchor vocabulary; the display list
                # calls the same thing "center".
                _TEXT_ANCHOR_CODES["center" if item.anchor == "middle" else item.anchor],
                item.size,
                paint,
                item.text,
                angle=item.spin,
            )


@_textblock.cached_measurements
def render_raster(
    spec: dict[str, Any],
    blob: bytes,
    scale: float = 2.0,
    *,
    fast_png: bool = False,
    borrowed: tuple[np.ndarray, ...] = (),
) -> np.ndarray | bytes:
    """Paint `spec` into an ``(h, w, 4)`` RGBA8 image via the native rasterizer."""
    spec = _decode_title_geometry(spec, blob)
    spec = _resolve_static_css_vars(spec)
    width, height, compact, plot = layout(spec)
    xa, ya = spec["x_axis"], spec["y_axis"]
    x_scales, y_scales, sx, sy, extra_x_axes, extra_y_axes = _axis_scales(spec, plot)
    # Polar reinterprets the same two axes: x carries theta, y carries r. The
    # projection comes from _svg so the vector and raster exports cannot drift.
    polar = (
        _PolarProjection(spec["x_axis"], spec["y_axis"], plot)
        if spec.get("coords") == "polar"
        else None
    )
    cols = spec["columns"]
    cmd = _Cmd(scale)

    dom_style = (spec.get("dom") or {}).get("style") or {}

    # Figure patch (mpl figure.facecolor): `theme(background=)` lands on the
    # root element's CSS background, painted over the whole canvas so the
    # margins match the browser. Gradients stay browser-only (skipped).
    figure_background = _solid_color(dom_style.get("background"))

    # The fused PNG path initializes its native canvas white, avoiding a second
    # full-frame memory pass. Raw RGBA callers still receive an explicit fill —
    # skipped when an opaque figure background would fully cover it anyway
    # (a translucent one keeps the white underlay to composite over, matching
    # the browser's white host page).
    if not fast_png and (figure_background is None or figure_background[3] < 255):
        cmd.fill(
            _rect_pts(0, 0, width, height),
            _parse_color(spec.get("canvas_background", "#ffffff")),
        )
    if figure_background is not None:
        cmd.fill(_rect_pts(0, 0, width, height), figure_background)

    # Static exports honor the same axes background token as HTML/SVG.  This
    # is deliberately a plot-rect fill rather than a canvas fill: the latter
    # is the Figure patch, composed above (or by pyplot's grid exporter). An
    # unset token keeps the plot rect transparent when a figure background is
    # present — matching the browser, where the root shows through — and
    # falls back to the classic white fill otherwise.
    plot_css = _css(dom_style.get("--chart-bg"), "")
    if plot_css:
        plot_background = _parse_color(plot_css)
    elif figure_background is None:
        plot_background = _parse_color("#ffffff")
    else:
        plot_background = None
    if plot_background is not None:
        cmd.fill(
            _rect_pts(plot["x"], plot["y"], plot["x"] + plot["w"], plot["y"] + plot["h"]),
            plot_background,
        )

    xt, xlab, xstep = axis_ticks(xa, plot["w"], True)
    yt, ylab, ystep = axis_ticks(ya, plot["h"], False)
    xmt, ymt = minor_axis_ticks(xa), minor_axis_ticks(ya)
    extra_x_ticks = {
        axis_id: axis_ticks(axis, plot["w"], True) for axis_id, axis, _axis_scale in extra_x_axes
    }
    extra_y_ticks = {
        axis_id: axis_ticks(axis, plot["h"], False) for axis_id, axis, _axis_scale in extra_y_axes
    }
    xstyle, ystyle = xa.get("style") or {}, ya.get("style") or {}
    xmstyle, ymstyle = xa.get("minor_style") or {}, ya.get("minor_style") or {}
    default_grid = _css(dom_style.get("--chart-grid"), _GRID)
    default_axis = _css(dom_style.get("--chart-axis"), _AXIS)
    default_text = _css(dom_style.get("--chart-text"), _TEXT)
    px0, py0 = plot["x"], plot["y"]
    px1, py1 = plot["x"] + plot["w"], plot["y"] + plot["h"]

    hide_x = xa.get("tick_label_strategy") == "none"
    hide_y = ya.get("tick_label_strategy") == "none"

    cmd.clip(px0, py0, plot["w"], plot["h"])
    if polar is not None:
        _emit_polar_grid(cmd, polar, xt, yt, xstyle, ystyle, default_grid, hide_x, hide_y)
    for v in [] if hide_x or polar is not None else xmt:
        gx = float(sx(v))
        cmd.stroke(
            [(gx, py0), (gx, py1)],
            float(xmstyle.get("grid_width", 1)),
            _parse_color(
                _css(xmstyle.get("grid_color"), "transparent"),
                float(xmstyle.get("grid_opacity", 1.0)),
            ),
            dash=_AXIS_GRID_DASHES.get(str(xmstyle.get("grid_dash", "solid"))),
        )
    for v in [] if hide_y or polar is not None else ymt:
        gy = float(sy(v))
        cmd.stroke(
            [(px0, gy), (px1, gy)],
            float(ymstyle.get("grid_width", 1)),
            _parse_color(
                _css(ymstyle.get("grid_color"), "transparent"),
                float(ymstyle.get("grid_opacity", 1.0)),
            ),
            dash=_AXIS_GRID_DASHES.get(str(ymstyle.get("grid_dash", "solid"))),
        )
    for v in [] if hide_x or polar is not None else xt:
        gx = float(sx(v))
        cmd.stroke(
            [(gx, py0), (gx, py1)],
            float(xstyle.get("grid_width", 1)),
            _parse_color(
                _css(xstyle.get("grid_color"), default_grid),
                float(xstyle.get("grid_opacity", 1.0)),
            ),
            dash=_AXIS_GRID_DASHES.get(str(xstyle.get("grid_dash", "solid"))),
        )
    for v in [] if hide_y or polar is not None else yt:
        gy = float(sy(v))
        cmd.stroke(
            [(px0, gy), (px1, gy)],
            float(ystyle.get("grid_width", 1)),
            _parse_color(
                _css(ystyle.get("grid_color"), default_grid),
                float(ystyle.get("grid_opacity", 1.0)),
            ),
            dash=_AXIS_GRID_DASHES.get(str(ystyle.get("grid_dash", "solid"))),
        )

    # Grid/frame chrome is drawn before the shaped clip. Marks then share one
    # analytic annular-sector clip in the native painter, matching SVG's
    # polar clipPath without flattening every mark at the boundary.
    if polar is not None:
        cmd.polar_clip(polar)

    spec_palette: Sequence[str] = spec.get("palette") or DEFAULT_PALETTE
    for palette_i, t in enumerate(spec["traces"]):
        style = t.get("style") or {}
        color = _css(style.get("color"), spec_palette[palette_i % len(spec_palette)])
        kind = t["kind"]
        trace_sx = x_scales.get(t.get("x_axis", "x"), sx)
        trace_sy = y_scales.get(t.get("y_axis", "y"), sy)
        if t.get("tier") == "density" and t.get("density"):
            _emit_grid(cmd, "density", t["density"], blob, cols, trace_sx, trace_sy, style)
        elif kind == "line":
            _emit_line(cmd, t, blob, cols, trace_sx, trace_sy, style, color, polar)
        elif kind in ("area", "error_band"):
            _emit_area(cmd, t, blob, cols, trace_sx, trace_sy, style, color, plot, polar)
        elif kind == "scatter":
            _emit_scatter(cmd, t, blob, cols, trace_sx, trace_sy, style, color, polar)
        elif kind == "hexbin":
            _emit_hexbin(cmd, t, blob, cols, trace_sx, trace_sy, style, color)
        elif kind in {"errorbar", "stem", "box_whisker", "box_median", "contour", "segments"}:
            _emit_segments(cmd, t, blob, cols, trace_sx, trace_sy, style, color, polar)
        elif kind in ("bar", "column") and t.get("bar"):
            _emit_bars(cmd, t, blob, cols, trace_sx, trace_sy, style, color, plot, polar)
        elif kind == "heatmap" and t.get("heatmap"):
            _emit_grid(
                cmd,
                "heatmap",
                t["heatmap"],
                blob,
                cols,
                trace_sx,
                trace_sy,
                style,
                borrowed,
                polar,
            )
        elif kind == "triangle_mesh":
            _emit_triangle_mesh(cmd, t, blob, cols, trace_sx, trace_sy, style, color)
        elif kind == "funnel":
            _emit_funnel(cmd, t, blob, cols, trace_sx, trace_sy, style, color)

        elif kind == "ribbon":
            # MUST precede the rect fall-through: a ribbon ships x0/x1/y0/y1
            # too, so a later branch would draw every band as a rectangle.
            _emit_ribbon(cmd, t, blob, cols, trace_sx, trace_sy, style, color)
        elif all(k in t for k in ("x0", "x1", "y0", "y1")):
            _emit_rects(cmd, t, blob, cols, trace_sx, trace_sy, style, color, plot, polar)

    _emit_annotations(
        cmd,
        spec.get("annotations") or [],
        sx,
        sy,
        plot,
        width,
        height,
        polar=polar,
        default_text=_css(dom_style.get("--chart-annotation-text"), "") or default_text,
    )

    # Chrome (unclipped): baselines, labels, title, legend.
    cmd.clip(0, 0, width, height)
    # Text annotations are unclipped like matplotlib Text (clip_on=False):
    # margin titles and edge labels may live outside the plot rectangle.
    _emit_annotations(
        cmd,
        spec.get("annotations") or [],
        sx,
        sy,
        plot,
        width,
        height,
        phase="text",
        default_text=_css(dom_style.get("--chart-annotation-text"), "") or default_text,
        polar=polar,
    )
    # "none" silences the whole axis chrome (sparklines); "off" hides only the
    # label text and keeps baselines and the axis title (mpl shared axes).
    frame_sides = spec.get("frame_sides")
    explicit_frame_sides = frame_sides is not None
    if frame_sides is None:
        frame_sides = [xa.get("side", "bottom"), ya.get("side", "left")]
    if polar is not None:
        # One annular-sector outline replaces the four straight spines; "side"
        # has no polar meaning, so frame_sides is deliberately not consulted.
        frame_sides = []
        explicit_frame_sides = False
        if not hide_x:
            width_ = float(xstyle.get("axis_width", 1))
            paint = _parse_color(_css(xstyle.get("axis_color"), default_axis))
            outer = polar.frame_points(xt)
            if outer:
                if polar.full_sector:
                    cmd.stroke([*outer, outer[0]], width_, paint)
                    if polar.inner_radius > 0.0:
                        inner = (
                            polar.polygon_ring(polar.r_lo, xt)
                            if polar.grid_shape == "linear"
                            else polar.ring(polar.r_lo)
                        )
                        if inner:
                            cmd.stroke([*inner, inner[0]], width_, paint)
                else:
                    inner = (
                        polar.polygon_ring(polar.r_lo, xt)
                        if polar.inner_radius > 0.0 and polar.grid_shape == "linear"
                        else polar.ring(polar.r_lo)
                        if polar.inner_radius > 0.0
                        else [(polar.cx, polar.cy)]
                    )
                    boundary = [*outer, *reversed(inner)]
                    cmd.stroke([*boundary, boundary[0]], width_, paint)
    if not hide_y or explicit_frame_sides:
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
    if not hide_x or explicit_frame_sides:
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
    for _axis_id, axis, _axis_scale in extra_x_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        edge = py0 if axis.get("side", "bottom") == "top" else py1
        cmd.stroke(
            [(px0, edge), (px1, edge)],
            float(axis_style.get("axis_width", 1)),
            _parse_color(_css(axis_style.get("axis_color"), default_axis)),
        )
    for _axis_id, axis, _axis_scale in extra_y_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        edge = px1 if axis.get("side", "right") == "right" else px0
        cmd.stroke(
            [(edge, py0), (edge, py1)],
            float(axis_style.get("axis_width", 1)),
            _parse_color(_css(axis_style.get("axis_color"), default_axis)),
        )

    def tick_span(style: dict[str, Any]) -> tuple[float, float]:
        length = max(0.0, float(style.get("tick_length", 0)))
        direction = str(style.get("tick_direction", "out"))
        if direction == "in":
            return length, 0.0
        if direction == "inout":
            return length / 2, length / 2
        return 0.0, length

    if not hide_x and polar is None:
        inward, outward = tick_span(xmstyle)
        side = xa.get("side", "bottom")
        edge = py0 if side == "top" else py1
        for value in xmt:
            x = float(sx(value))
            y0, y1 = (
                (edge - outward, edge + inward)
                if side == "top"
                else (edge - inward, edge + outward)
            )
            cmd.stroke(
                [(x, y0), (x, y1)],
                float(xmstyle.get("tick_width", 1)),
                _parse_color(_css(xmstyle.get("tick_color"), default_axis)),
            )
        inward, outward = tick_span(xstyle)
        for side in _axis_tick_sides(xa, is_x=True):
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
                    _parse_color(_css(xstyle.get("tick_color"), default_axis)),
                )
    if not hide_y and polar is None:
        inward, outward = tick_span(ymstyle)
        side = ya.get("side", "left")
        edge = px1 if side == "right" else px0
        for value in ymt:
            y = float(sy(value))
            x0, x1 = (
                (edge - inward, edge + outward)
                if side == "right"
                else (edge - outward, edge + inward)
            )
            cmd.stroke(
                [(x0, y), (x1, y)],
                float(ymstyle.get("tick_width", 1)),
                _parse_color(_css(ymstyle.get("tick_color"), default_axis)),
            )
        inward, outward = tick_span(ystyle)
        for side in _axis_tick_sides(ya, is_x=False):
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
                    _parse_color(_css(ystyle.get("tick_color"), default_axis)),
                )
    for axis_id, axis, axis_scale in extra_x_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        inward, outward = tick_span(axis_style)
        for side in _axis_tick_sides(axis, is_x=True):
            edge = py0 if side == "top" else py1
            for value in extra_x_ticks[axis_id][0]:
                x = float(axis_scale(value))
                y0, y1 = (
                    (edge - outward, edge + inward)
                    if side == "top"
                    else (edge - inward, edge + outward)
                )
                cmd.stroke(
                    [(x, y0), (x, y1)],
                    float(axis_style.get("tick_width", 1)),
                    _parse_color(_css(axis_style.get("tick_color"), default_axis)),
                )
    for axis_id, axis, axis_scale in extra_y_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        inward, outward = tick_span(axis_style)
        for side in _axis_tick_sides(axis, is_x=False):
            edge = px1 if side == "right" else px0
            for value in extra_y_ticks[axis_id][0]:
                y = float(axis_scale(value))
                x0, x1 = (
                    (edge - inward, edge + outward)
                    if side == "right"
                    else (edge - outward, edge + inward)
                )
                cmd.stroke(
                    [(x0, y), (x1, y)],
                    float(axis_style.get("tick_width", 1)),
                    _parse_color(_css(axis_style.get("tick_color"), default_axis)),
                )

    slots = slot_styles(spec)

    def slot_paint(slot: str, fallback: str) -> tuple:
        """A slot's text paint, or the writer's own default."""
        resolved = slot_text_color(slots.get(slot) or {}, "")
        return _parse_color(resolved or fallback)

    def emit_tick_labels(
        axis: dict[str, Any],
        values: list[float],
        step: float,
        axis_scale: _Scale,
        *,
        is_x: bool,
    ) -> None:
        axis_style = axis.get("style") or {}
        # The axis's own tick_label_color/tick_color is the narrower
        # selector and wins; the chart-wide slot fills in when it says nothing.
        axis_tick_paint = _css(axis_style.get("tick_label_color", axis_style.get("tick_color")), "")
        tick_color = (
            _parse_color(axis_tick_paint)
            if axis_tick_paint
            else slot_paint("tick_label", default_text)
        )
        font_size = slot_font_size(slots.get("tick_label") or {}, _axis_tick_font_size(axis))
        baseline_shift = _axis_tick_label_baseline_shift(axis)
        # An explicit tick_label_anchor (axis spec or style) overrides the
        # side-derived default, matching the browser client and SVG export.
        explicit_anchor = _tick_label_anchor(axis, axis_style, "")
        for side in _axis_tick_label_sides(axis, is_x=is_x):
            side_axis = {**axis, "side": side}
            side_items = _axis_tick_label_layout(side_axis, values, step, axis_scale, is_x)
            # Unstyled defaults reproduce the pre-`tick_label_pad` placement exactly.
            # The bottom gap is 15 here against the SVG exporter's 16: that 1 px has
            # always separated the two and is not this seam's to change.
            if is_x:
                label_offset = (
                    _axis_tick_label_offset(axis, 7.0, 0.2)
                    if side == "top"
                    else _axis_tick_label_offset(axis, 15.0, 0.8)
                )
            else:
                label_offset = _axis_tick_label_offset(axis, 8.0)
            for item in side_items:
                block = _textblock.measure(item["text"], font_size)
                if is_x:
                    row_offset = float(item["row"]) * (font_size + 4)
                    x = float(item["pos"])
                    y = (
                        py0 - label_offset - row_offset
                        if side == "top"
                        else py1 + label_offset + row_offset
                    )
                    angle = float(item["angle"])
                    if explicit_anchor:
                        anchor = _TEXT_ANCHOR_CODES[explicit_anchor]
                    elif angle == 0:
                        anchor = 1
                    elif (side == "bottom" and angle < 0) or (side == "top" and angle > 0):
                        anchor = 2
                    else:
                        anchor = 0
                else:
                    x = px1 + label_offset if side == "right" else px0 - label_offset
                    y = (
                        float(item["pos"])
                        + baseline_shift
                        - (block.line_count - 1) * block.line_step / 2.0
                    )
                    default_anchor = 0 if side == "right" else 2
                    anchor = (
                        _TEXT_ANCHOR_CODES[explicit_anchor] if explicit_anchor else default_anchor
                    )
                _emit_text_block(
                    cmd,
                    x,
                    y,
                    anchor,
                    font_size,
                    tick_color,
                    item["text"],
                    angle=float(item["angle"]),
                )

    if polar is not None:
        _emit_polar_tick_labels(
            cmd,
            polar,
            xlab,
            ylab,
            xstep,
            ystep,
            xa,
            ya,
            slot_font_size(slots.get("tick_label") or {}, _axis_tick_font_size(xa)),
            slot_font_size(slots.get("tick_label") or {}, _axis_tick_font_size(ya)),
            _polar_label_paint(xa, slot_paint, default_text),
            _polar_label_paint(ya, slot_paint, default_text),
            hide_x or xa.get("tick_label_strategy") == "off",
            hide_y or ya.get("tick_label_strategy") == "off",
        )
    else:
        emit_tick_labels(xa, xlab, xstep, sx, is_x=True)
        emit_tick_labels(ya, ylab, ystep, sy, is_x=False)
    for axis_id, axis, axis_scale in extra_x_axes:
        _ticks, tick_labels, step = extra_x_ticks[axis_id]
        emit_tick_labels(axis, tick_labels, step, axis_scale, is_x=True)
    for axis_id, axis, axis_scale in extra_y_axes:
        _ticks, tick_labels, step = extra_y_ticks[axis_id]
        emit_tick_labels(axis, tick_labels, step, axis_scale, is_x=False)
    legacy_title = spec.get("title") if not spec.get("title_options") else None
    # The width layout measured the title band at; wrapping anywhere else would
    # draw more lines than `title_room` reserved (see _svg._title_wrap_width).
    title_wrap_width = plot.get("title_wrap_width")
    if legacy_title:
        title_slot = slots.get("title") or {}
        title_italic, title_bold = _native_font_emphasis(
            {
                "font_style": title_slot.get("font-style"),
                "font_weight": title_slot.get("font-weight", 400),
            }
        )
        legacy_size = slot_font_size(title_slot, 14.0)
        legacy_block = _textblock.measure(legacy_title, legacy_size, max_width=title_wrap_width)
        # Lines run downward from the baseline, so lift the block by its trailing
        # lines: the last line keeps the historical single-line baseline. A
        # one-line title has no trailing lines and emits exactly as before.
        legacy_trailing = (legacy_block.line_count - 1) * legacy_block.line_step
        _emit_text_block(
            cmd,
            width / 2,
            plot["y"] - plot["top_axis_room"] - (10 if compact else 12) - legacy_trailing,
            1,
            legacy_size,
            slot_paint("title", default_text),
            "\n".join(legacy_block.lines),
            italic=title_italic,
            bold=title_bold,
        )
    for title_entry in [] if legacy_title else _title_entries(spec):
        title_style, title_size, title_block = _title_metrics(spec, title_entry, title_wrap_width)
        title_italic, title_bold = _native_font_emphasis(
            {
                "font_style": title_style.get("font-style"),
                # 400 = Matplotlib's `axes.titleweight: normal`; the baked
                # atlas only has a bold face, so anything >= 600 rounds up to
                # it. Mirrors the SVG/browser title default.
                "font_weight": title_style.get("font-weight", 400),
            }
        )
        trailing = (title_block.line_count - 1) * title_block.line_step
        if title_entry.get("automatic_y", True):
            title_anchor_y = plot["y"] - plot["top_axis_room"]
        else:
            title_anchor_y = plot["y"] + (1.0 - float(title_entry.get("y", 1.0))) * plot["h"]
        loc = str(title_entry.get("loc", "center"))
        title_x = {
            "left": plot["x"],
            "center": plot["x"] + plot["w"] / 2.0,
            "right": plot["x"] + plot["w"],
        }.get(loc, plot["x"] + plot["w"] / 2.0)
        _emit_text_block(
            cmd,
            title_x,
            title_anchor_y - float(title_entry.get("pad", 8.0)) - title_block.descent - trailing,
            {"left": 0, "center": 1, "right": 2}.get(loc, 1),
            title_size,
            _parse_color(slot_text_color(title_style, default_text)),
            # The wrapped lines, not the raw string: one long line inside a
            # two-line band is the clipping bug this reservation exists to stop.
            "\n".join(title_block.lines),
            italic=title_italic,
            bold=title_bold,
        )

    def emit_axis_title(axis: dict[str, Any], *, is_x: bool) -> None:
        if not axis.get("label") or _axis_tick_label_strategy(axis) == "none":
            return
        axis_style = axis.get("style") or {}
        geometry = _axis_label_geometry(axis, plot, is_x=is_x)
        anchor = {"start": 0, "middle": 1, "end": 2}[geometry["anchor"]]
        axis_title_slot = slots.get("axis_title") or {}
        italic, bold = _native_font_emphasis(
            {
                "font_style": axis_style.get("label_font_style")
                or axis_title_slot.get("font-style"),
                "font_weight": axis_style.get(
                    "label_font_weight", axis_title_slot.get("font-weight", 400)
                ),
            }
        )
        _emit_text_block(
            cmd,
            float(geometry["x"]),
            float(geometry["y"]),
            anchor,
            slot_font_size(slots.get("axis_title") or {}, float(geometry["font_size"])),
            (
                _parse_color(_css(axis_style.get("label_color"), ""))
                if _css(axis_style.get("label_color"), "")
                else slot_paint("axis_title", default_text)
            ),
            str(axis["label"]),
            angle=float(geometry["angle"]),
            italic=italic,
            bold=bold,
        )

    emit_axis_title(xa, is_x=True)
    emit_axis_title(ya, is_x=False)
    for _axis_id, axis, _axis_scale in extra_x_axes:
        emit_axis_title(axis, is_x=True)
    for _axis_id, axis, _axis_scale in extra_y_axes:
        emit_axis_title(axis, is_x=False)

    named = legend_items(spec["traces"], spec_palette)
    main_legend = spec.get("legend") or {}
    main_items = main_legend.get("items") or named
    show_main_legend = spec.get("show_legend", True) and bool(main_items)
    extra_legends = [(extra, extra.get("items") or []) for extra in spec.get("extra_legends") or []]
    legends: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    if show_main_legend:
        legends.append((main_items, main_legend))
    legends.extend((items, extra) for extra, items in extra_legends if items)
    # The browser scrolls an oversized legend. Static files cannot, so clip the
    # bounded/truncated equivalent to the plot rectangle. The exemption for an
    # anchored legend (which is placed relative to, and may sit outside, the
    # axes) is scoped per legend exactly as in `_svg.py`: one anchored legend
    # must not lift the clip off its non-anchored siblings. The clip is a
    # stateful raster command, so only emit it on a transition — an
    # all-anchored or all-unanchored figure yields the same stream as before.
    # The clip is the plot rect unioned with any polar legend gutter, which sits
    # outside it — the plot rect alone erased a polar legend. Shared with the
    # SVG clipPath via `legend_clip_rect`.
    lx, ly, lw, lh = legend_clip_rect(plot)
    clipped_to_plot = False
    for items, options in legends:
        want_clip = not options.get("anchor")
        if want_clip != clipped_to_plot:
            if want_clip:
                cmd.clip(lx, ly, lw, lh)
            else:
                cmd.clip(0, 0, width, height)
            clipped_to_plot = want_clip
        _emit_legend(
            cmd,
            items,
            plot,
            legend_options_with_slot(spec, options),
            default_text,
            spec_palette,
            slots.get("legend_label") or {},
            slots.get("legend_title") or {},
        )
    if clipped_to_plot:
        cmd.clip(0, 0, width, height)
    if spec.get("colorbar"):
        _emit_colorbar(
            cmd,
            spec["colorbar"],
            plot,
            _colorbar_right_axis_room(ya, extra_y_axes, compact),
            default_text,
            slots.get("colorbar_title") or slots.get("colorbar") or {},
            slots.get("colorbar_tick") or slots.get("colorbar") or {},
        )

    w_px, h_px = max(1, round(width * scale)), max(1, round(height * scale))
    from . import _native

    spans = (blob, *borrowed)
    # The command buffer ships as a borrowed buffer, not a `bytes` copy: the
    # ctypes seam wraps it with `np.frombuffer` and the native rasterizer only
    # reads it, so freezing it would duplicate a display list that is O(marks)
    # (megabytes on a direct-tier scatter) for nothing.
    if fast_png:
        return _native.rasterize_png_spans(cmd.buf, spans, w_px, h_px)
    return _native.rasterize_spans(cmd.buf, spans, w_px, h_px)


def _emit_line(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    if style.get("step"):
        xv, yv = _step_arrays(xv, yv, style["step"])
    c = _rgba(style.get("color"), color, _stroke_opacity(style))
    width = float(style.get("width", 1.5))
    # `render_raster` takes a plain spec dict, so a hand-built or round-tripped
    # one can carry a value `compile_mark_style` would have rejected. Fall back
    # to the documented default rather than raising a bare KeyError from inside
    # the byte packer.
    cap = str(style.get("linecap", "round"))
    cap = cap if cap in _CAP_CODES else "round"
    if polar is not None:
        # Chords between projected points (polar-axes.md §5). The smooth branch
        # is skipped outright: its Bezier control points are only exact under an
        # affine map, and `smooth_stroke` bakes that map into Rust. Vertices
        # outside the radial range split the stroke into visible runs — the
        # same cull the client shader applies. The shaped clip contains paint at
        # the boundary, but it cannot restore gap semantics after an invalid
        # data vertex has been projected through the centre.
        px, py = polar(xv, yv)
        visible = polar.position_mask(xv, yv)
        indices = np.flatnonzero(visible)
        runs = (
            [np.arange(len(xv))]
            if bool(visible.all())
            else np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
        )
        for run in runs:
            if len(run) < 2:
                continue
            points = list(zip(px[run].tolist(), py[run].tolist(), strict=True))
            cmd.stroke(points, width, c, dash=style.get("dash"), cap=cap)
    elif style.get("curve") == "smooth" and len(xv) >= 3 and affine_fast_path(sx, sy, polar):
        cmd.smooth_stroke(xv, yv, sx, sy, width, c, dash=style.get("dash"), cap=cap)
    else:
        pts = _scene.curve_points(xv, yv, sx, sy, False)
        cmd.stroke(pts, width, c, dash=style.get("dash"), cap=cap)


def _native_font_emphasis(style: dict[str, Any]) -> tuple[bool, bool]:
    """Return baked-font italic/bold approximations for an annotation."""
    italic = str(style.get("font_style", "")).lower() in {"italic", "oblique"}
    weight = str(style.get("font_weight", "")).lower()
    try:
        bold = float(weight) >= 600
    except ValueError:
        bold = weight in {"bold", "semibold", "demibold", "heavy", "black"}
    return italic, bold


def _math_italic_ranges(style: dict[str, Any]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for item in str(style.get("math_italic_ranges", "")).split(","):
        try:
            start, end = (int(value) for value in item.split(":", 1))
        except ValueError:
            continue
        if 0 <= start < end:
            ranges.append((start, end))
    return ranges


def _emit_annotations(
    cmd: _Cmd,
    annotations: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    plot: dict[str, float],
    width: float,
    height: float,
    *,
    phase: str = "marks",
    polar: "Optional[_PolarProjection]" = None,
    default_text: str = _TEXT,
) -> None:
    px0, py0 = plot["x"], plot["y"]
    text_phase = phase == "text"

    def point(x: float, y: float) -> tuple[float, float]:
        """Jointly project point-anchored geometry under polar coordinates."""
        if polar is not None:
            px, py = polar(x, y)
            return float(px), float(py)
        return float(sx(x)), float(sy(y))

    for ann in annotations:
        # Geometry (rules/bands/arrows/markers) draws in the clipped marks
        # pass; every label draws in the unclipped chrome pass, matching
        # matplotlib's Text and the client's DOM labels.
        style = ann.get("style") or {}
        restore_plot_clip = False
        color = _rgba(style.get("color"), "#667085", float(style.get("opacity", 1.0)))
        start = max(0.0, min(1.0, float(style.get("span_start", 0.0))))
        end = max(start, min(1.0, float(style.get("span_end", 1.0))))
        if text_phase:
            pass
        elif ann.get("kind") == "rule":
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
        elif ann.get("kind") in ("arrow", "callout"):
            if _annotation_connector_unclipped(ann, sx, sy, plot, polar):
                cmd.clip(0, 0, width, height)
                restore_plot_clip = True
            if ann.get("kind") == "arrow":
                x0, y0 = point(float(ann["x0"]), float(ann["y0"]))
                x1, y1 = point(float(ann["x1"]), float(ann["y1"]))
            else:  # pointer from the offset label back to the data point
                x1, y1 = point(float(ann["x"]), float(ann["y"]))
                x0, y0 = x1 + float(ann.get("dx", 0.0)), y1 + float(ann.get("dy", 0.0))
            if all(np.isfinite(v) for v in (x0, y0, x1, y1)):
                shapes = _arrow_shapes(x0, y0, x1, y1, style)
                stroke_width = max(0.5, float(style.get("width", 1.5)))
                if shapes["taper"] is not None:
                    cmd.fill(shapes["taper"], color)
                else:
                    cmd.stroke(
                        shapes["shaft"],
                        stroke_width,
                        color,
                        dash=(
                            [float(value) for value in style["dash"].split(",")]
                            if isinstance(style.get("dash"), str)
                            else style.get("dash")
                        ),
                    )
                for decoration in (shapes["head"], shapes["tail"]):
                    if decoration is None:
                        continue
                    if decoration["kind"] == "fill":
                        cmd.fill(decoration["points"], color)
                    else:
                        cmd.stroke(decoration["points"], stroke_width, color)
        elif ann.get("kind") == "marker":
            mx, my = point(float(ann["x"]), float(ann["y"]))
            if np.isfinite(mx) and np.isfinite(my):
                alpha = float(style.get("opacity", 1.0))
                stroke_w = float(style.get("stroke_width", 0.0))
                cmd.point(
                    mx,
                    my,
                    max(0.5, float(ann.get("size", 8.0)) / 2.0),
                    _SYMBOLS.get(str(ann.get("symbol", "circle")), 0),
                    _rgba(style.get("color"), "#2563eb", alpha),
                    stroke_w,
                    (
                        _rgba(style.get("stroke_color"), "#ffffff", alpha)
                        if stroke_w > 0
                        else (0, 0, 0, 0)
                    ),
                )
        if restore_plot_clip:
            cmd.clip(plot["x"], plot["y"], plot["w"], plot["h"])
            if polar is not None:
                cmd.polar_clip(polar)
        if text_phase and ann.get("text"):
            x, y, label_anchor, vertical_align = annotation_label_placement(
                ann, style, sx, sy, plot, width, height, polar
            )
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            if vertical_align:
                style = {**style, "vertical_align": vertical_align}
            anchor = {"start": 0, "middle": 1, "end": 2}.get(label_anchor, 0)
            font_size = _px_size(style.get("font_size"), 11.0)
            lines = str(ann["text"]).splitlines() or [""]
            line_height = font_size * 1.2
            # A callout's `color` paints its arrow; the label prefers its own.
            label_color = style.get("label_color") or style.get("color")
            label_opacity = style.get(
                "label_opacity",
                style.get("opacity", 1.0) if ann.get("kind") == "text" else 1.0,
            )
            color = _rgba(label_color, default_text, float(label_opacity))
            rotation = float(style.get("rotation", 0.0)) % 360.0
            italic, bold = _native_font_emphasis(style)
            math_ranges = _math_italic_ranges(style)
            line_offset = 0
            if rotation in (90.0, 270.0):
                # Vertical text via the rasterizer's rotated glyph paths.
                # matplotlib aligns the post-rotation box: vertical_align picks
                # the anchor along the reading axis, the horizontal anchor
                # shifts the baseline across it (ascent ~0.78em, descent ~0.22em).
                x += float(ann.get("dx", 0.0))
                y += float(ann.get("dy", 0.0))
                cw = rotation == 270.0
                va = str(style.get("vertical_align", ""))
                along = {"center": 1, "top": 0 if cw else 2, "bottom": 2 if cw else 0}.get(va, 0)
                ascent, descent = font_size * 0.78, font_size * 0.22
                if cw:
                    base = {0: descent, 1: (descent - ascent) / 2, 2: -ascent}[anchor]
                else:
                    base = {0: ascent, 1: (ascent - descent) / 2, 2: -descent}[anchor]
                stack = -line_height if cw else line_height  # later lines: glyph-down
                for index, line in enumerate(lines):
                    line_ranges = [
                        (max(0, start - line_offset), min(len(line), end - line_offset))
                        for start, end in math_ranges
                        if start < line_offset + len(line) and end > line_offset
                    ]
                    cmd.text(
                        x + base + index * stack,
                        y,
                        along,
                        font_size,
                        color,
                        line,
                        angle=90.0 if cw else -90.0,
                        italic=italic,
                        bold=bold,
                        italic_ranges=line_ranges,
                    )
                    line_offset += len(line) + 1
                continue
            vertical_align = style.get("vertical_align")
            text_x = x + float(ann.get("dx", 0.0))
            text_y = _annotation_first_baseline(
                y + float(ann.get("dy", 0.0)),
                len(lines),
                line_height,
                font_size,
                vertical_align,
            )
            _emit_text_box(cmd, style, lines, text_x, text_y, line_height, font_size, anchor)
            for index, line in enumerate(lines):
                line_ranges = [
                    (max(0, start - line_offset), min(len(line), end - line_offset))
                    for start, end in math_ranges
                    if start < line_offset + len(line) and end > line_offset
                ]
                cmd.text(
                    text_x,
                    text_y + index * line_height,
                    anchor,
                    font_size,
                    color,
                    line,
                    angle=-rotation,
                    italic=italic,
                    bold=bold,
                    italic_ranges=line_ranges,
                )
                line_offset += len(line) + 1


def _emit_text_box(
    cmd: _Cmd,
    style: dict[str, Any],
    lines: list[str],
    x: float,
    first_y: float,
    line_height: float,
    font_size: float,
    anchor: int,
) -> None:
    """Draw the bounded CSS approximation used by pyplot ``text(bbox=)``."""
    background = style.get("background")
    border = str(style.get("border", ""))
    if background is None and not border:
        return
    pad_parts = str(style.get("padding", "0")).split()

    def px(value: str) -> float:
        try:
            return max(0.0, float(value.removesuffix("px")))
        except ValueError:
            return 0.0

    pad_y = px(pad_parts[0]) if pad_parts else 0.0
    pad_x = px(pad_parts[1]) if len(pad_parts) > 1 else pad_y
    text_width = _estimated_text_width(lines, font_size)
    left = x - (text_width / 2 if anchor == 1 else text_width if anchor == 2 else 0.0) - pad_x
    top = first_y - font_size * 0.8 - pad_y
    right = left + text_width + pad_x * 2
    bottom = top + font_size + (len(lines) - 1) * line_height + pad_y * 2
    # `boxstyle="round"`/`round4` set border_radius, which the browser applies
    # as CSS border-radius; round the same corners here or the exported box is
    # square where the live one is not.
    points = _round_rect_pts(
        left, top, right, bottom, _box_corner_radius(style, right - left, bottom - top)
    )
    if background is not None:
        cmd.fill(points, _parse_color(str(background)))
    if border:
        parts = border.split()
        try:
            width = max(0.0, float(parts[0].removesuffix("px")))
        except (IndexError, ValueError):
            width = 1.0
        if width:
            cmd.stroke(points + [points[0]], width, _parse_color(parts[-1]))


def _emit_area(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    plot: dict[str, float],
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    xv = _column(blob, cols[t["x"]])
    yv = _column(blob, cols[t["y"]])
    bv = _column(blob, cols[t["base"]])
    smooth = style.get("curve") == "smooth"
    if polar is not None:
        # Chord-bounded polygon (polar-axes.md §5); smoothing is skipped because
        # its control points are only exact under an affine map. Radii clamp to
        # the radial range — the fill at each theta is [base, top] ∩
        # [r_lo, r_hi], and a base below r_lo would otherwise mirror through
        # the centre (mirrors the SVG area branch and AREA_VS). Vertices
        # outside the theta sector (or NaN) are CULLED, splitting the fill
        # into visible runs — the SVG path applies position_mask inside
        # _curve_path and the client NaN-culls in the shader; painting them
        # here drew chords across the sector boundary and let NaN reach the
        # display list (§19).
        radial_min, radial_max = sorted((polar.r_lo, polar.r_hi))
        top_r = np.clip(yv, radial_min, radial_max)
        base_r = np.clip(bv, radial_min, radial_max)
        visible = polar.position_mask(xv, top_r) & polar.position_mask(xv, base_r)
        if bool(visible.all()):
            runs = [np.arange(len(xv))]
        else:
            indices = np.flatnonzero(visible)
            runs = (
                []
                if indices.size == 0
                else np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
            )
        pieces = []
        for run in runs:
            if len(run) < 2:
                continue
            run_top = np.column_stack(polar(xv[run], top_r[run]))
            run_base = np.column_stack(polar(xv[run][::-1], base_r[run][::-1]))
            pieces.append((run_top, run_base))
    else:
        top = _scene.curve_points(xv, yv, sx, sy, smooth)
        base = _scene.curve_points(xv[::-1], bv[::-1], sx, sy, smooth)
        pieces = [(top, base)]
    op = _fill_opacity(style, 0.35)
    fill_spec = style.get("fill")
    for top, base in pieces:
        poly = np.vstack([top, base])
        if isinstance(fill_spec, dict):
            xs, ys = poly[:, 0], poly[:, 1]
            bbox = (xs.min(), ys.min(), xs.max() - xs.min(), ys.max() - ys.min())
            g0, g1 = _grad_line(
                fill_spec.get("space", "mark"), fill_spec.get("dir", "down"), bbox, plot
            )
            stops = [
                (o, (c[0], c[1], c[2], int(c[3] * op))) for o, c in _grad_stops(fill_spec, color)
            ]
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


def _trace_paint_rgba(
    trace: dict[str, Any],
    key: str,
    n: int,
    fallback: str,
    read: _paint.ColumnReader,
) -> np.ndarray:
    """Resolve one payload paint channel to intrinsic float RGBA."""
    channel = trace.get(key) or {}
    direct = _paint.direct_rgba(channel, n, read)
    if direct is not None:
        return direct
    rgba = np.empty((n, 4), dtype=np.float64)
    rgba[:, 3] = 1.0
    mode = channel.get("mode")
    if mode == "continuous":
        rgba[:, :3] = _lut(channel.get("colormap", "viridis"), read(channel["buf"])[:n]) / 255.0
    elif mode == "categorical":
        codes = np.asarray(read(channel["buf"]), dtype=np.int64)[:n]
        palette = channel.get("palette") or DEFAULT_PALETTE
        # Per-index resolution (channels.palette_rows_rgba8), not _parse_color
        # per entry: browser-only entries (var(--…)) must degrade to DISTINCT
        # built-in colors — parsing each alone collapsed every var() category
        # onto the same fallback, so a PNG painted two stages one color while
        # SVG/PDF kept them apart.
        from . import channels as _pal_channels

        table = _pal_channels.palette_rows_rgba8(palette, len(palette)).astype(np.float64) / 255.0
        rgba[:] = table[codes % len(table)]
    else:
        rgba[:] = (
            np.asarray(_parse_color(_css(channel.get("color"), fallback)), dtype=np.float64) / 255.0
        )
    return rgba


def _emit_authored_scatter(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    """Paint bounded pyplot-authored paths/glyphs in display-list space."""
    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    px, py = polar(xv, yv) if polar is not None else (sx(xv), sy(yv))
    # Out-of-range radii are culled like the client shader culls them. The
    # shaped clip contains glyph extent at the boundary, but a below-range
    # position itself mirrors into the visible annulus and must still be
    # rejected before projection.
    visible = polar.position_mask(xv, yv) if polar is not None else None
    n = len(xv)
    if not n:
        return

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    face = _trace_paint_rgba(t, "color", n, color, read)
    fills = np.rint(
        _paint.effective_rgba(face, t, read, component="fill", default_opacity=0.8) * 255.0
    ).astype(np.uint8)
    if (t.get("stroke") or {}).get("mode") == "match_fill":
        stroke_intrinsic = face
    elif t.get("stroke") is not None:
        stroke_intrinsic = _trace_paint_rgba(t, "stroke", n, color, read)
    elif style.get("stroke") is not None:
        stroke_intrinsic = np.tile(
            np.asarray(
                _parse_color(_css(style.get("stroke"), color)),
                dtype=np.float64,
            )
            / 255.0,
            (n, 1),
        )
    else:
        stroke_intrinsic = face
    strokes = np.rint(
        _paint.effective_rgba(
            stroke_intrinsic,
            t,
            read,
            component="stroke",
            default_opacity=0.8,
        )
        * 255.0
    ).astype(np.uint8)
    size_ch = t.get("size") or {}
    if size_ch.get("mode") == "continuous":
        values = _column(blob, cols[size_ch["buf"]])
        r0, r1 = size_ch.get("range_px", [2, 18])
        radii = (r0 + (r1 - r0) * np.clip(values, 0, 1)) / 2
    else:
        radii = np.full(n, float(size_ch.get("size", 4.0)) / 2)
    widths = _paint.style_values(t, "stroke_width", n, read, float(style.get("stroke_width", 0)))
    marker_path = style.get("marker_path")
    marker_glyph = style.get("marker_glyph")
    filled = bool(marker_path and marker_path.get("filled", True))

    for index in range(n):
        if visible is not None and not visible[index]:
            continue
        fill = tuple(int(value) for value in fills[index])
        stroke = tuple(int(value) for value in strokes[index])
        diameter = max(0.0, 2 * (float(radii[index]) - float(widths[index]) / 2))
        if marker_glyph:
            cmd.text(
                float(px[index]),
                float(py[index]) + diameter * 0.34,
                1,
                diameter,
                fill,
                str(marker_glyph),
            )
            continue
        if not marker_path:
            continue
        contours = []
        for contour in marker_path.get("contours") or ():
            values = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
            contours.append(
                [
                    (
                        float(px[index]) + diameter * float(x),
                        float(py[index]) - diameter * float(y),
                    )
                    for x, y in values
                ]
            )
        if filled:
            for points in contours:
                cmd.fill(points, fill)
            if float(widths[index]) > 0:
                for points in contours:
                    cmd.stroke(points, float(widths[index]), stroke, closed=True)
        else:
            width = max(1.0, float(widths[index]))
            for points in contours:
                cmd.stroke(points, width, fill)


def _emit_scatter(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    ch = t.get("color") or {}
    size_ch = t.get("size") or {}
    if style.get("marker_path") or style.get("marker_glyph"):
        _emit_authored_scatter(cmd, t, blob, cols, sx, sy, style, color, polar)
        return

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    fill_op = _fill_opacity(style, 0.8)
    stroke_op = _stroke_opacity(style, 0.8)
    artist_alpha = style.get("artist_alpha")
    if artist_alpha is not None:
        # Matplotlib artist alpha replaces the intrinsic paint alpha. Scalar
        # alpha does not need a style channel, so retain it in both affine
        # scatter fast paths instead of silently painting opaque points.
        scalar_alpha = float(artist_alpha)
        fill_op *= scalar_alpha
        stroke_op *= scalar_alpha
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
        affine_fast_path(sx, sy, polar)
        and not t.get("channels")
        and (t.get("stroke") is None or t["stroke"].get("mode") == "match_fill")
        and (color_mode in {"continuous", "categorical"} or size_mode == "continuous")
    ):
        paint = _parse_color(_css(ch.get("color"), color))
        alpha = max(0, min(255, int(round(fill_op * paint[3]))))
        cmd.affine_channel_points(
            cols[t["x"]],
            cols[t["y"]],
            sx,
            sy,
            ch,
            size_ch,
            (paint[0], paint[1], paint[2], alpha),
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
        affine_fast_path(sx, sy, polar)
        and ch.get("mode") not in {"continuous", "categorical", "direct_rgba"}
        and size_ch.get("mode") != "continuous"
        and not t.get("channels")
        and (t.get("stroke") is None or t["stroke"].get("mode") == "match_fill")
    ):
        paint = _parse_color(_css(ch.get("color"), color))
        alpha = max(0, min(255, int(round(fill_op * paint[3]))))
        fill = (paint[0], paint[1], paint[2], alpha)
        radius = float(size_ch.get("size", 4.0)) / 2
        cmd.affine_points(cols[t["x"]], cols[t["y"]], sx, sy, radius, fill, sym, sw, stroke)
        return

    xv, yv = _column(blob, cols[t["x"]]), _column(blob, cols[t["y"]])
    px, py = polar(xv, yv) if polar is not None else (sx(xv), sy(yv))
    n = len(xv)
    if n == 0:
        return
    face_intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    fills = np.rint(
        _paint.effective_rgba(face_intrinsic, t, read, component="fill", default_opacity=0.8)
        * 255.0
    ).astype(np.uint8)

    if size_ch.get("mode") == "continuous":
        sv = _column(blob, cols[size_ch["buf"]])
        r0, r1 = size_ch.get("range_px", [2, 18])
        radii = (r0 + (r1 - r0) * np.clip(sv, 0, 1)) / 2
    else:
        radii = np.full(n, float(size_ch.get("size", 4.0)) / 2)

    widths = _paint.style_values(t, "stroke_width", n, read, sw)
    symbol_channel = (t.get("channels") or {}).get("symbol")
    symbols = (
        np.asarray(read(symbol_channel["buf"]), dtype=np.uint8)[:n]
        if symbol_channel is not None
        else np.full(n, sym, dtype=np.uint8)
    )
    if (t.get("stroke") or {}).get("mode") == "match_fill":
        stroke_intrinsic = face_intrinsic
    elif t.get("stroke") is not None:
        stroke_intrinsic = _trace_paint_rgba(t, "stroke", n, color, read)
    elif style.get("stroke") is not None:
        stroke_intrinsic = np.tile(
            np.asarray(_parse_color(_css(style.get("stroke"), color)), dtype=np.float64) / 255.0,
            (n, 1),
        )
    else:
        stroke_intrinsic = face_intrinsic
    strokes = np.rint(
        _paint.effective_rgba(stroke_intrinsic, t, read, component="stroke", default_opacity=0.8)
        * 255.0
    ).astype(np.uint8)
    if polar is not None:
        # Cull out-of-range radii the way the client shader does: below r_lo a
        # sprite mirrors through the centre. The shaped clip contains glyph
        # extent at valid boundaries, but cannot distinguish that mirrored
        # invalid position from an honest in-range one.
        visible = polar.position_mask(xv, yv)
        if not bool(visible.all()):
            px, py, radii, fills = px[visible], py[visible], radii[visible], fills[visible]
            symbols, widths, strokes = symbols[visible], widths[visible], strokes[visible]
            n = len(px)
            if n == 0:
                return
    if (
        np.all(widths == widths[0])
        and np.all(symbols == symbols[0])
        and np.all(strokes == strokes[0])
    ):
        cmd.points(
            px,
            py,
            radii,
            fills,
            int(symbols[0]),
            float(widths[0]),
            tuple(int(value) for value in strokes[0]),
        )
    else:
        for index in range(n):
            cmd.points(
                px[index : index + 1],
                py[index : index + 1],
                radii[index : index + 1],
                fills[index : index + 1],
                int(symbols[index]),
                float(widths[index]),
                tuple(int(value) for value in strokes[index]),
            )


def _emit_segments(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    x0 = _column(blob, cols[t["x0"]])
    x1 = _column(blob, cols[t["x1"]])
    y0 = _column(blob, cols[t["y0"]])
    y1 = _column(blob, cols[t["y1"]])

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    n = len(x0)
    intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    colors = np.rint(
        _paint.effective_rgba(intrinsic, t, read, component="stroke", default_opacity=1.0) * 255.0
    ).astype(np.uint8)
    widths = _paint.style_values(t, "width", n, read, float(style.get("width", 1.2)))
    if polar is None:
        px0, py0, px1, py1 = sx(x0), sy(y0), sx(x1), sy(y1)
    else:
        c0 = np.asarray(polar.r_scale.coord(y0), dtype=np.float64)
        c1 = np.asarray(polar.r_scale.coord(y1), dtype=np.float64)
        lo = min(polar.r_lo_coord, polar.r_hi_coord)
        hi = max(polar.r_lo_coord, polar.r_hi_coord)
        keep = (
            np.isfinite(x0)
            & np.isfinite(x1)
            & np.isfinite(c0)
            & np.isfinite(c1)
            & (np.maximum(c0, c1) >= lo)
            & (np.minimum(c0, c1) <= hi)
        )
        dr = c1 - c0
        ta = np.zeros(n, dtype=np.float64)
        tb = np.ones(n, dtype=np.float64)
        moving = np.abs(dr) > 1e-30
        ta[moving] = (lo - c0[moving]) / dr[moving]
        tb[moving] = (hi - c0[moving]) / dr[moving]
        t0 = np.maximum(0.0, np.minimum(ta, tb))
        t1 = np.minimum(1.0, np.maximum(ta, tb))
        clipped_x0 = x0 + (x1 - x0) * t0
        clipped_x1 = x0 + (x1 - x0) * t1
        clipped_c0 = np.clip(c0 + dr * t0, lo, hi)
        clipped_c1 = np.clip(c0 + dr * t1, lo, hi)
        keep &= polar.theta_visible_mask(clipped_x0)
        keep &= polar.theta_visible_mask(clipped_x1)
        clipped_y0 = polar.r_scale.value(clipped_c0)
        clipped_y1 = polar.r_scale.value(clipped_c1)
        px0, py0 = polar(clipped_x0[keep], clipped_y0[keep])
        px1, py1 = polar(clipped_x1[keep], clipped_y1[keep])
        colors = colors[keep]
        widths = widths[keep]
        n = len(widths)
    if n == 0:
        return
    dash = style.get("dash")
    if dash:
        # The batched segments primitive cannot dash; fall back to one dashed
        # stroke per segment (contour negative-level convention, few segments).
        dash_pattern = (
            [float(value) for value in dash.split(",")] if isinstance(dash, str) else list(dash)
        )
        for index in range(n):
            cmd.stroke(
                [(float(px0[index]), float(py0[index])), (float(px1[index]), float(py1[index]))],
                float(widths[index]),
                tuple(int(v) for v in colors[index]),
                dash=dash_pattern,
            )
        return
    if np.all(widths == widths[0]):
        cmd.segments(px0, py0, px1, py1, float(widths[0]), colors)
    else:
        for index in range(n):
            cmd.stroke(
                [
                    (float(px0[index]), float(py0[index])),
                    (float(px1[index]), float(py1[index])),
                ],
                float(widths[index]),
                tuple(int(value) for value in colors[index]),
            )


def _mesh_fill_rgba(
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    n: int,
    style: dict[str, Any],
    color: str,
) -> np.ndarray:
    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    return np.rint(
        _paint.effective_rgba(intrinsic, t, read, component="fill", default_opacity=1.0) * 255.0
    ).astype(np.uint8)


def _emit_hexbin(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
) -> None:
    """Expand shipped cell centers into the six-triangle hexagon fan locally
    (the payload carries centers only — see _payload._emit_hexbin)."""
    cx = _column(blob, cols[t["x"]])
    cy = _column(blob, cols[t["y"]])
    n = min(len(cx), len(cy))
    ring_x, ring_y = hexbin_ring(style)
    ring_x, ring_y = np.append(ring_x, ring_x[0]), np.append(ring_y, ring_y[0])
    x0 = np.repeat(sx(cx[:n]), 6)
    y0 = np.repeat(sy(cy[:n]), 6)
    x1 = np.asarray(sx(cx[:n, None] + ring_x[None, :-1]), dtype=np.float64).reshape(-1)
    y1 = np.asarray(sy(cy[:n, None] + ring_y[None, :-1]), dtype=np.float64).reshape(-1)
    x2 = np.asarray(sx(cx[:n, None] + ring_x[None, 1:]), dtype=np.float64).reshape(-1)
    y2 = np.asarray(sy(cy[:n, None] + ring_y[None, 1:]), dtype=np.float64).reshape(-1)
    fills = np.repeat(_mesh_fill_rgba(t, blob, cols, n, style, color), 6, axis=0)
    cmd.triangles(x0, y0, x1, y1, x2, y2, fills, 0.0, (0, 0, 0, 0))


def _emit_funnel(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
) -> None:
    """Funnel segments: one flat-filled 4-corner polygon per stage.

    Geometry comes from `_scene.funnel_quad` — the same reference the SVG
    exporter and the golden test consume — built from the **axis-mapped**
    edges, so the straight edges live in transformed space exactly like the
    client's mesh triangles (the ribbon rule, minus the cubic).
    """
    pos0 = _column(blob, cols[t["pos0"]])
    pos1 = _column(blob, cols[t["pos1"]])
    lo0 = _column(blob, cols[t["lo0"]])
    hi0 = _column(blob, cols[t["hi0"]])
    lo1 = _column(blob, cols[t["lo1"]])
    hi1 = _column(blob, cols[t["hi1"]])
    horizontal = t.get("orientation") == "horizontal"
    spos, scross = (sx, sy) if horizontal else (sy, sx)
    n = min(len(pos0), len(pos1), len(lo0), len(hi0), len(lo1), len(hi1))

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    fills = np.rint(
        _paint.effective_rgba(intrinsic, t, read, component="fill", default_opacity=1.0) * 255.0
    ).astype(np.uint8)
    stroke_width = float(style.get("stroke_width", 0.0) or 0.0)
    stroke_op = _stroke_opacity(style)
    stroke_c = (
        _rgba(style.get("stroke"), color, stroke_op)
        if stroke_width > 0 and style.get("stroke") is not None
        else None
    )
    # An omitted stroke colour matches each segment's own fill
    # (edgecolors="face"), resolved per stage like the ribbon's per-band rule.
    edges = (
        np.rint(
            np.column_stack([intrinsic[:, :3] * 255.0, intrinsic[:, 3] * stroke_op * 255.0])
        ).astype(np.uint8)
        if stroke_width > 0 and style.get("stroke") is None
        else None
    )
    for i in range(n):
        mapped = (
            float(spos(pos0[i])),
            float(spos(pos1[i])),
            float(scross(lo0[i])),
            float(scross(hi0[i])),
            float(scross(lo1[i])),
            float(scross(hi1[i])),
        )
        if not all(math.isfinite(v) for v in mapped):
            continue
        quad = _scene.funnel_quad(*mapped, horizontal)
        poly = list(zip(quad[:, 0].tolist(), quad[:, 1].tolist(), strict=True))
        cmd.fill(poly, tuple(int(v) for v in fills[i]))
        edge_c = (
            stroke_c
            if stroke_c is not None
            else (tuple(int(v) for v in edges[i]) if edges is not None else None)
        )
        if edge_c is not None:
            cmd.stroke([*poly, poly[0]], stroke_width, edge_c)


def _emit_ribbon(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
) -> None:
    """Flow bands, flattened, with the gradient running along the flow.

    Geometry comes from `_scene.ribbon_polygon` — the same reference the SVG
    exporter's cubics and the golden test consume — so the two static outputs
    cannot drift. The polygon is built from the **axis-mapped** endpoints, not
    mapped after flattening: the ribbon cubic is normative in transformed space
    (ribbon geometry contract), which is the only curve the SVG exporter's
    exact pixel-space `C` and the client's clip-space sweep can both draw —
    flattening in data space and mapping each vertex bows a different curve on
    log/symlog axes. Under affine axes the two orders are the same curve.
    `cmd.grad` takes an arbitrary two-point gradient vector, which is what lets
    the ramp follow the flow rather than an axis.
    """
    x0v = _column(blob, cols[t["x0"]])
    x1v = _column(blob, cols[t["x1"]])
    slo = _column(blob, cols[t["y0"]])
    shi = _column(blob, cols[t["y1"]])
    tlo = _column(blob, cols[t["target_y0"]])
    thi = _column(blob, cols[t["target_y1"]])
    n = len(x0v)

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    source_rgba = _trace_paint_rgba(t, "color", n, color, read)
    fills = np.rint(
        _paint.effective_rgba(source_rgba, t, read, component="fill", default_opacity=1.0) * 255.0
    ).astype(np.uint8)
    if t.get("color_target"):
        target_rgba = _trace_paint_rgba(t, "color_target", n, color, read)
        fills2 = np.rint(
            _paint.effective_rgba(target_rgba, t, read, component="fill", default_opacity=1.0)
            * 255.0
        ).astype(np.uint8)
    else:
        fills2 = fills
    stroke_width = float(style.get("stroke_width", 0.0) or 0.0)
    # Outline alpha folds opacity * stroke_opacity, the same stack every other
    # stroked mark applies and the SVG writer's stroke-opacity mirrors. An
    # omitted stroke colour matches each band's own fill (edgecolors="face"),
    # resolved per band in the loop rather than once for the whole trace.
    stroke_op = _stroke_opacity(style)
    stroke_c = (
        _rgba(style.get("stroke"), color, stroke_op)
        if stroke_width > 0 and style.get("stroke") is not None
        else None
    )
    edges = (
        np.rint(
            np.column_stack([source_rgba[:, :3] * 255.0, source_rgba[:, 3] * stroke_op * 255.0])
        ).astype(np.uint8)
        if stroke_width > 0 and style.get("stroke") is None
        else None
    )

    for i in range(n):
        px0, px1 = float(sx(x0v[i])), float(sx(x1v[i]))
        py_slo, py_shi = float(sy(slo[i])), float(sy(shi[i]))
        py_tlo, py_thi = float(sy(tlo[i])), float(sy(thi[i]))
        if not all(math.isfinite(v) for v in (px0, px1, py_slo, py_shi, py_tlo, py_thi)):
            continue
        poly_data = _scene.ribbon_polygon(px0, px1, py_slo, py_shi, py_tlo, py_thi)
        poly = list(zip(poly_data[:, 0].tolist(), poly_data[:, 1].tolist(), strict=True))
        # effective_rgba already folded the trace opacity into the alpha.
        a = tuple(int(v) for v in fills[i])
        b = tuple(int(v) for v in fills2[i])
        # Flat only when all FOUR channels agree: ends differing in alpha
        # alone still ramp, and cmd.grad's RGBA stops interpolate it.
        if a == b:
            cmd.fill(poly, a)
        else:
            # Gradient vector spans the two faces horizontally; the y term is
            # irrelevant because the ramp is purely along the flow.
            gy = float(poly_data[0, 1])
            cmd.grad(poly, (px0, gy), (px1, gy), [(0.0, a), (1.0, b)])
        edge_c = (
            stroke_c
            if stroke_c is not None
            else (tuple(int(v) for v in edges[i]) if edges is not None else None)
        )
        if edge_c is not None:
            cmd.stroke([*poly, poly[0]], stroke_width, edge_c)


def _emit_triangle_mesh(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
) -> None:
    vertices = [_column(blob, cols[t[name]]) for name in ("x0", "y0", "x1", "y1", "x2", "y2")]
    n = min(len(values) for values in vertices)

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    fills = _mesh_fill_rgba(t, blob, cols, n, style, color)

    x0, y0, x1, y1, x2, y2 = vertices
    widths = _paint.style_values(t, "stroke_width", n, read, float(style.get("stroke_width", 0.0)))
    if (t.get("stroke") or {}).get("mode") == "match_fill":
        stroke_intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    elif t.get("stroke") is not None:
        stroke_intrinsic = _trace_paint_rgba(t, "stroke", n, color, read)
    elif style.get("stroke") is not None:
        stroke_intrinsic = np.tile(
            np.asarray(_parse_color(_css(style.get("stroke"), color)), dtype=np.float64) / 255.0,
            (n, 1),
        )
    else:
        stroke_intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    strokes = np.rint(
        _paint.effective_rgba(stroke_intrinsic, t, read, component="stroke", default_opacity=1.0)
        * 255.0
    ).astype(np.uint8)
    projected = (sx(x0[:n]), sy(y0[:n]), sx(x1[:n]), sy(y1[:n]), sx(x2[:n]), sy(y2[:n]))
    if n == 0:
        return
    if style.get("joined_fill") and np.all(fills == fills[0]) and np.all(widths == 0.0):
        boundary = _paint.triangle_mesh_boundary(x0, y0, x1, y1, x2, y2)
        if boundary is not None:
            cmd.fill(
                list(zip(sx(boundary[:, 0]), sy(boundary[:, 1]), strict=True)),
                tuple(int(value) for value in fills[0]),
            )
            return
    if np.all(widths == widths[0]) and np.all(strokes == strokes[0]):
        cmd.triangles(
            *projected,
            fills,
            float(widths[0]),
            tuple(int(value) for value in strokes[0]),
        )
    else:
        for index in range(n):
            cmd.triangles(
                projected[0][index : index + 1],
                projected[1][index : index + 1],
                projected[2][index : index + 1],
                projected[3][index : index + 1],
                projected[4][index : index + 1],
                projected[5][index : index + 1],
                fills[index : index + 1],
                float(widths[index]),
                tuple(int(value) for value in strokes[index]),
            )


def _bar_geom(
    cmd: _Cmd,
    x: float,
    y: float,
    w: float,
    h: float,
    style: dict[str, Any],
    fill_cmd: Callable[[list[tuple[float, float]]], None],
    stroke_c: tuple[int, ...],
    sw: float,
    tip_top: bool,
) -> None:
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


def _polar_wedge_fill(
    cmd: _Cmd,
    style: dict[str, Any],
    color: str,
    plot: dict[str, float],
    fills: np.ndarray,
) -> Callable[[list[tuple[float, float]], int], None]:
    """Paint one flattened wedge, honoring a gradient `fill=` like the cartesian
    path does.

    The polar branches used to call `cmd.fill(poly, flat)` unconditionally, so a
    gradient reached the SVG (`fill="url(#g3)"`) and the browser but came out
    flat in the PNG — a three-way divergence with the raster the odd one out.
    Per-item colors still win when there is no gradient, since each wedge in a
    pie carries its own.
    """
    if isinstance(style.get("fill"), dict):
        grad_only, _stroke_c, _sw = _fill_maker(cmd, style, color, plot)

        def paint(poly: list[tuple[float, float]], index: int) -> None:
            grad_only(poly)
    else:

        def paint(poly: list[tuple[float, float]], index: int) -> None:
            cmd.fill(poly, tuple(int(value) for value in fills[index]))

    return paint


def _fill_maker(
    cmd: _Cmd,
    style: dict[str, Any],
    color: str,
    plot: dict[str, float],
) -> tuple[Callable[[list[tuple[float, float]]], None], tuple[int, ...], float]:
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

        def fill_cmd(poly: list[tuple[float, float]]) -> None:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            g0, g1 = _grad_line(
                fill_spec.get("space", "mark"), fill_spec.get("dir", "down"), bbox, plot
            )
            cmd.grad(poly, g0, g1, stops)
    else:
        flat = _rgba(style.get("color"), color, fill_op)

        def fill_cmd(poly: list[tuple[float, float]]) -> None:
            cmd.fill(poly, flat)

    return fill_cmd, stroke_c, sw


def _rect_style_arrays(
    trace: dict[str, Any],
    n: int,
    fallback: str,
    read: _paint.ColumnReader,
    default_opacity: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Resolve batched rectangle paint, stroke width, and radii."""
    face = _trace_paint_rgba(trace, "color", n, fallback, read)
    fills = np.rint(
        _paint.effective_rgba(face, trace, read, component="fill", default_opacity=default_opacity)
        * 255.0
    ).astype(np.uint8)
    style = trace.get("style") or {}
    if (trace.get("stroke") or {}).get("mode") == "match_fill":
        stroke_face = face
    elif trace.get("stroke") is not None:
        stroke_face = _trace_paint_rgba(trace, "stroke", n, fallback, read)
    elif style.get("stroke") is not None:
        stroke_face = np.tile(
            np.asarray(_parse_color(_css(style.get("stroke"), fallback)), dtype=np.float64) / 255.0,
            (n, 1),
        )
    else:
        stroke_face = face
    strokes = np.rint(
        _paint.effective_rgba(
            stroke_face, trace, read, component="stroke", default_opacity=default_opacity
        )
        * 255.0
    ).astype(np.uint8)
    widths = _paint.style_values(
        trace, "stroke_width", n, read, float(style.get("stroke_width", 0.0))
    )
    radii = _paint.style_matrix(trace, "corner_radius", n, read)
    if radii is None:
        tip, base = _corner_radii(style)
        radii = np.tile(np.asarray([[tip, base]], dtype=np.float64), (n, 1))
    return fills, strokes, widths, radii


def _emit_bars(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    plot: dict[str, float],
    polar: "Optional[_PolarProjection]" = None,
) -> None:
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

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    fills, strokes, widths, radii = _rect_style_arrays(t, len(pos), color, read, 0.85)
    if polar is not None:
        # Annular sectors, flattened: the display list has no arc opcode, so the
        # same wedge the SVG exporter draws with `A` ships as a polygon here.
        paint = _polar_wedge_fill(cmd, style, color, plot, fills)
        for i in range(len(pos)):
            poly = polar_wedge_points(
                polar,
                float(pos[i]) - half,
                float(pos[i]) + half,
                float(min(v0[i], v1[i])),
                float(max(v0[i], v1[i])),
                corner_radius=float(np.max(radii[i])) if len(radii) else 0.0,
                wedge_gap=float(style.get("wedge_gap", 0.0) or 0.0),
            )
            if len(poly) < 3:
                continue
            paint(poly, i)
            if widths[i] > 0:
                cmd.stroke(
                    [*poly, poly[0]],
                    float(widths[i]),
                    tuple(int(v) for v in strokes[i]),
                )
        return
    if not isinstance(style.get("fill"), dict) and not np.any(radii) and not np.any(widths):
        if horizontal:
            xa, xb = sx(np.minimum(v0, v1)), sx(np.maximum(v0, v1))
            ya, yb = sy(pos + half), sy(pos - half)
        else:
            xa, xb = sx(pos - half), sx(pos + half)
            ya, yb = sy(np.maximum(v0, v1)), sy(np.minimum(v0, v1))
        x0, x1 = np.minimum(xa, xb), np.maximum(xa, xb)
        y0, y1 = np.minimum(ya, yb), np.maximum(ya, yb)
        cmd.rects(x0, y0, x1, y1, fills)
        return
    if not isinstance(style.get("fill"), dict):
        for i in range(len(pos)):
            if horizontal:
                x0, x1 = float(sx(min(v0[i], v1[i]))), float(sx(max(v0[i], v1[i])))
                y0, y1 = float(sy(pos[i] + half)), float(sy(pos[i] - half))
                tip_top = True
            else:
                x0, x1 = float(sx(pos[i] - half)), float(sx(pos[i] + half))
                y0, y1 = float(sy(max(v0[i], v1[i]))), float(sy(min(v0[i], v1[i])))
                tip_top = bool(v1[i] >= v0[i])
            item_style = dict(style)
            item_style["corner_radius"] = (
                float(radii[i, 0])
                if radii.shape[1] == 1
                else [float(radii[i, 0]), float(radii[i, 1])]
            )

            def fill_item(poly: list[tuple[float, float]], index: int = i) -> None:
                cmd.fill(poly, tuple(int(value) for value in fills[index]))

            _bar_geom(
                cmd,
                min(x0, x1),
                min(y0, y1),
                abs(x1 - x0),
                abs(y1 - y0),
                item_style,
                fill_item,
                tuple(int(value) for value in strokes[i]),
                float(widths[i]),
                tip_top,
            )
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


def _emit_rects(
    cmd: _Cmd,
    t: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    color: str,
    plot: dict[str, float],
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    x0v, x1v = _column(blob, cols[t["x0"]]), _column(blob, cols[t["x1"]])
    y0v, y1v = _column(blob, cols[t["y0"]]), _column(blob, cols[t["y1"]])

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    fills, strokes, widths, radii = _rect_style_arrays(t, len(x0v), color, read, 0.85)
    if polar is not None:
        # Four edge columns are an annular sector, flattened (no arc opcode).
        # This is the path unequal-width slices — a pie or donut — take.
        paint = _polar_wedge_fill(cmd, style, color, plot, fills)
        for i in range(len(x0v)):
            poly = polar_wedge_points(
                polar,
                float(x0v[i]),
                float(x1v[i]),
                float(min(y0v[i], y1v[i])),
                float(max(y0v[i], y1v[i])),
                corner_radius=float(np.max(radii[i])) if len(radii) else 0.0,
                wedge_gap=float(style.get("wedge_gap", 0.0) or 0.0),
            )
            if len(poly) < 3:
                continue
            paint(poly, i)
            if widths[i] > 0:
                cmd.stroke([*poly, poly[0]], float(widths[i]), tuple(int(v) for v in strokes[i]))
        return
    if not isinstance(style.get("fill"), dict) and not np.any(radii) and not np.any(widths):
        xa, xb = sx(x0v), sx(x1v)
        ya, yb = sy(y0v), sy(y1v)
        cmd.rects(
            np.minimum(xa, xb),
            np.minimum(ya, yb),
            np.maximum(xa, xb),
            np.maximum(ya, yb),
            fills,
        )
        return
    if not isinstance(style.get("fill"), dict):
        for i in range(len(x0v)):
            xa_, xb = float(sx(x0v[i])), float(sx(x1v[i]))
            ya_, yb = float(sy(y0v[i])), float(sy(y1v[i]))
            item_style = dict(style)
            item_style["corner_radius"] = (
                float(radii[i, 0])
                if radii.shape[1] == 1
                else [float(radii[i, 0]), float(radii[i, 1])]
            )

            def fill_item(poly: list[tuple[float, float]], index: int = i) -> None:
                cmd.fill(poly, tuple(int(value) for value in fills[index]))

            _bar_geom(
                cmd,
                min(xa_, xb),
                min(ya_, yb),
                abs(xb - xa_),
                abs(yb - ya_),
                item_style,
                fill_item,
                tuple(int(value) for value in strokes[i]),
                float(widths[i]),
                bool(y1v[i] >= y0v[i]),
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


def _emit_grid(
    cmd: _Cmd,
    kind: str,
    g: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    sx: _Scale,
    sy: _Scale,
    style: dict[str, Any],
    borrowed: tuple[np.ndarray, ...] = (),
    polar: "Optional[_PolarProjection]" = None,
) -> None:
    if kind == "heatmap":
        if polar is not None:
            rgba = np.ascontiguousarray(
                polar_heatmap_rgba(
                    g,
                    blob,
                    cols,
                    style,
                    polar,
                    borrowed,
                    output_scale=cmd.s,
                )
            )
            out_h, out_w = rgba.shape[:2]
            plot = polar.plot
            cmd.image(
                plot["x"],
                plot["y"],
                plot["w"],
                plot["h"],
                out_w,
                out_h,
                rgba.tobytes(),
                nearest=True,
            )
            return
        w, h = int(g["w"]), int(g["h"])
        if not (sx.affine and sy.affine):
            # Heatmap cells are uniform in *data* space, but the native image
            # ops stretch linearly across the dest rect — on a nonlinear axis
            # the grid must first be resampled to scale coordinates (the same
            # `_svg.warp_grid_rgba` the SVG exporter uses). Density grids are
            # already scale-coordinate-uniform (§28) and skip this.
            xr, yr = g["x_range"], g["y_range"]
            rgba = warp_grid_rgba(
                _heatmap_rgba_grid(g, blob, cols, style, borrowed), xr, yr, sx, sy
            )
            oh, ow = rgba.shape[:2]
            dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
            cmd.image(
                dx, dy, dw, dh, ow, oh, np.ascontiguousarray(rgba[::-1]).tobytes(), nearest=True
            )
            return
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
        xr, yr = g["x_range"], g["y_range"]
        dx, dy, dw, dh = _scene.grid_dest_rect(xr, yr, sx, sy)
        if g.get("rgba") is not None:
            # Mean point color per cell (LOD doc §2): rgb from the shipped
            # plane; displayed alpha is the PHYSICAL compositing of the
            # cell's points (`_svg._physical_density_alpha` — the same law
            # as _svg._density_image and the client's texture upload).
            # Precomposed here and emitted as a plain image op; the
            # count→LUT density op cannot express per-cell color.
            rgba_meta = cols[g["rgba"]]
            mean = np.frombuffer(
                blob, dtype=np.uint8, count=rgba_meta["len"], offset=rgba_meta["byte_offset"]
            ).reshape(h, w, 4)
            counts = _density_column(blob, meta, g).reshape(h, w)
            alpha = _physical_density_alpha(counts, mean[..., 3], _fill_opacity(style, 0.85))
            rgba = np.ascontiguousarray(np.dstack([mean[..., :3], alpha])[::-1])
            cmd.image(dx, dy, dw, dh, w, h, rgba.tobytes(), nearest=False)
            return
        paint_alpha = 1.0
        if g.get("color") is not None:
            red, green, blue, alpha = _parse_color(g["color"])
            stops = np.asarray([(red, green, blue), (red, green, blue)], dtype=np.uint8)
            paint_alpha = alpha / 255.0
        else:
            stops = np.asarray(_colormap_stops(g.get("colormap", "viridis")), dtype=np.uint8)
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


def _emit_legend(
    cmd: _Cmd,
    named: list[dict[str, Any]],
    plot: dict[str, float],
    options: dict[str, Any],
    text_color: str = _TEXT,
    palette: Sequence[str] = DEFAULT_PALETTE,
    label_slot: Optional[dict[str, Any]] = None,
    title_slot: Optional[dict[str, Any]] = None,
) -> None:
    label_slot = label_slot or {}
    title_slot = title_slot or {}
    legend = _legend_layout(named, plot, options)
    if not legend["visible_count"]:
        # A plot too short for even one entry: no floating frame/title either.
        return
    style_opts = legend["style"]
    pad, handle, gap = legend["pad"], legend["handle"], legend["gap"]
    line_h, ncols = legend["line_h"], legend["ncols"]
    swatch_h = legend["swatch_h"]
    title, title_h = legend["title"], legend["title_h"]
    font_size, text_h = legend["font_size"], legend["text_h"]
    column_offsets = legend["column_offsets"]
    box_w, box_h = legend["box_w"], legend["box_h"]
    x, y = legend["x"], legend["y"]
    # frameon=False (background transparent) drops the box entirely (§ mpl parity).
    if style_opts.get("background") != "transparent":
        radius = 4.0 if style_opts.get("borderRadius") else 0.0
        frame_points = _round_rect_pts(x, y, x + box_w, y + box_h, radius)
        if style_opts.get("boxShadow"):
            shadow_points = _round_rect_pts(x + 2, y + 2, x + box_w + 2, y + box_h + 2, radius)
            cmd.fill(shadow_points, (0, 0, 0, 55))
        # An explicit background is a paint, not a tint — see the matching note
        # in `_svg._legend`; the two writers must agree.
        frame_alpha = style_opts.get("--xy-legend-frame-alpha")
        if frame_alpha is not None:
            alpha = float(frame_alpha)
        else:
            alpha = 0.08 if style_opts.get("background") is None else 1.0
        background = style_opts.get("background")
        frame = (
            _rgba(background, "#808080", alpha)
            if background
            else (128, 128, 128, round(255 * alpha))
        )
        cmd.fill(frame_points, frame)
        border = _rgba(style_opts.get("borderColor"), "#cccccc", alpha)
        # closed=True: the point list omits a repeated start point. Without it,
        # the final edge is silently dropped for both square and rounded frames.
        cmd.stroke(frame_points, 1.0, border, closed=True)
    if title:
        cmd.text(
            x + box_w / 2,
            y + pad / 2 + font_size * 0.82,
            1,
            slot_font_size(title_slot, font_size),
            _parse_color(slot_text_color(title_slot, text_color)),
            str(title),
        )
    for i, t in enumerate(named[: legend["visible_count"]]):
        style = t.get("style") or {}
        color_str = _css(
            style.get("color") or (t.get("color") or {}).get("color"),
            palette[i % len(palette)],
        )
        c = _parse_color(color_str)
        col, row = i % ncols, i // ncols
        rx, ry = x + column_offsets[col], y + pad / 2 + title_h + row * line_h
        hx0, hx1, cy = rx, rx + handle, ry + text_h / 2
        kind = t.get("kind")
        if kind == "scatter":
            _emit_legend_marker(cmd, style, (hx0 + hx1) / 2, cy, color_str)
        elif kind in _LEGEND_LINE_KINDS:
            width = float(style.get("width", 1.5))
            gap_color = style.get("legend_gap_color")
            if gap_color is not None and style.get("dash"):
                cmd.stroke(
                    [(hx0, cy), (hx1, cy)],
                    width,
                    _parse_color(_css(gap_color, color_str)),
                )
            cmd.stroke(
                [(hx0, cy), (hx1, cy)],
                width,
                c,
                dash=style.get("dash"),
            )
            marker = style.get("legend_marker")
            if isinstance(marker, dict):
                _emit_legend_marker(cmd, marker, (hx0 + hx1) / 2, cy, color_str)
        else:
            swatch_points = _rect_pts(hx0, cy - swatch_h / 2, hx1, cy + swatch_h / 2)
            cmd.fill(swatch_points, c)
            stroke_width = max(0.0, float(style.get("stroke_width", 0.0)))
            if style.get("stroke") is not None and stroke_width > 0.0:
                cmd.stroke(
                    swatch_points,
                    stroke_width,
                    _rgba(style.get("stroke"), color_str),
                    closed=True,
                )
            hatch = style.get("hatch")
            if hatch:
                _emit_legend_hatch(
                    cmd,
                    hx0,
                    hx1,
                    cy - swatch_h / 2,
                    cy + swatch_h / 2,
                    str(hatch),
                    _parse_color(_css(style.get("hatch_color"), "#222222")),
                )
        cmd.text(
            hx1 + gap,
            ry + font_size * 0.82,
            0,
            slot_font_size(label_slot, font_size),
            _parse_color(slot_text_color(label_slot, text_color)),
            legend["names"][i],
        )


def _emit_legend_marker(
    cmd: _Cmd,
    style: dict[str, Any],
    x: float,
    y: float,
    default_color: str,
) -> None:
    """Render one Matplotlib marker centered on its legend line sample."""
    symbol = str(style.get("symbol", "circle"))
    sym = _SYMBOLS.get(symbol, 0)
    marker_path = style.get("marker_path")
    marker_glyph = style.get("marker_glyph")
    color_str = _css(style.get("color"), default_color)
    color = _parse_color(color_str)
    sw = float(style.get("stroke_width", 0.0))
    if (
        symbol in {"plus_line", "x_line", "horizontal_line", "vertical_line"}
        or (marker_path and not bool(marker_path.get("filled", True)))
    ) and sw <= 0:
        sw = 1.0
    stroke = _rgba(style.get("stroke"), color_str) if sw > 0 else (0, 0, 0, 0)
    radius = max(0.5, float(style.get("size", 8.0)) / 2.0)
    if marker_glyph:
        cmd.text(x, y + radius * 0.68, 1, 2 * radius, color, str(marker_glyph))
    elif marker_path:
        for contour in marker_path.get("contours") or ():
            values = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
            points = [(x + 2 * radius * float(px), y - 2 * radius * float(py)) for px, py in values]
            if bool(marker_path.get("filled", True)):
                cmd.fill(points, color)
                if sw > 0:
                    cmd.stroke(points, sw, stroke if stroke[3] else color, closed=True)
            else:
                cmd.stroke(points, max(1.0, sw), color)
    else:
        cmd.point(x, y, radius, sym, color, sw, stroke)


def _emit_legend_hatch(
    cmd: _Cmd,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    hatch: str,
    color: tuple[int, int, int, int],
) -> None:
    mid_y = (y0 + y1) / 2
    if "-" in hatch:
        cmd.stroke([(x0, mid_y), (x1, mid_y)], 1.0, color)
    for char, direction in (("/", 1), ("\\", -1)):
        count = min(3, hatch.count(char))
        for index in range(count):
            center = x0 + (index + 1) * (x1 - x0) / (count + 1)
            half = min((x1 - x0) / 4, (y1 - y0) / 2)
            cmd.stroke(
                [
                    (center - half, mid_y + direction * half),
                    (center + half, mid_y - direction * half),
                ],
                1.0,
                color,
            )
    if "." in hatch:
        for fraction in (0.3, 0.7):
            x = x0 + fraction * (x1 - x0)
            cmd.point(
                x,
                mid_y,
                min(1.1, (y1 - y0) * 0.09),
                _SYMBOLS["circle"],
                color,
                0.0,
                (0, 0, 0, 0),
            )
    if "*" in hatch:
        center = (x0 + x1) / 2
        cmd.point(
            center,
            mid_y,
            min(x1 - x0, y1 - y0) * 0.28,
            _SYMBOLS["star"],
            color,
            0.0,
            (0, 0, 0, 0),
        )


def _emit_colorbar(
    cmd: _Cmd,
    options: dict[str, Any],
    plot: dict[str, float],
    right_axis_room: float = 0.0,
    text_color: str = _TEXT,
    title_slot: Optional[dict[str, Any]] = None,
    tick_slot: Optional[dict[str, Any]] = None,
) -> None:
    title_slot = title_slot or {}
    tick_slot = tick_slot or {}
    title_size = slot_font_size(title_slot, COLORBAR_FONT_SIZE)
    title_paint = _parse_color(slot_text_color(title_slot, text_color))
    tick_size = slot_font_size(tick_slot, COLORBAR_FONT_SIZE)
    tick_paint = _parse_color(slot_text_color(tick_slot, text_color))
    from ._svg import _colorbar_tick_target, _fmt_log, _linear_ticks, _log_ticks, _lut

    orientation = options.get("orientation", "vertical")
    shrink = float(options.get("shrink", 1.0))
    anchor = options.get("anchor") or [0.5, 0.5]
    placement = options.get("placement")
    if placement == "axes":
        x, y, width, height = plot["x"], plot["y"], plot["w"], plot["h"]
    elif orientation == "horizontal":
        width = plot["w"] * shrink
        x = plot["x"] + (plot["w"] - width) * float(anchor[0])
        gap = (
            float(options["pad"]) * plot["h"]
            if options.get("pad") is not None
            else (plot["bottom_axis_room"] or 10)
        )
        y = plot["y"] + plot["h"] + gap
        height = 18
    else:
        # right_axis_room shifts the whole colorbar clear of right-side named
        # y-axis chrome (layout() reserves room for both additively).
        gap = float(options["pad"]) * plot["w"] if options.get("pad") is not None else 24.0
        x = plot["x"] + plot["w"] + right_axis_room + gap
        height = plot["h"] * shrink
        y = plot["y"] + (plot["h"] - height) * (1.0 - float(anchor[1]))
        width = 18
    # A discrete (resampled) colormap paints N solid bands; otherwise a smooth
    # 64-step gradient approximates the continuous ramp.
    levels = options.get("levels")
    if levels and int(levels) >= 1:
        n_seg = int(levels)
        exact_colors = options.get("band_colors")
        colors = (
            np.asarray(exact_colors, dtype=np.uint8)
            if isinstance(exact_colors, list) and len(exact_colors) == n_seg
            else _lut(
                options.get("colormap", "viridis"),
                (np.arange(n_seg, dtype=np.float64) + 0.5) / n_seg,
            )
        )
    else:
        n_seg = 64
        colors = _lut(options.get("colormap", "viridis"), np.linspace(0.0, 1.0, n_seg))
    fractions = np.linspace(0.0, 1.0, n_seg + 1)
    boundaries = np.asarray(options.get("boundaries", []), dtype=np.float64).reshape(-1)
    if (
        levels
        and options.get("spacing") == "proportional"
        and len(boundaries) == n_seg + 1
        and np.isfinite(boundaries).all()
        and boundaries[-1] > boundaries[0]
        and np.all(np.diff(boundaries) > 0.0)
    ):
        fractions = (boundaries - boundaries[0]) / (boundaries[-1] - boundaries[0])
    line_only = bool(options.get("line_only"))
    if line_only:
        outline = _rect_pts(x, y, x + width, y + height)
        cmd.fill(outline, (255, 255, 255, 255))
        cmd.stroke([*outline, outline[0]], 1.0, _parse_color(text_color))
    else:
        for index, color in enumerate(colors):
            lower, upper = float(fractions[index]), float(fractions[index + 1])
            if orientation == "horizontal":
                x0, x1 = x + width * lower, x + width * upper
                cmd.fill(_rect_pts(x0, y, x1 + 0.5, y + height), (*map(int, color), 255))
            else:
                y0 = y + height * (1.0 - upper)
                y1 = y + height * (1.0 - lower)
                cmd.fill(_rect_pts(x, y0, x + width, y1 + 0.5), (*map(int, color), 255))
    domain = options.get("domain", [0.0, 1.0])
    lo, hi = float(domain[0]), float(domain[1])
    log_scale = options.get("scale") == "log"

    def fraction(value: float) -> float:
        if log_scale:
            return np.log(value / lo) / np.log(hi / lo) if hi != lo else 0.0
        return (value - lo) / ((hi - lo) or 1.0)

    def automatic_ticks(length: float) -> list[float]:
        target = _colorbar_tick_target(length)
        return (
            _log_ticks(lo, hi, target)[1] if log_scale else _linear_ticks(lo, hi, target)[0]
        ) or [lo, hi]

    format_tick = _fmt_log if log_scale else lambda value: f"{value:g}"
    ticks = options.get("ticks")
    supplied_labels = options.get("tick_labels")
    tick_label_map = (
        {float(cast(Any, value)): str(supplied_labels[index]) for index, value in enumerate(ticks)}
        if isinstance(ticks, list)
        and isinstance(supplied_labels, list)
        and len(ticks) == len(supplied_labels)
        else {}
    )

    def tick_text(value: float) -> str:
        return tick_label_map.get(float(value), format_tick(value))

    extend = options.get("extend")
    if extend in ("max", "both"):
        color = (
            (255, 255, 255, 255)
            if line_only
            else (*map(int, options.get("over_color", colors[-1])), 255)
        )
        if orientation == "horizontal":
            pts = [(x + width, y), (x + width, y + height), (x + width + 9, y + height / 2)]
        else:
            pts = [(x, y), (x + width, y), (x + width / 2, y - 9)]
        cmd.fill(pts, color)
        if line_only:
            cmd.stroke([*pts, pts[0]], 1.0, _parse_color(text_color))
    if extend in ("min", "both"):
        color = (
            (255, 255, 255, 255)
            if line_only
            else (*map(int, options.get("under_color", colors[0])), 255)
        )
        if orientation == "horizontal":
            pts = [(x, y), (x, y + height), (x - 9, y + height / 2)]
        else:
            pts = [(x, y + height), (x + width, y + height), (x + width / 2, y + height + 9)]
        cmd.fill(pts, color)
        if line_only:
            cmd.stroke([*pts, pts[0]], 1.0, _parse_color(text_color))
    for line in options.get("lines") or []:
        value = float(line.get("value", np.nan))
        if not np.isfinite(value) or value < min(lo, hi) or value > max(lo, hi):
            continue
        line_fraction = fraction(value)
        color = _parse_color(str(line.get("color") or text_color))
        line_width = max(0.5, float(line.get("width", 1.0)))
        dash = [3.7 * line_width, 1.6 * line_width] if line.get("dash") == "dashed" else None
        if orientation == "horizontal":
            position = x + width * line_fraction
            cmd.stroke([(position, y), (position, y + height)], line_width, color, dash=dash)
        else:
            position = y + height * (1.0 - line_fraction)
            cmd.stroke([(x, position), (x + width, position)], line_width, color, dash=dash)
    if orientation == "horizontal":
        h_positions = (
            [float(value) for value in ticks if lo <= float(value) <= hi]
            if ticks is not None
            else automatic_ticks(width)
        )
        if options.get("minor_ticks") and len(h_positions) >= 2:
            ordered = sorted(set(h_positions))
            for left, right in pairwise(ordered):
                for step in range(1, 5):
                    value = (
                        10 ** (np.log10(left) + (np.log10(right) - np.log10(left)) * step / 5.0)
                        if log_scale
                        else left + (right - left) * step / 5.0
                    )
                    tx = x + width * fraction(value)
                    cmd.stroke(
                        [(tx, y + height), (tx, y + height + 3)],
                        1,
                        _parse_color(text_color),
                    )
        for value in h_positions:
            cmd.text(
                x + width * fraction(value),
                y + height + 13,
                1,
                tick_size,
                tick_paint,
                tick_text(value),
            )
        if options.get("label"):
            cmd.text(
                x + width / 2,
                y + height + 26,
                1,
                title_size,
                title_paint,
                str(options["label"]),
            )
    else:
        tick_positions = (
            [float(value) for value in ticks if lo <= float(value) <= hi]
            if ticks is not None
            else automatic_ticks(height)
        )
        if options.get("minor_ticks") and len(tick_positions) >= 2:
            ordered = sorted(set(tick_positions))
            for lower, upper in pairwise(ordered):
                for step in range(1, 5):
                    value = (
                        10 ** (np.log10(lower) + (np.log10(upper) - np.log10(lower)) * step / 5.0)
                        if log_scale
                        else lower + (upper - lower) * step / 5.0
                    )
                    ty = y + height * (1 - fraction(value))
                    cmd.stroke(
                        [(x + width, ty), (x + width + 3, ty)],
                        1,
                        _parse_color(text_color),
                    )
        for value in tick_positions:
            cmd.text(
                x + width + 4,
                y + height * (1 - fraction(value)) + 4,
                0,
                tick_size,
                tick_paint,
                tick_text(value),
            )
        # Matplotlib rotates a vertical colorbar's label 90° CCW and centers it
        # alongside the bar, outboard of the tick labels. The native glyph
        # protocol rotates in quarter turns (_TEXT_ROT_CCW), so 90° is exact
        # here; the upright-glyph limitation applies only to arbitrary angles.
        # A horizontal label above the bar instead sat at `plot.y - 5`, where
        # the glyph ascent overflowed the canvas top edge and was clipped. The
        # baseline matches the SVG exporter's `x + width + 38` so both static
        # paths agree, inside the room layout() already reserves for a label.
        if options.get("label"):
            cmd.text(
                x + width + 38,
                y + height / 2,
                1 | _TEXT_ROT_CCW,
                title_size,
                title_paint,
                str(options["label"]),
            )


def _export_payload(
    fig: Any,
    width: Optional[int],
    height: Optional[int],
    background: Optional[str],
) -> tuple[dict[str, Any], bytes, tuple[np.ndarray, ...]]:
    """Build the raster payload with export-time size/background overrides."""
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
    spec = _resolve_auto_legend_locations(
        fig,
        spec,
        blob,
        width=width,
        height=height,
    )
    apply_export_background(spec, background)
    return spec, blob, borrowed


def to_rgba(
    fig: Any,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    background: Optional[str] = None,
) -> np.ndarray:
    """Render `fig` to an ``(h, w, 4)`` RGBA8 array (no encode).

    The shared pixel source for every native raster format: PNG keeps its
    fused Rust encode path in `to_png`, while JPEG/WebP export encodes this
    array. `background` overrides the figure canvas color ("transparent"
    yields alpha-0 pixels outside the plot rect)."""
    spec, blob, borrowed = _export_payload(fig, width, height, background)
    rendered = render_raster(spec, blob, float(scale), borrowed=borrowed)
    assert isinstance(rendered, np.ndarray)  # fast_png=False never returns bytes
    return rendered


def to_png(
    fig: Any,
    path: Optional[str | PathLike[str]] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    fast: bool = False,
    background: Optional[str] = None,
) -> bytes:
    """Render `fig` to PNG bytes with the native rasterizer (no browser)."""
    # The fused Rust PNG path initializes an opaque white canvas, so any
    # non-default background must take the raw-RGBA encode branch.
    fast = fast and background is None
    spec, blob, borrowed = _export_payload(fig, width, height, background)
    rendered = render_raster(spec, blob, float(scale), fast_png=fast, borrowed=borrowed)
    data = rendered if isinstance(rendered, bytes) else _png.encode(rendered)
    if path is not None:
        with open(path, "wb") as f:
            f.write(data)
    return data
