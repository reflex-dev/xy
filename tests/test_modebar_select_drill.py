"""Modebar selection follows density drill pickability."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_DENSITY_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    const g = view.gpuTraces.find((t) => t.tier === "density");
    const trigger = view.root.querySelector("[data-xy-modebar-select-trigger]");
    const shown = () => !!trigger && trigger.style.display !== "none";

    // Aggregated tier: no point identity, so the trigger exists but hides.
    const builtAtDensityTier = !!trigger;
    const hiddenAtDensityTier = !view._pickable && !shown();

    // Drill-in: the kernel's points reply sets g.drill and recomputes
    // pickability. The probe fakes the minimal drill sibling — the wiring
    // under test is capability -> UI sync, not the drill machinery.
    g.drill = { n: 16, win: { ...view.view } };
    view._updatePickable();
    const shownAfterDrill = view._pickable && shown();

    // Losing the capability mid-gesture must also drop the select drag mode
    // and close the menu, not just hide the button.
    view._setDragMode("select-lasso");
    view._dropDrill(g);
    const hiddenAfterDrop = !view._pickable && !shown();
    const dragModeReverted = view.dragMode === "pan";
    const menuClosed = !view._selectMenuOpen;

    // Re-drilling brings the trigger back (the sync is not one-way).
    g.drill = { n: 16, win: { ...view.view } };
    view._updatePickable();
    const shownAfterRedrill = shown();

    document.body.setAttribute("data-xy-select-drill-probe", JSON.stringify({
      builtAtDensityTier,
      hiddenAtDensityTier,
      shownAfterDrill,
      hiddenAfterDrop,
      dragModeReverted,
      menuClosed,
      shownAfterRedrill,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-select-drill-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _chart_html() -> str:
    rng = np.random.default_rng(7)
    chart = xy.scatter_chart(
        xy.scatter(
            rng.normal(0.0, 1.0, 20_000),
            rng.normal(0.0, 1.0, 20_000),
            density=True,
        ),
        xy.x_axis(),
        xy.y_axis(),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_select_trigger_tracks_drill_pickability(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _chart_html().replace(_RENDER_CALL, _DENSITY_PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "select_drill.html",
        "data-xy-select-drill-probe",
        label="modebar select drill probe",
    )

    assert result["builtAtDensityTier"] is True
    assert result["hiddenAtDensityTier"] is True
    assert result["shownAfterDrill"] is True
    assert result["hiddenAfterDrop"] is True
    assert result["dragModeReverted"] is True
    assert result["menuClosed"] is True
    assert result["shownAfterRedrill"] is True
