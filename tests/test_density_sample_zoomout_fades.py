"""The drawn density sample always describes the displayed window (§28, T9).

Exact-scan density replies ship a deterministic point sample for *their*
window; zoom-out replies (pyramid and integral-image servers alike)
intentionally omit one. Samples therefore ride the density cache entry they
were computed for, and each frame draws the overlay of the best cached window
for the current view: the smallest window that covers the view wins at full
alpha, so a deep zoom-out falls back through the cache to the HOME sample and
the full point cloud returns — points on screen always describe the window
being displayed (the original field bug: a drilled window's sample lingered
over every later zoom-out as an opaque "stuck point blob").

Only a view that NO cached window covers draws a partial overlay, bounded by
the T9 coverage fade — and the band value is a *composited* opacity target
(per-point alpha solved against the expected overplot), because compositing
~13 overlapping layers of a mid-band alpha renders a near-opaque slab (a
"fading" sample that never looked faded). The "sampled n of N" badge tracks
what is actually drawn.

This drives the real client in headless Chromium: it applies a density update
carrying a small-window sample W, then asserts W's overlay draws inside W, the
home overlay takes over (full alpha) on zoom-out, the no-coverage fallback is
overplot-compensated, far past everything nothing draws (badge off), and W's
overlay returns on zoom back in.
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
    // A sub-window sample, as an exact-scan reply for a zoomed-in view would
    // ship: window W = 1/10 of home linearly (1/100 of the area).
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const N = 500;
    const xs = new Float32Array(N), ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
    }
    // Density update for W carrying the sample (grid 4x4 is enough).
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

    // Record every sampled-tier overlay drawn in one frame: {n, alpha}.
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
    const badgeShowsSample = () =>
      view._reductionBadgeItems().some((i) => i.indexOf("sampled") === 0);
    const zoomTo = (f) => {
      view.view = {
        x0: cx - (wx1 - wx0) * f / 2, x1: cx + (wx1 - wx0) * f / 2,
        y0: cy - (wy1 - wy0) * f / 2, y1: cy + (wy1 - wy0) * f / 2,
      };
    };

    // Inside W: W's own overlay draws at full alpha, badge on.
    zoomTo(1);
    const atWindow = sampleDrawn();
    const atWindowBadge = badgeShowsSample();
    // 4x linear zoom-out: the view has outgrown W but the HOME window covers
    // it — the home sample takes over at FULL alpha (points always describe
    // the displayed window; no lingering drilled cluster).
    zoomTo(4);
    const homeTakeover = sampleDrawn();
    const homeTakeoverBadge = badgeShowsSample();
    // 40x linear (4x past home): nothing covers the view; the home overlay is
    // the best partial and draws inside the T9 band — overplot-compensated,
    // so the drawn alpha is far below the raw band value (1/3 at coverage
    // 1/16) instead of compositing into an opaque slab.
    zoomTo(40);
    const fallback = sampleDrawn();
    // 400x linear: past the band entirely — nothing drawn, badge off.
    zoomTo(400);
    const farOut = sampleDrawn();
    const farOutBadge = badgeShowsSample();
    // Deep INSIDE W (view 1/100 of the window's area): the fixed sampling
    // fraction leaves ~5 expected in-view points — a handful of dots standing
    // in for the window's real rows lies in the other direction, so the
    // zoom-in bound hides the overlay (and its badge) too.
    zoomTo(0.1);
    const zoomedIn = sampleDrawn();
    const zoomedInBadge = badgeShowsSample();
    // Zoom back into W: its overlay and badge return (pure function of the
    // view and the cache, no stuck state).
    zoomTo(1);
    const backIn = sampleDrawn();
    const backInBadge = badgeShowsSample();

    // Sticky selection: a near-equal window (5% wider, as successive
    // locally-served replies produce at a settled zoom) carrying its own
    // subset must NOT steal the frame from the overlay already on screen —
    // that flip re-rolled the drawn dots reply after reply ("jumping
    // around" at a settled zoom). A genuinely finer window still wins.
    const w2x0 = cx - sx * 0.0525, w2x1 = cx + sx * 0.0525;
    const w2y0 = cy - sy * 0.0525, w2y1 = cy + sy * 0.0525;
    const N2 = 400;
    const xs2 = new Float32Array(N2), ys2 = new Float32Array(N2);
    for (let i = 0; i < N2; i++) {
      xs2[i] = w2x0 + (w2x1 - w2x0) * ((i * 0.6180339887) % 1);
      ys2[i] = w2y0 + (w2y1 - w2y0) * ((i * 0.3141592653) % 1);
    }
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 90000,
        density: {
          buf: 0, w: gw, h: gh, max: 3,
          x_range: [w2x0, w2x1], y_range: [w2y0, w2y1],
          sample: {
            n: 90000, visible: 90000,
            x: { buf: 1, offset: 0, scale: 1, len: N2 },
            y: { buf: 2, offset: 0, scale: 1, len: N2 },
            x_range: [w2x0, w2x1], y_range: [w2y0, w2y1],
          },
        },
      }],
    }, [grid.buffer, xs2.buffer, ys2.buffer]);
    // Simulate W2's overlay being the one on screen; W (5% smaller) is the
    // strictly-smallest containing window — without stickiness it would win
    // and swap the dots.
    g._shownSampleOverlay = g.density.overlay;
    const stickyKept = sampleDrawn();

    document.body.setAttribute("data-xy-sample-probe", JSON.stringify({
      hasHomeOverlay: !!(g.density && g.densityCache && g.densityCache.some((d) => d && d.overlay)),
      windowN: N,
      atWindow, atWindowBadge, homeTakeover, homeTakeoverBadge,
      fallback, farOut, farOutBadge, zoomedIn, zoomedInBadge,
      backIn, backInBadge, stickyKept,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-sample-probe-error",
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


def test_drawn_sample_tracks_the_displayed_window(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "sample_zoomout_fade.html",
        "data-xy-sample-probe",
        label="sample window-pairing probe",
    )

    assert result["hasHomeOverlay"] is True
    n_w = result["windowN"]
    # Inside W the reply's own sample owns the hybrid look, badge on.
    assert result["atWindow"] is not None
    assert result["atWindow"]["n"] == n_w
    assert result["atWindow"]["alpha"] == 1
    assert result["atWindowBadge"] is True
    # Zoomed out past W: the home sample takes over at FULL alpha — the point
    # cloud for the displayed window, not W's stale cluster (the regression).
    assert result["homeTakeover"] is not None
    assert result["homeTakeover"]["n"] > n_w
    assert result["homeTakeover"]["alpha"] == 1
    assert result["homeTakeoverBadge"] is True
    # Past every cached window the best partial draws inside the T9 band,
    # overplot-compensated: the raw band value at coverage 1/16 is 1/3, but
    # ~13 point layers per pixel must composite to ~the band value, so the
    # per-point alpha collapses well below it.
    assert result["fallback"] is not None
    assert result["fallback"]["n"] > n_w
    assert 0 < result["fallback"]["alpha"] < 0.15
    # Far past the band: nothing drawn, badge off.
    assert result["farOut"] is None
    assert result["farOutBadge"] is False
    # Deep inside W the zoom-in bound hides the overlay: ~5 expected in-view
    # points must not masquerade as "the data" (the mirror-image lie of the
    # zoom-out blob), and the badge goes with it.
    assert result["zoomedIn"] is None
    assert result["zoomedInBadge"] is False
    # Back inside W: its overlay and badge return; nothing latched.
    assert result["backIn"] is not None
    assert result["backIn"]["n"] == n_w
    assert result["backIn"]["alpha"] == 1
    assert result["backInBadge"] is True
    # Sticky selection: with W2's near-equal overlay on screen, the strictly
    # smaller W must not steal the frame — the drawn set stays W2's (n=400),
    # so settled zooms don't re-roll the dots on every reply.
    assert result["stickyKept"] is not None
    assert result["stickyKept"]["n"] == 400
