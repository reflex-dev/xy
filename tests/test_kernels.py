"""Kernel correctness for the native Rust core.

The two thesis-risk tests §25 moved to the front of Phase 0 live here:
offset-encoding precision on ms timestamps, and M4's no-silent-data-loss
guarantees.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from xy import kernels as k
from xy.config import MAX_SCREEN_DIM

BACKENDS = [pytest.param(k, id=f"dispatch[{k.BACKEND}]")]


@pytest.fixture(params=BACKENDS)
def impl(request):
    return request.param


# -- offset-encoded f32 (§4/§16) -------------------------------------------


def test_precision_1s_span_in_10y_ms_series(impl):
    """§25 exit criterion: 1-second window inside a 10-year ms-timestamp series."""
    t0 = 1.6e12  # ~2020 in ms epoch
    ten_years = 10 * 365 * 86_400_000
    # The visible window: 1000 points, 1ms apart, deep inside the series.
    window = t0 + ten_years * 0.7 + np.arange(1000, dtype=np.float64)
    offset = float(window[500])  # §16: re-center on the viewport
    enc = impl.encode_f32(window, offset)
    decoded = enc.astype(np.float64) + offset
    max_err_ms = np.abs(decoded - window).max()
    assert max_err_ms < 1e-3, f"worst error {max_err_ms} ms"


def test_naive_f32_would_corrupt_the_same_data(impl):
    """Control: without the offset, f32 destroys ms resolution (§15 finding 2)."""
    t0 = 1.6e12
    window = t0 + np.arange(1000, dtype=np.float64)
    naive = impl.encode_f32(window, 0.0)
    worst = np.abs(naive.astype(np.float64) - window).max()
    assert worst > 1.0


def test_encode_scale(impl):
    data = np.array([10.0, 20.0, 30.0])
    enc = impl.encode_f32(data, 20.0, 0.1)
    np.testing.assert_allclose(enc, [-1.0, 0.0, 1.0], rtol=1e-6)


@pytest.mark.parametrize("baseline", ["zero", "sym", "wiggle", "weighted_wiggle"])
def test_stacked_bounds_match_matplotlib_reference(impl, baseline):
    values = np.array(
        [[1.0, 2.0, 3.0, 4.0], [2.0, 1.0, 4.0, 2.0], [0.5, 3.0, 1.0, 2.0]],
        dtype=np.float64,
    )
    stack = np.cumsum(values, axis=0)
    if baseline == "zero":
        first = np.zeros(values.shape[1])
    elif baseline == "sym":
        first = -np.sum(values, axis=0) * 0.5
        stack += first
    elif baseline == "wiggle":
        m = values.shape[0]
        first = (values * (m - 0.5 - np.arange(m)[:, None])).sum(axis=0) / -m
        stack += first
    else:
        total = np.sum(values, axis=0)
        inv_total = np.zeros_like(total)
        inv_total[total > 0] = 1.0 / total[total > 0]
        increase = np.hstack((values[:, :1], np.diff(values)))
        below_size = total - stack + 0.5 * values
        move_up = below_size * inv_total
        move_up[:, 0] = 0.5
        center = np.cumsum(((move_up - 0.5) * increase).sum(axis=0))
        first = center - 0.5 * total
        stack += first
    expected_lower = np.vstack((first, stack[:-1]))
    lower, upper = impl.stacked_bounds(values, baseline)
    np.testing.assert_allclose(lower, expected_lower)
    np.testing.assert_allclose(upper, stack)


def test_histogram2d_arbitrary_edges_and_weights_match_numpy(impl):
    rng = np.random.default_rng(22)
    x = rng.normal(size=20_000)
    y = x * 0.25 + rng.normal(size=20_000)
    weights = rng.uniform(0.1, 2.0, size=20_000)
    x_edges = np.array([-4.0, -1.5, -0.2, 0.1, 0.8, 4.0])
    y_edges = np.array([-5.0, -2.0, -0.5, 0.7, 1.0, 5.0])
    actual = impl.histogram2d(x, y, x_edges, y_edges, weights)
    expected, _, _ = np.histogram2d(x, y, bins=(x_edges, y_edges), weights=weights)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_quad_mesh_triangles_support_rectilinear_and_warped_grids(impl):
    values = np.array([[1.0, 2.0], [3.0, np.nan]])
    rect = impl.quad_mesh_triangles(np.array([0.0, 1.0, 4.0]), np.array([0.0, 2.0, 5.0]), values)
    assert all(len(column) == 6 for column in rect)
    np.testing.assert_array_equal(rect[-1], [1.0, 1.0, 2.0, 2.0, 3.0, 3.0])
    xx, yy = np.meshgrid([0.0, 1.0, 4.0], [0.0, 2.0, 5.0])
    xx[1, 1] += 0.25
    yy[1, 1] -= 0.5
    warped = impl.quad_mesh_triangles(xx, yy, values)
    assert all(len(column) == 6 for column in warped)
    assert warped[2][0] == 1.0
    assert warped[5][0] == 1.5


def test_indexed_triangle_geometry_edges_and_contours(impl):
    x = np.array([0.0, 1.0, 0.0, 1.0])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    topology = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
    z = x + y
    mesh = impl.indexed_triangles(x, y, topology, z, values_at="vertex")
    assert all(len(column) == 2 for column in mesh)
    np.testing.assert_allclose(mesh[-1], [2.0 / 3.0, 4.0 / 3.0])
    edges = impl.triangle_edges(x, y, topology)
    assert all(len(column) == 5 for column in edges)  # shared diagonal is unique
    contours = impl.marching_triangles(x, y, z, topology, np.array([0.5, 1.5]))
    assert all(len(column) == 2 for column in contours)
    np.testing.assert_array_equal(contours[-1], [0.5, 1.5])


def test_native_delaunay_topology_covers_unstructured_points(impl):
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.5])
    y = np.array([0.0, 0.0, 1.0, 1.0, 0.5])
    topology = impl.delaunay_triangles(x, y)
    assert topology.shape == (4, 3)
    assert set(topology.reshape(-1)) == set(range(5))
    signed_area = (x[topology[:, 1]] - x[topology[:, 0]]) * (
        y[topology[:, 2]] - y[topology[:, 0]]
    ) - (y[topology[:, 1]] - y[topology[:, 0]]) * (x[topology[:, 2]] - x[topology[:, 0]])
    assert np.all(signed_area > 0)


def test_native_delaunay_merges_duplicate_locations_and_bounds_quadratic_work(impl):
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.0])
    y = np.array([0.0, 0.0, 1.0, 1.0, 0.0])
    topology = impl.delaunay_triangles(x, y)
    assert topology.shape == (2, 3)
    with pytest.raises(ValueError, match="limited to 10,000"):
        impl.delaunay_triangles(np.arange(10_001.0), np.arange(10_001.0))


def test_curvilinear_single_row_quad_mesh_has_nonzero_area(impl):
    x = np.array([[0.0, 1.0, 2.0]])
    y = np.array([[0.0, 0.2, 0.0]])
    mesh = impl.quad_mesh_triangles(x, y, np.array([[1.0, 2.0, 3.0]]))
    area2 = np.abs(
        (mesh[2] - mesh[0]) * (mesh[5] - mesh[1]) - (mesh[3] - mesh[1]) * (mesh[4] - mesh[0])
    )
    assert np.all(area2 > 0.0)


def test_sector_triangles_tessellate_pie_and_donut_geometry(impl):
    pie = impl.sector_triangles(np.array([1.0, 2.0, 3.0]))
    assert all(len(column) == 60 for column in pie)
    np.testing.assert_array_equal(np.unique(pie[-1]), [0.0, 1.0, 2.0])
    donut = impl.sector_triangles(
        np.array([1.0, 1.0]),
        explode=np.array([0.0, 0.1]),
        inner_radius=0.5,
        start_degrees=90.0,
        counterclockwise=False,
    )
    assert all(len(column) == 120 for column in donut)
    radius = np.hypot(donut[0], donut[1])
    assert np.isclose(radius.min(), 0.5)


def test_polygon_triangulation_handles_concave_shapes(impl):
    x = np.array([0.0, 2.0, 2.0, 1.0, 0.0])
    y = np.array([0.0, 0.0, 2.0, 1.0, 2.0])
    topology = impl.polygon_triangles(x, y)
    assert topology.shape == (3, 3)
    triangles = impl.indexed_triangles(x, y, topology)
    area = (
        np.abs(
            (triangles[2] - triangles[0]) * (triangles[5] - triangles[1])
            - (triangles[3] - triangles[1]) * (triangles[4] - triangles[0])
        ).sum()
        * 0.5
    )
    assert np.isclose(area, 3.0)


def test_native_spectral_kernels_find_tone_and_correlation_peak(impl):
    sample_rate = 1024.0
    time = np.arange(2048) / sample_rate
    values = np.sin(2 * np.pi * 64.0 * time)
    frequency, real, imag = impl.rfft(values, nfft=256, sample_rate=sample_rate)
    assert frequency[np.argmax(np.hypot(real, imag))] == 64.0
    non_power_frequency, non_power_real, non_power_imag = impl.rfft(
        values, nfft=300, sample_rate=sample_rate
    )
    assert np.isclose(
        non_power_frequency[np.argmax(np.hypot(non_power_real, non_power_imag))],
        64.0,
        atol=sample_rate / 300,
    )
    frequency, pxx, _pyy, _cross_real, _cross_imag = impl.welch_spectra(
        values, nfft=256, noverlap=128, sample_rate=sample_rate
    )
    assert frequency[np.argmax(pxx)] == 64.0
    shifted = np.sin(2 * np.pi * 64.0 * time + 0.4)
    frequency, _pxx, _pyy, _cross_real, cross_imag = impl.welch_spectra(
        values, shifted, nfft=256, noverlap=128, sample_rate=sample_rate
    )
    assert cross_imag[np.flatnonzero(frequency == 64.0)[0]] > 0.0
    power, frequency, segment_time = impl.spectrogram(
        values, nfft=256, noverlap=128, sample_rate=sample_rate
    )
    assert power.shape == (15, 129)
    assert frequency[np.argmax(power[0])] == 64.0
    assert np.all(np.diff(segment_time) > 0)
    lag, correlation = impl.correlation(values, values, max_lags=12)
    assert lag[np.argmax(correlation)] == 0.0
    assert np.isclose(correlation.max(), 1.0)
    delayed = np.roll(values, 5)
    lag, correlation = impl.correlation(values, delayed, max_lags=12)
    assert lag[np.argmax(correlation)] == -5.0
    offset = np.array([10.0, 11.0, 12.0, 13.0])
    lag, correlation = impl.correlation(offset, offset, max_lags=2)
    expected = np.correlate(offset, offset, mode="full")[1:6] / np.dot(offset, offset)
    np.testing.assert_allclose(correlation, expected)


def test_vector_segments_emit_shaft_and_arrowheads_and_skip_invalid(impl):
    x0, x1, y0, y1 = impl.vector_segments(
        np.array([0.0, np.nan]),
        np.array([0.0, 1.0]),
        np.array([2.0, 1.0]),
        np.array([0.0, 1.0]),
    )
    assert len(x0) == len(x1) == len(y0) == len(y1) == 3
    np.testing.assert_allclose([x0[0], y0[0], x1[0], y1[0]], [0.0, 0.0, 2.0, 0.0])
    np.testing.assert_allclose(x0[1:], 2.0)
    np.testing.assert_allclose(y0[1:], 0.0)


def test_weighted_ecdf_native_sort_aggregation(impl):
    x, cumulative = impl.weighted_ecdf(
        np.array([3.0, 1.0, 2.0, 2.0, np.nan]),
        np.array([4.0, 1.0, 2.0, 3.0, 99.0]),
    )
    np.testing.assert_array_equal(x, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(cumulative, [0.1, 0.6, 1.0])


def test_streamlines_integrate_regular_grid_in_native_core(impl):
    x = np.linspace(-1.0, 1.0, 12)
    y = np.linspace(-1.0, 1.0, 10)
    xx, yy = np.meshgrid(x, y)
    x0, x1, y0, y1 = impl.streamlines(x, y, -yy, xx, density=0.8, max_steps=200)
    assert 0 < len(x0) == len(x1) == len(y0) == len(y1)
    assert np.isfinite(np.concatenate((x0, x1, y0, y1))).all()
    assert np.max(np.abs(x1)) <= 1.0
    assert np.max(np.abs(y1)) <= 1.0


# -- zone maps (§22) ---------------------------------------------------------


def test_zone_maps_stats(impl):
    rng = np.random.default_rng(7)
    data = rng.normal(100.0, 5.0, 200_000)
    data[::1000] = np.nan
    mins, maxs, counts, nulls, sums, sum_sqs, positive_mins, positive_maxs = impl.zone_maps(
        data, 65_536
    )
    assert len(mins) == 4  # ceil(200k / 64k)
    valid = data[~np.isnan(data)]
    assert int(counts.sum()) == len(valid)
    assert int(nulls.sum()) == 200
    assert np.isclose(mins.min(), valid.min())
    assert np.isclose(maxs.max(), valid.max())
    assert np.isclose(sums.sum(), valid.sum())
    assert np.isclose(sum_sqs.sum(), (valid * valid).sum())
    positive = valid[valid > 0]
    assert np.isclose(positive_mins[counts > 0].min(), positive.min())
    assert np.isclose(positive_maxs[counts > 0].max(), positive.max())


def test_zone_maps_pair_is_bit_identical_to_separate_columns(impl):
    rng = np.random.default_rng(17)
    x = rng.normal(size=1_100_123)
    y = rng.normal(size=1_100_123)
    x[::997] = np.nan
    y[::991] = np.inf
    separate = (impl.zone_maps(x), impl.zone_maps(y))
    paired = impl.zone_maps_pair(x, y)
    for got_column, expected_column in zip(paired, separate, strict=True):
        for got, expected in zip(got_column, expected_column, strict=True):
            np.testing.assert_array_equal(got, expected)

    empty = impl.zone_maps_pair(x[:0], y[:0])
    assert all(len(field) == 0 for column in empty for field in column)
    with pytest.raises(ValueError, match="equal length"):
        impl.zone_maps_pair(x, y[:-1])


def test_zone_maps_autorange_matches_full_scan(impl):
    rng = np.random.default_rng(11)
    data = rng.uniform(-1e6, 1e6, 100_001)
    mins, maxs, counts, *_ = impl.zone_maps(data, 4096)
    assert np.isclose(mins[counts > 0].min(), data.min())
    assert np.isclose(maxs[counts > 0].max(), data.max())


def test_zone_maps_empty(impl):
    out = impl.zone_maps(np.array([], dtype=np.float64))
    assert all(len(a) == 0 for a in out)


def test_zone_maps_huge_values_do_not_warn(impl):
    data = np.array([1.0e308, np.nextafter(1.0e308, np.inf)], dtype=np.float64)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", RuntimeWarning)
        mins, maxs, counts, nulls, sums, sum_sqs, positive_mins, positive_maxs = impl.zone_maps(
            data, 65_536
        )
    runtime_warnings = [w for w in seen if issubclass(w.category, RuntimeWarning)]
    assert runtime_warnings == []
    assert int(counts.sum()) == 2
    assert int(nulls.sum()) == 0
    assert np.isfinite(mins[0])
    assert np.isfinite(maxs[0])
    assert positive_mins[0] == 1.0e308
    assert positive_maxs[0] == np.nextafter(1.0e308, np.inf)
    assert np.isinf(sums[0])
    assert np.isinf(sum_sqs[0])


# -- M4 decimation (§5 Tier 1) ----------------------------------------------


def test_m4_preserves_spikes(impl):
    n = 100_000
    x = np.arange(n, dtype=np.float64)
    y = np.sin(x * 0.001)
    y[12_345] = 50.0
    y[67_890] = -50.0
    idx = impl.m4_indices(x, y, 0.0, float(n), 1000)
    assert 12_345 in idx
    assert 67_890 in idx
    assert len(idx) <= 4000  # ≤ 4 points per bucket
    # Rendered extremes are exact: decimated min/max == full min/max.
    assert y[idx].max() == y.max()
    assert y[idx].min() == y.min()


def test_m4_first_last_preserved(impl):
    n = 50_000
    x = np.arange(n, dtype=np.float64)
    y = np.cos(x * 0.01)
    idx = impl.m4_indices(x, y, 0.0, float(n), 512)
    assert idx[0] == 0
    assert idx[-1] == n - 1
    assert np.all(np.diff(idx.astype(np.int64)) > 0)  # sorted, unique


def test_m4_visible_window_only(impl):
    n = 10_000
    x = np.arange(n, dtype=np.float64)
    y = x * 2.0
    idx = impl.m4_indices(x, y, 2_500.0, 5_000.0, 64)
    assert len(idx) > 0
    assert idx.min() >= 2_500
    assert idx.max() < 5_000


def test_m4_skips_nan(impl):
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([1.0, np.nan, 5.0, 2.0])
    idx = impl.m4_indices(x, y, 0.0, 4.0, 1)
    assert 1 not in idx
    assert 2 in idx


def test_m4_empty_window(impl):
    x = np.arange(100, dtype=np.float64)
    y = x.copy()
    idx = impl.m4_indices(x, y, 1000.0, 2000.0, 16)
    assert len(idx) == 0


def test_m4_invalid_args(impl):
    x = np.arange(10, dtype=np.float64)
    with pytest.raises(ValueError):
        impl.m4_indices(x, x, 5.0, 5.0, 16)
    with pytest.raises(ValueError):
        impl.m4_indices(x, x, 0.0, 10.0, 0)
    with pytest.raises(ValueError):
        impl.m4_indices(x, x[:5], 0.0, 10.0, 16)


# -- min/max ------------------------------------------------------------------


def test_min_max(impl):
    assert impl.min_max(np.array([np.nan, 2.0, -1.0])) == (-1.0, 2.0)
    assert impl.min_max(np.array([np.nan])) is None
    assert impl.min_max(np.array([], dtype=np.float64)) is None


# -- sorted-ingest predicate --------------------------------------------------


def test_is_sorted_matches_numpy_diff_predicate(impl):
    cases = [
        np.array([], dtype=np.float64),
        np.array([3.0]),
        np.array([np.nan]),
        np.array([1.0, 1.0, 2.0]),
        np.array([-np.inf, 0.0, np.inf]),
        np.array([2.0, 1.0]),
        np.array([1.0, np.nan, 3.0]),
        np.array([1.0, 2.0, np.nan]),
        np.array([np.nan, 1.0, 2.0]),
        np.array([0.0, 1.0, 5.0, 4.0, 9.0]),
        np.arange(10_000, dtype=np.float64),
    ]
    for data in cases:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            expected = bool(np.all(np.diff(data) >= 0))
        assert impl.is_sorted(data) is expected, data


def test_is_sorted_accepts_convertible_input(impl):
    assert impl.is_sorted(np.arange(8, dtype=np.float32)) is True
    assert impl.is_sorted([0, 1, 2]) is True
    assert impl.is_sorted([2, 1]) is False


# -- 2D density binning (§5 Tier 2) ------------------------------------------


def test_bin_2d_conserves_and_places(impl):
    x = np.array([0.25, 0.75, 0.25, 0.75])
    y = np.array([0.25, 0.25, 0.75, 0.75])
    grid = impl.bin_2d(x, y, 0.0, 1.0, 0.0, 1.0, 2, 2)
    assert grid.shape == (2, 2)
    assert grid.sum() == 4.0
    # row 0 = bottom (GL convention)
    assert grid[0, 0] == 1.0 and grid[1, 1] == 1.0


def test_bin_2d_skips_nan_and_outside(impl):
    x = np.array([0.5, np.nan, 5.0, -1.0])
    y = np.array([0.5, 0.5, 0.5, 0.5])
    grid = impl.bin_2d(x, y, 0.0, 1.0, 0.0, 1.0, 1, 1)
    assert grid[0, 0] == 1.0


def test_bin_2d_hotspot(impl):
    x = np.concatenate([np.full(1000, 0.1), np.array([0.9])])
    y = np.concatenate([np.full(1000, 0.1), np.array([0.9])])
    grid = impl.bin_2d(x, y, 0.0, 1.0, 0.0, 1.0, 2, 2)
    assert grid.max() == 1000.0
    assert grid.sum() == 1001.0


def test_bin_2d_invalid_args(impl):
    x = np.arange(10.0)
    with pytest.raises(ValueError):
        impl.bin_2d(x, x, 0.0, 0.0, 0.0, 1.0, 4, 4)
    with pytest.raises(ValueError):
        impl.bin_2d(x, x, 0.0, 1.0, 0.0, 1.0, 0, 4)


def test_marching_squares_extracts_segments(impl):
    z = np.array([[0.0, 1.0], [1.0, 0.0]])
    x0, x1, y0, y1, emitted_levels = impl.marching_squares(
        z, np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([0.5])
    )
    np.testing.assert_allclose(x0, [0.5, 0.5])
    np.testing.assert_allclose(x1, [1.0, 0.0])
    np.testing.assert_allclose(y0, [0.0, 1.0])
    np.testing.assert_allclose(y1, [0.5, 0.5])
    np.testing.assert_allclose(emitted_levels, [0.5, 0.5])


def test_marching_squares_resolves_asymmetric_saddles(impl):
    x0, x1, y0, y1, emitted_levels = impl.marching_squares(
        np.array([[3.0, 0.0], [0.0, 1.0]]),
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0]),
        np.array([0.5]),
    )
    # The high-valued diagonal dominates, so the contour must join the bottom
    # crossing to the right crossing and the top crossing to the left one.
    np.testing.assert_allclose(x0, [5.0 / 6.0, 0.5])
    np.testing.assert_allclose(x1, [1.0, 0.0])
    np.testing.assert_allclose(y0, [0.0, 1.0])
    np.testing.assert_allclose(y1, [0.5, 5.0 / 6.0])
    np.testing.assert_allclose(emitted_levels, [0.5, 0.5])


def test_marching_squares_skips_nonfinite_cells_and_empty_levels(impl):
    z = np.array([[np.nan, 1.0], [1.0, 0.0]])
    result = impl.marching_squares(z, np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([0.5]))
    assert all(len(values) == 0 for values in result)
    empty = impl.marching_squares(
        np.zeros((2, 2)), np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([])
    )
    assert all(len(values) == 0 for values in empty)


# -- chart-prep kernels -------------------------------------------------------


def test_factorize_fixed_returns_first_seen_codes_and_validates_shape(impl):
    values = np.array(["beta", "alpha", "beta", "gamma", "alpha"], dtype="U5")
    codes, unique = impl.factorize_fixed(values)
    np.testing.assert_array_equal(codes, [0, 1, 0, 2, 1])
    np.testing.assert_array_equal(unique, [0, 1, 3])
    compact = impl.factorize_fixed_u8(values)
    assert compact is not None
    compact_codes, compact_unique = compact
    np.testing.assert_array_equal(compact_codes, codes)
    np.testing.assert_array_equal(compact_unique, unique)
    counted = impl.factorize_fixed_u8_counts(values)
    assert counted is not None
    counted_codes, counted_unique, counts = counted
    np.testing.assert_array_equal(counted_codes, codes)
    np.testing.assert_array_equal(counted_unique, unique)
    np.testing.assert_array_equal(counts, [2, 2, 1])
    assert impl.factorize_fixed_u8(np.asarray([f"v{i}" for i in range(257)])) is None
    assert impl.factorize_fixed_u8_counts(np.asarray([f"v{i}" for i in range(257)])) is None

    impl.remap_u8(compact_codes, np.array([2, 0, 1], dtype=np.uint8))
    np.testing.assert_array_equal(compact_codes, [2, 0, 2, 1, 0])
    impl.remap_u8(np.empty(0, dtype=np.uint8), np.empty(0, dtype=np.uint8))
    with pytest.raises(ValueError, match="non-object 1-D"):
        impl.factorize_fixed(values.astype(object))
    with pytest.raises(ValueError, match="non-object 1-D"):
        impl.factorize_fixed(values.reshape(1, -1))
    with pytest.raises(ValueError, match="outside the mapping"):
        impl.remap_u8(np.array([2], dtype=np.uint8), np.array([0, 1], dtype=np.uint8))


def test_factorize_unicode1_direct_table_matches_fixed_records_and_endian(impl):
    values = np.array(["β", "a", "β", "", "é"], dtype="U1")
    expected = impl.factorize_fixed_u8_counts(values)
    actual = impl.factorize_unicode1_u8_counts(values)
    assert expected is not None and actual is not None
    for got, want in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(got, want)

    nonnative = values.astype(values.dtype.newbyteorder("S"))
    swapped = impl.factorize_unicode1_u8_counts(nonnative)
    assert swapped is not None
    for got, want in zip(swapped, expected, strict=True):
        np.testing.assert_array_equal(got, want)

    with pytest.raises(ValueError, match="Unicode U1"):
        impl.factorize_unicode1_u8_counts(values.astype("U2"))


def test_histogram_uniform_matches_numpy_counts(impl):
    x = np.array([0.0, 0.2, 0.9, 1.0, 1.1, np.nan, np.inf])
    counts, edges = impl.histogram_uniform(x, 0.0, 1.0, 4)
    expect_counts, expect_edges = np.histogram(x[np.isfinite(x)], bins=4, range=(0.0, 1.0))
    np.testing.assert_allclose(counts, expect_counts)
    np.testing.assert_allclose(edges, expect_edges)


def test_histogram_uniform_density(impl):
    x = np.array([0.0, 0.2, 0.8, 1.0])
    counts, _edges = impl.histogram_uniform(x, 0.0, 1.0, 2, density=True)
    expect, _ = np.histogram(x, bins=2, range=(0.0, 1.0), density=True)
    np.testing.assert_allclose(counts, expect)


def test_normalize_f32_modes(impl):
    x = np.array([-1.0, 0.0, 5.0, 10.0, 11.0, np.nan, np.inf])
    zero = impl.normalize_f32(x, (0.0, 10.0), nonfinite="zero")
    np.testing.assert_allclose(zero, [0.0, 0.0, 0.5, 1.0, 1.0, 0.0, 0.0])
    nan = impl.normalize_f32(x, (0.0, 10.0), nonfinite="nan")
    np.testing.assert_allclose(nan[:5], [0.0, 0.0, 0.5, 1.0, 1.0])
    assert np.isnan(nan[5]) and np.isnan(nan[6])


def test_normalize_f32_rejects_unknown_nonfinite_mode(impl):
    with pytest.raises(ValueError, match="nonfinite"):
        impl.normalize_f32(np.array([1.0]), (0.0, 1.0), nonfinite="drop")


def test_chart_prep_kernels_reject_nonfinite_or_degenerate_domains(impl):
    x = np.arange(4.0)
    with pytest.raises(ValueError):
        impl.m4_indices(x, x, 0.0, np.inf, 8)
    with pytest.raises(ValueError):
        impl.bin_2d(x, x, 0.0, np.inf, 0.0, 1.0, 4, 4)
    with pytest.raises(ValueError):
        impl.histogram_uniform(x, 0.0, np.inf, 4)
    with pytest.raises(ValueError):
        impl.normalize_f32(x, (1.0, 1.0))
    with pytest.raises(ValueError):
        impl.range_indices(x, x, 0.0, np.inf, 0.0, 1.0)
    with pytest.raises(ValueError):
        impl.local_log_density(x, x, 0.0, 1.0, 0.0, np.inf, 4, 4)


def test_kernel_wrappers_reject_non_1d_inputs_before_native_boundary(impl):
    arr = np.arange(6.0).reshape(2, 3)
    one = np.arange(6.0)
    with pytest.raises(ValueError, match="1-D"):
        impl.zone_maps(arr)
    with pytest.raises(ValueError, match="1-D"):
        impl.encode_f32(arr, 0.0)
    with pytest.raises(ValueError, match="1-D"):
        impl.min_max(arr)
    with pytest.raises(ValueError, match="1-D"):
        impl.histogram_uniform(arr, 0.0, 6.0, 3)
    with pytest.raises(ValueError, match="1-D"):
        impl.normalize_f32(arr, (0.0, 6.0))
    with pytest.raises(ValueError, match="1-D"):
        impl.m4_indices(arr, arr, 0.0, 6.0, 4)
    with pytest.raises(ValueError, match="1-D"):
        impl.bin_2d(arr, arr, 0.0, 6.0, 0.0, 6.0, 4, 4)
    with pytest.raises(ValueError, match="1-D"):
        impl.range_indices(arr, one, 0.0, 6.0, 0.0, 6.0)
    with pytest.raises(ValueError, match="1-D"):
        impl.local_log_density(one, arr, 0.0, 6.0, 0.0, 6.0, 4, 4)
    with pytest.raises(ValueError, match="2-D"):
        impl.marching_squares(one, np.arange(6.0), np.arange(2.0), np.array([0.5]))


def test_kernel_wrappers_reject_bad_integer_dimensions(impl):
    x = np.arange(4.0)
    with pytest.raises(ValueError, match="chunk_size"):
        impl.zone_maps(x, 1.5)
    with pytest.raises(ValueError, match="n_buckets"):
        impl.m4_indices(x, x, 0.0, 4.0, 1.5)
    with pytest.raises(ValueError, match="n_buckets"):
        impl.m4_indices(x, x, 0.0, 4.0, True)
    with pytest.raises(ValueError, match="w"):
        impl.bin_2d(x, x, 0.0, 4.0, 0.0, 4.0, True, 4)
    with pytest.raises(ValueError, match="h"):
        impl.local_log_density(x, x, 0.0, 4.0, 0.0, 4.0, 4, 1.5)
    with pytest.raises(ValueError, match="n_bins"):
        impl.histogram_uniform(x, 0.0, 4.0, True)


def test_kernel_wrappers_reject_oversized_allocation_dimensions(impl):
    x = np.arange(4.0)
    too_many = MAX_SCREEN_DIM + 1
    with pytest.raises(ValueError, match="n_buckets"):
        impl.m4_indices(x, x, 0.0, 4.0, too_many)
    with pytest.raises(ValueError, match="w"):
        impl.bin_2d(x, x, 0.0, 4.0, 0.0, 4.0, too_many, 4)
    with pytest.raises(ValueError, match="h"):
        impl.bin_2d(x, x, 0.0, 4.0, 0.0, 4.0, 4, too_many)
    with pytest.raises(ValueError, match="n_bins"):
        impl.histogram_uniform(x, 0.0, 4.0, too_many)
    with pytest.raises(ValueError, match="w"):
        impl.local_log_density(x, x, 0.0, 4.0, 0.0, 4.0, too_many, 4)


def test_size_sentinel_detection_matches_platform_usize_width(monkeypatch):
    """usize::MAX error sentinels must be detected at the platform c_size_t width.

    On 32-bit targets (armv7 / win32 / wasm32 — all shipped wheels) the Rust
    sentinel arrives as 2**32-1. A comparison hard-coded to 2**64-1 never
    matches there, so an error return — including a panic converted by the
    ffi_guard shield — would be sliced as valid data. Simulate the 32-bit ABI
    by narrowing the module sentinel and stubbing each size-returning entry
    point; every wrapper must consult the shared constant and raise.
    """
    import ctypes

    from xy import _native

    assert ctypes.c_size_t(-1).value == _native._USIZE_MAX
    sentinel = 2**32 - 1
    monkeypatch.setattr(_native, "_USIZE_MAX", sentinel)
    x = np.arange(8.0)
    cases = [
        ("xy_zone_maps", lambda: _native.zone_maps(x, 4)),
        ("xy_m4_indices", lambda: _native.m4_indices(x, x, 0.0, 8.0, 2)),
        ("xy_bin_2d_indices", lambda: _native.bin_2d_indices(x, x, 0.0, 8.0, 0.0, 8.0, 4, 4)),
        ("xy_histogram_uniform", lambda: _native.histogram_uniform(x, 0.0, 8.0, 4)),
        ("xy_range_indices", lambda: _native.range_indices(x, x, 0.0, 8.0, 0.0, 8.0)),
    ]
    for symbol, call in cases:
        monkeypatch.setattr(_native._lib, symbol, lambda *args, _s=sentinel: _s)
        with pytest.raises(ValueError):
            call()


def test_encode_f32_rejects_nonfinite_offset_or_scale(impl):
    x = np.arange(4.0)
    with pytest.raises(ValueError, match="offset"):
        impl.encode_f32(x, np.inf)
    with pytest.raises(ValueError, match="scale"):
        impl.encode_f32(x, 0.0, np.nan)


def test_kernel_float_parameters_reject_bool_coercion(impl):
    x = np.arange(4.0)
    with pytest.raises(ValueError, match="offset"):
        impl.encode_f32(x, True)
    with pytest.raises(ValueError, match="scale"):
        impl.encode_f32(x, 0.0, np.bool_(True))
    with pytest.raises(ValueError, match="x range"):
        impl.m4_indices(x, x, False, 4.0, 4)
    with pytest.raises(ValueError, match="x range"):
        impl.bin_2d(x, x, 0.0, True, 0.0, 4.0, 4, 4)
    with pytest.raises(ValueError, match="y range"):
        impl.bin_2d(x, x, 0.0, 4.0, np.bool_(False), 4.0, 4, 4)
    with pytest.raises(ValueError, match="histogram range"):
        impl.histogram_uniform(x, False, 4.0, 4)
    with pytest.raises(ValueError, match="domain"):
        impl.normalize_f32(x, (False, 4.0))
    with pytest.raises(ValueError, match="x range"):
        impl.range_indices(x, x, False, 4.0, 0.0, 4.0)
    with pytest.raises(ValueError, match="y range"):
        impl.local_log_density(x, x, 0.0, 4.0, False, 4.0, 4, 4)


def test_range_indices(impl):
    x = np.array([0.0, 1.0, 2.0, 3.0, np.nan])
    y = np.array([0.0, 1.5, 2.5, 4.0, 1.0])
    idx = impl.range_indices(x, y, 1.0, 3.0, 1.0, 3.0)
    np.testing.assert_array_equal(idx, [1, 2])


def test_valid_indices_f64_all_valid_filtered_and_positive(impl):
    x = np.array([1.0, 2.0, np.nan, 4.0, -5.0, 6.0])
    y = np.array([1.0, np.inf, 3.0, -4.0, 5.0, 6.0])
    np.testing.assert_array_equal(impl.valid_indices_f64((x, y)), [0, 3, 4, 5])
    np.testing.assert_array_equal(impl.valid_indices_f64((x, y), positive_columns=(1,)), [0, 4, 5])
    assert impl.valid_indices_f64((np.arange(10.0), np.arange(10.0))) is None
    assert impl.valid_indices_f64((np.array([]), np.array([]))) is None
    with pytest.raises(ValueError, match="equal length"):
        impl.valid_indices_f64((np.arange(2.0), np.arange(3.0)))
    with pytest.raises(ValueError, match="positive column"):
        impl.valid_indices_f64((x, y), positive_columns=(2,))


def test_bin_2d_indices_matches_separate_kernels(impl):
    rng = np.random.default_rng(5)
    x = rng.uniform(-100, 100, 50_000)
    y = rng.uniform(-100, 100, 50_000)
    x[::971] = np.nan  # NaN skipped by both outputs
    x[::1013] = 95.0  # exact hi edge: indexed (inclusive) but not binned (half-open)
    args = (-95.0, 95.0, -80.0, 80.0, 64, 48)

    grid, idx = impl.bin_2d_indices(x, y, *args)
    grid_ref = impl.bin_2d(x, y, *args)
    idx_ref = impl.range_indices(x, y, *args[:4])

    assert grid.dtype == np.float32 and grid.shape == (48, 64)
    np.testing.assert_array_equal(grid, grid_ref)
    np.testing.assert_array_equal(idx, idx_ref)


def test_bin_2d_indices_edge_point_indexed_but_not_binned(impl):
    grid, idx = impl.bin_2d_indices(
        np.array([1.0, 0.5]), np.array([0.5, 0.5]), 0.0, 1.0, 0.0, 1.0, 2, 2
    )
    np.testing.assert_array_equal(idx, [0, 1])
    assert float(grid.sum()) == 1.0  # only the interior point lands in a cell


def test_bin_2d_indices_empty_and_validation(impl):
    grid, idx = impl.bin_2d_indices(np.array([]), np.array([]), 0.0, 1.0, 0.0, 1.0, 2, 2)
    assert grid.shape == (2, 2) and float(grid.sum()) == 0.0 and idx.shape == (0,)
    with pytest.raises(ValueError, match="equal length"):
        impl.bin_2d_indices(np.array([1.0]), np.array([]), 0.0, 1.0, 0.0, 1.0, 2, 2)
    with pytest.raises(ValueError, match="range"):
        impl.bin_2d_indices(np.array([1.0]), np.array([1.0]), 1.0, 0.0, 0.0, 1.0, 2, 2)


def test_bin_2d_sample_range_matches_separate_kernels_and_retries(impl):
    from xy import lod

    rng = np.random.default_rng(17)
    x = rng.uniform(-100.0, 100.0, 100_123)
    y = rng.uniform(-100.0, 100.0, 100_123)
    x[::997] = np.nan
    args = (-95.0, 95.0, -80.0, 80.0, 64, 48)
    seed = 23
    threshold = int(lod._sample_threshold(0.0075))

    grid, rows = impl.bin_2d_sample_range(x, y, *args, seed, threshold, 1)
    np.testing.assert_array_equal(grid, impl.bin_2d(x, y, *args))
    np.testing.assert_array_equal(
        rows,
        impl.sample_range_indices(len(x), seed, threshold, 2_000),
    )


def test_bin_2d_sample_range_empty_and_validation(impl):
    grid, rows = impl.bin_2d_sample_range(
        np.array([]), np.array([]), 0.0, 1.0, 0.0, 1.0, 2, 2, 0, 0, 0
    )
    assert grid.shape == (2, 2) and float(grid.sum()) == 0.0 and rows.shape == (0,)
    with pytest.raises(ValueError, match="equal length"):
        impl.bin_2d_sample_range(np.array([1.0]), np.array([]), 0.0, 1.0, 0.0, 1.0, 2, 2, 0, 0, 0)
    with pytest.raises(ValueError, match="threshold"):
        impl.bin_2d_sample_range(
            np.array([1.0]), np.array([1.0]), 0.0, 2.0, 0.0, 2.0, 2, 2, 0, -1, 0
        )


def test_bin_2d_counted_stratified_sample_matches_separate_kernels(impl):
    rng = np.random.default_rng(117)
    n = 100_123
    x = rng.uniform(-100.0, 100.0, n)
    y = rng.uniform(-100.0, 100.0, n)
    groups = (np.arange(n, dtype=np.uint32) % 7).astype(np.uint8)
    groups[::25_000] = 7
    counts = np.bincount(groups, minlength=8).astype(np.uint64)
    args = (-95.0, 95.0, -80.0, 80.0, 64, 48)

    grid, rows = impl.bin_2d_stratified_sample_range_u8_counted(
        x, y, groups, counts, *args, 31, 0.0001, 3, 1
    )
    np.testing.assert_array_equal(grid, impl.bin_2d(x, y, *args))
    np.testing.assert_array_equal(
        rows,
        impl.stratified_sample_range_u8(groups, 8, 31, 0.0001, 3, 1, counts=counts),
    )

    with pytest.raises(ValueError, match="arguments or codes"):
        impl.bin_2d_stratified_sample_range_u8_counted(
            x, y, groups, counts + 1, *args, 31, 0.0001, 3, 1
        )


def test_sample_mask_matches_numpy_hash_reference(impl):
    # lod.hash_row_ids is the pure-NumPy SplitMix64 reference; the fused native
    # mask must be bit-identical to hashing + thresholding through it.
    from xy import lod

    rng = np.random.default_rng(11)
    ids = rng.integers(0, 2**63, size=100_000).astype(np.uint64)
    for seed, fraction in [(0, 0.5), (7, 0.001), (2**40, 0.25)]:
        threshold = lod._sample_threshold(fraction)
        ref = lod.hash_row_ids(ids, seed=seed) <= threshold
        got = impl.sample_mask(ids, seed, int(threshold))
        assert got.dtype == np.bool_
        np.testing.assert_array_equal(got, ref)


def test_sample_mask_u32_ids_match_widened_u64(impl):
    from xy import lod

    rng = np.random.default_rng(13)
    ids32 = rng.integers(0, 2**32, size=100_000, dtype=np.uint64).astype(np.uint32)
    for seed, fraction in [(0, 0.5), (7, 0.001), (2**40, 0.25)]:
        threshold = int(lod._sample_threshold(fraction))
        np.testing.assert_array_equal(
            impl.sample_mask(ids32, seed, threshold),
            impl.sample_mask(ids32.astype(np.uint64), seed, threshold),
        )


def test_density_log_u8_matches_wire_reference(impl):
    grid = np.array([0, 1, 2, 3, 9, 100, 10_000], dtype=np.float32)
    encoded, maximum = impl.density_log_u8(grid)
    expected = np.round(255.0 * np.log1p(grid.astype(np.float64)) / np.log1p(10_000.0)).astype(
        np.uint8
    )
    expected[(grid > 0) & (expected == 0)] = 1
    assert maximum == 10_000.0
    np.testing.assert_array_equal(encoded, expected)
    zeros, maximum = impl.density_log_u8(np.zeros((2, 3), dtype=np.float32))
    assert maximum == 0.0
    np.testing.assert_array_equal(zeros, 0)


def test_sample_mask_edges(impl):
    ids = np.arange(64, dtype=np.uint64)
    assert impl.sample_mask(ids[:0], 0, 2**63).shape == (0,)
    assert impl.sample_mask(ids, 0, 2**64 - 1).all()  # threshold=max keeps all
    assert not impl.sample_mask(ids, 0, 0).any()  # only exact-zero hashes
    with pytest.raises(ValueError, match="one-dimensional"):
        impl.sample_mask(ids.reshape(8, 8), 0, 1)


def test_stratified_sample_mask_matches_numpy_reference(impl):
    # Direct port of the per-category NumPy loop the fused kernel replaced:
    # hash-threshold per category plus an argpartition floor fill. Distinct ids
    # can't tie on hashes (SplitMix64 is a bijection), so equality is exact.
    from xy import lod

    rng = np.random.default_rng(3)
    n = 50_000
    ids = rng.permutation(n).astype(np.uint64)
    groups = rng.choice(4, size=n, p=[0.9, 0.06, 0.039, 0.001]).astype(np.uint32)

    def reference(fraction: float, min_count: int) -> np.ndarray:
        hashes = lod.hash_row_ids(ids, seed=9)
        keep = np.zeros(n, dtype=bool)
        counts = np.bincount(groups, minlength=4)
        for group, count in enumerate(counts):
            idx = np.flatnonzero(groups == group)
            group_fraction = min(1.0, fraction * float(np.sqrt(n / float(count))))
            group_keep = hashes[idx] <= lod._sample_threshold(group_fraction)
            floor = min(min_count, len(idx))
            if floor and int(group_keep.sum()) < floor:
                winners = np.argpartition(hashes[idx], floor - 1)[:floor]
                group_keep[winners] = True
            keep[idx] = group_keep
        return keep

    for fraction, min_count in [(1 / 4096, 1), (1 / 64, 5), (0.5, 0)]:
        got = impl.stratified_sample_mask(ids, groups, 4, 9, fraction, min_count)
        assert got.dtype == np.bool_
        np.testing.assert_array_equal(got, reference(fraction, min_count))


def test_stratified_sample_mask_u32_ids_match_widened_u64(impl):
    rng = np.random.default_rng(17)
    n = 50_000
    ids32 = rng.permutation(n).astype(np.uint32)
    groups = rng.choice(4, size=n, p=[0.9, 0.06, 0.039, 0.001]).astype(np.uint32)
    for fraction, min_count in [(1 / 4096, 1), (1 / 64, 5), (0.5, 0)]:
        np.testing.assert_array_equal(
            impl.stratified_sample_mask(ids32, groups, 4, 9, fraction, min_count),
            impl.stratified_sample_mask(ids32.astype(np.uint64), groups, 4, 9, fraction, min_count),
        )


def test_stratified_sample_mask_edges(impl):
    ids = np.arange(64, dtype=np.uint64)
    groups = (ids % 4).astype(np.uint32)
    assert impl.stratified_sample_mask(ids[:0], groups[:0], 4, 0, 0.5, 1).shape == (0,)
    with pytest.raises(ValueError, match="equal length"):
        impl.stratified_sample_mask(ids, groups[:10], 4, 0, 0.5, 1)
    with pytest.raises(ValueError, match="fraction"):
        impl.stratified_sample_mask(ids, groups, 4, 0, 0.0, 1)
    with pytest.raises(ValueError, match="min_count"):
        impl.stratified_sample_mask(ids, groups, 4, 0, 0.5, -1)
    with pytest.raises(ValueError, match="n_groups"):
        impl.stratified_sample_mask(ids, groups, 0, 0, 0.5, 1)
    # Out-of-range group codes are rejected by the native side, not clamped.
    bad = groups.copy()
    bad[7] = 9
    with pytest.raises(ValueError, match="n_groups"):
        impl.stratified_sample_mask(ids, bad, 4, 0, 0.5, 1)


def test_stratified_sample_range_u8_matches_materialized_mask(impl):
    n = (1 << 20) + 137
    ids = np.arange(n, dtype=np.uint64)
    groups = np.zeros(n, dtype=np.uint8)
    groups[::10] = 1
    groups[::1000] = 2
    groups[::100_000] = 3
    fraction = 1.0 / 4096.0
    mask = impl.stratified_sample_mask(ids, groups.astype(np.uint32), 4, 31, fraction, 3)
    expected = np.flatnonzero(mask).astype(np.uint32)

    # Deliberately tiny to exercise the exact-count retry contract.
    actual = impl.stratified_sample_range_u8(groups, 4, 31, fraction, 3, 1)
    counts = np.bincount(groups, minlength=4).astype(np.uint64)
    counted = impl.stratified_sample_range_u8(groups, 4, 31, fraction, 3, 1, counts=counts)

    assert actual.dtype == np.uint32
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(counted, expected)


def test_stratified_sample_range_u8_validation(impl):
    groups = np.arange(8, dtype=np.uint8) % 2
    assert impl.stratified_sample_range_u8(groups[:0], 2, 0, 0.5, 1, 0).shape == (0,)
    with pytest.raises(ValueError, match="uint8"):
        impl.stratified_sample_range_u8(groups.astype(np.uint32), 2, 0, 0.5, 1, 8)
    with pytest.raises(ValueError, match="n_groups"):
        impl.stratified_sample_range_u8(groups, 257, 0, 0.5, 1, 8)
    with pytest.raises(ValueError, match="fraction"):
        impl.stratified_sample_range_u8(groups, 2, 0, 0.0, 1, 8)
    bad = groups.copy()
    bad[3] = 2
    with pytest.raises(ValueError, match="group code"):
        impl.stratified_sample_range_u8(bad, 2, 0, 0.5, 1, 8)
    with pytest.raises(ValueError, match="counts"):
        impl.stratified_sample_range_u8(
            groups, 2, 0, 0.5, 1, 8, counts=np.array([7, 0], dtype=np.uint64)
        )


def test_local_log_density_shape_and_range(impl):
    x = np.array([0.1, 0.1, 0.1, 0.9], dtype=np.float64)
    y = np.array([0.1, 0.1, 0.1, 0.9], dtype=np.float64)
    d = impl.local_log_density(x, y, 0.0, 1.0, 0.0, 1.0, 2, 2)
    assert d.dtype == np.float32
    assert d.shape == x.shape
    assert d.min() >= 0.0 and d.max() <= 1.0
    assert d[0] == d[1] == d[2]
    assert d[0] > d[3]


def test_chart_prep_kernels_handle_empty_inputs(impl):
    x = np.array([], dtype=np.float64)
    counts, edges = impl.histogram_uniform(x, 0.0, 1.0, 4)
    np.testing.assert_array_equal(counts, np.zeros(4))
    np.testing.assert_allclose(edges, np.linspace(0.0, 1.0, 5))
    np.testing.assert_array_equal(impl.normalize_f32(x, (0.0, 1.0)), np.array([], dtype=np.float32))
    np.testing.assert_array_equal(
        impl.range_indices(x, x, 0.0, 1.0, 0.0, 1.0), np.array([], dtype=np.uint32)
    )
    np.testing.assert_array_equal(
        impl.local_log_density(x, x, 0.0, 1.0, 0.0, 1.0, 4, 4), np.array([], dtype=np.float32)
    )


def test_local_log_density_does_not_clamp_outside_window(impl):
    x = np.array([0.1, 0.1, 2.0, 0.5], dtype=np.float64)
    y = np.array([0.1, 0.1, 0.1, np.nan], dtype=np.float64)
    d = impl.local_log_density(x, y, 0.0, 1.0, 0.0, 1.0, 2, 2)
    assert d[0] > 0.0 and d[1] > 0.0
    assert d[2] == 0.0
    assert d[3] == 0.0


def test_pyramid_wrappers_reject_invalid_public_arguments(impl):
    x = np.arange(8.0, dtype=np.float64)
    short = np.arange(7.0, dtype=np.float64)

    with pytest.raises(ValueError, match="equal length"):
        impl.pyramid_build(x, short, 0.0, 8.0, 0.0, 8.0, 4)
    with pytest.raises(ValueError, match="base_dim"):
        impl.pyramid_build(x, x, 0.0, 8.0, 0.0, 8.0, True)
    with pytest.raises(ValueError, match="power-of-two"):
        impl.pyramid_build(x, x, 0.0, 8.0, 0.0, 8.0, 3)
    with pytest.raises(ValueError, match="base_dim"):
        impl.pyramid_build(x, x, 0.0, 8.0, 0.0, 8.0, MAX_SCREEN_DIM + 1)
    with pytest.raises(ValueError, match="x range"):
        impl.pyramid_build(x, x, False, 8.0, 0.0, 8.0, 4)
    with pytest.raises(ValueError, match="y range"):
        impl.pyramid_build(x, x, 0.0, 8.0, 0.0, np.nan, 4)
    assert impl.pyramid_build(x[:0], x[:0], 0.0, 8.0, 0.0, 8.0, 4) == 0

    handle = impl.pyramid_build(x, x, 0.0, 8.0, 0.0, 8.0, 4)
    assert handle
    try:
        with pytest.raises(ValueError, match="pyramid handle"):
            impl.pyramid_count(True, 0.0, 8.0, 0.0, 8.0)
        with pytest.raises(ValueError, match="non-negative"):
            impl.pyramid_compose(-1, 0.0, 8.0, 0.0, 8.0, 4, 4)
        with pytest.raises(ValueError, match="x range"):
            impl.pyramid_count(handle, 0.0, 0.0, 0.0, 8.0)
        with pytest.raises(ValueError, match="y range"):
            impl.pyramid_compose(handle, 0.0, 8.0, np.inf, 8.0, 4, 4)
        with pytest.raises(ValueError, match="w"):
            impl.pyramid_compose(handle, 0.0, 8.0, 0.0, 8.0, True, 4)
        assert impl.pyramid_count(0, 0.0, 8.0, 0.0, 8.0) is None
        assert impl.pyramid_compose(0, 0.0, 8.0, 0.0, 8.0, 4, 4) is None
        with pytest.raises(ValueError, match="equal length"):
            impl.pyramid_append(handle, x, short)
        with pytest.raises(ValueError, match="pyramid handle"):
            impl.pyramid_append(True, x, x)
    finally:
        assert impl.pyramid_free(handle)
    with pytest.raises(ValueError, match="pyramid handle"):
        impl.pyramid_free(True)


def test_pyramid_matches_bin2d_and_conserves():
    # §5 Tier 3: full-window compose is exactly the base grid; counts conserve;
    # outresolving windows are refused (the exact path must run instead).
    rng = np.random.default_rng(7)
    x = rng.uniform(0, 100, 5000)
    y = rng.uniform(0, 100, 5000)
    h = k.pyramid_build(x, y, 0.0, 100.0, 0.0, 100.0, 64)
    assert h != 0
    try:
        grid, level = k.pyramid_compose(h, 0.0, 100.0, 0.0, 100.0, 64, 64)
        assert level == 0
        direct = np.asarray(k.bin_2d(x, y, 0.0, 100.0, 0.0, 100.0, 64, 64))
        np.testing.assert_array_equal(np.asarray(grid).ravel(), direct.ravel())
        assert k.pyramid_count(h, 0.0, 100.0, 0.0, 100.0) == 5000.0
        sub = k.pyramid_compose(h, 10.0, 60.0, 20.0, 70.0, 16, 16)
        assert sub is not None
        total = float(np.asarray(sub[0]).sum())
        c0 = k.pyramid_count(h, 10.0, 60.0, 20.0, 70.0)
        assert abs(total - c0) <= c0 * 0.02  # whole-cell edge band
        assert k.pyramid_compose(h, 50.0, 50.4, 50.0, 50.4, 512, 512) is None
    finally:
        assert k.pyramid_free(h)
    assert not k.pyramid_free(h)


def test_pyramid_append_matches_rebuild_and_is_atomic_on_domain_growth():
    rng = np.random.default_rng(8)
    x = rng.uniform(0, 100, 5000)
    y = rng.uniform(0, 100, 5000)
    tail_x = np.array([10.0, 10.0, 50.0, 99.0, np.nan])
    tail_y = np.array([20.0, 20.0, 50.0, 1.0, 10.0])
    incremental = k.pyramid_build(x, y, 0.0, 100.0, 0.0, 100.0, 64)
    rebuilt = k.pyramid_build(
        np.concatenate([x, tail_x]),
        np.concatenate([y, tail_y]),
        0.0,
        100.0,
        0.0,
        100.0,
        64,
    )
    assert incremental and rebuilt
    try:
        assert k.pyramid_append(incremental, tail_x, tail_y)
        inc_grid, _ = k.pyramid_compose(incremental, 0.0, 100.0, 0.0, 100.0, 64, 64)
        rebuilt_grid, _ = k.pyramid_compose(rebuilt, 0.0, 100.0, 0.0, 100.0, 64, 64)
        np.testing.assert_array_equal(inc_grid, rebuilt_grid)

        before = inc_grid.copy()
        assert not k.pyramid_append(incremental, [50.0, 100.0], [50.0, 50.0])
        after, _ = k.pyramid_compose(incremental, 0.0, 100.0, 0.0, 100.0, 64, 64)
        np.testing.assert_array_equal(after, before)
    finally:
        assert k.pyramid_free(incremental)
        assert k.pyramid_free(rebuilt)


def test_heatmap_rgba_maps_stops_and_flips_rows():
    raw = np.array([[0.0, 0.5], [1.0, np.nan]], dtype=np.float64)
    stops = np.array([[0, 10, 20], [100, 110, 120]], dtype=np.uint8)

    rgba = k.heatmap_rgba(raw, 2, 2, stops, 200)

    # Only genuinely missing (NaN) cells are transparent; a real in-domain 0
    # paints the colormap's floor color opaquely (Matplotlib hist2d/imshow fill
    # the whole extent — empty bins are the 0-color, not holes).
    np.testing.assert_array_equal(
        rgba,
        np.array(
            [
                [[100, 110, 120, 200], [0, 0, 0, 0]],
                [[0, 10, 20, 200], [50, 60, 70, 200]],
            ],
            dtype=np.uint8,
        ),
    )
    with pytest.raises(ValueError, match="scalar count"):
        k.heatmap_rgba(raw, 3, 2, stops, 200)


@pytest.mark.parametrize("maximum", [0.0, 1.0, 13.0, 10_000.0, 1.0e12])
@pytest.mark.parametrize("opacity", [0.0, 0.37, 0.85, 1.0])
def test_density_rgba_matches_vectorized_static_export(maximum, opacity):
    encoded = np.arange(256, dtype=np.uint8).reshape(16, 16)
    stops = np.array(
        [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
        dtype=np.uint8,
    )
    values = encoded.astype(np.float64)
    if maximum > 0.0:
        values = np.expm1((values / 255.0) * np.log1p(maximum))
        t = np.clip(values / maximum, 0.0, 1.0)
    else:
        t = np.zeros_like(values)
    position = t * (len(stops) - 1)
    lo = np.floor(position).astype(np.uint8)
    hi = np.minimum(lo + 1, len(stops) - 1)
    fraction = position - lo
    rgb = np.empty((*encoded.shape, 3), dtype=np.uint8)
    stops_f64 = stops.astype(np.float64)
    for channel in range(3):
        start = stops_f64[lo, channel]
        rgb[..., channel] = np.round(start + (stops_f64[hi, channel] - start) * fraction).astype(
            np.uint8
        )
    alpha = (np.clip(t * 1.35, 0.0, 1.0) * 255.0 * opacity).astype(np.uint8)
    alpha[encoded == 0] = 0
    expected = np.dstack([rgb, alpha])[::-1]

    actual = k.density_rgba(encoded, 16, 16, maximum, stops, opacity)
    np.testing.assert_array_equal(actual, expected)


def test_density_rgba_validates_shape_and_domain():
    stops = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)
    with pytest.raises(ValueError, match="count"):
        k.density_rgba(np.zeros(3, dtype=np.uint8), 2, 2, 1.0, stops, 1.0)
    with pytest.raises(ValueError, match="maximum"):
        k.density_rgba(np.zeros(4, dtype=np.uint8), 2, 2, -1.0, stops, 1.0)
    with pytest.raises(ValueError, match="opacity"):
        k.density_rgba(np.zeros(4, dtype=np.uint8), 2, 2, 1.0, stops, 1.1)
