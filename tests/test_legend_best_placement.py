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
        ("UPPER RIGHT", "upper right"),
        ("  lower   left ", "lower left"),
        ("right", "center right"),  # Matplotlib's code 5 aliases center right
        ("left", "center left"),
        ("right upper", "upper right"),  # Matplotlib takes either word order
        # `top`/`bottom` name the same edge as `upper`/`lower`. CSS, Plotly and
        # XY's own docs use them, and `top left` used to render CENTER-left.
        ("top left", "upper left"),
        ("top-left", "upper left"),
        ("bottom_right", "lower right"),
        ("TOP RIGHT", "upper right"),
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


def test_the_docs_spelling_lands_where_it_reads() -> None:
    # docs/content/components/facets-and-layers.md uses loc="top left"; before
    # the vocabulary closed, the substring match found "left" but neither
    # "upper" nor "lower", so the page rendered a CENTER-left legend.
    top_left = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="a"), xy.legend(loc="top left")
    ).to_svg()
    upper_left = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="a"), xy.legend(loc="upper left")
    ).to_svg()
    assert top_left == upper_left


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
