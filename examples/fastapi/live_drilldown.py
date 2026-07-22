from __future__ import annotations

import base64
import json
import os
import threading
import warnings
from functools import lru_cache
from typing import Any, Union

import numpy as np
from starlette.requests import Request
from starlette.responses import JSONResponse

import xy

# The live drilldown server probes the engine directly (traces, density_view,
# drill bookkeeping), so it works on the internal figure compiled from the
# public composition API via `Chart.figure()`.
from xy._figure import Figure
from xy.widget import bundled_js

_DEFAULT_LIVE_POINTS = 100_000_000


def _live_points() -> int:
    """Point count for the drilldown demo, from ``XY_LIVE_POINTS``.

    A non-integer or non-positive value falls back to the default with a
    warning rather than aborting app import or failing deep in data generation.
    """
    raw = os.environ.get("XY_LIVE_POINTS")
    if raw is None:
        return _DEFAULT_LIVE_POINTS
    try:
        points = int(raw)
    except ValueError:
        points = 0
    if points < 1:
        warnings.warn(
            f"XY_LIVE_POINTS={raw!r} is not a positive integer; using {_DEFAULT_LIVE_POINTS:,}",
            RuntimeWarning,
            stacklevel=2,
        )
        return _DEFAULT_LIVE_POINTS
    return points


# Point count for the drilldown demo; override with XY_LIVE_POINTS.
LIVE_SCATTER_POINTS = _live_points()
LIVE_DRILLDOWN_ROUTE = "/api/xy/drilldown"
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


def colored_scatter_chart(
    n: int = LIVE_SCATTER_POINTS,
    *,
    title: str | None = None,
    width: Union[str, int] = "100%",
    height: int = 430,
) -> xy.Chart:
    title = title or f"{_point_label(n)} live drilldown scatter"
    x, y, color, size = colored_scatter_data(n)
    return xy.scatter_chart(
        xy.scatter(x, y, color=color, size=size, colormap="viridis", opacity=0.72, density=True),
        xy.x_axis(label="feature A"),
        xy.y_axis(label="feature B"),
        title=title,
        width=width,
        height=height,
    )


def colored_scatter_figure(
    n: int = LIVE_SCATTER_POINTS,
    *,
    title: str | None = None,
    width: Union[str, int] = "100%",
    height: int = 430,
) -> Figure:
    return colored_scatter_chart(n, title=title, width=width, height=height).figure()


