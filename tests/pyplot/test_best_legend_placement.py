"""``legend(loc="best")`` must choose the corner Matplotlib chooses.

Every ``matplotlib`` location in this file is a *measured* value, not a guess:
each was read out of ``matplotlib.legend.Legend._find_best_position`` under
matplotlib 3.11.1 for the same figure, together with its per-candidate badness.
The comments quote those badness numbers so a future change to the scoring model
can be judged against Matplotlib rather than against this file.

Assertions are on the resolved ``loc`` that reaches the wire, never on pixels.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy
import xy.pyplot as plt
from xy._svg import _legend_layout


def resolved_loc(ax) -> str:
    """The legend loc the built figure actually ships, at the figure's own size."""
    spec, _ = ax.figure._charts()[0].figure().build_payload()
    return spec["legend"]["loc"]


# --------------------------------------------------------------------------
# Parity table. `matplotlib` is what matplotlib 3.11.1 picks; `expected` is what
# the shim picks. They are equal except where `note` records a measured reason.
# --------------------------------------------------------------------------


def _births_seasonal_curve():
    """The reported defect, reduced to its geometry.

    `examples/pdsh/pdsh_04_09_text_and_annotation.ipynb` cell 23: one wide,
    366-point series labelled `births`, a late-summer peak reaching ~0.87 of the
    view, and a low winter tail that leaves the top-right corner clear.
    Matplotlib picks upper right at badness 0.

    The old linear estimate sized this legend at 0.30 x 0.17 of the axes
    (`0.12 + 0.03 * len("births")` by `0.10 + 0.07 * 1`) against a real
    0.097 x 0.083. The inflated upper-right candidate reached back to x=0.70 and
    down to y=0.83, swallowing the summer peak, while the inflated upper-left
    candidate stopped at x=0.30 and stayed empty -- so upper left won.
    """
    t = np.linspace(0.0, 1.0, 366)
    y = 3900 + 1300 * np.exp(-(((t - 0.68) / 0.16) ** 2))
    y += 40 * np.sin(2 * np.pi * t * 7)
    _, ax = plt.subplots(figsize=(12, 4))
    ax.plot(t, y, label="births")
    ax.set_ylim(3600, 5400)
    ax.legend(loc="best")
    return ax


def _data_in_upper_right():
    """A rising diagonal fills the upper right. Matplotlib: upper left (0);
    upper right scores 11."""
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 200)
    ax.plot(x, x, label="rising")
    ax.legend(loc="best")
    return ax


def _data_in_upper_left():
    """A falling diagonal fills the upper left. Matplotlib: upper right (0)."""
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 200)
    ax.plot(x, 10 - x, label="falling")
    ax.legend(loc="best")
    return ax


def _few_entries_short_labels():
    """One entry, one-character label -> the smallest possible box.
    Matplotlib: upper right, badness 0."""
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 100)
    ax.plot(x, np.sin(x), label="a")
    ax.legend(loc="best")
    return ax


def _full_amplitude_oscillation():
    """A sine filling the view vertically. Matplotlib: lower left (0), after
    scoring upper right 2 and upper left 45 -- the two vertices near the last
    peak are what disqualify upper right."""
    _, ax = plt.subplots()
    x = np.linspace(0, 20, 1000)
    ax.plot(x, np.sin(x), label="sin")
    ax.legend(loc="best")
    return ax


def _center_band_oscillation():
    """Four phase-shifted sines: every corner busy, the center band sparse.
    Matplotlib: center left 20, against center right 36."""
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 500)
    ax.plot(x, np.sin(x[:, None] + np.pi * np.arange(0, 2, 0.5)))
    ax.legend(["a", "b"])
    return ax


def _diagonal_band_long_labels():
    """Two near-identical diagonals with a long label -> a wide two-row box.
    Matplotlib: upper left (0); upper right scores 57."""
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 300)
    ax.plot(x, x, label="identity")
    ax.plot(x, x + 0.5, label="identity shifted up by a half")
    ax.legend(loc="best")
    return ax


def _data_fills_axes():
    """A uniform cloud over the whole view: no candidate is empty.

    Matplotlib ties upper left and lower right at 2 contained vertices out of
    400 and breaks the tie by location code, giving upper left. The shim's box
    is ~12% narrower and ~14% shorter *as a fraction of its plot rect* (the box
    is pixel-accurate; xy's plot rect is larger than Matplotlib's axes rect),
    which separates the tie and leaves lower right strictly emptier.
    """
    _, ax = plt.subplots()
    rng = np.random.default_rng(0)
    ax.plot(rng.uniform(0, 1, 400), rng.uniform(0, 1, 400), "o", label="cloud")
    ax.legend(loc="best")
    return ax


