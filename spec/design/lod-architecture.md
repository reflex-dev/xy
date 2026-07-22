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
| 2 | Density / aggregate surface | mean-point-color texture, count as alpha (§2) | O(screen) texels | shipped (scatter) |
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
| scatter | points | — (unordered decimation lies, §28) | mean-color density grid (§2; count planes + color planes, §4 below) | drill-in ships exact visible points + channels (shipped) |
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
density surface wears the data's own colors; count drives only the alpha.**
A cell's color is what the eye would see if every one of its points were
drawn sub-pixel — the physically downsampled image — so the aggregate view
and the point view are two magnifications of the same picture, not two
different charts. More points → deeper (more opaque) color; fewer points →
lighter; the color itself always comes from the represented points.

1. **Count is always channel 0, and it is the ALPHA channel.** The count
   grid ships log-tone-mapped (`buf` + `max`, log-u8) and drives opacity
   exclusively. Color rides on top of count, never instead of it —
   otherwise sparse-but-extreme cells look as important as dense ones. No
   shipped path colormaps counts anymore (the client keeps a count→LUT
   fallback solely for hand-built/legacy count-only specs).
2. **Per-point colors → per-cell alpha-weighted MEAN of the *resolved*
   colors, averaged in linear light.** One law for every channel mode —
   continuous (colormapped value), categorical (palette color), and
   `direct_rgba` alike: each point contributes the exact sRGB color it draws
   with, weighted by its straight alpha, summed in linear light (integer
   pipeline: checked-in sRGB⇄linear-u16 tables, u64 sums — bitwise
   deterministic across thread counts and platforms), then quantized back to
   sRGB. Ships as a `w*h*4` straight-alpha RGBA8 plane (`rgba`, mean color +
   mean point alpha) with `color_agg: "mean"` recorded; displayed alpha =
   count tone-curve × mean point alpha. A cell of one point shows that
   point's exact color; an all-invisible (alpha-0) cell never invents one.
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
5. **The drill handoff is intensity-only now:** hue is continuous by
   construction (both sides show the points' colors), so freshly drilled
   points arrive in their native colors and only their opacity hands off —
   entering at the cell's count-alpha (`density_val` through the same tone
   curve as the texture) and easing to native opacity as `lod_blend` → 0.
   The same rule runs outbound: exiting marks re-target the aggregate's
   count-alpha and melt into a surface that already matches their hue.

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
- **The overlay's size is a pure function of the visible count**
  (`lod.density_sample_target`). A flat target made the drill boundary a
  cliff: one zoom step swapped ~8k sampled points for up to `budget` exact
  ones (live-drilldown field report). The per-view target is
  `budget² / visible`, floored at `DENSITY_SAMPLE_TARGET` and capped at the
  visible count, so the drawn point count is continuous through the tier
  swap (T2's no-hard-cut contract extends to *how many* marks are on screen)
  while far zoom-outs keep the cheap payload-bounded overlay — the ramp is
  active only between `budget` and `budget²/base` visible (~200k–4.9M at the
  defaults) and its payload is bounded by the budget, i.e. by what the drill
  itself would ship. Categorical overlays cap the ramp at `budget/√k`: the
  sqrt-share rule keeps ≈ `target·√k` rows for k balanced categories (the
  same Cauchy–Schwarz bound that sizes kernel capacity), so the stratified
  overlay also approaches — never exceeds — the budget. Because the retained
  fraction (`target/visible`) rises monotonically as the visible count
  falls, subset monotonicity above is preserved: zooming in only adds
  points. Every reply records the target it used (`sample.target`) — §28.

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
  kernel-side. Fine. (Shipped shape: fixed 2048² base ⇒ 22 MB counts +
  45 MB color per colored trace, `pyramid_report_bytes`.)
- 1B points: ~330-660 MB — still kernel-side RAM, but now Tier 3 applies:
  tiles are chunked to disk (Arrow/Parquet row groups per tile, dossier §32),
  LRU-resident under a byte budget, and *only* the ≤ ~12 visible tiles are
  ever needed per frame. The client never holds more than screen-bounded
  textures regardless.

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
  statistic at the boundary. Hue is continuous *by construction* — the
  aggregate surface wears the mean point color (§2), so marks and texture
  agree on color at every zoom — and intensity hands off via the lod_blend
  count-alpha ramp. The kernel's blend weight (`visible/budget`) is only ≈1
  when the swap happens at the budget boundary — a fast zoom skips levels
  and lands marks with a mostly-native weight, a visible intensity pop at
  the swap (live-drilldown field capture). The BOUNDARY is therefore the
  transition itself, client-side: fresh marks arrive with the shown blend
  seeded at 1 (entering at the aggregate's local count-alpha) and ease to
  the kernel's native weight, and dying/exiting marks re-target blend 1 so
  they melt into the texture as they fade (`lodApplyDrill`,
  `lodBeginDrillExitContinuous`; revives restore the native weight via
  `lodEnterDrillContinuous`).
- **T4 — normalization is eased, never stepped** (exposure-style normMax).
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
  live-drilldown transport), `_lodPendingAt` ages past the hold window
  (`LOD_PENDING_HOLD_MS`), `lodHoldPendingDrill` releases, and the exit fade
  restores the aggregate. Re-arming only while the view animates was a way the
  zoom-out "stuck point blob" could persist: a settled view with a stranded
  pending had nothing to drive it out of the hold, so the drilled subset stayed
  painted and the full point cloud never returned. (Complements T7, which fixes
  the same visible symptom from the texture-lifetime side.)
  The hold engages for ANY fresh pending refresh whose view still overlaps the
  drill window — zoom-outs past the drill budget included. The exact marks are
  the previous zoom level's content, and holding them until the right-sized
  reply lands is one transition; exit-fading them immediately dropped the
  frame to a coarser cached texture plus the home/initial overview sample and
  then transitioned AGAIN when the reply landed — the zoom-out "flash of the
  initial view" (live-drilldown field report). The earlier gate (pending view
  centered in the window and estimated-visible within the drill budget) made
  the hold refine-only, so every real zoom-out took the double transition. A
  reply always retires the hold: a density reply marks the drill dying and the
  exit fade runs over the fresh texture (T2), a points reply refreshes the
  marks in place; the age-out above bounds a stranded pending, and a pending
  view fully clear of the window (a far pan) never holds — marks clipped
  entirely off screen hold nothing.
