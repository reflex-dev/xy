//! Fast, multithreaded extraction of **node coordinates** from an
//! OpenStreetMap `.osm.pbf` into two flat little-endian `f64` files
//! (`lon`, `lat`) — the on-disk canonical columns a large-scale plotting
//! engine memory-maps directly.
//!
//! Why this exists: the reference Python binding materializes a Python object
//! per node, capping throughput at a few hundred thousand nodes/second — hours
//! for a full planet (~9 billion nodes). This crate decodes the PBF protobuf
//! by hand, decompresses blobs with a pure-Rust zlib (`flate2`/`miniz_oxide`),
//! and fans blob decoding across a thread pool, reaching tens of millions of
//! nodes/second — minutes for the planet.
//!
//! ## Format
//!
//! A `.osm.pbf` is a sequence of `[u32 BE header-len][BlobHeader][Blob]`. The
//! first blob is an `OSMHeader`; the rest are `OSMData`, each a zlib-compressed
//! `PrimitiveBlock`. Nodes are stored delta- and zigzag-encoded inside
//! `DenseNodes`. We decode only what node coordinates require and ignore tags,
//! ways, and relations. See <https://wiki.openstreetmap.org/wiki/PBF_Format>.
//!
//! ## Output
//!
//! Two files of native-endian `f64`, one value per node, `lon[i]`/`lat[i]`
//! paired. Node order is not preserved across threads — irrelevant for an
//! unordered point cloud, and the whole point of the parallel write.
//!
//! Unix only (uses positioned writes); the decoder itself is portable.

pub mod sort;

use std::fs::File;
use std::io::{self, BufReader, Read};
use std::os::unix::fs::FileExt;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::sync_channel;
use std::sync::Arc;

/// Summary of a decode run.
#[derive(Debug, Clone, Copy, Default)]
pub struct Stats {
    /// Node coordinates written to the output columns.
    pub nodes: u64,
    /// Non-dense (`Node`) entries encountered — 0 for planet dumps; reported,
    /// never silently dropped.
    pub sparse_nodes: u64,
    /// `OSMData` blocks decoded.
    pub blocks: u64,
}

// ---- protobuf primitives (trusted, well-formed input) ----------------------

#[inline]
fn read_varint(buf: &[u8], pos: &mut usize) -> u64 {
    let mut result: u64 = 0;
    let mut shift = 0u32;
    loop {
        let b = buf[*pos];
        *pos += 1;
        result |= ((b & 0x7F) as u64) << shift;
        if b & 0x80 == 0 {
            return result;
        }
        shift += 7;
    }
}

#[inline]
fn zigzag(n: u64) -> i64 {
    ((n >> 1) as i64) ^ -((n & 1) as i64)
}

/// Advance `pos` past one field's value given its wire type.
#[inline]
fn skip_field(buf: &[u8], pos: &mut usize, wire: u64) {
    match wire {
        0 => {
            read_varint(buf, pos);
        }
        1 => *pos += 8,
        2 => {
            let len = read_varint(buf, pos) as usize;
            *pos += len;
        }
        5 => *pos += 4,
        _ => panic!("unsupported protobuf wire type {wire}"),
    }
}

// ---- blob framing ----------------------------------------------------------

/// `(type, datasize)` from a `BlobHeader` (fields 1 = type, 3 = datasize).
fn parse_blob_header(bh: &[u8]) -> io::Result<(String, usize)> {
    let mut pos = 0;
    let mut btype = String::new();
    let mut datasize: i64 = -1;
    while pos < bh.len() {
        let tag = read_varint(bh, &mut pos);
        let (field, wire) = (tag >> 3, tag & 0x7);
        match (field, wire) {
            (1, 2) => {
                let len = read_varint(bh, &mut pos) as usize;
                btype = String::from_utf8_lossy(&bh[pos..pos + len]).into_owned();
                pos += len;
            }
            (3, 0) => datasize = read_varint(bh, &mut pos) as i64,
            (_, w) => skip_field(bh, &mut pos, w),
        }
    }
    if datasize < 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "BlobHeader has no datasize",
        ));
    }
    Ok((btype, datasize as usize))
}

