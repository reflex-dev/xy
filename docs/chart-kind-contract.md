# Chart-kind contract

How to add a 2D chart type. The engine is organized so a new kind reuses the
shared machinery — zoom/pan/box-zoom/modebar, responsive sizing, the f64
canonical store with §16 offset-encoded f32 upload, ticks/axes/legend, the
data-less spec + binary blob transport (§29), and the view-dependent LOD/drill
framework (§5/§28) — and only supplies the parts that are genuinely specific to
the mark. Adding a kind is filling in the blanks below, not editing the render
loop.

Organize by **primitive**, not by chart name: most of a Plotly-scale 2D catalog
reduces to a few GPU primitives on top of the shared infrastructure.

| Primitive | Status | Charts it unlocks |
|---|---|---|
| Points | built (`scatter`) | scatter, bubble |
| Lines | built (`line`) | line, area (fill), spline, ECDF, error bands |
| Rectangles | **next** | bar, histogram, candlestick/OHLC, waterfall, error bars, heatmap cells |
| Filled polygons | planned | area fill, violin, confidence bands |
| Grid texture | built (`density` tier) | heatmap, 2D histogram, hexbin |

Establish the primitive once; the charts sharing it are mostly wiring.

## The two seams (and the dispatch that ties them)

A chart kind `K` is defined by a kernel emitter and a client renderer, matched
by the string `K` on the wire (`trace.kind`).

### 1. Kernel — `python/fastcharts/`

- **`figure.py`: `_emit_<K>(self, t, pw, xr, yr, px_width) -> dict`.** Dispatched
  by `_emit_trace` via `getattr(self, f"_emit_{t.kind}")` — no edit to the
  dispatcher. Returns the trace's spec entry and ships its columns through the
  `_PayloadWriter` (`pw.ship` for §4 offset-encoded geometry, `pw.ship_scalar`
  for raw f32 channels/grids). Set `tier` explicitly (`direct` | `decimated` |
  `density`) — every tier decision is recorded, never silent (§28).
- **A builder on `Figure`** (e.g. `hist(...)`, `bar(...)`) that ingests columns
  into the `ColumnStore` and appends a `Trace`. Reuse `_ingest_xy` for the
  equal-length (x,y) contract; a non-xy mark ingests its own columns.
- **Channels** (optional): if the mark has per-mark color/size, reuse
  `channels.ship_channels(trace, sel, ship_scalar, palette)` — the same wire
  shape scatter uses, so continuous/categorical color and size come for free.

### 2. Client — `js/src/`

- **`55_marks.js`: a `MARK_KINDS[K]` entry** with `build(view, g, trace, buffer)`
  (GPU setup onto the gpu record `g`) and `draw(view, g, x0, x1, y0, y1)` (one
  frame). Reuse `view._buildXY` and `view._map` for xy-shaped marks; a mark with
  its own vertex layout (bars, candles = instanced rects) uploads its own
  buffers and computes its own transform. This is the only place the render loop
  learns about a new kind.
- **Shaders** (if the mark needs a new primitive): add to `40_gl.js`. Fragment
  shaders must be `precision highp` for any uniform shared with the vertex stage
  (a caught precision-mismatch bug). Reuse `POINT`/`LINE` programs where the
  geometry matches.

## What you get for free (do not re-implement)

- **Interaction**: pan, wheel zoom (cursor-anchored), box-zoom, modebar, reset,
  dblclick — all operate on the view rectangle and `_map` uniforms, mark-blind.
- **Responsive sizing**: `width/height:"100%"` + ResizeObserver.
- **Precision**: canonical f64 CPU-side; f32 upload offset-encoded and
  re-centered on deep zoom (§16). Never send f64 through the GPU path.
- **LOD/drill framework** (`lod.py` + `45_lod.js`): the visible-count tier
  decision with hysteresis, drilled-subset versioning (`drill_seq`), window
  encoding, screen-derived grid shaping, entry/exit fades, the density-source
  cache, and eased normalization. An *aggregating* kind supplies its own
  aggregate kernel (density uses `bin_2d`; a 1D histogram supplies 1D binning)
  and reuses this framework around it.
- **Transport**: data-less JSON spec + one binary blob; no JSON numbers (§29).
- **Ticks / axes / time axis / autorange**: keyed on axis kind, not mark kind.

## Extension points not yet generalized (do it when the case lands)

These are still shaped for the marks that exist. Generalize them when a real new
mark needs them — not preemptively (an interface guessed from one example is
usually wrong):

- **Picking** (`_renderPick`, `_pickAt`): point-geometry only today. A pickable
  bar/candle needs its own pick geometry; add a `pick` step to `MARK_KINDS` then.
- **Legend** (`_buildLegend`): handles density / categorical / continuous /
  named-series swatches. A mark needing a different swatch adds a case.
- **Decimation** (`interaction.decimate_view`): line-only (`t.kind == "line"`).
  Any 1D-orderable mark (area, candlestick/OHLC) that decimates opens this gate
  into a per-kind decimator hook.
- **The drill "real marks"** render as points (`lod` calls `_drawPoints`). A
  drilling kind whose drilled marks aren't points routes through its own
  renderer — introduce a kind-dispatched drill-mark draw at that point.

## Checklist for a new kind

1. `Figure.<K>(...)` builder + `_emit_<K>` (kernel spec/columns, explicit tier).
2. `MARK_KINDS[K] = { build, draw }` (+ shaders if a new primitive).
3. Component wrapper: entry in `components._MARK_APPLIERS` + a `*_chart` fn.
4. Tests: payload shape + tier decision (pytest); a render probe in
   `scripts/render_smoke_nonumpy.py` asserting it lights pixels.
5. If aggregating: an aggregate kernel (native + NumPy-fallback parity) and wire
   it through the `lod` framework rather than a bespoke path.
6. Roadmap: move the kind from planned → implemented.
