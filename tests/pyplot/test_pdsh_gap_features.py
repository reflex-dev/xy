"""The PDSH-benchmark gap features: locators/formatters, named styles,
clim/gci, colorbar handles, GridSpec spans, and the new colormaps.

Each block mirrors real notebook usage (Python Data Science Handbook ch. 4),
so a regression here means real scripts break again.
"""

from __future__ import annotations

import io
import re

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def _png(fig=None):
    buffer = io.BytesIO()
    (fig or plt.gcf()).savefig(buffer, format="png")
    data = buffer.getvalue()
    assert data[:4] == b"\x89PNG"
    return data


def _svg():
    buffer = io.BytesIO()
    plt.savefig(buffer, format="svg")
    return buffer.getvalue().decode()


# -- locators / formatters -------------------------------------------------


def test_axis_proxy_getters_return_ticker_objects():
    fig, ax = plt.subplots()
    assert isinstance(ax.xaxis.get_major_locator(), plt.AutoLocator)
    assert isinstance(ax.xaxis.get_minor_locator(), plt.NullLocator)
    assert isinstance(ax.yaxis.get_major_formatter(), plt.ScalarFormatter)
    assert isinstance(ax.yaxis.get_minor_formatter(), plt.NullFormatter)


def test_null_locator_removes_ticks_from_the_export():
    fig, ax = plt.subplots()
    ax.plot(np.arange(10), np.arange(10))
    ax.yaxis.set_major_locator(plt.NullLocator())
    ax.xaxis.set_major_formatter(plt.NullFormatter())
    assert len(ax.get_yticks()) == 0
    _png()


def test_multiple_locator_positions_are_exact_multiples():
    fig, ax = plt.subplots()
    x = np.linspace(0, 3 * np.pi, 50)
    ax.plot(x, np.sin(x))
    ax.set_xlim(0, 3 * np.pi)
    ax.xaxis.set_major_locator(plt.MultipleLocator(np.pi / 2))
    assert np.allclose(ax.get_xticks(), np.arange(0, 3 * np.pi + 1e-9, np.pi / 2))


def test_maxn_locator_caps_tick_count():
    fig, ax = plt.subplots()
    ax.plot([0, 63], [0, 63])
    ax.xaxis.set_major_locator(plt.MaxNLocator(3))
    ticks = ax.get_xticks()
    assert 2 <= len(ticks) <= 4


def test_maxn_locator_matches_matplotlib_tick_values():
    # Reference values from matplotlib 3.11 MaxNLocator.tick_values; edge
    # ticks may overrun the view — the axis clips them at draw time.
    assert np.allclose(plt.MaxNLocator(3).tick_values(0, 1), [0.0, 0.4, 0.8, 1.2])
    assert np.allclose(plt.MaxNLocator(5).tick_values(0, 1), [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    assert np.allclose(
        plt.MaxNLocator(4, steps=[1, 3, 10]).tick_values(0, 1), [0.0, 0.3, 0.6, 0.9, 1.2]
    )
    assert np.allclose(
        plt.MaxNLocator(5, integer=True).tick_values(-0.5, 6.5), [-2.0, 0.0, 2.0, 4.0, 6.0, 8.0]
    )
    assert np.allclose(plt.MaxNLocator(3).tick_values(-3.15, 66.15), [-25.0, 0.0, 25.0, 50.0, 75.0])
    with pytest.raises(ValueError):
        plt.MaxNLocator(3, steps=[0.5, 1])


def test_maxn_locator_grid_renders_matplotlib_ticks():
    # PDSH 04.10: MaxNLocator(3) on a 4x4 grid labels 0.0/0.4/0.8, not 0/0.5/1.
    fig, axs = plt.subplots(4, 4, sharex=True, sharey=True)
    for axi in axs.flat:
        axi.xaxis.set_major_locator(plt.MaxNLocator(3))
        axi.yaxis.set_major_locator(plt.MaxNLocator(3))
    assert set(re.findall(r"<text[^>]*>([^<]+)</text>", _svg())) == {"0.0", "0.4", "0.8"}


def test_auto_locator_density_adapts_to_panel_size():
    # matplotlib's AutoLocator budgets ticks by axes size: tiny panels get
    # two intervals, so an explicit AutoLocator must match the default axes.
    fig, axs = plt.subplots(4, 4, sharex=True, sharey=True)
    for axi in axs.flat:
        axi.xaxis.set_major_locator(plt.AutoLocator())
        axi.yaxis.set_major_locator(plt.AutoLocator())
    assert set(re.findall(r"<text[^>]*>([^<]+)</text>", _svg())) == {"0.0", "0.5", "1.0"}


def test_func_formatter_labels_reach_the_export():
    fig, ax = plt.subplots()
    ax.plot([0, 4], [0, 4])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, pos: f"{v:.0f}%"))
    assert "%" in _svg()


