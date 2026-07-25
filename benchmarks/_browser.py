"""Headless-Chromium chart-ready measurement.

For browser-rendered charts (xy, Plotly-HTML, Bokeh, Altair, hvPlot) the
static-export byte count says nothing about how long the *browser* takes to parse
the embedded JS, build the scene graph, and paint. This measures that by waiting
for a visible chart canvas/SVG/image. Page-level FCP is
recorded for diagnostics, but is not used as chart TTFR: titles, loading text, or
other chrome can paint before the chart exists.

We inline library JS (no CDN) so TTFR reflects parse+execute+paint without
network variance. Returns milliseconds, or None if no browser is available or
the page never painted (reported, never silently zero).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)

# Appended before </body>: wait for a visible chart surface, then
# record navigation-relative chart-ready time into the title for scraping.
_PROBE = """
<script>
(function () {
  function fcp() {
    var paints = performance.getEntriesByType('paint') || [];
    for (var i = 0; i < paints.length; i++)
      if (paints[i].name === 'first-contentful-paint') return paints[i].startTime;
    return null;
  }
  function visibleChartSurface() {
    var nodes = document.querySelectorAll('.xy canvas,.js-plotly-plot canvas,' +
      '.js-plotly-plot svg,.bk-root canvas,.bk-root svg,canvas,svg,img');
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var rect = node.getBoundingClientRect();
      var style = getComputedStyle(node);
      if (rect.width <= 1 || rect.height <= 1 || style.display === 'none' ||
          style.visibility === 'hidden') continue;
      if (node.tagName === 'SVG' && !node.querySelector('path,rect,circle,line,polyline,polygon,text'))
        continue;
      if (node.tagName === 'IMG' && !node.complete) continue;
      return true;
    }
    return false;
  }
  function finish(ready) {
    var paint = fcp();
    var heap = performance.memory ? performance.memory.usedJSHeapSize : null;
    document.title = 'CHART_READY ready=' + (ready == null ? 'na' : ready.toFixed(1)) +
                     ' fcp=' + (paint == null ? 'na' : paint.toFixed(1)) +
                     ' heap=' + (heap == null ? 'na' : Number(heap).toFixed(0));
  }
  function poll(deadline) {
    if (visibleChartSurface()) {
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { finish(performance.now()); });
      });
    } else if (performance.now() < deadline) {
      setTimeout(function () { poll(deadline); }, 16);
    } else {
      finish(null);
    }
  }
  function start() { poll(performance.now() + 10000); }
  if (document.readyState === 'complete') start();
  else window.addEventListener('load', start);
})();
</script>
"""


def find_chromium(explicit: str | None = None) -> str | None:
    for c in ([explicit] if explicit else []) + list(_CHROMIUM_CANDIDATES):
        if c and (Path(c).is_file() or shutil.which(c)):
            return c
    return None


def chromium_gl_flags() -> list[str]:
    if os.environ.get("XY_BENCH_HARDWARE_GL") == "1":
        return []
    return ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def _inject_probe(html: str) -> str:
    if "</body>" in html:
        return html.replace("</body>", _PROBE + "</body>", 1)
    return html + _PROBE


def chart_ready_metrics(
    html: str,
    *,
    chromium: str | None = None,
    virtual_time_ms: int = 12_000,
    timeout_s: int = 180,
) -> dict[str, float | None] | None:
    """Navigation-to-chart-ready and JS-heap metrics for one browser page."""
    exe = find_chromium(chromium)
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "page.html"
        p.write_text(_inject_probe(html), encoding="utf-8")
        try:
            out = subprocess.run(
                [
                    exe,
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    *chromium_gl_flags(),
                    "--hide-scrollbars",
                    "--enable-precise-memory-info",
                    f"--virtual-time-budget={virtual_time_ms}",
                    "--dump-dom",
                    p.as_uri(),
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return None
    m = re.search(r"ready=([\d.]+|na)\s+fcp=([\d.]+|na)\s+heap=([\d.]+|na)", out.stdout)
    if not m:
        return None
    return {
        "ready_ms": None if m.group(1) == "na" else float(m.group(1)),
        "fcp_ms": None if m.group(2) == "na" else float(m.group(2)),
        "js_heap_bytes": None if m.group(3) == "na" else float(m.group(3)),
    }


def first_chart_ready_ms(
    html: str,
    *,
    chromium: str | None = None,
    virtual_time_ms: int = 12_000,
    timeout_s: int = 180,
) -> float | None:
    metrics = chart_ready_metrics(
        html,
        chromium=chromium,
        virtual_time_ms=virtual_time_ms,
        timeout_s=timeout_s,
    )
    return None if metrics is None else metrics["ready_ms"]


def first_paint_ms(
    html: str,
    *,
    chromium: str | None = None,
    virtual_time_ms: int = 12_000,
    timeout_s: int = 180,
) -> float | None:
    """Backward-compatible alias for the chart-ready probe."""
    return first_chart_ready_ms(
        html,
        chromium=chromium,
        virtual_time_ms=virtual_time_ms,
        timeout_s=timeout_s,
    )
