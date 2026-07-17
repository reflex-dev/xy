"""Returned handles: the mutation surface of matplotlib's artist model.

A handle wraps the *declarative spec entry* an Axes call appended — mutating
it (``set_ydata``, ``set_color``, ``remove``) edits the spec and invalidates
the Axes' cached chart, so the next render/export rebuilds. This covers the
dominant mutation idioms without reproducing matplotlib's artist graph.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from itertools import pairwise
from typing import Any, Optional

import numpy as np

from ._colors import resolve_color
from ._rc import rcParams
from ._transforms import Bbox, IdentityTransform


def unit_converted_values(values: Any) -> Any:
    """Datetime-like values in the engine's converted unit — f64 ms since
    epoch (columns.py); every other dtype is already its own converted form."""
    from xy.columns import _datetime_to_float_ms, _is_datetime_object_array

    array = np.asanyarray(values)
    if np.issubdtype(array.dtype, np.datetime64) or _is_datetime_object_array(array.reshape(-1)):
        converted, _ = _datetime_to_float_ms(array, 0)
        return converted
    return values


def _set_entry_clim(artist: "Artist", vmin: Any = None, vmax: Any = None) -> None:
    """Set a mappable entry's color domain, autoscaling any side left as None."""
    if vmax is None and isinstance(vmin, (tuple, list)):
        vmin, vmax = vmin
    entry = artist._entry
    if vmin is None or vmax is None:
        kwargs = entry.get("kwargs", {})
        values = entry.get("source_z", kwargs.get("color", entry.get("z")))
        try:
            numeric = np.asarray(values, dtype=np.float64)
            finite = numeric[np.isfinite(numeric)]
        except (TypeError, ValueError):
            finite = np.asarray([], dtype=np.float64)
        fallback = (
            float(finite.min()) if finite.size else 0.0,
            float(finite.max()) if finite.size else 1.0,
        )
        current = entry.get("kwargs", {}).get("domain", fallback)
        vmin = current[0] if vmin is None else vmin
        vmax = current[1] if vmax is None else vmax
    domain = (float(vmin), float(vmax))
    entry["kwargs"]["domain"] = domain
    axes = artist._axes
    # A live colorbar derived from this mappable tracks the new limits, as in
    # matplotlib where the colorbar shares the mappable's norm.
    if getattr(axes, "_colorbar_source", None) is entry and axes._colorbar is not None:
        axes._colorbar["domain"] = [domain[0], domain[1]]
    artist._touch()