def test_locator_refreshes_as_data_lands():
    fig, ax = plt.subplots()
    ax.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax.plot([0, 25], [0, 1])
    before = len(ax.get_xticks())
    ax.plot([0, 95], [0, 1])
    assert len(ax.get_xticks()) > before


def test_set_xticks_displaces_a_stored_locator():
    fig, ax = plt.subplots()
    ax.plot([0, 100], [0, 1])
    ax.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax.set_xticks([0, 50])
    assert list(ax.get_xticks()) == [0.0, 50.0]


def test_explicit_labels_displace_a_stored_formatter():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, p: "F"))
    ax.set_xticks([0, 1], labels=["lo", "hi"])
    svg = _svg()
    assert "lo" in svg and "F" not in svg


def test_set_major_locator_rejects_non_locators():
    fig, ax = plt.subplots()
    with pytest.raises(TypeError):
        ax.xaxis.set_major_locator(object())


def test_log_axis_formatter_formats_log_ticks():
    fig, ax = plt.subplots()
    ax.plot([1, 10, 100], [1, 10, 100])
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(plt.FormatStrFormatter("%g!"))
    assert "10!" in _svg()


# -- style.context and named styles ------------------------------------------


def test_style_context_applies_and_restores_rcparams():
    base = dict(plt.rcParams)
    with plt.style.context("ggplot"):
        assert plt.rcParams["axes.facecolor"] == "#E5E5E5"
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        assert ax._grid is True
        assert ax._theme_tokens["plot_background"] == "#E5E5E5"
        assert ax._prop_cycle[0] == "#E24A33"
    assert dict(plt.rcParams) == base


@pytest.mark.parametrize(
    "name",
    [
        "fivethirtyeight",
        "ggplot",
        "bmh",
        "dark_background",
        "grayscale",
        "seaborn-whitegrid",
        "seaborn-v0_8-whitegrid",
        "seaborn-v0_8-white",
    ],
)
def test_named_styles_render(name):
    with plt.style.context(name):
        fig, ax = plt.subplots()
        ax.plot([0, 1, 2], [0, 1, 4])
        _png(fig)


def test_unknown_style_still_fails_loudly():
    with pytest.raises(NotImplementedError):
        plt.style.use("solarize_light2")


def test_grid_color_rcparam_reaches_the_axes():
    with plt.rc_context({"grid.color": "#123456", "axes.grid": True}):
        fig, ax = plt.subplots()
        assert ax._grid_color == "#123456"


def test_cycler_routes_into_prop_cycle():
    colors = plt.cycler("color", ["#EE6666", "#3388BB"])
    with plt.rc_context({"axes.prop_cycle": colors}):
        fig, ax = plt.subplots()
        assert ax._prop_cycle == ["#EE6666", "#3388BB"]
    with pytest.raises(NotImplementedError):
        plt.cycler("linestyle", ["-", "--"])


