"""Transport-agnostic message dispatcher (docs/design/reflex-integration.md §3.1).

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

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from .figure import Selection
from .interaction import _integer_id
from .lod import normalize_window

if TYPE_CHECKING:
    from .figure import Figure

__all__ = ["ChannelCallbacks", "handle_message"]

# (reply message, buffers to ship beside it — None when the reply has none).
Reply = tuple[dict[str, Any], Optional[list[bytes]]]


@dataclass(frozen=True)
class ChannelCallbacks:
    """Python-side event callbacks a transport wires into the dispatcher.

    All optional; a transport with no Python callbacks (a bare export host)
    passes nothing and still gets the wire replies.
    """

    on_hover: Optional[Callable[[dict[str, Any]], None]] = None
    on_click: Optional[Callable[[dict[str, Any]], None]] = None
    on_brush: Optional[Callable[[dict[str, float]], None]] = None
    on_select: Optional[Callable[[Selection], None]] = None
    on_view_change: Optional[Callable[[dict[str, Any]], None]] = None


_NO_CALLBACKS = ChannelCallbacks()


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
            trace_id = _integer_id(content.get("trace", -1), "trace")
            index = _integer_id(content.get("index", -1), "index")
            drill_seq = None if dseq is None else _integer_id(dseq, "drill_seq")
            row = fig.pick(
                trace_id,
                index,
                drill_seq,
            )
        except (TypeError, ValueError):
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
            trace_id = _integer_id(content.get("trace", -1), "trace")
            index = _integer_id(content.get("index", -1), "index")
            drill_seq = None if dseq is None else _integer_id(dseq, "drill_seq")
            row = fig.pick(trace_id, index, drill_seq)
        except (TypeError, ValueError):
            return None
        if row is not None and callbacks.on_click is not None:
            callbacks.on_click(row)
        return None
    if kind == "view_change":
        if callbacks.on_view_change is None:
            return None
        try:
            view = {
                "x0": float(content["x0"]),
                "x1": float(content["x1"]),
                "y0": float(content["y0"]),
                "y1": float(content["y1"]),
                "source": str(content.get("source", "view")),
            }
        except (KeyError, TypeError, ValueError):
            return None
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
        if callbacks.on_brush is not None:
            callbacks.on_brush({"x0": x0, "x1": x1, "y0": y0, "y1": y1})
        traces = []
        out: list[bytes] = []
        total = 0
        for tid, idx in sel.items():
            # The wire mask speaks shipped-vertex positions; the Selection
            # callback below keeps canonical rows (§34 — callbacks get real
            # data, the GPU gets its own coordinate space).
            wire_idx = fig.to_shipped_indices(tid, idx)
            traces.append(
                {
                    "id": tid,
                    "count": int(len(wire_idx)),
                    "buf": len(out),
                    # Which drilled subset this mask speaks for; the client
                    # drops it if its buffers have moved on (§17).
                    "drill_seq": fig.traces[tid].drill_seq,
                }
            )
            out.append(wire_idx.tobytes())
            total += len(idx)
        if callbacks.on_select is not None:
            callbacks.on_select(Selection(fig, sel))
        return {"type": "selection", "traces": traces, "total": total}, out
    if kind == "select_clear":
        if callbacks.on_select is not None:
            callbacks.on_select(Selection(fig, {}))
        return {"type": "selection", "traces": [], "total": 0}, None
    return None
