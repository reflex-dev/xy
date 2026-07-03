"""Headless render smoke that needs neither numpy nor PyPI.

Builds a payload by hand (stdlib `array` + `struct`) in exactly the wire shape
`Figure.build_payload` emits, drives the pre-installed Chromium against the
standalone JS bundle, and reads back a lit-pixel count via gl.readPixels. This
verifies the *render client* — the half cargo can't touch — in a locked-down
environment. The numpy-backed `scripts/smoke_render.py` supersedes it once deps
are installable.
"""

from __future__ import annotations

import base64
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "fastcharts" / "static"
CHROMIUM_CANDIDATES = ["/opt/pw-browsers/chromium", "chromium", "chromium-browser", "google-chrome"]


def find_chromium() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


def encode_f32(vals, offset):  # noqa: ANN001
    return array("f", [float(v - offset) for v in vals]).tobytes()


def build_payload():
    # Exercises the full scatter path: a line, a scatter with continuous color
    # + variable size, and a Tier-2 density surface — all in Figure's wire shape.
    n = 2000
    xs = [float(i) for i in range(n)]
    ys = [math.sin(i * 0.02) for i in range(n)]
    ys[1000] = 5.0

    cols = []
    blob = bytearray()

    def ship(vals, offset=None, kind="float"):
        off = ((min(vals) + max(vals)) / 2.0) if offset is None else offset
        raw = encode_f32(vals, off)
        cols.append(
            {"byte_offset": len(blob), "len": len(vals), "offset": off, "scale": 1.0, "kind": kind}
        )
        blob.extend(raw)
        return len(cols) - 1

    def ship_scalar(vals):
        raw = array("f", [float(v) for v in vals]).tobytes()
        cols.append({"byte_offset": len(blob), "len": len(vals)})
        blob.extend(raw)
        return len(cols) - 1

    # continuous color = normalized index; variable size = |sin|.
    m = n // 20
    cvals = [i / (m - 1) for i in range(m)]
    svals = [abs(math.sin(i * 0.4)) for i in range(m)]

    # A density grid (8×6) with a hotspot, hand-built.
    gw, gh = 8, 6
    grid = [0.0] * (gw * gh)
    grid[gh // 2 * gw + gw // 2] = 500.0
    for i in range(gw * gh):
        grid[i] += i % 3
    density_buf = ship_scalar(grid)

    traces = [
        {
            "id": 0,
            "kind": "line",
            "name": "sine",
            "tier": "direct",
            "n_points": n,
            "style": {"color": "#4c78a8", "width": 1.5, "opacity": 1.0},
            "x": ship(xs),
            "y": ship(ys),
        },
        {
            "id": 1,
            "kind": "scatter",
            "name": "pts",
            "tier": "direct",
            "n_points": m,
            "style": {"opacity": 0.85},
            "x": ship(xs[::20]),
            "y": ship([v + 2.0 for v in ys[::20]]),
            "color": {
                "mode": "continuous",
                "colormap": "viridis",
                "domain": [0.0, 1.0],
                "buf": ship_scalar(cvals),
            },
            "size": {"mode": "continuous", "range_px": [3.0, 16.0], "buf": ship_scalar(svals)},
        },
        {
            "id": 2,
            "kind": "scatter",
            "name": "density",
            "tier": "density",
            "n_points": 1_000_000,
            "style": {"opacity": 1.0},
            "density": {
                "buf": density_buf,
                "w": gw,
                "h": gh,
                "max": 502.0,
                "colormap": "magma",
                "x_range": [0.0, float(n)],
                "y_range": [-3.0, 8.0],
                "channels_dropped": False,
            },
        },
    ]
    spec = {
        "protocol": 2,
        "width": 800,
        "height": 400,
        "title": "nonumpy smoke",
        "x_axis": {"kind": "linear", "label": "i", "range": [0.0, float(n)]},
        "y_axis": {"kind": "linear", "label": "y", "range": [-3.0, 8.0]},
        "traces": traces,
        "columns": cols,
        "backend": "none",
    }
    return spec, bytes(blob)


def main() -> None:
    standalone = (STATIC / "standalone.js").read_text(encoding="utf-8")
    spec, blob = build_payload()
    # sanity: blob is 4 bytes per shipped f32
    assert len(blob) == sum(c["len"] for c in spec["columns"]) * 4
    struct.unpack_from("<f", blob, 0)  # decodes as little-endian f32

    page = f"""<!doctype html><html><head><meta charset=utf-8><title>pending</title></head>
<body><div id=chart></div>
<script>{standalone}</script>
<script>
const spec={json.dumps(spec)};
const bytes=Uint8Array.from(atob("{base64.b64encode(blob).decode()}"),c=>c.charCodeAt(0));
try{{
  const v=fastcharts.renderStandalone(document.getElementById("chart"),spec,bytes.buffer);
  setTimeout(()=>{{try{{
    v._drawNow();
    const gl=v.gl,w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,px=new Uint8Array(w*h*4);
    gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
    let lit=0;for(let i=3;i<px.length;i+=4)if(px[i]>8)lit++;
    const labels=document.querySelectorAll(".fastcharts div").length;
    // Picking: scan the plot for any pickable scatter point (GPU ID readback).
    let hits=0, sampleRow=null;
    for(let sx=4; sx<v.plot.w && hits<1; sx+=3){{
      for(let sy=4; sy<v.plot.h; sy+=3){{
        const hit=v._pickAt(sx,sy);
        if(hit){{hits++; sampleRow=v._localRow(hit); break;}}
      }}
    }}
    const hasXY = sampleRow && sampleRow.x!==undefined ? 1 : 0;
    // Selection: box-select the left half in data space (standalone -> local mask).
    v._selectLocal(-1e9, 1e9, -1e9, 1e9);  // select everything first
    const selAll = v._selectionCount;
    v._clearSelection();
    v._selectLocal(0, 1000, -3, 8);        // a sub-range
    const selSome = v._selectionCount;
    const active = v.gpuTraces.some(g=>g.selActive) ? 1 : 0;
    // Modebar: button row present, and its zoom controls actually move the view.
    const bar = v._modebar;
    const btns = bar ? bar.querySelectorAll("button").length : 0;
    const spanX = () => v.view.x1 - v.view.x0;
    const s0 = spanX();
    v._zoomBy(0.5);                 // zoom in -> span shrinks
    const zin = spanX() < s0 ? 1 : 0;
    v._zoomBy(2);                   // back out
    v._zoomToBox([10,0],[20,5]);    // box-zoom fits the rectangle
    const boxOk = (Math.abs(v.view.x0-10)<1e-6 && Math.abs(v.view.x1-20)<1e-6) ? 1 : 0;
    v.view = {{...v.view0}};
    v._setDragMode("zoom");
    const zmode = (v.dragMode==="zoom" && v.canvas.style.cursor==="crosshair") ? 1 : 0;
    v._setDragMode("pan");
    document.title=`FC_OK lit=${{lit}} total=${{w*h}} labels=${{labels}} pick=${{hits}} row=${{hasXY}} selAll=${{selAll}} selSome=${{selSome}} active=${{active}} btns=${{btns}} zin=${{zin}} box=${{boxOk}} zmode=${{zmode}}`;
  }}catch(e){{document.title="FC_ERROR "+e.message}}}},200);
}}catch(e){{document.title="FC_ERROR "+e.message}}
</script></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.html"
        p.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [
                find_chromium(),
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--virtual-time-budget=4000",
                "--dump-dom",
                p.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    m = re.search(r"<title>([^<]*)</title>", out.stdout)
    title = m.group(1) if m else "(none)"
    print("probe:", title)
    if not title.startswith("FC_OK"):
        print(out.stderr[-2000:], file=sys.stderr)
        raise SystemExit("render failed")
    lit = int(re.search(r"lit=(\d+)", title).group(1))
    total = int(re.search(r"total=(\d+)", title).group(1))
    labels = int(re.search(r"labels=(\d+)", title).group(1))
    pick = int(re.search(r"pick=(\d+)", title).group(1))
    rowok = int(re.search(r"row=(\d+)", title).group(1))
    sel_all = int(re.search(r"selAll=(\d+)", title).group(1))
    sel_some = int(re.search(r"selSome=(\d+)", title).group(1))
    active = int(re.search(r"active=(\d+)", title).group(1))
    btns = int(re.search(r"btns=(\d+)", title).group(1))
    zin = int(re.search(r"zin=(\d+)", title).group(1))
    box = int(re.search(r"box=(\d+)", title).group(1))
    zmode = int(re.search(r"zmode=(\d+)", title).group(1))
    frac = lit / max(total, 1)
    print(
        f"lit fraction: {frac:.3%}, DOM chrome nodes: {labels}, pick hits: {pick}, "
        f"row-decoded: {rowok}, select all/sub: {sel_all}/{sel_some}, mask active: {active}, "
        f"modebar btns: {btns}, zoom-in: {zin}, box-zoom: {box}, zoom-mode: {zmode}"
    )
    if not (0.001 < frac < 0.95):
        raise SystemExit(f"suspicious lit fraction {frac}")
    if labels < 6:
        raise SystemExit(f"too few DOM tick labels: {labels}")
    if pick < 1:
        raise SystemExit("GPU picking found no scatter point")
    if rowok < 1:
        raise SystemExit("picked point did not decode to x/y (standalone hover)")
    if sel_all < 1:
        raise SystemExit("box-select over everything selected nothing")
    if not (0 < sel_some <= sel_all):
        raise SystemExit(f"sub-range selection implausible: {sel_some} of {sel_all}")
    if active != 1:
        raise SystemExit("selection mask did not activate")
    if btns < 5:
        raise SystemExit(f"modebar missing buttons: {btns}")
    if zin != 1:
        raise SystemExit("modebar zoom-in did not shrink the view span")
    if box != 1:
        raise SystemExit("box-zoom did not fit the dragged rectangle")
    if zmode != 1:
        raise SystemExit("drag-mode toggle did not switch to box-zoom")
    print(
        "render smoke OK (no numpy): line + colored/sized scatter + density + "
        "picking + box-select + modebar/box-zoom"
    )


if __name__ == "__main__":
    main()
