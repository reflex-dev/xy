from __future__ import annotations

from datetime import datetime, timedelta

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
    assert marker["kwargs"]["stroke_width"] == 3


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda ax: ax.plot([0, 1], [1, 2], scalex=False), "scalex"),
        (lambda ax: ax.plot([0, 1], [1, 2], fillstyle="left"), "fillstyle"),
        (lambda ax: ax.plot([0, 1], [1, 2], solid_capstyle="round"), "capstyle"),
        (lambda ax: ax.hlines([1], [0], [2], linestyles="dashed"), "linestyles"),
        (lambda ax: ax.fill_between([0, 1], [0, 1], interpolate=True), "interpolate"),
        (lambda ax: ax.fill_betweenx([0, 1], [0, 1], step="pre"), "step"),
        (lambda ax: ax.arrow(0, 0, 1, 1, shape="left"), "head shape"),
        (lambda ax: ax.errorbar([0], [1], yerr=0.2, barsabove=True), "barsabove"),
        (lambda ax: ax.violinplot([[1, 2]], side="low"), "side"),
        (lambda ax: ax.imshow([[1]], interpolation_stage="rgba"), "interpolation_stage"),
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
    assert ax._entries[0]["kwargs"]["style"]["dash"] == "6.0,4.0"


def test_log_wrappers_accept_only_the_native_log_contract() -> None:
    _fig, ax = plt.subplots()
    ax.loglog([1, 10], [1, 100], base=10, nonpositive="clip")
    assert ax._axis["x"]["type_"] == "log"
    assert ax._axis["y"]["type_"] == "log"
    with pytest.raises(NotImplementedError, match="base=2"):
        ax.semilogx([1, 2], [1, 2], base=2)
    with pytest.raises(NotImplementedError, match="subs"):
        ax.semilogy([1, 2], [1, 2], subs=[1, 2])
    with pytest.raises(NotImplementedError, match="nonpositive"):
        ax.set_xscale("log", nonpositive="mask")
    for scale in ("symlog", "logit", "asinh"):
        with pytest.raises(NotImplementedError, match=scale):
            ax.set_xscale(scale)


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
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], units="xy"), "units"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], headwidth=6), "headwidth"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], headlength=2), "headlength"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], headaxislength=2), "headaxislength"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], minshaft=2), "minshaft"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], minlength=0), "minlength"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], norm=Normalize(0, 1)), "norm"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], clim=(0, 1)), "clim"),
        (lambda ax: ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], zorder=3), "zorder"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], length=9), "length"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], fill_empty=True), "fill_empty"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], rounding=False), "rounding"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], flip_barb=True), "flip_barb"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], sizes={"spacing": 0.2}), "sizes"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], barbcolor="red"), "barbcolor"),
        (lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], flagcolor="red"), "flagcolor"),
        (
            lambda ax: ax.barbs([0, 1], [0, 1], [1, 0], [0, 1], barb_increments={"half": 3}),
            "barb_increments",
        ),
        (lambda ax: ax.contour(_Z, origin="lower"), "origin"),
        (lambda ax: ax.contour(_Z, linestyles="dashed"), "linestyles"),
        (lambda ax: ax.contourf(_Z, corner_mask=False), "corner_mask"),
        (lambda ax: ax.contourf(_Z, corner_mask="legacy"), "corner_mask"),
        (lambda ax: ax.streamplot(*_stream_args(), transform="data"), "transform"),
        (lambda ax: ax.streamplot(*_stream_args(), zorder=2), "zorder"),
        (lambda ax: ax.streamplot(*_stream_args(), minlength=0.5), "minlength"),
        (
            lambda ax: ax.streamplot(*_stream_args(), broken_streamlines=False),
            "broken_streamlines",
        ),
        (lambda ax: ax.streamplot(*_stream_args(), arrowstyle="->"), "arrowstyle"),
        (
            lambda ax: ax.streamplot(*_stream_args(), integration_max_step_scale=2.0),
            "integration_max_step_scale",
        ),
        (
            lambda ax: ax.streamplot(*_stream_args(), integration_max_error_scale=0.5),
            "integration_max_error_scale",
        ),
        (lambda ax: ax.pcolormesh(_Z, antialiased=False), "antialiased"),
        (lambda ax: ax.pcolor(_Z, antialiased=False), "antialiased"),
        (lambda ax: ax.table(cellText=[["a"]], cellLoc="center"), "cellLoc"),
        (lambda ax: ax.table(cellText=[["a"]], rowLoc="center"), "rowLoc"),
        (lambda ax: ax.table(cellText=[["a"]], colLoc="left"), "colLoc"),
        (lambda ax: ax.table(cellText=[["a"]], loc="top"), "loc"),
        (lambda ax: ax.stem([0, 1], [1, 2], basefmt="k-"), "basefmt"),
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
        (
            lambda ax: ax.pie_label(ax.pie([1.0, 2.0]), "{frac:.0%}", rotate=True),
            "rotate",
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


def test_contour_extent_generates_coordinate_grids() -> None:
    _fig, ax = plt.subplots()
    ax.contour(np.arange(12.0).reshape(3, 4), extent=(0, 6, 10, 40))
    entry = ax._entries[0]
    np.testing.assert_allclose(entry["kwargs"]["x"], [0.0, 2.0, 4.0, 6.0])
    np.testing.assert_allclose(entry["kwargs"]["y"], [10.0, 25.0, 40.0])


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
    with pytest.raises(NotImplementedError, match=r"pcolormesh\(norm=LogNorm\)"):
        ax.pcolormesh(_Z, norm=LogNorm())


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
