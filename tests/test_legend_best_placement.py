"""`loc="best"` and the closed legend-placement vocabulary.

`best` is Matplotlib's default `loc`, so it is the spelling users reach for
first. It is resolved at payload-build time, which is what keeps the browser
client and the two static writers from each making their own guess.
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


def test_best_resolves_before_the_wire_so_no_renderer_sees_it() -> None:
    # The whole point of resolving at build time: three renderers, one decision.
    figure = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="a"), xy.legend(loc="best")
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["legend"]["loc"] != "best"
    assert spec["legend"]["loc"] in _legendfit._CANDIDATE_ORDER


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
_LOG_X = [5000.0, 7500.0, 1.0, 3000.0, 8000.0]
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
