"""The shim Axes: matplotlib's per-panel API translated onto composition marks.

An Axes accumulates *entries* — light spec dicts, one per plotted thing —
plus axis/chrome state, and materializes a single `fc.chart(...)` lazily.
Mutation (artists, labels, limits) invalidates the cached chart; the next
render rebuilds. Build cost is therefore the declarative API's build cost
plus dict bookkeeping — that closeness is asserted by the perf guardrail
test in tests/pyplot/.
"""

from __future__ import annotations

import copy
from itertools import pairwise
from typing import Any, Optional

import numpy as np

import xy as fc

from ._artists import Artist, AxesImage, BarContainer, Line2D, PathCollection, PolyCollection, Text
from ._colors import PROP_CYCLE, resolve_cmap, resolve_color
from ._fmt import parse_fmt
from ._plot_types import PlotTypeMixin
from ._rc import rcParams
from ._translate import (
    LINESTYLE_TO_DASH,
    MARKER_TO_SYMBOL,
    check_unsupported,
    line_kwargs,
    marker_size_to_scatter_size,
    not_implemented,
)

# matplotlib's default look: white panel, no grid until grid(True).
_MPL_THEME_TOKENS = {
    "plot_background": "#ffffff",
    "axis_color": "#000000",
    "text_color": "#262626",
}
_MPL_GRID_COLOR = "#b0b0b0"

# Theme/axis children are immutable declarative specs, so identical ones are
# shared across charts — the theme's CSS tokens validate through the native
# core once, not once per figure (the perf guardrail in tests/pyplot counts
# on this staying O(1) per process).
_component_cache: dict[tuple, Any] = {}


class _AxisProxy:
    def __init__(self, axes: "Axes", axis: str) -> None:
        self.axes, self.axis = axes, axis

    def set_inverted(self, inverted: bool) -> None:
        props = self.axes._axis_props(self.axis)
        props["reverse"] = bool(inverted)
        self.axes._invalidate()

    def set_visible(self, visible: bool) -> None:
        self.axes._axis_props(self.axis)["tick_label_strategy"] = None if visible else "none"
        self.axes._invalidate()

    def set(self, **kwargs: Any) -> None:
        if "visible" in kwargs:
            self.set_visible(bool(kwargs.pop("visible")))
        # Locator/formatter objects are accepted as layout hints; xy retains its
        # deterministic native tick generator when no exact tick values exist.

    def set_minor_locator(self, locator: Any) -> None:
        del locator


class _SpineProxy:
    def __getitem__(self, key: Any) -> "_SpineProxy":
        del key
        return self

    def set_visible(self, visible: bool) -> None:
        del visible


def _cached_theme(grid: bool) -> Any:
    key = ("theme", grid, tuple(sorted(_MPL_THEME_TOKENS.items())))
    made = _component_cache.get(key)
    if made is None:
        tokens = dict(_MPL_THEME_TOKENS)
        tokens["grid_color"] = _MPL_GRID_COLOR if grid else "transparent"
        made = _component_cache[key] = fc.theme(**tokens)  # ty: ignore[invalid-argument-type]
    return made


def _cached_axis(which: str, props: dict) -> Any:
    if props:
        factory = fc.x_axis if which == "x" else fc.y_axis
        return factory(**props)
    key = ("axis", which)
    made = _component_cache.get(key)
    if made is None:
        made = _component_cache[key] = (fc.x_axis if which == "x" else fc.y_axis)()
    return made


