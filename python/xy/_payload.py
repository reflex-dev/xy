"""Wire-spec compiler for `Figure`: `build_payload` plus the per-kind
emitters and the Tier-2 density/sample specs, and the `_PayloadWriter` that
owns the binary blob + column table. Split out of `_figure.py` as a mixin;
`Figure` inherits `PayloadMixin`, so every `self.*` resolves through the
concrete `Figure` via the MRO (§29: data moves as typed binary buffers)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import _native, channels, kernels, lod
from ._trace import Trace
from .columns import Column
from .config import (
    DECIMATION_THRESHOLD,
    DEFAULT_PALETTE,
    DENSITY_GRID,
    DENSITY_SAMPLE_SEED,
    DENSITY_SAMPLE_TARGET,
    PROTOCOL_VERSION,
)

if TYPE_CHECKING:
    # Type-only host base so the mixin's `self.*` resolves against the Figure
    # surface (a Protocol, so no inheritance cycle); runtime base is `object`.
    from ._hosts import FigureHost as _Host
else:
    _Host = object


class _PayloadWriter:
    """Accumulates the binary blob + column table for `build_payload`.

    The single place that knows the wire encoding, so every chart type ships
    columns the same way (§29): `ship` for offset-encoded geometry (§4), and
    `ship_scalar` for raw f32 channels/grids already in final units, and
    `ship_u8` for byte-precision categorical/density values. Adding a chart
    means calling these, not re-implementing the encoding.
    """

    def __init__(self, *, split: bool = False, borrow_heatmaps: bool = False) -> None:
        # split=True: every column ships as its own wire buffer — spec entries
        # carry `buf` (the wire-buffer index) with byte_offset 0, and
        # `buffers()` returns per-column views with no join copy. Packed mode
        # keeps the single `blob()` with global byte offsets (standalone
        # export, streaming-refresh reopen state).
        self.columns: list[dict[str, Any]] = []
        self._chunks: list[bytes | np.ndarray] = []
        self._pos = 0
        self._split = split
        self.borrow_heatmaps = borrow_heatmaps
        self.borrowed: list[np.ndarray] = []

    def ship(self, values: np.ndarray, col: "Column") -> int:
        """Offset-encoded geometry column: `(v - offset) * scale` as f32
        (§4/§16). Scale is 1.0 except for absurd-magnitude domains, where it
        normalizes so finite f64 can't overflow to ±inf in f32 (§19)."""
        encoded = lod.encode_f32_values(
            values,
            col.suggest_offset(),
            col.min,
            col.max,
            kind=col.kind,
        )
        return self._append(encoded.values, encoded.meta)

    def ship_scalar(self, values: np.ndarray) -> int:
        """Raw f32 column already in final units (no offset): channel/grid/heights."""
        enc = np.ascontiguousarray(values, dtype=np.float32)
        return self._append(enc, {})

    def ship_u8(self, values: np.ndarray) -> int:
        """Raw byte column, padded so every later f32 column stays aligned."""
        enc = np.ascontiguousarray(values, dtype=np.uint8).reshape(-1)
        index = len(self.columns)
        if self._split:
            # One buffer per column: fold the alignment padding into the u8
            # buffer itself (spec `len` still counts only real values), so the
            # split layout stays a byte-identical repack of the packed blob.
            padding = (-len(enc)) % 4
            padded = np.concatenate([enc, np.zeros(padding, np.uint8)]) if padding else enc
            self.columns.append(
                {"buf": len(self._chunks), "byte_offset": 0, "len": int(len(enc)), "dtype": "u8"}
            )
            self._chunks.append(padded)
            self._pos += padded.nbytes
            return index
        self.columns.append({"byte_offset": self._pos, "len": int(len(enc)), "dtype": "u8"})
        self._chunks.append(enc)
        self._pos += enc.nbytes
        padding = (-self._pos) % 4
        if padding:
            self._chunks.append(bytes(padding))
            self._pos += padding
        return index

    def borrow_f64(self, values: np.ndarray) -> int:
        """Register canonical f64 storage as a synchronous raster-only span.

        Span 0 is the owned payload blob; borrowed arrays start at 1. Nothing
        about the public browser payload uses this representation.
        """
        arr = np.ascontiguousarray(values, dtype="<f8").reshape(-1)
        span = len(self.borrowed) + 1
        self.borrowed.append(arr)
        index = len(self.columns)
        self.columns.append({"span": span, "byte_offset": 0, "len": int(len(arr)), "dtype": "f64"})
        return index

    def ship_values(self, values: np.ndarray, *, kind: str = "float") -> int:
        """Offset-encoded temporary geometry not backed by a canonical Column."""
        vals = np.ascontiguousarray(values, dtype=np.float64)
        bounds = kernels.min_max(vals)
        offset = (bounds[0] + bounds[1]) / 2.0 if bounds is not None else 0.0
        lo, hi = bounds if bounds is not None else (0.0, 0.0)
        encoded = lod.encode_f32_values(vals, offset, lo, hi, kind=kind)
        return self._append(encoded.values, encoded.meta)

    def _append(self, enc: np.ndarray, meta: dict[str, Any]) -> int:
        # Retain the encoded array until blob assembly so each column is copied
        # once into the final bytes object, rather than once in `tobytes()` and
        # again by `join` — and split mode ships these views with no copy at all.
        enc = np.ascontiguousarray(enc)
        idx = len(self.columns)
        if self._split:
            # `buf` indexes the wire buffer list (== `_chunks`), which can
            # drift from the column table (`borrow_f64` columns own no chunk).
            self.columns.append(
                {"buf": len(self._chunks), "byte_offset": 0, "len": int(len(enc)), **meta}
            )
        else:
            self.columns.append({"byte_offset": self._pos, "len": int(len(enc)), **meta})
        self._chunks.append(enc)
        self._pos += enc.nbytes
        return idx

    def blob(self) -> bytes:
        return b"".join(
            chunk if isinstance(chunk, bytes) else chunk.data.cast("B") for chunk in self._chunks
        )

    def buffers(self) -> list[memoryview]:
        """Per-column wire buffers (split mode): zero-copy views over the
        encoded chunks, ready to ship as separate binary comm frames."""
        return [
            memoryview(c).cast("B") if isinstance(c, bytes) else c.data.cast("B")
            for c in self._chunks
        ]


