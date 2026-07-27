"""Regressions reduced from Matplotlib's layout gallery examples."""

from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _textblock
from xy.pyplot._grid import _composite_rgba
from xy.pyplot._mplfig import _measured_axis_chrome


def test_set_aspect_accepts_positional_adjustable() -> None:
    _fig, ax = plt.subplots()
    ax.plot([-3.0, 3.0], [-3.0, 3.0])

    ax.set_aspect("equal", "box")

    assert ax._aspect_equal is True
    assert ax._aspect_adjustable == "box"


def test_log_scale_after_equal_aspect_recomputes_stale_linear_bounds() -> None:
    _fig, ax = plt.subplots()
    ax.plot([1.0, 10.0], [1.0, 2.0])
    ax.set_aspect("equal")

    ax.set_xscale("log")

    assert all(np.isfinite(ax.get_position().bounds))


def test_uniform_subplot_axes_expose_one_shared_gridspec() -> None:
    fig, axes = plt.subplots(nrows=3, ncols=3)

    gridspec = axes[1, 2].get_gridspec()

    assert gridspec is axes[0, 0].get_gridspec()
    assert gridspec is axes[2, 2].get_gridspec()
    assert gridspec.nrows == 3
    assert gridspec.ncols == 3
    assert axes[1, 2].get_subplotspec().rows == (1, 2)
    assert axes[1, 2].get_subplotspec().cols == (2, 3)

    for ax in axes[1:, -1]:
        ax.remove()
    spanning = fig.add_subplot(gridspec[1:, -1])

    assert spanning.get_gridspec() is gridspec
    assert spanning.get_subplotspec().rows == (1, 3)
    assert spanning.get_subplotspec().cols == (2, 3)
    assert (fig._nrows, fig._ncols) == (3, 3)


def test_absolute_subplot_composition_preserves_neighboring_spines() -> None:
    fig, _axes = plt.subplots(nrows=1, ncols=2, figsize=(6.4, 4.8))
    output = BytesIO()

    fig.savefig(output, dpi=100, format="png")
    output.seek(0)

    pixels = np.asarray(plt.imread(output))
    left_rect = fig._effective_rects()[0]
    scale = pixels.shape[1] / 640
    right = round((left_rect[0] + left_rect[2]) * 640 * scale)
    top = round((1.0 - left_rect[1] - left_rect[3]) * 480 * scale)
    bottom = round((1.0 - left_rect[1]) * 480 * scale)
    spine_strip = pixels[top:bottom, right - 2 : right + 3, :3]
    dark_threshold = 128 if np.issubdtype(spine_strip.dtype, np.integer) else 0.5
    dark_by_column = np.all(spine_strip < dark_threshold, axis=2).sum(axis=0)

    assert dark_by_column.max() > 0.9 * (bottom - top)


def test_constrained_subplot_xlabels_stay_inside_static_canvas() -> None:
    """The invert-axes gallery xlabel reached the panel edge and was clipped."""
    fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(6.4, 4), layout="constrained")
    fig.suptitle("Inverted axis with ...")
    for ax in axes:
        ax.plot([0.01, 4.0], [1.0, 0.02])
        ax.set_title("fixed limits: set_xlim(4, 0)")
        ax.set_xlabel("decreasing x ⟶")

    svg_output = BytesIO()
    fig.savefig(svg_output, format="svg")
    root = ElementTree.fromstring(svg_output.getvalue())
    panels = [node for node in root if node.tag.endswith("svg")]
    assert len(panels) == 2
    for panel in panels:
        label = next(
            node
            for node in panel.iter()
            if node.tag.endswith("text") and "".join(node.itertext()) == "decreasing x ⟶"
        )
        block = _textblock.measure("decreasing x ⟶", float(label.attrib["font-size"]))
        remaining = float(panel.attrib["height"]) - (float(label.attrib["y"]) + block.descent)
        assert remaining >= 3.5

    png_output = BytesIO()
    fig.savefig(png_output, format="png")
    png_output.seek(0)
    pixels = np.asarray(plt.imread(png_output))
    rgb = pixels[:, :, :3]
    white = 0.99 if np.issubdtype(rgb.dtype, np.floating) else 250
    # Four fully blank rows prove the antialiased glyph edge remains inside
    # the canvas without demanding a fifth whole pixel beyond the SVG's
    # independently measured 3.5 px clearance.
    assert np.all(rgb[-4:] >= white)


