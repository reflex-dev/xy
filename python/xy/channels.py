"""Scatter data channels: color and size (§36c — data-driven styling is
spec-level, resolved on the GPU, never CSS).

Transport principle (§2/§29): a per-point channel ships as one compact scalar
plus a small lookup table in the spec — f32 for normalized continuous values,
or u8 for categorical palette indices when the client LUT can represent every
category. Never per-point RGBA (4×) when a scalar + LUT does. So a categorical,
sized scatter is ~13 bytes/point on the wire (x, y, color-code, size-scalar),
matching the §2 "typical scatter ≤ 24 B/pt" budget with headroom.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import numpy.typing as npt

from . import _validate, config, kernels

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
    "rdgy",
    "rdbu",
    "jet",
    "binary",
)


def is_colormap(name: str) -> bool:
    """Return whether *name* is a supported colormap, including ``_r`` variants."""
    return name in COLORMAPS or (name.endswith("_r") and name[:-2] in COLORMAPS)


DEFAULT_COLORMAP = "viridis"

# The client palette LUT is 256 texels; categories beyond this collide in the
# shader, so we warn (channels.resolve_color).
MAX_CATEGORIES = 256
_FACTORIZE_PROBE_ROWS = 4096
_FACTORIZE_NATIVE_MAX_PROBE_CATEGORIES = 512


@dataclass
class ColorChannel:
    """Resolved color encoding for a scatter trace."""

    mode: str  # "constant" | "continuous" | "categorical" | "direct_rgba" | "match_fill"
    # constant:
    constant: Optional[str] = None
    # continuous: per-point value normalized to [0,1] at ship time; domain kept
    # for the axis/legend readout (exact, f64 — never through f32, §16).
    values: Optional[npt.NDArray[np.float64]] = None
    domain: Optional[tuple[float, float]] = None
    colormap: str = DEFAULT_COLORMAP
    # categorical: integer code per point + the category labels + palette.
    codes: Optional[npt.NDArray[np.uint8] | npt.NDArray[np.uint32]] = None
    categories: Optional[list[str]] = None
    # Exact dense-code counts, fused into native compact factorization. They
    # let full-domain stratified sampling skip a source-sized recount.
    counts: Optional[npt.NDArray[np.uint64]] = None
    # direct_rgba: canonical straight-alpha float RGBA.  The wire uses packed
    # normalized RGBA8, while keeping the canonical values here lets pyplot
    # getters and post-hoc artist mutation retain Matplotlib semantics.
    rgba: Optional[npt.NDArray[np.float64]] = None
    # Append-only backing storage for streaming continuous channels. Kept out
    # of the wire/spec surface; values remains the exact-length view.
    _buffer: Optional[npt.NDArray[np.float64]] = field(
        default=None, init=False, repr=False, compare=False
    )

    def spec(self) -> dict[str, Any]:
        """The channel's resolved settings as a plain dict, exactly as
        shipped in the chart spec."""
        if self.mode == "constant":
            return {"mode": "constant", "color": self.constant}
        if self.mode == "continuous":
            return {
                "mode": "continuous",
                "colormap": self.colormap,
                "domain": list(self.domain) if self.domain else None,
            }
        if self.mode == "direct_rgba":
            return {"mode": "direct_rgba", "components": 4, "dtype": "u8"}
        if self.mode == "match_fill":
            return {"mode": "match_fill"}
        return {"mode": "categorical", "categories": self.categories}


@dataclass
class StyleChannel:
    """A direct per-mark style channel in final renderer units.

    ``values`` is always canonical f64 except for integer-coded symbols.  The
    payload compiler chooses compact f32/u8 transport and slices it with the
    same row selection as geometry and paint.
    """

    values: np.ndarray
    components: int = 1
    dtype: str = "f32"  # "f32" | "u8"

    def spec(self) -> dict[str, Any]:
        return {"mode": "direct", "components": self.components, "dtype": self.dtype}


@dataclass
class SizeChannel:
    """A resolved scatter size encoding: constant, or values mapped to a
    pixel range. Built by `resolve_size`."""

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
        """The channel's resolved settings as a plain dict, exactly as
        shipped in the chart spec."""
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


def _category_code_dtype(category_count: int) -> type[np.uint8] | type[np.uint32]:
    return np.uint8 if category_count <= MAX_CATEGORIES else np.uint32


def _use_native_fixed_factorizer(arr: np.ndarray) -> bool:
    """Choose the O(N) hash path when a bounded global probe is low-cardinality.

    With nearly every label unique, Python must still materialize and sort the
    complete display-label set; hashing those records first is redundant work.
    Sampling across the full array avoids that regression while keeping the
    decision independent of N.
    """
    n = len(arr)
    if n <= _FACTORIZE_PROBE_ROWS:
        probe = arr
    else:
        rows = np.linspace(0, n - 1, _FACTORIZE_PROBE_ROWS, dtype=np.intp)
        probe = arr[rows]
    return len(np.unique(probe)) <= _FACTORIZE_NATIVE_MAX_PROBE_CATEGORIES


def _factorize_categories(
    arr: np.ndarray,
) -> tuple[
    list[str],
    npt.NDArray[np.uint8] | npt.NDArray[np.uint32],
    Optional[npt.NDArray[np.uint64]],
]:
    """Factorize categorical data without relying on object sorting.

    `np.unique(..., return_inverse=True)` sorts the raw Python objects; mixed
    object arrays (`"a"`, `None`, `1`) raise in NumPy because those values are
    not mutually orderable. Chart labels are strings on the client anyway, so
    canonicalize to display labels first, sort those labels for deterministic
    palettes, and then map each row back to its code. Fixed-width NumPy
    strings/bytes/bools can identify equal records in Rust without creating N
    Python objects; only their compact unique set crosses the label-policy path.
    """
    if arr.dtype.kind in ("U", "S", "b") and _use_native_fixed_factorizer(arr):
        compact = (
            kernels.factorize_unicode1_u8_counts(arr, MAX_CATEGORIES)
            if arr.dtype.kind == "U" and arr.dtype.itemsize == 4
            else kernels.factorize_fixed_u8_counts(arr, MAX_CATEGORIES)
        )
        if compact is not None:
            raw_codes, unique_indices, raw_counts = compact
            unique_labels = [category_label(value) for value in arr[unique_indices]]
            categories = sorted(set(unique_labels))
            index = {label: i for i, label in enumerate(categories)}
            remap = np.fromiter(
                (index[label] for label in unique_labels),
                dtype=np.uint8,
                count=len(unique_labels),
            )
            identity = np.arange(len(remap), dtype=np.uint8)
            if not np.array_equal(remap, identity):
                kernels.remap_u8(raw_codes, remap)
            counts = np.zeros(len(categories), dtype=np.uint64)
            for label, count in zip(unique_labels, raw_counts, strict=True):
                counts[index[label]] += count
            return categories, raw_codes, counts

        raw_codes, unique_indices = kernels.factorize_fixed(arr)
        unique_labels = [category_label(value) for value in arr[unique_indices]]
        categories = sorted(set(unique_labels))
        index = {label: i for i, label in enumerate(categories)}
        dtype = _category_code_dtype(len(categories))
        remap = np.fromiter(
            (index[label] for label in unique_labels),
            dtype=dtype,
            count=len(unique_labels),
        )
        return categories, remap[raw_codes], None

    labels = [category_label(v) for v in arr.astype(object)]
    categories = sorted(set(labels))
    index = {label: i for i, label in enumerate(categories)}
    codes = np.fromiter(
        (index[label] for label in labels),
        dtype=_category_code_dtype(len(categories)),
        count=len(labels),
    )
    return categories, codes, None


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
    domain: Optional[tuple[float, float]] = None,
) -> ColorChannel:
    """Interpret the `color=` argument.

    - `None` / a CSS color string → constant.
    - a length-n array of numbers → continuous (normalized + colormap).
    - a length-n array of strings/categories → categorical (factorized + palette).

    `domain` pins the continuous normalization window (matplotlib's
    vmin/vmax); values outside clip to the colormap ends.
    """
    if not is_colormap(colormap):
        raise ValueError(f"unknown colormap {colormap!r}; known: {COLORMAPS}")
    if domain is not None:
        lo, hi = float(domain[0]), float(domain[1])
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            raise ValueError(f"color domain must be finite (lo, hi) with lo < hi, got {domain!r}")
        domain = (lo, hi)

    # Constant channels keep the colormap too: it still drives the density
    # ramp when the trace aggregates (§5 Tier 2), and a typo'd name must
    # error here rather than render a silently wrong ramp.
    if color is None:
        return ColorChannel(mode="constant", constant=default_constant, colormap=colormap)
    if isinstance(color, str):
        # Literal constant color: validated against the native CSS grammar so
        # a typo errors here instead of rendering a silently wrong mark.
        return ColorChannel(
            mode="constant", constant=_validate.css_color(color, "color"), colormap=colormap
        )

    if hasattr(color, "to_numpy"):
        color = color.to_numpy()
    arr = np.asarray(color)
    if arr.ndim == 2 and arr.shape in {(n, 3), (n, 4)}:
        try:
            rgba = np.asarray(arr, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("direct RGB/RGBA colors must be real numeric") from exc
        if not np.isfinite(rgba).all() or np.any((rgba < 0.0) | (rgba > 1.0)):
            raise ValueError("direct RGB/RGBA colors must contain finite values between 0 and 1")
        if rgba.shape[1] == 3:
            rgba = np.column_stack((rgba, np.ones(n, dtype=np.float64)))
        return ColorChannel(mode="direct_rgba", rgba=np.ascontiguousarray(rgba))

    if arr.ndim != 1 or len(arr) != n:
        raise ValueError(f"color array must be 1-D length {n}, got shape {arr.shape}")

    if _is_categorical(arr):
        cats, codes, counts = _factorize_categories(arr)
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
        elif len(cats) > len(config.DEFAULT_PALETTE):
            import warnings

            # The default palette is deliberately eight slots (its adjacency
            # order is the CVD-safety gate; see config.DEFAULT_PALETTE), so
            # category colors repeat modulo eight. Allowed, never silent (§28).
            warnings.warn(
                f"categorical color has {len(cats)} categories but the default "
                f"palette has {len(config.DEFAULT_PALETTE)} colors; colors repeat "
                f"every {len(config.DEFAULT_PALETTE)} categories (category 9 "
                "wears category 1's color). Consider grouping rare categories "
                "or a continuous encoding.",
                RuntimeWarning,
                stacklevel=3,
            )
        return ColorChannel(
            mode="categorical",
            codes=codes,
            categories=cats,
            counts=counts,
        )

    vals = _as_real_array(arr, "color array")
    return ColorChannel(
        mode="continuous",
        values=vals,
        domain=domain if domain is not None else _continuous_domain(vals),
        colormap=colormap,
    )


def resolve_size(size: Any, n: int, *, range_px: tuple[float, float] = (2.0, 18.0)) -> SizeChannel:
    """Resolve a scatter ``size`` input into a `SizeChannel`.

    A scalar (or None) becomes a constant size; a length-``n`` numeric
    array maps linearly onto ``range_px`` pixels.
    """
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
    Non-finite (NaN, ±inf) → domain floor so it never poisons a vertex
    (design dossier §19); the validity story tightens with real bitmaps
    later."""
    return kernels.normalize_f32(values, domain, nonfinite="zero")


