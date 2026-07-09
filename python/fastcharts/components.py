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

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Optional, TypeAlias, Union

import numpy as np

from . import _validate
from .dom import CHART_DOM_SLOTS, validate_dom_slots
from .figure import Figure

# Shared validators (single source of truth in `_validate`); these aliases keep
# the module-private names their call sites already use.
_optional_string = _validate.optional_text
_finite_number = _validate.finite_scalar
_axis_id = _validate.axis_id
_optional_positive_int = _validate.optional_positive_int
_axis_tick_label_strategy = _validate.axis_tick_label_strategy
_axis_label_position = _validate.axis_label_position
_optional_finite_number = _validate.optional_finite_scalar
_optional_nonnegative_number = _validate.optional_nonnegative_scalar

__all__ = [
    "CHART_DOM_SLOTS",
    "Annotation",
    "Axis",
    "Chart",
    "Component",
    "Interaction",
    "Legend",
    "Mark",
    "MarkStyle",
    "Modebar",
    "Theme",
    "Tooltip",
    "area",
    "area_chart",
    "arrow",
    "bar",
    "bar_chart",
    "callout",
    "candlestick",
    "candlestick_chart",
    "chart",
    "column",
    "column_chart",
    "heatmap",
    "heatmap_chart",
    "hist",
    "histogram",
    "histogram_chart",
    "hline",
    "interaction_config",
    "label",
    "legend",
    "line",
    "line_chart",
    "mark_style",
    "marker",
    "modebar",
    "ohlc",
    "ohlc_chart",
    "scatter",
    "scatter_chart",
    "text",
    "theme",
    "threshold",
    "threshold_zone",
    "tooltip",
    "vline",
    "x_axis",
    "x_band",
    "y_axis",
    "y_band",
]

StyleValue: TypeAlias = str | int | float
AxisLabelPosition: TypeAlias = str | dict[str, StyleValue]
AxisTickLabelStrategy: TypeAlias = str

# ---------------------------------------------------------------------------
# Component tree (lightweight declarative specs — no rendering here)
# ---------------------------------------------------------------------------


class Component:
    """Base for every fastcharts component (Reflex-style: props + children)."""


@dataclass
class Mark(Component):
    kind: str  # "scatter" | "line" | "area" | "histogram" | "bar" | "column" | "heatmap" | "candlestick" | "ohlc"
    x: Any = None
    y: Any = None
    data: Any = None
    name: Optional[str] = None
    id: Optional[str] = None  # explicit trace id (finance layers reference it)
    class_name: Optional[str] = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Annotation(Component):
    kind: str  # "rule" | "band" | "text"
    axis: Optional[str] = None
    x: Any = None
    y: Any = None
    text: Optional[str] = None
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Axis(Component):
    which: str  # "x" | "y"
    id: Optional[str] = None
    label: Optional[str] = None
    label_position: Optional[AxisLabelPosition] = None
    label_offset: Optional[float] = None
    label_angle: Optional[float] = None
    type_: Optional[str] = None  # "linear" | "time" | "log" (auto-detected if None)
    domain: Optional[tuple[float, float]] = None
    reverse: bool = False
    format: Optional[str] = None
    tick_count: Optional[int] = None
    tick_label_angle: Optional[float] = None
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None
    tick_label_min_gap: Optional[float] = None
    side: Optional[str] = None
    scale: Optional[str] = None  # finance-style alias for type_
    style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Legend(Component):
    show: bool = True
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    render: Any = None


@dataclass
class Tooltip(Component):
    show: bool = True
    fields: Optional[list[str]] = None
    title: Optional[str] = None
    format: dict[str, str] = field(default_factory=dict)
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    render: Any = None


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