class Artist:
    def __init__(self, axes: Any, entry: dict[str, Any]) -> None:
        self._axes = axes
        self._entry = entry  # the mutable spec dict the Axes rendered from
        self._visible = True
        self._visible_opacity = float(entry.get("kwargs", {}).get("opacity", 1.0))
        self._zorder = float(entry.get("_zorder", 0.0))
        self._clip_on = bool(entry.get("kwargs", {}).get("clip_on", True))
        self._transform: Any = axes.transData if axes is not None else IdentityTransform()
        self._rasterized = False
        if axes is not None:
            axes._register_artist(self)

    def _touch(self) -> None:
        self._axes._invalidate()

    def remove(self) -> None:
        self._axes._remove_entry(self._entry)
        self._axes._unregister_artist(self)

    def set_label(self, label: str) -> None:
        self._entry["kwargs"]["name"] = str(label)
        self._touch()

    def get_label(self) -> Optional[str]:
        return self._entry["kwargs"].get("name")

    def set_alpha(self, alpha: float) -> None:
        self._visible_opacity = float(alpha)
        if self._visible:
            self._entry["kwargs"]["opacity"] = float(alpha)
        self._touch()

    def get_alpha(self) -> Any:
        if not self._visible:
            return self._visible_opacity
        return self._entry["kwargs"].get("opacity")

    def set_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._visible:
            return
        if not visible:
            self._visible_opacity = float(self._entry["kwargs"].get("opacity", 1.0))
        self._visible = visible
        self._entry["kwargs"]["opacity"] = self._visible_opacity if visible else 0.0
        self._touch()

    def get_visible(self) -> bool:
        return self._visible

    def set_zorder(self, level: float) -> None:
        self._zorder = float(level)
        self._entry["_zorder"] = self._zorder
        host = self._axes._y2_of or self._axes
        host._entries.sort(key=lambda item: float(item.get("_zorder", 0.0)))
        self._touch()

    def get_zorder(self) -> float:
        return self._zorder

    def set_clip_on(self, enabled: bool) -> None:
        if not enabled:
            raise NotImplementedError(
                f"{type(self).__name__} unclipped rendering is not supported by xy.pyplot"
            )
        self._clip_on = bool(enabled)
        self._touch()

    def get_clip_on(self) -> bool:
        return self._clip_on

    def set_clip_path(self, path: Any) -> None:
        raise NotImplementedError(
            f"{type(self).__name__} clip paths are not supported; image clip paths are supported"
        )

    def get_clip_path(self) -> Any:
        return self._entry.get("clip_path")

    def set_transform(self, transform: Any) -> None:
        if not hasattr(transform, "transform"):
            raise TypeError("transform must provide a transform(xy) method")
        coordinate_space = getattr(transform, "coordinate_space", "data")
        if coordinate_space != "data" or not hasattr(self._transform, "inverted"):
            raise NotImplementedError(
                f"{type(self).__name__} requires an invertible data-coordinate transform"
            )
        if hasattr(transform, "inverted"):
            try:
                transform.inverted()  # a singular matrix must fail this call,
            except np.linalg.LinAlgError as error:  # not the next set_transform
                raise ValueError("set_transform() requires an invertible transform") from error
        old_inverse = self._transform.inverted()

        def convert(x: Any, y: Any) -> tuple[np.ndarray, np.ndarray]:
            xa, ya = np.broadcast_arrays(x, y)
            points = np.column_stack((xa.ravel(), ya.ravel()))
            made = np.asarray(transform.transform(old_inverse.transform(points)), dtype=float)
            return made[:, 0].reshape(xa.shape), made[:, 1].reshape(ya.shape)

        if "x" in self._entry and "y" in self._entry:
            self._entry["x"], self._entry["y"] = convert(self._entry["x"], self._entry["y"])
        elif self._entry.get("kind") == "@mark":
            factory = self._entry.get("factory")
            pairs = {
                "segments": ((0, 1), (2, 3)),
                "triangle_mesh": ((0, 1), (2, 3), (4, 5)),
                "step": ((0, 1),),
                "stem": ((0, 1),),
                "errorbar": ((0, 1),),
            }.get(factory)
            if pairs is None:
                raise NotImplementedError(
                    f"{type(self).__name__} transform is not supported for {factory!r} geometry"
                )
            args = list(self._entry["args"])
            for x_index, y_index in pairs:
                args[x_index], args[y_index] = convert(args[x_index], args[y_index])
            self._entry["args"] = tuple(args)
        else:
            raise NotImplementedError(
                f"{type(self).__name__} transform is not supported for this geometry"
            )
        for marker_entry in self._marker_entries():
            if marker_entry is not self._entry:
                marker_entry["x"], marker_entry["y"] = convert(marker_entry["x"], marker_entry["y"])
        self._transform = transform
        self._touch()

    def get_transform(self) -> Any:
        return self._transform

    def set_rasterized(self, rasterized: bool) -> None:
        if rasterized:
            raise NotImplementedError(
                f"{type(self).__name__} selective rasterization is not supported by xy.pyplot; "
                "PNG export rasterizes everything already"
            )
        self._rasterized = bool(rasterized)

    def get_rasterized(self) -> bool:
        return self._rasterized

    def set_color(self, color: Any) -> None:
        self._entry["kwargs"]["color"] = resolve_color(color)
        self._touch()

    def get_color(self) -> Any:
        return self._entry["kwargs"].get("color")

    def _marker_entries(self) -> list[dict[str, Any]]:
        """Return marker specs controlled by this matplotlib-style handle.

        ``plot(..., marker=...)`` is represented internally as a line entry
        followed by a scatter overlay.  Matplotlib exposes one ``Line2D`` for
        both, so visible marker mutations need to follow that adjacent overlay.
        Marker-only plots are already backed directly by a scatter entry.
        """

        if self._entry.get("kind") == "scatter":
            return [self._entry]

        entries = getattr(self._axes, "_entries", [])
        try:
            index = next(i for i, entry in enumerate(entries) if entry is self._entry)
        except StopIteration:
            return []
        if index + 1 >= len(entries):
            return []

        candidate = entries[index + 1]
        if candidate.get("kind") != "scatter":
            return []
        kwargs = candidate.get("kwargs", {})
        if "symbol" not in kwargs:
            return []
        return [candidate]

    def set_markerfacecolor(self, color: Any) -> None:
        for entry in self._marker_entries():
            entry["kwargs"]["color"] = resolve_color(color)
        self._touch()

    set_mfc = set_markerfacecolor

    def set_markeredgecolor(self, color: Any) -> None:
        for entry in self._marker_entries():
            if isinstance(color, str) and color.lower() == "none":
                old_width = float(entry["kwargs"].get("stroke_width", 0.0))
                entry["kwargs"].pop("stroke", None)
                entry["kwargs"].pop("stroke_width", None)
                entry["kwargs"]["size"] = max(
                    0.0, float(entry["kwargs"].get("size", 0.0)) - old_width
                )
            else:
                if "stroke_width" not in entry["kwargs"]:
                    width = float(rcParams["lines.markeredgewidth"]) * self._axes._point_scale()
                    entry["kwargs"]["stroke_width"] = width
                    entry["kwargs"]["size"] = float(entry["kwargs"].get("size", 0.0)) + width
                entry["kwargs"]["stroke"] = resolve_color(color)
        self._touch()

    set_mec = set_markeredgecolor

    def set_markersize(self, size: Any) -> None:
        # Matplotlib specifies Line2D marker size in points; xy's scatter mark
        # consumes output-pixel diameters at the owning figure's DPI.
        for entry in self._marker_entries():
            stroke_width = float(entry["kwargs"].get("stroke_width", 0.0))
            entry["kwargs"]["size"] = float(size) * self._axes._point_scale() + stroke_width
        self._touch()

    set_ms = set_markersize


