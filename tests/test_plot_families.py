from __future__ import annotations

import numpy as np
import pytest

import xy as fc
from xy._figure import Figure


def test_error_band_and_errorbar_use_compact_geometry() -> None:
    fig = (
        Figure()
        .error_band([0, 1, 2], [1, 2, 1], [2, 3, 2])
        .errorbar([0, 1, 2], [1, 2, 1], yerr=[0.1, 0.2, 0.1])
    )
    spec, _blob = fig.build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["error_band", "errorbar"]
    assert spec["traces"][0]["base"] >= 0
    assert spec["traces"][1]["n_marks"] == 9  # main segment + two caps per point
    y_range = fig.y_range()
    assert y_range[0] < 0.9
    assert y_range[1] > 2.1


def test_large_errorbars_report_segment_reduction() -> None:
    n = 20_000
    fig = Figure().errorbar(np.arange(n), np.arange(n, dtype=float), yerr=1.0)
    spec, _ = fig.build_payload(px_width=100)
    trace = spec["traces"][0]
    assert trace["tier"] == "decimated"
    assert trace["n_points"] == n
    assert trace["n_marks"] == 3 * max(1024, 100 * 4)


def test_box_violin_and_ecdf_have_bounded_mark_counts() -> None:
    rng = np.random.default_rng(12)
    groups = [rng.normal(size=10_000), rng.normal(loc=1, size=10_000)]
    box_spec, _ = Figure().box(groups).build_payload()
    violin_spec, _ = Figure().violin(groups, bins=32).build_payload()
    ecdf_spec, _ = Figure().ecdf(np.concatenate(groups), bins=128).build_payload()
    assert box_spec["traces"][1]["n_marks"] == 2
    assert violin_spec["traces"][0]["n_marks"] <= 64
    assert ecdf_spec["traces"][0]["n_marks"] <= 129


def test_distribution_marks_group_1d_values_by_categories() -> None:
    fig = Figure().box([1, 2, 3, 10, 11, 12], x=["a", "a", "a", "b", "b", "b"])
    spec, _ = fig.build_payload()
    assert spec["traces"][1]["n_marks"] == 2


def test_hexbin_is_screen_bounded_and_contour_emits_isolines() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=100_000)
    y = x * 0.5 + rng.normal(size=100_000)
    hex_spec, _ = Figure().hexbin(x, y, gridsize=32).build_payload()
    contour_spec, _ = (
        Figure().contour(np.arange(64, dtype=float).reshape(8, 8), levels=5).build_payload()
    )
    assert hex_spec["traces"][0]["kind"] == "hexbin"
    ny = int(32 / np.sqrt(3.0))
    assert hex_spec["traces"][0]["n_marks"] <= (32 + 1) * (ny + 1) + 32 * ny
    # Centers plus one color value per cell; renderers expand the shared
    # hexagon geometry (style hex_dx/hex_dy) locally instead of shipping
    # six vertices per cell across seven columns.
    assert all(key in hex_spec["traces"][0] for key in ("x", "y", "color"))
    assert "x0" not in hex_spec["traces"][0]
    assert hex_spec["traces"][0]["style"]["hex_dx"] > 0
    assert hex_spec["traces"][0]["style"]["hex_dy"] > 0
    assert contour_spec["traces"][0]["kind"] == "contour"
    assert contour_spec["traces"][0]["n_marks"] > 0


def test_step_stairs_and_stem_share_expected_wire_shapes() -> None:
    fig = Figure().step([0, 1, 2], [1, 2, 1]).stairs([1, 2], [0, 1, 2]).stem([0, 1], [1, 2])
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["kind"] == "line"
    assert spec["traces"][0]["style"]["step"] == "post"
    assert spec["traces"][1]["style"]["step"] == "post"
    assert [trace["kind"] for trace in spec["traces"][2:]] == ["stem", "scatter"]


