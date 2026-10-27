"""Exact contracts behind the remaining Matplotlib colorbar gallery blockers."""

from __future__ import annotations

import re
from collections.abc import Iterator
from io import BytesIO
from xml.etree import ElementTree

import numpy as np
import pytest

import xy.pyplot as plt


class LogNorm:
    """Dependency-free stand-in accepted through Matplotlib's type-name contract."""

    def __init__(self, vmin: float, vmax: float) -> None:
        self.vmin = vmin
        self.vmax = vmax


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    plt.close("all")
    yield
    plt.close("all")


def test_virtual_colorbar_has_one_position_box_for_both_query_modes() -> None:
    fig, ax = plt.subplots()
    image = ax.imshow(np.arange(4.0).reshape(2, 2))

    colorbar = fig.colorbar(image, shrink=0.7)

    active = colorbar.ax.get_position(original=False)
    original = colorbar.ax.get_position(original=True)
    assert original.bounds == pytest.approx(active.bounds)


def test_time_series_histogram_log_mesh_and_pad_zero_render_statically() -> None:
    """Reduced data, exact pcolormesh/colorbar calls from time_series_histogram.py."""
    fig, axes = plt.subplots(nrows=3, figsize=(6, 8), layout="constrained")
    cmap = plt.colormaps["plasma"]
    cmap = cmap.with_extremes(bad=cmap(0))
    xedges = np.linspace(0.0, 4.0 * np.pi, 5)
    yedges = np.linspace(-2.0, 2.0, 4)
    counts = np.asarray(
        [
            [0.0, 1.0, 10.0, 100.0],
            [2.0, 20.0, 150.0, 200.0],
            [0.0, 5.0, 50.0, 125.0],
        ]
    )

    log_mesh = axes[1].pcolormesh(
        xedges,
        yedges,
        counts,
        cmap=cmap,
        norm="log",
        vmax=1.5e2,
        rasterized=True,
    )
    fig.colorbar(log_mesh, ax=axes[1], label="# points", pad=0)
    linear_mesh = axes[2].pcolormesh(
        xedges,
        yedges,
        counts,
        cmap=cmap,
        vmax=1.5e2,
        rasterized=True,
    )
    fig.colorbar(linear_mesh, ax=axes[2], label="# points", pad=0)

    rgba = np.asarray(log_mesh._entry["args"][0])
    assert rgba.shape == counts.shape + (4,)
    assert log_mesh.get_rasterized() is True
    assert log_mesh._entry["_mpl_domain"] == (1.0, 150.0)
    assert log_mesh._entry["_mpl_norm_scale"] == "log"
    np.testing.assert_allclose(rgba[0, 0], rgba[0, 1])
    np.testing.assert_allclose(rgba[1, 3], np.asarray(cmap(1.0)))
    assert axes[1]._colorbar == {
        "colormap": "plasma",
        "domain": [1.0, 150.0],
        "label": "# points",
        "orientation": "vertical",
        "scale": "log",
        "pad": 0.0,
    }

    fig._charts()
    for index in (1, 2):
        allocated_width = round(600 * fig._effective_rects()[index][2])
        expected_room = 80.0  # pad=0 vertical chrome (62) + label (18)
        assert axes[index]._plot_box_px[2] == pytest.approx(allocated_width - expected_room)

    svg_target = BytesIO()
    fig.savefig(svg_target, format="svg")
    svg = svg_target.getvalue().decode()
    assert "xy-colorbar-plasma" in svg
    assert ">1</text>" in svg and ">10</text>" in svg and ">100</text>" in svg

    png_target = BytesIO()
    fig.savefig(png_target, format="png")
    pixels = np.asarray(plt.imread(BytesIO(png_target.getvalue())))
    assert pixels.shape == (800, 600, 4)


def test_hexbin_demo_log_colorbar_keeps_counts_and_covers_svg_cell_seams() -> None:
    """Exact data and log-mappable calls from statistics/hexbin_demo.py."""
    np.random.seed(19680801)
    n = 100_000
    x = np.random.standard_normal(n)
    y = 2.0 + 3.0 * x + 4.0 * np.random.standard_normal(n)
    fig, ax = plt.subplots(figsize=(4.5, 4))

    hexagons = ax.hexbin(x, y, gridsize=50, bins="log", cmap="inferno")
    fig.colorbar(hexagons, ax=ax, label="counts")

    core = fig._charts()[0].figure()
    trace = core.traces[0]
    assert trace.colorbar_domain == (1.0, 575.0)
    assert trace.colorbar_scale == "log"
    assert trace.color_ch.domain == pytest.approx((0.0, np.log(575.0)))
    assert core.colorbar_options == {
        "colormap": "inferno",
        "domain": [1.0, 575.0],
        "label": "counts",
        "orientation": "vertical",
        "scale": "log",
    }

    target = BytesIO()
    fig.savefig(target, format="svg")
    svg = target.getvalue().decode()
    colorbar = svg[svg.rfind('<defs><linearGradient id="xy-colorbar-inferno"') :]
    assert re.findall(r">([^<>]+)</text>", colorbar) == ["1", "10", "100", "counts"]

    root = ElementTree.fromstring(svg)
    cells = [node for node in root.iter() if node.tag.endswith("polygon")]
    assert len(cells) > 1_000
    assert all(node.get("fill") == node.get("stroke") for node in cells)
    assert all(node.get("stroke-width") == "0.5" for node in cells)


