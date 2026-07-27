from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    plt.rcdefaults()
    yield
    plt.close("all")
    plt.rcdefaults()


def _axis_domain(ax, which: str) -> tuple[float, float]:
    chart = ax._build_chart(640, 480)
    figure = chart.figure()
    return figure.x_range() if which == "x" else figure.y_range()


def test_default_rc_margins_apply_to_public_and_rendered_line_limits() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [1.0, 3.0, 2.0])

    assert ax.get_xlim() == pytest.approx((-0.1, 2.1))
    assert ax.get_ylim() == pytest.approx((0.9, 3.1))
    assert _axis_domain(ax, "x") == pytest.approx((-0.1, 2.1))
    assert _axis_domain(ax, "y") == pytest.approx((0.9, 3.1))


def test_default_margin_render_delegates_to_figure_autorange(monkeypatch) -> None:
    _fig, ax = plt.subplots()
    ax.plot(np.arange(10_000.0), np.arange(10_000.0))

    def unexpected_scan(_axis: str) -> tuple[float, float]:
        raise AssertionError("ordinary rendering must not rescan pyplot arrays")

    monkeypatch.setattr(ax, "_auto_domain", unexpected_scan)
    chart = ax._build_chart(640, 480)
    axes = {
        child.which: child
        for child in chart.children
        if getattr(child, "which", None) in {"x", "y"}
    }

    assert axes["x"].domain is None
    assert axes["y"].domain is None
    assert axes["x"].margin == pytest.approx(0.05)
    assert axes["y"].margin == pytest.approx(0.05)
    assert chart.figure().x_range() == pytest.approx((-499.95, 10_498.95))


def test_singleton_margin_matches_public_and_rendered_limits() -> None:
    _fig, ax = plt.subplots()
    ax.plot([5.0], [1.0])

    assert ax.get_xlim() == pytest.approx((4.95, 6.05))
    assert ax.get_ylim() == pytest.approx((0.95, 2.05))
    assert _axis_domain(ax, "x") == pytest.approx(ax.get_xlim())
    assert _axis_domain(ax, "y") == pytest.approx(ax.get_ylim())


def test_twin_y_margin_matches_public_and_rendered_limits() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [1.0, 2.0])
    twin = ax.twinx()
    twin.plot([0.0, 1.0], [10.0, 20.0])
    twin.margins(y=0.1)

    rendered = ax._build_chart(640, 480).figure()._range("y2")

    assert ax.get_ylim() == pytest.approx((0.95, 2.05))
    assert twin.get_ylim() == pytest.approx((9.0, 21.0))
    assert rendered == pytest.approx(twin.get_ylim())


def test_axes_snapshot_rc_margins_at_creation() -> None:
    with plt.rc_context({"axes.xmargin": 0.1, "axes.ymargin": 0.2}):
        _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [-1.0, 1.0])

    assert ax.get_xlim() == pytest.approx((-1.0, 11.0))
    assert ax.get_ylim() == pytest.approx((-1.4, 1.4))


def test_default_margin_is_applied_in_log_coordinate_space() -> None:
    _fig, ax = plt.subplots()
    ax.plot([1.0, 10.0, 100.0], [1.0, 2.0, 3.0])
    ax.set_xscale("log")

    expected = (10.0**-0.1, 10.0**2.1)
    assert ax.get_xlim() == pytest.approx(expected)
    assert _axis_domain(ax, "x") == pytest.approx(expected)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.2, 1.8, 1.4], (0.0, 1.89)),
        ([-1.2, -1.8, -1.4], (-1.89, 0.0)),
        ([-2.0, 3.0, 1.0], (-2.25, 3.25)),
    ],
)
def test_vertical_bar_limits_include_sticky_baseline_and_margin(values, expected) -> None:
    _fig, ax = plt.subplots()
    ax.bar([0.0, 1.0, 2.0], values)

    assert ax.get_ylim() == pytest.approx(expected)
    assert _axis_domain(ax, "y") == pytest.approx(expected)


def test_stacked_bar_limits_include_bases_and_cumulative_tops() -> None:
    _fig, ax = plt.subplots()
    ax.bar([0.0, 1.0, 2.0], [1.0, 1.5, 0.8])
    ax.bar(
        [0.0, 1.0, 2.0],
        [2.0, 1.0, 2.5],
        bottom=[1.0, 1.5, 0.8],
    )

    assert ax.get_xlim() == pytest.approx((-0.54, 2.54))
    assert ax.get_ylim() == pytest.approx((0.0, 3.465))
    assert _axis_domain(ax, "x") == pytest.approx((-0.54, 2.54))
    assert _axis_domain(ax, "y") == pytest.approx((0.0, 3.465))


def test_horizontal_bar_limits_include_value_baseline_and_category_width() -> None:
    _fig, ax = plt.subplots()
    ax.barh(["A", "B", "C"], [1.2, 1.8, 1.4])

    assert ax.get_xlim() == pytest.approx((0.0, 1.89))
    assert ax.get_ylim() == pytest.approx((-0.54, 2.54))
    assert _axis_domain(ax, "x") == pytest.approx((0.0, 1.89))
    assert _axis_domain(ax, "y") == pytest.approx((-0.54, 2.54))


def test_categorical_bar_domain_covers_every_category() -> None:
    _fig, ax = plt.subplots()
    ax.bar(
        ["first category", "second category", "third category", "fourth category"],
        [1.0, 3.0, 2.0, 4.0],
    )

    assert ax.get_xlim() == pytest.approx((-0.59, 3.59))
    assert ax.get_ylim() == pytest.approx((0.0, 4.2))
    assert _axis_domain(ax, "x") == pytest.approx((-0.59, 3.59))


