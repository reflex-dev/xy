from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pytest

import xy.pyplot as plt


def test_plot_marker_styles_and_markevery_reach_marker_entry() -> None:
    _fig, ax = plt.subplots()
    ax.plot(
        [0, 1, 2, 3],
        [1, 2, 3, 4],
        marker="o",
        markevery=2,
        markerfacecolor="red",
        markeredgecolor="blue",
        markeredgewidth=3,
    )
    marker = ax._entries[1]
    np.testing.assert_array_equal(marker["x"], [0, 2])
    assert marker["kwargs"]["color"] == "red"
    assert marker["kwargs"]["stroke"] == "blue"
    assert marker["kwargs"]["stroke_width"] == pytest.approx(3 * 100 / 72)
    assert marker["kwargs"]["size"] == pytest.approx(9 * 100 / 72)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda ax: ax.plot([0, 1], [1, 2], scalex=False), "scalex"),
        (lambda ax: ax.plot([0, 1], [1, 2], fillstyle="left"), "fillstyle"),
        (lambda ax: ax.plot([0, 1], [1, 2], solid_capstyle="round"), "capstyle"),
        (lambda ax: ax.fill_betweenx([0, 1], [0, 1], step="pre"), "step"),
        (lambda ax: ax.arrow(0, 0, 1, 1, shape="left"), "head shape"),
        (lambda ax: ax.errorbar([0], [1], yerr=0.2, barsabove=True), "barsabove"),
        (lambda ax: ax.psd([1, 2, 3], window=np.ones(3)), "window"),
    ],
)
def test_material_options_are_not_silently_discarded(call, match: str) -> None:
    _fig, ax = plt.subplots()
    with pytest.raises((TypeError, NotImplementedError), match=match):
        call(ax)


def test_scatter_color_domain_is_retained_and_norm_is_loud() -> None:
    _fig, ax = plt.subplots()
    ax.scatter([0, 1], [1, 2], c=[10, 20], vmin=0, vmax=30)
    assert ax._entries[0]["kwargs"]["domain"] == (0.0, 30.0)
    with pytest.raises(NotImplementedError, match=r"scatter\(norm"):
        ax.scatter([0], [1], c=[2], norm=lambda value: value)


def test_rule_linestyle_is_retained_as_dash_geometry() -> None:
    _fig, ax = plt.subplots()
    ax.axvline(1, linestyle="--")
    # Matplotlib's "--" pattern (3.7, 1.6) pt scaled by lw=1.5 and dpi=100.
    assert ax._entries[0]["kwargs"]["style"]["dash"] == "7.7083,3.3333"


def test_named_dash_patterns_follow_linewidth_and_figure_dpi() -> None:
    _fig, ax = plt.subplots(dpi=144)
    line = ax.plot([0, 1], [0, 1], linestyle="-.", linewidth=2)[0]
    step = ax.step([0, 1], [1, 0], linestyle=":", linewidth=3)[0]

    # At 144 dpi one point is two pixels. Matplotlib scales each named pattern
    # by the line width before the point-to-pixel conversion.
    assert line._entry["kwargs"]["dash"] == [25.6, 6.4, 4.0, 6.4]
    assert step._entry["kwargs"]["dash"] == [6.0, 9.9]


def test_hlines_and_vlines_emit_dash_geometry() -> None:
    _fig, ax = plt.subplots()
    horizontal = ax.hlines([1], [0], [2], linestyles="dashed")
    vertical = ax.vlines([1], [0], [2], linestyles="dotted")
    assert len(horizontal._entry["args"][0]) > 1
    assert len(vertical._entry["args"][0]) > 1


def test_fill_between_interpolate_extends_to_curve_crossing() -> None:
    _fig, ax = plt.subplots()
    collection = ax.fill_between(
        [0, 1, 2, 3],
        [-1, 1, 1, -1],
        0,
        where=[False, True, True, False],
        interpolate=True,
    )
    np.testing.assert_allclose(collection._entry["x"], [0.5, 1.0, 2.0, 2.5])


def test_log_wrappers_accept_base_subs_and_nonpositive_contract() -> None:
    _fig, ax = plt.subplots()
    ax.loglog([1, 10], [1, 100], base=10, nonpositive="clip")
    assert ax._axis["x"]["type_"] == "log"
    assert ax._axis["y"]["type_"] == "log"
    ax.semilogx([1, 2], [1, 2], base=2)
    assert ax._scale_specs["x"]["base"] == 2
    ax.semilogy([1, 2], [1, 2], subs=[1, 2])
    assert ax._scale_specs["y"]["subs"] == (1.0, 2.0)
    ax.set_xscale("log", nonpositive="mask")
    assert ax._axis["x"]["nonpositive"] == "mask"
    for scale in ("symlog", "logit", "asinh"):
        ax.set_xscale(scale)
        assert ax._scale_specs["x"]["name"] == scale


