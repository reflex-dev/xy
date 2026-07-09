"""The Figure: a data-less spec + column handles (§9).

The spec is tiny JSON — trace kinds, styles, axis config, and *references* into
the column store. Data never rides in the spec: encoded f32 columns travel as
one binary blob beside it (§29: no JSON numbers, no re-encoding, parse-shaped
work is forbidden on the client).
"""

from __future__ import annotations

import warnings
from os import PathLike
from typing import Any, Optional, TypeAlias

import numpy as np

from . import _annotations, _validate, channels, columns, export, interaction, kernels
from ._annotations import AnnotationsMixin
from ._payload import PayloadMixin
from ._trace import Trace
from .channels import ColorChannel, SizeChannel
from .columns import Column, ColumnStore, ColumnStoreCheckpoint

# Tier/tuning constants live in config.py (shared with interaction/export/
# _payload); several are re-exported here — this module is their historic
# import path and tests import them from `fastcharts.figure` (F401 kept for
# the re-exports; DIRECT_SOFT_CEILING/DEFAULT_PALETTE are also used below).
from .config import (  # noqa: E402, F401
    DECIMATION_THRESHOLD,
    DEFAULT_PALETTE,
    DENSITY_GRID,
    DENSITY_SAMPLE_SEED,
    DENSITY_SAMPLE_TARGET,
    DIRECT_SOFT_CEILING,
    PROTOCOL_VERSION,
    SCATTER_DENSITY_THRESHOLD,
)
from .dom import validate_dom_slots

_FigureCheckpoint: TypeAlias = tuple[ColumnStoreCheckpoint, int, dict[str, list[str]], int]


class Selection:
    """The payload handed to an `on_select` callback (§34). Holds the selected
    row indices per trace and lends convenient access to the underlying data —
    callbacks receive real arrays, never JSON."""

    def __init__(self, figure: "Figure", per_trace: dict[int, np.ndarray]) -> None:
        self._figure = figure
        self.per_trace = per_trace  # {trace_id: np.ndarray[uint32]}

    @property
    def index(self) -> np.ndarray:
        """Concatenated selected indices across all traces (single-trace charts
        are the common case, where this is just that trace's indices)."""
        arrs = list(self.per_trace.values())
        return np.concatenate(arrs) if arrs else np.empty(0, dtype="uint32")

    def __len__(self) -> int:
        return int(sum(len(v) for v in self.per_trace.values()))

    def xy(self, trace_id: int = 0) -> tuple[np.ndarray, np.ndarray]:
        """(x, y) f64 arrays for the selected points of a trace (from canonical)."""
        t = interaction._trace(self._figure, trace_id)
        idx = self.per_trace.get(t.id)
        if idx is None:
            return np.empty(0), np.empty(0)
        return t.x.values[idx], t.y.values[idx]


