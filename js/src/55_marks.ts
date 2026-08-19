import { chartBackdrop, parseColor } from "./20_theme";

// ---------------------------------------------------------------------------
// Mark-renderer registry — the client-side dispatch for chart kinds.
//
// Mirrors the kernel's `_emit_<kind>` dispatch (figure.py) so the two sides
// stay symmetric: adding a 2D chart is an entry here plus an `_emit_<kind>`,
// not another branch inside ChartView. A renderer owns two steps for its kind:
//
//   build(view, g, trace, buffer)   — GPU setup: upload geometry/attribute
//                                     buffers onto the gpu record `g`. Reuse
//                                     view._buildXY for plain (x,y) marks; a
//                                     mark with its own vertex layout (bars,
//                                     candles) uploads its own buffers.
//   draw(view, g, x0, x1, y0, y1)   — one frame in the current data window.
//                                     xy marks map with view._map(); a mark
//                                     with a different transform maps itself.
//
// Tiering is orthogonal: a density-tier trace is handled by 45_lod.js before
// this registry is consulted (its drilled marks still render as points today).
// Picking and legend swatches are separate extension points documented in
// spec/api/chart-kind-contract.md — generalize them when a pickable non-point
// mark actually lands, not preemptively.
// ---------------------------------------------------------------------------

// Capabilities (beyond build/draw) so no per-kind knowledge leaks back into
// ChartView branches:
//   pointPick    — marks are point-shaped and participate in the GPU ID pick
//                  pass (§17). A future rect/candle mark supplies its own pick
//                  step instead (see spec/api/chart-kind-contract.md).
//   retainCpu    — standalone export keeps CPU f32 copies of x/y so hover can
//                  read approximate values with no kernel attached (§37).
//   refreshColor — re-resolve CSS-expressed constant colors on theme change
//                  (§36 live re-resolution); each kind knows where its
//                  constant color lives in the spec.
const RECT_MARK = {
  build: (view, g, t, buffer) => view._buildRectMark(g, t, buffer),
  draw: (view, g) => {
    const [x0, x1] = view._axisRange(g.xAxis);
    const [y0, y1] = view._axisRange(g.yAxis);
    const edgePad = g.trace.kind === "histogram"
      ? [0, 0, view._edgePadForValue(0, y0, y1, view.canvas.height), 0]
      : [0, 0, 0, 0];
    view._drawRects(
      g,
      view._map(g.x0Meta, x0, x1, g.xAxis),
      view._map(g.x1Meta, x0, x1, g.xAxis),
      view._map(g.y0Meta, y0, y1, g.yAxis),
      view._map(g.y1Meta, y0, y1, g.yAxis),
      edgePad
    );
  },
  refreshColor: (view, g) => {
    if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
    // stroke + gradient stops are CSS-expressed too — re-resolve with the theme.
    view._rectMarkStyleGpu(g, g.trace);
  },
};

const BAR_MARK = {
  build: (view, g, t, buffer) => view._buildBarMark(g, t, buffer),
  draw: (view, g) => {
    if (!g.trace.bar) {
      RECT_MARK.draw(view, g);
      return;
    }
    const horizontal = g.orientation === 1;
    const pAxis = horizontal ? g.yAxis : g.xAxis;
    const vAxis = horizontal ? g.xAxis : g.yAxis;
    const [p0, p1] = view._axisRange(pAxis);
    const [v0, v1] = view._axisRange(vAxis);
    const pmap = view._map(g.posMeta, p0, p1, pAxis);
    const v1map = view._map(g.value1Meta, v0, v1, vAxis);
    const v0map = g.value0Mode === 1
      ? view._map(g.value0Meta, v0, v1, vAxis)
      : null;
    const v0Const = g.value0Mode === 0
      ? view._mapConst(g.value0Const, v0, v1, vAxis)
      : null;
    const v0EdgePad = g.value0Mode === 0
      ? view._edgePadForValue(
        g.value0Const,
        v0,
        v1,
        horizontal ? view.canvas.width : view.canvas.height
      )
      : 0;
    view._drawBars(g, pmap, v1map, v0map, v0Const, v0EdgePad);
  },
  refreshColor: (view, g) => {
    if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
    // stroke + gradient stops are CSS-expressed too — re-resolve with the theme.
    view._rectMarkStyleGpu(g, g.trace);
  },
};

