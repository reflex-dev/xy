"""Bounded semantic and perceptual comparisons with the pinned reference."""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as xyplt

mpl = pytest.importorskip("matplotlib")
mpl.use("Agg")
import matplotlib.pyplot as mplplt  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_state():
    xyplt.close("all")
    mplplt.close("all")
    yield
    xyplt.close("all")
    mplplt.close("all")


def test_reference_line_data_cycle_limits_ticks_and_shared_axes() -> None:
    xyfig, xyaxes = xyplt.subplots(2, 1, sharex=True)
    mplfig, mplaxes = mplplt.subplots(2, 1, sharex=True)
    del mplfig
    for axes in (xyaxes, mplaxes):
        axes[0].plot([0, 1, 2], [2, 1, 4])
        axes[0].plot([0, 1, 2], [1, 3, 2])
        axes[0].set_xlim(-0.25, 2.25)
        axes[0].set_ylim(0.5, 4.5)
        axes[0].set_xticks([0, 1, 2], ["a", "b", "c"])
        axes[0].set_xlabel("category")
    for xyline, mplline in zip(xyaxes[0].lines, mplaxes[0].lines, strict=True):
        np.testing.assert_array_equal(xyline.get_xdata(), mplline.get_xdata())
        np.testing.assert_array_equal(xyline.get_ydata(), mplline.get_ydata())
        np.testing.assert_allclose(to_rgba(xyline.get_color()), to_rgba(mplline.get_color()))
    np.testing.assert_allclose(xyaxes[0].get_xlim(), mplaxes[0].get_xlim())
    np.testing.assert_allclose(xyaxes[0].get_ylim(), mplaxes[0].get_ylim())
    assert xyfig._sharex
    assert mplaxes[0].get_shared_x_axes().joined(mplaxes[0], mplaxes[1])
    np.testing.assert_array_equal(xyaxes[0].get_xticks(), mplaxes[0].get_xticks())
    assert xyaxes[0].get_xlabel() == mplaxes[0].get_xlabel()


def test_reference_bar_geometry_stacking_and_container_shape() -> None:
    xyfig, xyax = xyplt.subplots()
    mplfig, mplax = mplplt.subplots()
    del xyfig, mplfig
    x = np.array([0.0, 1.0, 2.0])
    heights = np.array([2.0, 3.0, 1.0])
    bottoms = np.array([1.0, 0.5, 2.0])
    xycontainer = xyax.bar(x, heights, width=0.6, bottom=bottoms, label="values")
    mplcontainer = mplax.bar(x, heights, width=0.6, bottom=bottoms, label="values")
    mpl_centers = [patch.get_x() + patch.get_width() / 2 for patch in mplcontainer.patches]
    np.testing.assert_allclose(xycontainer.position_centers, mpl_centers)
    np.testing.assert_allclose(xycontainer.bottoms, [patch.get_y() for patch in mplcontainer])
    np.testing.assert_allclose(
        xycontainer.tops, [patch.get_y() + patch.get_height() for patch in mplcontainer]
    )
    assert np.asarray(xycontainer.datavalues).shape == mplcontainer.datavalues.shape


@pytest.mark.parametrize(
    "options",
    [
        {"stacked": True},
        {"density": True},
        {"cumulative": True},
        {"density": True, "cumulative": True},
        {"stacked": True, "cumulative": True},
    ],
)
def test_reference_histogram_counts_edges_density_cumulative_and_stacking(options) -> None:
    values = [np.array([0.0, 0.2, 0.8, 1.5]), np.array([0.1, 0.7, 1.2, 1.8])]
    weights = [np.array([1.0, 2.0, 1.0, 3.0]), np.array([2.0, 1.0, 2.0, 1.0])]
    _xyfig, xyax = xyplt.subplots()
    _mplfig, mplax = mplplt.subplots()
    xycounts, xyedges, xycontainers = xyax.hist(
        values, bins=[0, 0.5, 1, 2], weights=weights, **options
    )
    mplcounts, mpledges, mplcontainers = mplax.hist(
        values, bins=[0, 0.5, 1, 2], weights=weights, **options
    )
    np.testing.assert_allclose(xycounts, mplcounts)
    np.testing.assert_allclose(xyedges, mpledges)
    assert len(xycontainers) == len(mplcontainers)


