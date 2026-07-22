"""The retained density sample must fade out on deep zoom-out (§28, T9).

Exact-scan density replies ship a deterministic point sample for *their*
window; zoom-out replies (pyramid and integral-image servers alike)
intentionally omit one, so the client retains the last sample for the hybrid
"density + points" look across pans and mild zoom-outs (#24).

The bug: the retained sample was drawn whenever the view merely *overlapped*
its window. Zoomed far out, the same ~8k points compress into a tiny screen
region and overplot into a solid dark rectangle — the zoom-out "stuck point
blob" pinned by the live-drilldown HAR: the blob's extent matched the last
`sample`-bearing response's window exactly, while the density surface under it
kept updating correctly.

The fix bounds the retained overlay by coverage: full alpha while the sample
window covers ≥ 1/16 of the view area, hidden below 1/64, log-eased between —
and the "sampled n of N" badge tracks what is actually drawn.

This drives the real client in headless Chromium: it applies a density update
carrying a small-window sample, then asserts the overlay draws inside/near the
window, fades at the band edge, and is gone (badge included) far outside.
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
    // ship: window = 1/10 of home linearly (1/100 of the area).
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const N = 500;
    const xs = new Float32Array(N), ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
    }
    // Density update for the window carrying the sample (grid 4x4 is enough).
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
      let drawn = 0;
      const real = view._drawPoints;
      view._drawPoints = function (d, xm, ym, alpha) {
        if (d === g.sampleOverlay) drawn = alpha === undefined ? 1 : alpha;
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

    // At the sample's own window: fully drawn, badge on.
    zoomTo(1);
    const atWindow = sampleDrawn();
    const atWindowBadge = badgeShowsSample();
    // 2x linear zoom-out (coverage 1/4, above the band): still fully drawn.
    zoomTo(2);
    const mildOut = sampleDrawn();
    // 6x linear (coverage 1/36, inside the band): fading, strictly between.
    zoomTo(6);
    const fading = sampleDrawn();
    // 10x linear (coverage 1/100, past the band): hidden, badge off.
    zoomTo(10);
    const farOut = sampleDrawn();
    const farOutBadge = badgeShowsSample();
    // Zooming back in restores the overlay and its badge (pure function of
    // the view, no stuck state).
    zoomTo(1);
    const backIn = sampleDrawn();
    const backInBadge = badgeShowsSample();

    document.body.setAttribute("data-xy-sample-probe", JSON.stringify({
      hasSample: !!g.sampleOverlay,
      atWindow, atWindowBadge, mildOut, fading, farOut, farOutBadge,
      backIn, backInBadge,
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


def test_retained_sample_fades_past_zoomout_bound(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "sample_zoomout_fade.html",
        "data-xy-sample-probe",
        label="retained-sample zoom-out fade probe",
    )

    assert result["hasSample"] is True
    # Inside/at its window the sample owns the hybrid look, badge on.
    assert result["atWindow"] == 1
    assert result["atWindowBadge"] is True
    # A mild zoom-out (coverage 1/4) keeps it fully drawn (#24 preserved).
    assert result["mildOut"] == 1
    # Inside the fade band it draws at reduced alpha.
    assert 0 < result["fading"] < 1
    # Far past the band: not drawn at all — this is the regression (the
    # pre-fix client kept painting it as an opaque blob) — and not badged.
    assert result["farOut"] == 0
    assert result["farOutBadge"] is False
    # Zoom back in: overlay and badge return; nothing latched.
    assert result["backIn"] == 1
    assert result["backInBadge"] is True
