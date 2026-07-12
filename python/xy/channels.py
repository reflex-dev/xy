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

import numbers
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import numpy.typing as npt

from . import _validate, kernels

_finite_scalar = _validate.finite_scalar

# Named colormaps the client knows (LUTs live in the JS client, §36). Kept
# small and CVD-safe by default.
COLORMAPS = (
    "viridis",
    "magma",
    "plasma",
    "inferno",
    "cividis",
    "gray",
    "turbo",
    "coolwarm",
    "blues",
    "rdylgn",
    "rainbow",
    "spectral",
    "piyg",
    "purples",
    "pubu",
    "prgn",
    "binary",
)


def is_colormap(name: str) -> bool:
    """Return whether *name* is a supported colormap, including ``_r`` variants."""
    return name in COLORMAPS or (name.endswith("_r") and name[:-2] in COLORMAPS)


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
    # Append-only backing storage for streaming continuous channels. Kept out
    # of the wire/spec surface; values remains the exact-length view.
    _buffer: Optional[npt.NDArray[np.float64]] = field(
        default=None, init=False, repr=False, compare=False
    )

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
    # See ColorChannel._buffer.
    _buffer: Optional[npt.NDArray[np.float64]] = field(
        default=None, init=False, repr=False, compare=False
    )

    def spec(self) -> dict[str, Any]:
        if self.mode == "constant":
            return {"mode": "constant", "size": self.constant}
        return {
            "mode": "continuous",
            "range_px": list(self.range_px),
            "domain": list(self.domain) if self.domain else None,
        }


def _is_categorical(arr: np.ndarray) -> bool:
    if arr.dtype.kind in ("U", "S", "b"):
        return True
    if arr.dtype == object:
        return not _object_array_is_real_numeric(arr)
    return False


def _is_missing_category(value: Any) -> bool:
    if value is None:
        return True
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return True
    try:
        # Covers float NaN, numpy scalar NaN/NaT, and pandas.NA-like values
        # without importing pandas. Object comparisons can return arrays or
        # raise, so keep this deliberately defensive.
        return bool(value != value)
    except Exception:
        return False


def category_label(value: Any) -> str:
    """Canonical display label for category-like data.

    Shared by categorical color channels and categorical axes so legends,
    ticks, and composed marks agree on how messy labels display.
    """
    if _is_missing_category(value):
        return "(missing)"
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def _factorize_categories(arr: np.ndarray) -> tuple[list[str], npt.NDArray[np.float64]]:
    """Factorize categorical data without relying on object sorting.

    `np.unique(..., return_inverse=True)` sorts the raw Python objects; mixed
    object arrays (`"a"`, `None`, `1`) raise in NumPy because those values are
    not mutually orderable. Chart labels are strings on the client anyway, so
    canonicalize to display labels first, sort those labels for deterministic
    palettes, and then map each row back to its code.
    """
    labels = [category_label(v) for v in arr.astype(object)]
    categories = sorted(set(labels))
    index = {label: i for i, label in enumerate(categories)}
    codes = np.fromiter((index[label] for label in labels), dtype=np.float64, count=len(labels))
    return categories, codes


def _object_array_is_real_numeric(arr: np.ndarray) -> bool:
    seen = False
    for value in arr:
        if _is_missing_category(value):
            continue
        seen = True
        if not _is_real_number_object(value):
            return False
    return seen


def _is_real_number_object(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_, str, bytes, np.bytes_)):
        return False
    if isinstance(value, numbers.Real):
        return True
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _as_real_array(values: np.ndarray, label: str) -> npt.NDArray[np.float64]:
    if np.issubdtype(values.dtype, np.bool_):
        raise ValueError(f"{label} must be real numeric, not boolean")
    if np.issubdtype(values.dtype, np.complexfloating):
        raise ValueError(f"{label} must be real numeric")
    if values.dtype == object and not _object_array_is_real_numeric(values):
        raise ValueError(f"{label} must be real numeric")
    try:
        return values.astype(np.float64, copy=False)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be real numeric") from e


def _size_range(range_px: tuple[float, float]) -> tuple[float, float]:
    try:
        lo_raw, hi_raw = range_px
    except (TypeError, ValueError) as e:
        raise ValueError("size_range must contain exactly two finite pixel values") from e
    lo = _finite_scalar(lo_raw, "size_range[0]")
    hi = _finite_scalar(hi_raw, "size_range[1]")
    if lo < 0 or hi < 0 or hi < lo:
        raise ValueError("size_range must be non-negative and ordered low-to-high")
    return (lo, hi)


def _continuous_domain(values: npt.NDArray[np.float64]) -> tuple[float, float]:
    bounds = kernels.min_max(values)
    if bounds is None:
        return (0.0, 1.0)
    lo, hi = bounds
    if lo == hi:
        pad = abs(lo) * 0.05 or 0.5
        return (lo - pad, hi + pad)
    return (lo, hi)


