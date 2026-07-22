"""Transport-agnostic message dispatcher (spec/design/reflex-integration.md §3.1).

One kernel-side dispatcher for every transport: the anywidget comm today, and
any future host (the planned Reflex adapter's HTTP routes) tomorrow. A
transport parses its wire format, calls `handle_message`, and ships whatever
reply comes back; Python-side callbacks fire in here so every transport gets
identical semantics. Not to be confused with `channels.py`, which resolves
scatter color/size *encoding* channels.

Contracts (moved verbatim from `FigureWidget._on_custom_msg`):

- **Never raises on client-supplied data.** Malformed messages return None
  (silently dropped — a hostile or racing client must not be able to crash
  the kernel). Exceptions raised by *user callbacks* propagate: those are
  bugs in caller code, not client data.
- **Replies are return values, not sends.** The transport sends after this
  returns, so callbacks now fire before the reply leaves the process
  (previously the widget sent `pick_result` before `on_hover` and `selection`
  between `on_brush` and `on_select`). No client, test, or doc observes that
  interleaving — identical bytes arrive in the same order — and the named
  ordering invariant, on_brush before on_select, is preserved and tested.
- **`append` is not a message kind.** `Figure.append` already returns the
  transport-agnostic `(msg, buffers)` refresh; each transport ships it its
  own way (the widget re-syncs traits and sends; a server transport would
  broadcast it). Do not add a third message shape here.
- **`buffers` is accepted and currently unused** — no inbound message carries
  binary payloads today, but the signature is part of the §3.1 contract so
  the §3.2 length-prefixed HTTP framing (which would also live in this
  module) can pass them through without a break.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from ._figure import Selection
from ._framing import (
    DEFAULT_FRAME_LIMITS,
    FRAME_ALIGNMENT,
    FRAME_HEADER_SIZE,
    FRAME_MAGIC,
    FRAME_VERSION,
    DecodedFrame,
    FrameDecodeError,
    FrameEncodeError,
    FrameError,
    FrameLimits,
    decode_frame,
    encode_frame,
    encode_frame_parts,
)
from .interaction import _integer_id
from .lod import normalize_window

if TYPE_CHECKING:
    from ._figure import Figure

__all__ = [
    "DEFAULT_FRAME_LIMITS",
    "FRAME_ALIGNMENT",
    "FRAME_HEADER_SIZE",
    "FRAME_MAGIC",
    "FRAME_VERSION",
    "SELECTION_EVENT_ID_LIMIT",
    "SELECTION_EVENT_ROW_LIMIT",
    "ChannelCallbacks",
    "DecodedFrame",
    "FrameDecodeError",
    "FrameEncodeError",
    "FrameError",
    "FrameLimits",
    "decode_frame",
    "encode_frame",
    "encode_frame_parts",
    "handle_message",
]

# (reply message, buffers to ship beside it — None when the reply has none).
Reply = tuple[dict[str, Any], Optional[list[bytes]]]

# Reflex semantic selection events include bounded JSON projections. The
# complete canonical Selection remains server-side and can be re-resolved.
SELECTION_EVENT_ROW_LIMIT = 1000
SELECTION_EVENT_ID_LIMIT = 10000


@dataclass(frozen=True)
class ChannelCallbacks:
    """Python-side event callbacks a transport wires into the dispatcher.

    All optional; a transport with no Python callbacks (a bare export host)
    passes nothing and still gets the wire replies.
    """

    on_hover: Optional[Callable[[dict[str, Any]], None]] = None
    on_click: Optional[Callable[[dict[str, Any]], None]] = None
    on_brush: Optional[Callable[[dict[str, Any]], None]] = None
    on_select: Optional[Callable[[Selection], None]] = None
    on_view_change: Optional[Callable[[dict[str, Any]], None]] = None
    on_animation_start: Optional[Callable[[dict[str, Any]], None]] = None
    on_animation_end: Optional[Callable[[dict[str, Any]], None]] = None


_NO_CALLBACKS = ChannelCallbacks()


def _selection_reply(
    fig: "Figure",
    selected: dict[int, Any],
    callbacks: ChannelCallbacks,
    brush: dict[str, Any],
    *,
    include_rows: bool = False,
    kind: Optional[str] = None,
    seq: Any = None,
) -> Reply:
    if callbacks.on_brush is not None:
        callbacks.on_brush(brush)
    traces = []
    out: list[bytes] = []
    total = 0
    for tid, idx in selected.items():
        # The wire mask speaks shipped-vertex positions; callbacks retain
        # canonical rows (§34 — the GPU and Python have distinct index spaces).
        wire_idx = fig.to_shipped_indices(tid, idx)
        traces.append(
            {
                "id": tid,
                "count": int(len(wire_idx)),
                "buf": len(out),
                "drill_seq": fig.traces[tid].drill_seq,
            }
        )
        out.append(wire_idx.tobytes())
        total += len(idx)
    if callbacks.on_select is not None:
        callbacks.on_select(Selection(fig, selected))
    message: dict[str, Any] = {"type": "selection", "traces": traces, "total": total}
    if seq is not None:
        message["seq"] = seq
    if include_rows:
        canonical_row_ids = []
        ids_remaining = SELECTION_EVENT_ID_LIMIT
        ids_truncated = False
        for tid in sorted(selected):
            canonical = sorted(int(value) for value in selected[tid])
            kept = canonical[:ids_remaining]
            canonical_row_ids.append({"trace": int(tid), "ids": kept})
            ids_remaining -= len(kept)
            if len(kept) < len(canonical):
                ids_truncated = True
            if ids_remaining == 0:
                ids_truncated = ids_truncated or any(
                    len(selected[other_tid]) for other_tid in sorted(selected) if other_tid > tid
                )
                break
        rows, rows_truncated = (
            Selection(fig, selected).rows(SELECTION_EVENT_ROW_LIMIT),
            (total > SELECTION_EVENT_ROW_LIMIT),
        )
        message.update(
            {
                "version": 1,
                "kind": kind,
                "mode": "replace",
                "canonical_row_ids": canonical_row_ids,
                "rows": rows,
                "truncated": ids_truncated or rows_truncated,
            }
        )
        if kind == "box":
            message["bounds"] = dict(brush)
        elif kind == "lasso":
            message["polygon"] = brush["polygon"]
    return message, out


def handle_message(
    fig: "Figure",
    content: Any,
    buffers: Optional[list[bytes]] = None,
    callbacks: ChannelCallbacks = _NO_CALLBACKS,
) -> Optional[Reply]:
    """Dispatch one client message against a figure.

    Returns the reply to ship back over the wire, or None when there is
    nothing to send (malformed input, callback-only kinds, empty updates).
    """
    del buffers  # no inbound message carries buffers today (see module doc)
    if not isinstance(content, dict):
        return None
    kind = content.get("type")
    if not isinstance(kind, str):
        return None
    if kind in {"animation_start", "animation_end"}:
        callback = (
            callbacks.on_animation_start
            if kind == "animation_start"
            else callbacks.on_animation_end
        )
        if callback is not None:
            event: dict[str, Any] = {"phase": str(content.get("phase", "update"))}
            if kind == "animation_end" and isinstance(content.get("cancelled"), bool):
                event["cancelled"] = content["cancelled"]
            callback(event)
        return None
    if kind == "view":
        # Zoom/pan crossed what the shipped decimation can serve: recompute
        # for the visible window only (§28), stale-while-revalidate on the
        # client (§17 — it keeps drawing the old tier until this arrives).
        seq = content.get("seq")
        try:
            x0 = float(content["x0"])
            x1 = float(content["x1"])
            if not x1 > x0:
                return None
            update, out = fig.decimate_view(
                x0,
                x1,
                content.get("px", 2048),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if update["traces"]:
            return {"type": "tier_update", "seq": seq, **update}, out
        return None
    if kind == "density_view":
        # Tier-2 scatter panned/zoomed: re-bin the visible window (§5).
        seq = content.get("seq")
        try:
            update, out = fig.density_view(
                content["trace"],
                content["x0"],
                content["x1"],
                content["y0"],
                content["y1"],
                content.get("w", 512),
                content.get("h", 384),
            )
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        if update["traces"]:
            return {"type": "density_update", "seq": seq, **update}, out
        return None
    if kind == "pick":
        # Hover/click drill: exact f64 row from canonical (§16/§17). The
        # client's drill_seq rejects picks that raced a subset swap.
        dseq = content.get("drill_seq")
        try:
            trace_id = _integer_id(content["trace"], "trace")
            index = _integer_id(content["index"], "index")
            drill_seq = None if dseq is None else _integer_id(dseq, "drill_seq")
            row = fig.pick(
                trace_id,
                index,
                drill_seq,
            )
        except (KeyError, TypeError, ValueError):
            return None
        if row is not None and callbacks.on_hover is not None:
            callbacks.on_hover(row)
        # Reply ships even when row is None (stale drill_seq): the client
        # clears its hover state on the empty result.
        return {"type": "pick_result", "seq": content.get("seq"), "row": row}, None
    if kind == "click":
        dseq = content.get("drill_seq")
        row = None
        try:
            trace_id = _integer_id(content["trace"], "trace")
            index = _integer_id(content["index"], "index")
            drill_seq = None if dseq is None else _integer_id(dseq, "drill_seq")
            row = fig.pick(trace_id, index, drill_seq)
        except (KeyError, TypeError, ValueError):
            return None
        if row is not None and callbacks.on_click is not None:
            callbacks.on_click(row)
        return None
    if kind == "view_change":
        try:
            raw_ranges = content.get("ranges")
            ranges: dict[str, list[float]] = {}
            if isinstance(raw_ranges, dict):
                for axis_id, raw_range in raw_ranges.items():
                    if axis_id not in fig.axis_options:
                        continue
                    if not isinstance(raw_range, (tuple, list)) or len(raw_range) != 2:
                        raise ValueError("invalid view range")
                    lo, hi = float(raw_range[0]), float(raw_range[1])
                    if not math.isfinite(lo) or not math.isfinite(hi) or lo == hi:
                        raise ValueError("invalid view range")
                    ranges[axis_id] = [lo, hi]
            if not ranges:
                x0, x1, y0, y1 = normalize_window(
                    content["x0"],
                    content["x1"],
                    content["y0"],
                    content["y1"],
                    require_area=False,
                )
                ranges = {"x": [x0, x1], "y": [y0, y1]}
            x_range = ranges.get("x")
            y_range = ranges.get("y")
            view = {
                "ranges": ranges,
                "source": str(content.get("source", "view")),
                "axes": [
                    axis_id
                    for axis_id in content.get("axes", [])
                    if isinstance(axis_id, str) and axis_id in ranges
                ],
                "phase": str(content.get("phase", "end")),
                "interaction_id": content.get("interaction_id"),
            }
            if x_range is not None:
                view.update({"x0": x_range[0], "x1": x_range[1]})
            if y_range is not None:
                view.update({"y0": y_range[0], "y1": y_range[1]})
        except (KeyError, TypeError, ValueError):
            return None
        # Every committed view event feeds the figure's durable-state cache
        # (view-state.md §5.1) — the reason end-phase events always ship —
        # independent of whether a Python callback is registered.
        fig._record_view_ranges(ranges)
        if callbacks.on_view_change is not None:
            callbacks.on_view_change(view)
        return None
    if kind == "select":
        # Box-select → range predicate (§34 Tier A). Ship a selection mask
        # per trace so the client dims unselected marks; call on_select with
        # the resolved indices (Arrow-slice-shaped, not JSON — §34 API note).
        try:
            x0, x1, y0, y1 = normalize_window(
                content["x0"],
                content["x1"],
                content["y0"],
                content["y1"],
                require_area=False,
            )
            sel = fig.select_range(
                x0,
                x1,
                y0,
                y1,
            )
        except (KeyError, TypeError, ValueError):
            return None
        fig._record_selection({"range": {"x0": x0, "x1": x1, "y0": y0, "y1": y1}})
        return _selection_reply(
            fig,
            sel,
            callbacks,
            {"x0": x0, "x1": x1, "y0": y0, "y1": y1},
            include_rows=bool(content.get("include_rows")),
            kind="box",
            seq=content.get("seq"),
        )
    if kind == "select_polygon":
        try:
            points = content["points"]
            sel = fig.select_polygon(points)
            polygon = [[float(point[0]), float(point[1])] for point in points]
        except (IndexError, KeyError, TypeError, ValueError):
            return None
        fig._record_selection({"polygon": polygon})
        return _selection_reply(
            fig,
            sel,
            callbacks,
            {"polygon": polygon},
            include_rows=bool(content.get("include_rows")),
            kind="lasso",
            seq=content.get("seq"),
        )
    if kind == "select_clear":
        fig._record_selection(None)
        if callbacks.on_select is not None:
            callbacks.on_select(Selection(fig, {}))
        message: dict[str, Any] = {"type": "selection", "traces": [], "total": 0}
        if content.get("seq") is not None:
            message["seq"] = content["seq"]
        if content.get("include_rows"):
            message.update(
                {
                    "version": 1,
                    "kind": "clear",
                    "mode": "replace",
                    "canonical_row_ids": [],
                    "rows": [],
                    "truncated": False,
                }
            )
        return message, None
    return None
