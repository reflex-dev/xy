"""Matplotlib plot-type adapters.

This module is deliberately inside :mod:`xy.pyplot`: signatures, return
containers, implicit defaults, and Matplotlib vocabulary never enter the core
package.  Each method emits a small adapter entry that materializes through a
generic public ``xy`` mark.  Expensive 2-D binning is dispatched to the native
Rust kernel rather than NumPy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from ._artists import (
    Artist,
    BarContainer,
    ContourSet,
    ErrorbarContainer,
    GroupedBarReturn,
    Line2D,
    PathCollection,
    PieContainer,
    PolyCollection,
    StemContainer,
    StepPatch,
    StreamplotSet,
    Table,
    Text,
    Wedge,
)
from ._colors import PROP_CYCLE, resolve_cmap, resolve_color
from ._fmt import parse_fmt
from ._translate import LINESTYLE_TO_DASH, check_unsupported, line_kwargs


def _from_data(value: Any, data: Any) -> Any:
    if data is not None and isinstance(value, str):
        try:
            return data[value]
        except (KeyError, TypeError):
            pass
    return value


def _line_props(owner: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    props = line_kwargs(kwargs)
    props.setdefault("color", owner._next_color())
    linestyle = props.pop("linestyle", None)
    if linestyle is not None:
        dash = LINESTYLE_TO_DASH.get(linestyle)
        if dash not in (None, "none"):
            props["dash"] = dash
    return props


def _sequence_param(value: Any, n: int, name: str) -> list[Any]:
    if isinstance(value, str) or np.isscalar(value):
        return [value] * n
    result = list(value)
    if len(result) == 1:
        return result * n
    if len(result) != n:
        raise ValueError(f"{name} must be scalar or have length {n}, got {len(result)}")
    return result


def _float(value: Any) -> float:
    return float(value)


def _uniform_mesh_axes(
    x: Any, y: Any, shape: tuple[int, int]
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Return heatmap centers when a mesh is uniform and rectilinear."""
    rows, cols = shape
    xa = np.asarray(x)
    ya = np.asarray(y)
    if xa.ndim == 2 and ya.ndim == 2:
        if xa.shape != ya.shape:
            raise ValueError("pcolormesh X and Y must have matching shapes")
        if not np.allclose(xa, xa[:1, :], equal_nan=True) or not np.allclose(
            ya, ya[:, :1], equal_nan=True
        ):
            return None
        xa, ya = xa[0], ya[:, 0]
    if xa.ndim != 1 or ya.ndim != 1:
        raise ValueError("pcolormesh X and Y must be 1-D or rectilinear 2-D arrays")

    def centers(values: np.ndarray, size: int, name: str) -> Optional[np.ndarray]:
        values = values.astype(np.float64, copy=False)
        if len(values) == size:
            result = values
            spacing = np.diff(result)
        elif len(values) == size + 1:
            result = (values[:-1] + values[1:]) * 0.5
            spacing = np.diff(values)
        else:
            raise ValueError(
                f"pcolormesh {name} has length {len(values)}; expected {size} or {size + 1}"
            )
        if len(spacing) > 1 and not np.allclose(spacing, spacing[0]):
            return None
        return result

    x_centers = centers(xa, cols, "X")
    y_centers = centers(ya, rows, "Y")
    if x_centers is None or y_centers is None:
        return None
    return x_centers, y_centers


