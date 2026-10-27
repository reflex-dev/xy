#!/usr/bin/env python3
"""Live xy chart host for the UX benchmark: production client, production wire.

Runs as a child process. Serves one page whose JS imports `ChartView` from the
shipped ESM bundle and connects it to this process over a real WebSocket. The
bridge is `channel.handle_message` — the same dispatcher the widget and Reflex
adapters use — so deep zoom drills to exact rows exactly as a live chart does.
This is the interactive xy chart; the standalone HTML export is not measured.

Wire framing (binary, both directions where buffers ride):
    u32le json_len | json bytes | buffer bytes concatenated
    json: {"content": <message>, "buf_lens": [int, ...]}
Client -> server messages are plain JSON text (inbound carries no buffers).

Also serves:
    /static/*   the installed xy client bundle
    /oracle     ?x0=&x1=&y0=&y1= -> {"count": rows in window}  (ground truth
                for the drill check, computed on the exact source arrays)

On startup prints one line:  META {"port": ..., "n": ..., "sentinels": [...]}
then serves until killed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import tornado.httpserver
import tornado.netutil
import tornado.web
import tornado.websocket

import xy
from xy.channel import handle_message

SEED = 20260713
# Sentinels sit in the far Gaussian tail: guaranteed sparse (drillable), and
# they stretch the autoscaled home domain so their home-view pixels are
# interior, not clipped at the frame edge.
SENTINELS = [(4.6, 2.2), (4.9, 2.45), (4.75, 2.05), (5.0, 2.3), (4.55, 2.5)]


def make_data(n: int) -> tuple[np.ndarray, np.ndarray]:
    """The ceiling workload plus planted sentinel rows (replacing, not
    appending, so every arm still receives exactly n rows)."""
    rng = np.random.default_rng(SEED)
    x = rng.standard_normal(n, dtype=np.float32)
    y = rng.standard_normal(n, dtype=np.float32)
    y *= np.float32(1.2)
    y += x
    y *= np.float32(0.5)
    for i, (sx, sy) in enumerate(SENTINELS):
        x[i] = np.float32(sx)
        y[i] = np.float32(sy)
    return x, y


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>xy live</title>
<style>html,body{margin:0;background:#fff}#chart{width:900px;height:420px}</style>
<div id="chart"></div>
<script type="module">
import { ChartView } from "/static/index.js";

function decodeFrame(buf) {
  // Header and every buffer are 8-byte padded by the host so each column's
  // DataView offset satisfies its dtype alignment (the client's decoder
  // rejects misaligned columns, correctly).
  const view = new DataView(buf);
  const jsonLen = view.getUint32(0, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, jsonLen)));
  const buffers = [];
  let off = (4 + jsonLen + 7) & ~7;
  for (const len of json.buf_lens) {
    buffers.push(new DataView(buf, off, len));
    off += (len + 7) & ~7;
  }
  return { content: json.content, buffers };
}

const ws = new WebSocket(`ws://${location.host}/ws`);
ws.binaryType = "arraybuffer";
const handlers = [];
ws.onmessage = (ev) => {
  if (typeof ev.data === "string") return;
  const { content, buffers } = decodeFrame(ev.data);
  if (content.type === "init") {
    const comm = {
      send: (msg) => ws.send(JSON.stringify(msg)),
      wantsViewChange: () => false,
      onMessage: (cb) => { handlers.push(cb); return () => {}; },
    };
    window.__view = new ChartView(
      document.getElementById("chart"), content.spec, buffers, comm);
    window.__wireReady = true;
  } else {
    for (const cb of handlers) cb(content, buffers);
  }
};

window.__arm = {
  ready: () => !!window.__view && !!window.__view.gl,
  domain: () => {
    const v = window.__view && window.__view.view;
    return v ? { x0: v.x0, x1: v.x1, y0: v.y0, y1: v.y1 } : null;
  },
  project: (x, y) => {
    const view = window.__view;
    const v = view.view;
    const r = view.canvas.getBoundingClientRect();
    if (x < v.x0 || x > v.x1 || y < v.y0 || y > v.y1) return null;
    return {
      px: ((x - v.x0) / (v.x1 - v.x0)) * r.width,
      py: (1 - (y - v.y0) / (v.y1 - v.y0)) * r.height,
    };
  },
  readbacks: () => {
    const view = window.__view;
    view._drawNow();
    const gl = view.gl;
    gl.finish();
    const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const data = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, data);
    const r = view.canvas.getBoundingClientRect();
    return [{ data, w, h, topDown: false, cssW: r.width, cssH: r.height }];
  },
  zoomInput: (fx, fy, dir) => {
    const view = window.__view;
    const r = view.canvas.getBoundingClientRect();
    view.canvas.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true, cancelable: true,
      clientX: r.left + r.width * fx,
      clientY: r.top + r.height * fy,
      deltaY: dir > 0 ? -120 : 120,
      deltaMode: 0,
    }));
  },
};
</script>
"""