def test_subplots_adjust_explicit_cax_fills_requested_axes_in_static_exports() -> None:
    """Exact subplot/cax calls from subplots_adjust.py."""
    np.random.seed(19680801)
    fig = plt.figure(figsize=(6.4, 4.8), dpi=100)
    top = plt.subplot(211)
    plt.imshow(np.random.random((20, 20)))
    bottom = plt.subplot(212)
    image = plt.imshow(np.random.random((20, 20)))
    plt.subplots_adjust(bottom=0.1, right=0.8, top=0.9)
    cax = plt.axes((0.85, 0.1, 0.075, 0.8))
    colorbar = plt.colorbar(cax=cax)

    assert colorbar.ax is cax
    assert cax.get_position().bounds == pytest.approx((0.85, 0.1, 0.075, 0.8))
    assert cax._colorbar["placement"] == "axes"
    assert top._colorbar is None
    assert bottom._colorbar is None
    assert cax._colorbar_source is image._entry

    svg_target = BytesIO()
    fig.savefig(svg_target, format="svg")
    svg = svg_target.getvalue().decode()
    assert re.search(r'<svg[^>]+width="640"[^>]+height="480"', svg)
    assert "xy-colorbar-viridis" in svg

    png_target = BytesIO()
    fig.savefig(png_target, format="png")
    pixels = np.asarray(plt.imread(BytesIO(png_target.getvalue())))
    assert pixels.shape == (480, 640, 4)
    colorbar_pixels = pixels[48:432, 544:592, :3]
    assert np.ptp(colorbar_pixels.mean(axis=1), axis=0).max() > 0.5
    assert np.mean(np.ptp(colorbar_pixels, axis=0)) > 0.1


def test_log_norm_bounds_and_colorbar_pad_validate_loudly() -> None:
    fig, ax = plt.subplots()
    values = np.asarray([[0.0, 1.0], [10.0, 100.0]])

    with pytest.raises(ValueError, match="positive"):
        ax.pcolormesh(np.zeros((2, 2)), norm="log")
    with pytest.raises(ValueError, match="Invalid"):
        ax.pcolormesh(values, norm="log", vmin=0.0)

    image = ax.imshow(values)
    with pytest.raises(ValueError, match="nonnegative"):
        fig.colorbar(image, pad=-0.01)
    with pytest.raises(ValueError, match="nonnegative"):
        fig.colorbar(image, pad=np.inf)


def test_imshow_uses_the_same_log_normalization_and_colorbar_contract() -> None:
    fig, ax = plt.subplots()
    cmap = plt.colormaps["plasma"].with_extremes(bad=plt.colormaps["plasma"](0))
    values = np.asarray([[0.0, 1.0], [10.0, 100.0]])

    image = ax.imshow(values, cmap=cmap, norm="log", vmax=100.0)
    fig.colorbar(image)

    assert image._entry["z"].shape == (2, 2, 4)
    assert image._entry["_mpl_domain"] == (1.0, 100.0)
    assert image._entry["_mpl_norm_scale"] == "log"
    assert ax._colorbar["domain"] == [1.0, 100.0]
    assert ax._colorbar["scale"] == "log"

    svg_target = BytesIO()
    fig.savefig(svg_target, format="svg")
    svg = svg_target.getvalue().decode()
    assert ">1</text>" in svg and ">10</text>" in svg and ">100</text>" in svg


def test_rasterized_setter_round_trips_only_for_image_backed_meshes() -> None:
    _fig, ax = plt.subplots()
    mesh = ax.pcolormesh(np.arange(4.0).reshape(2, 2))

    mesh.set_rasterized(True)
    assert mesh.get_rasterized() is True
    mesh.set_rasterized(False)
    assert mesh.get_rasterized() is False

    x = np.asarray([[0.0, 1.0, 2.0], [0.0, 0.8, 2.0], [0.0, 1.0, 2.0]])
    y = np.asarray([[0.0, 0.0, 0.0], [1.0, 1.2, 1.0], [2.0, 2.0, 2.0]])
    triangle_mesh = ax.pcolormesh(x, y, np.arange(4.0).reshape(2, 2))
    with pytest.raises(NotImplementedError, match="selective rasterization"):
        triangle_mesh.set_rasterized(True)


def test_nonuniform_mesh_accepts_a_log_norm_instance() -> None:
    _fig, ax = plt.subplots()
    x = np.asarray([[0.0, 1.0, 2.0], [0.0, 0.8, 2.0], [0.0, 1.0, 2.0]])
    y = np.asarray([[0.0, 0.0, 0.0], [1.0, 1.2, 1.0], [2.0, 2.0, 2.0]])

    mesh = ax.pcolormesh(
        x,
        y,
        np.asarray([[1.0, 2.0], [3.0, 4.0]]),
        norm=LogNorm(1.0, 4.0),
    )

    assert mesh._entry["_mpl_domain"] == (1.0, 4.0)
    assert mesh._entry["_mpl_norm_scale"] == "log"
    assert np.asarray(mesh._entry["kwargs"]["color"]).shape[-1] == 4


def test_colorbar_consumes_mappable_extend_when_not_explicitly_overridden() -> None:
    fig, ax = plt.subplots()
    values = np.arange(16.0).reshape(4, 4)
    contour = ax.contourf(values, levels=[2.0, 6.0, 10.0], extend="both")

    fig.colorbar(contour)

    assert ax._colorbar["extend"] == "both"
    svg_target = BytesIO()
    fig.savefig(svg_target, format="svg")
    assert svg_target.getvalue().count(b"<polygon") >= 2
