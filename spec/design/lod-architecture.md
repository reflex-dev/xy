# LOD / Drilldown Architecture — Tier 0/1/2/3

**Status:** design + implementation plan. Supersedes nothing — this refines
dossier §5/§10/§16/§17/§22/§28 into a buildable spec, grounded in what already
ships (`python/xy/lod.py`, `js/src/45_lod.ts`, `interaction.py`,
kernels ABI v3). The whole XY claim rests on one sentence:

> **Large data stays truthful and interactive.**

Truthful means: nothing drawn implies data that doesn't exist, nothing that
exists is silently hidden, and every reduction is recorded in the spec (§28).
Interactive means: pan/zoom stays inside the §17 frame budget at any N.

---

## 1. The tier ladder (per-kind, not global)

A **tier is a property of a (trace, viewport) pair**, never of a dataset:
what ships is count-only, `tier = f(visible_count)`, hysteresis-guarded (§5).
`drill_decision(visible, budget, in_drill, exit_factor)` in `python/xy/lod.py`
returns `visible <= budget * (exit_factor if in_drill else 1.0)`; `js/src/45_lod.ts`
mirrors it. Implemented today for scatter (drill-in/out with hysteresis); this
doc extends the same rule to every kind. Folding `mark_pixel_area × overdraw`
into the decision is dossier F3 — *specified, pending, not implemented*; no
pixel-area or overdraw term exists in `python/xy/` or `js/src/` today.

| Tier | Name | Representation | Cost model | Status |
|---|---|---|---|---|
| 0 | Direct | every visible mark, exact | O(visible) verts | shipped (all kinds) |
| 1 | Shape-preserving reduction | per-pixel-column aggregate that IS the mark's meaning (M4 for lines; OHLC-bucket for candles when finance returns; max-bin for bars) | O(px) verts | shipped (line) |
| 2 | Density / aggregate surface | mean-point-color texture composited at the points' own alpha (§2) | O(screen) texels | shipped (scatter) |
| 3 | Out-of-core tiles | Tier-2 pyramid where not all tiles are resident | O(visible tiles) | **this doc** |

**Invariant L1 (recorded reduction):** every update carries `tier`, `mode`,
`visible`, and `reduction` (implemented for scatter updates through
`lod.LodPlan`; initial density traces carry `tier` plus density metadata).
**Invariant L2 (exact under budget):** if `visible ≤ budget`, the user sees
real marks with real channels — never a sample, never an aggregate.
**Invariant L3 (index-space versioning):** any shipped subset is versioned
(`drill_seq`) and stale cross-wire replies are dropped, not translated
(shipped; keep for every future subset-shipping kind).

### Per-kind ladder

| Kind | Tier 0 | Tier 1 | Tier 2 | zoom-in recovery |
|---|---|---|---|---|
| scatter | points | — (unordered decimation lies, §28) | mean-color density grid (§2; count planes + color planes, §4 below) | drill-in ships exact points + channels for a padded ALIGNED window (T13); views inside any shipped window — live or cached — are answered locally, no request (T12/T13) |
| line/area | polyline | M4 per column (extrema-exact) | — (M4 already screen-bounded) | re-decimate window (shipped) |
| heatmap | cell rects | — | mip-style tile reduction of the user grid (max/mean recorded) | finer pyramid level, then exact cells |
| histogram/bar | rects | re-bin at viewport resolution | — (bins are already aggregates) | re-bin visible window (finer bins = more truth, never less) |
| candlestick (when restored) | body+wick | OHLC bucket (first/max/min/last) | — | re-bucket window |

Key asymmetry to respect: **histogram/heatmap are born aggregated** — their
Tier-1 is "re-aggregate at the right resolution," and truthfulness means the
*bin math* is exact, not that raw rows are drawn. Scatter is the only kind
whose Tier 2 changes representation entirely; that's why the drill machinery
lives there.

### Shared Python contract

Tiered chart kinds must enter through the common LOD primitives in
`python/xy/lod.py`:

- `ViewportRequest.from_client(...)` normalizes flipped ranges, rejects
  non-finite bounds, and clamps hostile/tiny screen dimensions before any
  kernel, cache, or trace drill-state mutation sees them.
- `plan_view_lod(...)` records the direct-vs-aggregate decision, hysteresis,
  screen-bounded grid shape, `mode`, `tier`, `visible`, and `reduction`.
- `EncodedColumn`, `encode_f32_values(...)`, `geometry_offset(...)`,
  `encode_window_xy_columns(...)`, `add_window_xy(...)`, and
  `BufferWriter.add_encoded(...)` are the shared geometry wire primitive: f64
  data-space values become finite f32 buffers plus `{offset, scale, len}`
  metadata in exactly one place. `geometry_offset` is the one offset policy:
  window/domain midpoint on linear axes, pinned 0.0 on log-family axes
  (dossier §16).
- `sample_rows_for_target(...)` is the shared target-bounded subset primitive:
  density overlays and future sampled tiers ask for "about N stable rows from
  this viewport" in one place instead of copying target-fraction math.
- `local_log_density(...)` provides the transition handoff values used when an
  aggregate view drills into exact points without a visual hard cut.

Scatter uses this today for density sample overlays and drill updates through
`add_window_xy(...)`. Line and area zoom re-decimation also route incremental
buffers through `BufferWriter.add_encoded` so the wire contract is shared even
when the tier decision is simply "M4 for this x-window." Future candlestick,
box plot, histogram, or heatmap LOD code should pass its own representation
names (`ohlc-buckets`, `box-buckets`, `bins`, etc.) into
`plan_view_lod(...)` instead of reimplementing viewport validation, tier
metadata, or encoded-buffer assembly.

