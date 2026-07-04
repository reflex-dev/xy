from __future__ import annotations

import base64
import json
import threading
from functools import lru_cache
from typing import Any, Union

import numpy as np
from starlette.requests import Request
from starlette.responses import JSONResponse

from fastcharts import Figure
from fastcharts.widget import bundled_js

LIVE_SCATTER_POINTS = 10_000_000
LIVE_DRILLDOWN_ROUTE = "/api/fastcharts/drilldown"
_FIGURE_LOCK = threading.Lock()


def colored_scatter_data(
    n: int = LIVE_SCATTER_POINTS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1.0, n)
    y = x.copy()
    y *= 0.55
    y += rng.normal(0, 0.55, n)
    color = np.hypot(x, y)
    size = rng.normal(6, 2.5, n)
    np.abs(size, out=size)
    np.clip(size, 2, 16, out=size)
    return x, y, color, size


def colored_scatter_figure(
    n: int = LIVE_SCATTER_POINTS,
    *,
    title: str = "10M live drilldown scatter",
    width: Union[str, int] = "100%",
    height: int = 430,
) -> Figure:
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
    return colored_scatter_figure()


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
<title>10M live drilldown scatter</title>
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
let latestDensitySeq = -1;

function b64ToArrayBuffer(b64) {{
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}}

async function endpointUrl() {{
  try {{
    const env = await fetch("/env.json").then((r) => r.ok ? r.json() : null);
    if (env && env.PING) return new URL("{route}", env.PING).href;
  }} catch (err) {{}}
  return "{route}";
}}

const endpoint = endpointUrl();
const comm = {{
  send: async (msg) => {{
    if (!["density_view", "pick", "select", "select_clear"].includes(msg.type)) return;
    try {{
      if (msg.type === "density_view") {{
        latestDensitySeq = msg.seq;
        statusEl.textContent = "updating";
      }}
      const res = await fetch(await endpoint, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(msg),
      }});
      if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
      const payload = await res.json();
      if (
        payload.message &&
        payload.message.type === "density_update" &&
        payload.message.seq !== latestDensitySeq
      ) return;
      const buffers = (payload.buffers || []).map(b64ToArrayBuffer);
      for (const cb of callbacks) cb(payload.message, buffers);
      const trace = payload.message && payload.message.traces && payload.message.traces[0];
      if (trace && trace.mode) {{
        const visible = Number(trace.visible || 0).toLocaleString();
        statusEl.textContent = trace.mode === "points" ? `${{visible}} points` : `${{visible}} density`;
      }}
    }} catch (err) {{
      statusEl.textContent = "offline";
      console.error("fastcharts drilldown request failed", err);
    }}
  }},
  onMessage: (cb) => callbacks.push(cb),
}};

const view = new fastcharts.ChartView(
  document.getElementById("chart"),
  spec,
  initialBytes.buffer,
  comm,
);
window.fastchartsLiveDrilldown = view;
</script>
</body>
</html>"""