def test_generic_segments_share_instanced_renderers() -> None:
    fig = Figure().segments([0, 1], [0, 1], [1, 2], [1, 0], color="#336699")
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["kind"] == "segments"
    assert spec["traces"][0]["n_marks"] == 2
    assert "<line" in fig.to_svg()
    assert fig.to_png(engine=fc.Engine.default).startswith(b"\x89PNG")


def test_triangle_mesh_ships_per_triangle_color_and_renders_static_exports() -> None:
    fig = Figure().triangle_mesh(
        [0.0, 1.0],
        [0.0, 0.0],
        [1.0, 2.0],
        [0.0, 0.0],
        [0.5, 1.5],
        [1.0, 1.0],
        color=[0.0, 1.0],
        stroke="#111827",
        stroke_width=0.75,
    )
    spec, _ = fig.build_payload()
    trace = spec["traces"][0]
    assert trace["kind"] == "triangle_mesh"
    assert trace["n_marks"] == 2
    assert trace["color"]["mode"] == "continuous"
    assert all(name in trace for name in ("x0", "y0", "x1", "y1", "x2", "y2"))
    svg = fig.to_svg()
    assert svg.count("<polygon") == 2
    assert fig.to_png(engine=fc.Engine.default).startswith(b"\x89PNG")


def test_triangle_mesh_filters_nonfinite_geometry_and_color_rows() -> None:
    fig = Figure().triangle_mesh(
        [0.0, np.nan, 2.0],
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 3.0],
        [0.0, 0.0, 0.0],
        [0.5, 1.5, 2.5],
        [1.0, 1.0, 1.0],
        color=[0.0, 1.0, np.nan],
    )
    spec, _ = fig.build_payload()
    trace = spec["traces"][0]
    assert trace["n_points"] == 3
    assert trace["n_marks"] == 1
    assert spec["columns"][trace["color"]["buf"]]["len"] == 1


def test_new_marks_reject_invalid_inputs_without_mutating_figure() -> None:
    fig = Figure().line([0, 1], [1, 2])
    with pytest.raises(ValueError, match="errorbar requires"):
        fig.errorbar([0], [1])
    with pytest.raises(ValueError, match="strictly increasing"):
        fig.stairs([1, 2], [0, 2, 1])
    with pytest.raises(ValueError, match="at least one finite"):
        fig.hexbin([np.nan], [np.nan])
    assert len(fig.traces) == 1


def _step_value(sx: np.ndarray, sy: np.ndarray, q: float) -> float:
    """Evaluate an expanded step polyline at x=q (value held from the left)."""
    return float(sy[np.searchsorted(sx, q, side="right") - 1])


def test_stairs_ships_compact_form_and_renders_correct_bins() -> None:
    from xy._svg import _step_arrays

    edges = np.array([0.0, 1.0, 3.0, 6.0])
    vals = np.array([2.0, 5.0, 1.0])
    mids = (edges[:-1] + edges[1:]) / 2.0
    for where in ("pre", "post", "mid"):
        fig = Figure().stairs(vals, edges, where=where)
        trace = fig.traces[0]
        assert trace.style["step"] == where
        # Compact canonical form: k+1 shipped points, expansion is client-side.
        assert len(trace.x.values) == len(edges)
        np.testing.assert_array_equal(trace.x.values, edges)
    for where in ("pre", "post"):
        fig = Figure().stairs(vals, edges, where=where)
        trace = fig.traces[0]
        sx, sy = _step_arrays(trace.x.values, trace.y.values, where)
        # Every bin [edges[i], edges[i+1]] renders at height vals[i]; pre and
        # post produce identical bin geometry for edge-aligned stairs.
        for mid, val in zip(mids, vals, strict=True):
            assert _step_value(sx, sy, float(mid)) == val
    fig = Figure().stairs(vals, edges, where="mid")
    trace = fig.traces[0]
    sx, sy = _step_arrays(trace.x.values, trace.y.values, "mid")
    # mid transitions at bin centers: vals[0] before the first center, and
    # vals[i] holds across interior edge i.
    assert _step_value(sx, sy, 0.25) == vals[0]
    assert _step_value(sx, sy, float(edges[1])) == vals[1]
    assert _step_value(sx, sy, float(edges[2])) == vals[2]
    with pytest.raises(ValueError, match="at least one value"):
        Figure().stairs([], [0.0])


