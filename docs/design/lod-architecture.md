# LOD / Drilldown Architecture — Tier 0/1/2/3

**Status:** design + implementation plan. Supersedes nothing — this refines
dossier §5/§10/§16/§17/§22/§28 into a buildable spec, grounded in what already
ships (`python/fastcharts/lod.py`, `js/src/45_lod.js`, `interaction.py`,
kernels ABI v3). The whole FastCharts claim rests on one sentence:

> **Large data stays truthful and interactive.**

Truthful means: nothing drawn implies data that doesn't exist, nothing that
exists is silently hidden, and every reduction is recorded in the spec (§28).
Interactive means: pan/zoom stays inside the §17 frame budget at any N.

---

## 1. The tier ladder (per-kind, not global)

A **tier is a property of a (trace, viewport) pair**, never of a dataset:
`tier = f(visible_count, mark_pixel_area × overdraw)` (§5). Implemented today
for scatter (drill-in/out with hysteresis); this doc extends the same rule to
every kind.

| Tier | Name | Representation | Cost model | Status |
|---|---|---|---|---|
| 0 | Direct | every visible mark, exact | O(visible) verts | shipped (all kinds) |
| 1 | Shape-preserving reduction | per-pixel-column aggregate that IS the mark's meaning (M4 for lines; OHLC-bucket for candles when finance returns; max-bin for bars) | O(px) verts | shipped (line) |
| 2 | Density / aggregate surface | colormapped count (+channel) texture | O(screen) texels | shipped (scatter) |
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
| scatter | points | — (unordered decimation lies, §28) | density grid (+ channel aggregates, §4 below) | drill-in ships exact visible points + channels (shipped) |
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
`python/fastcharts/lod.py`:

- `ViewportRequest.from_client(...)` normalizes flipped ranges, rejects
  non-finite bounds, and clamps hostile/tiny screen dimensions before any
  kernel, cache, or trace drill-state mutation sees them.
- `plan_view_lod(...)` records the direct-vs-aggregate decision, hysteresis,
  screen-bounded grid shape, `mode`, `tier`, `visible`, and `reduction`.
- `EncodedColumn`, `encode_f32_values(...)`,
  `encode_window_xy_columns(...)`, `add_window_xy(...)`, and
  `BufferWriter.add_encoded(...)` are the shared geometry wire primitive: f64
  data-space values become finite f32 buffers plus `{offset, scale, len}`
  metadata in exactly one place.
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
lying is the hard part (§5-F5). Rules, per channel mode:

1. **Count is always channel 0.** The density surface's luminance/alpha
   encodes count (log tone-mapped, shipped). Any additional channel rides on
   top of count, never instead of it — otherwise sparse-but-extreme cells
   look as important as dense ones.
2. **Continuous channel → per-cell MEAN, displayed only with count ≥ floor.**
   Ship a second grid `sum(channel)`; client computes mean = sum/count in the
   shader. Cells under a count floor (default 1) render count-only — a mean
   of one point is exact, a mean of zero is a lie.
   *Rejected:* per-cell max (overweights outliers silently). Max is offered as
   an explicit `agg="max"` the user must opt into, and the legend then says
   "max per cell" (recorded, §28).
3. **Categorical channel → per-cell MAJORITY + purity.** Ship two grids:
   `argmax(category)` (palette index) and `purity = max_count/count`.
   The shader desaturates toward the count ramp as purity → 1/k, so a
   50/50 cell doesn't masquerade as solidly category A. This is the honest
   version of datashader's `count_cat` composite.
   Categories >256 already warn at ingest (LUT width); majority-of-256 is
   fine because the palette itself caps there.
4. **Size channel → drop at Tier 2, always say so.** Size has no honest
   per-cell aggregate that isn't just another continuous channel; we already
   ship `channels_dropped: true`. Keep that; render the legend badge from it.
5. **The drill handoff already solves re-entry:** freshly drilled points wear
   the density ramp by local log-density (`lod_blend`), easing to native
   channels as the window shrinks — the same rules make the *outbound*
   transition honest because both endpoints display the same statistics.

**Invariant L4 (badge):** any active reduction that drops or transforms a
channel renders a visible "aggregated: mean/majority/…" badge sourced from
the spec, not from client guesswork. (Client work item; spec already carries
the facts.)

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
- Each tile stores channel-aggregate grids per §2: `count`, and per channel
  `sum` (continuous) or `argmax+purity` (categorical) — f32 planes.
