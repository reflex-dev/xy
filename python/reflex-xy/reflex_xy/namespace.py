"""The xy data plane as a second socket.io namespace on Reflex's server.

Transport decision (spec/design/reflex-integration.md): instead of new HTTP
endpoints, the data plane multiplexes onto the app's existing engine.io
websocket as its own namespace (`/_xy`). socket.io multiplexing means the
browser keeps ONE physical connection for app state and chart data; this
namespace inherits the connection's lifecycle, origin checks, and query
token — anything the app plane gains (auth on connect, proxy config, TLS)
the data plane gets for free, because it *is* the same connection.

Wire shape: metadata is one small JSON object per event; every data column
rides as a native socket.io binary attachment (`bytes` values below), which
the browser receives as `ArrayBuffer`s in-place. No JSON numbers for data,
no base64 (§29) — and no custom length-prefix framing needed, because the
socket.io protocol already delimits attachments.

Events, client -> server:
    sub     {fig, px?}    subscribe; joins the figure room, replies `payload`
    unsub   {fig}         leave the figure room
    msg     {fig, m}      one channel.handle_message dispatch, reply `msg`

Events, server -> client:
    payload {fig, mid?, version, spec, buffer_hashes, buffers} first paint / sparse refresh
    msg     {fig, message, buffers}         handle_message reply or push
    err     {fig, error}                    token unknown/foreign, rebuild failed

Every inbound handler is total: malformed input drops or answers `err`,
never raises (a hostile client must not be able to crash the worker —
channel.py's contract, extended to the transport).
"""

from __future__ import annotations

import asyncio
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Optional

from socketio import AsyncNamespace

from xy.channel import handle_message

from .registry import FigureEntry, FigureRegistry
from .tokens import parse_token

if TYPE_CHECKING:
    from xy._figure import Figure

__all__ = ["XY_NAMESPACE", "XYNamespace"]

#: socket.io namespace for the chart data plane. A namespace name is part of
#: the socket.io protocol, not a URL: it needs no route, no mount, and no
#: reverse-proxy entry beyond what the app's websocket already has.
XY_NAMESPACE = "/_xy"

# One payload/message is screen-bounded by construction (§29); these caps are
# the transport's fail-closed backstop, not a tuning knob.
_MAX_PX_HINT = 8192
_MIN_PX_HINT = 16
_PX_BUCKET = 64
_MAX_PAYLOAD_BUCKETS = 8

# An async callable(token) -> Figure | None: given a parseable figure token,
# rebuild the figure from Reflex state (wired by app.setup; see state_bridge).
RebuildHook = Callable[[str], Awaitable[Optional["Figure"]]]


def _plain(value: Any) -> Any:
    """Best-effort JSON-safe copy for small reply metadata.

    Kernel replies may carry numpy scalars (pick rows). Data buffers never
    pass through here — they ship as binary attachments.
    """
    item = getattr(value, "item", None)
    if callable(item) and getattr(value, "shape", None) == ():
        return item()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _buffer_bytes(buffers: Any) -> list[bytes]:
    """socket.io attaches `bytes`/`bytearray` only; memoryviews must convert.

    This is the single wire copy of each column (the join copy the split
    payload layout avoids does not come back — each column converts alone).
    """
    return [b if isinstance(b, (bytes, bytearray)) else bytes(b) for b in (buffers or [])]


