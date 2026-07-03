"""Native-kernel benchmark, stdlib only (no numpy / no PyPI).

Times the Rust core through the C ABI so the throughput claims are executed
numbers, not aspirations, even in a locked-down environment. The numpy-backed
`scripts/bench.py` measures the full figure→payload path once deps install;
this measures the kernels that path is built on.

Usage: python scripts/bench_native.py [--sizes 1e5,1e6,1e7]
"""

from __future__ import annotations

import argparse
import ctypes
import math
import time
from array import array

from abi_smoke import load  # same directory


def _ptr(a: array, ct):  # noqa: ANN001
    addr, _ = a.buffer_info()
    return ctypes.cast(addr, ctypes.POINTER(ct))


def timeit(fn, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def bench(lib, n: int) -> dict:  # noqa: ANN001
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
    t = timeit(lambda: lib.fc_zone_maps(
        _ptr(x, D), n, 65536,
        _ptr(zmin, D), _ptr(zmax, D), _ptr(zc, U64), _ptr(zn, U64), _ptr(zsum, D), _ptr(zsq, D),
    ))
    zone_mpts = n / t / 1e6

    # m4 over the full range into ~2048 pixel columns
    buckets = 2048
    idx = array("I", bytes(4 * buckets * 4))
    t = timeit(lambda: lib.fc_m4_indices(
        _ptr(x, D), _ptr(y, D), n, 0.0, float(n), buckets, _ptr(idx, U32)
    ))
    m4_mpts = n / t / 1e6

    # m4 over a 1% window (the zoom re-decimation cost — §17)
    x0, x1 = n * 0.495, n * 0.505
    t = timeit(lambda: lib.fc_m4_indices(
        _ptr(x, D), _ptr(y, D), n, x0, x1, buckets, _ptr(idx, U32)
    ))
    zoom_ms = t * 1e3

    return {
        "n": n,
        "encode_mpts_s": encode_mpts,
        "zone_maps_mpts_s": zone_mpts,
        "m4_full_mpts_s": m4_mpts,
        "zoom_redecimate_ms": zoom_ms,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e5,1e6,1e7")
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]
    lib = load()

    print("| points | encode f32 | zone maps | M4 (full) | zoom re-decimate (1% window) |")
    print("|---|---|---|---|---|")
    for n in sizes:
        r = bench(lib, n)
        print(
            f"| {r['n']:,} | {r['encode_mpts_s']:.0f} Mpt/s | {r['zone_maps_mpts_s']:.0f} Mpt/s "
            f"| {r['m4_full_mpts_s']:.0f} Mpt/s | {r['zoom_redecimate_ms']:.2f} ms |"
        )


if __name__ == "__main__":
    main()
