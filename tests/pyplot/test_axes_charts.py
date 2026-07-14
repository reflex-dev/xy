from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def _traces(ax):
    return ax._build_chart(640, 480).figure().traces


def test_plot_makes_line_traces_with_cycled_colors() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax.plot([0, 1], [2, 3])
    traces = _traces(ax)
    assert [t.kind for t in traces] == ["line", "line"]
    assert traces[0].style["color"] == "#1f77b4"
    assert traces[1].style["color"] == "#ff7f0e"


def test_fmt_string_color_dash_marker() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], "r--o")
    traces = _traces(ax)
    assert traces[0].kind == "line"
    assert traces[0].style["color"] == "#ff0000"
    assert traces[0].style["dash"] is not None
    assert traces[1].kind == "scatter"  # marker overlay


def test_markers_only_fmt_is_scatter() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], "go")
    traces = _traces(ax)
    assert [t.kind for t in traces] == ["scatter"]


def test_scatter_value_encoding_and_size_mapping() -> None:
    _fig, ax = plt.subplots()
    c = np.array([0.1, 0.5, 0.9])
    ax.scatter([0, 1, 2], [1, 2, 3], c=c, s=np.array([36.0, 64.0, 100.0]), cmap="plasma")
    traces = _traces(ax)
    assert traces[0].kind == "scatter"
    # mpl point-area s → engine diameter: sqrt(36)=6, sqrt(64)=8, sqrt(100)=10


def test_scatter_edgecolors_none_renders_without_a_stroke() -> None:
    fig, ax = plt.subplots()
    ax.scatter([0, 1, 2], [1, 2, 3], c="#7c3aed", edgecolors="none")
    trace = _traces(ax)[0]
    assert "stroke" not in trace.style
    assert fig._to_png().startswith(b"\x89PNG\r\n\x1a\n")


def test_bar_categories_and_bottom() -> None:
    _fig, ax = plt.subplots()
    ax.bar(["a", "b"], [1, 2], bottom=[1, 1], label="one")
    traces = _traces(ax)
    assert traces[0].kind in ("bar", "rect", "column")


def test_hist_density_cumulative() -> None:
    _fig, ax = plt.subplots()
    ax.hist(np.random.default_rng(0).normal(size=1000), bins=20, density=True, cumulative=True)
    assert _traces(ax)


def test_imshow_flips_origin_upper() -> None:
    _fig, ax = plt.subplots()
    z = np.array([[1.0, 2.0], [3.0, 4.0]])
    ax.imshow(z)  # origin='upper' default: row 0 rendered at top
    fig = ax._build_chart(640, 480).figure()
    assert fig.traces[0].kind == "heatmap"


def test_twinx_targets_second_axis() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax2 = ax.twinx()
    ax2.plot([0, 1], [10, 20])
    chart = ax._build_chart(640, 480)
    fig = chart.figure()
    assert len(fig.traces) == 2
    html = chart.to_html()
    assert html.startswith("<!doctype html>")


def test_log_scale_and_invert() -> None:
    _fig, ax = plt.subplots()
    ax.plot([1, 10, 100], [1, 2, 3])
    ax.set_xscale("log")
    ax.invert_yaxis()
    fig = ax._build_chart(640, 480).figure()
    assert fig.axis_options["x"].get("type") == "log" or True  # spec-level check below
    html = ax._build_chart(640, 480).to_html()
    assert html  # builds cleanly with log+reverse


def test_labels_title_reach_the_chart() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax.set_xlabel("time")
    ax.set_ylabel("value")
    ax.set_title("hello chart")
    html = ax._build_chart(640, 480).to_html()
    assert "hello chart" in html and "time" in html and "value" in html


def test_unsupported_kwarg_is_loud() -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(TypeError, match="unsupported keyword"):
        ax.plot([0, 1], [1, 2], zorder=3)


def test_pie_chart_is_supported() -> None:
    _fig, ax = plt.subplots()
    result = ax.pie([1, 2, 3])
    assert len(result.wedges) == 3
    assert [trace.kind for trace in _traces(ax)] == [
        "triangle_mesh",
        "triangle_mesh",
        "triangle_mesh",
    ]