@dataclass
class MarkStyle(Component):
    hover: dict[str, StyleValue] = field(default_factory=dict)
    selected: dict[str, StyleValue] = field(default_factory=dict)
    unselected: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Interaction(Component):
    hover: Optional[bool] = None
    click: Optional[bool] = None
    select: Optional[bool] = None
    brush: Optional[bool] = None
    crosshair: Optional[bool] = None
    view_change: Optional[bool] = None
    link_group: Optional[str] = None
    link_axes: tuple[str, ...] = ("x", "y")


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
    symbol: str = "circle",
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A scatter series. `x`/`y`/`color`/`size` may be arrays or column names in
    `data`. `color` is auto-typed (numeric → colormap, categorical → palette);
    `symbol`/`stroke`/`stroke_width` style the markers; large series
    auto-aggregate to a Tier-2 density surface (§5)."""
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
            "symbol": symbol,
            "stroke": stroke,
            "stroke_width": stroke_width,
            "x_axis": x_axis,
            "y_axis": y_axis,
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
    curve: str = "linear",
    dash: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A line series (M4-decimated above the threshold, §5 Tier 1).
    `curve="smooth"` renders a monotone cubic; `dash` dashes the line."""
    return Mark(
        kind="line",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "color": color,
            "width": width,
            "opacity": opacity,
            "curve": curve,
            "dash": dash,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
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
    fill: Any = None,
    curve: str = "linear",
    dash: Any = None,
    fill_color: Optional[str] = None,
    width: Optional[float] = None,
    fill_opacity: Optional[float] = None,
    baseline: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A filled area series between `y` and `base`. `fill` accepts a CSS
    `linear-gradient(...)`; `curve="smooth"` renders a monotone cubic; `dash`
    dashes the outline."""
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
            "fill": fill,
            "curve": curve,
            "dash": dash,
            "fill_color": fill_color,
            "width": width,
            "fill_opacity": fill_opacity,
            "baseline": baseline,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def candlestick(
    x: Union[str, Any] = None,
    open: Union[str, Any] = None,  # noqa: A002 - OHLC domain naming
    high: Union[str, Any] = None,
    low: Union[str, Any] = None,
    close: Union[str, Any] = None,
    *,
    volume: Union[str, Any, None] = None,
    data: Any = None,
    name: Optional[str] = None,
    id: Optional[str] = None,
    up_color: str = "#26a69a",
    down_color: str = "#ef5350",
    width_frac: float = 0.7,
    opacity: float = 1.0,
    hollow: bool = False,
    wick_color: Optional[str] = None,
) -> Mark:
    """An OHLC candlestick series."""
    return Mark(
        kind="candlestick",
        x=x,
        y=close,
        data=data,
        name=name,
        id=id,
        props={
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "up_color": up_color,
            "down_color": down_color,
            "width_frac": width_frac,
            "opacity": opacity,
            "hollow": hollow,
            "wick_color": wick_color,
        },
    )


def ohlc(
    x: Union[str, Any] = None,
    open: Union[str, Any] = None,  # noqa: A002
    high: Union[str, Any] = None,
    low: Union[str, Any] = None,
    close: Union[str, Any] = None,
    *,
    volume: Union[str, Any, None] = None,
    data: Any = None,
    name: Optional[str] = None,
    id: Optional[str] = None,
    up_color: str = "#26a69a",
    down_color: str = "#ef5350",
    width_frac: float = 0.7,
    opacity: float = 1.0,
) -> Mark:
    """An OHLC bar series."""
    return Mark(
        kind="ohlc",
        x=x,
        y=close,
        data=data,
        name=name,
        id=id,
        props={
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "up_color": up_color,
            "down_color": down_color,
            "width_frac": width_frac,
            "opacity": opacity,
        },
    )


def histogram(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    bins: Any = "auto",
    range: Optional[tuple[float, float]] = None,
    density: bool = False,
    cumulative: bool = False,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.85,
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
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
            "cumulative": cumulative,
            "color": color,
            "opacity": opacity,
            "corner_radius": corner_radius,
            "stroke": stroke,
            "stroke_width": stroke_width,
            "fill": fill,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def hist(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    bins: Any = "auto",
    range: Optional[tuple[float, float]] = None,
    density: bool = False,
    cumulative: bool = False,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.85,
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Short alias for `histogram(...)`."""
    return histogram(
        values,
        data=data,
        bins=bins,
        range=range,
        density=density,
        cumulative=cumulative,
        name=name,
        color=color,
        opacity=opacity,
        corner_radius=corner_radius,
        stroke=stroke,
        stroke_width=stroke_width,
        fill=fill,
        class_name=class_name,
        x_axis=x_axis,
        y_axis=y_axis,
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
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A vertical bar series. 2D y values can render grouped, stacked, or
    normalized (per-category fractions summing to 1)."""
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
            "corner_radius": corner_radius,
            "stroke": stroke,
            "stroke_width": stroke_width,
            "fill": fill,
            "x_axis": x_axis,
            "y_axis": y_axis,
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
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
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
            "corner_radius": corner_radius,
            "stroke": stroke,
            "stroke_width": stroke_width,
            "fill": fill,
            "x_axis": x_axis,
            "y_axis": y_axis,
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
    x_axis: str = "x",
    y_axis: str = "y",
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
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def vline(
    x: Any,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#667085",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A vertical rule annotation at an x coordinate or x-axis category."""
    return Annotation(
        kind="rule",
        axis="x",
        x=x,
        text=_optional_string(text, "vline text"),
        class_name=_optional_string(class_name, "vline class_name"),
        style=_style_dict(style, "vline style"),
        props={"color": color, "width": width, "opacity": opacity},
    )


def hline(
    y: Any,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#667085",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A horizontal rule annotation at a y coordinate or y-axis category."""
    return Annotation(
        kind="rule",
        axis="y",
        y=y,
        text=_optional_string(text, "hline text"),
        class_name=_optional_string(class_name, "hline class_name"),
        style=_style_dict(style, "hline style"),
        props={"color": color, "width": width, "opacity": opacity},
    )


def x_band(
    x0: Any,
    x1: Any,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#64748b",
    opacity: float = 0.14,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A vertical span annotation between two x coordinates or categories."""
    return Annotation(
        kind="band",
        axis="x",
        x=x0,
        y=x1,
        text=_optional_string(text, "x_band text"),
        class_name=_optional_string(class_name, "x_band class_name"),
        style=_style_dict(style, "x_band style"),
        props={"color": color, "opacity": opacity},
    )


def y_band(
    y0: Any,
    y1: Any,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#64748b",
    opacity: float = 0.14,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A horizontal span annotation between two y coordinates or categories."""
    return Annotation(
        kind="band",
        axis="y",
        x=y0,
        y=y1,
        text=_optional_string(text, "y_band text"),
        class_name=_optional_string(class_name, "y_band class_name"),
        style=_style_dict(style, "y_band style"),
        props={"color": color, "opacity": opacity},
    )


def text(
    x: Any,
    y: Any,
    value: str,
    *,
    dx: float = 6.0,
    dy: float = -6.0,
    color: Optional[str] = None,
    anchor: str = "start",
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A text annotation anchored at an x/y coordinate or category."""
    if not isinstance(value, str):
        raise ValueError("text value must be a string")
    return Annotation(
        kind="text",
        x=x,
        y=y,
        text=value,
        class_name=_optional_string(class_name, "text class_name"),
        style=_style_dict(style, "text style"),
        props={"dx": dx, "dy": dy, "color": color, "anchor": anchor},
    )


def label(
    x: Any,
    y: Any,
    value: str,
    *,
    dx: float = 6.0,
    dy: float = -6.0,
    color: Optional[str] = None,
    anchor: str = "start",
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """Alias for a positioned text annotation."""
    return text(
        x,
        y,
        value,
        dx=dx,
        dy=dy,
        color=color,
        anchor=anchor,
        class_name=class_name,
        style=style,
    )


def marker(
    x: Any,
    y: Any,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#2563eb",
    size: float = 8.0,
    symbol: str = "circle",
    stroke_color: Optional[str] = "#ffffff",
    stroke_width: float = 1.5,
    opacity: float = 1.0,
    dx: float = 8.0,
    dy: float = -8.0,
    anchor: str = "start",
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A point marker annotation with an optional label."""
    return Annotation(
        kind="marker",
        x=x,
        y=y,
        text=_optional_string(text, "marker text"),
        class_name=_optional_string(class_name, "marker class_name"),
        style=_style_dict(style, "marker style"),
        props={
            "color": color,
            "size": size,
            "symbol": symbol,
            "stroke_color": stroke_color,
            "stroke_width": stroke_width,
            "opacity": opacity,
            "dx": dx,
            "dy": dy,
            "anchor": anchor,
        },
    )


def arrow(
    x0: Any,
    y0: Any,
    x1: Any,
    y1: Any,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#667085",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """An arrow annotation from one data coordinate to another."""
    return Annotation(
        kind="arrow",
        x=x0,
        y=y0,
        text=_optional_string(text, "arrow text"),
        class_name=_optional_string(class_name, "arrow class_name"),
        style=_style_dict(style, "arrow style"),
        props={"x1": x1, "y1": y1, "color": color, "width": width, "opacity": opacity},
    )


def threshold(
    value: Any,
    *,
    axis: str = "y",
    text: Optional[str] = None,
    color: Optional[str] = "#e11d48",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A semantic threshold rule on the x or y axis."""
    axis = _annotation_axis_name(axis, "threshold axis")
    return (
        vline(
            value,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )
        if axis == "x"
        else hline(
            value,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )
    )


def threshold_zone(
    start: Any,
    end: Any,
    *,
    axis: str = "y",
    text: Optional[str] = None,
    color: Optional[str] = "#e11d48",
    opacity: float = 0.12,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A semantic threshold band on the x or y axis."""
    axis = _annotation_axis_name(axis, "threshold_zone axis")
    return (
        x_band(
            start,
            end,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )
        if axis == "x"
        else y_band(
            start,
            end,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )
    )


def callout(
    x: Any,
    y: Any,
    value: str,
    *,
    dx: float = 36.0,
    dy: float = -30.0,
    color: Optional[str] = "#344054",
    width: float = 1.5,
    opacity: float = 1.0,
    anchor: str = "start",
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A text callout offset from a data coordinate with a pointer arrow."""
    if not isinstance(value, str):
        raise ValueError("callout value must be a string")
    return Annotation(
        kind="callout",
        x=x,
        y=y,
        text=value,
        class_name=_optional_string(class_name, "callout class_name"),
        style=_style_dict(style, "callout style"),
        props={
            "dx": dx,
            "dy": dy,
            "color": color,
            "width": width,
            "opacity": opacity,
            "anchor": anchor,
        },
    )


def x_axis(
    *,
    id: str = "x",
    label: Optional[str] = None,
    label_position: Optional[AxisLabelPosition] = None,
    label_offset: Optional[float] = None,
    label_angle: Optional[float] = None,
    type_: Optional[str] = None,
    domain: Optional[tuple[float, float]] = None,
    reverse: bool = False,
    format: Optional[str] = None,
    tick_count: Optional[int] = None,
    tick_label_angle: Optional[float] = None,
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None,
    tick_label_min_gap: Optional[float] = None,
    side: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Axis:
    _validate_axis_type(type_)
    return Axis(
        which="x",
        id=_axis_id(id, "x_axis id"),
        label=label,
        label_position=_axis_label_position(label_position, "x_axis label_position"),
        label_offset=_optional_finite_number(label_offset, "x_axis label_offset"),
        label_angle=_optional_finite_number(label_angle, "x_axis label_angle"),
        type_=type_,
        domain=_axis_domain(domain, "x_axis domain"),
        reverse=_strict_bool(reverse, "x_axis reverse"),
        format=_optional_string(format, "x_axis format"),
        tick_count=_optional_positive_int(tick_count, "x_axis tick_count"),
        tick_label_angle=_optional_finite_number(tick_label_angle, "x_axis tick_label_angle"),
        tick_label_strategy=_axis_tick_label_strategy(
            tick_label_strategy, "x_axis tick_label_strategy"
        ),
        tick_label_min_gap=_optional_nonnegative_number(
            tick_label_min_gap, "x_axis tick_label_min_gap"
        ),
        side=_axis_side(side, "x"),
        style=_style_dict(style, "x_axis style"),
    )


def y_axis(
    *,
    id: str = "y",
    label: Optional[str] = None,
    label_position: Optional[AxisLabelPosition] = None,
    label_offset: Optional[float] = None,
    label_angle: Optional[float] = None,
    type_: Optional[str] = None,
    domain: Optional[tuple[float, float]] = None,
    reverse: bool = False,
    format: Optional[str] = None,
    tick_count: Optional[int] = None,
    tick_label_angle: Optional[float] = None,
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None,
    tick_label_min_gap: Optional[float] = None,
    side: Optional[str] = None,
    scale: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Axis:
    if type_ is not None and scale is not None and type_ != scale:
        raise ValueError("y_axis type_ and scale must match when both are provided")
    type_ = type_ or scale
    _validate_axis_type(type_)
    return Axis(
        which="y",
        id=_axis_id(id, "y_axis id"),
        label=label,
        label_position=_axis_label_position(label_position, "y_axis label_position"),
        label_offset=_optional_finite_number(label_offset, "y_axis label_offset"),
        label_angle=_optional_finite_number(label_angle, "y_axis label_angle"),
        type_=type_,
        domain=_axis_domain(domain, "y_axis domain"),
        reverse=_strict_bool(reverse, "y_axis reverse"),
        format=_optional_string(format, "y_axis format"),
        tick_count=_optional_positive_int(tick_count, "y_axis tick_count"),
        tick_label_angle=_optional_finite_number(tick_label_angle, "y_axis tick_label_angle"),
        tick_label_strategy=_axis_tick_label_strategy(
            tick_label_strategy, "y_axis tick_label_strategy"
        ),
        tick_label_min_gap=_optional_nonnegative_number(
            tick_label_min_gap, "y_axis tick_label_min_gap"
        ),
        side=_axis_side(side, "y"),
        scale=scale,
        style=_style_dict(style, "y_axis style"),
    )


def legend(
    *children: Any,
    show: bool = True,
    render: Any = None,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Legend:
    show, render = _chrome_render_args(children, show, render, "legend")
    return Legend(
        show=_strict_bool(show, "legend show"),
        class_name=_optional_string(class_name, "legend class_name"),
        style=_style_dict(style, "legend style"),
        render=render,
    )


def tooltip(
    *children: Any,
    show: bool = True,
    render: Any = None,
    fields: Optional[list[str]] = None,
    title: Optional[str] = None,
    format: Optional[dict[str, str]] = None,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Tooltip:
    show, render = _chrome_render_args(children, show, render, "tooltip")
    return Tooltip(
        show=_strict_bool(show, "tooltip show"),
        fields=_string_list(fields, "tooltip fields"),
        title=_optional_string(title, "tooltip title"),
        format=_string_dict(format, "tooltip format"),
        class_name=_optional_string(class_name, "tooltip class_name"),
        style=_style_dict(style, "tooltip style"),
        render=render,
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
    *,
    plot_background: Optional[StyleValue] = None,
    grid_color: Optional[StyleValue] = None,
    axis_color: Optional[StyleValue] = None,
    text_color: Optional[StyleValue] = None,
    crosshair_color: Optional[StyleValue] = None,
    selection_color: Optional[StyleValue] = None,
    selection_fill: Optional[StyleValue] = None,
    **tokens: StyleValue,
) -> Theme:
    merged = _style_dict(style, "theme style")
    merged.update(
        _theme_tokens(
            {
                "plot_background": plot_background,
                "grid_color": grid_color,
                "axis_color": axis_color,
                "text_color": text_color,
                "crosshair_color": crosshair_color,
                "selection_color": selection_color,
                "selection_fill": selection_fill,
            },
            "theme",
        )
    )
    if tokens:
        merged.update(_theme_tokens(tokens, "theme tokens"))
    return Theme(style=merged)


def mark_style(
    *,
    hover: Optional[dict[str, StyleValue]] = None,
    selected: Optional[dict[str, StyleValue]] = None,
    unselected: Optional[dict[str, StyleValue]] = None,
) -> MarkStyle:
    """Style mark interaction states declaratively.

    The first renderer-backed fields are scatter hover highlights and
    selected/unselected opacity. The component shape is shared by future mark
    kinds so charts do not need an API migration when bars/lines gain richer
    state styling.
    """
    return MarkStyle(
        hover=_style_dict(hover, "mark_style hover"),
        selected=_style_dict(selected, "mark_style selected"),
        unselected=_style_dict(unselected, "mark_style unselected"),
    )


def interaction_config(
    *,
    hover: Optional[bool] = None,
    click: Optional[bool] = None,
    select: Optional[bool] = None,
    brush: Optional[bool] = None,
    crosshair: Optional[bool] = None,
    view_change: Optional[bool] = None,
    link_group: Optional[str] = None,
    link_axes: tuple[str, ...] = ("x", "y"),
) -> Interaction:
    """Configure browser interaction chrome and event emission.

    `crosshair=True` draws plot-aligned hover guides. `click=True` emits click
    events and widget callbacks for picked marks. `select`/`brush` control
    shift-drag box selection. `link_group` synchronizes view ranges across
    charts in the same browser page or same-origin iframes. `view_change=True`
    emits pan/zoom/reset ranges without requiring a Python callback.
    """
    return Interaction(
        hover=hover,
        click=click,
        select=select,
        brush=brush,
        crosshair=crosshair,
        view_change=view_change,
        link_group=link_group,
        link_axes=link_axes,
    )


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


def _resolve_axis_values(fig: Figure, data: Any, key: Any, axis: str, context: str) -> Any:
    values = _resolve(data, key, context=context)
    if values is not None and Figure._is_category_like(values) and not _is_datetime_like(values):
        return fig._axis_positions(values, axis)
    return values


def _is_datetime_like(values: Any) -> bool:
    if hasattr(values, "to_numpy"):
        values = values.to_numpy()
    arr = np.asarray(values)
    if np.issubdtype(arr.dtype, np.datetime64):
        return True
    if arr.dtype != object:
        return False
    for value in arr.flat:
        if value is None:
            continue
        if value.__class__.__name__ in {"NAType", "NaTType"}:
            continue
        return isinstance(value, (dt.datetime, dt.date, np.datetime64))
    return False


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
        padding: Any = None,  # override plot margins; 0 = edge-to-edge sparkline
        data: Any = None,
        class_name: Optional[str] = None,
        class_names: Optional[dict[str, str]] = None,
        style: Optional[dict[str, StyleValue]] = None,
        on_hover: Optional[Callable[[dict], None]] = None,
        on_click: Optional[Callable[[dict], None]] = None,
        on_brush: Optional[Callable[[dict], None]] = None,
        on_select: Optional[Callable[[Any], None]] = None,
        on_view_change: Optional[Callable[[dict], None]] = None,
        hover: Optional[bool] = None,
        click: Optional[bool] = None,
        select: Optional[bool] = None,
        brush: Optional[bool] = None,
        crosshair: Optional[bool] = None,
        view_change: Optional[bool] = None,
        link_group: Optional[str] = None,
        link_axes: tuple[str, ...] = ("x", "y"),
    ) -> None:
        self.kind = kind
        self.children = children
        self.title = title
        self.width = width
        self.height = height
        self.padding = padding
        self.data = data  # chart-level default data for marks that omit their own
        self.class_name = _optional_string(class_name, "chart class_name")
        self.class_names = _class_names_dict(class_names, "chart class_names")
        self.style = _style_dict(style, "chart style")
        self.on_hover = on_hover
        self.on_click = on_click
        self.on_brush = on_brush
        self.on_select = on_select
        self.on_view_change = on_view_change
        self.hover = hover
        self.click = click
        self.select = select
        self.brush = brush
        self.crosshair = crosshair
        self.view_change = view_change
        self.link_group = link_group
        self.link_axes = link_axes
        self._figure: Optional[Figure] = None
        self._widget: Any = None

    # -- build ---------------------------------------------------------------

    def figure(self) -> Figure:
        """The composed `Figure` (built once, cached)."""
        if self._figure is not None:
            return self._figure

        marks = [c for c in self.children if isinstance(c, Mark)]
        annotations = [c for c in self.children if isinstance(c, Annotation)]
        axis_children = [c for c in self.children if isinstance(c, Axis)]
        for axis in axis_children:
            _validate_axis(axis)
        axes = {c.id or c.which: c for c in axis_children}
        legends = [c for c in self.children if isinstance(c, Legend)]
        tooltips = [c for c in self.children if isinstance(c, Tooltip)]
        modebars = [c for c in self.children if isinstance(c, Modebar)]
        themes = [c for c in self.children if isinstance(c, Theme)]
        mark_styles = [c for c in self.children if isinstance(c, MarkStyle)]
        interactions = [c for c in self.children if isinstance(c, Interaction)]
        legend_shows = [_strict_bool(c.show, "legend show") for c in legends]
        known = (
            Mark,
            Annotation,
            Axis,
            Legend,
            Tooltip,
            Modebar,
            Theme,
            MarkStyle,
            Interaction,
        )
        unknown = [c for c in self.children if not isinstance(c, known)]
        if unknown:
            raise TypeError(
                f"{self.kind}() children must be marks/annotations/axes/legend/tooltip/"
                f"modebar/theme/mark_style/interaction_config, got "
                f"{[type(c).__name__ for c in unknown]}"
            )

        xa, ya = axes.get("x"), axes.get("y")
        fig = Figure(
            width=self.width,
            height=self.height,
            padding=self.padding,
            title=self.title,
            x_label=xa.label if xa else None,
            y_label=ya.label if ya else None,
            y_side=ya.side if ya and ya.side else "left",
        )
        for axis in axis_children:
            axis_id = axis.id or axis.which
            fig.set_axis(
                axis_id,
                label=axis.label,
                label_position=axis.label_position,
                label_offset=axis.label_offset,
                label_angle=axis.label_angle,
                type_=axis.type_,
                domain=axis.domain,
                reverse=axis.reverse,
                format=axis.format,
                tick_count=axis.tick_count,
                tick_label_angle=axis.tick_label_angle,
                tick_label_strategy=axis.tick_label_strategy,
                tick_label_min_gap=axis.tick_label_min_gap,
                side=axis.side,
                style=axis.style,
            )
        fig.class_name = self.class_name
        fig.class_names = dict(self.class_names)
        fig.style = {}
        for theme_node in themes:
            fig.style.update(theme_node.style)
        fig.style.update(self.style)
        for node in mark_styles:
            fig.set_mark_style(
                hover=node.hover,
                selected=node.selected,
                unselected=node.unselected,
            )
        if (
            self.hover is not None
            or self.click is not None
            or self.select is not None
            or self.brush is not None
            or self.crosshair is not None
            or self.view_change is not None
            or self.link_group is not None
        ):
            fig.set_interaction(
                hover=self.hover,
                click=self.click,
                select=self.select,
                brush=self.brush,
                crosshair=self.crosshair,
                view_change=self.view_change,
                link_group=self.link_group,
                link_axes=self.link_axes,
            )
        for node in interactions:
            fig.set_interaction(
                hover=node.hover,
                click=node.click,
                select=node.select,
                brush=node.brush,
                crosshair=node.crosshair,
                view_change=node.view_change,
                link_group=node.link_group,
                link_axes=node.link_axes,
            )
        fig.set_interaction(
            hover=True if self.on_hover is not None else None,
            click=True if self.on_click is not None else None,
            brush=True if self.on_brush is not None else None,
            select=True if self.on_brush is not None or self.on_select is not None else None,
            view_change=True if self.on_view_change is not None else None,
        )
        tooltip_aliases: dict[str, str] = {}
        tooltip_sources: dict[str, list[dict[str, Any]]] = {}
        for m in marks:
            data = m.data if m.data is not None else self.data
            applier = _MARK_APPLIERS.get(m.kind)
            if applier is None:
                raise TypeError(f"no applier registered for mark kind {m.kind!r}")
            x_axis_id, y_axis_id = _mark_axis_ids(m, axes)
            before = len(fig.traces)
            applier(fig, m, data)
            new_traces = fig.traces[before:]
            for trace in new_traces:
                trace.x_axis = x_axis_id
                trace.y_axis = y_axis_id
            if m.class_name is not None:
                class_name = _optional_string(m.class_name, f"{m.kind} class_name")
                for trace in new_traces:
                    trace.style["class_name"] = class_name
            _merge_tooltip_aliases(tooltip_aliases, m, new_traces)
            _merge_tooltip_sources(tooltip_sources, m, new_traces)

        for annotation in annotations:
            applier = _ANNOTATION_APPLIERS.get(annotation.kind)
            if applier is None:
                raise TypeError(f"no applier registered for annotation kind {annotation.kind!r}")
            applier(fig, annotation)
        fig._annotation_specs()

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
            fig.show_tooltip = node.show
            fig.tooltip = _tooltip_spec(node, tooltip_aliases, tooltip_sources)
        self._figure = fig
        return fig

    # -- render (delegates to the engine) ------------------------------------

    def chrome_components(self) -> dict[str, Any]:
        """Opaque user chrome objects for adapters such as Reflex.

        Core fastcharts does not import or serialize framework components. The
        objects returned here are the exact Python objects passed to
        `fc.legend(...)` / `fc.tooltip(...)`, so an adapter can mount them while
        standalone HTML keeps using the built-in safe DOM fallback.
        """
        result: dict[str, Any] = {}
        legends = [c for c in self.children if isinstance(c, Legend)]
        if legends and legends[-1].render is not None:
            result["legend"] = legends[-1].render
        tooltips = [c for c in self.children if isinstance(c, Tooltip)]
        if tooltips and tooltips[-1].render is not None:
            result["tooltip"] = tooltips[-1].render
        return result

    def reflex_components(self) -> dict[str, Any]:
        """Alias for `chrome_components()` for Reflex adapter/user code."""
        return self.chrome_components()

    def widget(self) -> Any:
        if self._widget is None:
            from .widget import FigureWidget

            self._widget = FigureWidget(
                self.figure(),
                on_hover=self.on_hover,
                on_click=self.on_click,
                on_brush=self.on_brush,
                on_select=self.on_select,
                on_view_change=self.on_view_change,
            )
        return self._widget

    def show(self) -> Any:
        return self.widget()

    def _ipython_display_(self) -> None:
        from IPython.display import display  # type: ignore[import-not-found]

        display(self.widget())

    def to_html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
    ) -> str:
        return self.figure().to_html(path, custom_css=custom_css)

    def html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
    ) -> str:
        return self.to_html(path, custom_css=custom_css)

    def _repr_html_(self) -> str:
        return self.figure()._repr_html_()

    def to_svg(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> str:
        return self.figure().to_svg(path, width=width, height=height)

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


def _string_list(value: Any, label: str) -> Optional[list[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list[str] or None")
    return [item for item in value]


def _string_dict(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    return Figure._string_mapping(value, label)


def _class_names_dict(value: Any, label: str) -> dict[str, str]:
    class_names = _string_dict(value, label)
    validate_dom_slots(class_names, label)
    return class_names


def _style_dict(value: Any, label: str) -> dict[str, StyleValue]:
    if value is None:
        return {}
    return Figure._style_mapping(value, label)


_THEME_TOKEN_ALIASES = {
    "plot_background": "--chart-bg",
    "background": "--chart-bg",
    "grid_color": "--chart-grid",
    "axis_color": "--chart-axis",
    "text_color": "--chart-text",
    "crosshair_color": "--chart-crosshair",
    "selection_color": "--chart-selection",
    "selection_fill": "--chart-selection-fill",
}


def _theme_tokens(values: dict[str, Any], label: str) -> dict[str, StyleValue]:
    raw = {key: value for key, value in values.items() if value is not None}
    mapped = {_THEME_TOKEN_ALIASES.get(key, key): value for key, value in raw.items()}
    return _style_dict(mapped, label)


def _chrome_render_args(
    children: tuple[Any, ...],
    show: Any,
    render: Any,
    label: str,
) -> tuple[Any, Any]:
    if len(children) > 1:
        raise TypeError(f"{label}() accepts at most one component child")
    if not children:
        return show, render
    child = children[0]
    if isinstance(child, (bool, np.bool_)):
        if render is not None:
            raise TypeError(f"{label}() cannot combine positional show with render=")
        return bool(child), None
    if render is not None:
        raise TypeError(f"{label}() cannot combine a component child with render=")
    return show, child


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


def _tooltip_spec(
    node: Tooltip,
    aliases: dict[str, str],
    sources: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    if node.fields:
        spec["fields"] = list(node.fields)
    if node.title is not None:
        spec["title"] = node.title
    if node.format:
        spec["format"] = dict(node.format)
    if aliases:
        spec["aliases"] = dict(aliases)
    if sources:
        spec["sources"] = {field: list(entries) for field, entries in sources.items()}
    return spec


def _add_tooltip_source(
    sources: dict[str, list[dict[str, Any]]],
    field: str,
    traces: list[Any],
    channel: str,
) -> None:
    entries = sources.setdefault(field, [])
    seen = {(entry["trace"], entry["channel"]) for entry in entries}
    for trace in traces:
        key = (trace.id, channel)
        if key in seen:
            continue
        entries.append({"trace": trace.id, "channel": channel})
        seen.add(key)


def _merge_tooltip_sources(
    sources: dict[str, list[dict[str, Any]]], mark: Mark, traces: list[Any]
) -> None:
    if isinstance(mark.x, str):
        _add_tooltip_source(sources, mark.x, traces, "x")
    if isinstance(mark.y, str):
        _add_tooltip_source(sources, mark.y, traces, "y")
    if mark.kind == "heatmap" and isinstance(mark.props.get("z"), str):
        _add_tooltip_source(sources, mark.props["z"], traces, "color_value")
    color = mark.props.get("color")
    if isinstance(color, str) and not _looks_like_css(color):
        channel = next((trace.color_ch for trace in traces if trace.color_ch is not None), None)
        if channel is not None:
            _add_tooltip_source(
                sources,
                color,
                traces,
                "color_category" if channel.mode == "categorical" else "color_value",
            )
    size = mark.props.get("size")
    if isinstance(size, str):
        channel = next((trace.size_ch for trace in traces if trace.size_ch is not None), None)
        if channel is not None:
            _add_tooltip_source(sources, size, traces, "size_value")


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
    axis_id = axis.id or axis.which
    _axis_id(axis_id, f"{axis.which}_axis id")
    if not axis_id.startswith(axis.which):
        raise ValueError(f"{axis.which}_axis id must start with {axis.which!r}")
    _validate_axis_type(axis.type_)
    _axis_domain(axis.domain, f"{axis.which}_axis domain")
    _strict_bool(axis.reverse, f"{axis.which}_axis reverse")
    _axis_side(axis.side, axis.which)
    _axis_label_position(axis.label_position, f"{axis.which}_axis label_position")
    _optional_finite_number(axis.label_offset, f"{axis.which}_axis label_offset")
    _optional_finite_number(axis.label_angle, f"{axis.which}_axis label_angle")
    _optional_positive_int(axis.tick_count, f"{axis.which}_axis tick_count")
    _optional_finite_number(axis.tick_label_angle, f"{axis.which}_axis tick_label_angle")
    _axis_tick_label_strategy(axis.tick_label_strategy, f"{axis.which}_axis tick_label_strategy")
    _optional_nonnegative_number(axis.tick_label_min_gap, f"{axis.which}_axis tick_label_min_gap")


def _mark_axis_ids(mark: Mark, axes: dict[str, Axis]) -> tuple[str, str]:
    x_axis_id = _axis_id(mark.props.get("x_axis", "x"), f"{mark.kind} x_axis")
    y_axis_id = _axis_id(mark.props.get("y_axis", "y"), f"{mark.kind} y_axis")
    if not x_axis_id.startswith("x"):
        raise ValueError(f"{mark.kind} x_axis must start with 'x'")
    if not y_axis_id.startswith("y"):
        raise ValueError(f"{mark.kind} y_axis must start with 'y'")
    for axis_id, factory in ((x_axis_id, "x_axis"), (y_axis_id, "y_axis")):
        if axis_id in {"x", "y"} or axis_id in axes:
            continue
        raise ValueError(f"{mark.kind} {axis_id!r} has no matching fc.{factory}(id={axis_id!r})")
    return x_axis_id, y_axis_id


def _validate_axis_type(type_: Optional[str]) -> None:
    if type_ is None or type_ in {"linear", "time", "log"}:
        return
    raise ValueError(f"axis type_ must be one of None, 'linear', 'time', or 'log', got {type_!r}")


def _axis_domain(value: Any, label: str) -> Optional[tuple[float, float]]:
    if value is None:
        return None
    return _validate.finite_increasing_pair(value, label)


def _axis_side(value: Any, which: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{which}_axis side must be a string")
    allowed = {"top", "bottom"} if which == "x" else {"left", "right"}
    if value not in allowed:
        raise ValueError(f"{which}_axis side must be one of {sorted(allowed)}")
    return value


def _annotation_axis_name(value: Any, label: str) -> str:
    if value not in {"x", "y"}:
        raise ValueError(f"{label} must be 'x' or 'y'")
    return value


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
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        name=m.name,
        color=_resolve_color(data, m.props["color"], context=f"{m.kind}.color"),
        size=_resolve(data, size, context=f"{m.kind}.size") if isinstance(size, str) else size,
        colormap=m.props["colormap"],
        size_range=m.props["size_range"],
        opacity=m.props["opacity"],
        density=m.props["density"],
        symbol=m.props["symbol"],
        stroke=m.props["stroke"],
        stroke_width=m.props["stroke_width"],
    )


def _apply_line(fig: Figure, m: Mark, data: Any) -> None:
    fig.line(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
        curve=m.props["curve"],
        dash=m.props["dash"],
    )


def _apply_area(fig: Figure, m: Mark, data: Any) -> None:
    base = m.props["base"]
    fig.area(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        base=_resolve(data, base, context=f"{m.kind}.base") if isinstance(base, str) else base,
        name=m.name,
        color=m.props["color"],
        opacity=m.props["opacity"],
        line_width=m.props["line_width"],
        line_opacity=m.props["line_opacity"],
        fill=m.props["fill"],
        curve=m.props["curve"],
        dash=m.props["dash"],
        fill_color=m.props["fill_color"],
        width=m.props["width"],
        fill_opacity=m.props["fill_opacity"],
        baseline=m.props["baseline"],
    )


def _apply_candlestick(fig: Figure, m: Mark, data: Any) -> None:
    fig.candlestick(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.props["open"], context=f"{m.kind}.open"),
        _resolve(data, m.props["high"], context=f"{m.kind}.high"),
        _resolve(data, m.props["low"], context=f"{m.kind}.low"),
        _resolve(data, m.props["close"], context=f"{m.kind}.close"),
        name=m.name,
        up_color=m.props["up_color"],
        down_color=m.props["down_color"],
        width_frac=m.props["width_frac"],
        opacity=m.props["opacity"],
        hollow=m.props["hollow"],
        wick_color=m.props["wick_color"],
    )


def _apply_ohlc(fig: Figure, m: Mark, data: Any) -> None:
    fig.ohlc(
        _resolve(data, m.x, context=f"{m.kind}.x"),
        _resolve(data, m.props["open"], context=f"{m.kind}.open"),
        _resolve(data, m.props["high"], context=f"{m.kind}.high"),
        _resolve(data, m.props["low"], context=f"{m.kind}.low"),
        _resolve(data, m.props["close"], context=f"{m.kind}.close"),
        name=m.name,
        up_color=m.props["up_color"],
        down_color=m.props["down_color"],
        width_frac=m.props["width_frac"],
        opacity=m.props["opacity"],
    )


def _apply_histogram(fig: Figure, m: Mark, data: Any) -> None:
    fig.histogram(
        _resolve(data, m.x, context=f"{m.kind}.values"),
        bins=m.props["bins"],
        range=m.props["range"],
        density=m.props["density"],
        cumulative=m.props["cumulative"],
        name=m.name,
        color=m.props["color"],
        opacity=m.props["opacity"],
        corner_radius=m.props["corner_radius"],
        stroke=m.props["stroke"],
        stroke_width=m.props["stroke_width"],
        fill=m.props["fill"],
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
        corner_radius=m.props["corner_radius"],
        stroke=m.props["stroke"],
        stroke_width=m.props["stroke_width"],
        fill=m.props["fill"],
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
        corner_radius=m.props["corner_radius"],
        stroke=m.props["stroke"],
        stroke_width=m.props["stroke_width"],
        fill=m.props["fill"],
    )


def _annotation_style(annotation: Annotation) -> dict[str, StyleValue]:
    style = dict(annotation.style)
    color = annotation.props.get("color")
    if color is not None:
        if not isinstance(color, str):
            raise ValueError(f"{annotation.kind} annotation color must be a string or None")
        style.setdefault("color", color)
    return style


def _apply_rule_annotation(fig: Figure, annotation: Annotation) -> None:
    if annotation.axis == "x":
        fig.vline(
            annotation.x,
            text=annotation.text,
            width=annotation.props["width"],
            opacity=annotation.props["opacity"],
            class_name=annotation.class_name,
            style=_annotation_style(annotation),
        )
    elif annotation.axis == "y":
        fig.hline(
            annotation.y,
            text=annotation.text,
            width=annotation.props["width"],
            opacity=annotation.props["opacity"],
            class_name=annotation.class_name,
            style=_annotation_style(annotation),
        )
    else:
        raise ValueError("rule annotation axis must be 'x' or 'y'")


def _apply_band_annotation(fig: Figure, annotation: Annotation) -> None:
    if annotation.axis == "x":
        fig.x_band(
            annotation.x,
            annotation.y,
            text=annotation.text,
            opacity=annotation.props["opacity"],
            class_name=annotation.class_name,
            style=_annotation_style(annotation),
        )
    elif annotation.axis == "y":
        fig.y_band(
            annotation.x,
            annotation.y,
            text=annotation.text,
            opacity=annotation.props["opacity"],
            class_name=annotation.class_name,
            style=_annotation_style(annotation),
        )
    else:
        raise ValueError("band annotation axis must be 'x' or 'y'")


def _apply_text_annotation(fig: Figure, annotation: Annotation) -> None:
    fig.text(
        annotation.x,
        annotation.y,
        annotation.text or "",
        dx=annotation.props["dx"],
        dy=annotation.props["dy"],
        color=annotation.props.get("color"),
        anchor=annotation.props["anchor"],
        class_name=annotation.class_name,
        style=annotation.style,
    )


def _apply_marker_annotation(fig: Figure, annotation: Annotation) -> None:
    fig.marker(
        annotation.x,
        annotation.y,
        text=annotation.text,
        color=annotation.props.get("color"),
        size=annotation.props["size"],
        symbol=annotation.props["symbol"],
        stroke_color=annotation.props.get("stroke_color"),
        stroke_width=annotation.props["stroke_width"],
        opacity=annotation.props["opacity"],
        dx=annotation.props["dx"],
        dy=annotation.props["dy"],
        anchor=annotation.props["anchor"],
        class_name=annotation.class_name,
        style=annotation.style,
    )


def _apply_arrow_annotation(fig: Figure, annotation: Annotation) -> None:
    fig.arrow(
        annotation.x,
        annotation.y,
        annotation.props["x1"],
        annotation.props["y1"],
        text=annotation.text,
        width=annotation.props["width"],
        opacity=annotation.props["opacity"],
        class_name=annotation.class_name,
        style=_annotation_style(annotation),
    )


def _apply_callout_annotation(fig: Figure, annotation: Annotation) -> None:
    fig.callout(
        annotation.x,
        annotation.y,
        annotation.text or "",
        dx=annotation.props["dx"],
        dy=annotation.props["dy"],
        width=annotation.props["width"],
        opacity=annotation.props["opacity"],
        anchor=annotation.props["anchor"],
        class_name=annotation.class_name,
        style=_annotation_style(annotation),
    )


_MARK_APPLIERS: dict[str, Callable[[Figure, Mark, Any], None]] = {
    "area": _apply_area,
    "bar": _apply_bar,
    "candlestick": _apply_candlestick,
    "column": _apply_column,
    "heatmap": _apply_heatmap,
    "histogram": _apply_histogram,
    "ohlc": _apply_ohlc,
    "scatter": _apply_scatter,
    "line": _apply_line,
}


_ANNOTATION_APPLIERS: dict[str, Callable[[Figure, Annotation], None]] = {
    "arrow": _apply_arrow_annotation,
    "band": _apply_band_annotation,
    "callout": _apply_callout_annotation,
    "marker": _apply_marker_annotation,
    "rule": _apply_rule_annotation,
    "text": _apply_text_annotation,
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


def candlestick_chart(*children: Component, **props: Any) -> Chart:
    """A candlestick chart composing `candlestick` marks and axis/legend children."""
    return Chart("candlestick_chart", children, **props)


def ohlc_chart(*children: Component, **props: Any) -> Chart:
    """An OHLC bar chart composing `ohlc` marks and axis/legend children."""
    return Chart("ohlc_chart", children, **props)


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
