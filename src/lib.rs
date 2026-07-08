//! C ABI for the fastcharts native core (design dossier §32: the native Rust core
//! runs inside the Python process, operating zero-copy over NumPy/Arrow buffers).
//!
//! Deliberately dependency-free (std only): builds with no registry access, and
//! the C ABI is independent of the CPython version — one cdylib per platform
//! covers all Pythons (§33's wheel-matrix goal, minus the ABI cross-product).
//!
//! Phase 0 exposes stateless kernels over caller-owned buffers — the canonical
//! column store stays on the Python side as NumPy arrays (CPU is the truth, GPU
//! and every derived buffer is a cache, §27). A Rust-owned column store arrives
//! with Tier 2/3.
//!
//! Safety contract (enforced by the single ctypes wrapper in
//! `python/fastcharts/_native.py`, the only in-tree caller): non-empty inputs
//! use non-null, properly aligned pointers sized as documented per function.
//! Empty inputs are accepted without dereferencing their pointers; invalid
//! pointer/argument combinations return the documented error sentinel instead of
//! panicking across the C boundary.

pub mod kernels;
mod simd;
pub mod tiles;

use kernels::ZoneMap;

fn finite_gt(lo: f64, hi: f64) -> bool {
    lo.is_finite() && hi.is_finite() && hi > lo
}

fn finite_ordered(lo: f64, hi: f64) -> bool {
    lo.is_finite() && hi.is_finite() && hi >= lo
}

/// Panic backstop for the C ABI: a Rust panic must never unwind across
/// `extern "C"` into the host interpreter — that is undefined behavior and in
/// practice aborts the embedding CPython process. Any panic (an internal
/// assert, a worker-join failure, an OOM unwind) maps to the calling entry
/// point's error sentinel instead; output buffers may then be partially
/// written, exactly like the existing invalid-argument paths, and callers
/// already treat the sentinel as "output undefined". `AssertUnwindSafe` is
/// sound because nothing observes the closure's captures after a panic.
fn ffi_guard<R>(sentinel: R, body: impl FnOnce() -> R) -> R {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(body)).unwrap_or(sentinel)
}

/// ABI version — bumped on any signature change. The Python wrapper checks this
/// at load time and refuses a mismatched library loudly (§33 comm-versioning
/// rule, applied to the in-process boundary).
pub const ABI_VERSION: u32 = 7;

#[no_mangle]
pub extern "C" fn fc_abi_version() -> u32 {
    ABI_VERSION
}

/// Zone maps (§22) over `data[0..len]` in chunks of `chunk_size`.
///
/// Output arrays must each hold `ceil(len / chunk_size)` elements.
/// Returns the number of chunks written.
///
/// # Safety
/// `data` must point to `len` readable f64s; each out pointer to
/// `ceil(len/chunk_size)` writable elements; `chunk_size > 0`.
#[no_mangle]
pub unsafe extern "C" fn fc_zone_maps(
    data: *const f64,
    len: usize,
    chunk_size: usize,
    out_min: *mut f64,
    out_max: *mut f64,
    out_count: *mut u64,
    out_null_count: *mut u64,
    out_sum: *mut f64,
    out_sum_sq: *mut f64,
) -> usize {
    if chunk_size == 0 {
        return usize::MAX;
    }
    if len == 0 {
        return 0;
    }
    let n_chunks = len.div_ceil(chunk_size);
    if data.is_null()
        || out_min.is_null()
        || out_max.is_null()
        || out_count.is_null()
        || out_null_count.is_null()
        || out_sum.is_null()
        || out_sum_sq.is_null()
    {
        return usize::MAX;
    }
    let data = std::slice::from_raw_parts(data, len);
    let zms = match ffi_guard(None, || Some(kernels::zone_maps(data, chunk_size))) {
        Some(z) => z,
        None => return usize::MAX,
    };
    debug_assert_eq!(zms.len(), n_chunks);
    for (i, zm) in zms.iter().enumerate() {
        let ZoneMap {
            min,
            max,
            count,
            null_count,
            sum,
            sum_sq,
        } = *zm;
        *out_min.add(i) = min;
        *out_max.add(i) = max;
        *out_count.add(i) = count;
        *out_null_count.add(i) = null_count;
        *out_sum.add(i) = sum;
        *out_sum_sq.add(i) = sum_sq;
    }
    zms.len()
}

/// Offset-encode (§4/§16): `out[i] = (data[i] - offset) * scale` as f32.
/// Returns 1 on success (including the empty no-op), 0 on null arguments —
/// callers must treat 0 as "output undefined".
///
/// # Safety
/// `data` must point to `len` readable f64s, `out` to `len` writable f32s.
#[no_mangle]
pub unsafe extern "C" fn fc_encode_f32(
    data: *const f64,
    len: usize,
    offset: f64,
    scale: f64,
    out: *mut f32,
) -> i32 {
    if len == 0 {
        return 1;
    }
    if data.is_null() || out.is_null() {
        return 0;
    }
    let data = std::slice::from_raw_parts(data, len);
    let out = std::slice::from_raw_parts_mut(out, len);
    ffi_guard(0, || {
        kernels::encode_f32_into(data, offset, scale, out);
        1
    })
}