def test_datetime_timedelta_and_categories_have_bounded_native_conversions() -> None:
    _fig, ax = plt.subplots()
    dates = [datetime(2024, 1, 1), datetime(2024, 1, 2)]
    ax.plot(dates, [1, 2])
    date_values = ax._build_chart(640, 480).figure().traces[0].x.values
    np.testing.assert_array_equal(date_values, [1704067200000, 1704153600000])

    _fig, ax = plt.subplots()
    ax.plot([timedelta(hours=1), timedelta(hours=2)], [1, 2])
    np.testing.assert_array_equal(ax._entries[0]["x"], [3600, 7200])

    _fig, ax = plt.subplots()
    ax.plot(["alpha", "beta"], [1, 2])
    categorical = ax._build_chart(640, 480).figure().traces[0].x.values
    np.testing.assert_array_equal(categorical, [0, 1])


def test_imshow_uses_rc_image_origin_default() -> None:
    plt.rcParams["image.origin"] = "lower"
    _fig, ax = plt.subplots()
    ax.imshow([[1, 2], [3, 4]])
    assert not ax._axis["y"].get("reverse", False)

    plt.rcParams["image.origin"] = "upper"
    _fig, ax = plt.subplots()
    ax.imshow([[1, 2], [3, 4]])
    assert ax._axis["y"]["reverse"] is True


def test_errorbar_limit_flags_change_one_sided_geometry() -> None:
    _fig, ax = plt.subplots()
    ax.errorbar([0, 1], [2, 3], yerr=[0.5, 1], lolims=[True, False], uplims=[False, True])
    yerr = ax._entries[0]["kwargs"]["yerr"]
    np.testing.assert_array_equal(yerr, [[0, 1], [0.5, 0]])


class Normalize:
    """Stand-in for matplotlib.colors.Normalize (accepted by type name)."""

    def __init__(self, vmin=None, vmax=None) -> None:
        self.vmin = vmin
        self.vmax = vmax


class LogNorm(Normalize):
    pass


def _stream_args() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    coords = np.arange(4.0)
    return coords, coords, np.ones((4, 4)), np.ones((4, 4))


_Z = np.arange(16.0).reshape(4, 4)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda ax: ax.pie([1, 2], shadow=True), "shadow"),
        (lambda ax: ax.pie([1, 2], frame=True), "frame"),
        (lambda ax: ax.pie([1, 2], rotatelabels=True), "rotatelabels"),
        (lambda ax: ax.pie([1, 2], hatch="//"), "hatch"),
        (lambda ax: ax.pie([1, 2], wedgeprops={"hatch": "x"}), "hatch"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], headwidth=6), "headwidth"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], headlength=2), "headlength"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], headaxislength=2), "headaxislength"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], minshaft=2), "minshaft"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], minlength=0), "minlength"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], norm=Normalize(0, 1)), "norm"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], clim=(0, 1)), "clim"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], zorder=3), "zorder"),
        (lambda ax: ax.contour(_Z, linestyles="dashed"), "linestyles"),
        (lambda ax: ax.contourf(_Z, corner_mask="legacy"), "corner_mask"),
        (lambda ax: ax.streamplot(*_stream_args(), transform="data"), "transform"),
        (lambda ax: ax.streamplot(*_stream_args(), zorder=2), "zorder"),
        (lambda ax: ax.streamplot(*_stream_args(), minlength=0.5), "minlength"),
        (lambda ax: ax.streamplot(*_stream_args(), arrowstyle="->"), "arrowstyle"),
        (lambda ax: ax.pcolormesh(_Z, antialiased=False), "antialiased"),
        (lambda ax: ax.pcolor(_Z, antialiased=False), "antialiased"),
        (lambda ax: ax.table(cellText=[["a"]], cellLoc="center"), "cellLoc"),
        (lambda ax: ax.table(cellText=[["a"]], rowLoc="center"), "rowLoc"),
        (lambda ax: ax.table(cellText=[["a"]], colLoc="left"), "colLoc"),
        (lambda ax: ax.table(cellText=[["a"]], loc="top"), "loc"),
        (
            lambda ax: ax.quiverkey(_quiver(ax), 0.5, 0.5, 1, "k", fontproperties={"size": 9}),
            "fontproperties",
        ),
        (lambda ax: ax.quiverkey(_quiver(ax), 0.5, 0.5, 1, "k", zorder=5), "zorder"),
        (lambda ax: ax.bar_label(ax.bar([0], [1]), fontproperties="serif"), "fontproperties"),
        (lambda ax: ax.spy(np.eye(3), aspect="auto"), "aspect"),
        (
            lambda ax: ax.tripcolor([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], antialiased=True),
            "antialiased",
        ),
        (
            lambda ax: ax.tricontour([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], antialiased=False),
            "antialiased",
        ),
        (
            lambda ax: ax.tricontour([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], linestyles="dashed"),
            "linestyles",
        ),
        (
            lambda ax: ax.tricontourf([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], antialiased=True),
            "antialiased",
        ),
        (lambda ax: ax.eventplot([[1, 2]], linestyles="steps"), "linestyle"),
        (
            lambda ax: ax.triplot([0, 1, 2], [0, 1, 0], triangles=[[0, 1, 2]], dashes=(2, 1)),
            "dashes",
        ),
        (
            lambda ax: ax.tricontour([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], extend="both"),
            "extend",
        ),
        (
            lambda ax: ax.tripcolor([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], norm=LogNorm()),
            r"tripcolor\(norm=LogNorm\)",
        ),
        (
            lambda ax: ax.tricontour([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], norm=LogNorm()),
            r"tricontour\(norm=LogNorm\)",
        ),
    ],
)
def test_p3_options_are_rejected_instead_of_silently_discarded(call, match: str) -> None:
    _fig, ax = plt.subplots()
    with pytest.raises((TypeError, NotImplementedError), match=match):
        call(ax)