def append_continuous(channel: Any, values: npt.NDArray[np.float64], label: str) -> None:
    """Append a continuous channel in amortized O(tail) time.

    Geometry columns already use a capacity-doubling buffer for streaming;
    channel arrays need the same contract. The domain expands monotonically so
    a newly appended value is not silently clamped to the old color/size scale.
    Non-finite values remain valid channel inputs and are handled by the
    existing normalization policy; they do not expand the domain.
    """
    if channel.mode != "continuous" or channel.values is None:
        raise ValueError(f"{label} channel is not continuous")
    tail = np.ascontiguousarray(values, dtype=np.float64).ravel()
    if len(tail) == 0:
        return
    current = channel.values
    n_old = len(current)
    n_new = n_old + len(tail)
    buffer = channel._buffer
    if buffer is None or len(buffer) < n_new:
        capacity = max(n_new, n_old * 2, 1024)
        buffer = np.empty(capacity, dtype=np.float64)
        buffer[:n_old] = current
        channel._buffer = buffer
    elif not (
        np.shares_memory(current, buffer)
        and current.ndim == 1
        and current.size == n_old
        and current.strides == buffer.strides
        and current.__array_interface__["data"][0] == buffer.__array_interface__["data"][0]
    ):
        # `values` is expected to remain the exact prefix view of `_buffer`.
        # Re-copy if a future caller rebinds it, so a stale capacity buffer
        # cannot silently corrupt the retained prefix.
        buffer[:n_old] = current
    buffer[n_old:n_new] = tail
    channel.values = buffer[:n_new]

    finite = tail[np.isfinite(tail)]
    if len(finite):
        lo, hi = channel.domain or _continuous_domain(current)
        channel.domain = (min(lo, float(finite.min())), max(hi, float(finite.max())))


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
        # Literal constant color: validated against the native CSS grammar so
        # a typo errors here instead of rendering a silently wrong mark.
        return ColorChannel(mode="constant", constant=_validate.css_color(color, "color"))

    if hasattr(color, "to_numpy"):
        color = color.to_numpy()
    arr = np.asarray(color)
    if arr.ndim != 1 or len(arr) != n:
        raise ValueError(f"color array must be 1-D length {n}, got shape {arr.shape}")

    if not is_colormap(colormap):
        raise ValueError(f"unknown colormap {colormap!r}; known: {COLORMAPS}")

    if _is_categorical(arr):
        cats, codes = _factorize_categories(arr)
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
            codes=codes,
            categories=cats,
        )

    vals = _as_real_array(arr, "color array")
    return ColorChannel(
        mode="continuous", values=vals, domain=_continuous_domain(vals), colormap=colormap
    )


def resolve_size(size: Any, n: int, *, range_px: tuple[float, float] = (2.0, 18.0)) -> SizeChannel:
    if size is None:
        return SizeChannel(mode="constant")
    if np.isscalar(size):
        constant = _finite_scalar(size, "size")
        if constant < 0:
            raise ValueError("size must be non-negative")
        return SizeChannel(mode="constant", constant=constant)

    if hasattr(size, "to_numpy"):
        size = size.to_numpy()
    arr = np.asarray(size)
    if arr.ndim != 1 or len(arr) != n:
        raise ValueError(f"size array must be 1-D length {n}, got shape {arr.shape}")
    vals = _as_real_array(arr, "size array")
    return SizeChannel(
        mode="continuous",
        values=vals,
        domain=_continuous_domain(vals),
        range_px=_size_range(range_px),
    )


def normalize_to_unit(values: npt.NDArray[np.float64], domain: tuple[float, float]) -> np.ndarray:
    """Map values to [0,1] over `domain` (for continuous color/size upload).
    Non-finite (NaN, ±inf) → domain floor so it never poisons a vertex (§19);
    the validity story tightens with real bitmaps later."""
    return kernels.normalize_f32(values, domain, nonfinite="zero")


def ship_channels(trace: Any, sel: Any, ship_scalar: Any, palette: list[str]) -> tuple[Any, Any]:
    """Ship a trace's color and size channels in the standard wire shape
    (§29/§36c): per-point channels carry a `buf` index into the blob; constant
    channels ship spec-only. Used by the build path and by drill-in view
    updates for any chart kind with per-mark channels.

    Slices *before* normalizing: normalization is element-wise over a
    precomputed global domain, and drill updates call this per zoom step —
    normalizing all N rows to ship a 200k window is O(N) work for nothing.
    Returns (color_spec, size_spec)."""
    cc = trace.color_ch or ColorChannel(mode="constant", constant=None)
    color_spec = cc.spec()
    if cc.mode == "continuous":
        values = cc.values
        domain = cc.domain
        if values is None or domain is None:
            raise ValueError("continuous color channel missing values or domain")
        vals = values if sel is None else values[sel]
        color_spec["buf"] = ship_scalar(normalize_to_unit(vals, domain))
    elif cc.mode == "categorical":
        code_values = cc.codes
        categories = cc.categories
        if code_values is None or categories is None:
            raise ValueError("categorical color channel missing codes or categories")
        codes = code_values if sel is None else code_values[sel]
        color_spec["buf"] = ship_scalar(codes)
        color_spec["palette"] = [palette[i % len(palette)] for i in range(len(categories))]

    sc = trace.size_ch or SizeChannel(mode="constant")
    size_spec = sc.spec()
    if sc.mode == "continuous":
        values = sc.values
        domain = sc.domain
        if values is None or domain is None:
            raise ValueError("continuous size channel missing values or domain")
        vals = values if sel is None else values[sel]
        size_spec["buf"] = ship_scalar(normalize_to_unit(vals, domain))
    return color_spec, size_spec
