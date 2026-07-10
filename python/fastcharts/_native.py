"""ctypes binding to the native Rust core (design dossier §32).

The core is a dependency-free C-ABI cdylib; every call here passes NumPy buffer
pointers directly — zero copies across the Python/Rust boundary (§4: one
physical copy of every value; §29: in-process transport is 0-copy).

This module raises ImportError if the library is missing or ABI-mismatched;
`fastcharts.kernels` re-raises that with remediation guidance. There is no
pure-Python fallback — the native core is required (§33: no-wheel behavior is
defined, and it is a loud failure, never a silent degrade).
"""

from __future__ import annotations

import ctypes
import operator
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import numpy.typing as npt

from .config import MAX_SCREEN_DIM

ABI_VERSION = 12

# Rust reports invalid arguments (and, via the ffi_guard panic shield, any
# internal panic) by returning `usize::MAX` from size-returning entry points.
# `usize` is `c_size_t`, whose width is platform-dependent — 32 bits on
# armv7/win32/wasm32 — so the sentinel must be derived from ctypes. Comparing
# against 2**64-1 would never match on 32-bit targets and an error return
# would be sliced as data.
_USIZE_MAX = ctypes.c_size_t(-1).value


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
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_encode_f32.restype = ctypes.c_int32
    lib.fc_encode_f32.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_void_p,
    ]
    lib.fc_m4_indices.restype = ctypes.c_size_t
    lib.fc_m4_indices.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    lib.fc_min_max.restype = ctypes.c_int32
    lib.fc_min_max.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    lib.fc_is_sorted.restype = ctypes.c_int32
    lib.fc_is_sorted.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.fc_bin_2d.restype = ctypes.c_int32
    lib.fc_bin_2d.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    lib.fc_bin_2d_indices.restype = ctypes.c_size_t
    lib.fc_bin_2d_indices.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_histogram_uniform.restype = ctypes.c_size_t
    lib.fc_histogram_uniform.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_int32,
        ctypes.c_void_p,
    ]
    lib.fc_normalize_f32.restype = ctypes.c_int32
    lib.fc_normalize_f32.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int32,
        ctypes.c_void_p,
    ]
    lib.fc_range_indices.restype = ctypes.c_size_t
    lib.fc_range_indices.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_void_p,
    ]
    lib.fc_sample_mask.restype = ctypes.c_int32
    lib.fc_sample_mask.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_void_p,
    ]
    lib.fc_stratified_sample_mask.restype = ctypes.c_int32
    lib.fc_stratified_sample_mask.argtypes = [
        ctypes.c_void_p,  # ids
        ctypes.c_void_p,  # groups
        ctypes.c_size_t,  # len
        ctypes.c_size_t,  # n_groups
        ctypes.c_uint64,  # seed
        ctypes.c_double,  # fraction
        ctypes.c_uint64,  # min_count
        ctypes.c_void_p,  # out
    ]
    lib.fc_pyramid_build.restype = ctypes.c_uint64
    lib.fc_pyramid_build.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
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
        ctypes.c_void_p,
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
        ctypes.c_void_p,
    ]
    lib.fc_pyramid_free.restype = ctypes.c_int32
    lib.fc_pyramid_free.argtypes = [ctypes.c_uint64]
    lib.fc_local_log_density.restype = ctypes.c_int32
    lib.fc_local_log_density.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    lib.fc_rasterize.restype = ctypes.c_int32
    lib.fc_rasterize.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.c_void_p,  # out (w*h*4 RGBA8)
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.fc_css_check.restype = ctypes.c_int32
    lib.fc_css_check.argtypes = [
        ctypes.c_uint32,  # kind (0 decl, 1 color, 2 length list, 3 number)
        ctypes.c_char_p,  # prop (UTF-8; null only at len 0)
        ctypes.c_size_t,  # prop_len
        ctypes.c_char_p,  # value (UTF-8)
        ctypes.c_size_t,  # value_len
        ctypes.c_void_p,  # out_rgba (4 f32s; written for statically-parsed colors)
    ]
    return lib


_lib = _load()


def _as_f64(arr: npt.NDArray[np.float64], label: str = "data") -> npt.NDArray[np.float64]:
    out = np.ascontiguousarray(arr, dtype=np.float64)
    if out.ndim != 1:
        raise ValueError(f"{label} must be 1-D, got shape {out.shape}")
    return out


