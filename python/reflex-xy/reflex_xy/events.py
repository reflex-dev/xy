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
    """``on_point_hover`` — throttled hover row resolution."""

    type: Literal["point_hover"]


class PointClickEvent(_PointEventBase):
    """``on_point_click`` — pointer or keyboard activation of one point."""

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
    """

    version: int
    type: Literal["select_end"]
    token: str
    selection: SelectionPayload


class ViewChangeEvent(TypedDict):
    """``on_view_change`` — debounced final viewport after pan/zoom."""

    version: int
    type: Literal["view_change"]
    token: str
    x_domain: list[float]  # [x0, x1]
    y_domain: list[float]  # [y0, y1]
    source: str  # gesture that produced the view (pan/zoom/keyboard/...)
    phase: Literal["final"]
