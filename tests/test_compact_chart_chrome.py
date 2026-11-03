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

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy import _svg  # noqa: E402
from xy.export import find_chromium  # noqa: E402

STORES = ["Bismarck", "Fargo", "Grand Forks", "Jamestown", "Minot", "West Fargo"]


def _stores_chart(height: int = 300, styles=None, **y_axis):
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
        **({"styles": styles} if styles else {}),
    )


def _y_ticks(chart) -> list[float]:
    spec, _blob = chart.figure().build_payload()
    _w, _h, _compact, plot = _svg.layout(spec)
    _ticks, labelled, _step = _svg.axis_ticks(
        spec["axes"]["y"], plot["h"], False, slot_font_px=_svg._tick_label_slot_px(spec)
    )
    return labelled


def _chromium() -> str:
    chromium = find_chromium()
    if not chromium:
        if os.environ.get("XY_REQUIRE_BROWSER"):
            pytest.fail("XY_REQUIRE_BROWSER is set but no Chromium installation was found")
        pytest.skip("no chromium available for the compact chrome probes")
    return chromium


def _probe(chart, script: str, attribute: str, name: str) -> dict:
    document = probe_document(chart, script)
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


# --- review findings (PR 545) -------------------------------------------------------


def test_polar_radial_category_axis_keeps_numeric_density() -> None:
    # A polar radial axis carries `hole`; it keeps the 45 px target.
    axis = {"kind": "category", "categories": STORES, "range": [-0.5, 5.5], "hole": 0.0}
    assert len(_svg.axis_ticks(axis, 220.0, False)[1]) == 3
    cartesian = {key: value for key, value in axis.items() if key != "hole"}
    assert len(_svg.axis_ticks(cartesian, 220.0, False)[1]) == len(STORES)


BIG_LABELS = {"tick_label": {"font_size": "24px"}}


def test_static_category_pitch_uses_the_tick_label_slot_font() -> None:
    # 24 px labels need ~38 px each; six of them do not fit ~220 px.
    labelled = _y_ticks(_stores_chart(height=300, styles=BIG_LABELS))
    assert 1 < len(labelled) < len(STORES)


def test_browser_category_pitch_uses_the_tick_label_slot_font() -> None:
    chart = _stores_chart(height=300, styles=BIG_LABELS)
    payload = _probe(chart, _TICK_PROBE, "data-xy-category-ticks", "category_ticks_big")
    assert len(payload["labels"]) == len(_y_ticks(chart)), payload


_TITLE_BOUNDS_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const root = view.root.getBoundingClientRect();
    const box = document.querySelector('[data-xy-slot="title"]').getBoundingClientRect();
    document.body.setAttribute("data-xy-title-bounds", JSON.stringify({
      left: box.left - root.left, right: root.right - box.right,
      plotLeft: view.plot.x,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-title-bounds-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_title_stays_on_the_canvas_beside_a_wide_left_gutter() -> None:
    # Long category names widen the measured left gutter, pulling the plot's
    # centre right; a max-content title centred there must not cross the edge.
    names = [f"Regional distribution centre {i}" for i in range(4)]
    chart = xy.chart(
        xy.bar(names, [3.0, 5.0, 2.0, 4.0], orientation="horizontal"),
        title="Quarterly fulfilment overview report",
        width=320,
        height=220,
    )
    payload = _probe(chart, _TITLE_BOUNDS_PROBE, "data-xy-title-bounds", "title_bounds")
    assert payload["plotLeft"] > 120, payload  # the wide gutter this test needs
    assert payload["left"] >= 0, payload
    assert payload["right"] >= 0, payload
