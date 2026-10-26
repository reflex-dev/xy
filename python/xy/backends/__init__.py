"""Optional renderer backends shipped with :mod:`xy`.

Importing this package is intentionally cheap and does not import Matplotlib.
The Matplotlib adapter is loaded only when one of its public classes is
requested, or when Matplotlib resolves ``module://xy.backends.backend_xy``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .display_list import DisplayList, DisplayListError

if TYPE_CHECKING:
    from .backend_xy import FigureCanvasXY, FigureManagerXY, RendererXY, TimerXY
    from .backend_xy_widget import FigureCanvasXYWidget

__all__ = [
    "DisplayList",
    "DisplayListError",
    "FigureCanvasXY",
    "FigureCanvasXYWidget",
    "FigureManagerXY",
    "RendererXY",
    "TimerXY",
]

_MATPLOTLIB_EXPORTS = frozenset(
    {
        "FigureCanvasXY",
        "FigureManagerXY",
        "RendererXY",
        "TimerXY",
    }
)


def __getattr__(name: str) -> Any:
    """Lazily expose the optional Matplotlib backend classes."""
    if name not in _MATPLOTLIB_EXPORTS:
        if name == "FigureCanvasXYWidget":
            from .backend_xy_widget import FigureCanvasXYWidget

            return FigureCanvasXYWidget
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import backend_xy

    return getattr(backend_xy, name)
