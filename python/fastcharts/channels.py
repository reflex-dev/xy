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
    NaN → 0 so it never poisons a vertex (§19); the validity story tightens with
    real bitmaps later."""
    lo, hi = domain
    span = hi - lo if hi > lo else 1.0
    out = (np.nan_to_num(values, nan=lo) - lo) / span
    return np.clip(out, 0.0, 1.0)
