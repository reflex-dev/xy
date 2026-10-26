"""matplotlib color vocabulary → CSS colors the engine accepts.

Covers the surfaces real scripts use: single-letter codes, the default
prop cycle (``C0``–``C9``), ``tab:*`` names, and gray shorthand ("0.5").
Everything else (CSS names, hex, rgb()) passes through — the engine
validates CSS colors natively.
"""

from __future__ import annotations

import numbers
import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any, NamedTuple, Optional, TypeGuard, cast

import numpy as np


def scalar_float(value: Any) -> float:
    """``float()`` behind an ``Any`` boundary.

    ``np.isscalar`` narrows to a union that includes ``complex``, which
    ``float()`` rejects at runtime anyway — keep that runtime behavior
    without every call site repeating a cast."""
    return float(value)


# matplotlib's default prop cycle (tab10) — series with no explicit color
# take these in order, so shim output reads like matplotlib.
PROP_CYCLE = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)

_SINGLE_LETTER = {
    "b": "#0000ff",
    "g": "#008000",
    "r": "#ff0000",
    "c": "#00bfbf",
    "m": "#bf00bf",
    "y": "#bfbf00",
    "k": "#000000",
    "w": "#ffffff",
}

_TAB = {
    "tab:blue": "#1f77b4",
    "tab:orange": "#ff7f0e",
    "tab:green": "#2ca02c",
    "tab:red": "#d62728",
    "tab:purple": "#9467bd",
    "tab:brown": "#8c564b",
    "tab:pink": "#e377c2",
    "tab:gray": "#7f7f7f",
    "tab:grey": "#7f7f7f",
    "tab:olive": "#bcbd22",
    "tab:cyan": "#17becf",
}

# The gallery currently exercises this XKCD color as a standalone ``plot``
# format string. Keep the dependency boundary explicit: pyplot must not import
# Matplotlib just to resolve its named-color table.
_XKCD = {
    "xkcd:crimson": "#8c000f",
}

# matplotlib colormap names the engine knows (identity), plus common aliases.
CMAPS = {
    "viridis": "viridis",
    "plasma": "plasma",
    "inferno": "inferno",
    "magma": "magma",
    "cividis": "cividis",
    "autumn": "autumn",
    "gray": "gray",
    "grey": "gray",
    "greys": "gray",
    "turbo": "turbo",
    "coolwarm": "coolwarm",
    "rdbu": "rdbu",
    "rdbu_r": "rdbu_r",
    "bwr": "coolwarm",
    "blues": "blues",
    "rdylgn": "rdylgn",
    "rainbow": "rainbow",
    "spectral": "spectral",
    "piyg": "piyg",
    "purples": "purples",
    "pubu": "pubu",
    "prgn": "prgn",
    "rdgy": "rdgy",
    "jet": "jet",
    "binary": "binary",
    "flag": "flag",
    "reds": "reds",
    "bone": "bone",
    "winter": "winter",
    "bupu": "bupu",
    "rdylbu": "rdylbu",
    "ylgn": "ylgn",
    "wistia": "wistia",
    "puor": "puor",
}


class Cmap:
    """Small callable colormap carrier compatible with common pyplot scripts."""

    def __init__(self, name: str) -> None:
        self.name = resolve_cmap(name)
        self.N = 256
        self._bad: object = "transparent"
        self._under: object | None = None
        self._over: object | None = None

    def resampled(self, lutsize: int) -> "Cmap":
        result = Cmap(self.name)
        result.N = max(1, int(lutsize))
        return result

    def with_extremes(self, **kwargs: object) -> "Cmap":
        result = Cmap(self.name)
        result.N = self.N
        for key in ("bad", "under", "over"):
            if key in kwargs:
                getattr(result, f"set_{key}")(kwargs[key])
        return result

    def set_bad(self, color: object = "transparent", alpha: object = None) -> None:
        self._bad = color if alpha is None else (color, alpha)

    def set_under(self, color: object = "transparent", alpha: object = None) -> None:
        self._under = color if alpha is None else (color, alpha)

    def set_over(self, color: object = "transparent", alpha: object = None) -> None:
        self._over = color if alpha is None else (color, alpha)

    def __call__(self, values: object) -> object:
        from xy._svg import _lut

        source = np.asarray(values)
        array = np.asarray(values, dtype=np.float64)
        normalized = array
        if np.issubdtype(source.dtype, np.integer):
            normalized = array / max(1, self.N - 1)
        flat_values = normalized.reshape(-1)
        flat = _lut(self.name, np.clip(np.nan_to_num(flat_values, nan=0.0), 0.0, 1.0)) / 255.0
        rgba = np.column_stack((flat, np.ones(len(flat), dtype=np.float64))).reshape(
            array.shape + (4,)
        )
        flat_rgba = rgba.reshape(-1, 4)
        for mask, extreme in (
            (np.isnan(flat_values), self._bad),
            (flat_values < 0.0, self._under),
            (flat_values > 1.0, self._over),
        ):
            if extreme is not None and np.any(mask):
                flat_rgba[mask] = _rgba_floats(extreme)
        return tuple(rgba.tolist()) if array.ndim == 0 else rgba


