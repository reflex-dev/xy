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
        let next = dim / 2;
        let prev = levels.last().expect("at least one level");
        let mut lvl = vec![0u32; next * next];
        for cy in 0..next {
            for cx in 0..next {
                let a = prev[(2 * cy) * dim + 2 * cx] as u64
                    + prev[(2 * cy) * dim + 2 * cx + 1] as u64
                    + prev[(2 * cy + 1) * dim + 2 * cx] as u64
                    + prev[(2 * cy + 1) * dim + 2 * cx + 1] as u64;
                lvl[cy * next + cx] = a.min(u32::MAX as u64) as u32;
            }
        }
        levels.push(lvl);
        dims.push(next);
        dim = next;
    }
    Some(Pyramid { levels, dims, x0, x1, y0, y1 })
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
    let mut total = 0u64;
    let lvl = &p.levels[0];
    for cy in cy0..cy1 {
        for cx in cx0..cx1 {
            total += lvl[cy * dim + cx] as u64;
        }
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
    for cy in cy0..cy1 {
        let ycen = p.y0 + (cy as f64 + 0.5) * cell_y;
        let oy = (((ycen - lo_y) * sy) as usize).min(h - 1);
        for cx in cx0..cx1 {
            let c = lvl[cy * dim + cx];
            if c == 0 {
                continue;
            }
            let xcen = p.x0 + (cx as f64 + 0.5) * cell_x;
            let ox = (((xcen - lo_x) * sx) as usize).min(w - 1);
            out[oy * w + ox] += c as f32;
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
