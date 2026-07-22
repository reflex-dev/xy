# Large-Data Performance & Memory Audit - 2026-07-22

Scope: the full large-N data path — Rust core (`src/`), Python layer
(`python/xy/`), and the TypeScript render client (`js/src/`) — audited
for time and resident-memory costs that scale with point count, against the
§2/§27 targets. This was a source audit plus measured kernel work; browser
measurements were not run in this pass (the audit sandbox has no npm/PyPI
access), so client findings below are code-verified but not yet profiled.

Headline: the hot paths already deliver the design. Ingest of contiguous
float64 is zero-copy through ctypes; a 10M-point density scatter makes **zero
full-size copies** from user array to wire bytes; heavy reductions run in
parallel AVX2-dispatched Rust; LOD tiers are computed on demand, not retained;
the widget transport is binary with no join copy. The findings are therefore
second-tier: conditional paths (categorical/object dtypes, animation keys,
hover fallbacks) and residual serial kernels. Three kernel findings were fixed
in this audit; the rest are recorded as a ranked backlog.

## Fixed in this audit (measured, bit-identical)

Method: interleaved A/B (min/median of 7 alternating runs) of the pre- and
post-change `libxy_core.so` on the same process and buffers, 10M points,
4-core sandbox; the parallel wins scale with cores (E5 caps at 18 workers).
Outputs were verified bit-identical via a SHA-256 digest over ~60 cases per
kernel (boundary sizes, NaN placement, exact-edge values, undersized
capacity), plus the 103 in-crate tests and `scripts/abi_smoke.py` (121
checks). No C-ABI signature changed; `ABI_VERSION` is untouched.

### XY-PERF-2026-01: `histogram2d` was fully serial — 3.75× (4 cores)

`kernels::histogram2d_into` (the irregular-edges compatibility path behind
`xy_histogram2d`) scanned on one core while the uniform-grid path
(`histogram_uniform_impl`) fanned out. 10M points into a 100×100 grid:
175 ms → 47 ms.

Fix: the **unweighted** case now uses per-worker u64 grids with an
integer-sum merge under the same grid-aware fan-out cap as `bin_2d`
(`bin_2d_threads`), which is bit-identical to the serial pass for any thread
count. The **weighted** case deliberately stays serial: f64 accumulation is
order-dependent, and a per-thread merge would make results vary with core
count (§21 determinism). Recorded here so nobody "fixes" the weighted path
without a thread-count-invariant summation scheme.

### XY-PERF-2026-02: `is_sorted_f64` was a serial full scan — 2.97× (4 cores)

The line/area sorted-ingest predicate (§28) ran `windows(2).all(...)` on one
core — a full 800 MB scan at 100M points, paid on every line ingest whose
data is actually sorted (the common case; unsorted data early-exits). 10M
sorted: 8.9 ms → 3.0 ms.

Fix: overlapping-segment fan-out (each worker checks its boundary pair, so
coverage is exact), with a shared relaxed `AtomicBool` polled every 32k pairs
to propagate the early exit. The pair-AND is order-independent, so the result
is exact for any thread count.

### XY-PERF-2026-03: sampling ABIs triple-handled the selected rows — 1.22×

`sample_range_indices` and the fused `bin_2d_sample_range` built per-worker
`Vec<u32>` selections (necessary — counts are data-dependent), concatenated
them into a second selection-sized `Vec`, and then the ABI shell copied that
into the caller's NumPy buffer: one transient allocation plus two extra
full passes over up to N u32 per call. At a 50% keep fraction over 10M rows
that was a 20 MB transient and 19 ms → 15 ms.

Fix: `write_selected_chunks` copies each worker's chunk directly into the
caller buffer at its prefix offset (fanning the disjoint copies out above the
512k threshold), and the kernels return the exact required length without
writing when capacity is insufficient — same two-phase capacity protocol,
one less staging buffer (§27). The stratified samplers keep their owned
result because the rare-category floor merge sorts/dedups after selection;
their selections are target-bounded (~`DENSITY_SAMPLE_TARGET`), so the concat
there is O(sample), not O(N).

## Verified-strong (no action needed — protect these)

- **Zero-copy ingest and identity dedup**: contiguous f64 NumPy input is
  aliased, not copied (`columns.py`); N traces over one array hold it once.
- **Density tier ships O(screen)**: 10M-point scatter → 768 KB wire payload,
  no N-sized buffer copied, encoded, or joined (`_payload.py`).
- **ctypes seam**: raw-address pointers, caller-allocated outputs, no
  per-call NumPy copies (`_native.py`); kernels borrow, never clone inputs.
- **Client upload**: payload columns land as typed-array views and go
  straight to `gl.bufferData` — no slice, no copy (`50_chartview.ts`
  `_columnView`/`_upload`); scatter hover is O(1) GPU picking.
- **Bounded caches**: client density cache (8, pinned-safe eviction), lazy
  GC-tied Tier-3 pyramid, no Python payload cache.

## Backlog — ranked follow-ups (not implemented here)

### High

