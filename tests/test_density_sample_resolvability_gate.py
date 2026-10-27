"""Sample overlays draw only below the resolvable-count gate (#225).

Above the drill budget, a fixed-size sample reads as individual data points at
a zoom where real points are sub-pixel — sampling above the resolution of the
graph misrepresents the dataset (the issue's field capture: zooming out from a
drilled window brought "individual points" back over a 100M-point cloud). The
client therefore gates every overlay candidate on the estimated in-view count:
the overlay's recorded window count scaled by the view's share of its window,
drawn only when that fits LOD_DIRECT_POINT_BUDGET. In kernel mode the gate
makes the hybrid look transient at most (interactive density replies ship no
samples anymore; real points arrive when a window fits the budget); standalone
exports keep the overlay as their only point representation once a zoom
resolves it.

This drives the real client in headless Chromium: an overlay whose window
holds far more points than the budget must NOT draw even when its window
covers the view exactly (badge off — density-only), while zooming deep enough
into the same window that the estimated in-view count fits the budget brings
the overlay (and badge) back. With a kernel attached the overlay never draws
at all — resolvable views get REAL points from the kernel, so retained
sample rows there read as data that isn't (#225 field follow-up).
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
    // Window W = central 20% of home; its sample CLAIMS 10M points in-window
    // (a 100M-point-cloud zoom level) — far past the 200k direct budget.
    const wx0 = cx - sx * 0.1, wx1 = cx + sx * 0.1;
    const wy0 = cy - sy * 0.1, wy1 = cy + sy * 0.1;
    const N = 400;
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
        id: g.trace.id, mode: "density", visible: 10000000,
        density: {
          buf: 0, w: gw, h: gh, max: 3,
          x_range: [wx0, wx1], y_range: [wy0, wy1],
          sample: {
            n: N, visible: 10000000,
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
    const badgeShowsSample = () =>
      view._reductionBadgeItems().some((i) => i.indexOf("sampled") === 0);
    const zoomTo = (f) => {
      view.view = {
        x0: cx - (wx1 - wx0) * f / 2, x1: cx + (wx1 - wx0) * f / 2,
        y0: cy - (wy1 - wy0) * f / 2, y1: cy + (wy1 - wy0) * f / 2,
      };
    };

    // Model the 100M-cloud scenario: the HOME overlay too must claim a count
    // far past the budget (the real chart under this probe holds only 60k
    // points, whose overlay would honestly — and correctly — keep drawing).
    const homeOverlay = g.sampleOverlay;
    const homeVisible = homeOverlay.sample.visible;
    homeOverlay.sample.visible = 100000000;

    // At W itself: 10M estimated in view — W's overlay must NOT draw even
    // though its window covers the view exactly, and the home overlay (1e8)
    // is gated too. Density-only, badge off.
    zoomTo(1);
    const atWindow = sampleDrawn();
    const atWindowBadge = badgeShowsSample();

    // At home: nothing resolvable anywhere — the #225 field capture's fix:
    // no individual points over a 100M-point aggregate.
    view.view = { ...v0 };
    const atBigHome = sampleDrawn();

    // 1/16 of W linearly (1/256 of the area): W's estimated in-view count is
    // ~39k <= budget — the overlay (and badge) return: points are resolvable.
    zoomTo(1 / 16);
    const deepIn = sampleDrawn();
    const deepInBadge = badgeShowsSample();

    // Just under the gate boundary from above: 1/4 linear = 1/16 area →
    // 625k estimated, still over budget — still density-only.
    zoomTo(1 / 4);
    const midway = sampleDrawn();

    // Restore the honest 60k home count: a dataset under the budget is
    // resolvable everywhere and keeps the hybrid look, home included.
    homeOverlay.sample.visible = homeVisible;
    view.view = { ...v0 };
    const atHome = sampleDrawn();
    const atHomeBadge = badgeShowsSample();

    // Kernel-attached clients NEVER draw retained samples (#225 field
    // follow-up): wherever a view is resolvable, the kernel ships REAL
    // points — a handful of arbitrary sample rows at full alpha there reads
    // as data that isn't. The overlay is the standalone client's fallback.
    view.comm = { send: () => {} };
    const kernelAtHome = sampleDrawn();
    zoomTo(1 / 16);
    const kernelDeepIn = sampleDrawn();
    const kernelBadge = badgeShowsSample();
    view.comm = null;
    view.view = { ...v0 };

    document.body.setAttribute("data-xy-gate-probe", JSON.stringify({
      hasOverlays: !!(g.densityCache && g.densityCache.some((d) => d && d.overlay)),
      windowN: N,
      atWindow, atWindowBadge, atBigHome, deepIn, deepInBadge, midway,
      atHome, atHomeBadge, kernelAtHome, kernelDeepIn, kernelBadge,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-gate-probe-error",
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


def test_sample_overlay_gated_by_resolvable_count(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "sample_resolvability_gate.html",
        "data-xy-gate-probe",
        label="sample resolvability-gate probe",
    )

    assert result["hasOverlays"] is True
    # 10M points estimated in view: no overlay, no badge — density-only. This
    # is the #225 contract: no sampled points above the graph's resolution.
    assert result["atWindow"] is None
    assert result["atWindowBadge"] is False
    # Home over a (claimed) 100M cloud: density-only there too.
    assert result["atBigHome"] is None
    # Still over budget at 1/16 of the window's area: still density-only.
    assert result["midway"] is None
    # Deep enough that the estimated in-view count fits the budget: the
    # overlay returns at full alpha, badge on.
    assert result["deepIn"] is not None
    assert result["deepIn"]["n"] == result["windowN"]
    assert result["deepIn"]["alpha"] == 1
    assert result["deepInBadge"] is True
    # A dataset under the budget is resolvable everywhere: its home overlay
    # keeps drawing (nothing changes for small charts) — in STANDALONE mode.
    assert result["atHome"] is not None
    assert result["atHomeBadge"] is True
    # With a kernel attached the overlay never draws at any zoom: resolvable
    # views get real points from the kernel, not retained sample rows.
    assert result["kernelAtHome"] is None
    assert result["kernelDeepIn"] is None
    assert result["kernelBadge"] is False