def _quiver(ax):
    return ax.quiver([0, 1], [0, 1], [1, 0], [0, 1])


def test_matplotlib_default_option_values_pass_through() -> None:
    _fig, ax = plt.subplots()
    ax.pie([1, 2], shadow=False, frame=False, rotatelabels=False)
    ax.quiver(
        [0, 1],
        [0, 1],
        [1, 0],
        [0, 1],
        units="width",
        headwidth=3,
        headlength=5,
        headaxislength=4.5,
        minshaft=1,
        minlength=1,
    )
    ax.barbs(
        [0, 1], [0, 1], [1, 0], [0, 1], rounding=True, fill_empty=False, flip_barb=False, length=7
    )
    ax.contour(_Z, corner_mask=True)
    ax.pcolormesh(_Z, antialiased=True)
    ax.table(cellText=[["a"]], cellLoc="right", rowLoc="left", colLoc="center", loc="bottom")
    ax.stem([0, 1], [1, 2], basefmt="C3-")
    ax.spy(np.eye(3), aspect="equal")
    ax.tripcolor([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], antialiased=False)
    ax.tricontour([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], antialiased=True, extend="neither")
    ax.tricontourf([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], antialiased=False)
    assert ax._entries


def test_quiver_units_control_width_without_changing_vector_length() -> None:
    _fig, ax = plt.subplots()
    width_units = ax.quiver([0, 10], [0, 10], [1, 0], [0, 1], units="width", width=0.02, scale=1)
    x_units = ax.quiver([0, 10], [0, 10], [1, 0], [0, 1], units="x", width=0.02, scale=1)
    np.testing.assert_allclose(width_units._entry["args"][0], x_units._entry["args"][0])
    np.testing.assert_allclose(width_units._entry["args"][2], x_units._entry["args"][2])
    assert width_units._entry["kwargs"]["width"] > x_units._entry["kwargs"]["width"]


def test_barbs_use_fixed_staffs_and_matplotlib_tail_decomposition() -> None:
    _fig, ax = plt.subplots()
    ax.barbs(
        np.arange(5.0),
        np.zeros(5),
        [0, 5, 10, 50, 65],
        np.zeros(5),
        length=8,
        fill_empty=True,
        rounding=False,
    )
    segments = ax._entries[0]
    triangles = ax._entries[1]
    assert segments["factory"] == "segments"
    assert triangles["factory"] == "triangle_mesh"
    # Empty circle (12), then half/full/flag/flag+full+half geometries.
    assert len(segments["args"][0]) == 24
    assert len(triangles["args"][0]) == 14  # 12 circle wedges + two flags
    x0, y0, x1, y1 = map(np.asarray, segments["args"])
    staff_indices = [12, 14, 16, 19]
    staff_lengths = np.hypot(
        x1[staff_indices] - x0[staff_indices], y1[staff_indices] - y0[staff_indices]
    )
    np.testing.assert_allclose(staff_lengths, staff_lengths[0])


