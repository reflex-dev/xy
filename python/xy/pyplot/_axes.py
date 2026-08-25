"""The shim Axes: matplotlib's per-panel API translated onto composition marks.

An Axes accumulates *entries* — light spec dicts, one per plotted thing —
plus axis/chrome state, and materializes a single `xy.chart(...)` lazily.
Mutation (artists, labels, limits) invalidates the cached chart; the next
render rebuilds. Build cost is therefore the declarative API's build cost
plus dict bookkeeping — that closeness is asserted by the perf guardrail
test in tests/pyplot/.
"""

from __future__ import annotations

import builtins
import copy
import math
import warnings

# Runtime imports, not TYPE_CHECKING: `typing.get_type_hints()` on the public
# Axes methods must resolve these annotation names (all stdlib or xy-local).
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import suppress
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Literal, Optional

import numpy as np

import xy

from .. import _textblock
from .._typing import ArrayLike, ColorLike, ColorsLike, LimitsLike, Scalar
from ..components import _polar_axis_kwargs
from ._artists import (
    Artist,
    AxesImage,
    BarContainer,
    Legend,
    Line2D,
    Patch,
    PathCollection,
    PolyCollection,
    Text,
    _PatchFacade,
    unit_converted_values,
)
from ._colors import (
    PROP_CYCLE,
    cmap_extreme,
    normalize_scalar_grid,
    prepare_boundary_norm,
    resolve_cmap,
    resolve_color,
    resolve_rgba,
    resolve_rgba_array,
    scalar_float,
    scalar_grid_rgba,
)
from ._fmt import parse_fmt
from ._markers import marker_render_spec
from ._mathtext import mathtext_italic_ranges, mathtext_to_unicode
from ._plot_types import PlotTypeMixin
from ._rc import RcParams, rc_figsize_px, rcParams
from ._ticker import (
    AsinhLocator,
    AutoLocator,
    AutoMinorLocator,
    FixedLocator,
    Locator,
    LogFormatterSciNotation,
    LogitFormatter,
    LogitLocator,
    NullFormatter,
    NullLocator,
    ScalarFormatter,
    SymmetricalLogLocator,
    as_formatter,
)
from ._transforms import Bbox, CoordinateTransform, IdentityTransform
from ._translate import (
    LINESTYLE_TO_DASH,
    MPL_DASH_PATTERN,
    check_unsupported,
    line_kwargs,
    marker_size_to_scatter_size,
    not_implemented,
)

_UNSET = object()

# matplotlib's default look: white panel, no grid until grid(True).
_MPL_THEME_TOKENS = {
    "plot_background": "#ffffff",
    "axis_color": "#000000",
    "text_color": "#262626",
}
_MPL_GRID_COLOR = "#b0b0b0"
# The 1x1 axes rectangle implied by the rcParams figure.subplot.* defaults
# (left .125, bottom .11, right .9, top .88). `_mplfig` owns the general
# gridspec resolution; this is the last-resort answer for a detached axes.
_DEFAULT_AXES_RECT = (0.125, 0.11, 0.775, 0.77)

# Matplotlib's candidate order for ``loc="best"``: `Legend.codes` 1..10, scored
# in order, first zero-badness box wins, lower code wins a tie. Code 5
# ("right") anchors identically to code 7 ("center right") — offsetbox resolves
# both to its 'E' corner — so the pair is folded onto the single canonical name
# at code 5's position. The order `min()` observes is unchanged and no redundant
# box is scored. Do not reorder: this *is* the tie-break contract.
_LEGEND_LOC_ANCHORS = {
    "upper right": (1.0, 1.0),
    "upper left": (0.0, 1.0),
    "lower left": (0.0, 0.0),
    "lower right": (1.0, 0.0),
    "right": (1.0, 0.5),
    "center left": (0.0, 0.5),
    "center right": (1.0, 0.5),
    "lower center": (0.5, 0.0),
    "upper center": (0.5, 1.0),
    "center": (0.5, 0.5),
}
_BEST_LOC_ORDER = (
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "right",
    "center left",
    "lower center",
    "upper center",
    "center",
)
# Per-series path-vertex budget for occupancy scoring (§28: decimation is
# specified, never silent). Path scoring also tests segment/box intersections,
# so 512 vertices preserve the gallery parity without restoring the old cost.
_BEST_LOC_SAMPLE = 512
# Scatter offsets have no connecting segments to recover a skipped excursion.
# Retain #274's 4,096-offset coverage for that one mark family while keeping
# the lower path budget that restored the compatibility benchmark performance.
_BEST_LOC_SCATTER_SAMPLE = 4096
# Plot box of the default 640x480 figure, for direct `_best_legend_loc` callers
# that have no chart geometry to hand.
_DEFAULT_BEST_PLOT_SIZE = (564.0, 428.0)


