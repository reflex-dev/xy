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
from contextlib import suppress
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Optional

import numpy as np

import xy as fc

from ._artists import (
    Artist,
    AxesImage,
    BarContainer,
    Legend,
    Line2D,
    PathCollection,
    PolyCollection,
    Text,
    unit_converted_values,
)
from ._colors import PROP_CYCLE, resolve_cmap, resolve_color
from ._fmt import parse_fmt
from ._mathtext import mathtext_to_unicode
from ._plot_types import PlotTypeMixin
from ._rc import RcParams, rcParams
from ._ticker import AutoLocator, NullLocator, ScalarFormatter, as_formatter
from ._transforms import Bbox, CoordinateTransform, IdentityTransform
from ._translate import (
    LINESTYLE_TO_DASH,
    MARKER_TO_SYMBOL,
    MPL_DASH_PATTERN,
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

# rc-derived chrome styling per (RcParams.version, dpi); see _load_rc_chrome.
_rc_chrome_cache: dict[tuple, dict[str, Any]] = {}


def _rc_chrome_snapshot(dpi: float) -> dict[str, Any]:
    cycle = rcParams["axes.prop_cycle"].by_key().get("color", [])
    family = rcParams["font.family"]
    family = family if isinstance(family, str) else ", ".join(map(str, family))
    if family == "sans-serif":
        family = "DejaVu Sans, sans-serif"
    theme_tokens = {
        "plot_background": resolve_color(rcParams["axes.facecolor"]),
        "axis_color": resolve_color(rcParams["axes.edgecolor"]),
        "text_color": resolve_color(
            rcParams["axes.labelcolor"]
            if rcParams["axes.titlecolor"] == "auto"
            else rcParams["axes.titlecolor"]
        ),
    }
    return {
        "prop_cycle": [
            resolved for color in cycle if (resolved := resolve_color(color)) is not None
        ],
        "grid_color": resolve_color(rcParams["grid.color"]) or _MPL_GRID_COLOR,
        "theme_tokens": theme_tokens,
        "theme_style": {
            "font-family": family,
            "font-size": f"{_font_size(rcParams['font.size'], rcParams['font.size'], dpi):g}px",
        },
        "chrome_styles": {
            "title": {
                "font-size": (
                    f"{_font_size(rcParams['axes.titlesize'], rcParams['font.size'], dpi):g}px"
                ),
                "color": theme_tokens["text_color"],
            },
            "axis_title": {
                "font-size": (
                    f"{_font_size(rcParams['axes.labelsize'], rcParams['font.size'], dpi):g}px"
                ),
                "color": resolve_color(rcParams["axes.labelcolor"]),
            },
            "tick_label": {
                "font-size": (
                    f"{_font_size(rcParams['xtick.labelsize'], rcParams['font.size'], dpi):g}px"
                ),
                "color": resolve_color(
                    rcParams["xtick.color"]
                    if rcParams["xtick.labelcolor"] == "inherit"
                    else rcParams["xtick.labelcolor"]
                ),
            },
        },
        "hidden_spines": {
            side
            for side in ("left", "bottom", "top", "right")
            if not bool(rcParams[f"axes.spines.{side}"])
        },
    }


def _identity_transform() -> Any:
    return IdentityTransform()


def _scale_values(values: Any, spec: Optional[dict[str, Any]], *, inverse: bool = False) -> Any:
    """Apply a dependency-free matplotlib-style nonlinear scale."""
    if not spec or spec["name"] == "linear":
        return values
    source = np.asarray(values, dtype=np.float64)
    name = spec["name"]
    if name == "symlog":
        threshold = spec["linthresh"]
        scale = spec["linscale"]
        base = spec["base"]
        adjusted = scale / (1.0 - base**-1)
        if inverse:
            absolute = np.abs(source)
            result = np.where(
                absolute <= threshold * adjusted,
                absolute / adjusted,
                threshold * np.power(base, absolute / threshold - adjusted),
            )
            return np.sign(source) * result
        absolute = np.abs(source)
        result = absolute * adjusted
        outside = absolute > threshold
        result = np.asarray(result)
        result[outside] = threshold * (
            adjusted + np.log(absolute[outside] / threshold) / np.log(base)
        )
        return np.sign(source) * result
    if name == "logit":
        if inverse:
            return 1.0 / (1.0 + np.exp(-source))
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.log(source / (1.0 - source))
        # values at/outside (0, 1) are masked like matplotlib, never ±inf
        return np.where((source > 0.0) & (source < 1.0), result, np.nan)
    if name == "asinh":
        width = spec["linear_width"]
        return width * np.sinh(source / width) if inverse else width * np.arcsinh(source / width)
    return values


def _transform_entry_axis(entry: dict[str, Any], axis: str, old: Any, new: Any) -> None:
    def convert(values: Any) -> Any:
        return _scale_values(_scale_values(values, old, inverse=True), new)

    key = axis
    if key in entry:
        with suppress(TypeError, ValueError):
            entry[key] = convert(entry[key])
    if entry.get("kind") != "@mark":
        return
    factory = entry.get("factory")
    indexes = {
        "segments": (0, 2) if axis == "x" else (1, 3),
        "triangle_mesh": (0, 2, 4) if axis == "x" else (1, 3, 5),
        "step": (0,) if axis == "x" else (1,),
        "stem": (0,) if axis == "x" else (1,),
        "errorbar": (0,) if axis == "x" else (1,),
        "hexbin": (0,) if axis == "x" else (1,),
    }.get(factory, ())
    args = list(entry.get("args", ()))
    for index in indexes:
        args[index] = convert(args[index])
    entry["args"] = tuple(args)


def _nonlinear_ticks(domain: tuple[float, float], spec: dict[str, Any]) -> np.ndarray:
    lo, hi = map(float, _scale_values(np.asarray(domain), spec, inverse=True))
    if spec["name"] == "logit":
        candidates = np.asarray([0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999])
        return candidates[(candidates >= lo) & (candidates <= hi)]
    if spec["name"] == "symlog":
        threshold, base = spec["linthresh"], spec["base"]
        largest = max(abs(lo), abs(hi), threshold)
        powers = threshold * base ** np.arange(
            0, max(1, int(np.ceil(np.log(largest / threshold) / np.log(base)))) + 1
        )
        candidates = np.unique(np.concatenate((-powers[::-1], [0.0], powers)))
        return candidates[(candidates >= lo) & (candidates <= hi)]
    return np.linspace(lo, hi, 6)


class _AxisProxy:
    def __init__(self, axes: "Axes", axis: str) -> None:
        self.axes, self.axis = axes, axis

    def _ticker_slot(self) -> tuple["Axes", str]:
        axes = self.axes
        host = axes._y2_of or axes
        key = "y2" if (self.axis == "y" and axes._y2_of is not None) else self.axis
        return host, key

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
        if "major_locator" in kwargs:
            self.set_major_locator(kwargs.pop("major_locator"))
        if "major_formatter" in kwargs:
            self.set_major_formatter(kwargs.pop("major_formatter"))

    @staticmethod
    def _is_units_registry_ticker(ticker: Any) -> bool:
        # pandas' date locators/formatters (TimeSeries_DateLocator & co.) speak
        # matplotlib's unit-registry coordinates (period/date ordinals), which
        # never exist here: the engine's time axis is native ms-since-epoch and
        # ticks itself. Treat them as compat-noops so the native ticks render.
        return (type(ticker).__module__ or "").startswith("pandas.plotting")

    def set_major_locator(self, locator: Any) -> None:
        if self._is_units_registry_ticker(locator):
            return
        if not hasattr(locator, "tick_values"):
            raise TypeError("set_major_locator() requires a Locator with tick_values()")
        host, key = self._ticker_slot()
        host._tickers[(key, "major_locator")] = locator
        # A locator displaces explicit ticks, and vice versa: last call wins.
        props = self.axes._axis_props(self.axis)
        for stale in ("tick_values", "tick_labels", "tick_count"):
            props.pop(stale, None)
        host._auto_scale_axis_ticks.discard(key)
        self.axes._invalidate()

    def get_major_locator(self) -> Any:
        host, key = self._ticker_slot()
        return host._tickers.get((key, "major_locator")) or AutoLocator()

    def set_major_formatter(self, formatter: Any) -> None:
        if self._is_units_registry_ticker(formatter):
            return
        host, key = self._ticker_slot()
        host._tickers[(key, "major_formatter")] = as_formatter(formatter, "set_major_formatter()")
        self.axes._invalidate()

    def get_major_formatter(self) -> Any:
        host, key = self._ticker_slot()
        return host._tickers.get((key, "major_formatter")) or ScalarFormatter()

    def set_minor_locator(self, locator: Any) -> None:
        # compat-noop for rendering: minor ticks are outside the native axis
        # contract. The locator is retained so get_minor_locator round-trips.
        host, key = self._ticker_slot()
        host._tickers[(key, "minor_locator")] = locator

    def get_minor_locator(self) -> Any:
        host, key = self._ticker_slot()
        return host._tickers.get((key, "minor_locator")) or NullLocator()

    def set_minor_formatter(self, formatter: Any) -> None:
        # compat-noop for rendering, mirroring set_minor_locator.
        host, key = self._ticker_slot()
        host._tickers[(key, "minor_formatter")] = as_formatter(formatter, "set_minor_formatter()")

    def tick_bottom(self) -> None:
        pass  # exact no-op: the engine only draws bottom x ticks

    def tick_left(self) -> None:
        pass  # exact no-op: the engine only draws left y ticks

    def get_majorticklabels(self) -> list["_TickLabel"]:
        return self.axes._tick_label_handles(self.axis)

    def get_minorticklabels(self) -> list["_TickLabel"]:
        return []  # minor ticks are outside the native axis contract

    def get_minor_formatter(self) -> Any:
        from ._ticker import NullFormatter

        host, key = self._ticker_slot()
        return host._tickers.get((key, "minor_formatter")) or NullFormatter()


class SecondaryAxis:
    """A linked, tick-only secondary axis sharing its parent's plot rectangle."""

    def __init__(self, parent: "Axes", axis: str, location: Any, functions: Any) -> None:
        self._parent, self._axis = parent, axis
        if isinstance(location, str):
            allowed = {"top", "bottom"} if axis == "x" else {"left", "right"}
            if location not in allowed:
                raise ValueError(f"secondary {axis} axis location must be one of {sorted(allowed)}")
            self._side, self._location = location, None
        else:
            value = float(location)
            if not np.isfinite(value):
                raise ValueError("secondary axis location must be finite")
            raise NotImplementedError(
                "xy.pyplot secondary axes currently support named edge locations only"
            )
        if functions is None:
            self._forward = self._inverse = lambda values: np.asarray(values, dtype=float)
        elif isinstance(functions, (tuple, list)) and len(functions) == 2:
            self._forward, self._inverse = functions
            if not callable(self._forward) or not callable(self._inverse):
                raise TypeError("secondary axis functions must be callable")
        elif hasattr(functions, "transform") and hasattr(functions, "inverted"):
            self._forward = functions.transform
            self._inverse = functions.inverted().transform
        else:
            raise TypeError("functions must be a (forward, inverse) pair or invertible transform")
        self._label = ""
        self._ticks: Optional[np.ndarray] = None
        self._tick_labels: Optional[list[str]] = None

    def set_xlabel(self, label: Any, **kwargs: Any) -> "SecondaryAxis":
        if self._axis != "x":
            raise AttributeError("secondary y axes use set_ylabel()")
        if kwargs:
            raise TypeError(f"set_xlabel() got unsupported keyword argument {next(iter(kwargs))!r}")
        self._label = str(label)
        self._parent._invalidate()
        return self

    def set_ylabel(self, label: Any, **kwargs: Any) -> "SecondaryAxis":
        if self._axis != "y":
            raise AttributeError("secondary x axes use set_xlabel()")
        if kwargs:
            raise TypeError(f"set_ylabel() got unsupported keyword argument {next(iter(kwargs))!r}")
        self._label = str(label)
        self._parent._invalidate()
        return self

    def set_ticks(self, ticks: Any, labels: Any = None, **kwargs: Any) -> None:
        check_unsupported(kwargs, "secondary-axis set_ticks()")
        self._ticks = np.asarray(ticks, dtype=float)
        self._tick_labels = None
        if labels is not None:
            self._tick_labels = [str(label) for label in labels]
            if len(self._tick_labels) != len(self._ticks):
                raise ValueError("secondary-axis labels must match ticks")
        self._parent._invalidate()

    def set_functions(self, functions: Any) -> None:
        replacement = SecondaryAxis(self._parent, self._axis, self._side, functions)
        self._forward, self._inverse = replacement._forward, replacement._inverse
        self._parent._invalidate()

    def remove(self) -> None:
        self._parent._secondary_axes.remove(self)
        self._parent._invalidate()

    def _component(self, index: int) -> Any:
        props = self._parent._axis_props(self._axis)
        domain = np.asarray(props.get("domain", self._parent._auto_domain(self._axis)), dtype=float)
        primary_spec = self._parent._scale_specs[self._axis]
        primary_values = _scale_values(
            np.linspace(domain[0], domain[1], 6), primary_spec, inverse=True
        )
        secondary_values = np.asarray(
            self._ticks if self._ticks is not None else self._forward(primary_values), dtype=float
        )
        positions = np.asarray(self._inverse(secondary_values), dtype=float)
        positions = np.asarray(_scale_values(positions, primary_spec), dtype=float)
        if positions.shape != secondary_values.shape or not np.all(np.isfinite(positions)):
            raise ValueError("secondary axis functions must return matching finite values")
        labels = self._tick_labels or [f"{value:g}" for value in secondary_values]
        factory = fc.x_axis if self._axis == "x" else fc.y_axis
        axis_domain = (float(domain[0]), float(domain[1]))
        return factory(
            id=f"{self._axis}s{index}",
            side=self._side,
            domain=axis_domain,
            tick_values=positions,
            tick_labels=labels,
            label=self._label or None,
        )


class _TickLabel:
    """A tick label handle; styling applies to the whole axis, matching the
    uniform ``for tick in ax.get_xticklabels()`` loops scripts write."""

    def __init__(self, axes: "Axes", axis: str, text: str) -> None:
        self._axes, self._axis, self._text = axes, axis, text

    def get_text(self) -> str:
        return self._text

    def set_color(self, color: Any) -> None:
        style = self._axes._axis_props(self._axis).setdefault("style", {})
        style["tick_label_color"] = resolve_color(color)
        self._axes._invalidate()

    def set_rotation(self, angle: Any) -> None:
        self._axes._axis_props(self._axis)["tick_label_angle"] = float(angle)
        self._axes._invalidate()


class _SharedAxesGroup:
    """matplotlib's shared-axes Grouper over the shim's shared props dicts."""

    def __init__(self, axis: str) -> None:
        self._axis = axis

    def _pool(self, ax: Any) -> list[Any]:
        fig = getattr(ax, "figure", None)
        return list(fig._axes) if fig is not None else [ax]

    def get_siblings(self, ax: Any) -> list[Any]:
        props = ax._axis_props(self._axis)
        return [a for a in self._pool(ax) if a._axis_props(self._axis) is props] or [ax]

    def joined(self, a: Any, b: Any) -> bool:
        return a._axis_props(self._axis) is b._axis_props(self._axis)

    def join(self, *axes_list: Any) -> None:
        first = axes_list[0]
        shared = first._axis_props(self._axis)
        for other in axes_list[1:]:
            key = "y2" if (self._axis == "y" and other._y2_of is not None) else self._axis
            (other._y2_of or other)._axis[key] = shared
            other._invalidate()


class _SpineProxy:
    def __init__(
        self, axes: "Axes", names: tuple[str, ...] = ("left", "bottom", "top", "right")
    ) -> None:
        self.axes, self.names = axes, names

    def __getitem__(self, key: Any) -> "_SpineProxy":
        names = (key,) if isinstance(key, str) else tuple(key)
        unknown = set(names) - {"left", "bottom", "top", "right"}
        if unknown:
            raise KeyError(next(iter(unknown)))
        return _SpineProxy(self.axes, names)

    def values(self) -> list["_SpineProxy"]:
        return [_SpineProxy(self.axes, (name,)) for name in self.names]

    def keys(self) -> list[str]:
        return list(self.names)

    def items(self) -> list[tuple[str, "_SpineProxy"]]:
        return [(name, _SpineProxy(self.axes, (name,))) for name in self.names]

    def __iter__(self):
        return iter(self.names)

    def set_visible(self, visible: bool) -> None:
        for name in self.names:
            if bool(visible):
                self.axes._hidden_spines.discard(name)
            else:
                self.axes._hidden_spines.add(name)
        self.axes._invalidate()


def _cached_theme(grid: bool, tokens: dict[str, Any], style: dict[str, Any]) -> Any:
    key = ("theme", grid, tuple(sorted(tokens.items())), tuple(sorted(style.items())))
    made = _component_cache.get(key)
    if made is None:
        applied = dict(tokens)
        applied["grid_color"] = _MPL_GRID_COLOR if grid else "transparent"
        made = _component_cache[key] = fc.theme(style=style, **applied)
    return made


def _cached_modebar(show: bool) -> Any:
    key = ("modebar", show)
    made = _component_cache.get(key)
    if made is None:
        made = _component_cache[key] = fc.modebar(show=show)
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
        self._owned_artists: list[Any] = []
        self._containers: list[Any] = []
        self._axis: dict[str, dict[str, Any]] = {"x": {}, "y": {}, "y2": {}}
        self._title: Optional[str] = None
        self._legend = False
        self._legend_options: dict[str, Any] = {}
        self._extra_legends: list[Any] = []
        self._colorbar: Optional[dict[str, Any]] = None
        self._colorbar_source: Optional[dict[str, Any]] = None  # entry the colorbar reads
        self._aspect_equal = False
        self._aspect_adjustable = "box"
        self._aspect_bounds: Optional[tuple[float, float, float, float]] = None
        self._insets: list[tuple["Axes", tuple[float, float, float, float]]] = []
        self._insets_materialized = False
        self._figure_rect: Optional[tuple[float, float, float, float]] = None
        self._absolute_plot_ratio: Optional[float] = None
        self._padding: Optional[list[float]] = None
        self._xmargin = 0.0
        self._ymargin = 0.0
        self._margin_overrides: set[str] = set()
        self._explicit_domains: set[str] = set()
        self._secondary_axes: list[SecondaryAxis] = []
        self._scale_specs: dict[str, dict[str, Any]] = {
            "x": {"name": "linear"},
            "y": {"name": "linear"},
            "y2": {"name": "linear"},
        }
        self._auto_scale_axis_ticks: set[str] = set()
        self._tickers: dict[tuple[str, str], Any] = {}
        self._hidden_spines: set[str] = set()
        self._grid = bool(rcParams["axes.grid"])
        self._grid_color = _MPL_GRID_COLOR
        self._grid_axis = "both"
        self._grid_style: dict[str, Any] = {}
        self._anchor: Optional[str] = None
        self._cycle = 0
        self._prop_cycle: Optional[list[str]] = None
        self._load_rc_chrome()
        self._chart: Any = None
        self._twin: Optional[Axes] = None
        self._y2_of = y2_of  # when set, our marks target axis id "y2" on the host
        self.transAxes = CoordinateTransform("axes_fraction")
        self.transData = _identity_transform()
        self.xaxis = _AxisProxy(self, "x")
        self.yaxis = _AxisProxy(self, "y")
        self.spines = _SpineProxy(self)
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        for axis in ("x", "y"):
            style = _rc_axis_style(axis, dpi)
            if style:
                self._axis[axis]["style"] = style

    # -- lifecycle -----------------------------------------------------------

    def _load_rc_chrome(self) -> None:
        """Snapshot the rcParams-derived color cycle, theme, and chrome styles.

        The derived snapshot is a pure function of (rcParams state, figure
        dpi), so it is computed once per rc state and shared across axes —
        per-axes recomputation was measurable in the shim's fixed build cost
        (tests/pyplot/test_perf_guardrail.py). Only the members that axes
        mutate in place (theme tokens, hidden spines) are copied per axes.
        """
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        key = (RcParams.version, dpi)
        snapshot = _rc_chrome_cache.get(key)
        if snapshot is None:
            if len(_rc_chrome_cache) > 64:
                _rc_chrome_cache.clear()
            snapshot = _rc_chrome_cache[key] = _rc_chrome_snapshot(dpi)
        self._prop_cycle = snapshot["prop_cycle"]
        self._grid_color = snapshot["grid_color"]
        self._theme_tokens = dict(snapshot["theme_tokens"])  # set_facecolor mutates
        self._theme_style = snapshot["theme_style"]
        self._chrome_styles = snapshot["chrome_styles"]
        self._hidden_spines = set(snapshot["hidden_spines"])  # spines API mutates

    def _invalidate(self) -> None:
        host = self._y2_of or self
        host._chart = None
        if host.figure is not None:
            host.figure._invalidate()

    def _point_scale(self) -> float:
        """Convert Matplotlib points to this figure's output pixels."""
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        return dpi / 72.0

    def _mpl_dash(self, dash: Any, linewidth: Any) -> Any:
        """Scale a named dash pattern the way Matplotlib does, or pass through.

        Named patterns ("dashed"/"dotted"/"dashdot") become an on/off pixel
        list scaled by the line width and figure DPI, matching Matplotlib's
        ``scale_dashes`` plus point sizing. ``None``, the ``"none"`` sentinel,
        and explicit numeric sequences are returned unchanged.
        """
        if not isinstance(dash, str) or dash not in MPL_DASH_PATTERN:
            return dash
        scale = float(linewidth) * self._point_scale()
        return [round(value * scale, 4) for value in MPL_DASH_PATTERN[dash]]

    def _remove_entry(self, entry: dict[str, Any]) -> None:
        host = self._y2_of or self
        for index, candidate in enumerate(host._entries):
            if candidate is entry:
                host._entries.pop(index)
                break
        host._invalidate()

    def _register_artist(self, artist: Any) -> None:
        host = self._y2_of or self
        if artist not in host._owned_artists:
            host._owned_artists.append(artist)

    def _unregister_artist(self, artist: Any) -> None:
        host = self._y2_of or self
        if artist in host._owned_artists:
            host._owned_artists.remove(artist)

    def _register_container(self, container: Any) -> None:
        host = self._y2_of or self
        if container not in host._containers:
            host._containers.append(container)

    def _unregister_container(self, container: Any) -> None:
        host = self._y2_of or self
        if container in host._containers:
            host._containers.remove(container)

    @property
    def lines(self) -> list[Any]:
        return [item for item in self._owned_artists if isinstance(item, Line2D)]

    @property
    def collections(self) -> list[Any]:
        from ._artists import ContourSet

        return [
            item
            for item in self._owned_artists
            if isinstance(item, (PathCollection, PolyCollection, ContourSet))
        ]

    @property
    def patches(self) -> list[Any]:
        from ._artists import Wedge

        return [item for item in self._owned_artists if isinstance(item, Wedge)]

    @property
    def texts(self) -> list[Any]:
        return [item for item in self._owned_artists if isinstance(item, Text)]

    @property
    def images(self) -> list[Any]:
        return [item for item in self._owned_artists if isinstance(item, AxesImage)]

    @property
    def tables(self) -> list[Any]:
        from ._artists import Table

        return [item for item in self._owned_artists if isinstance(item, Table)]

    @property
    def containers(self) -> list[Any]:
        return list(self._containers)

    @property
    def artists(self) -> list[Any]:
        categorized = set(
            self.lines
            + self.collections
            + self.patches
            + self.texts
            + self.images
            + self.tables
            + self.containers
        )
        return [item for item in self._owned_artists if item not in categorized]

    def get_children(self) -> list[Any]:
        """Return a stable snapshot of shim-owned children in creation order."""
        result = list(self._owned_artists)
        result.extend(item for item in self._containers if item not in result)
        return result

    def _next_color(self) -> str:
        host = self._y2_of or self
        cycle = getattr(host, "_prop_cycle", None) or PROP_CYCLE
        color = cycle[host._cycle % len(cycle)]
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

    def _transform_points(self, x: Any, y: Any, transform: Any) -> tuple[np.ndarray, np.ndarray]:
        x_values, y_values = np.broadcast_arrays(x, y)
        if transform in (None, self.transData):
            return np.asarray(x_values), np.asarray(y_values)
        if not hasattr(transform, "transform"):
            raise TypeError("transform must provide a transform(xy) method")
        points = np.asarray(
            transform.transform(np.column_stack((x_values.ravel(), y_values.ravel()))), dtype=float
        )
        if points.shape != (x_values.size, 2):
            raise ValueError("transform must return one x/y pair per input point")
        if getattr(transform, "coordinate_space", "data") in {"axes_fraction", "figure_fraction"}:
            # baking fractions into data coordinates goes silently stale on
            # the next limit change; only text/annotations track these spaces
            raise not_implemented(
                "data artists with transform=transAxes/transFigure",
                "affine data transforms composed with ax.transData",
            )
        return points[:, 0].reshape(x_values.shape), points[:, 1].reshape(y_values.shape)

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
        nonlinear_axes = []
        for axis in ("x", "y"):
            key = "y2" if axis == "y" and self._y2_of is not None else axis
            spec = host._scale_specs[key]
            if spec["name"] != "linear":
                _transform_entry_axis(entry, axis, {"name": "linear"}, spec)
                nonlinear_axes.append((axis, spec))
        host._entries.append(entry)
        for axis, spec in nonlinear_axes:
            # scale-generated ticks were derived from the extent at
            # set_*scale time; new data must refresh them (user-set ticks
            # clear the marker and are left alone)
            key = "y2" if axis == "y" and self._y2_of is not None else axis
            if key in host._auto_scale_axis_ticks and spec["name"] in {
                "symlog",
                "logit",
                "asinh",
            }:
                props = self._axis_props(axis)
                ticks = _nonlinear_ticks(self._entry_extent(axis), spec)
                props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
                props["tick_labels"] = [f"{tick:g}" for tick in ticks]
                props["tick_count"] = max(1, len(ticks))
        host._invalidate()
        return entry

    def clear(self) -> None:
        self._entries.clear()
        self._owned_artists.clear()
        self._containers.clear()
        self._axis = {"x": {}, "y": {}, "y2": {}}
        self._secondary_axes.clear()
        self._scale_specs = {
            "x": {"name": "linear"},
            "y": {"name": "linear"},
            "y2": {"name": "linear"},
        }
        self._auto_scale_axis_ticks = set()
        self._tickers = {}
        self._hidden_spines = set()
        self._title = None
        self._legend = False
        self._legend_options = {}
        self._extra_legends = []
        self._colorbar = None
        self._colorbar_source = None
        self._aspect_equal = False
        self._aspect_adjustable = "box"
        self._aspect_bounds = None
        self._insets = []
        self._insets_materialized = False
        self._absolute_plot_ratio = None
        self._padding = None
        self._grid = bool(rcParams["axes.grid"])
        self._grid_color = _MPL_GRID_COLOR
        self._grid_axis = "both"
        self._grid_style = {}
        self._cycle = 0
        self._load_rc_chrome()
        self._chart = None
        self._twin = None
        self.xaxis = _AxisProxy(self, "x")
        self.yaxis = _AxisProxy(self, "y")
        self.spines = _SpineProxy(self)
        for axis in ("x", "y"):
            style = _rc_axis_style(axis)
            if style:
                self._axis[axis]["style"] = style
        self._invalidate()

    cla = clear

    # -- plotting ------------------------------------------------------------

    def plot(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        scalex = kwargs.pop("scalex", True)
        scaley = kwargs.pop("scaley", True)
        if scalex is not True or scaley is not True:
            raise not_implemented("plot(scalex=False/scaley=False)")
        base = line_kwargs(kwargs)
        marker = kwargs.pop("marker", None)
        markersize = kwargs.pop("markersize", kwargs.pop("ms", None))
        markerfacecolor = kwargs.pop("markerfacecolor", kwargs.pop("mfc", None))
        markerfacecoloralt = kwargs.pop("markerfacecoloralt", None)
        markeredgecolor = kwargs.pop("markeredgecolor", kwargs.pop("mec", None))
        markeredgewidth = kwargs.pop("markeredgewidth", kwargs.pop("mew", None))
        fillstyle = kwargs.pop("fillstyle", None)
        cap_join = {
            key: kwargs.pop(key, None)
            for key in ("solid_capstyle", "solid_joinstyle", "dash_capstyle", "dash_joinstyle")
        }
        if markerfacecoloralt is not None:
            raise not_implemented("plot(markerfacecoloralt=...)")
        if fillstyle not in (None, "full"):
            raise not_implemented(f"plot(fillstyle={fillstyle!r})")
        if any(value is not None for value in cap_join.values()):
            raise not_implemented("plot(capstyle/joinstyle)")
        markevery = kwargs.pop("markevery", None)
        drawstyle = kwargs.pop("drawstyle", None)
        transform = kwargs.pop("transform", None)
        if transform is not None and not hasattr(transform, "transform"):
            raise TypeError("plot transform must provide transform(xy)")
        if drawstyle not in (None, "default", "steps-pre", "steps-mid", "steps-post"):
            raise ValueError(f"unsupported drawstyle: {drawstyle!r}")
        check_unsupported(kwargs, "plot()")

        handles: list[Line2D] = []
        for gx, gy, fmt in _iter_plot_groups(args):
            gx, gy = np.atleast_1d(gx), np.atleast_1d(gy)
            gx, gy = _convert_timedelta_axis(gx), _convert_timedelta_axis(gy)
            # A 2-D operand draws one line per column; each column advances the
            # property cycle so column N gets color C{N}, matching matplotlib.
            for x, y in _plot_series_columns(gx, gy):
                handles.append(
                    self._plot_series(
                        x,
                        y,
                        fmt,
                        base,
                        marker,
                        markersize,
                        markerfacecolor,
                        markeredgecolor,
                        markeredgewidth,
                        markevery,
                        drawstyle,
                        transform,
                    )
                )
        return handles

    def _plot_series(
        self,
        x: Any,
        y: Any,
        fmt: Optional[str],
        base: dict[str, Any],
        marker: Any,
        markersize: Any,
        markerfacecolor: Any,
        markeredgecolor: Any,
        markeredgewidth: Any,
        markevery: Any,
        drawstyle: Any,
        transform: Any,
    ) -> "Line2D":
        if transform is not None:
            x, y = self._transform_points(x, y, transform)
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
        dash = self._mpl_dash(dash, per.get("width", rcParams["lines.linewidth"]))

        entry_kwargs = {
            "color": per.get("color"),
            "width": per.get("width", rcParams["lines.linewidth"]),
            "opacity": per.get("opacity", 1.0),
            "name": per.get("name"),
        }
        marker_size_pt = float(rcParams["lines.markersize"] if markersize is None else markersize)
        marker_edge_visible = not (
            isinstance(markeredgecolor, str) and markeredgecolor.lower() == "none"
        )
        marker_edge_px = (
            float(rcParams["lines.markeredgewidth"] if markeredgewidth is None else markeredgewidth)
            * self._point_scale()
            if marker_edge_visible
            else 0.0
        )
        # Matplotlib's point marker is a half-size circle, while the pixel
        # marker is a snapped one-pixel rectangle independent of markersize.
        # Keep those semantics instead of treating every marker as a circle.
        marker_path_px = marker_size_pt * self._point_scale()
        if this_marker == ".":
            marker_path_px *= 0.5
        elif this_marker == ",":
            marker_path_px = 1.0
            marker_edge_px = 0.0
            marker_edge_visible = False
        marker_size_px = marker_path_px + marker_edge_px
        marker_edge_style = (
            {
                "stroke": (
                    entry_kwargs["color"]
                    if markeredgecolor in (None, "auto")
                    else resolve_color(markeredgecolor)
                ),
                "stroke_width": marker_edge_px,
            }
            if marker_edge_visible
            else {}
        )
        if dash == "none":
            entry = self._add(
                "scatter",
                {
                    "x": x,
                    "y": y,
                    "kwargs": {
                        **{k: v for k, v in entry_kwargs.items() if k != "width"},
                        "symbol": _marker_symbol(this_marker or "o"),
                        "size": marker_size_px,
                        **marker_edge_style,
                        **(
                            {"color": resolve_color(markerfacecolor)}
                            if markerfacecolor not in (None, "auto")
                            else {}
                        ),
                    },
                },
            )
        else:
            if dash is not None:
                entry_kwargs["dash"] = dash
            numeric_x = np.asarray(x)
            # finite_pairs stays None for gap-free data: a non-finite value
            # anywhere leaves the sum non-finite (inf - inf is nan), so the
            # common clean case skips the per-element isfinite mask. Finite
            # data whose sum overflows merely takes the exact scan.
            finite_pairs = None
            try:
                xv64 = np.asarray(x, dtype=np.float64)
                yv64 = np.asarray(y, dtype=np.float64)
                if not np.isfinite(xv64.sum() + yv64.sum()):
                    finite_pairs = np.isfinite(xv64)
                    finite_pairs &= np.isfinite(yv64)
            except (TypeError, ValueError):
                pass
            has_gaps = finite_pairs is not None and not bool(np.all(finite_pairs))
            if not has_gaps:
                finite_pairs = None
            from xy import kernels

            # Native sortedness instead of an astype copy + diff + compare —
            # this runs on every plot() call, and O(n) temporaries here are
            # exactly what the perf guardrail exists to catch. For gap-free
            # data (the only case where the value matters — has_gaps routes
            # to segments regardless) `not is_sorted` == any(diff < 0).
            preserve_path = (
                not has_gaps
                and numeric_x.ndim == 1
                and len(numeric_x) > 1
                and np.issubdtype(numeric_x.dtype, np.number)
                and not kernels.is_sorted(np.asarray(numeric_x, dtype=np.float64))
            )
            if preserve_path or has_gaps:
                xv, yv = np.asarray(x), np.asarray(y)
                if finite_pairs is None:  # parametric path, no gaps
                    finite_pairs = np.ones(len(xv), dtype=bool)
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
                overlay = self._add(
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
                            "size": marker_size_px,
                            "name": None,
                            **marker_edge_style,
                            **(
                                {"color": resolve_color(markerfacecolor)}
                                if markerfacecolor not in (None, "auto")
                                else {}
                            ),
                        },
                    },
                )
                # The overlay marks the same Line2D; it must not claim its own
                # legend slot when labels are assigned positionally.
                overlay["_legend_skip"] = True
        handle = Line2D(self, entry)
        if transform is not None:
            handle._transform = transform
        return handle

    def scatter(
        self, x: Any, y: Any, s: Any = None, c: Any = None, **kwargs: Any
    ) -> PathCollection:
        if c is None and "color" in kwargs:
            c = kwargs.pop("color")
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        marker = kwargs.pop("marker", None)
        transform = kwargs.pop("transform", None)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidths = kwargs.pop("linewidths", kwargs.pop("linewidth", kwargs.pop("lw", None)))
        plotnonfinite = bool(kwargs.pop("plotnonfinite", False))
        vmin, vmax = kwargs.pop("vmin", None), kwargs.pop("vmax", None)
        norm = kwargs.pop("norm", None)
        if norm is not None:
            raise not_implemented("scatter(norm=...)")
        check_unsupported(kwargs, "scatter()")

        xv = np.ma.asarray(x).reshape(-1)
        yv = np.ma.asarray(y).reshape(-1)
        s_arr = None if s is None or np.isscalar(s) else np.ma.asarray(s).reshape(-1)
        dropped = np.ma.getmaskarray(xv) | np.ma.getmaskarray(yv)
        if s_arr is not None and len(s_arr) == len(dropped):
            dropped = dropped | np.ma.getmaskarray(s_arr)
        if dropped.any():
            # matplotlib never draws rows masked in x, y, or s
            keep = ~dropped
            xv, yv = xv[keep], yv[keep]
            if s_arr is not None and len(s_arr) == len(dropped):
                s_arr = s_arr[keep]
            if (
                c is not None
                and not isinstance(c, str)
                and not (
                    isinstance(c, (tuple, list))
                    and len(c) in (3, 4)
                    and not hasattr(c[0], "__len__")
                )
            ):
                c_rows = np.ma.asarray(c)
                if c_rows.ndim >= 1 and c_rows.shape[0] == len(dropped):
                    c = c_rows[keep]
        xv, yv = np.asarray(xv), np.asarray(yv)
        if s_arr is not None:
            s = np.asarray(s_arr)
        x, y = xv, yv
        if transform is not None:
            x, y = self._transform_points(x, y, transform)
        source_color = None
        cv = None if c is None or isinstance(c, str) else np.ma.asarray(c).reshape(-1)
        if (
            cv is not None
            and cv.ndim == 1
            and len(cv) == len(xv)
            and np.issubdtype(cv.dtype, np.number)
        ):
            source_color = cv.copy()
            numeric_color = np.ma.asarray(cv, dtype=np.float64)
            finite_color = np.isfinite(numeric_color.filled(np.nan)) & ~np.ma.getmaskarray(
                numeric_color
            )
            if plotnonfinite:
                cv = np.where(finite_color, numeric_color.filled(0.0), 0.0)
            else:
                xv, yv, cv = xv[finite_color], yv[finite_color], numeric_color.data[finite_color]
                if s is not None and not np.isscalar(s):
                    s = np.asarray(s)[finite_color]
            x, y, c = xv, yv, cv

        symbol = _marker_symbol(marker) if marker else "circle"
        marker_path_px = marker_size_to_scatter_size(
            s,
            default=6.0 * self._point_scale(),
            point_scale=self._point_scale(),
        )
        if symbol == "point":
            marker_path_px = np.asarray(marker_path_px) * 0.5
            if np.ndim(marker_path_px) == 0:
                marker_path_px = float(marker_path_px)
        elif symbol == "pixel":
            marker_path_px = (
                np.ones_like(marker_path_px, dtype=np.float64)
                if isinstance(marker_path_px, np.ndarray)
                else 1.0
            )

        edge_setting = rcParams["scatter.edgecolors"] if edgecolors is None else edgecolors
        no_edges = isinstance(edge_setting, str) and edge_setting.lower() == "none"
        edge_width_px = (
            0.0
            if no_edges
            else float(rcParams["patch.linewidth"] if linewidths is None else linewidths)
            * self._point_scale()
        )
        size_px = np.asarray(marker_path_px) + edge_width_px
        if np.ndim(size_px) == 0:
            size_px = float(size_px)
        entry_kwargs: dict[str, Any] = {
            "size": size_px,
            "opacity": float(alpha) if alpha is not None else 1.0,
            "name": str(label) if label is not None else None,
            "symbol": symbol,
        }
        if isinstance(size_px, np.ndarray) and size_px.size:
            # matplotlib s= is absolute (points²); pin the engine's size range
            # to the converted pixel values so normalization is the identity
            # instead of compressing everything into the default 2-18 px band.
            size_values = np.asarray(size_px, dtype=np.float64)
            finite_sizes = size_values[np.isfinite(size_values)]
            if finite_sizes.size:
                lo_px, hi_px = float(finite_sizes.min()), float(finite_sizes.max())
                if hi_px > lo_px:
                    entry_kwargs["size_range"] = (lo_px, hi_px)
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
            entry_kwargs["colormap"] = resolve_cmap(
                cmap if cmap is not None else rcParams["image.cmap"]
            )
            if vmin is not None or vmax is not None:
                # one-sided limits autoscale the other side, like matplotlib
                values = np.asarray(c, dtype=np.float64)
                finite = values[np.isfinite(values)]
                lo = (
                    float(vmin) if vmin is not None else float(finite.min()) if finite.size else 0.0
                )
                hi = (
                    float(vmax) if vmax is not None else float(finite.max()) if finite.size else 1.0
                )
                entry_kwargs["domain"] = (lo, hi)
        if not no_edges:
            if not (isinstance(edge_setting, str) and edge_setting.lower() == "face"):
                entry_kwargs["stroke"] = resolve_color(edge_setting)
            entry_kwargs["stroke_width"] = edge_width_px
        entry = self._add("scatter", {"x": x, "y": y, "kwargs": entry_kwargs})
        if source_color is not None:
            entry["source_array"] = source_color
        if "colormap" in entry_kwargs:
            levels = _discrete_levels(cmap)
            if levels is not None:
                entry["discrete_levels"] = levels
        artist = PathCollection(self, entry)
        if transform is not None:
            artist._transform = transform
        return artist

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
        if edgecolor is None and rcParams["patch.force_edgecolor"]:
            edgecolor = rcParams["patch.edgecolor"]  # seaborn styles force patch edges
        linewidth = kwargs.pop("linewidth", None)
        xerr = kwargs.pop("xerr", None)
        yerr = kwargs.pop("yerr", None)
        error_kw = kwargs.pop("error_kw", {}) or {}
        capsize = kwargs.pop("capsize", error_kw.pop("capsize", None))
        kwargs.pop("ecolor", error_kw.pop("ecolor", None))
        align = kwargs.pop("align", "center")
        if align not in {"center", "edge"}:
            raise ValueError("bar()/barh() align must be 'center' or 'edge'")
        if align == "edge":
            try:
                cats = np.asarray(cats, dtype=np.float64) + float(thickness) / 2.0
            except (TypeError, ValueError):
                raise ValueError("bar align='edge' requires numeric positions") from None
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
        if (
            edgecolor is None
            and histtype in ("bar", "barstacked")
            and rcParams["patch.force_edgecolor"]
        ):
            edgecolor = rcParams["patch.edgecolor"]  # seaborn styles force patch edges
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
        # matplotlib's bin filling: a single (or stacked) series spans the full
        # bin so adjacent bars touch; only multiple side-by-side series shrink
        # to 0.8 of the bin, split evenly.  The shim previously applied the 0.8
        # factor to single-series hists too, leaving visible gaps.
        binwidth = float(np.min(np.diff(edges)))
        rel_width = 1.0 if (stacked or len(datasets) == 1) else 0.8
        width = binwidth * rel_width / (1 if stacked else len(datasets))
        for index, values in enumerate(counts):
            positions = centers if stacked else centers + (index - (len(datasets) - 1) / 2) * width
            current_base = base.copy() if stacked else np.zeros_like(values)
            resolved_color = (
                resolve_color(colors[index]) if colors[index] is not None else self._next_color()
            )
            if orientation == "horizontal" and histtype == "stepfilled":
                # The core area primitive fills along y. Horizontal filled
                # steps are equivalently represented by touching horizontal
                # bars, preserving the exact bins/counts without rotating a
                # rasterized approximation.
                entry = self._add(
                    "bar",
                    {
                        "x": positions,
                        "y": values,
                        "kwargs": {
                            "base": current_base,
                            "width": width,
                            "orientation": "horizontal",
                            "color": resolved_color,
                            "opacity": 1.0 if alpha is None else float(alpha),
                            "name": None if labels[index] is None else str(labels[index]),
                            "stroke": resolve_color(edgecolor) if edgecolor is not None else None,
                        },
                    },
                )
            elif orientation == "horizontal" and histtype.startswith("step"):
                step_values = values + current_base
                path_x = np.repeat(step_values, 2)
                path_y = np.repeat(edges, 2)[1:-1]
                entry = self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": (path_x[:-1], path_y[:-1], path_x[1:], path_y[1:]),
                        "kwargs": {
                            "color": resolved_color,
                            "width": 1.2,
                            "name": None if labels[index] is None else str(labels[index]),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            elif histtype == "stepfilled":
                # matplotlib fills the step polygon down to the baseline; the
                # area mark takes the pre-expanded step vertices verbatim.
                tops = values + current_base
                no_edge = edgecolor is None or (
                    isinstance(edgecolor, str) and edgecolor.lower() == "none"
                )
                entry = self._add(
                    "@mark",
                    {
                        "factory": "area",
                        "args": (np.repeat(edges, 2)[1:-1], np.repeat(tops, 2)),
                        "kwargs": {
                            "base": np.repeat(current_base, 2),
                            "color": resolved_color,
                            "line_color": None if no_edge else resolve_color(edgecolor),
                            "line_width": (
                                0.0
                                if no_edge
                                else float(rcParams["patch.linewidth"]) * self._point_scale()
                            ),
                            "line_opacity": 1.0 if alpha is None else float(alpha),
                            "stroke_perimeter": not no_edge,
                            "name": None if labels[index] is None else str(labels[index]),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            elif histtype.startswith("step"):
                step_values = values + current_base
                entry = self._add(
                    "@mark",
                    {
                        "factory": "stairs",
                        "args": (step_values, edges),
                        "kwargs": {
                            "color": resolved_color,
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
                            "color": resolved_color,
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
        interpolate = kwargs.pop("interpolate", False)
        if step not in (None, "pre", "post", "mid"):
            raise ValueError("fill_between step must be 'pre', 'post', 'mid', or None")
        if transform not in (None, "xaxis transform"):
            raise not_implemented("fill_between(transform=...)")
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
            if interpolate:
                # Extend a selected region to the linear intersection of y1
                # and y2 at each where-boundary, matching Matplotlib's useful
                # behavior for threshold fills.
                if start > 0:
                    d0 = upper[start - 1] - lower[start - 1]
                    d1 = upper[start] - lower[start]
                    if np.isfinite(d0 + d1) and d0 != d1:
                        t = float(np.clip(-d0 / (d1 - d0), 0.0, 1.0))
                        cross_x = xv[start - 1] + t * (xv[start] - xv[start - 1])
                        cross_y = upper[start - 1] + t * (upper[start] - upper[start - 1])
                        sx = np.r_[cross_x, sx]
                        su = np.r_[cross_y, su]
                        sl = np.r_[cross_y, sl]
                if end < len(xv):
                    d0 = upper[end - 1] - lower[end - 1]
                    d1 = upper[end] - lower[end]
                    if np.isfinite(d0 + d1) and d0 != d1:
                        t = float(np.clip(-d0 / (d1 - d0), 0.0, 1.0))
                        cross_x = xv[end - 1] + t * (xv[end] - xv[end - 1])
                        cross_y = upper[end - 1] + t * (upper[end] - upper[end - 1])
                        sx = np.r_[sx, cross_x]
                        su = np.r_[su, cross_y]
                        sl = np.r_[sl, cross_y]
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
                            "line_width": float(rcParams["patch.linewidth"]) * self._point_scale(),
                            "line_opacity": float(alpha) if alpha is not None else 1.0,
                            "stroke_perimeter": True,
                            "name": str(label) if label is not None and not entries else None,
                        },
                    },
                )
            )
        if interpolate:
            # A single selected point between deselected neighbors spans no
            # interval, but matplotlib still draws its interpolated wedge.
            covered = np.zeros(len(xv), dtype=bool)
            for start, end in zip(starts, ends, strict=True):
                covered[start:end] = True
            finite_pt = np.isfinite(xv + upper + lower)
            for i in np.flatnonzero(mask & ~covered & finite_pt):
                sx = [float(xv[i])]
                su = [float(upper[i])]
                sl = [float(lower[i])]
                for j, prepend in ((i - 1, True), (i + 1, False)):
                    if 0 <= j < len(xv) and finite_pt[j]:
                        d0 = upper[j] - lower[j]
                        d1 = upper[i] - lower[i]
                        if d0 != d1:
                            t = float(np.clip(-d0 / (d1 - d0), 0.0, 1.0))
                            cross_x = float(xv[j] + t * (xv[i] - xv[j]))
                            cross_y = float(upper[j] + t * (upper[i] - upper[j]))
                            if prepend:
                                sx.insert(0, cross_x)
                                su.insert(0, cross_y)
                                sl.insert(0, cross_y)
                            else:
                                sx.append(cross_x)
                                su.append(cross_y)
                                sl.append(cross_y)
                if len(sx) >= 2:
                    entries.append(
                        self._add(
                            "area",
                            {
                                "x": np.asarray(sx),
                                "y": np.asarray(su),
                                "kwargs": {
                                    "base": np.asarray(sl),
                                    "color": resolved_color,
                                    "opacity": float(alpha) if alpha is not None else 1.0,
                                    "line_width": float(rcParams["patch.linewidth"])
                                    * self._point_scale(),
                                    "line_opacity": float(alpha) if alpha is not None else 1.0,
                                    "stroke_perimeter": True,
                                    "name": str(label)
                                    if label is not None and not entries
                                    else None,
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
        origin = kwargs.pop("origin", rcParams["image.origin"])
        if origin not in {"upper", "lower"}:
            raise ValueError("imshow origin must be 'upper' or 'lower'")
        aspect = kwargs.pop("aspect", None)
        alpha = kwargs.pop("alpha", None)
        clim = kwargs.pop("clim", None)
        transform = kwargs.pop("transform", None)
        interpolation = kwargs.pop("interpolation", None)
        interpolation_stage = kwargs.pop("interpolation_stage", None)
        clip_on = kwargs.pop("clip_on", True)
        colorizer = kwargs.pop("colorizer", None)
        clip_path = kwargs.pop("clip_path", None)
        extent = kwargs.pop("extent", None)
        norm = kwargs.pop("norm", None)
        supported_interpolation = {
            None,
            "none",
            "nearest",
            "bilinear",
            "bicubic",
            "spline16",
            "spline36",
            "hanning",
            "hamming",
            "hermite",
            "kaiser",
            "quadric",
            "catrom",
            "gaussian",
            "bessel",
            "mitchell",
            "sinc",
            "lanczos",
            "antialiased",
        }
        if interpolation not in supported_interpolation:
            raise ValueError(f"unsupported imshow interpolation: {interpolation!r}")
        if interpolation_stage not in (None, "data"):
            raise not_implemented(f"imshow(interpolation_stage={interpolation_stage!r})")
        if clip_on is not True:
            raise not_implemented("imshow(clip_on=False)")
        if transform not in (None, self.transData, self.transAxes):
            raise not_implemented("imshow(transform=...)")
        if transform is self.transAxes and extent is None:
            raise ValueError("imshow(transform=ax.transAxes) requires extent")
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
        # A resampled colormap (plt.get_cmap(name, N)) with no *customized*
        # extremes must render N flat bands through the ordinary heatmap path so
        # a later plt.clim() still applies; only genuine set_under/over/bad
        # customization needs the Python-baked truecolor branch below.
        imshow_levels = _discrete_levels(cmap) if not truecolor and norm is None else None
        if imshow_levels is not None and has_extremes:
            default_extremes = (
                getattr(cmap, "_under", None) is None
                and getattr(cmap, "_over", None) is None
                and getattr(cmap, "_bad", "transparent") in ("transparent", None)
            )
            if default_extremes:
                has_extremes = False
            else:
                imshow_levels = None
        if not truecolor and norm is not None and callable(norm) and not has_extremes:
            mapped = np.ma.asarray(norm(grid), dtype=np.float64)
            cmap_callable = cmap if callable(cmap) else None
            if cmap_callable is None:
                try:
                    mpl_colormaps = __import__("matplotlib", fromlist=["colormaps"]).colormaps

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
            from xy._svg import _lut

            from ._colors import _rgba_floats

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
            rgb = _lut(resolve_cmap(cmap), np.nan_to_num(normalized, nan=0.0).reshape(-1)).reshape(
                grid.shape + (3,)
            )
            rgba = np.dstack((rgb / 255.0, np.ones(grid.shape, dtype=float)))

            def extreme(name: str, default: tuple[float, float, float, float]) -> np.ndarray:
                value = getattr(cmap, f"_{name}", None)
                if value is None:
                    return np.asarray(default)
                if isinstance(value, tuple) and len(value) == 2 and value[1] is None:
                    value = value[0]
                return np.asarray(_rgba_floats(value), dtype=float)

            rgba[grid < lo] = extreme("under", (0.0, 0.0, 0.0, 1.0))
            rgba[grid > hi] = extreme("over", (1.0, 1.0, 1.0, 1.0))
            rgba[~np.isfinite(grid) | np.ma.getmaskarray(masked_grid)] = extreme(
                "bad", (0.0, 0.0, 0.0, 0.0)
            )
            grid, truecolor = rgba, True
        alpha_array = (
            None if alpha is None or np.isscalar(alpha) else np.asarray(alpha, dtype=float)
        )
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
                rgb = _lut(
                    resolve_cmap(cmap if cmap is not None else rcParams["image.cmap"]),
                    normalized.reshape(-1),
                )
                grid = np.dstack((rgb.reshape(grid.shape + (3,)) / 255.0, alpha_array))
                truecolor = True
        if (
            not truecolor
            and interpolation not in (None, "none", "nearest")
            and min(grid.shape) >= 2
        ):
            # The notebook's ordinary image box is ~369 px per side. A 128²
            # intermediate left each interpolated sample covering about 3×3
            # display pixels because heatmaps intentionally use nearest texture
            # sampling. Keep a bounded 512² surface so non-nearest imshow output
            # is at least display-resolution while nearest retains source cells.
            grid = _upsample_grid(grid, max(512, grid.shape[1]), max(512, grid.shape[0]))
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
            "colormap": resolve_cmap(cmap if cmap is not None else rcParams["image.cmap"]),
            "opacity": 1.0,
        }
        if alpha is not None and np.isscalar(alpha):
            entry_kwargs["opacity"] = float(np.asarray(alpha, dtype=np.float64))
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
        if imshow_levels is not None:
            entry["discrete_levels"] = imshow_levels
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
                props["dash"] = self._mpl_dash(
                    dash, props.get("width", rcParams["lines.linewidth"])
                )
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
        linestyle = kwargs.pop("linestyle", kwargs.pop("ls", None))
        if linestyle is not None and linestyle not in LINESTYLE_TO_DASH:
            raise ValueError(f"unsupported annotation linestyle: {linestyle!r}")
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
        dash = LINESTYLE_TO_DASH.get(linestyle)
        if dash not in (None, "none"):
            scaled = self._mpl_dash(dash, akw.get("width", rcParams["lines.linewidth"]))
            akw.setdefault("style", {})["dash"] = ",".join(map(str, scaled))
        return self._add(f"@{kind}", {"args": args, "kwargs": akw})

    def text(
        self, x: Any, y: Any, s: str, fontdict: Optional[dict[str, Any]] = None, **kwargs: Any
    ) -> Text:
        if fontdict:
            kwargs = {**fontdict, **kwargs}
        color = kwargs.pop("color", kwargs.pop("c", None))
        fontsize = kwargs.pop("fontsize", kwargs.pop("size", None))
        ha = kwargs.pop("ha", kwargs.pop("horizontalalignment", None))
        va = kwargs.pop("va", kwargs.pop("verticalalignment", None))
        transform = kwargs.pop("transform", None)
        fontweight = kwargs.pop("fontweight", kwargs.pop("weight", None))
        fontfamily = kwargs.pop("fontfamily", kwargs.pop("family", None))
        rotation = kwargs.pop("rotation", None)
        check_unsupported(kwargs, "text()")
        akw = {"color": resolve_color(color)} if color is not None else {}
        if ha is not None:
            akw["anchor"] = {"left": "start", "center": "middle", "right": "end"}.get(
                str(ha), "start"
            )
        style: dict[str, Any] = {}
        if fontsize is not None:
            style["font_size"] = float(fontsize)
        if va is not None:
            style["vertical_align"] = str(va)
        if fontweight is not None:
            style["font_weight"] = str(fontweight)
        if fontfamily is not None:
            style["font_family"] = str(fontfamily)
        if rotation is not None:
            style["rotation"] = 90.0 if rotation == "vertical" else float(rotation)
        if transform is self.transAxes or transform == "axes fraction":
            style["coordinate_space"] = "axes_fraction"
        elif transform in {getattr(self.figure, "transFigure", None), "figure fraction"}:
            style["coordinate_space"] = "figure_fraction"
        if style:
            akw["style"] = style
        return Text(self, self._add("@text", {"args": (x, y, _plain_text(s)), "kwargs": akw}))

    def annotate(self, text: str, xy: tuple, xytext: Optional[tuple] = None, **kwargs: Any) -> Text:
        arrowprops = kwargs.pop("arrowprops", None)
        fontsize = kwargs.pop("fontsize", kwargs.pop("size", None))
        color = kwargs.pop("color", None)
        xycoords = kwargs.pop("xycoords", "data")
        textcoords = kwargs.pop("textcoords", None)
        ha = kwargs.pop("ha", kwargs.pop("horizontalalignment", None))
        va = kwargs.pop("va", kwargs.pop("verticalalignment", None))
        family = kwargs.pop("family", kwargs.pop("fontfamily", None))
        weight = kwargs.pop("weight", kwargs.pop("fontweight", None))
        rotation = kwargs.pop("rotation", None)
        bbox = kwargs.pop("bbox", None)
        check_unsupported(kwargs, "annotate()")
        akw: dict[str, Any] = {}
        if color is not None:
            akw["color"] = resolve_color(color)
        if arrowprops is not None:
            akw["arrowprops"] = dict(arrowprops)
        if bbox is not None:
            akw["bbox"] = dict(bbox)
        if ha is not None:
            akw["anchor"] = {"left": "start", "center": "middle", "right": "end"}.get(
                str(ha), "start"
            )
        text_xy = xy
        if xytext is not None:
            if textcoords in {"offset points", "offset pixels"}:
                scale = self._point_scale() if textcoords == "offset points" else 1.0
                akw["dx"], akw["dy"] = float(xytext[0]) * scale, -float(xytext[1]) * scale
            else:
                converted = self._data_coordinates(xytext)
                if converted is not None:
                    # matplotlib places the text AT xytext (data coordinates);
                    # date strings convert like matplotlib's unit registry.
                    text_xy = converted
                else:
                    akw["dx"], akw["dy"] = 8.0, -8.0
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
        if va is not None:
            style["vertical_align"] = str(va)
        if weight is not None:
            style["font_weight"] = str(weight)
        if family is not None:
            style["font_family"] = str(family)
        if rotation is not None:
            style["rotation"] = 90.0 if rotation == "vertical" else float(rotation)
        if style:
            akw["style"] = style
        if arrowprops is not None and text_xy != xy:
            if style.get("coordinate_space"):
                raise not_implemented(
                    "annotate(arrowprops=) outside data coordinates",
                    "data-coordinate annotations",
                )
            start = self._data_coordinates(text_xy)
            end = self._data_coordinates(xy)
            if start is None or end is None:
                raise not_implemented(
                    "annotate(arrowprops=) with non-numeric coordinates",
                    "numeric data coordinates",
                )
            # Straight arrow from the text toward the point; arrowstyle and
            # connectionstyle curves are approximated by this straight shaft.
            shrink = float(arrowprops.get("shrink", 0.0))
            (sx0, sy0), (ex0, ey0) = start, end
            if shrink:
                dx_a, dy_a = ex0 - sx0, ey0 - sy0
                sx0, sy0 = sx0 + shrink * dx_a, sy0 + shrink * dy_a
                ex0, ey0 = ex0 - shrink * dx_a, ey0 - shrink * dy_a
            arrow_color, arrow_width, arrow_style = _arrow_visuals(
                arrowprops,
                mutation_scale=_font_size_points(
                    fontsize if fontsize is not None else rcParams["font.size"],
                    rcParams["font.size"],
                )
                * self._point_scale(),
            )
            self._add(
                "@arrow",
                {
                    "args": (sx0, sy0, ex0, ey0),
                    "kwargs": {
                        "color": arrow_color,
                        "width": arrow_width,
                        "style": arrow_style,
                    },
                },
            )
        return Text(
            self,
            self._add(
                "@text", {"args": (text_xy[0], text_xy[1], _plain_text(text)), "kwargs": akw}
            ),
        )

    # -- axis config -----------------------------------------------------------

    def set_xlabel(self, label: str, **kwargs: Any) -> None:
        props = self._axis_props("x")
        props["label"] = _plain_text(label)
        _apply_axis_label_kwargs(props, kwargs, "set_xlabel()")
        self._invalidate()

    def set_ylabel(self, label: str, **kwargs: Any) -> None:
        props = self._axis_props("y")
        props["label"] = _plain_text(label)
        _apply_axis_label_kwargs(props, kwargs, "set_ylabel()")
        self._invalidate()

    def set_title(self, title: str, **kwargs: Any) -> None:
        _consume_text_kwargs(kwargs, "set_title()")
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
            "position": self.set_position,
            "anchor": self.set_anchor,
            "aspect": self.set_aspect,
            "facecolor": self.set_facecolor,
            "axisbelow": self.set_axisbelow,
        }
        xticklabels = kwargs.pop("xticklabels", None)
        yticklabels = kwargs.pop("yticklabels", None)
        projection = kwargs.pop("projection", None)
        if projection not in (None, "rectilinear"):
            raise not_implemented(f"projection={projection!r} axes", "2-D rectilinear charts")
        unknown: list[str] = []
        for name, value in kwargs.items():
            setter = aliases.get(name)
            if setter is None:
                unknown.append(name)
                continue
            setter(value)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise AttributeError(f"Axes.set() got unsupported property name(s): {names}")
        for axis, labels in (("x", xticklabels), ("y", yticklabels)):
            if labels is None:
                continue
            labels = [str(value) for value in labels]
            props = self._axis_props(axis)
            if labels:
                props["tick_labels"] = labels
            else:
                # matplotlib: xticklabels=[] hides labels but keeps the ticks.
                props.pop("tick_labels", None)
                props["tick_label_strategy"] = "off"
        self._invalidate()
        return self

    def set_xlim(self, left: Any = None, right: Any = None) -> None:
        if isinstance(left, (tuple, list)):
            left, right = left
        current = self._axis_props("x").get("domain")
        lo, hi = current if current is not None else self._entry_extent("x")
        spec = (self._y2_of or self)._scale_specs["x"]
        current_original = _scale_values(np.asarray((lo, hi)), spec, inverse=True)
        start = float(current_original[0] if left is None else left)
        end = float(current_original[1] if right is None else right)
        transformed = _scale_values(np.asarray((start, end)), spec)
        self._axis_props("x")["domain"] = tuple(sorted(map(float, transformed)))
        self._axis_props("x")["reverse"] = start > end
        self._explicit_domains.add("x")
        self._invalidate()

    def get_xlim(self) -> tuple[float, float]:
        lo, hi = self._axis_props("x").get("domain", self._auto_domain("x"))
        lo, hi = map(
            float,
            _scale_values(
                np.asarray((lo, hi)), (self._y2_of or self)._scale_specs["x"], inverse=True
            ),
        )
        return (hi, lo) if self._axis_props("x").get("reverse") else (lo, hi)

    def set_ylim(self, bottom: Any = None, top: Any = None) -> None:
        if isinstance(bottom, (tuple, list)):
            bottom, top = bottom
        current = self._axis_props("y").get("domain")
        lo, hi = current if current is not None else self._entry_extent("y")
        key = "y2" if self._y2_of is not None else "y"
        spec = (self._y2_of or self)._scale_specs[key]
        current_original = _scale_values(np.asarray((lo, hi)), spec, inverse=True)
        start = float(current_original[0] if bottom is None else bottom)
        end = float(current_original[1] if top is None else top)
        transformed = _scale_values(np.asarray((start, end)), spec)
        self._axis_props("y")["domain"] = tuple(sorted(map(float, transformed)))
        self._axis_props("y")["reverse"] = start > end
        self._explicit_domains.add("y")
        self._invalidate()

    def get_ylim(self) -> tuple[float, float]:
        lo, hi = self._axis_props("y").get("domain", self._auto_domain("y"))
        key = "y2" if self._y2_of is not None else "y"
        lo, hi = map(
            float,
            _scale_values(
                np.asarray((lo, hi)), (self._y2_of or self)._scale_specs[key], inverse=True
            ),
        )
        return (hi, lo) if self._axis_props("y").get("reverse") else (lo, hi)

    def get_position(self, original: bool = False) -> Bbox:
        del original  # compat-noop: shim axes have no active/original position split
        return Bbox.from_bounds(*(self._figure_rect or (0.125, 0.11, 0.775, 0.77)))

    def set_position(self, position: Any) -> None:
        self._figure_rect = _parse_bounds(position, "set_position()")
        self._invalidate()

    def _axis_holds_datetimes(self, axis: str) -> bool:
        from xy.components import _is_datetime_like

        key = "x" if axis == "x" else "y"
        return any(key in entry and _is_datetime_like(entry[key]) for entry in self._entries)

    def _data_coordinate(self, value: Any, axis: str) -> Optional[float]:
        """A data-space coordinate as the engine's float — numbers directly,
        datetime-likes (and, on a datetime axis, matplotlib's registry-parsed
        date strings) as ms since epoch. None means not coordinate-like."""
        if _is_number(value):
            return float(value)
        if isinstance(value, str):
            value = _parse_date_text(value) if self._axis_holds_datetimes(axis) else None
            if value is None:
                return None
        try:
            converted = np.asarray(
                unit_converted_values(np.asarray([value])), dtype=np.float64
            ).reshape(-1)
        except (TypeError, ValueError):
            return None
        return float(converted[0]) if converted.size and np.isfinite(converted[0]) else None

    def _data_coordinates(self, xy: tuple) -> Optional[tuple[float, float]]:
        x = self._data_coordinate(xy[0], "x")
        y = self._data_coordinate(xy[1], "y")
        return None if x is None or y is None else (x, y)

    def _entry_values(self, axis: str) -> np.ndarray:
        """Every finite data coordinate the entries contribute to *axis* autoscale."""
        values: list[np.ndarray] = []
        for entry in self._entries:
            key = "x" if axis == "x" else "y"
            if key in entry:
                try:
                    array = np.asarray(unit_converted_values(entry[key]), dtype=np.float64).reshape(
                        -1
                    )
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
                if factory == "contour":
                    z = np.asarray(entry["args"][0])
                    coordinates = entry.get("kwargs", {}).get(key)
                    if coordinates is None and z.ndim >= 2:
                        coordinates = np.arange(z.shape[1 if axis == "x" else 0], dtype=float)
                    if coordinates is not None:
                        array = np.asarray(coordinates, dtype=np.float64).reshape(-1)
                        values.append(array[np.isfinite(array)])
            elif entry.get("kind") == "heatmap" and entry.get("extent") is not None:
                bounds = entry["extent"]
                values.append(np.asarray(bounds[:2] if axis == "x" else bounds[2:], dtype=float))
        return np.concatenate(values) if values else np.array([], dtype=np.float64)

    def _entry_extent(self, axis: str) -> tuple[float, float]:
        finite = self._entry_values(axis)
        if len(finite) == 0:
            return (0.0, 1.0)
        lo, hi = float(np.min(finite)), float(np.max(finite))
        return (lo, hi if hi > lo else lo + 1.0)

    def _auto_domain(self, axis: str) -> tuple[float, float]:
        lo, hi = self._entry_extent(axis)
        margin = self._xmargin if axis == "x" else self._ymargin
        if margin == 0.0:
            return lo, hi
        span = hi - lo
        pad = span * margin if span > 0 else abs(lo) * margin or margin
        return lo - pad, hi + pad

    def axis(self, arg: Any = None, **kwargs: Any) -> tuple[float, float, float, float]:
        kwargs.pop("emit", None)  # compat-noop: callback emission is not exposed
        if isinstance(arg, bool):
            arg = "on" if arg else "off"
        if isinstance(arg, str):
            arg = arg.lower()

        if isinstance(arg, (tuple, list)):
            if len(arg) != 4:
                raise TypeError("the first argument to axis() must be [xmin, xmax, ymin, ymax]")
            self.set_xlim(arg[0], arg[1])
            self.set_ylim(arg[2], arg[3])
        elif arg == "off":
            self._materialize_axis_view_domains()
            self.set_axis_off()
        elif arg == "on":
            self._materialize_axis_view_domains()
            self.xaxis.set_visible(True)
            self.yaxis.set_visible(True)
        elif arg in {"auto", "equal", "scaled", "image", "square"}:
            # All five Matplotlib modes begin with autoscale_view(tight=False),
            # whose limits include the configured x/y margins.
            self._aspect_equal = False
            self._aspect_adjustable = "box"
            self._aspect_bounds = None
            self._set_tight_domains()
            if arg in {"equal", "scaled", "image", "square"}:
                self._set_aspect_equal_from_current()
            if arg == "equal":
                # Matplotlib spells axis("equal") as
                # set_aspect("equal", adjustable="datalim"): retain the axes
                # rectangle and expand a data limit at draw time.
                self._aspect_adjustable = "datalim"
            if arg in {"scaled", "image"}:
                x0, x1 = self.get_xlim()
                y0, y1 = self.get_ylim()
                self._set_box_aspect_ratio(abs(x1 - x0) / max(abs(y1 - y0), 1e-12))
            if arg == "square":
                x0, x1 = self.get_xlim()
                y0, y1 = self.get_ylim()
                edge = max(abs(x1 - x0), abs(y1 - y0))
                self.set_xlim(x0, x0 + edge)
                self.set_ylim(y0, y0 + edge)
                self._aspect_bounds = (x0, x0 + edge, y0, y0 + edge)
                self._set_box_aspect_ratio(1.0)
        elif arg == "tight":
            self._aspect_equal = False
            self._aspect_adjustable = "box"
            self._aspect_bounds = None
            self._set_tight_domains()
        elif arg is not None:
            raise ValueError(f"unsupported axis() argument {arg!r}")

        if arg is None:
            self._materialize_axis_view_domains()
            limits = {}
            for axis_name in ("x", "y"):
                lower = kwargs.pop(f"{axis_name}min", None)
                upper = kwargs.pop(f"{axis_name}max", None)
                if lower is not None or upper is not None:
                    limits[axis_name] = (lower, upper)
            if "x" in limits:
                x0, x1 = self.get_xlim()
                lower, upper = limits["x"]
                self.set_xlim(x0 if lower is None else lower, x1 if upper is None else upper)
            if "y" in limits:
                y0, y1 = self.get_ylim()
                lower, upper = limits["y"]
                self.set_ylim(y0 if lower is None else lower, y1 if upper is None else upper)

        if kwargs:
            raise TypeError(f"axis() got an unexpected keyword argument {next(iter(kwargs))!r}")
        x0, x1 = self.get_xlim()
        y0, y1 = self.get_ylim()
        return float(x0), float(x1), float(y0), float(y1)

    def set_aspect(self, aspect: Any, **kwargs: Any) -> None:
        adjustable = kwargs.pop("adjustable", None)
        # anchor/share are accepted compatibility hints; the shim has no
        # independent Artist layout graph on which to apply them.
        kwargs.pop("anchor", None)  # compat-noop: axes anchoring has no separate layout graph
        kwargs.pop("share", None)  # compat-noop: aspect sharing is resolved by shared axis state
        if kwargs:
            raise TypeError(
                f"set_aspect() got an unexpected keyword argument {next(iter(kwargs))!r}"
            )
        if adjustable is not None:
            if adjustable not in {"box", "datalim"}:
                raise ValueError("adjustable must be 'box' or 'datalim'")
            self._aspect_adjustable = adjustable
        self._aspect_equal = aspect in ("equal", 1, 1.0)
        if self._aspect_equal:
            self._set_aspect_equal_from_current()
        else:
            self._aspect_bounds = None
            self._invalidate()

    def margins(self, *args: Any, **kwargs: Any) -> None:
        tight = kwargs.pop("tight", None)
        del tight
        x = kwargs.pop("x", None)
        y = kwargs.pop("y", None)
        if kwargs:
            raise TypeError(f"margins() got unsupported keyword argument {next(iter(kwargs))!r}")
        if len(args) > 2:
            raise TypeError("margins() takes at most two positional arguments")
        if len(args) == 1:
            x = y = args[0]
        elif len(args) == 2:
            x, y = args
        if x is None and y is None:
            return
        if x is not None:
            self._xmargin = _validate_margin(x, "x")
            self._margin_overrides.add("x")
            if "x" not in self._explicit_domains:
                self._axis_props("x").pop("domain", None)
        if y is not None:
            self._ymargin = _validate_margin(y, "y")
            self._margin_overrides.add("y")
            if "y" not in self._explicit_domains:
                self._axis_props("y").pop("domain", None)
        self._invalidate()

    def relim(self, visible_only: bool = False) -> None:
        del visible_only  # compat-noop: invisible entries retain the same data extent
        for axis in ("x", "y"):
            if axis not in self._explicit_domains:
                self._axis_props(axis).pop("domain", None)
        self._invalidate()

    def autoscale(
        self, enable: bool = True, axis: str = "both", tight: Optional[bool] = None
    ) -> None:
        if axis not in {"both", "x", "y"}:
            raise ValueError("autoscale() axis must be 'both', 'x', or 'y'")
        axes = ("x", "y") if axis == "both" else (axis,)
        for item in axes:
            if enable:
                self._explicit_domains.discard(item)
                if tight:
                    self._axis_props(item)["domain"] = self._entry_extent(item)
                    self._explicit_domains.add(item)
                else:
                    self._axis_props(item).pop("domain", None)
            else:
                self._axis_props(item)["domain"] = self._auto_domain(item)
                self._explicit_domains.add(item)
        self._invalidate()

    def autoscale_view(
        self, tight: Optional[bool] = None, scalex: bool = True, scaley: bool = True
    ) -> None:
        if scalex:
            self.autoscale(True, axis="x", tight=tight)
        if scaley:
            self.autoscale(True, axis="y", tight=tight)

    def get_xbound(self) -> tuple[float, float]:
        return self.get_xlim()

    def set_xbound(self, lower: Any = None, upper: Any = None) -> None:
        if isinstance(lower, (tuple, list)):
            lower, upper = lower
        current = self.get_xlim()
        self.set_xlim(
            current[0] if lower is None else lower, current[1] if upper is None else upper
        )

    def get_ybound(self) -> tuple[float, float]:
        return self.get_ylim()

    def set_ybound(self, lower: Any = None, upper: Any = None) -> None:
        if isinstance(lower, (tuple, list)):
            lower, upper = lower
        current = self.get_ylim()
        self.set_ylim(
            current[0] if lower is None else lower, current[1] if upper is None else upper
        )

    def ticklabel_format(self, **kwargs: Any) -> None:
        axis = kwargs.pop("axis", "both")
        style = kwargs.pop("style", None)
        scilimits = kwargs.pop("scilimits", None)
        use_offset = kwargs.pop("useOffset", kwargs.pop("useoffset", None))
        use_locale = kwargs.pop("useLocale", None)
        use_math_text = kwargs.pop("useMathText", None)
        if use_locale not in (None, False):
            raise not_implemented("ticklabel_format(useLocale=True)")
        if use_math_text not in (None, False):
            raise not_implemented("ticklabel_format(useMathText=True)")
        if kwargs:
            raise TypeError(
                f"ticklabel_format() got unsupported keyword argument {next(iter(kwargs))!r}"
            )
        if axis not in {"both", "x", "y"}:
            raise ValueError("ticklabel_format() axis must be 'both', 'x', or 'y'")
        if style not in {None, "plain", "sci", "scientific"}:
            raise ValueError("ticklabel_format() style must be 'plain' or 'sci'")
        for item in ("x", "y") if axis == "both" else (axis,):
            props = self._axis_props(item)
            props["tick_label_format"] = {
                "style": "sci" if style == "scientific" else style,
                "scilimits": None if scilimits is None else tuple(scilimits),
                "use_offset": use_offset,
            }
        self._invalidate()

    def minorticks_on(self) -> None:
        self._axis_props("x")["minor_ticks"] = True
        self._axis_props("y")["minor_ticks"] = True
        self._invalidate()

    def minorticks_off(self) -> None:
        self._axis_props("x")["minor_ticks"] = False
        self._axis_props("y")["minor_ticks"] = False
        self._invalidate()

    def get_xlabel(self) -> str:
        return str(self._axis_props("x").get("label", ""))

    def get_ylabel(self) -> str:
        return str(self._axis_props("y").get("label", ""))

    def get_title(self) -> str:
        return "" if self._title is None else str(self._title)

    def get_xaxis(self) -> _AxisProxy:
        return self.xaxis

    def get_yaxis(self) -> _AxisProxy:
        return self.yaxis

    def get_figure(self, root: Any = None) -> Any:
        del root  # compat-noop: no nested subfigures; both roots are self.figure
        return self.figure

    def get_lines(self) -> list[Line2D]:
        host = self._y2_of or self
        return [artist for artist in host._owned_artists if isinstance(artist, Line2D)]

    def get_shared_x_axes(self) -> _SharedAxesGroup:
        return _SharedAxesGroup("x")

    def get_shared_y_axes(self) -> _SharedAxesGroup:
        return _SharedAxesGroup("y")

    def get_xticklabels(self) -> list[_TickLabel]:
        return self._tick_label_handles("x")

    def get_yticklabels(self) -> list[_TickLabel]:
        return self._tick_label_handles("y")

    def _tick_label_handles(self, axis: str) -> list[_TickLabel]:
        labels = self._axis_props(axis).get("tick_labels")
        if labels is None:
            labels = [f"{value:g}" for value in self._computed_ticks(axis, False)]
        return [_TickLabel(self, axis, str(text)) for text in labels]

    def set_facecolor(self, color: Any) -> None:
        resolved = resolve_color(color)
        if resolved is not None:
            self._theme_tokens["plot_background"] = resolved
        self._invalidate()

    def get_facecolor(self) -> Any:
        return self._theme_tokens.get("plot_background")

    def set_axisbelow(self, b: Any) -> None:
        # The engine composites grid lines beneath data marks unconditionally,
        # which is exactly axisbelow=True; other orders are not expressible.
        if b is not True:
            raise not_implemented(
                f"set_axisbelow({b!r})", "the engine's fixed grid-below-marks order"
            )

    def get_legend(self) -> Any:
        return self if (self._y2_of or self)._legend else None

    def get_legend_handles_labels(self) -> tuple[list[Artist], list[str]]:
        handles: list[Artist] = []
        labels: list[str] = []
        for entry in (self._y2_of or self)._entries:
            label = entry.get("kwargs", {}).get("name")
            if label and not str(label).startswith("_"):
                handles.append(Artist(self, entry))
                labels.append(str(label))
        return handles, labels

    def set_prop_cycle(self, *args: Any, **kwargs: Any) -> None:
        if args and kwargs:
            raise TypeError("set_prop_cycle() accepts positional or keyword form, not both")
        colors = None
        if len(args) == 1:
            cycle = args[0]
            if hasattr(cycle, "by_key"):
                colors = cycle.by_key().get("color")
            elif isinstance(cycle, dict):
                colors = cycle.get("color")
        elif len(args) == 2 and args[0] == "color":
            colors = args[1]
        elif len(args) > 0:
            raise NotImplementedError("xy.pyplot set_prop_cycle() only supports color cycles")
        elif kwargs:
            unsupported = set(kwargs) - {"color"}
            if unsupported:
                raise NotImplementedError("xy.pyplot set_prop_cycle() only supports color cycles")
            colors = kwargs.get("color")
        if colors is None:
            self._prop_cycle = None
        else:
            self._prop_cycle = [
                resolved for color in colors if (resolved := resolve_color(color)) is not None
            ]
        self._cycle = 0
        self._invalidate()

    def secondary_xaxis(
        self, location: Any = "top", functions: Any = None, *, transform: Any = None
    ) -> SecondaryAxis:
        if transform is not None:
            raise not_implemented("secondary_xaxis(transform=...)")
        made = SecondaryAxis(self, "x", location, functions)
        self._secondary_axes.append(made)
        self._invalidate()
        return made

    def secondary_yaxis(
        self, location: Any = "right", functions: Any = None, *, transform: Any = None
    ) -> SecondaryAxis:
        if transform is not None:
            raise not_implemented("secondary_yaxis(transform=...)")
        made = SecondaryAxis(self, "y", location, functions)
        self._secondary_axes.append(made)
        self._invalidate()
        return made

    def _set_tight_domains(self) -> None:
        # Matplotlib's axis("tight") disables further autoscaling after an
        # autoscale_view(tight=True), but that view still includes the current
        # axes.xmargin/axes.ymargin (5% by default).  "Tight" suppresses tick
        # locator expansion; it does not mean raw data extrema.
        for axis in ("x", "y"):
            margin = (
                (self._xmargin if axis == "x" else self._ymargin)
                if axis in self._margin_overrides
                else float(rcParams[f"axes.{axis}margin"])
            )
            lo, hi = self._entry_extent(axis)
            span = hi - lo
            pad = span * margin if span > 0 else abs(lo) * margin or margin
            self._axis_props(axis)["domain"] = (lo - pad, hi + pad)
        self._explicit_domains.update({"x", "y"})
        self._invalidate()

    def _materialize_axis_view_domains(self) -> None:
        """Expose Matplotlib-like auto limits for axis query/decorative forms."""
        if not self._entries:
            return
        changed = False
        for axis in ("x", "y"):
            if "domain" in self._axis_props(axis):
                continue
            margin = (
                (self._xmargin if axis == "x" else self._ymargin)
                if axis in self._margin_overrides
                else float(rcParams[f"axes.{axis}margin"])
            )
            lo, hi = self._entry_extent(axis)
            pad = (hi - lo) * margin
            self._axis_props(axis)["domain"] = (lo - pad, hi + pad)
            changed = True
        if changed:
            self._invalidate()

    def _set_aspect_equal_from_current(self) -> None:
        x0, x1 = self._axis_props("x").get("domain", self._auto_domain("x"))
        y0, y1 = self._axis_props("y").get("domain", self._auto_domain("y"))
        self._aspect_equal = True
        self._aspect_bounds = (float(x0), float(x1), float(y0), float(y1))
        self._invalidate()

    def _set_box_aspect_ratio(self, ratio: float) -> None:
        """Center a Matplotlib-style adjustable box for one ordinary axes."""
        if self.figure is None or len(self.figure.axes) != 1:
            # Multi-panel box placement belongs to the grid compositor.  Keep
            # equal-unit domain rendering there rather than turning one subplot
            # into a free-form figure rectangle that overlaps its neighbors.
            return
        figure_width, figure_height = self.figure._panel_px()
        x0, y0, width, height = self.get_position().bounds
        current = (width * figure_width) / max(height * figure_height, 1e-12)
        if current > ratio:
            new_width = height * figure_height * ratio / figure_width
            x0 += (width - new_width) * 0.5
            width = new_width
        elif current < ratio:
            new_height = width * figure_width / ratio / figure_height
            y0 += (height - new_height) * 0.5
            height = new_height
        self._figure_rect = (x0, y0, width, height)
        self._absolute_plot_ratio = ratio
        self._invalidate()

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
                    "args": (
                        [x0, x1, x1, x0],
                        [y0, y0, y1, y1],
                        [x1, x1, x0, x0],
                        [y0, y1, y1, y0],
                    ),
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
        if isinstance(artist, Legend):
            host = self._y2_of or self
            artist._attach(host)
            host._extra_legends.append(artist)
            host._invalidate()
            return artist
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
                extent = (
                    None
                    if bounds is None
                    else (bounds[0], bounds[0] + bounds[2], bounds[1], bounds[1] + bounds[3])
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
        raise TypeError(
            f"unsupported Artist {type(artist).__name__}; use text(), imshow(), "
            "add_line(), add_patch(), or add_collection()"
        )

    def add_line(self, line: Any) -> Line2D:
        if isinstance(line, Line2D):
            if line._axes is not self:
                raise ValueError("cannot move a Line2D between Axes")
            return line
        get_data = getattr(line, "get_data", None)
        if get_data is None:
            raise TypeError(
                f"unsupported line {type(line).__name__}; add_line() requires Line2D-like get_data()"
            )
        x, y = get_data()
        kwargs: dict[str, Any] = {}
        for getter_name, target in (
            ("get_color", "color"),
            ("get_label", "label"),
            ("get_linewidth", "linewidth"),
            ("get_alpha", "alpha"),
        ):
            getter = getattr(line, getter_name, None)
            if getter is not None:
                value = getter()
                if value is not None:
                    kwargs[target] = value
        return self.plot(x, y, **kwargs)[0]

    def add_container(self, container: Any) -> Any:
        from ._artists import BarContainer, ErrorbarContainer, StemContainer

        if not isinstance(container, (BarContainer, ErrorbarContainer, StemContainer)):
            raise TypeError(
                f"unsupported container {type(container).__name__}; supported containers are "
                "BarContainer, ErrorbarContainer, and StemContainer"
            )
        self._register_container(container)
        return container

    def add_table(self, table: Any) -> Any:
        from ._artists import Table

        if not isinstance(table, Table):
            raise TypeError(
                f"unsupported table {type(table).__name__}; create tables with Axes.table()"
            )
        if getattr(table, "_axes", self) is not self:
            raise ValueError("cannot move a Table between Axes")
        self._register_artist(table)
        return table

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
                    np.abs(target_x - x_values[x_left]) <= np.abs(target_x - x_values[x_right]),
                    x_left,
                    x_right,
                )
                y_right = np.searchsorted(y_values, target_y)
                y_right = np.clip(y_right, 0, len(y_values) - 1)
                y_left = np.clip(y_right - 1, 0, len(y_values) - 1)
                y_index = np.where(
                    np.abs(target_y - y_values[y_left]) <= np.abs(target_y - y_values[y_right]),
                    y_left,
                    y_right,
                )
                data = data[np.ix_(y_index, x_index)]
            else:
                horizontal = np.vstack([np.interp(target_x, x_values, row) for row in data])
                data = np.vstack(
                    [
                        np.interp(target_y, y_values, horizontal[:, col])
                        for col in range(horizontal.shape[1])
                    ]
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

    def set_xscale(self, scale: str, **kwargs: Any) -> None:
        self._set_scale("x", scale, kwargs)

    def set_yscale(self, scale: str, **kwargs: Any) -> None:
        self._set_scale("y", scale, kwargs)

    def _set_scale(self, axis: str, scale: str, kwargs: Optional[dict[str, Any]] = None) -> None:
        kwargs = {} if kwargs is None else dict(kwargs)
        if scale not in ("linear", "log", "symlog", "logit", "asinh"):
            raise ValueError(f"unknown {axis} scale {scale!r}")
        host = self._y2_of or self
        key = "y2" if axis == "y" and self._y2_of is not None else axis
        old = host._scale_specs[key]
        if scale == "linear" and kwargs:
            check_unsupported(kwargs, f"set_{axis}scale('linear')")
        if scale == "log":
            base = kwargs.pop("base", 10)
            subs = kwargs.pop("subs", None)
            nonpositive = kwargs.pop("nonpositive", "clip")
            check_unsupported(kwargs, f"set_{axis}scale('log')")
            if float(base) != 10.0:
                raise not_implemented(f"set_{axis}scale('log', base={base!r})")
            if subs is not None:
                raise not_implemented(f"set_{axis}scale('log', subs=...)")
            if nonpositive != "clip":
                raise not_implemented(f"set_{axis}scale('log', nonpositive={nonpositive!r})")
        new: dict[str, Any]
        if scale == "symlog":
            new = {
                "name": scale,
                "base": float(kwargs.pop("base", 10.0)),
                "linthresh": float(kwargs.pop("linthresh", 2.0)),
                "linscale": float(kwargs.pop("linscale", 1.0)),
            }
        elif scale == "asinh":
            new = {"name": scale, "linear_width": float(kwargs.pop("linear_width", 1.0))}
        else:
            new = {"name": scale}
        check_unsupported(kwargs, f"set_{axis}scale({scale!r})")
        if scale == "symlog" and (
            new["base"] <= 1 or new["linthresh"] <= 0 or new["linscale"] <= 0
        ):
            raise ValueError(f"set_{axis}scale({scale!r}) parameters must be positive")
        if scale == "asinh" and new["linear_width"] <= 0:
            raise ValueError(f"set_{axis}scale({scale!r}) parameters must be positive")
        for entry in host._entries:
            if axis == "y" and entry.get("y_axis", "y") != key:
                continue
            _transform_entry_axis(entry, axis, old, new)
        props = self._axis_props(axis)
        if "domain" in props:
            props["domain"] = tuple(
                map(float, _scale_values(_scale_values(props["domain"], old, inverse=True), new))
            )
        if key in host._auto_scale_axis_ticks:
            # ticks generated for the previous scale, not user-set:
            # regenerate for the new scale instead of converting them
            props.pop("tick_values", None)
            props.pop("tick_labels", None)
            props.pop("tick_count", None)
            host._auto_scale_axis_ticks.discard(key)
        if "tick_values" in props:
            labels = props.get("tick_labels") or [
                f"{v:g}" for v in _scale_values(props["tick_values"], old, inverse=True)
            ]
            props["tick_values"] = list(
                map(
                    float,
                    _scale_values(_scale_values(props["tick_values"], old, inverse=True), new),
                )
            )
            props["tick_labels"] = labels
        elif scale in {"symlog", "logit", "asinh"}:
            ticks = _nonlinear_ticks(self._entry_extent(axis), new)
            props["tick_values"] = list(map(float, _scale_values(ticks, new)))
            props["tick_labels"] = [f"{tick:g}" for tick in ticks]
            props["tick_count"] = max(1, len(ticks))
            host._auto_scale_axis_ticks.add(key)
        host._scale_specs[key] = new
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
        if axis not in {"both", "x", "y"}:
            raise ValueError("tick_params() axis must be 'both', 'x', or 'y'")
        rotation = kwargs.pop("labelrotation", kwargs.pop("rotation", None))
        colors = kwargs.pop("colors", None)
        color = kwargs.pop("color", colors)
        labelcolor = kwargs.pop("labelcolor", colors)
        length = kwargs.pop("length", None)
        width = kwargs.pop("width", None)
        direction = kwargs.pop("direction", None)
        label_visible = _tick_label_visibility(kwargs)
        if kwargs:
            raise TypeError(
                f"tick_params() got unsupported keyword argument {next(iter(kwargs))!r}"
            )
        for ax in ("x", "y") if axis == "both" else (axis,):
            props = self._axis_props(ax)
            if rotation is not None:
                props["tick_label_angle"] = float(rotation)
            style = props.setdefault("style", {})
            if color is not None:
                style["tick_color"] = resolve_color(color)
            if labelcolor is not None:
                style["tick_label_color"] = resolve_color(labelcolor)
            if length is not None:
                style["tick_length"] = float(length) * self._point_scale()
            if width is not None:
                style["tick_width"] = float(width) * self._point_scale()
            if direction is not None:
                if direction not in {"in", "out", "inout"}:
                    raise ValueError("tick_params() direction must be 'in', 'out', or 'inout'")
                style["tick_direction"] = direction
            if label_visible is not None:
                props["tick_label_strategy"] = None if label_visible else "off"
        self._invalidate()

    def set_xticks(
        self, ticks: Any, labels: Any = None, *, rotation: Any = None, **kwargs: Any
    ) -> None:
        if kwargs.pop("minor", False):
            return
        props = self._axis_props("x")
        if ticks is not None:
            spec = (self._y2_of or self)._scale_specs["x"]
            (self._y2_of or self)._auto_scale_axis_ticks.discard("x")
            (self._y2_of or self)._tickers.pop(("x", "major_locator"), None)
            props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
            props["tick_count"] = max(1, len(props["tick_values"]))
            if labels is None:
                if spec and spec.get("name") != "linear":
                    # exporters see transformed positions; label the originals
                    props["tick_labels"] = [
                        f"{tick:g}" for tick in np.asarray(ticks, dtype=float).reshape(-1)
                    ]
                else:
                    props.pop("tick_labels", None)
        if labels is not None:
            props["tick_labels"] = [_plain_text(value) for value in labels]
            if len(props["tick_labels"]) != len(props.get("tick_values", [])):
                raise ValueError("labels must have the same length as ticks")
            # matplotlib: explicit labels install a FixedFormatter, displacing
            # any user formatter.
            (self._y2_of or self)._tickers.pop(("x", "major_formatter"), None)
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
            key = "y2" if self._y2_of is not None else "y"
            spec = (self._y2_of or self)._scale_specs[key]
            (self._y2_of or self)._auto_scale_axis_ticks.discard(key)
            (self._y2_of or self)._tickers.pop((key, "major_locator"), None)
            props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
            props["tick_count"] = max(1, len(props["tick_values"]))
            if labels is None:
                if spec and spec.get("name") != "linear":
                    # exporters see transformed positions; label the originals
                    props["tick_labels"] = [
                        f"{tick:g}" for tick in np.asarray(ticks, dtype=float).reshape(-1)
                    ]
                else:
                    props.pop("tick_labels", None)
        if labels is not None:
            props["tick_labels"] = [_plain_text(value) for value in labels]
            if len(props["tick_labels"]) != len(props.get("tick_values", [])):
                raise ValueError("labels must have the same length as ticks")
            key = "y2" if self._y2_of is not None else "y"
            (self._y2_of or self)._tickers.pop((key, "major_formatter"), None)
        if rotation is not None:
            props["tick_label_angle"] = float(rotation)
        self._invalidate()

    def get_xticks(self, *, minor: bool = False) -> np.ndarray:
        return self._computed_ticks("x", minor)

    def get_yticks(self, *, minor: bool = False) -> np.ndarray:
        return self._computed_ticks("y", minor)

    def _computed_ticks(self, axis: str, minor: bool) -> np.ndarray:
        props = self._axis_props(axis)
        if minor:
            return np.asarray(props.get("minor_tick_values", []), dtype=float)
        if "tick_values" in props:
            key = "y2" if axis == "y" and self._y2_of is not None else axis
            return np.asarray(
                _scale_values(
                    props["tick_values"], (self._y2_of or self)._scale_specs[key], inverse=True
                ),
                dtype=float,
            )
        # Auto-ticked axes report the same nice locations the exporters draw.
        from xy._svg import _linear_ticks, _log_ticks

        lo, hi = sorted(self.get_xlim() if axis == "x" else self.get_ylim())
        if not (np.isfinite(lo) and np.isfinite(hi)) or lo == hi:
            return np.asarray([], dtype=float)
        host = self._y2_of or self
        key = "y2" if (axis == "y" and self._y2_of is not None) else axis
        locator = host._tickers.get((key, "major_locator"))
        if locator is not None:
            ticks = np.asarray(locator.tick_values(lo, hi), dtype=float).reshape(-1)
            pad = (hi - lo) * 1e-9
            return ticks[(ticks >= lo - pad) & (ticks <= hi + pad)]
        if props.get("type_") == "log":
            return np.asarray(_log_ticks(float(lo), float(hi))[0], dtype=float)
        return np.asarray(_linear_ticks(float(lo), float(hi))[0], dtype=float)

    def set_anchor(self, anchor: Any) -> None:
        if anchor is False:
            self._anchor = None
            self._invalidate()
            return
        normalized = str(anchor).upper()
        if normalized not in {"C", "SW", "S", "SE", "E", "NE", "N", "NW", "W"}:
            raise ValueError(f"unsupported anchor mode {anchor!r}")
        self._anchor = normalized
        self._invalidate()

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

    def twiny(self) -> "Axes":
        if self.figure is None:
            raise ValueError("twiny() requires an Axes attached to a Figure")
        twin = Axes(self.figure)
        twin._axis["y"] = self._axis_props("y")
        self.figure._axes.append(twin)
        self.figure._current_ax = twin
        self.figure._invalidate()
        return twin

    def legend(self, *args: Any, **kwargs: Any) -> None:
        host = self._y2_of or self
        if len(args) >= 2:
            # legend(handles, labels): relabel the artists the caller passed.
            handles, labels = args[0], args[1]
            for handle, label in zip(handles, labels, strict=False):
                entry = getattr(handle, "_entry", None)
                if entry is not None:
                    entry.setdefault("kwargs", {})["name"] = _plain_text(label)
        elif len(args) == 1:
            # legend(labels): assign labels positionally to the plotted artists,
            # skipping marker overlays that share their line's legend slot.
            labels = args[0]
            eligible = [entry for entry in host._entries if not entry.get("_legend_skip")]
            for entry, label in zip(eligible, labels, strict=False):
                entry.setdefault("kwargs", {})["name"] = _plain_text(label)
        host._legend = True
        host._legend_options = self._compose_legend_options(kwargs)
        host._invalidate()

    def _compose_legend_options(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Translate legend() keyword styling into the engine's option dict.

        Shared by ``Axes.legend`` and the standalone ``Legend`` artist so a
        second, manually added legend honors the same loc/frame/font keywords.
        """
        loc = kwargs.pop("loc", rcParams["legend.loc"])
        ncols = kwargs.pop("ncols", kwargs.pop("ncol", 1))
        title = kwargs.pop("title", None)
        fontsize = kwargs.pop("fontsize", None)
        prop = kwargs.pop("prop", None)
        if prop is not None:
            if not isinstance(prop, dict):
                raise not_implemented("legend(prop=FontProperties)", "prop={'size': ...}")
            prop = dict(prop)
            size = prop.pop("size", None)
            if fontsize is None:
                fontsize = size
            if prop:
                raise not_implemented(
                    f"legend(prop={{{sorted(prop)[0]!r}: ...}})", "prop={'size': ...}"
                )
        if fontsize is None:
            fontsize = rcParams["legend.fontsize"]
        labelcolor = kwargs.pop("labelcolor", None)
        frameon = kwargs.pop("frameon", rcParams["legend.frameon"])
        facecolor = kwargs.pop("facecolor", rcParams["legend.facecolor"])
        edgecolor = kwargs.pop("edgecolor", rcParams["legend.edgecolor"])
        framealpha = kwargs.pop("framealpha", None)
        fancybox = kwargs.pop("fancybox", False)
        shadow = kwargs.pop("shadow", False)
        borderpad = kwargs.pop("borderpad", None)
        labelspacing = kwargs.pop("labelspacing", None)
        # Remaining handle/title geometry is not expressible yet and stays
        # loud; the frame and row-layout options above map directly to CSS and
        # the static exporters.
        layout_options = {
            key: kwargs.pop(key)
            for key in (
                "title_fontsize",
                "handlelength",
                "handletextpad",
            )
            if key in kwargs
        }
        if layout_options:
            raise not_implemented(
                f"legend({sorted(layout_options)[0]}=...)",
                "loc, ncols, title, fontsize, colors, and frame styling",
            )
        # The engine legend draws one swatch per entry, which is exactly the
        # matplotlib default; only the default values are expressible.
        for key, default in (("numpoints", 1), ("scatterpoints", 1)):
            if key in kwargs and int(kwargs.pop(key)) != default:
                raise not_implemented(f"legend({key}=...)", f"the matplotlib default ({default})")
        unsupported = set(kwargs)
        if unsupported:
            raise TypeError(f"legend() got unsupported keyword argument {sorted(unsupported)[0]!r}")
        style: dict[str, Any] = {}
        if fontsize is not None:
            style["fontSize"] = (
                f"{_font_size(fontsize, rcParams['font.size'], self._point_scale() * 72.0):g}px"
            )
        if labelcolor is not None:
            style["color"] = resolve_color(labelcolor)
        if frameon is False:
            style["background"] = "transparent"
            style["borderColor"] = "transparent"
        else:
            if facecolor == "inherit":
                facecolor = rcParams["axes.facecolor"]
            if facecolor is not None:
                style["background"] = resolve_color(facecolor)
            if edgecolor is not None:
                style["borderColor"] = resolve_color(edgecolor)
                style["borderStyle"] = "solid"
        if framealpha is not None:
            alpha_value = float(framealpha)
            if not 0.0 <= alpha_value <= 1.0:
                raise ValueError("legend framealpha must be between 0 and 1")
            style["--xy-legend-frame-alpha"] = alpha_value
        if bool(fancybox):
            style["borderRadius"] = "4px"
        if bool(shadow):
            style["boxShadow"] = "2px 2px 4px rgba(0,0,0,0.3)"
        if borderpad is not None:
            padding = float(borderpad)
            if padding < 0:
                raise ValueError("legend borderpad must be non-negative")
            style["padding"] = f"{padding:g}em"
        if labelspacing is not None:
            spacing = float(labelspacing)
            if spacing < 0:
                raise ValueError("legend labelspacing must be non-negative")
            style["rowGap"] = f"{spacing:g}em"
        options: dict[str, Any] = {"loc": loc, "ncols": max(1, int(ncols))}
        if title is not None:
            options["title"] = _plain_text(title)
        if style:
            options["style"] = style
        return options

    def grid(self, visible: Any = True, **kwargs: Any) -> None:
        host = self._y2_of or self
        which = kwargs.pop("which", "major")
        axis = kwargs.pop("axis", "both")
        if which not in {"major", "both"}:
            raise ValueError("grid() only supports major grid lines")
        if axis not in {"both", "x", "y"}:
            raise ValueError("grid() axis must be 'both', 'x', or 'y'")
        color = kwargs.pop("color", kwargs.pop("c", None))
        linestyle = kwargs.pop("linestyle", kwargs.pop("ls", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", None))
        alpha = kwargs.pop("alpha", None)
        if kwargs:
            raise TypeError(f"grid() got unsupported keyword argument {next(iter(kwargs))!r}")
        host._grid = bool(visible) if visible is not None else not host._grid
        host._grid_axis = axis
        style = host._grid_style = {}
        if color is not None and (resolved_grid := resolve_color(color)) is not None:
            host._grid_color = resolved_grid
        if linewidth is not None:
            style["grid_width"] = float(linewidth)
        if linestyle is not None:
            dash = LINESTYLE_TO_DASH.get(linestyle, linestyle)
            if dash is not None:  # solid is the engine default, not a style key
                style["grid_dash"] = dash
        if alpha is not None:
            style["grid_opacity"] = float(alpha)
        grid_color = host._grid_color if host._grid else "transparent"
        for item in ("x", "y"):
            props = host._axis_props(item)
            axis_style = props.setdefault("style", {})
            for stale in ("grid_width", "grid_dash", "grid_opacity"):
                axis_style.pop(stale, None)
            if axis in {"both", item}:
                axis_style["grid_color"] = grid_color
                axis_style.update(style)
            else:
                axis_style["grid_color"] = "transparent"
        host._invalidate()

    def _axis_props(self, axis: str) -> dict[str, Any]:
        host = self._y2_of or self
        key = "y2" if (axis == "y" and self._y2_of is not None) else axis
        return host._axis[key]

    def _ticker_view(self, key: str, props: dict[str, Any]) -> tuple[float, float]:
        """The axis view interval in *data* space, for locator math."""
        axis = "y" if key == "y2" else key
        domain = props.get("domain")
        if domain is None:
            owner = self._twin if (key == "y2" and self._twin is not None) else self
            domain = owner._auto_domain(axis)
        lo, hi = sorted(map(float, domain))
        spec = self._scale_specs.get(key) or {"name": "linear"}
        if spec.get("name") != "linear":
            lo, hi = sorted(map(float, _scale_values(np.asarray([lo, hi]), spec, inverse=True)))
        return lo, hi

    def _apply_tickers(
        self, key: str, props: dict[str, Any], nbins_hint: Optional[int] = None
    ) -> None:
        """Resolve a user locator/formatter into concrete tick props (in place)."""
        from ._ticker import NullFormatter

        locator = self._tickers.get((key, "major_locator"))
        formatter = self._tickers.get((key, "major_formatter"))
        minor_locator = self._tickers.get((key, "minor_locator"))
        minor_formatter = self._tickers.get((key, "minor_formatter"))
        # The engine draws a single tick set. When a script blanks the major
        # labels and puts the text on located minors (matplotlib's centered
        # date-label idiom: major NullFormatter + labeled minor locator), the
        # minor pair is the one carrying information — promote it.
        if (
            isinstance(formatter, NullFormatter)
            and minor_locator is not None
            and hasattr(minor_locator, "tick_values")
            and minor_formatter is not None
            and not isinstance(minor_formatter, NullFormatter)
        ):
            locator, formatter = minor_locator, minor_formatter
        is_log = (
            props.get("type_") == "log" or (self._scale_specs.get(key) or {}).get("name") == "log"
        )
        if locator is None and formatter is None and not is_log:
            return
        spec = self._scale_specs.get(key) or {"name": "linear"}
        lo, hi = self._ticker_view(key, props)
        auto_log = False
        if locator is not None:
            locator._nbins_hint = nbins_hint
            ticks = np.asarray(locator.tick_values(lo, hi), dtype=float).reshape(-1)
            pad = (hi - lo) * 1e-9
            ticks = ticks[(ticks >= lo - pad) & (ticks <= hi + pad)]
        elif "tick_values" in props:
            ticks = np.asarray(
                _scale_values(props["tick_values"], spec, inverse=True), dtype=float
            ).reshape(-1)
        else:
            from ._ticker import LogLocator

            auto = LogLocator() if is_log else AutoLocator()
            auto._nbins_hint = nbins_hint
            ticks = np.asarray(auto.tick_values(lo, hi), dtype=float).reshape(-1)
            if not is_log:
                pad = (hi - lo) * 1e-9
                ticks = ticks[(ticks >= lo - pad) & (ticks <= hi + pad)]
            auto_log = is_log
        props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
        if formatter is not None:
            props["tick_labels"] = [
                _plain_text(formatter(float(value), position))
                for position, value in enumerate(ticks)
            ]
        elif auto_log:
            # matplotlib's LogFormatter look: decades label as 10^k.
            props["tick_labels"] = [_pow10_label(value) for value in ticks]
        elif spec.get("name") != "linear":
            props["tick_labels"] = [f"{value:g}" for value in ticks]
        else:
            props.pop("tick_labels", None)
        if len(ticks):
            props["tick_count"] = len(ticks)
        else:
            props.pop("tick_count", None)

    # -- materialization -----------------------------------------------------------

    def _chart_children(self) -> list[Any]:
        children: list[Any] = []
        for e in self._entries:
            kind = e["kind"]
            axis_kw = {"y_axis": e["y_axis"]} if e["y_axis"] != "y" else {}
            kw = e.get("kwargs", {})
            name = kw.get("name")
            if isinstance(name, str) and "$" in name:  # legend text carries mathtext
                kw["name"] = _plain_text(name)
            if kind == "line":
                kw = dict(kw)
                kw["width"] = (
                    float(kw.get("width", rcParams["lines.linewidth"])) * self._point_scale()
                )
                children.append(fc.line(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "scatter":
                kw = dict(kw)
                domain = kw.pop("domain", None)  # vmin/vmax → the color channel window
                levels = e.get("discrete_levels")
                if levels is not None and "colormap" in kw and not isinstance(kw.get("color"), str):
                    color_vals = np.asarray(kw.get("color"), dtype=np.float64)
                    dom = domain
                    if dom is None:
                        finite = color_vals[np.isfinite(color_vals)]
                        dom = (
                            (float(finite.min()), float(finite.max()))
                            if finite.size
                            else (0.0, 1.0)
                        )
                    kw["color"] = _quantize_to_levels(color_vals, dom, int(levels))
                    domain = dom
                if domain is not None:
                    kw["color_domain"] = (float(domain[0]), float(domain[1]))
                children.append(fc.scatter(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "bar":
                children.append(fc.bar(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "area":
                children.append(fc.area(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "histogram":
                children.append(fc.histogram(values=e["values"], **kw, **axis_kw))
            elif kind == "heatmap":
                z = e["z"]
                levels = e.get("discrete_levels")
                if levels is not None:
                    zarr = np.asarray(z, dtype=np.float64)
                    if zarr.ndim == 2:
                        kw = dict(kw)
                        dom = kw.get("domain")
                        if dom is None:
                            finite = zarr[np.isfinite(zarr)]
                            dom = (
                                (float(finite.min()), float(finite.max()))
                                if finite.size
                                else (0.0, 1.0)
                            )
                        z = _quantize_to_levels(zarr, dom, int(levels))
                        kw["domain"] = (float(dom[0]), float(dom[1]))
                children.append(fc.heatmap(z=z, **kw, **axis_kw))
            elif kind == "@mark":
                children.append(getattr(fc, e["factory"])(*e["args"], **kw, **axis_kw))
            elif kind == "@hline":
                children.append(fc.hline(*e["args"], **kw))
            elif kind == "@arrow":
                children.append(fc.arrow(*e["args"], **kw))
            elif kind == "@vline":
                children.append(fc.vline(*e["args"], **kw))
            elif kind == "@x_band":
                children.append(fc.x_band(*e["args"], **kw))
            elif kind == "@y_band":
                children.append(fc.y_band(*e["args"], **kw))
            elif kind == "@text":
                opacity = kw.get("opacity")
                if opacity is not None and float(opacity) == 0.0:
                    continue  # set_visible(False) must hide text in every exporter
                text_kw = {
                    key: value
                    for key, value in kw.items()
                    if key in {"dx", "dy", "color", "anchor", "class_name", "style"}
                }
                # matplotlib text sits exactly at its anchor point; only offset
                # textcoords set dx/dy, so the callout defaults must not leak in.
                text_kw.setdefault("dx", 0.0)
                text_kw.setdefault("dy", 0.0)
                if "font_size" in (text_kw.get("style") or {}):
                    text_kw["style"] = dict(text_kw["style"])
                    text_kw["style"]["font_size"] = (
                        float(text_kw["style"]["font_size"]) * self._point_scale()
                    )
                if opacity is not None and float(opacity) < 1.0:
                    text_kw["style"] = {**(text_kw.get("style") or {}), "opacity": float(opacity)}
                if "font_size" not in (text_kw.get("style") or {}):
                    # matplotlib text defaults to font.size (10 pt → 13.9 px at
                    # dpi 100); without this the client's 11 px slot default wins.
                    text_kw["style"] = {
                        **(text_kw.get("style") or {}),
                        "font_size": _font_size_points(rcParams["font.size"], rcParams["font.size"])
                        * self._point_scale(),
                    }
                if kw.get("bbox"):
                    # matplotlib's text bbox patch, as label box styles.
                    text_kw["style"] = {
                        **_bbox_label_style(
                            kw["bbox"],
                            font_size=float((text_kw.get("style") or {}).get("font_size", 11.0)),
                        ),
                        **(text_kw.get("style") or {}),
                    }
                # matplotlib's pandas-registered converter parses date strings
                # placed on a date axis; categorical axes keep their strings.
                x, y = e["args"][0], e["args"][1]
                if isinstance(x, str) and self._axis_holds_datetimes("x"):
                    x = _parse_date_text(x) or x
                if isinstance(y, str) and self._axis_holds_datetimes("y"):
                    y = _parse_date_text(y) or y
                arrowprops = kw.get("arrowprops")
                value = str(e["args"][2]) if len(e["args"]) > 2 else ""
                if arrowprops and value and text_kw.get("dx") is not None:
                    # Offset-placed annotate(arrowprops=): matplotlib pins the
                    # arrow from the text to the data point across zoom — the
                    # engine's callout annotation is exactly that object.
                    font_size = float((text_kw.get("style") or {}).get("font_size", 11.0))
                    arrow_color, arrow_width, arrow_style = _arrow_visuals(
                        arrowprops, mutation_scale=font_size
                    )
                    style: dict[str, Any] = {**(text_kw.get("style") or {}), **arrow_style}
                    # matplotlib starts the arrow at the text patch edge
                    # (shrinkA/B default 2 pt); approximate the patch with a
                    # radial clearance around the label anchor.
                    style.setdefault("gap_start", font_size * 0.5 + 2.0)
                    style.setdefault("gap_end", 3.0)
                    # The callout color prop paints the arrow; pin the label's
                    # own color so it doesn't inherit the arrow's.
                    style.setdefault(
                        "label_color",
                        text_kw.get("color")
                        or resolve_color(rcParams.get("text.color", "black"))
                        or "black",
                    )
                    children.append(
                        fc.callout(
                            x,
                            y,
                            value,
                            dx=float(text_kw["dx"]),
                            dy=float(text_kw.get("dy", 0.0)),
                            color=arrow_color,
                            width=arrow_width,
                            anchor=text_kw.get("anchor", "start"),
                            class_name=text_kw.get("class_name"),
                            style=style,
                        )
                    )
                else:
                    children.append(fc.text(x, y, *e["args"][2:], **text_kw))
        return children

    def _best_legend_loc(
        self,
        x_domain: Optional[tuple[float, float]] = None,
        y_domain: Optional[tuple[float, float]] = None,
    ) -> str:
        """Choose the least occupied corner using bounded data-space samples.

        Matplotlib tests artist extents against several candidate boxes and
        keeps the first candidate (upper right) on ties. The shim has no Artist
        layout graph, but its canonical entry arrays are enough to make the
        same decision: for each corner, count sampled marks that fall inside a
        legend-box-sized region there — not the whole quadrant, so a curve
        crossing the middle no longer taints every corner. The domains passed
        in are the *displayed* limits (after equal-aspect expansion), which is
        what decides whether the data actually reaches a corner.
        """
        try:
            xlo, xhi = sorted(
                map(float, x_domain or self._axis["x"].get("domain") or self._auto_domain("x"))
            )
            ylo, yhi = sorted(
                map(float, y_domain or self._axis["y"].get("domain") or self._auto_domain("y"))
            )
        except (TypeError, ValueError):
            return "upper right"
        if xhi <= xlo or yhi <= ylo:
            return "upper right"
        # Fractional footprint of the legend box, grown by row count and the
        # longest label so a crowded legend guards a larger corner region.
        labels = [
            str(entry.get("kwargs", {}).get("name", ""))
            for entry in self._entries
            if entry.get("kwargs", {}).get("name")
        ]
        rows = max(1, len(labels))
        max_len = max((len(text) for text in labels), default=4)
        box_h = min(0.6, 0.10 + 0.07 * rows)
        box_w = min(0.6, 0.12 + 0.03 * max_len)
        # Every Matplotlib candidate box, in Matplotlib's own preference order
        # (corners, then the mid-edges, then dead center) so min() keeps the
        # first on ties. Each tuple is (name, x_lo, x_hi, y_lo, y_hi) in the
        # normalized [0, 1] plot box with y pointing up. Including the centered
        # edges is what lets a full-amplitude oscillation park the legend on the
        # sparse zero-crossing band, exactly like Matplotlib. ('right' is code 5
        # in Matplotlib and aliases 'center right'; keeping the single canonical
        # name here preserves the tie order without a redundant candidate.)
        cx_lo, cx_hi = 0.5 - box_w / 2.0, 0.5 + box_w / 2.0
        cy_lo, cy_hi = 0.5 - box_h / 2.0, 0.5 + box_h / 2.0
        candidates = (
            ("upper right", 1.0 - box_w, 1.0, 1.0 - box_h, 1.0),
            ("upper left", 0.0, box_w, 1.0 - box_h, 1.0),
            ("lower left", 0.0, box_w, 0.0, box_h),
            ("lower right", 1.0 - box_w, 1.0, 0.0, box_h),
            ("center right", 1.0 - box_w, 1.0, cy_lo, cy_hi),
            ("center left", 0.0, box_w, cy_lo, cy_hi),
            ("lower center", cx_lo, cx_hi, 0.0, box_h),
            ("upper center", cx_lo, cx_hi, 1.0 - box_h, 1.0),
            ("center", cx_lo, cx_hi, cy_lo, cy_hi),
        )
        scores = {name: 0.0 for name, *_ in candidates}
        entries_used = 0
        x_reverse = bool(self._axis["x"].get("reverse"))
        y_reverse = bool(self._axis["y"].get("reverse"))
        for entry in self._entries:
            x_values, y_values = entry.get("x"), entry.get("y")
            if x_values is None or y_values is None:
                args: Any = entry.get("args")
                if args is not None and len(args) >= 2:
                    x_values, y_values = args[0], args[1]
            if x_values is None or y_values is None:
                continue
            try:
                xv, yv = np.broadcast_arrays(
                    np.asarray(x_values, dtype=np.float64),
                    np.asarray(y_values, dtype=np.float64),
                )
            except (TypeError, ValueError):
                continue
            xv, yv = xv.reshape(-1), yv.reshape(-1)
            finite = np.flatnonzero(np.isfinite(xv) & np.isfinite(yv))
            if len(finite) > 512:
                finite = finite[np.linspace(0, len(finite) - 1, 512, dtype=np.intp)]
            if not len(finite):
                continue
            xn = np.clip((xv[finite] - xlo) / (xhi - xlo), 0.0, 1.0)
            yn = np.clip((yv[finite] - ylo) / (yhi - ylo), 0.0, 1.0)
            if x_reverse:
                xn = 1.0 - xn
            if y_reverse:
                yn = 1.0 - yn
            n = float(len(finite))
            entries_used += 1
            for name, xl, xh, yl, yh in candidates:
                inside = (xn >= xl) & (xn <= xh) & (yn >= yl) & (yn <= yh)
                scores[name] += float(np.count_nonzero(inside)) / n
        if not entries_used:
            return "upper right"
        # Normalize to a mean occupancy in [0, 1] so the tolerance below is
        # independent of series count. Matplotlib's integer badness makes
        # near-equal boxes exact ties broken by candidate order; our continuous
        # metric would otherwise let a sub-percent sampling difference override
        # that order (e.g. picking "center left" over "center right" on a
        # symmetric oscillation). Treat boxes within a small band as tied and
        # keep the first — which is Matplotlib's preference.
        for name in scores:
            scores[name] /= entries_used
        best = min(scores.values())
        return next(name for name, score in scores.items() if score <= best + 0.02)

    def _build_chart(self, width: int, height: int) -> Any:
        if self._y2_of is not None:
            return self._y2_of._build_chart(width, height)
        if self._chart is not None:
            return self._chart
        self._materialize_insets()
        children = self._chart_children()
        if self._twin is not None:
            children.extend(self._twin._chart_children())
        chart_padding = None if self._padding is None else list(self._padding)
        adjusted_aspect = False
        aspect_domains: Optional[tuple[tuple[float, float], tuple[float, float]]] = None
        if self._aspect_equal and self._aspect_bounds is not None:
            x0, x1, y0, y1 = self._aspect_bounds
            x0, x1 = self._axis["x"].get("domain", (x0, x1))
            y0, y1 = self._axis["y"].get("domain", (y0, y1))
            compact = width < 520
            if chart_padding is None:
                top, right, bottom, left = (
                    (6.0, 8.0, 36.0, 46.0) if compact else (10.0, 14.0, 42.0, 62.0)
                )
            else:
                top, right, bottom, left = map(float, chart_padding)
            layout_top = top + ((26.0 if compact else 30.0) if self._title else 0.0)
            layout_right = right
            layout_bottom = bottom
            if self._colorbar is not None:
                if self._colorbar.get("orientation") == "horizontal":
                    layout_bottom += 38.0 + (16.0 if self._colorbar.get("label") else 0.0)
                else:
                    layout_right += 86.0 + (18.0 if self._colorbar.get("label") else 0.0)
            plot_width = max(40.0, width - left - layout_right)
            plot_height = max(40.0, height - layout_top - layout_bottom)
            data_ratio = abs(x1 - x0) / max(abs(y1 - y0), np.finfo(float).eps)
            plot_ratio = plot_width / plot_height
            if self._aspect_adjustable == "datalim":
                # axis("equal") keeps the normal axes rectangle. Expand the
                # narrower data dimension around its existing center so one
                # x unit and one y unit occupy the same number of pixels.
                if plot_ratio > data_ratio:
                    center = (x0 + x1) * 0.5
                    half_span = abs(y1 - y0) * plot_ratio * 0.5
                    x0, x1 = center - half_span, center + half_span
                else:
                    center = (y0 + y1) * 0.5
                    half_span = abs(x1 - x0) / plot_ratio * 0.5
                    y0, y1 = center - half_span, center + half_span
                aspect_domains = ((x0, x1), (y0, y1))
            else:
                # adjustable='box' preserves image limits and changes the axes
                # rectangle to maintain equal data-unit scaling.
                if plot_ratio > data_ratio:
                    extra = plot_width - plot_height * data_ratio
                    left += extra * 0.5
                    right += extra * 0.5
                else:
                    extra = plot_height - plot_width / data_ratio
                    top += extra * 0.5
                    bottom += extra * 0.5
                chart_padding = [top, right, bottom, left]
                # Image-like entries carry their extent outside the ordinary
                # axis property dictionaries. Materialize it so the renderer's
                # generic range padding cannot move explicit image edges.
                self._axis["x"]["domain"] = (x0, x1)
                self._axis["y"]["domain"] = (y0, y1)
            adjusted_aspect = True
        if not adjusted_aspect and self._xmargin != 0.0 and "x" not in self._explicit_domains:
            self._axis["x"]["domain"] = self._auto_domain("x")
        if not adjusted_aspect and self._ymargin != 0.0 and "y" not in self._explicit_domains:
            self._axis["y"]["domain"] = self._auto_domain("y")
        if chart_padding is None and any(
            entry["kind"] == "@text"
            and (entry["kwargs"].get("style") or {}).get("coordinate_space") == "axes_fraction"
            and _is_number(entry["args"][0])
            and float(entry["args"][0]) > 1.0
            for entry in self._entries
        ):
            # Margin text right of the axes box (seaborn-style row titles at
            # axes-fraction x > 1) needs room the label-aware default margins
            # don't reserve; mirror layout()'s defaults and widen the right side.
            compact = width < 520
            chart_padding = (
                [6.0, 8.0 + 26.0, 36.0, 46.0] if compact else [10.0, 14.0 + 26.0, 42.0, 62.0]
            )
        # A dataless matplotlib axis views exactly (0, 1) — margins never apply.
        # Pin it so the engine's autorange padding cannot widen the empty view
        # (padding turns the 0.5 midpoint tick into a bare 0/1 pair).
        for axis in ("x", "y"):
            if (
                not adjusted_aspect
                and axis not in self._explicit_domains
                and self._axis[axis].get("domain") is None
                and len(self._entry_values(axis)) == 0
            ):
                self._axis[axis]["domain"] = (0.0, 1.0)
        x_props = {k: v for k, v in self._axis["x"].items() if v is not None}
        y_props = {k: v for k, v in self._axis["y"].items() if v is not None}
        if aspect_domains is not None:
            x_props["domain"], y_props["domain"] = aspect_domains
        auto_tick_counts = self._auto_tick_counts(x_props, width, height)
        self._apply_tickers("x", x_props, auto_tick_counts["x"])
        self._apply_tickers("y", y_props, auto_tick_counts["y"])
        self._apply_auto_tick_density(x_props, y_props, auto_tick_counts)
        children.append(_cached_axis("x", x_props))
        children.append(_cached_axis("y", y_props))
        for index, secondary in enumerate(self._secondary_axes, 1):
            children.append(secondary._component(index))
        if self._twin is not None:
            y2_props = {k: v for k, v in self._axis["y2"].items() if v is not None}
            self._apply_tickers("y2", y2_props, auto_tick_counts["y"])
            children.append(fc.y_axis(id="y2", side="right", **y2_props))
        if self._legend:
            legend_options = dict(self._legend_options)
            if legend_options.get("loc") in (None, "best"):
                legend_options["loc"] = self._best_legend_loc(
                    x_props.get("domain"), y_props.get("domain")
                )
            children.append(fc.legend(**legend_options))
        elif not any(entry.get("kwargs", {}).get("name") for entry in self._entries):
            # Core XY can auto-create a continuous-color "value" legend.
            # An unlabeled Matplotlib collection must not acquire one.
            children.append(fc.legend(show=False))
        if not self.figure._show_toolbar():
            children.append(_cached_modebar(False))
        theme_tokens = self._theme_tokens
        if _MPL_THEME_TOKENS:
            if self._grid_axis != "both":
                tokens = dict(theme_tokens)
                tokens["grid_color"] = "transparent"
                children.append(fc.theme(style=self._theme_style, **tokens))
            elif self._grid_color == _MPL_GRID_COLOR:
                children.append(_cached_theme(self._grid, theme_tokens, self._theme_style))
            else:
                tokens = dict(theme_tokens)
                tokens["grid_color"] = self._grid_color if self._grid else "transparent"
                children.append(fc.theme(style=self._theme_style, **tokens))
        self._chart = fc.chart(
            *children,
            title=self._title,
            width=width,
            height=height,
            padding=chart_padding,
            styles=self._chrome_styles,
        )
        core_figure = self._chart.figure()
        core_figure.frame_sides = [
            side for side in ("left", "bottom", "top", "right") if side not in self._hidden_spines
        ]
        if self._colorbar is not None:
            figure = core_figure
            options = dict(self._colorbar)
            if options.pop("_autoscale", False):
                derived = _colorbar_figure_domain(figure)
                if derived is not None:
                    options["domain"] = [derived[0], derived[1]]
            figure.colorbar_options = options
        if self._extra_legends:
            extras = []
            for leg in self._extra_legends:
                spec = leg.spec()
                if spec.get("loc") in (None, "best"):
                    spec["loc"] = self._best_legend_loc(
                        x_props.get("domain"), y_props.get("domain")
                    )
                extras.append(spec)
            core_figure.extra_legends = extras
        return self._chart

    def _auto_tick_counts(
        self,
        x_props: dict[str, Any],
        width: int,
        height: int,
    ) -> dict[str, int]:
        """Matplotlib's ``Axis.get_tick_space()`` per axis: how many tick
        intervals fit the estimated plot rect at the tick-label font size."""
        compact = width < 520
        if self._padding is None:
            left, right = (46.0, 8.0) if compact else (62.0, 14.0)
            top, bottom = (6.0, 36.0) if compact else (10.0, 42.0)
        else:
            top, right, bottom, left = map(float, self._padding)
        if self._title:
            top += 26.0 if compact else 30.0
        if x_props.get("side") == "top":
            top += 26.0 if compact else 32.0
        plot_width = max(40.0, float(width) - left - right)
        plot_height = max(40.0, float(height) - top - bottom)
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        base = float(rcParams["font.size"])
        x_font = _font_size_points(rcParams["xtick.labelsize"], base)
        y_font = _font_size_points(rcParams["ytick.labelsize"], base)
        return {
            "x": max(1, min(9, int(np.floor(plot_width * 72.0 / dpi / (x_font * 3.0))))),
            "y": max(1, min(9, int(np.floor(plot_height * 72.0 / dpi / (y_font * 2.0))))),
        }

    def _apply_auto_tick_density(
        self,
        x_props: dict[str, Any],
        y_props: dict[str, Any],
        counts: dict[str, int],
    ) -> None:
        """Match Matplotlib AutoLocator's axes-size tick-space heuristic."""
        for axis, props in (("x", x_props), ("y", y_props)):
            if (
                "tick_count" not in props
                and "tick_values" not in props
                and (axis, "major_locator") not in self._tickers
            ):
                props["tick_count"] = counts[axis]


def _discrete_levels(cmap: Any) -> Optional[int]:
    """Number of quantization bands for a resampled colormap (``get_cmap(n, N)``).

    Matplotlib's builtin continuous colormaps carry ``N == 256``; a smaller N
    (e.g. ``plt.get_cmap('viridis', 6)``) requests N flat bands. Returns that
    count only when it is a genuine down-sampling, else None (stay continuous).
    """
    n = getattr(cmap, "N", None)
    if isinstance(n, (int, np.integer)) and 1 <= int(n) < 256:
        return int(n)
    return None


def _quantize_to_levels(values: Any, domain: tuple[float, float], levels: int) -> np.ndarray:
    """Snap values to the representative value of their band, so a later
    linear colormap lookup over ``domain`` reproduces matplotlib's N discrete
    bands. NaN is preserved (missing cells stay transparent)."""
    v = np.asarray(values, dtype=np.float64)
    lo, hi = float(domain[0]), float(domain[1])
    span = (hi - lo) or 1.0
    u = np.clip((v - lo) / span, 0.0, 1.0)
    if levels <= 1:
        q = np.zeros_like(u)
    else:
        q = np.minimum(np.floor(u * levels), levels - 1) / (levels - 1)
    return lo + q * span


def _colorbar_figure_domain(figure: Any) -> Optional[tuple[float, float]]:
    """Value domain of the last color-mapped trace on a compiled figure.

    Used to back a colorbar whose mappable computes its domain inside the mark
    (e.g. hexbin counts), where it is not knowable when ``colorbar()`` runs.
    """
    for trace in reversed(getattr(figure, "traces", []) or []):
        style = getattr(trace, "style", None) or {}
        if style.get("role") == "heatmap" and style.get("domain") is not None:
            lo, hi = style["domain"]
            return (float(lo), float(hi))
        color_ch = getattr(trace, "color_ch", None)
        if color_ch is not None and color_ch.mode == "continuous" and color_ch.domain:
            lo, hi = color_ch.domain
            return (float(lo), float(hi))
    return None


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating))


# matplotlib arrowstyle name → (tail, head) endpoint shapes, in the shim's
# text→point drawing direction (A = tail at the text, B = head at the point).
_ARROWSTYLE_ENDS = {
    "-": ("none", "none"),
    "->": ("none", "v"),
    "<-": ("v", "none"),
    "<->": ("v", "v"),
    "-|>": ("none", "triangle"),
    "<|-": ("triangle", "none"),
    "<|-|>": ("triangle", "triangle"),
    "|-|": ("bar", "bar"),
    "]-[": ("bar", "bar"),
    "]-": ("bar", "none"),
    "-[": ("none", "bar"),
    "simple": ("none", "triangle"),
    "fancy": ("none", "triangle"),
    "wedge": ("none", "triangle"),
}


def _parse_style_options(spec: str) -> dict[str, float]:
    options: dict[str, float] = {}
    for part in spec.split(",")[1:]:
        key, _, value = part.partition("=")
        try:
            options[key.strip()] = float(value)
        except ValueError:
            continue
    return options


def _connection_curve(connectionstyle: Any) -> dict[str, float]:
    """matplotlib ``connectionstyle`` → quadratic-curve style keys (see
    ``_arrowgeom.py``): arc3's rad becomes ``curve``; angle3/angle become the
    ``angle_a``/``angle_b`` departure/arrival angles (corner rounding is
    approximated by the quadratic)."""
    if not isinstance(connectionstyle, str):
        return {}
    name = connectionstyle.split(",")[0].strip()
    options = _parse_style_options(connectionstyle)
    if name == "arc3":
        rad = options.get("rad", 0.0)
        return {"curve": rad} if rad else {}
    if name in ("angle3", "angle"):
        return {"angle_a": options.get("angleA", 90.0), "angle_b": options.get("angleB", 0.0)}
    return {}


def _arrow_visuals(
    arrowprops: dict[str, Any], mutation_scale: float = 14.0
) -> tuple[Optional[str], float, dict[str, Any]]:
    """Color, shaft width, and shape style keys for matplotlib ``arrowprops``.

    Head/tail shapes, filled tapered shafts (fancy/simple/wedge), and
    connectionstyle curves map onto the engine's arrow style vocabulary;
    ``mutation_scale`` mirrors matplotlib's (the annotation text size, px).
    What has no equivalent (corner rounding) is approximated, never dropped."""
    arrowstyle = arrowprops.get("arrowstyle")
    fancy = arrowstyle is None  # matplotlib's YAArrow-style thick default
    color = resolve_color(
        arrowprops.get("color")
        or arrowprops.get("facecolor")
        or arrowprops.get("fc")
        or arrowprops.get("edgecolor")
        or arrowprops.get("ec")
        or "black"
    )
    alpha = arrowprops.get("alpha")
    if color is not None and alpha is not None:
        from ._colors import _rgba_floats

        try:  # alpha dims only the arrow, so bake it into the color itself
            r, g, b, a = _rgba_floats(color)
        except ValueError:
            pass  # exotic CSS name: keep the color, lose alpha
        else:
            color = (
                f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},{float(alpha) * a:.3g})"
            )
    width = float(
        arrowprops.get(
            "width", arrowprops.get("lw", arrowprops.get("linewidth", 3.0 if fancy else 1.5))
        )
    )
    style: dict[str, Any] = {}
    if fancy:
        style["head_size"] = float(arrowprops.get("headwidth", 12.0))
    else:
        name = str(arrowstyle).split(",")[0].strip()
        tail, head = _ARROWSTYLE_ENDS.get(name, ("none", "triangle"))
        options = _parse_style_options(str(arrowstyle))
        scale = float(mutation_scale)
        if name in ("fancy", "simple", "wedge"):
            # Filled tapered shafts, matplotlib's mutation-scale-sized fills.
            if name == "wedge":
                style["shaft_width_start"] = options.get("tail_width", 0.3) * scale
                style["shaft_width_end"] = 1.0
                style["gap_end"] = 0.0  # the wedge tip IS the pointer
                head = "none"
            else:
                style["shaft_width_start"] = 2.0 if name == "fancy" else 1.5
                style["shaft_width_end"] = options.get("tail_width", 0.4) * scale
                style["head_size"] = options.get("head_width", 0.4) * scale * 2.2
        if head != "triangle":
            style["head_style"] = head
        if tail != "none":
            style["tail_style"] = tail
        if "bar" in (head, tail):
            # widthA/widthB are fractions of the mutation scale (~text size).
            bar = options.get("widthA", options.get("widthB", 0.4))
            style["head_size"] = max(4.0, bar * 20.0)
        elif "head_size" not in style:
            style["head_size"] = float(arrowprops.get("headwidth", 8.0))
    style.update(_connection_curve(arrowprops.get("connectionstyle")))
    return color, width, style


def _bbox_label_style(bbox: dict[str, Any], font_size: float = 11.0) -> dict[str, Any]:
    """matplotlib text ``bbox`` patch → annotation-label box styles.

    A CSS approximation drawn by the render client's DOM label; the static
    exporters keep the plain label (recorded in docs/matplotlib-compat.md).
    """
    style: dict[str, Any] = {}
    face = bbox.get("fc", bbox.get("facecolor", "C0"))
    alpha = bbox.get("alpha")
    if face is not None and face != "none":
        resolved = resolve_color(face)
        if resolved is not None:
            if alpha is not None:
                from ._colors import _rgba_floats

                try:
                    r, g, b, a = _rgba_floats(resolved)
                except ValueError:  # exotic CSS name: keep the fill, lose alpha
                    style["background"] = resolved
                else:
                    style["background"] = (
                        f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},"
                        f"{float(alpha) * a:.3g})"
                    )
            else:
                style["background"] = resolved
    edge = bbox.get("ec", bbox.get("edgecolor", "black"))
    if edge is not None and edge != "none":
        line_width = float(bbox.get("lw", bbox.get("linewidth", 1.0)))
        style["border"] = f"{line_width:g}px solid {resolve_color(edge)}"
    boxstyle = str(bbox.get("boxstyle", "square"))
    name = boxstyle.split(",")[0].strip()
    if "round" in name:
        style["border_radius"] = 8.0 if name == "round4" else 5.0
    # matplotlib pads the patch pad×fontsize around the text.
    pad = max(0.0, _parse_style_options(boxstyle).get("pad", 0.3)) * float(font_size)
    style["padding"] = f"{pad:.3g}px {pad * 1.3:.3g}px"
    return style


def _font_size_points(value: Any, base: Any) -> float:
    relative = {
        "xx-small": 0.6,
        "x-small": 0.75,
        "small": 0.85,
        "medium": 1.0,
        "large": 1.2,
        "x-large": 1.45,
        "xx-large": 1.75,
    }
    if isinstance(value, str):
        if value not in relative:
            raise ValueError(f"unsupported relative font size {value!r}")
        return float(base) * relative[value]
    result = float(value)
    if result <= 0:
        raise ValueError("font size must be positive")
    return result


def _font_size(value: Any, base: Any, dpi: float = 96.0) -> float:
    return _font_size_points(value, base) * float(dpi) / 72.0


def _rc_axis_style(axis: str, dpi: float = 96.0) -> dict[str, Any]:
    prefix = "xtick" if axis == "x" else "ytick"
    point_scale = float(dpi) / 72.0
    tick_color = rcParams[f"{prefix}.color"]
    label_color = rcParams[f"{prefix}.labelcolor"]
    result: dict[str, Any] = {}
    result["axis_width"] = float(rcParams["axes.linewidth"]) * point_scale
    result["tick_length"] = float(rcParams[f"{prefix}.major.size"]) * point_scale
    result["tick_width"] = float(rcParams[f"{prefix}.major.width"]) * point_scale
    if tick_color != "black":
        result["tick_color"] = resolve_color(tick_color)
    if label_color != "inherit" or tick_color != "black":
        result["tick_label_color"] = resolve_color(
            tick_color if label_color == "inherit" else label_color
        )
    # Always explicit: the render client and static exporters otherwise fall
    # back to their own 11 px default, not matplotlib's font.size-derived
    # medium (10 pt → 13.9 px at dpi 100).
    result["tick_label_size"] = _font_size(
        rcParams[f"{prefix}.labelsize"], rcParams["font.size"], dpi
    )
    if rcParams["axes.labelcolor"] != "black":
        result["label_color"] = resolve_color(rcParams["axes.labelcolor"])
    result["label_size"] = _font_size(rcParams["axes.labelsize"], rcParams["font.size"], dpi)
    return result


def _parse_bounds(value: Any, context: str) -> tuple[float, float, float, float]:
    bounds = getattr(value, "bounds", value)
    parsed = tuple(float(part) for part in bounds)
    if len(parsed) != 4:
        raise ValueError(f"{context} expects [left, bottom, width, height]")
    left, bottom, width, height = parsed
    if width < 0 or height < 0:
        raise ValueError(f"{context} width and height must be non-negative")
    return left, bottom, width, height


_DATE_TEXT_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def _parse_date_text(value: str) -> Optional[np.datetime64]:
    """A date string in the dateutil shapes gallery scripts use, or None.

    strptime's %m/%d accept unpadded fields, so '2012-1-1' parses too."""
    for fmt in _DATE_TEXT_FORMATS:
        try:
            return np.datetime64(datetime.strptime(value, fmt))
        except ValueError:
            continue
    return None


def _convert_timedelta_axis(values: np.ndarray) -> np.ndarray:
    """Map timedelta coordinates to seconds; dates and categories stay native."""
    array = np.asanyarray(values)
    if np.issubdtype(array.dtype, np.timedelta64):
        return array.astype("timedelta64[ns]").astype(np.float64) / 1_000_000_000.0
    if array.dtype == object and array.size:
        flat = array.reshape(-1)
        if all(isinstance(value, timedelta) for value in flat):
            return np.asarray([value.total_seconds() for value in flat], dtype=np.float64).reshape(
                array.shape
            )
        # pandas Periods (its dynamic date-plotting unit) → timestamps, the
        # engine's native time axis.
        if all(hasattr(value, "to_timestamp") for value in flat):
            return np.asarray([np.datetime64(value.to_timestamp()) for value in flat]).reshape(
                array.shape
            )
    return values


def _validate_margin(value: Any, axis: str) -> float:
    margin = float(value)
    if not np.isfinite(margin) or margin < 0:
        raise ValueError(f"{axis} margin must be a finite non-negative number")
    return margin


def _apply_axis_label_kwargs(props: dict[str, Any], kwargs: dict[str, Any], context: str) -> None:
    labelpad = kwargs.pop("labelpad", None)
    loc = kwargs.pop("loc", None)
    _consume_text_kwargs(kwargs, context)
    if labelpad is not None:
        props["label_offset"] = float(labelpad)
    if loc is not None:
        positions = {
            "left": "start",
            "bottom": "start",
            "center": "center",
            "right": "end",
            "top": "end",
        }
        if loc not in positions:
            raise ValueError(f"{context} loc must be one of {sorted(positions)}")
        props["label_position"] = positions[loc]


def _consume_text_kwargs(kwargs: dict[str, Any], context: str) -> None:
    # Accepted for Matplotlib-flavoured scripts.  The native engine currently
    # inherits font styling from the chart theme, so these kwargs are validated
    # and retained as compatibility inputs rather than silently acting on data.
    for key in (
        "fontsize",
        "size",
        "fontdict",
        "fontweight",
        "weight",
        "fontstyle",
        "style",
        "fontfamily",
        "family",
        "color",
        "horizontalalignment",
        "ha",
        "verticalalignment",
        "va",
        "rotation",
        "pad",
        "y",
        "x",
        "transform",
    ):
        kwargs.pop(key, None)
    if kwargs:
        raise TypeError(f"{context} got unsupported keyword argument {next(iter(kwargs))!r}")


def _tick_label_visibility(kwargs: dict[str, Any]) -> Optional[bool]:
    values = []
    for key in ("labelbottom", "labeltop", "labelleft", "labelright"):
        if key in kwargs:
            values.append(bool(kwargs.pop(key)))
    if not values:
        return None
    return any(values)


def _marker_symbol(marker: Any) -> str:
    try:
        return MARKER_TO_SYMBOL.get(marker, "circle")
    except TypeError:
        return "circle"


_SUPERSCRIPT_DIGITS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _pow10_label(value: float) -> str:
    """Matplotlib's log-decade label: 10 with a unicode superscript exponent."""
    exponent = np.log10(value) if value > 0 else np.nan
    if not np.isfinite(exponent) or abs(exponent - round(exponent)) > 1e-9:
        return f"{value:g}"
    return "10" + str(round(float(exponent))).translate(_SUPERSCRIPT_DIGITS)


def _plain_text(value: Any) -> str:
    text = str(value)
    converted = mathtext_to_unicode(text)
    if converted != text:
        return converted
    if "$" not in text and "\\" not in text:
        return text
    # ASCII fallback for TeX outside the unicode subset — approximate, never raw.
    text = text.replace("$", "")
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


def _plot_series_columns(x: Any, y: Any) -> list[tuple[Any, Any]]:
    """Split a plot() operand pair into per-column 1-D series.

    matplotlib draws one line per column of a 2-D operand (broadcasting a 1-D
    partner), and each column consumes the next entry of the property cycle.
    A purely 1-D pair yields a single series unchanged.
    """
    if np.ndim(x) < 2 and np.ndim(y) < 2:
        return [(x, y)]
    if np.ndim(x) == 1:
        x = np.broadcast_to(np.asarray(x)[:, None], np.shape(y))
    if np.ndim(y) == 1:
        y = np.broadcast_to(np.asarray(y)[:, None], np.shape(x))
    if x.shape != y.shape:
        raise ValueError("2-D plot x and y must have matching shapes")
    return [(x[:, i], y[:, i]) for i in range(x.shape[1])]


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