class Line2D(Artist):
    """Handle for plt.plot lines (and their marker overlays)."""

    @staticmethod
    def _segment_args_from_xy(x: Any, y: Any) -> tuple[Any, Any, Any, Any]:
        xv, yv = np.asarray(x), np.asarray(y)
        try:
            finite_pairs = np.isfinite(xv.astype(np.float64)) & np.isfinite(yv.astype(np.float64))
        except (TypeError, ValueError):
            finite_pairs = np.ones(len(xv), dtype=bool)
        keep = finite_pairs[:-1] & finite_pairs[1:]
        return xv[:-1][keep], yv[:-1][keep], xv[1:][keep], yv[1:][keep]

    @staticmethod
    def _same_data(left: Any, right: Any) -> bool:
        try:
            return bool(np.array_equal(np.asarray(left), np.asarray(right), equal_nan=True))
        except TypeError:
            return bool(
                np.array_equal(np.asarray(left, dtype=object), np.asarray(right, dtype=object))
            )

    def _sync_marker_data(self, key: str, old_value: Any, value: Any) -> None:
        for entry in self._marker_entries():
            if key not in entry:
                continue
            if self._same_data(entry[key], old_value):
                entry[key] = value

    def _set_xy(self, index: int, value: Any) -> None:
        key = "x" if index == 0 else "y"
        if self._entry["kind"] == "@mark" and self._entry.get("factory") == "step":
            old_value = self._entry.get(key)
            args = list(self._entry["args"])
            args[index] = value
            self._entry["args"] = tuple(args)
            self._entry[key] = value
            self._sync_marker_data(key, old_value, value)
            return
        if key not in self._entry:
            raise NotImplementedError(
                f"set_{key}data is not supported for Line2D handles without retained data"
            )
        old_value = self._entry[key]
        self._entry[key] = value
        if self._entry["kind"] == "@mark" and self._entry.get("factory") == "segments":
            self._entry["args"] = self._segment_args_from_xy(self._entry["x"], self._entry["y"])
        self._sync_marker_data(key, old_value, value)

    def set_data(self, x: Any, y: Any) -> None:
        self._set_xy(0, x)
        self._set_xy(1, y)
        self._touch()

    def set_xdata(self, x: Any) -> None:
        self._set_xy(0, x)
        self._touch()

    def set_ydata(self, y: Any) -> None:
        self._set_xy(1, y)
        self._touch()

    def get_xdata(self, orig: bool = True) -> Any:
        # orig=False asks for matplotlib's unit-converted floats.
        data = self._entry["x"]
        return data if orig else unit_converted_values(data)

    def get_ydata(self, orig: bool = True) -> Any:
        data = self._entry["y"]
        return data if orig else unit_converted_values(data)

    def set_linewidth(self, w: float) -> None:
        self._entry["kwargs"]["width"] = float(w)
        self._touch()

    set_lw = set_linewidth

    def set_dashes(self, sequence: Any) -> None:
        self._entry["kwargs"]["dash"] = [float(value) for value in sequence]
        self._touch()

    def set_dash_capstyle(self, style: Any) -> None:
        raise NotImplementedError("xy.pyplot does not support dash cap style mutation")

    def set_solid_capstyle(self, style: Any) -> None:
        raise NotImplementedError("xy.pyplot does not support solid cap style mutation")

    def set_gapcolor(self, color: Any) -> None:
        raise NotImplementedError("xy.pyplot does not support gapcolor mutation")


