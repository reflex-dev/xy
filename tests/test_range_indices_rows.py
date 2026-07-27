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
    """A row id past the column length must come back as the error sentinel.

    The entry point validates the ids rather than relying on the scan's own
    indexing panic: `ffi_guard` turns a panic into the sentinel only where
    panics unwind, and the PyEmscripten wheel is built `-C panic=abort` (see
    `.github/workflows/release.yml`) precisely so they cannot. There the panic
    aborted the Pyodide instance — and `xy.kernels` is public API, so the row
    array is caller data.
    """
    x = np.zeros(4)
    rows = np.array([0, 9], dtype=np.uint32)
    with pytest.raises(ValueError):
        kernels.range_indices_rows(x, x, rows, -1.0, 1.0, -1.0, 1.0)
    # The boundary id itself is valid; only past-the-end is an error.
    np.testing.assert_array_equal(
        kernels.range_indices_rows(x, x, np.array([3], dtype=np.uint32), -1.0, 1.0, -1.0, 1.0),
        np.array([3], dtype=np.uint32),
    )
    with pytest.raises(ValueError):
        kernels.range_indices_rows(x, x, np.array([4], dtype=np.uint32), -1.0, 1.0, -1.0, 1.0)


@pytest.mark.parametrize("bad", [2**32, 2**32 + 3, 2**40, -1, -(2**31)])
def test_a_row_id_that_would_wrap_is_rejected_not_cast(bad: int) -> None:
    """The u32 conversion is an unchecked C cast, so `2**32 + 3` would arrive as
    row 3 — in range, and therefore answered rather than refused. The caller
    would get a row it never asked for, which is worse than the error the
    kernel's bounds check exists to produce."""
    x = np.arange(10.0)
    y = np.zeros(10)
    rows = np.array([bad], dtype=np.int64)
    square_x = np.array([-1e9, 1e9, 1e9, -1e9])
    square_y = np.array([-1e9, -1e9, 1e9, 1e9])
    with pytest.raises(ValueError, match=r"canonical row ids in \[0, 2\*\*32\)"):
        kernels.range_indices_rows(x, y, rows, -1e9, 1e9, -1e9, 1e9)
    with pytest.raises(ValueError, match=r"canonical row ids in \[0, 2\*\*32\)"):
        kernels.polygon_select(x, y, rows, square_x, square_y)


@pytest.mark.parametrize("bad", [[3.9], [np.nan], [np.inf], [-0.5], [3.0]])
def test_a_float_row_id_is_refused_rather_than_rounded(bad: list[float]) -> None:
    """A float id has no row, and choosing one by cast is platform-dependent:
    `nan` saturates to 0 on arm64 but traps to INT64_MIN on x86_64, so a cast
    would make the guard disagree across the wheels we ship. `3.9` silently
    selecting row 3 is the same class of wrong answer as a wrapped id."""
    x = np.arange(8.0)
    y = np.arange(8.0)
    rows = np.asarray(bad)
    assert rows.dtype == np.float64
    with pytest.raises(ValueError, match="must be an integer array of row ids"):
        kernels.range_indices_rows(x, y, rows, 0.0, 8.0, 0.0, 8.0)
    with pytest.raises(ValueError, match="must be an integer array of row ids"):
        kernels.polygon_select(
            x, y, rows, np.array([-1e9, 1e9, 1e9, -1e9]), np.array([-1e9, -1e9, 1e9, 1e9])
        )


def test_an_empty_row_list_is_not_a_dtype_error() -> None:
    """`np.asarray([])` is float64, but selecting nothing is legitimate."""
    x = np.arange(8.0)
    got = kernels.range_indices_rows(x, x, np.asarray([]), 0.0, 8.0, 0.0, 8.0)
    assert got.size == 0 and got.dtype == np.uint32


def test_in_range_ids_survive_every_integer_dtype() -> None:
    """The range check must not start rejecting ordinary callers: any integer
    dtype holding valid ids still answers, and a uint32 array is passed through
    untouched."""
    x = np.arange(10.0)
    y = np.zeros(10)
    want = np.array([2, 5], dtype=np.uint32)
    for dtype in (np.uint32, np.int64, np.int32, np.uint64, np.int16, np.uint8):
        got = kernels.range_indices_rows(x, y, np.array([2, 5], dtype=dtype), -1e9, 1e9, -1e9, 1e9)
        np.testing.assert_array_equal(got, want)
        assert got.dtype == np.uint32


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
