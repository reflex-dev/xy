"""xy.pyplot — a matplotlib-flavored shim over the composition API.

    import xy.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot(x, y, "r--o", label="trend")
    ax.legend()
    plt.savefig("chart.png")

Every call translates onto the public declarative API (`xy.chart`
and friends); the engine never knows this module exists. Coverage is
corpus-defined — see docs/matplotlib-compat.md for the supported surface
and the loud `NotImplementedError` list.
"""

from __future__ import annotations

import contextlib
from typing import Any, Optional, Union

import numpy as np

from . import dates
from ._artists import (
    Artist,
    AxesImage,
    BarContainer,
    ContourSet,
    ErrorbarContainer,
    GroupedBarReturn,
    Legend,
    Line2D,
    PathCollection,
    PieContainer,
    PolyCollection,
    StemContainer,
    StepPatch,
    StreamplotSet,
    Table,
    Text,
)
from ._axes import Axes
from ._axisgrid import FacetGrid
from ._colors import LinearSegmentedColormap, ListedColormap
from ._mplfig import Figure, GridSpec
from ._rc import _PropCycle, rc, rc_context, rcdefaults, rcParams
from ._state import all_figures, close, figlabels, fignum_exists, fignums, figure, gca, gcf, sca
from ._ticker import (
    AutoLocator,
    FixedFormatter,
    FixedLocator,
    FormatStrFormatter,
    FuncFormatter,
    LinearLocator,
    LogLocator,
    MaxNLocator,
    MultipleLocator,
    NullFormatter,
    NullLocator,
    ScalarFormatter,
    StrMethodFormatter,
)
from ._translate import not_implemented

__all__ = [
    "AutoLocator",
    "Axes",
    "FacetGrid",
    "Figure",
    "FixedFormatter",
    "FixedLocator",
    "FormatStrFormatter",
    "FuncFormatter",
    "GridSpec",
    "Legend",
    "LinearLocator",
    "LinearSegmentedColormap",
    "ListedColormap",
    "LogLocator",
    "MaxNLocator",
    "MultipleLocator",
    "NullFormatter",
    "NullLocator",
    "ScalarFormatter",
    "StrMethodFormatter",
    "acorr",
    "angle_spectrum",
    "annotate",
    "arrow",
    "autoscale",
    "autoscale_view",
    "axes",
    "axhline",
    "axhspan",
    "axis",
    "axline",
    "axvline",
    "axvspan",
    "bar",
    "bar_label",
    "barbs",
    "barh",
    "box",
    "boxplot",
    "broken_barh",
    "bxp",
    "cla",
    "clabel",
    "clf",
    "clim",
    "close",
    "cm",
    "cohere",
    "colorbar",
    "colormaps",
    "contour",
    "contourf",
    "csd",
    "cycler",
    "dates",
    "delaxes",
    "ecdf",
    "errorbar",
    "eventplot",
    "figlegend",
    "fignum_exists",
    "figtext",
    "figure",
    "fill",
    "fill_between",
    "fill_betweenx",
    "findobj",
    "gca",
    "gcf",
    "gci",
    "get",
    "get_cmap",
    "get_figlabels",
    "get_fignums",
    "get_xbound",
    "get_ybound",
    "getp",
    "gray",
    "grid",
    "grouped_bar",
    "hexbin",
    "hist",
    "hist2d",
    "hlines",
    "imread",
    "imsave",
    "imshow",
    "legend",
    "loglog",
    "magnitude_spectrum",
    "matshow",
    "minorticks_off",
    "minorticks_on",
    "pcolor",
    "pcolorfast",
    "pcolormesh",
    "phase_spectrum",
    "pie",
    "pie_label",
    "plasma",
    "plot",
    "psd",
    "quiver",
    "quiverkey",
    "rc",
    "rcParams",
    "rc_context",
    "rcdefaults",
    "relim",
    "savefig",
    "sca",
    "scatter",
    "sci",
    "semilogx",
    "semilogy",
    "set_cmap",
    "set_xbound",
    "set_ybound",
    "setp",
    "show",
    "specgram",
    "spy",
    "stackplot",
    "stairs",
    "stem",
    "step",
    "streamplot",
    "style",
    "subplot",
    "subplot2grid",
    "subplot_mosaic",
    "subplots",
    "subplots_adjust",
    "suptitle",
    "table",
    "text",
    "ticklabel_format",
    "tight_layout",
    "title",
    "tricontour",
    "tricontourf",
    "tripcolor",
    "triplot",
    "twinx",
    "twiny",
    "violin",
    "violinplot",
    "viridis",
    "vlines",
    "xcorr",
    "xlabel",
    "xlim",
    "xscale",
    "xticks",
    "ylabel",
    "ylim",
    "yscale",
    "yticks",
]

# -- figure/axes management ----------------------------------------------------


def subplots(
    nrows: int = 1,
    ncols: int = 1,
    *,
    figsize: Optional[tuple[float, float]] = None,
    dpi: Optional[float] = None,
    sharex: bool = False,
    sharey: bool = False,
    squeeze: bool = True,
    **kwargs: Any,
) -> tuple[Figure, Any]:
    """Create a figure with a grid of axes.

    Parameters
    ----------
    nrows, ncols : int, default 1
        Grid shape.
    figsize : (float, float), optional
        Figure size in inches.
    dpi : float, optional
        Dots per inch (drives the pixel size of the canvas).
    sharex, sharey : bool, default False
        Link the x/y limits across the grid.
    squeeze : bool, default True
        Return a bare `Axes` for a 1×1 grid and a 1-D array for a single
        row/column instead of a 2-D array.
    width_ratios, height_ratios : sequence of float, optional
        Relative column widths / row heights (also accepted inside
        ``gridspec_kw``).
    subplot_kw : dict, optional
        Properties applied to every created axes via ``Axes.set``.
    **kwargs
        Remaining keywords are forwarded to `figure` (e.g.
        ``facecolor``, ``toolbar``).

    Returns
    -------
    (Figure, Axes or ndarray of Axes)
    """
    width_ratios = kwargs.pop("width_ratios", None)
    height_ratios = kwargs.pop("height_ratios", None)
    gridspec_kw = kwargs.pop("gridspec_kw", None) or {}
    subplot_kw = kwargs.pop("subplot_kw", None) or {}
    toolbar = kwargs.pop("toolbar", None)
    # Remaining kwargs are matplotlib's **fig_kw, forwarded to figure().
    fig = figure(figsize=figsize, dpi=dpi, toolbar=toolbar, **kwargs)
    if fig._axes and any(ax._entries for ax in fig._axes):
        # fresh figure, mpl semantics
        fig = figure(None, figsize=figsize, dpi=dpi, toolbar=toolbar, **kwargs)
    axes = fig.subplots(
        nrows,
        ncols,
        sharex=sharex,
        sharey=sharey,
        squeeze=squeeze,
        width_ratios=width_ratios,
        height_ratios=height_ratios,
        gridspec_kw=gridspec_kw,
    )
    if subplot_kw:
        for ax in np.atleast_1d(np.asarray(axes, dtype=object)).ravel():
            ax.set(**subplot_kw)
    return fig, axes


def subplot(*args: Any, **kwargs: Any) -> Axes:
    """Add or activate a subplot on the current figure.

    Accepts matplotlib's forms: ``subplot(nrows, ncols, index)`` or the
    packed ``subplot(211)`` shorthand. Returns the (new or existing)
    `Axes` and makes it current.
    """
    return gcf().add_subplot(*args, **kwargs)


def subplot_mosaic(mosaic: Any, **kwargs: Any) -> tuple[Figure, dict[Any, Axes]]:
    """Create a figure whose layout is described by an ASCII/list mosaic.

    ``mosaic`` is a string like ``"AB;CC"`` or a nested list of labels;
    the result maps each label to its `Axes`. ``figsize``/``dpi`` size
    the figure; other keywords go to ``Figure.subplot_mosaic``.
    """
    figsize = kwargs.pop("figsize", None)
    dpi = kwargs.pop("dpi", None)
    fig = figure(None, figsize=figsize, dpi=dpi)
    return fig, fig.subplot_mosaic(mosaic, **kwargs)


def axes(arg: Any = None, **kwargs: Any) -> Axes:
    """Add an axes to the current figure and make it current.

    ``axes()`` adds a full-figure axes; ``axes((left, bottom, width,
    height))`` places one at the given figure-fraction rectangle.
    Keywords are applied via ``Axes.set``.
    """
    if arg is None:
        ax = gcf().add_subplot(111)
        if kwargs:
            ax.set(**kwargs)
        return ax
    return gcf().add_axes(arg, **kwargs)


def delaxes(ax: Optional[Axes] = None) -> None:
    """Remove an axes (the current one by default) from the current figure."""
    gcf().delaxes(ax or gca())


def cla() -> None:
    """Clear the current axes."""
    gca().cla()


def clf() -> None:
    """Clear the current figure."""
    gcf().clf()


def get_fignums() -> list[int]:
    """The numbers of all open figures, sorted."""
    return fignums()


def get_figlabels() -> list[str]:
    """The labels of all open figures that were created with a string num."""
    return figlabels()


def figtext(x: float, y: float, s: str, **kwargs: Any) -> Any:
    """Place text at figure-fraction coordinates ``(x, y)`` (see `text`)."""
    return gcf().text(x, y, s, **kwargs)


def figlegend(*args: Any, **kwargs: Any) -> Any:
    """Add a figure-level legend (same call forms and keywords as `legend`)."""
    return gcf().legend(*args, **kwargs)


def twinx() -> Axes:
    """A twin of the current axes sharing x but with its own right y-axis."""
    return gca().twinx()


def twiny() -> Axes:
    """A twin of the current axes sharing y but with its own top x-axis."""
    return gca().twiny()


def subplot2grid(
    shape: tuple[int, int],
    loc: tuple[int, int],
    rowspan: int = 1,
    colspan: int = 1,
    fig: Optional[Figure] = None,
    **kwargs: Any,
) -> Axes:
    """Place an axes at cell ``loc`` of a ``shape`` grid on the figure.

    Only single-cell placement is supported; ``rowspan``/``colspan``
    other than 1 raise loudly.
    """
    if rowspan != 1 or colspan != 1:
        raise not_implemented("subplot2grid(rowspan/colspan)", "single-cell subplot2grid specs")
    target = fig or gcf()
    target._ensure_grid(int(shape[0]), int(shape[1]))
    ax = target._axes_at(int(loc[0]) * int(shape[1]) + int(loc[1]))
    target._current_ax = ax
    return ax


def box(on: Optional[bool] = None) -> None:
    """Show or hide the current axes' frame box (toggle when ``on=None``)."""
    ax = gca()
    ax._box = True if on is None else bool(on)
    ax._invalidate()