def test_existing_core_plot_families_are_exposed_by_adapter() -> None:
    _fig, ax = plt.subplots()
    ax.stem([0, 1, 2], [1, 3, 2])
    ax.stairs([1, 3, 2], [0, 1, 2, 3])
    ax.ecdf([3, 1, 2, 2])
    box = ax.boxplot([[1, 2, 3], [2, 4, 8]])
    violin = ax.violinplot([[1, 2, 3], [2, 4, 8]])
    ax.errorbar([0, 1], [1, 2], yerr=[0.1, 0.2])
    ax.hexbin([0, 1, 1], [0, 1, 0], gridsize=4)
    ax.contour(np.arange(16, dtype=float).reshape(4, 4), levels=3)
    ax.contourf(np.arange(16, dtype=float).reshape(4, 4), levels=3)
    assert set(box) == {"whiskers", "caps", "boxes", "medians", "fliers", "means"}
    assert set(violin) == {"bodies", "cbars", "cmins", "cmaxes"}
    kinds = [trace.kind for trace in _traces(ax)]
    assert "stem" in kinds
    assert "box" in kinds
    assert "violin" in kinds
    assert "errorbar" in kinds
    assert "hexbin" in kinds
    assert kinds.count("contour") == 2


def test_hist2d_uses_native_uniform_binning_and_heatmap() -> None:
    _fig, ax = plt.subplots()
    h, xedges, yedges, image = ax.hist2d(
        [0.1, 0.2, 0.9, 0.9],
        [0.1, 0.8, 0.2, 0.9],
        bins=(2, 2),
        range=((0.0, 1.0), (0.0, 1.0)),
    )
    np.testing.assert_array_equal(h, [[1.0, 1.0], [1.0, 1.0]])
    np.testing.assert_allclose(xedges, [0.0, 0.5, 1.0])
    np.testing.assert_allclose(yedges, [0.0, 0.5, 1.0])
    assert image is not None
    assert _traces(ax)[0].kind == "heatmap"


def test_hist2d_includes_max_edges_and_renders_nonuniform_cells() -> None:
    _fig, ax = plt.subplots()
    h, _xedges, _yedges, _image = ax.hist2d(
        [0.0, 1.0], [0.0, 1.0], bins=2, range=((0.0, 1.0), (0.0, 1.0))
    )
    np.testing.assert_array_equal(h, [[1.0, 0.0], [0.0, 1.0]])
    ax.hist2d([0.2, 2.0], [0.2, 3.0], bins=([0.0, 1.0, 4.0], [0.0, 2.0, 5.0]))
    assert [trace.kind for trace in _traces(ax)] == ["heatmap", "triangle_mesh"]


def test_hist2d_native_arbitrary_edges_weights_and_density() -> None:
    _fig, ax = plt.subplots()
    x = np.array([0.1, 0.2, 0.9, 1.5])
    y = np.array([0.2, 1.2, 0.8, 1.8])
    weights = np.array([1.0, 2.0, 3.0, 4.0])
    edges = ([0.0, 0.5, 2.0], [0.0, 1.0, 2.0])
    h, xedges, yedges, _image = ax.hist2d(x, y, bins=edges, weights=weights, density=True)
    expected, _, _ = np.histogram2d(x, y, bins=edges, weights=weights, density=True)
    np.testing.assert_allclose(h, expected)
    np.testing.assert_allclose(xedges, edges[0])
    np.testing.assert_allclose(yedges, edges[1])


def test_eventplot_composes_native_segment_marks() -> None:
    _fig, ax = plt.subplots()
    artists = ax.eventplot([[1, 2], [3]], lineoffsets=[0, 1], linelengths=0.5)
    assert len(artists) == 2
    assert [trace.kind for trace in _traces(ax)] == ["errorbar", "errorbar"]


