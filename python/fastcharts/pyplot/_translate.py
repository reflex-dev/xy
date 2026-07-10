"""matplotlib kwarg vocabulary → composition-API props.

One module owns every translation table so `_axes.py` stays readable and the
compat docs can be generated from a single source of truth.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ._colors import resolve_color

COMPAT_URL = "https://github.com/reflex-dev/reviz/blob/main/docs/matplotlib-compat.md"

LINESTYLE_TO_DASH = {
    "-": None,
    "solid": None,
    "--": "dashed",
    "dashed": "dashed",
    "-.": "dashdot",
    "dashdot": "dashdot",
    ":": "dotted",
    "dotted": "dotted",
    "": None,
    "none": "none",  # sentinel: marker-only plot
    "None": "none",
    " ": "none",
}

MARKER_TO_SYMBOL = {
    ".": "circle",
    ",": "circle",
    "o": "circle",
    "v": "triangle",
    "^": "triangle",
    "<": "triangle",
    ">": "triangle",
    "1": "triangle",
    "2": "triangle",
    "3": "triangle",
    "4": "triangle",
    "8": "circle",
    "s": "square",
    "p": "square",
    "P": "cross",
    "*": "diamond",
    "h": "circle",
    "H": "circle",
    "+": "cross",
    "x": "cross",
    "X": "cross",
    "D": "diamond",
    "d": "diamond",
    "|": "cross",
    "_": "cross",
}


def not_implemented(name: str, alternative: Optional[str] = None) -> "NotImplementedError":
    hint = f" Try {alternative} instead." if alternative else ""
    return NotImplementedError(
        f"fastcharts.pyplot does not implement {name}.{hint} "
        f"See the compatibility table: {COMPAT_URL}"
    )


def line_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Translate shared Line2D-ish kwargs; mutates kwargs by popping."""
    out: dict[str, Any] = {}
    color = kwargs.pop("color", kwargs.pop("c", None))
    if color is not None:
        out["color"] = resolve_color(color)
    width = kwargs.pop("linewidth", kwargs.pop("lw", None))
    if width is not None:
        out["width"] = float(width)
    alpha = kwargs.pop("alpha", None)
    if alpha is not None:
        out["opacity"] = float(alpha)
    ls = kwargs.pop("linestyle", kwargs.pop("ls", None))
    if ls is not None:
        if ls not in LINESTYLE_TO_DASH:
            raise ValueError(f"unsupported linestyle: {ls!r}")
        out["linestyle"] = ls
    label = kwargs.pop("label", None)
    if label is not None:
        out["name"] = str(label)
    return out


def marker_size_to_scatter_size(s: Any, default: float = 6.0) -> Any:
    """matplotlib sizes are areas in points²; the engine takes diameters in px.

    36 pt² (mpl default) ≈ 6 px diameter keeps default charts visually aligned.
    Arrays map element-wise so size encodings survive.
    """
    if s is None:
        return default
    arr = np.asarray(s, dtype=np.float64)
    out = np.sqrt(np.maximum(arr, 0.0))
    if out.ndim == 0:
        return float(out)
    return out


def check_unsupported(kwargs: dict[str, Any], where: str) -> None:
    """Anything left in kwargs is unsupported: fail loudly, never silently."""
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(
            f"fastcharts.pyplot {where} got unsupported keyword(s): {names}. "
            f"See the compatibility table: {COMPAT_URL}"
        )
