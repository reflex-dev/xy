"""The shim Figure: owns a grid of Axes, savefig/show, notebook display.

Single-axes figures delegate straight to the one chart. Multi-panel figures
compose through `_grid` (CSS-grid HTML, stitched native PNG) — the engine
itself has no grid container; that capability lives entirely in this shim.
"""

from __future__ import annotations

import inspect
import uuid
from os import PathLike
from pathlib import Path
from typing import Any, Literal, Optional, overload

import numpy as np

from .. import _textblock
from ._artists import Legend, Text, _PatchFacade
from ._axes import _DEFAULT_AXES_RECT, Axes, _font_size_points, _plain_text, _scale_values
from ._colors import resolve_color, resolve_rgba
from ._rc import rc_figsize_px, rcParams
from ._transforms import Bbox, CoordinateTransform
from ._translate import check_unsupported, not_implemented

_Chrome = tuple[float, float, float, float]
_ChromeCache = dict[tuple[int, int, int], _Chrome]


class _FigureText(Text):
    """Mutable Text handle whose backing entry is owned by a Figure."""

    def __init__(self, figure: "Figure", role: str, axes: Axes, entry: dict[str, Any]) -> None:
        self._figure = figure
        self._role = role
        super().__init__(axes, entry)

    def _touch(self) -> None:
        self._figure._invalidate()

    def set_text(self, text: str) -> None:
        super().set_text(text)
        setattr(self._figure, f"_sup{self._role}label", str(text))

    def remove(self) -> None:
        setattr(self._figure, f"_sup{self._role}label", None)
        setattr(self._figure, f"_sup{self._role}label_entry", None)
        self._axes._unregister_artist(self)
        self._figure._invalidate()


def _panel_chrome(
    ax: Axes,
    plot_w: int,
    *,
    cache: Optional[_ChromeCache] = None,
) -> _Chrome:
    """``(left, top, right, bottom)`` px of chrome around a free-form panel.

    One definition for the whole absolute-placement path: `_charts` sizes the
    panel with it, `_panel_positions` places the panel with it, and
    `Axes._frame_padding` pins the plot rect inside the panel with it. When
    those three disagree the plot box drifts off its gridspec cell.

    The chrome includes the gutters the renderers reserve outside the padding —
    the axes title, a top-side x axis (`matshow`), the secondary-y band — so the
    panel is always large enough to hold them without moving the plot rect. The
    title is the case matplotlib makes obvious: it draws above the axes without
    changing its position.
    """
    figure = ax.figure
    probe_h = 0
    cache_key: Optional[tuple[int, int, int]] = None
    if figure is not None:
        _canvas_w, canvas_h = rc_figsize_px(figure._figsize, figure._dpi)
        probe_h = max(120, round(canvas_h / max(1, figure._nrows)))
        cache_key = (id(ax), int(plot_w), probe_h)
        if cache is not None and cache_key in cache:
            return cache[cache_key]
    compact = plot_w + 54 < 520
    left, top = (46.0, 6.0) if compact else (62.0, 10.0)
    right, bottom = (8.0, 36.0) if compact else (14.0, 42.0)
    y_props = ax._axis["y"]
    y_style = y_props.get("style") or {}
    y_labels = y_props.get("tick_labels") or ()
    if y_labels and y_props.get("tick_label_strategy") not in {"none", "off"}:
        tick_size = float(y_style.get("tick_label_size", y_style.get("tick_size", 11.0)))
        tick_angle = float(y_props.get("tick_label_angle", 0.0))
        tick_width = max(
            _textblock.rotated_extent(_textblock.measure(label, tick_size), tick_angle)[0]
            for label in y_labels
        )
        tick_length = max(0.0, float(y_style.get("tick_length", 0.0)))
        direction = str(y_style.get("tick_direction", "out"))
        outward = (
            0.0 if direction == "in" else tick_length / 2.0 if direction == "inout" else tick_length
        )
        tick_offset = outward + max(0.0, float(y_style.get("tick_padding", 4.0)))
        needed = 4.0 + tick_offset + tick_width
        if y_props.get("label"):
            label_size = float(y_style.get("label_size", 12.0))
            needed += (
                float(y_props.get("label_offset", 0.4 * label_size))
                + _textblock.measure(y_props["label"], label_size).height
            )
        left = max(left, needed)
    extra_top, extra_right, extra_bottom = ax._outside_padding(compact)
    table_bottom = ax._table_bottom_points * ax._point_scale()
    defaults = (
        left,
        top + extra_top,
        right + extra_right,
        max(bottom + extra_bottom, table_bottom),
    )
    if figure is None:
        return defaults
    measured = _measured_axis_chrome(
        ax,
        max(120, round(plot_w + defaults[0] + defaults[2])),
        probe_h,
    )
    resolved: _Chrome = (
        max(defaults[0], measured[0]),
        max(defaults[1], measured[1]),
        max(defaults[2], measured[2]),
        max(defaults[3], measured[3]),
    )
    if cache is not None and cache_key is not None:
        cache[cache_key] = resolved
    return resolved


def _measured_left_gutter(ax: Axes, width: int, height: int) -> float:
    """The left gutter `_svg.layout()` will reserve for `ax`'s y-axis text.

    Probes the real spec because the reservation is measured from the tick
    labels the resolved range produces, which only exist after the payload is
    built. The probe costs one extra payload build on the notebook display path;
    the browser needs the number *before* the chart it renders is built, and a
    second implementation of the measurement is the thing this must not become.
    """
    from .. import _svg

    spec = _probe_axis_spec(ax, width, height)
    return float(_svg.layout(spec)[3]["x"])


def _probe_axis_spec(ax: Axes, width: int, height: int) -> dict[str, Any]:
    """Build a provisional spec without retaining probe-dependent axis state."""
    previous_chart = ax._chart
    missing = object()
    previous_plot_px = getattr(ax, "_materialize_plot_px", missing)
    twin = ax._twin
    previous_twin_plot_px = (
        getattr(twin, "_materialize_plot_px", missing) if twin is not None else missing
    )
    # Preserve the dictionaries themselves because shared axes may alias them.
    # `_build_chart()` can materialize equal-aspect domains from the provisional
    # width/height; those values must not leak into the final panel build.
    snapshots: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[int] = set()
    for props in ax._axis.values():
        if id(props) not in seen:
            snapshots.append((props, dict(props)))
            seen.add(id(props))
    ax._chart = None
    try:
        spec, _buffers = ax._build_chart(width, height).figure().build_payload_split()
        return spec
    finally:
        ax._chart = previous_chart
        for props, snapshot in snapshots:
            props.clear()
            props.update(snapshot)
        if previous_plot_px is missing:
            if hasattr(ax, "_materialize_plot_px"):
                del ax._materialize_plot_px
        else:
            ax._materialize_plot_px = previous_plot_px
        if twin is not None:
            if previous_twin_plot_px is missing:
                if hasattr(twin, "_materialize_plot_px"):
                    del twin._materialize_plot_px
            else:
                twin._materialize_plot_px = previous_twin_plot_px


def _measured_axis_chrome(ax: Axes, width: int, height: int) -> tuple[float, float, float, float]:
    """Intrinsic ``(left, top, right, bottom)`` chrome for final axes content.

    Tight/constrained layout needs the labels after plotting and styling have
    finished. Build one provisional payload, remove its figure-rectangle
    padding, and ask the same layout resolver used by PNG/SVG for the actual
    text reservation. The later layout adjustment invalidates this provisional
    chart before any output consumes it.
    """
    from .. import _svg

    spec = _probe_axis_spec(ax, width, height)
    intrinsic = dict(spec)
    intrinsic.pop("padding", None)
    measured_width, measured_height, _compact, plot = _svg.layout(intrinsic)
    return (
        float(plot["x"]),
        float(plot["y"]),
        float(measured_width - plot["x"] - plot["w"]),
        float(measured_height - plot["y"] - plot["h"]),
    )


def _contour_colorbar_lines(contour: Any, host: Axes) -> list[dict[str, Any]]:
    """Serialize a ContourSet's visible isoline styles for colorbar chrome."""
    from ._artists import _contour_legend_colors

    levels = np.asarray(contour.levels, dtype=np.float64).reshape(-1)
    widths = np.asarray(contour.get_linewidth(), dtype=np.float64).reshape(-1)
    colors = _contour_legend_colors(contour._entry, len(levels))
    return [
        {
            "value": float(level),
            "color": colors[index],
            "width": float(widths[index % len(widths)]) * host._point_scale(),
            "dash": (
                "dashed" if contour._entry["kwargs"].get("dash_negative") and level < 0 else None
            ),
        }
        for index, level in enumerate(levels)
    ]


