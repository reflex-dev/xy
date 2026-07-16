"""matplotlib kwarg vocabulary → composition-API props.

One module owns every translation table so `_axes.py` stays readable and the
compat docs can be generated from a single source of truth.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ._colors import resolve_color

COMPAT_URL = "https://github.com/reflex-dev/xy/blob/main/docs/engineering/matplotlib-compat.md"

# Matplotlib's unscaled named dash patterns, in points (rcParams
# lines.{dashed,dotted,dashdot}_pattern). Matplotlib multiplies these by the
# line width (lines.scale_dashes) and then by the figure DPI; the shim does the
# same so "--"/":"/"-." read like Matplotlib instead of the denser, shorter
# CSS presets used by the public composition API.
MPL_DASH_PATTERN = {
    "dashed": (3.7, 1.6),
    "dotted": (1.0, 1.65),
    "dashdot": (6.4, 1.6, 1.0, 1.6),
}

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
    ".": "point",
    ",": "pixel",
    "o": "circle",
    "v": "triangle_down",
    "^": "triangle",
    "<": "triangle_left",
    ">": "triangle_right",
    "1": "triangle_down",
    "2": "triangle",
    "3": "triangle_left",
    "4": "triangle_right",
    "8": "circle",
    "s": "square",
    "p": "pentagon",
    "P": "cross",
    "*": "star",
    "h": "hexagon",
    "H": "hexagon",
    "+": "plus_line",
    "x": "x_line",
    "X": "x",
    "D": "diamond",
    "d": "thin_diamond",
    "|": "cross",
    "_": "cross",
}


def not_implemented(name: str, alternative: Optional[str] = None) -> "NotImplementedError":
    hint = f" Try {alternative} instead." if alternative else ""
    return NotImplementedError(
        f"xy.pyplot does not implement {name}.{hint} See the compatibility table: {COMPAT_URL}"
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
        if isinstance(ls, tuple) and len(ls) == 2:
            out["dash"] = list(ls[1])
        else:
            if ls not in LINESTYLE_TO_DASH:
                raise ValueError(f"unsupported linestyle: {ls!r}")
            out["linestyle"] = ls
    dashes = kwargs.pop("dashes", None)
    if dashes is not None:
        out["dash"] = list(dashes)
    gapcolor = kwargs.pop("gapcolor", None)
    if gapcolor is not None:
        raise not_implemented("Line2D gapcolor")
    path_effects = kwargs.pop("path_effects", None)
    if path_effects:
        raise not_implemented("Line2D path_effects")
    label = kwargs.pop("label", None)
    if label is not None:
        out["name"] = str(label)
    return out


def marker_size_to_scatter_size(
    s: Any, default: float = 6.0, *, point_scale: float = 4.0 / 3.0
) -> Any:
    """matplotlib sizes are areas in points²; the engine takes diameters in px.

    36 pt² (mpl default) ≈ 6 px diameter keeps default charts visually aligned.
    Arrays map element-wise so size encodings survive.
    """
    if s is None:
        return default
    arr = np.asarray(s, dtype=np.float64)
    out = np.sqrt(np.maximum(arr, 0.0)) * float(point_scale)
    if out.ndim == 0:
        return float(out)
    return out


def check_unsupported(kwargs: dict[str, Any], where: str) -> None:
    """Anything left in kwargs is unsupported: fail loudly, never silently."""
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(
            f"xy.pyplot {where} got unsupported keyword(s): {names}. "
            f"See the compatibility table: {COMPAT_URL}"
        )
