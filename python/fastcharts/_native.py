"""ctypes binding to the native Rust core (design dossier §32).

The core is a dependency-free C-ABI cdylib; every call here passes NumPy buffer
pointers directly — zero copies across the Python/Rust boundary (§4: one
physical copy of every value; §29: in-process transport is 0-copy).

This module raises ImportError if the library is missing or ABI-mismatched;
`fastcharts.kernels` catches that and falls back to NumPy *loudly* (§33: no-wheel
behavior is defined, never silent).
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import numpy.typing as npt

ABI_VERSION = 2

_F64_P = ctypes.POINTER(ctypes.c_double)
_F32_P = ctypes.POINTER(ctypes.c_float)
_U64_P = ctypes.POINTER(ctypes.c_uint64)
_U32_P = ctypes.POINTER(ctypes.c_uint32)


def _lib_filename() -> str:
    if sys.platform == "win32":
        return "fastcharts_core.dll"
    if sys.platform == "darwin":
        return "libfastcharts_core.dylib"
    return "libfastcharts_core.so"


def _find_library() -> Path:
    name = _lib_filename()
    candidates = []
    env = os.environ.get("FASTCHARTS_NATIVE_LIB")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve().parent
    candidates.append(here / "_native_lib" / name)
    # Dev checkout: cargo target dir at the repo root.
    repo_root = here.parent.parent
    candidates.append(repo_root / "target" / "release" / name)
    candidates.append(repo_root / "target" / "debug" / name)
    for c in candidates:
        if c.exists():
            return c
    raise ImportError(
        f"fastcharts native core not found (looked for {name} in "
        f"{[str(c) for c in candidates]}). No prebuilt wheel exists for this "
        "platform — see the fastcharts README for supported platforms, or build "
        "from source with `cargo build --release`."
    )


def _load() -> ctypes.CDLL:
    lib = ctypes.CDLL(str(_find_library()))

    lib.fc_abi_version.restype = ctypes.c_uint32
    lib.fc_abi_version.argtypes = []
    got = lib.fc_abi_version()
    if got != ABI_VERSION:
        raise ImportError(
            f"fastcharts native core ABI mismatch: python wrapper expects "
            f"{ABI_VERSION}, library reports {got}. Reinstall fastcharts so the "
            "wheel and package versions match."
        )

    lib.fc_zone_maps.restype = ctypes.c_size_t
    lib.fc_zone_maps.argtypes = [
        _F64_P,
        ctypes.c_size_t,
        ctypes.c_size_t,
        _F64_P,
        _F64_P,
        _U64_P,
        _U64_P,
        _F64_P,
        _F64_P,
    ]
    lib.fc_encode_f32.restype = None
    lib.fc_encode_f32.argtypes = [
        _F64_P,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        _F32_P,
    ]
    lib.fc_m4_indices.restype = ctypes.c_size_t
    lib.fc_m4_indices.argtypes = [
        _F64_P,
        _F64_P,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        _U32_P,
    ]
    lib.fc_min_max.restype = ctypes.c_int32
    lib.fc_min_max.argtypes = [_F64_P, ctypes.c_size_t, _F64_P, _F64_P]
    lib.fc_bin_2d.restype = ctypes.c_int32
    lib.fc_bin_2d.argtypes = [
        _F64_P,
        _F64_P,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_size_t,
        _F32_P,
    ]
    return lib


_lib = _load()


def _as_f64(arr: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    out = np.ascontiguousarray(arr, dtype=np.float64)
    return out


def _ptr_f64(arr: npt.NDArray[np.float64]):  # noqa: ANN202
    return arr.ctypes.data_as(_F64_P)


def zone_maps(
    data: npt.NDArray[np.float64], chunk_size: int = 65_536
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.uint64],
    npt.NDArray[np.uint64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Per-chunk (min, max, count, null_count, sum, sum_sq) — §22."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    data = _as_f64(data)
    n = len(data)
    n_chunks = max(1, -(-n // chunk_size)) if n else 0
    if n == 0:
        empty_f = np.empty(0, dtype=np.float64)
        empty_u = np.empty(0, dtype=np.uint64)
        return empty_f, empty_f, empty_u, empty_u, empty_f.copy(), empty_f.copy()
    mins = np.empty(n_chunks, dtype=np.float64)
    maxs = np.empty(n_chunks, dtype=np.float64)
    counts = np.empty(n_chunks, dtype=np.uint64)
    nulls = np.empty(n_chunks, dtype=np.uint64)
    sums = np.empty(n_chunks, dtype=np.float64)
    sum_sqs = np.empty(n_chunks, dtype=np.float64)
    written = _lib.fc_zone_maps(
        _ptr_f64(data),
        n,
        chunk_size,
        _ptr_f64(mins),
        _ptr_f64(maxs),
        counts.ctypes.data_as(_U64_P),
        nulls.ctypes.data_as(_U64_P),
        _ptr_f64(sums),
        _ptr_f64(sum_sqs),
    )
    assert written == n_chunks
    return mins, maxs, counts, nulls, sums, sum_sqs


def encode_f32(
    data: npt.NDArray[np.float64], offset: float, scale: float = 1.0
) -> npt.NDArray[np.float32]:
    """Relative-f32 encode `(v - offset) * scale` — §4/§16."""
    data = _as_f64(data)
    if len(data) == 0:  # empty NumPy arrays may carry a null pointer
        return np.empty(0, dtype=np.float32)
    out = np.empty(len(data), dtype=np.float32)
    _lib.fc_encode_f32(_ptr_f64(data), len(data), offset, scale, out.ctypes.data_as(_F32_P))
    return out


def m4_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    n_buckets: int,
) -> npt.NDArray[np.uint32]:
    """M4 decimation indices over the visible window — §5 Tier 1."""
    if n_buckets <= 0:
        raise ValueError("n_buckets must be > 0")
    if not x1 > x0:
        raise ValueError("x1 must be > x0")
    x = _as_f64(x)
    y = _as_f64(y)
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if len(x) == 0:
        return np.empty(0, dtype=np.uint32)
    out = np.empty(n_buckets * 4, dtype=np.uint32)
    written = _lib.fc_m4_indices(
        _ptr_f64(x),
        _ptr_f64(y),
        len(x),
        x0,
        x1,
        n_buckets,
        out.ctypes.data_as(_U32_P),
    )
    if written == np.iinfo(np.uint64).max:  # usize::MAX sentinel
        raise ValueError("invalid m4 arguments")
    return out[:written].copy()


def bin_2d(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    w: int,
    h: int,
) -> npt.NDArray[np.float32]:
    """2D density grid (h, w) f32, row 0 = bottom — §5 Tier 2."""
    if not (w > 0 and h > 0 and x1 > x0 and y1 > y0):
        raise ValueError("require w>0, h>0, x1>x0, y1>y0")
    x = _as_f64(x)
    y = _as_f64(y)
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    out = np.zeros((h, w), dtype=np.float32)
    if len(x):
        ok = _lib.fc_bin_2d(
            _ptr_f64(x),
            _ptr_f64(y),
            len(x),
            x0,
            x1,
            y0,
            y1,
            w,
            h,
            out.ctypes.data_as(_F32_P),
        )
        if not ok:
            raise ValueError("invalid bin_2d arguments")
    return out


def min_max(data: npt.NDArray[np.float64]) -> Optional[tuple[float, float]]:
    """NaN-skipping min/max; None for empty/all-NaN input."""
    data = _as_f64(data)
    if len(data) == 0:
        return None
    lo = ctypes.c_double()
    hi = ctypes.c_double()
    ok = _lib.fc_min_max(_ptr_f64(data), len(data), ctypes.byref(lo), ctypes.byref(hi))
    return (lo.value, hi.value) if ok else None