---

## 2. Zoomed-out truthfulness with channels (the "no visual lying" rules)

Aggregating positions is easy; aggregating **color/size/category** without
lying is the hard part (§5-F5). The governing principle, shipped: **the
density surface wears the data's own colors, and it composites like the
data's own points.** A cell is what the eye would see if every one of its
points were drawn sub-pixel — the physically downsampled image — so the
aggregate view and the point view are two magnifications of the same
picture, not two different charts: same hue (the mean point color), same
lightness (the points' own alpha compositing).

1. **A mean-color cell's displayed alpha is the PHYSICAL compositing of its
   own points:** `1 − (1 − a_pt)^k` for k points whose drawn per-point
   alpha is `a_pt = mean channel alpha × trace style opacity` — exactly
   what k overplotted marks composite to, saturating after a few points
   just as real marks do. Style opacity folds INSIDE the exponent (dense
   cells saturate past it exactly like real overplot), so the draw path
   applies only transition fades on top of these textures — never the
   style opacity again. No window normalization touches the alpha, so
   lightness cannot swing between windows or across the texture↔points
   boundary (the previous law — a per-window log-count tone curve driving
   opacity — did both: a field capture of the 100M drilldown showed the
   surface visibly lighter/darker than the very points it aggregated). The
   count grid still ships (`buf` + `max`, log-u8): it marks occupancy, is
   the compositing exponent, and remains the ONLY structure — and the alpha
   ramp — for count-only surfaces (constant-color traces, hand-built/legacy
   specs), which keep the log tone curve and its eased normalization (T4).
   The recorded cost of physical alpha: density beyond a few points per
   cell no longer reads in the surface (real overplotted points saturate
   identically — the aggregate is exactly as saturated as the truth it
   downsamples; drill-in is where per-point structure returns).
2. **Per-point colors → per-cell alpha-weighted MEAN of the *resolved*
   colors, averaged in linear light.** One law for every channel mode —
   continuous (colormapped value), categorical (palette color), and
   `direct_rgba` alike: each point contributes the exact sRGB color it draws
   with, weighted by its straight alpha, summed in linear light (integer
   pipeline: checked-in sRGB⇄linear-u16 tables, u64 sums — bitwise
   deterministic across thread counts and platforms), then quantized back to
   sRGB. Ships as a `w*h*4` straight-alpha RGBA8 plane (`rgba`, mean color +
   mean point alpha) with `color_agg: "mean"` recorded; displayed alpha
   follows rule 1 (physical compositing of ā over the cell count). A cell
   of one point shows that point's exact color at that point's own alpha;
   an all-invisible (alpha-0) cell never invents one.
   Constant-color traces ship no plane — the mean of a constant IS the
   constant, so the wire keeps the 1-byte count grid plus `color` and the
   client tints (bit-equivalent, 4× cheaper). Cost, recorded: a
   channel-bearing trace pays one extra O(visible) color pass per exact
   re-bin (the count grid and sample selection stay fused as before; plain
   scatters are byte-identical to the pre-color pipeline), +4 B/cell on the
   wire, and the §4 pyramid's color planes at +8 B/cell.
   *Why mean-of-colors and not colormap(mean value):* the mean color is
   representation-agnostic (categories have no mean value), matches the
   drilled points' downsample exactly (the anti-jarring contract, T3), and
   never claims a data value that isn't there — a mixed red/blue cell reads
   as the purple *blend* the points themselves produce, not as a fictitious
   mid-scale value. The cost, recorded: a mixed cell's color can sit off the
   palette/colormap gamut; the sample overlay and drill-in disambiguate.
   *Rejected:* per-cell max (overweights outliers silently); majority+purity
   (hid minority categories entirely and desaturated toward a count ramp
   that no longer exists). Linear-light averaging is deliberate — sRGB-space
   byte averaging darkens mixes (red+blue → 128-purple instead of the
   physically correct 188-purple).
3. **Categorical channels beyond the palette fold first.** Codes wider than
   the 256-entry LUT bin with `code % len(palette)` — exactly the repeat
   rule the point shader applies — so every point bins with the color it
   draws with, at any cardinality.
4. **Size channel → drop at Tier 2, always say so.** Size has no honest
   per-cell aggregate that isn't just another continuous channel; we ship
   `channels_dropped: true` + `dropped_channels` naming it. Color is *not*
   listed there when it aggregates — `color_agg: "mean"` records the
   transform instead (aggregated ≠ dropped).
5. **Mean-color surfaces need no drill handoff at all:** hue is continuous
   by construction (both sides show the points' colors) and, under rule
   1's physical alpha, so is lightness — the texture composites exactly
   like the marks replacing it. Drilled points therefore enter and exit at
   NATIVE opacity; the entry/exit alpha fades (T2) alone carry the swap,
   and the client ignores `density_val`/`lod_blend` on such traces (the
   wire still carries them — count-only surfaces keep the intensity
   handoff: marks enter at the cell's count-alpha through the same tone
   curve as their texture and ease to native as `lod_blend` → 0, and
   exiting marks re-target it to melt into the ramp).

**Invariant L4 (badge):** any active reduction that drops or transforms a
channel renders a visible "aggregated: mean/…" badge sourced from the spec
(`color_agg`, `dropped_channels`), not from client guesswork. (Client work
item; spec already carries the facts.)

---

## 3. Deterministic sampling (anti-shimmer)

Wherever a representative *subset* is shown (Tier-2 hybrid overlay, future
"sampled" mode for mid-density views):

- **Sampling is a pure function of (row_id, zoom_level).** Use a splittable
  hash (`h = mix64(row_index)`), keep row iff `h < threshold(level)`.
  Thresholds are per-pyramid-level so zooming in only **adds** points
  (`threshold(l+1) ≥ threshold(l)`); the retained set at level l is a subset
  of level l+1. Pan does not reshuffle; zoom never *removes* a previously
  shown point until its tier changes. Implemented as
  `lod.sample_keep_mask(row_ids, level, ...)` using a SplitMix64 row-id hash;
  chart code should normally call `lod.sample_rows_for_target(...)`, which
  turns a target overlay size into that stable mask.
- **No RNG anywhere in the render path.** The engine bans `Math.random()` /
  time-seeded sampling by rule; the smoke's determinism probe (see testing
  suite) renders twice and asserts identical pixels. The Python primitive is
  tested for determinism, row-order independence, and subset monotonicity.
- Category-stratified variant: apply the same hash per category with
  per-category thresholds ∝ sqrt(share), floored at 1, so rare categories
  survive (min-representation rule). Implemented as
  `lod.stratified_sample_keep_mask(...)`; deterministic because the hash is.

This is the datashader/imMens lesson combined: screen-bounded *and* stable.

---

## 4. The Tier-3 tile pyramid (100M–1B points)

Today, every `density_view` re-bins the visible window: O(visible points) per
zoom step. At 100M visible that's ~1s/step — interactive-ish with the
pending-LOD hold, but not 60fps-smooth, and at 1B it's not viable. The
pyramid replaces per-view scans with per-view *tile composition*.

### 4.1 Structure

- **Data-space tiles**, power-of-two levels, 256×256 cells/tile.
  Level 0 covers the full x/y extent with 1 tile; level l has 4^l tiles.
- Each tile stores the channel aggregates per §2: `count` (u32), and for
  channel-bearing traces a mean-color plane — per cell `[r, g, b, a]` as
  linear-light u16 means plus mean straight alpha (u16 scale). Means, not
  sums: 8 B/cell instead of 24+, at the cost of one re-rounding per level
  (≤ 0.5 lsb of u16 per level — recorded, invisible).
- **Build:** one pass over rows bins into the finest level L
  (L ≈ ceil(log4(N / target_points_per_cell / 256²))); levels L-1..0 are 4→1
  reductions (`count`: exact u64 sums saturating to u32; color: exact
  weighted means, weight = child count × child mean alpha — the same
  alpha-weighted average the flat kernel computes over raw points).
  Total cost ≈ 1.33 × one full pass; total size ≈ 1.33 × finest level.
- **Rust owns this** (`tiles.rs`, see rust-engine doc): build_pyramid(),
  tile fetch by (level, tx, ty), append-aware rebuild of dirty tiles.
  Colored pyramids refuse native appends — the batch's colors are unknown to
  the count-only append path and an append can move a continuous channel's
  domain, silently re-coloring every already-binned point — so the caller
  invalidates and the next density view rebuilds lazily (recorded; count-only
  pyramids keep O(rows·levels) increments).

### 4.2 Serving a viewport

```
level  = clamp(round(log2(data_span / view_span)), 0, L)
tiles  = the ≤ ceil(w/256+1) × ceil(h/256+1) tiles intersecting the view
reply  = compose(tiles) → one grid ≤ (screen px) — done kernel-side today,
         client-side (texture atlas) in phase 3
```

- **Pan = tile reuse:** only newly exposed edge tiles ship. The client keeps
  the multi-window density cache it already has (`densityCache` in 45_lod.ts)
  — the pyramid formalizes it into keyed tiles instead of ad-hoc windows.
- **Zoom = adjacent level:** crossfade between level textures is the exact
  crossfade the client already does for density switches (`_densitySwitchPrev`).
- **Below the floor** (view finer than level L): re-bin visible rows via
  `range_indices` + `bin_2d` — O(visible), and visible is small at deep zoom.
  This is today's behavior, now only on the deep-zoom tail where it's cheap.
- **Drill-in unchanged:** when visible_count ≤ budget, ship exact points.
  The pyramid only changes how *aggregated* views are produced.

### 4.3 Truthfulness across levels

Count reductions are exact (sums of sums), so any pyramid level shows the
same counts the raw pass would. Color reductions are exact weighted means of
the stored child means, re-quantized to u16 once per level (≤ 0.5 lsb of
linear-u16 per level; over the 11 levels of the default base that stays
under one displayable sRGB step — recorded here, invisible in practice).
Level choice is recorded per update (`binning: "pyramid-L<l>"`). No level
ever extrapolates.

### 4.4 Memory & residency

- Finest level for 100M points at 16 pts/cell ≈ 6.25M cells ≈ 25 MB (count
  u32) + 50 MB mean-color plane ([u16; 4]/cell). ×1.33 pyramid ≈ 33-100 MB
  kernel-side. Fine. (Shipped shape: 2048² default base ⇒ 22 MB counts +
  45 MB color per colored trace, `pyramid_report_bytes`; huge/out-of-core
  traces build adaptively finer bases — Phase-3 item 7 — and the color plane
  scales with them.)
- 1B points: ~330-660 MB — still kernel-side RAM, but now Tier 3 applies:
  tiles are chunked to disk (Arrow/Parquet row groups per tile, dossier §32),
  LRU-resident under a byte budget, and *only* the ≤ ~12 visible tiles are
  ever needed per frame. The client never holds more than screen-bounded
  textures regardless.
- **Canonical out-of-core (landed).** Independently of the aggregate tiles,
  the *canonical* x/y columns can themselves exceed RAM. On native they are
  backed by a disk `np.memmap` (dossier §27 rule 5): the pyramid build,
  `bin_2d`, `range_indices`, and zone maps scan them straight from disk via the
  OS page cache, so building/serving the pyramid never requires the raw rows to
  be resident. Columns too large to build in RAM are streamed to disk by
  `xy._ooc.MemmapF64Builder`; `tests/test_ooc.py` covers ingest-without-copy and
  screen-bounded density rendering over a memmap-backed scatter.
- **Windowed-exact spatial index (landed).** A disk-backed companion to the
  pyramid for the zoomed-*in* regime, where the pyramid's upsampled floor is
  blocky (its finest cell is kilometres wide over a planet-scale extent).
  Points are pre-sorted into a row-major grid of cells with a cumulative-offset
  header (`osmium-rs`'s `osm-sort`, dossier §32b); `xy._spatial.SpatialIndex`
  reads only the cells a viewport overlaps — one contiguous memmap slice per
  grid row. Cost is O(points in window), so detail *sharpens and cheapens* with
  depth; the cheap offsets-only `window_count` (whole-cell overhang, an upper
  bound) gates the read, then the cells are gathered **once** and the render
  tier keyed on the *actual* in-window count:
  - **≤ `SCATTER_DENSITY_THRESHOLD` in-window → real points** (`binning:
    "spatial-points"`), shipped straight from the index as vertices so deep zoom
    is *crisp individual marks*, not a raster — the out-of-core drill-in the
    canonical rescan can't afford. Position-only: the derived index has no row
    ids or channels (§27), so it is gated to constant-styled traces and a pick
    can't resolve to a canonical row (an empty drill subset makes that explicit —
    exact-or-nothing, §16/§17).
  - **otherwise → exact grid** (`binning: "spatial-exact"`), re-binned via
    `kernels.bin_2d_f32` (f32-input, no f64 widening) at **full screen
    resolution** (one cell per pixel) and uploaded with **nearest-neighbour**
    filtering — no coarser aggregate grid stretched over the viewport, so there
    is neither upscale blur nor pixelation. The upsampled pyramid keeps `linear`
    (smooth aggregate); the wire carries the choice as `density.filter`.

  It engages while `window_count` is under `SPATIAL_EXACT_MAX_POINTS` and yields
  to the instant upsampled pyramid above it. `tests/test_spatial.py` covers cell
  grouping, windowed count/gather, exact-bin parity with a direct `bin_2d`, and
  the points-vs-grid tier decision keyed on the true in-window count.

---

## 5. Smooth transitions (already-shipped mechanics, kept as law)

The transition system was built and debugged in this repo; codifying the
invariants so future kinds don't regress them:

- **T1 — never blank:** a coarser covering representation draws until the
  finer one arrives (density-under-points; broadest-cache fallback).
- **T2 — never hard-cut:** representation changes crossfade (entry fade on
  the aggregate→marks transition only — restarting per refresh reads as
  flashing; exit fade with the "dying" state so buffers outlive the fade).
- **T3 — color-continuous:** the two sides of a transition display the same
  statistic at the boundary. On a mean-color surface BOTH channels are
  continuous by construction — hue because the surface wears the mean point
  color (§2 rule 2), lightness because it composites like the points
  themselves (§2 rule 1) — so marks swap at native opacity with no
  intensity handoff at all (§2 rule 5). Count-only surfaces keep the
  lod_blend count-alpha ramp: the kernel's blend weight (`visible/budget`)
  is only ≈1 when the swap happens at the budget boundary — a fast zoom
  skips levels and lands marks with a mostly-native weight, a visible
  intensity pop at the swap (live-drilldown field capture) — so the
  BOUNDARY is the transition itself, client-side: fresh marks arrive with
  the shown blend seeded at 1 (entering at the aggregate's local
  count-alpha) and ease to the kernel's native weight, and dying/exiting
  marks re-target blend 1 so they melt into the texture as they fade
  (`lodApplyDrill`, `lodBeginDrillExitContinuous`; revives restore the
  native weight via `lodEnterDrillContinuous`).
- **T4 — normalization is eased, never stepped** (exposure-style normMax) —
  count-only surfaces; a mean-color texture's physical alpha is
  max-independent, so it has no normalization to ease.
- **T5 — stale replies die:** seq on view updates, drill_seq on subsets,
  pending-view hold for prefetched drills.
- **T6 — invalid requests do not mutate:** malformed viewport/screen requests
  fail before `enter_drill`, `exit_drill`, cache replacement, or buffer
  version changes. The previous representation remains the authority.
- **T7 — cached textures outlive every live reference:** the multi-window
  density cache (`densityCache`, capped LRU) may free an *evicted* grid's GPU
  texture, but never one still reachable from the trace. `lodDensityPinned`
  pins the active grid, the previous grid, the crossfade source
  (`_densitySwitchPrev`), the last-drawn grid (`_shownDensity`, which becomes
  the *next* crossfade source), and the standalone overview restore point
  (`_homeDensity`). Freeing a still-referenced texture makes the next crossfade
  bind a deleted handle — a hard WebGL error (`bindTexture: … deleted object`)
  that drops the density frame and strands drilled points over a stale surface.
  Every `_drawDensity` also skips a grid whose texture is not `gl.isTexture`, so
  the invariant can never surface as a GL error even if a new reference is added.
- **T8 — a hold cannot outlive its reply:** the pending-view hold that keeps
  drilled marks on screen while a refinement is in flight (T5) is transient by
  contract — it must keep a frame scheduled so it re-evaluates every tick
  (`js/src/45_lod.js` `lodDrawDensityTier`, held branch). If the reply never
  lands (dropped as stale, coalesced away, or never sent — all reachable on the
  live-drilldown transport), `_lodPendingAt` ages past the hold window,
  `lodHoldPendingDrill` releases, and the exit fade restores the aggregate.
  Re-arming only while the view animates was a way the zoom-out "stuck point
  blob" could persist: a settled view with a stranded pending had nothing to
  drive it out of the hold, so the drilled subset stayed painted and the full
  point cloud never returned. (Complements T7, which fixes the same visible
  symptom from the texture-lifetime side.)
- **T9 — the drawn sample describes the displayed window, and only a
  RESOLVABLE window (#225):** a sample overlay draws only when the view it
  would describe could plausibly be points-tier — the overlay's recorded
  window count, scaled by the view's share of its window, fits
  `LOD_DIRECT_POINT_BUDGET` (`lodOverlayResolvable`). Above that, a
  fixed-size sample reads as individual data points at a zoom where real
  points are sub-pixel — sampling above the resolution of the graph
  misrepresents the dataset (the #225 field capture: zooming out from a
  drilled 100M-point cloud brought "individual points" back over the
  aggregate) — and the density surface, which wears the data's own colors
  (§2), stands alone. Interactive `density_view` replies therefore ship NO
  sample at all: the only retained overlay is the first-payload one, which
  doubles as the standalone re-bin worker's CPU source. A KERNEL-ATTACHED
  client never draws it at any zoom (field follow-up): wherever a view is
  resolvable the kernel ships REAL points, and a handful of retained sample
  rows at full alpha there reads as data that isn't. The overlay is the
  standalone (kernel-less) client's fallback — drawn only below the
  resolvability gate, where it is the only point representation that build
  will ever have. For the
  overlays that DO draw, window pairing holds: every sample rides the
  density cache entry it was computed for (`density.overlay`), and each
  frame draws the overlay of the best cached window for the current view
  (`lodSampleForView`, mirroring `lodDensityForView`) — the smallest window
  covering the view wins at full alpha, so points on screen always describe
  the window being displayed. (The pre-pairing client retained one global
  sample and drew it whenever the view merely overlapped its window: a
  drilled window's sample lingered over every later zoom-out as an opaque
  "stuck point blob".) Only a view that NO cached window covers draws a
  partial overlay, faded by the window's share of the view area — full alpha
  at ≥ `LOD_SAMPLE_FADE_COVER_HI` (1/4), hidden at
  ≤ `LOD_SAMPLE_FADE_COVER_LO` (1/32), log-eased between
  (`lodSampleViewAlpha`). The band value is a *composited* opacity target,
  not a per-point alpha: mid-band the window's screen footprint has shrunk
  enough that many points stack per pixel, and compositing k overplotted
  layers of alpha a reads as 1−(1−a)^k — at k≈10 even a=0.2 renders a
  near-opaque slab (a "fading" sample that never looked faded). The
  per-point alpha is solved as a = 1−(1−band)^(1/k), with k estimated from
  the drawn count, mean point footprint, and the window's on-screen area;
  k ≤ 1 degenerates to the band value exactly. Selection, alpha, and the
  resolvability gate are pure functions of (view, cache): every zoom frame
  re-derives them, nothing latches. Overlays die with their evicted cache
  entry (except the home/init overlay, the standalone re-bin worker's
  CPU-side source), and the "sampled n of N" badge reports the overlay
  actually drawn.
- **T10 — the aggregate backdrop is continuous through transitions, and
  retires when the drill settles:** the density texture draws under the
  marks in every TRANSITIONAL drill state — entering, held, dying, exiting —
  so every representation change is a marks-layer fade over a stable
  context, never a full-frame swap or a blank. (Previously marks "owned the
  frame" once their entry fade finished: the backdrop flipped to the blank
  chart background, and interleaved density/points replies during a
  continuous zoom flashed green-texture ⇄ points-on-blank — the
  live-drilldown flicker.) Once a drill is SETTLED inside its window —
  entry fade landed, no exit/hold/death in flight — the backdrop eases out
  (`lodDrillBackdropScale`): the marks are exact for that window, so the
  aggregate adds no information the marks don't already carry, and leaving
  it painted washes exact points with mean color that reads as data
  (field-reported against the mean-color surface). It eases back FAST the
  moment the view leaves the window, a refinement goes pending, or the
  drill dies — so zoom-outs still never blank (T1) and per-reply refreshes
  inside a settled drill never re-flash it. `lodDrawDensityTier` routes
  every branch's backdrop through `lodDrawDensityWithFade`, so
  cached-window crossfades stay continuous while drilled too.
- **T11 — an exited drill is a bounded revive cache:** a drill whose entry
  completed and whose exit fade has finished is retained so a rapid zoom
  back into its window hands the exact marks back with no kernel round-trip
  (the revive hysteresis) — but only while a nearby view could still
  plausibly be points-tier. Once the view outgrows the window past the drill
  budget (the hold's own `visible × area-ratio` estimate vs
  `LOD_DIRECT_POINT_BUDGET × LOD_DRILL_EXIT_FACTOR`), the buffers free on
  that frame with no kernel reply required (`lodDrillOutgrown` in
  `lodDrawDensityTier`) — geometry alone must never strand a drill's GPU
  buffers indefinitely (§27: every GPU buffer is a rebuildable cache).
  Never-entered drills are exempt: they are prefetches en route to their
  window, and the view being far from it is their normal transient state.
  A dying drill (kernel chose density) still frees via the exit fade as in
  T2, independent of geometry.
- **T12 — a zoom inside an exact drill elides the request:** once a points
  reply has shipped its window EXACTLY (`reduction: "none"` — Invariant L2's
  subset IS every point in the window), any requested view contained in that
  window is already answered by the marks on the GPU: the smaller window's
  points are a subset of the shipped ones, so `_scheduleViewRequest` sends no
  `density_view` for that trace and clears its pending markers
  (`lodDrillServesView` in `js/src/45_lod.ts`, re-checked at debounced send
  time so a drill landing or dying mid-debounce flips the decision). The seq
  still bumps, so an in-flight reply for an older, wider view dies stale
  instead of yanking exact marks out from under a view it cannot improve.
  Two things re-arm the request: leaving the window (any edge, same epsilon
  as `_viewInside`), and depth — the shipped geometry is f32, offset-encoded
  around the window midpoint (dossier §16), so once the view span drops below
  `LOD_DRILL_REENCODE_SPAN` (1/256) of the window span on either axis one
  request goes out purely to re-center the encoding (at 2⁻⁸ of the window the
  ~2⁻²⁴ encode quantum is still ≲0.1 px on a 4k-wide plot; the reply's
  re-centered window then re-arms the elision around itself). A dying drill
  never elides — the kernel chose a different representation and the reply
  flow owns that transition. Data changes cannot serve stale marks through
  the elision: streaming append and full payload updates rebuild the GPU
  trace, which drops the drill and with it the elision. Non-exact replies
  (anything but `reduction: "none"`, including replies that don't say) never
  arm it.
- **T13 — full-point windows are padded, aligned, cached, and never
  re-requested:** T12's elision is only as good as the window it can elide
  against, so both ends widen it. *Kernel side*, a points-tier reply ships
  the largest ALIGNED window around the view whose exact count still fits
  the budget (`interaction._padded_drill_window`): bounds snap outward to a
  power-of-two grid over the trace's extent, per dimension
  (`lod.aligned_window`), from a ladder of span targets
  (`DRILL_PAD_TARGETS`, coarsest first, pyramid-count-gated then
  exact-verified), floored at the raw view window. Alignment makes
  consecutive pans resolve to the SAME window — dedupable, cacheable — and
  neighboring windows tile; the padded span is hard-capped per axis
  (`DRILL_PAD_SPAN_CAP`, well under the 1/256 re-encode bound) so the §16
  offset encoding centered on the padded window can always be re-tightened
  by a deeper zoom's re-encode request. Nonlinear-axis traces skip padding
  (raw-space alignment mis-sizes log windows near zero) and keep the exact
  view window. `visible` counts the SHIPPED window; `lod_blend` stays keyed
  on the VIEW's own count — padding widens what ships, not what the user
  sees. *Client side*, a points reply for a new window RETIRES the previous
  exact drill into a bounded per-trace LRU (`g.drillCache`,
  `LOD_POINT_CACHE_WINDOWS`) instead of overwriting its buffers, and so does
  a drill that dies outside its window; any later view covered by a cached
  window promotes it back (`lodPromoteCachedDrill` — alpha-continuous, brush
  mask re-derived locally) with no wire message, so pan ping-pong and
  zoom-out/zoom-in sequences render entirely from the GPU. Cached windows
  obey the live drill's geometry-only memory discipline (T11): outgrown ⇒
  freed on the frame, no kernel reply required (§27). Because promoted
  windows carry retired `drill_seq`s, the kernel keeps a bounded subset
  history (`Trace.drill_history`, `DRILL_HISTORY_KEEP`) so picks against a
  recent retired window still translate exactly; expired seqs drop the pick
  (§16 exact-or-nothing), and data changes clear the history. Finally, an
  identical request never rides the wire twice: a `density_view` within half
  an output texel per edge of the trace's last sent request (gesture-end and
  settle emit sub-pixel twins; a grid shifted below half a texel is the same
  picture) is suppressed — already answered ⇒ nothing to refresh (the reply
  is deterministic for unchanged data; rebuilds reset the memo), still in
  flight ⇒ the trace keeps waiting on the ORIGINAL request's seq and that
  reply is accepted per-trace instead of dying to the global seq race
  (bounded by the same 1200ms window as the T8 hold, so a lost reply can't
  suppress forever).

  The AGGREGATE tier's own traffic is governed by a stronger rule, adopted
  from field feedback on the 100M drilldown (a HAR showed ~2.7 MB
  full-screen grids re-shipped on every pan/zoom step at 200–450% zoom for
  what was the same aggregate with marginally different blur): **the
  aggregate never refines.** Whatever density texture already covers the
  view stands — however blurry — until the view could plausibly resolve
  into REAL points; only then is a round-trip worth anything, and the
  kernel answers it with exact points once the window's count fits the
  budget. Blur at intermediate zooms is an accepted, recorded cost.
  - **The points-band gate** (`lodAggregateStands`): a `density_view` goes
    out only when the estimated in-view count sits within
    `LOD_DIRECT_POINT_BUDGET × LOD_POINTS_REQUEST_BAND`. Two independent
    estimators, LOWER wins (an over-estimate must never hold a view in blur
    when either signal says points could be close): the smallest cached
    density window CONTAINING the view (recorded `visible`, exact for its
    window, area-scaled — seeded by the home texture's first-payload
    count), and the retained deterministic sample counted in-view and
    re-weighted by `visible/n` (`lodSampleViewCount`) — a fixed-rate
    thinning of the whole trace, so it follows the data's ACTUAL
    distribution where area-scaling assumes uniformity and over-estimates
    sparse tails by orders of magnitude (~65 expected sample rows right at
    the band ⇒ ±12% noise; kernel-attached clients never DRAW the sample,
    T9 — estimating from it CPU-side is what it is retained for). A trace
    with no recorded counts anywhere always requests. A fresh grid for an
    already-cached window supersedes its unpinned twin
    (`lodRememberDensity` dedupe), so the gate always reads current facts.
    *Display side — the stepped ladder:* the aggregate sharpens in
    QUANTIZED steps, never per view. While standing, the one density
    request allowed is the next LADDER STEP window
    (`lodAggregateStepWindow`): the view snapped outward to a
    power-of-`LOD_AGG_STEP_FACTOR` block grid over the data extent, per
    axis, at most `LOD_AGG_STEP_MAX` steps below home, requested only when
    every covering texture is coarser than the step
    (`LOD_AGG_STEP_SLACK`). Quantization makes step windows pan-stable and
    dedupable — every view in a region resolves to the SAME window, pans
    inside a step repaint nothing, revisits hit the cache — so a zoom sees
    at most `LOD_AGG_STEP_MAX` smooth-to-smooth swaps before points, and
    worst-case softness is bounded (≈ `LOD_AGG_STEP_FACTOR`× stretch per
    axis) instead of unbounded home-stretch. Per-view refinement was the
    recorded failure mode twice over: multi-MB re-ships per pan/zoom step
    (the HAR), and fresh textures per view reading as jumping. A step
    reply is the ONE density reply that may repaint a covered view
    (matched against the marked request window, `g._stepReqWin`); every
    other covered reply — the band probes above all — lands as a
    facts-only cache entry (window + exact count,
    `lodRememberDensityFacts`) that recalibrates this gate: the band's
    exact grids have a hard speckled character (sparse cells at the
    points' own §2 alpha), and repainting the smooth surface with one per
    probe read as jumping between zoom levels (field capture). A reply for
    an UNCOVERED view still applies — silence must never blank a frame
    (T1) — and standalone clients apply everything (their re-binned grids
    are the only refinement they have). Recorded trade-off: inside the
    points band the raw-view probe takes the single request slot, so a
    view can briefly outrun its ladder step until points land.
  - **Source-clamped grids:** the transition-band replies that do go out
    stay cheap — a pyramid-served reply never composes more cells than the
    finest level resolves under the window
    (`interaction._pyramid_source_shape`, `ceil(base·frac)+1` per axis); a
    full-screen grid of upsampled base cells is the same picture at several
    times the bytes, and the client's texture filtering reproduces the
    upscale. Exact/spatial grids (true full-detail bins) keep screen
    resolution.
  - **One texture per frame (recorded reversal):** a fine-over-broad detail
    layer — drawing the smallest cached texture overlapping the view on top
    of the broad backdrop during pans — was tried and REVERTED: density
    textures alpha-composite, so the overlap double-counts opacity, and
    each window's texture is baked against its own eased normMax, so the
    seam is also a brightness step (field capture: a stale darker
    rectangle). Doing it right requires the backdrop scissored out of the
    detail region plus a shared normalization across cached textures;
    under the never-refines rule the case barely arises, so the tier draws
    one texture per frame.

Any new tiered kind must state how it satisfies T1–T13 in its chart-kind
contract entry before it lands.

---

## 6. Implementation plan

**Phase 1 — channel-truthful density (kernel+client)**
1. **Done:** `bin_2d_mean_color` kernel — per-cell count + alpha-weighted
   linear-light color sums in one pass, straight-alpha RGBA8 mean-color grid
   out (native Rust core; integer tables + integer sums, deterministic for
   any thread count and across platforms). Color source is either per-point
   LUT indices + a ≤256-entry RGBA8 LUT (continuous quantizes to the
   client's 256 texels; categorical passes codes, wide codes fold modulo the
   palette) or per-point straight RGBA8 (`direct_rgba`) —
   `channels.resolve_bin_colors` maps every channel mode onto one of the two.
2. **Done:** mean-color planes wired through the initial emit
   (`_payload._density_trace_spec`), `density_view` (exact and pyramid
   paths), the static SVG/PNG exporters, and the standalone re-bin worker;
   DENSITY_FS gained the `u_meanColor` branch (premultiplied RGBA8 texture,
   the §2 rule-1 physical alpha baked at upload so bilinear filtering
   weights color by coverage); mean-color drills swap at native opacity
   with no intensity handoff (§2 rule 5; count-only drills keep it).
   The colorbar for a continuous channel now stays on density traces — the
   surface really shows the channel's colors.
3. Legend/badge rendering from spec facts (`color_agg`, `dropped_channels`)
   remains a client work item; smoke probes for mean-cell color correctness
   ship (`render_smoke_nonumpy.py` `meancolor`, `abi_smoke.py` mean-color
   checks, `tests/test_density_mean_color.py` NumPy oracle).

**Phase 2 — deterministic sampling utilities**
4. **Done:** `lod.sample_keep_mask(row_ids, level)` SplitMix64 sampler +
   `lod.stratified_sample_keep_mask(...)`, plus
   `lod.sample_rows_for_target(...)` for target-sized overlays; tests assert
   row-order independence, rare-category floors, validation,
   dtype-preserving saturation, and subset-monotonicity across levels and
   viewport narrowing.
5. **Revised by #225 (resolvability gate, T9):** interactive density replies
   no longer ship samples at all — a fixed-size sample above the drill budget
   reads as individual data points at a zoom where real points are sub-pixel,
   and the mean-color surface (§2) is the truthful stand-alone
   representation. The retained first-payload sample remains (the standalone
   re-bin worker's CPU source) and draws — with its "sampled n of N" badge —
   only when the estimated in-view count fits the direct budget: kernel mode
   ships real points before that, so the hybrid look is transient at most;
   standalone exports surface it once a zoom resolves it; datasets under the
   budget keep it everywhere. The deterministic-sampling utilities (item 4)
   stay: the first-payload overlay and any future resolvable-tier subset are
   built from them.

**Phase 3 — pyramid (build + serve shipped; client cache and bench gate open)**
6. **Done (count + mean-color planes):** `src/tiles.rs` builds a square count
   pyramid over the trace's full data bounds — finest level is
   `PYRAMID_BASE_DIM`² (2048², `python/xy/config.py`), each coarser level an
   exact 4→1 u64 sum saturating to u32, so every level conserves total count.
   Channel-bearing traces build the §4.1 mean-color planes alongside
   (`xy_pyramid_build_color`, one fused scan — fan-out gated by the
   points-per-cell ratio and capped at 4 workers, ~170 MB transient
   accumulator each; +8 B/cell stored, ~45 MB/colored trace at the default
   base, reported by `pyramid_report_bytes`) and serve them with
   `xy_pyramid_compose_color`,
   whose count grid is bit-identical to `xy_pyramid_compose`. C ABI is
   `xy_pyramid_build` / `xy_pyramid_build_color` / `xy_pyramid_append` /
   `xy_pyramid_count` / `xy_pyramid_compose` / `xy_pyramid_compose_color` /
   `xy_pyramid_free` (no per-tile fetch entry point; composition happens
   kernel-side). Handles are slab indices behind a mutex, cached per trace
   and built lazily by `interaction._ensure_pyramid` on the first density
   view at ≥ `PYRAMID_MIN_POINTS` (2,000,000), released by a weakref
   finalizer; colored pyramids refuse appends and rebuild lazily (§4.1).
7. **Done:** `density_view` estimates the window with `pyramid_count` and
   serves it with `pyramid_compose` when that estimate sits safely above the
   drill threshold; `compose` picks the coarsest level that still meets the
   render resolution. Its `max_upsample` bound is 2× for in-RAM traces (so
   below-floor and near-drill windows fall through to the exact
   `range_indices` + `bin_2d` path), but unbounded for out-of-core / huge
   traces, which are served upsampled from an adaptively finer finest level
   (`~sqrt(N/target)`, capped `PYRAMID_MAX_DIM`) rather than rescanned. Level
   and mode are recorded per update as `binning: "pyramid-L<l>[-upsampled]"`.
   When *downsampling* (the coarsest adequate level packs 1–2 source cells per
   output bin), `compose` **area-weights** each source cell across the bins its
   extent overlaps rather than assigning it to the bin under its center;
   center-only assignment handed adjacent bins 1 vs 2 cells apiece — a beat
   against the output grid that showed as vertical banding in interim aggregate
   frames while zooming a dense cloud (#153). Weights within a snap tolerance of
   a bin edge collapse to one bin, so cell-aligned windows stay bit-exact. When
   *upsampling*, every output pixel instead pulls the source cell beneath it
   (filled blocks, no sparse "grid of points").
   Traces on a nonlinear (log/symlog) axis skip the pyramid entirely — its
   raw-space levels cannot compose a scale-coordinate grid (dossier §28) —
   and always take the exact path.
   When an out-of-core trace also carries a Tier-3 **spatial index**
   (`_spatial.SpatialIndex`, built by `osmium-rs osm-sort`), a window the
   pyramid could only serve `-upsampled` is instead answered exactly from just
   its in-window points: drilled to crisp real points when the count fits the
   direct budget, else binned to a **full-screen-resolution** grid served with
   nearest-neighbour filtering (`binning: "spatial-exact"`, `filter: "nearest"`)
   — no interpolation blur. Gated by an offsets-only `window_count` upper bound
   (`SPATIAL_EXACT_MAX_POINTS`); wider windows keep the instant upsampled pyramid.
   Color-channelled traces skip this tier entirely: the index is position-only
   (§27), so it can neither ship channels with a points drill nor bin the §2
   mean-color plane — the upsampled *colored* pyramid grid stays (blurry but
   truthful) rather than flipping to a count-only surface (recorded, dossier
   §28 table).
8. Client: tile-keyed cache replaces window-keyed `densityCache` (same
   eviction, same crossfades). Still pending — `js/src/45_lod.ts` keys the
   cache by density window, and no client code reads the served level.
9. Bench gate: 100M pan p95 < 16ms kernel time, zoom step < 50ms, memory
   within 1.5× finest level.

**Phase 4 — Tier-3 residency (~2 wks, after Arrow ingest)**
10. Tile spill/load under byte budget; zone-map-pruned tile index for
    unordered scatter (bucket at ingest, dossier §32b).

Exit criteria for the headline claim: 100M-point colored scatter — pan/zoom
never blanks, never shimmers, mean-color cells match a NumPy oracle, drill-in
to exact points under 200k visible, all reductions visible in spec + badge.
