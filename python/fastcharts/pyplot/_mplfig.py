"""The shim Figure: owns a grid of Axes, savefig/show, notebook display.

Single-axes figures delegate straight to the one chart. Multi-panel figures
compose through `_grid` (CSS-grid HTML, stitched native PNG) — the engine
itself has no grid container; that capability lives entirely in this shim.
"""

from __future__ import annotations

import warnings
from os import PathLike
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ._axes import Axes
from ._rc import rc_figsize_px
from ._translate import not_implemented


class Figure:
    def __init__(
        self,
        num: int,
        figsize: Optional[tuple[float, float]] = None,
        dpi: Optional[float] = None,
    ) -> None:
        self.number = num
        self._figsize = figsize
        self._dpi = dpi
        self._suptitle: Optional[str] = None
        self._nrows = 1
        self._ncols = 1
        self._axes: list[Axes] = []
        self._current_ax: Optional[Axes] = None
        self._html_cache: Optional[str] = None

    # -- layout --------------------------------------------------------------

    def _invalidate(self) -> None:
        self._html_cache = None

    def add_subplot(self, *args: Any) -> Axes:
        if args and args != (1, 1, 1) and args != (111,):
            nrows, ncols, index = _parse_subplot_args(args)
            self._ensure_grid(nrows, ncols)
            ax = self._axes_at(index - 1)
        else:
            self._ensure_grid(1, 1)
            ax = self._axes_at(0)
        self._current_ax = ax  # matplotlib: add_subplot activates the axes
        return ax

    def _ensure_grid(self, nrows: int, ncols: int) -> None:
        if (
            (nrows, ncols) != (self._nrows, self._ncols)
            and self._axes
            and any(ax._entries for ax in self._axes)
        ):
            raise ValueError("cannot reshape a figure that already has plotted axes")
        self._nrows, self._ncols = nrows, ncols
        while len(self._axes) < nrows * ncols:
            self._axes.append(Axes(self))

    def _axes_at(self, index: int) -> Axes:
        self._ensure_grid(self._nrows, self._ncols)
        if not self._axes:
            self._axes.append(Axes(self))
        return self._axes[index]

    @property
    def axes(self) -> list[Axes]:
        return list(self._axes)

    def gca(self) -> Axes:
        if self._current_ax is not None and self._current_ax in self._axes:
            return self._current_ax
        return self._axes_at(0)

    # -- chrome ---------------------------------------------------------------

    def suptitle(self, title: str, **kwargs: Any) -> None:
        self._suptitle = str(title)
        self._invalidate()

    def tight_layout(self, **kwargs: Any) -> None:
        pass  # engine layout is label-aware already

    def subplots_adjust(self, **kwargs: Any) -> None:
        pass

    def set_size_inches(self, w: Any, h: Any = None) -> None:
        if h is None:
            w, h = w[0], w[1]  # tuple form
        self._figsize = (float(w), float(h))
        self._invalidate()

    def colorbar(self, *args: Any, **kwargs: Any) -> None:
        pass  # heatmap/density charts render their own scale in the legend slot

    # -- panel sizing -----------------------------------------------------------

    def _panel_px(self) -> tuple[int, int]:
        w, h = rc_figsize_px(self._figsize, self._dpi)
        return max(120, w // self._ncols), max(120, h // self._nrows)

    def _charts(self) -> list[Any]:
        pw, ph = self._panel_px()
        return [ax._build_chart(pw, ph) for ax in self._axes] or []

    def _single(self) -> Optional[Any]:
        charts = self._charts()
        if self._nrows == self._ncols == 1 and len(charts) == 1:
            return charts[0]
        return None

    # -- output -----------------------------------------------------------------

    def savefig(
        self, fname: Any, dpi: Any = None, format: Optional[str] = None, **kwargs: Any
    ) -> None:
        kwargs.pop("bbox_inches", None)  # label-aware layout already trims
        kwargs.pop("transparent", None)
        kwargs.pop("facecolor", None)
        path = Path(fname) if isinstance(fname, (str, PathLike)) else None
        suffix = (format or (path.suffix.lstrip(".") if path is not None else "png")).lower()
        if dpi is not None and self._dpi is None:
            self._dpi = float(dpi)
            for ax in self._axes:
                ax._chart = None
            self._invalidate()

        single = self._single()
        if suffix in ("png",):
            data = self._to_png() if single is None else single.to_png()
        elif suffix in ("svg",):
            if single is None:
                raise not_implemented("savefig(<multi-panel>.svg)", "savefig('grid.html') or .png")
            data = single.to_svg().encode()
        elif suffix in ("html",):
            data = self._to_html().encode()
        else:
            raise not_implemented(f"savefig(format={suffix!r})", "png, svg, or html")

        if path is not None:
            path.write_bytes(data)
        else:
            fname.write(data)  # file-like

    def _to_png(self) -> bytes:
        from ._grid import stitch_png

        return stitch_png(self._charts(), self._nrows, self._ncols, self._suptitle)

    def _to_html(self) -> str:
        if self._html_cache is None:
            single = self._single()
            if single is not None and self._suptitle is None:
                self._html_cache = single.to_html()
            else:
                from ._grid import compose_html

                self._html_cache = compose_html(
                    self._charts(), self._nrows, self._ncols, self._suptitle
                )
        return self._html_cache

    def _repr_html_(self) -> str:
        return self._to_html()

    def show(self, *args: Any, **kwargs: Any) -> None:
        import tempfile
        import webbrowser

        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(self._to_html())
        webbrowser.open(f"file://{f.name}")


def _parse_subplot_args(args: tuple) -> tuple[int, int, int]:
    if len(args) == 1 and isinstance(args[0], int) and args[0] >= 111:
        code = args[0]
        return code // 100, (code // 10) % 10, code % 10
    if len(args) == 3:
        return int(args[0]), int(args[1]), int(args[2])
    raise ValueError(f"unsupported add_subplot args: {args!r}")


def make_axes_grid(fig: Figure, nrows: int, ncols: int, squeeze: bool = True) -> Any:
    """The plt.subplots() return contract: Axes, 1-D, or 2-D ndarray."""
    fig._ensure_grid(nrows, ncols)
    axes = np.empty((nrows, ncols), dtype=object)
    for r in range(nrows):
        for c in range(ncols):
            axes[r, c] = fig._axes_at(r * ncols + c)
    if squeeze:
        if nrows == ncols == 1:
            return axes[0, 0]
        if nrows == 1 or ncols == 1:
            return axes.ravel()
    return axes


def apply_sharing(fig: Figure, sharex: bool, sharey: bool) -> None:
    """Static share: at build time, identical domains across panels. Live
    linked panning across panels is an engine roadmap item, not shim scope."""
    if not (sharex or sharey):
        return
    warnings.warn(
        "sharex/sharey apply shared static domains; live linked zoom across "
        "panels is not yet supported",
        stacklevel=3,
    )