def test_tight_layout_reserves_subplot_tick_chrome() -> None:
    fig, axes = plt.subplots(nrows=3, ncols=3, figsize=(6.4, 4.8))
    axes[1, 2].get_gridspec()

    fig.tight_layout()

    first = axes[0, 0]._figure_rect
    second = axes[0, 1]._figure_rect
    below = axes[1, 0]._figure_rect
    assert first is not None and second is not None and below is not None
    horizontal_gap = (second[0] - first[0] - first[2]) * 640
    vertical_gap = (first[1] - below[1] - below[3]) * 480
    assert horizontal_gap >= 57
    assert vertical_gap >= 43


def test_tight_layout_recomputes_materialized_subplot_rectangles() -> None:
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(6.4, 4.8))

    fig.tight_layout()
    first = axes[0, 0]._figure_rect
    fig.tight_layout(pad=3.0)
    second = axes[0, 0]._figure_rect

    assert first is not None and second is not None
    assert second != first
    assert second[0] > first[0]
    assert second[2] < first[2]


def test_subplots_constrained_layout_reserves_subplot_tick_chrome() -> None:
    plt.close("all")
    fig, _axes = plt.subplots(nrows=1, ncols=3, figsize=(8, 4), layout="constrained")

    first, second, _third = fig._effective_rects()
    assert fig._layout_options["engine"] == "tight"
    assert (second[0] - first[0] - first[2]) * 800 >= 57


def test_subplot_mosaic_constrained_layout_reserves_subplot_tick_chrome() -> None:
    plt.close("all")
    fig, _axes = plt.subplot_mosaic(
        [["no_norm", "density", "weight"]],
        figsize=(8, 4),
        layout="constrained",
    )

    first, second, _third = fig._effective_rects()
    assert fig._layout_options["engine"] == "tight"
    assert (second[0] - first[0] - first[2]) * 800 >= 57


def test_constrained_layout_remeasures_final_rotated_category_labels() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), layout="constrained")
    empty_rect = fig._effective_rects()[0]
    labels = [
        "United States",
        "Democratic Republic of the Congo",
        "United Kingdom",
        "Papua New Guinea",
    ]

    ax.bar(labels, [4, 3, 2, 1])
    ax.tick_params("x", rotation=45, rotation_mode="xtick")

    assert fig._layout_dirty is True
    final_rect = fig._effective_rects()[0]
    assert fig._layout_dirty is False
    assert final_rect[1] > empty_rect[1]

    charts = fig._charts()
    spec, _blob = charts[0].figure().build_payload()
    from xy import _svg

    _width, height, _compact, plot = _svg.layout(spec)
    assert height - plot["y"] - plot["h"] > 80

    png = BytesIO()
    svg = BytesIO()
    fig.savefig(png, format="png", dpi=100)
    fig.savefig(svg, format="svg", dpi=100)
    assert png.getvalue().startswith(b"\x89PNG")
    assert b"rotate(-45" in svg.getvalue()


