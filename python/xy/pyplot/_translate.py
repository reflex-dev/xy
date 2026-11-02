"""matplotlib kwarg vocabulary → composition-API props.

One module owns every translation table so `_axes.py` stays readable and the
compat docs can be generated from a single source of truth.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ._colors import resolve_color

COMPAT_URL = "https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/compat.md"
SUPPORT_REQUEST_URL = "https://github.com/reflex-dev/xy/issues"

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
    "|": "vertical_line",
    "_": "horizontal_line",
}


def not_implemented(name: str, alternative: Optional[str] = None) -> "NotImplementedError":
    hint = f" Try {alternative} instead." if alternative else ""
    return NotImplementedError(
        f"xy.pyplot does not implement {name}.{hint} See the compatibility table: {COMPAT_URL}. "
        f"Request support: {SUPPORT_REQUEST_URL}"
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
        # Kept private to the pyplot entry.  Materialization draws a solid
        # underlay before the dashed foreground, reproducing Matplotlib's
        # alternating gap paint without expanding the public mark protocol.
        out["_gapcolor"] = resolve_color(gapcolor)
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


# Matplotlib ``Artist``-level keywords every plotting call accepts but that
# have no engine equivalent: draw-order overrides, clipping/rasterization
# policy, hit-testing metadata, and renderer filters. They are accepted and
# ignored (documented compat-noops in spec/matplotlib/compat.md) instead of
# raising ``TypeError`` on scripts that carry them for the real renderer.
# ``visible=False`` is *not* in this set: the entry point hides the artist.
ARTIST_NOOP_KWARGS = frozenset(
    {
        "zorder",
        "clip_on",
        "clip_box",
        "rasterized",
        "antialiased",
        "aa",
        "snap",
        "gid",
        "url",
        "picker",
        "pickradius",
        "in_layout",
        "agg_filter",
        "sketch_params",
        "path_effects",
        "mouseover",
        "animated",
    }
)

# Axes entry points that take the Artist-level keywords above. Every method in
# the Matplotlib 3.11 Plotting inventory plus the chrome setters scripts pass
# ``zorder=``/``clip_on=`` to. ``annotate`` and ``clabel`` honor ``zorder``
# themselves and keep it (see the ``keep`` table below).
ARTIST_KWARG_METHODS = (
    "acorr",
    "angle_spectrum",
    "annotate",
    "arrow",
    "axhline",
    "axhspan",
    "axline",
    "axvline",
    "axvspan",
    "bar",
    "bar_label",
    "barbs",
    "barh",
    "boxplot",
    "broken_barh",
    "bxp",
    "clabel",
    "cohere",
    "contour",
    "contourf",
    "csd",
    "ecdf",
    "errorbar",
    "eventplot",
    "fill",
    "fill_between",
    "fill_betweenx",
    "grouped_bar",
    "hexbin",
    "hist",
    "hist2d",
    "hlines",
    "imshow",
    "loglog",
    "magnitude_spectrum",
    "matshow",
    "pcolor",
    "pcolorfast",
    "pcolormesh",
    "phase_spectrum",
    "pie",
    "pie_label",
    "plot",
    "psd",
    "quiver",
    "quiverkey",
    "scatter",
    "semilogx",
    "semilogy",
    "specgram",
    "spy",
    "stackplot",
    "stairs",
    "stem",
    "step",
    "streamplot",
    "table",
    "text",
    "tricontour",
    "tricontourf",
    "tripcolor",
    "triplot",
    "violin",
    "violinplot",
    "vlines",
    "xcorr",
    "set_title",
    "set_xlabel",
    "set_ylabel",
)

# Methods that implement one of the no-op names themselves and must see it:
# annotate/clabel order their text by ``zorder``, the mesh family records
# ``rasterized`` on its handle (``get_rasterized()``), and imshow honors
# ``clip_on`` for images.
ARTIST_KWARG_KEEP: dict[str, frozenset[str]] = {
    "annotate": frozenset({"zorder"}),
    "clabel": frozenset({"zorder"}),
    "pcolormesh": frozenset({"rasterized"}),
    "pcolor": frozenset({"rasterized"}),
    "pcolorfast": frozenset({"rasterized"}),
    "imshow": frozenset({"clip_on"}),
    "matshow": frozenset({"clip_on"}),
    # Chrome setters return no artist to hide, so they apply ``visible``
    # to the stored title/label state themselves.
    "set_title": frozenset({"visible"}),
    "set_xlabel": frozenset({"visible"}),
    "set_ylabel": frozenset({"visible"}),
}


def strip_artist_noops(kwargs: dict[str, Any], keep: frozenset[str] = frozenset()) -> bool:
    """Drop the accepted-and-ignored Artist keywords; return the ``visible`` flag.

    Mutates ``kwargs``. ``visible`` is popped too because the entry points
    apply it to the artists they return (``set_visible(False)``) rather than
    ignoring it; ``visible=True`` is Matplotlib's default and a no-op.
    """
    for name in ARTIST_NOOP_KWARGS:
        if name in kwargs and name not in keep:
            kwargs.pop(name)  # compat-noop: no engine equivalent (see ARTIST_NOOP_KWARGS)
    if "visible" in keep:
        return True  # the method applies ``visible`` to its own state
    visible = kwargs.pop("visible", True)
    return True if visible is None else bool(visible)


def check_unsupported(kwargs: dict[str, Any], where: str) -> None:
    """Anything left in kwargs is unsupported: fail loudly, never silently."""
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(
            f"xy.pyplot {where} got unsupported keyword(s): {names}. "
            f"See the compatibility table: {COMPAT_URL}. "
            f"Request support: {SUPPORT_REQUEST_URL}"
        )
