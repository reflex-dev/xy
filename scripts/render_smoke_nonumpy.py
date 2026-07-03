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
    # A line (sine + spike) and a scatter, mirroring Figure's spec shape.
    n = 2000
    xs = [float(i) for i in range(n)]
    ys = [math.sin(i * 0.02) for i in range(n)]
    ys[1000] = 5.0

    cols = []
    blob = bytearray()

    def ship(vals):
        offset = (min(vals) + max(vals)) / 2.0
        raw = encode_f32(vals, offset)
        meta = {"byte_offset": len(blob), "len": len(vals), "offset": offset, "scale": 1.0, "kind": "float"}
        cols.append(meta)
        blob.extend(raw)
        return len(cols) - 1

    traces = [
        {"id": 0, "kind": "line", "name": "sine", "tier": "direct", "n_points": n,
         "style": {"color": "#4c78a8", "width": 1.5, "opacity": 1.0},
         "x": ship(xs), "y": ship(ys)},
        {"id": 1, "kind": "scatter", "name": "pts", "tier": "direct", "n_points": n // 20,
         "style": {"color": "#f58518", "size": 4.0, "opacity": 0.8},
         "x": ship(xs[::20]), "y": ship([v + 2.0 for v in ys[::20]])},
    ]
    spec = {
        "protocol": 1, "width": 800, "height": 400, "title": "nonumpy smoke",
        "x_axis": {"kind": "linear", "label": "i", "range": [0.0, float(n)]},
        "y_axis": {"kind": "linear", "label": "y", "range": [-3.0, 8.0]},
        "traces": traces, "columns": cols, "backend": "none",
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
    document.title=`FC_OK lit=${{lit}} total=${{w*h}} labels=${{labels}}`;
  }}catch(e){{document.title="FC_ERROR "+e.message}}}},200);
}}catch(e){{document.title="FC_ERROR "+e.message}}
</script></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.html"
        p.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [find_chromium(), "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
             "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
             "--virtual-time-budget=4000", "--dump-dom", p.as_uri()],
            capture_output=True, text=True, timeout=120,
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
    frac = lit / max(total, 1)
    print(f"lit fraction: {frac:.3%}, DOM chrome nodes: {labels}")
    if not (0.001 < frac < 0.9):
        raise SystemExit(f"suspicious lit fraction {frac}")
    if labels < 6:
        raise SystemExit(f"too few DOM tick labels: {labels}")
    print("render smoke OK (no numpy)")


if __name__ == "__main__":
    main()
