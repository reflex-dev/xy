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
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import _validate, channels, columns, kernels
from ._trace import Trace
from .config import DEFAULT_PALETTE, DIRECT_SOFT_CEILING, MAX_CONTOUR_WORK

if TYPE_CHECKING:
    from ._figure import Figure


def _append_segment_trace(
    self,
    kind: str,
    x0: Any,
    x1: Any,
    y0: Any,
    y1: Any,
    *,
    name: Optional[str],
    color: Optional[str],
    opacity: float,
    width: float,
    role: str,
    color_ch: Any = None,
    count: Optional[int] = None,
    dash: Optional[str] = None,
) -> None:
    """Append a compact instanced line-segment trace.

    Error bars, stems, box whiskers, and contour isolines all have the same
    transport shape. Keeping that shape here avoids one trace/object per
    segment while allowing the browser and static exporters to share one
    renderer.
    """
    name = self._optional_text(name, f"{kind} name")
    opacity = self._opacity(opacity, f"{kind} opacity")
    width = self._positive_scalar(width, f"{kind} width")
    arrays = [
        self._as_1d_float(v, f"{kind} {label}")
        for label, v in (("x0", x0), ("x1", x1), ("y0", y0), ("y1", y1))
    ]
    if len({len(v) for v in arrays}) != 1:
        raise ValueError(f"{kind} segment columns must have equal length")
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
                    "opacity": opacity,
                    "width": width,
                    "role": role,
                    **({"dash": dash} if dash else {}),
                },
                color_ch=color_ch,
                count=count,
            )
        )
    except Exception:
        self._rollback(checkpoint)
        raise


def segments(
    self,
    x0: Any,
    y0: Any,
    x1: Any,
    y1: Any,
    *,
    name: Optional[str] = None,
    color: Any = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    width: float = 1.2,
    opacity: float = 1.0,
) -> "Figure":
    """Add independent line segments through the shared instanced renderer."""
    arrays = [self._as_1d_float(values, "segments color geometry") for values in (x0, y0, x1, y1)]
    if len({len(values) for values in arrays}) != 1:
        raise ValueError("segments coordinate columns must have equal length")
    default = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
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
    )
    return self


def triangle_mesh(
    self,
    x0: Any,
    y0: Any,
    x1: Any,
    y1: Any,
    x2: Any,
    y2: Any,
    *,
    color: Any = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    name: Optional[str] = None,
    opacity: float = 1.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
) -> "Figure":
    """Add independently colored filled triangles as one instanced mesh."""
    name = self._optional_text(name, "triangle_mesh name")
    opacity = self._opacity(opacity, "triangle_mesh opacity")
    stroke = self._optional_css_color(stroke, "triangle_mesh stroke")
    stroke_width = self._nonnegative_scalar(stroke_width, "triangle_mesh stroke_width")
    if stroke is not None and stroke_width == 0.0:
        stroke_width = 1.0
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
    default_color = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
    color_ch = channels.resolve_color(color, n, colormap=colormap, default_constant=default_color)
    if domain is not None:
        if color_ch.mode != "continuous":
            raise ValueError("triangle_mesh domain requires a continuous numeric color array")
        color_ch.domain = self._finite_increasing_pair(domain, "triangle_mesh domain")
    checkpoint = self._checkpoint()
    try:
        x0c, y0c, x1c, y1c, x2c, y2c = [self.store.ingest(values) for values in arrays]
        style: dict[str, Any] = {"opacity": opacity, "role": "triangle-mesh"}
        if stroke is not None:
            style["stroke"] = stroke
        if stroke_width:
            style["stroke_width"] = stroke_width
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
                count=n,
            )
        )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def _error_extent(
    value: Any, n: int, center: np.ndarray, label: str
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
    self, values: Any, x: Any, group: Any, kind: str
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
):
    """Extract flat contour segments through the native marching-squares kernel."""
    return kernels.marching_squares(z, x_coords, y_coords, levels)


