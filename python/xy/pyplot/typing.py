"""Public typing contracts for :mod:`xy.pyplot`'s two implementations.

``xy.pyplot`` selects its implementation at runtime, so a static type checker
cannot infer a concrete result type from an earlier ``set_mode()`` call.  The
factory result aliases in this module therefore expose the honest union:
xy-owned classes in native mode and dependency-free structural protocols for
Matplotlib-owned objects in compat mode.

The compat protocols deliberately avoid importing Matplotlib.  Native-only
installs can inspect and type-check this module without installing the optional
``xy[matplotlib]`` extra.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, TypeAlias, runtime_checkable

from ._axes import Axes as _NativeAxes
from ._mplfig import Figure as _NativeFigure
from ._mplfig import SubFigure as _NativeSubFigure


@runtime_checkable
class AxesProtocol(Protocol):
    """Figure/axes operations shared by native and compat results."""

    @property
    def figure(self) -> FigureProtocol | None: ...

    def plot(self, *args: Any, **kwargs: Any) -> Sequence[Any]: ...

    def scatter(self, *args: Any, **kwargs: Any) -> Any: ...

    def matshow(self, *args: Any, **kwargs: Any) -> Any: ...

    def set_title(self, title: str, /, **kwargs: Any) -> Any: ...

    def set_xlabel(self, label: str, /, **kwargs: Any) -> Any: ...

    def set_ylabel(self, label: str, /, **kwargs: Any) -> Any: ...

    def get_xlim(self) -> tuple[float, float]: ...

    def get_ylim(self) -> tuple[float, float]: ...


@runtime_checkable
class FigureProtocol(Protocol):
    """Figure operations shared by native and compat results."""

    @property
    def axes(self) -> Sequence[AxesProtocol]: ...

    @property
    def canvas(self) -> Any: ...

    def add_subplot(self, *args: Any, **kwargs: Any) -> AxesProtocol: ...

    def add_axes(self, *args: Any, **kwargs: Any) -> AxesProtocol: ...

    def subplots(self, *args: Any, **kwargs: Any) -> Any: ...

    def savefig(self, fname: Any, **kwargs: Any) -> None: ...

    def get_size_inches(self) -> Any: ...

    def get_dpi(self) -> float: ...


@runtime_checkable
class CompatAxesProtocol(AxesProtocol, Protocol):
    """Matplotlib-owned Axes surface available specifically in compat mode."""

    def get_subplotspec(self) -> Any: ...

    def get_legend_handles_labels(self) -> tuple[list[Any], list[str]]: ...

    def secondary_xaxis(self, *args: Any, **kwargs: Any) -> Any: ...

    def secondary_yaxis(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class CompatFigureProtocol(FigureProtocol, Protocol):
    """Matplotlib-owned Figure surface available specifically in compat mode."""

    def get_layout_engine(self) -> Any: ...

    def draw_without_rendering(self) -> None: ...


NativeAxes: TypeAlias = _NativeAxes
"""Concrete Axes type returned in ``native`` mode."""

NativeFigure: TypeAlias = _NativeFigure
"""Concrete Figure type returned in ``native`` mode."""

NativeSubFigure: TypeAlias = _NativeSubFigure
"""Concrete SubFigure type returned in ``native`` mode."""

CompatAxes: TypeAlias = CompatAxesProtocol
"""Structural Axes type returned in ``compat`` mode."""

CompatFigure: TypeAlias = CompatFigureProtocol
"""Structural Figure type returned in ``compat`` mode."""

AxesResult: TypeAlias = NativeAxes | CompatAxes
"""Return type of a mode-routed pyplot axes factory."""

FigureResult: TypeAlias = NativeFigure | CompatFigure
"""Return type of a mode-routed pyplot figure factory."""

__all__ = [
    "AxesProtocol",
    "AxesResult",
    "CompatAxes",
    "CompatAxesProtocol",
    "CompatFigure",
    "CompatFigureProtocol",
    "FigureProtocol",
    "FigureResult",
    "NativeAxes",
    "NativeFigure",
    "NativeSubFigure",
]
