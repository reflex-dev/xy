"""Kernel dispatch: the native Rust core is required.

xy computes through a compiled Rust C-ABI core. There is no pure-Python
fallback: if the native core cannot be loaded — an unsupported platform with no
published wheel and no local Rust build — importing this module raises
ImportError with remediation, rather than silently degrading (§33: no-wheel
behavior is defined, and it is a loud failure).

`BACKEND` stays inspectable (always ``"native"``) so tooling can keep asserting
which path served a figure (§28: every tier decision is observable).
"""

from __future__ import annotations

try:
    from . import _native as _impl
except ImportError as err:  # pragma: no cover - platform-dependent
    raise ImportError(
        "xy requires its native Rust core, which could not be loaded "
        f"({err}). Prebuilt wheels cover Linux glibc and musl (x86-64, aarch64, "
        "armv7), macOS (x86-64, Apple Silicon), and Windows (x86, x64, arm64); "
        "on those platforms `pip install xy` needs no toolchain. On any "
        "other platform, install a Rust toolchain (https://rustup.rs) and "
        "reinstall from source (or run `cargo build --release`)."
    ) from err

BACKEND = "native"

CSS_DECLARATION = _impl.CSS_DECLARATION
CSS_COLOR = _impl.CSS_COLOR
CSS_LENGTH = _impl.CSS_LENGTH
CSS_NUMBER = _impl.CSS_NUMBER

css_check = _impl.css_check
correlation = _impl.correlation
density_rgba = _impl.density_rgba
density_log_u8 = _impl.density_log_u8
delaunay_triangles = _impl.delaunay_triangles
zone_maps = _impl.zone_maps
zone_maps_pair = _impl.zone_maps_pair
encode_f32 = _impl.encode_f32
factorize_fixed = _impl.factorize_fixed
factorize_fixed_u8 = _impl.factorize_fixed_u8
factorize_fixed_u8_counts = _impl.factorize_fixed_u8_counts
factorize_unicode1_u8_counts = _impl.factorize_unicode1_u8_counts
m4_indices = _impl.m4_indices
marching_squares = _impl.marching_squares
marching_triangles = _impl.marching_triangles
is_sorted = _impl.is_sorted
min_max = _impl.min_max
bin_2d = _impl.bin_2d
bin_2d_indices = _impl.bin_2d_indices
bin_2d_sample_range = _impl.bin_2d_sample_range
bin_2d_stratified_sample_range_u8_counted = _impl.bin_2d_stratified_sample_range_u8_counted
histogram_uniform = _impl.histogram_uniform
heatmap_rgba = _impl.heatmap_rgba
histogram2d = _impl.histogram2d
indexed_triangles = _impl.indexed_triangles
normalize_f32 = _impl.normalize_f32
valid_indices_f64 = _impl.valid_indices_f64
remap_u8 = _impl.remap_u8
range_indices = _impl.range_indices
sample_mask = _impl.sample_mask
sample_range_indices = _impl.sample_range_indices
stratified_sample_range_u8 = _impl.stratified_sample_range_u8
sector_triangles = _impl.sector_triangles
stacked_bounds = _impl.stacked_bounds
streamlines = _impl.streamlines
triangle_edges = _impl.triangle_edges
local_log_density = _impl.local_log_density
pyramid_build = _impl.pyramid_build
pyramid_append = _impl.pyramid_append
pyramid_count = _impl.pyramid_count
pyramid_compose = _impl.pyramid_compose
pyramid_free = _impl.pyramid_free
polygon_triangles = _impl.polygon_triangles
quad_mesh_triangles = _impl.quad_mesh_triangles
rasterize = _impl.rasterize
rasterize_png = _impl.rasterize_png
rfft = _impl.rfft
spectrogram = _impl.spectrogram
stratified_sample_mask = _impl.stratified_sample_mask
vector_segments = _impl.vector_segments
welch_spectra = _impl.welch_spectra
weighted_ecdf = _impl.weighted_ecdf

__all__ = [
    "BACKEND",
    "CSS_COLOR",
    "CSS_DECLARATION",
    "CSS_LENGTH",
    "CSS_NUMBER",
    "bin_2d",
    "bin_2d_indices",
    "bin_2d_sample_range",
    "bin_2d_stratified_sample_range_u8_counted",
    "correlation",
    "css_check",
    "delaunay_triangles",
    "density_log_u8",
    "density_rgba",
    "encode_f32",
    "factorize_fixed",
    "factorize_fixed_u8",
    "factorize_fixed_u8_counts",
    "factorize_unicode1_u8_counts",
    "heatmap_rgba",
    "histogram2d",
    "histogram_uniform",
    "indexed_triangles",
    "is_sorted",
    "local_log_density",
    "m4_indices",
    "marching_squares",
    "marching_triangles",
    "min_max",
    "normalize_f32",
    "polygon_triangles",
    "pyramid_append",
    "pyramid_build",
    "pyramid_compose",
    "pyramid_count",
    "pyramid_free",
    "quad_mesh_triangles",
    "range_indices",
    "rasterize",
    "rasterize_png",
    "remap_u8",
    "rfft",
    "sample_mask",
    "sample_range_indices",
    "sector_triangles",
    "spectrogram",
    "stacked_bounds",
    "stratified_sample_mask",
    "stratified_sample_range_u8",
    "streamlines",
    "triangle_edges",
    "valid_indices_f64",
    "vector_segments",
    "weighted_ecdf",
    "welch_spectra",
    "zone_maps",
    "zone_maps_pair",
]