def encode_frame(content: dict[str, Any], buffers: list[Any]) -> bytes:
    """Frame with 8-byte alignment: header padded, each buffer padded, so
    every column's client-side DataView offset meets its dtype alignment."""
    raw = [bytes(memoryview(b)) for b in buffers]
    body = json.dumps({"content": content, "buf_lens": [len(b) for b in raw]}).encode()
    parts = [struct.pack("<I", len(body)), body, b" " * (-(4 + len(body)) % 8)]
    for b in raw:
        parts.append(b)
        parts.append(b"\0" * (-len(b) % 8))
    return b"".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--density", choices=("auto", "off"), default="auto")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    x, y = make_data(args.n)
    mark = xy.scatter(x=x, y=y, density=False) if args.density == "off" else xy.scatter(x=x, y=y)
    fig = xy.scatter_chart(mark, width=900, height=420).figure()
    spec, bufs = fig.build_payload_split()

    static_dir = Path(xy.__file__).resolve().parent / "static"

    class PageHandler(tornado.web.RequestHandler):
        def get(self) -> None:
            self.set_header("Content-Type", "text/html")
            self.write(PAGE)

    class OracleHandler(tornado.web.RequestHandler):
        def get(self) -> None:
            q = {k: float(self.get_argument(k)) for k in ("x0", "x1", "y0", "y1")}
            inside = (x >= q["x0"]) & (x <= q["x1"]) & (y >= q["y0"]) & (y <= q["y1"])
            self.write({"count": int(np.count_nonzero(inside))})

    class WSHandler(tornado.websocket.WebSocketHandler):
        def open(self) -> None:
            self.write_message(encode_frame({"type": "init", "spec": spec}, bufs), binary=True)

        def on_message(self, message: str | bytes) -> None:
            if isinstance(message, bytes):
                return  # inbound messages carry no buffers (channel contract)
            reply = handle_message(fig, json.loads(message))
            if reply is not None:
                content, out = reply
                self.write_message(encode_frame(content, out), binary=True)

    async def serve() -> None:
        # The server must be created inside the running loop so its handlers
        # are scheduled on it — created outside, the socket binds but accepted
        # connections are never serviced.
        app = tornado.web.Application(
            [
                (r"/", PageHandler),
                (r"/ws", WSHandler),
                (r"/oracle", OracleHandler),
                (
                    r"/static/(.*)",
                    tornado.web.StaticFileHandler,
                    {"path": str(static_dir)},
                ),
            ]
        )
        sockets = tornado.netutil.bind_sockets(args.port, "127.0.0.1")
        server = tornado.httpserver.HTTPServer(app)
        server.add_sockets(sockets)
        port = sockets[0].getsockname()[1]
        print(
            "META "
            + json.dumps(
                {
                    "port": port,
                    "n": args.n,
                    "sentinels": [list(s) for s in SENTINELS],
                    "mode": "density" if fig.traces[0].use_density() else "direct",
                }
            ),
            flush=True,
        )
        await asyncio.Event().wait()

    asyncio.run(serve())


if __name__ == "__main__":
    main()