def test_barbs_support_increment_flip_size_and_color_controls() -> None:
    _fig, ax = plt.subplots()
    ax.barbs(
        [0, 1],
        [0, 0],
        [120, 40],
        [0, 0],
        barb_increments={"half": 10, "full": 20, "flag": 100},
        sizes={"spacing": 0.2, "height": 0.3, "emptybarb": 0.25},
        flip_barb=True,
        barbcolor=["b", "g"],
        flagcolor="r",
    )
    segment_entries = [entry for entry in ax._entries if entry["factory"] == "segments"]
    triangle_entries = [entry for entry in ax._entries if entry["factory"] == "triangle_mesh"]
    assert {entry["kwargs"]["color"] for entry in segment_entries} == {"#0000ff", "#008000"}
    assert triangle_entries[0]["kwargs"]["color"] == "#ff0000"


def test_fully_masked_barbs_return_an_empty_collection() -> None:
    _fig, ax = plt.subplots()
    masked = np.ma.masked_all(3)

    collection = ax.barbs([0, 1, 2], [0, 1, 2], masked, masked)

    assert collection._entry["factory"] == "segments"
    assert len(collection._entry["args"][0]) == 0


def test_stem_dashed_basefmt_builds_a_flat_dash_pattern() -> None:
    _fig, ax = plt.subplots()

    container = ax.stem([0.0, 1.0], [1.0, 2.0], basefmt="k--")
    ax._build_chart(640, 480)

    dash = container.baseline._entry["kwargs"]["dash"]
    assert dash
    assert all(np.isscalar(value) for value in dash)


def test_path_collection_get_sizes_tracks_set_sizes() -> None:
    _fig, ax = plt.subplots()
    collection = ax.scatter([0.0, 1.0], [0.0, 1.0], s=[4.0, 9.0])

    collection.set_sizes([16.0, 25.0])

    np.testing.assert_array_equal(collection.get_sizes(), [16.0, 25.0])


def test_barb_staff_length_is_screen_stable_across_subplot_grids() -> None:
    def staff_pixels(fig: Any, ax: Any) -> float:
        ax.barbs([0.0, 4.0], [0.0, 3.0], [50.0, 50.0], [0.0, 0.0])
        segments = next(entry for entry in ax._entries if entry["factory"] == "segments")
        x0, y0, x1, y1 = (np.asarray(values) for values in segments["args"])
        figure_width, figure_height = fig._panel_px()
        rects = fig._effective_rects()
        if rects is None:
            plot_width, plot_height = figure_width * 0.775, figure_height * 0.77
        else:
            rect = rects[fig._axes.index(ax)]
            total_width = figure_width * fig._ncols
            total_height = figure_height * fig._nrows
            plot_width, plot_height = total_width * rect[2], total_height * rect[3]
        return float(
            np.hypot(
                (x1[0] - x0[0]) / 4.0 * plot_width,
                (y1[0] - y0[0]) / 3.0 * plot_height,
            )
        )

    single_fig, single_ax = plt.subplots()
    grid_fig, grid_axes = plt.subplots(2, 2)
    np.testing.assert_allclose(
        staff_pixels(single_fig, single_ax),
        staff_pixels(grid_fig, grid_axes[0, 0]),
        rtol=1e-12,
    )


def test_streamplot_integration_controls_drive_adaptive_step_size() -> None:
    x = np.linspace(-1.0, 1.0, 30)
    y = np.linspace(-1.0, 1.0, 30)
    xx, yy = np.meshgrid(x, y)

    def segment_lengths(step_scale: float) -> np.ndarray:
        _fig, ax = plt.subplots()
        ax.streamplot(
            x,
            y,
            -yy,
            xx,
            start_points=[[0.5, 0.0]],
            broken_streamlines=False,
            integration_max_step_scale=step_scale,
            integration_max_error_scale=step_scale,
        )
        entry = next(entry for entry in ax._entries if entry.get("factory") == "segments")
        x0, y0, x1, y1 = map(np.asarray, entry["args"])
        return np.hypot(x1 - x0, y1 - y0)

    fine = segment_lengths(0.2)
    coarse = segment_lengths(2.0)
    assert np.median(fine) < np.median(coarse)
    assert len(fine) > len(coarse)


def test_streamplot_accepts_gallery_autumn_colormap() -> None:
    x = np.linspace(-1.0, 1.0, 8)
    y = np.linspace(-1.0, 1.0, 8)
    xx, yy = np.meshgrid(x, y)
    _fig, ax = plt.subplots()
    result = ax.streamplot(x, y, -yy, xx, color=xx, cmap="autumn")
    assert result.lines._entry["kwargs"]["colormap"] == "autumn"


