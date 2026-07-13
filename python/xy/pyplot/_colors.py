"""matplotlib color vocabulary → CSS colors the engine accepts.

Covers the surfaces real scripts use: single-letter codes, the default
prop cycle (``C0``–``C9``), ``tab:*`` names, and gray shorthand ("0.5").
Everything else (CSS names, hex, rgb()) passes through — the engine
validates CSS colors natively.
"""

from __future__ import annotations

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
    "rdbu": "coolwarm_r",
    "rdbu_r": "coolwarm",
    "bwr": "coolwarm",
    "blues": "blues",
    "rdylgn": "rdylgn",
    "rainbow": "rainbow",
    "spectral": "spectral",
    "piyg": "piyg",
    "purples": "purples",
    "pubu": "pubu",
    "prgn": "prgn",
    "binary": "binary",
}


class Cmap:
    """Small callable colormap carrier compatible with common pyplot scripts."""

    def __init__(self, name: str) -> None:
        self.name = resolve_cmap(name)
        self.N = 256

    def resampled(self, lutsize: int) -> "Cmap":
        result = Cmap(self.name)
        result.N = max(1, int(lutsize))
        return result

    def with_extremes(self, **kwargs: object) -> "Cmap":
        result = Cmap(self.name)
        result.N = self.N
        for key in ("bad", "under", "over"):
            if key in kwargs:
                setattr(result, f"_{key}", kwargs[key])
        return result

    def set_bad(self, color: object = "transparent", alpha: object = None) -> None:
        self._bad = (color, alpha)

    def set_under(self, color: object = "transparent", alpha: object = None) -> None:
        self._under = (color, alpha)

    def set_over(self, color: object = "transparent", alpha: object = None) -> None:
        self._over = (color, alpha)

    def __call__(self, values: object) -> object:
        from xy._svg import _lut

        array = np.asarray(values, dtype=np.float64)
        normalized = array
        if np.issubdtype(array.dtype, np.integer) or (
            np.isfinite(array).any() and np.nanmax(np.abs(array)) > 1.0
        ):
            normalized = array / max(1, self.N - 1)
        flat = _lut(self.name, normalized.reshape(-1)) / 255.0
        rgba = np.column_stack((flat, np.ones(len(flat), dtype=np.float64))).reshape(
            array.shape + (4,)
        )
        return tuple(rgba.tolist()) if array.ndim == 0 else rgba


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
    return "viridis"