/// M4 decimation (§5 Tier 1): source indices of {first, min, max, last} per
/// bucket over the visible window `[x0, x1)`. `x` must be ascending.
///
/// `out` must hold `4 * n_buckets` u32s. Returns the count written, or
/// `usize::MAX` on invalid arguments (non-finite bounds, x1 <= x0, or
/// n_buckets == 0).
///
/// # Safety
/// `x`/`y` must point to `len` readable f64s; `out` to `4 * n_buckets`
/// writable u32s.
#[no_mangle]
pub unsafe extern "C" fn fc_m4_indices(
    x: *const f64,
    y: *const f64,
    len: usize,
    x0: f64,
    x1: f64,
    n_buckets: usize,
    out: *mut u32,
) -> usize {
    if n_buckets == 0 || !finite_gt(x0, x1) {
        return usize::MAX;
    }
    if len == 0 {
        return 0;
    }
    if x.is_null() || y.is_null() {
        return usize::MAX;
    }
    let x = std::slice::from_raw_parts(x, len);
    let y = std::slice::from_raw_parts(y, len);
    let idx = match ffi_guard(None, || Some(kernels::m4_indices(x, y, x0, x1, n_buckets))) {
        Some(idx) => idx,
        None => return usize::MAX,
    };
    if idx.is_empty() {
        return 0;
    }
    if out.is_null() {
        return usize::MAX;
    }
    let out = std::slice::from_raw_parts_mut(out, n_buckets * 4);
    out[..idx.len()].copy_from_slice(&idx);
    idx.len()
}

/// 2D density aggregation (§5 Tier 2): additively bin points into a `w × h`
/// grid over the viewport. `out` must be `w * h` f32s (fully overwritten).
///
/// # Safety
/// `x`/`y` must point to `len` readable f64s; `out` to `w * h` writable f32s;
/// `w > 0 && h > 0` and finite increasing bounds.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn fc_bin_2d(
    x: *const f64,
    y: *const f64,
    len: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    out: *mut f32,
) -> i32 {
    let bad = w == 0 || h == 0 || !finite_gt(x0, x1) || !finite_gt(y0, y1);
    if bad {
        return 0;
    }
    if out.is_null() {
        return 0;
    }
    let (x, y) = if len == 0 {
        (&[][..], &[][..])
    } else {
        if x.is_null() || y.is_null() {
            return 0;
        }
        (
            std::slice::from_raw_parts(x, len),
            std::slice::from_raw_parts(y, len),
        )
    };
    let out = std::slice::from_raw_parts_mut(out, w * h);
    ffi_guard(0, || {
        kernels::bin_2d(x, y, x0, x1, y0, y1, w, h, out);
        1
    })
}

/// Fused density scan (§5 Tier 2): one pass writing BOTH the count grid
/// (bin_2d semantics: half-open finite window) and the ascending in-window
/// row indices (range_indices semantics: inclusive window). Each output is
/// bitwise identical to its standalone kernel. Returns the index count, or
/// `usize::MAX` on invalid arguments.
///
/// # Safety
/// `x`/`y` must point to `len` readable f64s; `grid` to `w*h` writable f32s;
/// `idx` to `len` writable u32s.
#[no_mangle]
pub unsafe extern "C" fn fc_bin_2d_indices(
    x: *const f64,
    y: *const f64,
    len: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    grid: *mut f32,
    idx: *mut u32,
) -> usize {
    let bad = w == 0 || h == 0 || !finite_gt(x0, x1) || !finite_gt(y0, y1);
    if bad || grid.is_null() {
        return usize::MAX;
    }
    let (x, y, idx) = if len == 0 {
        (&[][..], &[][..], &mut [][..])
    } else {
        if x.is_null() || y.is_null() || idx.is_null() {
            return usize::MAX;
        }
        (
            std::slice::from_raw_parts(x, len),
            std::slice::from_raw_parts(y, len),
            std::slice::from_raw_parts_mut(idx, len),
        )
    };
    let grid = std::slice::from_raw_parts_mut(grid, w * h);
    if len == 0 {
        grid.fill(0.0);
        return 0;
    }
    ffi_guard(usize::MAX, || kernels::bin_2d_indices(x, y, x0, x1, y0, y1, w, h, grid, idx))
}

