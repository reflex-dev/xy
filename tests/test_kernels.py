"""Kernel correctness — native core and NumPy fallback, asserted identical.

The two thesis-risk tests §25 moved to the front of Phase 0 live here:
offset-encoding precision on ms timestamps, and M4's no-silent-data-loss
guarantees.
"""

from __future__ import annotations

import numpy as np
import pytest

from fastcharts import _fallback
from fastcharts import kernels as k

BACKENDS = [pytest.param(k, id=f"dispatch[{k.BACKEND}]"), pytest.param(_fallback, id="numpy")]


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


# -- native/fallback parity (§33: the fallback is semantically identical) ------


@pytest.mark.skipif(k.BACKEND != "native", reason="native core not built")
def test_backends_agree():
    from fastcharts import _native

    rng = np.random.default_rng(3)
    x = np.sort(rng.uniform(0, 1e6, 30_000))
    y = rng.normal(0, 1, 30_000)
    y[::500] = np.nan

    np.testing.assert_array_equal(
        _native.m4_indices(x, y, 0.0, 1e6, 777),
        _fallback.m4_indices(x, y, 0.0, 1e6, 777),
    )
    np.testing.assert_array_equal(
        _native.encode_f32(y, 0.5, 2.0), _fallback.encode_f32(y, 0.5, 2.0)
    )
    for a, b in zip(_native.zone_maps(x, 4096), _fallback.zone_maps(x, 4096)):
        np.testing.assert_allclose(a, b)
    assert _native.min_max(y) == _fallback.min_max(y)
