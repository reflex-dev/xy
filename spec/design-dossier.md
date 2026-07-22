# Building a Faster Charting Engine — Complete Design Dossier

*A single compiled record of the design, the competitive research that validates it,
the performance estimates, and the full audit trail. Python-only binding.*

---

## Thesis in one paragraph

Plotly's cost scales with **how much data you have**; this engine's cost scales with
**how many pixels are on screen**. That inversion is bought by four changes, each of
which removes a different one of Plotly's ceilings: **GPU instanced rendering** (not one
SVG node per point), **typed binary transport** (not JSON parsing), a **native
Rust core in the Python process** (not main-thread compute), and — the real unlock — a
**multi-tier level-of-detail system** that never draws or ships more primitives than the
screen can show. One Rust core runs natively inside the Python kernel doing all heavy
work; a thin JS/WebGL2 client in the browser composes screen-bounded tiles on the GPU
today, with a WASM client remaining a future pure-browser path. The result targets
**100M–1B+ points interactively** at **12–24 bytes/point** (direct) or screen-bounded
memory (aggregated) — versus Plotly's practical ~1M ceiling.

Every claim in this dossier is **mode-scoped and testable** — no universal numbers.

---

## How to read this document

1. **Part 1 — The Design** (§1–§37): the full specification. §1–§14 are the core; §15–§31
   fold in two prior audit rounds; §32–§37 add the Python-only architecture, distribution,
   filtering, theming, and the transfer protocol.
2. **Part 2 — Competitive Research**: how the fastest libraries in the field actually
   work, and where each of the six core bets is validated, corrected, or extended. All
   sourced.
3. **Part 3 — Performance Estimates**: projected standing vs standard Python **and** React
   charting libraries.
4. **Appendix A — Audit Log (round 3)**: the raw adversarial review that produced Part IV.

## Status — resolved vs outstanding

| Audit round | Findings | Disposition |
|---|---|---|
| Round 2 (self) | 15 findings | Resolved in-place → §15–§26 |
| Round 3 (external) | 10 findings | Resolved in-place → §27–§31 |
| Round 3 (deep, Appendix A) | F1–F3 (Critical/Major) | **F1–F2 resolved** → Part IV (§32–§35): distribution, filtering. **F3 specified, not implemented** — the tier decision is still count-only and vertex buffers are unchunked (§5) |
| Round 3 (deep, Appendix A) | **F4–F12** | **Outstanding** — not yet folded into the spec (see below) |
| Round 4 (styling) | F-S1–F-S3 | **Partly resolved** → §36: probe-element color resolution shipped; client-side export parity shipped, kernel-side theme snapshot and indexed series tokens still pending |

**Outstanding work (F4–F12), the honest to-do list:**
- **F4** — per-trace f32 offsets (a single viewport origin can't serve traces at wildly
  different coordinate magnitudes). *Augments §4/§16.*
- **F5** — aggregation algebra for color-by-category / mean / non-count reductions
  (Tier-2 currently assumes a scalar density). *Augments §5.*
- **F6** — per-*view* colormap normalization domain (else zoom flickers brightness).
  *Augments §5.*
- **F7** — streaming into the pyramid: `+=`/`-=` across levels; min/max tiles need
  periodic rebuild under eviction. *Augments §28.*
- **F8** — scope the "logically identical across targets" guarantee to bit-identical
  *aggregate buffers*, pixels diffed per-backend. *Augments §21.*
- **F9** — pyramid storage cost is undercounted for multi-trace / multi-channel / fine
  levels. *Augments §27.*
- **F10** — the "Plotly ~40–100 B/pt × 3 copies" figure is unverified; relabel as an
  estimate pending a heap-snapshot, lead with the measured ~14× (plotly-resampler).
  *Augments §1/§2.*
- **F11** — fuzz the Arrow IPC ingest path for served/multi-user apps. *Augments §29.*
- **F12** — reframe the tile pyramid as *unifying live interaction with the pyramid +
  index*, not a novel invention (datashader's `render_tiles` + XYZ tiles are prior art).
  *Augments §5.*

---
---


# Part 1 — The Design

# High-Performance Charting Engine — Design Plan

**Goal:** A Plotly-compatible charting engine that renders *orders of magnitude* more
data, interactively, using a *fraction* of the memory — while running everywhere
Plotly runs (browser, Python/R/Julia bindings, notebooks, static export).

The whole plan is organized around two hard requirements:

1. **Data scale** — smooth interaction at 10M–1B+ points, not 10k.
2. **Memory** — a small, bounded, predictable footprint; target ≤ ~4–8 bytes per
   point resident, versus Plotly's effective ~40–100+ bytes/point.

Everything below is justified against one of those two.

---

## 1. Why Plotly is slow and memory-hungry (the things we must not repeat)

| Root cause | Effect on memory | Effect on data scale |
|---|---|---|
| **Data embedded in JSON** (`x: [1.0, 2.0, …]`) | Each number is ~15–20 bytes as a JSON string, then an 8-byte boxed JS number after parse | Parse time is linear and huge; blocks main thread |
| **Multiple copies of the data** — user `data`, `gd._fullData`, and `calcdata` are separate arrays | 2–4× duplication of every array | More GC pressure, slower updates |
| **One SVG DOM node per point** (2D default) | Each node is hundreds of bytes of DOM + style | Browser dies at ~10⁴–10⁵ nodes |
| **Calc/layout on the main thread, every update** | — | UI freezes on large data or streaming |
| **No level-of-detail** — draws every point even when 10M map to 800px | Holds all points hot | Wasteful; the screen can't show them anyway |

Our design negates each row directly.

---

## 2. Performance & memory targets (acceptance criteria)

| Dataset | Plotly today | This engine (target) |
|---|---|---|
| 100k point scatter | sluggish pan/zoom (SVG) | 60fps, <10 MB resident |
| 1M point line | often unusable | 60fps via decimation, <20 MB |
| 10M point scatter | OOM / crash | 60fps via GPU aggregation, <100 MB |
| 100M+ / out-of-core | impossible | interactive via viewport tiling, bounded RAM |
| Resident bytes/point | ~40–100+ | **mode-dependent — see below** |
| Streaming append | full re-serialize | O(appended), ring buffer, constant memory |

Bytes/point, honestly, by mode (a bare "4–8" was payload-only arithmetic — f32 x,y is
already 8, before validity bits, color/size/selection channels, indices, LOD cache,
staging, and GPU alignment; the full ledger is the Memory Model, §27):

| Mode | Target (all-in: canonical + derived + GPU + overheads) |
|---|---|
| Direct scatter, x/y only | **≤ 12** bytes/pt (8 payload + masks/indices/staging amortized) |
| Direct scatter, typical (color/size/selection) | **≤ 24** bytes/pt |
| Decimated line (Tier 1) | ≤ 12 bytes/pt canonical + **screen-bounded** derived |
| Aggregated / tiled (Tiers 2–3) | canonical may be out-of-core; **resident memory screen-bounded**, not data-bounded (+~1.33× pyramid on stored aggregates) |
| Streaming ring | **constant**: capacity × per-point cost, regardless of history |

"Screen-bounded" is a claim about *resident* memory in aggregated/tiled modes only —
it is **not** a universal engine property, and benchmarks report each mode separately
so the happy path can't stand in for the whole (§12).

If a milestone doesn't move one of these numbers, it's not in scope for that milestone.

---

## 3. Architecture at a glance

```
┌───────────────────────────────────────────────────────────────┐
│  Language bindings (Python / R / Julia / JS)                    │
│  - build a DATA-LESS spec  {traces, layout}                     │
│  - hand off data as Apache Arrow columns (zero-copy from pandas)│
└───────────────┬───────────────────────────────────────────────┘
                │  spec (small JSON) + typed column buffers (binary)
                ▼
┌───────────────────────────────────────────────────────────────┐
│  CORE  (Rust cdylib, C ABI — runs inside the Python process)    │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Ingest &    │  │ LOD /        │  │ Scene graph (retained) │ │
│  │ column store│→ │ decimation / │→ │ + diff engine          │ │
│  │ (1 copy)    │  │ aggregation  │  │                        │ │
│  └─────────────┘  └──────────────┘  └────────────────────────┘ │
│         loaded via ctypes; NumPy buffers passed by pointer       │
└───────────────┬───────────────────────────────────────────────┘
                │  GPU buffers (uploaded once)   +  draw commands
                ▼
┌───────────────────────────────────────────────────────────────┐
│  RENDER  WebGPU (primary) / WebGL2 (fallback) — one <canvas>    │
│  - instanced draws for marks; density textures for aggregates   │
│  - DOM/SVG only for chrome (axes text, legend, tooltip)         │
└───────────────────────────────────────────────────────────────┘
```

An in-browser WASM core running in a Web Worker with SharedArrayBuffer transport was
the original design and was dropped in favor of the native-in-kernel core (§32); a WASM
client remains a possible future pure-browser path.

The two requirements live primarily in the **data pipeline (§4–§6)**. The renderer
(§7) matters, but memory and scale are won or lost in how we store and reduce data.

---

## 4. The data pipeline — single-copy, columnar, typed (this is the core of the memory story)

**Principle: one physical copy of every value, from ingest to GPU.**

- **Ingest as Apache Arrow — with an honest copy count.** "Zero-copy" is true only
  *within a process*. Polars and Arrow-backed pandas hand columns to the binding with
  zero copies; classic NumPy-backed pandas costs **one** conversion copy at ingest
  (numeric NumPy → Arrow can often alias; object/string dtypes cannot). Crossing a
  process boundary (kernel → browser, server → client) is never zero-copy for anyone —
  the achievable bound is **one binary transfer with no re-encoding**: the compact
  GPU-ready blob written once, moved as binary HTTP/websocket/comm frames (never
  base64/JSON on live paths), landing as
  a JS `ArrayBuffer` used in place. The claim we actually make: **minimum possible
  copies per boundary, and zero *format transformations* end-to-end** — the bytes that
  leave pandas are byte-layout-identical to the bytes the GPU upload reads. Per-path
  copy budgets are specified in the Transport Matrix (§29).
- **Column store is the single source of truth.** A trace's `x`/`y`/`color` are
  *references* (column id + offset + length) into immutable canonical buffers. The
  calc/LOD stages produce *derived* buffers only when they must (e.g. a decimated
  view), never a defensive clone of the raw data. Contrast Plotly's `data` +
  `_fullData` + `calcdata` triplication.
- **Struct-of-Arrays, not Array-of-Structs.** `x[]`, `y[]` as contiguous typed
  arrays — cache-friendly, and each column uploads to the GPU as one vertex buffer
  with no marshalling.
- **f32 on the GPU via offset encoding — not naive f32.** f32 has a 24-bit mantissa;
  a millisecond epoch timestamp (~1.7×10¹²) doesn't fit, so *every time series* would
  be corrupted by a naive "f32 by default" rule. The default mechanism is therefore:
  keep the column's source dtype (i64 timestamps, f64 where given) in the store,
  compute a per-column **offset + scale** at ingest, and upload *relative* f32
  (`(v − offset) × scale`). The offset/scale ride in the view transform, which stays
  f64 on the CPU. This preserves the 4-bytes/point GPU footprint *and* full precision
  for large-magnitude/small-delta domains (time, finance, geo). Deep zoom re-centers
  the offset when the visible range's relative span approaches f32 resolution
  (~1 part in 10⁷) — see §16. Most charts don't need 15 significant digits to fill
  800 pixels, but the digits they do need must be the *right* ones.
- **Dictionary-encode categoricals** (Arrow gives this for free): store small int
  codes + one dictionary, not repeated strings.
- **GPU residency = the CPU copy can be dropped — but WASM makes "dropped" subtle.**
  wasm32 linear memory is capped at **4 GB** and, once grown, **does not shrink back
  to the browser** — `free()` returns pages to the allocator, not the OS. So the rule
  is stronger than "free after upload": **large columns never enter WASM linear memory
  at all.** They live in JS-side `ArrayBuffer`s (which the browser *can* reclaim) or
  in GPU buffers; the WASM core operates on them via views and keeps only metadata,
  derived LOD buffers, and bounded scratch arenas inside linear memory. Linear memory
  is budgeted (fixed arena for scratch, sized by *screen*, not data) so it never
  ratchets up with dataset size. wasm64/memory64 lifts the 4 GB cap where supported
  but doesn't change the strategy — datasets beyond a threshold go through Tier 3
  tiling regardless. On native, columns stay `mmap`'d and the OS pages them.

  **Ownership model (resolving a real contradiction):** an earlier draft said the CPU
  copy "can be dropped after GPU upload" — but Tiers 1–3 *recompute* decimations and
  bins from raw columns on zoom, and picking/export/drill also read them. Data that
  exists only in VRAM can't serve any of that (readback is slow, and WebGL2 readback
  paths are worse). So the default is: **the canonical store is CPU-side (JS
  ArrayBuffers / mmap / server tier), and every GPU buffer is a cache** — droppable,
  rebuildable, byte-budgeted (§6). Dropping the CPU copy is a narrow, *explicit*
  opt-in for static Tier-0 traces, and it visibly downgrades the trace (no re-tier on
  zoom, bin-level hover only, no export from source). Full accounting in the Memory
  Model (§27).

**Memory accounting example — 10M point scatter:**
- Plotly: JSON payload alone is ~200–400 MB of text; post-parse, arrays + boxed
  values + SVG attempt → gigabytes / crash.
- This engine: `x` f32 (40 MB) + `y` f32 (40 MB) = **80 MB**, uploaded once to GPU,
  then the CPU copy is freed → ~0 resident CPU, 80 MB VRAM. And with aggregation
  (§6) the GPU only ever holds a screen-sized density texture (~a few MB).

---

## 5. Data-scale strategy — a multi-tier Level-of-Detail (LOD) system

The key insight: **never push the GPU more primitives than the screen has pixels.**
The engine picks a tier per trace and re-picks on zoom (operating only on the visible
window). Beyond vertex count, real GPUs impose two other ceilings (both documented by
deck.gl in production):

- **Fill-rate:** fragment work = `count × mark_pixel_area × overdraw`. 10M radius-5
  points ≈ 1B fragment invocations/frame; a 500k-point scatter with large or
  overlapping semi-transparent markers is fill-bound well below any vertex ceiling.
- **Allocation:** Chrome caps a single allocation at ~1 GB; deck.gl documents crashes
  between 10M–100M items during buffer creation for exactly this reason.

