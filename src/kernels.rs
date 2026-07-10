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
    pub positive_min: f64,
    pub positive_max: f64,
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
            positive_min: f64::INFINITY,
            positive_max: f64::NEG_INFINITY,
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
    zone_maps_impl(data, chunk_size, par_threads(data.len()))
}

fn zone_map_one(chunk: &[f64]) -> ZoneMap {
    let mut zm = ZoneMap::empty();
    for &v in chunk {
        if !v.is_finite() {
            zm.null_count += 1;
        } else {
            zm.count += 1;
            zm.min = zm.min.min(v);
            zm.max = zm.max.max(v);
            if v > 0.0 {
                zm.positive_min = zm.positive_min.min(v);
                zm.positive_max = zm.positive_max.max(v);
            }
            zm.sum += v;
            zm.sum_sq += v * v;
        }
    }
    zm
}

/// Chunks are independent, so ingest fans out across cores by splitting at
/// chunk boundaries — every chunk is still folded sequentially by one thread,
/// so results are bitwise identical to the serial pass for any thread count.
fn zone_maps_impl(data: &[f64], chunk_size: usize, threads: usize) -> Vec<ZoneMap> {
    let n_chunks = data.len().div_ceil(chunk_size);
    if threads <= 1 || n_chunks < 2 {
        return data.chunks(chunk_size).map(zone_map_one).collect();
    }
    let per = n_chunks.div_ceil(threads);
    std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let lo = (t * per * chunk_size).min(data.len());
                let hi = ((t + 1) * per * chunk_size).min(data.len());
                let seg = &data[lo..hi];
                s.spawn(move || seg.chunks(chunk_size).map(zone_map_one).collect::<Vec<_>>())
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|hd| hd.join().expect("zone_maps worker panicked"))
            .collect()
    })
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
/// Element-wise, so the parallel fan-out writes disjoint segments and is
/// bitwise identical to the serial loop.
pub fn encode_f32_into(data: &[f64], offset: f64, scale: f64, out: &mut [f32]) {
    assert_eq!(data.len(), out.len());
    let threads = par_threads(data.len());
    if threads <= 1 {
        for (o, &v) in out.iter_mut().zip(data) {
            *o = ((v - offset) * scale) as f32;
        }
        return;
    }
    let chunk = data.len().div_ceil(threads);
    std::thread::scope(|s| {
        for (dseg, oseg) in data.chunks(chunk).zip(out.chunks_mut(chunk)) {
            s.spawn(move || {
                for (o, &v) in oseg.iter_mut().zip(dseg) {
                    *o = ((v - offset) * scale) as f32;
                }
            });
        }
    });
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

    m4_indices_impl(x, y, x0, x1, n_buckets, start, end, par_threads(end - start))
}

/// Emit one bucket's {first, min, max, last} rows, sorted and deduplicated.
/// Shared by the scalar and SIMD (simd.rs) M4 state machines so a bucket
/// flush is identical by construction.
pub(crate) fn m4_flush(first: u32, min_i: u32, max_i: u32, last: u32, out: &mut Vec<u32>) {
    let mut ids = [first, min_i, max_i, last];
    ids.sort_unstable();
    let mut prev = u32::MAX;
    for id in ids {
        if id != prev {
            out.push(id);
            prev = id;
        }
    }
}

