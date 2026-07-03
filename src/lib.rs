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
//! `python/fastcharts/_native.py`, the only caller): all pointers are non-null,
//! properly aligned, and sized as documented per function.

pub mod kernels;

use kernels::ZoneMap;

/// ABI version — bumped on any signature change. The Python wrapper checks this
/// at load time and refuses a mismatched library loudly (§33 comm-versioning
/// rule, applied to the in-process boundary).
pub const ABI_VERSION: u32 = 2;

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
    let data = std::slice::from_raw_parts(data, len);
    let zms = kernels::zone_maps(data, chunk_size);
    for (i, zm) in zms.iter().enumerate() {
        let ZoneMap { min, max, count, null_count, sum, sum_sq } = *zm;
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
) {
    let data = std::slice::from_raw_parts(data, len);
    let out = std::slice::from_raw_parts_mut(out, len);
    kernels::encode_f32_into(data, offset, scale, out);
}

/// M4 decimation (§5 Tier 1): source indices of {first, min, max, last} per
/// bucket over the visible window `[x0, x1)`. `x` must be ascending.
///
/// `out` must hold `4 * n_buckets` u32s. Returns the count written, or
/// `usize::MAX` on invalid arguments (x1 <= x0 or n_buckets == 0).
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
    // `!(x1 > x0)` (not `x1 <= x0`) deliberately rejects NaN bounds too.
    #[allow(clippy::neg_cmp_op_on_partial_ord)]
    if n_buckets == 0 || !(x1 > x0) {
        return usize::MAX;
    }
    let x = std::slice::from_raw_parts(x, len);
    let y = std::slice::from_raw_parts(y, len);
    let idx = kernels::m4_indices(x, y, x0, x1, n_buckets);
    let out = std::slice::from_raw_parts_mut(out, n_buckets * 4);
    out[..idx.len()].copy_from_slice(&idx);
    idx.len()
}

/// 2D density aggregation (§5 Tier 2): additively bin points into a `w × h`
/// grid over the viewport. `out` must be `w * h` f32s (fully overwritten).
///
/// # Safety
/// `x`/`y` must point to `len` readable f64s; `out` to `w * h` writable f32s;
/// `w > 0 && h > 0 && x1 > x0 && y1 > y0`.
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
    // `!(a > b)` (not `a <= b`) deliberately rejects NaN bounds too.
    #[allow(clippy::neg_cmp_op_on_partial_ord)]
    let bad = w == 0 || h == 0 || !(x1 > x0) || !(y1 > y0);
    if bad {
        return 0;
    }
    let x = std::slice::from_raw_parts(x, len);
    let y = std::slice::from_raw_parts(y, len);
    let out = std::slice::from_raw_parts_mut(out, w * h);
    kernels::bin_2d(x, y, x0, x1, y0, y1, w, h, out);
    1
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
    let data = std::slice::from_raw_parts(data, len);
    match kernels::min_max(data) {
        Some((mn, mx)) => {
            *out_min = mn;
            *out_max = mx;
            1
        }
        None => 0,
    }
}