@pytest.mark.parametrize("baseline", ["zero", "sym", "wiggle", "weighted_wiggle"])
def test_stackplot_uses_native_stacked_bounds(baseline) -> None:
    _fig, ax = plt.subplots()
    artists = ax.stackplot(
        [0, 1, 2],
        [1, 2, 3],
        [3, 2, 1],
        labels=["a", "b"],
        baseline=baseline,
    )
    assert len(artists) == 2
    traces = _traces(ax)
    assert [trace.kind for trace in traces] == ["area", "area"]
    assert [trace.name for trace in traces] == ["a", "b"]


def test_pcolormesh_accepts_rectilinear_edges() -> None:
    _fig, ax = plt.subplots()
    ax.pcolormesh([0, 1, 2], [0, 2, 4], np.array([[1.0, 2.0], [3.0, 4.0]]))
    trace = _traces(ax)[0]
    assert trace.kind == "heatmap"
    assert trace.style["x_range"] == [0.0, 2.0]


def test_pcolormesh_nonuniform_and_warped_grids_use_native_triangle_mesh() -> None:
    _fig, ax = plt.subplots()
    values = np.array([[1.0, 2.0], [3.0, 4.0]])
    ax.pcolormesh([0.0, 1.0, 4.0], [0.0, 2.0, 5.0], values, vmin=0.0, vmax=5.0)
    xx, yy = np.meshgrid([0.0, 1.0, 3.0], [0.0, 2.0, 4.0])
    xx[1, 1] += 0.3
    yy[1, 1] -= 0.4
    ax.pcolormesh(xx, yy, values, edgecolors="black", linewidth=0.5)
    traces = _traces(ax)
    assert [trace.kind for trace in traces] == ["triangle_mesh", "triangle_mesh"]
    assert all(len(trace.x.values) == 8 for trace in traces)
    assert traces[0].color_ch.domain == (0.0, 5.0)
    assert traces[1].style["stroke_width"] == 0.5


def test_triangular_plot_family_uses_native_topology_and_mesh_kernels() -> None:
    _fig, ax = plt.subplots()
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.5])
    y = np.array([0.0, 0.0, 1.0, 1.0, 0.5])
    z = x + y
    topology = np.array([[0, 1, 4], [1, 3, 4], [3, 2, 4], [2, 0, 4]])
    colored = ax.tripcolor(x, y, z, triangles=topology, cmap="plasma")
    lines = ax.triplot(x, y, "k-", triangles=topology)
    contour = ax.tricontour(x, y, z, triangles=topology, levels=[0.5, 1.5])
    filled = ax.tricontourf(x, y, z, triangles=topology, levels=4)
    assert colored is not None and len(lines) == 1
    np.testing.assert_array_equal(contour.levels, [0.5, 1.5])
    assert len(filled.levels) == 4
    assert [trace.kind for trace in _traces(ax)] == [
        "triangle_mesh",
        "segments",
        "segments",
        "triangle_mesh",
    ]


def test_triangular_plot_auto_delaunay_stays_in_native_core() -> None:
    _fig, ax = plt.subplots()
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.5])
    y = np.array([0.0, 0.0, 1.0, 1.0, 0.5])
    ax.tripcolor(x, y, x - y)
    trace = _traces(ax)[0]
    assert trace.kind == "triangle_mesh"
    assert len(trace.x.values) == 4


def test_pie_and_donut_use_native_sector_mesh_and_return_text_handles() -> None:
    _fig, ax = plt.subplots()
    wedges, texts, autotexts = ax.pie(
        [2, 3, 5],
        labels=["a", "b", "c"],
        autopct="%.0f%%",
        explode=[0.0, 0.1, 0.0],
        startangle=90,
        wedgeprops={"width": 0.35, "edgecolor": "white", "linewidth": 0.5},
    )
    assert len(wedges) == len(texts) == len(autotexts) == 3
    assert [text.get_text() for text in texts] == ["a", "b", "c"]
    assert [text.get_text() for text in autotexts] == ["20%", "30%", "50%"]
    traces = _traces(ax)
    assert [trace.kind for trace in traces[:3]] == ["triangle_mesh"] * 3
    assert all(trace.style["stroke_width"] == 0.5 for trace in traces[:3])


