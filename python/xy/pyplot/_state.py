"""The pyplot implicit-state machine: current figure, current axes.

matplotlib's Gcf reduced to what scripts observe: figure(n) creates or
activates, gcf/gca materialize on demand, close() forgets.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from ._mplfig import Figure
from ._rc import rcParams

_figures: dict[int, Figure] = {}
_current: Optional[int] = None


def figure(
    num: Optional[Union[int, str]] = None,
    figsize: Optional[tuple[float, float]] = None,
    dpi: Optional[float] = None,
    **kwargs: Any,
) -> Figure:
    global _current
    toolbar = kwargs.pop("toolbar", None)
    if num is None:
        num = max(_figures) + 1 if _figures else 1
    key = num if isinstance(num, int) else hash(num)
    if key not in _figures:
        _figures[key] = Figure(
            key,
            figsize=figsize,
            dpi=dpi,
            facecolor=kwargs.get("facecolor", rcParams["figure.facecolor"]),
            toolbar=toolbar,
        )
        _figures[key]._label = "" if isinstance(num, int) else str(num)
    elif figsize is not None or dpi is not None or toolbar is not None:
        fig = _figures[key]
        fig._figsize = figsize or fig._figsize
        fig._dpi = dpi or fig._dpi
        fig._toolbar = toolbar if toolbar is not None else fig._toolbar
        fig._invalidate()
    _current = key
    return _figures[key]


def gcf() -> Figure:
    if _current is None or _current not in _figures:
        return figure()
    return _figures[_current]


def gca() -> Any:
    return gcf().gca()


def sca(ax: Any) -> None:
    global _current
    fig = ax.figure if ax.figure is not None else gcf()
    _figures.setdefault(fig.number, fig)
    _current = fig.number
    fig._current_ax = ax


def close(target: Any = None) -> None:
    global _current
    if target == "all":
        _figures.clear()
        _current = None
        return
    if target is None:
        key = _current
    elif isinstance(target, Figure):
        key = target.number
    else:
        key = target if isinstance(target, int) else hash(target)
    _figures.pop(key, None)
    if _current == key:
        _current = max(_figures) if _figures else None


def fignums() -> list[int]:
    return sorted(key for key in _figures if isinstance(key, int))


def fignum_exists(num: Union[int, str]) -> bool:
    key = num if isinstance(num, int) else hash(num)
    return key in _figures


def figlabels() -> list[str]:
    return [
        getattr(_figures[key], "_label", "")
        for key in sorted(_figures)
        if getattr(_figures[key], "_label", "")
    ]


def all_figures() -> list[Figure]:
    figures = list(_figures.values())
    if figures:
        return figures
    # A few official gallery helpers (notably JoinStyle.demo/CapStyle.demo)
    # construct Matplotlib artists internally even after the pyplot import is
    # swapped.  When Matplotlib is already loaded, adapt those line/text-only
    # figures at this boundary so the strict gallery script still exports via xy.
    import sys

    mpl = sys.modules.get("matplotlib.pyplot")
    if mpl is None:
        return figures
    adapted: list[Figure] = []
    for number in mpl.get_fignums():
        source = mpl.figure(number)
        target = Figure(-int(number), figsize=tuple(source.get_size_inches()), dpi=source.dpi)
        target._ensure_grid(1, max(1, len(source.axes)))
        for index, source_axes in enumerate(source.axes):
            axes = target._axes_at(index)
            for line in source_axes.lines:
                marker = line.get_marker()
                axes.plot(
                    line.get_xdata(),
                    line.get_ydata(),
                    color=line.get_color(),
                    linewidth=line.get_linewidth(),
                    **({"marker": marker} if marker not in {None, "None", "none", ""} else {}),
                )
            for item in source_axes.texts:
                x, y = item.get_position()
                axes.text(x, y, item.get_text(), color=item.get_color())
            axes.set_xlim(source_axes.get_xlim())
            axes.set_ylim(source_axes.get_ylim())
            axes.set_title(source_axes.get_title())
        adapted.append(target)
    return adapted
