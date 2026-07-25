# osmpbf-nodes

Fast, multithreaded extraction of **node coordinates** from an OpenStreetMap
`.osm.pbf` file into two flat little-endian `f64` column files (`lon`, `lat`).

Built for feeding large-scale point-cloud / plotting engines that memory-map
their canonical columns: the output is exactly what such an engine wants on
disk, and the whole planet (~9 billion nodes) decodes in **minutes** instead of
the hours a per-object Python binding takes.

## Why

The reference Python binding (pyosmium) materializes a Python object per node,
which caps throughput at a few hundred thousand nodes/second. This crate decodes
the PBF protobuf by hand, decompresses blobs with pure-Rust zlib
(`flate2`/`miniz_oxide`), and fans blob decoding across a thread pool. On a
16-core desktop it sustains **~50–60 M nodes/second**, validated to produce
bit-for-bit identical coordinates to pyosmium.

## Install / build

```sh
cargo build --release
```

## Use (CLI)

```sh
osm-nodes planet-latest.osm.pbf lon.f64 lat.f64 --threads 16
```

- `lon.f64` / `lat.f64`: native-endian `f64`, one value per node, `lon[i]`
  paired with `lat[i]`. Load with `numpy.memmap(path, dtype='<f8')`.
- Node order is **not** preserved (parallel writes) — fine for an unordered
  point cloud; sort externally if you need determinism.
- Output files are pre-sized sparse and truncated to the exact count, so the
  default `--capacity` (12e9) costs nothing if the planet is smaller.

## Use (library)

```rust
use osmpbf_nodes::decode_pbf_nodes;
use std::path::Path;

let stats = decode_pbf_nodes(
    Path::new("planet.osm.pbf"),
    Path::new("lon.f64"),
    Path::new("lat.f64"),
    12_000_000_000, // capacity upper bound
    16,             // threads
)?;
println!("{} nodes across {} blocks", stats.nodes, stats.blocks);
```

## Scope & limitations

- Extracts node **coordinates only** — tags, ways, relations, and metadata are
  ignored. Non-dense `Node` entries (rare; absent from planet dumps) are counted
  and reported, never silently dropped.
- Handles `raw` and `zlib`-compressed blobs (the only forms produced by
  osmosis/osmium). lzma/zstd blobs are rejected with an error.
- Unix only (uses positioned writes). The decoder itself is portable.

## License

Apache-2.0.