/// Decompress a `Blob` (field 1 = raw, field 3 = zlib_data, field 2 = raw_size)
/// into its `PrimitiveBlock` bytes.
fn inflate_blob(blob: &[u8]) -> io::Result<Vec<u8>> {
    let mut pos = 0;
    let mut raw_size = 0usize;
    let mut raw: Option<(usize, usize)> = None;
    let mut zlib: Option<(usize, usize)> = None;
    while pos < blob.len() {
        let tag = read_varint(blob, &mut pos);
        let (field, wire) = (tag >> 3, tag & 0x7);
        match (field, wire) {
            (2, 0) => raw_size = read_varint(blob, &mut pos) as usize,
            (1, 2) => {
                let len = read_varint(blob, &mut pos) as usize;
                raw = Some((pos, pos + len));
                pos += len;
            }
            (3, 2) => {
                let len = read_varint(blob, &mut pos) as usize;
                zlib = Some((pos, pos + len));
                pos += len;
            }
            (_, w) => skip_field(blob, &mut pos, w),
        }
    }
    if let Some((s, e)) = raw {
        return Ok(blob[s..e].to_vec());
    }
    if let Some((s, e)) = zlib {
        let mut out = Vec::with_capacity(raw_size);
        flate2::read::ZlibDecoder::new(&blob[s..e]).read_to_end(&mut out)?;
        return Ok(out);
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "Blob uses an unsupported compression (only raw/zlib handled)",
    ))
}

// ---- PrimitiveBlock / DenseNodes decode ------------------------------------

/// Decode every node coordinate in a `PrimitiveBlock`, appending degrees to
/// `lon`/`lat`. Returns the count of non-dense `Node` entries seen (skipped).
fn decode_primitive_block(buf: &[u8], lon: &mut Vec<f64>, lat: &mut Vec<f64>) -> u64 {
    // Pass 1: coordinate scaling (granularity=17 default 100, lat_offset=19,
    // lon_offset=20, all int, appear *after* the groups in the byte stream) and
    // the byte ranges of each primitivegroup (field 2).
    let mut pos = 0;
    let mut granularity: i64 = 100;
    let mut lat_off: i64 = 0;
    let mut lon_off: i64 = 0;
    let mut groups: Vec<(usize, usize)> = Vec::new();
    while pos < buf.len() {
        let tag = read_varint(buf, &mut pos);
        let (field, wire) = (tag >> 3, tag & 0x7);
        match (field, wire) {
            (2, 2) => {
                let len = read_varint(buf, &mut pos) as usize;
                groups.push((pos, pos + len));
                pos += len;
            }
            (17, 0) => granularity = read_varint(buf, &mut pos) as i64,
            (19, 0) => lat_off = read_varint(buf, &mut pos) as i64,
            (20, 0) => lon_off = read_varint(buf, &mut pos) as i64,
            (_, w) => skip_field(buf, &mut pos, w),
        }
    }
    let scale = granularity as f64;
    let mut sparse = 0u64;
    for (s, e) in groups {
        sparse += decode_group(&buf[s..e], scale, lat_off as f64, lon_off as f64, lon, lat);
    }
    sparse
}

fn decode_group(
    buf: &[u8],
    scale: f64,
    lat_off: f64,
    lon_off: f64,
    lon: &mut Vec<f64>,
    lat: &mut Vec<f64>,
) -> u64 {
    let mut pos = 0;
    let mut sparse = 0u64;
    while pos < buf.len() {
        let tag = read_varint(buf, &mut pos);
        let (field, wire) = (tag >> 3, tag & 0x7);
        match (field, wire) {
            (2, 2) => {
                // DenseNodes
                let len = read_varint(buf, &mut pos) as usize;
                decode_dense(&buf[pos..pos + len], scale, lat_off, lon_off, lon, lat);
                pos += len;
            }
            (1, 2) => {
                // repeated Node (sparse) — count and skip; planet has none.
                sparse += 1;
                let len = read_varint(buf, &mut pos) as usize;
                pos += len;
            }
            (_, w) => skip_field(buf, &mut pos, w),
        }
    }
    sparse
}