class PayloadMixin(_Host):
    def build_payload(self, px_width: Optional[int] = None) -> tuple[dict[str, Any], bytes]:
        """Encode every trace for first paint: (spec, binary buffer blob).

        Per-kind logic lives in `_emit_<kind>` methods dispatched here — adding a
        chart type means adding one emitter, not editing this loop. Direct traces
        ship whole columns offset-encoded (§4); long lines ship M4-decimated
        (§5 Tier 1); dense scatter ships a density grid (§5 Tier 2). Every
        reduction is recorded in the spec — no silent quality changes (§28).
        """
        pw = _PayloadWriter()
        spec = self._payload_spec(pw, self._resolve_px_width(px_width))
        return spec, pw.blob()

    def build_payload_split(
        self, px_width: Optional[int] = None
    ) -> tuple[dict[str, Any], list[memoryview]]:
        """`build_payload` with per-column wire buffers instead of one blob.

        Same emitters, same encoded bytes — but the columns ship as a list of
        borrowed buffer views, skipping the join copy (the single largest
        allocation of a direct-tier build). The spec says so explicitly:
        `buffer_layout: "split"`, and each column entry carries `buf`, its
        index into the buffer list (§29 — the comm protocol already carries
        multi-buffer messages on the update path; this extends it to first
        paint).
        """
        pw = _PayloadWriter(split=True)
        spec = self._payload_spec(pw, self._resolve_px_width(px_width))
        spec["buffer_layout"] = "split"
        return spec, pw.buffers()

    def _build_raster_payload(
        self, px_width: Optional[int] = None
    ) -> tuple[dict[str, Any], bytes, tuple[np.ndarray, ...]]:
        """Private static-export payload with borrowed canonical heatmap spans."""
        pw = _PayloadWriter(borrow_heatmaps=True)
        spec = self._payload_spec(pw, self._resolve_px_width(px_width))
        return spec, pw.blob(), tuple(pw.borrowed)

    def _resolve_px_width(self, px_width: Optional[int]) -> int:
        if px_width is None:
            # A concrete chart should pay for the pixels it can display, not
            # the historical 2048px fluid-layout fallback. Responsive charts
            # keep that headroom until the browser reports a real width; live
            # resize/view requests then refine the decimation for the new size.
            width = self.width
            px_width = (
                int(width)
                if isinstance(width, (int, float)) and not isinstance(width, bool)
                else 2048
            )
        px_width, _ = lod.screen_shape(px_width, 16)
        return px_width

    def _payload_spec(self, pw: "_PayloadWriter", px_width: int) -> dict[str, Any]:
        # `_range` is an O(traces x chunks) autorange scan and is invariant
        # while this build runs (emitters only touch shipped_sel/drill state),
        # so each axis pays for it once even when many traces share an axis.
        ranges: dict[str, tuple[float, float]] = {}

        def axis_range(axis_id: str) -> tuple[float, float]:
            r = ranges.get(axis_id)
            if r is None:
                ranges[axis_id] = r = self._range(axis_id)
            return r

        spec_traces = []
        for t in self.traces:
            xr = axis_range(t.x_axis)
            yr = axis_range(t.y_axis)
            spec_traces.append(
                self._emit_trace(t, pw, (min(xr), max(xr)), (min(yr), max(yr)), px_width)
            )
        axis_specs = {
            axis_id: self._axis_spec(axis_id, axis_range(axis_id)) for axis_id in self.axis_options
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
        if self.legend_options:
            spec["legend"] = self.legend_options
        extra_legends = getattr(self, "extra_legends", None)
        if extra_legends:
            spec["extra_legends"] = extra_legends
        if self.frame_sides is not None:
            spec["frame_sides"] = list(self.frame_sides)
        if self.colorbar_options:
            spec["colorbar"] = self.colorbar_options
        if self.show_modebar is False:
            spec["show_modebar"] = False
        export_options = getattr(self, "export_options", None)
        if export_options:
            spec["export"] = export_options
        if self.show_tooltip is False:
            spec["show_tooltip"] = False
        if self.padding is not None:
            spec["padding"] = list(self.padding)
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
        return spec

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
    def _finite_sel(t: Trace, xv: np.ndarray, yv: np.ndarray) -> np.ndarray | None:
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

    @staticmethod
    def _default_styled(t: Trace) -> dict[str, Any]:
        """Trace style dict with the per-trace palette default when no color
        was given — the one place this rule lives (was copy-pasted per kind)."""
        style = dict(t.style)
        if style.get("color") is None:
            style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
        return style

    @staticmethod
    def _m4_decimate(
        t: Trace, xr: tuple, px_width: int, *arrays: np.ndarray
    ) -> tuple[str, tuple[np.ndarray, ...]]:
        """M4-decimate the parallel `arrays` (x first) when the trace is over
        the threshold; M4 already excludes non-finite within the window (§19).
        Returns `(tier, arrays)` — shared by the line and area emitters."""
        if t.n_points <= DECIMATION_THRESHOLD:
            return "direct", arrays
        if len(arrays) == 2:
            selected = _native.m4_points(
                arrays[0], arrays[1], xr[0], xr[1] + np.finfo(np.float64).eps, px_width
            )
            return "decimated", selected
        idx = kernels.m4_indices(
            arrays[0], arrays[1], xr[0], xr[1] + np.finfo(np.float64).eps, px_width
        )
        if len(idx):
            return "decimated", tuple(a[idx] for a in arrays)
        return "decimated", tuple(a[:0] for a in arrays)

    def _emit_line(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        tier, (xv, yv) = self._m4_decimate(t, xr, px_width, t.x.values, t.y.values)
        if tier == "direct":
            sel = self._finite_sel(t, xv, yv)
            if sel is not None:
                xv, yv = xv[sel], yv[sel]
        if len(xv):
            finite = self._log_visible_mask(t, xv, yv)
            if not bool(np.all(finite)):
                xv, yv = xv[finite], yv[finite]
        return self._base_entry(t, pw, xv, yv, tier, self._default_styled(t))

    def _emit_area(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        if t.base is None:
            raise ValueError("area trace missing baseline column")
        tier, (xv, yv, bv) = self._m4_decimate(
            t, xr, px_width, t.x.values, t.y.values, t.base.values
        )
        sel = np.flatnonzero(self._log_visible_mask(t, xv, yv, bv))
        if len(sel) != len(xv):
            xv, yv, bv = xv[sel], yv[sel], bv[sel]
        entry = self._base_entry(t, pw, xv, yv, tier, self._default_styled(t))
        entry["base"] = pw.ship(bv, t.base)
        return entry

    def _emit_error_band(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_area(t, pw, xr, yr, px_width)

    def _emit_scatter(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        if t.use_density():
            t.shipped_sel = None  # no per-point marks, no pick mapping
            t.drill_mode = False  # full view: density until a zoom drills in
            return self._density_trace_spec(t, xr, yr, *DENSITY_GRID, pw)
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
        entry["color"], entry["size"] = self._ship_channels(t, sel, pw.ship_scalar, pw.ship_u8)
        t.shipped_sel = sel  # pick/selection translation (§17)
        return entry

    def _emit_hexbin(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        del xr, yr, px_width
        xv, yv = t.x.values, t.y.values
        sel = self._finite_sel(t, xv, yv)
        if sel is not None:
            xv, yv = xv[sel], yv[sel]
        # Cells ship as centers plus one scalar color value. Every hexagon
        # shares the same geometry (style hex_dx/hex_dy), so each renderer
        # expands the six-triangle fan locally and the wire cost stays
        # O(cells), not O(cells x vertices x channels) (§29).
        entry = {
            "id": t.id,
            "kind": t.kind,
            "name": t.name,
            "style": self._default_styled(t),
            "tier": "direct",
            "n_points": t.n_points,
            "n_marks": int(len(xv)),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "x": pw.ship_values(xv),
            "y": pw.ship_values(yv),
        }
        entry["color"], _size = self._ship_channels(t, sel, pw.ship_scalar, pw.ship_u8)
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
        if t.rgba_grid is not None:
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
                    "rgba_bufs": [pw.ship_scalar(column.values) for column in t.rgba_grid],
                    "w": int(cols),
                    "h": int(rows),
                    "x_range": list(t.style["x_range"]),
                    "y_range": list(t.style["y_range"]),
                },
            }
        domain = tuple(t.style["domain"])
        if pw.borrow_heatmaps:
            buffer_index = pw.borrow_f64(t.grid.values)
            encoding = "canonical-f64"
        else:
            norm = kernels.normalize_f32(t.grid.values, domain, nonfinite="nan")
            buffer_index = pw.ship_scalar(norm)
            encoding = None
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
                "buf": buffer_index,
                "w": int(cols),
                "h": int(rows),
                "x_range": list(t.style["x_range"]),
                "y_range": list(t.style["y_range"]),
                "colormap": cmap,
                "domain": list(domain),
                **({"enc": encoding} if encoding is not None else {}),
            },
            "color": {"mode": "continuous", "colormap": cmap, "domain": list(domain)},
        }

    def _emit_box(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_rect(t, pw, xr, yr, px_width)

    def _emit_violin(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_rect(t, pw, xr, yr, px_width)

    def _emit_segments(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        del xr, yr
        if t.x0 is None or t.x1 is None or t.y0 is None or t.y1 is None:
            raise ValueError(f"{t.kind} trace missing segment columns")
        x0v, x1v, y0v, y1v = t.x0.values, t.x1.values, t.y0.values, t.y1.values
        tier = "direct"
        if t.kind == "errorbar" and t.count:
            # Segments ship grouped by role, count per group: 3 groups with
            # caps (main + two cap blocks), 1 without. Decimate per point
            # across every group so caps stay attached to their bars.
            seg_per, remainder = divmod(len(x0v), t.count)
            max_groups = max(1024, int(px_width) * 4)
            if remainder == 0 and seg_per >= 1 and t.count > max_groups:
                chosen = np.linspace(0, t.count - 1, max_groups, dtype=np.int64)
                indices = np.concatenate([chosen + k * t.count for k in range(seg_per)])
                x0v, x1v, y0v, y1v = x0v[indices], x1v[indices], y0v[indices], y1v[indices]
                tier = "decimated"
        elif t.kind == "stem" and len(x0v) > max(1024, int(px_width) * 4):
            chosen = np.linspace(0, len(x0v) - 1, max(1024, int(px_width) * 4), dtype=np.int64)
            x0v, x1v, y0v, y1v = x0v[chosen], x1v[chosen], y0v[chosen], y1v[chosen]
            tier = "decimated"
        sel_arg = self._rect_finite_sel(t, x0v, x1v, y0v, y1v)
        if sel_arg is not None:
            x0v, x1v, y0v, y1v = x0v[sel_arg], x1v[sel_arg], y0v[sel_arg], y1v[sel_arg]
        entry = {
            "id": t.id,
            "kind": t.kind,
            "name": t.name,
            "style": self._default_styled(t),
            "tier": tier,
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
            entry["color"], _size = self._ship_channels(t, sel_arg, pw.ship_scalar, pw.ship_u8)
        return entry

    def _emit_triangle_mesh(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        del xr, yr, px_width
        if t.x0 is None or t.x1 is None or t.y0 is None or t.y1 is None:
            raise ValueError("triangle_mesh trace missing geometry columns")
        x0v, x1v, x2v = t.x0.values, t.x1.values, t.x.values
        y0v, y1v, y2v = t.y0.values, t.y1.values, t.y.values
        geometry = (t.x0, t.x1, t.x, t.y0, t.y1, t.y)
        values = (x0v, x1v, x2v, y0v, y1v, y2v)
        candidates = [
            array for column, array in zip(geometry, values, strict=True) if column.zone.null_count
        ]
        if t.color_ch is not None and t.color_ch.mode == "continuous":
            if t.color_ch.values is None:
                raise ValueError("triangle_mesh continuous color channel missing values")
            candidates.append(t.color_ch.values)
        sel_arg = kernels.valid_indices_f64(tuple(candidates)) if candidates else None
        if sel_arg is not None:
            x0v, x1v, x2v = x0v[sel_arg], x1v[sel_arg], x2v[sel_arg]
            y0v, y1v, y2v = y0v[sel_arg], y1v[sel_arg], y2v[sel_arg]
        entry = {
            "id": t.id,
            "kind": t.kind,
            "name": t.name,
            "style": self._default_styled(t),
            "tier": "direct",
            "n_points": t.n_points,
            "n_marks": int(len(x0v)),
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "x0": pw.ship(x0v, t.x0),
            "x1": pw.ship(x1v, t.x1),
            "x2": pw.ship(x2v, t.x),
            "y0": pw.ship(y0v, t.y0),
            "y1": pw.ship(y1v, t.y1),
            "y2": pw.ship(y2v, t.y),
        }
        if t.color_ch is not None:
            entry["color"], _size = self._ship_channels(t, sel_arg, pw.ship_scalar, pw.ship_u8)
        return entry

    def _emit_errorbar(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_segments(t, pw, xr, yr, px_width)

    def _emit_stem(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_segments(t, pw, xr, yr, px_width)

    def _emit_box_whisker(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_segments(t, pw, xr, yr, px_width)

    def _emit_box_median(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_segments(t, pw, xr, yr, px_width)

    def _emit_contour(
        self, t: Trace, pw: "_PayloadWriter", xr: tuple, yr: tuple, px_width: int
    ) -> dict[str, Any]:
        return self._emit_segments(t, pw, xr, yr, px_width)

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
        style = self._default_styled(t)
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
            entry["color"], _size = self._ship_channels(t, sel_arg, pw.ship_scalar, pw.ship_u8)
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

        style = self._default_styled(t)
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
            entry["color"], _size = self._ship_channels(t, sel_arg, pw.ship_scalar, pw.ship_u8)
        return entry

    def _ship_channels(self, t: Trace, sel, ship_scalar, ship_u8) -> tuple[Any, Any]:  # noqa: ANN001
        """Ship a trace's color/size channels (delegates to channels.py — the
        same wire shape serves the build path and drill-in view updates)."""
        return channels.ship_channels(t, sel, ship_scalar, ship_u8, DEFAULT_PALETTE)

    def _density_sample_spec(
        self,
        t: Trace,
        sel: np.ndarray,
        visible: int,
        xr: tuple[float, float],
        yr: tuple[float, float],
        pw: "_PayloadWriter",
        *,
        sample_sel: Optional[np.ndarray] = None,
    ) -> Optional[dict[str, Any]]:
        if visible <= 0:
            return None
        if sample_sel is None:
            categories = None
            if t.color_ch and t.color_ch.mode == "categorical" and t.color_ch.codes is not None:
                categories = t.color_ch.codes[sel]
            sample_sel = lod.sample_rows_for_target(
                sel,
                DENSITY_SAMPLE_TARGET,
                categories=categories,
                seed=DENSITY_SAMPLE_SEED,
            )
        if len(sample_sel) == 0:
            return None
        color_spec, size_spec = self._ship_channels(t, sample_sel, pw.ship_scalar, pw.ship_u8)
        style = dict(t.style)
        try:
            style["opacity"] = min(float(style.get("opacity", 0.8)), 0.55)
        except (TypeError, ValueError):
            style["opacity"] = 0.55
        x_col = pw.ship_values(t.x.values[sample_sel], kind=t.x.kind)
        y_col = pw.ship_values(t.y.values[sample_sel], kind=t.y.kind)
        return {
            "mode": "sampled",
            "n": int(len(sample_sel)),
            "visible": int(visible),
            "target": DENSITY_SAMPLE_TARGET,
            "level": 0,
            "seed": DENSITY_SAMPLE_SEED,
            "x": {"col": x_col, **pw.columns[x_col]},
            "y": {"col": y_col, **pw.columns[y_col]},
            "x_range": list(xr),
            "y_range": list(yr),
            "color": color_spec,
            "size": size_spec,
            "style": style,
        }

    def _density_trace_spec(self, t: Trace, xr, yr, w, h, pw: "_PayloadWriter") -> dict[str, Any]:  # noqa: ANN001
        """Bin a scatter into a density grid and build its spec entry (§5 Tier 2).
        The grid ships in the client's one-byte log texture precision; exact
        visible counts remain metadata, and the client recomputes the
        normalization domain per view so brightness is stable (§F6)."""
        # A clean full-domain trace has identity visible rows. Avoid allocating
        # and then hashing an N-entry u32 index vector merely to retain the
        # small sampled overlay; the implicit-range samplers apply the same
        # SplitMix predicates with scratch proportional to the returned rows.
        # Compact categorical codes can be scanned directly in Rust; wider
        # codes retain the general visible-index path.
        categorical = bool(t.color_ch and t.color_ch.mode == "categorical")
        compact_categorical = bool(
            categorical
            and t.color_ch is not None
            and t.color_ch.codes is not None
            and t.color_ch.codes.dtype == np.uint8
        )
        full_identity = (
            (not categorical or compact_categorical)
            and not (t.x.zone.null_count or t.y.zone.null_count)
            and t.x.min >= xr[0]
            and t.x.max <= xr[1]
            and t.y.min >= yr[0]
            and t.y.max <= yr[1]
        )
        sample_sel = None
        if full_identity:
            visible = int(t.n_points)
            sel = np.empty(0, dtype=np.uint32)
            if compact_categorical:
                assert t.color_ch is not None and t.color_ch.codes is not None
                if t.color_ch.counts is not None:
                    grid, sample_sel = lod.bin_2d_stratified_sample_row_range_for_target(
                        t.x.values,
                        t.y.values,
                        t.color_ch.codes,
                        len(t.color_ch.categories or ()),
                        xr[0],
                        xr[1],
                        yr[0],
                        yr[1],
                        w,
                        h,
                        DENSITY_SAMPLE_TARGET,
                        counts=t.color_ch.counts,
                        seed=DENSITY_SAMPLE_SEED,
                    )
                else:
                    # Defensive compatibility for traces assembled outside the
                    # normal resolver; production factorization always emits
                    # counts and takes the fused path.
                    grid = kernels.bin_2d(t.x.values, t.y.values, xr[0], xr[1], yr[0], yr[1], w, h)
                    sample_sel = lod.stratified_sample_row_range_for_target(
                        t.color_ch.codes,
                        len(t.color_ch.categories or ()),
                        DENSITY_SAMPLE_TARGET,
                        seed=DENSITY_SAMPLE_SEED,
                    )
            else:
                grid, sample_sel = lod.bin_2d_sample_row_range_for_target(
                    t.x.values,
                    t.y.values,
                    xr[0],
                    xr[1],
                    yr[0],
                    yr[1],
                    w,
                    h,
                    DENSITY_SAMPLE_TARGET,
                    seed=DENSITY_SAMPLE_SEED,
                )
        else:
            # Fused single pass: grid (bin_2d semantics) + visible rows
            # (range_indices semantics) without re-reading full columns twice.
            grid, sel = kernels.bin_2d_indices(
                t.x.values, t.y.values, xr[0], xr[1], yr[0], yr[1], w, h
            )
            visible = int(len(sel))
        encoded_grid, gmax = kernels.density_log_u8(grid)
        # Honor the user's colormap for the density ramp even though the per-point
        # color *data* can't survive count-aggregation (needs the §5-F5 algebra).
        # Constant channels carry it too — colormap= without color data means
        # exactly this ramp. Categorical has no ramp, so it keeps the default.
        cmap = (
            t.color_ch.colormap
            if (t.color_ch and t.color_ch.mode in ("constant", "continuous"))
            else channels.DEFAULT_COLORMAP
        )
        color_dropped = bool(t.color_ch and t.color_ch.mode != "constant")
        size_dropped = bool(t.size_ch and t.size_ch.mode != "constant")
        dropped = color_dropped or size_dropped
        density = {
            "buf": pw.ship_u8(encoded_grid),
            "w": w,
            "h": h,
            "max": gmax,
            "enc": "log-u8",
            "colormap": cmap,
            "x_range": list(xr),
            "y_range": list(yr),
            "channels_dropped": dropped,  # never silent (§28)
        }
        if t.color_ch and t.color_ch.mode == "constant" and t.color_ch.constant is not None:
            density["color"] = t.color_ch.constant
        sample = self._density_sample_spec(t, sel, visible, xr, yr, pw, sample_sel=sample_sel)
        if sample is not None:
            density["sample"] = sample
        return {
            "id": t.id,
            "kind": "scatter",
            "name": t.name,
            "style": dict(t.style),
            "tier": "density",
            "n_points": t.n_points,
            "n_marks": int(w * h),
            "visible": visible,
            "x_axis": t.x_axis,
            "y_axis": t.y_axis,
            "density": density,
        }