def test_contour_extent_generates_coordinate_grids() -> None:
    _fig, ax = plt.subplots()
    ax.contour(np.arange(12.0).reshape(3, 4), extent=(0, 6, 10, 40))
    entry = ax._entries[0]
    np.testing.assert_allclose(entry["kwargs"]["x"], [0.0, 2.0, 4.0, 6.0])
    np.testing.assert_allclose(entry["kwargs"]["y"], [10.0, 25.0, 40.0])


def test_contour_origin_matches_image_pixel_centers() -> None:
    _fig, ax = plt.subplots()
    lower = ax.contour(_Z, origin="lower")._entry
    upper = ax.contour(_Z, origin="upper", extent=(10, 14, 20, 26))._entry

    np.testing.assert_allclose(lower["kwargs"]["x"], [0.5, 1.5, 2.5, 3.5])
    np.testing.assert_allclose(lower["kwargs"]["y"], [0.5, 1.5, 2.5, 3.5])
    np.testing.assert_allclose(upper["kwargs"]["x"], [10.5, 11.5, 12.5, 13.5])
    # The native kernel requires increasing coordinates, so origin='upper'
    # reverses the source rows while preserving Matplotlib's top-first visual.
    np.testing.assert_allclose(upper["kwargs"]["y"], [20.75, 22.25, 23.75, 25.25])
    np.testing.assert_allclose(upper["source_z"], _Z[::-1])


def test_contour_corner_mask_controls_missing_corner_geometry_and_is_inherited() -> None:
    _fig, ax = plt.subplots()
    z = np.array([[np.nan, 1.0], [0.0, 0.0]])
    masked = ax.contour(z, levels=[0.5], corner_mask=True)
    assert masked._entry["corner_mask"] is True

    inherited = ax.contour(masked)
    assert inherited._entry["corner_mask"] is True
    explicit = ax.contour(z, levels=[0.5], corner_mask=False)
    assert explicit._entry["corner_mask"] is False

    _fig2, ax2 = plt.subplots()
    ax2.contour(z, levels=[0.5], corner_mask=True)
    chart = ax2._build_chart(640, 480).figure()
    contour_traces = [trace for trace in chart.traces if trace.kind == "contour"]
    assert len(contour_traces) == 1


def test_contourf_corner_mask_uses_exact_band_clipped_triangles() -> None:
    _fig, ax = plt.subplots()
    z = np.ma.array([[0.0, 1.0], [0.0, 0.0]], mask=[[True, False], [False, False]])
    ax.contourf(
        z,
        levels=[-1.0, 0.5, 2.0],
        colors=["red", "blue"],
        corner_mask=True,
    )

    figure = ax._build_chart(300, 300).figure()
    mesh = next(trace for trace in figure.traces if trace.kind == "triangle_mesh")
    geometry = np.column_stack(
        [getattr(mesh, name).values for name in ("x0", "y0", "x1", "y1", "x", "y")]
    )
    # ContourPy's retained triangle is split at z=.5 into a quad and triangle;
    # triangulating the quad yields these three exact faces, all bounded by the
    # true x+y=1 masked-corner diagonal rather than a sampled staircase.
    np.testing.assert_allclose(
        geometry,
        [
            [0.5, 0.5, 1.0, 0.5, 1.0, 1.0],
            [0.5, 0.5, 1.0, 1.0, 0.0, 1.0],
            [0.5, 0.5, 1.0, 0.0, 1.0, 0.5],
        ],
    )
    assert figure.to_svg().count("<polygon points=") == 3


def test_contourf_legend_elements_keep_per_band_hatches_and_handleheight() -> None:
    _fig, ax = plt.subplots()
    contour = ax.contourf(
        _Z,
        levels=[0.0, 5.0, 10.0, 15.0],
        colors="none",
        hatches=[".", "/", "\\"],
    )
    handles, labels = contour.legend_elements(str_format="{:2.1f}".format)
    assert len(handles) == len(labels) == 3
    assert len({id(handle) for handle in handles}) == 3
    assert [handle._entry["kwargs"]["hatch"] for handle in handles] == [".", "/", "\\"]

    ax.legend(handles, labels, handleheight=2, framealpha=1)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["handleheight"] == 2.0
    assert [item["style"]["hatch"] for item in spec["legend"]["items"]] == [".", "/", "\\"]
    assert all(item["kind"] == "bar" for item in spec["legend"]["items"])


