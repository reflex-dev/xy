//! Spatial sort: reorder canonical (lon, lat) f64 columns into a grid-bucketed
//! layout so a viewport query reads only its in-window points, not the whole
//! column. This is the Tier-3 out-of-core index (xy dossier §28/§32b): the
//! per-viewport cost drops from O(N) to O(points in window), so zoom gets
//! *sharper and faster* the deeper you go.
//!
//! Output is a derived f32 cache (half the bytes; ~1 m geo precision is plenty
//! for rendering — the f64 canonical store remains the source of truth):
//!   - `<out>_lon.f32`, `<out>_lat.f32`: points sorted by row-major grid cell
//!   - `<out>.idx`: header + (g*g + 1) u64 cumulative offsets (prefix sum), so
//!     cell b owns points [off[b], off[b+1]); a window's cells are contiguous
//!     per grid row → one slice read per row.
//!
//! Algorithm: an external counting sort that never holds all N in RAM and does
//! sequential I/O only. Pass 1 histograms cell counts. Points are then split
//! into P equal-count partitions (skew-proof) written as sequential f32 files;
//! each partition (sized to RAM) is counting-sorted in memory and appended to
//! the final columns in cell order. Peak RAM ≈ one partition.

use std::fs::File;
use std::io::{self, BufWriter, Read, Write};
use std::os::unix::fs::FileExt;
use std::path::Path;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::time::Instant;

const MAGIC: &[u8; 8] = b"XYSPIDX1";

fn nthreads() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
}

/// Read exactly `buf.len()` f64 at byte offset `off*8` via a positional read
/// (thread-safe, no shared cursor — many threads scan disjoint slices at once).
fn read_f64_at(f: &File, buf: &mut [f64], point_off: u64) -> io::Result<()> {
    let bytes =
        unsafe { std::slice::from_raw_parts_mut(buf.as_mut_ptr() as *mut u8, buf.len() * 8) };
    f.read_exact_at(bytes, point_off * 8)
}

pub struct SortStats {
    pub n: u64,
    pub g: usize,
    pub partitions: usize,
    pub max_partition: u64,
}

#[inline]
fn cell_of(v: f64, lo: f64, inv_span_g: f64, g: usize) -> usize {
    // Bucket by the *f32* value the index stores, not the f64 source: passes 1/2
    // see f64 and pass 3 sees the round-tripped f32, so rounding to f32 here
    // makes the cell identical across all passes (else a boundary point lands in
    // a different partition than its file → out of range). Clamp to [0, g-1].
    let vf = (v as f32) as f64;
    let c = ((vf - lo) * inv_span_g) as isize;
    c.max(0).min(g as isize - 1) as usize
}