def test_subplot_mosaic_string_preserves_spans_holes_and_ratios() -> None:
    plt.close("all")
    fig, axes = plt.subplot_mosaic(
        "AA;B.",
        figsize=(6.4, 4.8),
        width_ratios=(4, 1),
        height_ratios=(1, 4),
    )

    assert list(axes) == ["A", "B"]
    assert fig.axes == [axes["A"], axes["B"]]
    assert fig._width_ratios == (4.0, 1.0)
    assert fig._height_ratios == (1.0, 4.0)
    assert axes["A"].get_subplotspec().rows == (0, 1)
    assert axes["A"].get_subplotspec().cols == (0, 2)
    assert axes["B"].get_subplotspec().rows == (1, 2)
    assert axes["B"].get_subplotspec().cols == (0, 1)

    top = axes["A"].get_position().bounds
    lower = axes["B"].get_position().bounds
    grid = axes["A"].get_gridspec()
    lower_right = grid.cell_rect((1, 2), (1, 2))
    assert top[0] == pytest.approx(lower[0])
    assert top[2] == pytest.approx(0.775)
    assert lower[2] == pytest.approx(4 * lower_right[2])
    assert lower[3] == pytest.approx(4 * top[3])


def test_subplot_mosaic_multiline_string_and_custom_sentinel() -> None:
    plt.close("all")
    fig, axes = plt.subplot_mosaic(
        """
        AA
        B_
        """,
        empty_sentinel="_",
    )

    assert set(axes) == {"A", "B"}
    assert len(fig.axes) == 2
    assert axes["A"].get_subplotspec().cols == (0, 2)
    assert axes["B"].get_subplotspec().rows == (1, 2)


def test_subplot_mosaic_strips_each_multiline_row() -> None:
    fig, axes = plt.subplot_mosaic(
        """
        AA
          B_
        """,
        empty_sentinel="_",
    )

    assert set(axes) == {"A", "B"}
    assert len(fig.axes) == 2
    assert axes["A"].get_subplotspec().cols == (0, 2)
    assert axes["B"].get_subplotspec().cols == (0, 1)


def test_provisional_chrome_probe_restores_equal_aspect_domains() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8))
    ax.imshow(np.arange(8).reshape(2, 4), extent=(0.0, 4.0, 0.0, 2.0))
    ax.set_aspect("equal", adjustable="box")
    before = {axis: dict(ax._axis_props(axis)) for axis in ("x", "y")}
    had_plot_px = hasattr(ax, "_materialize_plot_px")
    before_plot_px = getattr(ax, "_materialize_plot_px", None)

    measured = _measured_axis_chrome(ax, 320, 180)

    assert all(value >= 0.0 for value in measured)
    assert {axis: dict(ax._axis_props(axis)) for axis in ("x", "y")} == before
    assert hasattr(ax, "_materialize_plot_px") is had_plot_px
    assert getattr(ax, "_materialize_plot_px", None) == before_plot_px


def test_subplot_mosaic_list_form_matches_spectrum_gallery_geometry() -> None:
    plt.close("all")
    fig, axes = plt.subplot_mosaic(
        [
            ["signal", "signal"],
            ["magnitude", "log_magnitude"],
            ["phase", "angle"],
        ]
    )

    assert list(axes) == ["signal", "magnitude", "log_magnitude", "phase", "angle"]
    assert len(fig.axes) == 5
    assert axes["signal"].get_subplotspec().rows == (0, 1)
    assert axes["signal"].get_subplotspec().cols == (0, 2)
    signal = axes["signal"].get_position().bounds
    magnitude = axes["magnitude"].get_position().bounds
    assert signal[2] > 2 * magnitude[2]


def test_figure_constrained_layout_reflows_a_later_spectrum_mosaic() -> None:
    """The gallery builds the figure before calling ``fig.subplot_mosaic``."""
    plt.close("all")
    fig = plt.figure(figsize=(7, 7), dpi=100, layout="constrained")
    axes = fig.subplot_mosaic(
        [
            ["signal", "signal"],
            ["magnitude", "log_magnitude"],
            ["phase", "angle"],
        ]
    )
    axes["signal"].set(title="Signal", xlabel="Time (s)", ylabel="Amplitude")
    axes["magnitude"].set_title("Magnitude Spectrum")
    axes["log_magnitude"].set_title("Log. Magnitude Spectrum")
    axes["phase"].set_title("Phase Spectrum")
    axes["angle"].set_title("Angle Spectrum")
    for ax in axes.values():
        ax.plot([0, 1], [0, 1])

    assert fig._layout_options["engine"] == "tight"
    assert fig._layout_dirty is True
    rects = fig._effective_rects()
    assert rects is not None
    assert fig._layout_dirty is False

    signal, magnitude, _log_magnitude, phase, _angle = rects
    signal_to_magnitude = (signal[1] - magnitude[1] - magnitude[3]) * 700
    magnitude_to_phase = (magnitude[1] - phase[1] - phase[3]) * 700
    assert signal_to_magnitude >= 64
    assert magnitude_to_phase >= 64