class PathCollection(Artist):
    """Handle for plt.scatter marks."""

    def get_array(self) -> Any:
        return self._entry.get("source_array", self._entry.get("kwargs", {}).get("color"))

    def get_offsets(self) -> Any:
        return np.column_stack((self._entry.get("x", []), self._entry.get("y", [])))

    def set_offsets(self, xy: Any) -> None:
        import numpy as np

        arr = np.asarray(xy, dtype=np.float64)
        self._entry["x"] = arr[:, 0]
        self._entry["y"] = arr[:, 1]
        self._touch()

    def legend_elements(
        self, prop: str = "colors", num: Any = "auto", **kwargs: Any
    ) -> tuple[list["PathCollection"], list[str]]:
        import numpy as np

        del kwargs
        values = self._entry["kwargs"].get("size" if prop == "sizes" else "color")
        try:
            array = np.asarray(values, dtype=np.float64).reshape(-1)
        except (TypeError, ValueError):
            array = np.arange(1, dtype=np.float64)
        unique = np.unique(array[np.isfinite(array)])
        count = 5 if num == "auto" else max(1, int(num))
        chosen = unique if len(unique) <= count else np.linspace(unique.min(), unique.max(), count)
        return [self] * len(chosen), [f"{value:g}" for value in chosen]

    @property
    def cmap(self) -> Any:
        from . import _colors

        return _colors.Cmap(self._entry["kwargs"].get("colormap", "viridis"))

    def set_clim(self, vmin: Any = None, vmax: Any = None) -> None:
        _set_entry_clim(self, vmin, vmax)

    def get_cmap(self) -> Any:
        return self.cmap