def test_grouped_box_matches_naive_grouping_semantics() -> None:
    rng = np.random.default_rng(42)
    vals = rng.normal(size=10_000)
    keys = rng.integers(0, 50, size=10_000).astype(np.float64)
    fig = Figure().box(vals, group=keys)
    box_trace = fig.traces[1]
    median_trace = fig.traces[2]
    unique = np.unique(keys)
    naive = [vals[keys == key] for key in unique]
    np.testing.assert_allclose((box_trace.x0.values + box_trace.x1.values) / 2.0, unique)
    np.testing.assert_allclose(box_trace.y0.values, [np.percentile(g, 25.0) for g in naive])
    np.testing.assert_allclose(box_trace.y1.values, [np.percentile(g, 75.0) for g in naive])
    np.testing.assert_allclose(median_trace.y0.values, [np.median(g) for g in naive])


def test_categorical_group_keeps_first_appearance_order() -> None:
    fig = Figure().box([10.0, 1.0, 12.0, 3.0], group=["b", "a", "b", "a"])
    assert fig._axis_categories["x"] == ["b", "a"]
    median_trace = fig.traces[2]
    np.testing.assert_allclose(median_trace.y0.values, [11.0, 2.0])


def test_box_whiskers_end_at_observations_inside_fence() -> None:
    from xy.marks import _distribution_stats

    vals = np.array([0.0, 10.0, 11.0, 12.0, 13.0, 14.0, 40.0])
    q1, _med, q3, low, high, outliers = _distribution_stats(vals)
    iqr = q3 - q1
    inside = vals[(vals >= q1 - 1.5 * iqr) & (vals <= q3 + 1.5 * iqr)]
    # Whisker ends are observations, not the bare Tukey fence values.
    assert low == inside.min()
    assert high == inside.max()
    assert low in vals and high in vals
    np.testing.assert_array_equal(np.sort(outliers), np.sort(vals[(vals < low) | (vals > high)]))


def test_binned_ecdf_uses_right_edges_and_never_exceeds_exact() -> None:
    rng = np.random.default_rng(9)
    vals = rng.normal(size=5_000)
    fig = Figure().ecdf(vals, bins=64)
    trace = fig.traces[0]
    sx, sy = trace.x.values, trace.y.values
    # Below the first bin's right edge the binned CDF is exactly 0.
    assert sy[0] == 0.0
    assert sx[0] == vals.min()
    exact = np.searchsorted(np.sort(vals), sx, side="right") / len(vals)
    assert np.all(sy <= exact + 1e-12)
    assert sy[-1] == 1.0


def test_violin_density_is_not_damped_at_the_boundary() -> None:
    rng = np.random.default_rng(21)
    vals = rng.exponential(scale=1.0, size=20_000)
    fig = Figure().violin(vals, bins=32)
    trace = fig.traces[0]
    widths = trace.x1.values - trace.x0.values
    # Exponential mass piles at 0: the widest band must be the boundary bin.
    assert int(np.argmax(widths)) == 0


def test_errorbar_cap_size_zero_ships_only_main_segments() -> None:
    n = 20_000
    fig = Figure().errorbar(np.arange(n), np.arange(n, dtype=float), yerr=1.0, cap_size=0)
    assert len(fig.traces[0].x0.values) == n
    spec, _ = fig.build_payload(px_width=100)
    trace = spec["traces"][0]
    assert trace["tier"] == "decimated"
    assert trace["n_marks"] == max(1024, 100 * 4)


