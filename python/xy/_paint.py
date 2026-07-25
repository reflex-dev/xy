"""Shared direct-paint and alpha resolution for static exporters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

ColumnReader = Callable[[int], np.ndarray]


def triangle_mesh_boundary(*vertices: np.ndarray) -> np.ndarray | None:
    """Recover the single exterior ring of a tessellated simple polygon.

    ``Axes.fill`` reaches the shared triangle renderer for WebGL, but static
    exporters should paint its triangulation as one polygon. Otherwise each
    independently antialiased triangle leaks a hairline of background (and
    applies translucent alpha more than once) along internal diagonals.
    """
    if len(vertices) != 6:
        raise ValueError("triangle mesh boundary requires six coordinate arrays")
    arrays = [np.asarray(values, dtype=np.float64).reshape(-1) for values in vertices]
    n = min((len(values) for values in arrays), default=0)
    if n == 0:
        return None
    finite = np.concatenate(arrays)
    span = float(np.nanmax(finite) - np.nanmin(finite))
    # Each triangle coordinate is transported in an independently offset
    # float32 column, so the same source vertex may decode a few ULPs apart in
    # x0/x1/x2. The joined-fill flag is only used for one simple polygon; a
    # generous relative bucket is still far below meaningful edge spacing.
    tolerance = max(span * 2e-5, 1e-12)

    def vertex_key(point: tuple[float, float]) -> tuple[int, int]:
        return (round(point[0] / tolerance), round(point[1] / tolerance))

    edge_counts: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
    points_by_key: dict[tuple[int, int], tuple[float, float]] = {}
    for index in range(n):
        points = (
            (float(arrays[0][index]), float(arrays[1][index])),
            (float(arrays[2][index]), float(arrays[3][index])),
            (float(arrays[4][index]), float(arrays[5][index])),
        )
        for start, end in zip(points, points[1:] + points[:1], strict=True):
            start_key, end_key = vertex_key(start), vertex_key(end)
            points_by_key.setdefault(start_key, start)
            points_by_key.setdefault(end_key, end)
            edge = (start_key, end_key) if start_key <= end_key else (end_key, start_key)
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    boundary = [edge for edge, count in edge_counts.items() if count == 1]
    if len(boundary) < 3:
        return None
    adjacency: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for start, end in boundary:
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        return None
    first = boundary[0][0]
    ring = [first]
    previous: tuple[int, int] | None = None
    current = first
    for _ in range(len(boundary)):
        neighbors = adjacency[current]
        following = neighbors[0] if neighbors[0] != previous else neighbors[1]
        if following == first:
            if len(ring) != len(boundary):
                return None
            return np.asarray([points_by_key[key] for key in ring], dtype=np.float64)
        ring.append(following)
        previous, current = current, following
    return None


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