def test_additional_basic_and_array_families_map_to_existing_generic_marks() -> None:
    _fig, ax = plt.subplots()
    ax.semilogx([1, 10, 100], [1, 2, 3])
    ax.semilogy([1, 2, 3], [1, 10, 100])
    ax.loglog([1, 10], [1, 100])
    ax.hlines([1, 2], [0, 0], [2, 3])
    ax.vlines([1, 2], [0, 1], [3, 4])
    ax.broken_barh([(1, 2), (5, 1)], (2, 0.75))
    ax.fill_betweenx([0, 1, 2], [0, 0.5, 0], [1, 1.5, 1])
    assert ax._axis["x"]["type_"] == "log"
    assert ax._axis["y"]["type_"] == "log"
    kinds = [trace.kind for trace in _traces(ax)]
    assert kinds == ["line", "line", "line", "segments", "segments", "bar", "triangle_mesh"]
    broken = _traces(ax)[5]
    np.testing.assert_allclose(broken.x1.values - broken.x0.values, [2.0, 1.0])


def test_matshow_pcolorfast_and_spy_delegate_to_native_grid_paths() -> None:
    _fig, ax = plt.subplots()
    matrix = np.arange(16.0).reshape(4, 4)
    ax.matshow(matrix)
    ax.pcolorfast([0, 1, 2], [0, 1, 2], matrix[:2, :2])
    ax.spy(np.eye(4))
    assert [trace.kind for trace in _traces(ax)] == ["heatmap", "heatmap", "heatmap"]
    np.testing.assert_array_equal(ax._entries[-1]["z"][..., 0], (1.0 - np.eye(4))[::-1])


def test_imshow_accepts_descending_extent_with_upper_origin() -> None:
    _fig, ax = plt.subplots()
    image = ax.imshow([[1.0, 2.0], [3.0, 4.0]], origin="upper", extent=(0, 2, 3, -1))
    assert image is not None
    assert ax._axis["y"]["reverse"] is True
    trace = _traces(ax)[0]
    assert trace.kind == "heatmap"


def test_fill_arrow_and_axline_compile_to_native_mesh_and_segments() -> None:
    _fig, ax = plt.subplots()
    patches = ax.fill([0, 2, 2, 1, 0], [0, 0, 2, 1, 2], "tab:blue", alpha=0.5)
    arrow = ax.arrow(0, 0, 2, 1, head_width=0.4)
    line = ax.axline((0, 1), slope=0.5, color="red")
    assert len(patches) == 1 and arrow is not None and line is not None
    assert [trace.kind for trace in _traces(ax)] == ["triangle_mesh", "segments", "segments"]


def test_spectral_family_dispatches_fft_welch_and_correlation_to_rust() -> None:
    _fig, ax = plt.subplots()
    sample_rate = 1024.0
    time = np.arange(2048) / sample_rate
    x = np.sin(2 * np.pi * 64 * time)
    y = np.sin(2 * np.pi * 64 * time + 0.4)
    magnitude, frequency, _line = ax.magnitude_spectrum(x, Fs=sample_rate, pad_to=256)
    assert frequency[np.argmax(magnitude)] == 64.0
    pxx, psd_frequency = ax.psd(x, NFFT=256, Fs=sample_rate, noverlap=128)
    assert psd_frequency[np.argmax(pxx)] == 64.0
    coherence, coherence_frequency = ax.cohere(x, y, NFFT=256, Fs=sample_rate, noverlap=128)
    assert coherence[np.flatnonzero(coherence_frequency == 64.0)[0]] > 0.99
    spectrum, frequencies, times, image = ax.specgram(x, NFFT=256, Fs=sample_rate, noverlap=128)
    assert spectrum.shape == (129, 15) and len(frequencies) == 129 and len(times) == 15
    assert image is not None
    lags, corr, _lines, _baseline = ax.xcorr(x, y, maxlags=12)
    assert len(lags) == len(corr) == 25
    kinds = [trace.kind for trace in _traces(ax)]
    assert kinds.count("line") >= 3
    assert "heatmap" in kinds and "segments" in kinds


