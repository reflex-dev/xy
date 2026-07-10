"""Browser interaction benchmark for fastcharts.

This is intentionally opt-in instead of part of the core CodSpeed suite:
headless Chromium is useful for user-visible latency, but too heavyweight and
machine-sensitive for every microbenchmark run. The benchmark measures the
actual ChartView paths for zoom, pan, hover, and box zoom, then verifies that
the canvas produced nonblank WebGL pixels.

Usage:
  PYTHONPATH=python .venv/bin/python benchmarks/bench_interaction.py --sizes 1e4,1e5,1e6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fastcharts_browser import (  # noqa: E402
    chart_payload,
    json_bytes,
    page_for_charts,
    run_json_probe,
)
from categories import BENCHMARK_CATEGORIES, categories_for, markdown_category_table  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

INTERACTION_CATEGORY_IDS = (
    "medium_direct_scatter",
    "huge_scatter_overview",
    "huge_line_time_series",
    "core_2d_chart_breadth",
    "interaction_smoothness",
)
RENDER_W, RENDER_H = 900, 420
TOOLTIP_SAMPLE_COUNT = 8
INTERACTION_BUDGETS_MS = {
    "wheel_zoom_p95_ms": 600.0,
    "pan_p95_ms": 300.0,
    "crosshair_p95_ms": 300.0,
    "hover_p95_ms": 350.0,
    "box_zoom_p95_ms": 300.0,
    "brush_select_p95_ms": 200.0,
}
INTERACTION_VISUAL_BUDGETS = {
    # Normalized mean RGB delta between adjacent zoom frames. This is a guard
    # against the "flash to a totally different ramp" class of density/LOD bugs,
    # not a perceptual golden image test.
    "max_frame_color_delta": 0.85,
    # WebGL readback floor during repeated zoom/pan/box interactions. This catches
    # "technically nonblank but visibly collapsed" frames.
    "min_interaction_lit_pixels": 64,
}


def _parse_sizes(text: str) -> list[int]:
    return [int(float(part)) for part in text.split(",") if part.strip()]


def _scatter_figure(n: int) -> Any:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_interaction.py")
    from fastcharts import Figure

    rng = np.random.default_rng(70_011 + n)
    x = rng.normal(0.0, 1.0, n).astype(np.float64, copy=False)
    y = (0.58 * x + rng.normal(0.0, 0.72, n)).astype(np.float64, copy=False)
    fig = Figure(
        width=RENDER_W,
        height=RENDER_H,
        title=f"{n:,} point interaction probe",
        x_label="x",
        y_label="y",
    ).scatter(x, y, name="points", opacity=0.72)
    fig.set_interaction(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    )
    return fig


def _core_interaction_figures() -> list[dict[str, Any]]:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_interaction.py")
    from fastcharts import Figure

    rng = np.random.default_rng(89_021)

    x_line = np.linspace(0.0, 18_000.0, 120_000, dtype=np.float64)
    y_line = np.cumsum(rng.normal(0.0, 0.18, x_line.size)).astype(np.float64, copy=False)
    line = Figure(
        width=RENDER_W,
        height=RENDER_H,
        title="120k sample line interaction probe",
        x_label="sample",
        y_label="signal",
    ).line(x_line, y_line, name="signal", width=1.4)
    line.set_interaction(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    )

    hist_values = np.concatenate(
        [
            rng.normal(-1.1, 0.52, 70_000),
            rng.normal(1.35, 0.68, 50_000),
        ]
    )
    hist = Figure(
        width=RENDER_W,
        height=RENDER_H,
        title="120k value histogram interaction probe",
        x_label="value",
        y_label="count",
    ).histogram(hist_values, bins=180, name="distribution")
    hist.set_interaction(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    )

    categories = [f"C{i:04d}" for i in range(1_200)]
    values = (
        42.0
        + 18.0 * np.sin(np.linspace(0.0, 18.0, len(categories)))
        + rng.normal(0.0, 3.0, len(categories))
    )
    bars = Figure(
        width=RENDER_W,
        height=RENDER_H,
        title="1.2k bar interaction probe",
        x_label="category",
        y_label="value",
    ).bar(categories, values, name="bars")
    bars.set_interaction(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    )

    hx = np.linspace(-3.0, 3.0, 220)
    hy = np.linspace(-2.4, 2.4, 180)
    xx, yy = np.meshgrid(hx, hy)
    z = np.exp(-((xx - 0.85) ** 2 + (yy + 0.3) ** 2)) + 0.72 * np.exp(
        -((xx + 1.2) ** 2 + (yy - 0.65) ** 2) / 0.52
    )
    heatmap = Figure(
        width=RENDER_W,
        height=RENDER_H,
        title="220x180 heatmap interaction probe",
        x_label="x",
        y_label="y",
    ).heatmap(z, x=hx, y=hy, name="heat")
    heatmap.set_interaction(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    )

    return [
        {
            "scenario": "line_120k_interaction",
            "family": "line",
            "n": int(x_line.size),
            "category_ids": ("huge_line_time_series", "interaction_smoothness"),
            "figure": line,
        },
        {
            "scenario": "histogram_120k_interaction",
            "family": "histogram",
            "n": int(hist_values.size),
            "category_ids": ("core_2d_chart_breadth", "interaction_smoothness"),
            "figure": hist,
        },
        {
            "scenario": "bar_1200_interaction",
            "family": "bar",
            "n": len(categories),
            "category_ids": ("core_2d_chart_breadth", "interaction_smoothness"),
            "figure": bars,
        },
        {
            "scenario": "heatmap_39600_interaction",
            "family": "heatmap",
            "n": int(z.size),
            "category_ids": ("core_2d_chart_breadth", "interaction_smoothness"),
            "figure": heatmap,
        },
    ]


def _probe_js(reps: int) -> str:
    return f"""