class AxesImage(Artist):
    """Image handle with the scalar-mappable surface used by gallery helpers."""

    @property
    def axes(self) -> Any:
        return self._axes

    def get_array(self) -> Any:
        return self._entry.get("source_z", self._entry["z"])

    def get_cmap(self) -> Any:
        from ._colors import Cmap

        return Cmap(self._entry["kwargs"].get("colormap", "viridis"))

    def get_extent(self) -> tuple[float, float, float, float]:
        if "extent" in self._entry:
            return tuple(self._entry["extent"])
        z = np.asarray(self._entry["z"])
        x = self._entry["kwargs"].get("x")
        y = self._entry["kwargs"].get("y")
        if x is None or y is None:
            return (-0.5, z.shape[1] - 0.5, -0.5, z.shape[0] - 0.5)
        xv, yv = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        dx = (xv[-1] - xv[0]) / max(1, len(xv) - 1) / 2
        dy = (yv[-1] - yv[0]) / max(1, len(yv) - 1) / 2
        return (float(xv[0] - dx), float(xv[-1] + dx), float(yv[0] - dy), float(yv[-1] + dy))

    def set_data(self, *args: Any) -> None:
        import numpy as np

        if len(args) == 1:
            self._entry["z"] = np.asarray(args[0])
        elif len(args) == 3:
            x, y, z = args
            self._entry["z"] = np.asarray(z)
            self._entry["kwargs"]["x"] = np.asarray(x)
            self._entry["kwargs"]["y"] = np.asarray(y)
        else:
            raise TypeError("set_data expects image data or x, y, image data")
        self._touch()

    def set_clip_path(self, path: Any) -> None:
        self._entry["clip_path"] = path
        grid = np.asarray(self._entry["z"])
        rows, cols = grid.shape[:2]
        left, right, bottom, top = self.get_extent()
        xs = np.linspace(
            left + (right - left) / (2 * cols), right - (right - left) / (2 * cols), cols
        )
        ys = np.linspace(
            bottom + (top - bottom) / (2 * rows), top - (top - bottom) / (2 * rows), rows
        )
        xx, yy = np.meshgrid(xs, ys)
        if hasattr(path, "center") and hasattr(path, "radius"):
            cx, cy = path.center
            mask = (xx - float(cx)) ** 2 + (yy - float(cy)) ** 2 <= float(path.radius) ** 2
        elif hasattr(path, "get_path"):
            points = np.column_stack((xx.reshape(-1), yy.reshape(-1)))
            mask = path.get_path().contains_points(points).reshape(rows, cols)
        else:
            self._touch()
            return
        if grid.ndim == 3:
            rgba = np.asarray(grid, dtype=np.float64)
            if np.nanmax(rgba[..., :3]) > 1.0:
                rgba[..., :3] /= 255.0
            if rgba.shape[-1] == 3:
                rgba = np.dstack((rgba, np.ones((rows, cols), dtype=float)))
            rgba[..., 3] *= mask
            self._entry["z"] = rgba
        else:
            self._entry["z"] = np.where(mask, grid, np.nan)
        self._touch()

    def set_transform(self, transform: Any) -> None:
        self._transform = transform
        self._entry["transform"] = transform
        if not hasattr(transform, "transform") or not hasattr(transform, "inverted"):
            self._touch()
            return
        grid = np.asarray(self._entry["z"])
        rows, cols = grid.shape[:2]
        left, right, bottom, top = self.get_extent()
        corners = np.asarray([[left, bottom], [right, bottom], [right, top], [left, top]])
        transformed = np.asarray(transform.transform(corners), dtype=float)
        x0, y0 = np.min(transformed, axis=0)
        x1, y1 = np.max(transformed, axis=0)
        out_cols = max(2, cols)
        out_rows = max(2, rows)
        xs = np.linspace(x0, x1, out_cols)
        ys = np.linspace(y0, y1, out_rows)
        xx, yy = np.meshgrid(xs, ys)
        source = np.asarray(
            transform.inverted().transform(np.column_stack((xx.reshape(-1), yy.reshape(-1))))
        )
        col = np.rint((source[:, 0] - left) / (right - left) * (cols - 1)).astype(int)
        row = np.rint((source[:, 1] - bottom) / (top - bottom) * (rows - 1)).astype(int)
        valid = (col >= 0) & (col < cols) & (row >= 0) & (row < rows)
        if grid.ndim == 2:
            warped = np.full((out_rows, out_cols), np.nan, dtype=float)
            warped.reshape(-1)[valid] = grid[row[valid], col[valid]]
            # Scalar heatmaps encode missing values through a quantized scalar
            # texture, where NaN cannot carry alpha reliably.  Convert the
            # transformed result to RGBA so pixels outside the transformed
            # image are genuinely transparent rather than a black rectangle.
            from xy._svg import _lut

            finite = warped[np.isfinite(warped)]
            domain = self._entry["kwargs"].get("domain")
            if domain is None:
                lo = float(finite.min()) if finite.size else 0.0
                hi = float(finite.max()) if finite.size else 1.0
            else:
                lo, hi = map(float, domain)
            normalized = np.clip((warped - lo) / ((hi - lo) or 1.0), 0.0, 1.0)
            rgb = _lut(
                self._entry["kwargs"].get("colormap", "viridis"),
                np.nan_to_num(normalized, nan=0.0).reshape(-1),
            ).reshape(warped.shape + (3,))
            warped = np.dstack((rgb / 255.0, np.isfinite(warped).astype(np.float64)))
        else:
            channels = grid.shape[-1]
            warped = np.zeros((out_rows, out_cols, max(4, channels)), dtype=float)
            if channels == 3:
                warped[..., 3] = 0.0
            warped.reshape(-1, warped.shape[-1])[valid, :channels] = grid[row[valid], col[valid]]
            if channels == 3:
                warped.reshape(-1, 4)[valid, 3] = 1.0
        self._entry["z"] = warped
        self._entry["kwargs"]["x"] = xs
        self._entry["kwargs"]["y"] = ys
        self._axes._aspect_bounds = (float(x0), float(x1), float(y0), float(y1))
        self._touch()

    def set_clim(self, vmin: Any = None, vmax: Any = None) -> None:
        _set_entry_clim(self, vmin, vmax)

    def norm(self, value: Any) -> Any:
        import numpy as np

        data = np.asarray(self._entry["z"], dtype=np.float64)
        domain = self._entry["kwargs"].get("domain")
        lo, hi = domain if domain is not None else (np.nanmin(data), np.nanmax(data))
        return np.clip((np.asarray(value) - lo) / ((hi - lo) or 1.0), 0.0, 1.0)


