"""ctypes binding to the native Rust core (design dossier §32).

The core is a C-ABI cdylib; every call here passes NumPy buffer pointers
directly — zero copies across the Python/Rust boundary (§4: one
physical copy of every value; §29: in-process transport is 0-copy).

This module raises ImportError if the library is missing or ABI-mismatched;
`xy.kernels` re-raises that with remediation guidance. There is no
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

from .config import MAX_CONTOUR_WORK, MAX_SCREEN_DIM

ABI_VERSION = 17

# Rust reports invalid arguments (and, via the ffi_guard panic shield, any
# internal panic) by returning `usize::MAX` from size-returning entry points.
# `usize` is `c_size_t`, whose width is platform-dependent — 32 bits on
# armv7/win32/wasm32 — so the sentinel must be derived from ctypes. Comparing
# against 2**64-1 would never match on 32-bit targets and an error return
# would be sliced as data.
_USIZE_MAX = ctypes.c_size_t(-1).value


def _lib_filename() -> str:
    if sys.platform == "win32":
        return "xy_core.dll"
    if sys.platform == "darwin":
        return "libxy_core.dylib"
    return "libxy_core.so"


def _find_library() -> Path:
    name = _lib_filename()
    candidates = []
    env = os.environ.get("XY_NATIVE_LIB")
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
        f"xy native core not found (looked for {name} in "
        f"{[str(c) for c in candidates]}). No prebuilt wheel exists for this "
        "platform — see the xy README for supported platforms, or build "
        "from source with `cargo build --release`."
    )


def _load() -> ctypes.CDLL:
    lib = ctypes.CDLL(str(_find_library()))

    lib.fc_abi_version.restype = ctypes.c_uint32
    lib.fc_abi_version.argtypes = []
    got = lib.fc_abi_version()
    if got != ABI_VERSION:
        raise ImportError(
            f"xy native core ABI mismatch: python wrapper expects "
            f"{ABI_VERSION}, library reports {got}. Reinstall xy so the "
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
    lib.fc_stacked_bounds.restype = ctypes.c_int32
    lib.fc_stacked_bounds.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_histogram2d.restype = ctypes.c_int32
    lib.fc_histogram2d.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    lib.fc_quad_mesh_triangles.restype = ctypes.c_size_t
    lib.fc_quad_mesh_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_sector_triangles.restype = ctypes.c_size_t
    lib.fc_sector_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.fc_rfft.restype = ctypes.c_int32
    lib.fc_rfft.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_welch_spectra.restype = ctypes.c_int32
    lib.fc_welch_spectra.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_spectrogram.restype = ctypes.c_int32
    lib.fc_spectrogram.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_correlation.restype = ctypes.c_int32
    lib.fc_correlation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_weighted_ecdf.restype = ctypes.c_size_t
    lib.fc_weighted_ecdf.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_indexed_triangles.restype = ctypes.c_size_t
    lib.fc_indexed_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_triangle_edges.restype = ctypes.c_size_t
    lib.fc_triangle_edges.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_delaunay_triangles.restype = ctypes.c_size_t
    lib.fc_delaunay_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.fc_polygon_triangles.restype = ctypes.c_size_t
    lib.fc_polygon_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.fc_marching_triangles.restype = ctypes.c_size_t
    lib.fc_marching_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.fc_vector_segments.restype = ctypes.c_size_t
    lib.fc_vector_segments.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_uint32,
        ctypes.c_double,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.fc_streamlines.restype = ctypes.c_size_t
    lib.fc_streamlines.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.fc_marching_squares.restype = ctypes.c_size_t
    lib.fc_marching_squares.argtypes = [
        ctypes.c_void_p,  # z (rows * cols f64s)
        ctypes.c_size_t,  # rows
        ctypes.c_size_t,  # cols
        ctypes.c_void_p,  # x_coords (cols f64s)
        ctypes.c_void_p,  # y_coords (rows f64s)
        ctypes.c_void_p,  # levels (n_levels f64s)
        ctypes.c_size_t,  # n_levels
        ctypes.c_void_p,  # x0 output
        ctypes.c_void_p,  # x1 output
        ctypes.c_void_p,  # y0 output
        ctypes.c_void_p,  # y1 output
        ctypes.c_void_p,  # level output
        ctypes.c_size_t,  # output capacity in segments
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
    lib.fc_rasterize_png.restype = ctypes.c_size_t
    lib.fc_rasterize_png.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.c_void_p,  # out PNG bytes
        ctypes.c_size_t,  # out_capacity
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.fc_heatmap_rgba.restype = ctypes.c_int32
    lib.fc_heatmap_rgba.argtypes = [
        ctypes.c_void_p,  # raw f64
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
        ctypes.c_void_p,  # RGB stops
        ctypes.c_size_t,  # stop_count
        ctypes.c_uint8,  # alpha
        ctypes.c_void_p,  # out RGBA8
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
    # Two block allocations (6 f64 rows + 2 u64 rows) instead of eight
    # scattered ones: zone maps run on every ingest, and the allocator +
    # `.ctypes` round-trips were a measurable slice of small-chart builds.
    # Row views stay C-contiguous, and both dtypes are 8 bytes wide.
    f64_rows = np.empty((6, n_chunks), dtype=np.float64)
    u64_rows = np.empty((2, n_chunks), dtype=np.uint64)
    f64_ptr = f64_rows.ctypes.data
    u64_ptr = u64_rows.ctypes.data
    row_bytes = n_chunks * 8
    written = _lib.fc_zone_maps(
        _ptr_f64(data),
        n,
        chunk_size,
        f64_ptr,  # mins
        f64_ptr + row_bytes,  # maxs
        u64_ptr,  # counts
        u64_ptr + row_bytes,  # null counts
        f64_ptr + 2 * row_bytes,  # sums
        f64_ptr + 3 * row_bytes,  # sum_sqs
        f64_ptr + 4 * row_bytes,  # positive_mins
        f64_ptr + 5 * row_bytes,  # positive_maxs
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid zone_maps arguments")
    if written != n_chunks:
        raise RuntimeError(f"xy native zone_maps wrote {written} chunks, expected {n_chunks}")
    mins, maxs, sums, sum_sqs, positive_mins, positive_maxs = f64_rows
    counts, nulls = u64_rows
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
        raise RuntimeError("xy native encode_f32 failed (output undefined)")
    return out


def stacked_bounds(
    values: npt.NDArray[np.float64], baseline: str = "zero"
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Native stacked-series lower/upper bounds for area composition."""
    modes = {"zero": 0, "sym": 1, "wiggle": 2, "weighted_wiggle": 3}
    if baseline not in modes:
        raise ValueError(f"baseline must be one of {tuple(modes)}, got {baseline!r}")
    values = np.ascontiguousarray(values, dtype=np.float64)
    if values.ndim != 2 or min(values.shape) == 0:
        raise ValueError(f"values must be a non-empty 2-D array, got shape {values.shape}")
    lower = np.empty_like(values)
    upper = np.empty_like(values)
    ok = _lib.fc_stacked_bounds(
        values.ctypes.data,
        values.shape[0],
        values.shape[1],
        modes[baseline],
        lower.ctypes.data,
        upper.ctypes.data,
    )
    if ok != 1:
        raise RuntimeError("xy native stacked_bounds failed (output undefined)")
    return lower, upper


