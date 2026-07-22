"""anywidget integration (§33.3): one widget implementation covers Jupyter,
JupyterLab, VS Code, Colab, and Marimo, with a binary comm channel — spec as
JSON, data as raw buffers, never base64/JSON numbers (§29 Jupyter row).

The JS render client ships inside the wheel as a static asset — versioned,
no CDN (§33.2, airgapped notebooks).
"""

from __future__ import annotations

import asyncio
import pathlib
import time
from typing import TYPE_CHECKING, Any, Optional

import anywidget
import traitlets

# Selection lives in figure.py (it's the on_select payload and has no widget
# dependency); re-exported here for backward compatibility.
from ._figure import Selection
from .channel import ChannelCallbacks, handle_message

if TYPE_CHECKING:
    from ._figure import Figure

_STATIC = pathlib.Path(__file__).parent / "static"

__all__ = ["FigureWidget", "Selection", "bundled_js"]


def bundled_js(which: str = "widget") -> str:
    """Read a bundled client build ("widget" ESM or "standalone" IIFE)."""
    name = "index.js" if which == "widget" else "standalone.js"
    path = _STATIC / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — the JS client was not bundled into this install. "
            "Dev checkout: run `npm run build` in js/."
        )
    return path.read_text(encoding="utf-8")


class FigureWidget(anywidget.AnyWidget):
    """The live notebook widget host: a data-less JSON spec plus raw binary
    column buffers, rendered by the shipped ES module."""

    _esm = _STATIC / "index.js"

    # Data-less spec (§9) — tiny JSON, sync'd as a trait.
    spec = traitlets.Dict().tag(sync=True)
    # Encoded columns — raw binary, never JSON, split layout: a list of
    # per-column memoryviews, each transported as its own binary comm frame
    # with no join copy (§29). The traits always hold a *complete* payload —
    # they are the notebook-reopen state, re-synced on a debounce during
    # streaming; the per-tick append push is a custom message with partial
    # buffers (§4 append reuse). The trait stays Any so the client picks the
    # layout from `spec.buffer_layout`, not the trait shape (older saved
    # outputs may still hold a packed blob).
    buffers = traitlets.Any().tag(sync=True)

    def __init__(
        self,
        figure: "Figure",
        *,
        on_hover: Any = None,
        on_click: Any = None,
        on_brush: Any = None,
        on_select: Any = None,
        on_view_change: Any = None,
        on_animation_start: Any = None,
        on_animation_end: Any = None,
        **kwargs: Any,
    ) -> None:
        self._figure = figure
        self._callbacks = ChannelCallbacks(
            on_hover=on_hover,
            on_click=on_click,
            on_brush=on_brush,
            on_select=on_select,
            on_view_change=on_view_change,
            on_animation_start=on_animation_start,
            on_animation_end=on_animation_end,
        )
        spec, bufs = figure.build_payload_split()
        self._configure_transport(spec)
        self._reopen_synced_at = time.monotonic()
        self._reopen_sync_handle: Optional[Any] = None
        super().__init__(spec=spec, buffers=bufs, **kwargs)
        self.on_msg(self._on_custom_msg)

    def _configure_transport(self, spec: dict[str, Any]) -> None:
        """Attach private subscriptions without changing browser behavior."""
        if self._callbacks.on_view_change is not None:
            spec["interaction"] = {
                **spec.get("interaction", {}),
                "_transport_view_change": True,
            }

    def append(
        self,
        trace_id: int,
        x: Any,
        y: Any,
        *,
        color: Any = None,
        size: Any = None,
        stroke: Any = None,
        opacity: Any = None,
        alpha: Any = None,
        stroke_width: Any = None,
        symbol: Any = None,
    ) -> None:
        """Streaming append: extend a trace's data and push the refresh to the
        client.

        The per-tick push is the (small) append message: split buffers only
        for columns the client does not already hold — unchanged traces ship
        as cid-only addressing (§4 append reuse). Notebook-reopen state (the
        synced spec/buffers traits) re-syncs as a complete payload on a
        debounce, so a saved output is at most `REOPEN_SYNC_INTERVAL_S` stale
        instead of paying a full-payload trait sync every tick.

        The debounce timer needs an asyncio event loop running in the
        *calling* thread (the Jupyter kernel's main thread always has one).
        Without one — plain scripts, worker threads — there is nothing to
        defer to, so every append re-syncs the reopen state inline: still
        correct, but the stream pays a full-payload trait sync per tick, so
        high-rate producers should append from the loop thread."""
        msg, buffers = self._figure.append(
            trace_id,
            x,
            y,
            color=color,
            size=size,
            stroke=stroke,
            opacity=opacity,
            alpha=alpha,
            stroke_width=stroke_width,
            symbol=symbol,
        )
        self._configure_transport(msg["spec"])
        self.send(msg, buffers=buffers)
        self._schedule_reopen_sync()

    # Reopen-state debounce (§4): full trait re-syncs are capped at one per
    # interval; a trailing timer (when an event loop is running — the Jupyter
    # kernel always has one) syncs the final state after the stream quiets.
    # Without a loop the sync happens inline, keeping headless use exact.
    REOPEN_SYNC_INTERVAL_S = 1.0

    def _sync_reopen_state(self) -> None:
        self._reopen_sync_handle = None
        self._reopen_synced_at = time.monotonic()
        spec, bufs = self._figure.build_payload_split()
        self._configure_transport(spec)
        with self.hold_sync():
            self.spec = spec
            self.buffers = bufs

    def _schedule_reopen_sync(self) -> None:
        if self._reopen_sync_handle is not None:
            return  # trailing sync already armed
        elapsed = time.monotonic() - self._reopen_synced_at
        if elapsed >= self.REOPEN_SYNC_INTERVAL_S:
            self._sync_reopen_state()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._sync_reopen_state()  # no loop to defer to: stay exact
            return
        self._reopen_sync_handle = loop.call_later(
            self.REOPEN_SYNC_INTERVAL_S - elapsed, self._sync_reopen_state
        )

    def close(self) -> None:
        handle = self._reopen_sync_handle
        if handle is not None:
            handle.cancel()
            self._reopen_sync_handle = None
        super().close()

    # -- programmatic view state (spec/design/view-state.md §5.1) ------------

    def set_view(
        self,
        ranges: Any = None,
        *,
        animate: bool = True,
        history: bool = True,
    ) -> None:
        """Apply a partial per-axis ranges patch through the client's single
        clamped mutation path (merge-patch: absent axes are untouched)."""
        msg = self._figure.state_patch_message(ranges=ranges, animate=animate, history=history)
        self.send(msg)

    def reset_view(self, axes: Any = None) -> None:
        """Navigate to the home ranges (None = the configured reset_axes)."""
        self.send(self._figure.view_nav_message(axes))

    def select(
        self,
        *,
        range: Any = None,
        polygon: Any = None,
        rows: Any = None,
        history: bool = True,
    ) -> None:
        """Programmatic selection. Geometric forms (`range=`/`polygon=`) ship
        to the client and resolve exactly like a gesture; `rows=` resolves
        kernel-side into mask buffers and is non-durable (history is ignored
        for it, and `view_state()` reports only the opaque rows marker)."""
        if rows is not None:
            if range is not None or polygon is not None:
                raise ValueError("pass rows= alone, or range=/polygon= without rows=")
            msg, buffers = self._figure.selection_rows_message(rows)
            self._figure._record_selection({"rows": True})
            self.send(msg, buffers=buffers)
            return
        selection = self._figure._validated_state_selection(range=range, polygon=polygon)
        if selection is None:
            raise ValueError("select() needs range=, polygon=, or rows=")
        self.send(self._figure.state_patch_message(selection=selection, history=history))

    def clear_selection(self) -> None:
        """Clear any selection (durable: history records it)."""
        self.send(self._figure.state_patch_message(selection=None))

    def view_state(self) -> dict[str, Any]:
        """Last committed durable view state (kernel-side cache, §5.1)."""
        return self._figure.view_state()

    def _on_custom_msg(self, widget: Any, content: Any, msg_buffers: Any) -> None:
        # All dispatch and callback semantics live in channel.handle_message
        # (reflex-integration §3.1) — this widget is one transport among
        # (eventually) several; it only owns the anywidget comm send.
        reply = handle_message(self._figure, content, msg_buffers, callbacks=self._callbacks)
        if reply is not None:
            msg, buffers = reply
            self.send(msg, buffers=buffers)
