//! Multi-resolution count pyramid (§5 Tier 3 / LOD doc phase 3).
//!
//! Converts the per-viewport O(N) re-bin into O(N) once at build plus
//! O(visible cells) per interaction. Levels are square count grids over the
//! trace's full data bounds: level 0 is `base_dim`², each higher level is a
//! 4→1 exact sum (u64 accumulate, saturating to u32), so every level
//! conserves total count bit-exactly.
//!
//! `compose` fills a render grid for a view window from the coarsest level
//! that still meets the render resolution (bounded upsampling), assigning
//! each source cell to the output bin containing its center — deterministic
//! and count-conserving over whole cells; windows that outresolve level 0
//! are refused (caller falls back to an exact re-bin, disclosed per §28).
//!
//! No unsafe here; the C-ABI shell in lib.rs owns marshaling. Handles are
//! slab indices behind a Mutex (engine doc §3.3): stale/double-freed handles
//! are error codes, never UB.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

use crate::kernels;

pub struct Pyramid {
    /// levels[0] = finest (dim²), levels[k] has dim >> k per side; last is 1².
    levels: Vec<Vec<u32>>,
    dims: Vec<usize>,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
}

/// Max upsampling allowed before compose refuses: rendering source cells
/// into an output grid finer than 2x reads as blur/blocks — beyond that the
/// exact path must run (and at drill-scale windows it does anyway).
const MAX_UPSAMPLE: usize = 2;

pub fn build(x: &[f64], y: &[f64], x0: f64, x1: f64, y0: f64, y1: f64, base_dim: usize) -> Option<Pyramid> {
    if x.len() != y.len() || base_dim < 2 || !base_dim.is_power_of_two() {
        return None;
    }
    if !(x0.is_finite() && x1.is_finite() && y0.is_finite() && y1.is_finite() && x1 > x0 && y1 > y0) {
        return None;
    }
    let grid = kernels::bin_2d_counts(x, y, x0, x1, y0, y1, base_dim, base_dim);
    let mut levels: Vec<Vec<u32>> = Vec::new();
    let mut dims = Vec::new();
    levels.push(grid);
    dims.push(base_dim);
    let mut dim = base_dim;
    while dim > 1 {
        let prev = levels.last().expect("at least one level");
        let lvl = reduce_level(prev, dim);
        dim /= 2;
        levels.push(lvl);
        dims.push(dim);
    }
    Some(Pyramid { levels, dims, x0, x1, y0, y1 })
}

/// 4→1 exact reduction of one square level: each output cell is the u64 sum
/// of its 2×2 source block, saturating to u32 (§5 — every level conserves the
/// total exactly, up to saturation). Row slices + `chunks_exact(2)` keep the
/// inner loop free of bounds checks so it autovectorizes.
fn reduce_level(prev: &[u32], dim: usize) -> Vec<u32> {
    let next = dim / 2;
    let mut lvl = vec![0u32; next * next];
    for (cy, out_row) in lvl.chunks_exact_mut(next).enumerate() {
        let top = &prev[2 * cy * dim..2 * cy * dim + dim];
        let bot = &prev[(2 * cy + 1) * dim..(2 * cy + 1) * dim + dim];
        for ((o, t), b) in out_row
            .iter_mut()
            .zip(top.chunks_exact(2))
            .zip(bot.chunks_exact(2))
        {
            let a = t[0] as u64 + t[1] as u64 + b[0] as u64 + b[1] as u64;
            *o = a.min(u32::MAX as u64) as u32;
        }
    }
    lvl
}

/// Cell-index range [lo, hi) of a level whose cell CENTERS fall inside the
/// window along one axis.
fn center_range(lo: f64, hi: f64, full_lo: f64, full_hi: f64, dim: usize) -> (usize, usize) {
    let cell = (full_hi - full_lo) / dim as f64;
    // center of cell i is full_lo + (i + 0.5) * cell; inside ⇔ lo <= c < hi
    let first = ((lo - full_lo) / cell - 0.5).ceil().max(0.0) as usize;
    let last = (((hi - full_lo) / cell - 0.5).floor() as isize + 1).max(0) as usize;
    (first.min(dim), last.min(dim))
}

