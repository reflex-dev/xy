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


def test_reference_contour_levels_and_triangle_topology() -> None:
    grid = np.arange(16.0).reshape(4, 4)
    _xyfig, xyax = xyplt.subplots()
    _mplfig, mplax = mplplt.subplots()
    xy_contour = xyax.contour(grid, levels=[3.0, 7.0, 11.0])
    mpl_contour = mplax.contour(grid, levels=[3.0, 7.0, 11.0])
    np.testing.assert_allclose(xy_contour.levels, mpl_contour.levels)

    x = np.array([0.0, 1.0, 0.0, 1.0])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    triangles = np.array([[0, 1, 2], [1, 3, 2]])
    values = np.array([0.0, 1.0, 2.0, 3.0])
    xy_tri = xyax.tripcolor(x, y, values, triangles=triangles)
    mpl_tri = mplax.tripcolor(x, y, triangles, values)
    assert len(xy_tri._entry["args"][0]) == len(mpl_tri.get_paths())
    np.testing.assert_allclose(xyax.get_xlim(), mplax.get_xlim(), atol=0.06)
    np.testing.assert_allclose(xyax.get_ylim(), mplax.get_ylim(), atol=0.06)


def test_reference_vector_directions_scatter_masks_and_removable_handles() -> None:
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([1.0, 2.0, 3.0])
    u = np.array([1.0, 0.0, -1.0])
    v = np.array([0.0, 1.0, 0.0])
    _xyfig, xyax = xyplt.subplots()
    _mplfig, mplax = mplplt.subplots()
    xy_quiver = xyax.quiver(x, y, u, v, scale=1)
    mpl_quiver = mplax.quiver(x, y, u, v, scale=1)
    np.testing.assert_allclose(mpl_quiver.X, x)
    np.testing.assert_allclose(mpl_quiver.Y, y)
    shafts = np.arange(0, len(xy_quiver._entry["args"][0]), 3)
    dx = xy_quiver._entry["args"][2][shafts] - xy_quiver._entry["args"][0][shafts]
    dy = xy_quiver._entry["args"][3][shafts] - xy_quiver._entry["args"][1][shafts]
    np.testing.assert_allclose(np.arctan2(dy, dx), np.arctan2(v, u))

    colors = np.ma.array([0.0, 1.0, 2.0], mask=[False, True, False])
    xy_scatter = xyax.scatter(x, y, c=colors, s=[4.0, 9.0, 16.0])
    mpl_scatter = mplax.scatter(x, y, c=colors, s=[4.0, 9.0, 16.0])
    np.testing.assert_array_equal(
        np.ma.getmaskarray(xy_scatter.get_array()), np.ma.getmaskarray(mpl_scatter.get_array())
    )
    before_xy, before_mpl = len(xyax.collections), len(mplax.collections)
    xy_scatter.remove()
    mpl_scatter.remove()
    assert len(xyax.collections) == before_xy - 1
    assert len(mplax.collections) == before_mpl - 1


def test_reference_truecolor_rgba_is_preserved() -> None:
    rgba = np.array(
        [
            [[1.0, 0.0, 0.0, 0.25], [0.0, 1.0, 0.0, 0.5]],
            [[0.0, 0.0, 1.0, 0.75], [1.0, 1.0, 1.0, 1.0]],
        ]
    )
    _xyfig, xyax = xyplt.subplots()
    _mplfig, mplax = mplplt.subplots()
    xy_image = xyax.imshow(rgba, interpolation="nearest")
    mpl_image = mplax.imshow(rgba, interpolation="nearest")
    np.testing.assert_allclose(xy_image.get_array(), mpl_image.get_array())


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


# Per-family floors for the cross-engine mask IoU; the negative control below
# asserts a wrong-geometry render scores under every one of these.
MINIMUM_IOU = {"line": 0.20, "bar": 0.70, "image": 0.55}


def _dilate(mask: np.ndarray, radius: int = 5) -> np.ndarray:
    padded = np.pad(mask, radius)
    result = np.zeros_like(mask)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            result |= padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
    return result


def _normalize_mask(mask: np.ndarray, size: int = 256) -> np.ndarray:
    """Crop renderer margins and fit geometry into an aspect-preserving box."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return np.zeros((size, size), dtype=bool)
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    scale = size / max(crop.shape)
    height = max(1, round(crop.shape[0] * scale))
    width = max(1, round(crop.shape[1] * scale))
    yi = np.linspace(0, crop.shape[0] - 1, height).astype(int)
    xi = np.linspace(0, crop.shape[1] - 1, width).astype(int)
    result = np.zeros((size, size), dtype=bool)
    y0, x0 = (size - height) // 2, (size - width) // 2
    result[y0 : y0 + height, x0 : x0 + width] = crop[np.ix_(yi, xi)]
    return result


@pytest.mark.parametrize("family", ["line", "bar", "image"])
def test_reference_pngs_have_tolerant_perceptual_and_geometry_agreement(family: str) -> None:
    # Both backends rasterize the 4x3-inch figure at the requested 80 DPI, so
    # point-sized strokes, markers, and text are compared at the same physical
    # size rather than hiding a pyplot-only 2x export scale in the reference.
    xyfig, xyax = xyplt.subplots(figsize=(4, 3), dpi=80)
    mplfig, mplax = mplplt.subplots(figsize=(4, 3), dpi=80)
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
    assert xypixels.shape == mplpixels.shape == (240, 320, 4)
    xymask, mplmask = _foreground_mask(xypixels), _foreground_mask(mplpixels)
    normalized_xy = _dilate(_normalize_mask(xymask))
    normalized_mpl = _dilate(_normalize_mask(mplmask))
    overlap = np.count_nonzero(normalized_xy & normalized_mpl)
    union = np.count_nonzero(normalized_xy | normalized_mpl)
    assert overlap / max(1, union) > MINIMUM_IOU[family]
    xy_fraction = np.mean(xymask)
    mpl_fraction = np.mean(mplmask)
    assert 0.5 < xy_fraction / mpl_fraction < 2.0
    xy_luma = np.mean(xypixels[..., :3], axis=-1)[xymask].mean()
    mpl_luma = np.mean(mplpixels[..., :3], axis=-1)[mplmask].mean()
    assert abs(xy_luma - mpl_luma) < 0.20


def test_perceptual_oracle_rejects_blank_and_wrong_geometry() -> None:
    reference = np.zeros((100, 100), dtype=bool)
    reference[20:80, 45:55] = True
    blank = np.zeros_like(reference)
    wrong = np.zeros_like(reference)
    wrong[45:55, 20:80] = True
    for candidate in (blank, wrong):
        left = _dilate(_normalize_mask(candidate))
        right = _dilate(_normalize_mask(reference))
        iou = np.count_nonzero(left & right) / max(1, np.count_nonzero(left | right))
        # tied to the live thresholds: loosening MINIMUM_IOU below the score a
        # wrong-geometry render can reach must fail here, not pass silently
        assert iou < min(MINIMUM_IOU.values())
