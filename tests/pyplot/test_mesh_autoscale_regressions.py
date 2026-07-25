"""The pre-build autoscale scan must recognize every factory the shim emits.

`Axes._iter_entry_arrays` feeds `_axis_is_dataless`, and a populated axes that
scans as dataless gets pinned to the empty ``(0, 1)`` view in `_build_chart` —
clipping the real geometry. Mesh, image, ECDF, and box entries keep their
coordinates inside ``kwargs`` rather than as top-level ``x``/``y``, so each
needs an explicit branch. These lock every one of them in place.
"""

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


def _rendered(ax, which: str) -> tuple[float, float]:
    figure = ax._build_chart(640, 480).figure()
    return figure.x_range() if which == "x" else figure.y_range()


def _assert_contains(view: tuple[float, float], lo: float, hi: float) -> None:
    span = max(abs(lo), abs(hi), 1.0)
    tolerance = span * 1e-12
    assert view[0] <= lo + tolerance, f"{view} clips data low edge {lo}"
    assert view[1] >= hi - tolerance, f"{view} clips data high edge {hi}"


def test_hist2d_view_contains_every_bin() -> None:
    """The reported defect: 30x30 bins computed, ~4x3 of them visible."""
    rng = np.random.default_rng(1701)
    x, y = rng.multivariate_normal([0, 0], [[1, 1], [1, 2]], 10_000).T
    _fig, ax = plt.subplots()

    counts, xedges, yedges, _image = ax.hist2d(x, y, bins=30)

    assert counts.shape == (30, 30)
    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    # Matplotlib gives hist2d sticky edges: the view is exactly the bin edges.
    assert ax.get_xlim() == pytest.approx((xedges[0], xedges[-1]))
    assert ax.get_ylim() == pytest.approx((yedges[0], yedges[-1]))
    _assert_contains(_rendered(ax, "x"), xedges[0], xedges[-1])
    _assert_contains(_rendered(ax, "y"), yedges[0], yedges[-1])


def test_hist2d_explicit_range_is_not_pinned_to_the_unit_view() -> None:
    rng = np.random.default_rng(0)
    _fig, ax = plt.subplots()

    _counts, xedges, yedges, _image = ax.hist2d(
        rng.normal(size=500), rng.normal(size=500), bins=10, range=((-3, 3), (-2, 2))
    )

    assert (xedges[0], xedges[-1]) == pytest.approx((-3.0, 3.0))
    assert ax.get_xlim() == pytest.approx((-3.0, 3.0))
    assert ax.get_ylim() == pytest.approx((-2.0, 2.0))
    _assert_contains(_rendered(ax, "x"), xedges[0], xedges[-1])
    _assert_contains(_rendered(ax, "y"), yedges[0], yedges[-1])


def test_hist2d_irregular_bins_take_the_mesh_path_and_still_autoscale() -> None:
    """Non-uniform bins delegate to pcolormesh; both paths must autoscale."""
    rng = np.random.default_rng(0)
    xedges = np.array([-4.0, -1.0, 0.0, 1.0, 4.0])
    yedges = np.array([-4.0, 0.0, 1.0, 4.0])
    _fig, ax = plt.subplots()

    ax.hist2d(rng.normal(size=500), rng.normal(size=500), bins=[xedges, yedges])

    assert not ax._axis_is_dataless("x")
    assert ax.get_xlim() == pytest.approx((xedges[0], xedges[-1]))
    assert ax.get_ylim() == pytest.approx((yedges[0], yedges[-1]))
    assert _rendered(ax, "x") == pytest.approx((xedges[0], xedges[-1]))
    assert _rendered(ax, "y") == pytest.approx((yedges[0], yedges[-1]))


def test_pcolormesh_uniform_grid_hugs_its_outer_cell_edges() -> None:
    z = np.random.default_rng(1).normal(size=(25, 30))
    _fig, ax = plt.subplots()

    ax.pcolormesh(np.linspace(0.0, 5.0, 31), np.linspace(0.0, 5.0, 26), z)

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    assert ax.get_xlim() == pytest.approx((0.0, 5.0))
    assert ax.get_ylim() == pytest.approx((0.0, 5.0))
    # Sticky on both ends, so no margin is added to a mesh.
    assert _rendered(ax, "x") == pytest.approx((0.0, 5.0))
    assert _rendered(ax, "y") == pytest.approx((0.0, 5.0))


def test_pcolormesh_two_dimensional_coordinates_autoscale() -> None:
    grid_x, grid_y = np.meshgrid(np.linspace(0.0, 5.0, 30), np.linspace(0.0, 5.0, 25))
    _fig, ax = plt.subplots()

    ax.pcolormesh(grid_x, grid_y, np.sin(grid_x)[:-1, :-1])

    assert not ax._axis_is_dataless("x")
    _assert_contains(_rendered(ax, "x"), 0.0, 5.0)
    _assert_contains(_rendered(ax, "y"), 0.0, 5.0)


def test_pcolormesh_without_coordinates_uses_implicit_integer_edges() -> None:
    """Matplotlib's pcolormesh(C) occupies edges 0..N and 0..M."""
    _fig, ax = plt.subplots()

    ax.pcolormesh(np.arange(12.0).reshape(3, 4))

    assert not ax._axis_is_dataless("x")
    assert ax.get_xlim() == pytest.approx((0.0, 4.0))
    assert ax.get_ylim() == pytest.approx((0.0, 3.0))