**What ships today is count-only:** `tier = f(visible_count)`, hysteresis-guarded.
`drill_decision(visible, budget, in_drill, exit_factor)` in `python/xy/lod.py` returns
`visible <= budget * (exit_factor if in_drill else 1.0)`, with
`DRILL_EXIT_FACTOR = 1.15` (`python/xy/config.py`) so a trace that has drilled down to
real points stays drilled until the count clearly exceeds the budget again. The client
mirrors the same rule (`LOD_DIRECT_POINT_BUDGET`, `LOD_DRILL_EXIT_FACTOR` in
`js/src/45_lod.ts`). Mark pixel area and overdraw do **not** enter the decision.

*Pending (F3, not implemented):* folding `mark_pixel_area × estimated_overdraw` into the
tier decision, so a dense large-marker scatter trips Tier 2 aggregation at sub-ceiling
counts; and **chunked vertex buffers** (multi-buffer draws, ~128 MB segments) so the
allocation cliff is structurally unreachable. Both remain the intended design; neither
exists in `js/src/` today.

**Tier 0 — Direct.** Upload raw columns, draw with instancing. Simple, exact. The
budget is channel-dependent: `Trace.use_density()` (`python/xy/_trace.py`) picks
`DIRECT_SOFT_CEILING = 2_000_000` when the trace carries a per-point color or size
channel, and `SCATTER_DENSITY_THRESHOLD = 200_000` otherwise (both in
`python/xy/config.py`). A plain scatter therefore aggregates at 200k — its whole win is
not drawing 10M dots — while a scatter whose per-point color/size aggregation would
destroy stays direct up to 2M. `js/src/45_lod.ts` carries the matching 200k client
budget.

**Tier 1 — Decimated lines (LTTB / min-max per pixel column):** for line/area traces
with more points than horizontal pixels, reduce to ~2–4 points per pixel column
(min+max preserves spikes). Computed incrementally in the worker; recomputed only for
the visible x-range on zoom. Turns 100M points into ~a few thousand drawn vertices
with no visible difference.

**Tier 2 — multiresolution aggregation (datashader-style, but tiled):** for massive
scatter and heatmaps, don't draw points — draw a colormapped **density texture**.

The naive version ("bin all points into a screen-sized texture") is *not* "O(points)
once": the bin grid depends on the viewport, so every pan/zoom would re-bin the whole
dataset. The intended design is a **data-space tile pyramid** — the four bullets below
describe that target, not current behavior; see the shipped subset after them:

- At ingest (or lazily on first Tier-2 entry), build aggregation tiles in *data*
  coordinates at power-of-two zoom levels — count/sum per cell, ~256² cells per tile.
  Building level *k+1* from level *k* is a 4→1 reduction, so the whole pyramid costs
  ~1.33× one full pass and its total size is ~1.33× the finest level you keep.
- Rendering a viewport = **compose the intersecting tiles** of the nearest pyramid
  level into the screen texture and colormap. **Pan is pure tile reuse** (fetch the
  newly exposed edge tiles); **zoom steps to the adjacent level**. Per-frame cost is
  O(visible tiles) — never O(points) after the initial build.
- Only zooming *below* the finest prebuilt level triggers true re-binning — and only
  of the points in the visible window (found via the chunk index, §22/§28), with
  stale-while-revalidate + progressive refinement (§17) covering the rebuild.
- Colormapping (including perceptual/log scaling and dynamic-range normalization)
  happens at *composite* time on the aggregate values, so restyling never re-bins.

*Shipped today (`src/tiles.rs`, `python/xy/interaction.py`):* a **single square count
pyramid**, not tiles. One trace-wide grid over the full data bounds whose finest level
is `PYRAMID_BASE_DIM`² (2048², `python/xy/config.py`), each coarser level an exact 4→1
u64 sum saturating to u32 down to 1². Built lazily on the first density view at
≥ `PYRAMID_MIN_POINTS` (2,000,000). There is no per-tile fetch entry point and no tile
addressing — the C ABI is `xy_pyramid_build` / `_append` / `_count` / `_compose` /
`_free`, and composition happens kernel-side over the whole window, refusing past
`MAX_UPSAMPLE` (2×, `src/tiles.rs`) so below-floor windows fall back to the exact
`range_indices` + `bin_2d` path. Only the `count` plane exists; the per-channel `sum` /
`argmax+purity` planes above are not built. *Pending:* tiling proper (per-tile build,
fetch, and pan-time reuse), so "pan is pure tile reuse" is design, not behavior. See
`spec/design/lod-architecture.md` §4 for the full design and its shipped-status ledger.

So the honest cost model of the tiled design: **O(points) once at build, O(visible tiles) per frame,
O(visible points) on deep zoom past the pyramid floor.** This is also exactly the
structure Tier 3 needs (§28) — Tier 2 and Tier 3 share the tile machinery; Tier 3
just adds not-all-tiles-resident.

*Backend reality check — three implementations of the same tier:*
- **WebGPU:** compute shader + atomic adds into a storage buffer. The clean path.
- **WebGL2 (no compute, no atomics):** render points as 1px primitives with
  **additive blending into a float render target** (`EXT_color_buffer_float` +
  `EXT_float_blend`, near-universal in WebGL2) — each fragment adds 1 to its bin.
  Same output, one extra render pass; count-based aggregations (count, sum, and
  mean via two channels) work; min/max aggregations fall back to the worker.
- **No usable float blending:** bin in the worker (SIMD Rust over columnar data,
  ~50–100M pts/s) and upload the finished density texture. Slower to *rebuild* on
  zoom, identical to render.

The tier's *capability* is universal; only its rebuild latency degrades down the
fallback chain. Progressive refinement (§17) hides most of that.

