//! Pure compute kernels for the charting engine.
//!
//! Design dossier references:
//! - Zone maps (§22): one-pass per-chunk statistics, computed at ingest.
//! - Offset+scale f32 encoding (§4, §16): full-precision f64/i64 canonical data is
//!   uploaded to the GPU as *relative* f32 — `(v - offset) * scale` — so
//!   large-magnitude/small-delta domains (ms timestamps, finance, geo) keep the
//!   digits that matter. Deep zoom re-centers the offset (§16); the kernel takes the
//!   offset explicitly so the caller owns that policy.
//! - M4 decimation (§5 Tier 1, research Part 2 §2): per pixel column keep
//!   first/min/max/last — provably pixel-accurate for a rasterized line (Jugel et
//!   al., VLDB 2014). NaN-aware: buckets never span invalid values silently (§19).

/// One-pass statistics for a chunk of a column (§22).
///
/// Non-finite values (NaN and ±∞) count as nulls: neither is plottable, both
/// corrupt GPU primitives if they reach a vertex buffer (§19), and ∞ would
/// poison min/max/sum for autorange. Treating them uniformly as invalid is what
/// lets autorange, `null_count`, and the ship-time drop all agree. (Arrow
/// validity bitmaps arrive later; non-finite-as-null is the Phase-0 contract.)
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ZoneMap {
    pub min: f64,
    pub max: f64,
    pub count: u64,
    pub null_count: u64,
    pub sum: f64,
    pub sum_sq: f64,
}

impl ZoneMap {
    pub fn empty() -> Self {
        ZoneMap {
            min: f64::INFINITY,
            max: f64::NEG_INFINITY,
            count: 0,
            null_count: 0,
            sum: 0.0,
            sum_sq: 0.0,
        }
    }
}

/// Default chunk size: ~64k values (§22).
pub const DEFAULT_CHUNK: usize = 65_536;

/// Compute zone maps over `data` in chunks of `chunk_size`.
pub fn zone_maps(data: &[f64], chunk_size: usize) -> Vec<ZoneMap> {
    assert!(chunk_size > 0, "chunk_size must be positive");
    data.chunks(chunk_size)
        .map(|chunk| {
            let mut zm = ZoneMap::empty();
            for &v in chunk {
                if !v.is_finite() {
                    zm.null_count += 1;
                } else {
                    zm.count += 1;
                    zm.min = zm.min.min(v);
                    zm.max = zm.max.max(v);
                    zm.sum += v;
                    zm.sum_sq += v * v;
                }
            }
            zm
        })
        .collect()
}

/// Encode canonical f64 values as relative f32: `(v - offset) * scale` (§4).
///
/// NaN passes through as f32 NaN — the caller is responsible for keeping NaN out
/// of vertex buffers via the gap/segment machinery (§19); passing it through here
/// keeps the kernel total rather than silently inventing values.
pub fn encode_f32(data: &[f64], offset: f64, scale: f64, out: &mut Vec<f32>) {
    out.clear();
    out.reserve(data.len());
    // Simple loop autovectorizes; keep it branch-free on the hot path.
    out.extend(data.iter().map(|&v| ((v - offset) * scale) as f32));
}

/// As [`encode_f32`] but into a caller-owned slice (the C ABI path — the output
/// buffer is a NumPy array allocated Python-side, so no copy on return).
pub fn encode_f32_into(data: &[f64], offset: f64, scale: f64, out: &mut [f32]) {
    assert_eq!(data.len(), out.len());
    for (o, &v) in out.iter_mut().zip(data) {
        *o = ((v - offset) * scale) as f32;
    }
}

