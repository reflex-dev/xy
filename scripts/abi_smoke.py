"""Stdlib-only smoke test for the native C ABI (no numpy required).

cargo tests cover the kernels; this covers the *boundary* — ctypes signatures,
pointer/struct layout, sentinel values — which is where the Python/Rust seam is
most likely to break and which the Rust tests can't reach. Uses the builtin
`array` module for contiguous typed buffers.

Runs in CI as an early gate before the numpy-backed suite, and is the one
verification that works even when PyPI is unreachable.
"""

from __future__ import annotations

import ctypes
import math
import sys
from array import array
from pathlib import Path

ABI_VERSION = 2
ROOT = Path(__file__).resolve().parent.parent


def _lib_name() -> str:
    if sys.platform == "win32":
        return "fastcharts_core.dll"
    if sys.platform == "darwin":
        return "libfastcharts_core.dylib"
    return "libfastcharts_core.so"


def load() -> ctypes.CDLL:
    name = _lib_name()
    for cand in (ROOT / "target" / "release" / name, ROOT / "target" / "debug" / name):
        if cand.exists():
            lib = ctypes.CDLL(str(cand))
            break
    else:
        raise SystemExit(f"{name} not built; run `cargo build --release`")

    F64P = ctypes.POINTER(ctypes.c_double)
    F32P = ctypes.POINTER(ctypes.c_float)
    U64P = ctypes.POINTER(ctypes.c_uint64)
    U32P = ctypes.POINTER(ctypes.c_uint32)

    lib.fc_abi_version.restype = ctypes.c_uint32
    lib.fc_abi_version.argtypes = []
    lib.fc_encode_f32.restype = None
    lib.fc_encode_f32.argtypes = [F64P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, F32P]
    lib.fc_m4_indices.restype = ctypes.c_size_t
    lib.fc_m4_indices.argtypes = [
        F64P, F64P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, ctypes.c_size_t, U32P
    ]
    lib.fc_zone_maps.restype = ctypes.c_size_t
    lib.fc_zone_maps.argtypes = [F64P, ctypes.c_size_t, ctypes.c_size_t] + [F64P, F64P, U64P, U64P, F64P, F64P]
    lib.fc_min_max.restype = ctypes.c_int32
    lib.fc_min_max.argtypes = [F64P, ctypes.c_size_t, F64P, F64P]
    D = ctypes.c_double
    Z = ctypes.c_size_t
    lib.fc_bin_2d.restype = ctypes.c_int32
    lib.fc_bin_2d.argtypes = [F64P, F64P, Z, D, D, D, D, Z, Z, F32P]
    return lib


def _ptr(a: array, ct):  # noqa: ANN001
    addr, _ = a.buffer_info()
    return ctypes.cast(addr, ctypes.POINTER(ct))


