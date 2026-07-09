"""Kernel correctness for the native Rust core.

The two thesis-risk tests §25 moved to the front of Phase 0 live here:
offset-encoding precision on ms timestamps, and M4's no-silent-data-loss
guarantees.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from fastcharts import kernels as k
from fastcharts.config import MAX_SCREEN_DIM

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


# -- zone maps (§22) ---------------------------------------------------------


def test_zone_maps_stats(impl):
    rng = np.random.default_rng(7)
    data = rng.normal(100.0, 5.0, 200_000)
    data[::1000] = np.nan
    mins, maxs, counts, nulls, sums, sum_sqs = impl.zone_maps(data, 65_536)
    assert len(mins) == 4  # ceil(200k / 64k)
    valid = data[~np.isnan(data)]
    assert int(counts.sum()) == len(valid)
    assert int(nulls.sum()) == 200
    assert np.isclose(mins.min(), valid.min())
    assert np.isclose(maxs.max(), valid.max())
    assert np.isclose(sums.sum(), valid.sum())
    assert np.isclose(sum_sqs.sum(), (valid * valid).sum())


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
        mins, maxs, counts, nulls, sums, sum_sqs = impl.zone_maps(data, 65_536)
    runtime_warnings = [w for w in seen if issubclass(w.category, RuntimeWarning)]
    assert runtime_warnings == []
    assert int(counts.sum()) == 2
    assert int(nulls.sum()) == 0
    assert np.isfinite(mins[0])
    assert np.isfinite(maxs[0])
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


# -- chart-prep kernels -------------------------------------------------------


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


def test_sample_mask_matches_numpy_hash_reference(impl):
    # lod.hash_row_ids is the pure-NumPy SplitMix64 reference; the fused native
    # mask must be bit-identical to hashing + thresholding through it.
    from fastcharts import lod

    rng = np.random.default_rng(11)
    ids = rng.integers(0, 2**63, size=100_000).astype(np.uint64)
    for seed, fraction in [(0, 0.5), (7, 0.001), (2**40, 0.25)]:
        threshold = lod._sample_threshold(fraction)
        ref = lod.hash_row_ids(ids, seed=seed) <= threshold
        got = impl.sample_mask(ids, seed, int(threshold))
        assert got.dtype == np.bool_
        np.testing.assert_array_equal(got, ref)


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
    from fastcharts import lod

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
