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

use std::collections::{BinaryHeap, HashMap};

const MAX_ROW_THREADS: usize = 18;

/// Factor fixed-width records in first-seen order without materializing Python
/// objects. `codes[i]` identifies `data[i * width..]`; `unique_indices` stores
/// the first row for every emitted code. The caller may reorder the compact
/// unique set afterward (categorical display labels sort lexically in Python).
pub fn factorize_fixed_into(
    data: &[u8],
    width: usize,
    codes: &mut [u32],
    unique_indices: &mut [u32],
) -> Option<usize> {
    if data.len().checked_rem(width) != Some(0) {
        return None;
    }
    let n = data.len() / width;
    if codes.len() < n || unique_indices.len() < n || n > u32::MAX as usize {
        return None;
    }
    // Keys borrow immutable rows from the call-scoped input arena. Avoiding a
    // heap allocation per distinct label matters for high-cardinality data.
    let mut groups: HashMap<&[u8], u32> = HashMap::new();
    let mut unique_count = 0usize;
    for (row_index, row) in data.chunks_exact(width).enumerate() {
        let code = if let Some(&code) = groups.get(row) {
            code
        } else {
            let code = u32::try_from(unique_count).ok()?;
            groups.insert(row, code);
            unique_indices[unique_count] = u32::try_from(row_index).ok()?;
            unique_count += 1;
            code
        };
        codes[row_index] = code;
    }
    Some(unique_count)
}

/// Compact variant for palette-sized categorical sets. Returns `None` when
/// the unique-index capacity (at most 256 for u8 codes) is exceeded; callers
/// can then retry the general u32 path without risking code wraparound.
#[inline(always)]
fn compact_record_hash(record: &[u8]) -> u64 {
    #[inline(always)]
    fn avalanche(mut value: u64) -> u64 {
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }

    if record.len() <= 8 {
        return compact_narrow_hash(compact_record_key(record), record.len());
    }
    let mut hash = (record.len() as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    for chunk in record.chunks(8) {
        let mut bytes = [0u8; 8];
        bytes[..chunk.len()].copy_from_slice(chunk);
        hash ^= avalanche(u64::from_ne_bytes(bytes));
        hash = hash.rotate_left(27).wrapping_mul(0x3C79_AC49_2BA7_B653);
    }
    avalanche(hash)
}

#[inline(always)]
fn compact_record_key(record: &[u8]) -> u64 {
    let mut bytes = [0u8; 8];
    bytes[..record.len()].copy_from_slice(record);
    u64::from_ne_bytes(bytes)
}

#[inline(always)]
fn compact_narrow_hash(key: u64, width: usize) -> u64 {
    let mut value = key ^ (width as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    value ^= value >> 32;
    value = value.wrapping_mul(0xD6E8_FEB8_6659_FD93);
    value ^ (value >> 32)
}

#[derive(Clone)]
struct CompactCodebook {
    slots: [u16; 512],
    hashes: [u64; 256],
    first_indices: [u32; 256],
    len: usize,
}

struct CompactFactorization {
    codebook: CompactCodebook,
    counts: [u64; 256],
}

impl CompactCodebook {
    fn new() -> Self {
        Self {
            slots: [u16::MAX; 512],
            hashes: [0; 256],
            first_indices: [u32::MAX; 256],
            len: 0,
        }
    }

    #[inline(always)]
    fn lookup(&self, data: &[u8], width: usize, record: &[u8], hash: u64) -> Option<u8> {
        let mut slot = hash as usize & (self.slots.len() - 1);
        loop {
            let entry = self.slots[slot];
            if entry == u16::MAX {
                return None;
            }
            let code = entry as usize;
            let first = self.first_indices[code] as usize;
            if self.hashes[code] == hash && &data[first * width..(first + 1) * width] == record {
                return Some(code as u8);
            }
            slot = (slot + 1) & (self.slots.len() - 1);
        }
    }

    #[inline(always)]
    fn find_or_insert(
        &mut self,
        data: &[u8],
        width: usize,
        row_index: usize,
        record: &[u8],
        capacity: usize,
    ) -> Option<(u8, bool)> {
        let hash = compact_record_hash(record);
        let mut slot = hash as usize & (self.slots.len() - 1);
        loop {
            let entry = self.slots[slot];
            if entry == u16::MAX {
                if self.len >= capacity {
                    return None;
                }
                let code = u8::try_from(self.len).ok()?;
                self.slots[slot] = u16::from(code);
                self.hashes[self.len] = hash;
                self.first_indices[self.len] = u32::try_from(row_index).ok()?;
                self.len += 1;
                return Some((code, true));
            }
            let code = entry as usize;
            let first = self.first_indices[code] as usize;
            if self.hashes[code] == hash && &data[first * width..(first + 1) * width] == record {
                return Some((code as u8, false));
            }
            slot = (slot + 1) & (self.slots.len() - 1);
        }
    }
}

fn factorize_fixed_u8_serial(
    data: &[u8],
    width: usize,
    codes: &mut [u8],
    capacity: usize,
) -> Option<CompactFactorization> {
    let mut codebook = CompactCodebook::new();
    let mut counts = [0u64; 256];
    for (row_index, record) in data.chunks_exact(width).enumerate() {
        let code = codebook
            .find_or_insert(data, width, row_index, record, capacity)?
            .0;
        codes[row_index] = code;
        counts[code as usize] += 1;
    }
    Some(CompactFactorization { codebook, counts })
}

fn factorize_threads(n: usize) -> usize {
    par_threads(n)
}

/// Probe a small prefix to establish the usual compact palette, then encode
/// disjoint output chunks in parallel against that immutable codebook. If a
/// late category exists, worker-local first-seen lists are merged in canonical
/// row order and one final parallel encode applies the completed codebook.
fn factorize_fixed_u8_parallel(
    data: &[u8],
    width: usize,
    codes: &mut [u8],
    capacity: usize,
    threads: usize,
) -> Option<CompactFactorization> {
    const PROBE_ROWS: usize = 4096;
    let n = codes.len();
    let prefix = n.min(PROBE_ROWS);
    let mut codebook = CompactCodebook::new();
    let mut prefix_counts = [0u64; 256];
    for (row_index, record) in data[..prefix * width].chunks_exact(width).enumerate() {
        let code = codebook
            .find_or_insert(data, width, row_index, record, capacity)?
            .0;
        codes[row_index] = code;
        prefix_counts[code as usize] += 1;
    }
    if prefix == n {
        return Some(CompactFactorization {
            codebook,
            counts: prefix_counts,
        });
    }

    let base_len = codebook.len;
    let remaining = n - prefix;
    let rows_per = remaining.div_ceil(threads);
    let data_per = rows_per * width;
    let discoveries = std::thread::scope(|scope| -> Option<Vec<(Vec<u32>, [u64; 256])>> {
        let handles: Vec<_> = data[prefix * width..]
            .chunks(data_per)
            .zip(codes[prefix..].chunks_mut(rows_per))
            .enumerate()
            .map(|(chunk_index, (data_chunk, code_chunk))| {
                let mut local = codebook.clone();
                scope.spawn(move || -> Option<(Vec<u32>, [u64; 256])> {
                    let start = prefix + chunk_index * rows_per;
                    let mut counts = [0u64; 256];
                    for (offset, record) in data_chunk.chunks_exact(width).enumerate() {
                        let code = local
                            .find_or_insert(data, width, start + offset, record, capacity)?
                            .0;
                        code_chunk[offset] = code;
                        counts[code as usize] += 1;
                    }
                    Some((local.first_indices[base_len..local.len].to_vec(), counts))
                })
            })
            .collect();
        let mut discovered = Vec::with_capacity(handles.len());
        for handle in handles {
            discovered.push(
                handle
                    .join()
                    .expect("compact-factorization worker panicked")?,
            );
        }
        Some(discovered)
    })?;

    for (chunk, _) in &discoveries {
        for row_index in chunk {
            let row_index = *row_index as usize;
            let record = &data[row_index * width..(row_index + 1) * width];
            codebook.find_or_insert(data, width, row_index, record, capacity)?;
        }
    }
    if codebook.len == base_len {
        let mut counts = prefix_counts;
        for (_, part) in discoveries {
            for (total, value) in counts.iter_mut().zip(part) {
                *total += value;
            }
        }
        return Some(CompactFactorization { codebook, counts });
    }

    // At least one category first appeared beyond the prefix. Worker-local
    // provisional codes can differ, so overwrite every row from the merged
    // first-seen codebook. This uncommon path still has bounded memory.
    let rows_per = n.div_ceil(threads);
    let data_per = rows_per * width;
    let parts = std::thread::scope(|scope| -> Option<Vec<[u64; 256]>> {
        let handles: Vec<_> = data
            .chunks(data_per)
            .zip(codes.chunks_mut(rows_per))
            .map(|(data_chunk, code_chunk)| {
                let codebook = &codebook;
                scope.spawn(move || -> Option<[u64; 256]> {
                    let mut counts = [0u64; 256];
                    for (record, output) in data_chunk.chunks_exact(width).zip(code_chunk) {
                        let hash = compact_record_hash(record);
                        let code = codebook.lookup(data, width, record, hash)?;
                        *output = code;
                        counts[code as usize] += 1;
                    }
                    Some(counts)
                })
            })
            .collect();
        let mut parts = Vec::with_capacity(handles.len());
        for handle in handles {
            parts.push(
                handle
                    .join()
                    .expect("compact-factorization retry worker panicked")?,
            );
        }
        Some(parts)
    })?;
    let mut counts = [0u64; 256];
    for part in parts {
        for (total, value) in counts.iter_mut().zip(part) {
            *total += value;
        }
    }
    Some(CompactFactorization { codebook, counts })
}

/// Direct-value specialization for one-byte records. A bounded prefix usually
/// establishes the complete value→code table; workers then encode disjoint
/// spans and accumulate raw-value counts in one pass. Values first seen later
/// are ordered by their global first row and trigger one cheap remap pass.
fn factorize_byte_values_parallel(
    data: &[u8],
    codes: &mut [u8],
    capacity: usize,
    threads: usize,
) -> Option<CompactFactorization> {
    const PROBE_ROWS: usize = 4096;
    let prefix = data.len().min(PROBE_ROWS);
    let mut table = [u16::MAX; 256];
    let mut codebook = CompactCodebook::new();
    let mut raw_counts = [0u64; 256];
    for (row, &value) in data[..prefix].iter().enumerate() {
        let entry = &mut table[value as usize];
        if *entry == u16::MAX {
            if codebook.len >= capacity {
                return None;
            }
            *entry = codebook.len as u16;
            codebook.first_indices[codebook.len] = row as u32;
            codebook.len += 1;
        }
        codes[row] = *entry as u8;
        raw_counts[value as usize] += 1;
    }
    if prefix < data.len() {
        let remaining = data.len() - prefix;
        let per = remaining.div_ceil(threads);
        let parts = std::thread::scope(|scope| {
            let handles: Vec<_> = data[prefix..]
                .chunks(per)
                .zip(codes[prefix..].chunks_mut(per))
                .enumerate()
                .map(|(chunk_index, (values, outputs))| {
                    let table = &table;
                    scope.spawn(move || {
                        let start = prefix + chunk_index * per;
                        let mut counts = [0u64; 256];
                        let mut first = [u32::MAX; 256];
                        for (offset, (&value, output)) in values.iter().zip(outputs).enumerate() {
                            let value_index = value as usize;
                            counts[value_index] += 1;
                            let entry = table[value_index];
                            if entry == u16::MAX {
                                first[value_index] =
                                    first[value_index].min((start + offset) as u32);
                                *output = 0;
                            } else {
                                *output = entry as u8;
                            }
                        }
                        (counts, first)
                    })
                })
                .collect();
            handles
                .into_iter()
                .map(|handle| handle.join().expect("byte-factorization worker panicked"))
                .collect::<Vec<_>>()
        });
        let mut late_first = [u32::MAX; 256];
        for (counts, first) in parts {
            for value in 0..256 {
                raw_counts[value] += counts[value];
                late_first[value] = late_first[value].min(first[value]);
            }
        }
        let mut late: Vec<(u32, usize)> = late_first
            .iter()
            .enumerate()
            .filter_map(|(value, &row)| (row != u32::MAX).then_some((row, value)))
            .collect();
        late.sort_unstable();
        for (row, value) in &late {
            if codebook.len >= capacity {
                return None;
            }
            table[*value] = codebook.len as u16;
            codebook.first_indices[codebook.len] = *row;
            codebook.len += 1;
        }
        if !late.is_empty() {
            let per = data.len().div_ceil(threads);
            std::thread::scope(|scope| {
                for (values, outputs) in data.chunks(per).zip(codes.chunks_mut(per)) {
                    let table = &table;
                    scope.spawn(move || {
                        for (&value, output) in values.iter().zip(outputs) {
                            *output = table[value as usize] as u8;
                        }
                    });
                }
            });
        }
    }
    let mut counts = [0u64; 256];
    for (value, &count) in raw_counts.iter().enumerate() {
        let code = table[value];
        if code != u16::MAX {
            counts[code as usize] = count;
        }
    }
    Some(CompactFactorization { codebook, counts })
}

const UNICODE_CODEPOINT_DOMAIN: usize = 0x11_0000;

struct UnicodeFactorPart {
    counts: [u64; 256],
    late: Vec<(u32, u32)>,
}

#[inline(always)]
fn decode_codepoint(value: u32, swap_endian: bool) -> u32 {
    if swap_endian {
        value.swap_bytes()
    } else {
        value
    }
}

/// Factor NumPy-style one-codepoint Unicode records through their bounded
/// scalar domain instead of hashing four-byte records. `swap_endian` supports
/// non-native NumPy dtypes without copying the source column.
pub fn factorize_unicode1_u8_counts_into(
    values: &[u32],
    swap_endian: bool,
    codes: &mut [u8],
    unique_indices: &mut [u32],
    counts: &mut [u64],
) -> Option<usize> {
    if values.len() > u32::MAX as usize
        || codes.len() < values.len()
        || unique_indices.len() > 256
        || counts.len() < unique_indices.len()
    {
        return None;
    }
    if values.is_empty() {
        return Some(0);
    }
    let capacity = unique_indices.len();
    let mut table = vec![u16::MAX; UNICODE_CODEPOINT_DOMAIN];
    let mut unique_count = 0usize;
    let mut result_counts = [0u64; 256];
    let threads = factorize_threads(values.len());
    const PROBE_ROWS: usize = 4096;
    let prefix = if threads > 1 {
        values.len().min(PROBE_ROWS)
    } else {
        values.len()
    };
    for (row, &raw) in values[..prefix].iter().enumerate() {
        let value = decode_codepoint(raw, swap_endian) as usize;
        let entry = table.get_mut(value)?;
        if *entry == u16::MAX {
            if unique_count >= capacity {
                return None;
            }
            *entry = unique_count as u16;
            unique_indices[unique_count] = row as u32;
            unique_count += 1;
        }
        let code = *entry as u8;
        codes[row] = code;
        result_counts[code as usize] += 1;
    }
    if prefix == values.len() {
        counts[..unique_count].copy_from_slice(&result_counts[..unique_count]);
        return Some(unique_count);
    }

    let remaining = values.len() - prefix;
    let per = remaining.div_ceil(threads);
    let parts = std::thread::scope(|scope| -> Option<Vec<UnicodeFactorPart>> {
        let handles: Vec<_> = values[prefix..]
            .chunks(per)
            .zip(codes[prefix..].chunks_mut(per))
            .enumerate()
            .map(|(chunk_index, (value_chunk, code_chunk))| {
                let table = &table;
                scope.spawn(move || -> Option<UnicodeFactorPart> {
                    let start = prefix + chunk_index * per;
                    let mut local_counts = [0u64; 256];
                    let mut late: HashMap<u32, u32> = HashMap::new();
                    for (offset, (&raw, output)) in value_chunk.iter().zip(code_chunk).enumerate() {
                        let value = decode_codepoint(raw, swap_endian);
                        let entry = *table.get(value as usize)?;
                        if entry == u16::MAX {
                            late.entry(value).or_insert((start + offset) as u32);
                            *output = 0;
                        } else {
                            let code = entry as u8;
                            *output = code;
                            local_counts[code as usize] += 1;
                        }
                    }
                    let mut late: Vec<(u32, u32)> =
                        late.into_iter().map(|(value, row)| (row, value)).collect();
                    late.sort_unstable();
                    Some(UnicodeFactorPart {
                        counts: local_counts,
                        late,
                    })
                })
            })
            .collect();
        let mut parts = Vec::with_capacity(handles.len());
        for handle in handles {
            parts.push(
                handle
                    .join()
                    .expect("unicode-factorization worker panicked")?,
            );
        }
        Some(parts)
    })?;

    let prefix_unique_count = unique_count;
    for part in &parts {
        for &(row, value) in &part.late {
            let entry = &mut table[value as usize];
            if *entry != u16::MAX {
                continue;
            }
            if unique_count >= capacity {
                return None;
            }
            *entry = unique_count as u16;
            unique_indices[unique_count] = row;
            unique_count += 1;
        }
    }
    if unique_count == prefix_unique_count {
        for part in parts {
            for (total, value) in result_counts.iter_mut().zip(part.counts) {
                *total += value;
            }
        }
    } else {
        result_counts.fill(0);
        let per = values.len().div_ceil(threads);
        let parts = std::thread::scope(|scope| {
            let handles: Vec<_> = values
                .chunks(per)
                .zip(codes.chunks_mut(per))
                .map(|(value_chunk, code_chunk)| {
                    let table = &table;
                    scope.spawn(move || {
                        let mut local_counts = [0u64; 256];
                        for (&raw, output) in value_chunk.iter().zip(code_chunk) {
                            let value = decode_codepoint(raw, swap_endian) as usize;
                            let code = table[value] as u8;
                            *output = code;
                            local_counts[code as usize] += 1;
                        }
                        local_counts
                    })
                })
                .collect();
            handles
                .into_iter()
                .map(|handle| {
                    handle
                        .join()
                        .expect("unicode-factorization retry worker panicked")
                })
                .collect::<Vec<_>>()
        });
        for part in parts {
            for (total, value) in result_counts.iter_mut().zip(part) {
                *total += value;
            }
        }
    }
    counts[..unique_count].copy_from_slice(&result_counts[..unique_count]);
    Some(unique_count)
}

fn factorize_fixed_u8_impl(
    data: &[u8],
    width: usize,
    codes: &mut [u8],
    capacity: usize,
) -> Option<CompactFactorization> {
    if data.len().checked_rem(width) != Some(0) || capacity > 256 {
        return None;
    }
    let n = data.len() / width;
    if codes.len() < n || n > u32::MAX as usize {
        return None;
    }

    let threads = factorize_threads(n);
    // Single-byte records have a perfect direct codebook. This covers bool
    // and byte-valued labels without hashing or collision checks.
    if width == 1 {
        if threads > 1 {
            return factorize_byte_values_parallel(data, codes, capacity, threads);
        }
        let mut table = [u16::MAX; 256];
        let mut codebook = CompactCodebook::new();
        let mut counts = [0u64; 256];
        for (row_index, &value) in data.iter().enumerate() {
            let entry = &mut table[value as usize];
            if *entry == u16::MAX {
                if codebook.len >= capacity {
                    return None;
                }
                *entry = codebook.len as u16;
                codebook.first_indices[codebook.len] = u32::try_from(row_index).ok()?;
                codebook.len += 1;
            }
            let code = *entry as u8;
            codes[row_index] = code;
            counts[code as usize] += 1;
        }
        return Some(CompactFactorization { codebook, counts });
    }

    // The fixed 512-slot codebook is bounded by the u8 palette contract and
    // stays in L1. Full-record equality resolves every hash collision.
    if threads > 1 {
        factorize_fixed_u8_parallel(data, width, codes, capacity, threads)
    } else {
        factorize_fixed_u8_serial(data, width, codes, capacity)
    }
}

pub fn factorize_fixed_u8_into(
    data: &[u8],
    width: usize,
    codes: &mut [u8],
    unique_indices: &mut [u32],
) -> Option<usize> {
    let factorized = factorize_fixed_u8_impl(data, width, codes, unique_indices.len())?;
    let count = factorized.codebook.len;
    unique_indices[..count].copy_from_slice(&factorized.codebook.first_indices[..count]);
    Some(count)
}

/// Compact fixed-record factorization plus exact per-code counts from the same
/// pass. Counts follow first-seen code order and are written through `count`.
pub fn factorize_fixed_u8_counts_into(
    data: &[u8],
    width: usize,
    codes: &mut [u8],
    unique_indices: &mut [u32],
    counts: &mut [u64],
) -> Option<usize> {
    if counts.len() < unique_indices.len() {
        return None;
    }
    let factorized = factorize_fixed_u8_impl(data, width, codes, unique_indices.len())?;
    let count = factorized.codebook.len;
    unique_indices[..count].copy_from_slice(&factorized.codebook.first_indices[..count]);
    counts[..count].copy_from_slice(&factorized.counts[..count]);
    Some(count)
}

/// Apply a compact codebook permutation in place.
pub fn remap_u8_inplace(values: &mut [u8], mapping: &[u8]) -> bool {
    for value in values {
        let Some(&mapped) = mapping.get(usize::from(*value)) else {
            return false;
        };
        *value = mapped;
    }
    true
}

/// One-pass statistics for a chunk of a column (§22).
///
/// Non-finite values (NaN and ±∞) count as nulls: neither is plottable, both
/// corrupt GPU primitives if they reach a vertex buffer (§19), and ∞ would
/// poison min/max/sum for autorange. Treating them uniformly as invalid is what
/// lets autorange, `null_count`, and the ship-time drop all agree. (Arrow
/// validity bitmaps arrive later; non-finite-as-null is the Phase-0 contract.)
#[repr(C)]
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
    zone_maps_impl(data, chunk_size, zone_map_threads(data.len(), chunk_size))
}

/// Zone-map chunks are fully independent and produce no merge traffic, so
/// they amortize fan-out much earlier than general row-scan kernels. Bound the
/// workers by actual chunks: spawning many threads for two chunks only adds
/// scheduler noise. CodSpeed's instruction simulator sums work across threads
/// rather than measuring wall time, so keep its gate on the representative
/// serial instruction path and cover fan-out with wall-clock benchmarks.
fn zone_map_threads(n: usize, chunk_size: usize) -> usize {
    static CODSPEED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    let codspeed = *CODSPEED.get_or_init(|| std::env::var_os("CODSPEED_ENV").is_some());
    let cores = std::thread::available_parallelism().map_or(1, |p| p.get());
    zone_map_threads_for(n, chunk_size, cores, codspeed)
}

fn zone_map_threads_for(n: usize, chunk_size: usize, cores: usize, codspeed: bool) -> usize {
    let n_chunks = n.div_ceil(chunk_size);
    // Require two complete chunks before paying spawn cost. Express this as
    // division rather than `2 * chunk_size` so hostile ABI values cannot
    // overflow usize before the guarded FFI call rejects/handles them.
    if n / chunk_size < 2 || codspeed {
        return 1;
    }
    cores.min(MAX_ROW_THREADS).min(n_chunks).max(1)
}

fn zone_map_one(chunk: &[f64]) -> ZoneMap {
    let mut zm = ZoneMap::empty();
    for &v in chunk {
        zone_map_update(&mut zm, v);
    }
    zm
}

#[inline(always)]
fn zone_map_update(zm: &mut ZoneMap, value: f64) {
    if !value.is_finite() {
        zm.null_count += 1;
    } else {
        zm.count += 1;
        zm.min = zm.min.min(value);
        zm.max = zm.max.max(value);
        if value > 0.0 {
            zm.positive_min = zm.positive_min.min(value);
            zm.positive_max = zm.positive_max.max(value);
        }
        zm.sum += value;
        zm.sum_sq += value * value;
    }
}

fn zone_map_pair_one(x: &[f64], y: &[f64]) -> (ZoneMap, ZoneMap) {
    debug_assert_eq!(x.len(), y.len());
    let mut x_map = ZoneMap::empty();
    let mut y_map = ZoneMap::empty();
    for (&x_value, &y_value) in x.iter().zip(y) {
        zone_map_update(&mut x_map, x_value);
        zone_map_update(&mut y_map, y_value);
    }
    (x_map, y_map)
}

/// Compute two equal-length columns' independent zone maps in one scoped
/// parallel call. Each column keeps its original row order within every chunk,
/// so all floating reductions are bit-identical to separate [`zone_maps`]
/// calls.
pub fn zone_maps_pair(
    x: &[f64],
    y: &[f64],
    chunk_size: usize,
) -> Option<(Vec<ZoneMap>, Vec<ZoneMap>)> {
    if x.len() != y.len() || chunk_size == 0 {
        return None;
    }
    let n_chunks = x.len().div_ceil(chunk_size);
    let threads = zone_map_threads(x.len(), chunk_size);
    if threads <= 1 || n_chunks < 2 {
        let (x_maps, y_maps): (Vec<_>, Vec<_>) = x
            .chunks(chunk_size)
            .zip(y.chunks(chunk_size))
            .map(|(x_chunk, y_chunk)| zone_map_pair_one(x_chunk, y_chunk))
            .unzip();
        return Some((x_maps, y_maps));
    }
    let per = n_chunks.div_ceil(threads);
    let parts = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..threads)
            .map(|thread| {
                let lo = (thread * per * chunk_size).min(x.len());
                let hi = ((thread + 1) * per * chunk_size).min(x.len());
                let x_segment = &x[lo..hi];
                let y_segment = &y[lo..hi];
                scope.spawn(move || {
                    x_segment
                        .chunks(chunk_size)
                        .zip(y_segment.chunks(chunk_size))
                        .map(|(x_chunk, y_chunk)| zone_map_pair_one(x_chunk, y_chunk))
                        .collect::<Vec<_>>()
                })
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|handle| handle.join().expect("zone-map-pair worker panicked"))
            .collect::<Vec<_>>()
    });
    Some(parts.into_iter().unzip())
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

