"""Compact-chart chrome regressions: category labels and the chart title.

1. A vertical category axis took the numeric tick density (one label per 45 px
   of plot height). Category labels are one text line each, so a 6-store
   horizontal bar chart at a dashboard height labelled only every other store.
2. A centred title is an absolutely positioned box whose ``left`` is the plot's
   midpoint, so it shrink-wrapped to the room right of that point. On a 320 px
   card it wrapped into lines the title band never reserved, and its first line
   was painted above the canvas.

The browser probes skip (never fail) without Chromium; ``XY_REQUIRE_BROWSER=1``
turns that into a failure.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy import _svg  # noqa: E402
from xy.export import find_chromium  # noqa: E402

STORES = ["Bismarck", "Fargo", "Grand Forks", "Jamestown", "Minot", "West Fargo"]

_RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)


def _stores_chart(height: int = 300, **y_axis):
    return xy.chart(
        xy.bar(
            STORES,
            np.full((len(STORES), 4), 5.0),
            series=["Waiting Parts", "In Progress", "Waiting Approval", "Complete"],
            mode="stacked",
            orientation="horizontal",
        ),
        xy.y_axis(label="Store", **y_axis),
        title="Work orders by store",
        width=900,
        height=height,
    )


def _y_ticks(chart) -> list[float]:
    spec, _blob = chart.figure().build_payload()
    _w, _h, _compact, plot = _svg.layout(spec)
    _ticks, labelled, _step = _svg.axis_ticks(spec["axes"]["y"], plot["h"], False)
    return labelled


def _chromium() -> str:
    chromium = find_chromium()
    if not chromium:
        if os.environ.get("XY_REQUIRE_BROWSER"):
            pytest.fail("XY_REQUIRE_BROWSER is set but no Chromium installation was found")
        pytest.skip("no chromium available for the compact chrome probes")
    return chromium


def _probe(chart, script: str, attribute: str, name: str) -> dict:
    document = chart.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update the probe swap"
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    document = document.replace("</body>", script + "\n</body>", 1)
    with tempfile.TemporaryDirectory() as td:
        return run_browser_probe(
            _chromium(), document, Path(td) / f"{name}.html", attribute, label=name
        )


# --- category labels --------------------------------------------------------------


def test_static_vertical_category_axis_labels_every_category_that_fits() -> None:
    # About 220 px of plot for six one-line labels: every store fits.
    assert len(_y_ticks(_stores_chart(height=300))) == len(STORES)


def test_static_vertical_category_axis_still_thins_when_rows_are_too_short() -> None:
    labelled = _y_ticks(_stores_chart(height=150))
    assert 1 < len(labelled) < len(STORES)


def test_authored_tick_count_still_wins() -> None:
    assert len(_y_ticks(_stores_chart(height=300, tick_count=2))) <= 3


_TICK_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const labels = [...document.querySelectorAll('[data-xy-label-kind="tick"][data-xy-axis="y"]')]
      .filter((node) => node.textContent && getComputedStyle(node).display !== "none");
    document.body.setAttribute("data-xy-category-ticks", JSON.stringify({
      labels: labels.map((node) => node.textContent),
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-category-ticks-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_vertical_category_axis_matches_static_labels() -> None:
    chart = _stores_chart(height=300)
    payload = _probe(chart, _TICK_PROBE, "data-xy-category-ticks", "category_ticks")
    assert sorted(payload["labels"]) == sorted(STORES), payload


# --- compact title ------------------------------------------------------------------


_TITLE_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const root = view.root.getBoundingClientRect();
    const title = document.querySelector('[data-xy-slot="title"]');
    if (!title) throw new Error("title never rendered");
    const box = title.getBoundingClientRect();
    const lineHeight = Number.parseFloat(getComputedStyle(title).lineHeight)
      || Number.parseFloat(getComputedStyle(title).fontSize) * 1.2;
    document.body.setAttribute("data-xy-compact-title", JSON.stringify({
      lines: Math.round(box.height / lineHeight),
      titleTopToRootTop: box.top - root.top,
      titleBottomToCanvasTop: view.canvas.getBoundingClientRect().top - box.bottom,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-compact-title-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_compact_title_wraps_only_where_layout_reserved() -> None:
    months = np.arange(12)
    chart = xy.line_chart(
        xy.line(months, 40 + 9 * months, name="Signups"),
        title="Small card (320x200)",
        width=320,
        height=200,
    )
    payload = _probe(chart, _TITLE_PROBE, "data-xy-compact-title", "compact_title")
    assert payload["lines"] == 1, payload
    assert payload["titleTopToRootTop"] >= 0, payload
    assert payload["titleBottomToCanvasTop"] >= 0, payload
