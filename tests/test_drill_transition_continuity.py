"""Drill transitions are continuous: backdrop, colors, and stale replies (§5).

The live-drilldown field capture showed three compounding discontinuities
while zooming across the drill boundary:

- the frame flipped between "density texture" and "marks on a blank
  background" (marks used to own the frame once their entry fade finished);
- the marks' colors jumped at the swap — the kernel's `lod_blend` weight
  assumes level-by-level zooms, so a fast zoom landed marks with a
  mostly-native weight over a differently-colored texture;
- a points reply for a window the view had already outgrown (fast zoom-out
  racing a slow scan) revived the drill and flipped the frame back.

The fixes, each asserted here against the real client in headless Chromium:

- T10 continuous backdrop: the aggregate texture draws under the marks in
  every drill state — entering, settled, held, exiting.
- Fresh marks enter wearing the aggregate's colormap (`lodBlendShown` seeds
  at 1) and dying/exiting marks re-target blend 1, so both directions of the
  texture↔marks swap are color-continuous regardless of skipped levels.
- A points reply whose window the view has grown far past still applies (the
  kernel may prefetch), but its marks are not drawn for a view that never
  entered the window — the frame stays on the aggregate.
- T11 geometry-only retirement: an entered-then-exited drill frees its GPU
  buffers once the view outgrows its window past the drill budget, with no
  kernel reply required; never-entered prefetches are exempt.
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
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const N = 400;
    const xs = new Float32Array(N), ys = new Float32Array(N), dv = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
      dv[i] = (i % 100) / 100;
    }
    const pointsReply = (seq, drillSeq) => ({
      type: "density_update", seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "points", visible: 1500, drill_seq: drillSeq,
        x: { buf: 0, offset: 0, scale: 1, len: N },
        y: { buf: 1, offset: 0, scale: 1, len: N },
        x_range: [wx0, wx1], y_range: [wy0, wy1],
        density_val: { buf: 2 },
        lod_blend: 0.05,  // a deep, mostly-native weight — the fast-zoom case
        density_colormap: "viridis",
      }],
    });

    // Enter the drill: view inside W, points reply applies.
    view.view = { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    view._onKernelMsg(pointsReply(view.seq, 1), [xs.buffer, ys.buffer, dv.buffer]);
    const enterBlendShown = g.drill ? g.drill.lodBlendShown : null;
    const enterBlendTarget = g.drill ? g.drill.lodBlend : null;

    // Settle the entry fade, then check a settled inside frame draws the
    // aggregate UNDER the marks (T10) — previously marks owned the frame.
    const frameLayers = () => {
      let density = 0, marks = 0;
      const rd = view._drawDensity, rp = view._drawPoints;
      view._drawDensity = function () { density += 1; return rd.apply(this, arguments); };
      view._drawPoints = function (d) { if (d === g.drill) marks += 1; return rp.apply(this, arguments); };
      view._drawNow();
      view._drawDensity = rd;
      view._drawPoints = rp;
      return { density, marks };
    };
    view._drawNow(); clk += 500; view._drawNow();
    const settledInside = frameLayers();

    // A density update arrives (zoom-out swap): the dying marks re-target the
    // aggregate's colormap so they melt into the texture as they fade.
    const gw = 4, gh = 4;
    const grid = new Float32Array(gw * gh).fill(3);
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 100000,
        density: { buf: 0, w: gw, h: gh, max: 3,
          x_range: [wx0, wx1], y_range: [wy0, wy1] },
      }],
    }, [grid.buffer]);
    const exitBlendTarget = g.drill ? g.drill.lodBlend : null;
    const exitLayers = frameLayers(); // mid exit fade: texture + fading marks
    clk += 500; view._drawNow(); // fade completes, drill frees

    // A late points reply for a window the view has far outgrown (fast
    // zoom-out racing a slow scan) still APPLIES — the wire contract; the
    // kernel may legitimately prefetch — but the frame stays density-only:
    // marks for a window the view never entered are not drawn, so the reply
    // cannot flip the frame back to points (the flicker's second half).
    view.view = {
      x0: cx - sx * 2, x1: cx + sx * 2,
      y0: cy - sy * 2, y1: cy + sy * 2,
    };
    view._onKernelMsg(pointsReply(view.seq, 2), [xs.buffer, ys.buffer, dv.buffer]);
    const departedApplied = !!g.drill;
    const departedLayers = frameLayers();
    // A never-entered (prefetch-shaped) drill survives frames at a view far
    // past its window — T11 retirement is armed only by a completed entry.
    const departedStillAllocated = !!g.drill;

    // The same reply while the view is INSIDE the window draws marks again.
    view.view = { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    view._onKernelMsg(pointsReply(view.seq, 3), [xs.buffer, ys.buffer, dv.buffer]);
    const insideLayers = frameLayers();

    // Geometry-only retirement (T11): the entered drill exits by zoom alone —
    // no pending request, no density reply — and once the view outgrows its
    // window past the drill budget the buffers free without a kernel
    // round-trip (previously they were stranded until a density reply).
    view.view = {
      x0: cx - (wx1 - wx0) * 8, x1: cx + (wx1 - wx0) * 8,
      y0: cy - (wy1 - wy0) * 8, y1: cy + (wy1 - wy0) * 8,
    };
    view._drawNow();
    clk += 500; view._drawNow();
    const geometryRetired = !g.drill;

    document.body.setAttribute("data-xy-transition-probe", JSON.stringify({
      enterBlendShown, enterBlendTarget,
      settledInside, exitBlendTarget, exitLayers,
      departedApplied, departedLayers, departedStillAllocated,
      insideLayers, geometryRetired,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-transition-probe-error",
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


def test_drill_transitions_are_continuous(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "drill_transition_continuity.html",
        "data-xy-transition-probe",
        label="drill transition continuity probe",
    )

    # Fresh marks enter wearing the aggregate's colormap (shown blend seeds at
    # 1) and ease toward the kernel's native weight.
    assert result["enterBlendShown"] == 1
    assert result["enterBlendTarget"] == pytest.approx(0.05)
    # T10: a settled inside frame still draws the aggregate under the marks —
    # the backdrop never flips to the blank chart background.
    assert result["settledInside"]["density"] >= 1
    assert result["settledInside"]["marks"] >= 1
    # Dying marks re-target the aggregate's colormap for the exit.
    assert result["exitBlendTarget"] == 1
    # And the exit frame is texture + fading marks, not a hard cut.
    assert result["exitLayers"]["density"] >= 1
    assert result["exitLayers"]["marks"] >= 1
    # A points reply for a window the view has far outgrown applies (wire
    # contract — the kernel may prefetch) but the frame stays density-only:
    # no marks flip for a departed view.
    assert result["departedApplied"] is True
    assert result["departedLayers"]["density"] >= 1
    assert result["departedLayers"]["marks"] == 0
    # …and the never-entered drill survives those frames: T11 retirement is
    # armed only by a completed entry, so prefetches are never reaped while
    # the view is (normally) still far from their window.
    assert result["departedStillAllocated"] is True
    # The same reply while the view sits inside its window draws marks.
    assert result["insideLayers"]["marks"] >= 1
    # Geometry-only retirement (T11): entered, then zoomed far out with no
    # pending and no reply — the drill frees on the exit-completion frame.
    assert result["geometryRetired"] is True
