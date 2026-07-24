"""The aggregate sharpens in QUANTIZED ladder steps and probes the points
band with raw views (LOD doc T13, revised on #225 field feedback).

The field HAR behind this (100M live drilldown): every pan and zoom step
re-requested a multi-MB density grid — including back-to-back windows
differing by sub-pixel amounts — for a picture that was the same aggregate
with marginally different blur, and per-view textures read as zoom/pan
jumping. The revised contract: while the estimated in-view count sits above
the points band (LOD_POINTS_REQUEST_BAND × the direct budget), the only
density request allowed is the next LADDER STEP — the view snapped outward
to a power-of-LOD_AGG_STEP_FACTOR block grid over the extent, at most
LOD_AGG_STEP_MAX steps below home — whose reply is the one density reply
that may repaint a covered view (a smooth-to-smooth swap; pans inside a
step re-resolve to the same window). Inside the band the RAW view is
requested so the kernel decides the tier with real counts; its density
replies land as facts only. Sub-texel twins of the last sent request are
suppressed outright, and the frame always draws ONE aggregate texture (a
tried fine-over-broad detail layer was reverted: density textures
alpha-composite, so overlaps double-count opacity, and per-window
normalization makes the seam a brightness step — the field capture's
"stale rectangle").

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
    const shownBefore = g.density;
    applyDensity(wx0, wx1, wy0, wy1, 200, 150, 10000000);
    // Display side of the stands-rule: the home texture covers the view, so
    // the reply changed no pixels — it landed as a FACTS-ONLY cache entry
    // (window + exact count) that the points-band gate reads below. The
    // field capture behind this: transition-band exact grids repainting the
    // smooth standing surface on every probe read as zoom-level jumping.
    const standingHeld = g.density === shownBefore;
    const factsStored = (g.densityCache || []).some(
      (c) => c && !c.tex && c.visible === 10000000);

    // Zooming inside W at half its span: ~2.5M estimated in view — nowhere
    // near points territory, so the aggregate stands. The one request the
    // stepped ladder allows: the QUANTIZED step-1 window (the view snapped
    // outward to extent/4 blocks — here exactly W's bounds), never the raw
    // view window.
    const stepView = viewAt(0.5, 0.5, 0.25, 0.25);
    const stepSent = request(stepView) === 1;
    const stepMsg = sent.filter((m) => m.type === "density_view").pop();
    const stepTol = sx * 1e-9;
    const stepAligned = stepMsg &&
      Math.abs(stepMsg.x0 - wx0) <= stepTol && Math.abs(stepMsg.x1 - wx1) <= stepTol &&
      Math.abs(stepMsg.y0 - wy0) <= stepTol && Math.abs(stepMsg.y1 - wy1) <= stepTol;
    const stepMarked = Array.isArray(g._stepReqWin);
    // The step reply is the ONE density reply allowed to repaint a covered
    // view: it replaces the standing texture (smooth-to-smooth swap).
    applyDensity(stepMsg.x0, stepMsg.x1, stepMsg.y0, stepMsg.y1, 200, 150, 10000000);
    const stepApplied = g.density !== shownBefore &&
      Math.abs(g.density.xRange[0] - wx0) <= stepTol && g._stepReqWin === null;

    // Re-requesting a view the step texture now covers sends nothing.
    const insideElided = request(stepView) === 0;
    const elisionClearedPending = g._lodPendingView === null;

    // Deeper inside W (1/16 of its area): ~625k estimated — inside the
    // points band (budget x 4), so the RAW VIEW request goes out and the
    // kernel decides with real counts.
    const bandView = viewAt(0.5, 0.5, 0.12, 0.12);
    const bandRequested = request(bandView) === 1;
    const bandMsg = sent.filter((m) => m.type === "density_view").pop();
    const bandIsRawView = bandMsg &&
      Math.abs(bandMsg.x0 - bandView.x0) <= stepTol &&
      Math.abs(bandMsg.x1 - bandView.x1) <= stepTol;

    // A window whose count is already points-scale requests immediately.
    const w2x0 = v0.x0 + sx * 0.10, w2x1 = v0.x0 + sx * 0.40;
    const w2y0 = v0.y0 + sy * 0.10, w2y1 = v0.y0 + sy * 0.40;
    applyDensity(w2x0, w2x1, w2y0, w2y1, 100, 75, 300000);
    const nearDrillRequested = request(viewAt(0.25, 0.25, 0.15, 0.15)) === 1;

    // Sub-texel dedup: a settle re-request shifted by 0.2 output texels is
    // the same picture — suppressed while the first is in flight; a shift of
    // 3 texels is a genuinely different window — sent. Restore the honest
    // 60k sample weighting first so these views sit in the points band and
    // request RAW windows (a standing view would quantize to the same
    // aligned step window under any sub-block shift, gating on alignment
    // rather than the dedup memo this section pins).
    g.sampleOverlay.sample.visible = 60000;
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

    // Coverage failure still applies the reply: a view panned past every
    // cached window must never sit on a blank frame waiting for points (T1).
    view.view = { x0: v0.x1 + sx, x1: v0.x1 + 2 * sx, y0: v0.y0, y1: v0.y1 };
    applyDensity(v0.x1 + sx, v0.x1 + 2 * sx, v0.y0, v0.y1, 50, 40, 5000000);
    const uncoveredApplied = g.density !== shownBefore && g.density.visible === 5000000;

    document.body.setAttribute("data-xy-economy-probe", JSON.stringify({
      hasDensity: !!g, homeHasCount, standingHeld, factsStored,
      stepSent, stepAligned, stepMarked, stepApplied,
      insideElided, elisionClearedPending, bandRequested, bandIsRawView,
      nearDrillRequested,
      sentBase, subTexelSuppressed, texelsRequested,
      densityDraws, uncoveredApplied,
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
    # Display side: a mid-band aggregate reply repaints NOTHING while a
    # covering texture stands — it lands as facts for the gate; a reply for
    # an uncovered view still applies (never a blank frame, T1).
    assert result["standingHeld"] is True
    assert result["factsStored"] is True
    assert result["uncoveredApplied"] is True
    # The stepped ladder: a standing view whose covering texture is coarser
    # than its step requests the QUANTIZED aligned step window (never the
    # raw view window), marks it, and that reply repaints; the same view
    # afterwards requests nothing.
    assert result["stepSent"] is True
    assert result["stepAligned"] is True
    assert result["stepMarked"] is True
    assert result["stepApplied"] is True
    assert result["insideElided"] is True
    assert result["elisionClearedPending"] is True
    # The points band and points-scale windows still request the RAW view —
    # the kernel keeps deciding with real counts everywhere it could answer
    # sharper.
    assert result["bandRequested"] is True
    assert result["bandIsRawView"] is True
    assert result["nearDrillRequested"] is True
    # Sub-texel dedup: same picture, no second request; a real shift sends.
    assert result["sentBase"] is True
    assert result["subTexelSuppressed"] is True
    assert result["texelsRequested"] is True
    # Exactly one aggregate texture per settled frame — no detail stacking.
    assert result["densityDraws"] == 1
