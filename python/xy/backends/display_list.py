"""Renderer-neutral display-list IR and standalone serializers.

The IR deliberately contains only JSON-compatible values.  Matplotlib, NumPy,
browser objects, and renderer-specific handles never cross this boundary.  All
geometry is stored in device pixels using Matplotlib's conventional bottom-left
origin; serializers perform the final coordinate-system conversion.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import sys
from array import array
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, SupportsFloat, SupportsIndex, cast

DISPLAY_LIST_SCHEMA = "xy.display-list/1"
PATH_COLLECTION_BATCH_SCHEMA = "xy.path-collection.instances/1"
_PATH_COLLECTION_BATCH_WIDTH = 24


class DisplayListError(ValueError):
    """Raised when a display list does not satisfy the public IR contract."""


def _positive_finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise DisplayListError(f"{label} must be a finite positive number")
    numeric = cast(str | bytes | bytearray | SupportsFloat | SupportsIndex, value)
    try:
        result = float(numeric)
    except (TypeError, ValueError) as exc:
        raise DisplayListError(f"{label} must be a finite positive number") from exc
    if not math.isfinite(result) or result <= 0:
        raise DisplayListError(f"{label} must be a finite positive number")
    return result


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise DisplayListError(f"{label} must be finite")
    numeric = cast(str | bytes | bytearray | SupportsFloat | SupportsIndex, value)
    try:
        result = float(numeric)
    except (TypeError, ValueError) as exc:
        raise DisplayListError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise DisplayListError(f"{label} must be finite")
    return result


def _json_safe(value: Any) -> Any:
    """Return plain JSON data and reject non-finite renderer output."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DisplayListError("display-list values must be finite")
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # NumPy scalars and similar numeric wrappers intentionally enter here.  A
    # float conversion is preferable to importing NumPy into this IR module.
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise DisplayListError(
            f"display-list value {type(value).__name__!r} is not JSON-compatible"
        ) from exc
    if not math.isfinite(numeric):
        raise DisplayListError("display-list values must be finite")
    return numeric