def _scatter_cluster_upper_right():
    """A tight cluster near the upper-right corner.

    Matplotlib scores upper right 1 -- a single one of 200 offsets sits in the
    corner box -- and so falls through to upper left. That lone offset lies
    between the shim's box edge and Matplotlib's, for the same plot-rect reason
    as `_data_fills_axes`, so the shim sees upper right as empty.
    """
    _, ax = plt.subplots()
    rng = np.random.default_rng(3)
    ax.scatter(rng.normal(8, 0.4, 200), rng.normal(8, 0.4, 200), label="cluster")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.legend(loc="best")
    return ax


def _many_entries_long_labels():
    """Six long labels -> a box covering ~71% x ~31% of the plot.

    No candidate is close to empty. Matplotlib ties lower left and lower center
    at 147 and takes lower left; the shim's smaller box makes the dead-center
    box the emptiest instead. Same plot-rect gap, amplified by a box this large.
    """
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 100)
    for index in range(6):
        ax.plot(
            x,
            0.4 * np.sin(x) + index * 0.05,
            label=f"a very long descriptive series label number {index}",
        )
    ax.legend(loc="best")
    return ax


PARITY_CASES = [
    # (id, builder, matplotlib 3.11.1 loc, shim loc)
    ("births_seasonal_curve", _births_seasonal_curve, "upper right", "upper right"),
    ("data_in_upper_right", _data_in_upper_right, "upper left", "upper left"),
    ("data_in_upper_left", _data_in_upper_left, "upper right", "upper right"),
    ("few_entries_short_labels", _few_entries_short_labels, "upper right", "upper right"),
    ("full_amplitude_oscillation", _full_amplitude_oscillation, "lower left", "lower left"),
    ("center_band_oscillation", _center_band_oscillation, "center left", "center left"),
    ("diagonal_band_long_labels", _diagonal_band_long_labels, "upper left", "upper left"),
    # Known divergences, each attributed in the builder's docstring.
    ("data_fills_axes", _data_fills_axes, "upper left", "lower right"),
    ("scatter_cluster_upper_right", _scatter_cluster_upper_right, "upper left", "upper right"),
    ("many_entries_long_labels", _many_entries_long_labels, "lower left", "center"),
]


@pytest.mark.parametrize(
    ("builder", "matplotlib_loc", "expected"),
    [case[1:] for case in PARITY_CASES],
    ids=[case[0] for case in PARITY_CASES],
)
def test_best_loc_matches_matplotlib_per_data_shape(builder, matplotlib_loc, expected):
    assert resolved_loc(builder()) == expected


def test_measured_parity_against_matplotlib():
    """Pin the measured parity rate, so a scoring change has to argue its case.

    7 of these 10 shapes now resolve to the corner Matplotlib picks, against 6
    of 10 before -- and *not* a superset. Three shapes were fixed
    (`births_seasonal_curve`, `full_amplitude_oscillation`,
    `center_band_oscillation`) and two regressed (`data_fills_axes`,
    `scatter_cluster_upper_right`): those two used to match by accident, because
    an oversized candidate box happened to disqualify the same corner
    Matplotlib rejects for a real reason.

    The exact counts are deliberate: this is a compatibility contract, so a
    scoring or legend-metric change should have to re-measure against
    Matplotlib rather than silently drift. (Checked against PR 248's `0308c98`
    DejaVu glyph advances, which land here once #254 absorbs them: the box gets
    narrower in pixels and *more* accurate, and this set stays 7/10.)
    """
    parity = {case[0]: resolved_loc(case[1]()) == case[2] for case in PARITY_CASES}
    assert sum(parity.values()) == 7
    assert {name for name, matched in parity.items() if not matched} == {
        "data_fills_axes",
        "scatter_cluster_upper_right",
        "many_entries_long_labels",
    }


