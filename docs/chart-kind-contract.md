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
| Rectangles | landed (`candlestick`) | bar, histogram, waterfall, error bars, heatmap cells (reuse the instanced-quad CANDLE program / `_drawCandles` pattern) |
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

## Registry capabilities

Beyond `build`/`draw`, `MARK_KINDS` entries carry capability flags/hooks so no
per-kind knowledge lives in ChartView branches (the smoke's `reg` probe pins
this contract): `pointPick` (participates in the point-geometry GPU pick pass),
`retainCpu` (standalone export keeps CPU x/y copies for kernel-less hover,
§37), `refreshColor(view, g)` (theme-change re-resolution of CSS constant
colors, §36), and `hover(view, g, dataX)` (a CPU nearest-mark readout that
runs *before* the GPU point pick — candlestick/OHLC use it for O/H/L/C tooltips
and to snap the crosshair; a mark without it falls back to GPU point picking).
The registry and `markOf()` are exported (`fastcharts.MARK_KINDS`) — it is the
public extension surface.

Zoom re-decimation for a decimated mark plugs into `interaction.decimate_view`
(kind-dispatched: line = M4, candlestick/OHLC = `ohlc_decimate`) and the client
`tier_update` handler (branch on `upd.kind`). The crosshair is chart-wide (any
kind) and snaps its vertical guide via the `hover` hook when present.

## Extension points not yet generalized (do it when the case lands)

These are still shaped for the marks that exist. Generalize them when a real new
mark needs them — not preemptively (an interface guessed from one example is
usually wrong). Each has an explicit trigger:

- **Picking** (`_renderPick`, `_pickAt`): point-geometry only today
  (`pointPick`). *Trigger: first pickable non-point mark (bar/candle)* — add a
  `pick` step to `MARK_KINDS` and give the mark its own ID-pass geometry.
- **Legend** (`_buildLegend`): keyed on *channel modes* (density / categorical /
  continuous / named-series), not mark kinds — a colored bar inherits swatches
  for free. *Trigger: a mark needing a swatch that isn't channel-shaped.*
- **Decimation** (`interaction.decimate_view`): line-only (`t.kind == "line"`).
  *Trigger: the first other 1D-orderable mark (area, candlestick/OHLC)* — open
  the gate into a per-kind decimator hook.
- **The drill "real marks"** render as points (`lod` calls `_drawPoints`).
  *Trigger: a drilling kind whose drilled marks aren't points* — route through
  `MARK_KINDS` at that call site.
- **Trace shape & autorange**: `Trace(x, y)` is an xy pair and
  `Figure._range()` reads exactly those columns. A multi-column mark (OHLC:
  open/high/low/close; box: distribution stats) adds its extra columns to the
  trace and — critically — must contribute its true extent to autorange
  (candlestick y-range = min(low)..max(high), not close). *Trigger: first
  multi-column mark* — add an optional per-kind range hook next to
  `_emit_<kind>` and an `extra columns` convention on Trace; both additive.
- **Categorical axis**: `x_axis.kind` is `linear | time` only. Bar/box/violin
  need category axes: positions ship as f64 codes (the wire already handles
  that), the spec's axis entry gains `kind: "category"` + a `categories` label
  table, and the client ticks/labels from the table instead of numeric
  formatting. Design this *with bar* (the protocol is versioned; the change is
  additive) — but do not ship bar without it.
- **View-request protocol**: the client enumerates tier needs per message type
  (`view` for decimated lines, `density_view` per density trace) and the
  widget's handler chain mirrors that. The kernel already knows every trace's
  tier — the client doesn't need to enumerate. *Trigger: the first new
  aggregating kind (histogram)* — unify into one viewport message the kernel
  answers per trace, and bump PROTOCOL once, instead of accreting a message
  type per tier.

## Checklist for a new kind

1. `Figure.<K>(...)` builder + `_emit_<K>` (kernel spec/columns, explicit tier).
2. `MARK_KINDS[K] = { build, draw }` (+ shaders if a new primitive).
3. Component wrapper: entry in `components._MARK_APPLIERS` + a `*_chart` fn.
4. Tests: payload shape + tier decision (pytest); a render probe in
   `scripts/render_smoke_nonumpy.py` asserting it lights pixels.
5. If aggregating: an aggregate kernel (native + NumPy-fallback parity) and wire
   it through the `lod` framework rather than a bespoke path.
6. Roadmap: move the kind from planned → implemented.