class BarContainer(Artist):
    """Handle for plt.bar/barh groups."""

    def __init__(self, axes: Any, entry: dict[str, Any]) -> None:
        super().__init__(axes, entry)
        self.datavalues = entry.get("y")
        self.orientation = entry.get("kwargs", {}).get("orientation", "vertical")
        self.errorbar = None
        axes._register_container(self)

    def remove(self) -> None:
        super().remove()
        self._axes._unregister_container(self)

    @property
    def position_centers(self) -> Any:
        return self._entry.get("x")

    @property
    def bottoms(self) -> Any:
        import numpy as np

        values = np.asarray(self.datavalues, dtype=np.float64)
        base = self._entry.get("kwargs", {}).get("base", 0.0)
        return np.broadcast_to(np.asarray(base, dtype=np.float64), values.shape)

    @property
    def tops(self) -> Any:
        import numpy as np

        return self.bottoms + np.asarray(self.datavalues, dtype=np.float64)


class StepPatch(Artist):
    """Handle for ``stairs`` output backed by a compact core stairs mark."""

    def get_data(self) -> tuple[Any, Any, Any]:
        return (
            self._entry["values"],
            self._entry.get("edges"),
            self._entry["kwargs"].get("base", self._entry.get("baseline", 0.0)),
        )


class StemContainer:
    """Small tuple-compatible analogue of matplotlib's StemContainer."""

    def __init__(self, artist: Artist) -> None:
        self.markerline = artist
        self.stemlines = artist
        self.baseline = artist
        artist._axes._register_container(self)

    def __iter__(self) -> Iterator[Any]:
        return iter((self.markerline, self.stemlines, self.baseline))

    def remove(self) -> None:
        self.stemlines.remove()
        self.stemlines._axes._unregister_container(self)


class ErrorbarContainer:
    """Tuple-compatible errorbar handle without reproducing mpl's artist graph."""

    def __init__(self, artist: Artist, data_line: Optional[Line2D] = None) -> None:
        self.lines = (data_line, (), (artist,))
        self.has_xerr = artist._entry["kwargs"].get("xerr") is not None
        self.has_yerr = artist._entry["kwargs"].get("yerr") is not None
        self._artist = artist
        artist._axes._register_container(self)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.lines)

    def remove(self) -> None:
        self._artist.remove()
        self._artist._axes._unregister_container(self)


class ContourSet(Artist):
    """Contour result exposing the commonly inspected compatibility fields."""

    @property
    def levels(self) -> Any:
        return self._entry.get("levels", self._entry["kwargs"].get("levels"))

    @property
    def cmap(self) -> Any:
        from ._colors import Cmap

        return Cmap(self._entry["kwargs"].get("colormap", "viridis"))

    def set(self, **kwargs: Any) -> "ContourSet":
        path_effects = kwargs.pop("path_effects", None)
        if path_effects:
            effect = next(
                (item for item in path_effects if "TickedStroke" in type(item).__name__),
                None,
            )
            if effect is not None:
                from xy import kernels

                z = np.asarray(self._entry["args"][0], dtype=np.float64)
                x = self._entry["kwargs"].get("x")
                y = self._entry["kwargs"].get("y")
                x = np.arange(z.shape[1], dtype=float) if x is None else np.asarray(x, dtype=float)
                y = np.arange(z.shape[0], dtype=float) if y is None else np.asarray(y, dtype=float)
                levels = np.asarray(self._entry["kwargs"].get("levels"), dtype=np.float64)
                x0, x1, y0, y1, _ = kernels.marching_squares(z, x, y, levels)
                stride = max(1, int(round(float(getattr(effect, "_spacing", 10.0)) / 3.0)))
                choose = np.arange(len(x0)) % stride == 0
                x0, x1, y0, y1 = (values[choose] for values in (x0, x1, y0, y1))
                dx, dy = x1 - x0, y1 - y0
                magnitude = np.hypot(dx, dy)
                valid = magnitude > 0
                dx, dy, magnitude = dx[valid], dy[valid], magnitude[valid]
                mx, my = (x0[valid] + x1[valid]) * 0.5, (y0[valid] + y1[valid]) * 0.5
                angle = np.deg2rad(float(getattr(effect, "_angle", 45.0)))
                ux, uy = dx / magnitude, dy / magnitude
                tx = ux * np.cos(angle) - uy * np.sin(angle)
                ty = ux * np.sin(angle) + uy * np.cos(angle)
                spacing = min(
                    np.nanmedian(np.abs(np.diff(x))) if len(x) > 1 else 1.0,
                    np.nanmedian(np.abs(np.diff(y))) if len(y) > 1 else 1.0,
                )
                length = spacing * float(getattr(effect, "_length", 1.4)) * 3.0
                self._axes._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": (mx, my, mx + tx * length, my + ty * length),
                        "kwargs": {
                            "color": self._entry["kwargs"].get("color", "#222222"),
                            "width": self._entry["kwargs"].get("width", 1.1),
                            "opacity": self._entry["kwargs"].get("opacity", 1.0),
                        },
                    },
                )
        if "linewidth" in kwargs:
            self._entry["kwargs"]["width"] = float(kwargs.pop("linewidth"))
        self._touch()
        return self

    def get_linewidth(self) -> list[float]:
        return [float(self._entry["kwargs"].get("width", 1.1))]

    def set_linewidth(self, width: Any) -> None:
        self._entry["kwargs"]["width"] = float(np.asarray(width).reshape(-1)[0])
        self._touch()

    def set_linestyle(self, style: Any) -> None:
        self._entry["linestyle"] = style
        self._touch()

    def legend_elements(self, **kwargs: Any) -> tuple[list["ContourSet"], list[str]]:
        formatter = kwargs.pop("str_format", str)
        levels = np.asarray(self.levels).reshape(-1)
        labels = [
            f"{formatter(float(lo))} < x <= {formatter(float(hi))}" for lo, hi in pairwise(levels)
        ]
        return [self] * len(labels), labels


