"""Scatter data channels: color and size (§36c — data-driven styling is
spec-level, resolved on the GPU, never CSS).

Transport principle (§2/§29): a per-point channel ships as **one f32 per point**
plus a small lookup table in the spec — a normalized scalar the GPU maps through
a colormap LUT (continuous) or a palette index (categorical), or a size range.
Never per-point RGBA (4×) when a scalar + LUT does. So a colored, sized scatter
is ~16 bytes/point on the wire (x, y, color-scalar, size-scalar), matching the
§2 "typical scatter ≤ 24 B/pt" budget with headroom.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import numpy.typing as npt

# Named colormaps the client knows (LUTs live in the JS client, §36). Kept
# small and CVD-safe by default.
COLORMAPS = ("viridis", "magma", "plasma", "cividis", "turbo")
DEFAULT_COLORMAP = "viridis"

# The client palette LUT is 256 texels; categories beyond this collide in the
# shader, so we warn (channels.resolve_color).
MAX_CATEGORIES = 256


@dataclass
class ColorChannel:
    """Resolved color encoding for a scatter trace."""

    mode: str  # "constant" | "continuous" | "categorical"
    # constant:
    constant: Optional[str] = None
    # continuous: per-point value normalized to [0,1] at ship time; domain kept
    # for the axis/legend readout (exact, f64 — never through f32, §16).
    values: Optional[npt.NDArray[np.float64]] = None
    domain: Optional[tuple[float, float]] = None
    colormap: str = DEFAULT_COLORMAP
    # categorical: integer code per point + the category labels + palette.
    codes: Optional[npt.NDArray[np.float64]] = None
    categories: Optional[list[str]] = None

    def spec(self) -> dict[str, Any]:
        if self.mode == "constant":
            return {"mode": "constant", "color": self.constant}
        if self.mode == "continuous":
            return {
                "mode": "continuous",
                "colormap": self.colormap,
                "domain": list(self.domain) if self.domain else None,
            }
        return {"mode": "categorical", "categories": self.categories}


@dataclass
class SizeChannel:
    mode: str  # "constant" | "continuous"
    constant: float = 4.0
    values: Optional[npt.NDArray[np.float64]] = None
    domain: Optional[tuple[float, float]] = None
    range_px: tuple[float, float] = (2.0, 18.0)

    def spec(self) -> dict[str, Any]:
        if self.mode == "constant":
            return {"mode": "constant", "size": self.constant}
        return {"mode": "continuous", "range_px": list(self.range_px)}


def _is_categorical(arr: np.ndarray) -> bool:
    return arr.dtype.kind in ("U", "S", "O", "b")


def resolve_color(
    color: Any,
    n: int,
    *,
    colormap: str = DEFAULT_COLORMAP,
    default_constant: str,
) -> ColorChannel:
    """Interpret the `color=` argument.

    - `None` / a CSS color string → constant.
    - a length-n array of numbers → continuous (normalized + colormap).
    - a length-n array of strings/categories → categorical (factorized + palette).
    """
    if color is None:
        return ColorChannel(mode="constant", constant=default_constant)
    if isinstance(color, str):
        return ColorChannel(mode="constant", constant=color)

    if hasattr(color, "to_numpy"):
        color = color.to_numpy()
    arr = np.asarray(color)
    if arr.ndim != 1 or len(arr) != n:
        raise ValueError(f"color array must be 1-D length {n}, got shape {arr.shape}")

    if colormap not in COLORMAPS:
        raise ValueError(f"unknown colormap {colormap!r}; known: {COLORMAPS}")

    if _is_categorical(arr):
        cats, codes = np.unique(arr.astype(object), return_inverse=True)
        if len(cats) > MAX_CATEGORIES:
            import warnings

            # The client's palette LUT is 256-wide; beyond that, codes collide
            # in the shader. A categorical scatter with >256 distinct values is
            # rarely legible anyway — warn loudly rather than mis-color silently.
            warnings.warn(
                f"categorical color has {len(cats)} categories; only the first "
                f"{MAX_CATEGORIES} get distinct palette slots (the rest collide). "
                "Consider grouping rare categories or a continuous encoding.",
                RuntimeWarning,
                stacklevel=3,
            )
        return ColorChannel(
            mode="categorical",
            codes=codes.astype(np.float64),
            categories=[str(c) for c in cats.tolist()],
        )

    vals = arr.astype(np.float64)
    finite = vals[np.isfinite(vals)]
    lo = float(finite.min()) if len(finite) else 0.0
    hi = float(finite.max()) if len(finite) else 1.0
    return ColorChannel(mode="continuous", values=vals, domain=(lo, hi), colormap=colormap)


def resolve_size(size: Any, n: int, *, range_px: tuple[float, float] = (2.0, 18.0)) -> SizeChannel:
    if size is None:
        return SizeChannel(mode="constant")
    if np.isscalar(size):
        return SizeChannel(mode="constant", constant=float(size))

    if hasattr(size, "to_numpy"):
        size = size.to_numpy()
    arr = np.asarray(size)
    if arr.ndim != 1 or len(arr) != n:
        raise ValueError(f"size array must be 1-D length {n}, got shape {arr.shape}")
    vals = arr.astype(np.float64)
    finite = vals[np.isfinite(vals)]
    lo = float(finite.min()) if len(finite) else 0.0
    hi = float(finite.max()) if len(finite) else 1.0
    return SizeChannel(mode="continuous", values=vals, domain=(lo, hi), range_px=range_px)


def normalize_to_unit(values: npt.NDArray[np.float64], domain: tuple[float, float]) -> np.ndarray:
    """Map values to [0,1] over `domain` (for continuous color/size upload).
    Non-finite (NaN, ±inf) → domain floor so it never poisons a vertex (§19);
    the validity story tightens with real bitmaps later."""
    lo, hi = domain
    span = hi - lo if hi > lo else 1.0
    safe = np.where(np.isfinite(values), values, lo)
    return np.clip((safe - lo) / span, 0.0, 1.0)


def ship_channels(trace: Any, sel: Any, ship_scalar: Any, palette: list[str]) -> tuple[Any, Any]:
    """Ship a trace's color and size channels in the standard wire shape
    (§29/§36c): per-point channels carry a `buf` index into the blob; constant
    channels ship spec-only. Used by the build path and by drill-in view
    updates for any chart kind with per-mark channels.

    Slices *before* normalizing: normalization is element-wise over a
    precomputed global domain, and drill updates call this per zoom step —
    normalizing all N rows to ship a 200k window is O(N) work for nothing.
    Returns (color_spec, size_spec)."""
    cc = trace.color_ch
    color_spec = cc.spec()
    if cc.mode == "continuous":
        vals = cc.values if sel is None else cc.values[sel]
        color_spec["buf"] = ship_scalar(normalize_to_unit(vals, cc.domain))
    elif cc.mode == "categorical":
        codes = cc.codes if sel is None else cc.codes[sel]
        color_spec["buf"] = ship_scalar(codes)
        color_spec["palette"] = [palette[i % len(palette)] for i in range(len(cc.categories))]

    sc = trace.size_ch
    size_spec = sc.spec()
    if sc.mode == "continuous":
        vals = sc.values if sel is None else sc.values[sel]
        size_spec["buf"] = ship_scalar(normalize_to_unit(vals, sc.domain))
    return color_spec, size_spec