/// NaN-skipping min/max (autorange primitive). Returns 1 and writes the result,
/// or 0 if the input is empty / all-NaN.
///
/// # Safety
/// `data` must point to `len` readable f64s; out pointers to one writable f64.
#[no_mangle]
pub unsafe extern "C" fn fc_min_max(
    data: *const f64,
    len: usize,
    out_min: *mut f64,
    out_max: *mut f64,
) -> i32 {
    if len == 0 {
        return 0;
    }
    if data.is_null() || out_min.is_null() || out_max.is_null() {
        return 0;
    }
    let data = std::slice::from_raw_parts(data, len);
    match ffi_guard(None, || kernels::min_max(data)) {
        Some((mn, mx)) => {
            *out_min = mn;
            *out_max = mx;
            1
        }
        None => 0,
    }
}

/// Uniform fixed-bin histogram. Returns the count of finite in-range values, or
/// `usize::MAX` on invalid arguments. `out_counts` must hold `n_bins` f64s.
///
/// # Safety
/// `data` must point to `len` readable f64s; `out_counts` to `n_bins` writable
/// f64s; `n_bins > 0` and `lo`/`hi` finite increasing.
#[no_mangle]
pub unsafe extern "C" fn fc_histogram_uniform(
    data: *const f64,
    len: usize,
    lo: f64,
    hi: f64,
    n_bins: usize,
    density: i32,
    out_counts: *mut f64,
) -> usize {
    let bad = n_bins == 0 || !finite_gt(lo, hi);
    if bad {
        return usize::MAX;
    }
    if out_counts.is_null() {
        return usize::MAX;
    }
    let data = if len == 0 {
        &[][..]
    } else {
        if data.is_null() {
            return usize::MAX;
        }
        std::slice::from_raw_parts(data, len)
    };
    let out = std::slice::from_raw_parts_mut(out_counts, n_bins);
    let total = match ffi_guard(None, || Some(kernels::histogram_uniform(data, lo, hi, out))) {
        Some(t) => t,
        None => return usize::MAX,
    };
    if density != 0 && total > 0 {
        let bin_w = (hi - lo) / n_bins as f64;
        let denom = total as f64 * bin_w;
        for c in out.iter_mut() {
            *c /= denom;
        }
    }
    total as usize
}

/// Normalize f64 values into f32 `[0,1]`. `nan_mode=0` maps non-finite values to
/// 0.0; `nan_mode=1` maps them to f32 NaN. Returns 1 on success (including the
/// empty no-op), 0 on null arguments or a non-finite/inverted domain — the
/// former silent-void failure left the output buffer uninitialized with no way
/// to detect it.
///
/// # Safety
/// `data` must point to `len` readable f64s; `out` to `len` writable f32s.
#[no_mangle]
pub unsafe extern "C" fn fc_normalize_f32(
    data: *const f64,
    len: usize,
    lo: f64,
    hi: f64,
    nan_mode: i32,
    out: *mut f32,
) -> i32 {
    if len == 0 {
        return 1;
    }
    if data.is_null() || out.is_null() || !finite_gt(lo, hi) {
        return 0;
    }
    let data = std::slice::from_raw_parts(data, len);
    let out = std::slice::from_raw_parts_mut(out, len);
    let nan_value = if nan_mode == 1 { f32::NAN } else { 0.0 };
    ffi_guard(0, || {
        kernels::normalize_f32_into(data, lo, hi, nan_value, out);
        1
    })
}

/// Deterministic sampling mask (§5/§17): `out[i] = 1` iff
/// `splitmix64(ids[i] + seed) <= threshold`. Bit-identical to
/// `fastcharts.lod.hash_row_ids` thresholding, fused into one pass.
/// Returns 1 on success (including the empty no-op), 0 on null arguments.
///
/// # Safety
/// `ids` must point to `len` readable u64s; `out` to `len` writable u8s.
#[no_mangle]
pub unsafe extern "C" fn fc_sample_mask(
    ids: *const u64,
    len: usize,
    seed: u64,
    threshold: u64,
    out: *mut u8,
) -> i32 {
    if len == 0 {
        return 1;
    }
    if ids.is_null() || out.is_null() {
        return 0;
    }
    let ids = std::slice::from_raw_parts(ids, len);
    let out = std::slice::from_raw_parts_mut(out, len);
    ffi_guard(0, || {
        kernels::sample_mask(ids, seed, threshold, out);
        1
    })
}

/// Canonical row indices inside an inclusive rectangular window. Returns the
/// count written. `out` must hold `len` u32s.
///
/// # Safety
/// `x`/`y` must point to `len` readable f64s; `out` to `len` writable u32s.
#[no_mangle]
pub unsafe extern "C" fn fc_range_indices(
    x: *const f64,
    y: *const f64,
    len: usize,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out: *mut u32,
) -> usize {
    if !finite_ordered(lo_x, hi_x) || !finite_ordered(lo_y, hi_y) {
        return usize::MAX;
    }
    if len == 0 {
        return 0;
    }
    if x.is_null() || y.is_null() || out.is_null() {
        return usize::MAX;
    }
    let x = std::slice::from_raw_parts(x, len);
    let y = std::slice::from_raw_parts(y, len);
    let out = std::slice::from_raw_parts_mut(out, len);
    ffi_guard(usize::MAX, || kernels::range_indices(x, y, lo_x, hi_x, lo_y, hi_y, out))
}