def _bar_like(
    self,
    kind: str,
    x: Any,
    y: Any,
    *,
    name: Optional[str],
    color: Any,
    colors: Optional[list[str]],
    width: float,
    base: Any,
    mode: str,
    orientation: str,
    series: Optional[list[str]],
    opacity: float,
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
) -> "Figure":
    name = self._optional_text(name, f"{kind} name")
    width = self._positive_scalar(width, f"{kind} width")
    opacity = self._opacity(opacity, f"{kind} opacity")
    mark_style = self._rect_mark_style(kind, corner_radius, stroke, stroke_width, fill)
    if mode not in {"grouped", "stacked", "normalized"}:
        raise ValueError(f"{kind} mode must be 'grouped', 'stacked', or 'normalized'")
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError(f"{kind} orientation must be 'vertical' or 'horizontal'")
    category_axis = "x" if orientation == "vertical" else "y"
    pos, category_labels = self._axis_positions_with_labels(x, category_axis)
    vals = self._bar_value_matrix(y, len(pos), kind)
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
    series_names = self._series_names(name, series, vals.shape[0])
    series_colors = self._series_colors(color, colors, vals.shape[0])
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
                opacity=opacity,
                # grouped/stacked are no-ops for one series, but normalized
                # rescales even a single series — record it (§28).
                role=f"{kind}-normalized" if mode == "normalized" else kind,
                extra_style=mark_style,
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
                    opacity=opacity,
                    role=f"{kind}-grouped",
                    extra_style=mark_style,
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
                    opacity=opacity,
                    role=f"{kind}-{mode}",
                    extra_style=mark_style,
                )
                pos_base = np.where(row >= 0, y1, pos_base)
                neg_base = np.where(row < 0, y1, neg_base)
    except Exception:
        self._rollback(checkpoint)
        raise
    return self


def line(
    self,
    x: Any,
    y: Any,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    curve: str = "linear",
    dash: Any = None,
) -> "Figure":
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
    self,
    x: Any,
    y: Any,
    *,
    base: Any = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.35,
    line_width: float = 1.2,
    line_opacity: float = 1.0,
    fill: Any = None,
    curve: str = "linear",
    dash: Any = None,
) -> "Figure":
    """Add a filled area trace between `y` and `base`.

    `base` may be a scalar or a length-N array, which covers both the common
    zero-baseline area chart and future stacked-area construction.
    `fill` accepts a CSS `linear-gradient(...)` (see docs/styling.md);
    `curve="smooth"` renders a monotone cubic through the points; `dash`
    dashes the outline.
    """
    name = self._optional_text(name, "area name")
    color = self._optional_css_color(color, "area color")
    opacity = self._opacity(opacity, "area opacity")
    line_width = self._nonnegative_scalar(line_width, "area line_width")
    line_opacity = self._opacity(line_opacity, "area line_opacity")
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
        }
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
    self,
    x: Any,
    lower: Any,
    upper: Any,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
    opacity: float = 0.22,
    line_width: float = 0.0,
    line_opacity: float = 0.0,
    fill: Any = None,
) -> "Figure":
    """Add an uncertainty/confidence band between ``lower`` and ``upper``.

    The band is one filled strip, not one rectangle per observation. It uses
    the same M4 reduction and WebGL area path as a large area series.
    """
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
    self,
    x: Any,
    y: Any,
    *,
    yerr: Any = None,
    xerr: Any = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    cap_size: Optional[float] = None,
    opacity: float = 1.0,
) -> "Figure":
    """Add vertical and/or horizontal error bars as instanced segments.

    ``yerr`` and ``xerr`` accept symmetric lengths or a ``(lower, upper)``
    pair. ``cap_size`` is expressed in the perpendicular data-axis units,
    which makes the geometry stable in both notebook and static exports.
    The default (``None``) auto-sizes caps to 0.25x the median adjacent
    spacing of the distinct positions along that axis (0.4 when fewer than
    two are distinct); ``cap_size=0`` omits the caps entirely.
    """
    if yerr is None and xerr is None:
        raise ValueError("errorbar requires yerr, xerr, or both")
    name = self._optional_text(name, "errorbar name")
    color = self._optional_css_color(color, "errorbar color")
    if color is None:
        color = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
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
            )
        return self
    except Exception:
        self._rollback(checkpoint)
        raise


def step(
    self,
    x: Any,
    y: Any,
    *,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Any = None,
) -> "Figure":
    """Add a step line without expanding the canonical input columns."""
    if where not in {"pre", "post", "mid"}:
        raise ValueError("step where must be 'pre', 'post', or 'mid'")
    self.line(x, y, name=name, color=color, width=width, opacity=opacity, dash=dash)
    self.traces[-1].style["step"] = where
    return self


