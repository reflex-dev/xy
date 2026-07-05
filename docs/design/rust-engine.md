# Rust Data Engine — Module Boundaries & FFI Protocol

**Status:** design. Decides what lives in Rust vs Python and how the FFI seam
evolves without rewrites. Grounded in the shipped engine: zero-crate cdylib
(`src/lib.rs`, ABI v3, 10 exported symbols), ctypes binding (`_native.py`),
NumPy fallback with enforced parity (`_fallback.py`, `FASTCHARTS_FORCE_FALLBACK`
tests), dispatch in `kernels.py`.

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
| zone maps, encode_f32, m4, bin_2d, min_max, histogram_uniform, normalize_f32, range_indices, local_log_density | Rust (ABI v3) | correct |
| ohlc_decimate (when finance returns) | was NumPy-in-kernels.py | acceptable stopgap **only** because candles decimate to ≤px buckets; promote to Rust with the pyramid work |
| tier decisions, hysteresis, drill_seq, spec/emitters, channel resolution | Python | correct — keep |
| visible-count mask for drill | NumPy expression in `lod.visible_mask` | promote: it's O(N) per zoom step at 100M — fold into `fc_range_indices` (already exists) so count+indices come from one pass |

### Target Rust ownership (matches the priority list)

binning (1D/2D/channel-aware) ✅/plan · decimation (M4 ✅, OHLC plan) ·
range filtering (`fc_range_indices` ✅) · grouping/category encoding (plan:
`fc_factorize` — today NumPy `unique`, fine to N≈10M, promote when category
charts hit interaction paths) · histogram stats ✅ · quantiles (plan:
`fc_quantiles`, needed by box/violin) · box/violin stats (thin composition
over quantiles — stats in Rust, assembly in Python) · multi-resolution tile
generation (plan: `tiles.rs`, the LOD doc's pyramid) · streaming append
(plan: `stream.rs`, §5 below).

## 2. Module boundaries (crate layout)

```
src/
  lib.rs        # C ABI shell ONLY: extern fns, pointer/len marshaling,
                #   ABI_VERSION. No math. Every fn: null/len checks → slice
                #   → call kernels::* → write out-params.
  kernels.rs    # pure safe Rust, today's 9 kernels. No unsafe, no I/O.
  tiles.rs      # (plan) pyramid build/fetch. Owns tile memory; handles are
                #   opaque u64 ids passed over the ABI (§3.3).
  stream.rs     # (plan) append buffers + dirty-tile tracking.
  stats.rs      # (plan) quantiles/box/violin/factorize.
```

Rules: `lib.rs` is the only file with `unsafe`; kernel modules are pure
functions over slices (fuzzable, testable without FFI); **dependencies are
minimized, not prohibited** (policy 2026-07-05): a crate may be added when it
pays for itself — measured win, small dependency tree, well-maintained — and
the C-ABI/one-cdylib-per-platform property is preserved. Note the dev sandbox
cannot reach crates.io, so required crates must be vendored or the sandbox
loses local build/test; prefer feature-gated optional deps (e.g. SIMD
argminmax, tsdownsample-class speed) with the lean build as default.

## 3. FFI protocol — how it evolves without rewrites

### 3.1 What's already right (keep as law)

- **C ABI + ctypes, no PyO3**: no per-CPython builds, no registry needed.
- **Caller-allocated buffers**: Python (NumPy) allocates outputs; Rust writes
  into them and returns counts. No cross-language ownership for array data.
- **f64 in, f32 out** for geometry (offset-encoded, §16); u32 for indices.
- **Lockstep `ABI_VERSION`** in `src/lib.rs` + `_native.py`, checked at load,
  fallback on mismatch — an old wheel never mis-calls a new lib.
- **Fallback parity as a contract**: every kernel exists twice (Rust, NumPy)
  and CI runs the suite both ways. A kernel without a fallback doesn't merge.

### 3.2 Evolution rules (the anti-rewrite discipline)

- **E1 — additive by default**: new capability = new `fc_*` symbol. Existing
  signatures are immutable once shipped in a release; changing one means a
  new name (`fc_bin_2d_v2`) + ABI bump, old symbol kept for one minor cycle.
- **E2 — flags-struct for growth-prone kernels**: kernels we *know* will grow
  options (tile fetch, channel binning) take a final `*const FcOpts` pointer
  to a versioned plain-C struct (`{u32 size; ...}`); size-checked so old
  callers pass smaller structs safely. This is how we avoid v2/v3 name churn
  for the pyramid API specifically.
- **E3 — no callbacks across the ABI**: Rust never calls back into Python.
  Progress/streaming = polling functions. Keeps the seam re-entrant and GIL-
  trivial (all kernels release the GIL implicitly since ctypes calls do).
- **E4 — errors are return codes** (0 ok, negative = documented error enum),
  never panics across FFI: `lib.rs` wraps kernel calls in `catch_unwind` →
  error code (work item — today kernels are panic-free by construction, but
  the belt goes on with the next ABI bump).
- **E5 — threading stays inside**: when kernels go parallel (pyramid build),
  std::thread scoped inside the call; the ABI stays synchronous. Async/
  incremental build = handle + `fc_pyramid_poll` (E3).

### 3.3 Opaque handles (for tiles/streams)

Arrays-in/arrays-out stops working when Rust must own long-lived state
(pyramid, append buffers). Pattern:

```c
u64  fc_pyramid_build(const f64* x, const f64* y, /*channels…*/, FcOpts*);
i32  fc_pyramid_tile(u64 h, u32 level, u32 tx, u32 ty, f32* out_count, ...);
void fc_pyramid_free(u64 h);
```

Handles are indices into a Rust-side registry (mutex-guarded slab), not raw
pointers — a stale/double-freed handle is an error code, not UB. Python wraps
each in an object with `__del__`/weakref finalizer. The NumPy fallback
implements the same handle API over Python dicts, preserving parity.

## 4. What Python keeps forever

Ingest normalization (pandas/arrow/dtype coercion — ecosystem glue),
`ColumnStore`/zone-map bookkeeping (thin, O(chunks)), all spec emission,
tier/budget policy, channel *resolution* (mode inference, palette, warnings),
validation and error messages (the new bounds/bool hardening lives at this
layer and belongs there), widget/comm transport. This layer is the product's
personality; keeping it in Python is a feature.

## 5. Streaming append (design sketch, phase after pyramid)

`stream.rs`: per-column chunked append buffers (fixed 64k-row chunks) with
per-chunk zone maps computed on seal — identical shape to today's ingest
zone maps, so autorange/pruning code doesn't change. Appends mark
intersecting pyramid tiles dirty; dirty tiles rebuild lazily on next fetch
(bounded: a stream touching one region rebuilds ~1 tile/level). ABI:
`fc_stream_new/append/seal/free` + the pyramid fetch reading through the
stream handle. Python-side `Figure.append(trace_id, **cols)` re-emits only
affected view updates. This slots into the existing update protocol — no new
message types (the unified view message from the contract covers it).

## 6. Implementation order

1. E4 panic-shield + error enum (with next ABI bump, cheap insurance).
2. `fc_bin_2d_channels` (LOD doc phase 1) — first FcOpts-style kernel.
3. Fold drill visible-count into `fc_range_indices` (one pass, count+idx).
4. `stats.rs`: `fc_quantiles` (+ box/violin composition) — unblocks rank-8
   box plots with Rust-grade interaction.
5. `tiles.rs` pyramid handles (LOD phases 3-4).
6. `stream.rs` append (after Arrow ingest lands).