def _regular_mesh_axes(x: Any, y: Any, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Return axes for a rectilinear grid, including non-uniform spacing."""
    rows, cols = shape
    xa, ya = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if xa.ndim == ya.ndim == 2:
        if xa.shape != shape or ya.shape != shape:
            raise ValueError("grid X and Y must match the data shape")
        if not np.allclose(xa, xa[:1, :], equal_nan=True) or not np.allclose(
            ya, ya[:, :1], equal_nan=True
        ):
            raise ValueError("grid X and Y must be rectilinear")
        xa, ya = xa[0], ya[:, 0]
    if xa.shape != (cols,) or ya.shape != (rows,):
        raise ValueError(f"grid X and Y must have lengths {cols} and {rows}")
    return xa, ya


def _triangulation_inputs(
    args: tuple[Any, ...], triangles: Any, data: Any
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[Any, ...]]:
    """Normalize matplotlib's `(x, y, ...)` or Triangulation-object forms."""
    if args and all(hasattr(args[0], name) for name in ("x", "y", "triangles")):
        triangulation = args[0]
        x = np.asarray(triangulation.x, dtype=np.float64)
        y = np.asarray(triangulation.y, dtype=np.float64)
        topology = np.asarray(triangulation.triangles, dtype=np.int64)
        mask = getattr(triangulation, "mask", None)
        if mask is not None:
            topology = topology[~np.asarray(mask, dtype=bool)]
        rest = args[1:]
    else:
        if len(args) < 2:
            raise TypeError("triangular plot requires x and y coordinates")
        x = np.asarray(_from_data(args[0], data), dtype=np.float64)
        y = np.asarray(_from_data(args[1], data), dtype=np.float64)
        rest = args[2:]
        if triangles is None:
            from xy import kernels

            topology = kernels.delaunay_triangles(x, y)
        else:
            topology = np.asarray(_from_data(triangles, data), dtype=np.int64)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError("triangular plot x and y must be equal-length 1-D arrays")
    if topology.ndim != 2 or topology.shape[1:] != (3,):
        raise ValueError("triangles must have shape (n, 3)")
    return x, y, np.ascontiguousarray(topology, dtype=np.int64), rest


def _triangle_levels(values: np.ndarray, levels: Any) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        raise ValueError("triangular contour z must contain a finite value")
    if isinstance(levels, (int, np.integer)) and not isinstance(levels, (bool, np.bool_)):
        count = int(levels)
        if count <= 0 or count > 256:
            raise ValueError("levels must be between 1 and 256")
        lo, hi = float(finite.min()), float(finite.max())
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        return np.linspace(lo, hi, count + 2, dtype=np.float64)[1:-1]
    result = np.asarray(levels, dtype=np.float64).reshape(-1)
    if len(result) == 0 or len(result) > 256 or not np.isfinite(result).all():
        raise ValueError("levels must contain 1 to 256 finite values")
    return np.sort(result)


class PlotTypeMixin:
    """Additional Matplotlib chart methods kept out of the core ``Axes`` type."""

    if TYPE_CHECKING:

        def _add(self, kind: str, entry: dict[str, Any]) -> dict[str, Any]: ...

        def _next_color(self) -> str: ...

        def plot(self, *args: Any, **kwargs: Any) -> list[Line2D]: ...

        def bar(self, *args: Any, **kwargs: Any) -> BarContainer: ...

        def barh(self, *args: Any, **kwargs: Any) -> BarContainer: ...

        def imshow(self, *args: Any, **kwargs: Any) -> Any: ...

        def axhline(self, *args: Any, **kwargs: Any) -> Line2D: ...

        def set_xticks(self, *args: Any, **kwargs: Any) -> None: ...

        def set_yticks(self, *args: Any, **kwargs: Any) -> None: ...

        def set_xlim(self, *args: Any, **kwargs: Any) -> None: ...

        def set_ylim(self, *args: Any, **kwargs: Any) -> None: ...

        def set_xscale(self, scale: str) -> None: ...

        def set_yscale(self, scale: str) -> None: ...

    def semilogx(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        base = kwargs.pop("base", kwargs.pop("basex", None))
        kwargs.pop("subs", kwargs.pop("subsx", None))
        kwargs.pop("nonpositive", kwargs.pop("nonposx", None))
        del base
        result = self.plot(*args, **kwargs)
        self.set_xscale("log")
        return result

    def semilogy(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        base = kwargs.pop("base", kwargs.pop("basey", None))
        kwargs.pop("subs", kwargs.pop("subsy", None))
        kwargs.pop("nonpositive", kwargs.pop("nonposy", None))
        del base
        result = self.plot(*args, **kwargs)
        self.set_yscale("log")
        return result

    def loglog(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        base = kwargs.pop("base", None)
        kwargs.pop("subs", None)
        kwargs.pop("nonpositive", None)
        del base
        result = self.plot(*args, **kwargs)
        self.set_xscale("log")
        self.set_yscale("log")
        return result

    def hlines(
        self,
        y: Any,
        xmin: Any,
        xmax: Any,
        colors: Any = None,
        linestyles: Any = "solid",
        label: Any = "",
        **kwargs: Any,
    ) -> PolyCollection:
        width = kwargs.pop("linewidth", kwargs.pop("linewidths", 1.2))
        alpha = kwargs.pop("alpha", None)
        kwargs.pop("data", None)
        check_unsupported(kwargs, "hlines()")
        yv, x0, x1 = np.broadcast_arrays(y, xmin, xmax)
        if linestyles not in (None, "solid", "-"):
            pass  # generic segments are solid; geometry remains exact
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0.reshape(-1), yv.reshape(-1), x1.reshape(-1), yv.reshape(-1)),
                "kwargs": {
                    "color": resolve_color(colors) if colors is not None else self._next_color(),
                    "width": _float(np.asarray(width).reshape(-1)[0]),
                    "opacity": 1.0 if alpha is None else float(alpha),
                    "name": str(label) if label else None,
                },
            },
        )
        return PolyCollection(self, entry)

    def vlines(
        self,
        x: Any,
        ymin: Any,
        ymax: Any,
        colors: Any = None,
        linestyles: Any = "solid",
        label: Any = "",
        **kwargs: Any,
    ) -> PolyCollection:
        xv, y0, y1 = np.broadcast_arrays(x, ymin, ymax)
        return self._vlines_entry(xv, y0, y1, colors, linestyles, label, kwargs)

    def _vlines_entry(
        self,
        xv: np.ndarray,
        y0: np.ndarray,
        y1: np.ndarray,
        colors: Any,
        linestyles: Any,
        label: Any,
        kwargs: dict[str, Any],
    ) -> PolyCollection:
        width = kwargs.pop("linewidth", kwargs.pop("linewidths", 1.2))
        alpha = kwargs.pop("alpha", None)
        kwargs.pop("data", None)
        check_unsupported(kwargs, "vlines()")
        del linestyles
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (xv.reshape(-1), y0.reshape(-1), xv.reshape(-1), y1.reshape(-1)),
                "kwargs": {
                    "color": resolve_color(colors) if colors is not None else self._next_color(),
                    "width": _float(np.asarray(width).reshape(-1)[0]),
                    "opacity": 1.0 if alpha is None else float(alpha),
                    "name": str(label) if label else None,
                },
            },
        )
        return PolyCollection(self, entry)

    def broken_barh(self, xranges: Any, yrange: Any, **kwargs: Any) -> PolyCollection:
        ranges = np.asarray(xranges, dtype=np.float64)
        if ranges.ndim != 2 or ranges.shape[1:] != (2,):
            raise ValueError("broken_barh xranges must have shape (n, 2)")
        ymin, height = map(float, yrange)
        color = kwargs.pop("facecolors", kwargs.pop("facecolor", kwargs.pop("color", None)))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        edgecolor = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("linewidths", None))
        check_unsupported(kwargs, "broken_barh()")
        entry_kwargs: dict[str, Any] = {
            "base": ranges[:, 0],
            "color": resolve_color(color) if color is not None else self._next_color(),
            "name": None if label is None else str(label),
            "opacity": 1.0 if alpha is None else float(alpha),
            "orientation": "horizontal",
            "width": height,
        }
        if edgecolor is not None:
            entry_kwargs["stroke"] = resolve_color(edgecolor)
            entry_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "bar",
            {
                "x": np.full(len(ranges), ymin + height * 0.5),
                "y": ranges[:, 0] + ranges[:, 1],
                "kwargs": entry_kwargs,
            },
        )
        return PolyCollection(self, entry)

    def fill_betweenx(
        self, y: Any, x1: Any, x2: Any = 0, where: Any = None, **kwargs: Any
    ) -> PolyCollection:
        yv, left, right = np.broadcast_arrays(
            np.asarray(y, dtype=np.float64),
            np.asarray(x1, dtype=np.float64),
            np.asarray(x2, dtype=np.float64),
        )
        if yv.ndim != 1 or len(yv) < 2:
            raise ValueError(
                "fill_betweenx inputs must resolve to 1-D arrays with at least two points"
            )
        color = kwargs.pop("color", kwargs.pop("facecolor", None))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        edgecolor = kwargs.pop("edgecolor", None)
        linewidth = kwargs.pop("linewidth", None)
        kwargs.pop("interpolate", None)
        kwargs.pop("step", None)
        kwargs.pop("data", None)
        check_unsupported(kwargs, "fill_betweenx()")
        vertices_x = np.column_stack((left, right))
        vertices_y = np.column_stack((yv, yv))
        cells = np.zeros((len(yv) - 1, 1), dtype=np.float64)
        if where is not None:
            mask = np.asarray(where, dtype=bool)
            if mask.shape != yv.shape:
                raise ValueError("fill_betweenx where must match y")
            cells[~(mask[:-1] & mask[1:]), 0] = np.nan
        from xy import kernels

        x0, y0, xa, ya, xb, yb, _ = kernels.quad_mesh_triangles(vertices_x, vertices_y, cells)
        mark_kwargs: dict[str, Any] = {
            "color": resolve_color(color) if color is not None else self._next_color(),
            "name": None if label is None else str(label),
            "opacity": 0.35 if alpha is None else float(alpha),
        }
        if edgecolor is not None:
            mark_kwargs["stroke"] = resolve_color(edgecolor)
            mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, xa, ya, xb, yb),
                "kwargs": mark_kwargs,
            },
        )
        return PolyCollection(self, entry)

    def fill(self, *args: Any, data: Any = None, **kwargs: Any) -> list[PolyCollection]:
        if len(args) < 2:
            raise TypeError("fill() requires x and y polygon coordinates")
        facecolor = kwargs.pop("color", kwargs.pop("facecolor", None))
        edgecolor = kwargs.pop("edgecolor", None)
        linewidth = kwargs.pop("linewidth", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        check_unsupported(kwargs, "fill()")
        groups: list[tuple[Any, Any, Any]] = []
        index = 0
        while index < len(args):
            if index + 1 >= len(args):
                raise TypeError("fill() polygon coordinates must be x, y pairs")
            x_values = _from_data(args[index], data)
            y_values = _from_data(args[index + 1], data)
            index += 2
            positional_color = None
            if index < len(args) and isinstance(args[index], str):
                try:
                    positional_color, _line, _marker = parse_fmt(args[index])
                except ValueError:
                    positional_color = args[index]
                index += 1
            groups.append((x_values, y_values, positional_color))
        from xy import kernels

        result: list[PolyCollection] = []
        for x_values, y_values, positional_color in groups:
            xv = np.asarray(x_values, dtype=np.float64)
            yv = np.asarray(y_values, dtype=np.float64)
            topology = kernels.polygon_triangles(xv, yv)
            x0, y0, x1, y1, x2, y2, _ = kernels.indexed_triangles(xv, yv, topology)
            chosen = facecolor
            if chosen is None and positional_color is not None:
                chosen = positional_color
            mark_kwargs: dict[str, Any] = {
                "color": resolve_color(chosen) if chosen is not None else self._next_color(),
                "name": None if label is None else str(label),
                "opacity": 1.0 if alpha is None else float(alpha),
            }
            if edgecolor is not None:
                mark_kwargs["stroke"] = resolve_color(edgecolor)
                mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": mark_kwargs,
                },
            )
            result.append(PolyCollection(self, entry))
        return result

    def arrow(self, x: float, y: float, dx: float, dy: float, **kwargs: Any) -> PolyCollection:
        color = kwargs.pop("color", kwargs.pop("facecolor", kwargs.pop("edgecolor", None)))
        alpha = kwargs.pop("alpha", None)
        width = kwargs.pop("linewidth", kwargs.pop("width", 1.2))
        head_width = kwargs.pop("head_width", None)
        head_length = kwargs.pop("head_length", None)
        kwargs.pop("length_includes_head", None)
        kwargs.pop("shape", None)
        kwargs.pop("overhang", None)
        kwargs.pop("head_starts_at_zero", None)
        check_unsupported(kwargs, "arrow()")
        ratio = 0.22
        if head_length is not None:
            length = float(np.hypot(dx, dy))
            ratio = 0.0 if length == 0 else min(1.0, float(head_length) / length)
        elif head_width is not None:
            length = float(np.hypot(dx, dy))
            ratio = 0.0 if length == 0 else min(1.0, float(head_width) / length)
        from xy import kernels

        x0, x1, y0, y1 = kernels.vector_segments(
            np.array([x]),
            np.array([y]),
            np.array([dx]),
            np.array([dy]),
            head_ratio=ratio,
        )
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": resolve_color(color) if color is not None else self._next_color(),
                    "opacity": 1.0 if alpha is None else float(alpha),
                    "width": float(width),
                },
            },
        )
        return PolyCollection(self, entry)

    def axline(
        self, xy1: tuple[float, float], xy2: Any = None, *, slope: Any = None, **kwargs: Any
    ) -> Line2D:
        if (xy2 is None) == (slope is None):
            raise TypeError("axline() requires exactly one of xy2 or slope")
        if xy2 is None:
            xy2 = (float(xy1[0]) + 1.0, float(xy1[1]) + float(slope))
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "axline()")
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": ([xy1[0]], [xy1[1]], [xy2[0]], [xy2[1]]),
                "kwargs": {
                    "color": props.get("color"),
                    "opacity": props.get("opacity", 1.0),
                    "width": props.get("width", 1.2),
                },
            },
        )
        return Line2D(self, entry)

    def _spectral_line(
        self, frequency: np.ndarray, values: np.ndarray, kwargs: dict[str, Any]
    ) -> Line2D:
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "spectral plot")
        entry = self._add("line", {"x": frequency, "y": values, "kwargs": props})
        return Line2D(self, entry)

    def magnitude_spectrum(
        self,
        x: Any,
        Fs: float = 2,
        Fc: float = 0,
        window: Any = None,
        pad_to: Any = None,
        sides: Any = None,
        scale: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Line2D]:
        del window, sides
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        nfft = len(values) if pad_to is None else int(pad_to)
        from xy import kernels

        frequency, real, imag = kernels.rfft(values, nfft=nfft, sample_rate=float(Fs))
        magnitude = np.hypot(real, imag) / max(1.0, nfft * 0.5)
        shown = (
            20.0 * np.log10(np.maximum(magnitude, np.finfo(float).tiny))
            if scale == "dB"
            else magnitude
        )
        line = self._spectral_line(frequency + float(Fc), shown, kwargs)
        return magnitude, frequency + float(Fc), line

    def angle_spectrum(
        self,
        x: Any,
        Fs: float = 2,
        Fc: float = 0,
        window: Any = None,
        pad_to: Any = None,
        sides: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Line2D]:
        del window, sides
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        nfft = len(values) if pad_to is None else int(pad_to)
        from xy import kernels

        frequency, real, imag = kernels.rfft(values, nfft=nfft, sample_rate=float(Fs))
        angle = np.arctan2(imag, real)
        frequency = frequency + float(Fc)
        return angle, frequency, self._spectral_line(frequency, angle, kwargs)

    def phase_spectrum(
        self,
        x: Any,
        Fs: float = 2,
        Fc: float = 0,
        window: Any = None,
        pad_to: Any = None,
        sides: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Line2D]:
        del window, sides
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        nfft = len(values) if pad_to is None else int(pad_to)
        from xy import kernels

        frequency, real, imag = kernels.rfft(values, nfft=nfft, sample_rate=float(Fs))
        phase = np.unwrap(np.arctan2(imag, real))
        frequency = frequency + float(Fc)
        return phase, frequency, self._spectral_line(frequency, phase, kwargs)

    def grouped_bar(
        self,
        heights: Any,
        *,
        positions: Any = None,
        group_spacing: float = 1.5,
        bar_spacing: float = 0,
        tick_labels: Any = None,
        labels: Any = None,
        orientation: str = "vertical",
        colors: Any = None,
        **kwargs: Any,
    ) -> GroupedBarReturn:
        """Draw Matplotlib 3.11 grouped bars using ordinary generic bar marks."""
        inferred_ticks = inferred_labels = None
        if hasattr(heights, "to_numpy") and hasattr(heights, "index"):
            matrix = np.asarray(heights.to_numpy(), dtype=np.float64)
            inferred_ticks = list(heights.index)
            inferred_labels = list(heights.columns)
            datasets = [matrix[:, index] for index in range(matrix.shape[1])]
        elif isinstance(heights, dict):
            if labels is not None:
                raise ValueError("labels must not be passed with dict heights")
            inferred_labels = list(heights)
            datasets = [np.asarray(value, dtype=np.float64) for value in heights.values()]
        elif isinstance(heights, (list, tuple)):
            datasets = [np.asarray(value, dtype=np.float64) for value in heights]
        else:
            matrix = np.asarray(heights, dtype=np.float64)
            if matrix.ndim == 1:
                matrix = matrix[:, None]
            if matrix.ndim != 2:
                raise ValueError("grouped_bar heights must be 1-D or 2-D")
            datasets = [matrix[:, index] for index in range(matrix.shape[1])]
        if not datasets or any(values.ndim != 1 for values in datasets):
            raise ValueError("grouped_bar requires one or more 1-D datasets")
        count = len(datasets[0])
        if any(len(values) != count for values in datasets):
            raise ValueError("all grouped_bar datasets must have equal length")
        centers = (
            np.arange(count, dtype=np.float64)
            if positions is None
            else np.asarray(positions, dtype=np.float64)
        )
        if centers.shape != (count,):
            raise ValueError("grouped_bar positions must match the category count")
        dataset_labels = inferred_labels if labels is None else list(labels)
        if dataset_labels is None:
            dataset_labels = [None] * len(datasets)
        if len(dataset_labels) != len(datasets):
            raise ValueError("grouped_bar labels must match the dataset count")
        palette = (
            [self._next_color() for _ in datasets]
            if colors is None
            else [list(colors)[index % len(list(colors))] for index in range(len(datasets))]
        )
        step = float(np.min(np.diff(centers))) if len(centers) > 1 else 1.0
        denominator = (
            len(datasets)
            + max(0.0, float(group_spacing))
            + max(0.0, float(bar_spacing)) * max(0, len(datasets) - 1)
        )
        width = step / max(denominator, 1.0)
        stride = width * (1.0 + max(0.0, float(bar_spacing)))
        start = -0.5 * stride * (len(datasets) - 1)
        containers: list[BarContainer] = []
        for index, values in enumerate(datasets):
            local = dict(kwargs)
            local["color"] = palette[index]
            if dataset_labels[index] is not None:
                local["label"] = dataset_labels[index]
            shifted = centers + start + index * stride
            if orientation == "vertical":
                containers.append(self.bar(shifted, values, width=width, **local))
            elif orientation == "horizontal":
                containers.append(self.barh(shifted, values, height=width, **local))
            else:
                raise ValueError("grouped_bar orientation must be 'vertical' or 'horizontal'")
        chosen_ticks = inferred_ticks if tick_labels is None else tick_labels
        if chosen_ticks is not None:
            if orientation == "vertical":
                self.set_xticks(centers, chosen_ticks)
            else:
                self.set_yticks(centers, chosen_ticks)
        return GroupedBarReturn(containers)

    def bar_label(
        self,
        container: BarContainer,
        labels: Any = None,
        *,
        fmt: Any = "%g",
        label_type: str = "edge",
        padding: float = 0,
        **kwargs: Any,
    ) -> list[Text]:
        if label_type not in ("edge", "center"):
            raise ValueError("bar_label label_type must be 'edge' or 'center'")
        values = np.asarray(container.datavalues, dtype=np.float64)
        centers = np.asarray(container.position_centers)
        bottoms = np.asarray(container.bottoms, dtype=np.float64)
        tops = np.asarray(container.tops, dtype=np.float64)
        raw_labels = [None] * len(values) if labels is None else list(labels)
        if len(raw_labels) != len(values):
            raise ValueError("bar_label labels must match the number of bars")
        color = kwargs.pop("color", None)
        kwargs.pop("fontsize", None)
        kwargs.pop("fontproperties", None)
        check_unsupported(kwargs, "bar_label()")
        result: list[Text] = []
        for index, value in enumerate(values):
            if raw_labels[index] is not None:
                label = str(raw_labels[index])
            elif callable(fmt):
                label = str(fmt(value if label_type == "center" else tops[index]))
            elif "{" in str(fmt):
                label = str(fmt).format(value if label_type == "center" else tops[index])
            else:
                label = str(fmt) % (value if label_type == "center" else tops[index])
            coordinate = (
                (bottoms[index] + tops[index]) * 0.5
                if label_type == "center"
                else tops[index] + np.sign(value or 1.0) * float(padding) * 0.01
            )
            x, y = (
                (centers[index], coordinate)
                if container.orientation == "vertical"
                else (coordinate, centers[index])
            )
            entry = self._add(
                "@text",
                {
                    "args": (x, y, label),
                    "kwargs": {"color": resolve_color(color)} if color is not None else {},
                },
            )
            result.append(Text(self, entry))
        return result

    def psd(
        self,
        x: Any,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 0,
        pad_to: Any = None,
        sides: Any = None,
        scale_by_freq: Any = None,
        return_line: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> Any:
        del detrend, window, pad_to, sides, scale_by_freq
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        from xy import kernels

        frequency, pxx, _pyy, _cross_real, _cross_imag = kernels.welch_spectra(
            values, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        frequency = frequency + float(Fc)
        shown = 10.0 * np.log10(np.maximum(pxx, np.finfo(float).tiny))
        line = self._spectral_line(frequency, shown, kwargs)
        return (pxx, frequency, line) if return_line else (pxx, frequency)

    def csd(
        self,
        x: Any,
        y: Any,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 0,
        pad_to: Any = None,
        sides: Any = None,
        scale_by_freq: Any = None,
        return_line: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> Any:
        del detrend, window, pad_to, sides, scale_by_freq
        xv = np.asarray(_from_data(x, data), dtype=np.float64)
        yv = np.asarray(_from_data(y, data), dtype=np.float64)
        from xy import kernels

        frequency, _pxx, _pyy, real, imag = kernels.welch_spectra(
            xv, yv, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        cross = real + 1j * imag
        frequency = frequency + float(Fc)
        shown = 10.0 * np.log10(np.maximum(np.abs(cross), np.finfo(float).tiny))
        line = self._spectral_line(frequency, shown, kwargs)
        return (cross, frequency, line) if return_line else (cross, frequency)

    def cohere(
        self,
        x: Any,
        y: Any,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 0,
        pad_to: Any = None,
        sides: Any = None,
        scale_by_freq: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray]:
        del detrend, window, pad_to, sides, scale_by_freq
        xv = np.asarray(_from_data(x, data), dtype=np.float64)
        yv = np.asarray(_from_data(y, data), dtype=np.float64)
        from xy import kernels

        frequency, pxx, pyy, real, imag = kernels.welch_spectra(
            xv, yv, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        coherence = (real * real + imag * imag) / np.maximum(pxx * pyy, np.finfo(float).tiny)
        frequency = frequency + float(Fc)
        self._spectral_line(frequency, coherence, kwargs)
        return coherence, frequency

    def specgram(
        self,
        x: Any,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 128,
        cmap: Any = None,
        xextent: Any = None,
        pad_to: Any = None,
        sides: Any = None,
        scale_by_freq: Any = None,
        mode: Any = None,
        scale: Any = None,
        vmin: Any = None,
        vmax: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, PolyCollection]:
        del detrend, window, xextent, pad_to, sides, scale_by_freq, mode, scale
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        from xy import kernels

        power, frequency, time = kernels.spectrogram(
            values, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        frequency = frequency + float(Fc)
        shown = 10.0 * np.log10(np.maximum(power, np.finfo(float).tiny))
        alpha = kwargs.pop("alpha", None)
        check_unsupported(kwargs, "specgram()")
        mark_kwargs: dict[str, Any] = {
            "x": time,
            "y": frequency,
            "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
            "opacity": 1.0 if alpha is None else float(alpha),
        }
        if vmin is not None and vmax is not None:
            mark_kwargs["domain"] = (float(vmin), float(vmax))
        entry = self._add(
            "@mark", {"factory": "heatmap", "args": (shown.T,), "kwargs": mark_kwargs}
        )
        return power.T, frequency, time, PolyCollection(self, entry)

    def xcorr(
        self,
        x: Any,
        y: Any,
        normed: bool = True,
        detrend: Any = None,
        usevlines: bool = True,
        maxlags: Any = 10,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Any, Any]:
        del detrend
        xv = np.asarray(_from_data(x, data), dtype=np.float64)
        yv = np.asarray(_from_data(y, data), dtype=np.float64)
        from xy import kernels

        lag, correlation = kernels.correlation(
            xv, yv, max_lags=None if maxlags is None else int(maxlags), normalize=bool(normed)
        )
        color = kwargs.pop("color", None)
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", 1.2))
        check_unsupported(kwargs, "xcorr()/acorr()")
        chosen = (
            resolve_color(color)
            if color is not None and (isinstance(color, str) or np.isscalar(color))
            else self._next_color()
        )
        if usevlines:
            artist = self.vlines(lag, 0.0, correlation, colors=chosen, linewidth=linewidth)
        else:
            artist = self.plot(lag, correlation, color=chosen, linewidth=linewidth)[0]
        baseline = self.axhline(0.0, color=chosen, linewidth=0.8)
        return lag, correlation, artist, baseline

    def acorr(self, x: Any, **kwargs: Any) -> tuple[np.ndarray, np.ndarray, Any, Any]:
        return self.xcorr(x, x, **kwargs)

    def stem(
        self,
        *args: Any,
        linefmt: Any = None,
        markerfmt: Any = None,
        basefmt: Any = None,
        bottom: float = 0,
        label: Any = None,
        orientation: str = "vertical",
        data: Any = None,
    ) -> StemContainer:
        if len(args) == 1:
            y = _from_data(args[0], data)
            x = np.arange(len(y), dtype=np.float64)
        elif len(args) == 2:
            x, y = (_from_data(arg, data) for arg in args)
        else:
            raise TypeError("stem() takes y or x, y")
        color = None
        if linefmt:
            color_spec, linestyle, _marker = parse_fmt(str(linefmt))
            color = resolve_color(color_spec) if color_spec else None
            del linestyle
        symbol = "circle"
        if markerfmt:
            marker_color, _linestyle, marker = parse_fmt(str(markerfmt))
            color = color or (resolve_color(marker_color) if marker_color else None)
            from ._translate import MARKER_TO_SYMBOL

            symbol = MARKER_TO_SYMBOL.get(marker or "o", "circle")
        del basefmt
        chosen = color or self._next_color()
        if orientation == "vertical":
            entry = self._add(
                "@mark",
                {
                    "factory": "stem",
                    "args": (x, y),
                    "kwargs": {
                        "base": bottom,
                        "name": str(label) if label is not None else None,
                        "color": chosen,
                        "symbol": symbol,
                    },
                },
            )
        elif orientation == "horizontal":
            xv = np.asarray(x, dtype=np.float64)
            yv = np.asarray(y, dtype=np.float64)
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (np.full_like(xv, float(bottom)), xv, yv, xv),
                    "kwargs": {
                        "name": str(label) if label is not None else None,
                        "color": chosen,
                        "width": 1.2,
                    },
                },
            )
            self._add(
                "scatter",
                {"x": yv, "y": xv, "kwargs": {"color": chosen, "symbol": symbol, "size": 5.0}},
            )
        else:
            raise ValueError("stem orientation must be 'vertical' or 'horizontal'")
        return StemContainer(Artist(self, entry))

    def stairs(
        self,
        values: Any,
        edges: Any = None,
        *,
        orientation: str = "vertical",
        baseline: Any = 0,
        fill: bool = False,
        data: Any = None,
        **kwargs: Any,
    ) -> StepPatch:
        values = _from_data(values, data)
        edges = _from_data(edges, data)
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "stairs()")
        vals = np.asarray(values, dtype=np.float64)
        edge_values = (
            np.arange(len(vals) + 1, dtype=np.float64)
            if edges is None
            else np.asarray(edges, dtype=np.float64)
        )
        if vals.ndim != 1 or edge_values.shape != (len(vals) + 1,):
            raise ValueError("stairs edges must have one more element than values")
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("stairs orientation must be 'vertical' or 'horizontal'")
        if fill:
            base_values = np.broadcast_to(
                np.asarray(0.0 if baseline is None else baseline, dtype=np.float64), vals.shape
            )
            left, right = edge_values[:-1], edge_values[1:]
            if orientation == "vertical":
                x0 = np.concatenate((left, left))
                y0 = np.concatenate((base_values, base_values))
                x1 = np.concatenate((right, right))
                y1 = np.concatenate((base_values, vals))
                x2 = np.concatenate((right, left))
                y2 = np.concatenate((vals, vals))
            else:
                x0 = np.concatenate((base_values, base_values))
                y0 = np.concatenate((left, left))
                x1 = np.concatenate((base_values, vals))
                y1 = np.concatenate((right, right))
                x2 = np.concatenate((vals, vals))
                y2 = np.concatenate((right, left))
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": {
                        "color": props.get("color"),
                        "opacity": props.get("opacity", 1.0),
                        "name": props.get("name"),
                    },
                    "values": values,
                    "edges": edges,
                },
            )
            return StepPatch(self, entry)
        if orientation == "horizontal":
            x0 = np.concatenate((vals, vals[:-1]))
            x1 = np.concatenate((vals, vals[1:]))
            y0 = np.concatenate((edge_values[:-1], edge_values[1:-1]))
            y1 = np.concatenate((edge_values[1:], edge_values[1:-1]))
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": {
                        "color": props.get("color"),
                        "width": props.get("width", 1.2),
                        "opacity": props.get("opacity", 1.0),
                        "name": props.get("name"),
                    },
                    "values": values,
                    "edges": edges,
                    "baseline": baseline,
                },
            )
            return StepPatch(self, entry)
        entry = self._add(
            "@mark",
            {
                "factory": "stairs",
                "args": (values, edges),
                "values": values,
                "edges": edges,
                "kwargs": props,
            },
        )
        return StepPatch(self, entry)

    def ecdf(
        self,
        x: Any,
        weights: Any = None,
        *,
        complementary: bool = False,
        orientation: str = "vertical",
        compress: bool = False,
        data: Any = None,
        **kwargs: Any,
    ) -> Artist:
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "ecdf()")
        if weights is None and not complementary and orientation == "vertical" and not compress:
            entry = self._add("@mark", {"factory": "ecdf", "args": (values,), "kwargs": props})
            return Artist(self, entry)
        weight_values = (
            np.ones(len(values), dtype=np.float64)
            if weights is None
            else np.asarray(_from_data(weights, data), dtype=np.float64)
        )
        if len(weight_values) != len(values) or np.any(weight_values < 0):
            raise ValueError("ecdf weights must be nonnegative and match x")
        from xy import kernels

        unique, cumulative = kernels.weighted_ecdf(values, weight_values)
        if complementary:
            cumulative = 1.0 - cumulative
        sx = np.concatenate(([unique[0]], unique))
        sy = np.concatenate(([1.0 if complementary else 0.0], cumulative))
        if orientation == "vertical":
            args = (sx, sy)
        elif orientation == "horizontal":
            args = (sy, sx)
        else:
            raise ValueError("ecdf orientation must be 'vertical' or 'horizontal'")
        entry = self._add(
            "@mark", {"factory": "step", "args": args, "kwargs": {"where": "post", **props}}
        )
        return Artist(self, entry)

    def boxplot(
        self,
        x: Any,
        *,
        notch: Any = None,
        sym: Any = None,
        vert: Any = None,
        orientation: str = "vertical",
        whis: Any = None,
        positions: Any = None,
        widths: Any = None,
        patch_artist: Any = None,
        bootstrap: Any = None,
        usermedians: Any = None,
        conf_intervals: Any = None,
        meanline: Any = None,
        showmeans: Any = None,
        showcaps: Any = None,
        showbox: Any = None,
        showfliers: Any = None,
        boxprops: Any = None,
        tick_labels: Any = None,
        flierprops: Any = None,
        medianprops: Any = None,
        meanprops: Any = None,
        capprops: Any = None,
        whiskerprops: Any = None,
        manage_ticks: bool = True,
        autorange: bool = False,
        zorder: Any = None,
        capwidths: Any = None,
        label: Any = None,
        data: Any = None,
    ) -> dict[str, list[Artist]]:
        del sym, patch_artist, manage_ticks, zorder, tick_labels
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        unsupported = {
            "notch": notch,
            "whis": whis if whis not in (None, 1.5) else None,
            "bootstrap": bootstrap,
            "usermedians": usermedians,
            "conf_intervals": conf_intervals,
            "meanline": meanline,
            "showmeans": showmeans,
            "showcaps": False if showcaps is False else None,
            "showbox": False if showbox is False else None,
            "autorange": True if autorange else None,
            "capwidths": capwidths,
        }
        del unsupported
        values = _from_data(x, data)
        color = None
        for props in (boxprops, medianprops, whiskerprops, capprops, flierprops, meanprops):
            if props and color is None:
                color = props.get("color", props.get("facecolor"))
        entry = self._add(
            "@mark",
            {
                "factory": "box",
                "args": (values,),
                "kwargs": {
                    "x": positions,
                    "name": str(label) if label is not None else None,
                    "color": resolve_color(color) if color is not None else self._next_color(),
                    "width": _float(widths) if np.isscalar(widths) and widths is not None else 0.6,
                    "orientation": orientation,
                    "show_outliers": True if showfliers is None else bool(showfliers),
                },
            },
        )
        artist = Artist(self, entry)
        return {
            "whiskers": [artist],
            "caps": [artist],
            "boxes": [artist],
            "medians": [artist],
            "fliers": [artist] if showfliers is not False else [],
            "means": [],
        }

    def violinplot(
        self,
        dataset: Any,
        positions: Any = None,
        *,
        vert: Any = None,
        orientation: str = "vertical",
        widths: float = 0.5,
        showmeans: bool = False,
        showextrema: bool = True,
        showmedians: bool = False,
        quantiles: Any = None,
        points: int = 100,
        bw_method: Any = None,
        side: str = "both",
        facecolor: Any = None,
        linecolor: Any = None,
        data: Any = None,
    ) -> dict[str, Any]:
        del showextrema, linecolor
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        del bw_method, side
        values = _from_data(dataset, data)
        entry = self._add(
            "@mark",
            {
                "factory": "violin",
                "args": (values,),
                "kwargs": {
                    "x": positions,
                    "color": resolve_color(facecolor)
                    if facecolor is not None
                    else self._next_color(),
                    "width": float(widths),
                    "bins": max(4, min(1024, int(points))),
                    "orientation": orientation,
                },
            },
        )
        result: dict[str, Any] = {"bodies": [Artist(self, entry)]}
        groups = (
            [np.asarray(values, dtype=np.float64)]
            if np.asarray(values).ndim == 1
            else [np.asarray(group, dtype=np.float64) for group in values]
        )
        centers = np.arange(1, len(groups) + 1) if positions is None else np.asarray(positions)
        if showmeans:
            means = [float(np.nanmean(group)) for group in groups]
            result["cmeans"] = (
                self.hlines(means, centers - widths * 0.2, centers + widths * 0.2)
                if orientation == "vertical"
                else self.vlines(means, centers - widths * 0.2, centers + widths * 0.2)
            )
        if showmedians:
            medians = [float(np.nanmedian(group)) for group in groups]
            result["cmedians"] = (
                self.hlines(medians, centers - widths * 0.2, centers + widths * 0.2)
                if orientation == "vertical"
                else self.vlines(medians, centers - widths * 0.2, centers + widths * 0.2)
            )
        if quantiles is not None:
            quantile_values: list[float] = []
            quantile_positions: list[float] = []
            for center, group, requested in zip(centers, groups, quantiles, strict=True):
                made = np.quantile(group[np.isfinite(group)], requested)
                quantile_values.extend(np.asarray(made).reshape(-1))
                quantile_positions.extend([float(center)] * np.asarray(made).size)
            qv, qp = np.asarray(quantile_values), np.asarray(quantile_positions)
            result["cquantiles"] = (
                self.hlines(qv, qp - widths * 0.2, qp + widths * 0.2)
                if orientation == "vertical"
                else self.vlines(qv, qp - widths * 0.2, qp + widths * 0.2)
            )
        return result

    def errorbar(
        self,
        x: Any,
        y: Any,
        yerr: Any = None,
        xerr: Any = None,
        fmt: str = "",
        *,
        ecolor: Any = None,
        elinewidth: Any = None,
        capsize: Any = None,
        barsabove: bool = False,
        lolims: Any = False,
        uplims: Any = False,
        xlolims: Any = False,
        xuplims: Any = False,
        errorevery: Any = 1,
        capthick: Any = None,
        elinestyle: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> ErrorbarContainer:
        del barsabove, capthick, elinestyle
        del lolims, uplims, xlolims, xuplims
        x, y = _from_data(x, data), _from_data(y, data)
        yerr, xerr = _from_data(yerr, data), _from_data(xerr, data)
        if errorevery != 1:
            start, stride = (
                (0, int(np.asarray(errorevery).item()))
                if np.isscalar(errorevery)
                else map(int, errorevery)
            )
            selection = np.arange(len(np.asarray(x)))[start::stride]
            x, y = np.asarray(x)[selection], np.asarray(y)[selection]

            def subset_error(error: Any) -> Any:
                if error is None or np.isscalar(error):
                    return error
                arr = np.asarray(error)
                return arr[..., selection]

            yerr, xerr = subset_error(yerr), subset_error(xerr)
        base = line_kwargs(kwargs)
        check_unsupported(kwargs, "errorbar()")
        color = (
            resolve_color(ecolor) if ecolor is not None else base.get("color", self._next_color())
        )
        entry = self._add(
            "@mark",
            {
                "factory": "errorbar",
                "args": (x, y),
                "kwargs": {
                    "yerr": yerr,
                    "xerr": xerr,
                    "name": base.get("name"),
                    "color": color,
                    "width": float(elinewidth or base.get("width", 1.2)),
                    "cap_size": None if capsize is None else float(capsize),
                    "opacity": base.get("opacity", 1.0),
                },
            },
        )
        data_line: Optional[Line2D] = None
        if fmt and fmt.lower() != "none":
            line_kwargs_for_plot: dict[str, Any] = {}
            if "color" in base:
                line_kwargs_for_plot["color"] = base["color"]
            if "width" in base:
                line_kwargs_for_plot["linewidth"] = base["width"]
            if "opacity" in base:
                line_kwargs_for_plot["alpha"] = base["opacity"]
            if "name" in base:
                line_kwargs_for_plot["label"] = base["name"]
            data_line = self.plot(x, y, fmt, **line_kwargs_for_plot)[0]
        return ErrorbarContainer(Artist(self, entry), data_line)

    def hexbin(
        self,
        x: Any,
        y: Any,
        C: Any = None,
        *,
        gridsize: Any = 100,
        bins: Any = None,
        xscale: str = "linear",
        yscale: str = "linear",
        extent: Any = None,
        cmap: Any = None,
        norm: Any = None,
        vmin: Any = None,
        vmax: Any = None,
        alpha: Any = None,
        linewidths: Any = None,
        edgecolors: Any = "face",
        reduce_C_function: Any = np.mean,
        mincnt: Any = None,
        marginals: bool = False,
        colorizer: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> PathCollection:
        del linewidths, edgecolors, reduce_C_function
        del C, norm, mincnt, marginals, colorizer, vmin, vmax
        check_unsupported(kwargs, "hexbin()")
        x, y = _from_data(x, data), _from_data(y, data)
        if xscale != "linear":
            self.set_xscale(xscale)
        if yscale != "linear":
            self.set_yscale(yscale)
        data_range = None
        if extent is not None:
            xmin, xmax, ymin, ymax = map(float, extent)
            data_range = ((xmin, xmax), (ymin, ymax))
        mode = "log" if bins == "log" else "count"
        entry = self._add(
            "@mark",
            {
                "factory": "hexbin",
                "args": (x, y),
                "x": x,
                "y": y,
                "kwargs": {
                    "gridsize": gridsize,
                    "range": data_range,
                    "bins": mode,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "opacity": 0.9 if alpha is None else float(alpha),
                },
            },
        )
        return PathCollection(self, entry)

    def _contour(self, filled: bool, args: tuple[Any, ...], kwargs: dict[str, Any]) -> ContourSet:
        if len(args) in (1, 2):
            z = args[0]
            x = y = None
            positional_levels = args[1] if len(args) == 2 else None
        elif len(args) in (3, 4):
            x, y, z = args[:3]
            positional_levels = args[3] if len(args) == 4 else None
            za = np.asarray(z)
            xa, ya = np.asarray(x), np.asarray(y)
            if xa.ndim == 2 and ya.ndim == 2:
                try:
                    x, y = _regular_mesh_axes(xa, ya, za.shape)
                except ValueError:
                    # Curvilinear grids become an unstructured native
                    # triangulation; all O(n²) topology work remains in Rust.
                    return self._tricontour(
                        filled,
                        (xa.reshape(-1), ya.reshape(-1), za.reshape(-1)),
                        kwargs,
                    )
        else:
            raise TypeError("contour() expects Z, [levels] or X, Y, Z, [levels]")
        levels = kwargs.pop("levels", positional_levels if positional_levels is not None else 10)
        cmap = kwargs.pop("cmap", None)
        colors = kwargs.pop("colors", None)
        linewidths = kwargs.pop("linewidths", None)
        alpha = kwargs.pop("alpha", None)
        kwargs.pop("origin", None)
        kwargs.pop("extent", None)
        check_unsupported(kwargs, "contour()/contourf()")
        color = None
        if colors is not None:
            color = resolve_color(colors if isinstance(colors, str) else next(iter(colors)))
        width = _float(linewidths) if np.isscalar(linewidths) and linewidths is not None else 1.1
        entry = self._add(
            "@mark",
            {
                "factory": "contour",
                "args": (z,),
                "kwargs": {
                    "x": x,
                    "y": y,
                    "levels": levels,
                    "filled": filled,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "color": color,
                    "width": width,
                    "opacity": 0.9 if alpha is None else float(alpha),
                },
            },
        )
        return ContourSet(self, entry)

    def contour(self, *args: Any, data: Any = None, **kwargs: Any) -> ContourSet:
        del data
        return self._contour(False, args, kwargs)

    def contourf(self, *args: Any, data: Any = None, **kwargs: Any) -> ContourSet:
        del data
        return self._contour(True, args, kwargs)

    def clabel(
        self,
        CS: ContourSet,
        levels: Any = None,
        *,
        fontsize: Any = None,
        inline: bool = True,
        inline_spacing: float = 5,
        fmt: Any = None,
        colors: Any = None,
        use_clabeltext: bool = False,
        manual: Any = False,
        rightside_up: bool = True,
        zorder: Any = None,
    ) -> list[Text]:
        """Label contour levels without exposing contour semantics to core."""
        del fontsize, inline, inline_spacing, use_clabeltext, rightside_up, zorder
        chosen = np.asarray(CS.levels if levels is None else levels, dtype=np.float64).reshape(-1)
        if isinstance(manual, (list, tuple, np.ndarray)) and len(manual):
            locations = list(manual)
        else:
            locations = [(0.5, 0.5)] * len(chosen)
        color_values = [colors] * len(chosen) if isinstance(colors, str) else colors
        if color_values is None:
            color_values = [None] * len(chosen)
        elif not isinstance(color_values, list):
            color_values = list(color_values)
        result: list[Text] = []
        for index, level in enumerate(chosen):
            location = locations[index % len(locations)]
            if callable(fmt):
                label = str(fmt(level))
            elif isinstance(fmt, dict):
                label = str(fmt.get(level, level))
            elif isinstance(fmt, str):
                label = fmt % level
            else:
                label = f"{level:g}"
            color = color_values[index % len(color_values)]
            entry = self._add(
                "@text",
                {
                    "args": (float(location[0]), float(location[1]), label),
                    "kwargs": {"color": resolve_color(color)} if color is not None else {},
                },
            )
            result.append(Text(self, entry))
        return result

    def bxp(
        self,
        bxpstats: Any,
        positions: Any = None,
        *,
        widths: Any = None,
        vert: Any = None,
        orientation: str = "vertical",
        patch_artist: bool = False,
        shownotches: bool = False,
        showmeans: bool = False,
        showcaps: bool = True,
        showbox: bool = True,
        showfliers: bool = True,
        boxprops: Any = None,
        whiskerprops: Any = None,
        flierprops: Any = None,
        medianprops: Any = None,
        capprops: Any = None,
        meanprops: Any = None,
        meanline: bool = False,
        manage_ticks: bool = True,
        zorder: Any = None,
        capwidths: Any = None,
        label: Any = None,
    ) -> dict[str, list[Artist]]:
        """Draw exact precomputed box geometry with generic segment/scatter marks."""
        del patch_artist, shownotches, manage_ticks, zorder
        stats = list(bxpstats)
        count = len(stats)
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("bxp orientation must be 'vertical' or 'horizontal'")
        pos = (
            np.arange(1, count + 1, dtype=np.float64)
            if positions is None
            else np.asarray(positions, dtype=np.float64)
        )
        if pos.shape != (count,):
            raise ValueError("bxp positions must match bxpstats")
        box_widths = np.asarray(_sequence_param(0.5 if widths is None else widths, count, "widths"))
        cap_width_values = np.asarray(
            _sequence_param(
                box_widths * 0.5 if capwidths is None else capwidths, count, "capwidths"
            ),
            dtype=np.float64,
        )

        def style(props: Any, fallback: Any = None) -> dict[str, Any]:
            source = dict(props or {})
            color = source.pop("color", source.pop("edgecolor", fallback))
            width = source.pop("linewidth", source.pop("lw", 1.2))
            alpha = source.pop("alpha", 1.0)
            source.pop("linestyle", source.pop("ls", None))
            check_unsupported(source, "bxp component properties")
            return {
                "color": resolve_color(color) if color is not None else fallback,
                "width": float(width),
                "opacity": float(alpha),
            }

        default_color = self._next_color()

        def emit(coords: list[tuple[float, float, float, float]], props: Any) -> list[Artist]:
            if not coords:
                return []
            values = np.asarray(coords, dtype=np.float64)
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (values[:, 0], values[:, 1], values[:, 2], values[:, 3]),
                    "kwargs": style(props, default_color),
                },
            )
            return [Artist(self, entry)]

        box_segments: list[tuple[float, float, float, float]] = []
        median_segments: list[tuple[float, float, float, float]] = []
        whisker_segments: list[tuple[float, float, float, float]] = []
        cap_segments: list[tuple[float, float, float, float]] = []
        mean_segments: list[tuple[float, float, float, float]] = []
        flier_x: list[float] = []
        flier_y: list[float] = []
        for index, item in enumerate(stats):
            required = ("med", "q1", "q3", "whislo", "whishi")
            if any(name not in item for name in required):
                raise ValueError(f"bxpstats[{index}] is missing a required statistic")
            center = float(pos[index])
            half = float(box_widths[index]) * 0.5
            cap_half = float(cap_width_values[index]) * 0.5
            q1, q3 = float(item["q1"]), float(item["q3"])
            med = float(item["med"])
            low, high = float(item["whislo"]), float(item["whishi"])
            if orientation == "vertical":
                box_segments.extend(
                    [
                        (center - half, q1, center + half, q1),
                        (center + half, q1, center + half, q3),
                        (center + half, q3, center - half, q3),
                        (center - half, q3, center - half, q1),
                    ]
                )
                median_segments.append((center - half, med, center + half, med))
                whisker_segments.extend([(center, low, center, q1), (center, q3, center, high)])
                cap_segments.extend(
                    [
                        (center - cap_half, low, center + cap_half, low),
                        (center - cap_half, high, center + cap_half, high),
                    ]
                )
                flier_x.extend([center] * len(item.get("fliers", ())))
                flier_y.extend(float(value) for value in item.get("fliers", ()))
                if showmeans and "mean" in item:
                    mean = float(item["mean"])
                    mean_segments.append(
                        (center - half, mean, center + half, mean)
                        if meanline
                        else (center, mean, center, mean)
                    )
            else:
                box_segments.extend(
                    [
                        (q1, center - half, q1, center + half),
                        (q1, center + half, q3, center + half),
                        (q3, center + half, q3, center - half),
                        (q3, center - half, q1, center - half),
                    ]
                )
                median_segments.append((med, center - half, med, center + half))
                whisker_segments.extend([(low, center, q1, center), (q3, center, high, center)])
                cap_segments.extend(
                    [
                        (low, center - cap_half, low, center + cap_half),
                        (high, center - cap_half, high, center + cap_half),
                    ]
                )
                flier_x.extend(float(value) for value in item.get("fliers", ()))
                flier_y.extend([center] * len(item.get("fliers", ())))
                if showmeans and "mean" in item:
                    mean = float(item["mean"])
                    mean_segments.append(
                        (mean, center - half, mean, center + half)
                        if meanline
                        else (mean, center, mean, center)
                    )
        result = {
            "boxes": emit(box_segments, boxprops) if showbox else [],
            "medians": emit(median_segments, medianprops),
            "whiskers": emit(whisker_segments, whiskerprops),
            "caps": emit(cap_segments, capprops) if showcaps else [],
            "means": emit(mean_segments, meanprops),
            "fliers": [],
        }
        if showfliers and flier_x:
            source = dict(flierprops or {})
            color = source.pop("color", default_color)
            marker = source.pop("marker", "o")
            size = source.pop("markersize", source.pop("ms", 5.0))
            source.pop("markerfacecolor", None)
            source.pop("markeredgecolor", None)
            check_unsupported(source, "bxp(flierprops=)")
            entry = self._add(
                "scatter",
                {
                    "x": flier_x,
                    "y": flier_y,
                    "kwargs": {
                        "color": resolve_color(color),
                        "size": float(size),
                        "symbol": "circle" if marker == "o" else "square",
                    },
                },
            )
            result["fliers"] = [Artist(self, entry)]
        if label is not None and result["medians"]:
            result["medians"][0].set_label(str(label))
        return result

    def violin(
        self,
        vpstats: Any,
        positions: Any = None,
        *,
        vert: Any = None,
        orientation: str = "vertical",
        widths: Any = 0.5,
        showmeans: bool = False,
        showextrema: bool = True,
        showmedians: bool = False,
        side: str = "both",
        facecolor: Any = None,
        linecolor: Any = None,
    ) -> dict[str, Any]:
        """Draw violin bodies from precomputed coordinates and densities."""
        stats = list(vpstats)
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("violin orientation must be 'vertical' or 'horizontal'")
        if side not in ("both", "low", "high"):
            raise ValueError("violin side must be 'both', 'low', or 'high'")
        pos = (
            np.arange(1, len(stats) + 1, dtype=np.float64)
            if positions is None
            else np.asarray(positions, dtype=np.float64)
        )
        width_values = np.asarray(_sequence_param(widths, len(stats), "widths"), dtype=float)
        if pos.shape != (len(stats),):
            raise ValueError("violin positions must match vpstats")
        body_color = resolve_color(facecolor) if facecolor is not None else self._next_color()
        edge_color = resolve_color(linecolor) if linecolor is not None else body_color
        from xy import kernels

        bodies: list[Artist] = []
        center_segments: dict[str, list[tuple[float, float, float, float]]] = {
            "cmeans": [],
            "cmedians": [],
            "cmins": [],
            "cmaxes": [],
            "cbars": [],
            "cquantiles": [],
        }
        for index, item in enumerate(stats):
            coords = np.asarray(item["coords"], dtype=np.float64)
            vals = np.asarray(item["vals"], dtype=np.float64)
            if coords.ndim != 1 or vals.shape != coords.shape or len(coords) < 2:
                raise ValueError("violin stats coords and vals must be matching 1-D arrays")
            peak = float(np.max(np.abs(vals)))
            density = np.zeros_like(vals) if peak == 0 else vals / peak * width_values[index] * 0.5
            center = float(pos[index])
            low = center - density if side in ("both", "low") else np.full_like(density, center)
            high = center + density if side in ("both", "high") else np.full_like(density, center)
            if orientation == "vertical":
                polygon_x = np.concatenate((low, high[::-1]))
                polygon_y = np.concatenate((coords, coords[::-1]))
            else:
                polygon_x = np.concatenate((coords, coords[::-1]))
                polygon_y = np.concatenate((low, high[::-1]))
            topology = kernels.polygon_triangles(polygon_x, polygon_y)
            x0, y0, x1, y1, x2, y2, _ = kernels.indexed_triangles(polygon_x, polygon_y, topology)
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": {"color": body_color, "opacity": 0.8},
                },
            )
            bodies.append(Artist(self, entry))
            half = width_values[index] * 0.25

            def line_at(
                value: float, center: float = center, half: float = half
            ) -> tuple[float, float, float, float]:
                return (
                    (center - half, value, center + half, value)
                    if orientation == "vertical"
                    else (value, center - half, value, center + half)
                )

            minimum, maximum = (
                float(item.get("min", coords.min())),
                float(item.get("max", coords.max())),
            )
            if showextrema:
                center_segments["cmins"].append(line_at(minimum))
                center_segments["cmaxes"].append(line_at(maximum))
                center_segments["cbars"].append(
                    (center, minimum, center, maximum)
                    if orientation == "vertical"
                    else (minimum, center, maximum, center)
                )
            if showmeans and "mean" in item:
                center_segments["cmeans"].append(line_at(float(item["mean"])))
            if showmedians and "median" in item:
                center_segments["cmedians"].append(line_at(float(item["median"])))
            center_segments["cquantiles"].extend(
                line_at(float(value)) for value in item.get("quantiles", ())
            )
        result: dict[str, Any] = {"bodies": bodies}
        for name, coordinates in center_segments.items():
            if not coordinates:
                continue
            values = np.asarray(coordinates, dtype=np.float64)
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (values[:, 0], values[:, 1], values[:, 2], values[:, 3]),
                    "kwargs": {"color": edge_color, "width": 1.0},
                },
            )
            result[name] = Artist(self, entry)
        return result

    def hist2d(
        self,
        x: Any,
        y: Any,
        bins: Any = 10,
        *,
        range: Any = None,  # noqa: A002 - Matplotlib signature
        density: bool = False,
        weights: Any = None,
        cmin: Any = None,
        cmax: Any = None,
        data: Any = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, PolyCollection]:
        x = np.asarray(_from_data(x, data), dtype=np.float64)
        y = np.asarray(_from_data(y, data), dtype=np.float64)
        if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
            raise ValueError("hist2d x and y must be equal-length 1-D arrays")
        weight_values = None
        if weights is not None:
            weight_values = np.asarray(_from_data(weights, data), dtype=np.float64)
            if weight_values.ndim != 1 or len(weight_values) != len(x):
                raise ValueError("hist2d weights must have the same length as x and y")
        from xy import kernels

        finite = np.isfinite(x) & np.isfinite(y)
        xv, yv = x[finite], y[finite]
        if not len(xv):
            raise ValueError("hist2d requires at least one finite pair")
        wv = None if weight_values is None else weight_values[finite]
        if range is None:
            xr = kernels.min_max(xv)
            yr = kernels.min_max(yv)
            if xr is None or yr is None:
                raise ValueError("hist2d requires finite x and y ranges")
            xr = (xr[0] - 0.5, xr[1] + 0.5) if xr[0] == xr[1] else xr
            yr = (yr[0] - 0.5, yr[1] + 0.5) if yr[0] == yr[1] else yr
        else:
            if len(range) != 2 or len(range[0]) != 2 or len(range[1]) != 2:
                raise ValueError("hist2d range must be ((xmin, xmax), (ymin, ymax))")
            xr = (float(range[0][0]), float(range[0][1]))
            yr = (float(range[1][0]), float(range[1][1]))

        def make_edges(spec: Any, bounds: tuple[float, float], label: str) -> np.ndarray:
            if isinstance(spec, (int, np.integer)):
                count = int(spec)
                if count <= 0:
                    raise ValueError(f"hist2d {label} bins must be positive")
                return np.linspace(bounds[0], bounds[1], count + 1)
            edges = np.asarray(spec, dtype=np.float64)
            if edges.ndim != 1 or len(edges) < 2 or not np.all(np.diff(edges) > 0):
                raise ValueError(
                    f"hist2d {label} bin edges must be a strictly increasing 1-D array"
                )
            return edges

        if isinstance(bins, (int, np.integer)):
            x_spec = y_spec = bins
        else:
            bin_values = list(bins)
            if len(bin_values) == 2 and (
                any(not np.isscalar(value) for value in bin_values)
                or all(isinstance(value, (int, np.integer)) for value in bin_values)
            ):
                x_spec, y_spec = bin_values
            else:
                x_spec = y_spec = bin_values
        xedges = make_edges(x_spec, xr, "x")
        yedges = make_edges(y_spec, yr, "y")
        uniform_counts = (
            wv is None
            and isinstance(x_spec, (int, np.integer))
            and isinstance(y_spec, (int, np.integer))
        )
        if uniform_counts:
            flat = kernels.bin_2d(
                xv,
                yv,
                xedges[0],
                xedges[-1],
                yedges[0],
                yedges[-1],
                len(xedges) - 1,
                len(yedges) - 1,
            )
            h = np.asarray(flat, dtype=np.float64).T
        else:
            h = kernels.histogram2d(xv, yv, xedges, yedges, wv)
        if density:
            total = float(h.sum())
            if total:
                areas = np.diff(xedges)[:, None] * np.diff(yedges)[None, :]
                h = h / total / areas
        if cmin is not None:
            h[h < float(cmin)] = np.nan
        if cmax is not None:
            h[h > float(cmax)] = np.nan
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        kwargs.pop("norm", None)
        check_unsupported(kwargs, "hist2d()")
        mark_kwargs: dict[str, Any] = {
            "x": (xedges[:-1] + xedges[1:]) * 0.5,
            "y": (yedges[:-1] + yedges[1:]) * 0.5,
            "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
            "opacity": 0.95 if alpha is None else float(alpha),
        }
        if vmin is not None and vmax is not None:
            mark_kwargs["domain"] = (float(vmin), float(vmax))
        entry = self._add(
            "@mark",
            {"factory": "heatmap", "args": (h.T,), "kwargs": mark_kwargs},
        )
        return h, xedges, yedges, PolyCollection(self, entry)

    def eventplot(
        self,
        positions: Any,
        *,
        orientation: str = "horizontal",
        lineoffsets: Any = 1,
        linelengths: Any = 1,
        linewidths: Any = None,
        colors: Any = None,
        alpha: Any = None,
        linestyles: Any = "solid",
        data: Any = None,
        **kwargs: Any,
    ) -> list[PolyCollection]:
        check_unsupported(kwargs, "eventplot()")
        del linestyles
        source = _from_data(positions, data)
        arr = np.asarray(source, dtype=object)
        groups = [source] if arr.ndim == 1 and all(np.isscalar(v) for v in source) else list(source)
        offsets = _sequence_param(lineoffsets, len(groups), "lineoffsets")
        lengths = _sequence_param(linelengths, len(groups), "linelengths")
        widths = _sequence_param(
            1.5 if linewidths is None else linewidths, len(groups), "linewidths"
        )
        palette = PROP_CYCLE if colors is None else _sequence_param(colors, len(groups), "colors")
        if colors is None:
            palette = [self._next_color() for _ in groups]
        result: list[PolyCollection] = []
        for group, offset, length, width, color in zip(
            groups, offsets, lengths, widths, palette, strict=True
        ):
            values = np.asarray(group, dtype=np.float64)
            fixed = np.full(len(values), float(offset), dtype=np.float64)
            if orientation == "horizontal":
                x, y = values, fixed
                err_kwargs = {"yerr": float(length) * 0.5}
            elif orientation == "vertical":
                x, y = fixed, values
                err_kwargs = {"xerr": float(length) * 0.5}
            else:
                raise ValueError("eventplot orientation must be 'horizontal' or 'vertical'")
            entry = self._add(
                "@mark",
                {
                    "factory": "errorbar",
                    "args": (x, y),
                    "kwargs": {
                        **err_kwargs,
                        "cap_size": 0.0,
                        "color": resolve_color(color),
                        "width": float(width),
                        "opacity": 1.0 if alpha is None else float(alpha),
                    },
                },
            )
            result.append(PolyCollection(self, entry))
        return result

    def stackplot(
        self,
        x: Any,
        *args: Any,
        labels: Any = (),
        colors: Any = None,
        baseline: str = "zero",
        data: Any = None,
        **kwargs: Any,
    ) -> list[PolyCollection]:
        """Stack areas using native lower/upper-bound computation."""
        if not args:
            raise TypeError("stackplot() requires at least one y series")
        x = np.asarray(_from_data(x, data), dtype=np.float64)
        resolved = [_from_data(value, data) for value in args]
        values = np.vstack(resolved).astype(np.float64, copy=False)
        if values.ndim != 2 or values.shape[1] != len(x):
            raise ValueError("stackplot y series must all have the same length as x")
        from xy import kernels

        lower, upper = kernels.stacked_bounds(values, baseline)
        label_values = (
            _sequence_param(labels, values.shape[0], "labels")
            if labels
            else [None] * values.shape[0]
        )
        if colors is None:
            color_values = [self._next_color() for _ in range(values.shape[0])]
        else:
            raw_colors = list(colors) if not isinstance(colors, str) else [colors]
            if not raw_colors:
                raise ValueError("stackplot colors must not be empty")
            color_values = [raw_colors[i % len(raw_colors)] for i in range(values.shape[0])]
        alpha = kwargs.pop("alpha", None)
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", None))
        kwargs.pop("edgecolor", None)
        kwargs.pop("facecolor", None)
        check_unsupported(kwargs, "stackplot()")
        result: list[PolyCollection] = []
        for row in range(values.shape[0]):
            entry = self._add(
                "@mark",
                {
                    "factory": "area",
                    "args": (x, upper[row]),
                    "kwargs": {
                        "base": lower[row],
                        "name": None if label_values[row] is None else str(label_values[row]),
                        "color": resolve_color(color_values[row]),
                        "opacity": 1.0 if alpha is None else float(alpha),
                        "line_width": 1.2 if linewidth is None else float(linewidth),
                    },
                },
            )
            result.append(PolyCollection(self, entry))
        return result

    def pcolormesh(self, *args: Any, **kwargs: Any) -> PolyCollection:
        if len(args) == 1:
            z = np.asarray(args[0], dtype=np.float64)
            x = y = None
        elif len(args) == 3:
            x, y, raw = args
            z = np.asarray(raw, dtype=np.float64)
        else:
            raise TypeError("pcolormesh() expects C or X, Y, C")
        if z.ndim != 2:
            raise ValueError("pcolormesh C must be 2-D")
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        shading = kwargs.pop("shading", None)
        kwargs.pop("antialiased", None)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("linewidths", None))
        kwargs.pop("norm", None)
        if shading not in (None, "auto", "flat", "nearest", "gouraud"):
            raise ValueError(f"invalid pcolormesh shading {shading!r}")
        check_unsupported(kwargs, "pcolormesh()")
        colormap = resolve_cmap(cmap) if cmap is not None else "viridis"
        opacity = 0.95 if alpha is None else float(alpha)
        domain = (float(vmin), float(vmax)) if vmin is not None and vmax is not None else None
        regular = None if x is None else _uniform_mesh_axes(x, y, z.shape)
        if x is None or (regular is not None and shading != "gouraud"):
            if regular is not None:
                x, y = regular
            mark_kwargs: dict[str, Any] = {
                "x": x,
                "y": y,
                "colormap": colormap,
                "opacity": opacity,
            }
            if domain is not None:
                mark_kwargs["domain"] = domain
            entry = self._add("@mark", {"factory": "heatmap", "args": (z,), "kwargs": mark_kwargs})
            return PolyCollection(self, entry)

        from xy import kernels

        if y is None:
            raise ValueError("pcolormesh requires Y when X is provided")
        x0, y0, x1, y1, x2, y2, scalar = kernels.quad_mesh_triangles(x, y, z)
        mark_kwargs: dict[str, Any] = {
            "color": scalar,
            "colormap": colormap,
            "opacity": opacity,
        }
        if domain is not None:
            mark_kwargs["domain"] = domain
        no_edges = edgecolors is None or (
            isinstance(edgecolors, str) and edgecolors.lower() == "none"
        )
        if not no_edges:
            mark_kwargs["stroke"] = resolve_color(edgecolors)
            mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, x1, y1, x2, y2),
                "kwargs": mark_kwargs,
            },
        )
        return PolyCollection(self, entry)

    def pcolor(self, *args: Any, **kwargs: Any) -> PolyCollection:
        return self.pcolormesh(*args, **kwargs)

    def pcolorfast(self, *args: Any, **kwargs: Any) -> PolyCollection:
        return self.pcolormesh(*args, **kwargs)

    def matshow(self, z: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("origin", "upper")
        return self.imshow(z, **kwargs)

    def spy(
        self,
        z: Any,
        precision: Any = 0,
        marker: Any = None,
        markersize: Any = None,
        aspect: Any = "equal",
        origin: str = "upper",
        **kwargs: Any,
    ) -> Any:
        del marker, markersize, aspect
        values = z.toarray() if hasattr(z, "toarray") else np.asarray(z)
        threshold = 0.0 if precision in (None, "present") else float(precision)
        mask = np.abs(np.asarray(values, dtype=np.float64)) > threshold
        kwargs.setdefault("cmap", "gray")
        kwargs.setdefault("vmin", 0.0)
        kwargs.setdefault("vmax", 1.0)
        kwargs["origin"] = origin
        return self.imshow(mask.astype(np.float64), **kwargs)

    def pie(
        self,
        x: Any,
        explode: Any = None,
        labels: Any = None,
        colors: Any = None,
        autopct: Any = None,
        pctdistance: float = 0.6,
        shadow: Any = False,
        labeldistance: Any = 1.1,
        startangle: float = 0,
        radius: float = 1,
        counterclock: bool = True,
        wedgeprops: Any = None,
        textprops: Any = None,
        center: tuple[float, float] = (0, 0),
        frame: bool = False,
        rotatelabels: bool = False,
        normalize: bool = True,
        hatch: Any = None,
        *,
        data: Any = None,
    ) -> Any:
        del shadow, frame, rotatelabels, hatch
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        if values.ndim != 1 or len(values) == 0:
            raise ValueError("pie x must be a non-empty 1-D array")
        offsets = np.zeros(len(values), dtype=np.float64)
        if explode is not None:
            offsets = np.asarray(_from_data(explode, data), dtype=np.float64)
            if offsets.shape != values.shape:
                raise ValueError("pie explode must have the same length as x")
        label_values = (
            [None] * len(values)
            if labels is None
            else _sequence_param(labels, len(values), "labels")
        )
        if colors is None:
            color_values = [self._next_color() for _ in values]
        else:
            provided = list(colors) if not isinstance(colors, str) else [colors]
            if not provided:
                raise ValueError("pie colors must not be empty")
            color_values = [provided[index % len(provided)] for index in range(len(values))]
        wedge_style = dict(wedgeprops or {})
        width = wedge_style.pop("width", None)
        edgecolor = wedge_style.pop("edgecolor", wedge_style.pop("ec", None))
        linewidth = wedge_style.pop("linewidth", wedge_style.pop("lw", None))
        alpha = wedge_style.pop("alpha", None)
        wedge_style.pop("hatch", None)
        if wedge_style:
            check_unsupported(wedge_style, "pie(wedgeprops=)")
        inner_radius = 0.0 if width is None else max(0.0, float(radius) - float(width))
        from xy import kernels

        x0, y0, x1, y1, x2, y2, sectors = kernels.sector_triangles(
            values,
            explode=offsets,
            center=(float(center[0]), float(center[1])),
            radius=float(radius),
            inner_radius=inner_radius,
            start_degrees=float(startangle),
            counterclockwise=bool(counterclock),
            normalize=bool(normalize),
        )
        total = float(np.sum(values)) if normalize else 1.0
        direction = 1.0 if counterclock else -1.0
        boundaries = np.deg2rad(float(startangle)) + direction * np.pi * 2.0 * np.concatenate(
            ([0.0], np.cumsum(values) / total)
        )
        mids = (boundaries[:-1] + boundaries[1:]) * 0.5
        wedges: list[Wedge] = []
        for index in range(len(values)):
            selected = sectors == float(index)
            mark_kwargs: dict[str, Any] = {
                "color": resolve_color(color_values[index]),
                "name": None if label_values[index] is None else str(label_values[index]),
                "opacity": 1.0 if alpha is None else float(alpha),
            }
            if edgecolor is not None:
                mark_kwargs["stroke"] = resolve_color(edgecolor)
                mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (
                        x0[selected],
                        y0[selected],
                        x1[selected],
                        y1[selected],
                        x2[selected],
                        y2[selected],
                    ),
                    "kwargs": mark_kwargs,
                },
            )
            entry["pie_center"] = (float(center[0]), float(center[1]))
            entry["pie_mid"] = float(mids[index])
            entry["pie_radius"] = float(radius)
            entry["pie_explode"] = float(offsets[index])
            wedges.append(Wedge(self, entry))

        angle = np.deg2rad(float(startangle))
        text_style = dict(textprops or {})
        text_color = text_style.pop("color", None)
        text_style.pop("fontsize", None)
        text_style.pop("ha", None)
        text_style.pop("va", None)
        if text_style:
            check_unsupported(text_style, "pie(textprops=)")

        def add_text(distance: float, mid: float, value: str, offset: float) -> Text:
            local_center_x = float(center[0]) + offset * float(radius) * np.cos(mid)
            local_center_y = float(center[1]) + offset * float(radius) * np.sin(mid)
            entry = self._add(
                "@text",
                {
                    "args": (
                        local_center_x + distance * float(radius) * np.cos(mid),
                        local_center_y + distance * float(radius) * np.sin(mid),
                        value,
                    ),
                    "kwargs": {"color": resolve_color(text_color)}
                    if text_color is not None
                    else {},
                },
            )
            return Text(self, entry)

        texts: list[Text] = []
        autotexts: list[Text] = []
        for index, value in enumerate(values):
            sweep = direction * np.pi * 2.0 * float(value) / total
            mid = angle + sweep * 0.5
            if labeldistance is not None:
                texts.append(
                    add_text(
                        float(labeldistance),
                        mid,
                        "" if label_values[index] is None else str(label_values[index]),
                        float(offsets[index]),
                    )
                )
            if autopct is not None:
                percentage = 100.0 * float(value) / total
                label = autopct(percentage) if callable(autopct) else str(autopct) % percentage
                autotexts.append(
                    add_text(float(pctdistance), mid, str(label), float(offsets[index]))
                )
            angle += sweep
        extent = float(radius) * (1.25 + float(np.max(offsets)))
        self.set_xlim(float(center[0]) - extent, float(center[0]) + extent)
        self.set_ylim(float(center[1]) - extent, float(center[1]) + extent)
        return PieContainer(wedges, values, bool(normalize), texts, autotexts)

    def pie_label(
        self,
        container: PieContainer,
        labels: Any,
        *,
        distance: float = 0.6,
        textprops: Any = None,
        rotate: bool = False,
        alignment: str = "auto",
    ) -> list[Text]:
        del rotate
        if alignment not in ("auto", "center", "outer"):
            raise ValueError("pie_label alignment must be 'auto', 'center', or 'outer'")
        if isinstance(labels, str):
            formatted = [
                labels.format(absval=value, frac=frac)
                for value, frac in zip(container.values, container.fracs, strict=True)
            ]
        else:
            formatted = list(labels)
        if len(formatted) != len(container.wedges):
            raise ValueError("pie_label labels must match the wedge count")
        style = dict(textprops or {})
        color = style.pop("color", None)
        style.pop("fontsize", None)
        style.pop("ha", None)
        style.pop("va", None)
        check_unsupported(style, "pie_label(textprops=)")
        result: list[Text] = []
        for wedge, label in zip(container.wedges, formatted, strict=True):
            entry_data = wedge._entry
            center_x, center_y = entry_data["pie_center"]
            mid = float(entry_data["pie_mid"])
            radius = float(entry_data["pie_radius"])
            explode = float(entry_data["pie_explode"])
            radial = (float(distance) + explode) * radius
            entry = self._add(
                "@text",
                {
                    "args": (
                        center_x + radial * np.cos(mid),
                        center_y + radial * np.sin(mid),
                        str(label),
                    ),
                    "kwargs": {"color": resolve_color(color)} if color is not None else {},
                },
            )
            result.append(Text(self, entry))
        container.add_texts(result)
        return result

    def table(
        self,
        cellText: Any = None,
        cellColours: Any = None,
        cellLoc: str = "right",
        colWidths: Any = None,
        rowLabels: Any = None,
        rowColours: Any = None,
        rowLoc: str = "left",
        colLabels: Any = None,
        colColours: Any = None,
        colLoc: str = "center",
        loc: str = "bottom",
        bbox: Any = None,
        edges: str = "closed",
        **kwargs: Any,
    ) -> Table:
        """Render an Axes table as generic colored cells, rules, and text."""
        del cellLoc, rowLoc, colLoc, loc
        if cellText is None:
            if cellColours is None:
                raise ValueError("table requires cellText or cellColours")
            shape = np.asarray(cellColours, dtype=object).shape
            raw_text = [[""] * shape[1] for _ in range(shape[0])]
        else:
            raw_text = [list(row) for row in cellText]
        if not raw_text or not raw_text[0] or any(len(row) != len(raw_text[0]) for row in raw_text):
            raise ValueError("table cellText must be a non-empty rectangular matrix")
        rows, cols = len(raw_text), len(raw_text[0])
        raw_colors = (
            [["#ffffff"] * cols for _ in range(rows)]
            if cellColours is None
            else [list(row) for row in cellColours]
        )
        if len(raw_colors) != rows or any(len(row) != cols for row in raw_colors):
            raise ValueError("table cellColours must match cellText")
        if rowLabels is not None:
            labels = list(rowLabels)
            if len(labels) != rows:
                raise ValueError("table rowLabels must match the row count")
            row_palette = (
                ["#ffffff"] * rows
                if rowColours is None
                else _sequence_param(rowColours, rows, "rowColours")
            )
            for index in range(rows):
                raw_text[index].insert(0, labels[index])
                raw_colors[index].insert(0, row_palette[index])
            cols += 1
        if colLabels is not None:
            labels = list(colLabels)
            expected = cols - (1 if rowLabels is not None else 0)
            if len(labels) != expected:
                raise ValueError("table colLabels must match the column count")
            if rowLabels is not None:
                labels.insert(0, "")
            palette = (
                ["#ffffff"] * expected
                if colColours is None
                else _sequence_param(colColours, expected, "colColours")
            )
            if rowLabels is not None:
                palette.insert(0, "#ffffff")
            raw_text.insert(0, labels)
            raw_colors.insert(0, palette)
            rows += 1
        if bbox is None:
            left, bottom, width, height = 0.0, 0.0, 1.0, 1.0
        else:
            left, bottom, width, height = map(float, bbox)
        if colWidths is None:
            widths = np.full(cols, width / cols, dtype=np.float64)
        else:
            widths = np.asarray(colWidths, dtype=np.float64)
            if rowLabels is not None and len(widths) == cols - 1:
                widths = np.insert(widths, 0, widths[0])
            if widths.shape != (cols,):
                raise ValueError("table colWidths must match the column count")
            widths *= width / widths.sum()
        x_edges = left + np.concatenate(([0.0], np.cumsum(widths)))
        y_edges = bottom + np.linspace(0.0, height, rows + 1)
        x0: list[float] = []
        y0: list[float] = []
        x1: list[float] = []
        y1: list[float] = []
        x2: list[float] = []
        y2: list[float] = []
        triangle_colors: list[str] = []
        for row in range(rows):
            display_row = rows - row - 1
            for col in range(cols):
                xa, xb = x_edges[col], x_edges[col + 1]
                ya, yb = y_edges[display_row], y_edges[display_row + 1]
                x0.extend((xa, xa))
                y0.extend((ya, ya))
                x1.extend((xb, xb))
                y1.extend((ya, yb))
                x2.extend((xb, xa))
                y2.extend((yb, yb))
                chosen = resolve_color(raw_colors[row][col]) or "#ffffff"
                triangle_colors.extend((chosen, chosen))
        fill_entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, x1, y1, x2, y2),
                "kwargs": {"color": triangle_colors, "opacity": 0.9},
            },
        )
        artists: list[Artist] = [Artist(self, fill_entry)]
        if edges not in ("", "open"):
            sx0 = np.concatenate((x_edges, np.full(len(y_edges), left)))
            sy0 = np.concatenate((np.full(len(x_edges), bottom), y_edges))
            sx1 = np.concatenate((x_edges, np.full(len(y_edges), left + width)))
            sy1 = np.concatenate((np.full(len(x_edges), bottom + height), y_edges))
            rule_entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (sx0, sy0, sx1, sy1),
                    "kwargs": {"color": "#1f2937", "width": 0.8},
                },
            )
            artists.append(Artist(self, rule_entry))
        text_color = kwargs.pop("color", None)
        kwargs.pop("fontsize", None)
        check_unsupported(kwargs, "table()")
        cells: dict[tuple[int, int], Text] = {}
        for row in range(rows):
            display_row = rows - row - 1
            for col in range(cols):
                entry = self._add(
                    "@text",
                    {
                        "args": (
                            (x_edges[col] + x_edges[col + 1]) * 0.5,
                            (y_edges[display_row] + y_edges[display_row + 1]) * 0.5,
                            str(raw_text[row][col]),
                        ),
                        "kwargs": {"color": resolve_color(text_color)}
                        if text_color is not None
                        else {},
                    },
                )
                handle = Text(self, entry)
                cells[(row, col)] = handle
                artists.append(handle)
        return Table(artists, cells)

    def tripcolor(
        self,
        *args: Any,
        triangles: Any = None,
        facecolors: Any = None,
        shading: str = "flat",
        data: Any = None,
        **kwargs: Any,
    ) -> PolyCollection:
        x, y, topology, rest = _triangulation_inputs(args, triangles, data)
        if facecolors is None:
            if len(rest) != 1:
                raise TypeError("tripcolor() requires one color-value array")
            values = np.asarray(_from_data(rest[0], data), dtype=np.float64)
            values_at = "vertex"
        else:
            if rest:
                raise TypeError("tripcolor() facecolors conflicts with positional color values")
            values = np.asarray(_from_data(facecolors, data), dtype=np.float64)
            values_at = "face"
        if shading not in ("flat", "gouraud"):
            raise ValueError("tripcolor shading must be 'flat' or 'gouraud'")
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("linewidths", None))
        label = kwargs.pop("label", None)
        kwargs.pop("norm", None)
        kwargs.pop("antialiased", None)
        check_unsupported(kwargs, "tripcolor()")
        from xy import kernels

        x0, y0, x1, y1, x2, y2, scalar = kernels.indexed_triangles(
            x, y, topology, values, values_at=values_at
        )
        mark_kwargs: dict[str, Any] = {
            "color": scalar,
            "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
            "name": None if label is None else str(label),
            "opacity": 1.0 if alpha is None else float(alpha),
        }
        if vmin is not None and vmax is not None:
            mark_kwargs["domain"] = (float(vmin), float(vmax))
        if edgecolors is not None and not (
            isinstance(edgecolors, str) and edgecolors.lower() == "none"
        ):
            mark_kwargs["stroke"] = resolve_color(edgecolors)
            mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, x1, y1, x2, y2),
                "kwargs": mark_kwargs,
            },
        )
        return PolyCollection(self, entry)

    def triplot(
        self, *args: Any, triangles: Any = None, data: Any = None, **kwargs: Any
    ) -> list[Line2D]:
        x, y, topology, rest = _triangulation_inputs(args, triangles, data)
        fmt = rest[0] if rest else None
        if len(rest) > 1:
            raise TypeError("triplot() accepts at most one format string")
        props = _line_props(self, kwargs)
        if fmt is not None:
            color_spec, linestyle, _marker = parse_fmt(str(fmt))
            if color_spec is not None:
                props["color"] = resolve_color(color_spec)
            if linestyle is not None:
                props["dash"] = LINESTYLE_TO_DASH.get(linestyle)
        check_unsupported(kwargs, "triplot()")
        from xy import kernels

        x0, x1, y0, y1 = kernels.triangle_edges(x, y, topology)
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": props.get("color"),
                    "width": props.get("width", 1.2),
                    "opacity": props.get("opacity", 1.0),
                    "name": props.get("name"),
                },
            },
        )
        return [Line2D(self, entry)]

    def _tricontour(
        self, filled: bool, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> ContourSet:
        triangles = kwargs.pop("triangles", None)
        data = kwargs.pop("data", None)
        x, y, topology, rest = _triangulation_inputs(args, triangles, data)
        if not rest:
            raise TypeError("tricontour() requires z values")
        z = np.asarray(_from_data(rest[0], data), dtype=np.float64)
        if z.ndim != 1 or len(z) != len(x):
            raise ValueError("tricontour z must be a 1-D array matching x and y")
        positional_levels = rest[1] if len(rest) > 1 else None
        if len(rest) > 2:
            raise TypeError("tricontour() received too many positional arguments")
        level_arg = kwargs.pop("levels", positional_levels if positional_levels is not None else 10)
        levels = _triangle_levels(z, level_arg)
        cmap = kwargs.pop("cmap", None)
        colors = kwargs.pop("colors", None)
        linewidths = kwargs.pop("linewidths", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        kwargs.pop("norm", None)
        kwargs.pop("antialiased", None)
        kwargs.pop("extend", None)
        check_unsupported(kwargs, "tricontour()/tricontourf()")
        colormap = resolve_cmap(cmap) if cmap is not None else "viridis"
        opacity = 1.0 if alpha is None else float(alpha)
        domain_lo, domain_hi = float(levels[0]), float(levels[-1])
        if domain_lo == domain_hi:
            padding = abs(domain_lo) * 0.05 or 0.5
            domain_lo, domain_hi = domain_lo - padding, domain_hi + padding
        explicit_color = None
        if colors is not None:
            explicit_color = resolve_color(
                colors if isinstance(colors, str) else next(iter(colors))
            )
        from xy import kernels

        if filled:
            x0, y0, x1, y1, x2, y2, scalar = kernels.indexed_triangles(
                x, y, topology, z, values_at="vertex"
            )
            mark_kwargs: dict[str, Any] = {
                "color": explicit_color if explicit_color is not None else scalar,
                "colormap": colormap,
                "name": None if label is None else str(label),
                "opacity": opacity,
            }
            if explicit_color is None:
                mark_kwargs["domain"] = (domain_lo, domain_hi)
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": mark_kwargs,
                    "levels": levels,
                },
            )
        else:
            x0, x1, y0, y1, segment_levels = kernels.marching_triangles(x, y, z, topology, levels)
            width = _float(np.asarray(linewidths).reshape(-1)[0]) if linewidths is not None else 1.1
            segment_kwargs: dict[str, Any] = {
                "color": explicit_color if explicit_color is not None else segment_levels,
                "colormap": colormap,
                "name": None if label is None else str(label),
                "opacity": opacity,
                "width": width,
            }
            if explicit_color is None:
                segment_kwargs["domain"] = (domain_lo, domain_hi)
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": segment_kwargs,
                    "levels": levels,
                },
            )
        return ContourSet(self, entry)

    def tricontour(self, *args: Any, **kwargs: Any) -> ContourSet:
        return self._tricontour(False, args, kwargs)

    def tricontourf(self, *args: Any, **kwargs: Any) -> ContourSet:
        return self._tricontour(True, args, kwargs)

    def _vector_field(
        self, args: tuple[Any, ...], kwargs: dict[str, Any], name: str
    ) -> PolyCollection:
        if len(args) == 2:
            raw_u, raw_v = args
            u_grid = np.asarray(raw_u, dtype=np.float64)
            v_grid = np.asarray(raw_v, dtype=np.float64)
            if u_grid.shape != v_grid.shape:
                raise ValueError(f"{name} U and V must have matching shapes")
            if u_grid.ndim == 1:
                x = np.arange(u_grid.size, dtype=np.float64)
                y = np.zeros(u_grid.size, dtype=np.float64)
            elif u_grid.ndim == 2:
                rows, cols = u_grid.shape
                xx, yy = np.meshgrid(np.arange(cols), np.arange(rows))
                x, y = xx.reshape(-1), yy.reshape(-1)
            else:
                raise ValueError(f"{name} U and V must be 1-D or 2-D")
            u, v = u_grid.reshape(-1), v_grid.reshape(-1)
            c = None
        elif len(args) in (4, 5):
            raw_x, raw_y, raw_u, raw_v = args[:4]
            c = args[4] if len(args) == 5 else None
            u_grid = np.asarray(raw_u, dtype=np.float64)
            v_grid = np.asarray(raw_v, dtype=np.float64)
            if u_grid.shape != v_grid.shape:
                raise ValueError(f"{name} U and V must have matching shapes")
            x_grid = np.asarray(raw_x, dtype=np.float64)
            y_grid = np.asarray(raw_y, dtype=np.float64)
            if x_grid.ndim == y_grid.ndim == 1 and u_grid.ndim == 2:
                x_grid, y_grid = np.meshgrid(x_grid, y_grid)
            if x_grid.shape != u_grid.shape or y_grid.shape != u_grid.shape:
                raise ValueError(f"{name} X, Y, U, and V must resolve to matching shapes")
            x, y = x_grid.reshape(-1), y_grid.reshape(-1)
            u, v = u_grid.reshape(-1), v_grid.reshape(-1)
        else:
            raise TypeError(f"{name}() expects U, V or X, Y, U, V[, C]")
        color = kwargs.pop("color", c)
        alpha = kwargs.pop("alpha", None)
        width = kwargs.pop("width", kwargs.pop("linewidth", 1.2))
        scale = kwargs.pop("scale", None)
        pivot = kwargs.pop("pivot", "tail")
        angles = kwargs.pop("angles", "uv")
        scale_units = kwargs.pop("scale_units", None)
        kwargs.pop("units", None)
        kwargs.pop("headwidth", None)
        kwargs.pop("headlength", None)
        kwargs.pop("headaxislength", None)
        kwargs.pop("minshaft", None)
        kwargs.pop("minlength", None)
        cmap = kwargs.pop("cmap", None)
        kwargs.pop("norm", None)
        kwargs.pop("clim", None)
        check_unsupported(kwargs, f"{name}()")
        if not isinstance(angles, str):
            directions = np.deg2rad(np.asarray(angles, dtype=np.float64).reshape(-1))
            lengths = np.hypot(u, v)
            if directions.shape != lengths.shape:
                raise ValueError(f"{name} angles must match U and V")
            u, v = lengths * np.cos(directions), lengths * np.sin(directions)
        elif angles not in ("uv", "xy"):
            raise ValueError(f"invalid {name} angles {angles!r}")
        if scale_units not in (None, "width", "height", "dots", "inches", "x", "y", "xy"):
            raise ValueError(f"invalid {name} scale_units {scale_units!r}")
        from xy import kernels

        x0, x1, y0, y1 = kernels.vector_segments(
            x,
            y,
            u,
            v,
            scale=1.0 if scale is None else float(scale),
            pivot=pivot,
            head_ratio=0.28 if name == "barbs" else 0.22,
        )
        segment_color: Any
        if color is not None and not isinstance(color, str):
            values = np.asarray(color).reshape(-1)
            if len(values) != len(x):
                raise ValueError(f"{name} color values must match U and V")
            keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(u) & np.isfinite(v)
            keep &= np.hypot(u, v) > 0
            segment_color = np.repeat(values[keep], 3)
        else:
            segment_color = resolve_color(color) if color is not None else self._next_color()
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": segment_color,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "width": float(width),
                    "opacity": 1.0 if alpha is None else float(alpha),
                },
            },
        )
        return PolyCollection(self, entry)

    def quiver(self, *args: Any, data: Any = None, **kwargs: Any) -> PolyCollection:
        del data
        return self._vector_field(args, kwargs, "quiver")

    def barbs(self, *args: Any, data: Any = None, **kwargs: Any) -> PolyCollection:
        del data
        return self._vector_field(args, kwargs, "barbs")

    def quiverkey(
        self,
        Q: PolyCollection,
        X: float,
        Y: float,
        U: float,
        label: str,
        **kwargs: Any,
    ) -> PolyCollection:
        angle = np.deg2rad(float(kwargs.pop("angle", 0.0)))
        kwargs.pop("coordinates", None)
        labelpos = kwargs.pop("labelpos", "N")
        labelsep = float(kwargs.pop("labelsep", 0.1))
        color = kwargs.pop("color", Q.get_color())
        labelcolor = kwargs.pop("labelcolor", None)
        kwargs.pop("fontproperties", None)
        kwargs.pop("zorder", None)
        check_unsupported(kwargs, "quiverkey()")
        from xy import kernels

        x0, x1, y0, y1 = kernels.vector_segments(
            np.asarray([float(X)], dtype=np.float64),
            np.asarray([float(Y)], dtype=np.float64),
            np.asarray([float(U) * np.cos(angle)], dtype=np.float64),
            np.asarray([float(U) * np.sin(angle)], dtype=np.float64),
            head_ratio=0.22,
        )
        chosen = (
            resolve_color(color)
            if color is not None and isinstance(color, (str, tuple, list))
            else self._next_color()
        )
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {"color": chosen, "width": 1.2},
            },
        )
        offsets = {
            "N": (0.0, labelsep),
            "S": (0.0, -labelsep),
            "E": (labelsep, 0.0),
            "W": (-labelsep, 0.0),
        }
        if labelpos not in offsets:
            raise ValueError("quiverkey labelpos must be N, S, E, or W")
        dx, dy = offsets[labelpos]
        self._add(
            "@text",
            {
                "args": (float(X) + dx, float(Y) + dy, str(label)),
                "kwargs": {"color": resolve_color(labelcolor)} if labelcolor is not None else {},
            },
        )
        return PolyCollection(self, entry)

    def streamplot(
        self,
        x: Any,
        y: Any,
        u: Any,
        v: Any,
        density: Any = 1,
        linewidth: Any = None,
        color: Any = None,
        cmap: Any = None,
        norm: Any = None,
        arrowsize: float = 1,
        arrowstyle: str = "-|>",
        minlength: float = 0.1,
        transform: Any = None,
        zorder: Any = None,
        start_points: Any = None,
        maxlength: float = 4.0,
        integration_direction: str = "both",
        broken_streamlines: bool = True,
        *,
        num_arrows: int = 1,
        data: Any = None,
    ) -> StreamplotSet:
        del norm, arrowsize, arrowstyle, minlength, transform, zorder, broken_streamlines
        del start_points, integration_direction, num_arrows
        x_values = np.asarray(_from_data(x, data), dtype=np.float64)
        y_values = np.asarray(_from_data(y, data), dtype=np.float64)
        u_values = np.asarray(_from_data(u, data), dtype=np.float64)
        v_values = np.asarray(_from_data(v, data), dtype=np.float64)
        if u_values.shape != v_values.shape or u_values.ndim != 2:
            raise ValueError("streamplot U and V must be matching 2-D arrays")
        if x_values.ndim == y_values.ndim == 2:
            x_values, y_values = _regular_mesh_axes(x_values, y_values, u_values.shape)
        if x_values.ndim != 1 or y_values.ndim != 1:
            raise ValueError("streamplot X and Y must define a regular grid")
        density_value = float(np.max(np.asarray(density, dtype=np.float64)))
        width_value = (
            1.2 if linewidth is None else float(np.nanmean(np.asarray(linewidth, dtype=np.float64)))
        )
        from xy import kernels

        max_steps = max(1, min(100_000, int(float(maxlength) * max(u_values.shape) * 8)))
        x0, x1, y0, y1 = kernels.streamlines(
            x_values,
            y_values,
            u_values,
            v_values,
            density=density_value,
            max_steps=max_steps,
        )
        if color is not None and not isinstance(color, str):
            numeric_color = np.asarray(color, dtype=np.float64)
            chosen_color: Any = np.full(len(x0), float(np.nanmean(numeric_color)))
        else:
            chosen_color = resolve_color(color) if color is not None else self._next_color()
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": chosen_color,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "width": width_value,
                },
            },
        )
        collection = PolyCollection(self, entry)
        return StreamplotSet(collection, collection)
