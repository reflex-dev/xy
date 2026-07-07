"""The Figure: a data-less spec + column handles (§9).

The spec is tiny JSON — trace kinds, styles, axis config, and *references* into
the column store. Data never rides in the spec: encoded f32 columns travel as
one binary blob beside it (§29: no JSON numbers, no re-encoding, parse-shaped
work is forbidden on the client).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Optional, TypeAlias

import numpy as np

from . import channels, columns, export, interaction, kernels, lod
from .channels import ColorChannel, SizeChannel
from .columns import Column, ColumnStore, ColumnStoreCheckpoint

# Tier/tuning constants live in config.py (shared with interaction/export);
# re-exported here because this module is their historic import path.
from .config import (  # noqa: E402
    DECIMATION_THRESHOLD,
    DEFAULT_PALETTE,
    DENSITY_GRID,
    DIRECT_SOFT_CEILING,
    PROTOCOL_VERSION,
    SCATTER_DENSITY_THRESHOLD,
)

_FigureCheckpoint: TypeAlias = tuple[ColumnStoreCheckpoint, int, dict[str, list[str]], int]


@dataclass
class Trace:
    id: int
    kind: str  # "line" | "scatter" | "area" | "histogram" | "bar" | "column" | "heatmap"
    x: Column
    y: Column
    x_axis: str = "x"
    y_axis: str = "y"
    name: Optional[str] = None
    style: dict[str, Any] = field(default_factory=dict)
    # Area-style marks keep an explicit baseline column; rectangle-like marks
    # use x0/x1/y0/y1 below.
    base: Optional[Column] = None
    # Grid-like marks (heatmap/image) ship one scalar grid plus metadata instead
    # of four rectangle columns per cell.
    grid: Optional[Column] = None
    grid_shape: Optional[tuple[int, int]] = None  # (rows, columns)
    count: Optional[int] = None
    # Rect-like marks ship four geometry columns while still keeping x/y as the
    # conventional center/value columns for common bookkeeping.
    x0: Optional[Column] = None
    x1: Optional[Column] = None
    y0: Optional[Column] = None
    y1: Optional[Column] = None
    color_ch: Optional[ColorChannel] = None  # scatter color encoding
    size_ch: Optional[SizeChannel] = None  # scatter size encoding
    # Tri-state density override: None = auto (threshold), True/False = forced.
    # (A bool here silently ignored density=False — staff-review finding.)
    force_density: Optional[bool] = None
    # Shipped-row → canonical-row mapping, set by build_payload when the shipped
    # copy drops NaN rows (§19), and by the drill-in view path when a Tier-2
    # trace ships its visible subset. The client's GPU pick and selection masks
    # speak in *shipped* indices; canonical readouts must translate through this
    # or hover/selection silently report the wrong rows.
    shipped_sel: Optional[Any] = None
    # Tier-2 drill state (§5: tier follows the *visible* count): True while the
    # current view ships real points instead of the density grid. Kernel-side
    # only — the per-view decision itself rides each update (§28).
    drill_mode: bool = False
    # Monotonic version of shipped_sel. Every drill update bumps it and ships
    # it; pick/selection echo it back so a reply computed against a *different*
    # subset is dropped instead of translating indices in the wrong space
    # (§16/§17: exact readout beats stale availability).
    drill_seq: int = 0

    @property
    def n_points(self) -> int:
        if self.count is not None:
            return self.count
        return len(self.x)

    def use_density(self) -> bool:
        """Whether this scatter renders as a Tier-2 density grid (§5)."""
        if self.kind != "scatter":
            return False
        if self.force_density is not None:
            return self.force_density
        per_point = (self.color_ch and self.color_ch.mode != "constant") or (
            self.size_ch and self.size_ch.mode != "constant"
        )
        # Per-point channels keep direct draw until the hard ceiling; plain
        # scatter aggregates earlier (its whole win is not drawing 10M dots).
        threshold = DIRECT_SOFT_CEILING if per_point else SCATTER_DENSITY_THRESHOLD
        return self.n_points > threshold


class _PayloadWriter:
    """Accumulates the binary blob + column table for `build_payload`.

    The single place that knows the wire encoding, so every chart type ships
    columns the same way (§29): `ship` for offset-encoded geometry (§4), and
    `ship_scalar` for raw f32 channels/grids already in final units (color
    codes, density counts, bin heights). Adding a chart means calling these, not
    re-implementing the encoding.
    """

    def __init__(self) -> None:
        self.columns: list[dict[str, Any]] = []
        self._chunks: list[bytes] = []
        self._pos = 0

    def ship(self, values: np.ndarray, col: "Column") -> int:
        """Offset-encoded geometry column: `(v - offset) * scale` as f32
        (§4/§16). Scale is 1.0 except for absurd-magnitude domains, where it
        normalizes so finite f64 can't overflow to ±inf in f32 (§19)."""
        offset = col.suggest_offset()
        scale = lod.f32_safe_scale(offset, col.min, col.max)
        enc = kernels.encode_f32(values, offset, scale)
        return self._append(enc, {"offset": offset, "scale": scale, "kind": col.kind})

    def ship_scalar(self, values: np.ndarray) -> int:
        """Raw f32 column already in final units (no offset): channel/grid/heights."""
        enc = np.ascontiguousarray(values, dtype=np.float32)
        return self._append(enc, {})

    def ship_values(self, values: np.ndarray, *, kind: str = "float") -> int:
        """Offset-encoded temporary geometry not backed by a canonical Column."""
        vals = np.ascontiguousarray(values, dtype=np.float64)
        bounds = kernels.min_max(vals)
        offset = (bounds[0] + bounds[1]) / 2.0 if bounds is not None else 0.0
        scale = lod.f32_safe_scale(offset, *bounds) if bounds is not None else 1.0
        enc = kernels.encode_f32(vals, offset, scale)
        return self._append(enc, {"offset": offset, "scale": scale, "kind": kind})

    def _append(self, enc: np.ndarray, meta: dict[str, Any]) -> int:
        raw = enc.tobytes()
        self.columns.append({"byte_offset": self._pos, "len": int(len(enc)), **meta})
        self._chunks.append(raw)
        self._pos += len(raw)
        return len(self.columns) - 1

    def blob(self) -> bytes:
        return b"".join(self._chunks)


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


