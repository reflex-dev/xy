"""Headless render smoke test: does the WebGL2 client actually put pixels on
screen for a real payload? (§12 — a renderer's correctness oracle is an image.)

Drives headless Chromium directly (no Playwright dependency): builds a
standalone page the same way `Figure.to_html` does, adds a probe that draws
synchronously and counts non-transparent pixels via gl.readPixels, then reads
the result out of the dumped DOM title.

Usage: python scripts/smoke_render.py [chromium-binary]
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

from fastcharts import Figure
from fastcharts.export import _bundled_js

CHROMIUM_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
]


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
    rng = np.random.default_rng(1)
    y = np.cumsum(rng.normal(size=n))
    fig = Figure(title="smoke")
    fig.line(x, y, name="walk")
    fig.scatter(x[::100], y[::100] + 20.0, name="pts", size=3.0)
    spec, blob = fig.build_payload()
    assert spec["traces"][0]["tier"] == "decimated"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>pending</title></head>
<body><div id="chart"></div>
<script>{_bundled_js("standalone")}</script>
<script>
  const spec = {json.dumps(spec)};
  const bytes = Uint8Array.from(atob("{base64.b64encode(blob).decode()}"), c => c.charCodeAt(0));
  try {{
    const view = fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
    setTimeout(() => {{
      try {{
        view._drawNow();  // synchronous draw; read back in the same task
        const gl = view.gl;
        const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
        const px = new Uint8Array(w * h * 4);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
        let lit = 0;
        for (let i = 3; i < px.length; i += 4) if (px[i] > 8) lit++;
        const labels = document.querySelectorAll(".fastcharts div").length;
        document.title = `FC_OK lit=${{lit}} total=${{w * h}} labels=${{labels}}`;
      }} catch (e) {{ document.title = "FC_ERROR " + e.message; }}
    }}, 200);
  }} catch (e) {{ document.title = "FC_ERROR " + e.message; }}
</script></body></html>"""


def main() -> None:
    chromium = find_chromium()
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "smoke.html"
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
        raise SystemExit(f"render smoke failed: {title}")
    lit = int(re.search(r"lit=(\d+)", title).group(1))  # type: ignore[union-attr]
    total = int(re.search(r"total=(\d+)", title).group(1))  # type: ignore[union-attr]
    labels = int(re.search(r"labels=(\d+)", title).group(1))  # type: ignore[union-attr]
    frac = lit / max(total, 1)
    print(f"lit fraction: {frac:.3%}, DOM chrome nodes: {labels}")
    # A line + scatter across the plot should light a nontrivial pixel share,
    # and axis labels must exist in the DOM (§7 chrome contract).
    if not (0.002 < frac < 0.9):
        raise SystemExit(f"suspicious lit fraction {frac:.4f}")
    if labels < 6:
        raise SystemExit(f"expected DOM tick labels, found {labels}")
    print("render smoke OK")


if __name__ == "__main__":
    main()
