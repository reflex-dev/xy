"""Lasso selection: the native ray cast must answer exactly what the
vectorized per-edge predicate answered (design dossier §34)."""

from __future__ import annotations

import numpy as np
import pytest

from xy import kernels
from xy._figure import Figure


def _per_edge_reference(
    x: np.ndarray, y: np.ndarray, rows: np.ndarray, polygon: np.ndarray
) -> np.ndarray:
    """One pass per polygon edge, crossing parity accumulated across rows.

    This is the definition `kernels.polygon_select` implements; keeping it
    here makes the contract executable rather than a comment.
    """
    xs, ys = x[rows], y[rows]
    inside = np.zeros(len(rows), dtype=np.bool_)
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        crosses = (yi > ys) != (yj > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            edge_x = (xj - xi) * (ys - yi) / (yj - yi) + xi
        inside ^= crosses & (xs < edge_x)
        j = i
    return rows[inside]


def _ring(n: int, *, r: float = 30.0, cx: float = 50.0, cy: float = 50.0) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], axis=1)


def _star(n: int = 24) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    r = np.where(np.arange(n) % 2 == 0, 40.0, 12.0)
    return np.stack([50.0 + r * np.cos(t), 50.0 + r * np.sin(t)], axis=1)


POLYGONS = {
    "triangle": np.array([[10.0, 10.0], [90.0, 20.0], [50.0, 80.0]]),
    # Horizontal edges are the zero-height ones the vectorized form divided
    # by and masked away.
    "axis_aligned_box": np.array([[20.0, 20.0], [80.0, 20.0], [80.0, 80.0], [20.0, 80.0]]),
    # Self-intersecting, so even-odd parity is load-bearing.
    "bowtie": np.array([[10.0, 10.0], [90.0, 90.0], [90.0, 10.0], [10.0, 90.0]]),
    "collinear": np.array([[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]]),
    "repeated_vertex": np.array([[10.0, 10.0], [10.0, 10.0], [90.0, 90.0], [10.0, 90.0]]),
    "flat": np.array([[0.0, 30.0], [50.0, 30.0], [100.0, 30.0]]),
    # Straddles the >= 16-vertex gate where edges get bucketed by y.
    "ring_15": _ring(15),
    "ring_16": _ring(16),
    "ring_64": _ring(64),
    "ring_257": _ring(257),
    # The API ceiling `Figure.select_polygon` enforces.
    "ring_2048": _ring(2048),
    "star_concave": _star(),
    "covers_everything": _ring(32, r=500.0),
    "encloses_nothing": _ring(32, r=1e-6),
}


@pytest.fixture(scope="module")
def sample() -> tuple[np.ndarray, np.ndarray]:
    """A lattice (points land exactly on vertices and edges) plus the
    non-finite rows a canonical column is allowed to carry (§19)."""
    gx, gy = np.meshgrid(np.arange(0.0, 100.0, 2.0), np.arange(0.0, 100.0, 2.0))
    x = np.concatenate([gx.ravel(), [np.nan, 0.0, np.inf, -np.inf, 50.0, 20.0]])
    y = np.concatenate([gy.ravel(), [50.0, np.nan, 50.0, 50.0, np.inf, 20.0]])
    return np.ascontiguousarray(x), np.ascontiguousarray(y)


@pytest.mark.parametrize("name", sorted(POLYGONS))
def test_native_cast_matches_the_per_edge_predicate(name, sample):
    x, y = sample
    polygon = POLYGONS[name]
    rows = np.arange(len(x), dtype=np.uint32)
    got = kernels.polygon_select(
        x, y, rows, np.ascontiguousarray(polygon[:, 0]), np.ascontiguousarray(polygon[:, 1])
    )
    assert np.array_equal(got, _per_edge_reference(x, y, rows, polygon))
    assert got.dtype == np.uint32


@pytest.mark.parametrize(
    "rows",
    [
        np.empty(0, dtype=np.uint32),
        np.array([0], dtype=np.uint32),
        np.arange(0, 2400, 7, dtype=np.uint32),
    ],
    ids=["empty", "single", "strided"],
)
def test_candidate_subsets_preserve_order_and_membership(rows, sample):
    """The real call shape: `rows` is the zone-pruned bbox subset, and the
    reply must stay in canonical ascending order."""
    x, y = sample
    polygon = POLYGONS["ring_64"]
    got = kernels.polygon_select(
        x, y, rows, np.ascontiguousarray(polygon[:, 0]), np.ascontiguousarray(polygon[:, 1])
    )
    assert np.array_equal(got, _per_edge_reference(x, y, rows, polygon))
    assert np.all(np.diff(got.astype(np.int64)) > 0)
    assert set(got.tolist()) <= set(rows.tolist())


def test_figure_lasso_selects_the_disc_and_nothing_outside_it():
    rng = np.random.default_rng(67)
    x = rng.uniform(0.0, 100.0, 20_000)
    y = rng.uniform(0.0, 100.0, 20_000)
    fig = Figure()
    fig.scatter(x, y)
    polygon = _ring(64, r=20.0).tolist()

    selected = fig.select_polygon(polygon)[0]
    inside_radius = np.hypot(x[selected] - 50.0, y[selected] - 50.0)
    # Every selected point is within the circumscribed radius; the inscribed
    # radius bounds what the 64-gon must have caught.
    assert inside_radius.max() <= 20.0
    caught = np.hypot(x - 50.0, y - 50.0) <= 20.0 * np.cos(np.pi / 64)
    assert set(np.flatnonzero(caught).tolist()) <= set(selected.tolist())


def test_polygon_vertex_and_row_validation():
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 3.0])
    rows = np.array([0, 1, 2], dtype=np.uint32)
    square_x = np.array([0.0, 4.0, 4.0, 0.0])
    square_y = np.array([0.0, 0.0, 4.0, 4.0])

    # Fewer than three vertices encloses nothing rather than erroring.
    assert len(kernels.polygon_select(x, y, rows, square_x[:2], square_y[:2])) == 0

    with pytest.raises(ValueError):
        kernels.polygon_select(x, y[:2], rows, square_x, square_y)
    with pytest.raises(ValueError):
        kernels.polygon_select(x, y, rows, square_x, square_y[:3])
    # A row id past the end of the column is a caller bug, not a silent drop.
    # The entry point checks the ids itself (`rows_in_bounds`) rather than
    # leaving it to the kernel's indexing panic, so this holds on panic-abort
    # targets too — under the PyEmscripten wheel's `-C panic=abort` the panic
    # aborted the interpreter instead of raising.
    with pytest.raises(ValueError):
        kernels.polygon_select(x, y, np.array([99], dtype=np.uint32), square_x, square_y)
