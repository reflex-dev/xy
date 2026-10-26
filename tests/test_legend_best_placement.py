"""`loc="best"` and the closed legend-placement vocabulary.

The payload records both a concrete first-frame location and automatic intent:
static writers stay deterministic while the browser can reconsider the result
from rendered geometry after its layout or visible view changes.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

import xy
from xy import _legendfit


def _loc(figure) -> str:
    spec, _blob = figure.build_payload()
    return (spec.get("legend") or {}).get("loc")


def _legend_label_xy(svg: str, name: str) -> tuple[float, float]:
    match = re.search(rf'<text x="([0-9.]+)" y="([0-9.]+)"[^>]*>{name}</text>', svg)
    assert match, f"no legend entry {name!r} in the SVG"
    return float(match.group(1)), float(match.group(2))


# --- the vocabulary ----------------------------------------------------------


@pytest.mark.parametrize(
    "spelling,expected",
    [
        ("upper right", "upper right"),
        # Case and surrounding whitespace are normalized so the writers' token
        # match sees a value it recognizes...
        ("UPPER RIGHT", "upper right"),
        ("  lower   left ", "lower left"),
        # ...but the caller's spelling is otherwise preserved. `top`/`bottom`
        # are public core aliases that `_svg._legend_layout` resolves to the
        # same geometry, and `tests/pyplot/test_best_legend_placement.py` pins
        # that passthrough — rewriting them here is a core API change.
        ("top left", "top left"),
        ("top-left", "top-left"),
        ("bottom_right", "bottom_right"),
        ("TOP RIGHT", "top right"),
        ("right", "right"),  # Matplotlib's code 5; the layout centers it
        ("right upper", "right upper"),  # either word order is accepted
    ],
)
def test_locations_normalize(spelling: str, expected: str) -> None:
    assert xy.legend(loc=spelling).loc == expected


@pytest.mark.parametrize(
    "spelling", ["northeast", "outside right", "zzz", "", "middle left", "upper middle"]
)
def test_an_unknown_location_raises_instead_of_landing_somewhere(spelling: str) -> None:
    # The writers resolve a location by substring, so an unrecognized string
    # does not fail — it lands somewhere. Spellings that are unambiguous are
    # normalized above; anything left is refused rather than guessed at.
    with pytest.raises(ValueError, match="is not a legend location"):
        xy.legend(loc=spelling)


@pytest.mark.parametrize(
    "alias,canonical",
    [("top left", "upper left"), ("bottom right", "lower right"), ("TOP RIGHT", "upper right")],
)
def test_an_alias_lands_where_it_reads(alias: str, canonical: str) -> None:
    # docs/content/components/facets-and-layers.md uses loc="top left". The
    # value reaches the wire in the caller's own spelling; what must match is
    # the geometry the writers derive from it.
    def svg(loc: str) -> str:
        return xy.line_chart(xy.line([0.0, 1.0], [0.0, 1.0], name="a"), xy.legend(loc=loc)).to_svg()

    assert _legend_label_xy(svg(alias), "a") == _legend_label_xy(svg(canonical), "a")


# --- best placement ----------------------------------------------------------


def test_best_avoids_the_corner_the_data_occupies() -> None:
    rising = xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [0.0, 1.0, 2.0], name="a"), xy.legend(loc="best")
    ).figure()
    falling = xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [2.0, 1.0, 0.0], name="a"), xy.legend(loc="best")
    ).figure()

    assert _loc(rising) == "upper left"
    assert _loc(falling) == "upper right"


def test_best_prefers_the_open_lower_right_over_busy_upper_left() -> None:
    # Occupy every canonical candidate except lower-right, with deliberately
    # dense activity in the motivating upper-left corner from issue #485.
    x = [0.05] * 12 + [0.95, 0.05, 0.95, 0.05, 0.50, 0.50, 0.50]
    y = [0.95] * 12 + [0.95, 0.05, 0.50, 0.50, 0.05, 0.95, 0.50]
    figure = xy.scatter_chart(
        xy.scatter(x, y, size=30, name="activity"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=640,
        height=420,
    ).figure()
    assert _loc(figure) == "lower right"


def test_best_ships_a_concrete_fallback_with_live_auto_intent() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="a"), xy.legend(loc="best")
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["legend"]["loc"] != "best"
    assert spec["legend"]["loc"] in _legendfit._CANDIDATE_ORDER
    # The concrete location keeps static writers deterministic; the separate
    # intent flag lets the live renderer reconsider it after layout/view
    # changes without guessing whether the author requested a fixed corner.
    assert spec["legend"]["auto_loc"] == "best"


def test_polar_best_ships_only_a_concrete_location() -> None:
    figure = xy.chart(
        xy.line([0.0, 1.0], [0.2, 0.8], name="a"),
        xy.legend(loc="best"),
        coords="polar",
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["legend"]["loc"] in _legendfit._CANDIDATE_ORDER
    assert "auto_loc" not in spec["legend"]


def test_an_unspecified_legend_location_keeps_the_compatible_default() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [1.0, 0.0], name="a"),
        xy.legend(),
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["legend"] == {"loc": None, "ncols": 1}


def test_explicit_location_bypasses_automatic_placement() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [1.0, 0.0], name="a"),
        xy.legend(loc="lower center"),
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["legend"] == {"loc": "lower center", "ncols": 1}


def test_explicit_anchor_and_location_are_preserved_exactly() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [1.0, 0.0], name="a"),
        xy.legend(loc="upper left", anchor=(1.2, 0.5)),
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["legend"] == {
        "loc": "upper left",
        "anchor": [1.2, 0.5],
        "ncols": 1,
    }


def test_initial_candidates_use_the_measured_legend_footprint() -> None:
    def footprint(font_size: str) -> tuple[float, float]:
        figure = xy.line_chart(
            xy.line([0.0, 1.0], [0.0, 1.0], name="Measured series"),
            xy.legend(loc="best", style={"fontSize": font_size}),
        ).figure()
        spec, _blob = figure.build_payload()
        candidates, _plot_size = _legendfit._measured_candidates(
            spec, spec["legend"], ["Measured series"]
        )
        _name, x0, x1, y0, y1 = candidates[0]
        return x1 - x0, y1 - y0

    small = footprint("11px")
    large = footprint("22px")
    assert large[0] > small[0]
    assert large[1] > small[1]


def test_emitted_column_decoding_keeps_blob_and_writer_rows_aligned() -> None:
    from xy._payload import _PayloadWriter

    writer = _PayloadWriter()
    geometry = 1e12 + np.arange(5, dtype=np.float64) * 256.0
    geometry_ref = writer.ship_values(geometry)
    rgba = np.arange(20, dtype=np.uint8).reshape(5, 4)
    rgba_ref = writer.ship_u8(rgba)
    spec = {"columns": writer.columns}

    expected_geometry = geometry[[0, 2, 4]]
    expected_rgba = rgba[[0, 2, 4]].astype(np.float64)
    for source in (writer, writer.blob()):
        np.testing.assert_array_equal(
            _legendfit._rendered_column(spec, source, geometry_ref, 3),
            expected_geometry,
        )
        np.testing.assert_array_equal(
            _legendfit._rendered_column_rows(spec, source, rgba_ref, 4, 3),
            expected_rgba,
        )


def test_best_moves_the_legend_off_the_data_in_the_svg() -> None:
    months = list(range(6))
    revenue = [12.0, 19.0, 15.0, 27.0, 24.0, 33.0]
    chart = xy.line_chart(xy.line(months, revenue, name="Revenue"), xy.legend(loc="best"))
    centered = xy.line_chart(xy.line(months, revenue, name="Revenue"), xy.legend(loc="center"))
    assert _legend_label_xy(chart.to_svg(), "Revenue") != _legend_label_xy(
        centered.to_svg(), "Revenue"
    )


def test_best_falls_back_when_there_is_nothing_to_score() -> None:
    # An all-NaN series has no finite pair; placement must still be a real
    # location rather than an exception or a None on the wire.
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [float("nan"), float("nan")], name="a"),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_scores_a_large_series_without_a_full_scan() -> None:
    # normalize() strides before the isfinite pass; the result must still be
    # the empty corner, not a fallback.
    n = 500_000
    x = np.linspace(0.0, 1.0, n)
    figure = xy.line_chart(xy.line(x, x, name="a"), xy.legend(loc="best")).figure()
    assert _loc(figure) == "upper left"


def test_best_counts_a_line_segment_crossing_a_candidate() -> None:
    # Neither endpoint is inside the upper-right legend box, but the rendered
    # segment crosses it on the way out of the fixed view.
    figure = xy.line_chart(
        xy.line([0.70, 1.10], [0.70, 1.10], name="line"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


def test_best_counts_a_thick_line_touching_a_candidate() -> None:
    def placement(width: float) -> str:
        figure = xy.line_chart(
            xy.line([0.90, 0.98], [0.90, 0.90], width=width, name="line"),
            xy.x_axis(domain=(0.0, 1.0)),
            xy.y_axis(domain=(0.0, 1.0)),
            xy.legend(loc="best"),
            width=640,
            height=420,
        ).figure()
        return _loc(figure)

    # The centerline sits just below the upper-right box. Only the 30px stroke
    # reaches it, so centerline-only intersection misses visible overlap.
    assert placement(1.0) == "upper right"
    assert placement(30.0) == "upper left"


def test_best_counts_the_visible_area_fill() -> None:
    # The top edge crosses the upper-right candidate and the fill below it is
    # visible geometry; point-anchor scoring alone incorrectly leaves the
    # legend in that corner.
    figure = xy.area_chart(
        xy.area([0.70, 1.10], [0.70, 1.10], base=[0.60, 0.60], name="area"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


def test_best_counts_bar_rectangles_not_only_their_centers() -> None:
    # The center falls just left of the measured candidate while the authored
    # width carries the rectangle into it.
    figure = xy.bar_chart(
        xy.bar([0.75], [1.0], width=0.40, name="bar"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


@pytest.mark.parametrize("kind", ["column", "histogram"])
def test_best_counts_every_public_rectangular_mark(kind: str) -> None:
    axes = (
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 3.0)),
        xy.legend(loc="best"),
    )
    if kind == "column":
        figure = xy.column_chart(
            xy.column([0.75], [3.0], width=0.40, name="column"), *axes
        ).figure()
    else:
        figure = xy.histogram_chart(
            xy.histogram([0.75, 0.80, 0.85], bins=[0.60, 1.0], name="histogram"),
            *axes,
        ).figure()
    assert _loc(figure) == "upper left"


def test_best_compares_area_coverage_not_only_intersection() -> None:
    # Every upper candidate touches this filled wedge, but the upper-left sees
    # only a thin sliver while the upper-right is almost full. A boolean
    # polygon-intersection score makes those candidates tie.
    figure = xy.area_chart(
        xy.area([0.0, 1.0], [0.95, 1.0], base=[0.0, 0.0], name="area"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


def test_best_ignores_fully_transparent_marks() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], opacity=0.0, name="invisible"),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_ignores_an_all_transparent_direct_channel() -> None:
    figure = xy.bar_chart(
        xy.bar([0.75, 0.90], [1.0, 1.0], opacity=[0.0, 0.0], name="invisible"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


@pytest.mark.parametrize("kind", ["line", "scatter", "area", "bar"])
def test_best_ignores_known_zero_alpha_paint(kind: str) -> None:
    if kind == "line":
        mark = xy.line([0.85, 0.95], [0.90, 0.95], color="#ff000000", name="a")
    elif kind == "scatter":
        mark = xy.scatter([0.97], [0.97], size=60, color="#ff000000", name="a")
    elif kind == "area":
        mark = xy.area(
            [0.85, 0.95],
            [0.90, 0.95],
            base=[0.80, 0.80],
            color="#ff000000",
            line_opacity=0,
            name="a",
        )
    else:
        mark = xy.bar([0.90], [0.20], base=[0.80], width=0.20, color="#ff000000", name="a")
    figure = xy.chart(
        mark,
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


@pytest.mark.parametrize("kind", ["line", "scatter", "bar"])
def test_best_ignores_zero_component_opacity(kind: str) -> None:
    if kind == "line":
        mark = xy.line(
            [0.85, 0.95],
            [0.90, 0.95],
            name="a",
            style={"stroke_opacity": 0},
        )
    elif kind == "scatter":
        mark = xy.scatter(
            [0.97],
            [0.97],
            size=60,
            name="a",
            style={"fill_opacity": 0, "stroke_opacity": 0},
        )
    else:
        mark = xy.bar(
            [0.90],
            [0.20],
            base=[0.80],
            width=0.20,
            name="a",
            style={"fill_opacity": 0, "stroke_opacity": 0},
        )
    figure = xy.chart(
        mark,
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_ignores_direct_rgba_when_every_mark_is_transparent() -> None:
    figure = xy.scatter_chart(
        xy.scatter(
            [0.85, 0.95],
            [0.90, 0.95],
            color=["#ff000000", "#00ff0000"],
            name="a",
        ),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_uses_intrinsic_rgba_for_the_artist_alpha_sentinel() -> None:
    rgba = np.tile([1.0, 0.0, 0.0, 1.0], (2, 1))
    figure = xy.bar_chart(
        xy.bar(
            [0.85, 0.95],
            [0.20, 0.20],
            base=[0.80, 0.80],
            width=0.10,
            color=rgba,
            _artist_alpha=[-1.0, -1.0],
            name="bars",
        ),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


def test_best_artist_alpha_override_replaces_transparent_intrinsic_rgba() -> None:
    rgba = np.tile([1.0, 0.0, 0.0, 0.0], (2, 1))
    figure = xy.bar_chart(
        xy.bar(
            [0.85, 0.95],
            [0.20, 0.20],
            base=[0.80, 0.80],
            width=0.10,
            color=rgba,
            _artist_alpha=[1.0, 1.0],
            name="bars",
        ),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


def test_best_ignores_transparent_direct_fill_and_stroke_rgba() -> None:
    transparent = np.tile([1.0, 0.0, 0.0, 0.0], (2, 1))
    figure = xy.bar_chart(
        xy.bar(
            [0.85, 0.95],
            [0.20, 0.20],
            base=[0.80, 0.80],
            width=0.10,
            color=transparent,
            stroke=transparent,
            stroke_width=[2.0, 2.0],
            name="ghosts",
        ),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_matches_direct_stroke_alpha_to_each_row_stroke_width() -> None:
    transparent = np.tile([1.0, 0.0, 0.0, 0.0], (2, 1))
    stroke = np.tile([0.0, 1.0, 0.0, 1.0], (2, 1))
    figure = xy.bar_chart(
        xy.bar(
            [0.90, 0.10],
            [0.20, 0.20],
            base=[0.80, 0.10],
            width=0.10,
            color=transparent,
            stroke=stroke,
            stroke_width=[0.0, 2.0],
            name="bars",
        ),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    # The only stroked row is in the lower-left. The zero-width upper-right row
    # must not borrow that row's visible stroke paint.
    assert _loc(figure) == "upper right"


def test_best_ignores_transparent_categorical_palette_rows() -> None:
    figure = xy.scatter_chart(
        xy.scatter(
            [0.95, 0.96, 0.97, 0.50],
            [0.95, 0.96, 0.97, 0.50],
            color=["ghost", "ghost", "ghost", "solid"],
            size=20,
            name="points",
        ),
        xy.theme(palette={"ghost": "transparent", "solid": "red"}),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


@pytest.mark.parametrize("kind", ["area", "bar"])
def test_best_uses_gradient_stop_alpha_instead_of_base_color(kind: str) -> None:
    common = (
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    )
    if kind == "area":
        visible = xy.area(
            [0.85, 0.99],
            [0.90, 0.99],
            base=[0.80, 0.80],
            color="transparent",
            fill="linear-gradient(red, blue)",
            line_opacity=0,
            name="area",
        )
        ghost = xy.area(
            [0.85, 0.99],
            [0.90, 0.99],
            base=[0.80, 0.80],
            color="red",
            fill="linear-gradient(transparent, transparent)",
            line_opacity=0,
            name="area",
        )
    else:
        visible = xy.bar(
            [0.90],
            [0.20],
            base=[0.80],
            width=0.20,
            color="transparent",
            fill="linear-gradient(red, blue)",
            name="bar",
        )
        ghost = xy.bar(
            [0.90],
            [0.20],
            base=[0.80],
            width=0.20,
            color="red",
            fill="linear-gradient(transparent, transparent)",
            name="bar",
        )
    assert _loc(xy.chart(visible, *common).figure()) == "upper left"
    assert _loc(xy.chart(ghost, *common).figure()) == "upper right"


def test_best_scores_an_area_perimeter_baseline_and_sides() -> None:
    def placement(stroke_perimeter: bool) -> str:
        figure = xy.area_chart(
            xy.area(
                [0.85, 0.99],
                [0.10, 0.10],
                base=[0.95, 0.95],
                color="transparent",
                line_color="red",
                line_width=3,
                line_opacity=1,
                stroke_perimeter=stroke_perimeter,
                name="area",
            ),
            xy.x_axis(domain=(0.0, 1.0)),
            xy.y_axis(domain=(0.0, 1.0)),
            xy.legend(loc="best"),
        ).figure()
        return _loc(figure)

    assert placement(False) == "upper right"
    assert placement(True) == "upper left"


def test_best_ignores_zero_size_scatter_without_a_stroke() -> None:
    figure = xy.scatter_chart(
        xy.scatter([0.97], [0.97], size=0, name="zero"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_scores_the_m4_geometry_that_is_actually_emitted() -> None:
    # This isolated extremum falls between the legacy scorer's independent
    # 1024-point sample, but M4 deliberately preserves it for rendering.
    count = 100_000
    x = np.linspace(0.0, 1.0, count)
    y = np.zeros(count)
    y[95_000] = 1.0
    figure = xy.line_chart(
        xy.line(x, y, name="An important decimator-preserved spike"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    spec, blob = figure.build_payload()
    trace = spec["traces"][0]
    assert trace["tier"] == "decimated"
    emitted_y = _legendfit._rendered_column(spec, blob, trace["y"], None)
    assert emitted_y is not None and float(np.max(emitted_y)) == pytest.approx(1.0)
    assert spec["legend"]["loc"] == "upper left"


def test_best_scores_a_log_density_grid_in_display_space() -> None:
    # The grid is bounded (512x384) even though the source is large. Its wire
    # ranges remain raw, so this also catches interpolation in data rather than
    # log-display coordinates.
    count = 220_000
    values = np.geomspace(1_500.0, 10_000.0, count)
    figure = xy.scatter_chart(
        xy.scatter(values, values, density=True, name="density"),
        xy.x_axis(type_="log", domain=(1.0, 10_000.0)),
        xy.y_axis(type_="log", domain=(1.0, 10_000.0)),
        xy.legend(loc="best"),
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["traces"][0]["tier"] == "density"
    assert spec["legend"]["loc"] == "upper left"


def test_best_ignores_density_cells_with_zero_mean_alpha() -> None:
    count = 210_000
    x = np.linspace(0.85, 0.99, count)
    rgba = np.zeros((count, 4), dtype=np.float64)
    rgba[:, 0] = 1.0
    figure = xy.scatter_chart(
        xy.scatter(x, x, color=rgba, density=True, name="ghost"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["traces"][0]["tier"] == "density"
    assert spec["legend"]["loc"] == "upper right"


def test_best_counts_important_annotations() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [0.05, 0.05], name="line"),
        xy.text(0.95, 0.95, "important"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


@pytest.mark.parametrize(
    "annotation",
    [
        xy.vline(0.95, style={"span_start": 0.0, "span_end": 0.2}),
        xy.x_band(0.90, 0.99, style={"span_start": 0.0, "span_end": 0.2}),
    ],
    ids=["rule", "band"],
)
def test_best_respects_annotation_fractional_spans(annotation) -> None:
    figure = xy.chart(
        xy.line([0.10, 0.20], [0.10, 0.20], opacity=0, name="hidden"),
        annotation,
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_best_scores_a_visible_annotation_label_when_its_shape_is_transparent() -> None:
    figure = xy.chart(
        xy.line([0.10, 0.20], [0.10, 0.20], opacity=0, name="hidden"),
        xy.vline(0.95, text="visible label", opacity=0),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


@pytest.mark.parametrize(
    "space,x,y",
    [
        ("axes_fraction", 0.95, 0.95),
        ("xaxis_transform", 95.0, 0.95),
        ("yaxis_transform", 0.95, 95.0),
        ("figure_fraction", 0.90, 0.90),
    ],
)
def test_best_scores_annotation_coordinate_spaces(space: str, x: float, y: float) -> None:
    figure = xy.chart(
        xy.line([0.0, 100.0], [0.0, 0.0], opacity=0, name="hidden"),
        xy.text(x, y, "important", dx=0, dy=0, style={"coordinate_space": space}),
        xy.x_axis(domain=(0.0, 100.0)),
        xy.y_axis(domain=(0.0, 100.0)),
        xy.legend(loc="best"),
        width=640,
        height=420,
    ).figure()
    assert _loc(figure) == "upper left"


def test_figure_fraction_fallback_stays_in_plot_coordinates(monkeypatch) -> None:
    from xy import _svg

    def browser_only_layout(*_args, **_kwargs):
        raise ValueError("layout requires the browser")

    monkeypatch.setattr(_svg, "layout", browser_only_layout)
    scores = {"probe": 0.0}
    candidates = (("probe", 0.0, 0.05, 0.0, 0.05),)
    annotations = (
        {
            "kind": "text",
            "x": 0.10,
            "y": 0.10,
            "text": "i",
            "style": {"coordinate_space": "figure_fraction", "color": "black"},
        },
    )
    axis = ((0.0, 1.0), False, None, 1.0)

    # Figure (0.10, 0.10) maps inside this box in the standard fallback
    # 640x480 frame's 564x428 plot. Returning the raw pair as axes fractions
    # misses it entirely.
    assert _legendfit._score_annotations(
        scores,
        candidates,
        annotations,
        axis,
        axis,
        (564.0, 428.0),
        {"width": 640, "height": 480},
    )
    assert scores["probe"] == 1.0


@pytest.mark.parametrize("opacity", ["var(--ann-opacity)", "calc(1 - .2)", "inherit"])
def test_unresolved_css_annotation_opacity_is_conservatively_visible(opacity: str) -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [0.05, 0.05], name="line"),
        xy.text(0.95, 0.95, "important", style={"opacity": opacity}),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper left"


def test_best_respects_a_start_anchored_annotation_label_box() -> None:
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [0.05, 0.05], name="line"),
        xy.text(0.662, 0.956, "x" * 30, anchor="start", dx=0, dy=0),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=640,
        height=420,
    ).figure()
    assert _loc(figure) == "upper left"


@pytest.mark.parametrize(
    "annotation",
    [
        xy.vline(0.95, color="transparent"),
        xy.x_band(0.85, 1.0, color="transparent"),
        xy.text(0.95, 0.95, "ghost", style={"color": "transparent"}),
    ],
    ids=["rule", "band", "text"],
)
def test_best_ignores_known_transparent_annotations(annotation) -> None:
    figure = xy.chart(
        xy.line([0.10, 0.20], [0.10, 0.20], name="line"),
        annotation,
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "upper right"


def test_sparse_finite_points_survive_the_stride() -> None:
    # A mostly-NaN series whose finite points would fall between strides must
    # still be scored rather than dropped from placement.
    y = np.full(20_000, np.nan)
    x = np.linspace(0.0, 1.0, 20_000)
    y[3] = 0.99
    y[7] = 0.98
    projected = _legendfit.normalize(x, y, (0.0, 1.0), (0.0, 1.0))
    assert projected is not None


def test_the_core_and_the_pyplot_shim_agree() -> None:
    # Two copies of this scoring exist (see xy/_legendfit.py's module docstring).
    # Pin them to the same answer so folding one onto the other stays safe.
    from xy import pyplot as plt

    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [0.0, 1.0, 2.0, 3.0]

    figure = plt.figure()
    axes = figure.add_subplot(1, 1, 1)
    axes.plot(xs, ys, label="a")
    axes.legend(loc="best")
    shim_loc = axes._best_legend_loc()

    core = xy.line_chart(xy.line(xs, ys, name="a"), xy.legend(loc="best")).figure()
    assert _loc(core) == shim_loc


# --- display-space scoring ----------------------------------------------------


#: A scatter whose display-space and value-space occupancy disagree. Four marks
#: sit in the top two decades and one near the origin: on screen (log) they
#: crowd the right edge and free the lower-left, while raw subtraction spreads
#: them and frees the upper-right instead. A fixture on the diagonal cannot
#: tell the two apart — both spaces see a diagonal — so it would pass with the
#: transform removed.
_LOG_X = [7000.0, 7500.0, 1.1, 3000.0, 8000.0]
_LOG_Y = [7000.0, 4.0, 8000.0, 3600.0, 2000.0]


def test_best_scores_a_log_axis_in_display_space() -> None:
    figure = xy.scatter_chart(
        xy.scatter(x=_LOG_X, y=_LOG_Y, name="a"),
        xy.x_axis(type_="log", domain=(1.0, 10000.0)),
        xy.y_axis(type_="log", domain=(1.0, 10000.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) == "lower left"


def test_the_log_fixture_would_fail_without_the_transform() -> None:
    # Guards the test above: it is only meaningful if value-space scoring gives
    # a different answer on this fixture.
    domain = (1.0, 10000.0)
    raw = _legendfit.normalize(np.array(_LOG_X), np.array(_LOG_Y), domain, domain)
    logged = _legendfit.normalize(
        np.array(_LOG_X), np.array(_LOG_Y), domain, domain, x_scale="log", y_scale="log"
    )
    assert _legendfit.best_loc([raw], ["a"]) == "upper right"
    assert _legendfit.best_loc([logged], ["a"]) == "lower left"


def test_log_normalization_spreads_decades_evenly() -> None:
    decades = np.array([1.0, 10.0, 100.0, 1000.0, 10000.0])
    xn, _yn = _legendfit.normalize(
        decades, decades, (1.0, 10000.0), (1.0, 10000.0), x_scale="log", y_scale="log"
    )
    assert np.allclose(xn, [0.0, 0.25, 0.5, 0.75, 1.0])


def test_symlog_normalization_uses_the_axis_constant() -> None:
    # These values are interior and asymmetric on purpose. The obvious fixture,
    # `[-100, 0, 100]` on a symmetric domain, is invariant to the constant
    # (symlog is odd), so it cannot detect whether the constant is read at all.
    values = np.array([0.0, 1.0, 10.0, 100.0])

    def positions(constant: float) -> np.ndarray:
        xn, _yn = _legendfit.normalize(
            values,
            values,
            (0.0, 100.0),
            (0.0, 100.0),
            x_scale="symlog",
            y_scale="symlog",
            x_constant=constant,
            y_constant=constant,
        )
        return xn

    assert np.allclose(positions(1.0), [0.0, 0.15, 0.52, 1.0], atol=0.01)
    assert np.allclose(positions(25.0), [0.0, 0.024, 0.209, 1.0], atol=0.01)
    assert not np.allclose(positions(1.0), positions(25.0))


def test_off_plot_marks_are_dropped_not_clamped() -> None:
    # Every renderer clips them; folding them onto an edge would guard a corner
    # the viewer sees as empty.
    values = np.array([0.0, 0.5, 1.0, 50.0, 99.0])
    xn, _yn = _legendfit.normalize(values, values, (0.0, 1.0), (0.0, 1.0))
    assert np.allclose(xn, [0.0, 0.5, 1.0])


def test_a_series_entirely_off_plot_is_not_scored() -> None:
    values = np.array([50.0, 60.0])
    assert _legendfit.normalize(values, values, (0.0, 1.0), (0.0, 1.0)) is None


def test_a_fixed_domain_frees_the_corner_the_clipped_marks_left() -> None:
    # The tail sits above the domain, so it is clipped away and upper-right is
    # empty on screen even though the raw data reaches it.
    xs = [0.0, 1.0, 2.0, 3.0]
    figure = xy.line_chart(
        xy.line(xs, [0.0, 0.1, 0.2, 99.0], name="a"),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
    ).figure()
    assert _loc(figure) in {"upper right", "upper left", "upper center"}
