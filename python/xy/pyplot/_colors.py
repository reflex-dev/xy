"""matplotlib color vocabulary → CSS colors the engine accepts.

Covers the surfaces real scripts use: single-letter codes, the default
prop cycle (``C0``–``C9``), ``tab:*`` names, and gray shorthand ("0.5").
Everything else (CSS names, hex, rgb()) passes through — the engine
validates CSS colors natively.
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np

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

# matplotlib colormap names the engine knows (identity), plus common aliases.
CMAPS = {
    "viridis": "viridis",
    "plasma": "plasma",
    "inferno": "inferno",
    "magma": "magma",
    "cividis": "cividis",
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
        if resolved.lower() not in named:
            raise ValueError(
                f"colormap extremes require a CSS hex/rgb or basic named color, got {color!r}"
            )
        result = named[resolved.lower()]
    if isinstance(alpha, (int, float)):
        result = (result[0], result[1], result[2], float(alpha))
    return result


def _is_color_alpha_pair(value: object) -> bool:
    """(color, alpha) where color is a str or RGB(A) sequence — never a bare 2-tuple."""
    if not (isinstance(value, (tuple, list)) and len(value) == 2):
        return False
    color, alpha = value
    if alpha is not None and not isinstance(alpha, (int, float)):
        return False
    return isinstance(color, str) or (
        isinstance(color, (tuple, list, np.ndarray)) and len(color) in (3, 4)
    )


def resolve_color(value: object) -> Optional[str]:
    """A matplotlib color spec → CSS color string (None passes through)."""
    if value is None:
        return None
    if not isinstance(value, str):
        if isinstance(value, (tuple, list)) and len(value) == 2 and isinstance(value[0], str):
            return resolve_color(value[0])
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
    if value.lower() == "none":
        return "transparent"
    # matplotlib gray shorthand: a float in a string, "0.0" black - "1.0" white.
    try:
        gray = float(value)
    except ValueError:
        return value  # CSS name/hex/rgb() — engine validates
    level = max(0, min(255, round(gray * 255)))
    return f"rgb({level},{level},{level})"


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