fn decode_dense(
    buf: &[u8],
    scale: f64,
    lat_off: f64,
    lon_off: f64,
    lon: &mut Vec<f64>,
    lat: &mut Vec<f64>,
) {
    // DenseNodes: lat=8, lon=9 are packed, delta-encoded sint64 arrays of equal
    // length (one entry per node). id=1 is ignored.
    let mut pos = 0;
    let mut lat_r: Option<(usize, usize)> = None;
    let mut lon_r: Option<(usize, usize)> = None;
    while pos < buf.len() {
        let tag = read_varint(buf, &mut pos);
        let (field, wire) = (tag >> 3, tag & 0x7);
        match (field, wire) {
            (8, 2) => {
                let len = read_varint(buf, &mut pos) as usize;
                lat_r = Some((pos, pos + len));
                pos += len;
            }
            (9, 2) => {
                let len = read_varint(buf, &mut pos) as usize;
                lon_r = Some((pos, pos + len));
                pos += len;
            }
            (_, w) => skip_field(buf, &mut pos, w),
        }
    }
    let (Some((mut p, pe)), Some((mut q, qe))) = (lat_r, lon_r) else {
        return;
    };
    let (mut lat_v, mut lon_v) = (0i64, 0i64);
    while p < pe && q < qe {
        lat_v += zigzag(read_varint(buf, &mut p));
        lon_v += zigzag(read_varint(buf, &mut q));
        lat.push(1e-9 * (lat_off + scale * lat_v as f64));
        lon.push(1e-9 * (lon_off + scale * lon_v as f64));
    }
}

// ---- driver ----------------------------------------------------------------

/// Decode all node coordinates from `pbf` into the `lon`/`lat` output files.
///
/// The outputs are pre-sized to `capacity` values (a sparse file until
/// written) and truncated to the exact node count on completion, so an
/// over-estimate is cheap. `n_threads` blob decoders run in parallel while a
/// reader thread streams blobs sequentially.
pub fn decode_pbf_nodes(
    pbf: &Path,
    lon_path: &Path,
    lat_path: &Path,
    capacity: u64,
    n_threads: usize,
) -> io::Result<Stats> {
    let lon_file = Arc::new(File::create(lon_path)?);
    let lat_file = Arc::new(File::create(lat_path)?);
    lon_file.set_len(capacity * 8)?;
    lat_file.set_len(capacity * 8)?;

    let cursor = Arc::new(AtomicU64::new(0));
    let sparse = Arc::new(AtomicU64::new(0));
    let blocks = Arc::new(AtomicU64::new(0));
    let n_threads = n_threads.max(1);

    let (tx, rx) = sync_channel::<Vec<u8>>(n_threads * 2);
    let rx = Arc::new(std::sync::Mutex::new(rx));

    let mut workers = Vec::with_capacity(n_threads);
    for _ in 0..n_threads {
        let rx = Arc::clone(&rx);
        let lon_file = Arc::clone(&lon_file);
        let lat_file = Arc::clone(&lat_file);
        let cursor = Arc::clone(&cursor);
        let sparse = Arc::clone(&sparse);
        let blocks = Arc::clone(&blocks);
        workers.push(std::thread::spawn(move || -> io::Result<()> {
            let mut lon: Vec<f64> = Vec::new();
            let mut lat: Vec<f64> = Vec::new();
            loop {
                let blob = {
                    let guard = rx.lock().unwrap();
                    match guard.recv() {
                        Ok(b) => b,
                        Err(_) => break,
                    }
                };
                lon.clear();
                lat.clear();
                let pb = inflate_blob(&blob)?;
                let s = decode_primitive_block(&pb, &mut lon, &mut lat);
                if s > 0 {
                    sparse.fetch_add(s, Ordering::Relaxed);
                }
                blocks.fetch_add(1, Ordering::Relaxed);
                let count = lon.len() as u64;
                if count == 0 {
                    continue;
                }
                let off = cursor.fetch_add(count, Ordering::Relaxed);
                if off + count > capacity {
                    return Err(io::Error::other(
                        "node count exceeded capacity; raise --capacity",
                    ));
                }
                let byte_off = off * 8;
                lon_file.write_all_at(as_bytes(&lon), byte_off)?;
                lat_file.write_all_at(as_bytes(&lat), byte_off)?;
            }
            Ok(())
        }));
    }

    // Reader: stream blobs sequentially; hand OSMData blobs to the pool.
    let read_result = (|| -> io::Result<()> {
        let mut reader = BufReader::with_capacity(1 << 22, File::open(pbf)?);
        let mut len_buf = [0u8; 4];
        // A short read anywhere is a truncated tail (e.g. a partial download):
        // stop cleanly with whatever whole blobs we have, rather than erroring.
        loop {
            match reader.read_exact(&mut len_buf) {
                Ok(()) => {}
                Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => break,
                Err(e) => return Err(e),
            }
            let hlen = u32::from_be_bytes(len_buf) as usize;
            let mut hbuf = vec![0u8; hlen];
            if read_full_or_eof(&mut reader, &mut hbuf)?.is_none() {
                break;
            }
            let (btype, datasize) = parse_blob_header(&hbuf)?;
            let mut blob = vec![0u8; datasize];
            if read_full_or_eof(&mut reader, &mut blob)?.is_none() {
                break;
            }
            if btype == "OSMData" {
                // Send fails only if all workers died (their error surfaces on join).
                if tx.send(blob).is_err() {
                    break;
                }
            }
        }
        Ok(())
    })();
    drop(tx);

    let mut first_err = read_result.err();
    for w in workers {
        let joined = match w.join() {
            Ok(inner) => inner,
            Err(_) => Err(io::Error::other("worker panicked")),
        };
        if let Err(e) = joined {
            first_err.get_or_insert(e);
        }
    }
    if let Some(e) = first_err {
        return Err(e);
    }

    let nodes = cursor.load(Ordering::Relaxed);
    lon_file.set_len(nodes * 8)?;
    lat_file.set_len(nodes * 8)?;
    Ok(Stats {
        nodes,
        sparse_nodes: sparse.load(Ordering::Relaxed),
        blocks: blocks.load(Ordering::Relaxed),
    })
}

