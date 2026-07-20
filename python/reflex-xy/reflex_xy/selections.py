"""Server-side resolution of bounded Reflex selection events."""

from __future__ import annotations

from typing import Any

from xy._figure import Selection

from .registry import registry

__all__ = ["resolve_selection"]


def resolve_selection(event: Any) -> Selection | None:
    """Re-resolve a ``select_end`` event against the live figure.

    Returns the complete, unbounded canonical selection for the event token.
    Call :meth:`Selection.rows` for deterministic JSON dictionaries. This is
    the fallback when the bounded event payload reports ``truncated``.
    Unknown tokens, cleared/empty selections, and malformed events return
    ``None``; client input never raises from this helper.
    """
    try:
        if not isinstance(event, dict) or event.get("type") != "select_end":
            return None
        token = event.get("token")
        selection = event.get("selection")
        if not isinstance(token, str) or not isinstance(selection, dict):
            return None
        if selection.get("cleared") or selection.get("kind") == "clear":
            return None
        entry = registry.get(token)
        if entry is None:
            return None
        kind = selection.get("kind")
        if kind == "box":
            bounds = selection["data_bounds"]
            per_trace = entry.figure.select_range(
                bounds["x0"], bounds["x1"], bounds["y0"], bounds["y1"]
            )
        elif kind == "lasso":
            per_trace = entry.figure.select_polygon(selection["polygon"])
        else:
            return None
        resolved = Selection(entry.figure, per_trace)
        return resolved if len(resolved) else None
    except (IndexError, KeyError, TypeError, ValueError):
        return None