**Tier 3 — Out-of-core / viewport tiling (> RAM datasets):** store columns as chunked
Arrow (row groups / Parquet-like), and stream only the chunks the current viewport
needs. Pre-aggregate coarse "overview" tiles (the Tier-2 pyramid's upper levels) so a
zoomed-out view reads a small summary, and detail chunks page in on zoom. RAM stays
bounded regardless of total dataset size (the "1B points" case).

*"Chunks intersecting the viewport" requires an index — arbitrary row groups don't
know what they intersect.* Two cases: **(a) ordered/1-D data** (time series — the
overwhelmingly common Tier-3 case): chunk zone maps (§22) give x-min/x-max per chunk,
so viewport→chunks is a binary search over sorted ranges. **(b) unordered 2-D scatter:**
zone maps only bound, they don't localize — points get bucketed into the Tier-2
data-space tile grid at ingest (one spatial-sort/shuffle pass, the priciest part of
Tier-3 ingest and stated as such), after which viewport→tiles is arithmetic. The full
per-trace-kind rules live in the LOD/Tiling Contract (§28).

Tier transitions are automatic and hysteresis-guarded (to avoid thrashing at the
boundary), and every downsampling decision is logged so we never *silently* hide data.

### 5.1 Tuning constants — `python/xy/config.py`

Every tier/decimation threshold lives in one module (§28: no silent decisions). The
table is the complete contents of `python/xy/config.py`; values are the ones shipped
today. "Read by" lists the modules that *consume* the constant — `python/xy/_figure.py`
re-exports several of them as a historic import path and is not listed for those.

| Constant | Value | What it gates | Read by |
| --- | --- | --- | --- |
| `PROTOCOL_VERSION` | `3` | Wire-spec version stamped on every payload; the client refuses a mismatch loudly (§33). | `_payload.py` |
| `DECIMATION_THRESHOLD` | `10_000` | Line/area traces with more points than this ship M4-decimated (Tier 1); at or below, raw columns go over the wire. Also gates re-decimation on the interaction path. | `_payload.py`, `interaction.py` |
| `SCATTER_DENSITY_THRESHOLD` | `200_000` | Tier-0 → Tier-2 count budget for a scatter with **no** per-point channel (`Trace.use_density()`), and the visible-count budget for view-LOD planning and drill decisions. | `_trace.py`, `interaction.py`; mirrored client-side as `LOD_DIRECT_POINT_BUDGET` in `js/src/45_lod.ts` |
| `DIRECT_SOFT_CEILING` | `2_000_000` | Tier-0 → Tier-2 count budget for a scatter that **does** carry a per-point color or size channel; above it density is forced and the channels are warned about, never silently dropped (§5 F5). | `_trace.py`, `marks.py` |
| `DENSITY_GRID` | `(512, 384)` | Default density-grid cell dimensions for the initial spec, before the client requests a viewport-matched size via `density_view`. | `_payload.py` |
| `MAX_SCREEN_DIM` | `4096` | Upper clamp on any browser-supplied pixel dimension, so untrusted widget/comm input cannot inflate decimation buckets or density grids. | `lod.py`, `_native.py` |
| `MAX_CONTOUR_WORK` | `4_000_000` | Ceiling on contour `cells × levels`; a request over it raises instead of allocating an unbounded segment buffer. | `marks.py`, `_native.py` |
| `DRILL_EXIT_FACTOR` | `1.15` | Hysteresis multiplier on the drill boundary: a trace already drilled to real points stays drilled until the visible count exceeds `budget × 1.15`. | `lod.py` (`drill_decision`, `plan_view_lod`), `interaction.py`; mirrored as `LOD_DRILL_EXIT_FACTOR` in `js/src/45_lod.ts` |
| `DENSITY_TARGET_POINTS_PER_CELL` | `16.0` | Target points per cell when sizing an aggregation grid, so a barely-over-budget view does not get a one-point-per-pixel grid that looks like static and re-ships large. | `lod.py` |
| `DENSITY_SAMPLE_TARGET` | `8_192` | Size of the deterministic real-point sample shipped over an aggregated scatter's density texture (hybrid overlay). | `_payload.py`, `interaction.py` |
| `DENSITY_SAMPLE_SEED` | `0` | Seed for that sample; a fixed seed makes the overlay identical across re-ships of the same view. | `_payload.py`, `interaction.py` |
| `DEFAULT_PALETTE` | 10 CVD-safe hex entries | Per-trace default color cycle and the fallback categorical palette when a channel supplies none (§20/§36). | `marks.py`, `_payload.py`, `_svg.py`, `_raster.py` |
| `PYRAMID_MIN_POINTS` | `2_000_000` | Trace size at/above which a Tier-3 tile pyramid is built lazily; smaller traces never pay for one. | `interaction.py` |
| `PYRAMID_BASE_DIM` | `2048` | Edge of the pyramid's base level in cells (`dim²` u32 counts, ~1/3 overhead for the coarser levels); sets resident pyramid bytes. | `interaction.py` |

Nothing in this table folds mark pixel area or overdraw into a tier decision — that is
F3, still pending (above).

---

## 6. Memory-reduction techniques (checklist)

- ✅ Binary Arrow transport — no JSON, no parse bloat, no string numbers.
- ✅ Single physical copy — references through the pipeline, not clones.
- ✅ f64 canonical CPU-side, uploaded as window-centered offset-encoded f32 (§4/§16) —
  *not* "f32 by default", which §4 rejects outright.
- ✅ Struct-of-Arrays typed columns → direct GPU upload.
- ✅ Dictionary encoding for categoricals.
- ✅ GPU buffers are droppable caches, rebuilt from the retained canonical CPU store
  (§27 rule 1); `mmap` on native. Dropping the *canonical* copy after upload is a
  narrow, explicit opt-in for static Tier-0 traces, never the default (§4).
- ✅ Aggregation tiers so hot memory is screen-bounded, not data-bounded.
- ✅ **Ring buffers for streaming** — fixed-capacity circular GPU buffer; appends
  overwrite oldest, constant memory, no re-allocation, no re-serialize.
- ✅ No worker/main-thread data duplication: the core computes in the Python process and
  the client receives screen-bounded buffers over the comm channel (§8/§37). The
  SharedArrayBuffer/transferable-ArrayBuffer scheme belonged to the dropped in-browser
  WASM core (§8).
- ✅ Retained scene graph + buffer diffs — updating a color is a uniform write, not a
  data re-upload.
- ✅ Large columns live *outside* WASM linear memory (JS ArrayBuffers / GPU); linear
  memory holds only metadata + screen-sized scratch arenas (see §4).
- ✅ Arrow **validity bitmaps** carried through the pipeline — nulls cost 1 bit, not a
  sentinel column (see §19).
- ✅ **Explicit memory budgets with eviction.** VRAM is finite and not queryable in
  browsers: the LOD cache (§10) and Tier-3 tiles run under a byte budget with
  LRU-by-zoom-distance eviction, and everything evicted is recomputable from source
  columns. Includes WebGPU device-loss / WebGL context-loss recovery: the scene graph
  + column store are sufficient to rebuild all GPU state, so loss = a reupload, not
  a crash (see §18).

---

## 7. Rendering core

- **WebGPU primary, WebGL2 fallback.** One `<canvas>`, everything is GPU primitives.
- **Instanced draws** for markers/bars/lines — one draw call for millions of marks.
- **Density textures** for aggregated tiers (§5, Tier 2).
- **DOM/SVG only for chrome** — axis tick labels, legend, title, tooltip. Little of it,
  and it stays crisp/accessible/selectable.
- **Retained scene graph**, spec-diff → buffer-diff. Pan/zoom is a view-matrix uniform
  update, touching zero data buffers.
- **GPU picking** for hover/select — render IDs to an offscreen target, read back the
  pixel under the cursor. O(1) regardless of point count.

---

## 8. Compute & threading

- The Rust core runs **natively inside the Python process**, loaded as a C-ABI cdylib
  through `ctypes` (`python/xy/_native.py`; `Cargo.toml` `crate-type = ["cdylib",
  "rlib"]`). It is not compiled to WASM and does not run in a browser thread. Heavy
  work happens off the browser entirely, so the UI thread is never the bottleneck for
  big data.
- Heavy stages (decimation, binning, autorange, KDE, stacking) run in the kernel on the
  columnar buffers; NumPy arrays are passed to the core by pointer, without copying.
- The browser side is a **thin JS/WebGL2 client** on the main thread: it mounts,
  forwards input, uploads the screen-bounded buffers the kernel computes, and draws
  chrome. Results arrive over the comm channel (§37), not over `postMessage`, so
  neither SharedArrayBuffer nor cross-origin isolation (COOP/COEP) is required —
  which is what lets the client run in Jupyter, embedded iframes, and third-party
  contexts that cannot set those headers.
- One Web Worker exists client-side, and it is not the core: `js/src/46_worker.ts`
  re-bins the retained density sample for kernel-less standalone exports (`to_html`),
  off the main thread, booted from a Blob URL. Environments without workers fall back
  to the stretched overview texture.
- *Dropped path, kept for history:* the original design put the Rust core in a Web
  Worker as WASM, with SharedArrayBuffer transport and transferable ArrayBuffers as the
  universal fallback. §32 supersedes it. A WASM client remains a future pure-browser
  option.
- The *same Rust* compiled **native** does headless static export (PNG/SVG/PDF) with no
  browser — faster than Kaleido. **Consistency claim, stated honestly:** *logically*
  identical (same scales, same layout, same LOD decisions — guaranteed by sharing the
  core), *perceptually* identical within a screenshot-diff tolerance — but **not
  byte-identical**: GPU rasterization is not bit-deterministic across drivers, and
  browser text is DOM-rendered (§7) while native text is shaped by the core's own
  font stack. The native **CPU rasterizer is the deterministic reference image** that
  both targets are diffed against in CI (see §21).

---

## 9. Spec & bindings (keep Plotly's reach)

- Declarative `{traces, layout}` spec, **but data-less** — traces reference columns by
  handle; data travels as Arrow beside the spec. Spec stays tiny and diffable.
- Thin bindings per language build the spec + hand off Arrow (zero-copy from pandas).
- A **`plotly`-compatible shim** maps the common Plotly figure API onto our spec so
  existing code/docs port with minimal changes — the migration story is the moat.

---

## 10. Core data structures (sketch)

```rust
// Immutable, single-copy source of truth
struct Column { id: ColId, dtype: DType /*F32,F64,I32,Dict*/, buf: Arc<ArrowBuffer>, len: usize }

struct Trace { kind: TraceKind, x: ColRef, y: ColRef, style: StyleRef, lod: LodState }

// What actually lives on the GPU
struct GpuTrace { vbo: BufferId, count: u32, tier: Tier, view_uniforms: Mat3 }

enum Tier { Direct, DecimatedLine{px_width:u32}, Aggregated{tex:TextureId}, Tiled{loaded:Vec<ChunkId>} }

struct Viewport { x_range:(f64,f64), y_range:(f64,f64), px:(u32,u32) } // drives LOD selection

// LOD cache keyed by (trace, zoom-bucket) so re-zooming reuses work.
// Byte-accounted: this cache is exactly where "bounded memory" would otherwise
// quietly die. Every entry is recomputable from canonical columns, so eviction
// is always safe.
struct LodCache {
    entries: HashMap<(TraceId, ZoomBucket), DerivedBuffer>,
    bytes_used: usize,                  // maintained on insert/evict
    budget: MemoryBudget,               // per-chart cap + share of global cap (§27)
    lru: EvictionQueue,                 // LRU weighted by zoom-distance from viewport
}
```

---

## 11. Milestones

- **Phase 0 — Prove the memory/scale thesis (spike).** Data-less spec + Arrow ingest +
  WebGL2 direct-draw scatter/line (Tier 0). Benchmark memory bytes/point and FPS at
  100k / 1M. *Exit:* beat Plotly's memory by ≥5× at 1M points.
- **Phase 1 — LOD lines + workers.** Move core to Web Worker; add LTTB/min-max
  decimation (Tier 1) + SharedArrayBuffer. *Exit:* 10M-point line at 60fps.
- **Phase 2 — GPU aggregation.** Density-texture scatter/heatmap (Tier 2). *Exit:*
  10M-point scatter at 60fps, screen-bounded VRAM.
- **Phase 3 — WebGPU backend + native export.** Second render backend; native headless
  PNG/SVG. *Exit:* identical output browser vs native; export with no browser dep.
- **Phase 4 — Out-of-core tiling.** Chunked columns + viewport streaming + overview
  tiles (Tier 3). *Exit:* 100M+ / larger-than-RAM at bounded memory.
- **Phase 5 — Breadth + compat.** More trace types; Plotly-compatible API shim;
  `express`-style one-liners. *Exit:* drop-in for the common Plotly figures.

---

## 12. Benchmark harness (built in Phase 0, run every phase)

- **Datasets:** synthetic 100k / 1M / 10M / 100M; a real streaming feed; a categorical-heavy set.
- **Metrics:** resident memory (CPU + VRAM), bytes/point, pan/zoom FPS, time-to-first-paint,
  streaming append latency, static-export time.
- **Baseline:** the same figures in Plotly, side by side, in CI. A regression on any
  metric fails the build. Every silent cap (top-N, decimation ratio) is asserted and logged.

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| WebGPU not universal yet | WebGL2 fallback path from day one |
| Canvas text less crisp than SVG | DOM chrome for all text; native SVG-emit path for small print-quality 2D |
| Ecosystem/trace-type breadth is Plotly's real moat | Plotly-compatible spec + API shim; prioritize the 20% of trace types that are 80% of usage |
| f32 precision in geo/finance | Per-trace f64 opt-in; offset-encoding for large-magnitude small-delta data |
| Decimation hides real features | min-max (not mean) decimation preserves spikes; log every reduction |
| WASM↔JS↔GPU boundary chatter | Batch draw commands; keep the hot loop inside one worker; SAB/transferables |
| SAB unavailable (no COOP/COEP in notebooks/iframes) | Transferable-ArrayBuffer ownership-handoff path is the default design; SAB is an optimization (§8) |
| Timestamps/large magnitudes break f32 | Offset+scale encoding is the default upload path; f64 view transform on CPU (§4, §16) |
| WebGL2 can't do compute-shader binning | Additive-blend float-target binning; worker-side SIMD binning as last resort (§5) |
| Browser caps live GPU contexts (~16 in Chrome); dashboards want 30+ charts | Per-chart context under an LRU governor, budget 12 (§18) |
| VRAM exhaustion / device loss | Byte-budgeted caches with eviction; full GPU state rebuildable from scene graph (§6, §18) |
| Canvas is invisible to screen readers | Structured a11y layer: ARIA summary, keyboard nav, data-table export (§20) |
| WASM bundle bloat vs plotly.js partial bundles | Feature-gated trace modules, size budget in CI (§23) |
| Rebinning cost on every zoom frame breaks 60fps | Stale-while-revalidate + progressive refinement (§17) |

---

## 14. The one-paragraph summary

Store every value **once per boundary**, as **typed columnar Arrow** (offset-encoded
f32 on the GPU, SoA), moved with the minimum copies each boundary permits — zero
in-process, one binary transfer cross-process — and **no JSON or re-encoding anywhere**.
Never draw more primitives than there are pixels: a **multi-tier LOD system** (direct →
decimated → tile-pyramid-aggregated → out-of-core-tiled) keeps *resident* memory
screen-bounded in the aggregated tiers instead of data-bounded, which is what lets it
handle 10M–1B+ points. A **retained scene graph** with buffer-diff updates
and **ring-buffer streaming** keeps memory constant under change. A single **Rust core**
(WASM in-browser, native for export) plus a **data-less Plotly-compatible spec** preserves
Plotly's universal reach. Memory and scale are won in the data pipeline; the GPU renderer
just consumes what the pipeline has already minimized.

---
---

# Part II — Audit addendum

*A hostile review of Part I. Five claims did not survive contact with reality and have
been corrected in place (§4, §5, §6, §8, §13); the sections below add design that was
missing entirely.*

## 15. Audit findings summary

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | "Byte-identical" browser/native output is impossible (GPU float nondeterminism, DOM vs native text) and contradicted §7 | **Critical — false claim** | Reworded to logical + perceptual identity; CPU reference rasterizer as CI oracle (§8, §21) |
| 2 | "f32 by default" corrupts every time series (ms epoch > f32 mantissa) | **Critical — data corruption** | Offset+scale relative encoding is the default upload path (§4); deep-zoom re-centering (§16) |
| 3 | SharedArrayBuffer needs COOP/COEP — unavailable in Jupyter/iframes, i.e. exactly where Plotly-reach matters | **Critical — deployment** | Transferable-ArrayBuffer ownership handoff is the design baseline; SAB is an optimization (§8) |
| 4 | Tier-2 GPU binning assumed compute shaders + atomics; WebGL2 has neither — flagship feature silently absent on fallback | **Critical — feature gap** | Three-implementation ladder: compute / additive-blend float target / worker SIMD (§5) |
| 5 | "Free CPU buffer after upload" is a no-op for browser memory — wasm32 linear memory never shrinks, caps at 4 GB | **Major — memory claim** | Large columns never enter linear memory; screen-sized scratch arenas (§4, §6) |
| 6 | Hover/pick undefined for aggregated tiers; naive pick readback + LOD recompute breaks interaction latency | Major | Interaction latency model, stale-while-revalidate, progressive refinement (§17) |
| 7 | No multi-chart story; browsers cap live GPU contexts (~16 in Chrome), dashboards want 30+ | Major | Per-chart context under an LRU governor, budget 12 (§18) |
| 8 | No null/NaN semantics; NaN in f32 vertex data corrupts primitives | Major | Validity bitmaps end-to-end, gap semantics (§19) |
| 9 | Canvas rendering is an accessibility regression vs Plotly's SVG | Major | Structured a11y layer (§20) |
| 10 | Autorange is an O(n) full scan per update | Moderate | Chunk zone maps make it O(chunks) (§22) |
| 11 | No VRAM budget/eviction; no device-loss recovery | Moderate | Byte-budgeted caches; rebuildable GPU state (§6, §18) |
| 12 | No bundle-size budget — a fat WASM blob forfeits a real Plotly pain point (3.5 MB+) | Moderate | Feature-gated modules + CI size budget (§23) |
| 13 | Compat shim scope unquantified (~3,000 Plotly schema attributes) | Moderate | Generated conformance suite + explicit degradation contract (§24) |
| 14 | Benchmarks measured throughput but not interaction latency; "60fps" undefined | Minor | Latency budgets + p99 framing added (§17, §12) |
| 15 | No extensibility story (Plotly has custom traces) | Minor | Custom-mark API sketch (§24) |

## 16. Numeric precision & deep zoom

The offset-encoding scheme (§4) has one failure mode left: **zooming deeper than f32
relative resolution** (~1 part in 10⁷ of the current offset window — e.g. sub-second
detail inside a decade of millisecond timestamps).

- The viewport (always f64 on CPU) monitors `visible_span / offset_window_span`. When
  it crosses ~10⁻⁵, the core **re-centers**: pick a new offset at the viewport center,
  re-encode *only the visible chunks* (cheap — they're the ones paged in), and swap
  buffers. Hysteresis on the threshold prevents thrash at the boundary.
- **Axis ticks and hover labels never go through f32.** Tick positions, tick label
  values, and hover readouts are computed CPU-side in f64/i64 from source columns —
  the GPU path only ever positions pixels, so display precision is exact even when
  geometry is quantized to sub-pixel f32.
- **Linear axes stay offset-encoded through the vertex transform.** The shader's
  affine view mapping is composed directly onto the encoded values (`xyMap`,
  `js/src/40_gl.ts`); the CPU folds the offset into the affine constants in f64
  (`_map`, `js/src/50_chartview.ts`). Decoding to absolute coordinates in-shader
  first would discard the low bits whenever a deeply zoomed window is far smaller
  than the offset — after which zooming back out could never recover the point
  spread. Only log axes decode before mapping, because log10 is not affine.
  *Augments §4.*
- **Time is i64 end-to-end** (Arrow timestamp columns), with calendar-aware tick
  generation (months are not 30×86400s). Plotly gets this right; matching it is
  table stakes and it must not be routed through any float path.

## 17. Interaction & latency model

Part I said "60fps" without defining what has to happen inside a frame. The budgets:

| Interaction | Budget | Mechanism |
|---|---|---|
| Pan / zoom (view change) | same frame (≤16 ms) | uniform update only — **never** blocks on recompute |
| Hover highlight | ≤2 frames | GPU pick readback is async (`mapAsync`); 1-frame-stale results are imperceptible |
| LOD tier rebuild after zoom | 100–300 ms, non-blocking | **stale-while-revalidate**: keep drawing the old tier, transformed by the new view matrix (slightly wrong resolution, right position), swap when the worker delivers |
| Tier-2 rebin on large data | first result <100 ms | **progressive refinement**: bin a 1-in-k sample first (coarse density appears immediately), refine with remaining data over subsequent frames. Standard datashader-at-interactive trick; also masks the slower WebGL2/worker binning fallbacks |
| Streaming append | ≤1 frame to visible | ring-buffer write + partial `writeBuffer`, no scene rebuild |

**Hover semantics per tier** (the doc previously defined hover only for direct draws):
- *Tier 0/1:* GPU pick → point ID → exact source-row readout (f64/i64, via §16).
- *Tier 2 (aggregated):* the pick target is a **bin**, not a point. Hover shows bin
  summary (count, x/y range, aggregate value). Click-to-drill spawns a worker query
  that returns the top-k underlying rows from the column store — honest about
  aggregation instead of pretending a fake "nearest point."
- *Tier 3:* same as Tier 2, but the drill query may touch unpaged chunks →
  it's async with a loading affordance.

## 18. Many charts per page (the dashboard problem)

Plotly's real-world habitat is dashboards with 10–50 figures. Browsers cap live
WebGL contexts per page (~16 in Chrome) and LRU-evict the oldest on overflow, which
permanently blanks the earliest charts of a big dashboard.

**Shipped: one context per chart, governed.** `XY_CONTEXT_GOVERNOR`
(`js/src/50_chartview.ts`) keeps the page inside a budget — default **12**, overridable
via `window.XY_CONTEXT_BUDGET` — leaving headroom under Chrome's cap for host-page GL.
When a view is about to acquire a context at budget, the least-recently-visible
*off-screen* view releases its own via `WEBGL_lose_context` and re-acquires when
scrolled back into view; an over-budget panel keeps showing its last frame as a static
image. Under the budget nothing is ever released. Every decision is observable:
`data-xy-ctx` on the canvas reads `live` | `released` | `lost`. See
`spec/process/production-readiness.md` §"WebGL context cap" for the claim limits.
`destroy()` releases the context via `WEBGL_lose_context` too, so a view teardown —
including the destroy+rebuild a full-payload republish performs — frees its slot
immediately rather than leaving a destroyed context to linger until GC and count
against the browser cap.

**The budget is shared across same-origin frames.** Chrome's cap is *process-wide* —
one budget for every iframe in the tab — but a per-document governor sees only its own
charts. A page that renders each chart in its own iframe (docs sites, SaaS dashboards,
and the `examples/fastapi` gallery, which needs iframes to host each standalone
`to_html` document) would otherwise defeat the governor entirely: no frame ever
releases (each is under budget alone), the browser LRU-evicts live charts, and the
evicted charts fight to recover and re-evict — a scroll-driven "Too many active WebGL
contexts" storm. The governor closes this by sharing one budget over a
`BroadcastChannel("xy-webgl-context-governor")`: each frame announces its live-context
count (`{t:"live", id, n}`, with `hello`/`bye` for join/leave), and any frame over the
shared budget sheds its own *off-screen* views — never a visible one, so a sibling
frame loading cannot blank a chart the user is looking at. `IntersectionObserver`
already reports an off-screen iframe's chart as not-intersecting (it clips to the
top-level viewport), so the visibility signal is correct across the frame boundary; the
budget accounting was the only gap.

Two subtleties the implementation must get right. **(1) Restore ordering.** A governed
release is `WEBGL_lose_context.loseContext()`; re-acquire is `restoreContext()`. Chromium
*silently drops* a `restoreContext()` issued before that context's `webglcontextlost`
event has dispatched (or synchronously inside the dispatch), stranding the canvas lost
forever — and a chart scrolled back into view in the same task it was shed hits exactly
that window. Recovery therefore defers until the loss event lands (`_ctxLostPending`)
and retries on a fresh task; a released chart that never re-acquired on scroll-in was the
first symptom. **(2) Incremental shedding.** Frames over budget release *one* off-screen
view per event-loop turn, not the whole computed excess: several frames observing the
same over-budget snapshot would each drop the full deficit and collectively over-release,
so each sheds one, announces, and re-evaluates against the fresher count — converging on
the budget instead of overshooting it (still safe either way; an off-screen over-release
just revives on demand).

Coordination is otherwise best-effort and self-healing: `BroadcastChannel` delivery is
asynchronous, so a burst of charts constructed in one synchronous tick across many frames
can briefly overshoot before the first `live` messages arrive (a handful of transient
evictions that recover); a frame frozen into the back/forward cache says `bye` on
`pagehide` and re-announces on `pageshow` (`persisted`) so peers neither count a frozen
frame nor omit a restored one; and a frame that crashes without a `bye` only lowers the
effective budget (a few extra off-screen releases, revived on demand) — it never blanks a
visible chart or evicts. Cross-origin and `sandbox`-without-`allow-same-origin` frames
(e.g. the notebook `_repr_html_` frame) get an isolated channel scope and fall back to
per-document behavior.

**Device/context loss is a first-class event:** all GPU state is derived state, rebuilt
from the scene graph + column store on a new context. The visible cost is one reupload
flicker, never lost data. The governor depends on this — a governed release is a
deliberate context loss put through the same restore path.

*Unimplemented design option — shared-context compositing:*

- **One renderer, one GPU context per page.** Each chart becomes a *client* of the
  shared renderer: it owns a scene subgraph and a target rectangle.
- Two compositing modes, chosen per environment: (a) a single full-page canvas behind
  the DOM, charts drawn into scissored viewports — cheapest, works everywhere; or
  (b) per-chart canvases fed by `transferControlToOffscreen` /
  `drawImage`-from-shared-framebuffer where layout demands real DOM interleaving.
- Shared context would also mean **shared caches**: two charts of the same DataFrame
  reference the same columns and the same GPU buffers — a dashboard of 20 views of
  one 10M-row table holds the data **once**, which is a memory win Plotly cannot
  express at all.

## 19. Nulls, NaN, and gaps

- Arrow **validity bitmaps** are the single source of null truth, carried through
  every stage (1 bit/value — no 8-byte NaN sentinel columns).
- NaN/invalid values **never reach vertex buffers** — an f32 NaN silently kills the
  primitives that share it (GL behavior is undefined-but-usually-invisible geometry,
  and it differs by driver — a determinism hole as well as a correctness one).
- Semantics preserved from Plotly: a null inside a line trace = **gap** (line break),
  implemented by splitting the draw into segments at ingest (segment index list, not
  per-frame branching). Aggregations skip nulls and expose `count_valid` vs `count`.
- Decimation (Tier 1) treats gap boundaries as hard edges — min/max buckets never
  span a gap, or decimation would invent data across a hole.

## 20. Accessibility (a regression Plotly would win otherwise)

SVG charts are imperfect but *inspectable*; a canvas is a black rectangle to assistive
tech. Ship from Phase 1, not as a retrofit:

- A parallel **semantic layer** in the DOM: chart role + generated text summary
  (trace count, ranges, extremes — derivable from the zone maps of §22 for free),
  `aria-live` region for hover readouts.
- **Keyboard navigation**: arrow keys walk points (direct tiers) or bins (aggregated
  tiers), reusing the exact hover pipeline of §17 — one code path, two input devices.
- **"View as table"** escape hatch: the column store already has the data; render the
  visible window as an HTML table on demand.
- High-contrast + `prefers-reduced-motion` respected in the theme system; colormaps
  ship with CVD-safe defaults.

## 21. Visual testing, determinism, and text

The correctness oracle for a renderer is an image, and images from GPUs are
driver-dependent. The testing architecture:

- The native build includes a **software (CPU) rasterizer path** — slow, simple,
  bit-deterministic. It is the **reference implementation**. Every backend (WebGPU,
  WebGL2, native GPU) is screenshot-diffed against it with a perceptual metric
  (per-channel tolerance + small SSIM window), not byte equality.
- **Text is the biggest determinism variable**, so it's pinned: the core bundles its
  own font shaping/rasterization (embedded default font; user fonts loaded explicitly)
  for native output *and* for the CPU reference. In the browser, chrome text is DOM
  (crisp, selectable, accessible — §7), and the conformance suite compares *layout
  boxes* (positions/extents from the shared layout engine) rather than glyph pixels
  across that boundary. Same layout, per-target rasterization.
- **LOD decisions are part of the tested contract**: given (data, viewport, tier),
  the chosen tier and the decimated/binned output are deterministic and asserted —
  so "it looked different" can always be bisected to *layout*, *LOD*, or *raster*.
- CI matrix: reference images from CPU rasterizer; per-backend perceptual diffs;
  the §12 perf harness gains **interaction-latency** metrics (input-to-photon for
  pan, hover, tier-swap; p50/p99 frame time — "60fps" now means *p99 ≤ 16.7 ms
  during continuous pan*, not an average).

## 22. Chunk statistics (zone maps) — cheap answers to expensive questions

At ingest, every column chunk (~64k values) gets a one-pass statistics block:
`min, max, count, null_count, sum, sum_sq` (+ dictionary cardinality for categoricals).
Cost: one streaming pass you were already paying at f32-encode time. Buys:

- **Autorange in O(chunks)** instead of O(n) — the §1 complaint about full-scan
  autorange, actually closed.
- **Tier-3 pruning**: viewport queries skip chunks whose min/max don't intersect —
  the same trick as Parquet row-group pruning, applied to pan/zoom.
- **Instant summaries** for the a11y layer (§20) and for aggregated-hover drill
  previews (§17) without touching raw data.
- Deep zoom re-centering (§16) picks its new offset from zone maps, not a scan.

## 23. Deployment matrix & bundle budget

Where it must run, and what each environment denies us:

| Environment | Denied | Design answer |
|---|---|---|
| Jupyter / VS Code notebooks | COOP/COEP (no SAB), sometimes strict CSP | transferables path (§8); WASM served same-origin by the extension; no `eval` anywhere |
| Embedded iframes (docs, dashboards-in-SaaS) | COOP/COEP, GPU context quota shared with host | transferables; the context governor shares one budget across same-origin iframes over a `BroadcastChannel` so a chart-per-iframe page stays under the process-wide cap (§18) |
| Strict-CSP enterprise pages | `wasm-unsafe-eval` may be blocked | documented CSP requirements; **pure-JS fallback build** (same core transpiled level: Tier 0/1 only, capped point counts) so a chart *renders* rather than white-boxes |
| Old browsers / no WebGL2 | GPU entirely | same pure-JS + 2D-canvas fallback, capped; loudly reported via the §5 no-silent-caps rule |
| Server / CI (native) | no display | headless native path (§8) |

**Bundle size.** The shipped client is a single minified JS bundle —
`python/xy/static/index.js`, ~277 KB minified / ~76 KB gzipped (vite/oxc; built from
the TypeScript sources in `js/src`) — with no WASM payload and no lazily-loaded trace
modules. The one size gate CI enforces is on the **wheel**: `.github/workflows/ci.yml`
asserts the built wheel is ≤ 15 MB (§33). CI also verifies the committed JS bundles are
*fresh* (`node js/build.mjs` reproduces them byte-for-byte), but it does not measure
their bytes.

*Pending:* a gzipped-size budget on the client bundle, failing the build exactly like a
perf regression (§12), plus per-trace-family lazy feature modules (Plotly's
partial-bundle pain). Neither exists today.

## 24. Extensibility & the compatibility contract

- **Compat is a measured number.** Plotly's `plot-schema.json` (~3,000 attributes) is
  ingested to *generate* the conformance suite: each attribute is classified
  `supported | mapped-with-difference | unsupported`, the shim **warns loudly** on
  unsupported attributes (never silently drops), and the docs publish the coverage
  table per release. "Drop-in for the common 80%" becomes checkable, not vibes.
- **Custom traces without forking:** a registered *mark plugin* provides
  (a) a calc function over columns → columns (runs in the worker, gets zone maps),
  (b) either a composition of built-in GPU primitives (instanced marks, density
  textures, line strips) *or* a WGSL/GLSL snippet pair for exotic marks, and
  (c) hover/a11y descriptors so §17/§20 work uncalled-for. Plotly's moat is breadth;
  a plugin API is how breadth arrives without the core team writing all 40 traces.

## 25. Milestone amendments (audit-driven)

- **Phase 0** additionally proves: offset-encoding precision on ms-timestamp data
  (test: 1-second span inside a 10-year series), and the transferables-only path in
  a real Jupyter notebook. *Both are thesis risks, so they move to the front.*
- **Phase 1** ships the a11y semantic layer + keyboard nav (§20) and zone maps (§22)
  — both are near-free at ingest time and brutal to retrofit.
- **Phase 2** ships all **three** Tier-2 implementations (§5) and progressive
  refinement (§17), not just the WebGPU one — the fallback ladder *is* the feature.
- **Phase 3** adds the CPU reference rasterizer + perceptual-diff CI (§21) *before*
  the second backend lands, so WebGPU-vs-WebGL2 divergence is caught from day one.
- **Phase 4** adds shared-context dashboard compositing (§18) — tiling and
  multi-chart stress the same VRAM budget and should be tuned together.
- **Phase 5** adds the generated conformance suite + coverage table (§24).

## 26. Summary of Part II in one paragraph

The audit's theme: Part I was right about *where the wins live* (data pipeline, LOD,
GPU) but optimistic about *the floor it runs on*. Browsers deny you shared memory in
notebooks, atomics in WebGL2, shrinkable WASM memory, more than a dozen GPU contexts,
and bit-determinism everywhere — and f32 quietly destroys timestamps. Each denial now
has a designed fallback that preserves the capability and degrades only latency, and
each former hand-wave (hover-on-aggregates, nulls, a11y, text, bundle size, compat
scope) is now a contract with a test attached. The plan's claims are weaker in wording
and much stronger in survivability.