@lru_cache(maxsize=1)
def live_figure() -> Figure:
    return colored_scatter_figure()


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
        fig = live_figure()
        if kind == "density_view":
            try:
                if _density_is_stale(density_client_id or "default", density_seq):
                    return _response(
                        {
                            "type": "density_update",
                            "seq": content.get("seq"),
                            "trace": content.get("trace"),
                            "stale": True,
                            "traces": [],
                        }
                    )
                # The engine serves every window itself: wide windows come
                # from the kernel's mean-color pyramid in O(visible cells)
                # (LOD doc §2/§4 — counts AND per-cell mean point colors, so
                # the aggregate always wears the data's own colors), and
                # near-budget windows drill to exact points. The demo's old
                # integral-image overview predated the pyramid and could only
                # re-bin counts, which is exactly the colorless surface the
                # engine no longer draws.
                update, buffers = fig.density_view(
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
                {
                    "type": "density_update",
                    "seq": content.get("seq"),
                    "trace": content.get("trace"),
                    **update,
                },
                buffers,
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
const REQUEST_TIMEOUT_MS = 15000;
const overviewTrace = spec.traces.find((trace) => trace.kind === "scatter" && trace.density);
const clientId = globalThis.crypto && globalThis.crypto.randomUUID
  ? globalThis.crypto.randomUUID()
  : `${{Date.now()}}-${{Math.random().toString(36).slice(2)}}`;
let latestDensitySeq = -1;
let pendingDensityMsg = null;
let densityInFlight = false;
const DIRECT_POINT_BUDGET = 200000;
const LOCAL_DENSITY_EXACT_FACTOR = 4;
let overviewIntegral = null;
let overviewDensityBuffer = null;
let overviewRgbaBuffer = null;

function overviewData() {{
  if (!overviewTrace || !overviewTrace.density) return null;
  const density = overviewTrace.density;
  const col = spec.columns[density.buf];
  if (!col) return null;
  let values;
  if (density.enc === "log-u8") {{
    const encoded = new Uint8Array(initialBytes.buffer, col.byte_offset || 0, col.len);
    values = new Float32Array(encoded.length);
    const denom = Math.log1p(Math.max(0, density.max || 0));
    if (denom > 0) {{
      for (let i = 0; i < encoded.length; i++) {{
        if (encoded[i] > 0) values[i] = Math.expm1((encoded[i] / 255) * denom);
      }}
    }}
  }} else {{
    values = new Float32Array(initialBytes.buffer, col.byte_offset || 0, col.len);
  }}
  // Mean point color plane (LOD doc §2): local re-bins aggregate it alongside
  // the counts, so browser-served grids wear the data's colors exactly like
  // kernel-served ones — count only ever drives the alpha.
  let rgba = null;
  if (density.rgba !== undefined && spec.columns[density.rgba]) {{
    const rcol = spec.columns[density.rgba];
    rgba = new Uint8Array(initialBytes.buffer, rcol.byte_offset || 0, rcol.len);
  }}
  return {{
    density,
    values,
    rgba,
    width: density.w,
    height: density.h,
  }};
}}

const overview = overviewData();

// sRGB <-> linear-light for mean-color aggregation — the same law as the
// kernel's bin_2d_mean_color, so a locally re-binned cell matches what the
// server would ship for the same window.
const SRGB_LIN = (() => {{
  const table = new Float64Array(256);
  for (let i = 0; i < 256; i++) {{
    const c = i / 255;
    table[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }}
  return table;
}})();
function linearToSrgb8(v) {{
  const c = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(c * 255)));
}}

function b64ToArrayBuffer(b64) {{
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}}

