"""Returned handles: the mutation surface of matplotlib's artist model.

A handle wraps the *declarative spec entry* an Axes call appended — mutating
it (``set_ydata``, ``set_color``, ``remove``) edits the spec and invalidates
the Axes' cached chart, so the next render/export rebuilds. This covers the
dominant mutation idioms without reproducing matplotlib's artist graph.
"""

from __future__ import annotations

from typing import Any, Optional

from ._colors import resolve_color


class Artist:
    def __init__(self, axes: Any, entry: dict[str, Any]) -> None:
        self._axes = axes
        self._entry = entry  # the mutable spec dict the Axes rendered from

    def _touch(self) -> None:
        self._axes._invalidate()

    def remove(self) -> None:
        self._axes._remove_entry(self._entry)

    def set_label(self, label: str) -> None:
        self._entry["kwargs"]["name"] = str(label)
        self._touch()

    def get_label(self) -> Optional[str]:
        return self._entry["kwargs"].get("name")

    def set_alpha(self, alpha: float) -> None:
        self._entry["kwargs"]["opacity"] = float(alpha)
        self._touch()

    def set_color(self, color: Any) -> None:
        self._entry["kwargs"]["color"] = resolve_color(color)
        self._touch()

    def get_color(self) -> Any:
        return self._entry["kwargs"].get("color")


class Line2D(Artist):
    """Handle for plt.plot lines (and their marker overlays)."""

    def set_data(self, x: Any, y: Any) -> None:
        self._entry["x"] = x
        self._entry["y"] = y
        self._touch()

    def set_xdata(self, x: Any) -> None:
        self._entry["x"] = x
        self._touch()

    def set_ydata(self, y: Any) -> None:
        self._entry["y"] = y
        self._touch()

    def get_xdata(self) -> Any:
        return self._entry["x"]

    def get_ydata(self) -> Any:
        return self._entry["y"]

    def set_linewidth(self, w: float) -> None:
        self._entry["kwargs"]["width"] = float(w)
        self._touch()

    set_lw = set_linewidth


class PathCollection(Artist):
    """Handle for plt.scatter marks."""

    def set_offsets(self, xy: Any) -> None:
        import numpy as np

        arr = np.asarray(xy, dtype=np.float64)
        self._entry["x"] = arr[:, 0]
        self._entry["y"] = arr[:, 1]
        self._touch()


class BarContainer(Artist):
    """Handle for plt.bar/barh groups."""