- **T9 — the drawn sample describes the displayed window:** the deterministic
  point sample shipped with an exact-scan density reply represents *its*
  window only, so every sample overlay rides the density cache entry it was
  computed for (`density.overlay`; replies that omit a sample — pyramid and
  integral-image zoom-out paths, Phase 2 item 5 — simply add no overlay to
  their entry). Each frame draws the overlay of the best cached window for
  the current view (`lodSampleForView`, mirroring `lodDensityForView`): the
  smallest window covering the view wins at full alpha, so a deep zoom-out
  falls back through the cache to the HOME sample and the full point cloud
  returns — points on screen always describe the window being displayed.
  (The pre-pairing client retained one global sample and drew it whenever
  the view merely overlapped its window: a drilled window's sample lingered
  over every later zoom-out as an opaque "stuck point blob", pinned by a
  live-drilldown wire capture — the blob's extent matched the last
  sample-bearing reply's window exactly while the density surface kept
  updating under it.) Only a view that NO cached window covers draws a
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
  k ≤ 1 degenerates to the band value exactly. Selection and alpha are pure
  functions of (view, cache): every zoom frame re-derives them, nothing
  latches. Overlays die with their evicted cache entry (except the home/init
  overlay, the standalone re-bin worker's CPU-side source), and the
  "sampled n of N" badge reports the overlay actually drawn.
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

Any new tiered kind must state how it satisfies T1–T11 in its chart-kind
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
   count tone-curve baked into alpha at upload so bilinear filtering weights
   color by coverage); the drill handoff became intensity-only (§2 rule 5).
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
5. **Done for exact density views:** hybrid scatter mode renders density plus
   deterministic sampled exact points, with a visible "sampled n of N" badge.
   Pyramid-served density views still need tile-aware sample overlays so the
   same anti-shimmer contract holds without rescanning raw rows. Until they
   exist, a sample-less reply's window carries no overlay of its own and the
   T9 window pairing serves the best cached window's sample instead (the
   home overlay above all, so zoom-outs keep representative points), bounded
   by the coverage fade when nothing covers the view.

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
   render resolution and refuses beyond `MAX_UPSAMPLE` (2×), so below-floor
   and near-drill windows fall through to the exact `range_indices` +
   `bin_2d` path. Level is recorded per update as `binning: "pyramid-L<l>"`.
   Traces on a nonlinear (log/symlog) axis skip the pyramid entirely — its
   raw-space levels cannot compose a scale-coordinate grid (dossier §28) —
   and always take the exact path.
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