/// Approximate in-window count from the finest level (whole cells whose
/// centers are inside). Exact when the window aligns with cell edges.
pub fn count(p: &Pyramid, lo_x: f64, hi_x: f64, lo_y: f64, hi_y: f64) -> f64 {
    let dim = p.dims[0];
    let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
    let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
    if cx1 <= cx0 || cy1 <= cy0 {
        return 0.0;
    }
    let mut total = 0u64;
    let lvl = &p.levels[0];
    for cy in cy0..cy1 {
        // Per-row slice so the u32→u64 widen-add autovectorizes; integer sums
        // are order-independent, so the total is unchanged.
        let row = &lvl[cy * dim + cx0..cy * dim + cx1];
        total += row.iter().map(|&c| c as u64).sum::<u64>();
    }
    total as f64
}

/// Fill `out` (w×h, row-major, row 0 = bottom, same contract as bin_2d) for
/// the window from the coarsest adequate level. Returns the level used, or
/// None when even level 0 cannot meet the resolution (window too small).
#[allow(clippy::too_many_arguments)]
pub fn compose(
    p: &Pyramid,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    out: &mut [f32],
) -> Option<usize> {
    if w == 0 || h == 0 || out.len() != w * h {
        return None;
    }
    if !(hi_x > lo_x && hi_y > lo_y) {
        return None;
    }
    // Pick the coarsest level that still meets the render resolution without
    // upsampling (fewest cells to walk, no blur). Only when even level 0
    // cannot meet it, tolerate up to MAX_UPSAMPLE before refusing — beyond
    // that the exact path must run.
    let mut chosen: Option<usize> = None;
    for level in (0..p.levels.len()).rev() {
        let dim = p.dims[level];
        let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
        let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
        if cx1 - cx0 >= w && cy1 - cy0 >= h {
            chosen = Some(level);
            break;
        }
    }
    if chosen.is_none() {
        let dim = p.dims[0];
        let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
        let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
        if (cx1 - cx0) * MAX_UPSAMPLE >= w && (cy1 - cy0) * MAX_UPSAMPLE >= h {
            chosen = Some(0);
        }
    }
    let level = chosen?;
    let dim = p.dims[level];
    let lvl = &p.levels[level];
    for c in out.iter_mut() {
        *c = 0.0;
    }
    let cell_x = (p.x1 - p.x0) / dim as f64;
    let cell_y = (p.y1 - p.y0) / dim as f64;
    let sx = w as f64 / (hi_x - lo_x);
    let sy = h as f64 / (hi_y - lo_y);
    let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
    let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
    // center_range can yield cx1 < cx0 for windows astronomically past the
    // domain (the isize+1 in it wraps); the indexed loop iterated that as
    // empty, but slicing would panic — keep the empty-window behavior.
    if cx0 < cx1 {
        // ox depends only on cx: hoist the center→output-bin math (same f64
        // expression, so identical bins) out of the per-row loop.
        let ox_of: Vec<u32> = (cx0..cx1)
            .map(|cx| {
                let xcen = p.x0 + (cx as f64 + 0.5) * cell_x;
                (((xcen - lo_x) * sx) as usize).min(w - 1) as u32
            })
            .collect();
        for cy in cy0..cy1 {
            let ycen = p.y0 + (cy as f64 + 0.5) * cell_y;
            let oy = (((ycen - lo_y) * sy) as usize).min(h - 1);
            let row = &lvl[cy * dim + cx0..cy * dim + cx1];
            let out_row = &mut out[oy * w..(oy + 1) * w];
            for (&c, &ox) in row.iter().zip(ox_of.iter()) {
                if c == 0 {
                    continue;
                }
                out_row[ox as usize] += c as f32;
            }
        }
    }
    Some(level)
}

// -- handle registry (engine doc §3.3) ---------------------------------------

