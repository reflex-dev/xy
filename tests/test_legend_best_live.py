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
from pathlib import Path

import pytest

import xy
from conftest import probe_document, run_browser_probe
from xy.export import find_chromium

ROOT = Path(__file__).resolve().parents[1]
CHARTVIEW = ROOT / "js" / "src" / "50_chartview.ts"
INTERACTION = ROOT / "js" / "src" / "53_interaction.ts"
KERNEL = ROOT / "js" / "src" / "54_kernel.ts"
ANIMATION = ROOT / "js" / "src" / "56_animation.ts"
WRAPPER = ROOT / "python" / "reflex_xy" / "assets" / "XYChart.jsx"


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
      rasterBytes: view._legendBestScratch.width * view._legendBestScratch.height * 4,
      markKinds: view.spec.traces.map((trace) => trace.kind),
      annotationLabels: document.querySelectorAll(
        '[data-xy-slot="annotation_label"]'
      ).length,
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
(() => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view.root.style.transform = "scale(0.6)";
    view.root.style.transformOrigin = "top left";
    view._markBestLegendsDirty();
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._drawNow();
    const legend = document.querySelector('[data-xy-slot="legend"]');
    const labels = [...document.querySelectorAll('[data-xy-slot="annotation_label"]')];
    const raster = view._bestLegendRaster();
    document.body.setAttribute("data-xy-legend-invisible-annotation", JSON.stringify({
      loc: legend?.dataset.xyLegendLoc || null,
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


def _mixed_chart():
    # Every mark and the annotation occupies the home view's upper-right
    # corner. In the 0.8..1.0 viewport they all project into the lower-left.
    return xy.chart(
        xy.line([0.82, 0.86], [0.82, 0.86], name="line"),
        xy.scatter([0.83, 0.85], [0.85, 0.83], name="scatter", size=12),
        xy.area([0.82, 0.86], [0.84, 0.86], base=[0.80, 0.80], name="area"),
        xy.bar([0.84], [0.86], base=[0.80], width=0.04, name="bar"),
        xy.text(0.84, 0.84, "important"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
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


def test_live_best_source_contract_is_bounded_and_settled() -> None:
    source = CHARTVIEW.read_text(encoding="utf-8")
    interaction = INTERACTION.read_text(encoding="utf-8")
    kernel = KERNEL.read_text(encoding="utf-8")
    animation = ANIMATION.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    helper = source.split("export function xyLegendBestLocation", 1)[1].split(
        "// SVG gradient ids", 1
    )[0]
    raster = source.split("  _bestLegendRaster()", 1)[1].split("  _bestLegendLocationForRaster", 1)[
        0
    ]

    assert "LEGEND_BEST_GRID_W = 96" in source
    assert "LEGEND_BEST_GRID_H = 72" in source
    assert "LEGEND_BEST_TIE_BAND" not in source
    assert "(scores.get(loc) ?? Infinity) === floor" in helper
    assert helper.index('"upper right"') < helper.index('"upper left"')
    assert "getImageData" in raster
    assert "this.canvas" in raster and "this.overlay" in raster
    assert "this.chrome" not in raster
    assert "._cpu" not in raster
    assert "this._drawChrome();\n    this._maybePositionBestLegends();" in source
    assert 'phase === "end" && this._markBestLegendsDirty()' in source
    assert 'this.spec?.coords !== "polar"' in source
    assert "!Array.isArray(options.anchor)" in source
    assert interaction.count("this._settleBestLegendInteraction();") == 2
    cancelled_animation = interaction.split("  _cancelViewAnimation()", 1)[1].split(
        "  _setView", 1
    )[0]
    assert "const wasActive = !!this._viewAnim;" in cancelled_animation
    assert "wasActive && this._markBestLegendsDirty?.()" in cancelled_animation
    native_gl = source.split("    } else {\n      if (!this._governorRegistered)", 1)[1].split(
        "    }\n    this.gl = gl;", 1
    )[0]
    assert "preserveDrawingBuffer: needsLegendBestSnapshot" in native_gl
    assert 'legend.dataset.xyLegendAutoLoc === "best"' in native_gl
    assert "gl.getContextAttributes()?.preserveDrawingBuffer === true" in native_gl
    assert "!this._glHost && this._legendBestCanvasSnapshotReady !== true" in raster
    context_loss = source.split('this._listen(this.canvas, "webglcontextlost"', 1)[1].split(
        'this._listen(this.canvas, "webglcontextrestored"', 1
    )[0]
    assert "this._legendBestInteractionActive = false;" in context_loss
    assert "this._markBestLegendsDirty();" in context_loss
    assert "g._drillBackdropTick || g._blendTick || g.drill?._blendTick" in source
    assert "this._bestLegendAnnotationPainted(label)" in raster
    assert "plot: this.canvas.getBoundingClientRect()" in raster
    assert "(left - plotLeft) / plotRect.width" in source
    annotation_paint = source.split("  _bestLegendAnnotationPainted", 1)[1].split(
        "  _bestLegendRaster", 1
    )[0]
    assert "getComputedStyle(node)" in annotation_paint
    assert 'style.visibility === "hidden"' in annotation_paint
    assert "Number(style.opacity) <= 0" in annotation_paint
    assert "transparent(labelStyle.color)" in annotation_paint
    assert kernel.count("if (legendGeometryChanged) this._markBestLegendsDirty();") == 2
    sample_rebin = kernel.split("  _applySampleRebinGrid", 1)[1].split("  _applyAppend", 1)[0]
    append = kernel.split("  _applyAppend", 1)[1].split("  _scheduleAppendRefine", 1)[0]
    assert "this._markBestLegendsDirty();" in sample_rebin
    assert "this._markBestLegendsDirty();" in append
    update_payload = animation.split("  updatePayload(spec, buffer)", 1)[1]
    assert "this._adoptBestLegendFallbacks?.(spec);" in update_payload
    assert "this.gpuTraces = spec.traces.map" in update_payload
    assert update_payload.index("this.gpuTraces = spec.traces.map") < update_payload.index(
        "this._markBestLegendsDirty?.();", update_payload.index("this.gpuTraces = spec.traces.map")
    )
    assert "const mountedLegendSpec = (legend, coords) =>" in wrapper
    assert "const { loc: _concreteFallback, ...mounted } = legend;" in wrapper
    assert "legend: mountedLegendSpec(spec?.legend, spec?.coords)" in wrapper
    assert "mountedLegendSpec(legend, spec?.coords)" in wrapper


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


def test_live_best_ignores_unpainted_annotation_labels(tmp_path: Path) -> None:
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
    result = run_browser_probe(
        chromium,
        probe_document(chart, _INVISIBLE_ANNOTATION_PROBE),
        tmp_path / "legend_best_invisible_annotations.html",
        "data-xy-legend-invisible-annotation",
        label="unpainted annotation legend obstacle probe",
    )

    assert result["labelCount"] == 2, result
    assert result["painted"] == [False, False], result
    assert result["loc"] == "upper right", result
    assert result["normalizedLegendWidth"] == pytest.approx(
        result["expectedLegendWidth"], abs=0.01
    ), result
    assert "0" in result["opacities"], result
    assert any(
        color.startswith("rgba(") and color.endswith(", 0)") for color in result["colors"]
    ), result


def test_update_payload_keeps_auto_legend_chrome_and_scores_after_animation(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    initial = _payload_update_chart(0.96, 0.96)
    replacement = _payload_update_chart(0.04, 0.04)
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
