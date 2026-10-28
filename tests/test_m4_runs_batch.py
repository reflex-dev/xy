"""Batched finite-run M4 must retain the per-run kernel's exact row choices."""

import numpy as np
import pytest

from xy import kernels, lod


def _reference(x, y, valid, window, width):
    edges = np.flatnonzero(np.diff(np.r_[False, valid, False]))
    selected = []
    boundaries = [0]
    for start, stop in edges.reshape(-1, 2):
        rows = kernels.m4_indices(x[start:stop], y[start:stop], *window, width) + start
        if len(rows):
            selected.append(rows)
            boundaries.append(boundaries[-1] + len(rows))
    return (
        np.concatenate(selected) if selected else np.empty(0, dtype=np.uint32),
        np.asarray(boundaries, dtype=np.uint32),
    )


@pytest.mark.parametrize("seed", range(12))
def test_batched_runs_match_existing_m4_row_for_row(seed):
    rng = np.random.default_rng(seed)
    n = 5_000
    x = np.cumsum(rng.integers(0, 4, n)).astype(float)
    y = rng.choice([-8.0, -2.0, 0.0, 1.0, 9.0], n)
    valid = rng.random(n) > 0.12
    for window in ((-1, x[-1] + 1), (x[700], x[3900]), (x[-1] + 1, x[-1] + 5)):
        for width in (1, 3, 31, 720):
            edges = np.flatnonzero(np.diff(np.r_[False, valid, False])).astype(np.uint32)
            actual = kernels.m4_runs_indices(x, y, edges, *window, width)
            expected = _reference(x, y, valid, window, width)
            for got, want in zip(actual, expected, strict=True):
                np.testing.assert_array_equal(got, want)


def test_lod_uses_one_batched_call_for_fragmented_data(monkeypatch):
    original = kernels.m4_runs_indices
    calls = []

    def batch(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(kernels, "m4_runs_indices", batch)
    x = np.arange(100_000.0)
    y = np.sin(x)
    valid = np.ones(len(x), dtype=bool)
    valid[50::100] = False
    actual = lod.line_run_indices(x, y, valid, (0, len(x)), 720)
    expected = _reference(x, y, valid, (0, len(x)), 720)
    assert len(calls) == 1
    for got, want in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(got, want)


def test_batch_matches_parallel_m4_and_reset_run_domains():
    x = np.tile(np.arange(160_000.0), 2)
    y = np.cos(np.arange(len(x)) * 0.005)
    valid = np.ones(len(x), dtype=bool)
    valid[159_999] = False
    for window in ((0, 160_000), (100, 159_000)):
        expected = _reference(x, y, valid, window, 720)
        edges = np.flatnonzero(np.diff(np.r_[False, valid, False])).astype(np.uint32)
        actual = kernels.m4_runs_indices(x, y, edges, *window, 720)
        for got, want in zip(actual, expected, strict=True):
            np.testing.assert_array_equal(got, want)


@pytest.mark.parametrize("bounds", [[0, 3, 2, 4], [0, 2, 3, 7], [1, 1], [-1, 2], [0, 2, 3]])
def test_batch_rejects_invalid_run_bounds(bounds):
    with pytest.raises(ValueError):
        kernels.m4_runs_indices(np.arange(6.0), np.ones(6), np.asarray(bounds), 0, 6, 4)