def test_errorbar_default_cap_size_tracks_data_spacing() -> None:
    x = np.array([0.0, 1.0, 2.0, 4.0])
    fig = Figure().errorbar(x, [1.0, 2.0, 1.0, 2.0], yerr=0.5)
    x0 = fig.traces[0].x0.values
    # Auto cap: 0.25 x median adjacent spacing of distinct x (here 1.0).
    np.testing.assert_allclose(x0[len(x) : 2 * len(x)], x - 0.25)
    fig_one = Figure().errorbar([5.0], [1.0], yerr=0.5)
    np.testing.assert_allclose(fig_one.traces[0].x0.values[1:], [5.0 - 0.4, 5.0 - 0.4])


def test_errorbar_rejects_non_finite_error_values() -> None:
    fig = Figure()
    with pytest.raises(ValueError, match="finite"):
        fig.errorbar([0.0, 1.0], [1.0, 2.0], yerr=[np.nan, 0.1])
    with pytest.raises(ValueError, match="finite"):
        fig.errorbar([0.0, 1.0], [1.0, 2.0], xerr=[0.1, np.inf])
    assert len(fig.traces) == 0
    assert len(fig.store) == 0


def test_hexbin_does_not_retain_raw_points_in_the_store() -> None:
    rng = np.random.default_rng(4)
    n = 1_000_000
    fig = Figure().hexbin(rng.normal(size=n), rng.normal(size=n), gridsize=32)
    total_elements = sum(len(col) for col in fig.store.columns)
    # Only occupied bin centers may be resident, never the raw points.
    ny = int(32 / np.sqrt(3.0))
    assert total_elements <= 2 * ((32 + 1) * (ny + 1) + 32 * ny)
    assert fig.traces[0].count == n
    failing = Figure()
    with pytest.raises(ValueError, match="no finite points"):
        failing.hexbin([0.0, 0.1], [0.0, 0.1], range=((10.0, 11.0), (10.0, 11.0)))
    assert len(failing.store) == 0


def test_failing_filled_contour_rolls_back_the_heatmap() -> None:
    fig = Figure()
    z = np.arange(16, dtype=float).reshape(4, 4)
    with pytest.raises(ValueError, match="do not intersect"):
        fig.contour(z, levels=np.array([1e9]), filled=True)
    assert len(fig.traces) == 0
    assert len(fig.store) == 0


def test_failing_box_and_violin_commit_no_axis_categories() -> None:
    for mark in ("box", "violin"):
        fig = Figure()
        with pytest.raises(ValueError, match="at least one finite group"):
            getattr(fig, mark)([np.nan, np.nan], x=["a", "b"])
        assert fig._axis_categories == {}
        assert len(fig.traces) == 0


def test_box_2d_values_are_column_oriented() -> None:
    rng = np.random.default_rng(8)
    tall = rng.normal(size=(100, 3))
    spec, _ = Figure().box(tall).build_payload()
    assert spec["traces"][1]["n_marks"] == 3
    wide = rng.normal(size=(3, 100))
    spec, _ = Figure().box(wide).build_payload()
    assert spec["traces"][1]["n_marks"] == 100
    # Sequence-of-datasets input keeps one group per item (ragged allowed).
    spec, _ = Figure().box([[1.0, 2.0, 3.0], [4.0, 5.0]]).build_payload()
    assert spec["traces"][1]["n_marks"] == 2
    with pytest.raises(ValueError, match="must be 1-D"):
        Figure().box(tall, x=0)


def test_facet_chart_filters_table_and_shares_domains() -> None:
    data = {
        "x": [0, 1, 2, 0, 1, 2],
        "y": [1, 2, 3, 3, 2, 1],
        "group": ["a", "a", "a", "b", "b", "b"],
    }
    grid = fc.facet_chart(fc.line(x="x", y="y"), by="group", data=data, cols=2).figure()
    assert len(grid.figures) == 2
    assert grid.labels == ("a", "b")
    assert grid.figures[0].x_range() == grid.figures[1].x_range()
    assert grid.figures[0].y_range() == grid.figures[1].y_range()
    assert len(grid.to_html()) > 1000
