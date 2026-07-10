//! Runtime-dispatched SIMD acceleration for the hot exact-path scans.
//!
//! The crate builds for baseline x86-64 (SSE2), so the scalar kernels never
//! see 256-bit registers. Each function here is a clone of a scalar kernel
//! restructured *branch-free* (blend instead of `continue`) and compiled under
//! `#[target_feature(enable = "avx2")]` so LLVM autovectorizes it — no
//! explicit intrinsics unless a loop demonstrably fails to vectorize.
//!
//! Only the kernels where the restructure measurably wins live here (this
//! box, 10M points): min_max +89%, bin_2d +~50%, local-density gather +~42%,
//! range scan +20–50% at ≤1M (wash at 10M where it's bandwidth-bound).
//! M4 and histogram were tried and REVERTED — measured slower (the bucket
//! state machine / scatter increment dominates and the extra block pass costs
//! more than the vector math saves); see the notes on their scalar kernels.
//!
//! Rules (rust-engine doc §3.4):
//! - Only kernels whose outputs are **order-independent** are accelerated:
//!   integer counts, exact comparisons, and float truncation casts. Kernels
//!   that accumulate floats (zone-map sum/sum_sq) stay scalar — vector
//!   reassociation would break bitwise determinism.
//! - Results must be **bitwise identical** to the scalar kernels; the fuzz
//!   tests below enforce this on hostile data.
//! - `unsafe` is confined to the `#[target_feature]` wrappers here (the one
//!   documented exception to "unsafe only in lib.rs"); every wrapper is
//!   reached only through a safe `try_*` fn that has checked [`use_avx2`].
//! - Kill switch: `XY_SIMD=0` forces the scalar paths — the
//!   before/after benchmark and a debugging escape hatch.
//!
//! Non-x86_64 (e.g. aarch64) needs nothing here: NEON is part of the aarch64
//! baseline, so the scalar kernels already autovectorize at full width there.

#![allow(dead_code, reason = "SIMD kernels are staged behind parity tests before hot-path wiring")]

/// Lane-block size for the two-phase scans: phase 1 computes per-point cell
/// indices / masks branch-free into a stack block (vectorizes), phase 2 does
/// the scalar scatter/compact that SIMD can't express without conflicts.
/// 1 KiB of u32 per block — L1-resident, amortizes the loop overhead.
const BLOCK: usize = 1024;

/// Sentinel for "point rejected" lanes (NaN/±∞/out of window). Real cell and
/// bucket indices are always well below this (grids are screen-sized).
const SKIP: u32 = u32::MAX;

#[cfg(target_arch = "x86_64")]
pub(crate) fn use_avx2() -> bool {
    use std::sync::OnceLock;
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| {
        std::env::var_os("XY_SIMD").is_none_or(|v| v != "0")
            && std::arch::is_x86_feature_detected!("avx2")
    })
}

#[cfg(not(target_arch = "x86_64"))]
pub(crate) fn use_avx2() -> bool {
    false
}

// ---------------------------------------------------------------------------
// Branch-free loop bodies (shared by the AVX2 wrappers; plain safe Rust).
// ---------------------------------------------------------------------------

/// NaN-skipping min/max, blend-style: non-finite lanes contribute the identity
/// element instead of being branched over. min/max are order-independent, so
/// the vectorized reduction is exactly the serial result.
#[inline(always)]
fn min_max_body(data: &[f64]) -> (f64, f64) {
    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for &v in data {
        let lo = if v.is_finite() { v } else { f64::INFINITY };
        let hi = if v.is_finite() { v } else { f64::NEG_INFINITY };
        min = if lo < min { lo } else { min };
        max = if hi > max { hi } else { max };
    }
    (min, max)
}

/// Phase 1 of bin_2d/local-density: per-point cell index or SKIP. The cast
/// chain matches the scalar kernel exactly for accepted points (truncation of
/// a value in `[0, w)`/`[0, h)`); rejected lanes may compute garbage that the
/// blend discards. Wrapping u32 arithmetic keeps rejected lanes deterministic
/// and panic-free without widening to u64 (which AVX2 multiplies poorly).
#[expect(clippy::too_many_arguments, reason = "viewport + grid, same as bin_2d")]
#[inline(always)]
fn cell_block(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    sx: f64,
    sy: f64,
    w: usize,
    h: usize,
    cells: &mut [u32; BLOCK],
) {
    for l in 0..x.len() {
        let xv = x[l];
        let yv = y[l];
        // NaN fails every comparison; ±∞ fails the window bounds (finite x0..y1).
        let ok = xv >= x0 && xv < x1 && yv >= y0 && yv < y1;
        let cx = ((((xv - x0) * sx) as i32).min(w as i32 - 1) as u32).min(w as u32 - 1);
        let cy = ((((yv - y0) * sy) as i32).min(h as i32 - 1) as u32).min(h as u32 - 1);
        let c = cy.wrapping_mul(w as u32).wrapping_add(cx);
        cells[l] = if ok { c } else { SKIP };
    }
}

