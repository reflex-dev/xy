"""Typed declarations for the v1 semantic event envelopes.

These mirror, field for field, the envelopes ``XYChart.jsx`` dispatches into
Reflex event handlers (``on_point_hover`` / ``on_point_click`` /
``on_select_end`` / ``on_view_change``; catalog in
``spec/design/reflex-integration.md``). They are declarations only: handlers
still receive plain dicts, and annotating a handler argument with one of
these types changes nothing at runtime — it documents the shape and lets a
type checker verify field access::

    @rx.event
    def on_click(self, event: reflex_xy.PointClickEvent):
        row = event["canonical_row_id"]

The JS side is the single producer; keep this module in sync with
``assets/XYChart.jsx`` (``pointEnvelope`` / the ``select_end`` and
``view_change`` dispatches) whenever an envelope gains a field.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

__all__ = [
    "CanonicalRowIdGroup",
    "DataBounds",
    "Modifiers",
    "PointClickEvent",
    "PointData",
    "PointHoverEvent",
    "ScreenPoint",
    "SelectEndEvent",
    "SelectionPayload",
    "ViewChangeEvent",
]


class PointData(TypedDict):
    """Canonical f64 data-space coordinates of one point."""

    x: float
    y: float


class ScreenPoint(TypedDict):
    """Canvas-relative CSS pixel coordinates; ``None`` for keyboard
    activation, where no pointer position exists."""

    x: Optional[float]
    y: Optional[float]


class Modifiers(TypedDict):
    """Keyboard modifiers held during activation."""

    shift: bool
    alt: bool
    ctrl: bool
    meta: bool


class _PointEventBase(TypedDict):
    version: int
    token: str
    trace: int
    canonical_row_id: int
    data: PointData
    # Remaining per-point channels (color/size/label columns) keyed by
    # channel name; the set depends on the trace's encodings.
    datum: dict[str, Any]


class PointHoverEvent(_PointEventBase):
    """``on_point_hover`` — throttled hover row resolution.

    Shape (hover tooltips don't expand TypedDict fields, so they are
    spelled out here)::

        {
            "version": int,             # envelope version (1)
            "type": "point_hover",
            "token": str,               # chart identity token
            "trace": int,               # trace index in the figure
            "canonical_row_id": int,    # row id in canonical data order
            "data": {"x": float, "y": float},   # f64 data-space coords
            "datum": {channel: value, ...},     # remaining per-point channels
        }
    """

    type: Literal["point_hover"]


class PointClickEvent(_PointEventBase):
    """``on_point_click`` — pointer or keyboard activation of one point.

    Shape::

        {
            "version": int,             # envelope version (1)
            "type": "point_click",
            "token": str,               # chart identity token
            "trace": int,               # trace index in the figure
            "canonical_row_id": int,    # row id in canonical data order
            "data": {"x": float, "y": float},   # f64 data-space coords
            "datum": {channel: value, ...},     # remaining per-point channels
            "screen": {"x": float | None, "y": float | None},  # CSS px;
                                        # None for keyboard activation
            "modifiers": {"shift": bool, "alt": bool,
                          "ctrl": bool, "meta": bool},
        }
    """

    type: Literal["point_click"]
    screen: ScreenPoint
    modifiers: Modifiers


class DataBounds(TypedDict):
    """Box-selection rectangle in data space."""

    x0: float
    x1: float
    y0: float
    y1: float


class CanonicalRowIdGroup(TypedDict):
    """Canonical row ids for one trace, ascending, bounded by the
    selection event id limit (``truncated`` reports the cut)."""

    trace: int
    ids: list[int]


class SelectionPayload(TypedDict):
    kind: Literal["box", "lasso", "clear"]
    mode: Literal["replace"]
    data_bounds: Optional[DataBounds]  # box selections; None for lasso/clear
    polygon: Optional[list[list[float]]]  # lasso vertices; None for box/clear
    canonical_row_ids: list[CanonicalRowIdGroup]
    rows: list[dict[str, Any]]  # bounded Selection.rows() projection
    total_count: int
    truncated: bool  # rows/ids were cut; resolve_selection() gets the rest
    cleared: bool


class SelectEndEvent(TypedDict):
    """``on_select_end`` — completed box/lasso selection or a clear.

    ``resolve_selection(event)`` re-resolves the complete, unbounded
    selection server-side when the bounded payload reports ``truncated``.

    Shape::

        {
            "version": int,             # envelope version (1)
            "type": "select_end",
            "token": str,               # chart identity token
            "selection": {
                "kind": "box" | "lasso" | "clear",
                "mode": "replace",
                "data_bounds": {"x0", "x1", "y0", "y1"} | None,  # box only
                "polygon": [[x, y], ...] | None,                 # lasso only
                "canonical_row_ids": [{"trace": int, "ids": [int, ...]}, ...],
                "rows": [{column: value, ...}, ...],  # bounded projection
                "total_count": int,
                "truncated": bool,      # rows/ids were cut at the event limit
                "cleared": bool,
            },
        }
    """

    version: int
    type: Literal["select_end"]
    token: str
    selection: SelectionPayload


class ViewChangeEvent(TypedDict):
    """``on_view_change`` — throttled viewport stream during and after pan/zoom.

    Dispatches are leading+trailing throttled (latest-wins): ``update``-phase
    events stream while the gesture is in progress so dependent charts track
    it live, and the resting viewport always arrives as a final ``final``-phase
    event. Handlers that only care about settled views can filter on ``phase``.

    Shape::

        {
            "version": int,             # envelope version (1)
            "type": "view_change",
            "token": str,               # chart identity token
            "x_domain": [x0, x1],       # f64 data-space window
            "y_domain": [y0, y1],
            "source": str,              # gesture: pan/zoom/keyboard/...
            "phase": "update" | "final",
        }
    """

    version: int
    type: Literal["view_change"]
    token: str
    x_domain: list[float]  # [x0, x1]
    y_domain: list[float]  # [y0, y1]
    source: str  # gesture that produced the view (pan/zoom/keyboard/...)
    phase: Literal["update", "final"]