def setp(obj: Any, *args: Any, **kwargs: Any) -> None:
    """Set properties on an artist (or list of artists) via ``set_*`` methods.

    Accepts keyword form ``setp(lines, linewidth=2)`` or matplotlib's
    positional property/value pairs ``setp(lines, "linewidth", 2)``.
    """
    if args:
        if len(args) % 2:
            raise ValueError("setp positional arguments must be property/value pairs")
        kwargs.update(dict(zip(args[0::2], args[1::2], strict=True)))
    targets = obj if isinstance(obj, (list, tuple)) else [obj]
    for target in targets:
        for name, value in kwargs.items():
            setter = getattr(target, f"set_{name}", None)
            if setter is None:
                raise AttributeError(f"object has no set_{name}()")
            setter(value)


def getp(obj: Any, property: Optional[str] = None) -> Any:
    """Read an artist property via its ``get_*`` method.

    With no ``property``, returns a dict of every readable property.
    """
    if property is None:
        return {
            name[4:]: method()
            for name, method in ((n, getattr(obj, n)) for n in dir(obj) if n.startswith("get_"))
            if callable(method)
        }
    getter = getattr(obj, f"get_{property}", None)
    if getter is None:
        raise AttributeError(f"object has no get_{property}()")
    return getter()


def get(obj: Any, property: Optional[str] = None) -> Any:
    """Alias of `getp`."""
    return getp(obj, property)


def findobj(obj: Any = None, match: Any = None) -> list[Any]:
    """Collect axes and artists under ``obj`` (default: the current figure).

    ``match`` is an optional predicate applied to each candidate.
    """
    root = obj or gcf()
    found: list[Any] = []
    axes = getattr(root, "axes", []) if not isinstance(root, Axes) else [root]
    for ax in axes:
        if match is None or match(ax):
            found.append(ax)
        for entry in getattr(ax, "_entries", []):
            artist = getattr(entry, "_artist", None)
            if artist is not None and (match is None or match(artist)):
                found.append(artist)
    return found


def set_cmap(cmap: Any) -> None:
    """Set the default colormap (``rcParams["image.cmap"]``) by name."""
    from ._colors import resolve_cmap

    name = str(getattr(cmap, "name", cmap))
    resolve_cmap(name)  # unknown names must fail here, not at render time
    rcParams["image.cmap"] = name


def viridis() -> Any:
    """Set the default colormap to viridis and return it."""
    set_cmap("viridis")
    return get_cmap("viridis")


def plasma() -> Any:
    """Set the default colormap to plasma and return it."""
    set_cmap("plasma")
    return get_cmap("plasma")


def gray() -> Any:
    """Set the default colormap to gray and return it."""
    set_cmap("gray")
    return get_cmap("gray")


def imsave(fname: Any, arr: Any, **kwargs: Any) -> None:
    """Save an array as a PNG image file, without drawing a figure.

    ``arr`` is 2-D scalar data (colormapped via ``cmap``) or an
    ``(M, N, 3|4)`` RGB(A) array; ``fname`` is a path or binary
    file-like. JPEG output is not supported in the dependency-free shim.
    """
    format_name = str(kwargs.pop("format", "")).lower()
    cmap = kwargs.pop("cmap", None)
    if kwargs:
        raise TypeError(f"imsave() got unsupported keyword argument {next(iter(kwargs))!r}")
    path = str(fname)
    if format_name in {"jpg", "jpeg"} or path.lower().endswith((".jpg", ".jpeg")):
        raise not_implemented(
            "imsave(JPEG)", "PNG output; JPEG remains outside the dependency-free shim"
        )
    image = np.asarray(arr)
    if image.ndim == 2:
        from ._colors import Cmap

        # Colormap the original values: quantizing to uint8 first would
        # collapse any range outside [0, 255] to a handful of colors.
        scalar = image.astype(np.float64)
        finite = scalar[np.isfinite(scalar)]
        lo = float(finite.min()) if finite.size else 0.0
        hi = float(finite.max()) if finite.size else 1.0
        normalized = (scalar - lo) / (hi - lo) if hi > lo else np.zeros_like(scalar)
        rgba = Cmap(cmap if cmap is not None else rcParams["image.cmap"])(normalized)
        image = np.round(np.asarray(rgba, dtype=np.float64) * 255.0).astype(np.uint8)
    else:
        # cmap is ignored for RGB(A) input, matching matplotlib.
        if image.dtype != np.uint8:
            finite = image.astype(float)
            if finite.size and np.nanmax(finite) <= 1.0 and np.nanmin(finite) >= 0.0:
                image = np.clip(finite * 255.0, 0, 255).astype(np.uint8)
            else:
                image = np.clip(finite, 0, 255).astype(np.uint8)
        if image.ndim == 3 and image.shape[2] == 3:
            alpha = np.full((*image.shape[:2], 1), 255, dtype=np.uint8)
            image = np.concatenate((image, alpha), axis=2)
        elif image.ndim != 3 or image.shape[2] != 4:
            raise ValueError("imsave() expects a 2-D grayscale, RGB, or RGBA array")
    from xy._png import encode

    data = encode(np.ascontiguousarray(image, dtype=np.uint8))
    if hasattr(fname, "write"):
        fname.write(data)
    else:
        from pathlib import Path

        Path(fname).write_bytes(data)


