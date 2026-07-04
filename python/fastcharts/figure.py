"""The Figure: a data-less spec + column handles (§9).

The spec is tiny JSON — trace kinds, styles, axis config, and *references* into
the column store. Data never rides in the spec: encoded f32 columns travel as
one binary blob beside it (§29: no JSON numbers, no re-encoding, parse-shaped
work is forbidden on the client).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from . import channels, export, interaction, kernels
from .channels import ColorChannel, SizeChannel
from .column import Column, ColumnStore

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


@dataclass
class Trace:
    id: int
    kind: str  # "line" | "scatter" | "candlestick"
    x: Column
    y: Column
    name: Optional[str] = None
    style: dict[str, Any] = field(default_factory=dict)
    color_ch: Optional[ColorChannel] = None  # scatter color encoding
    size_ch: Optional[SizeChannel] = None  # scatter size encoding
    # OHLC columns for candlestick/bar-range marks (§28: multi-column mark).
    # `y` mirrors close so the shared xy machinery has a sensible fallback; the
    # y-autorange hook below uses low/high, not close.
    open_: Optional[Column] = None
    high: Optional[Column] = None
    low: Optional[Column] = None
    close: Optional[Column] = None
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
        return len(self.x)

    def range_for(self, axis: str) -> tuple[float, float]:
        """Data extent this trace contributes to autorange on `axis`. The
        per-kind hook (§28): candlesticks must span low..high on y, not close —
        clamping to close would clip every wick."""
        if axis == "x":
            return self.x.min, self.x.max
        if self.close is not None:
            return self.low.min, self.high.max
        return self.y.min, self.y.max

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
        """Offset-encoded geometry column: `(v - offset)` as f32 (§4/§16)."""
        offset = col.suggest_offset()
        enc = kernels.encode_f32(values, offset, 1.0)
        return self._append(enc, {"offset": offset, "scale": 1.0, "kind": col.kind})

    def ship_at(self, values: np.ndarray, offset: float, kind: str = "float") -> int:
        """Offset-encode against an *explicit* shared offset — for a group of
        columns that must map on one axis together (a candle's open/high/low/
        close all ride the y offset, §16), where each column's own midpoint
        would desync them."""
        enc = kernels.encode_f32(values, offset, 1.0)
        return self._append(enc, {"offset": offset, "scale": 1.0, "kind": kind})

    def ship_scalar(self, values: np.ndarray) -> int:
        """Raw f32 column already in final units (no offset): channel/grid/heights."""
        enc = np.ascontiguousarray(values, dtype=np.float32)
        return self._append(enc, {})

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

    def __init__(self, figure: "Figure", per_trace: dict) -> None:
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
        idx = self.per_trace.get(trace_id)
        t = self._figure.traces[trace_id]
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
        for name, v in (("width", width), ("height", height)):
            if isinstance(v, str) and v != "100%":
                raise ValueError(f'{name} must be an int (pixels) or "100%", got {v!r}')
        self.width = width
        self.height = height
        self.title = title
        self.x_label = x_label
        self.y_label = y_label
        self.store = ColumnStore()
        self.traces: list[Trace] = []
        self.show_legend = True
        self._widget: Any = None

    # -- trace builders -----------------------------------------------------

    def _ingest_xy(self, x: Any, y: Any, kind: str) -> tuple[Column, Column]:
        """Ingest an (x, y) pair into the column store with the equal-length
        contract every xy chart shares (line/scatter/area/bar/…)."""
        xc = self.store.ingest(x)
        yc = self.store.ingest(y)
        if len(xc) != len(yc):
            raise ValueError(f"{kind} x and y must have equal length, got {len(xc)} and {len(yc)}")
        return xc, yc

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

    def candlestick(
        self,
        x: Any,
        open: Any,  # noqa: A002 - OHLC naming is the domain convention
        high: Any,
        low: Any,
        close: Any,
        *,
        name: Optional[str] = None,
        up_color: str = "#26a69a",  # teal/orange default — CVD-safer than green/red
        down_color: str = "#ef5350",
        width_frac: float = 0.7,  # body width as a fraction of candle slot
        opacity: float = 1.0,
    ) -> "Figure":
        """Add a candlestick (OHLC) trace. `x` is the time/period axis; `open`,
        `high`, `low`, `close` are equal-length series. Body spans open→close,
        wick spans low→high; up (close≥open) and down candles are colored
        distinctly. Large series ship OHLC-bucketed for a screen-bounded first
        paint (§5/§28). Y-autorange spans low..high."""
        cols = [self.store.ingest(v) for v in (x, open, high, low, close)]
        n0 = len(cols[0])
        if any(len(c) != n0 for c in cols):
            raise ValueError(
                "candlestick x/open/high/low/close must have equal length, got "
                f"{[len(c) for c in cols]}"
            )
        xc = cols[0]
        # Candles must be x-sorted (decimation buckets by x; §28 sorted rule).
        if not np.all(np.diff(xc.values) >= 0):
            order = np.argsort(xc.values, kind="stable")
            cols = [self.store.ingest(c.values[order]) for c in cols]
        xc, oc, hc, lc, cc = cols
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="candlestick",
                x=xc,
                y=cc,  # close, so the shared xy machinery has a fallback
                name=name,
                style={
                    "up_color": up_color,
                    "down_color": down_color,
                    "width_frac": float(width_frac),
                    "opacity": opacity,
                },
                open_=oc,
                high=hc,
                low=lc,
                close=cc,
            )
        )
        return self

    # -- ranges ---------------------------------------------------------------

    def x_range(self) -> tuple[float, float]:
        return self._range("x")

    def y_range(self) -> tuple[float, float]:
        return self._range("y")

    def _range(self, axis: str) -> tuple[float, float]:
        # Autorange is O(chunks) via zone maps (§22), not an O(n) rescan.
        lo = np.inf
        hi = -np.inf
        for t in self.traces:
            t_lo, t_hi = t.range_for(axis)
            lo = min(lo, t_lo)
            hi = max(hi, t_hi)
        if not np.isfinite(lo) or not np.isfinite(hi):
            return (0.0, 1.0)
        if lo == hi:
            pad = abs(lo) * 0.05 or 0.5
            return (lo - pad, hi + pad)
        pad = (hi - lo) * 0.03
        return (lo - pad, hi + pad)

    def _axis_kind(self, axis: str) -> str:
        for t in self.traces:
            col = t.x if axis == "x" else t.y
            if col.kind == "time_ms":
                return "time"
        return "linear"

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
        xr = self.x_range()
        yr = self.y_range()
        spec_traces = [self._emit_trace(t, pw, xr, yr, px_width) for t in self.traces]

        spec = {
            "protocol": PROTOCOL_VERSION,
            "width": self.width,
            "height": self.height,
            "title": self.title,
            "x_axis": {"kind": self._axis_kind("x"), "label": self.x_label, "range": list(xr)},
            "y_axis": {"kind": self._axis_kind("y"), "label": self.y_label, "range": list(yr)},
            "traces": spec_traces,
            "columns": pw.columns,
            "backend": kernels.BACKEND,
            "show_legend": self.show_legend,
        }
        return spec, pw.blob()

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
            "x": pw.ship(xv, t.x),
            "y": pw.ship(yv, t.y),
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

    def _emit_line(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        xv, yv = t.x.values, t.y.values
        tier = "direct"
        if t.n_points > DECIMATION_THRESHOLD:
            # M4 already excludes non-finite within the visible window (§19).
            idx = kernels.m4_indices(xv, yv, xr[0], xr[1] + np.finfo(np.float64).eps, px_width)
            if len(idx):
                xv, yv, tier = xv[idx], yv[idx], "decimated"
        else:
            sel = self._finite_sel(t, xv, yv)
            if sel is not None:
                xv, yv = xv[sel], yv[sel]
        style = dict(t.style)
        if style.get("color") is None:
            style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
        return self._base_entry(t, pw, xv, yv, tier, style)

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
        entry = self._base_entry(t, pw, xv, yv, "direct", dict(t.style))
        entry["color"], entry["size"] = self._ship_channels(t, sel, pw.ship_scalar)
        t.shipped_sel = sel  # pick/selection translation (§17)
        return entry

    def _emit_candlestick(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        x = t.x.values
        o, h, low, c = t.open_.values, t.high.values, t.low.values, t.close.values
        tier = "direct"
        if t.n_points > DECIMATION_THRESHOLD:
            # OHLC-bucket per pixel column: screen-bounded first paint (§5). The
            # candlestick analog of M4 — open=first, high=max, low=min,
            # close=last per bucket preserves the candle's meaning.
            xd, od, hd, ld, cd = kernels.ohlc_decimate(
                x, o, h, low, c, xr[0], xr[1] + np.finfo(np.float64).eps, px_width
            )
            if len(xd):
                x, o, h, low, c, tier = xd, od, hd, ld, cd, "decimated"
        else:
            finite = (
                np.isfinite(x) & np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c)
            )
            if not finite.all():
                x, o, h, low, c = x[finite], o[finite], h[finite], low[finite], c[finite]
        # open/high/low/close share the y offset so they map on one axis (§16).
        y_off = t.close.suggest_offset()
        k = t.close.kind
        return {
            "id": t.id,
            "kind": "candlestick",
            "name": t.name,
            "style": dict(t.style),
            "tier": tier,
            "n_points": t.n_points,
            "x": pw.ship(x, t.x),
            "open": pw.ship_at(o, y_off, k),
            "high": pw.ship_at(h, y_off, k),
            "low": pw.ship_at(low, y_off, k),
            "close": pw.ship_at(c, y_off, k),
        }

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

    def to_html(self, path: Optional[str] = None) -> str:
        """Standalone interactive HTML (export.py): JS client + spec + base64
        buffers in one self-contained file. Base64 carries a stated ~33% size
        tax (§29 static-export row)."""
        return export.to_html(self, path)

    def memory_report(self) -> dict[str, Any]:
        """§27: every byte class itemized; if it isn't in the report it isn't real."""
        spec, blob = self.build_payload()
        report = self.store.memory_report()
        report["transport_bytes_first_paint"] = len(blob)
        n_total = sum(t.n_points for t in self.traces) or 1
        report["transport_bytes_per_point"] = len(blob) / n_total
        report["backend"] = kernels.BACKEND
        return report
