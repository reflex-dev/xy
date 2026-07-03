"""Headless-Chromium time-to-first-render (TTFR) measurement.

For browser-rendered charts (fastcharts, Plotly-HTML, Bokeh, Altair, hvPlot) the
static-export byte count says nothing about how long the *browser* takes to parse
the embedded JS, build the scene graph, and paint. This measures that: load the
HTML in headless Chromium and read the First Contentful Paint from the
Performance API (navigationStart → first paint), the standard TTFR proxy.

We inline library JS (no CDN) so TTFR reflects parse+execute+paint without
network variance. Returns milliseconds, or None if no browser is available or
the page never painted (reported, never silently zero).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_CHROMIUM_CANDIDATES = (
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)

# Appended before </body>: after the page's own scripts run (Chromium advances
# virtual time through async renders), record FCP into the title for scraping.
_PROBE = """
<script>
(function () {
  function report() {
    var paints = performance.getEntriesByType('paint') || [];
    var fcp = null;
    for (var i = 0; i < paints.length; i++)
      if (paints[i].name === 'first-contentful-paint') fcp = paints[i].startTime;
    var nav = (performance.getEntriesByType('navigation') || [])[0];
    var load = nav ? nav.loadEventEnd : (performance.timing
      ? performance.timing.loadEventEnd - performance.timing.navigationStart : null);
    document.title = 'TTFR fcp=' + (fcp == null ? 'na' : fcp.toFixed(1)) +
                     ' load=' + (load == null ? 'na' : Number(load).toFixed(1));
  }
  if (document.readyState === 'complete') setTimeout(report, 0);
  else window.addEventListener('load', function () { setTimeout(report, 0); });
})();
</script>
"""


def find_chromium(explicit: str | None = None) -> str | None:
    for c in ([explicit] if explicit else []) + list(_CHROMIUM_CANDIDATES):
        if c and (Path(c).is_file() or shutil.which(c)):
            return c
    return None


def _inject_probe(html: str) -> str:
    if "</body>" in html:
        return html.replace("</body>", _PROBE + "</body>", 1)
    return html + _PROBE


def first_paint_ms(
    html: str,
    *,
    chromium: str | None = None,
    virtual_time_ms: int = 12_000,
    timeout_s: int = 180,
) -> float | None:
    """Time-to-first-contentful-paint for a page, in ms (None if unmeasurable)."""
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
                    "--use-angle=swiftshader",
                    "--enable-unsafe-swiftshader",
                    "--hide-scrollbars",
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
    m = re.search(r"fcp=([\d.]+|na)\s+load=([\d.]+|na)", out.stdout)
    if not m:
        return None
    fcp, load = m.group(1), m.group(2)
    if fcp != "na":
        return float(fcp)
    if load != "na":  # some renderers don't emit FCP; loadEventEnd is the fallback
        return float(load)
    return None
