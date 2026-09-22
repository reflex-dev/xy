"""`show=False` collapses the axis's layout slot (dossier §33, axes docs).

The visibility shorthands compile to transparent axis paints rather than to a
flag, so layout has to ask the paint whether any text will be seen. The static
exporters already do (`_axis_text_paint_visible`, whose docstring names the
edge-to-edge sparkline as the reason); the browser did not, so the same chart
rendered flush in an SVG and inset in a canvas. These tests pin the two to each
other.

Browser probes drive the real client; they skip (never fail) without Chromium,
like the repo's others.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

WIDTH = 1088
HEIGHT = 200
PADDING = (8, 0, 28, 0)


def _chart(**axes):
    """The reported repro: a line with both axes switched off, no padding to
    spare, and a fluid width so the plot can reach the container edge."""
    return xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(**axes.get("x", {})),
        xy.y_axis(**axes.get("y", {})),
        width=WIDTH,
        height=HEIGHT,
        padding=PADDING,
    )


def _svg_plot_rect(chart) -> tuple[float, float]:
    """The exporter's plot rect, read from the clip path it draws marks into."""
    svg = chart.to_svg()
    match = re.search(r"<clipPath[^>]*>\s*<rect ([^/]*)/>", svg)
    assert match is not None, "SVG clip path shape changed; update this helper"
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group(1)))
    return float(attrs["x"]), float(attrs["width"])


def test_export_collapses_the_slot_for_show_false() -> None:
    """The contract the exporters already keep: nothing drawn, nothing
    reserved, on either side."""
    assert _svg_plot_rect(_chart(x={"show": False}, y={"show": False})) == (0.0, WIDTH)
    flush_right = _chart(x={"show": False}, y={"show": False, "side": "right"})
    assert _svg_plot_rect(flush_right) == (0.0, WIDTH)
    # A grid needs no gutter, so `show=False, grid=True` is flush as well.
    grid_only = _chart(x={"show": False}, y={"show": False, "grid": True})
    assert _svg_plot_rect(grid_only) == (0.0, WIDTH)
    # An axis that draws its labels still reserves its room.
    x0, w = _svg_plot_rect(_chart())
    assert x0 > 0 and w < WIDTH, (x0, w)


_PLOT_RECT_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    view._drawNow();
    document.body.setAttribute("data-xy-plotrect", JSON.stringify({
      x: view.plot.x, w: view.plot.w,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-plotrect-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def _browser_plot_rect(chart, label: str) -> tuple[float, float]:
    chromium = find_chromium()
    if not chromium:
        # `run_browser_probe` turns an unlaunchable browser into a failure under
        # XY_REQUIRE_BROWSER; skipping before that call would slip past it.
        if os.environ.get("XY_REQUIRE_BROWSER"):
            pytest.fail(f"{label}: XY_REQUIRE_BROWSER is set but no chromium was found")
        pytest.skip(f"no chromium available for the {label} probe")
    document = probe_document(chart, _PLOT_RECT_PROBE)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium, document, Path(td) / "axis.html", "data-xy-plotrect", label=label
        )
    return round(float(payload["x"]), 1), round(float(payload["w"]), 1)


def test_browser_show_false_reaches_the_edge_like_the_export() -> None:
    """The divergence this fixes: the browser reserved a gutter for text the
    shorthands had already made invisible, so a chart that exported flush
    rendered inset. Both sides now answer the same question about the paint."""
    off = {"show": False}
    assert _browser_plot_rect(_chart(x=off, y=off), "axes off") == (0.0, float(WIDTH))

    # The right side was the worse case: a flat 54 px reservation that no style
    # zeroing could reach.
    right = _chart(x=off, y={"show": False, "side": "right"})
    assert _browser_plot_rect(right, "right axis off") == (0.0, float(WIDTH))

    # `show=False, grid=True` keeps the grid and still claims no gutter.
    grid = _chart(x=off, y={"show": False, "grid": True})
    assert _browser_plot_rect(grid, "grid only") == (0.0, float(WIDTH))


def test_browser_visible_axes_keep_their_room() -> None:
    """The other half of the contract: an axis whose text is drawn reserves the
    room it needs, and the browser agrees with the exporter about how much."""
    chart = _chart()
    browser = _browser_plot_rect(chart, "axes on")
    assert browser[0] > 0 and browser[1] < WIDTH, browser
    export = _svg_plot_rect(chart)
    # The two measure text with different engines, so they are close rather
    # than identical; a whole gutter's worth of difference is the regression.
    assert abs(browser[0] - export[0]) <= 8, (browser, export)
    assert abs(browser[1] - export[1]) <= 8, (browser, export)
