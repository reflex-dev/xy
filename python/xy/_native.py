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

ABI_VERSION = 38

# Rust reports invalid arguments (and, via the ffi_guard panic shield, any
# internal panic) by returning `usize::MAX` from size-returning entry points.
# `usize` is `c_size_t`, whose width is platform-dependent — 32 bits on
# armv7/win32/wasm32 — so the sentinel must be derived from ctypes. Comparing
# against 2**64-1 would never match on 32-bit targets and an error return
# would be sliced as data.
_USIZE_MAX = ctypes.c_size_t(-1).value
_FACTORIZE_CAPACITY_EXCEEDED = _USIZE_MAX - 1


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

    lib.xy_abi_version.restype = ctypes.c_uint32
    lib.xy_abi_version.argtypes = []
    got = lib.xy_abi_version()
    if got != ABI_VERSION:
        raise ImportError(
            f"xy native core ABI mismatch: python wrapper expects "
            f"{ABI_VERSION}, library reports {got}. Reinstall xy so the "
            "wheel and package versions match."
        )

    lib.xy_factorize_fixed.restype = ctypes.c_size_t
    lib.xy_factorize_fixed.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_factorize_fixed_u8.restype = ctypes.c_size_t
    lib.xy_factorize_fixed_u8.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_factorize_fixed_u8_counts.restype = ctypes.c_size_t
    lib.xy_factorize_fixed_u8_counts.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_factorize_unicode1_u8_counts.restype = ctypes.c_size_t
    lib.xy_factorize_unicode1_u8_counts.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_remap_u8.restype = ctypes.c_int32
    lib.xy_remap_u8.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]

    lib.xy_zone_maps.restype = ctypes.c_size_t
    lib.xy_zone_maps.argtypes = [
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
    lib.xy_zone_maps_pair.restype = ctypes.c_size_t
    lib.xy_zone_maps_pair.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_datetime64_to_ms.restype = ctypes.c_int32
    lib.xy_datetime64_to_ms.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
        ctypes.c_int64,
        ctypes.c_int64,
        ctypes.c_void_p,
    ]
    lib.xy_encode_f32.restype = ctypes.c_int32
    lib.xy_encode_f32.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_void_p,
    ]
    lib.xy_m4_indices.restype = ctypes.c_size_t
    lib.xy_m4_indices.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    lib.xy_svg_poly_path.restype = ctypes.c_size_t
    lib.xy_svg_poly_path.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_m4_points.restype = ctypes.c_size_t
    lib.xy_m4_points.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_stacked_bounds.restype = ctypes.c_int32
    lib.xy_stacked_bounds.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_histogram2d.restype = ctypes.c_int32
    lib.xy_histogram2d.argtypes = [
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
    lib.xy_quad_mesh_triangles.restype = ctypes.c_size_t
    lib.xy_quad_mesh_triangles.argtypes = [
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
    lib.xy_sector_triangles.restype = ctypes.c_size_t
    lib.xy_sector_triangles.argtypes = [
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
    lib.xy_rfft.restype = ctypes.c_int32
    lib.xy_rfft.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_welch_spectra.restype = ctypes.c_int32
    lib.xy_welch_spectra.argtypes = [
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
    lib.xy_spectrogram.restype = ctypes.c_int32
    lib.xy_spectrogram.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_correlation.restype = ctypes.c_int32
    lib.xy_correlation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_weighted_ecdf.restype = ctypes.c_size_t
    lib.xy_weighted_ecdf.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.xy_indexed_triangles.restype = ctypes.c_size_t
    lib.xy_indexed_triangles.argtypes = [
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
    lib.xy_triangle_edges.restype = ctypes.c_size_t
    lib.xy_triangle_edges.argtypes = [
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
    lib.xy_delaunay_triangles.restype = ctypes.c_size_t
    lib.xy_delaunay_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_polygon_triangles.restype = ctypes.c_size_t
    lib.xy_polygon_triangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_marching_triangles.restype = ctypes.c_size_t
    lib.xy_marching_triangles.argtypes = [
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
    lib.xy_vector_segments.restype = ctypes.c_size_t
    lib.xy_vector_segments.argtypes = [
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
    lib.xy_streamlines.restype = ctypes.c_size_t
    lib.xy_streamlines.argtypes = [
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
    lib.xy_marching_squares.restype = ctypes.c_size_t
    lib.xy_marching_squares.argtypes = [
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
    lib.xy_min_max.restype = ctypes.c_int32
    lib.xy_min_max.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    lib.xy_is_sorted.restype = ctypes.c_int32
    lib.xy_is_sorted.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.xy_bin_2d.restype = ctypes.c_int32
    lib.xy_bin_2d.argtypes = [
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
    lib.xy_bin_2d_indices.restype = ctypes.c_size_t
    lib.xy_bin_2d_indices.argtypes = [
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
    lib.xy_bin_2d_sample_range.restype = ctypes.c_size_t
    lib.xy_bin_2d_sample_range.argtypes = [
        ctypes.c_void_p,  # x
        ctypes.c_void_p,  # y
        ctypes.c_size_t,  # len
        ctypes.c_double,  # x0
        ctypes.c_double,  # x1
        ctypes.c_double,  # y0
        ctypes.c_double,  # y1
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
        ctypes.c_uint64,  # seed
        ctypes.c_uint64,  # threshold
        ctypes.c_void_p,  # grid
        ctypes.c_void_p,  # sampled rows
        ctypes.c_size_t,  # sampled-row capacity
    ]
    lib.xy_bin_2d_stratified_sample_range_u8_counted.restype = ctypes.c_size_t
    lib.xy_bin_2d_stratified_sample_range_u8_counted.argtypes = [
        ctypes.c_void_p,  # x
        ctypes.c_void_p,  # y
        ctypes.c_void_p,  # groups
        ctypes.c_size_t,  # len
        ctypes.c_void_p,  # counts
        ctypes.c_size_t,  # n_groups
        ctypes.c_double,  # x0
        ctypes.c_double,  # x1
        ctypes.c_double,  # y0
        ctypes.c_double,  # y1
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
        ctypes.c_uint64,  # seed
        ctypes.c_double,  # fraction
        ctypes.c_uint64,  # min_count
        ctypes.c_void_p,  # grid
        ctypes.c_void_p,  # sampled rows
        ctypes.c_size_t,  # sampled-row capacity
    ]
    lib.xy_histogram_uniform.restype = ctypes.c_size_t
    lib.xy_histogram_uniform.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_int32,
        ctypes.c_void_p,
    ]
    lib.xy_normalize_f32.restype = ctypes.c_int32
    lib.xy_normalize_f32.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int32,
        ctypes.c_void_p,
    ]
    lib.xy_valid_indices_f64.restype = ctypes.c_size_t
    lib.xy_valid_indices_f64.argtypes = [
        ctypes.c_void_p,  # array of f64 pointers
        ctypes.c_size_t,  # number of columns
        ctypes.c_size_t,  # row count
        ctypes.c_uint64,  # positive-column bit mask
        ctypes.c_void_p,  # output row IDs
        ctypes.c_size_t,  # output capacity
    ]
    lib.xy_range_indices.restype = ctypes.c_size_t
    lib.xy_range_indices.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_void_p,
    ]
    lib.xy_sample_mask.restype = ctypes.c_int32
    lib.xy_sample_mask.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_void_p,
    ]
    lib.xy_sample_mask_u32.restype = ctypes.c_int32
    lib.xy_sample_mask_u32.argtypes = list(lib.xy_sample_mask.argtypes)
    lib.xy_sample_range_indices.restype = ctypes.c_size_t
    lib.xy_sample_range_indices.argtypes = [
        ctypes.c_size_t,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_stratified_sample_range_u8.restype = ctypes.c_size_t
    lib.xy_stratified_sample_range_u8.argtypes = [
        ctypes.c_void_p,  # groups
        ctypes.c_size_t,  # len
        ctypes.c_size_t,  # n_groups
        ctypes.c_uint64,  # seed
        ctypes.c_double,  # fraction
        ctypes.c_uint64,  # min_count
        ctypes.c_void_p,  # out
        ctypes.c_size_t,  # capacity
    ]
    lib.xy_stratified_sample_range_u8_counted.restype = ctypes.c_size_t
    lib.xy_stratified_sample_range_u8_counted.argtypes = [
        ctypes.c_void_p,  # groups
        ctypes.c_size_t,  # len
        ctypes.c_void_p,  # counts
        ctypes.c_size_t,  # n_groups
        ctypes.c_uint64,  # seed
        ctypes.c_double,  # fraction
        ctypes.c_uint64,  # min_count
        ctypes.c_void_p,  # out
        ctypes.c_size_t,  # capacity
    ]
    lib.xy_stratified_sample_mask.restype = ctypes.c_int32
    lib.xy_stratified_sample_mask.argtypes = [
        ctypes.c_void_p,  # ids
        ctypes.c_void_p,  # groups
        ctypes.c_size_t,  # len
        ctypes.c_size_t,  # n_groups
        ctypes.c_uint64,  # seed
        ctypes.c_double,  # fraction
        ctypes.c_uint64,  # min_count
        ctypes.c_void_p,  # out
    ]
    lib.xy_stratified_sample_mask_u32.restype = ctypes.c_int32
    lib.xy_stratified_sample_mask_u32.argtypes = list(lib.xy_stratified_sample_mask.argtypes)
    lib.xy_pyramid_build.restype = ctypes.c_uint64
    lib.xy_pyramid_build.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_uint32,
    ]
    lib.xy_pyramid_append.restype = ctypes.c_int32
    lib.xy_pyramid_append.argtypes = [
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.xy_pyramid_count.restype = ctypes.c_int32
    lib.xy_pyramid_count.argtypes = [
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_void_p,
    ]
    lib.xy_pyramid_compose.restype = ctypes.c_int32
    lib.xy_pyramid_compose.argtypes = [
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    lib.xy_pyramid_free.restype = ctypes.c_int32
    lib.xy_pyramid_free.argtypes = [ctypes.c_uint64]
    lib.xy_local_log_density.restype = ctypes.c_int32
    lib.xy_local_log_density.argtypes = [
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
    lib.xy_rasterize.restype = ctypes.c_int32
    lib.xy_rasterize.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.c_void_p,  # out (w*h*4 RGBA8)
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.xy_rasterize_png.restype = ctypes.c_size_t
    lib.xy_rasterize_png.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.c_void_p,  # out PNG bytes
        ctypes.c_size_t,  # out_capacity
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.xy_rasterize_data.restype = ctypes.c_int32
    lib.xy_rasterize_data.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.c_void_p,  # external data arena
        ctypes.c_size_t,  # data_len
        ctypes.c_void_p,  # out (w*h*4 RGBA8)
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.xy_rasterize_png_data.restype = ctypes.c_size_t
    lib.xy_rasterize_png_data.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.c_void_p,  # external data arena
        ctypes.c_size_t,  # data_len
        ctypes.c_void_p,  # out PNG bytes
        ctypes.c_size_t,  # out_capacity
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.xy_rasterize_spans.restype = ctypes.c_int32
    lib.xy_rasterize_spans.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.POINTER(ctypes.c_void_p),  # span pointers
        ctypes.POINTER(ctypes.c_size_t),  # span lengths
        ctypes.c_size_t,  # span count
        ctypes.c_void_p,  # out (w*h*4 RGBA8)
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.xy_rasterize_png_spans.restype = ctypes.c_size_t
    lib.xy_rasterize_png_spans.argtypes = [
        ctypes.c_void_p,  # cmd
        ctypes.c_size_t,  # cmd_len
        ctypes.POINTER(ctypes.c_void_p),  # span pointers
        ctypes.POINTER(ctypes.c_size_t),  # span lengths
        ctypes.c_size_t,  # span count
        ctypes.c_void_p,  # out PNG bytes
        ctypes.c_size_t,  # out_capacity
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
    ]
    lib.xy_heatmap_rgba.restype = ctypes.c_int32
    lib.xy_heatmap_rgba.argtypes = [
        ctypes.c_void_p,  # raw f64
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
        ctypes.c_void_p,  # RGB stops
        ctypes.c_size_t,  # stop_count
        ctypes.c_uint8,  # alpha
        ctypes.c_void_p,  # out RGBA8
    ]
    lib.xy_density_rgba.restype = ctypes.c_int32
    lib.xy_density_rgba.argtypes = [
        ctypes.c_void_p,  # encoded log-u8
        ctypes.c_size_t,  # w
        ctypes.c_size_t,  # h
        ctypes.c_double,  # original maximum
        ctypes.c_void_p,  # RGB stops
        ctypes.c_size_t,  # stop_count
        ctypes.c_double,  # opacity
        ctypes.c_void_p,  # out RGBA8
    ]
    lib.xy_density_log_u8.restype = ctypes.c_int32
    lib.xy_density_log_u8.argtypes = [
        ctypes.c_void_p,  # grid f32
        ctypes.c_size_t,  # len
        ctypes.c_void_p,  # out u8
        ctypes.c_void_p,  # out max f64
    ]
    lib.xy_css_check.restype = ctypes.c_int32
    lib.xy_css_check.argtypes = [
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


def _fixed_records(values: np.ndarray) -> tuple[np.ndarray, int]:
    records = np.ascontiguousarray(values)
    if records.ndim != 1 or records.dtype.hasobject:
        raise ValueError("factorize_fixed values must be a non-object 1-D array")
    width = int(records.dtype.itemsize)
    if width <= 0:
        raise ValueError("factorize_fixed values must have positive-width records")
    return records, width


def factorize_fixed(
    values: np.ndarray,
) -> tuple[npt.NDArray[np.uint32], npt.NDArray[np.uint32]]:
    """First-seen codes and unique-row indices for fixed-width 1-D values.

    The native kernel compares the complete memory record; label conversion
    and lexical ordering remain with the channel policy layer.
    """
    records, width = _fixed_records(values)
    n = len(records)
    codes = np.empty(n, dtype=np.uint32)
    unique_indices = np.empty(n, dtype=np.uint32)
    if n == 0:
        return codes, unique_indices
    written = _lib.xy_factorize_fixed(
        records.ctypes.data,
        n,
        width,
        codes.ctypes.data,
        unique_indices.ctypes.data,
    )
    if written == _USIZE_MAX or written > n:
        raise ValueError("native factorize_fixed rejected the record array")
    return codes, unique_indices[:written].copy()


def factorize_fixed_u8(
    values: np.ndarray, max_unique: int = 256
) -> Optional[tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint32]]]:
    """Compact fixed-record factorization, or ``None`` above `max_unique`."""
    max_unique = _bounded_positive_int(max_unique, "max_unique", max_value=256)
    records, width = _fixed_records(values)
    n = len(records)
    codes = np.empty(n, dtype=np.uint8)
    unique_indices = np.empty(min(n, max_unique), dtype=np.uint32)
    if n == 0:
        return codes, unique_indices
    written = _lib.xy_factorize_fixed_u8(
        records.ctypes.data,
        n,
        width,
        codes.ctypes.data,
        unique_indices.ctypes.data,
        len(unique_indices),
    )
    if written == _FACTORIZE_CAPACITY_EXCEEDED:
        return None
    if written == _USIZE_MAX or written > len(unique_indices):
        raise ValueError("native factorize_fixed_u8 rejected the record array")
    return codes, unique_indices[:written].copy()


def factorize_fixed_u8_counts(
    values: np.ndarray, max_unique: int = 256
) -> Optional[
    tuple[
        npt.NDArray[np.uint8],
        npt.NDArray[np.uint32],
        npt.NDArray[np.uint64],
    ]
]:
    """Compact factorization plus exact counts in first-seen code order."""
    max_unique = _bounded_positive_int(max_unique, "max_unique", max_value=256)
    records, width = _fixed_records(values)
    n = len(records)
    codes = np.empty(n, dtype=np.uint8)
    capacity = min(n, max_unique)
    unique_indices = np.empty(capacity, dtype=np.uint32)
    counts = np.empty(capacity, dtype=np.uint64)
    if n == 0:
        return codes, unique_indices, counts
    written = _lib.xy_factorize_fixed_u8_counts(
        records.ctypes.data,
        n,
        width,
        codes.ctypes.data,
        unique_indices.ctypes.data,
        counts.ctypes.data,
        capacity,
    )
    if written == _FACTORIZE_CAPACITY_EXCEEDED:
        return None
    if written == _USIZE_MAX or written > capacity:
        raise ValueError("native factorize_fixed_u8_counts rejected the record array")
    return codes, unique_indices[:written].copy(), counts[:written].copy()


def factorize_unicode1_u8_counts(
    values: np.ndarray, max_unique: int = 256
) -> Optional[
    tuple[
        npt.NDArray[np.uint8],
        npt.NDArray[np.uint32],
        npt.NDArray[np.uint64],
    ]
]:
    """Direct-table factorization for one-codepoint NumPy Unicode arrays."""
    max_unique = _bounded_positive_int(max_unique, "max_unique", max_value=256)
    records = np.ascontiguousarray(values)
    if records.ndim != 1 or records.dtype.kind != "U" or records.dtype.itemsize != 4:
        raise ValueError("values must be a one-dimensional Unicode U1 array")
    n = len(records)
    codes = np.empty(n, dtype=np.uint8)
    capacity = min(n, max_unique)
    unique_indices = np.empty(capacity, dtype=np.uint32)
    counts = np.empty(capacity, dtype=np.uint64)
    if n == 0:
        return codes, unique_indices, counts
    native_order = "<" if sys.byteorder == "little" else ">"
    swap_endian = records.dtype.byteorder not in ("=", "|", native_order)
    written = _lib.xy_factorize_unicode1_u8_counts(
        records.ctypes.data,
        n,
        int(swap_endian),
        codes.ctypes.data,
        unique_indices.ctypes.data,
        counts.ctypes.data,
        capacity,
    )
    if written == _FACTORIZE_CAPACITY_EXCEEDED:
        return None
    if written == _USIZE_MAX or written > capacity:
        raise ValueError("native factorize_unicode1_u8_counts rejected the array")
    return codes, unique_indices[:written].copy(), counts[:written].copy()


def remap_u8(values: npt.NDArray[np.uint8], mapping: npt.NDArray[np.uint8]) -> None:
    """Apply a compact categorical codebook permutation in place."""
    values = np.asarray(values)
    mapping = np.ascontiguousarray(mapping, dtype=np.uint8)
    if values.dtype != np.uint8 or values.ndim != 1 or not values.flags.c_contiguous:
        raise ValueError("remap_u8 values must be a contiguous uint8 1-D array")
    if mapping.ndim != 1:
        raise ValueError("remap_u8 mapping must be a 1-D array")
    if len(values) == 0:
        return
    if len(mapping) == 0:
        raise ValueError("remap_u8 mapping must be non-empty")
    ok = _lib.xy_remap_u8(
        values.ctypes.data,
        len(values),
        mapping.ctypes.data,
        len(mapping),
    )
    if not ok:
        raise ValueError("remap_u8 encountered a code outside the mapping")


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


def _bounded_nonnegative_int(value: int, label: str, max_value: int) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        out = operator.index(value)
    except TypeError as e:
        raise ValueError(f"{label} must be a non-negative integer") from e
    if out < 0 or out > max_value:
        raise ValueError(f"{label} must be between 0 and {max_value}")
    return int(out)


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
    written = _lib.xy_zone_maps(
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


_ZONE_MAP_DTYPE = np.dtype(
    [
        ("min", np.float64),
        ("max", np.float64),
        ("positive_min", np.float64),
        ("positive_max", np.float64),
        ("count", np.uint64),
        ("null_count", np.uint64),
        ("sum", np.float64),
        ("sum_sq", np.float64),
    ],
    align=True,
)
if _ZONE_MAP_DTYPE.itemsize != 64:  # pragma: no cover - platform ABI invariant
    raise ImportError("xy native ZoneMap layout is not 64 bytes on this platform")


def zone_maps_pair(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    chunk_size: int = 65_536,
) -> tuple[tuple[np.ndarray, ...], tuple[np.ndarray, ...]]:
    """Bit-identical zone maps for two equal-length columns in one call."""
    chunk_size = _positive_int(chunk_size, "chunk_size")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    n_chunks = max(1, -(-len(x) // chunk_size)) if len(x) else 0
    x_records = np.empty(n_chunks, dtype=_ZONE_MAP_DTYPE)
    y_records = np.empty(n_chunks, dtype=_ZONE_MAP_DTYPE)
    if len(x):
        written = _lib.xy_zone_maps_pair(
            x.ctypes.data,
            y.ctypes.data,
            len(x),
            chunk_size,
            x_records.ctypes.data,
            y_records.ctypes.data,
        )
        if written == _USIZE_MAX:
            raise ValueError("invalid zone_maps_pair arguments")
        if written != n_chunks:
            raise RuntimeError(
                f"xy native zone_maps_pair wrote {written} chunks, expected {n_chunks}"
            )

    def unpack(records: np.ndarray) -> tuple[np.ndarray, ...]:
        return (
            records["min"].copy(),
            records["max"].copy(),
            records["count"].copy(),
            records["null_count"].copy(),
            records["sum"].copy(),
            records["sum_sq"].copy(),
            records["positive_min"].copy(),
            records["positive_max"].copy(),
        )

    return unpack(x_records), unpack(y_records)


def datetime64_to_ms(
    values: npt.NDArray[np.int64], numerator: int, denominator: int
) -> npt.NDArray[np.float64]:
    """Convert datetime ticks to whole-ms f64 with one output allocation.

    ``values`` may be strided (including reversed); the native loop reads the
    source view directly. NumPy's NaT sentinel maps to NaN and finer-than-ms
    units use exact floor division, including for negative pre-epoch values.
    """
    arr = np.asarray(values)
    if arr.ndim != 1 or arr.dtype != np.dtype(np.int64):
        raise ValueError("datetime64 ticks must be a 1-D int64 array")
    try:
        numerator = int(numerator)
        denominator = int(denominator)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("datetime64 conversion ratio must be positive int64") from exc
    i64_max = np.iinfo(np.int64).max
    if not (0 < numerator <= i64_max and 0 < denominator <= i64_max):
        raise ValueError("datetime64 conversion ratio must be positive int64")
    out = np.empty(len(arr), dtype=np.float64)
    status = _lib.xy_datetime64_to_ms(
        arr.ctypes.data,
        len(arr),
        arr.strides[0],
        numerator,
        denominator,
        out.ctypes.data,
    )
    if status == -1:
        raise OverflowError("Overflow when converting between datetime64 units")
    if status != 1:
        raise ValueError("invalid datetime64 conversion arguments")
    return out


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
    ok = _lib.xy_encode_f32(_ptr_f64(data), len(data), offset, scale, out.ctypes.data)
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
    ok = _lib.xy_stacked_bounds(
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
    ok = _lib.xy_histogram2d(
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
    written = _lib.xy_quad_mesh_triangles(
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
    query = _lib.xy_sector_triangles(*common, 0, 0, 0, 0, 0, 0, 0, 0)
    if query == _USIZE_MAX:
        raise ValueError("invalid sector geometry")
    outputs = [np.empty(query, dtype=np.float64) for _ in range(7)]
    written = _lib.xy_sector_triangles(
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
    ok = _lib.xy_rfft(
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
    ok = _lib.xy_welch_spectra(
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
    ok = _lib.xy_spectrogram(
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
    ok = _lib.xy_correlation(
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
    written = _lib.xy_weighted_ecdf(
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
    written = _lib.xy_indexed_triangles(
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
    written = _lib.xy_triangle_edges(
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
    written = _lib.xy_delaunay_triangles(
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
    written = _lib.xy_polygon_triangles(
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
    query = _lib.xy_marching_triangles(*common, 0, 0, 0, 0, 0, 0)
    if query == _USIZE_MAX:
        raise ValueError("invalid marching triangle geometry")
    outputs = [np.empty(query, dtype=np.float64) for _ in range(5)]
    if query == 0:
        return outputs[0], outputs[1], outputs[2], outputs[3], outputs[4]
    written = _lib.xy_marching_triangles(
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
    written = _lib.xy_vector_segments(
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
    query = _lib.xy_streamlines(
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
    written = _lib.xy_streamlines(
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
    written = _lib.xy_m4_indices(
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


def m4_points(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    n_buckets: int,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """M4-decimate an x/y pair without materializing gather indices in Python."""
    n_buckets = _bounded_positive_int(n_buckets, "n_buckets")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if len(x) == 0:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty.copy()
    out_x = np.empty(n_buckets * 4, dtype=np.float64)
    out_y = np.empty(n_buckets * 4, dtype=np.float64)
    written = _lib.xy_m4_points(
        _ptr_f64(x),
        _ptr_f64(y),
        len(x),
        x0,
        x1,
        n_buckets,
        _ptr_f64(out_x),
        _ptr_f64(out_y),
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid m4 arguments")
    return out_x[:written], out_y[:written]


def svg_poly_path(x: npt.ArrayLike, y: npt.ArrayLike) -> str:
    """Serialize parallel screen coordinates as SVG path data in Rust."""
    xa = np.ascontiguousarray(x, dtype=np.float64).reshape(-1)
    ya = np.ascontiguousarray(y, dtype=np.float64).reshape(-1)
    if len(xa) != len(ya) or len(xa) == 0:
        raise ValueError("x and y must be non-empty and have equal length")
    # Normal chart coordinates fit comfortably. The ABI returns the exact
    # requirement without writing when an adversarial fixed-point value needs
    # more room, so the uncommon retry remains allocation-safe.
    capacity = max(64, len(xa) * 32)
    while True:
        out = ctypes.create_string_buffer(capacity)
        written = _lib.xy_svg_poly_path(_ptr_f64(xa), _ptr_f64(ya), len(xa), out, capacity)
        if written == _USIZE_MAX:
            raise ValueError("invalid SVG polyline coordinates")
        if written <= capacity:
            return out.raw[:written].decode("ascii")
        capacity = written


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

    def allocate(
        size: int,
    ) -> tuple[
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
    ]:
        return (
            np.empty(size, dtype=np.float64),
            np.empty(size, dtype=np.float64),
            np.empty(size, dtype=np.float64),
            np.empty(size, dtype=np.float64),
            np.empty(size, dtype=np.float64),
        )

    def extract(outputs: tuple[npt.NDArray[np.float64], ...]) -> int:
        return int(
            _lib.xy_marching_squares(
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
    return (
        outputs[0][:written],
        outputs[1][:written],
        outputs[2][:written],
        outputs[3][:written],
        outputs[4][:written],
    )


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
        ok = _lib.xy_bin_2d(
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
    written = _lib.xy_bin_2d_indices(
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
    # First paint autoranges to the data extent, so every finite row is
    # usually in range: avoid duplicating the full selection when no slack
    # needs trimming.
    return grid, idx if written == len(idx) else idx[:written].copy()


def bin_2d_sample_range(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    w: int,
    h: int,
    seed: int,
    threshold: int,
    capacity_hint: int,
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.uint32]]:
    """Return the exact density grid and implicit-row sample in one scan."""
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    y0, y1 = _finite_increasing(y0, y1, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    seed = _bounded_nonnegative_int(seed, "seed", max_value=np.iinfo(np.uint64).max)
    threshold = _bounded_nonnegative_int(threshold, "threshold", max_value=np.iinfo(np.uint64).max)
    capacity = _bounded_nonnegative_int(capacity_hint, "capacity_hint", max_value=len(x))
    grid = np.zeros((h, w), dtype=np.float32)
    rows = np.empty(capacity, dtype=np.uint32)

    def extract(output: npt.NDArray[np.uint32]) -> int:
        return int(
            _lib.xy_bin_2d_sample_range(
                _ptr_f64(x),
                _ptr_f64(y),
                len(x),
                x0,
                x1,
                y0,
                y1,
                w,
                h,
                ctypes.c_uint64(int(seed)),
                ctypes.c_uint64(int(threshold)),
                grid.ctypes.data,
                output.ctypes.data if len(output) else None,
                len(output),
            )
        )

    written = extract(rows)
    if written == _USIZE_MAX:
        raise ValueError("invalid bin_2d_sample_range arguments")
    if written > capacity:
        rows = np.empty(written, dtype=np.uint32)
        repeated = extract(rows)
        if repeated != written:
            raise RuntimeError("native bin_2d_sample_range returned an inconsistent count")
    return grid, rows[:written]


def bin_2d_stratified_sample_range_u8_counted(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    groups: npt.NDArray[np.uint8],
    counts: npt.NDArray[np.uint64],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    w: int,
    h: int,
    seed: int,
    fraction: float,
    min_count: int,
    capacity_hint: int,
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.uint32]]:
    """Return the exact density grid and counted u8 stratified sample."""
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    y0, y1 = _finite_increasing(y0, y1, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    groups = np.asarray(groups)
    if groups.ndim != 1 or groups.dtype != np.uint8 or len(groups) != len(x):
        raise ValueError("groups must be a one-dimensional uint8 array matching x and y")
    groups = np.ascontiguousarray(groups)
    counts = np.asarray(counts)
    if counts.ndim != 1 or counts.dtype != np.uint64 or not 1 <= len(counts) <= 256:
        raise ValueError("counts must be a one-dimensional uint64 array of length 1..256")
    counts = np.ascontiguousarray(counts)
    seed = _bounded_nonnegative_int(seed, "seed", max_value=np.iinfo(np.uint64).max)
    fraction = _finite_float(fraction, "fraction")
    if fraction <= 0.0:
        raise ValueError("fraction must be > 0")
    min_count = _bounded_nonnegative_int(min_count, "min_count", max_value=np.iinfo(np.uint64).max)
    capacity = _bounded_nonnegative_int(capacity_hint, "capacity_hint", max_value=len(x))
    grid = np.zeros((h, w), dtype=np.float32)
    rows = np.empty(capacity, dtype=np.uint32)

    def extract(output: npt.NDArray[np.uint32]) -> int:
        return int(
            _lib.xy_bin_2d_stratified_sample_range_u8_counted(
                _ptr_f64(x),
                _ptr_f64(y),
                groups.ctypes.data if len(groups) else None,
                len(x),
                counts.ctypes.data,
                len(counts),
                x0,
                x1,
                y0,
                y1,
                w,
                h,
                ctypes.c_uint64(seed),
                ctypes.c_double(fraction),
                ctypes.c_uint64(min_count),
                grid.ctypes.data,
                output.ctypes.data if len(output) else None,
                len(output),
            )
        )

    written = extract(rows)
    if written == _USIZE_MAX:
        raise ValueError("invalid bin_2d_stratified_sample_range_u8_counted arguments or codes")
    if written > capacity:
        rows = np.empty(written, dtype=np.uint32)
        repeated = extract(rows)
        if repeated != written:
            raise RuntimeError("native categorical bin/sample returned an inconsistent count")
    return grid, rows[:written]


def is_sorted(data: npt.NDArray[np.float64]) -> bool:
    """Non-decreasing check with NaN-poisoning (any NaN fails its pairs) —
    identical to ``np.all(np.diff(data) >= 0)`` without the two temporaries."""
    data = _as_f64(data, "data")
    if len(data) < 2:
        return True
    return bool(_lib.xy_is_sorted(_ptr_f64(data), len(data)))


def min_max(data: npt.NDArray[np.float64]) -> Optional[tuple[float, float]]:
    """NaN-skipping min/max; None for empty/all-NaN input."""
    data = _as_f64(data, "data")
    if len(data) == 0:
        return None
    lo = ctypes.c_double()
    hi = ctypes.c_double()
    ok = _lib.xy_min_max(_ptr_f64(data), len(data), ctypes.byref(lo), ctypes.byref(hi))
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
    written = _lib.xy_histogram_uniform(
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
        ok = _lib.xy_normalize_f32(_ptr_f64(data), len(data), lo, hi, nan_mode, out.ctypes.data)
        if ok != 1:
            raise RuntimeError("xy native normalize_f32 failed (output undefined)")
    return out


def valid_indices_f64(
    columns: tuple[npt.NDArray[np.float64], ...],
    *,
    positive_columns: tuple[int, ...] = (),
) -> Optional[npt.NDArray[np.uint32]]:
    """Rows finite across every column, or ``None`` when every row is valid.

    ``positive_columns`` additionally requires ``> 0`` for those zero-based
    column positions. The all-valid path is one allocation-free Rust scan;
    only a filtered result allocates row IDs.
    """
    if not 1 <= len(columns) <= 64:
        raise ValueError("columns must contain between 1 and 64 arrays")
    arrays = tuple(_as_f64(column, f"columns[{index}]") for index, column in enumerate(columns))
    size = len(arrays[0])
    if any(len(array) != size for array in arrays[1:]):
        raise ValueError("validity columns must have equal length")
    positive_mask = 0
    for column in positive_columns:
        column = _bounded_nonnegative_int(column, "positive column", max_value=len(arrays) - 1)
        positive_mask |= 1 << column
    pointer_array_type = ctypes.c_void_p * len(arrays)
    pointers = pointer_array_type(*(array.ctypes.data if size else None for array in arrays))

    def invoke(output: npt.NDArray[np.uint32] | None) -> int:
        return int(
            _lib.xy_valid_indices_f64(
                pointers,
                len(arrays),
                size,
                ctypes.c_uint64(positive_mask),
                output.ctypes.data if output is not None and len(output) else None,
                len(output) if output is not None else 0,
            )
        )

    written = invoke(None)
    if written == _USIZE_MAX or written > size:
        raise ValueError("invalid valid_indices_f64 arguments")
    if written == size:
        return None
    # A source-sized scratch lets Rust workers fill disjoint row-aligned
    # segments and compact in parallel. Shrink before returning so callers do
    # not retain N-row storage for a small filtered result.
    output = np.empty(size, dtype=np.uint32)
    repeated = invoke(output)
    if repeated != written:
        raise RuntimeError("native valid_indices_f64 returned an inconsistent count")
    return output[:written].copy()


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
    written = _lib.xy_range_indices(
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
    return out if written == len(out) else out[:written].copy()


def sample_mask(
    ids: npt.NDArray[np.uint64],
    seed: int,
    threshold: int,
) -> npt.NDArray[np.bool_]:
    """Deterministic sampling mask: `splitmix64(ids + seed) <= threshold`.

    Bit-identical to `lod.hash_row_ids(ids, seed=seed) <= threshold` (the
    NumPy reference, asserted by the parity test), fused into one native pass
    with no full-width u64 temporaries. uint32 ids dispatch to an entry point
    that widens each id in-register instead of copying the full selection.
    """
    ids = np.asarray(ids)
    if ids.dtype == np.uint32:
        ids = np.ascontiguousarray(ids)
        fn = _lib.xy_sample_mask_u32
    else:
        ids = np.ascontiguousarray(ids, dtype=np.uint64)
        fn = _lib.xy_sample_mask
    if ids.ndim != 1:
        raise ValueError("ids must be a one-dimensional uint64 array")
    out = np.empty(len(ids), dtype=np.uint8)
    if len(ids):
        ok = fn(
            ids.ctypes.data,
            len(ids),
            ctypes.c_uint64(int(seed)),
            ctypes.c_uint64(int(threshold)),
            out.ctypes.data,
        )
        if ok != 1:
            raise RuntimeError("xy native sample_mask failed (output undefined)")
    return out.view(np.bool_)


def sample_range_indices(
    size: int,
    seed: int,
    threshold: int,
    capacity_hint: int,
) -> npt.NDArray[np.uint32]:
    """Sample implicit ids ``0..size`` without an input array or mask."""
    size = _bounded_nonnegative_int(size, "size", max_value=np.iinfo(np.uint32).max)
    capacity = _bounded_nonnegative_int(capacity_hint, "capacity_hint", max_value=size)
    out = np.empty(capacity, dtype=np.uint32)
    written = _lib.xy_sample_range_indices(
        size,
        ctypes.c_uint64(int(seed)),
        ctypes.c_uint64(int(threshold)),
        out.ctypes.data if capacity else None,
        capacity,
    )
    if written == _USIZE_MAX:
        raise ValueError("invalid sample_range_indices arguments")
    if written > capacity:
        out = np.empty(written, dtype=np.uint32)
        repeated = _lib.xy_sample_range_indices(
            size,
            ctypes.c_uint64(int(seed)),
            ctypes.c_uint64(int(threshold)),
            out.ctypes.data,
            written,
        )
        if repeated != written:
            raise RuntimeError("native sample_range_indices returned an inconsistent count")
    return out[:written]


def stratified_sample_range_u8(
    groups: npt.NDArray[np.uint8],
    n_groups: int,
    seed: int,
    fraction: float,
    min_count: int,
    capacity_hint: int,
    counts: npt.NDArray[np.uint64] | None = None,
) -> npt.NDArray[np.uint32]:
    """Stratified sample of implicit ids ``0..len(groups)``.

    This is equivalent to materializing the ids and a stratified keep mask,
    but its temporary memory scales with the returned sample.
    """
    groups = np.asarray(groups)
    if groups.ndim != 1 or groups.dtype != np.uint8:
        raise ValueError("groups must be a one-dimensional uint8 array")
    groups = np.ascontiguousarray(groups)
    n_groups = _bounded_positive_int(n_groups, "n_groups", 256)
    fraction = _finite_float(fraction, "fraction")
    if fraction <= 0.0:
        raise ValueError("fraction must be > 0")
    min_count = _bounded_nonnegative_int(min_count, "min_count", np.iinfo(np.uint64).max)
    capacity = _bounded_nonnegative_int(capacity_hint, "capacity_hint", len(groups))
    if counts is not None:
        counts = np.asarray(counts)
        if counts.ndim != 1 or counts.dtype != np.uint64 or len(counts) != n_groups:
            raise ValueError("counts must be a uint64 array with one value per group")
        counts = np.ascontiguousarray(counts)

    def invoke(out_pointer: int | None, out_capacity: int) -> int:
        if counts is None:
            return int(
                _lib.xy_stratified_sample_range_u8(
                    groups.ctypes.data if len(groups) else None,
                    len(groups),
                    n_groups,
                    ctypes.c_uint64(int(seed)),
                    ctypes.c_double(fraction),
                    ctypes.c_uint64(min_count),
                    out_pointer,
                    out_capacity,
                )
            )
        return int(
            _lib.xy_stratified_sample_range_u8_counted(
                groups.ctypes.data if len(groups) else None,
                len(groups),
                counts.ctypes.data,
                n_groups,
                ctypes.c_uint64(int(seed)),
                ctypes.c_double(fraction),
                ctypes.c_uint64(min_count),
                out_pointer,
                out_capacity,
            )
        )

    out = np.empty(capacity, dtype=np.uint32)
    written = invoke(out.ctypes.data if capacity else None, capacity)
    if written == _USIZE_MAX:
        detail = "counts or group code" if counts is not None else "arguments or group code"
        raise ValueError(f"invalid stratified_sample_range_u8 {detail}")
    if written > capacity:
        out = np.empty(written, dtype=np.uint32)
        repeated = invoke(out.ctypes.data, written)
        if repeated != written:
            raise RuntimeError("native stratified_sample_range_u8 returned an inconsistent count")
    return out[:written]


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
    uint32 ids dispatch to the in-register widening entry point.
    """
    ids = np.asarray(ids)
    if ids.dtype == np.uint32:
        ids = np.ascontiguousarray(ids)
        fn = _lib.xy_stratified_sample_mask_u32
    else:
        ids = np.ascontiguousarray(ids, dtype=np.uint64)
        fn = _lib.xy_stratified_sample_mask
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
        ok = fn(
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
        _lib.xy_pyramid_build(
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


def pyramid_append(
    handle: int,
    x: "npt.NDArray[np.float64]",
    y: "npt.NDArray[np.float64]",
) -> bool:
    """Increment an existing count pyramid from a canonical append batch.

    Returns ``False`` when the handle is stale/busy or a finite point expands
    the pyramid domain; callers then invalidate it and lazily rebuild. A false
    result never partially updates the native cache.
    """
    handle = _pyramid_handle(handle)
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    return (
        _lib.xy_pyramid_append(
            ctypes.c_uint64(handle),
            _ptr_f64(x) if len(x) else None,
            _ptr_f64(y) if len(y) else None,
            len(x),
        )
        == 1
    )


def pyramid_count(handle: int, lo_x: float, hi_x: float, lo_y: float, hi_y: float) -> float | None:
    handle = _pyramid_handle(handle)
    lo_x, hi_x = _finite_increasing(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_increasing(lo_y, hi_y, "y range")
    out = ctypes.c_double(0.0)
    ok = _lib.xy_pyramid_count(
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
) -> tuple[npt.NDArray[np.float32], int] | None:
    """(grid f32 [h*w], level) from the pyramid, or None when the window
    outresolves it (caller falls back to an exact re-bin, §28)."""
    handle = _pyramid_handle(handle)
    lo_x, hi_x = _finite_increasing(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_increasing(lo_y, hi_y, "y range")
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    out = np.zeros(w * h, dtype=np.float32)
    level = _lib.xy_pyramid_compose(
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
    return _lib.xy_pyramid_free(ctypes.c_uint64(_pyramid_handle(handle))) == 1


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
        ok = _lib.xy_local_log_density(
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
    ok = _lib.xy_rasterize(cmd_ptr, buf.size, _ptr_u8(out), w, h)
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
    written = _lib.xy_rasterize_png(cmd_ptr, buf.size, _ptr_u8(out), out.size, w, h)
    if written == _USIZE_MAX or written > out.size:
        raise ValueError("native raster-to-PNG encoder rejected the command buffer")
    return out[:written].tobytes()


def rasterize_data(cmds: bytes, data: bytes, w: int, h: int) -> npt.NDArray[np.uint8]:
    """Paint a display list that may reference a synchronous external arena."""
    w = _positive_int(w, "raster width")
    h = _positive_int(h, "raster height")
    buf = np.frombuffer(cmds, dtype=np.uint8)
    arena = np.frombuffer(data, dtype=np.uint8)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    ok = _lib.xy_rasterize_data(
        _ptr_u8(buf) if buf.size else None,
        buf.size,
        _ptr_u8(arena) if arena.size else None,
        arena.size,
        _ptr_u8(out),
        w,
        h,
    )
    if not ok:
        raise ValueError("native rasterizer rejected the command buffer or external data")
    return out


def rasterize_png_data(cmds: bytes, data: bytes, w: int, h: int) -> bytes:
    """Paint and encode a display list backed by a synchronous external arena."""
    w = _positive_int(w, "raster width")
    h = _positive_int(h, "raster height")
    buf = np.frombuffer(cmds, dtype=np.uint8)
    arena = np.frombuffer(data, dtype=np.uint8)
    raw_len = operator.mul(operator.mul(w, h), 4)
    capacity = raw_len + raw_len // 8 + 65_536
    out = np.empty(capacity, dtype=np.uint8)
    written = _lib.xy_rasterize_png_data(
        _ptr_u8(buf) if buf.size else None,
        buf.size,
        _ptr_u8(arena) if arena.size else None,
        arena.size,
        _ptr_u8(out),
        out.size,
        w,
        h,
    )
    if written == _USIZE_MAX or written > out.size:
        raise ValueError(
            "native raster-to-PNG encoder rejected the command buffer or external data"
        )
    return out[:written].tobytes()


def _byte_span_arrays(spans):  # noqa: ANN001, ANN202 - private ctypes adapter
    arenas: list[npt.NDArray[np.uint8]] = []
    for span in spans:
        if isinstance(span, np.ndarray):
            contiguous = np.ascontiguousarray(span)
            arena = contiguous.view(np.uint8).reshape(-1)
        else:
            arena = np.frombuffer(span, dtype=np.uint8)
        arenas.append(arena)
    pointer_type = ctypes.c_void_p * len(arenas)
    length_type = ctypes.c_size_t * len(arenas)
    pointers = pointer_type(*(arena.ctypes.data if arena.size else None for arena in arenas))
    lengths = length_type(*(arena.size for arena in arenas))
    return arenas, pointers, lengths


def rasterize_spans(cmds: bytes, spans, w: int, h: int) -> npt.NDArray[np.uint8]:  # noqa: ANN001
    """Paint a display list borrowing multiple call-scoped byte arenas."""
    w = _positive_int(w, "raster width")
    h = _positive_int(h, "raster height")
    buf = np.frombuffer(cmds, dtype=np.uint8)
    arenas, pointers, lengths = _byte_span_arrays(spans)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    ok = _lib.xy_rasterize_spans(
        _ptr_u8(buf) if buf.size else None,
        buf.size,
        pointers if arenas else None,
        lengths if arenas else None,
        len(arenas),
        _ptr_u8(out),
        w,
        h,
    )
    if not ok:
        raise ValueError("native rasterizer rejected the command buffer or borrowed spans")
    return out


def rasterize_png_spans(cmds: bytes, spans, w: int, h: int) -> bytes:  # noqa: ANN001
    """Paint and encode a display list borrowing multiple byte arenas."""
    w = _positive_int(w, "raster width")
    h = _positive_int(h, "raster height")
    buf = np.frombuffer(cmds, dtype=np.uint8)
    arenas, pointers, lengths = _byte_span_arrays(spans)
    raw_len = operator.mul(operator.mul(w, h), 4)
    capacity = raw_len + raw_len // 8 + 65_536
    out = np.empty(capacity, dtype=np.uint8)
    written = _lib.xy_rasterize_png_spans(
        _ptr_u8(buf) if buf.size else None,
        buf.size,
        pointers if arenas else None,
        lengths if arenas else None,
        len(arenas),
        _ptr_u8(out),
        out.size,
        w,
        h,
    )
    if written == _USIZE_MAX or written > out.size:
        raise ValueError("native raster-to-PNG encoder rejected the command buffer or spans")
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
    ok = _lib.xy_heatmap_rgba(
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


def density_rgba(
    encoded: npt.ArrayLike,
    w: int,
    h: int,
    maximum: float,
    stops: npt.ArrayLike,
    opacity: float,
) -> npt.NDArray[np.uint8]:
    """Map a log-u8 density grid to a vertically flipped RGBA8 image."""
    w = _positive_int(w, "density width")
    h = _positive_int(h, "density height")
    values = np.ascontiguousarray(encoded, dtype=np.uint8).reshape(-1)
    stop_array = np.ascontiguousarray(stops, dtype=np.uint8)
    maximum = _finite_float(maximum, "density maximum")
    opacity = _finite_float(opacity, "density opacity")
    if maximum < 0.0:
        raise ValueError("density maximum must be >= 0")
    if not 0.0 <= opacity <= 1.0:
        raise ValueError("density opacity must be in [0, 1]")
    if values.size != w * h:
        raise ValueError("density scalar count must match width * height")
    if stop_array.ndim != 2 or stop_array.shape[1] != 3 or stop_array.shape[0] < 1:
        raise ValueError("density stops must be a non-empty (n, 3) array")
    out = np.empty((h, w, 4), dtype=np.uint8)
    ok = _lib.xy_density_rgba(
        _ptr_u8(values),
        w,
        h,
        maximum,
        _ptr_u8(stop_array),
        stop_array.shape[0],
        opacity,
        _ptr_u8(out),
    )
    if not ok:
        raise ValueError("native density colormap rejected the inputs")
    return out


def density_log_u8(grid: npt.NDArray[np.float32]) -> tuple[npt.NDArray[np.uint8], float]:
    """Log-encode a density grid for the client's one-byte R8 texture."""
    values = np.ascontiguousarray(grid, dtype=np.float32)
    if values.ndim not in (1, 2):
        raise ValueError("density grid must be one- or two-dimensional")
    out = np.empty(values.shape, dtype=np.uint8)
    maximum = ctypes.c_double()
    ok = _lib.xy_density_log_u8(
        values.ctypes.data if values.size else None,
        values.size,
        out.ctypes.data if out.size else None,
        ctypes.byref(maximum),
    )
    if ok != 1:
        raise RuntimeError("xy native density_log_u8 failed")
    return out, float(maximum.value)


# xy_css_check kinds — keep in sync with `src/lib.rs`.
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
    passthrough), negative = error code (see `xy_css_check` docs). ``rgba``
    is the 0..1 channel tuple for statically-resolved colors, else None
    (`currentColor` parses with no static channels). The error-message
    mapping lives in `_validate.py`; this wrapper stays mechanical.
    """
    vb = value.encode("utf-8")
    pb = prop.encode("utf-8")
    out = (ctypes.c_float * 4)(float("nan"), 0.0, 0.0, 0.0)
    status = int(_lib.xy_css_check(kind, pb or None, len(pb), vb or None, len(vb), out))
    wrote = status == 1 and out[0] == out[0]  # NaN sentinel: untouched = no static color
    return status, (out[0], out[1], out[2], out[3]) if wrote else None
