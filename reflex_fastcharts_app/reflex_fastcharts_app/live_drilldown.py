from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Union

import numpy as np
from starlette.requests import Request
from starlette.responses import JSONResponse

from fastcharts import Figure
from fastcharts.config import DRILL_EXIT_FACTOR, SCATTER_DENSITY_THRESHOLD
from fastcharts.lod import grid_shape
from fastcharts.widget import bundled_js

LIVE_SCATTER_POINTS = 100_000_000
LIVE_DRILLDOWN_ROUTE = "/api/fastcharts/drilldown"
DENSITY_OVERVIEW_BINS = 6144
DENSITY_OVERVIEW_CHUNK = 1_000_000
OVERVIEW_EXACT_FACTOR = 4.0
_FIGURE_LOCK = threading.Lock()
_DENSITY_SEQ_LOCK = threading.Lock()
_LATEST_DENSITY_SEQ: dict[str, int] = {}


def _point_label(n: int) -> str:
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n % 1_000 == 0:
        return f"{n // 1_000}k"
    return f"{n:,}"


def colored_scatter_data(
    n: int = LIVE_SCATTER_POINTS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(11)
    x = np.empty(n, dtype=np.float64)
    y = np.empty(n, dtype=np.float64)
    color = np.empty(n, dtype=np.float64)
    size = np.empty(n, dtype=np.float64)
    chunk = 1_000_000
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        xs = rng.normal(0, 1.0, end - start)
        ys = rng.normal(0, 0.55, end - start)
        ys += xs * 0.55
        ss = rng.normal(6, 2.5, end - start)
        np.abs(ss, out=ss)
        np.clip(ss, 2, 16, out=ss)
        x[start:end] = xs
        y[start:end] = ys
        np.hypot(xs, ys, out=color[start:end])
        size[start:end] = ss
    return x, y, color, size


def colored_scatter_figure(
    n: int = LIVE_SCATTER_POINTS,
    *,
    title: str | None = None,
    width: Union[str, int] = "100%",
    height: int = 430,
) -> Figure:
    title = title or f"{_point_label(n)} live drilldown scatter"
    x, y, color, size = colored_scatter_data(n)
    return Figure(
        title=title,
        x_label="feature A",
        y_label="feature B",
        width=width,
        height=height,
    ).scatter(x, y, color=color, size=size, colormap="viridis", opacity=0.72, density=True)


@lru_cache(maxsize=1)
def live_figure() -> Figure:
    return live_store().figure


@dataclass(frozen=True)
class DensityOverview:
    integral: np.ndarray
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    width: int
    height: int

    @classmethod
    def build(cls, fig: Figure, trace_id: int = 0) -> "DensityOverview":
        t = fig.traces[trace_id]
        x0, x1 = fig.x_range()
        y0, y1 = fig.y_range()
        w = h = DENSITY_OVERVIEW_BINS
        grid = np.zeros((h, w), dtype=np.uint32)
        flat_grid = grid.reshape(-1)
        x_scale = w / (x1 - x0)
        y_scale = h / (y1 - y0)
        xv = t.x.values
        yv = t.y.values

        for start in range(0, t.n_points, DENSITY_OVERVIEW_CHUNK):
            end = min(start + DENSITY_OVERVIEW_CHUNK, t.n_points)
            xs = xv[start:end]
            ys = yv[start:end]
            valid = np.isfinite(xs) & np.isfinite(ys)
            valid &= (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
            if not np.any(valid):
                continue
            ix = ((xs[valid] - x0) * x_scale).astype(np.int64)
            iy = ((ys[valid] - y0) * y_scale).astype(np.int64)
            np.clip(ix, 0, w - 1, out=ix)
            np.clip(iy, 0, h - 1, out=iy)
            counts = np.bincount(iy * w + ix)
            flat_grid[: len(counts)] += counts.astype(np.uint32, copy=False)

        summed = np.cumsum(grid, axis=0, dtype=np.uint32)
        summed = np.cumsum(summed, axis=1, dtype=np.uint32)
        integral = np.zeros((h + 1, w + 1), dtype=np.uint32)
        integral[1:, 1:] = summed
        return cls(integral=integral, x_range=(x0, x1), y_range=(y0, y1), width=w, height=h)

    def _edges(
        self, lo: float, hi: float, domain: tuple[float, float], cells: int, bins: int
    ) -> np.ndarray:
        d0, d1 = domain
        span = d1 - d0
        edges = (np.linspace(lo, hi, cells + 1) - d0) * (bins / span)
        return np.clip(np.floor(edges).astype(np.int64), 0, bins)

    def _view_bounds(self, x0: float, x1: float, y0: float, y1: float) -> tuple[int, int, int, int]:
        bx0, bx1 = self._edges(x0, x1, self.x_range, 1, self.width)
        by0, by1 = self._edges(y0, y1, self.y_range, 1, self.height)
        return int(bx0), int(bx1), int(by0), int(by1)

    def count(self, x0: float, x1: float, y0: float, y1: float) -> int:
        bx0, bx1, by0, by1 = self._view_bounds(x0, x1, y0, y1)
        if bx1 <= bx0 or by1 <= by0:
            return 0
        ii = self.integral
        return int(ii[by1, bx1]) - int(ii[by0, bx1]) - int(ii[by1, bx0]) + int(ii[by0, bx0])

    def density(
        self,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        w: int,
        h: int,
        visible: int,
    ) -> np.ndarray | None:
        bx0, bx1, by0, by1 = self._view_bounds(x0, x1, y0, y1)
        source_w = bx1 - bx0
        source_h = by1 - by0
        if source_w < 16 or source_h < 16:
            return None
        w, h = grid_shape(w, h, visible)
        w = max(16, min(w, source_w))
        h = max(16, min(h, source_h))
        x_edges = self._edges(x0, x1, self.x_range, w, self.width)
        y_edges = self._edges(y0, y1, self.y_range, h, self.height)
        ii = self.integral
        x_lo = x_edges[:-1]
        x_hi = x_edges[1:]
        y_lo = y_edges[:-1]
        y_hi = y_edges[1:]
        grid = (
            ii[y_hi[:, None], x_hi[None, :]].astype(np.int64)
            - ii[y_lo[:, None], x_hi[None, :]].astype(np.int64)
            - ii[y_hi[:, None], x_lo[None, :]].astype(np.int64)
            + ii[y_lo[:, None], x_lo[None, :]].astype(np.int64)
        )
        return grid.astype(np.float32, copy=False)


@dataclass(frozen=True)
class LiveStore:
    figure: Figure
    overview: DensityOverview


@lru_cache(maxsize=1)
def live_store() -> LiveStore:
    fig = colored_scatter_figure()
    return LiveStore(figure=fig, overview=DensityOverview.build(fig))


def _b64(buf: bytes) -> str:
    return base64.b64encode(buf).decode("ascii")


def _seq_value(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _density_client_id(content: dict[str, Any]) -> str:
    return str(content.get("client_id") or "default")


def _mark_latest_density(content: dict[str, Any]) -> tuple[str, int | None]:
    client_id = _density_client_id(content)
    seq = _seq_value(content.get("seq"))
    if seq is None:
        return client_id, None
    with _DENSITY_SEQ_LOCK:
        latest = _LATEST_DENSITY_SEQ.get(client_id, -1)
        if seq > latest:
            _LATEST_DENSITY_SEQ[client_id] = seq
    return client_id, seq


def _density_is_stale(client_id: str, seq: int | None) -> bool:
    if seq is None:
        return False
    with _DENSITY_SEQ_LOCK:
        return seq < _LATEST_DENSITY_SEQ.get(client_id, -1)


def _response(message: dict[str, Any], buffers: list[bytes] | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "message": message,
            "buffers": [_b64(buffer) for buffer in (buffers or [])],
        }
    )


def _live_density_view(
    store: LiveStore, trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
) -> tuple[dict[str, Any], list[bytes]]:
    fig = store.figure
    if trace_id != 0:
        return fig.density_view(trace_id, x0, x1, y0, y1, w, h)
    t = fig.traces[trace_id]
    if not t.use_density():
        return {"traces": []}, []

    lo_x, hi_x = min(x0, x1), max(x0, x1)
    lo_y, hi_y = min(y0, y1), max(y0, y1)
    budget = SCATTER_DENSITY_THRESHOLD * (DRILL_EXIT_FACTOR if t.drill_mode else 1.0)
    visible = store.overview.count(lo_x, hi_x, lo_y, hi_y)
    if visible <= budget * OVERVIEW_EXACT_FACTOR:
        return fig.density_view(trace_id, lo_x, hi_x, lo_y, hi_y, w, h)

    grid = store.overview.density(lo_x, hi_x, lo_y, hi_y, w, h, visible)
    if grid is None:
        return fig.density_view(trace_id, lo_x, hi_x, lo_y, hi_y, w, h)

    if t.drill_mode:
        t.drill_seq += 1
    t.drill_mode = False
    t.shipped_sel = None
    return (
        {
            "traces": [
                {
                    "id": trace_id,
                    "mode": "density",
                    "visible": visible,
                    "density": {
                        "buf": 0,
                        "w": int(grid.shape[1]),
                        "h": int(grid.shape[0]),
                        "max": float(grid.max()) if grid.size else 0.0,
                        "x_range": [lo_x, hi_x],
                        "y_range": [lo_y, hi_y],
                    },
                }
            ]
        },
        [grid.reshape(-1).astype(np.float32, copy=False).tobytes()],
    )


async def drilldown_endpoint(request: Request) -> JSONResponse:
    try:
        content = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    kind = content.get("type")
    density_client_id: str | None = None
    density_seq: int | None = None
    if kind == "density_view":
        density_client_id, density_seq = _mark_latest_density(content)

    with _FIGURE_LOCK:
        store = live_store()
        fig = store.figure
        if kind == "density_view":
            try:
                if _density_is_stale(density_client_id or "default", density_seq):
                    return _response(
                        {
                            "type": "density_update",
                            "seq": content.get("seq"),
                            "stale": True,
                            "traces": [],
                        }
                    )
                update, buffers = _live_density_view(
                    store,
                    int(content["trace"]),
                    float(content["x0"]),
                    float(content["x1"]),
                    float(content["y0"]),
                    float(content["y1"]),
                    int(content.get("w", 512)),
                    int(content.get("h", 384)),
                )
            except (KeyError, ValueError, IndexError):
                return JSONResponse({"error": "bad density_view request"}, status_code=400)
            return _response(
                {"type": "density_update", "seq": content.get("seq"), **update}, buffers
            )

        if kind == "pick":
            dseq = content.get("drill_seq")
            row = fig.pick(
                int(content.get("trace", -1)),
                int(content.get("index", -1)),
                None if dseq is None else int(dseq),
            )
            return _response({"type": "pick_result", "seq": content.get("seq"), "row": row})

        if kind in {"select", "select_clear"}:
            return _response({"type": "selection", "traces": [], "total": 0})

    return JSONResponse({"error": f"unsupported message type {kind!r}"}, status_code=400)


def live_drilldown_html() -> str:
    fig = colored_scatter_figure()
    spec, blob = fig.build_payload()
    spec_js = json.dumps(spec).replace("</", "<\\/")
    b64 = _b64(blob)
    route = LIVE_DRILLDOWN_ROUTE
    js = bundled_js("standalone")
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{_point_label(LIVE_SCATTER_POINTS)} live drilldown scatter</title>
<style>
html,body{{margin:0;width:100%;height:100%;font-family:system-ui,sans-serif;background:#fff;}}
#chart{{width:100%;height:430px;}}
#status{{position:absolute;right:12px;top:10px;z-index:10;padding:4px 8px;border:1px solid rgba(16,24,40,.14);border-radius:4px;background:rgba(255,255,255,.86);color:#344054;font:12px system-ui,sans-serif;pointer-events:none;}}
</style>
</head>
<body>
<div id="chart"></div>
<div id="status">density</div>
<script>{js}</script>
<script>
const spec = {spec_js};
const initialBytes = Uint8Array.from(atob("{b64}"), c => c.charCodeAt(0));
const callbacks = [];
const statusEl = document.getElementById("status");
const clientId = globalThis.crypto && globalThis.crypto.randomUUID
  ? globalThis.crypto.randomUUID()
  : `${{Date.now()}}-${{Math.random().toString(36).slice(2)}}`;
let latestDensitySeq = -1;
let pendingDensityMsg = null;
let densityInFlight = false;

function b64ToArrayBuffer(b64) {{
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}}

function pointsPayloadInsideView(trace) {{
  const view = window.fastchartsLiveDrilldown;
  if (!view || !trace || trace.mode !== "points" || !trace.x_range || !trace.y_range) return true;
  const candidate = view._viewAnim && view._viewAnim.target ? view._viewAnim.target : view.view;
  return viewInsideWindow(candidate, {{
    x0: trace.x_range[0],
    x1: trace.x_range[1],
    y0: trace.y_range[0],
    y1: trace.y_range[1],
  }});
}}

function viewInsideWindow(candidate, win) {{
  if (!candidate || !win) return false;
  const ex = (candidate.x1 - candidate.x0) * 1e-4;
  const ey = (candidate.y1 - candidate.y0) * 1e-4;
  return (
    candidate.x0 >= win.x0 - ex &&
    candidate.x1 <= win.x1 + ex &&
    candidate.y0 >= win.y0 - ey &&
    candidate.y1 <= win.y1 + ey
  );
}}

function currentDrillCoversView(view, candidate) {{
  const trace = view && view.gpuTraces && view.gpuTraces.find((g) => g.tier === "density");
  if (!trace || !trace.drill) return true;
  return viewInsideWindow(candidate, trace.drill.win);
}}

async function endpointUrl() {{
  try {{
    const env = await fetch("/env.json").then((r) => r.ok ? r.json() : null);
    if (env && env.PING) return new URL("{route}", env.PING).href;
  }} catch (err) {{}}
  return "{route}";
}}

const endpoint = endpointUrl();
async function sendMessage(msg) {{
  const outbound = {{ ...msg, client_id: clientId }};
  try {{
    const res = await fetch(await endpoint, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(outbound),
    }});
    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
    const payload = await res.json();
    if (
      payload.message &&
      payload.message.type === "density_update" &&
      (payload.message.seq !== latestDensitySeq ||
        (window.fastchartsLiveDrilldown && payload.message.seq !== window.fastchartsLiveDrilldown.seq))
    ) return;
    const buffers = (payload.buffers || []).map(b64ToArrayBuffer);
    for (const cb of callbacks) cb(payload.message, buffers);
    const trace = payload.message && payload.message.traces && payload.message.traces[0];
    if (trace && trace.mode) {{
      if (trace.mode === "points" && !pointsPayloadInsideView(trace)) {{
        statusEl.textContent = "updating";
        return;
      }}
      const visible = Number(trace.visible || 0).toLocaleString();
      statusEl.textContent = trace.mode === "points" ? `${{visible}} points` : `${{visible}} density`;
    }}
  }} catch (err) {{
    statusEl.textContent = "offline";
    console.error("fastcharts drilldown request failed", err);
  }}
}}

async function pumpDensity() {{
  if (densityInFlight || !pendingDensityMsg) return;
  const msg = pendingDensityMsg;
  pendingDensityMsg = null;
  densityInFlight = true;
  try {{
    await sendMessage(msg);
  }} finally {{
    densityInFlight = false;
    if (pendingDensityMsg) void pumpDensity();
  }}
}}

const comm = {{
  send: async (msg) => {{
    if (!["density_view", "pick", "select", "select_clear"].includes(msg.type)) return;
    if (msg.type === "density_view") {{
      latestDensitySeq = msg.seq;
      pendingDensityMsg = msg;
      statusEl.textContent = "updating";
      void pumpDensity();
      return;
    }}
    await sendMessage(msg);
  }},
  onMessage: (cb) => callbacks.push(cb),
}};

const view = new fastcharts.ChartView(
  document.getElementById("chart"),
  spec,
  initialBytes.buffer,
  comm,
);
const setView = view._setView.bind(view);
view._setView = (next, opts) => {{
  const result = setView(next, opts);
  if (!currentDrillCoversView(view, next)) statusEl.textContent = "updating";
  return result;
}};
window.fastchartsLiveDrilldown = view;
</script>
</body>
</html>"""