def _user_color_table(colors: object) -> np.ndarray:
    """(M, 3|4) rows of 0-1 floats (or resolvable color strings) → (M, 4) RGBA."""
    if isinstance(colors, (list, tuple)) and colors and all(isinstance(c, str) for c in colors):
        rows = []
        for spec in colors:
            resolved = resolve_color(spec) or ""
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", resolved):
                raise ValueError(
                    f"unsupported colormap color {spec!r}; use hex strings or 0-1 RGB(A) rows"
                )
            rows.append([int(resolved[i : i + 2], 16) / 255.0 for i in (1, 3, 5)] + [1.0])
        return np.asarray(rows, dtype=np.float64)
    table = np.asarray(colors, dtype=np.float64)
    if table.ndim != 2 or table.shape[1] not in (3, 4) or not len(table):
        raise ValueError("colormap colors must be an (N, 3) or (N, 4) array of 0-1 floats")
    if table.shape[1] == 3:
        table = np.column_stack((table, np.ones(len(table), dtype=np.float64)))
    return np.clip(table, 0.0, 1.0)


class ListedColormap:
    """matplotlib.colors.ListedColormap: a user-supplied discrete color table.

    The engine renders *named* colormaps only, so user-built colormaps serve
    the Python-side idiom — ``cmap(np.arange(cmap.N))`` — whose RGBA output
    feeds image/scatter calls directly. Passing one as ``cmap=`` still fails
    loudly in ``resolve_cmap`` (there is no engine table to render).
    """

    def __init__(self, colors: object, name: str = "listed", N: int | None = None) -> None:
        table = _user_color_table(colors)
        if N is not None:
            count = max(1, int(N))
            table = np.tile(table, (-(-count // len(table)), 1))[:count]
        self.colors = table
        self.name = str(name)
        self.N = len(table)

    def __call__(self, values: object) -> object:
        array = np.asarray(values)
        if np.issubdtype(array.dtype, np.integer):
            index = np.clip(array, 0, self.N - 1)
        else:
            scaled = np.clip(np.nan_to_num(np.asarray(array, np.float64), nan=0.0), 0.0, 1.0)
            index = np.minimum((scaled * self.N).astype(int), self.N - 1)
        rgba = self.colors[index]
        return tuple(rgba.tolist()) if array.ndim == 0 else rgba


class LinearSegmentedColormap:
    """matplotlib's from_list surface: anchors interpolated Python-side.

    Same engine boundary as ListedColormap — callable for RGBA tables, not
    renderable by name.
    """

    def __init__(self, name: str, anchors: np.ndarray, N: int = 256) -> None:
        self.name = str(name)
        self._anchors = anchors
        self.N = max(1, int(N))

    @classmethod
    def from_list(
        cls, name: str, colors: object, N: int = 256, **kwargs: object
    ) -> "LinearSegmentedColormap":
        if kwargs:
            raise TypeError(f"from_list() got unsupported keyword argument {next(iter(kwargs))!r}")
        return cls(name, _user_color_table(colors), N)

    def resampled(self, lutsize: int) -> "LinearSegmentedColormap":
        return LinearSegmentedColormap(self.name, self._anchors, lutsize)

    def __call__(self, values: object) -> object:
        array = np.asarray(values)
        normalized = np.asarray(array, dtype=np.float64)
        if np.issubdtype(array.dtype, np.integer):
            normalized = normalized / max(1, self.N - 1)
        clipped = np.clip(np.nan_to_num(normalized, nan=0.0), 0.0, 1.0)
        position = clipped * (len(self._anchors) - 1)
        low = np.floor(position).astype(int)
        high = np.minimum(low + 1, len(self._anchors) - 1)
        t = (position - low)[..., None]
        rgba = self._anchors[low] * (1.0 - t) + self._anchors[high] * t
        return tuple(rgba.tolist()) if array.ndim == 0 else rgba


def _rgba_floats(value: object) -> tuple[float, float, float, float]:
    """Resolve the bounded color forms used by colormap extremes."""
    alpha: object = None
    color = value
    if isinstance(value, (tuple, list)) and _is_color_alpha_pair(value):
        color, alpha = value[0], value[1]
    resolved = resolve_color(color)
    if resolved is None or resolved == "transparent":
        result = (0.0, 0.0, 0.0, 0.0)
    elif resolved.startswith("#") and len(resolved) in (7, 9):
        channels = [
            int(resolved[index : index + 2], 16) / 255.0 for index in range(1, len(resolved), 2)
        ]
        result = (channels[0], channels[1], channels[2], channels[3] if len(channels) == 4 else 1.0)
    elif resolved.startswith("rgb("):
        channels = [float(part) for part in resolved[4:-1].split(",")]
        result = (channels[0] / 255.0, channels[1] / 255.0, channels[2] / 255.0, 1.0)
    elif resolved.startswith("rgba("):
        channels = [float(part) for part in resolved[5:-1].split(",")]
        result = (channels[0] / 255.0, channels[1] / 255.0, channels[2] / 255.0, channels[3])
    else:
        named = {
            "black": (0.0, 0.0, 0.0, 1.0),
            "white": (1.0, 1.0, 1.0, 1.0),
            "red": (1.0, 0.0, 0.0, 1.0),
            "green": (0.0, 0.5, 0.0, 1.0),
            "blue": (0.0, 0.0, 1.0, 1.0),
            "yellow": (1.0, 1.0, 0.0, 1.0),
            "cyan": (0.0, 1.0, 1.0, 1.0),
            "magenta": (1.0, 0.0, 1.0, 1.0),
        }
        result = named.get(resolved.lower())
        if result is None:
            # Ordinary plotting colors can be any CSS named color because the
            # engine validates them natively. Colormap extremes are baked to
            # RGBA in Python, so route the same vocabulary through the native
            # CSS parser rather than narrowing it to eight basic names.
            result = resolve_rgba(resolved)
    if isinstance(alpha, numbers.Real) and not isinstance(alpha, (bool, np.bool_)):
        result = (result[0], result[1], result[2], float(alpha))
    if not all(np.isfinite(result)) or any(channel < 0.0 or channel > 1.0 for channel in result):
        raise ValueError(f"RGBA channels must be finite and between 0 and 1, got {value!r}")
    return result


def cmap_extreme(
    cmap: object,
    name: str,
    default: object = None,
) -> np.ndarray | None:
    """Resolve one shim or Matplotlib colormap extreme to straight RGBA.

    XY's lightweight colormaps store ``_bad``/``_under``/``_over`` while
    Matplotlib's own colormaps use ``_rgba_bad``/``_rgba_under``/
    ``_rgba_over``.  Keeping both spellings behind one resolver prevents
    images, contours, and their colorbars from disagreeing about configured
    cap and invalid-sample colors.
    """
    value = getattr(cmap, f"_{name}", None)
    if value is None:
        value = getattr(cmap, f"_rgba_{name}", None)
    if value is None:
        value = default
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2 and value[1] is None:
        value = value[0]
    return np.asarray(_rgba_floats(value), dtype=np.float64)


def _is_color_alpha_pair(value: object) -> TypeGuard[Sequence[Any]]:
    """(color, alpha) where color is a str or RGB(A) sequence — never a bare 2-tuple."""
    if not (isinstance(value, (tuple, list)) and len(value) == 2):
        return False
    color, alpha = value
    if alpha is not None and (
        not isinstance(alpha, numbers.Real) or isinstance(alpha, (bool, np.bool_))
    ):
        return False
    return isinstance(color, str) or (
        isinstance(color, (tuple, list, np.ndarray)) and len(color) in (3, 4)
    )


def resolve_color(value: object) -> Optional[str]:
    """A matplotlib color spec → CSS color string (None passes through)."""
    if value is None:
        return None
    if not isinstance(value, str):
        if _is_color_alpha_pair(value):
            rgba = _rgba_floats(value)
            return (
                f"rgba({round(rgba[0] * 255)},{round(rgba[1] * 255)},"
                f"{round(rgba[2] * 255)},{rgba[3]:g})"
            )
        # RGB(A) tuples in 0-1 floats.
        if isinstance(value, (tuple, list, np.ndarray)) and len(value) in (3, 4):
            channels = np.asarray(value, dtype=np.float64).reshape(-1).tolist()
            parts = [max(0, min(255, round(v * 255))) for v in channels[:3]]
            if len(channels) == 4:
                return f"rgba({parts[0]},{parts[1]},{parts[2]},{channels[3]:g})"
            return f"rgb({parts[0]},{parts[1]},{parts[2]})"
        raise ValueError(f"unsupported color spec: {value!r}")
    if len(value) == 2 and value[0] == "C" and value[1].isdigit():
        return PROP_CYCLE[int(value[1])]
    if value in _SINGLE_LETTER:
        return _SINGLE_LETTER[value]
    if value in _TAB:
        return _TAB[value]
    if value.lower() in _XKCD:
        return _XKCD[value.lower()]
    if value.lower() == "none":
        return "transparent"
    # matplotlib gray shorthand: a float in a string, "0.0" black - "1.0" white.
    try:
        gray = float(value)
    except ValueError:
        return value  # CSS name/hex/rgb() — engine validates
    level = max(0, min(255, round(gray * 255)))
    return f"rgb({level},{level},{level})"


def resolve_rgba(value: object) -> tuple[float, float, float, float]:
    """Resolve one Matplotlib color spec to canonical straight-alpha RGBA."""
    alpha: Optional[float] = None
    color = value
    if _is_color_alpha_pair(value):
        color, raw_alpha = value
        alpha = None if raw_alpha is None else float(raw_alpha)
    css = resolve_color(color)
    if css is None:
        css = "transparent"
    from xy import kernels

    status, parsed = kernels.css_check(kernels.CSS_COLOR, css)
    if status <= 0 or parsed is None:
        raise ValueError(f"color {value!r} cannot be resolved to static RGBA")
    red, green, blue, parsed_alpha = (float(channel) for channel in parsed)
    rgba = (red, green, blue, parsed_alpha if alpha is None else alpha)
    if not all(np.isfinite(rgba)) or any(channel < 0.0 or channel > 1.0 for channel in rgba):
        raise ValueError(f"RGBA channels must be finite and between 0 and 1, got {value!r}")
    return rgba


def is_color_like(value: object) -> bool:
    """Whether *value* is one complete color spec understood by pyplot."""
    if isinstance(value, str):
        try:
            gray = float(value)
        except ValueError:
            pass
        else:
            # Matplotlib gray-string colors are bounded to [0, 1]. Keeping
            # that check here is important for fmt strings: "2"/"3"/"4"/"8"
            # are marker tokens, not clamped grayscale colors.
            return bool(np.isfinite(gray) and 0.0 <= gray <= 1.0)
    try:
        resolve_rgba(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def resolve_rgba_array(values: object, n: int, label: str) -> np.ndarray:
    """Resolve one color or N color specs into an ``(N, 4)`` float array."""
    try:
        numeric = np.asarray(values)
    except (TypeError, ValueError):
        numeric = np.asarray(values, dtype=object)
    if (
        numeric.ndim == 2
        and numeric.shape in {(n, 3), (n, 4)}
        and np.issubdtype(numeric.dtype, np.number)
    ):
        rgba = np.asarray(numeric, dtype=np.float64)
        if rgba.shape[1] == 3:
            rgba = np.column_stack((rgba, np.ones(n, dtype=np.float64)))
        if not np.isfinite(rgba).all() or np.any((rgba < 0.0) | (rgba > 1.0)):
            raise ValueError(f"{label} RGBA channels must be finite and between 0 and 1")
        return np.ascontiguousarray(rgba)
    if (
        isinstance(values, str)
        or _is_color_alpha_pair(values)
        or (
            numeric.ndim == 1
            and numeric.shape in {(3,), (4,)}
            and np.issubdtype(numeric.dtype, np.number)
        )
    ):
        return np.tile(np.asarray(resolve_rgba(values), dtype=np.float64), (n, 1))
    sequence = list(cast("Iterable[Any]", values))
    if len(sequence) != n:
        raise ValueError(f"{label} sequence must have length {n}, got {len(sequence)}")
    return np.asarray([resolve_rgba(item) for item in sequence], dtype=np.float64)


def resolve_cmap(name: object) -> str:
    """A matplotlib cmap (name or object) → engine colormap name."""
    text = getattr(name, "name", name)
    if not isinstance(text, str):
        raise ValueError(f"unsupported colormap: {name!r}")
    key = text.lower()
    if key in CMAPS:
        return CMAPS[key]
    if key.endswith("_r") and key[:-2] in CMAPS:
        return f"{CMAPS[key[:-2]]}_r"
    raise ValueError(f"unsupported colormap: {text!r}")


class BoundaryNormGrid(NamedTuple):
    """Renderer-ready samples and discrete metadata for a BoundaryNorm."""

    rgba: np.ndarray
    domain: tuple[float, float]
    boundaries: np.ndarray
    band_colors: np.ndarray


def prepare_boundary_norm(
    values: object,
    norm: object,
    cmap: object,
    vmin: object = None,
    vmax: object = None,
) -> BoundaryNormGrid | None:
    """Bake a Matplotlib-like ``BoundaryNorm`` through its callable colormap.

    BoundaryNorm returns integer LUT indices, not normalized floats. Keeping
    that conversion here prevents ``imshow`` and ``pcolormesh`` from inventing
    different normalization rules, while the returned boundaries and exact
    per-band colors let every colorbar renderer reproduce the same discrete
    mapping.
    """

    if type(norm).__name__ != "BoundaryNorm":
        return None
    if not callable(norm):
        raise TypeError("BoundaryNorm must be callable")
    if vmin is not None or vmax is not None:
        raise ValueError(
            "Passing a Normalize instance simultaneously with vmin/vmax is not supported; "
            "set the bounds on the norm instance instead"
        )
    boundaries = np.asarray(getattr(norm, "boundaries", None), dtype=np.float64).reshape(-1)
    if (
        len(boundaries) < 2
        or not np.isfinite(boundaries).all()
        or np.any(np.diff(boundaries) <= 0.0)
    ):
        raise ValueError("BoundaryNorm boundaries must be finite and strictly increasing")

    source = np.ma.asarray(values, dtype=np.float64)
    raw = np.asarray(source.filled(np.nan), dtype=np.float64)
    norm_callable = cast(Callable[[Any], Any], norm)
    mapped = np.ma.asarray(norm_callable(source))
    cmap_callable: Callable[[Any], Any] = (
        cast(Callable[[Any], Any], cmap) if callable(cmap) else Cmap(resolve_cmap(cmap))
    )
    rgba = np.asarray(cmap_callable(mapped.filled(0)), dtype=np.float64)
    expected = raw.shape + (3,)
    if rgba.shape not in {expected, raw.shape + (4,)}:
        raise ValueError("BoundaryNorm colormap must return RGB or RGBA samples")
    if rgba.shape[-1] == 3:
        rgba = np.concatenate(
            (rgba, np.ones(raw.shape + (1,), dtype=np.float64)),
            axis=-1,
        )
    invalid = np.ma.getmaskarray(source) | np.ma.getmaskarray(mapped) | ~np.isfinite(raw)
    bad = cmap_extreme(cmap_callable, "bad", (0.0, 0.0, 0.0, 0.0))
    assert bad is not None
    rgba[invalid] = bad

    midpoints = (boundaries[:-1] + boundaries[1:]) * 0.5
    band_rgba = np.asarray(
        cmap_callable(np.ma.asarray(norm_callable(midpoints)).filled(0)), dtype=np.float64
    )
    if (
        band_rgba.ndim != 2
        or band_rgba.shape[0] != len(midpoints)
        or band_rgba.shape[1] not in (3, 4)
    ):
        raise ValueError("BoundaryNorm colormap must return one RGB(A) row per interval")
    band_colors = np.rint(np.clip(band_rgba[:, :3], 0.0, 1.0) * 255.0).astype(np.uint8)
    return BoundaryNormGrid(
        np.ascontiguousarray(rgba),
        (float(boundaries[0]), float(boundaries[-1])),
        boundaries,
        band_colors,
    )


def normalize_scalar_grid(
    values: object,
    norm: object,
    vmin: object = None,
    vmax: object = None,
) -> tuple[np.ndarray, tuple[float, float] | None, str]:
    """Resolve the bounded scalar-normalization contract shared by images.

    The core heatmap renderer owns linear normalization.  Non-linear pyplot
    norms are therefore reduced to normalized scalar samples here while the
    original value-domain and scale name remain available to the mappable and
    its colorbar.  This deliberately supports the two scale names Matplotlib
    uses throughout the in-scope gallery: ``"linear"`` and ``"log"``.

    Returns ``(render_values, original_domain, scale)``.  Invalid or masked
    log samples are NaN so the colormap's bad color can be applied uniformly
    by :func:`scalar_grid_rgba`.
    """

    source = np.ma.asarray(values, dtype=np.float64)
    raw = np.asarray(source.filled(np.nan), dtype=np.float64)
    norm_name = norm.lower() if isinstance(norm, str) else type(norm).__name__
    if norm is None or norm_name == "Normalize":
        norm_name = "linear"
    elif norm_name == "LogNorm":
        norm_name = "log"
    if norm_name not in {"linear", "log"}:
        if isinstance(norm, str):
            raise ValueError(f"{norm!r} is not a valid value for norm")
        raise NotImplementedError(
            f"xy.pyplot does not implement norm={type(norm).__name__}; "
            "use norm='linear', norm='log', or vmin=/vmax="
        )
    if norm is not None and not isinstance(norm, str) and (vmin is not None or vmax is not None):
        raise ValueError(
            "Passing a Normalize instance simultaneously with vmin/vmax is not supported; "
            "set the bounds on the norm instance instead"
        )

    norm_vmin = getattr(norm, "vmin", None)
    norm_vmax = getattr(norm, "vmax", None)
    lo_arg = norm_vmin if vmin is None else vmin
    hi_arg = norm_vmax if vmax is None else vmax
    finite = raw[np.isfinite(raw)]
    if norm_name == "linear":
        if lo_arg is None and hi_arg is None:
            return raw, None, "linear"
        lo = (
            scalar_float(lo_arg)
            if lo_arg is not None
            else (float(finite.min()) if finite.size else 0.0)
        )
        hi = (
            scalar_float(hi_arg)
            if hi_arg is not None
            else (float(finite.max()) if finite.size else 1.0)
        )
        if not np.isfinite([lo, hi]).all():
            raise ValueError("vmin and vmax must be finite")
        if hi < lo:
            raise ValueError("vmin must be less than or equal to vmax")
        return raw, (lo, hi), "linear"

    positive = finite[finite > 0.0]
    if not positive.size and (lo_arg is None or hi_arg is None):
        raise ValueError("log normalization requires at least one positive finite value")
    lo = scalar_float(lo_arg) if lo_arg is not None else float(positive.min())
    hi = scalar_float(hi_arg) if hi_arg is not None else float(positive.max())
    if not np.isfinite([lo, hi]).all() or lo <= 0.0 or hi <= 0.0:
        raise ValueError("Invalid vmin or vmax")
    if hi < lo:
        raise ValueError("vmin must be less than or equal to vmax")
    invalid = np.ma.getmaskarray(source) | ~np.isfinite(raw) | (raw <= 0.0)
    if hi == lo:
        normalized = np.zeros(raw.shape, dtype=np.float64)
    else:
        normalized = (np.log(raw, where=~invalid, out=np.zeros_like(raw)) - np.log(lo)) / (
            np.log(hi) - np.log(lo)
        )
    normalized[invalid] = np.nan
    return normalized, (lo, hi), "log"


def scalar_grid_rgba(values: object, cmap: object) -> np.ndarray:
    """Paint normalized scalar samples, including bad/under/over colors.

    ``values`` may contain samples outside ``[0, 1]``; those retain Matplotlib
    colormap under/over semantics.  NaN is the bad-color channel.  The result
    is truecolor RGBA so every renderer sees the same non-linear mapping.
    """

    from xy._svg import _lut

    normalized = np.asarray(values, dtype=np.float64)
    cmap_name = resolve_cmap(cmap)
    safe = np.clip(np.nan_to_num(normalized, nan=0.0), 0.0, 1.0)
    rgb = _lut(cmap_name, safe.reshape(-1)).reshape(normalized.shape + (3,))
    rgba = np.concatenate(
        (rgb / 255.0, np.ones(normalized.shape + (1,), dtype=np.float64)),
        axis=-1,
    )
    endpoints = _lut(cmap_name, np.asarray([0.0, 1.0], dtype=np.float64)) / 255.0
    under_default = (*endpoints[0], 1.0)
    over_default = (*endpoints[1], 1.0)

    under = cmap_extreme(cmap, "under", under_default)
    over = cmap_extreme(cmap, "over", over_default)
    bad = cmap_extreme(cmap, "bad", (0.0, 0.0, 0.0, 0.0))
    assert under is not None and over is not None and bad is not None
    rgba[normalized < 0.0] = under
    rgba[normalized > 1.0] = over
    rgba[~np.isfinite(normalized)] = bad
    return rgba
