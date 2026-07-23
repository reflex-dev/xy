"""Density requests are elided, deduped, and drawn sharp (LOD doc T13).

The field HAR behind this (100M live drilldown, 200-450% zoom): every pan and
zoom step re-requested a ~2.7 MB full-screen density grid — including
back-to-back windows differing by sub-pixel amounts — while the draw path fell
back to the blurriest cached texture the moment a pan left the freshest
window. Three client rules fix it:

- **source-resolution elision**: a cached texture that already sits at the
  kernel's finest attainable aggregate cell size (`min_cell`, pyramid-served
  replies) answers any contained view — zooming further in cannot sharpen it —
  guarded so the exact/drill regimes stay reachable (estimated in-view count
  above the budget band, bounded window/view area ratio);
- **sub-texel request dedup**: a request within half an output texel of the
  trace's last sent request is suppressed (answered → nothing to refresh;
  in flight → keep waiting on the original seq);
- **finer-detail layering**: when no fine window contains the view, the
  smallest cached texture overlapping it draws on top of the broad backdrop
  instead of the frame dropping to uniform blur.

This drives the real client in headless Chromium with a captured comm.
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
    view._sampleRebinDisabled = true;
    const g = view.gpuTraces.find((t) => t.tier === "density");
    let clk = 100000;
    view._now = () => clk;
    g._densityNormAnim = null;

    const v0 = view.view0;
    const cx = (v0.x0 + v0.x1) / 2, cy = (v0.y0 + v0.y1) / 2;
    const sx = v0.x1 - v0.x0, sy = v0.y1 - v0.y0;
    const sent = [];
    view.comm = { send: (m) => sent.push(m) };
    const densitySent = () => sent.filter((m) => m.type === "density_view").length;
    const request = (v) => {
      const before = densitySent();
      view._scheduleViewRequest(view._viewFrom(v), { delay: 0 });
      return densitySent() - before;
    };
    const viewAt = (fcx, fcy, fspanx, fspany) => ({
      x0: v0.x0 + sx * fcx - sx * fspanx / 2, x1: v0.x0 + sx * fcx + sx * fspanx / 2,
      y0: v0.y0 + sy * fcy - sy * fspany / 2, y1: v0.y0 + sy * fcy + sy * fspany / 2,
    });

    // A pyramid-served reply: grid at the trace's SOURCE resolution
    // (cell == min_cell), `visible` points in-window.
    const applyDensity = (x0d, x1d, y0d, y1d, gw, gh, visible) => {
      const grid = new Float32Array(gw * gh).fill(3);
      view._onKernelMsg({
        type: "density_update", seq: view.seq, trace: g.trace.id,
        traces: [{
          id: g.trace.id, mode: "density", visible,
          binning: "pyramid-L0",
          density: {
            buf: 0, w: gw, h: gh, max: 3,
            x_range: [x0d, x1d], y_range: [y0d, y1d],
            min_cell: [(x1d - x0d) / gw, (y1d - y0d) / gh],
          },
        }],
      }, [grid.buffer]);
    };
    // Window W = central 50% of home, 10M points in-window.
    const wx0 = cx - sx * 0.25, wx1 = cx + sx * 0.25;
    const wy0 = cy - sy * 0.25, wy1 = cy + sy * 0.25;
    applyDensity(wx0, wx1, wy0, wy1, 200, 150, 10000000);
    const cached = g.density;
    const storedFacts = Number.isFinite(cached.visible) && !!cached.minCell;

    // Zooming INSIDE W (half its span, area ratio 4): the kernel could not
    // return anything sharper than the cached source-resolution texture, and
    // ~2.5M estimated points are nowhere near drill — no request.
    const insideElided = request(viewAt(0.5, 0.5, 0.25, 0.25)) === 0;
    const elisionClearedPending = g._lodPendingView === null;

    // A deep dive (area ratio 16 > 8) re-requests: the uniform-density
    // estimate overshoots in sparse corners, so let the kernel re-decide.
    const deepDiveRequested = request(viewAt(0.5, 0.5, 0.12, 0.12)) === 1;

    // Near the exact/drill regime the kernel CAN do better: a separate
    // window with only 300k in-window — a half-span view inside it
    // estimates ~75k, points territory, so the request must go out even
    // though the cached texture is source-limited.
    const w2x0 = v0.x0 + sx * 0.10, w2x1 = v0.x0 + sx * 0.40;
    const w2y0 = v0.y0 + sy * 0.10, w2y1 = v0.y0 + sy * 0.40;
    applyDensity(w2x0, w2x1, w2y0, w2y1, 100, 75, 300000);
    const nearDrillRequested = request(viewAt(0.25, 0.25, 0.15, 0.15)) === 1;

    // Sub-texel dedup: a settle re-request shifted by 0.2 output texels is
    // the same picture — suppressed while the first is in flight; a shift of
    // 3 texels is a genuinely different window — sent.
    const plotW = Math.round(view.plot.w);
    const base = viewAt(0.75, 0.75, 0.2, 0.2);
    const sentBase = request(base) === 1;
    const texel = (base.x1 - base.x0) / plotW;
    const nudged = { ...base, x0: base.x0 + texel * 0.2, x1: base.x1 + texel * 0.2 };
    const subTexelSuppressed = request(nudged) === 0;
    const shifted = { ...base, x0: base.x0 + texel * 3, x1: base.x1 + texel * 3 };
    const texelsRequested = request(shifted) === 1;

    // Finer-detail layering: pan half-out of W (not contained, ~50% overlap).
    // The home texture is the containing backdrop, but W's fine texture must
    // draw ON TOP of it instead of the frame dropping to home's blur.
    view.view = viewAt(0.75, 0.5, 0.5, 0.5);
    view._drawNow();
    clk += 1000; // land the density crossfade so the detail layer engages
    view._drawNow();
    const drawnRanges = [];
    const real = view._drawDensity;
    view._drawDensity = function (gg, dd, op) {
      if (gg === g && dd && dd.xRange) drawnRanges.push([dd.xRange[0], dd.xRange[1], op]);
      return real.apply(this, arguments);
    };
    view._drawNow();
    view._drawDensity = real;
    const fineIdx = drawnRanges.findIndex((r) => Math.abs(r[0] - wx0) < sx * 1e-9);
    const broadIdx = drawnRanges.findIndex((r) => r[0] < wx0 - sx * 0.1);
    const detailDrawn = fineIdx >= 0 && broadIdx >= 0 && fineIdx > broadIdx;

    document.body.setAttribute("data-xy-economy-probe", JSON.stringify({
      hasDensity: !!g, storedFacts,
      insideElided, elisionClearedPending, deepDiveRequested, nearDrillRequested,
      sentBase, subTexelSuppressed, texelsRequested,
      drawnCount: drawnRanges.length, detailDrawn,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-economy-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _density_html() -> str:
    rng = np.random.default_rng(0)
    n = 60_000
    x = rng.normal(0.0, 1.0, n)
    y = rng.normal(0.0, 1.0, n)
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


def test_density_requests_elided_deduped_and_layered(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "density_request_economy.html",
        "data-xy-economy-probe",
        label="density request-economy probe",
    )

    assert result["hasDensity"] is True
    assert result["storedFacts"] is True
    # Source-resolution elision: a zoom inside a source-limited cached window
    # sends nothing (the kernel cannot sharpen it) and clears its pending
    # marker like every other elision.
    assert result["insideElided"] is True
    assert result["elisionClearedPending"] is True
    # The guards keep the kernel in charge where it can do better.
    assert result["deepDiveRequested"] is True
    assert result["nearDrillRequested"] is True
    # Sub-texel dedup: same picture, no second request; a real shift sends.
    assert result["sentBase"] is True
    assert result["subTexelSuppressed"] is True
    assert result["texelsRequested"] is True
    # The finest overlapping cached texture draws over the broad backdrop.
    assert result["detailDrawn"] is True