---
---

# Part III — Second audit round (external review)

*An external review confirmed four Part-II fixes (offset encoding, SAB fallback,
byte-identical retraction, cache eviction) and surfaced six further findings, all
accepted: the zero-copy overclaim, payload-only memory targets, the GPU-residency ↔
LOD-recompute contradiction, the false "O(points) once" aggregation cost, the missing
Tier-3 index, and the unscoped compat surface. Those are corrected in place
(§2, §4, §5, §10, §14). The reviewer's verdict — "replace universal claims with
precise modes where they are actually true" — is the theme of this part. It adds the
three sections the review demanded before implementation.*

## 27. Memory Model — every byte class, who owns it, when it dies

The five classes of memory, per chart:

| Class | Lives in | Sized by | Freed when |
|---|---|---|---|
| **Canonical columns** | JS ArrayBuffers / mmap (native) / server (Tier 3) — *never* WASM linear memory | data | trace removed (or explicitly demoted, below) |
| **Derived buffers** (decimations, pyramid tiles, segment indices) | worker-side buffers + LodCache | screen (per entry) × cache budget | LRU-evicted under byte budget; always recomputable |
| **Staging** (encode/upload scratch) | WASM arena + mapped GPU staging rings | screen, fixed | reused every frame — never grows with data |
| **GPU buffers/textures** | VRAM | visible working set | evicted under VRAM budget; rebuilt from canonical + derived on demand or device-loss |
| **Overheads** | everywhere | — | *counted, not ignored*: validity bitmaps (1 bit/val), dictionaries, per-buffer GPU alignment padding (256 B granularity), double-buffering during in-flight uploads |

Rules that make the mode targets in §2 real:

1. **GPU is a cache, CPU/server is the truth.** Every VRAM object has a rebuild
   recipe (column refs + transform). Nothing user-provided is *only* in VRAM.
2. **Budgets are explicit and hierarchical:** global engine budget → per-chart share
   → per-class caps (LodCache, tile residency, VRAM estimate). VRAM is unqueryable in
   browsers, so the VRAM budget is a conservative self-accounting of our own
   allocations with allocation-failure backoff (drop to a coarser tier, evict, retry).
3. **Upload overlap is bounded:** staging rings mean at most one screen-sized slice
   of data is duplicated CPU+GPU at any instant — not the whole column.
4. **Demotion is explicit:** the "drop canonical, keep GPU" mode (§4) is a per-trace
   API call that returns the freed bytes and records the trace as `degraded` —
   visible in the debug HUD and in `chart.memory_report()`, which itemizes all five
   classes per trace. If a memory number isn't in the report, it isn't real.

## 28. LOD / Tiling Contract — exact rules per trace kind

For each kind: *canonical requirement → tier ladder → what hover/select means → what
recomputes on zoom.*

