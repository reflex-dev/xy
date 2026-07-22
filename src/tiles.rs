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
    /// Mean-color planes for channel-bearing traces (LOD doc §2): per cell
    /// `[r, g, b, a]` — the alpha-weighted mean point color in linear-light
    /// u16 plus the mean straight alpha scaled to 0..=65535. Means (not sums)
    /// keep the planes at 8 B/cell; each 4→1 reduction re-rounds once, a
    /// ≤ 0.5-lsb-of-u16 error per level (recorded in the LOD doc, §28).
    /// `None` for count-only pyramids; those compose counts only.
    color_levels: Option<Vec<Vec<[u16; 4]>>>,
    dims: Vec<usize>,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
}

impl Pyramid {
    pub fn has_color(&self) -> bool {
        self.color_levels.is_some()
    }
}

/// Max upsampling allowed before compose refuses: rendering source cells
/// into an output grid finer than 2x reads as blur/blocks — beyond that the
/// exact path must run (and at drill-scale windows it does anyway).
const MAX_UPSAMPLE: usize = 2;

pub fn build(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    base_dim: usize,
) -> Option<Pyramid> {
    if x.len() != y.len() || base_dim < 2 || !base_dim.is_power_of_two() {
        return None;
    }
    if !(x0.is_finite() && x1.is_finite() && y0.is_finite() && y1.is_finite() && x1 > x0 && y1 > y0)
    {
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
    Some(Pyramid {
        levels,
        color_levels: None,
        dims,
        x0,
        x1,
        y0,
        y1,
    })
}

/// Build a pyramid that also carries mean-color planes, for channel-bearing
/// traces whose density surface wears the mean point color (LOD doc §2).
/// One fused serial scan accumulates counts and alpha-weighted linear-light
/// color sums together (exact integer sums, so the result is independent of
/// row order); count levels are identical to `build`'s. The transient base
/// accumulator is 40 B/cell (~170 MB at the 2048² default) and is released
/// before the function returns — builds are one-time per trace and lazy.
#[allow(clippy::too_many_arguments)]
pub fn build_color(
    x: &[f64],
    y: &[f64],
    colors: &kernels::BinColorSource<'_>,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    base_dim: usize,
) -> Option<Pyramid> {
    if x.len() != y.len() || base_dim < 2 || !base_dim.is_power_of_two() {
        return None;
    }
    if !(x0.is_finite() && x1.is_finite() && y0.is_finite() && y1.is_finite() && x1 > x0 && y1 > y0)
    {
        return None;
    }
    match colors {
        kernels::BinColorSource::Indexed { idx, lut } => {
            if idx.len() != x.len() || lut.is_empty() || lut.len() > 256 {
                return None;
            }
        }
        kernels::BinColorSource::Rgba(rgba) => {
            if rgba.len() != x.len() * 4 {
                return None;
            }
        }
    }
    let base = kernels::bin_2d_mean_color_cells(x, y, colors, x0, x1, y0, y1, base_dim, base_dim);
    let mut counts = Vec::with_capacity(base.len());
    let mut color = Vec::with_capacity(base.len());
    for cell in &base {
        counts.push(cell.count);
        color.push(cell.mean_u16x4());
    }
    drop(base);
    let mut levels = vec![counts];
    let mut color_levels = vec![color];
    let mut dims = vec![base_dim];
    let mut dim = base_dim;
    while dim > 1 {
        let prev = levels.last().expect("at least one level");
        let prev_color = color_levels.last().expect("at least one color level");
        let lvl = reduce_level(prev, dim);
        let clvl = reduce_color_level(prev, prev_color, dim);
        dim /= 2;
        levels.push(lvl);
        color_levels.push(clvl);
        dims.push(dim);
    }
    Some(Pyramid {
        levels,
        color_levels: Some(color_levels),
        dims,
        x0,
        x1,
        y0,
        y1,
    })
}

/// Add a batch to an existing pyramid without rescanning its canonical prefix.
///
/// Every finite pair must remain inside the pyramid's original half-open
/// domain.  The caller rebuilds when an append expands that domain; validating
/// the complete batch before the first write keeps a rejected update atomic.
/// Non-finite pairs are ignored exactly like [`kernels::bin_2d_counts`].
pub fn append(p: &mut Pyramid, x: &[f64], y: &[f64]) -> bool {
    if x.len() != y.len() {
        return false;
    }
    // A colored pyramid cannot be incremented without the batch's colors —
    // and an append can also move a continuous channel's domain, silently
    // re-coloring every already-binned point. Refuse; the caller invalidates
    // and the next density view rebuilds lazily (LOD doc §4.1).
    if p.color_levels.is_some() {
        return false;
    }
    for (&xv, &yv) in x.iter().zip(y) {
        if (xv.is_finite() && yv.is_finite())
            && (xv < p.x0 || xv >= p.x1 || yv < p.y0 || yv >= p.y1)
        {
            return false;
        }
    }

    let base_dim = p.dims[0];
    let sx = base_dim as f64 / (p.x1 - p.x0);
    let sy = base_dim as f64 / (p.y1 - p.y0);
    for (&xv, &yv) in x.iter().zip(y) {
        if !xv.is_finite() || !yv.is_finite() {
            continue;
        }
        let mut cx = (((xv - p.x0) * sx) as usize).min(base_dim - 1);
        let mut cy = (((yv - p.y0) * sy) as usize).min(base_dim - 1);
        for (level, &dim) in p.levels.iter_mut().zip(&p.dims) {
            let cell = &mut level[cy * dim + cx];
            *cell = cell.saturating_add(1);
            cx >>= 1;
            cy >>= 1;
        }
    }
    true
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

/// 4→1 reduction of one color level. Each parent is the exact weighted mean
/// of its children — weight = child count × child mean alpha, the same
/// alpha-weighted average `bin_2d_mean_color` computes over raw points — then
/// re-rounded once to u16 (the ≤ 0.5-lsb-per-level error recorded on the
/// struct). u128 keeps the count×alpha×mean products exact even at saturated
/// child counts.
fn reduce_color_level(prev_counts: &[u32], prev_color: &[[u16; 4]], dim: usize) -> Vec<[u16; 4]> {
    let next = dim / 2;
    let mut lvl = vec![[0u16; 4]; next * next];
    for cy in 0..next {
        for cx in 0..next {
            let mut count: u64 = 0;
            let mut weight: u128 = 0;
            let mut sums = [0u128; 3];
            for (sy, sx) in [
                (2 * cy, 2 * cx),
                (2 * cy, 2 * cx + 1),
                (2 * cy + 1, 2 * cx),
                (2 * cy + 1, 2 * cx + 1),
            ] {
                let c = u64::from(prev_counts[sy * dim + sx]);
                if c == 0 {
                    continue;
                }
                let [r, g, b, a] = prev_color[sy * dim + sx];
                let w = u128::from(c) * u128::from(a);
                count += c;
                weight += w;
                sums[0] += w * u128::from(r);
                sums[1] += w * u128::from(g);
                sums[2] += w * u128::from(b);
            }
            if count == 0 || weight == 0 {
                continue;
            }
            let mean = |s: u128| ((s + weight / 2) / weight).min(u128::from(u16::MAX)) as u16;
            let alpha =
                ((weight + u128::from(count) / 2) / u128::from(count)).min(u128::from(u16::MAX));
            lvl[cy * next + cx] = [mean(sums[0]), mean(sums[1]), mean(sums[2]), alpha as u16];
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

/// Pick the coarsest level that still meets the render resolution without
/// upsampling (fewest cells to walk, no blur). Only when even level 0
/// cannot meet it, tolerate up to MAX_UPSAMPLE before refusing — beyond
/// that the exact path must run.
fn choose_level(
    p: &Pyramid,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
) -> Option<usize> {
    for level in (0..p.levels.len()).rev() {
        let dim = p.dims[level];
        let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
        let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
        if cx1 - cx0 >= w && cy1 - cy0 >= h {
            return Some(level);
        }
    }
    let dim = p.dims[0];
    let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
    let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
    if (cx1 - cx0) * MAX_UPSAMPLE >= w && (cy1 - cy0) * MAX_UPSAMPLE >= h {
        return Some(0);
    }
    None
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
    let level = choose_level(p, lo_x, hi_x, lo_y, hi_y, w, h)?;
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

/// `compose` plus the mean-color plane: fills the same f32 count grid (same
/// level choice, same center mapping, same accumulation order — bit-identical
/// counts) and a `w*h*4` straight-alpha RGBA8 grid whose cells carry the
/// weighted mean of the composed source cells' mean colors (weight = count ×
/// mean alpha, matching `bin_2d_mean_color` over raw points). Returns `None`
/// for windows the pyramid cannot serve, and for pyramids built without
/// color planes — the caller falls back to the exact scan either way.
#[allow(clippy::too_many_arguments)]
pub fn compose_color(
    p: &Pyramid,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    out: &mut [f32],
    out_rgba: &mut [u8],
) -> Option<usize> {
    let color_levels = p.color_levels.as_ref()?;
    if w == 0 || h == 0 || out.len() != w * h || out_rgba.len() != w * h * 4 {
        return None;
    }
    if !(hi_x > lo_x && hi_y > lo_y) {
        return None;
    }
    let level = choose_level(p, lo_x, hi_x, lo_y, hi_y, w, h)?;
    let dim = p.dims[level];
    let lvl = &p.levels[level];
    let clvl = &color_levels[level];
    for c in out.iter_mut() {
        *c = 0.0;
    }
    out_rgba.fill(0);
    // Per-output-cell exact accumulators (u128 keeps count×alpha×mean
    // products exact even at saturated counts; ~0.6 MB per 128×128 output
    // block of a typical screen grid, freed on return).
    #[derive(Clone, Copy, Default)]
    struct Acc {
        weight: u128,
        red: u128,
        green: u128,
        blue: u128,
        count: u64,
    }
    let mut acc = vec![Acc::default(); w * h];
    let cell_x = (p.x1 - p.x0) / dim as f64;
    let cell_y = (p.y1 - p.y0) / dim as f64;
    let sx = w as f64 / (hi_x - lo_x);
    let sy = h as f64 / (hi_y - lo_y);
    let (cx0, cx1) = center_range(lo_x, hi_x, p.x0, p.x1, dim);
    let (cy0, cy1) = center_range(lo_y, hi_y, p.y0, p.y1, dim);
    if cx0 < cx1 {
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
            let crow = &clvl[cy * dim + cx0..cy * dim + cx1];
            let out_row = &mut out[oy * w..(oy + 1) * w];
            let acc_row = &mut acc[oy * w..(oy + 1) * w];
            for ((&c, &[r, g, b, alpha]), &ox) in row.iter().zip(crow.iter()).zip(ox_of.iter()) {
                if c == 0 {
                    continue;
                }
                out_row[ox as usize] += c as f32;
                let a = &mut acc_row[ox as usize];
                let weight = u128::from(c) * u128::from(alpha);
                a.count += u64::from(c);
                a.weight += weight;
                a.red += weight * u128::from(r);
                a.green += weight * u128::from(g);
                a.blue += weight * u128::from(b);
            }
        }
    }
    for (a, quad) in acc.iter().zip(out_rgba.chunks_exact_mut(4)) {
        if a.count == 0 || a.weight == 0 {
            continue;
        }
        let mean =
            |s: u128| ((s + a.weight / 2) / a.weight).min(u128::from(u16::MAX)) as u16;
        // Stored alphas are u16-scaled (×257); the weighted mean over source
        // cells comes back on the same scale, so /257 restores the byte.
        let alpha_u16 =
            ((a.weight + u128::from(a.count) / 2) / u128::from(a.count)).min(u128::from(u16::MAX));
        quad[0] = kernels::linear_u16_to_srgb_u8(mean(a.red));
        quad[1] = kernels::linear_u16_to_srgb_u8(mean(a.green));
        quad[2] = kernels::linear_u16_to_srgb_u8(mean(a.blue));
        quad[3] = ((alpha_u16 + 128) / 257).min(255) as u8;
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

/// Mutate a registered pyramid when no compose/count currently holds a cloned
/// `Arc`.  A concurrent reader makes this return `None`; the caller can safely
/// fall back to invalidation + lazy rebuild without adding a lock to every
/// steady-state interaction read.
pub fn reg_append(h: u64, x: &[f64], y: &[f64]) -> Option<bool> {
    let mut g = registry().lock().expect("pyramid registry poisoned");
    let p = Arc::get_mut(g.1.get_mut(&h)?)?;
    Some(append(p, x, y))
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
    fn append_matches_a_full_rebuild_and_rejects_domain_growth_atomically() {
        let (x, y) = cross(5000);
        let tail_x = vec![10.0, 10.0, 50.0, 99.99, f64::NAN];
        let tail_y = vec![20.0, 20.0, 50.0, 0.01, 10.0];
        let mut incremental = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        assert!(append(&mut incremental, &tail_x, &tail_y));

        let mut all_x = x.clone();
        let mut all_y = y.clone();
        all_x.extend_from_slice(&tail_x);
        all_y.extend_from_slice(&tail_y);
        let rebuilt = build(&all_x, &all_y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        assert_eq!(incremental.levels, rebuilt.levels);

        let before = incremental.levels.clone();
        assert!(!append(&mut incremental, &[50.0, 100.0], &[50.0, 50.0]));
        assert_eq!(
            incremental.levels, before,
            "rejected append must not partially mutate"
        );
    }

    /// Deterministic two-color source: points left of x=50 wear LUT entry 0,
    /// the rest entry 1.
    fn split_idx(x: &[f64]) -> Vec<u8> {
        x.iter().map(|&v| u8::from(v >= 50.0)).collect()
    }

    const RED_BLUE: [[u8; 4]; 2] = [[255, 0, 0, 255], [0, 0, 255, 255]];

    #[test]
    fn colored_build_keeps_count_levels_and_rejects_append() {
        let (x, y) = cross(5000);
        let idx = split_idx(&x);
        let colors = kernels::BinColorSource::Indexed {
            idx: &idx,
            lut: &RED_BLUE,
        };
        let plain = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        let mut colored = build_color(&x, &y, &colors, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        assert_eq!(
            plain.levels, colored.levels,
            "color planes must not perturb the count pyramid"
        );
        assert!(colored.has_color() && !plain.has_color());
        let before = colored.levels.clone();
        assert!(
            !append(&mut colored, &[50.0], &[50.0]),
            "colored pyramids refuse increments (colors unknown, domain may shift)"
        );
        assert_eq!(colored.levels, before);
    }

    #[test]
    fn compose_color_counts_match_compose_and_colors_match_kernel() {
        let (x, y) = cross(6000);
        let idx = split_idx(&x);
        let colors = kernels::BinColorSource::Indexed {
            idx: &idx,
            lut: &RED_BLUE,
        };
        let dim = 64;
        let p = build_color(&x, &y, &colors, 0.0, 100.0, 0.0, 100.0, dim).unwrap();
        let mut counts = vec![0.0f32; dim * dim];
        let mut rgba = vec![0u8; dim * dim * 4];
        let level =
            compose_color(&p, 0.0, 100.0, 0.0, 100.0, dim, dim, &mut counts, &mut rgba).unwrap();
        assert_eq!(level, 0);
        let mut plain = vec![0.0f32; dim * dim];
        assert_eq!(
            compose(&p, 0.0, 100.0, 0.0, 100.0, dim, dim, &mut plain),
            Some(0)
        );
        assert_eq!(counts, plain, "count grid is bit-identical to compose");
        let mut direct = vec![0u8; dim * dim * 4];
        kernels::bin_2d_mean_color(&x, &y, &colors, 0.0, 100.0, 0.0, 100.0, dim, dim, &mut direct);
        assert_eq!(
            rgba, direct,
            "full-window level-0 compose reproduces the direct mean-color grid"
        );
    }

    #[test]
    fn compose_color_zoomed_out_levels_stay_pure_per_side() {
        // All-red left half, all-blue right half: any pyramid level keeps
        // each side's cells exactly pure, and mean alpha stays opaque.
        let (x, y) = cross(8000);
        let idx = split_idx(&x);
        let colors = kernels::BinColorSource::Indexed {
            idx: &idx,
            lut: &RED_BLUE,
        };
        let p = build_color(&x, &y, &colors, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        let (w, h) = (8, 8);
        let mut counts = vec![0.0f32; w * h];
        let mut rgba = vec![0u8; w * h * 4];
        let level =
            compose_color(&p, 0.0, 100.0, 0.0, 100.0, w, h, &mut counts, &mut rgba).unwrap();
        assert!(level > 0, "an 8x8 render must come from a coarser level");
        for cy in 0..h {
            for cx in 0..w {
                let quad = &rgba[(cy * w + cx) * 4..(cy * w + cx) * 4 + 4];
                if counts[cy * w + cx] <= 0.0 {
                    assert_eq!(quad, [0, 0, 0, 0]);
                    continue;
                }
                let expect = if cx < w / 2 { RED_BLUE[0] } else { RED_BLUE[1] };
                assert_eq!(
                    quad, expect,
                    "pure-side cell at ({cx},{cy}) must keep its exact color"
                );
            }
        }
    }

    #[test]
    fn compose_color_without_planes_or_bad_shapes_refuses() {
        let (x, y) = cross(4000);
        let p = build(&x, &y, 0.0, 100.0, 0.0, 100.0, 64).unwrap();
        let mut counts = vec![0.0f32; 16];
        let mut rgba = vec![0u8; 64];
        assert_eq!(
            compose_color(&p, 0.0, 100.0, 0.0, 100.0, 4, 4, &mut counts, &mut rgba),
            None,
            "count-only pyramids refuse color composition"
        );
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
        assert_eq!(
            composed, direct,
            "full-window compose is the exact base grid"
        );
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
        assert!(
            (total - c0).abs() <= c0 * 0.02,
            "conservation within edge band: {total} vs {c0}"
        );
        assert!(
            lvl > 0,
            "16x16 render over half the domain uses a coarser level"
        );
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
        assert_eq!(reg_append(h, &[50.0], &[50.0]), Some(true));
        let total = reg_with(h, |p| count(p, 0.0, 100.0, 0.0, 100.0)).unwrap();
        assert_eq!(total, 101.0);
        assert!(reg_remove(h));
        assert!(!reg_remove(h), "double free is an error, not UB");
        assert!(reg_with(h, |_| ()).is_none(), "stale handle is refused");
    }
}