/// Compute lower/upper bounds for a stack of row-major series.
///
/// `baseline` is an engine-level layout mode: 0 = zero, 1 = symmetric,
/// 2 = unweighted wiggle, 3 = weighted wiggle.  The two caller-owned output
/// buffers have the same `(rows, cols)` row-major layout as `values`.
/// Keeping this O(rows*cols) transform native avoids allocating a Python
/// cumulative stack before the screen-bounded area marks are built.
pub fn stacked_bounds_into(
    values: &[f64],
    rows: usize,
    cols: usize,
    baseline: u32,
    lower: &mut [f64],
    upper: &mut [f64],
) -> bool {
    let Some(len) = rows.checked_mul(cols) else {
        return false;
    };
    if rows == 0
        || cols == 0
        || baseline > 3
        || values.len() != len
        || lower.len() != len
        || upper.len() != len
    {
        return false;
    }

    let mut weighted_center = 0.0;
    for col in 0..cols {
        let mut total = 0.0;
        for row in 0..rows {
            total += values[row * cols + col];
        }
        let first = match baseline {
            0 => 0.0,
            1 => -0.5 * total,
            2 => {
                let m = rows as f64;
                let weighted = (0..rows)
                    .map(|row| values[row * cols + col] * (m - 0.5 - row as f64))
                    .sum::<f64>();
                -weighted / m
            }
            3 => {
                let inv_total = if total > 0.0 { 1.0 / total } else { 0.0 };
                let mut cumulative = 0.0;
                let mut center_step = 0.0;
                for row in 0..rows {
                    let value = values[row * cols + col];
                    cumulative += value;
                    let below_size = total - cumulative + 0.5 * value;
                    let move_up = if col == 0 {
                        0.5
                    } else {
                        below_size * inv_total
                    };
                    let previous = if col == 0 {
                        0.0
                    } else {
                        values[row * cols + col - 1]
                    };
                    center_step += (move_up - 0.5) * (value - previous);
                }
                weighted_center += center_step;
                weighted_center - 0.5 * total
            }
            _ => unreachable!(),
        };

        let mut cursor = first;
        for row in 0..rows {
            let index = row * cols + col;
            lower[index] = cursor;
            cursor += values[index];
            upper[index] = cursor;
        }
    }
    true
}

fn histogram_edge_bin(value: f64, edges: &[f64]) -> Option<usize> {
    if !value.is_finite() || value < edges[0] || value > edges[edges.len() - 1] {
        return None;
    }
    if value == edges[edges.len() - 1] {
        return Some(edges.len() - 2);
    }
    let upper = edges.partition_point(|edge| *edge <= value);
    upper
        .checked_sub(1)
        .filter(|index| *index + 1 < edges.len())
}

/// Weighted 2-D histogram over arbitrary monotonically increasing edges.
///
/// Output is x-major `(nx, ny)`, matching common statistical APIs. Non-finite
/// coordinates and weights are skipped. The uniform-grid hot path continues
/// to use `bin_2d`; this kernel covers the irregular-bin compatibility case
/// without moving an O(points) scan back into Python.
pub fn histogram2d_into(
    x: &[f64],
    y: &[f64],
    weights: Option<&[f64]>,
    x_edges: &[f64],
    y_edges: &[f64],
    out: &mut [f64],
) -> bool {
    if x.len() != y.len()
        || weights.is_some_and(|values| values.len() != x.len())
        || x_edges.len() < 2
        || y_edges.len() < 2
        || !x_edges.windows(2).all(|pair| pair[1] > pair[0])
        || !y_edges.windows(2).all(|pair| pair[1] > pair[0])
        || !x_edges.iter().all(|value| value.is_finite())
        || !y_edges.iter().all(|value| value.is_finite())
    {
        return false;
    }
    let nx = x_edges.len() - 1;
    let ny = y_edges.len() - 1;
    if out.len() != nx.saturating_mul(ny) {
        return false;
    }
    if let Some(values) = weights {
        // Weighted accumulation stays serial: f64 addition is order-dependent,
        // so a per-thread merge would make the sums vary with core count
        // (§21 determinism).
        out.fill(0.0);
        for index in 0..x.len() {
            let Some(x_bin) = histogram_edge_bin(x[index], x_edges) else {
                continue;
            };
            let Some(y_bin) = histogram_edge_bin(y[index], y_edges) else {
                continue;
            };
            let weight = values[index];
            if weight.is_finite() {
                out[x_bin * ny + y_bin] += weight;
            }
        }
    } else {
        // Unit weights are integer counts: per-worker u64 grids with an
        // integer-sum merge are bit-identical to the serial pass for any
        // thread count. Same grid-aware fan-out cap as `bin_2d`.
        histogram2d_count(
            x,
            y,
            x_edges,
            y_edges,
            bin_2d_threads(x.len(), nx * ny),
            out,
        );
    }
    true
}

fn histogram2d_count_scan(
    x: &[f64],
    y: &[f64],
    x_edges: &[f64],
    y_edges: &[f64],
    bins: &mut [u64],
) {
    let ny = y_edges.len() - 1;
    for index in 0..x.len() {
        let Some(x_bin) = histogram_edge_bin(x[index], x_edges) else {
            continue;
        };
        let Some(y_bin) = histogram_edge_bin(y[index], y_edges) else {
            continue;
        };
        bins[x_bin * ny + y_bin] += 1;
    }
}