def test_residual_divergence_is_attributable_to_the_plot_rect(monkeypatch):
    """Two of the three residuals are the plot-rect gap, not the scoring model.

    The legend box is pixel-accurate against Matplotlib (a one-row box measures
    25.4 px in both engines), but xy lays out a 564 x 428 plot box where
    Matplotlib's default axes rect is 496 x 369.6 -- so the *same* box is ~12%
    narrower and ~14% shorter as a fraction, and knife-edge candidates decided
    by one or two vertices fall the other way.

    Substituting Matplotlib's axes rect as the denominator lifts parity from
    7/10 to 9/10, which attributes the residual without papering over it. xy is
    deliberately *not* scored against a geometry it does not render: doing so
    would place legends by a rect the exporters never use, and would need
    undoing once the frame-geometry work converges the two.
    """
    monkeypatch.setattr(
        type(plt.subplots()[1]),
        "_plot_rect_px",
        lambda self, width, height, padding=None, x_side=None: (
            width * 0.775,
            height * 0.77,
        ),
    )
    parity = {case[0]: resolved_loc(case[1]()) == case[2] for case in PARITY_CASES}
    assert sum(parity.values()) == 9
    assert {name for name, matched in parity.items() if not matched} == {"data_fills_axes"}


# --------------------------------------------------------------------------
# The footprint is measured, not estimated
# --------------------------------------------------------------------------


def test_best_scores_the_measured_legend_box_not_a_linear_estimate():
    """The scored footprint is the box the exporters actually lay out."""
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 366)
    ax.plot(x, 0.05 * np.sin(x), label="average daily births")
    ax.set_ylim(-1, 1)
    ax.legend(loc="best")

    chart = ax._build_chart(1200, 400)
    spec, _ = chart.figure().build_payload()
    from xy._svg import layout

    _, _, _, plot = layout(spec)
    box = _legend_layout(
        [trace for trace in spec["traces"] if trace.get("name")], plot, spec["legend"]
    )
    # One row of one label: nowhere near the 0.12 + 0.03 * len(label) width and
    # 0.10 + 0.07 * rows height the old estimate produced (0.30 x 0.17).
    assert box["box_w"] / plot["w"] < 0.20
    assert box["box_h"] / plot["h"] < 0.12
    assert spec["legend"]["loc"] == "upper right"


def test_longer_labels_grow_the_scored_footprint():
    """A wider legend guards a wider region, so it can change the choice."""

    def build(label):
        _, ax = plt.subplots()
        x = np.linspace(0, 10, 200)
        # Data hugging the top-left leaves the right side clear, but only for a
        # box narrow enough to fit beside it.
        ax.plot(x, 10 - 3 * x, label=label)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.legend(loc="best")
        return ax

    narrow = _legend_footprint_width(build("a"))
    wide = _legend_footprint_width(build("an extremely long series label indeed"))
    assert wide > narrow * 2


def _legend_footprint_width(ax) -> float:
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    from xy._svg import layout

    _, _, _, plot = layout(spec)
    box = _legend_layout(
        [trace for trace in spec["traces"] if trace.get("name")], plot, spec["legend"]
    )
    return box["box_w"] / plot["w"]


def test_best_scores_the_displayed_view_not_the_raw_data_extent():
    """Autorange padding moves the corners; `best` must see the padded view.

    Data spanning exactly the data extent reaches y=1.0, but the rendered view
    is padded past it, so the top band is clear on screen. Scoring the raw
    extent instead reports the top band as occupied.
    """
    _, ax = plt.subplots()
    x = np.linspace(0, 10, 200)
    ax.plot(x, np.full_like(x, 1.0), label="flat top")
    ax.plot(x, np.linspace(0.0, 0.2, 200), label="rising floor")
    ax.legend(loc="best")
    figure = ax._build_chart(640, 480).figure()
    lo, hi = figure.y_range()
    assert hi > 1.0 and lo < 0.0  # the engine padded past the data
    # The flat line at y=1.0 sits *below* the padded top edge, so the upper
    # corners are still occupied by it and matplotlib's first empty candidate
    # is a lower one.
    assert resolved_loc(ax) in {"lower left", "lower right", "lower center"}


def test_borderaxespad_insets_every_candidate_box():
    """Matplotlib pads the container before anchoring, so the pad must reach
    scoring -- otherwise every candidate sits flush against the plot edge."""

    def pads(borderaxespad):
        _, ax = plt.subplots()
        x = np.linspace(0, 10, 400)
        ax.plot(x, x, label="rising")
        ax.legend(loc="best", borderaxespad=borderaxespad)
        *_, pad_x, pad_y = ax._legend_footprint(ax._legend_options, None, (564.0, 428.0))
        return pad_x, pad_y

    assert pads(0.0) == (0.0, 0.0)
    half_x, half_y = pads(0.5)
    assert half_x > 0.0 and half_y > 0.0
    # Linear in borderaxespad, and larger vertically because the plot box is
    # shorter than it is wide.
    quad_x, quad_y = pads(2.0)
    assert quad_x == pytest.approx(half_x * 4.0)
    assert quad_y == pytest.approx(half_y * 4.0)
    assert half_y > half_x
    # The pixel pad itself is Matplotlib's: borderaxespad * legend font px.
    assert half_x * 564.0 == pytest.approx(0.5 * 10.0 * 100.0 / 72.0)


