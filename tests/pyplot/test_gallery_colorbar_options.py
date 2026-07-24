"""Regressions reduced from Matplotlib's colorbar gallery."""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean() -> None:
    plt.close("all")
    yield
    plt.close("all")


def test_colorbar_location_anchor_shrink_and_minor_ticks_reach_exports() -> None:
    fig, ax = plt.subplots()
    image = ax.imshow(np.arange(16).reshape(4, 4), cmap="Blues")

    colorbar = fig.colorbar(
        image,
        ax=ax,
        location="right",
        anchor=(0.0, 0.3),
        shrink=0.7,
    )
    colorbar.minorticks_on()

    assert ax._colorbar["orientation"] == "vertical"
    assert ax._colorbar["anchor"] == [0.0, 0.3]
    assert ax._colorbar["shrink"] == pytest.approx(0.7)
    assert ax._colorbar["minor_ticks"] is True

    svg = BytesIO()
    fig.savefig(svg, format="svg")
    assert b'data-xy-colorbar-minor="true"' in svg.getvalue()

    png = BytesIO()
    fig.savefig(png, format="png")
    assert png.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

    colorbar.minorticks_off()
    assert ax._colorbar["minor_ticks"] is False


def test_bottom_location_selects_horizontal_orientation() -> None:
    fig, ax = plt.subplots()
    image = ax.imshow(np.eye(3))

    fig.colorbar(image, ax=ax, location="bottom", shrink=0.5)

    assert ax._colorbar["orientation"] == "horizontal"
    assert ax._colorbar["shrink"] == pytest.approx(0.5)


def test_colorbar_domain_excludes_masked_image_values() -> None:
    fig, ax = plt.subplots()
    values = np.ma.masked_greater(np.asarray([[-2.0, -1.0], [1.0, 2.0]]), 0.0)
    image = ax.imshow(values, cmap="Blues")

    fig.colorbar(image, ax=ax)

    assert ax._colorbar["domain"] == [-2.0, -1.0]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"location": "left"}, "right or bottom"),
        ({"shrink": 0.0}, "shrink"),
        ({"anchor": (0.5,)}, "anchor"),
        ({"location": "right", "orientation": "horizontal"}, "incompatible"),
    ],
)
def test_colorbar_gallery_options_reject_invalid_values(
    kwargs: dict[str, object], message: str
) -> None:
    fig, ax = plt.subplots()
    image = ax.imshow(np.eye(3))

    with pytest.raises((ValueError, NotImplementedError), match=message):
        fig.colorbar(image, ax=ax, **kwargs)