/// M4 decimation (§5 Tier 1): for `n_buckets` uniform buckets over `[x0, x1)`,
/// return the source indices of {first, min-y, max-y, last} per bucket, sorted
/// ascending and deduplicated.
///
/// Requirements (per the LOD contract, §28): `x` ascending (engine sorts once at
/// ingest for line traces), `x.len() == y.len()`. Points with NaN y are skipped —
/// min/max buckets never span a gap (§19); gap segmentation itself is a later
/// milestone.
pub fn m4_indices(x: &[f64], y: &[f64], x0: f64, x1: f64, n_buckets: usize) -> Vec<u32> {
    assert_eq!(x.len(), y.len());
    assert!(n_buckets > 0);
    assert!(x1_gt_x0(x0, x1), "x1 must be finite and > x0");
    if x.is_empty() {
        return Vec::new();
    }

    // Visible window via binary search (x sorted ascending).
    let start = x.partition_point(|&v| v < x0);
    let end = x.partition_point(|&v| v < x1);
    if start >= end {
        return Vec::new();
    }

    let inv_bucket_w = n_buckets as f64 / (x1 - x0);
    let mut out: Vec<u32> = Vec::with_capacity(n_buckets * 4);

    // Per-bucket running state.
    let mut cur_bucket = usize::MAX;
    let mut first = 0u32;
    let mut last = 0u32;
    let mut min_i = 0u32;
    let mut max_i = 0u32;
    let mut min_v = f64::INFINITY;
    let mut max_v = f64::NEG_INFINITY;
    let mut has_any = false;

    let flush = |first: u32, min_i: u32, max_i: u32, last: u32, out: &mut Vec<u32>| {
        let mut ids = [first, min_i, max_i, last];
        ids.sort_unstable();
        let mut prev = u32::MAX;
        for id in ids {
            if id != prev {
                out.push(id);
                prev = id;
            }
        }
    };

    for i in start..end {
        let yv = y[i];
        if !yv.is_finite() {
            continue; // NaN and ±∞ are non-plottable (§19)
        }
        let b = (((x[i] - x0) * inv_bucket_w) as usize).min(n_buckets - 1);
        if b != cur_bucket {
            if has_any {
                flush(first, min_i, max_i, last, &mut out);
            }
            cur_bucket = b;
            first = i as u32;
            min_i = i as u32;
            max_i = i as u32;
            min_v = yv;
            max_v = yv;
            has_any = true;
        } else {
            if yv < min_v {
                min_v = yv;
                min_i = i as u32;
            }
            if yv > max_v {
                max_v = yv;
                max_i = i as u32;
            }
        }
        last = i as u32;
    }
    if has_any {
        flush(first, min_i, max_i, last, &mut out);
    }
    out
}

/// 2D density aggregation (§5 Tier 2): additively bin points into a `w × h`
/// grid over `[x0, x1) × [y0, y1)`, one count per cell. Points with NaN in
/// either coordinate, or outside the viewport, are skipped. Output is f32
/// (ready for direct texture upload; colormapping happens at composite time on
/// the client, so restyle never re-bins — §5).
///
/// `out` must be `w * h` long; it is fully overwritten (zeroed then filled).
/// Row-major, row 0 = bottom (`y0`), matching GL texture coordinates.
///
/// This is the "bin the visible window" path (datashader's interactive model,
/// §5 research): O(visible points) per viewport change, screen-bounded output.
/// The live tile pyramid that makes pan/zoom O(visible tiles) is a later
/// milestone; this is the correct, honest Tier-2 MVP.
#[allow(clippy::too_many_arguments)] // viewport (x0,x1,y0,y1) + grid (w,h) + io is irreducible
pub fn bin_2d(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    out: &mut [f32],
) {
    assert_eq!(x.len(), y.len());
    assert_eq!(out.len(), w * h);
    assert!(w > 0 && h > 0 && x1_gt_x0(x0, x1) && x1_gt_x0(y0, y1));
    for c in out.iter_mut() {
        *c = 0.0;
    }
    let sx = w as f64 / (x1 - x0);
    let sy = h as f64 / (y1 - y0);
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        // Non-finite fails the range comparisons already, but check explicitly
        // so intent is clear and -∞/∞ can never index a cell.
        if !xv.is_finite() || !yv.is_finite() || xv < x0 || xv >= x1 || yv < y0 || yv >= y1 {
            continue;
        }
        let cx = ((xv - x0) * sx) as usize;
        let cy = ((yv - y0) * sy) as usize;
        // Guard the top/right edge against f64 rounding landing exactly on w/h.
        let cx = cx.min(w - 1);
        let cy = cy.min(h - 1);
        out[cy * w + cx] += 1.0;
    }
}