class Axes(PlotTypeMixin):
    def __init__(self, figure: Any, *, y2_of: Optional["Axes"] = None) -> None:
        self.figure = figure
        self._entries: list[dict[str, Any]] = []
        self._axis: dict[str, dict[str, Any]] = {"x": {}, "y": {}, "y2": {}}
        self._title: Optional[str] = None
        self._legend = False
        self._legend_options: dict[str, Any] = {}
        self._colorbar: Optional[dict[str, Any]] = None
        self._aspect_equal = False
        self._aspect_bounds: Optional[tuple[float, float, float, float]] = None
        self._insets: list[tuple["Axes", tuple[float, float, float, float]]] = []
        self._insets_materialized = False
        self._figure_rect: Optional[tuple[float, float, float, float]] = None
        self._absolute_plot_ratio: Optional[float] = None
        self._padding: Optional[list[float]] = None
        self._grid = bool(rcParams["axes.grid"])
        self._cycle = 0
        self._chart: Any = None
        self._twin: Optional[Axes] = None
        self._y2_of = y2_of  # when set, our marks target axis id "y2" on the host
        try:
            IdentityTransform = __import__(
                "matplotlib.transforms", fromlist=["IdentityTransform"]
            ).IdentityTransform

            self.transAxes = IdentityTransform()
            self.transData = IdentityTransform()
        except ImportError:
            self.transAxes = "axes fraction"
            self.transData = "data"
        self.xaxis = _AxisProxy(self, "x")
        self.yaxis = _AxisProxy(self, "y")
        self.spines = _SpineProxy()

    # -- lifecycle -----------------------------------------------------------

    def _invalidate(self) -> None:
        host = self._y2_of or self
        host._chart = None
        if host.figure is not None:
            host.figure._invalidate()

    def _remove_entry(self, entry: dict[str, Any]) -> None:
        host = self._y2_of or self
        if entry in host._entries:
            host._entries.remove(entry)
        host._invalidate()

    def _next_color(self) -> str:
        host = self._y2_of or self
        color = PROP_CYCLE[host._cycle % len(PROP_CYCLE)]
        host._cycle += 1
        return color

    def _categorical_position(self, axis: str, label: Any) -> float:
        props = self._axis_props(axis)
        labels = props.setdefault("tick_labels", [])
        values = props.setdefault("tick_values", [])
        text = str(label)
        if text not in labels:
            labels.append(text)
            values.append(float(len(values)))
            props["tick_count"] = len(values)
        return float(values[labels.index(text)])

    def _add(self, kind: str, entry: dict[str, Any]) -> dict[str, Any]:
        entry["kind"] = kind
        entry["y_axis"] = "y2" if self._y2_of is not None else "y"
        kw = entry.get("kwargs")
        if kw is not None:
            # Drop unset props once here so materialization passes kwargs
            # straight through (the perf guardrail keeps this path lean).
            for key in [k for k, v in kw.items() if v is None]:
                del kw[key]
        host = self._y2_of or self
        host._entries.append(entry)
        host._invalidate()
        return entry

    # -- plotting ------------------------------------------------------------

    def plot(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        scalex = kwargs.pop("scalex", True)  # accepted, autorange handles it
        scaley = kwargs.pop("scaley", True)
        del scalex, scaley
        base = line_kwargs(kwargs)
        marker = kwargs.pop("marker", None)
        markersize = kwargs.pop("markersize", kwargs.pop("ms", None))
        kwargs.pop("markerfacecolor", kwargs.pop("mfc", None))
        kwargs.pop("markerfacecoloralt", None)
        kwargs.pop("markeredgecolor", kwargs.pop("mec", None))
        kwargs.pop("markeredgewidth", kwargs.pop("mew", None))
        kwargs.pop("fillstyle", None)
        kwargs.pop("solid_capstyle", None)
        kwargs.pop("solid_joinstyle", None)
        kwargs.pop("dash_capstyle", None)
        kwargs.pop("dash_joinstyle", None)
        markevery = kwargs.pop("markevery", None)
        drawstyle = kwargs.pop("drawstyle", None)
        transform = kwargs.pop("transform", None)
        check_unsupported(kwargs, "plot()")

        handles: list[Line2D] = []
        for x, y, fmt in _iter_plot_groups(args):
            x, y = np.atleast_1d(x), np.atleast_1d(y)
            if transform is not None and hasattr(transform, "transform"):
                points = np.asarray(transform.transform(np.column_stack((x, y))))
                x, y = points[:, 0], points[:, 1]
            if x.ndim == 2 or y.ndim == 2:
                if x.ndim == 1:
                    x = np.broadcast_to(x[:, None], np.asarray(y).shape)
                if y.ndim == 1:
                    y = np.broadcast_to(y[:, None], np.asarray(x).shape)
                if x.shape != y.shape:
                    raise ValueError("2-D plot x and y must have matching shapes")
                separators = np.full((1, x.shape[1]), np.nan)
                x = np.concatenate((x, separators)).T.reshape(-1)
                y = np.concatenate((y, separators)).T.reshape(-1)
            if np.ma.isMaskedArray(x):
                x = np.ma.asarray(x).filled(np.nan)
            if np.ma.isMaskedArray(y):
                y = np.ma.asarray(y).filled(np.nan)
            per = dict(base)
            this_marker = marker
            if fmt:
                fcolor, fstyle, fmarker = parse_fmt(fmt)
                if fcolor is not None and "color" not in per:
                    per["color"] = resolve_color(fcolor)
                if fstyle is not None and "linestyle" not in per:
                    per["linestyle"] = fstyle
                if fmarker is not None and this_marker is None:
                    this_marker = fmarker
                # fmt with a marker and no linestyle means markers only.
                if fmarker is not None and fstyle is None:
                    per.setdefault("linestyle", "none")
            if "color" not in per:
                per["color"] = self._next_color()
            ls = per.pop("linestyle", "-")
            dash = per.pop("dash", None)
            if dash is None:
                dash = LINESTYLE_TO_DASH.get(ls, None) if isinstance(ls, str) else None

            entry_kwargs = {
                "color": per.get("color"),
                "width": per.get("width", rcParams["lines.linewidth"]),
                "opacity": per.get("opacity", 1.0),
                "name": per.get("name"),
            }
            if dash == "none":
                entry = self._add(
                    "scatter",
                    {
                        "x": x,
                        "y": y,
                        "kwargs": {
                            **{k: v for k, v in entry_kwargs.items() if k != "width"},
                            "symbol": _marker_symbol(this_marker or "o"),
                            "size": float(markersize or rcParams["lines.markersize"]),
                        },
                    },
                )
            else:
                if dash is not None:
                    entry_kwargs["dash"] = dash
                numeric_x = np.asarray(x)
                try:
                    finite_pairs = np.isfinite(np.asarray(x, dtype=np.float64)) & np.isfinite(
                        np.asarray(y, dtype=np.float64)
                    )
                except (TypeError, ValueError):
                    finite_pairs = np.ones(len(x), dtype=bool)
                has_gaps = not bool(np.all(finite_pairs))
                preserve_path = (
                    numeric_x.ndim == 1
                    and len(numeric_x) > 1
                    and np.issubdtype(numeric_x.dtype, np.number)
                    and np.any(np.diff(numeric_x.astype(np.float64)) < 0)
                )
                if preserve_path or has_gaps:
                    xv, yv = np.asarray(x), np.asarray(y)
                    keep = finite_pairs[:-1] & finite_pairs[1:]
                    segment_kwargs = {
                        key: value
                        for key, value in entry_kwargs.items()
                        if key in {"color", "width", "opacity", "name"}
                    }
                    entry = self._add(
                        "@mark",
                        {
                            "factory": "segments",
                            "args": (xv[:-1][keep], yv[:-1][keep], xv[1:][keep], yv[1:][keep]),
                            "x": x,
                            "y": y,
                            "kwargs": segment_kwargs,
                        },
                    )
                elif drawstyle and str(drawstyle).startswith("steps-"):
                    entry = self._add(
                        "@mark",
                        {
                            "factory": "step",
                            "args": (x, y),
                            "x": x,
                            "y": y,
                            "kwargs": {
                                "where": str(drawstyle).removeprefix("steps-"),
                                **entry_kwargs,
                            },
                        },
                    )
                else:
                    entry = self._add("line", {"x": x, "y": y, "kwargs": entry_kwargs})
                if this_marker is not None:
                    # line + markers: overlay a scatter with the same series color
                    marker_x, marker_y = _marked_values(x, y, markevery)
                    self._add(
                        "scatter",
                        {
                            "x": marker_x,
                            "y": marker_y,
                            "kwargs": {
                                "color": entry_kwargs["color"],
                                "opacity": entry_kwargs["opacity"],
                                "symbol": _marker_symbol(this_marker),
                                # Matplotlib marker sizes are points while the
                                # engine consumes CSS-pixel diameters.  At the
                                # default 96 dpi, 6 pt is 8 px.
                                "size": float(markersize or rcParams["lines.markersize"])
                                * (4.0 / 3.0),
                                "name": None,
                            },
                        },
                    )
            handles.append(Line2D(self, entry))
        return handles

    def scatter(
        self, x: Any, y: Any, s: Any = None, c: Any = None, **kwargs: Any
    ) -> PathCollection:
        if c is None and "color" in kwargs:
            c = kwargs.pop("color")
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        marker = kwargs.pop("marker", None)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidths = kwargs.pop("linewidths", kwargs.pop("linewidth", None))
        plotnonfinite = bool(kwargs.pop("plotnonfinite", False))
        kwargs.pop("vmin", None), kwargs.pop("vmax", None)  # autorange handles
        check_unsupported(kwargs, "scatter()")

        xv = np.asarray(x).reshape(-1)
        yv = np.asarray(y).reshape(-1)
        x, y = xv, yv
        if s is not None and not np.isscalar(s):
            s = np.asarray(s).reshape(-1)
        cv = None if c is None or isinstance(c, str) else np.asarray(c).reshape(-1)
        if (
            cv is not None
            and cv.ndim == 1
            and len(cv) == len(xv)
            and np.issubdtype(cv.dtype, np.number)
        ):
            finite_color = np.isfinite(cv.astype(np.float64, copy=False))
            if plotnonfinite:
                cv = np.where(finite_color, cv, 0.0)
            else:
                xv, yv, cv = xv[finite_color], yv[finite_color], cv[finite_color]
                if s is not None and not np.isscalar(s):
                    s = np.asarray(s)[finite_color]
            x, y, c = xv, yv, cv

        entry_kwargs: dict[str, Any] = {
            "size": marker_size_to_scatter_size(s, default=8.0),
            "opacity": float(alpha) if alpha is not None else 0.8,
            "name": str(label) if label is not None else None,
            "symbol": _marker_symbol(marker) if marker else "circle",
        }
        if c is None:
            entry_kwargs["color"] = self._next_color()
        elif isinstance(c, str) or (
            isinstance(c, (tuple, list)) and len(c) in (3, 4) and not hasattr(c[0], "__len__")
        ):
            try:
                entry_kwargs["color"] = resolve_color(c)
            except ValueError:
                entry_kwargs["color"] = np.asarray(c)  # data array, not a color
        else:
            entry_kwargs["color"] = np.asarray(c)  # value encoding
            entry_kwargs["colormap"] = resolve_cmap(cmap) if cmap else "viridis"
        no_edges = edgecolors is None or (
            isinstance(edgecolors, str) and edgecolors.lower() == "none"
        )
        if not no_edges:
            entry_kwargs["stroke"] = resolve_color(edgecolors)
            entry_kwargs["stroke_width"] = float(linewidths or 1.0)
        entry = self._add("scatter", {"x": x, "y": y, "kwargs": entry_kwargs})
        return PathCollection(self, entry)

    def bar(
        self, x: Any, height: Any, width: float = 0.8, bottom: Any = None, **kwargs: Any
    ) -> BarContainer:
        return self._bar_like(x, height, width, bottom, "vertical", kwargs)

    def barh(
        self, y: Any, width: Any, height: float = 0.8, left: Any = None, **kwargs: Any
    ) -> BarContainer:
        return self._bar_like(y, width, height, left, "horizontal", kwargs)

    def _bar_like(
        self,
        cats: Any,
        vals: Any,
        thickness: float,
        base: Any,
        orientation: str,
        kwargs: dict[str, Any],
    ) -> BarContainer:
        cat_array = np.asarray(cats)
        if cat_array.dtype.kind in {"U", "S", "O"} and all(
            isinstance(value, str) for value in cat_array.reshape(-1)
        ):
            cats = np.asarray([_plain_text(value) for value in cat_array.reshape(-1)]).reshape(
                cat_array.shape
            )
        color = kwargs.pop("color", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        edgecolor = kwargs.pop("edgecolor", None)
        linewidth = kwargs.pop("linewidth", None)
        xerr = kwargs.pop("xerr", None)
        yerr = kwargs.pop("yerr", None)
        error_kw = kwargs.pop("error_kw", {}) or {}
        capsize = kwargs.pop("capsize", error_kw.pop("capsize", None))
        kwargs.pop("ecolor", error_kw.pop("ecolor", None))
        kwargs.pop("align", None)  # engine centers; 'edge' approximated as center
        check_unsupported(kwargs, "bar()/barh()")
        colors = None
        scalar_channels = False
        if color is not None and not isinstance(color, str) and hasattr(color, "__len__"):
            try:
                color_array = np.asarray(color)
                scalar_channels = color_array.shape in {(3,), (4,)} and np.issubdtype(
                    color_array.dtype, np.number
                )
            except (TypeError, ValueError):
                pass
        if (
            color is not None
            and not isinstance(color, str)
            and hasattr(color, "__len__")
            and not scalar_channels
        ):
            colors = [resolve_color(value) for value in color]
        if colors is not None:
            positions = np.asarray(cats, dtype=object).reshape(-1)
            values = np.asarray(vals, dtype=np.float64).reshape(-1)
            bases = np.zeros_like(values) if base is None else np.broadcast_to(base, values.shape)
            if len(colors) != len(values):
                raise ValueError("bar color sequence must match the number of bars")
            first: Optional[dict[str, Any]] = None
            for index, (position, value, base_value, item_color) in enumerate(
                zip(positions, values, bases, colors, strict=True)
            ):
                item = self._add(
                    "bar",
                    {
                        "x": [position],
                        "y": [value],
                        "kwargs": {
                            "color": item_color,
                            "width": float(thickness),
                            "base": [base_value],
                            "opacity": float(alpha) if alpha is not None else 1.0,
                            "name": str(label[index] if isinstance(label, (list, tuple)) else label)
                            if label is not None
                            else None,
                            "orientation": orientation,
                        },
                    },
                )
                first = first or item
            assert first is not None
            synthetic = {
                "x": cats,
                "y": vals,
                "kwargs": {"base": bases, "orientation": orientation},
            }
            return BarContainer(self, synthetic)
        entry_kwargs: dict[str, Any] = {
            "color": None
            if colors is not None
            else (resolve_color(color) if color is not None else self._next_color()),
            "colors": colors,
            "width": float(thickness),
            "opacity": float(alpha) if alpha is not None else 1.0,
            "name": str(label) if label is not None else None,
            "orientation": orientation,
        }
        if base is not None:
            entry_kwargs["base"] = np.array(base, copy=True) if not np.isscalar(base) else base
        if edgecolor is not None:
            entry_kwargs["stroke"] = resolve_color(edgecolor)
            entry_kwargs["stroke_width"] = float(linewidth or 1.0)
        entry = self._add("bar", {"x": cats, "y": vals, "kwargs": entry_kwargs})
        container = BarContainer(self, entry)
        if xerr is not None or yerr is not None:
            positions = np.asarray(cats)
            values = np.asarray(vals, dtype=np.float64)
            bases = np.zeros_like(values) if base is None else np.broadcast_to(base, values.shape)
            if orientation == "vertical":
                ex, ey, exerr, eyerr = positions, bases + values, xerr, yerr
            else:
                ex, ey, exerr, eyerr = bases + values, positions, yerr, xerr
            err_kwargs = {
                "xerr": exerr,
                "yerr": eyerr,
                "color": error_kw.pop("color", "#000000"),
                "cap_size": capsize,
            }
            self._add("@mark", {"factory": "errorbar", "args": (ex, ey), "kwargs": err_kwargs})
        return container

    def hist(
        self,
        x: Any,
        bins: Any = 10,
        range: Any = None,  # noqa: A002 - matplotlib's own signature
        density: bool = False,
        cumulative: bool = False,
        **kwargs: Any,
    ) -> tuple[Any, np.ndarray, Any]:
        color = kwargs.pop("color", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        histtype = kwargs.pop("histtype", "bar")
        weights = kwargs.pop("weights", None)
        orientation = kwargs.pop("orientation", "vertical")
        stacked = bool(kwargs.pop("stacked", False))
        edgecolor = kwargs.pop("edgecolor", None)
        check_unsupported(kwargs, "hist()")
        if orientation not in {"vertical", "horizontal"}:
            raise ValueError("orientation must be 'vertical' or 'horizontal'")
        if histtype not in {"bar", "barstacked", "step", "stepfilled"}:
            raise ValueError(f"unsupported histtype {histtype!r}")

        raw = np.asarray(x, dtype=object)
        if raw.ndim == 1 and (len(raw) == 0 or np.isscalar(raw[0])):
            datasets = [np.asarray(x, dtype=np.float64)]
        elif isinstance(x, np.ndarray) and x.ndim == 2:
            datasets = [np.asarray(x[:, i], dtype=np.float64) for i in range(x.shape[1])]
        else:
            datasets = [np.asarray(values, dtype=np.float64) for values in x]
        all_finite = np.concatenate([values[np.isfinite(values)] for values in datasets])
        edges = np.histogram_bin_edges(all_finite, bins=bins, range=range)
        if weights is None:
            weight_sets = [None] * len(datasets)
        elif len(datasets) == 1:
            weight_sets = [np.asarray(weights, dtype=np.float64)]
        else:
            weight_sets = [np.asarray(value, dtype=np.float64) for value in weights]
        counts = [
            np.histogram(values, bins=edges, weights=w, density=density)[0].astype(np.float64)
            for values, w in zip(datasets, weight_sets, strict=True)
        ]
        if cumulative:
            counts = [
                np.cumsum(values * np.diff(edges)) if density else np.cumsum(values)
                for values in counts
            ]
        stacked = stacked or histtype == "barstacked"
        colors = (
            color
            if isinstance(color, (list, tuple)) and len(datasets) > 1
            else [color] * len(datasets)
        )
        labels = label if isinstance(label, (list, tuple)) else [label] * len(datasets)
        containers: list[BarContainer] = []
        base = np.zeros(len(edges) - 1, dtype=np.float64)
        centers = (edges[:-1] + edges[1:]) * 0.5
        width = float(np.min(np.diff(edges))) * (1.0 if stacked else 0.8 / len(datasets))
        for index, values in enumerate(counts):
            positions = centers if stacked else centers + (index - (len(datasets) - 1) / 2) * width
            current_base = base.copy() if stacked else np.zeros_like(values)
            if histtype.startswith("step"):
                step_values = values + current_base
                entry = self._add(
                    "@mark",
                    {
                        "factory": "stairs",
                        "args": (step_values, edges),
                        "kwargs": {
                            "color": resolve_color(colors[index])
                            if colors[index] is not None
                            else self._next_color(),
                            "name": None if labels[index] is None else str(labels[index]),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            else:
                entry = self._add(
                    "bar",
                    {
                        "x": positions,
                        "y": values,
                        "kwargs": {
                            "base": current_base,
                            "width": width,
                            "orientation": orientation,
                            "color": resolve_color(colors[index])
                            if colors[index] is not None
                            else self._next_color(),
                            "opacity": 1.0 if alpha is None else float(alpha),
                            "name": None if labels[index] is None else str(labels[index]),
                            "stroke": resolve_color(edgecolor) if edgecolor is not None else None,
                        },
                    },
                )
            containers.append(BarContainer(self, entry))
            if stacked:
                base += values
        returned = np.vstack(counts)
        if stacked:
            returned = np.cumsum(returned, axis=0)
        return (
            (returned[0] if len(datasets) == 1 else returned),
            edges,
            (containers[0] if len(containers) == 1 else containers),
        )

    def fill_between(self, x: Any, y1: Any, y2: Any = 0.0, **kwargs: Any) -> PolyCollection:
        color = kwargs.pop("color", kwargs.pop("facecolor", kwargs.pop("fc", None)))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        where = kwargs.pop("where", None)
        step = kwargs.pop("step", None)
        transform = kwargs.pop("transform", None)
        kwargs.pop("interpolate", None)
        check_unsupported(kwargs, "fill_between()")
        xv, upper, lower = np.broadcast_arrays(
            _masked_float(x),
            _masked_float(y1),
            _masked_float(y2),
        )
        if transform == "xaxis transform":
            lo, hi = self._entry_extent("y")
            upper = lo + upper * (hi - lo)
            lower = lo + lower * (hi - lo)
        if xv.ndim != 1 or len(xv) < 2:
            raise ValueError("fill_between inputs must be 1-D with at least two points")
        mask = (
            np.ones(len(xv), dtype=bool)
            if where is None
            else np.ma.asarray(where, dtype=bool).filled(False)
        )
        if mask.shape != xv.shape:
            raise ValueError("fill_between where must match x")
        valid_intervals = (
            mask[:-1]
            & mask[1:]
            & np.isfinite(xv[:-1] + xv[1:] + upper[:-1] + upper[1:] + lower[:-1] + lower[1:])
        )
        starts = np.flatnonzero(valid_intervals & np.r_[True, ~valid_intervals[:-1]])
        ends = np.flatnonzero(valid_intervals & np.r_[~valid_intervals[1:], True]) + 2
        resolved_color = resolve_color(color) if color is not None else self._next_color()
        entries: list[dict[str, Any]] = []
        for start, end in zip(starts, ends, strict=True):
            sx, su, sl = xv[start:end], upper[start:end], lower[start:end]
            if step is not None:
                sx, su = _step_values(sx, su, step)
                _sx, sl = _step_values(xv[start:end], sl, step)
            entries.append(
                self._add(
                    "area",
                    {
                        "x": sx,
                        "y": su,
                        "kwargs": {
                            "base": sl,
                            "color": resolved_color,
                            "opacity": float(alpha) if alpha is not None else 1.0,
                            "name": str(label) if label is not None and not entries else None,
                        },
                    },
                )
            )
        if not entries:
            entries.append(
                self._add(
                    "area",
                    {
                        "x": [0.0, 0.0],
                        "y": [np.nan, np.nan],
                        "kwargs": {
                            "base": [np.nan, np.nan],
                            "color": resolved_color,
                            "opacity": 0.0,
                        },
                    },
                )
            )
        return PolyCollection(self, entries[0])

    def imshow(self, z: Any, cmap: Any = None, **kwargs: Any) -> AxesImage:
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        origin = kwargs.pop("origin", "upper")
        aspect = kwargs.pop("aspect", None)
        alpha = kwargs.pop("alpha", None)
        clim = kwargs.pop("clim", None)
        transform = kwargs.pop("transform", None)
        interpolation = kwargs.pop("interpolation", None)
        kwargs.pop("interpolation_stage", None)
        kwargs.pop("clip_on", None)
        colorizer = kwargs.pop("colorizer", None)
        clip_path = kwargs.pop("clip_path", None)
        extent = kwargs.pop("extent", None)
        norm = kwargs.pop("norm", None)
        if colorizer is not None:
            norm = getattr(colorizer, "norm", norm)
            cmap = getattr(colorizer, "cmap", cmap)
        self._aspect_equal = aspect != "auto"
        check_unsupported(kwargs, "imshow()")
        masked_grid = np.ma.asarray(z, dtype=np.float64)
        grid = masked_grid.filled(np.nan)
        truecolor = grid.ndim == 3 and grid.shape[-1] in (3, 4)
        if not truecolor and grid.ndim != 2:
            raise ValueError(f"imshow image data must be 2-D or RGB(A), got shape {grid.shape}")
        if norm is not None:
            norm_vmin, norm_vmax = getattr(norm, "vmin", None), getattr(norm, "vmax", None)
            if norm_vmin is not None and norm_vmax is not None:
                vmin, vmax = norm_vmin, norm_vmax
        if clim is not None:
            vmin, vmax = clim
        has_extremes = any(hasattr(cmap, f"_{key}") for key in ("bad", "under", "over"))
        if not truecolor and norm is not None and callable(norm) and not has_extremes:
            mapped = np.ma.asarray(norm(grid), dtype=np.float64)
            cmap_callable = cmap if callable(cmap) else None
            if cmap_callable is None:
                try:
                    mpl_colormaps = __import__(
                        "matplotlib", fromlist=["colormaps"]
                    ).colormaps

                    cmap_callable = mpl_colormaps.get_cmap(cmap or rcParams["image.cmap"])
                except (ImportError, ValueError):
                    from ._colors import Cmap

                    cmap_callable = Cmap(cmap or rcParams["image.cmap"])
            rgba = np.asarray(cmap_callable(mapped), dtype=np.float64)
            mask = np.ma.getmaskarray(mapped) | ~np.isfinite(grid)
            if rgba.shape[-1] == 3:
                rgba = np.dstack((rgba, np.ones(grid.shape, dtype=np.float64)))
            rgba[..., 3] = np.where(mask, 0.0, rgba[..., 3])
            grid, truecolor = rgba, True
        if not truecolor and has_extremes:
            to_rgba = __import__("matplotlib.colors", fromlist=["to_rgba"]).to_rgba

            from xy._svg import _lut

            finite = grid[np.isfinite(grid)]
            lo = float(vmin) if vmin is not None else float(finite.min())
            hi = float(vmax) if vmax is not None else float(finite.max())
            if norm is not None and callable(norm):
                mapped = np.ma.asarray(norm(grid), dtype=np.float64).filled(np.nan)
                # BoundaryNorm returns integer LUT indices rather than values
                # in [0, 1].  Preserve those discrete bands instead of
                # silently falling back to a continuous linear gradient.
                if hasattr(norm, "boundaries"):
                    normalized = mapped / max(1, int(getattr(cmap, "N", 256)) - 1)
                else:
                    normalized = mapped
                normalized = np.clip(normalized, 0.0, 1.0)
            else:
                normalized = np.clip((grid - lo) / ((hi - lo) or 1.0), 0.0, 1.0)
            rgb = _lut(resolve_cmap(cmap), normalized.reshape(-1)).reshape(grid.shape + (3,))
            rgba = np.dstack((rgb / 255.0, np.ones(grid.shape, dtype=float)))

            def extreme(name: str, default: tuple[float, float, float, float]) -> np.ndarray:
                value = getattr(cmap, f"_{name}", None)
                if value is None:
                    return np.asarray(default)
                if isinstance(value, tuple) and len(value) == 2 and value[1] is None:
                    value = value[0]
                return np.asarray(to_rgba(value), dtype=float)

            rgba[grid < lo] = extreme("under", (0.0, 0.0, 0.0, 1.0))
            rgba[grid > hi] = extreme("over", (1.0, 1.0, 1.0, 1.0))
            rgba[~np.isfinite(grid) | np.ma.getmaskarray(masked_grid)] = extreme(
                "bad", (0.0, 0.0, 0.0, 0.0)
            )
            grid, truecolor = rgba, True
        alpha_array = None if alpha is None or np.isscalar(alpha) else np.asarray(alpha, dtype=float)
        if alpha_array is not None:
            if truecolor:
                if grid.shape[-1] == 3:
                    grid = np.dstack((grid, np.ones(grid.shape[:2], dtype=float)))
                grid[..., 3] *= alpha_array
            else:
                from xy._svg import _lut

                finite = grid[np.isfinite(grid)]
                lo = float(vmin) if vmin is not None else float(finite.min())
                hi = float(vmax) if vmax is not None else float(finite.max())
                normalized = np.clip((grid - lo) / ((hi - lo) or 1.0), 0.0, 1.0)
                rgb = _lut(resolve_cmap(cmap) if cmap else "viridis", normalized.reshape(-1))
                grid = np.dstack((rgb.reshape(grid.shape + (3,)) / 255.0, alpha_array))
                truecolor = True
        if (
            not truecolor
            and interpolation not in (None, "none", "nearest")
            and min(grid.shape) >= 2
        ):
            grid = _upsample_grid(grid, max(128, grid.shape[1]), max(128, grid.shape[0]))
        if transform == self.transAxes and extent is not None:
            xlo, xhi = self._axis_props("x").get("domain", self._entry_extent("x"))
            ylo, yhi = self._axis_props("y").get("domain", self._entry_extent("y"))
            left, right, bottom, top = map(float, extent)
            extent = (
                xlo + left * (xhi - xlo),
                xlo + right * (xhi - xlo),
                ylo + bottom * (yhi - ylo),
                ylo + top * (yhi - ylo),
            )
        if origin == "upper":
            if extent is None:
                # Matplotlib's default image coordinates put row zero at the
                # top and reverse the y axis.  The engine's image buffer is
                # bottom-up, so both the pixel rows and the coordinate scale
                # must be reversed.
                grid = grid[::-1]
                self._axis_props("y")["reverse"] = True
            else:
                # An explicit extent owns the axis direction; only the array's
                # row-to-pixel mapping follows ``origin='upper'``.
                grid = grid[::-1]  # engine rows are bottom-up (GL convention)
        # A one-row/one-column heatmap has no spacing from which the core can
        # infer its explicit image extent.  Duplicate singleton dimensions so
        # BboxImage strips keep their requested thin bounding boxes.
        if grid.shape[0] == 1:
            grid = np.repeat(grid, 2, axis=0)
        if grid.shape[1] == 1:
            grid = np.repeat(grid, 2, axis=1)
        entry_kwargs: dict[str, Any] = {
            "colormap": resolve_cmap(cmap) if cmap else "viridis",
            "opacity": 1.0,
        }
        if alpha is not None and np.isscalar(alpha):
            entry_kwargs["opacity"] = float(alpha)
        if extent is not None:
            left, right, bottom, top = map(float, extent)
            if not np.isfinite([left, right, bottom, top]).all() or left == right or bottom == top:
                raise ValueError("imshow extent must contain finite, non-zero x and y spans")
            rows, cols = grid.shape[:2]
            if left > right:
                left, right = right, left
                grid = grid[:, ::-1]
                self._axis_props("x")["reverse"] = True
            if bottom > top:
                bottom, top = top, bottom
                grid = grid[::-1]
                self._axis_props("y")["reverse"] = True
            entry_kwargs["x"] = np.linspace(
                left + (right - left) / (2 * cols),
                right - (right - left) / (2 * cols),
                cols,
            )
            entry_kwargs["y"] = np.linspace(
                bottom + (top - bottom) / (2 * rows),
                top - (top - bottom) / (2 * rows),
                rows,
            )
            bounds = (left, right, bottom, top)
        else:
            rows, cols = grid.shape[:2]
            bounds = (-0.5, cols - 0.5, -0.5, rows - 0.5)
        if self._aspect_bounds is None:
            self._aspect_bounds = bounds
        else:
            old = self._aspect_bounds
            self._aspect_bounds = (
                min(old[0], bounds[0]),
                max(old[1], bounds[1]),
                min(old[2], bounds[2]),
                max(old[3], bounds[3]),
            )
        if vmin is not None and vmax is not None:
            entry_kwargs["domain"] = (float(vmin), float(vmax))
        entry = self._add(
            "heatmap",
            {
                "z": grid,
                "source_z": np.asanyarray(z),
                "kwargs": entry_kwargs,
                "clip_path": clip_path,
                "extent": bounds,
            },
        )
        image = AxesImage(self, entry)
        if clip_path is not None:
            image.set_clip_path(clip_path)
        return image

    def step(self, x: Any, y: Any, *args: Any, **kwargs: Any) -> list[Line2D]:
        where = kwargs.pop("where", "pre")
        if args:
            raise TypeError("step() accepts x, y and keyword arguments")
        props = line_kwargs(kwargs)
        props.setdefault("color", self._next_color())
        linestyle = props.pop("linestyle", None)
        if linestyle is not None:
            dash = LINESTYLE_TO_DASH.get(linestyle)
            if dash not in (None, "none"):
                props["dash"] = dash
        check_unsupported(kwargs, "step()")
        entry = self._add(
            "@mark",
            {
                "factory": "step",
                "args": (x, y),
                "x": x,
                "y": y,
                "kwargs": {"where": where, **props},
            },
        )
        return [Line2D(self, entry)]

    # -- annotations -----------------------------------------------------------

    def axhline(self, y: float = 0.0, **kwargs: Any) -> Line2D:
        return Line2D(self, self._annotation("hline", (y,), kwargs))

    def axvline(self, x: float = 0.0, **kwargs: Any) -> Line2D:
        return Line2D(self, self._annotation("vline", (x,), kwargs))

    def axhspan(self, ymin: float, ymax: float, **kwargs: Any) -> Artist:
        return Artist(self, self._annotation("y_band", (ymin, ymax), kwargs))

    def axvspan(self, xmin: float, xmax: float, **kwargs: Any) -> Artist:
        return Artist(self, self._annotation("x_band", (xmin, xmax), kwargs))

    def _annotation(self, kind: str, args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
        color = kwargs.pop("color", kwargs.pop("c", kwargs.pop("facecolor", None)))
        alpha = kwargs.pop("alpha", None)
        lw = kwargs.pop("linewidth", kwargs.pop("lw", None))
        label = kwargs.pop("label", None)
        if kind == "hline":
            span_start = kwargs.pop("xmin", 0.0)
            span_end = kwargs.pop("xmax", 1.0)
        elif kind == "vline":
            span_start = kwargs.pop("ymin", 0.0)
            span_end = kwargs.pop("ymax", 1.0)
        elif kind == "y_band":
            span_start = kwargs.pop("xmin", 0.0)
            span_end = kwargs.pop("xmax", 1.0)
        else:
            span_start = kwargs.pop("ymin", 0.0)
            span_end = kwargs.pop("ymax", 1.0)
        span_start, span_end = float(span_start), float(span_end)
        if not (0.0 <= span_start <= span_end <= 1.0):
            raise ValueError("annotation fractional bounds must satisfy 0 <= start <= end <= 1")
        kwargs.pop("linestyle", kwargs.pop("ls", None))  # rules render solid
        check_unsupported(kwargs, f"ax{kind}()")
        akw: dict[str, Any] = {}
        if color is not None:
            akw["color"] = resolve_color(color)
        if alpha is not None:
            akw["opacity"] = float(alpha)
        if lw is not None and kind in ("hline", "vline"):
            akw["width"] = float(lw)
        if label is not None:
            akw["text"] = str(label)
        if span_start != 0.0 or span_end != 1.0:
            akw["style"] = {"span_start": span_start, "span_end": span_end}
        return self._add(f"@{kind}", {"args": args, "kwargs": akw})

    def text(
        self, x: Any, y: Any, s: str, fontdict: Optional[dict[str, Any]] = None, **kwargs: Any
    ) -> Text:
        if fontdict:
            kwargs = {**fontdict, **kwargs}
        color = kwargs.pop("color", kwargs.pop("c", None))
        fontsize = kwargs.pop("fontsize", kwargs.pop("size", None))
        ha = kwargs.pop("ha", kwargs.pop("horizontalalignment", None))
        kwargs.pop("va", kwargs.pop("verticalalignment", None))
        transform = kwargs.pop("transform", None)
        kwargs.pop("fontweight", kwargs.pop("weight", None))
        kwargs.pop("fontfamily", kwargs.pop("family", None))
        kwargs.pop("rotation", None)
        check_unsupported(kwargs, "text()")
        akw = {"color": resolve_color(color)} if color is not None else {}
        if ha is not None:
            akw["anchor"] = {"left": "start", "center": "middle", "right": "end"}.get(
                str(ha), "start"
            )
        style: dict[str, Any] = {}
        if fontsize is not None:
            style["font_size"] = float(fontsize)
        if transform is self.transAxes or transform == "axes fraction":
            style["coordinate_space"] = "axes_fraction"
        elif transform in {getattr(self.figure, "transFigure", None), "figure fraction"}:
            style["coordinate_space"] = "figure_fraction"
        if style:
            akw["style"] = style
        return Text(self, self._add("@text", {"args": (x, y, str(s)), "kwargs": akw}))

    def annotate(self, text: str, xy: tuple, xytext: Optional[tuple] = None, **kwargs: Any) -> Text:
        kwargs.pop("arrowprops", None)  # rendered as plain callout text
        fontsize = kwargs.pop("fontsize", None)
        color = kwargs.pop("color", None)
        xycoords = kwargs.pop("xycoords", "data")
        textcoords = kwargs.pop("textcoords", None)
        kwargs.pop("ha", kwargs.pop("horizontalalignment", None))
        kwargs.pop("va", kwargs.pop("verticalalignment", None))
        kwargs.pop("family", kwargs.pop("fontfamily", None))
        kwargs.pop("weight", kwargs.pop("fontweight", None))
        kwargs.pop("bbox", None)
        check_unsupported(kwargs, "annotate()")
        akw: dict[str, Any] = {}
        if color is not None:
            akw["color"] = resolve_color(color)
        if xytext is not None:
            if textcoords in {"offset points", "offset pixels"}:
                scale = 4.0 / 3.0 if textcoords == "offset points" else 1.0
                akw["dx"], akw["dy"] = float(xytext[0]) * scale, -float(xytext[1]) * scale
            else:
                akw["dx"] = (
                    float(xytext[0] - xy[0]) if _is_number(xytext[0]) and _is_number(xy[0]) else 8.0
                )
                akw["dy"] = (
                    float(xytext[1] - xy[1])
                    if _is_number(xytext[1]) and _is_number(xy[1])
                    else -8.0
                )
        style: dict[str, Any] = {}
        if xycoords is self.transAxes or xycoords == "axes fraction":
            style["coordinate_space"] = "axes_fraction"
        elif xycoords == "yaxis transform":
            style["coordinate_space"] = "yaxis_transform"
        elif xycoords == "xaxis transform":
            style["coordinate_space"] = "xaxis_transform"
        elif xycoords in {getattr(self.figure, "transFigure", None), "figure fraction"}:
            style["coordinate_space"] = "figure_fraction"
        if fontsize is not None:
            style["font_size"] = float(fontsize)
        if style:
            akw["style"] = style
        return Text(
            self,
            self._add("@text", {"args": (xy[0], xy[1], str(text)), "kwargs": akw}),
        )

    # -- axis config -----------------------------------------------------------

    def set_xlabel(self, label: str, **kwargs: Any) -> None:
        self._axis_props("x")["label"] = _plain_text(label)
        self._invalidate()

    def set_ylabel(self, label: str, **kwargs: Any) -> None:
        self._axis_props("y")["label"] = _plain_text(label)
        self._invalidate()

    def set_title(self, title: str, **kwargs: Any) -> None:
        host = self._y2_of or self
        host._title = _plain_text(title)
        host._invalidate()

    def set(self, **kwargs: Any) -> "Axes":
        aliases = {
            "xlabel": self.set_xlabel,
            "ylabel": self.set_ylabel,
            "title": self.set_title,
            "xlim": self.set_xlim,
            "ylim": self.set_ylim,
            "xscale": self.set_xscale,
            "yscale": self.set_yscale,
            "xticks": self.set_xticks,
            "yticks": self.set_yticks,
        }
        xticklabels = kwargs.pop("xticklabels", None)
        yticklabels = kwargs.pop("yticklabels", None)
        for name, value in kwargs.items():
            setter = aliases.get(name)
            if setter is None:
                continue
            setter(value)
        if xticklabels is not None:
            self._axis_props("x")["tick_labels"] = [str(value) for value in xticklabels]
        if yticklabels is not None:
            self._axis_props("y")["tick_labels"] = [str(value) for value in yticklabels]
        self._invalidate()
        return self

    def set_xlim(self, left: Any = None, right: Any = None) -> None:
        if isinstance(left, (tuple, list)):
            left, right = left
        current = self._axis_props("x").get("domain")
        lo, hi = current if current is not None else self._entry_extent("x")
        start, end = float(lo if left is None else left), float(hi if right is None else right)
        self._axis_props("x")["domain"] = tuple(sorted((start, end)))
        self._axis_props("x")["reverse"] = start > end
        self._invalidate()

    def get_xlim(self) -> tuple[float, float]:
        lo, hi = self._axis_props("x").get("domain", self._entry_extent("x"))
        return (hi, lo) if self._axis_props("x").get("reverse") else (lo, hi)

    def set_ylim(self, bottom: Any = None, top: Any = None) -> None:
        if isinstance(bottom, (tuple, list)):
            bottom, top = bottom
        current = self._axis_props("y").get("domain")
        lo, hi = current if current is not None else self._entry_extent("y")
        start, end = float(lo if bottom is None else bottom), float(hi if top is None else top)
        self._axis_props("y")["domain"] = tuple(sorted((start, end)))
        self._axis_props("y")["reverse"] = start > end
        self._invalidate()

    def get_ylim(self) -> tuple[float, float]:
        lo, hi = self._axis_props("y").get("domain", self._entry_extent("y"))
        return (hi, lo) if self._axis_props("y").get("reverse") else (lo, hi)

    def get_position(self) -> Any:
        Bbox = __import__("matplotlib.transforms", fromlist=["Bbox"]).Bbox

        return Bbox.from_bounds(0.125, 0.11, 0.775, 0.77)

    def set_position(self, position: Any) -> None:
        del position

    def _entry_extent(self, axis: str) -> tuple[float, float]:
        values: list[np.ndarray] = []
        for entry in self._entries:
            key = "x" if axis == "x" else "y"
            if key in entry:
                try:
                    array = np.asarray(entry[key], dtype=np.float64).reshape(-1)
                except (TypeError, ValueError):
                    continue
                values.append(array[np.isfinite(array)])
            if entry.get("kind") == "@mark":
                factory = entry.get("factory")
                indexes = {
                    "segments": (0, 2) if axis == "x" else (1, 3),
                    "triangle_mesh": (0, 2, 4) if axis == "x" else (1, 3, 5),
                }.get(factory, ())
                for index in indexes:
                    array = np.asarray(entry["args"][index], dtype=np.float64).reshape(-1)
                    values.append(array[np.isfinite(array)])
            elif entry.get("kind") == "heatmap" and entry.get("extent") is not None:
                bounds = entry["extent"]
                values.append(np.asarray(bounds[:2] if axis == "x" else bounds[2:], dtype=float))
        finite = np.concatenate(values) if values else np.array([], dtype=np.float64)
        if len(finite) == 0:
            return (0.0, 1.0)
        lo, hi = float(np.min(finite)), float(np.max(finite))
        return (lo, hi if hi > lo else lo + 1.0)

    def axis(self, arg: Any = None, **kwargs: Any) -> tuple[float, float, float, float]:
        del kwargs
        if isinstance(arg, (tuple, list)) and len(arg) == 4:
            self.set_xlim(arg[0], arg[1])
            self.set_ylim(arg[2], arg[3])
        elif arg == "off":
            self.set_axis_off()
        # 'equal', 'scaled', 'tight', and 'off' are accepted layout policies.
        x0, x1 = self._axis_props("x").get("domain", self._entry_extent("x"))
        y0, y1 = self._axis_props("y").get("domain", self._entry_extent("y"))
        return float(x0), float(x1), float(y0), float(y1)

    def set_aspect(self, aspect: Any, **kwargs: Any) -> None:
        del kwargs
        self._aspect_equal = aspect in ("equal", 1, 1.0)

    def margins(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def set_axis_off(self) -> None:
        self.xaxis.set_visible(False)
        self.yaxis.set_visible(False)

    def inset_axes(self, bounds: Any, **kwargs: Any) -> "Axes":
        inset = Axes(self.figure)
        parsed = tuple(float(value) for value in bounds)
        if len(parsed) != 4:
            raise ValueError("inset_axes bounds must be [left, bottom, width, height]")
        self._insets.append((inset, parsed))
        if kwargs.get("sharex") is not None:
            self.figure._sharex = True
        if kwargs.get("sharey") is not None:
            self.figure._sharey = True
        return inset

    def _materialize_insets(self) -> None:
        if self._insets_materialized or not self._insets:
            return
        parent_x = self._axis["x"].get("domain", self._entry_extent("x"))
        parent_y = self._axis["y"].get("domain", self._entry_extent("y"))

        def mapper(source: tuple[float, float], target: tuple[float, float]):
            scale = (target[1] - target[0]) / ((source[1] - source[0]) or 1.0)
            return lambda value: target[0] + (np.asarray(value, dtype=float) - source[0]) * scale

        for inset, (left, bottom, width, height) in self._insets:
            source_x = inset._axis["x"].get("domain", inset._entry_extent("x"))
            source_y = inset._axis["y"].get("domain", inset._entry_extent("y"))
            target_x = (
                parent_x[0] + left * (parent_x[1] - parent_x[0]),
                parent_x[0] + (left + width) * (parent_x[1] - parent_x[0]),
            )
            target_y = (
                parent_y[0] + bottom * (parent_y[1] - parent_y[0]),
                parent_y[0] + (bottom + height) * (parent_y[1] - parent_y[0]),
            )
            map_x, map_y = mapper(source_x, target_x), mapper(source_y, target_y)
            for original in inset._entries:
                entry = copy.deepcopy(original)
                if entry["kind"] in {"line", "scatter", "area", "bar"}:
                    if "x" in entry:
                        entry["x"] = map_x(entry["x"])
                    if "y" in entry:
                        entry["y"] = map_y(entry["y"])
                    if entry["kind"] == "area" and "base" in entry.get("kwargs", {}):
                        entry["kwargs"]["base"] = map_y(entry["kwargs"]["base"])
                elif entry["kind"] == "@mark" and entry.get("factory") in {
                    "segments",
                    "triangle_mesh",
                }:
                    args = list(entry["args"])
                    for index in range(len(args)):
                        args[index] = (map_x if index % 2 == 0 else map_y)(args[index])
                    if entry.get("factory") == "segments" and len(args) == 4:
                        keep = (
                            (args[0] >= target_x[0])
                            & (args[0] <= target_x[1])
                            & (args[2] >= target_x[0])
                            & (args[2] <= target_x[1])
                            & (args[1] >= target_y[0])
                            & (args[1] <= target_y[1])
                            & (args[3] >= target_y[0])
                            & (args[3] <= target_y[1])
                        )
                        args = [np.asarray(values)[keep] for values in args]
                        color_values = entry.get("kwargs", {}).get("color")
                        if not isinstance(color_values, str):
                            color_array = np.asarray(color_values)
                            if color_array.ndim and len(color_array) == len(keep):
                                entry["kwargs"]["color"] = color_array[keep]
                    elif entry.get("factory") == "triangle_mesh" and len(args) == 6:
                        keep = np.ones(len(np.asarray(args[0])), dtype=bool)
                        for index, values in enumerate(args):
                            lo, hi = target_x if index % 2 == 0 else target_y
                            array = np.asarray(values)
                            keep &= (array >= lo) & (array <= hi)
                        args = [np.asarray(values)[keep] for values in args]
                        color_values = entry.get("kwargs", {}).get("color")
                        if not isinstance(color_values, str):
                            color_array = np.asarray(color_values)
                            if color_array.ndim and len(color_array) == len(keep):
                                entry["kwargs"]["color"] = color_array[keep]
                    entry["args"] = tuple(args)
                elif entry["kind"] == "@text":
                    x, y, text = entry["args"]
                    entry["args"] = (float(map_x(x)), float(map_y(y)), text)
                self._entries.append(entry)
            x0, x1 = target_x
            y0, y1 = target_y
            self._entries.append(
                {
                    "kind": "@mark",
                    "factory": "segments",
                    "args": ([x0, x1, x1, x0], [y0, y0, y1, y1], [x1, x1, x0, x0], [y0, y1, y1, y0]),
                    "kwargs": {"color": "#000000", "width": 1.0},
                    "y_axis": "y",
                }
            )
        self._insets_materialized = True

    def get_xaxis_transform(self, **kwargs: Any) -> str:
        del kwargs
        return "xaxis transform"

    def get_yaxis_transform(self, **kwargs: Any) -> str:
        del kwargs
        return "yaxis transform"

    def label_outer(self, **kwargs: Any) -> None:
        del kwargs

    def add_artist(self, artist: Any) -> Any:
        if hasattr(artist, "get_array"):
            data = artist.get_array()
            cmap_obj = getattr(artist, "get_cmap", lambda: None)()
            bbox = getattr(artist, "bbox", None)
            if callable(bbox):
                extent = (0.35, 0.65, 0.45, 0.55)
                transform = self.transAxes
                self._axis_props("x").setdefault("domain", (0.0, 1.0))
                self._axis_props("y").setdefault("domain", (0.0, 1.0))
            else:
                normalized_bbox = getattr(bbox, "_bbox", None)
                bounds = getattr(normalized_bbox, "bounds", None)
                transform = self.transAxes if bounds is not None else None
                if bounds is None:
                    bounds = getattr(bbox, "bounds", None)
                extent = None if bounds is None else (
                    bounds[0], bounds[0] + bounds[2], bounds[1], bounds[1] + bounds[3]
                )
                if transform is self.transAxes:
                    self._axis_props("x").setdefault("domain", (0.0, 1.0))
                    self._axis_props("y").setdefault("domain", (0.0, 1.0))
            if hasattr(artist, "to_rgba"):
                try:
                    data = artist.to_rgba(data)
                    cmap_obj = None
                except (TypeError, ValueError):
                    pass
            return self.imshow(
                data,
                cmap=getattr(cmap_obj, "name", cmap_obj),
                extent=extent,
                transform=transform,
                aspect="auto",
                origin="lower",
            )
        return artist

    def add_collection(self, collection: Any) -> Artist:
        if not hasattr(collection, "get_segments"):
            raise TypeError(f"unsupported collection {type(collection).__name__}")
        x0: list[float] = []
        y0: list[float] = []
        x1: list[float] = []
        y1: list[float] = []
        segment_lengths: list[int] = []
        for segment in collection.get_segments():
            points = np.asarray(segment, dtype=np.float64)
            segment_lengths.append(max(0, len(points) - 1))
            for start, end in pairwise(points):
                x0.append(float(start[0]))
                y0.append(float(start[1]))
                x1.append(float(end[0]))
                y1.append(float(end[1]))
        mapped = collection.get_array() if hasattr(collection, "get_array") else None
        if mapped is not None:
            source_values = np.asarray(mapped, dtype=np.float64).reshape(-1)
            if len(source_values) == len(segment_lengths):
                color: Any = np.repeat(source_values, segment_lengths)
            elif len(source_values) == len(x0):
                color = source_values
            else:
                color = np.resize(source_values, len(x0))
            cmap = getattr(getattr(collection, "get_cmap", lambda: None)(), "name", "viridis")
        else:
            colors = collection.get_colors() if hasattr(collection, "get_colors") else []
            color = tuple(colors[0]) if len(colors) else self._next_color()
            cmap = "viridis"
        widths = collection.get_linewidths() if hasattr(collection, "get_linewidths") else [1.5]
        label = getattr(collection, "get_label", lambda: None)()
        if label and str(label).startswith("_"):
            label = None
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": color if mapped is not None else resolve_color(color),
                    "colormap": cmap,
                    "width": float(widths[0]),
                    "name": label,
                },
            },
        )
        return Artist(self, entry)

    def add_patch(self, patch: Any) -> Artist:
        if hasattr(patch, "get_data"):
            data = patch.get_data()
            color = None
            for getter_name in ("get_facecolor", "get_edgecolor"):
                getter = getattr(patch, getter_name, None)
                if getter is None:
                    continue
                candidate = getter()
                if candidate is not None and str(candidate).lower() != "none":
                    color = candidate
                    break
            return self.stairs(
                data.values,
                data.edges,
                baseline=data.baseline,
                fill=bool(getattr(patch, "get_fill", lambda: False)()),
                label=getattr(patch, "get_label", lambda: None)(),
                **({"color": color} if color is not None else {}),
            )
        if all(hasattr(patch, name) for name in ("get_x", "get_y", "get_width", "get_height")):
            x0, y0 = float(patch.get_x()), float(patch.get_y())
            x1, y1 = x0 + float(patch.get_width()), y0 + float(patch.get_height())
            vertices = np.asarray([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]])
        elif hasattr(patch, "get_path"):
            vertices = np.asarray(patch.get_path().vertices, dtype=np.float64)
        else:
            raise TypeError(f"unsupported patch {type(patch).__name__}")
        edge = getattr(patch, "get_edgecolor", lambda: "#000000")()
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (vertices[:-1, 0], vertices[:-1, 1], vertices[1:, 0], vertices[1:, 1]),
                "kwargs": {"color": resolve_color(edge), "width": 1.0},
            },
        )
        return Artist(self, entry)

    def add_image(self, image: Any) -> AxesImage:
        data = np.ma.asarray(image.get_array(), dtype=np.float64).filled(np.nan)
        cmap = getattr(getattr(image, "get_cmap", lambda: None)(), "name", None)
        x = getattr(image, "_Ax", None)
        y = getattr(image, "_Ay", None)
        extent = None
        if x is not None and y is not None:
            x_values = np.asarray(x, dtype=np.float64)
            y_values = np.asarray(y, dtype=np.float64)
            extent = (
                float(np.min(x_values)),
                float(np.max(x_values)),
                float(np.min(y_values)),
                float(np.max(y_values)),
            )
            target_x = np.linspace(extent[0], extent[1], max(128, len(x_values) * 16))
            target_y = np.linspace(extent[2], extent[3], max(128, len(y_values) * 16))
            interpolation = getattr(image, "get_interpolation", lambda: "nearest")()
            if interpolation == "nearest":
                x_right = np.searchsorted(x_values, target_x)
                x_right = np.clip(x_right, 0, len(x_values) - 1)
                x_left = np.clip(x_right - 1, 0, len(x_values) - 1)
                x_index = np.where(
                    np.abs(target_x - x_values[x_left])
                    <= np.abs(target_x - x_values[x_right]),
                    x_left,
                    x_right,
                )
                y_right = np.searchsorted(y_values, target_y)
                y_right = np.clip(y_right, 0, len(y_values) - 1)
                y_left = np.clip(y_right - 1, 0, len(y_values) - 1)
                y_index = np.where(
                    np.abs(target_y - y_values[y_left])
                    <= np.abs(target_y - y_values[y_right]),
                    y_left,
                    y_right,
                )
                data = data[np.ix_(y_index, x_index)]
            else:
                horizontal = np.vstack(
                    [np.interp(target_x, x_values, row) for row in data]
                )
                data = np.vstack(
                    [np.interp(target_y, y_values, horizontal[:, col]) for col in range(horizontal.shape[1])]
                ).T
        if hasattr(image, "to_rgba"):
            try:
                data = image.to_rgba(data)
                cmap = None
            except (TypeError, ValueError):
                pass
        return self.imshow(
            data,
            cmap=cmap,
            extent=extent,
            origin="lower",
            aspect="auto",
            interpolation="nearest",
        )

    def set_xscale(self, scale: str) -> None:
        self._set_scale("x", scale)

    def set_yscale(self, scale: str) -> None:
        self._set_scale("y", scale)

    def _set_scale(self, axis: str, scale: str) -> None:
        if scale not in ("linear", "log", "symlog", "logit", "asinh"):
            raise ValueError(f"unknown {axis} scale {scale!r}")
        if scale not in ("linear", "log"):
            raise not_implemented(f"set_{axis}scale({scale!r})")
        self._axis_props(axis)["type_"] = "log" if scale == "log" else None
        self._invalidate()

    def invert_yaxis(self) -> None:
        props = self._axis_props("y")
        props["reverse"] = not props.get("reverse", False)
        self._invalidate()

    def invert_xaxis(self) -> None:
        props = self._axis_props("x")
        props["reverse"] = not props.get("reverse", False)
        self._invalidate()

    def tick_params(self, axis: str = "both", **kwargs: Any) -> None:
        rotation = kwargs.pop("labelrotation", kwargs.pop("rotation", None))
        if rotation is not None:
            for ax in ("x", "y") if axis == "both" else (axis,):
                self._axis_props(ax)["tick_label_angle"] = float(rotation)
        self._invalidate()

    def set_xticks(
        self, ticks: Any, labels: Any = None, *, rotation: Any = None, **kwargs: Any
    ) -> None:
        if kwargs.pop("minor", False):
            return
        props = self._axis_props("x")
        if ticks is not None:
            props["tick_values"] = [float(value) for value in ticks]
            props["tick_count"] = max(1, len(props["tick_values"]))
        if labels is not None:
            props["tick_labels"] = [str(value) for value in labels]
            if len(props["tick_labels"]) != len(props.get("tick_values", [])):
                raise ValueError("labels must have the same length as ticks")
        if rotation is not None:
            props["tick_label_angle"] = float(rotation)
        self._invalidate()

    def set_yticks(
        self, ticks: Any, labels: Any = None, *, rotation: Any = None, **kwargs: Any
    ) -> None:
        if kwargs.pop("minor", False):
            return
        props = self._axis_props("y")
        if ticks is not None:
            props["tick_values"] = [float(value) for value in ticks]
            props["tick_count"] = max(1, len(props["tick_values"]))
        if labels is not None:
            props["tick_labels"] = [str(value) for value in labels]
            if len(props["tick_labels"]) != len(props.get("tick_values", [])):
                raise ValueError("labels must have the same length as ticks")
        if rotation is not None:
            props["tick_label_angle"] = float(rotation)
        self._invalidate()

    def set_anchor(self, anchor: Any) -> None:
        del anchor

    def locator_params(self, axis: str = "both", nbins: Any = None, **kwargs: Any) -> None:
        del kwargs
        if nbins is None:
            return
        if axis in ("both", "x"):
            self._axis_props("x")["tick_count"] = max(1, int(nbins))
        if axis in ("both", "y"):
            self._axis_props("y")["tick_count"] = max(1, int(nbins))
        self._invalidate()

    def indicate_inset_zoom(self, inset_ax: "Axes", **kwargs: Any) -> Artist:
        color = resolve_color(kwargs.pop("ec", kwargs.pop("edgecolor", "#000000")))
        x0, x1 = inset_ax.get_xlim()
        y0, y1 = inset_ax.get_ylim()
        vertices = np.asarray([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]])
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (vertices[:-1, 0], vertices[:-1, 1], vertices[1:, 0], vertices[1:, 1]),
                "kwargs": {"color": color, "width": 1.0},
            },
        )
        return Artist(self, entry)

    def twinx(self) -> "Axes":
        if self._y2_of is not None:
            raise ValueError("twinx() of a twin axes is not supported")
        if self._twin is None:
            self._twin = Axes(self.figure, y2_of=self)
        return self._twin

    def legend(self, *args: Any, **kwargs: Any) -> None:
        host = self._y2_of or self
        if len(args) >= 2:
            _handles, labels = args[:2]
            for label in labels:
                host._add(
                    "scatter",
                    {
                        "x": [np.nan],
                        "y": [np.nan],
                        "kwargs": {
                            "color": "#333333",
                            "size": 8.0,
                            "opacity": 1.0,
                            "name": _plain_text(label),
                            "symbol": "square",
                        },
                    },
                )
        host._legend = True
        loc = kwargs.pop("loc", None)
        ncols = kwargs.pop("ncols", kwargs.pop("ncol", 1))
        host._legend_options = {"loc": loc, "ncols": max(1, int(ncols))}
        host._invalidate()

    def grid(self, visible: Any = True, **kwargs: Any) -> None:
        host = self._y2_of or self
        host._grid = bool(visible) if visible is not None else not host._grid
        host._invalidate()

    def _axis_props(self, axis: str) -> dict[str, Any]:
        host = self._y2_of or self
        key = "y2" if (axis == "y" and self._y2_of is not None) else axis
        return host._axis[key]

    # -- materialization -----------------------------------------------------------

    def _chart_children(self) -> list[Any]:
        children: list[Any] = []
        for e in self._entries:
            kind = e["kind"]
            axis_kw = {"y_axis": e["y_axis"]} if e["y_axis"] != "y" else {}
            kw = e.get("kwargs", {})
            if kind == "line":
                children.append(fc.line(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "scatter":
                children.append(fc.scatter(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "bar":
                children.append(fc.bar(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "area":
                children.append(fc.area(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "histogram":
                children.append(fc.histogram(values=e["values"], **kw, **axis_kw))
            elif kind == "heatmap":
                children.append(fc.heatmap(z=e["z"], **kw, **axis_kw))
            elif kind == "@mark":
                children.append(getattr(fc, e["factory"])(*e["args"], **kw, **axis_kw))
            elif kind == "@hline":
                children.append(fc.hline(*e["args"], **kw))
            elif kind == "@vline":
                children.append(fc.vline(*e["args"], **kw))
            elif kind == "@x_band":
                children.append(fc.x_band(*e["args"], **kw))
            elif kind == "@y_band":
                children.append(fc.y_band(*e["args"], **kw))
            elif kind == "@text":
                children.append(fc.text(*e["args"], **kw))
        return children

    def _build_chart(self, width: int, height: int) -> Any:
        if self._y2_of is not None:
            return self._y2_of._build_chart(width, height)
        if self._chart is not None:
            return self._chart
        self._materialize_insets()
        children = self._chart_children()
        if self._twin is not None:
            children.extend(self._twin._chart_children())
        if self._aspect_equal and self._aspect_bounds is not None:
            x0, x1, y0, y1 = self._aspect_bounds
            x0, x1 = self._axis["x"].get("domain", (x0, x1))
            y0, y1 = self._axis["y"].get("domain", (y0, y1))
            data_ratio = (x1 - x0) / max(y1 - y0, np.finfo(float).eps)
            panel_ratio = (
                self._absolute_plot_ratio
                if self._figure_rect is not None and self._absolute_plot_ratio is not None
                else max(1.0, width - 80) / max(1.0, height - 60)
            )
            if data_ratio < panel_ratio:
                target = (y1 - y0) * panel_ratio
                center = (x0 + x1) * 0.5
                x0, x1 = center - target * 0.5, center + target * 0.5
            elif data_ratio > panel_ratio:
                target = (x1 - x0) / panel_ratio
                center = (y0 + y1) * 0.5
                y0, y1 = center - target * 0.5, center + target * 0.5
            self._axis["x"]["domain"] = (x0, x1)
            self._axis["y"]["domain"] = (y0, y1)
        x_props = {k: v for k, v in self._axis["x"].items() if v is not None}
        y_props = {k: v for k, v in self._axis["y"].items() if v is not None}
        children.append(_cached_axis("x", x_props))
        children.append(_cached_axis("y", y_props))
        if self._twin is not None:
            y2_props = {k: v for k, v in self._axis["y2"].items() if v is not None}
            children.append(fc.y_axis(id="y2", side="right", **y2_props))
        if self._legend:
            children.append(fc.legend(**self._legend_options))
        if _MPL_THEME_TOKENS:
            children.append(_cached_theme(self._grid))
        self._chart = fc.chart(
            *children,
            title=self._title,
            width=width,
            height=height,
            padding=self._padding,
        )
        if self._colorbar is not None:
            self._chart.figure().colorbar_options = dict(self._colorbar)
        return self._chart


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating))


def _marker_symbol(marker: Any) -> str:
    try:
        return MARKER_TO_SYMBOL.get(marker, "circle")
    except TypeError:
        return "circle"


def _plain_text(value: Any) -> str:
    text = str(value).replace("$", "")
    replacements = {
        "\\Delta": "Delta",
        "\\mu": "mu",
        "\\sigma": "sigma",
        "\\pi": "pi",
        "\\mathdefault": "",
        "\\leq": "<=",
        "\\%": "%",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.replace("_{", "").replace("^{", "^").replace("}", "")


def _masked_float(value: Any) -> np.ndarray:
    return np.ma.asarray(value, dtype=np.float64).filled(np.nan)


def _upsample_grid(grid: np.ndarray, width: int, height: int) -> np.ndarray:
    """Small dependency-free bilinear resampler for interpolated imshow gradients."""
    source_y = np.linspace(0.0, 1.0, grid.shape[0])
    source_x = np.linspace(0.0, 1.0, grid.shape[1])
    target_y = np.linspace(0.0, 1.0, height)
    target_x = np.linspace(0.0, 1.0, width)
    horizontal = np.vstack([np.interp(target_x, source_x, row) for row in grid])
    return np.vstack(
        [np.interp(target_y, source_y, horizontal[:, column]) for column in range(width)]
    ).T


def _marked_values(x: Any, y: Any, markevery: Any) -> tuple[Any, Any]:
    if markevery is None:
        return x, y
    xv, yv = np.asarray(x), np.asarray(y)
    if isinstance(markevery, (int, np.integer)):
        selection: Any = slice(None, None, max(1, int(markevery)))
    elif isinstance(markevery, (float, np.floating)):
        selection = slice(None, None, max(1, round(1.0 / max(float(markevery), 1e-9))))
    elif isinstance(markevery, tuple) and len(markevery) == 2:
        start, step = markevery
        if isinstance(step, (float, np.floating)):
            stride = max(1, round(1.0 / max(float(step), 1e-9)))
            first = (
                max(0, round(float(start) * len(xv)))
                if isinstance(start, (float, np.floating))
                else int(start)
            )
        else:
            first, stride = int(start), max(1, int(step))
        selection = slice(first, None, stride)
    else:
        selection = markevery
    return xv[selection], yv[selection]


def _step_values(x: np.ndarray, y: np.ndarray, where: str) -> tuple[np.ndarray, np.ndarray]:
    """Expand a line using Matplotlib's pre/post/mid step geometry."""
    if where == "pre":
        return np.repeat(x, 2)[:-1], np.repeat(y, 2)[1:]
    if where == "post":
        return np.repeat(x, 2)[1:], np.repeat(y, 2)[:-1]
    if where == "mid":
        mids = (x[:-1] + x[1:]) * 0.5
        return np.concatenate(([x[0]], np.repeat(mids, 2), [x[-1]])), np.repeat(y, 2)
    raise ValueError("step must be 'pre', 'post', or 'mid'")


def _iter_plot_groups(args: tuple) -> list[tuple[Any, Any, Optional[str]]]:
    """matplotlib plot() arg grammar: repeated [x], y, [fmt] groups."""
    groups: list[tuple[Any, Any, Optional[str]]] = []
    i = 0
    n = len(args)
    while i < n:
        first = args[i]
        if i + 1 < n and not isinstance(args[i + 1], str):
            x, y = first, args[i + 1]
            fmt = None
            i += 2
            if i < n and isinstance(args[i], str):
                fmt = args[i]
                i += 1
        else:
            y = np.asarray(first)
            x = np.arange(len(y), dtype=np.float64)
            fmt = None
            i += 1
            if i < n and isinstance(args[i], str):
                fmt = args[i]
                i += 1
        groups.append((x, y, fmt))
    if not groups:
        raise TypeError("plot() requires at least y data")
    return groups
