"""A declarative, composition-based component API.

The *feel* is Reflex's (reflex.dev) Recharts components — a chart container with
mark and axis children, snake_case keyword props, `data=` + column-name
resolution, and `on_*` event props — but fastcharts does **not** import or depend
on Reflex. It's the same ergonomics on top of the fastcharts engine (`Figure`):

    import fastcharts as fc

    fc.scatter_chart(
        fc.scatter(x="sepal_w", y="sepal_l", color="species", size="petal_l", data=df),
        fc.x_axis(label="sepal width"),
        fc.y_axis(label="sepal length"),
        fc.legend(),
        title="Iris",
        on_hover=lambda row: print(row),
        on_select=lambda sel: print(len(sel.index), "points"),
    )

Marks accept `x`/`y`/`color`/`size` as arrays *or* as string column names into
`data` (a DataFrame, dict, or anything indexable) — the Reflex/Recharts
`data_key` idiom, read more directly. Everything composes into a `Figure`, so a
chart renders in notebooks and exports to HTML exactly like the fluent API.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Optional, Union

import numpy as np

from .figure import Figure

__all__ = [
    "Axis",
    "Chart",
    "Component",
    "Legend",
    "Mark",
    "area",
    "area_chart",
    "bar",
    "bar_chart",
    "column",
    "column_chart",
    "heatmap",
    "heatmap_chart",
    "hist",
    "histogram",
    "histogram_chart",
    "legend",
    "line",
    "line_chart",
    "scatter",
    "scatter_chart",
    "x_axis",
    "y_axis",
]

# ---------------------------------------------------------------------------
# Component tree (lightweight declarative specs — no rendering here)
# ---------------------------------------------------------------------------


class Component:
    """Base for every fastcharts component (Reflex-style: props + children)."""


@dataclass
class Mark(Component):
    kind: str  # "scatter" | "line" | "area" | "histogram" | "bar" | "column" | "heatmap"
    x: Any = None
    y: Any = None
    data: Any = None
    name: Optional[str] = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Axis(Component):
    which: str  # "x" | "y"
    label: Optional[str] = None
    type_: Optional[str] = None  # "linear" | "time" (auto-detected if None)


@dataclass
class Legend(Component):
    show: bool = True


# ---------------------------------------------------------------------------
# Factory functions (the public, Reflex-flavored surface)
# ---------------------------------------------------------------------------


def scatter(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    color: Union[str, Any, None] = None,
    size: Union[str, float, Any] = 4.0,
    name: Optional[str] = None,
    colormap: str = "viridis",
    size_range: tuple[float, float] = (2.0, 18.0),
    opacity: float = 0.8,
    density: Optional[bool] = None,
) -> Mark:
    """A scatter series. `x`/`y`/`color`/`size` may be arrays or column names in
    `data`. `color` is auto-typed (numeric → colormap, categorical → palette);
    large series auto-aggregate to a Tier-2 density surface (§5)."""
    return Mark(
        kind="scatter",
        x=x,
        y=y,
        data=data,
        name=name,
        props={
            "color": color,
            "size": size,
            "colormap": colormap,
            "size_range": size_range,
            "opacity": opacity,
            "density": density,
        },
    )


def line(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
) -> Mark:
    """A line series (M4-decimated above the threshold, §5 Tier 1)."""
    return Mark(
        kind="line",
        x=x,
        y=y,
        data=data,
        name=name,
        props={"color": color, "width": width, "opacity": opacity},
    )


def area(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    base: Union[str, float, Any] = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.35,
    line_width: float = 1.2,
    line_opacity: float = 1.0,
) -> Mark:
    """A filled area series between `y` and `base`."""
    return Mark(
        kind="area",
        x=x,
        y=y,
        data=data,
        name=name,
        props={
            "base": base,
            "color": color,
            "opacity": opacity,
            "line_width": line_width,
            "line_opacity": line_opacity,
        },
    )


def histogram(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    bins: Any = "auto",
    range: Optional[tuple[float, float]] = None,
    density: bool = False,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.85,
) -> Mark:
    """A 1D histogram. `values` may be an array or a column name in `data`."""
    return Mark(
        kind="histogram",
        x=values,
        data=data,
        name=name,
        props={
            "bins": bins,
            "range": range,
            "density": density,
            "color": color,
            "opacity": opacity,
        },
    )


def hist(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    bins: Any = "auto",
    range: Optional[tuple[float, float]] = None,
    density: bool = False,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.85,
) -> Mark:
    """Short alias for `histogram(...)`."""
    return histogram(
        values,
        data=data,
        bins=bins,
        range=range,
        density=density,
        name=name,
        color=color,
        opacity=opacity,
    )


def bar(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    color: Any = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Union[str, float, Any] = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: float = 0.85,
) -> Mark:
    """A vertical bar series. 2D y values can render grouped or stacked."""
    return Mark(
        kind="bar",
        x=x,
        y=y,
        data=data,
        name=name,
        props={
            "color": color,
            "colors": colors,
            "width": width,
            "base": base,
            "mode": mode,
            "orientation": orientation,
            "series": series,
            "opacity": opacity,
        },
    )


def column(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    color: Any = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Union[str, float, Any] = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: float = 0.85,
) -> Mark:
    """Alias for vertical column charts; shares the bar renderer."""
    return Mark(
        kind="column",
        x=x,
        y=y,
        data=data,
        name=name,
        props={
            "color": color,
            "colors": colors,
            "width": width,
            "base": base,
            "mode": mode,
            "orientation": orientation,
            "series": series,
            "opacity": opacity,
        },
    )


def heatmap(
    z: Union[str, Any] = None,
    *,
    x: Union[str, Any, None] = None,
    y: Union[str, Any, None] = None,
    data: Any = None,
    name: Optional[str] = None,
    colormap: str = "viridis",
    domain: Optional[tuple[float, float]] = None,
    opacity: float = 0.95,
) -> Mark:
    """A rectangular heatmap from a 2D matrix. `z`, `x`, and `y` may be data keys."""
    return Mark(
        kind="heatmap",
        x=x,
        y=y,
        data=data,
        name=name,
        props={
            "z": z,
            "colormap": colormap,
            "domain": domain,
            "opacity": opacity,
        },
    )


def x_axis(*, label: Optional[str] = None, type_: Optional[str] = None) -> Axis:
    _validate_axis_type(type_)
    return Axis(which="x", label=label, type_=type_)


def y_axis(*, label: Optional[str] = None, type_: Optional[str] = None) -> Axis:
    _validate_axis_type(type_)
    return Axis(which="y", label=label, type_=type_)


def legend(show: bool = True) -> Legend:
    return Legend(show=_strict_bool(show, "legend show"))


# ---------------------------------------------------------------------------
# Chart container
# ---------------------------------------------------------------------------


def _resolve(data: Any, key: Any, *, context: Optional[str] = None) -> Any:
    """Reflex `data_key` idiom: a string names a column in `data`; anything else
    is passed through as the values themselves."""
    if isinstance(key, str):
        prefix = f"{context} " if context else ""
        if data is None:
            raise ValueError(
                f"{prefix}column name {key!r} given but no data= provided; pass data=df "
                "or give x/y/color/size as arrays"
            )
        try:
            return data[key]
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(f"{prefix}column {key!r} not found in data") from e
    return key


class Chart(Component):
    """Composes marks + axis/legend children into a `Figure`. Renders in
    notebooks and exports to HTML via the underlying engine."""

    def __init__(
        self,
        kind: str,
        children: tuple[Component, ...],
        *,
        title: Optional[str] = None,
        width: "int | str" = 900,  # pixels, or "100%" to fill the parent
        height: "int | str" = 420,  # pixels, or "100%" (parent needs a height)
        data: Any = None,
        on_hover: Optional[Callable[[dict], None]] = None,
        on_select: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self.kind = kind
        self.children = children
        self.title = title
        self.width = width
        self.height = height
        self.data = data  # chart-level default data for marks that omit their own
        self.on_hover = on_hover
        self.on_select = on_select
        self._figure: Optional[Figure] = None
        self._widget: Any = None

    # -- build ---------------------------------------------------------------

    def figure(self) -> Figure:
        """The composed `Figure` (built once, cached)."""
        if self._figure is not None:
            return self._figure

        marks = [c for c in self.children if isinstance(c, Mark)]
        axis_children = [c for c in self.children if isinstance(c, Axis)]
        for axis in axis_children:
            _validate_axis(axis)
        axes = {c.which: c for c in axis_children}
        legends = [c for c in self.children if isinstance(c, Legend)]
        legend_shows = [_strict_bool(c.show, "legend show") for c in legends]
        unknown = [c for c in self.children if not isinstance(c, (Mark, Axis, Legend))]
        if unknown:
            raise TypeError(
                f"{self.kind}() children must be marks/axes/legend, got "
                f"{[type(c).__name__ for c in unknown]}"
            )

        xa, ya = axes.get("x"), axes.get("y")
        fig = Figure(
            width=self.width,
            height=self.height,
            title=self.title,
            x_label=xa.label if xa else None,
            y_label=ya.label if ya else None,
        )
        for axis in (xa, ya):
            if axis and axis.type_ == "log":
                import warnings

                warnings.warn(
                    "log axes are on the v1 roadmap (§30) but not implemented "
                    "yet; falling back to linear.",
                    RuntimeWarning,
                    stacklevel=2,
                )

        for m in marks:
            data = m.data if m.data is not None else self.data
            applier = _MARK_APPLIERS.get(m.kind)
            if applier is None:
                raise TypeError(f"no applier registered for mark kind {m.kind!r}")
            applier(fig, m, data)

        if legend_shows and not legend_shows[-1]:
            fig.show_legend = False
        self._figure = fig
        return fig

    # -- render (delegates to the engine) ------------------------------------

    def widget(self) -> Any:
        if self._widget is None:
            from .widget import FigureWidget

            self._widget = FigureWidget(
                self.figure(), on_hover=self.on_hover, on_select=self.on_select
            )
        return self._widget

    def show(self) -> Any:
        return self.widget()

    def _ipython_display_(self) -> None:
        from IPython.display import display  # type: ignore[import-not-found]

        display(self.widget())

    def to_html(self, path: Optional[str | PathLike[str]] = None) -> str:
        return self.figure().to_html(path)

    def to_png(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        chromium: Optional[str] = None,
    ) -> bytes:
        return self.figure().to_png(
            path,
            width=width,
            height=height,
            scale=scale,
            chromium=chromium,
        )

    def memory_report(self) -> dict[str, Any]:
        return self.figure().memory_report()


def _resolve_color(data: Any, color: Any, *, context: Optional[str] = None) -> Any:
    """Disambiguate a string `color`: a CSS color is a constant; any other
    string is a column name resolved from `data` (Reflex data_key idiom)."""
    if not isinstance(color, str):
        return color  # None, or an already-materialized array
    if _looks_like_css(color):
        return color  # constant color
    return _resolve(data, color, context=context)  # column name → values (raises if no data)


def _strict_bool(value: Any, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise ValueError(f"{label} must be True or False")


def _validate_axis(axis: Axis) -> None:
    if axis.which not in {"x", "y"}:
        raise ValueError(f"axis.which must be 'x' or 'y', got {axis.which!r}")
    _validate_axis_type(axis.type_)


def _validate_axis_type(type_: Optional[str]) -> None:
    if type_ is None or type_ in {"linear", "time", "log"}:
        return
    raise ValueError(f"axis type_ must be one of None, 'linear', 'time', or 'log', got {type_!r}")


def _looks_like_css(s: str) -> bool:
    """Heuristic: a bare color string vs a column name. Hex, rgb(), and common
    named colors are treated as constant colors; everything else is a column."""
    if s.startswith("#") or s.startswith("rgb") or s.startswith("hsl") or s.startswith("oklch"):
        return True
    return s.lower() in _CSS_NAMES


_CSS_NAMES = {
    "black",
    "white",
    "red",
    "green",
    "blue",
    "yellow",
    "orange",
    "purple",
    "gray",
    "grey",
    "cyan",
    "magenta",
    "pink",
    "brown",
    "teal",
    "navy",
    "gold",
    "silver",
    "maroon",
    "olive",
    "lime",
    "aqua",
    "fuchsia",
    "transparent",
}


# ---------------------------------------------------------------------------
# Mark appliers — one per mark kind, mapping a declarative Mark onto a Figure
# call with its (data-resolved) props. Register a new chart type here; the
# Chart container dispatches through this table, so figure() never grows a
# per-kind branch.
# ---------------------------------------------------------------------------


def _apply_scatter(fig: Figure, m: Mark, data: Any) -> None:
    size = m.props["size"]
    fig.scatter(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.y, context=f"{m.kind}.y"),
        name=m.name,
        color=_resolve_color(data, m.props["color"], context=f"{m.kind}.color"),
        size=_resolve(data, size, context=f"{m.kind}.size") if isinstance(size, str) else size,
        colormap=m.props["colormap"],
        size_range=m.props["size_range"],
        opacity=m.props["opacity"],
        density=m.props["density"],
    )


def _apply_line(fig: Figure, m: Mark, data: Any) -> None:
    fig.line(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.y, context=f"{m.kind}.y"),
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
    )


def _apply_area(fig: Figure, m: Mark, data: Any) -> None:
    base = m.props["base"]
    fig.area(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.y, context=f"{m.kind}.y"),
        base=_resolve(data, base, context=f"{m.kind}.base") if isinstance(base, str) else base,
        name=m.name,
        color=m.props["color"],
        opacity=m.props["opacity"],
        line_width=m.props["line_width"],
        line_opacity=m.props["line_opacity"],
    )


def _apply_histogram(fig: Figure, m: Mark, data: Any) -> None:
    fig.histogram(
        _resolve(data, m.x, context=f"{m.kind}.values"),
        bins=m.props["bins"],
        range=m.props["range"],
        density=m.props["density"],
        name=m.name,
        color=m.props["color"],
        opacity=m.props["opacity"],
    )


def _apply_heatmap(fig: Figure, m: Mark, data: Any) -> None:
    fig.heatmap(
        _resolve(data, m.props["z"], context=f"{m.kind}.z"),
        x=_resolve(data, m.x, context=f"{m.kind}.x") if m.x is not None else None,
        y=_resolve(data, m.y, context=f"{m.kind}.y") if m.y is not None else None,
        name=m.name,
        colormap=m.props["colormap"],
        domain=m.props["domain"],
        opacity=m.props["opacity"],
    )


def _apply_bar(fig: Figure, m: Mark, data: Any) -> None:
    base = m.props["base"]
    fig.bar(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.y, context=f"{m.kind}.y"),
        name=m.name,
        color=m.props["color"],
        colors=m.props["colors"],
        width=m.props["width"],
        base=_resolve(data, base, context=f"{m.kind}.base") if isinstance(base, str) else base,
        mode=m.props["mode"],
        orientation=m.props["orientation"],
        series=m.props["series"],
        opacity=m.props["opacity"],
    )


def _apply_column(fig: Figure, m: Mark, data: Any) -> None:
    base = m.props["base"]
    fig.column(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.y, context=f"{m.kind}.y"),
        name=m.name,
        color=m.props["color"],
        colors=m.props["colors"],
        width=m.props["width"],
        base=_resolve(data, base, context=f"{m.kind}.base") if isinstance(base, str) else base,
        mode=m.props["mode"],
        orientation=m.props["orientation"],
        series=m.props["series"],
        opacity=m.props["opacity"],
    )


_MARK_APPLIERS: dict[str, Callable[[Figure, Mark, Any], None]] = {
    "area": _apply_area,
    "bar": _apply_bar,
    "column": _apply_column,
    "heatmap": _apply_heatmap,
    "histogram": _apply_histogram,
    "scatter": _apply_scatter,
    "line": _apply_line,
}


def scatter_chart(*children: Component, **props: Any) -> Chart:
    """A scatter chart composing `scatter` marks and axis/legend children."""
    return Chart("scatter_chart", children, **props)


def line_chart(*children: Component, **props: Any) -> Chart:
    """A line chart composing `line` marks and axis/legend children."""
    return Chart("line_chart", children, **props)


def area_chart(*children: Component, **props: Any) -> Chart:
    """An area chart composing `area` marks and axis/legend children."""
    return Chart("area_chart", children, **props)


def histogram_chart(*children: Component, **props: Any) -> Chart:
    """A histogram chart composing `histogram` marks and axis/legend children."""
    return Chart("histogram_chart", children, **props)


def bar_chart(*children: Component, **props: Any) -> Chart:
    """A bar chart composing `bar` marks and axis/legend children."""
    return Chart("bar_chart", children, **props)


def column_chart(*children: Component, **props: Any) -> Chart:
    """A column chart composing `column` marks and axis/legend children."""
    return Chart("column_chart", children, **props)


def heatmap_chart(*children: Component, **props: Any) -> Chart:
    """A heatmap chart composing `heatmap` marks and axis/legend children."""
    return Chart("heatmap_chart", children, **props)