function pointsPayloadInsideView(trace) {{
  const view = window.xyLiveDrilldown;
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

function densityRequestPending(view) {{
  const trace = view && view.gpuTraces && view.gpuTraces.find((g) => g.tier === "density");
  if (!(trace && trace._lodPendingView && trace._lodPendingSeq === view.seq)) return false;
  if (trace._lodPendingAt && performance.now() - trace._lodPendingAt > REQUEST_TIMEOUT_MS + 500) {{
    return false;
  }}
  return true;
}}

function clearStaleUpdatingStatus() {{
  if (statusEl.textContent !== "updating") return;
  if (densityRequestPending(window.xyLiveDrilldown)) return;
  statusEl.textContent = "density";
}}

function sameRange(a0, a1, b0, b1) {{
  const span = Math.max(Math.abs(b1 - b0), 1);
  const eps = span * 1e-6;
  return Math.abs(a0 - b0) <= eps && Math.abs(a1 - b1) <= eps;
}}

function isInitialOverviewRequest(msg) {{
  if (!overviewTrace || !overviewTrace.density || Number(msg.trace) !== overviewTrace.id) return false;
  const density = overviewTrace.density;
  return (
    sameRange(Number(msg.x0), Number(msg.x1), density.x_range[0], density.x_range[1]) &&
    sameRange(Number(msg.y0), Number(msg.y1), density.y_range[0], density.y_range[1])
  );
}}

function setDensityStatus(visible) {{
  statusEl.textContent = `${{Number(visible || 0).toLocaleString()}} density`;
}}

function overviewDensityArrayBuffer() {{
  if (!overview) return null;
  if (!overviewDensityBuffer) {{
    overviewDensityBuffer = overview.values.buffer.slice(
      overview.values.byteOffset,
      overview.values.byteOffset + overview.values.byteLength,
    );
  }}
  return overviewDensityBuffer;
}}

function overviewRgbaArrayBuffer() {{
  if (!overview || !overview.rgba) return null;
  if (!overviewRgbaBuffer) {{
    overviewRgbaBuffer = overview.rgba.buffer.slice(
      overview.rgba.byteOffset,
      overview.rgba.byteOffset + overview.rgba.byteLength,
    );
  }}
  return overviewRgbaBuffer;
}}

function initialOverviewUpdate(msg) {{
  if (!overview || !overviewTrace || !overviewTrace.density) return null;
  const buffer = overviewDensityArrayBuffer();
  if (!buffer) return null;
  const density = overviewTrace.density;
  // Re-serve the home grid with its mean-color plane — dropping it here would
  // flip the overview back to a count-colormapped surface on the way out.
  const rgbaBuffer = overviewRgbaArrayBuffer();
  const densityOut = {{
    buf: 0,
    w: density.w,
    h: density.h,
    max: density.max,
    x_range: density.x_range,
    y_range: density.y_range,
  }};
  if (rgbaBuffer) {{
    densityOut.rgba = 1;
    densityOut.color_agg = "mean";
  }}
  return {{
    visible: overviewTrace.n_points,
    message: {{
      type: "density_update",
      seq: msg.seq,
      traces: [{{
        id: Number(msg.trace),
        mode: "density",
        visible: overviewTrace.n_points,
        density: densityOut,
      }}],
    }},
    buffers: rgbaBuffer ? [buffer, rgbaBuffer] : [buffer],
  }};
}}

function buildOverviewIntegral() {{
  if (!overview) return null;
  if (overviewIntegral) return overviewIntegral;
  const {{ values, width, height }} = overview;
  const stride = width + 1;
  const integral = new Float64Array((height + 1) * stride);
  for (let y = 0; y < height; y++) {{
    let rowSum = 0;
    for (let x = 0; x < width; x++) {{
      rowSum += values[y * width + x] || 0;
      integral[(y + 1) * stride + x + 1] = integral[y * stride + x + 1] + rowSum;
    }}
  }}
  overviewIntegral = {{ integral, stride }};
  return overviewIntegral;
}}

function overviewEdge(value, domain, cells) {{
  const span = domain[1] - domain[0];
  if (!Number.isFinite(value) || !Number.isFinite(span) || span <= 0) return 0;
  const raw = Math.floor(((value - domain[0]) / span) * cells);
  return Math.max(0, Math.min(cells, raw));
}}

// Inverse of overviewEdge: the data coordinate at a source-bin boundary. A
// requested window can extend past the data domain, where overviewEdge clamps
// the bin index; mapping that clamped index back gives the range the grid
// actually covers, which is what the renderer must be told (see below).
function overviewEdgeValue(bin, domain, cells) {{
  const span = domain[1] - domain[0];
  if (!Number.isFinite(span) || cells <= 0) return domain[0];
  return domain[0] + (bin / cells) * span;
}}

function overviewSum(ii, stride, x0, x1, y0, y1) {{
  return (
    ii[y1 * stride + x1] -
    ii[y0 * stride + x1] -
    ii[y1 * stride + x0] +
    ii[y0 * stride + x0]
  );
}}

function localDensityUpdate(msg) {{
  if (!overview || Number(msg.trace) !== overviewTrace.id) return null;
  const built = buildOverviewIntegral();
  if (!built) return null;
  const {{ density, width, height }} = overview;
  const loX = Math.min(Number(msg.x0), Number(msg.x1));
  const hiX = Math.max(Number(msg.x0), Number(msg.x1));
  const loY = Math.min(Number(msg.y0), Number(msg.y1));
  const hiY = Math.max(Number(msg.y0), Number(msg.y1));
  const bx0 = overviewEdge(loX, density.x_range, width);
  const bx1 = overviewEdge(hiX, density.x_range, width);
  const by0 = overviewEdge(loY, density.y_range, height);
  const by1 = overviewEdge(hiY, density.y_range, height);
  if (bx1 <= bx0 || by1 <= by0) return null;

  const sourceW = bx1 - bx0;
  const sourceH = by1 - by0;
  const visible = overviewSum(built.integral, built.stride, bx0, bx1, by0, by1);
  if (visible <= DIRECT_POINT_BUDGET * LOCAL_DENSITY_EXACT_FACTOR) return null;
  if (sourceW < 16 || sourceH < 16) return null;

  // The grid's cells span the clamped source bins [bx0,bx1]x[by0,by1], which
  // cover only the on-domain part of the requested window. Report the data
  // range those bins actually represent — not the raw request. Reporting the
  // request would stretch the fixed-extent texture across a wider window
  // whenever the view reaches past the data, sliding the density off the
  // point cloud (drilled points and the retained sample draw at true data
  // coordinates, so any mismatch here shows up as an offset).
  const gridX0 = overviewEdgeValue(bx0, density.x_range, width);
  const gridX1 = overviewEdgeValue(bx1, density.x_range, width);
  const gridY0 = overviewEdgeValue(by0, density.y_range, height);
  const gridY1 = overviewEdgeValue(by1, density.y_range, height);

  const requestedW = Math.round(Number(msg.w) || width);
  const requestedH = Math.round(Number(msg.h) || height);
  const outW = Math.max(16, Math.min(requestedW, width, sourceW));
  const outH = Math.max(16, Math.min(requestedH, height, sourceH));
  const grid = new Float32Array(outW * outH);
  // Mean point color per output cell (LOD doc §2): the weighted mean of the
  // covered source cells' mean colors, weight = count × mean point alpha —
  // the same aggregation the kernel's pyramid compose applies, in linear
  // light. Total work is one pass over the covered source cells.
  const meanRgba = overview.rgba ? new Uint8Array(outW * outH * 4) : null;
  let max = 0;
  for (let y = 0; y < outH; y++) {{
    const y0 = Math.floor(by0 + (sourceH * y) / outH);
    const y1 = Math.max(y0 + 1, Math.floor(by0 + (sourceH * (y + 1)) / outH));
    for (let x = 0; x < outW; x++) {{
      const x0 = Math.floor(bx0 + (sourceW * x) / outW);
      const x1 = Math.max(x0 + 1, Math.floor(bx0 + (sourceW * (x + 1)) / outW));
      const value = overviewSum(built.integral, built.stride, x0, x1, y0, y1);
      grid[y * outW + x] = value;
      if (value > max) max = value;
      if (!meanRgba || value <= 0) continue;
      let weight = 0, r = 0, g = 0, b = 0, alphaSum = 0, countSum = 0;
      for (let sy = y0; sy < y1; sy++) {{
        for (let sx = x0; sx < x1; sx++) {{
          const count = overview.values[sy * width + sx];
          if (!(count > 0)) continue;
          const at = (sy * width + sx) * 4;
          const cellAlpha = overview.rgba[at + 3];
          const w2 = count * cellAlpha;
          countSum += count;
          alphaSum += w2;
          if (w2 <= 0) continue;
          weight += w2;
          r += w2 * SRGB_LIN[overview.rgba[at]];
          g += w2 * SRGB_LIN[overview.rgba[at + 1]];
          b += w2 * SRGB_LIN[overview.rgba[at + 2]];
        }}
      }}
      if (weight > 0 && countSum > 0) {{
        const at = (y * outW + x) * 4;
        meanRgba[at] = linearToSrgb8(r / weight);
        meanRgba[at + 1] = linearToSrgb8(g / weight);
        meanRgba[at + 2] = linearToSrgb8(b / weight);
        meanRgba[at + 3] = Math.max(0, Math.min(255, Math.round(alphaSum / countSum)));
      }}
    }}
  }}
  const densityOut = {{
    buf: 0,
    w: outW,
    h: outH,
    max,
    x_range: [gridX0, gridX1],
    y_range: [gridY0, gridY1],
  }};
  if (meanRgba) {{
    densityOut.rgba = 1;
    densityOut.color_agg = "mean";
  }}
  return {{
    visible,
    message: {{
      type: "density_update",
      seq: msg.seq,
      traces: [{{
        id: Number(msg.trace),
        mode: "density",
        visible: Math.round(visible),
        density: densityOut,
      }}],
    }},
    buffers: meanRgba ? [grid.buffer, meanRgba.buffer] : [grid.buffer],
  }};
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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {{
    const res = await fetch(await endpoint, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(outbound),
      signal: controller.signal,
    }});
    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
    const payload = await res.json();
    if (
      payload.message &&
      payload.message.type === "density_update" &&
      (payload.message.seq !== latestDensitySeq ||
        (window.xyLiveDrilldown && payload.message.seq !== window.xyLiveDrilldown.seq))
    ) {{
      clearStaleUpdatingStatus();
      return;
    }}
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
    }} else {{
      clearStaleUpdatingStatus();
    }}
  }} catch (err) {{
    if (err && err.name === "AbortError" && msg.type === "density_view") {{
      // Client-side timeout, not an outage: a first deep exact scan over the
      // full source can legitimately outlast REQUEST_TIMEOUT_MS (observed at
      // 15.007s vs the 15s budget). Re-park the request so the pump retries
      // it — parkedMsgStale still drops it if the view moved on — instead of
      // stranding the window behind a misleading "offline".
      if (!pendingDensityMsg && (msg._retries = (msg._retries || 0) + 1) <= 2) {{
        pendingDensityMsg = msg;
        statusEl.textContent = "updating";
      }} else if (!pendingDensityMsg) {{
        statusEl.textContent = "timed out";
      }}
    }} else {{
      statusEl.textContent = "offline";
      console.error("xy drilldown request failed", err);
    }}
  }} finally {{
    clearTimeout(timeout);
  }}
}}

