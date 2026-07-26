"""Row-restricted rectangular selection: `range_indices_rows` must answer
exactly what `range_indices` answers over the same rows (design dossier §34).

This is the kernel that lets the zone-map-pruned branch of `select_range` scan
candidates in place. Before it, that branch gathered `x[candidates]` and
`y[candidates]` into two fresh f64 columns — 16 bytes per candidate, so a
*partial* selection cost several times a whole-domain one.
"""

from __future__ import annotations

import numpy as np
import pytest

from xy import interaction, kernels
from xy._figure import Figure


def _reference(
    x: np.ndarray, y: np.ndarray, rows: np.ndarray, win: tuple[float, float, float, float]
) -> np.ndarray:
    """What the gather-then-scan form produced, kept executable."""
    lo_x, hi_x, lo_y, hi_y = win
    hit = kernels.range_indices(x[rows], y[rows], lo_x, hi_x, lo_y, hi_y)
    return rows[hit]


WINDOWS = [
    (-0.5, 0.5, -0.5, 0.5),
    (-10.0, 10.0, -10.0, 10.0),  # everything
    (100.0, 200.0, 100.0, 200.0),  # nothing
    (0.0, 0.0, 0.0, 0.0),  # degenerate point window
    (-1.0, 0.0, 0.0, 1.0),  # one quadrant
]


@pytest.mark.parametrize("win", WINDOWS, ids=lambda w: f"{w[0]}_{w[1]}_{w[2]}_{w[3]}")
@pytest.mark.parametrize("n", [1, 2, 17, 1000, 100_000])
def test_matches_the_gathered_form(n: int, win: tuple[float, float, float, float]) -> None:
    rng = np.random.default_rng(4)
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    for rows in (
        np.arange(n, dtype=np.uint32),  # every row
        np.arange(0, n, 3, dtype=np.uint32),  # a strided subset
        np.array([n - 1], dtype=np.uint32),  # the last row alone
        np.empty(0, dtype=np.uint32),  # nothing
    ):
        got = kernels.range_indices_rows(x, y, rows, *win)
        want = _reference(x, y, rows, win)
        np.testing.assert_array_equal(got, want)
        assert got.dtype == np.uint32


def test_non_finite_is_never_inside() -> None:
    """NaN and infinities fail every comparison, matching `range_indices`."""
    x = np.array([0.0, np.nan, np.inf, -np.inf, 0.5, 0.0, 0.0])
    y = np.array([0.0, 0.0, 0.0, 0.0, 0.5, np.nan, np.inf])
    rows = np.arange(len(x), dtype=np.uint32)
    got = kernels.range_indices_rows(x, y, rows, -1.0, 1.0, -1.0, 1.0)
    np.testing.assert_array_equal(got, np.array([0, 4], dtype=np.uint32))
    np.testing.assert_array_equal(got, _reference(x, y, rows, (-1.0, 1.0, -1.0, 1.0)))


def test_bounds_are_inclusive() -> None:
    x = np.array([-1.0, -1.0, 1.0, 1.0, 0.0])
    y = np.array([-1.0, 1.0, -1.0, 1.0, 0.0])
    rows = np.arange(5, dtype=np.uint32)
    got = kernels.range_indices_rows(x, y, rows, -1.0, 1.0, -1.0, 1.0)
    np.testing.assert_array_equal(got, rows)


def test_row_order_is_preserved_not_sorted() -> None:
    """Output follows `rows`, so a caller's ordering survives the scan."""
    x = np.array([0.0, 0.1, 0.2, 0.3])
    y = np.zeros(4)
    rows = np.array([3, 1, 2, 0], dtype=np.uint32)
    got = kernels.range_indices_rows(x, y, rows, -1.0, 1.0, -1.0, 1.0)
    np.testing.assert_array_equal(got, rows)


def test_parallel_and_serial_agree() -> None:
    """The threaded gather-down must produce the serial answer exactly."""
    rng = np.random.default_rng(5)
    n = 2_000_000
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    rows = np.arange(0, n, 2, dtype=np.uint32)
    got = kernels.range_indices_rows(x, y, rows, -0.25, 0.25, -0.25, 0.25)
    want = _reference(x, y, rows, (-0.25, 0.25, -0.25, 0.25))
    np.testing.assert_array_equal(got, want)
    assert 0 < got.size < rows.size


@pytest.mark.parametrize("bad", [(np.nan, 1.0, -1.0, 1.0), (1.0, -1.0, -1.0, 1.0)])
def test_invalid_window_raises(bad: tuple[float, float, float, float]) -> None:
    x = np.zeros(4)
    rows = np.arange(4, dtype=np.uint32)
    with pytest.raises(ValueError):
        kernels.range_indices_rows(x, x, rows, *bad)


def test_out_of_range_row_is_an_error_not_a_read() -> None:
    """A row id past the column length must come back as the error sentinel."""
    x = np.zeros(4)
    rows = np.array([0, 9], dtype=np.uint32)
    with pytest.raises(ValueError):
        kernels.range_indices_rows(x, x, rows, -1.0, 1.0, -1.0, 1.0)


def test_select_range_agrees_across_the_pruning_branches() -> None:
    """Zone-pruned and whole-column selection must return the same rows.

    `select_range` takes the pruned branch only when some zone chunks are
    excluded, so a sorted-x column with a narrow window exercises the path this
    kernel replaced, and a full-domain window exercises the other one.
    """
    rng = np.random.default_rng(6)
    n = 300_000
    x = np.sort(rng.normal(size=n))
    y = rng.normal(size=n)
    fig = Figure()
    fig.scatter(x, y)
    fig.build_payload()

    for lo, hi in ((-10.0, 10.0), (-0.5, 0.0), (-3.0, 3.0), (0.9, 1.1)):
        got = interaction.select_range(fig, lo, hi, -0.5, 0.5)[0]
        want = np.flatnonzero((x >= lo) & (x <= hi) & (y >= -0.5) & (y <= 0.5))
        np.testing.assert_array_equal(got.astype(np.int64), want)
