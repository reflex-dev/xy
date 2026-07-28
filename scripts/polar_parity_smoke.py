"""Bind the GLSL polar transform to the shared fixtures — the client half of
the contract in spec/design/polar-axes.md §4.

`tests/test_polar_transform.py` binds `_svg._PolarProjection` (and through it
both static exporters) to `tests/fixtures/polar_transform.json`. This probe
binds the OTHER implementation — the real `xyPolarPos` in the shipped bundle,
not a JS mirror of it — by rendering one scatter point per fixture sample in a
unique solid colour, reading the pixels back, and comparing each colour's
centroid against the fixture value.

The fixture stores pixel positions for its own authored plot rect, while the
client computes a rect of its own; the two are reconciled without a third copy
of the transform because a fixture point's offset from the centre, in units of
the disc radius, is rect-independent: `(px - cx, py - cy) / R` depends only on
the axis config and (theta, r). The probe rescales that unit-disc offset to the
runtime canvas.

Points are placed at 60% of each fixture radius so no sprite clips at the
canvas edge (a half-clipped disc's centroid shifts inward, which would read as
a transform error). Under a linear radial scale the unit-disc offset scales
exactly with the normalized radius, so the expected position stays exact.

Stdlib-only, like the other smoke probes: runs in the no-PyPI CI lane.
"""

from __future__ import annotations

import base64
import json
import math
import re
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

from _protocol import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "xy" / "static"
FIXTURES = ROOT / "tests" / "fixtures" / "polar_transform.json"
CHROMIUM_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
]

# One saturated, unambiguous colour per fixture point (max 6 points per case).
COLORS = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff"]

# Test radius fraction (see module docstring) and centroid tolerance in px.
# The sprite is an antialiased disc, so its lit-pixel centroid sits within a
# fraction of a pixel of its centre; 1.5 px absorbs that plus f32 encoding.
RADIUS_FRACTION = 0.6
TOLERANCE_PX = 1.5


def find_chromium() -> str:
    import shutil

    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


def build_case_payload(case: dict) -> tuple[dict, bytes, list[dict]]:
    """One spec per fixture case: one single-point scatter trace per sample."""
    cfg = case["config"]
    r_lo, r_hi = cfg["r_range"]
    span = (r_hi - r_lo) or 1.0
    turn = 360.0 if cfg["unit"] == "degrees" else 2.0 * math.pi

    cols: list[dict] = []
    blob = bytearray()

    def ship(value: float) -> int:
        cols.append(
            {"byte_offset": len(blob), "len": 1, "offset": 0.0, "scale": 1.0, "kind": "float"}
        )
        blob.extend(array("f", [float(value)]).tobytes())
        return len(cols) - 1

    traces = []
    expected = []
    fx_plot = case["plot"]
    fx_cx = fx_plot["x"] + fx_plot["w"] / 2.0
    fx_cy = fx_plot["y"] + fx_plot["h"] / 2.0
    fx_radius = min(fx_plot["w"], fx_plot["h"]) / 2.0
    for i, point in enumerate(case["points"]):
        rn = (point["r"] - r_lo) / span
        test_r = r_lo + span * rn * RADIUS_FRACTION
        # Unit-disc offset of the fixture point, scaled to the test radius.
        ux = (point["px"] - fx_cx) / fx_radius * RADIUS_FRACTION
        uy = (point["py"] - fx_cy) / fx_radius * RADIUS_FRACTION
        expected.append({"ux": ux, "uy": uy, "color": COLORS[i]})
        traces.append(
            {
                "id": i,
                "kind": "scatter",
                "name": f"p{i}",
                "tier": "direct",
                "n_points": 1,
                # Scatter colour rides the channel dict — the client reads
                # `t.color.color`, and `style.color` is the legend swatch.
                "color": {"color": COLORS[i]},
                "size": {"size": 11.0},
                "style": {"color": COLORS[i], "size": 11.0, "opacity": 1.0},
                "x": ship(point["theta"]),
                "y": ship(test_r),
            }
        )

    spec = {
        "protocol": PROTOCOL_VERSION,
        "width": 420,
        "height": 380,
        "coords": "polar",
        "x_axis": {
            "kind": "linear",
            "range": [0.0, turn],
            "theta_unit": cfg["unit"],
            "theta_zero": cfg["zero"],
            "theta_direction": cfg["direction"],
        },
        "y_axis": {"kind": "linear", "range": [r_lo, r_hi]},
        "traces": traces,
        "columns": cols,
        "backend": "none",
    }
    spec["axes"] = {"x": spec["x_axis"], "y": spec["y_axis"]}
    return spec, bytes(blob), expected


