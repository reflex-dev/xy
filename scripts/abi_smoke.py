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

ROOT = Path(__file__).resolve().parent.parent


def _expected_abi_version() -> int:
    """Read ABI_VERSION from the ctypes wrapper source (stdlib-only; the
    wrapper imports numpy, so it can't be imported here). One less copy of
    the constant to keep in sync — src/lib.rs and _native.py stay the two
    authoritative locations (CLAUDE.md invariant)."""
    source = (ROOT / "python" / "fastcharts" / "_native.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("ABI_VERSION = "):
            return int(line.split("=", 1)[1].strip())
    raise SystemExit("ABI_VERSION not found in python/fastcharts/_native.py")


ABI_VERSION = _expected_abi_version()


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
    U8P = ctypes.POINTER(ctypes.c_uint8)

    lib.fc_abi_version.restype = ctypes.c_uint32
    lib.fc_abi_version.argtypes = []
    lib.fc_encode_f32.restype = ctypes.c_int32
    lib.fc_encode_f32.argtypes = [F64P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, F32P]
    lib.fc_m4_indices.restype = ctypes.c_size_t
    lib.fc_m4_indices.argtypes = [
        F64P,
        F64P,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        U32P,
    ]
    lib.fc_zone_maps.restype = ctypes.c_size_t
    lib.fc_zone_maps.argtypes = [F64P, ctypes.c_size_t, ctypes.c_size_t] + [
        F64P,
        F64P,
        U64P,
        U64P,
        F64P,
        F64P,
    ]
    lib.fc_min_max.restype = ctypes.c_int32
    lib.fc_min_max.argtypes = [F64P, ctypes.c_size_t, F64P, F64P]
    D = ctypes.c_double
    Z = ctypes.c_size_t
    lib.fc_bin_2d.restype = ctypes.c_int32
    lib.fc_bin_2d.argtypes = [F64P, F64P, Z, D, D, D, D, Z, Z, F32P]
    lib.fc_bin_2d_indices.restype = ctypes.c_size_t
    lib.fc_bin_2d_indices.argtypes = [F64P, F64P, Z, D, D, D, D, Z, Z, F32P, U32P]
    lib.fc_histogram_uniform.restype = ctypes.c_size_t
    lib.fc_histogram_uniform.argtypes = [
        F64P,
        ctypes.c_size_t,
        D,
        D,
        ctypes.c_size_t,
        ctypes.c_int32,
        F64P,
    ]
    lib.fc_normalize_f32.restype = ctypes.c_int32
    lib.fc_normalize_f32.argtypes = [F64P, ctypes.c_size_t, D, D, ctypes.c_int32, F32P]
    lib.fc_range_indices.restype = ctypes.c_size_t
    lib.fc_range_indices.argtypes = [F64P, F64P, ctypes.c_size_t, D, D, D, D, U32P]
    lib.fc_sample_mask.restype = ctypes.c_int32
    lib.fc_sample_mask.argtypes = [
        U64P,
        ctypes.c_size_t,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint8),
    ]
    lib.fc_stratified_sample_mask.restype = ctypes.c_int32
    lib.fc_stratified_sample_mask.argtypes = [
        U64P,
        U32P,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint8),
    ]
    lib.fc_rasterize.restype = ctypes.c_int32
    lib.fc_rasterize.argtypes = [U8P, ctypes.c_size_t, U8P, ctypes.c_size_t, ctypes.c_size_t]
    lib.fc_local_log_density.restype = ctypes.c_int32
    lib.fc_local_log_density.argtypes = [
        F64P,
        F64P,
        ctypes.c_size_t,
        D,
        D,
        D,
        D,
        Z,
        Z,
        F32P,
    ]
    return lib


def _ptr(a: array, ct):  # noqa: ANN001
    addr, _ = a.buffer_info()
    return ctypes.cast(addr, ctypes.POINTER(ct))