class Figure(AnnotationsMixin, PayloadMixin):
    """Build with `line()` / `scatter()`, display with `show()` (notebook) or
    `to_html()` (standalone file, no kernel round-trips)."""

    def __init__(
        self,
        *,
        width: "int | str" = 900,
        height: "int | str" = 420,
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        padding: Any = None,
    ) -> None:
        # width/height: pixels, or "100%" to fill the parent container — the
        # client measures the container and re-renders on resize
        # (ResizeObserver), re-requesting decimation/density at the new pixel
        # size (§28). height="100%" needs a parent with a defined height (the
        # usual CSS contract); otherwise the chart falls back to its 120px
        # min-height.
        self.width = self._pixel_dimension(width, "width")
        self.height = self._pixel_dimension(height, "height")
        # padding: override the auto plot margins (top, right, bottom, left) in
        # px — a scalar sets all four. None keeps the label-aware defaults. Zero
        # padding + hidden axes gives an edge-to-edge sparkline for dashboards.
        self.padding = self._padding(padding, "padding")
        self.title = self._optional_text(title, "title")
        self.x_label = self._optional_text(x_label, "x_label")
        self.y_label = self._optional_text(y_label, "y_label")
        self.axis_options: dict[str, dict[str, Any]] = {
            "x": {"label": self.x_label, "side": "bottom"},
            "y": {"label": self.y_label, "side": "left"},
        }
        self.store = ColumnStore()
        self.traces: list[Trace] = []
        self.show_legend = True
        self.show_modebar = True
        self.show_tooltip = True
        self.class_name: Optional[str] = None
        self.class_names: dict[str, str] = {}
        self.style: dict[str, str | int | float] = {}
        self.chrome_styles: dict[str, dict[str, str | int | float]] = {}
        self.tooltip: Optional[dict[str, Any]] = None
        self.interaction: dict[str, Any] = {}
        self.mark_style: dict[str, dict[str, str | int | float]] = {}
        self.annotations: list[dict[str, Any]] = []
        self._axis_categories: dict[str, list[str]] = {}
        self._widget: Any = None

    # -- axis config --------------------------------------------------------

    def set_axis(
        self,
        axis_id: str,
        *,
        label: Optional[str] = None,
        label_position: Optional[Any] = None,
        label_offset: Optional[float] = None,
        label_angle: Optional[float] = None,
        type_: Optional[str] = None,
        domain: Optional[tuple[float, float]] = None,
        reverse: bool = False,
        format: Optional[str] = None,
        tick_count: Optional[int] = None,
        tick_label_angle: Optional[float] = None,
        tick_label_strategy: Optional[str] = None,
        tick_label_min_gap: Optional[float] = None,
        side: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        axis_id = self._axis_id(axis_id, "axis id")
        axis_dim = self._axis_dim(axis_id)
        if type_ is not None and type_ not in {"linear", "time", "log"}:
            raise ValueError("axis type_ must be one of None, 'linear', 'time', or 'log'")
        if domain is not None:
            domain = self._finite_increasing_pair(domain, f"{axis_id} axis domain")
            if type_ == "log" and domain[0] <= 0:
                raise ValueError(f"{axis_id} log axis domain must be positive")
        if side is None:
            side = "bottom" if axis_dim == "x" else ("right" if axis_id != "y" else "left")
        elif axis_dim == "x" and side not in {"top", "bottom"}:
            raise ValueError("x axis side must be 'top' or 'bottom'")
        elif axis_dim == "y" and side not in {"left", "right"}:
            raise ValueError("y axis side must be 'left' or 'right'")
        self.axis_options[axis_id] = {
            "label": self._optional_text(label, f"{axis_id} axis label"),
            "label_position": self._axis_label_position(
                label_position, f"{axis_id} axis label_position"
            ),
            "label_offset": self._optional_finite_scalar(
                label_offset, f"{axis_id} axis label_offset"
            ),
            "label_angle": self._optional_finite_scalar(label_angle, f"{axis_id} axis label_angle"),
            "type": type_,
            "domain": domain,
            "reverse": self._bool_param(reverse, f"{axis_id} axis reverse"),
            "format": self._optional_text(format, f"{axis_id} axis format"),
            "tick_count": self._optional_positive_int(tick_count, f"{axis_id} axis tick_count"),
            "tick_label_angle": self._optional_finite_scalar(
                tick_label_angle, f"{axis_id} axis tick_label_angle"
            ),
            "tick_label_strategy": self._axis_tick_label_strategy(
                tick_label_strategy, f"{axis_id} axis tick_label_strategy"
            ),
            "tick_label_min_gap": None
            if tick_label_min_gap is None
            else self._nonnegative_scalar(tick_label_min_gap, f"{axis_id} axis tick_label_min_gap"),
            "side": side,
            "style": self._optional_state_style(style, f"{axis_id} axis style"),
        }
        if axis_id == "x":
            self.x_label = self.axis_options[axis_id]["label"]
        elif axis_id == "y":
            self.y_label = self.axis_options[axis_id]["label"]
        return self

    def set_interaction(
        self,
        *,
        hover: Optional[bool] = None,
        click: Optional[bool] = None,
        select: Optional[bool] = None,
        brush: Optional[bool] = None,
        crosshair: Optional[bool] = None,
        view_change: Optional[bool] = None,
        link_group: Optional[str] = None,
        link_axes: tuple[str, ...] = ("x", "y"),
    ) -> "Figure":
        updates: dict[str, Any] = {}
        for name, value in (
            ("hover", hover),
            ("click", click),
            ("select", select),
            ("brush", brush),
            ("crosshair", crosshair),
            ("view_change", view_change),
        ):
            normalized = self._optional_bool(value, f"interaction {name}")
            if normalized is not None:
                updates[name] = normalized
        if link_group is not None:
            group = self._optional_text(link_group, "interaction link_group")
            if not group:
                raise ValueError("interaction link_group must be a non-empty string or None")
            updates["link_group"] = group
            updates["link_axes"] = self._link_axes(link_axes)
        self.interaction.update(updates)
        return self

    def set_mark_style(
        self,
        *,
        hover: Optional[dict[str, Any]] = None,
        selected: Optional[dict[str, Any]] = None,
        unselected: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Configure mark hover/selection state styling."""
        for state, value in (
            ("hover", hover),
            ("selected", selected),
            ("unselected", unselected),
        ):
            style = self._optional_state_style(value, f"mark_style {state}")
            if style:
                self.mark_style[state] = {**self.mark_style.get(state, {}), **style}
        return self

    # -- trace builders -----------------------------------------------------

    def _ingest_xy(self, x: Any, y: Any, kind: str) -> tuple[Column, Column]:
        """Ingest an (x, y) pair into the column store with the equal-length
        contract every xy chart shares (line/scatter/area/bar/…)."""
        checkpoint = self.store.checkpoint()
        try:
            xc = self.store.ingest(x)
            yc = self.store.ingest(y)
            if len(xc) != len(yc):
                raise ValueError(
                    f"{kind} x and y must have equal length, got {len(xc)} and {len(yc)}"
                )
            return xc, yc
        except Exception:
            self.store.rollback(checkpoint)
            raise

    def _checkpoint(self) -> _FigureCheckpoint:
        return (
            self.store.checkpoint(),
            len(self.traces),
            {axis: list(labels) for axis, labels in self._axis_categories.items()},
            len(self.annotations),
        )

    def _rollback(self, checkpoint: _FigureCheckpoint) -> None:
        store_checkpoint, trace_len, axis_categories, annotation_len = checkpoint
        self.store.rollback(store_checkpoint)
        del self.traces[trace_len:]
        del self.annotations[annotation_len:]
        self._axis_categories = axis_categories

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
            if not np.all(np.diff(xc.values) >= 0):
                # LOD contract (§28): line x must be sorted; the engine sorts once
                # at ingest, and says so. The predicate is NaN-safe on purpose:
                # `any(diff < 0)` is False for NaN diffs, which would let a
                # NaN-carrying x skip the sort and violate M4's sorted precondition.
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
            if not np.all(np.diff(xc.values) >= 0):
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
            counts, edges = np.histogram(finite, bins=hist_bins, range=hist_range, density=density)
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
        return self._bar_like(
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
        return self._bar_like(
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

    def _rect_mark_style(
        self,
        kind: str,
        corner_radius: Any,
        stroke: Optional[str],
        stroke_width: float,
        fill: Any,
    ) -> dict[str, Any]:
        """Validate the rect-family mark styling (rounded corners, border,
        gradient fill) into the sparse style keys the client renders.

        `corner_radius` is a px float for all four corners, or a `(tip, base)`
        pair in mark space — `(6, 0)` rounds only the value end of each bar
        (the top of a vertical bar), which stays correct for horizontal and
        negative bars. Setting `stroke` alone implies a 1px border, matching
        CSS expectations; the client defaults a widthed border with no color
        to the mark color."""
        style: dict[str, Any] = {}
        if isinstance(corner_radius, (tuple, list)):
            if len(corner_radius) != 2:
                raise ValueError(f"{kind} corner_radius pair must be (tip, base)")
            tip = self._nonnegative_scalar(corner_radius[0], f"{kind} corner_radius tip")
            base = self._nonnegative_scalar(corner_radius[1], f"{kind} corner_radius base")
            if tip or base:
                style["corner_radius"] = [tip, base]
        else:
            radius = self._nonnegative_scalar(corner_radius, f"{kind} corner_radius")
            if radius:
                style["corner_radius"] = radius
        stroke = self._optional_css_color(stroke, f"{kind} stroke")
        stroke_width = self._nonnegative_scalar(stroke_width, f"{kind} stroke_width")
        if stroke is not None and stroke_width == 0.0:
            stroke_width = 1.0
        fill_spec = _validate.mark_fill(fill, f"{kind} fill")
        if stroke is not None:
            style["stroke"] = stroke
        if stroke_width:
            style["stroke_width"] = stroke_width
        if fill_spec is not None:
            style["fill"] = fill_spec
        return style

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

    def _append_bar_rect(
        self,
        kind: str,
        orientation: str,
        pos0: np.ndarray,
        pos1: np.ndarray,
        value0: np.ndarray,
        value1: np.ndarray,
        *,
        name: Optional[str],
        color: Optional[str],
        opacity: float,
        role: str,
        extra_style: Optional[dict[str, Any]] = None,
    ) -> None:
        if orientation == "vertical":
            self._append_rect_trace(
                kind,
                pos0,
                pos1,
                value0,
                value1,
                name=name,
                color=color,
                opacity=opacity,
                role=role,
                orientation=orientation,
                extra_style=extra_style,
            )
        else:
            self._append_rect_trace(
                kind,
                value0,
                value1,
                pos0,
                pos1,
                name=name,
                color=color,
                opacity=opacity,
                role=role,
                orientation=orientation,
                extra_style=extra_style,
            )

    @staticmethod
    def _as_1d_float(values: Any, label: str) -> np.ndarray:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{label} must be 1-D, got shape {arr.shape}")
        return Figure._real_float_array(arr, label)

    # Shared argument validators (bodies live in `_validate`); these thin
    # staticmethod aliases keep `self._foo(...)` call sites — and the two
    # helpers `components` reaches through `Figure` — unchanged.
    _finite_scalar = staticmethod(_validate.finite_scalar)
    _finite_increasing_pair = staticmethod(_validate.finite_increasing_pair)
    _positive_scalar = staticmethod(_validate.positive_scalar)
    _optional_finite_scalar = staticmethod(_validate.optional_finite_scalar)
    _optional_positive_int = staticmethod(_validate.optional_positive_int)
    _axis_tick_label_strategy = staticmethod(_validate.axis_tick_label_strategy)
    _nonnegative_scalar = staticmethod(_validate.nonnegative_scalar)
    _opacity = staticmethod(_validate.opacity)
    _padding = staticmethod(_validate.plot_padding)
    _optional_bool = staticmethod(_validate.optional_bool)
    _bool_param = staticmethod(_validate.bool_param)
    _axis_id = staticmethod(_validate.axis_id)
    _optional_text = staticmethod(_validate.optional_text)
    _optional_css_color = staticmethod(_validate.optional_css_color)
    _string_mapping = staticmethod(_validate.string_mapping)
    _style_mapping = staticmethod(_validate.style_mapping)

    @staticmethod
    def _axis_dim(axis_id: str) -> str:
        return "x" if axis_id.startswith("x") else "y"

    @staticmethod
    def _link_axes(value: Any) -> list[str]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("interaction link_axes must be a tuple/list containing 'x' and/or 'y'")
        axes = list(value)
        if not axes or any(axis not in {"x", "y"} for axis in axes):
            raise ValueError("interaction link_axes must contain only 'x' and/or 'y'")
        out: list[str] = []
        for axis in axes:
            if axis not in out:
                out.append(axis)
        return out

    _axis_label_position = staticmethod(_validate.axis_label_position)

    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        if isinstance(value, str):
            return value
        raise ValueError(f"{label} must be a string")

    @staticmethod
    def _pixel_dimension(value: Any, label: str) -> Any:
        if isinstance(value, str):
            if value == "100%":
                return value
            raise ValueError(f'{label} must be a positive integer pixel count or "100%"')
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise ValueError(f'{label} must be a positive integer pixel count or "100%"')
        out = int(value)
        if out <= 0:
            raise ValueError(f'{label} must be a positive integer pixel count or "100%"')
        return out

    @staticmethod
    def _auto_domain(bounds: Optional[tuple[float, float]]) -> tuple[float, float]:
        """Finite increasing domain for auto-scaled scalar marks.

        Kernels require `hi > lo`; user data does not owe us variance. Expand a
        degenerate domain the same way autorange does so constant histograms and
        heatmaps render instead of tripping an internal precondition.
        """
        if bounds is None:
            return (0.0, 1.0)
        lo, hi = bounds
        if lo == hi:
            pad = abs(lo) * 0.05 or 0.5
            return (lo - pad, hi + pad)
        return (lo, hi)

    @staticmethod
    def _as_float_array(values: Any, label: str) -> np.ndarray:
        arrow = columns._arrow_to_numpy(values)
        if arrow is not None:  # pyarrow channel input: nulls become NaN
            values = arrow[0]
        elif hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim not in (1, 2):
            raise ValueError(f"{label} must be 1-D or 2-D, got shape {arr.shape}")
        return Figure._real_float_array(arr, label)

    @staticmethod
    def _real_float_array(arr: np.ndarray, label: str) -> np.ndarray:
        if np.issubdtype(arr.dtype, np.bool_):
            raise ValueError(f"{label} must be real numeric, not boolean")
        if arr.dtype == object and any(isinstance(value, (bool, np.bool_)) for value in arr.flat):
            raise ValueError(f"{label} must be real numeric, not boolean")
        if np.issubdtype(arr.dtype, np.complexfloating):
            raise ValueError(f"{label} must be real numeric")
        try:
            return arr.astype(np.float64, copy=False)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{label} must be real numeric") from e

    @staticmethod
    def _bar_value_matrix(values: Any, n_x: int, kind: str) -> np.ndarray:
        arr = Figure._as_float_array(values, f"{kind} y")
        if arr.ndim == 1:
            if len(arr) != n_x:
                raise ValueError(f"{kind} x and y must have equal length, got {n_x} and {len(arr)}")
            return arr.reshape(1, n_x)
        if arr.shape[1] == n_x:
            return arr
        if arr.shape[0] == n_x:
            return arr.T
        raise ValueError(
            f"{kind} 2-D y must have one dimension matching x length {n_x}, got {arr.shape}"
        )

    @staticmethod
    def _series_names(name: Optional[str], series: Optional[list[str]], n_series: int) -> list[str]:
        if series is not None:
            if len(series) != n_series:
                raise ValueError(f"series must have length {n_series}, got {len(series)}")
            names: list[str] = []
            for i, item in enumerate(series):
                if not isinstance(item, str):
                    raise ValueError(f"series[{i}] must be a string")
                names.append(item)
            return names
        if n_series == 1:
            return [name or ""]
        prefix = f"{name} " if name else "series "
        return [f"{prefix}{i + 1}" for i in range(n_series)]

    @staticmethod
    def _series_colors(
        color: Any, colors: Optional[list[str]], n_series: int
    ) -> list[Optional[str]]:
        if colors is not None:
            if len(colors) != n_series:
                raise ValueError(f"colors must have length {n_series}, got {len(colors)}")
            return [_validate.css_color(c, f"colors[{i}]") for i, c in enumerate(colors)]
        if isinstance(color, (list, tuple, np.ndarray)) and not isinstance(color, str):
            color_list: list[Optional[str]] = [
                _validate.css_color(str(c), f"color[{i}]") for i, c in enumerate(color)
            ]
            if len(color_list) != n_series:
                raise ValueError(
                    f"color sequence must have length {n_series}, got {len(color_list)}"
                )
            return color_list
        if color is not None:
            color = _validate.css_color(color, "color")
        return [color for _ in range(n_series)]

    @staticmethod
    def _is_category_like(values: Any) -> bool:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        return arr.dtype.kind in ("U", "S", "O", "b")

    @staticmethod
    def _category_axis_labels(values: Any, axis: str) -> list[str]:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{axis} categories must be 1-D, got shape {arr.shape}")
        return [channels.category_label(raw) for raw in arr.astype(object)]

    def _axis_positions(self, values: Any, axis: str, *, commit: bool = True) -> np.ndarray:
        if not self._is_category_like(values):
            return self._as_1d_float(values, f"{axis} values")
        raw_labels = self._category_axis_labels(values, axis)
        labels = (
            self._axis_categories.setdefault(axis, [])
            if commit
            else list(self._axis_categories.get(axis, []))
        )
        lookup = {label: i for i, label in enumerate(labels)}
        out = np.empty(len(raw_labels), dtype=np.float64)
        for i, label in enumerate(raw_labels):
            pos = lookup.get(label)
            if pos is None:
                pos = len(labels)
                labels.append(label)
                lookup[label] = pos
            out[i] = float(pos)
        return out

    def _commit_axis_positions(self, values: Any, axis: str) -> None:
        if values is not None and self._is_category_like(values):
            self._axis_positions(values, axis, commit=True)

    @staticmethod
    def _broadcast_base(base: Any, n: int, kind: str) -> np.ndarray:
        if np.isscalar(base):
            return np.full(n, Figure._finite_scalar(base, f"{kind} base"), dtype=np.float64)
        arr = Figure._as_1d_float(base, f"{kind} base")
        if len(arr) != n:
            raise ValueError(f"{kind} base must have length {n}, got {len(arr)}")
        return arr

    def _heatmap_axis_positions(self, values: Any, n: int, axis: str) -> np.ndarray:
        if values is None:
            return np.arange(n, dtype=np.float64)
        is_category = self._is_category_like(values)
        pos = self._axis_positions(values, axis, commit=False)
        if len(pos) != n:
            raise ValueError(f"heatmap {axis} must have length {n}, got {len(pos)}")
        if is_category:
            labels = self._category_axis_labels(values, axis)
            if len(set(labels)) != len(labels):
                raise ValueError(f"heatmap {axis} categories must be unique after normalization")
        return pos

    @staticmethod
    def _cell_edges(centers: np.ndarray, label: str) -> np.ndarray:
        centers = np.asarray(centers, dtype=np.float64)
        if centers.ndim != 1:
            raise ValueError(f"{label} centers must be 1-D")
        if len(centers) == 0:
            raise ValueError(f"{label} needs at least one center")
        if len(centers) == 1:
            return np.array([centers[0] - 0.5, centers[0] + 0.5], dtype=np.float64)
        diffs = np.diff(centers)
        if not np.all(np.isfinite(diffs)) or np.any(diffs <= 0):
            raise ValueError(f"{label} centers must be finite and strictly increasing")
        mids = (centers[:-1] + centers[1:]) / 2.0
        first = centers[0] - diffs[0] / 2.0
        last = centers[-1] + diffs[-1] / 2.0
        return np.concatenate(([first], mids, [last])).astype(np.float64, copy=False)

    def _append_rect_trace(
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
        role: str,
        orientation: Optional[str] = None,
        color_ch: Optional[ColorChannel] = None,
        size_ch: Optional[SizeChannel] = None,
        count: Optional[int] = None,
        extra_style: Optional[dict[str, Any]] = None,
    ) -> None:
        name = self._optional_text(name, f"{kind} name")
        opacity = self._opacity(opacity, f"{kind} opacity")
        lengths = {
            self._rect_edge_len(x0, f"{kind} x0"),
            self._rect_edge_len(x1, f"{kind} x1"),
            self._rect_edge_len(y0, f"{kind} y0"),
            self._rect_edge_len(y1, f"{kind} y1"),
        }
        if len(lengths) != 1:
            raise ValueError(f"{kind} rectangle columns must have equal length")
        checkpoint = self._checkpoint()
        try:
            x0c = self.store.ingest(x0)
            x1c = self.store.ingest(x1)
            y0c = self.store.ingest(y0)
            y1c = self.store.ingest(y1)
            xc = self.store.ingest(x0c.values + (x1c.values - x0c.values) / 2.0)
            yc = self.store.ingest(y1c.values)
            style: dict[str, Any] = {"color": color, "opacity": opacity, "role": role}
            if orientation is not None:
                style["orientation"] = orientation
            if extra_style is not None:
                style.update(extra_style)
            self.traces.append(
                Trace(
                    id=len(self.traces),
                    kind=kind,
                    x=xc,
                    y=yc,
                    x0=x0c,
                    x1=x1c,
                    y0=y0c,
                    y1=y1c,
                    name=name,
                    style=style,
                    color_ch=color_ch,
                    size_ch=size_ch,
                    count=count,
                )
            )
        except Exception:
            self._rollback(checkpoint)
            raise

    @staticmethod
    def _rect_edge_len(values: Any, label: str) -> int:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{label} must be 1-D, got shape {arr.shape}")
        return len(arr)

    # -- ranges ---------------------------------------------------------------

    def x_range(self) -> tuple[float, float]:
        return self._range("x")

    def y_range(self) -> tuple[float, float]:
        return self._range("y")

    def _range(self, axis_id: str) -> tuple[float, float]:
        opts = self.axis_options.get(axis_id, {})
        fixed = opts.get("domain")
        if fixed is not None:
            lo, hi = fixed
            return (hi, lo) if opts.get("reverse") else (lo, hi)

        # Autorange is O(chunks) via zone maps (§22), not an O(n) rescan.
        lo = np.inf
        hi = -np.inf
        for t in self.traces:
            for col in self._range_columns(t, axis_id):
                lo = min(lo, col.min)
                hi = max(hi, col.max)
        if not np.isfinite(lo) or not np.isfinite(hi):
            lo, hi = 0.0, 1.0
        scale = self._axis_scale(axis_id)
        if scale == "log":
            positives: list[float] = []
            for t in self.traces:
                for col in self._range_columns(t, axis_id):
                    finite = col.values[np.isfinite(col.values) & (col.values > 0)]
                    if finite.size:
                        positives.extend([float(np.min(finite)), float(np.max(finite))])
            if not positives:
                raise ValueError(f"{axis_id} log axis requires at least one positive value")
            lo, hi = min(positives), max(positives)
        if lo == hi:
            pad = abs(lo) * 0.05 or 0.5
            lo, hi = lo - pad, hi + pad
            if scale == "log" and lo <= 0:
                lo = hi / 10.0
            return (hi, lo) if opts.get("reverse") else (lo, hi)
        pad = (hi - lo) * 0.03
        anchor = self._zero_baseline_anchor(axis_id)
        out_lo = lo - pad
        out_hi = hi + pad
        if anchor == "lo" and lo == 0.0 and hi > 0.0:
            out_lo = 0.0
        elif anchor == "hi" and hi == 0.0 and lo < 0.0:
            out_hi = 0.0
        if scale == "log":
            out_lo = max(out_lo, lo / 10.0, np.nextafter(0.0, 1.0))
        return (out_hi, out_lo) if opts.get("reverse") else (out_lo, out_hi)

    def _zero_baseline_anchor(self, axis_id: str) -> Optional[str]:
        """Pin zero to the plot edge for positive/negative rectangle charts.

        Histograms and bars encode their baseline as a rectangle edge. Padding
        away from that edge makes the bars visually float above the axis, so the
        value axis keeps zero flush when every mark extends in one direction.
        """
        axis = self._axis_dim(axis_id)
        for t in self.traces:
            if axis == "x" and t.x_axis != axis_id:
                continue
            if axis == "y" and t.y_axis != axis_id:
                continue
            if t.x0 is None or t.x1 is None or t.y0 is None or t.y1 is None:
                continue
            base = t.x0.values if axis == "x" else t.y0.values
            value = t.x1.values if axis == "x" else t.y1.values
            finite = np.isfinite(base) & np.isfinite(value)
            if not np.any(finite):
                continue
            base = base[finite]
            value = value[finite]
            if not np.all(base == 0.0):
                continue
            if np.all(value >= 0.0):
                return "lo"
            if np.all(value <= 0.0):
                return "hi"
        return None

    def _axis_scale(self, axis_id: str) -> str:
        return "log" if self.axis_options.get(axis_id, {}).get("type") == "log" else "linear"

    def _axis_kind(self, axis_id: str) -> str:
        axis = self._axis_dim(axis_id)
        forced = self.axis_options.get(axis_id, {}).get("type")
        if forced == "time":
            return "time"
        if axis in self._axis_categories:
            return "category"
        for t in self.traces:
            if axis == "x" and t.x_axis != axis_id:
                continue
            if axis == "y" and t.y_axis != axis_id:
                continue
            col = t.x if axis == "x" else t.y
            if col.kind == "time_ms":
                return "time"
        return "linear"

    def _axis_spec(self, axis_id: str, range_: tuple[float, float]) -> dict[str, Any]:
        axis = self._axis_dim(axis_id)
        opts = self.axis_options.get(axis_id, {})
        if axis_id == "x":
            label = self.x_label
        elif axis_id == "y":
            label = self.y_label
        else:
            label = opts.get("label")
        label = self._optional_text(label, f"{axis}_label")
        label_position = self._axis_label_position(
            opts.get("label_position"), f"{axis_id} axis label_position"
        )
        label_offset = self._optional_finite_scalar(
            opts.get("label_offset"), f"{axis_id} axis label_offset"
        )
        label_angle = self._optional_finite_scalar(
            opts.get("label_angle"), f"{axis_id} axis label_angle"
        )
        tick_count = self._optional_positive_int(
            opts.get("tick_count"), f"{axis_id} axis tick_count"
        )
        tick_label_angle = self._optional_finite_scalar(
            opts.get("tick_label_angle"), f"{axis_id} axis tick_label_angle"
        )
        tick_label_strategy = self._axis_tick_label_strategy(
            opts.get("tick_label_strategy"), f"{axis_id} axis tick_label_strategy"
        )
        tick_label_min_gap = (
            None
            if opts.get("tick_label_min_gap") is None
            else self._nonnegative_scalar(
                opts.get("tick_label_min_gap"), f"{axis_id} axis tick_label_min_gap"
            )
        )
        kind = self._axis_kind(axis_id)
        spec: dict[str, Any] = {
            "id": axis_id,
            "kind": kind,
            "label": label,
            "range": list(range_),
            "side": opts.get("side", "bottom" if axis == "x" else "left"),
        }
        if label_position is not None:
            spec["label_position"] = label_position
        if label_offset is not None:
            spec["label_offset"] = label_offset
        if label_angle is not None:
            spec["label_angle"] = label_angle
        if tick_count is not None:
            spec["tick_count"] = tick_count
        if tick_label_angle is not None:
            spec["tick_label_angle"] = tick_label_angle
        if tick_label_strategy is not None:
            spec["tick_label_strategy"] = tick_label_strategy
        if tick_label_min_gap is not None:
            spec["tick_label_min_gap"] = tick_label_min_gap
        if self._axis_scale(axis_id) == "log":
            spec["scale"] = "log"
        if opts.get("reverse"):
            spec["reverse"] = True
        if opts.get("domain") is not None:
            spec["domain"] = list(opts["domain"])
        if opts.get("format") is not None:
            spec["format"] = opts["format"]
        style = self._optional_state_style(opts.get("style"), f"{axis_id} axis style")
        if style:
            spec["style"] = style
        if kind == "category":
            spec["categories"] = list(self._axis_categories.get(axis, []))
        return spec

    def _range_columns(self, t: Trace, axis_id: str) -> list[Column]:
        axis = self._axis_dim(axis_id)
        if axis == "x" and t.x_axis != axis_id:
            return []
        if axis == "y" and t.y_axis != axis_id:
            return []
        if t.kind == "area" and t.base is not None:
            return [t.x] if axis == "x" else [t.y, t.base]
        if t.x0 is not None and t.x1 is not None and t.y0 is not None and t.y1 is not None:
            return [t.x0, t.x1] if axis == "x" else [t.y0, t.y1]
        return [t.x if axis == "x" else t.y]

    # -- payload --------------------------------------------------------------

    def _interaction_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {}
        for name in ("hover", "click", "select", "brush", "crosshair", "view_change"):
            if name in self.interaction:
                spec[name] = self._bool_param(self.interaction[name], f"interaction {name}")
        link_group = self.interaction.get("link_group")
        if link_group is not None:
            group = self._optional_text(link_group, "interaction link_group")
            if not group:
                raise ValueError("interaction link_group must be a non-empty string or None")
            spec["link_group"] = group
            spec["link_axes"] = self._link_axes(self.interaction.get("link_axes", ("x", "y")))
        return spec

    def _mark_style_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {}
        for state in ("hover", "selected", "unselected"):
            style = self._optional_state_style(self.mark_style.get(state), f"mark_style {state}")
            if style:
                spec[state] = style
        return spec

    def _dom_spec(self) -> dict[str, Any]:
        dom: dict[str, Any] = {}
        class_name = self._optional_text(self.class_name, "class_name")
        if class_name:
            dom["class_name"] = class_name
        class_names = self._string_mapping(self.class_names, "class_names")
        validate_dom_slots(class_names, "class_names")
        if class_names:
            dom["class_names"] = class_names
        validate_dom_slots(self.chrome_styles, "chrome_styles")
        style = self._style_mapping(self.style, "style")
        if style:
            dom["style"] = style
        styles = {
            slot: self._style_mapping(slot_style, f"chrome_styles[{slot!r}]")
            for slot, slot_style in self.chrome_styles.items()
        }
        styles = {slot: slot_style for slot, slot_style in styles.items() if slot_style}
        if styles:
            dom["styles"] = styles
        return dom

    # -- per-kind payload emitters (extend here for new chart types) ---------

    def _rect_finite_sel(
        self,
        t: Trace,
        x0v: np.ndarray,
        x1v: np.ndarray,
        y0v: np.ndarray,
        y1v: np.ndarray,
    ) -> Optional[np.ndarray]:
        """Rows that can safely become rectangle vertices, or None for all rows."""
        finite = np.isfinite(x0v) & np.isfinite(x1v) & np.isfinite(y0v) & np.isfinite(y1v)
        if t.color_ch and t.color_ch.mode == "continuous":
            values = t.color_ch.values
            if values is None:
                raise ValueError(f"{t.kind} continuous color channel missing values")
            finite &= np.isfinite(values)
        elif t.color_ch and t.color_ch.mode == "categorical":
            codes = t.color_ch.codes
            if codes is None:
                raise ValueError(f"{t.kind} categorical color channel missing codes")
            finite &= np.isfinite(codes)
        sel = np.flatnonzero(finite)
        return sel if len(sel) != len(x0v) else None

    # -- channel & density helpers -------------------------------------------

    # Interaction handlers live in interaction.py (§17/§34); these delegates are
    # the public API the widget and users call.

    def density_view(
        self, trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
    ) -> tuple[dict[str, Any], list[bytes]]:
        """Re-bin a Tier-2 scatter for a new viewport (§5)."""
        return interaction.density_view(self, trace_id, x0, x1, y0, y1, w, h)

    def pick(
        self, trace_id: int, index: int, drill_seq: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        """Exact source-row readout for a hover/pick (§16/§17); `index` is a
        shipped vertex index, translated to a canonical row when NaN rows were
        dropped at ship time (§19). Pass the client's `drill_seq` to reject a
        pick that raced a drill update (wrong index space → None, never a
        wrong row)."""
        return interaction.pick(self, trace_id, index, drill_seq)

    def select_range(
        self, x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
    ) -> dict[int, np.ndarray]:
        """Box-select → canonical indices per scatter trace (§34 Filter Tier A)."""
        return interaction.select_range(self, x0, x1, y0, y1, trace_id)

    def to_shipped_indices(self, trace_id: int, canonical: np.ndarray) -> np.ndarray:
        """Canonical rows → shipped vertex positions (the client's mask space)."""
        return interaction.to_shipped_indices(self, trace_id, canonical)

    def decimate_view(
        self, x0: float, x1: float, px_width: int
    ) -> tuple[dict[str, Any], list[bytes]]:
        """Re-decimate visible line windows on zoom (§28), offsets re-centered (§16)."""
        return interaction.decimate_view(self, x0, x1, px_width)

    def append(
        self, trace_id: int, x: Any, y: Any, *, color: Any = None, size: Any = None
    ) -> tuple[dict[str, Any], list[bytes]]:
        """Streaming append (rust-engine §5): extend a scatter/line trace's
        canonical columns and get the client refresh message back. The widget's
        `append` sends it; headless callers can inspect or discard it. Payloads
        stay screen-bounded (§29), so this is O(pixels) on the wire regardless
        of how much data has accumulated."""
        return interaction.append_data(self, trace_id, x, y, color, size)

    # -- output -----------------------------------------------------------

    def widget(self) -> Any:
        if self._widget is None:
            from .widget import FigureWidget

            self._widget = FigureWidget(self)
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
        """Standalone interactive HTML (export.py): JS client + spec + base64
        buffers in one self-contained file. Base64 carries a stated ~33% size
        tax (§29 static-export row). `custom_css` injects an author stylesheet
        so `class_names` utility classes (e.g. Tailwind) resolve in the export."""
        return export.to_html(self, path, custom_css=custom_css)

    def html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
    ) -> str:
        """Alias for ``to_html`` for component-style API symmetry."""
        return self.to_html(path, custom_css=custom_css)

    def _repr_html_(self) -> str:
        """Notebook HTML repr fallback using the standalone export path."""
        return self.to_html()

    def to_svg(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> str:
        """Static SVG (_svg.py): a pure-Python render of the same decimated
        payload the browser client consumes — resolution-independent, tiny
        (screen-bounded regardless of source size), and dependency-free.
        `width`/`height` override the figure's pixel size."""
        from . import _svg

        return _svg.to_svg(self, path, width=width, height=height)

    def to_png(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        engine: str = "native",
        chromium: Optional[str] = None,
        sandbox: bool = True,
    ) -> bytes:
        """Static PNG (export.py). `engine="native"` (default) paints the
        decimated payload with the built-in Rust rasterizer — no browser,
        millisecond export, small indexed PNGs. `engine="chromium"` screenshots
        the standalone HTML for a pixel-exact match to the live WebGL chart
        (needs a Chromium/Chrome binary; see export.find_chromium)."""
        return export.to_png(
            self,
            path,
            width=width,
            height=height,
            scale=scale,
            engine=engine,
            chromium=chromium,
            sandbox=sandbox,
        )

    def memory_report(self) -> dict[str, Any]:
        """§27: every byte class itemized; if it isn't in the report it isn't real."""
        spec, blob = self.build_payload()
        report = self.store.memory_report()
        report["transport_bytes_first_paint"] = len(blob)
        n_total = sum(t.n_points for t in self.traces) or 1
        report["transport_bytes_per_point"] = len(blob) / n_total
        report["backend"] = kernels.BACKEND
        return report

    @staticmethod
    def _optional_state_style(
        value: Optional[dict[str, Any]], label: str
    ) -> dict[str, str | int | float]:
        if value is None:
            return {}
        return Figure._style_mapping(value, label)


# The AnnotationsMixin methods (in `_annotations.py`) carry a `-> "Figure"`
# return annotation; expose the concrete class in that module so
# `typing.get_type_hints` resolves it at runtime without a load-time cycle.
_annotations.Figure = Figure