def histogram2d(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x_edges: npt.NDArray[np.float64],
    y_edges: npt.NDArray[np.float64],
    weights: Optional[npt.NDArray[np.float64]] = None,
) -> npt.NDArray[np.float64]:
    """Native weighted 2-D histogram for arbitrary monotonic bin edges."""
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    x_edges = _as_f64(x_edges, "x_edges")
    y_edges = _as_f64(y_edges, "y_edges")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if len(x_edges) < 2 or len(y_edges) < 2:
        raise ValueError("x_edges and y_edges must each contain at least two values")
    if weights is not None:
        weights = _as_f64(weights, "weights")
        if len(weights) != len(x):
            raise ValueError("weights must have the same length as x and y")
        weights_ptr = weights.ctypes.data
    else:
        weights_ptr = 0
    out = np.empty((len(x_edges) - 1, len(y_edges) - 1), dtype=np.float64)
    ok = _lib.fc_histogram2d(
        x.ctypes.data if len(x) else 0,
        y.ctypes.data if len(y) else 0,
        weights_ptr,
        len(x),
        x_edges.ctypes.data,
        len(x_edges),
        y_edges.ctypes.data,
        len(y_edges),
        out.ctypes.data,
    )
    if ok != 1:
        raise ValueError("invalid histogram2d arguments")
    return out


