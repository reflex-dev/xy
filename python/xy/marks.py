"""The declarative mark core: the single implementation of every chart kind.

Each function here IS both public dialects: `Figure` binds them as its fluent
methods (`Figure.scatter is marks.scatter`), and the composition API's
appliers call those same bound methods. One body, one signature, one set of
defaults — the parity tests assert the identity. Functions take the figure
as `self` (they are written as methods; `__figure.py` assigns them in the class
body) and reach engine state — store, traces, checkpoint/rollback, ingest and
axis-position helpers — through it.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Optional, Union

import numpy as np

from . import _validate, channels, columns, kernels, styles
from ._trace import Trace
from ._typing import ArrayLike, Scalar
from .config import (
    DEFAULT_PALETTE,
    DIRECT_SOFT_CEILING,
    MAX_CONTOUR_WORK,
    default_palette_color,
)

if TYPE_CHECKING:
    from ._figure import Figure


_SYMBOL_CODES = {
    name: index
    for index, name in enumerate(
        (
            "circle",
            "square",
            "diamond",
            "triangle",
            "cross",
            "hexagon",
            "pentagon",
            "star",
            "triangle_down",
            "triangle_left",
            "triangle_right",
            "x",
            "point",
            "pixel",
            "thin_diamond",
            "plus_line",
            "x_line",
        )
    )
}


def _direct_style(
    value: Any,
    n: int,
    label: str,
    style_channels: dict[str, channels.StyleChannel],
    key: str,
    *,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    constant, channel = channels.resolve_style_channel(
        value, n, label, minimum=minimum, maximum=maximum
    )
    if channel is not None:
        style_channels[key] = channel
        # Opacity channels multiply the scalar renderer uniform; keep that
        # uniform neutral so the vector is applied exactly once. Width-like
        # channels select over their scalar fallback instead.
        return 1.0 if key == "opacity" else default
    return default if constant is None else float(constant)


def _direct_symbols(value: Any, n: int, style_channels: dict[str, channels.StyleChannel]) -> str:
    if isinstance(value, str):
        return _validate.point_symbol(value, "scatter symbol")
    arr = np.asarray(value, dtype=object)
    if arr.shape != (n,):
        raise ValueError(f"scatter symbol array must have shape {(n,)}, got {arr.shape}")
    codes = np.empty(n, dtype=np.uint8)
    for index, raw in enumerate(arr):
        symbol = _validate.point_symbol(raw, f"scatter symbol[{index}]")
        codes[index] = _SYMBOL_CODES[symbol]
    style_channels["symbol"] = channels.StyleChannel(codes, dtype="u8")
    return "circle"


def _stroke_channel(
    value: Any, n: int, label: str
) -> tuple[Optional[str], Optional[channels.ColorChannel]]:
    if value is None:
        return None, None
    if isinstance(value, str):
        return _validate.css_color(value, label), None
    resolved = channels.resolve_color(value, n, default_constant="transparent")
    if resolved.mode != "direct_rgba":
        raise ValueError(f"{label} arrays must be numeric RGB/RGBA with shape ({n}, 3|4)")
    return None, resolved


def _series_direct_paints(
    value: Any,
    n_series: int,
    n_items: int,
    label: str,
) -> Optional[list[channels.ColorChannel]]:
    """Resolve numeric bar paint arrays without confusing CSS sequences.

    A one-series bar accepts ``(N, 3|4)`` and a multi-series bar accepts
    ``(S, N, 3|4)``.  Returning ``None`` leaves scalar/per-series CSS color
    handling to the existing palette resolver.
    """
    if value is None or isinstance(value, str):
        return None
    arr = np.asarray(value)
    if not np.issubdtype(arr.dtype, np.number):
        return None
    if n_series == 1 and arr.shape in {(n_items, 3), (n_items, 4)}:
        return [channels.resolve_color(arr, n_items, default_constant=DEFAULT_PALETTE[0])]
    if arr.ndim == 3 and arr.shape[:2] == (n_series, n_items) and arr.shape[2] in (3, 4):
        return [
            channels.resolve_color(
                arr[index], n_items, default_constant=DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]
            )
            for index in range(n_series)
        ]
    raise ValueError(
        f"{label} numeric paint must have shape ({n_items}, 3|4) for one series "
        f"or ({n_series}, {n_items}, 3|4), got {arr.shape}"
    )


def _series_style_values(
    value: Any,
    n_series: int,
    n_items: int,
    label: str,
    key: str,
    *,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> tuple[list[float], list[dict[str, channels.StyleChannel]]]:
    """Resolve scalar, ``(N,)``, or ``(S,N)`` bar style values."""
    if value is None or np.isscalar(value):
        constant, _ = channels.resolve_style_channel(
            value, n_items, label, minimum=minimum, maximum=maximum
        )
        resolved = default if constant is None else float(constant)
        return [resolved] * n_series, [{} for _ in range(n_series)]
    arr = np.asarray(value)
    if n_series == 1 and arr.shape == (n_items,):
        rows = [arr]
    elif arr.shape == (n_series, n_items):
        rows = [arr[index] for index in range(n_series)]
    else:
        raise ValueError(
            f"{label} array must have shape ({n_items},) for one series or "
            f"({n_series}, {n_items}), got {arr.shape}"
        )
    out: list[dict[str, channels.StyleChannel]] = []
    for row in rows:
        _, channel = channels.resolve_style_channel(
            row, n_items, label, minimum=minimum, maximum=maximum
        )
        assert channel is not None
        out.append({key: channel})
    constant = 1.0 if key == "opacity" else default
    return [constant] * n_series, out


def _series_corner_radius(
    value: Any,
    n_series: int,
    n_items: int,
    label: str,
) -> tuple[Any, list[dict[str, channels.StyleChannel]]]:
    """Resolve constant radius/pair or direct per-bar radii."""
    arr = np.asarray(value)
    # A plain two-scalar tuple/list remains the existing constant (tip, base)
    # form.  Numeric ndarrays are direct channels, including shape (N, 2).
    if (
        np.isscalar(value)
        or isinstance(value, tuple)
        or (
            isinstance(value, (tuple, list))
            and len(value) == 2
            and all(np.isscalar(item) for item in value)
        )
    ):
        return value, [{} for _ in range(n_series)]
    if n_series == 1 and arr.shape == (n_items,):
        rows, components = [arr], 1
    elif n_series == 1 and arr.shape == (n_items, 2):
        rows, components = [arr], 2
    elif arr.shape == (n_series, n_items):
        rows, components = [arr[index] for index in range(n_series)], 1
    elif arr.shape == (n_series, n_items, 2):
        rows, components = [arr[index] for index in range(n_series)], 2
    else:
        raise ValueError(
            f"{label} array must have shape ({n_items},), ({n_items}, 2), "
            f"({n_series}, {n_items}), or ({n_series}, {n_items}, 2); got {arr.shape}"
        )
    result: list[dict[str, channels.StyleChannel]] = []
    for row in rows:
        _, channel = channels.resolve_style_channel(
            row, n_items, label, minimum=0.0, components=components
        )
        assert channel is not None
        result.append({"corner_radius": channel})
    return 0.0, result


def _append_segment_trace(
    self: "Figure",
    kind: str,
    x0: ArrayLike,
    x1: ArrayLike,
    y0: ArrayLike,
    y1: ArrayLike,
    *,
    name: Optional[str],
    color: Optional[str],
    opacity: Any,
    width: Any,
    role: str,
    color_ch: Optional[channels.ColorChannel] = None,
    count: Optional[int] = None,
    dash: Optional[list[float]] = None,
    extra_style: Optional[dict[str, Any]] = None,
) -> None:
    """Append a compact instanced line-segment trace.

    Error bars, stems, box whiskers, and contour isolines all have the same
    transport shape. Keeping that shape here avoids one trace/object per
    segment while allowing the browser and static exporters to share one
    renderer.
    """
    name = self._optional_text(name, f"{kind} name")
    arrays = [
        self._as_1d_float(v, f"{kind} {label}")
        for label, v in (("x0", x0), ("x1", x1), ("y0", y0), ("y1", y1))
    ]
    if len({len(v) for v in arrays}) != 1:
        raise ValueError(f"{kind} segment columns must have equal length")
    n = len(arrays[0])
    style_channels: dict[str, channels.StyleChannel] = {}
    opacity_value = _direct_style(
        opacity,
        n,
        f"{kind} opacity",
        style_channels,
        "opacity",
        default=1.0,
        minimum=0.0,
        maximum=1.0,
    )
    width_value = _direct_style(
        width,
        n,
        f"{kind} width",
        style_channels,
        "width",
        default=1.2,
        minimum=0.0,
    )
    checkpoint = self._checkpoint()
    try:
        x0c, x1c, y0c, y1c = [self.store.ingest(v) for v in arrays]
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind=kind,
                # Segment payloads and autorange use the explicit endpoint
                # columns. Reuse x0/y0 for common row-count bookkeeping rather
                # than allocating, scanning, and storing two unused midpoint
                # columns for every contour/errorbar/stem trace.
                x=x0c,
                y=y0c,
                x0=x0c,
                x1=x1c,
                y0=y0c,
                y1=y1c,
                name=name,
                style={
                    "color": color,
                    "opacity": opacity_value,
                    "width": width_value,
                    "role": role,
                    **({"dash": dash} if dash else {}),
                    **(extra_style or {}),
                },
                color_ch=color_ch,
                style_channels=style_channels,
                count=count,
            )
        )
    except Exception:
        self._rollback(checkpoint)
        raise


def segments(
    self: "Figure",
    x0: ArrayLike,
    y0: ArrayLike,
    x1: ArrayLike,
    y1: ArrayLike,
    *,
    name: Optional[str] = None,
    color: Union[str, ArrayLike, None] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    width: Any = 1.2,
    opacity: Any = 1.0,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add independent line segments through the shared instanced renderer."""
    css = styles.compile_mark_style("segments", style)
    color = css.get("color", color)
    width = css.get("width", width)
    opacity = css.get("opacity", opacity)
    arrays = [self._as_1d_float(values, "segments color geometry") for values in (x0, y0, x1, y1)]
    if len({len(values) for values in arrays}) != 1:
        raise ValueError("segments coordinate columns must have equal length")
    default = default_palette_color(len(self.traces))
    color_ch = channels.resolve_color(
        color, len(arrays[0]), colormap=colormap, default_constant=default
    )
    if domain is not None:
        if color_ch.mode != "continuous":
            raise ValueError("segments domain requires a continuous numeric color array")
        color_ch.domain = self._finite_increasing_pair(domain, "segments domain")
    constant = color_ch.constant if color_ch.mode == "constant" else None
    self._append_segment_trace(
        "segments",
        arrays[0],
        arrays[2],
        arrays[1],
        arrays[3],
        name=name,
        color=constant,
        opacity=opacity,
        width=width,
        role="segments",
        color_ch=None if color_ch.mode == "constant" else color_ch,
        extra_style=styles._opacity_channels(css),
    )
    return self