def stairs(
    self,
    values: Any,
    edges: Any = None,
    *,
    where: str = "post",
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Any = None,
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
    )


def ecdf(
    self,
    values: Any,
    *,
    bins: Optional[int] = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
    dash: Any = None,
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
            sx, sy, where="post", name=name, color=color, width=width, opacity=opacity, dash=dash
        )
    unique, counts = np.unique(vals, return_counts=True)
    cdf = np.cumsum(counts, dtype=np.float64) / len(vals)
    sx = np.concatenate(([unique[0]], unique))
    sy = np.concatenate(([0.0], cdf))
    return self.step(
        sx, sy, where="post", name=name, color=color, width=width, opacity=opacity, dash=dash
    )


def stem(
    self,
    x: Any,
    y: Any,
    *,
    base: Any = 0.0,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.2,
    opacity: float = 1.0,
    marker: bool = True,
    marker_size: float = 5.0,
    symbol: str = "circle",
) -> "Figure":
    """Add vertical stem segments and optional point markers."""
    name = self._optional_text(name, "stem name")
    color = self._optional_css_color(color, "stem color")
    if color is None:
        color = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
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
    self,
    x: Any,
    y: Any,
    *,
    name: Optional[str] = None,
    color: Any = None,
    size: Any = 4.0,
    opacity: float = 0.8,
    colormap: str = channels.DEFAULT_COLORMAP,
    color_domain: Optional[tuple[float, float]] = None,
    size_range: tuple[float, float] = (2.0, 18.0),
    density: Optional[bool] = None,
    symbol: str = "circle",
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
) -> "Figure":
    """Add a scatter trace.

    `color` may be a CSS color (constant), a numeric array (continuous →
    colormap), or a categorical array (factorized → palette). `size` may be
    a scalar or a numeric array (mapped to `size_range` px). `symbol` picks
    the marker shape (circle/square/diamond/triangle/cross); `stroke` /
    `stroke_width` draw a point border. Large scatters auto-switch to a
    Tier-2 density surface (§5); pass `density=True/False` to force it.
    """
    name = self._optional_text(name, "scatter name")
    opacity = self._opacity(opacity, "scatter opacity")
    density = self._optional_bool(density, "scatter density")
    symbol = _validate.point_symbol(symbol, "scatter symbol")
    stroke = self._optional_css_color(stroke, "scatter stroke")
    stroke_width = self._nonnegative_scalar(stroke_width, "scatter stroke_width")
    if stroke is not None and stroke_width == 0.0:
        stroke_width = 1.0
    checkpoint = self._checkpoint()
    try:
        xc, yc = self._ingest_xy(x, y, "scatter")
        n = len(xc)
        default_color = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
        color_ch = channels.resolve_color(
            color, n, colormap=colormap, default_constant=default_color, domain=color_domain
        )
        size_ch = channels.resolve_size(size, n, range_px=size_range)

        point_style: dict[str, Any] = {"opacity": opacity}
        if symbol != "circle":
            point_style["symbol"] = symbol
        if stroke is not None:
            point_style["stroke"] = stroke
        if stroke_width:
            point_style["stroke_width"] = stroke_width

        trace = Trace(
            id=len(self.traces),
            kind="scatter",
            x=xc,
            y=yc,
            name=name,
            style=point_style,
            color_ch=color_ch,
            size_ch=size_ch,
            force_density=density,
        )

        per_point = color_ch.mode != "constant" or size_ch.mode != "constant"
        if density is None and per_point and n > DIRECT_SOFT_CEILING:
            warnings.warn(
                f"scatter has {n:,} points with per-point color/size — above the "
                f"direct ceiling ({DIRECT_SOFT_CEILING:,}). Falling back to a "
                "density surface; per-point channels are dropped (aggregating "
                "arbitrary color/size needs the §5-F5 aggregation algebra, not yet "
                "implemented). Pass density=False to keep direct draw at your risk.",
                RuntimeWarning,
                stacklevel=2,
            )
            trace.force_density = True
        elif density is None and n > DIRECT_SOFT_CEILING:
            warnings.warn(
                f"scatter has {n:,} points above the soft ceiling "
                f"({DIRECT_SOFT_CEILING:,}); using a density surface for the "
                "initial render.",
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
    self,
    values: Any,
    *,
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
) -> "Figure":
    """Add a 1D histogram backed by the shared rectangle primitive.

    `cumulative=True` accumulates bins left-to-right: with the default
    count mode the last bin equals the number of in-range values; combined
    with `density=True` it becomes the empirical CDF (last bin ~1.0).
    """
    name = self._optional_text(name, "histogram name")
    opacity = self._opacity(opacity, "histogram opacity")
    mark_style = self._rect_mark_style("histogram", corner_radius, stroke, stroke_width, fill)
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
    zeros = np.zeros_like(counts, dtype=np.float64)
    self._append_rect_trace(
        "histogram",
        edges[:-1],
        edges[1:],
        zeros,
        counts,
        name=name,
        color=color,
        opacity=opacity,
        role="histogram",
        count=int(len(vals)),
        extra_style={"cumulative": cumulative, "density": density, **mark_style},
    )
    return self