/// Phase 1 of the window scan: per-point inclusion mask (closed ranges,
/// NaN fails). A byte mask store vectorizes; the compaction is phase 2.
#[inline(always)]
fn range_mask_block(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    mask: &mut [bool; BLOCK],
) {
    for l in 0..x.len() {
        mask[l] = x[l] >= lo_x && x[l] <= hi_x && y[l] >= lo_y && y[l] <= hi_y;
    }
}

// ---------------------------------------------------------------------------
// AVX2 wrappers (the only unsafe in this module) + scalar-consumer phase 2.
// ---------------------------------------------------------------------------

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn min_max_avx2(data: &[f64]) -> (f64, f64) {
    min_max_body(data)
}

#[cfg(target_arch = "x86_64")]
#[expect(clippy::too_many_arguments, reason = "viewport + grid, same as bin_2d")]
#[target_feature(enable = "avx2")]
unsafe fn bin_2d_count_avx2(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    grid: &mut [u32],
) {
    let sx = w as f64 / (x1 - x0);
    let sy = h as f64 / (y1 - y0);
    let mut cells = [SKIP; BLOCK];
    let mut i = 0;
    while i < x.len() {
        let len = (x.len() - i).min(BLOCK);
        cell_block(&x[i..i + len], &y[i..i + len], x0, x1, y0, y1, sx, sy, w, h, &mut cells);
        for &c in &cells[..len] {
            if c != SKIP {
                let cell = &mut grid[c as usize];
                *cell = cell.saturating_add(1);
            }
        }
        i += len;
    }
}

#[cfg(target_arch = "x86_64")]
#[expect(clippy::too_many_arguments, reason = "window + output, same as range_scan")]
#[target_feature(enable = "avx2")]
unsafe fn range_scan_avx2(
    x: &[f64],
    y: &[f64],
    base: u32,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out: &mut [u32],
) -> usize {
    let mut mask = [false; BLOCK];
    let mut n = 0usize;
    let mut i = 0;
    while i < x.len() {
        let len = (x.len() - i).min(BLOCK);
        range_mask_block(&x[i..i + len], &y[i..i + len], lo_x, hi_x, lo_y, hi_y, &mut mask);
        for (l, &m) in mask[..len].iter().enumerate() {
            if m {
                out[n] = base + (i + l) as u32;
                n += 1;
            }
        }
        i += len;
    }
    n
}

/// Local-density gather: same cell math as bin_2d, but phase 2 reads the
/// (already log-normalized) grid value back per point instead of scattering.
#[cfg(target_arch = "x86_64")]
#[expect(clippy::too_many_arguments, reason = "window + grid, same as local_log_density")]
#[target_feature(enable = "avx2")]
unsafe fn density_gather_avx2(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    grid: &[f32],
    out: &mut [f32],
) {
    let sx = w as f64 / (hi_x - lo_x);
    let sy = h as f64 / (hi_y - lo_y);
    let mut cells = [SKIP; BLOCK];
    let mut i = 0;
    while i < x.len() {
        let len = (x.len() - i).min(BLOCK);
        cell_block(
            &x[i..i + len],
            &y[i..i + len],
            lo_x,
            hi_x,
            lo_y,
            hi_y,
            sx,
            sy,
            w,
            h,
            &mut cells,
        );
        for (l, &c) in cells[..len].iter().enumerate() {
            if c != SKIP {
                out[i + l] = grid[c as usize];
            }
        }
        i += len;
    }
}

// ---------------------------------------------------------------------------
// Safe dispatch: `Some(accelerated result)` when AVX2 is available and
// enabled, `None` to tell the caller to run its scalar path. This keeps
// every `unsafe` call site inside this module.
// ---------------------------------------------------------------------------

pub(crate) fn try_min_max(data: &[f64]) -> Option<(f64, f64)> {
    #[cfg(target_arch = "x86_64")]
    if use_avx2() {
        // SAFETY: use_avx2() verified AVX2 support on this CPU at runtime.
        return Some(unsafe { min_max_avx2(data) });
    }
    let _ = data;
    None
}

#[expect(clippy::too_many_arguments, reason = "viewport + grid, same as bin_2d")]
pub(crate) fn try_bin_2d_count(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    grid: &mut [u32],
) -> bool {
    #[cfg(target_arch = "x86_64")]
    if use_avx2() {
        // SAFETY: use_avx2() verified AVX2 support on this CPU at runtime.
        unsafe { bin_2d_count_avx2(x, y, x0, x1, y0, y1, w, h, grid) };
        return true;
    }
    let _ = (x, y, x0, x1, y0, y1, w, h, grid);
    false
}

