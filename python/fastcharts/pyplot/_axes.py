"""The shim Axes: matplotlib's per-panel API translated onto composition marks.

An Axes accumulates *entries* — light spec dicts, one per plotted thing —
plus axis/chrome state, and materializes a single `fc.chart(...)` lazily.
Mutation (artists, labels, limits) invalidates the cached chart; the next
render rebuilds. Build cost is therefore the declarative API's build cost
plus dict bookkeeping — that closeness is asserted by the perf guardrail
test in tests/pyplot/.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

import fastcharts as fc

from ._artists import BarContainer, Line2D, PathCollection
from ._colors import PROP_CYCLE, resolve_cmap, resolve_color
from ._fmt import parse_fmt
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


class Axes:
    def __init__(self, figure: Any, *, y2_of: Optional["Axes"] = None) -> None:
        self.figure = figure
        self._entries: list[dict[str, Any]] = []
        self._axis: dict[str, dict[str, Any]] = {"x": {}, "y": {}, "y2": {}}
        self._title: Optional[str] = None
        self._legend = False
        self._grid = bool(rcParams["axes.grid"])
        self._cycle = 0
        self._chart: Any = None
        self._twin: Optional[Axes] = None
        self._y2_of = y2_of  # when set, our marks target axis id "y2" on the host

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
        check_unsupported(kwargs, "plot()")

        handles: list[Line2D] = []
        for x, y, fmt in _iter_plot_groups(args):
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
            per.setdefault("color", self._next_color())
            ls = per.pop("linestyle", "-")
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
                            "symbol": MARKER_TO_SYMBOL.get(this_marker or "o", "circle"),
                            "size": float(markersize or rcParams["lines.markersize"]),
                        },
                    },
                )
            else:
                if dash is not None:
                    entry_kwargs["dash"] = dash
                entry = self._add("line", {"x": x, "y": y, "kwargs": entry_kwargs})
                if this_marker is not None:
                    # line + markers: overlay a scatter with the same series color
                    self._add(
                        "scatter",
                        {
                            "x": x,
                            "y": y,
                            "kwargs": {
                                "color": entry_kwargs["color"],
                                "opacity": entry_kwargs["opacity"],
                                "symbol": MARKER_TO_SYMBOL.get(this_marker, "circle"),
                                "size": float(markersize or rcParams["lines.markersize"]),
                                "name": None,
                            },
                        },
                    )
            handles.append(Line2D(self, entry))
        return handles

    def scatter(
        self, x: Any, y: Any, s: Any = None, c: Any = None, **kwargs: Any
    ) -> PathCollection:
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        marker = kwargs.pop("marker", None)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidths = kwargs.pop("linewidths", kwargs.pop("linewidth", None))
        kwargs.pop("vmin", None), kwargs.pop("vmax", None)  # autorange handles
        check_unsupported(kwargs, "scatter()")

        entry_kwargs: dict[str, Any] = {
            "size": marker_size_to_scatter_size(s, default=6.0),
            "opacity": float(alpha) if alpha is not None else 0.8,
            "name": str(label) if label is not None else None,
            "symbol": MARKER_TO_SYMBOL.get(marker, "circle") if marker else "circle",
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
        if edgecolors is not None:
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
        color = kwargs.pop("color", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        edgecolor = kwargs.pop("edgecolor", None)
        linewidth = kwargs.pop("linewidth", None)
        kwargs.pop("align", None)  # engine centers; 'edge' approximated as center
        check_unsupported(kwargs, "bar()/barh()")
        entry_kwargs: dict[str, Any] = {
            "color": resolve_color(color) if color is not None else self._next_color(),
            "width": float(thickness),
            "opacity": float(alpha) if alpha is not None else 1.0,
            "name": str(label) if label is not None else None,
            "orientation": orientation,
        }
        if base is not None:
            entry_kwargs["base"] = base
        if edgecolor is not None:
            entry_kwargs["stroke"] = resolve_color(edgecolor)
            entry_kwargs["stroke_width"] = float(linewidth or 1.0)
        entry = self._add("bar", {"x": cats, "y": vals, "kwargs": entry_kwargs})
        return BarContainer(self, entry)

    def hist(
        self,
        x: Any,
        bins: Any = 10,
        range: Any = None,  # noqa: A002 - matplotlib's own signature
        density: bool = False,
        cumulative: bool = False,
        **kwargs: Any,
    ) -> tuple[None, None, BarContainer]:
        color = kwargs.pop("color", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        kwargs.pop("histtype", None)  # bars are the only type; steps ≈ bars
        kwargs.pop("edgecolor", None)
        check_unsupported(kwargs, "hist()")
        entry = self._add(
            "histogram",
            {
                "values": x,
                "kwargs": {
                    "bins": bins,
                    "range": tuple(range) if range is not None else None,
                    "density": bool(density),
                    "cumulative": bool(cumulative),
                    "color": resolve_color(color) if color is not None else self._next_color(),
                    "opacity": float(alpha) if alpha is not None else 1.0,
                    "name": str(label) if label is not None else None,
                },
            },
        )
        # matplotlib returns (n, bins, patches); counts/edges are engine-side.
        return None, None, BarContainer(self, entry)

    def fill_between(self, x: Any, y1: Any, y2: Any = 0.0, **kwargs: Any) -> BarContainer:
        color = kwargs.pop("color", kwargs.pop("facecolor", None))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        check_unsupported(kwargs, "fill_between()")
        entry = self._add(
            "area",
            {
                "x": x,
                "y": y1,
                "kwargs": {
                    "base": y2,
                    "color": resolve_color(color) if color is not None else self._next_color(),
                    "opacity": float(alpha) if alpha is not None else 0.35,
                    "name": str(label) if label is not None else None,
                },
            },
        )
        return BarContainer(self, entry)

    def imshow(self, z: Any, cmap: Any = None, **kwargs: Any) -> BarContainer:
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        origin = kwargs.pop("origin", "upper")
        aspect = kwargs.pop("aspect", None)
        kwargs.pop("interpolation", None)  # engine renders exact cells
        kwargs.pop("extent", None)
        del aspect
        check_unsupported(kwargs, "imshow()")
        grid = np.asarray(z, dtype=np.float64)
        if origin == "upper":
            grid = grid[::-1]  # engine rows are bottom-up (GL convention)
        entry_kwargs: dict[str, Any] = {"colormap": resolve_cmap(cmap) if cmap else "viridis"}
        if vmin is not None and vmax is not None:
            entry_kwargs["domain"] = (float(vmin), float(vmax))
        entry = self._add("heatmap", {"z": grid, "kwargs": entry_kwargs})
        return BarContainer(self, entry)

    pcolormesh = imshow

    def step(self, x: Any, y: Any, *args: Any, **kwargs: Any) -> list[Line2D]:
        kwargs.pop("where", None)  # step renders as a line either way (compat doc)
        kwargs.setdefault("linestyle", "-")
        return self.plot(x, y, *args, **kwargs)

    # -- annotations -----------------------------------------------------------

    def axhline(self, y: float = 0.0, **kwargs: Any) -> None:
        self._annotation("hline", (y,), kwargs)

    def axvline(self, x: float = 0.0, **kwargs: Any) -> None:
        self._annotation("vline", (x,), kwargs)

    def axhspan(self, ymin: float, ymax: float, **kwargs: Any) -> None:
        self._annotation("y_band", (ymin, ymax), kwargs)

    def axvspan(self, xmin: float, xmax: float, **kwargs: Any) -> None:
        self._annotation("x_band", (xmin, xmax), kwargs)

    def _annotation(self, kind: str, args: tuple, kwargs: dict[str, Any]) -> None:
        color = kwargs.pop("color", kwargs.pop("c", kwargs.pop("facecolor", None)))
        alpha = kwargs.pop("alpha", None)
        lw = kwargs.pop("linewidth", kwargs.pop("lw", None))
        label = kwargs.pop("label", None)
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
        host = self._y2_of or self
        host._entries.append({"kind": f"@{kind}", "args": args, "kwargs": akw, "y_axis": "y"})
        host._invalidate()

    def text(self, x: Any, y: Any, s: str, **kwargs: Any) -> None:
        color = kwargs.pop("color", kwargs.pop("c", None))
        kwargs.pop("fontsize", None)
        kwargs.pop("ha", None), kwargs.pop("va", None)
        check_unsupported(kwargs, "text()")
        akw = {"color": resolve_color(color)} if color is not None else {}
        host = self._y2_of or self
        host._entries.append(
            {"kind": "@text", "args": (x, y, str(s)), "kwargs": akw, "y_axis": "y"}
        )
        host._invalidate()

    def annotate(self, text: str, xy: tuple, xytext: Optional[tuple] = None, **kwargs: Any) -> None:
        kwargs.pop("arrowprops", None)  # rendered as plain callout text
        kwargs.pop("fontsize", None)
        color = kwargs.pop("color", None)
        check_unsupported(kwargs, "annotate()")
        akw: dict[str, Any] = {}
        if color is not None:
            akw["color"] = resolve_color(color)
        if xytext is not None:
            akw["dx"] = (
                float(xytext[0] - xy[0]) if _is_number(xytext[0]) and _is_number(xy[0]) else 8.0
            )
            akw["dy"] = (
                float(xytext[1] - xy[1]) if _is_number(xytext[1]) and _is_number(xy[1]) else -8.0
            )
        host = self._y2_of or self
        host._entries.append(
            {"kind": "@text", "args": (xy[0], xy[1], str(text)), "kwargs": akw, "y_axis": "y"}
        )
        host._invalidate()

    # -- axis config -----------------------------------------------------------

    def set_xlabel(self, label: str, **kwargs: Any) -> None:
        self._axis_props("x")["label"] = str(label)
        self._invalidate()

    def set_ylabel(self, label: str, **kwargs: Any) -> None:
        self._axis_props("y")["label"] = str(label)
        self._invalidate()

    def set_title(self, title: str, **kwargs: Any) -> None:
        host = self._y2_of or self
        host._title = str(title)
        host._invalidate()

    def set_xlim(self, left: Any = None, right: Any = None) -> None:
        if isinstance(left, (tuple, list)):
            left, right = left
        self._axis_props("x")["domain"] = (float(left), float(right))
        self._invalidate()

    def set_ylim(self, bottom: Any = None, top: Any = None) -> None:
        if isinstance(bottom, (tuple, list)):
            bottom, top = bottom
        self._axis_props("y")["domain"] = (float(bottom), float(top))
        self._invalidate()

    def set_xscale(self, scale: str) -> None:
        self._set_scale("x", scale)

    def set_yscale(self, scale: str) -> None:
        self._set_scale("y", scale)

    def _set_scale(self, axis: str, scale: str) -> None:
        if scale not in ("linear", "log"):
            raise not_implemented(f"{axis}scale({scale!r})", "'linear' or 'log'")
        self._axis_props(axis)["type_"] = None if scale == "linear" else "log"
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
        # Arbitrary tick positions are not an engine feature; tick *count* and
        # label rotation map. Positions are accepted and approximated by count.
        props = self._axis_props("x")
        if ticks is not None and hasattr(ticks, "__len__") and len(ticks) > 1:
            props["tick_count"] = len(ticks)
        if rotation is not None:
            props["tick_label_angle"] = float(rotation)
        self._invalidate()

    set_yticks = set_xticks

    def twinx(self) -> "Axes":
        if self._y2_of is not None:
            raise ValueError("twinx() of a twin axes is not supported")
        if self._twin is None:
            self._twin = Axes(self.figure, y2_of=self)
        return self._twin

    def legend(self, *args: Any, **kwargs: Any) -> None:
        host = self._y2_of or self
        host._legend = True  # loc/fontsize accepted; placement is the chart's
        host._invalidate()

    def grid(self, visible: Any = True, **kwargs: Any) -> None:
        host = self._y2_of or self
        host._grid = bool(visible) if visible is not None else not host._grid
        host._invalidate()

    def _axis_props(self, axis: str) -> dict[str, Any]:
        host = self._y2_of or self
        key = "y2" if (axis == "y" and self._y2_of is not None) else axis
        return host._axis[key]

    # -- unsupported (loud) ------------------------------------------------------

    def pie(self, *a: Any, **k: Any) -> None:
        raise not_implemented("pie()", "a bar() chart")

    def boxplot(self, *a: Any, **k: Any) -> None:
        raise not_implemented("boxplot()", "hist() per group")

    def violinplot(self, *a: Any, **k: Any) -> None:
        raise not_implemented("violinplot()", "hist() per group")

    def errorbar(self, *a: Any, **k: Any) -> None:
        raise not_implemented("errorbar()", "plot() plus fill_between() for the band")

    def contour(self, *a: Any, **k: Any) -> None:
        raise not_implemented("contour()", "imshow()")

    contourf = contour

    def quiver(self, *a: Any, **k: Any) -> None:
        raise not_implemented("quiver()")

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
        children = self._chart_children()
        if self._twin is not None:
            children.extend(self._twin._chart_children())
        x_props = {k: v for k, v in self._axis["x"].items() if v is not None}
        y_props = {k: v for k, v in self._axis["y"].items() if v is not None}
        children.append(_cached_axis("x", x_props))
        children.append(_cached_axis("y", y_props))
        if self._twin is not None:
            y2_props = {k: v for k, v in self._axis["y2"].items() if v is not None}
            children.append(fc.y_axis(id="y2", side="right", **y2_props))
        if self._legend:
            children.append(fc.legend())
        if _MPL_THEME_TOKENS:
            children.append(_cached_theme(self._grid))
        self._chart = fc.chart(
            *children,
            title=self._title,
            width=width,
            height=height,
        )
        return self._chart


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating))


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