PROBE_JS = """
setTimeout(()=>{try{
  v._drawNow();
  const gl=v.gl,w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
  const px=new Uint8Array(w*h*4);
  gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
  const targets=TARGETS;
  const sums=targets.map(()=>({x:0,y:0,n:0}));
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const o=(y*w+x)*4;
    if(px[o+3]<32)continue;
    for(let t=0;t<targets.length;t++){
      const c=targets[t];
      if(Math.abs(px[o]-c[0])<48&&Math.abs(px[o+1]-c[1])<48&&Math.abs(px[o+2]-c[2])<48){
        sums[t].x+=x;sums[t].y+=y;sums[t].n++;
      }
    }
  }
  const dpr=v.dpr||1;
  const out=sums.map(s=>s.n?[s.x/s.n/dpr,(h-1-s.y/s.n)/dpr,s.n]:[NaN,NaN,0]);
  document.title="XY_OK plot="+v.plot.w+"x"+v.plot.h+" pts="+JSON.stringify(out);
}catch(e){document.title="XY_ERROR "+(e.stack||e.message)}},200);
"""


def run_case(chromium: str, standalone: str, case: dict) -> list[str]:
    spec, blob, expected = build_case_payload(case)
    targets = [
        [int(e["color"][1:3], 16), int(e["color"][3:5], 16), int(e["color"][5:7], 16)]
        for e in expected
    ]
    page = f"""<!doctype html><html><head><meta charset=utf-8><title>pending</title></head>
<body><div id=chart></div>
<script>{standalone}</script>
<script>
const spec={json.dumps(spec)};
const bytes=Uint8Array.from(atob("{base64.b64encode(blob).decode()}"),c=>c.charCodeAt(0));
try{{
  const v=xy.renderStandalone(document.getElementById("chart"),spec,bytes);
  {PROBE_JS.replace("TARGETS", json.dumps(targets))}
}}catch(e){{document.title="XY_ERROR "+(e.stack||e.message)}}
</script></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "polar_parity.html"
        p.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [
                chromium,
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
    if not title.startswith("XY_OK"):
        print(out.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"{case['name']}: render failed: {title[:400]}")

    plot_w, plot_h = map(float, re.search(r"plot=([\d.]+)x([\d.]+)", title).groups())
    observed = json.loads(re.search(r"pts=(\[.*\])", title).group(1))
    radius = min(plot_w, plot_h) / 2.0
    cx, cy = plot_w / 2.0, plot_h / 2.0

    failures = []
    for e, (ox, oy, n) in zip(expected, observed, strict=True):
        if not n:
            failures.append(f"{case['name']}: no pixels found for {e['color']}")
            continue
        want_x = cx + e["ux"] * radius
        want_y = cy + e["uy"] * radius
        dx, dy = ox - want_x, oy - want_y
        if math.hypot(dx, dy) > TOLERANCE_PX:
            failures.append(
                f"{case['name']}: {e['color']} at ({ox:.2f},{oy:.2f}) "
                f"expected ({want_x:.2f},{want_y:.2f}) — off by {math.hypot(dx, dy):.2f}px"
            )
    return failures


def main() -> None:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    standalone = (STATIC / "standalone.js").read_text(encoding="utf-8")
    chromium = find_chromium()
    failures: list[str] = []
    for case in cases:
        case_failures = run_case(chromium, standalone, case)
        status = "ok" if not case_failures else f"{len(case_failures)} FAILED"
        print(f"  {case['name']:<24} {len(case['points'])} points  {status}")
        failures.extend(case_failures)
    if failures:
        print()
        for f in failures:
            print("FAIL:", f)
        raise SystemExit(f"{len(failures)} polar parity failures")
    print("polar GLSL parity: all fixture cases match")


if __name__ == "__main__":
    main()
