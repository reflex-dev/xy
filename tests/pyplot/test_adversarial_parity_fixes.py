"""Regressions from the PR #44 review: adversarial parity gaps found by
independent testing against matplotlib 3.11 (exact tick location, absolute
subplot placement, dataless-axis state, subplots_adjust, date locator phase,
third-party locator contract, annotation arrows, and figure facecolor specs).

Every reference value here was produced by matplotlib 3.11.0.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def _ms(stamp: str) -> float:
    return float(np.datetime64(stamp, "ms").astype(np.int64))


# -- MaxNLocator: narrow, far-offset ranges ----------------------------------


def test_maxn_locator_keeps_scale_for_narrow_far_offset_ranges():
    # A ~1e-4 span sitting at 1e9: the offset logic must engage exactly here,
    # not bail out — bailing produced two out-of-view ticks that the axis then
    # clipped away entirely.
    ticks = plt.MaxNLocator(4).tick_values(1_000_000_000.0001, 1_000_000_000.0002)
    reference = 1e9 + np.asarray([9e-05, 1.2e-04, 1.5e-04, 1.8e-04, 2.1e-04])
    assert np.allclose(ticks, reference, rtol=0, atol=1e-6)
    # Three interior ticks survive view clipping (the edge pair overruns, as
    # in matplotlib, and is trimmed at draw time).
    inside = (ticks >= 1_000_000_000.0001) & (ticks <= 1_000_000_000.0002)
    assert inside.sum() == 3


def test_singular_range_still_returns_a_tick():
    assert list(plt.MaxNLocator(4).tick_values(2.0, 2.0)) == [2.0]


# -- absolute panel placement: titled axes ------------------------------------


def test_axes_title_keeps_absolute_panel_plot_rect():
    # Multi-panel figures place every plot box at its gridspec rectangle;
    # matplotlib does not move an axes when a title is added, so the title
    # must widen the panel chrome instead of eating 26-30px of plot height.
    from xy._svg import layout

    fig, axs = plt.subplots(2, 1, figsize=(6.4, 4.8))
    for ax in axs:
        ax.plot([1, 2], [3, 4])
    requested = fig._effective_rects()[0]
    axs[0].set_title("hello")
    charts = fig._charts()
    positions = fig._panel_positions(fig._effective_rects(), (640, 480))
    spec, _ = charts[0].figure().build_payload()
    _, _, _, plot = layout(spec)
    panel_x = round(positions[0][0] * 640)
    panel_y = round((1 - positions[0][1] - positions[0][3]) * 480)
    actual = (panel_x + plot["x"], panel_y + plot["y"], plot["w"], plot["h"])
    expected = (
        round(requested[0] * 640),
        round((1 - requested[1] - requested[3]) * 480),
        round(requested[2] * 640),
        round(requested[3] * 480),
    )
    assert actual == expected


# -- dataless-axis render fallback ---------------------------------------------


def test_empty_axis_render_does_not_pin_later_limits():
    # Rendering an empty axes shows the (0, 1) matplotlib view, but must not
    # persist it: data plotted afterwards autoscales as if never rendered.
    fig, ax = plt.subplots()
    ax.margins(0)
    ax._build_chart(640, 480)
    assert ax.get_xlim() == (0.0, 1.0)
    ax.plot([10, 20], [30, 40])
    assert ax.get_xlim() == (10.0, 20.0)
    assert ax.get_ylim() == (30.0, 40.0)


# -- gridspec spans after subplots_adjust ---------------------------------------


def test_gridspec_span_tracks_subplots_adjust():
    fig = plt.figure()
    gs = fig.add_gridspec(2, 2)
    ax = fig.add_subplot(gs[:, 0])
    fig.subplots_adjust(left=0.3, right=0.8)
    bounds = ax.get_position().bounds
    assert np.allclose(bounds, (0.3, 0.11, 0.22727272727272724, 0.77))


def test_subplots_adjust_before_gridspec_span_also_applies():
    fig = plt.figure()
    fig.subplots_adjust(left=0.3, right=0.8)
    gs = fig.add_gridspec(2, 2)
    ax = fig.add_subplot(gs[:, 0])
    assert np.allclose(ax.get_position().bounds, (0.3, 0.11, 0.22727272727272724, 0.77))


def test_subplots_adjust_overrides_set_position_for_gridspec_axes():
    # matplotlib re-resolves every subplotspec-backed axes on subplots_adjust,
    # even one previously moved by set_position (verified on 3.11).
    fig = plt.figure()
    gs = fig.add_gridspec(2, 2)
    ax = fig.add_subplot(gs[:, 0])
    ax.set_position((0.1, 0.1, 0.4, 0.8))
    assert ax.get_position().bounds == (0.1, 0.1, 0.4, 0.8)
    fig.subplots_adjust(left=0.35)
    assert np.allclose(ax.get_position().bounds, (0.35, 0.11, 0.25, 0.77))


def test_month_locator_bymonth_subset_keeps_rrule_stride():
    # rrule's MONTHLY interval strides over *all* months; bymonth filters the
    # survivors (matplotlib 3.11 reference).
    ticks = plt.dates.MonthLocator(bymonth=(1, 4, 7, 10), interval=2).tick_values(
        _ms("2011-01-15"), _ms("2013-06-01")
    )
    assert list(ticks) == [
        _ms(stamp)
        for stamp in ("2011-04-01", "2011-10-01", "2012-04-01", "2012-10-01", "2013-04-01")
    ]


# -- calendar locator interval phase --------------------------------------------


def test_month_locator_interval_phase_matches_matplotlib():
    # matplotlib's RRuleLocator anchors interval counting at the view-derived
    # dtstart (vmin - relativedelta(vmax, vmin)), not at a fixed epoch.
    ticks = plt.dates.MonthLocator(interval=2).tick_values(_ms("2011-11-23"), _ms("2013-04-17"))
    assert list(ticks) == [
        _ms(stamp)
        for stamp in (
            "2011-12-01",
            "2012-02-01",
            "2012-04-01",
            "2012-06-01",
            "2012-08-01",
            "2012-10-01",
            "2012-12-01",
            "2013-02-01",
            "2013-04-01",
        )
    ]


def test_day_locator_interval_phase_matches_matplotlib():
    ticks = plt.dates.DayLocator(interval=7).tick_values(_ms("2020-03-05"), _ms("2020-04-10"))
    assert list(ticks) == [
        _ms(stamp)
        for stamp in (
            "2020-03-06",
            "2020-03-13",
            "2020-03-20",
            "2020-03-27",
            "2020-04-03",
            "2020-04-10",
        )
    ]


def test_year_locator_base_stays_anchored_to_multiples():
    ticks = plt.dates.YearLocator(base=5).tick_values(_ms("2003-06-01"), _ms("2017-02-01"))
    assert list(ticks) == [_ms("2005-01-01"), _ms("2010-01-01"), _ms("2015-01-01")]


# -- third-party locator contract ------------------------------------------------


def test_third_party_locator_is_never_mutated():
    class SlottedLocator:
        __slots__ = ()

        def tick_values(self, lo, hi):
            return np.asarray([lo, hi])

    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.xaxis.set_major_locator(SlottedLocator())
    chart = ax._build_chart(640, 480)  # must not write hints onto the locator
    assert chart is not None


# -- annotation arrows: truthy/falsy gating ----------------------------------------


def _annotation_children(label, arrowprops):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.annotate(
        label, xy=(0.5, 0.5), xytext=(20, 20), textcoords="offset points", arrowprops=arrowprops
    )
    return {child.kind for child in ax._chart_children()}


def test_annotate_empty_label_with_arrowstyle_keeps_the_arrow():
    assert "callout" in _annotation_children("", {"arrowstyle": "->"})


def test_annotate_empty_arrowprops_dict_keeps_the_arrow():
    # matplotlib draws its default (YAArrow-style) arrow for arrowprops={}.
    assert "callout" in _annotation_children("x", {})


def test_annotate_without_arrowprops_stays_plain_text():
    kinds = _annotation_children("x", None)
    assert "callout" not in kinds and "text" in kinds


# -- figure facecolor color specs ----------------------------------------------------


def test_tuple_facecolor_normalizes_and_renders():
    fig, ax = plt.subplots(facecolor=(1.0, 0.0, 0.0, 1.0))
    ax.plot([0, 1], [0, 1])
    assert fig.get_facecolor() == "rgba(255,0,0,1)"
    html = fig._repr_html_()
    assert "rgba(255,0,0,1)" in html


def test_set_facecolor_accepts_tuples():
    fig, _ = plt.subplots()
    fig.set_facecolor((0.0, 1.0, 0.0))
    assert fig.get_facecolor() == "rgb(0,255,0)"