/// Per-point local log density for a subset. Returns 1 on success, 0 on invalid
/// grid/window arguments.
///
/// # Safety
/// `x`/`y` must point to `len` readable f64s; `out` to `len` writable f32s.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn fc_local_log_density(
    x: *const f64,
    y: *const f64,
    len: usize,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    out: *mut f32,
) -> i32 {
    let bad = w == 0 || h == 0 || !finite_gt(lo_x, hi_x) || !finite_gt(lo_y, hi_y);
    if bad {
        return 0;
    }
    if len == 0 {
        return 1;
    }
    if x.is_null() || y.is_null() || out.is_null() {
        return 0;
    }
    let x = std::slice::from_raw_parts(x, len);
    let y = std::slice::from_raw_parts(y, len);
    let out = std::slice::from_raw_parts_mut(out, len);
    ffi_guard(0, || {
        kernels::local_log_density(x, y, lo_x, hi_x, lo_y, hi_y, w, h, out);
        1
    })
}

// -- tile pyramid (§5 Tier 3): opaque u64 handles, engine doc §3.3 ------------

/// Build a count pyramid over the given bounds. Returns a nonzero handle, or
/// 0 on invalid arguments. The handle must be released with fc_pyramid_free.
/// # Safety
/// `x`/`y` must point to `len` readable f64s.
#[no_mangle]
pub unsafe extern "C" fn fc_pyramid_build(
    x: *const f64,
    y: *const f64,
    len: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    base_dim: u32,
) -> u64 {
    if x.is_null() || y.is_null() || len == 0 {
        return 0;
    }
    let x = std::slice::from_raw_parts(x, len);
    let y = std::slice::from_raw_parts(y, len);
    ffi_guard(0, || match tiles::build(x, y, x0, x1, y0, y1, base_dim as usize) {
        Some(p) => tiles::reg_insert(p),
        None => 0,
    })
}

/// Approximate in-window count from the finest level. 1 on success, 0 on a
/// stale/invalid handle or bad arguments.
/// # Safety
/// `out_count` must point to a writable f64.
#[no_mangle]
pub unsafe extern "C" fn fc_pyramid_count(
    handle: u64,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out_count: *mut f64,
) -> i32 {
    if out_count.is_null() || !finite_gt(lo_x, hi_x) || !finite_gt(lo_y, hi_y) {
        return 0;
    }
    ffi_guard(0, || {
        match tiles::reg_with(handle, |p| tiles::count(p, lo_x, hi_x, lo_y, hi_y)) {
            Some(c) => {
                *out_count = c;
                1
            }
            None => 0,
        }
    })
}

/// Compose the window into a w×h grid. Returns the level used (>= 0),
/// -1 on stale handle/bad args, -2 when the window outresolves the pyramid
/// (caller must fall back to an exact re-bin and disclose it, §28).
/// # Safety
/// `out` must point to `w * h` writable f32s.
#[no_mangle]
pub unsafe extern "C" fn fc_pyramid_compose(
    handle: u64,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    out: *mut f32,
) -> i32 {
    if out.is_null() || w == 0 || h == 0 || !finite_gt(lo_x, hi_x) || !finite_gt(lo_y, hi_y) {
        return -1;
    }
    let out = std::slice::from_raw_parts_mut(out, w * h);
    ffi_guard(-1, || {
        match tiles::reg_with(handle, |p| tiles::compose(p, lo_x, hi_x, lo_y, hi_y, w, h, out)) {
            Some(Some(level)) => level as i32,
            Some(None) => -2,
            None => -1,
        }
    })
}

/// Release a pyramid. 1 if it existed, 0 for stale/unknown handles.
/// # Safety
/// No pointer arguments; safe for any handle value.
#[no_mangle]
pub unsafe extern "C" fn fc_pyramid_free(handle: u64) -> i32 {
    ffi_guard(0, || if tiles::reg_remove(handle) { 1 } else { 0 })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ffi_guard_maps_panic_to_sentinel() {
        // A panic anywhere behind the C ABI must become the entry point's
        // error sentinel, never an unwind across `extern "C"` (which would
        // abort the embedding interpreter).
        let hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {})); // silence the expected panic
        let got = ffi_guard(usize::MAX, || panic!("deliberate test panic"));
        std::panic::set_hook(hook);
        assert_eq!(got, usize::MAX);
        assert_eq!(ffi_guard(0i32, || 1i32), 1);
    }
}
