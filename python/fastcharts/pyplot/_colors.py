"""matplotlib color vocabulary → CSS colors the engine accepts.

Covers the surfaces real scripts use: single-letter codes, the default
prop cycle (``C0``–``C9``), ``tab:*`` names, and gray shorthand ("0.5").
Everything else (CSS names, hex, rgb()) passes through — the engine
validates CSS colors natively.
"""

from __future__ import annotations

from typing import Optional

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
    "rdbu": "coolwarm",
    "rdbu_r": "coolwarm",
    "bwr": "coolwarm",
}


def resolve_color(value: object) -> Optional[str]:
    """A matplotlib color spec → CSS color string (None passes through)."""
    if value is None:
        return None
    if not isinstance(value, str):
        # RGB(A) tuples in 0-1 floats.
        if isinstance(value, (tuple, list)) and len(value) in (3, 4):
            channels = [float(v) for v in value]  # ty: ignore[invalid-argument-type]
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
    if key.endswith("_r") and key not in CMAPS:
        key = key[:-2]  # reversed variants render unreversed (documented)
    if key in CMAPS:
        return CMAPS[key]
    return "viridis"
