"""A declarative, composition-based component API.

The *feel* is Reflex's (reflex.dev) Recharts components — a chart container with
mark and axis children, snake_case keyword props, `data=` + column-name
resolution, and `on_*` event props — but xy does **not** import or depend
on Reflex. It's the same ergonomics on top of the xy engine (`Figure`):

    import xy as fc

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

The declarative layer is the core: `marks.py` holds the single implementation
of every chart kind, and `Figure` binds those functions as its fluent methods
(`Figure.scatter is marks.scatter`) — so the two dialects cannot drift in
behavior, signatures, or defaults (asserted by tests/test_api_parity.py).
"""

from __future__ import annotations

import datetime as dt
import uuid
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Optional, TypeAlias, Union

import numpy as np

from . import _validate, channels
from ._figure import Figure, Selection
from .dom import CHART_DOM_SLOTS, validate_dom_slots

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
    "FacetChart",
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
    "box",
    "box_chart",
    "callout",
    "chart",
    "column",
    "column_chart",
    "contour",
    "contour_chart",
    "ecdf",
    "ecdf_chart",
    "error_band",
    "error_band_chart",
    "errorbar",
    "errorbar_chart",
    "facet_chart",
    "heatmap",
    "heatmap_chart",
    "hexbin",
    "hexbin_chart",
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
    "scatter",
    "scatter_chart",
    "segments",
    "segments_chart",
    "stairs",
    "stairs_chart",
    "stem",
    "stem_chart",
    "step",
    "step_chart",
    "text",
    "theme",
    "threshold",
    "threshold_zone",
    "tooltip",
    "triangle_mesh",
    "triangle_mesh_chart",
    "violin",
    "violin_chart",
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
    """Base for every xy component (Reflex-style: props + children)."""