def _ptr_f64(arr: npt.NDArray[np.float64]) -> int:
    # Raw address int for a c_void_p parameter: ~2x cheaper per call than
    # `ctypes.data_as(...)`, which allocates a fresh pointer object. The
    # typed wrappers above are the type-safety layer (`_as_f64` etc.), so
    # the C boundary can take the untyped address.
    return arr.ctypes.data


def _ptr_u8(arr: npt.NDArray[np.uint8]) -> int:
    return arr.ctypes.data


def _positive_int(value: int, label: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a positive integer")
    try:
        out = operator.index(value)
    except TypeError as e:
        raise ValueError(f"{label} must be a positive integer") from e
    if out <= 0:
        raise ValueError(f"{label} must be > 0")
    return int(out)


def _bounded_positive_int(value: int, label: str, max_value: int = MAX_SCREEN_DIM) -> int:
    out = _positive_int(value, label)
    if out > max_value:
        raise ValueError(f"{label} must be <= {max_value}")
    return out


def _finite_float(value: float, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite real number")
    out = float(value)
    if not np.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def _finite_increasing(lo: float, hi: float, label: str) -> tuple[float, float]:
    lo_f = _finite_float(lo, label)
    hi_f = _finite_float(hi, label)
    if not hi_f > lo_f:
        raise ValueError(f"{label} must be finite and increasing")
    return lo_f, hi_f


def _finite_ordered(lo: float, hi: float, label: str) -> tuple[float, float]:
    lo_f = _finite_float(lo, label)
    hi_f = _finite_float(hi, label)
    if hi_f < lo_f:
        raise ValueError(f"{label} must be finite and ordered low-to-high")
    return lo_f, hi_f


def _pyramid_handle(value: int) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("pyramid handle must be an integer handle")
    try:
        out = operator.index(value)
    except TypeError as e:
        raise ValueError("pyramid handle must be an integer handle") from e
    if out < 0:
        raise ValueError("pyramid handle must be non-negative")
    return int(out)


def _pyramid_base_dim(value: int) -> int:
    out = _bounded_positive_int(value, "base_dim")
    if out < 2 or out & (out - 1):
        raise ValueError("base_dim must be a power-of-two integer >= 2")
    return out


def zone_maps(
    data: npt.NDArray[np.float64], chunk_size: int = 65_536
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.uint64],
    npt.NDArray[np.uint64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Per-chunk (min, max, count, null_count, sum, sum_sq, positive_min,
    positive_max) — §22."""
    chunk_size = _positive_int(chunk_size, "chunk_size")
    data = _as_f64(data, "data")
    n = len(data)
    n_chunks = max(1, -(-n // chunk_size)) if n else 0
    if n == 0:
        empty_f = np.empty(0, dtype=np.float64)
        empty_u = np.empty(0, dtype=np.uint64)
        return (
            empty_f,
            empty_f,
            empty_u,
            empty_u,
            empty_f.copy(),
            empty_f.copy(),
            empty_f.copy(),
            empty_f.copy(),
        )
    mins = np.empty(n_chunks, dtype=np.float64)
    maxs = np.empty(n_chunks, dtype=np.float64)
    counts = np.empty(n_chunks, dtype=np.uint64)
    nulls = np.empty(n_chunks, dtype=np.uint64)
    sums = np.empty(n_chunks, dtype=np.float64)
    sum_sqs = np.empty(n_chunks, dtype=np.float64)
    positive_mins = np.empty(n_chunks, dtype=np.float64)
    positive_maxs = np.empty(n_chunks, dtype=np.float64)
    written = _lib.fc_zone_maps(
        _ptr_f64(data),
        n,
        chunk_size,
        _ptr_f64(mins),
        _ptr_f64(maxs),
        counts.ctypes.data,
        nulls.ctypes.data,
        _ptr_f64(sums),
        _ptr_f64(sum_sqs),
        _ptr_f64(positive_mins),
        _ptr_f64(positive_maxs),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid zone_maps arguments")
    if written != n_chunks:
        raise RuntimeError(
            f"fastcharts native zone_maps wrote {written} chunks, expected {n_chunks}"
        )
    return mins, maxs, counts, nulls, sums, sum_sqs, positive_mins, positive_maxs


def encode_f32(
    data: npt.NDArray[np.float64], offset: float, scale: float = 1.0
) -> npt.NDArray[np.float32]:
    """Relative-f32 encode `(v - offset) * scale` — §4/§16."""
    data = _as_f64(data, "data")
    offset = _finite_float(offset, "offset")
    scale = _finite_float(scale, "scale")
    if len(data) == 0:  # empty NumPy arrays may carry a null pointer
        return np.empty(0, dtype=np.float32)
    out = np.empty(len(data), dtype=np.float32)
    ok = _lib.fc_encode_f32(_ptr_f64(data), len(data), offset, scale, out.ctypes.data)
    if ok != 1:
        raise RuntimeError("fastcharts native encode_f32 failed (output undefined)")
    return out


def m4_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    n_buckets: int,
) -> npt.NDArray[np.uint32]:
    """M4 decimation indices over the visible window — §5 Tier 1."""
    n_buckets = _bounded_positive_int(n_buckets, "n_buckets")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
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
        out.ctypes.data,
    )
    if written == _USIZE_MAX:
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
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    y0, y1 = _finite_increasing(y0, y1, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
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
            out.ctypes.data,
        )
        if not ok:
            raise ValueError("invalid bin_2d arguments")
    return out


def bin_2d_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    w: int,
    h: int,
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.uint32]]:
    """Fused density scan: `(bin_2d grid, range_indices rows)` in one pass.

    Each output is bitwise identical to its standalone kernel (asserted by the
    parity test); fusing halves the column traffic on the Tier-2 density path,
    which reads the full x/y columns twice otherwise.
    """
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    y0, y1 = _finite_increasing(y0, y1, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    grid = np.zeros((h, w), dtype=np.float32)
    idx = np.empty(len(x), dtype=np.uint32)
    if len(x) == 0:
        return grid, idx
    written = _lib.fc_bin_2d_indices(
        _ptr_f64(x),
        _ptr_f64(y),
        len(x),
        x0,
        x1,
        y0,
        y1,
        w,
        h,
        grid.ctypes.data,
        idx.ctypes.data,
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid bin_2d_indices arguments")
    return grid, idx[:written].copy()


def is_sorted(data: npt.NDArray[np.float64]) -> bool:
    """Non-decreasing check with NaN-poisoning (any NaN fails its pairs) —
    identical to ``np.all(np.diff(data) >= 0)`` without the two temporaries."""
    data = _as_f64(data, "data")
    if len(data) < 2:
        return True
    return bool(_lib.fc_is_sorted(_ptr_f64(data), len(data)))


def min_max(data: npt.NDArray[np.float64]) -> Optional[tuple[float, float]]:
    """NaN-skipping min/max; None for empty/all-NaN input."""
    data = _as_f64(data, "data")
    if len(data) == 0:
        return None
    lo = ctypes.c_double()
    hi = ctypes.c_double()
    ok = _lib.fc_min_max(_ptr_f64(data), len(data), ctypes.byref(lo), ctypes.byref(hi))
    return (lo.value, hi.value) if ok else None


def histogram_uniform(
    data: npt.NDArray[np.float64],
    lo: float,
    hi: float,
    n_bins: int,
    *,
    density: bool = False,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Uniform fixed-bin histogram — one Rust pass, no finite temp copy."""
    n_bins = _bounded_positive_int(n_bins, "n_bins")
    lo, hi = _finite_increasing(lo, hi, "histogram range")
    data = _as_f64(data, "data")
    counts = np.empty(n_bins, dtype=np.float64)
    written = _lib.fc_histogram_uniform(
        _ptr_f64(data),
        len(data),
        lo,
        hi,
        n_bins,
        int(density),
        _ptr_f64(counts),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid histogram arguments")
    edges = np.linspace(lo, hi, n_bins + 1, dtype=np.float64)
    return counts, edges


def normalize_f32(
    data: npt.NDArray[np.float64],
    domain: tuple[float, float],
    *,
    nonfinite: str = "zero",
) -> npt.NDArray[np.float32]:
    """Normalize to f32 [0,1]. nonfinite='zero' or 'nan'."""
    if nonfinite not in {"zero", "nan"}:
        raise ValueError("nonfinite must be 'zero' or 'nan'")
    data = _as_f64(data, "data")
    try:
        lo_raw, hi_raw = domain
    except (TypeError, ValueError) as e:
        raise ValueError("domain must contain exactly two finite increasing values") from e
    lo, hi = _finite_increasing(lo_raw, hi_raw, "domain")
    out = np.empty(len(data), dtype=np.float32)
    nan_mode = 1 if nonfinite == "nan" else 0
    if len(data):
        ok = _lib.fc_normalize_f32(_ptr_f64(data), len(data), lo, hi, nan_mode, out.ctypes.data)
        if ok != 1:
            raise RuntimeError("fastcharts native normalize_f32 failed (output undefined)")
    return out


def range_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
) -> npt.NDArray[np.uint32]:
    """Canonical row indices in an inclusive rectangular window."""
    lo_x, hi_x = _finite_ordered(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_ordered(lo_y, hi_y, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    out = np.empty(len(x), dtype=np.uint32)
    if len(x) == 0:
        return out
    written = _lib.fc_range_indices(
        _ptr_f64(x),
        _ptr_f64(y),
        len(x),
        lo_x,
        hi_x,
        lo_y,
        hi_y,
        out.ctypes.data,
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid range_indices arguments")
    return out[:written].copy()


def sample_mask(
    ids: npt.NDArray[np.uint64],
    seed: int,
    threshold: int,
) -> npt.NDArray[np.bool_]:
    """Deterministic sampling mask: `splitmix64(ids + seed) <= threshold`.

    Bit-identical to `lod.hash_row_ids(ids, seed=seed) <= threshold` (the
    NumPy reference, asserted by the parity test), fused into one native pass
    with no full-width u64 temporaries.
    """
    ids = np.ascontiguousarray(ids, dtype=np.uint64)
    if ids.ndim != 1:
        raise ValueError("ids must be a one-dimensional uint64 array")
    out = np.empty(len(ids), dtype=np.uint8)
    if len(ids):
        ok = _lib.fc_sample_mask(
            ids.ctypes.data,
            len(ids),
            ctypes.c_uint64(int(seed)),
            ctypes.c_uint64(int(threshold)),
            out.ctypes.data,
        )
        if ok != 1:
            raise RuntimeError("fastcharts native sample_mask failed (output undefined)")
    return out.view(np.bool_)


def stratified_sample_mask(
    ids: npt.NDArray[np.uint64],
    groups: npt.NDArray[np.uint32],
    n_groups: int,
    seed: int,
    fraction: float,
    min_count: int,
) -> npt.NDArray[np.bool_]:
    """Category-stratified deterministic sampling mask (§5/§17).

    Per-category keep fractions scale as `min(1, fraction * sqrt(n / count))`
    with a `min_count` lowest-hash floor per category. Bit-identical to the
    per-category NumPy reference in `fastcharts.lod` (asserted by the parity
    test), fused into one native pass instead of O(n · n_groups) rescans.
    """
    ids = np.ascontiguousarray(ids, dtype=np.uint64)
    groups = np.ascontiguousarray(groups, dtype=np.uint32)
    if ids.ndim != 1 or groups.ndim != 1:
        raise ValueError("ids and groups must be one-dimensional arrays")
    if len(ids) != len(groups):
        raise ValueError("ids and groups must have equal length")
    n_groups = _positive_int(n_groups, "n_groups")
    fraction = _finite_float(fraction, "fraction")
    if fraction <= 0.0:
        raise ValueError("fraction must be > 0")
    if isinstance(min_count, (bool, np.bool_)):
        raise ValueError("min_count must be a non-negative integer")
    min_count = operator.index(min_count)
    if min_count < 0:
        raise ValueError("min_count must be a non-negative integer")
    out = np.empty(len(ids), dtype=np.uint8)
    if len(ids):
        ok = _lib.fc_stratified_sample_mask(
            ids.ctypes.data,
            groups.ctypes.data,
            len(ids),
            n_groups,
            ctypes.c_uint64(int(seed)),
            ctypes.c_double(fraction),
            ctypes.c_uint64(min_count),
            out.ctypes.data,
        )
        if ok != 1:
            raise ValueError(
                "invalid stratified_sample_mask arguments (group codes must be < n_groups)"
            )
    return out.view(np.bool_)


def pyramid_build(
    x: "npt.NDArray[np.float64]",
    y: "npt.NDArray[np.float64]",
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    base_dim: int,
) -> int:
    """Build a count pyramid (§5 Tier 3). Returns a handle, 0 on failure."""
    base_dim = _pyramid_base_dim(base_dim)
    x0, x1 = _finite_increasing(x0, x1, "x range")
    y0, y1 = _finite_increasing(y0, y1, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if len(x) == 0:
        return 0
    return int(
        _lib.fc_pyramid_build(
            x.ctypes.data,
            y.ctypes.data,
            len(x),
            x0,
            x1,
            y0,
            y1,
            base_dim,
        )
    )


def pyramid_count(handle: int, lo_x: float, hi_x: float, lo_y: float, hi_y: float):
    handle = _pyramid_handle(handle)
    lo_x, hi_x = _finite_increasing(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_increasing(lo_y, hi_y, "y range")
    out = ctypes.c_double(0.0)
    ok = _lib.fc_pyramid_count(
        ctypes.c_uint64(handle),
        lo_x,
        hi_x,
        lo_y,
        hi_y,
        ctypes.byref(out),
    )
    return float(out.value) if ok == 1 else None


def pyramid_compose(
    handle: int, lo_x: float, hi_x: float, lo_y: float, hi_y: float, w: int, h: int
):
    """(grid f32 [h*w], level) from the pyramid, or None when the window
    outresolves it (caller falls back to an exact re-bin, §28)."""
    handle = _pyramid_handle(handle)
    lo_x, hi_x = _finite_increasing(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_increasing(lo_y, hi_y, "y range")
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    out = np.zeros(w * h, dtype=np.float32)
    level = _lib.fc_pyramid_compose(
        ctypes.c_uint64(handle),
        lo_x,
        hi_x,
        lo_y,
        hi_y,
        w,
        h,
        out.ctypes.data,
    )
    if level < 0:
        return None
    return out, int(level)


def pyramid_free(handle: int) -> bool:
    return _lib.fc_pyramid_free(ctypes.c_uint64(_pyramid_handle(handle))) == 1


def local_log_density(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
    w: int,
    h: int,
) -> npt.NDArray[np.float32]:
    """Per-point log-normalized local density in [0,1]."""
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    lo_x, hi_x = _finite_increasing(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_increasing(lo_y, hi_y, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    out = np.empty(len(x), dtype=np.float32)
    if len(x):
        ok = _lib.fc_local_log_density(
            _ptr_f64(x),
            _ptr_f64(y),
            len(x),
            lo_x,
            hi_x,
            lo_y,
            hi_y,
            w,
            h,
            out.ctypes.data,
        )
        if not ok:
            raise ValueError("invalid local_log_density arguments")
    return out


def rasterize(cmds: bytes, w: int, h: int) -> npt.NDArray[np.uint8]:
    """Paint a display-list command buffer (`_raster.py`) into an ``(h, w, 4)``
    straight-alpha RGBA8 image via the native rasterizer. Raises on a malformed
    buffer (the Rust side returns 0 = output undefined)."""
    w = _positive_int(w, "raster width")
    h = _positive_int(h, "raster height")
    buf = np.frombuffer(cmds, dtype=np.uint8)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    cmd_ptr = _ptr_u8(buf) if buf.size else None
    ok = _lib.fc_rasterize(cmd_ptr, buf.size, _ptr_u8(out), w, h)
    if not ok:
        raise ValueError("native rasterizer rejected the command buffer")
    return out


# fc_css_check kinds — keep in sync with `src/lib.rs`.
CSS_DECLARATION = 0
CSS_COLOR = 1
CSS_LENGTH = 2
CSS_NUMBER = 3


def css_check(
    kind: int, value: str, prop: str = ""
) -> tuple[int, Optional[tuple[float, float, float, float]]]:
    """Validate a CSS value against the native grammar (`src/css.rs`).

    Returns ``(status, rgba)``: status 1 = parsed statically, 2 = valid but
    browser-resolved (`var()`/`oklch()`/`calc()`/unknown-property
    passthrough), negative = error code (see `fc_css_check` docs). ``rgba``
    is the 0..1 channel tuple for statically-resolved colors, else None
    (`currentColor` parses with no static channels). The error-message
    mapping lives in `_validate.py`; this wrapper stays mechanical.
    """
    vb = value.encode("utf-8")
    pb = prop.encode("utf-8")
    out = (ctypes.c_float * 4)(float("nan"), 0.0, 0.0, 0.0)
    status = int(_lib.fc_css_check(kind, pb or None, len(pb), vb or None, len(vb), out))
    wrote = status == 1 and out[0] == out[0]  # NaN sentinel: untouched = no static color
    return status, (out[0], out[1], out[2], out[3]) if wrote else None
