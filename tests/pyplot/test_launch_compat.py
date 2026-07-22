from __future__ import annotations

from importlib.util import find_spec
from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as plt
from xy._svg import COLORMAP_STOPS, _lut


def test_hist_weights_horizontal_and_stacked_return_matplotlib_geometry() -> None:
    fig, ax = plt.subplots()
    values = [np.arange(5), np.arange(5) + 1]
    weights = [np.ones(5), np.arange(1, 6)]
    counts, edges, containers = ax.hist(
        values, bins=3, weights=weights, orientation="horizontal", stacked=True
    )
    assert counts.shape == (2, 3)
    assert np.all(counts[1] >= counts[0])
    assert len(edges) == 4
    assert len(containers) == 2


def test_bar_snapshots_mutable_bottom_and_fill_between_segments_mask() -> None:
    _fig, ax = plt.subplots()
    bottom = np.zeros(3)
    ax.bar(["a", "b", "c"], [2, 3, 4], bottom=bottom)
    bottom += 10
    trace = ax._build_chart(640, 480).figure().traces[0]
    assert np.allclose(trace.y.values, [2, 3, 4])

    ax.fill_between(
        np.arange(6), np.arange(6), where=[True, True, False, True, True, True], step="mid"
    )
    areas = [entry for entry in ax._entries if entry["kind"] == "area"]
    assert len(areas) == 2
    assert all(np.isfinite(np.asarray(entry["x"], dtype=float)).all() for entry in areas)


def test_bar_labels_are_centered_over_vertical_bars() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0, 1], [10, 20])
    labels = ax.bar_label(bars, fmt="%.1f", padding=3)
    assert len(labels) == 2
    for label, center in zip(labels, [0, 1], strict=True):
        assert label._entry["args"][0] == center
        assert label._entry["kwargs"]["anchor"] == "middle"
        assert label._entry["kwargs"]["dx"] == 0.0
        assert label._entry["kwargs"]["dy"] == -8.0


def test_pyplot_legend_location_and_columns_reach_render_spec() -> None:
    _fig, ax = plt.subplots()
    ax.bar([0, 1], [10, 20], label="values")
    ax.legend(loc="upper left", ncols=3)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["loc"] == "upper left"
    assert spec["legend"]["ncols"] == 3
    # Frame styling now rides along so the static-export legend can honor
    # frameon/facecolor/edgecolor (previously only the DOM legend saw it).
    assert "style" in spec["legend"]


def test_legend_best_avoids_the_busy_corner_and_default_axes_are_boxed() -> None:
    _fig, ax = plt.subplots()
    ax.scatter(np.linspace(0.72, 0.98, 100), np.linspace(0.7, 0.98, 100), label="busy")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend()
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["loc"] in {"upper left", "lower left", "lower right"}
    assert spec["frame_sides"] == ["left", "bottom", "top", "right"]


def test_filled_stairs_use_seamless_bins_and_hatches_are_not_dropped() -> None:
    _fig, ax = plt.subplots()
    ax.stairs([1, 2], [0, 1, 2], fill=True)
    ax.stairs([0.5, 1], [2, 3, 4], orientation="horizontal", hatch="//")
    assert any(entry["kind"] == "bar" for entry in ax._entries)
    assert not any(entry.get("factory") == "triangle_mesh" for entry in ax._entries)
    hatch = [entry for entry in ax._entries if entry.get("factory") == "segments"][-1]
    assert len(hatch["args"][0]) == 14


def test_adding_external_step_patch_does_not_advance_color_cycle() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import StepPatch as MatplotlibStepPatch

    _fig, ax = plt.subplots()
    ax.add_patch(MatplotlibStepPatch([1, 2], [0, 1, 2]))
    ax.stairs([2, 1], [0, 1, 2], fill=True)
    filled = [entry for entry in ax._entries if entry["kind"] == "bar"]
    assert filled[2]["kwargs"]["color"] == "#1f77b4"