def test_reference_image_extent_dimensions_origin_and_normalization_domain() -> None:
    data = np.arange(12.0).reshape(3, 4)
    extent = (10.0, 14.0, -2.0, 1.0)
    _xyfig, xyax = xyplt.subplots()
    _mplfig, mplax = mplplt.subplots()
    xyimage = xyax.imshow(data, extent=extent, origin="lower", vmin=2.0, vmax=9.0)
    mplimage = mplax.imshow(data, extent=extent, origin="lower", vmin=2.0, vmax=9.0)
    assert np.asarray(xyimage.get_array()).shape == np.asarray(mplimage.get_array()).shape
    np.testing.assert_array_equal(xyimage.get_array(), mplimage.get_array())
    np.testing.assert_allclose(xyimage.get_extent(), mplimage.get_extent())
    np.testing.assert_allclose(xyimage._entry["kwargs"]["domain"], mplimage.get_clim())
    assert (xyax.get_ylim()[0] > xyax.get_ylim()[1]) == mplax.yaxis_inverted()


def _png_pixels(data: bytes) -> np.ndarray:
    pixels = np.asarray(xyplt.imread(BytesIO(data)), dtype=np.float64)
    if pixels.max(initial=0.0) > 1.0:
        pixels /= 255.0
    return pixels


def _foreground_mask(pixels: np.ndarray) -> np.ndarray:
    rgb = pixels[..., :3]
    corners = np.stack((rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]))
    background = np.median(corners, axis=0)
    distance = np.linalg.norm(rgb - background, axis=-1)
    alpha = pixels[..., 3] if pixels.shape[-1] == 4 else np.ones(distance.shape)
    return (distance > 0.08) & (alpha > 0.1)


def _dilate(mask: np.ndarray, radius: int = 5) -> np.ndarray:
    padded = np.pad(mask, radius)
    result = np.zeros_like(mask)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            result |= padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
    return result


@pytest.mark.parametrize("family", ["line", "bar", "image"])
def test_reference_pngs_have_tolerant_perceptual_and_geometry_agreement(family: str) -> None:
    # xy's static renderer has a documented 640x480 minimum canvas.  Render the
    # reference at that same comparison canvas; figsize parity itself is not an
    # exact contract at sub-minimum sizes.
    xyfig, xyax = xyplt.subplots(figsize=(4, 3), dpi=80)
    mplfig, mplax = mplplt.subplots(figsize=(8, 6), dpi=80)
    if family == "line":
        for ax in (xyax, mplax):
            ax.plot([0, 1, 2, 3], [0, 2, 1, 3], "o-", color="#2563eb", linewidth=2)
            ax.set(xlabel="x", ylabel="y", title="line")
    elif family == "bar":
        for ax in (xyax, mplax):
            ax.bar([0, 1, 2], [2, 4, 3], color="#f97316", width=0.7)
            ax.set_title("bar")
    else:
        grid = np.arange(25.0).reshape(5, 5)
        for ax in (xyax, mplax):
            ax.imshow(grid, origin="lower", cmap="viridis", interpolation="nearest")
            ax.set_title("image")
    xybytes = xyfig._to_png()
    reference = BytesIO()
    mplfig.savefig(reference, format="png", dpi=80)
    xypixels, mplpixels = _png_pixels(xybytes), _png_pixels(reference.getvalue())
    assert xypixels.shape == mplpixels.shape == (480, 640, 4)
    xymask, mplmask = _foreground_mask(xypixels), _foreground_mask(mplpixels)
    overlap = np.count_nonzero(_dilate(xymask) & _dilate(mplmask))
    union = np.count_nonzero(_dilate(xymask) | _dilate(mplmask))
    assert overlap / max(1, union) > 0.08
    xy_fraction = np.mean(xymask)
    mpl_fraction = np.mean(mplmask)
    assert 0.1 < xy_fraction / mpl_fraction < 10.0
    xy_luma = np.mean(xypixels[..., :3], axis=-1)[xymask].mean()
    mpl_luma = np.mean(mplpixels[..., :3], axis=-1)[mplmask].mean()
    assert abs(xy_luma - mpl_luma) < 0.45