/// Read exactly `buf.len()` bytes, or return `None` if EOF arrives first
/// (a truncated final blob). Distinguishes clean truncation from a real error.
fn read_full_or_eof<R: Read>(r: &mut R, buf: &mut [u8]) -> io::Result<Option<()>> {
    let mut filled = 0;
    while filled < buf.len() {
        match r.read(&mut buf[filled..]) {
            Ok(0) => return Ok(None),
            Ok(n) => filled += n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
            Err(e) => return Err(e),
        }
    }
    Ok(Some(()))
}

#[inline]
fn as_bytes(v: &[f64]) -> &[u8] {
    // f64 is plain-old-data; a read-only reinterpret for positioned writes.
    unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn varint_roundtrip() {
        // Encode a few varints back-to-back and read them.
        let mut buf = Vec::new();
        for v in [0u64, 1, 127, 128, 300, 16384, u64::MAX] {
            let mut x = v;
            loop {
                let mut b = (x & 0x7F) as u8;
                x >>= 7;
                if x != 0 {
                    b |= 0x80;
                }
                buf.push(b);
                if x == 0 {
                    break;
                }
            }
        }
        let mut pos = 0;
        for v in [0u64, 1, 127, 128, 300, 16384, u64::MAX] {
            assert_eq!(read_varint(&buf, &mut pos), v);
        }
        assert_eq!(pos, buf.len());
    }

    #[test]
    fn zigzag_known_values() {
        assert_eq!(zigzag(0), 0);
        assert_eq!(zigzag(1), -1);
        assert_eq!(zigzag(2), 1);
        assert_eq!(zigzag(3), -2);
        assert_eq!(zigzag(4), 2);
        // A delta chain like DenseNodes stores: +1, +1, -1 → 0,1,2,1.
        let deltas = [zigzag(2), zigzag(2), zigzag(1)]; // 1, 1, -1
        let mut acc = 0i64;
        let cum: Vec<i64> = deltas
            .iter()
            .map(|d| {
                acc += d;
                acc
            })
            .collect();
        assert_eq!(cum, vec![1, 2, 1]);
    }
}