# -- colormaps ----------------------------------------------------------------


def test_rdgy_and_jet_resolve_and_render():
    assert plt.get_cmap("RdGy").name == "rdgy"
    assert plt.get_cmap("RdGy_r").name == "rdgy_r"
    assert plt.get_cmap("jet").name == "jet"
    fig, ax = plt.subplots()
    ax.contour(np.random.default_rng(0).normal(size=(12, 12)), cmap="RdGy")
    _png()


def test_linear_segmented_colormap_from_list_matches_anchors():
    table = np.array([[0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0, 1.0]])
    cmap = plt.LinearSegmentedColormap.from_list("g", table, 8)
    out = cmap(np.arange(8))
    assert out.shape == (8, 4)
    assert np.allclose(out[0], [0, 0, 0, 1])
    assert np.allclose(out[-1], [1, 1, 1, 1])
    assert np.all(np.diff(out[:, 0]) > 0)


def test_listed_colormap_indexes_discretely():
    cmap = plt.ListedColormap([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], name="rb")
    assert cmap.N == 2
    assert np.allclose(cmap(np.array([0, 1]))[:, :3], [[1, 0, 0], [0, 0, 1]])


def test_user_colormaps_reject_unresolvable_colors():
    with pytest.raises(ValueError):
        plt.LinearSegmentedColormap.from_list("bad", ["definitely-not-a-color"])


def test_cm_get_cmap_returns_resampled_cmap():
    cmap = plt.cm.get_cmap("Blues", 6)
    assert cmap.N == 6


# -- gci / clim / colorbar ------------------------------------------------------


def test_gci_tracks_the_last_mappable():
    fig, ax = plt.subplots()
    image = plt.imshow(np.eye(3))
    assert plt.gci() is image
    collection = plt.scatter([0, 1], [0, 1], c=[0.0, 1.0])
    assert plt.gci() is collection


def test_clim_updates_entry_and_live_colorbar():
    fig, ax = plt.subplots()
    image = plt.imshow(np.random.default_rng(0).normal(size=(4, 4)), cmap="RdGy")
    plt.colorbar()
    plt.clim(-1, 1)
    assert image._entry["kwargs"]["domain"] == (-1.0, 1.0)
    assert ax._colorbar["domain"] == [-1.0, 1.0]


def test_clim_one_sided_autoscales_the_other_side():
    fig, ax = plt.subplots()
    plt.scatter([0, 1, 2], [0, 1, 2], c=[1.0, 5.0, 9.0])
    plt.clim(2, None)
    assert plt.gci()._entry["kwargs"]["domain"] == (2.0, 9.0)


def test_clim_without_a_mappable_fails_loudly():
    plt.figure()
    with pytest.raises(RuntimeError):
        plt.clim(0, 1)


def test_colorbar_returns_handle_and_set_label_lands():
    fig, ax = plt.subplots()
    plt.hist2d(*np.random.default_rng(0).normal(size=(2, 200)), bins=10)
    handle = plt.colorbar()
    handle.set_label("counts in bin")
    assert ax._colorbar["label"] == "counts in bin"


def test_colorbar_ticks_and_extend_reach_both_exports():
    fig, ax = plt.subplots()
    image = plt.imshow(np.eye(4), cmap="viridis")
    plt.colorbar(image, ticks=[0.25, 0.75], extend="both")
    svg = _svg()
    assert "0.25" in svg and "0.75" in svg and "polygon" in svg
    _png()


def test_colorbar_rejects_unknown_kwargs_and_cax():
    fig, ax = plt.subplots()
    image = plt.imshow(np.eye(3))
    with pytest.raises(TypeError):
        plt.colorbar(image, fraction=0.05)
    with pytest.raises(NotImplementedError):
        plt.colorbar(image, cax=ax)


# -- axes surface ----------------------------------------------------------------


def test_get_figure_returns_owner():
    fig, ax = plt.subplots()
    assert ax.get_figure() is fig


