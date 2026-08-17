"""Live-browser ``legend(loc="best")`` placement regressions (#485).

Static writers keep the concrete location selected while the payload is built;
the browser additionally receives ``auto_loc="best"`` and may reconsider that
fallback against the pixels visible after layout, resize, or a settled view
change.  These probes exercise the shipped standalone client, including all
four required Cartesian mark families and a DOM annotation label.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

import xy
from conftest import probe_document, run_browser_probe
from xy.export import find_chromium

ROOT = Path(__file__).resolve().parents[1]
CHARTVIEW = ROOT / "js" / "src" / "50_chartview.ts"
KERNEL = ROOT / "js" / "src" / "54_kernel.ts"


_SETTLED_VIEW_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._drawNow();
    const legend = document.querySelector('[data-xy-slot="legend"]');
    if (!legend) throw new Error("legend never rendered");
    const initial = legend.dataset.xyLegendLoc;
    const initialAnnotationLabels = document.querySelectorAll(
      '[data-xy-slot="annotation_label"]'
    ).length;

    // Directly probe the pure candidate helper through its ChartView bridge:
    // an empty raster takes the first deterministic candidate, while an
    // occupied upper-right box advances to the next empty candidate.
    const raster = { occupancy: new Uint8Array(100 * 100), w: 100, h: 100 };
    const fakeLegend = {
      getBoundingClientRect: () => ({
        width: view.plot.w * 0.20,
        height: view.plot.h * 0.20,
      }),
    };
    const emptyWinner = view._bestLegendLocationForRaster(raster, fakeLegend);

    // One occupied cell is not a near-tie: exact minimum overlap must choose
    // the first actually-empty candidate. A completely dense raster is a true
    // tie and therefore retains canonical upper-right preference.
    const sparseRaster = { occupancy: new Uint8Array(100 * 100), w: 100, h: 100 };
    sparseRaster.occupancy[5 * 100 + 95] = 1;
    const sparseWinner = view._bestLegendLocationForRaster(sparseRaster, fakeLegend);
    const denseRaster = { occupancy: new Uint8Array(100 * 100), w: 100, h: 100 };
    denseRaster.occupancy.fill(1);
    const denseWinner = view._bestLegendLocationForRaster(denseRaster, fakeLegend);

    for (let y = 0; y < 30; y++) {
      for (let x = 70; x < 100; x++) raster.occupancy[y * 100 + x] = 1;
    }
    const occupiedWinner = view._bestLegendLocationForRaster(raster, fakeLegend);

    // Move the upper-right cluster into the lower-left of a zoomed viewport.
    // The update frame must retain the previous winner; only the matching end
    // phase is allowed to rescore and move the box.
    view._setView(
      { ranges: { x: [0.8, 1.0], y: [0.8, 1.0] } },
      {
        animate: false,
        request: false,
        source: "legend_probe",
        phase: "update",
        interactionId: 901,
      },
    );
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._drawNow();
    const duringUpdate = legend.dataset.xyLegendLoc;

    view._emitViewChange("legend_probe", {
      axes: ["x", "y"],
      phase: "end",
      interactionId: 901,
      broadcast: false,
    });
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._drawNow();
    const settled = legend.dataset.xyLegendLoc;

    const flush = () => {
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
    };
    const cancelUpdatedPan = (kind, pointerId) => {
      view._setView(
        { ranges: { x: [0.8, 1.0], y: [0.8, 1.0] } },
        { animate: false, request: false, source: "legend_cancel_reset" },
      );
      flush();
      view.dragMode = "pan";
      const rect = view.canvas.getBoundingClientRect();
      const start = { x: rect.left + rect.width * 0.15, y: rect.top + rect.height * 0.85 };
      const finish = { x: rect.left + rect.width * 0.90, y: rect.top + rect.height * 0.10 };
      view.canvas.dispatchEvent(new PointerEvent("pointerdown", {
        pointerId, pointerType: "mouse", button: 0, buttons: 1,
        clientX: start.x, clientY: start.y, bubbles: true,
      }));
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {
        pointerId, pointerType: "mouse", button: 0, buttons: 1,
        clientX: finish.x, clientY: finish.y, bubbles: true,
      }));
      flush();
      const during = legend.dataset.xyLegendLoc;
      const activeDuring = view._legendBestInteractionActive === true;
      if (kind === "pointercancel") {
        view.canvas.dispatchEvent(new PointerEvent("pointercancel", {
          pointerId, pointerType: "mouse", bubbles: true,
        }));
      } else {
        view.canvas.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Escape", bubbles: true,
        }));
      }
      flush();
      return {
        during,
        activeDuring,
        after: legend.dataset.xyLegendLoc,
        activeAfter: view._legendBestInteractionActive === true,
      };
    };
    const pointerCancel = cancelUpdatedPan("pointercancel", 71);
    const escapeCancel = cancelUpdatedPan("escape", 72);

    const boundedPan = (range, moves, pointerId) => {
      view._setView(
        { ranges: { x: range, y: range } },
        {
          animate: false,
          request: false,
          source: "legend_bounded_pan_reset",
          phase: "end",
        },
      );
      flush();
      view.dragMode = "pan";
      const rect = view.canvas.getBoundingClientRect();
      const start = { x: rect.left + rect.width * 0.5, y: rect.top + rect.height * 0.5 };
      view.canvas.dispatchEvent(new PointerEvent("pointerdown", {
        pointerId, pointerType: "mouse", button: 0, buttons: 1,
        clientX: start.x, clientY: start.y, bubbles: true,
      }));
      const activeDuring = [];
      let last = start;
      for (const [dx, dy] of moves) {
        last = { x: start.x + rect.width * dx, y: start.y + rect.height * dy };
        view.canvas.dispatchEvent(new PointerEvent("pointermove", {
          pointerId, pointerType: "mouse", button: 0, buttons: 1,
          clientX: last.x, clientY: last.y, bubbles: true,
        }));
        flush();
        activeDuring.push(view._legendBestInteractionActive === true);
      }
      view.canvas.dispatchEvent(new PointerEvent("pointerup", {
        pointerId, pointerType: "mouse", button: 0, buttons: 0,
        clientX: last.x, clientY: last.y, bubbles: true,
      }));
      flush();
      return {
        activeDuring,
        activeAfter: view._legendBestInteractionActive === true,
        ranges: view._eventView().ranges,
      };
    };
    // A fully clamped move never emits an update, so there is no private gate
    // to settle. If an earlier move changed the view, changedAxes accumulates
    // across later clamped moves and pointerup emits the matching end phase.
    const fullyClampedPan = boundedPan([0.0, 0.2], [[0.30, -0.30]], 73);
    const updatedThenClampedPan = boundedPan(
      [0.4, 0.6], [[0.10, -0.10], [2.50, -2.50], [3.00, -3.00]], 74
    );

    document.body.setAttribute("data-xy-legend-best-live", JSON.stringify({
      autoLoc: legend.dataset.xyLegendAutoLoc || null,
      initial,
      duringUpdate,
      settled,
      emptyWinner,
      sparseWinner,
      denseWinner,
      occupiedWinner,
      pointerCancel,
      escapeCancel,
      fullyClampedPan,
      updatedThenClampedPan,
      rasterBytes: view._legendBestScratch.width * view._legendBestScratch.height * 4,
      markKinds: view.spec.traces.map((trace) => trace.kind),
      annotationLabels: initialAnnotationLabels,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-best-live-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_RESIZE_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._drawNow();
    const legend = document.querySelector('[data-xy-slot="legend"]');
    if (!legend) throw new Error("legend never rendered");
    const wide = {
      loc: legend.dataset.xyLegendLoc,
      plotWidth: view.plot.w,
      legendWidth: legend.getBoundingClientRect().width,
    };

    view.root.style.width = "280px";
    view.fluid = true;
    view._resize(280, view.size.h);
    const narrow = {
      loc: legend.dataset.xyLegendLoc,
      plotWidth: view.plot.w,
      legendWidth: legend.getBoundingClientRect().width,
    };
    document.body.setAttribute(
      "data-xy-legend-best-resize",
      JSON.stringify({
        wide,
        narrow,
        nativeFallback: !view._glHost,
        preserveDrawingBuffer:
          view.gl.getContextAttributes()?.preserveDrawingBuffer === true,
        snapshotReady: view._legendBestCanvasSnapshotReady === true,
      }),
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-best-resize-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_HYSTERESIS_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    const flush = () => {
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
    };
    flush();
    const legends = [...document.querySelectorAll('[data-xy-slot="legend"]')];
    const legend = legends[0];
    const hiddenLegend = legends[1];
    if (!legend || !hiddenLegend) throw new Error("two probe legends never rendered");

    const gridW = 100;
    const gridH = 100;
    const plotRect = view.canvas.getBoundingClientRect();
    const legendRect = legend.getBoundingClientRect();
    const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
    const boxW = clamp(legendRect.width / plotRect.width, 0, 1);
    const boxH = clamp(legendRect.height / plotRect.height, 0, 1);
    const insetX = clamp(6 / view.plot.w, 0, 0.5);
    const insetY = clamp(6 / view.plot.h, 0, 0.5);
    const left = clamp(insetX, 0, Math.max(0, 1 - boxW));
    const right = clamp(1 - insetX - boxW, 0, Math.max(0, 1 - boxW));
    const upper = clamp(insetY, 0, Math.max(0, 1 - boxH));
    const cells = (x, y) => {
      const x0 = clamp(Math.floor(x * gridW), 0, gridW);
      const x1 = clamp(Math.ceil((x + boxW) * gridW), x0, gridW);
      const y0 = clamp(Math.floor(y * gridH), 0, gridH);
      const y1 = clamp(Math.ceil((y + boxH) * gridH), y0, gridH);
      const out = [];
      for (let row = y0; row < y1; row++) {
        for (let col = x0; col < x1; col++) out.push(row * gridW + col);
      }
      return out;
    };
    const upperRight = cells(right, upper);
    const upperLeft = cells(left, upper);
    const upperLeftSet = new Set(upperLeft);
    const cornerIntersection = upperRight.filter((cell) => upperLeftSet.has(cell)).length;
    if (cornerIntersection) throw new Error("probe legend corners unexpectedly overlap");

    // Start other candidates fully occupied, then assign deterministic corner
    // fractions. The small single-row legend keeps the two corner boxes
    // disjoint, so both normalized scores can be controlled independently.
    const makeRaster = (rightFraction, leftFraction) => {
      const occupancy = new Uint8Array(gridW * gridH);
      occupancy.fill(1);
      const writeFraction = (indices, fraction) => {
        for (const index of indices) occupancy[index] = 0;
        const count = Math.max(0, Math.min(
          indices.length,
          Math.round(indices.length * fraction),
        ));
        for (let i = 0; i < count; i++) occupancy[indices[i]] = 1;
      };
      writeFraction(upperRight, rightFraction);
      writeFraction(upperLeft, leftFraction);
      const score = (indices) =>
        indices.reduce((total, index) => total + occupancy[index], 0) / indices.length;
      return {
        raster: { occupancy, w: gridW, h: gridH, plot: plotRect },
        scores: { upperRight: score(upperRight), upperLeft: score(upperLeft) },
      };
    };
    const exactLegend = {
      dataset: {},
      getBoundingClientRect: () => ({
        width: legendRect.width,
        height: legendRect.height,
      }),
    };

    // A zero-layout sibling has no box to score, but the shared rendered marks
    // raster is still available. Temporary CSS visibility must not reset the
    // visible legend's completed score or adopt a new fallback for either box;
    // the hidden box will score (exactly, if it has never scored) when shown.
    const liveBeforeFallback = legend._xyLegendBestLiveLoc === legend.dataset.xyLegendLoc;
    const visibleBeforeSiblingFallback = legend.dataset.xyLegendLoc;
    const hiddenBeforeSiblingFallback = hiddenLegend.dataset.xyLegendLoc;
    const siblingFallbackSpec = structuredClone(view.spec);
    siblingFallbackSpec.extra_legends[0] = {
      ...siblingFallbackSpec.extra_legends[0],
      auto_loc: "best",
      loc: "lower left",
    };
    const siblingFallbackChanged = view._adoptBestLegendFallbacks(siblingFallbackSpec);
    const visibleAfterSiblingFallback = legend.dataset.xyLegendLoc;
    const visibleLiveAfterSiblingFallback =
      legend._xyLegendBestLiveLoc === legend.dataset.xyLegendLoc;
    const hiddenAfterSiblingFallback = hiddenLegend.dataset.xyLegendLoc;
    const hiddenLiveAfterSiblingFallback =
      hiddenLegend._xyLegendBestLiveLoc === hiddenLegend.dataset.xyLegendLoc;

    // A concrete server fallback must not itself become a sticky live result.
    // Force genuine view-wide capability loss after the chart's initial live
    // score, then restore raster capability and verify the first score is exact.
    const fallbackSpec = structuredClone(siblingFallbackSpec);
    fallbackSpec.legend = {
      ...(fallbackSpec.legend || {}),
      auto_loc: "best",
      loc: "lower right",
    };
    const originalAvailability = view._bestLegendLiveRasterAvailable;
    view._bestLegendLiveRasterAvailable = () => false;
    const fallbackChanged = view._adoptBestLegendFallbacks(fallbackSpec);
    view._bestLegendLiveRasterAvailable = originalAvailability;
    const fallback = legend.dataset.xyLegendLoc;
    const liveAfterFallback = legend._xyLegendBestLiveLoc === legend.dataset.xyLegendLoc;

    const originalRaster = view._bestLegendRaster;
    // Uniform occupancy is a true tie: the first measurable live placement
    // must ignore the noncanonical fallback and take canonical upper-right.
    let stage = makeRaster(1, 1);
    const firstExact = view._bestLegendLocationForRaster(stage.raster, exactLegend);
    view._bestLegendRaster = () => stage.raster;
    view._markBestLegendsDirty();
    flush();
    const firstLive = legend.dataset.xyLegendLoc;
    const liveAfterFirst = legend._xyLegendBestLiveLoc === legend.dataset.xyLegendLoc;

    // The exact winner reverses after a genuine settled view write, but its
    // improvement is only about two normalized occupancy points. The current
    // live corner should therefore remain stable.
    stage = makeRaster(0.52, 0.50);
    const nearScores = stage.scores;
    const nearExact = view._bestLegendLocationForRaster(stage.raster, exactLegend);
    const stableChangedAxes = view._setView(
      { ranges: { x: [0.01, 1.0] } },
      {
        animate: false,
        request: false,
        source: "legend_hysteresis_near",
        phase: "end",
        interactionId: 951,
      },
    );
    flush();
    const stableAfterSettled = legend.dataset.xyLegendLoc;

    // One occupied cell is less than five percentage points for this box, but
    // a completely empty challenger must still win on the next settled view.
    stage = makeRaster(1 / upperRight.length, 0);
    const emptyScores = stage.scores;
    const emptyExact = view._bestLegendLocationForRaster(stage.raster, exactLegend);
    const emptyChangedAxes = view._setView(
      { ranges: { x: [0.02, 1.0] } },
      {
        animate: false,
        request: false,
        source: "legend_hysteresis_empty",
        phase: "end",
        interactionId: 952,
      },
    );
    flush();
    const movedAfterSettled = legend.dataset.xyLegendLoc;

    // A fully dense raster is a true nine-way tie. Canonical exact scoring
    // returns upper-right, but a legend with a completed upper-left live score
    // must not hop on this later settled view merely because tie order differs.
    stage = makeRaster(1, 1);
    const uniformExact = view._bestLegendLocationForRaster(stage.raster, exactLegend);
    const uniformChangedAxes = view._setView(
      { ranges: { x: [0.03, 1.0] } },
      {
        animate: false,
        request: false,
        source: "legend_hysteresis_uniform",
        phase: "end",
        interactionId: 953,
      },
    );
    flush();
    const stableOnUniform = legend.dataset.xyLegendLoc;

    // The reverse sparse case proves uniform stickiness is not permanent:
    // upper-right is now empty and the current upper-left has one occupied
    // cell, so the empty exception must move immediately on settle.
    stage = makeRaster(0, 1 / upperLeft.length);
    const reverseEmptyScores = stage.scores;
    const reverseEmptyExact = view._bestLegendLocationForRaster(stage.raster, exactLegend);
    const reverseEmptyChangedAxes = view._setView(
      { ranges: { x: [0.04, 1.0] } },
      {
        animate: false,
        request: false,
        source: "legend_hysteresis_reverse_empty",
        phase: "end",
        interactionId: 954,
      },
    );
    flush();
    const movedFromUniform = legend.dataset.xyLegendLoc;

    // Re-arm the hidden automatic sibling and make the first box visually
    // tiny. Its overlap adds less than the hysteresis band to the second box's
    // near-uniform current corner: ordinary mark hysteresis would retain that
    // collision, while the multi-legend collision rule must take the exact
    // alternative and leave the two live boxes disjoint.
    hiddenLegend.style.display = "grid";
    legend.style.transform = "scale(0.1)";
    for (const candidate of legends) {
      candidate.dataset.xyLegendLoc = "upper right";
      candidate._xyLegendBestLiveLoc = "upper right";
      view._positionLegend(candidate, "upper right");
    }
    stage = makeRaster(0.52, 0.50);
    const collisionRaster = {
      ...stage.raster,
      occupancy: stage.raster.occupancy.slice(),
    };
    view._fillBestLegendRasterRect(collisionRaster, legend.getBoundingClientRect());
    const hiddenScorer = {
      dataset: { xyLegendLoc: "upper right" },
      _xyLegendBestLiveLoc: "upper right",
      getBoundingClientRect: () => hiddenLegend.getBoundingClientRect(),
    };
    const stickyWithPriorBox = view._bestLegendLocationForRaster(
      collisionRaster,
      hiddenScorer,
    );
    const exactWithPriorBox = view._bestLegendLocationForRaster(
      collisionRaster,
      hiddenScorer,
      false,
    );
    view._markBestLegendsDirty();
    flush();
    const multiLocs = legends.map((candidate) => candidate.dataset.xyLegendLoc);
    const multiLiveLocs = legends.map((candidate) => candidate._xyLegendBestLiveLoc);
    const multiRects = legends.map((candidate) => candidate.getBoundingClientRect());
    const multiOverlap =
      multiRects[0].left < multiRects[1].right &&
      multiRects[0].right > multiRects[1].left &&
      multiRects[0].top < multiRects[1].bottom &&
      multiRects[0].bottom > multiRects[1].top;

    // Pin the strict boundary independently of the measured legend footprint.
    // At this plot size, a 0.20 x 0.15 fake box covers exactly 20 raster cells
    // in either upper corner: 6/20 versus 5/20 is exactly 0.30 versus 0.25.
    // Five points must move, not stick because subtraction lands just below .05.
    const thresholdOccupancy = new Uint8Array(20 * 20);
    thresholdOccupancy.fill(1);
    const thresholdBoxW = 0.20;
    const thresholdBoxH = 0.15;
    const thresholdLeftX = clamp(insetX, 0, 1 - thresholdBoxW);
    const thresholdRightX = clamp(1 - insetX - thresholdBoxW, 0, 1 - thresholdBoxW);
    const thresholdUpperY = clamp(insetY, 0, 1 - thresholdBoxH);
    const thresholdCells = (x, y) => {
      const out = [];
      const x0 = clamp(Math.floor(x * 20), 0, 20);
      const x1 = clamp(Math.ceil((x + thresholdBoxW) * 20), x0, 20);
      const y0 = clamp(Math.floor(y * 20), 0, 20);
      const y1 = clamp(Math.ceil((y + thresholdBoxH) * 20), y0, 20);
      for (let row = y0; row < y1; row++) {
        for (let col = x0; col < x1; col++) out.push(row * 20 + col);
      }
      return out;
    };
    const thresholdUpperRight = thresholdCells(thresholdRightX, thresholdUpperY);
    const thresholdUpperLeft = thresholdCells(thresholdLeftX, thresholdUpperY);
    for (const index of [...thresholdUpperRight, ...thresholdUpperLeft]) {
      thresholdOccupancy[index] = 0;
    }
    for (const index of thresholdUpperRight.slice(0, 6)) thresholdOccupancy[index] = 1;
    for (const index of thresholdUpperLeft.slice(0, 5)) thresholdOccupancy[index] = 1;
    const thresholdRaster = {
      occupancy: thresholdOccupancy,
      w: 20,
      h: 20,
      plot: plotRect,
    };
    const thresholdLegend = {
      dataset: { xyLegendLoc: "upper right" },
      _xyLegendBestLiveLoc: "upper right",
      getBoundingClientRect: () => ({
        width: plotRect.width * thresholdBoxW,
        height: plotRect.height * thresholdBoxH,
      }),
    };
    const exactThresholdWinner = view._bestLegendLocationForRaster(
      thresholdRaster,
      thresholdLegend,
    );
    const thresholdScores = {
      upperRight: thresholdUpperRight.reduce(
        (total, index) => total + thresholdOccupancy[index], 0,
      ) / thresholdUpperRight.length,
      upperLeft: thresholdUpperLeft.reduce(
        (total, index) => total + thresholdOccupancy[index], 0,
      ) / thresholdUpperLeft.length,
    };
    const thresholdAreas = {
      upperRight: thresholdUpperRight.length,
      upperLeft: thresholdUpperLeft.length,
    };
    view._bestLegendRaster = originalRaster;

    document.body.setAttribute("data-xy-legend-best-hysteresis", JSON.stringify({
      cornerIntersection,
      legendCount: legends.length,
      liveBeforeFallback,
      visibleBeforeSiblingFallback,
      hiddenBeforeSiblingFallback,
      siblingFallbackChanged,
      visibleAfterSiblingFallback,
      visibleLiveAfterSiblingFallback,
      hiddenAfterSiblingFallback,
      hiddenLiveAfterSiblingFallback,
      fallbackChanged,
      fallback,
      liveAfterFallback,
      firstExact,
      firstLive,
      liveAfterFirst,
      nearExact,
      nearScores,
      stableChangedAxes,
      stableAfterSettled,
      emptyExact,
      emptyScores,
      emptyChangedAxes,
      movedAfterSettled,
      uniformExact,
      uniformChangedAxes,
      stableOnUniform,
      reverseEmptyScores,
      reverseEmptyExact,
      reverseEmptyChangedAxes,
      movedFromUniform,
      stickyWithPriorBox,
      exactWithPriorBox,
      multiLocs,
      multiLiveLocs,
      multiOverlap,
      exactThresholdWinner,
      thresholdScores,
      thresholdAreas,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-best-hysteresis-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_ISOLATED_MARK_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._drawNow();
    const legend = document.querySelector('[data-xy-slot="legend"]');
    if (!legend) throw new Error("legend never rendered");
    const raster = view._bestLegendRaster();
    document.body.setAttribute("data-xy-legend-best-mark", JSON.stringify({
      kind: view.spec.traces[0].kind,
      loc: legend.dataset.xyLegendLoc,
      autoLoc: legend.dataset.xyLegendAutoLoc || null,
      occupiedCells: raster
        ? raster.occupancy.reduce((total, value) => total + value, 0)
        : 0,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-best-mark-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_FIXED_CONTEXT_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    document.body.setAttribute("data-xy-legend-fixed-context", JSON.stringify({
      nativeFallback: !view._glHost,
      preserveDrawingBuffer:
        view.gl.getContextAttributes()?.preserveDrawingBuffer === true,
      snapshotReady: view._legendBestCanvasSnapshotReady === true,
      automaticLegends: view._legends.filter(
        (legend) => legend.dataset.xyLegendAutoLoc === "best"
      ).length,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-fixed-context-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_INVISIBLE_ANNOTATION_PROBE = r"""
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
    const flush = () => {
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
    };
    view.root.style.transform = "scale(0.6)";
    view.root.style.transformOrigin = "top left";
    view._markBestLegendsDirty();
    flush();
    const legends = [...document.querySelectorAll('[data-xy-slot="legend"]')];
    const legend = legends.find((item) => item.dataset.xyLegendAutoLoc === "best");
    const fixedLegend = legends.find((item) => item.dataset.xyLegendAutoLoc !== "best");
    const hiddenFixed = {
      loc: legend?.dataset.xyLegendLoc || null,
      visible: view._bestLegendIsVisible(fixedLegend),
      width: fixedLegend?.getBoundingClientRect().width || 0,
    };
    fixedLegend.style.visibility = "";
    await settle();
    flush();
    const visibleFixed = {
      loc: legend?.dataset.xyLegendLoc || null,
      visible: view._bestLegendIsVisible(fixedLegend),
      rect: fixedLegend.getBoundingClientRect().toJSON(),
    };
    // Position-only CSS changes keep the same layout dimensions, so they are
    // invisible to ResizeObserver. The shared attribute observer must compare
    // the full fixed obstacle rectangle and schedule a fresh score.
    view._positionLegend(fixedLegend, "upper left");
    await settle();
    flush();
    const movedFixed = {
      loc: legend?.dataset.xyLegendLoc || null,
      visible: view._bestLegendIsVisible(fixedLegend),
      rect: fixedLegend.getBoundingClientRect().toJSON(),
    };
    // The settled draw rebuilds annotation label chrome; inspect the current
    // nodes rather than the detached pre-transition labels.
    const labels = [...document.querySelectorAll('[data-xy-slot="annotation_label"]')];
    const raster = view._bestLegendRaster();
    document.body.setAttribute("data-xy-legend-invisible-annotation", JSON.stringify({
      legendCount: legends.length,
      hiddenFixed,
      visibleFixed,
      movedFixed,
      labelCount: labels.length,
      painted: labels.map((label) => view._bestLegendAnnotationPainted(label)),
      opacities: labels.map((label) => getComputedStyle(label).opacity),
      colors: labels.map((label) => getComputedStyle(label).color),
      normalizedLegendWidth: legend.getBoundingClientRect().width / raster.plot.width,
      expectedLegendWidth: legend.offsetWidth / view.plot.w,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-invisible-annotation-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_UPDATE_PAYLOAD_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    const decode = (b64) => {
      const binary = atob(b64);
      const out = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
      return out;
    };
    const flush = () => {
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
    };
    flush();
    const legend = document.querySelector('[data-xy-slot="legend"]');
    if (!legend) throw new Error("legend never rendered");
    const before = legend.dataset.xyLegendLoc;
    const applied = view.updatePayload(NEXT_SPEC, decode(NEXT_B64));
    const sameLegendNode = legend === document.querySelector('[data-xy-slot="legend"]');
    const animationActive = !!view._dataAnim;
    flush();
    const during = legend.dataset.xyLegendLoc;
    const dirtyDuring = view._legendBestDirty === true;

    let frames = 0;
    const finish = () => {
      if (view._dataAnim && frames++ < 180) {
        requestAnimationFrame(finish);
        return;
      }
      flush();
      const after = legend.dataset.xyLegendLoc;
      const dirtyAfter = view._legendBestDirty === true;

      // Simulate the capability case updatePayload must fall back for (a
      // detached/lost canvas, or a native context that declined preservation).
      const unavailableSpec = structuredClone(NEXT_SPEC);
      unavailableSpec.animation = { ...(unavailableSpec.animation || {}), enabled: false };
      unavailableSpec.legend = { ...unavailableSpec.legend, loc: "lower right" };
      const availability = view._bestLegendLiveRasterAvailable;
      view._bestLegendLiveRasterAvailable = () => false;
      const unavailableApplied = view.updatePayload(unavailableSpec, decode(NEXT_B64));
      const unavailableFallback = legend.dataset.xyLegendLoc;
      view._bestLegendLiveRasterAvailable = availability;

      document.body.setAttribute("data-xy-legend-update-payload", JSON.stringify({
        applied,
        sameLegendNode,
        animationActive,
        before,
        during,
        dirtyDuring,
        after,
        dirtyAfter,
        nextFallback: NEXT_SPEC.legend.loc,
        unavailableApplied,
        unavailableFallback,
      }));
    };
    requestAnimationFrame(finish);
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-update-payload-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


_HIDDEN_LEGEND_PROBE = r"""
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    const flush = () => {
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
    };
    // A new task runs after MutationObserver delivery. The probe then flushes
    // the draw it scheduled synchronously, avoiding timing assumptions about
    // headless requestAnimationFrame throttling.
    const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
    flush();
    const legend = document.querySelector('[data-xy-slot="legend"]');
    if (!legend) throw new Error("legend never rendered");
    const initial = legend.dataset.xyLegendLoc;
    const originalRaster = view._bestLegendRaster.bind(view);
    const originalVisibility = view._bestLegendIsVisible.bind(view);
    let rasterCalls = 0;
    let visibilityChecks = 0;
    view._bestLegendRaster = (...args) => {
      rasterCalls += 1;
      return originalRaster(...args);
    };
    view._bestLegendIsVisible = (...args) => {
      visibilityChecks += 1;
      return originalVisibility(...args);
    };

    const cleanRasterStart = rasterCalls;
    const cleanVisibilityStart = visibilityChecks;
    for (let i = 0; i < 3; i++) flush();
    const cleanDraws = {
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - cleanRasterStart,
      visibilityDelta: visibilityChecks - cleanVisibilityStart,
    };

    const hiddenRasterStart = rasterCalls;
    legend.style.display = "none";
    await Promise.resolve();
    view._setView(
      { ranges: { x: [0.8, 1.0], y: [0.8, 1.0] } },
      { animate: false, request: false, source: "hidden_legend", phase: "end" },
    );
    flush();
    const hiddenViewReadbackDelta = rasterCalls - hiddenRasterStart;
    // Unrelated draws and fresh dirty signals must remain readback-free while
    // no automatic legend has a painted box.
    for (let i = 0; i < 3; i++) {
      view._markBestLegendsDirty();
      flush();
    }
    const displayHidden = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - hiddenRasterStart,
    };

    const displayRestoreRasterStart = rasterCalls;
    legend.style.display = "";
    await settle();
    flush();
    const displayRestored = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - displayRestoreRasterStart,
      loc: legend.dataset.xyLegendLoc,
      width: legend.getBoundingClientRect().width,
      height: legend.getBoundingClientRect().height,
    };

    // ResizeObserver reports the unchanged layout box for transforms. The
    // legend attribute observer must remeasure the visual footprint even when
    // it stays nonzero and visible on both sides of the mutation.
    const halfScaleRasterStart = rasterCalls;
    legend.style.transform = "scale(0.5)";
    await settle();
    flush();
    const halfScale = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - halfScaleRasterStart,
      width: legend.getBoundingClientRect().width,
      height: legend.getBoundingClientRect().height,
    };
    const fullScaleRasterStart = rasterCalls;
    legend.style.transform = "scale(1)";
    await settle();
    flush();
    const fullScale = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - fullScaleRasterStart,
      width: legend.getBoundingClientRect().width,
      height: legend.getBoundingClientRect().height,
    };

    // A transformed zero-area box still has a client rect entry in Chromium;
    // it must be rejected before rasterization by its measured dimensions.
    const zeroSizeRasterStart = rasterCalls;
    legend.style.transform = "scale(0)";
    await Promise.resolve();
    view._markBestLegendsDirty();
    flush();
    for (let i = 0; i < 3; i++) {
      view._markBestLegendsDirty();
      flush();
    }
    const zeroSized = {
      clientRectCount: legend.getClientRects().length,
      width: legend.getBoundingClientRect().width,
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - zeroSizeRasterStart,
    };
    const zeroSizeRestoreRasterStart = rasterCalls;
    legend.style.transform = "";
    await settle();
    flush();
    const zeroSizeRestored = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - zeroSizeRestoreRasterStart,
      loc: legend.dataset.xyLegendLoc,
    };

    const collapseRasterStart = rasterCalls;
    legend.style.visibility = "collapse";
    await Promise.resolve();
    view._setView(
      { ranges: { x: [0.0, 1.0], y: [0.0, 1.0] } },
      { animate: false, request: false, source: "collapsed_legend", phase: "end" },
    );
    flush();
    const collapsedViewReadbackDelta = rasterCalls - collapseRasterStart;
    for (let i = 0; i < 3; i++) {
      view._markBestLegendsDirty();
      flush();
    }
    const collapsed = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - collapseRasterStart,
    };

    const collapseRestoreRasterStart = rasterCalls;
    legend.style.visibility = "";
    await settle();
    flush();
    const collapseRestored = {
      visible: view._bestLegendIsVisible(legend),
      dirty: view._legendBestDirty === true,
      readbackDelta: rasterCalls - collapseRestoreRasterStart,
      loc: legend.dataset.xyLegendLoc,
    };

    const resizeObserver = view._legendBestResizeObserver;
    const mutationObserver = view._legendBestMutationObserver;
    let resizeDisconnected = false;
    let mutationDisconnected = false;
    if (resizeObserver) {
      const disconnect = resizeObserver.disconnect.bind(resizeObserver);
      resizeObserver.disconnect = () => { resizeDisconnected = true; disconnect(); };
    }
    if (mutationObserver) {
      const disconnect = mutationObserver.disconnect.bind(mutationObserver);
      mutationObserver.disconnect = () => { mutationDisconnected = true; disconnect(); };
    }
    view.destroy();

    document.body.setAttribute("data-xy-legend-best-hidden", JSON.stringify({
      initial,
      cleanDraws,
      hiddenViewReadbackDelta,
      displayHidden,
      displayRestored,
      halfScale,
      fullScale,
      zeroSized,
      zeroSizeRestored,
      collapsedViewReadbackDelta,
      collapsed,
      collapseRestored,
      resizeDisconnected,
      mutationDisconnected,
      observersReleased:
        view._legendBestResizeObserver === null &&
        view._legendBestMutationObserver === null,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-best-hidden-error",
      String((err && err.stack) || err),
    );
  }
})();
</script>
"""


def _mixed_chart():
    # Every mark and the annotation occupies the home view's upper-right
    # corner. In the 0.8..1.0 viewport they all project into the lower-left.
    return xy.chart(
        xy.line([0.82, 0.86], [0.82, 0.86], name="line"),
        xy.scatter([0.83, 0.85], [0.85, 0.83], name="scatter", size=12),
        xy.area([0.82, 0.86], [0.84, 0.86], base=[0.80, 0.80], name="area"),
        xy.bar([0.84], [0.86], base=[0.80], width=0.04, name="bar"),
        xy.text(0.84, 0.84, "important"),
        xy.x_axis(domain=(0.0, 1.0), bounds=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0), bounds=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=520,
        height=360,
    )


def _resize_chart():
    # At 640 px the small bar is left of the legend. At 280 px the measured
    # legend footprint grows as a fraction of the plot and covers the bar.
    return xy.chart(
        xy.bar([0.75], [1.0], base=[0.90], width=0.04, name="series"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=640,
        height=360,
    )


def _isolated_mark_chart(kind: str):
    marks = {
        "line": xy.line([0.94, 0.98], [0.94, 0.98], name="line"),
        "scatter": xy.scatter([0.96], [0.96], name="scatter", size=6),
        "area": xy.area([0.94, 0.98], [0.96, 0.98], base=[0.90, 0.90], name="area"),
        "bar": xy.bar([0.96], [0.98], base=[0.90], width=0.04, name="bar"),
    }
    return xy.chart(
        marks[kind],
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=520,
        height=360,
    )


def _payload_update_chart(x: float, y: float):
    return xy.chart(
        xy.scatter([x], [y], name="series", size=10),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=520,
        height=360,
    )


def test_live_best_raster_contract_is_fixed_size_and_module_private() -> None:
    source = CHARTVIEW.read_text(encoding="utf-8")

    # Keep only stable structural contracts here. Candidate behavior, bounded
    # scratch bytes, settled gestures, data animation, fallback contexts,
    # and annotation paint are exercised by the browser probes below instead
    # of slicing method bodies on indentation-sensitive delimiters.
    assert re.search(r"\bconst\s+LEGEND_BEST_GRID_W\s*=\s*96\s*;", source)
    assert re.search(r"\bconst\s+LEGEND_BEST_GRID_H\s*=\s*72\s*;", source)
    assert re.search(r"\bconst\s+LEGEND_BEST_HYSTERESIS\s*=\s*0\.05\s*;", source)
    assert re.search(r"\bconst\s+LEGEND_BEST_SCORE_EPSILON\s*=\s*1e-12\s*;", source)
    assert "LEGEND_BEST_TIE_BAND" not in source
    assert re.search(r"(?m)^function\s+xyLegendBestLocation\s*\(", source)
    assert not re.search(r"\bexport\s+function\s+xyLegendBestLocation\s*\(", source)
    assert re.search(
        r"LEGEND_BEST_ORDER\s*=\s*\[\s*[\"']upper right[\"']\s*,\s*"
        r"[\"']upper left[\"']",
        source,
    )
    assert re.search(
        r"\(scores\.get\(loc\)\s*\?\?\s*Infinity\)\s*===\s*floor",
        source,
    )
    assert re.search(
        r"improvement\s*\+\s*LEGEND_BEST_SCORE_EPSILON\s*<\s*hysteresis",
        source,
    )
    assert re.search(
        r"this\._drawChrome\(\)\s*;\s*this\._maybePositionBestLegends\(\)\s*;",
        source,
    )

    kernel = KERNEL.read_text(encoding="utf-8")
    dirty_hook = r"this\._markBestLegendsDirty\s*\(\s*\)\s*;"
    for method in ("_applySampleRebinGrid", "_applyAppend"):
        # Both hooks are deliberately near the start of their methods. A
        # bounded formatting-tolerant window keeps this structural assertion
        # scoped without splitting on indentation or a particular next method.
        assert re.search(
            rf"\b{method}\s*\([^)]*\)\s*\{{[\s\S]{{0,1800}}?{dirty_hook}",
            kernel,
        )
    for message_type in ("tier_update", "density_update"):
        # Stop at the next message branch so one branch cannot satisfy the
        # other's geometry-change contract.
        assert re.search(
            rf'msg\.type\s*===\s*"{message_type}"'
            rf"(?:(?!\bmsg\.type\s*===)[\s\S])*?"
            rf"if\s*\(\s*legendGeometryChanged\s*\)\s*{dirty_hook}",
            kernel,
        )
    assert re.search(
        r'webglcontextlost"(?:(?!webglcontextrestored")[\s\S])*?'
        r"this\._legendBestInteractionActive\s*=\s*false\s*;"
        r"[\s\S]*?this\._markBestLegendsDirty\s*\(\s*\)\s*;",
        source,
    )
    assert re.search(
        r"g\._drillBackdropTick\s*\|\|\s*g\._blendTick\s*\|\|\s*"
        r"g\.drill\?\._blendTick",
        source,
    )


def test_live_best_hysteresis_stabilizes_settled_rescores_but_not_empty_boxes(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = probe_document(_payload_update_chart(0.5, 0.5), _HYSTERESIS_PROBE)
    capture = "window.__fcProbeView = xy.renderStandalone("
    assert capture in document
    # The hidden automatic sibling pins the lifecycle edge where a CSS-hidden
    # legend coexists with a visible live winner during a data-only update.
    document = document.replace(
        capture,
        """
spec.extra_legends = [{
  items: [{ name: "hidden", kind: "line", style: { color: "#9333ea" } }],
  loc: "upper right",
  auto_loc: "best",
  style: { display: "none" },
}];
"""
        + capture,
        1,
    )
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "legend_best_hysteresis.html",
        "data-xy-legend-best-hysteresis",
        label="automatic legend settled hysteresis probe",
    )

    assert result["cornerIntersection"] == 0, result
    assert result["legendCount"] == 2, result
    assert result["liveBeforeFallback"] is True, result
    assert result["siblingFallbackChanged"] is False, result
    assert result["visibleAfterSiblingFallback"] == result["visibleBeforeSiblingFallback"], result
    assert result["visibleLiveAfterSiblingFallback"] is True, result
    assert result["hiddenAfterSiblingFallback"] == result["hiddenBeforeSiblingFallback"], result
    assert result["hiddenLiveAfterSiblingFallback"] is False, result

    assert result["fallbackChanged"] is True, result
    assert result["fallback"] == "lower right", result
    assert result["liveAfterFallback"] is False, result
    assert result["firstExact"] == "upper right", result
    assert result["firstLive"] == result["firstExact"], result
    assert result["firstLive"] != result["fallback"], result
    assert result["liveAfterFirst"] is True, result

    near = result["nearScores"]
    assert near["upperLeft"] > 0, result
    assert near["upperRight"] > near["upperLeft"], result
    assert 0 < near["upperRight"] - near["upperLeft"] < 0.05, result
    assert result["nearExact"] == "upper left", result
    assert result["stableChangedAxes"] == ["x"], result
    assert result["stableAfterSettled"] == "upper right", result

    empty = result["emptyScores"]
    assert empty["upperLeft"] == 0, result
    assert 0 < empty["upperRight"] < 0.05, result
    assert result["emptyExact"] == "upper left", result
    assert result["emptyChangedAxes"] == ["x"], result
    assert result["movedAfterSettled"] == "upper left", result
    assert result["uniformExact"] == "upper right", result
    assert result["uniformChangedAxes"] == ["x"], result
    assert result["stableOnUniform"] == "upper left", result
    reverse_empty = result["reverseEmptyScores"]
    assert reverse_empty["upperRight"] == 0, result
    assert 0 < reverse_empty["upperLeft"] < 0.05, result
    assert result["reverseEmptyExact"] == "upper right", result
    assert result["reverseEmptyChangedAxes"] == ["x"], result
    assert result["movedFromUniform"] == "upper right", result
    assert result["stickyWithPriorBox"] == "upper right", result
    assert result["exactWithPriorBox"] == "upper left", result
    assert result["multiLocs"] == ["upper right", "upper left"], result
    assert result["multiLiveLocs"] == result["multiLocs"], result
    assert result["multiOverlap"] is False, result
    assert result["thresholdAreas"] == {"upperRight": 20, "upperLeft": 20}, result
    assert result["thresholdScores"]["upperRight"] == pytest.approx(0.30), result
    assert result["thresholdScores"]["upperLeft"] == pytest.approx(0.25), result
    assert result["exactThresholdWinner"] == "upper left", result


def test_live_best_uses_rendered_marks_and_moves_only_after_view_settles(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        probe_document(_mixed_chart(), _SETTLED_VIEW_PROBE),
        tmp_path / "legend_best_live.html",
        "data-xy-legend-best-live",
        label="live best legend settled-view probe",
    )

    assert result["autoLoc"] == "best", result
    assert result["markKinds"] == ["line", "scatter", "area", "bar"], result
    assert result["annotationLabels"] >= 1, result
    assert result["emptyWinner"] == "upper right", result
    assert result["sparseWinner"] == "upper left", result
    assert result["denseWinner"] == "upper right", result
    assert result["occupiedWinner"] == "upper left", result
    assert result["initial"] == "upper left", result
    assert result["duringUpdate"] == result["initial"], result
    assert result["settled"] == "upper right", result
    for cancellation in (result["pointerCancel"], result["escapeCancel"]):
        assert cancellation["during"] == "upper right", result
        assert cancellation["activeDuring"] is True, result
        assert cancellation["after"] == "upper left", result
        assert cancellation["activeAfter"] is False, result
    assert result["fullyClampedPan"]["activeDuring"] == [False], result
    assert result["fullyClampedPan"]["activeAfter"] is False, result
    for axis in ("x", "y"):
        assert result["fullyClampedPan"]["ranges"][axis] == pytest.approx([0, 0.2]), result
    assert result["updatedThenClampedPan"]["activeDuring"] == [True, True, True], result
    assert result["updatedThenClampedPan"]["activeAfter"] is False, result
    for axis in ("x", "y"):
        assert result["updatedThenClampedPan"]["ranges"][axis] == pytest.approx([0, 0.2]), result
    assert result["rasterBytes"] == 96 * 72 * 4, result


@pytest.mark.parametrize("kind", ["line", "scatter", "area", "bar"])
def test_live_best_scores_each_required_mark_in_isolation(
    kind: str,
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = probe_document(_isolated_mark_chart(kind), _ISOLATED_MARK_PROBE)
    capture = "window.__fcProbeView = xy.renderStandalone("
    assert capture in document
    # Make the serialized fallback deliberately wrong. The only way this can
    # reach upper-left is for the live raster to see this isolated mark.
    document = document.replace(
        capture,
        'spec.legend.loc = "upper right"; ' + capture,
        1,
    )
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / f"legend_best_{kind}.html",
        "data-xy-legend-best-mark",
        label=f"live best legend isolated {kind} probe",
    )

    assert result["kind"] == kind, result
    assert result["autoLoc"] == "best", result
    assert result["occupiedCells"] > 0, result
    assert result["loc"] == "upper left", result


def test_live_best_remeasures_the_legend_after_responsive_resize(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = probe_document(_resize_chart(), _RESIZE_PROBE)
    # Force the native per-chart context rather than the default shared host;
    # this is the only path whose DOM canvas itself must retain GL pixels.
    document = document.replace(
        "<head>",
        "<head><script>window.XY_SHARED_WEBGL = false;</script>",
        1,
    )
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "legend_best_resize.html",
        "data-xy-legend-best-resize",
        label="live best legend responsive-resize probe",
    )

    assert result["wide"]["loc"] == "upper right", result
    assert result["narrow"]["loc"] == "upper left", result
    assert result["nativeFallback"] is True, result
    assert result["preserveDrawingBuffer"] is True, result
    assert result["snapshotReady"] is True, result
    assert result["narrow"]["plotWidth"] < result["wide"]["plotWidth"], result
    assert (
        result["narrow"]["legendWidth"] / result["narrow"]["plotWidth"]
        > result["wide"]["legendWidth"] / result["wide"]["plotWidth"]
    ), result


def test_native_fixed_legend_keeps_default_drawing_buffer_policy(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.chart(
        xy.scatter([0.5], [0.5], name="series"),
        xy.legend(loc="upper right"),
        width=420,
        height=300,
    )
    document = probe_document(chart, _FIXED_CONTEXT_PROBE).replace(
        "<head>",
        "<head><script>window.XY_SHARED_WEBGL = false;</script>",
        1,
    )
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "legend_fixed_native_context.html",
        "data-xy-legend-fixed-context",
        label="fixed legend native-context policy probe",
    )

    assert result["nativeFallback"] is True, result
    assert result["automaticLegends"] == 0, result
    assert result["preserveDrawingBuffer"] is False, result
    assert result["snapshotReady"] is False, result


def test_live_best_ignores_unpainted_annotation_and_fixed_legend_boxes(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.chart(
        xy.scatter([0.04], [0.04], name="series", size=6),
        xy.text(
            0.98,
            0.98,
            "opacity zero ghost",
            anchor="end",
            style={"opacity": 0},
        ),
        xy.text(
            0.98,
            0.92,
            "transparent ghost",
            color="#00000000",
            anchor="end",
        ),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=520,
        height=360,
    )
    document = probe_document(chart, _INVISIBLE_ANNOTATION_PROBE)
    capture = "window.__fcProbeView = xy.renderStandalone("
    assert capture in document
    document = document.replace(
        capture,
        """
spec.extra_legends = [{
  items: [{ name: "hidden fixed", kind: "line", style: { color: "#9333ea" } }],
  loc: "upper right",
  style: { visibility: "hidden" },
}];
"""
        + capture,
        1,
    )
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "legend_best_invisible_annotations.html",
        "data-xy-legend-invisible-annotation",
        label="unpainted annotation legend obstacle probe",
    )

    assert result["legendCount"] == 2, result
    assert result["hiddenFixed"]["visible"] is False, result
    # Visibility-hidden boxes retain geometry, which is the exact case that
    # previously became a false occupancy obstacle.
    assert result["hiddenFixed"]["width"] > 0, result
    assert result["hiddenFixed"]["loc"] == "upper right", result
    visible_fixed = result["visibleFixed"]
    assert {key: visible_fixed[key] for key in ("loc", "visible")} == {
        "loc": "upper left",
        "visible": True,
    }, result
    moved_fixed = result["movedFixed"]
    assert {key: moved_fixed[key] for key in ("loc", "visible")} == {
        "loc": "upper right",
        "visible": True,
    }, result
    assert moved_fixed["rect"]["left"] < visible_fixed["rect"]["left"], result
    assert moved_fixed["rect"]["width"] == pytest.approx(visible_fixed["rect"]["width"]), result
    assert moved_fixed["rect"]["height"] == pytest.approx(visible_fixed["rect"]["height"]), result
    assert result["labelCount"] == 2, result
    assert result["painted"] == [False, False], result
    assert result["normalizedLegendWidth"] == pytest.approx(
        result["expectedLegendWidth"], abs=0.01
    ), result
    assert "0" in result["opacities"], result
    assert any(
        color.startswith("rgba(") and color.endswith(", 0)") for color in result["colors"]
    ), result


def test_hidden_auto_legend_skips_readback_and_rescores_when_visible(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        probe_document(_mixed_chart(), _HIDDEN_LEGEND_PROBE),
        tmp_path / "legend_best_hidden.html",
        "data-xy-legend-best-hidden",
        label="hidden automatic legend readback probe",
    )

    assert result["initial"] == "upper left", result
    assert result["cleanDraws"] == {
        "dirty": False,
        "readbackDelta": 0,
        "visibilityDelta": 0,
    }, result
    assert result["hiddenViewReadbackDelta"] == 0, result
    assert result["displayHidden"] == {
        "visible": False,
        "dirty": False,
        "readbackDelta": 0,
    }, result
    display_restored = result["displayRestored"]
    assert {key: display_restored[key] for key in ("visible", "dirty", "readbackDelta", "loc")} == {
        "visible": True,
        "dirty": False,
        "readbackDelta": 1,
        "loc": "upper right",
    }, result
    assert display_restored["width"] > 0, result
    assert display_restored["height"] > 0, result
    assert result["halfScale"]["visible"] is True, result
    assert result["halfScale"]["dirty"] is False, result
    assert result["halfScale"]["readbackDelta"] == 1, result
    assert result["halfScale"]["width"] == pytest.approx(
        display_restored["width"] * 0.5,
    ), result
    assert result["halfScale"]["height"] == pytest.approx(
        display_restored["height"] * 0.5,
    ), result
    assert result["fullScale"]["visible"] is True, result
    assert result["fullScale"]["dirty"] is False, result
    assert result["fullScale"]["readbackDelta"] == 1, result
    assert result["fullScale"]["width"] == pytest.approx(
        display_restored["width"],
    ), result
    assert result["fullScale"]["height"] == pytest.approx(
        display_restored["height"],
    ), result
    assert result["zeroSized"]["clientRectCount"] > 0, result
    assert result["zeroSized"]["width"] == 0, result
    assert result["zeroSized"]["visible"] is False, result
    assert result["zeroSized"]["dirty"] is False, result
    assert result["zeroSized"]["readbackDelta"] == 0, result
    assert result["zeroSizeRestored"] == {
        "visible": True,
        "dirty": False,
        "readbackDelta": 1,
        "loc": "upper right",
    }, result
    assert result["collapsedViewReadbackDelta"] == 0, result
    assert result["collapsed"] == {
        "visible": False,
        "dirty": False,
        "readbackDelta": 0,
    }, result
    assert result["collapseRestored"] == {
        "visible": True,
        "dirty": False,
        "readbackDelta": 1,
        "loc": "upper left",
    }, result
    assert result["resizeDisconnected"] is True, result
    assert result["mutationDisconnected"] is True, result
    assert result["observersReleased"] is True, result


def test_update_payload_keeps_auto_legend_chrome_and_scores_after_animation(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    initial = _payload_update_chart(0.96, 0.96)
    # Put the replacement mark under the prior upper-left live winner. Its
    # empty upper-right challenger must move after the animation settles; a
    # lower-left point would leave both upper boxes empty and correctly retain
    # upper-left under live hysteresis, making this settle hook unobservable.
    replacement = _payload_update_chart(0.04, 0.96)
    initial_spec, _ = initial.figure().build_payload()
    next_spec, next_buffer = replacement.figure().build_payload()
    next_spec["animation"] = xy.animation(
        enabled=True,
        duration=90,
        update="interpolate",
        interpolate=("position",),
    ).to_spec()
    assert initial_spec["legend"]["loc"] == "upper left"
    assert next_spec["legend"]["loc"] == "upper right"
    head = (
        f"<script>const NEXT_SPEC = {json.dumps(next_spec)};"
        f'const NEXT_B64 = "{base64.b64encode(next_buffer).decode("ascii")}";</script>'
    )
    result = run_browser_probe(
        chromium,
        probe_document(initial, _UPDATE_PAYLOAD_PROBE, head=head),
        tmp_path / "legend_best_update_payload.html",
        "data-xy-legend-update-payload",
        label="automatic legend updatePayload settle probe",
    )

    assert result["applied"] is True, result
    assert result["sameLegendNode"] is True, result
    assert result["animationActive"] is True, result
    assert result["before"] == "upper left", result
    assert result["during"] == result["before"], result
    assert result["dirtyDuring"] is True, result
    assert result["after"] == "upper right", result
    assert result["after"] == result["nextFallback"], result
    assert result["dirtyAfter"] is False, result
    assert result["unavailableApplied"] is True, result
    assert result["unavailableFallback"] == "lower right", result
