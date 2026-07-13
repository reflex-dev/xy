"""Returned handles: the mutation surface of matplotlib's artist model.

A handle wraps the *declarative spec entry* an Axes call appended — mutating
it (``set_ydata``, ``set_color``, ``remove``) edits the spec and invalidates
the Axes' cached chart, so the next render/export rebuilds. This covers the
dominant mutation idioms without reproducing matplotlib's artist graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Optional

import numpy as np

from ._colors import resolve_color


@dataclass(frozen=True)
class Bbox:
    """Dependency-free subset of ``matplotlib.transforms.Bbox`` used by the shim."""

    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def from_bounds(cls, x0: float, y0: float, width: float, height: float) -> "Bbox":
        return cls(float(x0), float(y0), float(x0 + width), float(y0 + height))

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.width, self.height)


class Artist:
    def __init__(self, axes: Any, entry: dict[str, Any]) -> None:
        self._axes = axes
        self._entry = entry  # the mutable spec dict the Axes rendered from

    def _touch(self) -> None:
        self._axes._invalidate()

    def remove(self) -> None:
        self._axes._remove_entry(self._entry)

    def set_label(self, label: str) -> None:
        self._entry["kwargs"]["name"] = str(label)
        self._touch()

    def get_label(self) -> Optional[str]:
        return self._entry["kwargs"].get("name")

    def set_alpha(self, alpha: float) -> None:
        self._entry["kwargs"]["opacity"] = float(alpha)
        self._touch()

    def set_color(self, color: Any) -> None:
        self._entry["kwargs"]["color"] = resolve_color(color)
        self._touch()

    def get_color(self) -> Any:
        return self._entry["kwargs"].get("color")

    def set_markerfacecolor(self, color: Any) -> None:
        del color

    def set_markeredgecolor(self, color: Any) -> None:
        del color

    def set_markersize(self, size: Any) -> None:
        del size


class Line2D(Artist):
    """Handle for plt.plot lines (and their marker overlays)."""

    def _set_xy(self, index: int, value: Any) -> None:
        if self._entry["kind"] == "@mark" and self._entry.get("factory") == "step":
            args = list(self._entry["args"])
            args[index] = value
            self._entry["args"] = tuple(args)
            self._entry["x" if index == 0 else "y"] = value
            return
        key = "x" if index == 0 else "y"
        if key not in self._entry:
            raise NotImplementedError(
                f"set_{key}data is not supported for segment-backed Line2D handles"
            )
        self._entry[key] = value

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

    def get_xdata(self) -> Any:
        return self._entry["x"]

    def get_ydata(self) -> Any:
        return self._entry["y"]

    def set_linewidth(self, w: float) -> None:
        self._entry["kwargs"]["width"] = float(w)
        self._touch()

    set_lw = set_linewidth

    def set_dashes(self, sequence: Any) -> None:
        self._entry["kwargs"]["dash"] = [float(value) for value in sequence]
        self._touch()

    def set_dash_capstyle(self, style: Any) -> None:
        del style

    set_solid_capstyle = set_dash_capstyle

    def set_gapcolor(self, color: Any) -> None:
        del color


class PathCollection(Artist):
    """Handle for plt.scatter marks."""

    def set_offsets(self, xy: Any) -> None:
        import numpy as np

        arr = np.asarray(xy, dtype=np.float64)
        self._entry["x"] = arr[:, 0]
        self._entry["y"] = arr[:, 1]
        self._touch()

    def legend_elements(self, prop: str = "colors", num: Any = "auto", **kwargs: Any):
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
        if vmax is None and isinstance(vmin, (tuple, list)):
            vmin, vmax = vmin
        self._entry["kwargs"]["domain"] = (float(vmin), float(vmax))
        self._touch()

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

    def __iter__(self):
        return iter((self.markerline, self.stemlines, self.baseline))

    def remove(self) -> None:
        self.stemlines.remove()


class ErrorbarContainer:
    """Tuple-compatible errorbar handle without reproducing mpl's artist graph."""

    def __init__(self, artist: Artist, data_line: Optional[Line2D] = None) -> None:
        self.lines = (data_line, (), (artist,))
        self.has_xerr = artist._entry["kwargs"].get("xerr") is not None
        self.has_yerr = artist._entry["kwargs"].get("yerr") is not None
        self._artist = artist

    def __iter__(self):
        return iter(self.lines)

    def remove(self) -> None:
        self._artist.remove()


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

    def __iter__(self):
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

    def get_celld(self) -> dict[tuple[int, int], "Text"]:
        return dict(self._cells)

    def remove(self) -> None:
        for artist in self._artists:
            artist.remove()


class Text(Artist):
    """Small mutable text handle for pie labels and percentage annotations."""

    def set_text(self, text: str) -> None:
        x, y, _old = self._entry["args"]
        self._entry["args"] = (x, y, str(text))
        self._touch()

    def get_text(self) -> str:
        return str(self._entry["args"][2])

    def get_window_extent(self, renderer: Any = None) -> Any:
        del renderer
        x, y, text = self._entry["args"]
        width = max(0.05, len(str(text)) * 0.018)
        return Bbox.from_bounds(float(x) - width / 2, float(y) - 0.04, width, 0.08)


class StreamplotSet:
    """Result container matching Matplotlib's ``lines``/``arrows`` surface."""

    def __init__(self, lines: PolyCollection, arrows: PolyCollection) -> None:
        self.lines = lines
        self.arrows = arrows
