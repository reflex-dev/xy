"""Streaming-append client smoke + micro-benchmark (stdlib-only, no PyPI).

Verifies the wire-protocol §4 streaming contract from the *client's* side, in
headless Chromium against the committed standalone bundle, by hand-building
append payloads exactly the way the kernel does (sticky offsets, stable
channel domains → byte-identical prefixes):

1. **Tail-only GPU uploads.** After the first append reallocates each direct
   trace's data store with doubling headroom, every further tick must upload
   only the appended tail via `bufferSubData` — zero `bufferData` calls, tail
   bytes on the wire to the GPU instead of the full O(N) buffers.
2. **Pixel equivalence.** After N in-place appends, the canvas must be
   byte-identical to a fresh render of the final payload (the fast path is an
   optimization, never a different picture).
3. **Coalesced refinement.** At home with the payload's recorded
   `decimation_px` covering the plot, a stream of appends sends *zero* view
   re-requests; zoomed into history, a 6-tick burst coalesces to a single
   round-trip (maxWait) instead of one per tick.

Prints the measured per-tick GPU upload bytes (fast path vs the full-rebuild
equivalent) so perf changes stay tracked, not asserted from folklore (§29).

Usage: python scripts/append_stream_smoke.py [chromium-binary]
Env: XY_APPEND_SMOKE_BUNDLE overrides the bundle path (dev builds).
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

from _protocol import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "xy" / "static"
CHROMIUM_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
]

N0 = 20_000  # initial rows per direct trace
M = 200  # rows appended per tick
TICKS = 5
DECIMATED_SHIPPED = 500
DECIMATED_PX = 2048


def find_chromium() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


class Writer:
    """Packed-blob writer mirroring `_PayloadWriter` (f32 columns only)."""

    def __init__(self) -> None:
        self.cols: list[dict] = []
        self.blob = bytearray()

    def ship(self, vals, offset: float, kind: str = "float") -> int:
        raw = array("f", [float(v - offset) for v in vals]).tobytes()
        self.cols.append(
            {
                "byte_offset": len(self.blob),
                "len": len(vals),
                "offset": offset,
                "scale": 1.0,
                "kind": kind,
            }
        )
        self.blob.extend(raw)
        return len(self.cols) - 1

    def ship_scalar(self, vals) -> int:
        raw = array("f", [float(v) for v in vals]).tobytes()
        self.cols.append({"byte_offset": len(self.blob), "len": len(vals)})
        self.blob.extend(raw)
        return len(self.cols) - 1


def series(n: int):
    xs = [float(i) for i in range(n)]
    ys = [math.sin(i * 0.003) * 2.0 for i in range(n)]
    cs = [(i % 97) / 96.0 for i in range(n)]  # stays inside [0, 1]
    ss = [abs(math.sin(i * 0.05)) for i in range(n)]
    return xs, ys, cs, ss


def build_payload(n: int, x_off: float, y_off: float):
    """One full payload for `n` rows per direct trace. Offsets are the
    caller's (sticky across ticks, like `Column.suggest_offset`), so every
    payload's columns are byte-prefixes of the next one's."""
    xs, ys, cs, ss = series(n)
    w = Writer()
    hi_x = float(n)  # home range follows the data
    traces = [
        {
            "id": 0,
            "kind": "scatter",
            "name": "pts",
            "tier": "direct",
            "n_points": n,
            "n_marks": n,
            "style": {"opacity": 0.8},
            "x": w.ship(xs, x_off),
            "y": w.ship(ys, y_off),
            "color": {
                "mode": "continuous",
                "colormap": "viridis",
                "domain": [0.0, 1.0],
                "buf": w.ship_scalar(cs),
            },
            "size": {
                "mode": "continuous",
                "range_px": [2.0, 10.0],
                "domain": [0.0, 1.0],
                "buf": w.ship_scalar(ss),
            },
        },
        {
            "id": 1,
            "kind": "line",
            "name": "walk",
            "tier": "direct",
            "n_points": n,
            "n_marks": n,
            "style": {"color": "#4c78a8", "width": 1.25, "opacity": 1.0},
            "x": w.ship(xs, x_off),
            "y": w.ship([v + 3.0 for v in ys], y_off),
        },
        {
            # A big decimated line, M4'd kernel-side per payload: its shipped
            # points are screen-bounded and its decision is recorded (§28).
            "id": 2,
            "kind": "line",
            "name": "big",
            "tier": "decimated",
            "n_points": 50_000,
            "n_marks": DECIMATED_SHIPPED,
            "decimation_px": DECIMATED_PX,
            "style": {"color": "#e45756", "width": 1.0, "opacity": 1.0},
            # Payload-independent content: the client legitimately keeps the
            # stale decimated tier until the coalesced refine answers (§17),
            # so the pixel oracle needs this trace identical across ticks.
            "x": w.ship([i * (N0 / DECIMATED_SHIPPED) for i in range(DECIMATED_SHIPPED)], x_off),
            "y": w.ship([-3.0 + (i % 7) * 0.3 for i in range(DECIMATED_SHIPPED)], y_off),
        },
    ]
    spec = {
        "protocol": PROTOCOL_VERSION,
        "width": 700,
        "height": 380,
        "title": "append stream",
        "x_axis": {"kind": "linear", "label": "x", "range": [0.0, hi_x]},
        "y_axis": {"kind": "linear", "label": "y", "range": [-4.0, 6.0]},
        "traces": traces,
        "columns": w.cols,
        "backend": "none",
        "show_legend": False,
    }
    return spec, bytes(w.blob)


def main() -> None:
    bundle_path = Path(os.environ.get("XY_APPEND_SMOKE_BUNDLE", STATIC / "standalone.js"))
    standalone = bundle_path.read_text(encoding="utf-8")

    # Sticky offsets, chosen once from the initial domain like
    # Column.suggest_offset and reused for every tick's payload.
    x_off = N0 / 2.0
    y_off = 0.0
    spec0, blob0 = build_payload(N0, x_off, y_off)
    ticks = []
    for k in range(1, TICKS + 1):
        spec, blob = build_payload(N0 + k * M, x_off, y_off)
        ticks.append({"spec": spec, "blob": base64.b64encode(blob).decode()})

    # Expected steady-state tail bytes per tick: 6 f32 columns × M rows
    # (scatter x/y/color/size + line x/y); the decimated trace is unaffected.
    tail_bytes = 6 * M * 4
    full_bytes = 6 * (N0 + TICKS * M) * 4  # what a rebuild re-uploads at the end

    page = f"""<!doctype html><html><head><meta charset=utf-8><title>pending</title></head>