| Trace kind | Canonical requirement | Tier ladder | Hover/select | On zoom |
|---|---|---|---|---|
| **Line / area / time series** | x sorted (or engine sorts once at ingest, stated) | direct → min-max per-px-column decimation → zone-map-pruned chunk streaming | exact point (binary search on x in canonical) at every tier | recompute decimation for visible x-range only; zone maps prune chunks |
| **Scatter** | none for Tiers 0–1; spatial bucketing pass at ingest for Tiers 2–3 | direct instanced → *no Tier 1 (decimating unordered points misleads)* → density pyramid → out-of-core tiles | Tier 0: GPU pick, exact row. Tiers 2–3: bin summary + async drill to top-k rows | pan = tile reuse; zoom = adjacent pyramid level; below pyramid floor = re-bin visible via tile index |
| **Heatmap / image** | gridded input | direct texture → mip pyramid (same machinery, degenerate case) | cell value (exact, from canonical grid) | mip level selection; nothing recomputes |
| **Bar / histogram** | histogram: raw column; bar: categories | bars are visually bounded (≤ ~10⁴ on screen) → direct; histogram re-bins from canonical on range change (cheap: 1-D, visible range only, zone-map-pruned) | exact bar/bin | 1-D re-bin, worker, stale-while-revalidate |
| **Streaming (any kind)** | ring capacity declared up front | ring buffer + incremental decimation (Tier-1 buckets updated, not rebuilt); pyramid tiles updated incrementally for touched cells | same as base kind, within retained window | append is O(appended); eviction from ring updates affected buckets only |
| **Box / violin / stat traces** | raw column | stats computed in worker from canonical (streaming algorithms; KDE on a bounded grid) — drawn geometry is tiny | stat readout (exact) | recompute stats for visible subset if axis-linked |

Contract-wide invariants: every tier transition is hysteresis-guarded and logged
(no silent quality change); every aggregated visual states its aggregation in the
hover UI; every derived artifact is reproducible from (canonical, viewport, params) —
which is what makes both the §21 determinism tests and the §27 eviction rules valid.

## 29. Transport Matrix — copies, format, and fallback per environment

The unit being counted: **physical copies of the data payload after it leaves the
user's data structure**, and whether any step re-encodes.

| Path | Transport | Copies (min/typical) | Re-encode? | Fallback / notes |
|---|---|---|---|---|
| **Pure JS app, same page** | typed arrays → transferable to worker | **0** / 0 (transfer = move) | none | SAB where isolated (§8) |
| **Python (Polars / Arrow-pandas), native render** | in-process Arrow | **0** / 0 | none | — |
| **Python (NumPy-pandas), native render** | NumPy → Arrow | **0–1** / 1 (numeric can alias; strings copy) | dictionary-encode strings once | conversion cost reported at ingest |
| **Jupyter kernel → browser** | xy's GPU-ready column blob over **binary** anywidget comm frames | **2** / 3 (payload assembly; socket transit; JS ArrayBuffer landing) | **never** — the compact f32/u8 blob lands as typed views; base64/JSON is forbidden on the live path | old frontends without binary comms: explicit unsupported/error rather than silently changing the performance contract |
| **Server app (Dash-style / Reflex)** | versioned `XYBF` frame over binary HTTP/WebSocket; strict JSON metadata + aligned raw buffers | 1–2 / 2–3 depending on server scatter/gather support; JS decode returns spans into `Response.arrayBuffer()` | never | control requests stay small JSON; SSE carries invalidations only; HTTP range requests into Parquet/Arrow files remain a Tier-3 option |
| **Static HTML export (interactive)** | xy blob base64-embedded in the one-file artifact | 1 decode + stated 33% text expansion | base64, because HTML is a text container | size warning above threshold; offer aggregate-only embed (ship pyramid, not points) |
| **Native static export** | in-process | 0 | none | — |

Design consequences: (a) the numerical wire payload **is** the browser upload format —
offset f32/u8 columns with no per-value transformation, while `XYBF` only supplies a
bounded/versioned envelope; (b) the copies that do happen are `memcpy`-shaped, never
number-parse-shaped; (c) every binding reports its actual copy count at ingest in debug
mode, so "zero-copy" regressions are observable rather than folklore; (d) the Jupyter
live path still has no text encoding of numbers, DOM payload, or main-thread data parse.

## 30. Compatibility subset — v1 is a list, not an aspiration

Full Plotly semantics (~40 trace types × transforms × axis quirks × hover rules) is a
multi-year tail. The shim (§24) ships against an explicit, benchmarked v1 surface —
chosen to cover the high-volume traces where this engine's advantage exists, because
compat effort on a 200-point pie chart buys nothing:

- **Traces:** `scatter`/`scattergl` (markers, lines, both; `fill` for area),
  `bar`, `histogram`, `heatmap`, `box`, `candlestick`/`ohlc`.
- **Layout:** cartesian axes (linear/log/date/category), 2-D subplot grids +
  shared/linked axes, legend (toggle behavior included), title/margins/annotations
  (text + arrow only).
- **Interaction:** default hover (`closest`/`x` modes), zoom/pan/box-select/lasso,
  `Plotly.react`-equivalent diff update, relayout/restyle events.