def imread(fname: Any, **kwargs: Any) -> np.ndarray:
    """Read an 8-bit PNG file into an ``(M, N, 4)`` RGBA uint8 array.

    ``fname`` is a path or binary file-like. Only PNG is supported in
    the dependency-free shim; JPEG raises loudly.
    """
    if kwargs:
        raise TypeError(f"imread() got unsupported keyword argument {next(iter(kwargs))!r}")
    data = (
        fname.read() if hasattr(fname, "read") else __import__("pathlib").Path(fname).read_bytes()
    )
    if data[:2] == b"\xff\xd8":
        raise not_implemented(
            "imread(JPEG)", "PNG input; JPEG remains outside the dependency-free shim"
        )
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("imread() only supports PNG files in the dependency-free shim")
    import struct
    import zlib

    position = 8
    width = height = color_type = None
    palette = b""
    transparency = b""
    idat = bytearray()
    while position + 8 <= len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        chunk = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _compression, _filter, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if depth != 8 or interlace != 0:
                raise ValueError("imread() supports only 8-bit non-interlaced PNG files")
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            transparency = chunk
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
    if width is None or height is None or color_type is None:
        raise ValueError("invalid PNG file")
    channels = {0: 1, 2: 3, 3: 1, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError("imread() supports grayscale, RGB, indexed, and RGBA PNG files")
    row_length = width * channels
    raw = zlib.decompress(bytes(idat))
    previous = bytearray(row_length)
    decoded = bytearray(width * height * 4)
    source = destination = 0
    for _row_index in range(height):
        filter_kind = raw[source]
        source += 1
        row = bytearray(raw[source : source + row_length])
        source += row_length
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_kind == 1:
                row[index] = (value + left) & 0xFF
            elif filter_kind == 2:
                row[index] = (value + up) & 0xFF
            elif filter_kind == 3:
                row[index] = (value + ((left + up) >> 1)) & 0xFF
            elif filter_kind == 4:
                predictor = left + up - up_left
                distances = (abs(predictor - left), abs(predictor - up), abs(predictor - up_left))
                row[index] = (value + (left, up, up_left)[distances.index(min(distances))]) & 0xFF
            elif filter_kind != 0:
                raise ValueError(f"unsupported PNG filter {filter_kind}")
        for column in range(width):
            if color_type == 6:
                rgba = row[column * 4 : column * 4 + 4]
            elif color_type == 2:
                rgba = row[column * 3 : column * 3 + 3] + b"\xff"
            elif color_type == 0:
                gray_value = row[column]
                rgba = bytes((gray_value, gray_value, gray_value, 255))
            else:
                palette_index = row[column]
                base = palette_index * 3
                alpha = transparency[palette_index] if palette_index < len(transparency) else 255
                rgba = palette[base : base + 3] + bytes((alpha,))
            decoded[destination : destination + 4] = rgba
            destination += 4
        previous = row
    return np.frombuffer(decoded, dtype=np.uint8).reshape(height, width, 4)


# -- pyplot function surface: delegate to the current axes ----------------------
#
# Every function below is an explicit wrapper over the matching `Axes` method
# (matplotlib generates its pyplot the same way, see boilerplate.py) so IDE
# hover and help() show the real supported signature instead of *args/**kwargs.
# Wrappers whose Axes method takes open **kwargs name the supported keywords
# and forward only the ones the caller supplied via `_given`, so kwarg-alias
# resolution (`lw`/`linewidth`, `ha`/`horizontalalignment`, rc-driven
# defaults) inside the Axes method keeps working unchanged.


def _given(**named: Any) -> dict[str, Any]:
    """The subset of named keyword arguments the caller actually supplied."""
    return {key: value for key, value in named.items() if value is not None}


def _record_mappable(result: Any) -> Any:
    """Track a freshly created color-mapped artist as the figure's current
    image (pyplot's sci() bookkeeping) so colorbar()/clim() find it."""
    candidate = result[-1] if isinstance(result, tuple) else result
    if hasattr(candidate, "_entry"):
        gcf()._gci = candidate
    return result


def plot(
    *args: Any,
    scalex: bool = True,
    scaley: bool = True,
    **kwargs: Any,
) -> list[Line2D]:
    """Plot y versus x as lines and/or markers on the current axes.

    Accepts matplotlib's call forms: ``plot(y)``, ``plot(x, y)``,
    ``plot(x, y, fmt)``, and repeated ``x, y, fmt`` groups, where ``fmt``
    is a ``[marker][line][color]`` shorthand such as ``"r--o"``. A 2-D
    operand draws one line per column.

    Supported keywords: ``color``/``c``, ``linewidth``/``lw``,
    ``linestyle``/``ls``, ``dashes``, ``alpha``, ``label``, ``zorder``,
    ``marker``, ``markersize``/``ms``, ``markerfacecolor``/``mfc``,
    ``markeredgecolor``/``mec``, ``markeredgewidth``/``mew``,
    ``markevery``, ``drawstyle``, and ``transform``. Anything else
    raises a loud error (see docs/matplotlib-compat.md).

    Returns the list of `Line2D` handles, one per plotted series.
    """
    return gca().plot(*args, scalex=scalex, scaley=scaley, **kwargs)


def semilogx(*args: Any, **kwargs: Any) -> list[Line2D]:
    """Like `plot`, but sets the x-axis to log scale first.

    Accepts ``base``/``basex``, ``subs``/``subsx``, and
    ``nonpositive``/``nonposx`` in addition to every `plot` keyword.
    """
    return gca().semilogx(*args, **kwargs)


def semilogy(*args: Any, **kwargs: Any) -> list[Line2D]:
    """Like `plot`, but sets the y-axis to log scale first.

    Accepts ``base``/``basey``, ``subs``/``subsy``, and
    ``nonpositive``/``nonposy`` in addition to every `plot` keyword.
    """
    return gca().semilogy(*args, **kwargs)


def loglog(*args: Any, **kwargs: Any) -> list[Line2D]:
    """Like `plot`, but sets both axes to log scale first.

    Accepts ``base``, ``subs``, and ``nonpositive`` in addition to every
    `plot` keyword.
    """
    return gca().loglog(*args, **kwargs)


def scatter(
    x: Any,
    y: Any,
    s: Any = None,
    c: Any = None,
    *,
    marker: Optional[str] = None,
    cmap: Any = None,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    alpha: Optional[float] = None,
    linewidths: Any = None,
    edgecolors: Any = None,
    plotnonfinite: bool = False,
    label: Optional[str] = None,
    transform: Any = None,
    **kwargs: Any,
) -> PathCollection:
    """A scatter plot of ``y`` versus ``x`` on the current axes.

    Parameters
    ----------
    x, y : array-like
        Point positions. Masked entries are dropped, matching matplotlib.
    s : float or array-like, optional
        Marker area in points² (scalar or per point).
    c : color or array-like, optional
        A single color, one color per point, or a numeric array mapped
        through ``cmap`` (use ``vmin``/``vmax`` to pin the color limits).
    marker : str, optional
        Marker symbol (e.g. ``"o"``, ``"s"``, ``"^"``).
    alpha : float, optional
        Marker opacity in [0, 1].
    linewidths, edgecolors : float / color, optional
        Marker outline width and color (``linewidth``/``lw`` and
        ``edgecolor`` aliases are accepted).
    plotnonfinite : bool, default False
        Keep non-finite points instead of dropping them.
    label : str, optional
        Legend entry for this series.

    The result becomes the figure's current mappable, so a bare
    `colorbar()` attaches to it. ``norm`` is not supported and raises.

    Returns
    -------
    PathCollection
    """
    return _record_mappable(
        gca().scatter(
            x,
            y,
            s,
            c,
            plotnonfinite=plotnonfinite,
            **_given(
                marker=marker,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                alpha=alpha,
                linewidths=linewidths,
                edgecolors=edgecolors,
                label=label,
                transform=transform,
            ),
            **kwargs,
        )
    )


def step(x: Any, y: Any, *args: Any, where: str = "pre", **kwargs: Any) -> list[Line2D]:
    """A step plot: `plot` with the line drawn as steps.

    ``where`` places the step transition at ``"pre"``, ``"post"``, or
    ``"mid"``; remaining arguments (including an optional ``fmt`` string)
    behave exactly like `plot`.
    """
    return gca().step(x, y, *args, where=where, **kwargs)


def bar(
    x: Any,
    height: Any,
    width: float = 0.8,
    bottom: Any = None,
    *,
    color: Any = None,
    edgecolor: Any = None,
    linewidth: Optional[float] = None,
    alpha: Optional[float] = None,
    label: Optional[str] = None,
    align: str = "center",
    xerr: Any = None,
    yerr: Any = None,
    capsize: Optional[float] = None,
    ecolor: Any = None,
    error_kw: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> BarContainer:
    """Vertical bars of the given ``height`` at positions ``x``.

    ``x`` may be numeric positions or category labels. ``bottom`` stacks
    this series on top of another. ``align`` is ``"center"`` (default) or
    ``"edge"``. ``xerr``/``yerr``/``capsize``/``ecolor``/``error_kw`` draw
    matplotlib-style error bars; ``color``, ``edgecolor``, ``linewidth``,
    ``alpha``, and ``label`` style the patches.

    Returns the `BarContainer` holding one patch per bar.
    """
    return gca().bar(
        x,
        height,
        width,
        bottom,
        align=align,
        **_given(
            color=color,
            edgecolor=edgecolor,
            linewidth=linewidth,
            alpha=alpha,
            label=label,
            xerr=xerr,
            yerr=yerr,
            capsize=capsize,
            ecolor=ecolor,
            error_kw=error_kw,
        ),
        **kwargs,
    )


def barh(
    y: Any,
    width: Any,
    height: float = 0.8,
    left: Any = None,
    *,
    color: Any = None,
    edgecolor: Any = None,
    linewidth: Optional[float] = None,
    alpha: Optional[float] = None,
    label: Optional[str] = None,
    align: str = "center",
    xerr: Any = None,
    yerr: Any = None,
    capsize: Optional[float] = None,
    ecolor: Any = None,
    error_kw: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> BarContainer:
    """Horizontal bars of the given ``width`` at positions ``y``.

    The horizontal twin of `bar`: ``left`` stacks series, ``align`` is
    ``"center"`` or ``"edge"``, and the same styling and error-bar
    keywords apply.
    """
    return gca().barh(
        y,
        width,
        height,
        left,
        align=align,
        **_given(
            color=color,
            edgecolor=edgecolor,
            linewidth=linewidth,
            alpha=alpha,
            label=label,
            xerr=xerr,
            yerr=yerr,
            capsize=capsize,
            ecolor=ecolor,
            error_kw=error_kw,
        ),
        **kwargs,
    )


def bar_label(
    container: BarContainer,
    labels: Any = None,
    *,
    fmt: Any = "%g",
    label_type: str = "edge",
    padding: float = 0,
    color: Any = None,
    fontsize: Any = None,
    **kwargs: Any,
) -> list[Text]:
    """Label the bars of a `bar`/`barh` container with their values.

    ``labels`` overrides the default value labels; ``fmt`` is a %-format,
    ``{}``-format, or callable; ``label_type`` places labels at the bar
    ``"edge"`` or ``"center"``, offset by ``padding`` points.
    """
    return gca().bar_label(
        container,
        labels,
        fmt=fmt,
        label_type=label_type,
        padding=padding,
        **_given(color=color, fontsize=fontsize),
        **kwargs,
    )


def grouped_bar(
    heights: Any,
    *,
    positions: Any = None,
    group_spacing: float = 1.5,
    bar_spacing: float = 0,
    tick_labels: Any = None,
    labels: Any = None,
    orientation: str = "vertical",
    colors: Any = None,
    **kwargs: Any,
) -> GroupedBarReturn:
    """Grouped bars: one group per position, one bar per dataset.

    ``heights`` is a sequence of datasets, a mapping of label → dataset,
    or a 2-D array (one column per dataset). Spacing is in multiples of
    bar width, matching matplotlib's `Axes.grouped_bar`.
    """
    return gca().grouped_bar(
        heights,
        positions=positions,
        group_spacing=group_spacing,
        bar_spacing=bar_spacing,
        tick_labels=tick_labels,
        labels=labels,
        orientation=orientation,
        colors=colors,
        **kwargs,
    )


def hist(
    x: Any,
    bins: Any = 10,
    range: Any = None,
    density: bool = False,
    cumulative: bool = False,
    *,
    weights: Any = None,
    color: Any = None,
    edgecolor: Any = None,
    alpha: Optional[float] = None,
    label: Any = None,
    histtype: str = "bar",
    orientation: str = "vertical",
    stacked: bool = False,
    **kwargs: Any,
) -> tuple[Any, np.ndarray, Any]:
    """A histogram of ``x`` on the current axes.

    Parameters
    ----------
    x : array-like or sequence of array-likes
        Input values; a sequence of datasets draws grouped/stacked bars.
    bins : int, sequence of edges, or str, default 10
        Binning, as in `numpy.histogram`.
    range : (float, float), optional
        Lower and upper bin range.
    density : bool, default False
        Normalize counts so the integral is 1.
    cumulative : bool, default False
        Accumulate counts left to right (or right to left for ``-1``).
    weights : array-like, optional
        Per-value weights.
    histtype : {"bar", "barstacked", "step", "stepfilled"}, default "bar"
    orientation : {"vertical", "horizontal"}, default "vertical"
    stacked : bool, default False
        Stack multiple datasets instead of grouping them.
    color, edgecolor, alpha, label
        Patch styling and legend entry (one per dataset).

    Returns
    -------
    counts, bin_edges, patches
        As matplotlib: counts (or a list of them), the edge array, and
        the bar container(s).
    """
    return gca().hist(
        x,
        bins,
        range=range,
        density=density,
        cumulative=cumulative,
        histtype=histtype,
        orientation=orientation,
        stacked=stacked,
        **_given(
            weights=weights,
            color=color,
            edgecolor=edgecolor,
            alpha=alpha,
            label=label,
        ),
        **kwargs,
    )


def fill_between(
    x: Any,
    y1: Any,
    y2: Any = 0.0,
    where: Any = None,
    *,
    interpolate: bool = False,
    step: Any = None,
    color: Any = None,
    alpha: Optional[float] = None,
    label: Optional[str] = None,
    transform: Any = None,
    **kwargs: Any,
) -> PolyCollection:
    """Fill the area between two horizontal curves ``y1`` and ``y2``.

    ``where`` masks the fill to a boolean condition (``interpolate=True``
    closes the gaps at crossings); ``step`` fills as steps
    (``"pre"``/``"post"``/``"mid"``). ``color`` (alias
    ``facecolor``/``fc``), ``alpha``, and ``label`` style the patch.
    """
    return gca().fill_between(
        x,
        y1,
        y2,
        interpolate=interpolate,
        **_given(
            where=where,
            step=step,
            color=color,
            alpha=alpha,
            label=label,
            transform=transform,
        ),
        **kwargs,
    )


def fill_betweenx(
    y: Any,
    x1: Any,
    x2: Any = 0,
    where: Any = None,
    **kwargs: Any,
) -> PolyCollection:
    """Fill the area between two vertical curves ``x1`` and ``x2``.

    The vertical twin of `fill_between`; accepts the same keywords
    (``color``/``facecolor``, ``edgecolor``, ``linewidth``, ``alpha``,
    ``label``, ``interpolate``, ``step``, ``transform``, ``data``).
    """
    return gca().fill_betweenx(y, x1, x2, where, **kwargs)


def fill(*args: Any, data: Any = None, **kwargs: Any) -> list[PolyCollection]:
    """Draw filled polygons from ``x, y[, color]`` argument groups.

    Accepts matplotlib's repeated-group form ``fill(x1, y1, "b", x2, y2,
    "r")`` plus ``color``/``facecolor``, ``edgecolor``/``ec``,
    ``linewidth``/``lw``, ``alpha``, and ``label`` keywords.
    """
    return gca().fill(*args, data=data, **kwargs)


def stackplot(
    x: Any,
    *args: Any,
    labels: Any = (),
    colors: Any = None,
    baseline: str = "zero",
    data: Any = None,
    **kwargs: Any,
) -> list[PolyCollection]:
    """A stacked area plot of one or more series over ``x``.

    Pass the series as separate arguments or one 2-D array.
    ``baseline`` is ``"zero"``, ``"sym"``, ``"wiggle"``, or
    ``"weighted_wiggle"``; ``alpha``, ``linewidth``/``lw``,
    ``edgecolor``, and ``facecolor`` keywords style the layers.
    """
    return gca().stackplot(
        x, *args, labels=labels, colors=colors, baseline=baseline, data=data, **kwargs
    )


def stem(
    *args: Any,
    linefmt: Any = None,
    markerfmt: Any = None,
    basefmt: Any = None,
    bottom: float = 0,
    label: Any = None,
    orientation: str = "vertical",
    data: Any = None,
) -> StemContainer:
    """A stem plot: vertical lines from a baseline to markers at each y.

    Call as ``stem(y)`` or ``stem(x, y)``. ``linefmt``/``markerfmt``/
    ``basefmt`` are `plot`-style fmt strings for the stems, heads, and
    baseline; ``bottom`` moves the baseline.
    """
    return gca().stem(
        *args,
        linefmt=linefmt,
        markerfmt=markerfmt,
        basefmt=basefmt,
        bottom=bottom,
        label=label,
        orientation=orientation,
        data=data,
    )


def stairs(
    values: Any,
    edges: Any = None,
    *,
    orientation: str = "vertical",
    baseline: Any = 0,
    fill: bool = False,
    data: Any = None,
    **kwargs: Any,
) -> StepPatch:
    """A stepwise constant function as a line or filled patch.

    ``values`` has one entry per interval, ``edges`` one more (defaults
    to ``0..len(values)``). Line keywords (``color``, ``linewidth``,
    ``linestyle``, ``alpha``, ``label``, ``hatch``) style the patch.
    """
    return gca().stairs(
        values,
        edges,
        orientation=orientation,
        baseline=baseline,
        fill=fill,
        data=data,
        **kwargs,
    )


def ecdf(
    x: Any,
    weights: Any = None,
    *,
    complementary: bool = False,
    orientation: str = "vertical",
    compress: bool = False,
    data: Any = None,
    **kwargs: Any,
) -> Artist:
    """The empirical cumulative distribution function of ``x``.

    ``complementary=True`` plots 1 - ECDF; line keywords (``color``,
    ``linewidth``, ``linestyle``, ``label``) style the curve.
    """
    return gca().ecdf(
        x,
        weights,
        complementary=complementary,
        orientation=orientation,
        compress=compress,
        data=data,
        **kwargs,
    )


def imshow(
    z: Any,
    cmap: Any = None,
    *,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    alpha: Optional[float] = None,
    origin: Optional[str] = None,
    aspect: Any = None,
    extent: Any = None,
    interpolation: Optional[str] = None,
    **kwargs: Any,
) -> AxesImage:
    """Display a 2-D scalar array or RGB(A) image on the current axes.

    Parameters
    ----------
    z : array-like
        ``(M, N)`` scalar data mapped through ``cmap``, or an
        ``(M, N, 3|4)`` RGB(A) image.
    cmap : str, optional
        Colormap name for scalar data (default from ``rcParams``).
    vmin, vmax : float, optional
        Color-limit pins for scalar data (``clim`` is also accepted).
    alpha : float, optional
        Image opacity in [0, 1].
    origin : {"upper", "lower"}, optional
        Index origin placement (default from ``rcParams``).
    aspect : {"equal", "auto"} or float, optional
        Axes aspect override.
    extent : (left, right, bottom, top), optional
        Data coordinates the image spans.
    interpolation : str, optional
        Resampling hint; nearest-equivalent modes are honored.

    The image becomes the figure's current mappable, so a bare
    `colorbar()` attaches to it. ``norm`` is not supported and raises.

    Returns
    -------
    AxesImage
    """
    return _record_mappable(
        gca().imshow(
            z,
            cmap,
            **_given(
                vmin=vmin,
                vmax=vmax,
                alpha=alpha,
                origin=origin,
                aspect=aspect,
                extent=extent,
                interpolation=interpolation,
            ),
            **kwargs,
        )
    )


def matshow(z: Any, **kwargs: Any) -> Any:
    """Display a matrix with ticks on top, as matplotlib's `matshow`.

    Accepts the `imshow` keywords (``cmap``, ``vmin``/``vmax``,
    ``alpha``, ``extent``, ...).
    """
    return _record_mappable(gca().matshow(z, **kwargs))


def pcolormesh(*args: Any, **kwargs: Any) -> PolyCollection:
    """A pseudocolor quadrilateral mesh of a 2-D array.

    Call as ``pcolormesh(C)`` or ``pcolormesh(X, Y, C)``. Supported
    keywords: ``cmap``, ``vmin``/``vmax``, ``alpha``, ``shading``
    (``"flat"``/``"nearest"``/``"auto"``/``"gouraud"``),
    ``edgecolors``/``edgecolor``, ``linewidth``/``linewidths``, and
    ``antialiased``. The mesh becomes the figure's current mappable.
    """
    return _record_mappable(gca().pcolormesh(*args, **kwargs))


def pcolor(*args: Any, **kwargs: Any) -> PolyCollection:
    """A pseudocolor plot of a 2-D array (see `pcolormesh`).

    Same call forms and keywords as `pcolormesh`, which implements it.
    """
    return _record_mappable(gca().pcolor(*args, **kwargs))


def pcolorfast(*args: Any, **kwargs: Any) -> PolyCollection:
    """matplotlib's fast pseudocolor path, served by `pcolormesh` here.

    Same call forms and keywords as `pcolormesh`.
    """
    return _record_mappable(gca().pcolorfast(*args, **kwargs))


def hist2d(
    x: Any,
    y: Any,
    bins: Any = 10,
    *,
    range: Any = None,
    density: bool = False,
    weights: Any = None,
    cmin: Any = None,
    cmax: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, PolyCollection]:
    """A 2-D histogram of ``x``/``y`` rendered as a pseudocolor mesh.

    ``bins``/``range``/``density``/``weights`` follow
    `numpy.histogram2d`; ``cmin``/``cmax`` blank cells outside the count
    window. ``cmap``, ``vmin``/``vmax``, and ``alpha`` style the mesh,
    which becomes the figure's current mappable.

    Returns ``(counts, xedges, yedges, image)`` as matplotlib does.
    """
    return _record_mappable(
        gca().hist2d(
            x,
            y,
            bins,
            range=range,
            density=density,
            weights=weights,
            cmin=cmin,
            cmax=cmax,
            data=data,
            **kwargs,
        )
    )


def hexbin(
    x: Any,
    y: Any,
    C: Any = None,
    *,
    gridsize: Any = 100,
    bins: Any = None,
    xscale: str = "linear",
    yscale: str = "linear",
    extent: Any = None,
    cmap: Any = None,
    norm: Any = None,
    vmin: Any = None,
    vmax: Any = None,
    alpha: Any = None,
    linewidths: Any = None,
    edgecolors: Any = "face",
    reduce_C_function: Any = np.mean,
    mincnt: Any = None,
    marginals: bool = False,
    colorizer: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> PathCollection:
    """A hexagonal binning plot of ``x``/``y`` point density.

    With ``C`` given, each hexagon shows ``reduce_C_function`` of the
    values that fall in it instead of a count. ``gridsize`` sets the
    number of hexagons across, ``bins="log"`` log-scales the counts, and
    ``mincnt`` hides sparse cells. The result becomes the figure's
    current mappable.
    """
    return _record_mappable(
        gca().hexbin(
            x,
            y,
            C,
            gridsize=gridsize,
            bins=bins,
            xscale=xscale,
            yscale=yscale,
            extent=extent,
            cmap=cmap,
            norm=norm,
            vmin=vmin,
            vmax=vmax,
            alpha=alpha,
            linewidths=linewidths,
            edgecolors=edgecolors,
            reduce_C_function=reduce_C_function,
            mincnt=mincnt,
            marginals=marginals,
            colorizer=colorizer,
            data=data,
            **kwargs,
        )
    )


def contour(*args: Any, data: Any = None, **kwargs: Any) -> ContourSet:
    """Contour lines of a 2-D array.

    Call as ``contour(Z)``, ``contour(X, Y, Z)``, or with a trailing
    level count/sequence. Supported keywords: ``levels``, ``cmap``,
    ``colors``, ``linewidths``, ``linestyles``, ``alpha``, and
    ``extent``. The set becomes the figure's current mappable.
    """
    return _record_mappable(gca().contour(*args, data=data, **kwargs))


def contourf(*args: Any, data: Any = None, **kwargs: Any) -> ContourSet:
    """Filled contours of a 2-D array (same call forms as `contour`)."""
    return _record_mappable(gca().contourf(*args, data=data, **kwargs))


def clabel(
    CS: ContourSet,
    levels: Any = None,
    *,
    fontsize: Any = None,
    inline: bool = True,
    inline_spacing: float = 5,
    fmt: Any = None,
    colors: Any = None,
    use_clabeltext: bool = False,
    manual: Any = False,
    rightside_up: bool = True,
    zorder: Any = None,
) -> list[Text]:
    """Label the levels of a `contour` result in place.

    ``levels`` restricts which levels get labels; ``fmt`` is a %-format,
    mapping, or callable; ``inline`` breaks the contour under each label.
    """
    return gca().clabel(
        CS,
        levels,
        fontsize=fontsize,
        inline=inline,
        inline_spacing=inline_spacing,
        fmt=fmt,
        colors=colors,
        use_clabeltext=use_clabeltext,
        manual=manual,
        rightside_up=rightside_up,
        zorder=zorder,
    )


def spy(
    z: Any,
    precision: Any = 0,
    marker: Any = None,
    markersize: Any = None,
    aspect: Any = "equal",
    origin: str = "upper",
    **kwargs: Any,
) -> Any:
    """Plot the sparsity pattern of a 2-D array.

    Cells with ``|value| > precision`` are drawn; with ``marker`` given
    they render as markers instead of image cells.
    """
    return gca().spy(z, precision, marker, markersize, aspect=aspect, origin=origin, **kwargs)


def axhline(y: float = 0.0, **kwargs: Any) -> Line2D:
    """A horizontal line spanning the axes at data coordinate ``y``.

    Styled by the `plot` line keywords (``color``, ``linewidth``,
    ``linestyle``, ``alpha``, ``label``, ...).
    """
    return gca().axhline(y, **kwargs)


def axvline(x: float = 0.0, **kwargs: Any) -> Line2D:
    """A vertical line spanning the axes at data coordinate ``x``.

    Styled by the `plot` line keywords (``color``, ``linewidth``,
    ``linestyle``, ``alpha``, ``label``, ...).
    """
    return gca().axvline(x, **kwargs)


def axhspan(ymin: float, ymax: float, **kwargs: Any) -> Artist:
    """A horizontal band spanning the axes between ``ymin`` and ``ymax``.

    ``color``/``facecolor``, ``alpha``, and ``label`` style the patch.
    """
    return gca().axhspan(ymin, ymax, **kwargs)


def axvspan(xmin: float, xmax: float, **kwargs: Any) -> Artist:
    """A vertical band spanning the axes between ``xmin`` and ``xmax``.

    ``color``/``facecolor``, ``alpha``, and ``label`` style the patch.
    """
    return gca().axvspan(xmin, xmax, **kwargs)


def axline(
    xy1: tuple[float, float],
    xy2: Optional[tuple[float, float]] = None,
    *,
    slope: Optional[float] = None,
    **kwargs: Any,
) -> Line2D:
    """An infinite line through ``xy1`` and ``xy2`` (or with ``slope``).

    Styled by the `plot` line keywords.
    """
    return gca().axline(xy1, xy2, slope=slope, **kwargs)


def hlines(
    y: Any,
    xmin: Any,
    xmax: Any,
    colors: Any = None,
    linestyles: Any = "solid",
    label: Any = "",
    **kwargs: Any,
) -> PolyCollection:
    """Horizontal line segments from ``xmin`` to ``xmax`` at each ``y``.

    ``colors``/``linestyles`` may be scalars or one per segment;
    ``linewidth``/``linewidths``/``lw``, ``alpha``, ``data``, and
    ``transform`` are also accepted.
    """
    return gca().hlines(y, xmin, xmax, colors, linestyles, label, **kwargs)


def vlines(
    x: Any,
    ymin: Any,
    ymax: Any,
    colors: Any = None,
    linestyles: Any = "solid",
    label: Any = "",
    **kwargs: Any,
) -> PolyCollection:
    """Vertical line segments from ``ymin`` to ``ymax`` at each ``x``.

    The vertical twin of `hlines`, with the same keywords.
    """
    return gca().vlines(x, ymin, ymax, colors, linestyles, label, **kwargs)


def broken_barh(xranges: Any, yrange: Any, **kwargs: Any) -> PolyCollection:
    """A sequence of horizontal bars at one vertical position.

    ``xranges`` is a sequence of ``(start, width)`` pairs and ``yrange``
    a single ``(y, height)``. ``facecolors``/``facecolor``/``color``,
    ``edgecolors``/``edgecolor``, ``linewidth``, ``alpha``, ``label``,
    and ``align`` style the bars.
    """
    return gca().broken_barh(xranges, yrange, **kwargs)


def arrow(x: float, y: float, dx: float, dy: float, **kwargs: Any) -> PolyCollection:
    """An arrow from ``(x, y)`` to ``(x + dx, y + dy)`` in data coordinates.

    Supported keywords: ``width``, ``head_width``, ``head_length``,
    ``length_includes_head``, ``color``/``facecolor``/``edgecolor``,
    ``alpha``, and ``transform``.
    """
    return gca().arrow(x, y, dx, dy, **kwargs)


def text(
    x: Any,
    y: Any,
    s: str,
    fontdict: Optional[dict[str, Any]] = None,
    *,
    color: Any = None,
    fontsize: Any = None,
    ha: Optional[str] = None,
    va: Optional[str] = None,
    rotation: Any = None,
    fontweight: Any = None,
    fontfamily: Any = None,
    transform: Any = None,
    **kwargs: Any,
) -> Text:
    """Place text at data coordinates ``(x, y)`` on the current axes.

    ``ha``/``va`` (aliases ``horizontalalignment``/``verticalalignment``)
    anchor the text; ``color``/``c``, ``fontsize``/``size``,
    ``fontweight``/``weight``, ``fontfamily``/``family``, and
    ``rotation`` style it. Pass ``transform=ax.transAxes`` for
    axes-fraction placement. Basic mathtext (``$...$``) is rendered.
    """
    return gca().text(
        x,
        y,
        s,
        fontdict,
        **_given(
            color=color,
            fontsize=fontsize,
            ha=ha,
            va=va,
            rotation=rotation,
            fontweight=fontweight,
            fontfamily=fontfamily,
            transform=transform,
        ),
        **kwargs,
    )


def annotate(
    text: str,
    xy: tuple[float, float],
    xytext: Optional[tuple[float, float]] = None,
    *,
    xycoords: Any = "data",
    textcoords: Any = None,
    arrowprops: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> Text:
    """Annotate the point ``xy`` with text, optionally offset at ``xytext``.

    ``xycoords``/``textcoords`` choose the coordinate systems (``"data"``,
    ``"axes fraction"``, ``"offset points"``, ...); ``arrowprops`` draws
    a matplotlib-style arrow between the text and the point. `text`
    styling keywords (``color``, ``fontsize``, ``ha``/``va``,
    ``rotation``, ``bbox``, ...) are also accepted.
    """
    return gca().annotate(
        text,
        xy,
        xytext,
        xycoords=xycoords,
        **_given(textcoords=textcoords, arrowprops=arrowprops),
        **kwargs,
    )


def table(
    cellText: Any = None,
    cellColours: Any = None,
    cellLoc: str = "right",
    colWidths: Any = None,
    rowLabels: Any = None,
    rowColours: Any = None,
    rowLoc: str = "left",
    colLabels: Any = None,
    colColours: Any = None,
    colLoc: str = "center",
    loc: str = "bottom",
    bbox: Any = None,
    edges: str = "closed",
    **kwargs: Any,
) -> Table:
    """Add a table of cell texts to the current axes.

    Mirrors matplotlib's `Axes.table` layout arguments; ``color`` and
    ``fontsize`` keywords style the cell text.
    """
    return gca().table(
        cellText,
        cellColours,
        cellLoc,
        colWidths,
        rowLabels,
        rowColours,
        rowLoc,
        colLabels,
        colColours,
        colLoc,
        loc,
        bbox,
        edges,
        **kwargs,
    )


def legend(*args: Any, **kwargs: Any) -> None:
    """Show the legend of the current axes.

    Call forms: ``legend()`` (labeled artists), ``legend(labels)``, or
    ``legend(handles, labels)``. Supported keywords: ``loc``,
    ``ncols``/``ncol``, ``title``, ``fontsize`` (or ``prop={"size":
    ...}``), ``labelcolor``, ``frameon``, ``facecolor``, ``edgecolor``,
    ``framealpha``, ``fancybox``, ``shadow``, ``borderpad``, and
    ``labelspacing``. Unsupported layout keywords raise loudly.
    """
    return gca().legend(*args, **kwargs)


def grid(
    visible: Any = True,
    which: str = "major",
    axis: str = "both",
    *,
    color: Any = None,
    linestyle: Any = None,
    linewidth: Optional[float] = None,
    alpha: Optional[float] = None,
    **kwargs: Any,
) -> None:
    """Toggle and style the grid of the current axes.

    ``which`` selects ``"major"``/``"minor"``/``"both"`` lines and
    ``axis`` restricts to ``"x"`` or ``"y"``. ``color``/``c``,
    ``linestyle``/``ls``, ``linewidth``/``lw``, and ``alpha`` style the
    lines.
    """
    return gca().grid(
        visible,
        which=which,
        axis=axis,
        **_given(color=color, linestyle=linestyle, linewidth=linewidth, alpha=alpha),
        **kwargs,
    )


def axis(arg: Any = None, **kwargs: Any) -> tuple[float, float, float, float]:
    """Get or set axis properties of the current axes.

    ``axis()`` returns ``(xmin, xmax, ymin, ymax)``;
    ``axis((xmin, xmax, ymin, ymax))`` sets the limits;
    ``axis("off"/"on"/"equal"/"scaled"/"square"/"tight"/"auto")`` applies
    the matplotlib convenience modes.
    """
    return gca().axis(arg, **kwargs)


def pie(
    x: Any,
    explode: Any = None,
    labels: Any = None,
    colors: Any = None,
    autopct: Any = None,
    pctdistance: float = 0.6,
    shadow: Any = False,
    labeldistance: Any = 1.1,
    startangle: float = 0,
    radius: float = 1,
    counterclock: bool = True,
    wedgeprops: Any = None,
    textprops: Any = None,
    center: tuple[float, float] = (0, 0),
    frame: bool = False,
    rotatelabels: bool = False,
    normalize: bool = True,
    hatch: Any = None,
    *,
    data: Any = None,
) -> Any:
    """A pie chart of the values in ``x``.

    ``explode`` offsets slices, ``autopct`` labels them with their share
    (%-format or callable), ``startangle``/``counterclock`` control
    orientation, and ``wedgeprops``/``textprops`` style slices and
    labels. Returns ``(wedges, texts)`` or ``(wedges, texts, autotexts)``
    as matplotlib does.
    """
    return gca().pie(
        x,
        explode,
        labels,
        colors,
        autopct,
        pctdistance,
        shadow,
        labeldistance,
        startangle,
        radius,
        counterclock,
        wedgeprops,
        textprops,
        center,
        frame,
        rotatelabels,
        normalize,
        hatch,
        data=data,
    )


def pie_label(
    container: PieContainer,
    labels: Any,
    *,
    distance: float = 0.6,
    textprops: Any = None,
    rotate: bool = False,
    alignment: str = "auto",
) -> list[Text]:
    """Label the wedges of a `pie` result (matplotlib 3.11's
    `Axes.pie_label`).

    ``labels`` may be strings or a %-format/callable applied per wedge;
    ``distance`` places labels as a fraction of the radius.
    """
    return gca().pie_label(
        container,
        labels,
        distance=distance,
        textprops=textprops,
        rotate=rotate,
        alignment=alignment,
    )


def boxplot(
    x: Any,
    *,
    notch: Any = None,
    sym: Any = None,
    vert: Any = None,
    orientation: str = "vertical",
    whis: Any = None,
    positions: Any = None,
    widths: Any = None,
    patch_artist: Any = None,
    bootstrap: Any = None,
    usermedians: Any = None,
    conf_intervals: Any = None,
    meanline: Any = None,
    showmeans: Any = None,
    showcaps: Any = None,
    showbox: Any = None,
    showfliers: Any = None,
    boxprops: Any = None,
    tick_labels: Any = None,
    flierprops: Any = None,
    medianprops: Any = None,
    meanprops: Any = None,
    capprops: Any = None,
    whiskerprops: Any = None,
    manage_ticks: bool = True,
    autorange: bool = False,
    zorder: Any = None,
    capwidths: Any = None,
    label: Any = None,
    data: Any = None,
) -> dict[str, list[Artist]]:
    """Box-and-whisker plots of one dataset or a sequence of datasets.

    Follows matplotlib's `Axes.boxplot`: ``whis`` sets the whisker
    reach, ``positions``/``widths``/``tick_labels`` lay the boxes out,
    the ``show*`` flags toggle elements, and the ``*props`` dicts style
    them. Returns the matplotlib-shaped dict of artist lists.
    """
    return gca().boxplot(
        x,
        notch=notch,
        sym=sym,
        vert=vert,
        orientation=orientation,
        whis=whis,
        positions=positions,
        widths=widths,
        patch_artist=patch_artist,
        bootstrap=bootstrap,
        usermedians=usermedians,
        conf_intervals=conf_intervals,
        meanline=meanline,
        showmeans=showmeans,
        showcaps=showcaps,
        showbox=showbox,
        showfliers=showfliers,
        boxprops=boxprops,
        tick_labels=tick_labels,
        flierprops=flierprops,
        medianprops=medianprops,
        meanprops=meanprops,
        capprops=capprops,
        whiskerprops=whiskerprops,
        manage_ticks=manage_ticks,
        autorange=autorange,
        zorder=zorder,
        capwidths=capwidths,
        label=label,
        data=data,
    )


def bxp(
    bxpstats: Any,
    positions: Any = None,
    *,
    widths: Any = None,
    vert: Any = None,
    orientation: str = "vertical",
    patch_artist: bool = False,
    shownotches: bool = False,
    showmeans: bool = False,
    showcaps: bool = True,
    showbox: bool = True,
    showfliers: bool = True,
    boxprops: Any = None,
    whiskerprops: Any = None,
    flierprops: Any = None,
    medianprops: Any = None,
    capprops: Any = None,
    meanprops: Any = None,
    meanline: bool = False,
    manage_ticks: bool = True,
    zorder: Any = None,
    capwidths: Any = None,
    label: Any = None,
) -> dict[str, list[Artist]]:
    """Draw box plots from precomputed statistics.

    ``bxpstats`` is a list of dicts with ``med``/``q1``/``q3``/
    ``whislo``/``whishi`` (plus optional ``mean``/``fliers``), as
    produced by `matplotlib.cbook.boxplot_stats`.
    """
    return gca().bxp(
        bxpstats,
        positions,
        widths=widths,
        vert=vert,
        orientation=orientation,
        patch_artist=patch_artist,
        shownotches=shownotches,
        showmeans=showmeans,
        showcaps=showcaps,
        showbox=showbox,
        showfliers=showfliers,
        boxprops=boxprops,
        whiskerprops=whiskerprops,
        flierprops=flierprops,
        medianprops=medianprops,
        capprops=capprops,
        meanprops=meanprops,
        meanline=meanline,
        manage_ticks=manage_ticks,
        zorder=zorder,
        capwidths=capwidths,
        label=label,
    )


def violinplot(
    dataset: Any,
    positions: Any = None,
    *,
    vert: Any = None,
    orientation: str = "vertical",
    widths: float = 0.5,
    showmeans: bool = False,
    showextrema: bool = True,
    showmedians: bool = False,
    quantiles: Any = None,
    points: int = 100,
    bw_method: Any = None,
    side: str = "both",
    facecolor: Any = None,
    linecolor: Any = None,
    data: Any = None,
) -> dict[str, Any]:
    """Violin plots (kernel density estimates) of one or more datasets.

    ``bw_method`` tunes the KDE bandwidth, ``points`` its resolution;
    the ``show*`` flags toggle means/extrema/medians and ``side`` draws
    half violins. Returns the matplotlib-shaped dict of artists.
    """
    return gca().violinplot(
        dataset,
        positions,
        vert=vert,
        orientation=orientation,
        widths=widths,
        showmeans=showmeans,
        showextrema=showextrema,
        showmedians=showmedians,
        quantiles=quantiles,
        points=points,
        bw_method=bw_method,
        side=side,
        facecolor=facecolor,
        linecolor=linecolor,
        data=data,
    )


def violin(
    vpstats: Any,
    positions: Any = None,
    *,
    vert: Any = None,
    orientation: str = "vertical",
    widths: Any = 0.5,
    showmeans: bool = False,
    showextrema: bool = True,
    showmedians: bool = False,
    side: str = "both",
    facecolor: Any = None,
    linecolor: Any = None,
) -> dict[str, Any]:
    """Draw violins from precomputed statistics (see `violinplot`).

    ``vpstats`` is a list of dicts with ``coords``/``vals``/``mean``/
    ``median``/``min``/``max``, as from `matplotlib.cbook.violin_stats`.
    """
    return gca().violin(
        vpstats,
        positions,
        vert=vert,
        orientation=orientation,
        widths=widths,
        showmeans=showmeans,
        showextrema=showextrema,
        showmedians=showmedians,
        side=side,
        facecolor=facecolor,
        linecolor=linecolor,
    )


def errorbar(
    x: Any,
    y: Any,
    yerr: Any = None,
    xerr: Any = None,
    fmt: str = "",
    *,
    ecolor: Any = None,
    elinewidth: Any = None,
    capsize: Any = None,
    barsabove: bool = False,
    lolims: Any = False,
    uplims: Any = False,
    xlolims: Any = False,
    xuplims: Any = False,
    errorevery: Any = 1,
    capthick: Any = None,
    elinestyle: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> ErrorbarContainer:
    """Plot ``y`` versus ``x`` with error bars.

    ``xerr``/``yerr`` are scalars, per-point arrays, or ``(lower,
    upper)`` pairs; ``fmt`` is a `plot`-style format for the data line
    and markers. ``ecolor``/``elinewidth``/``capsize``/``capthick``
    style the bars, ``errorevery`` subsamples them, and the ``*lims``
    flags draw one-sided limit arrows. `plot` keywords style the line.
    """
    return gca().errorbar(
        x,
        y,
        yerr,
        xerr,
        fmt,
        ecolor=ecolor,
        elinewidth=elinewidth,
        capsize=capsize,
        barsabove=barsabove,
        lolims=lolims,
        uplims=uplims,
        xlolims=xlolims,
        xuplims=xuplims,
        errorevery=errorevery,
        capthick=capthick,
        elinestyle=elinestyle,
        data=data,
        **kwargs,
    )


def eventplot(
    positions: Any,
    *,
    orientation: str = "horizontal",
    lineoffsets: Any = 1,
    linelengths: Any = 1,
    linewidths: Any = None,
    colors: Any = None,
    alpha: Any = None,
    linestyles: Any = "solid",
    data: Any = None,
    **kwargs: Any,
) -> list[PolyCollection]:
    """Plot identical parallel event lines at the given positions.

    One row (or column, with ``orientation="vertical"``) per dataset;
    ``lineoffsets``/``linelengths`` place and size the ticks.
    """
    return gca().eventplot(
        positions,
        orientation=orientation,
        lineoffsets=lineoffsets,
        linelengths=linelengths,
        linewidths=linewidths,
        colors=colors,
        alpha=alpha,
        linestyles=linestyles,
        data=data,
        **kwargs,
    )


def acorr(x: Any, **kwargs: Any) -> tuple[np.ndarray, np.ndarray, Any, Any]:
    """Plot the autocorrelation of ``x`` (see `xcorr` for the keywords).

    Returns ``(lags, correlations, lines, baseline)``.
    """
    return gca().acorr(x, **kwargs)


def xcorr(
    x: Any,
    y: Any,
    normed: bool = True,
    detrend: Any = None,
    usevlines: bool = True,
    maxlags: Any = 10,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray, Any, Any]:
    """Plot the cross-correlation of ``x`` and ``y`` per lag.

    ``maxlags`` bounds the lag window, ``usevlines`` draws stems instead
    of markers, and ``color``/``linewidth``/``lw`` style them.

    Returns ``(lags, correlations, lines, baseline)``.
    """
    return gca().xcorr(
        x,
        y,
        normed=normed,
        detrend=detrend,
        usevlines=usevlines,
        maxlags=maxlags,
        data=data,
        **kwargs,
    )


def psd(
    x: Any,
    NFFT: int = 256,
    Fs: float = 2,
    Fc: float = 0,
    detrend: Any = None,
    window: Any = None,
    noverlap: int = 0,
    pad_to: Any = None,
    sides: Any = None,
    scale_by_freq: Any = None,
    return_line: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> Any:
    """Plot the power spectral density of ``x`` (Welch's method).

    ``NFFT``/``noverlap``/``window`` control the segmenting, ``Fs`` is
    the sampling frequency, and `plot` keywords style the curve.
    Returns ``(Pxx, freqs)`` (plus the line with ``return_line=True``).
    """
    return gca().psd(
        x,
        NFFT=NFFT,
        Fs=Fs,
        Fc=Fc,
        detrend=detrend,
        window=window,
        noverlap=noverlap,
        pad_to=pad_to,
        sides=sides,
        scale_by_freq=scale_by_freq,
        return_line=return_line,
        data=data,
        **kwargs,
    )


def csd(
    x: Any,
    y: Any,
    NFFT: int = 256,
    Fs: float = 2,
    Fc: float = 0,
    detrend: Any = None,
    window: Any = None,
    noverlap: int = 0,
    pad_to: Any = None,
    sides: Any = None,
    scale_by_freq: Any = None,
    return_line: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> Any:
    """Plot the cross-spectral density of ``x`` and ``y``.

    Same segmenting keywords as `psd`. Returns ``(Pxy, freqs)`` (plus
    the line with ``return_line=True``).
    """
    return gca().csd(
        x,
        y,
        NFFT=NFFT,
        Fs=Fs,
        Fc=Fc,
        detrend=detrend,
        window=window,
        noverlap=noverlap,
        pad_to=pad_to,
        sides=sides,
        scale_by_freq=scale_by_freq,
        return_line=return_line,
        data=data,
        **kwargs,
    )


def cohere(
    x: Any,
    y: Any,
    NFFT: int = 256,
    Fs: float = 2,
    Fc: float = 0,
    detrend: Any = None,
    window: Any = None,
    noverlap: int = 0,
    pad_to: Any = None,
    sides: Any = None,
    scale_by_freq: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Plot the coherence between ``x`` and ``y`` (see `psd` keywords).

    Returns ``(Cxy, freqs)``.
    """
    return gca().cohere(
        x,
        y,
        NFFT=NFFT,
        Fs=Fs,
        Fc=Fc,
        detrend=detrend,
        window=window,
        noverlap=noverlap,
        pad_to=pad_to,
        sides=sides,
        scale_by_freq=scale_by_freq,
        data=data,
        **kwargs,
    )


def specgram(
    x: Any,
    NFFT: int = 256,
    Fs: float = 2,
    Fc: float = 0,
    detrend: Any = None,
    window: Any = None,
    noverlap: int = 128,
    cmap: Any = None,
    xextent: Any = None,
    pad_to: Any = None,
    sides: Any = None,
    scale_by_freq: Any = None,
    mode: Any = None,
    scale: Any = None,
    vmin: Any = None,
    vmax: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, PolyCollection]:
    """Plot a spectrogram of ``x`` as a pseudocolor image.

    Segmenting follows `psd`; ``cmap``/``vmin``/``vmax``/``alpha`` style
    the image. Returns ``(spectrum, freqs, t, image)``.
    """
    return gca().specgram(
        x,
        NFFT=NFFT,
        Fs=Fs,
        Fc=Fc,
        detrend=detrend,
        window=window,
        noverlap=noverlap,
        cmap=cmap,
        xextent=xextent,
        pad_to=pad_to,
        sides=sides,
        scale_by_freq=scale_by_freq,
        mode=mode,
        scale=scale,
        vmin=vmin,
        vmax=vmax,
        data=data,
        **kwargs,
    )


def magnitude_spectrum(
    x: Any,
    Fs: float = 2,
    Fc: float = 0,
    window: Any = None,
    pad_to: Any = None,
    sides: Any = None,
    scale: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray, Line2D]:
    """Plot the magnitude spectrum of ``x``.

    ``scale`` is ``"linear"`` or ``"dB"``; `plot` keywords style the
    curve. Returns ``(spectrum, freqs, line)``.
    """
    return gca().magnitude_spectrum(
        x,
        Fs=Fs,
        Fc=Fc,
        window=window,
        pad_to=pad_to,
        sides=sides,
        scale=scale,
        data=data,
        **kwargs,
    )


def angle_spectrum(
    x: Any,
    Fs: float = 2,
    Fc: float = 0,
    window: Any = None,
    pad_to: Any = None,
    sides: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray, Line2D]:
    """Plot the angle (wrapped phase) spectrum of ``x``.

    Returns ``(spectrum, freqs, line)``.
    """
    return gca().angle_spectrum(
        x,
        Fs=Fs,
        Fc=Fc,
        window=window,
        pad_to=pad_to,
        sides=sides,
        data=data,
        **kwargs,
    )


def phase_spectrum(
    x: Any,
    Fs: float = 2,
    Fc: float = 0,
    window: Any = None,
    pad_to: Any = None,
    sides: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> tuple[np.ndarray, np.ndarray, Line2D]:
    """Plot the unwrapped phase spectrum of ``x``.

    Returns ``(spectrum, freqs, line)``.
    """
    return gca().phase_spectrum(
        x,
        Fs=Fs,
        Fc=Fc,
        window=window,
        pad_to=pad_to,
        sides=sides,
        data=data,
        **kwargs,
    )


def quiver(*args: Any, data: Any = None, **kwargs: Any) -> PolyCollection:
    """A field of arrows: ``quiver(U, V)`` or ``quiver(X, Y, U, V)``.

    Optionally followed by a color array ``C``. Styling keywords
    (``color``, ``scale``, ``width``, ``alpha``, ...) follow
    matplotlib's quiver where supported; unsupported ones raise loudly.
    """
    return gca().quiver(*args, data=data, **kwargs)


def quiverkey(
    Q: PolyCollection,
    X: float,
    Y: float,
    U: float,
    label: str,
    **kwargs: Any,
) -> PolyCollection:
    """Add a key (reference arrow + label) for a `quiver` plot.

    ``coordinates`` picks the placement system (default ``"axes"``),
    ``labelpos`` puts the label N/S/E/W of the arrow, and ``color``/
    ``labelcolor``/``labelsep``/``angle`` style it.
    """
    return gca().quiverkey(Q, X, Y, U, label, **kwargs)


def barbs(*args: Any, data: Any = None, **kwargs: Any) -> PolyCollection:
    """A field of wind barbs: ``barbs(U, V)`` or ``barbs(X, Y, U, V)``.

    Rendered at matplotlib's default barb geometry; non-default
    ``length``/``fill_empty``/``rounding``/``flip_barb`` raise loudly.
    """
    return gca().barbs(*args, data=data, **kwargs)


def streamplot(
    x: Any,
    y: Any,
    u: Any,
    v: Any,
    density: Any = 1,
    linewidth: Any = None,
    color: Any = None,
    cmap: Any = None,
    norm: Any = None,
    arrowsize: float = 1,
    arrowstyle: str = "-|>",
    minlength: float = 0.1,
    transform: Any = None,
    zorder: Any = None,
    start_points: Any = None,
    maxlength: float = 4.0,
    integration_direction: str = "both",
    broken_streamlines: bool = True,
    integration_max_step_scale: float = 1.0,
    integration_max_error_scale: float = 1.0,
    *,
    num_arrows: int = 1,
    data: Any = None,
) -> StreamplotSet:
    """Streamlines of the vector field ``(u, v)`` on the grid ``(x, y)``.

    ``density`` controls line spacing, ``start_points`` seeds specific
    trajectories, and ``color``/``linewidth`` may be arrays evaluated
    along the field.
    """
    return gca().streamplot(
        x,
        y,
        u,
        v,
        density=density,
        linewidth=linewidth,
        color=color,
        cmap=cmap,
        norm=norm,
        arrowsize=arrowsize,
        arrowstyle=arrowstyle,
        minlength=minlength,
        transform=transform,
        zorder=zorder,
        start_points=start_points,
        maxlength=maxlength,
        integration_direction=integration_direction,
        broken_streamlines=broken_streamlines,
        integration_max_step_scale=integration_max_step_scale,
        integration_max_error_scale=integration_max_error_scale,
        num_arrows=num_arrows,
        data=data,
    )


def tripcolor(
    *args: Any,
    triangles: Any = None,
    facecolors: Any = None,
    shading: str = "flat",
    data: Any = None,
    **kwargs: Any,
) -> PolyCollection:
    """A pseudocolor plot over an unstructured triangular grid.

    Call as ``tripcolor(x, y, values)`` with optional ``triangles``
    indices (Delaunay otherwise). ``cmap``, ``vmin``/``vmax``,
    ``alpha``, and ``edgecolors`` style the mesh, which becomes the
    figure's current mappable.
    """
    return _record_mappable(
        gca().tripcolor(
            *args,
            triangles=triangles,
            facecolors=facecolors,
            shading=shading,
            data=data,
            **kwargs,
        )
    )


def triplot(
    *args: Any,
    triangles: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> list[Line2D]:
    """Draw the edges of an unstructured triangular grid.

    Call as ``triplot(x, y[, fmt])`` with optional ``triangles``
    indices; `plot` keywords style the edges and markers.
    """
    return gca().triplot(*args, triangles=triangles, data=data, **kwargs)


def tricontour(*args: Any, **kwargs: Any) -> ContourSet:
    """Contour lines over an unstructured triangular grid.

    Call as ``tricontour(x, y, values[, levels])``; accepts the
    `contour` keywords.
    """
    return gca().tricontour(*args, **kwargs)


def tricontourf(*args: Any, **kwargs: Any) -> ContourSet:
    """Filled contours over an unstructured triangular grid.

    Call as ``tricontourf(x, y, values[, levels])``; accepts the
    `contour` keywords.
    """
    return gca().tricontourf(*args, **kwargs)


def autoscale(enable: bool = True, axis: str = "both", tight: Optional[bool] = None) -> None:
    """Toggle autoscaling on the current axes and re-fit the limits.

    ``axis`` restricts to ``"x"`` or ``"y"``; ``tight=True`` drops the
    data margins.
    """
    return gca().autoscale(enable, axis, tight)


def autoscale_view(tight: Optional[bool] = None, scalex: bool = True, scaley: bool = True) -> None:
    """Re-fit the current axes' limits to the data (see `autoscale`)."""
    return gca().autoscale_view(tight, scalex, scaley)


def relim(visible_only: bool = False) -> None:
    """Recompute the current axes' data limits from its artists."""
    return gca().relim(visible_only)


def ticklabel_format(
    *,
    axis: str = "both",
    style: Optional[str] = None,
    scilimits: Optional[tuple[int, int]] = None,
    useOffset: Any = None,
    useLocale: Any = None,
    useMathText: Any = None,
    **kwargs: Any,
) -> None:
    """Configure the scalar tick-label formatter of the current axes.

    ``style`` is ``"sci"``/``"scientific"`` or ``"plain"``;
    ``scilimits=(m, n)`` bounds the exponent range that stays plain;
    ``useOffset`` (alias ``useoffset``) toggles the offset readout.
    """
    return gca().ticklabel_format(
        axis=axis,
        **_given(
            style=style,
            scilimits=scilimits,
            useOffset=useOffset,
            useLocale=useLocale,
            useMathText=useMathText,
        ),
        **kwargs,
    )


def minorticks_on() -> None:
    """Show minor ticks on the current axes."""
    return gca().minorticks_on()


def minorticks_off() -> None:
    """Hide minor ticks on the current axes."""
    return gca().minorticks_off()


def get_xbound() -> tuple[float, float]:
    """The current axes' x bounds as an ascending ``(lower, upper)``."""
    return gca().get_xbound()


def set_xbound(lower: Any = None, upper: Any = None) -> None:
    """Set the current axes' x bounds, keeping the axis orientation."""
    return gca().set_xbound(lower, upper)


def get_ybound() -> tuple[float, float]:
    """The current axes' y bounds as an ascending ``(lower, upper)``."""
    return gca().get_ybound()


def set_ybound(lower: Any = None, upper: Any = None) -> None:
    """Set the current axes' y bounds, keeping the axis orientation."""
    return gca().set_ybound(lower, upper)


def title(label: str, **kwargs: Any) -> None:
    """Set the title of the current axes (text keywords as in `text`)."""
    gca().set_title(label, **kwargs)


def suptitle(label: str, **kwargs: Any) -> None:
    """Set the figure-level title above all subplots."""
    gcf().suptitle(label, **kwargs)


def xlabel(label: str, **kwargs: Any) -> None:
    """Set the x-axis label of the current axes.

    ``color``, ``fontsize``/``size``, and other supported text keywords
    style it; unsupported ones raise loudly.
    """
    gca().set_xlabel(label, **kwargs)


def ylabel(label: str, **kwargs: Any) -> None:
    """Set the y-axis label of the current axes (same keywords as `xlabel`)."""
    gca().set_ylabel(label, **kwargs)


def xlim(*args: Any) -> None:
    """Set the x limits of the current axes.

    Call as ``xlim(left, right)``, ``xlim((left, right))``, or with
    ``left=``/``right=``; a descending pair inverts the axis.
    """
    gca().set_xlim(*args)


def ylim(*args: Any) -> None:
    """Set the y limits of the current axes (forms as in `xlim`)."""
    gca().set_ylim(*args)


def xscale(scale: str) -> None:
    """Set the x-axis scale: ``"linear"``, ``"log"``, ``"symlog"``, ...."""
    gca().set_xscale(scale)


def yscale(scale: str) -> None:
    """Set the y-axis scale: ``"linear"``, ``"log"``, ``"symlog"``, ...."""
    gca().set_yscale(scale)


def xticks(ticks: Any = None, labels: Any = None, *, rotation: Any = None, **kwargs: Any) -> None:
    """Place the x ticks at the given positions, optionally relabeled.

    ``rotation`` (degrees) and supported text keywords style the labels.
    """
    gca().set_xticks(ticks, labels, rotation=rotation, **kwargs)


def yticks(ticks: Any = None, labels: Any = None, *, rotation: Any = None, **kwargs: Any) -> None:
    """Place the y ticks at the given positions (see `xticks`)."""
    gca().set_yticks(ticks, labels, rotation=rotation, **kwargs)


def tight_layout(**kwargs: Any) -> None:
    """Trim the figure's padding, as matplotlib's tight layout pass."""
    gcf().tight_layout(**kwargs)


def subplots_adjust(**kwargs: Any) -> None:
    """Adjust subplot spacing (``left``/``right``/``top``/``bottom``/
    ``wspace``/``hspace`` figure fractions)."""
    gcf().subplots_adjust(**kwargs)


def get_cmap(name: Any = None, lut: Any = None) -> Any:
    """Look up a colormap by name (default viridis).

    ``lut`` resamples it to that many entries.
    """
    from ._colors import Cmap

    cmap = Cmap("viridis" if name is None else name)
    return cmap if lut is None else cmap.resampled(int(lut))


def colorbar(*args: Any, **kwargs: Any) -> Any:
    """Attach a colorbar for a mappable (default: the current one).

    Call as ``colorbar()``, ``colorbar(mappable)``, or with ``ax=``/
    ``cax=``/``label=`` as in matplotlib.
    """
    return gcf().colorbar(*args, **kwargs)


def gci() -> Any:
    """The current color-mapped artist (image/collection), or None."""
    return gcf()._gci


def sci(mappable: Any) -> None:
    """Make ``mappable`` the figure's current image (target of `colorbar`)."""
    gcf()._gci = mappable


def clim(vmin: Any = None, vmax: Any = None) -> None:
    """Set the color limits of the current image (see `gci`)."""
    image = gci()
    if image is None:
        raise RuntimeError(
            "clim() requires an image or collection; plot one first (e.g. imshow/scatter)"
        )
    image.set_clim(vmin, vmax)


# -- output ---------------------------------------------------------------------


def savefig(fname: Any, **kwargs: Any) -> None:
    """Save the current figure to ``fname``.

    The format comes from the suffix (or ``format=``): png, svg, or
    html. ``dpi``, ``transparent``, ``facecolor``, ``metadata``, and
    ``bbox_inches="tight"`` are supported; other keywords raise loudly.
    """
    gcf().savefig(fname, **kwargs)


def show(*args: Any, **kwargs: Any) -> None:
    """Display all open figures.

    Inside IPython/Jupyter the figures render inline and are closed,
    matching ``%matplotlib inline``; elsewhere each figure opens via its
    HTML host.
    """
    import sys

    ipython = sys.modules.get("IPython")
    shell = ipython.get_ipython() if ipython is not None else None
    if shell is not None:
        from IPython.display import display  # noqa: PLC0415

        for fig in all_figures():
            display(fig)
        close("all")
        return
    for fig in all_figures():
        fig.show()


def _flush_inline_figures() -> None:
    """Display pyplot figures at the end of an IPython cell, like `%matplotlib inline`."""
    if fignums():
        show()


def _install_ipython_display_hook() -> None:
    """Install one optional end-of-cell flush hook on the active IPython shell."""
    import sys  # noqa: PLC0415

    ipython = sys.modules.get("IPython")
    if ipython is None:
        return
    shell = ipython.get_ipython()
    events = getattr(shell, "events", None)
    if events is None or getattr(shell, "_xy_pyplot_inline_hook", None) is not None:
        return
    events.register("post_execute", _flush_inline_figures)
    shell._xy_pyplot_inline_hook = _flush_inline_figures


# -- namespaces scripts poke at ---------------------------------------------------


class _CmapNamespace:
    """plt.cm.viridis and friends: name carriers the shim resolves by name."""

    @staticmethod
    def get_cmap(name: Any = None, lut: Any = None) -> Any:
        # matplotlib removed cm.get_cmap in 3.9; older scripts still call it.
        return get_cmap(name, lut)

    def __getattr__(self, name: str) -> Any:
        from ._colors import CMAPS

        if name == "ScalarMappable":
            return type("ScalarMappable", (), {"__init__": lambda self, **kwargs: None})

        if name.lower() in CMAPS:
            return name
        raise AttributeError(f"colormap {name!r} is not supported; see docs/matplotlib-compat.md")


cm = _CmapNamespace()


class _ColormapRegistry:
    def __getitem__(self, name: str) -> Any:
        from ._colors import Cmap

        return Cmap(name)

    def __iter__(self):
        fallback = (
            "viridis",
            "plasma",
            "inferno",
            "magma",
            "cividis",
            "gray",
            "turbo",
            "coolwarm",
            "RdBu",
            "RdGy",
            "bwr",
            "jet",
            "Blues",
            "RdYlGn",
            "rainbow",
            "Spectral",
        )
        try:
            _matplotlib = __import__("matplotlib")

            return iter(tuple(_matplotlib.colormaps))
        except (ImportError, AttributeError):
            return iter(fallback)


colormaps = _ColormapRegistry()


# The stock stylesheets scripts reach for, reduced to the rcParams subset the
# shim renders (values match matplotlib 3.11's style library; gray shorthands
# are pre-resolved to hex so exporters never see them).
_NAMED_STYLES: dict[str, dict[str, Any]] = {
    "fivethirtyeight": {
        "figure.facecolor": "#f0f0f0",
        "axes.facecolor": "#f0f0f0",
        "axes.edgecolor": "#f0f0f0",
        "axes.grid": True,
        "grid.color": "#cbcbcb",
        "lines.linewidth": 4.0,
        "font.size": 14.0,
        "axes.prop_cycle": _PropCycle(
            ["#008fd5", "#fc4f30", "#e5ae38", "#6d904f", "#8b8b8b", "#810f7c"]
        ),
    },
    "ggplot": {
        "figure.facecolor": "white",
        "axes.facecolor": "#E5E5E5",
        "axes.edgecolor": "white",
        "axes.labelcolor": "#555555",
        "axes.grid": True,
        "grid.color": "white",
        "xtick.color": "#555555",
        "ytick.color": "#555555",
        "font.size": 10.0,
        "axes.prop_cycle": _PropCycle(
            ["#E24A33", "#348ABD", "#988ED5", "#777777", "#FBC15E", "#8EBA42", "#FFB5B8"]
        ),
    },
    "bmh": {
        "axes.facecolor": "#eeeeee",
        "axes.edgecolor": "#bcbcbc",
        "axes.grid": True,
        "grid.color": "#b2b2b2",
        "lines.linewidth": 2.0,
        "axes.prop_cycle": _PropCycle(
            [
                "#348ABD",
                "#A60628",
                "#7A68A6",
                "#467821",
                "#D55E00",
                "#CC79A7",
                "#56B4E9",
                "#009E73",
                "#F0E442",
                "#0072B2",
            ]
        ),
    },
    "dark_background": {
        "figure.facecolor": "black",
        "axes.facecolor": "black",
        "axes.edgecolor": "white",
        "axes.labelcolor": "white",
        "grid.color": "white",
        "xtick.color": "white",
        "ytick.color": "white",
        "axes.prop_cycle": _PropCycle(
            [
                "#8dd3c7",
                "#feffb3",
                "#bfbbd9",
                "#fa8174",
                "#81b1d2",
                "#fdb462",
                "#b3de69",
                "#bc82bd",
                "#ccebc4",
                "#ffed6f",
            ]
        ),
    },
    "grayscale": {
        "figure.facecolor": "#bfbfbf",
        "axes.facecolor": "white",
        "axes.edgecolor": "black",
        "axes.labelcolor": "black",
        "grid.color": "black",
        "xtick.color": "black",
        "ytick.color": "black",
        "axes.prop_cycle": _PropCycle(["#000000", "#666666", "#999999", "#b3b3b3"]),
    },
    "seaborn-v0_8-white": {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#262626",
        "axes.labelcolor": "#262626",
        "axes.grid": False,
        "grid.color": "#cccccc",
        "xtick.color": "#262626",
        "ytick.color": "#262626",
        "legend.frameon": False,
    },
    "seaborn-v0_8-whitegrid": {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#cccccc",
        "axes.labelcolor": "#262626",
        "axes.grid": True,
        "grid.color": "#cccccc",
        "xtick.color": "#262626",
        "ytick.color": "#262626",
        "legend.frameon": False,
    },
    "seaborn-v0_8-darkgrid": {
        "figure.facecolor": "white",
        "axes.facecolor": "#EAEAF2",
        "axes.edgecolor": "white",
        "axes.labelcolor": "#262626",
        "axes.grid": True,
        "grid.color": "white",
        "xtick.color": "#262626",
        "ytick.color": "#262626",
        "legend.frameon": False,
        # seaborn's axes_style forces white patch edges (bar/hist separators).
        "patch.edgecolor": "white",
        "patch.force_edgecolor": True,
    },
    # seaborn's classic "deep" palette — the cycle sns.set() installs.
    "seaborn-v0_8-deep": {
        "axes.prop_cycle": _PropCycle(
            ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]
        ),
    },
}
_NAMED_STYLES["seaborn-whitegrid"] = _NAMED_STYLES["seaborn-v0_8-whitegrid"]
_NAMED_STYLES["seaborn-darkgrid"] = _NAMED_STYLES["seaborn-v0_8-darkgrid"]


class _StyleNamespace:
    available = ("default", "xy", *sorted(_NAMED_STYLES))

    @staticmethod
    def use(name: Union[str, dict[str, Any], list[Union[str, dict[str, Any]]]]) -> None:
        if isinstance(name, list):
            for item in name:
                _StyleNamespace.use(item)
            return
        if isinstance(name, dict):
            unknown = sorted(set(name) - set(rcParams))
            if unknown:
                raise not_implemented(
                    f"style.use() rcParam {unknown[0]!r}", "the documented rcParams subset"
                )
            rcParams.update(name)
            return
        from . import _axes

        if name in _NAMED_STYLES:
            # matplotlib sheets are additive patches over the current params.
            rcParams.update(_NAMED_STYLES[name])
            _axes._component_cache.clear()
            return
        if name not in ("default", "xy"):
            raise not_implemented(
                f"style.use({name!r})", f"one of {_StyleNamespace.available} or an rcParams dict"
            )
        if name == "xy":
            _axes._MPL_THEME_TOKENS.clear()  # engine-native look
        else:
            rcdefaults()
            _axes._MPL_THEME_TOKENS.update(
                plot_background="#ffffff", axis_color="#000000", text_color="#262626"
            )
        _axes._component_cache.clear()

    @staticmethod
    @contextlib.contextmanager
    def context(name: Union[str, dict[str, Any], list[Union[str, dict[str, Any]]]]):
        from . import _axes

        snapshot = dict(rcParams)
        tokens = dict(_axes._MPL_THEME_TOKENS)
        try:
            _StyleNamespace.use(name)
            yield
        finally:
            rcParams.clear()
            rcParams.update(snapshot)
            _axes._MPL_THEME_TOKENS.clear()
            _axes._MPL_THEME_TOKENS.update(tokens)
            _axes._component_cache.clear()


style = _StyleNamespace()


def cycler(*args: Any, **kwargs: Any) -> Any:
    """matplotlib.cycler reduced to the color cycle the engine consumes."""
    if len(args) == 2 and not kwargs:
        key, values = args
    elif not args and len(kwargs) == 1:
        key, values = next(iter(kwargs.items()))
    else:
        raise not_implemented("cycler() with multiple keys", "a single color cycle")
    if key != "color":
        raise not_implemented(f"cycler({key!r})", "a 'color' cycle")
    return _PropCycle(list(values))


def np_asarray_passthrough(x: Any) -> Any:  # pragma: no cover - numpy re-export shim
    return np.asarray(x)


_install_ipython_display_hook()
