"""The shared type vocabulary for xy's public signatures.

These aliases exist so hovering a function shows what a parameter really
accepts, in plain terms, instead of ``Any``. They are honest unions — a
type checker can verify calls against them — and each one is documented
here so no matplotlib (or NumPy) background is assumed.

Only the engine-agnostic vocabulary lives here; CSS-flavored style types
stay in `xy.styles` (``StyleValue``/``StyleMapping``) and the pyplot shim
re-uses these same names so both API layers read alike.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol, TypeAlias, Union

import numpy.typing as npt

if TYPE_CHECKING:
    import numpy as np

# One-dimensional data: a list/tuple of numbers, a NumPy array, or anything
# that converts to one (pandas Series/Index, array-API objects, generators
# already materialized to sequences). Datetime and string categories are
# accepted where the function says so. When a chart takes ``data=``, a plain
# string is also allowed here and is looked up as a column name.
ArrayLike: TypeAlias = npt.ArrayLike

# A single scalar cell of data: Python or NumPy numbers.
Scalar: TypeAlias = Union[int, float, "np.integer", "np.floating"]

# One color: a name ("tab:blue", "rebeccapurple"), hex string ("#22aa88"),
# shorthand ("r", "k"), or an RGB(A) tuple of floats in [0, 1].
ColorLike: TypeAlias = Union[
    str,
    tuple[float, float, float],
    tuple[float, float, float, float],
]

# One color, or one per data point: a sequence of `ColorLike`, or a numeric
# array to be mapped through a colormap.
ColorsLike: TypeAlias = Union[ColorLike, Sequence[ColorLike], npt.ArrayLike]

# Axis bounds as (low, high); either side may be None to keep the
# automatically computed value.
LimitsLike: TypeAlias = tuple[Union[float, None], Union[float, None]]


class DataLike(Protocol):
    """Tabular data usable for the ``data=`` indirection: anything indexable
    by column name — a pandas DataFrame, a dict of arrays, or any mapping
    from column names to `ArrayLike` values."""

    def __getitem__(self, key: str) -> object: ...


# A tabular source, or None to pass arrays directly.
TableLike: TypeAlias = Union[DataLike, Mapping[str, ArrayLike], None]
