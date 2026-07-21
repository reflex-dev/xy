# Rust Data Engine — Module Boundaries & FFI Protocol

**Status:** design. Decides what lives in Rust vs Python and how the FFI seam
evolves without rewrites. Grounded in the shipped engine: single-dependency
cdylib (`src/lib.rs`, ABI v36; `png` is the one crate, for static export),
ctypes binding (`_native.py`), and
dispatch in `kernels.py`. The native core is required — `kernels.py` raises a
clear ImportError when it can't load, with no pure-Python fallback.

## 1. The placement rule

**Rust owns row-scan loops; Python owns decisions.** Precisely:

- If work is O(N) over data rows and sits on an interaction path (build,
  zoom, pan, drill) → Rust kernel.
- If work is O(traces), O(screen), or policy (tier choice, budget math, spec
  assembly, validation, warnings) → Python. Moving policy into Rust buys
  nothing (it's microseconds) and costs iteration speed — policy is what
  changes weekly.
- The client (JS) owns nothing O(N): it receives screen-bounded buffers only
  (§29). This boundary is what keeps the browser safe at 1B rows and it never
  moves.

### Current placement audit

| Concern | Today | Verdict |
|---|---|---|
| zone maps, encode_f32, m4, bin_2d, min_max, histogram_uniform, normalize_f32, range/validity indices, local_log_density | Rust (ABI v36) | correct — new equal-length x/y columns use a paired zone-map call with bit-identical per-column reductions; full-domain density first paint fuses binning with uniform or counted-u8 overlay sampling while retaining exact standalone outputs; mesh/rectangle validity scans consume only columns not already proven finite by zone metadata |
| fixed-width string/bytes/bool factorization | Rust (ABI v36) | correct — compact palettes use a bounded L1-resident codebook with full-record collision checks and emit exact counts; U1 uses a direct Unicode-scalar table with endian support; ≥512k rows probe a prefix then encode disjoint chunks in parallel, merging late labels by canonical first-row order before any retry; Python sees only unique labels and retains display-label ordering policy |
| static display-list raster, row-banded polyline/point/segment paint, batched fill+stroke triangle meshes, affine scatter projection plus typed color/size resolution, density/heatmap colormap and sampling | Rust (ABI v36) | correct — commands borrow f32/u8 payload or canonical spans synchronously; compact stratified sampling reuses factorization counts; batched/banded output is byte-identical |
| signal processing: `xy_rfft`, `xy_welch_spectra`, `xy_spectrogram` | Rust (ABI v36) | correct — O(N) transforms over sample columns; window/segment policy stays in Python |
| geometry/triangulation: `xy_delaunay_triangles`, `xy_polygon_triangles`, `xy_marching_squares`, `xy_marching_triangles`, `xy_streamlines`, `xy_vector_segments`, `xy_quad_mesh_triangles`, `xy_sector_triangles`, `xy_indexed_triangles`, `xy_triangle_edges` | Rust (ABI v36) | correct — output is screen-bounded index/vertex buffers; level choice and styling stay in Python |
| statistics: `xy_correlation`, `xy_weighted_ecdf`, `xy_histogram2d`, `xy_stacked_bounds` | Rust (ABI v36) | correct — row-scan reductions; binning policy and labels stay in Python |
| style/text helpers: `xy_css_check` (`css.rs`), `xy_svg_poly_path` (`svg.rs`) | Rust (ABI v36) | correct by a different rule — not O(rows) but O(points)/per-value on the export and validation paths, where per-item Python object churn dominates; error *messages* still assembled in Python |
| ohlc_decimate (when finance returns) | was NumPy-in-kernels.py | acceptable stopgap **only** because candles decimate to ≤px buckets; promote to Rust with the pyramid work |
| tier decisions, hysteresis, drill_seq, spec/emitters, channel resolution | Python | correct — keep |
| visible-count mask for drill | NumPy expression in `lod.visible_mask` | promote: it's O(N) per zoom step at 100M — fold into `xy_range_indices` (already exists) so count+indices come from one pass |

### Target Rust ownership (matches the priority list)

binning (1D/2D/channel-aware) ✅/plan · decimation (M4 ✅, OHLC plan) ·
range filtering (`xy_range_indices` ✅) · implicit uniform and compact-u8
stratified sampling (`xy_sample_range_indices` / `xy_stratified_sample_range_u8` ✅) · grouping/category encoding
(`xy_factorize_fixed` ✅ for contiguous fixed-width values; defensive Python
label canonicalization for mixed objects) · histogram stats ✅ · quantiles (plan:
`xy_quantiles`, needed by box/violin) · box/violin stats (thin composition
over quantiles — stats in Rust, assembly in Python) · multi-resolution tile
generation (`tiles.rs` ✅, including stable-domain incremental updates) ·
Rust-owned streaming column buffers (plan: `stream.rs`, §5 below).

## 2. Module boundaries (crate layout)

```
src/                                          # 15,423 lines shipped, 8 modules
  lib.rs        (3073)  # C ABI shell ONLY: extern fns, pointer/len marshaling,
                        #   ABI_VERSION, the ffi_guard panic shield (§3.2 E4),
                        #   and the mutex-guarded handle registry backing
                        #   tiles.rs. No math. Every fn: null/len checks →
                        #   slice → call kernels::*/raster::* → write out-params.
  kernels.rs    (6113)  # pure safe Rust row-scan kernels: zone maps/encode/M4,
                        #   binning + sampling, factorization, histogram/min-max/
                        #   normalize/range+validity indices, density, signal
                        #   (rfft/Welch/spectrogram), geometry (Delaunay, marching
                        #   squares/triangles, streamlines, vector segments),
                        #   correlation/weighted ECDF/stacked bounds.
                        #   No unsafe, no I/O.
  raster.rs     (3423)  # the entire native rasterizer — the whole static PNG
                        #   export path below Python's geometry/scale/colormap
                        #   computation. Consumes a tagged display-list command
                        #   stream (optionally borrowing f32/u8 payload or
                        #   canonical spans) and paints into a straight-alpha
                        #   RGBA8 framebuffer the caller owns:
                        #     · scanline polygon fill, flat + linear gradient,
                        #       with a rectangle fast path
                        #     · SDF/distance-based stroke and point-symbol paint
                        #       (round caps/joins and AA fall out of the metric)
                        #     · affine scatter projection, typed per-point color/
                        #       size resolution, batched triangle meshes, segments
                        #     · image blit incl. density/heatmap colormap sampling
                        #     · text, blitted and bilinearly scaled from font.rs
                        #     · row-banded multithreaded paint (std::thread::scope,
                        #       byte-identical to the serial path) and the fused
                        #       raster→PNG encode via `png`/fdeflate.
                        #   No unsafe; owns the crate's one third-party dep.
  font.rs       (1039)  # generated by scripts/gen_font.py — do not hand-edit.
                        #   Baked DejaVu Sans grayscale coverage atlas for
                        #   raster.rs: 205 glyph records (advance, w, h, left,
                        #   top, coverage offset/len) at BASE_PX=16 plus the
                        #   row-major coverage bytes, and EXTRA_CODEPOINTS, the
                        #   sorted table of the 110 non-ASCII codepoints. Data
                        #   only — no shaping, no FreeType, no unsafe. Coverage
                        #   limits are a product constraint, not a detail: §2.1.
  css.rs         (788)  # tiered CSS value/color validation behind `xy_css_check`.
  svg.rs          (58)  # screen-space coordinate serialization for the SVG path:
                        #   `poly_path` alone, folding parallel f64 x/y arrays
                        #   into one `M`/`L` path-data string with Python-matching
                        #   2-decimal fixed-point trimming (including the `-0`
                        #   case). Rejects length-mismatched, empty, or non-finite
                        #   input by returning None. Deliberately narrow: it
                        #   exists to kill one Python string per point, and the
                        #   rest of SVG scene construction stays in Python.
  simd.rs        (448)  # AVX2 twins of eligible kernels, runtime-dispatched (§3.4).
                        #   The one module besides lib.rs allowed `unsafe`.
  tiles.rs       (481)  # pyramid build/compose/incremental append. Owns tile memory;
                        #   handles are opaque u64 ids passed over the ABI (§3.3).
  stream.rs             # (plan) Rust-owned canonical append buffers.
  stats.rs              # (plan) quantiles/box/violin/factorize.
```

Line counts are `wc -l` at this revision and drift with the code; the ordering
(kernels > raster > lib > font > css > tiles > simd > svg) is the stable fact —
rasterization is the second-largest thing in the crate, and it is not a helper.

Rules: `lib.rs` is the only file with `unsafe` (except `simd.rs`, §3.4 rule
3); kernel modules are pure
functions over slices (fuzzable, testable without FFI); **dependencies are
minimized, not prohibited** (policy 2026-07-05): a crate may be added when it
pays for itself — measured win, small dependency tree, well-maintained — and
the C-ABI/one-cdylib-per-platform property is preserved. Note the dev sandbox
cannot reach crates.io, so required crates must be vendored or the sandbox
loses local build/test; prefer feature-gated optional deps (e.g. SIMD
argminmax, tsdownsample-class speed) with the lean build as default.

### 2.1 Native text is a bounded subset, and misses are silent

Declining FreeType bought the single-cdylib property (§3.1) and paid for it in
Unicode coverage. `font.rs` bakes exactly 205 glyphs: ASCII 32–126 (95) plus
the 110 codepoints enumerated in `font::EXTRA_CODEPOINTS` — lowercase Greek
(α–ω) and the eleven uppercase Greek letters that differ from Latin forms
(Γ Δ Θ Λ Ξ Π Σ Υ Φ Ψ Ω), math operators (`∂ ∇ ∈ − ∓ √ ∝ ∞ ∫ ≈ ≠ ≤ ≥`), the
left and right arrows only, super/subscript digits and a handful of subscript
letters, typographic quotes, en/em dashes, and a few symbols (`° ± × · µ ²³¹ …`).
Nothing else exists: no accented Latin at all, no Cyrillic, no CJK, no Arabic,
no emoji.

The failure mode is worse than the coverage gap. `glyph_index`
(`src/raster.rs:1175`) returns `None` for an uncovered codepoint, and the paint
loop's `let … else { continue; }` (`src/raster.rs:1236-1238`) drops that
character **before** the advance is applied — so the glyph is deleted, not
substituted, and the following glyphs close up over the hole. There is no tofu
box, no fallback glyph, no warning, and no error. `"Müller"` rasterizes as
`"Mller"`; a fully non-Latin label rasterizes as nothing. The anchoring pass
sums advances through the same `glyph_index` filter (`src/raster.rs:1200-1204`),
so a centered or right-anchored label is positioned on its *shortened* width —
the loss is self-consistent and therefore invisible in the output.

This violates §28 (no silent decisions) and is recorded as a known defect, not
a design intent. The minimum honest fix is a substitution glyph with a real
advance, so a coverage miss is *visible*; a warning surfaced at the Python
export boundary (where messages belong, §4) is the complete fix. Until then the
documented escape is `engine=xy.Engine.chromium`, and the user-facing statement
of the same limitation lives in `spec/api/styling.md` §"Native text coverage" —
these two must be amended together. The bound applies to the native raster
formats only; the SVG and PDF export paths have their own text contracts.

## 3. FFI protocol — how it evolves without rewrites

### 3.1 What's already right (keep as law)

- **C ABI + ctypes, no PyO3**: no per-CPython builds; consumers install the
  compiled wheel without a Rust or crate-registry dependency.
- **Caller-allocated buffers**: Python (NumPy) allocates outputs; Rust writes
  into them and returns counts. No cross-language ownership for array data.
- **f64 in, f32 out** for geometry (offset-encoded, §16); u32 for indices.
- **Lockstep `ABI_VERSION`** in `src/lib.rs` + `_native.py`, checked at load,
  hard error on mismatch — an old wheel never mis-calls a new lib.
- **The native core is the single implementation.** There is no pure-Python
  fallback; every kernel is tested directly against the Rust core, and a
  platform that can't load the core gets a clear ImportError, not a degrade.

### 3.2 Evolution rules (the anti-rewrite discipline)

- **E1 — additive by default**: new capability = new `xy_*` symbol. Existing
  signatures are immutable once shipped in a release; changing one means a
  new name (`xy_bin_2d_v2`) + ABI bump, old symbol kept for one minor cycle.
- **E2 — flags-struct for growth-prone kernels**: kernels we *know* will grow
  options (tile fetch, channel binning) take a final `*const FcOpts` pointer
  to a versioned plain-C struct (`{u32 size; ...}`); size-checked so old
  callers pass smaller structs safely. This is how we avoid v2/v3 name churn
  for the pyramid API specifically.
- **E3 — no callbacks across the ABI**: Rust never calls back into Python.
  Progress/streaming = polling functions. Keeps the seam re-entrant and GIL-
  trivial (all kernels release the GIL implicitly since ctypes calls do).
- **E4 — errors are return codes, never panics across FFI.** The panic shield
  has landed: `lib.rs` defines `ffi_guard(sentinel, body)` —
  `catch_unwind(AssertUnwindSafe(body)).unwrap_or(sentinel)` — and wraps every
  entry point that does work in it (63 call sites across 61 of the 62
  `extern "C" fn`s; `xy_abi_version` returns a constant and needs no shield),
  so any panic becomes that entry point's error sentinel instead of unwinding
  across `extern "C"`. Output buffers may be partially written on that path,
  exactly like the existing invalid-argument paths. Still outstanding:
  sentinels are per-kernel ad hoc
  (`0`, `usize::MAX`, `-1`/`-2`) rather than one documented negative error
  enum; unifying them is a work item for the next ABI bump.
- **E5 — threading stays inside**: parallel kernels use `std::thread::scope`
  inside the call; the ABI stays synchronous. General row scans cross over at
  512k values and scale to at most 18 workers. Zone maps cross earlier, at two
  complete 65,536-row chunks, because chunks are independent and require no
  merge; worker count is also capped by actual chunks. CodSpeed stays serial
  because its simulator sums thread instructions rather than wall time.
  Incremental build = handle + `xy_pyramid_append`, which mutates a live
  pyramid in place under the registry lock. A polling entry point
  (`xy_pyramid_poll`) for genuinely async builds is not built; if one is ever
  needed it follows E3 (poll, never call back).

### 3.3 Opaque handles (for tiles/streams)

Arrays-in/arrays-out stops working when Rust must own long-lived state
(pyramid, append buffers). Pattern:

```c
/* build: nonzero handle, or 0 on invalid arguments */
uint64_t xy_pyramid_build(const double* x, const double* y, size_t len,
                          double x0, double x1, double y0, double y1,
                          uint32_t base_dim);
/* append: 1 applied; 0 on stale/busy handle, bad args, or a point outside
   the pyramid's original domain (never partially mutates) */
int32_t xy_pyramid_append(uint64_t handle, const double* x,
                          const double* y, size_t len);
/* count over a window: 1 ok, 0 on stale handle/bad args */
int32_t xy_pyramid_count(uint64_t handle, double lo_x, double hi_x,
                         double lo_y, double hi_y, double* out_count);
/* compose window into a w×h grid: level used (>=0), -1 stale/bad args,
   -2 window outresolves the pyramid (caller re-bins exactly and discloses) */
int32_t xy_pyramid_compose(uint64_t handle, double lo_x, double hi_x,
                           double lo_y, double hi_y,
                           size_t w, size_t h, float* out);
/* free: 1 if it existed, 0 for stale/unknown */
int32_t xy_pyramid_free(uint64_t handle);
```

Note this API took explicit bounds plus `base_dim` rather than the E2
flags-struct; the option set stayed small enough that a versioned `FcOpts`
would have been ceremony. E2 still governs the channel-binning kernels.

Handles are indices into a Rust-side registry (mutex-guarded slab), not raw
pointers — a stale/double-freed handle is an error code, not UB. Python wraps
each in an object with `__del__`/weakref finalizer.

### 3.4 SIMD (contained in `src/simd.rs`)

The cdylib builds for baseline x86-64 (SSE2), so hot scans never see 256-bit
registers unless we ask. `simd.rs` holds branch-free clones of selected
kernels compiled under `#[target_feature(enable = "avx2")]` (LLVM
autovectorizes them — no hand-written intrinsics unless a loop demonstrably
fails to vectorize) with runtime `is_x86_feature_detected!` dispatch and a
`XY_SIMD=0` kill switch.

Rules, in priority order:

1. **Bitwise parity is non-negotiable.** Only order-independent kernels are
   eligible: integer counts, exact comparisons, truncation casts, min/max.
   Float *accumulation* (zone-map sum/sum_sq) must stay scalar — vector
   reassociation changes the result. Parity is enforced by fuzz tests in
   `simd.rs` comparing SIMD vs scalar on hostile data.
2. **Only measured wins ship.** Every dispatch is justified by a before/after
   number (via the kill switch); a kernel where the two-phase restructure
   loses (M4's sequential bucket state machine, histogram's scatter-dominated
   loop) is documented at its scalar definition and NOT dispatched.
3. **`unsafe` containment.** This module is the one exception to "unsafe only
   in `lib.rs`": the `#[target_feature]` wrappers are unsafe to call, and
   every call site sits behind a safe `try_*` fn that checks detection first.
   Kernels code never writes `unsafe` — it calls `simd::try_*` and falls back.
4. **aarch64 needs no twin.** NEON is part of the aarch64 baseline, so the
   scalar kernels already autovectorize at full width there.

## 4. What Python keeps forever

Ingest normalization (pandas/arrow/dtype coercion — ecosystem glue),
`ColumnStore`/zone-map bookkeeping (thin, O(chunks)), all spec emission,
tier/budget policy, channel *resolution* (mode inference, palette, warnings),
validation and error messages (the new bounds/bool hardening lives at this
layer and belongs there), widget/comm transport. This layer is the product's
personality; keeping it in Python is a feature.

## 5. Streaming append (Phase-0 landed Python-side; Rust `stream.rs` later)

**Landed (Phase-0, Python-side canonical):** `Column.append` grows an
amortized capacity buffer and extends zone maps incrementally (only chunks
at/after the old length recompute — the splice is bitwise identical to a
from-scratch ingest). `Figure.append(trace_id, x, y, color=, size=)`
validates atomically (line appends must continue the sorted series;
categorical channels and shared columns are rejected for now), frees the
trace's pyramid for lazy rebuild, exits any drill, and returns an `append`
message carrying a complete fresh payload — screen-bounded by construction
(§29), so the wire never needs deltas. The client rebuilds only the traces
named in `affected`, applies the follow policy (refit when at home, slide
when pinned to the live right edge, hold when inspecting history), and
refines tiered traces to its current window through the normal
stale-while-revalidate request path (§17).

**Still future (`stream.rs`):** Rust-owned chunked append buffers with
zone maps computed on seal, and — the important one — appends marking
intersecting pyramid tiles dirty with lazy per-tile rebuild (bounded: a
stream touching one region rebuilds ~1 tile/level). Phase-0 instead frees
the whole pyramid on append, so a >2M-point stream pays a full pyramid
rebuild on its next far-out view — recorded, not hidden. ABI:
`xy_stream_new/append/seal/free` + the pyramid fetch reading through the
stream handle.

## 6. Implementation order

E4's panic shield and the `tiles.rs` pyramid handles (LOD phases 3-4) have
landed; the remainder, in order:

1. E4 error enum — unify the ad-hoc per-kernel sentinels into one documented
   negative enum (with the next ABI bump, cheap insurance).
2. `xy_bin_2d_channels` (LOD doc phase 1) — first FcOpts-style kernel.
3. Fold drill visible-count into `xy_range_indices` (one pass, count+idx).
4. `stats.rs`: `xy_quantiles` (+ box/violin composition) — unblocks rank-8
   box plots with Rust-grade interaction.
5. `stream.rs` append (after Arrow ingest lands).
