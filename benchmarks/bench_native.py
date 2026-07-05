"""Native-kernel benchmark, stdlib only (no numpy / no PyPI).

Times the Rust core through the C ABI so the throughput claims are executed
numbers, not aspirations, even in a locked-down environment. The numpy-backed
`benchmarks/bench.py` measures the full figure→payload path once deps install;
this measures the kernels that path is built on.

Usage: python benchmarks/bench_native.py [--sizes 1e5,1e6,1e7]
"""

from __future__ import annotations

import argparse
import ctypes
import math
import sys
import time
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from abi_smoke import load  # noqa: E402


def _ptr(a: array, ct):
    addr, _ = a.buffer_info()
    return ctypes.cast(addr, ctypes.POINTER(ct))


def timeit(fn, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def bench(lib, n: int) -> dict:
    D = ctypes.c_double
    F = ctypes.c_float
    U32 = ctypes.c_uint32
    U64 = ctypes.c_uint64

    x = array("d", range(n))
    x = array("d", (float(i) for i in range(n)))
    y = array("d", (math.sin(i * 1e-3) for i in range(n)))

    # encode_f32
    enc = array("f", bytes(4 * n))
    t = timeit(lambda: lib.fc_encode_f32(_ptr(x, D), n, x[n // 2], 1.0, _ptr(enc, F)))
    encode_mpts = n / t / 1e6

    # zone_maps (64k chunks)
    nchunks = -(-n // 65536)
    zmin = array("d", bytes(8 * nchunks))
    zmax = array("d", bytes(8 * nchunks))
    zsum = array("d", bytes(8 * nchunks))
    zsq = array("d", bytes(8 * nchunks))
    zc = array("Q", bytes(8 * nchunks))
    zn = array("Q", bytes(8 * nchunks))
    t = timeit(
        lambda: lib.fc_zone_maps(
            _ptr(x, D),
            n,
            65536,
            _ptr(zmin, D),
            _ptr(zmax, D),
            _ptr(zc, U64),
            _ptr(zn, U64),
            _ptr(zsum, D),
            _ptr(zsq, D),
        )
    )
    zone_mpts = n / t / 1e6

    # m4 over the full range into ~2048 pixel columns
    buckets = 2048
    idx = array("I", bytes(4 * buckets * 4))
    t = timeit(
        lambda: lib.fc_m4_indices(_ptr(x, D), _ptr(y, D), n, 0.0, float(n), buckets, _ptr(idx, U32))
    )
    m4_mpts = n / t / 1e6

    # m4 over a 1% window (the zoom re-decimation cost — §17)
    x0, x1 = n * 0.495, n * 0.505
    t = timeit(
        lambda: lib.fc_m4_indices(_ptr(x, D), _ptr(y, D), n, x0, x1, buckets, _ptr(idx, U32))
    )
    zoom_ms = t * 1e3

    # bin_2d: the Tier-2 scatter aggregation cost (§5). 512x384 grid.
    gw, gh = 512, 384
    grid = array("f", bytes(4 * gw * gh))
    t = timeit(
        lambda: lib.fc_bin_2d(
            _ptr(x, D), _ptr(y, D), n, 0.0, float(n), -3.0, 3.0, gw, gh, _ptr(grid, F)
        )
    )
    bin_mpts = n / t / 1e6
    bin_ms = t * 1e3

    # histogram_uniform: fixed-bin histogram path for the public histogram API.
    bins = 512
    counts = array("d", bytes(8 * bins))
    t = timeit(
        lambda: lib.fc_histogram_uniform(_ptr(x, D), n, 0.0, float(n), bins, 0, _ptr(counts, D))
    )
    hist_mpts = n / t / 1e6
    hist_ms = t * 1e3

    # normalize_f32: color/size channels and heatmap normalization.
    norm = array("f", bytes(4 * n))
    t = timeit(lambda: lib.fc_normalize_f32(_ptr(y, D), n, -1.0, 1.0, 0, _ptr(norm, F)))
    norm_mpts = n / t / 1e6

    # range_indices: rectangular viewport/selection scan used by drilldown.
    sel = array("I", bytes(4 * n))
    t = timeit(
        lambda: lib.fc_range_indices(
            _ptr(x, D), _ptr(y, D), n, n * 0.45, n * 0.55, -2.0, 2.0, _ptr(sel, U32)
        )
    )
    range_mpts = n / t / 1e6
    range_ms = t * 1e3

    # local_log_density is only used once the visible drill subset is bounded,
    # so benchmark it at the interactive budget rather than full-N.
    local_n = min(n, 200_000)
    local = array("f", bytes(4 * local_n))
    t = timeit(
        lambda: lib.fc_local_log_density(
            _ptr(x, D),
            _ptr(y, D),
            local_n,
            0.0,
            float(local_n),
            -3.0,
            3.0,
            gw,
            gh,
            _ptr(local, F),
        )
    )
    local_mpts = local_n / t / 1e6
    local_ms = t * 1e3

    return {
        "n": n,
        "encode_mpts_s": encode_mpts,
        "zone_maps_mpts_s": zone_mpts,
        "m4_full_mpts_s": m4_mpts,
        "zoom_redecimate_ms": zoom_ms,
        "bin_2d_mpts_s": bin_mpts,
        "bin_2d_ms": bin_ms,
        "histogram_mpts_s": hist_mpts,
        "histogram_ms": hist_ms,
        "normalize_mpts_s": norm_mpts,
        "range_mpts_s": range_mpts,
        "range_ms": range_ms,
        "local_density_n": local_n,
        "local_density_mpts_s": local_mpts,
        "local_density_ms": local_ms,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e5,1e6,1e7")
    ap.add_argument("--json", default=None, help="write per-size metric rows here")
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]
    lib = load()

    rows = []
    print(
        "| points | encode f32 | normalize | histogram | zone maps | M4 (full) | "
        "zoom re-decimate | range scan | bin_2d (Tier2) | local density |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for n in sizes:
        r = bench(lib, n)
        rows.append(r)
        print(
            f"| {r['n']:,} | {r['encode_mpts_s']:.0f} Mpt/s "
            f"| {r['normalize_mpts_s']:.0f} Mpt/s "
            f"| {r['histogram_mpts_s']:.0f} Mpt/s ({r['histogram_ms']:.2f} ms) "
            f"| {r['zone_maps_mpts_s']:.0f} Mpt/s "
            f"| {r['m4_full_mpts_s']:.0f} Mpt/s "
            f"| {r['zoom_redecimate_ms']:.2f} ms "
            f"| {r['range_mpts_s']:.0f} Mpt/s ({r['range_ms']:.2f} ms) "
            f"| {r['bin_2d_mpts_s']:.0f} Mpt/s ({r['bin_2d_ms']:.0f} ms) "
            f"| {r['local_density_mpts_s']:.0f} Mpt/s "
            f"({r['local_density_ms']:.2f} ms/{r['local_density_n']:,}) |"
        )

    if args.json:
        import json

        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"rows": rows}, f, indent=2)


if __name__ == "__main__":
    main()