def main() -> None:
    lib = load()
    checks = 0

    def ok(cond: bool, msg: str) -> None:
        nonlocal checks
        if not cond:
            raise SystemExit(f"FAIL: {msg}")
        checks += 1

    ok(lib.fc_abi_version() == ABI_VERSION, "abi version")

    # encode_f32: the §16 precision claim, verified through the real ABI.
    t0 = 1.6e12
    x = array("d", [t0 + i for i in range(1000)])
    offset = t0 + 500.0
    out = array("f", [0.0]) * len(x)
    lib.fc_encode_f32(
        _ptr(x, ctypes.c_double), len(x), offset, 1.0, _ptr(out, ctypes.c_float)
    )
    worst = max(abs((out[i] + offset) - x[i]) for i in range(len(x)))
    ok(worst < 1e-3, f"offset-encoded precision worst={worst}")

    # Control: naive f32 (offset 0) is visibly wrong.
    naive = array("f", [0.0]) * len(x)
    lib.fc_encode_f32(_ptr(x, ctypes.c_double), len(x), 0.0, 1.0, _ptr(naive, ctypes.c_float))
    ok(max(abs(naive[i] - x[i]) for i in range(len(x))) > 1.0, "naive f32 corrupts")

    # m4_indices: spike preservation + first/last, through the ABI.
    n = 10_000
    xs = array("d", [float(i) for i in range(n)])
    ys = array("d", [math.sin(i * 0.01) for i in range(n)])
    ys[5432] = 100.0
    ys[7891] = -100.0
    buckets = 100
    idx_buf = array("I", [0]) * (buckets * 4)
    written = lib.fc_m4_indices(
        _ptr(xs, ctypes.c_double), _ptr(ys, ctypes.c_double), n,
        0.0, float(n), buckets, _ptr(idx_buf, ctypes.c_uint32),
    )
    idx = set(idx_buf[:written])
    ok(5432 in idx and 7891 in idx, "m4 preserves spikes")
    ok(0 in idx and (n - 1) in idx, "m4 keeps first/last")
    ok(written <= buckets * 4, "m4 bounded output")

    # m4 invalid-arg sentinel (usize::MAX).
    bad = lib.fc_m4_indices(
        _ptr(xs, ctypes.c_double), _ptr(ys, ctypes.c_double), n,
        5.0, 5.0, buckets, _ptr(idx_buf, ctypes.c_uint32),
    )
    ok(bad == (2**64 - 1), "m4 invalid-arg sentinel")

    # zone_maps: stats + NaN-as-null, through the ABI.
    data = array("d", [float(i) for i in range(10)])
    data[3] = float("nan")
    nchunks = 1
    zm = [array("d", [0.0]) * nchunks for _ in range(4)]  # min,max,sum,sumsq
    cnt = array("Q", [0]) * nchunks
    nul = array("Q", [0]) * nchunks
    wrote = lib.fc_zone_maps(
        _ptr(data, ctypes.c_double), len(data), 65536,
        _ptr(zm[0], ctypes.c_double), _ptr(zm[1], ctypes.c_double),
        _ptr(cnt, ctypes.c_uint64), _ptr(nul, ctypes.c_uint64),
        _ptr(zm[2], ctypes.c_double), _ptr(zm[3], ctypes.c_double),
    )
    ok(wrote == 1, "zone_maps chunk count")
    ok(cnt[0] == 9 and nul[0] == 1, "zone_maps counts NaN as null")
    ok(zm[0][0] == 0.0 and zm[1][0] == 9.0, "zone_maps min/max skip NaN")

    # min_max sentinel path.
    lo = ctypes.c_double()
    hi = ctypes.c_double()
    got = lib.fc_min_max(
        _ptr(data, ctypes.c_double), len(data), ctypes.byref(lo), ctypes.byref(hi)
    )
    ok(got == 1 and lo.value == 0.0 and hi.value == 9.0, "min_max ok")
    allnan = array("d", [float("nan")])
    ok(lib.fc_min_max(_ptr(allnan, ctypes.c_double), 1, ctypes.byref(lo), ctypes.byref(hi)) == 0,
       "min_max all-NaN returns 0")

    # bin_2d: 4 points, one per quadrant of a 2×2 grid; count conserved, row0 bottom.
    bx = array("d", [0.25, 0.75, 0.25, 0.75])
    by = array("d", [0.25, 0.25, 0.75, 0.75])
    grid = array("f", [0.0]) * 4
    got = lib.fc_bin_2d(
        _ptr(bx, ctypes.c_double), _ptr(by, ctypes.c_double), 4,
        0.0, 1.0, 0.0, 1.0, 2, 2, _ptr(grid, ctypes.c_float),
    )
    ok(got == 1, "bin_2d ok flag")
    ok(list(grid) == [1.0, 1.0, 1.0, 1.0], "bin_2d one per quadrant")
    ok(sum(grid) == 4.0, "bin_2d conserves count")
    # A dense cluster in one cell dominates.
    cx = array("d", [0.1] * 500 + [0.9])
    cy = array("d", [0.1] * 500 + [0.9])
    g2 = array("f", [0.0]) * 4
    lib.fc_bin_2d(
        _ptr(cx, ctypes.c_double), _ptr(cy, ctypes.c_double), 501,
        0.0, 1.0, 0.0, 1.0, 2, 2, _ptr(g2, ctypes.c_float),
    )
    ok(g2[0] == 500.0 and g2[3] == 1.0, "bin_2d density hotspot")

    print(f"ABI smoke: {checks} checks passed against {_lib_name()}")


if __name__ == "__main__":
    main()