<body><div id=chart></div><div id=fresh></div>
<script>{standalone}</script>
<script>
const spec0={json.dumps(spec0)};
const blob0=Uint8Array.from(atob("{base64.b64encode(blob0).decode()}"),c=>c.charCodeAt(0));
const ticks={json.dumps(ticks)};
const b64=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const gl2=WebGL2RenderingContext.prototype;
const counters={{data:0,dataBytes:0,sub:0,subBytes:0}};
const origData=gl2.bufferData, origSub=gl2.bufferSubData;
gl2.bufferData=function(target,d,usage){{
  counters.data++;
  counters.dataBytes+=typeof d==="number"?d:(d&&d.byteLength||0);
  return origData.apply(this,arguments);
}};
gl2.bufferSubData=function(target,off,d){{
  counters.sub++; counters.subBytes+=(d&&d.byteLength)||0;
  return origSub.apply(this,arguments);
}};
const reset=()=>{{counters.data=0;counters.dataBytes=0;counters.sub=0;counters.subBytes=0;}};
const snap=()=>({{...counters}});
const readCanvas=(v)=>{{
  v._drawNow();
  const gl=v.gl,w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
  const px=new Uint8Array(w*h*4);
  gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
  return px;
}};
const wait=(ms)=>new Promise(r=>setTimeout(r,ms));
(async()=>{{try{{
  const v=xy.renderStandalone(document.getElementById("chart"),spec0,blob0.buffer);
  v._sampleRebinDisabled=true;
  v._drawNow();
  const comm={{sent:[],send(m){{this.sent.push(m);}}}};
  v.comm=comm;

  // --- phase A: at-home stream (tail uploads + zero view re-requests) ---
  const perTick=[];
  for(const t of ticks){{
    reset();
    v._onKernelMsg({{type:"append",affected:[0,1],spec:t.spec}},[b64(t.blob)]);
    perTick.push(snap());
    await wait(60);
  }}
  await wait(1000); // any coalesced refine timer would have fired by now
  const viewSendsHome=comm.sent.filter(m=>m.type==="view").length;
  const steady=perTick.slice(1);
  const steadyData=steady.reduce((a,c)=>a+c.data,0);
  const steadySub=steady.reduce((a,c)=>a+c.subBytes,0)/steady.length;
  const inPlace=v.gpuTraces[0].n===({N0}+{TICKS}*{M})?1:0;
  const litPx=readCanvas(v);
  let lit=0;for(let i=3;i<litPx.length;i+=4)if(litPx[i]>8)lit++;

  // --- pixel oracle: fresh render of the final payload must match ---
  const last=ticks[ticks.length-1];
  const vf=xy.renderStandalone(document.getElementById("fresh"),
    JSON.parse(JSON.stringify(last.spec)),b64(last.blob).buffer);
  vf._sampleRebinDisabled=true;
  const freshPx=readCanvas(vf);
  const incPx=readCanvas(v);
  let mismatch=0;
  if(freshPx.length!==incPx.length)mismatch=-1;
  else for(let i=0;i<freshPx.length;i++)if(freshPx[i]!==incPx[i])mismatch++;
  vf.destroy();

  // --- phase B: zoomed into history — refines coalesce, never per tick ---
  v.view=v._viewFrom({{x0:100,x1:900}}); // strictly inside: hold, not follow
  comm.sent.length=0;
  for(let i=0;i<6;i++){{
    const t=ticks[i%ticks.length];
    v._onKernelMsg({{type:"append",affected:[0,1],spec:t.spec}},[b64(t.blob)]);
    await wait(60);
  }}
  await wait(1000);
  const viewSendsZoomed=comm.sent.filter(m=>m.type==="view").length;

  document.title="XY_OK "+JSON.stringify({{
    warmData:perTick[0].data,warmBytes:perTick[0].dataBytes,
    steadyData,steadySubBytes:Math.round(steadySub),
    inPlace,lit,mismatch,viewSendsHome,viewSendsZoomed,
  }});
}}catch(e){{document.title="XY_ERROR "+(e.stack||e.message)}}}})();
</script></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "append_smoke.html"
        p.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [
                find_chromium(),
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--virtual-time-budget=8000",
                "--dump-dom",
                p.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    m = re.search(r"<title>([^<]*)</title>", out.stdout)
    title = m.group(1) if m else "(none)"
    print("probe:", title)
    if not title.startswith("XY_OK"):
        print(out.stderr[-2000:], file=sys.stderr)
        raise SystemExit("append stream smoke failed to run")
    stats = json.loads(title[len("XY_OK ") :].replace("&quot;", '"'))

    print(
        f"per-tick GPU upload: steady {stats['steadySubBytes']} B via bufferSubData "
        f"(full rebuild would re-upload {full_bytes} B: "
        f"{full_bytes / max(stats['steadySubBytes'], 1):.0f}x more); "
        f"view round-trips: home={stats['viewSendsHome']}/{TICKS} ticks, "
        f"zoomed={stats['viewSendsZoomed']}/6 ticks"
    )
    if not stats["inPlace"]:
        raise SystemExit("append did not extend the GPU trace to the streamed row count")
    if stats["steadyData"] != 0:
        raise SystemExit(
            f"steady-state appends reallocated GPU buffers ({stats['steadyData']} bufferData "
            "calls after warm-up; expected tail-only bufferSubData)"
        )
    if not tail_bytes * 0.9 <= stats["steadySubBytes"] <= tail_bytes * 1.6:
        raise SystemExit(
            f"steady-state upload {stats['steadySubBytes']} B/tick is not tail-sized "
            f"(expected ~{tail_bytes} B)"
        )
    if stats["mismatch"] != 0:
        raise SystemExit(
            f"incremental appends diverged from a fresh render ({stats['mismatch']} bytes differ)"
        )
    if stats["lit"] < 500:
        raise SystemExit(f"suspiciously few lit pixels after appends ({stats['lit']})")
    if stats["viewSendsHome"] != 0:
        raise SystemExit(
            f"at-home stream sent {stats['viewSendsHome']} view re-requests; the recorded "
            f"decimation_px already covers the plot, expected 0"
        )
    if not 1 <= stats["viewSendsZoomed"] <= 2:
        raise SystemExit(
            f"zoomed 6-tick burst sent {stats['viewSendsZoomed']} view re-requests; "
            "expected a single coalesced round-trip (maxWait)"
        )
    print("append stream smoke OK: tail-only uploads + pixel-identical + coalesced refines")


if __name__ == "__main__":
    main()