class PolyCollection(Artist):
    """Generic collection handle used by adapter-composed chart families."""

    def set_clim(self, vmin: Any = None, vmax: Any = None) -> None:
        _set_entry_clim(self, vmin, vmax)


class Wedge(PolyCollection):
    """Pie wedge backed by a grouped subset of one native sector mesh."""


class PieContainer:
    """Matplotlib 3.11-compatible pie result with legacy tuple unpacking."""

    def __init__(
        self,
        wedges: list[Wedge],
        values: Any,
        normalize: bool,
        texts: list["Text"],
        autotexts: list["Text"],
    ) -> None:
        import numpy as np

        self.wedges = wedges
        self.values = np.asarray(values, dtype=np.float64)
        total = float(np.sum(self.values)) if normalize else 1.0
        self.fracs = self.values / total
        self.normalize = bool(normalize)
        self._texts: list[list[Text]] = [texts]
        if autotexts:
            self._texts.append(autotexts)

    @property
    def texts(self) -> list[list["Text"]]:
        return self._texts

    def add_texts(self, texts: list["Text"]) -> None:
        self._texts.append(texts)

    def remove(self) -> None:
        for wedge in self.wedges:
            wedge.remove()
        for group in self._texts:
            for item in group:
                item.remove()

    def __iter__(self) -> Iterator[list[Any]]:
        """Keep the pre-3.11 ``wedges, texts[, autotexts]`` idiom working."""
        yield self.wedges
        yield self._texts[0] if self._texts else []
        if len(self._texts) > 1:
            yield self._texts[1]


class GroupedBarReturn:
    """Provisional Matplotlib 3.11 grouped-bar result container."""

    def __init__(self, bar_containers: list[BarContainer]) -> None:
        self.bar_containers = bar_containers

    def remove(self) -> None:
        for container in self.bar_containers:
            container.remove()


class Table:
    """Composite table handle backed by generic mesh, segment, and text marks."""

    def __init__(self, artists: list[Artist], cells: dict[tuple[int, int], "Text"]) -> None:
        self._artists = artists
        self._cells = cells
        if artists:
            self._axes = artists[0]._axes
            self._axes._register_artist(self)

    def get_celld(self) -> dict[tuple[int, int], "Text"]:
        return dict(self._cells)

    def remove(self) -> None:
        for artist in self._artists:
            artist.remove()
        if hasattr(self, "_axes"):
            self._axes._unregister_artist(self)


class Text(Artist):
    """Small mutable text handle for pie labels and percentage annotations."""

    def set_text(self, text: str) -> None:
        x, y, _old = self._entry["args"]
        self._entry["args"] = (x, y, str(text))
        self._touch()

    def get_text(self) -> str:
        return str(self._entry["args"][2])

    def get_window_extent(self, renderer: Any = None) -> Any:
        del renderer  # compat-noop: shim text extents are renderer-independent
        x, y, text = self._entry["args"]
        width = max(0.05, len(str(text)) * 0.018)
        return Bbox.from_bounds(float(x) - width / 2, float(y) - 0.04, width, 0.08)