def test_figure_rejects_an_unknown_layout_engine() -> None:
    with pytest.raises(ValueError, match="Invalid value for 'layout'"):
        plt.figure(layout="overlap")


def test_subplot_mosaic_rejects_non_rectangular_label_regions() -> None:
    plt.close("all")
    with pytest.raises(ValueError, match="non-rectangular or non-contiguous"):
        plt.subplot_mosaic([["A", "B"], ["B", "A"]])


def test_subplot_mosaic_shares_live_domains_without_hiding_outer_labels() -> None:
    plt.close("all")
    fig, axes = plt.subplot_mosaic(
        [["top", "top"], ["left", "right"]],
        sharex=True,
        sharey=True,
    )
    axes["top"].plot([0, 1], [0, 2])
    axes["left"].plot([10, 20], [-3, 4])
    axes["right"].plot([30, 40], [5, 8])

    figures = [chart.figure() for chart in fig._charts()]
    assert fig._sharex == "all"
    assert fig._sharey == "all"
    assert len({tuple(core.x_range()) for core in figures}) == 1
    assert len({tuple(core.y_range()) for core in figures}) == 1
    assert all(core.interaction["link_axes"] == ["x", "y"] for core in figures)
    assert axes["top"]._axis_props("x")["tick_label_strategy"] == "off"
    assert axes["right"]._axis_props("y")["tick_label_strategy"] == "off"
    assert axes["left"]._axis_props("x").get("tick_label_strategy") != "off"
    assert axes["left"]._axis_props("y").get("tick_label_strategy") != "off"


def test_subplot_mosaic_png_contains_only_materialized_spanning_axes() -> None:
    plt.close("all")
    fig, axes = plt.subplot_mosaic("AA;B.", figsize=(6.4, 4.8), dpi=100)
    output = BytesIO()

    fig.savefig(output, format="png")
    output.seek(0)

    pixels = np.asarray(plt.imread(output))
    assert pixels.shape[:2] == (480, 640)
    assert len(fig._charts()) == 2
    top, lower = (axes[label].get_position().bounds for label in ("A", "B"))
    assert top[2] > 2 * lower[2]

    # A real span has one uninterrupted top spine across both columns.  A
    # phantom axes in the sentinel cell would instead split this into two.
    y = round((1.0 - top[1] - top[3]) * pixels.shape[0])
    x0 = round(top[0] * pixels.shape[1])
    x1 = round((top[0] + top[2]) * pixels.shape[1])
    threshold = 0.65 if np.issubdtype(pixels.dtype, np.floating) else 0.65 * 255
    spine = np.all(pixels[max(0, y - 1) : y + 2, x0:x1, :3] < threshold, axis=2)
    assert spine.sum(axis=1).max() > 0.9 * (x1 - x0)


def test_rgba_compositor_preserves_transparent_chrome() -> None:
    destination = np.array(
        [[[255, 255, 255, 255], [0, 0, 255, 255]]],
        dtype=np.uint8,
    )
    source = np.array(
        [[[0, 0, 0, 0], [255, 0, 0, 128]]],
        dtype=np.uint8,
    )

    _composite_rgba(destination, source)

    np.testing.assert_array_equal(destination[0, 0], [255, 255, 255, 255])
    np.testing.assert_array_equal(destination[0, 1], [128, 0, 127, 255])
