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
from ._rc import rcParams
from ._state import all_figures, close, figure, gca, gcf, sca
from ._translate import not_implemented

__all__ = [
    "Axes",
    "Figure",
    "bar",
    "barh",
    "close",
    "cm",
    "figure",
    "fill_between",
    "gca",
    "gcf",
    "grid",
    "hist",
    "imshow",
    "legend",
    "pcolormesh",
    "plot",
    "rcParams",
    "savefig",
    "sca",
    "scatter",
    "show",
    "step",
    "style",
    "subplot",
    "subplots",
    "suptitle",
    "text",
    "tight_layout",
    "title",
    "twinx",
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
    fig = figure(figsize=figsize, dpi=dpi)
    if fig._axes and any(ax._entries for ax in fig._axes):
        fig = figure(None, figsize=figsize, dpi=dpi)  # fresh figure, mpl semantics
    axes = make_axes_grid(fig, nrows, ncols, squeeze=squeeze)
    apply_sharing(fig, sharex, sharey)
    return fig, axes


def subplot(*args: Any, **kwargs: Any) -> Axes:
    return gcf().add_subplot(*args)


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
scatter = _delegated("scatter")
bar = _delegated("bar")
barh = _delegated("barh")
hist = _delegated("hist")
fill_between = _delegated("fill_between")
imshow = _delegated("imshow")
pcolormesh = _delegated("pcolormesh")
step = _delegated("step")
axhline = _delegated("axhline")
axvline = _delegated("axvline")
axhspan = _delegated("axhspan")
axvspan = _delegated("axvspan")
annotate = _delegated("annotate")
text = _delegated("text")
legend = _delegated("legend")
grid = _delegated("grid")
pie = _delegated("pie")
boxplot = _delegated("boxplot")
violinplot = _delegated("violinplot")
errorbar = _delegated("errorbar")
contour = _delegated("contour")
contourf = _delegated("contourf")
quiver = _delegated("quiver")


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

        if name.lower() in CMAPS:
            return name
        raise AttributeError(f"colormap {name!r} is not supported; see docs/matplotlib-compat.md")


cm = _CmapNamespace()


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