def hist(
    self,
    values: Any,
    *,
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
        fill=fill,
    )


def box(
    self,
    values: Any,
    *,
    x: Any = None,
    group: Any = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.6,
    opacity: float = 0.85,
    orientation: str = "vertical",
    show_outliers: bool = True,
    outlier_size: float = 4.0,
) -> "Figure":
    """Add grouped Tukey box plots from 1-D or column-oriented 2-D values."""
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError("box orientation must be 'vertical' or 'horizontal'")
    name = self._optional_text(name, "box name")
    color = self._optional_css_color(color, "box color")
    if color is None:
        color = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
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
            extra_style={"stroke_width": 1.0, "box_orientation": orientation},
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
    self,
    values: Any,
    *,
    x: Any = None,
    group: Any = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 0.8,
    bins: int = 64,
    opacity: float = 0.55,
    orientation: str = "vertical",
) -> "Figure":
    """Add bounded-resolution violin distributions.

    Density estimation is a smoothed histogram computed once in Python; each
    group ships its fixed ``bins``-sized band set. The client draws the bands
    through the shared instanced rectangle path, so input cardinality does not
    become DOM/GPU object cardinality.
    """
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
        )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self


def hexbin(
    self,
    x: Any,
    y: Any,
    *,
    gridsize: int | tuple[int, int] = 64,
    range: Optional[tuple[tuple[float, float], tuple[float, float]]] = None,
    bins: str = "count",
    C: Any = None,
    reduce_C_function: Any = np.mean,
    mincnt: Optional[int] = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    opacity: float = 0.9,
) -> "Figure":
    """Add a screen-bounded hexagonal density plot.

    Binning is performed by the native 2-D kernel. Only occupied bins are
    shipped as centers plus one scalar count/color channel.
    """
    if isinstance(gridsize, (int, np.integer)) and not isinstance(gridsize, (bool, np.bool_)):
        w = h = int(gridsize)
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
    threshold = 1 if mincnt is None else int(mincnt)
    if threshold < 0:
        raise ValueError("hexbin mincnt must be nonnegative")
    if cv is None:
        grid = kernels.bin_2d(xv, yv, xr[0], xr[1], yr[0], yr[1], w, h)
        grid2d = grid.reshape(h, w)
        rows, cols = np.nonzero(grid2d >= threshold)
    else:
        # count with the same clip membership the reducer uses below, so
        # mincnt filtering and aggregation always agree on bin contents
        x_index = np.clip(((xv - xr[0]) / (xr[1] - xr[0]) * w).astype(int), 0, w - 1)
        y_index = np.clip(((yv - yr[0]) / (yr[1] - yr[0]) * h).astype(int), 0, h - 1)
        grid2d = np.zeros((h, w), dtype=np.float64)
        np.add.at(grid2d, (y_index, x_index), 1.0)
        rows, cols = np.nonzero(grid2d >= max(1, threshold))
    counts = grid2d[rows, cols]
    if len(counts) == 0:
        raise ValueError("hexbin range contains no finite points")
    dx, dy = (xr[1] - xr[0]) / w, (yr[1] - yr[0]) / h
    centers_x = xr[0] + (cols + 0.5 + 0.5 * (rows & 1)) * dx
    centers_y = yr[0] + (rows + 0.5) * dy
    if cv is None:
        metric = np.log1p(counts) if bins == "log" else counts
    else:
        reduced: list[float] = []
        for row, col in zip(rows, cols, strict=True):
            values = cv[(x_index == col) & (y_index == row)]
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
                    "color": DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)],
                    "opacity": opacity,
                    "symbol": "hexagon",
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


