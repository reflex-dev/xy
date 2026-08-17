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
    ("data_fills_axes", _data_fills_axes, "upper left", "upper left"),
    ("scatter_cluster_upper_right", _scatter_cluster_upper_right, "upper left", "upper left"),
    ("many_entries_long_labels", _many_entries_long_labels, "lower left", "lower left"),
]


@pytest.mark.parametrize(
    ("builder", "matplotlib_loc", "expected"),
    [case[1:] for case in PARITY_CASES],
    ids=[case[0] for case in PARITY_CASES],
)
def test_best_loc_matches_matplotlib_per_data_shape(builder, matplotlib_loc, expected):
    assert resolved_loc(builder()) == expected


def test_measured_parity_against_matplotlib():
    """Pin the combined measured parity rate against Matplotlib 3.11."""
    parity = {case[0]: resolved_loc(case[1]()) == case[2] for case in PARITY_CASES}
    assert sum(parity.values()) == 10


def test_residual_divergence_is_attributable_to_the_plot_rect(monkeypatch):
    """The legacy Matplotlib plot-rect probe also remains 10/10."""
    monkeypatch.setattr(
        type(plt.subplots()[1]),
        "_displayed_plot_size",
        staticmethod(
            lambda figure, _ranges: (
                figure.width * 0.775,
                figure.height * 0.77,
            )
        ),
    )
    parity = {case[0]: resolved_loc(case[1]()) == case[2] for case in PARITY_CASES}
    assert sum(parity.values()) == 10


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
    assert box["box_w"] / plot["w"] < 0.21
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


def test_segment_crossing_disqualifies_a_box_without_contained_vertices():
    """Matplotlib adds one badness point when a path crosses a candidate.

    Both vertices sit outside the upper-right legend, but their segment crosses
    it. A vertex-only scorer incorrectly calls that corner empty.
    """
    _, ax = plt.subplots()
    ax.plot([0.7, 1.1], [0.7, 1.1], label="x")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="best")
    assert resolved_loc(ax) == "upper left"


def test_bar_rectangle_overlap_is_not_reduced_to_its_anchor():
    """A legend entirely inside a wide bar overlaps its Rectangle bbox."""
    _, ax = plt.subplots()
    ax.bar([0.9], [1.0], width=0.4, label="bar")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="best")
    assert resolved_loc(ax) == "upper left"


def test_sparse_scatter_offset_outside_path_budget_disqualifies_the_corner():
    """Scatter keeps #274's offset budget because it has no segment fallback.

    Index 2 is absent from the 512-point path sample of these 1,000 offsets.
    The other 999 points occupy the lower-right corner; this lone upper-right
    offset therefore has to be observed for Matplotlib's upper-left choice.
    """
    x = np.full(1000, 0.95)
    y = np.full(1000, 0.05)
    y[2] = 0.95

    _, ax = plt.subplots()
    ax.scatter(x, y, label="points")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="best")

    assert resolved_loc(ax) == "upper left"


def test_datetime_text_and_annotations_participate_in_best_placement():
    """Each string-datetime text artist disqualifies one top corner."""
    _, ax = plt.subplots()
    dates = np.asarray(["2026-01-01", "2026-01-02"], dtype="datetime64[D]")
    ax.plot(dates, [0.5, 0.5], label="dated")
    ax.set_ylim(0, 1)
    ax.text("2026-1-2", 0.95, "text")
    ax.annotate("annotation", xy=("2026-1-1", 0.95))
    ax.legend(loc="best")
    assert resolved_loc(ax) == "lower left"


@pytest.mark.parametrize("legend_kwargs", [{}, {"loc": "best"}], ids=["default", "best"])
def test_best_is_concrete_on_the_wire_and_retains_live_intent(legend_kwargs):
    """The shim's first choice is concrete while its automatic intent survives."""
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    ax.legend(**legend_kwargs)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["loc"] != "best"
    assert spec["legend"]["loc"] in xy.pyplot._axes._LEGEND_LOC_ANCHORS
    assert spec["legend"]["auto_loc"] == "best"


def test_explicit_anchored_and_polar_pyplot_legends_stay_exact():
    _, explicit = plt.subplots()
    explicit.plot([0, 1], [0, 1], label="a")
    explicit.legend(loc="lower left")

    _, anchored = plt.subplots()
    anchored.plot([0, 1], [0, 1], label="a")
    anchored.legend(loc="best", bbox_to_anchor=(0.0, 1.0))

    _, polar = plt.subplots(subplot_kw={"projection": "polar"})
    polar.plot([0.0, 1.0], [0.2, 0.8], label="a")
    polar.legend(loc="best")

    for ax in (explicit, anchored, polar):
        spec, _ = ax._build_chart(640, 480).figure().build_payload()
        assert "auto_loc" not in spec["legend"]


def test_automatic_extra_legend_retains_live_intent():
    from xy.pyplot import Legend

    _, ax = plt.subplots()
    line = ax.plot([0, 1], [0, 1])[0]
    ax.add_artist(Legend(ax, [line], ["extra"]))

    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    extra = spec["extra_legends"][0]
    assert extra["loc"] in xy.pyplot._axes._LEGEND_LOC_ANCHORS
    assert extra["auto_loc"] == "best"