/// Uniform-bin histogram over `[lo, hi]` with the last bin closed, matching
/// NumPy's fixed-bin behavior for the common chart path. Non-finite values and
/// values outside the range are skipped. `out` is fully overwritten.
pub fn histogram_uniform(data: &[f64], lo: f64, hi: f64, out: &mut [f64]) -> u64 {
    assert!(x1_gt_x0(lo, hi));
    assert!(!out.is_empty());
    for c in out.iter_mut() {
        *c = 0.0;
    }
    let n_bins = out.len();
    let scale = n_bins as f64 / (hi - lo);
    let mut total = 0u64;
    for &v in data {
        if !v.is_finite() || v < lo || v > hi {
            continue;
        }
        let idx = if v == hi {
            n_bins - 1
        } else {
            (((v - lo) * scale) as usize).min(n_bins - 1)
        };
        out[idx] += 1.0;
        total += 1;
    }
    total
}

/// Normalize values over `[lo, hi]` into f32 `[0,1]`. Non-finite values either
/// become 0.0 (channel path: no poison vertices) or NaN (heatmap path:
/// transparent missing cells on the client).
pub fn normalize_f32_into(data: &[f64], lo: f64, hi: f64, nan_value: f32, out: &mut [f32]) {
    assert_eq!(data.len(), out.len());
    assert!(x1_gt_x0(lo, hi));
    let span = hi - lo;
    for (dst, &v) in out.iter_mut().zip(data) {
        if v.is_finite() {
            *dst = (((v - lo) / span).clamp(0.0, 1.0)) as f32;
        } else {
            *dst = nan_value;
        }
    }
}

/// Canonical row indices inside a rectangular window. Bounds are inclusive to
/// match the existing Python selection/drill path.
pub fn range_indices(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out: &mut [u32],
) -> usize {
    assert_eq!(x.len(), y.len());
    assert!(out.len() >= x.len());
    let mut n = 0usize;
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        if xv >= lo_x && xv <= hi_x && yv >= lo_y && yv <= hi_y {
            out[n] = i as u32;
            n += 1;
        }
    }
    n
}

/// Per-point log-normalized local density for a subset. This fuses the
/// grid-bin + point-lookup pass used during drill handoff, avoiding Python-side
/// integer temp arrays.
#[allow(clippy::too_many_arguments)]
pub fn local_log_density(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    out: &mut [f32],
) {
    assert_eq!(x.len(), y.len());
    assert_eq!(x.len(), out.len());
    assert!(w > 0 && h > 0 && x1_gt_x0(lo_x, hi_x) && x1_gt_x0(lo_y, hi_y));
    for v in out.iter_mut() {
        *v = 0.0;
    }
    if x.is_empty() {
        return;
    }
    let mut grid = vec![0.0f32; w * h];
    bin_2d(x, y, lo_x, hi_x, lo_y, hi_y, w, h, &mut grid);
    let gmax = grid.iter().copied().fold(0.0f32, f32::max);
    if gmax <= 0.0 {
        return;
    }
    let denom = gmax.ln_1p();
    let sx = w as f64 / (hi_x - lo_x);
    let sy = h as f64 / (hi_y - lo_y);
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        if !xv.is_finite() || !yv.is_finite() || xv < lo_x || xv >= hi_x || yv < lo_y || yv >= hi_y
        {
            continue;
        }
        let cx = (((xv - lo_x) * sx) as isize).clamp(0, w as isize - 1) as usize;
        let cy = (((yv - lo_y) * sy) as isize).clamp(0, h as isize - 1) as usize;
        let c = grid[cy * w + cx];
        out[i] = if c > 0.0 { c.ln_1p() / denom } else { 0.0 };
    }
}