def triangle_mesh(
    self: "Figure",
    x0: ArrayLike,
    y0: ArrayLike,
    x1: ArrayLike,
    y1: ArrayLike,
    x2: ArrayLike,
    y2: ArrayLike,
    *,
    color: Union[str, ArrayLike, None] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    name: Optional[str] = None,
    opacity: Any = 1.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add independently colored filled triangles as one instanced mesh."""
    css = styles.compile_mark_style("triangle_mesh", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    stroke = css.get("stroke", stroke)
    stroke_width = css.get("stroke_width", stroke_width)
    name = self._optional_text(name, "triangle_mesh name")
    arrays = [
        self._as_1d_float(values, f"triangle_mesh {label}")
        for label, values in (
            ("x0", x0),
            ("y0", y0),
            ("x1", x1),
            ("y1", y1),
            ("x2", x2),
            ("y2", y2),
        )
    ]
    if len({len(values) for values in arrays}) != 1:
        raise ValueError("triangle_mesh coordinate columns must have equal length")
    n = len(arrays[0])
    style_channels: dict[str, channels.StyleChannel] = {}
    opacity_value = _direct_style(
        opacity,
        n,
        "triangle_mesh opacity",
        style_channels,
        "opacity",
        default=1.0,
        minimum=0.0,
        maximum=1.0,
    )
    stroke_value, stroke_ch = _stroke_channel(stroke, n, "triangle_mesh stroke")
    stroke_width_value = _direct_style(
        stroke_width,
        n,
        "triangle_mesh stroke_width",
        style_channels,
        "stroke_width",
        default=0.0,
        minimum=0.0,
    )
    if (
        (stroke_value is not None or stroke_ch is not None)
        and not stroke_width_value
        and ("stroke_width" not in style_channels)
    ):
        stroke_width_value = 1.0
    default_color = default_palette_color(len(self.traces))
    color_ch = channels.resolve_color(color, n, colormap=colormap, default_constant=default_color)
    if domain is not None:
        if color_ch.mode != "continuous":
            raise ValueError("triangle_mesh domain requires a continuous numeric color array")
        color_ch.domain = self._finite_increasing_pair(domain, "triangle_mesh domain")
    checkpoint = self._checkpoint()
    try:
        x0c, y0c, x1c, y1c, x2c, y2c = [self.store.ingest(values) for values in arrays]
        style: dict[str, Any] = {"opacity": opacity_value, "role": "triangle-mesh"}
        style.update(styles._opacity_channels(css))
        if stroke_value is not None:
            style["stroke"] = stroke_value
        if stroke_width_value:
            style["stroke_width"] = stroke_width_value
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="triangle_mesh",
                x=x2c,
                y=y2c,
                x0=x0c,
                x1=x1c,
                y0=y0c,
                y1=y1c,
                name=name,
                style=style,
                color_ch=color_ch,
                stroke_ch=stroke_ch,
                style_channels=style_channels,
                count=n,
            )
        )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def _error_extent(
    value: Union[Scalar, ArrayLike], n: int, center: np.ndarray, label: str
) -> tuple[np.ndarray, np.ndarray]:
    """Normalize scalar, symmetric, or ``(lower, upper)`` error input."""
    if value is None:
        raise ValueError(f"{label} must not be None")
    if np.isscalar(value):
        amount = Figure._finite_scalar(value, label)
        if amount < 0:
            raise ValueError(f"{label} must be non-negative")
        amount_arr = np.full(n, amount, dtype=np.float64)
        return center - amount_arr, center + amount_arr
    arr = Figure._as_float_array(value, label)
    if arr.ndim == 1:
        if len(arr) != n:
            raise ValueError(f"{label} must have length {n}, got {len(arr)}")
        lower_amount, upper_amount = arr, arr
    elif arr.shape == (2, n):
        lower_amount, upper_amount = arr[0], arr[1]
    elif arr.shape == (n, 2):
        lower_amount, upper_amount = arr[:, 0], arr[:, 1]
    else:
        raise ValueError(f"{label} must be a scalar, length-{n} array, or a 2x{n} array")
    # Non-finite extents must never reach vertex buffers (§19), and NaN
    # slips past a `< 0` comparison — reject it here with the input's name.
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} must be finite")
    if np.any(arr < 0):
        raise ValueError(f"{label} must be non-negative")
    return center - lower_amount, center + upper_amount


def _split_by_positions(
    vals: np.ndarray, positions: np.ndarray
) -> tuple[list[np.ndarray], np.ndarray]:
    """Single-pass factorized grouping over per-row positions.

    Output matches ``[vals[positions == p] for p in np.unique(positions)]`` —
    groups in sorted-position order, within-group input order preserved —
    without the O(n·k) rescan. NaN positions keep the mask semantics: NaN never
    compares equal, so a NaN key carries an empty group.
    """
    unique, inverse = np.unique(positions, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    bounds = np.searchsorted(inverse[order], np.arange(1, len(unique)))
    groups = np.split(vals[order], bounds)
    for i in np.flatnonzero(np.isnan(unique)):
        groups[i] = vals[:0]
    return groups, unique


def _distribution_groups(
    self: "Figure",
    values: Any,  # 1-D/2-D ArrayLike or a ragged sequence of 1-D datasets
    x: Optional[ArrayLike],
    group: Optional[ArrayLike],
    kind: str,
) -> tuple[list[np.ndarray], np.ndarray]:
    """Return finite value groups and their category/position coordinates.

    Axis categories are resolved with ``commit=False``; callers commit them
    inside their checkpointed try (the `_bar_like` pattern) so a failing build
    leaves no category residue on the figure.
    """
    if x is not None and group is not None:
        raise ValueError(f"{kind} accepts either x or group, not both")
    arr: Optional[np.ndarray] = None
    groups: Optional[list[np.ndarray]] = None
    if (
        isinstance(values, (list, tuple))
        and len(values)
        and all(not isinstance(v, str) and np.ndim(v) == 1 for v in values)
    ):
        # Sequence-of-datasets shape used by column-oriented statistical APIs:
        # one group per item, ragged lengths allowed.
        groups = [self._as_1d_float(v, f"{kind} values") for v in values]
    else:
        arr = self._as_float_array(values, f"{kind} values")
        if arr.ndim == 2:
            # Column-oriented, per the box/violin docstrings: one group per column.
            groups = [arr[:, i] for i in range(arr.shape[1])]
    if groups is not None:
        if group is not None:
            raise ValueError(f"{kind} group is only valid with 1-D values")
        if x is None:
            return groups, np.arange(len(groups), dtype=np.float64)
        if np.ndim(x) == 0:
            raise ValueError(f"{kind} x must be 1-D with one label per group")
        positions = self._axis_positions(x, "x", commit=False)
        if len(positions) != len(groups):
            raise ValueError(f"{kind} x must have one label per group")
        return groups, positions
    vals = self._as_1d_float(arr, f"{kind} values")
    key, key_name = (group, "group") if group is not None else (x, "x")
    if key is None:
        return [vals], np.array([0.0])
    positions = self._axis_positions(key, "x", commit=False)
    if len(positions) != len(vals):
        raise ValueError(f"{kind} {key_name} must have length {len(vals)}, got {len(positions)}")
    return _split_by_positions(vals, positions)


def _distribution_stats(group: np.ndarray) -> tuple[float, float, float, float, float, np.ndarray]:
    finite = group[np.isfinite(group)]
    if len(finite) == 0:
        empty = np.empty(0, dtype=np.float64)
        return (np.nan, np.nan, np.nan, np.nan, np.nan, empty)
    q1, median, q3 = np.percentile(finite, [25.0, 50.0, 75.0])
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    # Whiskers end at the most extreme observation inside the Tukey fence
    # at an observed point inside the fence, never at the bare fence value.
    # Both selections are non-empty: min <= q1 <= hi_fence and
    # lo_fence < q3 <= max.
    low = float(np.min(finite[finite >= lo_fence]))
    high = float(np.max(finite[finite <= hi_fence]))
    outliers = finite[(finite < low) | (finite > high)]
    return float(q1), float(median), float(q3), low, high, outliers


def _contour_segments(
    z: np.ndarray, x_coords: np.ndarray, y_coords: np.ndarray, levels: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extract flat contour segments through the native marching-squares kernel."""
    return kernels.marching_squares(z, x_coords, y_coords, levels)


def _bar_like(
    self: "Figure",
    kind: str,
    x: ArrayLike,
    y: ArrayLike,
    *,
    name: Optional[str],
    color: Any,
    colors: Optional[list[str]],
    width: float,
    base: Union[Scalar, ArrayLike],
    mode: str,
    orientation: str,
    series: Optional[list[str]],
    opacity: Any,
    corner_radius: Any = 0.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    artist_alpha: Any = None,
    fill: Union[str, dict[str, str], None] = None,
    style_extra: Optional[dict[str, Any]] = None,
) -> "Figure":
    name = self._optional_text(name, f"{kind} name")
    width = self._positive_scalar(width, f"{kind} width")
    if mode not in {"grouped", "stacked", "normalized"}:
        raise ValueError(f"{kind} mode must be 'grouped', 'stacked', or 'normalized'")
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError(f"{kind} orientation must be 'vertical' or 'horizontal'")
    category_axis = "x" if orientation == "vertical" else "y"
    pos, category_labels = self._axis_positions_with_labels(x, category_axis)
    vals = self._bar_value_matrix(y, len(pos), kind)
    n_series, n_items = vals.shape
    if mode == "normalized":
        if np.any(vals < 0):
            raise ValueError(
                f"{kind} mode='normalized' requires non-negative values; "
                "normalizing mixed-sign stacks is ambiguous"
            )
        # Per-category fractions of the finite total (NaN = missing segment).
        # Zero-total categories stay empty instead of emitting NaN, which
        # must never reach vertex buffers (§19).
        totals = np.nansum(vals, axis=0)
        vals = vals / np.where(totals > 0.0, totals, 1.0)
    base_vals = self._broadcast_base(base, len(pos), kind)
    series_names = self._series_names(name, series, n_series)
    direct_colors = _series_direct_paints(color, n_series, n_items, f"{kind} color")
    series_colors = (
        [None] * n_series
        if direct_colors is not None
        else self._series_colors(color, colors, n_series)
    )
    direct_strokes = _series_direct_paints(stroke, n_series, n_items, f"{kind} stroke")
    scalar_stroke = stroke if direct_strokes is None else None
    opacity_values, opacity_channels = _series_style_values(
        opacity,
        n_series,
        n_items,
        f"{kind} opacity",
        "opacity",
        default=0.85,
        minimum=0.0,
        maximum=1.0,
    )
    stroke_width_values, stroke_width_channels = _series_style_values(
        stroke_width,
        n_series,
        n_items,
        f"{kind} stroke_width",
        "stroke_width",
        default=0.0,
        minimum=0.0,
    )
    constant_radius, radius_channels = _series_corner_radius(
        corner_radius, n_series, n_items, f"{kind} corner_radius"
    )
    alpha_values, alpha_channels = _series_style_values(
        artist_alpha,
        n_series,
        n_items,
        f"{kind} alpha",
        "artist_alpha",
        default=-1.0,
        minimum=-1.0,
        maximum=1.0,
    )
    series_styles: list[dict[str, Any]] = []
    series_channels: list[dict[str, channels.StyleChannel]] = []
    for index in range(n_series):
        mark_style = self._rect_mark_style(
            kind,
            constant_radius,
            scalar_stroke,
            stroke_width_values[index],
            fill,
        )
        mark_style.update(style_extra or {})
        merged_channels = {
            **opacity_channels[index],
            **stroke_width_channels[index],
            **radius_channels[index],
            **alpha_channels[index],
        }
        if alpha_values[index] >= 0.0:
            # Constants remain spec-only. -1 means use intrinsic paint alpha.
            mark_style["artist_alpha"] = alpha_values[index]
        series_styles.append(mark_style)
        series_channels.append(merged_channels)
    checkpoint = self._checkpoint()
    try:
        if category_labels is not None:
            self._commit_category_labels(category_labels, category_axis)
        half = width / 2.0
        if vals.shape[0] == 1:
            self._append_bar_rect(
                kind,
                orientation,
                pos - half,
                pos + half,
                base_vals,
                base_vals + vals[0],
                name=name,
                color=series_colors[0],
                opacity=opacity_values[0],
                # grouped/stacked are no-ops for one series, but normalized
                # rescales even a single series — record it (§28).
                role=f"{kind}-normalized" if mode == "normalized" else kind,
                extra_style=series_styles[0],
                color_ch=None if direct_colors is None else direct_colors[0],
                stroke_ch=None if direct_strokes is None else direct_strokes[0],
                style_channels=series_channels[0],
            )
        elif mode == "grouped":
            slot = width / vals.shape[0]
            for i, row in enumerate(vals):
                p0 = pos - half + i * slot
                self._append_bar_rect(
                    kind,
                    orientation,
                    p0,
                    p0 + slot,
                    base_vals,
                    base_vals + row,
                    name=series_names[i],
                    color=series_colors[i],
                    opacity=opacity_values[i],
                    role=f"{kind}-grouped",
                    extra_style=series_styles[i],
                    color_ch=None if direct_colors is None else direct_colors[i],
                    stroke_ch=None if direct_strokes is None else direct_strokes[i],
                    style_channels=series_channels[i],
                )
        else:
            pos_base = base_vals.astype(np.float64, copy=True)
            neg_base = base_vals.astype(np.float64, copy=True)
            for i, row in enumerate(vals):
                y0 = np.where(row >= 0, pos_base, neg_base)
                y1 = y0 + row
                self._append_bar_rect(
                    kind,
                    orientation,
                    pos - half,
                    pos + half,
                    y0,
                    y1,
                    name=series_names[i],
                    color=series_colors[i],
                    opacity=opacity_values[i],
                    role=f"{kind}-{mode}",
                    extra_style=series_styles[i],
                    color_ch=None if direct_colors is None else direct_colors[i],
                    stroke_ch=None if direct_strokes is None else direct_strokes[i],
                    style_channels=series_channels[i],
                )
                pos_base = np.where(row >= 0, y1, pos_base)
                neg_base = np.where(row < 0, y1, neg_base)
    except Exception:
        self._rollback(checkpoint)
        raise
    return self


def line(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    curve: str = "linear",
    dash: Union[str, Sequence[float], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a line series. Very long series are automatically downsampled for
    display without changing the drawn shape.

    ``curve="smooth"`` renders a monotone cubic; ``dash`` dashes the line.
    """
    css = styles.compile_mark_style("line", style)
    color = css.get("color", color)
    width = css.get("width", width)
    opacity = css.get("opacity", opacity)
    dash = css.get("dash", dash)
    name = self._optional_text(name, "line name")
    color = self._optional_css_color(color, "line color")
    width = self._positive_scalar(width, "line width")
    opacity = self._opacity(opacity, "line opacity")
    curve = _validate.curve(curve, "line curve")
    dash_spec = _validate.dash(dash, "line dash")
    checkpoint = self._checkpoint()
    try:
        xc, yc = self._ingest_xy(x, y, "line")
        if not kernels.is_sorted(xc.values):
            # LOD contract (§28): line x must be sorted; the engine sorts once
            # at ingest, and says so. The predicate is NaN-safe on purpose:
            # a NaN fails its pairs, so a NaN-carrying x cannot skip the sort
            # and violate M4's sorted precondition.
            # argsort places NaNs last, where the m4 window excludes them.
            order = np.argsort(xc.values, kind="stable")
            xc = self.store.ingest(xc.values[order])
            yc = self.store.ingest(yc.values[order])
        style: dict[str, Any] = {"color": color, "width": width, "opacity": opacity}
        style.update(styles._opacity_channels(css))
        if curve != "linear":
            style["curve"] = curve
        if dash_spec is not None:
            style["dash"] = dash_spec
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="line",
                x=xc,
                y=yc,
                name=name,
                style=style,
            )
        )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def area(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    base: Union[Scalar, ArrayLike] = 0.0,
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
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a filled area trace between `y` and `base`.

    `base` may be a scalar or a length-N array, which covers both the common
    zero-baseline area chart and future stacked-area construction.
    `fill` accepts a CSS `linear-gradient(...)` (see spec/api/styling.md);
    `curve="smooth"` renders a monotone cubic through the points; `dash`
    dashes the outline.
    """
    css = styles.compile_mark_style("area", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    line_color = css.get("line_color", line_color)
    line_width = css.get("line_width", line_width)
    line_opacity = css.get("line_opacity", line_opacity)
    fill = css.get("fill", fill)
    dash = css.get("dash", dash)
    name = self._optional_text(name, "area name")
    color = self._optional_css_color(color, "area color")
    opacity = self._opacity(opacity, "area opacity")
    line_color = self._optional_css_color(line_color, "area line_color")
    line_width = self._nonnegative_scalar(line_width, "area line_width")
    line_opacity = self._opacity(line_opacity, "area line_opacity")
    stroke_perimeter = _validate.bool_param(stroke_perimeter, "area stroke_perimeter")
    fill_spec = _validate.mark_fill(fill, "area fill")
    curve = _validate.curve(curve, "area curve")
    dash_spec = _validate.dash(dash, "area dash")
    checkpoint = self._checkpoint()
    try:
        xc, yc = self._ingest_xy(x, y, "area")
        bc = (
            self.store.ingest(np.full(len(xc), self._finite_scalar(base, "area base")))
            if np.isscalar(base)
            else self.store.ingest(base)
        )
        if len(bc) != len(xc):
            raise ValueError(f"area base must have length {len(xc)}, got {len(bc)}")
        if not kernels.is_sorted(xc.values):
            order = np.argsort(xc.values, kind="stable")
            xc = self.store.ingest(xc.values[order])
            yc = self.store.ingest(yc.values[order])
            bc = self.store.ingest(bc.values[order])
        style: dict[str, Any] = {
            "color": color,
            "opacity": opacity,
            "line_width": line_width,
            "line_opacity": line_opacity,
            "stroke_perimeter": stroke_perimeter,
        }
        style.update(styles._opacity_channels(css))
        if line_color is not None:
            style["line_color"] = line_color
        if fill_spec is not None:
            style["fill"] = fill_spec
        if curve != "linear":
            style["curve"] = curve
        if dash_spec is not None:
            style["dash"] = dash_spec
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="area",
                x=xc,
                y=yc,
                base=bc,
                name=name,
                style=style,
            )
        )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def error_band(
    self: "Figure",
    x: ArrayLike,
    lower: ArrayLike,
    upper: ArrayLike,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.22,
    line_width: float = 0.0,
    line_opacity: float = 0.0,
    fill: Union[str, dict[str, str], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add an uncertainty/confidence band between ``lower`` and ``upper``.

    The band is one filled strip, not one rectangle per observation. It uses
    the same M4 reduction and WebGL area path as a large area series.
    """
    css = styles.compile_mark_style("error_band", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    line_width = css.get("line_width", line_width)
    line_opacity = css.get("line_opacity", line_opacity)
    fill = css.get("fill", fill)
    name = self._optional_text(name, "error_band name")
    color = self._optional_css_color(color, "error_band color")
    opacity = self._opacity(opacity, "error_band opacity")
    line_width = self._nonnegative_scalar(line_width, "error_band line_width")
    line_opacity = self._opacity(line_opacity, "error_band line_opacity")
    fill_spec = _validate.mark_fill(fill, "error_band fill")
    checkpoint = self._checkpoint()
    try:
        xc, lc = self._ingest_xy(x, lower, "error_band")
        uc = self.store.ingest(self._as_1d_float(upper, "error_band upper"))
        if len(uc) != len(xc):
            raise ValueError(f"error_band upper must have length {len(xc)}, got {len(uc)}")
        if not kernels.is_sorted(xc.values):
            order = np.argsort(xc.values, kind="stable")
            xc = self.store.ingest(xc.values[order])
            lc = self.store.ingest(lc.values[order])
            uc = self.store.ingest(uc.values[order])
        style: dict[str, Any] = {
            "color": color,
            "opacity": opacity,
            "line_width": line_width,
            "line_opacity": line_opacity,
            "role": "error-band",
        }
        style.update(styles._opacity_channels(css))
        if fill_spec is not None:
            style["fill"] = fill_spec
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="error_band",
                x=xc,
                y=uc,
                base=lc,
                name=name,
                style=style,
            )
        )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def _auto_cap_size(positions: np.ndarray) -> float:
    """Auto cap half-width in data units for error bars.

    0.25x the median adjacent spacing of the distinct finite positions along
    the cap's axis; 0.4 when fewer than two are distinct (no spacing exists).
    """
    distinct = np.unique(positions[np.isfinite(positions)])
    if len(distinct) < 2:
        return 0.4
    return 0.25 * float(np.median(np.diff(distinct)))


def errorbar(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    yerr: Union[Scalar, ArrayLike, None] = None,
    xerr: Union[Scalar, ArrayLike, None] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    cap_size: Optional[float] = None,
    opacity: float = 1.0,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add vertical and/or horizontal error bars as instanced segments.

    ``yerr`` and ``xerr`` accept symmetric lengths or a ``(lower, upper)``
    pair. ``cap_size`` is expressed in the perpendicular data-axis units,
    which makes the geometry stable in both notebook and static exports.
    The default (``None``) auto-sizes caps to 0.25x the median adjacent
    spacing of the distinct positions along that axis (0.4 when fewer than
    two are distinct); ``cap_size=0`` omits the caps entirely.
    """
    css = styles.compile_mark_style("errorbar", style)
    color = css.get("color", color)
    width = css.get("width", width)
    opacity = css.get("opacity", opacity)
    if yerr is None and xerr is None:
        raise ValueError("errorbar requires yerr, xerr, or both")
    name = self._optional_text(name, "errorbar name")
    color = self._optional_css_color(color, "errorbar color")
    if color is None:
        color = default_palette_color(len(self.traces))
    width = self._positive_scalar(width, "errorbar width")
    if cap_size is not None:
        cap_size = self._nonnegative_scalar(cap_size, "errorbar cap_size")
    opacity = self._opacity(opacity, "errorbar opacity")
    checkpoint = self._checkpoint()
    try:
        xc, yc = self._ingest_xy(x, y, "errorbar")
        n = len(xc)
        xvals, yvals = xc.values, yc.values
        emitted = False
        if yerr is not None:
            low, high = _error_extent(yerr, n, yvals, "errorbar yerr")
            cap = _auto_cap_size(xvals) if cap_size is None else cap_size
            if cap > 0.0:
                x0 = np.concatenate((xvals, xvals - cap, xvals - cap))
                x1 = np.concatenate((xvals, xvals + cap, xvals + cap))
                y0 = np.concatenate((low, low, high))
                y1 = np.concatenate((high, low, high))
            else:
                # No caps: ship only the n main segments, not 2n degenerate ones.
                x0, x1, y0, y1 = xvals, xvals, low, high
            self._append_segment_trace(
                "errorbar",
                x0,
                x1,
                y0,
                y1,
                name=name,
                color=color,
                opacity=opacity,
                width=width,
                role="y-errorbar",
                count=n,
                extra_style=styles._opacity_channels(css),
            )
            emitted = True
        if xerr is not None:
            low, high = _error_extent(xerr, n, xvals, "errorbar xerr")
            cap = _auto_cap_size(yvals) if cap_size is None else cap_size
            if cap > 0.0:
                x0 = np.concatenate((low, low, high))
                x1 = np.concatenate((high, low, high))
                y0 = np.concatenate((yvals, yvals - cap, yvals - cap))
                y1 = np.concatenate((yvals, yvals + cap, yvals + cap))
            else:
                x0, x1, y0, y1 = low, high, yvals, yvals
            self._append_segment_trace(
                "errorbar",
                x0,
                x1,
                y0,
                y1,
                name=None if emitted else name,
                color=color,
                opacity=opacity,
                width=width,
                role="x-errorbar",
                count=n,
                extra_style=styles._opacity_channels(css),
            )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def step(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Union[str, Sequence[float], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a step line without expanding the canonical input columns."""
    if where not in {"pre", "post", "mid"}:
        raise ValueError("step where must be 'pre', 'post', or 'mid'")
    css = styles.compile_mark_style("step", style)
    self.line(
        x,
        y,
        name=name,
        color=css.get("color", color),
        width=css.get("width", width),
        opacity=css.get("opacity", opacity),
        dash=css.get("dash", dash),
    )
    self.traces[-1].style["step"] = where
    self.traces[-1].style.update(styles._opacity_channels(css))
    return self


def stairs(
    self: "Figure",
    values: ArrayLike,
    edges: Optional[ArrayLike] = None,
    *,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Union[str, Sequence[float], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a Matplotlib-style precomputed stairs series.

    Ships the compact canonical form — the k+1 edges as x plus k+1 values
    with one endpoint duplicated — and lets the step tag do all expansion
    client-side, so bins never pre-expand into polyline vertices. Every
    ``where`` renders bin i at height ``values[i]``; ``mid`` moves the risers
    to the bin centers.
    """
    if where not in {"pre", "post", "mid"}:
        raise ValueError("stairs where must be 'pre', 'post', or 'mid'")
    vals = self._as_1d_float(values, "stairs values")
    if len(vals) == 0:
        raise ValueError("stairs values must contain at least one value")
    if edges is None:
        edge_values = np.arange(len(vals) + 1, dtype=np.float64)
    else:
        edge_values = self._as_1d_float(edges, "stairs edges")
    if len(edge_values) != len(vals) + 1:
        raise ValueError(f"stairs edges must have length {len(vals) + 1}, got {len(edge_values)}")
    if not np.all(np.isfinite(edge_values)) or not np.all(np.diff(edge_values) > 0):
        raise ValueError("stairs edges must be finite and strictly increasing")
    # Step expansion holds each y from its riser onward: "pre" reads the value
    # right of each edge from the next point, so the first value repeats;
    # "post"/"mid" read it from the previous point, so the last value repeats.
    sy = np.concatenate((vals[:1], vals)) if where == "pre" else np.append(vals, vals[-1])
    return self.step(
        edge_values,
        sy,
        where=where,
        name=name,
        color=color,
        width=width,
        opacity=opacity,
        dash=dash,
        style=style,
    )


def ecdf(
    self: "Figure",
    values: ArrayLike,
    *,
    bins: Optional[int] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Union[str, Sequence[float], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add an empirical cumulative distribution function.

    Exact mode coalesces repeated values before shipping. ``bins`` provides a
    bounded approximation for very large distributions using the native
    histogram kernel.
    """
    vals = self._as_1d_float(values, "ecdf values")
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        raise ValueError("ecdf values must contain at least one finite value")
    if bins is not None:
        if (
            isinstance(bins, (bool, np.bool_))
            or not isinstance(bins, (int, np.integer))
            or int(bins) <= 0
        ):
            raise ValueError("ecdf bins must be a positive integer or None")
        lo, hi = self._auto_domain(kernels.min_max(vals))
        counts, edges = kernels.histogram_uniform(vals, lo, hi, int(bins), density=False)
        keep = counts > 0
        # A bin's cumulative mass is only guaranteed at its RIGHT edge; the
        # left edge would bias the CDF up by as much as one bin. Anchoring 0
        # at edges[0] keeps the step right-continuous and never above the
        # exact ECDF.
        sx = np.concatenate(([edges[0]], edges[1:][keep]))
        sy = np.concatenate(([0.0], np.cumsum(counts)[keep] / len(vals)))
        return self.step(
            sx,
            sy,
            where="post",
            name=name,
            color=color,
            width=width,
            opacity=opacity,
            dash=dash,
            style=style,
        )
    unique, counts = np.unique(vals, return_counts=True)
    cdf = np.cumsum(counts, dtype=np.float64) / len(vals)
    sx = np.concatenate(([unique[0]], unique))
    sy = np.concatenate(([0.0], cdf))
    return self.step(
        sx,
        sy,
        where="post",
        name=name,
        color=color,
        width=width,
        opacity=opacity,
        dash=dash,
        style=style,
    )


def stem(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    base: Union[Scalar, ArrayLike] = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    opacity: float = 1.0,
    marker: bool = True,
    marker_size: float = 5.0,
    symbol: str = "circle",
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add vertical stem segments and optional point markers."""
    css = styles.compile_mark_style("stem", style)
    color = css.get("color", color)
    width = css.get("width", width)
    opacity = css.get("opacity", opacity)
    name = self._optional_text(name, "stem name")
    color = self._optional_css_color(color, "stem color")
    if color is None:
        color = default_palette_color(len(self.traces))
    width = self._positive_scalar(width, "stem width")
    opacity = self._opacity(opacity, "stem opacity")
    marker_size = self._nonnegative_scalar(marker_size, "stem marker_size")
    symbol = _validate.point_symbol(symbol, "stem symbol")
    checkpoint = self._checkpoint()
    try:
        xc, yc = self._ingest_xy(x, y, "stem")
        basev = self._broadcast_base(base, len(xc), "stem")
        self._append_segment_trace(
            "stem",
            xc.values,
            xc.values,
            basev,
            yc.values,
            name=name,
            color=color,
            opacity=opacity,
            width=width,
            role="stem",
            count=len(xc),
            extra_style=styles._opacity_channels(css),
        )
        if marker:
            self.scatter(
                xc.values,
                yc.values,
                name=None,
                color=color,
                size=marker_size,
                opacity=opacity,
                density=None,
                symbol=symbol,
            )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def scatter(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    name: Optional[str] = None,
    color: Union[str, ArrayLike, None] = None,
    size: Union[Scalar, ArrayLike, None] = 4.0,
    opacity: Any = 0.8,
    zoom_size_factor: float = 1.0,
    zoom_opacity: Optional[float] = None,
    zoom_emphasis: float = 16.0,
    colormap: str = channels.DEFAULT_COLORMAP,
    color_domain: Optional[tuple[float, float]] = None,
    size_range: tuple[float, float] = (2.0, 18.0),
    density: Optional[bool] = None,
    symbol: Any = "circle",
    stroke: Any = None,
    stroke_width: Any = 0.0,
    _artist_alpha: Any = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a scatter trace.

    `color` may be a CSS color (constant), a numeric array (continuous →
    colormap), or a categorical array (factorized → palette). `size` may be
    a scalar or a numeric array (mapped to `size_range` px). `symbol` picks
    one of the 17 renderer-backed marker shapes; `stroke` / `stroke_width`
    draw a point border. Large scatters automatically switch to an aggregated
    density surface; pass `density=True/False` to force or disable it.

    `zoom_size_factor` multiplies marker sizes and `zoom_opacity` sets their
    target opacity at `zoom_emphasis` times the initial view scale. The client
    interpolates both in logarithmic zoom space and clamps at the target.
    Defaults keep marker styling fixed at every zoom level.
    """
    css = styles.compile_mark_style("scatter", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    stroke = css.get("stroke", stroke)
    stroke_width = css.get("stroke_width", stroke_width)
    name = self._optional_text(name, "scatter name")
    zoom_size_factor = self._nonnegative_scalar(zoom_size_factor, "scatter zoom_size_factor")
    if zoom_size_factor == 0.0:
        raise ValueError("scatter zoom_size_factor must be > 0")
    if zoom_opacity is not None:
        zoom_opacity = self._opacity(zoom_opacity, "scatter zoom_opacity")
    zoom_emphasis = self._nonnegative_scalar(zoom_emphasis, "scatter zoom_emphasis")
    if zoom_emphasis <= 1.0:
        raise ValueError("scatter zoom_emphasis must be > 1")
    density = self._optional_bool(density, "scatter density")
    checkpoint = self._checkpoint()
    try:
        xc, yc = self._ingest_xy(x, y, "scatter")
        n = len(xc)
        style_channels: dict[str, channels.StyleChannel] = {}
        opacity_value = _direct_style(
            opacity,
            n,
            "scatter opacity",
            style_channels,
            "opacity",
            default=0.8,
            minimum=0.0,
            maximum=1.0,
        )
        artist_alpha_value: Optional[float] = None
        if _artist_alpha is not None:
            alpha_value, alpha_ch = channels.resolve_style_channel(
                _artist_alpha, n, "scatter alpha", minimum=0.0, maximum=1.0
            )
            if alpha_ch is not None:
                style_channels["artist_alpha"] = alpha_ch
            elif alpha_value is not None:
                artist_alpha_value = float(alpha_value)
        symbol_value = _direct_symbols(symbol, n, style_channels)
        stroke_value, stroke_ch = _stroke_channel(stroke, n, "scatter stroke")
        stroke_width_value = _direct_style(
            stroke_width,
            n,
            "scatter stroke_width",
            style_channels,
            "stroke_width",
            default=0.0,
            minimum=0.0,
        )
        if (
            (stroke_value is not None or stroke_ch is not None)
            and not stroke_width_value
            and ("stroke_width" not in style_channels)
        ):
            stroke_width_value = 1.0
        if (
            stroke_value is None
            and stroke_ch is None
            and (stroke_width_value or "stroke_width" in style_channels)
        ):
            stroke_ch = channels.ColorChannel(mode="match_fill")
        default_color = default_palette_color(len(self.traces))
        color_ch = channels.resolve_color(
            color, n, colormap=colormap, default_constant=default_color, domain=color_domain
        )
        size_ch = channels.resolve_size(size, n, range_px=size_range)

        point_style: dict[str, Any] = {"opacity": opacity_value}
        if artist_alpha_value is not None:
            point_style["artist_alpha"] = artist_alpha_value
        if zoom_size_factor != 1.0:
            point_style["zoom_size_factor"] = zoom_size_factor
        if zoom_opacity is not None:
            point_style["zoom_opacity"] = zoom_opacity
        if zoom_size_factor != 1.0 or zoom_opacity is not None:
            point_style["zoom_emphasis"] = zoom_emphasis
        point_style.update(styles._opacity_channels(css))
        if symbol_value != "circle":
            point_style["symbol"] = symbol_value
        if stroke_value is not None:
            point_style["stroke"] = stroke_value
        if stroke_width_value:
            point_style["stroke_width"] = stroke_width_value

        trace = Trace(
            id=len(self.traces),
            kind="scatter",
            x=xc,
            y=yc,
            name=name,
            style=point_style,
            color_ch=color_ch,
            stroke_ch=stroke_ch,
            size_ch=size_ch,
            style_channels=style_channels,
            force_density=density,
        )

        # The color channel survives aggregation as the density surface's
        # per-cell mean point color (LOD doc §2); every other per-item
        # channel is dropped at Tier 2 — allowed, never silent (§28).
        color_aggregates = channels.bins_mean_color(trace.color_ch)
        dropped_channels = tuple(
            name
            for name in trace.per_item_channel_names()
            if not (color_aggregates and name == "color")
        )
        mean_color_note = (
            " The color channel is kept as the surface's per-cell mean point color"
            " (count drives the alpha)."
            if color_aggregates
            else ""
        )
        if density is None and dropped_channels and n > DIRECT_SOFT_CEILING:
            warnings.warn(
                f"scatter has {n:,} points with per-point styles — above the "
                f"direct ceiling ({DIRECT_SOFT_CEILING:,}). Falling back to a "
                f"density surface; dropped channels: {', '.join(dropped_channels)} "
                "(aggregating arbitrary instance styles needs the §5-F5 aggregation algebra, not yet "
                f"implemented).{mean_color_note} "
                "Pass density=False to keep direct draw at your risk.",
                RuntimeWarning,
                stacklevel=2,
            )
            trace.force_density = True
        elif density is None and n > DIRECT_SOFT_CEILING:
            warnings.warn(
                f"scatter has {n:,} points above the soft ceiling "
                f"({DIRECT_SOFT_CEILING:,}); using a density surface for the "
                f"initial render.{mean_color_note}",
                RuntimeWarning,
                stacklevel=2,
            )
        elif density is False and n > DIRECT_SOFT_CEILING:
            # §28: opting out of aggregation above the ceiling is allowed but
            # never silent — fill-rate and the ~1 GB allocation cliff are real (§5 F3).
            warnings.warn(
                f"density=False with {n:,} points forces direct draw above the "
                f"ceiling ({DIRECT_SOFT_CEILING:,}); expect fill-rate-bound frames "
                "and possible buffer-allocation failure.",
                RuntimeWarning,
                stacklevel=2,
            )

        self.traces.append(trace)
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def histogram(
    self: "Figure",
    values: ArrayLike,
    *,
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
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a 1D histogram backed by the shared rectangle primitive.

    `cumulative=True` accumulates bins left-to-right: with the default
    count mode the last bin equals the number of in-range values; combined
    with `density=True` it becomes the empirical CDF (last bin ~1.0).
    """
    css = styles.compile_mark_style("histogram", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    corner_radius = css.get("corner_radius", corner_radius)
    stroke = css.get("stroke", stroke)
    stroke_width = css.get("stroke_width", stroke_width)
    fill = css.get("fill", fill)
    name = self._optional_text(name, "histogram name")
    density = self._bool_param(density, "histogram density")
    cumulative = self._bool_param(cumulative, "histogram cumulative")
    vals = self._as_1d_float(values, "histogram values")
    if density and not np.isfinite(vals).any():
        raise ValueError("histogram density requires at least one finite value")
    if isinstance(bins, (int, np.integer)) and not isinstance(bins, bool):
        n_bins = int(bins)
        if n_bins <= 0:
            raise ValueError("histogram bins must be positive")
        if range is None:
            lo, hi = self._auto_domain(kernels.min_max(vals))
        else:
            lo, hi = self._finite_increasing_pair(range, "histogram range")
        counts, edges = kernels.histogram_uniform(vals, lo, hi, n_bins, density=density)
    else:
        finite = vals[np.isfinite(vals)]
        hist_bins = 10 if len(finite) == 0 and isinstance(bins, str) else bins
        hist_range = (
            None if range is None else self._finite_increasing_pair(range, "histogram range")
        )
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            counts, edges = np.histogram(finite, bins=hist_bins, range=hist_range, density=density)
        if not np.isfinite(counts).all() or not np.isfinite(edges).all():
            raise ValueError("histogram could not produce finite bins")
    counts = counts.astype(np.float64, copy=False)
    if cumulative:
        # Density mode integrates density*width into an empirical CDF whose
        # last bin is ~1.0 (exactly 1.0 when every value is in range); count
        # mode simply accumulates bin counts.
        counts = np.cumsum(counts * np.diff(edges)) if density else np.cumsum(counts)
    n_bins = len(counts)
    direct_color = (
        channels.resolve_color(color, n_bins, default_constant=DEFAULT_PALETTE[0])
        if color is not None and not isinstance(color, str)
        else None
    )
    color_value = color if direct_color is None else None
    stroke_value, stroke_channel = _stroke_channel(stroke, n_bins, "histogram stroke")
    opacity_value, opacity_channels = _series_style_values(
        opacity,
        1,
        n_bins,
        "histogram opacity",
        "opacity",
        default=0.85,
        minimum=0.0,
        maximum=1.0,
    )
    width_value, width_channels = _series_style_values(
        stroke_width,
        1,
        n_bins,
        "histogram stroke_width",
        "stroke_width",
        default=0.0,
        minimum=0.0,
    )
    constant_radius, radius_channels = _series_corner_radius(
        corner_radius, 1, n_bins, "histogram corner_radius"
    )
    _, alpha_channels = _series_style_values(
        _artist_alpha,
        1,
        n_bins,
        "histogram alpha",
        "artist_alpha",
        default=-1.0,
        minimum=-1.0,
        maximum=1.0,
    )
    mark_style = self._rect_mark_style(
        "histogram", constant_radius, stroke_value, width_value[0], fill
    )
    mark_style.update(styles._opacity_channels(css))
    style_channels = {
        **opacity_channels[0],
        **width_channels[0],
        **radius_channels[0],
        **alpha_channels[0],
    }
    zeros = np.zeros_like(counts, dtype=np.float64)
    self._append_rect_trace(
        "histogram",
        edges[:-1],
        edges[1:],
        zeros,
        counts,
        name=name,
        color=color_value,
        opacity=opacity_value[0],
        role="histogram",
        count=int(len(vals)),
        extra_style={"cumulative": cumulative, "density": density, **mark_style},
        color_ch=direct_color,
        stroke_ch=stroke_channel,
        style_channels=style_channels,
    )
    return self


def hist(
    self: "Figure",
    values: ArrayLike,
    *,
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
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Short alias for `histogram(...)`, matching common Python chart APIs."""
    return self.histogram(
        values,
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
    )


def box(
    self: "Figure",
    values: ArrayLike,
    *,
    x: Optional[ArrayLike] = None,
    group: Optional[ArrayLike] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.6,
    opacity: float = 0.85,
    orientation: str = "vertical",
    show_outliers: bool = True,
    outlier_size: float = 4.0,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add grouped Tukey box plots from 1-D or column-oriented 2-D values."""
    css = styles.compile_mark_style("box", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError("box orientation must be 'vertical' or 'horizontal'")
    name = self._optional_text(name, "box name")
    color = self._optional_css_color(color, "box color")
    if color is None:
        color = default_palette_color(len(self.traces))
    width = self._positive_scalar(width, "box width")
    opacity = self._opacity(opacity, "box opacity")
    show_outliers = self._bool_param(show_outliers, "box show_outliers")
    outlier_size = self._nonnegative_scalar(outlier_size, "box outlier_size")
    groups, positions = _distribution_groups(self, values, x, group, "box")
    if len(groups) != len(positions):
        raise ValueError("box groups and positions must have equal length")
    stats = [_distribution_stats(g) for g in groups]
    finite_stats = [s for s in stats if np.isfinite(s[0])]
    if not finite_stats:
        raise ValueError("box values must contain at least one finite group")
    checkpoint = self._checkpoint()
    try:
        self._commit_axis_positions(x if x is not None else group, "x")
        q1 = np.asarray([s[0] for s in stats], dtype=np.float64)
        med = np.asarray([s[1] for s in stats], dtype=np.float64)
        q3 = np.asarray([s[2] for s in stats], dtype=np.float64)
        low = np.asarray([s[3] for s in stats], dtype=np.float64)
        high = np.asarray([s[4] for s in stats], dtype=np.float64)
        valid = np.isfinite(q1) & np.isfinite(q3)
        centers = np.asarray(positions, dtype=np.float64)
        if orientation == "vertical":
            bx0, bx1, by0, by1 = centers - width / 2.0, centers + width / 2.0, q1, q3
            wx0, wx1, wy0, wy1 = (
                np.concatenate(
                    (centers[valid], centers[valid] - width * 0.3, centers[valid] - width * 0.3)
                ),
                np.concatenate(
                    (centers[valid], centers[valid] + width * 0.3, centers[valid] + width * 0.3)
                ),
                np.concatenate((low[valid], low[valid], high[valid])),
                np.concatenate((high[valid], low[valid], high[valid])),
            )
            mx0, mx1, my0, my1 = (
                centers[valid] - width / 2.0,
                centers[valid] + width / 2.0,
                med[valid],
                med[valid],
            )
        else:
            bx0, bx1, by0, by1 = q1, q3, centers - width / 2.0, centers + width / 2.0
            wx0, wx1, wy0, wy1 = (
                np.concatenate((low[valid], low[valid], high[valid])),
                np.concatenate((high[valid], low[valid], high[valid])),
                np.concatenate(
                    (centers[valid], centers[valid] - width * 0.3, centers[valid] - width * 0.3)
                ),
                np.concatenate(
                    (centers[valid], centers[valid] + width * 0.3, centers[valid] + width * 0.3)
                ),
            )
            mx0, mx1, my0, my1 = (
                med[valid],
                med[valid],
                centers[valid] - width / 2.0,
                centers[valid] + width / 2.0,
            )
        self._append_segment_trace(
            "box_whisker",
            wx0,
            wx1,
            wy0,
            wy1,
            name=None,
            color=color,
            opacity=opacity,
            width=1.0,
            role="box-whisker",
        )
        self._append_rect_trace(
            "box",
            bx0[valid],
            bx1[valid],
            by0[valid],
            by1[valid],
            name=name,
            color=color,
            opacity=opacity,
            role="box",
            extra_style={
                "stroke_width": 1.0,
                "box_orientation": orientation,
                **styles._opacity_channels(css),
            },
        )
        self._append_segment_trace(
            "box_median",
            mx0,
            mx1,
            my0,
            my1,
            name=None,
            color=color,
            opacity=opacity,
            width=1.4,
            role="box-median",
        )
        if show_outliers:
            out_x: list[float] = []
            out_y: list[float] = []
            rng = np.random.default_rng(0)
            for center, s in zip(centers, stats, strict=True):
                points = s[5]
                jitter = rng.uniform(-width * 0.12, width * 0.12, len(points))
                if orientation == "vertical":
                    out_x.extend((center + jitter).tolist())
                    out_y.extend(points.tolist())
                else:
                    out_x.extend(points.tolist())
                    out_y.extend((center + jitter).tolist())
            if out_x:
                self.scatter(
                    out_x,
                    out_y,
                    name=None,
                    color=color,
                    size=outlier_size,
                    opacity=opacity,
                    density=None,
                    symbol="circle",
                )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def violin(
    self: "Figure",
    values: ArrayLike,
    *,
    x: Optional[ArrayLike] = None,
    group: Optional[ArrayLike] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.8,
    bins: int = 64,
    opacity: float = 0.55,
    orientation: str = "vertical",
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add bounded-resolution violin distributions.

    Density estimation is a smoothed histogram computed once in Python; each
    group ships its fixed ``bins``-sized band set. The client draws the bands
    through the shared instanced rectangle path, so input cardinality does not
    become DOM/GPU object cardinality.
    """
    css = styles.compile_mark_style("violin", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError("violin orientation must be 'vertical' or 'horizontal'")
    if (
        isinstance(bins, (bool, np.bool_))
        or not isinstance(bins, (int, np.integer))
        or int(bins) < 4
        or int(bins) > 1024
    ):
        raise ValueError("violin bins must be an integer between 4 and 1024")
    name = self._optional_text(name, "violin name")
    color = self._optional_css_color(color, "violin color")
    width = self._positive_scalar(width, "violin width")
    opacity = self._opacity(opacity, "violin opacity")
    groups, positions = _distribution_groups(self, values, x, group, "violin")
    rect_x0: list[np.ndarray] = []
    rect_x1: list[np.ndarray] = []
    rect_y0: list[np.ndarray] = []
    rect_y1: list[np.ndarray] = []
    n_bins = int(bins)
    kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    # mode="same" truncates the kernel at the boundaries; dividing by the
    # per-bin kernel coverage keeps edge bins at full weight instead of
    # pinching violins whose data piles at the min/max.
    coverage = np.convolve(np.ones(n_bins), kernel, mode="same")
    for center, group_values in zip(positions, groups, strict=True):
        finite = group_values[np.isfinite(group_values)]
        if len(finite) == 0:
            continue
        lo, hi = float(np.min(finite)), float(np.max(finite))
        if lo == hi:
            lo -= 0.5
            hi += 0.5
        edges = np.linspace(lo, hi, n_bins + 1)
        counts, _ = np.histogram(finite, bins=edges)
        smooth = np.convolve(counts.astype(np.float64), kernel, mode="same") / coverage
        peak = float(np.max(smooth)) or 1.0
        half_width = width * 0.5 * smooth / peak
        if orientation == "vertical":
            rect_x0.append(center - half_width)
            rect_x1.append(center + half_width)
            rect_y0.append(edges[:-1])
            rect_y1.append(edges[1:])
        else:
            rect_x0.append(edges[:-1])
            rect_x1.append(edges[1:])
            rect_y0.append(center - half_width)
            rect_y1.append(center + half_width)
    if not rect_x0:
        raise ValueError("violin values must contain at least one finite group")
    checkpoint = self._checkpoint()
    try:
        self._commit_axis_positions(x if x is not None else group, "x")
        self._append_rect_trace(
            "violin",
            np.concatenate(rect_x0),
            np.concatenate(rect_x1),
            np.concatenate(rect_y0),
            np.concatenate(rect_y1),
            name=name,
            color=color,
            opacity=opacity,
            role="violin",
            extra_style=styles._opacity_channels(css),
        )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self


def hexbin(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    gridsize: int | tuple[int, int] = 64,
    range: Optional[tuple[tuple[float, float], tuple[float, float]]] = None,
    bins: str = "count",
    C: Optional[ArrayLike] = None,
    reduce_C_function: Callable[[np.ndarray], Scalar] = np.mean,
    mincnt: Optional[int] = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    opacity: float = 0.9,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a screen-bounded hexagonal density plot.

    Binning is performed by the native 2-D kernel. Only occupied bins are
    shipped as centers plus one scalar count/color channel.
    """
    css = styles.compile_mark_style("hexbin", style)
    opacity = css.get("opacity", opacity)
    if isinstance(gridsize, (int, np.integer)) and not isinstance(gridsize, (bool, np.bool_)):
        w = int(gridsize)
        h = max(2, int(w / np.sqrt(3.0)))
    elif isinstance(gridsize, (tuple, list)) and len(gridsize) == 2:
        if any(
            isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
            for value in gridsize
        ):
            raise ValueError("hexbin gridsize dimensions must be integers")
        w, h = int(gridsize[0]), int(gridsize[1])
    else:
        raise ValueError("hexbin gridsize must be a positive integer or (width, height)")
    if w < 2 or h < 2:
        raise ValueError("hexbin gridsize dimensions must be >= 2")
    if w > 2048 or h > 2048:
        raise ValueError("hexbin gridsize dimensions must be <= 2048")
    if bins not in {"count", "log"}:
        raise ValueError("hexbin bins must be 'count' or 'log'")
    name = self._optional_text(name, "hexbin name")
    opacity = self._opacity(opacity, "hexbin opacity")
    if not channels.is_colormap(colormap):
        raise ValueError(f"unknown colormap {colormap!r}; known: {channels.COLORMAPS}")
    # Canonicalize WITHOUT ingesting: only occupied bin centers ship, so the
    # raw points must not stay resident in the figure's column store.
    x_all, _x_kind, _x_copies = columns._canonicalize(x)
    y_all, _y_kind, _y_copies = columns._canonicalize(y)
    if len(x_all) != len(y_all):
        raise ValueError(
            f"hexbin x and y must have equal length, got {len(x_all)} and {len(y_all)}"
        )
    n_points = len(x_all)
    c_all = None
    if C is not None:
        c_all, _c_kind, _c_copies = columns._canonicalize(C)
        if len(c_all) != len(x_all):
            raise ValueError("hexbin C must have the same length as x and y")
    finite = np.isfinite(x_all) & np.isfinite(y_all)
    if c_all is not None:
        finite &= np.isfinite(c_all)
    if not np.any(finite):
        raise ValueError("hexbin x and y must contain at least one finite pair")
    xv, yv = x_all[finite], y_all[finite]
    cv = None if c_all is None else c_all[finite]
    if range is None:
        xr = self._auto_domain(kernels.min_max(xv))
        yr = self._auto_domain(kernels.min_max(yv))
    else:
        if len(range) != 2:
            raise ValueError("hexbin range must be ((x0, x1), (y0, y1))")
        xr = self._finite_increasing_pair(range[0], "hexbin x range")
        yr = self._finite_increasing_pair(range[1], "hexbin y range")
    # Matplotlib displays zero-count cells when C is absent and mincnt is not
    # specified, producing the full rectangular honeycomb. Reducer hexbins
    # cannot reduce an empty group and therefore default to one observation.
    threshold = (0 if cv is None else 1) if mincnt is None else int(mincnt)
    if threshold < 0:
        raise ValueError("hexbin mincnt must be nonnegative")
    # Matplotlib's hex lattice is the union of an integer grid and a half-cell
    # offset grid. Assign each point to the nearer center in the hex metric;
    # rectangular binning plus staggered display centers leaves overlaps and
    # gaps and, more importantly, puts values in the wrong cells.
    fx = (xv - xr[0]) * w / (xr[1] - xr[0])
    fy = (yv - yr[0]) * h / (yr[1] - yr[0])
    ix1 = np.rint(fx).astype(np.int64)
    iy1 = np.rint(fy).astype(np.int64)
    ix2 = np.floor(fx).astype(np.int64)
    iy2 = np.floor(fy).astype(np.int64)
    use_first = (fx - ix1) ** 2 + 3.0 * (fy - iy1) ** 2 < (
        (fx - ix2 - 0.5) ** 2 + 3.0 * (fy - iy2 - 0.5) ** 2
    )
    valid_first = use_first & (ix1 >= 0) & (ix1 <= w) & (iy1 >= 0) & (iy1 <= h)
    valid_second = ~use_first & (ix2 >= 0) & (ix2 < w) & (iy2 >= 0) & (iy2 < h)
    if not np.any(valid_first | valid_second):
        raise ValueError("hexbin range contains no finite points")
    flat1 = iy1 * (w + 1) + ix1
    flat2 = iy2 * w + ix2
    count1 = np.bincount(flat1[valid_first], minlength=(w + 1) * (h + 1)).astype(float)
    count2 = np.bincount(flat2[valid_second], minlength=w * h).astype(float)
    keep1 = np.flatnonzero(count1 >= threshold)
    keep2 = np.flatnonzero(count2 >= threshold)
    counts = np.concatenate((count1[keep1], count2[keep2]))
    if len(counts) == 0:
        raise ValueError("hexbin range contains no finite points")
    dx, dy = (xr[1] - xr[0]) / w, (yr[1] - yr[0]) / h
    centers_x = np.concatenate((xr[0] + (keep1 % (w + 1)) * dx, xr[0] + (keep2 % w + 0.5) * dx))
    centers_y = np.concatenate((yr[0] + (keep1 // (w + 1)) * dy, yr[0] + (keep2 // w + 0.5) * dy))
    if cv is None:
        metric = np.log1p(counts) if bins == "log" else counts
    else:
        reduced: list[float] = []
        memberships = [cv[valid_first & (flat1 == flat)] for flat in keep1] + [
            cv[valid_second & (flat2 == flat)] for flat in keep2
        ]
        for values in memberships:
            made = np.asarray(reduce_C_function(values))
            if made.ndim != 0 or not np.isfinite(made):
                raise ValueError("hexbin reduce_C_function must return one finite scalar per bin")
            reduced.append(float(made))
        metric = np.asarray(reduced, dtype=np.float64)
    color_ch = channels.resolve_color(
        metric, len(metric), colormap=colormap, default_constant=DEFAULT_PALETTE[0]
    )
    checkpoint = self._checkpoint()
    try:
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="hexbin",
                x=self.store.ingest(centers_x),
                y=self.store.ingest(centers_y),
                name=name,
                style={
                    "color": default_palette_color(len(self.traces)),
                    "opacity": opacity,
                    "hex_dx": dx,
                    "hex_dy": dy,
                    **styles._opacity_channels(css),
                },
                color_ch=color_ch,
                size_ch=channels.SizeChannel(mode="constant", constant=8.0),
                count=int(n_points),
            )
        )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def _interpolate_contourf_grid(
    arr: np.ndarray, xpos: np.ndarray, ypos: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bilinearly densify a contour field before assigning discrete bands."""
    rows, cols = arr.shape

    def sample_count(size: int) -> int:
        # Eight samples per source interval removes visible cell stair-steps for
        # common scientific grids. The 512 target keeps the shipped grid bounded;
        # inputs already larger than that are never downsampled.
        return min((size - 1) * 8 + 1, max(size, 512))

    out_rows, out_cols = sample_count(rows), sample_count(cols)
    if (out_rows, out_cols) == (rows, cols):
        return arr, xpos, ypos

    row_at = np.linspace(0.0, rows - 1, out_rows)
    col_at = np.linspace(0.0, cols - 1, out_cols)
    row0 = np.floor(row_at).astype(np.intp)
    col0 = np.floor(col_at).astype(np.intp)
    row1 = np.minimum(row0 + 1, rows - 1)
    col1 = np.minimum(col0 + 1, cols - 1)
    row_weight = (row_at - row0)[:, None]
    col_weight = (col_at - col0)[None, :]

    z00 = arr[row0[:, None], col0[None, :]]
    z10 = arr[row0[:, None], col1[None, :]]
    z01 = arr[row1[:, None], col0[None, :]]
    z11 = arr[row1[:, None], col1[None, :]]
    valid = np.isfinite(z00) & np.isfinite(z10) & np.isfinite(z01) & np.isfinite(z11)
    interpolated = (
        z00 * (1.0 - row_weight) * (1.0 - col_weight)
        + z10 * (1.0 - row_weight) * col_weight
        + z01 * row_weight * (1.0 - col_weight)
        + z11 * row_weight * col_weight
    )
    interpolated[~valid] = np.nan
    dense_x = np.interp(col_at, np.arange(cols), xpos)
    dense_y = np.interp(row_at, np.arange(rows), ypos)
    return interpolated, dense_x, dense_y


def contour(
    self: "Figure",
    z: ArrayLike,
    *,
    x: Optional[ArrayLike] = None,
    y: Optional[ArrayLike] = None,
    levels: Union[int, ArrayLike] = 10,
    filled: bool = False,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    color: Optional[str] = None,
    width: float = 1.1,
    opacity: float = 0.9,
    dash_negative: bool = False,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add regular-grid contour isolines, optionally over a filled heatmap.

    `dash_negative` renders negative-level isolines dashed for a single-color
    contour (Matplotlib's monochrome convention); it is ignored when a colormap
    drives per-level color.
    """
    css = styles.compile_mark_style("contour", style)
    color = css.get("color", color)
    width = css.get("width", width)
    opacity = css.get("opacity", opacity)
    arr = self._as_float_array(z, "contour z")
    if arr.ndim != 2 or min(arr.shape) < 2:
        raise ValueError(
            f"contour z must be a 2-D matrix with at least 2 rows/columns, got {arr.shape}"
        )
    rows, cols = arr.shape
    xpos = self._heatmap_axis_positions(x, cols, "x")
    ypos = self._heatmap_axis_positions(y, rows, "y")
    finite = arr[np.isfinite(arr)]
    if len(finite) == 0:
        raise ValueError("contour z must contain at least one finite value")
    if isinstance(levels, (int, np.integer)) and not isinstance(levels, (bool, np.bool_)):
        n_levels = int(levels)
        if n_levels <= 0 or n_levels > 256:
            raise ValueError("contour levels must be between 1 and 256")
        lo, hi = self._auto_domain(kernels.min_max(finite))
        level_values = np.linspace(lo, hi, n_levels + 2, dtype=np.float64)[1:-1]
    else:
        level_values = self._as_1d_float(levels, "contour levels")
        if (
            len(level_values) == 0
            or len(level_values) > 256
            or not np.all(np.isfinite(level_values))
        ):
            raise ValueError("contour levels must contain 1 to 256 finite values")
        level_values = np.sort(level_values)
    work = (rows - 1) * (cols - 1) * len(level_values)
    if work > MAX_CONTOUR_WORK:
        raise ValueError(
            f"contour grid x levels exceeds the bounded work budget ({MAX_CONTOUR_WORK:,})"
        )
    if not channels.is_colormap(colormap):
        raise ValueError(f"unknown colormap {colormap!r}; known: {channels.COLORMAPS}")
    name = self._optional_text(name, "contour name")
    color = self._optional_css_color(color, "contour color")
    width = self._positive_scalar(width, "contour width")
    opacity = self._opacity(opacity, "contour opacity")
    # Checkpoint spans the optional filled heatmap too: a level set that never
    # intersects the grid must not leave a stray heatmap trace behind.
    checkpoint = self._checkpoint()
    try:
        if filled:
            # Matplotlib's contourf paints piecewise-constant bands *between*
            # consecutive levels, not a smooth ramp. Interpolate the scalar
            # field before snapping samples to band midpoints so boundaries
            # cross between source points instead of following square cells.
            # Values outside the level range stay unpainted (extend='neither').
            edges = np.asarray(level_values, dtype=np.float64)
            if len(edges) >= 2 and edges[0] < edges[-1]:
                dense, dense_x, dense_y = _interpolate_contourf_grid(arr, xpos, ypos)
                band = np.searchsorted(edges, dense, side="right") - 1
                mids = (edges[:-1] + edges[1:]) * 0.5
                banded = np.full(dense.shape, np.nan, dtype=np.float64)
                inside = np.isfinite(dense) & (band >= 0) & (band < len(edges) - 1)
                banded[inside] = mids[np.clip(band, 0, len(edges) - 2)][inside]
                self.heatmap(
                    banded,
                    x=dense_x,
                    y=dense_y,
                    name=name,
                    colormap=colormap,
                    domain=(float(edges[0]), float(edges[-1])),
                    opacity=min(opacity, 0.9),
                )
            else:
                self.heatmap(
                    arr,
                    x=x,
                    y=y,
                    name=name,
                    colormap=colormap,
                    opacity=min(opacity, 0.7),
                )
        x0, x1, y0, y1, level_values = _contour_segments(arr, xpos, ypos, level_values)
        if len(x0) == 0:
            raise ValueError("contour levels do not intersect the finite grid")
        domain = self._auto_domain((float(np.min(level_values)), float(np.max(level_values))))
        color_ch = (
            channels.ColorChannel(
                mode="continuous", values=level_values, domain=domain, colormap=colormap
            )
            if color is None
            else None
        )
        # contourf paints bands without outlining their boundaries. Users can
        # explicitly overlay contour() when isolines are desired.
        if not filled:
            # Matplotlib dashes negative isolines for a single-color contour. Split
            # the segment set by level sign so the negative group ships dashed; a
            # colormapped contour keeps every level solid.
            lv = np.asarray(level_values)
            if dash_negative and color is not None and np.any(lv < 0) and np.any(lv >= 0):
                # Matplotlib's dashed preset is scaled by the contour linewidth:
                # 3.7 on / 1.6 off times the rendered width.
                groups = ((lv >= 0, None), (lv < 0, [3.7 * width, 1.6 * width]))
            else:
                groups = ((np.ones(len(lv), dtype=bool), None),)
            for mask, dash in groups:
                self._append_segment_trace(
                    "contour",
                    x0[mask],
                    x1[mask],
                    y0[mask],
                    y1[mask],
                    name=name if dash is None else None,
                    color=color,
                    opacity=opacity,
                    width=width,
                    role="contour",
                    color_ch=color_ch,
                    dash=dash,
                    extra_style=styles._opacity_channels(css),
                )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self


def bar(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    name: Optional[str] = None,
    color: Any = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Union[Scalar, ArrayLike] = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: Any = 0.85,
    corner_radius: Any = 0.0,
    stroke: Any = None,
    stroke_width: Any = 0.0,
    _artist_alpha: Any = None,
    fill: Union[str, dict[str, str], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add vertical bars. 2D y values render grouped, stacked, or
    normalized (per-category fractions summing to 1) series.

    `corner_radius`/`stroke`/`stroke_width` are the CSS border analogues
    rendered into the mark; `fill` accepts a CSS `linear-gradient(...)`
    (spec/api/styling.md#styling-the-marks)."""
    css = styles.compile_mark_style("bar", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    corner_radius = css.get("corner_radius", corner_radius)
    stroke = css.get("stroke", stroke)
    stroke_width = css.get("stroke_width", stroke_width)
    fill = css.get("fill", fill)
    return _bar_like(
        self,
        "bar",
        x,
        y,
        name=name,
        color=color,
        colors=colors,
        width=width,
        base=base,
        mode=mode,
        orientation=orientation,
        series=series,
        opacity=opacity,
        corner_radius=corner_radius,
        stroke=stroke,
        stroke_width=stroke_width,
        artist_alpha=_artist_alpha,
        fill=fill,
        style_extra=styles._opacity_channels(css),
    )


def column(
    self: "Figure",
    x: ArrayLike,
    y: ArrayLike,
    *,
    name: Optional[str] = None,
    color: Union[str, Sequence[str], None] = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Union[Scalar, ArrayLike] = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: float = 0.85,
    corner_radius: Union[float, tuple[float, float]] = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Union[str, dict[str, str], None] = None,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Alias for vertical column charts; shares the bar/rect renderer."""
    css = styles.compile_mark_style("column", style)
    color = css.get("color", color)
    opacity = css.get("opacity", opacity)
    corner_radius = css.get("corner_radius", corner_radius)
    stroke = css.get("stroke", stroke)
    stroke_width = css.get("stroke_width", stroke_width)
    fill = css.get("fill", fill)
    return _bar_like(
        self,
        "column",
        x,
        y,
        name=name,
        color=color,
        colors=colors,
        width=width,
        base=base,
        mode=mode,
        orientation=orientation,
        series=series,
        opacity=opacity,
        corner_radius=corner_radius,
        stroke=stroke,
        stroke_width=stroke_width,
        fill=fill,
        style_extra=styles._opacity_channels(css),
    )


def heatmap(
    self: "Figure",
    z: Any,  # 2-D (rows, cols) or RGB(A) ArrayLike, or a DataFrame-like with .to_numpy()
    *,
    x: Optional[ArrayLike] = None,
    y: Optional[ArrayLike] = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    opacity: float = 0.95,
    style: styles.StyleMapping | None = None,
) -> "Figure":
    """Add a rectangular heatmap from a 2D value matrix.

    `z` is shaped `(rows, columns)`. Optional `x` and `y` arrays name the
    column/row centers; string/object arrays become categorical axes.
    """
    css = styles.compile_mark_style("heatmap", style)
    opacity = css.get("opacity", opacity)
    name = self._optional_text(name, "heatmap name")
    opacity = self._opacity(opacity, "heatmap opacity")
    if hasattr(z, "to_numpy"):
        z = z.to_numpy()
    arr = np.asarray(z)
    truecolor = arr.ndim == 3 and arr.shape[-1] in (3, 4)
    if not truecolor and arr.ndim != 2:
        raise ValueError(f"heatmap z must be 2-D or RGB(A), got shape {arr.shape}")
    if truecolor:
        rgba = np.asarray(arr, dtype=np.float64)
        if np.nanmax(rgba[..., :3]) > 1.0:
            rgba[..., :3] /= 255.0
        if rgba.shape[-1] == 3:
            rgba = np.dstack((rgba, np.ones(rgba.shape[:2], dtype=np.float64)))
        rgba = np.clip(rgba, 0.0, 1.0)
        rows, cols = rgba.shape[:2]
        zv = rgba[..., 0]
    else:
        zv = self._real_float_array(arr, "heatmap z")
        rows, cols = zv.shape
    xpos = self._heatmap_axis_positions(x, cols, "x")
    ypos = self._heatmap_axis_positions(y, rows, "y")
    x_edges = self._cell_edges(xpos, "heatmap x")
    y_edges = self._cell_edges(ypos, "heatmap y")
    z_flat = zv.reshape(-1)
    if not truecolor and not channels.is_colormap(colormap):
        raise ValueError(f"unknown colormap {colormap!r}; known: {channels.COLORMAPS}")
    explicit_domain = (
        None
        if truecolor or domain is None
        else self._finite_increasing_pair(domain, "heatmap domain")
    )
    checkpoint = self._checkpoint()
    try:
        self._commit_axis_positions(x, "x")
        self._commit_axis_positions(y, "y")
        grid = (
            self.store.ingest(z_flat)
            if explicit_domain is None
            else self.store.ingest(z_flat, defer_zone_maps=True)
        )
        if truecolor:
            lo, hi = 0.0, 1.0
        elif explicit_domain is None:
            bounds = (grid.min, grid.max)
            lo, hi = self._auto_domain(bounds if np.isfinite(bounds).all() else None)
        else:
            lo, hi = explicit_domain
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="heatmap",
                x=self.store.ingest(np.array([x_edges[0], x_edges[-1]], dtype=np.float64)),
                y=self.store.ingest(np.array([y_edges[0], y_edges[-1]], dtype=np.float64)),
                grid=grid,
                rgba_grid=(
                    (
                        self.store.ingest(rgba[..., 0].reshape(-1)),
                        self.store.ingest(rgba[..., 1].reshape(-1)),
                        self.store.ingest(rgba[..., 2].reshape(-1)),
                        self.store.ingest(rgba[..., 3].reshape(-1)),
                    )
                    if truecolor
                    else None
                ),
                grid_shape=(rows, cols),
                count=int(z_flat.size),
                name=name,
                style={
                    "opacity": opacity,
                    "role": "heatmap",
                    "colormap": colormap,
                    "domain": [lo, hi],
                    "truecolor": truecolor,
                    "x_range": [float(x_edges[0]), float(x_edges[-1])],
                    "y_range": [float(y_edges[0]), float(y_edges[-1])],
                    **styles._opacity_channels(css),
                },
            )
        )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self
