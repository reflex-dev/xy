"""Retired exact point windows are cached and promoted, never re-requested
(LOD doc T13).

"Once we get points, we can render anything inside there without further
requests": a points reply for a NEW window retires the previous exact window
into a per-trace LRU cache instead of overwriting its buffers; any later view
covered by a cached window promotes it back to the live drill with no kernel
round-trip — pan ping-pong across a window boundary and zoom-out/zoom-in
sequences render entirely from the GPU. A drill dying OUTSIDE its window
(zoom-out to density) retires the same way, so diving back into the region it
covered is also free. Cached windows obey the live drill's geometry-only
memory discipline (T11): once the view outgrows a window past the drill
budget, its buffers free with no kernel reply required (§27).

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
    const sx = v0.x1 - v0.x0, sy = v0.y1 - v0.y0;
    const sent = [];
    view.comm = { send: (m) => sent.push(m) };
    const densitySent = () => sent.filter((m) => m.type === "density_view").length;

    // A points reply for a window spanning [fx0, fx1] x [fy0, fy1] of home
    // (fractions), claiming `visible` in-window points.
    const N = 600;
    let nextSeq = 1;
    const applyPoints = (fx0, fx1, fy0, fy1, visible) => {
      const wx0 = v0.x0 + sx * fx0, wx1 = v0.x0 + sx * fx1;
      const wy0 = v0.y0 + sy * fy0, wy1 = v0.y0 + sy * fy1;
      const xs = new Float32Array(N), ys = new Float32Array(N);
      for (let i = 0; i < N; i++) {
        xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
        ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
      }
      view._applyDrill(g, {
        id: g.trace.id, mode: "points", visible, reduction: "none",
        drill_seq: nextSeq++,
        x: { buf: 0, offset: 0, scale: 1, len: N },
        y: { buf: 1, offset: 0, scale: 1, len: N },
        x_range: [wx0, wx1], y_range: [wy0, wy1],
      }, [xs.buffer, ys.buffer]);
      return { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    };
    const viewIn = (w, m) => ({
      x0: w.x0 + (w.x1 - w.x0) * m, x1: w.x1 - (w.x1 - w.x0) * m,
      y0: w.y0 + (w.y1 - w.y0) * m, y1: w.y1 - (w.y1 - w.y0) * m,
    });
    const sameWin = (a, b) => a && b &&
      Math.abs(a.x0 - b.x0) + Math.abs(a.x1 - b.x1) +
      Math.abs(a.y0 - b.y0) + Math.abs(a.y1 - b.y1) < (sx + sy) * 1e-9;
    const request = (v) => {
      const before = densitySent();
      view._scheduleViewRequest(view._viewFrom(v), { delay: 0 });
      return densitySent() - before;
    };

    // Drill into window A, then a points reply for a DISJOINT window B lands
    // (a pan): A retires into the cache instead of being overwritten.
    const winA = applyPoints(0.10, 0.20, 0.10, 0.20, 600);
    const seqA = 1;
    const winB = applyPoints(0.30, 0.40, 0.30, 0.40, 600);
    const retiredA = !!(g.drillCache && g.drillCache.length === 1 &&
      sameWin(g.drillCache[0].win, winA));
    const liveIsB = sameWin(g.drill.win, winB) && g.drill.seq === 2;

    // Pan back to a view inside A: promoted from the cache, no wire request,
    // and picks keep speaking A's subset version (the kernel's history
    // resolves it exactly).
    const promoteElided = request(viewIn(winA, 0.25)) === 0;
    const promotedIsA = sameWin(g.drill.win, winA) && g.drill.seq === seqA;
    const swappedBToCache = !!(g.drillCache && g.drillCache.length === 1 &&
      sameWin(g.drillCache[0].win, winB));

    // A view no cached window covers still requests.
    const elsewhereRequested = request({
      x0: v0.x0 + sx * 0.6, x1: v0.x0 + sx * 0.7,
      y0: v0.y0 + sy * 0.6, y1: v0.y0 + sy * 0.7 }) === 1;

    // LRU bound: windows C, D, E push the cache past its cap; the oldest
    // retired windows fall off, newest survive.
    applyPoints(0.50, 0.60, 0.50, 0.60, 600); // C  (A -> cache)
    applyPoints(0.62, 0.72, 0.62, 0.72, 600); // D  (C -> cache)
    applyPoints(0.74, 0.84, 0.74, 0.84, 600); // E  (D -> cache)
    const cacheBounded = g.drillCache.length <= 3;

    // Zoom-out to density: the drill dies; once its exit fade completes
    // OUTSIDE its window, it retires into the cache (still exact for its
    // window) instead of freeing.
    view.view = { ...v0 };
    const gw = 4, gh = 4;
    const grid = new Float32Array(gw * gh).fill(3);
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 60000,
        density: { buf: 0, w: gw, h: gh, max: 3,
          x_range: [v0.x0, v0.x1], y_range: [v0.y0, v0.y1] },
      }],
    }, [grid.buffer]);
    const dyingAfterDensity = g._drillDying === true;
    view._drawNow();          // exit fade starts
    clk += 500;               // past LOD_EXIT_FADE_MS
    view._drawNow();          // fade complete -> retire
    const winE = { x0: v0.x0 + sx * 0.74, x1: v0.x0 + sx * 0.84,
                   y0: v0.y0 + sy * 0.74, y1: v0.y0 + sy * 0.84 };
    const retiredOnDeath = !g.drill &&
      g.drillCache.some((e) => sameWin(e.win, winE));

    // Dive back into E's region: promoted, zero requests — the #225 workflow
    // (drill, zoom out, drill the same spot) with no re-shipping.
    const reviveElided = request(viewIn(winE, 0.25)) === 0;
    const revivedIsE = !!(g.drill && sameWin(g.drill.win, winE));

    // Geometry-only retirement for cached windows (T11 via T13): claim a
    // budget-scale count on every cached window, zoom far out, and the sweep
    // frees them on that frame — no kernel reply needed.
    for (const e of g.drillCache) e.visible = 150000;
    if (g.drill) g.drill.visible = 150000;
    view.view = { ...v0 };
    view._drawNow();
    const sweptWhenOutgrown = !g.drillCache || g.drillCache.length === 0;

    document.body.setAttribute("data-xy-cache-probe", JSON.stringify({
      hasDensity: !!g,
      retiredA, liveIsB, promoteElided, promotedIsA, swappedBToCache,
      elsewhereRequested, cacheBounded, dyingAfterDensity, retiredOnDeath,
      reviveElided, revivedIsE, sweptWhenOutgrown,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-cache-probe-error",
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


def test_point_windows_cache_promote_and_free(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "drill_point_window_cache.html",
        "data-xy-cache-probe",
        label="point-window cache probe",
    )

    assert result["hasDensity"] is True
    # A new window's reply retires the old exact window instead of
    # overwriting its buffers.
    assert result["retiredA"] is True
    assert result["liveIsB"] is True
    # Pan back inside A: promoted from the cache with no wire request, and
    # the promoted drill keeps A's subset version for picks.
    assert result["promoteElided"] is True
    assert result["promotedIsA"] is True
    assert result["swappedBToCache"] is True
    # Views nothing covers still go to the kernel.
    assert result["elsewhereRequested"] is True
    # The cache is bounded (LRU).
    assert result["cacheBounded"] is True
    # Zoom-out to density retires the dying drill (died outside its window)
    # into the cache once the exit fade completes...
    assert result["dyingAfterDensity"] is True
    assert result["retiredOnDeath"] is True
    # ...so diving back into that region is answered locally, zero requests.
    assert result["reviveElided"] is True
    assert result["revivedIsE"] is True
    # Outgrown cached windows free on the frame, no kernel reply required.
    assert result["sweptWhenOutgrown"] is True
