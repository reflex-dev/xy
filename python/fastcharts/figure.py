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

from . import kernels
from .column import Column, ColumnStore

PROTOCOL_VERSION = 1

# Line traces longer than this ship M4-decimated (Tier 1, §5); the canonical
# column stays kernel-side for re-decimation on zoom (§28: recompute for the
# visible x-range only).
DECIMATION_THRESHOLD = 10_000

# Direct-tier soft ceiling (§5 F3: fill-rate + allocation cliffs are real even
# when vertex count "fits"). Phase 0 warns; Tier 2 aggregation is the real fix.
DIRECT_SOFT_CEILING = 2_000_000

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

    @property
    def n_points(self) -> int:
        return len(self.x)


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
        color: Optional[str] = None,
        size: float = 4.0,
        opacity: float = 0.8,
    ) -> "Figure":
        xc = self.store.ingest(x)
        yc = self.store.ingest(y)
        if len(xc) > DIRECT_SOFT_CEILING:
            import warnings

            warnings.warn(
                f"scatter trace has {len(xc):,} points — above the direct-tier "
                f"soft ceiling ({DIRECT_SOFT_CEILING:,}). Rendering proceeds but "
                "may be fill-rate bound; Tier-2 density aggregation (Phase 2) is "
                "the designed path for this volume.",
                RuntimeWarning,
                stacklevel=2,
            )
        self.traces.append(
            Trace(
                id=len(self.traces),
                kind="scatter",
                x=xc,
                y=yc,
                name=name,
                style={"color": color, "size": size, "opacity": opacity},
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

        spec_traces: list[dict[str, Any]] = []
        for t in self.traces:
            style = dict(t.style)
            if style.get("color") is None:
                style["color"] = DEFAULT_PALETTE[t.id % len(DEFAULT_PALETTE)]
            tier = "direct"
            xv, yv = t.x.values, t.y.values
            if t.kind == "line" and t.n_points > DECIMATION_THRESHOLD:
                x0, x1 = self.x_range()
                idx = kernels.m4_indices(xv, yv, x0, x1 + np.finfo(np.float64).eps, px_width)
                if len(idx):
                    xv, yv = xv[idx], yv[idx]
                    tier = "decimated"
            elif t.x.zone.null_count or t.y.zone.null_count:
                # NaN never reaches a vertex buffer — it silently corrupts
                # primitives, driver-dependently (§19). Phase 0 drops invalid
                # rows on the shipped copy (canonical keeps them); real gap
                # semantics (segment index list) arrive with validity bitmaps.
                valid = ~(np.isnan(xv) | np.isnan(yv))
                xv, yv = xv[valid], yv[valid]
            spec_traces.append(
                {
                    "id": t.id,
                    "kind": t.kind,
                    "name": t.name,
                    "style": style,
                    "tier": tier,
                    "n_points": t.n_points,
                    "x": ship(xv, t.x),
                    "y": ship(yv, t.y),
                }
            )

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
        }
        return spec, b"".join(chunks)

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