fn histogram2d_count(
    x: &[f64],
    y: &[f64],
    x_edges: &[f64],
    y_edges: &[f64],
    threads: usize,
    out: &mut [f64],
) {
    let n = x.len();
    if threads <= 1 || n < threads {
        let mut bins = vec![0u64; out.len()];
        histogram2d_count_scan(x, y, x_edges, y_edges, &mut bins);
        for (cell, count) in out.iter_mut().zip(bins) {
            *cell = count as f64;
        }
        return;
    }
    let chunk = n.div_ceil(threads);
    let parts: Vec<Vec<u64>> = std::thread::scope(|scope| {
        let handles: Vec<_> = x
            .chunks(chunk)
            .zip(y.chunks(chunk))
            .map(|(xs, ys)| {
                let n_bins = out.len();
                scope.spawn(move || {
                    let mut bins = vec![0u64; n_bins];
                    histogram2d_count_scan(xs, ys, x_edges, y_edges, &mut bins);
                    bins
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().expect("histogram2d worker panicked"))
            .collect()
    });
    for (index, cell) in out.iter_mut().enumerate() {
        *cell = parts.iter().map(|bins| bins[index]).sum::<u64>() as f64;
    }
}

/// Expand a rectilinear or curvilinear quadrilateral grid into independent
/// filled triangles.
///
/// `values` is a row-major `(cell_rows, cell_cols)` scalar grid. Coordinates
/// are either rectilinear edge vectors (`x.len() == cell_cols + 1`,
/// `y.len() == cell_rows + 1`) or two flattened row-major vertex grids of
/// shape `(cell_rows + 1, cell_cols + 1)`. Every finite cell emits two
/// triangles and duplicates its scalar once, directly into caller-owned
/// columns ready for the instanced mesh renderer. Cells with a non-finite
/// value or vertex are omitted.
#[allow(clippy::too_many_arguments)]
pub fn quad_mesh_triangles_into(
    x: &[f64],
    y: &[f64],
    values: &[f64],
    cell_rows: usize,
    cell_cols: usize,
    layout: u32,
    out_x0: &mut [f64],
    out_y0: &mut [f64],
    out_x1: &mut [f64],
    out_y1: &mut [f64],
    out_x2: &mut [f64],
    out_y2: &mut [f64],
    out_values: &mut [f64],
) -> Option<usize> {
    let cell_count = cell_rows.checked_mul(cell_cols)?;
    let vertex_rows = cell_rows.checked_add(1)?;
    let vertex_cols = cell_cols.checked_add(1)?;
    let vertex_count = vertex_rows.checked_mul(vertex_cols)?;
    let capacity = cell_count.checked_mul(2)?;
    let valid_layout = match layout {
        0 => x.len() == vertex_cols && y.len() == vertex_rows,
        1 => x.len() == vertex_count && y.len() == vertex_count,
        2 => x.len() == cell_cols && y.len() == cell_rows,
        3 => x.len() == cell_count && y.len() == cell_count,
        _ => false,
    };
    if cell_rows == 0
        || cell_cols == 0
        || values.len() != cell_count
        || !valid_layout
        || out_x0.len() < capacity
        || out_y0.len() < capacity
        || out_x1.len() < capacity
        || out_y1.len() < capacity
        || out_x2.len() < capacity
        || out_y2.len() < capacity
        || out_values.len() < capacity
    {
        return None;
    }

    let center_edge = |values: &[f64], edge: usize| -> f64 {
        if values.len() == 1 {
            return values[0] + edge as f64 - 0.5;
        }
        if edge == 0 {
            1.5 * values[0] - 0.5 * values[1]
        } else if edge == values.len() {
            1.5 * values[values.len() - 1] - 0.5 * values[values.len() - 2]
        } else {
            0.5 * (values[edge - 1] + values[edge])
        }
    };
    let edge_weights = |edge: usize, size: usize| -> ((usize, f64), (usize, f64)) {
        if size == 1 {
            ((0, 1.0), (0, 0.0))
        } else if edge == 0 {
            ((0, 1.5), (1, -0.5))
        } else if edge == size {
            ((size - 1, 1.5), (size - 2, -0.5))
        } else {
            ((edge - 1, 0.5), (edge, 0.5))
        }
    };
    let centered_vertex = |values: &[f64], row: usize, col: usize| -> f64 {
        let (rw0, rw1) = edge_weights(row, cell_rows);
        let (cw0, cw1) = edge_weights(col, cell_cols);
        let sample = |r: usize, c: usize| values[r * cell_cols + c];
        rw0.1 * (cw0.1 * sample(rw0.0, cw0.0) + cw1.1 * sample(rw0.0, cw1.0))
            + rw1.1 * (cw0.1 * sample(rw1.0, cw0.0) + cw1.1 * sample(rw1.0, cw1.0))
    };
    let single_row_vertex = |row: usize, col: usize| -> (f64, f64) {
        if cell_cols == 1 {
            return (x[0] + col as f64 - 0.5, y[0] + row as f64 - 0.5);
        }
        let center = (center_edge(x, col), center_edge(y, col));
        let (a, b) = if col == 0 {
            (0, 1)
        } else if col == cell_cols {
            (cell_cols - 2, cell_cols - 1)
        } else {
            (col - 1, col)
        };
        let (dx, dy) = (x[b] - x[a], y[b] - y[a]);
        let length = (dx * dx + dy * dy).sqrt();
        let normal = if length > 0.0 {
            (-dy / length, dx / length)
        } else {
            (0.0, 1.0)
        };
        let half_width = if length > 0.0 { length * 0.5 } else { 0.5 };
        let offset = if row == 0 { -half_width } else { half_width };
        (center.0 + normal.0 * offset, center.1 + normal.1 * offset)
    };
    let single_col_vertex = |row: usize, col: usize| -> (f64, f64) {
        let center = (center_edge(x, row), center_edge(y, row));
        let (a, b) = if row == 0 {
            (0, 1)
        } else if row == cell_rows {
            (cell_rows - 2, cell_rows - 1)
        } else {
            (row - 1, row)
        };
        let (dx, dy) = (x[b] - x[a], y[b] - y[a]);
        let length = (dx * dx + dy * dy).sqrt();
        let normal = if length > 0.0 {
            (-dy / length, dx / length)
        } else {
            (1.0, 0.0)
        };
        let half_width = if length > 0.0 { length * 0.5 } else { 0.5 };
        let offset = if col == 0 { -half_width } else { half_width };
        (center.0 + normal.0 * offset, center.1 + normal.1 * offset)
    };
    let vertex = |row: usize, col: usize| -> (f64, f64) {
        match layout {
            0 => (x[col], y[row]),
            1 => {
                let index = row * vertex_cols + col;
                (x[index], y[index])
            }
            2 => (center_edge(x, col), center_edge(y, row)),
            3 if cell_rows == 1 => single_row_vertex(row, col),
            3 if cell_cols == 1 => single_col_vertex(row, col),
            3 => (centered_vertex(x, row, col), centered_vertex(y, row, col)),
            _ => unreachable!(),
        }
    };
    let mut written = 0;
    for row in 0..cell_rows {
        for col in 0..cell_cols {
            let value = values[row * cell_cols + col];
            let a = vertex(row, col);
            let b = vertex(row, col + 1);
            let c = vertex(row + 1, col + 1);
            let d = vertex(row + 1, col);
            if !value.is_finite()
                || ![a.0, a.1, b.0, b.1, c.0, c.1, d.0, d.1]
                    .iter()
                    .all(|coordinate| coordinate.is_finite())
            {
                continue;
            }
            for (p0, p1, p2) in [(a, b, c), (a, c, d)] {
                out_x0[written] = p0.0;
                out_y0[written] = p0.1;
                out_x1[written] = p1.0;
                out_y1[written] = p1.1;
                out_x2[written] = p2.0;
                out_y2[written] = p2.1;
                out_values[written] = value;
                written += 1;
            }
        }
    }
    Some(written)
}

/// Tessellate weighted circular/annular sectors into independent triangles.
/// Each output scalar is the source sector index, allowing an adapter to
/// group faces without rebuilding geometry in Python. With empty outputs the
/// function returns the required triangle count; otherwise all seven buffers
/// must have at least that capacity.
#[allow(clippy::too_many_arguments)]
pub fn sector_triangles_into(
    values: &[f64],
    explode: &[f64],
    center_x: f64,
    center_y: f64,
    radius: f64,
    inner_radius: f64,
    start_degrees: f64,
    counterclockwise: bool,
    normalize: bool,
    out_x0: &mut [f64],
    out_y0: &mut [f64],
    out_x1: &mut [f64],
    out_y1: &mut [f64],
    out_x2: &mut [f64],
    out_y2: &mut [f64],
    out_sector: &mut [f64],
) -> Option<usize> {
    if values.is_empty()
        || (!explode.is_empty() && explode.len() != values.len())
        || !values
            .iter()
            .all(|value| value.is_finite() && *value >= 0.0)
        || !explode
            .iter()
            .all(|value| value.is_finite() && *value >= 0.0)
        || !center_x.is_finite()
        || !center_y.is_finite()
        || !radius.is_finite()
        || radius <= 0.0
        || !inner_radius.is_finite()
        || inner_radius < 0.0
        || inner_radius >= radius
        || !start_degrees.is_finite()
    {
        return None;
    }
    let total = values.iter().sum::<f64>();
    if total <= 0.0 || (!normalize && total > 1.0 + 1e-12) {
        return None;
    }
    let denominator = if normalize { total } else { 1.0 };
    let direction = if counterclockwise { 1.0 } else { -1.0 };
    let mut required = 0usize;
    for &value in values {
        if value == 0.0 {
            continue;
        }
        let sweep = std::f64::consts::TAU * value / denominator;
        let steps = (sweep.abs() / (std::f64::consts::PI / 30.0)).ceil() as usize;
        let per_step = if inner_radius > 0.0 { 2 } else { 1 };
        required = required.checked_add(steps.max(1).checked_mul(per_step)?)?;
    }
    let query = out_x0.is_empty()
        && out_y0.is_empty()
        && out_x1.is_empty()
        && out_y1.is_empty()
        && out_x2.is_empty()
        && out_y2.is_empty()
        && out_sector.is_empty();
    if !query
        && [
            out_x0.len(),
            out_y0.len(),
            out_x1.len(),
            out_y1.len(),
            out_x2.len(),
            out_y2.len(),
            out_sector.len(),
        ]
        .iter()
        .any(|length| *length < required)
    {
        return None;
    }
    if query {
        return Some(required);
    }

    let mut angle = start_degrees.to_radians();
    let mut written = 0;
    for (sector, &value) in values.iter().enumerate() {
        let sweep = direction * std::f64::consts::TAU * value / denominator;
        if value == 0.0 {
            angle += sweep;
            continue;
        }
        let steps = (sweep.abs() / (std::f64::consts::PI / 30.0)).ceil() as usize;
        let steps = steps.max(1);
        let mid = angle + sweep * 0.5;
        let offset = explode.get(sector).copied().unwrap_or(0.0) * radius;
        let cx = center_x + offset * mid.cos();
        let cy = center_y + offset * mid.sin();
        for step in 0..steps {
            let a0 = angle + sweep * step as f64 / steps as f64;
            let a1 = angle + sweep * (step + 1) as f64 / steps as f64;
            let outer0 = (cx + radius * a0.cos(), cy + radius * a0.sin());
            let outer1 = (cx + radius * a1.cos(), cy + radius * a1.sin());
            let triangles = if inner_radius > 0.0 {
                let inner0 = (cx + inner_radius * a0.cos(), cy + inner_radius * a0.sin());
                let inner1 = (cx + inner_radius * a1.cos(), cy + inner_radius * a1.sin());
                [(inner0, outer0, outer1), (inner0, outer1, inner1)]
            } else {
                [((cx, cy), outer0, outer1), ((cx, cy), (cx, cy), (cx, cy))]
            };
            let count = if inner_radius > 0.0 { 2 } else { 1 };
            for &(p0, p1, p2) in &triangles[..count] {
                out_x0[written] = p0.0;
                out_y0[written] = p0.1;
                out_x1[written] = p1.0;
                out_y1[written] = p1.1;
                out_x2[written] = p2.0;
                out_y2[written] = p2.1;
                out_sector[written] = sector as f64;
                written += 1;
            }
        }
        angle += sweep;
    }
    Some(written)
}

fn fft_in_place(real: &mut [f64], imag: &mut [f64]) {
    let n = real.len();
    debug_assert_eq!(n, imag.len());
    if n <= 1 {
        return;
    }
    if !n.is_power_of_two() {
        // Bluestein's chirp-z transform reduces an arbitrary-size DFT to one
        // power-of-two convolution, preserving O(n log n) for spectral APIs.
        let Some(m) = n.checked_mul(2).and_then(|value| value.checked_sub(1)) else {
            return;
        };
        let m = m.next_power_of_two();
        let mut ar = vec![0.0; m];
        let mut ai = vec![0.0; m];
        let mut br = vec![0.0; m];
        let mut bi = vec![0.0; m];
        for index in 0..n {
            let angle = std::f64::consts::PI * (index as f64 * index as f64) / n as f64;
            let (sin, cos) = angle.sin_cos();
            ar[index] = real[index] * cos + imag[index] * sin;
            ai[index] = imag[index] * cos - real[index] * sin;
            br[index] = cos;
            bi[index] = sin;
            if index > 0 {
                br[m - index] = cos;
                bi[m - index] = sin;
            }
        }
        fft_in_place(&mut ar, &mut ai);
        fft_in_place(&mut br, &mut bi);
        for index in 0..m {
            let product_real = ar[index] * br[index] - ai[index] * bi[index];
            let product_imag = ar[index] * bi[index] + ai[index] * br[index];
            ar[index] = product_real;
            ai[index] = -product_imag;
        }
        fft_in_place(&mut ar, &mut ai);
        for index in 0..n {
            let conv_real = ar[index] / m as f64;
            let conv_imag = -ai[index] / m as f64;
            let angle = std::f64::consts::PI * (index as f64 * index as f64) / n as f64;
            let (sin, cos) = angle.sin_cos();
            real[index] = conv_real * cos + conv_imag * sin;
            imag[index] = conv_imag * cos - conv_real * sin;
        }
        return;
    }
    let bits = n.trailing_zeros();
    for index in 0..n {
        let reversed = index.reverse_bits() >> (usize::BITS - bits);
        if reversed > index {
            real.swap(index, reversed);
            imag.swap(index, reversed);
        }
    }
    let mut size = 2;
    while size <= n {
        let half = size / 2;
        let angle = -std::f64::consts::TAU / size as f64;
        let (step_imag, step_real) = angle.sin_cos();
        for start in (0..n).step_by(size) {
            let (mut twiddle_real, mut twiddle_imag) = (1.0, 0.0);
            for offset in 0..half {
                let even = start + offset;
                let odd = even + half;
                let odd_real = real[odd] * twiddle_real - imag[odd] * twiddle_imag;
                let odd_imag = real[odd] * twiddle_imag + imag[odd] * twiddle_real;
                let even_real = real[even];
                let even_imag = imag[even];
                real[even] = even_real + odd_real;
                imag[even] = even_imag + odd_imag;
                real[odd] = even_real - odd_real;
                imag[odd] = even_imag - odd_imag;
                let next_real = twiddle_real * step_real - twiddle_imag * step_imag;
                twiddle_imag = twiddle_real * step_imag + twiddle_imag * step_real;
                twiddle_real = next_real;
            }
        }
        size *= 2;
    }
}

fn spectral_window(nfft: usize) -> Vec<f64> {
    if nfft <= 1 {
        return vec![1.0; nfft];
    }
    (0..nfft)
        .map(|index| 0.5 - 0.5 * (std::f64::consts::TAU * index as f64 / (nfft - 1) as f64).cos())
        .collect()
}

fn windowed_fft(data: &[f64], start: usize, nfft: usize, window: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let available = data.len().saturating_sub(start).min(nfft);
    let mean = if available == 0 {
        0.0
    } else {
        data[start..start + available].iter().sum::<f64>() / available as f64
    };
    let mut real = vec![0.0; nfft];
    let mut imag = vec![0.0; nfft];
    for index in 0..available {
        real[index] = (data[start + index] - mean) * window[index];
    }
    fft_in_place(&mut real, &mut imag);
    (real, imag)
}

/// Windowed real FFT returning the nonnegative-frequency half spectrum.
pub fn rfft_into(
    data: &[f64],
    nfft: usize,
    sample_rate: f64,
    out_frequency: &mut [f64],
    out_real: &mut [f64],
    out_imag: &mut [f64],
) -> bool {
    let bins = nfft / 2 + 1;
    if data.is_empty()
        || nfft == 0
        || nfft > 65_536
        || !sample_rate.is_finite()
        || sample_rate <= 0.0
        || !data.iter().all(|value| value.is_finite())
        || out_frequency.len() != bins
        || out_real.len() != bins
        || out_imag.len() != bins
    {
        return false;
    }
    let window = spectral_window(nfft);
    let (real, imag) = windowed_fft(data, 0, nfft, &window);
    for index in 0..bins {
        out_frequency[index] = index as f64 * sample_rate / nfft as f64;
        out_real[index] = real[index];
        out_imag[index] = imag[index];
    }
    true
}

fn spectral_segment_count(len: usize, nfft: usize, noverlap: usize) -> Option<usize> {
    if nfft == 0 || noverlap >= nfft {
        return None;
    }
    if len <= nfft {
        Some(1)
    } else {
        Some(1 + (len - nfft) / (nfft - noverlap))
    }
}

/// Welch auto/cross spectral estimate. A missing `y` computes only `pxx`;
/// otherwise all auto and complex cross spectra are averaged natively.
#[allow(clippy::too_many_arguments)]
pub fn welch_spectra_into(
    x: &[f64],
    y: Option<&[f64]>,
    nfft: usize,
    noverlap: usize,
    sample_rate: f64,
    out_frequency: &mut [f64],
    out_pxx: &mut [f64],
    out_pyy: &mut [f64],
    out_pxy_real: &mut [f64],
    out_pxy_imag: &mut [f64],
) -> bool {
    let Some(segments) = spectral_segment_count(x.len(), nfft, noverlap) else {
        return false;
    };
    let bins = nfft / 2 + 1;
    if x.is_empty()
        || nfft > 65_536
        || !sample_rate.is_finite()
        || sample_rate <= 0.0
        || !x.iter().all(|value| value.is_finite())
        || y.is_some_and(|values| {
            values.len() != x.len() || !values.iter().all(|value| value.is_finite())
        })
        || [
            out_frequency.len(),
            out_pxx.len(),
            out_pyy.len(),
            out_pxy_real.len(),
            out_pxy_imag.len(),
        ]
        .iter()
        .any(|length| *length != bins)
    {
        return false;
    }
    out_pxx.fill(0.0);
    out_pyy.fill(0.0);
    out_pxy_real.fill(0.0);
    out_pxy_imag.fill(0.0);
    let window = spectral_window(nfft);
    let window_power = window.iter().map(|value| value * value).sum::<f64>();
    let stride = nfft - noverlap;
    for segment in 0..segments {
        let start = if x.len() <= nfft { 0 } else { segment * stride };
        let (xr, xi) = windowed_fft(x, start, nfft, &window);
        let y_fft = y.map(|values| windowed_fft(values, start, nfft, &window));
        for bin in 0..bins {
            out_pxx[bin] += xr[bin] * xr[bin] + xi[bin] * xi[bin];
            if let Some((ref yr, ref yi)) = y_fft {
                out_pyy[bin] += yr[bin] * yr[bin] + yi[bin] * yi[bin];
                out_pxy_real[bin] += xr[bin] * yr[bin] + xi[bin] * yi[bin];
                // Matplotlib/NumPy define Pxy as conj(X) * Y.  Reversing the
                // operands flips every phase while leaving magnitudes intact,
                // which makes the bug particularly easy to miss in PSD tests.
                out_pxy_imag[bin] += xr[bin] * yi[bin] - xi[bin] * yr[bin];
            }
        }
    }
    let scale = sample_rate * window_power * segments as f64;
    for bin in 0..bins {
        let one_sided = if bin > 0 && !(nfft.is_multiple_of(2) && bin == nfft / 2) {
            2.0
        } else {
            1.0
        };
        let factor = one_sided / scale;
        out_frequency[bin] = bin as f64 * sample_rate / nfft as f64;
        out_pxx[bin] *= factor;
        out_pyy[bin] *= factor;
        out_pxy_real[bin] *= factor;
        out_pxy_imag[bin] *= factor;
    }
    true
}

/// Spectrogram matrix in time-major `(segments, bins)` layout.
#[allow(clippy::too_many_arguments)]
pub fn spectrogram_into(
    data: &[f64],
    nfft: usize,
    noverlap: usize,
    sample_rate: f64,
    out_frequency: &mut [f64],
    out_time: &mut [f64],
    out_power: &mut [f64],
) -> bool {
    let Some(segments) = spectral_segment_count(data.len(), nfft, noverlap) else {
        return false;
    };
    let bins = nfft / 2 + 1;
    if data.is_empty()
        || nfft > 65_536
        || !sample_rate.is_finite()
        || sample_rate <= 0.0
        || !data.iter().all(|value| value.is_finite())
        || out_frequency.len() != bins
        || out_time.len() != segments
        || out_power.len() != segments.saturating_mul(bins)
    {
        return false;
    }
    let window = spectral_window(nfft);
    let window_power = window.iter().map(|value| value * value).sum::<f64>();
    let stride = nfft - noverlap;
    for (bin, frequency) in out_frequency.iter_mut().enumerate() {
        *frequency = bin as f64 * sample_rate / nfft as f64;
    }
    for segment in 0..segments {
        let start = if data.len() <= nfft {
            0
        } else {
            segment * stride
        };
        let (real, imag) = windowed_fft(data, start, nfft, &window);
        out_time[segment] = (start as f64 + nfft as f64 * 0.5) / sample_rate;
        for bin in 0..bins {
            let one_sided = if bin > 0 && !(nfft.is_multiple_of(2) && bin == nfft / 2) {
                2.0
            } else {
                1.0
            };
            out_power[segment * bins + bin] = (real[bin] * real[bin] + imag[bin] * imag[bin])
                * one_sided
                / (sample_rate * window_power);
        }
    }
    true
}

/// Direct lag correlation over `[-max_lag, max_lag]` with optional coefficient
/// normalization. This stays native because the O(n*lags) multiply-reduction
/// is the heavy part of `acorr`/`xcorr`.
pub fn correlation_into(
    x: &[f64],
    y: &[f64],
    max_lag: usize,
    normalize: bool,
    out_lag: &mut [f64],
    out_correlation: &mut [f64],
) -> bool {
    let Some(output_len) = max_lag
        .checked_mul(2)
        .and_then(|value| value.checked_add(1))
    else {
        return false;
    };
    if x.len() != y.len()
        || x.is_empty()
        || max_lag >= x.len()
        || !x.iter().chain(y).all(|value| value.is_finite())
        || out_lag.len() != output_len
        || out_correlation.len() != output_len
    {
        return false;
    }
    let denominator = if normalize {
        // xcorr/acorr use detrend_none by default.  Any requested detrending
        // is applied by the pyplot adapter before entering this hot loop.
        let xx = x.iter().map(|value| value * value).sum::<f64>();
        let yy = y.iter().map(|value| value * value).sum::<f64>();
        (xx * yy).sqrt()
    } else {
        1.0
    };
    for (output, lag) in (-(max_lag as isize)..=max_lag as isize).enumerate() {
        let mut sum = 0.0;
        if lag >= 0 {
            let shift = lag as usize;
            for index in 0..x.len() - shift {
                sum += x[index + shift] * y[index];
            }
        } else {
            let shift = (-lag) as usize;
            for index in 0..x.len() - shift {
                sum += x[index] * y[index + shift];
            }
        }
        out_lag[output] = lag as f64;
        out_correlation[output] = if denominator > 0.0 {
            sum / denominator
        } else {
            0.0
        };
    }
    true
}

/// Sort and aggregate a weighted empirical CDF into caller-owned columns.
///
/// Finite values with finite, non-negative weights participate. Equal values
/// are coalesced and cumulative mass is normalized to one. Sorting and the
/// O(n) aggregation stay native for large compatibility-layer distributions.
pub fn weighted_ecdf_into(
    values: &[f64],
    weights: &[f64],
    out_values: &mut [f64],
    out_cumulative: &mut [f64],
) -> Option<usize> {
    if values.len() != weights.len()
        || out_values.len() < values.len()
        || out_cumulative.len() < values.len()
    {
        return None;
    }
    let mut pairs: Vec<(f64, f64)> = values
        .iter()
        .copied()
        .zip(weights.iter().copied())
        .filter(|(value, weight)| value.is_finite() && weight.is_finite() && *weight >= 0.0)
        .collect();
    if pairs.is_empty() {
        return None;
    }
    pairs.sort_unstable_by(|left, right| left.0.total_cmp(&right.0));
    let total: f64 = pairs.iter().map(|pair| pair.1).sum();
    if !total.is_finite() || total <= 0.0 {
        return None;
    }
    let mut written = 0usize;
    let mut cumulative = 0.0;
    for (value, weight) in pairs {
        cumulative += weight;
        if written > 0 && out_values[written - 1] == value {
            out_cumulative[written - 1] = cumulative / total;
        } else {
            out_values[written] = value;
            out_cumulative[written] = cumulative / total;
            written += 1;
        }
    }
    Some(written)
}

/// Expand indexed triangles into renderer-ready coordinate columns and one
/// scalar per face. `value_mode` is 0 for a constant zero scalar, 1 for
/// face values, and 2 for the mean of three vertex values. Invalid indices,
/// non-finite vertices, and non-finite resolved scalars are compacted out.
#[allow(clippy::too_many_arguments)]
pub fn indexed_triangles_into(
    x: &[f64],
    y: &[f64],
    triangles: &[i64],
    values: &[f64],
    value_mode: u32,
    out_x0: &mut [f64],
    out_y0: &mut [f64],
    out_x1: &mut [f64],
    out_y1: &mut [f64],
    out_x2: &mut [f64],
    out_y2: &mut [f64],
    out_values: &mut [f64],
) -> Option<usize> {
    if x.len() != y.len() || !triangles.len().is_multiple_of(3) || value_mode > 2 {
        return None;
    }
    let count = triangles.len() / 3;
    if (value_mode == 1 && values.len() != count)
        || (value_mode == 2 && values.len() != x.len())
        || out_x0.len() < count
        || out_y0.len() < count
        || out_x1.len() < count
        || out_y1.len() < count
        || out_x2.len() < count
        || out_y2.len() < count
        || out_values.len() < count
    {
        return None;
    }
    let mut written = 0;
    for face in 0..count {
        let raw = &triangles[face * 3..face * 3 + 3];
        if raw
            .iter()
            .any(|index| *index < 0 || *index as usize >= x.len())
        {
            continue;
        }
        let index = [raw[0] as usize, raw[1] as usize, raw[2] as usize];
        let coordinates = [
            x[index[0]],
            y[index[0]],
            x[index[1]],
            y[index[1]],
            x[index[2]],
            y[index[2]],
        ];
        let scalar = match value_mode {
            0 => 0.0,
            1 => values[face],
            2 => (values[index[0]] + values[index[1]] + values[index[2]]) / 3.0,
            _ => unreachable!(),
        };
        if !coordinates.iter().all(|value| value.is_finite()) || !scalar.is_finite() {
            continue;
        }
        out_x0[written] = coordinates[0];
        out_y0[written] = coordinates[1];
        out_x1[written] = coordinates[2];
        out_y1[written] = coordinates[3];
        out_x2[written] = coordinates[4];
        out_y2[written] = coordinates[5];
        out_values[written] = scalar;
        written += 1;
    }
    Some(written)
}

/// Emit each topological triangle edge once as independent line segments.
#[allow(clippy::too_many_arguments)]
pub fn triangle_edges_into(
    x: &[f64],
    y: &[f64],
    triangles: &[i64],
    out_x0: &mut [f64],
    out_x1: &mut [f64],
    out_y0: &mut [f64],
    out_y1: &mut [f64],
) -> Option<usize> {
    if x.len() != y.len() || !triangles.len().is_multiple_of(3) {
        return None;
    }
    let capacity = triangles.len();
    if out_x0.len() < capacity
        || out_x1.len() < capacity
        || out_y0.len() < capacity
        || out_y1.len() < capacity
    {
        return None;
    }
    let mut seen = std::collections::HashSet::with_capacity(capacity);
    let mut written = 0;
    for face in triangles.chunks_exact(3) {
        if face
            .iter()
            .any(|index| *index < 0 || *index as usize >= x.len())
        {
            continue;
        }
        for pair in [(face[0], face[1]), (face[1], face[2]), (face[2], face[0])] {
            let key = if pair.0 < pair.1 {
                pair
            } else {
                (pair.1, pair.0)
            };
            if !seen.insert(key) {
                continue;
            }
            let a = key.0 as usize;
            let b = key.1 as usize;
            if ![x[a], y[a], x[b], y[b]]
                .iter()
                .all(|value| value.is_finite())
            {
                continue;
            }
            out_x0[written] = x[a];
            out_x1[written] = x[b];
            out_y0[written] = y[a];
            out_y1[written] = y[b];
            written += 1;
        }
    }
    Some(written)
}

fn orient2d(a: (f64, f64), b: (f64, f64), c: (f64, f64)) -> f64 {
    (b.0 - a.0) * (c.1 - a.1) - (b.1 - a.1) * (c.0 - a.0)
}

fn circumcircle_contains(
    a: (f64, f64),
    b: (f64, f64),
    c: (f64, f64),
    p: (f64, f64),
    epsilon: f64,
) -> bool {
    let ax = a.0 - p.0;
    let ay = a.1 - p.1;
    let bx = b.0 - p.0;
    let by = b.1 - p.1;
    let cx = c.0 - p.0;
    let cy = c.1 - p.1;
    let determinant = (ax * ax + ay * ay) * (bx * cy - cx * by)
        - (bx * bx + by * by) * (ax * cy - cx * ay)
        + (cx * cx + cy * cy) * (ax * by - bx * ay);
    let orientation = orient2d(a, b, c);
    (orientation > 0.0 && determinant > epsilon) || (orientation < 0.0 && determinant < -epsilon)
}

/// Dependency-free Bowyer-Watson Delaunay triangulation for unstructured 2-D
/// points. The algorithm is native because topology construction is the heavy
/// path; callers receive compact int64 indices and keep renderer geometry
/// expansion in the adjacent indexed-triangle kernel.
const MAX_QUADRATIC_TRIANGULATION_WORK: usize = 100_000_000;

pub fn delaunay_triangles(x: &[f64], y: &[f64]) -> Option<Vec<[i64; 3]>> {
    if x.len() != y.len()
        || x.len() < 3
        || x.len().checked_mul(x.len())? > MAX_QUADRATIC_TRIANGULATION_WORK
    {
        return None;
    }
    let mut seen = std::collections::HashSet::with_capacity(x.len());
    let mut points = Vec::with_capacity(x.len() + 3);
    let mut source_indices = Vec::with_capacity(x.len());
    for (source_index, (&xv, &yv)) in x.iter().zip(y).enumerate() {
        if !xv.is_finite() || !yv.is_finite() {
            return None;
        }
        if !seen.insert((xv.to_bits(), yv.to_bits())) {
            continue;
        }
        points.push((xv, yv));
        source_indices.push(source_index);
    }
    if points.len() < 3 {
        return None;
    }
    let min_x = points
        .iter()
        .map(|point| point.0)
        .fold(f64::INFINITY, f64::min);
    let max_x = points
        .iter()
        .map(|point| point.0)
        .fold(f64::NEG_INFINITY, f64::max);
    let min_y = points
        .iter()
        .map(|point| point.1)
        .fold(f64::INFINITY, f64::min);
    let max_y = points
        .iter()
        .map(|point| point.1)
        .fold(f64::NEG_INFINITY, f64::max);
    let span = (max_x - min_x).max(max_y - min_y);
    if span <= 0.0 || !span.is_finite() {
        return None;
    }
    let mid = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5);
    let super_start = points.len();
    points.push((mid.0 - 32.0 * span, mid.1 - span));
    points.push((mid.0, mid.1 + 32.0 * span));
    points.push((mid.0 + 32.0 * span, mid.1 - span));
    let mut triangles = vec![[super_start, super_start + 2, super_start + 1]];
    let epsilon = span.powi(4) * 1e-14;

    for point_index in 0..super_start {
        let point = points[point_index];
        let mut bad = vec![false; triangles.len()];
        let mut boundary: std::collections::HashMap<(usize, usize), (usize, usize, u8)> =
            std::collections::HashMap::new();
        for (index, triangle) in triangles.iter().enumerate() {
            if !circumcircle_contains(
                points[triangle[0]],
                points[triangle[1]],
                points[triangle[2]],
                point,
                epsilon,
            ) {
                continue;
            }
            bad[index] = true;
            for edge in [
                (triangle[0], triangle[1]),
                (triangle[1], triangle[2]),
                (triangle[2], triangle[0]),
            ] {
                let key = if edge.0 < edge.1 {
                    edge
                } else {
                    (edge.1, edge.0)
                };
                boundary
                    .entry(key)
                    .and_modify(|entry| entry.2 = entry.2.saturating_add(1))
                    .or_insert((edge.0, edge.1, 1));
            }
        }
        let mut kept = Vec::with_capacity(triangles.len() + boundary.len());
        for (triangle, is_bad) in triangles.into_iter().zip(bad) {
            if !is_bad {
                kept.push(triangle);
            }
        }
        for (_, (a, b, count)) in boundary {
            if count != 1 {
                continue;
            }
            let mut triangle = [a, b, point_index];
            if orient2d(points[a], points[b], point) < 0.0 {
                triangle.swap(0, 1);
            }
            if orient2d(points[triangle[0]], points[triangle[1]], point).abs() > epsilon.sqrt() {
                kept.push(triangle);
            }
        }
        triangles = kept;
    }
    let result = triangles
        .into_iter()
        .filter(|triangle| triangle.iter().all(|index| *index < super_start))
        .map(|triangle| {
            [
                source_indices[triangle[0]] as i64,
                source_indices[triangle[1]] as i64,
                source_indices[triangle[2]] as i64,
            ]
        })
        .collect::<Vec<_>>();
    (!result.is_empty()).then_some(result)
}

fn point_in_triangle(
    point: (f64, f64),
    a: (f64, f64),
    b: (f64, f64),
    c: (f64, f64),
    epsilon: f64,
) -> bool {
    orient2d(a, b, point) >= -epsilon
        && orient2d(b, c, point) >= -epsilon
        && orient2d(c, a, point) >= -epsilon
}

/// Ear-clipping triangulation for one simple polygon. Concave polygons are
/// supported; self-intersections, duplicate internal vertices, and zero-area
/// inputs fail loudly rather than producing corrupt renderer geometry.
pub fn polygon_triangles(x: &[f64], y: &[f64]) -> Option<Vec<[i64; 3]>> {
    if x.len() != y.len()
        || x.len() < 3
        || x.len().checked_mul(x.len())? > MAX_QUADRATIC_TRIANGULATION_WORK
        || !x.iter().chain(y).all(|value| value.is_finite())
    {
        return None;
    }
    let count = if x.len() > 3 && x[0] == x[x.len() - 1] && y[0] == y[y.len() - 1] {
        x.len() - 1
    } else {
        x.len()
    };
    if count < 3 {
        return None;
    }
    let mut seen = std::collections::HashSet::with_capacity(count);
    if !(0..count).all(|index| seen.insert((x[index].to_bits(), y[index].to_bits()))) {
        return None;
    }
    let signed_area = (0..count)
        .map(|index| {
            let next = (index + 1) % count;
            x[index] * y[next] - x[next] * y[index]
        })
        .sum::<f64>()
        * 0.5;
    if signed_area == 0.0 || !signed_area.is_finite() {
        return None;
    }
    let mut remaining = (0..count).collect::<Vec<_>>();
    if signed_area < 0.0 {
        remaining.reverse();
    }
    let span_x = x[..count].iter().copied().fold(f64::NEG_INFINITY, f64::max)
        - x[..count].iter().copied().fold(f64::INFINITY, f64::min);
    let span_y = y[..count].iter().copied().fold(f64::NEG_INFINITY, f64::max)
        - y[..count].iter().copied().fold(f64::INFINITY, f64::min);
    let epsilon = span_x.max(span_y).powi(2) * 1e-14;
    let point = |index: usize| (x[index], y[index]);
    let mut result = Vec::with_capacity(count - 2);
    while remaining.len() > 3 {
        let mut ear = None;
        for position in 0..remaining.len() {
            let a = remaining[(position + remaining.len() - 1) % remaining.len()];
            let b = remaining[position];
            let c = remaining[(position + 1) % remaining.len()];
            if orient2d(point(a), point(b), point(c)) <= epsilon {
                continue;
            }
            let contains = remaining.iter().any(|&candidate| {
                candidate != a
                    && candidate != b
                    && candidate != c
                    && point_in_triangle(point(candidate), point(a), point(b), point(c), epsilon)
            });
            if !contains {
                ear = Some((position, [a as i64, b as i64, c as i64]));
                break;
            }
        }
        let (position, triangle) = ear?;
        result.push(triangle);
        remaining.remove(position);
    }
    result.push([
        remaining[0] as i64,
        remaining[1] as i64,
        remaining[2] as i64,
    ]);
    Some(result)
}

/// Extract contour segments from an indexed triangular scalar field.
#[allow(clippy::too_many_arguments)]
pub fn marching_triangles_into(
    x: &[f64],
    y: &[f64],
    z: &[f64],
    triangles: &[i64],
    levels: &[f64],
    out_x0: &mut [f64],
    out_x1: &mut [f64],
    out_y0: &mut [f64],
    out_y1: &mut [f64],
    out_levels: &mut [f64],
) -> Option<usize> {
    if x.len() != y.len()
        || x.len() != z.len()
        || !triangles.len().is_multiple_of(3)
        || !levels.iter().all(|value| value.is_finite())
    {
        return None;
    }
    let query = out_x0.is_empty()
        && out_x1.is_empty()
        && out_y0.is_empty()
        && out_y1.is_empty()
        && out_levels.is_empty();
    let mut written = 0;
    for face in triangles.chunks_exact(3) {
        if face
            .iter()
            .any(|index| *index < 0 || *index as usize >= x.len())
        {
            continue;
        }
        let ids = [face[0] as usize, face[1] as usize, face[2] as usize];
        if ids
            .iter()
            .any(|index| !x[*index].is_finite() || !y[*index].is_finite() || !z[*index].is_finite())
        {
            continue;
        }
        for &level in levels {
            let mut points = [(0.0, 0.0); 3];
            let mut count = 0;
            for (a, b) in [(ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])] {
                let za = z[a] - level;
                let zb = z[b] - level;
                let point = if za == 0.0 {
                    Some((x[a], y[a]))
                } else if zb == 0.0 {
                    Some((x[b], y[b]))
                } else if (za < 0.0) != (zb < 0.0) {
                    let t = za / (za - zb);
                    Some((x[a] + t * (x[b] - x[a]), y[a] + t * (y[b] - y[a])))
                } else {
                    None
                };
                if let Some(point) = point {
                    if !points[..count].contains(&point) {
                        points[count] = point;
                        count += 1;
                    }
                }
            }
            if count == 2 {
                if !query
                    && (written >= out_x0.len()
                        || written >= out_x1.len()
                        || written >= out_y0.len()
                        || written >= out_y1.len()
                        || written >= out_levels.len())
                {
                    return None;
                }
                if !query {
                    out_x0[written] = points[0].0;
                    out_y0[written] = points[0].1;
                    out_x1[written] = points[1].0;
                    out_y1[written] = points[1].1;
                    out_levels[written] = level;
                }
                written += 1;
            }
        }
    }
    Some(written)
}

/// Convert vector origins/components into compact shaft + arrowhead segments.
///
/// `scale` follows vector-field convention: larger values shorten arrows.
/// `pivot` is 0 tail, 1 midpoint, 2 tip. Invalid vectors are omitted so no
/// non-finite coordinate can reach the renderer.
#[allow(clippy::too_many_arguments)]
pub fn vector_segments_into(
    x: &[f64],
    y: &[f64],
    u: &[f64],
    v: &[f64],
    scale: f64,
    pivot: u32,
    head_ratio: f64,
    out_x0: &mut [f64],
    out_x1: &mut [f64],
    out_y0: &mut [f64],
    out_y1: &mut [f64],
) -> Option<usize> {
    if x.len() != y.len()
        || x.len() != u.len()
        || x.len() != v.len()
        || !scale.is_finite()
        || scale <= 0.0
        || pivot > 2
        || !head_ratio.is_finite()
        || !(0.0..=1.0).contains(&head_ratio)
    {
        return None;
    }
    let required = x.len().checked_mul(3)?;
    if out_x0.len() < required
        || out_x1.len() < required
        || out_y0.len() < required
        || out_y1.len() < required
    {
        return None;
    }
    let mut written = 0;
    let head_angle = 0.45_f64;
    let (sin_a, cos_a) = head_angle.sin_cos();
    for index in 0..x.len() {
        if !x[index].is_finite()
            || !y[index].is_finite()
            || !u[index].is_finite()
            || !v[index].is_finite()
        {
            continue;
        }
        let dx = u[index] / scale;
        let dy = v[index] / scale;
        let length = dx.hypot(dy);
        if length == 0.0 {
            continue;
        }
        let (tail_x, tail_y) = match pivot {
            0 => (x[index], y[index]),
            1 => (x[index] - 0.5 * dx, y[index] - 0.5 * dy),
            2 => (x[index] - dx, y[index] - dy),
            _ => unreachable!(),
        };
        let tip_x = tail_x + dx;
        let tip_y = tail_y + dy;
        out_x0[written] = tail_x;
        out_y0[written] = tail_y;
        out_x1[written] = tip_x;
        out_y1[written] = tip_y;
        written += 1;

        let head = length * head_ratio;
        let ux = dx / length;
        let uy = dy / length;
        for side in [-1.0, 1.0] {
            let rx = ux * cos_a - side * uy * sin_a;
            let ry = side * ux * sin_a + uy * cos_a;
            out_x0[written] = tip_x;
            out_y0[written] = tip_y;
            out_x1[written] = tip_x - head * rx;
            out_y1[written] = tip_y - head * ry;
            written += 1;
        }
    }
    Some(written)
}

fn sample_vector_grid(
    x_coords: &[f64],
    y_coords: &[f64],
    u: &[f64],
    v: &[f64],
    x: f64,
    y: f64,
) -> Option<(f64, f64)> {
    if x < x_coords[0]
        || x > x_coords[x_coords.len() - 1]
        || y < y_coords[0]
        || y > y_coords[y_coords.len() - 1]
    {
        return None;
    }
    let col = x_coords
        .partition_point(|value| *value <= x)
        .saturating_sub(1)
        .min(x_coords.len() - 2);
    let row = y_coords
        .partition_point(|value| *value <= y)
        .saturating_sub(1)
        .min(y_coords.len() - 2);
    let tx = (x - x_coords[col]) / (x_coords[col + 1] - x_coords[col]);
    let ty = (y - y_coords[row]) / (y_coords[row + 1] - y_coords[row]);
    let cols = x_coords.len();
    let interp = |values: &[f64]| {
        let a = values[row * cols + col];
        let b = values[row * cols + col + 1];
        let c = values[(row + 1) * cols + col];
        let d = values[(row + 1) * cols + col + 1];
        (a * (1.0 - tx) + b * tx) * (1.0 - ty) + (c * (1.0 - tx) + d * tx) * ty
    };
    let sampled = (interp(u), interp(v));
    (sampled.0.is_finite() && sampled.1.is_finite()).then_some(sampled)
}

/// Integrate screen-bounded streamlines over a regular vector grid.
///
/// The output is independent segments so it reuses the same transport and
/// renderer as contours/error bars. Occupancy suppresses redundant paths;
/// work is bounded by grid resolution, density, and `max_steps`, never by an
/// unbounded adaptive integrator.
#[allow(clippy::too_many_arguments)]
pub fn streamlines(
    x_coords: &[f64],
    y_coords: &[f64],
    u: &[f64],
    v: &[f64],
    density: f64,
    max_steps: usize,
) -> Option<Vec<(f64, f64, f64, f64)>> {
    let rows = y_coords.len();
    let cols = x_coords.len();
    let len = rows.checked_mul(cols)?;
    if rows < 2
        || cols < 2
        || u.len() != len
        || v.len() != len
        || !density.is_finite()
        || density <= 0.0
        || max_steps == 0
        || !x_coords.windows(2).all(|pair| pair[1] > pair[0])
        || !y_coords.windows(2).all(|pair| pair[1] > pair[0])
        || !x_coords.iter().all(|value| value.is_finite())
        || !y_coords.iter().all(|value| value.is_finite())
    {
        return None;
    }
    let min_dx = x_coords
        .windows(2)
        .map(|pair| pair[1] - pair[0])
        .fold(f64::INFINITY, f64::min);
    let min_dy = y_coords
        .windows(2)
        .map(|pair| pair[1] - pair[0])
        .fold(f64::INFINITY, f64::min);
    let step = 0.35 * min_dx.min(min_dy);
    let seed_stride = (((rows.min(cols) as f64) / (12.0 * density)).floor() as usize).max(1);
    let mut occupied = vec![false; len];
    let mut out = Vec::new();
    for seed_row in (0..rows).step_by(seed_stride) {
        for seed_col in (0..cols).step_by(seed_stride) {
            if occupied[seed_row * cols + seed_col] {
                continue;
            }
            for direction in [-1.0, 1.0] {
                let mut px = x_coords[seed_col];
                let mut py = y_coords[seed_row];
                for _ in 0..max_steps {
                    let Some((su, sv)) = sample_vector_grid(x_coords, y_coords, u, v, px, py)
                    else {
                        break;
                    };
                    let speed = su.hypot(sv);
                    if speed <= f64::EPSILON {
                        break;
                    }
                    let nx = px + direction * step * su / speed;
                    let ny = py + direction * step * sv / speed;
                    if nx < x_coords[0]
                        || nx > x_coords[cols - 1]
                        || ny < y_coords[0]
                        || ny > y_coords[rows - 1]
                    {
                        break;
                    }
                    let col = x_coords
                        .partition_point(|value| *value <= nx)
                        .saturating_sub(1)
                        .min(cols - 1);
                    let row = y_coords
                        .partition_point(|value| *value <= ny)
                        .saturating_sub(1)
                        .min(rows - 1);
                    let cell = row * cols + col;
                    if occupied[cell] && !(row == seed_row && col == seed_col) {
                        break;
                    }
                    occupied[cell] = true;
                    out.push((px, nx, py, ny));
                    px = nx;
                    py = ny;
                }
            }
            occupied[seed_row * cols + seed_col] = true;
        }
    }
    Some(out)
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

    m4_indices_impl(
        x,
        y,
        x0,
        x1,
        n_buckets,
        start,
        end,
        par_threads(end - start),
    )
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
fn m4_range(
    x: &[f64],
    y: &[f64],
    x0: f64,
    inv_bucket_w: f64,
    n_buckets: usize,
    lo: usize,
    hi: usize,
) -> Vec<u32> {
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

/// Resolve the two diagonally ambiguous marching-squares cases with the
/// bilinear asymptotic decider.  A fixed lookup table tears or joins contours
/// incorrectly whenever the opposite-corner magnitudes are unequal; this is
/// the same determinant-based choice used by contour engines such as
/// Matplotlib's contourpy backend.
fn ambiguous_contour_pairs(
    mask: u8,
    v00: f64,
    v10: f64,
    v11: f64,
    v01: f64,
    level: f64,
) -> &'static [(u8, u8)] {
    const A: &[(u8, u8)] = &[(0, 1), (2, 3)];
    const B: &[(u8, u8)] = &[(3, 0), (1, 2)];
    let determinant = (v00 - level) * (v11 - level) - (v10 - level) * (v01 - level);
    if determinant > 0.0 || (determinant == 0.0 && mask == 10) {
        A
    } else {
        B
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
    let sorted_levels = levels.windows(2).all(|pair| pair[0] <= pair[1]);
    for row in 0..rows - 1 {
        for col in 0..cols - 1 {
            let v00 = z[row * cols + col];
            let v10 = z[row * cols + col + 1];
            let v11 = z[(row + 1) * cols + col + 1];
            let v01 = z[(row + 1) * cols + col];
            if !(v00.is_finite() && v10.is_finite() && v11.is_finite() && v01.is_finite()) {
                continue;
            }
            let local_min = v00.min(v10).min(v11).min(v01);
            let local_max = v00.max(v10).max(v11).max(v01);
            let corners = [
                (x_coords[col], y_coords[row], v00),
                (x_coords[col + 1], y_coords[row], v10),
                (x_coords[col + 1], y_coords[row + 1], v11),
                (x_coords[col], y_coords[row + 1], v01),
            ];
            let mut process_level = |level: f64| {
                let mask = u8::from(v00 >= level)
                    | (u8::from(v10 >= level) << 1)
                    | (u8::from(v11 >= level) << 2)
                    | (u8::from(v01 >= level) << 3);
                let pairs = if mask == 5 || mask == 10 {
                    ambiguous_contour_pairs(mask, v00, v10, v11, v01, level)
                } else {
                    contour_pairs(mask)
                };
                if pairs.is_empty() {
                    return;
                }
                let edge_point = |edge: usize| {
                    let (xa, ya, va) = corners[edge];
                    let (xb, yb, vb) = corners[(edge + 1) % 4];
                    let denom = vb - va;
                    let fraction = if denom == 0.0 {
                        0.5
                    } else {
                        ((level - va) / denom).clamp(0.0, 1.0)
                    };
                    (xa + (xb - xa) * fraction, ya + (yb - ya) * fraction)
                };
                for &(edge_a, edge_b) in pairs {
                    let (x0, y0) = edge_point(edge_a as usize);
                    let (x1, y1) = edge_point(edge_b as usize);
                    emit(x0, x1, y0, y1, level);
                    count += 1;
                }
            };
            if sorted_levels {
                let start = levels.partition_point(|level| *level < local_min);
                let end = levels.partition_point(|level| *level <= local_max);
                for &level in &levels[start..end] {
                    process_level(level);
                }
            } else {
                for &level in levels {
                    if level >= local_min && level <= local_max {
                        process_level(level);
                    }
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
    marching_squares_scan(
        z,
        rows,
        cols,
        x_coords,
        y_coords,
        levels,
        |x0, x1, y0, y1, level| {
            if written < capacity {
                x0_out[written] = x0;
                x1_out[written] = x1;
                y0_out[written] = y0;
                y1_out[written] = y1;
                level_out[written] = level;
            }
            written += 1;
        },
    );
    written
}

/// Map normalized heatmap scalars to a top-row-first RGBA8 image. This is the
/// Native counterpart of `_scene.grid_rgba`'s heatmap branch: non-finite
/// values are missing, while finite normalized values map through the same
/// evenly spaced color stops with ties-to-even byte rounding.
pub fn heatmap_rgba_into(
    raw: &[f64],
    w: usize,
    h: usize,
    stops: &[[u8; 3]],
    alpha: u8,
    out: &mut [u8],
) -> bool {
    if w == 0
        || h == 0
        || stops.is_empty()
        || raw.len() != w.saturating_mul(h)
        || out.len() != raw.len().saturating_mul(4)
    {
        return false;
    }
    for row in 0..h {
        let destination_row = h - 1 - row;
        for col in 0..w {
            let value = raw[row * w + col];
            let destination = (destination_row * w + col) * 4;
            out[destination..destination + 4].copy_from_slice(&heatmap_color(value, stops, alpha));
        }
    }
    true
}

/// Map one normalized heatmap scalar with the exact static-export semantics.
/// Kept in one place so full-grid conversion and direct raster sampling cannot
/// drift in rounding, missing-value, or alpha behavior.
pub(crate) fn heatmap_color(value: f64, stops: &[[u8; 3]], alpha: u8) -> [u8; 4] {
    debug_assert!(!stops.is_empty());
    // Only genuinely missing cells (NaN, e.g. masked/cmin-clipped bins) are
    // transparent. A real in-domain value of 0 must paint the colormap's floor
    // color, matching Matplotlib's hist2d/imshow which fill the whole extent.
    if value.is_nan() {
        return [0, 0, 0, 0];
    }
    let t = ((value * 255.0 - 1.0) / 254.0).clamp(0.0, 1.0);
    colormap_color(t, stops, alpha)
}

/// Evenly spaced color-stop interpolation for a normalized scalar. Shared by
/// heatmaps and borrowed per-mark color channels so ties-to-even byte rounding
/// cannot drift between static chart families.
pub(crate) fn colormap_color(value: f64, stops: &[[u8; 3]], alpha: u8) -> [u8; 4] {
    debug_assert!(!stops.is_empty());
    let last = stops.len() - 1;
    let t = value.clamp(0.0, 1.0);
    let position = t * last as f64;
    let lo = position.floor() as usize;
    let hi = (lo + 1).min(last);
    let fraction = position - lo as f64;
    let mut color = [0u8; 4];
    for channel in 0..3 {
        let start = stops[lo][channel] as f64;
        let value = start + (stops[hi][channel] as f64 - start) * fraction;
        color[channel] = value.round_ties_even().clamp(0.0, 255.0) as u8;
    }
    color[3] = alpha;
    color
}

/// Map the compact log-u8 density wire directly to a top-row-first RGBA8
/// image. This fuses log decode, colormap interpolation, alpha shaping, and
/// vertical flip so static export never materializes three full-grid NumPy
/// temporaries before entering the native rasterizer.
pub fn density_rgba_into(
    encoded: &[u8],
    w: usize,
    h: usize,
    maximum: f64,
    stops: &[[u8; 3]],
    opacity: f64,
    out: &mut [u8],
) -> bool {
    if w == 0
        || h == 0
        || encoded.len() != w.saturating_mul(h)
        || out.len() != encoded.len().saturating_mul(4)
    {
        return false;
    }
    let Some(lut) = density_rgba_lut(maximum, stops, opacity) else {
        return false;
    };
    for row in 0..h {
        let destination_row = h - 1 - row;
        for col in 0..w {
            let code = encoded[row * w + col] as usize;
            let destination = (destination_row * w + col) * 4;
            out[destination..destination + 4].copy_from_slice(&lut[code]);
        }
    }
    true
}

/// Precompute the exact log-u8 density colors once. The display-list
/// rasterizer uses this table to sample compact density bytes directly,
/// without expanding the full grid to a temporary RGBA image.
pub(crate) fn density_rgba_lut(
    maximum: f64,
    stops: &[[u8; 3]],
    opacity: f64,
) -> Option<[[u8; 4]; 256]> {
    if stops.is_empty()
        || !maximum.is_finite()
        || maximum < 0.0
        || !opacity.is_finite()
        || !(0.0..=1.0).contains(&opacity)
    {
        return None;
    }
    let last = stops.len() - 1;
    let log_max = maximum.ln_1p();
    let mut lut = [[0u8; 4]; 256];
    for (code, color) in lut.iter_mut().enumerate() {
        let t = if code == 0 || maximum <= 0.0 {
            0.0
        } else {
            (((code as f64 / 255.0) * log_max).exp_m1() / maximum).clamp(0.0, 1.0)
        };
        let position = t * last as f64;
        let lo = position.floor() as usize;
        let hi = (lo + 1).min(last);
        let fraction = position - lo as f64;
        for channel in 0..3 {
            let start = f64::from(stops[lo][channel]);
            let value = start + (f64::from(stops[hi][channel]) - start) * fraction;
            color[channel] = value.round_ties_even().clamp(0.0, 255.0) as u8;
        }
        color[3] = if code == 0 {
            0
        } else {
            ((t * 1.35).clamp(0.0, 1.0) * 255.0 * opacity) as u8
        };
    }
    Some(lut)
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
    bin_2d_impl(
        x,
        y,
        x0,
        x1,
        y0,
        y1,
        w,
        h,
        bin_2d_threads(x.len(), w * h),
        out,
    );
}

/// f32-input twin of [`bin_2d`] for the out-of-core spatial index
/// (`_spatial.py`): bins memmap'd f32 (lon, lat) slices **directly**, skipping
/// the f64 widening that otherwise dominates a windowed gather (an f32→f64 copy
/// of every in-window point — measured at ~half the whole query). Cell math
/// widens each value to f64 and matches `bin_2d` bit-for-bit over the same
/// points cast to f64, so the index's exact-density result is unchanged.
/// Parallel with private grids + an integer merge, so counts are thread-count
/// invariant.
#[allow(clippy::too_many_arguments)]
pub fn bin_2d_f32(
    x: &[f32],
    y: &[f32],
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
    let n = x.len();
    let threads = bin_2d_threads(n, w * h);
    if threads <= 1 || n < threads {
        let mut grid = vec![0u32; w * h];
        bin_2d_count_f32_scalar(x, y, x0, x1, y0, y1, w, h, &mut grid);
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
                    bin_2d_count_f32_scalar(xs, ys, x0, x1, y0, y1, w, h, &mut grid);
                    grid
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("bin_2d_f32 worker panicked"))
            .collect()
    });
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

/// f32 clone of [`bin_2d_count_scalar`]: widen each value to f64 so cell
/// indexing is identical to the f64 path, then count into a u32 grid.
#[allow(clippy::too_many_arguments)]
fn bin_2d_count_f32_scalar(
    x: &[f32],
    y: &[f32],
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
        let xv = x[i] as f64;
        let yv = y[i] as f64;
        if !xv.is_finite() || !yv.is_finite() || xv < x0 || xv >= x1 || yv < y0 || yv >= y1 {
            continue;
        }
        let cx = (((xv - x0) * sx) as usize).min(w - 1);
        let cy = (((yv - y0) * sy) as usize).min(h - 1);
        grid[cy * w + cx] = grid[cy * w + cx].saturating_add(1);
    }
}

/// Row-scan kernels fan out across cores only past this size, where thread
/// spawn + merge cost is well amortized. Threading stays inside the call —
/// the ABI remains synchronous (engine doc E5).
const PAR_THRESHOLD: usize = 1 << 19;

fn par_threads(n: usize) -> usize {
    static CODSPEED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    if *CODSPEED.get_or_init(|| std::env::var_os("CODSPEED_ENV").is_some()) {
        return 1;
    }
    let cores = std::thread::available_parallelism().map_or(1, |p| p.get());
    par_threads_for(n, cores)
}

fn par_threads_for(n: usize, cores: usize) -> usize {
    if n >= PAR_THRESHOLD {
        cores.clamp(1, MAX_ROW_THREADS)
    } else {
        1
    }
}

/// Grid-aware thread choice for the 2-D binning kernels. Going parallel makes
/// every worker zero a private `w*h` u32 grid and adds a t-way merge that
/// re-reads all `t*w*h` cells, so fan-out costs ≥ 2 memory ops per cell per
/// thread while the scan it accelerates costs ~15–20 ops per point. A thread
/// only pays for itself while its share of the scan outweighs one grid's
/// traffic, so cap fan-out at the points-per-cell ratio: screen-sized grids
/// keep the full row-scan fan-out, and once the grid has at least as many
/// cells as there are points (the tile-pyramid base level, §5:
/// `base_dim² ≈ 2n`) the kernel runs serial. Same counts for any cap — the
/// integer-sum merge is thread-count invariant.
fn bin_2d_threads(n: usize, cells: usize) -> usize {
    (n / cells.max(1)).clamp(1, par_threads(n))
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
    let threads = bin_2d_threads(n, w * h);
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

/// sRGB byte → linear-light u16 (IEC 61966-2-1, scaled to 0..=65535,
/// round-half-even). A checked-in literal keeps the mean-color pipeline
/// below integer-only end to end (no runtime `powf`/libm dependency), so it
/// is bitwise deterministic for any thread count and across platforms.
/// Strictly increasing, so the inverse is an exact search.
pub(crate) const SRGB_TO_LINEAR_U16: [u16; 256] = [
    0, 20, 40, 60, 80, 99, 119, 139,
    159, 179, 199, 219, 241, 264, 288, 313,
    340, 367, 396, 427, 458, 491, 526, 562,
    599, 637, 677, 718, 761, 805, 851, 898,
    947, 997, 1048, 1101, 1156, 1212, 1270, 1330,
    1391, 1453, 1517, 1583, 1651, 1720, 1790, 1863,
    1937, 2013, 2090, 2170, 2250, 2333, 2418, 2504,
    2592, 2681, 2773, 2866, 2961, 3058, 3157, 3258,
    3360, 3464, 3570, 3678, 3788, 3900, 4014, 4129,
    4247, 4366, 4488, 4611, 4736, 4864, 4993, 5124,
    5257, 5392, 5530, 5669, 5810, 5953, 6099, 6246,
    6395, 6547, 6700, 6856, 7014, 7174, 7335, 7500,
    7666, 7834, 8004, 8177, 8352, 8528, 8708, 8889,
    9072, 9258, 9445, 9635, 9828, 10022, 10219, 10417,
    10619, 10822, 11028, 11235, 11446, 11658, 11873, 12090,
    12309, 12530, 12754, 12980, 13209, 13440, 13673, 13909,
    14146, 14387, 14629, 14874, 15122, 15371, 15623, 15878,
    16135, 16394, 16656, 16920, 17187, 17456, 17727, 18001,
    18277, 18556, 18837, 19121, 19407, 19696, 19987, 20281,
    20577, 20876, 21177, 21481, 21787, 22096, 22407, 22721,
    23038, 23357, 23678, 24002, 24329, 24658, 24990, 25325,
    25662, 26001, 26344, 26688, 27036, 27386, 27739, 28094,
    28452, 28813, 29176, 29542, 29911, 30282, 30656, 31033,
    31412, 31794, 32179, 32567, 32957, 33350, 33745, 34143,
    34544, 34948, 35355, 35764, 36176, 36591, 37008, 37429,
    37852, 38278, 38706, 39138, 39572, 40009, 40449, 40891,
    41337, 41785, 42236, 42690, 43147, 43606, 44069, 44534,
    45002, 45473, 45947, 46423, 46903, 47385, 47871, 48359,
    48850, 49344, 49841, 50341, 50844, 51349, 51858, 52369,
    52884, 53401, 53921, 54445, 54971, 55500, 56032, 56567,
    57105, 57646, 58190, 58737, 59287, 59840, 60396, 60955,
    61517, 62082, 62650, 63221, 63795, 64372, 64952, 65535,
];

/// Nearest sRGB byte for a linear-light u16 — the exact inverse of the table
/// above (integer search over a strictly increasing sequence; ties round to
/// the darker byte).
pub(crate) fn linear_u16_to_srgb_u8(linear: u16) -> u8 {
    let above = SRGB_TO_LINEAR_U16.partition_point(|&v| v <= linear);
    if above == 0 {
        return 0; // unreachable: table[0] == 0 ≤ every u16
    }
    if above >= 256 {
        return 255;
    }
    let below_value = SRGB_TO_LINEAR_U16[above - 1];
    let above_value = SRGB_TO_LINEAR_U16[above];
    if linear - below_value <= above_value - linear {
        (above - 1) as u8
    } else {
        above as u8
    }
}

/// Per-point straight-alpha RGBA8 source for mean-color binning.
pub enum BinColorSource<'a> {
    /// One LUT index per point plus an RGBA8 palette/colormap table
    /// (1..=256 entries). Indices wrap modulo the table length — the
    /// palette's own repeat rule, so out-of-palette categorical codes bin
    /// with exactly the color they draw with.
    Indexed { idx: &'a [u8], lut: &'a [[u8; 4]] },
    /// Straight-alpha RGBA8, 4 bytes per point (the `direct_rgba` channel).
    Rgba(&'a [u8]),
}

/// One cell of the mean-color accumulator: exact integer sums, so the
/// parallel merge is order-independent (bitwise deterministic for any thread
/// count, like `bin_2d`). Color sums are alpha-weighted linear-light u16, so
/// a translucent point contributes proportionally and the mean is the
/// physically downsampled color of the cell's points.
#[derive(Clone, Copy, Default)]
pub(crate) struct MeanColorCell {
    pub(crate) count: u32,
    alpha: u64,
    red: u64,
    green: u64,
    blue: u64,
}

impl MeanColorCell {
    /// Straight-alpha RGBA8: sRGB mean color + mean point alpha (integer
    /// rounding, half away from zero — deterministic).
    fn rgba8(&self) -> [u8; 4] {
        if self.count == 0 || self.alpha == 0 {
            return [0, 0, 0, 0];
        }
        let mean = |sum: u64| ((sum + self.alpha / 2) / self.alpha).min(u16::MAX as u64) as u16;
        let alpha =
            ((self.alpha + u64::from(self.count) / 2) / u64::from(self.count)).min(255) as u8;
        [
            linear_u16_to_srgb_u8(mean(self.red)),
            linear_u16_to_srgb_u8(mean(self.green)),
            linear_u16_to_srgb_u8(mean(self.blue)),
            alpha,
        ]
    }

    /// Storage form for pyramid color planes: linear-light u16 mean color
    /// plus the mean straight alpha rescaled to 0..=65535.
    pub(crate) fn mean_u16x4(&self) -> [u16; 4] {
        if self.count == 0 || self.alpha == 0 {
            return [0, 0, 0, 0];
        }
        let mean = |sum: u64| ((sum + self.alpha / 2) / self.alpha).min(u16::MAX as u64) as u16;
        let alpha = ((self.alpha * 257 + u64::from(self.count) / 2) / u64::from(self.count))
            .min(u16::MAX as u64) as u16;
        [mean(self.red), mean(self.green), mean(self.blue), alpha]
    }
}

/// Byte budget for the mean-color scan's worker accumulators together. Each
/// worker owns a private `cells × size_of::<MeanColorCell>()` (40 B/cell)
/// grid; screen-sized grids and the 2048² default base level fit the full
/// 4-worker fan-out comfortably, but a no-rescan trace's adaptive base level
/// (§28; up to 16384² cells) would turn that fan-out into tens of GB of
/// transient build memory — the difference between a colored billion-point
/// build fitting in RAM or not. Workers over budget are shed down to a
/// serial scan: one-time build wall-clock is traded, peak RSS never. (The
/// merge target grid rides on top of the budget; at every size where memory
/// binds, the scan is already serial and allocates exactly one grid.)
const MEAN_COLOR_ACCUM_BUDGET_BYTES: usize = 1 << 30;

/// Pure fan-out choice for the mean-color scan: the row-scan fan-out
/// (`bin_2d_threads`) capped at 4, then shed to whatever worker count keeps
/// the private accumulators inside `MEAN_COLOR_ACCUM_BUDGET_BYTES`.
fn mean_color_threads_for(row_threads: usize, cells: usize) -> usize {
    let per_grid = cells.saturating_mul(std::mem::size_of::<MeanColorCell>());
    let by_memory = (MEAN_COLOR_ACCUM_BUDGET_BYTES / per_grid.max(1)).max(1);
    row_threads.min(4).min(by_memory)
}

/// Fused count+color accumulation over a full grid: the shared core of
/// `bin_2d_mean_color` and the pyramid build's base pass
/// (`tiles::build_color`). Returns the raw accumulator cells so callers keep
/// exact counts alongside the color means.
///
/// Fan-out is gated by the points-per-cell ratio (like `bin_2d`), capped at
/// 4, and shed further to fit `MEAN_COLOR_ACCUM_BUDGET_BYTES`: each worker's
/// private accumulator is ~10× a count grid (40 B/cell), so the cap bounds
/// the transient while still cutting the pyramid's 100M-row base scan to a
/// quarter. Integer sums merge order-independently — bitwise deterministic
/// for any thread count.
#[allow(clippy::too_many_arguments)]
pub(crate) fn bin_2d_mean_color_cells(
    x: &[f64],
    y: &[f64],
    colors: &BinColorSource<'_>,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
) -> Vec<MeanColorCell> {
    let n = x.len();
    let cells = w * h;
    let threads = mean_color_threads_for(bin_2d_threads(n, cells), cells);
    if threads <= 1 || n < threads {
        let mut grid = vec![MeanColorCell::default(); cells];
        bin_2d_mean_color_accumulate(x, y, colors, 0, x0, x1, y0, y1, w, h, &mut grid);
        return grid;
    }
    let chunk = n.div_ceil(threads);
    let grids: Vec<Vec<MeanColorCell>> = std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let lo = (t * chunk).min(n);
                let hi = ((t + 1) * chunk).min(n);
                let (xs, ys) = (&x[lo..hi], &y[lo..hi]);
                s.spawn(move || {
                    let mut grid = vec![MeanColorCell::default(); cells];
                    bin_2d_mean_color_accumulate(xs, ys, colors, lo, x0, x1, y0, y1, w, h, &mut grid);
                    grid
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|hd| hd.join().expect("bin_2d_mean_color worker panicked"))
            .collect()
    });
    let mut grid = vec![MeanColorCell::default(); cells];
    for part in &grids {
        for (acc, cell) in grid.iter_mut().zip(part) {
            acc.count = acc.count.saturating_add(cell.count);
            acc.alpha += cell.alpha;
            acc.red += cell.red;
            acc.green += cell.green;
            acc.blue += cell.blue;
        }
    }
    grid
}

/// Mean-color companion to `bin_2d` (§5 Tier 2, LOD doc §2): average the
/// *resolved point colors* of each cell so the density surface wears the data
/// set's own colors while count drives only the alpha channel. `out` is
/// `w*h*4` straight-alpha RGBA8, row 0 = bottom (same orientation as
/// `bin_2d`): rgb = alpha-weighted mean point color (averaged in linear
/// light, quantized back to sRGB), a = plain mean of the points' straight
/// alpha. Empty cells are fully zeroed; a cell whose points are all alpha-0
/// keeps rgb 0 too (its display alpha is 0, so no color is ever invented).
/// In-window/NaN predicates and cell indexing are bit-identical to
/// `bin_2d_count_scalar`, so occupied cells match the count grid exactly.
#[allow(clippy::too_many_arguments)] // window (x0,x1,y0,y1) + grid (w,h) + io is irreducible
pub fn bin_2d_mean_color(
    x: &[f64],
    y: &[f64],
    colors: &BinColorSource<'_>,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    out: &mut [u8],
) {
    assert_eq!(x.len(), y.len());
    assert_eq!(out.len(), w * h * 4);
    assert!(w > 0 && h > 0 && x1_gt_x0(x0, x1) && x1_gt_x0(y0, y1));
    match colors {
        BinColorSource::Indexed { idx, lut } => {
            assert_eq!(idx.len(), x.len());
            assert!(!lut.is_empty() && lut.len() <= 256);
        }
        BinColorSource::Rgba(rgba) => assert_eq!(rgba.len(), x.len() * 4),
    }
    let grid = bin_2d_mean_color_cells(x, y, colors, x0, x1, y0, y1, w, h);
    for (cell, quad) in grid.iter().zip(out.chunks_exact_mut(4)) {
        quad.copy_from_slice(&cell.rgba8());
    }
}

/// Shared scan used by the serial and parallel paths (per-point behavior is
/// identical by construction). `base` offsets the row index into the color
/// source so parallel chunks read their own colors.
#[allow(clippy::too_many_arguments)]
fn bin_2d_mean_color_accumulate(
    x: &[f64],
    y: &[f64],
    colors: &BinColorSource<'_>,
    base: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    grid: &mut [MeanColorCell],
) {
    let sx = w as f64 / (x1 - x0);
    let sy = h as f64 / (y1 - y0);
    for i in 0..x.len() {
        let xv = x[i];
        let yv = y[i];
        if !xv.is_finite() || !yv.is_finite() || xv < x0 || xv >= x1 || yv < y0 || yv >= y1 {
            continue;
        }
        let cx = (((xv - x0) * sx) as usize).min(w - 1);
        let cy = (((yv - y0) * sy) as usize).min(h - 1);
        let [r, g, b, a] = match colors {
            BinColorSource::Indexed { idx, lut } => lut[idx[base + i] as usize % lut.len()],
            BinColorSource::Rgba(rgba) => {
                let at = (base + i) * 4;
                [rgba[at], rgba[at + 1], rgba[at + 2], rgba[at + 3]]
            }
        };
        let cell = &mut grid[cy * w + cx];
        let weight = u64::from(a);
        cell.count = cell.count.saturating_add(1);
        cell.alpha += weight;
        cell.red += weight * u64::from(SRGB_TO_LINEAR_U16[r as usize]);
        cell.green += weight * u64::from(SRGB_TO_LINEAR_U16[g as usize]);
        cell.blue += weight * u64::from(SRGB_TO_LINEAR_U16[b as usize]);
    }
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
    let threads = bin_2d_threads(x.len(), w * h);
    bin_2d_indices_impl(x, y, lo_x, hi_x, lo_y, hi_y, w, h, threads, grid, idx)
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

/// Copy ascending per-worker row selections straight into `out` at their
/// prefix offsets. Returns the total selection length; rows are written only
/// when the total fits `out`, matching the two-phase capacity protocol of the
/// sampling ABI. Writing chunk-by-chunk replaces the previous
/// concatenate-then-copy shape, which allocated and copied a second
/// selection-sized buffer per call (§27: staging never grows with data).
fn write_selected_chunks(chunks: &[Vec<u32>], out: &mut [u32]) -> usize {
    let total: usize = chunks.iter().map(Vec::len).sum();
    if total == 0 || total > out.len() {
        return total;
    }
    if total >= PAR_THRESHOLD {
        // Destinations are disjoint, so the copies fan out safely.
        std::thread::scope(|scope| {
            let mut rest = &mut out[..total];
            for chunk in chunks {
                let (dst, tail) = std::mem::take(&mut rest).split_at_mut(chunk.len());
                rest = tail;
                scope.spawn(move || dst.copy_from_slice(chunk));
            }
        });
    } else {
        let mut cursor = 0usize;
        for chunk in chunks {
            out[cursor..cursor + chunk.len()].copy_from_slice(chunk);
            cursor += chunk.len();
        }
    }
    total
}

/// Full-domain density first paint: build the grid and deterministically
/// sample implicit row ids in one traversal. Unlike [`bin_2d_indices`], the
/// sampled rows do not depend on the viewport predicate: callers use this
/// only after proving every source row is visible. The two results are
/// therefore exactly [`bin_2d`] and [`sample_range_indices_into`] for the
/// same arguments, while interleaving the independent grid and SplitMix work
/// lets the CPU overlap their latency. Returns the exact selection length;
/// rows are written only when they fit `out_rows`.
#[allow(clippy::too_many_arguments)]
pub fn bin_2d_sample_range(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    seed: u64,
    threshold: u64,
    out: &mut [f32],
    out_rows: &mut [u32],
) -> usize {
    assert_eq!(x.len(), y.len());
    assert!(x.len() <= u32::MAX as usize);
    assert_eq!(out.len(), w * h);
    assert!(w > 0 && h > 0 && x1_gt_x0(x0, x1) && x1_gt_x0(y0, y1));
    let threads = bin_2d_threads(x.len(), w * h);
    let chunks =
        bin_2d_sample_range_impl(x, y, x0, x1, y0, y1, w, h, seed, threshold, threads, out);
    write_selected_chunks(&chunks, out_rows)
}

#[allow(clippy::too_many_arguments)]
fn bin_2d_sample_range_scan(
    x: &[f64],
    y: &[f64],
    base: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    seed: u64,
    threshold: u64,
    grid: &mut [u32],
) -> Vec<u32> {
    let sx = w as f64 / (x1 - x0);
    let sy = h as f64 / (y1 - y0);
    let mut selected = Vec::with_capacity(sample_expected_capacity(x.len(), threshold));
    for i in 0..x.len() {
        let row = base + i;
        if splitmix64(row as u64, seed) <= threshold {
            selected.push(row as u32);
        }
        let xv = x[i];
        let yv = y[i];
        if !xv.is_finite() || !yv.is_finite() || xv < x0 || xv >= x1 || yv < y0 || yv >= y1 {
            continue;
        }
        let cx = (((xv - x0) * sx) as usize).min(w - 1);
        let cy = (((yv - y0) * sy) as usize).min(h - 1);
        grid[cy * w + cx] = grid[cy * w + cx].saturating_add(1);
    }
    selected
}

#[allow(clippy::too_many_arguments)]
fn bin_2d_sample_range_impl(
    x: &[f64],
    y: &[f64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    seed: u64,
    threshold: u64,
    threads: usize,
    out: &mut [f32],
) -> Vec<Vec<u32>> {
    let n = x.len();
    if threads <= 1 || n < threads {
        let mut grid = vec![0u32; w * h];
        let selected =
            bin_2d_sample_range_scan(x, y, 0, x0, x1, y0, y1, w, h, seed, threshold, &mut grid);
        for (o, c) in out.iter_mut().zip(grid) {
            *o = c as f32;
        }
        return vec![selected];
    }

    let chunk = n.div_ceil(threads);
    let parts: Vec<(Vec<u32>, Vec<u32>)> = std::thread::scope(|scope| {
        let handles: Vec<_> = x
            .chunks(chunk)
            .zip(y.chunks(chunk))
            .enumerate()
            .map(|(thread, (xs, ys))| {
                let base = thread * chunk;
                scope.spawn(move || {
                    let mut grid = vec![0u32; w * h];
                    let selected = bin_2d_sample_range_scan(
                        xs, ys, base, x0, x1, y0, y1, w, h, seed, threshold, &mut grid,
                    );
                    (grid, selected)
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().expect("bin_2d_sample_range worker panicked"))
            .collect()
    });

    let cell_chunk = (w * h).div_ceil(threads);
    std::thread::scope(|scope| {
        for (part_index, out_part) in out.chunks_mut(cell_chunk).enumerate() {
            let base = part_index * cell_chunk;
            let parts = &parts;
            scope.spawn(move || {
                for (offset, cell) in out_part.iter_mut().enumerate() {
                    let count: u64 = parts
                        .iter()
                        .map(|(grid, _)| u64::from(grid[base + offset]))
                        .sum();
                    *cell = count as f32;
                }
            });
        }
    });

    parts.into_iter().map(|(_, rows)| rows).collect()
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

fn sample_expected_capacity(size: usize, threshold: u64) -> usize {
    let fraction = if threshold == u64::MAX {
        1.0
    } else {
        threshold as f64 / u64::MAX as f64
    };
    ((size as f64 * fraction).ceil() as usize).saturating_add(16)
}

/// Deterministic sampling mask: `out[i] = splitmix64(ids[i], seed) <= threshold`.
/// One fused pass — the NumPy expression allocates five full-width u64
/// temporaries (~80 MB each at 10M rows) and dominated the density payload
/// build; this reads ids once and writes the byte mask once. u32 ids widen
/// in-register, avoiding a caller-side u64 selection copy.
pub fn sample_mask<T: Copy + Sync + Into<u64>>(
    ids: &[T],
    seed: u64,
    threshold: u64,
    out: &mut [u8],
) {
    assert_eq!(ids.len(), out.len());
    sample_mask_impl(ids, seed, threshold, par_threads(ids.len()), out)
}

/// Deterministically sample implicit row ids `0..size` without materializing
/// the input ids or a byte mask.  The selected indices are ascending and are
/// bit-identical to filtering `arange(size)` with [`sample_mask`].
///
/// This is the common full-domain density-overlay path.  Its live memory is
/// proportional to the selected rows rather than the source row count.
/// Returns the exact selection length; rows are written straight from the
/// per-worker selections only when they fit `out` — no concatenated
/// intermediate copy.
pub fn sample_range_indices_into(size: usize, seed: u64, threshold: u64, out: &mut [u32]) -> usize {
    let chunks = sample_range_chunks(size, seed, threshold);
    write_selected_chunks(&chunks, out)
}

fn sample_range_chunks(size: usize, seed: u64, threshold: u64) -> Vec<Vec<u32>> {
    assert!(size <= u32::MAX as usize);
    if size == 0 {
        return Vec::new();
    }
    let threads = par_threads(size).min(size);
    let per = size.div_ceil(threads);
    std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .filter_map(|thread| {
                let start = thread * per;
                let stop = (start + per).min(size);
                (start < stop).then(|| {
                    s.spawn(move || {
                        let mut selected =
                            Vec::with_capacity(sample_expected_capacity(stop - start, threshold));
                        for id in start..stop {
                            if splitmix64(id as u64, seed) <= threshold {
                                selected.push(id as u32);
                            }
                        }
                        selected
                    })
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().expect("sample-range worker panicked"))
            .collect()
    })
}

/// Test-only convenience: the selection as one owned Vec.
#[cfg(test)]
pub fn sample_range_indices(size: usize, seed: u64, threshold: u64) -> Vec<u32> {
    sample_range_chunks(size, seed, threshold).concat()
}

/// Category-stratified sampling for implicit row ids `0..groups.len()`.
///
/// This is the full-domain categorical density-overlay path. It is equivalent
/// to [`stratified_sample_mask`] followed by filtering the implicit ids, but
/// never allocates an ids array or a source-sized byte mask. The result is
/// ascending, so it can index canonical columns directly.
///
/// `groups[i]` must be `< n_groups`; returns `None` for an invalid code or
/// empty group domain.
pub fn stratified_sample_range_u8(
    groups: &[u8],
    n_groups: usize,
    seed: u64,
    fraction: f64,
    min_count: u64,
) -> Option<Vec<u32>> {
    if n_groups == 0 || n_groups > 256 || groups.len() > u32::MAX as usize {
        return None;
    }
    if groups.is_empty() {
        return Some(Vec::new());
    }

    let mut counts = vec![0u64; n_groups];
    for &group in groups {
        *counts.get_mut(group as usize)? += 1;
    }
    stratified_sample_range_u8_counted(groups, &counts, seed, fraction, min_count)
}

/// As [`stratified_sample_range_u8`], reusing exact per-code counts produced
/// during factorization. `counts` must cover every dense code and sum to the
/// source length; malformed codes are still rejected during selection.
pub fn stratified_sample_range_u8_counted(
    groups: &[u8],
    counts: &[u64],
    seed: u64,
    fraction: f64,
    min_count: u64,
) -> Option<Vec<u32>> {
    if counts.is_empty()
        || counts.len() > 256
        || groups.len() > u32::MAX as usize
        || counts
            .iter()
            .try_fold(0u64, |sum, &count| sum.checked_add(count))?
            != groups.len() as u64
    {
        return None;
    }
    if groups.is_empty() {
        return Some(Vec::new());
    }
    stratified_sample_range_u8_from_counts(groups, counts, seed, fraction, min_count)
}

fn stratified_sample_range_u8_from_counts(
    groups: &[u8],
    counts: &[u64],
    seed: u64,
    fraction: f64,
    min_count: u64,
) -> Option<Vec<u32>> {
    let n_groups = counts.len();
    let n = groups.len() as f64;
    let thresholds: Vec<u64> = counts
        .iter()
        .map(|&count| sample_threshold(fraction * (n / count as f64).sqrt()))
        .collect();

    let threads = par_threads(groups.len());
    let per = groups.len().div_ceil(threads);
    let thresholds_ref = &thresholds;
    let chunks = std::thread::scope(|scope| -> Option<Vec<(Vec<u32>, Vec<u64>)>> {
        let handles: Vec<_> = groups
            .chunks(per)
            .enumerate()
            .map(|(chunk_index, chunk)| {
                scope.spawn(move || -> Option<(Vec<u32>, Vec<u64>)> {
                    let start = chunk_index * per;
                    let mut selected = Vec::new();
                    let mut kept = vec![0u64; n_groups];
                    for (offset, &group) in chunk.iter().enumerate() {
                        let row = start + offset;
                        let threshold = *thresholds_ref.get(group as usize)?;
                        if splitmix64(row as u64, seed) <= threshold {
                            selected.push(row as u32);
                            kept[group as usize] += 1;
                        }
                    }
                    Some((selected, kept))
                })
            })
            .collect();
        let mut chunks = Vec::with_capacity(handles.len());
        for handle in handles {
            chunks.push(handle.join().expect("stratified-range worker panicked")?);
        }
        Some(chunks)
    })?;

    let mut kept = vec![0u64; n_groups];
    let selected_len = chunks.iter().map(|(rows, _)| rows.len()).sum();
    let mut selected = Vec::with_capacity(selected_len);
    for (rows, part_kept) in chunks {
        selected.extend(rows);
        for (total, part) in kept.iter_mut().zip(part_kept) {
            *total += part;
        }
    }

    complete_stratified_sample_range(groups, counts, seed, min_count, selected, &kept)
}

/// Apply the per-category minimum to threshold-selected rows. Shared by the
/// standalone and bin-fused paths so rare-category behavior cannot drift.
fn complete_stratified_sample_range(
    groups: &[u8],
    counts: &[u64],
    seed: u64,
    min_count: u64,
    mut selected: Vec<u32>,
    kept: &[u64],
) -> Option<Vec<u32>> {
    // The threshold survivors already include every hash below the cutoff.
    // If a group misses its floor, merge in that group's globally lowest
    // hashes. Bounded max-heaps retain only the required floor rows rather
    // than materializing a pool for every source row.
    let n_groups = counts.len();
    let floors: Vec<usize> = counts
        .iter()
        .map(|&count| min_count.min(count) as usize)
        .collect();
    if floors
        .iter()
        .zip(kept)
        .any(|(&floor, &count)| count < floor as u64)
    {
        let deficient: Vec<bool> = floors
            .iter()
            .zip(kept)
            .map(|(&floor, &count)| count < floor as u64)
            .collect();
        let mut lowest: Vec<BinaryHeap<(u64, u32)>> =
            (0..n_groups).map(|_| BinaryHeap::new()).collect();
        for (row, &group) in groups.iter().enumerate() {
            let group = group as usize;
            if group >= n_groups {
                return None;
            }
            if !deficient[group] {
                continue;
            }
            let candidate = (splitmix64(row as u64, seed), row as u32);
            let heap = &mut lowest[group];
            if heap.len() < floors[group] {
                heap.push(candidate);
            } else if heap.peek().is_some_and(|largest| candidate < *largest) {
                heap.pop();
                heap.push(candidate);
            }
        }
        for heap in lowest {
            selected.extend(heap.into_iter().map(|(_, row)| row));
        }
        selected.sort_unstable();
        selected.dedup();
    }
    Some(selected)
}

/// Full-domain categorical density first paint. The grid is identical to
/// [`bin_2d`], while sampled rows are identical to
/// [`stratified_sample_range_u8_counted`]. Interleaving the independent work
/// avoids a second source-sized traversal and retains bounded sample scratch.
#[allow(clippy::too_many_arguments)]
pub fn bin_2d_stratified_sample_range_u8_counted(
    x: &[f64],
    y: &[f64],
    groups: &[u8],
    counts: &[u64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    seed: u64,
    fraction: f64,
    min_count: u64,
    out: &mut [f32],
) -> Option<Vec<u32>> {
    assert_eq!(x.len(), y.len());
    assert_eq!(x.len(), groups.len());
    assert_eq!(out.len(), w * h);
    assert!(w > 0 && h > 0 && x1_gt_x0(x0, x1) && x1_gt_x0(y0, y1));
    if counts.is_empty()
        || counts.len() > 256
        || groups.len() > u32::MAX as usize
        || counts
            .iter()
            .try_fold(0u64, |sum, &count| sum.checked_add(count))?
            != groups.len() as u64
    {
        return None;
    }
    if groups.is_empty() {
        out.fill(0.0);
        return Some(Vec::new());
    }
    let thresholds: Vec<u64> = counts
        .iter()
        .map(|&count| sample_threshold(fraction * (groups.len() as f64 / count as f64).sqrt()))
        .collect();
    let threads = bin_2d_threads(x.len(), w * h);
    bin_2d_stratified_sample_range_u8_impl(
        x,
        y,
        groups,
        counts,
        &thresholds,
        x0,
        x1,
        y0,
        y1,
        w,
        h,
        seed,
        min_count,
        threads,
        out,
    )
}

#[allow(clippy::too_many_arguments)]
fn bin_2d_stratified_sample_range_u8_scan(
    x: &[f64],
    y: &[f64],
    groups: &[u8],
    thresholds: &[u64],
    base: usize,
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    seed: u64,
    grid: &mut [u32],
) -> Option<(Vec<u32>, Vec<u64>)> {
    let sx = w as f64 / (x1 - x0);
    let sy = h as f64 / (y1 - y0);
    let mut selected = Vec::new();
    let mut kept = vec![0u64; thresholds.len()];
    for i in 0..x.len() {
        let row = base + i;
        let group = groups[i] as usize;
        let threshold = *thresholds.get(group)?;
        if splitmix64(row as u64, seed) <= threshold {
            selected.push(row as u32);
            kept[group] += 1;
        }
        let xv = x[i];
        let yv = y[i];
        if !xv.is_finite() || !yv.is_finite() || xv < x0 || xv >= x1 || yv < y0 || yv >= y1 {
            continue;
        }
        let cx = (((xv - x0) * sx) as usize).min(w - 1);
        let cy = (((yv - y0) * sy) as usize).min(h - 1);
        grid[cy * w + cx] = grid[cy * w + cx].saturating_add(1);
    }
    Some((selected, kept))
}

#[allow(clippy::too_many_arguments)]
fn bin_2d_stratified_sample_range_u8_impl(
    x: &[f64],
    y: &[f64],
    groups: &[u8],
    counts: &[u64],
    thresholds: &[u64],
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    w: usize,
    h: usize,
    seed: u64,
    min_count: u64,
    threads: usize,
    out: &mut [f32],
) -> Option<Vec<u32>> {
    let n = x.len();
    if threads <= 1 || n < threads {
        let mut grid = vec![0u32; w * h];
        let (selected, kept) = bin_2d_stratified_sample_range_u8_scan(
            x, y, groups, thresholds, 0, x0, x1, y0, y1, w, h, seed, &mut grid,
        )?;
        for (cell, count) in out.iter_mut().zip(grid) {
            *cell = count as f32;
        }
        return complete_stratified_sample_range(groups, counts, seed, min_count, selected, &kept);
    }

    let chunk = n.div_ceil(threads);
    type Part = (Vec<u32>, Vec<u32>, Vec<u64>);
    let parts = std::thread::scope(|scope| -> Option<Vec<Part>> {
        let handles: Vec<_> = x
            .chunks(chunk)
            .zip(y.chunks(chunk))
            .zip(groups.chunks(chunk))
            .enumerate()
            .map(|(thread, ((xs, ys), group_part))| {
                let base = thread * chunk;
                scope.spawn(move || -> Option<Part> {
                    let mut grid = vec![0u32; w * h];
                    let (selected, kept) = bin_2d_stratified_sample_range_u8_scan(
                        xs, ys, group_part, thresholds, base, x0, x1, y0, y1, w, h, seed, &mut grid,
                    )?;
                    Some((grid, selected, kept))
                })
            })
            .collect();
        let mut parts = Vec::with_capacity(handles.len());
        for handle in handles {
            parts.push(
                handle
                    .join()
                    .expect("bin_2d_stratified_sample_range worker panicked")?,
            );
        }
        Some(parts)
    })?;

    let cell_chunk = (w * h).div_ceil(threads);
    std::thread::scope(|scope| {
        for (part_index, out_part) in out.chunks_mut(cell_chunk).enumerate() {
            let base = part_index * cell_chunk;
            let parts = &parts;
            scope.spawn(move || {
                for (offset, cell) in out_part.iter_mut().enumerate() {
                    let count: u64 = parts
                        .iter()
                        .map(|(grid, _, _)| u64::from(grid[base + offset]))
                        .sum();
                    *cell = count as f32;
                }
            });
        }
    });

    let selected_len = parts.iter().map(|(_, rows, _)| rows.len()).sum();
    let mut selected = Vec::with_capacity(selected_len);
    let mut kept = vec![0u64; counts.len()];
    for (_, rows, part_kept) in parts {
        selected.extend(rows);
        for (total, part) in kept.iter_mut().zip(part_kept) {
            *total += part;
        }
    }
    complete_stratified_sample_range(groups, counts, seed, min_count, selected, &kept)
}

fn sample_mask_impl<T: Copy + Sync + Into<u64>>(
    ids: &[T],
    seed: u64,
    threshold: u64,
    threads: usize,
    out: &mut [u8],
) {
    if threads <= 1 || ids.len() < 2 {
        for (o, &id) in out.iter_mut().zip(ids) {
            *o = u8::from(splitmix64(id.into(), seed) <= threshold);
        }
        return;
    }
    let per = ids.len().div_ceil(threads);
    std::thread::scope(|s| {
        for (seg_ids, seg_out) in ids.chunks(per).zip(out.chunks_mut(per)) {
            s.spawn(move || {
                for (o, &id) in seg_out.iter_mut().zip(seg_ids) {
                    *o = u8::from(splitmix64(id.into(), seed) <= threshold);
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
pub fn stratified_sample_mask<T: Copy + Sync + Into<u64>>(
    ids: &[T],
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
    let threads = if n_groups <= 1024 {
        par_threads(ids.len())
    } else {
        1
    };
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
                        let keep = splitmix64(id.into(), seed) <= thresholds_ref[g as usize];
                        *o = u8::from(keep);
                        kept[g as usize] += u64::from(keep);
                    }
                    kept
                })
            })
            .collect();
        let mut kept = vec![0u64; n_groups];
        for h in handles {
            for (t, p) in kept
                .iter_mut()
                .zip(h.join().expect("keep-pass worker panicked"))
            {
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
                pools[g as usize].push((splitmix64(id.into(), seed), i));
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
fn histogram_uniform_impl(data: &[f64], lo: f64, hi: f64, threads: usize, out: &mut [f64]) -> u64 {
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
    let norm_one = move |dst: &mut f32, v: f64| {
        *dst = normalize_one_f32(v, lo, hi, nan_value);
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

/// Scalar form shared by bulk payload normalization and the rasterizer's
/// borrowed-f64 heatmap sampler. Keeping the f32 rounding here is what makes
/// the direct static path pixel-identical to the browser payload path.
pub(crate) fn normalize_one_f32(value: f64, lo: f64, hi: f64, nan_value: f32) -> f32 {
    if value.is_finite() {
        (((value - lo) / (hi - lo)).clamp(0.0, 1.0)) as f32
    } else {
        nan_value
    }
}

/// Count rows that satisfy a compact validity rule across parallel f64
/// columns. Bit `j` in `positive_mask` upgrades column `j` from "finite" to
/// "finite and > 0" (log-axis filtering). The common all-valid query performs
/// one allocation-free, parallel pass and lets Python keep identity selection
/// without building boolean temporaries or an N-entry index array.
pub fn valid_row_count_f64(columns: &[&[f64]], positive_mask: u64) -> Option<usize> {
    let first = *columns.first()?;
    if columns.len() > 64
        || first.len() > u32::MAX as usize
        || columns.iter().any(|column| column.len() != first.len())
    {
        return None;
    }
    let len = first.len();
    let threads = par_threads(len).min(len.max(1));
    if threads <= 1 || len < threads {
        return Some(valid_row_count_segment(columns, positive_mask, 0, len));
    }
    let chunk = len.div_ceil(threads);
    Some(std::thread::scope(|scope| {
        let handles: Vec<_> = (0..threads)
            .filter_map(|thread| {
                let start = thread * chunk;
                let stop = (start + chunk).min(len);
                (start < stop).then(|| {
                    scope
                        .spawn(move || valid_row_count_segment(columns, positive_mask, start, stop))
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().expect("valid-row worker panicked"))
            .sum()
    }))
}

#[inline(always)]
fn valid_row_f64(columns: &[&[f64]], positive_mask: u64, row: usize) -> bool {
    columns.iter().enumerate().all(|(column_index, column)| {
        let value = column[row];
        value.is_finite() && (positive_mask & (1u64 << column_index) == 0 || value > 0.0)
    })
}

fn valid_row_count_segment(
    columns: &[&[f64]],
    positive_mask: u64,
    start: usize,
    stop: usize,
) -> usize {
    (start..stop)
        .filter(|&row| valid_row_f64(columns, positive_mask, row))
        .count()
}

/// Write ascending valid row IDs into caller storage. Callers query
/// [`valid_row_count_f64`] first and provide that exact capacity; the uncommon
/// filtered case deliberately uses a single serial write pass, avoiding a
/// second source-sized temporary or retaining an oversized output allocation.
pub fn valid_row_indices_f64(
    columns: &[&[f64]],
    positive_mask: u64,
    out: &mut [u32],
) -> Option<usize> {
    let first = *columns.first()?;
    if columns.len() > 64
        || first.len() > u32::MAX as usize
        || columns.iter().any(|column| column.len() != first.len())
    {
        return None;
    }
    let mut written = 0usize;
    for row in 0..first.len() {
        if valid_row_f64(columns, positive_mask, row) {
            if written < out.len() {
                out[written] = row as u32;
            }
            written += 1;
        }
    }
    Some(written)
}

/// Parallel validity selection into an N-row scratch buffer. Workers write
/// disjoint source-aligned segments, then compact them in row order exactly as
/// [`range_indices_impl`] does. This is used only after the allocation-free
/// count query found rejected rows; the Python wrapper shrinks the scratch to
/// the exact retained length before returning it.
pub fn valid_row_indices_parallel_f64(
    columns: &[&[f64]],
    positive_mask: u64,
    out: &mut [u32],
) -> Option<usize> {
    let first = *columns.first()?;
    let len = first.len();
    if columns.len() > 64
        || len > u32::MAX as usize
        || out.len() < len
        || columns.iter().any(|column| column.len() != len)
    {
        return None;
    }
    let threads = par_threads(len).min(len.max(1));
    if threads <= 1 || len < threads {
        return valid_row_indices_f64(columns, positive_mask, out);
    }
    let chunk = len.div_ceil(threads);
    let counts: Vec<usize> = std::thread::scope(|scope| {
        let handles: Vec<_> = out[..len]
            .chunks_mut(chunk)
            .enumerate()
            .map(|(thread, output)| {
                let start = thread * chunk;
                let stop = (start + output.len()).min(len);
                scope.spawn(move || {
                    let mut written = 0usize;
                    for row in start..stop {
                        if valid_row_f64(columns, positive_mask, row) {
                            output[written] = row as u32;
                            written += 1;
                        }
                    }
                    written
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().expect("valid-row worker panicked"))
            .collect()
    });
    let mut write = counts.first().copied().unwrap_or(0);
    for (thread, &count) in counts.iter().enumerate().skip(1) {
        let start = thread * chunk;
        out.copy_within(start..start + count, write);
        write += count;
    }
    Some(write)
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

/// Log-encode a non-negative density grid for the client's R8 texture.
/// Zeros remain exact and every occupied cell maps to at least one.
pub fn density_log_u8_into(grid: &[f32], out: &mut [u8]) -> f64 {
    assert_eq!(grid.len(), out.len());
    let max = f64::from(grid_max(grid));
    if max <= 0.0 {
        out.fill(0);
        return 0.0;
    }
    let denom = max.ln_1p();
    for (&value, encoded) in grid.iter().zip(out.iter_mut()) {
        let value = f64::from(value);
        if value > 0.0 && value.is_finite() {
            let quantized = (255.0 * value.ln_1p() / denom).round_ties_even();
            *encoded = quantized.clamp(1.0, 255.0) as u8;
        } else {
            *encoded = 0;
        }
    }
    max
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
/// Large inputs fan out over overlapping segments (the pair AND is
/// order-independent); a shared flag propagates the early exit.
pub fn is_sorted_f64(data: &[f64]) -> bool {
    is_sorted_f64_impl(data, par_threads(data.len()))
}

fn is_sorted_f64_impl(data: &[f64], threads: usize) -> bool {
    let n = data.len();
    if threads <= 1 || n < threads * 2 {
        return data.windows(2).all(|pair| pair[1] >= pair[0]);
    }
    let violated = std::sync::atomic::AtomicBool::new(false);
    let per = n.div_ceil(threads);
    std::thread::scope(|scope| {
        let violated = &violated;
        for thread in 0..threads {
            // Segments overlap by one element so every boundary pair is
            // checked by exactly one worker.
            let start = thread * per;
            let stop = (start + per + 1).min(n);
            if start + 1 >= stop {
                continue;
            }
            let seg = &data[start..stop];
            scope.spawn(move || {
                let last = seg.len() - 1;
                let mut lo = 0usize;
                while lo < last {
                    if violated.load(std::sync::atomic::Ordering::Relaxed) {
                        return;
                    }
                    let hi = (lo + (1 << 15)).min(last);
                    if !seg[lo..=hi].windows(2).all(|pair| pair[1] >= pair[0]) {
                        violated.store(true, std::sync::atomic::Ordering::Relaxed);
                        return;
                    }
                    lo = hi;
                }
            });
        }
    });
    !violated.into_inner()
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
    fn factorize_fixed_preserves_first_seen_codes_and_full_record_identity() {
        let rows = [b"ab\0", b"xy\0", b"ab\0", b"abx", b"xy\0"];
        let data: Vec<u8> = rows.into_iter().flatten().copied().collect();
        let mut codes = [u32::MAX; 5];
        let mut unique = [u32::MAX; 5];
        let count = factorize_fixed_into(&data, 3, &mut codes, &mut unique);
        assert_eq!(count, Some(3));
        assert_eq!(codes, [0, 1, 0, 2, 1]);
        assert_eq!(&unique[..3], &[0, 1, 3]);

        assert_eq!(
            factorize_fixed_into(&data, 0, &mut codes, &mut unique),
            None
        );
        assert_eq!(
            factorize_fixed_into(&data[..14], 3, &mut codes, &mut unique),
            None
        );
        assert_eq!(
            factorize_fixed_into(&data, 3, &mut codes[..4], &mut unique),
            None
        );

        let mut compact_codes = [u8::MAX; 5];
        let mut compact_unique = [u32::MAX; 3];
        assert_eq!(
            factorize_fixed_u8_into(&data, 3, &mut compact_codes, &mut compact_unique),
            Some(3)
        );
        assert_eq!(compact_codes, [0, 1, 0, 2, 1]);
        let mut counted_codes = [u8::MAX; 5];
        let mut counted_unique = [u32::MAX; 3];
        let mut compact_counts = [u64::MAX; 3];
        assert_eq!(
            factorize_fixed_u8_counts_into(
                &data,
                3,
                &mut counted_codes,
                &mut counted_unique,
                &mut compact_counts,
            ),
            Some(3)
        );
        assert_eq!(counted_codes, [0, 1, 0, 2, 1]);
        assert_eq!(counted_unique, [0, 1, 3]);
        assert_eq!(compact_counts, [2, 2, 1]);
        assert!(remap_u8_inplace(&mut compact_codes, &[2, 0, 1]));
        assert_eq!(compact_codes, [2, 0, 2, 1, 0]);
        assert!(!remap_u8_inplace(&mut compact_codes, &[0, 1]));

        let mut too_few_unique = [u32::MAX; 2];
        assert_eq!(
            factorize_fixed_u8_into(&data, 3, &mut compact_codes, &mut too_few_unique),
            None
        );
    }

    #[test]
    fn factorize_fixed_u8_matches_general_across_record_widths() {
        for width in [1usize, 2, 3, 4, 8, 9, 16, 31] {
            let n_groups = if width == 1 { 200 } else { 256 };
            let n = 20_003usize;
            let mut data = Vec::with_capacity(n * width);
            for row in 0..n {
                let group = (row * 73 + 19) % n_groups;
                for byte in 0..width {
                    let value = if byte < 8 {
                        ((group as u64).rotate_left((byte * 7) as u32) >> (byte * 8)) as u8
                    } else {
                        (group as u8).wrapping_mul(31).wrapping_add(byte as u8)
                    };
                    data.push(value);
                }
            }
            let mut full_codes = vec![u32::MAX; n];
            let mut full_unique = vec![u32::MAX; n];
            let full_count =
                factorize_fixed_into(&data, width, &mut full_codes, &mut full_unique).unwrap();
            let mut compact_codes = vec![u8::MAX; n];
            let mut compact_unique = vec![u32::MAX; 256];
            let compact_count =
                factorize_fixed_u8_into(&data, width, &mut compact_codes, &mut compact_unique)
                    .unwrap();
            assert_eq!(compact_count, full_count, "width={width}");
            assert_eq!(
                compact_codes
                    .iter()
                    .map(|&code| u32::from(code))
                    .collect::<Vec<_>>(),
                full_codes,
                "width={width}",
            );
            assert_eq!(
                &compact_unique[..compact_count],
                &full_unique[..full_count],
                "width={width}",
            );
        }
    }

    #[test]
    fn factorize_fixed_u8_parallel_merges_late_categories_in_first_seen_order() {
        let width = 4usize;
        let n = 1_100_123usize;
        let mut data = vec![0u8; n * width];
        for row in 5000..n {
            let group = match row {
                5000..6000 => 3u32,
                6000..7000 => 2,
                7000 => 1,
                _ => ((row * 17) % 4) as u32,
            };
            data[row * width..(row + 1) * width].copy_from_slice(&group.to_ne_bytes());
        }
        let mut full_codes = vec![u32::MAX; n];
        let mut full_unique = vec![u32::MAX; n];
        let full_count =
            factorize_fixed_into(&data, width, &mut full_codes, &mut full_unique).unwrap();
        let mut compact_codes = vec![u8::MAX; n];
        let compact =
            factorize_fixed_u8_parallel(&data, width, &mut compact_codes, 256, 4).unwrap();

        assert_eq!(compact.codebook.len, full_count);
        assert_eq!(
            compact_codes
                .iter()
                .map(|&code| u32::from(code))
                .collect::<Vec<_>>(),
            full_codes,
        );
        assert_eq!(
            &compact.codebook.first_indices[..compact.codebook.len],
            &full_unique[..full_count],
        );
        assert_eq!(&compact.codebook.first_indices[..4], &[0, 5000, 6000, 7000]);
        assert_eq!(compact.counts[..4].iter().sum::<u64>(), n as u64);

        let mut insufficient_codes = vec![u8::MAX; n];
        assert!(
            factorize_fixed_u8_parallel(&data, width, &mut insufficient_codes, 3, 4,).is_none()
        );
    }

    #[test]
    fn factorize_byte_values_parallel_merges_late_values_and_counts() {
        let n = 1_100_123usize;
        let mut data = vec![0u8; n];
        data[5000..6000].fill(3);
        data[6000..7000].fill(2);
        data[7000] = 1;
        for (row, value) in data.iter_mut().enumerate().skip(7001) {
            *value = ((row * 17) % 4) as u8;
        }
        let mut full_codes = vec![u32::MAX; n];
        let mut full_unique = vec![u32::MAX; n];
        let full_count = factorize_fixed_into(&data, 1, &mut full_codes, &mut full_unique).unwrap();
        let mut compact_codes = vec![u8::MAX; n];
        let compact = factorize_byte_values_parallel(&data, &mut compact_codes, 256, 4).unwrap();

        assert_eq!(compact.codebook.len, full_count);
        assert_eq!(
            compact_codes
                .iter()
                .map(|&code| u32::from(code))
                .collect::<Vec<_>>(),
            full_codes,
        );
        assert_eq!(&compact.codebook.first_indices[..4], &[0, 5000, 6000, 7000]);
        for code in 0..compact.codebook.len {
            let expected = full_codes
                .iter()
                .filter(|&&value| value as usize == code)
                .count() as u64;
            assert_eq!(compact.counts[code], expected);
        }

        let mut insufficient_codes = vec![u8::MAX; n];
        assert!(factorize_byte_values_parallel(&data, &mut insufficient_codes, 3, 4).is_none());
    }

    #[test]
    fn factorize_unicode1_direct_table_preserves_endian_order_and_late_values() {
        let values = ['β' as u32, 'a' as u32, 'β' as u32, 0, 'é' as u32];
        let mut codes = [u8::MAX; 5];
        let mut unique = [u32::MAX; 5];
        let mut counts = [u64::MAX; 5];
        assert_eq!(
            factorize_unicode1_u8_counts_into(&values, false, &mut codes, &mut unique, &mut counts,),
            Some(4),
        );
        assert_eq!(codes, [0, 1, 0, 2, 3]);
        assert_eq!(&unique[..4], &[0, 1, 3, 4]);
        assert_eq!(&counts[..4], &[2, 1, 1, 1]);

        let swapped = values.map(u32::swap_bytes);
        let mut swapped_codes = [u8::MAX; 5];
        assert_eq!(
            factorize_unicode1_u8_counts_into(
                &swapped,
                true,
                &mut swapped_codes,
                &mut unique,
                &mut counts,
            ),
            Some(4),
        );
        assert_eq!(swapped_codes, codes);

        let mut late = vec![0u32; 1_100_123];
        late[5000..6000].fill('猫' as u32);
        late[6000..7000].fill('β' as u32);
        late[7000] = 'a' as u32;
        for (row, value) in late.iter_mut().enumerate().skip(7001) {
            *value = [0, '猫' as u32, 'β' as u32, 'a' as u32][row % 4];
        }
        let mut late_codes = vec![u8::MAX; late.len()];
        let mut late_unique = [u32::MAX; 4];
        let mut late_counts = [0u64; 4];
        assert_eq!(
            factorize_unicode1_u8_counts_into(
                &late,
                false,
                &mut late_codes,
                &mut late_unique,
                &mut late_counts,
            ),
            Some(4),
        );
        assert_eq!(late_unique, [0, 5000, 6000, 7000]);
        assert_eq!(late_counts.iter().sum::<u64>(), late.len() as u64);
        assert_eq!(late_codes[5000], 1);
        assert_eq!(late_codes[6000], 2);
        assert_eq!(late_codes[7000], 3);

        let invalid = [0x11_0000u32];
        assert_eq!(
            factorize_unicode1_u8_counts_into(
                &invalid,
                false,
                &mut codes[..1],
                &mut unique[..1],
                &mut counts[..1],
            ),
            None,
        );
    }

    #[test]
    fn stacked_bounds_zero_and_symmetric() {
        let values = [1.0, 2.0, 3.0, 4.0, 10.0, 20.0];
        let mut lower = [0.0; 6];
        let mut upper = [0.0; 6];
        assert!(stacked_bounds_into(
            &values, 2, 3, 0, &mut lower, &mut upper
        ));
        assert_eq!(lower, [0.0, 0.0, 0.0, 1.0, 2.0, 3.0]);
        assert_eq!(upper, [1.0, 2.0, 3.0, 5.0, 12.0, 23.0]);
        assert!(stacked_bounds_into(
            &values, 2, 3, 1, &mut lower, &mut upper
        ));
        assert_eq!(lower, [-2.5, -6.0, -11.5, -1.5, -4.0, -8.5]);
        assert_eq!(upper, [-1.5, -4.0, -8.5, 2.5, 6.0, 11.5]);
    }

    #[test]
    fn histogram2d_includes_right_edge_and_weights() {
        let x = [0.0, 0.5, 1.0, 2.0, f64::NAN];
        let y = [0.0, 0.5, 1.0, 2.0, 0.5];
        let weights = [1.0, 2.0, 3.0, 4.0, 100.0];
        let edges = [0.0, 1.0, 2.0];
        let mut out = [0.0; 4];
        assert!(histogram2d_into(
            &x,
            &y,
            Some(&weights),
            &edges,
            &edges,
            &mut out
        ));
        assert_eq!(out, [3.0, 0.0, 0.0, 7.0]);
    }

    #[test]
    fn quad_mesh_expands_rectilinear_and_compacts_missing_cells() {
        let x = [0.0, 1.0, 3.0];
        let y = [10.0, 20.0];
        let values = [2.0, f64::NAN];
        let mut x0 = [0.0; 4];
        let mut y0 = [0.0; 4];
        let mut x1 = [0.0; 4];
        let mut y1 = [0.0; 4];
        let mut x2 = [0.0; 4];
        let mut y2 = [0.0; 4];
        let mut scalar = [0.0; 4];
        let written = quad_mesh_triangles_into(
            &x,
            &y,
            &values,
            1,
            2,
            0,
            &mut x0,
            &mut y0,
            &mut x1,
            &mut y1,
            &mut x2,
            &mut y2,
            &mut scalar,
        );
        assert_eq!(written, Some(2));
        assert_eq!(&scalar[..2], &[2.0, 2.0]);
        assert_eq!(
            (x0[0], y0[0], x1[0], y1[0], x2[0], y2[0]),
            (0.0, 10.0, 1.0, 10.0, 1.0, 20.0)
        );
        assert_eq!(
            (x0[1], y0[1], x1[1], y1[1], x2[1], y2[1]),
            (0.0, 10.0, 1.0, 20.0, 0.0, 20.0)
        );
    }

    #[test]
    fn vector_segments_compact_invalid_vectors() {
        let x = [0.0, f64::NAN];
        let y = [0.0, 1.0];
        let u = [2.0, 1.0];
        let v = [0.0, 1.0];
        let mut x0 = [0.0; 6];
        let mut x1 = [0.0; 6];
        let mut y0 = [0.0; 6];
        let mut y1 = [0.0; 6];
        let written = vector_segments_into(
            &x, &y, &u, &v, 1.0, 0, 0.2, &mut x0, &mut x1, &mut y0, &mut y1,
        );
        assert_eq!(written, Some(3));
        assert_eq!((x0[0], y0[0], x1[0], y1[0]), (0.0, 0.0, 2.0, 0.0));
    }

    #[test]
    fn weighted_ecdf_sorts_coalesces_and_normalizes() {
        let values = [3.0, 1.0, 2.0, 2.0, f64::NAN];
        let weights = [4.0, 1.0, 2.0, 3.0, 99.0];
        let mut x = [0.0; 5];
        let mut cumulative = [0.0; 5];
        let written = weighted_ecdf_into(&values, &weights, &mut x, &mut cumulative);
        assert_eq!(written, Some(3));
        assert_eq!(&x[..3], &[1.0, 2.0, 3.0]);
        assert_eq!(&cumulative[..3], &[0.1, 0.6, 1.0]);
    }

    #[test]
    fn streamlines_stay_inside_regular_grid() {
        let x = [-1.0, 0.0, 1.0];
        let y = [-1.0, 0.0, 1.0];
        let mut u = Vec::new();
        let mut v = Vec::new();
        for &yv in &y {
            for &xv in &x {
                u.push(-yv);
                v.push(xv);
            }
        }
        let lines = streamlines(&x, &y, &u, &v, 1.0, 100).expect("valid grid");
        assert!(!lines.is_empty());
        assert!(lines.iter().all(|&(x0, x1, y0, y1)| {
            (-1.0..=1.0).contains(&x0)
                && (-1.0..=1.0).contains(&x1)
                && (-1.0..=1.0).contains(&y0)
                && (-1.0..=1.0).contains(&y1)
        }));
    }

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
    fn marching_squares_uses_asymptotic_decider_for_ambiguous_cells() {
        let x = [0.0, 1.0];
        let y = [0.0, 1.0];
        let levels = [0.5];

        let extract = |z: &[f64; 4]| {
            let mut x0 = [0.0; 2];
            let mut x1 = [0.0; 2];
            let mut y0 = [0.0; 2];
            let mut y1 = [0.0; 2];
            let mut emitted_levels = [0.0; 2];
            let written = marching_squares_into(
                z,
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
            (x0, x1, y0, y1)
        };

        // Positive diagonal dominates: join bottom-right and top-left.
        let (x0, x1, y0, y1) = extract(&[3.0, 0.0, 0.0, 1.0]);
        assert_eq!(x0, [5.0 / 6.0, 0.5]);
        assert_eq!(x1, [1.0, 0.0]);
        assert_eq!(y0, [0.0, 1.0]);
        assert_eq!(y1, [0.5, 5.0 / 6.0]);

        // Negative diagonal dominates in the complementary mask: join
        // bottom-left and top-right.
        let (x0, x1, y0, y1) = extract(&[0.0, 3.0, 1.0, 0.0]);
        assert_eq!(x0, [0.0, 1.0]);
        assert_eq!(x1, [1.0 / 6.0, 0.5]);
        assert_eq!(y0, [0.5, 5.0 / 6.0]);
        assert_eq!(y1, [0.0, 1.0]);
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
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
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
    fn bin_2d_sample_range_matches_separate_kernels() {
        let n = 1_200_123;
        let mut x = Vec::with_capacity(n);
        let mut y = Vec::with_capacity(n);
        let mut state = 91u64;
        for i in 0..n {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            x.push(if i % 997 == 0 {
                f64::NAN
            } else {
                (state >> 11) as f64 / (1u64 << 53) as f64 * 200.0 - 100.0
            });
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            y.push((state >> 11) as f64 / (1u64 << 53) as f64 * 200.0 - 100.0);
        }
        let (x0, x1, y0, y1, w, h) = (-95.0, 95.0, -80.0, 80.0, 128, 96);
        let seed = 23;
        let threshold = sample_threshold(0.0075);
        let mut grid_ref = vec![0.0f32; w * h];
        bin_2d(&x, &y, x0, x1, y0, y1, w, h, &mut grid_ref);
        let sample_ref = sample_range_indices(n, seed, threshold);

        for threads in [1, 4] {
            let mut grid = vec![0.0f32; w * h];
            let chunks = bin_2d_sample_range_impl(
                &x, &y, x0, x1, y0, y1, w, h, seed, threshold, threads, &mut grid,
            );
            assert_eq!(grid, grid_ref, "grid threads={threads}");
            assert_eq!(chunks.concat(), sample_ref, "sample threads={threads}");
            let mut written = vec![0u32; sample_ref.len()];
            assert_eq!(
                write_selected_chunks(&chunks, &mut written),
                sample_ref.len()
            );
            assert_eq!(written, sample_ref, "direct write threads={threads}");
            assert_eq!(
                write_selected_chunks(&chunks, &mut written[..sample_ref.len() - 1]),
                sample_ref.len(),
                "undersized capacity still reports the exact length"
            );
        }
    }

    #[test]
    fn bin_2d_stratified_sample_range_matches_separate_kernels() {
        let n = 1_200_123;
        let x: Vec<f64> = (0..n).map(|row| row as f64 / n as f64).collect();
        let y: Vec<f64> = (0..n).map(|row| ((row as f64) * 0.000_017).sin()).collect();
        let mut groups = vec![0u8; n];
        for (row, group) in groups.iter_mut().enumerate() {
            *group = if row % 300_000 == 0 {
                3
            } else if row % 1_000 == 0 {
                2
            } else if row % 10 == 0 {
                1
            } else {
                0
            };
        }
        let mut counts = vec![0u64; 4];
        for &group in &groups {
            counts[group as usize] += 1;
        }
        let args = (0.0, 1.0, -1.0, 1.0, 128, 96);
        let seed = 29;
        let fraction = 0.000_01;
        let min_count = 3;
        let mut grid_ref = vec![0.0f32; args.4 * args.5];
        bin_2d(
            &x,
            &y,
            args.0,
            args.1,
            args.2,
            args.3,
            args.4,
            args.5,
            &mut grid_ref,
        );
        let selected_ref =
            stratified_sample_range_u8_counted(&groups, &counts, seed, fraction, min_count)
                .unwrap();

        let thresholds: Vec<u64> = counts
            .iter()
            .map(|&count| sample_threshold(fraction * (n as f64 / count as f64).sqrt()))
            .collect();
        for threads in [1, 4] {
            let mut grid = vec![0.0f32; args.4 * args.5];
            let selected = bin_2d_stratified_sample_range_u8_impl(
                &x,
                &y,
                &groups,
                &counts,
                &thresholds,
                args.0,
                args.1,
                args.2,
                args.3,
                args.4,
                args.5,
                seed,
                min_count,
                threads,
                &mut grid,
            )
            .unwrap();
            assert_eq!(grid, grid_ref, "grid threads={threads}");
            assert_eq!(selected, selected_ref, "sample threads={threads}");
        }
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
        assert!(
            kept > ids.len() / 128 && kept < ids.len() / 32,
            "kept {kept}"
        );
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

    #[test]
    fn sample_range_matches_materialized_mask() {
        let size = 1_100_123;
        let threshold = sample_threshold(0.0075);
        let ids: Vec<u64> = (0..size as u64).collect();
        let mut mask = vec![0u8; size];
        sample_mask(&ids, 23, threshold, &mut mask);
        let expected: Vec<u32> = mask
            .iter()
            .enumerate()
            .filter_map(|(index, &keep)| (keep != 0).then_some(index as u32))
            .collect();
        assert_eq!(sample_range_indices(size, 23, threshold), expected);
    }

    #[test]
    fn valid_row_indices_filter_finite_and_positive_columns() {
        let x = [1.0, 2.0, f64::NAN, 4.0, -5.0, 6.0];
        let y = [1.0, f64::INFINITY, 3.0, -4.0, 5.0, 6.0];
        let columns = [&x[..], &y[..]];
        assert_eq!(valid_row_count_f64(&columns, 0), Some(4));
        assert_eq!(valid_row_count_f64(&columns, 0b10), Some(3));
        let mut out = [u32::MAX; 3];
        assert_eq!(valid_row_indices_f64(&columns, 0b10, &mut out), Some(3));
        assert_eq!(out, [0, 4, 5]);
        let mut parallel = [u32::MAX; 6];
        assert_eq!(
            valid_row_indices_parallel_f64(&columns, 0b10, &mut parallel),
            Some(3)
        );
        assert_eq!(&parallel[..3], &[0, 4, 5]);
    }

    #[test]
    fn valid_row_indices_parallel_matches_serial() {
        let n = PAR_THRESHOLD + 137;
        let mut x: Vec<f64> = (0..n).map(|row| row as f64 - 10.0).collect();
        let mut y: Vec<f64> = (0..n).map(|row| row as f64 + 1.0).collect();
        for row in (0..n).step_by(997) {
            x[row] = f64::NAN;
        }
        for row in (0..n).step_by(1013) {
            y[row] = f64::INFINITY;
        }
        let columns = [&x[..], &y[..]];
        let mut serial = vec![u32::MAX; n];
        let mut parallel = vec![u32::MAX; n];
        let serial_count = valid_row_indices_f64(&columns, 0b01, &mut serial).unwrap();
        let parallel_count = valid_row_indices_parallel_f64(&columns, 0b01, &mut parallel).unwrap();
        assert_eq!(parallel_count, serial_count);
        assert_eq!(parallel[..parallel_count], serial[..serial_count]);
    }

    #[test]
    fn density_log_u8_preserves_zero_and_max() {
        let grid = [0.0f32, 1.0, 2.0, 10.0, 100.0];
        let mut out = [0u8; 5];
        assert_eq!(density_log_u8_into(&grid, &mut out), 100.0);
        assert_eq!(out[0], 0);
        assert!(out[1..].iter().all(|&value| value > 0));
        assert_eq!(out[4], 255);
    }

    #[test]
    fn density_rgba_maps_flips_and_preserves_empty_alpha() {
        let encoded = [0u8, 255, 128, 1];
        let stops = [[0u8, 10, 20], [100, 110, 120]];
        let mut out = [0u8; 16];
        assert!(density_rgba_into(
            &encoded, 2, 2, 100.0, &stops, 0.85, &mut out
        ));
        assert!(out[3] > 0);
        assert_eq!(out[11], 0);
        assert_eq!(&out[12..16], &[100, 110, 120, 216]);
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
    fn stratified_sample_range_u8_matches_materialized_mask() {
        let len = 1_100_123usize;
        let groups: Vec<u8> = (0..len)
            .map(|row| match row % 10_000 {
                0 => 3,
                value if value < 11 => 2,
                value if value < 1_011 => 1,
                _ => 0,
            })
            .collect();
        let ids: Vec<u64> = (0..len as u64).collect();
        for (fraction, min_count) in [(1.0 / 65_536.0, 3), (1.0 / 512.0, 1), (0.4, 0)] {
            let groups_u32: Vec<u32> = groups.iter().map(|&group| u32::from(group)).collect();
            let mut mask = vec![0u8; len];
            assert!(stratified_sample_mask(
                &ids,
                &groups_u32,
                4,
                29,
                fraction,
                min_count,
                &mut mask,
            ));
            let expected: Vec<u32> = mask
                .iter()
                .enumerate()
                .filter_map(|(row, &keep)| (keep != 0).then_some(row as u32))
                .collect();
            assert_eq!(
                stratified_sample_range_u8(&groups, 4, 29, fraction, min_count),
                Some(expected.clone()),
                "fraction={fraction} min_count={min_count}",
            );
            let counts = [
                groups.iter().filter(|&&group| group == 0).count() as u64,
                groups.iter().filter(|&&group| group == 1).count() as u64,
                groups.iter().filter(|&&group| group == 2).count() as u64,
                groups.iter().filter(|&&group| group == 3).count() as u64,
            ];
            assert_eq!(
                stratified_sample_range_u8_counted(&groups, &counts, 29, fraction, min_count,),
                Some(expected),
                "counted fraction={fraction} min_count={min_count}",
            );
        }
    }

    #[test]
    fn stratified_sample_range_u8_validates_group_domain() {
        assert_eq!(
            stratified_sample_range_u8(&[], 3, 0, 0.5, 1),
            Some(Vec::new())
        );
        assert_eq!(stratified_sample_range_u8(&[0, 2], 2, 0, 0.5, 1), None);
        assert_eq!(stratified_sample_range_u8(&[0], 0, 0, 0.5, 1), None);
        assert_eq!(stratified_sample_range_u8(&[0], 257, 0, 0.5, 1), None);
        assert_eq!(
            stratified_sample_range_u8_counted(&[0, 1], &[1, 0], 0, 0.5, 1),
            None,
        );
    }

    #[test]
    fn stratified_sample_mask_pins_rare_and_stays_monotonic() {
        let len = 8_104usize;
        let ids: Vec<u64> = (0..len as u64).collect();
        let groups: Vec<u32> = (0..len)
            .map(|i| {
                if i < 8_000 {
                    0
                } else if i < 8_100 {
                    1
                } else {
                    2
                }
            })
            .collect();
        let mut lo = vec![0u8; len];
        let mut hi = vec![0u8; len];
        let base = 1.0 / 4096.0;
        assert!(stratified_sample_mask(
            &ids, &groups, 3, 23, base, 1, &mut lo
        ));
        assert!(stratified_sample_mask(
            &ids,
            &groups,
            3,
            23,
            base * 32.0,
            1,
            &mut hi
        ));
        for g in 0..3u32 {
            let kept: u64 = lo
                .iter()
                .zip(&groups)
                .filter(|&(_, &gg)| gg == g)
                .map(|(&k, _)| u64::from(k))
                .sum();
            assert!(kept >= 1, "group {g} lost its floor row");
        }
        assert!(
            lo.iter().zip(&hi).all(|(&a, &b)| a <= b),
            "mask not monotonic"
        );
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
        assert!(!stratified_sample_mask(
            &ids, &groups, 2, 0, 0.5, 1, &mut out
        ));
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
    fn zone_maps_pair_matches_separate_parallel_results() {
        let n = 1_100_123usize;
        let mut x: Vec<f64> = (0..n).map(|row| (row as f64 * 0.001).sin()).collect();
        let mut y: Vec<f64> = (0..n).map(|row| (row as f64 * 0.003).cos()).collect();
        x[997] = f64::NAN;
        y[991] = f64::INFINITY;
        let x_expected = zone_maps(&x, DEFAULT_CHUNK);
        let y_expected = zone_maps(&y, DEFAULT_CHUNK);
        let (x_actual, y_actual) = zone_maps_pair(&x, &y, DEFAULT_CHUNK).unwrap();
        assert_eq!(x_actual, x_expected);
        assert_eq!(y_actual, y_expected);
        assert!(zone_maps_pair(&x, &y[..n - 1], DEFAULT_CHUNK).is_none());
        assert!(zone_maps_pair(&x, &y, 0).is_none());
    }

    #[test]
    fn zone_map_fanout_tracks_complete_chunks_and_codspeed() {
        let chunk = 65_536;
        assert_eq!(zone_map_threads_for(chunk, chunk, 18, false), 1);
        assert_eq!(zone_map_threads_for(2 * chunk - 1, chunk, 18, false), 1);
        assert_eq!(zone_map_threads_for(2 * chunk, chunk, 18, false), 2);
        assert_eq!(zone_map_threads_for(200_000, chunk, 18, false), 4);
        assert_eq!(zone_map_threads_for(10 * chunk, chunk, 18, false), 10);
        assert_eq!(
            zone_map_threads_for(100 * chunk, chunk, 64, false),
            MAX_ROW_THREADS
        );
        assert_eq!(zone_map_threads_for(10 * chunk, chunk, 3, false), 3);
        assert_eq!(zone_map_threads_for(10 * chunk, chunk, 1, false), 1);
        assert_eq!(zone_map_threads_for(10 * chunk, chunk, 18, true), 1);
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
    fn bin_2d_threads_grid_aware() {
        // Below the fan-out threshold: serial regardless of grid size.
        assert_eq!(bin_2d_threads(PAR_THRESHOLD - 1, 4), 1);
        // Past the threshold with a screen-sized grid the points-per-cell
        // ratio exceeds the core cap: same fan-out as the 1-D row scans.
        assert_eq!(bin_2d_threads(1 << 23, 512 * 384), par_threads(1 << 23));
        // Ratio between 1 and the core cap: fan-out tracks points per cell
        // (min against par_threads so the assert holds on any core count).
        assert_eq!(
            bin_2d_threads(1 << 21, 1 << 20),
            2.min(par_threads(1 << 21))
        );
        // Grid at least as large as the point count (tile-pyramid base level
        // shape): per-thread grids + merge dwarf the scan — stay serial.
        assert_eq!(bin_2d_threads(1 << 20, 1 << 20), 1);
        assert_eq!(bin_2d_threads(2_100_000, 2048 * 2048), 1);
        assert_eq!(par_threads_for(PAR_THRESHOLD - 1, 64), 1);
        assert_eq!(par_threads_for(PAR_THRESHOLD, 64), MAX_ROW_THREADS);
        assert_eq!(par_threads_for(PAR_THRESHOLD, 1), 1);
    }

    #[test]
    fn srgb_linear_table_roundtrips_every_byte() {
        for (byte, &linear) in SRGB_TO_LINEAR_U16.iter().enumerate() {
            assert_eq!(
                linear_u16_to_srgb_u8(linear),
                byte as u8,
                "table entry {byte} must invert exactly"
            );
        }
        assert_eq!(linear_u16_to_srgb_u8(0), 0);
        assert_eq!(linear_u16_to_srgb_u8(u16::MAX), 255);
        assert!(
            SRGB_TO_LINEAR_U16.windows(2).all(|p| p[1] > p[0]),
            "strictly increasing — the inverse search depends on it"
        );
    }

    const MC_RED_BLUE: [[u8; 4]; 2] = [[255, 0, 0, 255], [0, 0, 255, 255]];

    #[test]
    fn bin_2d_mean_color_places_pure_and_mixed_cells() {
        // 2×2 grid over the unit square: bottom-left one red point;
        // bottom-right one red + one blue; NaN and out-of-window skipped.
        let x = [0.1, 0.6, 0.9, f64::NAN, 2.0];
        let y = [0.1, 0.1, 0.1, 0.5, 0.5];
        let idx = [0u8, 0, 1, 0, 1];
        let colors = BinColorSource::Indexed {
            idx: &idx,
            lut: &MC_RED_BLUE,
        };
        let mut out = vec![0u8; 2 * 2 * 4];
        bin_2d_mean_color(&x, &y, &colors, 0.0, 1.0, 0.0, 1.0, 2, 2, &mut out);
        assert_eq!(&out[0..4], &[255, 0, 0, 255], "pure cell keeps exact color");
        // Half red + half blue averaged in linear light: 65535/2 → 32768,
        // whose nearest sRGB byte is 188 — brighter than the sRGB-space
        // average (128), the physically downsampled mix.
        assert_eq!(&out[4..8], &[188, 0, 188, 255]);
        assert_eq!(&out[8..16], &[0u8; 8], "empty cells stay fully zero");
    }

    #[test]
    fn bin_2d_mean_color_weights_by_alpha() {
        // A faint red (alpha 51 = 20%) and an opaque blue share a cell: the
        // mean must lean blue 5:1, and the cell alpha is the plain mean.
        let x = [0.5, 0.5];
        let y = [0.5, 0.5];
        let lut = [[255, 0, 0, 51], [0, 0, 255, 255]];
        let idx = [0u8, 1];
        let colors = BinColorSource::Indexed {
            idx: &idx,
            lut: &lut,
        };
        let mut out = vec![0u8; 4];
        bin_2d_mean_color(&x, &y, &colors, 0.0, 1.0, 0.0, 1.0, 1, 1, &mut out);
        let expected_red = linear_u16_to_srgb_u8(((51u64 * 65535 + 153) / 306) as u16);
        let expected_blue = linear_u16_to_srgb_u8(((255u64 * 65535 + 153) / 306) as u16);
        assert_eq!(out, vec![expected_red, 0, expected_blue, 153]);
        assert!(out[2] > out[0], "opaque blue outweighs faint red");

        // All-invisible cell: count > 0 but zero weight — never invent color.
        let ghost_lut = [[255, 0, 0, 0]];
        let ghost_idx = [0u8, 0];
        let ghost = BinColorSource::Indexed {
            idx: &ghost_idx,
            lut: &ghost_lut,
        };
        bin_2d_mean_color(&x, &y, &ghost, 0.0, 1.0, 0.0, 1.0, 1, 1, &mut out);
        assert_eq!(out, vec![0, 0, 0, 0]);
    }

    #[test]
    fn bin_2d_mean_color_rgba_source_and_lut_wrap() {
        let x = [0.5, 0.5];
        let y = [0.5, 0.5];
        let rgba: Vec<u8> = vec![255, 0, 0, 255, 0, 0, 255, 255];
        let mut direct = vec![0u8; 4];
        bin_2d_mean_color(
            &x,
            &y,
            &BinColorSource::Rgba(&rgba),
            0.0,
            1.0,
            0.0,
            1.0,
            1,
            1,
            &mut direct,
        );
        assert_eq!(direct, vec![188, 0, 188, 255]);
        // Indices wrap modulo the LUT length (the palette repeat rule): code 2
        // over a 2-entry LUT wears entry 0.
        let idx = [2u8, 1];
        let mut wrapped = vec![0u8; 4];
        bin_2d_mean_color(
            &x,
            &y,
            &BinColorSource::Indexed {
                idx: &idx,
                lut: &MC_RED_BLUE,
            },
            0.0,
            1.0,
            0.0,
            1.0,
            1,
            1,
            &mut wrapped,
        );
        assert_eq!(wrapped, direct);
    }

    #[test]
    fn bin_2d_mean_color_parallel_matches_serial_oracle() {
        // Enough rows to fan out (PAR_THRESHOLD gate) over a small grid; the
        // serial cell accumulator is the oracle, so the threaded integer
        // merge must reproduce it bit-for-bit.
        let n = PAR_THRESHOLD + 4096;
        let mut x = Vec::with_capacity(n);
        let mut y = Vec::with_capacity(n);
        let mut idx = Vec::with_capacity(n);
        let mut seed = 0x00C0FFEE_u64;
        for _ in 0..n {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            x.push((seed % 1000) as f64 / 10.0);
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            y.push((seed % 1000) as f64 / 10.0);
            idx.push((seed % 4) as u8);
        }
        let lut = [
            [255, 0, 0, 255],
            [0, 0, 255, 255],
            [0, 200, 80, 128],
            [240, 240, 240, 30],
        ];
        let colors = BinColorSource::Indexed {
            idx: &idx,
            lut: &lut,
        };
        let (w, h) = (32, 32);
        let mut out = vec![0u8; w * h * 4];
        bin_2d_mean_color(&x, &y, &colors, 0.0, 100.0, 0.0, 100.0, w, h, &mut out);
        // The oracle accumulates serially by construction (direct call, one
        // chunk) — `bin_2d_mean_color_cells` itself fans out at this size.
        let mut cells = vec![MeanColorCell::default(); w * h];
        bin_2d_mean_color_accumulate(&x, &y, &colors, 0, 0.0, 100.0, 0.0, 100.0, w, h, &mut cells);
        for (cell_index, cell) in cells.iter().enumerate() {
            assert_eq!(
                &out[cell_index * 4..cell_index * 4 + 4],
                &cell.rgba8(),
                "cell {cell_index}"
            );
        }
        // Occupancy must match bin_2d exactly (same predicates, same cells).
        let mut counts = vec![0.0f32; w * h];
        bin_2d(&x, &y, 0.0, 100.0, 0.0, 100.0, w, h, &mut counts);
        for (cell_index, count) in counts.iter().enumerate() {
            assert_eq!(
                *count > 0.0,
                out[cell_index * 4 + 3] > 0,
                "cell {cell_index} occupancy"
            );
        }
    }

    #[test]
    fn mean_color_threads_shed_to_fit_accumulator_budget() {
        // Screen-sized grids and the 2048² default base level keep the full
        // 4-worker fan-out; the adaptive no-rescan base levels (§28) shed to
        // serial so worker accumulators (40 B/cell) never multiply into
        // tens of GB of transient build memory.
        assert_eq!(mean_color_threads_for(16, 512 * 384), 4);
        assert_eq!(mean_color_threads_for(4, 2048 * 2048), 4);
        assert_eq!(mean_color_threads_for(4, 4096 * 4096), 1);
        assert_eq!(mean_color_threads_for(4, 16384 * 16384), 1);
        assert_eq!(mean_color_threads_for(1, 64), 1);
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

    #[test]
    fn bin_2d_f32_matches_bin_2d_over_widened_points() {
        // The out-of-core spatial-index path bins f32 columns directly; its
        // grid must equal bin_2d over the *same points cast to f64* — the
        // contract _spatial.density_grid and its parity test rely on. Cover a
        // grid big enough to trip the parallel path (private grids + merge).
        let mut s = 0x9e3779b97f4a7c15u64;
        let mut next = || {
            s ^= s >> 12;
            s ^= s << 25;
            s ^= s >> 27;
            (s.wrapping_mul(0x2545f4914f6cdd1d) >> 11) as f64 / (1u64 << 53) as f64
        };
        let n = 300_000usize;
        let (mut xf, mut yf) = (Vec::with_capacity(n), Vec::with_capacity(n));
        for _ in 0..n {
            xf.push((next() * 20.0 - 10.0) as f32);
            yf.push((next() * 20.0 - 10.0) as f32);
        }
        // A few non-finite / out-of-window values must be skipped identically.
        xf[0] = f32::NAN;
        yf[1] = f32::INFINITY;
        xf[2] = 1e30;
        let (w, h) = (128usize, 96usize);
        let (x0, x1, y0, y1) = (-8.0, 7.5, -6.0, 6.5);
        let xd: Vec<f64> = xf.iter().map(|&v| v as f64).collect();
        let yd: Vec<f64> = yf.iter().map(|&v| v as f64).collect();
        let mut a = vec![0.0f32; w * h];
        let mut b = vec![0.0f32; w * h];
        bin_2d(&xd, &yd, x0, x1, y0, y1, w, h, &mut a);
        bin_2d_f32(&xf, &yf, x0, x1, y0, y1, w, h, &mut b);
        assert_eq!(a, b);
        assert!(b.iter().sum::<f32>() > 0.0);
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
                    assert!(
                        m.min.is_finite() && m.max.is_finite() && m.min <= m.max,
                        "it={it}"
                    );
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
            let (w, h) = (
                1 + (rng.next() % 16) as usize,
                1 + (rng.next() % 12) as usize,
            );
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
    #[cfg(not(target_family = "wasm"))]
    fn fuzz_parallel_matches_serial() {
        // The public fns only fan out past PAR_THRESHOLD, so drive the impl
        // directly: hostile data must produce bitwise-identical results for
        // every thread count (including threads > n and empty tail chunks).
        let mut rng = Rng(0x5EED_000A);
        for it in 0..120 {
            let n = (rng.next() % 2000) as usize;
            let x = rng.hostile_vec(n, -10.0, 10.0);
            let y = rng.hostile_vec(n, -10.0, 10.0);
            let (w, h) = (
                1 + (rng.next() % 16) as usize,
                1 + (rng.next() % 12) as usize,
            );
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
                assert_eq!(
                    zm_serial, zm_par,
                    "zone_maps parity it={it} threads={threads}"
                );
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
                assert_eq!(
                    rn_serial, rn_par,
                    "range count parity it={it} threads={threads}"
                );
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
                assert!(
                    x[i as usize].is_finite() && y[i as usize].is_finite(),
                    "it={it}"
                );
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