def quantize_unit_u8(values: npt.NDArray[np.float64], domain: tuple[float, float]) -> np.ndarray:
    """Normalize over `domain` and quantize to u8 (0..255 spanning [0,1]).

    The lossy sibling of :func:`normalize_to_unit`, for wire paths where the
    value is only ever a GPU LUT/ramp coordinate (a colormap texture has 256
    texels; a size ramp spans ~16 px) and is never read back into a displayed
    number — 75% less traffic than f32, same rendered output (§29). Chunked
    like the other full-column quantizers (LOD doc §4.4): drill slices see one
    pass, while the spatial-index builder can feed a whole 1e9-row column with
    chunk-bounded temporaries and identical per-element results."""
    out = np.empty(len(values), dtype=np.uint8)
    for start in range(0, len(values), _QUANTIZE_CHUNK):
        end = start + _QUANTIZE_CHUNK
        unit = normalize_to_unit(values[start:end], domain)
        out[start:end] = np.rint(np.clip(unit, 0.0, 1.0) * 255.0).astype(np.uint8)
    return out


def colormap_lut_rgba8(colormap: str) -> npt.NDArray[np.uint8]:
    """The client's 256-texel colormap LUT as (256, 4) straight-alpha RGBA8.

    Built from the same stop tables the SVG exporter mirrors from
    `js/src/10_colormaps.ts`, so a value binned through this LUT wears the
    byte-identical color its drawn point does."""
    from . import _svg  # deferred: channels is core, _svg owns the stop tables

    lut = np.empty((256, 4), dtype=np.uint8)
    lut[:, :3] = _svg._lut(colormap, np.linspace(0.0, 1.0, 256))
    lut[:, 3] = 255
    return lut