def quad_mesh_triangles(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    values: npt.NDArray[np.float64],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Expand a rectilinear or curvilinear quad grid into finite triangles."""
    values = np.ascontiguousarray(values, dtype=np.float64)
    if values.ndim != 2 or min(values.shape, default=0) == 0:
        raise ValueError(f"values must be a non-empty 2-D array, got shape {values.shape}")
    rows, cols = values.shape
    x_values = np.ascontiguousarray(x, dtype=np.float64)
    y_values = np.ascontiguousarray(y, dtype=np.float64)
    if x_values.ndim == y_values.ndim == 1:
        if x_values.shape == (cols + 1,) and y_values.shape == (rows + 1,):
            layout = 0
        elif x_values.shape == (cols,) and y_values.shape == (rows,):
            layout = 2
        else:
            raise ValueError(
                "rectilinear coordinates must be cell centers or edges matching values.shape"
            )
    elif x_values.ndim == y_values.ndim == 2:
        if x_values.shape == y_values.shape == (rows + 1, cols + 1):
            layout = 1
        elif x_values.shape == y_values.shape == (rows, cols):
            layout = 3
        else:
            raise ValueError(
                "curvilinear coordinate grids must both match the value centers or cell edges"
            )
    else:
        raise ValueError("x and y must both be 1-D edge vectors or matching 2-D vertex grids")
    x_flat = x_values.reshape(-1)
    y_flat = y_values.reshape(-1)
    capacity = rows * cols * 2
    outputs = [np.empty(capacity, dtype=np.float64) for _ in range(7)]
    written = _lib.fc_quad_mesh_triangles(
        x_flat.ctypes.data,
        len(x_flat),
        y_flat.ctypes.data,
        len(y_flat),
        values.ctypes.data,
        rows,
        cols,
        layout,
        *(output.ctypes.data for output in outputs),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid quad_mesh_triangles arguments")
    return (
        outputs[0][:written].copy(),
        outputs[1][:written].copy(),
        outputs[2][:written].copy(),
        outputs[3][:written].copy(),
        outputs[4][:written].copy(),
        outputs[5][:written].copy(),
        outputs[6][:written].copy(),
    )


def sector_triangles(
    values: npt.NDArray[np.float64],
    *,
    explode: Optional[npt.NDArray[np.float64]] = None,
    center: tuple[float, float] = (0.0, 0.0),
    radius: float = 1.0,
    inner_radius: float = 0.0,
    start_degrees: float = 0.0,
    counterclockwise: bool = True,
    normalize: bool = True,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Tessellate weighted circular or annular sectors in the native core."""
    weights = _as_f64(values, "values")
    if len(weights) == 0:
        raise ValueError("values must not be empty")
    offsets = None if explode is None else _as_f64(explode, "explode")
    if offsets is not None and len(offsets) != len(weights):
        raise ValueError("explode must have the same length as values")
    center_x = _finite_float(center[0], "center[0]")
    center_y = _finite_float(center[1], "center[1]")
    radius = _finite_float(radius, "radius")
    inner_radius = _finite_float(inner_radius, "inner_radius")
    start_degrees = _finite_float(start_degrees, "start_degrees")
    common = (
        weights.ctypes.data,
        len(weights),
        offsets.ctypes.data if offsets is not None else 0,
        center_x,
        center_y,
        radius,
        inner_radius,
        start_degrees,
        int(bool(counterclockwise)),
        int(bool(normalize)),
    )
    query = _lib.fc_sector_triangles(*common, 0, 0, 0, 0, 0, 0, 0, 0)
    if query == _USIZE_MAX:
        raise ValueError("invalid sector geometry")
    outputs = [np.empty(query, dtype=np.float64) for _ in range(7)]
    written = _lib.fc_sector_triangles(
        *common,
        *(output.ctypes.data for output in outputs),
        query,
    )
    if written != query:
        raise RuntimeError("native sector_triangles returned an inconsistent triangle count")
    return tuple(outputs)  # type: ignore[return-value]


def rfft(
    data: npt.NDArray[np.float64], *, nfft: int = 256, sample_rate: float = 2.0
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Windowed real FFT as frequency, real, and imaginary columns."""
    values = _as_f64(data, "data")
    nfft = _bounded_positive_int(nfft, "nfft", max_value=65_536)
    sample_rate = _finite_float(sample_rate, "sample_rate")
    outputs = [np.empty(nfft // 2 + 1, dtype=np.float64) for _ in range(3)]
    ok = _lib.fc_rfft(
        values.ctypes.data if len(values) else 0,
        len(values),
        nfft,
        sample_rate,
        *(output.ctypes.data for output in outputs),
    )
    if ok != 1:
        raise ValueError("invalid rfft arguments")
    return outputs[0], outputs[1], outputs[2]


def welch_spectra(
    x: npt.NDArray[np.float64],
    y: Optional[npt.NDArray[np.float64]] = None,
    *,
    nfft: int = 256,
    noverlap: int = 0,
    sample_rate: float = 2.0,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Native Welch auto and optional complex cross spectra."""
    x_values = _as_f64(x, "x")
    y_values = None if y is None else _as_f64(y, "y")
    if y_values is not None and len(y_values) != len(x_values):
        raise ValueError("x and y must have equal length")
    nfft = _bounded_positive_int(nfft, "nfft", max_value=65_536)
    noverlap = operator.index(noverlap)
    if noverlap < 0 or noverlap >= nfft:
        raise ValueError("noverlap must be non-negative and less than nfft")
    sample_rate = _finite_float(sample_rate, "sample_rate")
    outputs = [np.empty(nfft // 2 + 1, dtype=np.float64) for _ in range(5)]
    ok = _lib.fc_welch_spectra(
        x_values.ctypes.data if len(x_values) else 0,
        y_values.ctypes.data if y_values is not None else 0,
        len(x_values),
        nfft,
        noverlap,
        sample_rate,
        *(output.ctypes.data for output in outputs),
    )
    if ok != 1:
        raise ValueError("invalid Welch spectrum arguments")
    return outputs[0], outputs[1], outputs[2], outputs[3], outputs[4]


def spectrogram(
    data: npt.NDArray[np.float64],
    *,
    nfft: int = 256,
    noverlap: int = 128,
    sample_rate: float = 2.0,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Native time-major Welch spectrogram."""
    values = _as_f64(data, "data")
    nfft = _bounded_positive_int(nfft, "nfft", max_value=65_536)
    noverlap = operator.index(noverlap)
    if noverlap < 0 or noverlap >= nfft:
        raise ValueError("noverlap must be non-negative and less than nfft")
    sample_rate = _finite_float(sample_rate, "sample_rate")
    segments = 1 if len(values) <= nfft else 1 + (len(values) - nfft) // (nfft - noverlap)
    frequency = np.empty(nfft // 2 + 1, dtype=np.float64)
    time = np.empty(segments, dtype=np.float64)
    power = np.empty((segments, len(frequency)), dtype=np.float64)
    ok = _lib.fc_spectrogram(
        values.ctypes.data if len(values) else 0,
        len(values),
        nfft,
        noverlap,
        sample_rate,
        frequency.ctypes.data,
        time.ctypes.data,
        power.ctypes.data,
    )
    if ok != 1:
        raise ValueError("invalid spectrogram arguments")
    return power, frequency, time


def correlation(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    *,
    max_lags: Optional[int] = None,
    normalize: bool = True,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Native direct lag correlation."""
    x_values = _as_f64(x, "x")
    y_values = _as_f64(y, "y")
    if len(x_values) != len(y_values) or len(x_values) == 0:
        raise ValueError("x and y must have equal non-zero length")
    lag_count = len(x_values) - 1 if max_lags is None else operator.index(max_lags)
    if lag_count < 0 or lag_count >= len(x_values):
        raise ValueError("max_lags must be between 0 and len(x)-1")
    lag = np.empty(2 * lag_count + 1, dtype=np.float64)
    result = np.empty_like(lag)
    ok = _lib.fc_correlation(
        x_values.ctypes.data,
        y_values.ctypes.data,
        len(x_values),
        lag_count,
        int(bool(normalize)),
        lag.ctypes.data,
        result.ctypes.data,
    )
    if ok != 1:
        raise ValueError("invalid correlation arguments")
    return lag, result


def weighted_ecdf(
    values: npt.NDArray[np.float64], weights: npt.NDArray[np.float64]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Native weighted sort, duplicate aggregation, and cumulative mass."""
    value_array = _as_f64(values, "values")
    weight_array = _as_f64(weights, "weights")
    if len(value_array) != len(weight_array) or len(value_array) == 0:
        raise ValueError("values and weights must have equal non-zero length")
    output_values = np.empty(len(value_array), dtype=np.float64)
    cumulative = np.empty(len(value_array), dtype=np.float64)
    written = _lib.fc_weighted_ecdf(
        value_array.ctypes.data,
        weight_array.ctypes.data,
        len(value_array),
        output_values.ctypes.data,
        cumulative.ctypes.data,
    )
    if written == _USIZE_MAX:
        raise ValueError("weighted ECDF requires finite values and nonnegative positive mass")
    return output_values[:written].copy(), cumulative[:written].copy()


def _triangle_inputs(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    triangles: npt.NDArray[np.int64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.int64]]:
    x_values = _as_f64(x, "x")
    y_values = _as_f64(y, "y")
    if len(x_values) != len(y_values):
        raise ValueError("x and y must have equal length")
    topology = np.ascontiguousarray(triangles, dtype=np.int64)
    if topology.ndim != 2 or topology.shape[1:] != (3,):
        raise ValueError(f"triangles must have shape (n, 3), got {topology.shape}")
    if len(topology) == 0:
        raise ValueError("triangles must contain at least one face")
    return x_values, y_values, topology


def indexed_triangles(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    triangles: npt.NDArray[np.int64],
    values: Optional[npt.NDArray[np.float64]] = None,
    *,
    values_at: str = "auto",
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Expand indexed topology into finite renderer-ready triangles."""
    x_values, y_values, topology = _triangle_inputs(x, y, triangles)
    if values_at not in {"auto", "face", "vertex"}:
        raise ValueError("values_at must be 'auto', 'face', or 'vertex'")
    if values is None:
        scalar = np.empty(0, dtype=np.float64)
        mode = 0
    else:
        scalar = _as_f64(values, "values")
        if values_at == "face" or (values_at == "auto" and len(scalar) == len(topology)):
            mode = 1
            expected = len(topology)
        else:
            mode = 2
            expected = len(x_values)
        if len(scalar) != expected:
            raise ValueError(f"{values_at} values must have length {expected}, got {len(scalar)}")
    outputs = [np.empty(len(topology), dtype=np.float64) for _ in range(7)]
    written = _lib.fc_indexed_triangles(
        x_values.ctypes.data,
        y_values.ctypes.data,
        len(x_values),
        topology.ctypes.data,
        len(topology),
        scalar.ctypes.data if len(scalar) else 0,
        len(scalar),
        mode,
        *(output.ctypes.data for output in outputs),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid indexed triangle geometry")
    return (
        outputs[0][:written].copy(),
        outputs[1][:written].copy(),
        outputs[2][:written].copy(),
        outputs[3][:written].copy(),
        outputs[4][:written].copy(),
        outputs[5][:written].copy(),
        outputs[6][:written].copy(),
    )


def triangle_edges(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    triangles: npt.NDArray[np.int64],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Return unique finite edges from indexed triangle topology."""
    x_values, y_values, topology = _triangle_inputs(x, y, triangles)
    capacity = len(topology) * 3
    outputs = [np.empty(capacity, dtype=np.float64) for _ in range(4)]
    written = _lib.fc_triangle_edges(
        x_values.ctypes.data,
        y_values.ctypes.data,
        len(x_values),
        topology.ctypes.data,
        len(topology),
        *(output.ctypes.data for output in outputs),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid triangle edge geometry")
    copied = [output[:written].copy() for output in outputs]
    return copied[0], copied[1], copied[2], copied[3]


def delaunay_triangles(
    x: npt.NDArray[np.float64], y: npt.NDArray[np.float64]
) -> npt.NDArray[np.int64]:
    """Construct dependency-free native Delaunay topology for 2-D points."""
    x_values = _as_f64(x, "x")
    y_values = _as_f64(y, "y")
    if len(x_values) != len(y_values) or len(x_values) < 3:
        raise ValueError("x and y must have equal length of at least three")
    if len(x_values) > 10_000:
        raise ValueError(
            "native quadratic Delaunay triangulation is limited to 10,000 points; "
            "provide explicit topology for larger inputs"
        )
    # A planar triangulation has at most 2n-5 faces for n>=3.
    capacity = max(1, 2 * len(x_values))
    output = np.empty((capacity, 3), dtype=np.int64)
    written = _lib.fc_delaunay_triangles(
        x_values.ctypes.data,
        y_values.ctypes.data,
        len(x_values),
        output.ctypes.data,
        capacity,
    )
    if written == _USIZE_MAX:
        raise ValueError("points must include at least three finite, non-collinear locations")
    return output[:written].copy()


def polygon_triangles(
    x: npt.NDArray[np.float64], y: npt.NDArray[np.float64]
) -> npt.NDArray[np.int64]:
    """Triangulate one finite simple polygon with native ear clipping."""
    x_values = _as_f64(x, "x")
    y_values = _as_f64(y, "y")
    if len(x_values) != len(y_values) or len(x_values) < 3:
        raise ValueError("polygon x and y must have equal length of at least three")
    if len(x_values) > 10_000:
        raise ValueError("quadratic polygon triangulation is limited to 10,000 vertices")
    closed = x_values[0] == x_values[-1] and y_values[0] == y_values[-1]
    capacity = len(x_values) - (3 if closed else 2)
    output = np.empty((capacity, 3), dtype=np.int64)
    written = _lib.fc_polygon_triangles(
        x_values.ctypes.data,
        y_values.ctypes.data,
        len(x_values),
        output.ctypes.data,
        capacity,
    )
    if written == _USIZE_MAX:
        raise ValueError("polygon must be finite, simple, and non-degenerate")
    return output[:written].copy()


def marching_triangles(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    z: npt.NDArray[np.float64],
    triangles: npt.NDArray[np.int64],
    levels: npt.NDArray[np.float64],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Extract isoline segments from an indexed triangular scalar field."""
    x_values, y_values, topology = _triangle_inputs(x, y, triangles)
    z_values = _as_f64(z, "z")
    level_values = _as_f64(levels, "levels")
    if len(z_values) != len(x_values):
        raise ValueError("z must have the same length as x and y")
    if not np.isfinite(level_values).all():
        raise ValueError("levels must be finite")
    work = len(topology) * len(level_values)
    if work > MAX_CONTOUR_WORK:
        raise ValueError(
            f"marching_triangles faces x levels exceeds the bounded work budget ({MAX_CONTOUR_WORK:,})"
        )
    common = (
        x_values.ctypes.data,
        y_values.ctypes.data,
        z_values.ctypes.data,
        len(x_values),
        topology.ctypes.data,
        len(topology),
        level_values.ctypes.data if len(level_values) else 0,
        len(level_values),
    )
    query = _lib.fc_marching_triangles(*common, 0, 0, 0, 0, 0, 0)
    if query == _USIZE_MAX:
        raise ValueError("invalid marching triangle geometry")
    outputs = [np.empty(query, dtype=np.float64) for _ in range(5)]
    if query == 0:
        return outputs[0], outputs[1], outputs[2], outputs[3], outputs[4]
    written = _lib.fc_marching_triangles(
        *common,
        *(output.ctypes.data for output in outputs),
        query,
    )
    if written != query:
        raise RuntimeError("native marching_triangles returned an inconsistent segment count")
    return outputs[0], outputs[1], outputs[2], outputs[3], outputs[4]


def vector_segments(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    u: npt.NDArray[np.float64],
    v: npt.NDArray[np.float64],
    *,
    scale: float = 1.0,
    pivot: str = "tail",
    head_ratio: float = 0.22,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Native vector shafts and arrowheads as four compact segment columns."""
    pivots = {"tail": 0, "mid": 1, "middle": 1, "tip": 2}
    if pivot not in pivots:
        raise ValueError(f"pivot must be one of {tuple(pivots)}, got {pivot!r}")
    scale = _finite_float(scale, "scale")
    head_ratio = _finite_float(head_ratio, "head_ratio")
    if scale <= 0.0 or not 0.0 <= head_ratio <= 1.0:
        raise ValueError("scale must be positive and head_ratio must be between 0 and 1")
    arrays = [_as_f64(values, name) for values, name in ((x, "x"), (y, "y"), (u, "u"), (v, "v"))]
    if len({len(values) for values in arrays}) != 1:
        raise ValueError("x, y, u, and v must have equal length")
    capacity = len(arrays[0]) * 3
    outputs = [np.empty(capacity, dtype=np.float64) for _ in range(4)]
    if capacity == 0:
        return outputs[0], outputs[1], outputs[2], outputs[3]
    written = _lib.fc_vector_segments(
        *(values.ctypes.data for values in arrays),
        len(arrays[0]),
        scale,
        pivots[pivot],
        head_ratio,
        *(values.ctypes.data for values in outputs),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid vector_segments arguments")
    copied = [values[:written].copy() for values in outputs]
    return copied[0], copied[1], copied[2], copied[3]


def streamlines(
    x_coords: npt.NDArray[np.float64],
    y_coords: npt.NDArray[np.float64],
    u: npt.NDArray[np.float64],
    v: npt.NDArray[np.float64],
    *,
    density: float = 1.0,
    max_steps: int = 2048,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Native bounded streamline integration over a regular vector grid."""
    x_coords = _as_f64(x_coords, "x_coords")
    y_coords = _as_f64(y_coords, "y_coords")
    u = np.ascontiguousarray(u, dtype=np.float64)
    v = np.ascontiguousarray(v, dtype=np.float64)
    expected = (len(y_coords), len(x_coords))
    if u.shape != expected or v.shape != expected:
        raise ValueError(f"u and v must both have shape {expected}")
    density = _finite_float(density, "density")
    max_steps = _bounded_positive_int(max_steps, "max_steps", max_value=100_000)
    query = _lib.fc_streamlines(
        x_coords.ctypes.data,
        len(x_coords),
        y_coords.ctypes.data,
        len(y_coords),
        u.ctypes.data,
        v.ctypes.data,
        density,
        max_steps,
        0,
        0,
        0,
        0,
        0,
    )
    if query == _USIZE_MAX:
        raise ValueError("invalid streamlines arguments")
    outputs = [np.empty(query, dtype=np.float64) for _ in range(4)]
    if query == 0:
        return outputs[0], outputs[1], outputs[2], outputs[3]
    written = _lib.fc_streamlines(
        x_coords.ctypes.data,
        len(x_coords),
        y_coords.ctypes.data,
        len(y_coords),
        u.ctypes.data,
        v.ctypes.data,
        density,
        max_steps,
        *(values.ctypes.data for values in outputs),
        query,
    )
    if written != query:
        raise RuntimeError("native streamlines returned an inconsistent segment count")
    return outputs[0], outputs[1], outputs[2], outputs[3]


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


def marching_squares(
    z: npt.NDArray[np.float64],
    x_coords: npt.NDArray[np.float64],
    y_coords: npt.NDArray[np.float64],
    levels: npt.NDArray[np.float64],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Extract regular-grid contour segments with native marching squares."""
    z = np.ascontiguousarray(z, dtype=np.float64)
    x_coords = _as_f64(x_coords, "x_coords")
    y_coords = _as_f64(y_coords, "y_coords")
    levels = _as_f64(levels, "levels")
    if z.ndim != 2 or min(z.shape) < 2:
        raise ValueError(f"z must be a 2-D array with at least 2 rows/columns, got {z.shape}")
    rows, cols = z.shape
    if len(x_coords) != cols or len(y_coords) != rows:
        raise ValueError("coordinate arrays must match the z grid dimensions")
    if (
        not np.isfinite(x_coords).all()
        or not np.isfinite(y_coords).all()
        or not np.isfinite(levels).all()
    ):
        raise ValueError("coordinates and levels must be finite")
    if not np.all(np.diff(x_coords) > 0) or not np.all(np.diff(y_coords) > 0):
        raise ValueError("coordinate arrays must be strictly increasing")
    if len(levels) == 0:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty.copy(), empty.copy(), empty.copy(), empty.copy()
    work = (rows - 1) * (cols - 1) * len(levels)
    if work > MAX_CONTOUR_WORK:
        raise ValueError(
            f"marching_squares grid x levels exceeds the bounded work budget ({MAX_CONTOUR_WORK:,})"
        )
    # Most smooth fields emit O(perimeter × levels) segments, far below the
    # two-per-cell theoretical maximum. Start with that exact-output capacity
    # and exploit the kernel's required-count return to retry only adversarial
    # checkerboards. This removes the unconditional full count-only scan.
    maximum = 2 * work
    capacity = min(maximum, max(64, 2 * (rows + cols) * len(levels)))

    def allocate(size: int) -> tuple[npt.NDArray[np.float64], ...]:
        return tuple(np.empty(size, dtype=np.float64) for _ in range(5))

    def extract(outputs: tuple[npt.NDArray[np.float64], ...]) -> int:
        return int(
            _lib.fc_marching_squares(
                _ptr_f64(z),
                rows,
                cols,
                _ptr_f64(x_coords),
                _ptr_f64(y_coords),
                _ptr_f64(levels),
                len(levels),
                *(_ptr_f64(output) for output in outputs),
                len(outputs[0]),
            )
        )

    outputs = allocate(capacity)
    written = extract(outputs)
    if written == _USIZE_MAX or written > maximum:
        raise ValueError("invalid marching_squares arguments")
    if written > capacity:
        outputs = allocate(written)
        repeated = extract(outputs)
        if repeated != written:
            raise RuntimeError("native marching_squares returned an inconsistent segment count")
    return tuple(output[:written] for output in outputs)


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
            raise RuntimeError("xy native normalize_f32 failed (output undefined)")
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
            raise RuntimeError("xy native sample_mask failed (output undefined)")
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
    per-category NumPy reference in `xy.lod` (asserted by the parity
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


def rasterize_png(cmds: bytes, w: int, h: int) -> bytes:
    """Paint a display list and encode it as PNG wholly inside the Rust core."""
    w = _positive_int(w, "raster width")
    h = _positive_int(h, "raster height")
    buf = np.frombuffer(cmds, dtype=np.uint8)
    raw_len = operator.mul(operator.mul(w, h), 4)
    capacity = raw_len + raw_len // 8 + 65_536
    out = np.empty(capacity, dtype=np.uint8)
    cmd_ptr = _ptr_u8(buf) if buf.size else None
    written = _lib.fc_rasterize_png(cmd_ptr, buf.size, _ptr_u8(out), out.size, w, h)
    if written == _USIZE_MAX or written > out.size:
        raise ValueError("native raster-to-PNG encoder rejected the command buffer")
    return out[:written].tobytes()


def heatmap_rgba(
    raw: npt.ArrayLike,
    w: int,
    h: int,
    stops: npt.ArrayLike,
    alpha: int,
) -> npt.NDArray[np.uint8]:
    """Map heatmap scalars to a vertically flipped ``(h, w, 4)`` RGBA image."""
    w = _positive_int(w, "heatmap width")
    h = _positive_int(h, "heatmap height")
    values = np.ascontiguousarray(raw, dtype=np.float64).reshape(-1)
    stop_array = np.ascontiguousarray(stops, dtype=np.uint8)
    if values.size != w * h:
        raise ValueError("heatmap scalar count must match width * height")
    if stop_array.ndim != 2 or stop_array.shape[1] != 3 or stop_array.shape[0] < 1:
        raise ValueError("heatmap stops must be a non-empty (n, 3) array")
    alpha = operator.index(alpha)
    if not 0 <= alpha <= 255:
        raise ValueError("heatmap alpha must be in [0, 255]")
    out = np.empty((h, w, 4), dtype=np.uint8)
    ok = _lib.fc_heatmap_rgba(
        _ptr_f64(values),
        w,
        h,
        _ptr_u8(stop_array),
        stop_array.shape[0],
        alpha,
        _ptr_u8(out),
    )
    if not ok:
        raise ValueError("native heatmap colormap rejected the inputs")
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
