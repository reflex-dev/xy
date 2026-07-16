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
| Lines | built (`line`) | line, spline, step/stairs, ECDF, error-band outlines |
| Segments | built (`errorbar`/`stem`/`contour`) | error bars, stems, box whiskers, contour isolines |
| Rectangles | built (`histogram`; compact-bar variant for `bar`/`column`) | bar, histogram, box, violin, candlestick/OHLC, waterfall |
| Filled polygons | built (`area`) | area fill, confidence bands, stacked area |
| Grid texture | built (`density` tier, `heatmap`) | heatmap, image, 2D histogram, hexbin, filled contour |

Establish the primitive once; the charts sharing it are mostly wiring.

## The two seams (and the dispatch that ties them)

A chart kind `K` is defined by a kernel emitter and a client renderer, matched
by the string `K` on the wire (`trace.kind`).

### 1. Kernel — `python/xy/`

- **`_payload.py`: `_emit_<K>(self, t, pw, xr, yr, px_width) -> dict`.** Dispatched
  by `_emit_trace` via `getattr(self, f"_emit_{t.kind}")` — no edit to the
  dispatcher. Returns the trace's spec entry and ships its columns through the
  `_PayloadWriter` (`pw.ship` for §4 offset-encoded geometry, `pw.ship_scalar`
  for raw f32 channels/grids, and `pw.ship_u8` for byte-precision values). Set
  `tier` explicitly (`direct` | `decimated` |
  `density`) — every tier decision is recorded, never silent (§28).
- **A builder on the internal `Figure`** (`marks.py`, e.g. `hist(...)`,
  `bar(...)`) that ingests columns
  into the `ColumnStore` and appends a `Trace`. Reuse `_ingest_xy` for the
  equal-length (x,y) contract; a non-xy mark ingests its own columns.
- **Channels** (optional): if the mark has per-mark color/size, reuse
  `channels.ship_channels(trace, sel, ship_scalar, palette)` — the same wire
  shape scatter and heatmap use, so continuous/categorical color and size come
  from one path.

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

### Rectangle-family wire formats

The rectangle family deliberately has two wire shapes:

- **Full rectangles** (`histogram` today, and later irregular cells/candles):
  four edge columns, `x0/x1/y0/y1`. Use this when widths are irregular or both
  axes need independent per-mark edges.
- **Compact bars** (`bar`/`column`): one position column, one endpoint value
  column, an optional baseline column or scalar `value0_const`, and scalar
  `width`. This keeps common bars to two data columns instead of four while
  preserving the same rect fragment shader and legend/color path.

Do not regress bars back to full rectangles for convenience; the 10k-category
benchmark tracks this as part of the core 2D payload budget.

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
colors, §36). The registry and `markOf()` are exported (`xy.MARK_KINDS`)
— it is the public extension surface.

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
- **Decimation** (`interaction.decimate_view`): line and area-like marks use the
  shared M4 path on first payload; errorbar/stem segments reduce to a
  pixel-derived cap at emit time. Contour is NOT pixel-bounded: its segment
  count is bounded only by grid cells × levels, so a dense grid with many
  levels ships proportionally many segments. *Trigger: the first interactive
  view-updated non-line 1D mark
  that needs a different reduction algebra (candlestick/OHLC, for example)* —
  open the gate into a per-kind decimator hook.
- **The drill "real marks"** render as points (`lod` calls `_drawPoints`).
  *Trigger: a drilling kind whose drilled marks aren't points* — route through
  `MARK_KINDS` at that call site.
- **Trace shape & autorange**: `Trace(x, y)` remains the conventional center/value
  pair, while rectangle and segment marks carry explicit `x0/x1/y0/y1` columns.
  `Figure._range_columns()` already includes those geometry extents, so error
  bars, boxes, violins, contours, and other multi-column marks do not autorange
  to their midpoint only. *Trigger: a future mark whose extent is not expressible
  by these columns* — add an optional per-kind range hook next to
  `_emit_<kind>` rather than teaching the render loop about the mark.
- **Categorical axis**: `x_axis.kind` supports category positions for
  bar/column, box/violin, and mixed categorical charts. Category positions ship
  as f64 codes with a shared label table; new categorical marks should reuse
  this path rather than inventing per-chart label rendering.
- **View-request protocol**: the client enumerates tier needs per message type
  (`view` for decimated lines, `density_view` per density trace) and the
  widget's handler chain mirrors that. The kernel already knows every trace's
  tier — the client doesn't need to enumerate. *Trigger: the first new
  view-dependent aggregating kind beyond scatter density* — unify into one
  viewport message the kernel answers per trace, and bump PROTOCOL once, instead
  of accreting a message type per tier.

## Checklist for a new kind

1. Internal `Figure.<K>(...)` builder (`marks.py`) + `_emit_<K>` (kernel
   spec/columns, explicit tier).
2. `MARK_KINDS[K] = { build, draw }` (+ shaders if a new primitive).
3. Public composition surface: a `xy.<K>(...)` mark factory, an entry in
   `components._MARK_APPLIERS`, and a `*_chart` fn.
4. Tests: payload shape + tier decision (pytest); a render probe in
   `scripts/render_smoke_nonumpy.py` asserting it lights pixels.
5. If aggregating: an aggregate kernel (native Rust core) and wire
   it through the `lod` framework rather than a bespoke path.
6. Roadmap and contract docs: record the kind as implemented and note any
   compatibility-depth follow-ups.