1. **Object-dtype categorical colors factorize in pure Python**
   (`channels.py:266`). The native factorizer is tried only for `U`/`S`/`b`
   dtypes; a pandas string/category column arriving as object dtype (the
   common real-world case) pays ~2 Python-level passes over N plus an
   N-entry label list — seconds and hundreds of MB transient at 10M rows.
   Fix: coerce object string arrays to fixed-width once (C-level
   `astype("U")`-shape conversion) so the existing parallel Rust factorizer
   applies, preserving `category_label` canonicalization for the mixed-object
   remainder. Needs careful parity tests on label semantics.
2. **Client hover fallback is O(N) per pointer-move for line/bar/rect traces**
   (`50_chartview.ts:4494` `_nearestCpuIndex`, `_barHover`, `_rectHover`).
   Only points draw into the pick FBO; a direct 1M-point line linear-scans
   every vertex on every `pointermove`. Fix: binary-search x (line ingest
   sorts x) and a sorted position index for bars/rects; linear fallback only
   while a transition animation is interpolating positions.

### Medium

3. **Animation `key=` encoding hashes all rows even when discarded**
   (`components.py:3629`). Per-row Python `blake2s` over N rows, then
   `_transition_entry` falls back to `snap:key-limit` above
   `MAX_ANIMATION_MATCH_ROWS` (200k) and throws the digests away. Fix:
   short-circuit when the fallback is certain (mind duplicate-key error
   semantics), and/or hash fixed-width key buffers natively.
4. **Direct-tier traces retain f32 wire buffers for the widget lifetime**
   (`widget.py:55`, `_payload.py:154`). A near-ceiling direct scatter
   (500k–2M pts) holds f64 canonical + f32 wire simultaneously (~24 B/pt)
   so notebook reopen can re-sync. Fix: rebuild-on-reopen from canonical, or
   drop after confirmed sync; must not break offline re-display. Density
   traces are unaffected (screen-bounded buffers).
5. **Tier/drill GPU buffers re-specified with `bufferData` + `STATIC_DRAW`
   on every interactive update** (`54_kernel.ts:294`, `45_lod.ts:239`).
   Orphans and reallocates driver storage per zoom settle (~800 KB per axis
   per drill refresh). Fix: `DYNAMIC_DRAW` + `bufferSubData` when the size
   fits, orphan only on growth (the `_lineDash` path already models this).
6. **Cached density tiers retain their CPU f32 grids** (`45_lod.ts:508`,
   cache depth 8). Only the active grid (tone-map animation) and
   `_homeDensity` (standalone rebin) need CPU copies; cached crossfade
   entries need only their texture. Tens of MB per density-heavy trace at
   high DPI. Fix: null `.grid` on non-active cached entries.
7. **General (>256-unique) factorization is serial**
   (`kernels.rs` `factorize_fixed_into`): the compact-u8 path fans out with
   probe-prefix + per-worker codebooks; the high-cardinality `HashMap` path
   does not. Generalize the same first-seen merge; the u8 path is the
   template.
8. **`select_polygon` runs ray-casting as a Python loop over polygon edges**
   (`interaction.py:234`): up to 2048 edge passes × candidate rows, each
   allocating candidate-sized temporaries. Fix: a `xy_polygon_contains`
   kernel taking the polygon once (easy parity test).

### Low / bounded

9. **Streaming append rebuilds zone-map arrays via 8 `np.concatenate` per
   call** (`columns.py:169`) — O(appends × chunks); give zone maps the same
   capacity-doubling treatment as the data buffer (splice must stay bitwise
   identical to recompute).
10. **`weighted_ecdf_into` materializes an N-sized `(f64, f64)` pair Vec
    before sorting** (`kernels.rs:1687`) — ~160 MB transient at 10M rows on
    the compat ECDF path. Sort an index permutation into the caller's output
    buffers instead.
11. **Rasterizer triangle meshes allocate per triangle and paint serially**
    (`raster.rs:356` `fill_poly` scratch; `OP_TRIANGLES` loop) — hoist
    scratch and reuse the row-banded painter (`paint_banded`) that points and
    segments already use.
12. **`_asF32`/`_asU32` silently full-copy misaligned kernel-reply buffers**
    (`50_chartview.ts:4715`) — currently zero-copy because the transport
    aligns; add a dev-mode warning so a packing regression is observable
    rather than a silent 4 MB/column memcpy.
13. **`local_log_density` allocates a fresh screen-sized grid per
    interaction call** (`kernels.rs:4380`) — reusable scratch would remove
    per-frame churn; bounded by screen size, so low.
14. **Standalone rebin worker keeps its bounded sample as f64**
    (`46_worker.ts:21`) — f32 halves a fixed-size buffer; per-bin math does
    not need f64.

Non-findings recorded to prevent re-litigating: `bin_2d`'s per-thread u32
grids and re-read merge are a documented, bounded tradeoff (`bin_2d_threads`
caps fan-out by points-per-cell; integer merge keeps output thread-count
invariant); the Delaunay/ear-clipping kernels are O(n²) but explicitly capped
by `MAX_QUADRATIC_TRIANGULATION_WORK` and must never be wired to large
scatters; the static-export base64 33% expansion is inherent to the one-file
HTML container (§29) and only affects exports.