- **Build:** one pass over rows bins into the finest level L
  (L ≈ ceil(log4(N / target_points_per_cell / 256²))); levels L-1..0 are 4→1
  reductions (`count` sums; `sum` sums; majority re-argmaxes from summed
  per-category counts — which requires keeping per-category counts at build
  time for the top-k categories, k ≤ 8, "other" bucketed; recorded).
  Total cost ≈ 1.33 × one full pass; total size ≈ 1.33 × finest level.
- **Rust owns this** (`tiles.rs`, see rust-engine doc): build_pyramid(),
  tile fetch by (level, tx, ty), append-aware rebuild of dirty tiles.

### 4.2 Serving a viewport

```
level  = clamp(round(log2(data_span / view_span)), 0, L)
tiles  = the ≤ ceil(w/256+1) × ceil(h/256+1) tiles intersecting the view
reply  = compose(tiles) → one grid ≤ (screen px) — done kernel-side today,
         client-side (texture atlas) in phase 3
```

- **Pan = tile reuse:** only newly exposed edge tiles ship. The client keeps
  the multi-window density cache it already has (`densityCache` in 45_lod.js)
  — the pyramid formalizes it into keyed tiles instead of ad-hoc windows.
- **Zoom = adjacent level:** crossfade between level textures is the exact
  crossfade the client already does for density switches (`_densitySwitchPrev`).
- **Below the floor** (view finer than level L): re-bin visible rows via
  `range_indices` + `bin_2d` — O(visible), and visible is small at deep zoom.
  This is today's behavior, now only on the deep-zoom tail where it's cheap.
- **Drill-in unchanged:** when visible_count ≤ budget, ship exact points.
  The pyramid only changes how *aggregated* views are produced.

### 4.3 Truthfulness across levels

Reductions are exact (sums of sums; majority from kept per-category counts),
so any pyramid level shows the same statistics the raw pass would — modulo
the "other" bucket for tail categories, which the spec records
(`categories_bucketed: k`). Level choice is recorded per update
(`pyramid_level`). No level ever extrapolates.

### 4.4 Memory & residency

- Finest level for 100M points at 16 pts/cell ≈ 6.25M cells ≈ 25 MB (count
  f32) + 25 MB/channel. ×1.33 pyramid ≈ 33-66 MB kernel-side. Fine.
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
  statistic at the boundary (lod_blend density-ramp handoff).
- **T4 — normalization is eased, never stepped** (exposure-style normMax).
- **T5 — stale replies die:** seq on view updates, drill_seq on subsets,
  pending-view hold for prefetched drills.
- **T6 — invalid requests do not mutate:** malformed viewport/screen requests
  fail before `enter_drill`, `exit_drill`, cache replacement, or buffer
  version changes. The previous representation remains the authority.

Any new tiered kind must state how it satisfies T1–T6 in its chart-kind
contract entry before it lands.

---

## 6. Implementation plan

**Phase 1 — channel-truthful density (kernel+client, ~1 wk)**
1. `bin_2d_channels` kernel: count + sum(channel) [+ top-k category counts]
   in one pass (native Rust core).
2. Wire mean/majority+purity grids through `density_view` and the initial
   emit; extend DENSITY_FS to blend channel color over the count ramp with
   the purity desaturation; count-floor uniform.
3. Legend/badge rendering from spec facts; smoke probes: mean-cell color
   correctness, purity desaturation, badge presence.

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
   same anti-shimmer contract holds without rescanning raw rows.

**Phase 3 — pyramid (~2-3 wks)**
6. `src/tiles.rs`: pyramid build + tile fetch (C ABI: `fc_pyramid_build`,
   `fc_pyramid_tile`); Python `Pyramid` cache keyed per trace; build lazily
   on first Tier-2 entry above a size threshold (recorded).
7. `density_view` serves from pyramid when present (level select + compose);
   below-floor re-bin via `range_indices`.
8. Client: tile-keyed cache replaces window-keyed `densityCache` (same
   eviction, same crossfades); `pyramid_level` in updates.
9. Bench gate: 100M pan p95 < 16ms kernel time, zoom step < 50ms, memory
   within 1.5× finest level.

**Phase 4 — Tier-3 residency (~2 wks, after Arrow ingest)**
10. Tile spill/load under byte budget; zone-map-pruned tile index for
    unordered scatter (bucket at ingest, dossier §32b).

Exit criteria for the headline claim: 100M-point colored scatter — pan/zoom
never blanks, never shimmers, mean-color cells match a NumPy oracle, drill-in
to exact points under 200k visible, all reductions visible in spec + badge.
