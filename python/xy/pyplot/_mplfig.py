"""The shim Figure: owns a grid of Axes, savefig/show, notebook display.

Single-axes figures delegate straight to the one chart. Multi-panel figures
compose through `_grid` (CSS-grid HTML, stitched native PNG) — the engine
itself has no grid container; that capability lives entirely in this shim.
"""

from __future__ import annotations

import uuid
from os import PathLike
from pathlib import Path
from typing import Any, Literal, Optional, overload

import numpy as np

from ._artists import Text
from ._axes import Axes, _plain_text
from ._colors import resolve_color
from ._rc import rc_figsize_px, rcParams
from ._transforms import CoordinateTransform
from ._translate import check_unsupported, not_implemented


def _png_with_metadata(data: bytes, metadata: dict[Any, Any]) -> bytes:
    """Insert standards-compliant PNG text chunks before IEND."""
    from xy import _png

    chunks = []
    for raw_key, raw_value in metadata.items():
        key = str(raw_key)
        value = str(raw_value)
        try:
            encoded_key = key.encode("latin-1", "strict")
        except UnicodeEncodeError:
            encoded_key = b""
        if not encoded_key or len(encoded_key) > 79 or "\x00" in key:
            raise ValueError("PNG metadata keys must be 1-79 Latin-1 characters")
        try:
            payload = key.encode("latin-1") + b"\0" + value.encode("latin-1")
            chunks.append(_png._chunk(b"tEXt", payload))
        except UnicodeEncodeError:
            # iTXt: keyword, compression flag/method, language, translated
            # keyword, then UTF-8 text.
            payload = key.encode("latin-1") + b"\0\0\0\0\0" + value.encode("utf-8")
            chunks.append(_png._chunk(b"iTXt", payload))
    marker = data.rfind(b"\x00\x00\x00\x00IEND")
    if marker < 0:
        raise ValueError("invalid PNG output")
    return data[:marker] + b"".join(chunks) + data[marker:]