def contour(
    self,
    z: Any,
    *,
    x: Any = None,
    y: Any = None,
    levels: int | Any = 10,
    filled: bool = False,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    color: Optional[str] = None,
    width: float = 1.1,
    opacity: float = 0.9,
    dash_negative: bool = False,
) -> "Figure":
    """Add regular-grid contour isolines, optionally over a filled heatmap.

    `dash_negative` renders negative-level isolines dashed for a single-color
    contour (Matplotlib's monochrome convention); it is ignored when a colormap
    drives per-level color.
    """
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
            # consecutive levels, not a smooth ramp. Snap each cell to its
            # band's midpoint so the heatmap renders flat bands; cells outside
            # [levels[0], levels[-1]] stay unpainted (extend='neither').
            edges = np.asarray(level_values, dtype=np.float64)
            if len(edges) >= 2 and edges[0] < edges[-1]:
                band = np.searchsorted(edges, arr, side="right") - 1
                mids = (edges[:-1] + edges[1:]) * 0.5
                banded = np.full(arr.shape, np.nan, dtype=np.float64)
                inside = np.isfinite(arr) & (band >= 0) & (band < len(edges) - 1)
                banded[inside] = mids[np.clip(band, 0, len(edges) - 2)][inside]
                self.heatmap(
                    banded,
                    x=x,
                    y=y,
                    name=None,
                    colormap=colormap,
                    domain=(float(edges[0]), float(edges[-1])),
                    opacity=min(opacity, 0.9),
                )
            else:
                self.heatmap(arr, x=x, y=y, name=None, colormap=colormap, opacity=min(opacity, 0.7))
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
        # Matplotlib dashes negative isolines for a single-color contour. Split
        # the segment set by level sign so the negative group ships dashed; a
        # colormapped contour keeps every level solid.
        lv = np.asarray(level_values)
        if dash_negative and color is not None and np.any(lv < 0) and np.any(lv >= 0):
            groups = ((lv >= 0, None), (lv < 0, "6,4"))
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
            )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self


def bar(
    self,
    x: Any,
    y: Any,
    *,
    name: Optional[str] = None,
    color: Any = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Any = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: float = 0.85,
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
) -> "Figure":
    """Add vertical bars. 2D y values render grouped, stacked, or
    normalized (per-category fractions summing to 1) series.

    `corner_radius`/`stroke`/`stroke_width` are the CSS border analogues
    rendered into the mark; `fill` accepts a CSS `linear-gradient(...)`
    (docs/styling.md#styling-the-marks)."""
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
        fill=fill,
    )


def column(
    self,
    x: Any,
    y: Any,
    *,
    name: Optional[str] = None,
    color: Any = None,
    colors: Optional[list[str]] = None,
    width: float = 0.8,
    base: Any = 0.0,
    mode: str = "grouped",
    orientation: str = "vertical",
    series: Optional[list[str]] = None,
    opacity: float = 0.85,
    corner_radius: Any = 0.0,
    stroke: Optional[str] = None,
    stroke_width: float = 0.0,
    fill: Any = None,
) -> "Figure":
    """Alias for vertical column charts; shares the bar/rect renderer."""
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
    )


def heatmap(
    self,
    z: Any,
    *,
    x: Any = None,
    y: Any = None,
    name: Optional[str] = None,
    colormap: str = channels.DEFAULT_COLORMAP,
    domain: Optional[tuple[float, float]] = None,
    opacity: float = 0.95,
) -> "Figure":
    """Add a rectangular heatmap from a 2D value matrix.

    `z` is shaped `(rows, columns)`. Optional `x` and `y` arrays name the
    column/row centers; string/object arrays become categorical axes.
    """
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
                    tuple(self.store.ingest(rgba[..., index].reshape(-1)) for index in range(4))
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
                },
            )
        )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self
