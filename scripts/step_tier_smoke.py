"""Step traces must stay step-shaped through kernel tier updates.

Step geometry is expanded client-side after LOD (the canonical columns stay
compact), so both upload paths — the initial build and the `tier_update`
refinement that replaces the vertex buffers on zoom — have to run the same
expansion. This gate renders a decimated `step` chart in headless Chromium,
feeds the view a synthetic tier_update exactly as the kernel would ship it,
and asserts the re-uploaded vertex stream still contains the step risers.

Usage: python scripts/step_tier_smoke.py [chromium-binary]
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import xy as fc
from xy.export import _bundled_js

CHROMIUM_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
]

REFINED_POINTS = 1000


def find_chromium() -> str:
    import shutil

    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium binary found; pass one as argv[1]")


def build_page() -> str:
    n = 500_000
    x = np.arange(n, dtype=np.float64)
    rng = np.random.default_rng(7)
    y = np.cumsum(rng.normal(size=n))
    chart = fc.chart(fc.step(x, y, name="steps", where="post"), title="step tier smoke")
    spec, blob = chart.figure().build_payload()
    assert spec["traces"][0]["tier"] == "decimated", spec["traces"][0]["tier"]
    assert spec["traces"][0]["style"].get("step") == "post"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>pending</title></head>
<body><div id="chart"></div>
<script>{_bundled_js("standalone")}</script>
<script>
  const spec = {json.dumps(spec)};
  const bytes = Uint8Array.from(atob("{base64.b64encode(blob).decode()}"), c => c.charCodeAt(0));
  function countDupes(a) {{
    if (!a) return -1;
    let d = 0;
    for (let i = 1; i < a.length; i++) if (a[i] === a[i - 1]) d++;
    return d;
  }}
  try {{
    const view = xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
    setTimeout(() => {{
      try {{
        const g = view.gpuTraces[0];
        const before = {{ n: g.n, dupes: countDupes(g._dashX) }};
        // Synthetic refined window: raw polyline points, shaped exactly like a
        // kernel tier_update after zoom-driven re-decimation.
        const k = {REFINED_POINTS};
        const xs = new Float32Array(k), ys = new Float32Array(k);
        for (let i = 0; i < k; i++) {{ xs[i] = i; ys[i] = Math.sin(i * 0.01); }}
        const msg = {{
          type: "tier_update", seq: view.seq,
          traces: [{{ id: g.trace.id,
            x: {{ buf: 0, len: k, offset: 0, scale: 1 }},
            y: {{ buf: 1, len: k, offset: 0, scale: 1 }} }}],
        }};
        view._onKernelMsg(msg, [xs.buffer, ys.buffer]);
        const after = {{ n: g.n, dupes: countDupes(g._dashX) }};
        document.title = `FC_OK before_n=${{before.n}} before_dupes=${{before.dupes}} ` +
          `after_n=${{after.n}} after_dupes=${{after.dupes}}`;
      }} catch (e) {{ document.title = "FC_ERROR " + e.message; }}
    }}, 200);
  }} catch (e) {{ document.title = "FC_ERROR " + e.message; }}
</script></body></html>"""


def main() -> None:
    chromium = find_chromium()
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "probe.html"
        page.write_text(build_page(), encoding="utf-8")
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
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    m = re.search(r"<title>([^<]*)</title>", out.stdout)
    title = m.group(1) if m else "(no title in DOM dump)"
    print("probe:", title)
    if not title.startswith("FC_OK"):
        print(out.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"step tier smoke failed: {title}")
    vals = {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", title)}
    k = REFINED_POINTS
    # post-step expansion of k points is 1 + (k-1)*2 vertices with a duplicate
    # x (riser) at every interior point; a lost expansion leaves k and 0.
    if vals["before_dupes"] <= 0:
        raise SystemExit(f"initial build not step-expanded: {vals}")
    if vals["after_n"] != 1 + (k - 1) * 2:
        raise SystemExit(f"tier update lost step expansion: {vals}")
    if vals["after_dupes"] != k - 1:
        raise SystemExit(f"no step risers after tier update: {vals}")
    print("step tier smoke OK")


if __name__ == "__main__":
    main()
