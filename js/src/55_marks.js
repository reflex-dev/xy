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
// docs/chart-kind-contract.md — generalize them when a pickable non-point
// mark actually lands, not preemptively.
// ---------------------------------------------------------------------------

// Capabilities (beyond build/draw) so no per-kind knowledge leaks back into
// ChartView branches:
//   pointPick    — marks are point-shaped and participate in the GPU ID pick
//                  pass (§17). A future rect/candle mark supplies its own pick
//                  step instead (see docs/chart-kind-contract.md).
//   retainCpu    — standalone export keeps CPU f32 copies of x/y so hover can
//                  read approximate values with no kernel attached (§37).
//   refreshColor — re-resolve CSS-expressed constant colors on theme change
//                  (§36 live re-resolution); each kind knows where its
//                  constant color lives in the spec.
const RECT_MARK = {
  build: (view, g, t, buffer) => view._buildRectMark(g, t, buffer),
  draw: (view, g, x0, x1, y0, y1) => {
    const edgePad = g.trace.kind === "histogram"
      ? [0, 0, view._edgePadForValue(0, y0, y1, view.canvas.height), 0]
      : [0, 0, 0, 0];
    view._drawRects(
      g,
      view._map(g.x0Meta, x0, x1),
      view._map(g.x1Meta, x0, x1),
      view._map(g.y0Meta, y0, y1),
      view._map(g.y1Meta, y0, y1),
      edgePad
    );
  },
  refreshColor: (view, g) => {
    if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
  },
};

const BAR_MARK = {
  build: (view, g, t, buffer) => view._buildBarMark(g, t, buffer),
  draw: (view, g, x0, x1, y0, y1) => {
    if (!g.trace.bar) {
      RECT_MARK.draw(view, g, x0, x1, y0, y1);
      return;
    }
    const horizontal = g.orientation === 1;
    const pmap = horizontal ? view._map(g.posMeta, y0, y1) : view._map(g.posMeta, x0, x1);
    const v1map = horizontal ? view._map(g.value1Meta, x0, x1) : view._map(g.value1Meta, y0, y1);
    const v0map = g.value0Mode === 1
      ? (horizontal ? view._map(g.value0Meta, x0, x1) : view._map(g.value0Meta, y0, y1))
      : null;
    const v0Const = g.value0Mode === 0
      ? view._mapConst(g.value0Const, horizontal ? x0 : y0, horizontal ? x1 : y1)
      : null;
    const v0EdgePad = g.value0Mode === 0
      ? view._edgePadForValue(
        g.value0Const,
        horizontal ? x0 : y0,
        horizontal ? x1 : y1,
        horizontal ? view.canvas.width : view.canvas.height
      )
      : 0;
    view._drawBars(g, pmap, v1map, v0map, v0Const, v0EdgePad);
  },
  refreshColor: (view, g) => {
    if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
  },
};

const MARK_KINDS = {
  histogram: RECT_MARK,
  bar: BAR_MARK,
  column: BAR_MARK,
  heatmap: {
    build: (view, g, t, buffer) => view._buildHeatmapMark(g, t, buffer),
    draw: (view, g) => view._drawHeatmap(g),
  },
  scatter: {
    build: (view, g, t, buffer) => view._buildScatterMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) =>
      view._drawPoints(g, view._map(g.xMeta, x0, x1), view._map(g.yMeta, y0, y1)),
    pointPick: true,
    retainCpu: true,
    refreshColor: (view, g) => {
      if (g.colorMode === 0 && g.trace.color) {
        g.color = parseColor(view.root, g.trace.color.color, g.color);
      }
    },
  },
  line: {
    build: (view, g, t, buffer) => view._buildLineMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) =>
      view._drawLine(g, view._map(g.xMeta, x0, x1), view._map(g.yMeta, y0, y1)),
    refreshColor: (view, g) => {
      g.color = parseColor(view.root, g.trace.style.color, g.color);
    },
  },
  area: {
    build: (view, g, t, buffer) => view._buildAreaMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) => {
      const xm = view._map(g.xMeta, x0, x1);
      const ym = view._map(g.yMeta, y0, y1);
      view._drawArea(g, xm, ym, view._map(g.baseMeta, y0, y1));
      if ((g.trace.style.line_width ?? 0) > 0) {
        view._drawLine(
          g,
          xm,
          ym,
          g.lineColor,
          g.trace.style.line_width,
          g.trace.style.line_opacity ?? 1
        );
      }
    },
    refreshColor: (view, g) => {
      g.color = parseColor(view.root, g.trace.style.color, g.color);
      g.lineColor = parseColor(view.root, g.trace.style.color, g.lineColor || g.color);
    },
  },
};

// Registry lookup with the scatter fallback every dispatch site shares.
function markOf(kind) {
  return MARK_KINDS[kind] || MARK_KINDS.scatter;
}
