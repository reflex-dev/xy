"""Picking boundary-ID smoke: high trace slots + exact point indices (§17).

The pick encoding once split IDs into a 24-bit point index and an 8-bit trace
slot; the +1 background-sentinel shift saturated the alpha byte, so trace slot
255 aliased onto 254, and point indices wrapped above 2^24. The fix is one
global 32-bit id space (`u_pick_base` + gl_VertexID). This smoke pins the
boundary behavior an ordinary nonblank-pixel gate cannot see:

- a 256-trace figure must pick slots 0, 127, 253, 254, and **255** each back
  to the correct trace id (255 is the exact alias the old encoding produced);
- a 70,000-point trace must pick an exact high index through the range
  decode, and a second trace stacked after it must come back with its own
  (trace, local-index) pair, proving the global->local mapping;
- steady hover must NOT re-render the pick framebuffer per hover-target
  change (hover highlights live in the color pass), while a view change must
  still refresh it and keep picks correct — the pick cache contract.

Stdlib-only (no numpy, no PyPI), headless Chromium via --dump-dom — the same
harness conventions as render_smoke_nonumpy.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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

GRID = 16  # 16x16 = 256 one-point traces
N_BIG = 70_000
BIG_PICK_INDEX = 69_999


def find_chromium() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


def build_payload():
    cols = []
    blob = bytearray()

    def ship(vals):
        cols.append(
            {
                "byte_offset": len(blob),
                "len": len(vals),
                "offset": 0.0,
                "scale": 1.0,
                "kind": "float",
            }
        )
        blob.extend(array("f", [float(v) for v in vals]).tobytes())
        return len(cols) - 1

    traces = []
    # 256 one-point traces on a grid strictly inside the [0,1] view so the
    # enlarged pick targets (>=6px) of neighbors never overlap at 900x420.
    for i in range(GRID * GRID):
        gx = (i % GRID + 0.5) / GRID
        gy = (i // GRID + 0.5) / GRID
        traces.append(
            {
                "id": i,
                "kind": "scatter",
                "name": None,
                "tier": "direct",
                "n_points": 1,
                "style": {"opacity": 1.0},
                "x": ship([gx]),
                "y": ship([gy]),
            }
        )
    spec = {
        "protocol": 3,
        "width": 900,
        "height": 420,
        "title": None,
        "show_legend": False,
        "x_axis": {"kind": "linear", "label": "x", "range": [0.0, 1.0]},
        "y_axis": {"kind": "linear", "label": "y", "range": [0.0, 1.0]},
        "traces": traces,
        "columns": cols,
        "backend": "none",
    }

    # Second figure: two stacked direct traces; the first is large so the
    # second's global pick range starts deep into the id space.
    cols2 = []
    blob2 = bytearray()

    def ship2(vals):
        cols2.append(
            {
                "byte_offset": len(blob2),
                "len": len(vals),
                "offset": 0.0,
                "scale": 1.0,
                "kind": "float",
            }
        )
        blob2.extend(array("f", [float(v) for v in vals]).tobytes())
        return len(cols2) - 1

    # Big trace: points along y=0.25, except the probe target parked alone at
    # (0.75, 0.75). Second trace: one point at (0.25, 0.75) — its global id is
    # 1 + N_BIG, exercising the range decode past the first trace.
    xs = [0.02 + 0.6 * (i / N_BIG) for i in range(N_BIG)]
    ys = [0.25] * N_BIG
    xs[BIG_PICK_INDEX] = 0.75
    ys[BIG_PICK_INDEX] = 0.75
    spec2 = {
        "protocol": 3,
        "width": 900,
        "height": 420,
        "title": None,
        "show_legend": False,
        "x_axis": {"kind": "linear", "label": "x", "range": [0.0, 1.0]},
        "y_axis": {"kind": "linear", "label": "y", "range": [0.0, 1.0]},
        "traces": [
            {
                "id": 0,
                "kind": "scatter",
                "name": None,
                "tier": "direct",
                "n_points": N_BIG,
                "style": {"opacity": 1.0},
                "x": ship2(xs),
                "y": ship2(ys),
            },
            {
                "id": 1,
                "kind": "scatter",
                "name": None,
                "tier": "direct",
                "n_points": 1,
                "style": {"opacity": 1.0},
                "x": ship2([0.25]),
                "y": ship2([0.75]),
            },
        ],
        "columns": cols2,
        "backend": "none",
    }
    return spec, bytes(blob), spec2, bytes(blob2)


PROBE = """
<script>
(() => {
  const b64ToBuf = (b64) => {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  };
  const fail = (msg) => { document.title = "FC_FAIL " + msg; };
  try {
    const v = xy.renderStandalone(document.getElementById("grid"), SPEC, b64ToBuf(BLOB));
    v._drawNow();
    // CSS position of trace i's point inside the plot rect.
    const cssOf = (i) => {
      const gx = (i % GRID + 0.5) / GRID, gy = (Math.floor(i / GRID) + 0.5) / GRID;
      return [gx * v.plot.w, (1 - gy) * v.plot.h];
    };
    const slots = [0, 127, 253, 254, 255];
    const got = slots.map((i) => {
      const [cx, cy] = cssOf(i);
      const hit = v._pickAt(cx, cy);
      return hit ? [hit.trace, hit.index] : null;
    });
    for (let k = 0; k < slots.length; k++) {
      const g = got[k];
      if (!g) return fail(`slot ${slots[k]}: no hit`);
      if (g[0] !== slots[k]) return fail(`slot ${slots[k]}: picked trace ${g[0]}`);
      if (g[1] !== 0) return fail(`slot ${slots[k]}: index ${g[1]}`);
    }

    const v2 = xy.renderStandalone(document.getElementById("two"), SPEC2, b64ToBuf(BLOB2));
    v2._drawNow();
    const hitBig = v2._pickAt(0.75 * v2.plot.w, 0.25 * v2.plot.h);
    if (!hitBig) return fail("big: no hit");
    if (hitBig.trace !== 0 || hitBig.index !== BIG_PICK_INDEX)
      return fail(`big: got trace ${hitBig.trace} index ${hitBig.index}`);
    const hitSecond = v2._pickAt(0.25 * v2.plot.w, 0.25 * v2.plot.h);
    if (!hitSecond) return fail("second: no hit");
    if (hitSecond.trace !== 1 || hitSecond.index !== 0)
      return fail(`second: got trace ${hitSecond.trace} index ${hitSecond.index}`);

    // Pick-cache contract: a hover sweep across distinct targets must render
    // the pick framebuffer at most once, with the scheduled highlight frame
    // actually painted between moves; a view change must then refresh the
    // cache. rAF is stubbed with a drainable queue (the render_smoke pattern)
    // because bare rAF does not tick under --virtual-time-budget --dump-dom.
    let pickRenders = 0;
    const renderPick0 = v._renderPick;
    v._renderPick = function (...a) { pickRenders++; return renderPick0.apply(this, a); };
    const rafQ = [];
    const realRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = (cb) => { rafQ.push(cb); return rafQ.length; };
    const frame = () => { for (const cb of rafQ.splice(0)) cb(performance.now()); };
    // The initial render leaves a frame pending in the REAL rAF, which never
    // fires under --virtual-time-budget; draw() would coalesce into it
    // forever. Paint it out and clear the handle so scheduling goes through
    // the drainable stub.
    v._drawNow();
    v._raf = null;
    const rect = v.canvas.getBoundingClientRect();
    const hoverAt = (i) => {
      const [cx, cy] = cssOf(i);
      v._hover({ clientX: rect.left + cx, clientY: rect.top + cy });
    };
    v._pickDirty = true; // start from a known-dirty state
    for (const i of [0, 17, 34, 17, 255]) {
      hoverAt(i); // 5 moves, 5 target changes
      frame(); // paint the scheduled hover-highlight frame
    }
    const sweepRenders = pickRenders;
    if (sweepRenders !== 1) {
      window.requestAnimationFrame = realRaf;
      return fail(`hover sweep rendered pick ${sweepRenders}x (want 1)`);
    }
    // Zoom out slightly: the next pick must re-render and still resolve
    // correctly in the new view.
    v._setView({ x0: -0.1, x1: 1.1, y0: -0.1, y1: 1.1 }, { animate: false, request: false });
    frame(); // the view-change frame invalidates the pick cache
    const zx = ((0.5 / GRID + 0.1) / 1.2) * v.plot.w; // trace 0 in the new view
    const zy = (1 - (0.5 / GRID + 0.1) / 1.2) * v.plot.h;
    const hitZoomed = v._pickAt(zx, zy);
    window.requestAnimationFrame = realRaf;
    if (pickRenders !== 2)
      return fail(`view change: pick rendered ${pickRenders}x total (want 2)`);
    if (!hitZoomed || hitZoomed.trace !== 0)
      return fail(`view change: picked ${hitZoomed && hitZoomed.trace} (want 0)`);
    v._renderPick = renderPick0;

    document.title = `FC_OK slots=${slots.join(",")} big=${hitBig.index} second=${hitSecond.trace}/${hitSecond.index} hoverPickRenders=${sweepRenders} viewRefresh=1`;
  } catch (e) {
    fail(String((e && e.stack) || e).slice(0, 300));
  }
})();
</script>
"""


def main() -> None:
    standalone = (STATIC / "standalone.js").read_text(encoding="utf-8")
    spec, blob, spec2, blob2 = build_payload()
    import base64

    html = (
        "<!doctype html><html><head><meta charset=utf-8>"
        "<script>window.onerror=(m,s,l,c)=>{document.title='FC_FAIL pageerror '+m+' @'+l+':'+c};</script>"
        "</head><body>"
        '<div id="grid"></div><div id="two"></div>'
        f"<script>{standalone}</script>"
        f"<script>const GRID={GRID};const BIG_PICK_INDEX={BIG_PICK_INDEX};"
        f"const SPEC={json.dumps(spec)};"
        f'const BLOB="{base64.b64encode(blob).decode()}";'
        f"const SPEC2={json.dumps(spec2)};"
        f'const BLOB2="{base64.b64encode(blob2).decode()}";</script>'
        f"{PROBE}</body></html>"
    )
    exe = find_chromium()
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "pick.html"
        page.write_text(html, encoding="utf-8")
        out = subprocess.run(
            [
                exe,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--virtual-time-budget=8000",
                "--dump-dom",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    import re

    m = re.search(r"<title>(.*?)</title>", out.stdout, re.S | re.I)
    title = m.group(1).strip() if m else "(no title)"
    if not title.startswith("FC_OK"):
        raise SystemExit(f"pick boundary smoke FAILED: {title}")
    print(f"pick boundary smoke OK: {title[6:]}")


if __name__ == "__main__":
    main()
