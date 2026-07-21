"""A declarative, composition-based component API.

The *feel* is Reflex's (reflex.dev) chart components — a chart container with
mark and axis children, snake_case keyword props, `data=` + column-name
resolution, and `on_*` event props — but xy does **not** import or depend
on Reflex. It's the same ergonomics on top of the xy engine (`Figure`):

    import xy

    xy.scatter_chart(
        xy.scatter(x="sepal_w", y="sepal_l", color="species", size="petal_l", data=df),
        xy.x_axis(label="sepal width"),
        xy.y_axis(label="sepal length"),
        xy.legend(),
        title="Iris",
        on_hover=lambda row: print(row),
        on_select=lambda sel: print(len(sel.index), "points"),
    )

Marks accept `x`/`y`/`color`/`size` as arrays *or* as string column names into
`data` (a DataFrame, dict, or anything indexable) — a string-column key
idiom, read more directly. Everything composes into a `Figure`, so a
chart renders in notebooks and exports to HTML exactly like the fluent API.

The declarative layer is the core: `marks.py` holds the single implementation
of every chart kind, and `Figure` binds those functions as its fluent methods
(`Figure.scatter is marks.scatter`) — so the two dialects cannot drift in
behavior, signatures, or defaults (asserted by tests/test_api_parity.py).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import uuid
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Literal, Optional, TypeAlias, Union

import numpy as np

from . import _validate, channels, export, styles
from ._figure import Figure, Selection
from ._typing import ArrayLike, ColorLike, Scalar, TableLike
from .dom import CHART_DOM_SLOTS, validate_dom_slots

# Shared validators (single source of truth in `_validate`); these aliases keep
# the module-private names their call sites already use.
_optional_string = _validate.optional_text
_finite_number = _validate.finite_scalar
_axis_id = _validate.axis_id
_optional_positive_int = _validate.optional_positive_int
_axis_tick_label_strategy = _validate.axis_tick_label_strategy
_axis_tick_label_anchor = _validate.axis_tick_label_anchor
_axis_label_position = _validate.axis_label_position
_optional_finite_number = _validate.optional_finite_scalar
_optional_nonnegative_number = _validate.optional_nonnegative_scalar

__all__ = [
    "CHART_DOM_SLOTS",
    "Animation",
    "Annotation",
    "Axis",
    "Chart",
    "Colorbar",
    "Component",
    "ExportConfig",
    "FacetChart",
    "Interaction",
    "Legend",
    "Mark",
    "Modebar",
    "Spring",
    "Theme",
    "Tooltip",
    "animation",
    "area",
    "area_chart",
    "arrow",
    "bar",
    "bar_chart",
    "box",
    "box_chart",
    "callout",
    "chart",
    "colorbar",
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
    "export_config",
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
    "marker",
    "modebar",
    "scatter",
    "scatter_chart",
    "segments",
    "segments_chart",
    "spring",
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

# One annotation coordinate: a number, a datetime, or (on a categorical
# axis) a category label.
CoordinateLike: TypeAlias = Union[Scalar, str, dt.datetime, dt.date, np.datetime64]
AxisLabelPosition: TypeAlias = str | dict[str, StyleValue]
AxisTickLabelStrategy: TypeAlias = str

# ---------------------------------------------------------------------------
# Component tree (lightweight declarative specs — no rendering here)
# ---------------------------------------------------------------------------


class Component:
    """Base for every xy component (Reflex-style: props + children)."""


@dataclass
class Mark(Component):
    """A data series inside a chart: one mark kind plus its data/encodings.

    Built by the mark constructors (`scatter`, `line`, `bar`, ...) rather
    than directly; ``props`` carries the kind-specific options verbatim.
    """

    kind: str  # chart mark registry key
    x: Any = None  # column name or ArrayLike (typed on the mark factories)
    y: Any = None  # column name or ArrayLike (typed on the mark factories)
    data: TableLike = None
    name: Optional[str] = None
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    key: Any = None
    animation: "Animation | bool | None" = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Annotation(Component):
    """A non-data overlay (reference rule, band, or text label).

    Built by `vline`/`hline`/`x_band`/`y_band`/`text`/`label` and friends.
    """

    kind: str  # "rule" | "band" | "text"
    axis: Optional[str] = None
    x: Optional[CoordinateLike] = None
    y: Optional[CoordinateLike] = None
    text: Optional[str] = None
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Axis(Component):
    """Axis configuration (scale, domain, ticks, label). Built by
    `x_axis`/`y_axis`, which validate every field."""

    which: str  # "x" | "y"
    id: Optional[str] = None
    label: Optional[str] = None
    label_position: Optional[AxisLabelPosition] = None
    label_offset: Optional[float] = None
    label_angle: Optional[float] = None
    type_: Optional[str] = None  # "linear" | "time" | "log" (auto-detected if None)
    domain: Optional[tuple[float, float]] = None
    bounds: Union[tuple[float, float], Literal["data"], None] = None
    reverse: bool = False
    format: Optional[str] = None
    tick_count: Optional[int] = None
    tick_values: Optional[list[float]] = None
    tick_labels: Optional[list[str]] = None
    tick_label_angle: Optional[float] = None
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None
    tick_label_anchor: Optional[str] = None
    tick_label_min_gap: Optional[float] = None
    side: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Legend(Component):
    """Legend chrome; ``render`` remains opaque for Reflex adapters."""

    show: bool = True
    loc: Optional[str] = None
    ncols: int = 1
    title: Optional[str] = None
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    render: Any = None


@dataclass
class Tooltip(Component):
    """Hover-tooltip chrome; ``render`` remains opaque for Reflex adapters."""

    show: bool = True
    fields: Optional[list[str]] = None
    title: Optional[str] = None
    format: dict[str, str] = field(default_factory=dict)
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    render: Any = None


@dataclass
class Colorbar(Component):
    """Color scale chrome; ``render`` remains opaque for Reflex adapters."""

    show: bool = True
    title: Optional[str] = None
    orientation: str = "vertical"
    ticks: Optional[list[float]] = None
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    render: Any = None


@dataclass
class Modebar(Component):
    """Modebar (zoom/pan/reset controls) chrome."""

    show: bool = True
    class_name: Optional[str] = None
    style: dict[str, StyleValue] = field(default_factory=dict)
    button_class_name: Optional[str] = None
    button_style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class ExportConfig(Component):
    """Declarative export defaults (built by `export_config`): governs the
    modebar's download menu (formats/filename) and provides defaults for the
    Python export APIs. Pure description — no I/O happens at build time."""

    formats: Optional[tuple[str, ...]] = None
    filename: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    scale: Optional[float] = None
    background: Optional[str] = None
    quality: Optional[int] = None


@dataclass
class Theme(Component):
    """Chart-wide style tokens (plot background, grid/axis/text colors)."""

    style: dict[str, StyleValue] = field(default_factory=dict)


@dataclass
class Interaction(Component):
    """Interaction switches (hover/click/select/brush/crosshair/navigation/pan/zoom) and
    cross-chart axis linking. Built by `interaction_config`."""

    hover: Optional[bool] = None
    click: Optional[bool] = None
    select: Optional[bool] = None
    brush: Optional[bool] = None
    crosshair: Optional[bool] = None
    navigation: Optional[bool] = None
    pan: Optional[bool] = None
    zoom: Optional[bool] = None
    view_change: Optional[bool] = None
    link_group: Optional[str] = None
    link_axes: tuple[str, ...] = ("x", "y")


@dataclass(frozen=True)
class Spring:
    """A bounded, serializable spring easing policy."""

    stiffness: float = 170.0
    damping: float = 26.0
    mass: float = 1.0

    def to_spec(self) -> dict[str, float | str]:
        return {
            "type": "spring",
            "stiffness": _positive_animation_number(self.stiffness, "spring stiffness"),
            "damping": _positive_animation_number(self.damping, "spring damping"),
            "mass": _positive_animation_number(self.mass, "spring mass"),
        }


@dataclass
class Animation(Component):
    """Declarative browser transition policy built by :func:`animation`."""

    enabled: bool | Literal["auto"] = "auto"
    delay: float = 0.0
    duration: float = 400.0
    easing: str | tuple[float, float, float, float] | Spring = "ease-out"
    match: Literal["index", "append", "key"] = "index"
    enter: str = "auto"
    update: str = "interpolate"
    interpolate: tuple[str, ...] = ("position", "size", "color", "domain")
    on_start: Optional[Callable[[dict], None]] = field(default=None, repr=False, compare=False)
    on_end: Optional[Callable[[dict], None]] = field(default=None, repr=False, compare=False)

    def to_spec(self) -> dict[str, Any]:
        enabled = self.enabled
        if enabled != "auto" and not isinstance(enabled, bool):
            raise ValueError("animation enabled must be False, True, or 'auto'")
        match = _animation_choice(self.match, "match", {"index", "append", "key"})
        enter = _animation_choice(self.enter, "enter", {"auto", "none", "scale", "grow", "reveal"})
        update = _animation_choice(self.update, "update", {"none", "interpolate"})
        easing: Any
        if isinstance(self.easing, Spring):
            easing = self.easing.to_spec()
        elif isinstance(self.easing, str):
            allowed = {"linear", "ease", "ease-in", "ease-out", "ease-in-out", "spring"}
            easing = _animation_choice(self.easing, "easing", allowed)
            if easing == "spring":
                easing = Spring().to_spec()
        elif isinstance(self.easing, (tuple, list)):
            if len(self.easing) != 4:
                raise ValueError("animation cubic Bézier easing must contain four numbers")
            easing = [
                _finite_number(value, f"animation easing[{i}]")
                for i, value in enumerate(self.easing)
            ]
            if not (0.0 <= easing[0] <= 1.0 and 0.0 <= easing[2] <= 1.0):
                raise ValueError("animation cubic Bézier x control points must be between 0 and 1")
        else:
            raise ValueError(
                "animation easing must be a named easing, four-number cubic Bézier, or spring"
            )
        try:
            policies = tuple(self.interpolate)
        except TypeError as exc:
            raise ValueError("animation interpolate must be a sequence of named policies") from exc
        allowed_policies = {"position", "size", "color", "domain"}
        if (
            not policies
            or any(p not in allowed_policies for p in policies)
            or len(set(policies)) != len(policies)
        ):
            raise ValueError(
                "animation interpolate must contain unique named policies from "
                f"{sorted(allowed_policies)}"
            )
        for callback, label in ((self.on_start, "on_start"), (self.on_end, "on_end")):
            if callback is not None and not callable(callback):
                raise ValueError(f"animation {label} must be callable or None")
        return {
            "enabled": enabled,
            "delay": _nonnegative_animation_number(self.delay, "animation delay"),
            "duration": _nonnegative_animation_number(self.duration, "animation duration"),
            "easing": easing,
            "match": match,
            "enter": enter,
            "update": update,
            "interpolate": list(policies),
        }


def _positive_animation_number(value: Any, label: str) -> float:
    number = _finite_number(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _nonnegative_animation_number(value: Any, label: str) -> float:
    number = _finite_number(value, label)
    if number < 0:
        raise ValueError(f"{label} must be non-negative")
    return number


def _animation_choice(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"animation {label} must be one of {sorted(allowed)}")
    return value


def spring(*, stiffness: float = 170.0, damping: float = 26.0, mass: float = 1.0) -> Spring:
    """Build a serializable spring easing policy.

    Args:
        stiffness: Spring stiffness; larger values respond more quickly.
        damping: Resistance that settles the spring and limits overshoot.
        mass: Spring mass; larger values respond more slowly.
    """
    value = Spring(stiffness=stiffness, damping=damping, mass=mass)
    value.to_spec()
    return value


def animation(
    *,
    enabled: bool | Literal["auto"] = "auto",
    delay: float = 0,
    duration: float = 400,
    easing: str | tuple[float, float, float, float] | Spring = "ease-out",
    match: Literal["index", "append", "key"] = "index",
    enter: str = "auto",
    update: str = "interpolate",
    interpolate: Sequence[str] = ("position", "size", "color", "domain"),
    on_start: Optional[Callable[[dict], None]] = None,
    on_end: Optional[Callable[[dict], None]] = None,
) -> Animation:
    """Configure entrance and data-update motion without per-frame callbacks.

    Args:
        enabled: ``"auto"`` honors reduced motion; a boolean explicitly enables or disables.
        delay: Non-negative delay before motion begins, in milliseconds.
        duration: Non-negative animation duration, in milliseconds.
        easing: Named easing, four-number cubic Bézier tuple, or ``spring()`` policy.
        match: Row identity strategy: ``"index"``, ``"append"``, or ``"key"``.
        enter: Entrance effect, such as ``"auto"``, ``"scale"``, or ``"reveal"``.
        update: Update effect; use ``"interpolate"`` or ``"none"``.
        interpolate: Unique channels to interpolate during updates.
        on_start: Optional live-host callback receiving the animation-start event.
        on_end: Optional live-host callback receiving the animation-end event.
    """
    value = Animation(
        enabled=enabled,
        delay=delay,
        duration=duration,
        easing=easing,
        match=match,
        enter=enter,
        update=update,
        interpolate=tuple(interpolate),
        on_start=on_start,
        on_end=on_end,
    )
    value.to_spec()
    return value


# ---------------------------------------------------------------------------
# Factory functions (the public, Reflex-flavored surface)
# ---------------------------------------------------------------------------


def scatter(
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    color: Union[str, ColorLike, ArrayLike, None] = None,
    size: Union[str, Scalar, ArrayLike, None] = 4.0,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    color_domain: Optional[tuple[float, float]] = None,
    size_range: tuple[float, float] = (2.0, 18.0),
    opacity: Any = 0.8,
    density: Optional[bool] = None,
    symbol: Any = "circle",
    stroke: Any = None,
    stroke_width: Any = 0.0,
    _artist_alpha: Any = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A scatter series with optional color, size, and density encodings.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        color: Constant color, values, or a column name.
        size: Constant marker size, values, or a column name.
        name: Series label used by legends and tooltips.
        colormap: Colormap used for continuous color values.
        color_domain: Explicit minimum and maximum for continuous colors.
        size_range: Minimum and maximum rendered marker sizes.
        opacity: Marker opacity from zero to one.
        density: Whether to force or disable density aggregation.
        symbol: Marker symbol name.
        stroke: Optional marker outline color.
        stroke_width: Marker outline width in pixels.
        _artist_alpha: Internal Matplotlib alpha override, scalar or per marker.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="scatter",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "scatter style"),
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
            "_artist_alpha": _artist_alpha,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def line(
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    curve: str = "linear",
    dash: Union[str, Sequence[float], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A line series with automatic M4 decimation for large inputs.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        name: Series label used by legends and tooltips.
        color: Line color.
        width: Line width in pixels.
        opacity: Line opacity from zero to one.
        curve: Interpolation mode, such as ``linear`` or ``smooth``.
        dash: Optional line dash pattern.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="line",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "line style"),
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
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    base: Union[str, Scalar, ArrayLike] = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.35,
    line_color: Optional[str] = None,
    line_width: float = 1.2,
    line_opacity: float = 1.0,
    stroke_perimeter: bool = False,
    fill: Union[str, dict[str, str], None] = None,
    curve: str = "linear",
    dash: Union[str, Sequence[float], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A filled area series between ``y`` and ``base``.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        base: Baseline value, values, or a column name.
        name: Series label used by legends and tooltips.
        color: Area fill color.
        opacity: Fill opacity from zero to one.
        line_color: Outline color.
        line_width: Outline width in pixels.
        line_opacity: Outline opacity from zero to one.
        stroke_perimeter: Whether to stroke the complete area perimeter.
        fill: CSS fill value or linear gradient.
        curve: Interpolation mode, such as ``linear`` or ``smooth``.
        dash: Optional outline dash pattern.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="area",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "area style"),
        props={
            "base": base,
            "color": color,
            "opacity": opacity,
            "line_color": line_color,
            "line_width": line_width,
            "line_opacity": line_opacity,
            "stroke_perimeter": stroke_perimeter,
            "fill": fill,
            "curve": curve,
            "dash": dash,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def error_band(
    x: Union[str, ArrayLike, None] = None,
    lower: Union[str, ArrayLike, None] = None,
    upper: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.22,
    line_width: float = 0.0,
    line_opacity: float = 0.0,
    fill: Union[str, dict[str, str], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A confidence or error band between lower and upper series.

    Args:
        x: X values or a column name resolved from ``data``.
        lower: Lower-bound values or a column name.
        upper: Upper-bound values or a column name.
        data: Table used to resolve column-name inputs.
        name: Series label used by legends and tooltips.
        color: Band color.
        opacity: Band opacity from zero to one.
        line_width: Boundary-line width in pixels.
        line_opacity: Boundary-line opacity from zero to one.
        fill: CSS fill value or linear gradient.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="error_band",
        x=x,
        y=lower,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "error_band style"),
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
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    yerr: Union[str, Scalar, ArrayLike, None] = None,
    xerr: Union[str, Scalar, ArrayLike, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    cap_size: Optional[float] = None,
    opacity: float = 1.0,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Vertical and/or horizontal uncertainty bars.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        yerr: Symmetric or asymmetric vertical error values.
        xerr: Symmetric or asymmetric horizontal error values.
        name: Series label used by legends and tooltips.
        color: Error-bar color.
        width: Stroke width in pixels.
        cap_size: Optional cap length in pixels.
        opacity: Stroke opacity from zero to one.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="errorbar",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "errorbar style"),
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
    x0: Union[str, ArrayLike, None] = None,
    y0: Union[str, ArrayLike, None] = None,
    x1: Union[str, ArrayLike, None] = None,
    y1: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    name: Optional[str] = None,
    color: Union[str, ColorLike, ArrayLike, None] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    width: Any = 1.2,
    opacity: Any = 1.0,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Independent line segments rendered as one instanced mark.

    Args:
        x0: Starting x coordinates or a column name.
        y0: Starting y coordinates or a column name.
        x1: Ending x coordinates or a column name.
        y1: Ending y coordinates or a column name.
        data: Table used to resolve column-name inputs.
        name: Series label used by legends and tooltips.
        color: Constant color, values, or a column name.
        colormap: Colormap used for continuous color values.
        domain: Explicit minimum and maximum for continuous colors.
        width: Segment width in pixels.
        opacity: Segment opacity from zero to one.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="segments",
        x=x0,
        y=y0,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "segments style"),
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
    x0: Union[str, ArrayLike, None] = None,
    y0: Union[str, ArrayLike, None] = None,
    x1: Union[str, ArrayLike, None] = None,
    y1: Union[str, ArrayLike, None] = None,
    x2: Union[str, ArrayLike, None] = None,
    y2: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    color: Union[str, ColorLike, ArrayLike, None] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    name: Optional[str] = None,
    opacity: Any = 1.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Filled triangle mesh with constant or per-triangle color values.

    Args:
        x0: First-vertex x coordinates or a column name.
        y0: First-vertex y coordinates or a column name.
        x1: Second-vertex x coordinates or a column name.
        y1: Second-vertex y coordinates or a column name.
        x2: Third-vertex x coordinates or a column name.
        y2: Third-vertex y coordinates or a column name.
        data: Table used to resolve column-name inputs.
        color: Constant color, values, or a column name.
        colormap: Colormap used for continuous color values.
        domain: Explicit minimum and maximum for continuous colors.
        name: Series label used by legends and tooltips.
        opacity: Triangle opacity from zero to one.
        stroke: Optional triangle outline color.
        stroke_width: Triangle outline width in pixels.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="triangle_mesh",
        x=x0,
        y=y0,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "triangle_mesh style"),
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
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Union[str, Sequence[float], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A stepped line series.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        where: Position of each step transition.
        name: Series label used by legends and tooltips.
        color: Line color.
        width: Line width in pixels.
        opacity: Line opacity from zero to one.
        dash: Optional line dash pattern.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="step",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "step style"),
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
    values: Union[str, ArrayLike, None] = None,
    edges: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Union[str, Sequence[float], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A precomputed stairs series from values and bin edges.

    Args:
        values: Step heights or a column name resolved from ``data``.
        edges: Bin-edge values or a column name.
        data: Table used to resolve column-name inputs.
        where: Position of each step transition.
        name: Series label used by legends and tooltips.
        color: Line color.
        width: Line width in pixels.
        opacity: Line opacity from zero to one.
        dash: Optional line dash pattern.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="stairs",
        x=values,
        y=edges,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "stairs style"),
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
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    base: Union[str, Scalar, ArrayLike] = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    opacity: float = 1.0,
    marker: bool = True,
    marker_size: float = 5.0,
    symbol: str = "circle",
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A stem plot with optional point markers.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        base: Baseline value, values, or a column name.
        name: Series label used by legends and tooltips.
        color: Stem and marker color.
        width: Stem width in pixels.
        opacity: Mark opacity from zero to one.
        marker: Whether to draw a marker at each stem endpoint.
        marker_size: Marker size in pixels.
        symbol: Marker symbol name.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="stem",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "stem style"),
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
    values: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    bins: Optional[int] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Union[str, Sequence[float], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """An empirical cumulative distribution function.

    Args:
        values: Sample values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        bins: Optional bounded number of evaluation bins.
        name: Series label used by legends and tooltips.
        color: Line color.
        width: Line width in pixels.
        opacity: Line opacity from zero to one.
        dash: Optional line dash pattern.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="ecdf",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "ecdf style"),
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
    values: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    x: Union[str, ArrayLike, None] = None,
    group: Union[str, ArrayLike, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.6,
    opacity: float = 0.85,
    orientation: str = "vertical",
    show_outliers: bool = True,
    outlier_size: float = 4.0,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Grouped Tukey box plots from 1-D or column-oriented 2-D values.

    Args:
        values: Sample values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        x: Optional group positions or a column name.
        group: Optional grouping values or a column name.
        name: Series label used by legends and tooltips.
        color: Box color.
        width: Box width in category units.
        opacity: Box opacity from zero to one.
        orientation: ``vertical`` or ``horizontal`` orientation.
        show_outliers: Whether to render outlier points.
        outlier_size: Outlier marker size in pixels.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="box",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "box style"),
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
    values: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    x: Union[str, ArrayLike, None] = None,
    group: Union[str, ArrayLike, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.8,
    bins: int = 64,
    opacity: float = 0.55,
    orientation: str = "vertical",
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Grouped bounded-resolution violin distributions.

    Args:
        values: Sample values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        x: Optional group positions or a column name.
        group: Optional grouping values or a column name.
        name: Series label used by legends and tooltips.
        color: Violin color.
        width: Violin width in category units.
        bins: Density resolution.
        opacity: Violin opacity from zero to one.
        orientation: ``vertical`` or ``horizontal`` orientation.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="violin",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "violin style"),
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
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    gridsize: int | tuple[int, int] = 64,
    range: Optional[tuple[tuple[float, float], tuple[float, float]]] = None,
    bins: str = "count",
    C: Union[str, ArrayLike, None] = None,
    reduce_C_function: Callable[[np.ndarray], Scalar] = np.mean,
    mincnt: Optional[int] = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    opacity: float = 0.9,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A native-kernel binned hexagonal density plot.

    Args:
        x: X values or a column name resolved from ``data``.
        y: Y values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        gridsize: Horizontal and optional vertical bin counts.
        range: Explicit x and y input ranges.
        bins: Bin normalization mode.
        C: Optional values aggregated within each hexagon.
        reduce_C_function: Reduction applied to values in each hexagon.
        mincnt: Minimum observations required to render a hexagon.
        name: Series label used by legends and tooltips.
        colormap: Colormap used for bin values.
        opacity: Hexagon opacity from zero to one.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="hexbin",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "hexbin style"),
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
    z: Union[str, ArrayLike, None] = None,
    *,
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    data: TableLike = None,
    levels: Union[int, ArrayLike] = 10,
    filled: bool = False,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    color: Optional[str] = None,
    width: float = 1.1,
    opacity: float = 0.9,
    dash_negative: bool = False,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Regular-grid isolines, optionally with a filled density surface.

    Args:
        z: Two-dimensional scalar grid or a column name.
        x: Optional x coordinates or a column name.
        y: Optional y coordinates or a column name.
        data: Table used to resolve column-name inputs.
        levels: Number or explicit values of contour levels.
        filled: Whether to fill intervals between contours.
        name: Series label used by legends and tooltips.
        colormap: Colormap used for contour values.
        color: Constant isoline color.
        width: Isoline width in pixels.
        opacity: Contour opacity from zero to one.
        dash_negative: Whether negative isolines use a dashed stroke.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="contour",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "contour style"),
        props={
            "z": z,
            "levels": levels,
            "filled": filled,
            "colormap": colormap,
            "color": color,
            "width": width,
            "opacity": opacity,
            "dash_negative": dash_negative,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def histogram(
    values: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    bins: Union[int, str, ArrayLike] = "auto",
    range: Optional[tuple[float, float]] = None,
    density: bool = False,
    cumulative: bool = False,
    name: Optional[str] = None,
    color: Any = None,
    opacity: Any = 0.85,
    corner_radius: Any = 0.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    _artist_alpha: Any = None,
    fill: Union[str, dict[str, str], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A one-dimensional histogram.

    Args:
        values: Sample values or a column name resolved from ``data``.
        data: Table used to resolve column-name inputs.
        bins: Bin count, edges, or automatic binning strategy.
        range: Explicit minimum and maximum input values.
        density: Whether to normalize bin areas to one.
        cumulative: Whether bins contain cumulative counts.
        name: Series label used by legends and tooltips.
        color: Bar color.
        opacity: Bar opacity from zero to one.
        corner_radius: Bar corner radius in pixels.
        stroke: Optional bar outline color.
        stroke_width: Bar outline width in pixels.
        _artist_alpha: Internal Matplotlib alpha override, scalar or per bin.
        fill: CSS fill value or linear gradient.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="histogram",
        x=values,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "histogram style"),
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
            "_artist_alpha": _artist_alpha,
            "fill": fill,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def hist(
    values: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    bins: Union[int, str, ArrayLike] = "auto",
    range: Optional[tuple[float, float]] = None,
    density: bool = False,
    cumulative: bool = False,
    name: Optional[str] = None,
    color: Any = None,
    opacity: Any = 0.85,
    corner_radius: Any = 0.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    _artist_alpha: Any = None,
    fill: Union[str, dict[str, str], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
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
        _artist_alpha=_artist_alpha,
        fill=fill,
        style=style,
        class_name=class_name,
        x_axis=x_axis,
        y_axis=y_axis,
    )


def bar(
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    name: Optional[str] = None,
    color: Any = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Union[str, Scalar, ArrayLike] = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: Any = 0.85,
    corner_radius: Any = 0.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    _artist_alpha: Any = None,
    fill: Union[str, dict[str, str], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A bar series supporting grouped, stacked, and normalized modes.

    Args:
        x: Category positions or a column name resolved from ``data``.
        y: Bar values, series matrix, or a column name.
        data: Table used to resolve column-name inputs.
        name: Series label used by legends and tooltips.
        color: Constant color, values, or a column name.
        colors: Colors assigned to multiple series.
        width: Bar width in category units.
        base: Baseline value, values, or a column name.
        mode: ``grouped``, ``stacked``, or ``normalized`` layout.
        orientation: ``vertical`` or ``horizontal`` orientation.
        series: Optional names for matrix-valued series.
        opacity: Bar opacity from zero to one.
        corner_radius: Bar corner radius in pixels.
        stroke: Optional bar outline color.
        stroke_width: Bar outline width in pixels.
        _artist_alpha: Internal Matplotlib alpha override, scalar or per bar.
        fill: CSS fill value or linear gradient.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="bar",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "bar style"),
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
            "_artist_alpha": _artist_alpha,
            "fill": fill,
            "x_axis": x_axis,
            "y_axis": y_axis,
        },
    )


def column(
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    *,
    data: TableLike = None,
    name: Optional[str] = None,
    color: Union[str, Sequence[str], None] = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Union[str, Scalar, ArrayLike] = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: float = 0.85,
    corner_radius: Union[float, tuple[float, float]] = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Union[str, dict[str, str], None] = None,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    key: Any = None,
    animation: Animation | bool | None = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """Create a vertical column series using the shared bar renderer.

    Args:
        x: Category positions or a column name resolved from ``data``.
        y: Column values, series matrix, or a column name.
        data: Table used to resolve column-name inputs.
        name: Series label used by legends and tooltips.
        color: Constant color, values, or a column name.
        colors: Colors assigned to multiple series.
        width: Column width in category units.
        base: Baseline value, values, or a column name.
        mode: ``grouped``, ``stacked``, or ``normalized`` layout.
        orientation: Orientation forwarded to the bar renderer.
        series: Optional names for matrix-valued series.
        opacity: Column opacity from zero to one.
        corner_radius: Column corner radius in pixels.
        stroke: Optional column outline color.
        stroke_width: Column outline width in pixels.
        fill: CSS fill value or linear gradient.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        key: Stable row identities, or a column name resolved from ``data``.
        animation: Per-mark animation override; ``False`` disables animation.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="column",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        key=key,
        animation=animation,
        style=_mark_style_dict(style, "column style"),
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
    z: Union[str, ArrayLike, None] = None,
    *,
    x: Union[str, ArrayLike, None] = None,
    y: Union[str, ArrayLike, None] = None,
    data: TableLike = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    opacity: float = 0.95,
    style: Optional[dict[str, StyleValue]] = None,
    class_name: Optional[str] = None,
    x_axis: str = "x",
    y_axis: str = "y",
) -> Mark:
    """A rectangular heatmap from a two-dimensional matrix.

    Args:
        z: Two-dimensional values or a column name resolved from ``data``.
        x: Optional x coordinates or a column name.
        y: Optional y coordinates or a column name.
        data: Table used to resolve column-name inputs.
        name: Series label used by legends and tooltips.
        colormap: Colormap used for cell values.
        domain: Explicit minimum and maximum for the color scale.
        opacity: Cell opacity from zero to one.
        style: Mark style overrides.
        class_name: Adapter-only trace metadata; it does not style canvas geometry.
        x_axis: Identifier of the x axis used by this mark.
        y_axis: Identifier of the y axis used by this mark.
    """
    return Mark(
        kind="heatmap",
        x=x,
        y=y,
        data=data,
        name=name,
        class_name=class_name,
        style=_mark_style_dict(style, "heatmap style"),
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
    x: CoordinateLike,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#667085",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A vertical rule annotation at an x coordinate or x-axis category.

    Args:
        x: X coordinate or category where the rule is drawn.
        text: Optional label displayed beside the rule.
        color: Rule color.
        width: Rule width in pixels.
        opacity: Rule opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    y: CoordinateLike,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#667085",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A horizontal rule annotation at a y coordinate or y-axis category.

    Args:
        y: Y coordinate or category where the rule is drawn.
        text: Optional label displayed beside the rule.
        color: Rule color.
        width: Rule width in pixels.
        opacity: Rule opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    x0: CoordinateLike,
    x1: CoordinateLike,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#64748b",
    opacity: float = 0.14,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A vertical span annotation between two x coordinates or categories.

    Args:
        x0: Starting x coordinate or category.
        x1: Ending x coordinate or category.
        text: Optional label displayed in the band.
        color: Band color.
        opacity: Band opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    y0: CoordinateLike,
    y1: CoordinateLike,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#64748b",
    opacity: float = 0.14,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A horizontal span annotation between two y coordinates or categories.

    Args:
        y0: Starting y coordinate or category.
        y1: Ending y coordinate or category.
        text: Optional label displayed in the band.
        color: Band color.
        opacity: Band opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    x: CoordinateLike,
    y: CoordinateLike,
    value: str,
    *,
    dx: float = 6.0,
    dy: float = -6.0,
    color: Optional[str] = None,
    anchor: str = "start",
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A text annotation anchored at an x/y coordinate or category.

    Args:
        x: Anchor x coordinate or category.
        y: Anchor y coordinate or category.
        value: Text to display.
        dx: Horizontal pixel offset from the anchor.
        dy: Vertical pixel offset from the anchor.
        color: Text color.
        anchor: Text alignment relative to the anchor point.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    x: CoordinateLike,
    y: CoordinateLike,
    value: str,
    *,
    dx: float = 6.0,
    dy: float = -6.0,
    color: Optional[str] = None,
    anchor: str = "start",
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """Create a positioned text label.

    Args:
        x: Anchor x coordinate or category.
        y: Anchor y coordinate or category.
        value: Text to display.
        dx: Horizontal pixel offset from the anchor.
        dy: Vertical pixel offset from the anchor.
        color: Text color.
        anchor: Text alignment relative to the anchor point.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    x: CoordinateLike,
    y: CoordinateLike,
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
    """A point marker annotation with an optional label.

    Args:
        x: Marker x coordinate or category.
        y: Marker y coordinate or category.
        text: Optional marker label.
        color: Marker fill color.
        size: Marker size in pixels.
        symbol: Marker symbol name.
        stroke_color: Marker outline color.
        stroke_width: Marker outline width in pixels.
        opacity: Marker opacity from zero to one.
        dx: Horizontal label offset in pixels.
        dy: Vertical label offset in pixels.
        anchor: Label alignment relative to the marker.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    x0: CoordinateLike,
    y0: CoordinateLike,
    x1: CoordinateLike,
    y1: CoordinateLike,
    *,
    text: Optional[str] = None,
    color: Optional[str] = "#667085",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """An arrow annotation from one data coordinate to another.

    Args:
        x0: Starting x coordinate or category.
        y0: Starting y coordinate or category.
        x1: Ending x coordinate or category.
        y1: Ending y coordinate or category.
        text: Optional arrow label.
        color: Arrow color.
        width: Arrow width in pixels.
        opacity: Arrow opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    value: CoordinateLike,
    *,
    axis: str = "y",
    text: Optional[str] = None,
    color: Optional[str] = "#e11d48",
    width: float = 1.5,
    opacity: float = 1.0,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A semantic threshold rule on the x or y axis.

    Args:
        value: Coordinate or category where the threshold is drawn.
        axis: Axis receiving the threshold, ``x`` or ``y``.
        text: Optional threshold label.
        color: Rule color.
        width: Rule width in pixels.
        opacity: Rule opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    start: CoordinateLike,
    end: CoordinateLike,
    *,
    axis: str = "y",
    text: Optional[str] = None,
    color: Optional[str] = "#e11d48",
    opacity: float = 0.12,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Annotation:
    """A semantic threshold band on the x or y axis.

    Args:
        start: Starting coordinate or category.
        end: Ending coordinate or category.
        axis: Axis receiving the band, ``x`` or ``y``.
        text: Optional threshold label.
        color: Band color.
        opacity: Band opacity from zero to one.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    x: CoordinateLike,
    y: CoordinateLike,
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
    """A text callout offset from a data coordinate with a pointer arrow.

    Args:
        x: Anchor x coordinate or category.
        y: Anchor y coordinate or category.
        value: Callout text.
        dx: Horizontal pixel offset from the anchor.
        dy: Vertical pixel offset from the anchor.
        color: Callout color.
        width: Pointer width in pixels.
        opacity: Callout opacity from zero to one.
        anchor: Text alignment relative to the callout point.
        class_name: DOM class name applied to the annotation.
        style: Annotation style overrides.
    """
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
    bounds: Union[tuple[float, float], Literal["data"], None] = None,
    reverse: bool = False,
    format: Optional[str] = None,
    tick_count: Optional[int] = None,
    tick_values: Union[Sequence[float], np.ndarray, None] = None,
    tick_labels: Optional[Sequence[str]] = None,
    tick_label_angle: Optional[float] = None,
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None,
    tick_label_anchor: Optional[str] = None,
    tick_label_min_gap: Optional[float] = None,
    side: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Axis:
    """Configure an x axis.

    Args:
        id: Axis identifier referenced by marks.
        label: Axis label.
        label_position: Named or structured label placement.
        label_offset: Label offset in pixels.
        label_angle: Label rotation in degrees.
        type_: Scale type, such as ``linear``, ``time``, or ``log``.
        domain: Explicit minimum and maximum scale values.
        bounds: Hard navigation limits, or ``"data"`` to use the data range.
            Pan and zoom are clamped within these limits; ``None`` leaves
            navigation unrestricted.
        reverse: Whether to reverse the scale direction.
        format: Tick-label format string.
        tick_count: Requested number of ticks.
        tick_values: Explicit tick positions.
        tick_labels: Labels corresponding to explicit tick positions.
        tick_label_angle: Tick-label rotation in degrees.
        tick_label_strategy: Collision-handling strategy for tick labels.
        tick_label_anchor: Which edge of a tick label pins to its tick —
            ``"start"``, ``"center"`` (default), or ``"end"`` (matplotlib's
            ``ha`` values ``"left"``/``"right"`` are accepted as aliases).
            With ``tick_label_angle``, the label rotates about the pinned
            edge, so an end-anchored slanted label hangs entirely below a
            bottom axis instead of seesawing around its midpoint.
        tick_label_min_gap: Minimum gap between tick labels in pixels.
        side: Side of the plot where the axis is drawn.
        style: Axis style overrides.
    """
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
        bounds=_axis_bounds(bounds, "x_axis bounds"),
        reverse=_strict_bool(reverse, "x_axis reverse"),
        format=_optional_string(format, "x_axis format"),
        tick_count=_optional_positive_int(tick_count, "x_axis tick_count"),
        tick_values=values,
        tick_labels=labels,
        tick_label_angle=_optional_finite_number(tick_label_angle, "x_axis tick_label_angle"),
        tick_label_strategy=_axis_tick_label_strategy(
            tick_label_strategy, "x_axis tick_label_strategy"
        ),
        tick_label_anchor=_axis_tick_label_anchor(tick_label_anchor, "x_axis tick_label_anchor"),
        tick_label_min_gap=_optional_nonnegative_number(
            tick_label_min_gap, "x_axis tick_label_min_gap"
        ),
        side=_axis_side(side, "x"),
        style=styles.compile_axis_style(style, "x_axis style"),
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
    bounds: Union[tuple[float, float], Literal["data"], None] = None,
    reverse: bool = False,
    format: Optional[str] = None,
    tick_count: Optional[int] = None,
    tick_values: Union[Sequence[float], np.ndarray, None] = None,
    tick_labels: Optional[Sequence[str]] = None,
    tick_label_angle: Optional[float] = None,
    tick_label_strategy: Optional[AxisTickLabelStrategy] = None,
    tick_label_anchor: Optional[str] = None,
    tick_label_min_gap: Optional[float] = None,
    side: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Axis:
    """Configure a y axis.

    Args:
        id: Axis identifier referenced by marks.
        label: Axis label.
        label_position: Named or structured label placement.
        label_offset: Label offset in pixels.
        label_angle: Label rotation in degrees.
        type_: Scale type, such as ``linear``, ``time``, or ``log``.
        domain: Explicit minimum and maximum scale values.
        bounds: Hard navigation limits, or ``"data"`` to use the data range.
            Pan and zoom are clamped within these limits; ``None`` leaves
            navigation unrestricted.
        reverse: Whether to reverse the scale direction.
        format: Tick-label format string.
        tick_count: Requested number of ticks.
        tick_values: Explicit tick positions.
        tick_labels: Labels corresponding to explicit tick positions.
        tick_label_angle: Tick-label rotation in degrees.
        tick_label_strategy: Collision-handling strategy for tick labels.
        tick_label_anchor: Which edge of a tick label pins to its tick —
            ``"start"``, ``"center"``, or ``"end"`` (matplotlib's ``ha``
            values ``"left"``/``"right"`` are accepted as aliases). Unset
            defaults to the tick-side edge: ``"end"`` for a left-side axis,
            ``"start"`` for a right-side one. With ``tick_label_angle``,
            the label rotates about the pinned edge.
        tick_label_min_gap: Minimum gap between tick labels in pixels.
        side: Side of the plot where the axis is drawn.
        style: Axis style overrides.
    """
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
        bounds=_axis_bounds(bounds, "y_axis bounds"),
        reverse=_strict_bool(reverse, "y_axis reverse"),
        format=_optional_string(format, "y_axis format"),
        tick_count=_optional_positive_int(tick_count, "y_axis tick_count"),
        tick_values=values,
        tick_labels=labels,
        tick_label_angle=_optional_finite_number(tick_label_angle, "y_axis tick_label_angle"),
        tick_label_strategy=_axis_tick_label_strategy(
            tick_label_strategy, "y_axis tick_label_strategy"
        ),
        tick_label_anchor=_axis_tick_label_anchor(tick_label_anchor, "y_axis tick_label_anchor"),
        tick_label_min_gap=_optional_nonnegative_number(
            tick_label_min_gap, "y_axis tick_label_min_gap"
        ),
        side=_axis_side(side, "y"),
        style=styles.compile_axis_style(style, "y_axis style"),
    )


def legend(
    *children: Any,
    show: bool = True,
    loc: Optional[str] = None,
    ncols: int = 1,
    title: Optional[str] = None,
    render: Any = None,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Legend:
    """Configure chart legend chrome.

    Args:
        *children: Optional opaque replacement content.
        show: Whether to display the legend.
        loc: Legend placement within or around the plot.
        ncols: Number of legend columns.
        title: Optional legend title.
        render: Opaque renderer supplied by an adapter.
        class_name: DOM class name applied to the legend.
        style: Legend style overrides.
    """
    show, render = _chrome_render_args(children, show, render, "legend")
    return Legend(
        show=_strict_bool(show, "legend show"),
        loc=_optional_string(loc, "legend loc"),
        ncols=_optional_positive_int(ncols, "legend ncols") or 1,
        title=_optional_string(title, "legend title"),
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
    """Configure chart tooltip chrome.

    Args:
        *children: Optional opaque replacement content.
        show: Whether to display tooltips.
        render: Opaque renderer supplied by an adapter.
        fields: Data fields shown in each tooltip.
        title: Optional tooltip title.
        format: Per-field value formats.
        class_name: DOM class name applied to the tooltip.
        style: Tooltip style overrides.
    """
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


def colorbar(
    *children: Any,
    show: bool = True,
    render: Any = None,
    title: Optional[str] = None,
    orientation: str = "vertical",
    ticks: Optional[list[float]] = None,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
) -> Colorbar:
    """Configure color-scale chrome.

    Args:
        *children: Optional opaque replacement content.
        show: Whether to display the colorbar.
        render: Opaque renderer supplied by an adapter.
        title: Optional colorbar title. By default XY uses the color field or
            mark name when one is available.
        orientation: ``vertical`` or ``horizontal`` placement.
        ticks: Optional finite numeric tick positions.
        class_name: DOM class name applied to the colorbar.
        style: Colorbar style overrides.
    """
    show, render = _chrome_render_args(children, show, render, "colorbar")
    show, title, orientation, ticks, class_name, style = _validated_colorbar_fields(
        show, title, orientation, ticks, class_name, style
    )
    return Colorbar(
        show=show,
        title=title,
        orientation=orientation,
        ticks=ticks,
        class_name=class_name,
        style=style,
        render=render,
    )


def _validated_colorbar_fields(
    show: Any,
    title: Any,
    orientation: Any,
    ticks: Any,
    class_name: Any,
    style: Any,
) -> tuple[
    bool,
    Optional[str],
    str,
    Optional[list[float]],
    Optional[str],
    dict[str, StyleValue],
]:
    """Validate the public ``Colorbar`` fields; the single validation body.

    Called by the ``colorbar()`` factory and by Chart's apply path, so a
    directly constructed ``Colorbar`` node cannot put malformed chrome
    options on the wire.
    """
    return (
        _strict_bool(show, "colorbar show"),
        _optional_string(title, "colorbar title"),
        _colorbar_orientation(orientation),
        _colorbar_ticks(ticks),
        _optional_string(class_name, "colorbar class_name"),
        _style_dict(style, "colorbar style"),
    )


def _colorbar_orientation(value: Any) -> str:
    if not isinstance(value, str) or value not in {"vertical", "horizontal"}:
        raise ValueError("colorbar orientation must be 'vertical' or 'horizontal'")
    return value


def _colorbar_ticks(value: Any) -> Optional[list[float]]:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise ValueError("colorbar ticks must be an iterable of finite numbers or None")
    try:
        return [_finite_number(tick, "colorbar tick") for tick in value]
    except TypeError as exc:
        raise ValueError("colorbar ticks must be an iterable of finite numbers or None") from exc


def modebar(
    show: bool = True,
    *,
    class_name: Optional[str] = None,
    style: Optional[dict[str, StyleValue]] = None,
    button_class_name: Optional[str] = None,
    button_style: Optional[dict[str, StyleValue]] = None,
) -> Modebar:
    """Configure interactive chart controls.

    Args:
        show: Whether to display the modebar.
        class_name: DOM class name applied to the modebar.
        style: Modebar style overrides.
        button_class_name: DOM class name applied to each button.
        button_style: Style overrides applied to each button.
    """
    return Modebar(
        show=_strict_bool(show, "modebar show"),
        class_name=_optional_string(class_name, "modebar class_name"),
        style=_style_dict(style, "modebar style"),
        button_class_name=_optional_string(button_class_name, "modebar button_class_name"),
        button_style=_style_dict(button_style, "modebar button_style"),
    )


# Everything `export_config(formats=...)` accepts: the unified image matrix
# plus the non-image exports. The browser modebar shows the client-safe subset
# (png/jpeg/webp/svg/csv) in the configured order; pdf/html entries govern the
# Python-side defaults only.
_EXPORT_CONFIG_FORMATS = ("png", "jpeg", "webp", "svg", "pdf", "csv", "html")
_EXPORT_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


def export_config(
    formats: Optional[Sequence[str]] = None,
    *,
    filename: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: Optional[float] = None,
    background: Optional[str] = None,
    quality: Optional[int] = None,
) -> ExportConfig:
    """Describe export defaults as part of the chart (no I/O at build time).

    Args:
        formats: Download formats, in menu order. The modebar shows the
            client-safe subset (png/jpeg/webp/svg/csv); an empty list hides
            the download menu entirely. Also the default format list for
            batch export helpers.
        filename: Download/file basename (no extension or path separators).
        width: Default export width in pixels.
        height: Default export height in pixels.
        scale: Default device-pixel-ratio for raster export.
        background: Default export background ("auto", a CSS color, or
            "transparent"; JPEG rejects transparent at export time).
        quality: Default JPEG/lossy-WebP quality (1-100).
    """
    validated_formats: Optional[tuple[str, ...]] = None
    if formats is not None:
        if isinstance(formats, str):
            raise ValueError("export_config formats must be a sequence of format names")
        seen: list[str] = []
        for value in formats:
            fmt = export._FORMAT_ALIASES.get(str(value).lower(), str(value).lower())
            if fmt not in _EXPORT_CONFIG_FORMATS:
                raise ValueError(
                    f"export_config format must be one of {_EXPORT_CONFIG_FORMATS}, got {value!r}"
                )
            if fmt in seen:
                raise ValueError(f"export_config formats repeats {fmt!r}")
            seen.append(fmt)
        validated_formats = tuple(seen)
    if filename is not None:
        filename = _optional_string(filename, "export_config filename") or ""
        if not _EXPORT_FILENAME_RE.fullmatch(filename):
            raise ValueError(
                "export_config filename must be a plain basename "
                f"(letters/digits/dot/dash/underscore/space), got {filename!r}"
            )
    if quality is not None and (
        isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100
    ):
        raise ValueError(f"export_config quality must be an integer in 1..100, got {quality!r}")
    return ExportConfig(
        formats=validated_formats,
        filename=filename,
        width=None if width is None else export._positive_pixel_count(width, "export width"),
        height=None if height is None else export._positive_pixel_count(height, "export height"),
        scale=None if scale is None else export._positive_finite_float(scale, "export scale"),
        background=None if background is None else _export_background(background),
        quality=quality,
    )


def _export_background(background: str) -> str:
    if not isinstance(background, str) or not background.strip():
        raise ValueError(f"export_config background must be a CSS color string, got {background!r}")
    value = background.strip()
    if value != "auto" and not export._BACKGROUND_RE.fullmatch(value):
        raise ValueError(f"export_config background is not a safe CSS color: {background!r}")
    return value


def theme(
    style: Optional[dict[str, StyleValue]] = None,
    *,
    background: Optional[StyleValue] = None,
    plot_background: Optional[StyleValue] = None,
    grid_color: Optional[StyleValue] = None,
    axis_color: Optional[StyleValue] = None,
    text_color: Optional[StyleValue] = None,
    crosshair_color: Optional[StyleValue] = None,
    selection_color: Optional[StyleValue] = None,
    selection_fill: Optional[StyleValue] = None,
    **tokens: StyleValue,
) -> Theme:
    """Configure chart theme tokens.

    Args:
        style: Base chart style overrides.
        background: Figure background color — paints the whole chart card
            including margins, title, and tick labels (matplotlib's
            ``figure.facecolor``). The plot rect shows through unless
            ``plot_background`` sets it separately.
        plot_background: Plot-area background color — the data rect only
            (matplotlib's ``axes.facecolor``).
        grid_color: Grid-line color.
        axis_color: Axis-line and tick color.
        text_color: Default chart text color.
        crosshair_color: Hover crosshair color.
        selection_color: Selection-outline color.
        selection_fill: Selection-region fill color.
        **tokens: Additional supported theme tokens.
    """
    merged = _style_dict(style, "theme style")
    merged.update(
        _theme_tokens(
            {
                "background": background,
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


def interaction_config(
    *,
    hover: Optional[bool] = None,
    click: Optional[bool] = None,
    select: Optional[bool] = None,
    brush: Optional[bool] = None,
    crosshair: Optional[bool] = None,
    navigation: Optional[bool] = None,
    pan: Optional[bool] = None,
    zoom: Optional[bool] = None,
    view_change: Optional[bool] = None,
    link_group: Optional[str] = None,
    link_axes: tuple[str, ...] = ("x", "y"),
) -> Interaction:
    """Configure browser interaction chrome and event emission.

    Args:
        hover: Whether pointer movement emits hover events.
        click: Whether picked marks emit click events.
        select: Whether shift-drag box selection is enabled.
        brush: Whether brush selection is enabled.
        crosshair: Whether plot-aligned hover guides are shown.
        navigation: Whether pointer drag and wheel gestures pan or zoom the chart.
        pan: Whether plain-drag pan is enabled. ``False`` ignores plain-drag
            pan gestures. The default keeps panning enabled.
        zoom: Whether viewport zoom is enabled. ``False`` ignores wheel and
            box zoom, double-click reset, and modebar zoom controls. The
            default keeps zooming enabled.
        view_change: Whether pan, zoom, and reset emit range events.
        link_group: Identifier used to synchronize charts in the browser.
        link_axes: Axes synchronized within the link group.
    """
    return Interaction(
        hover=hover,
        click=click,
        select=select,
        brush=brush,
        crosshair=crosshair,
        navigation=navigation,
        pan=pan,
        zoom=zoom,
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
        padding: Union[
            float, Sequence[float], None
        ] = None,  # plot margins; 0 = edge-to-edge sparkline
        data: TableLike = None,
        class_name: Optional[str] = None,
        class_names: Optional[dict[str, str]] = None,
        style: Optional[dict[str, StyleValue]] = None,
        styles: Optional[dict[str, dict[str, StyleValue]]] = None,
        on_hover: Optional[Callable[[dict], None]] = None,
        on_click: Optional[Callable[[dict], None]] = None,
        on_brush: Optional[Callable[[dict], None]] = None,
        on_select: Optional[Callable[[Selection], None]] = None,
        on_view_change: Optional[Callable[[dict], None]] = None,
        hover: Optional[bool] = None,
        click: Optional[bool] = None,
        select: Optional[bool] = None,
        brush: Optional[bool] = None,
        crosshair: Optional[bool] = None,
        navigation: Optional[bool] = None,
        pan: Optional[bool] = None,
        zoom: Optional[bool] = None,
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
        self.navigation = navigation
        self.pan = pan
        self.zoom = zoom
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
        colorbars = [c for c in self.children if isinstance(c, Colorbar)]
        modebars = [c for c in self.children if isinstance(c, Modebar)]
        export_configs = [c for c in self.children if isinstance(c, ExportConfig)]
        themes = [c for c in self.children if isinstance(c, Theme)]
        interactions = [c for c in self.children if isinstance(c, Interaction)]
        animations = [c for c in self.children if isinstance(c, Animation)]
        legend_shows = [_strict_bool(c.show, "legend show") for c in legends]
        known = (
            Mark,
            Annotation,
            Axis,
            Legend,
            Tooltip,
            Colorbar,
            Modebar,
            ExportConfig,
            Theme,
            Interaction,
            Animation,
        )
        unknown = [c for c in self.children if not isinstance(c, known)]
        if unknown:
            raise TypeError(
                f"{self.kind}() children must be marks/annotations/axes/legend/tooltip/"
                f"colorbar/modebar/export_config/theme/interaction_config/animation, got "
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
                bounds=axis.bounds,
                reverse=axis.reverse,
                format=axis.format,
                tick_count=axis.tick_count,
                tick_values=axis.tick_values,
                tick_labels=axis.tick_labels,
                tick_label_angle=axis.tick_label_angle,
                tick_label_strategy=axis.tick_label_strategy,
                tick_label_anchor=axis.tick_label_anchor,
                tick_label_min_gap=axis.tick_label_min_gap,
                side=axis.side,
                style=axis.style,
            )
        # Facet builds pre-seed the union category order (set as a private
        # attribute by FacetChart) so shared categorical domains align the
        # same categories at the same positions across panels; positions are
        # committed at ingest, so this must land before the marks apply.
        for axis_id, categories in self._facet_axis_categories.items():
            fig._axis_categories[axis_id] = list(categories)
        fig.class_name = self.class_name
        fig.class_names = dict(self.class_names)
        fig.style = {}
        for theme_node in themes:
            fig.style.update(theme_node.style)
        fig.style.update(self.style)
        chart_animation = animations[-1] if animations else None
        if chart_animation is not None:
            fig.animation_options = chart_animation.to_spec()
        for slot, slot_style in self.styles.items():
            fig.chrome_styles[slot] = {**fig.chrome_styles.get(slot, {}), **slot_style}
        if (
            self.hover is not None
            or self.click is not None
            or self.select is not None
            or self.brush is not None
            or self.crosshair is not None
            or self.navigation is not None
            or self.pan is not None
            or self.zoom is not None
            or self.view_change is not None
            or self.link_group is not None
        ):
            fig.set_interaction(
                hover=self.hover,
                click=self.click,
                select=self.select,
                brush=self.brush,
                crosshair=self.crosshair,
                navigation=self.navigation,
                pan=self.pan,
                zoom=self.zoom,
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
                navigation=node.navigation,
                pan=node.pan,
                zoom=node.zoom,
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
        colorbar_candidates: list[dict[str, Any]] = []
        for m in marks:
            data = m.data if m.data is not None else self.data
            applier = _MARK_APPLIERS.get(m.kind)
            if applier is None:
                raise TypeError(f"no applier registered for mark kind {m.kind!r}")
            x_axis_id, y_axis_id = _mark_axis_ids(m, axes)
            before = len(fig.traces)
            previous_axis_ids = fig._active_axis_ids
            fig._active_axis_ids = {"x": x_axis_id, "y": y_axis_id}
            try:
                applier(fig, m, data)
            finally:
                fig._active_axis_ids = previous_axis_ids
            new_traces = fig.traces[before:]
            for trace in new_traces:
                trace.x_axis = x_axis_id
                trace.y_axis = y_axis_id
            _apply_mark_transition_metadata(
                fig,
                m,
                data,
                new_traces,
                fig.animation_options,
            )
            if m.class_name is not None:
                class_name = _optional_string(m.class_name, f"{m.kind} class_name")
                for trace in new_traces:
                    trace.style["class_name"] = class_name
            _merge_tooltip_aliases(tooltip_aliases, m, new_traces)
            _merge_tooltip_sources(tooltip_sources, m, new_traces)
            colorbar_candidate = _declarative_colorbar_options(m, new_traces)
            if colorbar_candidate is not None:
                colorbar_candidates.append(colorbar_candidate)

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
            if node.title is not None:
                fig.legend_options["title"] = node.title
            if node.style:
                # Carry the frame/frameon styling into the static-export spec so
                # the raster/SVG legend can honor frameon=False (transparent bg).
                fig.legend_options["style"] = dict(node.style)
        if legend_shows and not legend_shows[-1]:
            fig.show_legend = False
        if modebars:
            node = modebars[-1]
            _apply_chrome_node(fig, "modebar", node.class_name, node.style)
            _apply_chrome_node(fig, "modebar_button", node.button_class_name, node.button_style)
            fig.show_modebar = node.show
        if export_configs:
            node = export_configs[-1]
            # Re-validate: ``ExportConfig`` is a public dataclass as well as
            # the `export_config()` return type, so direct construction must
            # not put malformed options on the wire.
            validated = export_config(
                formats=node.formats,
                filename=node.filename,
                width=node.width,
                height=node.height,
                scale=node.scale,
                background=node.background,
                quality=node.quality,
            )
            export_options: dict[str, Any] = {}
            if validated.formats is not None:
                export_options["formats"] = list(validated.formats)
            for key in ("filename", "width", "height", "scale", "background", "quality"):
                value = getattr(validated, key)
                if value is not None:
                    export_options[key] = value
            fig.export_options = export_options or None
        if tooltips:
            node = tooltips[-1]
            _apply_chrome_node(fig, "tooltip", node.class_name, node.style)
            fig.show_tooltip = node.show
            fig.tooltip = _tooltip_spec(node, tooltip_aliases, tooltip_sources)
        if colorbars:
            node = colorbars[-1]
            # ``Colorbar`` is a public dataclass as well as the return type of
            # ``colorbar()``. Re-run the shared validators here so direct
            # construction cannot put malformed chrome options on the wire.
            (
                node_show,
                node_title,
                node_orientation,
                node_ticks,
                node_class_name,
                node_style,
            ) = _validated_colorbar_fields(
                node.show,
                node.title,
                node.orientation,
                node.ticks,
                node.class_name,
                node.style,
            )
            _apply_chrome_node(fig, "colorbar", node_class_name, node_style)
            if not node_show:
                fig.colorbar_options = None
            elif node.render is None:
                options = (
                    dict(colorbar_candidates[-1])
                    if colorbar_candidates
                    else (dict(fig.colorbar_options) if fig.colorbar_options else None)
                )
                if options is not None:
                    options["orientation"] = node_orientation
                    if node_title is not None:
                        options["label"] = node_title
                    if node_ticks is not None:
                        options["ticks"] = node_ticks
                    fig.colorbar_options = options
        self._figure = fig
        return fig

    # -- render (delegates to the engine) ------------------------------------

    def chrome_components(self) -> dict[str, Any]:
        """Opaque user chrome objects for adapters such as Reflex.

        Core xy does not import or serialize framework components. The
        objects returned here are the exact Python objects passed to
        `xy.legend(...)` / `xy.tooltip(...)` / `xy.colorbar(...)`, so an adapter can mount them while
        standalone HTML keeps using the built-in safe DOM fallback.
        """
        result: dict[str, Any] = {}
        legends = [c for c in self.children if isinstance(c, Legend)]
        if legends and legends[-1].render is not None:
            result["legend"] = legends[-1].render
        tooltips = [c for c in self.children if isinstance(c, Tooltip)]
        if tooltips and tooltips[-1].render is not None:
            result["tooltip"] = tooltips[-1].render
        colorbars = [c for c in self.children if isinstance(c, Colorbar)]
        if colorbars and colorbars[-1].render is not None:
            result["colorbar"] = colorbars[-1].render
        return result

    def reflex_components(self) -> dict[str, Any]:
        """Alias for `chrome_components()` for Reflex adapter/user code."""
        return self.chrome_components()

    def widget(self) -> Any:
        """The live notebook widget for this chart (built once, cached).

        Requires the widget extras (anywidget); event callbacks passed to
        the chart are wired onto it.
        """
        if self._widget is None:
            from .widget import FigureWidget

            animations = [c for c in self.children if isinstance(c, Animation)]
            animation_node = animations[-1] if animations else None
            mark_animations = [
                c.animation
                for c in self.children
                if isinstance(c, Mark) and isinstance(c.animation, Animation)
            ]

            def animation_callback(name: str) -> Optional[Callable[[dict], None]]:
                callbacks = []
                if animation_node is not None:
                    callback = getattr(animation_node, name)
                    if callback is not None:
                        callbacks.append(callback)
                for node in mark_animations:
                    callback = getattr(node, name)
                    if callback is not None and callback not in callbacks:
                        callbacks.append(callback)
                if not callbacks:
                    return None

                def dispatch(event: dict) -> None:
                    for callback in callbacks:
                        callback(event)

                return dispatch

            widget_kwargs: dict[str, Any] = {
                "on_hover": self.on_hover,
                "on_click": self.on_click,
                "on_brush": self.on_brush,
                "on_select": self.on_select,
                "on_view_change": self.on_view_change,
            }
            on_animation_start = animation_callback("on_start")
            on_animation_end = animation_callback("on_end")
            if on_animation_start is not None:
                widget_kwargs["on_animation_start"] = on_animation_start
            if on_animation_end is not None:
                widget_kwargs["on_animation_end"] = on_animation_end
            self._widget = FigureWidget(self.figure(), **widget_kwargs)
        return self._widget

    def show(self) -> Any:
        """Display the chart: returns the live widget (see `widget`)."""
        return self.widget()

    def _ipython_display_(self) -> None:
        from IPython.display import display  # type: ignore[import-not-found]

        display(self.widget())

    def to_html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
        animation_progress: Optional[float] = None,
    ) -> str:
        """A self-contained HTML document for the chart.

        Writes it to ``path`` when given; returns the HTML either way.
        """
        return self.figure().to_html(
            path,
            custom_css=custom_css,
            animation_progress=animation_progress,
        )

    def html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
        animation_progress: Optional[float] = None,
    ) -> str:
        """Alias of `to_html`."""
        return self.to_html(
            path,
            custom_css=custom_css,
            animation_progress=animation_progress,
        )

    def _repr_html_(self) -> str:
        return self.figure()._repr_html_()

    def to_svg(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> str:
        """A static SVG render of the chart (written to ``path`` if given)."""
        return self.figure().to_svg(path, width=width, height=height)

    def to_png(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        engine: export.Engine = export.Engine.default,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """A PNG render of the chart, returned as bytes.

        ``scale`` multiplies the pixel density; ``engine`` picks the
        raster path (native or headless Chromium). Written to ``path``
        when given.
        """
        return self.figure().to_png(
            path,
            width=width,
            height=height,
            scale=scale,
            engine=engine,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def _export_defaults(
        self,
        fmt: str,
        width: Optional[int],
        height: Optional[int],
        scale: Optional[float],
        background: Optional[str],
        quality: Optional[int],
        *,
        lossy_webp: bool = False,
    ) -> dict[str, Any]:
        """Fill omitted export options from the chart's `export_config`.

        Direct arguments always win. Declarative defaults degrade gracefully
        where a format cannot honor them (config quality applies only where
        output is actually lossy — JPEG, plus WebP when the resolved engine
        is Chromium; a config "transparent" background is dropped for JPEG)
        — only *explicit* arguments produce hard errors downstream."""
        config = self.figure().export_options or {}
        if quality is None and (fmt == "jpeg" or (fmt == "webp" and lossy_webp)):
            quality = config.get("quality")
        if background is None:
            background = config.get("background")
            if background == "auto" or (background == "transparent" and fmt == "jpeg"):
                background = None
        return {
            "width": width if width is not None else config.get("width"),
            "height": height if height is not None else config.get("height"),
            "scale": scale if scale is not None else config.get("scale", 2.0),
            "background": background,
            "quality": quality,
        }

    def to_image(
        self,
        format: str = "png",
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: Optional[float] = None,
        background: Optional[str] = None,
        engine: export.Engine | str = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Unified static export: PNG/JPEG/WebP/SVG/PDF bytes.

        Omitted width/height/scale/background/quality fall back to the
        chart's `export_config` defaults; explicit arguments override them.
        See `export.to_image` for the full format/engine/background policy."""
        fmt = export._normalize_format(format)
        resolved = export._resolve_image_engine(engine, fmt, custom_css)
        return self.figure().to_image(
            format,
            engine=engine,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
            **self._export_defaults(
                fmt,
                width,
                height,
                scale,
                background,
                quality,
                lossy_webp=resolved == "browser",
            ),
        )

    def write_image(
        self,
        path: str | PathLike[str],
        *,
        format: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: Optional[float] = None,
        background: Optional[str] = None,
        engine: export.Engine | str = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Atomic file export with extension-inferred format (.png/.jpg/
        .jpeg/.webp/.svg/.pdf/.html). `export_config` defaults apply as in
        `to_image`; explicit arguments override them."""
        fmt = (
            export._normalize_format(format, allow_html=True)
            if format is not None
            else export._infer_format(path)
        )
        if fmt != "html":
            resolved = export._resolve_image_engine(engine, fmt, custom_css)
            defaults = self._export_defaults(
                fmt,
                width,
                height,
                scale,
                background,
                quality,
                lossy_webp=resolved == "browser",
            )
        if fmt == "html":
            # HTML routing rejects raster-only options; forward the user's own
            # arguments (not the declarative defaults) so that rejection
            # applies to what was actually passed.
            return self.figure().write_image(
                path,
                format=format,
                width=width,
                height=height,
                scale=scale if scale is not None else 2.0,
                background=background,
                engine=engine,
                quality=quality,
                optimize=optimize,
                custom_css=custom_css,
                sandbox=sandbox,
                gl=gl,
            )
        return self.figure().write_image(
            path,
            format=format,
            engine=engine,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
            **defaults,
        )

    def memory_report(self) -> dict[str, Any]:
        """Byte-level accounting of the chart's data and cache buffers."""
        return self.figure().memory_report()

    # -- live data (structure-immutable: build a new chart for new marks) ----

    def append(
        self,
        trace_id: int,
        x: ArrayLike,
        y: ArrayLike,
        *,
        color: Optional[ArrayLike] = None,
        size: Optional[ArrayLike] = None,
    ) -> None:
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


def _transition_key_token(value: Any, index: int) -> bytes:
    """Canonical, type-sensitive bytes for one supported stable key."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value.__class__.__name__ in {"NAType", "NaTType"}:
        raise ValueError(f"animation key is missing at row {index}")
    if isinstance(value, bool):
        return b"b:1" if value else b"b:0"
    if isinstance(value, int):
        return f"i:{value}".encode("ascii")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"animation key must be finite at row {index}")
        return b"f:" + value.hex().encode("ascii")
    if isinstance(value, str):
        return b"s:" + value.encode("utf-8")
    if isinstance(value, bytes):
        return b"y:" + value
    if isinstance(value, (dt.datetime, dt.date)):
        return ("t:" + value.isoformat()).encode("utf-8")
    raise ValueError(
        "animation key values must be strings, finite numbers, booleans, bytes, or dates; "
        f"row {index} has {type(value).__name__}"
    )


def _encode_transition_keys(value: Any, expected: int, label: str) -> np.ndarray:
    arr = np.asarray(value, dtype=object)
    if arr.ndim != 1:
        raise ValueError(f"{label} must be one-dimensional")
    if len(arr) != expected:
        raise ValueError(f"{label} must have length {expected}, got {len(arr)}")
    result = np.empty((expected, 2), dtype=np.uint32)
    seen: dict[bytes, int] = {}
    digests: dict[bytes, bytes] = {}
    for index, raw in enumerate(arr):
        token = _transition_key_token(raw, index)
        previous = seen.get(token)
        if previous is not None:
            raise ValueError(f"{label} contains duplicate value at rows {previous} and {index}")
        seen[token] = index
        digest = hashlib.blake2s(token, digest_size=8, person=b"xykeyv1").digest()
        collision = digests.get(digest)
        if collision is not None and collision != token:
            raise ValueError(f"{label} produced an identity digest collision")
        digests[digest] = token
        result[index, 0] = int.from_bytes(digest[:4], "little")
        result[index, 1] = int.from_bytes(digest[4:], "little")
    return result


def _original_mark_positions(
    fig: Figure, mark: Mark, data: Any, expected: int
) -> np.ndarray | None:
    """Return pre-sort numeric x positions for sorted line-like marks."""
    try:
        raw = _resolve(data, mark.x, context=f"{mark.kind}.x")
        arr = np.asarray(raw)
    except (TypeError, ValueError, KeyError):
        return None
    if arr.ndim != 1 or len(arr) != expected:
        return None
    if np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.datetime64):
        try:
            return (
                arr.astype("datetime64[ns]").astype(np.int64)
                if np.issubdtype(arr.dtype, np.datetime64)
                else arr.astype(np.float64)
            )
        except (TypeError, ValueError):
            return None
    axis_id = str(mark.props.get("x_axis", "x"))
    categories = fig._axis_categories.get(axis_id, [])
    lookup = {value: i for i, value in enumerate(categories)}
    try:
        return np.asarray([lookup[value] for value in arr], dtype=np.float64)
    except (KeyError, TypeError):
        return None


def _apply_mark_transition_metadata(
    fig: Figure,
    mark: Mark,
    data: Any,
    traces: list[Any],
    chart_spec: Optional[dict[str, Any]],
) -> None:
    override = mark.animation
    if override is None:
        mark_spec = None
    elif isinstance(override, bool):
        mark_spec = {"enabled": override}
    elif isinstance(override, Animation):
        mark_spec = override.to_spec()
    else:
        raise ValueError(f"{mark.kind} animation must be xy.animation(...), bool, or None")
    effective = {**(chart_spec or {}), **(mark_spec or {})}
    if (
        effective.get("enabled") is not False
        and effective.get("match") == "key"
        and mark.key is None
    ):
        raise ValueError(f"{mark.kind} animation match='key' requires key=")
    keys: np.ndarray | None = None
    if mark.key is not None:
        raw = (
            _resolve(data, mark.key, context=f"{mark.kind}.key")
            if isinstance(mark.key, str)
            else mark.key
        )
        if not traces:
            raise ValueError(
                f"{mark.kind} key cannot be attached because the mark emitted no traces"
            )
        expected = int(traces[0].n_points)
        keys = _encode_transition_keys(raw, expected, f"{mark.kind} key")
        if mark.kind in {"line", "area", "error_band"}:
            positions = _original_mark_positions(fig, mark, data, expected)
            if positions is not None:
                keys = keys[np.argsort(positions, kind="stable")]
    for trace in traces:
        trace.animation = None if mark_spec is None else dict(mark_spec)
        if keys is not None:
            if trace.n_points != len(keys):
                raise ValueError(
                    f"{mark.kind} key has {len(keys)} rows but emitted trace {trace.id} "
                    f"has {trace.n_points} logical rows"
                )
            trace.transition_keys = keys


def _colorbar_source_title(mark: Mark) -> Optional[str]:
    """Human-readable title for the scalar channel represented by a mark.

    Column-name channels are more precise than a trace name (a scatter named
    ``"observations"`` can still be colored by ``"temperature"``). For
    array-backed scalar fields the mark name is the only declarative label.
    Hexbin's implicit metric is named explicitly because it is derived rather
    than supplied by the caller.
    """
    if mark.kind in {"scatter", "segments", "triangle_mesh"}:
        color = mark.props.get("color")
        if isinstance(color, str) and not _looks_like_css(color):
            return color
    elif mark.kind in {"heatmap", "contour"}:
        z = mark.props.get("z")
        if isinstance(z, str):
            return z
    elif mark.kind == "hexbin":
        values = mark.props.get("C")
        if isinstance(values, str):
            return values
        if values is None:
            return "log(count + 1)" if mark.props.get("bins") == "log" else "count"
    return mark.name


def _declarative_colorbar_options(mark: Mark, traces: list[Any]) -> Optional[dict[str, Any]]:
    """Infer built-in colorbar metadata from the mark's compiled scalar channel.

    The compiled trace is authoritative: it owns the post-validation domain
    and colormap and distinguishes continuous, categorical, constant, and
    true-color channels. A mark can expand to multiple traces, so the last
    compatible trace mirrors the chart's last-mappable-wins composition rule.
    """
    options: Optional[dict[str, Any]] = None
    for trace in traces:
        if trace.kind == "heatmap":
            if trace.style.get("truecolor"):
                continue
            domain = trace.style.get("domain")
            colormap = trace.style.get("colormap")
        else:
            channel = trace.color_ch
            if channel is None or channel.mode != "continuous":
                continue
            # A density-tier scatter colors aggregate counts; its original
            # per-row color channel is explicitly dropped, so advertising that
            # channel's domain beside the density ramp would be misleading.
            if trace.kind == "scatter" and trace.use_density():
                continue
            domain = channel.domain
            colormap = channel.colormap
        if domain is None or colormap is None:
            continue
        options = {
            "domain": [float(domain[0]), float(domain[1])],
            "colormap": str(colormap),
        }

    if options is None:
        return None
    title = _colorbar_source_title(mark)
    if title is not None:
        options["label"] = title
    if mark.kind == "contour" and mark.props.get("filled"):
        levels = mark.props.get("levels")
        if isinstance(levels, (int, np.integer)):
            count = int(levels)
        elif levels is None:
            count = 0
        else:
            try:
                count = len(levels)
            except TypeError:
                count = 0
        # Filled contour intervals lie between adjacent level boundaries.
        if count > 1:
            options["levels"] = count - 1
    return options


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


def _mark_style_dict(value: Any, label: str) -> dict[str, StyleValue]:
    return styles.normalize_css_style(value, label)


def _slot_styles_dict(value: Any, label: str) -> dict[str, dict[str, StyleValue]]:
    """Per-slot inline styles (`styles={slot: {...}}` — spec/api/styling.md's
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
    # `background` intentionally has no token alias: it passes through as the
    # root element's CSS background, painting the whole figure — margins,
    # title, tick labels — not just the plot rect (mpl figure.facecolor vs
    # axes.facecolor). Static exporters honor the same key.
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
        style=mark.style,
        props=mark.props,
    )


class FacetChart(Component):
    """Composition wrapper for a chart repeated over a table column."""

    def __init__(
        self,
        children: tuple[Component, ...],
        *,
        by: Union[str, ArrayLike, None],
        cols: int = 3,
        share_x: bool = True,
        share_y: bool = True,
        link: Optional[Union[str, bool]] = None,
        link_select: bool = False,
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
        if isinstance(link, (bool, np.bool_)):
            link = "both" if bool(link) else None
        elif link not in (None, "x", "y", "both"):
            raise ValueError("facet_chart link must be True, False, None, 'x', 'y', or 'both'")
        self.link = link
        self.link_select = _strict_bool(link_select, "facet_chart link_select")
        self.gap = int(gap)
        self.props = dict(props)
        self._grid: Any = None

    def figure(self) -> Any:
        """The composed `FacetGrid` of per-panel figures (built once, cached)."""
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
        linked_dims = (
            [] if self.link is None else [self.link] if self.link != "both" else ["x", "y"]
        )
        # A linked dimension must start from the same domain; otherwise the
        # first interaction would make panels jump from incomparable views.
        shared_dims = [
            dim
            for dim, shared in (("x", self.share_x), ("y", self.share_y))
            if shared or dim in linked_dims
        ]
        shared_axis_ids = [
            axis_id
            for dim in shared_dims
            for axis_id in dict.fromkeys(
                axis_id
                for fig in figures
                for axis_id in fig.axis_options
                if fig._axis_dim(axis_id) == dim
            )
        ]
        unshareable: set[str] = set()
        preseed: dict[str, list[str]] = {}
        for axis_id in shared_axis_ids:
            per_panel = [fig._axis_categories.get(axis_id) for fig in figures]
            if all(categories is None for categories in per_panel):
                continue
            if any(categories is None for categories in per_panel):
                warnings.warn(
                    f"facet_chart cannot share the {axis_id} axis: the {axis_id} channel is "
                    "categorical in some panels but numeric in others; skipping "
                    f"{axis_id} domain sharing",
                    UserWarning,
                    stacklevel=2,
                )
                unshareable.add(axis_id)
                continue
            union: list[str] = []
            seen: set[str] = set()
            for categories in per_panel:
                for category in categories or ():
                    if category not in seen:
                        seen.add(category)
                        union.append(category)
            if any(categories != union for categories in per_panel):
                preseed[axis_id] = union
        if preseed:
            # Category positions commit at ingest, so panels with differing
            # category sets must be rebuilt with the union order pre-seeded —
            # otherwise a shared numeric domain aligns different categories
            # at the same position.
            figures = build_panels(preseed)
        for axis_id in shared_axis_ids:
            if axis_id in unshareable:
                continue
            ranges = [fig._range(axis_id) for fig in figures]
            # Reversed axes report descending (hi, lo) pairs; take the pairwise
            # min/max so the merged domain is always increasing.
            lo = min(min(pair) for pair in ranges)
            hi = max(max(pair) for pair in ranges)
            for fig in figures:
                fig._set_axis_domain(axis_id, (lo, hi))
        if linked_dims or self.link_select:
            group = next(
                (
                    fig.interaction["link_group"]
                    for fig in figures
                    if "link_group" in fig.interaction
                ),
                f"xy-facet-{uuid.uuid4().hex[:8]}",
            )
            for fig in figures:
                fig.set_interaction(link_group=group, link_axes=tuple(linked_dims))
                if self.link_select:
                    fig.interaction["link_select"] = True
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
        """Live notebook widgets, one per facet panel."""
        return self.figure().widget()

    def show(self) -> list[Any]:
        """Display the facet grid: returns the panel widgets."""
        return self.widget()

    def to_html(
        self, path: Optional[str | PathLike[str]] = None, *, custom_css: Optional[str] = None
    ) -> str:
        """A self-contained HTML document laying the panels out as a grid."""
        return self.figure().to_html(path, custom_css=custom_css)

    def html(
        self, path: Optional[str | PathLike[str]] = None, *, custom_css: Optional[str] = None
    ) -> str:
        """Alias of `to_html`."""
        return self.to_html(path, custom_css=custom_css)

    def _repr_html_(self) -> str:
        grid = self.figure()
        return export.notebook_iframe(
            grid.to_html(),
            width=grid.width,
            height=grid.grid_height + grid._title_height,
        )

    def _ipython_display_(self) -> None:
        """Display the isolated facet document in notebook frontends."""
        from IPython.display import display  # type: ignore[import-not-found]

        display({"text/html": self._repr_html_()}, raw=True)

    def to_svg(self, path: Optional[str | PathLike[str]] = None) -> str:
        """A static SVG render of the facet grid (written to ``path`` if given)."""
        return self.figure().to_svg(path)

    def to_png(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        scale: float = 2.0,
        engine: export.Engine = export.Engine.default,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """A PNG render of the facet grid, returned as bytes (see `Chart.to_png`)."""
        return self.figure().to_png(
            path,
            scale=scale,
            engine=engine,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def to_image(
        self,
        format: str = "png",
        *,
        scale: float = 2.0,
        background: Optional[str] = None,
        engine: export.Engine | str = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Unified static export of the grid (same format matrix as
        `Chart.to_image`; the grid's geometry is fixed by its panels)."""
        return self.figure().to_image(
            format,
            scale=scale,
            background=background,
            engine=engine,
            quality=quality,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def write_image(
        self,
        path: str | PathLike[str],
        *,
        format: Optional[str] = None,
        scale: float = 2.0,
        background: Optional[str] = None,
        engine: export.Engine | str = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Atomic extension-inferred file export of the grid (see
        `FacetGrid.write_image`)."""
        return self.figure().write_image(
            path,
            format=format,
            scale=scale,
            background=background,
            engine=engine,
            quality=quality,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def memory_report(self) -> dict[str, Any]:
        """Byte-level accounting of every panel's data and cache buffers."""
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
        raise ValueError(f"{mark.kind} {axis_id!r} has no matching xy.{factory}(id={axis_id!r})")
    return x_axis_id, y_axis_id


def _validate_axis_type(type_: Optional[str]) -> None:
    if type_ is None or type_ in {"linear", "time", "log"}:
        return
    raise ValueError(f"axis type_ must be one of None, 'linear', 'time', or 'log', got {type_!r}")


def _axis_domain(value: Any, label: str) -> Optional[tuple[float, float]]:
    if value is None:
        return None
    return _validate.finite_increasing_pair(value, label)


def _axis_bounds(value: Any, label: str) -> Union[tuple[float, float], Literal["data"], None]:
    if value is None:
        return value
    if isinstance(value, str):
        if value == "data":
            return value
        raise ValueError(f"{label} must be an increasing pair, 'data', or None")
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
            _artist_alpha=m.props.get("_artist_alpha"),
            style=m.style,
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
        style=m.style,
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
        line_color=m.props["line_color"],
        line_width=m.props["line_width"],
        line_opacity=m.props["line_opacity"],
        stroke_perimeter=m.props["stroke_perimeter"],
        fill=m.props["fill"],
        curve=m.props["curve"],
        dash=m.props["dash"],
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        style=m.style,
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
        dash_negative=m.props.get("dash_negative", False),
        style=m.style,
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
        _artist_alpha=m.props.get("_artist_alpha"),
        fill=m.props["fill"],
        style=m.style,
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
        style=m.style,
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
        _artist_alpha=m.props.get("_artist_alpha"),
        fill=m.props["fill"],
        style=m.style,
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
        style=m.style,
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
    by: Union[str, ArrayLike, None] = None,
    cols: int = 3,
    share_x: bool = True,
    share_y: bool = True,
    link: Optional[Union[str, bool]] = None,
    link_select: bool = False,
    gap: int = 12,
    **props: Any,
) -> FacetChart:
    """Repeat the child mark composition once per value of ``by``.

    Args:
        *children: Marks, axes, annotations, and chart chrome for each panel.
        by: Facet values or a column name resolved from chart-level data.
        cols: Maximum number of panel columns.
        share_x: Whether panels share an x domain.
        share_y: Whether panels share a y domain.
        link: Runtime-linked axes: ``True``/``"both"`` for both axes,
            ``"x"`` or ``"y"`` for one axis, and ``False``/``None`` to disable.
        link_select: Whether data-space selections are echoed across panels.
        gap: Gap between panels in pixels.
        **props: Additional shared chart properties. ``width`` is the total
            grid width, while ``height`` is the height of each panel; the
            composed height grows with the number of facet rows.
    """
    return FacetChart(
        children,
        by=by,
        cols=cols,
        share_x=share_x,
        share_y=share_y,
        link=link,
        link_select=link_select,
        gap=gap,
        **props,
    )