def test_set_axisbelow_true_only():
    fig, ax = plt.subplots()
    ax.set_axisbelow(True)
    with pytest.raises(NotImplementedError):
        ax.set_axisbelow(False)


def test_axes_facecolor_kwarg_lands_in_theme():
    ax = plt.axes(facecolor="#E6E6E6")
    assert ax.get_facecolor() == "#E6E6E6"


def test_spines_values_hide_all_renders_transparent_axis():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    for spine in ax.spines.values():
        spine.set_visible(False)
    _png()


def test_hiding_a_single_left_spine_is_renderable():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.spines["left"].set_visible(False)
    _png()
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert "left" not in spec["frame_sides"]


def test_tick_label_handles_recolor_axis_labels():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    labels = ax.get_xticklabels()
    assert labels
    for tick in labels:
        tick.set_color("gray")
    assert ax._axis["x"]["style"]["tick_label_color"] == "gray"


def test_shared_axes_group_reflects_static_sharing():
    fig = plt.figure()
    grid = plt.GridSpec(2, 2)
    first = fig.add_subplot(grid[0, 0])
    second = fig.add_subplot(grid[0, 1], sharey=first)
    group = first.get_shared_y_axes()
    assert group.joined(first, second)
    assert second in group.get_siblings(first)


def test_legend_numpoints_default_accepted_others_loud():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    ax.legend(numpoints=1, scatterpoints=1)
    with pytest.raises(NotImplementedError):
        ax.legend(numpoints=3)


def test_figure_canvas_surface():
    fig = plt.figure()
    assert "png" in fig.canvas.get_supported_filetypes()
    fig.canvas.draw()


# -- GridSpec spans ---------------------------------------------------------------


def test_gridspec_span_rects_are_consistent():
    plt.figure()
    grid = plt.GridSpec(2, 3, wspace=0.4, hspace=0.3)
    single = plt.subplot(grid[0, 0])
    span = plt.subplot(grid[0, 1:])
    assert span._figure_rect[2] > single._figure_rect[2] * 1.8
    assert abs(single._figure_rect[1] - span._figure_rect[1]) < 1e-9
    _png()


def test_gridspec_row_zero_is_at_the_top():
    plt.figure()
    grid = plt.GridSpec(2, 2, hspace=0.3)
    top = plt.subplot(grid[0, 0])
    bottom = plt.subplot(grid[1, 0])
    assert top._figure_rect[1] > bottom._figure_rect[1]


def test_single_cell_specs_keep_the_uniform_grid():
    fig = plt.figure()
    gs = fig.add_gridspec(2, 2)
    ax = fig.add_subplot(gs[0, 1])
    assert ax._figure_rect is None


def test_gridspec_flat_and_negative_indexes():
    grid = plt.GridSpec(4, 4)
    spec = grid[-1, 1:]
    assert spec.rows == (3, 4)
    assert spec.cols == (1, 4)
    flat = grid[5]
    assert flat.rows == (1, 2) and flat.cols == (1, 2)


def test_gridspec_step_slicing_fails_loudly():
    grid = plt.GridSpec(4, 4)
    with pytest.raises(NotImplementedError):
        grid[::2, 0]


def test_subplot_mixes_into_free_form_figures():
    fig = plt.figure()
    fig.add_axes([0.1, 0.5, 0.8, 0.4]).plot([0, 1], [0, 1])
    ax = plt.subplot(2, 3, 1)
    ax.text(0.5, 0.5, "(2, 3, 1)")
    again = plt.subplot(2, 3, 1)
    assert again is ax
    _png()


def test_subplots_subplot_kw_applies_everywhere():
    fig, axes = plt.subplots(2, subplot_kw=dict(xticks=[], yticks=[]))
    for ax in axes:
        assert list(ax._axis["x"].get("tick_values", [])) == []
    _png()