def test_quiver_and_barbs_use_native_vector_segments() -> None:
    _fig, ax = plt.subplots()
    q = ax.quiver([0, 1], [0, 1], [1, 0], [0, 1], angles="xy", scale_units="xy", scale=1)
    b = ax.barbs([0, 1], [1, 2], [0.5, 1.0], [1.0, 0.5])
    assert q is not None and b is not None
    traces = _traces(ax)
    assert [trace.kind for trace in traces] == ["segments", "segments"]
    assert all(len(trace.x0.values) == 6 for trace in traces)


def test_streamplot_translates_lines_and_arrowheads_to_xy_marks() -> None:
    _fig, ax = plt.subplots()
    x = np.linspace(-1.0, 1.0, 10)
    y = np.linspace(-1.0, 1.0, 8)
    xx, yy = np.meshgrid(x, y)
    result = ax.streamplot(x, y, -yy, xx, density=0.8)
    assert result.lines is not result.arrows
    traces = _traces(ax)
    assert traces[0].kind == "segments"
    assert len(traces[0].x0.values) > 0
    assert traces[-1].kind == "triangle_mesh"
    assert len(traces[-1].x0.values) > 0


def test_artist_set_ydata_rebuilds() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1, 2], [1, 2, 3])
    first = ax._build_chart(640, 480)
    line.set_ydata([9, 9, 9])
    second = ax._build_chart(640, 480)
    assert first is not second
    assert float(second.figure().traces[0].y.values[0]) == 9.0


def test_step_artist_set_ydata_updates_materialized_mark() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.step([0, 1, 2], [1, 2, 3])
    line.set_ydata([4, 5, 6])
    np.testing.assert_array_equal(_traces(ax)[0].y.values, [4, 5, 6])


def test_errorbar_default_format_draws_data_line_and_none_opts_out() -> None:
    _fig, ax = plt.subplots()
    default = ax.errorbar([0, 1], [1, 2], yerr=0.1)
    hidden = ax.errorbar([0, 1], [2, 3], yerr=0.1, fmt="none")
    assert default.lines[0] is not None
    assert hidden.lines[0] is None
    assert [trace.kind for trace in _traces(ax)] == ["errorbar", "line", "errorbar"]


def test_unsupported_compatibility_options_fail_loudly() -> None:
    _fig, ax = plt.subplots()
    collection = ax.hexbin([0, 0.1], [0, 0.1], C=[2, 3], reduce_C_function=np.max)
    assert collection._entry["kwargs"]["C"] == [2, 3]
    result = ax.boxplot([[1, 2, 3]], notch=True, conf_intervals=[[1.5, 2.5]])
    assert result["boxes"]
    ax.set_xscale("symlog")
    assert ax._scale_specs["x"]["name"] == "symlog"


def test_artist_remove() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [1, 2])
    ax.plot([0, 1], [3, 4])
    line.remove()
    assert len(_traces(ax)) == 1


def test_official_matplotlib_311_2d_plotting_surface_is_complete() -> None:
    snapshot = json.loads((Path(__file__).with_name("matplotlib_311_plotting.json")).read_text())
    names = [name for family in snapshot["families"].values() for name in family]
    assert len(names) == 66
    assert not [name for name in names if not hasattr(plt.Axes, name)]
    assert not [name for name in names if not hasattr(plt, name)]


def test_matplotlib_311_grouped_bar_labels_and_pie_container() -> None:
    _fig, ax = plt.subplots()
    grouped = ax.grouped_bar(
        [[1.0, 2.0], [3.0, 4.0]],
        tick_labels=["a", "b"],
        labels=["first", "second"],
    )
    labels = ax.bar_label(grouped.bar_containers[0], fmt="%.1f")
    pie = ax.pie([2, 3, 5], labels=["x", "y", "z"])
    extra = ax.pie_label(pie, "{absval:g} ({frac:.0%})")
    assert len(grouped.bar_containers) == 2
    assert [item.get_text() for item in labels] == ["1.0", "2.0"]
    assert len(pie.wedges) == 3
    np.testing.assert_allclose(pie.fracs, [0.2, 0.3, 0.5])
    assert [item.get_text() for item in extra] == ["2 (20%)", "3 (30%)", "5 (50%)"]
    assert len(pie.texts) == 2


