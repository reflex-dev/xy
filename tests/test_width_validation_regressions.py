"""Focused regressions for scalar and malformed rectangle/contour widths."""

from __future__ import annotations

import numpy as np
import pytest

from xy._figure import Figure


def test_contour_accepts_numeric_zero_dimensional_width_arrays() -> None:
    z = np.array([[0.0, 1.0], [1.0, 2.0]])

    for width in (np.array(1.1), np.array(1.1, dtype=np.float32)):
        spec, _blob = Figure().contour(z, levels=[0.5, 1.5], width=width).build_payload()
        assert spec["traces"][0]["style"]["width"] == pytest.approx(1.1)


@pytest.mark.parametrize("width", [np.array(True), np.array(False)])
def test_contour_zero_dimensional_boolean_widths_remain_invalid(width: np.ndarray) -> None:
    z = np.array([[0.0, 1.0], [1.0, 2.0]])

    with pytest.raises(ValueError, match="contour width"):
        Figure().contour(z, levels=[0.5, 1.5], width=width)


@pytest.mark.parametrize("kind", ["bar", "column"])
@pytest.mark.parametrize(
    "width",
    [
        "wide",
        object(),
        [[0.5], [0.5, 0.6]],
    ],
    ids=["string", "object", "ragged"],
)
def test_rectangle_width_conversion_errors_name_the_argument(
    kind: str,
    width: object,
) -> None:
    build = getattr(Figure(), kind)

    with pytest.raises(
        ValueError,
        match=rf"{kind} width must be scalar or contain numeric values",
    ):
        build([0.0, 1.0], [1.0, 2.0], width=width)