def palette_rgba8(palette: list[str], n_categories: int) -> npt.NDArray[np.uint8]:
    """Categorical palette colors as straight-alpha RGBA8 LUT rows.

    One row per category up to 256; beyond that callers fold codes modulo the
    base palette instead (`resolve_bin_colors`), which is the same repeat rule
    `ship_color_channel` applies."""
    rows = min(n_categories, MAX_CATEGORIES)
    lut = np.empty((max(rows, 1), 4), dtype=np.uint8)
    for i in range(lut.shape[0]):
        status, rgba = kernels.css_check(kernels.CSS_COLOR, str(palette[i % len(palette)]))
        if status != 1 or rgba is None:
            rgba = (0.0, 0.0, 0.0, 1.0)
        lut[i] = [round(c * 255) for c in rgba]
    return lut


def bins_mean_color(cc: Optional[ColorChannel]) -> bool:
    """Whether this channel aggregates to a mean-color density plane at
    Tier 2 (LOD doc §2) instead of being dropped. Cheap predicate — no
    arrays are touched — for warning/spec sites; `resolve_bin_colors` is
    gated on exactly this."""
    return cc is not None and cc.mode in ("continuous", "categorical", "direct_rgba")


# Chunk length for full-column color-source quantization. The math is
# element-wise, so chunking changes nothing but the transient footprint: a
# one-shot pipeline materializes several full-length f64 temporaries at once
# (~20 GB at 1e9 rows — the difference between a colored billion-point build
# fitting in RAM or not), while chunked passes keep every temporary at chunk
# size and the only N-sized allocation is the u8 result.
_QUANTIZE_CHUNK = 1 << 22