/// Serial M4 over rows `[lo, hi)` — the shared building block: the serial path
/// runs it once over the whole window; the parallel path runs it per bucket-
/// aligned segment and concatenates. Stays scalar deliberately: a two-phase
/// SIMD restructure (precomputed bucket ids) measured *slower* (472 vs
/// 915 Mpt/s at 1M) — the sequential bucket state machine dominates, and the
/// extra block store/load pass outweighs vectorizing the cheap float math.
fn m4_range(x: &[f64], y: &[f64], x0: f64, inv_bucket_w: f64, n_buckets: usize, lo: usize, hi: usize) -> Vec<u32> {
    let mut out: Vec<u32> = Vec::with_capacity((n_buckets * 4).min((hi - lo) * 4));

    // Per-bucket running state.
    let mut cur_bucket = usize::MAX;
    let mut first = 0u32;
    let mut last = 0u32;
    let mut min_i = 0u32;
    let mut max_i = 0u32;
    let mut min_v = f64::INFINITY;
    let mut max_v = f64::NEG_INFINITY;
    let mut has_any = false;

    for i in lo..hi {
        let yv = y[i];
        if !yv.is_finite() {
            continue; // NaN and ±∞ are non-plottable (§19)
        }
        let b = (((x[i] - x0) * inv_bucket_w) as usize).min(n_buckets - 1);
        if b != cur_bucket {
            if has_any {
                m4_flush(first, min_i, max_i, last, &mut out);
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
        m4_flush(first, min_i, max_i, last, &mut out);
    }
    out
}

/// Buckets are monotone non-decreasing in sorted x, so every bucket's rows are
/// contiguous. Split the window at bucket boundaries (nudging each split
/// forward until it starts a new bucket), scan each segment with the same
/// serial routine, and concatenate in order — bitwise identical to the serial
/// pass for any thread count. Degenerate case: one giant bucket collapses to
/// a single segment (serial speed, still correct).
#[allow(clippy::too_many_arguments)]
fn m4_indices_impl(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    n_buckets: usize,
    start: usize,
    end: usize,
    threads: usize,
) -> Vec<u32> {
    let inv_bucket_w = n_buckets as f64 / (x1 - x0);
    if threads <= 1 {
        return m4_range(x, y, x0, inv_bucket_w, n_buckets, start, end);
    }
    let bucket_of = |i: usize| (((x[i] - x0) * inv_bucket_w) as usize).min(n_buckets - 1);
    let span = end - start;
    let chunk = span.div_ceil(threads);
    let mut bounds: Vec<usize> = vec![start];
    for t in 1..threads {
        let mut j = (start + t * chunk).min(end);
        while j < end && j > 0 && bucket_of(j) == bucket_of(j - 1) {
            j += 1;
        }
        let prev = *bounds.last().expect("bounds never empty");
        if j > prev && j < end {
            bounds.push(j);
        }
    }
    bounds.push(end);
    let parts: Vec<Vec<u32>> = std::thread::scope(|s| {
        let handles: Vec<_> = bounds
            .windows(2)
            .map(|wnd| {
                let (lo, hi) = (wnd[0], wnd[1]);
                s.spawn(move || m4_range(x, y, x0, inv_bucket_w, n_buckets, lo, hi))
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("m4 worker panicked"))
            .collect()
    });
    let mut out = Vec::with_capacity(parts.iter().map(Vec::len).sum());
    for p in parts {
        out.extend(p);
    }
    out
}

fn contour_pairs(mask: u8) -> &'static [(u8, u8)] {
    match mask {
        1 => &[(3, 0)],
        2 => &[(0, 1)],
        3 => &[(3, 1)],
        4 => &[(1, 2)],
        5 => &[(3, 0), (1, 2)],
        6 => &[(0, 2)],
        7 => &[(3, 2)],
        8 => &[(2, 3)],
        9 => &[(0, 2)],
        10 => &[(0, 1), (2, 3)],
        11 => &[(1, 2)],
        12 => &[(1, 3)],
        13 => &[(0, 1)],
        14 => &[(3, 0)],
        _ => &[],
    }
}

/// Scan a regular grid with marching squares and emit flat isoline segments.
///
/// The cell/level traversal and ambiguous-cell table intentionally mirror the
/// Python reference that originally lived in `marks.py`. Keeping the output as
/// independent segments avoids a topology/joining pass and lets the WebGL,
/// SVG, and native raster paths share the existing segment primitive.
#[allow(clippy::too_many_arguments)]
fn marching_squares_scan<F>(
    z: &[f64],
    rows: usize,
    cols: usize,
    x_coords: &[f64],
    y_coords: &[f64],
    levels: &[f64],
    mut emit: F,
) -> usize
where
    F: FnMut(f64, f64, f64, f64, f64),
{
    assert_eq!(z.len(), rows * cols);
    assert_eq!(x_coords.len(), cols);
    assert_eq!(y_coords.len(), rows);
    let mut count = 0usize;
    for &level in levels {
        for row in 0..rows - 1 {
            for col in 0..cols - 1 {
                let v00 = z[row * cols + col];
                let v10 = z[row * cols + col + 1];
                let v11 = z[(row + 1) * cols + col + 1];
                let v01 = z[(row + 1) * cols + col];
                if !(v00.is_finite() && v10.is_finite() && v11.is_finite() && v01.is_finite()) {
                    continue;
                }
                let mask = u8::from(v00 >= level)
                    | (u8::from(v10 >= level) << 1)
                    | (u8::from(v11 >= level) << 2)
                    | (u8::from(v01 >= level) << 3);
                let pairs = contour_pairs(mask);
                if pairs.is_empty() {
                    continue;
                }
                let corners = [
                    (x_coords[col], y_coords[row], v00),
                    (x_coords[col + 1], y_coords[row], v10),
                    (x_coords[col + 1], y_coords[row + 1], v11),
                    (x_coords[col], y_coords[row + 1], v01),
                ];
                let mut points = [(0.0f64, 0.0f64); 4];
                for edge in 0..4 {
                    let (xa, ya, va) = corners[edge];
                    let (xb, yb, vb) = corners[(edge + 1) % 4];
                    let denom = vb - va;
                    let fraction = if denom == 0.0 {
                        0.5
                    } else {
                        ((level - va) / denom).clamp(0.0, 1.0)
                    };
                    points[edge] = (
                        xa + (xb - xa) * fraction,
                        ya + (yb - ya) * fraction,
                    );
                }
                for &(edge_a, edge_b) in pairs {
                    let (x0, y0) = points[edge_a as usize];
                    let (x1, y1) = points[edge_b as usize];
                    emit(x0, x1, y0, y1, level);
                    count += 1;
                }
            }
        }
    }
    count
}

/// Write marching-squares segments into caller-owned parallel output arrays.
///
/// Returns the required segment count even when the output capacity is too
/// small; in that case only the prefix that fits is written. The C ABI uses
/// this to perform a bounded count query followed by one exact allocation.
#[allow(clippy::too_many_arguments)]
pub fn marching_squares_into(
    z: &[f64],
    rows: usize,
    cols: usize,
    x_coords: &[f64],
    y_coords: &[f64],
    levels: &[f64],
    x0_out: &mut [f64],
    x1_out: &mut [f64],
    y0_out: &mut [f64],
    y1_out: &mut [f64],
    level_out: &mut [f64],
) -> usize {
    let capacity = x0_out.len();
    assert_eq!(x1_out.len(), capacity);
    assert_eq!(y0_out.len(), capacity);
    assert_eq!(y1_out.len(), capacity);
    assert_eq!(level_out.len(), capacity);
    let mut written = 0usize;
    marching_squares_scan(z, rows, cols, x_coords, y_coords, levels, |x0, x1, y0, y1, level| {
        if written < capacity {
            x0_out[written] = x0;
            x1_out[written] = x1;
            y0_out[written] = y0;
            y1_out[written] = y1;
            level_out[written] = level;
        }
        written += 1;
    });
    written
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
    bin_2d_impl(x, y, x0, x1, y0, y1, w, h, par_threads(x.len()), out);
}

/// Row-scan kernels fan out across cores only past this size, where thread
/// spawn + merge cost is well amortized. Threading stays inside the call —
/// the ABI remains synchronous (engine doc E5).
const PAR_THRESHOLD: usize = 1 << 19;

fn par_threads(n: usize) -> usize {
    if n >= PAR_THRESHOLD {
        std::thread::available_parallelism().map_or(1, |p| p.get().min(8))
    } else {
        1
    }
}

/// Count in-window points per cell into a u32 grid (saturating). Shared by the
/// serial and parallel paths so per-point behavior is identical by construction.
/// Dispatches to the AVX2 clone when available (simd.rs).
#[allow(clippy::too_many_arguments)]
fn bin_2d_count(
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
    if crate::simd::try_bin_2d_count(x, y, x0, x1, y0, y1, w, h, grid) {
        return;
    }
    bin_2d_count_scalar(x, y, x0, x1, y0, y1, w, h, grid);
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn bin_2d_count_scalar(
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
        grid[cy * w + cx] = grid[cy * w + cx].saturating_add(1);
    }
}

/// Integer-count variant used by the tile pyramid. Keeping the first grid in
/// its native representation avoids allocating a large f32 grid only to
/// convert every cell back to u32 before building pyramid levels.
#[allow(clippy::too_many_arguments)]
pub(crate) fn bin_2d_counts(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
) -> Vec<u32> {
    let n = x.len();
    let threads = par_threads(n);
    if threads <= 1 || n < threads {
        let mut grid = vec![0u32; w * h];
        bin_2d_count(x, y, x0, x1, y0, y1, w, h, &mut grid);
        return grid;
    }

    let chunk = n.div_ceil(threads);
    let grids: Vec<Vec<u32>> = std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let lo = (t * chunk).min(n);
                let hi = ((t + 1) * chunk).min(n);
                let (xs, ys) = (&x[lo..hi], &y[lo..hi]);
                s.spawn(move || {
                    let mut grid = vec![0u32; w * h];
                    bin_2d_count(xs, ys, x0, x1, y0, y1, w, h, &mut grid);
                    grid
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("bin_2d worker panicked"))
            .collect()
    });

    let mut grid = vec![0u32; w * h];
    let cell_chunk = (w * h).div_ceil(threads);
    let grids_ref = &grids;
    std::thread::scope(|s| {
        for (ci, out) in grid.chunks_mut(cell_chunk).enumerate() {
            let base = ci * cell_chunk;
            s.spawn(move || {
                for (j, cell) in out.iter_mut().enumerate() {
                    *cell = grids_ref
                        .iter()
                        .map(|g| g[base + j] as u64)
                        .sum::<u64>()
                        .min(u32::MAX as u64) as u32;
                }
            });
        }
    });
    grid
}

/// Exact integer counts, converted to f32 once at the end. This is bitwise
/// deterministic for ANY thread count (integer sums are associative), and
/// strictly better than the old serial `f32 += 1.0`, which silently stalled
/// at 2^24 points per cell; exact f64 accumulation avoids that ceiling.
#[allow(clippy::too_many_arguments)]
fn bin_2d_impl(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    threads: usize,
    out: &mut [f32],
) {
    let n = x.len();
    if threads <= 1 || n < threads {
        let mut grid = vec![0u32; w * h];
        bin_2d_count(x, y, x0, x1, y0, y1, w, h, &mut grid);
        for (o, c) in out.iter_mut().zip(grid) {
            *o = c as f32;
        }
        return;
    }
    let chunk = n.div_ceil(threads);
    let grids: Vec<Vec<u32>> = std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let lo = (t * chunk).min(n);
                let hi = ((t + 1) * chunk).min(n);
                let (xs, ys) = (&x[lo..hi], &y[lo..hi]);
                s.spawn(move || {
                    let mut grid = vec![0u32; w * h];
                    bin_2d_count(xs, ys, x0, x1, y0, y1, w, h, &mut grid);
                    grid
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("bin_2d worker panicked"))
            .collect()
    });
    // Merge in parallel too: at screen-sized grids the w*h reduction is a
    // real fraction of the total. Disjoint output slices, integer sums —
    // still bitwise deterministic for any thread count.
    let cell_chunk = (w * h).div_ceil(threads);
    let grids_ref = &grids;
    std::thread::scope(|s| {
        for (ci, oseg) in out.chunks_mut(cell_chunk).enumerate() {
            let base = ci * cell_chunk;
            s.spawn(move || {
                for (j, o) in oseg.iter_mut().enumerate() {
                    let c: u64 = grids_ref.iter().map(|g| u64::from(g[base + j])).sum();
                    *o = c as f32;
                }
            });
        }
    });
}