class StreamplotSet:
    """Result container matching Matplotlib's ``lines``/``arrows`` surface."""

    def __init__(self, lines: PolyCollection, arrows: PolyCollection) -> None:
        self.lines = lines
        self.arrows = arrows


def _legend_item_from_entry(
    entry: dict[str, Any], label: Any, point_scale: float
) -> dict[str, Any]:
    """Freeze a plotted entry into a standalone legend swatch descriptor.

    The primary legend derives its swatches from trace names inside the render
    client; a manually built :class:`Legend` instead ships explicit items so it
    can show a *subset* of the handles under different labels. The item shape
    (``kind`` + ``style`` with color/width/dash/symbol) matches what every
    renderer already draws for a named trace, so line dashes and marker glyphs
    render identically.
    """
    kind = str(entry.get("kind", "line"))
    if kind.startswith("@"):  # generic marks (errorbar, vlines, …) → a line sample
        kind = "line"
    kw = entry.get("kwargs", {})
    style: dict[str, Any] = {}
    color = kw.get("color")
    if isinstance(color, str):
        style["color"] = color
    width = kw.get("width")
    if width is not None:
        style["width"] = float(width) * point_scale
    opacity = kw.get("opacity")
    if opacity is not None:
        style["opacity"] = float(opacity)
    # Rule annotations keep renderer-specific geometry inside ``style`` while
    # ordinary line/step entries keep it at the top level. Accept both shapes
    # so explicit Legend handles preserve the plotted dash.
    dash = kw.get("dash", (kw.get("style") or {}).get("dash"))
    if isinstance(dash, str) and "," in dash:
        try:
            dash = [float(value.strip()) for value in dash.split(",")]
        except ValueError:
            dash = None
    if isinstance(dash, str) and dash not in ("", "none", "solid"):
        from .. import _validate

        try:
            resolved = _validate.dash(dash, "legend dash")
        except (ValueError, TypeError):
            resolved = None
        if resolved:
            style["dash"] = resolved
    elif isinstance(dash, (list, tuple)):
        style["dash"] = [float(v) for v in dash]
    if kind == "scatter":
        symbol = kw.get("symbol")
        if symbol:
            style["symbol"] = symbol
        for key in ("stroke", "stroke_width"):
            if kw.get(key) is not None:
                style[key] = kw[key]
    return {"name": str(label), "kind": kind, "style": style}


class Legend:
    """A standalone legend artist, as ``matplotlib.legend.Legend``.

    Construct it with the parent axes plus explicit handles/labels, then attach
    it via ``ax.add_artist(leg)`` to render a *second* legend (e.g. one legend
    per group of lines) alongside the axes' own ``ax.legend()``.
    """

    def __init__(
        self, parent: Any, handles: Any, labels: Any, loc: Any = "best", **kwargs: Any
    ) -> None:
        handles, labels = list(handles), list(labels)
        if len(handles) != len(labels):
            warnings.warn(
                f"Legend: mismatched number of handles ({len(handles)}) and "
                f"labels ({len(labels)}); the extras are ignored",
                stacklevel=2,
            )
        self._pairs: list[tuple[dict[str, Any], Any]] = []
        for handle, label in zip(handles, labels, strict=False):
            entry = getattr(handle, "_entry", None)
            if entry is None:
                # ErrorbarContainer exposes the bars through its private
                # compatibility artist rather than inheriting Artist itself.
                entry = getattr(getattr(handle, "_artist", None), "_entry", None)
            if entry is None:
                warnings.warn(
                    f"Legend does not support {type(handle).__name__} handles; "
                    f"dropping the entry for {label!r}",
                    stacklevel=2,
                )
                continue
            self._pairs.append((entry, label))
        self._kwargs = dict(kwargs)
        self._kwargs.setdefault("loc", loc)
        self._attach(parent)

    def _attach(self, parent: Any) -> None:
        """(Re)freeze options and swatch scaling against *parent*'s figure state.

        ``Axes.add_artist`` calls this so a legend constructed against one axes
        but attached to another picks up the host's dpi/rcParams state rather
        than keeping the constructor's.
        """
        self._parent = parent
        self._options = parent._compose_legend_options(dict(self._kwargs))
        scale = parent._point_scale()
        self._items = [_legend_item_from_entry(entry, label, scale) for entry, label in self._pairs]

    def spec(self) -> dict[str, Any]:
        """The option dict plus explicit items, ready for the render payload."""
        options = dict(self._options)
        options["items"] = self._items
        return options
