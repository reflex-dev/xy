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

from typing import Any, Optional, Union

import numpy as np

from ._axes import Axes
from ._mplfig import Figure, apply_sharing, make_axes_grid
from ._rc import rc, rc_context, rcdefaults, rcParams
from ._state import all_figures, close, figlabels, fignum_exists, fignums, figure, gca, gcf, sca
from ._translate import not_implemented

__all__ = [
    "Axes",
    "Figure",
    "LogLocator",
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
    "close",
    "cm",
    "cohere",
    "colorbar",
    "colormaps",
    "contour",
    "contourf",
    "csd",
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
    width_ratios = kwargs.pop("width_ratios", None)
    height_ratios = kwargs.pop("height_ratios", None)
    gridspec_kw = kwargs.pop("gridspec_kw", None) or {}
    width_ratios = gridspec_kw.get("width_ratios", width_ratios)
    height_ratios = gridspec_kw.get("height_ratios", height_ratios)
    fig = figure(figsize=figsize, dpi=dpi)
    if fig._axes and any(ax._entries for ax in fig._axes):
        fig = figure(None, figsize=figsize, dpi=dpi)  # fresh figure, mpl semantics
    axes = make_axes_grid(fig, nrows, ncols, squeeze=squeeze)
    fig._width_ratios = None if width_ratios is None else tuple(map(float, width_ratios))
    fig._height_ratios = None if height_ratios is None else tuple(map(float, height_ratios))
    apply_sharing(fig, sharex, sharey)
    return fig, axes


def subplot(*args: Any, **kwargs: Any) -> Axes:
    return gcf().add_subplot(*args)


def subplot_mosaic(mosaic: Any, **kwargs: Any) -> tuple[Figure, dict[Any, Axes]]:
    figsize = kwargs.pop("figsize", None)
    dpi = kwargs.pop("dpi", None)
    fig = figure(None, figsize=figsize, dpi=dpi)
    return fig, fig.subplot_mosaic(mosaic, **kwargs)


def axes(arg: Any = None, **kwargs: Any) -> Axes:
    if arg is None:
        return gcf().add_subplot(111)
    return gcf().add_axes(arg, **kwargs)


def delaxes(ax: Optional[Axes] = None) -> None:
    gcf().delaxes(ax or gca())


def cla() -> None:
    gca().cla()


def clf() -> None:
    gcf().clf()


def get_fignums() -> list[int]:
    return fignums()


def get_figlabels() -> list[str]:
    return figlabels()


def figtext(x: float, y: float, s: str, **kwargs: Any) -> Any:
    return gcf().text(x, y, s, **kwargs)


def figlegend(*args: Any, **kwargs: Any) -> Any:
    return gcf().legend(*args, **kwargs)


def twinx() -> Axes:
    return gca().twinx()


def twiny() -> Axes:
    return gca().twiny()


def subplot2grid(shape: tuple[int, int], loc: tuple[int, int], rowspan: int = 1, colspan: int = 1, fig: Optional[Figure] = None, **kwargs: Any) -> Axes:
    if rowspan != 1 or colspan != 1:
        raise not_implemented("subplot2grid(rowspan/colspan)", "single-cell subplot2grid specs")
    target = fig or gcf()
    target._ensure_grid(int(shape[0]), int(shape[1]))
    ax = target._axes_at(int(loc[0]) * int(shape[1]) + int(loc[1]))
    target._current_ax = ax
    return ax


def box(on: Optional[bool] = None) -> None:
    ax = gca()
    ax._box = True if on is None else bool(on)
    ax._invalidate()


def setp(obj: Any, *args: Any, **kwargs: Any) -> None:
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
    if property is None:
        return {name[4:]: method() for name, method in ((n, getattr(obj, n)) for n in dir(obj) if n.startswith("get_")) if callable(method)}
    getter = getattr(obj, f"get_{property}", None)
    if getter is None:
        raise AttributeError(f"object has no get_{property}()")
    return getter()


def get(obj: Any, property: Optional[str] = None) -> Any:
    return getp(obj, property)


def findobj(obj: Any = None, match: Any = None) -> list[Any]:
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
    rcParams["image.cmap"] = str(getattr(cmap, "name", cmap))


def viridis() -> Any:
    set_cmap("viridis")
    return get_cmap("viridis")


def plasma() -> Any:
    set_cmap("plasma")
    return get_cmap("plasma")


def gray() -> Any:
    set_cmap("gray")
    return get_cmap("gray")


def imsave(fname: Any, arr: Any, **kwargs: Any) -> None:
    format_name = str(kwargs.pop("format", "")).lower()
    kwargs.pop("cmap", None)
    if kwargs:
        raise TypeError(f"imsave() got unsupported keyword argument {next(iter(kwargs))!r}")
    path = str(fname)
    if format_name in {"jpg", "jpeg"} or path.lower().endswith((".jpg", ".jpeg")):
        raise not_implemented("imsave(JPEG)", "PNG output; JPEG remains outside the dependency-free shim")
    image = np.asarray(arr)
    if image.dtype != np.uint8:
        finite = image.astype(float)
        if finite.size and np.nanmax(finite) <= 1.0 and np.nanmin(finite) >= 0.0:
            image = np.clip(finite * 255.0, 0, 255).astype(np.uint8)
        else:
            image = np.clip(finite, 0, 255).astype(np.uint8)
    if image.ndim == 2:
        image = np.repeat(image[:, :, None], 4, axis=2)
        image[:, :, 3] = 255
    elif image.ndim == 3 and image.shape[2] == 3:
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
    if kwargs:
        raise TypeError(f"imread() got unsupported keyword argument {next(iter(kwargs))!r}")
    data = fname.read() if hasattr(fname, "read") else __import__("pathlib").Path(fname).read_bytes()
    if data[:2] == b"\xff\xd8":
        raise not_implemented("imread(JPEG)", "PNG input; JPEG remains outside the dependency-free shim")
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
            width, height, depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk)
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