/// Fused density scan (§5 Tier 2): one pass over `x`/`y` producing BOTH the
/// screen-bounded count grid and the ascending in-window row indices, instead
/// of `bin_2d` + `range_indices` each re-reading the full columns. The two
/// outputs keep their historical predicates — they are deliberately different:
/// indices use the inclusive window (`>= lo && <= hi`, `range_indices`
/// semantics) while grid cells use the half-open finite window (`>= lo && <
/// hi`, `bin_2d` semantics) — so each output is bitwise identical to its
/// standalone kernel. Returns the index count.
#[allow(clippy::too_many_arguments)]
pub fn bin_2d_indices(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    grid: &mut [f32],
    idx: &mut [u32],
) -> usize {
    assert_eq!(x.len(), y.len());
    assert_eq!(grid.len(), w * h);
    assert!(w > 0 && h > 0 && x1_gt_x0(lo_x, hi_x) && x1_gt_x0(lo_y, hi_y));
    assert!(idx.len() >= x.len());
    bin_2d_indices_impl(x, y, lo_x, hi_x, lo_y, hi_y, w, h, par_threads(x.len()), grid, idx)
}

/// Serial fused scan over one segment: local u32 grid counts + ascending
/// `base + i` indices. Shared by the serial and parallel paths so per-point
/// behavior is identical by construction.
#[allow(clippy::too_many_arguments)]
fn bin_2d_indices_scan(
    x: &[f64],
    y: &[f64],
    base: u32,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    grid: &mut [u32],
    idx: &mut [u32],
) -> usize {
    let sx = w as f64 / (hi_x - lo_x);
    let sy = h as f64 / (hi_y - lo_y);
    let mut n = 0;
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        // range_indices predicate: inclusive on every side (NaN fails all).
        if xv >= lo_x && xv <= hi_x && yv >= lo_y && yv <= hi_y {
            idx[n] = base + i as u32;
            n += 1;
        }
        // bin_2d predicate: half-open top/right, explicitly finite.
        if !xv.is_finite() || !yv.is_finite() || xv < lo_x || xv >= hi_x || yv < lo_y || yv >= hi_y
        {
            continue;
        }
        let cx = (((xv - lo_x) * sx) as usize).min(w - 1);
        let cy = (((yv - lo_y) * sy) as usize).min(h - 1);
        grid[cy * w + cx] = grid[cy * w + cx].saturating_add(1);
    }
    n
}

