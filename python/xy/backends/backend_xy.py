"""Matplotlib backend that records an XY display list.

Use it through Matplotlib's normal module-backend mechanism::

    matplotlib.use("module://xy.backends.backend_xy")

This module is the optional-dependency boundary: :mod:`xy.backends` and the
display-list serializers do not import Matplotlib, while importing this module
requires Matplotlib 3.11.
"""

from __future__ import annotations

import math
import os
import sys
import time
import weakref
import webbrowser
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, TextIO, cast

if TYPE_CHECKING:
    from .backend_xy_host import LoopbackHost
    from .backend_xy_widget import FigureCanvasXYWidget

try:
    import matplotlib
    import numpy as np
    from matplotlib.backend_bases import (
        FigureCanvasBase,
        FigureManagerBase,
        NavigationToolbar2,
        RendererBase,
        TimerBase,
        ToolContainerBase,
        _Backend,
    )
    from matplotlib.backend_tools import Cursors
    from matplotlib.font_manager import fontManager as _font_manager
    from matplotlib.font_manager import get_font
    from matplotlib.ft2font import LoadFlags
    from matplotlib.path import Path as MplPath
    from matplotlib.textpath import TextToPath
    from matplotlib.transforms import Affine2D
except ImportError as exc:  # pragma: no cover - exercised in a no-extra install
    raise ImportError(
        "xy's Matplotlib backend requires the optional Matplotlib integration; "
        'install it with `pip install "xy[matplotlib]"`'
    ) from exc

from .display_list import PATH_COLLECTION_BATCH_SCHEMA, DisplayList, DisplayListError

_MIN_MATPLOTLIB = (3, 11)
_MAX_MATPLOTLIB = (3, 12)
_PACKED_BATCH_MIN_VALUES = 4096
_PATH_COLLECTION_BATCH_WIDTH = 24


def _hinting_flag() -> LoadFlags:
    mapping = {
        "default": LoadFlags.DEFAULT,
        "no_autohint": LoadFlags.NO_AUTOHINT,
        "force_autohint": LoadFlags.FORCE_AUTOHINT,
        "no_hinting": LoadFlags.NO_HINTING,
        True: LoadFlags.FORCE_AUTOHINT,
        False: LoadFlags.NO_HINTING,
        "either": LoadFlags.DEFAULT,
        "native": LoadFlags.NO_AUTOHINT,
        "auto": LoadFlags.FORCE_AUTOHINT,
        "none": LoadFlags.NO_HINTING,
    }
    return mapping[matplotlib.rcParams["text.hinting"]]


def _matplotlib_minor() -> tuple[int, int]:
    parts = matplotlib.__version__.split(".", 2)
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as exc:  # pragma: no cover - nonstandard vendor version
        raise ImportError(
            f"cannot interpret Matplotlib version {matplotlib.__version__!r}"
        ) from exc


if not (_MIN_MATPLOTLIB <= _matplotlib_minor() < _MAX_MATPLOTLIB):
    raise ImportError(
        "xy's Matplotlib backend currently targets Matplotlib >=3.11,<3.12; "
        f"found {matplotlib.__version__}"
    )


def _plain_color(value: Any) -> list[float] | None:
    if value is None:
        return None
    channels = [float(channel) for channel in value]
    if len(channels) == 3:
        channels.append(1.0)
    if len(channels) != 4:
        raise ValueError("Matplotlib colors must be RGB or RGBA")
    return channels


def _intern_value(value: Any, values: list[Any]) -> int:
    """Return the stable index of a small repeated JSON value."""
    for index, existing in enumerate(values):
        if existing == value:
            return index
    values.append(value)
    return len(values) - 1


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _affine_values(transform: Any) -> list[float]:
    matrix = transform.get_matrix()
    return [
        float(matrix[0, 0]),
        float(matrix[1, 0]),
        float(matrix[0, 1]),
        float(matrix[1, 1]),
        float(matrix[0, 2]),
        float(matrix[1, 2]),
    ]


def _write_text(target: str | os.PathLike[str] | TextIO | BinaryIO, value: str) -> None:
    if isinstance(target, (str, os.PathLike)):
        Path(cast(str | os.PathLike[str], target)).write_text(value, encoding="utf-8")
        return
    try:
        cast(TextIO, target).write(value)
    except TypeError:
        cast(BinaryIO, target).write(value.encode("utf-8"))


def _write_bytes(target: str | os.PathLike[str] | BinaryIO, value: bytes) -> None:
    if isinstance(target, (str, os.PathLike)):
        Path(cast(str | os.PathLike[str], target)).write_bytes(value)
        return
    target.write(value)