def test_masked_and_nan_lines_break_instead_of_bridging_missing_values() -> None:
    _fig, ax = plt.subplots()
    x = np.arange(5.0)
    masked = np.ma.masked_where(x == 2, x)
    ax.plot(x, masked, "o-")
    ax.plot(x, [0, 1, np.nan, 3, 4], "o-")
    segment_entries = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    assert len(segment_entries) == 2
    assert all(len(entry["args"][0]) == 2 for entry in segment_entries)


def test_line_collection_preserves_continuous_segment_colors() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots()
    collection = LineCollection(
        [[[0, 0], [1, 1]], [[1, 1], [2, 0]]], array=np.array([0.0, 1.0]), cmap="plasma"
    )
    artist = ax.add_collection(collection)
    fig.colorbar(artist, label="value")
    entry = ax._entries[-1]
    assert np.array_equal(entry["kwargs"]["color"], [0.0, 1.0])
    assert entry["kwargs"]["colormap"] == "plasma"
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["colorbar"] == {
        "colormap": "plasma",
        "domain": [0.0, 1.0],
        "label": "value",
        "orientation": "vertical",
    }


def test_colorbar_reads_original_matplotlib_scalar_mappable() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots()
    collection = LineCollection(
        [[[0, 0], [1, 1]], [[1, 1], [2, 0]]],
        array=np.array([0.0, 2.0]),
        cmap="plasma",
    )
    ax.add_collection(collection)
    fig.colorbar(collection)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["colorbar"]["domain"] == [0.0, 2.0]
    assert spec["colorbar"]["colormap"] == "plasma"


def test_image_colorbar_uses_norm_domain_and_owns_its_label() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import Normalize

    fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-2.0, 0.0, 2.0]]),
        cmap=plt.colormaps["gray"].with_extremes(under="green", over="red"),
        norm=Normalize(vmin=-1.0, vmax=1.0),
    )
    colorbar = fig.colorbar(image)
    colorbar.set_label("intensity")
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["colorbar"]["domain"] == [-1.0, 1.0]
    assert spec["colorbar"]["label"] == "intensity"
    assert ax._axis["y"].get("label") is None


def test_matplotlib_marker_sizes_are_converted_from_points_to_css_pixels() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], "o-")
    ax.scatter([0], [0])
    scatters = [entry for entry in ax._entries if entry["kind"] == "scatter"]
    # 6 pt marker path plus the centered 1 pt marker edge at figure DPI.
    assert scatters[0]["kwargs"]["size"] == pytest.approx(7 * 100 / 72)
    assert scatters[1]["kwargs"]["size"] == pytest.approx(7 * 100 / 72)


def test_explicit_line_color_does_not_advance_default_cycle() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], color="lightgrey")
    second = ax.plot([0, 1], [1, 0])[0]
    assert second.get_color() == "#1f77b4"


def test_truecolor_imshow_keeps_rgba_channels_in_payload() -> None:
    _fig, ax = plt.subplots()
    image = np.array([[[255, 0, 0, 255], [0, 255, 0, 128]]], dtype=np.uint8)
    ax.imshow(image, interpolation="nearest")
    spec, blob = ax._build_chart(320, 200).figure().build_payload()
    heatmap = spec["traces"][0]["heatmap"]
    meta = spec["columns"][heatmap["rgba_buf"]]
    packed = np.frombuffer(blob, dtype=np.uint8, count=meta["len"], offset=meta["byte_offset"])
    assert heatmap["enc"] == "rgba8"
    assert meta["dtype"] == "u8"
    assert meta["len"] == heatmap["w"] * heatmap["h"] * 4
    assert packed.reshape(-1, 4).tolist().count([255, 0, 0, 255]) == 2
    assert packed.reshape(-1, 4).tolist().count([0, 255, 0, 128]) == 2
    assert "buf" not in heatmap
    assert heatmap["h"] == 2


def test_boundary_norm_imshow_produces_discrete_truecolor_bands() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import BoundaryNorm

    cmap = plt.colormaps["gray"].with_extremes(under="green", over="red", bad="blue")
    _fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-2.0, -0.75, -0.25, 0.1, 0.75, 2.0]]),
        cmap=cmap,
        norm=BoundaryNorm([-1, -0.5, 0, 0.5, 1], ncolors=cmap.N),
    )
    rgba = np.asarray(image._entry["z"])
    assert rgba.shape == (2, 6, 4)
    assert not np.array_equal(rgba[0, 1], rgba[0, 2])
    assert np.allclose(rgba[0, 0, :3], [0.0, 128 / 255, 0.0], atol=0.02)
    assert np.allclose(rgba[0, -1, :3], [1.0, 0.0, 0.0], atol=0.02)