def main() -> None:
    lib = load()
    checks = 0
    size_max = ctypes.c_size_t(-1).value
    F64P = ctypes.POINTER(ctypes.c_double)
    F32P = ctypes.POINTER(ctypes.c_float)
    U64P = ctypes.POINTER(ctypes.c_uint64)
    U32P = ctypes.POINTER(ctypes.c_uint32)
    U8P = ctypes.POINTER(ctypes.c_uint8)
    null_f64 = F64P()
    null_f32 = F32P()
    null_u64 = U64P()
    null_u32 = U32P()

    def ok(cond: bool, msg: str) -> None:
        nonlocal checks
        if not cond:
            raise SystemExit(f"FAIL: {msg}")
        checks += 1

    ok(lib.fc_abi_version() == ABI_VERSION, "abi version")

    # Boundary guardrails: empty inputs may carry null pointers; invalid
    # non-empty null inputs must return sentinels/flags rather than crash.
    ok(lib.fc_encode_f32(null_f64, 0, 0.0, 1.0, null_f32) == 1, "encode_f32 empty/null ok status")
    tiny_f = array("f", [123.0])
    status = lib.fc_encode_f32(null_f64, 1, 0.0, 1.0, _ptr(tiny_f, ctypes.c_float))
    ok(
        status == 0 and tiny_f[0] == 123.0,
        "encode_f32 rejects null input with 0 status, without writing",
    )
    ok(
        lib.fc_m4_indices(null_f64, null_f64, 0, 0.0, 1.0, 4, null_u32) == 0,
        "m4 empty/null returns zero",
    )
    ok(
        lib.fc_m4_indices(null_f64, null_f64, 1, 0.0, 1.0, 4, null_u32) == size_max,
        "m4 non-empty/null sentinel",
    )
    ok(
        lib.fc_zone_maps(
            null_f64, 0, 65_536, null_f64, null_f64, null_u64, null_u64, null_f64, null_f64
        )
        == 0,
        "zone_maps empty/null returns zero",
    )
    ok(
        lib.fc_zone_maps(
            null_f64, 1, 65_536, null_f64, null_f64, null_u64, null_u64, null_f64, null_f64
        )
        == size_max,
        "zone_maps non-empty/null sentinel",
    )
    ok(
        lib.fc_min_max(
            null_f64, 0, ctypes.byref(ctypes.c_double()), ctypes.byref(ctypes.c_double())
        )
        == 0,
        "min_max empty/null returns zero",
    )
    empty_grid = array("f", [99.0]) * 4
    ok(
        lib.fc_bin_2d(
            null_f64, null_f64, 0, 0.0, 1.0, 0.0, 1.0, 2, 2, _ptr(empty_grid, ctypes.c_float)
        )
        == 1
        and list(empty_grid) == [0.0, 0.0, 0.0, 0.0],
        "bin_2d empty/null zeroes grid",
    )
    ok(
        lib.fc_bin_2d(
            null_f64, null_f64, 1, 0.0, 1.0, 0.0, 1.0, 2, 2, _ptr(empty_grid, ctypes.c_float)
        )
        == 0,
        "bin_2d non-empty/null error flag",
    )
    empty_hist = array("d", [99.0]) * 4
    ok(
        lib.fc_histogram_uniform(null_f64, 0, 0.0, 1.0, 4, 0, _ptr(empty_hist, ctypes.c_double))
        == 0
        and list(empty_hist) == [0.0, 0.0, 0.0, 0.0],
        "histogram empty/null zeroes counts",
    )
    ok(
        lib.fc_histogram_uniform(null_f64, 1, 0.0, 1.0, 4, 0, _ptr(empty_hist, ctypes.c_double))
        == size_max,
        "histogram non-empty/null sentinel",
    )
    ok(
        lib.fc_normalize_f32(null_f64, 0, 0.0, 1.0, 0, null_f32) == 1,
        "normalize_f32 empty/null ok status",
    )
    tiny_norm = array("f", [123.0])
    status = lib.fc_normalize_f32(null_f64, 1, 0.0, 1.0, 0, _ptr(tiny_norm, ctypes.c_float))
    ok(
        status == 0 and tiny_norm[0] == 123.0,
        "normalize_f32 rejects null input with 0 status, without writing",
    )
    one_val = array("d", [0.5])
    status = lib.fc_normalize_f32(
        _ptr(one_val, ctypes.c_double), 1, 1.0, 0.0, 0, _ptr(tiny_norm, ctypes.c_float)
    )
    ok(
        status == 0 and tiny_norm[0] == 123.0,
        "normalize_f32 inverted domain now signals 0 (was a silent void)",
    )
    ok(
        lib.fc_range_indices(null_f64, null_f64, 0, 0.0, 1.0, 0.0, 1.0, null_u32) == 0,
        "range_indices empty/null returns zero",
    )
    ok(
        lib.fc_range_indices(null_f64, null_f64, 1, 0.0, 1.0, 0.0, 1.0, null_u32) == size_max,
        "range_indices non-empty/null sentinel",
    )
    # bin_2d_indices: fused grid + visible-row scan. A point exactly on the
    # inclusive hi edge appears in the index list (range_indices semantics)
    # but not in any grid cell (bin_2d's half-open semantics).
    bx = array("d", [0.25, 1.0])
    by = array("d", [0.25, 0.5])
    bgrid = array("f", [9.0]) * 4
    bidx = array("I", [7, 7])
    written = lib.fc_bin_2d_indices(
        _ptr(bx, ctypes.c_double),
        _ptr(by, ctypes.c_double),
        2,
        0.0,
        1.0,
        0.0,
        1.0,
        2,
        2,
        _ptr(bgrid, ctypes.c_float),
        _ptr(bidx, ctypes.c_uint32),
    )
    ok(written == 2 and list(bidx) == [0, 1], "bin_2d_indices inclusive index list")
    ok(sum(bgrid) == 1.0, "bin_2d_indices half-open grid excludes hi edge")
    ok(
        lib.fc_bin_2d_indices(
            null_f64, null_f64, 0, 0.0, 1.0, 0.0, 1.0, 2, 2, _ptr(bgrid, ctypes.c_float), null_u32
        )
        == 0
        and sum(bgrid) == 0.0,
        "bin_2d_indices empty/null zeroes grid, returns zero",
    )
    ok(
        lib.fc_bin_2d_indices(
            null_f64, null_f64, 1, 0.0, 1.0, 0.0, 1.0, 2, 2, _ptr(bgrid, ctypes.c_float), null_u32
        )
        == size_max,
        "bin_2d_indices non-empty/null sentinel",
    )
    # sample_mask: SplitMix64(id + seed) <= threshold, one byte per row.
    ids = array("Q", [0, 1, 2, 3])
    mask = array("B", [9, 9, 9, 9])
    lib.fc_sample_mask(
        _ptr(ids, ctypes.c_uint64),
        4,
        ctypes.c_uint64(0),
        ctypes.c_uint64(2**64 - 1),
        _ptr(mask, ctypes.c_uint8),
    )
    ok(list(mask) == [1, 1, 1, 1], "sample_mask threshold=max keeps all")
    lib.fc_sample_mask(
        _ptr(ids, ctypes.c_uint64),
        4,
        ctypes.c_uint64(0),
        ctypes.c_uint64(0),
        _ptr(mask, ctypes.c_uint8),
    )
    ok(list(mask) == [0, 0, 0, 0], "sample_mask threshold=0 keeps none")
    # SplitMix64(0+0) reference value — must match lod.hash_row_ids bit-for-bit.
    lib.fc_sample_mask(
        _ptr(ids, ctypes.c_uint64),
        1,
        ctypes.c_uint64(0),
        ctypes.c_uint64(0xE220A8397B1DCDAF),
        _ptr(mask, ctypes.c_uint8),
    )
    ok(mask[0] == 1, "sample_mask splitmix64(0) reference vector inclusive")
    lib.fc_sample_mask(
        _ptr(ids, ctypes.c_uint64),
        1,
        ctypes.c_uint64(0),
        ctypes.c_uint64(0xE220A8397B1DCDAF - 1),
        _ptr(mask, ctypes.c_uint8),
    )
    ok(mask[0] == 0, "sample_mask splitmix64(0) reference vector exclusive")
    mask_null = array("B", [7])
    status = lib.fc_sample_mask(
        null_u64, 1, ctypes.c_uint64(0), ctypes.c_uint64(1), _ptr(mask_null, ctypes.c_uint8)
    )
    ok(
        status == 0 and mask_null[0] == 7,
        "sample_mask rejects null input with 0 status, without writing",
    )
    ok(
        lib.fc_sample_mask(
            null_u64, 0, ctypes.c_uint64(0), ctypes.c_uint64(1), ctypes.POINTER(ctypes.c_uint8)()
        )
        == 1,
        "sample_mask empty/null ok status",
    )
    # stratified_sample_mask: per-category thresholds + lowest-hash floor.
    sgroups = array("I", [0, 0, 0, 1])
    smask = array("B", [9, 9, 9, 9])
    status = lib.fc_stratified_sample_mask(
        _ptr(ids, ctypes.c_uint64),
        _ptr(sgroups, ctypes.c_uint32),
        4,
        2,
        ctypes.c_uint64(0),
        ctypes.c_double(1.0),
        ctypes.c_uint64(1),
        _ptr(smask, ctypes.c_uint8),
    )
    ok(
        status == 1 and list(smask) == [1, 1, 1, 1],
        "stratified_sample_mask fraction=1 keeps all",
    )
    status = lib.fc_stratified_sample_mask(
        _ptr(ids, ctypes.c_uint64),
        _ptr(sgroups, ctypes.c_uint32),
        4,
        2,
        ctypes.c_uint64(0),
        ctypes.c_double(1e-18),
        ctypes.c_uint64(1),
        _ptr(smask, ctypes.c_uint8),
    )
    ok(
        status == 1 and sum(smask) == 2 and smask[3] == 1,
        "stratified_sample_mask floor pins one row per category",
    )
    smask_bad = array("B", [7, 7, 7, 7])
    bad_groups = array("I", [0, 0, 0, 5])  # 5 >= n_groups
    ok(
        lib.fc_stratified_sample_mask(
            _ptr(ids, ctypes.c_uint64),
            _ptr(bad_groups, ctypes.c_uint32),
            4,
            2,
            ctypes.c_uint64(0),
            ctypes.c_double(0.5),
            ctypes.c_uint64(1),
            _ptr(smask_bad, ctypes.c_uint8),
        )
        == 0,
        "stratified_sample_mask rejects out-of-range group codes",
    )
    ok(
        lib.fc_stratified_sample_mask(
            null_u64,
            _ptr(sgroups, ctypes.c_uint32),
            4,
            2,
            ctypes.c_uint64(0),
            ctypes.c_double(0.5),
            ctypes.c_uint64(1),
            _ptr(smask_bad, ctypes.c_uint8),
        )
        == 0,
        "stratified_sample_mask rejects null ids with 0 status",
    )
    ok(
        lib.fc_stratified_sample_mask(
            null_u64,
            null_u32,
            0,
            1,
            ctypes.c_uint64(0),
            ctypes.c_double(0.5),
            ctypes.c_uint64(1),
            ctypes.POINTER(ctypes.c_uint8)(),
        )
        == 1,
        "stratified_sample_mask empty/null ok status",
    )
    ok(
        lib.fc_local_log_density(null_f64, null_f64, 0, 0.0, 1.0, 0.0, 1.0, 2, 2, null_f32) == 1,
        "local_log_density empty/null ok",
    )
    ok(
        lib.fc_local_log_density(
            null_f64,
            null_f64,
            1,
            0.0,
            1.0,
            0.0,
            1.0,
            2,
            2,
            _ptr(tiny_norm, ctypes.c_float),
        )
        == 0,
        "local_log_density non-empty/null error flag",
    )

    # encode_f32: the §16 precision claim, verified through the real ABI.
    t0 = 1.6e12
    x = array("d", [t0 + i for i in range(1000)])
    offset = t0 + 500.0
    out = array("f", [0.0]) * len(x)
    lib.fc_encode_f32(_ptr(x, ctypes.c_double), len(x), offset, 1.0, _ptr(out, ctypes.c_float))
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
        _ptr(xs, ctypes.c_double),
        _ptr(ys, ctypes.c_double),
        n,
        0.0,
        float(n),
        buckets,
        _ptr(idx_buf, ctypes.c_uint32),
    )
    idx = set(idx_buf[:written])
    ok(5432 in idx and 7891 in idx, "m4 preserves spikes")
    ok(0 in idx and (n - 1) in idx, "m4 keeps first/last")
    ok(written <= buckets * 4, "m4 bounded output")

    # m4 invalid-arg sentinel (usize::MAX).
    bad = lib.fc_m4_indices(
        _ptr(xs, ctypes.c_double),
        _ptr(ys, ctypes.c_double),
        n,
        5.0,
        5.0,
        buckets,
        _ptr(idx_buf, ctypes.c_uint32),
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
        _ptr(data, ctypes.c_double),
        len(data),
        65536,
        _ptr(zm[0], ctypes.c_double),
        _ptr(zm[1], ctypes.c_double),
        _ptr(cnt, ctypes.c_uint64),
        _ptr(nul, ctypes.c_uint64),
        _ptr(zm[2], ctypes.c_double),
        _ptr(zm[3], ctypes.c_double),
    )
    ok(wrote == 1, "zone_maps chunk count")
    ok(cnt[0] == 9 and nul[0] == 1, "zone_maps counts NaN as null")
    ok(zm[0][0] == 0.0 and zm[1][0] == 9.0, "zone_maps min/max skip NaN")

    # inf must be treated as null too (§19 hardening): min/max stay finite.
    idata = array("d", [1.0, float("inf"), float("-inf"), 3.0])
    izm = [array("d", [0.0]) for _ in range(4)]
    icnt = array("Q", [0])
    inul = array("Q", [0])
    lib.fc_zone_maps(
        _ptr(idata, ctypes.c_double),
        4,
        65536,
        _ptr(izm[0], ctypes.c_double),
        _ptr(izm[1], ctypes.c_double),
        _ptr(icnt, ctypes.c_uint64),
        _ptr(inul, ctypes.c_uint64),
        _ptr(izm[2], ctypes.c_double),
        _ptr(izm[3], ctypes.c_double),
    )
    ok(icnt[0] == 2 and inul[0] == 2, "zone_maps counts inf as null")
    ok(izm[0][0] == 1.0 and izm[1][0] == 3.0, "zone_maps min/max skip inf")

    # min_max sentinel path.
    lo = ctypes.c_double()
    hi = ctypes.c_double()
    got = lib.fc_min_max(_ptr(data, ctypes.c_double), len(data), ctypes.byref(lo), ctypes.byref(hi))
    ok(got == 1 and lo.value == 0.0 and hi.value == 9.0, "min_max ok")
    allnan = array("d", [float("nan")])
    ok(
        lib.fc_min_max(_ptr(allnan, ctypes.c_double), 1, ctypes.byref(lo), ctypes.byref(hi)) == 0,
        "min_max all-NaN returns 0",
    )

    # bin_2d: 4 points, one per quadrant of a 2×2 grid; count conserved, row0 bottom.
    bx = array("d", [0.25, 0.75, 0.25, 0.75])
    by = array("d", [0.25, 0.25, 0.75, 0.75])
    grid = array("f", [0.0]) * 4
    got = lib.fc_bin_2d(
        _ptr(bx, ctypes.c_double),
        _ptr(by, ctypes.c_double),
        4,
        0.0,
        1.0,
        0.0,
        1.0,
        2,
        2,
        _ptr(grid, ctypes.c_float),
    )
    ok(got == 1, "bin_2d ok flag")
    ok(list(grid) == [1.0, 1.0, 1.0, 1.0], "bin_2d one per quadrant")
    ok(sum(grid) == 4.0, "bin_2d conserves count")
    # A dense cluster in one cell dominates.
    cx = array("d", [0.1] * 500 + [0.9])
    cy = array("d", [0.1] * 500 + [0.9])
    g2 = array("f", [0.0]) * 4
    lib.fc_bin_2d(
        _ptr(cx, ctypes.c_double),
        _ptr(cy, ctypes.c_double),
        501,
        0.0,
        1.0,
        0.0,
        1.0,
        2,
        2,
        _ptr(g2, ctypes.c_float),
    )
    ok(g2[0] == 500.0 and g2[3] == 1.0, "bin_2d density hotspot")

    # histogram_uniform: fixed-bin counts, last edge closed.
    hx = array("d", [0.0, 0.2, 0.9, 1.0, 1.1, float("nan"), float("inf")])
    hist = array("d", [0.0]) * 4
    total = lib.fc_histogram_uniform(
        _ptr(hx, ctypes.c_double),
        len(hx),
        0.0,
        1.0,
        4,
        0,
        _ptr(hist, ctypes.c_double),
    )
    ok(total == 4, "histogram valid total")
    ok(list(hist) == [2.0, 0.0, 0.0, 2.0], "histogram counts")

    # normalize_f32: clamp finite values, route non-finite values by mode.
    nx = array("d", [-1.0, 0.0, 5.0, 10.0, 11.0, float("nan"), float("inf")])
    norm = array("f", [0.0]) * len(nx)
    lib.fc_normalize_f32(
        _ptr(nx, ctypes.c_double),
        len(nx),
        0.0,
        10.0,
        0,
        _ptr(norm, ctypes.c_float),
    )
    ok(list(norm) == [0.0, 0.0, 0.5, 1.0, 1.0, 0.0, 0.0], "normalize zero mode")
    lib.fc_normalize_f32(
        _ptr(nx, ctypes.c_double),
        len(nx),
        0.0,
        10.0,
        1,
        _ptr(norm, ctypes.c_float),
    )
    ok(math.isnan(norm[5]) and math.isnan(norm[6]), "normalize nan mode")

    # range_indices: canonical inclusive rectangular selection.
    rx = array("d", [0.0, 1.0, 2.0, 3.0, float("nan")])
    ry = array("d", [0.0, 1.5, 2.5, 4.0, 1.0])
    ridx = array("I", [0]) * len(rx)
    written = lib.fc_range_indices(
        _ptr(rx, ctypes.c_double),
        _ptr(ry, ctypes.c_double),
        len(rx),
        1.0,
        3.0,
        1.0,
        3.0,
        _ptr(ridx, ctypes.c_uint32),
    )
    ok(written == 2 and list(ridx[:written]) == [1, 2], "range_indices")

    # local_log_density: per-point density stays normalized and hotspot wins.
    lx = array("d", [0.1, 0.1, 0.1, 0.9])
    ly = array("d", [0.1, 0.1, 0.1, 0.9])
    lout = array("f", [0.0]) * len(lx)
    got = lib.fc_local_log_density(
        _ptr(lx, ctypes.c_double),
        _ptr(ly, ctypes.c_double),
        len(lx),
        0.0,
        1.0,
        0.0,
        1.0,
        2,
        2,
        _ptr(lout, ctypes.c_float),
    )
    ok(got == 1, "local_log_density ok flag")
    ok(0.0 <= min(lout) <= max(lout) <= 1.0, "local_log_density normalized")
    ok(lout[0] == lout[1] == lout[2] and lout[0] > lout[3], "local_log_density hotspot")

    # tile pyramid (§5 Tier 3): build → count → compose → free, plus stale
    # handle semantics, through the real ABI.
    n_p = 64
    px = array("d", [float(i % 8) + 0.5 for i in range(n_p)])
    py = array("d", [float(i // 8) + 0.5 for i in range(n_p)])
    lib.fc_pyramid_build.restype = ctypes.c_uint64
    lib.fc_pyramid_build.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_uint32,
    ]
    lib.fc_pyramid_count.restype = ctypes.c_int32
    lib.fc_pyramid_count.argtypes = [
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.fc_pyramid_compose.restype = ctypes.c_int32
    lib.fc_pyramid_compose.argtypes = [
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_float),
    ]
    lib.fc_pyramid_free.restype = ctypes.c_int32
    lib.fc_pyramid_free.argtypes = [ctypes.c_uint64]
    handle = lib.fc_pyramid_build(
        _ptr(px, ctypes.c_double), _ptr(py, ctypes.c_double), n_p, 0.0, 8.0, 0.0, 8.0, 8
    )
    ok(handle != 0, "pyramid build returns a handle")
    cnt = ctypes.c_double(0.0)
    ok(
        lib.fc_pyramid_count(ctypes.c_uint64(handle), 0.0, 8.0, 0.0, 8.0, ctypes.byref(cnt)) == 1,
        "pyramid count ok",
    )
    ok(cnt.value == float(n_p), "pyramid count is exact on the full window")
    grid_p = array("f", bytes(4 * 8 * 8))
    lvl = lib.fc_pyramid_compose(
        ctypes.c_uint64(handle), 0.0, 8.0, 0.0, 8.0, 8, 8, _ptr(grid_p, ctypes.c_float)
    )
    ok(lvl == 0, "full-window compose uses level 0")
    ok(sum(grid_p) == float(n_p), "compose conserves the count")
    tiny = array("f", bytes(4 * 64 * 64))
    ok(
        lib.fc_pyramid_compose(
            ctypes.c_uint64(handle), 3.0, 3.1, 3.0, 3.1, 64, 64, _ptr(tiny, ctypes.c_float)
        )
        == -2,
        "outresolving window is refused, not faked",
    )
    ok(lib.fc_pyramid_free(ctypes.c_uint64(handle)) == 1, "pyramid free")
    ok(lib.fc_pyramid_free(ctypes.c_uint64(handle)) == 0, "double free is an error code")

    # rasterize: caller-owned RGBA8 framebuffer; empty command buffer clears to
    # transparent, a malformed op is rejected, and a null out is refused.
    null_u8 = U8P()
    fb = array("B", [9]) * (2 * 2 * 4)
    ok(
        lib.fc_rasterize(null_u8, 0, _ptr(fb, ctypes.c_uint8), 2, 2) == 1
        and all(v == 0 for v in fb),
        "rasterize empty buffer clears framebuffer",
    )
    bad = array("B", [1, 9, 9, 9, 9])  # FILL_POLY claiming a huge point count
    ok(
        lib.fc_rasterize(_ptr(bad, ctypes.c_uint8), len(bad), _ptr(fb, ctypes.c_uint8), 2, 2) == 0,
        "rasterize rejects a malformed command buffer",
    )
    ok(lib.fc_rasterize(null_u8, 0, null_u8, 2, 2) == 0, "rasterize refuses a null framebuffer")

    print(f"ABI smoke: {checks} checks passed against {_lib_name()}")


if __name__ == "__main__":
    main()