def _quantized_lut_idx(values: npt.NDArray[np.float64], domain: tuple[float, float]) -> np.ndarray:
    """Continuous values -> u8 LUT texel indices, chunk-bounded temporaries.

    Per-element math is exactly the historical one-shot chain —
    `normalize_to_unit` (f32), widen to f64, ×255, `rint`, cast u8 — applied
    per chunk, so results are bitwise identical while peak memory stays
    O(chunk) + the N-byte output."""
    out = np.empty(len(values), dtype=np.uint8)
    for start in range(0, len(values), _QUANTIZE_CHUNK):
        end = start + _QUANTIZE_CHUNK
        unit = normalize_to_unit(values[start:end], domain)
        out[start:end] = np.rint(np.asarray(unit, dtype=np.float64) * 255.0).astype(np.uint8)
    return out


def _quantized_rgba8(values: npt.NDArray[np.float64]) -> np.ndarray:
    """Float RGBA rows -> straight-alpha RGBA8, chunk-bounded temporaries."""
    out = np.empty(values.shape, dtype=np.uint8)
    for start in range(0, len(values), _QUANTIZE_CHUNK):
        end = start + _QUANTIZE_CHUNK
        seg = values[start:end]
        out[start:end] = np.rint(np.clip(seg, 0.0, 1.0) * 255.0).astype(np.uint8)
    return out