def test_add_subplot_xticklabels_empty_hides_labels():
    fig = plt.figure()
    grid = plt.GridSpec(2, 2)
    ax = fig.add_subplot(grid[0, 0], xticklabels=[])
    assert ax._axis["x"]["tick_label_strategy"] == "off"  # labels hidden, ticks kept


# -- pandas period interop ---------------------------------------------------------


def test_period_values_plot_as_timestamps():
    pd = pytest.importorskip("pandas")
    fig, ax = plt.subplots()
    (line,) = ax.plot(pd.period_range("2012-01", periods=5, freq="M"), np.arange(5))
    assert np.issubdtype(np.asarray(line.get_xdata()).dtype, np.datetime64)
    _png()


# -- pandas dynamic timeseries + xy.pyplot.dates (PDSH 04.09) ----------------


def _ms(stamp: str) -> float:
    return float(np.datetime64(stamp, "ms").astype(np.int64))


def test_pandas_datetime_series_plot_completes():
    pd = pytest.importorskip("pandas")
    index = pd.date_range("2012-01-01", periods=120, freq="D")
    series = pd.Series(np.linspace(4000.0, 5000.0, 120), index=index)
    fig, ax = plt.subplots()
    series.plot(ax=ax)  # pandas' ts path: get_xdata(orig=False) + set_xlim
    lo, hi = ax.get_xlim()
    assert lo == _ms("2012-01-01") and hi == _ms("2012-04-29")
    _png()


def test_get_xdata_orig_false_is_ms_since_epoch():
    fig, ax = plt.subplots()
    x = np.asarray(["2012-01-01", "NaT", "2012-01-03"], dtype="datetime64[ns]")
    (line,) = ax.plot(x, [1.0, 2.0, 3.0])
    assert np.issubdtype(np.asarray(line.get_xdata()).dtype, np.datetime64)
    converted = np.asarray(line.get_xdata(orig=False))
    assert converted.dtype == np.float64
    assert converted[0] == _ms("2012-01-01") and np.isnan(converted[1])
    assert np.asarray(line.get_ydata(orig=False)).dtype == np.float64


def test_month_locator_ticks_month_starts_in_ms():
    locator = plt.dates.MonthLocator()
    ticks = locator.tick_values(_ms("2012-01-15"), _ms("2012-04-20"))
    assert list(ticks) == [_ms("2012-02-01"), _ms("2012-03-01"), _ms("2012-04-01")]
    mid = plt.dates.MonthLocator(bymonthday=15).tick_values(_ms("2012-01-01"), _ms("2012-03-01"))
    assert list(mid) == [_ms("2012-01-15"), _ms("2012-02-15")]


def test_date_formatter_formats_ms_values():
    assert plt.dates.DateFormatter("%b %d")(_ms("2012-11-25")) == "Nov 25"


def test_labeled_minor_ticker_pair_is_promoted_when_majors_are_blank():
    fig, ax = plt.subplots()
    x = np.arange("2012-01-01", "2012-07-01", dtype="datetime64[D]")
    ax.plot(x, np.linspace(0.0, 1.0, len(x)))
    ax.xaxis.set_major_locator(plt.dates.MonthLocator())
    ax.xaxis.set_minor_locator(plt.dates.MonthLocator(bymonthday=15))
    ax.xaxis.set_major_formatter(plt.NullFormatter())
    ax.xaxis.set_minor_formatter(plt.dates.DateFormatter("%b"))
    svg = _svg()
    assert "Feb" in svg and "May" in svg