@dataclass(slots=True)
class DisplayList:
    """An ordered, serializable set of device-space rendering operations."""

    width: float
    height: float
    dpi: float
    commands: list[dict[str, Any]] = field(default_factory=list)
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    fallback_used: bool = False
    fallback_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.width = _positive_finite(self.width, "width")
        self.height = _positive_finite(self.height, "height")
        self.dpi = _positive_finite(self.dpi, "dpi")
        if not isinstance(self.fallback_used, bool):
            raise DisplayListError("fallback_used must be true or false")
        if self.fallback_used and not self.fallback_reason:
            raise DisplayListError("fallback_reason is required when fallback_used is true")
        if not self.fallback_used and self.fallback_reason is not None:
            raise DisplayListError("fallback_reason requires fallback_used=true")
        if self.fallback_reason is not None and not isinstance(self.fallback_reason, str):
            raise DisplayListError("fallback_reason must be a string")
        self.commands = _json_safe(self.commands)
        self.resources = _json_safe(self.resources)
        self.metadata = _json_safe(self.metadata)

    def add(self, command_type: str, /, **payload: Any) -> dict[str, Any]:
        """Append one ordered command and return the stored plain dictionary."""
        if not command_type or not isinstance(command_type, str):
            raise DisplayListError("command_type must be a non-empty string")
        command = {"type": command_type, **payload}
        stored = _json_safe(command)
        self.commands.append(stored)
        return stored

    def add_png_resource(self, png: bytes, *, width: int, height: int) -> str:
        """Deduplicate an in-memory PNG and return its stable resource id."""
        if not isinstance(png, bytes):
            raise DisplayListError("PNG resources must be bytes")
        resource_width = int(_positive_finite(width, "image width"))
        resource_height = int(_positive_finite(height, "image height"))
        digest = hashlib.sha256(png).hexdigest()
        resource_id = f"image-{digest[:24]}"
        self.resources.setdefault(
            resource_id,
            {
                "type": "image/png",
                "width": resource_width,
                "height": resource_height,
                "sha256": digest,
                "data": base64.b64encode(png).decode("ascii"),
            },
        )
        return resource_id

    def add_array_resource(
        self,
        data: bytes,
        *,
        dtype: str,
        shape: tuple[int, ...],
    ) -> str:
        """Deduplicate one packed numeric batch and return its resource id.

        Large mesh/collection buffers stay batched instead of expanding every
        scalar through Python dictionaries and JSON-safe validation.  The
        payload remains self-contained and JSON-compatible for browser, SVG,
        and raster consumers.
        """
        if not isinstance(data, bytes):
            raise DisplayListError("array resources must be bytes")
        item_sizes = {"<f4": 4, "<f8": 8}
        if dtype not in item_sizes:
            raise DisplayListError("array resource dtype must be '<f4' or '<f8'")
        if (
            not isinstance(shape, tuple)
            or not shape
            or any(
                isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in shape
            )
        ):
            raise DisplayListError("array resource shape must contain nonnegative integers")
        item_count = math.prod(shape)
        if len(data) != item_count * item_sizes[dtype]:
            raise DisplayListError("array resource byte count does not match its shape")
        digest = hashlib.sha256(data).hexdigest()
        identity_hash = hashlib.sha256()
        identity_hash.update(dtype.encode("ascii"))
        identity_hash.update(b"\0")
        identity_hash.update(b",".join(str(size).encode("ascii") for size in shape))
        identity_hash.update(b"\0")
        identity_hash.update(data)
        identity = identity_hash.hexdigest()
        resource_id = f"array-{identity[:24]}"
        self.resources.setdefault(
            resource_id,
            {
                "type": "application/vnd.xy.ndarray",
                "dtype": dtype,
                "shape": list(shape),
                "sha256": digest,
                "data": base64.b64encode(data).decode("ascii"),
            },
        )
        return resource_id

    def array_resource(self, resource_id: str) -> tuple[array[float], tuple[int, ...]]:
        """Decode and validate a packed numeric resource.

        This is the shared resource boundary for every exporter.  Consumers
        may cache or convert the returned flat array, but they must not grow a
        second JSON representation of a collection or mesh.
        """
        resource = self.resources.get(resource_id)
        if resource is None or resource.get("type") != "application/vnd.xy.ndarray":
            raise DisplayListError(f"missing numeric array resource {resource_id!r}")
        dtype = resource.get("dtype")
        typecode = {"<f4": "f", "<f8": "d"}.get(dtype)
        if typecode is None:
            raise DisplayListError(f"unsupported array resource dtype {dtype!r}")
        shape_value = resource.get("shape")
        if (
            not isinstance(shape_value, list)
            or not shape_value
            or any(
                isinstance(size, bool) or not isinstance(size, int) or size < 0
                for size in shape_value
            )
        ):
            raise DisplayListError("array resource has an invalid shape")
        try:
            raw = base64.b64decode(resource["data"], validate=True)
        except (KeyError, ValueError) as exc:
            raise DisplayListError("array resource contains invalid base64") from exc
        if hashlib.sha256(raw).hexdigest() != resource.get("sha256"):
            raise DisplayListError("array resource checksum does not match")
        values = array(typecode)
        values.frombytes(raw)
        if sys.byteorder != "little":
            values.byteswap()
        shape = tuple(shape_value)
        if len(values) != math.prod(shape):
            raise DisplayListError("array resource byte count does not match its shape")
        return values, shape

    def add_path_resource(self, path: list[list[Any]]) -> str:
        """Deduplicate device-space path geometry and return its resource id."""
        safe_path = _json_safe(path)
        if not isinstance(safe_path, list):  # pragma: no cover - type guard
            raise DisplayListError("path resources must be lists of segments")
        encoded = json.dumps(
            safe_path,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        resource_id = f"path-{digest[:24]}"
        self.resources.setdefault(
            resource_id,
            {
                "type": "application/vnd.xy.path+json",
                "sha256": digest,
                "path": safe_path,
            },
        )
        return resource_id

    def path_resource(self, resource_id: str) -> list[list[Any]]:
        """Resolve and checksum one content-addressed path resource."""
        resource = self.resources.get(resource_id)
        if resource is None or resource.get("type") != "application/vnd.xy.path+json":
            raise DisplayListError(f"missing path resource {resource_id!r}")
        path = _json_safe(resource.get("path"))
        if not isinstance(path, list):
            raise DisplayListError("path resource must contain a list of segments")
        encoded = json.dumps(
            path,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != resource.get("sha256"):
            raise DisplayListError("path resource checksum does not match")
        return cast(list[list[Any]], path)

    def add_font_resource(self, font: Mapping[str, Any]) -> str:
        """Deduplicate JSON font metadata and return its stable resource id."""
        if not isinstance(font, Mapping):
            raise DisplayListError("font resources must be mappings")
        safe_font = _json_safe(dict(font))
        if not isinstance(safe_font, dict):  # pragma: no cover - type guard
            raise DisplayListError("font resources must contain JSON metadata")
        encoded = json.dumps(
            safe_font,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        resource_id = f"font-{digest[:24]}"
        self.resources.setdefault(
            resource_id,
            {
                "type": "application/vnd.xy.font+json",
                "sha256": digest,
                "font": safe_font,
            },
        )
        return resource_id

    def font_resource(self, resource_id: str) -> dict[str, Any]:
        """Resolve and checksum one content-addressed font resource."""
        resource = self.resources.get(resource_id)
        if resource is None or resource.get("type") != "application/vnd.xy.font+json":
            raise DisplayListError(f"missing font resource {resource_id!r}")
        font = _json_safe(resource.get("font"))
        if not isinstance(font, dict):
            raise DisplayListError("font resource must contain a metadata mapping")
        encoded = json.dumps(
            font,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != resource.get("sha256"):
            raise DisplayListError("font resource checksum does not match")
        return cast(dict[str, Any], font)

    def mark_fallback(self, reason: str) -> None:
        """Mark use of a non-XY renderer so acceptance can reject the result."""
        if not reason:
            raise DisplayListError("fallback reason must be non-empty")
        self.fallback_used = True
        self.fallback_reason = str(reason)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible representation."""
        return {
            "schema": DISPLAY_LIST_SCHEMA,
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "metadata": deepcopy(self.metadata),
            "resources": deepcopy(self.resources),
            "commands": deepcopy(self.commands),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DisplayList":
        """Validate and reconstruct a display list produced by :meth:`to_dict`."""
        if not isinstance(value, dict):
            raise DisplayListError("display list must be a dictionary")
        if value.get("schema") != DISPLAY_LIST_SCHEMA:
            raise DisplayListError(f"unsupported display-list schema {value.get('schema')!r}")
        commands = value.get("commands", [])
        resources = value.get("resources", {})
        metadata = value.get("metadata", {})
        if not isinstance(commands, list):
            raise DisplayListError("commands must be a list")
        if not all(isinstance(command, dict) and command.get("type") for command in commands):
            raise DisplayListError("every command must be a dictionary with a type")
        if not isinstance(resources, dict):
            raise DisplayListError("resources must be a dictionary")
        if not isinstance(metadata, dict):
            raise DisplayListError("metadata must be a dictionary")
        fallback_used = value.get("fallback_used", False)
        if not isinstance(fallback_used, bool):
            raise DisplayListError("fallback_used must be true or false")
        return cls(
            width=cast(float, value.get("width")),
            height=cast(float, value.get("height")),
            dpi=cast(float, value.get("dpi")),
            commands=commands,
            resources=resources,
            fallback_used=fallback_used,
            fallback_reason=value.get("fallback_reason"),
            metadata=metadata,
        )

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize the complete IR without allowing NaN or infinity."""
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            indent=indent,
            separators=separators,
            sort_keys=True,
            allow_nan=False,
        )

    def to_svg(self, *, metadata: dict[str, Any] | None = None) -> str:
        """Render the display list as standalone SVG without Matplotlib."""
        return _SVGSerializer(self, metadata=metadata).render()

    def to_html(self, *, title: str = "XY Matplotlib figure") -> str:
        """Render a self-contained HTML document containing SVG and the IR."""
        svg = self.to_svg()
        if svg.startswith("<?xml"):
            svg = svg.split("\n", 1)[1]
        payload = self.to_json().replace("<", "\\u003c").replace(">", "\\u003e")
        safe_title = html.escape(title, quote=True)
        return (
            "<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{safe_title}</title>"
            "<style>html,body{margin:0}svg{display:block;max-width:100%;height:auto}</style>"
            "</head><body>"
            f"{svg}"
            '<script type="application/json" id="xy-display-list">'
            f"{payload}</script>"
            "</body></html>\n"
        )

    def to_rgba(self, *, scale: float = 1.0) -> Any:
        """Rasterize through XY's native painter into an RGBA8 NumPy array."""
        from .raster import rasterize

        return rasterize(self, scale=scale)

    def to_png(self, *, scale: float = 1.0) -> bytes:
        """Rasterize and encode with XY; no Matplotlib renderer is consulted."""
        from .raster import to_png

        return to_png(self, scale=scale)


def _batch_count(command: dict[str, Any], shape: tuple[int, ...], label: str) -> int:
    count = command.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise DisplayListError(f"{label} count must be a nonnegative integer")
    if not shape or shape[0] != count:
        raise DisplayListError(f"{label} count does not match its packed resource")
    return count


def _batch_index(
    value: object,
    length: int,
    label: str,
    *,
    allow_missing: bool = False,
) -> int | None:
    numeric = _finite(value, label)
    index = int(numeric)
    if numeric != index:
        raise DisplayListError(f"{label} must be an integer")
    if allow_missing and index == -1:
        return None
    if index < 0 or index >= length:
        raise DisplayListError(f"{label} is out of range")
    return index


def marker_path(display_list: DisplayList, command: dict[str, Any]) -> list[list[Any]]:
    """Resolve legacy or resource-backed marker geometry."""
    resource_id = command.get("path_resource")
    if resource_id is None:
        path = command.get("path")
        if not isinstance(path, list):
            raise DisplayListError("marker collection is missing its path")
        return cast(list[list[Any]], path)
    if not isinstance(resource_id, str):
        raise DisplayListError("marker path resource id must be a string")
    return display_list.path_resource(resource_id)


def text_glyph_path(display_list: DisplayList, command: dict[str, Any]) -> list[list[Any]]:
    """Resolve legacy inline or content-addressed text outline geometry."""
    resource_id = command.get("glyph_path_resource")
    if resource_id is None:
        path = command.get("glyph_path")
        if not isinstance(path, list):
            raise DisplayListError("text command is missing its glyph path")
        return cast(list[list[Any]], path)
    if not isinstance(resource_id, str):
        raise DisplayListError("text glyph path resource id must be a string")
    return display_list.path_resource(resource_id)


def text_font(display_list: DisplayList, command: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve legacy inline or content-addressed text font metadata."""
    resource_id = command.get("font_resource")
    if resource_id is None:
        font = command.get("font")
        if font is None:
            return None
        if not isinstance(font, dict):
            raise DisplayListError("text font metadata must be a mapping")
        return cast(dict[str, Any], font)
    if not isinstance(resource_id, str):
        raise DisplayListError("text font resource id must be a string")
    return display_list.font_resource(resource_id)


def marker_positions(
    display_list: DisplayList,
    command: dict[str, Any],
) -> Iterator[tuple[float, float]]:
    """Iterate legacy or packed marker positions without expanding the IR."""
    resource_id = command.get("positions_resource")
    if resource_id is None:
        positions = command.get("positions")
        if not isinstance(positions, list):
            raise DisplayListError("marker collection is missing its positions")
        for position in positions:
            if not isinstance(position, list) or len(position) != 2:
                raise DisplayListError("marker positions must contain x and y")
            yield _finite(position[0], "marker x"), _finite(position[1], "marker y")
        return
    if not isinstance(resource_id, str):
        raise DisplayListError("marker positions resource id must be a string")
    values, shape = display_list.array_resource(resource_id)
    count = _batch_count(command, shape, "marker collection")
    if len(shape) != 2 or shape[1] != 2:
        raise DisplayListError("packed marker positions must have shape (N, 2)")
    for index in range(count):
        start = index * 2
        yield (
            _finite(values[start], "marker x"),
            _finite(values[start + 1], "marker y"),
        )


def path_collection_paths(
    display_list: DisplayList,
    command: dict[str, Any],
) -> list[list[list[Any]]]:
    """Resolve legacy or resource-backed path-collection geometry."""
    resource_ids = command.get("path_resources")
    if resource_ids is None:
        paths = command.get("paths")
        if not isinstance(paths, list):
            raise DisplayListError("path collection is missing its paths")
        return cast(list[list[list[Any]]], paths)
    if not isinstance(resource_ids, list) or not all(
        isinstance(resource_id, str) for resource_id in resource_ids
    ):
        raise DisplayListError("path collection resource ids must be strings")
    return [display_list.path_resource(resource_id) for resource_id in resource_ids]


def path_collection_items(
    display_list: DisplayList,
    command: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """Iterate legacy or packed collection instances as transient values."""
    resource_id = command.get("instances_resource")
    if resource_id is None:
        items = command.get("items")
        if not isinstance(items, list):
            raise DisplayListError("path collection is missing its instances")
        yield from items
        return
    if command.get("instances_schema") != PATH_COLLECTION_BATCH_SCHEMA:
        raise DisplayListError("unsupported packed path-collection schema")
    if not isinstance(resource_id, str):
        raise DisplayListError("path-collection resource id must be a string")
    values, shape = display_list.array_resource(resource_id)
    count = _batch_count(command, shape, "path collection")
    if len(shape) != 2 or shape[1] != _PATH_COLLECTION_BATCH_WIDTH:
        raise DisplayListError(
            f"packed path-collection instances must have shape (N, {_PATH_COLLECTION_BATCH_WIDTH})"
        )
    paths = path_collection_paths(display_list, command)
    templates = command.get("style_templates")
    clips = command.get("clips")
    urls = command.get("urls")
    if not isinstance(templates, list) or not all(
        isinstance(template, dict) for template in templates
    ):
        raise DisplayListError("path-collection style templates must be dictionaries")
    if not isinstance(clips, list) or not all(isinstance(clip, dict) for clip in clips):
        raise DisplayListError("path-collection clips must be dictionaries")
    if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
        raise DisplayListError("path-collection URLs must be strings")
    for item_index in range(count):
        start = item_index * _PATH_COLLECTION_BATCH_WIDTH
        row = values[start : start + _PATH_COLLECTION_BATCH_WIDTH]
        path_index = _batch_index(row[0], len(paths), "path-collection path index")
        style_index = _batch_index(row[3], len(templates), "path-collection style index")
        clip_index = _batch_index(
            row[4],
            len(clips),
            "path-collection clip index",
            allow_missing=True,
        )
        url_index = _batch_index(
            row[5],
            len(urls),
            "path-collection URL index",
            allow_missing=True,
        )
        fill_flag = _batch_index(row[6], 2, "path-collection fill flag")
        stroke_flag = _batch_index(row[11], 2, "path-collection stroke flag")
        antialiased = _batch_index(row[18], 2, "path-collection antialias flag")
        hatch_color_flag = _batch_index(row[19], 2, "path-collection hatch-color flag")
        assert path_index is not None
        assert style_index is not None
        assert fill_flag is not None
        assert stroke_flag is not None
        assert antialiased is not None
        assert hatch_color_flag is not None
        style = dict(templates[style_index])
        style.update(
            {
                "fill": [float(value) for value in row[7:11]] if fill_flag else None,
                "stroke": [float(value) for value in row[12:16]] if stroke_flag else None,
                "linewidth": _finite(row[16], "path-collection linewidth"),
                "opacity": _finite(row[17], "path-collection opacity"),
                "antialiased": bool(antialiased),
                "hatch_color": (
                    [float(value) for value in row[20:24]] if hatch_color_flag else None
                ),
            }
        )
        yield {
            "path": path_index,
            "offset": [
                _finite(row[1], "path-collection x"),
                _finite(row[2], "path-collection y"),
            ],
            "style": style,
            "clip": clips[clip_index] if clip_index is not None else None,
            "url": urls[url_index] if url_index is not None else None,
            "gid": None,
        }


def quad_mesh_items(
    display_list: DisplayList,
    command: dict[str, Any],
) -> Iterator[tuple[list[list[float]], list[float] | None, list[float] | None]]:
    """Iterate legacy or packed quad geometry and colors."""
    points_resource = command.get("points_resource")
    if points_resource is None:
        quads = command.get("quads")
        if not isinstance(quads, list):
            raise DisplayListError("quad mesh is missing its cells")
        for quad in quads:
            yield quad["points"], quad.get("face"), quad.get("edge")
        return
    if not isinstance(points_resource, str):
        raise DisplayListError("quad-mesh points resource id must be a string")
    points, point_shape = display_list.array_resource(points_resource)
    count = _batch_count(command, point_shape, "quad mesh")
    if len(point_shape) != 3 or point_shape[1:] != (4, 2):
        raise DisplayListError("packed quad-mesh points must have shape (N, 4, 2)")

    def colors(name: str) -> array[float] | None:
        resource_id = command.get(name)
        if resource_id is None:
            return None
        if not isinstance(resource_id, str):
            raise DisplayListError(f"quad-mesh {name} must be a string")
        values, shape = display_list.array_resource(resource_id)
        if shape != (count, 4):
            raise DisplayListError("packed quad-mesh colors must have shape (N, 4)")
        return values

    faces = colors("faces_resource")
    edges = colors("edges_resource")
    for index in range(count):
        point_start = index * 8
        points_value = [
            [
                _finite(points[point_start + corner * 2], "quad-mesh x"),
                _finite(points[point_start + corner * 2 + 1], "quad-mesh y"),
            ]
            for corner in range(4)
        ]
        color_start = index * 4
        face = (
            [
                _finite(value, "quad-mesh face channel")
                for value in faces[color_start : color_start + 4]
            ]
            if faces is not None
            else None
        )
        edge = (
            [
                _finite(value, "quad-mesh edge channel")
                for value in edges[color_start : color_start + 4]
            ]
            if edges is not None
            else None
        )
        yield points_value, face, edge


def _fmt(value: object) -> str:
    number = _finite(value, "SVG coordinate")
    if abs(number) < 5e-13:
        number = 0.0
    return format(number, ".9g")


def _rgb(color: list[float] | None) -> tuple[str, float] | None:
    if color is None:
        return None
    if len(color) not in (3, 4):
        raise DisplayListError("colors must contain RGB or RGBA channels")
    channels = [min(1.0, max(0.0, float(channel))) for channel in color]
    alpha = channels[3] if len(channels) == 4 else 1.0
    red, green, blue = (round(channel * 255) for channel in channels[:3])
    return f"#{red:02x}{green:02x}{blue:02x}", alpha


def _attrs(values: Mapping[str, object]) -> str:
    return "".join(
        f' {name}="{html.escape(str(value), quote=True)}"'
        for name, value in values.items()
        if value is not None
    )


class _SVGSerializer:
    """Small SVG writer for :class:`DisplayList` commands."""

    def __init__(
        self,
        display_list: DisplayList,
        *,
        metadata: dict[str, Any] | None,
    ) -> None:
        self.display_list = display_list
        self.metadata = _json_safe(metadata or {})
        self._clip_ids: dict[str, str] = {}
        self._clips: list[tuple[str, dict[str, Any]]] = []
        self._resource_counter = 0
        self._hatch_ids: dict[str, str] = {}
        self._hatches: list[tuple[str, dict[str, Any]]] = []
        self._gouraud_counter = 0
        self._gouraud_filters_used = False
        self._group_counts: dict[str, int] = {}
        self._array_cache: dict[str, tuple[array[float], tuple[int, ...]]] = {}
        self._path_ids: dict[str, str] = {}
        self._path_definitions: list[tuple[str, list[list[Any]]]] = []

    @property
    def height(self) -> float:
        return self.display_list.height

    def _path_d(
        self,
        segments: list[list[Any]],
        *,
        dx: float = 0,
        dy: float = 0,
        coordinate_height: float | None = None,
    ) -> str:
        height = self.height if coordinate_height is None else coordinate_height
        pieces: list[str] = []
        for segment in segments:
            if not segment:
                continue
            code = segment[0]
            coords = segment[1:]
            if code in {"M", "L"} and len(coords) == 2:
                pieces.append(
                    f"{code}{_fmt(float(coords[0]) + dx)} {_fmt(height - (float(coords[1]) + dy))}"
                )
            elif code == "Q" and len(coords) == 4:
                pieces.append(
                    "Q"
                    f"{_fmt(float(coords[0]) + dx)} "
                    f"{_fmt(height - (float(coords[1]) + dy))} "
                    f"{_fmt(float(coords[2]) + dx)} "
                    f"{_fmt(height - (float(coords[3]) + dy))}"
                )
            elif code == "C" and len(coords) == 6:
                pieces.append(
                    "C"
                    f"{_fmt(float(coords[0]) + dx)} "
                    f"{_fmt(height - (float(coords[1]) + dy))} "
                    f"{_fmt(float(coords[2]) + dx)} "
                    f"{_fmt(height - (float(coords[3]) + dy))} "
                    f"{_fmt(float(coords[4]) + dx)} "
                    f"{_fmt(height - (float(coords[5]) + dy))}"
                )
            elif code == "Z":
                pieces.append("Z")
            else:
                raise DisplayListError(f"invalid path segment {segment!r}")
        return " ".join(pieces)

    def _style(self, style: dict[str, Any]) -> dict[str, str]:
        attrs: dict[str, str] = {}
        fill = _rgb(style.get("fill"))
        stroke = _rgb(style.get("stroke"))
        hatch_id = self._hatch_id(style)
        if hatch_id is not None:
            attrs["fill"] = f"url(#{hatch_id})"
        elif fill is None:
            attrs["fill"] = "none"
        else:
            attrs["fill"] = fill[0]
            if fill[1] != 1:
                attrs["fill-opacity"] = _fmt(fill[1])
        if stroke is not None and float(style.get("linewidth", 0)) > 0:
            attrs["stroke"] = stroke[0]
            if stroke[1] != 1:
                attrs["stroke-opacity"] = _fmt(stroke[1])
            attrs["stroke-width"] = _fmt(style["linewidth"])
            attrs["stroke-linejoin"] = str(style.get("join", "round"))
            attrs["stroke-linecap"] = str(style.get("cap", "butt"))
            dash = style.get("dash")
            if dash and dash.get("sequence"):
                attrs["stroke-dasharray"] = " ".join(_fmt(value) for value in dash["sequence"])
                attrs["stroke-dashoffset"] = _fmt(dash.get("offset", 0))
        opacity = float(style.get("opacity", 1))
        if opacity != 1:
            attrs["opacity"] = _fmt(opacity)
        if style.get("antialiased") is False:
            attrs["shape-rendering"] = "crispEdges"
        return attrs

    def _hatch_id(self, style: dict[str, Any]) -> str | None:
        if not style.get("hatch") or not style.get("hatch_path"):
            return None
        hatch_data = {
            "path": style["hatch_path"],
            "tile_size": style.get("hatch_tile_size", 72),
            "face": style.get("fill"),
            "color": style.get("hatch_color"),
            "linewidth": style.get("hatch_linewidth", 1),
        }
        key = json.dumps(hatch_data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        hatch_id = self._hatch_ids.get(key)
        if hatch_id is None:
            hatch_id = f"xy-hatch-{len(self._hatch_ids) + 1}"
            self._hatch_ids[key] = hatch_id
            self._hatches.append((hatch_id, hatch_data))
        return hatch_id

    def _clip_id(self, clip: dict[str, Any] | None) -> str | None:
        if not clip:
            return None
        key = json.dumps(clip, sort_keys=True, separators=(",", ":"), allow_nan=False)
        clip_id = self._clip_ids.get(key)
        if clip_id is None:
            clip_id = f"xy-clip-{len(self._clip_ids) + 1}"
            self._clip_ids[key] = clip_id
            self._clips.append((clip_id, clip))
        return clip_id

    def _with_common(
        self,
        attrs: dict[str, str],
        *,
        clip: dict[str, Any] | None,
        url: str | None,
        gid: str | None,
    ) -> tuple[dict[str, str], str, str]:
        clip_id = self._clip_id(clip)
        if clip_id:
            attrs["clip-path"] = f"url(#{clip_id})"
        if gid:
            attrs["id"] = gid
        opening = ""
        closing = ""
        if url:
            safe_url = html.escape(url, quote=True)
            opening = f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">'
            closing = "</a>"
        return attrs, opening, closing

    def _path(self, command: dict[str, Any]) -> str:
        attrs = self._style(command["style"])
        attrs["d"] = self._path_d(command["path"])
        attrs, opening, closing = self._with_common(
            attrs,
            clip=command.get("clip"),
            url=command.get("url"),
            gid=command.get("gid"),
        )
        return f"{opening}<path{_attrs(attrs)}/>{closing}"

    def _text(self, command: dict[str, Any]) -> str:
        text_font(self.display_list, command)
        attrs = self._style(command["style"])
        resource_id = command.get("glyph_path_resource")
        if resource_id is None:
            attrs["d"] = self._path_d(text_glyph_path(self.display_list, command))
            element = "path"
        else:
            if not isinstance(resource_id, str):
                raise DisplayListError("text glyph path resource id must be a string")
            attrs["href"] = f"#{self._path_resource_id(resource_id)}"
            element = "use"
        font_resource_id = command.get("font_resource")
        if font_resource_id is not None:
            attrs["data-font-resource"] = str(font_resource_id)
        attrs["data-text"] = command.get("text", "")
        attrs["aria-label"] = command.get("text", "")
        attrs, opening, closing = self._with_common(
            attrs,
            clip=command.get("clip"),
            url=command.get("url"),
            gid=command.get("gid"),
        )
        return f"{opening}<{element}{_attrs(attrs)}/>{closing}"

    def _path_collection(self, command: dict[str, Any]) -> str:
        paths = path_collection_paths(self.display_list, command)
        resource_ids = command.get("path_resources")
        definitions: list[str] = []
        hrefs: list[str] = []
        if resource_ids is None:
            self._resource_counter += 1
            prefix = f"xy-path-{self._resource_counter}"
            for index, path in enumerate(paths):
                path_id = f"{prefix}-{index}"
                hrefs.append(path_id)
                definitions.append(
                    f'<path id="{path_id}" d="{html.escape(self._path_d(path), quote=True)}"/>'
                )
        else:
            hrefs = [self._path_resource_id(resource_id) for resource_id in resource_ids]
        uses = []
        for item in path_collection_items(self.display_list, command):
            attrs = self._style(item["style"])
            path_index = int(item["path"])
            if path_index < 0 or path_index >= len(hrefs):
                raise DisplayListError("path-collection path index is out of range")
            attrs["href"] = f"#{hrefs[path_index]}"
            dx, dy = item.get("offset", [0, 0])
            if dx or dy:
                # The referenced path has already been converted to SVG's
                # top-left coordinates, so a positive device-space y offset is
                # a negative SVG translation.
                attrs["transform"] = f"translate({_fmt(dx)} {_fmt(-float(dy))})"
            element = f"<use{_attrs(attrs)}/>"
            group_attrs: dict[str, str] = {}
            clip_id = self._clip_id(item.get("clip"))
            if clip_id:
                # Keep clipping in global device coordinates.  Attaching it to
                # the translated <use> would translate the clip as well.
                group_attrs["clip-path"] = f"url(#{clip_id})"
            if item.get("gid"):
                group_attrs["id"] = item["gid"]
            if group_attrs:
                element = f"<g{_attrs(group_attrs)}>{element}</g>"
            if item.get("url"):
                safe_url = html.escape(item["url"], quote=True)
                element = (
                    f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{element}</a>'
                )
            uses.append(element)
        body = (f"<defs>{''.join(definitions)}</defs>" if definitions else "") + "".join(uses)
        if command.get("gid"):
            body = f"<g{_attrs({'id': command['gid']})}>{body}</g>"
        return body

    def _marker_collection(self, command: dict[str, Any]) -> str:
        path = marker_path(self.display_list, command)
        resource_id = command.get("path_resource")
        if resource_id is None:
            self._resource_counter += 1
            marker_id = f"xy-marker-{self._resource_counter}"
            definition = (
                f'<defs><path id="{marker_id}" '
                f'd="{html.escape(self._path_d(path), quote=True)}"/></defs>'
            )
        else:
            marker_id = self._path_resource_id(resource_id)
            definition = ""
        style = self._style(command["style"])
        uses = []
        for x, y in marker_positions(self.display_list, command):
            attrs = dict(style)
            attrs["href"] = f"#{marker_id}"
            attrs["transform"] = f"translate({_fmt(x)} {_fmt(-float(y))})"
            uses.append(f"<use{_attrs(attrs)}/>")
        group_attrs: dict[str, str] = {}
        clip_id = self._clip_id(command.get("clip"))
        if clip_id:
            group_attrs["clip-path"] = f"url(#{clip_id})"
        if command.get("gid"):
            group_attrs["id"] = command["gid"]
        body = f"<g{_attrs(group_attrs)}>{''.join(uses)}</g>"
        url = command.get("url")
        if url:
            safe_url = html.escape(url, quote=True)
            body = f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{body}</a>'
        return definition + body

    def _image(self, command: dict[str, Any]) -> str:
        resource = self.display_list.resources.get(command["resource"])
        if resource is None or resource.get("type") != "image/png":
            raise DisplayListError(f"missing PNG resource {command['resource']!r}")
        x = float(command["x"])
        y = float(command["y"])
        width = float(command["width"])
        height = float(command["height"])
        attrs: dict[str, str] = {
            "href": f"data:image/png;base64,{resource['data']}",
            "width": _fmt(width),
            "height": _fmt(height),
            "preserveAspectRatio": "none",
        }
        matrix = command.get("transform")
        if matrix is None:
            attrs["x"] = _fmt(x)
            attrs["y"] = _fmt(self.height - y - height)
        else:
            if len(matrix) != 6:
                raise DisplayListError("image transforms must contain six affine values")
            a, b, c, d, e, f = (float(value) for value in matrix)
            # The Matplotlib transform maps normalized, bottom-origin image
            # coordinates. Resources are stored top-row first, so fold both
            # normalization and the source-y flip into the SVG matrix.
            attrs["transform"] = (
                "matrix("
                f"{_fmt(a / width)} {_fmt(-b / width)} "
                f"{_fmt(-c / height)} {_fmt(d / height)} "
                f"{_fmt(e + x + c)} {_fmt(self.height - (f + y) - d)}"
                ")"
            )
            if command.get("interpolation") == "nearest":
                attrs["style"] = "image-rendering:crisp-edges;image-rendering:pixelated"
        alpha = float(command.get("alpha", 1))
        if alpha != 1:
            attrs["opacity"] = _fmt(alpha)
        element = f"<image{_attrs(attrs)}/>"
        group_attrs: dict[str, str] = {}
        clip_id = self._clip_id(command.get("clip"))
        if clip_id:
            group_attrs["clip-path"] = f"url(#{clip_id})"
        if command.get("gid"):
            group_attrs["id"] = command["gid"]
        if group_attrs:
            element = f"<g{_attrs(group_attrs)}>{element}</g>"
        if command.get("url"):
            safe_url = html.escape(command["url"], quote=True)
            element = (
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{element}</a>'
            )
        return element

    def _array_resource(self, resource_id: str) -> tuple[array[float], tuple[int, ...]]:
        cached = self._array_cache.get(resource_id)
        if cached is not None:
            return cached
        cached = self.display_list.array_resource(resource_id)
        self._array_cache[resource_id] = cached
        return cached

    def _path_resource_id(self, resource_id: str) -> str:
        path_id = self._path_ids.get(resource_id)
        if path_id is not None:
            return path_id
        path = self.display_list.path_resource(resource_id)
        path_id = f"xy-path-resource-{len(self._path_ids) + 1}"
        self._path_ids[resource_id] = path_id
        self._path_definitions.append((path_id, path))
        return path_id

    def _gouraud_items(self, command: dict[str, Any]) -> Any:
        triangles_resource = command.get("triangles_resource")
        colors_resource = command.get("colors_resource")
        if triangles_resource is None and colors_resource is None:
            return zip(command["triangles"], command["colors"], strict=True)
        if not isinstance(triangles_resource, str) or not isinstance(colors_resource, str):
            raise DisplayListError("Gouraud triangle and color resources must be paired")
        triangles, triangle_shape = self._array_resource(triangles_resource)
        colors, color_shape = self._array_resource(colors_resource)
        if (
            len(triangle_shape) != 3
            or triangle_shape[1:] != (3, 2)
            or len(color_shape) != 3
            or color_shape[1:] != (3, 4)
            or triangle_shape[0] != color_shape[0]
        ):
            raise DisplayListError("packed Gouraud arrays have incompatible shapes")

        def items() -> Any:
            for index in range(triangle_shape[0]):
                triangle_start = index * 6
                color_start = index * 12
                yield (
                    [
                        triangles[triangle_start : triangle_start + 2],
                        triangles[triangle_start + 2 : triangle_start + 4],
                        triangles[triangle_start + 4 : triangle_start + 6],
                    ],
                    [
                        colors[color_start : color_start + 4],
                        colors[color_start + 4 : color_start + 8],
                        colors[color_start + 8 : color_start + 12],
                    ],
                )

        return items()

    def _gouraud(self, command: dict[str, Any]) -> str:
        self._gouraud_filters_used = True
        output = []
        clip_id = self._clip_id(command.get("clip"))
        for points, colors in self._gouraud_items(command):
            converted = [(float(x), self.height - float(y)) for x, y in points]
            mean = [sum(float(vertex[channel]) for vertex in colors) / 3 for channel in range(4)]
            if mean[3] == 0:
                continue
            gradient_ids = []
            definitions = []
            for index in range(3):
                x1, y1 = converted[index]
                x2, y2 = converted[(index + 1) % 3]
                x3, y3 = converted[(index + 2) % 3]
                if x2 == x3:
                    xb, yb = x2, y1
                elif y2 == y3:
                    xb, yb = x1, y2
                else:
                    slope1 = (y2 - y3) / (x2 - x3)
                    intercept1 = y2 - slope1 * x2
                    slope2 = -(1 / slope1)
                    intercept2 = y1 - slope2 * x1
                    xb = (-intercept1 + intercept2) / (slope1 - slope2)
                    yb = slope2 * xb + intercept2
                gradient_id = f"xy-gouraud-{self._gouraud_counter}-{index}"
                gradient_ids.append(gradient_id)
                vertex_color = _rgb(colors[index])
                average_color = _rgb(mean)
                assert vertex_color is not None and average_color is not None
                definitions.append(
                    f'<linearGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" '
                    f'x1="{_fmt(x1)}" y1="{_fmt(y1)}" x2="{_fmt(xb)}" y2="{_fmt(yb)}">'
                    f'<stop offset="1" stop-color="{average_color[0]}" '
                    f'stop-opacity="{_fmt(vertex_color[1])}"/>'
                    f'<stop offset="0" stop-color="{vertex_color[0]}" stop-opacity="0"/>'
                    "</linearGradient>"
                )
            self._gouraud_counter += 1
            path_d = "M" + " L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in converted) + " Z"
            average_color = _rgb(mean)
            assert average_color is not None
            triangle = (
                f"<defs>{''.join(definitions)}</defs>"
                f'<path d="{path_d}" fill="{average_color[0]}" fill-opacity="1" '
                'shape-rendering="crispEdges"/>'
                '<g stroke="none" stroke-width="0" shape-rendering="crispEdges" '
                'filter="url(#xy-color-matrix)">'
                f'<path d="{path_d}" fill="url(#{gradient_ids[0]})"/>'
                f'<path d="{path_d}" fill="url(#{gradient_ids[1]})" '
                'filter="url(#xy-color-add)"/>'
                f'<path d="{path_d}" fill="url(#{gradient_ids[2]})" '
                'filter="url(#xy-color-add)"/>'
                "</g>"
            )
            output.append(triangle)
        attrs: dict[str, str] = {}
        if clip_id:
            attrs["clip-path"] = f"url(#{clip_id})"
        if command.get("gid"):
            attrs["id"] = command["gid"]
        return f"<g{_attrs(attrs)}>{''.join(output)}</g>"

    def _quad_mesh(self, command: dict[str, Any]) -> str:
        output = []
        for points, face, edge in quad_mesh_items(self.display_list, command):
            path = [
                ["M", *points[0]],
                ["L", *points[1]],
                ["L", *points[2]],
                ["L", *points[3]],
                ["Z"],
            ]
            style = dict(command["style"])
            style["fill"] = face
            # An edge-less mesh must not inherit the graphics context's
            # default foreground stroke.  Explicit edges remain per-quad.
            style["stroke"] = edge
            attrs = self._style(style)
            attrs["d"] = self._path_d(path)
            clip_id = self._clip_id(command.get("clip"))
            if clip_id:
                attrs["clip-path"] = f"url(#{clip_id})"
            output.append(f"<path{_attrs(attrs)}/>")
        return "".join(output)

    def _shared_path_definitions(self) -> str:
        output = [
            f'<path id="{path_id}" d="{html.escape(self._path_d(path), quote=True)}"/>'
            for path_id, path in self._path_definitions
        ]
        return f"<defs>{''.join(output)}</defs>" if output else ""

    def _clip_definitions(self) -> str:
        output = []
        for clip_id, clip in self._clips:
            if clip.get("type") == "rect":
                x = float(clip["x"])
                y = float(clip["y"])
                height = float(clip["height"])
                element = (
                    f'<rect x="{_fmt(x)}" y="{_fmt(self.height - y - height)}" '
                    f'width="{_fmt(clip["width"])}" height="{_fmt(height)}"/>'
                )
            elif clip.get("type") == "path":
                element = f'<path d="{html.escape(self._path_d(clip["path"]), quote=True)}"/>'
            else:
                raise DisplayListError(f"unknown clip type {clip.get('type')!r}")
            output.append(
                f'<clipPath id="{clip_id}" clipPathUnits="userSpaceOnUse">{element}</clipPath>'
            )
        return f"<defs>{''.join(output)}</defs>" if output else ""

    def _hatch_definitions(self) -> str:
        output = []
        for hatch_id, hatch in self._hatches:
            tile_size = float(hatch["tile_size"])
            face = _rgb(hatch.get("face"))
            color = _rgb(hatch.get("color"))
            if color is None:
                color = ("#000000", 1.0)
            path_d = self._path_d(
                hatch["path"],
                coordinate_height=tile_size,
            )
            face_attrs = {"fill": "none"} if face is None else {"fill": face[0]}
            if face is not None and face[1] != 1:
                face_attrs["fill-opacity"] = _fmt(face[1])
            path_attrs = {
                "d": path_d,
                "fill": color[0],
                "stroke": color[0],
                "stroke-width": _fmt(hatch["linewidth"]),
                "stroke-linecap": "butt",
                "stroke-linejoin": "miter",
            }
            if color[1] != 1:
                path_attrs["stroke-opacity"] = _fmt(color[1])
                path_attrs["fill-opacity"] = _fmt(color[1])
            output.append(
                f'<pattern id="{hatch_id}" patternUnits="userSpaceOnUse" '
                f'x="0" y="0" width="{_fmt(tile_size)}" height="{_fmt(tile_size)}">'
                f'<rect x="0" y="0" width="{_fmt(tile_size + 1)}" '
                f'height="{_fmt(tile_size + 1)}"{_attrs(face_attrs)}/>'
                f"<path{_attrs(path_attrs)}/></pattern>"
            )
        return f"<defs>{''.join(output)}</defs>" if output else ""

    def _gouraud_filter_definitions(self) -> str:
        if not self._gouraud_filters_used:
            return ""
        return (
            "<defs>"
            '<filter id="xy-color-add">'
            '<feComposite in="SourceGraphic" in2="BackgroundImage" operator="arithmetic" '
            'k2="1" k3="1"/></filter>'
            '<filter id="xy-color-matrix">'
            '<feColorMatrix type="matrix" values="1 0 0 0 0 '
            "0 1 0 0 0 0 0 1 0 0 1 1 1 1 0 0 0 0 0 1"
            '"/></filter>'
            "</defs>"
        )

    def render(self) -> str:
        body: list[str] = []
        group_stack: list[str] = []
        for command in self.display_list.commands:
            command_type = command["type"]
            if command_type == "path":
                body.append(self._path(command))
            elif command_type == "text":
                body.append(self._text(command))
            elif command_type == "path_collection":
                body.append(self._path_collection(command))
            elif command_type == "marker_collection":
                body.append(self._marker_collection(command))
            elif command_type == "image":
                body.append(self._image(command))
            elif command_type == "gouraud_triangles":
                body.append(self._gouraud(command))
            elif command_type == "quad_mesh":
                body.append(self._quad_mesh(command))
            elif command_type == "group_open":
                name = str(command.get("name", "group"))
                group_id = command.get("gid")
                if not group_id:
                    count = self._group_counts.get(name, 0) + 1
                    self._group_counts[name] = count
                    group_id = f"{name}_{count}"
                body.append(f"<g{_attrs({'id': str(group_id)})}>")
                group_stack.append(name)
            elif command_type == "group_close":
                name = str(command.get("name", "group"))
                if not group_stack:
                    raise DisplayListError(f"closing unopened SVG group {name!r}")
                opened = group_stack.pop()
                if opened != name:
                    raise DisplayListError(f"closing SVG group {name!r} while {opened!r} is open")
                body.append("</g>")
            else:
                raise DisplayListError(f"unknown display-list command {command_type!r}")
        if group_stack:
            raise DisplayListError(f"unclosed SVG group {group_stack[-1]!r}")

        report = {
            "schema": DISPLAY_LIST_SCHEMA,
            "fallback_used": self.display_list.fallback_used,
            "fallback_reason": self.display_list.fallback_reason,
            **self.display_list.metadata,
            **self.metadata,
        }
        metadata = html.escape(
            json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
        width = _fmt(self.display_list.width)
        height = _fmt(self.display_list.height)
        # Clip definitions are discovered while commands are serialized.
        definitions = (
            '<defs><style type="text/css">'
            "*{stroke-linejoin: round; stroke-linecap: butt}"
            "</style></defs>"
            + self._clip_definitions()
            + self._hatch_definitions()
            + self._gouraud_filter_definitions()
            + self._shared_path_definitions()
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            'role="img">'
            f'<metadata id="xy-render-metadata">{metadata}</metadata>'
            f"{definitions}{''.join(body)}</svg>\n"
        )


__all__ = [
    "DISPLAY_LIST_SCHEMA",
    "DisplayList",
    "DisplayListError",
    "text_font",
    "text_glyph_path",
]