const SEGMENT_MARK = {
  build: (view, g, t, buffer) => view._buildSegmentMark(g, t, buffer),
  draw: (view, g) => {
    const [x0, x1] = view._axisRange(g.xAxis);
    const [y0, y1] = view._axisRange(g.yAxis);
    view._drawSegments(
      g,
      view._map(g.x0Meta, x0, x1, g.xAxis),
      view._map(g.y0Meta, y0, y1, g.yAxis),
    );
  },
  refreshColor: (view, g) => {
    if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
  },
};

const AREA_MARK = {
  build: (view, g, t, buffer) => view._buildAreaMark(g, t, buffer),
  draw: (view, g) => {
    const [x0, x1] = view._axisRange(g.xAxis);
    const [y0, y1] = view._axisRange(g.yAxis);
    const xm = view._map(g.xMeta, x0, x1, g.xAxis);
    const ym = view._map(g.yMeta, y0, y1, g.yAxis);
    view._drawArea(g, xm, ym, view._map(g.baseMeta, y0, y1, g.yAxis));
    if ((g.trace.style.line_width ?? 0) > 0) {
      view._drawLine(g, xm, ym, g.lineColor, g.trace.style.line_width, g.trace.style.line_opacity ?? 1);
      if (g.trace.style.stroke_perimeter) {
        // fill_between is a closed polygon. Draw its second boundary too;
        // the generic area mark intentionally outlines only the value curve.
        const yBuf = g.yBuf, yMeta = g.yMeta, dashY = g._dashY;
        g.yBuf = g.baseBuf;
        g.yMeta = g.baseMeta;
        g._dashY = g._cpu.base;
        view._drawLine(g, xm, ym, g.lineColor, g.trace.style.line_width, g.trace.style.line_opacity ?? 1);
        g.yBuf = yBuf;
        g.yMeta = yMeta;
        g._dashY = dashY;
      }
    }
  },
  refreshColor: (view, g) => {
    g.color = parseColor(view.root, g.trace.style.color, g.color);
    g.lineColor = parseColor(view.root, g.trace.style.line_color || g.trace.style.color, g.lineColor || g.color);
    g.grad = view._resolveMarkFill(g.trace.style, g.color);
  },
};

const MESH_MARK = {
  build: (view, g, t, buffer) => view._buildMeshMark(g, t, buffer),
  draw: (view, g) => {
    const [x0, x1] = view._axisRange(g.xAxis);
    const [y0, y1] = view._axisRange(g.yAxis);
    view._drawMesh(g, view._map(g.x0Meta, x0, x1, g.xAxis), view._map(g.y0Meta, y0, y1, g.yAxis));
  },
  refreshColor: (view, g) => {
    if (g.colorMode === 0 && g.trace.color) g.color = parseColor(view.root, g.trace.color.color, g.color);
    const style = g.trace.style || {};
    g.meshStroke = parseColor(view.root, style.stroke || "transparent", [0, 0, 0, 0]);
  },
};

