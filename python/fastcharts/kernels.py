"""Kernel dispatch: the native Rust core is required.

fastcharts computes through a compiled Rust C-ABI core. There is no pure-Python
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
        "fastcharts requires its native Rust core, which could not be loaded "
        f"({err}). Prebuilt wheels cover Linux (x86-64, aarch64), macOS "
        "(x86-64, arm64), and Windows (x86-64); on those platforms "
        "`pip install fastcharts` needs no toolchain. On any other platform, "
        "install a Rust toolchain (https://rustup.rs) and reinstall from "
        "source (or run `cargo build --release`)."
    ) from err

BACKEND = "native"

zone_maps = _impl.zone_maps
encode_f32 = _impl.encode_f32
m4_indices = _impl.m4_indices
min_max = _impl.min_max
bin_2d = _impl.bin_2d
histogram_uniform = _impl.histogram_uniform
normalize_f32 = _impl.normalize_f32
range_indices = _impl.range_indices
local_log_density = _impl.local_log_density
pyramid_build = _impl.pyramid_build
pyramid_count = _impl.pyramid_count
pyramid_compose = _impl.pyramid_compose
pyramid_free = _impl.pyramid_free

__all__ = [
    "BACKEND",
    "bin_2d",
    "encode_f32",
    "histogram_uniform",
    "local_log_density",
    "m4_indices",
    "min_max",
    "normalize_f32",
    "pyramid_build",
    "pyramid_compose",
    "pyramid_count",
    "pyramid_free",
    "range_indices",
    "zone_maps",
]
