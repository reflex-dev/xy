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

from . import _validate, channels, kernels
from ._trace import Trace
from .config import DEFAULT_PALETTE, DIRECT_SOFT_CEILING

if TYPE_CHECKING:
    from ._figure import Figure


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
    pos = self._axis_positions(x, category_axis, commit=False)
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
        self._commit_axis_positions(x, category_axis)
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
            color, n, colormap=colormap, default_constant=default_color
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
    if arr.ndim != 2:
        raise ValueError(f"heatmap z must be 2-D, got shape {arr.shape}")
    zv = self._real_float_array(arr, "heatmap z")
    rows, cols = zv.shape
    xpos = self._heatmap_axis_positions(x, cols, "x")
    ypos = self._heatmap_axis_positions(y, rows, "y")
    x_edges = self._cell_edges(xpos, "heatmap x")
    y_edges = self._cell_edges(ypos, "heatmap y")
    z_flat = zv.reshape(-1)
    if colormap not in channels.COLORMAPS:
        raise ValueError(f"unknown colormap {colormap!r}; known: {channels.COLORMAPS}")
    if domain is None:
        lo, hi = self._auto_domain(kernels.min_max(z_flat))
    else:
        lo, hi = self._finite_increasing_pair(domain, "heatmap domain")
    checkpoint = self._checkpoint()
    try:
        self._commit_axis_positions(x, "x")
        self._commit_axis_positions(y, "y")
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="heatmap",
                x=self.store.ingest(np.array([x_edges[0], x_edges[-1]], dtype=np.float64)),
                y=self.store.ingest(np.array([y_edges[0], y_edges[-1]], dtype=np.float64)),
                grid=self.store.ingest(z_flat),
                grid_shape=(rows, cols),
                count=int(z_flat.size),
                name=name,
                style={
                    "opacity": opacity,
                    "role": "heatmap",
                    "colormap": colormap,
                    "domain": [lo, hi],
                    "x_range": [float(x_edges[0]), float(x_edges[-1])],
                    "y_range": [float(y_edges[0]), float(y_edges[-1])],
                },
            )
        )
    except Exception:
        self._rollback(checkpoint)
        raise
    return self