def test_contourf_dot_star_and_backslash_hatches_keep_their_geometry() -> None:
    z = np.tile([0.2, 1.2, 2.2], (3, 1))
    _fig, ax = plt.subplots()
    ax.contourf(
        z,
        levels=[0.0, 1.0, 2.0, 3.0],
        colors="none",
        hatches=[".", "*", "\\"],
    )

    dots = next(
        entry
        for entry in ax._entries
        if entry["kind"] == "scatter" and entry["kwargs"]["symbol"] == "circle"
    )
    stars = next(
        entry
        for entry in ax._entries
        if entry["kind"] == "scatter" and entry["kwargs"]["symbol"] == "star"
    )
    hatch_lines = next(
        entry
        for entry in ax._entries
        if entry["kind"] == "@mark" and entry.get("factory") == "segments"
    )

    assert set(dots["x"]) == {0.0}
    assert set(stars["x"]) == {1.0}
    assert dots["_legend_skip"] is stars["_legend_skip"] is True
    x0, y0, x1, y1 = map(np.asarray, hatch_lines["args"])
    assert np.all(x1 > x0)
    assert np.all(y1 < y0)


def test_static_legend_hatches_use_filled_dots_and_stars() -> None:
    from xy._raster import _SYMBOLS, _emit_legend_hatch
    from xy._svg import _legend_hatch_svg

    dots = _legend_hatch_svg(0.0, 20.0, 0.0, 20.0, ".", "#123456")
    star = _legend_hatch_svg(0.0, 20.0, 0.0, 20.0, "*", "#123456")
    slash = _legend_hatch_svg(0.0, 20.0, 0.0, 20.0, "/", "#123456")
    backslash = _legend_hatch_svg(0.0, 20.0, 0.0, 20.0, "\\", "#123456")

    assert dots.count("<circle") == 2
    assert "<path" not in dots
    assert "<path" in star and 'fill="#123456"' in star and "stroke=" not in star
    assert "M5,15 L15,5" in slash
    assert "M5,5 L15,15" in backslash

    class Recorder:
        def __init__(self) -> None:
            self.points: list[tuple[Any, ...]] = []
            self.strokes: list[tuple[Any, ...]] = []

        def point(self, *args: Any) -> None:
            self.points.append(args)

        def stroke(self, *args: Any, **_kwargs: Any) -> None:
            self.strokes.append(args)

    recorder = Recorder()
    _emit_legend_hatch(
        recorder,
        0.0,
        20.0,
        0.0,
        20.0,
        ".*\\",
        (18, 52, 86, 255),
    )
    assert [point[3] for point in recorder.points] == [
        _SYMBOLS["circle"],
        _SYMBOLS["circle"],
        _SYMBOLS["star"],
    ]
    assert len(recorder.strokes) == 1


def test_contourf_preserves_unknown_public_extend_as_unextended_geometry() -> None:
    _fig, ax = plt.subplots()
    contour = ax.contourf(_Z, levels=4, extend="lower")

    assert contour._entry["extend"] == "lower"
    assert contour._entry["kwargs"]["extend"] == "neither"


def test_violinplot_flat_quantiles_are_one_single_violin_group() -> None:
    _fig, ax = plt.subplots()
    result = ax.violinplot(
        [1.0, 2.0, 3.0, 4.0],
        quantiles=[0.25, 0.5, 0.75],
        showextrema=False,
    )

    quantile_segments = result["cquantiles"]._entry["args"]
    assert len(quantile_segments[0]) == 3
    np.testing.assert_allclose(quantile_segments[1], [1.75, 2.5, 3.25])


def test_plot_masked_integer_coordinates_use_nan_gaps() -> None:
    _fig, ax = plt.subplots()
    line = ax.plot(
        np.ma.array([0, 1, 2], mask=[False, True, False]),
        [3, 4, 5],
        "ro",
    )[0]
    np.testing.assert_allclose(line.get_xdata()[[0, 2]], [0.0, 2.0])
    assert np.isnan(line.get_xdata()[1])


def test_contour_solid_style_and_negative_rc_setting() -> None:
    _fig, ax = plt.subplots()
    explicit = ax.contour(_Z - 7.5, colors="black", linestyles="-")
    assert explicit._entry["kwargs"]["dash_negative"] is False

    with plt.rc_context({"contour.negative_linestyle": "solid"}):
        configured = ax.contour(_Z - 7.5, colors="black")
    assert configured._entry["kwargs"]["dash_negative"] is False

    default = ax.contour(_Z - 7.5, colors="black")
    assert default._entry["kwargs"]["dash_negative"] is True

    listed = ax.contourf(_Z, colors=("r", "g", "b"))
    palette = np.asarray(
        [
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 128 / 255, 0.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
        ]
    )
    expected = palette[np.arange(len(listed.levels) - 1) % len(palette)]
    np.testing.assert_allclose(listed._entry["kwargs"]["color"], expected)
    assert listed._entry["kwargs"]["dash_negative"] is False