def _folded_codes_u8(codes: np.ndarray, n_palette: int) -> np.ndarray:
    """Wide categorical codes -> u8 palette rows (mod fold), chunk-bounded."""
    out = np.empty(len(codes), dtype=np.uint8)
    for start in range(0, len(codes), _QUANTIZE_CHUNK):
        end = start + _QUANTIZE_CHUNK
        out[start:end] = (codes[start:end] % n_palette).astype(np.uint8)
    return out


def resolve_bin_colors(cc: Optional[ColorChannel], sel: Any, palette: list[str]) -> Optional[dict]:
    """Kernel color source for mean-color density binning (LOD doc §2).

    Returns `kernels.bin_2d_mean_color`-style kwargs — ``{"idx", "lut"}`` for
    palette/colormap channels, ``{"rgba"}`` for direct RGBA — resolved to the
    straight-alpha RGBA8 each point *draws* with, so the aggregated surface
    and the drawn marks share one color story. Constant channels return
    ``None``: their mean is the constant, so the count-only grid plus the
    client-side tint reproduces it exactly with no per-cell color plane.
    """
    if not bins_mean_color(cc):
        return None
    assert cc is not None
    if cc.mode == "direct_rgba":
        rgba = cc.rgba
        if rgba is None:
            raise ValueError("direct RGBA color channel missing values")
        values = rgba if sel is None else rgba[sel]
        return {"rgba": _quantized_rgba8(values)}
    if cc.mode == "continuous":
        values = cc.values
        domain = cc.domain
        if values is None or domain is None:
            raise ValueError("continuous color channel missing values or domain")
        vals = values if sel is None else values[sel]
        # Same normalization the wire ships, quantized to the nearest of the
        # client's 256 LUT texels (chunked: full-column calls keep transient
        # temporaries chunk-bounded instead of several × N).
        return {"idx": _quantized_lut_idx(vals, domain), "lut": colormap_lut_rgba8(cc.colormap)}
    code_values = cc.codes
    categories = cc.categories
    if code_values is None or categories is None:
        raise ValueError("categorical color channel missing codes or categories")
    codes = code_values if sel is None else code_values[sel]
    if codes.dtype == np.uint8:
        return {"idx": codes, "lut": palette_rgba8(palette, len(categories))}
    # >256 categories ship wide codes; palette colors repeat every
    # len(palette) categories, so folding the codes onto the base palette
    # bins each point with exactly the color it draws with.
    return {
        "idx": _folded_codes_u8(codes, len(palette)),
        "lut": palette_rgba8(palette, len(palette)),
    }


def ship_channels(
    trace: Any,
    sel: Any,
    ship_scalar: Any,
    ship_u8: Any,
    palette: list[str],
    *,
    quantize_continuous: bool = False,
) -> tuple[Any, Any]:
    """Ship a trace's color and size channels in the standard wire shape
    (design dossier §29/§36c): per-point channels carry a `buf` index into the blob; constant
    channels ship spec-only. Used by the build path and by drill-in view
    updates for any chart kind with per-mark channels.

    Slices *before* normalizing: normalization is element-wise over a
    precomputed global domain, and drill updates call this per zoom step —
    normalizing all N rows to ship a 200k window is O(N) work for nothing.

    `quantize_continuous` ships continuous color/size as u8 LUT coordinates
    (`dtype: "u8"` marker) instead of unit f32. Live-interaction paths opt in:
    their hover/pick answers come from the server's canonical columns, so the
    quantization is invisible. The build path must NOT opt in — it retains the
    shipped columns CPU-side (`_cpu.color`/`_cpu.size`) and denormalizes them
    for tooltip readouts, where 8-bit steps would show as wrong digits.
    Returns (color_spec, size_spec)."""
    cc = trace.color_ch or ColorChannel(mode="constant", constant=None)
    color_spec = ship_color_channel(
        cc, sel, ship_scalar, ship_u8, palette, quantize_continuous=quantize_continuous
    )
    sc = trace.size_ch or SizeChannel(mode="constant")
    size_spec = sc.spec()
    if sc.mode == "continuous":
        values = sc.values
        domain = sc.domain
        if values is None or domain is None:
            raise ValueError("continuous size channel missing values or domain")
        vals = values if sel is None else values[sel]
        if quantize_continuous:
            size_spec["buf"] = ship_u8(quantize_unit_u8(vals, domain))
            size_spec["dtype"] = "u8"
        else:
            size_spec["buf"] = ship_scalar(normalize_to_unit(vals, domain))
    return color_spec, size_spec