export const MARK_KINDS = {
  histogram: RECT_MARK,
  box: RECT_MARK,
  violin: RECT_MARK,
  errorbar: SEGMENT_MARK,
  stem: SEGMENT_MARK,
  box_whisker: SEGMENT_MARK,
  box_median: SEGMENT_MARK,
  contour: SEGMENT_MARK,
  segments: SEGMENT_MARK,
  triangle_mesh: MESH_MARK,
  ribbon: {
    build: (view, g, t, buffer) => view._buildRibbonMark(g, t, buffer),
    draw: (view, g) => {
      const [x0, x1] = view._axisRange(g.xAxis);
      const [y0, y1] = view._axisRange(g.yAxis);
      view._drawRibbons(
        g,
        view._map(g.x0Meta, x0, x1, g.xAxis),
        view._map(g.y0Meta, y0, y1, g.yAxis),
      );
    },
    // No pointPick: the GPU id pass draws gl.POINTS from the xy slots, which
    // for a ribbon are the target span's y values — garbage ids. Hover works
    // through the CPU containment path (_ribbonHover); selection is absent
    // rather than wrong, per the ribbon geometry contract.
    retainCpu: true,
    refreshColor: (view, g) => {
      if (g.trace.color) g.color = parseColor(view.root, g.trace.color.color, g.color);
      // Both ends of the gradient and the outline are theme-resolved CSS, so
      // all three go stale together on a light/dark flip, not just the source.
      if (g.trace.color_target) {
        g.colorTarget = parseColor(view.root, g.trace.color_target.color, g.color);
      }
      const style = g.trace.style || {};
      if (style.stroke) g.stroke = parseColor(view.root, style.stroke, g.color);
    },
  },
  error_band: AREA_MARK,
  funnel: {
    build: (view, g, t, buffer) => view._buildFunnelMark(g, t, buffer),
    draw: (view, g) => {
      const [x0, x1] = view._axisRange(g.xAxis);
      const [y0, y1] = view._axisRange(g.yAxis);
      view._drawFunnels(g, view._map(g.x0Meta, x0, x1, g.xAxis), view._map(g.y0Meta, y0, y1, g.yAxis));
    },
    // No pointPick: the GPU id pass draws gl.POINTS from the xy slots, which
    // for a funnel hold trailing cross edges — garbage ids. Hover works
    // through the CPU containment path (_funnelHover); box/lasso selection is
    // absent rather than wrong, as for ribbon. stageNav puts the per-stage
    // centers into the keyboard traversal so the funnel reads as an ordered
    // process, stage 0 first.
    stageNav: true,
    retainCpu: true,
    refreshColor: (view, g) => {
      // The palette rows (possibly var(--…)) and the outline are CSS; both
      // re-resolve against the new theme. buffer=null reuses the stashed
      // codes and re-uploads the recolored per-stage RGBA rows.
      view._funnelPaint(g, g.trace, null);
      // A rebuild uploads UNDIMMED rows, so a theme flip while a legend row
      // is hovered dropped that row's emphasis until the next mouse move.
      // Re-apply it against the NEW backdrop.
      const hover = view._legendHover;
      if (hover && hover.cat != null && !hover.off && hover.traces
          && hover.traces.includes(view.gpuTraces.indexOf(g))) {
        view._dimFunnelPaint(g, hover.cat, chartBackdrop(view.root, view.theme.bg));
      }
      const style = g.trace.style || {};
      g.stroke = style.stroke ? parseColor(view.root, style.stroke, [0, 0, 0, 1]) : null;
    },
  },
  hexbin: {
    build: (view, g, t, buffer) => view._buildHexbinMark(g, t, buffer),
    draw: (view, g) => {
      if (g.authoredMarker) return;
      const [x0, x1] = view._axisRange(g.xAxis);
      const [y0, y1] = view._axisRange(g.yAxis);
      view._drawMesh(g, view._map(g.x0Meta, x0, x1, g.xAxis), view._map(g.y0Meta, y0, y1, g.yAxis));
    },
    refreshColor: (view, g) => {
      if (g.colorMode === 0 && g.trace.color) g.color = parseColor(view.root, g.trace.color.color, g.color);
      const style = g.trace.style || {};
      g.meshStroke = parseColor(view.root, style.stroke || "transparent", [0, 0, 0, 0]);
    },
  },
  bar: BAR_MARK,
  column: BAR_MARK,
  heatmap: {
    build: (view, g, t, buffer) => view._buildHeatmapMark(g, t, buffer),
    draw: (view, g) => view._drawHeatmap(g),
  },
  scatter: {
    build: (view, g, t, buffer) => view._buildScatterMark(g, t, buffer),
    draw: (view, g) => {
      const [x0, x1] = view._axisRange(g.xAxis);
      const [y0, y1] = view._axisRange(g.yAxis);
      view._drawPoints(g, view._map(g.xMeta, x0, x1, g.xAxis), view._map(g.yMeta, y0, y1, g.yAxis));
    },
    pointPick: true,
    retainCpu: true,
    refreshColor: (view, g) => {
      if (g.colorMode === 0 && g.trace.color) {
        g.color = parseColor(view.root, g.trace.color.color, g.color);
      }
      view._pointMarkStyle(g, g.trace);
    },
  },
  line: {
    build: (view, g, t, buffer) => view._buildLineMark(g, t, buffer),
    draw: (view, g) => {
      const [x0, x1] = view._axisRange(g.xAxis);
      const [y0, y1] = view._axisRange(g.yAxis);
      view._drawLine(g, view._map(g.xMeta, x0, x1, g.xAxis), view._map(g.yMeta, y0, y1, g.yAxis));
    },
    refreshColor: (view, g) => {
      g.color = parseColor(view.root, g.trace.style.color, g.color);
    },
  },
  area: AREA_MARK,
};

// Registry lookup with the scatter fallback every dispatch site shares.
export function markOf(kind) {
  return MARK_KINDS[kind] || MARK_KINDS.scatter;
}
