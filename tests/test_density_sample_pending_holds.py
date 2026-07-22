"""A pending refresh holds the drawn sample overlay — no home flash (T5/T9).

The T9 pure selection draws the overlay of the smallest cached window that
covers the view. On zoom-out that is the home/init overlay, so while the
right-sized reply was still loading the client flashed the initial view's
point cloud, then switched again when the reply landed — a double transition
reading as "the chart reset" (live-drilldown field report).

`lodSampleForViewHeld` keeps the overlay ALREADY on screen while a fresh
refresh for the view is in flight, with its alpha still the pure T9 coverage
function (full while its window covers the view amply, coverage-faded beyond,
invisible past the band — the density backdrop keeps T1). Finer or same-size
switches are never a "reset" and happen immediately, so zoom-in behavior is
unchanged. The reply — or the T8 age-out for a stranded pending — releases
the hold and the pure (view, cache) selection resumes, home takeover
included (the existing zoomout-fades probe pins that baseline).

This drives the real client in headless Chromium: it caches a sub-window
sample W, zooms out with a fresh pending and asserts W's overlay (not home's)
is drawn at the T9 banded alpha; delivers the reply and asserts home takes
over; re-holds and strands the pending to assert the age-out releases it; and
zooms back in under a pending to assert finer switches are not held.
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
    // A sub-window sample, as an exact-scan reply for a zoomed-in view ships:
    // window W = 1/10 of home linearly (1/100 of the area).
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const N = 500;
    const xs = new Float32Array(N), ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
    }
    const gw = 4, gh = 4;
    const grid = new Float32Array(gw * gh).fill(3);
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 100000,
        density: {
          buf: 0, w: gw, h: gh, max: 3,
          x_range: [wx0, wx1], y_range: [wy0, wy1],
          sample: {
            n: 100000, visible: 100000,
            x: { buf: 1, offset: 0, scale: 1, len: N },
            y: { buf: 2, offset: 0, scale: 1, len: N },
            x_range: [wx0, wx1], y_range: [wy0, wy1],
          },
        },
      }],
    }, [grid.buffer, xs.buffer, ys.buffer]);

    const sampleDrawn = () => {
      let drawn = null;
      const real = view._drawPoints;
      view._drawPoints = function (d, xm, ym, alpha) {
        if (d && d.tier === "sampled") drawn = { n: d.n, alpha: alpha === undefined ? 1 : alpha };
        return real.apply(this, arguments);
      };
      view._drawNow();
      view._drawPoints = real;
      return drawn;
    };
    const zoomTo = (f) => {
      view.view = {
        x0: cx - (wx1 - wx0) * f / 2, x1: cx + (wx1 - wx0) * f / 2,
        y0: cy - (wy1 - wy0) * f / 2, y1: cy + (wy1 - wy0) * f / 2,
      };
    };
    const armPending = () => {
      g._lodPendingView = { ...view.view };
      g._lodPendingSeq = view.seq;
      g._lodPendingAt = clk;
    };

    // Inside W: W's own overlay draws at full alpha.
    zoomTo(1);
    const atWindow = sampleDrawn();

    // 4x linear zoom-out WITH a fresh pending: the home window covers the
    // view, but the hold keeps W's overlay on screen at the T9 banded alpha
    // (coverage 1/16 sits inside the fade band, so alpha < 1) — the pre-fix
    // client switched to the home/init overlay at full alpha here.
    zoomTo(4);
    armPending();
    const heldOut = sampleDrawn();

    // The reply lands (no sample of its own — the pyramid zoom-out shape):
    // pendings clear, the pure T9 selection resumes, home takes over fully.
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 4000000,
        density: {
          buf: 0, w: gw, h: gh, max: 3,
          x_range: [view.view.x0, view.view.x1], y_range: [view.view.y0, view.view.y1],
        },
      }],
    }, [grid.buffer]);
    const afterReply = sampleDrawn();

    // Zoom back into W (its overlay returns — pure function of view+cache),
    // then re-hold on a zoom-out and STRAND the pending: the T8 age-out must
    // release the hold with no reply at all.
    zoomTo(1);
    sampleDrawn();
    zoomTo(4);
    armPending();
    const heldAgain = sampleDrawn();
    g._lodPendingAt = clk - 5000;
    const afterStranded = sampleDrawn();

    // Zoom-IN under a pending is never held: from the home view, entering W
    // switches to W's finer overlay immediately.
    zoomTo(40);
    view._drawNow(); // shown overlay is now home's
    const atHome = sampleDrawn();
    zoomTo(1);
    armPending();
    const zoomInSwitch = sampleDrawn();

    document.body.setAttribute("data-xy-sample-hold-probe", JSON.stringify({
      hasHomeOverlay: !!(g.densityCache && g.densityCache.some((d) => d && d.overlay)),
      windowN: N,
      atWindow, heldOut, afterReply, heldAgain, afterStranded,
      atHome, zoomInSwitch,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-sample-hold-probe-error",
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


def test_pending_refresh_holds_drawn_sample_overlay(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "sample_pending_hold.html",
        "data-xy-sample-hold-probe",
        label="sample pending-hold probe",
    )

    assert result["hasHomeOverlay"] is True
    n_w = result["windowN"]
    assert result["atWindow"] is not None and result["atWindow"]["n"] == n_w
    assert result["atWindow"]["alpha"] == 1
    # Zoomed out with a fresh pending: W's overlay HOLDS (not home's), faded
    # by the T9 coverage band — never a full-alpha initial-view flash.
    assert result["heldOut"] is not None
    assert result["heldOut"]["n"] == n_w
    assert 0 < result["heldOut"]["alpha"] < 1
    # The reply releases the hold; the pure T9 home takeover resumes.
    assert result["afterReply"] is not None
    assert result["afterReply"]["n"] > n_w
    assert result["afterReply"]["alpha"] == 1
    # A stranded pending ages out (T8) and releases the hold with no reply.
    assert result["heldAgain"] is not None and result["heldAgain"]["n"] == n_w
    assert result["afterStranded"] is not None
    assert result["afterStranded"]["n"] > n_w
    assert result["afterStranded"]["alpha"] == 1
    # Zoom-in under a pending switches to the finer overlay immediately.
    assert result["atHome"] is not None and result["atHome"]["n"] > n_w
    assert result["zoomInSwitch"] is not None
    assert result["zoomInSwitch"]["n"] == n_w