def ship_color_channel(
    cc: ColorChannel,
    sel: Any,
    ship_scalar: Any,
    ship_u8: Any,
    palette: list[str],
    *,
    quantize_continuous: bool = False,
) -> dict[str, Any]:
    """Ship one fill/stroke paint channel in the common wire representation."""
    color_spec = cc.spec()
    if cc.mode == "direct_rgba":
        rgba = cc.rgba
        if rgba is None:
            raise ValueError("direct RGBA color channel missing values")
        values = rgba if sel is None else rgba[sel]
        packed = np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)
        color_spec["buf"] = ship_u8(packed.reshape(-1))
        color_spec["n"] = int(len(values))
    elif cc.mode == "match_fill":
        pass
    elif cc.mode == "continuous":
        values = cc.values
        domain = cc.domain
        if values is None or domain is None:
            raise ValueError("continuous color channel missing values or domain")
        vals = values if sel is None else values[sel]
        if quantize_continuous:
            color_spec["buf"] = ship_u8(quantize_unit_u8(vals, domain))
            color_spec["dtype"] = "u8"
        else:
            color_spec["buf"] = ship_scalar(normalize_to_unit(vals, domain))
    elif cc.mode == "categorical":
        code_values = cc.codes
        categories = cc.categories
        if code_values is None or categories is None:
            raise ValueError("categorical color channel missing codes or categories")
        codes = code_values if sel is None else code_values[sel]
        # The palette texture has exactly 256 entries.  When every category is
        # representable, codes are lossless bytes: 75% less channel traffic
        # and GPU storage than f32.  Keep the legacy f32 path above that limit
        # so existing >256-category collision behavior is unchanged.
        if len(categories) <= MAX_CATEGORIES:
            color_spec["buf"] = ship_u8(codes)
            color_spec["dtype"] = "u8"
        else:
            color_spec["buf"] = ship_scalar(codes)
        color_spec["palette"] = [palette[i % len(palette)] for i in range(len(categories))]

    return color_spec


def resolve_style_channel(
    value: Any,
    n: int,
    label: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    components: int = 1,
) -> tuple[Any, Optional[StyleChannel]]:
    """Return ``(constant, channel)`` for a scalar-or-direct numeric style."""
    if value is None or (np.isscalar(value) and components == 1):
        if value is None:
            return None, None
        constant = _finite_scalar(value, label)
        if minimum is not None and constant < minimum:
            raise ValueError(f"{label} must be at least {minimum}")
        if maximum is not None and constant > maximum:
            raise ValueError(f"{label} must be at most {maximum}")
        return constant, None
    arr = np.asarray(value)
    expected = (n,) if components == 1 else (n, components)
    if arr.shape != expected:
        raise ValueError(f"{label} array must have shape {expected}, got {arr.shape}")
    values = _as_real_array(arr.reshape(-1), f"{label} array").reshape(expected)
    if not np.isfinite(values).all():
        raise ValueError(f"{label} array must contain only finite values")
    if minimum is not None and np.any(values < minimum):
        raise ValueError(f"{label} array values must be at least {minimum}")
    if maximum is not None and np.any(values > maximum):
        raise ValueError(f"{label} array values must be at most {maximum}")
    return None, StyleChannel(np.ascontiguousarray(values), components=components)


def ship_style_channels(
    style_channels: dict[str, StyleChannel], sel: Any, ship_scalar: Any, ship_u8: Any
) -> dict[str, Any]:
    """Ship direct style channels after applying the geometry row selection."""
    result: dict[str, Any] = {}
    for name, channel in style_channels.items():
        values = channel.values if sel is None else channel.values[sel]
        spec = channel.spec()
        flat = np.ascontiguousarray(values).reshape(-1)
        spec["buf"] = ship_u8(flat) if channel.dtype == "u8" else ship_scalar(flat)
        spec["n"] = int(len(values))
        result[name] = spec
    return result