class XYNamespace(AsyncNamespace):
    """Serve registry figures to browser clients over the shared socket."""

    def __init__(
        self,
        registry: FigureRegistry,
        *,
        namespace: str = XY_NAMESPACE,
        rebuild: Optional[RebuildHook] = None,
    ) -> None:
        super().__init__(namespace)
        self.registry = registry
        self._rebuild = rebuild
        # Per-mount transport state. Only hashes from the immediately
        # preceding payload are considered reusable, which bounds both ends
        # to one current screen-sized payload and makes eviction implicit.
        # `mid` is part of the key: two mounts of the same token share one
        # Socket.IO sid but have independent browser-side column caches.
        self._client_columns: dict[tuple[str, str, Optional[str]], set[str]] = {}
        self._subscription_px: dict[tuple[str, str, Optional[str]], Optional[int]] = {}
        self._payload_locks: dict[tuple[str, str, Optional[str]], asyncio.Lock] = {}

    # -- connection lifecycle ------------------------------------------------

    async def on_connect(self, sid: str, environ: dict) -> None:
        """Record the Reflex client token this connection authenticated with.

        The engine.io connection is shared with Reflex's `/_event` namespace,
        so the same `?token=` query string reaches us — session affinity and
        any future connection auth are inherited, not reimplemented.
        """
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        token_list = query.get("token", [])
        await self.save_session(sid, {"client_token": token_list[0] if token_list else None})

    async def on_disconnect(self, sid: str) -> None:
        """Rooms are cleaned up by socket.io; figures outlive the socket.

        Deliberate: a dropped connection (reload, laptop lid, transient
        network) must not destroy server-side figures — the client
        resubscribes with the same tokens on reconnect.
        """
        for key in [key for key in self._subscription_px if key[0] == sid]:
            self._client_columns.pop(key, None)
            self._subscription_px.pop(key, None)
            self._payload_locks.pop(key, None)

    # -- subscription ----------------------------------------------------------

    async def on_sub(self, sid: str, data: Any) -> None:
        token, entry = await self._entry_for(sid, data, allow_rebuild=True)
        if token is None or entry is None:
            return
        px = self._px_hint(data)
        mid = self._mount_id(data)
        key = (sid, token, mid)
        self._subscription_px[key] = px
        await self.enter_room(sid, self._room(token))
        spec, raw = await self._cached_payload(entry, px)
        await self._emit_payload(sid, token, entry.version, spec, raw, mid=mid)

    async def on_unsub(self, sid: str, data: Any) -> None:
        token = self._token_of(data)
        if token is not None:
            mid = self._mount_id(data)
            keys = (
                [key for key in self._subscription_px if key[:2] == (sid, token)]
                if mid is None
                else [(sid, token, mid)]
            )
            for key in keys:
                self._client_columns.pop(key, None)
                self._subscription_px.pop(key, None)
                self._payload_locks.pop(key, None)
            if not any(key[:2] == (sid, token) for key in self._subscription_px):
                await self.leave_room(sid, self._room(token))

    # -- interaction round-trips ----------------------------------------------

    async def on_msg(self, sid: str, data: Any) -> None:
        token, entry = await self._entry_for(sid, data, allow_rebuild=True)
        if token is None or entry is None:
            return
        if isinstance(data, dict) and data.get("v") is not None:
            try:
                message_version = int(data["v"])
            except (TypeError, ValueError):
                message_version = entry.version
            if message_version != entry.version:
                return
        content = data.get("m") if isinstance(data, dict) else None
        async with entry.lock:
            # Kernel work off the event loop: the Rust kernels release the
            # GIL, so a slow view recompute never stalls app-plane traffic.
            reply = await asyncio.to_thread(handle_message, entry.figure, content, None)
        if reply is None:
            return
        message, buffers = reply
        envelope: dict[str, Any] = {
            "fig": token,
            "message": _plain(message),
            "buffers": _buffer_bytes(buffers),
        }
        # Replies are mount-addressed: several charts on one page share one
        # socket, so the client tags requests with a mount id and we echo it.
        mid = data.get("mid") if isinstance(data, dict) else None
        if isinstance(mid, str) and len(mid) <= 64:
            envelope["mid"] = mid
        await self.emit("msg", envelope, to=sid)

    # -- server-side pushes (append/refresh fan-out) ---------------------------

    async def broadcast_message(
        self, token: str, message: dict[str, Any], buffers: Optional[list[bytes]] = None
    ) -> None:
        """Push one channel message to every subscriber of a figure."""
        await self.emit(
            "msg",
            {
                "fig": token,
                "message": _plain(message),
                "buffers": _buffer_bytes(buffers),
            },
            room=self._room(token),
        )

    async def broadcast_payload(self, token: str, entry: FigureEntry) -> None:
        """Push a full refreshed payload (figure rebuilt) to subscribers."""
        subscriptions = [
            (sid, mid, px)
            for (sid, subscribed_token, mid), px in list(self._subscription_px.items())
            if subscribed_token == token
        ]
        by_bucket: dict[int, tuple[dict[str, Any], list[memoryview]]] = {}
        for sid, mid, px in subscriptions:
            bucket = self._px_bucket(px)
            payload = by_bucket.get(bucket)
            if payload is None:
                payload = await self._cached_payload(entry, px)
                by_bucket[bucket] = payload
            await self._emit_payload(sid, token, entry.version, *payload, mid=mid)

    @staticmethod
    def _px_bucket(px: Optional[int]) -> int:
        if px is None:
            return 0
        return min(_MAX_PX_HINT, ((px + _PX_BUCKET - 1) // _PX_BUCKET) * _PX_BUCKET)

    async def _cached_payload(
        self, entry: FigureEntry, px: Optional[int]
    ) -> tuple[dict[str, Any], list[memoryview]]:
        """Build once per figure version/rounded screen width."""
        bucket = self._px_bucket(px)
        key = (entry.version, bucket)
        async with entry.lock:
            cached = entry.payload_cache.get(key)
            if cached is not None:
                return cached
            built = await asyncio.to_thread(
                entry.figure.build_payload_split,
                None if bucket == 0 else bucket,
            )
            entry.payload_cache[key] = built
            while len(entry.payload_cache) > _MAX_PAYLOAD_BUCKETS:
                entry.payload_cache.pop(next(iter(entry.payload_cache)))
            return built

    async def _emit_payload(
        self,
        sid: str,
        token: str,
        version: int,
        spec: dict[str, Any],
        raw: list[memoryview],
        *,
        mid: Optional[str] = None,
    ) -> None:
        """Emit only columns absent from this socket's previous payload.

        Socket.IO is ordered and reliable within a connection. Serializing
        this `(sid, figure)` stream therefore makes the prior manifest a safe
        acknowledgement: a reconnect gets a new sid and starts from empty.
        """
        state_key = (sid, token, mid)
        lock = self._payload_locks.setdefault(state_key, asyncio.Lock())
        async with lock:
            known = self._client_columns.get(state_key, set())
            current: set[str] = set()
            outgoing_hashes: list[str] = []
            outgoing_buffers: list[memoryview] = []
            selected: set[str] = set()
            for column in spec.get("columns", []):
                content_hash = column.get("hash")
                buffer_index = column.get("buf")
                if not isinstance(content_hash, str) or not isinstance(buffer_index, int):
                    raise RuntimeError("split payload column is missing hash/buffer identity")
                if not 0 <= buffer_index < len(raw):
                    raise RuntimeError("split payload column references an unknown buffer")
                current.add(content_hash)
                if content_hash in known or content_hash in selected:
                    continue
                selected.add(content_hash)
                outgoing_hashes.append(content_hash)
                outgoing_buffers.append(raw[buffer_index])
            envelope = {
                "fig": token,
                "version": version,
                "spec": spec,
                "buffer_hashes": outgoing_hashes,
                "buffers": _buffer_bytes(outgoing_buffers),
            }
            if mid is not None:
                envelope["mid"] = mid
            await self.emit("payload", envelope, to=sid)
            self._client_columns[state_key] = current

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _room(token: str) -> str:
        return f"fig:{token}"

    @staticmethod
    def _token_of(data: Any) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        token = data.get("fig")
        if not isinstance(token, str) or not token or len(token) > 512:
            return None
        return token

    @staticmethod
    def _px_hint(data: Any) -> Optional[int]:
        try:
            px = int(data.get("px"))
        except (AttributeError, TypeError, ValueError):
            return None
        return max(_MIN_PX_HINT, min(_MAX_PX_HINT, px))

    @staticmethod
    def _mount_id(data: Any) -> Optional[str]:
        mid = data.get("mid") if isinstance(data, dict) else None
        return mid if isinstance(mid, str) and len(mid) <= 64 else None

    async def _entry_for(
        self, sid: str, data: Any, *, allow_rebuild: bool
    ) -> tuple[Optional[str], Optional[FigureEntry]]:
        """Resolve a message's figure token to a registry entry.

        Enforces token affinity: a state-derived figure token embeds the
        client token it was minted for, and only the connection carrying that
        same client token may touch it. Imperative (opaque) tokens have no
        embedded identity — they rely on unguessability, like the client
        token itself.
        """
        token = self._token_of(data)
        if token is None:
            return None, None
        parsed = parse_token(token)
        if parsed is not None:
            session = await self.get_session(sid)
            if session.get("client_token") != parsed.client_token:
                await self._err(sid, token, "figure belongs to another session")
                return token, None
        entry = self.registry.get(token)
        if entry is None and parsed is not None and allow_rebuild and self._rebuild is not None:
            # Registry miss: worker restarted, or the reconnect landed on a
            # node that never built this figure. Reflex state is the durable
            # record — rebuild the figure from it and carry on (§27 applied
            # to processes: every registered figure is a rebuildable cache).
            try:
                figure = await self._rebuild(token)
            except Exception:  # noqa: BLE001 - rebuild runs user builder code
                figure = None
            if figure is not None:
                entry = self.registry.publish(token, figure, broadcast=False)
        if entry is None:
            await self._err(sid, token, "unknown figure token")
            return token, None
        return token, entry

    async def _err(self, sid: str, token: Optional[str], error: str) -> None:
        await self.emit("err", {"fig": token, "error": error}, to=sid)