def test_contour_linewidths_cycle_by_level_and_artist_updates_preserve_arrays() -> None:
    _fig, ax = plt.subplots()
    point_scale = ax._point_scale()
    contour = ax.contour(
        np.arange(25.0).reshape(5, 5),
        levels=[4, 8, 12, 16, 20],
        colors="black",
        linewidths=[0.5, 2.0],
    )
    np.testing.assert_allclose(contour.get_linewidth(), [0.5, 2.0])
    np.testing.assert_allclose(
        contour._entry["kwargs"]["width"],
        np.array([0.5, 2.0]) * point_scale,
    )

    contour.set_linewidth([1.0, 3.0, 2.0])
    np.testing.assert_allclose(contour.get_linewidth(), [1.0, 3.0, 2.0])
    np.testing.assert_allclose(
        contour._entry["kwargs"]["width"],
        np.array([1.0, 3.0, 2.0]) * point_scale,
    )

    contour.set(linewidth=[0.75, 1.5])
    np.testing.assert_allclose(contour.get_linewidth(), [0.75, 1.5])
    np.testing.assert_allclose(
        contour._entry["kwargs"]["width"],
        np.array([0.75, 1.5]) * point_scale,
    )

    traces = ax._build_chart(640, 480).figure().traces
    widths = np.concatenate(
        [
            trace.style_channels["width"].values
            for trace in traces
            if trace.kind == "contour" and "width" in trace.style_channels
        ]
    )
    np.testing.assert_allclose(
        sorted(set(widths)),
        np.array([0.75, 1.5]) * point_scale,
    )


def test_stem_dashed_linefmt_emits_dash_segments_and_markers() -> None:
    _fig, ax = plt.subplots()
    ax.stem([0, 1], [4, 8], linefmt="r--")
    segments = ax._entries[0]
    assert segments["factory"] == "segments"
    assert segments["kwargs"]["color"] == "#ff0000"
    assert len(segments["args"][0]) > 2  # each stem splits into dash pieces
    np.testing.assert_array_equal(segments["args"][0], segments["args"][2])  # stems stay vertical
    assert ax._entries[1]["kind"] == "scatter"


def test_pcolormesh_plain_normalize_maps_to_domain() -> None:
    _fig, ax = plt.subplots()
    ax.pcolormesh(_Z, norm=Normalize(1.0, 4.0))
    assert ax._entries[0]["kwargs"]["domain"] == (1.0, 4.0)
    log_mesh = ax.pcolormesh(_Z, norm=LogNorm())
    assert log_mesh._entry["_mpl_domain"] == (1.0, 15.0)
    assert log_mesh._entry["_mpl_norm_scale"] == "log"
    assert log_mesh._entry["args"][0].shape == _Z.shape + (4,)


def test_bar_label_fontsize_reaches_text_style() -> None:
    _fig, ax = plt.subplots()
    ax.bar_label(ax.bar([0, 1], [2, 3]), fontsize=11)
    texts = [entry for entry in ax._entries if entry["kind"] == "@text"]
    assert len(texts) == 2
    assert all(entry["kwargs"]["style"]["font_size"] == 11.0 for entry in texts)


def test_streamplot_seeds_and_direction_drive_the_native_integrator() -> None:
    x = np.linspace(0.0, 1.0, 5)
    y = np.linspace(0.0, 1.0, 5)
    u, v = np.ones((5, 5)), np.zeros((5, 5))
    _fig, ax = plt.subplots()
    ax.streamplot(x, y, u, v, start_points=[[0.5, 0.5]], integration_direction="forward")
    segments = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    starts_x = np.concatenate([np.asarray(entry["args"][0]) for entry in segments])
    starts_y = np.concatenate([np.asarray(entry["args"][1]) for entry in segments])
    assert np.all(starts_x >= 0.5)  # forward-only integration from the seed
    np.testing.assert_allclose(starts_y, 0.5)

    _fig, ax = plt.subplots()
    ax.streamplot(x, y, u, v, start_points=[[0.5, 0.5]], integration_direction="backward")
    segments = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    ends_x = np.concatenate([np.asarray(entry["args"][2]) for entry in segments])
    assert np.all(ends_x <= 0.5)

    _fig, ax = plt.subplots()
    with pytest.raises(ValueError, match="start_points"):
        ax.streamplot(x, y, u, v, start_points=[[5.0, 5.0]])