@dataclass
class Mark(Component):
    kind: str  # chart mark registry key
    x: Any = None
    y: Any = None
    data: Any = None
    name: Optional[str] = None
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
    tick_values: Optional[list[float]] = None
    tick_labels: Optional[list[str]] = None
    tick_label_angle: Optional[float] = None
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None
    tick_label_min_gap: Optional[float] = None
    side: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Legend(Component):
    show: bool = True
    loc: Optional[str] = None
    ncols: int = 1
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
    colormap: str = channels.DEFAULT_COLORMAP,
    color_domain: Optional[tuple[float, float]] = None,
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
            "color_domain": color_domain,
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
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def error_band(
    x: Union[str, Any] = None,
    lower: Union[str, Any] = None,
    upper: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.22,
    line_width: float = 0.0,
    line_opacity: float = 0.0,
    fill: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A confidence/error band between lower and upper series."""
    return Mark(
        kind="error_band",
        x=x,
        y=lower,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "upper": upper,
            "color": color,
            "opacity": opacity,
            "line_width": line_width,
            "line_opacity": line_opacity,
            "fill": fill,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def errorbar(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    yerr: Union[str, Any, None] = None,
    xerr: Union[str, Any, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    cap_size: Optional[float] = None,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Vertical and/or horizontal uncertainty bars."""
    return Mark(
        kind="errorbar",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "yerr": yerr,
            "xerr": xerr,
            "color": color,
            "width": width,
            "cap_size": cap_size,
            "opacity": opacity,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def segments(
    x0: Union[str, Any] = None,
    y0: Union[str, Any] = None,
    x1: Union[str, Any] = None,
    y1: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    color: Any = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    width: float = 1.2,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Independent line segments rendered as one instanced mark."""
    return Mark(
        kind="segments",
        x=x0,
        y=y0,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "x1": x1,
            "y1": y1,
            "color": color,
            "colormap": colormap,
            "domain": domain,
            "width": width,
            "opacity": opacity,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def triangle_mesh(
    x0: Union[str, Any] = None,
    y0: Union[str, Any] = None,
    x1: Union[str, Any] = None,
    y1: Union[str, Any] = None,
    x2: Union[str, Any] = None,
    y2: Union[str, Any] = None,
    *,
    data: Any = None,
    color: Any = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    name: Optional[str] = None,
    opacity: float = 1.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Filled triangle mesh with constant or per-triangle color values."""
    return Mark(
        kind="triangle_mesh",
        x=x0,
        y=y0,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "color": color,
            "colormap": colormap,
            "domain": domain,
            "opacity": opacity,
            "stroke": stroke,
            "stroke_width": stroke_width,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def step(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A stepped line series."""
    return Mark(
        kind="step",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "where": where,
            "color": color,
            "width": width,
            "opacity": opacity,
            "dash": dash,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def stairs(
    values: Union[str, Any] = None,
    edges: Union[str, Any, None] = None,
    *,
    data: Any = None,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A precomputed stairs series from values and bin edges."""
    return Mark(
        kind="stairs",
        x=values,
        y=edges,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "where": where,
            "color": color,
            "width": width,
            "opacity": opacity,
            "dash": dash,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def stem(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    base: Union[str, float, Any] = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    opacity: float = 1.0,
    marker: bool = True,
    marker_size: float = 5.0,
    symbol: str = "circle",
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A stem plot with optional point markers."""
    return Mark(
        kind="stem",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "base": base,
            "color": color,
            "width": width,
            "opacity": opacity,
            "marker": marker,
            "marker_size": marker_size,
            "symbol": symbol,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def ecdf(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    bins: Optional[int] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Any = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """An empirical cumulative distribution function."""
    return Mark(
        kind="ecdf",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "bins": bins,
            "color": color,
            "width": width,
            "opacity": opacity,
            "dash": dash,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def box(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    x: Union[str, Any, None] = None,
    group: Union[str, Any, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.6,
    opacity: float = 0.85,
    orientation: str = "vertical",
    show_outliers: bool = True,
    outlier_size: float = 4.0,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Grouped Tukey box plots from 1-D or column-oriented 2-D values."""
    return Mark(
        kind="box",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "x": x,
            "group": group,
            "color": color,
            "width": width,
            "opacity": opacity,
            "orientation": orientation,
            "show_outliers": show_outliers,
            "outlier_size": outlier_size,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def violin(
    values: Union[str, Any] = None,
    *,
    data: Any = None,
    x: Union[str, Any, None] = None,
    group: Union[str, Any, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.8,
    bins: int = 64,
    opacity: float = 0.55,
    orientation: str = "vertical",
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Grouped bounded-resolution violin distributions."""
    return Mark(
        kind="violin",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "x": x,
            "group": group,
            "color": color,
            "width": width,
            "bins": bins,
            "opacity": opacity,
            "orientation": orientation,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def hexbin(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    gridsize: int | tuple[int, int] = 64,
    range: Optional[tuple[tuple[float, float], tuple[float, float]]] = None,
    bins: str = "count",
    C: Any = None,
    reduce_C_function: Any = np.mean,
    mincnt: Optional[int] = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    opacity: float = 0.9,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A native-kernel binned hexagonal density plot."""
    return Mark(
        kind="hexbin",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "gridsize": gridsize,
            "range": range,
            "bins": bins,
            "C": C,
            "reduce_C_function": reduce_C_function,
            "mincnt": mincnt,
            "colormap": colormap,
            "opacity": opacity,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def contour(
    z: Union[str, Any] = None,
    *,
    x: Union[str, Any, None] = None,
    y: Union[str, Any, None] = None,
    data: Any = None,
    levels: int | Any = 10,
    filled: bool = False,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    color: Optional[str] = None,
    width: float = 1.1,
    opacity: float = 0.9,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Regular-grid isolines, optionally with a filled density surface."""
    return Mark(
        kind="contour",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        props={
            "z": z,
            "levels": levels,
            "filled": filled,
            "colormap": colormap,
            "color": color,
            "width": width,
            "opacity": opacity,
            "x_axis": x_axis,
            "y_axis": y_axis,
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
    colormap: str = channels.DEFAULT_COLORMAP,
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
    tick_values: Optional[Any] = None,
    tick_labels: Optional[Any] = None,
    tick_label_angle: Optional[float] = None,
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None,
    tick_label_min_gap: Optional[float] = None,
    side: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Axis:
    _validate_axis_type(type_)
    values = None if tick_values is None else [float(v) for v in tick_values]
    labels = None if tick_labels is None else [str(v) for v in tick_labels]
    if labels is not None and (values is None or len(labels) != len(values)):
        raise ValueError("x_axis tick_labels must match tick_values")
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
        tick_values=values,
        tick_labels=labels,
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
    tick_values: Optional[Any] = None,
    tick_labels: Optional[Any] = None,
    tick_label_angle: Optional[float] = None,
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None,
    tick_label_min_gap: Optional[float] = None,
    side: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Axis:
    _validate_axis_type(type_)
    values = None if tick_values is None else [float(v) for v in tick_values]
    labels = None if tick_labels is None else [str(v) for v in tick_labels]
    if labels is not None and (values is None or len(labels) != len(values)):
        raise ValueError("y_axis tick_labels must match tick_values")
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
        tick_values=values,
        tick_labels=labels,
        tick_label_angle=_optional_finite_number(tick_label_angle, "y_axis tick_label_angle"),
        tick_label_strategy=_axis_tick_label_strategy(
            tick_label_strategy, "y_axis tick_label_strategy"
        ),
        tick_label_min_gap=_optional_nonnegative_number(
            tick_label_min_gap, "y_axis tick_label_min_gap"
        ),
        side=_axis_side(side, "y"),
        style=_style_dict(style, "y_axis style"),
    )


def legend(
    *children: Any,
    show: bool = True,
    loc: Optional[str] = None,
    ncols: int = 1,
    render: Any = None,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Legend:
    show, render = _chrome_render_args(children, show, render, "legend")
    return Legend(
        show=_strict_bool(show, "legend show"),
        loc=_optional_string(loc, "legend loc"),
        ncols=_optional_positive_int(ncols, "legend ncols") or 1,
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
    if values is None:
        return None
    # Fast paths that keep the dtype probes off the timed ingestion workflow
    # (§12). A dtype-carrying numeric (NumPy array, pandas Series) can never
    # be category- or datetime-like, so skip the probes outright. A plain
    # Python list/tuple is converted exactly once here and the array is
    # passed on — otherwise `_is_category_like`, `_is_datetime_like`, and
    # engine ingest each re-run the same O(n) conversion on the raw list.
    dtype = getattr(values, "dtype", None)
    if dtype is not None:
        if getattr(dtype, "kind", "") in "fiu":
            return values
    elif isinstance(values, (list, tuple)):
        values = np.asarray(values)
        if values.dtype.kind in "fiu":
            return values
    if Figure._is_category_like(values) and not _is_datetime_like(values):
        return fig._axis_positions(values, axis)
    return values


def _is_datetime_like(values: Any) -> bool:
    if hasattr(values, "to_numpy"):
        try:
            values = values.to_numpy()
        except ValueError:
            # pyarrow Arrays with nulls refuse the default zero-copy
            # conversion (ArrowInvalid is a ValueError); this probe needs the
            # actual values, so allow the copy.
            values = values.to_numpy(zero_copy_only=False)
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
        styles: Optional[dict[str, dict[str, StyleValue]]] = None,
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
        self.styles = _slot_styles_dict(styles, "chart styles")
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
        # Facet builds pre-seed a union category order here (per axis dim) so
        # shared categorical domains align across panels; see FacetChart.
        self._facet_axis_categories: dict[str, list[Any]] = {}

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
                tick_values=axis.tick_values,
                tick_labels=axis.tick_labels,
                tick_label_angle=axis.tick_label_angle,
                tick_label_strategy=axis.tick_label_strategy,
                tick_label_min_gap=axis.tick_label_min_gap,
                side=axis.side,
                style=axis.style,
            )
        # Facet builds pre-seed the union category order (set as a private
        # attribute by FacetChart) so shared categorical domains align the
        # same categories at the same positions across panels; positions are
        # committed at ingest, so this must land before the marks apply.
        for axis_dim, categories in self._facet_axis_categories.items():
            fig._axis_categories[axis_dim] = list(categories)
        fig.class_name = self.class_name
        fig.class_names = dict(self.class_names)
        fig.style = {}
        for theme_node in themes:
            fig.style.update(theme_node.style)
        fig.style.update(self.style)
        for slot, slot_style in self.styles.items():
            fig.chrome_styles[slot] = {**fig.chrome_styles.get(slot, {}), **slot_style}
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
            node = legends[-1]
            _apply_chrome_node(fig, "legend", node.class_name, node.style)
            fig.legend_options = {"loc": node.loc, "ncols": node.ncols}
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

        Core xy does not import or serialize framework components. The
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
        engine: str = "native",
        optimize: bool = False,
        chromium: Optional[str] = None,
        sandbox: bool = True,
    ) -> bytes:
        return self.figure().to_png(
            path,
            width=width,
            height=height,
            scale=scale,
            engine=engine,
            optimize=optimize,
            chromium=chromium,
            sandbox=sandbox,
        )

    def memory_report(self) -> dict[str, Any]:
        return self.figure().memory_report()

    # -- live data (structure-immutable: build a new chart for new marks) ----

    def append(self, trace_id: int, x: Any, y: Any, *, color: Any = None, size: Any = None) -> None:
        """Streaming append: extend a trace's data in place.

        Routed through the live widget when one exists (client refresh plus
        notebook-reopen trait sync); otherwise the built figure mutates
        directly and a later `widget()`/`to_html()` ships the streamed state.
        Already-exported HTML files are snapshots and do not update. Trace ids
        follow mark declaration order (one id per rendered series). Contract
        violations (wrong trace kind, unsorted line x, missing channel tail)
        raise exactly like `Figure.append`.
        """
        if self._widget is not None:
            self._widget.append(trace_id, x, y, color=color, size=size)
        else:
            self.figure().append(trace_id, x, y, color=color, size=size)

    def pick(self, trace_id: int, index: int) -> Optional[dict[str, Any]]:
        """Exact source-row readout from the canonical f64 store.

        Same index space as `Figure.pick`: a shipped vertex index, translated
        to the canonical row when NaN rows were dropped at ship time. Returns
        None when the index is out of range.
        """
        return self.figure().pick(trace_id, index)

    def select_range(
        self,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        trace_id: Optional[int] = None,
    ) -> "Selection":
        """Python-side box select: points inside the window as a `Selection`
        (canonical row indices per trace, with `.index` / `.xy()` access —
        the same object `on_select` callbacks receive)."""
        fig = self.figure()
        return Selection(fig, fig.select_range(x0, x1, y0, y1, trace_id))


def _resolve_color(data: Any, color: Any, *, context: Optional[str] = None) -> Any:
    """Disambiguate a string `color`: a CSS color is a constant; any other
    string is a column name resolved from `data` (Reflex data_key idiom)."""
    if not isinstance(color, str):
        return color  # None, or an already-materialized array
    if _looks_like_css(color):
        return color  # constant color
    try:
        return _resolve(data, color, context=context)  # column name → values
    except ValueError:
        if color.startswith("#") or "(" in color:
            # Color-shaped strings are never real column names; surface the
            # precise CSS reason (the '#3b82zz' typo class) instead of a
            # misleading column-lookup error.
            _validate.css_color(color, context or "color")
        raise


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


def _slot_styles_dict(value: Any, label: str) -> dict[str, dict[str, StyleValue]]:
    """Per-slot inline styles (`styles={slot: {...}}` — docs/styling.md's
    fourth mechanism): slot names validate against `CHART_DOM_SLOTS`, each
    inner dict through the same CSS-declaration gate as `style=`."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dict mapping slot -> style dict")
    validate_dom_slots(value, label)
    return {
        slot: _style_dict(slot_style, f"{label}[{slot!r}]") for slot, slot_style in value.items()
    }


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


def _mark_xy_channels(mark: Mark) -> tuple[str, str]:
    """Tooltip channels for Mark.x/Mark.y. The stairs factory stores values in
    Mark.x and edges in Mark.y, but the rendered channels are swapped (edges
    become x positions, values become y heights)."""
    return ("y", "x") if mark.kind == "stairs" else ("x", "y")


def _merge_tooltip_sources(
    sources: dict[str, list[dict[str, Any]]], mark: Mark, traces: list[Any]
) -> None:
    x_channel, y_channel = _mark_xy_channels(mark)
    if isinstance(mark.x, str):
        _add_tooltip_source(sources, mark.x, traces, x_channel)
    if isinstance(mark.y, str):
        _add_tooltip_source(sources, mark.y, traces, y_channel)
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
    x_channel, y_channel = _mark_xy_channels(mark)
    if isinstance(mark.x, str):
        aliases.setdefault(mark.x, x_channel)
    if isinstance(mark.y, str):
        aliases.setdefault(mark.y, y_channel)
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


# Mark props that carry per-row data channels (besides Mark.x/Mark.y); facet
# splitting must not let a raw length-n array slip whole into every panel.
_FACET_CHANNEL_PROPS = ("color", "size", "upper", "yerr", "xerr", "base", "z", "x", "group")


def _facet_check_mark_channels(mark: Mark, n: int) -> None:
    items = [("x", mark.x), ("y", mark.y)]
    items.extend((key, mark.props.get(key)) for key in _FACET_CHANNEL_PROPS)
    for channel, value in items:
        if value is None or isinstance(value, (str, bytes)) or np.isscalar(value):
            continue
        try:
            length = len(value)
        except TypeError:
            continue
        if length == n:
            raise ValueError(
                f"facet_chart cannot split raw {mark.kind} {channel}= values across "
                "panels; pass column names with data= so each panel can subset its rows"
            )


def _facet_mark(mark: Mark, mask: np.ndarray, n: int) -> Mark:
    """Panel copy of a mark: mark-level data= tables subset with the panel's
    row mask (when row-aligned) so panels do not repeat the full dataset."""
    if mark.data is None:
        return mark
    from .facets import _subset_data

    return Mark(
        kind=mark.kind,
        x=mark.x,
        y=mark.y,
        data=_subset_data(mark.data, mask, n),
        name=mark.name,
        class_name=mark.class_name,
        props=mark.props,
    )


class FacetChart(Component):
    """Composition wrapper for a chart repeated over a table column."""

    def __init__(
        self,
        children: tuple[Component, ...],
        *,
        by: Any,
        cols: int = 3,
        share_x: bool = True,
        share_y: bool = True,
        gap: int = 12,
        **props: Any,
    ) -> None:
        if by is None:
            raise TypeError(
                "facet_chart requires by= — a column name in data= or per-row facet values"
            )
        if (
            isinstance(cols, (bool, np.bool_))
            or not isinstance(cols, (int, np.integer))
            or int(cols) <= 0
        ):
            raise ValueError("facet_chart cols must be a positive integer")
        if (
            isinstance(gap, (bool, np.bool_))
            or not isinstance(gap, (int, np.integer))
            or int(gap) < 0
        ):
            raise ValueError("facet_chart gap must be a non-negative integer")
        self.children = children
        self.by = by
        self.cols = int(cols)
        self.share_x = _strict_bool(share_x, "facet_chart share_x")
        self.share_y = _strict_bool(share_y, "facet_chart share_y")
        self.gap = int(gap)
        self.props = dict(props)
        self._grid: Any = None

    def figure(self) -> Any:
        if self._grid is not None:
            return self._grid
        from .facets import FacetGrid, _facet_values, _subset_data

        data = self.props.get("data")
        if isinstance(self.by, str) and data is None:
            raise ValueError("facet_chart data is required when by is a column name")
        codes, unique_labels = _facet_values(data, self.by)
        n = len(codes)
        width = self.props.get("width", 900)
        height = self.props.get("height", 420)
        if not isinstance(width, (int, np.integer)) or isinstance(width, (bool, np.bool_)):
            raise ValueError("facet_chart width must be a positive integer")
        if not isinstance(height, (int, np.integer)) or isinstance(height, (bool, np.bool_)):
            raise ValueError("facet_chart height must be a positive integer")
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            raise ValueError("facet_chart width and height must be positive")
        panel_width = max(120, (width - (self.cols - 1) * self.gap) // self.cols)
        base_title = self.props.get("title")
        for child in self.children:
            if isinstance(child, Mark):
                _facet_check_mark_channels(child, n)
        masks = [codes == code for code in range(len(unique_labels))]

        def build_panels(preseed: dict[str, list[str]]) -> list[Figure]:
            figures: list[Figure] = []
            for label, mask in zip(unique_labels, masks, strict=True):
                panel_props = dict(self.props)
                panel_props["data"] = None if data is None else _subset_data(data, mask, n)
                panel_props["width"] = panel_width
                panel_props["height"] = height
                # Panel title is the facet label; the grid container renders
                # the base title exactly once.
                panel_props["title"] = label
                children = tuple(
                    _facet_mark(child, mask, n) if isinstance(child, Mark) else child
                    for child in self.children
                )
                panel = Chart("facet_panel", children, **panel_props)
                if preseed:
                    panel._facet_axis_categories = preseed
                figures.append(panel.figure())
            return figures

        figures = build_panels({})
        shared_dims = [dim for dim, shared in (("x", self.share_x), ("y", self.share_y)) if shared]
        unshareable: set[str] = set()
        preseed: dict[str, list[str]] = {}
        for dim in shared_dims:
            per_panel = [fig._axis_categories.get(dim) for fig in figures]
            if all(categories is None for categories in per_panel):
                continue
            if any(categories is None for categories in per_panel):
                warnings.warn(
                    f"facet_chart cannot share the {dim} axis: the {dim} channel is "
                    "categorical in some panels but numeric in others; skipping "
                    f"{dim} domain sharing",
                    UserWarning,
                    stacklevel=2,
                )
                unshareable.add(dim)
                continue
            union: list[str] = []
            seen: set[str] = set()
            for categories in per_panel:
                for category in categories or ():
                    if category not in seen:
                        seen.add(category)
                        union.append(category)
            if any(categories != union for categories in per_panel):
                preseed[dim] = union
        if preseed:
            # Category positions commit at ingest, so panels with differing
            # category sets must be rebuilt with the union order pre-seeded —
            # otherwise a shared numeric domain aligns different categories
            # at the same position.
            figures = build_panels(preseed)
        for dim in shared_dims:
            if dim in unshareable:
                continue
            ranges = [fig.x_range() if dim == "x" else fig.y_range() for fig in figures]
            # Reversed axes report descending (hi, lo) pairs; take the pairwise
            # min/max so the merged domain is always increasing.
            lo = min(min(pair) for pair in ranges)
            hi = max(max(pair) for pair in ranges)
            for fig in figures:
                fig._set_axis_domain(dim, (lo, hi))
        if shared_dims and not any("link_group" in fig.interaction for fig in figures):
            # Shared-axis panels pan/zoom together in live outputs.
            group = f"fc-facet-{uuid.uuid4().hex[:8]}"
            for fig in figures:
                fig.set_interaction(link_group=group, link_axes=tuple(shared_dims))
        self._grid = FacetGrid(
            figures,
            unique_labels,
            cols=self.cols,
            width=width,
            height=height,
            gap=self.gap,
            title=base_title,
        )
        return self._grid

    def widget(self) -> list[Any]:
        return self.figure().widget()

    def show(self) -> list[Any]:
        return self.widget()

    def to_html(
        self, path: Optional[str | PathLike[str]] = None, *, custom_css: Optional[str] = None
    ) -> str:
        return self.figure().to_html(path, custom_css=custom_css)

    def html(
        self, path: Optional[str | PathLike[str]] = None, *, custom_css: Optional[str] = None
    ) -> str:
        return self.to_html(path, custom_css=custom_css)

    def _repr_html_(self) -> str:
        return self.to_html()

    def to_svg(self, path: Optional[str | PathLike[str]] = None) -> str:
        return self.figure().to_svg(path)

    def to_png(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        scale: float = 2.0,
        engine: str = "native",
        optimize: bool = False,
        chromium: Optional[str] = None,
        sandbox: bool = True,
    ) -> bytes:
        return self.figure().to_png(
            path,
            scale=scale,
            engine=engine,
            optimize=optimize,
            chromium=chromium,
            sandbox=sandbox,
        )

    def memory_report(self) -> dict[str, Any]:
        return self.figure().memory_report()


def _validate_axis(axis: Axis) -> None:
    """Structural checks `Figure.set_axis` cannot make: the which/id agreement.

    Field-level validation runs exactly once per field: eagerly in the
    `x_axis`/`y_axis` factories for factory-built children, and in
    `Figure.set_axis` (which every Axis child is replayed through inside the
    same `Chart.figure()` call) for directly-constructed `Axis(...)` objects.
    Re-checking every field here was a second/third pass over the same values.
    """
    if axis.which not in {"x", "y"}:
        raise ValueError(f"axis.which must be 'x' or 'y', got {axis.which!r}")
    axis_id = axis.id or axis.which
    _axis_id(axis_id, f"{axis.which}_axis id")
    if not axis_id.startswith(axis.which):
        raise ValueError(f"{axis.which}_axis id must start with {axis.which!r}")


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
    """A string `color=` is a constant when it parses under the native CSS
    color grammar (src/css.rs: hex, rgb()/hsl(), the full named-color table,
    and browser-resolved forms like var()/oklch()); anything else is a column
    name. The old prefix heuristic accepted any '#…' string, so a typo'd hex
    like '#3b82zz' classified as a "valid" color and rendered silently wrong —
    the exact grammar fails it over to column lookup, whose error names the
    string."""
    from . import kernels

    # Routed through `_validate._css_check` for its verdict memo — the same
    # constant colors are re-classified on every chart build.
    return _validate._css_check(kernels.CSS_COLOR, s) > 0


# ---------------------------------------------------------------------------
# Mark appliers — one per mark kind, mapping a declarative Mark onto a Figure
# call with its (data-resolved) props. Register a new chart type here; the
# Chart container dispatches through this table, so figure() never grows a
# per-kind branch.
# ---------------------------------------------------------------------------


def _apply_scatter(fig: Figure, m: Mark, data: Any) -> None:
    size = m.props["size"]
    checkpoint = fig._checkpoint()
    try:
        fig.scatter(
            _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
            _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
            name=m.name,
            color=_resolve_color(data, m.props["color"], context=f"{m.kind}.color"),
            size=_resolve(data, size, context=f"{m.kind}.size") if isinstance(size, str) else size,
            colormap=m.props["colormap"],
            color_domain=m.props.get("color_domain"),
            size_range=m.props["size_range"],
            opacity=m.props["opacity"],
            density=m.props["density"],
            symbol=m.props["symbol"],
            stroke=m.props["stroke"],
            stroke_width=m.props["stroke_width"],
        )
    except Exception:
        # Axis resolution happens before Figure.scatter's own transactional
        # checkpoint; roll it back too if later channel validation fails.
        fig._rollback(checkpoint)
        raise


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
    )


def _apply_error_band(fig: Figure, m: Mark, data: Any) -> None:
    fig.error_band(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.lower"),
        _resolve_axis_values(fig, data, m.props["upper"], "y", f"{m.kind}.upper"),
        name=m.name,
        color=m.props["color"],
        opacity=m.props["opacity"],
        line_width=m.props["line_width"],
        line_opacity=m.props["line_opacity"],
        fill=m.props["fill"],
    )


def _apply_errorbar(fig: Figure, m: Mark, data: Any) -> None:
    yerr = m.props["yerr"]
    xerr = m.props["xerr"]
    fig.errorbar(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        yerr=_resolve(data, yerr, context=f"{m.kind}.yerr") if isinstance(yerr, str) else yerr,
        xerr=_resolve(data, xerr, context=f"{m.kind}.xerr") if isinstance(xerr, str) else xerr,
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        cap_size=m.props["cap_size"],
        opacity=m.props["opacity"],
    )


def _apply_segments(fig: Figure, m: Mark, data: Any) -> None:
    color = m.props["color"]
    fig.segments(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x0"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y0"),
        _resolve_axis_values(fig, data, m.props["x1"], "x", f"{m.kind}.x1"),
        _resolve_axis_values(fig, data, m.props["y1"], "y", f"{m.kind}.y1"),
        name=m.name,
        color=_resolve_color(data, color, context=f"{m.kind}.color"),
        colormap=m.props["colormap"],
        domain=m.props["domain"],
        width=m.props["width"],
        opacity=m.props["opacity"],
    )


def _apply_triangle_mesh(fig: Figure, m: Mark, data: Any) -> None:
    color = m.props["color"]
    fig.triangle_mesh(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x0"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y0"),
        _resolve_axis_values(fig, data, m.props["x1"], "x", f"{m.kind}.x1"),
        _resolve_axis_values(fig, data, m.props["y1"], "y", f"{m.kind}.y1"),
        _resolve_axis_values(fig, data, m.props["x2"], "x", f"{m.kind}.x2"),
        _resolve_axis_values(fig, data, m.props["y2"], "y", f"{m.kind}.y2"),
        color=_resolve_color(data, color, context=f"{m.kind}.color"),
        colormap=m.props["colormap"],
        domain=m.props["domain"],
        name=m.name,
        opacity=m.props["opacity"],
        stroke=m.props["stroke"],
        stroke_width=m.props["stroke_width"],
    )


def _apply_step(fig: Figure, m: Mark, data: Any) -> None:
    fig.step(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        where=m.props["where"],
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
        dash=m.props["dash"],
    )


def _apply_stairs(fig: Figure, m: Mark, data: Any) -> None:
    edges = _resolve(data, m.y, context=f"{m.kind}.edges") if m.y is not None else None
    fig.stairs(
        _resolve(data, m.x, context=f"{m.kind}.values"),
        edges,
        where=m.props["where"],
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
        dash=m.props["dash"],
    )


def _apply_stem(fig: Figure, m: Mark, data: Any) -> None:
    base = m.props["base"]
    fig.stem(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        base=_resolve(data, base, context=f"{m.kind}.base") if isinstance(base, str) else base,
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
        marker=m.props["marker"],
        marker_size=m.props["marker_size"],
        symbol=m.props["symbol"],
    )


def _apply_ecdf(fig: Figure, m: Mark, data: Any) -> None:
    fig.ecdf(
        _resolve(data, m.x, context=f"{m.kind}.values"),
        bins=m.props["bins"],
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
        dash=m.props["dash"],
    )


def _apply_box(fig: Figure, m: Mark, data: Any) -> None:
    x = m.props["x"]
    group = m.props["group"]
    fig.box(
        _resolve(data, m.x, context=f"{m.kind}.values"),
        x=_resolve(data, x, context=f"{m.kind}.x") if isinstance(x, str) else x,
        group=_resolve(data, group, context=f"{m.kind}.group") if isinstance(group, str) else group,
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
        orientation=m.props["orientation"],
        show_outliers=m.props["show_outliers"],
        outlier_size=m.props["outlier_size"],
    )


def _apply_violin(fig: Figure, m: Mark, data: Any) -> None:
    x = m.props["x"]
    group = m.props["group"]
    fig.violin(
        _resolve(data, m.x, context=f"{m.kind}.values"),
        x=_resolve(data, x, context=f"{m.kind}.x") if isinstance(x, str) else x,
        group=_resolve(data, group, context=f"{m.kind}.group") if isinstance(group, str) else group,
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        bins=m.props["bins"],
        opacity=m.props["opacity"],
        orientation=m.props["orientation"],
    )


def _apply_hexbin(fig: Figure, m: Mark, data: Any) -> None:
    fig.hexbin(
        _resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x"),
        _resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y"),
        gridsize=m.props["gridsize"],
        range=m.props["range"],
        bins=m.props["bins"],
        C=_resolve(data, m.props["C"], context=f"{m.kind}.C")
        if isinstance(m.props["C"], str)
        else m.props["C"],
        reduce_C_function=m.props["reduce_C_function"],
        mincnt=m.props["mincnt"],
        name=m.name,
        colormap=m.props["colormap"],
        opacity=m.props["opacity"],
    )


def _apply_contour(fig: Figure, m: Mark, data: Any) -> None:
    fig.contour(
        _resolve(data, m.props["z"], context=f"{m.kind}.z"),
        x=_resolve_axis_values(fig, data, m.x, "x", f"{m.kind}.x") if m.x is not None else None,
        y=_resolve_axis_values(fig, data, m.y, "y", f"{m.kind}.y") if m.y is not None else None,
        levels=m.props["levels"],
        filled=m.props["filled"],
        name=m.name,
        colormap=m.props["colormap"],
        color=m.props["color"],
        width=m.props["width"],
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
    "box": _apply_box,
    "column": _apply_column,
    "contour": _apply_contour,
    "ecdf": _apply_ecdf,
    "errorbar": _apply_errorbar,
    "error_band": _apply_error_band,
    "hexbin": _apply_hexbin,
    "heatmap": _apply_heatmap,
    "histogram": _apply_histogram,
    "scatter": _apply_scatter,
    "segments": _apply_segments,
    "line": _apply_line,
    "step": _apply_step,
    "stairs": _apply_stairs,
    "stem": _apply_stem,
    "triangle_mesh": _apply_triangle_mesh,
    "violin": _apply_violin,
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


def histogram_chart(*children: Component, **props: Any) -> Chart:
    """A histogram chart composing `histogram` marks and axis/legend children."""
    return Chart("histogram_chart", children, **props)


def bar_chart(*children: Component, **props: Any) -> Chart:
    """A bar chart composing `bar` marks and axis/legend children."""
    return Chart("bar_chart", children, **props)


def box_chart(*children: Component, **props: Any) -> Chart:
    """A box/distribution chart composing `box` marks."""
    return Chart("box_chart", children, **props)


def column_chart(*children: Component, **props: Any) -> Chart:
    """A column chart composing `column` marks and axis/legend children."""
    return Chart("column_chart", children, **props)


def heatmap_chart(*children: Component, **props: Any) -> Chart:
    """A heatmap chart composing `heatmap` marks and axis/legend children."""
    return Chart("heatmap_chart", children, **props)


def violin_chart(*children: Component, **props: Any) -> Chart:
    """A violin chart composing `violin` marks."""
    return Chart("violin_chart", children, **props)


def contour_chart(*children: Component, **props: Any) -> Chart:
    """A contour chart composing `contour` marks."""
    return Chart("contour_chart", children, **props)


def hexbin_chart(*children: Component, **props: Any) -> Chart:
    """A hexbin chart composing `hexbin` marks."""
    return Chart("hexbin_chart", children, **props)


def ecdf_chart(*children: Component, **props: Any) -> Chart:
    """An ECDF chart composing `ecdf` marks."""
    return Chart("ecdf_chart", children, **props)


def errorbar_chart(*children: Component, **props: Any) -> Chart:
    """An error-bar chart composing `errorbar` marks."""
    return Chart("errorbar_chart", children, **props)


def error_band_chart(*children: Component, **props: Any) -> Chart:
    """An uncertainty-band chart composing `error_band` marks."""
    return Chart("error_band_chart", children, **props)


def step_chart(*children: Component, **props: Any) -> Chart:
    """A step chart composing `step` marks."""
    return Chart("step_chart", children, **props)


def stairs_chart(*children: Component, **props: Any) -> Chart:
    """A stairs chart composing `stairs` marks."""
    return Chart("stairs_chart", children, **props)


def stem_chart(*children: Component, **props: Any) -> Chart:
    """A stem chart composing `stem` marks."""
    return Chart("stem_chart", children, **props)


def segments_chart(*children: Component, **props: Any) -> Chart:
    """A segment chart composing generic independent segment marks."""
    return Chart("segments_chart", children, **props)


def triangle_mesh_chart(*children: Component, **props: Any) -> Chart:
    """A filled triangular mesh chart."""
    return Chart("triangle_mesh_chart", children, **props)


def facet_chart(
    *children: Component,
    by: Any = None,
    cols: int = 3,
    share_x: bool = True,
    share_y: bool = True,
    gap: int = 12,
    **props: Any,
) -> FacetChart:
    """Repeat the child mark composition once per value of ``by``.

    ``by`` is normally a column name resolved from chart-level ``data``;
    panels share domains by default and retain the same per-panel LOD path.
    """
    return FacetChart(
        children, by=by, cols=cols, share_x=share_x, share_y=share_y, gap=gap, **props
    )
