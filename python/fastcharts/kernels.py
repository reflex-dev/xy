"""Kernel dispatch: native Rust core when available, NumPy fallback otherwise.

The fallback is loud, never silent (§33: "no-wheel behavior is defined") — one
warning at import, and `BACKEND` is inspectable so tests and debug tooling can
assert which path served a figure (§28: every tier decision is observable).

Set FASTCHARTS_FORCE_FALLBACK=1 to force the NumPy path (used by parity tests).
"""

from __future__ import annotations

import os
import warnings

if os.environ.get("FASTCHARTS_FORCE_FALLBACK") == "1":
    from . import _fallback as _impl

    BACKEND = "numpy"
else:
    try:
        from . import _native as _impl  # type: ignore[no-redef]

        BACKEND = "native"
    except ImportError as err:
        from . import _fallback as _impl  # type: ignore[no-redef]

        BACKEND = "numpy"
        warnings.warn(
            f"fastcharts: native core unavailable ({err}); using the NumPy "
            "fallback. Interaction stays correct but ingest/decimation is "
            "slower — install a platform wheel or `cargo build --release`.",
            RuntimeWarning,
            stacklevel=2,
        )

zone_maps = _impl.zone_maps
encode_f32 = _impl.encode_f32
m4_indices = _impl.m4_indices
min_max = _impl.min_max

__all__ = ["BACKEND", "encode_f32", "m4_indices", "min_max", "zone_maps"]