#[expect(clippy::too_many_arguments, reason = "window + output, same as range_scan")]
pub(crate) fn try_range_scan(
    x: &[f64],
    y: &[f64],
    base: u32,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out: &mut [u32],
) -> Option<usize> {
    #[cfg(target_arch = "x86_64")]
    if use_avx2() {
        // SAFETY: use_avx2() verified AVX2 support on this CPU at runtime.
        return Some(unsafe { range_scan_avx2(x, y, base, lo_x, hi_x, lo_y, hi_y, out) });
    }
    let _ = (x, y, base, lo_x, hi_x, lo_y, hi_y, out);
    None
}

#[expect(clippy::too_many_arguments, reason = "window + grid, same as local_log_density")]
pub(crate) fn try_density_gather(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    grid: &[f32],
    out: &mut [f32],
) -> bool {
    #[cfg(target_arch = "x86_64")]
    if use_avx2() {
        // SAFETY: use_avx2() verified AVX2 support on this CPU at runtime.
        unsafe { density_gather_avx2(x, y, lo_x, hi_x, lo_y, hi_y, w, h, grid, out) };
        return true;
    }
    let _ = (x, y, lo_x, hi_x, lo_y, hi_y, w, h, grid, out);
    false
}

// ---------------------------------------------------------------------------
// Bitwise parity: SIMD vs scalar on hostile data. These run on any x86_64
// CI runner (all have AVX2) and no-op silently elsewhere.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernels;

    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            let mut x = self.0;
            x ^= x >> 12;
            x ^= x << 25;
            x ^= x >> 27;
            self.0 = x;
            x.wrapping_mul(0x2545F4914F6CDD1D)
        }
        fn f01(&mut self) -> f64 {
            (self.next() >> 11) as f64 / (1u64 << 53) as f64
        }
        fn hostile(&mut self, lo: f64, hi: f64) -> f64 {
            match self.next() % 16 {
                0 => f64::NAN,
                1 => f64::INFINITY,
                2 => f64::NEG_INFINITY,
                3 => 1e300,
                4 => -1e300,
                5 => 1e-300,
                6 => -0.0,
                _ => lo + self.f01() * (hi - lo),
            }
        }
        fn hostile_vec(&mut self, n: usize, lo: f64, hi: f64) -> Vec<f64> {
            (0..n).map(|_| self.hostile(lo, hi)).collect()
        }
    }

    #[test]
    fn simd_parity_all_kernels() {
        if !use_avx2() {
            eprintln!("simd_parity_all_kernels: no AVX2 (or disabled), skipping");
            return;
        }
        let mut rng = Rng(0x51D_0001);
        for it in 0..200 {
            // Sizes straddle BLOCK so partial tail blocks are exercised.
            let n = (rng.next() % (3 * BLOCK as u64)) as usize;
            let x = rng.hostile_vec(n, -10.0, 10.0);
            let y = rng.hostile_vec(n, -10.0, 10.0);
            let (x0, x1, y0, y1) = (-5.0, 7.0, -6.0, 4.0);
            let (w, h) = (1 + (rng.next() % 16) as usize, 1 + (rng.next() % 12) as usize);

            // min_max
            let simd_mm = try_min_max(&x).expect("avx2 on");
            assert_eq!(simd_mm, kernels::min_max_scalar(&x), "min_max it={it}");

            // bin_2d counting
            let mut gs = vec![0u32; w * h];
            kernels::bin_2d_count_scalar(&x, &y, x0, x1, y0, y1, w, h, &mut gs);
            let mut gv = vec![0u32; w * h];
            assert!(try_bin_2d_count(&x, &y, x0, x1, y0, y1, w, h, &mut gv));
            assert_eq!(gs, gv, "bin_2d it={it}");

            // range scan
            let mut rs = vec![0u32; n.max(1)];
            let ns = kernels::range_scan_scalar(&x, &y, 7, x0, x1, y0, y1, &mut rs[..n]);
            let mut rv = vec![0u32; n.max(1)];
            let nv = try_range_scan(&x, &y, 7, x0, x1, y0, y1, &mut rv[..n]).expect("avx2 on");
            assert_eq!((ns, &rs[..ns]), (nv, &rv[..nv]), "range it={it}");

            // density gather over a synthetic normalized grid
            let grid: Vec<f32> = (0..w * h).map(|c| (c % 7) as f32 / 7.0).collect();
            let mut os = vec![0f32; n];
            kernels::density_gather_scalar(&x, &y, x0, x1, y0, y1, w, h, &grid, &mut os);
            let mut ov = vec![0f32; n];
            assert!(try_density_gather(&x, &y, x0, x1, y0, y1, w, h, &grid, &mut ov));
            let bits = |v: &[f32]| v.iter().map(|f| f.to_bits()).collect::<Vec<u32>>();
            assert_eq!(bits(&os), bits(&ov), "gather it={it}");
        }
    }
}
