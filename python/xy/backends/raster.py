"""XY-owned raster consumer for :mod:`xy.backends.display_list`.

This module translates the public JSON IR into the existing native XY command
stream.  It does not import or instantiate a Matplotlib, Agg, Cairo, or browser
renderer.
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from collections.abc import Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np

from xy import _native, _png
from xy._raster import _Cmd

from .display_list import (
    DisplayListError,
    marker_path,
    marker_positions,
    path_collection_items,
    path_collection_paths,
    quad_mesh_items,
    text_font,
    text_glyph_path,
)

if TYPE_CHECKING:
    from .display_list import DisplayList

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _rgba8(color: Any, opacity: float = 1.0) -> tuple[int, int, int, int]:
    if color is None:
        return 0, 0, 0, 0
    channels = [min(1.0, max(0.0, float(value))) for value in color]
    if len(channels) == 3:
        channels.append(1.0)
    if len(channels) != 4:
        raise DisplayListError("raster colors must contain RGB or RGBA channels")
    channels[3] *= min(1.0, max(0.0, float(opacity)))
    return (
        int(round(channels[0] * 255)),
        int(round(channels[1] * 255)),
        int(round(channels[2] * 255)),
        int(round(channels[3] * 255)),
    )


def _curve_steps(points: Sequence[tuple[float, float]]) -> int:
    length = sum(math.dist(start, end) for start, end in pairwise(points))
    return max(4, min(64, int(math.ceil(length / 2))))


def _flatten_path(
    segments: list[list[Any]],
    *,
    canvas_height: float,
    offset: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[list[tuple[float, float]], bool]]:
    """Flatten SVG-shaped path segments into top-left device-space contours."""
    contours: list[tuple[list[tuple[float, float]], bool]] = []
    points: list[tuple[float, float]] = []
    current: tuple[float, float] | None = None
    start: tuple[float, float] | None = None
    closed = False
    dx, dy = offset

    def device_point(x: Any, y: Any) -> tuple[float, float]:
        return float(x) + dx, canvas_height - (float(y) + dy)

    def finish() -> None:
        nonlocal points, current, start, closed
        if points:
            contours.append((points, closed))
        points = []
        current = None
        start = None
        closed = False

    for segment in segments:
        if not segment:
            continue
        code = segment[0]
        values = segment[1:]
        if code == "M" and len(values) == 2:
            finish()
            point = device_point(values[0], values[1])
            current = point
            start = point
            points = [point]
        elif code == "L" and len(values) == 2:
            if current is None:
                point = device_point(values[0], values[1])
                current = point
                start = point
                points = [point]
            else:
                current = device_point(values[0], values[1])
                points.append(current)
        elif code == "Q" and len(values) == 4:
            if current is None:
                raise DisplayListError("quadratic path segment has no current point")
            control = device_point(values[0], values[1])
            end = device_point(values[2], values[3])
            begin = current
            steps = _curve_steps((begin, control, end))
            for index in range(1, steps + 1):
                t = index / steps
                inverse = 1 - t
                points.append(
                    (
                        inverse * inverse * begin[0]
                        + 2 * inverse * t * control[0]
                        + t * t * end[0],
                        inverse * inverse * begin[1]
                        + 2 * inverse * t * control[1]
                        + t * t * end[1],
                    )
                )
            current = end
        elif code == "C" and len(values) == 6:
            if current is None:
                raise DisplayListError("cubic path segment has no current point")
            control1 = device_point(values[0], values[1])
            control2 = device_point(values[2], values[3])
            end = device_point(values[4], values[5])
            begin = current
            steps = _curve_steps((begin, control1, control2, end))
            for index in range(1, steps + 1):
                t = index / steps
                inverse = 1 - t
                points.append(
                    (
                        inverse**3 * begin[0]
                        + 3 * inverse * inverse * t * control1[0]
                        + 3 * inverse * t * t * control2[0]
                        + t**3 * end[0],
                        inverse**3 * begin[1]
                        + 3 * inverse * inverse * t * control1[1]
                        + 3 * inverse * t * t * control2[1]
                        + t**3 * end[1],
                    )
                )
            current = end
        elif code == "Z":
            if points:
                closed = True
                current = start
        else:
            raise DisplayListError(f"invalid raster path segment {segment!r}")
    finish()
    return contours


def _crisp_rectilinear_path(
    segments: list[list[Any]],
    *,
    scale: float,
    offset: tuple[float, float],
) -> list[list[Any]]:
    """Assign every pixel centre in an edge-less rectangle to one cell.

    Matplotlib sends flat ``pcolor`` and ``pcolormesh`` cells with
    ``antialiased=False``.  The native polygon filler normally computes
    subpixel coverage, which is desirable for general paths but leaves a
    partially transparent hairline when neighboring cells are composited one
    at a time.  Snap only closed, axis-aligned quadrilaterals to half-open
    device-pixel boundaries; arbitrary polygons retain normal coverage.
    """
    points: list[tuple[float, float]] = []
    closed = False
    for segment in segments:
        if not segment:
            continue
        if segment[0] in {"M", "L"} and len(segment) == 3:
            points.append((float(segment[1]), float(segment[2])))
        elif segment[0] == "Z":
            closed = True
        else:
            return segments
    if len(points) == 5 and points[-1] == points[0]:
        points.pop()
    if not closed or len(points) != 4:
        return segments
    tolerance = 1e-9
    if not all(
        abs(start[0] - end[0]) <= tolerance or abs(start[1] - end[1]) <= tolerance
        for start, end in zip(points, points[1:] + points[:1], strict=True)
    ):
        return segments

    dx, dy = offset

    def snap(value: float, shift: float) -> float:
        # Pixel centres are n + 0.5 in the scaled raster.  The first centre on
        # or beyond an edge is ceil(edge - 0.5), so shared coordinates become
        # identical, gap-free integer boundaries.
        scaled = round((value + shift) * scale - 0.5, 9)
        return math.ceil(scaled) / scale - shift

    snapped = [(snap(x, dx), snap(y, dy)) for x, y in points]
    return [
        ["M", *snapped[0]],
        ["L", *snapped[1]],
        ["L", *snapped[2]],
        ["L", *snapped[3]],
        ["Z"],
    ]


def _coverage_mask(
    contours: list[tuple[list[tuple[float, float]], bool]],
    *,
    x0: float,
    y0: float,
    pixel_width: int,
    pixel_height: int,
    scale: float,
) -> np.ndarray:
    """Return antialiased nonzero-winding coverage for a device-space path."""
    rings = [points for points, _closed in contours if len(points) >= 3]
    if not rings or pixel_width <= 0 or pixel_height <= 0:
        return np.zeros((pixel_height, pixel_width), dtype=np.float32)

    supersample = 2
    sample_width = pixel_width * supersample
    sample_height = pixel_height * supersample
    x_samples = x0 + (np.arange(sample_width) + 0.5) / (scale * supersample)
    coverage = np.zeros((sample_height, sample_width), dtype=np.uint8)
    edges = [
        (start, end)
        for ring in rings
        for start, end in zip(ring, ring[1:] + ring[:1], strict=True)
        if start[1] != end[1]
    ]
    for row in range(sample_height):
        y = y0 + (row + 0.5) / (scale * supersample)
        events: list[tuple[float, int]] = []
        for (x_start, y_start), (x_end, y_end) in edges:
            if y_start <= y < y_end:
                direction = 1
            elif y_end <= y < y_start:
                direction = -1
            else:
                continue
            intersection = x_start + (y - y_start) * (x_end - x_start) / (y_end - y_start)
            events.append((intersection, direction))
        if not events:
            continue
        events.sort(key=lambda item: item[0])
        intersections = np.asarray([item[0] for item in events], dtype=float)
        winding = np.cumsum([item[1] for item in events], dtype=np.int32)
        positions = np.searchsorted(intersections, x_samples, side="right") - 1
        inside = positions >= 0
        inside[inside] = winding[positions[inside]] != 0
        coverage[row] = inside
    return coverage.reshape(pixel_height, supersample, pixel_width, supersample).mean(
        axis=(1, 3), dtype=np.float32
    )


def _source_over(destination: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Composite straight-alpha RGBA8 ``source`` over ``destination``."""
    destination_float = destination.astype(np.float32) / 255
    source_float = source.astype(np.float32) / 255
    destination_alpha = destination_float[:, :, 3:4]
    source_alpha = source_float[:, :, 3:4]
    output_alpha = source_alpha + destination_alpha * (1 - source_alpha)
    premultiplied = source_float[:, :, :3] * source_alpha + destination_float[
        :, :, :3
    ] * destination_alpha * (1 - source_alpha)
    output = np.zeros_like(destination_float)
    np.divide(
        premultiplied,
        output_alpha,
        out=output[:, :, :3],
        where=output_alpha > 0,
    )
    output[:, :, 3:4] = output_alpha
    return np.rint(np.clip(output, 0, 1) * 255).astype(np.uint8)


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _decode_rgba_png(resource: dict[str, Any]) -> np.ndarray:
    """Decode the non-interlaced RGBA8 PNG resources emitted by RendererXY."""
    try:
        encoded = base64.b64decode(resource["data"], validate=True)
    except (KeyError, ValueError) as exc:
        raise DisplayListError("image resource contains invalid base64") from exc
    if not encoded.startswith(_PNG_SIGNATURE):
        raise DisplayListError("image resource is not a PNG")
    offset = len(_PNG_SIGNATURE)
    idat = bytearray()
    width = height = None
    while offset + 12 <= len(encoded):
        length = struct.unpack_from(">I", encoded, offset)[0]
        offset += 4
        chunk_type = encoded[offset : offset + 4]
        offset += 4
        end = offset + length
        if end + 4 > len(encoded):
            raise DisplayListError("truncated PNG resource")
        payload = encoded[offset:end]
        expected_crc = struct.unpack_from(">I", encoded, end)[0]
        actual_crc = zlib.crc32(payload, zlib.crc32(chunk_type))
        if actual_crc != expected_crc:
            raise DisplayListError("PNG resource has an invalid chunk checksum")
        offset = end + 4
        if chunk_type == b"IHDR":
            if len(payload) != 13:
                raise DisplayListError("invalid PNG IHDR")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise DisplayListError(
                    "raster consumer requires non-interlaced RGBA8 PNG resources"
                )
        elif chunk_type == b"IDAT":
            idat.extend(payload)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or not idat:
        raise DisplayListError("PNG resource is missing IHDR or IDAT")
    try:
        filtered = zlib.decompress(idat)
    except zlib.error as exc:
        raise DisplayListError("PNG resource has invalid compressed data") from exc
    stride = width * 4
    if len(filtered) != height * (stride + 1):
        raise DisplayListError("PNG resource has an unexpected decoded size")
    output = np.empty((height, stride), dtype=np.uint8)
    source = memoryview(filtered)
    for row in range(height):
        start = row * (stride + 1)
        filter_type = source[start]
        scanline = np.frombuffer(source[start + 1 : start + 1 + stride], dtype=np.uint8).copy()
        previous = output[row - 1] if row else np.zeros(stride, dtype=np.uint8)
        if filter_type == 1:
            for column in range(4, stride):
                scanline[column] = (int(scanline[column]) + int(scanline[column - 4])) & 0xFF
        elif filter_type == 2:
            scanline = (scanline.astype(np.uint16) + previous).astype(np.uint8)
        elif filter_type == 3:
            for column in range(stride):
                left = int(scanline[column - 4]) if column >= 4 else 0
                scanline[column] = (
                    int(scanline[column]) + ((left + int(previous[column])) // 2)
                ) & 0xFF
        elif filter_type == 4:
            for column in range(stride):
                left = int(scanline[column - 4]) if column >= 4 else 0
                upper_left = int(previous[column - 4]) if column >= 4 else 0
                scanline[column] = (
                    int(scanline[column]) + _paeth(left, int(previous[column]), upper_left)
                ) & 0xFF
        elif filter_type != 0:
            raise DisplayListError(f"unsupported PNG filter {filter_type}")
        output[row] = scanline
    return output.reshape(height, width, 4)


class _DisplayListRasterizer:
    def __init__(self, display_list: "DisplayList", scale: float) -> None:
        self.display_list = display_list
        self.scale = scale
        self.width = display_list.width
        self.height = display_list.height
        self.cmd = _Cmd(scale)
        self._path_clip_cache: dict[
            tuple[tuple[Any, ...], ...],
            tuple[float, float, float, float, np.ndarray] | None,
        ] = {}
        self._array_cache: dict[str, np.ndarray] = {}
        self._text_path_cache: dict[str, list[list[Any]]] = {}

    def _array_resource(self, resource_id: str) -> np.ndarray:
        cached = self._array_cache.get(resource_id)
        if cached is not None:
            return cached
        values, shape = self.display_list.array_resource(resource_id)
        result = np.asarray(values).reshape(shape)
        self._array_cache[resource_id] = result
        return result

    def _text_path(self, command: dict[str, Any]) -> list[list[Any]]:
        resource_id = command.get("glyph_path_resource")
        if resource_id is None:
            return text_glyph_path(self.display_list, command)
        if not isinstance(resource_id, str):
            raise DisplayListError("text glyph path resource id must be a string")
        cached = self._text_path_cache.get(resource_id)
        if cached is None:
            cached = text_glyph_path(self.display_list, command)
            self._text_path_cache[resource_id] = cached
        return cached

    def _path_clip_entry(
        self,
        clip: dict[str, Any],
    ) -> tuple[float, float, float, float, np.ndarray] | None:
        """Measure and rasterize a shaped clip once per distinct path.

        Polar axes and other projections attach the same clip path to dozens of
        Artists.  Recomputing its supersampled winding mask independently for
        every stroke dominated raster time.  Cached masks remain an internal
        raster-consumer detail; the shared display list still carries the exact
        path on each operation.
        """
        path = clip.get("path")
        if not isinstance(path, list):
            return None
        try:
            key = tuple(tuple(segment) for segment in path)
        except TypeError:
            return None
        if key in self._path_clip_cache:
            return self._path_clip_cache[key]

        contours = _flatten_path(path, canvas_height=self.height)
        points = [point for contour, _closed in contours for point in contour]
        if not points:
            self._path_clip_cache[key] = None
            return None
        xs, ys = zip(*points, strict=True)
        x0 = max(0.0, math.floor(min(xs) * self.scale) / self.scale)
        y0 = max(0.0, math.floor(min(ys) * self.scale) / self.scale)
        x1 = min(self.width, math.ceil(max(xs) * self.scale) / self.scale)
        y1 = min(self.height, math.ceil(max(ys) * self.scale) / self.scale)
        pixel_width = int(round((x1 - x0) * self.scale))
        pixel_height = int(round((y1 - y0) * self.scale))
        if pixel_width <= 0 or pixel_height <= 0:
            self._path_clip_cache[key] = None
            return None
        coverage = _coverage_mask(
            contours,
            x0=x0,
            y0=y0,
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            scale=self.scale,
        )
        entry = x0, y0, x1, y1, coverage
        self._path_clip_cache[key] = entry
        return entry

    def _aligned_bounds(
        self,
        points: Sequence[tuple[float, float]],
        *,
        pad: float = 0,
        clip: dict[str, Any] | None = None,
    ) -> tuple[float, float, float, float, int, int] | None:
        if not points:
            return None
        xs, ys = zip(*points, strict=True)
        minimum_x = min(xs) - pad
        maximum_x = max(xs) + pad
        minimum_y = min(ys) - pad
        maximum_y = max(ys) + pad
        if clip is not None and clip.get("type") == "path":
            clip_entry = self._path_clip_entry(clip)
            if clip_entry is None:
                return None
            clip_x0, clip_y0, clip_x1, clip_y1, _coverage = clip_entry
            minimum_x = max(minimum_x, clip_x0)
            maximum_x = min(maximum_x, clip_x1)
            minimum_y = max(minimum_y, clip_y0)
            maximum_y = min(maximum_y, clip_y1)
        x0 = max(0.0, math.floor(minimum_x * self.scale) / self.scale)
        y0 = max(0.0, math.floor(minimum_y * self.scale) / self.scale)
        x1 = min(self.width, math.ceil(maximum_x * self.scale) / self.scale)
        y1 = min(self.height, math.ceil(maximum_y * self.scale) / self.scale)
        pixel_width = int(round((x1 - x0) * self.scale))
        pixel_height = int(round((y1 - y0) * self.scale))
        if pixel_width <= 0 or pixel_height <= 0:
            return None
        return x0, y0, x1, y1, pixel_width, pixel_height

    def _render_local(self, command: _Cmd, pixel_width: int, pixel_height: int) -> np.ndarray:
        return _native.rasterize_spans(command.buf, (), pixel_width, pixel_height)

    def _apply_path_clip(
        self,
        image: np.ndarray,
        clip: dict[str, Any] | None,
        *,
        x0: float,
        y0: float,
    ) -> None:
        if clip is None or clip.get("type") != "path":
            return
        entry = self._path_clip_entry(clip)
        coverage = np.zeros(image.shape[:2], dtype=np.float32)
        if entry is not None:
            clip_x0, clip_y0, _clip_x1, _clip_y1, clip_coverage = entry
            request_column = int(round(x0 * self.scale))
            request_row = int(round(y0 * self.scale))
            clip_column = int(round(clip_x0 * self.scale))
            clip_row = int(round(clip_y0 * self.scale))
            overlap_x0 = max(request_column, clip_column)
            overlap_y0 = max(request_row, clip_row)
            overlap_x1 = min(
                request_column + image.shape[1],
                clip_column + clip_coverage.shape[1],
            )
            overlap_y1 = min(
                request_row + image.shape[0],
                clip_row + clip_coverage.shape[0],
            )
            if overlap_x0 < overlap_x1 and overlap_y0 < overlap_y1:
                target_x0 = overlap_x0 - request_column
                target_y0 = overlap_y0 - request_row
                source_x0 = overlap_x0 - clip_column
                source_y0 = overlap_y0 - clip_row
                width = overlap_x1 - overlap_x0
                height = overlap_y1 - overlap_y0
                coverage[target_y0 : target_y0 + height, target_x0 : target_x0 + width] = (
                    clip_coverage[
                        source_y0 : source_y0 + height,
                        source_x0 : source_x0 + width,
                    ]
                )
        image[:, :, 3] = np.rint(image[:, :, 3].astype(np.float32) * coverage).astype(np.uint8)

    def _emit_layer(
        self,
        image: np.ndarray,
        *,
        x0: float,
        y0: float,
        clip: dict[str, Any] | None,
    ) -> None:
        self._set_clip(None if clip is not None and clip.get("type") == "path" else clip)
        pixel_height, pixel_width = image.shape[:2]
        self.cmd.image(
            x0,
            y0,
            pixel_width / self.scale,
            pixel_height / self.scale,
            pixel_width,
            pixel_height,
            image.tobytes(),
            nearest=True,
        )

    def _set_clip(self, clip: dict[str, Any] | None) -> None:
        if clip is None:
            self.cmd.clip(0, 0, self.width, self.height)
            return
        if clip.get("type") == "rect":
            x = float(clip["x"])
            y = self.height - float(clip["y"]) - float(clip["height"])
            self.cmd.clip(x, y, float(clip["width"]), float(clip["height"]))
            return
        if clip.get("type") == "path":
            # Shaped clips are applied as exact antialiased coverage masks by
            # each primitive painter before its layer enters this stream.
            self.cmd.clip(0, 0, self.width, self.height)
            return
        raise DisplayListError(f"unknown raster clip type {clip.get('type')!r}")

    def _compound_fill(
        self,
        contours: list[tuple[list[tuple[float, float]], bool]],
        color: tuple[int, int, int, int],
    ) -> None:
        rings = [points for points, _closed in contours if len(points) >= 3]
        if not rings or color[3] == 0:
            return
        all_points = [point for ring in rings for point in ring]
        xs, ys = zip(*all_points, strict=True)
        x0 = max(0.0, math.floor(min(xs) * self.scale) / self.scale)
        y0 = max(0.0, math.floor(min(ys) * self.scale) / self.scale)
        x1 = min(self.width, math.ceil(max(xs) * self.scale) / self.scale)
        y1 = min(self.height, math.ceil(max(ys) * self.scale) / self.scale)
        pixel_width = int(round((x1 - x0) * self.scale))
        pixel_height = int(round((y1 - y0) * self.scale))
        if pixel_width <= 0 or pixel_height <= 0:
            return
        coverage = _coverage_mask(
            contours,
            x0=x0,
            y0=y0,
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            scale=self.scale,
        )
        alpha = np.rint(coverage * color[3]).astype(np.uint8)
        image = np.empty((pixel_height, pixel_width, 4), dtype=np.uint8)
        image[:, :, :3] = color[:3]
        image[:, :, 3] = alpha
        self.cmd.image(
            x0,
            y0,
            x1 - x0,
            y1 - y0,
            pixel_width,
            pixel_height,
            image.tobytes(),
            nearest=True,
        )

    def _hatch_layer(
        self,
        style: dict[str, Any],
        *,
        x0: float,
        y0: float,
        pixel_width: int,
        pixel_height: int,
    ) -> np.ndarray:
        output = np.zeros((pixel_height, pixel_width, 4), dtype=np.uint8)
        hatch_path = style.get("hatch_path")
        tile_size = float(style.get("hatch_tile_size", 0))
        opacity = float(style.get("opacity", 1))
        color = _rgba8(style.get("hatch_color"), opacity)
        linewidth = float(style.get("hatch_linewidth", 1))
        if not hatch_path or tile_size <= 0 or color[3] == 0:
            return output

        contours = _flatten_path(hatch_path, canvas_height=tile_size)
        command = _Cmd(self.scale)
        command.clip(0, 0, pixel_width / self.scale, pixel_height / self.scale)
        first_column = math.floor(x0 / tile_size) - 1
        last_column = math.ceil((x0 + pixel_width / self.scale) / tile_size) + 1
        first_row = math.floor(y0 / tile_size) - 1
        last_row = math.ceil((y0 + pixel_height / self.scale) / tile_size) + 1
        for row in range(first_row, last_row + 1):
            for column in range(first_column, last_column + 1):
                dx = column * tile_size - x0
                dy = row * tile_size - y0
                for points, closed in contours:
                    shifted = [(x + dx, y + dy) for x, y in points]
                    if closed and len(shifted) >= 3:
                        command.fill(shifted, color)
                    if len(shifted) >= 2 and linewidth > 0:
                        command.stroke(
                            shifted,
                            linewidth,
                            color,
                            closed=closed,
                            cap="butt",
                        )
        return self._render_local(command, pixel_width, pixel_height)

    def _path_layer(
        self,
        contours: list[tuple[list[tuple[float, float]], bool]],
        style: dict[str, Any],
        clip: dict[str, Any] | None,
    ) -> None:
        points = [point for contour, _closed in contours for point in contour]
        opacity = float(style.get("opacity", 1))
        fill = _rgba8(style.get("fill"), opacity)
        stroke = _rgba8(style.get("stroke"), opacity)
        linewidth = float(style.get("linewidth", 0))
        padding = linewidth / 2 + 1 / self.scale if stroke[3] and linewidth > 0 else 0
        bounds = self._aligned_bounds(points, pad=padding, clip=clip)
        if bounds is None:
            return
        x0, y0, _x1, _y1, pixel_width, pixel_height = bounds
        image = np.zeros((pixel_height, pixel_width, 4), dtype=np.uint8)
        has_hatch = bool(style.get("hatch") and style.get("hatch_path"))
        shape_coverage: np.ndarray | None = None
        if fill[3] or has_hatch:
            fillable = [(ring, closed) for ring, closed in contours if len(ring) >= 3]
            shape_coverage = _coverage_mask(
                fillable,
                x0=x0,
                y0=y0,
                pixel_width=pixel_width,
                pixel_height=pixel_height,
                scale=self.scale,
            )
        if fill[3] and shape_coverage is not None:
            image[:, :, :3] = fill[:3]
            image[:, :, 3] = np.rint(shape_coverage * fill[3]).astype(np.uint8)

        if has_hatch and shape_coverage is not None:
            hatch = self._hatch_layer(
                style,
                x0=x0,
                y0=y0,
                pixel_width=pixel_width,
                pixel_height=pixel_height,
            )
            hatch[:, :, 3] = np.rint(hatch[:, :, 3].astype(np.float32) * shape_coverage).astype(
                np.uint8
            )
            image = _source_over(image, hatch)

        if stroke[3] and linewidth > 0:
            command = _Cmd(self.scale)
            command.clip(0, 0, pixel_width / self.scale, pixel_height / self.scale)
            dash = style.get("dash")
            sequence = dash.get("sequence") if isinstance(dash, dict) else None
            cap = str(style.get("cap", "round"))
            if cap not in {"butt", "round", "square"}:
                cap = "round"
            for ring, closed in contours:
                if len(ring) >= 2:
                    command.stroke(
                        [(x - x0, y - y0) for x, y in ring],
                        linewidth,
                        stroke,
                        closed=closed,
                        dash=sequence,
                        cap=cap,
                    )
            image = _source_over(
                image,
                self._render_local(command, pixel_width, pixel_height),
            )

        self._apply_path_clip(image, clip, x0=x0, y0=y0)
        self._emit_layer(image, x0=x0, y0=y0, clip=clip)

    def _paint_path(
        self,
        segments: list[list[Any]],
        style: dict[str, Any],
        clip: dict[str, Any] | None,
        *,
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        if (
            style.get("antialiased") is False
            and not style.get("hatch")
            and (style.get("stroke") is None or float(style.get("linewidth", 0)) <= 0)
        ):
            segments = _crisp_rectilinear_path(
                segments,
                scale=self.scale,
                offset=offset,
            )
        contours = _flatten_path(segments, canvas_height=self.height, offset=offset)
        if style.get("hatch") or (clip is not None and clip.get("type") == "path"):
            self._path_layer(contours, style, clip)
            return

        self._set_clip(clip)
        opacity = float(style.get("opacity", 1.0))
        fill = _rgba8(style.get("fill"), opacity)
        if fill[3]:
            fillable = [(points, closed) for points, closed in contours if len(points) >= 3]
            if len(fillable) == 1:
                self.cmd.fill(fillable[0][0], fill)
            elif fillable:
                self._compound_fill(fillable, fill)
        stroke = _rgba8(style.get("stroke"), opacity)
        width = float(style.get("linewidth", 0))
        if stroke[3] and width > 0:
            dash = style.get("dash")
            sequence = dash.get("sequence") if isinstance(dash, dict) else None
            cap = str(style.get("cap", "round"))
            if cap not in {"butt", "round", "square"}:
                cap = "round"
            for points, closed in contours:
                if len(points) >= 2:
                    self.cmd.stroke(
                        points,
                        width,
                        stroke,
                        closed=closed,
                        dash=sequence,
                        cap=cap,
                    )

    def _paint_affine_image(
        self,
        command: dict[str, Any],
        image: np.ndarray,
        matrix: Sequence[float],
    ) -> None:
        if len(matrix) != 6:
            raise DisplayListError("image transforms must contain six affine values")
        a, b, c, d, e, f = (float(value) for value in matrix)
        determinant = a * d - b * c
        if abs(determinant) <= np.finfo(float).eps:
            return
        x_offset = float(command["x"])
        y_offset = float(command["y"])
        device_corners = [
            (
                a * source_x + c * source_y + e + x_offset,
                b * source_x + d * source_y + f + y_offset,
            )
            for source_x, source_y in ((0, 0), (1, 0), (1, 1), (0, 1))
        ]
        top_corners = [(x, self.height - y) for x, y in device_corners]
        clip = command.get("clip")
        bounds = self._aligned_bounds(top_corners, pad=1 / self.scale, clip=clip)
        if bounds is None:
            return
        x0, y0, _x1, _y1, pixel_width, pixel_height = bounds
        quad_coverage = _coverage_mask(
            [(top_corners, True)],
            x0=x0,
            y0=y0,
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            scale=self.scale,
        )
        x_grid = x0 + (np.arange(pixel_width, dtype=np.float32) + 0.5) / self.scale
        top_y_grid = y0 + (np.arange(pixel_height, dtype=np.float32) + 0.5) / self.scale
        rhs_x = x_grid[np.newaxis, :] - (x_offset + e)
        rhs_y = self.height - top_y_grid[:, np.newaxis] - (y_offset + f)
        source_x = (d * rhs_x - c * rhs_y) / determinant
        source_y = (-b * rhs_x + a * rhs_y) / determinant
        source_x = np.clip(source_x, 0, 1)
        source_y = np.clip(source_y, 0, 1)
        source_height, source_width = image.shape[:2]
        interpolation = str(command.get("interpolation", "nearest"))
        if interpolation == "nearest":
            columns = np.clip(
                np.floor(source_x * source_width).astype(np.int64),
                0,
                source_width - 1,
            )
            rows = np.clip(
                np.floor((1 - source_y) * source_height).astype(np.int64),
                0,
                source_height - 1,
            )
            layer = image[rows, columns].copy()
        elif interpolation == "bilinear":
            source = image.astype(np.float32) / 255
            alpha = source[:, :, 3:4]
            premultiplied = np.concatenate([source[:, :, :3] * alpha, alpha], axis=2)
            column_position = source_x * source_width - 0.5
            row_position = (1 - source_y) * source_height - 0.5
            column0 = np.floor(column_position).astype(np.int64)
            row0 = np.floor(row_position).astype(np.int64)
            column_fraction = (column_position - column0)[:, :, np.newaxis]
            row_fraction = (row_position - row0)[:, :, np.newaxis]
            column1 = column0 + 1
            row1 = row0 + 1
            column0 = np.clip(column0, 0, source_width - 1)
            column1 = np.clip(column1, 0, source_width - 1)
            row0 = np.clip(row0, 0, source_height - 1)
            row1 = np.clip(row1, 0, source_height - 1)
            top = (
                premultiplied[row0, column0] * (1 - column_fraction)
                + premultiplied[row0, column1] * column_fraction
            )
            bottom = (
                premultiplied[row1, column0] * (1 - column_fraction)
                + premultiplied[row1, column1] * column_fraction
            )
            sampled = top * (1 - row_fraction) + bottom * row_fraction
            straight = np.zeros_like(sampled)
            np.divide(
                sampled[:, :, :3],
                sampled[:, :, 3:4],
                out=straight[:, :, :3],
                where=sampled[:, :, 3:4] > 0,
            )
            straight[:, :, 3:4] = sampled[:, :, 3:4]
            layer = np.rint(np.clip(straight, 0, 1) * 255).astype(np.uint8)
        else:
            raise DisplayListError(f"unknown image interpolation {interpolation!r}")

        layer[:, :, 3] = np.rint(layer[:, :, 3].astype(np.float32) * quad_coverage).astype(np.uint8)
        self._apply_path_clip(layer, clip, x0=x0, y0=y0)
        self._emit_layer(layer, x0=x0, y0=y0, clip=clip)

    def _paint_image(self, command: dict[str, Any]) -> None:
        resource = self.display_list.resources.get(command["resource"])
        if resource is None or resource.get("type") != "image/png":
            raise DisplayListError(f"missing PNG resource {command['resource']!r}")
        image = _decode_rgba_png(resource)
        alpha = min(1.0, max(0.0, float(command.get("alpha", 1))))
        if alpha != 1:
            image = image.copy()
            image[:, :, 3] = np.rint(image[:, :, 3].astype(float) * alpha).astype(np.uint8)
        matrix = command.get("transform")
        if matrix is not None:
            self._paint_affine_image(command, image, matrix)
            return

        x = float(command["x"])
        y = self.height - float(command["y"]) - float(command["height"])
        width = float(command["width"])
        height = float(command["height"])
        clip = command.get("clip")
        if clip is not None and clip.get("type") == "path":
            points = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
            bounds = self._aligned_bounds(points, clip=clip)
            if bounds is None:
                return
            x0, y0, _x1, _y1, pixel_width, pixel_height = bounds
            local = _Cmd(self.scale)
            local.clip(0, 0, pixel_width / self.scale, pixel_height / self.scale)
            local.image(
                x - x0,
                y - y0,
                width,
                height,
                image.shape[1],
                image.shape[0],
                image.tobytes(),
                nearest=command.get("interpolation") == "nearest",
            )
            layer = self._render_local(local, pixel_width, pixel_height)
            self._apply_path_clip(layer, clip, x0=x0, y0=y0)
            self._emit_layer(layer, x0=x0, y0=y0, clip=clip)
            return

        self._set_clip(clip)
        self.cmd.image(
            x,
            y,
            width,
            height,
            image.shape[1],
            image.shape[0],
            image.tobytes(),
            nearest=command.get("interpolation") == "nearest",
        )

    def _paint_quad_mesh(self, command: dict[str, Any]) -> None:
        self._set_clip(command.get("clip"))
        common_style = command["style"]
        for points, face, edge in quad_mesh_items(self.display_list, command):
            style = dict(common_style)
            style["fill"] = face
            # Do not leak the graphics context's default foreground stroke
            # into meshes whose edge color is explicitly absent.
            style["stroke"] = edge
            path = [
                ["M", *points[0]],
                ["L", *points[1]],
                ["L", *points[2]],
                ["L", *points[3]],
                ["Z"],
            ]
            self._paint_path(path, style, command.get("clip"))

    def _rectilinear_gouraud_layer(
        self,
        triangles: np.ndarray,
        colors: np.ndarray,
        *,
        x0: float,
        y0: float,
        pixel_width: int,
        pixel_height: int,
    ) -> np.ndarray | None:
        """Vectorize Matplotlib's four-triangle rectilinear QuadMesh batches."""
        if len(triangles) % 4:
            return None
        triangle_groups = triangles.reshape(-1, 4, 3, 2)
        color_groups = colors.reshape(-1, 4, 3, 4)
        centers = triangle_groups[:, :, 2]
        if not np.allclose(centers, centers[:, :1], rtol=0, atol=1e-7):
            return None
        # QuadMesh._convert_mesh_to_triangles emits
        # (a,b,center), (b,c,center), (c,d,center), (d,a,center).
        corners = np.stack(
            [
                triangle_groups[:, 0, 0],
                triangle_groups[:, 0, 1],
                triangle_groups[:, 1, 1],
                triangle_groups[:, 2, 1],
            ],
            axis=1,
        )
        corner_colors = np.stack(
            [
                color_groups[:, 0, 0],
                color_groups[:, 0, 1],
                color_groups[:, 1, 1],
                color_groups[:, 2, 1],
            ],
            axis=1,
        )
        center_colors = color_groups[:, :, 2]
        if not (
            np.allclose(center_colors, center_colors[:, :1], rtol=0, atol=1e-7)
            and np.allclose(
                center_colors[:, 0],
                corner_colors.mean(axis=1),
                rtol=0,
                atol=5e-7,
            )
        ):
            return None
        x_values = np.unique(corners[:, :, 0])
        y_values = np.unique(corners[:, :, 1])
        if (
            len(x_values) < 2
            or len(y_values) < 2
            or len(triangle_groups) != (len(x_values) - 1) * (len(y_values) - 1)
        ):
            return None
        x_indices = np.searchsorted(x_values, corners[:, :, 0])
        y_indices = np.searchsorted(y_values, corners[:, :, 1])
        if not (
            np.allclose(x_values[x_indices], corners[:, :, 0], rtol=0, atol=1e-7)
            and np.allclose(y_values[y_indices], corners[:, :, 1], rtol=0, atol=1e-7)
        ):
            return None
        cell_x = x_indices.min(axis=1)
        cell_y = y_indices.min(axis=1)
        cell_ids = cell_y * (len(x_values) - 1) + cell_x
        if len(np.unique(cell_ids)) != len(triangle_groups):
            return None

        vertex_ids = (y_indices * len(x_values) + x_indices).reshape(-1)
        vertex_colors = corner_colors.reshape(-1, 4)
        order = np.argsort(vertex_ids, kind="stable")
        duplicate = vertex_ids[order][1:] == vertex_ids[order][:-1]
        if np.any(duplicate) and not np.allclose(
            vertex_colors[order][1:][duplicate],
            vertex_colors[order][:-1][duplicate],
            rtol=0,
            atol=1e-7,
        ):
            return None
        color_grid = np.full((len(y_values), len(x_values), 4), np.nan, dtype=np.float32)
        color_grid[y_indices.reshape(-1), x_indices.reshape(-1)] = corner_colors.reshape(-1, 4)
        if not np.all(np.isfinite(color_grid)):
            return None

        supersample = 2
        sample_width = pixel_width * supersample
        sample_height = pixel_height * supersample
        sample_scale = self.scale * supersample
        x_coordinates = x0 + (np.arange(sample_width, dtype=np.float32) + 0.5) / sample_scale
        y_coordinates = y0 + (np.arange(sample_height, dtype=np.float32) + 0.5) / sample_scale
        inside_x = (x_coordinates >= x_values[0]) & (x_coordinates <= x_values[-1])
        x_cells = np.clip(
            np.searchsorted(x_values, x_coordinates, side="right") - 1,
            0,
            len(x_values) - 2,
        )
        x_span = x_values[x_cells + 1] - x_values[x_cells]
        if np.any(x_span <= 0):
            return None
        u = (x_coordinates - x_values[x_cells]) / x_span
        premultiplied = np.zeros((sample_height, sample_width, 4), dtype=np.float32)

        for row_start in range(0, sample_height, 128):
            row_stop = min(sample_height, row_start + 128)
            rows = y_coordinates[row_start:row_stop]
            inside_y = (rows >= y_values[0]) & (rows <= y_values[-1])
            y_cells = np.clip(
                np.searchsorted(y_values, rows, side="right") - 1,
                0,
                len(y_values) - 2,
            )
            y_span = y_values[y_cells + 1] - y_values[y_cells]
            if np.any(y_span <= 0):
                return None
            v = (rows - y_values[y_cells]) / y_span
            q00 = color_grid[y_cells[:, np.newaxis], x_cells[np.newaxis, :]]
            q10 = color_grid[y_cells[:, np.newaxis], x_cells[np.newaxis, :] + 1]
            q01 = color_grid[y_cells[:, np.newaxis] + 1, x_cells[np.newaxis, :]]
            q11 = color_grid[y_cells[:, np.newaxis] + 1, x_cells[np.newaxis, :] + 1]
            center = (q00 + q10 + q01 + q11) / 4
            u_grid = u[np.newaxis, :]
            v_grid = v[:, np.newaxis]
            left = (u_grid <= v_grid) & (u_grid <= 1 - v_grid)
            right = (u_grid >= v_grid) & (u_grid >= 1 - v_grid)
            lower = ~left & ~right & (v_grid <= 0.5)
            upper = ~left & ~right & ~lower
            interpolated = np.zeros_like(q00)
            candidate = (
                q00 * (1 - u_grid - v_grid)[:, :, np.newaxis]
                + q01 * (v_grid - u_grid)[:, :, np.newaxis]
                + center * np.broadcast_to(2 * u_grid, left.shape)[:, :, np.newaxis]
            )
            interpolated[left] = candidate[left]
            candidate = (
                q10 * (u_grid - v_grid)[:, :, np.newaxis]
                + q11 * (u_grid + v_grid - 1)[:, :, np.newaxis]
                + center * np.broadcast_to(2 * (1 - u_grid), right.shape)[:, :, np.newaxis]
            )
            interpolated[right] = candidate[right]
            candidate = (
                q00 * (1 - u_grid - v_grid)[:, :, np.newaxis]
                + q10 * (u_grid - v_grid)[:, :, np.newaxis]
                + center * np.broadcast_to(2 * v_grid, lower.shape)[:, :, np.newaxis]
            )
            interpolated[lower] = candidate[lower]
            candidate = (
                q01 * (v_grid - u_grid)[:, :, np.newaxis]
                + q11 * (u_grid + v_grid - 1)[:, :, np.newaxis]
                + center * np.broadcast_to(2 * (1 - v_grid), upper.shape)[:, :, np.newaxis]
            )
            interpolated[upper] = candidate[upper]
            interpolated = np.clip(interpolated, 0, 1)
            inside = inside_y[:, np.newaxis] & inside_x[np.newaxis, :]
            alpha = interpolated[:, :, 3]
            output = premultiplied[row_start:row_stop]
            output[:, :, :3][inside] = interpolated[:, :, :3][inside] * alpha[inside, np.newaxis]
            output[:, :, 3][inside] = alpha[inside]
        return premultiplied

    def _paint_gouraud(self, command: dict[str, Any]) -> None:
        triangles_resource = command.get("triangles_resource")
        colors_resource = command.get("colors_resource")
        if triangles_resource is None and colors_resource is None:
            triangles = np.asarray(command["triangles"], dtype=float)
            colors = np.asarray(command["colors"], dtype=float)
        elif isinstance(triangles_resource, str) and isinstance(colors_resource, str):
            triangles = self._array_resource(triangles_resource)
            colors = self._array_resource(colors_resource)
        else:
            raise DisplayListError("Gouraud triangle and color resources must be paired")
        if not len(triangles):
            return
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 2):
            raise DisplayListError("Gouraud triangles must have shape (N, 3, 2)")
        transformed = triangles.copy()
        transformed[:, :, 1] = self.height - transformed[:, :, 1]
        if colors.ndim != 3 or colors.shape[:2] != transformed.shape[:2]:
            raise DisplayListError("Gouraud colors must match triangle vertices")
        if colors.shape[2] == 3:
            colors = np.concatenate(
                [colors, np.ones((*colors.shape[:2], 1), dtype=float)],
                axis=2,
            )
        elif colors.shape[2] != 4:
            raise DisplayListError("Gouraud colors must contain RGB or RGBA channels")
        points = [tuple(point) for triangle in transformed for point in triangle]
        clip = command.get("clip")
        bounds = self._aligned_bounds(points, pad=1 / self.scale, clip=clip)
        if bounds is None:
            return
        x0, y0, _x1, _y1, pixel_width, pixel_height = bounds
        supersample = 2
        sample_width = pixel_width * supersample
        sample_height = pixel_height * supersample
        premultiplied = self._rectilinear_gouraud_layer(
            transformed,
            colors,
            x0=x0,
            y0=y0,
            pixel_width=pixel_width,
            pixel_height=pixel_height,
        )
        rectilinear_batch = premultiplied is not None
        if premultiplied is None:
            premultiplied = np.zeros((sample_height, sample_width, 4), dtype=np.float32)
        sample_scale = self.scale * supersample

        if not rectilinear_batch:
            for triangle, vertex_colors in zip(transformed, colors, strict=True):
                minimum_x = max(
                    0,
                    int(math.floor((triangle[:, 0].min() - x0) * sample_scale)),
                )
                maximum_x = min(
                    sample_width,
                    int(math.ceil((triangle[:, 0].max() - x0) * sample_scale)),
                )
                minimum_y = max(
                    0,
                    int(math.floor((triangle[:, 1].min() - y0) * sample_scale)),
                )
                maximum_y = min(
                    sample_height,
                    int(math.ceil((triangle[:, 1].max() - y0) * sample_scale)),
                )
                if minimum_x >= maximum_x or minimum_y >= maximum_y:
                    continue
                x_coordinates = (
                    x0 + (np.arange(minimum_x, maximum_x, dtype=np.float32) + 0.5) / sample_scale
                )
                y_coordinates = (
                    y0 + (np.arange(minimum_y, maximum_y, dtype=np.float32) + 0.5) / sample_scale
                )
                x_grid = x_coordinates[np.newaxis, :]
                y_grid = y_coordinates[:, np.newaxis]
                (x_a, y_a), (x_b, y_b), (x_c, y_c) = triangle
                denominator = (y_b - y_c) * (x_a - x_c) + (x_c - x_b) * (y_a - y_c)
                if abs(denominator) <= np.finfo(float).eps:
                    continue
                weight_a = (
                    (y_b - y_c) * (x_grid - x_c) + (x_c - x_b) * (y_grid - y_c)
                ) / denominator
                weight_b = (
                    (y_c - y_a) * (x_grid - x_c) + (x_a - x_c) * (y_grid - y_c)
                ) / denominator
                weight_c = 1 - weight_a - weight_b
                inside = (weight_a >= -1e-7) & (weight_b >= -1e-7) & (weight_c >= -1e-7)
                if not np.any(inside):
                    continue
                interpolated = (
                    weight_a[:, :, np.newaxis] * vertex_colors[0]
                    + weight_b[:, :, np.newaxis] * vertex_colors[1]
                    + weight_c[:, :, np.newaxis] * vertex_colors[2]
                )
                interpolated = np.clip(interpolated, 0, 1).astype(np.float32)
                source_alpha = interpolated[:, :, 3:4]
                region = premultiplied[minimum_y:maximum_y, minimum_x:maximum_x]
                source_rgb = interpolated[:, :, :3] * source_alpha
                region_rgb = source_rgb + region[:, :, :3] * (1 - source_alpha)
                region_alpha = source_alpha + region[:, :, 3:4] * (1 - source_alpha)
                region[inside, :3] = region_rgb[inside]
                region[inside, 3:4] = region_alpha[inside]

        averaged = premultiplied.reshape(
            pixel_height,
            supersample,
            pixel_width,
            supersample,
            4,
        ).mean(axis=(1, 3), dtype=np.float32)
        straight = np.zeros_like(averaged)
        np.divide(
            averaged[:, :, :3],
            averaged[:, :, 3:4],
            out=straight[:, :, :3],
            where=averaged[:, :, 3:4] > 0,
        )
        straight[:, :, 3:4] = averaged[:, :, 3:4]
        image = np.rint(np.clip(straight, 0, 1) * 255).astype(np.uint8)
        self._apply_path_clip(image, clip, x0=x0, y0=y0)
        self._emit_layer(image, x0=x0, y0=y0, clip=clip)

    def render(self) -> np.ndarray:
        for command in self.display_list.commands:
            command_type = command["type"]
            if command_type == "path":
                self._paint_path(command["path"], command["style"], command.get("clip"))
            elif command_type == "text":
                text_font(self.display_list, command)
                self._paint_path(self._text_path(command), command["style"], command.get("clip"))
            elif command_type == "path_collection":
                paths = path_collection_paths(self.display_list, command)
                for item in path_collection_items(self.display_list, command):
                    self._paint_path(
                        paths[int(item["path"])],
                        item["style"],
                        item.get("clip"),
                        offset=tuple(item.get("offset", (0.0, 0.0))),
                    )
            elif command_type == "marker_collection":
                path = marker_path(self.display_list, command)
                for position in marker_positions(self.display_list, command):
                    self._paint_path(
                        path,
                        command["style"],
                        command.get("clip"),
                        offset=tuple(position),
                    )
            elif command_type == "image":
                self._paint_image(command)
            elif command_type == "quad_mesh":
                self._paint_quad_mesh(command)
            elif command_type == "gouraud_triangles":
                self._paint_gouraud(command)
            elif command_type in {"group_open", "group_close"}:
                continue
            else:
                raise DisplayListError(f"unknown raster command {command_type!r}")
        width = max(1, round(self.width * self.scale))
        height = max(1, round(self.height * self.scale))
        return _native.rasterize_spans(self.cmd.buf, (), width, height)


def rasterize(display_list: "DisplayList", *, scale: float = 1.0) -> np.ndarray:
    """Rasterize a shared display list into an H-by-W straight-alpha RGBA8 array."""
    if isinstance(scale, bool):
        raise DisplayListError("raster scale must be a finite positive number")
    try:
        numeric_scale = float(scale)
    except (TypeError, ValueError) as exc:
        raise DisplayListError("raster scale must be a finite positive number") from exc
    if not math.isfinite(numeric_scale) or numeric_scale <= 0:
        raise DisplayListError("raster scale must be a finite positive number")
    return _DisplayListRasterizer(display_list, numeric_scale).render()


def to_png(display_list: "DisplayList", *, scale: float = 1.0) -> bytes:
    """Rasterize and encode a display list with XY's native PNG encoder."""
    return _png.encode(rasterize(display_list, scale=scale))


__all__ = ["rasterize", "to_png"]
