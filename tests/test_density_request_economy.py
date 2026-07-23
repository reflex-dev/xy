"""The aggregate tier never refines; requests only probe the points band
(LOD doc T13, revised on #225 field feedback).

The field HAR behind this (100M live drilldown): every pan and zoom step
re-requested a multi-MB density grid — including back-to-back windows
differing by sub-pixel amounts — for a picture that was the same aggregate
with marginally different blur. The revised contract: whatever density
texture already covers the view STANDS, however blurry, until the view could
plausibly resolve into REAL points (estimated in-view count within
LOD_POINTS_REQUEST_BAND × the direct budget); only then does a density_view
go out, and the kernel answers it with exact points once the count fits.
Sub-texel twins of the last sent request are suppressed outright, and the
frame always draws ONE aggregate texture (a tried fine-over-broad detail
layer was reverted: density textures alpha-composite, so overlaps
double-count opacity, and per-window normalization makes the seam a
brightness step — the field capture's "stale rectangle").

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

    // The home texture carries the payload's recorded count (60k here).
    const homeHasCount = Number.isFinite(g.density.visible);
    // Model a huge cloud: this probe chart holds 60k points (points-band
    // everywhere, so nothing would ever stand). Re-weight the retained
    // sample's claim so each sample row represents ~1.2M points — the
    // distribution-true estimator then reads like a 10B-point trace, and
    // the window-count fixtures below drive the area estimator.
    g.sampleOverlay.sample.visible = 10000000000;

    // A density reply for window W = central 50% of home, 10M in-window.
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
          },
        }],
      }, [grid.buffer]);
    };
    const wx0 = cx - sx * 0.25, wx1 = cx + sx * 0.25;
    const wy0 = cy - sy * 0.25, wy1 = cy + sy * 0.25;
    applyDensity(wx0, wx1, wy0, wy1, 200, 150, 10000000);

    // Zooming inside W at half its span: ~2.5M estimated in view — nowhere
    // near points territory, so the texture stands and NOTHING is requested,
    // pending markers included.
    const insideElided = request(viewAt(0.5, 0.5, 0.25, 0.25)) === 0;
    const elisionClearedPending = g._lodPendingView === null;

    // Deeper inside W (1/16 of its area): ~625k estimated — inside the
    // points band (budget x 4), so the request goes out and the kernel
    // decides with real counts.
    const bandRequested = request(viewAt(0.5, 0.5, 0.12, 0.12)) === 1;

    // A window whose count is already points-scale requests immediately.
    const w2x0 = v0.x0 + sx * 0.10, w2x1 = v0.x0 + sx * 0.40;
    const w2y0 = v0.y0 + sy * 0.10, w2y1 = v0.y0 + sy * 0.40;
    applyDensity(w2x0, w2x1, w2y0, w2y1, 100, 75, 300000);
    const nearDrillRequested = request(viewAt(0.25, 0.25, 0.15, 0.15)) === 1;

    // Sub-texel dedup: a settle re-request shifted by 0.2 output texels is
    // the same picture — suppressed while the first is in flight; a shift of
    // 3 texels is a genuinely different window — sent. (These views sit
    // inside the 60k home count, i.e. always in the points band, so only
    // the dedup memo gates them.)
    const plotW = Math.round(view.plot.w);
    const base = viewAt(0.75, 0.75, 0.2, 0.2);
    const sentBase = request(base) === 1;
    const texel = (base.x1 - base.x0) / plotW;
    const nudged = { ...base, x0: base.x0 + texel * 0.2, x1: base.x1 + texel * 0.2 };
    const subTexelSuppressed = request(nudged) === 0;
    const shifted = { ...base, x0: base.x0 + texel * 3, x1: base.x1 + texel * 3 };
    const texelsRequested = request(shifted) === 1;

    // One aggregate texture per frame (the reverted detail layer must stay
    // reverted): straddle W's edge — home contains the view and draws alone
    // once the crossfade settles; W's finer texture must NOT stack on top.
    view.view = viewAt(0.75, 0.5, 0.5, 0.5);
    view._drawNow();
    clk += 1000; // land the density crossfade
    view._drawNow();
    let densityDraws = 0;
    const real = view._drawDensity;
    view._drawDensity = function (gg, dd, op) {
      if (gg === g) densityDraws++;
      return real.apply(this, arguments);
    };
    view._drawNow();
    view._drawDensity = real;

    document.body.setAttribute("data-xy-economy-probe", JSON.stringify({
      hasDensity: !!g, homeHasCount,
      insideElided, elisionClearedPending, bandRequested, nearDrillRequested,
      sentBase, subTexelSuppressed, texelsRequested,
      densityDraws,
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


def test_aggregate_stands_until_points_band(tmp_path: Path) -> None:
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
    assert result["homeHasCount"] is True
    # The aggregate stands: no refinement requests while the estimated
    # in-view count sits clearly above points territory.
    assert result["insideElided"] is True
    assert result["elisionClearedPending"] is True
    # The points band and points-scale windows still request — the kernel
    # keeps deciding with real counts everywhere it could answer sharper.
    assert result["bandRequested"] is True
    assert result["nearDrillRequested"] is True
    # Sub-texel dedup: same picture, no second request; a real shift sends.
    assert result["sentBase"] is True
    assert result["subTexelSuppressed"] is True
    assert result["texelsRequested"] is True
    # Exactly one aggregate texture per settled frame — no detail stacking.
    assert result["densityDraws"] == 1