def test_repeated_categorical_bars_share_the_renderers_category_map() -> None:
    _fig, ax = plt.subplots()
    ax.bar(["same", "same"], [1.0, 2.0])

    assert ax.get_xlim() == pytest.approx((-0.44, 0.44))
    assert _axis_domain(ax, "x") == pytest.approx(ax.get_xlim())


def test_nonzero_bar_base_stays_sticky_in_the_rendered_domain() -> None:
    _fig, ax = plt.subplots()
    ax.bar([0.0, 1.0], [1.0, 2.0], bottom=10.0)

    assert ax.get_ylim() == pytest.approx((10.0, 12.1))
    assert _axis_domain(ax, "y") == pytest.approx(ax.get_ylim())


def test_fill_between_and_errorbar_geometry_contribute_to_autoscale() -> None:
    _fig, fill_ax = plt.subplots()
    fill_ax.fill_between([0.0, 1.0], [2.0, 3.0], [-5.0, -4.0])
    assert fill_ax.get_ylim() == pytest.approx((-5.4, 3.4))
    assert _axis_domain(fill_ax, "y") == pytest.approx(fill_ax.get_ylim())

    _fig, error_ax = plt.subplots()
    error_ax.errorbar([0.0, 1.0], [2.0, 3.0], yerr=[5.0, 6.0])
    assert error_ax.get_ylim() == pytest.approx((-3.6, 9.6))
    assert _axis_domain(error_ax, "y") == pytest.approx(error_ax.get_ylim())


def test_default_bar_margin_reserves_visible_headroom_for_edge_labels() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0.0, 1.0, 2.0], [1.2, 1.8, 1.4], width=0.55)
    labels = ax.bar_label(bars, fmt="%.1f", padding=3)

    assert [label.get_text() for label in labels] == ["1.2", "1.8", "1.4"]
    assert ax.get_ylim() == pytest.approx((0.0, 1.935))
    assert _axis_domain(ax, "y") == pytest.approx((0.0, 1.935))
    assert max(np.asarray(bars.tops, dtype=float)) < ax.get_ylim()[1]


def test_explicit_margin_overrides_bar_label_headroom_default() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0.0, 1.0], [1.0, 2.0])
    ax.margins(y=0.02)
    ax.bar_label(bars, padding=3)

    assert ax.get_ylim() == pytest.approx((0.0, 2.04))
    assert _axis_domain(ax, "y") == pytest.approx((0.0, 2.04))


def test_horizontal_edge_labels_reserve_value_axis_headroom() -> None:
    _fig, ax = plt.subplots()
    bars = ax.barh(["A", "B", "C"], [1.2, 1.8, 1.4])
    ax.bar_label(bars, padding=3)

    assert ax.get_xlim() == pytest.approx((0.0, 1.935))
    assert _axis_domain(ax, "x") == pytest.approx((0.0, 1.935))


def test_centered_bar_labels_do_not_expand_autoscale_margin() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0.0, 1.0], [1.0, 2.0])
    ax.bar_label(bars, label_type="center")

    assert ax.get_ylim() == pytest.approx((0.0, 2.1))


def test_vertical_edge_bar_labels_follow_asymmetric_error_endpoints_and_sign() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar(
        [0.0, 1.0],
        [3.0, -4.0],
        bottom=[1.0, 2.0],
        yerr=[[0.5, 1.5], [2.0, 0.25]],
    )

    labels = ax.bar_label(bars, padding=3)

    assert bars.errorbar is not None
    assert bars.errorbar.has_yerr
    assert [label._entry["args"][1] for label in labels] == pytest.approx([6.0, -3.5])
    assert [label._entry["kwargs"]["dy"] for label in labels] == pytest.approx(
        [-3.0 * 100.0 / 72.0, 3.0 * 100.0 / 72.0]
    )
    assert [label._entry["kwargs"]["style"]["vertical_align"] for label in labels] == [
        "bottom",
        "top",
    ]


def test_inverted_vertical_bar_axis_flips_edge_label_padding_and_alignment() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0.0, 1.0], [3.0, -4.0], yerr=[[0.5, 1.5], [2.0, 0.25]])
    ax.invert_yaxis()

    labels = ax.bar_label(bars, padding=3)

    assert [label._entry["args"][1] for label in labels] == pytest.approx([5.0, -5.5])
    assert [label._entry["kwargs"]["dy"] for label in labels] == pytest.approx(
        [3.0 * 100.0 / 72.0, -3.0 * 100.0 / 72.0]
    )
    assert [label._entry["kwargs"]["style"]["vertical_align"] for label in labels] == [
        "top",
        "bottom",
    ]


def test_horizontal_edge_bar_labels_follow_errors_and_inverted_axis() -> None:
    _fig, ax = plt.subplots()
    bars = ax.barh(
        [0.0, 1.0],
        [3.0, -4.0],
        left=[1.0, 2.0],
        xerr=[[0.5, 1.5], [2.0, 0.25]],
    )
    ax.invert_xaxis()

    labels = ax.bar_label(bars, padding=4)

    assert bars.errorbar is not None
    assert bars.errorbar.has_xerr
    assert [label._entry["args"][0] for label in labels] == pytest.approx([6.0, -3.5])
    assert [label._entry["kwargs"]["dx"] for label in labels] == pytest.approx(
        [-4.0 * 100.0 / 72.0, 4.0 * 100.0 / 72.0]
    )
    assert [label._entry["kwargs"]["anchor"] for label in labels] == ["end", "start"]