fn x1_gt_x0(x0: f64, x1: f64) -> bool {
    #[allow(clippy::neg_cmp_op_on_partial_ord)]
    {
        x0.is_finite() && x1.is_finite() && x1 > x0
    }
}

/// Max value over an f32 grid — the per-view normalization domain for
/// colormapping (§5 F6: recomputed per view so zoom doesn't flicker brightness).
pub fn grid_max(grid: &[f32]) -> f32 {
    grid.iter().copied().fold(0.0f32, f32::max)
}

/// Min/max over a slice, NaN-skipping — the autorange primitive when zone maps
/// aren't available (they make this O(chunks), §22).
pub fn min_max(data: &[f64]) -> Option<(f64, f64)> {
    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for &v in data {
        if v.is_finite() {
            min = min.min(v);
            max = max.max(v);
        }
    }
    if min <= max {
        Some((min, max))
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zone_maps_basic() {
        let data: Vec<f64> = (0..10).map(|i| i as f64).collect();
        let zms = zone_maps(&data, 4);
        assert_eq!(zms.len(), 3);
        assert_eq!(zms[0].min, 0.0);
        assert_eq!(zms[0].max, 3.0);
        assert_eq!(zms[0].count, 4);
        assert_eq!(zms[0].sum, 6.0);
        assert_eq!(zms[2].min, 8.0);
        assert_eq!(zms[2].max, 9.0);
        assert_eq!(zms[2].count, 2);
    }

    #[test]
    fn zone_maps_nan_is_null() {
        let data = [1.0, f64::NAN, 3.0];
        let zms = zone_maps(&data, 65_536);
        assert_eq!(zms[0].count, 2);
        assert_eq!(zms[0].null_count, 1);
        assert_eq!(zms[0].min, 1.0);
        assert_eq!(zms[0].max, 3.0);
    }

    #[test]
    fn zone_maps_inf_is_null() {
        // ±∞ must count as null and never contaminate min/max/sum — else
        // autorange collapses (§19 hardening).
        let data = [1.0, f64::INFINITY, f64::NEG_INFINITY, 3.0];
        let zms = zone_maps(&data, 65_536);
        assert_eq!(zms[0].count, 2);
        assert_eq!(zms[0].null_count, 2);
        assert_eq!(zms[0].min, 1.0);
        assert_eq!(zms[0].max, 3.0);
        assert_eq!(zms[0].sum, 4.0);
        assert!(zms[0].sum_sq.is_finite());
    }

    #[test]
    fn encode_precision_ms_timestamps() {
        // The §25 thesis test: a 1-second span inside a 10-year ms-timestamp
        // series must survive the f32 path when re-centered on the window.
        let t0: f64 = 1.7e12; // ~2023 in ms epoch
        let window: Vec<f64> = (0..1000).map(|i| t0 + i as f64).collect(); // 1ms steps
        let offset = t0 + 500.0; // viewport-center offset (§16 re-centering)
        let mut enc = Vec::new();
        encode_f32(&window, offset, 1.0, &mut enc);
        for (i, &e) in enc.iter().enumerate() {
            let decoded = e as f64 + offset;
            let err = (decoded - window[i]).abs();
            // Relative span is 1000ms; f32 resolves ~6e-5 ms at that magnitude.
            assert!(err < 1e-3, "err {err} at {i}");
        }
    }

    #[test]
    fn encode_naive_f32_would_corrupt() {
        // Control: the same data as raw f32 (offset 0) loses ms resolution
        // entirely — this is the §15 finding #2 the offset path exists to fix.
        let t0: f64 = 1.7e12;
        let window: Vec<f64> = (0..1000).map(|i| t0 + i as f64).collect();
        let mut enc = Vec::new();
        encode_f32(&window, 0.0, 1.0, &mut enc);
        let worst = enc
            .iter()
            .zip(&window)
            .map(|(&e, &v)| (e as f64 - v).abs())
            .fold(0.0f64, f64::max);
        assert!(
            worst > 1.0,
            "naive f32 should be visibly wrong, got {worst}"
        );
    }

    #[test]
    fn m4_keeps_extremes() {
        // A spike in the middle of a bucket must survive decimation.
        let n = 10_000;
        let x: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let mut y: Vec<f64> = x.iter().map(|v| (v * 0.01).sin()).collect();
        y[5_432] = 100.0; // spike
        y[7_891] = -100.0; // negative spike
        let idx = m4_indices(&x, &y, 0.0, n as f64, 100);
        assert!(idx.len() <= 400);
        assert!(idx.contains(&5_432));
        assert!(idx.contains(&7_891));
        // First and last points of the window are preserved (M4, not min/max-only).
        assert_eq!(idx[0], 0);
        assert_eq!(*idx.last().unwrap(), (n - 1) as u32);
        // Sorted and unique.
        assert!(idx.windows(2).all(|w| w[0] < w[1]));
    }

    #[test]
    fn m4_visible_window_only() {
        let n = 1_000;
        let x: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let y = x.clone();
        let idx = m4_indices(&x, &y, 250.0, 500.0, 10);
        assert!(!idx.is_empty());
        assert!(idx.iter().all(|&i| (250..500).contains(&(i as usize))));
    }

    #[test]
    fn m4_skips_non_finite() {
        let x = [0.0, 1.0, 2.0, 3.0, 4.0];
        let y = [1.0, f64::NAN, 5.0, f64::INFINITY, 2.0];
        let idx = m4_indices(&x, &y, 0.0, 5.0, 1);
        assert!(!idx.contains(&1)); // NaN y
        assert!(!idx.contains(&3)); // inf y
        assert!(idx.contains(&2));
    }

    #[test]
    fn min_max_skips_non_finite() {
        assert_eq!(min_max(&[f64::NAN, 2.0, -1.0]), Some((-1.0, 2.0)));
        assert_eq!(
            min_max(&[f64::INFINITY, 2.0, f64::NEG_INFINITY, -1.0]),
            Some((-1.0, 2.0))
        );
        assert_eq!(min_max(&[f64::NAN, f64::INFINITY]), None);
        assert_eq!(min_max(&[]), None);
    }

    #[test]
    fn bin_2d_counts_and_conserves() {
        // 4 points, one per quadrant of a 2×2 grid over the unit square.
        let x = [0.25, 0.75, 0.25, 0.75];
        let y = [0.25, 0.25, 0.75, 0.75];
        let mut out = vec![0.0f32; 4];
        bin_2d(&x, &y, 0.0, 1.0, 0.0, 1.0, 2, 2, &mut out);
        assert_eq!(out, vec![1.0, 1.0, 1.0, 1.0]);
        // Total count conserved.
        assert_eq!(out.iter().sum::<f32>(), 4.0);
    }

    #[test]
    fn bin_2d_row0_is_bottom() {
        // A point low in y must land in row 0 (GL texture convention).
        let x = [0.5];
        let y = [0.1];
        let mut out = vec![0.0f32; 4]; // 2 wide, 2 tall
        bin_2d(&x, &y, 0.0, 1.0, 0.0, 1.0, 2, 2, &mut out);
        assert_eq!(out[0] + out[1], 1.0); // bottom row
        assert_eq!(out[2] + out[3], 0.0); // top row empty
    }

    #[test]
    fn bin_2d_skips_nan_and_outside() {
        let x = [0.5, f64::NAN, 5.0, -1.0, f64::INFINITY];
        let y = [0.5, 0.5, 0.5, 0.5, 0.5];
        let mut out = vec![0.0f32; 1];
        bin_2d(&x, &y, 0.0, 1.0, 0.0, 1.0, 1, 1, &mut out);
        assert_eq!(out[0], 1.0); // only the in-range, finite point
    }

    #[test]
    fn bin_2d_edge_rounding() {
        // A point exactly on the top/right edge must not write out of bounds.
        let x = [1.0 - f64::EPSILON, 0.999999];
        let y = [0.999999, 1.0 - f64::EPSILON];
        let mut out = vec![0.0f32; 16]; // 4×4
        bin_2d(&x, &y, 0.0, 1.0, 0.0, 1.0, 4, 4, &mut out);
        assert_eq!(out.iter().sum::<f32>(), 2.0);
    }

    #[test]
    fn bin_2d_density_hotspot() {
        // A cluster in one cell should dominate grid_max.
        let mut x = vec![0.1; 1000];
        let mut y = vec![0.1; 1000];
        x.extend((0..10).map(|i| 0.5 + i as f64 * 0.001));
        y.extend((0..10).map(|_| 0.9));
        let mut out = vec![0.0f32; 100]; // 10×10
        bin_2d(&x, &y, 0.0, 1.0, 0.0, 1.0, 10, 10, &mut out);
        assert_eq!(grid_max(&out), 1000.0);
        assert_eq!(out.iter().sum::<f32>(), 1010.0);
    }

    #[test]
    fn local_density_does_not_clamp_outside_points() {
        let x = [0.1, 0.1, 2.0, 0.5];
        let y = [0.1, 0.1, 0.1, f64::NAN];
        let mut out = [0.0f32; 4];
        local_log_density(&x, &y, 0.0, 1.0, 0.0, 1.0, 2, 2, &mut out);
        assert!(out[0] > 0.0);
        assert!(out[1] > 0.0);
        assert_eq!(out[2], 0.0);
        assert_eq!(out[3], 0.0);
    }
}

#[cfg(test)]
mod fuzz {
    //! Deterministic fuzz: hostile inputs (NaN, ±inf, huge/tiny magnitudes,
    //! empty/short arrays) against kernel invariants. Zero-crate by design —
    //! a seeded xorshift64* PRNG makes every failure reproducible from its
    //! iteration number. These are the properties humans forget to hand-test.
    use super::*;

    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            // xorshift64* — deterministic, no crates.
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
        /// Hostile scalar: mostly in-range, salted with NaN/±inf/huge/tiny/-0.
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

    fn naive_in_window(x: &[f64], y: &[f64], x0: f64, x1: f64, y0: f64, y1: f64) -> usize {
        x.iter()
            .zip(y)
            .filter(|(&a, &b)| {
                a.is_finite() && b.is_finite() && a >= x0 && a < x1 && b >= y0 && b < y1
            })
            .count()
    }

    #[test]
    fn fuzz_zone_maps_accounting() {
        let mut rng = Rng(0x5EED_0001);
        for it in 0..200 {
            let n = (rng.next() % 300) as usize;
            let data = rng.hostile_vec(n, -50.0, 50.0);
            let maps = zone_maps(&data, 64);
            // Contract (pinned by zone_maps_inf_is_null): `count` is FINITE
            // rows only; non-finite rows land in `null_count`; they partition n.
            let finite: u64 = maps.iter().map(|m| m.count).sum();
            let nulls: u64 = maps.iter().map(|m| m.null_count).sum();
            let naive_nulls = data.iter().filter(|v| !v.is_finite()).count() as u64;
            assert_eq!(finite + nulls, n as u64, "partition it={it}");
            assert_eq!(nulls, naive_nulls, "it={it}");
            // per-chunk min/max are finite whenever the chunk has a finite value
            for m in &maps {
                if m.count > 0 {
                    assert!(m.min.is_finite() && m.max.is_finite() && m.min <= m.max, "it={it}");
                }
            }
        }
    }

    #[test]
    fn fuzz_min_max_matches_naive() {
        let mut rng = Rng(0x5EED_0002);
        for it in 0..200 {
            let n = (rng.next() % 200) as usize;
            let data = rng.hostile_vec(n, -1e6, 1e6);
            let got = min_max(&data);
            let finite: Vec<f64> = data.iter().copied().filter(|v| v.is_finite()).collect();
            match got {
                None => assert!(finite.is_empty(), "it={it}"),
                Some((lo, hi)) => {
                    let nlo = finite.iter().copied().fold(f64::INFINITY, f64::min);
                    let nhi = finite.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                    assert_eq!((lo, hi), (nlo, nhi), "it={it}");
                }
            }
        }
    }

    #[test]
    fn fuzz_encode_f32_shape_and_determinism() {
        let mut rng = Rng(0x5EED_0003);
        for it in 0..200 {
            let n = (rng.next() % 200) as usize;
            let data = rng.hostile_vec(n, -1e4, 1e4);
            let offset = rng.hostile(-1e4, 1e4);
            let mut a = Vec::new();
            let mut b = Vec::new();
            encode_f32(&data, offset, 1.0, &mut a);
            encode_f32(&data, offset, 1.0, &mut b);
            assert_eq!(a.len(), n, "it={it}");
            // NaN != NaN, so determinism is a BITWISE property.
            let bits = |v: &Vec<f32>| v.iter().map(|f| f.to_bits()).collect::<Vec<u32>>();
            assert_eq!(bits(&a), bits(&b), "determinism it={it}");
            if offset.is_finite() {
                for (i, (&v, &e)) in data.iter().zip(&a).enumerate() {
                    // moderate finite inputs stay finite through the encoding
                    if v.is_finite() && v.abs() < 1e30 && offset.abs() < 1e30 {
                        assert!(e.is_finite(), "it={it} i={i} v={v} off={offset}");
                    }
                }
            }
        }
    }

    #[test]
    fn fuzz_m4_indices_window_and_bounds() {
        let mut rng = Rng(0x5EED_0004);
        for it in 0..200 {
            let n = (rng.next() % 300) as usize;
            // x must be ascending (ingest contract); y is hostile.
            let mut x: Vec<f64> = (0..n).map(|i| i as f64).collect();
            // salt some non-finite y and occasional NaN x tail (argsort-last shape)
            let y = rng.hostile_vec(n, -100.0, 100.0);
            if n > 4 && rng.next() % 4 == 0 {
                let k = n - 1;
                x[k] = f64::NAN;
            }
            let buckets = 1 + (rng.next() % 64) as usize;
            let x0 = rng.f01() * (n as f64);
            let x1 = x0 + 1.0 + rng.f01() * (n as f64);
            let idx = m4_indices(&x, &y, x0, x1, buckets);
            let idx2 = m4_indices(&x, &y, x0, x1, buckets);
            assert_eq!(idx, idx2, "determinism it={it}");
            assert!(idx.len() <= 4 * buckets, "it={it}");
            let mut prev: i64 = -1;
            for &i in &idx {
                assert!((i as usize) < n, "it={it}");
                assert!(i as i64 > prev, "sorted+dedup it={it}");
                prev = i as i64;
                let xv = x[i as usize];
                assert!(xv.is_finite() && xv >= x0 && xv < x1, "window it={it}");
                assert!(y[i as usize].is_finite(), "§19 it={it}");
            }
        }
    }

    #[test]
    fn fuzz_bin_2d_count_conservation() {
        let mut rng = Rng(0x5EED_0005);
        for it in 0..200 {
            let n = (rng.next() % 300) as usize;
            let x = rng.hostile_vec(n, -10.0, 10.0);
            let y = rng.hostile_vec(n, -10.0, 10.0);
            let (w, h) = (1 + (rng.next() % 16) as usize, 1 + (rng.next() % 12) as usize);
            let (x0, x1, y0, y1) = (-5.0, 7.0, -6.0, 4.0);
            let mut grid = vec![0f32; w * h];
            bin_2d(&x, &y, x0, x1, y0, y1, w, h, &mut grid);
            let total: f64 = grid.iter().map(|&c| c as f64).sum();
            let naive = naive_in_window(&x, &y, x0, x1, y0, y1) as f64;
            assert_eq!(total, naive, "conservation it={it}");
            assert!(grid.iter().all(|&c| c >= 0.0), "it={it}");
        }
    }

    #[test]
    fn fuzz_histogram_uniform_conservation() {
        let mut rng = Rng(0x5EED_0006);
        for it in 0..200 {
            let n = (rng.next() % 400) as usize;
            let data = rng.hostile_vec(n, -20.0, 20.0);
            let bins = 1 + (rng.next() % 64) as usize;
            let (lo, hi) = (-10.0, 15.0);
            let mut out = vec![0f64; bins];
            let counted = histogram_uniform(&data, lo, hi, &mut out);
            let naive = data
                .iter()
                .filter(|v| v.is_finite() && **v >= lo && **v <= hi)
                .count() as u64;
            assert_eq!(counted, naive, "it={it}");
            let total: f64 = out.iter().sum();
            assert_eq!(total, naive as f64, "sum it={it}");
            assert!(out.iter().all(|&c| c >= 0.0), "it={it}");
        }
    }

    #[test]
    fn fuzz_range_indices_sorted_exact() {
        let mut rng = Rng(0x5EED_0007);
        for it in 0..200 {
            let n = (rng.next() % 300) as usize;
            let x = rng.hostile_vec(n, -10.0, 10.0);
            let y = rng.hostile_vec(n, -10.0, 10.0);
            let (lo_x, hi_x, lo_y, hi_y) = (-4.0, 8.0, -9.0, 3.0);
            let mut out = vec![0u32; n];
            let m = range_indices(&x, &y, lo_x, hi_x, lo_y, hi_y, &mut out);
            let naive: Vec<u32> = (0..n)
                .filter(|&i| x[i] >= lo_x && x[i] <= hi_x && y[i] >= lo_y && y[i] <= hi_y)
                .map(|i| i as u32)
                .collect();
            assert_eq!(&out[..m], naive.as_slice(), "it={it}");
            // NaN/±inf can never satisfy the closed-range comparisons
            for &i in &out[..m] {
                assert!(x[i as usize].is_finite() && y[i as usize].is_finite(), "it={it}");
            }
        }
    }

    #[test]
    fn fuzz_normalize_f32_unit_range() {
        let mut rng = Rng(0x5EED_0008);
        for it in 0..200 {
            let n = (rng.next() % 200) as usize;
            let data = rng.hostile_vec(n, -1e3, 1e3);
            let mut out = vec![0f32; n];
            normalize_f32_into(&data, -500.0, 500.0, 0.0, &mut out);
            for (i, (&v, &o)) in data.iter().zip(&out).enumerate() {
                if v.is_finite() {
                    assert!((0.0..=1.0).contains(&o), "unit it={it} i={i} o={o}");
                } else {
                    assert_eq!(o, 0.0, "nan_value it={it} i={i}");
                }
            }
        }
    }

    #[test]
    fn fuzz_local_log_density_unit_range() {
        let mut rng = Rng(0x5EED_0009);
        for it in 0..100 {
            let n = (rng.next() % 200) as usize;
            let x = rng.hostile_vec(n, 0.0, 10.0);
            let y = rng.hostile_vec(n, 0.0, 10.0);
            let mut out = vec![0f32; n];
            local_log_density(&x, &y, 0.0, 10.0, 0.0, 10.0, 8, 8, &mut out);
            for (i, &d) in out.iter().enumerate() {
                assert!((0.0..=1.0).contains(&d), "it={it} i={i} d={d}");
            }
        }
    }
}