/// Append a thread-local scatter buffer to partition `q`'s file at a
/// reserved, non-overlapping offset. `pwrite` to disjoint ranges is safe from
/// many threads without a lock, so pass 2 fans out across cores while still
/// producing exactly `used_parts` files (not threads×parts — that would blow
/// the open-fd limit). Order within a partition file is arbitrary; pass 3
/// counting-sorts by cell regardless.
fn flush_part(files: &[File], tails: &[AtomicU64], q: usize, buf: &mut Vec<u8>) -> io::Result<()> {
    if buf.is_empty() {
        return Ok(());
    }
    let at = tails[q].fetch_add(buf.len() as u64, Ordering::Relaxed);
    files[q].write_all_at(buf, at)?;
    buf.clear();
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn spatial_sort(
    lon_path: &Path,
    lat_path: &Path,
    out_prefix: &Path,
    g: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    n_partitions: usize,
) -> io::Result<SortStats> {
    let n = File::open(lon_path)?.metadata()?.len() / 8;
    let cells = g * g;
    let inv_x = g as f64 / (x1 - x0);
    let inv_y = g as f64 / (y1 - y0);
    let block = 1usize << 20; // 1M values per I/O chunk

    // ---- Pass 1: histogram cell counts, parallel over disjoint slices --------
    // Each thread positionally reads its slice and folds a private histogram;
    // the T partials are then summed. Turns a read-bound O(N) scan into a
    // parallel one that saturates NVMe bandwidth.
    let threads = nthreads();
    let mut counts = vec![0u64; cells];
    let t_p1 = Instant::now();
    {
        let lon_f = File::open(lon_path)?;
        let lat_f = File::open(lat_path)?;
        let per = n.div_ceil(threads as u64);
        let partials: Vec<io::Result<Vec<u64>>> = std::thread::scope(|s| {
            let hs: Vec<_> = (0..threads)
                .map(|ti| {
                    let (lon_f, lat_f) = (&lon_f, &lat_f);
                    s.spawn(move || -> io::Result<Vec<u64>> {
                        let mut local = vec![0u64; cells];
                        let (start, end) = (ti as u64 * per, ((ti as u64 + 1) * per).min(n));
                        let (mut lb, mut tb) = (vec![0f64; block], vec![0f64; block]);
                        let mut off = start;
                        while off < end {
                            let k = (block as u64).min(end - off) as usize;
                            read_f64_at(lon_f, &mut lb[..k], off)?;
                            read_f64_at(lat_f, &mut tb[..k], off)?;
                            for i in 0..k {
                                let cx = cell_of(lb[i], x0, inv_x, g);
                                let cy = cell_of(tb[i], y0, inv_y, g);
                                local[cy * g + cx] += 1;
                            }
                            off += k as u64;
                        }
                        Ok(local)
                    })
                })
                .collect();
            hs.into_iter().map(|h| h.join().unwrap()).collect()
        });
        for pres in partials {
            let local = pres?;
            for b in 0..cells {
                counts[b] += local[b];
            }
        }
    }

    eprintln!("  pass 1 (histogram): {:.1}s", t_p1.elapsed().as_secs_f64());

    // ---- Prefix sum → cell start offsets; equal-count partition boundaries ---
    let mut offsets = vec![0u64; cells + 1];
    for b in 0..cells {
        offsets[b + 1] = offsets[b] + counts[b];
    }
    let total = offsets[cells];
    // Partition p owns cell range [cell_lo[p], cell_lo[p+1]); boundaries chosen
    // so each partition holds ≈ total/P points. A cell→partition LUT makes the
    // scatter O(1)/point.
    let target = total.div_ceil(n_partitions as u64).max(1);
    let mut part_of = vec![0u32; cells];
    let mut cell_lo = vec![0usize; n_partitions + 1];
    let mut p = 0usize;
    for b in 0..cells {
        while p + 1 < n_partitions && offsets[b] >= (p as u64 + 1) * target {
            p += 1;
            cell_lo[p] = b;
        }
        part_of[b] = p as u32;
    }
    for slot in &mut cell_lo[p + 1..=n_partitions] {
        *slot = cells;
    }
    let used_parts = p + 1;

    // ---- Pass 2: scatter points into per-partition f32 files (sequential) ----
    let t_p2 = Instant::now();
    let tmp: Vec<_> = (0..used_parts)
        .map(|q| out_prefix.with_extension(format!("part{q}")))
        .collect();
    {
        // T threads each scatter a disjoint input slice into per-thread-local
        // buffers keyed by partition, appending to the shared partition files
        // via reserved-offset positional writes (see `flush_part`). Fully
        // parallel — pass 2 is no longer the serial floor.
        let files: Vec<File> = tmp.iter().map(File::create).collect::<io::Result<_>>()?;
        let tails: Vec<AtomicU64> = (0..used_parts).map(|_| AtomicU64::new(0)).collect();
        let lon_f = File::open(lon_path)?;
        let lat_f = File::open(lat_path)?;
        let per = n.div_ceil(threads as u64);
        // Per-partition local buffer size before a positional write; 128 KiB
        // keeps write syscalls coarse while the working set stays ≈ threads ×
        // used_parts × 128 KiB (~1 GiB at 16×512).
        const FLUSH: usize = 1 << 17;
        let (files, tails, part_of) = (&files, &tails, &part_of);
        let results: Vec<io::Result<()>> = std::thread::scope(|s| {
            let hs: Vec<_> = (0..threads)
                .map(|ti| {
                    let (lon_f, lat_f) = (&lon_f, &lat_f);
                    s.spawn(move || -> io::Result<()> {
                        let (start, end) = (ti as u64 * per, ((ti as u64 + 1) * per).min(n));
                        let (mut lb, mut tb) = (vec![0f64; block], vec![0f64; block]);
                        let mut bufs: Vec<Vec<u8>> = (0..used_parts)
                            .map(|_| Vec::with_capacity(FLUSH + 8))
                            .collect();
                        let mut off = start;
                        while off < end {
                            let k = (block as u64).min(end - off) as usize;
                            read_f64_at(lon_f, &mut lb[..k], off)?;
                            read_f64_at(lat_f, &mut tb[..k], off)?;
                            for i in 0..k {
                                let cx = cell_of(lb[i], x0, inv_x, g);
                                let cy = cell_of(tb[i], y0, inv_y, g);
                                let q = part_of[cy * g + cx] as usize;
                                let b = &mut bufs[q];
                                b.extend_from_slice(&(lb[i] as f32).to_le_bytes());
                                b.extend_from_slice(&(tb[i] as f32).to_le_bytes());
                                if b.len() >= FLUSH {
                                    flush_part(files, tails, q, b)?;
                                }
                            }
                            off += k as u64;
                        }
                        for (q, buf) in bufs.iter_mut().enumerate() {
                            flush_part(files, tails, q, buf)?;
                        }
                        Ok(())
                    })
                })
                .collect();
            hs.into_iter().map(|h| h.join().unwrap()).collect()
        });
        for r in results {
            r?;
        }
    }
    eprintln!("  pass 2 (scatter):   {:.1}s", t_p2.elapsed().as_secs_f64());

    // ---- Pass 3: counting-sort each partition in RAM → final columns ---------
    let t_p3 = Instant::now();
    // Partitions are independent and land in disjoint, known output ranges
    // (offsets[cell_lo[q]]), so workers sort them in parallel and write each
    // straight to its slice via a positional write — no ordering barrier.
    let out_lon = File::create(out_prefix.with_extension("lon.f32"))?;
    let out_lat = File::create(out_prefix.with_extension("lat.f32"))?;
    out_lon.set_len(total * 4)?;
    out_lat.set_len(total * 4)?;
    let next = AtomicUsize::new(0);
    let max_partition = AtomicUsize::new(0);
    let results: Vec<io::Result<()>> = std::thread::scope(|s| {
        let hs: Vec<_> = (0..threads)
            .map(|_| {
                let (next, max_partition) = (&next, &max_partition);
                let (out_lon, out_lat, tmp, offsets, cell_lo) =
                    (&out_lon, &out_lat, &tmp, &offsets, &cell_lo);
                s.spawn(move || -> io::Result<()> {
                    loop {
                        let q = next.fetch_add(1, Ordering::Relaxed);
                        if q >= used_parts {
                            return Ok(());
                        }
                        let (b_lo, b_hi) = (cell_lo[q], cell_lo[q + 1]);
                        let base = offsets[b_lo];
                        let m = (offsets[b_hi] - base) as usize;
                        max_partition.fetch_max(m, Ordering::Relaxed);
                        let mut raw = vec![0u8; m * 8];
                        File::open(&tmp[q])?.read_exact(&mut raw)?;
                        let pairs = unsafe {
                            std::slice::from_raw_parts(raw.as_ptr() as *const f32, m * 2)
                        };
                        let span = b_hi - b_lo;
                        let mut cur = vec![0u32; span + 1];
                        for i in 0..m {
                            let cx = cell_of(pairs[2 * i] as f64, x0, inv_x, g);
                            let cy = cell_of(pairs[2 * i + 1] as f64, y0, inv_y, g);
                            cur[(cy * g + cx) - b_lo + 1] += 1;
                        }
                        for k in 0..span {
                            cur[k + 1] += cur[k];
                        }
                        let (mut slon, mut slat) = (vec![0f32; m], vec![0f32; m]);
                        for i in 0..m {
                            let cx = cell_of(pairs[2 * i] as f64, x0, inv_x, g);
                            let cy = cell_of(pairs[2 * i + 1] as f64, y0, inv_y, g);
                            let slot = &mut cur[(cy * g + cx) - b_lo];
                            slon[*slot as usize] = pairs[2 * i];
                            slat[*slot as usize] = pairs[2 * i + 1];
                            *slot += 1;
                        }
                        out_lon.write_all_at(
                            unsafe {
                                std::slice::from_raw_parts(slon.as_ptr() as *const u8, m * 4)
                            },
                            base * 4,
                        )?;
                        out_lat.write_all_at(
                            unsafe {
                                std::slice::from_raw_parts(slat.as_ptr() as *const u8, m * 4)
                            },
                            base * 4,
                        )?;
                        std::fs::remove_file(&tmp[q])?;
                    }
                })
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });
    for r in results {
        r?;
    }
    let max_partition = max_partition.load(Ordering::Relaxed) as u64;
    eprintln!("  pass 3 (sort+write):{:.1}s", t_p3.elapsed().as_secs_f64());

    // ---- Index file: header + cumulative offsets ----------------------------
    let mut idx = BufWriter::new(File::create(out_prefix.with_extension("idx"))?);
    idx.write_all(MAGIC)?;
    idx.write_all(&(g as u32).to_le_bytes())?;
    idx.write_all(&0u32.to_le_bytes())?;
    for v in [x0, x1, y0, y1] {
        idx.write_all(&v.to_le_bytes())?;
    }
    idx.write_all(&total.to_le_bytes())?;
    let off_bytes =
        unsafe { std::slice::from_raw_parts(offsets.as_ptr() as *const u8, offsets.len() * 8) };
    idx.write_all(off_bytes)?;
    idx.flush()?;

    Ok(SortStats {
        n,
        g,
        partitions: used_parts,
        max_partition,
    })
}
