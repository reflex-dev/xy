"""Behavioral regression: an explicit legend max-height survives a resize.

The client's responsive legend cap (`_resize`) re-applies an automatic
`max-height` unless the author set one. The guard reads the chrome `styles`
spec, which ships the author's *raw* key — and the Python API form is
snake_case (`max_height`). A raw-key-only lookup missed that form, so on a
responsive resize the automatic cap clobbered an explicit `max_height`
(browser-verified: 50px became the plot height). The source-grep suites cannot
see this — it only manifests in a live browser after a resize — so this test
renders the standalone export in headless Chromium and asserts the computed
`max-height` before *and* after a forced resize.

Skips (never fails) when no Chromium is available or the headless GL context
can't come up, matching the repo's other browser probes.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy as fc  # noqa: E402
from xy.export import find_chromium  # noqa: E402

# Capture the standalone render call's return value so the probe can drive the
# view directly (the same swap the visual-regression smoke uses).
_RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)

# Async probe: wait for the legend, record its computed max-height, force a
# responsive height change (so _resize runs its legend-cap branch), then record
# the max-height again. Result lands on a body attribute for `--dump-dom`.
_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const raf = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    let legend = null;
    for (let i = 0; i < 200; i++) {
      legend = document.querySelector('[data-fc-slot="legend"]');
      if (legend) break;
      await sleep(25);
    }
    if (!legend) throw new Error("legend never rendered");
    const initial = getComputedStyle(legend).maxHeight;
    // Force a responsive height change so _resize takes the legend-cap branch.
    view.fluid = true;
    view.fluidH = true;
    view._resize(view.size.w, view.size.h + 260);
    await raf();
    legend = document.querySelector('[data-fc-slot="legend"]') || legend;
    const afterResize = getComputedStyle(legend).maxHeight;
    document.body.setAttribute(
      "data-fc-legend-maxheight",
      JSON.stringify({ initial, afterResize })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-fc-legend-maxheight-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def _dump_dom(chromium: str, page: Path) -> str | None:
    """One headless render pass; None on a chromium-level failure (retryable)."""
    try:
        proc = subprocess.run(
            [
                chromium,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--allow-file-access-from-files",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--hide-scrollbars",
                "--window-size=640,480",
                "--virtual-time-budget=8000",
                "--dump-dom",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _probe_maxheight(chromium: str, document: str, page: Path) -> dict | None:
    """Render + probe with retries. Returns the parsed result payload, or None
    if every attempt hit an environmental miss (no DOM / GL error / no result).

    Headless probes on shared runners have transient warm-up misses (virtual
    time / GL init) that a relaunch clears; a genuine regression fails every
    attempt with a *value* mismatch, which we surface — never retry away.
    """
    page.write_text(document, encoding="utf-8")
    last: str | None = None
    for _ in range(3):
        dom = _dump_dom(chromium, page)
        if dom is None:
            continue
        error = re.search(r'data-fc-legend-maxheight-error="([^"]*)"', dom)
        if error:
            last = f"probe error: {html_lib.unescape(error.group(1))}"
            continue
        match = re.search(r'data-fc-legend-maxheight="([^"]*)"', dom)
        if match:
            return json.loads(html_lib.unescape(match.group(1)))
        last = "probe did not finish (no result attribute)"
    if last:
        pytest.skip(f"legend resize probe could not run after retries: {last}")
    pytest.skip("headless chromium unavailable/failed after retries")
    return None  # unreachable; keeps type-checkers happy


def test_snake_case_legend_max_height_survives_resize() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the resize regression probe")

    fig = fc.chart(
        fc.line(x=[0, 1, 2, 3], y=[0, 1, 0, 1], name="alpha"),
        fc.line(x=[0, 1, 2, 3], y=[1, 0, 1, 0], name="beta"),
        fc.legend(),
        # snake_case is the documented Python API form; it must reach the client
        # AND be honored by the responsive-cap guard on resize.
        styles={"legend": {"max_height": 50}},
        width=480,
        height=320,
    )

    document = fig.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update the probe swap"
    capture_call = render_call.replace(
        "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
    )
    document = document.replace(render_call, capture_call, 1)
    document = document.replace("</body>", _PROBE + "\n</body>", 1)

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "legend_resize.html"
        payload = _probe_maxheight(chromium, document, page)

    # Before the fix, the auto-cap overwrote the explicit 50px with the (grown)
    # plot height on resize. It must stay pinned at the author's value.
    assert payload["initial"] == "50px", f"explicit max_height not applied at build: {payload}"
    assert payload["afterResize"] == "50px", (
        f"resize clobbered the explicit snake_case max_height: {payload}"
    )