def test_static_export_at_the_same_size_keeps_pyplots_richer_decision(monkeypatch):
    # This deterministic fixture separates pyplot's annotation-aware scorer
    # from the core fallback scorer. Re-resolving at unchanged dimensions
    # would silently move the payload's lower-left choice to upper-left.
    rng = np.random.default_rng(10)
    ax = None
    for index in range(7):
        fixture, candidate_ax = plt.subplots()
        count = int(rng.integers(1, 40))
        candidate_ax.plot(rng.random(count), rng.random(count), label="a")
        if index % 3 == 0:
            candidate_ax.text(
                float(rng.random()),
                float(rng.random()),
                "W" * int(rng.integers(1, 30)),
            )
        candidate_ax.set_xlim(0, 1)
        candidate_ax.set_ylim(0, 1)
        candidate_ax.legend(loc="best")
        if index < 6:
            # The seventh seeded case is the minimal scorer-separating
            # regression. Earlier cases only advance that deterministic RNG
            # sequence; release their pyplot state as soon as it is consumed.
            plt.close(fixture)
        else:
            ax = candidate_ax

    assert ax is not None
    core = ax._build_chart(640, 480).figure()
    spec, _ = core.build_payload()
    assert spec["legend"]["loc"] == "lower left"

    from xy import _raster, _svg

    rendered = []
    original = _svg.render_svg

    def capture(spec, blob, **kwargs):
        rendered.append(spec["legend"]["loc"])
        return original(spec, blob, **kwargs)

    monkeypatch.setattr(_svg, "render_svg", capture)
    core.to_svg()
    core.to_svg(width=640, height=480)
    assert rendered == ["lower left", "lower left"]

    raster_locs = [
        _raster._export_payload(core, None, None, None)[0]["legend"]["loc"],
        _raster._export_payload(core, 640, 480, None)[0]["legend"]["loc"],
    ]
    assert raster_locs == ["lower left", "lower left"]
    plt.close(fixture)


def test_unlabeled_entries_do_not_crash_measurement():
    """A legend with no labelled entry still measures as one empty row."""
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.legend(loc="best")
    assert resolved_loc(ax) in xy.pyplot._axes._LEGEND_LOC_ANCHORS


# --------------------------------------------------------------------------
# The substring-match guard
# --------------------------------------------------------------------------


def test_pyplot_legend_loc_rejects_misspelled_locations():
    """Matplotlib's location vocabulary belongs to the pyplot shim.

    Core ``xy.legend`` intentionally has its own vocabulary (including the
    documented ``"top left"`` spelling), so validating this in the shared
    component is a core API regression rather than a pyplot compatibility fix.
    """
    _, ax = plt.subplots()
    for bogus in ("uppper right", "top left", "", "middle"):
        with pytest.raises(ValueError, match="legend loc must be one of"):
            ax.legend(loc=bogus)
    assert xy.legend(loc="top left").loc == "top left"


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("top", "upper"),
        ("top left", "upper left"),
        ("top-center", "upper-center"),
        ("bottom", "lower"),
        ("bottom right", "lower right"),
        ("bottom_center", "lower_center"),
    ],
)
def test_core_legend_vertical_aliases_match_static_layout(alias, canonical):
    """Core aliases keep their public spelling but share SVG anchor geometry."""
    items = [{"name": "abc"}]
    plot = {"x": 40.0, "y": 20.0, "w": 400.0, "h": 300.0}
    for anchor in (None, (0.2, 0.3), (0.2, 0.3, 0.4, 0.5)):
        options = {"loc": alias, "anchor": anchor}
        canonical_options = {"loc": canonical, "anchor": anchor}
        actual = _legend_layout(items, plot, options)
        expected = _legend_layout(items, plot, canonical_options)
        assert (actual["x"], actual["y"]) == pytest.approx((expected["x"], expected["y"]))


def test_every_matplotlib_loc_places_the_box_at_its_anchor():
    items = [{"name": "abc"}]
    plot = {"x": 40.0, "y": 20.0, "w": 400.0, "h": 300.0}
    inset = 6.0
    for loc, (hx, vy) in xy.pyplot._axes._LEGEND_LOC_ANCHORS.items():
        box = _legend_layout(items, plot, {"loc": loc})
        want_x = plot["x"] + inset + hx * (plot["w"] - 2 * inset - box["box_w"])
        want_y = plot["y"] + inset + (1.0 - vy) * (plot["h"] - 2 * inset - box["box_h"])
        assert box["x"] == pytest.approx(want_x), loc
        assert box["y"] == pytest.approx(want_y), loc


def test_right_and_center_right_are_the_same_anchor():
    """Matplotlib resolves codes 5 and 7 to the same offsetbox corner."""
    locations = xy.pyplot._axes._LEGEND_LOC_ANCHORS
    assert locations["right"] == locations["center right"]
    items = [{"name": "abc"}]
    plot = {"x": 0.0, "y": 0.0, "w": 400.0, "h": 300.0}
    a = _legend_layout(items, plot, {"loc": "right"})
    b = _legend_layout(items, plot, {"loc": "center right"})
    assert (a["x"], a["y"]) == (b["x"], b["y"])


def test_best_candidate_order_is_matplotlib_code_order():
    """The tie-break contract: Matplotlib prefers the lower location code."""
    from xy.pyplot._axes import _BEST_LOC_ORDER

    # Codes 1..10 with code 7 folded onto its identical code-5 "right" anchor.
    assert _BEST_LOC_ORDER == (
        "upper right",
        "upper left",
        "lower left",
        "lower right",
        "right",
        "center left",
        "lower center",
        "upper center",
        "center",
    )
    assert set(_BEST_LOC_ORDER) <= set(xy.pyplot._axes._LEGEND_LOC_ANCHORS)


def test_ties_keep_the_earliest_candidate():
    """An empty plot leaves every candidate at zero -> code 1 wins."""
    _, ax = plt.subplots()
    ax.plot([], [], label="nothing")
    ax.legend(loc="best")
    assert resolved_loc(ax) == "upper right"
