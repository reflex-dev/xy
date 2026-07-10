from __future__ import annotations

import numpy as np
import pytest

import fastcharts as fc
from fastcharts._figure import Figure


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
    assert hex_spec["traces"][0]["n_marks"] <= 32 * 32
    assert contour_spec["traces"][0]["kind"] == "contour"
    assert contour_spec["traces"][0]["n_marks"] > 0


def test_step_stairs_and_stem_share_expected_wire_shapes() -> None:
    fig = Figure().step([0, 1, 2], [1, 2, 1]).stairs([1, 2], [0, 1, 2]).stem([0, 1], [1, 2])
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["kind"] == "line"
    assert spec["traces"][0]["style"]["step"] == "post"
    assert spec["traces"][1]["style"]["step"] == "post"
    assert [trace["kind"] for trace in spec["traces"][2:]] == ["stem", "scatter"]


def test_new_marks_reject_invalid_inputs_without_mutating_figure() -> None:
    fig = Figure().line([0, 1], [1, 2])
    with pytest.raises(ValueError, match="errorbar requires"):
        fig.errorbar([0], [1])
    with pytest.raises(ValueError, match="strictly increasing"):
        fig.stairs([1, 2], [0, 2, 1])
    with pytest.raises(ValueError, match="at least one finite"):
        fig.hexbin([np.nan], [np.nan])
    assert len(fig.traces) == 1


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
