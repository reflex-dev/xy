"""FastAPI live drilldown: a 100M-point scatter served by the engine's own LOD.

The pattern this example demonstrates is deliberately small:

- build one figure (`live_figure`), serve its payload plus the bundled render
  client as a single HTML page;
- wire `ChartView` to a custom transport — a `comm` object whose `send` POSTs
  the client's messages to one endpoint and feeds each JSON reply (with its
  base64 binary buffers) back through `onMessage`;
- the endpoint dispatches `density_view` / `pick` straight to the figure,
  under one lock.

Everything hard belongs to the engine. `Figure.density_view` picks the tier
per window — mean-color pyramid composition for wide views, exact re-bins
near the drill budget, exact points inside it (LOD doc §2/§4) — and the
render client debounces its requests, drops stale replies by `seq`, and keeps
the best cached density texture drawn until a fresh one lands (§17
stale-while-revalidate). Earlier revisions of this demo predated the kernel
pyramid and re-implemented zoom-out aggregation twice — an integral-image
overview server-side and ~350 lines of page JS (local re-bins, request
parking, per-client staleness maps). Those paths could only aggregate counts,
not the §2 mean-color planes, which is why they were both slower to maintain
and wrong the moment the density surface started wearing the data's colors.
"""

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

# The live drilldown server probes the engine directly (density_view, pick),
# so it works on the internal figure compiled from the public composition API
# via `Chart.figure()`.
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
# One figure serves every request; density_view mutates its drill bookkeeping,
# so requests (and payload builds) serialize.
_FIGURE_LOCK = threading.Lock()


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
    fig = colored_scatter_figure()
    # Warm the kernel's mean-color pyramid (LOD doc §4) at startup so the
    # first interactive zoom answers in milliseconds instead of paying the
    # one-time build; the reply itself is discarded.
    x0, x1 = fig.x_range()
    y0, y1 = fig.y_range()
    fig.density_view(0, x0, x1, y0, y1, 512, 384)
    return fig


def _b64(buf: bytes) -> str:
    return base64.b64encode(buf).decode("ascii")


def _response(message: dict[str, Any], buffers: list[bytes] | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "message": message,
            "buffers": [_b64(buffer) for buffer in (buffers or [])],
        }
    )


async def drilldown_endpoint(request: Request) -> JSONResponse:
    """Answer the render client's messages with the engine's own replies.

    One lock, one dispatch — no request bookkeeping. `Figure.density_view`
    owns the whole ladder (mean-color pyramid for wide windows, exact re-bins
    near the budget, drill-in to real points, hysteresis, recorded
    reductions), and the render client discards stale replies by `seq`.
    """
    try:
        content = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    kind = content.get("type")
    with _FIGURE_LOCK:
        fig = live_figure()
        if kind == "density_view":
            try:
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
    fig = live_figure()
    with _FIGURE_LOCK:
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
const statusEl = document.getElementById("status");
const callbacks = [];

function b64ToArrayBuffer(b64) {{
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}}

// The demo may run behind a proxying sandbox that exposes the API on another
// origin (PING in /env.json); otherwise the route is same-origin.
async function endpointUrl() {{
  try {{
    const env = await fetch("/env.json").then((r) => r.ok ? r.json() : null);
    if (env && env.PING) return new URL("{route}", env.PING).href;
  }} catch (err) {{}}
  return "{route}";
}}
const endpoint = endpointUrl();

// The whole custom transport: POST the render client's message, hand the
// reply and its binary buffers back to the view. Tiering, drill state, the
// mean-color pyramid, request debouncing, stale-reply drops (by seq), and
// the cached-texture hold while a reply is in flight all live in the engine
// and its render client — this page only moves bytes and updates a badge.
async function sendMessage(msg) {{
  try {{
    const res = await fetch(await endpoint, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(msg),
    }});
    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
    const payload = await res.json();
    if (!payload.message) return;
    const buffers = (payload.buffers || []).map(b64ToArrayBuffer);
    for (const cb of callbacks) cb(payload.message, buffers);
    const trace = payload.message.traces && payload.message.traces[0];
    if (trace && trace.mode && payload.message.seq === view.seq) {{
      const visible = Number(trace.visible || 0).toLocaleString();
      statusEl.textContent = trace.mode === "points" ? `${{visible}} points` : `${{visible}} density`;
    }}
  }} catch (err) {{
    statusEl.textContent = "offline";
    console.error("xy drilldown request failed", err);
  }}
}}

const comm = {{
  send: (msg) => {{
    if (["density_view", "pick", "select", "select_clear"].includes(msg.type)) {{
      void sendMessage(msg);
    }}
  }},
  onMessage: (cb) => callbacks.push(cb),
}};

const view = new xy.ChartView(
  document.getElementById("chart"),
  spec,
  initialBytes.buffer,
  comm,
);
window.xyLiveDrilldown = view;
</script>
</body>
</html>"""