class Figure:
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
    ) -> None:
        # width/height: pixels, or "100%" to fill the parent container — the
        # client measures the container and re-renders on resize
        # (ResizeObserver), re-requesting decimation/density at the new pixel
        # size (§28). height="100%" needs a parent with a defined height (the
        # usual CSS contract); otherwise the chart falls back to its 120px
        # min-height.
        self.width = self._pixel_dimension(width, "width")
        self.height = self._pixel_dimension(height, "height")
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
            "label_angle": self._optional_finite_scalar(
                label_angle, f"{axis_id} axis label_angle"
            ),
            "type": type_,
            "domain": domain,
            "reverse": self._bool_param(reverse, f"{axis_id} axis reverse"),
            "format": self._optional_text(format, f"{axis_id} axis format"),
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
    ) -> "Figure":
        name = self._optional_text(name, "line name")
        width = self._positive_scalar(width, "line width")
        opacity = self._opacity(opacity, "line opacity")
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
            self.traces.append(
                Trace(
                    id=len(self.traces),
                    kind="line",
                    x=xc,
                    y=yc,
                    name=name,
                    style={"color": color, "width": width, "opacity": opacity},
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
    ) -> "Figure":
        """Add a filled area trace between `y` and `base`.

        `base` may be a scalar or a length-N array, which covers both the common
        zero-baseline area chart and future stacked-area construction.
        """
        name = self._optional_text(name, "area name")
        opacity = self._opacity(opacity, "area opacity")
        line_width = self._nonnegative_scalar(line_width, "area line_width")
        line_opacity = self._opacity(line_opacity, "area line_opacity")
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
            self.traces.append(
                Trace(
                    id=len(self.traces),
                    kind="area",
                    x=xc,
                    y=yc,
                    base=bc,
                    name=name,
                    style={
                        "color": color,
                        "opacity": opacity,
                        "line_width": line_width,
                        "line_opacity": line_opacity,
                    },
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
    ) -> "Figure":
        """Add a scatter trace.

        `color` may be a CSS color (constant), a numeric array (continuous →
        colormap), or a categorical array (factorized → palette). `size` may be
        a scalar or a numeric array (mapped to `size_range` px). Large scatters
        auto-switch to a Tier-2 density surface (§5); pass `density=True/False`
        to force it.
        """
        name = self._optional_text(name, "scatter name")
        opacity = self._opacity(opacity, "scatter opacity")
        density = self._optional_bool(density, "scatter density")
        checkpoint = self._checkpoint()
        try:
            xc, yc = self._ingest_xy(x, y, "scatter")
            n = len(xc)
            default_color = DEFAULT_PALETTE[len(self.traces) % len(DEFAULT_PALETTE)]
            color_ch = channels.resolve_color(
                color, n, colormap=colormap, default_constant=default_color
            )
            size_ch = channels.resolve_size(size, n, range_px=size_range)

            trace = Trace(
                id=len(self.traces),
                kind="scatter",
                x=xc,
                y=yc,
                name=name,
                style={"opacity": opacity},
                color_ch=color_ch,
                size_ch=size_ch,
                force_density=density,
            )

            per_point = color_ch.mode != "constant" or size_ch.mode != "constant"
            if density is None and per_point and n > DIRECT_SOFT_CEILING:
                import warnings

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
                import warnings

                warnings.warn(
                    f"scatter has {n:,} points above the soft ceiling "
                    f"({DIRECT_SOFT_CEILING:,}); using a density surface for the "
                    "initial render.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            elif density is False and n > DIRECT_SOFT_CEILING:
                import warnings

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
        name: Optional[str] = None,
        color: Optional[str] = None,
        opacity: float = 0.85,
    ) -> "Figure":
        """Add a 1D histogram backed by the shared rectangle primitive."""
        name = self._optional_text(name, "histogram name")
        opacity = self._opacity(opacity, "histogram opacity")
        density = self._bool_param(density, "histogram density")
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
        zeros = np.zeros_like(counts, dtype=np.float64)
        self._append_rect_trace(
            "histogram",
            edges[:-1],
            edges[1:],
            zeros,
            counts.astype(np.float64, copy=False),
            name=name,
            color=color,
            opacity=opacity,
            role="histogram",
            count=int(len(vals)),
        )
        return self

    def hist(
        self,
        values: Any,
        *,
        bins: Any = "auto",
        range: Optional[tuple[float, float]] = None,
        density: bool = False,
        name: Optional[str] = None,
        color: Optional[str] = None,
        opacity: float = 0.85,
    ) -> "Figure":
        """Short alias for `histogram(...)`, matching common Python chart APIs."""
        return self.histogram(
            values,
            bins=bins,
            range=range,
            density=density,
            name=name,
            color=color,
            opacity=opacity,
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
    ) -> "Figure":
        """Add vertical bars. 2D y values render grouped or stacked series."""
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

    def vline(
        self,
        x: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#667085",
        width: float = 1.5,
        opacity: float = 1.0,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a vertical rule annotation at data coordinate `x`.

        Rules live in the chart chrome layer: they stay crisp during pan/zoom
        and annotate the current plot without adding a data trace or legend row.
        """
        return self._append_rule_annotation(
            "x",
            x,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def hline(
        self,
        y: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#667085",
        width: float = 1.5,
        opacity: float = 1.0,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a horizontal rule annotation at data coordinate `y`."""
        return self._append_rule_annotation(
            "y",
            y,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def x_band(
        self,
        x0: Any,
        x1: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#64748b",
        opacity: float = 0.14,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a vertical span annotation from `x0` to `x1`."""
        return self._append_band_annotation(
            "x",
            x0,
            x1,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def y_band(
        self,
        y0: Any,
        y1: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#64748b",
        opacity: float = 0.14,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a horizontal span annotation from `y0` to `y1`."""
        return self._append_band_annotation(
            "y",
            y0,
            y1,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def text(
        self,
        x: Any,
        y: Any,
        text: str,
        *,
        dx: float = 6.0,
        dy: float = -6.0,
        color: Optional[str] = None,
        anchor: str = "start",
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a text annotation anchored at a data coordinate."""
        text = self._required_text(text, "text annotation text")
        dx = self._finite_scalar(dx, "text annotation dx")
        dy = self._finite_scalar(dy, "text annotation dy")
        if anchor not in {"start", "middle", "end"}:
            raise ValueError("text annotation anchor must be 'start', 'middle', or 'end'")
        self.annotations.append(
            {
                "kind": "text",
                "x": x,
                "y": y,
                "text": text,
                "dx": dx,
                "dy": dy,
                "anchor": anchor,
                "style": {
                    "color": self._optional_text(color, "text annotation color"),
                    **self._style_mapping(style or {}, "text annotation style"),
                },
                "class_name": self._optional_text(class_name, "text annotation class_name"),
            }
        )
        return self

    def arrow(
        self,
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
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add an arrow annotation from (`x0`, `y0`) to (`x1`, `y1`)."""
        width = self._positive_scalar(width, "arrow width")
        opacity = self._opacity(opacity, "arrow opacity")
        self.annotations.append(
            {
                "kind": "arrow",
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "text": self._optional_text(text, "arrow text"),
                "style": {
                    "color": self._optional_text(color, "arrow color"),
                    "width": width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, "arrow style"),
                },
                "class_name": self._optional_text(class_name, "arrow class_name"),
            }
        )
        return self

    def callout(
        self,
        x: Any,
        y: Any,
        text: str,
        *,
        dx: float = 36.0,
        dy: float = -30.0,
        color: Optional[str] = "#344054",
        width: float = 1.5,
        opacity: float = 1.0,
        anchor: str = "start",
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a text callout offset from a data coordinate with a pointer arrow."""
        text = self._required_text(text, "callout text")
        dx = self._finite_scalar(dx, "callout dx")
        dy = self._finite_scalar(dy, "callout dy")
        width = self._positive_scalar(width, "callout width")
        opacity = self._opacity(opacity, "callout opacity")
        if anchor not in {"start", "middle", "end"}:
            raise ValueError("callout anchor must be 'start', 'middle', or 'end'")
        self.annotations.append(
            {
                "kind": "callout",
                "x": x,
                "y": y,
                "text": text,
                "dx": dx,
                "dy": dy,
                "anchor": anchor,
                "style": {
                    "color": self._optional_text(color, "callout color"),
                    "width": width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, "callout style"),
                },
                "class_name": self._optional_text(class_name, "callout class_name"),
            }
        )
        return self

    def _append_rule_annotation(
        self,
        axis: str,
        value: Any,
        *,
        text: Optional[str],
        color: Optional[str],
        width: float,
        opacity: float,
        class_name: Optional[str],
        style: Optional[dict[str, Any]],
    ) -> "Figure":
        width = self._positive_scalar(width, f"{axis} rule width")
        opacity = self._opacity(opacity, f"{axis} rule opacity")
        self.annotations.append(
            {
                "kind": "rule",
                "axis": axis,
                "value": value,
                "text": self._optional_text(text, f"{axis} rule text"),
                "style": {
                    "color": self._optional_text(color, f"{axis} rule color"),
                    "width": width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, f"{axis} rule style"),
                },
                "class_name": self._optional_text(class_name, f"{axis} rule class_name"),
            }
        )
        return self

    def _append_band_annotation(
        self,
        axis: str,
        start: Any,
        end: Any,
        *,
        text: Optional[str],
        color: Optional[str],
        opacity: float,
        class_name: Optional[str],
        style: Optional[dict[str, Any]],
    ) -> "Figure":
        opacity = self._opacity(opacity, f"{axis} band opacity")
        self.annotations.append(
            {
                "kind": "band",
                "axis": axis,
                "start": start,
                "end": end,
                "text": self._optional_text(text, f"{axis} band text"),
                "style": {
                    "color": self._optional_text(color, f"{axis} band color"),
                    "opacity": opacity,
                    **self._style_mapping(style or {}, f"{axis} band style"),
                },
                "class_name": self._optional_text(class_name, f"{axis} band class_name"),
            }
        )
        return self

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
    ) -> "Figure":
        name = self._optional_text(name, f"{kind} name")
        width = self._positive_scalar(width, f"{kind} width")
        opacity = self._opacity(opacity, f"{kind} opacity")
        if mode not in {"grouped", "stacked"}:
            raise ValueError(f"{kind} mode must be 'grouped' or 'stacked'")
        if orientation not in {"vertical", "horizontal"}:
            raise ValueError(f"{kind} orientation must be 'vertical' or 'horizontal'")
        category_axis = "x" if orientation == "vertical" else "y"
        pos = self._axis_positions(x, category_axis, commit=False)
        vals = self._bar_value_matrix(y, len(pos), kind)
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
                    role=kind,
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
                        role=f"{kind}-stacked",
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
            )

    @staticmethod
    def _as_1d_float(values: Any, label: str) -> np.ndarray:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{label} must be 1-D, got shape {arr.shape}")
        return Figure._real_float_array(arr, label)

    @staticmethod
    def _finite_scalar(value: Any, label: str) -> float:
        if isinstance(value, (bool, np.bool_)):
            raise ValueError(f"{label} must be a finite real number")
        try:
            out = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{label} must be a finite real number") from e
        if not np.isfinite(out):
            raise ValueError(f"{label} must be finite")
        return out

    @staticmethod
    def _finite_increasing_pair(values: Any, label: str) -> tuple[float, float]:
        try:
            lo_raw, hi_raw = values
        except (TypeError, ValueError) as e:
            raise ValueError(f"{label} must contain exactly two finite values") from e
        lo = Figure._finite_scalar(lo_raw, f"{label}[0]")
        hi = Figure._finite_scalar(hi_raw, f"{label}[1]")
        if hi <= lo:
            raise ValueError(f"{label} must be finite and increasing")
        return lo, hi

    @staticmethod
    def _positive_scalar(value: Any, label: str) -> float:
        out = Figure._finite_scalar(value, label)
        if out <= 0:
            raise ValueError(f"{label} must be positive")
        return out

    @staticmethod
    def _optional_finite_scalar(value: Any, label: str) -> Optional[float]:
        if value is None:
            return None
        return Figure._finite_scalar(value, label)

    @staticmethod
    def _nonnegative_scalar(value: Any, label: str) -> float:
        out = Figure._finite_scalar(value, label)
        if out < 0:
            raise ValueError(f"{label} must be non-negative")
        return out

    @staticmethod
    def _opacity(value: Any, label: str) -> float:
        out = Figure._finite_scalar(value, label)
        if out < 0 or out > 1:
            raise ValueError(f"{label} must be between 0 and 1")
        return out

    @staticmethod
    def _optional_bool(value: Any, label: str) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        raise ValueError(f"{label} must be True, False, or None")

    @staticmethod
    def _bool_param(value: Any, label: str) -> bool:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        raise ValueError(f"{label} must be True or False")

    @staticmethod
    def _axis_id(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty string")
        if value[0] not in {"x", "y"}:
            raise ValueError(f"{label} must start with 'x' or 'y'")
        if not all(ch.isalnum() or ch in {"_", "-"} for ch in value):
            raise ValueError(f"{label} may only contain letters, digits, '_' and '-'")
        return value

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

    @staticmethod
    def _optional_text(value: Any, label: str) -> Optional[str]:
        if value is None or isinstance(value, str):
            return value
        raise ValueError(f"{label} must be a string or None")

    @staticmethod
    def _axis_label_position(
        value: Any, label: str
    ) -> Optional[str | dict[str, str | int | float]]:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.replace("-", "_")
            allowed = {"start", "center", "end", "inside_start", "inside_center", "inside_end"}
            if normalized not in allowed:
                raise ValueError(f"{label} must be one of {sorted(allowed)} or a CSS style dict")
            return normalized
        return Figure._style_mapping(value, label)

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
            return list(colors)
        if isinstance(color, (list, tuple, np.ndarray)) and not isinstance(color, str):
            color_list: list[Optional[str]] = [str(c) for c in color]
            if len(color_list) != n_series:
                raise ValueError(
                    f"color sequence must have length {n_series}, got {len(color_list)}"
                )
            return color_list
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

    def build_payload(self, px_width: int = 2048) -> tuple[dict[str, Any], bytes]:
        """Encode every trace for first paint: (spec, binary buffer blob).

        Per-kind logic lives in `_emit_<kind>` methods dispatched here — adding a
        chart type means adding one emitter, not editing this loop. Direct traces
        ship whole columns offset-encoded (§4); long lines ship M4-decimated
        (§5 Tier 1); dense scatter ships a density grid (§5 Tier 2). Every
        reduction is recorded in the spec — no silent quality changes (§28).
        """
        pw = _PayloadWriter()
        spec_traces = []
        for t in self.traces:
            xr = self._range(t.x_axis)
            yr = self._range(t.y_axis)
            spec_traces.append(
                self._emit_trace(t, pw, (min(xr), max(xr)), (min(yr), max(yr)), px_width)
            )
        axis_specs = {
            axis_id: self._axis_spec(axis_id, self._range(axis_id)) for axis_id in self.axis_options
        }

        spec = {
            "protocol": PROTOCOL_VERSION,
            "width": self.width,
            "height": self.height,
            "title": self._optional_text(self.title, "title"),
            "x_axis": axis_specs["x"],
            "y_axis": axis_specs["y"],
            "axes": axis_specs,
            "traces": spec_traces,
            "columns": pw.columns,
            "backend": kernels.BACKEND,
            "show_legend": self.show_legend,
        }
        if self.show_modebar is False:
            spec["show_modebar"] = False
        if self.show_tooltip is False:
            spec["show_tooltip"] = False
        dom = self._dom_spec()
        if dom:
            spec["dom"] = dom
        if self.tooltip is not None:
            spec["tooltip"] = self.tooltip
        mark_style = self._mark_style_spec()
        if mark_style:
            spec["mark_style"] = mark_style
        interaction = self._interaction_spec()
        if interaction:
            spec["interaction"] = interaction
        annotations = self._annotation_specs()
        if annotations:
            spec["annotations"] = annotations
        return spec, pw.blob()

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
        if class_names:
            dom["class_names"] = class_names
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

    def _annotation_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for i, annotation in enumerate(self.annotations):
            kind = annotation.get("kind")
            label = f"annotation[{i}]"
            if kind == "rule":
                axis = self._annotation_axis(annotation.get("axis"), f"{label}.axis")
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "rule",
                        "axis": axis,
                        "value": self._annotation_value(
                            annotation.get("value"), axis, f"{label}.value"
                        ),
                    }
                )
            elif kind == "band":
                axis = self._annotation_axis(annotation.get("axis"), f"{label}.axis")
                start = self._annotation_value(annotation.get("start"), axis, f"{label}.start")
                end = self._annotation_value(annotation.get("end"), axis, f"{label}.end")
                if end <= start:
                    raise ValueError(f"{label} end must be greater than start")
                specs.append(
                    self._annotation_common(annotation)
                    | {"kind": "band", "axis": axis, "start": start, "end": end}
                )
            elif kind == "text":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "text",
                        "x": self._annotation_value(annotation.get("x"), "x", f"{label}.x"),
                        "y": self._annotation_value(annotation.get("y"), "y", f"{label}.y"),
                        "text": self._required_text(annotation.get("text"), f"{label}.text"),
                        "dx": self._finite_scalar(annotation.get("dx", 0.0), f"{label}.dx"),
                        "dy": self._finite_scalar(annotation.get("dy", 0.0), f"{label}.dy"),
                        "anchor": self._annotation_anchor(
                            annotation.get("anchor", "start"), f"{label}.anchor"
                        ),
                    }
                )
            elif kind == "arrow":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "arrow",
                        "x0": self._annotation_value(annotation.get("x0"), "x", f"{label}.x0"),
                        "y0": self._annotation_value(annotation.get("y0"), "y", f"{label}.y0"),
                        "x1": self._annotation_value(annotation.get("x1"), "x", f"{label}.x1"),
                        "y1": self._annotation_value(annotation.get("y1"), "y", f"{label}.y1"),
                    }
                )
            elif kind == "callout":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "callout",
                        "x": self._annotation_value(annotation.get("x"), "x", f"{label}.x"),
                        "y": self._annotation_value(annotation.get("y"), "y", f"{label}.y"),
                        "text": self._required_text(annotation.get("text"), f"{label}.text"),
                        "dx": self._finite_scalar(annotation.get("dx", 0.0), f"{label}.dx"),
                        "dy": self._finite_scalar(annotation.get("dy", 0.0), f"{label}.dy"),
                        "anchor": self._annotation_anchor(
                            annotation.get("anchor", "start"), f"{label}.anchor"
                        ),
                    }
                )
            else:
                raise ValueError(
                    f"{label} kind must be 'rule', 'band', 'text', 'arrow', or 'callout'"
                )
        return specs

    def _annotation_common(self, annotation: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        text = self._optional_text(annotation.get("text"), "annotation text")
        if text is not None:
            out["text"] = text
        class_name = self._optional_text(annotation.get("class_name"), "annotation class_name")
        if class_name is not None:
            out["class_name"] = class_name
        raw_style = annotation.get("style", {})
        if not isinstance(raw_style, dict):
            raise ValueError("annotation style must be a dict[str, str | int | float]")
        raw_style = {key: value for key, value in raw_style.items() if value is not None}
        style = self._style_mapping(raw_style, "annotation style")
        if style:
            out["style"] = style
        return out

    @staticmethod
    def _annotation_axis(axis: Any, label: str) -> str:
        if axis not in {"x", "y"}:
            raise ValueError(f"{label} must be 'x' or 'y'")
        return axis

    @staticmethod
    def _annotation_anchor(anchor: Any, label: str) -> str:
        if anchor not in {"start", "middle", "end"}:
            raise ValueError(f"{label} must be 'start', 'middle', or 'end'")
        return anchor

    def _annotation_value(self, value: Any, axis: str, label: str) -> float:
        categories = self._axis_categories.get(axis)
        if isinstance(value, str) and categories is not None:
            normalized = channels.category_label(value)
            try:
                return float(categories.index(normalized))
            except ValueError as e:
                raise ValueError(
                    f"{label} category {value!r} is not present on the {axis}-axis"
                ) from e
        if isinstance(value, str):
            raise ValueError(
                f"{label} must be a finite coordinate; string coordinates require "
                f"a categorical {axis}-axis"
            )
        try:
            arr, _kind, _copies = columns._canonicalize([value])
        except ValueError as e:
            raise ValueError(f"{label} must be a finite coordinate") from e
        out = float(arr[0])
        if not np.isfinite(out):
            raise ValueError(f"{label} must be finite")
        return out

    # -- per-kind payload emitters (extend here for new chart types) ---------

    def _emit_trace(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        emitter = getattr(self, f"_emit_{t.kind}", None)
        if emitter is None:
            raise ValueError(f"no payload emitter for trace kind {t.kind!r}")
        return emitter(t, pw, xr, yr, px_width)

    def _base_entry(
        self, t: Trace, pw: "_PayloadWriter", xv: np.ndarray, yv: np.ndarray, tier: str, style: dict
    ) -> dict[str, Any]:
        """The shared spec skeleton for any xy trace that ships x/y geometry."""
        return {
            "id": t.id,
            "kind": t.kind,
            "name": t.name,
            "style": style,
            "tier": tier,
            "n_points": t.n_points,
            "n_marks": int(len(xv)),
            "x": pw.ship(xv, t.x),
            "y": pw.ship(yv, t.y),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
        }

    @staticmethod
    def _finite_sel(t: Trace, xv: np.ndarray, yv: np.ndarray):
        """Indices where both x and y are finite, or None if nothing to drop.

        Non-finite (NaN or ±inf) never reaches a vertex buffer — it silently
        corrupts primitives, driver-dependently (§19). Zone maps count both as
        null, so we only scan when a null is present. Canonical keeps every row;
        real gap semantics (segment index list) arrive with validity bitmaps.
        """
        if not (t.x.zone.null_count or t.y.zone.null_count):
            return None
        return np.flatnonzero(np.isfinite(xv) & np.isfinite(yv))

    def _log_visible_mask(
        self,
        t: Trace,
        xv: np.ndarray,
        yv: np.ndarray,
        base: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        mask = np.isfinite(xv) & np.isfinite(yv)
        if self._axis_scale(t.x_axis) == "log":
            mask &= xv > 0
        if self._axis_scale(t.y_axis) == "log":
            mask &= yv > 0
            if base is not None:
                mask &= np.isfinite(base) & (base > 0)
        elif base is not None:
            mask &= np.isfinite(base)
        return mask

    def _emit_line(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        xv, yv = t.x.values, t.y.values
        tier = "direct"
        if t.n_points > DECIMATION_THRESHOLD:
            # M4 already excludes non-finite within the visible window (§19).
            idx = kernels.m4_indices(xv, yv, xr[0], xr[1] + np.finfo(np.float64).eps, px_width)
            tier = "decimated"
            if len(idx):
                xv, yv = xv[idx], yv[idx]
            else:
                xv, yv = xv[:0], yv[:0]
        else:
            sel = self._finite_sel(t, xv, yv)
            if sel is not None:
                xv, yv = xv[sel], yv[sel]
        if len(xv):
            finite = self._log_visible_mask(t, xv, yv)
            if not bool(np.all(finite)):
                xv, yv = xv[finite], yv[finite]
        style = dict(t.style)
        if style.get("color") is None:
            style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
        return self._base_entry(t, pw, xv, yv, tier, style)

    def _emit_area(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        if t.base is None:
            raise ValueError("area trace missing baseline column")
        xv, yv, bv = t.x.values, t.y.values, t.base.values
        tier = "direct"
        if t.n_points > DECIMATION_THRESHOLD:
            idx = kernels.m4_indices(xv, yv, xr[0], xr[1] + np.finfo(np.float64).eps, px_width)
            tier = "decimated"
            if len(idx):
                xv, yv, bv = xv[idx], yv[idx], bv[idx]
            else:
                xv, yv, bv = xv[:0], yv[:0], bv[:0]
        sel = np.flatnonzero(self._log_visible_mask(t, xv, yv, bv))
        if len(sel) != len(xv):
            xv, yv, bv = xv[sel], yv[sel], bv[sel]
        style = dict(t.style)
        if style.get("color") is None:
            style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
        entry = self._base_entry(t, pw, xv, yv, tier, style)
        entry["base"] = pw.ship(bv, t.base)
        return entry

    def _emit_scatter(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        if t.use_density():
            t.shipped_sel = None  # no per-point marks, no pick mapping
            t.drill_mode = False  # full view: density until a zoom drills in
            return self._density_trace_spec(t, xr, yr, *DENSITY_GRID, pw.ship_scalar)
        xv, yv = t.x.values, t.y.values
        sel = self._finite_sel(t, xv, yv)
        if sel is not None:
            xv, yv = xv[sel], yv[sel]
        if len(xv):
            visible = self._log_visible_mask(t, xv, yv)
            if not bool(np.all(visible)):
                sel = np.flatnonzero(visible) if sel is None else sel[visible]
                xv, yv = xv[visible], yv[visible]
        entry = self._base_entry(t, pw, xv, yv, "direct", dict(t.style))
        entry["color"], entry["size"] = self._ship_channels(t, sel, pw.ship_scalar)
        t.shipped_sel = sel  # pick/selection translation (§17)
        return entry

    def _emit_histogram(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_rect(t, pw, xr, yr, px_width)

    def _emit_bar(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_bar_compact(t, pw, xr, yr, px_width)

    def _emit_column(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_bar_compact(t, pw, xr, yr, px_width)

    def _emit_heatmap(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        del xr, yr, px_width
        if t.grid is None or t.grid_shape is None:
            raise ValueError("heatmap trace missing grid column")
        rows, cols = t.grid_shape
        domain = tuple(t.style["domain"])
        norm = kernels.normalize_f32(t.grid.values, domain, nonfinite="nan")
        cmap = t.style.get("colormap", channels.DEFAULT_COLORMAP)
        return {
            "id": t.id,
            "kind": "heatmap",
            "name": t.name,
            "style": dict(t.style),
            "tier": "direct",
            "n_points": t.n_points,
            "n_marks": int(rows * cols),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "heatmap": {
                "buf": pw.ship_scalar(norm),
                "w": int(cols),
                "h": int(rows),
                "x_range": list(t.style["x_range"]),
                "y_range": list(t.style["y_range"]),
                "colormap": cmap,
                "domain": list(domain),
            },
            "color": {"mode": "continuous", "colormap": cmap, "domain": list(domain)},
        }

    def _emit_rect(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        del xr, yr, px_width
        if t.x0 is None or t.x1 is None or t.y0 is None or t.y1 is None:
            raise ValueError(f"{t.kind} trace missing rectangle columns")
        x0v, x1v, y0v, y1v = t.x0.values, t.x1.values, t.y0.values, t.y1.values
        sel_arg = self._rect_finite_sel(t, x0v, x1v, y0v, y1v)
        if sel_arg is not None:
            x0v, x1v, y0v, y1v = x0v[sel_arg], x1v[sel_arg], y0v[sel_arg], y1v[sel_arg]
        style = dict(t.style)
        if style.get("color") is None:
            style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
        entry = {
            "id": t.id,
            "kind": t.kind,
            "name": t.name,
            "style": style,
            "tier": "direct",
            "n_points": t.n_points,
            "n_marks": int(len(x0v)),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "x0": pw.ship(x0v, t.x0),
            "x1": pw.ship(x1v, t.x1),
            "y0": pw.ship(y0v, t.y0),
            "y1": pw.ship(y1v, t.y1),
        }
        if t.color_ch is not None:
            entry["color"], _size = self._ship_channels(t, sel_arg, pw.ship_scalar)
        return entry

    def _emit_bar_compact(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        del xr, yr, px_width
        if t.x0 is None or t.x1 is None or t.y0 is None or t.y1 is None:
            raise ValueError(f"{t.kind} trace missing bar columns")

        x0v, x1v, y0v, y1v = t.x0.values, t.x1.values, t.y0.values, t.y1.values
        sel_arg = self._rect_finite_sel(t, x0v, x1v, y0v, y1v)
        if sel_arg is not None:
            x0v, x1v, y0v, y1v = x0v[sel_arg], x1v[sel_arg], y0v[sel_arg], y1v[sel_arg]

        orientation = str(t.style.get("orientation", "vertical"))
        if orientation == "vertical":
            widths = x1v - x0v
            pos = t.x.values if sel_arg is None else t.x.values[sel_arg]
            value0 = y0v
            value1 = t.y.values if sel_arg is None else t.y.values[sel_arg]
            pos_ref = pw.ship(pos, t.x)
            value1_ref = pw.ship(value1, t.y)
            value0_col = t.y0
            value_axis = "y"
        elif orientation == "horizontal":
            widths = y1v - y0v
            pos = (y0v + y1v) / 2.0
            value0 = x0v
            value1 = x1v
            pos_ref = pw.ship_values(pos)
            value1_ref = pw.ship(value1, t.x1)
            value0_col = t.x0
            value_axis = "x"
        else:
            raise ValueError(f"unknown bar orientation {orientation!r}")

        if len(widths) == 0:
            width = 1.0
        else:
            width = float(widths[0])
            if not np.isfinite(width) or width <= 0 or not np.allclose(widths, width):
                return self._emit_rect(t, pw, (), (), 0)

        style = dict(t.style)
        if style.get("color") is None:
            style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
        bar_spec: dict[str, Any] = {
            "orientation": orientation,
            "value_axis": value_axis,
            "pos": pos_ref,
            "value1": value1_ref,
            "width": width,
        }
        if len(value0) and np.isfinite(value0).all() and np.all(value0 == value0[0]):
            bar_spec["value0_const"] = float(value0[0])
        else:
            bar_spec["value0"] = pw.ship(value0, value0_col)

        entry = {
            "id": t.id,
            "kind": t.kind,
            "name": t.name,
            "style": style,
            "tier": "direct",
            "n_points": t.n_points,
            "n_marks": int(len(pos)),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "bar": bar_spec,
        }
        if t.color_ch is not None:
            entry["color"], _size = self._ship_channels(t, sel_arg, pw.ship_scalar)
        return entry

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

    def _ship_channels(self, t: Trace, sel, ship_scalar) -> tuple[Any, Any]:  # noqa: ANN001
        """Ship a trace's color/size channels (delegates to channels.py — the
        same wire shape serves the build path and drill-in view updates)."""
        return channels.ship_channels(t, sel, ship_scalar, DEFAULT_PALETTE)

    def _density_trace_spec(self, t: Trace, xr, yr, w, h, ship_scalar) -> dict[str, Any]:  # noqa: ANN001
        """Bin a scatter into a density grid and build its spec entry (§5 Tier 2).
        The grid ships as one f32 buffer (h×w counts); the client colormaps it,
        recomputing the normalization domain per view so brightness is stable (§F6)."""
        grid = kernels.bin_2d(t.x.values, t.y.values, xr[0], xr[1], yr[0], yr[1], w, h)
        gmax = float(grid.max()) if grid.size else 0.0
        # Honor the user's colormap for the density ramp even though the per-point
        # color *data* can't survive count-aggregation (needs the §5-F5 algebra).
        cmap = (
            t.color_ch.colormap
            if (t.color_ch and t.color_ch.mode == "continuous")
            else channels.DEFAULT_COLORMAP
        )
        color_dropped = bool(t.color_ch and t.color_ch.mode != "constant")
        size_dropped = bool(t.size_ch and t.size_ch.mode != "constant")
        dropped = color_dropped or size_dropped
        return {
            "id": t.id,
            "kind": "scatter",
            "name": t.name,
            "style": dict(t.style),
            "tier": "density",
            "n_points": t.n_points,
            "n_marks": int(w * h),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "density": {
                "buf": ship_scalar(grid.reshape(-1)),
                "w": w,
                "h": h,
                "max": gmax,
                "colormap": cmap,
                "x_range": list(xr),
                "y_range": list(yr),
                "channels_dropped": dropped,  # never silent (§28)
            },
        }

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

    def to_html(self, path: Optional[str | PathLike[str]] = None) -> str:
        """Standalone interactive HTML (export.py): JS client + spec + base64
        buffers in one self-contained file. Base64 carries a stated ~33% size
        tax (§29 static-export row)."""
        return export.to_html(self, path)

    def html(self, path: Optional[str | PathLike[str]] = None) -> str:
        """Alias for ``to_html`` for component-style API symmetry."""
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
        """Static PNG (export.py): renders the standalone HTML in headless
        Chromium and screenshots it, so the raster matches the live chart.
        Needs a Chromium/Chrome binary (see export.find_chromium); HTML export
        needs nothing extra."""
        return export.to_png(
            self,
            path,
            width=width,
            height=height,
            scale=scale,
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
    def _string_mapping(value: dict[str, Any], label: str) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a dict[str, str]")
        out: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError(f"{label} must be a dict[str, str]")
            out[key] = item
        return out

    @staticmethod
    def _style_mapping(value: dict[str, Any], label: str) -> dict[str, str | int | float]:
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a dict[str, str | int | float]")
        out: dict[str, str | int | float] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(
                item, (str, int, float, np.integer, np.floating)
            ):
                raise ValueError(f"{label} must be a dict[str, str | int | float]")
            if isinstance(item, (bool, np.bool_)):
                raise ValueError(f"{label} must be a dict[str, str | int | float]")
            number = (
                float(item) if isinstance(item, (int, float, np.integer, np.floating)) else None
            )
            if number is not None and not np.isfinite(number):
                raise ValueError(f"{label} numeric values must be finite")
            out[key] = item.item() if isinstance(item, (np.integer, np.floating)) else item
        return out

    @staticmethod
    def _optional_state_style(
        value: Optional[dict[str, Any]], label: str
    ) -> dict[str, str | int | float]:
        if value is None:
            return {}
        return Figure._style_mapping(value, label)
