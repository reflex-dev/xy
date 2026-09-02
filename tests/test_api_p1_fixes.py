"""Public-API P1 fixes: silent drops, leaked exception types, and factory
shortcuts that the composed `*_chart` builders promised but did not honor.

Each block pins one previously reproduced defect against the public surface
(`xy.*` only), so a regression shows up as the user would have seen it.
"""

from __future__ import annotations

import re
import warnings

import numpy as np
import pyarrow as pa
import pytest

import xy
from xy import channels
from xy.components import _MARK_APPLIERS

# -- 1. log axis drops non-positive rows loudly ------------------------------


def _log_payload(**axis_kwargs):
    chart = xy.scatter_chart(
        xy.scatter(x=range(5), y=[-1, 0, 1, 2, 3]),
        xy.y_axis(type_="log", **axis_kwargs),
    )
    return chart.figure().build_payload()[0]


def test_log_axis_default_drop_warns_with_axis_count_and_remedy() -> None:
    with pytest.warns(RuntimeWarning, match=r"y .*2 of 5 .*nonpositive=") as record:
        spec = _log_payload()
    assert spec["traces"][0]["n_marks"] == 3
    message = str(record[0].message)
    assert "symlog" in message


@pytest.mark.parametrize("mode", ["clip", "mask"])
def test_log_axis_explicit_nonpositive_policy_is_silent(mode: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        spec = _log_payload(nonpositive=mode)
    assert spec["traces"][0]["n_marks"] == 3


def test_log_axis_all_positive_data_is_silent() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        chart = xy.scatter_chart(
            xy.scatter(x=range(3), y=[1, 2, 3]),
            xy.y_axis(type_="log"),
        )
        chart.figure().build_payload()


def test_log_axis_area_counts_rows_not_columns() -> None:
    """y and base both fail on the same row: one dropped row, not two."""
    chart = xy.area_chart(
        xy.area(x=[0, 1, 2], y=[0, 2, 3], base=[-1, 1, 1]),
        xy.y_axis(type_="log"),
    )
    with pytest.warns(RuntimeWarning, match=r"1 of 3"):
        chart.figure().build_payload()


# -- 2. non-finite continuous color/size rows are not drawn -----------------


def _shipped_color_u8(color: list[float]) -> tuple[int, np.ndarray]:
    fig = xy.scatter_chart(xy.scatter(x=[1, 2, 3, 4, 5], y=[1, 2, 3, 4, 5], color=color)).figure()
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    return trace["n_marks"], fig.traces[0].shipped_sel


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_color_row_is_not_drawn(bad: float) -> None:
    n_marks, sel = _shipped_color_u8([1.0, bad, 3.0, 4.0, 5.0])
    assert n_marks == 4
    np.testing.assert_array_equal(sel, [0, 2, 3, 4])


def test_nonfinite_size_row_is_not_drawn() -> None:
    fig = xy.scatter_chart(
        xy.scatter(x=[1, 2, 3], y=[1, 2, 3], size=[4.0, np.nan, 8.0]),
    ).figure()
    spec, _blob = fig.build_payload()
    assert spec["traces"][0]["n_marks"] == 2
    np.testing.assert_array_equal(fig.traces[0].shipped_sel, [0, 2])


def test_nonfinite_color_and_xy_exclusions_compose() -> None:
    fig = xy.scatter_chart(
        xy.scatter(x=[1, np.nan, 3, 4], y=[1, 2, 3, 4], color=[1.0, 2.0, np.inf, 4.0]),
    ).figure()
    spec, _blob = fig.build_payload()
    assert spec["traces"][0]["n_marks"] == 2
    np.testing.assert_array_equal(fig.traces[0].shipped_sel, [0, 3])


def _svg_mark_count(svg: str) -> int:
    return len(re.findall(r"<circle\b", svg))


def test_static_exports_see_the_same_rows_as_the_wire() -> None:
    """The exporters read the shipped buffers, so a colour-less point cannot
    reappear in SVG wearing the domain-floor colour."""
    chart = xy.scatter_chart(
        xy.scatter(x=[1, 2, 3], y=[1, 2, 3], color=[1.0, np.inf, 3.0]),
        width=200,
        height=120,
    )
    svg = chart.to_svg()
    assert _svg_mark_count(svg) == 2


def test_finite_channels_do_not_allocate_a_selection() -> None:
    fig = xy.scatter_chart(
        xy.scatter(x=[1, 2, 3], y=[1, 2, 3], color=[1.0, 2.0, 3.0], size=[1.0, 2.0, 3.0]),
    ).figure()
    fig.build_payload()
    assert fig.traces[0].shipped_sel is None


def test_quantizer_contract_documented_not_silent() -> None:
    # The quantizer itself still floors non-finite input: the contract is that
    # the emitters exclude such rows before shipping (design dossier §19).
    out = channels.quantize_unit_u8(np.array([1.0, np.nan, 3.0]), (1.0, 3.0))
    np.testing.assert_array_equal(out, [0, 0, 255])


# -- 3. sankey_chart accepts its own mark -------------------------------------

LINKS = [("a", "b", 1.0), ("a", "c", 2.0), ("b", "d", 1.0), ("c", "d", 2.0)]


def _spec(chart: xy.Chart) -> dict:
    spec, _blob = chart.figure().build_payload()
    return spec


def test_sankey_chart_accepts_links_or_a_sankey_mark() -> None:
    by_links = _spec(xy.sankey_chart(LINKS, width=400, height=300))
    by_mark = _spec(xy.sankey_chart(xy.sankey(LINKS), width=400, height=300))
    assert by_links == by_mark


def test_sankey_chart_mark_form_keeps_mark_props() -> None:
    spec = _spec(xy.sankey_chart(xy.sankey(LINKS, node_width=0.1, labels=False)))
    control = _spec(xy.sankey_chart(LINKS, node_width=0.1, labels=False))
    assert spec == control


def test_sankey_chart_refuses_mark_kwargs_beside_an_explicit_mark() -> None:
    with pytest.raises(ValueError, match=r"explicit xy\.sankey"):
        xy.sankey_chart(xy.sankey(LINKS), node_width=0.1)


def test_sankey_chart_accepts_chrome_children_first() -> None:
    chart = xy.sankey_chart(xy.legend(show=False), xy.sankey(LINKS))
    spec = _spec(chart)
    assert spec["traces"] == _spec(xy.sankey_chart(LINKS, xy.legend(show=False)))["traces"]
    assert spec["traces"] and all(t["kind"] == "ribbon" for t in spec["traces"])


def test_sankey_chart_chrome_only_is_mark_free() -> None:
    assert xy.sankey_chart(xy.legend(show=False)).figure().traces == []


def test_sankey_chart_refuses_mark_kwargs_without_links() -> None:
    with pytest.raises(ValueError, match="without links"):
        xy.sankey_chart(xy.legend(show=False), node_width=0.1)


# -- 4. a hand-built xy.Mark never leaks KeyError ------------------------------

_MINIMAL_MARK_DATA = {
    "heatmap": {"x": [0, 1], "y": [0, 1], "z": [[1, 2], [3, 4]]},
}


@pytest.mark.parametrize("kind", sorted(_MARK_APPLIERS))
def test_bare_mark_builds_or_raises_value_error(kind: str) -> None:
    extra = dict(_MINIMAL_MARK_DATA.get(kind, {}))
    x = extra.pop("x", [1.0, 2.0, 3.0])
    y = extra.pop("y", [1.0, 2.0, 3.0])
    mark = xy.Mark(kind=kind, x=x, y=y, props=extra)
    try:
        xy.chart(mark).figure()
    except ValueError as exc:
        assert kind in str(exc) or "links" in str(exc) or "requires" in str(exc) or str(exc)
    except KeyError as exc:  # pragma: no cover - the defect under test
        pytest.fail(f"{kind}: KeyError leaked for missing prop {exc}")


def test_bare_scatter_and_line_marks_match_their_factories() -> None:
    bare = xy.chart(xy.Mark(kind="scatter", x=[1, 2], y=[1, 2])).figure()
    made = xy.chart(xy.scatter(x=[1, 2], y=[1, 2])).figure()
    assert bare.build_payload()[0]["traces"] == made.build_payload()[0]["traces"]
    bare_line = xy.chart(xy.Mark(kind="line", x=[1, 2], y=[1, 2])).figure()
    made_line = xy.chart(xy.line(x=[1, 2], y=[1, 2])).figure()
    assert bare_line.build_payload()[0]["traces"] == made_line.build_payload()[0]["traces"]


def test_bare_mark_explicit_props_win_over_factory_defaults() -> None:
    fig = xy.chart(xy.Mark(kind="scatter", x=[1, 2], y=[1, 2], props={"size": 9.0})).figure()
    assert fig.traces[0].size_ch.constant == 9.0


# -- 5. bare pyarrow string arrays are categorical axes ------------------------


def _x_categories(values) -> list[str]:
    fig = xy.scatter_chart(xy.scatter(x=values, y=[1, 2, 3])).figure()
    return list(fig._axis_categories["x"])


def test_pyarrow_string_array_is_a_categorical_axis() -> None:
    assert _x_categories(pa.array(["a", "b", "c"])) == ["a", "b", "c"]


def test_pyarrow_chunked_string_array_is_a_categorical_axis() -> None:
    assert _x_categories(pa.chunked_array([["a", "b"], ["c"]])) == ["a", "b", "c"]


def test_pyarrow_dictionary_array_is_a_categorical_axis() -> None:
    assert _x_categories(pa.array(["a", "b", "a"]).dictionary_encode()) == ["a", "b"]


def test_pyarrow_string_array_with_nulls_matches_pandas() -> None:
    pd = pytest.importorskip("pandas")
    arrow = _x_categories(pa.array(["a", None, "c"]))
    pandas = _x_categories(pd.Series(["a", None, "c"], dtype="string[pyarrow]"))
    assert arrow == pandas


def test_pyarrow_string_facet_keys() -> None:
    """`by=` as a per-row pyarrow string array factorizes like a list would."""
    data = {"x": [1, 2, 3, 4], "y": [1, 2, 3, 4]}
    by = pa.array(["a", "a", "b", None])
    grid = xy.facet_chart(xy.scatter(x="x", y="y"), by=by, data=data).figure()
    assert list(grid.labels) == ["a", "b", "(missing)"]


# -- 6. a missing facet column is a ValueError like every other column ---------


def test_missing_facet_column_is_a_value_error() -> None:
    data = {"x": [1, 2], "y": [1, 2]}
    with pytest.raises(ValueError, match="facet column 'zz' not found in data"):
        xy.facet_chart(xy.scatter(x="x", y="y"), by="zz", data=data).figure()


def test_missing_facet_column_in_a_frame_is_a_value_error() -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"x": [1, 2], "y": [1, 2]})
    with pytest.raises(ValueError, match="facet column 'zz' not found in data"):
        xy.facet_chart(xy.scatter(x="x", y="y"), by="zz", data=df).figure()
