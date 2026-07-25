"""Shared direct-paint and alpha resolution for static exporters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

ColumnReader = Callable[[int], np.ndarray]


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
