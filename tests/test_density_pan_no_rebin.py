"""Standalone (kernel-less) density: panning must keep the full-data overview.

A `to_html` density export ships the overview grid (binned kernel-side from
every source point) plus the retained §28 sample. Without a kernel, only the
sample can be re-binned in the browser. Re-binning it on a mere *pan* swaps the
full-data grid for a noisier sample-derived grid normalized against a much
smaller maximum, so the density visibly jumps (overview <-> sample) on the
slightest drag. The re-bin must fire only on a genuine zoom-*in*, where it adds
resolution the overview grid lacks; pans and zoom-outs keep the overview.

This drives the real client in headless Chromium and inspects the decision made
by `_requestSampleRebin`, using a sentinel object to distinguish "restored the
overview" from "left the sample grid in place". The wall-clock re-bin worker is
disabled (`_sampleRebinDisabled`) so no worker spawns to stall `--dump-dom`;
the gate under test runs before that flag is consulted.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    // Never spawn the wall-clock re-bin worker under --virtual-time-budget
    // --dump-dom; the pan/zoom gate under test runs before this flag is read.
    view._sampleRebinDisabled = true;
    const g = view.gpuTraces.find((t) => t.tier === "density");
    const v0 = view.view0;
    const sx = v0.x1 - v0.x0, sy = v0.y1 - v0.y0;
    g._homeDensity = g.density;
    // A sentinel stands in for a sample-rebinned grid; restoring the overview
    // replaces it, leaving it in place means the re-bin path was taken.
    const sentinel = { __sentinel: true };

    // 1) Pan at home zoom (span unchanged, shifted 20%): keep the overview.
    g.density = sentinel;
    view._requestSampleRebin(
      g,
      { x0: v0.x0 + sx * 0.2, x1: v0.x1 + sx * 0.2,
        y0: v0.y0 + sy * 0.2, y1: v0.y1 + sy * 0.2 },
      view.seq,
    );
    const panRestoredOverview = g.density !== sentinel;
    const panSpawnedWorker = !!view._rebinWorker;

    // 2) Zoom in (span halved, centered): do NOT restore -> sample re-bin path.
    g.density = sentinel;
    const cx = (v0.x0 + v0.x1) / 2, cy = (v0.y0 + v0.y1) / 2;
    view._requestSampleRebin(
      g,
      { x0: cx - sx * 0.25, x1: cx + sx * 0.25,
        y0: cy - sy * 0.25, y1: cy + sy * 0.25 },
      view.seq,
    );
    const zoomKeptSampleGrid = g.density === sentinel;

    // 3) The retained sample overlay must keep drawing through a pan/zoom-out,
    // not drop out the instant the view leaves its home window. Spy on the
    // point draw for a zoomed-out view (span 2x, so the view is NOT inside the
    // sample window) and for a view panned entirely off the data.
    g.density = g._homeDensity;
    let drewPoints = 0;
    const realDrawPoints = view._drawPoints;
    view._drawPoints = function () { drewPoints += 1; };
    view.view = { x0: v0.x0 - sx * 0.5, x1: v0.x1 + sx * 0.5,
                  y0: v0.y0 - sy * 0.5, y1: v0.y1 + sy * 0.5 };
    view._drawDensitySample(g, view.view.x0, view.view.x1, view.view.y0, view.view.y1);
    const sampleDrawnZoomedOut = drewPoints > 0;
    drewPoints = 0;
    view.view = { x0: v0.x1 + sx * 5, x1: v0.x1 + sx * 6,
                  y0: v0.y1 + sy * 5, y1: v0.y1 + sy * 6 };
    view._drawDensitySample(g, view.view.x0, view.view.x1, view.view.y0, view.view.y1);
    const sampleSkippedOffData = drewPoints === 0;
    view._drawPoints = realDrawPoints;

    document.body.setAttribute("data-xy-rebin-probe", JSON.stringify({
      hasDensity: !!g,
      panRestoredOverview,
      panSpawnedWorker,
      zoomKeptSampleGrid,
      sampleDrawnZoomedOut,
      sampleSkippedOffData,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-rebin-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _density_html() -> str:
    rng = np.random.default_rng(0)
    n = 60_000
    x = rng.normal(0.0, 1.0, n)
    y = rng.normal(0.0, 1.0, n)
    # density=True forces the density tier (overview grid + retained sample)
    # regardless of point count, so the export exercises the standalone re-bin
    # path deterministically and cheaply.
    chart = xy.scatter_chart(
        xy.scatter(x, y, density=True),
        xy.x_axis(),
        xy.y_axis(),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_standalone_pan_keeps_overview_only_zoom_rebins(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "density_pan.html",
        "data-xy-rebin-probe",
        label="density pan re-bin probe",
    )

    assert result["hasDensity"] is True
    # A pan keeps (restores) the full-data overview and spawns no worker.
    assert result["panRestoredOverview"] is True
    assert result["panSpawnedWorker"] is False
    # A genuine zoom-in still routes to the sample re-bin path.
    assert result["zoomKeptSampleGrid"] is True
    # The sample overlay travels with the view: it keeps drawing when zoomed out
    # past its home window, and only drops when panned entirely off the data.
    assert result["sampleDrawnZoomedOut"] is True
    assert result["sampleSkippedOffData"] is True
