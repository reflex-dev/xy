# Every OpenStreetMap node, out-of-core

Render **all ~10.7 billion OpenStreetMap planet nodes** as an interactive
density scatter in `xy`, straight off disk. This is the end-to-end proof of the
design dossier's §27 *"mmap (native)"* canonical-store row and the §2 *"100M+ /
out-of-core — interactive via viewport tiling, bounded RAM"* target, at true
planet scale: **172 GB of lon/lat lives on disk, resident memory stays
screen-bounded** (the density pyramid), never data-bounded.

The dataset used here: `planet-latest.osm.pbf` decoded to
**10,742,674,832 nodes** → two f64 columns (`osm_lon.f64`, `osm_lat.f64`,
86 GB each).

## What's in here

| File | Role |
|---|---|
| `osmium-rs/` | Native Rust crate: `osm-nodes` (PBF → f64 columns, ~250× pyosmium) and `osm-sort` (builds the Tier-3 spatial index). |
| `ingest.py` | Parse a planet `.pbf` into f64 columns and render the out-of-core density scatter (with timings). |
| `viewer.py` | Interactive browser viewer — serves `xy`'s real WebGL client over plain HTTP; pan/zoom re-aggregate every viewport from disk. |
| `_pbf_split.py` | Standalone PBF blob-framing scanner (byte-range enumeration for parallel decode); reference/legacy helper. |

## Prerequisites

- **Rust** (for the native parser/sorter): `cd examples/osm/osmium-rs && cargo build --release`
- **The render client**, built once from the repo root (it is not committed — see #214): `npm ci && node js/build.mjs`
- **A planet PBF**: download `planet-latest.osm.pbf` from a mirror (~80 GB). *(Any `.osm.pbf` extract works — a city/country extract is a fast way to try the pipeline.)*
- Disk: ~260 GB free for the full planet (172 GB columns + 84 GB spatial index).

All commands below are run **from the repo root**.

## 1. Parse: PBF → canonical f64 columns

```bash
python examples/osm/ingest.py \
    --pbf /path/to/planet-latest.osm.pbf \
    --out /path/to/osm-data
```

`osm-nodes` decodes DenseNodes (delta + zigzag varint) across all CPU cores
with a zlib-ng inflate backend, writing `osm_lon.f64` / `osm_lat.f64` straight
to disk. `ingest.py` then builds the figure and prints the memory report and a
few zoom timings — proving `canonical_bytes` (RAM-resident) stays **0** while
`canonical_mapped_bytes` (disk) holds all 172 GB.

Re-run against columns already on disk with `--reuse` (skips parsing).

## 2. (Optional but recommended) Build the deep-zoom spatial index

The density pyramid alone answers zoomed-out views crisply, but its finest
level over the whole planet is ~2.4 km/cell — so city/street zoom would only
upsample (blurry). `osm-sort` spatially sorts every point into a grid-bucketed
layout so a viewport reads only its in-window points — deep zoom then gets
**sharper and cheaper the further you go**.

```bash
examples/osm/osmium-rs/target/release/osm-sort \
    /path/to/osm-data/osm_lon.f64 \
    /path/to/osm-data/osm_lat.f64 \
    /path/to/osm-data/osm_spatial \
    --grid 8192 --partitions 512
```

Produces `osm_spatial.lon.f32` / `osm_spatial.lat.f32` (sorted by cell) and
`osm_spatial.idx` (header + cumulative cell offsets). It's an external counting
sort — sequential I/O only, peak RAM ≈ one partition. `viewer.py` attaches it
automatically if `osm_spatial.idx` sits next to the columns.

## 3. View

```bash
python examples/osm/viewer.py --out /path/to/osm-data --port 8777
# open http://localhost:8777/
```

Drag to pan, scroll to zoom. Every viewport is re-aggregated through the same
`channel.handle_message` kernel protocol the notebook widget uses. The tier
served rides each update as `binning`:

- `pyramid-L<l>` / `-upsampled` — zoomed-out aggregate from the pre-binned pyramid.
- `spatial-exact` (`filter: nearest`) — deep zoom re-binned exactly from the
  in-window points at full screen resolution (crisp streets, no interpolation blur).
- `spatial-points` — deep enough that the window fits the direct budget: the
  real points ship as individual marks.

## Rough timings (10.7B nodes, NVMe SSD, 16 cores)

| Stage | Cost | Notes |
|---|---|---|
| Parse (`osm-nodes`) | minutes | ~250× the pyosmium binding; multithreaded + zlib-ng |
| Spatial sort (`osm-sort`) | ~8 min (~21 M pts/s) | 3-pass parallel external counting sort |
| Figure build (zone maps) | **~51 s first time, then instant** | one 172 GB scan; result cached to a `.xyzones` sidecar next to each column, so every later run (e.g. viewer restart) loads it in milliseconds |
| Pan / zoom | single-digit ms | screen-bounded per viewport, independent of N |

The `.xyzones` zone-map cache is a general `xy` out-of-core feature (see
`python/xy/columns.py`): the first `figure()` over a memmapped column persists
its per-chunk statistics, and reopening validates the sidecar against the
file's size/mtime before reusing it — so the 51 s domain scan is paid once, not
on every restart.