// Pyramids are stored as `Arc` so lookups can clone the handle out and drop
// the registry lock before running any compute: holding the mutex across a
// whole compose/count would serialize every pyramid operation process-wide,
// and a panic inside the closure would poison the registry permanently,
// bricking all later pyramid calls.
/// `(next_handle, live pyramids)` — the registry state behind the lock.
type Registry = (u64, HashMap<u64, Arc<Pyramid>>);

static REGISTRY: OnceLock<Mutex<Registry>> = OnceLock::new();

fn registry() -> &'static Mutex<Registry> {
    REGISTRY.get_or_init(|| Mutex::new((0, HashMap::new())))
}

pub fn reg_insert(p: Pyramid) -> u64 {
    let mut g = registry().lock().expect("pyramid registry poisoned");
    g.0 += 1;
    let h = g.0;
    g.1.insert(h, Arc::new(p));
    h
}

pub fn reg_with<R>(h: u64, f: impl FnOnce(&Pyramid) -> R) -> Option<R> {
    let p = {
        let g = registry().lock().expect("pyramid registry poisoned");
        g.1.get(&h).cloned()
    }; // lock dropped here — compute runs unserialized
    p.map(|p| f(&p))
}

pub fn reg_remove(h: u64) -> bool {
    let mut g = registry().lock().expect("pyramid registry poisoned");
    g.1.remove(&h).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cross(n: usize) -> (Vec<f64>, Vec<f64>) {
        // deterministic scattered points in [0,100)²
        let mut x = Vec::with_capacity(n);
        let mut y = Vec::with_capacity(n);
        let mut s = 0x5EED_1234_u64;
        for _ in 0..n {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            x.push((s % 10_000) as f64 / 100.0);
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            y.push((s % 10_000) as f64 / 100.0);
        }
        (x, y)
    }

    #[test]
    fn pyramid_levels_conserve_total() {
        let (x, y) = cross(5000);
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        let totals: Vec<u64> = p
            .levels
            .iter()
            .map(|l| l.iter().map(|&c| c as u64).sum())
            .collect();
        for t in &totals {
            assert_eq!(*t, totals[0], "every level conserves the total");
        }
        assert_eq!(totals[0], 5000);
    }

    #[test]
    fn compose_full_window_matches_bin2d_exactly() {
        let (x, y) = cross(4000);
        let dim = 64;
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, dim).unwrap();
        let mut composed = vec![0.0f32; dim * dim];
        let level = compose(&p, 0.0, 100.0, 0.0, 100.0, dim, dim, &mut composed).unwrap();
        assert_eq!(level, 0);
        let mut direct = vec![0.0f32; dim * dim];
        kernels::bin_2d(&x, &y, 0.0, 100.0, 0.0, 100.0, dim, dim, &mut direct);
        assert_eq!(composed, direct, "full-window compose is the exact base grid");
    }

    #[test]
    fn compose_aligned_subwindow_matches_bin2d() {
        let (x, y) = cross(6000);
        let dim = 64;
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, dim).unwrap();
        // window aligned to level-0 cell edges: [25,75)² = cells 16..48
        let (w, h) = (32, 32);
        let mut composed = vec![0.0f32; w * h];
        let level = compose(&p, 25.0, 75.0, 25.0, 75.0, w, h, &mut composed).unwrap();
        assert_eq!(level, 0);
        let mut direct = vec![0.0f32; w * h];
        kernels::bin_2d(&x, &y, 25.0, 75.0, 25.0, 75.0, w, h, &mut direct);
        assert_eq!(composed, direct, "cell-aligned windows are exact");
    }

    #[test]
    fn compose_conserves_count_and_refuses_deep_zoom() {
        let (x, y) = cross(4000);
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        let (w, h) = (16, 16);
        let mut g = vec![0.0f32; w * h];
        let lvl = compose(&p, 10.0, 60.0, 20.0, 70.0, w, h, &mut g).unwrap();
        let total: f64 = g.iter().map(|&c| c as f64).sum();
        // count() reads level 0; compose may use a coarser level whose edge
        // cells differ slightly — whole-cell approximation, small at the rim.
        let c0 = count(&p, 10.0, 60.0, 20.0, 70.0);
        assert!((total - c0).abs() <= c0 * 0.02, "conservation within edge band: {total} vs {c0}");
        assert!(lvl > 0, "16x16 render over half the domain uses a coarser level");
        // deeper than level 0 can resolve at 2x upsample -> refused
        let mut tiny = vec![0.0f32; 512 * 512];
        assert!(compose(&p, 50.0, 51.0, 50.0, 51.0, 512, 512, &mut tiny).is_none());
    }

    #[test]
    fn reduce_level_sums_blocks_and_saturates() {
        // 4x4 of 0..16 -> 2x2: each output is the exact sum of its 2x2 block,
        // e.g. top-left block {0, 1, 4, 5} sums to 10.
        let prev: Vec<u32> = (0..16).collect();
        assert_eq!(reduce_level(&prev, 4), vec![10, 18, 42, 50]);
        // Block sums accumulate in u64 and clamp to u32::MAX — never wrap.
        let big = vec![u32::MAX; 4];
        assert_eq!(reduce_level(&big, 2), vec![u32::MAX]);
        let mixed = vec![u32::MAX, 1, 0, 0];
        assert_eq!(reduce_level(&mixed, 2), vec![u32::MAX]);
    }

    #[test]
    fn count_matches_scalar_reference_and_handles_reversed_window() {
        let (x, y) = cross(5000);
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        let dim = p.dims[0];
        let (cx0, cx1) = center_range(13.0, 87.5, p.x0, p.x1, dim);
        let (cy0, cy1) = center_range(22.4, 61.0, p.y0, p.y1, dim);
        let mut reference = 0u64;
        for cy in cy0..cy1 {
            for cx in cx0..cx1 {
                reference += p.levels[0][cy * dim + cx] as u64;
            }
        }
        assert_eq!(count(&p, 13.0, 87.5, 22.4, 61.0), reference as f64);
        // degenerate/reversed windows count zero cells, never panic
        assert_eq!(count(&p, 90.0, 10.0, 0.0, 100.0), 0.0);
        assert_eq!(count(&p, 50.0, 50.0, 0.0, 100.0), 0.0);
    }

    // Release-only: in debug builds center_range's `as isize + 1` panics on
    // these magnitudes (pre-existing, caught by ffi_guard at the ABI); the
    // wrap to cx1 < cx0 that reaches compose's row slicing only occurs in
    // release, where the old indexed loop silently iterated it as empty.
    #[cfg(not(debug_assertions))]
    #[test]
    fn compose_window_astronomically_past_domain_is_empty_not_panic() {
        let (x, y) = cross(4000);
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        // hi so far past the domain that center_range saturates and wraps:
        // cx range comes back reversed (cx0=32, cx1=0). Must compose to an
        // all-zero grid with a level, exactly like the pre-slicing code.
        let (w, h) = (2, 2);
        let mut g = vec![7.0f32; w * h];
        let level = compose(&p, 50.0, 1.0e21, 0.0, 100.0, w, h, &mut g);
        assert!(level.is_some());
        assert!(g.iter().all(|&c| c == 0.0), "wrapped window composes empty");
        // nanosecond-epoch-scale garbage coordinates over a small domain
        // (realistic bad input) must also never panic.
        let mut g2 = vec![0.0f32; w * h];
        let _ = compose(&p, 1.0e18, 1.75e18, 0.0, 100.0, w, h, &mut g2);
    }

    #[test]
    fn registry_roundtrip_and_stale_handle() {
        let (x, y) = cross(100);
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 8).unwrap();
        let h = reg_insert(p);
        assert!(h > 0);
        let total = reg_with(h, |p| count(p, 0.0, 100.0, 0.0, 100.0)).unwrap();
        assert_eq!(total, 100.0);
        assert!(reg_remove(h));
        assert!(!reg_remove(h), "double free is an error, not UB");
        assert!(reg_with(h, |_| ()).is_none(), "stale handle is refused");
    }
}