def _delegated(name: str):
    def call(*args: Any, **kwargs: Any) -> Any:
        return getattr(gca(), name)(*args, **kwargs)

    call.__name__ = name
    call.__qualname__ = name
    call.__doc__ = f"pyplot {name}(): applies to the current axes (see Axes.{name})."
    return call


plot = _delegated("plot")
acorr = _delegated("acorr")
angle_spectrum = _delegated("angle_spectrum")
cohere = _delegated("cohere")
csd = _delegated("csd")
magnitude_spectrum = _delegated("magnitude_spectrum")
phase_spectrum = _delegated("phase_spectrum")
psd = _delegated("psd")
specgram = _delegated("specgram")
xcorr = _delegated("xcorr")
fill = _delegated("fill")
arrow = _delegated("arrow")
axline = _delegated("axline")
scatter = _delegated("scatter")
bar = _delegated("bar")
bar_label = _delegated("bar_label")
grouped_bar = _delegated("grouped_bar")
barh = _delegated("barh")
hist = _delegated("hist")
fill_between = _delegated("fill_between")
fill_betweenx = _delegated("fill_betweenx")
imshow = _delegated("imshow")
matshow = _delegated("matshow")
pcolor = _delegated("pcolor")
pcolorfast = _delegated("pcolorfast")
pcolormesh = _delegated("pcolormesh")
step = _delegated("step")
stem = _delegated("stem")
stairs = _delegated("stairs")
ecdf = _delegated("ecdf")
hist2d = _delegated("hist2d")
hexbin = _delegated("hexbin")
eventplot = _delegated("eventplot")
stackplot = _delegated("stackplot")
axhline = _delegated("axhline")
axvline = _delegated("axvline")
axhspan = _delegated("axhspan")
axvspan = _delegated("axvspan")
annotate = _delegated("annotate")
text = _delegated("text")
table = _delegated("table")
legend = _delegated("legend")
grid = _delegated("grid")
axis = _delegated("axis")
pie = _delegated("pie")
pie_label = _delegated("pie_label")
boxplot = _delegated("boxplot")
bxp = _delegated("bxp")
violinplot = _delegated("violinplot")
violin = _delegated("violin")
errorbar = _delegated("errorbar")
contour = _delegated("contour")
contourf = _delegated("contourf")
clabel = _delegated("clabel")
quiver = _delegated("quiver")
quiverkey = _delegated("quiverkey")
barbs = _delegated("barbs")
streamplot = _delegated("streamplot")
semilogx = _delegated("semilogx")
semilogy = _delegated("semilogy")
loglog = _delegated("loglog")
hlines = _delegated("hlines")
vlines = _delegated("vlines")
broken_barh = _delegated("broken_barh")
spy = _delegated("spy")
tripcolor = _delegated("tripcolor")
triplot = _delegated("triplot")
tricontour = _delegated("tricontour")
tricontourf = _delegated("tricontourf")
autoscale = _delegated("autoscale")
autoscale_view = _delegated("autoscale_view")
relim = _delegated("relim")
ticklabel_format = _delegated("ticklabel_format")
minorticks_on = _delegated("minorticks_on")
minorticks_off = _delegated("minorticks_off")
get_xbound = _delegated("get_xbound")
set_xbound = _delegated("set_xbound")
get_ybound = _delegated("get_ybound")
set_ybound = _delegated("set_ybound")