(() => {{
  try {{
    const payload = FC_CHARTS[0];
    const el = document.createElement("div");
    document.getElementById("root").appendChild(el);
    const view = fastcharts.renderStandalone(el, payload.spec, fcBytesFromB64(payload.b64));
    view._drawNow();
    const before = {{...view.view}};
    const canvasRect = () => view.canvas.getBoundingClientRect();
    view.canvas.setPointerCapture = () => {{}};
    view.canvas.releasePointerCapture = () => {{}};
    const eventAt = (fx, fy) => {{
      const r = canvasRect();
      return {{
        clientX: r.left + r.width * fx,
        clientY: r.top + r.height * fy,
      }};
    }};

    // Warm shader compilation, DOM tooltip layout, crosshair nodes, and local
    // selection buffers so the measured p95 is steady-state interaction cost.
    view._zoomAt(0.99, 0.5, 0.5, false);
    view._setView(before, {{animate: false, request: false}});
    view._updateCrosshair(eventAt(0.5, 0.5));
    view.canvas.dispatchEvent(new PointerEvent("pointermove", {{
      bubbles: true,
      pointerId: 1,
      ...eventAt(0.5, 0.5),
    }}));
    const warmX0 = before.x0 + (before.x1 - before.x0) * 0.35;
    const warmX1 = before.x0 + (before.x1 - before.x0) * 0.65;
    const warmY0 = before.y0 + (before.y1 - before.y0) * 0.35;
    const warmY1 = before.y0 + (before.y1 - before.y0) * 0.65;
    view._selectLocal(warmX0, warmX1, warmY0, warmY1);
    view._clearSelection();
    settlePixels();

    let viewChanged = false;
    function noteViewChanged() {{
      const v = view.view;
      if (Math.abs(v.x0 - before.x0) > 1e-9 || Math.abs(v.x1 - before.x1) > 1e-9 ||
          Math.abs(v.y0 - before.y0) > 1e-9 || Math.abs(v.y1 - before.y1) > 1e-9) {{
        viewChanged = true;
      }}
    }}

    function settlePixels() {{
      if (view._pendingWheelZoom) {{
        const pending = view._pendingWheelZoom;
        view._pendingWheelZoom = null;
        if (view._wheelZoomRaf) cancelAnimationFrame(view._wheelZoomRaf);
        view._wheelZoomRaf = null;
        view._zoomAt(pending.factor, pending.fx, pending.fy, false);
      }}
      if (view._viewAnim) {{
        const target = view._viewAnim.target;
        view._cancelViewAnimation();
        view.view = target;
      }}
      if (view._raf) {{
        cancelAnimationFrame(view._raf);
        view._raf = null;
      }}
      const gl = view.gl;
      view._drawNow();
      const pixel = new Uint8Array(4);
      gl.readPixels(
        Math.max(0, Math.floor(gl.drawingBufferWidth / 2)),
        Math.max(0, Math.floor(gl.drawingBufferHeight / 2)),
        1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel
      );
    }}
    function measure(fn, trackView = false) {{
      const values = [];
      for (let i = 0; i < {reps}; i++) {{
        const t0 = performance.now();
        fn(i);
        if (trackView) noteViewChanged();
        settlePixels();
        values.push(performance.now() - t0);
      }}
      return fcStats(values);
    }}
    function nonblankCanvasPixels() {{
      view._drawNow();
      const gl = view.gl;
      const w = gl.drawingBufferWidth;
      const h = gl.drawingBufferHeight;
      const pixels = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      let count = 0;
      for (let i = 0; i < pixels.length; i += 4) {{
        if (pixels[i] || pixels[i + 1] || pixels[i + 2] || pixels[i + 3]) count++;
      }}
      return count;
    }}
    function tickLabelOverlapCount() {{
      view._lastLabelDraw = null;
      view._drawNow();
      const labels = Array.from(view.labels.querySelectorAll("[data-fc-label-kind='tick']"))
        .filter((node) => {{
          const style = getComputedStyle(node);
          return style.display !== "none" && style.visibility !== "hidden";
        }})
        .map((node) => ({{
          axis: node.dataset.fcAxis || "",
          side: node.dataset.fcAxisSide || "",
          text: node.textContent || "",
          rect: node.getBoundingClientRect(),
        }}))
        .filter((item) => item.rect.width > 0 && item.rect.height > 0);
      let overlaps = 0;
      for (let i = 0; i < labels.length; i++) {{
        for (let j = i + 1; j < labels.length; j++) {{
          const a = labels[i], b = labels[j];
          if (a.axis !== b.axis || a.side !== b.side) continue;
          const gap = 1.0;
          if (
            a.rect.left < b.rect.right - gap &&
            a.rect.right > b.rect.left + gap &&
            a.rect.top < b.rect.bottom - gap &&
            a.rect.bottom > b.rect.top + gap
          ) {{
            overlaps++;
          }}
        }}
      }}
      return {{ label_count: labels.length, tick_label_overlap_count: overlaps }};
    }}
    function interactionBlankFrameProbe() {{
      const saved = {{...view.view}};
      let blankFrameCount = 0;
      let minLit = Infinity;
      const record = () => {{
        const lit = nonblankCanvasPixels();
        minLit = Math.min(minLit, lit);
        if (lit <= 0) blankFrameCount++;
      }};
      for (let i = 0; i < 8; i++) {{
        view._zoomAt(i % 2 ? 1.08 : 0.92, 0.35 + (i % 3) * 0.15, 0.42, false);
        record();
      }}
      for (let i = 0; i < 8; i++) {{
        const v = view.view;
        const dx = (v.x1 - v.x0) * (i % 2 ? 0.018 : -0.018);
        const dy = (v.y1 - v.y0) * (i % 2 ? -0.012 : 0.012);
        view._setView({{x0: v.x0 + dx, x1: v.x1 + dx, y0: v.y0 + dy, y1: v.y1 + dy}}, {{
          animate: false,
          request: false,
        }});
        record();
      }}
      for (let i = 0; i < 4; i++) {{
        const v = view.view;
        const x0 = v.x0 + (v.x1 - v.x0) * 0.25;
        const x1 = v.x0 + (v.x1 - v.x0) * 0.75;
        const y0 = v.y0 + (v.y1 - v.y0) * 0.25;
        const y1 = v.y0 + (v.y1 - v.y0) * 0.75;
        view._zoomToBox([x0, y0], [x1, y1], false);
        record();
        view._setView(saved, {{animate: false, request: false}});
        record();
      }}
      view._setView(saved, {{animate: false, request: false}});
      return {{
        blank_frame_count: blankFrameCount,
        min_interaction_lit_pixels: Number.isFinite(minLit) ? minLit : 0,
      }};
    }}
    function frameRgbSample() {{
      view._drawNow();
      const gl = view.gl;
      const fullW = gl.drawingBufferWidth;
      const fullH = gl.drawingBufferHeight;
      const w = Math.max(1, Math.min(96, fullW));
      const h = Math.max(1, Math.min(64, fullH));
      const x = Math.max(0, Math.floor((fullW - w) / 2));
      const y = Math.max(0, Math.floor((fullH - h) / 2));
      const pixels = new Uint8Array(w * h * 4);
      gl.readPixels(x, y, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      return pixels;
    }}
    function meanRgbDelta(a, b) {{
      if (!a || !b || a.length !== b.length || !a.length) return 0;
      let sum = 0;
      let samples = 0;
      for (let i = 0; i < a.length; i += 4) {{
        sum += Math.abs(a[i] - b[i]);
        sum += Math.abs(a[i + 1] - b[i + 1]);
        sum += Math.abs(a[i + 2] - b[i + 2]);
        samples += 3;
      }}
      return sum / (samples * 255);
    }}
    function colorContinuityProbe() {{
      const saved = {{...view.view}};
      let prev = frameRgbSample();
      let maxFrameColorDelta = 0;
      for (let i = 0; i < 10; i++) {{
        view._zoomAt(i % 2 ? 1.035 : 0.965, 0.48 + (i % 3) * 0.02, 0.52, false);
        const next = frameRgbSample();
        maxFrameColorDelta = Math.max(maxFrameColorDelta, meanRgbDelta(prev, next));
        prev = next;
      }}
      view._setView(saved, {{animate: false, request: false}});
      view._drawNow();
      return {{ max_frame_color_delta: maxFrameColorDelta }};
    }}
    function tooltipProbe() {{
      const eligible = view.gpuTraces.some((g) =>
        fastcharts.markOf(g.trace.kind).pointPick && g.tier !== "density");
      if (!eligible) return {{ tooltip_eligible: false, tooltip_stable: true, tooltip_visible_samples: 0 }};
      let hit = null;
      for (let sx = 4; sx < view.plot.w && !hit; sx += 5) {{
        for (let sy = 4; sy < view.plot.h; sy += 5) {{
          if (view._pickAt(sx, sy)) {{
            hit = {{ sx, sy }};
            break;
          }}
        }}
      }}
      if (!hit) return {{ tooltip_eligible: true, tooltip_stable: false, tooltip_visible_samples: 0 }};
      let visible = 0;
      let flickers = 0;
      const rect = canvasRect();
      for (let i = 0; i < {TOOLTIP_SAMPLE_COUNT}; i++) {{
        view.canvas.dispatchEvent(new PointerEvent("pointermove", {{
          bubbles: true,
          pointerId: 1,
          clientX: rect.left + hit.sx,
          clientY: rect.top + hit.sy,
        }}));
        if (view.tooltip && view.tooltip.style.display !== "none") visible++;
        else flickers++;
      }}
      return {{
        tooltip_eligible: true,
        tooltip_stable: flickers === 0,
        tooltip_visible_samples: visible,
      }};
    }}
    function viewsClose(a, b) {{
      const sx = Math.max(Math.abs(a.x1 - a.x0), Math.abs(b.x1 - b.x0), 1);
      const sy = Math.max(Math.abs(a.y1 - a.y0), Math.abs(b.y1 - b.y0), 1);
      return Math.abs(a.x0 - b.x0) <= sx * 1e-8 &&
        Math.abs(a.x1 - b.x1) <= sx * 1e-8 &&
        Math.abs(a.y0 - b.y0) <= sy * 1e-8 &&
        Math.abs(a.y1 - b.y1) <= sy * 1e-8;
    }}
    function span(v, axis) {{
      return Math.abs(v[axis + "1"] - v[axis + "0"]);
    }}
    function boxZoomInvariantProbe() {{
      view._setView(before, {{animate: false, request: false}});
      const x0 = before.x0 + (before.x1 - before.x0) * 0.24;
      const x1 = before.x0 + (before.x1 - before.x0) * 0.76;
      const y0 = before.y0 + (before.y1 - before.y0) * 0.24;
      const y1 = before.y0 + (before.y1 - before.y0) * 0.76;
      view._zoomToBox([x0, y0], [x1, y1], false);
      const after = {{...view.view}};
      const finite = [after.x0, after.x1, after.y0, after.y1].every(Number.isFinite);
      const changed = finite && !viewsClose(after, before);
      const narrowed = finite &&
        span(after, "x") < span(before, "x") * 0.75 &&
        span(after, "y") < span(before, "y") * 0.75;
      view._setView(before, {{animate: false, request: false}});
      const restored = viewsClose(view.view, before);
      return {{
        box_zoom_changed: changed,
        box_zoom_narrowed: narrowed,
        box_zoom_restored: restored,
      }};
    }}
    function brushSelectionInvariantProbe() {{
      view._setView(before, {{animate: false, request: false}});
      const eligible = view.gpuTraces.some((g) => g._cpu && g.tier !== "density" && g.n > 0);
      if (!eligible) {{
        view._clearSelection();
        return {{
          brush_select_eligible: false,
          brush_select_count: 0,
          brush_select_cleared: Number(view._selectionCount || 0) === 0,
        }};
      }}
      const x0 = before.x0 + (before.x1 - before.x0) * 0.12;
      const x1 = before.x0 + (before.x1 - before.x0) * 0.88;
      const y0 = before.y0 + (before.y1 - before.y0) * 0.12;
      const y1 = before.y0 + (before.y1 - before.y0) * 0.88;
      view._selectLocal(x0, x1, y0, y1);
      const count = Number(view._selectionCount || 0);
      view._clearSelection();
      const cleared = Number(view._selectionCount || 0) === 0 &&
        view.gpuTraces.every((g) => !g.selActive && !(g.drill && g.drill.selActive));
      return {{
        brush_select_eligible: true,
        brush_select_count: count,
        brush_select_cleared: cleared,
      }};
    }}

    const wheel = measure((i) => {{
      view.canvas.dispatchEvent(new WheelEvent("wheel", {{
        bubbles: true,
        cancelable: true,
        deltaY: i % 2 ? 26 : -26,
        ...eventAt(0.5, 0.5),
      }}));
    }}, true);
    const pan = measure((i) => {{
      const start = eventAt(0.5, 0.5);
      const end = eventAt(i % 2 ? 0.52 : 0.48, 0.5);
      view.canvas.dispatchEvent(new PointerEvent("pointerdown", {{bubbles: true, pointerId: 11, ...start}}));
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {{bubbles: true, pointerId: 11, ...end}}));
      view.canvas.dispatchEvent(new PointerEvent("pointerup", {{bubbles: true, pointerId: 11, ...end}}));
    }}, true);
    const hover = measure((i) => {{
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {{
        bubbles: true,
        pointerId: 1,
        ...eventAt(0.18 + (i % 9) * 0.08, 0.25 + (i % 7) * 0.07),
      }}));
    }});
    const crosshair = measure((i) => {{
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {{
        bubbles: true,
        pointerId: 2,
        ...eventAt(0.1 + (i % 8) * 0.1, 0.2 + (i % 6) * 0.1),
      }}));
    }});
    const box = measure((i) => {{
      const start = eventAt(0.22, 0.22);
      const end = eventAt(0.78, 0.78);
      const priorMode = view.dragMode;
      view.dragMode = "zoom";
      view.canvas.dispatchEvent(new PointerEvent("pointerdown", {{bubbles: true, pointerId: 12, ...start}}));
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {{bubbles: true, pointerId: 12, ...end}}));
      view.canvas.dispatchEvent(new PointerEvent("pointerup", {{bubbles: true, pointerId: 12, ...end}}));
      view.dragMode = priorMode;
      if (i % 2) view._setView(before, {{animate: false, request: false}});
    }}, true);
    const brush = measure((i) => {{
      const start = eventAt(0.18 + (i % 4) * 0.03, 0.18);
      const end = eventAt(0.68 + (i % 4) * 0.03, 0.82);
      view.canvas.dispatchEvent(new PointerEvent("pointerdown", {{
        bubbles: true, pointerId: 13, shiftKey: true, ...start,
      }}));
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {{
        bubbles: true, pointerId: 13, shiftKey: true, ...end,
      }}));
      view.canvas.dispatchEvent(new PointerEvent("pointerup", {{
        bubbles: true, pointerId: 13, shiftKey: true, ...end,
      }}));
      view._clearSelection();
    }});
    view._setView(before, {{animate: false, request: false}});
    settlePixels();
    const nonblank = Math.max(fcNonblankPixels(view), nonblankCanvasPixels());
    if (nonblank <= 0) throw new Error("blank WebGL canvas");
    const crosshairVisible = !!(view.crosshairX && view.crosshairY &&
      view.crosshairX.style.display === "block" && view.crosshairY.style.display === "block");
    const blankFrames = interactionBlankFrameProbe();
    const labelLayout = tickLabelOverlapCount();
    const colorContinuity = colorContinuityProbe();
    const tooltip = tooltipProbe();
    const boxZoomInvariant = boxZoomInvariantProbe();
    const brushSelectionInvariant = brushSelectionInvariantProbe();
    fcReport("FC_INTERACTION", {{
      status: "ok",
      tier: payload.spec.traces[0].tier,
      nonblank_pixels: nonblank,
      view_changed: viewChanged,
      crosshair_visible: crosshairVisible,
      ...blankFrames,
      ...labelLayout,
      ...colorContinuity,
      ...tooltip,
      ...boxZoomInvariant,
      ...brushSelectionInvariant,
      wheel_zoom: wheel,
      pan: pan,
      hover: hover,
      crosshair: crosshair,
      box_zoom: box,
      brush_select: brush,
    }});
  }} catch (err) {{
    fcFail("FC_INTERACTION", err);
  }}
}})();
"""


def _flatten_probe_metrics(row: dict[str, Any], result: dict[str, Any]) -> None:
    row["status"] = result.get("status", "failed(no status)")
    if row["status"] != "ok":
        return
    row["tier"] = result.get("tier")
    row["nonblank_pixels"] = result.get("nonblank_pixels")
    row["view_changed"] = bool(result.get("view_changed"))
    row["crosshair_visible"] = bool(result.get("crosshair_visible"))
    row["blank_frame_count"] = result.get("blank_frame_count")
    row["min_interaction_lit_pixels"] = result.get("min_interaction_lit_pixels")
    row["label_count"] = result.get("label_count")
    row["tick_label_overlap_count"] = result.get("tick_label_overlap_count")
    row["max_frame_color_delta"] = result.get("max_frame_color_delta")
    row["tooltip_eligible"] = bool(result.get("tooltip_eligible"))
    row["tooltip_stable"] = bool(result.get("tooltip_stable"))
    row["tooltip_visible_samples"] = result.get("tooltip_visible_samples")
    row["box_zoom_changed"] = bool(result.get("box_zoom_changed"))
    row["box_zoom_narrowed"] = bool(result.get("box_zoom_narrowed"))
    row["box_zoom_restored"] = bool(result.get("box_zoom_restored"))
    row["brush_select_eligible"] = bool(result.get("brush_select_eligible"))
    row["brush_select_count"] = result.get("brush_select_count")
    row["brush_select_cleared"] = bool(result.get("brush_select_cleared"))
    for name in ("wheel_zoom", "pan", "hover", "crosshair", "box_zoom", "brush_select"):
        stats = result.get(name) or {}
        row[f"{name}_median_ms"] = stats.get("median_ms")
        row[f"{name}_p95_ms"] = stats.get("p95_ms")
        row[f"{name}_p99_ms"] = stats.get("p99_ms")
        row[f"{name}_max_ms"] = stats.get("max_ms")
        row[f"{name}_reps"] = stats.get("reps")


# Virtual-time budget for the interaction probe pages. The default 15s is
# plenty on developer hardware, but CI runs WebGL through SwiftShader on
# shared runners, where the density scenario's reps can outlive it — the
# probe then never writes its marker title and the row reports
# "failed(no probe title)". Virtual time advances instantly once the page
# goes idle, so a large budget costs nothing when the probe finishes early.
# The wall-clock ceiling has the same failure mode — CI has produced
# "failed(timeout)" for the density scenario at the default 180s — so it
# gets matching headroom; a healthy probe never comes near either limit.
PROBE_VIRTUAL_TIME_MS = 120_000
PROBE_TIMEOUT_S = 600


def _probe_with_retries(
    html: str, *, chromium: str | None, scenario: str, retries: int
) -> dict[str, Any]:
    """One probe run, re-launched on a non-ok status up to `retries` times.

    Headless-Chromium probes have environmental failure modes (budget
    exhaustion, GPU init hiccups) that a fresh launch resolves; a genuine
    client regression fails every attempt. Retries are printed, never
    silent (§28: every reliability decision is recorded)."""
    result = run_json_probe(
        html,
        marker="FC_INTERACTION",
        chromium=chromium,
        virtual_time_ms=PROBE_VIRTUAL_TIME_MS,
        timeout_s=PROBE_TIMEOUT_S,
    )
    attempts = 1
    while result.get("status") != "ok" and attempts <= retries:
        print(
            f"interaction probe retry {attempts}/{retries} for {scenario}: {result.get('status')}",
            file=sys.stderr,
        )
        result = run_json_probe(
            html,
            marker="FC_INTERACTION",
            chromium=chromium,
            virtual_time_ms=PROBE_VIRTUAL_TIME_MS,
            timeout_s=PROBE_TIMEOUT_S,
        )
        attempts += 1
    return result


def run(
    *, sizes: list[int], reps: int, chromium: str | None = None, retries: int = 0
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for n in sizes:
        fig = _scatter_figure(n)
        spec, blob = fig.build_payload()
        tier = spec["traces"][0]["tier"]
        category_ids = (
            ("medium_direct_scatter", "interaction_smoothness")
            if tier == "direct"
            else ("huge_scatter_overview", "interaction_smoothness")
        )
        row: dict[str, Any] = {
            "scenario": f"{tier}_scatter_interaction",
            "n": n,
            "tier": tier,
            "benchmark_categories": [category["id"] for category in categories_for(category_ids)],
            "payload_bytes": json_bytes(spec) + len(blob),
        }
        html = page_for_charts(
            [chart_payload("interaction", spec, blob)],
            _probe_js(reps),
            title="fastcharts interaction probe",
        )
        row["html_bytes"] = len(html.encode("utf-8"))
        result = _probe_with_retries(
            html, chromium=chromium, scenario=row["scenario"], retries=retries
        )
        _flatten_probe_metrics(row, result)
        rows.append(row)

    for case in _core_interaction_figures():
        spec, blob = case["figure"].build_payload()
        tier = spec["traces"][0]["tier"]
        row = {
            "scenario": case["scenario"],
            "family": case["family"],
            "n": case["n"],
            "tier": tier,
            "benchmark_categories": [
                category["id"] for category in categories_for(case["category_ids"])
            ],
            "payload_bytes": json_bytes(spec) + len(blob),
        }
        html = page_for_charts(
            [chart_payload(case["scenario"], spec, blob)],
            _probe_js(reps),
            title=f"fastcharts {case['scenario']} probe",
        )
        row["html_bytes"] = len(html.encode("utf-8"))
        result = _probe_with_retries(
            html, chromium=chromium, scenario=case["scenario"], retries=retries
        )
        _flatten_probe_metrics(row, result)
        rows.append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "interaction-browser",
        "measurement_scope": "standalone-client-input-to-pixel-readback",
        "environment": collect_environment_metadata(chromium=chromium),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(INTERACTION_CATEGORY_IDS),
        "interaction_budgets_ms": dict(INTERACTION_BUDGETS_MS),
        "interaction_visual_budgets": dict(INTERACTION_VISUAL_BUDGETS),
        "tooltip_sample_count": TOOLTIP_SAMPLE_COUNT,
        "reps": reps,
        "rows": rows,
    }


def _fmt_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _fmt_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    n = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# fastcharts browser interaction benchmark",
        "",
        f"Repetitions per gesture: `{report['reps']}`.",
        f"Repeated tooltip samples per eligible row: `{report.get('tooltip_sample_count', 0)}`.",
        "",
        "## Benchmark Categories",
        "",
        *markdown_category_table(report.get("benchmark_categories", BENCHMARK_CATEGORIES)),
        "",
        "Tracked in this run: "
        + ", ".join(f"`{category['id']}`" for category in report["tracked_categories"]),
        "",
        "## Budgets",
        "",
        "| metric | p95 budget |",
        "|---|---:|",
    ]
    for metric, budget in report["interaction_budgets_ms"].items():
        lines.append(f"| `{metric}` | {budget:.1f} ms |")
    lines += [
        "",
        "| visual invariant | budget |",
        "|---|---:|",
    ]
    for metric, budget in report.get("interaction_visual_budgets", {}).items():
        direction = ">=" if metric.startswith("min_") else "<="
        lines.append(f"| `{metric}` | {direction} {budget:.2f} |")
    lines += [
        "",
        "## Results",
        "",
        "| scenario | points | tier | payload | wheel p95 | pan p95 | hover p95 | crosshair p95 | box p95 | brush p95 | box zoom | brush select | blank frames | tick overlaps | color delta | tooltip | status |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {scenario} | {n:,} | {tier} | {payload} | {wheel} | {pan} | {hover} | {crosshair} | {box} | {brush} | {box_state} | {brush_count} | {blank} | {overlaps} | {color_delta} | {tooltip} | {status} |".format(
                scenario=row["scenario"],
                n=row["n"],
                tier=row.get("tier", "—"),
                payload=_fmt_bytes(row.get("payload_bytes")),
                wheel=_fmt_ms(row.get("wheel_zoom_p95_ms")),
                pan=_fmt_ms(row.get("pan_p95_ms")),
                hover=_fmt_ms(row.get("hover_p95_ms")),
                crosshair=_fmt_ms(row.get("crosshair_p95_ms")),
                box=_fmt_ms(row.get("box_zoom_p95_ms")),
                brush=_fmt_ms(row.get("brush_select_p95_ms")),
                box_state=(
                    "ok"
                    if row.get("box_zoom_changed")
                    and row.get("box_zoom_narrowed")
                    and row.get("box_zoom_restored")
                    else "fail"
                ),
                brush_count=(
                    row.get("brush_select_count", "—")
                    if row.get("brush_select_eligible")
                    else "n/a"
                ),
                blank=row.get("blank_frame_count", "—"),
                overlaps=row.get("tick_label_overlap_count", "—"),
                color_delta=(
                    "—"
                    if row.get("max_frame_color_delta") is None
                    else f"{row['max_frame_color_delta']:.3f}"
                ),
                tooltip="ok" if row.get("tooltip_stable") else "fail",
                status=row.get("status", "unknown"),
            )
        )
    lines += [
        "",
        "Notes:",
        "",
        "- Timed gestures enter through DOM events, flush queued wheel/animation state, draw, and perform a WebGL readback before the sample stops.",
        "- Scope is standalone client input-to-GPU-finish; widget/backend LOD work is measured by native and workflow rows.",
        "- `nonblank` is a WebGL readback sanity check over the rendered chart canvas.",
        "- Budget verification rejects blank canvases, blank interaction frames, missing view changes, missing crosshair chrome, box zoom that does not narrow/restore the viewport, brush selection that does not select/clear eligible marks, overlapping tick labels, unstable tooltips, oversized frame color jumps, and p95 values over the listed limits.",
        "- Scatter rows sweep the requested sizes; line, histogram, bar, and heatmap rows are fixed core-family probes so interaction regressions are not scatter-only.",
        "- The density rows measure client interaction over the current density surface; backend drilldown switching is tracked separately in CodSpeed.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="1e4,1e5,1e6")
    parser.add_argument("--reps", type=int, default=24)
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--out", default=None, help="write Markdown report here")
    parser.add_argument("--json", default=None, help="write JSON report here")
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help="per-scenario probe relaunches on a non-ok status (for shared CI runners)",
    )
    args = parser.parse_args()

    report = run(
        sizes=_parse_sizes(args.sizes),
        reps=args.reps,
        chromium=args.chromium,
        retries=args.retries,
    )
    md = to_markdown(report)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