def _path_intersects_boxes(
    x: np.ndarray,
    y: np.ndarray,
    boxes: Sequence[tuple[float, float, float, float]],
) -> list[bool]:
    """Whether a polyline touches each box, including edge-only crossings.

    Matplotlib adds one badness point per artist path intersecting the
    candidate legend rectangle, independently of the number of contained
    vertices. Liang-Barsky clipping gives the same segment/rectangle question
    without materializing a Matplotlib ``Path``. Segment coordinates and deltas
    are shared across all nine legend candidates; a bounding-box rejection
    keeps the exact clipping solve off segments that cannot touch a candidate.
    """
    boxes = tuple(boxes)
    if x.size < 2 or y.size < 2:
        return [False] * len(boxes)
    x0, y0, x1, y1 = x[:-1], y[:-1], x[1:], y[1:]
    finite = np.isfinite(x0) & np.isfinite(y0) & np.isfinite(x1) & np.isfinite(y1)
    if not finite.any():
        return [False] * len(boxes)
    x0, y0, x1, y1 = x0[finite], y0[finite], x1[finite], y1[finite]
    segment_x_lo, segment_x_hi = np.minimum(x0, x1), np.maximum(x0, x1)
    segment_y_lo, segment_y_hi = np.minimum(y0, y1), np.maximum(y0, y1)
    result: list[bool] = []
    for x_lo, x_hi, y_lo, y_hi in boxes:
        possible = (
            (segment_x_hi >= x_lo)
            & (segment_x_lo <= x_hi)
            & (segment_y_hi >= y_lo)
            & (segment_y_lo <= y_hi)
        )
        if not possible.any():
            result.append(False)
            continue
        hit = False
        for index in np.flatnonzero(possible):
            ax0, ay0, ax1, ay1 = x0[index], y0[index], x1[index], y1[index]
            if (x_lo <= ax0 <= x_hi and y_lo <= ay0 <= y_hi) or (
                x_lo <= ax1 <= x_hi and y_lo <= ay1 <= y_hi
            ):
                hit = True
                break
            adx, ady = ax1 - ax0, ay1 - ay0
            if adx:
                for boundary in (x_lo, x_hi):
                    ratio = (boundary - ax0) / adx
                    if 0.0 <= ratio <= 1.0 and y_lo <= ay0 + ratio * ady <= y_hi:
                        hit = True
                        break
            if hit:
                break
            if ady:
                for boundary in (y_lo, y_hi):
                    ratio = (boundary - ay0) / ady
                    if 0.0 <= ratio <= 1.0 and x_lo <= ax0 + ratio * adx <= x_hi:
                        hit = True
                        break
                if hit:
                    break
        result.append(hit)
    return result


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
                **_rc_font_weight(rcParams["axes.titleweight"]),
            },
            "axis_title": {
                "font-size": (
                    f"{_font_size(rcParams['axes.labelsize'], rcParams['font.size'], dpi):g}px"
                ),
                "color": resolve_color(rcParams["axes.labelcolor"]),
                **_rc_font_weight(rcParams["axes.labelweight"]),
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
        nonpositive = spec.get("nonpositive", "mask")
        if inverse:
            with np.errstate(over="ignore"):
                return 1.0 / (1.0 + np.power(10.0, -source))
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.log10(source / (1.0 - source))
        if nonpositive == "clip":
            return np.where(source <= 0.0, -1000.0, np.where(source >= 1.0, 1000.0, result))
        # Values at/outside (0, 1) are masked like matplotlib, never ±inf.
        return np.where((source > 0.0) & (source < 1.0), result, np.nan)
    if name == "asinh":
        width = spec["linear_width"]
        return width * np.sinh(source / width) if inverse else width * np.arcsinh(source / width)
    if name == "function":
        function = spec["inverse" if inverse else "forward"]
        result = np.asarray(function(source), dtype=np.float64)
        if result.shape != source.shape:
            try:
                result = np.broadcast_to(result, source.shape)
            except ValueError as error:
                raise ValueError("function scale must preserve the input shape") from error
        return result
    return values


class _ScaleTransformProxy:
    """Small Matplotlib-shaped scale transform used by ``Axis.get_transform``."""

    def __init__(self, spec: dict[str, Any], *, inverse: bool = False) -> None:
        self._spec = spec
        self._inverse = inverse

    def transform(self, values: Any) -> np.ndarray:
        source = np.asarray(values, dtype=np.float64)
        if self._spec["name"] == "log":
            base = float(self._spec.get("base", 10.0))
            with np.errstate(divide="ignore", invalid="ignore"):
                if self._inverse:
                    return np.power(base, source)
                result = np.log(source) / np.log(base)
            if self._spec.get("nonpositive", "clip") == "clip":
                return np.where(source <= 0, -1000.0, result)
            return np.where(source > 0, result, np.nan)
        return np.asarray(_scale_values(source, self._spec, inverse=self._inverse))

    def inverted(self) -> "_ScaleTransformProxy":
        return _ScaleTransformProxy(self._spec, inverse=not self._inverse)

    @property
    def base(self) -> float:
        return float(self._spec.get("base", 10.0))

    @property
    def linthresh(self) -> float:
        return float(self._spec["linthresh"])

    @property
    def linscale(self) -> float:
        return float(self._spec["linscale"])

    @property
    def linear_width(self) -> float:
        return float(self._spec["linear_width"])


def _clip_infinite_line(
    point: tuple[float, float],
    direction: tuple[float, float],
    xlim: tuple[float, float],
    ylim: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Clip one infinite data-space line to a rectangular view."""
    xlo, xhi = sorted(map(float, xlim))
    ylo, yhi = sorted(map(float, ylim))
    px, py = map(float, point)
    dx, dy = map(float, direction)
    if (dx == 0.0 and dy == 0.0) or not np.isfinite([px, py]).all():
        raise ValueError("Cannot draw a line through two identical or non-finite points")
    xtol = max(1.0, xhi - xlo) * 1e-12
    ytol = max(1.0, yhi - ylo) * 1e-12
    candidates: list[tuple[float, float, float]] = []
    if dx != 0.0:
        for x in (xlo, xhi):
            t = (x - px) / dx
            y = py + t * dy
            if ylo - ytol <= y <= yhi + ytol:
                candidates.append((t, x, min(yhi, max(ylo, y))))
    if dy != 0.0:
        for y in (ylo, yhi):
            t = (y - py) / dy
            x = px + t * dx
            if xlo - xtol <= x <= xhi + xtol:
                candidates.append((t, min(xhi, max(xlo, x)), y))
    candidates.sort(key=lambda item: item[0])
    unique: list[tuple[float, float, float]] = []
    for candidate in candidates:
        if not unique or not np.allclose(candidate[1:], unique[-1][1:], rtol=0.0, atol=1e-11):
            unique.append(candidate)
    if not unique:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    if len(unique) == 1:
        # A line tangent to one view corner has two coincident middle
        # intersections in Matplotlib's draw-time solve. Preserve that
        # degenerate two-vertex segment rather than turning it into an invalid
        # empty line trace.
        unique.append(unique[0])
    start, stop = unique[0], unique[-1]
    return (
        np.asarray([start[1], stop[1]], dtype=np.float64),
        np.asarray([start[2], stop[2]], dtype=np.float64),
    )


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
        "area": (0,) if axis == "x" else (1,),
        "step": (0,) if axis == "x" else (1,),
        # Compact stairs store (values, edges), the reverse of ordinary
        # Cartesian (x, y) argument order.
        "stairs": (1,) if axis == "x" else (0,),
        "stem": (0,) if axis == "x" else (1,),
        "errorbar": (0,) if axis == "x" else (1,),
        "hexbin": (0,) if axis == "x" else (1,),
    }.get(factory, ())
    args = list(entry.get("args", ()))
    for index in indexes:
        args[index] = convert(args[index])
    entry["args"] = tuple(args)
    if factory == "area" and axis == "y" and "base" in entry.get("kwargs", {}):
        entry["kwargs"]["base"] = convert(entry["kwargs"]["base"])


def _heatmap_span(entry: dict[str, Any], axis: str) -> Optional[np.ndarray]:
    """The outer cell edges a ``@mark``/``heatmap`` entry occupies on *axis*.

    ``hist2d``/``pcolormesh``/``specgram`` register their cell **centers**
    inside ``kwargs``, so the autoscale scan's generic top-level ``entry[key]``
    probe never sees them.  Mirror `Figure._heatmap_axis_positions` plus
    `Figure._cell_edges` exactly rather than re-deriving the geometry: absent
    centers default to ``arange(n)``, and the drawn span reaches half a cell
    beyond the first and last center, which is what recovers the original
    ``hist2d`` bin edges from its centers.
    """
    from xy._figure import Figure

    args = entry.get("args", ())
    if not args:
        return None
    z = np.asarray(args[0])
    if z.ndim < 2:
        return None
    # Both (rows, cols) and RGB(A) (rows, cols, bands) grids index the same way.
    count = z.shape[1 if axis == "x" else 0]
    centers = entry.get("kwargs", {}).get(axis)
    if centers is None:
        positions = np.arange(count, dtype=np.float64)
    else:
        try:
            positions = np.asarray(unit_converted_values(centers), dtype=np.float64).reshape(-1)
        except (TypeError, ValueError):
            # String/object centers become first-seen ordinals in the core.
            positions = np.arange(np.asarray(centers).size, dtype=np.float64)
    if positions.size != count or not np.all(np.isfinite(positions)):
        return None
    try:
        edges = Figure._cell_edges(positions, f"heatmap {axis}")
    except ValueError:
        # A build with these centers will raise for the same reason; leave the
        # decision to the core instead of guessing a span here.
        return None
    return np.asarray([edges[0], edges[-1]], dtype=np.float64)


def _box_spans(entry: dict[str, Any], axis: str) -> Iterator[np.ndarray]:
    """The spans a ``@mark``/``box`` entry occupies on *axis*.

    The value axis mirrors `marks.box`: Tukey whiskers plus, when outliers are
    drawn, the flier points beyond them.  The category axis follows
    Matplotlib's ``manage_ticks=True`` contract, which reserves position +/-
    0.5 regardless of the drawn box width.
    """
    from xy.marks import _distribution_stats

    args = entry.get("args", ())
    if not args:
        return
    kwargs = entry.get("kwargs", {})
    orientation = kwargs.get("orientation", "vertical")
    values = args[0]
    if (
        isinstance(values, (list, tuple))
        and len(values)
        and all(not isinstance(item, str) and np.ndim(item) == 1 for item in values)
    ):
        groups = [np.asarray(item, dtype=np.float64) for item in values]
    else:
        array = np.asarray(values, dtype=np.float64)
        groups = (
            [array[:, index] for index in range(array.shape[1])]
            if array.ndim == 2
            else [array.reshape(-1)]
        )
    positions = kwargs.get("x")
    ordinals = np.arange(len(groups), dtype=np.float64)
    if positions is None:
        # marks.box defaults absent positions to arange(len(groups)).
        centers = ordinals
    else:
        try:
            centers = np.asarray(unit_converted_values(positions), dtype=np.float64).reshape(-1)
        except (TypeError, ValueError):
            # String categories become their first-seen ordinal positions.
            centers = ordinals
    if centers.size != len(groups) or not np.all(np.isfinite(centers)):
        centers = ordinals
    category_axis = "x" if orientation == "vertical" else "y"
    if axis == category_axis:
        yield centers - 0.5
        yield centers + 0.5
        return
    stats = [_distribution_stats(group) for group in groups]
    spans = [np.asarray([stat[3], stat[4]], dtype=np.float64) for stat in stats]
    if kwargs.get("show_outliers", True):
        spans.extend(np.asarray(stat[5], dtype=np.float64) for stat in stats)
    yield from spans


def _scale_default_tickers(spec: dict[str, Any]) -> dict[str, Any]:
    """Matplotlib's default ticker quartet for a non-native scale."""
    name = spec["name"]
    if name == "symlog":
        locator_options = {
            "base": spec["base"],
            "linthresh": spec["linthresh"],
        }
        return {
            "major_locator": SymmetricalLogLocator(**locator_options),
            "major_formatter": LogFormatterSciNotation(spec["base"]),
            "minor_locator": SymmetricalLogLocator(
                **locator_options,
                subs=spec.get("subs"),
            ),
            "minor_formatter": NullFormatter(),
        }
    if name == "asinh":
        formatter: Any = (
            LogFormatterSciNotation(spec["base"]) if spec["base"] > 1 else ScalarFormatter()
        )
        return {
            "major_locator": AsinhLocator(
                spec["linear_width"],
                base=spec["base"],
            ),
            "major_formatter": formatter,
            "minor_locator": AsinhLocator(
                spec["linear_width"],
                base=spec["base"],
                subs=spec.get("subs"),
            ),
            "minor_formatter": NullFormatter(),
        }
    if name == "logit":
        formatter_options = {
            "one_half": spec["one_half"],
            "use_overline": spec["use_overline"],
        }
        return {
            "major_locator": LogitLocator(),
            "major_formatter": LogitFormatter(**formatter_options),
            "minor_locator": LogitLocator(minor=True),
            "minor_formatter": LogitFormatter(minor=True, **formatter_options),
        }
    if name == "function":
        return {
            "major_locator": AutoLocator(),
            "major_formatter": ScalarFormatter(),
            "minor_locator": NullLocator(),
            "minor_formatter": NullFormatter(),
        }
    return {}


class _AxisProxy:
    def __init__(self, axes: "Axes", axis: str) -> None:
        self.axes, self.axis = axes, axis

    def _ticker_slot(self) -> tuple["Axes", str]:
        axes = self.axes
        host = axes._y2_of or axes
        key = "y2" if (self.axis == "y" and axes._y2_of is not None) else self.axis
        return host._shared_ticker_source(key), key

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
        if "minor_locator" in kwargs:
            self.set_minor_locator(kwargs.pop("minor_locator"))
        if "minor_formatter" in kwargs:
            self.set_minor_formatter(kwargs.pop("minor_formatter"))

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
        props = host._axis[key]
        for stale in ("tick_values", "tick_labels", "tick_count"):
            props.pop(stale, None)
        host._auto_scale_axis_ticks.discard(key)
        if key in host._tick_expanded_domains:
            host._tick_expanded_domains.discard(key)
            props.pop("domain", None)
        host._invalidate_shared_ticker_axis(key)

    def get_major_locator(self) -> Any:
        host, key = self._ticker_slot()
        return host._tickers.get((key, "major_locator")) or AutoLocator()

    def set_major_formatter(self, formatter: Any) -> None:
        if self._is_units_registry_ticker(formatter):
            return
        host, key = self._ticker_slot()
        host._tickers[(key, "major_formatter")] = as_formatter(formatter, "set_major_formatter()")
        host._invalidate_shared_ticker_axis(key)

    def get_major_formatter(self) -> Any:
        host, key = self._ticker_slot()
        return host._tickers.get((key, "major_formatter")) or ScalarFormatter()

    def set_minor_locator(self, locator: Any) -> None:
        """Set the locator used for the independent unlabeled minor tick set."""
        host, key = self._ticker_slot()
        host._tickers[(key, "minor_locator")] = locator
        host._invalidate_shared_ticker_axis(key)

    def get_minor_locator(self) -> Any:
        host, key = self._ticker_slot()
        return host._tickers.get((key, "minor_locator")) or NullLocator()

    def get_transform(self) -> _ScaleTransformProxy:
        host, key = self._ticker_slot()
        return _ScaleTransformProxy(host._scale_specs[key])

    def set_minor_formatter(self, formatter: Any) -> None:
        """Set a minor formatter, used when a labeled minor set is promoted."""
        host, key = self._ticker_slot()
        host._tickers[(key, "minor_formatter")] = as_formatter(formatter, "set_minor_formatter()")
        host._invalidate_shared_ticker_axis(key)

    def set_tick_params(
        self,
        which: str = "major",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        """Forward tick styling to this proxy's axes dimension."""
        which = str(which).lower()
        if which not in {"major", "minor", "both"}:
            raise ValueError("Axis.set_tick_params() which must be 'major', 'minor', or 'both'")
        if reset:
            raise not_implemented(
                "Axis.set_tick_params(reset=True)",
                alternative="reset=False",
            )
        self.axes.tick_params(axis=self.axis, which=which, **kwargs)

    def set_ticks_position(self, position: str) -> None:
        """Move tick marks (and, for an edge, their labels) like Matplotlib."""
        position = str(position).lower()
        allowed = (
            {"top", "bottom", "both", "default", "none"}
            if self.axis == "x"
            else {"left", "right", "both", "default", "none"}
        )
        if position not in allowed:
            raise ValueError(
                f"{self.axis}axis.set_ticks_position() position must be one of {sorted(allowed)}"
            )
        if self.axis == "x":
            if position == "top":
                updates = {
                    "top": True,
                    "labeltop": True,
                    "bottom": False,
                    "labelbottom": False,
                }
            elif position == "bottom":
                updates = {
                    "top": False,
                    "labeltop": False,
                    "bottom": True,
                    "labelbottom": True,
                }
            elif position == "both":
                updates = {"top": True, "bottom": True}
            elif position == "none":
                updates = {"top": False, "bottom": False}
            else:
                updates = {
                    "top": True,
                    "labeltop": False,
                    "bottom": True,
                    "labelbottom": True,
                }
        elif position == "right":
            updates = {
                "right": True,
                "labelright": True,
                "left": False,
                "labelleft": False,
            }
        elif position == "left":
            updates = {
                "right": False,
                "labelright": False,
                "left": True,
                "labelleft": True,
            }
        elif position == "both":
            updates = {"right": True, "left": True}
        elif position == "none":
            updates = {"right": False, "left": False}
        else:
            updates = {
                "right": True,
                "labelright": False,
                "left": True,
                "labelleft": True,
            }
        self.axes.tick_params(axis=self.axis, which="both", **updates)

    def set_label_position(self, position: str) -> None:
        """Move only the axis title, independently from ticks and labels."""
        position = str(position).lower()
        allowed = {"top", "bottom"} if self.axis == "x" else {"left", "right"}
        if position not in allowed:
            raise ValueError(
                f"{self.axis}axis.set_label_position() position must be one of {sorted(allowed)}"
            )
        props = self.axes._axis_props(self.axis)
        # Core's ``side`` owns the axis title and is also the fallback for tick
        # sides. Materialize the current independent tick state first so moving
        # a title never moves ticks that the caller did not request.
        props["tick_sides"] = [
            side for side, visible in self.axes._tick_sides[self.axis].items() if visible
        ]
        props["tick_label_sides"] = [
            side.removeprefix("label")
            for side, visible in self.axes._tick_label_sides[self.axis].items()
            if visible
        ]
        props["side"] = position
        self.axes._invalidate()

    def grid(self, visible: bool | None = None, which: str = "major", **kwargs: Any) -> None:
        """Configure grid lines for only this axis.

        This is Matplotlib's ``Axis.grid`` surface: unlike ``Axes.grid`` it
        has no ``axis=`` argument because the proxy already identifies the
        target dimension.
        """
        which = str(which).lower()
        if which not in {"major", "minor", "both"}:
            raise ValueError("grid() which must be 'major', 'minor', or 'both'")
        self.axes.grid(visible, which=which, axis=self.axis, **kwargs)

    def tick_bottom(self) -> None:
        if self.axis != "x":
            raise AttributeError("tick_bottom() is only available on an x axis")
        self.set_ticks_position("bottom")

    def tick_left(self) -> None:
        if self.axis != "y":
            raise AttributeError("tick_left() is only available on a y axis")
        self.set_ticks_position("left")

    def get_majorticklabels(self) -> list["_TickLabel"]:
        return self.axes._tick_label_handles(self.axis)

    def get_minorticklabels(self) -> list["_TickLabel"]:
        # The wire's independent minor set is intentionally unlabeled. A
        # labeled minor pair is promoted to the ordinary label set at build.
        return []

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

    def set_xlabel(self, label: str, **kwargs: Any) -> "SecondaryAxis":
        if self._axis != "x":
            raise AttributeError("secondary y axes use set_ylabel()")
        if kwargs:
            raise TypeError(f"set_xlabel() got unsupported keyword argument {next(iter(kwargs))!r}")
        self._label = str(label)
        self._parent._invalidate()
        return self

    def set_ylabel(self, label: str, **kwargs: Any) -> "SecondaryAxis":
        if self._axis != "y":
            raise AttributeError("secondary x axes use set_xlabel()")
        if kwargs:
            raise TypeError(f"set_ylabel() got unsupported keyword argument {next(iter(kwargs))!r}")
        self._label = str(label)
        self._parent._invalidate()
        return self

    def set_ticks(
        self, ticks: ArrayLike, labels: Sequence[str] | None = None, **kwargs: Any
    ) -> None:
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
        factory = xy.x_axis if self._axis == "x" else xy.y_axis
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

    def set_color(self, color: ColorLike) -> None:
        style = self._axes._axis_props(self._axis).setdefault("style", {})
        style["tick_label_color"] = resolve_color(color)
        self._axes._invalidate()

    def set_horizontalalignment(self, align: str) -> None:
        align = str(align).lower()
        anchors = {"left": "start", "center": "center", "right": "end"}
        if align not in anchors:
            raise ValueError("align must be 'left', 'center', or 'right'")
        self._axes._axis_props(self._axis)["tick_label_anchor"] = anchors[align]
        self._axes._invalidate()

    set_ha = set_horizontalalignment

    def get_horizontalalignment(self) -> str:
        anchors = {"start": "left", "center": "center", "end": "right"}
        props = self._axes._axis_props(self._axis)
        anchor = props.get("tick_label_anchor")
        if anchor is None:
            if self._axis == "x":
                return "center"
            sides = props.get("tick_label_sides") or [props.get("side", "left")]
            return "left" if sides[0] == "right" else "right"
        return anchors.get(str(anchor), "center")

    def set_rotation(self, angle: float) -> None:
        angle = float(angle)
        self._axes._axis_props(self._axis)["tick_label_angle"] = angle
        self._axes._apply_tick_rotation_mode(self._axis, angle)
        self._axes._invalidate()

    def get_rotation(self) -> float:
        return float(self._axes._axis_props(self._axis).get("tick_label_angle", 0.0))

    def set_rotation_mode(self, mode: str | None) -> None:
        self._axes._set_tick_rotation_mode(self._axis, mode)
        self._axes._invalidate()

    def get_rotation_mode(self) -> str:
        return self._axes._tick_rotation_modes.get(self._axis) or "default"


class _SharedAxesGroup:
    """matplotlib's shared-axes Grouper over the shim's shared props dicts."""

    def __init__(self, axis: str) -> None:
        self._axis = axis

    def _pool(self, ax: Any) -> list[Any]:
        fig = getattr(ax, "figure", None)
        return list(fig._axes) if fig is not None else [ax]

    def get_siblings(self, ax: Axes) -> list[Any]:
        source = ax._shared_ticker_source(self._axis)
        props = ax._axis_props(self._axis)
        return [
            other
            for other in self._pool(ax)
            if other._shared_ticker_source(self._axis) is source
            or other._axis_props(self._axis) is props
        ] or [ax]

    def joined(self, a: Axes, b: Axes) -> bool:
        return a._shared_ticker_source(self._axis) is b._shared_ticker_source(
            self._axis
        ) or a._axis_props(self._axis) is b._axis_props(self._axis)

    def join(self, *axes_list: Any) -> None:
        first = axes_list[0]
        source = first._shared_ticker_source(self._axis)
        shared = first._axis_props(self._axis)
        for other in axes_list[1:]:
            key = "y2" if (self._axis == "y" and other._y2_of is not None) else self._axis
            (other._y2_of or other)._axis[key] = shared
            other._shared_axis_sources[self._axis] = source
            other._invalidate()


class _SpineProxy:
    def __init__(
        self, axes: "Axes", names: tuple[str, ...] = ("left", "bottom", "top", "right")
    ) -> None:
        self.axes, self.names = axes, names

    def __getitem__(self, key: Any) -> "_SpineProxy":
        if isinstance(key, str):
            names = (key,)
        elif isinstance(key, list):
            names = tuple(key)
        elif isinstance(key, tuple):
            raise ValueError("Multiple spines must be passed as a single list")
        elif isinstance(key, slice):
            if key.start is not None or key.stop is not None or key.step is not None:
                raise ValueError(
                    "Spines does not support slicing except for the fully "
                    "open slice [:] to access all spines."
                )
            names = self.names
        else:
            raise TypeError(f"spine key must be a string, list, or open slice, got {type(key)!r}")
        unknown = set(names) - {"left", "bottom", "top", "right"}
        if unknown:
            raise KeyError(next(iter(unknown)))
        return _SpineProxy(self.axes, names)

    def __getattr__(self, name: str) -> "_SpineProxy":
        if name in {"left", "bottom", "top", "right"}:
            return self[name]
        raise AttributeError(name)

    def values(self) -> list["_SpineProxy"]:
        return [_SpineProxy(self.axes, (name,)) for name in self.names]

    def keys(self) -> list[str]:
        return list(self.names)

    def items(self) -> list[tuple[str, "_SpineProxy"]]:
        return [(name, _SpineProxy(self.axes, (name,))) for name in self.names]

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    def set_visible(self, visible: bool) -> None:
        for name in self.names:
            if bool(visible):
                self.axes._hidden_spines.discard(name)
            else:
                self.axes._hidden_spines.add(name)
        self.axes._invalidate()

    def get_visible(self) -> bool:
        return all(name not in self.axes._hidden_spines for name in self.names)


def _cached_theme(grid: bool, tokens: dict[str, Any], style: dict[str, Any]) -> Any:
    key = ("theme", grid, tuple(sorted(tokens.items())), tuple(sorted(style.items())))
    made = _component_cache.get(key)
    if made is None:
        applied = dict(tokens)
        applied["grid_color"] = _MPL_GRID_COLOR if grid else "transparent"
        made = _component_cache[key] = xy.theme(style=style, **applied)
    return made


def _cached_modebar(show: bool) -> Any:
    key = ("modebar", show)
    made = _component_cache.get(key)
    if made is None:
        made = _component_cache[key] = xy.modebar(show=show)
    return made


def _cached_axis(which: str, props: dict) -> Any:
    if props:
        if which == "x" and any(
            key in props
            for key in ("theta_unit", "theta_zero", "theta_direction", "sector", "grid_shape")
        ):
            # `_polar_axis_kwargs` drops the keywords `theta_axis` refuses. This
            # bag is not hand-authored: every Axes carries an rcParam-derived
            # `minor_style`, and `minorticks_on()`/`tick_params(ha=)` add more.
            # Dropping them is what all three renderers already do with those
            # values; refusing would turn `projection="polar"` into an error over
            # a default nobody asked for. Recorded in spec/matplotlib/compat.md.
            angular = _polar_axis_kwargs(props)
            unit = angular.pop("theta_unit", None)
            zero = angular.pop("theta_zero", None)
            direction = angular.pop("theta_direction", None)
            sector = angular.pop("sector", None)
            grid_shape = angular.pop("grid_shape", None)
            return xy.theta_axis(
                unit=unit,
                zero=zero,
                direction=direction,
                sector=sector,
                grid_shape=grid_shape,
                **angular,
            )
        if which == "y" and any(key in props for key in ("hole", "r_origin")):
            radial = _polar_axis_kwargs(props)
            hole = radial.pop("hole", None)
            origin = radial.pop("r_origin", None)
            return xy.r_axis(hole=hole, origin=origin, **radial)
        factory = xy.x_axis if which == "x" else xy.y_axis
        return factory(**props)
    key = ("axis", which)
    made = _component_cache.get(key)
    if made is None:
        made = _component_cache[key] = (xy.x_axis if which == "x" else xy.y_axis)()
    return made


def _without_repeats(ring: np.ndarray) -> np.ndarray:
    """A ring with consecutive duplicate vertices dropped, closing vertex kept.

    Matplotlib repeats a vertex inside its full-circle paths, and the
    triangulator rejects any polygon carrying a duplicate. That repeat is not
    bit-exact, so the comparison needs a tolerance, but it has to scale with
    the ring rather than with coordinate magnitude. `np.isclose` scales with
    magnitude and so treats vertices 10,000 units apart as one at x = 1e9,
    erasing a patch drawn on genomic or epoch-millisecond axes.

    Measured against Matplotlib 3.11.1 as a fraction of the ring's
    bounding-box diagonal, repeats sit at 9e-17 while the smallest real edge
    across the shapes we flatten sits at 2e-3. A threshold of 1e-12 of the
    span is ten thousand times above the noise and a billion times below the
    smallest real edge.
    """
    if len(ring) < 2:
        return ring
    span = float(np.hypot(*(ring.max(axis=0) - ring.min(axis=0))))
    if not np.isfinite(span):
        # One non-finite coordinate makes every tolerance derived from the span
        # meaningless: against an infinite one, each gap reads as a duplicate
        # and the ring empties. Keep it whole and let the triangulator reject
        # it on its own terms.
        return ring
    return ring[np.r_[True, np.hypot(*(ring[1:] - ring[:-1]).T) > span * 1e-12]]


def _refine_at_pixel_scale(path: Any, transform: Any, rings: list[Any], pixels: float) -> Any:
    """Re-flatten `path` as though the patch spanned `pixels` output pixels.

    ``to_polygons`` subdivides a cubic Bézier until it is flat in the
    coordinates it is handed, so flattening through the patch transform takes
    its tessellation from the *numeric magnitude* of the data. `Circle(radius=1)`
    comes back as sixteen segments whose alternate vertices overshoot the true
    radius by 2.5%, while the identical circle drawn as `radius=1000` comes
    back smooth. Matplotlib never shows this, because its renderers flatten in
    display space, after the full data-to-pixel transform.

    xy builds geometry when the patch is added, before the view is known, so
    there is no true pixel transform to use here. Flattening as though the
    patch filled the figure is the finest resolution it could ever need, and
    undoing the scale afterwards leaves data-space rings whose accuracy no
    longer depends on the units the caller happened to plot in.

    The patch transform is applied to the control points rather than composed
    onto a scale transform, because the shim never imports matplotlib. That is
    exact: an affine maps a cubic Bézier's control points to the control
    points of the mapped curve, and patch transforms are affine.

    Scaling is done about the patch's own corner rather than the origin. A
    round trip through `* scale` and `/ scale` costs relative precision, and
    a small patch at a large offset has little to spare: a 1e-4 rectangle at
    x = 1e9 loses eight times more area to the round trip when the offset
    rides along than when only the patch's own extent is scaled.
    """
    finite = [np.asarray(ring, dtype=np.float64) for ring in rings]
    finite = [ring for ring in finite if ring.ndim == 2 and len(ring) and np.isfinite(ring).all()]
    if not finite:
        return rings
    stacked = np.concatenate(finite)
    corner = stacked.min(axis=0)
    span = float(np.hypot(*(stacked.max(axis=0) - corner)))
    scale = pixels / span if span > 0.0 else 0.0
    if not np.isfinite(scale) or scale <= 0.0:
        return rings
    placed = np.asarray(transform.transform(path.vertices), dtype=np.float64)
    enlarged = type(path)((placed - corner) * scale, path.codes)
    return [np.asarray(ring, dtype=np.float64) / scale + corner for ring in enlarged.to_polygons()]


def _patch_placement(patch: Any) -> tuple[Any, Any]:
    """(transform to flatten through, xy transform to apply after) for a patch.

    Matplotlib's `Patch.get_transform` composes `get_patch_transform` with the
    artist-level transform, so `Rectangle(..., transform=Affine2D().rotate_deg(45))`
    carries its rotation there and flattening through `get_patch_transform`
    alone would silently drop it. When an artist transform has been set and
    matplotlib can compose it, the composite is the transform to flatten
    through. xy's own transform objects will not compose inside matplotlib
    (`TypeError`); of those, `ax.transData` is the identity so the patch
    transform alone is already right, a data-space affine comes back as the
    second element to apply to the flattened rings — exact, since an affine
    maps polygons to polygons — and axes/figure fractions are rejected the
    way `_transform_points` rejects them for every other data artist: baked
    fractions go silently stale on the next limit change.
    """
    patch_transform = patch.get_patch_transform()
    if not getattr(patch, "is_transform_set", lambda: False)():
        return patch_transform, None
    try:
        return patch.get_transform(), None
    except TypeError:
        artist_transform = getattr(patch, "_transform", None)
    if getattr(artist_transform, "coordinate_space", "data") in {
        "axes_fraction",
        "figure_fraction",
    }:
        raise not_implemented(
            "data artists with transform=transAxes/transFigure",
            "affine data transforms composed with ax.transData",
        )
    return patch_transform, artist_transform


def _patch_outline(patch: Any, pixels: float = 1024.0) -> list[np.ndarray]:
    """Data-space rings of a patch, curves flattened and its transform applied.

    ``Path.to_polygons`` applies the patch transform and resolves curves into
    straight segments, so a rotated Rectangle, a Circle, and a Wedge all come
    back as real geometry rather than as cubic Bézier control points. An
    artist-level `transform=` rides along per `_patch_placement`. `pixels` is
    the output size the flattening is resolved for — see
    `_refine_at_pixel_scale`, which is why it is not resolved in data units.
    Ducks without a path fall back to raw vertices, which drop curvature and
    rotation.
    """
    get_path = getattr(patch, "get_path", None)
    get_transform = getattr(patch, "get_patch_transform", None)
    rings: list[Any] = []
    after = None
    if get_path is not None and get_transform is not None:
        path = get_path()
        to_polygons = getattr(path, "to_polygons", None)
        if to_polygons is not None:
            transform, after = _patch_placement(patch)
            rings = list(to_polygons(transform))
            if rings:
                # A duck path that cannot be rebuilt from vertices and codes
                # keeps its data-space flattening rather than losing geometry.
                with suppress(AttributeError, TypeError, ValueError):
                    rings = list(_refine_at_pixel_scale(path, transform, rings, pixels))
            if after is not None:
                rings = [np.asarray(after.transform(ring), dtype=np.float64) for ring in rings]
    if not rings:
        if all(hasattr(patch, name) for name in ("get_x", "get_y", "get_width", "get_height")):
            x0, y0 = float(patch.get_x()), float(patch.get_y())
            x1, y1 = x0 + float(patch.get_width()), y0 + float(patch.get_height())
            rings = [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]
        elif get_path is not None:
            rings = [get_path().vertices]
        else:
            raise TypeError(f"unsupported patch {type(patch).__name__}")
    return [_without_repeats(np.asarray(ring, dtype=np.float64)) for ring in rings]


def _rings_are_nested(outline: list[np.ndarray]) -> bool:
    """True when one ring sits wholly inside another, so the path has holes.

    `kernels.polygon_triangles` takes one simple polygon, so a hole would have
    to be painted solid. Callers abstain from filling instead.

    Containment is every vertex inside, not the first one: rings that merely
    overlap put some vertices in and some out, and a first-vertex test would
    call them nested and hollow the whole patch. Overlapping rings fill
    ring-by-ring instead — their union, where the even-odd rule would leave
    the intersection unpainted, which errs on the side of painting what each
    ring alone would have painted.
    """
    from xy import kernels

    if len(outline) < 2:
        return False
    for index, ring in enumerate(outline):
        if not len(ring):
            continue
        rows = np.arange(len(ring), dtype=np.uint32)
        for other in outline[:index] + outline[index + 1 :]:
            if len(other) < 3:
                continue
            inside = kernels.polygon_select(ring[:, 0], ring[:, 1], rows, other[:, 0], other[:, 1])
            if len(inside) == len(ring):
                return True
    return False


def _opaque_or_none(color: Any) -> Any:
    """`color` unless it paints nothing — a "none" name or a zero alpha."""
    if color is None or str(color).lower() == "none":
        return None
    if isinstance(color, (tuple, list, np.ndarray)) and len(color) == 4 and not float(color[3]):
        return None
    return color


def _patch_fill_color(patch: Any) -> Any:
    """The patch's own face color, or None when it asks not to be filled."""
    if not getattr(patch, "get_fill", lambda: True)():
        return None
    return _opaque_or_none(getattr(patch, "get_facecolor", lambda: None)())


def _patch_edge_color(patch: Any) -> Any:
    """The patch's own edge color, or None when its outline paints nothing.

    Matplotlib leaves `edgecolor` as `"none"` on a filled patch unless the
    caller asks for one, so the common `Rectangle(facecolor=...)` has no
    visible outline at all. Emitting one anyway costs a mark per ring that
    can never be seen.
    """
    return _opaque_or_none(getattr(patch, "get_edgecolor", lambda: "#000000")())


class Axes(PlotTypeMixin):
    def __init__(self, figure: Any, *, y2_of: Optional["Axes"] = None) -> None:
        self.figure = figure
        self._entries: list[dict[str, Any]] = []
        self._owned_artists: list[Any] = []
        self._containers: list[Any] = []
        self._axis: dict[str, dict[str, Any]] = {"x": {}, "y": {}, "y2": {}}
        self._title: Optional[str] = None
        self._title_style: dict[str, Any] = {}
        self._titles: dict[str, dict[str, Any]] = {}
        self._legend = False
        self._legend_options: dict[str, Any] = {}
        self._legend_items: Optional[list[dict[str, Any]]] = None
        self._legend_handle: Optional[Legend] = None
        self._legend_artist: Optional[Legend] = None
        self._extra_legends: list[Any] = []
        self._colorbar: Optional[dict[str, Any]] = None
        self._colorbar_source: Optional[dict[str, Any]] = None  # entry the colorbar reads
        self._aspect_equal = False
        self._aspect_value = 1.0
        self._aspect_adjustable = "box"
        self._aspect_bounds: Optional[tuple[float, float, float, float]] = None
        self._insets: list[tuple["Axes", tuple[float, float, float, float]]] = []
        self._insets_materialized = False
        self._figure_rect: Optional[tuple[float, float, float, float]] = None
        # The originating gridspec span, when _figure_rect came from one —
        # subplots_adjust() re-resolves the rect instead of keeping it frozen.
        self._subplot_spec: Optional[Any] = None
        # Stable row-major cell identity for an ordinary subplot. Figure.axes
        # is a draw-order list, so removing an earlier axes must not slide
        # every later subplot into the preceding cell.
        self._subplot_index: Optional[int] = None
        # Figure.add_subplot() always creates a new axes, while pyplot.subplot()
        # activates an existing axes with the same subplot arguments.  Keep the
        # normalized spec separate from draw order so those two APIs can share
        # the grid implementation without sharing creation semantics.
        self._subplot_key: Optional[tuple[Any, ...]] = None
        self._subplot_claimed = False
        self._absolute_plot_ratio: Optional[float] = None
        # The plot rectangle the exporter demands, in chart pixels
        # (left, top, width, height).  Set by the grid compositor for a panel,
        # whose chart is the panel and not the whole figure; otherwise the
        # chart *is* the figure and the rectangle comes from get_position().
        self._plot_box_px: Optional[tuple[float, float, float, float]] = None
        self._shared_render_domains: dict[str, tuple[float, float]] = {}
        self._padding: Optional[list[float]] = None
        # "cartesian" or "polar" — matplotlib's `projection=` argument. Polar
        # reinterprets the same two axes (x carries theta, y carries r), which
        # is exactly how PolarAxes works: ordinary plot/scatter/bar/fill calls
        # render into the projection rather than into polar-specific artists.
        self._projection: str = "cartesian"
        self._polar_options: dict[str, Any] = {}
        self._polar_r_options: dict[str, Any] = {}
        # Natural ``table(loc="bottom")`` height in Matplotlib points. It is
        # converted at render time so savefig DPI changes preserve cell size.
        self._table_bottom_points = 0.0
        # Matplotlib snapshots the rc autoscale margins when an Axes is
        # created.  Keep those values on the axes so ordinary get_*lim() and
        # rendering use the advertised 5% defaults without requiring an
        # explicit margins() call.
        self._xmargin = float(rcParams["axes.xmargin"])
        self._ymargin = float(rcParams["axes.ymargin"])
        self._rc_margins = {
            "x": self._xmargin,
            "y": self._ymargin,
        }
        self._margin_overrides: set[str] = set()
        # Whether autoscaling should stop at the margin-expanded data limits
        # instead of asking the locator for round-number limits. ``None`` has
        # Matplotlib's initial false-like behavior and lets tight=None preserve
        # the preceding explicit choice.
        self._tight: bool | None = None
        # Edge annotations (notably bar_label) need more than the raw 5% data
        # margin to contain a 10 pt glyph plus point padding.  Keep that
        # renderer-independent reservation separate so an explicit margins()
        # call still wins.
        self._annotation_margins: dict[str, float] = {"x": 0.0, "y": 0.0}
        self._explicit_domains: set[str] = set()
        self._secondary_axes: list[SecondaryAxis] = []
        self._scale_specs: dict[str, dict[str, Any]] = {
            "x": {"name": "linear"},
            "y": {"name": "linear"},
            "y2": {"name": "linear"},
        }
        self._auto_scale_axis_ticks: set[str] = set()
        self._tick_expanded_domains: set[str] = set()
        self._tickers: dict[tuple[str, str], Any] = {}
        # Matplotlib shares the Axis ticker containers (locator/formatter)
        # while keeping per-Axes Tick artists and their visibility separate.
        # Figure.apply_sharing records the first panel in each shared group,
        # matching GridSpec.subplots' share source.
        self._shared_axis_sources: dict[str, Axes] = {}
        self._tick_rotation_modes: dict[str, str | None] = {"x": None, "y": None}
        self._tick_sides: dict[str, dict[str, bool]] = {
            "x": {"bottom": True, "top": False},
            "y": {"left": y2_of is None, "right": y2_of is not None},
        }
        self._tick_label_sides: dict[str, dict[str, bool]] = {
            "x": {"labelbottom": True, "labeltop": False},
            "y": {"labelleft": y2_of is None, "labelright": y2_of is not None},
        }
        self._tick_lengths: dict[str, float] = {}
        # Matplotlib's `axison` is an axes-wide draw-time gate. It does not
        # mutate the individual Axis or Spine visibility settings, so turning
        # it back on restores whatever those settings were before.
        self.axison = True
        self._hidden_spines: set[str] = set()
        self._grid = bool(rcParams["axes.grid"])
        self._grid_axes = {"x": self._grid, "y": self._grid}
        self._minor_grid_axes = {"x": False, "y": False}
        self._grid_color = _MPL_GRID_COLOR
        self._grid_axis = "both"
        self._grid_style: dict[str, Any] = {}
        self._anchor: Optional[str] = None
        self._cycle = 0
        self._patch_cycle = 0
        self._prop_cycle: Optional[list[str]] = None
        self._load_rc_chrome()
        self.patch = _PatchFacade(self)
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
                self._tick_lengths[axis] = float(style["tick_length"])
            self._axis[axis]["minor_style"] = _rc_minor_axis_style(axis, dpi)

    # -- lifecycle -----------------------------------------------------------

    def remove(self) -> None:
        """Remove this axes from its figure."""
        if self.figure is None or self not in self.figure._axes:
            raise ValueError("Axes is not attached to a figure")
        self.figure.delaxes(self)

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
        # Shared render domains are a snapshot from the preceding Figure
        # materialization pass. Any artist/limit mutation must make the next
        # pass discover the group's new final view before clipping axlines.
        host.__dict__.pop("_shared_render_domains", None)
        if host.figure is not None:
            host.figure._invalidate()

    def _point_scale(self) -> float:
        """Convert Matplotlib points to this figure's output pixels."""
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        return dpi / 72.0

    def _mpl_dash(self, dash: Any, linewidth: Any) -> Any:
        """Scale a Matplotlib dash pattern from points into output pixels.

        Named patterns ("dashed"/"dotted"/"dashdot") become an on/off pixel
        list scaled by the line width and figure DPI, matching Matplotlib's
        ``scale_dashes`` plus point sizing. Explicit numeric sequences use the
        same scale; only ``None`` and the ``"none"`` sentinel pass through.
        """
        if dash is None or dash == "none":
            return dash
        if isinstance(dash, str):
            if dash not in MPL_DASH_PATTERN:
                return dash
            dash = MPL_DASH_PATTERN[dash]
        scale = float(linewidth) * self._point_scale()
        return [round(float(value) * scale, 4) for value in dash]

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
        """The `Line2D` artists owned by this axes."""
        return [item for item in self._owned_artists if isinstance(item, Line2D)]

    @property
    def collections(self) -> list[Any]:
        """The collection artists (scatter/poly/contour) owned by this axes."""
        from ._artists import ContourSet

        return [
            item
            for item in self._owned_artists
            if isinstance(item, (PathCollection, PolyCollection, ContourSet))
        ]

    @property
    def patches(self) -> list[Any]:
        """The wedge patches owned by this axes."""
        from ._artists import Wedge

        return [item for item in self._owned_artists if isinstance(item, Wedge)]

    @property
    def texts(self) -> list[Any]:
        """The `Text` artists owned by this axes."""
        return [item for item in self._owned_artists if isinstance(item, Text)]

    @property
    def images(self) -> list[Any]:
        """The `AxesImage` artists owned by this axes."""
        return [item for item in self._owned_artists if isinstance(item, AxesImage)]

    @property
    def tables(self) -> list[Any]:
        """The `Table` artists owned by this axes."""
        from ._artists import Table

        return [item for item in self._owned_artists if isinstance(item, Table)]

    @property
    def containers(self) -> list[Any]:
        """The bar/errorbar/stem containers registered on this axes."""
        return list(self._containers)

    @property
    def artists(self) -> list[Any]:
        """Owned artists that fall in no other category list."""
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

    def _next_patch_color(self) -> str:
        """Advance Matplotlib's independent fill/patch property cycle."""
        host = self._y2_of or self
        cycle = getattr(host, "_prop_cycle", None) or PROP_CYCLE
        color = cycle[host._patch_cycle % len(cycle)]
        host._patch_cycle += 1
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
        for axis in ("x", "y"):
            key = "y2" if axis == "y" and self._y2_of is not None else axis
            spec = host._scale_specs[key]
            if spec["name"] != "linear":
                _transform_entry_axis(entry, axis, {"name": "linear"}, spec)
        host._entries.append(entry)
        for axis in ("x", "y"):
            key = "y2" if axis == "y" and self._y2_of is not None else axis
            if key in host._tick_expanded_domains:
                self._expand_domain_to_ticks(axis)
        # Aspect modes may be selected before any data is added (the
        # Matplotlib fill gallery does exactly this with ``axis("equal")``).
        # Keep their bounds tied to the current autoscaled data until the user
        # explicitly pins a domain instead of freezing the empty (0, 1) view.
        if host._aspect_equal and not host._explicit_domains:
            host._set_aspect_equal_from_current()
        host._invalidate()
        return entry

    def clear(self) -> None:
        """Reset the axes to a pristine state, removing every plotted thing.

        Drops all entries, owned artists, and containers, and restores axis
        limits, scales, ticks, title, legend, grid, aspect, and the color
        cycle to their rc defaults. ``cla`` is an alias of this method.
        """
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
        self._tick_expanded_domains = set()
        self._tickers = {}
        self._tick_rotation_modes = {"x": None, "y": None}
        self._tick_sides = {
            "x": {"bottom": True, "top": False},
            "y": {"left": self._y2_of is None, "right": self._y2_of is not None},
        }
        self._tick_label_sides = {
            "x": {"labelbottom": True, "labeltop": False},
            "y": {"labelleft": self._y2_of is None, "labelright": self._y2_of is not None},
        }
        self._tick_lengths = {}
        self.axison = True
        self._hidden_spines = set()
        self._title = None
        self._title_style = {}
        self._titles = {}
        self._legend = False
        self._legend_options = {}
        self._legend_items = None
        self._legend_handle = None
        self._legend_artist = None
        self._extra_legends = []
        self._colorbar = None
        self._colorbar_source = None
        self._aspect_equal = False
        self._aspect_value = 1.0
        self._aspect_adjustable = "box"
        self._aspect_bounds = None
        self._insets = []
        self._insets_materialized = False
        self._absolute_plot_ratio = None
        self._plot_box_px = None
        self._padding = None
        self._table_bottom_points = 0.0
        self._annotation_margins = {"x": 0.0, "y": 0.0}
        self._xmargin = float(rcParams["axes.xmargin"])
        self._ymargin = float(rcParams["axes.ymargin"])
        self._rc_margins = {
            "x": self._xmargin,
            "y": self._ymargin,
        }
        self._margin_overrides = set()
        self._tight = None
        self._explicit_domains = set()
        self._grid = bool(rcParams["axes.grid"])
        self._grid_axes = {"x": self._grid, "y": self._grid}
        self._minor_grid_axes = {"x": False, "y": False}
        self._grid_color = _MPL_GRID_COLOR
        self._grid_axis = "both"
        self._grid_style = {}
        self._cycle = 0
        self._patch_cycle = 0
        self._load_rc_chrome()
        self._polar_options = {}
        self._polar_r_options = {}
        if self._projection == "polar":
            self._set_projection("polar")
        self._chart = None
        self._twin = None
        self.xaxis = _AxisProxy(self, "x")
        self.yaxis = _AxisProxy(self, "y")
        self.spines = _SpineProxy(self)
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        for axis in ("x", "y"):
            self._axis[axis]["minor_style"] = _rc_minor_axis_style(axis, dpi)
            style = _rc_axis_style(axis, dpi)
            if style:
                self._axis[axis]["style"] = style
                self._tick_lengths[axis] = float(style["tick_length"])
        self._invalidate()

    cla = clear

    # -- plotting ------------------------------------------------------------

    def plot(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        """Plot y versus x as lines and/or markers.

        Accepts matplotlib's call forms: ``plot(y)``, ``plot(x, y)``,
        ``plot(x, y, fmt)``, and repeated ``x, y, fmt`` groups, where ``fmt``
        is a ``[marker][line][color]`` shorthand such as ``"r--o"``. A 2-D
        operand draws one line per column. Supported keywords: ``color``/``c``,
        ``linewidth``/``lw``, ``linestyle``/``ls``, ``dashes``, ``alpha``,
        ``label``, ``marker``, ``markersize``/``ms``, ``markerfacecolor``/
        ``mfc``, ``markeredgecolor``/``mec``, ``markeredgewidth``/``mew``,
        ``markevery``, ``drawstyle``, and ``transform``; anything else raises
        loudly. Returns the list of `Line2D` handles, one per series.
        """
        data = kwargs.pop("data", None)
        if data is not None:
            args = _replace_plot_data(args, data)
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
        if drawstyle == "steps":
            drawstyle = "steps-pre"
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
            masked_x = np.ma.asarray(x)
            if masked_x.dtype.kind in "iub":
                masked_x = masked_x.astype(np.float64)
            x = np.ma.filled(masked_x, np.nan)
        if np.ma.isMaskedArray(y):
            masked_y = np.ma.asarray(y)
            if masked_y.dtype.kind in "iub":
                masked_y = masked_y.astype(np.float64)
            y = np.ma.filled(masked_y, np.nan)
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
        if per.get("_gapcolor") is not None:
            entry_kwargs["_gapcolor"] = per["_gapcolor"]
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
                        **marker_render_spec(this_marker or "o"),
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
                            **marker_render_spec(this_marker),
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
        self,
        x: ArrayLike,
        y: ArrayLike,
        s: float | ArrayLike | None = None,
        c: ColorsLike | None = None,
        **kwargs: Any,
    ) -> PathCollection:
        """A scatter plot of ``y`` versus ``x``.

        ``s`` is the marker area in points² (scalar or per point); ``c`` is a
        single color, one color per point, or a numeric array mapped through
        ``cmap`` (pin the color limits with ``vmin``/``vmax``). Other
        supported keywords: ``marker``, ``alpha``, ``label``,
        ``edgecolors``/``edgecolor``, ``linewidths``/``linewidth``/``lw``,
        ``plotnonfinite``, and ``transform``. Masked entries are dropped,
        matching matplotlib; ``norm`` and other unsupported keywords raise
        loudly. Returns a `PathCollection`.
        """
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
        alpha_arr = (
            None if alpha is None or np.isscalar(alpha) else np.ma.asarray(alpha).reshape(-1)
        )
        linewidth_arr = (
            None
            if linewidths is None or np.isscalar(linewidths)
            else np.ma.asarray(linewidths).reshape(-1)
        )
        dropped = np.ma.getmaskarray(xv) | np.ma.getmaskarray(yv)
        for channel in (s_arr, alpha_arr, linewidth_arr):
            if channel is not None and len(channel) == len(dropped):
                dropped = dropped | np.ma.getmaskarray(channel)
        if dropped.any():
            # Matplotlib never draws rows masked in geometry or a style channel.
            keep = ~dropped
            xv, yv = xv[keep], yv[keep]
            if s_arr is not None and len(s_arr) == len(dropped):
                s_arr = s_arr[keep]
            if alpha_arr is not None and len(alpha_arr) == len(dropped):
                alpha_arr = alpha_arr[keep]
            if linewidth_arr is not None and len(linewidth_arr) == len(dropped):
                linewidth_arr = linewidth_arr[keep]
            for channel_name, channel in (("c", c), ("edgecolors", edgecolors)):
                if channel is None or isinstance(channel, str):
                    continue
                rows = np.ma.asarray(channel)
                if rows.ndim >= 1 and rows.shape[0] == len(dropped):
                    if channel_name == "c":
                        c = rows[keep]
                    else:
                        edgecolors = rows[keep]
        xv, yv = np.asarray(xv), np.asarray(yv)
        if s_arr is not None:
            s = np.asarray(s_arr)
        if alpha_arr is not None:
            alpha = np.asarray(alpha_arr)
        if linewidth_arr is not None:
            linewidths = np.asarray(linewidth_arr)
        x, y = xv, yv
        if transform is not None:
            x, y = self._transform_points(x, y, transform)
        source_color = None
        c_array = None if c is None or isinstance(c, str) else np.ma.asarray(c)
        single_numeric_color = bool(
            c_array is not None
            and c_array.ndim == 1
            and c_array.shape in {(3,), (4,)}
            and len(c_array) != len(xv)
            and np.issubdtype(c_array.dtype, np.number)
            and isinstance(c, (tuple, list))
        )
        cv = c_array
        if (
            cv is not None
            and cv.ndim == 1
            and len(cv) == len(xv)
            and np.issubdtype(cv.dtype, np.number)
            and not single_numeric_color
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
                if alpha is not None and not np.isscalar(alpha):
                    alpha = np.asarray(alpha)[finite_color]
                if linewidths is not None and not np.isscalar(linewidths):
                    linewidths = np.asarray(linewidths)[finite_color]
                if edgecolors is not None and not isinstance(edgecolors, str):
                    edge_array = np.asarray(edgecolors)
                    if edge_array.ndim >= 1 and edge_array.shape[0] == len(finite_color):
                        edgecolors = edge_array[finite_color]
            x, y, c = xv, yv, cv

        marker_spec = marker_render_spec(marker) if marker is not None else {"symbol": "circle"}
        symbol = str(marker_spec["symbol"])
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
        raw_edge_width = rcParams["patch.linewidth"] if linewidths is None else linewidths
        edge_width_px = (
            0.0 if no_edges else np.asarray(raw_edge_width, dtype=np.float64) * self._point_scale()
        )
        if np.ndim(edge_width_px) == 0:
            edge_width_px = float(edge_width_px)
        size_px = np.asarray(marker_path_px) + edge_width_px
        if np.ndim(size_px) == 0:
            size_px = float(size_px)
        entry_kwargs: dict[str, Any] = {
            "size": size_px,
            # Preserve the long-standing pyplot artist metadata while the
            # core receives alpha through the override channel below.
            "opacity": scalar_float(alpha) if alpha is not None and np.isscalar(alpha) else 1.0,
            "name": str(label) if label is not None else None,
            **marker_spec,
        }
        if alpha is not None:
            entry_kwargs["_artist_alpha"] = (
                scalar_float(alpha) if np.isscalar(alpha) else np.asarray(alpha, dtype=np.float64)
            )
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
        elif isinstance(c, str) or single_numeric_color:
            try:
                entry_kwargs["color"] = resolve_color(c)
            except ValueError:
                entry_kwargs["color"] = np.asarray(c)  # data array, not a color
        elif np.asarray(c).ndim == 2 or not np.issubdtype(np.asarray(c).dtype, np.number):
            entry_kwargs["color"] = resolve_rgba_array(c, len(x), "scatter c")
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
                if isinstance(edge_setting, str):
                    entry_kwargs["stroke"] = resolve_color(edge_setting)
                else:
                    entry_kwargs["stroke"] = resolve_rgba_array(
                        edge_setting, len(x), "scatter edgecolors"
                    )
            entry_kwargs["stroke_width"] = edge_width_px
        entry = self._add("scatter", {"x": x, "y": y, "kwargs": entry_kwargs})
        if source_color is not None:
            entry["source_array"] = source_color
        entry["source_sizes"] = np.asarray(
            rcParams["lines.markersize"] ** 2 if s is None else s, dtype=np.float64
        ).reshape(-1)
        if "colormap" in entry_kwargs:
            levels = _discrete_levels(cmap)
            if levels is not None:
                entry["discrete_levels"] = levels
        artist = PathCollection(self, entry)
        if transform is not None:
            artist._transform = transform
        return artist

    def bar(
        self,
        x: float | ArrayLike,
        height: float | ArrayLike,
        width: float | ArrayLike = 0.8,
        bottom: float | ArrayLike | None = None,
        **kwargs: Any,
    ) -> BarContainer:
        """Vertical bars of the given ``height`` at positions ``x``.

        ``x`` may be numeric positions or category labels; ``bottom`` stacks
        this series on top of another. Supported keywords: ``align``
        (``"center"`` or ``"edge"``), ``color`` (scalar or per bar),
        ``edgecolor``, ``linewidth``, ``alpha``, ``label``, and the
        ``xerr``/``yerr``/``capsize``/``ecolor``/``error_kw`` error-bar
        options; anything else raises loudly. Returns the `BarContainer`
        holding one patch per bar.
        """
        return self._bar_like(x, height, width, bottom, "vertical", kwargs)

    def barh(
        self,
        y: float | ArrayLike,
        width: float | ArrayLike,
        height: float | ArrayLike = 0.8,
        left: float | ArrayLike | None = None,
        **kwargs: Any,
    ) -> BarContainer:
        """Horizontal bars of the given ``width`` at positions ``y``.

        The horizontal twin of `bar`: ``left`` stacks series, ``align`` is
        ``"center"`` or ``"edge"``, and the same styling and error-bar
        keywords apply (``color``, ``edgecolor``, ``linewidth``, ``alpha``,
        ``label``, ``xerr``/``yerr``/``capsize``/``ecolor``/``error_kw``).
        """
        return self._bar_like(y, width, height, left, "horizontal", kwargs)

    def _bar_like(
        self,
        cats: Any,
        vals: Any,
        thickness: Any,
        base: Any,
        orientation: str,
        kwargs: dict[str, Any],
    ) -> BarContainer:
        def materialize_iterable(value: Any) -> Any:
            """Turn one-shot and view iterables into real bar columns.

            ``np.asarray(dict.values())`` is a scalar object array, which made
            one apparent bar and left the raw view to fail later during
            autoscale. Array-like containers such as Series already expose a
            meaningful ndarray and should stay untouched.
            """
            # Keep the common bar path allocation-neutral. In particular,
            # probing a list of category labels with ``np.asarray`` here and
            # again below doubled the string-array conversion cost.
            if value is None or isinstance(value, (str, bytes, list, tuple, range, np.ndarray)):
                return value
            if np.isscalar(value):
                return value
            array = np.asarray(value)
            if array.ndim != 0:
                return value
            try:
                return list(value)
            except TypeError:
                return value

        cats = materialize_iterable(cats)
        vals = materialize_iterable(vals)
        thickness = materialize_iterable(thickness)
        base = materialize_iterable(base)
        thickness_is_scalar = np.asarray(thickness).ndim == 0
        base_is_none = base is None
        base_is_scalar = base_is_none or np.asarray(base).ndim == 0
        try:
            cats, vals, broadcast_thickness, broadcast_base = np.broadcast_arrays(
                np.atleast_1d(cats),
                np.atleast_1d(vals),
                np.atleast_1d(thickness),
                np.atleast_1d(0.0 if base_is_none else base),
                subok=True,
            )
        except ValueError:
            raise ValueError(
                "shape mismatch: bar positional inputs cannot be broadcast to a single shape"
            ) from None
        if cats.ndim != 1:
            raise ValueError("bar positional inputs must be scalar or 1-D")
        thickness = thickness if thickness_is_scalar else broadcast_thickness
        if not base_is_none:
            base = base if base_is_scalar else np.array(broadcast_base, copy=True)
        cat_array = np.asarray(cats)
        if cat_array.dtype.kind == "U" and cat_array.dtype.isnative:
            # _plain_text only rewrites labels containing TeX markers; a
            # vectorized scan skips the per-label Python loop for the common
            # plain-string case (O(categories) per build otherwise). The scan
            # reads the UCS4 storage as codepoints rather than using
            # np.char/np.strings, whose first call pays a multi-millisecond
            # lazy ufunc setup — a one-shot cost CodSpeed attributes to
            # whichever chart build hits it first. The uint32 view is only
            # codepoints on native byte order; swapped arrays take the loop.
            flat = cat_array.reshape(-1)
            codes = np.ascontiguousarray(flat).view(np.uint32)
            if (codes == 36).any() or (codes == 92).any():  # "$" and "\" codepoints
                cats = np.asarray([_plain_text(value) for value in flat]).reshape(cat_array.shape)
            else:
                cats = cat_array
        elif cat_array.dtype.kind in {"U", "S", "O"} and all(
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
        raw_error_kw = kwargs.pop("error_kw", None)
        if raw_error_kw is None:
            error_kw: dict[str, Any] = {}
        elif isinstance(raw_error_kw, Mapping):
            # Matplotlib copies this caller-owned mapping before adding the
            # independent bar defaults.  Its setdefault order deliberately
            # gives nested error_kw values precedence over direct ecolor and
            # capsize arguments.
            error_kw = dict(raw_error_kw)
        else:
            raise TypeError("bar()/barh() error_kw must be a mapping or None")
        direct_capsize = kwargs.pop("capsize", rcParams["errorbar.capsize"])
        direct_ecolor = kwargs.pop("ecolor", "#000000")
        error_kw.setdefault("capsize", direct_capsize)
        error_kw.setdefault("ecolor", direct_ecolor)
        align = kwargs.pop("align", "center")
        if align not in {"center", "edge"}:
            raise ValueError("bar()/barh() align must be 'center' or 'edge'")
        n_bars = int(np.asarray(vals).size)
        thickness_array = np.asarray(thickness, dtype=np.float64)
        if thickness_array.ndim == 0:
            thickness_value: float | np.ndarray = float(thickness_array)
        else:
            try:
                thickness_value = np.broadcast_to(thickness_array, (n_bars,)).astype(
                    np.float64, copy=False
                )
            except ValueError:
                raise ValueError(
                    f"bar thickness must be scalar or broadcast to the {n_bars} bars"
                ) from None
        if not np.isfinite(thickness_value).all() or np.any(thickness_value <= 0.0):
            raise ValueError("bar thickness values must be finite and positive")
        if align == "edge":
            try:
                cats = np.asarray(cats, dtype=np.float64) + thickness_value / 2.0
            except (TypeError, ValueError):
                raise ValueError("bar align='edge' requires numeric positions") from None
        check_unsupported(kwargs, "bar()/barh()")
        patch_labels: Optional[list[str]] = None
        if label is not None and not isinstance(label, str) and np.iterable(label):
            patch_labels = [_plain_text(value) for value in label]
            if len(patch_labels) != n_bars:
                raise ValueError(
                    f"number of labels ({len(patch_labels)}) "
                    f"does not match number of bars ({n_bars})."
                )

        def paint(value: Any, label_text: str, default: Optional[str] = None) -> Any:
            if value is None:
                return default
            if isinstance(value, str):
                return resolve_color(value)
            array = np.asarray(value)
            if (
                array.ndim == 1
                and array.shape in {(3,), (4,)}
                and np.issubdtype(array.dtype, np.number)
            ):
                return resolve_color(value)
            return resolve_rgba_array(value, n_bars, label_text)

        entry_kwargs: dict[str, Any] = {
            "color": paint(color, "bar color", self._next_color()),
            "width": thickness_value,
            "opacity": 1.0,
            # A sequence labels the individual Rectangle patches in
            # Matplotlib, not the BarContainer.  Keep the batched data trace
            # unnamed; _chart_children emits empty, named bar proxies for the
            # visible legend entries without splitting the bar geometry.
            "name": (
                None if patch_labels is not None else str(label) if label is not None else None
            ),
            "orientation": orientation,
        }
        if alpha is not None:
            entry_kwargs["_artist_alpha"] = (
                scalar_float(alpha) if np.isscalar(alpha) else np.asarray(alpha, dtype=np.float64)
            )
        if base is not None:
            entry_kwargs["base"] = np.array(base, copy=True) if not np.isscalar(base) else base
        if edgecolor is not None:
            entry_kwargs["stroke"] = paint(edgecolor, "bar edgecolor")
            entry_kwargs["stroke_width"] = (
                np.asarray(linewidth, dtype=np.float64)
                if linewidth is not None and not np.isscalar(linewidth)
                else scalar_float(linewidth or 1.0)
            )
        elif linewidth is not None:
            entry_kwargs["stroke_width"] = (
                np.asarray(linewidth, dtype=np.float64)
                if not np.isscalar(linewidth)
                else scalar_float(linewidth)
            )
        entry = self._add(
            "bar",
            {
                "x": cats,
                "y": vals,
                "kwargs": entry_kwargs,
                **({"patch_labels": patch_labels} if patch_labels is not None else {}),
            },
        )
        errorbar = None
        if xerr is not None or yerr is not None:
            positions = np.asarray(cats)
            values = np.asarray(vals, dtype=np.float64)
            bases = np.zeros_like(values) if base is None else np.broadcast_to(base, values.shape)
            if orientation == "vertical":
                ex, ey, exerr, eyerr = positions, bases + values, xerr, yerr
            else:
                ex, ey, exerr, eyerr = bases + values, positions, xerr, yerr
            error_kw.setdefault("label", "_nolegend_")
            errorbar = self.errorbar(
                ex,
                ey,
                xerr=exerr,
                yerr=eyerr,
                fmt="none",
                **error_kw,
            )
        container = BarContainer(self, entry)
        container.errorbar = errorbar
        return container

    def hist(
        self,
        x: Any,
        bins: int | ArrayLike | str = 10,
        range: Any = None,  # noqa: A002 - matplotlib's own signature
        density: bool = False,
        cumulative: bool | int = False,
        **kwargs: Any,
    ) -> tuple[Any, np.ndarray, Any]:
        """A histogram of ``x``.

        ``x`` is one dataset or a sequence of datasets (drawn grouped, or
        stacked with ``stacked=True``); ``bins``/``range`` follow
        `numpy.histogram`, ``density`` normalizes, and ``cumulative``
        accumulates. Supported keywords: ``weights``, ``color``,
        ``edgecolor``, ``alpha``, ``label``, ``histtype`` (``"bar"``/
        ``"barstacked"``/``"step"``/``"stepfilled"``), ``orientation``, and
        ``stacked``; anything else raises loudly. Returns
        ``(counts, bin_edges, patches)`` as matplotlib does.
        """
        color = kwargs.pop("color", None)
        facecolor = kwargs.pop("facecolor", None)
        fill = kwargs.pop("fill", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        histtype = kwargs.pop("histtype", "bar")
        weights = kwargs.pop("weights", None)
        orientation = kwargs.pop("orientation", "vertical")
        stacked = bool(kwargs.pop("stacked", False))
        edgecolor = kwargs.pop("edgecolor", None)
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", None))
        linestyle = kwargs.pop("linestyle", kwargs.pop("ls", None))
        rwidth = kwargs.pop("rwidth", None)
        hatch = kwargs.pop("hatch", None)
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

        if np.isscalar(x):
            datasets = [np.atleast_1d(np.asarray(x, dtype=np.float64))]
        elif isinstance(x, np.ndarray) and x.ndim == 1 and x.dtype.kind in "fiub":
            # The common numeric-array call must not round-trip through an
            # object array: boxing every element just to sniff the input shape
            # is an O(n) cost per build (tests/pyplot/test_perf_guardrail.py).
            datasets = [np.asarray(x, dtype=np.float64)]
        elif isinstance(x, np.ndarray) and x.ndim == 2:
            # NB: iterate columns via .T — `range` here is the bin-range parameter.
            datasets = [np.asarray(column, dtype=np.float64) for column in x.T]
        else:
            raw = np.asarray(x, dtype=object)
            if raw.ndim == 1 and (len(raw) == 0 or np.isscalar(raw[0])):
                datasets = [np.asarray(x, dtype=np.float64)]
            else:
                datasets = [np.asarray(values, dtype=np.float64) for values in x]
        if isinstance(bins, (int, np.integer)) and not isinstance(bins, bool):
            # Fixed bin count: the edges depend only on the finite data range,
            # so a native NaN-skipping min/max scan replaces the filtered
            # concatenated copy. numpy applies its own defaults/expansion to
            # the range exactly as it would to data-derived outer edges.
            from xy import kernels

            if range is None:
                spans = [span for span in map(kernels.min_max, datasets) if span is not None]
                data_range = (
                    (min(lo for lo, _ in spans), max(hi for _, hi in spans)) if spans else None
                )
            else:
                data_range = range
            edges = np.histogram_bin_edges(np.empty(0), bins=bins, range=data_range)
        else:
            all_finite = np.concatenate([values[np.isfinite(values)] for values in datasets])
            edges = np.histogram_bin_edges(all_finite, bins=bins, range=range)
        if weights is None:
            weight_sets = [None] * len(datasets)
        elif len(datasets) == 1:
            weight_sets = [np.asarray(weights, dtype=np.float64)]
        else:
            weight_sets = [np.asarray(value, dtype=np.float64) for value in weights]
        stacked = stacked or histtype == "barstacked"
        # Matplotlib bins stacked inputs as raw (possibly weighted) mass,
        # cumulatively stacks the datasets, and only then normalizes the top
        # envelope.  Normalizing each input independently would give every
        # dataset unit area and is especially wrong for unequal bin widths.
        counts_array = np.vstack(
            [
                np.histogram(
                    values,
                    bins=edges,
                    weights=w,
                    density=density and not stacked,
                )[0].astype(np.float64)
                for values, w in zip(datasets, weight_sets, strict=True)
            ]
        )
        if stacked:
            tops = np.cumsum(counts_array, axis=0)
            if density:
                with np.errstate(divide="ignore", invalid="ignore"):
                    tops = (tops / np.diff(edges)) / tops[-1].sum()
            counts_array = np.diff(
                np.vstack((np.zeros((1, counts_array.shape[1]), dtype=np.float64), tops)),
                axis=0,
            )
        counts = list(counts_array)
        if cumulative:
            reverse = isinstance(cumulative, (int, float, np.number)) and cumulative < 0
            cumulative_tops = np.cumsum(counts_array, axis=0) if stacked else counts_array
            cumulative_tops = np.asarray(
                [
                    (
                        np.cumsum((values * np.diff(edges) if density else values)[::-1])[::-1]
                        if reverse
                        else np.cumsum(values * np.diff(edges) if density else values)
                    )
                    for values in cumulative_tops
                ]
            )
            counts_array = (
                np.diff(
                    np.vstack(
                        (
                            np.zeros((1, cumulative_tops.shape[1]), dtype=np.float64),
                            cumulative_tops,
                        )
                    ),
                    axis=0,
                )
                if stacked
                else cumulative_tops
            )
            counts = list(counts_array)

        def dataset_values(value: Any, name: str, *, color_value: bool = False) -> list[Any]:
            if value is None:
                return [None] * len(datasets)
            if color_value:
                try:
                    resolve_color(value)
                except (TypeError, ValueError):
                    pass
                else:
                    return [value] * len(datasets)
            if np.isscalar(value):
                return [value] * len(datasets)
            values = list(value)
            if len(values) != len(datasets):
                raise ValueError(
                    f"hist {name} sequence must have length {len(datasets)}, got {len(values)}"
                )
            return values

        colors = dataset_values(color, "color", color_value=True)
        facecolors = dataset_values(facecolor, "facecolor", color_value=True)
        edgecolors = dataset_values(edgecolor, "edgecolor", color_value=True)
        linewidths = dataset_values(linewidth, "linewidth")
        linestyles = dataset_values(linestyle, "linestyle")
        hatches = dataset_values(hatch, "hatch")
        # Matplotlib intentionally tolerates label-count mismatches: a scalar
        # labels only the first dataset, short sequences leave later datasets
        # unlabeled, and extra labels are ignored.
        label_values = [] if label is None else np.atleast_1d(np.asarray(label, dtype=str)).tolist()
        labels = (label_values + [None] * len(datasets))[: len(datasets)]
        containers: list[BarContainer] = []
        base = np.zeros(len(edges) - 1, dtype=np.float64)
        centers = (edges[:-1] + edges[1:]) * 0.5
        # matplotlib's bin filling: a single (or stacked) series spans the full
        # bin so adjacent bars touch; only multiple side-by-side series shrink
        # to 0.8 of the bin, split evenly.  The shim previously applied the 0.8
        # factor to single-series hists too, leaving visible gaps.
        binwidths = np.diff(edges)
        rel_width = (
            float(np.clip(float(rwidth), 0.0, 1.0))
            if rwidth is not None
            else (1.0 if (stacked or len(datasets) == 1) else 0.8)
        )
        width = binwidths * rel_width / (1 if stacked else len(datasets))
        histogram_entry_start = len(self._entries)
        histogram_entry_groups: list[list[dict[str, Any]]] = []
        # Keep the common uniform-bin entry scalar. Besides avoiding a
        # redundant per-bin column, explicit legends expect one swatch width;
        # genuinely unequal bins retain their exact width array.
        entry_width: float | np.ndarray = (
            float(width[0])
            if len(width) and np.allclose(width, width[0], rtol=1e-12, atol=0.0)
            else width
        )

        def add_dashed_bar_perimeters(
            positions: np.ndarray,
            values: np.ndarray,
            current_base: np.ndarray,
            resolved_edge: Optional[str],
            resolved_width: float,
            dash: Any,
        ) -> None:
            if dash in (None, "none") or resolved_edge is None:
                return
            half_width = width / 2.0
            low = positions - half_width
            high = positions + half_width
            top = current_base + values
            if orientation == "vertical":
                x0 = np.concatenate((low, high, high, low))
                y0 = np.concatenate((current_base, current_base, top, top))
                x1 = np.concatenate((high, high, low, low))
                y1 = np.concatenate((current_base, top, top, current_base))
            else:
                x0 = np.concatenate((current_base, current_base, top, top))
                y0 = np.concatenate((low, high, high, low))
                x1 = np.concatenate((current_base, top, top, current_base))
                y1 = np.concatenate((high, high, low, low))
            self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": {
                        "color": resolved_edge,
                        "width": resolved_width,
                        "dash": dash,
                        "opacity": 1.0 if alpha is None else float(alpha),
                        "name": None,
                    },
                },
            )

        for index, values in enumerate(counts):
            group_start = len(self._entries)
            positions = centers if stacked else centers + (index - (len(datasets) - 1) / 2) * width
            current_base = base.copy() if stacked else np.zeros_like(values)
            series_color = (
                resolve_color(colors[index]) if colors[index] is not None else self._next_color()
            )
            resolved_color = (
                resolve_color(facecolors[index]) if facecolors[index] is not None else series_color
            )
            resolved_edge = (
                resolve_color(edgecolors[index]) if edgecolors[index] is not None else None
            )
            resolved_width = (
                float(linewidths[index])
                if linewidths[index] is not None
                else float(rcParams["patch.linewidth"]) * self._point_scale()
            )
            linestyle_value = "-" if linestyles[index] is None else str(linestyles[index])
            if linestyle_value not in LINESTYLE_TO_DASH:
                raise ValueError(f"unsupported histogram linestyle: {linestyle_value!r}")
            dash = self._mpl_dash(LINESTYLE_TO_DASH[linestyle_value], resolved_width)
            # Matplotlib's Patch._set_edgecolor(None) makes a filled patch's
            # edge transparent unless patch.force_edgecolor is enabled.
            filled = histtype in {"bar", "barstacked", "stepfilled"} if fill is None else bool(fill)
            if not filled and resolved_edge is None:
                resolved_edge = (
                    series_color
                    if histtype == "step"
                    else resolve_color(rcParams["patch.edgecolor"])
                )
            elif filled and histtype == "step" and resolved_edge is None:
                resolved_edge = series_color

            if orientation == "horizontal" and histtype.startswith("step") and filled:
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
                            "width": entry_width,
                            "orientation": "horizontal",
                            "color": resolved_color,
                            "opacity": 1.0 if alpha is None else float(alpha),
                            "name": None if labels[index] is None else str(labels[index]),
                            **(
                                {"stroke": resolved_edge, "stroke_width": resolved_width}
                                if resolved_edge is not None and dash is None
                                else {}
                            ),
                        },
                    },
                )
                add_dashed_bar_perimeters(
                    positions, values, current_base, resolved_edge, resolved_width, dash
                )
            elif orientation == "horizontal" and histtype.startswith("step"):
                step_values = values + current_base
                # Matplotlib's unfilled step histogram is the top envelope
                # plus one connector to the current baseline at each end.  A
                # stacked series therefore starts/ends at the previous stack,
                # not at zero.
                path_x = np.concatenate(
                    (
                        current_base[:1],
                        np.repeat(step_values, 2),
                        current_base[-1:],
                    )
                )
                path_y = np.concatenate(
                    (
                        edges[:1],
                        np.repeat(edges, 2)[1:-1],
                        edges[-1:],
                    )
                )
                entry = self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": (path_x[:-1], path_y[:-1], path_x[1:], path_y[1:]),
                        "kwargs": {
                            "color": resolved_edge or series_color,
                            "width": resolved_width,
                            "dash": dash,
                            "name": None if labels[index] is None else str(labels[index]),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            elif histtype.startswith("step") and filled:
                # matplotlib fills the step polygon down to the baseline; the
                # area mark takes the pre-expanded step vertices verbatim.
                tops = values + current_base
                no_edge = resolved_edge in (None, "transparent") or (
                    isinstance(resolved_edge, str)
                    and resolved_edge.startswith("rgba(")
                    and resolved_edge.endswith(",0)")
                )
                entry = self._add(
                    "@mark",
                    {
                        "factory": "area",
                        "args": (np.repeat(edges, 2)[1:-1], np.repeat(tops, 2)),
                        "kwargs": {
                            "base": np.repeat(current_base, 2),
                            "color": resolved_color,
                            "line_color": None if no_edge else resolved_edge,
                            "line_width": 0.0 if no_edge else resolved_width,
                            "line_opacity": 1.0 if alpha is None else float(alpha),
                            "stroke_perimeter": not no_edge,
                            "dash": dash,
                            "name": None if labels[index] is None else str(labels[index]),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            elif histtype.startswith("step"):
                step_values = values + current_base
                # Keep the compact stairs trace for the O(bins) top envelope,
                # then add only Matplotlib's two missing baseline connectors.
                self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": (
                            edges[[0, -1]],
                            np.asarray((current_base[0], step_values[-1])),
                            edges[[0, -1]],
                            np.asarray((step_values[0], current_base[-1])),
                        ),
                        "kwargs": {
                            "color": resolved_edge or series_color,
                            "width": resolved_width,
                            "dash": dash,
                            "name": None,
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
                entry = self._add(
                    "@mark",
                    {
                        "factory": "stairs",
                        "args": (step_values, edges),
                        "kwargs": {
                            "color": resolved_edge or series_color,
                            "width": resolved_width,
                            "dash": dash,
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
                            "width": entry_width,
                            "orientation": orientation,
                            "color": "transparent" if fill is False else resolved_color,
                            "opacity": 1.0 if alpha is None else float(alpha),
                            "name": None if labels[index] is None else str(labels[index]),
                            **(
                                {"stroke": resolved_edge, "stroke_width": resolved_width}
                                if resolved_edge is not None and dash is None
                                else {}
                            ),
                        },
                    },
                )
                add_dashed_bar_perimeters(
                    positions, values, current_base, resolved_edge, resolved_width, dash
                )
                if hatches[index]:
                    self._stairs_hatch(
                        values + current_base,
                        positions - width / 2.0,
                        current_base,
                        orientation,
                        {
                            "color": resolved_edge or resolve_color(rcParams["patch.edgecolor"]),
                            "facecolor": resolved_color,
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                        hatch=str(hatches[index]),
                        right_edges=positions + width / 2.0,
                    )
            containers.append(BarContainer(self, entry))
            histogram_entry_groups.append(self._entries[group_start:])
            if stacked:
                base += values
        if stacked and histtype.startswith("step"):
            # Matplotlib draws stacked step polygons from the top dataset
            # downward, so the topmost outline cannot be hidden by lower
            # layers. Its automatic legend follows that artist insertion order
            # (top-to-bottom), while the returned patch containers are restored
            # to the caller's original dataset order. Keep those two contracts
            # distinct here as well.
            self._entries[histogram_entry_start:] = [
                entry for group in reversed(histogram_entry_groups) for entry in group
            ]
        returned = np.vstack(counts)
        if stacked:
            returned = np.cumsum(returned, axis=0)
        return (
            (returned[0] if len(datasets) == 1 else returned),
            edges,
            (containers[0] if len(containers) == 1 else containers),
        )

    def fill_between(
        self, x: ArrayLike, y1: float | ArrayLike, y2: float | ArrayLike = 0.0, **kwargs: Any
    ) -> PolyCollection:
        """Fill the area between two horizontal curves ``y1`` and ``y2``.

        Supported keywords: ``where`` masks the fill to a boolean condition
        (``interpolate=True`` closes the gaps at crossings), ``step`` fills
        as steps (``"pre"``/``"post"``/``"mid"``), and
        ``color``/``facecolor``/``fc``, ``alpha``, ``label``, and
        ``transform`` style the patch; anything else raises loudly. Returns
        a `PolyCollection`.
        """
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
        resolved_color = resolve_color(color) if color is not None else self._next_patch_color()
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
            # Matplotlib still returns a collection handle, but there is no
            # polygon to retain when no pair of adjacent points is selected.
            # Keep that logical empty artist out of the render-entry list
            # instead of exporting an all-NaN transparent area.
            empty = {
                "kind": "area",
                "y_axis": "y2" if self._y2_of is not None else "y",
                "x": np.empty(0, dtype=np.float64),
                "y": np.empty(0, dtype=np.float64),
                "kwargs": {
                    "base": np.empty(0, dtype=np.float64),
                    "color": resolved_color,
                    "opacity": float(alpha) if alpha is not None else 1.0,
                    "name": str(label) if label is not None else None,
                },
            }
            return PolyCollection(self, empty)
        return PolyCollection(self, entries[0])

    def imshow(self, z: ArrayLike, cmap: Any = None, **kwargs: Any) -> AxesImage:
        """Display a 2-D scalar array or RGB(A) image.

        ``z`` is ``(M, N)`` scalar data mapped through ``cmap`` or an
        ``(M, N, 3|4)`` RGB(A) array. Supported keywords: ``vmin``/``vmax``
        (or ``clim``) pin the color limits, ``alpha`` (scalar or array),
        ``origin`` (``"upper"``/``"lower"``), ``aspect``, ``extent``,
        ``interpolation``, ``norm``, ``colorizer``, ``clip_path``, and
        ``transform``; unsupported keywords or values raise loudly. Returns
        an `AxesImage`.
        """
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
            "auto",
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
        if interpolation_stage not in (None, "auto", "data", "rgba"):
            raise ValueError("imshow interpolation_stage must be 'auto', 'data', 'rgba', or None")
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
        self._aspect_value = 1.0
        check_unsupported(kwargs, "imshow()")
        # Matplotlib images own their array.  Keep the logical source separate
        # from the normalized/resampled render buffer so later caller mutation
        # cannot rewrite either side of the artist behind its back.
        source_grid = np.ma.asarray(z).copy()
        masked_grid = np.ma.asarray(source_grid, dtype=np.float64)
        grid = masked_grid.filled(np.nan)
        truecolor = grid.ndim == 3 and grid.shape[-1] in (3, 4)
        if not truecolor and grid.ndim != 2:
            raise ValueError(f"imshow image data must be 2-D or RGB(A), got shape {grid.shape}")
        truecolor_ceiling = (
            255.0 if truecolor and np.issubdtype(np.asanyarray(z).dtype, np.integer) else 1.0
        )
        source_rows, source_cols = grid.shape[:2]
        effective_interpolation = (
            rcParams["image.interpolation"] if interpolation is None else interpolation
        )
        (
            effective_interpolation,
            effective_interpolation_stage,
            interpolation_width,
            interpolation_height,
        ) = _resolve_imshow_sampling(
            grid.shape[:2],
            effective_interpolation,
            interpolation_stage,
        )
        if clim is not None:
            vmin, vmax = clim
        norm_scale = "linear"
        resolved_norm_domain: tuple[float, float] | None = None
        boundary_boundaries: np.ndarray | None = None
        boundary_colors: np.ndarray | None = None
        prepared_boundary = (
            None
            if truecolor
            else prepare_boundary_norm(
                masked_grid,
                norm,
                cmap if cmap is not None else rcParams["image.cmap"],
                vmin,
                vmax,
            )
        )
        if prepared_boundary is not None:
            grid = prepared_boundary.rgba
            resolved_norm_domain = prepared_boundary.domain
            boundary_boundaries = prepared_boundary.boundaries
            boundary_colors = prepared_boundary.band_colors
            vmin, vmax = resolved_norm_domain
            truecolor = True
        bounded_norm = isinstance(norm, str) or type(norm).__name__ in {"Normalize", "LogNorm"}
        if prepared_boundary is None and not truecolor and bounded_norm:
            mapped_grid, resolved_norm_domain, norm_scale = normalize_scalar_grid(
                masked_grid, norm, vmin, vmax
            )
            if resolved_norm_domain is not None:
                vmin, vmax = resolved_norm_domain
            if norm_scale == "log":
                grid = scalar_grid_rgba(
                    mapped_grid, cmap if cmap is not None else rcParams["image.cmap"]
                )
                truecolor = True
        elif norm is not None:
            norm_vmin, norm_vmax = getattr(norm, "vmin", None), getattr(norm, "vmax", None)
            if norm_vmin is not None and norm_vmax is not None:
                vmin, vmax = norm_vmin, norm_vmax
        cmap_extremes = {key: cmap_extreme(cmap, key) for key in ("bad", "under", "over")}
        bad = cmap_extremes["bad"]
        has_extremes = (
            cmap_extremes["under"] is not None
            or cmap_extremes["over"] is not None
            or (bad is not None and not np.array_equal(bad, np.zeros(4, dtype=np.float64)))
        )
        # A resampled colormap (plt.get_cmap(name, N)) with no *customized*
        # extremes must render N flat bands through the ordinary heatmap path so
        # a later plt.clim() still applies; only genuine set_under/over/bad
        # customization needs the Python-baked truecolor branch below.
        imshow_levels = _discrete_levels(cmap) if not truecolor and norm is None else None
        if imshow_levels is not None and has_extremes:
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

            under = cmap_extreme(cmap, "under", (0.0, 0.0, 0.0, 1.0))
            over = cmap_extreme(cmap, "over", (1.0, 1.0, 1.0, 1.0))
            bad = cmap_extreme(cmap, "bad", (0.0, 0.0, 0.0, 0.0))
            assert under is not None and over is not None and bad is not None
            rgba[grid < lo] = under
            rgba[grid > hi] = over
            rgba[~np.isfinite(grid) | np.ma.getmaskarray(masked_grid)] = bad
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
            and effective_interpolation_stage == "rgba"
            and effective_interpolation not in ("none", "nearest")
        ):
            grid = _scalar_grid_rgba(
                grid,
                cmap if cmap is not None else rcParams["image.cmap"],
                vmin,
                vmax,
            )
            truecolor = True
        if effective_interpolation not in ("none", "nearest") and min(grid.shape[:2]) >= 2:
            # The notebook's ordinary image box is ~369 px per side. A 128²
            # intermediate left each interpolated sample covering about 3×3
            # display pixels because heatmaps intentionally use nearest texture
            # sampling. Keep a bounded 512–1024 px surface so non-nearest
            # imshow output is at least display-resolution without making a
            # large source image allocate or multiply dense source-sized
            # resampling matrices. Nearest retains the original source cells.
            grid = _resample_grid(
                grid,
                interpolation_width,
                interpolation_height,
                effective_interpolation,
            )
            if truecolor:
                # Ringing filters legitimately overshoot their input range.
                # Scalar interpolation keeps that overshoot so normalization
                # can expose under/over colors, but RGBA output is bounded
                # channel data in Matplotlib and must be saturated before
                # static uint conversion instead of wrapping to black.
                grid = np.clip(grid, 0.0, truecolor_ceiling)
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
            bounds = (-0.5, source_cols - 0.5, -0.5, source_rows - 0.5)
            # Resampling changes texture resolution, never the image's data
            # coordinates. Give the intermediate samples explicit centers so
            # the core infers Matplotlib's original MxN half-cell extent
            # instead of exposing the implementation's 512--1024 grid.
            if (rows, cols) != (source_rows, source_cols):
                left, right, bottom, top = bounds
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
                "z": np.asanyarray(grid).copy(),
                "source_z": source_grid,
                "kwargs": entry_kwargs,
                "clip_path": clip_path,
                "extent": bounds,
                "_imshow_state": {
                    "cmap": cmap,
                    "kwargs": {
                        "vmin": vmin,
                        "vmax": vmax,
                        "alpha": alpha,
                        "origin": origin,
                        "aspect": aspect,
                        "extent": extent,
                        "interpolation": interpolation,
                        "interpolation_stage": interpolation_stage,
                        "norm": norm,
                        "clip_path": clip_path,
                    },
                },
            },
        )
        if norm_scale != "linear":
            entry["_mpl_norm_scale"] = norm_scale
        if resolved_norm_domain is not None:
            entry["_mpl_domain"] = resolved_norm_domain
        if imshow_levels is not None:
            entry["discrete_levels"] = imshow_levels
        if boundary_boundaries is not None and boundary_colors is not None:
            entry["discrete_levels"] = len(boundary_boundaries) - 1
            entry["discrete_boundaries"] = boundary_boundaries
            entry["discrete_colors"] = boundary_colors
        image = AxesImage(self, entry)
        if clip_path is not None:
            image.set_clip_path(clip_path)
        return image

    def _set_axes_image_data(self, image: AxesImage, z: Any) -> None:
        """Re-run an AxesImage through imshow's canonical preparation path.

        A temporary artist is used only as the normalized result carrier; it is
        removed before returning, leaving the original artist and entry identity
        stable for colorbars, ownership lists, and external handles.
        """
        entry = image._entry
        state = entry.get("_imshow_state")
        if state is None:
            entry["source_z"] = np.ma.asarray(z).copy()
            entry["z"] = np.asanyarray(z).copy()
            self._invalidate()
            return
        replacement = self.imshow(z, state["cmap"], **state["kwargs"])
        prepared = replacement._entry
        self._remove_entry(prepared)
        self._unregister_artist(replacement)

        entry["source_z"] = np.ma.asarray(prepared["source_z"]).copy()
        entry["z"] = np.asanyarray(prepared["z"]).copy()
        entry["extent"] = prepared["extent"]
        for coordinate in ("x", "y"):
            if coordinate in prepared["kwargs"]:
                entry["kwargs"][coordinate] = np.asanyarray(prepared["kwargs"][coordinate]).copy()
            else:
                entry["kwargs"].pop(coordinate, None)
        if "discrete_levels" in prepared:
            entry["discrete_levels"] = prepared["discrete_levels"]
        else:
            entry.pop("discrete_levels", None)
        self._invalidate()

    def step(self, x: ArrayLike, y: ArrayLike, *args: Any, **kwargs: Any) -> list[Line2D]:
        """A step plot of ``y`` versus ``x``.

        ``where`` places the step transition at ``"pre"`` (default),
        ``"post"``, or ``"mid"``. Styled by the `plot` line keywords
        (``color``/``c``, ``linewidth``/``lw``, ``linestyle``/``ls``,
        ``dashes``, ``alpha``, ``label``); anything else raises loudly.
        """
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
        """A horizontal line spanning the axes at data coordinate ``y``.

        ``xmin``/``xmax`` bound it as axes fractions in [0, 1]. Supported
        styling keywords: ``color``/``c``/``facecolor``, ``linewidth``/``lw``,
        ``linestyle``/``ls``, ``alpha``, and ``label``; anything else raises
        loudly.
        """
        return Line2D(self, self._annotation("hline", (y,), kwargs))

    def axvline(self, x: float = 0.0, **kwargs: Any) -> Line2D:
        """A vertical line spanning the axes at data coordinate ``x``.

        ``ymin``/``ymax`` bound it as axes fractions in [0, 1]; the same
        styling keywords as `axhline` apply (``color``/``c``/``facecolor``,
        ``linewidth``/``lw``, ``linestyle``/``ls``, ``alpha``, ``label``).
        """
        return Line2D(self, self._annotation("vline", (x,), kwargs))

    def axhspan(self, ymin: float, ymax: float, **kwargs: Any) -> Artist:
        """A horizontal band spanning the axes between ``ymin`` and ``ymax``.

        ``xmin``/``xmax`` bound it as axes fractions in [0, 1];
        ``color``/``c``/``facecolor``, ``alpha``, ``linestyle``/``ls``, and
        ``label`` style the patch. Anything else raises loudly.
        """
        return Artist(self, self._annotation("y_band", (ymin, ymax), kwargs))

    def axvspan(self, xmin: float, xmax: float, **kwargs: Any) -> Artist:
        """A vertical band spanning the axes between ``xmin`` and ``xmax``.

        ``ymin``/``ymax`` bound it as axes fractions in [0, 1]; the same
        styling keywords as `axhspan` apply.
        """
        return Artist(self, self._annotation("x_band", (xmin, xmax), kwargs))

    def _annotation(self, kind: str, args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
        color = kwargs.pop("color", kwargs.pop("c", kwargs.pop("facecolor", None)))
        alpha = kwargs.pop("alpha", None)
        lw = kwargs.pop("linewidth", kwargs.pop("lw", None))
        label = kwargs.pop("label", None)
        marker = kwargs.pop("marker", None)
        marker_size = kwargs.pop("markersize", kwargs.pop("ms", None))
        marker_face = kwargs.pop("markerfacecolor", kwargs.pop("mfc", None))
        marker_edge = kwargs.pop("markeredgecolor", kwargs.pop("mec", None))
        marker_edge_width = kwargs.pop("markeredgewidth", kwargs.pop("mew", None))
        if kind not in {"hline", "vline"} and any(
            value is not None
            for value in (marker, marker_size, marker_face, marker_edge, marker_edge_width)
        ):
            raise TypeError(f"xy.pyplot ax{kind}() does not accept line marker keywords")
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
        marker_base_color = (
            resolve_color(color) if color is not None else self._next_color() if marker else None
        )
        if marker_base_color is not None:
            akw.setdefault("color", marker_base_color)
        entry = self._add(f"@{kind}", {"args": args, "kwargs": akw})
        if marker is not None:
            path_size = (
                float(rcParams["lines.markersize"] if marker_size is None else marker_size)
                * self._point_scale()
            )
            edge_visible = not (isinstance(marker_edge, str) and marker_edge.lower() == "none")
            edge_width = (
                float(
                    rcParams["lines.markeredgewidth"]
                    if marker_edge_width is None
                    else marker_edge_width
                )
                * self._point_scale()
                if edge_visible
                else 0.0
            )
            entry["endpoint_marker"] = {
                **marker_render_spec(marker),
                "size": path_size + edge_width,
                "color": resolve_color(
                    marker_face if marker_face not in (None, "auto") else marker_base_color
                ),
                "opacity": float(alpha) if alpha is not None else 1.0,
                **(
                    {
                        "stroke": resolve_color(
                            marker_edge if marker_edge not in (None, "auto") else marker_base_color
                        ),
                        "stroke_width": edge_width,
                    }
                    if edge_visible
                    else {}
                ),
            }
        return entry

    def text(
        self,
        x: Scalar | str | datetime,
        y: Scalar | str | datetime,
        s: str,
        fontdict: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Text:
        """Place text at data coordinates ``(x, y)``.

        ``ha``/``va`` (aliases ``horizontalalignment``/``verticalalignment``)
        anchor the text; ``color``/``c``, ``fontsize``/``size``,
        ``fontweight``/``weight``, ``fontfamily``/``family``, and
        ``rotation`` style it, with ``fontdict`` supplying defaults. Pass
        ``transform=ax.transAxes`` (or the figure's ``transFigure``) for
        fraction placement. Basic mathtext (``$...$``) is rendered;
        unsupported keywords raise loudly.
        """
        if fontdict:
            kwargs = {**fontdict, **kwargs}
        color = kwargs.pop("color", kwargs.pop("c", None))
        fontsize = kwargs.pop("fontsize", kwargs.pop("size", None))
        ha = kwargs.pop("ha", kwargs.pop("horizontalalignment", None))
        va = kwargs.pop("va", kwargs.pop("verticalalignment", None))
        transform = kwargs.pop("transform", None)
        fontweight = kwargs.pop("fontweight", kwargs.pop("weight", None))
        fontfamily = kwargs.pop("fontfamily", kwargs.pop("family", None))
        fontstyle = kwargs.pop("fontstyle", kwargs.pop("style", None))
        rotation = kwargs.pop("rotation", None)
        bbox = kwargs.pop("bbox", None)
        check_unsupported(kwargs, "text()")
        # Matplotlib snapshots the active text default when the Text artist is
        # created.  Preserve that value on the entry so a later style-context
        # change cannot recolor an already-authored label at render time.
        akw = {"color": resolve_color(rcParams["text.color"] if color is None else color)}
        if bbox is not None:
            if not isinstance(bbox, Mapping):
                raise TypeError("text() bbox must be a mapping or None")
            akw["bbox"] = dict(bbox)
        if ha is not None:
            akw["anchor"] = {"left": "start", "center": "middle", "right": "end"}.get(
                str(ha), "start"
            )
        style: dict[str, Any] = {}
        if fontsize is not None:
            style["font_size"] = _font_size_points(fontsize, rcParams["font.size"])
        if va is not None:
            style["vertical_align"] = str(va)
        if fontweight is not None:
            style["font_weight"] = str(fontweight)
        if fontfamily is not None:
            style["font_family"] = str(fontfamily)
        if fontstyle is not None:
            fontstyle = str(fontstyle)
            if fontstyle not in {"normal", "italic", "oblique"}:
                raise ValueError("text() style must be 'normal', 'italic', or 'oblique'")
            style["font_style"] = fontstyle
        if rotation is not None:
            style["rotation"] = 90.0 if rotation == "vertical" else float(rotation)
        if transform is self.transAxes or transform == "axes fraction":
            style["coordinate_space"] = "axes_fraction"
        elif transform in {getattr(self.figure, "transFigure", None), "figure fraction"}:
            style["coordinate_space"] = "figure_fraction"
        if style:
            akw["style"] = style
        plain_text, math_italic_ranges = _plain_text_with_math_italic_ranges(s)
        if math_italic_ranges:
            akw["style"] = {
                **(akw.get("style") or {}),
                "math_italic_ranges": ",".join(
                    f"{start}:{end}" for start, end in math_italic_ranges
                ),
            }
        return Text(self, self._add("@text", {"args": (x, y, plain_text), "kwargs": akw}))

    def annotate(self, text: str, xy: tuple, xytext: Optional[tuple] = None, **kwargs: Any) -> Text:
        """Annotate the point ``xy`` with text, optionally offset at ``xytext``.

        ``xycoords``/``textcoords`` choose the coordinate systems
        (``"data"``, ``"axes fraction"``, ``"offset points"``, ...);
        ``arrowprops`` draws a matplotlib-style arrow between the text and
        the point. `text` styling keywords (``color``, ``fontsize``/``size``,
        ``ha``/``va``, ``fontweight``/``weight``, ``fontfamily``/``family``,
        ``rotation``, ``bbox``) are accepted; anything else raises loudly.
        """
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
        zorder = kwargs.pop("zorder", None)
        check_unsupported(kwargs, "annotate()")
        # Match Text creation semantics: the active rc default belongs to the
        # annotation even if materialization happens after a style context
        # exits.
        akw: dict[str, Any] = {
            "color": resolve_color(rcParams["text.color"] if color is None else color)
        }
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
            style["font_size"] = _font_size_points(fontsize, rcParams["font.size"])
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
        annotation_entries: list[dict[str, Any]] = []
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
            font_px = (
                _font_size_points(
                    fontsize if fontsize is not None else rcParams["font.size"],
                    rcParams["font.size"],
                )
                * self._point_scale()
            )
            arrow_color, arrow_width, arrow_style = _arrow_visuals(
                arrowprops, mutation_scale=font_px
            )
            # matplotlib draws the arrow from the text patch center, clipped
            # at the patch edge (+2pt shrink); start_offset + label_clear are
            # that attach model in the shared geometry.
            attach = _label_attach_styles(
                _plain_text(text),
                font_px,
                akw.get("anchor", "start"),
                style.get("vertical_align"),
                bbox=bbox is not None,
            )
            if attach is not None and not shrink:
                arrow_style = {**arrow_style, **attach}
            annotation_entries.append(
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
            )
        text_entry = self._add(
            "@text", {"args": (text_xy[0], text_xy[1], _plain_text(text)), "kwargs": akw}
        )
        annotation_entries.append(text_entry)
        if zorder is not None:
            for entry in annotation_entries:
                entry["_zorder"] = float(zorder)
            host = self._y2_of or self
            host._entries.sort(key=lambda entry: float(entry.get("_zorder", 0.0)))
        return Text(self, text_entry)

    # -- axis config -----------------------------------------------------------

    def set_xlabel(self, label: str, **kwargs: Any) -> None:
        """Set the x-axis label.

        ``labelpad`` offsets it and ``loc`` (``"left"``/``"center"``/
        ``"right"``) places it; the matplotlib text keywords (``fontsize``,
        ``color``, ...) are accepted as compatibility inputs, and anything
        else raises loudly. Basic mathtext (``$...$``) is rendered.
        """
        props = self._axis_props("x")
        props["label"] = _plain_text(label)
        _apply_axis_label_kwargs(props, kwargs, "set_xlabel()", point_scale=self._point_scale())
        self._invalidate()

    def set_ylabel(self, label: str, **kwargs: Any) -> None:
        """Set the y-axis label (same keywords as `set_xlabel`).

        ``loc`` takes ``"bottom"``/``"center"``/``"top"`` for this axis.
        """
        props = self._axis_props("y")
        props["label"] = _plain_text(label)
        _apply_axis_label_kwargs(props, kwargs, "set_ylabel()", point_scale=self._point_scale())
        self._invalidate()

    def set_title(self, title: str, **kwargs: Any) -> None:
        """Set the axes title.

        The matplotlib text keywords (``fontsize``, ``color``, ``pad``, ...)
        are accepted as compatibility inputs; anything else raises loudly.
        Basic mathtext (``$...$``) is rendered.
        """
        host = self._y2_of or self
        loc = str(kwargs.pop("loc", rcParams["axes.titlelocation"])).lower()
        if loc not in {"left", "center", "right"}:
            raise ValueError("set_title() loc must be 'left', 'center', or 'right'")
        authored_y = kwargs.pop("y", None)
        rc_y = rcParams["axes.titley"]
        automatic_y = authored_y is None and rc_y is None
        y = 1.0 if automatic_y else float(rc_y if authored_y is None else authored_y)
        if not np.isfinite(y):
            raise ValueError("set_title() y must be finite")
        pad = float(kwargs.pop("pad", rcParams["axes.titlepad"]))
        if not np.isfinite(pad):
            raise ValueError("set_title() pad must be finite")
        style = _title_css_style(
            _pop_text_style_kwargs(kwargs, "set_title()"),
            point_scale=self._point_scale(),
        )
        text = _plain_text(title)
        if text:
            host._titles[loc] = {
                "text": text,
                "loc": loc,
                "y": y,
                "pad": pad * self._point_scale(),
                "automatic_y": automatic_y,
                "style": style,
            }
        else:
            host._titles.pop(loc, None)
        # Keep the historical center aliases for get_title() and downstream
        # code that inspects the ordinary single-title state.
        if loc == "center":
            host._title = text or None
            host._title_style = style
        host._invalidate()

    def set(self, **kwargs: Any) -> "Axes":
        """Set multiple axes properties at once, matplotlib-style.

        Supported property names: ``xlabel``, ``ylabel``, ``title``,
        ``xlim``, ``ylim``, ``xscale``, ``yscale``, ``xticks``, ``yticks``,
        ``xticklabels``, ``yticklabels``, ``position``, ``anchor``,
        ``aspect``, ``adjustable``, ``facecolor``, and ``axisbelow``
        (``projection`` must stay rectilinear). Unknown names raise loudly.
        Returns the axes for chaining.
        """
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
            "adjustable": self.set_adjustable,
            "facecolor": self.set_facecolor,
            "axisbelow": self.set_axisbelow,
        }
        xticklabels = kwargs.pop("xticklabels", None)
        yticklabels = kwargs.pop("yticklabels", None)
        projection = kwargs.pop("projection", None)
        if projection is not None:
            # Pre-polar this raised NotImplementedError for every non-default
            # value, which left `plt.subplot(111, projection="polar")` on an
            # already-claimed slot rejecting a now-supported idiom.
            # _set_projection accepts 'polar'/'rectilinear' and stays loud
            # (ValueError) for anything else.
            self._set_projection(projection)
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

    def set_xlim(self, left: float | LimitsLike | None = None, right: float | None = None) -> None:
        """Set the x view limits.

        Call as ``set_xlim(left, right)`` or ``set_xlim((left, right))``;
        either side may be None to keep the current value. A descending pair
        inverts the axis. Values are in data space — nonlinear scales
        transform them internally.
        """
        if isinstance(left, (tuple, list)):
            left, right = left
        host = (self._y2_of or self)._shared_ticker_source("x")
        spec = host._scale_specs["x"]
        current_start, current_end = self.get_xlim()
        if spec["name"] == "log":
            auto_start, auto_end = self._auto_domain("x")
            if host._axis["x"].get("reverse"):
                auto_start, auto_end = auto_end, auto_start
            if not np.isfinite(current_start) or current_start <= 0:
                current_start = auto_start
            if not np.isfinite(current_end) or current_end <= 0:
                current_end = auto_end
        start = float(current_start if left is None else left)
        end = float(current_end if right is None else right)
        if not np.isfinite((start, end)).all():
            raise ValueError("Axis limits cannot be NaN or Inf")
        if spec["name"] == "log":
            if start <= 0:
                warnings.warn(
                    "Attempt to set non-positive xlim on a log-scaled axis will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
                start = current_start
            if end <= 0:
                warnings.warn(
                    "Attempt to set non-positive xlim on a log-scaled axis will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
                end = current_end
        transformed = _scale_values(np.asarray((start, end)), spec)
        host._axis["x"]["domain"] = tuple(sorted(map(float, transformed)))
        host._axis["x"]["reverse"] = start > end
        host._explicit_domains.add("x")
        host._tick_expanded_domains.discard("x")
        host._invalidate_shared_ticker_axis("x")

    def get_xlim(self) -> tuple[float, float]:
        """The current x view limits, in data space and display order."""
        host = (self._y2_of or self)._shared_ticker_source("x")
        if self._projection == "polar" and not self._has_explicit_shared_domain("x"):
            # Polar theta defaults to one complete turn, independently of the
            # data's angular extent. This is also the single source read by the
            # theta-limit setters/getters below; automatic Cartesian x padding
            # must never become an authored sector.
            return (0.0, 2.0 * math.pi)
        lo, hi = host._axis["x"].get("domain", self._auto_domain("x"))
        lo, hi = map(
            float,
            _scale_values(np.asarray((lo, hi)), host._scale_specs["x"], inverse=True),
        )
        return (hi, lo) if host._axis["x"].get("reverse") else (lo, hi)

    def set_ylim(self, bottom: float | LimitsLike | None = None, top: float | None = None) -> None:
        """Set the y view limits (forms as in `set_xlim`).

        A descending ``(bottom, top)`` pair inverts the axis; on a twin axes
        the limits apply to its own right-hand y-axis.
        """
        if isinstance(bottom, (tuple, list)):
            bottom, top = bottom
        base = self._y2_of or self
        key = "y2" if self._y2_of is not None else "y"
        host = base._shared_ticker_source(key)
        spec = host._scale_specs[key]
        current_start, current_end = self.get_ylim()
        if spec["name"] == "log":
            auto_start, auto_end = self._auto_domain("y")
            if host._axis[key].get("reverse"):
                auto_start, auto_end = auto_end, auto_start
            if not np.isfinite(current_start) or current_start <= 0:
                current_start = auto_start
            if not np.isfinite(current_end) or current_end <= 0:
                current_end = auto_end
        start = float(current_start if bottom is None else bottom)
        end = float(current_end if top is None else top)
        if not np.isfinite((start, end)).all():
            raise ValueError("Axis limits cannot be NaN or Inf")
        if spec["name"] == "log":
            if start <= 0:
                warnings.warn(
                    "Attempt to set non-positive ylim on a log-scaled axis will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
                start = current_start
            if end <= 0:
                warnings.warn(
                    "Attempt to set non-positive ylim on a log-scaled axis will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
                end = current_end
        transformed = _scale_values(np.asarray((start, end)), spec)
        host._axis[key]["domain"] = tuple(sorted(map(float, transformed)))
        host._axis[key]["reverse"] = start > end
        host._explicit_domains.add(key)
        host._tick_expanded_domains.discard(key)
        host._invalidate_shared_ticker_axis(key)

    def get_ylim(self) -> tuple[float, float]:
        """The current y view limits, in data space and display order."""
        base = self._y2_of or self
        key = "y2" if self._y2_of is not None else "y"
        host = base._shared_ticker_source(key)
        lo, hi = host._axis[key].get("domain", self._auto_domain("y"))
        lo, hi = map(
            float,
            _scale_values(np.asarray((lo, hi)), host._scale_specs[key], inverse=True),
        )
        return (hi, lo) if host._axis[key].get("reverse") else (lo, hi)

    def _aspect_coordinates(
        self,
        axis: str,
        bounds: tuple[float, float],
        *,
        inverse: bool = False,
    ) -> tuple[float, float]:
        """Convert stored domains to/from the coordinates aspect uses.

        Non-native scales are already baked into affine entry/domain
        coordinates. Native log axes retain data values for the core renderer,
        so aspect math must explicitly enter and leave log space.
        """
        host = self._y2_of or self
        key = "y2" if axis == "y" and self._y2_of is not None else axis
        spec = host._scale_specs[key]
        values = np.asarray(bounds, dtype=np.float64)
        if spec["name"] != "log":
            return float(values[0]), float(values[1])
        base = float(spec.get("base", 10.0))
        if inverse:
            transformed = np.power(base, values)
        else:
            with np.errstate(divide="ignore", invalid="ignore"):
                transformed = np.log(values) / np.log(base)
        if not np.isfinite(transformed).all():
            # A scale mutation can leave the aspect snapshot in the previous
            # scale's coordinates. Re-resolve from the current positive data
            # instead of making get_position()/export fail on stale bounds.
            fallback = np.asarray(self._auto_domain(axis), dtype=np.float64)
            with np.errstate(divide="ignore", invalid="ignore"):
                transformed = np.log(fallback) / np.log(base)
            if not np.isfinite(transformed).all():
                raise ValueError("log aspect limits must be positive and finite")
        return float(transformed[0]), float(transformed[1])

    def get_position(self, original: bool = False) -> Bbox:
        """The axes rectangle in figure fractions, as a `Bbox`.

        Grid-aware: a subplot without an explicit rect reports its gridspec
        cell under the figure's SubplotParams, so the panels of an ``n x m``
        grid report ``n * m`` distinct boxes exactly as matplotlib does.
        ``original=False`` applies adjustable-box aspect geometry, while
        ``original=True`` returns the allocated subplot rectangle.
        """
        if self.figure is not None:
            # A factory-authored tight/constrained layout first records an
            # empty-axes rectangle, then becomes dirty as artists and
            # colorbars arrive. Always enter the Figure resolver before
            # trusting that cached rectangle so get_position() observes the
            # same final-content solve as every exporter.
            rect = self.figure._axes_rect(self)
            if rect is None:
                rect = self._figure_rect or _DEFAULT_AXES_RECT
        elif self._figure_rect is not None:
            rect = self._figure_rect
        else:
            rect = _DEFAULT_AXES_RECT
        if original or not (
            self._aspect_equal
            and self._aspect_adjustable == "box"
            and self._aspect_bounds is not None
            and self.figure is not None
        ):
            return Bbox.from_bounds(*rect)

        x0, x1, y0, y1 = self._aspect_bounds
        x0, x1 = self._axis["x"].get("domain", (x0, x1))
        y0, y1 = self._axis["y"].get("domain", (y0, y1))
        tx0, tx1 = self._aspect_coordinates("x", (x0, x1))
        ty0, ty1 = self._aspect_coordinates("y", (y0, y1))
        data_ratio = abs(tx1 - tx0) / max(
            abs(ty1 - ty0) * self._aspect_value,
            np.finfo(float).eps,
        )
        fig_width, fig_height = self.figure.get_size_inches()
        left, bottom, width, height = rect
        physical_ratio = width * fig_width / max(height * fig_height, np.finfo(float).eps)
        if physical_ratio > data_ratio:
            active_width = height * fig_height * data_ratio / fig_width
            active_height = height
        else:
            active_width = width
            active_height = width * fig_width / (data_ratio * fig_height)
        anchor_x, anchor_y = self._aspect_anchor()
        return Bbox.from_bounds(
            left + (width - active_width) * anchor_x,
            bottom + (height - active_height) * anchor_y,
            active_width,
            active_height,
        )

    def set_position(self, position: Bbox | tuple[float, float, float, float]) -> None:
        """Place the axes at a figure-fraction rectangle.

        ``position`` is ``[left, bottom, width, height]`` (a Bbox-like with
        ``.bounds`` is also accepted); a later ``subplots_adjust`` still
        re-resolves gridspec-backed axes over this.
        """
        # The gridspec spec (if any) is kept: matplotlib's subplots_adjust
        # re-resolves every subplotspec-backed axes, overriding set_position.
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

    def _iter_entry_arrays(self, axis: str) -> Iterator[tuple[np.ndarray, bool]]:
        """Yield each (array, needs_finite_filter) an entry contributes to *axis*."""
        from xy.channels import category_label

        host = self._y2_of or self
        y_axis = "y2" if self._y2_of is not None else "y"
        category_positions: dict[str, float] = {}

        def numeric_or_categorical(values: Any) -> np.ndarray:
            """Mirror the core's first-seen categorical coordinate mapping.

            Pyplot materializes its own auto view before the core Figure is
            built.  String coordinates therefore cannot simply be skipped:
            doing so pins categorical line/scatter axes to the dataless
            ``(0, 1)`` view and clips every category after the second.
            """
            array = np.asarray(values).reshape(-1)
            try:
                return np.asarray(unit_converted_values(array), dtype=np.float64).reshape(-1)
            except (TypeError, ValueError):
                if array.dtype.kind not in {"U", "S", "O", "b"}:
                    raise
            labels = (
                array.tolist()
                if array.dtype.kind == "U"
                else [category_label(value) for value in array.astype(object)]
            )
            positions = np.empty(len(labels), dtype=np.float64)
            for index, label in enumerate(labels):
                text = str(label)
                positions[index] = category_positions.setdefault(
                    text, float(len(category_positions))
                )
            return positions

        for entry in host._entries:
            if axis == "y" and entry.get("y_axis", "y") != y_axis:
                continue
            if entry.get("_quiver_key_recipe") is not None:
                # QuiverKey is an Artist offset in axes/figure/data display
                # coordinates; Matplotlib never lets it change dataLim.
                continue
            quiver_recipe = entry.get("_quiver_recipe")
            if quiver_recipe is not None:
                # Quiver.get_datalim contributes only its offset locations,
                # not the display-sized arrow polygons. Keep that invariant
                # after materialization expands the entry into shaft/head
                # segments outside the data-position extent.
                key = "x" if axis == "x" else "y"
                scale_key = "y2" if axis == "y" and self._y2_of is not None else axis
                values = _scale_values(quiver_recipe[key], host._scale_specs[scale_key])
                yield np.asarray(values, dtype=np.float64).reshape(-1), True
                continue
            if entry.get("kind") == "@axline":
                # Matplotlib includes only untransformed defining points in
                # data limits (one anchor for slope form, both for two-point
                # form). Axes-fraction anchors never affect autoscale.
                if entry.get("transform_space") is None:
                    index = 0 if axis == "x" else 1
                    points = [entry["xy1"]]
                    if entry.get("xy2") is not None:
                        points.append(entry["xy2"])
                    yield np.asarray([point[index] for point in points], dtype=np.float64), True
                continue
            if entry.get("kind") == "bar":
                kwargs = entry.get("kwargs", {})
                orientation = kwargs.get("orientation", "vertical")
                centers = np.asarray(entry.get("x", ())).reshape(-1)
                centers = numeric_or_categorical(centers)
                values = np.asarray(entry.get("y", ()), dtype=np.float64).reshape(-1)
                bases = np.asarray(kwargs.get("base", 0.0), dtype=np.float64)
                bases = np.broadcast_to(bases, values.shape).reshape(-1)
                thickness = np.asarray(kwargs.get("width", 0.8), dtype=np.float64)
                thickness = np.broadcast_to(thickness, centers.shape).reshape(-1)
                if (orientation == "vertical" and axis == "x") or (
                    orientation == "horizontal" and axis == "y"
                ):
                    yield centers - thickness * 0.5, True
                    yield centers + thickness * 0.5, True
                else:
                    yield bases, True
                    yield bases + values, True
                continue
            key = "x" if axis == "x" else "y"
            if key in entry:
                try:
                    array = numeric_or_categorical(entry[key])
                except (TypeError, ValueError):
                    continue
                yield array, True
            if entry.get("kind") == "area" and axis == "y":
                base = entry.get("kwargs", {}).get("base")
                if base is not None:
                    yield np.asarray(base, dtype=np.float64).reshape(-1), True
            mpl_extent = entry.get("_mpl_extent", {}).get(axis)
            if mpl_extent is not None:
                yield np.asarray(mpl_extent, dtype=np.float64).reshape(-1), True
            if entry.get("kind") == "@mark":
                factory = entry.get("factory")
                indexes = {
                    "segments": (0, 2) if axis == "x" else (1, 3),
                    "triangle_mesh": (0, 2, 4) if axis == "x" else (1, 3, 5),
                    "stem": (0,) if axis == "x" else (1,),
                    "area": (0,) if axis == "x" else (1,),
                    # xy.stairs(values, edges) is compact and deliberately
                    # reverses the ordinary x/y argument order.
                    "stairs": (1,) if axis == "x" else (0,),
                    "step": (0,) if axis == "x" else (1,),
                }.get(factory, ())
                for index in indexes:
                    yield np.asarray(entry["args"][index], dtype=np.float64).reshape(-1), True
                if factory == "area" and axis == "y":
                    base = entry.get("kwargs", {}).get("base")
                    if base is not None:
                        yield np.asarray(base, dtype=np.float64).reshape(-1), True
                if factory == "stem" and axis == "y":
                    yield np.asarray(entry.get("kwargs", {}).get("base", 0.0)).reshape(-1), True
                if factory == "errorbar":
                    center = np.asarray(
                        entry["args"][0 if axis == "x" else 1], dtype=np.float64
                    ).reshape(-1)
                    yield center, True
                    error = entry.get("kwargs", {}).get("xerr" if axis == "x" else "yerr")
                    if error is not None:
                        raw = np.asarray(error, dtype=np.float64)
                        if raw.ndim >= 2 and raw.shape[0] == 2:
                            lower = np.broadcast_to(raw[0], center.shape)
                            upper = np.broadcast_to(raw[1], center.shape)
                        else:
                            lower = upper = np.broadcast_to(raw, center.shape)
                        yield center - lower, True
                        yield center + upper, True
                if factory == "contour":
                    z = np.asarray(entry["args"][0])
                    coordinates = entry.get("kwargs", {}).get(key)
                    if coordinates is None and z.ndim >= 2:
                        coordinates = np.arange(z.shape[1 if axis == "x" else 0], dtype=float)
                    if coordinates is not None:
                        yield np.asarray(coordinates, dtype=np.float64).reshape(-1), True
                elif factory == "heatmap":
                    # NB: distinct from the `kind == "heatmap"` branch below,
                    # which is imshow's explicit-extent entry shape.
                    span = _heatmap_span(entry, key)
                    if span is not None:
                        yield span, False
                elif factory == "ecdf":
                    if axis == "x":
                        yield np.asarray(entry["args"][0], dtype=np.float64).reshape(-1), True
                    else:
                        # marks.ecdf steps from 0 to cumulative mass 1.
                        yield np.asarray([0.0, 1.0], dtype=np.float64), False
                elif factory == "box":
                    for span in _box_spans(entry, axis):
                        yield span, True
            elif entry.get("kind") == "heatmap" and entry.get("extent") is not None:
                bounds = entry["extent"]
                yield np.asarray(bounds[:2] if axis == "x" else bounds[2:], dtype=float), False

    def _entry_values(self, axis: str) -> np.ndarray:
        """Every finite data coordinate the entries contribute to *axis* autoscale."""
        values = [
            array[np.isfinite(array)] if needs_filter else array
            for array, needs_filter in self._iter_entry_arrays(axis)
        ]
        return np.concatenate(values) if values else np.array([], dtype=np.float64)

    def _axis_is_dataless(self, axis: str) -> bool:
        """True when the entries contribute no coordinate to *axis* autoscale.

        The empty-view pin in `_build_chart` asks this on every default build,
        so it must not pay `_entry_values`'s full O(n) materialization when the
        chart obviously has data (tests/pyplot/test_perf_guardrail.py). A short
        prefix probe answers real data immediately; only all-non-finite
        prefixes fall through to a full scan.
        """
        host = self._y2_of or self
        y_axis = "y2" if self._y2_of is not None else "y"
        # Bars are a frequent build-path boundary case: `_iter_entry_arrays`
        # expands their centers, widths, bases, and endpoints before its first
        # yield. Dataless detection only needs one real coordinate, so answer
        # the ordinary bar case from the compact entry and leave pathological
        # all-non-finite inputs to the exact fallback below.
        for entry in host._entries:
            if axis == "y" and entry.get("y_axis", "y") != y_axis:
                continue
            if entry.get("kind") != "bar":
                continue
            kwargs = entry.get("kwargs", {})
            orientation = kwargs.get("orientation", "vertical")
            category_axis = "x" if orientation == "vertical" else "y"
            if axis == category_axis:
                centers = np.asarray(entry.get("x", ())).reshape(-1)
                if not centers.size:
                    continue
                if centers.dtype.kind in {"U", "S", "O", "b"}:
                    return False
                try:
                    numeric = np.asarray(unit_converted_values(centers), dtype=np.float64).reshape(
                        -1
                    )
                except (TypeError, ValueError):
                    return False
                if np.isfinite(numeric).any():
                    return False
                continue
            values = np.asarray(entry.get("y", ())).reshape(-1)
            if not values.size:
                continue
            base = np.asarray(kwargs.get("base", 0.0), dtype=np.float64)
            if base.ndim == 0:
                if np.isfinite(base).item():
                    return False
                continue
            try:
                bases = np.broadcast_to(base, values.shape).reshape(-1)
                numeric_values = np.asarray(values, dtype=np.float64)
            except (TypeError, ValueError):
                continue
            if np.isfinite(bases).any() or np.isfinite(bases + numeric_values).any():
                return False
        for array, needs_filter in self._iter_entry_arrays(axis):
            if not needs_filter:
                if array.size:
                    return False
            elif np.isfinite(array[:1024]).any() or np.isfinite(array[1024:]).any():
                return False
        return True

    def _entry_extent(self, axis: str) -> tuple[float, float]:
        finite = self._entry_values(axis)
        if len(finite) == 0:
            return (0.0, 1.0)
        lo, hi = float(np.min(finite)), float(np.max(finite))
        return (lo, hi if hi > lo else lo + 1.0)

    def _entry_sticky_edges(self, axis: str) -> np.ndarray:
        """Matplotlib-style sticky bar baselines on the value axis."""
        edges: list[np.ndarray] = []
        host = self._y2_of or self
        y_axis = "y2" if self._y2_of is not None else "y"
        for entry in host._entries:
            if axis == "y" and entry.get("y_axis", "y") != y_axis:
                continue
            mpl_sticky = entry.get("_mpl_sticky_edges", {}).get(axis)
            if mpl_sticky is not None:
                edges.append(np.asarray(mpl_sticky, dtype=np.float64).reshape(-1))
            if entry.get("kind") == "bar":
                kwargs = entry.get("kwargs", {})
                orientation = kwargs.get("orientation", "vertical")
                value_axis = "y" if orientation == "vertical" else "x"
                if axis != value_axis:
                    continue
                values = np.asarray(entry.get("y", ()), dtype=np.float64).reshape(-1)
                bases = np.asarray(kwargs.get("base", 0.0), dtype=np.float64)
                edges.append(np.broadcast_to(bases, values.shape).reshape(-1))
            elif entry.get("kind") == "@mark" and entry.get("factory") == "contour":
                z = np.asarray(entry["args"][0])
                coordinates = entry.get("kwargs", {}).get(axis)
                if coordinates is None and z.ndim >= 2:
                    coordinates = np.arange(z.shape[1 if axis == "x" else 0], dtype=float)
                if coordinates is not None:
                    values = np.asarray(coordinates, dtype=np.float64).reshape(-1)
                    finite = values[np.isfinite(values)]
                    if finite.size:
                        edges.append(np.asarray([finite.min(), finite.max()]))
            elif entry.get("kind") == "@mark" and entry.get("factory") == "heatmap":
                # Matplotlib gives pcolormesh/hist2d/specgram sticky edges: the
                # view hugs the outer cell edge with no margin at all.
                span = _heatmap_span(entry, axis)
                if span is not None:
                    edges.append(span)
            elif entry.get("kind") == "@mark" and entry.get("factory") == "ecdf":
                if axis == "y":
                    # An ECDF is sticky at both 0 and full cumulative mass.
                    edges.append(np.asarray([0.0, 1.0], dtype=np.float64))
            elif entry.get("kind") == "@mark" and entry.get("factory") == "box":
                kwargs = entry.get("kwargs", {})
                orientation = kwargs.get("orientation", "vertical")
                category_axis = "x" if orientation == "vertical" else "y"
                if axis == category_axis:
                    box_edges = [values[np.isfinite(values)] for values in _box_spans(entry, axis)]
                    finite_box_edges = [values for values in box_edges if values.size]
                    if finite_box_edges:
                        combined = np.concatenate(finite_box_edges)
                        edges.append(np.asarray([combined.min(), combined.max()]))
            elif entry.get("kind") == "heatmap" and entry.get("extent") is not None:
                # imshow's explicit extent is likewise sticky on both axes.
                bounds = entry["extent"]
                edges.append(np.asarray(bounds[:2] if axis == "x" else bounds[2:], dtype=float))
        if not edges:
            return np.array([], dtype=np.float64)
        combined = np.concatenate(edges)
        return combined[np.isfinite(combined)]

    def _has_nonzero_bar_baseline(self, axis: str) -> bool:
        """Whether the core's zero-only bar anchor cannot represent a base."""
        host = self._y2_of or self
        y_axis = "y2" if self._y2_of is not None else "y"
        for entry in host._entries:
            if axis == "y" and entry.get("y_axis", "y") != y_axis:
                continue
            if entry.get("kind") != "bar":
                continue
            orientation = entry.get("kwargs", {}).get("orientation", "vertical")
            value_axis = "y" if orientation == "vertical" else "x"
            if axis != value_axis:
                continue
            base = np.asarray(entry.get("kwargs", {}).get("base", 0.0), dtype=np.float64)
            finite = base[np.isfinite(base)]
            if finite.size and np.any(np.abs(finite) > np.finfo(np.float64).eps):
                return True
        return False

    def _has_fully_sticky_candidate(self, axis: str) -> bool:
        """Whether an entry can pin both ends of *axis*.

        Ordinary bar baselines are deliberately absent: they are one-sided,
        and the core already anchors them.  Keeping this probe structural and
        allocation-free avoids rescanning every bar coordinate during each
        default chart build merely to rediscover that fact.
        """
        host = self._y2_of or self
        y_axis = "y2" if self._y2_of is not None else "y"
        for entry in host._entries:
            if axis == "y" and entry.get("y_axis", "y") != y_axis:
                continue
            if entry.get("_mpl_sticky_edges", {}).get(axis) is not None:
                return True
            if entry.get("kind") == "heatmap" and entry.get("extent") is not None:
                return True
            if entry.get("kind") != "@mark":
                continue
            factory = entry.get("factory")
            if factory in {"contour", "heatmap"}:
                return True
            if factory == "ecdf" and axis == "y":
                return True
            if factory == "box":
                orientation = entry.get("kwargs", {}).get("orientation", "vertical")
                category_axis = "x" if orientation == "vertical" else "y"
                if axis == category_axis:
                    return True
        return False

    def _fully_sticky_domain(
        self,
        axis: str,
        *,
        dataless: Optional[bool] = None,
    ) -> Optional[tuple[float, float]]:
        """The raw extent when sticky edges pin *both* ends of *axis*.

        Image- and mesh-like marks (imshow/pcolormesh/hist2d/specgram) hug
        their outer cell edge in Matplotlib, and an ECDF hugs 0 and 1.  The
        core only knows the rectangle zero-baseline anchor, so it would pad
        such an axis by the ordinary margin.  `_build_chart` materializes this
        domain instead of a margin so the renderer cannot widen the view.

        Deliberately requires *both* ends: a one-sided sticky edge is the bar
        and histogram baseline, which the core already anchors itself.
        """
        if not self._has_fully_sticky_candidate(axis):
            return None
        sticky = self._entry_sticky_edges(axis)
        if not sticky.size:
            return None
        if dataless is True or (dataless is None and self._axis_is_dataless(axis)):
            return None
        lo, hi = self._entry_extent(axis)
        tolerance = np.finfo(np.float64).eps * max(1.0, abs(lo), abs(hi)) * 8
        pinned_lo = np.any(np.isclose(sticky, lo, rtol=0.0, atol=tolerance))
        pinned_hi = np.any(np.isclose(sticky, hi, rtol=0.0, atol=tolerance))
        return (lo, hi) if pinned_lo and pinned_hi else None

    def _auto_domain(self, axis: str) -> tuple[float, float]:
        host = self._y2_of or self
        key = "y2" if axis == "y" and self._y2_of is not None else axis
        spec = host._scale_specs[key]
        if self._axis_is_dataless(axis):
            return (1.0, 10.0) if spec["name"] == "log" else (0.0, 1.0)
        if axis == "y" and self._projection == "polar" and spec["name"] != "log":
            # The radial preview must match the engine's polar autorange
            # (centre origin, no outer pad — _figure._range), or every
            # rlim call snapshots cartesian-padded values: set_rmax(2.0)
            # froze [0.85, 2.0] where matplotlib gives [0, 2].
            lo, hi = self._entry_extent(axis)
            lo = min(0.0, float(lo))
            hi = float(hi) if hi > lo else lo + 1.0
            return lo, hi
        if spec["name"] == "log":
            # The core consumes log domains in the original positive data
            # space, while Matplotlib applies margins after transforming to
            # log space.  Do that transform locally rather than feeding a
            # linearly padded (and possibly negative) domain to the core.
            values = self._entry_values(axis)
            positive = values[values > 0.0]
            if positive.size == 0:
                return (1.0, 10.0)
            lo, hi = float(positive.min()), float(positive.max())
            transformed_lo, transformed_hi = np.log10((lo, hi))
        else:
            lo, hi = self._entry_extent(axis)
            transformed_lo, transformed_hi = lo, hi
        margin = self._effective_margin(axis)
        if margin == 0.0:
            return lo, hi
        span = transformed_hi - transformed_lo
        pad = span * margin if span > 0 else abs(transformed_lo) * margin or margin
        lower, upper = transformed_lo - pad, transformed_hi + pad
        if spec["name"] == "log":
            lower, upper = 10.0**lower, 10.0**upper
        sticky = self._entry_sticky_edges(axis)
        tolerance = np.finfo(np.float64).eps * max(1.0, abs(lo), abs(hi)) * 8
        if sticky.size:
            if np.any(np.isclose(sticky, lo, rtol=0.0, atol=tolerance)):
                lower = lo
            if np.any(np.isclose(sticky, hi, rtol=0.0, atol=tolerance)):
                upper = hi
        return lower, upper

    def axis(
        self, arg: str | bool | tuple[float, float, float, float] | None = None, **kwargs: Any
    ) -> tuple[float, float, float, float]:
        """Get or set axis properties in one call.

        ``axis()`` returns ``(xmin, xmax, ymin, ymax)``; ``axis((xmin, xmax,
        ymin, ymax))`` sets the limits; ``axis("off"/"on"/"equal"/"scaled"/
        "image"/"square"/"tight"/"auto")`` applies the matplotlib convenience
        modes (a bool means on/off). ``xmin``/``xmax``/``ymin``/``ymax``
        keywords adjust single limits and ``emit`` is a compat-noop;
        anything else raises loudly. Always returns the resulting limits.
        """
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
            self.set_axis_on()
        elif arg in {"auto", "equal", "scaled", "image", "square"}:
            # All five Matplotlib modes begin with autoscale_view(tight=False),
            # whose limits include the configured x/y margins.
            self._tight = False
            self._aspect_equal = False
            self._aspect_value = 1.0
            self._aspect_adjustable = "box"
            self._aspect_bounds = None
            # Calling an aspect/autoscale mode on an empty Axes must not turn
            # the placeholder (0, 1) view into explicit limits. Matplotlib
            # continues autoscaling when artists are added afterwards.
            if self._entries:
                self._set_tight_domains(tight=False)
            if arg in {"equal", "scaled", "image", "square"}:
                if self._entries:
                    self._set_aspect_equal_from_current()
                else:
                    self._aspect_equal = True
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
            if arg == "image":
                # image follows the shared tight=False transition with its
                # own autoscale_view(tight=True).
                self._tight = True
        elif arg == "tight":
            self._aspect_equal = False
            self._aspect_value = 1.0
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

    def get_adjustable(self) -> str:
        """Return whether aspect changes the axes box or its data limits."""
        return self._aspect_adjustable

    def set_adjustable(self, adjustable: str, share: bool = False) -> None:
        """Select ``"box"`` or ``"datalim"`` aspect adjustment."""
        if share:
            raise not_implemented(
                "Axes.set_adjustable(share=True)",
                "calling set_adjustable() on each shared Axes with share=False",
            )
        if adjustable not in {"box", "datalim"}:
            raise ValueError("adjustable must be 'box' or 'datalim'")
        self._aspect_adjustable = adjustable
        self._invalidate()

    def set_aspect(
        self,
        aspect: str | float,
        adjustable: Optional[str] = None,
        anchor: Any = None,
        share: bool = False,
        **kwargs: Any,
    ) -> None:
        """Set the data aspect ratio: ``"equal"``, ``"auto"``, or a positive float.

        ``adjustable`` is ``"box"`` (resize the axes rectangle) or
        ``"datalim"`` (expand a data limit at draw time); ``anchor`` controls
        where a box adjustment lands. ``share=True`` is not yet supported and
        fails loudly before mutating any axes. Anything else raises loudly.
        """
        if share:
            raise not_implemented(
                "Axes.set_aspect(share=True)",
                "calling set_aspect() on each shared Axes with share=False",
            )
        if kwargs:
            raise TypeError(
                f"set_aspect() got an unexpected keyword argument {next(iter(kwargs))!r}"
            )
        if adjustable is not None:
            self.set_adjustable(adjustable)
        if anchor is not None:
            self.set_anchor(anchor)
        if aspect == "auto":
            self._aspect_equal = False
            self._aspect_value = 1.0
        elif aspect == "equal":
            self._aspect_equal = True
            self._aspect_value = 1.0
        else:
            value = float(aspect)
            if not np.isfinite(value) or value <= 0:
                raise ValueError("aspect must be finite and positive")
            self._aspect_equal = True
            self._aspect_value = value
        if self._aspect_equal:
            self._set_aspect_equal_from_current()
        else:
            self._aspect_bounds = None
            self._invalidate()

    def get_gridspec(self) -> Any:
        """Return the GridSpec that placed this subplot, or ``None``.

        Uniform grids are stored compactly by the shim.  Materialize their
        shared GridSpec lazily so gallery idioms can remove cells and replace
        them with a spanning subplot through ``fig.add_subplot(gs[...])``.
        """
        if self._subplot_spec is not None:
            return self._subplot_spec.gridspec
        figure = self.figure
        if figure is None or self not in figure._axes:
            return None
        nrows, ncols = figure._nrows, figure._ncols
        cell_count = nrows * ncols
        uniform_axes = [
            axes
            for axes in figure._axes
            if axes._figure_rect is None
            and axes._subplot_index is not None
            and 0 <= axes._subplot_index < cell_count
        ]
        if cell_count <= 0 or len({axes._subplot_index for axes in uniform_axes}) < cell_count:
            return None
        from ._mplfig import _GridSpec, _SubplotSpec

        grid = _GridSpec(
            figure,
            nrows,
            ncols,
            width_ratios=figure._width_ratios,
            height_ratios=figure._height_ratios,
        )
        for axes in uniform_axes:
            index = axes._subplot_index
            assert index is not None
            row, col = divmod(index, ncols)
            spec = _SubplotSpec(
                grid,
                (row, row + 1),
                (col, col + 1),
            )
            axes._subplot_spec = spec
            # Once callers can remove arbitrary cells, list position no longer
            # identifies a subplot's row and column. Freeze every existing
            # cell to its GridSpec rect before the first removal.
            axes._figure_rect = grid.cell_rect(spec.rows, spec.cols)
        return grid

    def get_subplotspec(self) -> Any:
        """Return this axes' SubplotSpec, materializing a uniform one if needed."""
        self.get_gridspec()
        return self._subplot_spec

    def margins(self, *args: Any, **kwargs: Any) -> tuple[float, float] | None:
        """Set or return autoscaling padding around the data, as axis fractions.

        Call as ``margins(m)``, ``margins(x, y)``, or with ``x=``/``y=``;
        values must be finite and greater than -0.5 (negative margins clip).
        With no values, return the current ``(xmargin, ymargin)``. ``tight``
        controls round-number locator expansion; ``None`` preserves its prior
        setting. Explicitly set limits are left alone.
        """
        tight = kwargs.pop("tight", True)
        x = kwargs.pop("x", None)
        y = kwargs.pop("y", None)
        if kwargs:
            raise TypeError(f"margins() got unsupported keyword argument {next(iter(kwargs))!r}")
        if args and (x is not None or y is not None):
            raise TypeError("Cannot pass both positional and keyword arguments for x and/or y.")
        if len(args) == 1:
            x = y = args[0]
        elif len(args) == 2:
            x, y = args
        elif args:
            raise TypeError(
                "Must pass a single positional argument for all margins, "
                "or one for each margin (x, y)."
            )
        if x is None and y is None:
            if tight is not True:
                warnings.warn(f"ignoring tight={tight!r} in get mode", stacklevel=2)
            return self._xmargin, self._ymargin
        if tight is not None:
            self._tight = bool(tight)
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

    def _effective_margin(self, axis: str) -> float:
        configured = self._xmargin if axis == "x" else self._ymargin
        if axis in self._margin_overrides:
            return configured
        return max(configured, self._annotation_margins[axis])

    def _reserve_annotation_margin(self, axis: str, margin: float) -> None:
        """Reserve autoscale space for an annotation outside a data mark."""
        target = self._y2_of if axis == "x" and self._y2_of is not None else self
        target._annotation_margins[axis] = max(target._annotation_margins[axis], float(margin))

    def get_xmargin(self) -> float:
        """Return the configured x-axis autoscale margin."""
        return self._xmargin if "x" in self._margin_overrides else self._rc_margins["x"]

    def get_ymargin(self) -> float:
        """Return the configured y-axis autoscale margin."""
        return self._ymargin if "y" in self._margin_overrides else self._rc_margins["y"]

    def set_xmargin(self, margin: float) -> None:
        """Set x-axis autoscale padding as a fraction of the data interval."""
        self.margins(x=margin, tight=None)

    def set_ymargin(self, margin: float) -> None:
        """Set y-axis autoscale padding as a fraction of the data interval."""
        self.margins(y=margin, tight=None)

    def relim(self, visible_only: bool = False) -> None:
        """Recompute the data limits from the plotted entries.

        Axes with explicitly set limits keep them; ``visible_only`` is a
        compat-noop (invisible entries retain the same data extent).
        """
        del visible_only  # compat-noop: invisible entries retain the same data extent
        for axis in ("x", "y"):
            if axis not in self._explicit_domains:
                self._axis_props(axis).pop("domain", None)
        self._invalidate()

    def autoscale(
        self, enable: bool | None = True, axis: str = "both", tight: Optional[bool] = None
    ) -> None:
        """Turn autoscaling on or off and re-fit the limits.

        ``axis`` restricts to ``"x"`` or ``"y"`` (default ``"both"``);
        ``tight=True`` removes margins from axes receiving the request, and
        ``enable=False`` freezes the current auto limits.
        """
        if axis not in {"both", "x", "y"}:
            raise ValueError("autoscale() axis must be 'both', 'x', or 'y'")
        axes = ("x", "y") if axis == "both" else (axis,)
        # Matplotlib forwards ``tight`` to both axes when enable=None,
        # regardless of ``axis``. Their enabled/disabled state itself remains
        # unchanged.
        forwarded_axes = ("x", "y") if enable is None else axes if enable else ()
        if forwarded_axes and tight is not None:
            self._tight = bool(tight)
        for item in forwarded_axes:
            if tight:
                if item == "x":
                    self._xmargin = 0.0
                else:
                    self._ymargin = 0.0
                self._margin_overrides.add(item)
            if enable is True:
                self._explicit_domains.discard(item)
            if item not in self._explicit_domains:
                self._axis_props(item).pop("domain", None)
        if enable is False:
            for item in axes:
                self._axis_props(item)["domain"] = self._auto_domain(item)
                self._explicit_domains.add(item)
        self._invalidate()

    def autoscale_view(
        self, tight: Optional[bool] = None, scalex: bool = True, scaley: bool = True
    ) -> None:
        """Re-fit the axes limits to the data (see `autoscale`).

        ``scalex``/``scaley`` select which currently enabled axes to
        recompute. ``tight`` controls locator rounding while preserving the
        configured margins.
        """
        if tight is not None:
            self._tight = bool(tight)
        for item, selected in (("x", scalex), ("y", scaley)):
            if selected and item not in self._explicit_domains:
                self._axis_props(item).pop("domain", None)
        self._invalidate()

    def get_xbound(self) -> tuple[float, float]:
        """The x bounds as a ``(lower, upper)`` pair (see `get_xlim`)."""
        return self.get_xlim()

    def set_xbound(
        self, lower: float | LimitsLike | None = None, upper: float | None = None
    ) -> None:
        """Set the x bounds via `set_xlim`.

        Accepts ``set_xbound(lower, upper)`` or a single ``(lower, upper)``
        pair; either side may be None to keep the current value.
        """
        if isinstance(lower, (tuple, list)):
            lower, upper = lower
        current = self.get_xlim()
        self.set_xlim(
            current[0] if lower is None else lower, current[1] if upper is None else upper
        )

    def get_ybound(self) -> tuple[float, float]:
        """The y bounds as a ``(lower, upper)`` pair (see `get_ylim`)."""
        return self.get_ylim()

    def set_ybound(
        self, lower: float | LimitsLike | None = None, upper: float | None = None
    ) -> None:
        """Set the y bounds via `set_ylim` (forms as in `set_xbound`)."""
        if isinstance(lower, (tuple, list)):
            lower, upper = lower
        current = self.get_ylim()
        self.set_ylim(
            current[0] if lower is None else lower, current[1] if upper is None else upper
        )

    def ticklabel_format(self, **kwargs: Any) -> None:
        """Configure the scalar tick-label formatter.

        Supported keywords: ``axis`` (``"both"``/``"x"``/``"y"``), ``style``
        (``"plain"`` or ``"sci"``/``"scientific"``), ``scilimits=(m, n)``
        bounding the exponent range that stays plain, and ``useOffset``
        (alias ``useoffset``). ``useLocale``/``useMathText`` must stay False
        and anything else raises loudly.
        """
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
        """Show automatically subdivided minor ticks on both axes."""
        for axis in ("x", "y"):
            host, key = _AxisProxy(self, axis)._ticker_slot()
            spec = host._scale_specs.get(key) or {"name": "linear"}
            if spec.get("name") == "log":
                from ._ticker import LogLocator

                locator = LogLocator(
                    base=float(spec.get("base", 10.0)),
                    subs=spec.get("subs"),
                )
            else:
                locator = AutoMinorLocator()
            host._tickers[(key, "minor_locator")] = locator
            host._invalidate_shared_ticker_axis(key)

    def minorticks_off(self) -> None:
        """Hide minor ticks on both axes."""
        for axis in ("x", "y"):
            host, key = _AxisProxy(self, axis)._ticker_slot()
            host._tickers[(key, "minor_locator")] = NullLocator()
            host._axis[key].pop("minor_tick_values", None)
            host._invalidate_shared_ticker_axis(key)

    def get_xlabel(self) -> str:
        """The x-axis label text (empty string when unset)."""
        return str(self._axis_props("x").get("label", ""))

    def get_ylabel(self) -> str:
        """The y-axis label text (empty string when unset)."""
        return str(self._axis_props("y").get("label", ""))

    def get_title(self, loc: str = "center") -> str:
        """The axes title text for ``loc`` (empty string when unset)."""
        resolved = str(loc).lower()
        if resolved not in {"left", "center", "right"}:
            raise ValueError("get_title() loc must be 'left', 'center', or 'right'")
        title = (self._y2_of or self)._titles.get(resolved)
        return "" if title is None else str(title["text"])

    def get_xaxis(self) -> _AxisProxy:
        """The x-axis proxy (the same object as ``ax.xaxis``)."""
        return self.xaxis

    def get_yaxis(self) -> _AxisProxy:
        """The y-axis proxy (the same object as ``ax.yaxis``)."""
        return self.yaxis

    def get_figure(self, root: bool | None = None) -> Any:
        """The owning figure (``root`` is a compat-noop)."""
        del root  # compat-noop: no nested subfigures; both roots are self.figure
        return self.figure

    def get_lines(self) -> list[Line2D]:
        """The `Line2D` artists on this axes, in creation order."""
        host = self._y2_of or self
        return [artist for artist in host._owned_artists if isinstance(artist, Line2D)]

    def get_shared_x_axes(self) -> _SharedAxesGroup:
        """matplotlib's shared-x Grouper view over the figure's axes."""
        return _SharedAxesGroup("x")

    def get_shared_y_axes(self) -> _SharedAxesGroup:
        """matplotlib's shared-y Grouper view over the figure's axes."""
        return _SharedAxesGroup("y")

    def get_xticklabels(self) -> list[_TickLabel]:
        """Handles for the x tick labels (styling applies axis-wide)."""
        return self._tick_label_handles("x")

    def get_yticklabels(self) -> list[_TickLabel]:
        """Handles for the y tick labels (styling applies axis-wide)."""
        return self._tick_label_handles("y")

    def _tick_label_handles(self, axis: str) -> list[_TickLabel]:
        labels = self._axis_props(axis).get("tick_labels")
        if labels is None:
            labels = [f"{value:g}" for value in self._computed_ticks(axis, False)]
        return [_TickLabel(self, axis, str(text)) for text in labels]

    def set_facecolor(self, color: ColorLike) -> None:
        """Set the plot-panel background color."""
        resolved = resolve_color(color)
        if resolved is not None:
            self._theme_tokens["plot_background"] = resolved
        self._invalidate()

    def get_facecolor(self) -> Any:
        """The plot-panel background color."""
        return self._theme_tokens.get("plot_background")

    def set_axisbelow(self, b: bool) -> None:
        """Accept ``set_axisbelow(True)``; any other order raises loudly.

        The engine always composites grid lines beneath data marks, which is
        exactly ``axisbelow=True``; other stacking orders are not
        expressible.
        """
        # The engine composites grid lines beneath data marks unconditionally,
        # which is exactly axisbelow=True; other orders are not expressible.
        if b is not True:
            raise not_implemented(
                f"set_axisbelow({b!r})", "the engine's fixed grid-below-marks order"
            )

    def get_legend(self) -> Any:
        """Return the current legend artist, or ``None`` when hidden."""
        host = self._y2_of or self
        return host._legend_handle if host._legend else None

    def get_legend_handles_labels(self) -> tuple[list[Any], list[str]]:
        """Handles and labels of the entries that would appear in the legend.

        Entries whose label starts with ``"_"`` are excluded, matching
        matplotlib.
        """
        from ._artists import ErrorbarContainer

        host = self._y2_of or self
        errorbar_containers = {
            id(container._artist._entry): container
            for container in host._containers
            if isinstance(container, ErrorbarContainer)
        }
        bar_containers = {
            id(container._entry): container
            for container in host._containers
            if isinstance(container, BarContainer) and container._entry.get("kind") == "bar"
        }
        handles: list[Any] = []
        labels: list[str] = []
        for entry in host._entries:
            patch_labels = entry.get("patch_labels")
            if patch_labels is not None:
                container = bar_containers.get(id(entry))
                for index, label in enumerate(patch_labels):
                    if label and not str(label).startswith("_"):
                        handles.append(
                            container[index] if container is not None else Artist(self, entry)
                        )
                        labels.append(str(label))
                continue
            # Matplotlib scans ordinary child artists first, then containers.
            # Defer container-owned entries so an errorbar/bar pair follows
            # the public Axes.containers registration order.
            if id(entry) in errorbar_containers or id(entry) in bar_containers:
                continue
            label = entry.get("kwargs", {}).get("name")
            if label and not str(label).startswith("_"):
                handles.append(Artist(self, entry))
                labels.append(str(label))
        for container in host._containers:
            if not isinstance(container, (BarContainer, ErrorbarContainer)):
                continue
            if isinstance(container, BarContainer) and container._entry.get("kind") != "bar":
                continue
            if (
                isinstance(container, BarContainer)
                and container._entry.get("patch_labels") is not None
            ):
                continue
            label = container.get_label()
            if label and not str(label).startswith("_"):
                handles.append(container)
                labels.append(str(label))
        return handles, labels

    def set_prop_cycle(self, *args: Any, **kwargs: Any) -> None:
        """Set the color cycle used for new artists.

        Accepts a cycler, a ``{"color": [...]}`` dict,
        ``set_prop_cycle("color", colors)``, or a ``color=`` keyword;
        ``set_prop_cycle(None)`` restores the rc cycle. Only color cycles
        are supported — other properties raise loudly. Resets the cycle
        position.
        """
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
        self._patch_cycle = 0
        self._invalidate()

    def secondary_xaxis(
        self, location: str | float = "top", functions: Any = None, *, transform: Any = None
    ) -> SecondaryAxis:
        """Add a linked, tick-only secondary x-axis.

        ``location`` is ``"top"`` or ``"bottom"``; ``functions`` is a
        ``(forward, inverse)`` pair (or invertible transform) mapping parent
        coordinates to secondary ones. ``transform=`` raises loudly.
        Returns the `SecondaryAxis`.
        """
        if transform is not None:
            raise not_implemented("secondary_xaxis(transform=...)")
        made = SecondaryAxis(self, "x", location, functions)
        self._secondary_axes.append(made)
        self._invalidate()
        return made

    def secondary_yaxis(
        self, location: str | float = "right", functions: Any = None, *, transform: Any = None
    ) -> SecondaryAxis:
        """Add a linked, tick-only secondary y-axis.

        The y twin of `secondary_xaxis`: ``location`` is ``"left"`` or
        ``"right"``, and ``functions`` maps parent coordinates to secondary
        ones.
        """
        if transform is not None:
            raise not_implemented("secondary_yaxis(transform=...)")
        made = SecondaryAxis(self, "y", location, functions)
        self._secondary_axes.append(made)
        self._invalidate()
        return made

    def _set_tight_domains(self, *, tight: bool = True) -> None:
        # Axis modes materialize the margin-expanded view before applying
        # their aspect/autoscale policy. "Tight" suppresses tick-locator
        # expansion; it does not mean raw data extrema.
        self._tight = bool(tight)
        for axis in ("x", "y"):
            self._axis_props(axis)["domain"] = self._auto_domain(axis)
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
            self._axis_props(axis)["domain"] = self._auto_domain(axis)
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
        """Suppress every x/y-axis decoration without changing its settings."""
        self.axison = False
        self._invalidate()

    def set_axis_on(self) -> None:
        """Draw x/y-axis decorations using their existing visibility settings."""
        self.axison = True
        self._invalidate()

    def inset_axes(
        self, bounds: tuple[float, float, float, float] | Sequence[float], **kwargs: Any
    ) -> "Axes":
        """Add a child inset axes.

        ``bounds`` is ``(left, bottom, width, height)`` in parent-axes
        fractions; ``sharex``/``sharey`` hints link the figure's axes. The
        inset's contents are drawn into the parent when the chart
        materializes.
        """
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

        def mapper(
            source: tuple[float, float], target: tuple[float, float]
        ) -> Callable[[Any], np.ndarray]:
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
        """The x-axis transform sentinel: data-space x, axes-fraction y."""
        del kwargs
        return "xaxis transform"

    def get_yaxis_transform(self, **kwargs: Any) -> str:
        """The y-axis transform sentinel: axes-fraction x, data-space y."""
        del kwargs
        return "yaxis transform"

    def label_outer(self, remove_inner_ticks: bool = False) -> None:
        """Keep axis labels and tick labels only on the GridSpec's outer edges."""
        spec = self.get_subplotspec()
        if spec is None:
            return

        x_label_side = self._axis_props("x").get("side", "bottom")
        if spec.rows[0] != 0:
            if x_label_side == "top":
                self.set_xlabel("")
            self.tick_params(
                axis="x",
                which="both",
                labeltop=False,
                **({"top": False} if remove_inner_ticks else {}),
            )
        if spec.rows[1] != spec.nrows:
            if x_label_side == "bottom":
                self.set_xlabel("")
            self.tick_params(
                axis="x",
                which="both",
                labelbottom=False,
                **({"bottom": False} if remove_inner_ticks else {}),
            )

        y_label_side = self._axis_props("y").get("side", "left")
        if spec.cols[0] != 0:
            if y_label_side == "left":
                self.set_ylabel("")
            self.tick_params(
                axis="y",
                which="both",
                labelleft=False,
                **({"left": False} if remove_inner_ticks else {}),
            )
        if spec.cols[1] != spec.ncols:
            if y_label_side == "right":
                self.set_ylabel("")
            self.tick_params(
                axis="y",
                which="both",
                labelright=False,
                **({"right": False} if remove_inner_ticks else {}),
            )

    def add_artist(self, artist: Any) -> Any:
        """Add a prebuilt artist to the axes.

        Accepts a `Legend` (attached as an extra legend) or an image-like
        mappable with ``get_array()`` (drawn via `imshow`); anything else
        raises with a pointer to ``text()``/``imshow()``/``add_line()``/
        ``add_patch()``/``add_collection()``.
        """
        if isinstance(artist, Legend):
            host = self._y2_of or self
            artist._attach(host)
            host._extra_legends.append(artist)
            if artist is host._legend_artist:
                host._legend_artist = None
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
        """Add a `Line2D`-like artist, replotting foreign ones via `plot`.

        A shim `Line2D` must already belong to this axes; any other object
        needs ``get_data()`` and may carry ``get_color``/``get_label``/
        ``get_linewidth``/``get_alpha``.
        """
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
        """Register an existing container on this axes.

        Only `BarContainer`, `ErrorbarContainer`, and `StemContainer` are
        supported; other types raise.
        """
        from ._artists import BarContainer, ErrorbarContainer, StemContainer

        if not isinstance(container, (BarContainer, ErrorbarContainer, StemContainer)):
            raise TypeError(
                f"unsupported container {type(container).__name__}; supported containers are "
                "BarContainer, ErrorbarContainer, and StemContainer"
            )
        self._register_container(container)
        return container

    def add_table(self, table: Any) -> Any:
        """Register a `Table` created by ``Axes.table()``; other objects raise."""
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
        """Add a LineCollection-like artist (anything with ``get_segments()``).

        A ``get_array()`` value array becomes a per-segment color encoding
        through the collection's colormap; otherwise the first
        ``get_colors()`` entry (or the next cycle color) paints every
        segment.
        """
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
        """Add a patch as a filled body plus its outline, or as a stairs fill.

        StepPatch-likes (with ``get_data()``) route to `stairs`. Every other
        patch is flattened to data-space rings via ``Path.to_polygons``, so
        rotation and curvature survive; each ring fills with the patch's own
        face color, and rings draw their edge as line segments when the patch
        has a visible one. A path whose rings nest, meaning holes, draws its
        outline and skips the fill rather than painting the hole solid. The
        returned handle owns every mark the patch produced, so removing or
        hiding it moves the outline with the fill. Unsupported patch types
        raise.
        """
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
        from xy import kernels

        canvas = rc_figsize_px(self.figure._figsize, self.figure._dpi)
        outline = _patch_outline(patch, pixels=float(max(canvas)))
        face = _patch_fill_color(patch)
        edge = _patch_edge_color(patch)
        width = float(getattr(patch, "get_linewidth", lambda: 1.0)()) * self._point_scale()
        entries: list[dict[str, Any]] = []
        if face is not None and not _rings_are_nested(outline):
            for ring in outline:
                xv, yv = ring[:, 0], ring[:, 1]
                # Non-finite vertices have no triangulation, as in `Axes.fill`.
                finite = np.isfinite(xv) & np.isfinite(yv)
                xv, yv = xv[finite], yv[finite]
                if len(xv) > 2:
                    # Closing-vertex test at the ring's own scale, like
                    # `_without_repeats`: `np.allclose` scales with coordinate
                    # magnitude and would swallow a real 5,000-unit closing
                    # edge on a duck-path ring drawn at x = 1e9.
                    span = float(np.hypot(np.ptp(xv), np.ptp(yv)))
                    if np.hypot(xv[0] - xv[-1], yv[0] - yv[-1]) <= span * 1e-12:
                        xv, yv = xv[:-1], yv[:-1]
                if len(xv) < 3:
                    # Degenerate, such as a zero-height Rectangle. It has no
                    # body to fill; the outline pass below still draws it.
                    continue
                try:
                    topology = kernels.polygon_triangles(xv, yv)
                except ValueError as error:
                    # Self-intersecting, or past the triangulator's vertex cap.
                    # Matplotlib fills both, so say so rather than shipping a
                    # hollow patch that looks deliberate.
                    warnings.warn(
                        f"add_patch could not fill a {len(xv)}-vertex ring ({error}); "
                        "drawing its outline only",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    continue
                x0, y0, x1, y1, x2, y2, _ = kernels.indexed_triangles(xv, yv, topology)
                entries.append(
                    self._add(
                        "@mark",
                        {
                            "factory": "triangle_mesh",
                            "args": (x0, y0, x1, y1, x2, y2),
                            "kwargs": {"color": resolve_color(face), "_joined_fill": True},
                        },
                    )
                )
        # An invisible outline is worth emitting only when nothing else was:
        # the handle needs one entry to stand on, and a patch that drew no
        # body should still occupy its place in the spec.
        if (edge is not None and width > 0.0) or not entries:
            stroke = resolve_color(edge if edge is not None else "none")
            for ring in outline:
                entries.append(
                    self._add(
                        "@mark",
                        {
                            "factory": "segments",
                            "args": (ring[:-1, 0], ring[:-1, 1], ring[1:, 0], ring[1:, 1]),
                            "kwargs": {"color": stroke, "width": width},
                        },
                    )
                )
        return Patch(self, entries[0], entries[1:])

    def add_image(self, image: Any) -> AxesImage:
        """Add an AxesImage-like artist by resampling it through `imshow`.

        Non-uniform pixel coordinates (``pcolorfast``-style ``_Ax``/``_Ay``)
        are resampled onto a uniform grid, nearest or linear per the image's
        interpolation mode.
        """
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

    # -- polar projection (matplotlib PolarAxes surface) --------------------

    def _set_projection(self, projection: Any) -> None:
        """Back `subplot(projection=...)`; only 'polar' changes anything."""
        name = "cartesian" if projection in (None, "rectilinear") else str(projection)
        if name not in ("cartesian", "polar"):
            raise ValueError(
                f"projection {projection!r} is not supported; use 'polar' or 'rectilinear'"
            )
        self._projection = name
        if name == "polar":
            # Matplotlib's PolarAxes defaults: theta=0 due east, increasing
            # counterclockwise, angles in radians.
            self._polar_options.setdefault("theta_unit", "radians")
            self._polar_options.setdefault("theta_zero", "E")
            self._polar_options.setdefault("theta_direction", "counterclockwise")

    def _require_polar(self, method: str) -> None:
        if self._projection != "polar":
            raise AttributeError(
                f"{method} is only available on a polar axes; "
                "create one with subplot(projection='polar')"
            )

    def set_theta_zero_location(self, loc: str, offset: float = 0.0) -> None:
        """Direction that theta=0 points: 'N', 'NW', 'W', 'SW', 'S', 'SE', 'E'
        or 'NE', plus an optional offset in degrees."""
        self._require_polar("set_theta_zero_location")
        compass = {
            "E": 0.0,
            "NE": 45.0,
            "N": 90.0,
            "NW": 135.0,
            "W": 180.0,
            "SW": 225.0,
            "S": 270.0,
            "SE": 315.0,
        }
        key = str(loc).upper()
        if key not in compass:
            raise ValueError(f"theta zero location must be one of {sorted(compass)}")
        degrees = compass[key] + float(offset)
        # The four cardinals keep their letter so the wire stays readable and
        # one shared table resolves them; anything else ships as radians.
        letters = {0.0: "E", 90.0: "N", 180.0: "W", 270.0: "S"}
        normalized = degrees % 360.0
        self._polar_options["theta_zero"] = letters.get(normalized, math.radians(degrees))

    def set_theta_direction(self, direction: Any) -> None:
        """1/'counterclockwise'/'anticlockwise' or -1/'clockwise'."""
        self._require_polar("set_theta_direction")
        clockwise = {-1, "clockwise", "cw"}
        counter = {1, "counterclockwise", "anticlockwise", "ccw"}
        key = direction if isinstance(direction, int) else str(direction).lower()
        if key in clockwise:
            self._polar_options["theta_direction"] = "clockwise"
        elif key in counter:
            self._polar_options["theta_direction"] = "counterclockwise"
        else:
            raise ValueError("theta direction must be 1/-1 or 'clockwise'/'counterclockwise'")

    def set_theta_offset(self, offset: float) -> None:
        """Rotation of the theta=0 direction, in radians."""
        self._require_polar("set_theta_offset")
        self._polar_options["theta_zero"] = float(offset)

    def get_theta_offset(self) -> float:
        self._require_polar("get_theta_offset")
        zero = self._polar_options.get("theta_zero", "E")
        # Matplotlib's mapping is 0..2pi ccw from east, so "S" reads 3*pi/2 —
        # not the -pi/2 the render tables use. Same angle, but a compat getter
        # has to return matplotlib's number: `get_theta_offset() > 0` and
        # round-trips through `set_theta_offset` both break on the negative.
        table = {"E": 0.0, "N": math.pi / 2, "W": math.pi, "S": 3 * math.pi / 2}
        return table[zero] if isinstance(zero, str) else float(zero) % (2 * math.pi)

    def get_theta_direction(self) -> int:
        self._require_polar("get_theta_direction")
        return -1 if self._polar_options.get("theta_direction") == "clockwise" else 1

    def set_rlim(self, bottom: Any = None, top: Any = None, **kwargs: Any) -> Any:
        """Radial limits — the polar spelling of `set_ylim`.

        Accepts matplotlib's documented ``rmin``/``rmax`` keywords; anything
        else is refused by name rather than forwarded to `set_ylim`, whose
        signature does not know them.
        """
        self._require_polar("set_rlim")
        if "rmin" in kwargs:
            if bottom is not None:
                raise ValueError("set_rlim: pass either bottom or rmin, not both")
            bottom = kwargs.pop("rmin")
        if "rmax" in kwargs:
            if top is not None:
                raise ValueError("set_rlim: pass either top or rmax, not both")
            top = kwargs.pop("rmax")
        if kwargs:
            raise TypeError(f"set_rlim got unexpected keyword(s) {sorted(kwargs)}")
        return self.set_ylim(bottom, top)

    def set_rmin(self, rmin: float) -> None:
        self._require_polar("set_rmin")
        self.set_ylim(float(rmin), self.get_ylim()[1])

    def set_rmax(self, rmax: float) -> None:
        self._require_polar("set_rmax")
        self.set_ylim(self.get_ylim()[0], float(rmax))

    def get_rmin(self) -> float:
        self._require_polar("get_rmin")
        return float(self.get_ylim()[0])

    def get_rmax(self) -> float:
        self._require_polar("get_rmax")
        return float(self.get_ylim()[1])

    def set_rticks(self, ticks: Any, labels: Any = None, **kwargs: Any) -> Any:
        self._require_polar("set_rticks")
        return self.set_yticks(ticks, labels, **kwargs)

    def set_rgrids(self, radii: Any, labels: Any = None, **kwargs: Any) -> Any:
        """Radial gridline positions — matplotlib's `set_rgrids`."""
        self._require_polar("set_rgrids")
        return self.set_yticks(list(radii), labels, **kwargs)

    def set_thetagrids(self, angles: Any, labels: Any = None, **kwargs: Any) -> Any:
        """Angular gridline positions, in DEGREES.

        Matplotlib takes degrees here regardless of the data's unit, which is
        the one place its polar API is not unit-consistent; matching it matters
        more than being tidy.
        """
        values = [float(a) for a in angles]
        self._require_polar("set_thetagrids")
        if self._polar_options.get("theta_unit", "radians") == "radians":
            values = [math.radians(a) for a in values]
        return self.set_xticks(values, labels, **kwargs)

    def set_thetamin(self, thetamin: float) -> None:
        self._require_polar("set_thetamin")
        value = float(thetamin)
        if not math.isfinite(value):
            raise ValueError("thetamin must be finite")
        _lo, hi = sorted(self.get_xlim())
        lo = math.radians(value)
        if lo >= hi:
            raise ValueError("thetamin must be less than thetamax")
        self.set_xlim(lo, hi)

    def set_thetamax(self, thetamax: float) -> None:
        self._require_polar("set_thetamax")
        value = float(thetamax)
        if not math.isfinite(value):
            raise ValueError("thetamax must be finite")
        lo, _hi = sorted(self.get_xlim())
        hi = math.radians(value)
        if hi <= lo:
            raise ValueError("thetamax must be greater than thetamin")
        self.set_xlim(lo, hi)

    def get_thetamin(self) -> float:
        """Minimum visible theta in degrees, matching Matplotlib PolarAxes."""
        self._require_polar("get_thetamin")
        lo, _hi = sorted(self.get_xlim())
        return math.degrees(float(lo))

    def get_thetamax(self) -> float:
        """Maximum visible theta in degrees, matching Matplotlib PolarAxes."""
        self._require_polar("get_thetamax")
        _lo, hi = sorted(self.get_xlim())
        return math.degrees(float(hi))

    def set_rorigin(self, origin: Optional[float]) -> None:
        """Set the data-space radial origin; ``None`` restores rmin."""
        self._require_polar("set_rorigin")
        if origin is None:
            self._polar_r_options.pop("r_origin", None)
        else:
            value = float(origin)
            if not math.isfinite(value):
                raise ValueError("rorigin must be finite")
            self._polar_r_options["r_origin"] = value
        self._invalidate()

    def get_rorigin(self) -> float:
        """Return the authored radial origin, or the current radial minimum."""
        self._require_polar("get_rorigin")
        value = self._polar_r_options.get("r_origin")
        return self.get_rmin() if value is None else float(value)

    def set_xscale(self, scale: str, **kwargs: Any) -> None:
        """Set the x-axis scale.

        ``scale`` is ``"linear"``, ``"log"``, ``"symlog"``, ``"logit"``, or
        ``"asinh"``/``"function"``. Built-in scale options and a static
        ``functions=(forward, inverse)`` pair follow Matplotlib. Existing data,
        limits, and ticks are re-expressed in the new scale.
        """
        self._set_scale("x", scale, kwargs)

    def set_yscale(self, scale: str, **kwargs: Any) -> None:
        """Set the y-axis scale (same values and keywords as `set_xscale`)."""
        self._set_scale("y", scale, kwargs)

    def _set_scale(self, axis: str, scale: str, kwargs: Optional[dict[str, Any]] = None) -> None:
        kwargs = {} if kwargs is None else dict(kwargs)
        if scale not in ("linear", "log", "symlog", "logit", "asinh", "function"):
            raise ValueError(f"unknown {axis} scale {scale!r}")
        host = self._y2_of or self
        key = "y2" if axis == "y" and self._y2_of is not None else axis
        old = host._scale_specs[key]
        if scale == "linear" and kwargs:
            check_unsupported(kwargs, f"set_{axis}scale('linear')")
        base = 10.0
        subs: Any = None
        nonpositive = "clip"
        if scale == "log":
            base = float(kwargs.pop("base", 10))
            subs = kwargs.pop("subs", None)
            nonpositive = kwargs.pop("nonpositive", "clip")
            if not np.isfinite(base) or base <= 1:
                raise ValueError("log scale base must be greater than 1")
            if nonpositive not in {"clip", "mask"}:
                raise ValueError("nonpositive must be 'clip' or 'mask'")
            if subs is not None:
                subs = tuple(float(sub) for sub in subs)
                if any(not np.isfinite(sub) or sub <= 0 for sub in subs):
                    raise ValueError("log scale subs must contain positive finite values")
        new: dict[str, Any]
        if scale == "symlog":
            new = {
                "name": scale,
                "base": float(kwargs.pop("base", 10.0)),
                "linthresh": float(kwargs.pop("linthresh", 2.0)),
                "linscale": float(kwargs.pop("linscale", 1.0)),
                "subs": kwargs.pop("subs", None),
            }
        elif scale == "asinh":
            asinh_base = float(kwargs.pop("base", 10))
            asinh_subs = kwargs.pop("subs", "auto")
            if isinstance(asinh_subs, str) and asinh_subs == "auto":
                auto_subs = {
                    3: (2,),
                    4: (2,),
                    5: (2,),
                    8: (2, 4),
                    10: (2, 5),
                    16: (2, 4, 8),
                    64: (4, 16),
                    1024: (256, 512),
                }
                asinh_subs = auto_subs.get(int(asinh_base))
            elif asinh_subs is not None:
                asinh_subs = tuple(float(value) for value in asinh_subs)
            new = {
                "name": scale,
                "linear_width": float(kwargs.pop("linear_width", 1.0)),
                "base": asinh_base,
                "subs": asinh_subs,
            }
        elif scale == "logit":
            logit_nonpositive = kwargs.pop("nonpositive", "mask")
            if logit_nonpositive not in {"clip", "mask"}:
                raise ValueError("nonpositive must be 'clip' or 'mask'")
            new = {
                "name": scale,
                "nonpositive": logit_nonpositive,
                "one_half": str(kwargs.pop("one_half", r"\frac{1}{2}")),
                "use_overline": bool(kwargs.pop("use_overline", False)),
            }
        elif scale == "function":
            functions = kwargs.pop("functions", None)
            if (
                not isinstance(functions, (tuple, list))
                or len(functions) != 2
                or not all(callable(function) for function in functions)
            ):
                raise ValueError(f"set_{axis}scale('function') requires two callable functions")
            new = {
                "name": scale,
                "forward": functions[0],
                "inverse": functions[1],
            }
        elif scale == "log":
            new = {
                "name": "log",
                "base": base,
                "subs": subs,
                "nonpositive": nonpositive,
            }
        else:
            new = {"name": scale}
        check_unsupported(kwargs, f"set_{axis}scale({scale!r})")
        if scale == "symlog" and (
            new["base"] <= 1 or new["linthresh"] <= 0 or new["linscale"] <= 0
        ):
            raise ValueError(f"set_{axis}scale({scale!r}) parameters must be positive")
        if scale == "symlog" and new["subs"] is not None:
            new["subs"] = tuple(float(value) for value in new["subs"])
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
        host._scale_specs[key] = new
        # Matplotlib changes only scale-owned defaults; a user locator or
        # formatter remains authoritative. Mark our defaults so a later scale
        # transition can replace them without disturbing authored ticker state.
        for slot in (
            "major_locator",
            "major_formatter",
            "minor_locator",
            "minor_formatter",
        ):
            existing = host._tickers.get((key, slot))
            if getattr(existing, "_xy_scale_default", False):
                host._tickers.pop((key, slot), None)
        if "tick_values" not in props:
            for slot, ticker in _scale_default_tickers(new).items():
                if (key, slot) in host._tickers:
                    continue
                ticker._xy_scale_default = True
                host._tickers[(key, slot)] = ticker
        axis_props = self._axis_props(axis)
        axis_props["type_"] = "log" if scale == "log" else None
        if scale == "log":
            axis_props["nonpositive"] = nonpositive
        else:
            axis_props.pop("nonpositive", None)
        self._invalidate()

    def invert_yaxis(self) -> None:
        """Flip the y-axis direction (toggles on repeated calls)."""
        props = self._axis_props("y")
        props["reverse"] = not props.get("reverse", False)
        self._invalidate()

    def invert_xaxis(self) -> None:
        """Flip the x-axis direction (toggles on repeated calls)."""
        props = self._axis_props("x")
        props["reverse"] = not props.get("reverse", False)
        self._invalidate()

    def _set_tick_rotation_mode(self, axis: str, mode: str | None) -> None:
        if mode is None or mode == "default":
            normalized = None
        elif mode in {"anchor", "xtick", "ytick"}:
            normalized = mode
        else:
            raise ValueError(
                f"{mode!r} is not a valid value for rotation_mode; "
                "supported values are 'anchor', 'default', 'xtick', and 'ytick'"
            )
        self._tick_rotation_modes[axis] = normalized
        angle = float(self._axis_props(axis).get("tick_label_angle", 0.0))
        self._apply_tick_rotation_mode(axis, angle)

    def _apply_tick_rotation_mode(self, axis: str, angle: float) -> None:
        """Translate Matplotlib's special tick rotation pivot when expressible."""
        props = self._axis_props(axis)
        mode = self._tick_rotation_modes.get(axis)
        if mode == "anchor":
            props["tick_label_anchor"] = "center"
            return
        if mode != "xtick" or axis != "x":
            props.pop("tick_label_anchor", None)
            return
        # Matplotlib Text._ha_for_angle: bottom labels have verticalalignment
        # "top", while top labels use "bottom". Convert its left/right result
        # to XY's start/end anchor vocabulary.
        value = float(angle) % 360.0
        anchor_at_bottom = props.get("side", "bottom") == "top"
        if (
            value <= 10
            or 85 <= value <= 95
            or value >= 350
            or 170 <= value <= 190
            or 265 <= value <= 275
        ):
            anchor = "center"
        elif 10 < value < 85 or 190 < value < 265:
            anchor = "start" if anchor_at_bottom else "end"
        else:
            anchor = "end" if anchor_at_bottom else "start"
        props["tick_label_anchor"] = anchor

    def _apply_tick_side_visibility(
        self, axis: str, side_updates: dict[str, bool], length: float | None
    ) -> None:
        sides = self._tick_sides[axis]
        sides.update({key: value for key, value in side_updates.items() if key in sides})
        props = self._axis_props(axis)
        style = props.setdefault("style", {})
        if length is not None:
            self._tick_lengths[axis] = float(length) * self._point_scale()
        if any(sides.values()):
            style["tick_length"] = self._tick_lengths[axis]
            props["tick_sides"] = [side for side, shown in sides.items() if shown]
        else:
            # The native axis has one tick side, so zero length is its exact
            # representation of Matplotlib's tick1On=False/tick2On=False.
            style["tick_length"] = 0.0
            props["tick_sides"] = []

    def _apply_tick_label_side_visibility(self, axis: str, side_updates: dict[str, bool]) -> None:
        sides = self._tick_label_sides[axis]
        sides.update({key: value for key, value in side_updates.items() if key in sides})
        props = self._axis_props(axis)
        props["tick_label_strategy"] = None if any(sides.values()) else "off"
        props["tick_label_sides"] = [
            key.removeprefix("label") for key, shown in sides.items() if shown
        ]

    def tick_params(self, axis: str = "both", **kwargs: Any) -> None:
        """Change tick, tick-label, and axis-color appearance.

        ``axis`` selects ``"x"``/``"y"``/``"both"``. Supported keywords:
        ``which`` selects major/minor/both. ``labelrotation``/``rotation``,
        ``colors``, ``color``, ``labelcolor``, ``length``/``size``, ``width``,
        ``pad``, ``labelsize``, ``direction``
        (``"in"``/``"out"``/``"inout"``), and the ``labelbottom``/
        ``labeltop``/``labelleft``/``labelright`` and ``bottom``/``top``/
        ``left``/``right`` visibility flags. The legacy ``tick1On``/
        ``tick2On`` names are accepted. ``rotation_mode`` and
        ``labelrotation_mode`` support Matplotlib 3.11's special tick-label
        anchors; anything else raises loudly.
        """
        if axis not in {"both", "x", "y"}:
            raise ValueError("tick_params() axis must be 'both', 'x', or 'y'")
        which = str(kwargs.pop("which", "major")).lower()
        if which not in {"major", "minor", "both"}:
            raise ValueError("tick_params() which must be 'major', 'minor', or 'both'")
        reset = bool(kwargs.pop("reset", False))
        if reset:
            raise not_implemented("tick_params(reset=True)", "reset=False")
        rotation = kwargs.pop("labelrotation", kwargs.pop("rotation", None))
        rotation_mode = kwargs.pop("labelrotation_mode", kwargs.pop("rotation_mode", None))
        colors = kwargs.pop("colors", None)
        color = kwargs.pop("color", colors)
        labelcolor = kwargs.pop("labelcolor", colors)
        length = kwargs.pop("length", kwargs.pop("size", None))
        pad = kwargs.pop("pad", None)
        width = kwargs.pop("width", None)
        labelsize = kwargs.pop("labelsize", None)
        direction = kwargs.pop("direction", None)
        tick1_on = kwargs.pop("tick1On", None)
        tick2_on = kwargs.pop("tick2On", None)
        side_updates = {
            key: bool(kwargs.pop(key))
            for key in ("bottom", "top", "left", "right")
            if key in kwargs
        }
        label_side_updates = {
            key: bool(kwargs.pop(key))
            for key in ("labelbottom", "labeltop", "labelleft", "labelright")
            if key in kwargs
        }
        if kwargs:
            raise TypeError(
                f"tick_params() got unsupported keyword argument {next(iter(kwargs))!r}"
            )
        for ax in ("x", "y") if axis == "both" else (axis,):
            props = self._axis_props(ax)
            physical_sides = ("bottom", "top") if ax == "x" else ("left", "right")
            legacy_sides = dict(side_updates)
            if tick1_on is not None:
                legacy_sides[physical_sides[0]] = bool(tick1_on)
            if tick2_on is not None:
                legacy_sides[physical_sides[1]] = bool(tick2_on)
            if rotation is not None and which in {"major", "both"}:
                props["tick_label_angle"] = float(rotation)
            if rotation_mode is not None and which in {"major", "both"}:
                self._set_tick_rotation_mode(ax, rotation_mode)
            elif rotation is not None and which in {"major", "both"}:
                self._apply_tick_rotation_mode(ax, float(rotation))
            style_names = (
                ("style", "minor_style")
                if which == "both"
                else ("style" if which == "major" else "minor_style",)
            )
            for style_name in style_names:
                style = props.setdefault(style_name, {})
                if color is not None:
                    style["tick_color"] = resolve_color(color)
                if labelcolor is not None:
                    style["tick_label_color"] = resolve_color(labelcolor)
                if length is not None:
                    style["tick_length"] = float(length) * self._point_scale()
                if pad is not None:
                    style["tick_padding"] = float(pad) * self._point_scale()
                if width is not None:
                    style["tick_width"] = float(width) * self._point_scale()
                if labelsize is not None:
                    style["tick_label_size"] = (
                        _font_size_points(labelsize, rcParams["font.size"]) * self._point_scale()
                    )
                if direction is not None:
                    if direction not in {"in", "out", "inout"}:
                        raise ValueError("tick_params() direction must be 'in', 'out', or 'inout'")
                    style["tick_direction"] = direction
            if legacy_sides and which in {"major", "both"}:
                self._apply_tick_side_visibility(ax, legacy_sides, length)
            if legacy_sides and which == "minor":
                visible_minor_sides = [
                    side
                    for side in physical_sides
                    if legacy_sides.get(side, self._tick_sides[ax][side])
                ]
                if not visible_minor_sides:
                    props.setdefault("minor_style", {})["tick_length"] = 0.0
                elif (
                    length is None and props.setdefault("minor_style", {}).get("tick_length") == 0.0
                ):
                    props["minor_style"]["tick_length"] = _rc_minor_axis_style(
                        ax, self.figure.get_dpi()
                    )["tick_length"]
            if label_side_updates and which in {"major", "both"}:
                self._apply_tick_label_side_visibility(ax, label_side_updates)
        self._invalidate()

    def set_xticks(
        self,
        ticks: ArrayLike | None,
        labels: Sequence[str] | None = None,
        *,
        rotation: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Place the x ticks at the given positions, optionally relabeled.

        ``labels`` must match ``ticks`` in length and displaces any user
        formatter; ``rotation`` angles the labels in degrees. ``minor=True``
        is a compat-noop (minor ticks are outside the native axis contract).
        Positions are in data space, so nonlinear scales transform them.
        """
        if kwargs.pop("minor", False):
            return
        host = (self._y2_of or self)._shared_ticker_source("x")
        props = host._axis["x"]
        if ticks is not None:
            spec = host._scale_specs["x"]
            host._auto_scale_axis_ticks.discard("x")
            host._tickers.pop(("x", "major_locator"), None)
            props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
            props["tick_count"] = max(1, len(props["tick_values"]))
            self._expand_domain_to_ticks("x")
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
            host._tickers.pop(("x", "major_formatter"), None)
        if rotation is not None:
            self._axis_props("x")["tick_label_angle"] = float(rotation)
        host._invalidate_shared_ticker_axis("x")

    def set_yticks(
        self,
        ticks: ArrayLike | None,
        labels: Sequence[str] | None = None,
        *,
        rotation: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Place the y ticks at the given positions (see `set_xticks`)."""
        if kwargs.pop("minor", False):
            return
        base = self._y2_of or self
        key = "y2" if self._y2_of is not None else "y"
        host = base._shared_ticker_source(key)
        props = host._axis[key]
        if ticks is not None:
            spec = host._scale_specs[key]
            host._auto_scale_axis_ticks.discard(key)
            host._tickers.pop((key, "major_locator"), None)
            props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
            props["tick_count"] = max(1, len(props["tick_values"]))
            self._expand_domain_to_ticks("y")
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
            host._tickers.pop((key, "major_formatter"), None)
        if rotation is not None:
            self._axis_props("y")["tick_label_angle"] = float(rotation)
        host._invalidate_shared_ticker_axis(key)

    def _expand_domain_to_ticks(self, axis: str) -> None:
        """Apply Matplotlib's mandatory view expansion for explicit ticks."""
        host = self._y2_of or self
        key = "y2" if axis == "y" and self._y2_of is not None else axis
        props = self._axis_props(axis)
        ticks = np.asarray(props.get("tick_values", []), dtype=np.float64)
        ticks = ticks[np.isfinite(ticks)]
        if not len(ticks):
            return
        if axis in self._explicit_domains:
            domain = props.get("domain", self._auto_domain(axis))
        else:
            domain = self._auto_domain(axis)
            host._tick_expanded_domains.add(key)
        lo, hi = sorted(map(float, domain))
        props["domain"] = (min(lo, float(ticks.min())), max(hi, float(ticks.max())))
        self._invalidate()

    def _set_ticklabels(
        self,
        axis: str,
        labels: Sequence[str],
        *,
        minor: bool,
        fontdict: dict[str, Any] | None,
        kwargs: dict[str, Any],
    ) -> list[_TickLabel]:
        if minor:
            # Minor ticks are outside the native axis contract.
            return []
        if fontdict is not None and not isinstance(fontdict, dict):
            raise TypeError("fontdict must be a dict or None")
        options = {} if fontdict is None else dict(fontdict)
        options.update(kwargs)
        texts = [_plain_text(value) for value in labels]
        props = self._axis_props(axis)
        current_ticks = self._computed_ticks(axis, False)
        fixed_ticks = props.get("tick_values")
        if fixed_ticks is not None and texts and len(texts) != len(fixed_ticks):
            raise ValueError(
                f"The number of FixedLocator locations ({len(fixed_ticks)}) does not match "
                f"the number of labels ({len(texts)})."
            )
        if not texts:
            # FixedFormatter([]) yields one empty Text per current tick. The
            # native equivalent hides labels while preserving tick positions.
            props.pop("tick_labels", None)
            props["tick_label_strategy"] = "off"
            handles = [_TickLabel(self, axis, "") for _ in current_ticks]
        else:
            rendered = list(texts[: len(current_ticks)])
            rendered.extend("" for _ in range(len(current_ticks) - len(rendered)))
            setter = self.set_xticks if axis == "x" else self.set_yticks
            setter(current_ticks, rendered)
            props["tick_label_strategy"] = None
            handles = [_TickLabel(self, axis, text) for text in rendered]

        color = options.pop("color", options.pop("c", None))
        size = options.pop("fontsize", options.pop("size", None))
        rotation = options.pop("rotation", None)
        rotation_mode = options.pop("labelrotation_mode", options.pop("rotation_mode", None))
        alignment = options.pop("horizontalalignment", options.pop("ha", None))
        # These Text properties have no independent axis-wide native chrome
        # representation, but accepting them preserves Matplotlib's static
        # gallery call surface.
        _pop_text_style_kwargs(options, f"set_{axis}ticklabels()")
        style = props.setdefault("style", {})
        if color is not None:
            style["tick_label_color"] = resolve_color(color)
        if size is not None:
            dpi = float(
                self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"]
            )
            style["tick_label_size"] = _font_size(size, rcParams["font.size"], dpi)
        if rotation is not None:
            props["tick_label_angle"] = float(rotation)
        if rotation_mode is not None:
            self._set_tick_rotation_mode(axis, rotation_mode)
        elif rotation is not None:
            self._apply_tick_rotation_mode(axis, float(rotation))
        if alignment is not None:
            anchors = {
                "left": "start",
                "center": "center",
                "right": "end",
                "start": "start",
                "end": "end",
            }
            if alignment not in anchors:
                raise ValueError("horizontalalignment must be 'left', 'center', or 'right'")
            props["tick_label_anchor"] = anchors[alignment]
        self._invalidate()
        return handles

    def set_xticklabels(
        self,
        labels: Sequence[str],
        *,
        minor: bool = False,
        fontdict: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[_TickLabel]:
        """Set x tick labels without changing the current tick locations."""
        return self._set_ticklabels("x", labels, minor=minor, fontdict=fontdict, kwargs=kwargs)

    def set_yticklabels(
        self,
        labels: Sequence[str],
        *,
        minor: bool = False,
        fontdict: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[_TickLabel]:
        """Set y tick labels without changing the current tick locations."""
        return self._set_ticklabels("y", labels, minor=minor, fontdict=fontdict, kwargs=kwargs)

    def get_xticks(self, *, minor: bool = False) -> np.ndarray:
        """The x tick positions in data space.

        Explicit ticks return as set; auto-ticked axes report the same nice
        locations the exporters draw. ``minor=True`` returns the minor ticks
        (usually empty).
        """
        return self._computed_ticks("x", minor)

    def get_yticks(self, *, minor: bool = False) -> np.ndarray:
        """The y tick positions in data space (see `get_xticks`)."""
        return self._computed_ticks("y", minor)

    def _computed_ticks(self, axis: str, minor: bool) -> np.ndarray:
        base = self._y2_of or self
        key = "y2" if axis == "y" and self._y2_of is not None else axis
        host = base._shared_ticker_source(key)
        props = host._axis[key]
        if minor:
            key = "y2" if axis == "y" and self._y2_of is not None else axis
            return np.asarray(
                _scale_values(
                    props.get("minor_tick_values", []),
                    (self._y2_of or self)._scale_specs[key],
                    inverse=True,
                ),
                dtype=float,
            )
        if "tick_values" in props:
            return np.asarray(
                _scale_values(props["tick_values"], host._scale_specs[key], inverse=True),
                dtype=float,
            )
        # Auto-ticked axes report the same nice locations the exporters draw.
        from xy._svg import _linear_ticks, _log_ticks

        lo, hi = sorted(self.get_xlim() if axis == "x" else self.get_ylim())
        if not (np.isfinite(lo) and np.isfinite(hi)) or lo == hi:
            return np.asarray([], dtype=float)
        locator = host._tickers.get((key, "major_locator"))
        if locator is not None:
            ticks = np.asarray(locator.tick_values(lo, hi), dtype=float).reshape(-1)
            pad = (hi - lo) * 1e-9
            return ticks[(ticks >= lo - pad) & (ticks <= hi + pad)]
        if props.get("type_") == "log":
            return np.asarray(_log_ticks(float(lo), float(hi))[0], dtype=float)
        return np.asarray(_linear_ticks(float(lo), float(hi))[0], dtype=float)

    def set_anchor(self, anchor: str | Literal[False]) -> None:
        """Anchor the axes box within its allotted space.

        ``anchor`` is a compass code (``"C"``, ``"SW"``, ``"S"``, ``"SE"``,
        ``"E"``, ``"NE"``, ``"N"``, ``"NW"``, ``"W"``); False clears it.
        """
        if anchor is False:
            self._anchor = None
            self._invalidate()
            return
        normalized = str(anchor).upper()
        if normalized not in {"C", "SW", "S", "SE", "E", "NE", "N", "NW", "W"}:
            raise ValueError(f"unsupported anchor mode {anchor!r}")
        self._anchor = normalized
        self._invalidate()

    def locator_params(self, axis: str = "both", nbins: int | None = None, **kwargs: Any) -> None:
        """Control tick density: ``nbins`` caps the tick count per axis.

        ``axis`` selects ``"x"``/``"y"``/``"both"``; other keywords are
        accepted compat-noops.
        """
        del kwargs
        if nbins is None:
            return
        if axis in ("both", "x"):
            self._axis_props("x")["tick_count"] = max(1, int(nbins))
        if axis in ("both", "y"):
            self._axis_props("y")["tick_count"] = max(1, int(nbins))
        self._invalidate()

    def indicate_inset_zoom(self, inset_ax: "Axes", **kwargs: Any) -> Artist:
        """Draw a rectangle marking ``inset_ax``'s view limits on this axes.

        ``ec``/``edgecolor`` sets the outline color; connector lines are
        not drawn.
        """
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
        """A twin axes sharing this x-axis, with its own right-hand y-axis.

        Repeated calls return the same twin; twinning a twin raises.
        """
        if self._y2_of is not None:
            raise ValueError("twinx() of a twin axes is not supported")
        if self._twin is None:
            self._twin = Axes(self.figure, y2_of=self)
        return self._twin

    def twiny(self) -> "Axes":
        """A new axes sharing this y-axis (matplotlib's `twiny`).

        The twin joins the figure, becomes the current axes, and draws its
        own x-axis.
        """
        if self.figure is None:
            raise ValueError("twiny() requires an Axes attached to a Figure")
        twin = Axes(self.figure)
        twin._axis["y"] = self._axis_props("y")
        self.figure._axes.append(twin)
        self.figure._current_ax = twin
        self.figure._invalidate()
        return twin

    def legend(self, *args: Any, **kwargs: Any) -> Any:
        """Show the legend for this axes.

        Call forms: ``legend()`` (labeled artists), ``legend(labels)``
        (assigned positionally), or ``legend(handles, labels)``. Supported
        keywords: ``loc``, ``ncols``/``ncol``, ``title``, ``fontsize`` (or
        ``prop={"size": ...}``), ``labelcolor``, ``frameon``, ``facecolor``,
        ``edgecolor``, ``framealpha``, ``fancybox``, ``shadow``,
        ``borderpad``, and ``labelspacing``; unsupported layout keywords
        raise loudly. ``reverse=True`` reverses the resolved handle/label
        order. ``loc="best"`` picks the least occupied corner.
        """
        host = self._y2_of or self
        reverse = bool(kwargs.pop("reverse", False))
        if len(args) >= 2:
            handles = list(args[0])
            labels = [_plain_text(label) for label in args[1]]
            if reverse:
                handles.reverse()
                labels.reverse()
            legend_artist = Legend(host, handles, labels, **kwargs)
            host._legend_handle = legend_artist
            # An explicit handles/labels call defines the primary legend even
            # when the handles are proxy artists rather than plotted entries.
            # Freeze those items without renaming the underlying traces:
            # subsequent legend calls and secondary ``add_artist`` legends
            # must remain independent.
            host._legend_options = dict(legend_artist._options)
            if host._extra_legends:
                # Once a prior legend has been retained with add_artist(),
                # keep the replacement primary legend in the same explicit
                # artist layer so both boxes preserve their independent items.
                host._legend_artist = legend_artist
                host._legend_items = None
            else:
                host._legend_artist = None
                host._legend_items = list(legend_artist.spec()["items"])
        elif len(args) == 1:
            # legend(labels): assign labels positionally to the plotted artists,
            # skipping marker overlays that share their line's legend slot.
            labels = args[0]
            eligible = [entry for entry in host._entries if not entry.get("_legend_skip")]
            for entry, label in zip(eligible, labels, strict=False):
                entry.setdefault("kwargs", {})["name"] = _plain_text(label)
            host._legend_artist = None
            host._legend_items = None
            handles, labels = host.get_legend_handles_labels()
            if reverse:
                handles.reverse()
                labels.reverse()
            host._legend_handle = Legend(host, handles, labels, **kwargs)
            host._legend_options = dict(host._legend_handle._options)
            if reverse:
                # Automatic legends ordinarily let the renderer derive items
                # from trace order. Freeze the reversed result so this call's
                # explicit ordering survives materialization.
                host._legend_items = list(host._legend_handle.spec()["items"])
        else:
            host._legend_artist = None
            host._legend_items = None
            handles, labels = host.get_legend_handles_labels()
            if reverse:
                handles.reverse()
                labels.reverse()
            host._legend_handle = Legend(host, handles, labels, **kwargs)
            host._legend_options = dict(host._legend_handle._options)
            if reverse:
                host._legend_items = list(host._legend_handle.spec()["items"])
        host._legend = True
        host._invalidate()
        return host._legend_handle

    def _compose_legend_options(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Translate legend() keyword styling into the engine's option dict.

        Shared by ``Axes.legend`` and the standalone ``Legend`` artist so a
        second, manually added legend honors the same loc/frame/font keywords.
        """
        loc = kwargs.pop("loc", rcParams["legend.loc"])
        if not isinstance(loc, str) or loc not in {"best", *_LEGEND_LOC_ANCHORS}:
            raise ValueError(f"legend loc must be one of {['best', *sorted(_LEGEND_LOC_ANCHORS)]}")
        bbox_to_anchor = kwargs.pop("bbox_to_anchor", None)
        if bbox_to_anchor is not None:
            bounds = getattr(bbox_to_anchor, "bounds", bbox_to_anchor)
            if isinstance(bounds, (str, bytes)) or len(bounds) not in (2, 4):
                raise ValueError("legend bbox_to_anchor must contain 2 or 4 finite numbers")
            bbox_to_anchor = tuple(float(value) for value in bounds)
            if not all(np.isfinite(value) for value in bbox_to_anchor):
                raise ValueError("legend bbox_to_anchor must contain 2 or 4 finite numbers")
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
        framealpha = kwargs.pop("framealpha", rcParams["legend.framealpha"])
        fancybox = kwargs.pop("fancybox", False)
        shadow = kwargs.pop("shadow", False)
        borderpad = kwargs.pop("borderpad", rcParams["legend.borderpad"])
        labelspacing = kwargs.pop("labelspacing", rcParams["legend.labelspacing"])
        borderaxespad = kwargs.pop("borderaxespad", rcParams["legend.borderaxespad"])
        handleheight = kwargs.pop("handleheight", None)
        handlelength = kwargs.pop("handlelength", rcParams["legend.handlelength"])
        handletextpad = kwargs.pop("handletextpad", rcParams["legend.handletextpad"])
        # Remaining title geometry is not expressible yet and stays loud; the
        # frame, handle, and row-layout options above map directly to CSS and
        # the static exporters.
        layout_options = {key: kwargs.pop(key) for key in ("title_fontsize",) if key in kwargs}
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
        font_px = _font_size(fontsize, rcParams["font.size"], self._point_scale() * 72.0)
        style: dict[str, Any] = {}
        if fontsize is not None:
            style["fontSize"] = f"{font_px:g}px"
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
                style["borderWidth"] = "1px"
        if framealpha is not None:
            alpha_value = float(framealpha)
            if not 0.0 <= alpha_value <= 1.0:
                raise ValueError("legend framealpha must be between 0 and 1")
            style["--xy-legend-frame-alpha"] = alpha_value
        if bool(fancybox):
            style["borderRadius"] = "4px"
        if bool(shadow):
            style["boxShadow"] = "2px 2px 4px rgba(0,0,0,0.3)"
        padding = float(borderpad)
        if padding < 0:
            raise ValueError("legend borderpad must be non-negative")
        style["padding"] = f"{padding:g}em"
        spacing = float(labelspacing)
        if spacing < 0:
            raise ValueError("legend labelspacing must be non-negative")
        style["rowGap"] = f"{spacing:g}em"
        axes_padding = float(borderaxespad)
        if axes_padding < 0:
            raise ValueError("legend borderaxespad must be non-negative")
        options: dict[str, Any] = {
            "loc": loc,
            "ncols": max(1, int(ncols)),
            # Matplotlib measures borderaxespad in legend-font em. The wire
            # carries pixels so all three renderers place anchored legends at
            # the same physical distance from the axes.
            "border_pad": axes_padding * font_px,
        }
        if bbox_to_anchor is not None:
            options["anchor"] = bbox_to_anchor
        if handleheight is not None:
            handleheight_value = float(handleheight)
            if not np.isfinite(handleheight_value) or handleheight_value <= 0:
                raise ValueError("legend handleheight must be a positive finite number")
            options["handleheight"] = handleheight_value
        handlelength_value = float(handlelength)
        if not np.isfinite(handlelength_value) or handlelength_value < 0:
            raise ValueError("legend handlelength must be a non-negative finite number")
        options["handlelength"] = handlelength_value
        handletextpad_value = float(handletextpad)
        if not np.isfinite(handletextpad_value) or handletextpad_value < 0:
            raise ValueError("legend handletextpad must be a non-negative finite number")
        options["handletextpad"] = handletextpad_value
        if title is not None:
            options["title"] = _plain_text(title)
        if style:
            options["style"] = style
        return options

    def grid(self, visible: bool | None = True, **kwargs: Any) -> None:
        """Toggle and style the grid.

        ``visible=None`` toggles the current state; ``which`` accepts
        ``"major"``/``"both"`` and ``axis`` restricts to ``"x"`` or ``"y"``.
        ``color``/``c``,
        ``linestyle``/``ls``, ``linewidth``/``lw``, and ``alpha`` style the
        lines; anything else raises loudly.
        """
        host = self._y2_of or self
        which = str(kwargs.pop("which", "major")).lower()
        axis = kwargs.pop("axis", "both")
        if which not in {"major", "minor", "both"}:
            raise ValueError("grid() which must be 'major', 'minor', or 'both'")
        if axis not in {"both", "x", "y"}:
            raise ValueError("grid() axis must be 'both', 'x', or 'y'")
        color = kwargs.pop("color", kwargs.pop("c", None))
        linestyle = kwargs.pop("linestyle", kwargs.pop("ls", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", None))
        alpha = kwargs.pop("alpha", None)
        if kwargs:
            raise TypeError(f"grid() got unsupported keyword argument {next(iter(kwargs))!r}")
        has_style = any(value is not None for value in (color, linestyle, linewidth, alpha))
        if has_style and visible is None:
            visible = True
        selected = ("x", "y") if axis == "both" else (axis,)
        tiers = []
        if which in {"major", "both"}:
            tiers.append((host._grid_axes, "style"))
        if which in {"minor", "both"}:
            tiers.append((host._minor_grid_axes, "minor_style"))
        for states, _style_key in tiers:
            for item in selected:
                states[item] = not states[item] if visible is None else bool(visible)
        host._grid = any(host._grid_axes.values())
        visible_axes = [item for item, enabled in host._grid_axes.items() if enabled]
        host._grid_axis = "both" if len(visible_axes) != 1 else visible_axes[0]
        style: dict[str, Any] = {}
        if which in {"major", "both"}:
            host._grid_style = style
        if color is not None and (resolved_grid := resolve_color(color)) is not None:
            if which in {"major", "both"}:
                host._grid_color = resolved_grid
            style["grid_color"] = resolved_grid
        if linewidth is not None:
            style["grid_width"] = float(linewidth)
        if linestyle is not None:
            dash = LINESTYLE_TO_DASH.get(linestyle, linestyle)
            if dash is not None:  # solid is the engine default, not a style key
                style["grid_dash"] = dash
        if alpha is not None:
            style["grid_opacity"] = float(alpha)
        stale_style_keys = []
        if linewidth is not None:
            stale_style_keys.append("grid_width")
        if linestyle is not None:
            stale_style_keys.append("grid_dash")
        if alpha is not None:
            stale_style_keys.append("grid_opacity")
        for item in ("x", "y"):
            props = host._axis_props(item)
            for states, style_key in tiers:
                axis_style = props.setdefault(style_key, {})
                if item in selected:
                    for stale in stale_style_keys:
                        axis_style.pop(stale, None)
                    fallback = (
                        host._grid_color
                        if style_key == "style"
                        else resolve_color(rcParams["grid.color"])
                    )
                    axis_style.update(style)
                    axis_style["grid_color"] = (
                        axis_style.get("grid_color", fallback) if states[item] else "transparent"
                    )
                else:
                    axis_style.setdefault("grid_color", "transparent")
        host._invalidate()

    def _axis_props(self, axis: str) -> dict[str, Any]:
        host = self._y2_of or self
        key = "y2" if (axis == "y" and self._y2_of is not None) else axis
        return host._axis[key]

    def _shared_ticker_source(self, key: str) -> "Axes":
        """Axis whose locator/formatter and authored ticks this panel uses."""
        if key == "y2":
            return self
        return self._shared_axis_sources.get(key, self)

    def _invalidate_shared_ticker_axis(self, key: str) -> None:
        """Drop every chart cache that consumes one shared ticker container."""
        source = self._shared_ticker_source(key)
        figure = source.figure
        if figure is None:
            source._chart = None
            return
        for ax in figure._axes:
            if ax._shared_ticker_source(key) is source:
                ax._chart = None
        figure._invalidate()

    def _inherit_shared_axis_state(self, axis: str, props: dict[str, Any]) -> None:
        """Overlay the shared Axis state while retaining local tick visibility."""
        source = self._shared_ticker_source(axis)
        if source is self:
            return
        source_props = source._axis[axis]
        for name in (
            "domain",
            "reverse",
            "tick_values",
            "tick_labels",
            "tick_count",
            "minor_tick_values",
        ):
            if name in source_props:
                props[name] = source_props[name]

    def _has_explicit_shared_domain(self, axis: str) -> bool:
        return axis in self._shared_ticker_source(axis)._explicit_domains

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
        from ._ticker import LogLocator

        ticker_source = self._shared_ticker_source(key)
        locator = ticker_source._tickers.get((key, "major_locator"))
        formatter = ticker_source._tickers.get((key, "major_formatter"))
        minor_locator = ticker_source._tickers.get((key, "minor_locator"))
        minor_formatter = ticker_source._tickers.get((key, "minor_formatter"))
        # Core's minor tier is deliberately unlabeled. When a script blanks
        # the majors and labels located minors (Matplotlib's centered-date
        # idiom), promote that pair to the labeled tier.
        promoted_minor = (
            _is_null_formatter(formatter)
            and minor_locator is not None
            and minor_formatter is not None
            and not _is_null_formatter(minor_formatter)
        )
        if promoted_minor:
            locator, formatter = minor_locator, minor_formatter
        is_log = (
            props.get("type_") == "log" or (self._scale_specs.get(key) or {}).get("name") == "log"
        )
        if locator is None and formatter is None and minor_locator is None and not is_log:
            return
        spec = self._scale_specs.get(key) or {"name": "linear"}
        authored_labels = list(props["tick_labels"]) if "tick_labels" in props else None
        lo, hi = self._ticker_view(key, props)
        auto_log = False
        if locator is not None:
            if isinstance(locator, Locator):
                # Third-party locators only promise tick_values(); the density
                # hint is an xy-locator protocol, never forced onto them.
                locator._nbins_hint = nbins_hint
            ticks = _locator_tick_values(
                locator,
                lo,
                hi,
                datetime_axis=self._axis_holds_datetimes("y" if key == "y2" else key),
            )
            pad = (hi - lo) * 1e-9
            ticks = ticks[(ticks >= lo - pad) & (ticks <= hi + pad)]
        elif "tick_values" in props:
            ticks = np.asarray(
                _scale_values(props["tick_values"], spec, inverse=True), dtype=float
            ).reshape(-1)
        else:
            auto = LogLocator(base=float(spec.get("base", 10.0))) if is_log else AutoLocator()
            auto._nbins_hint = nbins_hint
            ticks = np.asarray(auto.tick_values(lo, hi), dtype=float).reshape(-1)
            if not is_log:
                pad = (hi - lo) * 1e-9
                ticks = ticks[(ticks >= lo - pad) & (ticks <= hi + pad)]
            auto_log = is_log
        props["tick_values"] = list(map(float, _scale_values(ticks, spec)))
        if formatter is not None:
            props["tick_labels"] = _formatter_tick_labels(
                formatter,
                ticks,
                datetime_axis=self._axis_holds_datetimes("y" if key == "y2" else key),
            )
        elif auto_log:
            # matplotlib's LogFormatter look: decades label as 10^k.
            props["tick_labels"] = [
                _pow_label(value, float(spec.get("base", 10.0))) for value in ticks
            ]
        elif authored_labels is not None:
            props["tick_labels"] = authored_labels
        elif spec.get("name") != "linear":
            props["tick_labels"] = [f"{value:g}" for value in ticks]
        else:
            props.pop("tick_labels", None)
        if len(ticks):
            props["tick_count"] = len(ticks)
        else:
            props.pop("tick_count", None)
        if promoted_minor:
            props.pop("minor_tick_values", None)
            props["style"] = {
                **(props.get("style") or {}),
                **(props.get("minor_style") or {}),
            }
            return

        # PR #336 owns the independent minor wire tier and the automatic log
        # subdivisions. This shim layer adds AutoMinorLocator and foreign-date
        # adaptation on top of that core contract.
        if is_log and minor_locator is None:
            minor_locator = LogLocator(base=float(spec.get("base", 10.0)), subs=spec.get("subs"))
        if minor_locator is None:
            props.pop("minor_tick_values", None)
            return
        minor = _minor_locator_tick_values(
            minor_locator,
            lo,
            hi,
            ticks,
            datetime_axis=self._axis_holds_datetimes("y" if key == "y2" else key),
        )
        pad = (hi - lo) * 1e-9
        minor = minor[(minor >= lo - pad) & (minor <= hi + pad)]
        if len(ticks) and len(minor):
            minor = minor[
                ~np.isclose(minor[:, None], ticks[None, :], rtol=1e-12, atol=0.0).any(axis=1)
            ]
        props["minor_tick_values"] = list(map(float, _scale_values(minor, spec)))

    # -- materialization -----------------------------------------------------------

    def _axline_data(self, entry: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        """Resolve deferred axline point transforms and clip to the final view."""
        shared_view = getattr(self, "_shared_render_domains", {})
        xlim = shared_view["x"] if "x" in shared_view else self.get_xlim()
        ylim = shared_view["y"] if "y" in shared_view else self.get_ylim()
        xy1 = entry["xy1"]
        xy2 = entry.get("xy2")
        if entry.get("transform_space") == "axes_fraction":
            xy1 = (
                xlim[0] + float(xy1[0]) * (xlim[1] - xlim[0]),
                ylim[0] + float(xy1[1]) * (ylim[1] - ylim[0]),
            )
            if xy2 is not None:
                xy2 = (
                    xlim[0] + float(xy2[0]) * (xlim[1] - xlim[0]),
                    ylim[0] + float(xy2[1]) * (ylim[1] - ylim[0]),
                )
        if xy2 is not None:
            direction = (float(xy2[0]) - float(xy1[0]), float(xy2[1]) - float(xy1[1]))
        else:
            slope = float(entry["slope"])
            direction = (0.0, 1.0) if np.isinf(slope) else (1.0, slope)
        return _clip_infinite_line(xy1, direction, xlim, ylim)

    def _chart_children(
        self,
        *,
        resolved_domains: Optional[Mapping[str, tuple[float, float]]] = None,
    ) -> list[Any]:
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
                # Every renderer already uses round caps for dashed lines.
                # ``Line2D.set_dash_capstyle("round")`` records the public
                # Matplotlib state, but it is not a core ``xy.line`` keyword.
                kw.pop("dash_capstyle", None)
                gapcolor = kw.pop("_gapcolor", None)
                if gapcolor is not None and kw.get("dash"):
                    children.append(
                        xy.line(
                            x=e["x"],
                            y=e["y"],
                            color=gapcolor,
                            width=kw["width"],
                            opacity=kw.get("opacity", 1.0),
                            **axis_kw,
                        )
                    )
                children.append(xy.line(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "@axline":
                kw = dict(kw)
                kw["width"] = (
                    float(kw.get("width", rcParams["lines.linewidth"])) * self._point_scale()
                )
                kw.pop("dash_capstyle", None)
                gapcolor = kw.pop("_gapcolor", None)
                x, y = self._axline_data(e)
                if not len(x):
                    # A transformed infinite line can miss the current view
                    # entirely. Matplotlib clips it to no visible geometry;
                    # do not emit an empty line component that static SVG
                    # would later try to convert into a path.
                    continue
                if gapcolor is not None and kw.get("dash"):
                    children.append(
                        xy.line(
                            x=x,
                            y=y,
                            color=gapcolor,
                            width=kw["width"],
                            opacity=kw.get("opacity", 1.0),
                            **axis_kw,
                        )
                    )
                children.append(xy.line(x=x, y=y, **kw, **axis_kw))
            elif kind == "scatter":
                kw = dict(kw)
                if "_mpl_line_marker_path_points" in e:
                    stroke_points = float(e["_mpl_line_marker_stroke_points"])
                    kw["stroke_width"] = stroke_points * self._point_scale()
                    kw["size"] = (
                        float(e["_mpl_line_marker_path_points"]) + stroke_points
                    ) * self._point_scale()
                if np.isscalar(kw.get("size")):
                    # The core keeps scatter size as a channel rather than a
                    # mark style. Opt this pyplot trace into carrying that
                    # constant through automatic legend-item derivation.
                    kw["_legend_trace_size"] = True
                if "_artist_alpha" in kw:
                    # pyplot alpha overrides intrinsic RGBA. Core opacity is
                    # an independent multiplier, so do not apply it twice.
                    kw["opacity"] = 1.0
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
                children.append(xy.scatter(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "bar":
                children.append(xy.bar(x=e["x"], y=e["y"], **kw, **axis_kw))
                patch_labels = e.get("patch_labels")
                if patch_labels is not None:
                    colors = resolve_rgba_array(
                        kw.get("color", "transparent"),
                        len(patch_labels),
                        "bar legend color",
                    )
                    orientation = kw.get("orientation", "vertical")
                    for index, label in enumerate(patch_labels):
                        if not label or str(label).startswith("_"):
                            continue
                        # Named zero-mark proxies give the core legend one
                        # correctly colored swatch per labeled patch while the
                        # actual bars remain a single vectorized trace.
                        children.append(
                            xy.bar(
                                x=np.empty(0, dtype=np.float64),
                                y=np.empty(0, dtype=np.float64),
                                name=str(label),
                                color=resolve_color(colors[index]),
                                opacity=1.0,
                                orientation=orientation,
                                **axis_kw,
                            )
                        )
            elif kind == "area":
                children.append(xy.area(x=e["x"], y=e["y"], **kw, **axis_kw))
            elif kind == "histogram":
                children.append(xy.histogram(values=e["values"], **kw, **axis_kw))
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
                children.append(xy.heatmap(z=z, **kw, **axis_kw))
            elif kind == "@mark":
                if e["factory"] == "step":
                    kw = dict(kw)
                    # ``Line2D.set_dash_capstyle()`` mutates the deferred
                    # pyplot entry, but core ``xy.step`` has fixed round caps
                    # and does not accept the Matplotlib-only keyword.
                    kw.pop("dash_capstyle", None)
                children.append(getattr(xy, e["factory"])(*e["args"], **kw, **axis_kw))
            elif kind == "@table_cell":
                geometry = e["table_geometry"]
                plot_width, plot_height = getattr(
                    self, "_materialize_plot_px", _DEFAULT_BEST_PLOT_SIZE
                )
                point_scale = self._point_scale()
                font_points = _font_size_points(
                    (kw.get("style") or {}).get("font_size", rcParams["font.size"]),
                    rcParams["font.size"],
                )
                font_px = font_points * point_scale
                x1 = float(geometry["x1"])
                dynamic_width = geometry.get("dynamic_width_points")
                x0 = (
                    x1 - float(dynamic_width) * point_scale / plot_width
                    if dynamic_width is not None
                    else float(geometry["x0"])
                )
                row_height = geometry.get("row_height_points")
                if row_height is not None:
                    height_fraction = float(row_height) * point_scale / plot_height
                    y1 = -float(geometry["row_from_top"]) * height_fraction
                    y0 = y1 - height_fraction
                else:
                    y0, y1 = float(geometry["y0"]), float(geometry["y1"])
                center_x, center_y = (x0 + x1) * 0.5, (y0 + y1) * 0.5
                cell_width_px = max(1.0, (x1 - x0) * plot_width)
                cell_height_px = max(1.0, (y1 - y0) * plot_height)
                # One transparent space supplies a DOM/SVG/native label box;
                # pixel padding expands it to the exact axes-fraction cell.
                # The visible text is a separate annotation so its left/right
                # anchor is independent of the cell background.
                space_width_px = font_px * 0.32
                box_style: dict[str, Any] = {
                    "coordinate_space": "axes_fraction",
                    "vertical_align": "center",
                    "font_size": font_px,
                    "label_color": "transparent",
                    "background": geometry["facecolor"],
                    "padding": (
                        f"{max(0.0, (cell_height_px - font_px) * 0.5):.4g}px "
                        f"{max(0.0, (cell_width_px - space_width_px) * 0.5):.4g}px"
                    ),
                }
                if geometry.get("border"):
                    box_style["border"] = geometry["border"]
                children.append(
                    xy.text(
                        center_x,
                        center_y,
                        " ",
                        dx=0.0,
                        dy=0.0,
                        anchor="middle",
                        class_name="xy-mpl-table-cell",
                        style=box_style,
                    )
                )
                anchor = kw.get("anchor", "middle")
                inset = min((x1 - x0) * 0.08, 3.0 / plot_width)
                text_x = (
                    x0 + inset if anchor == "start" else x1 - inset if anchor == "end" else center_x
                )
                text_style = {
                    **(kw.get("style") or {}),
                    "coordinate_space": "axes_fraction",
                    "vertical_align": "center",
                    "font_size": font_px,
                    "label_color": kw.get("color")
                    or resolve_color(rcParams.get("text.color", "black"))
                    or "black",
                }
                children.append(
                    xy.text(
                        text_x,
                        center_y,
                        str(e["args"][2]),
                        dx=0.0,
                        dy=0.0,
                        color=kw.get("color"),
                        anchor=anchor,
                        class_name="xy-mpl-table-cell",
                        style=text_style,
                    )
                )
            elif kind == "@hline":
                children.append(xy.hline(*e["args"], **kw))
                if e.get("endpoint_marker"):
                    x_domain = (
                        (resolved_domains or {}).get("x")
                        or self._axis_props("x").get("domain")
                        or self._auto_domain("x")
                    )
                    span = kw.get("style") or {}
                    start = float(span.get("span_start", 0.0))
                    end = float(span.get("span_end", 1.0))
                    x0, x1 = map(float, x_domain)
                    children.append(
                        xy.scatter(
                            x=[x0 + start * (x1 - x0), x0 + end * (x1 - x0)],
                            y=[float(e["args"][0]), float(e["args"][0])],
                            **e["endpoint_marker"],
                        )
                    )
            elif kind == "@arrow":
                children.append(xy.arrow(*e["args"], **kw))
            elif kind == "@vline":
                children.append(xy.vline(*e["args"], **kw))
                if e.get("endpoint_marker"):
                    y_domain = (
                        (resolved_domains or {}).get("y")
                        or self._axis_props("y").get("domain")
                        or self._auto_domain("y")
                    )
                    span = kw.get("style") or {}
                    start = float(span.get("span_start", 0.0))
                    end = float(span.get("span_end", 1.0))
                    y0, y1 = map(float, y_domain)
                    children.append(
                        xy.scatter(
                            x=[float(e["args"][0]), float(e["args"][0])],
                            y=[y0 + start * (y1 - y0), y0 + end * (y1 - y0)],
                            **e["endpoint_marker"],
                        )
                    )
            elif kind == "@x_band":
                children.append(xy.x_band(*e["args"], **kw))
            elif kind == "@y_band":
                children.append(xy.y_band(*e["args"], **kw))
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
                            point_scale=self._point_scale(),
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
                # "dx" in kw (not text_kw, which defaults it) marks offset
                # placement. An empty dict or empty label still draws the
                # arrow patch in matplotlib, so neither gates the callout.
                if arrowprops is not None and "dx" in kw:
                    # Offset-placed annotate(arrowprops=): matplotlib pins the
                    # arrow from the text to the data point across zoom — the
                    # engine's callout annotation is exactly that object.
                    font_size = float((text_kw.get("style") or {}).get("font_size", 11.0))
                    arrow_color, arrow_width, arrow_style = _arrow_visuals(
                        arrowprops, mutation_scale=font_size
                    )
                    style: dict[str, Any] = {**(text_kw.get("style") or {}), **arrow_style}
                    # matplotlib draws the arrow from the text patch center,
                    # clipped at the patch edge (shrinkA/B default 2 pt):
                    # start_offset + label_clear are that attach model; the
                    # small radial gap floor covers the label-less case.
                    attach = _label_attach_styles(
                        value,
                        font_size,
                        text_kw.get("anchor", "start"),
                        (text_kw.get("style") or {}).get("vertical_align"),
                        bbox=bool(kw.get("bbox")),
                    )
                    for key, spec_value in (attach or {}).items():
                        style.setdefault(key, spec_value)
                    style.setdefault("gap_start", 2.8)
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
                        xy.callout(
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
                    # matplotlib paints Text with rcParams["text.color"]
                    # (black by default). The engine's own annotation-label
                    # fallback is a design token that differs per renderer
                    # (SVG #667085, native rgba(32,32,32,.85), browser
                    # --chart-annotation-text), so an uncoloured pyplot label
                    # renders grey in the exporters. Pin matplotlib's default
                    # here — the same thing the callout branch above already
                    # does — so all three renderers agree without moving the
                    # engine's non-pyplot defaults.
                    text_kw["style"] = {
                        "label_color": text_kw.get("color")
                        or resolve_color(rcParams.get("text.color", "black"))
                        or "black",
                        **(text_kw.get("style") or {}),
                    }
                    children.append(xy.text(x, y, *e["args"][2:], **text_kw))
        return children

    def _apply_legend_handle_styles(
        self,
        core_figure: Any,
        claimed_trace_ids: Optional[builtins.set[int]] = None,
    ) -> builtins.set[int]:
        """Attach Matplotlib-only handle paint to automatic legend traces.

        Plot markers and dash gap colors are separate XY marks so the data
        renderer can stay compact, but Matplotlib's ``HandlerLine2D`` combines
        them into one legend handle. Match each named source entry to its
        materialized trace and retain that handle-only state without changing
        the plotted geometry or replacing the automatic interactive legend.
        """
        from ._artists import _legend_marker_style

        claimed = set() if claimed_trace_ids is None else claimed_trace_ids
        traces = list(core_figure.traces)
        line_factories = {"segments", "step", "stairs", "errorbar"}
        for index, entry in enumerate(self._entries):
            kwargs = entry.get("kwargs") or {}
            name = kwargs.get("name")
            if not name or str(name).startswith("_"):
                continue
            kind = entry.get("kind")
            if kind in {"line", "@axline"}:
                trace_kind = "line"
            elif kind == "@mark" and entry.get("factory") in line_factories:
                trace_kind = str(entry["factory"])
            else:
                continue
            target = next(
                (
                    trace
                    for trace in traces
                    if trace.id not in claimed
                    and trace.kind == trace_kind
                    and trace.name == str(name)
                ),
                None,
            )
            if target is None:
                continue
            claimed.add(target.id)
            gap_color = kwargs.get("_gapcolor")
            if isinstance(gap_color, str):
                target.style["legend_gap_color"] = gap_color
            if index + 1 >= len(self._entries):
                continue
            marker_entry = self._entries[index + 1]
            if marker_entry.get("kind") != "scatter" or not marker_entry.get("_legend_skip"):
                continue
            target.style["legend_marker"] = _legend_marker_style(marker_entry)
        return claimed

    def _plot_rect_px(
        self,
        width: int,
        height: int,
        padding: Optional[Sequence[float]] = None,
        x_side: Optional[str] = None,
    ) -> tuple[float, float]:
        """Estimated ``(w, h)`` of the plot box in pixels.

        Both the tick-space heuristic and ``best`` legend placement have to know
        how large the plot box will be, and both run before the chart exists, so
        they share this one padding model instead of estimating it twice.
        """
        compact = width < 520
        if padding is None:
            top, right, bottom, left = (
                (6.0, 8.0, 36.0, 46.0) if compact else (10.0, 14.0, 42.0, 62.0)
            )
        else:
            top, right, bottom, left = map(float, padding)
        top += self._title_room(compact)
        if x_side == "top":
            top += 26.0 if compact else 32.0
        return (
            max(40.0, float(width) - left - right),
            max(40.0, float(height) - top - bottom),
        )

    def _displayed_ranges(
        self,
        figure: Any,
        x_props: dict[str, Any],
        y_props: dict[str, Any],
    ) -> tuple[Optional[tuple[float, float]], Optional[tuple[float, float]]]:
        """The x/y view the built figure will actually render.

        ``best`` placement has to score against the *displayed* limits, not the
        raw data extent: an autoranged view is padded by the engine, so the
        corner a mark reaches on screen is not the corner it reaches in data
        space. The built figure already knows both (an explicit domain is
        returned verbatim), so ask it rather than re-deriving the padding.
        """
        try:
            return tuple(figure.x_range()), tuple(figure.y_range())  # type: ignore[return-value]
        except (ValueError, TypeError):
            # A log axis with no positive value cannot report a range; the
            # declared domains are the best available fallback.
            return x_props.get("domain"), y_props.get("domain")

    @staticmethod
    def _displayed_plot_size(
        figure: Any,
        displayed_ranges: tuple[Optional[tuple[float, float]], Optional[tuple[float, float]]],
    ) -> tuple[float, float]:
        """The plot rectangle the static/browser layout model will display.

        Legend placement runs after the core figure exists, so estimating this
        from a second list of default paddings is both unnecessary and wrong
        once titles, anchored legends, measured gutters, or an explicit axes
        rectangle alter the frame. Ask the same layout function used by the
        static exporters instead. The browser consumes the same resolved
        ``spec.padding`` contract.
        """
        from .._svg import layout

        known_ranges = {"x": displayed_ranges[0], "y": displayed_ranges[1]}
        axis_specs = {
            axis_id: figure._axis_spec(
                axis_id,
                known_ranges.get(axis_id) or figure._range(axis_id),
            )
            for axis_id in figure.axis_options
        }
        spec = {
            "width": figure.width,
            "height": figure.height,
            "title": figure.title,
            "title_options": figure.title_options,
            "x_axis": axis_specs["x"],
            "y_axis": axis_specs["y"],
            "axes": axis_specs,
        }
        if figure.padding is not None:
            spec["padding"] = list(figure.padding)
        if figure.colorbar_options:
            spec["colorbar"] = figure.colorbar_options
        *_, plot = layout(spec)
        return float(plot["w"]), float(plot["h"])

    def _legend_footprint(
        self,
        legend_options: Optional[dict[str, Any]],
        items: Optional[list[dict[str, Any]]],
        plot_size: tuple[float, float],
    ) -> tuple[float, float, float, float]:
        """Measured legend box and border inset, as fractions of the plot box.

        Returns ``(box_w, box_h, pad_x, pad_y)``. The box comes from
        ``_svg._legend_layout`` — the *same* geometry the SVG and raster
        exporters lay the legend out with, derived from the legend font size and
        the real label extents — so ``best`` scores the box that actually gets
        drawn. ``pad_*`` is Matplotlib's ``borderaxespad``, which insets the
        container every candidate is anchored inside.
        """
        from .._svg import _legend_layout

        options = dict(legend_options or {})
        # Size is independent of placement, and placement is exactly what has
        # not been decided yet — drop both keys so the layout's own resolver is
        # never handed the unresolved "best" we are here to replace.
        options.pop("loc", None)
        options.pop("anchor", None)
        if items is None:
            items = [
                {"name": str((entry.get("kwargs") or {}).get("name"))}
                for entry in self._entries
                if (entry.get("kwargs") or {}).get("name")
            ]
        # A legend with no labelled entry still has a frame; measure it as one
        # empty row rather than dividing by zero inside the layout.
        measured = _legend_layout(
            items or [{"name": ""}],
            {"x": 0.0, "y": 0.0, "w": plot_size[0], "h": plot_size[1]},
            options,
        )
        border_pad = max(0.0, float(options.get("border_pad") or 0.0))
        return (
            measured["box_w"] / plot_size[0],
            measured["box_h"] / plot_size[1],
            border_pad / plot_size[0],
            border_pad / plot_size[1],
        )

    def _best_legend_loc(
        self,
        x_domain: Optional[tuple[float, float]] = None,
        y_domain: Optional[tuple[float, float]] = None,
        *,
        legend_options: Optional[dict[str, Any]] = None,
        items: Optional[list[dict[str, Any]]] = None,
        plot_size: tuple[float, float] = _DEFAULT_BEST_PLOT_SIZE,
    ) -> str:
        """Choose the least occupied candidate box, as Matplotlib does.

        Matplotlib's ``Legend._find_best_position`` walks location codes 1..10
        in order, scores each anchored box by how many artist vertices it
        contains, stops at the first box scoring zero, and breaks ties by
        preferring the lower code. The shim has no Artist layout graph, but its
        canonical entry arrays plus the *measured* legend geometry are enough to
        make the same decision.

        The footprint being measured rather than estimated is the whole point:
        a linear guess from row count and label length ran ~3x too wide and ~2x
        too tall, which tainted corners the real legend never reaches and threw
        the choice to a different corner than Matplotlib's. The domains passed
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
        box_w, box_h, pad_x, pad_y = self._legend_footprint(legend_options, items, plot_size)
        # Matplotlib anchors every candidate inside the plot box inset by
        # borderaxespad on all four sides (offsetbox._get_anchored_bbox), so the
        # travel available to the box is the inset span minus the box itself.
        span_x = max(0.0, 1.0 - 2.0 * pad_x - box_w)
        span_y = max(0.0, 1.0 - 2.0 * pad_y - box_h)
        candidates = []
        for name in _BEST_LOC_ORDER:
            hx, vy = _LEGEND_LOC_ANCHORS[name]
            x_lo = pad_x + hx * span_x
            y_lo = pad_y + vy * span_y
            candidates.append((name, x_lo, x_lo + box_w, y_lo, y_lo + box_h))
        scores = {name: 0.0 for name, *_ in candidates}
        entries_used = 0
        x_reverse = bool(self._axis["x"].get("reverse"))
        y_reverse = bool(self._axis["y"].get("reverse"))

        category_maps: dict[str, dict[str, float]] = {}

        def axis_values(values: Any, axis: str) -> np.ndarray:
            """Entry coordinates in the engine's numeric data space."""
            try:
                return np.asarray(unit_converted_values(values), dtype=np.float64).reshape(-1)
            except (TypeError, ValueError):
                array = np.asanyarray(values).reshape(-1)
                if self._axis_holds_datetimes(axis):
                    converted = [self._data_coordinate(value, axis) for value in array]
                    if not all(value is not None for value in converted):
                        raise
                    return np.asarray(converted, dtype=np.float64)
                if not all(isinstance(value, str) for value in array):
                    raise
                mapping = category_maps.setdefault(axis, {})
                for entry in self._entries:
                    key = "x" if axis == "x" else "y"
                    source = entry.get(key)
                    if source is None:
                        continue
                    for value in np.asanyarray(source).reshape(-1):
                        if isinstance(value, str) and value not in mapping:
                            mapping[value] = float(len(mapping))
                return np.asarray([mapping[value] for value in array], dtype=np.float64)

        def normalize(values: Any, axis: str) -> np.ndarray:
            array = axis_values(values, axis)
            lo, hi = (xlo, xhi) if axis == "x" else (ylo, yhi)
            result = (array - lo) / (hi - lo)
            if x_reverse if axis == "x" else y_reverse:
                result = 1.0 - result
            return result

        for entry in self._entries:
            kind = entry.get("kind")
            kwargs = entry.get("kwargs") or {}

            # Matplotlib treats each bar as a Rectangle and counts overlapping
            # rectangle bboxes, not the four corner vertices. Preserve the
            # same distinction: a legend covering the middle of a wide bar
            # must be disqualified even when no rectangle corner lies inside.
            if kind == "bar":
                try:
                    categories = axis_values(
                        entry["x"], "x" if kwargs.get("orientation") != "horizontal" else "y"
                    )
                    values = axis_values(
                        entry["y"], "y" if kwargs.get("orientation") != "horizontal" else "x"
                    )
                    categories, values = np.broadcast_arrays(categories, values)
                    base = np.broadcast_to(
                        np.asarray(kwargs.get("base", 0.0), dtype=np.float64),
                        values.shape,
                    )
                    thickness = np.broadcast_to(
                        np.asarray(kwargs.get("width", 0.8), dtype=np.float64),
                        values.shape,
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if kwargs.get("orientation") == "horizontal":
                    bx0 = normalize(base, "x")
                    bx1 = normalize(base + values, "x")
                    by0 = normalize(categories - thickness / 2.0, "y")
                    by1 = normalize(categories + thickness / 2.0, "y")
                else:
                    bx0 = normalize(categories - thickness / 2.0, "x")
                    bx1 = normalize(categories + thickness / 2.0, "x")
                    by0 = normalize(base, "y")
                    by1 = normalize(base + values, "y")
                rect_x0, rect_x1 = np.minimum(bx0, bx1), np.maximum(bx0, bx1)
                rect_y0, rect_y1 = np.minimum(by0, by1), np.maximum(by0, by1)
                finite = (
                    np.isfinite(rect_x0)
                    & np.isfinite(rect_x1)
                    & np.isfinite(rect_y0)
                    & np.isfinite(rect_y1)
                )
                if not finite.any():
                    continue
                entries_used += 1
                for name, xl, xh, yl, yh in candidates:
                    overlaps = (
                        (rect_x0[finite] < xh)
                        & (rect_x1[finite] > xl)
                        & (rect_y0[finite] < yh)
                        & (rect_y1[finite] > yl)
                    )
                    scores[name] += float(np.count_nonzero(overlaps))
                continue

            x_values, y_values = entry.get("x"), entry.get("y")
            if kind == "@arrow":
                args: tuple[Any, ...] = tuple(entry.get("args") or ())
                if len(args) >= 4:
                    x_values, y_values = (args[0], args[2]), (args[1], args[3])
            elif kind == "@mark" and entry.get("factory") == "stairs":
                # ``xy.stairs`` stores ``(values, edges)``, while Matplotlib's
                # StepPatch contributes the expanded edge/value path to
                # Legend._auto_legend_data(). Feeding the compact arguments to
                # the generic (x, y) path reverses the axes and makes the
                # histogram effectively invisible to ``loc="best"``.
                args = tuple(entry.get("args") or ())
                if len(args) >= 2:
                    try:
                        values = axis_values(args[0], "y")
                        edges = axis_values(args[1], "x")
                    except (TypeError, ValueError):
                        continue
                    if len(edges) != len(values) + 1:
                        continue
                    x_values = np.repeat(edges, 2)[1:-1]
                    y_values = np.repeat(values, 2)
            elif kind == "@mark" and entry.get("factory") == "ecdf":
                # The compact ECDF mark owns only the source observations; the
                # renderer materializes its sorted post-step path. Score that
                # same path so a rising CDF occupies the upper-right region
                # instead of disappearing from best-placement input.
                args = entry.get("args") or ()
                if args:
                    try:
                        values = axis_values(args[0], "x")
                    except (TypeError, ValueError):
                        continue
                    values = np.sort(values[np.isfinite(values)])
                    if not len(values):
                        continue
                    x_values = np.concatenate((values[:1], values))
                    y_values = np.arange(len(values) + 1, dtype=np.float64) / len(values)
            elif kind == "area" and x_values is not None and y_values is not None:
                # PolyCollection contributes the complete closed polygon path:
                # top edge followed by the reversed baseline.
                try:
                    top_x = axis_values(x_values, "x")
                    top_y = axis_values(y_values, "y")
                    top_x, top_y = np.broadcast_arrays(top_x, top_y)
                    base = np.broadcast_to(
                        np.asarray(kwargs.get("base", 0.0), dtype=np.float64),
                        top_y.shape,
                    )
                    x_values = np.concatenate((top_x, top_x[::-1], top_x[:1]))
                    y_values = np.concatenate((top_y, base[::-1], top_y[:1]))
                except (TypeError, ValueError):
                    continue
            if x_values is None or y_values is None:
                args: Any = entry.get("args")
                if args is not None and len(args) >= 2:
                    x_values, y_values = args[0], args[1]
            if x_values is None or y_values is None:
                continue
            try:
                xv, yv = np.broadcast_arrays(
                    axis_values(x_values, "x"),
                    axis_values(y_values, "y"),
                )
            except (TypeError, ValueError):
                continue
            xv, yv = xv.reshape(-1), yv.reshape(-1)
            total = len(xv)
            sampled = total
            sample_budget = _BEST_LOC_SCATTER_SAMPLE if kind == "scatter" else _BEST_LOC_SAMPLE
            if total > sample_budget:
                # Stride down before the finite scan: occupancy scoring is
                # already sampled, so the full-array isfinite pass was pure
                # O(n) per-build cost on large legended series. Sparse finite
                # points can slip between strides on a mostly-NaN series, so
                # a sample with no finite pair falls back to the full array —
                # a series the old full-array pass scored still scores instead
                # of vanishing from placement.
                strided = np.linspace(0, total - 1, sample_budget, dtype=np.intp)
                sampled_x, sampled_y = xv[strided], yv[strided]
                if (np.isfinite(sampled_x) & np.isfinite(sampled_y)).any():
                    xv, yv = sampled_x, sampled_y
                    sampled = sample_budget
            path_xn = (xv - xlo) / (xhi - xlo)
            path_yn = (yv - ylo) / (yhi - ylo)
            if x_reverse:
                path_xn = 1.0 - path_xn
            if y_reverse:
                path_yn = 1.0 - path_yn
            finite = np.flatnonzero(np.isfinite(path_xn) & np.isfinite(path_yn))
            if not len(finite):
                continue
            # Unclipped: a point outside the view is outside every candidate
            # box, exactly as Matplotlib sees it in display space. Clipping used
            # to pin such points onto the nearest edge and count them there.
            xn = path_xn[finite]
            yn = path_yn[finite]
            # Matplotlib's badness is a raw vertex count summed over artists, so
            # a long series legitimately outweighs a short one. Scale a strided
            # series back to its true length to preserve that weighting.
            weight = total / float(sampled)
            entries_used += 1
            inside_counts = [
                int(np.count_nonzero((xn > xl) & (xn < xh) & (yn > yl) & (yn < yh)))
                for _, xl, xh, yl, yh in candidates
            ]
            path_hits = [False] * len(candidates)
            if kind != "scatter":
                # A contained vertex proves the path intersects the box. Run
                # the exact segment test only for edge-only crossings, which
                # keeps dense oscillating lines from solving the same question
                # twice for most candidates.
                unresolved = [index for index, count in enumerate(inside_counts) if not count]
                unresolved_hits = _path_intersects_boxes(
                    path_xn,
                    path_yn,
                    [
                        (
                            candidates[index][1],
                            candidates[index][2],
                            candidates[index][3],
                            candidates[index][4],
                        )
                        for index in unresolved
                    ],
                )
                for index, hit in zip(unresolved, unresolved_hits, strict=True):
                    path_hits[index] = hit
                for index, count in enumerate(inside_counts):
                    if count:
                        path_hits[index] = True
            for (name, *_), inside_count, path_hit in zip(
                candidates,
                inside_counts,
                path_hits,
                strict=True,
            ):
                # Strict, mirroring Bbox.count_contains.
                scores[name] += float(inside_count) * weight
                # ``Line2D``, Patch paths, and PolyCollection paths contribute
                # one additional badness point when a segment crosses the
                # legend even if neither endpoint is contained. Scatter is a
                # Collection and contributes offsets only.
                if path_hit:
                    scores[name] += 1.0
        if not entries_used:
            return "upper right"
        # Matplotlib compares exact integer badness and prefers the lower code
        # on a tie; dict order here *is* that code order, so the first minimum
        # wins. The only slack absorbs the float stride weight above — an
        # unsampled series scores whole numbers and ties exactly, as it must.
        best = min(scores.values())
        return next(name for name, score in scores.items() if score <= best * (1.0 + 1e-9))

    def _outside_padding(self, compact: bool) -> tuple[float, float, float]:
        """The top/right/bottom gutters the renderers reserve *outside* the
        chart's ``padding``.

        `_svg.layout()` and the browser's ``ChartView._layout()`` both add the
        title band, a top-side x axis, the colorbar strip, and the shared
        right-side gutter for a secondary y axis on top of whatever padding the
        spec carries. This is the shim's single mirror of that rule:
        `_frame_padding()` subtracts it so an explicit padding still lands the
        plot rect where Matplotlib puts the axes, the grid compositor adds it to
        the panel it allocates so that subtraction always fits, and the
        equal-aspect solve measures the real plot rect with it.
        """
        top = self._title_room(compact)
        if self._axis["x"].get("side") == "top":
            top += (26.0 if compact else 32.0) + self._x_multiline_extra()
        right = 0.0
        bottom = self._x_multiline_extra() if self._axis["x"].get("side") != "top" else 0.0
        if self._colorbar is not None:
            colorbar_right, colorbar_bottom = self._colorbar_outside_room(compact)
            right += colorbar_right
            bottom += colorbar_bottom
        if self._twin is not None or any(
            secondary._axis == "y" and secondary._side == "right"
            for secondary in self._secondary_axes
        ):
            right += 42.0 if compact else 54.0
        return top, right, bottom

    def _title_room(self, compact: bool) -> float:
        """Maximum top gutter required by the three independent title slots."""
        room = 0.0
        base_style = self._chrome_styles.get("title", {})
        for title in self._titles.values():
            style = {**base_style, **(title.get("style") or {})}
            raw_size = style.get("font-size", 14.0)
            try:
                size = float(str(raw_size).removesuffix("px"))
            except (TypeError, ValueError):
                size = 14.0
            measured = _textblock.measure(title["text"], size).height
            if title.get("automatic_y", True):
                candidate = max(26.0 if compact else 30.0, measured + float(title["pad"]))
            else:
                # Explicit y is an axes-fraction placement. Only reserve the
                # ordinary title block when its anchor is at/above the top.
                # The renderers use the final plot height for the exact
                # fractional offset.
                candidate = max(
                    0.0,
                    measured + float(title["pad"]) if float(title["y"]) >= 1.0 else 0.0,
                )
            room = max(room, candidate)
        return room

    def _x_multiline_extra(self) -> float:
        """Extra cross-axis room beyond the single-line matplotlib gutter."""
        props = self._axis["x"]
        style = props.get("style") or {}
        size = float(style.get("tick_label_size", style.get("tick_size", 11.0)))
        labels = props.get("tick_labels") or ()
        angle = float(props.get("tick_label_angle", 0.0))
        extra = 0.0
        for label in labels:
            lines = _textblock.split_lines(label)
            if len(lines) == 1:
                continue
            block = _textblock.measure(label, size)
            first = _textblock.measure(lines[0], size)
            extra = max(
                extra,
                _textblock.rotated_extent(block, angle)[1]
                - _textblock.rotated_extent(first, angle)[1],
            )
        if props.get("label") and len(_textblock.split_lines(props["label"])) > 1:
            label_size = float(style.get("label_size", 12.0))
            label_lines = _textblock.measure(props["label"], label_size).line_count
            extra = max(extra, max(0, label_lines - 1) * label_size * _textblock.LINE_HEIGHT)
        return extra

    def _colorbar_outside_room(self, compact: bool) -> tuple[float, float]:
        """Renderer room consumed by this axes' colorbar, in CSS pixels."""
        del compact  # colorbars keep their physical chrome on fixed pyplot canvases
        options = self._colorbar
        if options is None:
            return 0.0, 0.0
        label = bool(options.get("label"))
        explicit_axes = options.get("placement") == "axes"
        if options.get("orientation") == "horizontal":
            room = 24.0 if explicit_axes else (18.0 if options.get("pad") == 0 else 38.0)
            return 0.0, room + (16.0 if label else 0.0)
        room = 44.0 if explicit_axes else (62.0 if options.get("pad") == 0 else 86.0)
        return room + (18.0 if label else 0.0), 0.0

    def _aspect_anchor(self) -> tuple[float, float]:
        """Normalized anchor of an aspect-shrunk box within its allocation."""
        anchor = self._anchor or "C"
        x = 0.0 if "W" in anchor else 1.0 if "E" in anchor else 0.5
        y = 0.0 if "S" in anchor else 1.0 if "N" in anchor else 0.5
        return x, y

    def _frame_padding(self, width: int, height: int) -> Optional[list[float]]:
        """Explicit ``padding`` that renders the axes frame where Matplotlib
        draws it — the rectangle `get_position()` reports.

        Without this the renderers fell back to label-aware default margins
        (62/14/10/42 px at ordinary export sizes), which have nothing to do with
        the ``figure.subplot.*`` frame: a default 640x480 figure drew its frame
        at x 0.0969..0.9781 (13.8 % too wide) with its top edge at y 0.0208
        instead of 0.1208.  Returns None when the wanted rectangle cannot be
        expressed as non-negative padding, leaving the defaults in charge.
        """
        if self._colorbar is not None and self._plot_box_px is None:
            # Matplotlib's colorbar() steals its strip from the parent axes
            # rectangle, while the renderers reserve it outside the padding.
            # Reconciling the two is colorbar-placement work, not framing work.
            return None
        if self._plot_box_px is not None:
            left, top, plot_width, plot_height = self._plot_box_px
        else:
            # Padding describes the original allocation. Adjustable-box
            # aspect handling below shrinks it once; using the active position
            # here would apply the aspect solve twice.
            x0, y0, rect_width, rect_height = self.get_position(original=True).bounds
            left = x0 * width
            top = (1.0 - y0 - rect_height) * height
            plot_width = rect_width * width
            plot_height = rect_height * height
        extra_top, extra_right, extra_bottom = self._outside_padding(width < 520)
        padding = [
            top - extra_top,
            width - left - plot_width - extra_right,
            height - top - plot_height - extra_bottom,
            left,
        ]
        if any(value < 0.0 for value in padding):
            return None
        return padding

    def _build_chart(self, width: int, height: int) -> Any:
        if self._y2_of is not None:
            return self._y2_of._build_chart(width, height)
        if self._chart is not None:
            return self._chart
        with _textblock.measurement_cache():
            return self._build_chart_uncached(width, height)

    def _build_chart_uncached(self, width: int, height: int) -> Any:
        """Build a fresh chart while one pass owns repeated text metrics."""
        self._materialize_insets()
        self._materialize_quiver_geometry(width, height)
        chart_padding = (
            self._frame_padding(width, height) if self._padding is None else list(self._padding)
        )
        if self._table_bottom_points:
            compact = width < 520
            extra_bottom = self._outside_padding(compact)[2]
            if chart_padding is None:
                chart_padding = [6.0, 8.0, 36.0, 46.0] if compact else [10.0, 14.0, 42.0, 62.0]
            else:
                chart_padding = list(map(float, chart_padding))
            table_bottom = self._table_bottom_points * self._point_scale()
            chart_padding[2] = max(chart_padding[2], table_bottom - extra_bottom)
        adjusted_aspect = False
        aspect_domains: Optional[tuple[tuple[float, float], tuple[float, float]]] = None
        if self._aspect_equal and self._aspect_bounds is not None:
            x0, x1, y0, y1 = self._aspect_bounds
            x0, x1 = self._axis["x"].get("domain", (x0, x1))
            y0, y1 = self._axis["y"].get("domain", (y0, y1))
            tx0, tx1 = self._aspect_coordinates("x", (x0, x1))
            ty0, ty1 = self._aspect_coordinates("y", (y0, y1))
            compact = width < 520
            if chart_padding is None:
                top, right, bottom, left = (
                    (6.0, 8.0, 36.0, 46.0) if compact else (10.0, 14.0, 42.0, 62.0)
                )
            else:
                top, right, bottom, left = map(float, chart_padding)
            # Solve over the rect the renderers will actually draw, gutters and
            # all — a top-side x axis (matshow) otherwise made the equal-unit
            # solve believe the plot box was 26 px taller than it is.
            extra_top, extra_right, extra_bottom = self._outside_padding(compact)
            layout_top = top + extra_top
            layout_right = right + extra_right
            layout_bottom = bottom + extra_bottom
            plot_width = max(40.0, width - left - layout_right)
            plot_height = max(40.0, height - layout_top - layout_bottom)
            data_ratio = abs(tx1 - tx0) / max(
                abs(ty1 - ty0) * self._aspect_value,
                np.finfo(float).eps,
            )
            plot_ratio = plot_width / plot_height
            if self._aspect_adjustable == "datalim":
                # axis("equal") keeps the normal axes rectangle. Expand the
                # narrower data dimension around its existing center so one
                # x unit and one y unit occupy the same number of pixels.
                if plot_ratio > data_ratio:
                    center = (tx0 + tx1) * 0.5
                    half_span = abs(ty1 - ty0) * plot_ratio * self._aspect_value * 0.5
                    tx0, tx1 = center - half_span, center + half_span
                else:
                    center = (ty0 + ty1) * 0.5
                    half_span = abs(tx1 - tx0) / (plot_ratio * self._aspect_value) * 0.5
                    ty0, ty1 = center - half_span, center + half_span
                x0, x1 = self._aspect_coordinates("x", (tx0, tx1), inverse=True)
                y0, y1 = self._aspect_coordinates("y", (ty0, ty1), inverse=True)
                aspect_domains = ((x0, x1), (y0, y1))
            else:
                # adjustable='box' preserves image limits and changes the axes
                # rectangle to maintain equal data-unit scaling.
                anchor_x, anchor_y = self._aspect_anchor()
                if plot_ratio > data_ratio:
                    extra = plot_width - plot_height * data_ratio
                    left += extra * anchor_x
                    right += extra * (1.0 - anchor_x)
                else:
                    extra = plot_height - plot_width / data_ratio
                    top += extra * (1.0 - anchor_y)
                    bottom += extra * anchor_y
                chart_padding = [top, right, bottom, left]
                # Image-like entries carry their extent outside the ordinary
                # axis property dictionaries. Materialize it so the renderer's
                # generic range padding cannot move explicit image edges.
                self._axis["x"]["domain"] = (x0, x1)
                self._axis["y"]["domain"] = (y0, y1)
            adjusted_aspect = True
        if self._padding is None and any(
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
            if chart_padding is None:
                chart_padding = (
                    [6.0, 8.0 + 26.0, 36.0, 46.0] if compact else [10.0, 14.0 + 26.0, 42.0, 62.0]
                )
            else:
                chart_padding = list(map(float, chart_padding))
                chart_padding[1] += 26.0
        anchored_legends: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        if self._legend and self._legend_artist is None and self._legend_options.get("anchor"):
            _, labels = self.get_legend_handles_labels()
            if labels:
                anchored_legends.append(
                    (self._legend_options, [{"name": label} for label in labels])
                )
        extra_legend_artists = list(self._extra_legends)
        if self._legend_artist is not None:
            extra_legend_artists.append(self._legend_artist)
        for legend_artist in extra_legend_artists:
            legend_spec = legend_artist.spec()
            if legend_spec.get("anchor") and legend_spec.get("items"):
                anchored_legends.append((legend_spec, list(legend_spec["items"])))
        if anchored_legends:
            from .._svg import _legend_layout

            compact = width < 520
            if chart_padding is None:
                chart_padding = [6.0, 8.0, 36.0, 46.0] if compact else [10.0, 14.0, 42.0, 62.0]
            top, right, bottom, left = map(float, chart_padding)
            for legend_options, legend_items in anchored_legends:
                anchor = legend_options["anchor"]
                loc = str(legend_options.get("loc") or "upper right")
                ax, ay = float(anchor[0]), float(anchor[1])
                aw, ah = (0.0, 0.0) if len(anchor) == 2 else (float(anchor[2]), float(anchor[3]))
                # Ask the shared static geometry for the legend's natural
                # bounded size. A very tall provisional plot prevents entry
                # truncation from hiding the amount of outside room required.
                provisional_plot = {
                    "x": left,
                    "y": top,
                    "w": max(40.0, width - left - right),
                    "h": max(10_000.0, height - top - bottom),
                }
                legend_box = _legend_layout(legend_items, provisional_plot, legend_options)
                border_axes_pad = max(0.0, float(legend_options.get("border_pad", 0.0)))
                vertical_room = legend_box["box_h"] + border_axes_pad + 6.0
                horizontal_room = legend_box["box_w"] + border_axes_pad + 6.0
                if ay >= 1.0 and "lower" in loc:
                    top = max(top, vertical_room)
                if ay + ah <= 0.0 and "upper" in loc:
                    bottom = max(bottom, vertical_room)
                if ax >= 1.0 and "left" in loc:
                    right = max(right, min(220.0, horizontal_room))
                if ax + aw <= 0.0 and "right" in loc:
                    left = max(left, min(220.0, horizontal_room))
            chart_padding = [top, right, bottom, left]
        # A dataless matplotlib axis views exactly (0, 1) — margins never apply.
        # Pin it so the engine's autorange padding cannot widen the empty view
        # (padding turns the 0.5 midpoint tick into a bare 0/1 pair). Render
        # snapshot only: data plotted after a render must autoscale as usual.
        axis_dataless = {
            axis: self._axis_is_dataless(axis)
            for axis in ("x", "y")
            if not adjusted_aspect
            and not self._has_explicit_shared_domain(axis)
            and self._axis[axis].get("domain") is None
        }
        empty_view = {axis for axis, dataless in axis_dataless.items() if dataless}
        x_props = {k: v for k, v in self._axis["x"].items() if v is not None}
        y_props = {k: v for k, v in self._axis["y"].items() if v is not None}
        self._inherit_shared_axis_state("x", x_props)
        self._inherit_shared_axis_state("y", y_props)
        rotation_source = self._shared_ticker_source("x")
        if (
            rotation_source._tick_rotation_modes.get("x") == "xtick"
            and x_props.get("tick_label_angle") is not None
        ):
            # Matplotlib angles are counter-clockwise in display coordinates;
            # SVG/CSS and the native y-down raster surface rotate positive
            # angles clockwise. Keep the public Text angle unchanged, but
            # convert the materialized special-mode geometry so the selected
            # edge points toward the tick instead of pivoting into the plot.
            x_props["tick_label_angle"] = -float(x_props["tick_label_angle"])
        if not self.axison:
            # `set_axis_off()` is a draw-time override in Matplotlib: suppress
            # labels, ticks, grid lines and axis titles while leaving the
            # authored Axis state intact for a later `set_axis_on()`.
            x_props["tick_label_strategy"] = "none"
            y_props["tick_label_strategy"] = "none"
        for axis, props in (("x", x_props), ("y", y_props)):
            if (
                adjusted_aspect
                or self._has_explicit_shared_domain(axis)
                or axis in self._tick_expanded_domains
            ):
                continue
            # Mesh and image spans are sticky on both ends: materialize the
            # domain so the renderer's generic margin padding cannot widen an
            # axis Matplotlib pins flush to the outer cell edge. `margin` and
            # `domain` never combine (spec/design/pan-and-zoom-configuration.md
            # §9), so send exactly one of them.
            pinned = (
                None
                if props.get("domain") is not None
                else self._fully_sticky_domain(axis, dataless=axis_dataless.get(axis))
            )
            if pinned is not None:
                props["domain"] = pinned
            else:
                margin = self._effective_margin(axis)
                if margin < 0.0 or self._has_nonzero_bar_baseline(axis):
                    props["domain"] = self._auto_domain(axis)
                else:
                    props["margin"] = margin
        if "x" in empty_view:
            x_props["domain"] = (
                self._auto_domain("x") if self._scale_specs["x"]["name"] == "log" else (0.0, 1.0)
            )
        if "y" in empty_view:
            y_props["domain"] = (
                self._auto_domain("y") if self._scale_specs["y"]["name"] == "log" else (0.0, 1.0)
            )
        if aspect_domains is not None:
            x_props["domain"], y_props["domain"] = aspect_domains
        auto_tick_counts = self._auto_tick_counts(x_props, width, height)
        if (
            rcParams["axes.autolimit_mode"] == "round_numbers"
            and not adjusted_aspect
            and not self._tight
        ):
            self._apply_round_number_domains(x_props, y_props, auto_tick_counts)
        self._apply_tickers("x", x_props, auto_tick_counts["x"])
        self._apply_tickers("y", y_props, auto_tick_counts["y"])
        self._apply_auto_tick_density(x_props, y_props, auto_tick_counts)
        if self._projection == "polar":
            # A polar angular view defaults to one complete turn. Cartesian
            # autoscaling above can materialize a padded x domain (bars are a
            # common trigger), but that internal domain is not an authored
            # theta limit and must not become a sector. set_xlim() and
            # set_thetamin/max share the explicit-domain state, so preserve it
            # only when either public spelling has actually authored it.
            if not self._has_explicit_shared_domain("x"):
                x_props.pop("domain", None)
                x_props.pop("margin", None)
            # The angular descriptors are axis properties, so route them
            # through the authored x-axis component with its ticks, labels and
            # explicit limits intact. Calling Figure.set_axis() after chart
            # construction replaces unspecified fields with defaults and used
            # to erase set_thetagrids()/set_xticks() from polar axes.
            x_props.update(self._polar_options)
            y_props.update(self._polar_r_options)
        compact = width < 520
        if chart_padding is None:
            top, right, bottom, left = (
                (6.0, 8.0, 36.0, 46.0) if compact else (10.0, 14.0, 42.0, 62.0)
            )
        else:
            top, right, bottom, left = map(float, chart_padding)
        extra_top, extra_right, extra_bottom = self._outside_padding(compact)
        self._materialize_plot_px = (
            max(1.0, width - left - right - extra_right),
            max(1.0, height - top - bottom - extra_top - extra_bottom),
        )
        resolved_domains: dict[str, tuple[float, float]] = {}
        if any(
            entry.get("kind") == "@hline" and entry.get("endpoint_marker")
            for entry in self._entries
        ):
            resolved_domains["x"] = tuple(x_props.get("domain") or self._auto_domain("x"))
        if any(
            entry.get("kind") == "@vline" and entry.get("endpoint_marker")
            for entry in self._entries
        ):
            resolved_domains["y"] = tuple(y_props.get("domain") or self._auto_domain("y"))
        children = self._chart_children(resolved_domains=resolved_domains)
        if self._twin is not None:
            self._twin._materialize_plot_px = self._materialize_plot_px
        # The left gutter is no longer reserved here. `_svg.layout()` measures
        # it from the axis's own tick/title extents once the range is resolved,
        # which covers numeric ticks (this shim's 13.89 px rcParam fonts overrun
        # the 62 px default) as well as the categorical labels this branch used
        # to special-case, and applies to an authored `padding` too.
        children.append(_cached_axis("x", x_props))
        children.append(_cached_axis("y", y_props))
        for index, secondary in enumerate(self._secondary_axes, 1):
            children.append(secondary._component(index))
        if self._twin is not None:
            y2_props = {k: v for k, v in self._axis["y2"].items() if v is not None}
            if "y" not in self._twin._explicit_domains and "y2" not in self._tick_expanded_domains:
                if self._twin._axis_is_dataless("y"):
                    y2_props["domain"] = (
                        self._twin._auto_domain("y")
                        if self._scale_specs["y2"]["name"] == "log"
                        else (0.0, 1.0)
                    )
                else:
                    margin = self._twin._effective_margin("y")
                    if margin < 0.0 or self._twin._has_nonzero_bar_baseline("y"):
                        y2_props["domain"] = self._twin._auto_domain("y")
                    else:
                        y2_props["margin"] = margin
            self._apply_tickers("y2", y2_props, auto_tick_counts["y"])
            twin_domains: dict[str, tuple[float, float]] = {}
            if any(
                entry.get("kind") == "@hline" and entry.get("endpoint_marker")
                for entry in self._twin._entries
            ):
                twin_domains["x"] = tuple(x_props.get("domain") or self._auto_domain("x"))
            if any(
                entry.get("kind") == "@vline" and entry.get("endpoint_marker")
                for entry in self._twin._entries
            ):
                twin_domains["y"] = tuple(y2_props.get("domain") or self._twin._auto_domain("y"))
            children.extend(self._twin._chart_children(resolved_domains=twin_domains))
            children.append(xy.y_axis(id="y2", side="right", **y2_props))
        legend_needs_best = False
        if self._legend and self._legend_artist is not None:
            children.append(xy.legend(show=False))
        elif self._legend:
            legend_options = dict(self._legend_options)
            if legend_options.get("loc") in (None, "best"):
                # Left unresolved here on purpose and filled in below, once the
                # built figure can report the view it will actually display:
                # `best` is a question about which corner the marks reach on
                # screen, and an autoranged view is padded by the engine.
                legend_needs_best = True
                legend_options["loc"] = None
            # ``border_pad`` is an internal pixel-resolved Matplotlib wire
            # option; core's public legend component intentionally remains in
            # its declarative units. It is restored on the built Figure below.
            component_legend_options = dict(legend_options)
            component_legend_options.pop("border_pad", None)
            component_legend_options.pop("handleheight", None)
            component_legend_options.pop("handlelength", None)
            component_legend_options.pop("handletextpad", None)
            children.append(xy.legend(**component_legend_options))
        elif not any(entry.get("kwargs", {}).get("name") for entry in self._entries):
            # Core XY can auto-create a continuous-color "value" legend.
            # An unlabeled Matplotlib collection must not acquire one.
            children.append(xy.legend(show=False))
        if not self.figure._show_toolbar():
            children.append(_cached_modebar(False))
        theme_tokens = self._theme_tokens
        if _MPL_THEME_TOKENS:
            if self._grid_axis != "both":
                tokens = dict(theme_tokens)
                tokens["grid_color"] = "transparent"
                children.append(xy.theme(style=self._theme_style, **tokens))
            elif self._grid_color == _MPL_GRID_COLOR:
                children.append(_cached_theme(self._grid, theme_tokens, self._theme_style))
            else:
                tokens = dict(theme_tokens)
                tokens["grid_color"] = self._grid_color if self._grid else "transparent"
                children.append(xy.theme(style=self._theme_style, **tokens))
        chrome_styles = self._chrome_styles
        if self._title_style:
            chrome_styles = {
                **chrome_styles,
                "title": {
                    **chrome_styles.get("title", {}),
                    **self._title_style,
                },
            }
        self._chart = xy.chart(
            *children,
            title=self._title,
            width=width,
            height=height,
            padding=chart_padding,
            styles=chrome_styles,
            coords=self._projection,
        )
        core_figure = self._chart.figure()
        core_figure.title_options = [
            {
                **title,
                "style": dict(title.get("style") or {}),
            }
            for loc in ("left", "center", "right")
            if (title := self._titles.get(loc)) is not None
        ]
        # Matplotlib's categorical converter installs one fixed location per
        # first-seen category, and FixedLocator/set_*ticks draw every authored
        # location even when labels collide. The core chart API deliberately
        # auto-thins ordinary category axes; author the stronger policy only at
        # this compatibility boundary.
        for axis_id in ("x", "y"):
            options = core_figure.axis_options.get(axis_id, {})
            categories = core_figure._axis_categories.get(axis_id)
            ticker_source = self._shared_ticker_source(axis_id)
            locator = ticker_source._tickers.get((axis_id, "major_locator"))
            explicit_ticks = "tick_values" in ticker_source._axis[axis_id]
            if categories and options.get("tick_values") is None:
                options["tick_values"] = [float(index) for index in range(len(categories))]
                options["tick_count"] = max(1, len(categories))
            if (categories or isinstance(locator, FixedLocator) or explicit_ticks) and options.get(
                "tick_label_strategy"
            ) not in {"off", "none"}:
                options["tick_label_strategy"] = "preserve"
        claimed_legend_traces = self._apply_legend_handle_styles(core_figure)
        if self._twin is not None:
            self._twin._apply_legend_handle_styles(core_figure, claimed_legend_traces)
        if self._legend and self._legend_artist is None and "border_pad" in self._legend_options:
            core_figure.legend_options["border_pad"] = self._legend_options["border_pad"]
        if self._legend_items is not None:
            core_figure.legend_options["items"] = list(self._legend_items)
        best_ranges: Optional[
            tuple[Optional[tuple[float, float]], Optional[tuple[float, float]]]
        ] = None
        best_plot_size: Optional[tuple[float, float]] = None
        if legend_needs_best:
            best_ranges = self._displayed_ranges(core_figure, x_props, y_props)
            best_plot_size = self._displayed_plot_size(core_figure, best_ranges)
            core_figure.legend_options["loc"] = self._best_legend_loc(
                *best_ranges,
                legend_options=self._legend_options,
                plot_size=best_plot_size,
            )
            if self._projection == "cartesian" and self._legend_options.get("anchor") is None:
                # Preserve the Matplotlib scorer's richer initial decision, but
                # also tell the live renderer that an unanchored ``best``
                # legend may be reconsidered after resize or settled view
                # changes. Explicit, anchored, and polar locations stay exact.
                core_figure.legend_options["auto_loc"] = "best"
        if "handleheight" in self._legend_options:
            core_figure.legend_options["handleheight"] = self._legend_options["handleheight"]
        for key in ("handlelength", "handletextpad"):
            if key in self._legend_options:
                core_figure.legend_options[key] = self._legend_options[key]
        core_figure.frame_sides = (
            []
            if not self.axison
            else [
                side
                for side in ("left", "bottom", "top", "right")
                if side not in self._hidden_spines
            ]
        )
        if self._colorbar is not None:
            figure = core_figure
            options = dict(self._colorbar)
            if options.pop("_autoscale", False):
                derived = _colorbar_figure_domain(figure)
                if derived is not None:
                    options["domain"] = [derived[0], derived[1]]
            figure.colorbar_options = options
        legends = list(self._extra_legends)
        if self._legend_artist is not None:
            legends.append(self._legend_artist)
        if legends:
            if best_ranges is None:
                best_ranges = self._displayed_ranges(core_figure, x_props, y_props)
            if best_plot_size is None:
                best_plot_size = self._displayed_plot_size(core_figure, best_ranges)
            extras = []
            for leg in legends:
                spec = leg.spec()
                automatic = spec.get("loc") in (None, "best")
                if automatic:
                    spec["loc"] = self._best_legend_loc(
                        *best_ranges,
                        legend_options=spec,
                        items=list(spec.get("items") or []) or None,
                        plot_size=best_plot_size,
                    )
                    if self._projection == "cartesian" and spec.get("anchor") is None:
                        spec["auto_loc"] = "best"
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
        plot_width, plot_height = self._plot_rect_px(
            width, height, self._padding, x_props.get("side")
        )
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        base = float(rcParams["font.size"])
        x_font = _font_size_points(rcParams["xtick.labelsize"], base)
        y_font = _font_size_points(rcParams["ytick.labelsize"], base)
        return {
            "x": max(1, min(9, int(np.floor(plot_width * 72.0 / dpi / (x_font * 3.0))))),
            "y": max(1, min(9, int(np.floor(plot_height * 72.0 / dpi / (y_font * 2.0))))),
        }

    def _apply_round_number_domains(
        self,
        x_props: dict[str, Any],
        y_props: dict[str, Any],
        counts: dict[str, int],
    ) -> None:
        """Expand automatic linear views to the default locator's edge ticks.

        Matplotlib applies ``axes.autolimit_mode='round_numbers'`` at draw
        time, after the configured data margin and with the axes-size tick
        budget available. Keep the expansion on the render snapshot so an rc
        context cannot permanently turn an automatic view into an explicit
        one.
        """
        for axis, props in (("x", x_props), ("y", y_props)):
            if (
                self._has_explicit_shared_domain(axis)
                or axis in self._tick_expanded_domains
                or self._axis_is_dataless(axis)
            ):
                continue
            spec = self._scale_specs.get(axis) or {"name": "linear"}
            if spec.get("name") != "linear":
                continue
            if axis in self._margin_overrides:
                domain = props.get("domain", self._auto_domain(axis))
            else:
                lo, hi = self._entry_extent(axis)
                margin = self._rc_margins[axis]
                pad = (hi - lo) * margin
                domain = (lo - pad, hi + pad)
            ticker_source = self._shared_ticker_source(axis)
            locator = ticker_source._tickers.get((axis, "major_locator")) or AutoLocator()
            if not hasattr(locator, "view_limits"):
                continue
            if isinstance(locator, Locator):
                locator._nbins_hint = counts[axis]
            lo, hi = locator.view_limits(*map(float, domain))
            props["domain"] = (float(lo), float(hi))

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
                and (axis, "major_locator") not in self._shared_ticker_source(axis)._tickers
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
        if getattr(trace, "colorbar_domain", None) is not None:
            lo, hi = trace.colorbar_domain
            return (float(lo), float(hi))
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
    """Matplotlib ``connectionstyle`` → shared arrow-geometry style keys."""
    if not isinstance(connectionstyle, str):
        return {}
    name = connectionstyle.split(",")[0].strip()
    options = _parse_style_options(connectionstyle)
    if name == "arc3":
        rad = options.get("rad", 0.0)
        return {"curve": rad} if rad else {}
    if name in ("angle3", "angle"):
        result = {
            "angle_a": options.get("angleA", 90.0),
            "angle_b": options.get("angleB", 0.0),
        }
        if name == "angle":
            # ``angle`` is a sharp two-segment elbow. ``angle3`` uses the
            # same ray intersection as a quadratic Bézier control point.
            result["elbow"] = 1.0
        return result
    return {}


def _label_attach_styles(
    text: str,
    font_px: float,
    anchor: str,
    vertical: Any,
    *,
    bbox: bool = False,
) -> Optional[dict[str, str]]:
    """The render seam's arrow-attach styles for a label: ``start_offset``
    (anchor → text-box center, px) and ``label_clear`` (box extents around
    that center, "left,right,up,down" px, y-down).

    matplotlib's annotation arrows leave the text patch CENTER (relpos
    default (0.5, 0.5)) clipped at the patch edge — measured on 3.11.0 for
    "local minimum" at 13.89px: box anchor+[0, 106]x[-11.0, +3.3] (y-down),
    arrow start at (+111.6, -5.5), NOT at the baseline anchor. The estimates
    here (~0.58 em/char width, 1.2em line height, 0.35em descent below the
    baseline anchor, 2pt + ~0.35em clearance margin, + the bbox patch
    padding when one is drawn) land within a few px of that; the reference
    relations are pinned in tests/pyplot/test_annotation_label_clearance.py.
    """
    if not text:
        return None
    lines = text.split("\n")
    width = 0.58 * font_px * max(len(line) for line in lines)
    height = 1.2 * font_px * len(lines)
    margin = 2.8 + 0.35 * font_px + (0.4 * font_px if bbox else 0.0)
    if anchor == "middle":
        offset_x = 0.0
    elif anchor == "end":
        offset_x = -width / 2
    else:
        offset_x = width / 2
    if vertical in ("center", "middle", "center_baseline"):
        offset_y = 0.0
    elif vertical == "bottom":
        offset_y = -height / 2
    elif vertical == "top":
        offset_y = height / 2
    else:  # baseline at the anchor: ~0.35em of descent hangs below it
        offset_y = -(height / 2 - 0.35 * font_px)
    half_w, half_h = width / 2 + margin, height / 2 + margin
    return {
        "start_offset": f"{offset_x:.1f},{offset_y:.1f}",
        "label_clear": f"{half_w:.1f},{half_w:.1f},{half_h:.1f},{half_h:.1f}",
    }


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
        # Matplotlib's legacy YAArrow default has a substantially broader head
        # and a filled shaft, rather than the thin stroked ``->``
        # FancyArrowPatch style.  Matplotlib's defaults are a 4-point shaft and
        # a 12-point head base, so retain that one-third proportion.
        head_size = float(arrowprops.get("headwidth", 20.0))
        style["head_size"] = head_size
        style["shaft_width_start"] = head_size / 3.0
        style["shaft_width_end"] = head_size / 3.0
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


def _bbox_label_style(
    bbox: dict[str, Any],
    font_size: float = 11.0,
    point_scale: float = 1.0,
) -> dict[str, Any]:
    """matplotlib text ``bbox`` patch → annotation-label box styles.

    A CSS approximation shared by the browser and static exporters.
    """
    style: dict[str, Any] = {}
    alpha = bbox.get("alpha")

    def with_alpha(resolved: str) -> str:
        """Apply the patch ``alpha`` to one resolved colour.

        Matplotlib's ``bbox`` ``alpha`` is the *patch* alpha, not a face
        alpha: the SVG backend emits it as element ``opacity``, which dims
        the face and the edge together (so ``alpha=0.1`` leaves the default
        black edge effectively invisible). CSS paints ``background`` and
        ``border`` separately, so each has to carry the alpha itself.

        ``Patch.set_alpha`` *overrides* any alpha embedded in the face or edge
        colour; it does not multiply the two values.  Resolve through xy's
        native CSS Color 4 parser so Matplotlib/CSS names such as ``gray`` and
        ``rebeccapurple`` receive the same treatment as hex and rgb() forms.
        """
        if alpha is None:
            return resolved
        r, g, b, a = resolve_rgba((resolved, float(alpha)))
        return f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},{a:.3g})"

    face = bbox.get("fc", bbox.get("facecolor", "C0"))
    if face is not None and face != "none":
        resolved = resolve_color(face)
        if resolved is not None:
            style["background"] = with_alpha(resolved)
    edge = bbox.get("ec", bbox.get("edgecolor", "black"))
    if edge is not None and edge != "none":
        resolved_edge = resolve_color(edge)
        if resolved_edge is not None:
            line_width = float(bbox.get("lw", bbox.get("linewidth", 1.0)))
            style["border"] = f"{line_width:g}px solid {with_alpha(resolved_edge)}"
    boxstyle = str(bbox.get("boxstyle", "square"))
    name = boxstyle.split(",")[0].strip()
    if "round" in name:
        style["border_radius"] = 8.0 if name == "round4" else 5.0
    # With an explicit boxstyle, Matplotlib's pad is a fraction of the font
    # size.  Without one, top-level ``pad`` is in points (default 4 pt).
    if "boxstyle" in bbox:
        pad = max(0.0, _parse_style_options(boxstyle).get("pad", 0.3)) * float(font_size)
    else:
        pad = max(0.0, float(bbox.get("pad", 4.0))) * float(point_scale)
    style["padding"] = f"{pad:.3g}px"
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


def _rc_font_weight(value: Any, key: str = "font-weight") -> dict[str, Any]:
    """Carry a weight rcParam only when it asks for something other than normal.

    Matplotlib's ``axes.titleweight``/``axes.labelweight`` default to
    ``"normal"``, which is also every xy renderer's own default, so the
    default case needs nothing on the wire — the same rule the neighbouring
    ``axes.labelcolor`` check uses. An explicit weight (``"bold"``, ``"light"``,
    a numeric string) travels through to the browser, SVG, and raster paths.
    """
    weight = str(value)
    return {} if weight == "normal" else {key: weight}


def _rc_axis_style(axis: str, dpi: float = 96.0) -> dict[str, Any]:
    prefix = "xtick" if axis == "x" else "ytick"
    point_scale = float(dpi) / 72.0
    tick_color = rcParams[f"{prefix}.color"]
    label_color = rcParams[f"{prefix}.labelcolor"]
    result: dict[str, Any] = {}
    result["axis_width"] = float(rcParams["axes.linewidth"]) * point_scale
    result["grid_width"] = float(rcParams["grid.linewidth"]) * point_scale
    result["grid_opacity"] = float(rcParams["grid.alpha"])
    grid_dash = LINESTYLE_TO_DASH.get(
        rcParams["grid.linestyle"],
        rcParams["grid.linestyle"],
    )
    if grid_dash is not None:
        result["grid_dash"] = grid_dash
    result["tick_length"] = float(rcParams[f"{prefix}.major.size"]) * point_scale
    result["tick_padding"] = float(rcParams[f"{prefix}.major.pad"]) * point_scale
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
    # The browser reads the weight off `chrome_styles["axis_title"]`; the SVG
    # and native raster exporters read it off the axis style, so `axes.labelweight`
    # has to be published in both places to reach all three renderers.
    result.update(_rc_font_weight(rcParams["axes.labelweight"], "label_font_weight"))
    return result


def _rc_minor_axis_style(axis: str, dpi: float = 96.0) -> dict[str, Any]:
    """Snapshot Matplotlib's independent minor-tick stroke geometry."""
    prefix = "xtick" if axis == "x" else "ytick"
    point_scale = float(dpi) / 72.0
    style = {
        "tick_length": float(rcParams[f"{prefix}.minor.size"]) * point_scale,
        "tick_width": float(rcParams[f"{prefix}.minor.width"]) * point_scale,
        "tick_padding": float(rcParams[f"{prefix}.minor.pad"]) * point_scale,
        "grid_color": "transparent",
        "grid_width": float(rcParams["grid.linewidth"]) * point_scale,
        "grid_opacity": float(rcParams["grid.alpha"]),
    }
    grid_dash = LINESTYLE_TO_DASH.get(
        rcParams["grid.linestyle"],
        rcParams["grid.linestyle"],
    )
    if grid_dash is not None:
        style["grid_dash"] = grid_dash
    return style


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
    if not np.isfinite(margin) or margin <= -0.5:
        raise ValueError("margin must be finite and greater than -0.5")
    return margin


def _apply_axis_label_kwargs(
    props: dict[str, Any],
    kwargs: dict[str, Any],
    context: str,
    *,
    point_scale: float,
) -> None:
    labelpad = kwargs.pop("labelpad", None)
    loc = kwargs.pop("loc", None)
    text_style = _pop_text_style_kwargs(kwargs, context)
    axis_style = props.setdefault("style", {})
    for source, target in (
        ("color", "label_color"),
        ("font_size", "label_size"),
        ("font_family", "label_font_family"),
        ("font_weight", "label_font_weight"),
        ("font_style", "label_font_style"),
    ):
        if source in text_style:
            value = text_style[source]
            axis_style[target] = float(value) * point_scale if source == "font_size" else value
    if labelpad is not None:
        props["label_offset"] = float(labelpad)
    if "rotation" in text_style:
        props["label_angle"] = float(text_style["rotation"])
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


def _pop_text_style_kwargs(kwargs: dict[str, Any], context: str) -> dict[str, Any]:
    """Consume Matplotlib text kwargs and return renderer-backed font style."""
    fontdict = kwargs.pop("fontdict", None)
    if fontdict is not None:
        if not isinstance(fontdict, Mapping):
            raise TypeError(f"{context} fontdict must be a mapping or None")
        kwargs = {**fontdict, **kwargs}

    def pop_alias(primary: str, *aliases: str) -> Any:
        value = kwargs.pop(primary, None)
        for alias in aliases:
            alias_value = kwargs.pop(alias, None)
            if value is None:
                value = alias_value
        return value

    size = pop_alias("fontsize", "size")
    weight = pop_alias("fontweight", "weight")
    family = pop_alias("fontfamily", "family")
    font_style = pop_alias("fontstyle", "style")
    color = kwargs.pop("color", None)
    rotation = kwargs.pop("rotation", _UNSET)
    for key in (
        "horizontalalignment",
        "ha",
        "verticalalignment",
        "va",
        "pad",
        "y",
        "x",
        "transform",
    ):
        kwargs.pop(key, None)
    if kwargs:
        raise TypeError(f"{context} got unsupported keyword argument {next(iter(kwargs))!r}")

    style: dict[str, Any] = {}
    if size is not None:
        style["font_size"] = _font_size_points(size, rcParams["font.size"])
    if weight is not None:
        style["font_weight"] = str(weight)
    if family is not None:
        style["font_family"] = str(family)
    if font_style is not None:
        font_style = str(font_style)
        if font_style not in {"normal", "italic", "oblique"}:
            raise ValueError(f"{context} style must be 'normal', 'italic', or 'oblique'")
        style["font_style"] = font_style
    if color is not None:
        style["color"] = resolve_color(color)
    if rotation is not _UNSET:
        if rotation is None or rotation == "horizontal":
            rotation = 0.0
        elif rotation == "vertical":
            rotation = 90.0
        # Matplotlib angles use a y-up coordinate system, while SVG/CSS uses
        # y-down coordinates.  Store the renderer-facing angle with the
        # opposite sign so positive Matplotlib rotation stays counterclockwise.
        rendered_rotation = -float(rotation)
        style["rotation"] = 0.0 if rendered_rotation == 0.0 else rendered_rotation
    return style


def _title_css_style(style: dict[str, Any], *, point_scale: float) -> dict[str, Any]:
    """Translate renderer text style keys to the chart title's CSS slot."""
    result: dict[str, Any] = {}
    for source, target in (
        ("color", "color"),
        ("font_family", "font-family"),
        ("font_weight", "font-weight"),
        ("font_style", "font-style"),
    ):
        if source in style:
            result[target] = style[source]
    if "font_size" in style:
        result["font-size"] = f"{float(style['font_size']) * point_scale:g}px"
    return result


def _marker_symbol(marker: Any) -> str:
    """Named-symbol helper retained for plot-type adapters.

    Authored markers need the complete renderer spec and are handled by
    ``marker_render_spec`` at the direct plot/scatter call sites.
    """
    return str(marker_render_spec(marker)["symbol"])


_SUPERSCRIPT_DIGITS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _pow_label(value: float, base: float = 10.0) -> str:
    """Matplotlib's log-decade label with a unicode superscript exponent."""
    exponent = np.log(value) / np.log(base) if value > 0 else np.nan
    if not np.isfinite(exponent) or abs(exponent - round(exponent)) > 1e-9:
        return f"{value:g}"
    return f"{base:g}" + str(round(float(exponent))).translate(_SUPERSCRIPT_DIGITS)


def _pow10_label(value: float) -> str:
    return _pow_label(value, 10.0)


def _plain_text(value: Any) -> str:
    text = str(value)
    converted = mathtext_to_unicode(text)
    if converted != text:
        return converted
    if "$" not in text and "\\" not in text:
        return text
    # Matplotlib treats an odd number of dollar signs as literal text. This is
    # used by gallery formatters such as ``fmt="$ {x:.2f}"`` for currency.
    if text.count("$") % 2:
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


def _plain_text_with_math_italic_ranges(value: Any) -> tuple[str, list[tuple[int, int]]]:
    """Flatten simple mathtext while retaining its default italic spans."""
    converted, ranges = mathtext_italic_ranges(str(value))
    if converted != str(value):
        return converted, ranges
    return _plain_text(value), []


def _masked_float(value: Any) -> np.ndarray:
    return np.ma.asarray(value, dtype=np.float64).filled(np.nan)


def _resolve_imshow_sampling(
    source_shape: tuple[int, int],
    interpolation: str,
    interpolation_stage: Any,
) -> tuple[str, str, int, int]:
    """Resolve Matplotlib's adaptive image defaults against our bounded surface.

    Matplotlib 3.11 selects ``nearest`` for an image enlarged by more than
    three times in both dimensions, or by exactly one or two times, and uses
    ``hanning`` otherwise. Its automatic stage is RGBA for downsampling or
    enlargement below three times in either dimension, and data otherwise.

    Matplotlib makes that choice against the final display transform. Pyplot
    pre-renders smooth images into a bounded 512--1024 px intermediate, so that
    surface is the closest available display-resolution proxy and is also the
    exact target passed to :func:`_resample_grid`.
    """
    source_height, source_width = source_shape
    target_width = min(1024, max(512, source_width))
    target_height = min(1024, max(512, source_height))

    if interpolation in {"auto", "antialiased"}:
        nearest_x = (
            target_width > 3 * source_width
            or target_width == source_width
            or target_width == 2 * source_width
        )
        nearest_y = (
            target_height > 3 * source_height
            or target_height == source_height
            or target_height == 2 * source_height
        )
        interpolation = "nearest" if nearest_x and nearest_y else "hanning"

    if interpolation_stage in (None, "auto"):
        interpolation_stage = (
            "rgba"
            if target_width < 3 * source_width or target_height < 3 * source_height
            else "data"
        )

    return interpolation, interpolation_stage, target_width, target_height


def _interpolation_taps(source: int, target: int, method: str) -> tuple[np.ndarray, np.ndarray]:
    """Return source indices and normalized local taps for a separable filter."""
    positions = np.linspace(0.0, source - 1.0, target)[:, None]
    # Every supported kernel has radius at most four. Gathering those local
    # taps avoids the old target-by-source dense matrix, whose mostly-zero
    # allocation and matrix multiplies made ordinary large-image imshow
    # quadratic in memory and cubic in work.
    indices = np.floor(positions).astype(np.int64) + np.arange(-4, 5, dtype=np.int64)
    valid = (indices >= 0) & (indices < source)
    distance = positions - indices
    absolute = np.abs(distance)

    def keys(a: float) -> np.ndarray:
        first = (a + 2.0) * absolute**3 - (a + 3.0) * absolute**2 + 1.0
        second = a * absolute**3 - 5.0 * a * absolute**2 + 8.0 * a * absolute - 4.0 * a
        return np.where(absolute <= 1.0, first, np.where(absolute < 2.0, second, 0.0))

    if method == "bilinear":
        weights = np.maximum(0.0, 1.0 - absolute)
    elif method == "hanning":
        weights = np.where(absolute < 1.0, 0.5 + 0.5 * np.cos(np.pi * absolute), 0.0)
    elif method == "hamming":
        weights = np.where(absolute < 1.0, 0.54 + 0.46 * np.cos(np.pi * absolute), 0.0)
    elif method == "gaussian":
        weights = np.where(absolute < 2.0, np.exp(-2.0 * absolute**2), 0.0)
    elif method == "kaiser":
        # Match AGG's image_filter_kaiser, which Matplotlib delegates to:
        # a compact one-pixel support with beta=6.33.  Treating Kaiser like
        # the wider sinc-family filters averages almost the entire 4x4
        # interpolation-methods example at every output location, collapsing
        # its localized 2-D structure into a near one-dimensional gradient.
        radius = 1.0
        beta = 6.33
        weights = np.where(
            absolute < radius,
            np.i0(beta * np.sqrt(np.maximum(0.0, 1.0 - (absolute / radius) ** 2))) / np.i0(beta),
            0.0,
        )
    elif method == "sinc":
        weights = np.where(absolute < 4.0, np.sinc(distance), 0.0)
    elif method == "lanczos":
        weights = np.where(absolute < 3.0, np.sinc(distance) * np.sinc(distance / 3.0), 0.0)
    elif method == "bessel":
        # A windowed-sinc approximation keeps this dependency-free; unlike the
        # old bilinear alias it still preserves the filter's ringing character.
        weights = np.where(absolute < 4.0, np.sinc(distance) * np.sinc(distance / 4.0), 0.0)
    elif method == "mitchell":
        b = c = 1.0 / 3.0
        first = (
            (12 - 9 * b - 6 * c) * absolute**3 + (-18 + 12 * b + 6 * c) * absolute**2 + (6 - 2 * b)
        ) / 6.0
        second = (
            (-b - 6 * c) * absolute**3
            + (6 * b + 30 * c) * absolute**2
            + (-12 * b - 48 * c) * absolute
            + (8 * b + 24 * c)
        ) / 6.0
        weights = np.where(absolute < 1.0, first, np.where(absolute < 2.0, second, 0.0))
    else:
        cubic_a = {
            "bicubic": -0.75,
            "catrom": -0.5,
            "hermite": 0.0,
            "quadric": -0.25,
            "spline16": -1.0,
            "spline36": -0.35,
            "antialiased": -0.5,
        }.get(method, -0.5)
        weights = keys(cubic_a)
    weights = np.where(valid, weights, 0.0)
    totals = weights.sum(axis=1, keepdims=True)
    return (
        np.clip(indices, 0, source - 1),
        weights / np.where(np.abs(totals) > 1e-12, totals, 1.0),
    )


def _resample_grid(grid: np.ndarray, width: int, height: int, method: str) -> np.ndarray:
    """Dependency-free separable resampling for scalar and RGB(A) images."""
    values = np.asarray(grid, dtype=np.float64)
    iy, wy = _interpolation_taps(values.shape[0], height, method)
    ix, wx = _interpolation_taps(values.shape[1], width, method)

    def apply_taps(array: np.ndarray) -> np.ndarray:
        # Accumulate one tap at a time. A vectorized ``take`` over the whole
        # tap matrix materializes target × taps × source intermediates and can
        # consume more memory than the dense weights this replaces.
        vertical = np.zeros((len(iy), *array.shape[1:]), dtype=np.float64)
        y_shape = (len(iy),) + (1,) * (array.ndim - 1)
        for tap in range(iy.shape[1]):
            vertical += np.take(array, iy[:, tap], axis=0) * wy[:, tap].reshape(y_shape)
        horizontal = np.zeros((vertical.shape[0], len(ix), *vertical.shape[2:]), dtype=np.float64)
        x_shape = (1, len(ix)) + (1,) * (array.ndim - 2)
        for tap in range(ix.shape[1]):
            horizontal += np.take(vertical, ix[:, tap], axis=1) * wx[:, tap].reshape(x_shape)
        return horizontal

    def resample(channel: np.ndarray) -> np.ndarray:
        finite = np.isfinite(channel)
        if finite.all():
            return apply_taps(channel)
        # Renormalize around masked samples instead of allowing IEEE
        # ``0 * nan`` terms to poison every output pixel touched by a filter.
        numerator = apply_taps(np.where(finite, channel, 0.0))
        denominator = apply_taps(finite.astype(np.float64))
        return np.divide(
            numerator,
            denominator,
            out=np.full_like(numerator, np.nan),
            where=np.abs(denominator) > 1e-12,
        )

    if values.ndim == 2:
        return resample(values)
    channels = [resample(values[..., index]) for index in range(values.shape[2])]
    return np.stack(channels, axis=-1)


def _scalar_grid_rgba(grid: np.ndarray, cmap: Any, vmin: Any, vmax: Any) -> np.ndarray:
    """Map scalar samples before RGBA-stage interpolation."""
    values = np.asarray(grid, dtype=np.float64)
    finite = values[np.isfinite(values)]
    lo = float(vmin) if vmin is not None else (float(finite.min()) if finite.size else 0.0)
    hi = float(vmax) if vmax is not None else (float(finite.max()) if finite.size else 1.0)
    normalized = (values - lo) / ((hi - lo) or 1.0)
    return scalar_grid_rgba(normalized, cmap)


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


_MILLISECONDS_PER_DAY = 86_400_000.0
_MATPLOTLIB_EPOCH = datetime(1970, 1, 1)


def _is_foreign_matplotlib_date_object(value: Any) -> bool:
    return (type(value).__module__ or "").startswith("matplotlib.dates")


def _is_null_formatter(value: Any) -> bool:
    return value is not None and type(value).__name__ == "NullFormatter"


def _locator_tick_values(
    locator: Any,
    lo: float,
    hi: float,
    *,
    datetime_axis: bool,
) -> np.ndarray:
    """Resolve ordinary and Matplotlib-date locators into engine units."""
    if not _is_foreign_matplotlib_date_object(locator):
        return np.asarray(locator.tick_values(lo, hi), dtype=float).reshape(-1)
    unit = 1.0 if not datetime_axis else _MILLISECONDS_PER_DAY
    try:
        lo_datetime = _MATPLOTLIB_EPOCH + timedelta(days=float(lo) / unit)
        hi_datetime = _MATPLOTLIB_EPOCH + timedelta(days=float(hi) / unit)
    except (OverflowError, OSError, ValueError):
        return np.asarray([], dtype=float)
    values = np.asarray(locator.tick_values(lo_datetime, hi_datetime), dtype=float).reshape(-1)
    return values * unit


def _formatter_tick_labels(
    formatter: Any,
    ticks: np.ndarray,
    *,
    datetime_axis: bool,
) -> list[str]:
    """Format a complete tick set, retaining foreign formatter context."""
    values = np.asarray(ticks, dtype=float)
    if _is_foreign_matplotlib_date_object(formatter) and datetime_axis:
        values = values / _MILLISECONDS_PER_DAY
    format_ticks = getattr(formatter, "format_ticks", None)
    if callable(format_ticks):
        labels = format_ticks(values)
    else:
        set_locs = getattr(formatter, "set_locs", None)
        if callable(set_locs):
            set_locs(values)
        labels = [formatter(float(value), position) for position, value in enumerate(values)]
    return [_plain_text(label) for label in labels]


def _auto_minor_tick_values(
    locator: Any,
    lo: float,
    hi: float,
    major: np.ndarray,
) -> np.ndarray:
    """Matplotlib AutoMinorLocator's subdivision over resolved major ticks."""
    major = np.unique(np.asarray(major, dtype=float))
    if len(major) < 2:
        return np.asarray([], dtype=float)
    major_step = float(major[1] - major[0])
    ndivs = getattr(locator, "ndivs", None)
    if ndivs in (None, "auto"):
        mantissa = 10 ** (np.log10(abs(major_step)) % 1)
        ndivs = 5 if np.isclose(mantissa, [1.0, 2.5, 5.0, 10.0]).any() else 4
    ndivs = max(1, int(ndivs))
    minor_step = major_step / ndivs
    start = round((lo - major[0]) / minor_step)
    stop = round((hi - major[0]) / minor_step) + 1
    return np.arange(start, stop, dtype=float) * minor_step + major[0]


def _minor_locator_tick_values(
    locator: Any,
    lo: float,
    hi: float,
    major: np.ndarray,
    *,
    datetime_axis: bool,
) -> np.ndarray:
    if isinstance(locator, AutoMinorLocator) or type(locator).__name__ == "AutoMinorLocator":
        return _auto_minor_tick_values(locator, lo, hi, major)
    return _locator_tick_values(locator, lo, hi, datetime_axis=datetime_axis)


def _replace_plot_data(args: tuple[Any, ...], data: Any) -> tuple[Any, ...]:
    """Resolve string positional arguments through Matplotlib's ``data=`` map."""
    replaced: list[Any] = []
    for value in args:
        if not isinstance(value, str):
            replaced.append(value)
            continue
        try:
            candidate = data[value]
        except (IndexError, KeyError, TypeError, ValueError):
            # A non-key string is still meaningful as a plot format.
            replaced.append(value)
        else:
            replaced.append(candidate)
    return tuple(replaced)


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