class Figure:
    def __init__(
        self,
        num: int,
        figsize: Optional[tuple[float, float]] = None,
        dpi: Optional[float] = None,
        facecolor: Optional[str] = None,
        toolbar: Optional[bool] = None,
    ) -> None:
        self.number = num
        self._figsize = figsize
        self._dpi = dpi
        self._toolbar = toolbar  # None -> rcParams["toolbar"] decides
        # RGBA tuples and other matplotlib color specs normalize to a CSS
        # string here — everything downstream (HTML escaping, "none"/"white"
        # short-circuits) assumes a string.
        self._facecolor = (resolve_color(facecolor) if facecolor is not None else None) or "white"
        self._edgecolor = "white"
        self._suptitle: Optional[str] = None
        self._suptitle_style: dict[str, Any] = {}
        self._supxlabel: Optional[str] = None
        self._supylabel: Optional[str] = None
        self._nrows = 1
        self._ncols = 1
        self._axes: list[Axes] = []
        self._current_ax: Optional[Axes] = None
        self._html_cache: Optional[str] = None
        self.transFigure = CoordinateTransform("figure_fraction")
        self._sharex = False
        self._sharey = False
        self._link_group = f"xy-pyplot-{uuid.uuid4().hex[:8]}"
        self._shared_colorbar: Optional[dict[str, Any]] = None
        self._width_ratios: Optional[tuple[float, ...]] = None
        self._height_ratios: Optional[tuple[float, ...]] = None
        self._layout_options: dict[str, Any] = {}
        self._subplot_adjust: dict[str, float] = {}
        self._label = ""
        self._gci: Any = None  # last color-mapped artist, for plt.colorbar()/clim()

    def _show_toolbar(self) -> bool:
        """Whether panels render the interactive modebar controls.

        The figure kwarg wins; otherwise rcParams["toolbar"] decides, and the
        shim default is "none" — Matplotlib's inline backend shows no toolbar,
        so notebook output stays control-free unless explicitly enabled.
        """
        if self._toolbar is not None:
            return bool(self._toolbar)
        return str(rcParams.get("toolbar", "none")).lower() != "none"

    # -- layout --------------------------------------------------------------

    def _invalidate(self) -> None:
        self._html_cache = None

    @property
    def canvas(self) -> "_FigureCanvas":
        return _FigureCanvas(self)

    def add_subplot(self, *args: Any, **kwargs: Any) -> Axes:
        if len(args) == 1 and isinstance(args[0], _SubplotSpec):
            spec = args[0]
            if spec.is_single and not spec.gridspec.has_custom_geometry:
                self._ensure_grid(spec.nrows, spec.ncols)
                ax = self._axes_at(spec.index)
            else:
                # Spans and custom spacing become explicit figure rectangles.
                # The spec is kept so subplots_adjust() can re-resolve them.
                ax = self.add_axes(spec.gridspec.cell_rect(spec.rows, spec.cols))
                ax._subplot_spec = spec
        elif args and args != (1, 1, 1) and args != (111,):
            nrows, ncols, index = _parse_subplot_args(args)
            if any(a._figure_rect is not None for a in self._axes):
                # matplotlib mixes numbered subplots into figures that already
                # hold free-form axes; keep the figure free-form via the cell
                # rectangle (and return the existing axes for a repeat spec).
                row, col = divmod(index - 1, ncols)
                grid = _GridSpec(self, nrows, ncols)
                rect = grid.cell_rect((row, row + 1), (col, col + 1))
                existing = next((a for a in self._axes if a._figure_rect == rect), None)
                if existing is not None:
                    ax = existing
                else:
                    ax = self.add_axes(rect)
                    ax._subplot_spec = _SubplotSpec(grid, (row, row + 1), (col, col + 1))
            else:
                self._ensure_grid(nrows, ncols)
                ax = self._axes_at(index - 1)
        else:
            self._ensure_grid(1, 1)
            ax = self._axes_at(0)
        self._current_ax = ax  # matplotlib: add_subplot activates the axes
        sharex = kwargs.pop("sharex", None)
        sharey = kwargs.pop("sharey", None)
        if sharex is not None:
            ax._axis["x"] = sharex._axis_props("x")  # static share, as in twiny()
        if sharey is not None:
            ax._axis["y"] = sharey._axis_props("y")
        if kwargs:
            ax.set(**kwargs)
        return ax

    def add_axes(self, rect: Any, **kwargs: Any) -> Axes:
        parsed = tuple(float(value) for value in rect)
        if len(parsed) != 4 or any(value < 0 for value in parsed[2:]):
            raise ValueError("add_axes rect must be [left, bottom, width, height]")
        ax = Axes(self)
        self._axes.append(ax)
        ax._figure_rect = parsed
        self._nrows, self._ncols = 1, len(self._axes)
        self._current_ax = ax
        if kwargs:
            ax.set(**kwargs)
        return ax

    # The 1×1 default (squeeze=True) hands back a bare Axes — the shape almost
    # every script uses — so type checkers and IDE hover see the real type
    # instead of the grid union.
    @overload
    def subplots(
        self,
        nrows: Literal[1] = 1,
        ncols: Literal[1] = 1,
        *,
        sharex: bool = False,
        sharey: bool = False,
        squeeze: Literal[True] = True,
        width_ratios: Any = None,
        height_ratios: Any = None,
        gridspec_kw: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Axes: ...

    @overload
    def subplots(
        self,
        nrows: int = 1,
        ncols: int = 1,
        *,
        sharex: bool = False,
        sharey: bool = False,
        squeeze: bool = True,
        width_ratios: Any = None,
        height_ratios: Any = None,
        gridspec_kw: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any: ...

    def subplots(
        self,
        nrows: int = 1,
        ncols: int = 1,
        *,
        sharex: bool = False,
        sharey: bool = False,
        squeeze: bool = True,
        width_ratios: Any = None,
        height_ratios: Any = None,
        gridspec_kw: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Create a subplot grid on this figure and return its Axes array.

        This mirrors the axes-returning half of ``matplotlib.figure.Figure.subplots``.
        Figure creation and pyplot registration belong to the state module.
        """
        del kwargs
        gridspec_kw = gridspec_kw or {}
        width_ratios = gridspec_kw.get("width_ratios", width_ratios)
        height_ratios = gridspec_kw.get("height_ratios", height_ratios)
        axes = make_axes_grid(self, int(nrows), int(ncols), squeeze=squeeze)
        self._width_ratios = None if width_ratios is None else tuple(map(float, width_ratios))
        self._height_ratios = None if height_ratios is None else tuple(map(float, height_ratios))
        apply_sharing(self, _share_mode(sharex, "sharex"), _share_mode(sharey, "sharey"))
        self._hide_inner_tick_labels(int(nrows), int(ncols))
        self._invalidate()
        return axes

    def _hide_inner_tick_labels(self, nrows: int, ncols: int) -> None:
        """Matplotlib's shared-axes rule: only edge panels keep tick labels."""
        for index, ax in enumerate(self._axes):
            row, col = index // ncols, index % ncols
            if self._sharex in ("all", "col") and row < nrows - 1:
                ax._axis_props("x")["tick_label_strategy"] = "off"
            if self._sharey in ("all", "row") and col > 0:
                ax._axis_props("y")["tick_label_strategy"] = "off"

    def add_gridspec(self, nrows: int = 1, ncols: int = 1, **kwargs: Any) -> "_GridSpec":
        """Return a lightweight GridSpec facade backed by the current grid.

        The shim supports row-major single-cell specs such as ``fig.add_subplot(gs[0, 1])``.
        General spanning layout is intentionally not exposed as a fake GridSpec.
        """
        width_ratios = kwargs.pop("width_ratios", kwargs.pop("widths", None))
        height_ratios = kwargs.pop("height_ratios", kwargs.pop("heights", None))
        if kwargs:
            raise not_implemented(
                f"add_gridspec({', '.join(sorted(kwargs))})",
                "nrows, ncols, width_ratios, and height_ratios",
            )
        self._ensure_grid(int(nrows), int(ncols))
        self._width_ratios = None if width_ratios is None else tuple(map(float, width_ratios))
        self._height_ratios = None if height_ratios is None else tuple(map(float, height_ratios))
        self._invalidate()
        return _GridSpec(
            self,
            int(nrows),
            int(ncols),
            width_ratios=self._width_ratios,
            height_ratios=self._height_ratios,
        )

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

    def get_axes(self) -> list[Axes]:
        return self.axes

    def gca(self) -> Axes:
        if self._current_ax is not None and self._current_ax in self._axes:
            return self._current_ax
        return self._axes_at(0)

    def sca(self, ax: Axes) -> Axes:
        if ax not in self._axes:
            raise ValueError("Axes must belong to this figure")
        self._current_ax = ax
        return ax

    def delaxes(self, ax: Axes) -> None:
        if ax not in self._axes:
            raise ValueError("Axes must belong to this figure")
        index = self._axes.index(ax)
        self._axes.remove(ax)
        ax.figure = None
        if self._current_ax is ax:
            self._current_ax = self._axes[min(index, len(self._axes) - 1)] if self._axes else None
        if not self._axes:
            self._nrows, self._ncols = 1, 1
        self._invalidate()

    def clear(self, keep_observers: bool = False) -> None:
        del keep_observers  # compat-noop: the shim has no observer registry
        for ax in self._axes:
            ax.figure = None
        self._axes = []
        self._current_ax = None
        self._nrows, self._ncols = 1, 1
        self._suptitle = None
        self._supxlabel = None
        self._supylabel = None
        self._shared_colorbar = None
        self._gci = None
        self._width_ratios = None
        self._height_ratios = None
        self._layout_options = {}
        self._subplot_adjust = {}
        self._invalidate()

    clf = clear

    # -- chrome ---------------------------------------------------------------

    def suptitle(self, title: str, **kwargs: Any) -> None:
        size = kwargs.pop("fontsize", kwargs.pop("size", 16.0))
        weight = kwargs.pop("fontweight", kwargs.pop("weight", "normal"))
        family = kwargs.pop("fontfamily", kwargs.pop("family", "system-ui, sans-serif"))
        color = kwargs.pop("color", "#262626")
        x = kwargs.pop("x", 0.5)
        y = kwargs.pop("y", 0.98)
        ha = kwargs.pop("ha", kwargs.pop("horizontalalignment", "center"))
        va = kwargs.pop("va", kwargs.pop("verticalalignment", "top"))
        if kwargs:
            raise TypeError(f"suptitle() got unsupported keyword argument {next(iter(kwargs))!r}")
        self._suptitle = _plain_text(title)
        self._suptitle_style = {
            "size": float(size),
            "weight": str(weight),
            "family": str(family),
            "color": str(color),
            "x": float(x),
            "y": float(y),
            "ha": str(ha),
            "va": str(va),
        }
        self._invalidate()

    def supxlabel(self, label: str, **kwargs: Any) -> Text:
        self._supxlabel = str(label)
        return self.text(0.5, 0.01, label, ha=kwargs.pop("ha", "center"), **kwargs)

    def supylabel(self, label: str, **kwargs: Any) -> Text:
        self._supylabel = str(label)
        return self.text(
            0.01,
            0.5,
            label,
            va=kwargs.pop("va", "center"),
            rotation=kwargs.pop("rotation", "vertical"),
            **kwargs,
        )

    def text(
        self,
        x: Any,
        y: Any,
        s: str,
        fontdict: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Text:
        return self.gca().text(x, y, s, fontdict=fontdict, transform=self.transFigure, **kwargs)

    def legend(self, *args: Any, **kwargs: Any) -> None:
        axes = self.axes or [self.gca()]
        labels = args[1] if len(args) >= 2 else kwargs.get("labels")
        if labels is not None:
            axes[0].legend(args[0] if args else [], labels, **kwargs)
            return None
        for ax in axes:
            if any(entry.get("kwargs", {}).get("name") for entry in ax._entries):
                ax.legend(*args, **kwargs)
        if not any(ax._legend for ax in axes):
            axes[0].legend(*args, **kwargs)
        return None

    def tight_layout(self, **kwargs: Any) -> None:
        pad = kwargs.pop("pad", None)
        h_pad = kwargs.pop("h_pad", None)
        w_pad = kwargs.pop("w_pad", None)
        rect = kwargs.pop("rect", None)
        if kwargs:
            raise TypeError(
                f"tight_layout() got unsupported keyword argument {next(iter(kwargs))!r}"
            )
        self._layout_options = {
            "engine": "tight",
            "pad": pad,
            "h_pad": h_pad,
            "w_pad": w_pad,
            "rect": rect,
        }
        self._invalidate()

    def subplots_adjust(
        self,
        left: Any = None,
        bottom: Any = None,
        right: Any = None,
        top: Any = None,
        wspace: Any = None,
        hspace: Any = None,
    ) -> None:
        """Move the SubplotParams frame; panels re-render at their new rects."""
        updates = {
            "left": left,
            "bottom": bottom,
            "right": right,
            "top": top,
            "wspace": wspace,
            "hspace": hspace,
        }
        material = {key: float(value) for key, value in updates.items() if value is not None}
        merged = {
            **_SUBPLOT_PARAMS,
            "wspace": _SUBPLOT_SPACING,
            "hspace": _SUBPLOT_SPACING,
            **self._subplot_adjust,
            **material,
        }
        if merged["left"] >= merged["right"]:
            raise ValueError("left cannot be >= right")
        if merged["bottom"] >= merged["top"]:
            raise ValueError("bottom cannot be >= top")
        self._subplot_adjust.update(material)
        for ax in self._axes:
            if ax._subplot_spec is not None:
                # Gridspec-derived rectangles track the moved SubplotParams
                # frame (matplotlib re-resolves subplot positions on draw).
                spec = ax._subplot_spec
                ax._figure_rect = spec.gridspec.cell_rect(spec.rows, spec.cols)
            ax._invalidate()
        self._invalidate()

    def autofmt_xdate(self, **kwargs: Any) -> None:
        rotation = float(kwargs.pop("rotation", 30))
        ha = kwargs.pop("ha", "right")
        if kwargs:
            raise TypeError(
                f"autofmt_xdate() got unsupported keyword argument {next(iter(kwargs))!r}"
            )
        for ax in self._axes:
            props = ax._axis_props("x")
            props["tick_label_angle"] = rotation
            props.setdefault("style", {})["tick_label_anchor"] = str(ha)
        self._invalidate()

    def set_size_inches(self, w: Any, h: Any = None) -> None:
        if h is None:
            w, h = w[0], w[1]  # tuple form
        self._figsize = (float(w), float(h))
        self._invalidate()

    def get_size_inches(self) -> np.ndarray:
        w, h = rc_figsize_px(self._figsize, self._dpi)
        dpi = self.get_dpi()
        return np.asarray((w / dpi, h / dpi), dtype=float)

    def set_dpi(self, value: Any) -> None:
        self._dpi = float(value)
        for ax in self._axes:
            ax._chart = None
        self._invalidate()

    def get_dpi(self) -> float:
        return float(self._dpi if self._dpi is not None else 100.0)

    @property
    def dpi(self) -> float:
        return self.get_dpi()

    @dpi.setter
    def dpi(self, value: Any) -> None:
        self.set_dpi(value)

    def set_facecolor(self, color: Any) -> None:
        self._facecolor = resolve_color(color) or "none"
        self._invalidate()

    def get_facecolor(self) -> str:
        return self._facecolor

    def set_edgecolor(self, color: Any) -> None:
        self._edgecolor = str(color)
        self._invalidate()

    def get_edgecolor(self) -> str:
        return self._edgecolor

    def colorbar(self, mappable: Any = None, cax: Any = None, ax: Any = None, **kwargs: Any) -> Any:
        if cax is not None:
            raise not_implemented("colorbar(cax=...)", "the automatic colorbar placement")
        if mappable is None:
            mappable = self._gci
        axes_arg = ax
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
            numeric = np.ma.asarray(mapped_values, dtype=np.float64)
            finite = np.asarray(numeric.compressed(), dtype=np.float64)
            finite = finite[np.isfinite(finite)]
        except (TypeError, ValueError):
            finite = np.asarray([], dtype=np.float64)
        explicit_domain = entry.get("domain", props.get("domain"))
        orientation_arg = kwargs.pop("orientation", None)
        location = kwargs.pop("location", None)
        if location is not None:
            location = str(location).lower()
            if location not in {"right", "bottom"}:
                raise not_implemented(
                    f"colorbar(location={location!r})",
                    "right or bottom colorbar placement",
                )
            located_orientation = "vertical" if location == "right" else "horizontal"
            if orientation_arg is not None and str(orientation_arg) != located_orientation:
                raise ValueError("location and orientation select incompatible colorbar sides")
            orientation_arg = located_orientation
        orientation = str(orientation_arg or "vertical")
        if orientation not in {"vertical", "horizontal"}:
            raise ValueError("colorbar() orientation must be 'vertical' or 'horizontal'")
        shrink = float(kwargs.pop("shrink", 1.0))
        if not np.isfinite(shrink) or not 0.0 < shrink <= 1.0:
            raise ValueError("colorbar() shrink must be finite and in (0, 1]")
        anchor_arg = kwargs.pop("anchor", (0.5, 0.5))
        anchor_values = np.asarray(anchor_arg, dtype=np.float64).reshape(-1)
        if len(anchor_values) != 2 or not np.all(np.isfinite(anchor_values)):
            raise ValueError("colorbar() anchor must be a finite (x, y) pair")
        options = {
            "colormap": colormap or "viridis",
            "domain": (
                [float(explicit_domain[0]), float(explicit_domain[1])]
                if explicit_domain is not None
                else ([float(finite.min()), float(finite.max())] if finite.size else [0.0, 1.0])
            ),
            "label": _plain_text(kwargs.pop("label", "")),
            "orientation": orientation,
            "shrink": shrink,
            "anchor": [float(anchor_values[0]), float(anchor_values[1])],
        }
        # When the mappable's value domain is not knowable at colorbar() time
        # (e.g. hexbin counts are binned inside the mark), defer to the compiled
        # figure's color domain at render time instead of the 0..1 placeholder.
        if explicit_domain is None and not finite.size:
            options["_autoscale"] = True
        levels = entry.get("discrete_levels")
        if levels is not None:
            options["levels"] = int(levels)
            boundaries = entry.get("discrete_boundaries")
            if boundaries is not None:
                boundary_values = np.asarray(boundaries, dtype=np.float64).reshape(-1)
                options["boundaries"] = [float(value) for value in boundary_values]
        ticks = kwargs.pop("ticks", None)
        if ticks is not None:
            options["ticks"] = [float(value) for value in np.asarray(ticks).reshape(-1)]
        elif levels is not None and entry.get("discrete_boundaries") is not None:
            # Matplotlib uses a FixedLocator capped at roughly ten bins for a
            # contour colorbar. Match its offset selection so zero (or the
            # boundary closest to it) remains among the visible labels.
            locations = np.asarray(entry["discrete_boundaries"], dtype=np.float64).reshape(-1)
            step = max(1, int(np.ceil(len(locations) / 10)))
            candidates = [locations[offset::step] for offset in range(step)]
            selected = min(candidates, key=lambda values: np.min(np.abs(values)))
            zero_tolerance = (
                np.finfo(np.float64).eps * max(1.0, float(np.max(np.abs(locations)))) * 8
            )
            options["ticks"] = [
                0.0 if abs(float(value)) <= zero_tolerance else float(value) for value in selected
            ]
        extend = kwargs.pop("extend", None)
        if extend is not None:
            if extend not in ("neither", "min", "max", "both"):
                raise ValueError("colorbar() extend must be 'neither', 'min', 'max', or 'both'")
            if extend != "neither":
                options["extend"] = str(extend)
        check_unsupported(kwargs, "colorbar()")
        if isinstance(axes_arg, (list, tuple, np.ndarray)):
            self._shared_colorbar = options
            self._invalidate()
        else:
            axes._colorbar = options
            axes._colorbar_source = entry if entry else None
            axes._invalidate()

        class _Colorbar:
            def __init__(self, ax: Any, colorbar_options: dict[str, Any]) -> None:
                self.ax = ax
                self._options = colorbar_options

            def add_lines(self, *args: Any, **kwargs: Any) -> None:
                del args, kwargs

            def set_label(self, label: str, **kwargs: Any) -> None:
                del kwargs
                self._options["label"] = _plain_text(label)
                self.ax._invalidate()

            def set_ticks(self, ticks: Any, labels: Any = None, **kwargs: Any) -> None:
                if labels is not None:
                    raise not_implemented(
                        "Colorbar.set_ticks(labels=...)", "numeric tick positions"
                    )
                check_unsupported(kwargs, "Colorbar.set_ticks()")
                self._options["ticks"] = [float(value) for value in np.asarray(ticks).reshape(-1)]
                self.ax._invalidate()

            def minorticks_on(self) -> None:
                self._options["minor_ticks"] = True
                self.ax._invalidate()

            def minorticks_off(self) -> None:
                self._options["minor_ticks"] = False
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

    def _effective_rects(self) -> Optional[list[tuple[float, float, float, float]]]:
        """Per-axes figure rects when the figure needs free-form placement, else None.

        A figure is free-form when any axes carries an explicit rect (the
        add_axes path), when subplots_adjust() moved the SubplotParams frame,
        or when it holds more than one panel: multi-panel grids place every
        plot box at its matplotlib gridspec rectangle so the whole figure
        occupies exactly figsize — the CSS-grid composition floored panels at
        120 px, blowing a 6-inch 8x8 grid up to ~1000 px of scrollbars.
        Matplotlib places a rect-less axes at the SubplotParams default, so a
        default axes mixed with an inset keeps its full-size position instead
        of dragging every axes back onto the uniform grid.
        """
        if not self._axes:
            return None
        rects = [ax._figure_rect for ax in self._axes]
        if any(rect is not None for rect in rects):
            default = (
                _GridSpec(self, 1, 1, **self._subplot_adjust).cell_rect((0, 1), (0, 1))
                if self._subplot_adjust
                else (0.125, 0.11, 0.775, 0.77)
            )
            return [rect if rect is not None else default for rect in rects]
        if not self._subplot_adjust and len(self._axes) <= 1:
            return None
        # A uniform grid (adjusted or default SubplotParams): every panel
        # resolves to its gridspec cell rectangle under the frame and spacing.
        grid = _GridSpec(
            self,
            self._nrows,
            self._ncols,
            width_ratios=self._width_ratios,
            height_ratios=self._height_ratios,
            **self._subplot_adjust,
        )
        return [
            grid.cell_rect(
                (index // self._ncols, index // self._ncols + 1),
                (index % self._ncols, index % self._ncols + 1),
            )
            for index in range(len(self._axes))
        ]

    def _grid_cell_sizes(self) -> tuple[list[int], list[int]]:
        """Per-column widths and per-row heights of the CSS-grid panel layout.

        Cells floor at 120 px (the render client's minimum chart size), so a
        dense grid can legitimately exceed the nominal figure size — callers
        sizing the outer document must use these, not `figsize`.
        """
        total_w, total_h = rc_figsize_px(self._figsize, self._dpi)
        width_ratios = self._width_ratios or (1.0,) * self._ncols
        height_ratios = self._height_ratios or (1.0,) * self._nrows
        if len(width_ratios) != self._ncols or len(height_ratios) != self._nrows:
            raise ValueError("subplot width/height ratios must match the grid dimensions")
        widths = [max(120, round(total_w * value / sum(width_ratios))) for value in width_ratios]
        heights = [max(120, round(total_h * value / sum(height_ratios))) for value in height_ratios]
        return widths, heights

    def _charts(self) -> list[Any]:
        total_w, total_h = rc_figsize_px(self._figsize, self._dpi)
        rects = self._effective_rects()
        if rects is not None:
            charts = []
            for ax, rect in zip(self._axes, rects, strict=True):
                plot_w = max(1, round(total_w * rect[2]))
                plot_h = max(1, round(total_h * rect[3]))
                # Absolute axes rectangles describe the plot box.  Export
                # chrome lives outside that rectangle in the surrounding
                # figure buffer, matching Matplotlib add_axes semantics —
                # including the axes title, which matplotlib draws above the
                # axes without moving its position.
                compact = plot_w + 54 < 520
                margin_w, margin_h = (54, 42) if compact else (76, 52)
                if ax._title:
                    margin_h += 26 if compact else 30
                ax._absolute_plot_ratio = plot_w / plot_h
                charts.append(ax._build_chart(plot_w + margin_w, plot_h + margin_h))
        else:
            widths, heights = self._grid_cell_sizes()
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
                for group in self._share_groups(shared, len(figures)):
                    members = [figures[i] for i in group]
                    # matplotlib shared limits autoscale over the group's data;
                    # dataless panels follow the group instead of contributing
                    # their (0, 1) default view to the union.
                    sources = [figure for figure in members if figure.traces] or members
                    ranges = [
                        figure.x_range() if dim == "x" else figure.y_range() for figure in sources
                    ]
                    domain = (
                        min(min(pair) for pair in ranges),
                        max(max(pair) for pair in ranges),
                    )
                    for figure in members:
                        figure._set_axis_domain(dim, domain)
            for figure in figures:
                figure.set_interaction(link_group=self._link_group, link_axes=tuple(linked))
        return charts

    def _share_groups(self, mode: Any, count: int) -> list[list[int]]:
        """Panel-index groups whose data domains union under a share mode."""
        if mode == "col":
            return [
                [r * self._ncols + c for r in range(self._nrows) if r * self._ncols + c < count]
                for c in range(self._ncols)
            ]
        if mode == "row":
            return [
                [r * self._ncols + c for c in range(self._ncols) if r * self._ncols + c < count]
                for r in range(self._nrows)
            ]
        return [list(range(count))]

    def _single(self) -> Optional[Any]:
        charts = self._charts()
        if (
            self._nrows == self._ncols == 1
            and len(charts) == 1
            and self._axes[0]._figure_rect is None
            and not self._subplot_adjust
        ):
            return charts[0]
        return None

    def _panel_positions(
        self,
        rects: list[tuple[float, float, float, float]],
        canvas_size: tuple[int, int],
    ) -> list[tuple[float, float, float, float]]:
        """Expand plot-box rects into whole-panel rects including chart chrome.

        Free-form panels are built at plot size plus fixed chrome margins
        (`_charts`); exporters place the enlarged panel so its plot box lands
        exactly on the requested figure rectangle.
        """
        positions = []
        for ax, rect in zip(self._axes, rects, strict=True):
            compact = round(canvas_size[0] * rect[2]) + 54 < 520
            left, bottom = (46, 36) if compact else (62, 42)
            width, height = (54, 42) if compact else (76, 52)
            if ax._title:
                # The panel was built taller for its title (`_charts`); grow
                # the placement upward so the plot box stays on the rect.
                height += 26 if compact else 30
            positions.append(
                (
                    rect[0] - left / canvas_size[0],
                    rect[1] - bottom / canvas_size[1],
                    rect[2] + width / canvas_size[0],
                    rect[3] + height / canvas_size[1],
                )
            )
        return positions

    # -- output -----------------------------------------------------------------

    def savefig(
        self, fname: Any, dpi: Any = None, format: Optional[str] = None, **kwargs: Any
    ) -> None:
        path = Path(fname) if isinstance(fname, (str, PathLike)) else None
        if path is None and format is None:
            raise ValueError("savefig() requires format= for file-like output")
        if path is not None and format is None and not path.suffix:
            format = "png"  # matplotlib's savefig.format default
            path = path.with_suffix(".png")
        suffix = (format or (path.suffix.lstrip(".") if path is not None else "")).lower()
        transparent = bool(kwargs.pop("transparent", False))
        metadata = kwargs.pop("metadata", None)
        facecolor = kwargs.pop("facecolor", None)
        bbox_inches = kwargs.pop("bbox_inches", None)
        pad_inches = float(kwargs.pop("pad_inches", 0.1))
        if bbox_inches not in (None, "tight"):
            raise not_implemented("savefig(bbox_inches=Bbox)", "bbox_inches='tight'")
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("savefig metadata must be a mapping")
        unsupported = {key for key, value in kwargs.items() if value is not None}
        if unsupported:
            option = sorted(unsupported)[0]
            raise not_implemented(
                f"savefig({option}=...)",
                "dpi and format; compose backgrounds/layout explicitly for other options",
            )

        old_dpi = self._dpi
        old_facecolor = self._facecolor
        old_backgrounds = [ax._theme_tokens["plot_background"] for ax in self._axes]
        if dpi is not None:
            self._dpi = float(dpi)
            for ax in self._axes:
                ax._chart = None
            self._invalidate()
        if facecolor is not None:
            from ._colors import resolve_color

            self._facecolor = resolve_color(facecolor) or "none"
        if transparent:
            self._facecolor = "none"
            for ax in self._axes:
                ax._theme_tokens["plot_background"] = "none"
                ax._chart = None
            self._invalidate()
        try:
            if suffix == "png":
                data = self._to_png(
                    bbox_tight=bbox_inches == "tight",
                    pad_inches=pad_inches,
                )
                if metadata:
                    data = _png_with_metadata(data, metadata)
            elif suffix == "svg":
                single = self._single()
                if single is None or self._suptitle is not None:
                    from ._grid import compose_svg

                    canvas_size = rc_figsize_px(self._figsize, self._dpi)
                    rects = self._effective_rects()
                    data = compose_svg(
                        self._charts(),
                        self._nrows,
                        self._ncols,
                        self._suptitle,
                        self._suptitle_style,
                        positions=(
                            None if rects is None else self._panel_positions(rects, canvas_size)
                        ),
                        canvas_size=None if rects is None else canvas_size,
                    ).encode()
                else:
                    data = single.to_svg().encode()
                if self._facecolor not in ("none", "white"):
                    import html

                    fill = html.escape(self._facecolor, quote=True)
                    start = data.find(b">") + 1
                    rect = f'<rect width="100%" height="100%" fill="{fill}"/>'.encode()
                    data = data[:start] + rect + data[start:]
                if metadata:
                    import html

                    description = html.escape("; ".join(f"{k}: {v}" for k, v in metadata.items()))
                    start = data.find(b">") + 1
                    data = (
                        data[:start] + f"<metadata>{description}</metadata>".encode() + data[start:]
                    )
            elif suffix == "html":
                if metadata:
                    raise not_implemented("savefig(format='html', metadata=...)", "PNG or SVG")
                data = self._facecolor_wrapped(self._to_html()).encode()
            else:
                raise not_implemented(f"savefig(format={suffix!r})", "png, svg, or html")
        finally:
            self._dpi = old_dpi
            self._facecolor = old_facecolor
            for ax, background in zip(self._axes, old_backgrounds, strict=True):
                ax._theme_tokens["plot_background"] = background
                ax._chart = None
            self._invalidate()

        if path is not None:
            path.write_bytes(data)
        else:
            fname.write(data)  # file-like

    def _to_png(self, *, bbox_tight: bool = False, pad_inches: float = 0.1) -> bytes:
        from ._grid import stitch_png

        canvas_size = rc_figsize_px(self._figsize, self._dpi)
        rects = self._effective_rects()
        positions = None if rects is None else self._panel_positions(rects, canvas_size)

        return stitch_png(
            self._charts(),
            self._nrows,
            self._ncols,
            self._suptitle,
            self._shared_colorbar,
            suptitle_style=self._suptitle_style,
            positions=positions,
            canvas_size=canvas_size if positions is not None else None,
            facecolor=self._facecolor,
            bbox_tight=bbox_tight,
            pad_pixels=max(0, round(pad_inches * float(self._dpi or 100.0) * 2.0)),
        )

    def _to_html(self) -> str:
        if self._html_cache is None:
            single = self._single()
            if single is not None and self._suptitle is None:
                self._html_cache = single.to_html()
            else:
                from ._grid import compose_html

                canvas_size = rc_figsize_px(self._figsize, self._dpi)
                rects = self._effective_rects()
                self._html_cache = compose_html(
                    self._charts(),
                    self._nrows,
                    self._ncols,
                    self._suptitle,
                    self._suptitle_style,
                    positions=(
                        None if rects is None else self._panel_positions(rects, canvas_size)
                    ),
                    canvas_size=None if rects is None else canvas_size,
                )
        return self._html_cache

    def _to_notebook_html(self) -> tuple[str, int, int]:
        """Notebook-only tight layout matching Matplotlib's inline backend."""
        width, height = rc_figsize_px(self._figsize, self._dpi)
        dpi = float(self._dpi if self._dpi is not None else 100.0)
        if (
            self._nrows == self._ncols == 1
            and len(self._axes) == 1
            and self._axes[0]._figure_rect is None
            and not self._subplot_adjust
            and self._suptitle is None
        ):
            # Matplotlib's inline backend displays figures with
            # bbox_inches="tight" and pad_inches=.1.  For the ordinary default
            # axes this retains the 0.775×0.77 plot box and its label ink while
            # trimming the unused figure canvas.  Build directly at that tight
            # footprint so fonts/strokes remain unscaled and interactive.
            tight_width = max(120, round(width * 0.775 + dpi * 0.62))
            tight_height = max(120, round(height * 0.77 + dpi * 0.48))
            ax = self._axes[0]
            old_chart, old_padding = ax._chart, ax._padding
            try:
                ax._chart = None
                notebook_padding = [dpi * 0.15, dpi * 0.20, dpi * 0.34, dpi * 0.41]
                if (
                    ax._aspect_equal
                    and ax._aspect_adjustable == "box"
                    and ax._aspect_bounds is not None
                ):
                    # Once adjustable='box' makes an image square, Matplotlib's
                    # inline bbox crops away the old wide axes allocation. Match
                    # that post-layout footprint instead of retaining ~54 px of
                    # outer whitespace around the default square imshow.
                    notebook_padding[3] = dpi * 0.29
                    x0, x1, y0, y1 = ax._aspect_bounds
                    data_ratio = abs(x1 - x0) / max(abs(y1 - y0), np.finfo(float).eps)
                    plot_height = tight_height - notebook_padding[0] - notebook_padding[2]
                    colorbar_room = 0.0
                    if ax._colorbar is not None and ax._colorbar.get("orientation") != "horizontal":
                        colorbar_room = 86.0 + (18.0 if ax._colorbar.get("label") else 0.0)
                    aspect_width = (
                        notebook_padding[3]
                        + plot_height * data_ratio
                        + notebook_padding[1]
                        + colorbar_room
                    )
                    tight_width = max(120, min(tight_width, round(aspect_width)))
                ax._padding = notebook_padding
                doc = ax._build_chart(tight_width, tight_height).to_html()
            finally:
                ax._chart = old_chart
                ax._padding = old_padding
            return doc, tight_width, tight_height
        doc = self._to_html()
        single = self._single()
        if single is not None and self._suptitle is None:
            figure = single.figure()
            return doc, int(figure.width), int(figure.height)
        if self._effective_rects() is None and self._axes:
            # CSS-grid panel layout: cells floor at 120 px, so the composed
            # document can be larger than figsize. Size the notebook iframe to
            # the real grid content (cells + 4 px gaps + 4 px padding) so a
            # dense subplot grid displays whole instead of behind scrollbars.
            widths, heights = self._grid_cell_sizes()
            cols_used = min(len(self._axes), self._ncols)
            rows_used = -(-len(self._axes) // self._ncols)
            content_w = sum(widths[:cols_used]) + 4 * (self._ncols - 1) + 8
            content_h = sum(heights[:rows_used]) + 4 * (rows_used - 1) + 8
            if self._suptitle:
                size = float((self._suptitle_style or {}).get("size", 16))
                content_h += round(size * 1.4) + 8  # h2 line box + top margin
            return doc, content_w, content_h
        return doc, width, height

    def _facecolor_wrapped(self, doc: str) -> str:
        """The figure facecolor behind an HTML document — matplotlib's figure
        patch around the (separately painted, `--chart-bg`) axes plot box."""
        if self._facecolor in ("none", "transparent", "white"):
            return doc
        import html

        fill = html.escape(self._facecolor, quote=True)
        head_end = doc.find("</head>")
        if head_end != -1:
            # Same element specificity as the document's body{background:#fff}
            # rule; later in the head, so it wins.
            return doc[:head_end] + f"<style>body{{background:{fill}}}</style>" + doc[head_end:]
        return f'<div style="background-color:{fill}">{doc}</div>'

    def _repr_html_(self) -> str:
        from xy import export

        doc, width, height = self._to_notebook_html()
        return export.notebook_iframe(self._facecolor_wrapped(doc), width=width, height=height)

    def show(self, *args: Any, **kwargs: Any) -> None:
        import tempfile
        import webbrowser

        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(self._facecolor_wrapped(self._to_html()))
        webbrowser.open(f"file://{f.name}")


class _FigureCanvas:
    """The mpl canvas surface scripts poke: filetypes and draw triggers."""

    def __init__(self, figure: Figure) -> None:
        self.figure = figure

    def get_supported_filetypes(self) -> dict[str, str]:
        return {
            "png": "Portable Network Graphics",
            "svg": "Scalable Vector Graphics",
            "html": "xy interactive HTML",
        }

    def draw(self) -> None:
        self.figure._invalidate()  # the next export re-renders from scratch

    draw_idle = draw


class _SubplotSpec:
    def __init__(self, gridspec: "_GridSpec", rows: tuple[int, int], cols: tuple[int, int]) -> None:
        self.gridspec = gridspec
        self.rows = rows
        self.cols = cols
        self.nrows = gridspec.nrows
        self.ncols = gridspec.ncols

    @property
    def is_single(self) -> bool:
        return self.rows[1] - self.rows[0] == 1 and self.cols[1] - self.cols[0] == 1

    @property
    def index(self) -> int:
        return self.rows[0] * self.ncols + self.cols[0]


# matplotlib's SubplotParams defaults — the frame every gridspec rect lives in.
_SUBPLOT_PARAMS = {"left": 0.125, "right": 0.9, "bottom": 0.11, "top": 0.88}
_SUBPLOT_SPACING = 0.2  # figure.subplot.wspace/hspace default


class _GridSpec:
    """Grid geometry for subplot specs.

    Single cells on default geometry map onto the figure's uniform subplot
    grid; spans and custom spacing resolve to explicit figure rectangles
    (the add_axes path), which every exporter already positions.
    """

    def __init__(self, figure: Optional[Figure], nrows: int, ncols: int, **kwargs: Any) -> None:
        self.figure = figure
        self.nrows = int(nrows)
        self.ncols = int(ncols)
        if self.nrows < 1 or self.ncols < 1:
            raise ValueError("GridSpec must have at least one row and one column")
        geometry_keys = ("left", "bottom", "right", "top", "wspace", "hspace")
        self._geometry = {key: kwargs.pop(key, None) for key in geometry_keys}
        width_ratios = kwargs.pop("width_ratios", None)
        height_ratios = kwargs.pop("height_ratios", None)
        check_unsupported(kwargs, "GridSpec()")
        self._width_ratios = None if width_ratios is None else tuple(map(float, width_ratios))
        self._height_ratios = None if height_ratios is None else tuple(map(float, height_ratios))
        if self._width_ratios is not None and len(self._width_ratios) != self.ncols:
            raise ValueError("width_ratios must match the number of columns")
        if self._height_ratios is not None and len(self._height_ratios) != self.nrows:
            raise ValueError("height_ratios must match the number of rows")

    @property
    def has_custom_geometry(self) -> bool:
        return any(value is not None for value in self._geometry.values())

    @staticmethod
    def _span(key: Any, count: int) -> tuple[int, int]:
        if isinstance(key, slice):
            if key.step not in (None, 1):
                raise not_implemented("GridSpec slicing with a step", "contiguous spans")
            start, stop, _ = key.indices(count)
            if stop <= start:
                raise IndexError("GridSpec slice selects no cells")
            return start, stop
        index = int(key)
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError("GridSpec index out of range")
        return index, index + 1

    def __getitem__(self, key: Any) -> _SubplotSpec:
        if isinstance(key, tuple):
            if len(key) != 2:
                raise IndexError("GridSpec indexes are [row, col]")
            rows = self._span(key[0], self.nrows)
            cols = self._span(key[1], self.ncols)
            return _SubplotSpec(self, rows, cols)
        # Flat row-major indexing; a flat slice spans the bounding box of its
        # first and last cell, matching matplotlib's SubplotSpec corners.
        total = self.nrows * self.ncols
        first, stop = self._span(key, total)
        last = stop - 1
        r0, c0 = divmod(first, self.ncols)
        r1, c1 = divmod(last, self.ncols)
        return _SubplotSpec(self, (min(r0, r1), max(r0, r1) + 1), (min(c0, c1), max(c0, c1) + 1))

    def cell_rect(
        self, rows: tuple[int, int], cols: tuple[int, int]
    ) -> tuple[float, float, float, float]:
        """[left, bottom, width, height] figure fractions for a cell span."""
        # Per-key precedence, as in matplotlib: the gridspec's own geometry,
        # else the figure's (subplots_adjust-moved) SubplotParams, else the
        # rcParams-shaped defaults.
        adjust = self.figure._subplot_adjust if self.figure is not None else {}
        frame = {
            key: (
                self._geometry[key] if self._geometry[key] is not None else adjust.get(key, default)
            )
            for key, default in _SUBPLOT_PARAMS.items()
        }
        wspace = self._geometry["wspace"]
        hspace = self._geometry["hspace"]
        wspace = float(adjust.get("wspace", _SUBPLOT_SPACING)) if wspace is None else float(wspace)
        hspace = float(adjust.get("hspace", _SUBPLOT_SPACING)) if hspace is None else float(hspace)
        span_w = float(frame["right"]) - float(frame["left"])
        span_h = float(frame["top"]) - float(frame["bottom"])
        # wspace/hspace are fractions of the *average* cell size (matplotlib).
        avail_w = span_w / (1.0 + wspace * (self.ncols - 1) / self.ncols)
        avail_h = span_h / (1.0 + hspace * (self.nrows - 1) / self.nrows)
        gap_w = (span_w - avail_w) / (self.ncols - 1) if self.ncols > 1 else 0.0
        gap_h = (span_h - avail_h) / (self.nrows - 1) if self.nrows > 1 else 0.0
        wratios = self._width_ratios or (1.0,) * self.ncols
        hratios = self._height_ratios or (1.0,) * self.nrows
        widths = [avail_w * ratio / sum(wratios) for ratio in wratios]
        heights = [avail_h * ratio / sum(hratios) for ratio in hratios]
        c0, c1 = cols
        r0, r1 = rows
        x0 = float(frame["left"]) + sum(widths[:c0]) + c0 * gap_w
        width = sum(widths[c0:c1]) + (c1 - c0 - 1) * gap_w
        y_top = float(frame["top"]) - (sum(heights[:r0]) + r0 * gap_h)
        height = sum(heights[r0:r1]) + (r1 - r0 - 1) * gap_h
        return (x0, y_top - height, width, height)


class GridSpec(_GridSpec):
    """plt.GridSpec: figure-optional grid geometry with span support."""

    def __init__(
        self, nrows: int, ncols: int, figure: Optional[Figure] = None, **kwargs: Any
    ) -> None:
        super().__init__(figure, nrows, ncols, **kwargs)


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


def _share_mode(value: Any, label: str) -> Any:
    """Normalize matplotlib's sharex/sharey values to False | 'all' | 'row' | 'col'."""
    if value is None or value is False or value == "none":
        return False
    if value is True or value == "all":
        return "all"
    if value in ("row", "col"):
        return value
    raise ValueError(f"{label} must be one of True, False, 'all', 'none', 'row', 'col'")


def apply_sharing(fig: Figure, sharex: Any, sharey: Any) -> None:
    """Share static domains and live pan/zoom ranges across subplot panels."""
    fig._sharex = _share_mode(sharex, "sharex")
    fig._sharey = _share_mode(sharey, "sharey")
