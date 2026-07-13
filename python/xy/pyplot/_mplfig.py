"""The shim Figure: owns a grid of Axes, savefig/show, notebook display.

Single-axes figures delegate straight to the one chart. Multi-panel figures
compose through `_grid` (CSS-grid HTML, stitched native PNG) — the engine
itself has no grid container; that capability lives entirely in this shim.
"""

from __future__ import annotations

import uuid
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
        facecolor: Optional[str] = None,
    ) -> None:
        self.number = num
        self._figsize = figsize
        self._dpi = dpi
        self._facecolor = facecolor or "white"
        self._suptitle: Optional[str] = None
        self._nrows = 1
        self._ncols = 1
        self._axes: list[Axes] = []
        self._current_ax: Optional[Axes] = None
        self._html_cache: Optional[str] = None
        self.transFigure = "figure fraction"
        self._sharex = False
        self._sharey = False
        self._link_group = f"xy-pyplot-{uuid.uuid4().hex[:8]}"
        self._shared_colorbar: Optional[dict[str, Any]] = None
        self._width_ratios: Optional[tuple[float, ...]] = None
        self._height_ratios: Optional[tuple[float, ...]] = None

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

    def add_axes(self, rect: Any, **kwargs: Any) -> Axes:
        del kwargs
        parsed = tuple(float(value) for value in rect)
        if len(parsed) != 4 or any(value < 0 for value in parsed[2:]):
            raise ValueError("add_axes rect must be [left, bottom, width, height]")
        if not self._axes:
            ax = Axes(self)
            self._axes.append(ax)
        else:
            ax = Axes(self)
            self._axes.append(ax)
        ax._figure_rect = parsed
        self._nrows, self._ncols = 1, len(self._axes)
        self._current_ax = ax
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

    def autofmt_xdate(self, **kwargs: Any) -> None:
        del kwargs

    def set_size_inches(self, w: Any, h: Any = None) -> None:
        if h is None:
            w, h = w[0], w[1]  # tuple form
        self._figsize = (float(w), float(h))
        self._invalidate()

    def colorbar(self, mappable: Any = None, *args: Any, **kwargs: Any) -> Any:
        del args
        axes_arg = kwargs.pop("ax", None)
        axes = getattr(mappable, "_axes", None) or self.gca()
        entry = getattr(mappable, "_entry", {})
        props = entry.get("kwargs", {})
        mapped_values = entry.get("source_z", props.get("color", entry.get("z")))
        if mapped_values is None and hasattr(mappable, "get_array"):
            mapped_values = mappable.get_array()
        colormap = props.get("colormap")
        if colormap is None and hasattr(mappable, "get_cmap"):
            cmap_obj = mappable.get_cmap()
            colormap = getattr(cmap_obj, "name", cmap_obj)
        try:
            numeric = np.asarray(mapped_values, dtype=np.float64)
            finite = numeric[np.isfinite(numeric)]
        except (TypeError, ValueError):
            finite = np.asarray([], dtype=np.float64)
        explicit_domain = entry.get("domain", props.get("domain"))
        options = {
            "colormap": colormap or "viridis",
            "domain": (
                [float(explicit_domain[0]), float(explicit_domain[1])]
                if explicit_domain is not None
                else ([float(finite.min()), float(finite.max())] if finite.size else [0.0, 1.0])
            ),
            "label": str(kwargs.pop("label", "")),
            "orientation": str(kwargs.pop("orientation", "vertical")),
        }
        if isinstance(axes_arg, (list, tuple, np.ndarray)):
            self._shared_colorbar = options
            self._invalidate()
        else:
            axes._colorbar = options
            axes._invalidate()

        class _Colorbar:
            def __init__(self, ax: Any, colorbar_options: dict[str, Any]) -> None:
                self.ax = ax
                self._options = colorbar_options

            def add_lines(self, *args: Any, **kwargs: Any) -> None:
                del args, kwargs

            def set_label(self, label: str, **kwargs: Any) -> None:
                del kwargs
                self._options["label"] = str(label)
                self.ax._invalidate()

        return _Colorbar(axes, options)

    def figimage(
        self,
        image: Any,
        xo: float = 0,
        yo: float = 0,
        alpha: Any = None,
        origin: str = "upper",
        **kwargs: Any,
    ) -> Any:
        del kwargs
        axes = self.gca()
        width, height = self._panel_px()
        rows, cols = np.asarray(image).shape[:2]
        empty_axes = not bool(axes._entries)
        if empty_axes:
            axes._axis_props("x")["domain"] = (0.0, 1.0)
            axes._axis_props("y")["domain"] = (0.0, 1.0)
            axes._padding = [0.0, 0.0, 0.0, 0.0]
        extent = (
            float(xo) / width,
            (float(xo) + cols) / width,
            float(yo) / height,
            (float(yo) + rows) / height,
        )
        result = axes.imshow(
            image,
            alpha=alpha,
            origin=origin,
            aspect="auto",
            extent=extent,
            transform=axes.transAxes,
        )
        if len(self._axes) == 1 and empty_axes:
            axes.set_axis_off()
        return result

    def subplot_mosaic(self, mosaic: Any, **kwargs: Any) -> dict[Any, Axes]:
        rows = [list(row) for row in mosaic]
        labels: list[Any] = []
        for row in rows:
            for label in row:
                if label != "." and label not in labels:
                    labels.append(label)
        self._ensure_grid(max(1, len(rows)), max(1, max(map(len, rows))))
        return {label: self._axes_at(index) for index, label in enumerate(labels)}

    # -- panel sizing -----------------------------------------------------------

    def _panel_px(self) -> tuple[int, int]:
        w, h = rc_figsize_px(self._figsize, self._dpi)
        return max(120, w // self._ncols), max(120, h // self._nrows)

    def _charts(self) -> list[Any]:
        total_w, total_h = rc_figsize_px(self._figsize, self._dpi)
        if self._axes and all(ax._figure_rect is not None for ax in self._axes):
            charts = []
            for ax in self._axes:
                plot_w = max(1, round(total_w * ax._figure_rect[2]))
                plot_h = max(1, round(total_h * ax._figure_rect[3]))
                # Absolute axes rectangles describe the plot box.  Export
                # chrome lives outside that rectangle in the surrounding
                # figure buffer, matching Matplotlib add_axes semantics.
                compact = plot_w + 54 < 520
                margin_w, margin_h = (54, 42) if compact else (76, 52)
                ax._absolute_plot_ratio = plot_w / plot_h
                charts.append(ax._build_chart(plot_w + margin_w, plot_h + margin_h))
            return charts
        width_ratios = self._width_ratios or (1.0,) * self._ncols
        height_ratios = self._height_ratios or (1.0,) * self._nrows
        if len(width_ratios) != self._ncols or len(height_ratios) != self._nrows:
            raise ValueError("subplot width/height ratios must match the grid dimensions")
        widths = [max(120, round(total_w * value / sum(width_ratios))) for value in width_ratios]
        heights = [max(120, round(total_h * value / sum(height_ratios))) for value in height_ratios]
        charts = [
            ax._build_chart(widths[index % self._ncols], heights[index // self._ncols])
            for index, ax in enumerate(self._axes)
        ]
        if charts and (self._sharex or self._sharey):
            figures = [chart.figure() for chart in charts]
            linked: list[str] = []
            for dim, shared in (("x", self._sharex), ("y", self._sharey)):
                if not shared:
                    continue
                linked.append(dim)
                ranges = [
                    figure.x_range() if dim == "x" else figure.y_range() for figure in figures
                ]
                domain = (min(min(pair) for pair in ranges), max(max(pair) for pair in ranges))
                for figure in figures:
                    figure._set_axis_domain(dim, domain)
            for figure in figures:
                figure.set_interaction(link_group=self._link_group, link_axes=tuple(linked))
        return charts

    def _single(self) -> Optional[Any]:
        charts = self._charts()
        if (
            self._nrows == self._ncols == 1
            and len(charts) == 1
            and self._axes[0]._figure_rect is None
        ):
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
            if single is None:
                data = self._to_png()
            else:
                from xy import _raster

                data = _raster.to_png(single.figure(), fast=True)
        elif suffix in ("svg",):
            if single is None:
                from ._grid import compose_svg

                data = compose_svg(
                    self._charts(), self._nrows, self._ncols, self._suptitle
                ).encode()
            else:
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

        canvas_size = rc_figsize_px(self._figsize, self._dpi)
        positions = (
            [
                (
                    ax._figure_rect[0]
                    - (46 if round(canvas_size[0] * ax._figure_rect[2]) + 54 < 520 else 62)
                    / canvas_size[0],
                    ax._figure_rect[1]
                    - (36 if round(canvas_size[0] * ax._figure_rect[2]) + 54 < 520 else 42)
                    / canvas_size[1],
                    ax._figure_rect[2]
                    + (54 if round(canvas_size[0] * ax._figure_rect[2]) + 54 < 520 else 76)
                    / canvas_size[0],
                    ax._figure_rect[3]
                    + (42 if round(canvas_size[0] * ax._figure_rect[2]) + 54 < 520 else 52)
                    / canvas_size[1],
                )
                for ax in self._axes
            ]
            if self._axes and all(ax._figure_rect is not None for ax in self._axes)
            else None
        )

        return stitch_png(
            self._charts(),
            self._nrows,
            self._ncols,
            self._suptitle,
            self._shared_colorbar,
            positions=positions,
            canvas_size=canvas_size if positions is not None else None,
            facecolor=self._facecolor,
        )

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
    # Matplotlib's subplots() constructs axes in row-major order and leaves
    # the final one active for subsequent stateful ``plt.*`` calls.
    fig._current_ax = axes[-1, -1]
    if squeeze:
        if nrows == ncols == 1:
            return axes[0, 0]
        if nrows == 1 or ncols == 1:
            return axes.ravel()
    return axes


def apply_sharing(fig: Figure, sharex: bool, sharey: bool) -> None:
    """Share static domains and live pan/zoom ranges across subplot panels."""
    fig._sharex = bool(sharex)
    fig._sharey = bool(sharey)
