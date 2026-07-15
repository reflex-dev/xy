"""Seaborn-shaped FacetGrid running on the shim's own subplot grid.

Real seaborn's ``FacetGrid.map`` drives matplotlib's implicit pyplot state:
it activates each facet's axes with ``plt.sca`` and then calls the mapped
function with no ``ax=``. That contract cannot interoperate across engines —
mapping an ``xy.pyplot`` function over a seaborn grid draws into a phantom
xy figure while the seaborn grid stays empty. This class reproduces the
faceting contract natively (subset → activate panel → call ``func``), so the
corpus pattern ``FacetGrid(df, row=..., col=...).map(plt.hist, ...)`` renders
without seaborn or matplotlib installed.

Only row/col faceting is implemented; hue semantics (palette cycling,
``legend_out``) stay loud ``NotImplementedError``s rather than half-drawing.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from . import _state
from ._translate import check_unsupported, not_implemented


def _categorical_order(values: Any, order: Any) -> list[Any]:
    """Facet levels: explicit order, categorical dtype order, or data order."""
    if order is not None:
        return list(order)
    accessor = getattr(values, "cat", None)
    if accessor is not None:
        return list(accessor.categories)
    if hasattr(values, "categories"):
        return list(values.categories)
    arr = np.asarray(values)
    if arr.dtype.kind in "biufM":
        levels = np.unique(arr)
        if arr.dtype.kind == "f":
            levels = levels[np.isfinite(levels)]
        return list(levels)
    seen: list[Any] = []
    for value in arr:
        if isinstance(value, float) and np.isnan(value):
            continue
        if value not in seen:
            seen.append(value)
    return seen


class FacetGrid:
    """Row/column small multiples with the seaborn ``map`` contract."""

    _ROW_TEMPLATE = "{row_var} = {row_name}"
    _COL_TEMPLATE = "{col_var} = {col_name}"

    def __init__(
        self,
        data: Any,
        *,
        row: Optional[str] = None,
        col: Optional[str] = None,
        hue: Optional[str] = None,
        col_wrap: Optional[int] = None,
        sharex: Any = True,
        sharey: Any = True,
        height: float = 3.0,
        aspect: float = 1.0,
        palette: Any = None,
        row_order: Any = None,
        col_order: Any = None,
        hue_order: Any = None,
        hue_kws: Any = None,
        dropna: bool = False,
        legend_out: bool = True,
        despine: bool = True,
        margin_titles: bool = False,
        xlim: Any = None,
        ylim: Any = None,
        subplot_kws: Any = None,
        gridspec_kws: Any = None,
        **kwargs: Any,
    ) -> None:
        check_unsupported(kwargs, "FacetGrid()")
        if hue is not None or hue_order is not None or hue_kws or palette is not None:
            raise not_implemented(
                "FacetGrid(hue=/palette=)", "row/col faceting with per-call colors"
            )
        if col_wrap is not None:
            raise not_implemented("FacetGrid(col_wrap=)", "an explicit row= facet")
        if subplot_kws or gridspec_kws:
            raise not_implemented("FacetGrid(subplot_kws=/gridspec_kws=)")
        del legend_out  # observable only with hue, which is rejected above
        if data is None or not hasattr(data, "__getitem__"):
            raise TypeError("FacetGrid data must be a mapping or a pandas-like table")
        self.data = data
        self._dropna = bool(dropna)
        self._margin_titles = bool(margin_titles)
        self._margin_texts: list[Any] = []
        self._row_var, self._col_var = row, col
        self.row_names = _categorical_order(data[row], row_order) if row is not None else []
        self.col_names = _categorical_order(data[col], col_order) if col is not None else []
        if (row is not None and not self.row_names) or (col is not None and not self.col_names):
            raise ValueError("FacetGrid facet columns must have at least one level")
        nrow = max(1, len(self.row_names))
        ncol = max(1, len(self.col_names))
        figsize = (ncol * float(height) * float(aspect), nrow * float(height))
        self._figure = _state.figure(figsize=figsize)
        self.axes = np.asarray(
            self._figure.subplots(nrow, ncol, sharex=sharex, sharey=sharey, squeeze=False),
            dtype=object,
        )
        for ax in self.axes.flat:
            if xlim is not None:
                ax.set_xlim(*xlim)
            if ylim is not None:
                ax.set_ylim(*ylim)
        if despine:
            self.despine()
        self.set_titles()

    # -- seaborn-visible attributes ------------------------------------------------

    @property
    def figure(self) -> Any:
        return self._figure

    @property
    def fig(self) -> Any:
        return self._figure

    @property
    def ax(self) -> Any:
        if self.axes.shape == (1, 1):
            return self.axes[0, 0]
        raise AttributeError("Use the .axes attribute when the grid has more than one subplot")

    # -- faceting -------------------------------------------------------------------

    def _column_values(self, name: Any) -> np.ndarray:
        if not isinstance(name, str):
            raise TypeError("FacetGrid.map positional arguments must be column names")
        try:
            values = self.data[name]
        except (KeyError, IndexError, TypeError) as exc:
            raise KeyError(f"FacetGrid column {name!r} not found in data") from exc
        return np.asarray(values)

    def _facet_mask(self, row_i: int, col_j: int) -> np.ndarray:
        mask: Optional[np.ndarray] = None
        for var, level in (
            (self._row_var, self.row_names[row_i] if self._row_var is not None else None),
            (self._col_var, self.col_names[col_j] if self._col_var is not None else None),
        ):
            if var is None:
                continue
            level_mask = np.asarray(self._column_values(var) == level, dtype=bool)
            mask = level_mask if mask is None else mask & level_mask
        if mask is None:
            if hasattr(self.data, "iloc"):  # pandas-like: len() counts rows
                length = len(self.data)
            else:  # mapping: len() counts columns, so measure one column
                length = len(np.asarray(next(iter(self.data.values()))))
            mask = np.ones(length, dtype=bool)
        return mask

    def map(self, func: Any, *args: str, **kwargs: Any) -> "FacetGrid":
        """Subset per facet, activate its panel, and call ``func`` on the columns."""
        if not callable(func):
            raise TypeError("FacetGrid.map first argument must be callable")
        for (row_i, col_j), ax in np.ndenumerate(self.axes):
            mask = self._facet_mask(row_i, col_j)
            if not mask.any():
                continue
            columns = [self._column_values(name)[mask] for name in args]
            if self._dropna and columns:
                valid = np.ones(int(mask.sum()), dtype=bool)
                for column in columns:
                    if column.dtype.kind == "f":
                        valid &= ~np.isnan(column)
                columns = [column[valid] for column in columns]
            _state.sca(ax)
            func(*columns, **kwargs)
        self._finalize_grid(args[:2])
        return self

    def _finalize_grid(self, axlabels: tuple[str, ...]) -> None:
        self.set_axis_labels(*axlabels)
        self.set_titles()
        self._figure.tight_layout()

    # -- labels and titles ------------------------------------------------------------

    def set_axis_labels(
        self, x_var: Optional[str] = None, y_var: Optional[str] = None, **kwargs: Any
    ) -> "FacetGrid":
        if x_var is not None:
            self.set_xlabels(x_var, **kwargs)
        if y_var is not None:
            self.set_ylabels(y_var, **kwargs)
        return self

    def set_xlabels(self, label: str, clear_inner: bool = True, **kwargs: Any) -> "FacetGrid":
        for ax in self.axes[-1, :]:
            ax.set_xlabel(label, **kwargs)
        if clear_inner:
            for ax in self.axes[:-1, :].flat:
                ax.set_xlabel("")
        return self

    def set_ylabels(self, label: str, clear_inner: bool = True, **kwargs: Any) -> "FacetGrid":
        for ax in self.axes[:, 0]:
            ax.set_ylabel(label, **kwargs)
        if clear_inner:
            for ax in self.axes[:, 1:].flat:
                ax.set_ylabel("")
        return self

    def set_titles(
        self,
        template: Optional[str] = None,
        row_template: Optional[str] = None,
        col_template: Optional[str] = None,
        **kwargs: Any,
    ) -> "FacetGrid":
        row_template = self._ROW_TEMPLATE if row_template is None else row_template
        col_template = self._COL_TEMPLATE if col_template is None else col_template
        if template is None:
            if self._row_var is None:
                template = col_template
            elif self._col_var is None:
                template = row_template
            else:
                template = f"{row_template} | {col_template}"
        for text in self._margin_texts:
            text.remove()
        self._margin_texts = []
        if self._margin_titles and self._row_var is not None:
            for row_i, row_name in enumerate(self.row_names):
                self._margin_texts.append(
                    self.axes[row_i, -1].annotate(
                        row_template.format(row_var=self._row_var, row_name=row_name),
                        xy=(1.02, 0.5),
                        xycoords="axes fraction",
                        rotation=270,
                        ha="left",
                        va="center",
                        **kwargs,
                    )
                )
            for col_j, col_name in enumerate(self.col_names or [None]):
                title = (
                    col_template.format(col_var=self._col_var, col_name=col_name)
                    if self._col_var is not None
                    else ""
                )
                self.axes[0, col_j].set_title(title, **kwargs)
            for ax in self.axes[1:, :].flat:
                ax.set_title("")
            return self
        for row_i, col_j in np.ndindex(self.axes.shape):
            fields = {}
            if self._row_var is not None:
                fields["row_var"], fields["row_name"] = self._row_var, self.row_names[row_i]
            if self._col_var is not None:
                fields["col_var"], fields["col_name"] = self._col_var, self.col_names[col_j]
            self.axes[row_i, col_j].set_title(template.format(**fields) if fields else "", **kwargs)
        return self

    # -- convenience --------------------------------------------------------------

    def despine(self, **kwargs: Any) -> "FacetGrid":
        sides = {
            "top": kwargs.pop("top", True),
            "right": kwargs.pop("right", True),
            "left": kwargs.pop("left", False),
            "bottom": kwargs.pop("bottom", False),
        }
        check_unsupported(kwargs, "FacetGrid.despine()")
        for ax in self.axes.flat:
            for side, off in sides.items():
                if off:
                    ax.spines[side].set_visible(False)
        return self

    def set(self, **kwargs: Any) -> "FacetGrid":
        for ax in self.axes.flat:
            ax.set(**kwargs)
        return self

    def tight_layout(self, **kwargs: Any) -> "FacetGrid":
        self._figure.tight_layout(**kwargs)
        return self

    def savefig(self, *args: Any, **kwargs: Any) -> None:
        self._figure.savefig(*args, **kwargs)

    def add_legend(self, *args: Any, **kwargs: Any) -> "FacetGrid":
        raise not_implemented("FacetGrid.add_legend()", "per-axes legend() calls")

    def map_dataframe(self, func: Any, *args: Any, **kwargs: Any) -> "FacetGrid":
        raise not_implemented("FacetGrid.map_dataframe()", "FacetGrid.map()")