def test_normalize_with_extremes_remains_continuous() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import Normalize

    cmap = plt.colormaps["gray"].with_extremes(under="green", over="red")
    _fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-2.0, -0.5, 0.0, 0.5, 2.0]]),
        cmap=cmap,
        norm=Normalize(vmin=-1.0, vmax=1.0),
    )
    rgba = np.asarray(image._entry["z"])
    assert np.allclose(rgba[0, 2, :3], [0.5, 0.5, 0.5], atol=0.03)
    assert rgba[0, 1, 0] < rgba[0, 3, 0]


def test_affine_scalar_image_uses_transparent_rgba_outside_transform() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.transforms import Affine2D

    _fig, ax = plt.subplots()
    image = ax.imshow(np.arange(16, dtype=float).reshape(4, 4), origin="lower")
    image.set_transform(Affine2D().rotate_deg(30))
    rgba = np.asarray(image._entry["z"])
    assert rgba.shape == (4, 4, 4)
    assert np.any(rgba[..., 3] == 0.0)
    assert np.any(rgba[..., 3] == 1.0)


def test_filled_polygon_edge_is_one_outline_not_every_triangle_edge() -> None:
    _fig, ax = plt.subplots()
    ax.fill([0, 1, 1, 0], [0, 0, 1, 1], color="white", ec="black", lw=3)
    mesh = next(entry for entry in ax._entries if entry.get("factory") == "triangle_mesh")
    outline = next(entry for entry in ax._entries if entry.get("factory") == "segments")
    assert "stroke" not in mesh["kwargs"]
    assert len(outline["args"][0]) == 4
    assert outline["kwargs"]["width"] == 3.0


def test_streamplot_preserves_explicit_seeds_scalar_colors_and_widths() -> None:
    x = np.linspace(-1.0, 1.0, 20)
    y = np.linspace(-1.0, 1.0, 20)
    xx, yy = np.meshgrid(x, y)
    _fig, ax = plt.subplots()
    ax.streamplot(
        x,
        y,
        -yy,
        xx,
        start_points=np.array([[0.5, 0.0], [-0.5, 0.0]]),
        color=xx,
        linewidth=1.0 + np.abs(yy),
        cmap="viridis",
    )
    entries = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    has_matplotlib = find_spec("matplotlib") is not None
    if has_matplotlib:
        assert len(entries) > 1  # optional integrator retains varying widths
    else:
        assert entries  # dependency-free fallback still renders streamlines
    assert all(len(entry["args"][0]) > 0 for entry in entries)
    assert all(entry["kwargs"].get("domain") == (-1.0, 1.0) for entry in entries)
    if has_matplotlib:
        assert any(np.ptp(np.asarray(entry["kwargs"]["color"])) > 0 for entry in entries)
    else:
        assert all("color" in entry["kwargs"] for entry in entries)


def test_log_locator_contours_and_labels_use_real_contour_geometry() -> None:
    xx, yy = np.meshgrid(np.linspace(-2, 2, 40), np.linspace(-2, 2, 40))
    zz = 10.0 ** (2.0 * np.exp(-(xx**2 + yy**2)))
    _fig, ax = plt.subplots()
    contour = ax.contour(xx, yy, zz, locator=plt.LogLocator())
    labels = ax.clabel(contour, contour.levels)
    levels = np.asarray(contour.levels)
    assert np.allclose(levels, 10.0 ** np.arange(0, 3))
    positions = [label._entry["args"][:2] for label in labels]
    assert len(set(positions)) == len(positions)
    assert positions
    assert all(-2.0 <= x <= 2.0 and -2.0 <= y <= 2.0 for x, y in positions)