def test_streamplot_array_linewidth_and_color_are_sampled_per_segment() -> None:
    x = np.linspace(-1.0, 1.0, 8)
    y = np.linspace(-1.0, 1.0, 8)
    xx, yy = np.meshgrid(x, y)
    _fig, ax = plt.subplots()
    ax.streamplot(x, y, -yy, xx, color=xx, linewidth=1.0 + np.abs(yy), norm=Normalize(-2.0, 2.0))
    segments = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    assert len(segments) > 1  # varying widths split into width bins
    assert len({entry["kwargs"]["width"] for entry in segments}) > 1
    assert all(entry["kwargs"]["domain"] == (-2.0, 2.0) for entry in segments)
    assert any(np.ptp(np.asarray(entry["kwargs"]["color"])) > 0 for entry in segments)
    with pytest.raises(NotImplementedError, match=r"streamplot\(norm=LogNorm\)"):
        ax.streamplot(x, y, -yy, xx, color=xx, norm=LogNorm())


def test_eventplot_linestyles_render_dash_segments() -> None:
    _fig, ax = plt.subplots()
    ax.eventplot([[1, 2], [3]], linestyles=["dashed", "dotted"])
    assert [entry["factory"] for entry in ax._entries] == ["segments", "segments"]
    assert len(ax._entries[0]["args"][0]) > 2  # each event tick splits into dashes

    _fig, ax = plt.subplots()
    ax.eventplot([[1, 2]], linestyles="solid")
    assert ax._entries[0]["factory"] == "errorbar"


def test_triplot_dashed_fmt_splits_edges() -> None:
    _fig, ax = plt.subplots()
    ax.triplot([0.0, 1.0, 0.5], [0.0, 0.0, 1.0], "k--", triangles=[[0, 1, 2]])
    entry = ax._entries[0]
    assert entry["factory"] == "segments"
    assert len(entry["args"][0]) > 3  # three edges split into dash pieces


def test_tri_plain_normalize_maps_to_domain() -> None:
    _fig, ax = plt.subplots()
    ax.tripcolor([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], norm=Normalize(1.0, 3.0))
    assert ax._entries[-1]["kwargs"]["domain"] == (1.0, 3.0)
    ax.tricontour([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], norm=Normalize(-5.0, 5.0))
    assert ax._entries[-1]["kwargs"]["domain"] == (-5.0, 5.0)
    ax.tricontourf([0, 1, 2], [0, 1, 0], [1.0, 2.0, 3.0], norm=Normalize(0.0, 4.0))
    assert ax._entries[-1]["kwargs"]["domain"] == (0.0, 4.0)


@pytest.mark.parametrize("linestyle", ["-", "solid"])
def test_tricontour_accepts_solid_linestyle_aliases(linestyle: str) -> None:
    _fig, ax = plt.subplots()
    contour = ax.tricontour(
        [0.0, 1.0, 0.5],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 2.0],
        levels=[0.5, 1.5],
        triangles=[[0, 1, 2]],
        linestyles=linestyle,
    )
    assert contour._entry["factory"] == "segments"


def test_pie_pie_label_and_table_text_options_reach_text_style() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie(
        [1, 2],
        labels=["a", "b"],
        textprops={"fontsize": 9, "color": "red", "ha": "center", "va": "center"},
    )
    texts = [entry for entry in ax._entries if entry["kind"] == "@text"]
    assert len(texts) == 2
    assert all(entry["kwargs"]["style"]["font_size"] == 9.0 for entry in texts)
    assert all(entry["kwargs"]["style"]["vertical_align"] == "center" for entry in texts)
    assert all(entry["kwargs"]["anchor"] == "middle" for entry in texts)
    assert all(entry["kwargs"]["color"] == "red" for entry in texts)
    ax.pie_label(pie, "{frac:.0%}", textprops={"fontsize": 8})
    assert ax._entries[-1]["kind"] == "@text"
    assert ax._entries[-1]["kwargs"]["style"]["font_size"] == 8.0

    _fig, ax = plt.subplots()
    ax.table(cellText=[["a", "b"]], fontsize=10)
    cell_texts = [entry for entry in ax._entries if entry["kind"] == "@text"]
    assert len(cell_texts) == 2
    assert all(entry["kwargs"]["style"]["font_size"] == 10.0 for entry in cell_texts)