def _colorbar_tick_labels(formatter: Any, ticks: list[float]) -> list[str]:
    """Evaluate one colorbar formatter against the exact serialized ticks."""

    labels: list[str] = []
    for position, value in enumerate(ticks):
        if isinstance(formatter, str):
            if "{" in formatter:
                rendered = formatter.format(x=value, pos=position)
            elif "%" in formatter:
                rendered = formatter % value
            else:
                rendered = format(value, formatter)
        elif callable(formatter):
            try:
                rendered = formatter(value, position)
            except TypeError:
                rendered = formatter(value)
        else:
            raise TypeError("colorbar() format must be a format string or callable formatter")
        labels.append(_plain_text(str(rendered)))
    return labels


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
        self.patch = _PatchFacade(self)
        self._suptitle: Optional[str] = None
        self._suptitle_style: dict[str, Any] = {}
        self._supxlabel: Optional[str] = None
        self._supylabel: Optional[str] = None
        self._supxlabel_entry: Optional[dict[str, Any]] = None
        self._supylabel_entry: Optional[dict[str, Any]] = None
        self._figure_legend: Optional[dict[str, Any]] = None
        self._figure_legend_handle: Optional[Legend] = None
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
        self._layout_dirty = False
        self._applying_layout = False
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
        if self._layout_options.get("engine") == "tight" and not self._applying_layout:
            self._layout_dirty = True

    @property
    def canvas(self) -> "_FigureCanvas":
        return _FigureCanvas(self)

    def add_subplot(self, *args: Any, **kwargs: Any) -> Axes:
        if not args:
            args = (111,)
        if len(args) == 1 and isinstance(args[0], _SubplotSpec):
            spec = args[0]
            subplot_key = ("grid", spec.nrows, spec.ncols, spec.index)
            if spec.is_single and not spec.gridspec.has_custom_geometry:
                self._ensure_grid(spec.nrows, spec.ncols)
                ax = self._claim_or_create_subplot(subplot_key, spec.index)
            else:
                # Spans and custom spacing become explicit figure rectangles.
                # The spec is kept so subplots_adjust() can re-resolve them.
                ax = self.add_axes(spec.gridspec.cell_rect(spec.rows, spec.cols))
                # add_axes() models unrelated free-form panels as a 1×N row.
                # A GridSpec-backed span still belongs to its original grid;
                # retain that geometry for tight_layout/subplots_adjust.
                self._nrows, self._ncols = spec.nrows, spec.ncols
                ax._subplot_spec = spec
                ax._subplot_key = (
                    "gridspec",
                    id(spec.gridspec),
                    spec.rows,
                    spec.cols,
                )
                ax._subplot_claimed = True
        else:
            nrows, ncols, index = _parse_subplot_args(args)
            subplot_key = ("grid", nrows, ncols, index - 1)
            if any(a._figure_rect is not None for a in self._axes):
                # matplotlib mixes numbered subplots into figures that already
                # hold free-form axes; keep the figure free-form via the cell
                # rectangle. Figure.add_subplot() deliberately does not reuse
                # an existing match; pyplot.subplot() owns activation/reuse.
                row, col = divmod(index - 1, ncols)
                grid = _GridSpec(self, nrows, ncols)
                rect = grid.cell_rect((row, row + 1), (col, col + 1))
                ax = self.add_axes(rect)
                ax._subplot_spec = _SubplotSpec(grid, (row, row + 1), (col, col + 1))
                ax._subplot_key = subplot_key
                ax._subplot_claimed = True
            else:
                self._ensure_grid(nrows, ncols)
                ax = self._claim_or_create_subplot(subplot_key, index - 1)
        self._current_ax = ax  # matplotlib: add_subplot activates the axes
        sharex = kwargs.pop("sharex", None)
        sharey = kwargs.pop("sharey", None)
        self._share_subplot_axes(ax, sharex=sharex, sharey=sharey)
        if kwargs:
            ax.set(**kwargs)
        return ax

    @staticmethod
    def _share_subplot_axes(ax: Axes, *, sharex: Any = None, sharey: Any = None) -> None:
        """Wire construction-only subplot sharing without routing it through ``Axes.set``."""
        if sharex is not None:
            ax._axis["x"] = sharex._axis_props("x")  # static share, as in twiny()
        if sharey is not None:
            ax._axis["y"] = sharey._axis_props("y")
        if sharex is not None or sharey is not None:
            ax._invalidate()

    def _claim_or_create_subplot(self, key: tuple[Any, ...], index: int) -> Axes:
        """Claim a grid placeholder or append a same-spec overlay axes."""
        for candidate in self._axes:
            if candidate._subplot_key == key and not candidate._subplot_claimed:
                candidate._subplot_claimed = True
                return candidate
        ax = Axes(self)
        ax._subplot_index = index
        ax._subplot_key = key
        ax._subplot_claimed = True
        self._axes.append(ax)
        return ax

    def activate_subplot(self, *args: Any, **kwargs: Any) -> Axes:
        """Activate a matching subplot, creating it only when absent."""
        if not args:
            args = (111,)
        if len(args) == 1 and isinstance(args[0], _SubplotSpec):
            spec = args[0]
            if spec.is_single and not spec.gridspec.has_custom_geometry:
                key: tuple[Any, ...] = ("grid", spec.nrows, spec.ncols, spec.index)
            else:
                key = ("gridspec", id(spec.gridspec), spec.rows, spec.cols)
        else:
            nrows, ncols, index = _parse_subplot_args(args)
            key = ("grid", nrows, ncols, index - 1)
        existing = next(
            (ax for ax in self._axes if ax._subplot_claimed and ax._subplot_key == key),
            None,
        )
        if existing is None:
            return self.add_subplot(*args, **kwargs)
        self._current_ax = existing
        sharex = kwargs.pop("sharex", None)
        sharey = kwargs.pop("sharey", None)
        self._share_subplot_axes(existing, sharex=sharex, sharey=sharey)
        if kwargs:
            existing.set(**kwargs)
        return existing

    def add_axes(self, rect: Any, **kwargs: Any) -> Axes:
        parsed = tuple(float(value) for value in rect)
        if len(parsed) != 4 or any(value < 0 for value in parsed[2:]):
            raise ValueError("add_axes rect must be [left, bottom, width, height]")
        ax = Axes(self)
        self._axes.append(ax)
        ax._figure_rect = parsed
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
        grid_options = dict(gridspec_kw or {})
        width_ratios = grid_options.pop("width_ratios", width_ratios)
        height_ratios = grid_options.pop("height_ratios", height_ratios)
        grid = _GridSpec(
            self,
            int(nrows),
            int(ncols),
            width_ratios=width_ratios,
            height_ratios=height_ratios,
            **grid_options,
        )
        axes = make_axes_grid(self, int(nrows), int(ncols), squeeze=squeeze)
        self._width_ratios = grid._width_ratios
        self._height_ratios = grid._height_ratios
        if grid.has_custom_geometry:
            for index, ax in enumerate(self._axes):
                row, col = divmod(index, int(ncols))
                spec = _SubplotSpec(grid, (row, row + 1), (col, col + 1))
                ax._subplot_spec = spec
                ax._figure_rect = grid.cell_rect(spec.rows, spec.cols)
        apply_sharing(self, _share_mode(sharex, "sharex"), _share_mode(sharey, "sharey"))
        self._hide_inner_tick_labels(int(nrows), int(ncols))
        self._invalidate()
        return axes

    def _hide_inner_tick_labels(self, nrows: int, ncols: int) -> None:
        """Matplotlib's shared-axes rule: only edge panels keep tick labels."""
        for index, ax in enumerate(self._axes):
            row, col = index // ncols, index % ncols
            if self._sharex in ("all", "col") and row < nrows - 1:
                ax._apply_tick_label_side_visibility("x", {"labelbottom": False})
            if self._sharey in ("all", "row") and col > 0:
                ax._apply_tick_label_side_visibility("y", {"labelleft": False})

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
        reshaping = (nrows, ncols) != (self._nrows, self._ncols)
        if reshaping and self._axes and any(ax._entries for ax in self._axes):
            raise ValueError("cannot reshape a figure that already has plotted axes")
        self._nrows, self._ncols = nrows, ncols
        if reshaping:
            for index, ax in enumerate(self._axes):
                if ax._figure_rect is None:
                    ax._subplot_index = index
                    ax._subplot_key = ("grid", nrows, ncols, index)
        for index in range(nrows * ncols):
            key = ("grid", nrows, ncols, index)
            if any(ax._subplot_key == key for ax in self._axes):
                continue
            ax = Axes(self)
            ax._subplot_index = index
            ax._subplot_key = key
            self._axes.append(ax)

    def _axes_at(self, index: int) -> Axes:
        self._ensure_grid(self._nrows, self._ncols)
        key = ("grid", self._nrows, self._ncols, index)
        for ax in self._axes:
            if ax._subplot_key == key:
                return ax
        raise IndexError(index)

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
        self._supxlabel_entry = None
        self._supylabel_entry = None
        self._figure_legend = None
        self._figure_legend_handle = None
        self._shared_colorbar = None
        self._gci = None
        self._width_ratios = None
        self._height_ratios = None
        self._layout_options = {}
        self._layout_dirty = False
        self._applying_layout = False
        self._subplot_adjust = {}
        self._invalidate()

    clf = clear

    # -- chrome ---------------------------------------------------------------

    def suptitle(self, title: str, **kwargs: Any) -> None:
        size = kwargs.pop("fontsize", kwargs.pop("size", "large"))
        weight = kwargs.pop("fontweight", kwargs.pop("weight", "normal"))
        family = kwargs.pop("fontfamily", kwargs.pop("family", "system-ui, sans-serif"))
        # Figure titles are Text artists in Matplotlib: snapshot the active
        # text default when authored, rather than hard-coding the light-theme
        # paint or consulting rcParams later during export.
        color = kwargs.pop("color", None)
        if color is None:
            color = rcParams["text.color"]
        x = kwargs.pop("x", 0.5)
        y = kwargs.pop("y", 0.98)
        ha = kwargs.pop("ha", kwargs.pop("horizontalalignment", "center"))
        va = kwargs.pop("va", kwargs.pop("verticalalignment", "top"))
        if kwargs:
            raise TypeError(f"suptitle() got unsupported keyword argument {next(iter(kwargs))!r}")
        self._suptitle = _plain_text(title)
        self._suptitle_style = {
            "size": _font_size_points(size, rcParams["font.size"]),
            "weight": str(weight),
            "family": str(family),
            "color": str(color),
            "x": float(x),
            "y": float(y),
            "ha": str(ha),
            "va": str(va),
        }
        if self._layout_options.get("engine") == "tight":
            # Constrained/tight figures compose the suptitle outside the
            # per-panel chart chrome. Reserve a title row in the same pass
            # that already reserves tick and Axes-title chrome; otherwise a
            # one-row gallery places all three titles on the same baseline.
            prior = self._layout_options
            if prior.get("rect") is None:
                prior["rect"] = (0.0, 0.0, 1.0, 0.9)
                prior["suptitle_rect_reserved"] = True
        self._invalidate()

    def _resolved_suptitle_style(self) -> dict[str, Any]:
        """Resolve Matplotlib's point-sized title style for this output DPI."""
        style = dict(self._suptitle_style)
        style["size"] = float(style.get("size", 12.0)) * self.get_dpi() / 72.0
        return style

    def supxlabel(self, label: str, **kwargs: Any) -> Text:
        x = float(kwargs.pop("x", 0.5))
        y = float(kwargs.pop("y", 0.01))
        entry = self._figure_label_entry(
            x,
            y,
            label,
            ha=kwargs.pop("ha", kwargs.pop("horizontalalignment", "center")),
            va=kwargs.pop("va", kwargs.pop("verticalalignment", "bottom")),
            rotation=kwargs.pop("rotation", 0.0),
            kwargs=kwargs,
        )
        self._supxlabel = str(label)
        self._supxlabel_entry = entry
        self._invalidate()
        return _FigureText(self, "x", self.gca(), entry)

    def supylabel(self, label: str, **kwargs: Any) -> Text:
        x = float(kwargs.pop("x", 0.02))
        y = float(kwargs.pop("y", 0.5))
        entry = self._figure_label_entry(
            x,
            y,
            label,
            ha=kwargs.pop("ha", kwargs.pop("horizontalalignment", "left")),
            va=kwargs.pop("va", kwargs.pop("verticalalignment", "center")),
            rotation=kwargs.pop("rotation", 90.0),
            kwargs=kwargs,
        )
        self._supylabel = str(label)
        self._supylabel_entry = entry
        self._invalidate()
        return _FigureText(self, "y", self.gca(), entry)

    def _figure_label_entry(
        self,
        x: float,
        y: float,
        label: str,
        *,
        ha: Any,
        va: Any,
        rotation: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        size = kwargs.pop("fontsize", kwargs.pop("size", rcParams["figure.labelsize"]))
        weight = kwargs.pop("fontweight", kwargs.pop("weight", rcParams["figure.labelweight"]))
        family = kwargs.pop("fontfamily", kwargs.pop("family", "system-ui, sans-serif"))
        color = kwargs.pop("color", rcParams["text.color"])
        fontstyle = kwargs.pop("fontstyle", kwargs.pop("style", "normal"))
        if kwargs:
            raise TypeError(f"figure label got unsupported keyword argument {next(iter(kwargs))!r}")
        angle = 90.0 if rotation == "vertical" else float(rotation)
        return {
            "kind": "@text",
            "args": (x, y, _plain_text(label)),
            "kwargs": {
                "anchor": {"left": "start", "center": "middle", "right": "end"}.get(
                    str(ha), "middle"
                ),
                "color": resolve_color(color) or "black",
                "style": {
                    "coordinate_space": "figure_fraction",
                    "vertical_align": str(va),
                    "font_size": _font_size_points(size, rcParams["font.size"]),
                    "font_weight": str(weight),
                    "font_family": str(family),
                    "font_style": str(fontstyle),
                    "rotation": angle,
                },
            },
        }

    def _resolved_figure_labels(self) -> list[dict[str, Any]]:
        labels = []
        point_scale = self.get_dpi() / 72.0
        for role, entry in (
            ("x", self._supxlabel_entry),
            ("y", self._supylabel_entry),
        ):
            if entry is None:
                continue
            x, y, text = entry["args"]
            kwargs = entry["kwargs"]
            style = kwargs.get("style") or {}
            labels.append(
                {
                    "role": role,
                    "text": str(text),
                    "x": float(x),
                    "y": float(y),
                    "anchor": kwargs.get("anchor", "middle"),
                    "vertical_align": style.get("vertical_align", "center"),
                    "rotation": float(style.get("rotation", 0.0)),
                    "size": float(style.get("font_size", rcParams["font.size"])) * point_scale,
                    "weight": str(style.get("font_weight", "normal")),
                    "family": str(style.get("font_family", "system-ui, sans-serif")),
                    "font_style": str(style.get("font_style", "normal")),
                    "color": str(kwargs.get("color", "black")),
                    "opacity": float(kwargs.get("opacity", 1.0)),
                }
            )
        return labels

    def text(
        self,
        x: Any,
        y: Any,
        s: str,
        fontdict: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Text:
        return self.gca().text(x, y, s, fontdict=fontdict, transform=self.transFigure, **kwargs)

    def legend(self, *args: Any, **kwargs: Any) -> Legend:
        """Create one figure-level legend aggregated across all axes."""
        if len(args) > 2:
            raise TypeError("Figure.legend() accepts at most handles and labels")
        axes = self.axes or [self.gca()]
        detected_handles: list[Any] = []
        detected_labels: list[str] = []
        for ax in axes:
            handles, labels = ax.get_legend_handles_labels()
            detected_handles.extend(handles)
            detected_labels.extend(labels)
        if len(args) >= 2:
            handles, labels = list(args[0]), list(args[1])
        elif len(args) == 1:
            handles, labels = detected_handles, list(args[0])
        else:
            handles = list(kwargs.pop("handles", detected_handles))
            labels = list(kwargs.pop("labels", detected_labels))
        loc = kwargs.pop("loc", "upper right")
        figure_loc = str(loc)
        if figure_loc.startswith("outside "):
            if figure_loc != "outside right upper":
                raise not_implemented(
                    f"Figure.legend(loc={figure_loc!r})",
                    "loc='outside right upper'",
                )
            loc = "upper left"
        legend = Legend(axes[0], handles, labels, loc=loc, **kwargs)
        self._figure_legend_handle = legend
        self._figure_legend = {
            **legend.spec(),
            "figure_loc": figure_loc,
        }
        self._invalidate()
        return legend

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
        # Defer the solve until geometry is queried or an output is built.
        # Figure factories receive layout= before callers add marks/labels;
        # solving there permanently bakes an empty-axes rectangle.
        self._layout_dirty = True
        self._invalidate()
        # Preserve Matplotlib's observable call semantics for code that reads
        # axes positions immediately. Later content/style mutations mark the
        # request dirty again, so factory-authored tight/constrained layout is
        # still re-solved from final content at render time.
        self._ensure_layout()

    def _ensure_layout(self, chrome_cache: Optional[_ChromeCache] = None) -> None:
        if not self._layout_dirty or self._applying_layout:
            return
        self._applying_layout = True
        try:
            self._apply_tight_layout(chrome_cache)
        finally:
            self._applying_layout = False

    def _apply_tight_layout(self, chrome_cache: Optional[_ChromeCache] = None) -> None:
        options = self._layout_options
        pad = options.get("pad")
        h_pad = options.get("h_pad")
        w_pad = options.get("w_pad")
        rect = options.get("rect")
        # The native panels carry their own tick/title chrome, while the
        # GridSpec rectangles describe plot boxes only.  Reserve enough
        # figure-edge and inter-panel room for that chrome so adjacent panels
        # do not overlap.  This is the same job Matplotlib's tight-layout
        # engine performs from artist extents; the shim uses its deterministic
        # renderer margins instead of a second text-layout engine.
        if self._axes and not any(
            ax._figure_rect is not None and ax._subplot_spec is None and ax._subplot_index is None
            for ax in self._axes
        ):
            canvas_w, canvas_h = rc_figsize_px(self._figsize, self._dpi)
            compact = canvas_w / max(1, self._ncols) < 520
            nominal_plot_w = max(40, round(canvas_w / max(1, self._ncols)))
            chrome = [_panel_chrome(ax, nominal_plot_w, cache=chrome_cache) for ax in self._axes]
            # A lone row/column lets `_charts()` steal automatic-colorbar room
            # from the source axes. In a grid, the same chrome must instead
            # participate in the inter-panel solve or neighboring colorbars
            # overlap. `_tight_layout_colorbar_reservations()` detects that
            # pre-reserved grid geometry and prevents a second subtraction.
            resolved_chrome = []
            for ax, (left, top, right, bottom) in zip(self._axes, chrome, strict=True):
                automatic = ax._colorbar is not None and ax._colorbar.get("placement") != "axes"
                colorbar_right, colorbar_bottom = (
                    ax._colorbar_outside_room(compact) if automatic else (0.0, 0.0)
                )
                resolved_chrome.append(
                    (
                        left,
                        top,
                        right if self._ncols > 1 else max(0.0, right - colorbar_right),
                        bottom if self._nrows > 1 else max(0.0, bottom - colorbar_bottom),
                    )
                )
            chrome = resolved_chrome
            left_px = max((item[0] for item in chrome), default=46.0 if compact else 62.0)
            right_px = max(
                20.0 if compact else 26.0,
                max((item[2] for item in chrome), default=0.0),
            )
            bottom_px = max((item[3] for item in chrome), default=36.0 if compact else 42.0)
            top_px = max(20.0, max((item[1] for item in chrome), default=0.0))

            horizontal_gap = 58.0 if compact else 76.0
            vertical_gap = 44.0 if compact else 56.0
            for index, (ax, item) in enumerate(zip(self._axes, chrome, strict=True)):
                spec = ax._subplot_spec
                if spec is None:
                    row, col = divmod(index, max(1, self._ncols))
                    rows, cols = (row, row + 1), (col, col + 1)
                else:
                    rows, cols = spec.rows, spec.cols
                for other_index, other_ax in enumerate(self._axes):
                    if index == other_index:
                        continue
                    other_spec = other_ax._subplot_spec
                    if other_spec is None:
                        other_row, other_col = divmod(other_index, max(1, self._ncols))
                        other_rows = (other_row, other_row + 1)
                        other_cols = (other_col, other_col + 1)
                    else:
                        other_rows, other_cols = other_spec.rows, other_spec.cols
                    rows_overlap = max(rows[0], other_rows[0]) < min(rows[1], other_rows[1])
                    cols_overlap = max(cols[0], other_cols[0]) < min(cols[1], other_cols[1])
                    if rows_overlap and cols[1] == other_cols[0]:
                        horizontal_gap = max(
                            horizontal_gap,
                            item[2] + chrome[other_index][0],
                        )
                    if cols_overlap and rows[1] == other_rows[0]:
                        vertical_gap = max(
                            vertical_gap,
                            item[3] + chrome[other_index][1],
                        )

            if self._suptitle and not options.get("suptitle_rect_reserved"):
                style = self._resolved_suptitle_style()
                block = _textblock.measure(self._suptitle, float(style.get("size", 16.0)))
                y = float(style.get("y", 0.98))
                suptitle_bottom = max(0.0, (1.0 - y) * canvas_h) + block.height
                top_px += suptitle_bottom + 6.0
            for label in self._resolved_figure_labels():
                if label["role"] == "x":
                    bottom_px += float(label["size"]) + 8.0
                else:
                    left_px += float(label["size"]) + 8.0
            if (
                self._figure_legend
                and self._figure_legend.get("items")
                and self._figure_legend.get("figure_loc") == "outside right upper"
            ):
                from .._svg import _legend_layout

                measured = _legend_layout(
                    list(self._figure_legend.get("items") or []),
                    {"x": 0.0, "y": 0.0, "w": float(canvas_w), "h": float(canvas_h)},
                    {**self._figure_legend, "loc": "upper left"},
                )
                right_px += float(measured["box_w"]) + 12.0
            # Explicit *_pad values are font-size multiples in Matplotlib.
            point_px = float(rcParams["font.size"]) * float(self._dpi or 100.0) / 72.0
            base_pad = 1.08 if pad is None else float(pad)
            if w_pad is not None:
                horizontal_gap += (float(w_pad) - base_pad) * point_px
            if h_pad is not None:
                vertical_gap += (float(h_pad) - base_pad) * point_px
            if pad is not None:
                extra = (float(pad) - 1.08) * point_px
                left_px += extra
                right_px += extra
                bottom_px += extra
                top_px += extra

            frame = (0.0, 0.0, 1.0, 1.0) if rect is None else tuple(map(float, rect))
            if len(frame) != 4:
                raise ValueError("tight_layout(rect=...) must be [left, bottom, right, top]")
            frame_left, frame_bottom, frame_right, frame_top = frame
            left = frame_left + max(0.0, left_px) / canvas_w
            right = frame_right - max(0.0, right_px) / canvas_w
            bottom = frame_bottom + max(0.0, bottom_px) / canvas_h
            top = frame_top - max(0.0, top_px) / canvas_h
            inner_w = max(1.0, (right - left) * canvas_w)
            inner_h = max(1.0, (top - bottom) * canvas_h)
            cell_w = max(
                1.0,
                (inner_w - horizontal_gap * max(0, self._ncols - 1)) / max(1, self._ncols),
            )
            cell_h = max(
                1.0,
                (inner_h - vertical_gap * max(0, self._nrows - 1)) / max(1, self._nrows),
            )
            self.subplots_adjust(
                left=left,
                right=right,
                bottom=bottom,
                top=top,
                wspace=horizontal_gap / cell_w,
                hspace=vertical_gap / cell_h,
            )
        self._layout_dirty = False
        self._html_cache = None

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
        grid = _GridSpec(
            self,
            self._nrows,
            self._ncols,
            width_ratios=self._width_ratios,
            height_ratios=self._height_ratios,
        )
        for ax in self._axes:
            if ax._subplot_spec is not None:
                # Gridspec-derived rectangles track the moved SubplotParams
                # frame (matplotlib re-resolves subplot positions on draw).
                spec = ax._subplot_spec
                ax._figure_rect = spec.gridspec.cell_rect(spec.rows, spec.cols)
            elif ax._subplot_index is not None:
                # Matplotlib's subplots_adjust() restores a subplot whose
                # position was set explicitly to its SubplotSpec cell.
                row, col = divmod(ax._subplot_index, self._ncols)
                ax._figure_rect = grid.cell_rect((row, row + 1), (col, col + 1))
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
        if mappable is None:
            mappable = self._gci
        axes_arg = ax
        source_axes = getattr(mappable, "_axes", None) or self.gca()
        axes = cax if cax is not None else source_axes
        if cax is not None and cax not in self._axes:
            raise ValueError("colorbar cax must belong to this figure")
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
        explicit_domain = entry.get("_mpl_domain", entry.get("domain", props.get("domain")))
        norm_scale = str(entry.get("_mpl_norm_scale", props.get("_mpl_norm_scale", "linear")))
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
        spacing = str(kwargs.pop("spacing", "uniform")).lower()
        if spacing not in {"uniform", "proportional"}:
            raise ValueError("colorbar() spacing must be 'uniform' or 'proportional'")
        formatter = kwargs.pop("format", None)
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
        }
        if spacing != "uniform":
            options["spacing"] = spacing
        line_contour = entry.get("factory") == "contour" and not props.get("filled", False)
        if line_contour:
            # Matplotlib's line-contour colorbar is an empty bar crossed by the
            # ContourSet's own styled isolines; it is not a filled scalar ramp.
            options["line_only"] = True
            options["lines"] = _contour_colorbar_lines(mappable, source_axes)
        if norm_scale != "linear":
            options["scale"] = norm_scale
        pad = kwargs.pop("pad", None)
        if pad is not None:
            pad_value = float(pad)
            if not np.isfinite(pad_value) or pad_value < 0.0:
                raise ValueError("colorbar() pad must be a finite nonnegative number")
            options["pad"] = pad_value
        if cax is not None:
            options["placement"] = "axes"
        if shrink != 1.0:
            options["shrink"] = shrink
        if not np.array_equal(anchor_values, [0.5, 0.5]):
            options["anchor"] = [float(anchor_values[0]), float(anchor_values[1])]
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
        elif line_contour:
            locations = np.asarray(mappable.levels, dtype=np.float64).reshape(-1)
            step = max(1, int(np.ceil(len(locations) / 10)))
            candidates = [locations[offset::step] for offset in range(step)]
            selected = min(candidates, key=lambda values: np.min(np.abs(values)))
            zero_tolerance = (
                np.finfo(np.float64).eps * max(1.0, float(np.max(np.abs(locations)))) * 8
            )
            options["ticks"] = [
                0.0 if abs(float(value)) <= zero_tolerance else float(value) for value in selected
            ]
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
        if formatter is not None:
            if "ticks" not in options:
                raise not_implemented(
                    "colorbar(format=...) without fixed ticks",
                    "format= together with ticks= or a discrete mappable",
                )
            options["tick_labels"] = _colorbar_tick_labels(formatter, options["ticks"])
        extend = kwargs.pop("extend", None)
        if extend is None:
            # A contour set owns its extend state. Matplotlib colorbars inherit
            # it unless the caller explicitly overrides ``extend=``; losing it
            # drops the triangular end caps and misstates the mapped domain.
            extend = props.get("extend", entry.get("extend", "neither"))
        if extend is not None:
            if extend not in ("neither", "min", "max", "both"):
                raise ValueError("colorbar() extend must be 'neither', 'min', 'max', or 'both'")
            if extend != "neither":
                options["extend"] = str(extend)

        def rgb255(value: Any) -> list[int]:
            rgba = np.asarray(resolve_rgba(value), dtype=np.float64)
            return [int(round(255.0 * channel)) for channel in rgba[:3]]

        # Listed contour fills already carry their exact per-band RGBA table.
        # Keep that table on the colorbar instead of replacing it with samples
        # from the nominal fallback colormap. Extended rows own the cap colors.
        color_table = props.get("color")
        discrete_colors = entry.get("discrete_colors")
        if levels is not None and discrete_colors is not None:
            band_rows = np.asarray(discrete_colors, dtype=np.uint8)
            if band_rows.shape == (int(levels), 3):
                options["band_colors"] = band_rows.tolist()
        if levels is not None and color_table is not None and not isinstance(color_table, str):
            table = np.asarray(color_table, dtype=np.float64)
            if table.ndim == 2 and table.shape[1] in (3, 4) and len(table):
                rgb_table = np.rint(np.clip(table[:, :3], 0.0, 1.0) * 255.0).astype(int)
                extend_min = extend in ("min", "both")
                extend_max = extend in ("max", "both")
                band_count = int(levels)
                start = int(extend_min and len(rgb_table) >= band_count + 1 + int(extend_max))
                band_rows = rgb_table[start : start + band_count]
                if len(band_rows) == band_count:
                    options["band_colors"] = band_rows.tolist()
                if extend_min:
                    options["under_color"] = rgb_table[0].tolist()
                if extend_max:
                    options["over_color"] = rgb_table[-1].tolist()
        if extend in ("min", "both") and entry.get("cmap_under") is not None:
            options["under_color"] = rgb255(entry["cmap_under"])
        if extend in ("max", "both") and entry.get("cmap_over") is not None:
            options["over_color"] = rgb255(entry["cmap_over"])

        check_unsupported(kwargs, "colorbar()")
        if (
            cax is None
            and not isinstance(axes_arg, (list, tuple, np.ndarray))
            and source_axes._colorbar is not None
        ):
            # The wire format intentionally keeps one colorbar per chart. A
            # second Matplotlib colorbar therefore becomes an ordinary
            # explicit colorbar axes, a path every renderer already supports.
            # This preserves both bars without widening the core chart schema.
            left, bottom, parent_width, parent_height = source_axes.get_position().bounds
            canvas_width, canvas_height = rc_figsize_px(self._figsize, self._dpi)
            anchor_x, anchor_y = map(float, anchor_values)
            if orientation == "horizontal":
                bar_width = parent_width * shrink
                bar_left = left + (parent_width - bar_width) * anchor_x
                bar_height = max(18.0 / canvas_height, 0.025)
                bar_bottom = max(0.01, bottom - bar_height)
                rect = (bar_left, bar_bottom, bar_width, bar_height)
            else:
                bar_height = parent_height * shrink
                bar_bottom = bottom + (parent_height - bar_height) * anchor_y
                bar_width = max(18.0 / canvas_width, 0.025)
                rect = (
                    min(0.99 - bar_width, left + parent_width + 24.0 / canvas_width),
                    bar_bottom,
                    bar_width,
                    bar_height,
                )
            cax = self.add_axes(rect)
            self._current_ax = source_axes
            axes = cax
            options["placement"] = "axes"
        if cax is not None:
            axes.set_axis_off()
            axes.spines[:].set_visible(False)
            axes._colorbar = options
            axes._colorbar_source = entry if entry else None
            axes._invalidate()
        elif isinstance(axes_arg, (list, tuple, np.ndarray)):
            self._shared_colorbar = options
            self._invalidate()
        else:
            axes._colorbar = options
            axes._colorbar_source = entry if entry else None
            axes._invalidate()

        class _ColorbarAxes:
            """Minimal colorbar-axes facade backed by the chrome options.

            A colorbar is renderer chrome in xy rather than a data-bearing
            Axes. Exposing the host axes here made ``cbar.ax.set_ylabel`` rename
            the plot's y axis and could invalidate away the reserved colorbar
            strip during constrained-layout export.
            """

            def __init__(self, host: Any, colorbar_options: dict[str, Any]) -> None:
                self._host = host
                self._options = colorbar_options

            def set_ylabel(self, label: str, **kwargs: Any) -> None:
                del kwargs
                self._options["label"] = _plain_text(label)
                self._host._invalidate()

            def set_xlabel(self, label: str, **kwargs: Any) -> None:
                self.set_ylabel(label, **kwargs)

            def get_position(self, original: bool = False) -> Bbox:
                # compat-noop: virtual colorbar chrome has no independently
                # aspect-adjusted axes box, so its active and original boxes
                # are identical by construction.
                del original  # compat-noop: active/original virtual chrome boxes are identical
                left, bottom, width, height = self._host.get_position().bounds
                shrink_value = float(self._options.get("shrink", 1.0))
                anchor_value = self._options.get("anchor") or [0.5, 0.5]
                if self._options.get("orientation") == "horizontal":
                    bar_width = width * shrink_value
                    bar_left = left + (width - bar_width) * float(anchor_value[0])
                    return Bbox.from_bounds(bar_left, bottom - 0.08, bar_width, 0.04)
                bar_height = height * shrink_value
                bar_bottom = bottom + (height - bar_height) * float(anchor_value[1])
                return Bbox.from_bounds(left + width + 0.02, bar_bottom, 0.03, bar_height)

            def set_position(self, position: Any) -> None:
                values = np.asarray(
                    getattr(position, "bounds", position), dtype=np.float64
                ).reshape(-1)
                if len(values) != 4 or not np.isfinite(values).all():
                    raise ValueError(
                        "colorbar position must be a finite (left, bottom, width, height)"
                    )
                parent_left, parent_bottom, parent_width, parent_height = (
                    self._host.get_position().bounds
                )
                left, bottom, width, height = map(float, values)
                if self._options.get("orientation") == "horizontal":
                    shrink_value = float(np.clip(width / max(parent_width, 1e-12), 0.01, 1.0))
                    remainder = max(parent_width - width, 1e-12)
                    anchor = float(np.clip((left - parent_left) / remainder, 0.0, 1.0))
                    self._options["anchor"] = [anchor, 0.5]
                else:
                    shrink_value = float(np.clip(height / max(parent_height, 1e-12), 0.01, 1.0))
                    remainder = max(parent_height - height, 1e-12)
                    anchor = float(np.clip((bottom - parent_bottom) / remainder, 0.0, 1.0))
                    self._options["anchor"] = [0.5, anchor]
                self._options["shrink"] = shrink_value
                self._host._invalidate()

        class _Colorbar:
            def __init__(self, ax: Any, colorbar_options: dict[str, Any]) -> None:
                self._options = colorbar_options
                self._host = ax
                self.ax = (
                    ax
                    if colorbar_options.get("placement") == "axes"
                    else _ColorbarAxes(ax, colorbar_options)
                )

            def add_lines(self, contour: Any, *, erase: bool = True) -> None:
                from ._artists import ContourSet

                if not isinstance(contour, ContourSet):
                    raise not_implemented(
                        "Colorbar.add_lines(levels, colors, linewidths)",
                        "Colorbar.add_lines(ContourSet)",
                    )
                lines = _contour_colorbar_lines(contour, self._host)
                if erase:
                    self._options["lines"] = lines
                else:
                    self._options.setdefault("lines", []).extend(lines)
                self._host._invalidate()

            def set_label(self, label: str, **kwargs: Any) -> None:
                del kwargs
                self._options["label"] = _plain_text(label)
                self._host._invalidate()

            def set_ticks(self, ticks: Any, labels: Any = None, **kwargs: Any) -> None:
                if labels is not None:
                    raise not_implemented(
                        "Colorbar.set_ticks(labels=...)", "numeric tick positions"
                    )
                check_unsupported(kwargs, "Colorbar.set_ticks()")
                self._options["ticks"] = [float(value) for value in np.asarray(ticks).reshape(-1)]
                self._host._invalidate()

            def minorticks_on(self) -> None:
                self._options["minor_ticks"] = True
                self._host._invalidate()

            def minorticks_off(self) -> None:
                self._options["minor_ticks"] = False
                self._host._invalidate()

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

    def subplot_mosaic(
        self,
        mosaic: Any,
        *,
        sharex: bool = False,
        sharey: bool = False,
        width_ratios: Any = None,
        height_ratios: Any = None,
        empty_sentinel: Any = ".",
        subplot_kw: Optional[dict[str, Any]] = None,
        per_subplot_kw: Optional[dict[Any, dict[str, Any]]] = None,
        gridspec_kw: Optional[dict[str, Any]] = None,
    ) -> dict[Any, Axes]:
        """Create one axes for each rectangular label region in ``mosaic``.

        Unlike a dense ``subplots`` grid, a mosaic may contain holes and one
        label may span several cells.  Resolve every region through the same
        ``_GridSpec.cell_rect`` path as an explicit GridSpec span, but do not
        call ``_ensure_grid``: that helper intentionally materializes every
        dense-grid cell and would turn holes and repeated labels into phantom
        axes.
        """
        if not isinstance(sharex, bool) or not isinstance(sharey, bool):
            raise TypeError("sharex and sharey must be bool")
        if isinstance(mosaic, str):
            if "\n" in mosaic:
                cleaned = inspect.cleandoc(mosaic).strip("\n")
                rows = [list(row.strip()) for row in cleaned.split("\n")]
            else:
                rows = [list(row.strip()) for row in mosaic.split(";")]
        else:
            try:
                rows = [list(row) for row in mosaic]
            except TypeError as error:
                raise ValueError("mosaic must be a string or a 2-D row sequence") from error
        if not rows or not rows[0]:
            raise ValueError("mosaic must contain at least one row and one column")
        ncols = len(rows[0])
        if any(len(row) != ncols for row in rows):
            raise ValueError("all mosaic rows must have the same length")
        nrows = len(rows)

        grid_options = dict(gridspec_kw or {})
        for name, value in (
            ("width_ratios", width_ratios),
            ("height_ratios", height_ratios),
        ):
            if value is None:
                continue
            if name in grid_options:
                raise ValueError(f"{name!r} must not be defined both directly and in gridspec_kw")
            grid_options[name] = value
        grid = _GridSpec(self, nrows, ncols, **grid_options)

        positions: dict[Any, list[tuple[int, int]]] = {}
        for row_index, row in enumerate(rows):
            for col_index, label in enumerate(row):
                if label == empty_sentinel:
                    continue
                try:
                    hash(label)
                except TypeError as error:
                    raise TypeError("mosaic labels must be hashable scalar values") from error
                positions.setdefault(label, []).append((row_index, col_index))
        if not positions:
            raise ValueError("mosaic must contain at least one non-empty label")

        regions: list[tuple[Any, _SubplotSpec]] = []
        for label, cells in positions.items():
            row0 = min(row for row, _col in cells)
            row1 = max(row for row, _col in cells) + 1
            col0 = min(col for _row, col in cells)
            col1 = max(col for _row, col in cells) + 1
            if any(
                rows[row][col] != label for row in range(row0, row1) for col in range(col0, col1)
            ):
                raise ValueError(
                    f"mosaic label {label!r} specifies a non-rectangular or non-contiguous area"
                )
            regions.append((label, _SubplotSpec(grid, (row0, row1), (col0, col1))))

        common_options = dict(subplot_kw or {})
        per_label_options = dict(per_subplot_kw or {})
        unknown_labels = set(per_label_options) - set(positions)
        if unknown_labels:
            raise ValueError(
                f"per_subplot_kw contains labels absent from the mosaic: "
                f"{sorted(map(repr, unknown_labels))}"
            )

        self._nrows, self._ncols = nrows, ncols
        self._width_ratios = grid._width_ratios
        self._height_ratios = grid._height_ratios
        axes: dict[Any, Axes] = {}
        for label, spec in regions:
            options = {**common_options, **per_label_options.get(label, {})}
            ax = self.add_axes(grid.cell_rect(spec.rows, spec.cols), **options)
            ax._subplot_spec = spec
            ax._subplot_claimed = True
            axes[label] = ax

        apply_sharing(self, sharex, sharey)
        if sharex or sharey:
            for ax in axes.values():
                spec = ax._subplot_spec
                if sharex and spec.rows[1] < nrows:
                    ax._apply_tick_label_side_visibility("x", {"labelbottom": False})
                if sharey and spec.cols[0] > 0:
                    ax._apply_tick_label_side_visibility("y", {"labelleft": False})
        self._current_ax = next(reversed(axes.values()))
        self._invalidate()
        return axes

    # -- panel sizing -----------------------------------------------------------

    def _panel_px(self) -> tuple[int, int]:
        w, h = rc_figsize_px(self._figsize, self._dpi)
        return max(120, w // self._ncols), max(120, h // self._nrows)

    def _effective_rects(
        self,
        chrome_cache: Optional[_ChromeCache] = None,
    ) -> Optional[list[tuple[float, float, float, float]]]:
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
        self._ensure_layout(chrome_cache)
        if not self._axes:
            return None
        if (
            all(ax._figure_rect is None for ax in self._axes)
            and not self._subplot_adjust
            and len(self._axes) <= 1
            and self._supxlabel_entry is None
            and self._supylabel_entry is None
            and self._figure_legend is None
        ):
            return None
        return [self._axes_rect(ax) or _DEFAULT_AXES_RECT for ax in self._axes]

    def _axes_rect(self, ax: Axes) -> Optional[tuple[float, float, float, float]]:
        """One axes' matplotlib rectangle (figure fractions), or None if foreign.

        The single resolver behind both `_effective_rects` (what the exporters
        place) and `Axes.get_position` (what scripts read), so the reported box
        and the rendered box cannot drift apart.
        """
        self._ensure_layout()
        if ax._figure_rect is not None:
            return ax._figure_rect
        if ax not in self._axes:
            return None
        if any(other._figure_rect is not None for other in self._axes):
            # Free-form figure (add_axes/insets): matplotlib leaves a rect-less
            # axes at the SubplotParams frame instead of dragging it onto the
            # panel grid, which `add_axes` has already redefined as 1 x n.
            if not self._subplot_adjust:
                return _DEFAULT_AXES_RECT
            return _GridSpec(self, 1, 1, **self._subplot_adjust).cell_rect((0, 1), (0, 1))
        if len(self._axes) == 1 and self._nrows == self._ncols == 1 and not self._subplot_adjust:
            # The overwhelmingly common single-subplot case is exactly the
            # Matplotlib default frame. Avoid rebuilding a one-cell GridSpec
            # every time layout asks for the axes rectangle.
            return _DEFAULT_AXES_RECT
        # A uniform grid (adjusted or default SubplotParams): the panel
        # resolves to its gridspec cell rectangle under the frame and spacing.
        index = ax._subplot_index
        if index is None:
            index = self._axes.index(ax)
        row, col = divmod(index, self._ncols)
        grid = _GridSpec(
            self,
            self._nrows,
            self._ncols,
            width_ratios=self._width_ratios,
            height_ratios=self._height_ratios,
            **self._subplot_adjust,
        )
        return grid.cell_rect((row, row + 1), (col, col + 1))

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

    def _tight_layout_colorbar_reservations(
        self,
        rects: list[tuple[float, float, float, float]],
        canvas_size: tuple[int, int],
        chrome_cache: Optional[_ChromeCache] = None,
    ) -> set[int]:
        """Return automatic colorbars whose chrome already fits the layout.

        A tight/constrained solve may run either before or after ``colorbar()``.
        The engine name therefore cannot tell `_charts()` whether the solved
        rectangles include the colorbar.  Instead, test the resulting geometry:
        a vertical bar is reserved when the panel's full right chrome fits
        before the canvas edge or the next panel's left chrome; a horizontal
        bar uses the analogous clearance below the panel.
        """
        if self._layout_options.get("engine") != "tight":
            return set()

        canvas_w, canvas_h = canvas_size
        chromes = [
            _panel_chrome(ax, max(1, round(canvas_w * rect[2])), cache=chrome_cache)
            for ax, rect in zip(self._axes, rects, strict=True)
        ]
        reserved: set[int] = set()
        tolerance = 0.5
        for index, (ax, rect, chrome) in enumerate(zip(self._axes, rects, chromes, strict=True)):
            options = ax._colorbar
            if options is None or options.get("placement") == "axes":
                continue

            left, bottom, width, height = rect
            right = left + width
            top = bottom + height
            if options.get("orientation") == "horizontal":
                boundary = 0.0
                for other_index, other_rect in enumerate(rects):
                    if other_index == index:
                        continue
                    other_left, other_bottom, other_width, other_height = other_rect
                    other_right = other_left + other_width
                    other_top = other_bottom + other_height
                    columns_overlap = max(left, other_left) < min(right, other_right)
                    if columns_overlap and other_top <= bottom + tolerance / canvas_h:
                        boundary = max(
                            boundary,
                            other_top + chromes[other_index][1] / canvas_h,
                        )
                panel_bottom = bottom - chrome[3] / canvas_h
                if panel_bottom >= boundary - tolerance / canvas_h:
                    reserved.add(index)
                continue

            boundary = 1.0
            for other_index, other_rect in enumerate(rects):
                if other_index == index:
                    continue
                other_left, other_bottom, _other_width, other_height = other_rect
                other_top = other_bottom + other_height
                rows_overlap = max(bottom, other_bottom) < min(top, other_top)
                if rows_overlap and other_left >= right - tolerance / canvas_w:
                    boundary = min(
                        boundary,
                        other_left - chromes[other_index][0] / canvas_w,
                    )
            panel_right = right + chrome[2] / canvas_w
            if panel_right <= boundary + tolerance / canvas_w:
                reserved.add(index)
        return reserved

    def _charts(self, chrome_cache: Optional[_ChromeCache] = None) -> list[Any]:
        total_w, total_h = rc_figsize_px(self._figsize, self._dpi)
        rects = self._effective_rects(chrome_cache)
        chart_sizes: list[tuple[int, int]] = []
        if rects is not None:
            charts = []
            reserved_colorbars = self._tight_layout_colorbar_reservations(
                rects,
                (total_w, total_h),
                chrome_cache,
            )
            for index, (ax, rect) in enumerate(zip(self._axes, rects, strict=True)):
                allocated_plot_w = max(1, round(total_w * rect[2]))
                allocated_plot_h = max(1, round(total_h * rect[3]))
                compact = allocated_plot_w + 54 < 520
                colorbar_right, colorbar_bottom = ax._colorbar_outside_room(compact)
                automatic_colorbar = (
                    ax._colorbar is not None
                    and ax._colorbar.get("placement") != "axes"
                    and index not in reserved_colorbars
                )
                # Matplotlib steals an automatic colorbar from the source
                # subplot's allocation. Shrink here unless the actual
                # tight/constrained geometry already contains the complete
                # colorbar-bearing panel.
                plot_w = max(
                    40,
                    round(allocated_plot_w - colorbar_right)
                    if automatic_colorbar
                    else allocated_plot_w,
                )
                plot_h = max(
                    40,
                    round(allocated_plot_h - colorbar_bottom)
                    if automatic_colorbar
                    else allocated_plot_h,
                )
                # Absolute axes rectangles describe the plot box.  Export
                # chrome lives outside that rectangle in the surrounding
                # figure buffer, matching Matplotlib add_axes semantics —
                # including the axes title, which matplotlib draws above the
                # axes without moving its position.
                left, top, right, bottom = _panel_chrome(ax, plot_w, cache=chrome_cache)
                plot_ratio = plot_w / plot_h
                plot_box = (left, top, plot_w, plot_h)
                # Pin the plot rect inside the panel: the exporters place the
                # panel assuming its plot box sits at exactly this inset, so
                # the renderers must not pick their own label-aware margins.
                #
                # A chart may already be cached from when this was the figure's
                # only axes. Adding an overlapping axes switches the figure to
                # absolute composition, where the same Matplotlib axes rectangle
                # needs a smaller chrome-inclusive panel. Reusing the old chart
                # offsets its ticks and labels even though the plot boxes overlap.
                if ax._plot_box_px != plot_box or ax._absolute_plot_ratio != plot_ratio:
                    ax._plot_box_px = plot_box
                    ax._absolute_plot_ratio = plot_ratio
                    ax._chart = None
                chart_sizes.append((round(plot_w + left + right), round(plot_h + top + bottom)))
                charts.append(ax._build_chart(*chart_sizes[-1]))
        else:
            widths, heights = self._grid_cell_sizes()
            charts = []
            for index, ax in enumerate(self._axes):
                # Removing an overlay can return a one-axes figure to ordinary
                # (non-absolute) composition. Drop the absolute geometry and
                # its cached chart together so the remaining axes expands back
                # to the figure canvas.
                if ax._plot_box_px is not None or ax._absolute_plot_ratio is not None:
                    ax._plot_box_px = None
                    ax._absolute_plot_ratio = None
                    ax._chart = None
                chart_sizes.append((widths[index % self._ncols], heights[index // self._ncols]))
                charts.append(ax._build_chart(*chart_sizes[-1]))
        if charts and (self._sharex or self._sharey):
            figures = [chart.figure() for chart in charts]
            linked: list[str] = []
            shared_domains: list[dict[str, tuple[float, float]]] = [{} for _figure in figures]
            for dim, shared in (("x", self._sharex), ("y", self._sharey)):
                if not shared:
                    continue
                linked.append(dim)
                for group in self._share_groups(shared, len(figures)):
                    members = [figures[i] for i in group]
                    source_ax = self._axes[group[0]]
                    if dim in source_ax._explicit_domains:
                        domain = tuple(map(float, source_ax._axis[dim]["domain"]))
                    else:
                        # Matplotlib shared limits autoscale over the group's
                        # data; dataless panels follow the group instead of
                        # contributing their (0, 1) default view to the union.
                        sources = [figure for figure in members if figure.traces] or members
                        ranges = [
                            figure.x_range() if dim == "x" else figure.y_range()
                            for figure in sources
                        ]
                        domain = (
                            min(min(pair) for pair in ranges),
                            max(max(pair) for pair in ranges),
                        )
                    for index in group:
                        shared_domains[index][dim] = domain

            # Matplotlib's AxLine reads the live shared viewLim at draw time.
            # Our wire format needs finite endpoints, so materialize only axes
            # containing axlines one more time when their group's finalized
            # domain differs from the view used by the cached chart.
            for index, (ax, domains) in enumerate(zip(self._axes, shared_domains, strict=True)):
                if not any(entry["kind"] == "@axline" for entry in ax._entries):
                    continue
                data_domains = {}
                for dim, domain in domains.items():
                    spec = ax._scale_specs[dim]
                    data_domains[dim] = tuple(
                        map(
                            float,
                            _scale_values(np.asarray(domain), spec, inverse=True),
                        )
                    )
                if getattr(ax, "_shared_render_domains", {}) != data_domains:
                    ax._shared_render_domains = data_domains
                    ax._chart = None
                    charts[index] = ax._build_chart(*chart_sizes[index])

            figures = [chart.figure() for chart in charts]
            for figure, domains in zip(figures, shared_domains, strict=True):
                for dim, domain in domains.items():
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

    def _single(self, chrome_cache: Optional[_ChromeCache] = None) -> Optional[Any]:
        charts = self._charts(chrome_cache)
        if (
            self._nrows == self._ncols == 1
            and len(charts) == 1
            and self._axes[0]._figure_rect is None
            and not self._subplot_adjust
            and self._supxlabel_entry is None
            and self._supylabel_entry is None
            and self._figure_legend is None
        ):
            return charts[0]
        return None

    def _panel_positions(
        self,
        rects: list[tuple[float, float, float, float]],
        canvas_size: tuple[int, int],
        chrome_cache: Optional[_ChromeCache] = None,
    ) -> list[tuple[float, float, float, float]]:
        """Expand plot-box rects into whole-panel rects including chart chrome.

        Free-form panels are built at plot size plus fixed chrome margins
        (`_charts`); exporters place the enlarged panel so its plot box lands
        exactly on the requested figure rectangle.
        """
        positions = []
        for ax, rect in zip(self._axes, rects, strict=True):
            # The same chrome `_charts` built the panel with — including the
            # axes title, which grows the panel upward so the plot box stays
            # on the rect.
            left, top, right, bottom = _panel_chrome(
                ax,
                max(1, round(canvas_size[0] * rect[2])),
                cache=chrome_cache,
            )
            positions.append(
                (
                    rect[0] - left / canvas_size[0],
                    rect[1] - bottom / canvas_size[1],
                    rect[2] + (left + right) / canvas_size[0],
                    rect[3] + (top + bottom) / canvas_size[1],
                )
            )
        return positions

    # -- output -----------------------------------------------------------------

    @_textblock.cached_measurements
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
                chrome_cache: _ChromeCache = {}
                single = self._single(chrome_cache)
                if single is None or self._suptitle is not None:
                    from ._grid import compose_svg

                    canvas_size = rc_figsize_px(self._figsize, self._dpi)
                    rects = self._effective_rects(chrome_cache)
                    data = compose_svg(
                        self._charts(chrome_cache),
                        self._nrows,
                        self._ncols,
                        self._suptitle,
                        self._resolved_suptitle_style(),
                        figure_labels=self._resolved_figure_labels(),
                        figure_legend=self._figure_legend,
                        positions=(
                            None
                            if rects is None
                            else self._panel_positions(rects, canvas_size, chrome_cache)
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

    @_textblock.cached_measurements
    def _to_png(self, *, bbox_tight: bool = False, pad_inches: float = 0.1) -> bytes:
        from ._grid import stitch_png

        chrome_cache: _ChromeCache = {}
        canvas_size = rc_figsize_px(self._figsize, self._dpi)
        rects = self._effective_rects(chrome_cache)
        positions = (
            None if rects is None else self._panel_positions(rects, canvas_size, chrome_cache)
        )

        return stitch_png(
            self._charts(chrome_cache),
            self._nrows,
            self._ncols,
            self._suptitle,
            self._shared_colorbar,
            suptitle_style=self._resolved_suptitle_style(),
            figure_labels=self._resolved_figure_labels(),
            figure_legend=self._figure_legend,
            positions=positions,
            canvas_size=canvas_size if positions is not None else None,
            facecolor=self._facecolor,
            bbox_tight=bbox_tight,
            pad_pixels=max(0, round(pad_inches * float(self._dpi or 100.0))),
        )

    @_textblock.cached_measurements
    def _to_html(self) -> str:
        if self._html_cache is None:
            chrome_cache: _ChromeCache = {}
            single = self._single(chrome_cache)
            if single is not None and self._suptitle is None:
                self._html_cache = single.to_html()
            else:
                from ._grid import compose_html

                canvas_size = rc_figsize_px(self._figsize, self._dpi)
                rects = self._effective_rects(chrome_cache)
                self._html_cache = compose_html(
                    self._charts(chrome_cache),
                    self._nrows,
                    self._ncols,
                    self._suptitle,
                    self._resolved_suptitle_style(),
                    figure_labels=self._resolved_figure_labels(),
                    figure_legend=self._figure_legend,
                    positions=(
                        None
                        if rects is None
                        else self._panel_positions(rects, canvas_size, chrome_cache)
                    ),
                    canvas_size=None if rects is None else canvas_size,
                )
        return self._html_cache

    @_textblock.cached_measurements
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
                # Matplotlib's inline bbox is derived from the ink, so the y
                # title can never land on the tick labels there — but pinning a
                # padding also pins the browser's gutter, and 41 px does not
                # hold this shim's 13.89 px tick labels under a rotated title.
                # Ask the shared static-layout path what the axis text measures
                # (`_svg.layout` is the single authority for that reservation,
                # so browser, SVG, and PNG stay on one number) and, when the pin
                # is short, widen the *canvas* by the shortfall so the plot box
                # keeps Matplotlib's 0.775 fraction instead of losing width.
                measured_left = _measured_left_gutter(ax, tight_width, tight_height)
                if measured_left > notebook_padding[3]:
                    tight_width = max(
                        120, tight_width + int(round(measured_left - notebook_padding[3]))
                    )
                    notebook_padding[3] = measured_left
                    ax._chart = None
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
                size = float(self._resolved_suptitle_style()["size"])
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
    if squeeze and nrows == ncols == 1:
        # Avoid allocating and populating an object ndarray for the dominant
        # plt.subplots() case whose public return value is a bare Axes.
        fig._current_ax = fig._axes[0]
        fig._axes[0]._subplot_claimed = True
        return fig._axes[0]
    axes = np.empty((nrows, ncols), dtype=object)
    for r in range(nrows):
        for c in range(ncols):
            axes[r, c] = fig._axes_at(r * ncols + c)
            axes[r, c]._subplot_claimed = True
    # Matplotlib's subplots() constructs axes in row-major order and leaves
    # the final one active for subsequent stateful ``plt.*`` calls.
    fig._current_ax = axes[-1, -1]
    if squeeze and (nrows == 1 or ncols == 1):
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
    """Share domains, authored ticker state, and live ranges across panels."""
    fig._sharex = _share_mode(sharex, "sharex")
    fig._sharey = _share_mode(sharey, "sharey")
    for axis, mode in (("x", fig._sharex), ("y", fig._sharey)):
        for ax in fig._axes:
            ax._shared_axis_sources.pop(axis, None)
        if not mode:
            continue
        for group in fig._share_groups(mode, len(fig._axes)):
            if not group:
                continue
            source = fig._axes[group[0]]
            for index in group:
                fig._axes[index]._shared_axis_sources[axis] = source
