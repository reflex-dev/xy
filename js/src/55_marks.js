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
const MARK_KINDS = {
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
  candlestick: {
    build: (view, g, t, buffer) => view._buildCandleMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) => view._drawCandles(g, x0, x1, y0, y1),
    // Rect geometry, not a point — hover is a CPU nearest-x readout (§17),
    // handled by ChartView._hover via the `hover` hook rather than GPU pick.
    hover: (view, g, dataX) => view._candleHoverRow(g, dataX),
    refreshColor: (view, g) => {
      g.candle.up = parseColor(view.root, g.trace.style.up_color, g.candle.up);
      g.candle.down = parseColor(view.root, g.trace.style.down_color, g.candle.down);
    },
  },
  // OHLC bars: same OHLC data + build/hover as candlestick, tick-bar geometry.
  ohlc: {
    build: (view, g, t, buffer) => view._buildCandleMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) => view._drawOHLC(g, x0, x1, y0, y1),
    hover: (view, g, dataX) => view._candleHoverRow(g, dataX),
    refreshColor: (view, g) => {
      g.candle.up = parseColor(view.root, g.trace.style.up_color, g.candle.up);
      g.candle.down = parseColor(view.root, g.trace.style.down_color, g.candle.down);
    },
  },
};

// Registry lookup with the scatter fallback every dispatch site shares.
function markOf(kind) {
  return MARK_KINDS[kind] || MARK_KINDS.scatter;
}