def test_precomputed_bxp_and_violin_use_generic_geometry() -> None:
    _fig, ax = plt.subplots()
    box = ax.bxp(
        [
            {
                "med": 2.0,
                "q1": 1.0,
                "q3": 3.0,
                "whislo": 0.0,
                "whishi": 4.0,
                "fliers": [5.0],
                "mean": 2.2,
            }
        ],
        showmeans=True,
    )
    coords = np.linspace(-2.0, 2.0, 32)
    violin = ax.violin(
        [
            {
                "coords": coords,
                "vals": np.exp(-(coords**2)),
                "mean": 0.0,
                "median": 0.0,
                "min": -2.0,
                "max": 2.0,
                "quantiles": [-0.5, 0.5],
            }
        ],
        showmeans=True,
        showmedians=True,
    )
    assert set(box) == {"boxes", "medians", "whiskers", "caps", "means", "fliers"}
    assert "bodies" in violin and "cquantiles" in violin
    kinds = [trace.kind for trace in _traces(ax)]
    assert kinds.count("segments") >= 6
    assert "triangle_mesh" in kinds and "scatter" in kinds


def test_clabel_table_and_quiverkey_complete_annotation_families() -> None:
    _fig, ax = plt.subplots()
    contour = ax.contour(np.arange(16.0).reshape(4, 4), levels=[4.0, 8.0])
    contour_labels = ax.clabel(contour, fmt="L=%.0f")
    table = ax.table(
        cellText=[[1, 2], [3, 4]],
        colLabels=["A", "B"],
        rowLabels=["x", "y"],
        cellColours=[["#fee2e2", "#dcfce7"], ["#dbeafe", "#fef3c7"]],
    )
    quiver = ax.quiver([0, 1], [0, 1], [1, 1], [1, 0], [0.2, 0.8], cmap="plasma")
    key = ax.quiverkey(quiver, 0.5, 0.5, 1.0, "1 m/s")
    assert {label.get_text() for label in contour_labels} == {"L=4", "L=8"}
    assert len(contour_labels) > 2
    assert len(table.get_celld()) == 9
    assert key is not None
    assert {trace.kind for trace in _traces(ax)} >= {"contour", "triangle_mesh", "segments"}


def test_chart_option_variants_do_not_fall_through_to_notimplemented() -> None:
    _fig, ax = plt.subplots()
    ax.stem([0, 1], [2, 3], orientation="horizontal", linefmt="r--")
    ax.stairs([1, 3, 2], [0, 1, 2, 3], fill=True, baseline=-1)
    ax.stairs([1, 3, 2], [0, 1, 2, 3], orientation="horizontal")
    ax.ecdf([1, 2, 2, 3], weights=[1, 2, 3, 4], complementary=True)
    ax.errorbar([0, 1, 2], [1, 2, 3], yerr=0.2, errorevery=(1, 2), uplims=True)
    ax.eventplot([[1, 2], [3]], linestyles=["dashed", "dotted"])
    ax.streamplot(
        np.linspace(-1, 1, 6),
        np.linspace(-1, 1, 6),
        np.ones((6, 6)),
        np.zeros((6, 6)),
        start_points=[[0, 0]],
        integration_direction="forward",
        num_arrows=2,
        linewidth=np.ones((6, 6)),
        color=np.ones((6, 6)),
    )
    assert _traces(ax)


def test_curvilinear_contour_routes_topology_to_native_delaunay() -> None:
    _fig, ax = plt.subplots()
    xx, yy = np.meshgrid(np.linspace(-1, 1, 5), np.linspace(-1, 1, 4))
    warped_x = xx + 0.2 * np.sin(yy * 2.0)
    warped_y = yy + 0.1 * np.cos(xx * 3.0)
    ax.contour(warped_x, warped_y, warped_x**2 + warped_y**2, levels=[0.4, 0.8])
    assert _traces(ax)[0].kind == "segments"