class RendererXY(RendererBase):
    """A genuine Matplotlib renderer that emits device-space XY commands."""

    def __init__(self, width: float, height: float, dpi: float) -> None:
        super().__init__()
        self.width = float(width)
        self.height = float(height)
        self.dpi = float(dpi)
        self.display_list = self._new_display_list()
        self._filter_display_lists: list[DisplayList] = []

    def _new_display_list(self) -> DisplayList:
        return DisplayList(
            self.width,
            self.height,
            self.dpi,
            metadata={
                "backend": "module://xy.backends.backend_xy",
                "matplotlib": matplotlib.__version__,
                "coordinate_system": "device-pixels-bottom-left",
            },
        )

    def clear(self) -> None:
        """Discard prior commands while retaining the renderer allocation."""
        self.display_list = self._new_display_list()

    def start_filter(self) -> None:
        """Render the following Artist into an isolated XY display list.

        Matplotlib's ``agg_filter`` protocol is named after Agg, but only
        requires an offscreen RGBA buffer.  XY produces that buffer with its
        own display-list raster consumer so filtered Artists remain compatible
        with every XY output and never invoke a foreign renderer.
        """
        self._filter_display_lists.append(self.display_list)
        self.display_list = self._new_display_list()

    def stop_filter(self, filter_func: Any) -> None:
        """Apply an Artist filter and composite it into the parent display list."""
        filtered_display_list = self.display_list
        parent_display_list = self._filter_display_lists.pop()
        self.display_list = parent_display_list

        image = filtered_display_list.to_rgba()
        nonempty_rows = np.flatnonzero(np.any(image != 0, axis=(1, 2)))
        nonempty_columns = np.flatnonzero(np.any(image != 0, axis=(0, 2)))
        if not nonempty_rows.size or not nonempty_columns.size:
            return

        y_start = int(nonempty_rows[0])
        y_stop = int(nonempty_rows[-1]) + 1
        x_start = int(nonempty_columns[0])
        x_stop = int(nonempty_columns[-1]) + 1
        cropped = image[y_start:y_stop, x_start:x_stop]
        processed, offset_x, offset_y = filter_func(cropped / 255, self.dpi)
        processed = np.asarray(processed)
        if processed.dtype.kind == "f":
            processed = np.asarray(processed * 255, dtype=np.uint8)

        # Display-list image resources are top-row first, while Matplotlib's
        # draw_image protocol is bottom-row first.  draw_image performs the
        # resource normalization, so mirror RendererAgg and reverse here.
        gc = self.new_gc()
        self.draw_image(
            gc,
            x_start + float(offset_x),
            image.shape[0] - y_stop + float(offset_y),
            processed[::-1],
        )

    def get_canvas_width_height(self) -> tuple[int, int]:
        return int(round(self.width)), int(round(self.height))

    def points_to_pixels(self, points: Any) -> Any:
        return points * self.dpi / 72

    def get_text_width_height_descent(
        self,
        s: str,
        prop: Any,
        ismath: bool | Literal["TeX"],
    ) -> tuple[float, float, float]:
        """Use Matplotlib's configured FreeType hinting for plain text metrics."""
        if ismath:
            return super().get_text_width_height_descent(s, prop, ismath)
        font = get_font(_font_manager._find_fonts_by_props(prop))
        font.clear()
        font.set_size(prop.get_size_in_points(), self.dpi)
        font.set_text(s, 0, flags=_hinting_flag())
        width, height = font.get_width_height()
        descent = font.get_descent()
        return width / 64, height / 64, descent / 64

    def flipy(self) -> bool:
        # The IR owns Matplotlib's bottom-left device coordinate system.
        return False

    def option_image_nocomposite(self) -> bool:
        # Preserve image ordering and clipping as explicit display-list items.
        return True

    def option_scale_image(self) -> bool:
        return True

    def _path_segments(self, path: MplPath, transform: Any) -> list[list[Any]]:
        segments: list[list[Any]] = []
        for vertices, code in path.iter_segments(
            transform,
            remove_nans=True,
            clip=None,
            snap=False,
            simplify=False,
            curves=True,
        ):
            values = [float(value) for value in vertices]
            if code == MplPath.MOVETO:
                segments.append(["M", *values])
            elif code == MplPath.LINETO:
                segments.append(["L", *values])
            elif code == MplPath.CURVE3:
                segments.append(["Q", *values])
            elif code == MplPath.CURVE4:
                segments.append(["C", *values])
            elif code == MplPath.CLOSEPOLY:
                segments.append(["Z"])
            elif code != MplPath.STOP:  # pragma: no cover - protects future Path codes
                raise ValueError(f"unsupported Matplotlib path code {code!r}")
        return segments

    def _clip(self, gc: Any) -> dict[str, Any] | None:
        clip_path, clip_transform = gc.get_clip_path()
        if clip_path is not None:
            return {
                "type": "path",
                "path": self._path_segments(clip_path, clip_transform),
            }
        clip_rectangle = gc.get_clip_rectangle()
        if clip_rectangle is not None:
            x, y, width, height = (float(value) for value in clip_rectangle.bounds)
            return {
                "type": "rect",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
        return None

    def _style(self, gc: Any, face: Any = None) -> dict[str, Any]:
        forced_alpha = bool(gc.get_forced_alpha())
        alpha = float(gc.get_alpha())
        fill = _plain_color(face)
        stroke = _plain_color(gc.get_rgb())
        if forced_alpha:
            if fill is not None:
                fill[3] = 1.0
            if stroke is not None:
                stroke[3] = 1.0
        offset, sequence = gc.get_dashes()
        scale = self.dpi / 72
        dash = None
        if sequence is not None:
            dash = {
                "offset": float(offset) * scale,
                "sequence": [float(value) * scale for value in sequence],
            }
        cap = _enum_value(gc.get_capstyle())
        if cap == "projecting":
            cap = "square"
        hatch = gc.get_hatch()
        hatch_tile_size = 72 * scale
        hatch_path = (
            self._path_segments(gc.get_hatch_path(), Affine2D().scale(hatch_tile_size))
            if hatch is not None
            else None
        )
        return {
            "fill": fill,
            "stroke": stroke,
            "linewidth": float(gc.get_linewidth()) * scale,
            "dash": dash,
            "join": _enum_value(gc.get_joinstyle()),
            "cap": cap,
            "opacity": alpha if forced_alpha else 1.0,
            "antialiased": bool(gc.get_antialiased()),
            # Consumers share the transformed hatch tile instead of recovering
            # Matplotlib hatch semantics from a renderer-specific payload.
            "hatch": hatch,
            "hatch_path": hatch_path,
            "hatch_tile_size": hatch_tile_size,
            "hatch_color": _plain_color(gc.get_hatch_color()),
            "hatch_linewidth": float(gc.get_hatch_linewidth()) * scale,
        }

    def _common(self, gc: Any) -> dict[str, Any]:
        return {
            "clip": self._clip(gc),
            "url": gc.get_url(),
            "gid": gc.get_gid(),
        }

    def draw_path(
        self,
        gc: Any,
        path: MplPath,
        transform: Any,
        rgbFace: Any = None,
    ) -> None:
        segments = self._path_segments(path, transform)
        if not segments:
            return
        self.display_list.add(
            "path",
            path=segments,
            style=self._style(gc, rgbFace),
            **self._common(gc),
        )

    def draw_text(
        self,
        gc: Any,
        x: float,
        y: float,
        s: str,
        prop: Any,
        angle: float,
        ismath: bool | Literal["TeX"] = False,
        mtext: Any = None,
    ) -> None:
        features = mtext.get_fontfeatures() if mtext is not None else None
        language = mtext.get_language() if mtext is not None else None
        text_to_path = self._text2path
        if ismath == "TeX":
            # TextToPath normally lays TeX out at FONT_SCALE=100 and callers
            # scale the entire path back to the requested property size.  That
            # also (incorrectly) shrinks absolute TeX declarations such as
            # ``\font\a ptmr8r at 14pt\a`` by the outer 10/100 factor.  Lay
            # out a private TeX path at the actual property size instead: DVI
            # relative fonts remain relative, while absolute point sizes stay
            # absolute.  Never mutate RendererBase's shared TextToPath.
            text_to_path = TextToPath()
            text_to_path.FONT_SCALE = float(prop.get_size_in_points())
        vertices, codes = text_to_path.get_text_path(
            prop,
            s,
            ismath=ismath,
            features=features,
            language=language,
        )
        path = MplPath(vertices, codes)
        fontsize = self.points_to_pixels(prop.get_size_in_points())
        transform = (
            Affine2D().scale(fontsize / text_to_path.FONT_SCALE).rotate_deg(angle).translate(x, y)
        )
        glyph_path = self._path_segments(path, transform)
        if not glyph_path and not s:
            return
        style = self._style(gc, gc.get_rgb())
        style.update({"stroke": None, "linewidth": 0.0})
        glyph_path_resource = self.display_list.add_path_resource(glyph_path)
        font_resource = self.display_list.add_font_resource(
            {
                "family": list(prop.get_family()),
                "style": prop.get_style(),
                "variant": prop.get_variant(),
                "weight": prop.get_weight(),
                "stretch": prop.get_stretch(),
                "size_points": float(prop.get_size_in_points()),
            }
        )
        self.display_list.add(
            "text",
            text=str(s),
            glyph_path_resource=glyph_path_resource,
            position=[float(x), float(y)],
            angle=float(angle),
            ismath=ismath,
            font_resource=font_resource,
            style=style,
            **self._common(gc),
        )

    def draw_tex(
        self,
        gc: Any,
        x: float,
        y: float,
        s: str,
        prop: Any,
        angle: float,
        *,
        mtext: Any = None,
    ) -> None:
        self.draw_text(gc, x, y, s, prop, angle, ismath="TeX", mtext=mtext)

    def draw_markers(
        self,
        gc: Any,
        marker_path: MplPath,
        marker_trans: Any,
        path: MplPath,
        trans: Any,
        rgbFace: Any = None,
    ) -> None:
        path_vertices = np.asarray(path.vertices)
        if not path_vertices.size:
            return
        positions = np.empty((path_vertices.shape[0], 2), dtype="<f4")
        count = 0
        for vertices, _code in path.iter_segments(trans, simplify=False):
            if len(vertices):
                positions[count] = [float(vertices[-2]), float(vertices[-1])]
                count += 1
        if not count:
            return
        positions = np.ascontiguousarray(positions[:count])
        if not np.all(np.isfinite(positions)):
            raise DisplayListError("marker positions must be finite")
        marker_segments = self._path_segments(marker_path, marker_trans)
        path_resource = self.display_list.add_path_resource(marker_segments)
        positions_resource = self.display_list.add_array_resource(
            positions.tobytes(),
            dtype="<f4",
            shape=positions.shape,
        )
        self.display_list.add(
            "marker_collection",
            path_resource=path_resource,
            positions_resource=positions_resource,
            count=count,
            style=self._style(gc, rgbFace),
            **self._common(gc),
        )

    def draw_path_collection(
        self,
        gc: Any,
        master_transform: Any,
        paths: Any,
        all_transforms: Any,
        offsets: Any,
        offset_trans: Any,
        facecolors: Any,
        edgecolors: Any,
        linewidths: Any,
        linestyles: Any,
        antialiaseds: Any,
        urls: Any,
        offset_position: Any,
        *,
        hatchcolors: Any = None,
    ) -> None:
        iter_raw_paths = self._iter_collection_raw_paths  # ty: ignore[unresolved-attribute]
        raw_paths = list(iter_raw_paths(master_transform, paths, all_transforms))
        if not raw_paths:
            return
        path_resources = [
            self.display_list.add_path_resource(self._path_segments(path, transform))
            for path, transform in raw_paths
        ]
        path_ids = list(range(len(raw_paths)))
        if hatchcolors is None:
            hatchcolors = []
        try:
            offset_count = len(offsets)
        except TypeError:
            offset_count = 0
        capacity = max(len(path_ids), offset_count, 1)
        instances = np.zeros((capacity, _PATH_COLLECTION_BATCH_WIDTH), dtype="<f4")
        style_templates: list[dict[str, Any]] = []
        clips: list[dict[str, Any]] = []
        collected_urls: list[str] = []
        count = 0
        iter_collection = self._iter_collection  # ty: ignore[unresolved-attribute]
        for x, y, path_id, item_gc, face in iter_collection(
            gc,
            path_ids,
            offsets,
            offset_trans,
            facecolors,
            edgecolors,
            linewidths,
            linestyles,
            antialiaseds,
            urls,
            offset_position,
            hatchcolors=hatchcolors,
        ):
            if count == len(instances):
                grown = np.zeros((len(instances) * 2, _PATH_COLLECTION_BATCH_WIDTH), dtype="<f4")
                grown[:count] = instances
                instances = grown
            style = self._style(item_gc, face)
            fill = style.pop("fill")
            stroke = style.pop("stroke")
            linewidth = float(style.pop("linewidth"))
            opacity = float(style.pop("opacity"))
            antialiased = bool(style.pop("antialiased"))
            hatch_color = style.pop("hatch_color")
            if style.get("hatch") is None:
                # Matplotlib carries the current edge color through the GC's
                # inactive hatch fields.  It has no visible effect and would
                # otherwise manufacture one style template per collection
                # color, defeating the packed batch.
                style.pop("hatch_path", None)
                style.pop("hatch_tile_size", None)
                style.pop("hatch_linewidth", None)
            clip = self._clip(item_gc)
            url = item_gc.get_url()
            clip_index = -1 if clip is None else _intern_value(clip, clips)
            url_index = -1 if url is None else _intern_value(str(url), collected_urls)
            row = instances[count]
            row[:7] = [
                int(path_id),
                float(x),
                float(y),
                _intern_value(style, style_templates),
                clip_index,
                url_index,
                int(fill is not None),
            ]
            if fill is not None:
                row[7:11] = fill
            row[11] = int(stroke is not None)
            if stroke is not None:
                row[12:16] = stroke
            row[16:19] = [linewidth, opacity, int(antialiased)]
            row[19] = int(hatch_color is not None)
            if hatch_color is not None:
                row[20:24] = hatch_color
            count += 1
        instances = np.ascontiguousarray(instances[:count])
        if not np.all(np.isfinite(instances)):
            raise DisplayListError("path-collection instances must be finite")
        instances_resource = self.display_list.add_array_resource(
            instances.tobytes(),
            dtype="<f4",
            shape=instances.shape,
        )
        self.display_list.add(
            "path_collection",
            path_resources=path_resources,
            instances_resource=instances_resource,
            instances_schema=PATH_COLLECTION_BATCH_SCHEMA,
            count=count,
            style_templates=style_templates,
            clips=clips,
            urls=collected_urls,
            gid=gc.get_gid(),
        )

    def draw_image(
        self,
        gc: Any,
        x: float,
        y: float,
        im: Any,
        transform: Any = None,
    ) -> None:
        rgba = np.ascontiguousarray(im, dtype=np.uint8)
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError("Matplotlib images must be H-by-W RGBA uint8 arrays")
        # Matplotlib hands renderers image rows bottom-first.  Normalize the
        # shared resource to the top-first convention used by PNG, SVG, and
        # XY's native image blitter.
        rgba = np.ascontiguousarray(rgba[::-1])
        height, width = (int(value) for value in rgba.shape[:2])
        if width == 0 or height == 0:
            return
        from xy import _png

        png = _png.png_truecolor(width, height, rgba)
        resource = self.display_list.add_png_resource(png, width=width, height=height)
        self.display_list.add(
            "image",
            resource=resource,
            x=float(x),
            y=float(y),
            width=width,
            height=height,
            transform=_affine_values(transform) if transform is not None else None,
            interpolation="nearest" if transform is not None else "bilinear",
            alpha=float(gc.get_alpha()),
            **self._common(gc),
        )

    def draw_gouraud_triangles(
        self,
        gc: Any,
        triangles_array: Any,
        colors_array: Any,
        transform: Any,
    ) -> None:
        triangles = np.asarray(triangles_array, dtype=float)
        if not triangles.size:
            return
        transformed = transform.transform(triangles.reshape(-1, 2)).reshape(triangles.shape)
        colors = np.asarray(colors_array, dtype=float)
        if not np.all(np.isfinite(transformed)) or not np.all(np.isfinite(colors)):
            raise DisplayListError("Gouraud triangles and colors must be finite")
        if transformed.size + colors.size >= _PACKED_BATCH_MIN_VALUES:
            packed_triangles = np.ascontiguousarray(transformed, dtype="<f4")
            packed_colors = np.ascontiguousarray(colors, dtype="<f4")
            triangles_resource = self.display_list.add_array_resource(
                packed_triangles.tobytes(),
                dtype="<f4",
                shape=packed_triangles.shape,
            )
            colors_resource = self.display_list.add_array_resource(
                packed_colors.tobytes(),
                dtype="<f4",
                shape=packed_colors.shape,
            )
            self.display_list.add(
                "gouraud_triangles",
                triangles_resource=triangles_resource,
                colors_resource=colors_resource,
                count=len(transformed),
                clip=self._clip(gc),
                gid=gc.get_gid(),
            )
            return
        self.display_list.add(
            "gouraud_triangles",
            triangles=transformed.tolist(),
            colors=colors.tolist(),
            clip=self._clip(gc),
            gid=gc.get_gid(),
        )

    def draw_quad_mesh(
        self,
        gc: Any,
        master_transform: Any,
        meshWidth: int,
        meshHeight: int,
        coordinates: Any,
        offsets: Any,
        offsetTrans: Any,
        facecolors: Any,
        antialiased: bool,
        edgecolors: Any,
    ) -> None:
        coordinate_array = np.asarray(coordinates, dtype=float)
        transformed = master_transform.transform(coordinate_array.reshape(-1, 2)).reshape(
            coordinate_array.shape
        )
        offset_array = np.asarray(offsets, dtype=float)
        if offset_array.size:
            transformed_offsets = offsetTrans.transform(offset_array.reshape(-1, 2))
        else:
            transformed_offsets = np.array([[0.0, 0.0]])
        mesh_width = int(meshWidth)
        mesh_height = int(meshHeight)
        try:
            grid = transformed.reshape(mesh_height + 1, mesh_width + 1, 2)
        except ValueError as exc:
            raise DisplayListError("quad-mesh coordinates do not match its dimensions") from exc
        base_quads = np.stack(
            [
                grid[:-1, :-1],
                grid[:-1, 1:],
                grid[1:, 1:],
                grid[1:, :-1],
            ],
            axis=2,
        ).reshape(-1, 4, 2)
        quads = (
            base_quads[np.newaxis, :, :, :] + transformed_offsets[:, np.newaxis, np.newaxis, :]
        ).reshape(-1, 4, 2)
        quads = np.ascontiguousarray(quads, dtype="<f4")
        if not np.all(np.isfinite(quads)):
            raise DisplayListError("quad-mesh points must be finite")

        def packed_colors(values: Any, label: str) -> np.ndarray | None:
            colors = np.asarray(values, dtype=float)
            if not colors.size:
                return None
            if colors.ndim == 1:
                colors = colors.reshape(1, -1)
            else:
                colors = colors.reshape(-1, colors.shape[-1])
            if colors.shape[1] == 3:
                colors = np.concatenate([colors, np.ones((len(colors), 1))], axis=1)
            if colors.shape[1] != 4:
                raise DisplayListError(f"quad-mesh {label} must contain RGB or RGBA colors")
            if not np.all(np.isfinite(colors)):
                raise DisplayListError(f"quad-mesh {label} must be finite")
            selected = colors[np.arange(len(quads)) % len(colors)]
            return np.ascontiguousarray(selected, dtype="<f4")

        faces = packed_colors(facecolors, "facecolors")
        edges = packed_colors(edgecolors, "edgecolors") if edgecolors is not None else None
        points_resource = self.display_list.add_array_resource(
            quads.tobytes(),
            dtype="<f4",
            shape=quads.shape,
        )
        faces_resource = (
            self.display_list.add_array_resource(
                faces.tobytes(),
                dtype="<f4",
                shape=faces.shape,
            )
            if faces is not None
            else None
        )
        edges_resource = (
            self.display_list.add_array_resource(
                edges.tobytes(),
                dtype="<f4",
                shape=edges.shape,
            )
            if edges is not None
            else None
        )
        style = self._style(gc)
        style["antialiased"] = bool(antialiased)
        self.display_list.add(
            "quad_mesh",
            points_resource=points_resource,
            faces_resource=faces_resource,
            edges_resource=edges_resource,
            count=len(quads),
            style=style,
            clip=self._clip(gc),
            gid=gc.get_gid(),
        )

    def open_group(self, s: str, gid: str | None = None) -> None:
        self.display_list.add("group_open", name=str(s), gid=gid)

    def close_group(self, s: str) -> None:
        self.display_list.add("group_close", name=str(s))


class TimerXY(TimerBase):
    """An XY event-loop timer driven by the live host or ``flush_events``.

    The anywidget host sends event-loop heartbeats while a timer is active, and
    blocking ``pyplot.show()`` pumps the same canvas event loop outside a
    notebook.  No worker thread mutates Matplotlib artists.  Tests retain the
    deterministic :meth:`fire` hook.
    """

    def __init__(
        self,
        canvas: "FigureCanvasXY",
        interval: int | None = None,
        callbacks: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        self._canvas_ref = weakref.ref(canvas)
        self._running = False
        self._dispatching = False
        self._deadline = math.inf
        super().__init__(interval=interval, callbacks=callbacks)

    @property
    def running(self) -> bool:
        return self._running

    def _timer_start(self) -> None:
        canvas = self._canvas_ref()
        if canvas is None:
            return
        self._running = True
        self._deadline = time.monotonic() + self.interval / 1000
        canvas._timers.add(self)
        canvas._sync_widget_timer()

    def _timer_stop(self) -> None:
        self._running = False
        self._deadline = math.inf
        canvas = self._canvas_ref()
        if canvas is not None:
            canvas._timers.discard(self)
            canvas._sync_widget_timer()

    def _timer_set_interval(self) -> None:
        if self._running:
            self._deadline = time.monotonic() + self.interval / 1000
            canvas = self._canvas_ref()
            if canvas is not None:
                canvas._sync_widget_timer()

    def _timer_set_single_shot(self) -> None:
        return

    def fire(self) -> bool:
        """Run one timer turn; return whether the timer remains active."""
        if not self._running:
            return False
        if self._dispatching:
            return self._running

        # Schedule (or stop) before invoking callbacks.  A timer callback may
        # call ``canvas.flush_events()``; leaving the expired deadline in place
        # would recursively dispatch the same timer until the Python stack
        # failed.  Explicit callback stop/restart operations remain final
        # because nothing below overwrites their state.
        if self.single_shot:
            self.stop()
        else:
            self._deadline = time.monotonic() + self.interval / 1000
        self._dispatching = True
        try:
            self._on_timer()  # ty: ignore[unresolved-attribute]
        finally:
            self._dispatching = False
        return self._running

    def _fire_if_due(self, now: float) -> None:
        if self._running and not self._dispatching and now >= self._deadline:
            self.fire()


class _RegionXY:
    """Opaque canvas-region token used by the full-redraw blit protocol."""

    __slots__ = ("bbox", "generation")

    def __init__(self, bbox: tuple[float, float, float, float], generation: int) -> None:
        self.bbox = bbox
        self.generation = generation


class FigureCanvasXY(FigureCanvasBase):
    """Matplotlib canvas whose authoritative output is an XY display list."""

    filetypes = {  # noqa: RUF012 - Matplotlib defines this mutable class registry.
        "png": "Portable Network Graphics (XY native rasterizer)",
        "svg": "Scalable Vector Graphics (XY display list)",
        "html": "Standalone HTML (XY display list)",
        "json": "XY renderer display list",
    }
    fixed_dpi = None

    def __init__(self, figure: Any = None) -> None:
        super().__init__(figure)
        self.renderer: RendererXY | None = None
        self._last_key: tuple[float, float, float] | None = None
        self._timers: weakref.WeakSet[TimerXY] = weakref.WeakSet()
        self._draw_generation = 0
        self._widget: FigureCanvasXYWidget | None = None
        self._cursor_name = "pointer"

    @classmethod
    def get_default_filetype(cls) -> str:
        return str(matplotlib.rcParams.get("savefig.format") or "png")

    @property
    def fallback_used(self) -> bool:
        """Whether the most recently rendered display list used a fallback."""
        return bool(self.renderer and self.renderer.display_list.fallback_used)

    def get_renderer(self, *, cleared: bool = False) -> RendererXY:
        width, height = (float(value) for value in self.figure.bbox.size)
        key = width, height, float(self.figure.dpi)
        if self.renderer is None or self._last_key != key:
            self.renderer = RendererXY(width, height, self.figure.dpi)
            self._last_key = key
        elif cleared:
            self.renderer.clear()
        return self.renderer

    def draw(self, *args: Any, **kwargs: Any) -> None:
        renderer = self.get_renderer(cleared=True)
        wait_cursor = (
            self.toolbar._wait_cursor_for_draw_cm()  # ty: ignore[unresolved-attribute]
            if self.toolbar
            else nullcontext()
        )
        with wait_cursor:
            self.figure.draw(renderer)
            self._draw_generation += 1
            super().draw(*args, **kwargs)
        if self._widget is not None:
            self._widget.refresh(renderer.display_list)
        manager = getattr(self, "manager", None)
        if isinstance(manager, FigureManagerXY) and manager._browser_host is not None:
            manager._refresh_browser_host()

    @property
    def widget(self) -> FigureCanvasXYWidget:
        """Return the cached kernel-connected browser view for this canvas."""
        if self._widget is None:
            from .backend_xy_widget import FigureCanvasXYWidget

            self._widget = FigureCanvasXYWidget(self)
        return self._widget

    def get_widget(self) -> FigureCanvasXYWidget:
        """Method-form alias for environments that do not expose properties."""
        return self.widget

    def _timer_pump_interval(self) -> int:
        """Return the shortest active timer interval, or zero when idle."""
        intervals = [timer.interval for timer in self._timers if timer.running]
        return max(1, min(intervals)) if intervals else 0

    def _sync_widget_timer(self) -> None:
        """Keep every live browser heartbeat aligned with the timer registry."""
        if self._widget is not None:
            self._widget.sync_timer_interval()
        manager = getattr(self, "manager", None)
        if isinstance(manager, FigureManagerXY) and manager._browser_host is not None:
            manager._browser_host.refresh_timer(self._timer_pump_interval())

    def _browser_ui_state(self) -> dict[str, bool | str]:
        """Return browser chrome state without forcing widget or host creation."""
        toolbar = getattr(self, "toolbar", None)
        toolbar_enabled = isinstance(toolbar, NavigationToolbar2XY)
        return {
            "toolbar_enabled": toolbar_enabled,
            "toolbar_mode": str(getattr(toolbar, "mode", "")) if toolbar_enabled else "",
            "toolbar_message": str(getattr(toolbar, "message", "")),
            "toolbar_can_back": bool(
                toolbar_enabled and getattr(toolbar, "history_back_enabled", False)
            ),
            "toolbar_can_forward": bool(
                toolbar_enabled and getattr(toolbar, "history_forward_enabled", False)
            ),
            "cursor": self._cursor_name,
        }

    def _sync_browser_ui(self) -> None:
        """Synchronize toolbar, status, and cursor state with every live view."""
        state = self._browser_ui_state()
        if self._widget is not None:
            self._widget.sync_browser_ui(state)
        manager = getattr(self, "manager", None)
        host = getattr(manager, "_browser_host", None)
        if host is not None and not host.closed:
            host.refresh_ui(state)

    def set_cursor(self, cursor: Cursors) -> None:
        """Expose Matplotlib cursor changes to the browser canvas."""
        cursor_name = Cursors(cursor).name.lower()
        if self._cursor_name == cursor_name:
            return
        self._cursor_name = cursor_name
        self._sync_browser_ui()

    def copy_from_bbox(self, bbox: Any) -> _RegionXY:
        """Return an opaque region token for Matplotlib's blitting protocol.

        XY currently resolves blits with a complete redraw, so no pixel buffer
        is copied.  Retaining the requested bounds and draw generation still
        gives widgets and cursors the standard copy/restore lifecycle.
        """
        if self.renderer is None:
            self.draw()
        extents = tuple(float(value) for value in bbox.extents)
        if len(extents) != 4:
            raise ValueError("copy_from_bbox requires four bbox extents")
        return _RegionXY(cast(tuple[float, float, float, float], extents), self._draw_generation)

    def restore_region(
        self,
        region: _RegionXY,
        bbox: Any = None,
        xy: tuple[float, float] | None = None,
    ) -> None:
        """Accept a saved region; the following :meth:`blit` redraws fully."""
        if not isinstance(region, _RegionXY):
            raise TypeError("restore_region requires a region returned by copy_from_bbox")

    def blit(self, bbox: Any = None) -> None:
        """Honor blit requests as a complete redraw until region copies land."""
        self.draw()

    def new_timer(
        self,
        interval: int | None = None,
        callbacks: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> TimerXY:
        return TimerXY(self, interval=interval, callbacks=callbacks)

    def flush_events(self) -> None:
        manager = getattr(self, "manager", None)
        if isinstance(manager, FigureManagerXY):
            manager._pump_browser_host()
        now = time.monotonic()
        for timer in list(self._timers):
            timer._fire_if_due(now)

    def process_event(self, name: str, event: Any) -> None:
        """Deliver a backend event through Matplotlib's callback registry."""
        if name not in self.events:
            raise ValueError(f"unknown Matplotlib canvas event {name!r}")
        self.callbacks.process(name, event)

    def _render(self) -> DisplayList:
        self.draw()
        assert self.renderer is not None
        return self.renderer.display_list

    def print_svg(
        self,
        filename: str | os.PathLike[str] | TextIO | BinaryIO,
        *,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        _write_text(filename, self._render().to_svg(metadata=metadata))

    def print_html(
        self,
        filename: str | os.PathLike[str] | TextIO | BinaryIO,
        *,
        metadata: dict[str, Any] | None = None,
        title: str = "XY Matplotlib figure",
        **kwargs: Any,
    ) -> None:
        display_list = self._render()
        if metadata:
            display_list.metadata.update(metadata)
        _write_text(filename, display_list.to_html(title=title))

    def print_json(
        self,
        filename: str | os.PathLike[str] | TextIO | BinaryIO,
        *,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        display_list = self._render()
        if metadata:
            display_list.metadata.update(metadata)
        _write_text(filename, display_list.to_json(indent=2) + "\n")

    def print_png(
        self,
        filename: str | os.PathLike[str] | BinaryIO,
        *,
        metadata: dict[str, Any] | None = None,
        pil_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Render PNG through the XY display-list consumer, never Agg."""
        _write_bytes(filename, self._render().to_png())


class ToolbarXY(ToolContainerBase):
    """Backend-neutral tool container and foreign-widget staging area."""

    def __init__(self, toolmanager: Any = None) -> None:
        self.toolmanager = toolmanager
        self.items: list[dict[str, Any]] = []
        self.foreign_widgets: list[Any] = []
        self.toggled: dict[str, bool] = {}
        self.message = ""
        if toolmanager is not None:
            super().__init__(toolmanager)

    def add_toolitem(
        self,
        name: str,
        group: str,
        position: int,
        image: str | None,
        description: str | None,
        toggle: bool,
    ) -> None:
        item = {
            "name": name,
            "group": group,
            "image": image,
            "description": description,
            "toggle": bool(toggle),
        }
        group_indices = [
            index for index, candidate in enumerate(self.items) if candidate["group"] == group
        ]
        if position < 0 or position >= len(group_indices):
            insertion = group_indices[-1] + 1 if group_indices else len(self.items)
        else:
            insertion = group_indices[position]
        self.items.insert(insertion, item)
        if toggle:
            self.toggled[name] = False

    def toggle_toolitem(self, name: str, toggled: bool) -> None:
        if any(item["name"] == name for item in self.items):
            self.toggled[name] = bool(toggled)

    def remove_toolitem(self, name: str) -> None:
        self.items[:] = [item for item in self.items if item["name"] != name]
        self.toggled.pop(name, None)

    def set_message(self, s: str) -> None:
        self.message = str(s)

    def update(self) -> None:
        """Accept axes-change notifications from ``FigureManagerBase``."""
        return

    def insert(self, widget: Any, position: int) -> None:
        if position < 0 or position >= len(self.foreign_widgets):
            self.foreign_widgets.append(widget)
        else:
            self.foreign_widgets.insert(position, widget)

    def append(self, widget: Any) -> None:
        self.foreign_widgets.append(widget)


class NavigationToolbar2XY(NavigationToolbar2):
    """Behavior-complete navigation toolbar synchronized with browser chrome."""

    def __init__(self, canvas: FigureCanvasXY) -> None:
        self.foreign_widgets: list[Any] = []
        self.message = ""
        self.rubberband: tuple[float, float, float, float] | None = None
        self.history_back_enabled = False
        self.history_forward_enabled = False
        super().__init__(canvas)

    def set_message(self, s: str) -> None:
        self.message = str(s)
        cast(FigureCanvasXY, self.canvas)._sync_browser_ui()

    def set_history_buttons(self) -> None:
        stack = getattr(self, "_nav_stack", ())
        position = getattr(stack, "_pos", -1)
        self.history_back_enabled = position > 0
        self.history_forward_enabled = position < len(stack) - 1
        cast(FigureCanvasXY, self.canvas)._sync_browser_ui()

    def pan(self, *args: Any) -> None:
        super().pan(*args)
        cast(FigureCanvasXY, self.canvas)._sync_browser_ui()

    def zoom(self, *args: Any) -> None:
        super().zoom(*args)
        cast(FigureCanvasXY, self.canvas)._sync_browser_ui()

    def draw_rubberband(
        self,
        event: Any,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> None:
        self.rubberband = (float(x0), float(y0), float(x1), float(y1))

    def remove_rubberband(self) -> None:
        self.rubberband = None

    def save_figure(self, *args: Any) -> Any:
        """Report the standard unsupported status without a GUI file dialog."""
        return self.UNKNOWN_SAVED_STATUS

    def insert(self, widget: Any, position: int) -> None:
        if position < 0 or position >= len(self.foreign_widgets):
            self.foreign_widgets.append(widget)
        else:
            self.foreign_widgets.insert(position, widget)

    def append(self, widget: Any) -> None:
        self.foreign_widgets.append(widget)


class ContainerXY:
    """Minimal ordered widget container used by backend-embedding examples."""

    def __init__(self, canvas: FigureCanvasXY, toolbar: Any | None) -> None:
        self.children: list[Any] = [canvas]
        if toolbar is not None:
            self.children.append(toolbar)

    def pack_start(
        self,
        widget: Any,
        expand: bool = False,
        fill: bool = False,
        padding: int = 0,
    ) -> None:
        self.children.append(widget)

    def reorder_child(self, widget: Any, position: int) -> None:
        if widget not in self.children:
            return
        self.children.remove(widget)
        if position < 0 or position >= len(self.children):
            self.children.append(widget)
        else:
            self.children.insert(position, widget)

    def insert_child_after(self, widget: Any, sibling: Any) -> None:
        if widget in self.children:
            self.children.remove(widget)
        try:
            insertion = self.children.index(sibling) + 1
        except ValueError:
            insertion = len(self.children)
        self.children.insert(insertion, widget)


class FigureManagerXY(FigureManagerBase):
    """Manager for the live notebook widget and connected loopback host."""

    _toolbar2_class = NavigationToolbar2XY
    _toolmanager_toolbar_class = ToolbarXY

    def __init__(self, canvas: FigureCanvasXY, num: int) -> None:
        super().__init__(canvas, num)
        self.vbox = ContainerXY(canvas, self.toolbar)
        self._widget_displayed = False
        self._browser_host: LoopbackHost | None = None
        self._browser_opened = False

    def show(self) -> None:
        self.canvas.draw()
        ipython = sys.modules.get("IPython")
        shell = ipython.get_ipython() if ipython is not None else None
        if shell is not None:
            if not self._widget_displayed:
                from IPython.display import display  # noqa: PLC0415

                display(self.widget)
                self._widget_displayed = True
            return
        host = self._refresh_browser_host()
        if not self._browser_opened:
            try:
                opened = webbrowser.open(host.url)
            except BaseException:
                host.close()
                self._browser_host = None
                raise
            if opened is False:
                host.close()
                self._browser_host = None
                raise RuntimeError(f"could not open the XY browser host at {host.url}")
            self._browser_opened = True

    def _refresh_browser_host(self) -> LoopbackHost:
        """Create or refresh the authenticated live loopback browser host.

        The server owns no Matplotlib state: it serves cached frame snapshots
        and queues browser messages. :meth:`flush_events` dispatches those
        messages on Matplotlib's calling thread.
        """
        if self._browser_host is None or self._browser_host.closed:
            from .backend_xy_host import LoopbackHost  # noqa: PLC0415

            self._browser_host = LoopbackHost(self)
        canvas = cast(FigureCanvasXY, self.canvas)
        if canvas.renderer is not None:
            self._browser_host.refresh(
                canvas.renderer.display_list,
                generation=canvas._draw_generation,
                timer_interval=canvas._timer_pump_interval(),
                ui_state=canvas._browser_ui_state(),
            )
        return self._browser_host

    def _pump_browser_host(self) -> int:
        """Deliver any queued loopback events on the current thread."""
        if self._browser_host is None:
            return 0
        return self._browser_host.pump()

    @classmethod
    def start_main_loop(cls) -> None:
        """Pump XY timers on the caller's thread until all timers are idle."""
        from matplotlib._pylab_helpers import Gcf  # noqa: PLC0415

        try:
            while True:
                managers = [
                    manager
                    for manager in Gcf.get_all_fig_managers()
                    if isinstance(manager.canvas, FigureCanvasXY)
                ]
                canvases = [cast(FigureCanvasXY, manager.canvas) for manager in managers]
                timers = [
                    timer for canvas in canvases for timer in list(canvas._timers) if timer.running
                ]
                live_hosts = [
                    manager._browser_host
                    for manager in managers
                    if isinstance(manager, FigureManagerXY)
                    and manager._browser_host is not None
                    and not manager._browser_host.closed
                ]
                if not timers and not live_hosts:
                    return
                now = time.monotonic()
                for canvas in canvases:
                    canvas.flush_events()
                deadlines = [timer._deadline for timer in timers if timer.running]
                delay = max(0.001, min(0.01, min(deadlines) - now)) if deadlines else 0.01
                time.sleep(delay)
        except KeyboardInterrupt:
            return

    @property
    def widget(self) -> FigureCanvasXYWidget:
        """Return the canvas's cached live notebook/browser widget."""
        return cast(FigureCanvasXY, self.canvas).widget

    def get_widget(self) -> FigureCanvasXYWidget:
        """Method-form alias for :attr:`widget`."""
        return self.widget

    def resize(self, w: int, h: int) -> None:
        dpi = self.canvas.figure.dpi
        self.canvas.figure.set_size_inches(w / dpi, h / dpi, forward=False)
        self.canvas.draw_idle()

    def destroy(self) -> None:
        canvas = cast(FigureCanvasXY, self.canvas)
        for timer in list(canvas._timers):
            timer.stop()
        if canvas._widget is not None:
            canvas._widget.close()
            canvas._widget = None
        if self._browser_host is not None:
            self._browser_host.close()
            self._browser_host = None
        super().destroy()


FigureCanvasXY.manager_class = FigureManagerXY  # ty: ignore[invalid-assignment]
FigureCanvas = FigureCanvasXY
FigureManager = FigureManagerXY


@_Backend.export
class _BackendXY(_Backend):
    backend_version = "1"
    FigureCanvas = FigureCanvasXY
    FigureManager = FigureManagerXY
    mainloop = FigureManagerXY.start_main_loop


__all__ = [
    "ContainerXY",
    "FigureCanvas",
    "FigureCanvasXY",
    "FigureManager",
    "FigureManagerXY",
    "NavigationToolbar2XY",
    "RendererXY",
    "TimerXY",
    "ToolbarXY",
]