def test_parametric_line_preserves_input_order_instead_of_sorting_x() -> None:
    _fig, ax = plt.subplots()
    x = np.array([0.0, 1.0, 0.0, -1.0, 0.0])
    y = np.arange(len(x), dtype=float)
    ax.plot(x, y)
    trace = ax._build_chart(640, 480).figure().traces[0]
    assert trace.kind == "segments"
    assert np.array_equal(trace.x0.values, x[:-1])
    assert np.array_equal(trace.x1.values, x[1:])


def test_reversed_colormap_exact_ticks_and_fractional_annotations_export() -> None:
    fig, ax = plt.subplots()
    ax.imshow([[0.0, 1.0]], cmap="viridis_r")
    ax.set_xticks([0, 2, 4], ["zero", "two", "four"])
    ax.axhline(0.5, xmin=0.25, xmax=0.75)
    ax.text(0.5, 0.9, "axes text", transform=ax.transAxes, ha="center")
    core = ax._build_chart(640, 480).figure()
    spec, _blob = core.build_payload()
    assert spec["x_axis"]["tick_values"] == [0.0, 2.0, 4.0]
    assert spec["x_axis"]["tick_labels"] == ["zero", "two", "four"]
    assert np.array_equal(_lut("viridis_r", np.array([0.0]))[0], COLORMAP_STOPS["viridis"][-1])
    assert "axes text" in core.to_svg()
    assert fig._to_png().startswith(b"\x89PNG\r\n\x1a\n")


def test_imshow_interpolation_upsamples_gradients_but_nearest_keeps_cells() -> None:
    _fig, ax = plt.subplots()
    ax.imshow([[0.0, 1.0], [1.0, 0.0]], interpolation="bicubic")
    ax.imshow([[0.0, 1.0], [1.0, 0.0]], interpolation="nearest")
    assert np.asarray(ax._entries[0]["z"]).shape == (512, 512)
    assert np.asarray(ax._entries[1]["z"]).shape == (2, 2)
    core = ax._build_chart(640, 480).figure()
    spec, _blob = core.build_payload()
    assert spec["dom"]["style"]["--chart-grid"] == "transparent"
    assert 'stroke="transparent"' in core.to_svg()


def test_imshow_equal_aspect_preserves_explicit_extent_at_plot_edges() -> None:
    fig, ax = plt.subplots()
    ax.imshow(
        np.zeros((40, 50)),
        extent=[0, 5, 0, 5],
        origin="lower",
        interpolation="gaussian",
    )
    plt.colorbar()
    _doc, width, height = fig._to_notebook_html()
    assert (width, height) == (504, 418)
    core = ax._build_chart(width, height).figure()
    spec, _blob = core.build_payload()
    assert spec["x_axis"]["range"] == pytest.approx([0.0, 5.0])
    assert spec["y_axis"]["range"] == pytest.approx([0.0, 5.0])
    top, right, bottom, left = spec["padding"]
    # Equal x/y spans produce a square plot box after colorbar room is removed.
    assert width - left - right - 86 == pytest.approx(height - top - bottom)


def test_shared_subplots_link_live_views_and_grid_exports_keep_suptitle() -> None:
    fig, axes = plt.subplots(1, 2, sharex=True, sharey=True)
    axes[0].plot([0, 1], [0, 2])
    axes[1].plot([0, 2], [-1, 1])
    fig.suptitle("linked panels")
    figures = [chart.figure() for chart in fig._charts()]
    groups = {core.interaction.get("link_group") for core in figures}
    assert len(groups) == 1 and None not in groups
    assert all(core.interaction["link_axes"] == ["x", "y"] for core in figures)
    svg = BytesIO()
    fig.savefig(svg, format="svg")
    assert b"linked panels" in svg.getvalue()
    png = fig._to_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_boxplot_means_scatter_nonfinite_and_fontdict() -> None:
    _fig, ax = plt.subplots()
    box = ax.boxplot([[1, 2, 8], [2, 3, 4]], showmeans=True, meanline=True)
    assert box["means"]
    scatter = ax.scatter([0, 1, 2], [0, 1, 2], c=[0, np.nan, 2], plotnonfinite=False)
    assert len(np.asarray(scatter._entry["x"])) == 2
    text = ax.text(0, 0, "label", {"fontsize": 14, "fontfamily": "monospace"})
    assert text.get_text() == "label"
