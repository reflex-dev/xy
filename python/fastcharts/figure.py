"""The Figure: a data-less spec + column handles (§9).

The spec is tiny JSON — trace kinds, styles, axis config, and *references* into
the column store. Data never rides in the spec: encoded f32 columns travel as
one binary blob beside it (§29: no JSON numbers, no re-encoding, parse-shaped
work is forbidden on the client).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from . import channels, kernels
from .channels import ColorChannel, SizeChannel
from .column import Column, ColumnStore

PROTOCOL_VERSION = 2

# Line traces longer than this ship M4-decimated (Tier 1, §5); the canonical
# column stays kernel-side for re-decimation on zoom (§28: recompute for the
# visible x-range only).
DECIMATION_THRESHOLD = 10_000

# Scatter above this many points switches to Tier-2 density aggregation (§5):
# instead of shipping/drawing every point (fill-rate + the ~1 GB single-alloc
# cliff, §5 F3), the kernel bins the viewport into a density grid and the client
# colormaps it. Screen-bounded transport and VRAM regardless of point count.
SCATTER_DENSITY_THRESHOLD = 200_000

# Absolute direct-draw ceiling; above this, density is forced even if the user
# asked for per-point channels (they can't survive count-aggregation without the
# §5-F5 aggregation algebra — we warn and drop them, never silently mislead).
DIRECT_SOFT_CEILING = 2_000_000

# Default density grid resolution (cells). Screen-bounded (§5); the client
# requests a viewport-matched size on zoom via density_view.
DENSITY_GRID = (512, 384)

# CVD-safe default categorical palette (§20/§36 default theme).
DEFAULT_PALETTE = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
]


@dataclass
class Trace:
    id: int
    kind: str  # "line" | "scatter"
    x: Column
    y: Column
    name: Optional[str] = None
    style: dict[str, Any] = field(default_factory=dict)
    color_ch: Optional[ColorChannel] = None  # scatter color encoding
    size_ch: Optional[SizeChannel] = None  # scatter size encoding
    force_density: bool = False  # user opted into Tier-2 explicitly

    @property
    def n_points(self) -> int:
        return len(self.x)

    def use_density(self) -> bool:
        """Whether this scatter renders as a Tier-2 density grid (§5)."""
        if self.kind != "scatter":
            return False
        if self.force_density:
            return True
        per_point = (self.color_ch and self.color_ch.mode != "constant") or (
            self.size_ch and self.size_ch.mode != "constant"
        )
        # Per-point channels keep direct draw until the hard ceiling; plain
        # scatter aggregates earlier (its whole win is not drawing 10M dots).
        threshold = DIRECT_SOFT_CEILING if per_point else SCATTER_DENSITY_THRESHOLD
        return self.n_points > threshold


class Figure:
    """Build with `line()` / `scatter()`, display with `show()` (notebook) or
    `to_html()` (standalone file, no kernel round-trips)."""

    def __init__(
        self,
        *,
        width: int = 900,
        height: int = 420,
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
    ) -> None:
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
        xc = self.store.ingest(x)
        yc = self.store.ingest(y)
        if np.any(np.diff(xc.values) < 0):
            # LOD contract (§28): line x must be sorted; the engine sorts once
            # at ingest, and says so.
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
        xc = self.store.ingest(x)
        yc = self.store.ingest(y)
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
            force_density=bool(density) if density is not None else False,
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

        self.traces.append(trace)
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
            col = t.x if axis == "x" else t.y
            lo = min(lo, col.min)
            hi = max(hi, col.max)
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

        Direct traces ship whole columns offset-encoded (§4); long lines ship
        M4-decimated to ~4 points per pixel column (§5 Tier 1). Every reduction
        is recorded in the spec — no silent quality changes (§28).
        """
        shipped: list[dict[str, Any]] = []
        chunks: list[bytes] = []
        byte_pos = 0

        def ship(values: np.ndarray, col: Column) -> int:
            nonlocal byte_pos
            offset = col.suggest_offset()
            enc = kernels.encode_f32(values, offset, 1.0)
            raw = enc.tobytes()
            meta = {
                "byte_offset": byte_pos,
                "len": int(len(enc)),
                "offset": offset,
                "scale": 1.0,
                "kind": col.kind,
            }
            shipped.append(meta)
            chunks.append(raw)
            byte_pos += len(raw)
            return len(shipped) - 1

        def ship_scalar(values: np.ndarray) -> int:
            """Ship a raw f32 channel (already normalized/coded, no offset)."""
            nonlocal byte_pos
            enc = np.ascontiguousarray(values, dtype=np.float32)
            raw = enc.tobytes()
            shipped.append({"byte_offset": byte_pos, "len": int(len(enc))})
            chunks.append(raw)
            byte_pos += len(raw)
            return len(shipped) - 1

        xr = self.x_range()
        yr = self.y_range()

        spec_traces: list[dict[str, Any]] = []
        for t in self.traces:
            style = dict(t.style)

            if t.use_density():
                # Tier 2: ship a density grid, not points (§5).
                w, h = DENSITY_GRID
                spec_traces.append(self._density_trace_spec(t, xr, yr, w, h, ship_scalar))
                continue

            tier = "direct"
            xv, yv = t.x.values, t.y.values
            sel = None  # index selection applied to x/y — channels must match
            if t.kind == "line" and t.n_points > DECIMATION_THRESHOLD:
                idx = kernels.m4_indices(xv, yv, xr[0], xr[1] + np.finfo(np.float64).eps, px_width)
                if len(idx):
                    sel = idx
                    xv, yv = xv[idx], yv[idx]
                    tier = "decimated"
            elif t.x.zone.null_count or t.y.zone.null_count:
                # NaN never reaches a vertex buffer — it silently corrupts
                # primitives, driver-dependently (§19). Phase 0 drops invalid
                # rows on the shipped copy (canonical keeps them); real gap
                # semantics (segment index list) arrive with validity bitmaps.
                sel = np.flatnonzero(~(np.isnan(xv) | np.isnan(yv)))
                xv, yv = xv[sel], yv[sel]

            entry: dict[str, Any] = {
                "id": t.id,
                "kind": t.kind,
                "name": t.name,
                "style": style,
                "tier": tier,
                "n_points": t.n_points,
                "x": ship(xv, t.x),
                "y": ship(yv, t.y),
            }
            if t.kind == "scatter":
                entry["color"], entry["size"] = self._ship_channels(t, sel, ship_scalar)
            else:  # line/area: constant color from the trace style
                if style.get("color") is None:
                    style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
            spec_traces.append(entry)

        spec = {
            "protocol": PROTOCOL_VERSION,
            "width": self.width,
            "height": self.height,
            "title": self.title,
            "x_axis": {
                "kind": self._axis_kind("x"),
                "label": self.x_label,
                "range": list(self.x_range()),
            },
            "y_axis": {
                "kind": self._axis_kind("y"),
                "label": self.y_label,
                "range": list(self.y_range()),
            },
            "traces": spec_traces,
            "columns": shipped,
            "backend": kernels.BACKEND,
            "show_legend": self.show_legend,
        }
        return spec, b"".join(chunks)

    # -- channel & density helpers -------------------------------------------

    def _ship_channels(self, t: Trace, sel, ship_scalar) -> tuple[Any, Any]:  # noqa: ANN001
        """Ship a scatter's color and size channels. Returns (color_spec,
        size_spec); per-point channels carry a `buf` index into the blob."""
        cc = t.color_ch
        color_spec = cc.spec()
        if cc.mode == "continuous":
            unit = channels.normalize_to_unit(cc.values, cc.domain)
            color_spec["buf"] = ship_scalar(unit if sel is None else unit[sel])
        elif cc.mode == "categorical":
            codes = cc.codes if sel is None else cc.codes[sel]
            color_spec["buf"] = ship_scalar(codes)
            color_spec["palette"] = [
                DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)] for i in range(len(cc.categories))
            ]

        sc = t.size_ch
        size_spec = sc.spec()
        if sc.mode == "continuous":
            unit = channels.normalize_to_unit(sc.values, sc.domain)
            size_spec["buf"] = ship_scalar(unit if sel is None else unit[sel])
        return color_spec, size_spec

    def _density_trace_spec(self, t: Trace, xr, yr, w, h, ship_scalar) -> dict[str, Any]:  # noqa: ANN001
        """Bin a scatter into a density grid and build its spec entry (§5 Tier 2).
        The grid ships as one f32 buffer (h×w counts); the client colormaps it,
        recomputing the normalization domain per view so brightness is stable (§F6)."""
        grid = kernels.bin_2d(t.x.values, t.y.values, xr[0], xr[1], yr[0], yr[1], w, h)
        gmax = float(grid.max()) if grid.size else 0.0
        # Honor the user's colormap for the density ramp even though the per-point
        # color *data* can't survive count-aggregation (needs the §5-F5 algebra).
        cmap = t.color_ch.colormap if (t.color_ch and t.color_ch.mode == "continuous") else channels.DEFAULT_COLORMAP
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

    def density_view(
        self, trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
    ) -> tuple[dict[str, Any], list[bytes]]:
        """Re-bin a Tier-2 scatter for a new viewport (§5: O(visible points);
        the client requests this when pan/zoom leaves the shipped grid)."""
        t = self.traces[trace_id]
        if not t.use_density():
            return {"traces": []}, []
        w = max(16, min(w, 4096))
        h = max(16, min(h, 4096))
        grid = kernels.bin_2d(t.x.values, t.y.values, x0, x1, y0, y1, w, h)
        return (
            {
                "traces": [
                    {
                        "id": trace_id,
                        "density": {
                            "buf": 0,
                            "w": w,
                            "h": h,
                            "max": float(grid.max()) if grid.size else 0.0,
                            "x_range": [x0, x1],
                            "y_range": [y0, y1],
                        },
                    }
                ]
            },
            [grid.reshape(-1).astype(np.float32).tobytes()],
        )

    def pick(self, trace_id: int, index: int) -> Optional[dict[str, Any]]:
        """Exact source-row readout for a hover/pick (§17 Tier-0 hover; §16 —
        values come from the f64 canonical store, never through the f32 GPU path).
        Returns None if out of range."""
        t = self.traces[trace_id]
        if index < 0 or index >= t.n_points:
            return None
        out: dict[str, Any] = {
            "trace": trace_id,
            "index": index,
            "x": float(t.x.values[index]),
            "y": float(t.y.values[index]),
            "x_kind": t.x.kind,
            "y_kind": t.y.kind,
        }
        cc = t.color_ch
        if cc and cc.mode == "continuous" and cc.values is not None:
            out["color_value"] = float(cc.values[index])
        elif cc and cc.mode == "categorical" and cc.codes is not None:
            out["color_category"] = cc.categories[int(cc.codes[index])]
        sc = t.size_ch
        if sc and sc.mode == "continuous" and sc.values is not None:
            out["size_value"] = float(sc.values[index])
        return out

    def select_range(
        self, x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
    ) -> dict[int, np.ndarray]:
        """Indices of points inside the box, per scatter trace (§34 Filter Tier A:
        an indexed range predicate). A plain NumPy mask over canonical here; the
        zone-map-pruned version is the scale path. Returns {trace_id: indices}."""
        lo_x, hi_x = min(x0, x1), max(x0, x1)
        lo_y, hi_y = min(y0, y1), max(y0, y1)
        out: dict[int, np.ndarray] = {}
        for t in self.traces:
            if t.kind != "scatter":
                continue
            if trace_id is not None and t.id != trace_id:
                continue
            xv, yv = t.x.values, t.y.values
            mask = (xv >= lo_x) & (xv <= hi_x) & (yv >= lo_y) & (yv <= hi_y)
            out[t.id] = np.flatnonzero(mask).astype(np.uint32)
        return out

    def decimate_view(
        self, x0: float, x1: float, px_width: int
    ) -> tuple[dict[str, Any], list[bytes]]:
        """Re-decimate visible windows for a zoomed view (§28 line rule:
        recompute for the visible x-range only). The offset re-centers on the
        window midpoint — the §16 deep-zoom rule — so f32 precision follows the
        viewport instead of the whole series.
        """
        updates: list[dict[str, Any]] = []
        buffers: list[bytes] = []
        for t in self.traces:
            if t.kind != "line" or t.n_points <= DECIMATION_THRESHOLD:
                continue
            idx = kernels.m4_indices(t.x.values, t.y.values, x0, x1, max(16, px_width))
            if len(idx) == 0:
                continue
            xv, yv = t.x.values[idx], t.y.values[idx]
            x_off = (x0 + x1) / 2.0
            y_off = t.y.suggest_offset()
            x_enc = kernels.encode_f32(xv, x_off, 1.0)
            y_enc = kernels.encode_f32(yv, y_off, 1.0)
            updates.append(
                {
                    "id": t.id,
                    "x": {"buf": len(buffers), "len": len(x_enc), "offset": x_off, "scale": 1.0},
                    "y": {"buf": len(buffers) + 1, "len": len(y_enc), "offset": y_off, "scale": 1.0},
                }
            )
            buffers.append(x_enc.tobytes())
            buffers.append(y_enc.tobytes())
        return {"traces": updates}, buffers

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
        """Standalone interactive HTML: JS client + spec + base64 buffers.

        Base64 carries a stated ~33% size tax (§29 static-export row); above
        ~64 MB of payload we warn and suggest the aggregate-only embed that
        arrives with Tier 2.
        """
        import base64

        from .widget import bundled_js

        spec, blob = self.build_payload()
        if len(blob) > 64 * 2**20:
            import warnings

            warnings.warn(
                f"embedding {len(blob) / 2**20:.0f} MB of data (+33% as base64) "
                "into HTML; consider the aggregated embed once Tier 2 lands.",
                RuntimeWarning,
                stacklevel=2,
            )
        html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{self.title or "fastcharts"}</title>
<style>body{{margin:24px;font-family:system-ui,sans-serif;background:#fff}}</style>
</head>
<body>
<div id="chart"></div>
<script>{bundled_js("standalone")}</script>
<script>
  const spec = {json.dumps(spec)};
  const b64 = "{base64.b64encode(blob).decode("ascii")}";
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
</script>
</body>
</html>"""
        if path is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        return html

    def memory_report(self) -> dict[str, Any]:
        """§27: every byte class itemized; if it isn't in the report it isn't real."""
        spec, blob = self.build_payload()
        report = self.store.memory_report()
        report["transport_bytes_first_paint"] = len(blob)
        n_total = sum(t.n_points for t in self.traces) or 1
        report["transport_bytes_per_point"] = len(blob) / n_total
        report["backend"] = kernels.BACKEND
        return report