def test_specgram_axes_are_not_pinned_to_the_unit_view() -> None:
    rng = np.random.default_rng(0)
    _fig, ax = plt.subplots()

    _power, frequency, time, _image = ax.specgram(rng.normal(size=4096), NFFT=256, Fs=2.0)

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    half_time_bin = float(time[1] - time[0]) * 0.5
    assert ax.get_xlim() == pytest.approx(
        (float(time[0]) - half_time_bin, float(time[-1]) + half_time_bin)
    )
    assert ax.get_ylim() == pytest.approx((float(frequency[0]), float(frequency[-1])))
    assert _rendered(ax, "x") == pytest.approx(ax.get_xlim())
    assert _rendered(ax, "y") == pytest.approx(ax.get_ylim())


def test_imshow_explicit_extent_stays_flush_with_the_image_edges() -> None:
    _fig, ax = plt.subplots()

    ax.imshow(np.arange(12.0).reshape(3, 4), extent=(0.0, 4.0, 0.0, 3.0), aspect="auto")

    assert ax.get_xlim() == pytest.approx((0.0, 4.0))
    assert ax.get_ylim() == pytest.approx((0.0, 3.0))
    assert _rendered(ax, "x") == pytest.approx((0.0, 4.0))
    assert _rendered(ax, "y") == pytest.approx((0.0, 3.0))


def test_ecdf_spans_its_samples_and_sticks_to_zero_and_one() -> None:
    _fig, ax = plt.subplots()

    ax.ecdf(np.array([1.0, 2.0, 3.0, 4.0]))

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    # Matplotlib: x carries the ordinary 5% margin, y is sticky at 0 and 1.
    assert ax.get_xlim() == pytest.approx((0.85, 4.15))
    assert ax.get_ylim() == pytest.approx((0.0, 1.0))
    _assert_contains(_rendered(ax, "x"), 1.0, 4.0)
    assert _rendered(ax, "y") == pytest.approx((0.0, 1.0))


@pytest.mark.parametrize(
    ("kwargs", "sample_axis", "cumulative_axis"),
    [
        ({"weights": [1.0, 2.0, 3.0, 4.0]}, "x", "y"),
        ({"complementary": True}, "x", "y"),
        ({"compress": True}, "x", "y"),
        ({"orientation": "horizontal"}, "y", "x"),
    ],
)
def test_nondefault_ecdf_variants_autoscale_and_keep_cumulative_axis_sticky(
    kwargs: dict[str, object], sample_axis: str, cumulative_axis: str
) -> None:
    _fig, ax = plt.subplots()

    ax.ecdf(np.array([1.0, 2.0, 3.0, 4.0]), **kwargs)

    assert not ax._axis_is_dataless(sample_axis)
    assert not ax._axis_is_dataless(cumulative_axis)
    assert (ax.get_xlim() if cumulative_axis == "x" else ax.get_ylim()) == pytest.approx((0.0, 1.0))
    assert _rendered(ax, cumulative_axis) == pytest.approx((0.0, 1.0))


def test_ordinary_step_factory_contributes_both_axes_to_autoscale() -> None:
    _fig, ax = plt.subplots()

    ax.step([10.0, 20.0, 30.0], [-4.0, 2.0, 8.0])

    assert ax.get_xlim() == pytest.approx((9.0, 31.0))
    assert ax.get_ylim() == pytest.approx((-4.6, 8.6))


def test_boxplot_value_axis_covers_whiskers_and_fliers() -> None:
    rng = np.random.default_rng(0)
    left, right = rng.normal(size=2000), rng.normal(size=2000)
    _fig, ax = plt.subplots()

    ax.boxplot([left, right])

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    assert ax.get_xlim() == pytest.approx((0.5, 2.5))
    # Fliers are drawn, so the value axis reaches the extreme observations.
    _assert_contains(_rendered(ax, "y"), float(min(left.min(), right.min())), 0.0)
    _assert_contains(_rendered(ax, "y"), 0.0, float(max(left.max(), right.max())))


def test_boxplot_without_fliers_tightens_to_the_whiskers() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(size=2000)
    _fig, ax = plt.subplots()

    ax.boxplot([values], showfliers=False)

    rendered = _rendered(ax, "y")
    assert rendered[0] > values.min()
    assert rendered[1] < values.max()
    assert not ax._axis_is_dataless("y")


def test_horizontal_boxplot_swaps_which_axis_carries_the_values() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(size=500)
    _fig, ax = plt.subplots()

    ax.boxplot([values], orientation="horizontal")

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    assert ax.get_ylim() == pytest.approx((0.5, 1.5))
    _assert_contains(
        _rendered(ax, "x"), float(np.percentile(values, 25)), float(np.percentile(values, 75))
    )


def test_boxplot_custom_positions_reserve_half_unit_category_edges() -> None:
    rng = np.random.default_rng(0)
    _fig, ax = plt.subplots()

    ax.boxplot([rng.normal(size=100), rng.normal(size=100)], positions=[2.0, 4.0])

    assert ax.get_xlim() == pytest.approx((1.5, 4.5))
    assert _rendered(ax, "x") == pytest.approx((1.5, 4.5))


def test_mesh_entries_do_not_make_bar_baselines_sticky_on_both_ends() -> None:
    """Guard the `_fully_sticky_domain` narrowing: bars keep their margin.

    A one-sided sticky edge is the rectangle baseline, which the core anchors
    itself; materializing a domain for it would bypass the engine's autorange.
    """
    _fig, ax = plt.subplots()
    ax.bar([0.0, 1.0, 2.0], [1.0, 3.0, 2.0])

    chart = ax._build_chart(640, 480)
    axes = {
        child.which: child
        for child in chart.children
        if getattr(child, "which", None) in {"x", "y"}
    }
    assert axes["y"].domain is None
    assert axes["y"].margin == pytest.approx(0.05)
