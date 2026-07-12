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
from ._rc import rc, rcParams
from ._state import all_figures, close, figure, gca, gcf, sca
from ._translate import not_implemented

__all__ = [
    "Axes",
    "Figure",
    "LogLocator",
    "acorr",
    "angle_spectrum",
    "annotate",
    "arrow",
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
    "boxplot",
    "broken_barh",
    "bxp",
    "clabel",
    "close",
    "cm",
    "cohere",
    "colorbar",
    "colormaps",
    "contour",
    "contourf",
    "csd",
    "ecdf",
    "errorbar",
    "eventplot",
    "figure",
    "fill",
    "fill_between",
    "fill_betweenx",
    "gca",
    "gcf",
    "get_cmap",
    "grid",
    "grouped_bar",
    "hexbin",
    "hist",
    "hist2d",
    "hlines",
    "imshow",
    "legend",
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
    "rc",
    "rcParams",
    "savefig",
    "sca",
    "scatter",
    "semilogx",
    "semilogy",
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
    "subplot_mosaic",
    "subplots",
    "subplots_adjust",
    "suptitle",
    "table",
    "text",
    "tight_layout",
    "title",
    "tricontour",
    "tricontourf",
    "tripcolor",
    "triplot",
    "twinx",
    "violin",
    "violinplot",
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


def twinx() -> Axes:
    return gca().twinx()


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
