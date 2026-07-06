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
from typing import Any, Optional, TypeAlias, Union

import numpy as np

from .figure import Figure

__all__ = [
    "Axis",
    "Chart",
    "Component",
    "Legend",
    "Mark",
    "Modebar",
    "Theme",
    "Tooltip",
    "area",
    "area_chart",
    "bar",
    "bar_chart",
    "chart",
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
    "modebar",
    "scatter",
    "scatter_chart",
    "theme",
    "tooltip",
    "x_axis",
    "y_axis",
]

StyleValue: TypeAlias = str | int | float

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
    class_name: Optional[str] = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Axis(Component):
    which: str  # "x" | "y"
    label: Optional[str] = None
    type_: Optional[str] = None  # "linear" | "time" (auto-detected if None)


@dataclass
class Legend(Component):
    show: bool = True
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Tooltip(Component):
    fields: Optional[list[str]] = None
    title: Optional[str] = None
    format: dict[str, str] = field(default_factory=dict)
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Modebar(Component):
    show: bool = True
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    button_class_name: Optional[str] = None
    button_style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Theme(Component):
    style: dict[str, StyleValue] = field(default_factory=dict)


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
    class_name: Optional[str] = None,
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
        class_name=class_name,
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
    class_name: Optional[str] = None,
) -> Mark:
    """A line series (M4-decimated above the threshold, §5 Tier 1)."""
    return Mark(
        kind="line",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
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
    class_name: Optional[str] = None,
) -> Mark:
    """A filled area series between `y` and `base`."""
    return Mark(
        kind="area",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
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
    class_name: Optional[str] = None,
) -> Mark:
    """A 1D histogram. `values` may be an array or a column name in `data`."""
    return Mark(
        kind="histogram",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
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
    class_name: Optional[str] = None,
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
        class_name=class_name,
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
    class_name: Optional[str] = None,
) -> Mark:
    """A vertical bar series. 2D y values can render grouped or stacked."""
    return Mark(
        kind="bar",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
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
    class_name: Optional[str] = None,
) -> Mark:
    """Alias for vertical column charts; shares the bar renderer."""
    return Mark(
        kind="column",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
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
    class_name: Optional[str] = None,
) -> Mark:
    """A rectangular heatmap from a 2D matrix. `z`, `x`, and `y` may be data keys."""
    return Mark(
        kind="heatmap",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
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


def legend(
    show: bool = True,
    *,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Legend:
    return Legend(
        show=_strict_bool(show, "legend show"),
        class_name=_optional_string(class_name, "legend class_name"),
        style=_style_dict(style, "legend style"),
    )


def tooltip(
    *,
    fields: Optional[list[str]] = None,
    title: Optional[str] = None,
    format: Optional[dict[str, str]] = None,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Tooltip:
    return Tooltip(
        fields=_string_list(fields, "tooltip fields"),
        title=_optional_string(title, "tooltip title"),
        format=_string_dict(format, "tooltip format"),
        class_name=_optional_string(class_name, "tooltip class_name"),
        style=_style_dict(style, "tooltip style"),
    )


def modebar(
    show: bool = True,
    *,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
    button_class_name: Optional[str] = None,
    button_style: Optional[dict[str, StyleValue]] = None,
) -> Modebar:
    return Modebar(
        show=_strict_bool(show, "modebar show"),
        class_name=_optional_string(class_name, "modebar class_name"),
        style=_style_dict(style, "modebar style"),
        button_class_name=_optional_string(button_class_name, "modebar button_class_name"),
        button_style=_style_dict(button_style, "modebar button_style"),
    )


def theme(
    style: Optional[dict[str, StyleValue]] = None,
    **tokens: StyleValue,
) -> Theme:
    merged = _style_dict(style, "theme style")
    if tokens:
        merged.update(_style_dict(tokens, "theme tokens"))
    return Theme(style=merged)


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
        class_name: Optional[str] = None,
        class_names: Optional[dict[str, str]] = None,
        style: Optional[dict[str, StyleValue]] = None,
        on_hover: Optional[Callable[[dict], None]] = None,
        on_select: Optional[Callable[[Any], None]] = None,
        on_view_change: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.kind = kind
        self.children = children
        self.title = title
        self.width = width
        self.height = height
        self.data = data  # chart-level default data for marks that omit their own
        self.class_name = _optional_string(class_name, "chart class_name")
        self.class_names = _string_dict(class_names, "chart class_names")
        self.style = _style_dict(style, "chart style")
        self.on_hover = on_hover
        self.on_select = on_select
        self.on_view_change = on_view_change
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
        tooltips = [c for c in self.children if isinstance(c, Tooltip)]
        modebars = [c for c in self.children if isinstance(c, Modebar)]
        themes = [c for c in self.children if isinstance(c, Theme)]
        legend_shows = [_strict_bool(c.show, "legend show") for c in legends]
        known = (Mark, Axis, Legend, Tooltip, Modebar, Theme)
        unknown = [c for c in self.children if not isinstance(c, known)]
        if unknown:
            raise TypeError(
                f"{self.kind}() children must be marks/axes/legend/tooltip/modebar/theme, got "
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
        fig.class_name = self.class_name
        fig.class_names = dict(self.class_names)
        fig.style = {}
        for theme_node in themes:
            fig.style.update(theme_node.style)
        fig.style.update(self.style)
        for axis in (xa, ya):
            if axis and axis.type_ == "log":
                import warnings

                warnings.warn(
                    "log axes are on the v1 roadmap (§30) but not implemented "
                    "yet; falling back to linear.",
                    RuntimeWarning,
                    stacklevel=2,
                )

        tooltip_aliases: dict[str, str] = {}
        for m in marks:
            data = m.data if m.data is not None else self.data
            applier = _MARK_APPLIERS.get(m.kind)
            if applier is None:
                raise TypeError(f"no applier registered for mark kind {m.kind!r}")
            before = len(fig.traces)
            applier(fig, m, data)
            new_traces = fig.traces[before:]
            if m.class_name is not None:
                class_name = _optional_string(m.class_name, f"{m.kind} class_name")
                for trace in new_traces:
                    trace.style["class_name"] = class_name
            _merge_tooltip_aliases(tooltip_aliases, m, new_traces)

        if legends:
            _apply_chrome_node(fig, "legend", legends[-1].class_name, legends[-1].style)
        if legend_shows and not legend_shows[-1]:
            fig.show_legend = False
        if modebars:
            node = modebars[-1]
            _apply_chrome_node(fig, "modebar", node.class_name, node.style)
            _apply_chrome_node(fig, "modebar_button", node.button_class_name, node.button_style)
            fig.show_modebar = node.show
        if tooltips:
            node = tooltips[-1]
            _apply_chrome_node(fig, "tooltip", node.class_name, node.style)
            fig.tooltip = _tooltip_spec(node, tooltip_aliases)
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

    def html(self, path: Optional[str | PathLike[str]] = None) -> str:
        return self.to_html(path)

    def to_png(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        chromium: Optional[str] = None,
        sandbox: bool = True,
    ) -> bytes:
        return self.figure().to_png(
            path,
            width=width,
            height=height,
            scale=scale,
            chromium=chromium,
            sandbox=sandbox,
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


def _optional_string(value: Any, label: str) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{label} must be a string or None")


def _string_list(value: Any, label: str) -> Optional[list[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list[str] or None")
    return list(value)


def _string_dict(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    return Figure._string_mapping(value, label)


def _style_dict(value: Any, label: str) -> dict[str, StyleValue]:
    if value is None:
        return {}
    return Figure._style_mapping(value, label)


def _append_class(class_names: dict[str, str], slot: str, class_name: Optional[str]) -> None:
    if not class_name:
        return
    existing = class_names.get(slot)
    class_names[slot] = f"{existing} {class_name}" if existing else class_name


def _apply_chrome_node(
    fig: Figure,
    slot: str,
    class_name: Optional[str],
    style: dict[str, StyleValue],
) -> None:
    _append_class(fig.class_names, slot, _optional_string(class_name, f"{slot} class_name"))
    if style:
        fig.chrome_styles[slot] = {**fig.chrome_styles.get(slot, {}), **style}


def _tooltip_spec(node: Tooltip, aliases: dict[str, str]) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    if node.fields:
        spec["fields"] = list(node.fields)
    if node.title is not None:
        spec["title"] = node.title
    if node.format:
        spec["format"] = dict(node.format)
    if aliases:
        spec["aliases"] = dict(aliases)
    return spec


def _merge_tooltip_aliases(aliases: dict[str, str], mark: Mark, traces: list[Any]) -> None:
    if isinstance(mark.x, str):
        aliases.setdefault(mark.x, "x")
    if isinstance(mark.y, str):
        aliases.setdefault(mark.y, "y")
    color = mark.props.get("color")
    if isinstance(color, str) and not _looks_like_css(color):
        channel = next((trace.color_ch for trace in traces if trace.color_ch is not None), None)
        if channel is not None:
            aliases.setdefault(
                color,
                "color_category" if channel.mode == "categorical" else "color_value",
            )
    size = mark.props.get("size")
    if isinstance(size, str):
        channel = next((trace.size_ch for trace in traces if trace.size_ch is not None), None)
        if channel is not None:
            aliases.setdefault(size, "size_value")


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


def chart(*children: Component, **props: Any) -> Chart:
    """A neutral single-panel chart for overlays and mixed mark composition."""
    return Chart("chart", children, **props)


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