#[allow(clippy::too_many_arguments)]
fn bin_2d_indices_impl(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    w: usize,
    h: usize,
    threads: usize,
    out: &mut [f32],
    idx: &mut [u32],
) -> usize {
    let n = x.len();
    if threads <= 1 || n < threads {
        let mut grid = vec![0u32; w * h];
        let written = bin_2d_indices_scan(x, y, 0, lo_x, hi_x, lo_y, hi_y, w, h, &mut grid, idx);
        for (o, c) in out.iter_mut().zip(grid) {
            *o = c as f32;
        }
        return written;
    }
    let chunk = n.div_ceil(threads);
    // Workers fill disjoint idx segments aligned with their data chunk (a
    // chunk can never yield more matches than its length) and a local grid;
    // both merge steps below are order-preserving / integer sums, so the
    // result is bitwise identical to the serial scan for any thread count.
    let (grids, counts): (Vec<Vec<u32>>, Vec<usize>) = std::thread::scope(|s| {
        let handles: Vec<_> = x
            .chunks(chunk)
            .zip(y.chunks(chunk))
            .zip(idx[..n].chunks_mut(chunk))
            .enumerate()
            .map(|(t, ((xs, ys), iseg))| {
                let base = (t * chunk) as u32;
                s.spawn(move || {
                    let mut grid = vec![0u32; w * h];
                    let c = bin_2d_indices_scan(
                        xs, ys, base, lo_x, hi_x, lo_y, hi_y, w, h, &mut grid, iseg,
                    );
                    (grid, c)
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("bin_2d_indices worker panicked"))
            .unzip()
    });
    let mut write = counts[0];
    for (t, &c) in counts.iter().enumerate().skip(1) {
        let start = t * chunk;
        idx.copy_within(start..start + c, write);
        write += c;
    }
    let cell_chunk = (w * h).div_ceil(threads);
    let grids_ref = &grids;
    std::thread::scope(|s| {
        for (ci, oseg) in out.chunks_mut(cell_chunk).enumerate() {
            let base = ci * cell_chunk;
            s.spawn(move || {
                for (j, o) in oseg.iter_mut().enumerate() {
                    let c: u64 = grids_ref.iter().map(|g| u64::from(g[base + j])).sum();
                    *o = c as f32;
                }
            });
        }
    });
    write
}

const SPLITMIX_INCREMENT: u64 = 0x9E37_79B9_7F4A_7C15;
const SPLITMIX_MUL_1: u64 = 0xBF58_476D_1CE4_E5B9;
const SPLITMIX_MUL_2: u64 = 0x94D0_49BB_1331_11EB;

/// SplitMix64 of `(row_id + seed)` — the deterministic sampling hash (§5/§17).
/// Must stay bit-identical to `xy.lod.hash_row_ids` (wrapping u64
/// arithmetic on both sides); the Python parity test asserts this.
#[inline(always)]
fn splitmix64(id: u64, seed: u64) -> u64 {
    let mut z = id.wrapping_add(seed).wrapping_add(SPLITMIX_INCREMENT);
    z = (z ^ (z >> 30)).wrapping_mul(SPLITMIX_MUL_1);
    z = (z ^ (z >> 27)).wrapping_mul(SPLITMIX_MUL_2);
    z ^ (z >> 31)
}

/// Deterministic sampling mask: `out[i] = splitmix64(ids[i], seed) <= threshold`.
/// One fused pass — the NumPy expression allocates five full-width u64
/// temporaries (~80 MB each at 10M rows) and dominated the density payload
/// build; this reads ids once and writes the byte mask once.
pub fn sample_mask(ids: &[u64], seed: u64, threshold: u64, out: &mut [u8]) {
    assert_eq!(ids.len(), out.len());
    sample_mask_impl(ids, seed, threshold, par_threads(ids.len()), out)
}

fn sample_mask_impl(ids: &[u64], seed: u64, threshold: u64, threads: usize, out: &mut [u8]) {
    if threads <= 1 || ids.len() < 2 {
        for (o, &id) in out.iter_mut().zip(ids) {
            *o = u8::from(splitmix64(id, seed) <= threshold);
        }
        return;
    }
    let per = ids.len().div_ceil(threads);
    std::thread::scope(|s| {
        for (seg_ids, seg_out) in ids.chunks(per).zip(out.chunks_mut(per)) {
            s.spawn(move || {
                for (o, &id) in seg_out.iter_mut().zip(seg_ids) {
                    *o = u8::from(splitmix64(id, seed) <= threshold);
                }
            });
        }
    });
}

/// Sampling threshold for a keep fraction, matching the Python reference
/// `lod._sample_threshold` bit-for-bit: fractions >= 1 keep every row;
/// otherwise `fraction * (2^64 - 1)` in f64 (the constant rounds to 2^64),
/// truncated with the same saturating clamp as Python's
/// `max(0, min(u64_max, int(...)))`.
fn sample_threshold(fraction: f64) -> u64 {
    if fraction >= 1.0 {
        u64::MAX
    } else {
        // `as` saturates: NaN/negative -> 0, overflow -> u64::MAX.
        (fraction * u64::MAX as f64) as u64
    }
}

/// Category-stratified deterministic sampling mask (§5/§17). Per-category keep
/// fractions scale sublinearly (`min(1, fraction * sqrt(n / count))`) and every
/// category keeps at least `min(min_count, count)` of its lowest-hash rows, so
/// rare categories stay pinned into view. The mask is monotonic in `fraction`
/// because the floor rows (lowest hashes) are the first any threshold admits.
///
/// One fused pass replaces the per-category NumPy loop, whose repeated
/// `inverse == group` scans made it O(n·k). Ties on equal hashes break toward
/// the lower row index, so the floor stays deterministic with duplicate ids
/// (distinct ids can't tie — splitmix64 is a bijection).
///
/// `groups[i]` must be `< n_groups`; returns false (output undefined) on an
/// out-of-range code.
pub fn stratified_sample_mask(
    ids: &[u64],
    groups: &[u32],
    n_groups: usize,
    seed: u64,
    fraction: f64,
    min_count: u64,
    out: &mut [u8],
) -> bool {
    assert_eq!(ids.len(), groups.len());
    assert_eq!(ids.len(), out.len());
    if ids.is_empty() {
        return true;
    }
    let mut counts = vec![0u64; n_groups];
    for &g in groups {
        match counts.get_mut(g as usize) {
            Some(c) => *c += 1,
            None => return false,
        }
    }
    let n = ids.len() as f64;
    let thresholds: Vec<u64> = counts
        .iter()
        .map(|&c| sample_threshold(fraction * (n / c as f64).sqrt()))
        .collect();

    // Keep pass: parallel only when the per-thread kept-count vectors stay
    // small; a degenerate all-distinct grouping falls back to one thread.
    let threads = if n_groups <= 1024 { par_threads(ids.len()) } else { 1 };
    let per = ids.len().div_ceil(threads);
    let thresholds_ref = &thresholds;
    let kept: Vec<u64> = std::thread::scope(|s| {
        let handles: Vec<_> = ids
            .chunks(per)
            .zip(groups.chunks(per))
            .zip(out.chunks_mut(per))
            .map(|((seg_ids, seg_groups), seg_out)| {
                s.spawn(move || {
                    let mut kept = vec![0u64; n_groups];
                    for ((o, &id), &g) in seg_out.iter_mut().zip(seg_ids).zip(seg_groups) {
                        let keep = splitmix64(id, seed) <= thresholds_ref[g as usize];
                        *o = u8::from(keep);
                        kept[g as usize] += u64::from(keep);
                    }
                    kept
                })
            })
            .collect();
        let mut kept = vec![0u64; n_groups];
        for h in handles {
            for (t, p) in kept.iter_mut().zip(h.join().expect("keep-pass worker panicked")) {
                *t += p;
            }
        }
        kept
    });

    // Floor fill: gather (hash, row) only for deficient categories and admit
    // each one's `floor` lowest hashes on top of the threshold survivors.
    let deficient: Vec<bool> = counts
        .iter()
        .zip(&kept)
        .map(|(&c, &k)| k < min_count.min(c))
        .collect();
    if deficient.iter().any(|&d| d) {
        let mut pools: Vec<Vec<(u64, usize)>> = vec![Vec::new(); n_groups];
        for (i, (&id, &g)) in ids.iter().zip(groups).enumerate() {
            if deficient[g as usize] {
                pools[g as usize].push((splitmix64(id, seed), i));
            }
        }
        for (g, pool) in pools.iter_mut().enumerate() {
            if !deficient[g] {
                continue;
            }
            let floor = min_count.min(counts[g]) as usize;
            if floor < pool.len() {
                pool.select_nth_unstable(floor - 1);
                pool.truncate(floor);
            }
            for &(_, i) in pool.iter() {
                out[i] = 1;
            }
        }
    }
    true
}

/// Uniform-bin histogram over `[lo, hi]` with the last bin closed, matching
/// NumPy's fixed-bin behavior for the common chart path. Non-finite values and
/// values outside the range are skipped. `out` is fully overwritten.
pub fn histogram_uniform(data: &[f64], lo: f64, hi: f64, out: &mut [f64]) -> u64 {
    assert!(x1_gt_x0(lo, hi));
    assert!(!out.is_empty());
    histogram_uniform_impl(data, lo, hi, par_threads(data.len()), out)
}

/// Per-bin u64 counting shared by the serial and parallel paths. Stays scalar
/// deliberately: the blocked SIMD restructure measured ~8% slower — the
/// scatter increment dominates and can't vectorize (see simd.rs rules).
fn histogram_count(data: &[f64], lo: f64, hi: f64, bins: &mut [u64]) -> u64 {
    let n_bins = bins.len();
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
        bins[idx] += 1;
        total += 1;
    }
    total
}

/// Exact u64 counts merged then converted to f64 once — identical to the old
/// sequential `f64 += 1.0` (integers are exact in f64 far past any real N)
/// and bitwise deterministic for any thread count.
fn histogram_uniform_impl(
    data: &[f64],
    lo: f64,
    hi: f64,
    threads: usize,
    out: &mut [f64],
) -> u64 {
    let n = data.len();
    if threads <= 1 || n < threads {
        let mut bins = vec![0u64; out.len()];
        let total = histogram_count(data, lo, hi, &mut bins);
        for (o, c) in out.iter_mut().zip(bins) {
            *o = c as f64;
        }
        return total;
    }
    let chunk = n.div_ceil(threads);
    let parts: Vec<(Vec<u64>, u64)> = std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let seg = &data[(t * chunk).min(n)..((t + 1) * chunk).min(n)];
                let n_bins = out.len();
                s.spawn(move || {
                    let mut bins = vec![0u64; n_bins];
                    let total = histogram_count(seg, lo, hi, &mut bins);
                    (bins, total)
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("histogram worker panicked"))
            .collect()
    });
    let mut total = 0u64;
    for (i, o) in out.iter_mut().enumerate() {
        *o = parts.iter().map(|(b, _)| b[i]).sum::<u64>() as f64;
    }
    for (_, t) in &parts {
        total += t;
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
    let norm_one = move |dst: &mut f32, v: f64| {
        if v.is_finite() {
            *dst = (((v - lo) / span).clamp(0.0, 1.0)) as f32;
        } else {
            *dst = nan_value;
        }
    };
    let threads = par_threads(data.len());
    if threads <= 1 {
        for (dst, &v) in out.iter_mut().zip(data) {
            norm_one(dst, v);
        }
        return;
    }
    // Element-wise: disjoint output segments, bitwise identical to serial.
    let chunk = data.len().div_ceil(threads);
    std::thread::scope(|s| {
        for (dseg, oseg) in data.chunks(chunk).zip(out.chunks_mut(chunk)) {
            s.spawn(move || {
                for (dst, &v) in oseg.iter_mut().zip(dseg) {
                    norm_one(dst, v);
                }
            });
        }
    });
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
    range_indices_impl(x, y, lo_x, hi_x, lo_y, hi_y, par_threads(x.len()), out)
}

/// Append the global indices (`base + i`) of in-window rows to `out`,
/// returning the match count. NaN fails every comparison → skipped, matching
/// the historical behavior. Dispatches to the AVX2 clone when available.
#[allow(clippy::too_many_arguments)]
fn range_scan(
    x: &[f64],
    y: &[f64],
    base: u32,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out: &mut [u32],
) -> usize {
    if let Some(n) = crate::simd::try_range_scan(x, y, base, lo_x, hi_x, lo_y, hi_y, out) {
        return n;
    }
    range_scan_scalar(x, y, base, lo_x, hi_x, lo_y, hi_y, out)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn range_scan_scalar(
    x: &[f64],
    y: &[f64],
    base: u32,
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    out: &mut [u32],
) -> usize {
    let mut n = 0usize;
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        if xv >= lo_x && xv <= hi_x && yv >= lo_y && yv <= hi_y {
            out[n] = base + i as u32;
            n += 1;
        }
    }
    n
}

/// Parallel window scan: workers fill disjoint `out` segments aligned with
/// their data chunk (a chunk can never yield more matches than its length),
/// then segments compact left in chunk order — the result is the same
/// ascending index list the serial scan produces, bitwise.
#[allow(clippy::too_many_arguments)]
fn range_indices_impl(
    x: &[f64],
    y: &[f64],
    lo_x: f64,
    hi_x: f64,
    lo_y: f64,
    hi_y: f64,
    threads: usize,
    out: &mut [u32],
) -> usize {
    let n = x.len();
    if threads <= 1 || n < threads {
        return range_scan(x, y, 0, lo_x, hi_x, lo_y, hi_y, out);
    }
    let chunk = n.div_ceil(threads);
    let counts: Vec<usize> = std::thread::scope(|s| {
        let handles: Vec<_> = x
            .chunks(chunk)
            .zip(y.chunks(chunk))
            .zip(out[..n].chunks_mut(chunk))
            .enumerate()
            .map(|(t, ((xs, ys), oseg))| {
                let base = (t * chunk) as u32;
                s.spawn(move || range_scan(xs, ys, base, lo_x, hi_x, lo_y, hi_y, oseg))
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("range_indices worker panicked"))
            .collect()
    });
    let mut write = counts[0];
    for (t, &c) in counts.iter().enumerate().skip(1) {
        let start = t * chunk;
        out.copy_within(start..start + c, write);
        write += c;
    }
    write
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
    // Fold the log-normalization into the grid once per cell (w*h calls) rather
    // than once per point (n calls) — the per-point pass then only gathers a
    // precomputed value. Identical f32 arithmetic, so bitwise-equal output.
    for c in grid.iter_mut() {
        *c = if *c > 0.0 { c.ln_1p() / denom } else { 0.0 };
    }
    if crate::simd::try_density_gather(x, y, lo_x, hi_x, lo_y, hi_y, w, h, &grid, out) {
        return;
    }
    density_gather_scalar(x, y, lo_x, hi_x, lo_y, hi_y, w, h, &grid, out);
}

/// Per-point read-back of the normalized grid value (the drill-handoff color
/// seed). Out-of-window/non-finite points keep their pre-zeroed 0.0.
#[allow(clippy::too_many_arguments)]
pub(crate) fn density_gather_scalar(
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
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        if !xv.is_finite() || !yv.is_finite() || xv < lo_x || xv >= hi_x || yv < lo_y || yv >= hi_y
        {
            continue;
        }
        let cx = (((xv - lo_x) * sx) as isize).clamp(0, w as isize - 1) as usize;
        let cy = (((yv - lo_y) * sy) as isize).clamp(0, h as isize - 1) as usize;
        out[i] = grid[cy * w + cx];
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
    min_max_impl(data, par_threads(data.len()))
}

/// Non-decreasing check with NaN-poisoning: every consecutive pair must
/// satisfy `next >= prev`, and any NaN in either position fails the pair
/// (IEEE comparisons with NaN are false). This is exactly NumPy's
/// `all(diff(x) >= 0)` — the line/area sorted-ingest predicate (§28) — but
/// single-pass, allocation-free, and early-exit on the first violation.
pub fn is_sorted_f64(data: &[f64]) -> bool {
    data.windows(2).all(|pair| pair[1] >= pair[0])
}

/// Dispatches to the AVX2 clone when available (simd.rs).
fn min_max_scan(data: &[f64]) -> (f64, f64) {
    if let Some(mm) = crate::simd::try_min_max(data) {
        return mm;
    }
    min_max_scalar(data)
}

pub(crate) fn min_max_scalar(data: &[f64]) -> (f64, f64) {
    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for &v in data {
        if v.is_finite() {
            min = min.min(v);
            max = max.max(v);
        }
    }
    (min, max)
}

/// min/max are order-independent, so the chunked reduction is exactly the
/// serial result for any thread count.
fn min_max_impl(data: &[f64], threads: usize) -> Option<(f64, f64)> {
    let (min, max) = if threads <= 1 || data.len() < threads {
        min_max_scan(data)
    } else {
        let chunk = data.len().div_ceil(threads);
        std::thread::scope(|s| {
            let handles: Vec<_> = data
                .chunks(chunk)
                .map(|seg| s.spawn(move || min_max_scan(seg)))
                .collect();
            handles
                .into_iter()
                .map(|hd| hd.join().expect("min_max worker panicked"))
                .fold((f64::INFINITY, f64::NEG_INFINITY), |a, b| {
                    (a.0.min(b.0), a.1.max(b.1))
                })
        })
    };
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
    fn marching_squares_extracts_ambiguous_cell_segments() {
        let z = [0.0, 1.0, 1.0, 0.0];
        let x = [0.0, 1.0];
        let y = [0.0, 1.0];
        let levels = [0.5];
        let mut x0 = [0.0; 2];
        let mut x1 = [0.0; 2];
        let mut y0 = [0.0; 2];
        let mut y1 = [0.0; 2];
        let mut emitted_levels = [0.0; 2];
        let written = marching_squares_into(
            &z,
            2,
            2,
            &x,
            &y,
            &levels,
            &mut x0,
            &mut x1,
            &mut y0,
            &mut y1,
            &mut emitted_levels,
        );
        assert_eq!(written, 2);
        assert_eq!(x0, [0.5, 0.5]);
        assert_eq!(x1, [1.0, 0.0]);
        assert_eq!(y0, [0.0, 1.0]);
        assert_eq!(y1, [0.5, 0.5]);
        assert_eq!(emitted_levels, [0.5, 0.5]);
    }

    #[test]
    fn marching_squares_skips_nonfinite_cells() {
        let z = [f64::NAN, 1.0, 1.0, 0.0];
        let mut x0 = [0.0; 1];
        let mut x1 = [0.0; 1];
        let mut y0 = [0.0; 1];
        let mut y1 = [0.0; 1];
        let mut emitted_levels = [0.0; 1];
        let written = marching_squares_into(
            &z,
            2,
            2,
            &[0.0, 1.0],
            &[0.0, 1.0],
            &[0.5],
            &mut x0,
            &mut x1,
            &mut y0,
            &mut y1,
            &mut emitted_levels,
        );
        assert_eq!(written, 0);
    }

    #[test]
    fn bin_2d_indices_matches_separate_kernels() {
        // Random data with NaN and exact-boundary values: the fused kernel's
        // two outputs must be bitwise identical to bin_2d and range_indices.
        let n = 1_200_000;
        let mut x = Vec::with_capacity(n);
        let mut y = Vec::with_capacity(n);
        let mut state = 42u64;
        let mut rnd = || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            (state >> 11) as f64 / (1u64 << 53) as f64 * 200.0 - 100.0
        };
        for i in 0..n {
            if i % 997 == 0 {
                x.push(f64::NAN);
                y.push(rnd());
            } else if i % 1013 == 0 {
                // exact hi-edge: inside the inclusive index window,
                // outside the half-open grid window.
                x.push(95.0);
                y.push(0.0);
            } else {
                x.push(rnd());
                y.push(rnd());
            }
        }
        let (lo_x, hi_x, lo_y, hi_y, w, h) = (-95.0, 95.0, -80.0, 80.0, 128, 96);

        let mut grid_ref = vec![0.0f32; w * h];
        bin_2d(&x, &y, lo_x, hi_x, lo_y, hi_y, w, h, &mut grid_ref);
        let mut idx_ref = vec![0u32; n];
        let m_ref = range_indices(&x, &y, lo_x, hi_x, lo_y, hi_y, &mut idx_ref);

        for threads in [1, 4] {
            let mut grid = vec![0.0f32; w * h];
            let mut idx = vec![0u32; n];
            let m = bin_2d_indices_impl(
                &x, &y, lo_x, hi_x, lo_y, hi_y, w, h, threads, &mut grid, &mut idx,
            );
            assert_eq!(m, m_ref, "threads={threads}");
            assert_eq!(idx[..m], idx_ref[..m_ref], "threads={threads}");
            assert_eq!(grid, grid_ref, "threads={threads}");
        }
    }

    #[test]
    fn bin_2d_indices_edge_point_indexed_but_not_binned() {
        // One point exactly on the inclusive hi edge: present in the index
        // list (range semantics) but not counted in any cell (bin semantics).
        let x = [1.0, 0.5];
        let y = [0.5, 0.5];
        let mut grid = vec![0.0f32; 4];
        let mut idx = vec![0u32; 2];
        let m = bin_2d_indices(&x, &y, 0.0, 1.0, 0.0, 1.0, 2, 2, &mut grid, &mut idx);
        assert_eq!(m, 2);
        assert_eq!(&idx[..2], &[0, 1]);
        assert_eq!(grid.iter().sum::<f32>(), 1.0); // only the interior point binned
    }

    #[test]
    fn splitmix64_known_vectors() {
        // Reference values from the Python side (lod.hash_row_ids), which the
        // parity test in tests/test_kernels.py also asserts — keep in sync.
        assert_eq!(splitmix64(0, 0), 0xE220_A839_7B1D_CDAF);
        assert_eq!(splitmix64(1, 0), 0x910A_2DEC_8902_5CC1);
        assert_eq!(splitmix64(0, 1), 0x910A_2DEC_8902_5CC1); // id+seed symmetric
        assert_eq!(splitmix64(u64::MAX, 0), splitmix64(0, u64::MAX)); // wrapping
    }

    #[test]
    fn sample_mask_serial_and_parallel_agree() {
        let ids: Vec<u64> = (0..1_500_000).collect();
        let threshold = u64::MAX / 64;
        let mut serial = vec![0u8; ids.len()];
        let mut parallel = vec![0u8; ids.len()];
        sample_mask_impl(&ids, 7, threshold, 1, &mut serial);
        sample_mask_impl(&ids, 7, threshold, 4, &mut parallel);
        assert_eq!(serial, parallel);
        let kept: usize = serial.iter().map(|&b| b as usize).sum();
        // ~1/64 of rows expected; loose bounds guard against a broken hash
        assert!(kept > ids.len() / 128 && kept < ids.len() / 32, "kept {kept}");
    }

    #[test]
    fn sample_mask_empty_and_full_threshold() {
        let ids: Vec<u64> = (0..100).collect();
        let mut out = vec![0u8; 100];
        sample_mask(&ids, 0, u64::MAX, &mut out);
        assert!(out.iter().all(|&b| b == 1));
        sample_mask(&ids, 0, 0, &mut out);
        // threshold 0 keeps only rows whose hash is exactly 0 — none here
        assert!(out.iter().all(|&b| b == 0));
    }

    /// Direct port of the per-category NumPy loop this kernel replaced
    /// (`lod.stratified_sample_keep_mask` before the fused pass) — the
    /// oracle for the parity test.
    fn stratified_reference(
        ids: &[u64],
        groups: &[u32],
        n_groups: usize,
        seed: u64,
        fraction: f64,
        min_count: u64,
    ) -> Vec<u8> {
        let n = ids.len() as f64;
        let mut out = vec![0u8; ids.len()];
        for g in 0..n_groups as u32 {
            let idx: Vec<usize> = (0..ids.len()).filter(|&i| groups[i] == g).collect();
            if idx.is_empty() {
                continue;
            }
            let gf = fraction * (n / idx.len() as f64).sqrt();
            let th = sample_threshold(gf);
            let mut kept = 0usize;
            for &i in &idx {
                if splitmix64(ids[i], seed) <= th {
                    out[i] = 1;
                    kept += 1;
                }
            }
            let floor = (min_count as usize).min(idx.len());
            if kept < floor {
                let mut hashed: Vec<(u64, usize)> =
                    idx.iter().map(|&i| (splitmix64(ids[i], seed), i)).collect();
                hashed.sort_unstable();
                for &(_, i) in &hashed[..floor] {
                    out[i] = 1;
                }
            }
        }
        out
    }

    #[test]
    fn stratified_sample_mask_matches_reference() {
        // Skewed groups: one dominant, one mid, one rare — plus distinct ids
        // shuffled so group runs don't align with thread chunks.
        let len = 30_000usize;
        let ids: Vec<u64> = (0..len as u64).map(|i| splitmix64(i, 99)).collect();
        let groups: Vec<u32> = (0..len)
            .map(|i| match i % 1000 {
                0 => 2,
                x if x < 100 => 1,
                _ => 0,
            })
            .collect();
        for (fraction, min_count) in [(1.0 / 4096.0, 1), (1.0 / 64.0, 3), (0.5, 0)] {
            let mut got = vec![0u8; len];
            assert!(stratified_sample_mask(
                &ids, &groups, 3, 7, fraction, min_count, &mut got
            ));
            let want = stratified_reference(&ids, &groups, 3, 7, fraction, min_count);
            assert_eq!(got, want, "fraction={fraction} min_count={min_count}");
        }
    }

    #[test]
    fn stratified_sample_mask_pins_rare_and_stays_monotonic() {
        let len = 8_104usize;
        let ids: Vec<u64> = (0..len as u64).collect();
        let groups: Vec<u32> = (0..len)
            .map(|i| if i < 8_000 { 0 } else if i < 8_100 { 1 } else { 2 })
            .collect();
        let mut lo = vec![0u8; len];
        let mut hi = vec![0u8; len];
        let base = 1.0 / 4096.0;
        assert!(stratified_sample_mask(&ids, &groups, 3, 23, base, 1, &mut lo));
        assert!(stratified_sample_mask(&ids, &groups, 3, 23, base * 32.0, 1, &mut hi));
        for g in 0..3u32 {
            let kept: u64 = lo
                .iter()
                .zip(&groups)
                .filter(|&(_, &gg)| gg == g)
                .map(|(&k, _)| u64::from(k))
                .sum();
            assert!(kept >= 1, "group {g} lost its floor row");
        }
        assert!(lo.iter().zip(&hi).all(|(&a, &b)| a <= b), "mask not monotonic");
        let (nlo, nhi): (u64, u64) = (
            lo.iter().map(|&b| u64::from(b)).sum(),
            hi.iter().map(|&b| u64::from(b)).sum(),
        );
        assert!(nhi > nlo);
    }

    #[test]
    fn stratified_sample_mask_rejects_out_of_range_group() {
        let ids = [1u64, 2, 3];
        let groups = [0u32, 5, 0]; // 5 >= n_groups
        let mut out = [0u8; 3];
        assert!(!stratified_sample_mask(&ids, &groups, 2, 0, 0.5, 1, &mut out));
    }

    #[test]
    fn sample_threshold_matches_python_reference() {
        // int(0.5 * (2**64 - 1) as f64) computed by the Python reference.
        assert_eq!(sample_threshold(0.5), 9_223_372_036_854_775_808);
        assert_eq!(sample_threshold(1.0), u64::MAX);
        assert_eq!(sample_threshold(2.0), u64::MAX);
        assert_eq!(sample_threshold(0.0), 0);
        assert_eq!(sample_threshold(-1.0), 0);
    }

    #[test]
    fn zone_maps_basic() {
        let data: Vec<f64> = (0..10).map(|i| i as f64).collect();
        let zms = zone_maps(&data, 4);
        assert_eq!(zms.len(), 3);
        assert_eq!(zms[0].min, 0.0);
        assert_eq!(zms[0].max, 3.0);
        assert_eq!(zms[0].positive_min, 1.0);
        assert_eq!(zms[0].positive_max, 3.0);
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
        assert_eq!(zms[0].positive_min, 1.0);
        assert_eq!(zms[0].positive_max, 3.0);
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
        assert_eq!(zms[0].positive_min, 1.0);
        assert_eq!(zms[0].positive_max, 3.0);
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
            if n > 4 && rng.next().is_multiple_of(4) {
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
    fn fuzz_parallel_matches_serial() {
        // The public fns only fan out past PAR_THRESHOLD, so drive the impl
        // directly: hostile data must produce bitwise-identical results for
        // every thread count (including threads > n and empty tail chunks).
        let mut rng = Rng(0x5EED_000A);
        for it in 0..120 {
            let n = (rng.next() % 2000) as usize;
            let x = rng.hostile_vec(n, -10.0, 10.0);
            let y = rng.hostile_vec(n, -10.0, 10.0);
            let (w, h) = (1 + (rng.next() % 16) as usize, 1 + (rng.next() % 12) as usize);
            let (x0, x1, y0, y1) = (-5.0, 7.0, -6.0, 4.0);
            let mut serial = vec![0f32; w * h];
            bin_2d_impl(&x, &y, x0, x1, y0, y1, w, h, 1, &mut serial);
            let bins = 1 + (rng.next() % 64) as usize;
            let mut hs = vec![0f64; bins];
            let ts = histogram_uniform_impl(&x, -8.0, 8.0, 1, &mut hs);
            // m4 needs ascending x (ingest contract); duplicate-heavy so
            // bucket runs regularly straddle naive split points.
            let mx: Vec<f64> = (0..n).map(|i| (i / 3) as f64).collect();
            let buckets_m4 = 1 + (rng.next() % 48) as usize;
            let (s0, s1) = (0usize, n);
            let m4_serial = m4_indices_impl(&mx, &y, -1.0, n as f64 + 1.0, buckets_m4, s0, s1, 1);
            let zm_serial = zone_maps_impl(&x, 64, 1);
            let mut ri_serial = vec![0u32; n.max(1)];
            let rn_serial =
                range_indices_impl(&x, &y, -5.0, 7.0, -6.0, 4.0, 1, &mut ri_serial[..n]);
            for threads in [2usize, 3, 5] {
                let mut par = vec![0f32; w * h];
                bin_2d_impl(&x, &y, x0, x1, y0, y1, w, h, threads, &mut par);
                let sb: Vec<u32> = serial.iter().map(|v| v.to_bits()).collect();
                let pb: Vec<u32> = par.iter().map(|v| v.to_bits()).collect();
                assert_eq!(sb, pb, "bin_2d parity it={it} threads={threads}");
                let mut hp = vec![0f64; bins];
                let tp = histogram_uniform_impl(&x, -8.0, 8.0, threads, &mut hp);
                assert_eq!(ts, tp, "histogram total parity it={it} threads={threads}");
                assert_eq!(hs, hp, "histogram bins parity it={it} threads={threads}");
                let zm_par = zone_maps_impl(&x, 64, threads);
                assert_eq!(zm_serial, zm_par, "zone_maps parity it={it} threads={threads}");
                let m4_par =
                    m4_indices_impl(&mx, &y, -1.0, n as f64 + 1.0, buckets_m4, s0, s1, threads);
                assert_eq!(m4_serial, m4_par, "m4 parity it={it} threads={threads}");
                assert_eq!(
                    min_max_impl(&x, 1),
                    min_max_impl(&x, threads),
                    "min_max parity it={it} threads={threads}"
                );
                let mut ri_par = vec![0u32; n.max(1)];
                let rn_par =
                    range_indices_impl(&x, &y, -5.0, 7.0, -6.0, 4.0, threads, &mut ri_par[..n]);
                assert_eq!(rn_serial, rn_par, "range count parity it={it} threads={threads}");
                assert_eq!(
                    ri_serial[..rn_serial],
                    ri_par[..rn_par],
                    "range indices parity it={it} threads={threads}"
                );
            }
        }
    }

    #[test]
    fn fuzz_elementwise_parallel_parity() {
        // encode/normalize fan out only past PAR_THRESHOLD, so exercise the
        // public fns at threshold size once (real threads, hostile data) and
        // compare against a hand-rolled serial reference.
        let mut rng = Rng(0x5EED_000B);
        let n = super::PAR_THRESHOLD;
        let data = rng.hostile_vec(n, -1e6, 1e6);
        let mut enc = vec![0f32; n];
        encode_f32_into(&data, 12.5, 3.0, &mut enc);
        let mut norm = vec![0f32; n];
        normalize_f32_into(&data, -1e6, 1e6, 0.0, &mut norm);
        for (i, &v) in data.iter().enumerate() {
            let e = ((v - 12.5) * 3.0) as f32;
            assert_eq!(enc[i].to_bits(), e.to_bits(), "encode i={i}");
            let r = if v.is_finite() {
                (((v - -1e6) / 2e6).clamp(0.0, 1.0)) as f32
            } else {
                0.0
            };
            assert_eq!(norm[i].to_bits(), r.to_bits(), "normalize i={i}");
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

    #[test]
    fn is_sorted_matches_numpy_diff_predicate() {
        assert!(is_sorted_f64(&[]));
        assert!(is_sorted_f64(&[3.0]));
        assert!(is_sorted_f64(&[f64::NAN])); // no pairs -> sorted, like all(diff) on empty
        assert!(is_sorted_f64(&[1.0, 1.0, 2.0]));
        assert!(is_sorted_f64(&[f64::NEG_INFINITY, 0.0, f64::INFINITY]));
        assert!(!is_sorted_f64(&[2.0, 1.0]));
        assert!(!is_sorted_f64(&[1.0, f64::NAN, 3.0])); // NaN poisons its pairs
        assert!(!is_sorted_f64(&[1.0, 2.0, f64::NAN]));
        assert!(!is_sorted_f64(&[f64::NAN, 1.0, 2.0]));
        assert!(!is_sorted_f64(&[0.0, 1.0, 5.0, 4.0, 9.0]));
    }
}
