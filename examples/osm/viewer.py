"""Interactive browser viewer for an out-of-core OSM node scatter.

Serves xy's real WebGL render client (`python/xy/static/index.js`) against a
disk-backed density-scatter Figure. Pan/zoom drive the same kernel protocol the
notebook widget uses (`channel.handle_message`), so every viewport is
re-aggregated from the density pyramid — screen-bounded, at 1B+ points.

Transport is plain HTTP (the client correlates replies by `seq`, so a
request/response POST per message is sufficient — no websocket, stdlib only):

    GET  /          → the page (imports the client, builds a ChartView)
    GET  /index.js  → the render client bundle
    GET  /init      → framed initial payload (spec + buffers)
    POST /msg       → one client message → framed kernel reply

Run (from the repo root, after building the client once — `node js/build.mjs`):
    python examples/osm/viewer.py --out /path/to/osm-data [--port 8777]
then open http://localhost:8777/.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# examples/osm/ → repo root is two levels up; the package lives in python/.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "python"))
import xy  # noqa: E402
from xy import channel  # noqa: E402
from xy._ooc import open_f64  # noqa: E402

# The anywidget ESM bundle. It is built (not committed — see #214) by
# `node js/build.mjs`; the viewer errors clearly below if it is missing.
STATIC = os.path.join(_REPO_ROOT, "python", "xy", "static", "index.js")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>OSM nodes — xy out-of-core scatter</title>
<style>
  html,body{margin:0;height:100%;background:#0b0f14;color:#cdd6e0;font:13px system-ui}
  #chart{position:absolute;inset:0}
  #hud{position:absolute;left:10px;top:10px;z-index:10;background:rgba(10,14,20,.7);
       padding:8px 11px;border-radius:8px;pointer-events:none;line-height:1.5}
  b{color:#7fd7ff}
</style></head>
<body>
  <div id="hud">Loading <b id="n">…</b> OpenStreetMap nodes…<br>drag to pan · scroll to zoom</div>
  <div id="chart"></div>
<script type="module">
import { ChartView } from './index.js';

function parseFrame(ab){
  const dv=new DataView(ab); let o=0;
  const jl=dv.getUint32(o,true); o+=4;
  const content=JSON.parse(new TextDecoder().decode(new Uint8Array(ab,o,jl))); o+=jl;
  const buffers=[];
  while(o<ab.byteLength){ const bl=dv.getUint32(o,true); o+=4;
    buffers.push(new Uint8Array(ab.slice(o,o+bl))); o+=bl; }
  return {content, buffers};
}

const listeners=[];
const comm={
  send:(msg)=>{
    fetch('/msg',{method:'POST',body:JSON.stringify(msg)})
      .then(r=>r.arrayBuffer())
      .then(ab=>{ if(ab.byteLength<4) return;
        const {content,buffers}=parseFrame(ab);
        if(content && content.type) listeners.forEach(cb=>cb(content,buffers)); });
  },
  wantsViewChange:()=> true,
  onMessage:(cb)=>{ listeners.push(cb);
    return ()=>{ const i=listeners.indexOf(cb); if(i>=0) listeners.splice(i,1); }; },
};

const ab = await (await fetch('/init')).arrayBuffer();
const {content: spec, buffers} = parseFrame(ab);
spec.interaction = {...(spec.interaction||{}), _transport_view_change:true};
document.getElementById('n').textContent =
  (spec.traces?.[0]?.n_points ?? 0).toLocaleString();
new ChartView(document.getElementById('chart'), spec, buffers, comm);
</script>
</body></html>
"""


def build_figure(out_dir: str):
    xcol = open_f64(os.path.join(out_dir, "osm_lon.f64"))
    ycol = open_f64(os.path.join(out_dir, "osm_lat.f64"))
    print(f"loaded {len(xcol):,} nodes from disk (out-of-core)", flush=True)
    fig = xy.chart(xy.scatter(x=xcol, y=ycol, density=True)).figure()
    spec, bufs = fig.build_payload_split()
    spec.setdefault("interaction", {})["_transport_view_change"] = True
    # Attach the Tier-3 spatial index if built (osm-sort): deep zoom then serves
    # exact street-level detail from just the in-window points.
    idx_prefix = os.path.join(out_dir, "osm_spatial")
    if os.path.exists(idx_prefix + ".idx"):
        from xy._spatial import SpatialIndex

        fig.traces[0]._spatial_index = SpatialIndex.load(idx_prefix)
        print(f"spatial index attached ({idx_prefix}.idx)", flush=True)
    # Warm the density pyramid now (one O(N) disk scan) so the *first* pan/zoom
    # is instant instead of stalling on the lazy build. Full-domain view.
    t0 = time.perf_counter()
    tr = fig.traces[0]
    x0, x1, y0, y1 = tr.x.min, tr.x.max, tr.y.min, tr.y.max
    fig.density_view(0, x0, x1, y0, y1, 1200, 900)
    print(f"pyramid warmed in {time.perf_counter() - t0:.0f}s", flush=True)
    rep = fig.store.memory_report()
    print(
        f"canonical RAM-resident: {rep['canonical_bytes']:,} B | on disk: "
        f"{rep['canonical_mapped_bytes']:,} B",
        flush=True,
    )
    return fig, spec, bufs


def frame(content: dict, buffers) -> bytes:
    jb = json.dumps(content).encode()
    out = bytearray(struct.pack("<I", len(jb)) + jb)
    for b in buffers or []:
        mv = bytes(b)
        out += struct.pack("<I", len(mv)) + mv
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", required=True, help="dir holding osm_lon.f64 / osm_lat.f64 (see README)"
    )
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()

    if not os.path.exists(STATIC):
        raise SystemExit(
            f"render client not built: {STATIC}\n"
            "build it once from the repo root:  npm ci && node js/build.mjs"
        )

    fig, spec, bufs = build_figure(args.out)
    init_frame = frame(spec, bufs)
    lock = threading.Lock()
    with open(STATIC, "rb") as f:
        client_js = f.read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 — quiet
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/index.js":
                self._send(client_js, "text/javascript")
            elif self.path == "/init":
                self._send(init_frame, "application/octet-stream")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/msg":
                self.send_error(404)
                return
            n = int(self.headers.get("Content-Length", 0))
            content = json.loads(self.rfile.read(n) or b"{}")
            with lock:
                reply = channel.handle_message(fig, content)
            if reply is None:
                self._send(b"", "application/octet-stream")
            else:
                msg, out = reply
                self._send(frame(msg, out), "application/octet-stream")

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"\n  ▶  http://localhost:{args.port}/\n", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