def test_best_is_resolved_before_the_wire():
    """`"best"` is a shim concept; the wire only ever carries a real location."""
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    ax.legend(loc="best")
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["loc"] != "best"
    assert spec["legend"]["loc"] in xy._validate.LEGEND_LOCATIONS


def test_unlabeled_entries_do_not_crash_measurement():
    """A legend with no labelled entry still measures as one empty row."""
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.legend(loc="best")
    assert resolved_loc(ax) in xy._validate.LEGEND_LOCATIONS


# --------------------------------------------------------------------------
# The substring-match guard
# --------------------------------------------------------------------------


def test_legend_loc_rejects_unresolved_and_misspelled_locations():
    """Placement used to be substring-matched, so a string containing neither
    "left" nor "right" silently produced a *centered* legend. It is now an
    error at the call that introduces it."""
    for bogus in ("best", "uppper right", "top left", "", "middle"):
        with pytest.raises(ValueError, match="legend loc must be one of"):
            xy.legend(loc=bogus)


def test_legend_layout_rejects_an_unresolved_loc_reaching_the_exporter():
    """Second line of defence: the shared static geometry refuses to guess."""
    items = [{"name": "a"}]
    plot = {"x": 0.0, "y": 0.0, "w": 400.0, "h": 300.0}
    with pytest.raises(ValueError, match="legend loc must be one of"):
        _legend_layout(items, plot, {"loc": "best"})
    with pytest.raises(ValueError, match="legend loc must be one of"):
        _legend_layout(items, plot, {"loc": "north"})


def test_every_valid_loc_places_the_box_where_it_used_to():
    """The guard is a pure guard: valid names keep their exact geometry.

    Left/right/centre and upper/lower/centre are asserted against the plot box
    directly, which is what the replaced per-branch arithmetic computed.
    """
    items = [{"name": "abc"}]
    plot = {"x": 40.0, "y": 20.0, "w": 400.0, "h": 300.0}
    inset = 6.0
    for loc, (hx, vy) in xy._validate.LEGEND_LOCATIONS.items():
        box = _legend_layout(items, plot, {"loc": loc})
        want_x = plot["x"] + inset + hx * (plot["w"] - 2 * inset - box["box_w"])
        want_y = plot["y"] + inset + (1.0 - vy) * (plot["h"] - 2 * inset - box["box_h"])
        assert box["x"] == pytest.approx(want_x), loc
        assert box["y"] == pytest.approx(want_y), loc


def test_right_and_center_right_are_the_same_anchor():
    """Matplotlib resolves codes 5 and 7 to the same offsetbox corner."""
    assert xy._validate.LEGEND_LOCATIONS["right"] == (xy._validate.LEGEND_LOCATIONS["center right"])
    items = [{"name": "abc"}]
    plot = {"x": 0.0, "y": 0.0, "w": 400.0, "h": 300.0}
    a = _legend_layout(items, plot, {"loc": "right"})
    b = _legend_layout(items, plot, {"loc": "center right"})
    assert (a["x"], a["y"]) == (b["x"], b["y"])


def test_best_candidate_order_is_matplotlib_code_order():
    """The tie-break contract: Matplotlib prefers the lower location code."""
    from xy.pyplot._axes import _BEST_LOC_ORDER

    # Codes 1..10 with code 5 ("right") folded onto its identical code-7 anchor.
    assert _BEST_LOC_ORDER == (
        "upper right",
        "upper left",
        "lower left",
        "lower right",
        "center right",
        "center left",
        "lower center",
        "upper center",
        "center",
    )
    assert set(_BEST_LOC_ORDER) <= set(xy._validate.LEGEND_LOCATIONS)


def test_ties_keep_the_earliest_candidate():
    """An empty plot leaves every candidate at zero -> code 1 wins."""
    _, ax = plt.subplots()
    ax.plot([], [], label="nothing")
    ax.legend(loc="best")
    assert resolved_loc(ax) == "upper right"