- **Explicitly out of v1** (warn, don't silently drop — §24): 3-D, geo/mapbox,
  ternary/polar/carpet, sankey/sunburst/treemap, animation frames, legacy
  `transforms`, custom `hovertemplate` beyond basic field substitution.

Everything in the v1 list runs in the conformance suite from Phase 5 §25, and — the
actual point — **each is benchmarked at 100×–1000× Plotly's comfortable data volume.**
The subset is the moat *plus* the differentiator; breadth beyond it arrives via the
plugin API (§24) and demand, not via a compat death-march.

## 31. Revised one-paragraph summary (supersedes §14 where they differ)

The engine's claims are now **mode-scoped**: zero-copy *in process*, one binary
never-re-encoded transfer *across* processes (§29); 12–24 bytes/point in direct modes
and screen-bounded *resident* memory in aggregated/tiled modes (§2, §27); aggregation
that costs O(points) once, O(visible tiles) per frame, O(visible points) only past the
pyramid floor (§5); a CPU/server canonical store with the GPU strictly as a
byte-budgeted cache (§27); per-trace-kind LOD rules with defined hover semantics at
every tier (§28); and a named v1 compatibility surface (§30). Nothing universal, and
therefore nothing that only survives on the happy path — every number has a mode, a
budget, and a test.

---
---

# Part IV — Third audit round: the two missing workstreams

*Audit round 3 (post-research, post-Python-only decision) found that the plan's core
thesis survives but two Critical findings are missing **workstreams**, not tweaks:
distribution (F1) and filtering (F2). A third Major finding (F3 — real GPU ceilings)
is corrected in place in §5. This part adds the two sections and records the
scope decision that reshapes them.*

## 32. Python-only: the architecture consequence

The binding surface is now **Python only** (R/Julia/JS bindings dropped). This is not
just less code — it relocates the heavy tiers:

- **The native Rust core runs inside the Python process**, ingesting zero-copy from
  Polars/Arrow-backed pandas. Decimation (Tier 1), pyramid builds (Tier 2), Tier-3
  paging, and the filter index (§34) all run **natively, in-process, at full speed** —
  SIMD, real threads, mmap, no WASM caps, no 4 GB ceiling.
- **The browser side shrinks to a render client**: a thin WASM/JS module that receives
  screen-bounded aggregates/decimations/tiles over the comm channel, composes them on
  the GPU, and handles local pan/zoom against its resident tile cache. It re-requests
  from the kernel only when navigation crosses the pyramid floor or a filter changes.
- The **in-browser WASM core** (full pipeline client-side) remains the path for pure
  static-HTML export and server-app deployments where the data already lives
  client-side — but it is no longer the primary path. The primary path is
  **native-compute-where-the-data-lives → ship pixels-worth → thin GPU client**, the
  same shape the research validated in datashader/vaex, except pan/zoom stays local
  instead of round-tripping (this is exactly the VegaFusion DAG-partition idea: heavy
  nodes native, leaf render nodes in the browser).

## 33. Distribution — shipping the bits is a first-class workstream (F1)

**For a Python-only product, `pip install` is the product's front door, and it must
deliver three separately-hard artifacts.** Plotly.py's real-world engineering
complexity lives almost entirely here, not in rendering. Miss any piece and the user
hits a source build requiring a Rust toolchain — an instant adoption cliff.

1. **The native core as prebuilt wheels.** Built as a Rust **`cdylib` with a
   plain C ABI** and a focused PNG-encoding dependency, compiled by the Hatchling build hook and loaded
   from Python with `ctypes`. There is no CPython extension ABI at all, so one
   `py3-none-<platform>` wheel covers every supported Python version on that platform
   without PyO3 or `abi3`. Wheel matrix in CI, release-blocking: manylinux
   (x86_64 + aarch64), macOS (arm64 + x86_64), Windows x86_64. A missing native wheel
   is a release failure, not an end-user surprise.
2. **The JS/WebGL2 render client as bundled static assets** inside the same wheel —
   versioned, no CDN dependency (notebooks are often airgapped; §23's CSP rules
   apply). A WASM client is a future pure-browser/export path, not the current shipped
   client.
3. **The notebook integration via `anywidget`** — the current standard: one widget
   implementation works across Jupyter, JupyterLab, VS Code, Colab, and Marimo, and
   gives us the binary comm channel (§29's Jupyter row) without maintaining N
   frontend extensions. Server frameworks (Reflex/Dash-style) mount the same client
   as a component.

**Contracts that keep it honest:**
- **Comm-protocol versioning.** The native core and JS client ship together but can
  drift (cached notebook outputs, pinned server assets). The first-paint spec carries
  a protocol version; mismatch fails **loudly with an upgrade hint**, never silently
  renders wrong. Requests and replies carry no version of their own — the handshake
  happens once, at first paint, before any request is possible
  (`spec/design/wire-protocol.md` §7).
- **No-wheel behavior is defined:** the native Rust core is required and there is no
  pure-Python fallback. A source install compiles the core (Rust toolchain required);
  if the core cannot be loaded — an unsupported platform with no wheel and no local
  build — importing the compute layer raises a clear, actionable ImportError naming
  the supported platforms, never a silent degrade. Published platform wheels require
  the native core and fail the build if it is absent.
- **Install-size budget** joins the §23 bundle budget: wheel ≤ ~15 MB target
  (native core + JS client + assets), CI-enforced like every other number.
- **Import-time budget**: `import xy` does no heavy work (< 200 ms); NumPy and
  the native core initialize lazily when a chart-building API is first imported/used.

## 34. Filtering, selection & linked views — the pyramid alone cannot answer them (F2)

**The gap:** the Tier-2/3 pyramid holds *unfiltered* aggregates. `df[df.region=="US"]`,
a box-select driving a cross-filtered second chart, a legend toggle excluding a
category — all of these make the precomputed counts **wrong**, and §28 had no filter
path. The research confirmed this is why datashader deliberately re-aggregates every
interaction: a static pyramid is stale under any dynamic predicate. Filtering is not
an edge case in analytics — it is the main event, so it gets its own three-tier model,
mirroring the LOD ladder:

**Filter Tier A — indexed range predicates (cheap, instant).** Range filters on
indexed/zone-mapped columns (§22) — time windows, axis-linked ranges, numeric
between — resolve by **tile pruning and bin clipping**: zone maps identify chunks
wholly in/out (no recompute), and only boundary tiles re-bin. Cost O(boundary), the
common case for pan/zoom-linked filtering.

**Filter Tier B — arbitrary predicates (fast re-bin of the visible window).** For
predicates the index can't serve (string contains, computed expressions,
multi-column conditions): **re-bin only the visible window** in the native core —
SIMD binning at ~50–100M pts/s (§5's worker fallback numbers), zone-map-pruned to
the viewport, under stale-while-revalidate + progressive refinement (§17). This is
datashader's model, minus its two taxes: no full-dataset scan (visible window only)
and no per-frame network round-trip (pan/zoom still composes the filtered tiles
locally; only the *filter change* triggers recompute).

**Filter Tier C — linked brushing across views (the Falcon/Mosaic index).** For
cross-filtering dashboards — the highest-value technique from the research: build a
**summed-area (cumulative-sum) index keyed on the active view's dimensions** at
pixel-level bin resolution. Any brush range then resolves per passive view as a
**difference of cumulative sums: O(1) per bin, O(bins) per view, independent of row
count** — Falcon sustains 50 fps across 5 passive views from thousands to billions of
rows on exactly this structure. The index is built in the native core (one pass over
the filtered base, zone-map-accelerated), sized ∝ bins not rows (screen-bounded, §27
budget), rebuilt when the *active view* changes (Falcon's documented trade), and
prefetched on idle for the likely-next active view (Falcon's documented trick).

**Composition rules:** a session's filter state = (range predicates → Tier A) ∧
(arbitrary predicates → Tier B) ∧ (brush selections → Tier C). Selection is a
first-class per-trace bitmask (1 bit/row, §27-budgeted) so styled selected/unselected
rendering (dimming, highlight) works at every LOD tier — aggregated tiers carry a
second "selected-count" channel per bin (feeding the §5 aggregation set), so a brush
visibly lights up density, not just direct marks. Every filter application logs
which tier served it — no silent full rescans.

**API surface (Python):** `fig.filter(expr_or_mask)`, `fig.on_select(callback)`,
`link(fig_a, fig_b, on="x")` — the kernel-side core owns filter state so callbacks
receive Arrow slices, not JSON.

## 35. Milestone amendments (round 3)

- **Phase 0** adds the **wheel matrix + anywidget skeleton** (F1) — distribution is a
  thesis risk on par with the memory claims, so it's proven first, not retrofitted:
  exit criterion "pip install on a clean machine on all five platforms; figure renders
  in Jupyter, VS Code, and Colab."
- **Phase 1** adds Filter Tier A (zone-map range filtering) — near-free once zone maps
  (§22) exist.
- **Phase 2** adds Filter Tier B (visible-window re-bin) alongside the Tier-2
  pyramid — they share the SIMD binning kernel. The fill-rate-aware tier heuristic and
  buffer chunking (F3) are **still pending**: the shipped tier decision is count-only
  and the render client does not chunk vertex buffers (§5).
- **Phase 4** adds Filter Tier C (summed-area index + linked views) with the
  shared-context dashboard work (§18) — same milestone because cross-filtering is a
  dashboard feature.
- The §12 benchmark harness gains three filter benchmarks: range-filter latency (A),
  arbitrary-predicate re-bin latency at 10M/100M visible (B), and Falcon-style brush
  fps across 5 linked views at 100M rows (C) — target ≥50 fps to match the published
  Falcon bar.

## 36. Theming — CSS-native where it can be, a token bridge where it can't

**The constraint, stated honestly:** CSS styles DOM nodes, and the data marks (points,
lines, bars, density surfaces) are **pixels in a `<canvas>`**, not nodes — so a selector
like `.line { stroke: red }` has nothing to match. This is the direct cost of killing
the one-node-per-point wall (§1): you cannot have 10M CSS-addressable elements *and* 10M
points at 60 fps. Every GPU renderer (deck.gl, ECharts-GL, LightningChart) shares this
property. (Calibration: Plotly is barely CSS-styleable either — it writes computed
styles *inline* on its SVG, so stylesheet overrides mostly lose; its users theme via
`layout.template`, not CSS. The bar to clear is lower than "SVG" implies.)

The design splits into three styling surfaces:

**(a) Chrome — genuinely CSS-native.** Axis tick labels, titles, legend, tooltips, and
hover readouts are real HTML/SVG in the DOM (§7). Fonts, color, spacing, borders,
focus states: plain CSS, full inheritance and media queries, no bridge needed. The
container (size, border, background, layout) is ordinary too, and the canvas is
transparent-capable so a page background shows through. This covers most of what "make
the chart match my site" actually means — typography and chrome.

**(b) Marks — themed via a CSS-custom-property bridge.** The render client reads
`--chart-*` custom properties off its container and maps them to GPU state, so the
*marks* are themable through CSS variables even though they aren't CSS *nodes*:

```css
.my-dashboard {
  --chart-bg:   #0f1520;
  --chart-grid: #24313f;
  --chart-axis: rgb(226 232 240 / 55%);
  --chart-text: #e5e7eb;   /* chrome text: ticks, titles, legend, annotations */
}
```

Mechanism: `readTheme()` (`js/src/20_theme.ts`) resolves the canvas tokens at mount and
writes them to renderer state — clear color, grid and axis uniforms, label color. Chrome
tokens are consumed directly by the stylesheet (`XY_CHROME_CSS`, zero-specificity
`:where()` rules) rather than through the renderer. One implementation reality (audit
round 4): `getComputedStyle` returns a custom property's *raw token stream*, not a
resolved color — so color tokens are resolved via a hidden **probe element** (assign
`color: var(--chart-bg)`, read back the browser-computed rgb), which handles every CSS
color format (`oklch()`, `color-mix()`, named colors) without shipping a CSS color
parser. Crucially, **because
tokens flow through CSS variables, the cascade, inheritance, and media queries all
work** — the *variables* cascade even though the pixels don't, so per-container
theming, brand overrides, and `@media (prefers-color-scheme)` behave exactly as a CSS
author expects.

**The theme contract:**
- **A documented token vocabulary**, split by consumer. Canvas tokens read by
  `readTheme()`: `--chart-bg`, `--chart-grid`, `--chart-axis`, `--chart-text`. Chrome
  tokens read by the stylesheet: `--chart-tooltip-bg` / `--chart-tooltip-text`,
  `--chart-legend-bg`, `--chart-badge-bg` / `--chart-badge-text`, `--chart-modebar-bg` /
  `--chart-modebar-active`, `--chart-selection` / `--chart-selection-fill`,
  `--chart-zoom-selection` / `--chart-zoom-selection-fill`, `--chart-crosshair`,
  `--chart-annotation-text`, `--chart-cursor` / `--chart-cursor-pan`, `--chart-focus`.
  Unset tokens fall back to a built-in theme (`currentColor` at documented opacities for
  grid/axis/label). The public reference is `docs/styling/themes-and-tokens.md`.
- *Pending:* a **series-palette token** (`--chart-series-N`, indexed rather than a
  space-separated list so entries cascade and override individually, cycling with a
  lightness rotation past the highest defined index) and a **colormap token**
  (`--chart-colormap`, named ramp or stops → LUT texture). Neither is wired: series
  colors and colormaps come from the spec / `theme()` only. The categorical and
  sequential defaults are the accessible, CVD-safe palettes from §20, not arbitrary.
- **Live re-resolution.** The client watches `matchMedia('(prefers-color-scheme: dark)')`
  and a `MutationObserver` on the container's `class`/`data-theme`/`style`, re-resolving
  tokens on any change. Because of the retained scene graph (§7), **a theme change is
  uniform + LUT updates, never a data re-upload** — theme/dark-mode switching stays at
  60 fps even on a 100M-point figure, and a dashboard theme flip repaints every linked
  view in one frame.
- **Programmatic parity.** Everything a token sets is also settable from Python
  (`fig.theme(...)`) so notebook users who never touch CSS get the same control; the
  CSS bridge is the web-author's path to the same renderer state, not a separate system.
- **Export parity — partially closed; the kernel path is still an open gap.** Two export
  routes exist. *Client-side* (modebar download) is themed correctly: `_exportSvgMarkup()`
  (`js/src/53_interaction.ts`) inlines the resolved `--chart-*` tokens and inherited text
  styles onto the detached clone before serializing, so the downloaded SVG/PNG matches
  the screen. *Kernel-side* export (`to_svg` / `to_png` / `write_image`, rendered by
  `python/xy/_svg.py` and `python/xy/_raster.py`) has no CSS: it uses only the
  Python-set theme (`xy.theme(...)`), so a chart themed purely through CSS custom
  properties exports with the Python theme, not the on-screen one.
  *Pending:* a **theme snapshot** — the client sending its resolved token values back
  over the comm channel on every theme change, so the kernel holds the effective theme.
  No producer or handler exists today. With no client attached (headless script) the
  Python-set theme is authoritative and correct either way.
- **Escape hatches.** `MutationObserver` misses stylesheet swaps and non-color-scheme
  media flips → a public `refreshTheme()` exists for apps that restyle dynamically.
  `forced-colors: active` (Windows High Contrast) restyles DOM chrome automatically
  but not the canvas → the client listens for it and maps marks to the forced palette
  (ties to §20 accessibility).

**(c) Per-mark / data-dependent styling — inherently spec-level, not CSS.** Styling an
individual point (`.point[data-id="42"]:hover`) or coloring by a data column is *not*
reachable by CSS and never will be — there's no node. This goes through the spec
(`color=column`, `size=column`) and the selection bitmask (§34) for
selected/hover/highlight styling, resolved on the GPU. This is a real limitation, not
an oversight: it's the same reason the engine scales.

**Summary:** chrome is plain CSS; background/grid/axis/text are CSS via the
`--chart-*` token bridge (cascade + dark-mode included); per-mark data-driven styling
is spec-level. The one thing we explicitly *don't* promise is arbitrary per-element CSS
selectors on marks — the price of the pixel-based scale everything else buys.

## 37. Transfer protocol & caching — never send the same bytes twice

The kernel↔client boundary (§29, §32) needs a protocol, not just a format. The design
goal: **the wire carries only what the client provably lacks**, and every interaction
class has a defined (usually zero) transfer cost. Prior art absorbed: Perspective's
lesson (batch/schema reuse beats cell-level diffing), Falcon's idle prefetch, HTTP
content-addressing.

**Content-addressed, generation-keyed cache entries.** Every transferable unit —
column chunk, pyramid tile, decimation buffer, filter index slab — has a stable ID:

```
(trace_id, tier, tile_coords | chunk_idx, data_generation, filter_hash, agg_channel)
```

`data_generation` increments on data mutation (append bumps only affected chunks'
generations); `filter_hash` fingerprints the active predicate set (§34). Entries are
**immutable once created** — a changed tile is a *new* ID, never an overwrite — which
makes caching trivially correct: any ID the client holds is valid forever, eviction is
pure LRU under the §27 byte budget, and there is no invalidation protocol to get wrong.

**The manifest handshake.** On any state change the kernel sends a **manifest** (the
ID list the new view needs — a few hundred bytes); the client replies with the subset
it lacks; the kernel ships only those payloads. One round-trip, no redundant bytes,
and a notebook reconnect (fresh client, empty cache) needs no special path — it lacks
everything, so the manifest mechanism *is* the recovery mechanism.

**Per-interaction transfer costs (the contract):**

| Interaction | Wire cost | Why |
|---|---|---|
| Pan (within cached tiles) | **0 bytes** | client composes its cache; view matrix is local |
| Zoom within pyramid levels | **0 bytes** (typ.) | adjacent-level tiles usually prefetched |
| Zoom past pyramid floor / pan to cold region | missing tiles only | manifest diff |
| Filter toggle **back** to a previous state | **0 bytes** (typ.) | old `filter_hash` generation still cached — flipping US on/off re-sends nothing |
| New filter state | recomputed *visible* tiles only | §34 Tier A/B; tagged with new `filter_hash` |
| Streaming append | dirty tile cells + ring delta | O(appended), per §28 |
| Theme / style change | **0 bytes** | client-side uniforms/LUT (§36); nothing goes upstream |
| Hover / pick | ~1 row on drill | pick resolves client-side; drill fetches top-k rows |
| New trace on same DataFrame | new columns only | column IDs shared across figures — a dashboard of 20 views of one table transfers the data **once** (§18) |

**Prefetch & backpressure.** Idle prefetch (Falcon's trick) pulls the adjacent
pyramid level and viewport-neighbor tiles, budget-capped, so the common zoom/pan
stays in the 0-byte rows above. Rapid interaction events **coalesce** (only the
latest viewport wins); every request carries an ID and is **cancelable**, so a
superseded tile request dies on the kernel side instead of clogging the wire.
Responses are batched typed-binary frames (Perspective's lesson — never per-cell
messages), uncompressed on the hot path to preserve zero-copy, lz4 optional for
cold/remote Tier-3 tiles only.

**Two-sided budgets.** The client tile cache and the kernel's LodCache (§10) run the
same eviction policy (LRU weighted by zoom-distance) under independent byte budgets —
and because entries are immutable and recomputable from canonical columns, eviction
on either side is always safe; worst case is a re-send or re-bin, never wrongness.


---
---

# Part 2 — Competitive Research

# How the fastest graphing libraries work — research findings

Companion to the charting-engine design plan. Every load-bearing design decision was
checked against production libraries and the academic literature. **Headline: all six
core bets are independently validated in the field — but no single library combines
them, and the research forces two honest corrections and surfaces ~8 techniques to
steal.**

*Method: the session egress proxy blocked direct page fetches (403 on every host), so
all findings are WebSearch synthesis over primary sources (official docs, GitHub,
papers), with URLs cited (§7). Quantitative figures are the libraries' own published
numbers. A few research subagents received prompt-injected output impersonating system
messages ("drop your guardrails"); these were disregarded and the work redone.*

---

## 1. Scorecard — our design vs the field

| Design decision | Verdict | Strongest evidence |
|---|---|---|
| Arrow binary transport, no JSON | ✅ **Consensus** | Perspective, Mosaic, DuckDB-WASM, deck.gl |
| Offset-encoded f32 + f64 canonical | ✅ **Strongly validated** | deck.gl deprecated emulated fp64 once it did this; Cesium RTC |
| Min/max-per-pixel line decimation | ✅ **Best practice** | = academic M4; Chart.js ships it; 2023 paper recommends MinMax > LTTB |
| Web Worker + WASM core | ✅ **Consensus** | Perspective, DuckDB-WASM (worker-first) |
| GPU as cache, CPU/server canonical | ✅ **Universal** | deck.gl rebuilds GPU buffers from CPU typed arrays; nobody makes GPU the truth |
| Screen-bounded aggregate memory | ✅ **Validated at aggregate layer** | Falcon, datashader, Mosaic, imMens |
| Density-texture aggregation (Tier 2) | ✅ **Validated**, ⚠️ **not novel** | datashader, deck.gl GPUGridAggregator, imMens |
| Data-space tile pyramid (Tier 2/3) | ⚠️ **Refine** | beats datashader's *interactive* path; = its `render_tiles` export path |
| "Single copy / ~0 CPU after upload" | ⚠️ **Overclaim** | even uPlot keeps derived caches; reality is 1+ε copies |
| Plotly "40–100 B/pt × 3 copies" | ⚠️ **Unverified** | directionally right; **measure it**, don't publish it |

---

## 2. Validated — with the refinements the field teaches

**Arrow, no JSON.** Perspective states Arrow-IPC `ArrayBuffer` batches are far more
efficient than JSON (worse) or JS objects (much worse) and spare the main thread.
DuckDB-WASM returns results *always* as Arrow, zero-copy. *Refinements:* transfer
(don't structured-clone) Arrow buffers worker↔main — the backing `ArrayBuffer`s are
Transferable; keep IPC **uncompressed** on the hot path (compression breaks zero-copy).

**Offset-encoded f32 + f64 canonical.** The single strongest validation. deck.gl's
default is a viewport-determined common-space translation (`LNGLAT_OFFSETS`) with a
**zoom-driven origin re-basing that updates only a uniform** — and they **deprecated
emulated fp64 in v6.3** because the offset trick "rivals 64-bit precision at 32-bit
speeds." Cesium's RTC is the same idea (f32 relative to a center, f64 center on the
CPU). *Refinement:* keep full fp64-emulation as a rare fallback, not a default path —
the offset makes it almost never necessary.

**Min/max-per-pixel decimation.** Our Tier-1 is the academic **M4** algorithm (Jugel
et al., VLDB 2014): per pixel column keep **first, last, min, max** — *provably*
pixel-accurate for a rasterized line. The 2023 guidelines paper (arXiv 2304.00900)
finds **MinMax is the most visually *stable* algorithm** and recommends it over LTTB,
which drops spikes and jitters under pan. Chart.js ships `min-max` ("up to 4 points per
pixel") verbatim; ECharts added `minmax` in 5.5.0. *Refinement:* keep the full **4
points/column (M4)**, not just min+max (2) — first+last fix inter-column segment
correctness. Implement the kernel as **SIMD `argminmax`** (tsdownsample: 200–300×
NumPy, 1B pts <0.1s).

**Worker + WASM core.** Perspective runs its C++/WASM engine in a WebWorker; DuckDB-WASM
is "worker-first." Arquero is the counterexample — single-threaded main-thread JS — and
is cited as the thing that *doesn't* scale. Validates keeping the core off the main
thread.

**GPU as cache.** deck.gl rebuilds GPU buffers from canonical CPU typed arrays and
shallow-compares `data` to skip regen. No library treats GPU memory as source of truth.
Matches our §27 ownership model exactly.

**Screen-bounded aggregate memory.** Falcon: "the size of the data tile is independent
of the size of the data" (∝ bins × pixels). datashader: "fixed-size regardless of
records." imMens: "limited by the chosen resolution … not the number of records."
*Honest scope:* this holds at the **aggregate/index layer** — vaex/Arquero/deck.gl are
still data-bounded in their base store. Our tiling is what carries the property down to
the base layer.

**Deferred colormapping.** datashader's pipeline is Aggregate → Transform → Colormap
(default `eq_hist` histogram-equalization to beat overplotting) — exactly our
"colormap at composite time, so restyle never re-bins."

---

## 3. Corrections the research forces (the most valuable part)

**(a) "Single canonical copy, ~0 CPU after upload" is an overclaim.** Even uPlot — the
leanest library measured — keeps derived path/scale caches, and has an *open* zero-copy
request (#1124) precisely because true zero-copy isn't the default. Reality is **1 + ε
copies**: full columnar array once + small screen-bounded derived buffers. The doc
should say that, not imply zero extra bytes. *Good news:* the **bytes/point target is
validated and even conservative** — uPlot's typed-columnar, no-object-model design hits
**21 MB peak / 3 MB final** vs dygraphs 88/42 and Highcharts 97/55 on the same
benchmark. 12–24 B/pt is realistic.

**(b) Plotly's "40–100 B/pt × 3 copies" is not primary-sourced.** It's directionally
supported (Plotly keeps input + `calcdata` + GL/SVG buffers; plotly-resampler reports
**>10 GB → <700 MB ≈ 14×** when downsampled), but the exact byte figure should be
**measured** (heap-snapshot `scatter` vs `scattergl` at 1M pts) before it appears in any
public claim. Treat as estimate, not citation.

**(c) Hard GPU ceilings to design around.** deck.gl: ~1M points @60fps, degrades to
10–20fps near 10M, and **crashes between 10M–100M** during buffer generation because
**Chrome caps a single allocation at ~1 GB**. Plus **fragment fill-rate**: 10M radius-5
points ≈ **1B fragment invocations/frame**. Rerun hits a **2M-point wall** by
re-uploading every frame (validates our retained buffers, but shows the ceiling is
real). *Implication:* our **direct Tier-0 must chunk large buffers** and hand off to
aggregation before ~1M *drawn* marks — the vertex count isn't the only limit, fill-rate
and the 1 GB cap are.

**(d) The tile pyramid is not novel — and a static one goes stale.** datashader already
ships `render_tiles` (power-of-two 4096²→256² tiles, NetCDF out-of-core) — our Tier-2/3
*is* that, plus classic XYZ map pyramids. Our genuine contribution is making it **live
and interactive** (client-side per-frame compositing, re-bin only below the floor),
whereas datashader's is static export. **But** datashader keeps its *interactive* mode
re-aggregating on purpose: **a fixed pyramid is stale under brushing / filtering /
transform changes**, which re-aggregation handles for free. *This is a real gap in our
doc:* if we want dynamic filters on top of the pyramid, we need a fast re-bin path or a
**Falcon-style active-dimension index layered over the pyramid**.

---

## 4. Techniques to steal (ranked; mapped to doc sections)

1. **Falcon/Mosaic summed-area-table data cube** — for linked-view cross-filtering at
   scale. A cumulative-sum index keyed on the active brushing dimension makes any brush
   = a difference of cumsums → **O(1) passive-view updates, index size ∝ bins not rows**.
   Mosaic auto-materializes these at pixel resolution. *This is the answer for dashboard
   brushing (§18) and the fix for the stale-pyramid gap (§3d).*
2. **deck.gl offset-origin re-basing via uniform-only update** — the concrete mechanism
   for our §4/§16 precision path.
3. **Async GPU picking**: Rerun's integer **R32UI** ID texture + `GpuReadbackBelt`
   (async readback, no stall) over deck.gl's RGB8 (16M-ID cap); carry a **per-instance
   index** channel (GLMakie). Plus deck.gl's reusable **picking shader-module toggled by
   one uniform** so every mark type gets picking for free. *Augments §17.*
4. **Line rendering, two schools** — Rerun's **un-instanced triangle-list +
   `gl_VertexID`, joins as fragment-shader cut-outs, data in textures** for *many short*
   polylines (multi-series time series); instanced segments (regl-gpu-lines, 2 draw
   calls, miter/round joins) for *long* paths. Nobody uses `GL.LINES`. *Augments §7.*
5. **SDF markers** (quad + fragment-shader signed-distance function) for crisp,
   resolution-independent antialiased points — deck.gl, Makie, and Plotly all do this.
6. **DuckDB-WASM / hyparquet out-of-core**: Parquet **HTTP range requests +
   row-group-stat predicate pushdown** as the Tier-3 mechanism — possibly **no bespoke
   tiler needed**; Parquet row-group stats *are* a free coarse index (matches our zone
   maps §22). *Augments §5/§28.*
7. **VegaFusion DAG-partitioning** — decide *per transform node* whether it runs
   native-side or in the browser. A principled model for our native-core-vs-WASM split —
   **especially relevant now that binding is Python-only** (heavy nodes run native
   in-process; only leaf render nodes cross to the browser). *Augments §8/§9/§29.*
8. **Perspective's lesson**: batch/schema reuse **over** cell-level diffing — they
   *dropped* per-cell partial updates because computing which cells changed cost more
   than re-sending Arrow row batches. Bear on our diff engine (§7).

---

## 5. The datashader question, answered (the crux)

**Does datashader precompute a pyramid or re-aggregate every zoom?** In its **default
interactive mode: re-aggregates from scratch on every zoom/pan** — no cached pyramid.
HoloViews `rasterize`/`datashade` wrap the data in a `DynamicMap` driven by `RangeXY` +
`PlotSize` streams; each viewport change fires a **server-side callback that reruns
aggregation** over the in-view data into a fresh `Canvas(w, h, x_range, y_range)` grid,
then ships **one RGBA image** back over the Bokeh websocket. Cost per interaction =
**O(points in view) + a network round-trip**, nothing composited or reused between
frames. (It's made bearable by Numba + multicore + Dask/CUDA: ~1B points in seconds, 4B
in <3 min on 32 cores.) A *separate* offline module, `render_tiles`, does build a
static power-of-two pyramid — but not in the interactive path.

**Verdict:** for **navigation**, our live data-space pyramid genuinely beats datashader's
interactive path — **O(visible tiles), no per-frame round-trip, client-side
compositing, re-bin only below the floor** = strictly lower latency and jitter. It does
**not** beat datashader's own `render_tiles` in concept (same pyramid idea) and it
inherits the **static-pyramid-is-stale-under-filtering** tradeoff. Defensible framing:
we **unify** them — a *live* pyramid with client compositing — and layer a Falcon-style
active-dimension index when dynamic filtering is needed.

---

## 6. Competitive scale numbers (grounds the "how much faster" comparison)

| System | Published figure |
|---|---|
| Plotly.py `scattergl` | practical ceiling **~1M**; SVG ~10⁴–10⁵ |
| plotly-resampler | ships ~1000 pts; **>10 GB → <700 MB** memory |
| deck.gl (WebGL) | ~1M @60fps; **crashes 10M–100M** (1 GB alloc cap); fill-rate bound |
| uPlot | **21 MB peak** (vs 88–97); 166k pts in ~25 ms; ~6fps @100k OHLC |
| ECharts | "millions" via progressive (latency only, not memory); ~23fps @100k |
| datashader | **~1B in ~1s** (16 GB laptop); 4B in <3 min / 32 cores; GPU 10–15× @300M |
| vaex | **~1B rows/s** on-grid stats; out-of-core / mmap |
| Falcon | **50 fps**, 5 passive views, pixel-level brush; 10M browser / 1.7B via GPU DB |
| imMens | **50 fps invariant thousands→billions**; ≤4-D tiles; single active brush |
| Nanocubes | billions in laptop RAM (100s MB–GB); arbitrary dims, higher latency |
| VegaFusion | 1M-row histogram **~9.5s → ~0.6s** (aggregation pushed to Rust) |
| LightningChart JS | ~1.5B interactive line (commercial WebGL); 10M in ~0.29s |

---

## 7. Sources

**GPU rendering.** deck.gl performance/coordinate-systems/picking docs
(deck.gl/docs/*), vis.gl "flat earth" precision blog, luma.gl v9 docs, regl API,
LightningChart perf pages, Rerun `re_renderer` docs + ARCHITECTURE.md + issues #1136/#7857,
GLMakie/WGLMakie docs, Plotly.js WebGL deepwiki, regl-gpu-lines, Stardust (EuroVis 2017).

**Arrow / WASM / columnar.** Perspective architecture docs + discussions #2995/#1750,
regular-table, ClickHouse×Perspective blog; vaex docs + arXiv:1801.02638; Falcon
(idl.uw.edu/papers/falcon, CHI 2019) + falcon-vis; Mosaic (idl.cs.washington.edu
2024-Mosaic-TVCG.pdf) + arXiv:2507.19690; DuckDB-WASM (duckdb.org 2021 blog);
Arquero/Flechette (idl.uw.edu); hyparquet; Arrow IPC docs + issue #39017.

**Decimation.** LTTB thesis (Steinarsson 2013, skemman.is); M4 (vldb.org p797/p1705) +
Observable @uwdata/m4; guidelines paper arXiv:2304.00900; MinMaxLTTB arXiv:2305.00332;
tsdownsample arXiv:2307.05389; plotly-resampler arXiv:2206.08703; uPlot GitHub + HN
threads + issues #1124/#1122; ECharts perf/large-data/5.5.0 docs + ECharts-GL; Chart.js
decimation docs + PR #8468; dygraphs docs; regl-scatterplot; SciChart benchmark suite.

**Aggregation / data tiles.** imMens (vis.stanford.edu/papers/immens, EuroVis 2013,
DOI 10.1111/cgf.12129) + code; Nanocubes (IEEE TVCG 2013) + laurolins.github.io;
Hashedcubes (IEEE TVCG 2017); datashader Pipeline/Performance/Interactivity/tiling docs
+ tiles.py; HoloViews Large_Data; VegaFusion (vegafusion.io, arXiv:2208.06631); Bokeh
server / InteractiveImage discourse; viz surveys (Springer, Tsinghua VLDBJ).
---
---

# Part 3 — Performance estimates vs standard Python & React libraries

**These are design targets measured against each library's own published/measured
numbers — not results of a built system.** Phase 0's benchmark harness exists to replace
every estimate here with a measurement (Plotly side-by-side, regressions fail the build).
The honest framing: this is not one multiplier. The field splits into "convenience"
libraries (huge audience, low ceiling) and "big-data specialists" (high ceiling, poor
interactivity/ergonomics), and this engine beats each camp differently.

## Python libraries

| Library | Interactive ceiling | Memory | Interactive pan/zoom | Exact hover at scale | Notebook |
|---|---|---|---|---|---|
| **Matplotlib** | ~10⁴–10⁵ (static beyond) | heavy | ✗ static PNG | ✗ | render-only |
| **Plotly.py** | ~1M (`scattergl`); ~10⁴ SVG | high — resampler saw >10 GB → <700 MB (~14×) | ✓ but stutters near ceiling | ✓ small data | ✓ |
| **Bokeh / Altair** | ~10⁵ (Altair caps at 5k rows) | high | ✓ | ✓ small | ✓ |
| **datashader** | ~1B in ~1s (16 GB laptop) | screen-bounded (ships pixels) | ✗ alone — re-aggregates every zoom + round-trip; needs HoloViews/Bokeh stack | ✗ (raster) | ✓ |
| **vaex** | ~1B rows/s on-grid | out-of-core / mmap | limited | ✗ | partial |
| **PyQtGraph / VisPy** | millions (GPU) | moderate | ✓ | partial | ✗ desktop-first |
| **This engine** | **100M–1B, interactive** | **12–24 B/pt direct; screen-bounded aggregated** | ✓ local (tile reuse) | ✓ via canonical store + drill | ✓ |

## React / JS libraries

React chart libs are often *worse* than Python's, because SVG + React reconciliation
creates a **React element (and vdom diff) per data point**.

| Band | Libraries | Practical ceiling | Multiplier to our target |
|---|---|---|---|
| React SVG | **Recharts, Victory, Nivo** | ~1–10k points | **~10,000×** |
| React SVG (lean) | visx | ~10–50k | ~2,000× |
| Canvas wrappers | react-chartjs-2 (+decimation), uPlot-react | ~100k–1M lines | ~100× |
| Canvas / WebGL | ECharts (~23 fps @100k measured), Plotly.js `scattergl` (~1M) | ~1M | ~100× (via our aggregation tiers) |
| GPU-first | deck.gl (~1M @60fps; degrades by 10M; crashes 10–100M @ 1 GB alloc cap) | ~1–10M | ~10–100× |

Two structural notes for React specifically:
- Our marks **bypass React reconciliation entirely** — the component is a thin mount;
  data flows as Arrow over the prop/comm boundary, never through vdom diffing or state.
- Versus **deck.gl** (the strongest React-ecosystem competitor), the win isn't raw draw
  speed — it's the **aggregation tiers** plus the **buffer chunking** that deck.gl
  documents crashing without (the ~1 GB single-allocation cap, 10M–100M items).

## The verdict that matters

The honest headline is not "N× faster than everything." It is: **no existing Python or
React library gives you all four of {100M+ points, fully interactive pan/zoom/hover,
low/bounded memory, one simple API in a notebook or React app} at once.**

- vs the **convenience libraries** (Plotly, Bokeh, Altair, Recharts, Victory, Nivo,
  visx): **1–4 orders of magnitude** more points, several-fold less memory, no
  main-thread freeze. This is the decisive, everyday win.
- vs the **big-data specialists** (datashader, vaex): **not dramatically faster at raw
  throughput** — they use the same aggregation trick, so we're in their class, not 10×
  past them. The win is architectural: interactive pan (tile reuse vs re-aggregate +
  round-trip), exact hover/drill, and a single ergonomic API instead of a multi-library
  stack.
- vs **desktop GPU** (PyQtGraph, VisPy): comparable at ~1M on a desktop; our edge shows
  at 10M+, out-of-core, and *in the browser/notebook*, which they don't target.

**Two honesty caveats.** (1) Targets, not measurements — Phase 0 replaces them. (2) On a
plain desktop at ~1M points, VisPy/PyQtGraph and deck.gl are already GPU-fast; we don't
blow them away there — the separation appears at 10M+, out-of-core, linked-view
filtering, and low resident memory.


---
---

# Appendix A — Audit Log (round 3, verbatim)

*This is the raw adversarial review that produced Part IV. F1–F3 were resolved into §32–§35; F4–F12 remain outstanding (see the status table at the top).*

# Design audit — round 3 (post-research, Python-only)

Adversarial review of the charting-engine design plan **as it now stands** — i.e. after
Parts I–III, the **Python-only binding** decision, and the library research. Every
finding here is **new relative to Parts II and III** (I did not re-list the SAB, f32,
byte-identical, aggregation-cost, or Tier-3-index findings — those are already resolved
in the doc). Two lenses drive this round:

1. **Python-only changes the risk surface.** The binding layer collapses, but the
   product now lives or dies on two things the doc barely mentions: *how the native
   core ships via pip* and *how the render client gets into a notebook cell*.
2. **The research exposed real ceilings and gaps** — fill-rate, the 1 GB allocation
   cap, the stale-pyramid-under-filtering tradeoff, and the fact that the pyramid isn't
   novel.

Confidence is marked per finding: **[confirmed]** = verifiable by reading the doc or a
cited primary source; **[plausible]** = a logical consequence I'm confident of but
haven't measured.

---

## Findings summary

| # | Finding | Severity | Confidence |
|---|---|---|---|
| F1 | No packaging/distribution story — the #1 risk for a Python-only product | **Critical** | confirmed |
| F2 | No filtering / selection / linked-brushing model; a static pyramid is stale under any filter | **Critical** | confirmed |
| F3 | GPU ceilings mis-modeled — fill-rate & the 1 GB single-allocation cap bound Tier 0, not point count | **Major** | confirmed |
| F4 | A single viewport offset can't serve multiple traces at different coordinate magnitudes | **Major** | plausible |
| F5 | Tier-2 assumes a scalar density — color-by-category / mean / non-count aggregation unmodeled | **Major** | confirmed |
| F6 | Colormap normalization domain across pyramid levels is unspecified → brightness flicker on zoom | **Major** | plausible |
| F7 | Streaming into the pyramid is under-reconciled with multi-level structure + eviction | Moderate | confirmed |
| F8 | "One core, logically identical" collides with the per-backend implementation matrix | Moderate | confirmed |
| F9 | Pyramid storage cost ("~1.33×") undercounted for multi-trace / fine-level / multi-channel | Moderate | confirmed |
| F10 | "Plotly ~40–100 B/pt × 3 copies" stated as fact but unverified | Moderate (credibility) | confirmed |
| F11 | Arrow IPC deserialization robustness for served/multi-user apps | Minor (v1) | plausible |
| F12 | Positioning — the tile pyramid is framed as the differentiator but isn't novel | Minor (honesty) | confirmed |

---

## The three that actually change the plan

**F1 and F2 are not refinements — they are missing workstreams.** F1 is a whole
distribution engineering track that determines whether anyone can `pip install` this at
all; plotly.py's real-world complexity lives almost entirely here, not in rendering.
F2 is a missing *core capability* — filtering is not an edge case in analytics, it's the
main event, and the pyramid as designed cannot answer a filtered query. **F3** is the
one that most changes the *rendering* design: the tier heuristic and the "one draw call"
idealization are both wrong against real GPU limits. Everything else is correctness
detail or honesty.

---

## Detailed findings

### F1 — Packaging & distribution is unspecified. For Python-only, it's the highest risk. [Critical]
**Failure scenario.** `pip install <engine>` must deliver three separately-hard things:
(a) the **native Rust core** as prebuilt wheels across the matrix — manylinux (x86_64 +
aarch64), macOS (arm64 + x86_64), Windows — via a plain C-ABI `cdylib` built by
Hatchling, so the Python-version cross-product disappears without PyO3 or `abi3`; (b)
the compiled **JS/WebGL2 render client** as bundled static assets; (c) a **notebook
front-end integration** that injects that client
into an output cell and speaks the comm protocol. Miss one wheel and the user falls back
to a source build that needs a Rust toolchain — an instant adoption cliff, and the exact
friction that dogged early Rust-backed Python packages. The doc's §23 covers *runtime*
environments but nothing about *shipping the bits*.
**Fix.** Add a Distribution section: C-ABI platform wheels with a CI wheel matrix;
**`anywidget`** as the notebook client substrate (current standard — one implementation
works across Jupyter, Lab, VS Code, Colab, Marimo, and Reflex-style servers); explicit
asset bundling; **comm-protocol versioning** between the native core and the JS client
(they ship together but must fail loudly on mismatch); and a defined no-native-core
behavior (a clear, actionable ImportError naming the supported platforms — never a
silent quality or correctness change). This is bigger than any single rendering
decision.

### F2 — No filtering / selection / linked-brushing; the pyramid is stale under any filter. [Critical]
**Failure scenario.** The user filters (`df[df.region=="US"]`) or box-selects a region to
cross-filter a second chart. The precomputed Tier-2/3 pyramid holds *unfiltered* counts
and physically cannot answer the filtered query — it would show the wrong density.
§28's LOD contract has no filter path at all. Research (§3d of the findings) confirmed
datashader deliberately re-aggregates on every interaction precisely because a fixed
pyramid can't absorb dynamic predicates.
**Fix.** Define a filter model with three tiers of its own: (1) **indexed range
predicates** → prune/clip tiles via zone maps (§22), cheap; (2) **arbitrary predicates**
→ fast re-bin of the *visible window only* in the native SIMD core; (3) **linked brushing
across views** → adopt the **Falcon/Mosaic summed-area active-dimension cube** (research
steal #1): brush = difference of cumulative sums, **O(1) passive-view updates, index size
∝ bins not rows**. This closes both the functional gap and the stale-pyramid tradeoff,
and it's the single highest-value technique the research surfaced.

### F3 — GPU ceilings mis-modeled: fill-rate and the 1 GB cap, not vertex count. [Major]
**Failure scenario.** Two concrete ways "Tier 0 ≤ 1–2M points, one instanced draw"
breaks: (a) **allocation** — 100M f32 x/y is 800 MB in one buffer, at Chrome's documented
**~1 GB single-allocation cap**; add color/size and buffer *creation* crashes (deck.gl
documents crashes between 10M–100M for exactly this). The "one draw call for N points"
is an idealization. (b) **Fill-rate** — 10M radius-5 points ≈ **1B fragment invocations
per frame** independent of vertex count; a *500k*-point scatter with large or overlapping
semi-transparent markers is fill-bound well below the "1–2M" vertex ceiling.
**Fix.** (i) The render core must **chunk vertex buffers** (multi-buffer draw) and state
that explicitly. (ii) Tier selection must be `f(point_count, mark_pixel_area × overdraw)`
— a dense large-marker scatter trips Tier-2 aggregation even at "sub-ceiling" counts.
The doc currently selects tiers on count alone.

### F4 — One viewport offset can't serve multiple traces at different magnitudes. [Major]
**Failure scenario.** Two traces on shared axes: one with values ~0, one ~1e12 (or a
dual-axis chart, or a map overlay + local inset). deck.gl re-bases f32 by a *single*
viewport origin; a single origin leaves the far trace with catastrophic f32 error.
§4/§16 assume one offset window per plot.
**Fix.** Per-trace (or per-axis) offset+scale resolved into **per-trace model matrices**;
the shared view transform stays f64 on CPU and composes with each trace's offset at
upload. Modest bookkeeping, but the doc doesn't have it and multi-trace is the norm.

### F5 — Tier-2 assumes a scalar density; categorical/aggregation algebra is missing. [Major]
**Failure scenario.** `scatter(x, y, color=category)` with 12 categories over 50M points.
One density texture can't carry per-category counts; you need N per-category planes
(imMens's ∏-bins problem) or a per-bin categorical mode/argmax. `color=mean(value)` needs
2-channel (sum,count) accumulation; std needs more. The doc's Tier-2 is single-scalar.
**Fix.** Specify the **aggregation algebra** — count / sum / mean(2-ch) / min / max /
**categorical-by (N capped planes + "other")** — mirroring datashader's `ds.by`/`ds.mean`,
with its memory cost (N× the tile, feeding F9) and a category cap that logs truncation.

### F6 — Colormap normalization across pyramid levels is unspecified → zoom flicker. [Major]
**Failure scenario.** Color maps bin-count→hue. Coarse tiles have higher counts than fine
ones, and the visible max varies per viewport. Normalize per-tile → visible seams;
normalize globally → a near-black screen when zoomed in (all local counts low). Either
way, **zoom visibly flickers brightness.** datashader recomputes `eq_hist` per view for
this reason.
**Fix.** Normalization domain = **per-view**: recompute min/max (or a histogram for
`eq_hist`/log) over the *composed visible tiles* each frame — O(visible tiles), cheap.
State this, and expose linear/log/eq_hist at composite time (which, per research, is
where datashader does it too — validating "colormap at composite" but not the domain).

### F7 — Streaming into the pyramid is under-reconciled. [Moderate]
**Failure scenario.** 100k pts/s appended. §28 says "incremental tile update for touched
cells," but an appended point touches one cell at *every* pyramid level, and ring-buffer
**eviction must decrement** expired points' bins across all levels — a count/sum tile can
`+=`/`-=`, but a **min/max tile cannot be decremented** (you can't un-see the old max),
and per-view normalization (F6) drifts as totals change.
**Fix.** `+=` on append and `-=` on eviction across all levels for count/sum; **min/max
tiles need periodic rebuild** over the retained window — state that limitation; re-derive
normalization each frame per F6.

### F8 — "One core, logically identical" vs the per-backend matrix. [Moderate]
**Failure scenario.** Tier-2 now has three implementations (WebGPU compute / WebGL2
additive-blend / worker SIMD), lines have two schools, precision has fallbacks. The
"logically identical across targets" guarantee (§21) actually spans backends × tiers ×
trace-kinds × fallbacks — and the places most likely to diverge (the fallbacks) are the
least likely to be tested if the oracle only checks the primary path.
**Fix.** Scope the consistency guarantee to **tier *outputs*** — the decimated/binned
aggregate buffers, which are backend-independent and can be asserted **bit-identical**
across WebGPU/WebGL2-blend/worker-SIMD — and test *pixels* per-backend against the CPU
reference. That makes the strong claim (identical aggregates) cheaply testable and
demotes the pixel claim to per-backend perceptual diff.

### F9 — Pyramid storage "~1.33×" undercounts multi-trace / fine-level / multi-channel. [Moderate]
**Failure scenario.** "~1.33× the finest level" is *per trace, single channel*. A
dashboard of 20 traces, each with a fine level sized to a 4K viewport, × the multi-channel
tiles from F5, is 20 × 1.33 × channels — not a rounding error. imMens noted dense tiles
reach "millions of values" even at low dimensionality.
**Fix.** Put pyramid storage under the §27 byte budget with eviction: keep the cheap
coarse levels resident, **LRU-evict fine levels** (rebuildable from canonical), and state
the multi-trace × multi-channel multiplier in the memory model.

### F10 — "Plotly ~40–100 B/pt × 3 copies" is stated as fact but unverified. [Moderate — credibility]
The research could not source this figure. It's directionally supported (input +
`calcdata` + GL/SVG buffers; plotly-resampler's **>10 GB → <700 MB ≈ 14×**) but the byte
number is an estimate. In a doc whose thesis is "every number has a test," publishing an
unmeasured competitor figure is a credibility liability.
**Fix.** Relabel as an estimate pending a heap-snapshot measurement (`scatter` vs
`scattergl` at 1M pts); lead with the defensible 14× resampler figure.

### F11 — Arrow IPC deserialization robustness for served apps. [Minor — v1]
**Failure scenario.** A server app (Dash/Reflex-style) or a shared kernel receives Arrow
buffers from clients, or renders user-uploaded files; malformed IPC (bad offsets/lengths)
must not crash or read out of bounds. Rust helps, but the IPC reader is an attack surface.
**Fix.** Fuzz the Arrow ingest path; treat all cross-boundary Arrow as untrusted;
bounds-check offsets. Note under the §29 server-app row.

### F12 — The tile pyramid is framed as the differentiator but isn't novel. [Minor — honesty]
Research: datashader's `render_tiles` already builds power-of-two 256² pyramids (offline),
and XYZ map tiles are the classic form. The genuine contribution is a **live, interactive**
pyramid — client-side compositing, re-bin below the floor, and (per F2) a filter-aware
Falcon index over it.
**Fix.** Reframe the contribution as *unifying live interaction with the pyramid + index*,
not inventing the pyramid. Protects credibility and sharpens the actual claim.

---

## Corrections to fold into the main design doc

- **New section — Distribution** (F1): C-ABI platform wheels, anywidget client, static
  asset bundling, comm versioning, no-wheel fallback.
- **New section — Filtering, selection & linked views** (F2): three-tier filter model +
  Falcon summed-area index. Update §28 to reference it.
- **§2 / §5** (F3): tier heuristic = `f(count, mark_area × overdraw)`; buffer chunking;
  fill-rate + 1 GB cap named as ceilings.
- **§4 / §16** (F4): per-trace offset/scale + per-trace model matrices.
- **§5** (F5, F6): aggregation algebra (count/sum/mean/min/max/categorical-by) and
  per-view normalization domain.
- **§27** (F9): pyramid storage under budget with LRU eviction; multi-trace/channel
  multiplier.
- **§21** (F8): consistency guarantee scoped to aggregate buffers (bit-identical) +
  per-backend pixel diffs.
- **§28** (F7): streaming +=/-= across levels; min/max rebuild caveat.
- **§1 / §2** (F10): relabel the Plotly byte figure as an estimate; lead with 14×.
- **§29** (F11): fuzz Arrow ingest; untrusted-buffer handling.
- **§5 framing** (F12): pyramid = unifying live interaction, not novel invention.

## Verdict

The design survives the round — nothing here refutes the core thesis (screen-bounded
cost via LOD + Arrow + GPU), and the research independently validated all six load-bearing
bets. But two genuine gaps (**distribution**, **filtering**) are missing workstreams, not
tweaks, and the rendering model needs to trade its idealized "one draw call, count-based
tiers" for the real GPU ceilings (**F3**). Fix those three and the plan is buildable; the
rest are correctness and honesty polish.