def title(label: str, **kwargs: Any) -> None:
    gca().set_title(label, **kwargs)


def suptitle(label: str, **kwargs: Any) -> None:
    gcf().suptitle(label, **kwargs)


def xlabel(label: str, **kwargs: Any) -> None:
    gca().set_xlabel(label, **kwargs)


def ylabel(label: str, **kwargs: Any) -> None:
    gca().set_ylabel(label, **kwargs)


def xlim(*args: Any) -> None:
    gca().set_xlim(*args)


def ylim(*args: Any) -> None:
    gca().set_ylim(*args)


def xscale(scale: str) -> None:
    gca().set_xscale(scale)


def yscale(scale: str) -> None:
    gca().set_yscale(scale)


def xticks(ticks: Any = None, labels: Any = None, *, rotation: Any = None, **kwargs: Any) -> None:
    gca().set_xticks(ticks, labels, rotation=rotation, **kwargs)


def yticks(ticks: Any = None, labels: Any = None, *, rotation: Any = None, **kwargs: Any) -> None:
    gca().set_yticks(ticks, labels, rotation=rotation, **kwargs)


def tight_layout(**kwargs: Any) -> None:
    gcf().tight_layout(**kwargs)


def subplots_adjust(**kwargs: Any) -> None:
    gcf().subplots_adjust(**kwargs)


class LogLocator:
    pass


def get_cmap(name: Any = None, lut: Any = None) -> Any:
    from ._colors import Cmap

    cmap = Cmap("viridis" if name is None else name)
    return cmap if lut is None else cmap.resampled(int(lut))


def colorbar(*args: Any, **kwargs: Any) -> None:
    gcf().colorbar(*args, **kwargs)


# -- output ---------------------------------------------------------------------


def savefig(fname: Any, **kwargs: Any) -> None:
    gcf().savefig(fname, **kwargs)


def show(*args: Any, **kwargs: Any) -> None:
    import sys

    ipython = sys.modules.get("IPython")
    shell = ipython.get_ipython() if ipython is not None else None
    if shell is not None:
        from IPython.display import HTML, display  # noqa: PLC0415

        for fig in all_figures():
            display(HTML(fig._to_html()))
        close("all")
        return
    for fig in all_figures():
        fig.show()


# -- namespaces scripts poke at ---------------------------------------------------


class _CmapNamespace:
    """plt.cm.viridis and friends: name carriers the shim resolves by name."""

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
            "bwr",
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


class _StyleNamespace:
    available = ("default", "xy")

    @staticmethod
    def use(name: Union[str, list[str]]) -> None:
        if name not in ("default", "xy"):
            raise not_implemented(f"style.use({name!r})", "'default' or 'xy'")
        from . import _axes

        if name == "xy":
            _axes._MPL_THEME_TOKENS.clear()  # engine-native look
        # 'default' keeps the matplotlib-flavored theme


style = _StyleNamespace()


def np_asarray_passthrough(x: Any) -> Any:  # pragma: no cover - numpy re-export shim
    return np.asarray(x)
