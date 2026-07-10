"""The pyplot implicit-state machine: current figure, current axes.

matplotlib's Gcf reduced to what scripts observe: figure(n) creates or
activates, gcf/gca materialize on demand, close() forgets.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from ._mplfig import Figure

_figures: dict[int, Figure] = {}
_current: Optional[int] = None


def figure(
    num: Optional[Union[int, str]] = None,
    figsize: Optional[tuple[float, float]] = None,
    dpi: Optional[float] = None,
    **kwargs: Any,
) -> Figure:
    global _current
    if num is None:
        num = max(_figures) + 1 if _figures else 1
    key = num if isinstance(num, int) else hash(num)
    if key not in _figures:
        _figures[key] = Figure(key, figsize=figsize, dpi=dpi)
    elif figsize is not None or dpi is not None:
        fig = _figures[key]
        fig._figsize = figsize or fig._figsize
        fig._dpi = dpi or fig._dpi
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


def all_figures() -> list[Figure]:
    return list(_figures.values())
