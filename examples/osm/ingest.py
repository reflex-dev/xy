"""Ingest **every OpenStreetMap node** (~9 billion, from `planet-latest.osm.pbf`)
into xy's out-of-core canonical store and render it as a density scatter.

This is the end-to-end proof of the §27 "mmap (native)" canonical-store row and
the §2 "100M+ / out-of-core — interactive via viewport tiling, bounded RAM"
target, at true planet scale. Peak resident memory stays screen-bounded (the
density pyramid), not data-bounded (172 GB of lon/lat on disk).

Pipeline:
  planet.pbf ──osm-nodes (native)──▶ osm_lon.f64 / osm_lat.f64 (disk f64)
            ──▶ xy.scatter(density=True) ──▶ build_payload / density_view

Usage (from the repo root):
  python examples/osm/ingest.py \
      --pbf /path/to/planet-latest.osm.pbf \
      --out /path/to/osm-data \
      [--reuse]   # skip parsing; reuse osm_lon.f64/osm_lat.f64 on disk

The native parser (examples/osm/osmium-rs) is built with:
  cd examples/osm/osmium-rs && cargo build --release
"""

from __future__ import annotations

import argparse
import os
import resource
import subprocess
import sys
import time

import numpy as np

# examples/osm/ → repo root is two levels up; the package lives in python/.
_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "python"))
import xy  # noqa: E402
from xy._ooc import open_f64  # noqa: E402


def _rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # GB on Linux


def parse_planet(pbf: str, out_dir: str) -> tuple[np.memmap, np.memmap]:
    """Decode all node coordinates via the native `osm-nodes` parser
    (`osmium-rs/`, ~250x faster than the Python binding), then memmap the
    resulting f64 columns. The parser writes canonical columns straight to
    disk; xy never holds the data in RAM."""
    px = os.path.join(out_dir, "osm_lon.f64")
    py = os.path.join(out_dir, "osm_lat.f64")
    binary = os.path.join(_HERE, "osmium-rs", "target", "release", "osm-nodes")
    if not os.path.exists(binary):
        raise SystemExit(
            f"native parser not built: {binary}\n"
            "build it with:  cd examples/osm/osmium-rs && cargo build --release"
        )
    t0 = time.perf_counter()
    subprocess.run([binary, pbf, px, py], check=True)
    print(f"native parse wall-clock: {time.perf_counter() - t0:.0f}s", flush=True)
    xcol, ycol = open_f64(px), open_f64(py)
    print(
        f"canonical on disk: {xcol.nbytes + ycol.nbytes:,} bytes across 2 columns "
        f"({len(xcol):,} nodes)",
        flush=True,
    )
    return xcol, ycol


def bench(xcol: np.memmap, ycol: np.memmap) -> None:
    n = len(xcol)
    print(f"\n=== rendering {n:,} points (out-of-core density scatter) ===", flush=True)

    t0 = time.perf_counter()
    fig = xy.chart(xy.scatter(x=xcol, y=ycol, density=True)).figure()
    print(
        f"figure build (ingest + zone maps, one disk scan): {time.perf_counter() - t0:.0f}s",
        flush=True,
    )

    rep = fig.store.memory_report()
    print(f"  canonical_bytes (RAM-resident): {rep['canonical_bytes']:,}")
    print(f"  canonical_mapped_bytes (disk):  {rep['canonical_mapped_bytes']:,}")
    assert rep["canonical_bytes"] == 0, "canonical data leaked into RAM"

    t0 = time.perf_counter()
    spec, blob = fig.build_payload(2048)
    tr = spec["traces"][0]
    print(
        f"first paint: {time.perf_counter() - t0:.0f}s | wire blob = {len(blob):,} B "
        f"| tier={tr.get('tier')}",
        flush=True,
    )

    # Zoom into a continent-scale window; should serve from the pyramid.
    for label, (x0, x1, y0, y1) in {
        "world": (-180.0, 180.0, -85.0, 85.0),
        "europe": (-12.0, 32.0, 35.0, 60.0),
        "london": (-0.5, 0.3, 51.3, 51.7),
    }.items():
        t0 = time.perf_counter()
        s2, bufs2 = fig.density_view(0, x0, x1, y0, y1, 1000, 800)
        tr2 = s2["traces"][0] if s2.get("traces") else {}
        nbytes = sum(len(b) for b in bufs2)
        print(
            f"  zoom [{label}]: {(time.perf_counter() - t0) * 1e3:.0f} ms "
            f"| {len(bufs2)} bufs / {nbytes:,} B "
            f"| tier={tr2.get('tier')} | binning={tr2.get('binning')} | visible={tr2.get('visible')}",
            flush=True,
        )

    full = fig.memory_report()
    print(
        f"\nresident_array_bytes: {full['resident_array_bytes']:,} "
        f"(canonical RAM {full['canonical_bytes']:,} + channels {full['channel_bytes']:,} "
        f"+ pyramid {full['pyramid_bytes']:,})"
    )
    print(f"canonical on disk (mapped): {full['canonical_mapped_bytes']:,} bytes")
    print(f"peak process RSS: {_rss_gb():.2f} GB")
    print("\nOK — every OSM node rendered with screen-bounded resident memory.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", help="planet-latest.osm.pbf (omit with --reuse)")
    ap.add_argument("--out", required=True, help="output dir for the f64 columns")
    ap.add_argument(
        "--reuse",
        action="store_true",
        help="skip parsing; reuse osm_lon.f64/osm_lat.f64 already on disk",
    )
    args = ap.parse_args()
    if not args.reuse and not args.pbf:
        ap.error("--pbf is required unless --reuse is given")

    if args.reuse:
        xcol = open_f64(os.path.join(args.out, "osm_lon.f64"))
        ycol = open_f64(os.path.join(args.out, "osm_lat.f64"))
        print(f"reusing {len(xcol):,} nodes from disk", flush=True)
    else:
        xcol, ycol = parse_planet(args.pbf, args.out)
    bench(xcol, ycol)


if __name__ == "__main__":
    main()