def test_pandas_period_ordinal_tickers_are_ignored():
    pd = pytest.importorskip("pandas")
    converter = pytest.importorskip("pandas.plotting._matplotlib.converter")
    index = pd.date_range("2012-01-01", periods=30, freq="D")
    fig, ax = plt.subplots()
    ax.plot(index.values, np.arange(30.0))
    ax.xaxis.set_major_locator(
        converter.TimeSeries_DateLocator(index.to_period("D").freq, plot_obj=None)
    )
    ax.xaxis.set_major_formatter(
        converter.TimeSeries_DateFormatter(index.to_period("D").freq, plot_obj=None)
    )
    assert isinstance(ax.xaxis.get_major_locator(), plt.AutoLocator)
    assert isinstance(ax.xaxis.get_major_formatter(), plt.ScalarFormatter)
    _png()


def test_axis_proxy_majorticklabel_handles():
    fig, ax = plt.subplots()
    ax.plot([0.0, 4.0], [0.0, 4.0])
    labels = ax.xaxis.get_majorticklabels()
    assert labels and all(hasattr(label, "set_rotation") for label in labels)
    assert ax.xaxis.get_minorticklabels() == []


def test_figure_get_axes_matches_axes_property():
    fig, axes = plt.subplots(2, 2)
    assert fig.get_axes() == list(axes.ravel())


def test_annotate_accepts_size_alias():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.annotate("peak", xy=(0.5, 0.5), size=13)
    assert "peak" in _svg()


def test_text_date_string_coordinates_on_a_date_axis():
    fig, ax = plt.subplots()
    x = np.arange("2012-01-01", "2012-12-31", dtype="datetime64[D]")
    ax.plot(x, np.linspace(3600.0, 5400.0, len(x)))
    ax.text("2012-1-1", 3950, "New Year's Day", color="gray")  # unpadded, like PDSH
    ax.text("2012-11-25", 4450, "Thanksgiving", ha="center")
    svg = _svg()
    assert "New Year" in svg and "Thanksgiving" in svg


def test_text_string_coordinates_stay_categorical_on_category_axes():
    fig, ax = plt.subplots()
    ax.bar(["a", "b", "c"], [1.0, 3.0, 2.0])
    ax.text("b", 3.1, "peak")
    assert "peak" in _svg()


def test_subplots_facecolor_reaches_figure_and_notebook_display():
    fig, ax = plt.subplots(facecolor="lightgray")
    ax.plot([0.0, 1.0], [0.0, 1.0])
    assert fig.get_facecolor() == "lightgray"
    # The display document paints its own opaque body; the figure patch is a
    # later same-specificity body background override in the head.
    assert "body{background:lightgray}" in fig._repr_html_()
    _png(fig)


# -- annotate arrows and boxes (PDSH 04.09 births cell) ----------------------


def _annotation_specs(ax):
    return ax._build_chart(640, 480).figure()._annotation_specs()


def test_offset_point_annotate_with_arrowprops_becomes_a_callout():
    fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 10.0])
    ax.annotate(
        "peak",
        xy=(5, 5),
        xytext=(30, 30),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=-0.2"),
    )
    (callout,) = [a for a in _annotation_specs(ax) if a["kind"] == "callout"]
    assert callout["text"] == "peak"
    assert callout["style"]["head_style"] == "v"  # "->" is an open stroke head
    assert callout["style"]["curve"] == pytest.approx(-0.2)  # arc3 rad
    assert callout["style"]["gap_start"] > 0  # clears the text patch
    # Offset points go up; pixel offsets go down.
    assert callout["dx"] > 0 and callout["dy"] < 0