// A parked message can go stale while the previous request is in flight: a
// newer request supersedes it (seq moved on), or the view moved *without* a
// new request — the engine deliberately skips re-requesting while the current
// drill covers the view, so seq alone is not a complete staleness token here.
// Sending such a message anyway asks the server about a window nobody is
// looking at (observed in the wire capture: a zoomed-in window request fired
// long after zooming out); the exact-points reply then churns server drill
// state and, when the seq still matches, installs a drill that is instantly
// dying. Drop it at send time instead.
function parkedMsgStale(msg) {{
  const view = window.xyLiveDrilldown;
  if (!view || !msg || msg.seq === undefined) return false;
  if (msg.seq !== view.seq) return true;
  // Compare against where the view is headed, not a mid-animation frame —
  // a parked request for the animation target is current, not stale.
  const v = view._viewAnim && view._viewAnim.target ? view._viewAnim.target : view.view;
  return !(
    sameRange(Number(msg.x0), Number(msg.x1), Math.min(v.x0, v.x1), Math.max(v.x0, v.x1)) &&
    sameRange(Number(msg.y0), Number(msg.y1), Math.min(v.y0, v.y1), Math.max(v.y0, v.y1))
  );
}}

async function pumpDensity() {{
  if (densityInFlight || !pendingDensityMsg) return;
  const msg = pendingDensityMsg;
  pendingDensityMsg = null;
  if (parkedMsgStale(msg)) {{
    clearStaleUpdatingStatus();
    return;
  }}
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
      if (isInitialOverviewRequest(msg)) {{
        pendingDensityMsg = null;
        const initial = initialOverviewUpdate(msg);
        if (initial) {{
          for (const cb of callbacks) cb(initial.message, initial.buffers);
          setDensityStatus(initial.visible);
        }} else {{
          setDensityStatus(overviewTrace.n_points);
        }}
        return;
      }}
      const local = localDensityUpdate(msg);
      if (local) {{
        pendingDensityMsg = null;
        for (const cb of callbacks) cb(local.message, local.buffers);
        setDensityStatus(Math.round(local.visible));
        return;
      }}
      pendingDensityMsg = msg;
      statusEl.textContent = "updating";
      void pumpDensity();
      return;
    }}
    await sendMessage(msg);
  }},
  onMessage: (cb) => callbacks.push(cb),
}};

const view = new xy.ChartView(
  document.getElementById("chart"),
  spec,
  initialBytes.buffer,
  comm,
);
const setView = view._setView.bind(view);
view._setView = (next, opts) => {{
  const result = setView(next, opts);
  if (densityRequestPending(view) && !currentDrillCoversView(view, next)) {{
    statusEl.textContent = "updating";
  }}
  return result;
}};
window.xyLiveDrilldown = view;
</script>
</body>
</html>"""
