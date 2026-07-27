"""Shared direct-paint and alpha resolution for static exporters."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

ColumnReader = Callable[[int], np.ndarray]


def triangle_mesh_boundary(*vertices: np.ndarray) -> np.ndarray | None:
    """Recover one exterior walk from a connected tessellated polygon.

    ``Axes.fill`` reaches the shared triangle renderer for WebGL, but static
    exporters should paint its triangulation as one polygon. Otherwise each
    independently antialiased triangle leaks a hairline of background (and
    applies translucent alpha more than once) along internal diagonals.

    A filled strip can pinch where its two curves meet. Its boundary then has
    degree-four vertices rather than being a simple ring, and degenerate
    triangles at the pinch can repeat an edge twice. Retaining odd-count edges
    and following an Eulerian boundary walk preserves those touching lobes as
    one static fill without exposing the tessellation.
    """
    if len(vertices) != 6:
        raise ValueError("triangle mesh boundary requires six coordinate arrays")
    arrays = [np.asarray(values, dtype=np.float64).reshape(-1) for values in vertices]
    n = min((len(values) for values in arrays), default=0)
    if n == 0:
        return None
    coordinates = np.concatenate([values[:n] for values in arrays])
    if not np.isfinite(coordinates).all():
        return None
    span = float(coordinates.max() - coordinates.min())
    # Each triangle coordinate is transported in an independently offset
    # float32 column, so the same source vertex may decode a few ULPs apart in
    # x0/x1/x2. The joined-fill flag is only used for one simple polygon; a
    # generous relative bucket is still far below meaningful edge spacing.
    tolerance = max(span * 2e-5, 1e-12)

    # A single rounded bucket is not a proximity test: two float32-decoded
    # copies of one source vertex can straddle its boundary. Search the
    # neighboring cells and snap each copy to a stable representative instead.
    buckets: dict[tuple[int, int], list[int]] = {}
    points_by_key: list[tuple[float, float]] = []

    def vertex_key(point: tuple[float, float]) -> int:
        cell = (math.floor(point[0] / tolerance), math.floor(point[1] / tolerance))
        best: int | None = None
        best_distance = math.inf
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for candidate in buckets.get((cell[0] + dx, cell[1] + dy), ()):
                    other = points_by_key[candidate]
                    delta_x, delta_y = abs(point[0] - other[0]), abs(point[1] - other[1])
                    if delta_x <= tolerance and delta_y <= tolerance:
                        distance = delta_x * delta_x + delta_y * delta_y
                        if distance < best_distance:
                            best, best_distance = candidate, distance
        if best is not None:
            return best
        key = len(points_by_key)
        points_by_key.append(point)
        buckets.setdefault(cell, []).append(key)
        return key

    edge_counts: dict[tuple[int, int], int] = {}
    for index in range(n):
        points = (
            (float(arrays[0][index]), float(arrays[1][index])),
            (float(arrays[2][index]), float(arrays[3][index])),
            (float(arrays[4][index]), float(arrays[5][index])),
        )
        for start, end in zip(points, points[1:] + points[:1], strict=True):
            start_key, end_key = vertex_key(start), vertex_key(end)
            edge = (start_key, end_key) if start_key <= end_key else (end_key, start_key)
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    # Internal edges occur an even number of times. Degenerate triangles can
    # contribute the same edge twice, so ``count == 1`` incorrectly removes a
    # real boundary edge after a curve touches its baseline.
    boundary = [edge for edge, count in edge_counts.items() if edge[0] != edge[1] and count % 2]
    if len(boundary) < 3:
        return None
    adjacency: dict[int, set[int]] = {}
    for start, end in boundary:
        adjacency.setdefault(start, set()).add(end)
        adjacency.setdefault(end, set()).add(start)
    if any(len(neighbors) % 2 for neighbors in adjacency.values()):
        return None

    # Hierholzer's algorithm also handles pinch vertices where two or more
    # boundary rings touch at one point. A disconnected boundary (for example,
    # a polygon with a hole) deliberately falls back to triangle rendering:
    # the current static fill command carries one walk and cannot preserve
    # multiple-subpath winding semantics.
    first = boundary[0][0]
    stack = [first]
    walk: list[int] = []
    while stack:
        current = stack[-1]
        if adjacency[current]:
            following = adjacency[current].pop()
            adjacency[following].remove(current)
            stack.append(following)
        else:
            walk.append(stack.pop())
    if len(walk) != len(boundary) + 1 or walk[0] != walk[-1]:
        return None
    walk.reverse()
    return np.asarray([points_by_key[key] for key in walk[:-1]], dtype=np.float64)


def direct_rgba(channel: dict[str, Any], n: int, read_column: ColumnReader) -> np.ndarray | None:
    """Decode a packed normalized RGBA8 channel to canonical float RGBA."""
    if channel.get("mode") != "direct_rgba":
        return None
    raw = np.asarray(read_column(int(channel["buf"])), dtype=np.uint8).reshape(-1)
    expected = n * 4
    if len(raw) < expected:
        raise ValueError(f"direct RGBA buffer has {len(raw)} bytes; expected {expected}")
    return raw[:expected].reshape(n, 4).astype(np.float64) / 255.0


def style_values(
    trace: dict[str, Any],
    name: str,
    n: int,
    read_column: ColumnReader,
    default: float,
) -> np.ndarray:
    """Resolve one scalar/direct numeric style channel to N float values."""
    channel = (trace.get("channels") or {}).get(name)
    if channel is None:
        return np.full(n, float(trace.get("style", {}).get(name, default)), dtype=np.float64)
    raw = np.asarray(read_column(int(channel["buf"])), dtype=np.float64)
    components = int(channel.get("components", 1))
    expected = n * components
    if raw.size < expected:
        raise ValueError(f"{name} style buffer has {raw.size} values; expected {expected}")
    return raw[:expected].reshape(n, components)[:, 0]


def style_matrix(
    trace: dict[str, Any],
    name: str,
    n: int,
    read_column: ColumnReader,
) -> np.ndarray | None:
    """Return a direct style channel as its ``(N, components)`` matrix."""
    channel = (trace.get("channels") or {}).get(name)
    if channel is None:
        return None
    components = int(channel.get("components", 1))
    raw = np.asarray(read_column(int(channel["buf"])), dtype=np.float64)
    expected = n * components
    if raw.size < expected:
        raise ValueError(f"{name} style buffer has {raw.size} values; expected {expected}")
    return raw[:expected].reshape(n, components)


def effective_rgba(
    intrinsic: np.ndarray,
    trace: dict[str, Any],
    read_column: ColumnReader,
    *,
    component: str,
    default_opacity: float,
) -> np.ndarray:
    """Apply Matplotlib artist alpha and xy opacity in the documented order.

    Intrinsic paint alpha is replaced (not multiplied) when artist alpha is
    non-negative. Core opacity and the component-specific fill/stroke opacity
    remain multiplicative.
    """
    rgba = np.asarray(intrinsic, dtype=np.float64).copy()
    if rgba.ndim != 2 or rgba.shape[1] != 4:
        raise ValueError(f"intrinsic paint must have shape (N, 4), got {rgba.shape}")
    n = len(rgba)
    style = trace.get("style") or {}
    artist = style_values(trace, "artist_alpha", n, read_column, -1.0)
    base_alpha = np.where(artist >= 0.0, artist, rgba[:, 3])
    opacity = style_values(trace, "opacity", n, read_column, default_opacity)
    component_opacity = float(style.get(f"{component}_opacity", 1.0))
    rgba[:, 3] = np.clip(base_alpha * opacity * component_opacity, 0.0, 1.0)
    return np.clip(rgba, 0.0, 1.0)