def test_arrowstyle_shapes_map_to_engine_arrow_styles():
    fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 10.0])
    ax.annotate(
        "", xy=(1, 1), xytext=(2, 2), arrowprops={"arrowstyle": "|-|,widthA=0.2,widthB=0.2"}
    )
    ax.annotate("w", xy=(3, 3), xytext=(4, 4), arrowprops=dict(arrowstyle="wedge,tail_width=0.5"))
    ax.annotate(
        "f",
        xy=(5, 5),
        xytext=(6, 6),
        arrowprops=dict(
            arrowstyle="fancy", fc="0.6", ec="none", connectionstyle="angle3,angleA=0,angleB=-90"
        ),
    )
    bar, wedge, fancy = [a for a in _annotation_specs(ax) if a["kind"] == "arrow"]
    assert bar["style"]["head_style"] == "bar" and bar["style"]["tail_style"] == "bar"
    assert wedge["style"]["head_style"] == "none"  # the wedge tip IS the pointer
    assert wedge["style"]["shaft_width_start"] > wedge["style"]["shaft_width_end"]
    assert fancy["style"]["shaft_width_end"] > fancy["style"]["shaft_width_start"]
    assert fancy["style"]["angle_a"] == 0.0 and fancy["style"]["angle_b"] == -90.0
    assert fancy["style"]["color"] == "rgb(153,153,153)"  # fc="0.6" shorthand


def test_annotate_date_string_endpoints_draw_a_data_space_arrow():
    fig, ax = plt.subplots()
    x = np.arange("2012-08-01", "2012-10-01", dtype="datetime64[D]")
    ax.plot(x, np.linspace(4000.0, 5000.0, len(x)))
    ax.annotate(
        "",
        xy=("2012-9-1", 4850),
        xytext=("2012-9-7", 4850),
        xycoords="data",
        textcoords="data",
        arrowprops={"arrowstyle": "|-|,widthA=0.2,widthB=0.2"},
    )
    (arrow,) = [a for a in _annotation_specs(ax) if a["kind"] == "arrow"]
    assert arrow["x0"] == pytest.approx(_ms("2012-09-07"))
    assert arrow["x1"] == pytest.approx(_ms("2012-09-01"))
    assert arrow["y0"] == arrow["y1"] == 4850.0


def test_annotate_bbox_becomes_label_box_styles():
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Thanksgiving",
        xy=(0.5, 0.5),
        xytext=(-40, -30),
        textcoords="offset points",
        bbox=dict(boxstyle="round4,pad=.5", fc="0.9"),
        arrowprops=dict(arrowstyle="->"),
    )
    (callout,) = [a for a in _annotation_specs(ax) if a["kind"] == "callout"]
    style = callout["style"]
    assert style["background"] == "rgb(230,230,230)"  # fc="0.9" gray shorthand
    assert style["border"].endswith("black") and style["border_radius"] == 8.0
    assert style["padding"].startswith("6.94")  # pad=.5 of the 13.9px font


def test_annotate_arrowprops_alpha_dims_only_the_arrow():
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.annotate(
        "Christmas",
        xy=(0.9, 0.1),
        xytext=(-30, 0),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="wedge,tail_width=0.5", alpha=0.1),
    )
    (callout,) = [a for a in _annotation_specs(ax) if a["kind"] == "callout"]
    assert callout["style"]["color"] == "rgba(0,0,0,0.1)"
    assert callout["style"]["label_color"] == "black"  # the text stays opaque


def test_callout_arrows_reach_static_exports():
    fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [0.0, 10.0])
    ax.annotate(
        "peak",
        xy=(5, 5),
        xytext=(30, 30),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->"),
    )
    svg = _svg()
    assert "peak" in svg and "<polyline" in svg  # shaft + open V head
    _png(fig)


def test_default_rc_font_sizes_are_explicit_everywhere():
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.text(0.5, 0.5, "note")
    chart = ax._build_chart(640, 480)
    axes = {child.which: child for child in chart.children if hasattr(child, "which")}
    # font.size "medium" (10 pt at dpi 100) must land explicitly: the render
    # client and static exporters otherwise fall back to their 11 px default.
    assert axes["x"].style["tick_label_size"] == pytest.approx(13.8889, rel=1e-4)
    assert axes["x"].style["label_size"] == pytest.approx(13.8889, rel=1e-4)
    (text_ann,) = [a for a in _annotation_specs(ax) if a["kind"] == "text"]
    assert text_ann["style"]["font_size"] == pytest.approx(13.8889, rel=1e-4)
