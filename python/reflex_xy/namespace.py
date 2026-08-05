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
    sub     {fig, px?, mid?} subscribe; joins the figure room, replies `payload`
    unsub   {fig}         leave the figure room
    msg     {fig, v?, mid?, m}  one channel.handle_message dispatch, reply `msg`

Events, server -> client:
    payload {fig, version, spec, buffers, mid?} first paint / full refresh
    msg     {fig, version?, mid?, message, buffers}  reply or room-wide push
    err     {fig, error, resync?}            failure; resync requests a new `sub`

Each successful `sub` begins an authoritative client comparison epoch. Replies
and room-wide pushes carry the FigureEntry version whose data produced them.
Clients gate `msg` events until the epoch's payload arrives, then reject
versions outside that epoch (including stale interaction replies and masks).

Every inbound handler is total: malformed input drops or answers `err`,
never raises (a hostile client must not be able to crash the worker —
channel.py's contract, extended to the transport).
"""

from __future__ import annotations

import asyncio
import urllib.parse
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from socketio import AsyncNamespace

from xy.channel import handle_message

from .plan import PlanError, PlanMissError
from .registry import FigureEntry, FigureRegistry
from .tokens import parse_plan_token, parse_token

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

# socket.io-parser's Decoder ships with `maxAttachments: 10`; a binary packet
# with more attachments makes the BROWSER close the whole shared websocket as
# a parse error — which the app plane then re-opens, re-subscribing every
# chart into an infinite reconnect loop. Figures stay under the limit or fall
# back to the joined single-blob payload (`buffer_layout` != "split", which
# the client's `toSpans` already handles).
_MAX_WIRE_ATTACHMENTS = 10


def _build_wire_payload(
    figure: "Figure", px: Optional[int] = None
) -> tuple[dict[str, Any], list[Any]]:
    """Split-buffer payload, unless it would exceed the attachment limit."""
    spec, raw = figure.build_payload_split(px)
    if len(raw) <= _MAX_WIRE_ATTACHMENTS:
        return spec, raw
    # Rebuild joined rather than concatenating `raw`: the split spec addresses
    # columns by `buf` index and carries `buffer_layout: "split"`, which the
    # client rejects for a one-buffer packet. Running the emitters twice is
    # safe — they only assign shipped_sel/drill state, and the caller holds
    # the figure lock across both builds.
    spec, blob = figure.build_payload(px)
    return spec, [blob]


def _build_entry_payload(
    entry: FigureEntry, px: Optional[int] = None
) -> tuple[dict[str, Any], list[Any]]:
    """Build under ``sync_lock``; the async caller already holds ``lock``."""
    with entry.sync_lock:
        return _build_wire_payload(entry.figure, px)


def _handle_entry_message(entry: FigureEntry, content: Any) -> Any:
    """Dispatch under ``sync_lock``; the async caller already holds ``lock``."""
    with entry.sync_lock:
        return handle_message(entry.figure, content, None)


# An async callable(token) -> Figure | None: given a parseable figure token,
# rebuild the figure from Reflex state (wired by app.setup; see state_bridge).
# May raise PlanError subclasses for spec-aware err frames.
RebuildHook = Callable[[str], Awaitable[Optional["Figure"]]]


@dataclass(frozen=True)
class _RebuildFailure:
    """Client-facing outcome of a failed rebuild attempt."""

    error: str
    resync: bool = False


@dataclass(frozen=True)
class _TokenIdentity:
    """What a figure token reveals: session affinity and rebuildability."""

    affinity_client: Optional[str]
    rebuildable: bool
    plan_bound: Optional[tuple[str, str]] = None  # (data_token, digest)


def _token_identity(token: str) -> _TokenIdentity:
    composite = parse_plan_token(token)
    if composite is not None:
        return _TokenIdentity(
            affinity_client=composite.data.client_token,
            rebuildable=True,
            plan_bound=(composite.data_token, composite.digest),
        )
    parsed = parse_token(token)
    if parsed is not None and parsed.kind == "figure":
        return _TokenIdentity(affinity_client=parsed.client_token, rebuildable=True)
    if parsed is not None:
        # A bare data token names columns, never a figure: enforce affinity
        # (it embeds a session) but never serve or rebuild it as one.
        return _TokenIdentity(affinity_client=parsed.client_token, rebuildable=False)
    return _TokenIdentity(affinity_client=None, rebuildable=False)


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


def _buffer_bytes(
    buffers: Optional[Sequence[bytes | bytearray | memoryview]],
) -> list[bytes | bytearray]:
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
        # Socket.IO may dispatch events for one SID concurrently. Serialize
        # subscribe/unsubscribe for one mount token so a slow rebuild cannot
        # re-add membership after a later unsubscribe. Locks are reference-
        # counted so hostile/abandoned token strings do not create a second
        # process-lifetime cache.
        self._subscription_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._subscription_lock_users: dict[tuple[str, str], int] = {}
        # A page with several same-token mounts can miss concurrently on a
        # cold worker. They share one task, including its failure result and
        # room fan-out, so one cancelled waiter cannot cancel the attempt and
        # a failed builder is not rerun serially by every existing waiter.
        self._rebuild_attempts: dict[
            str, asyncio.Task[tuple[Optional[FigureEntry], Optional[_RebuildFailure]]]
        ] = {}

    # -- connection lifecycle ------------------------------------------------

    async def on_connect(self, sid: str, environ: dict) -> None:
        """Record the Reflex client token presented by this connection.

        The engine.io connection is shared with Reflex's `/_event` namespace,
        so the same `?token=` query string reaches us. Reflex treats this as a
        bearer session identifier (its TokenManager links rather than
        authenticates it); engine-level origin/auth policy is inherited from
        the shared connection.
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
        self.registry.disconnect(sid)

    # -- subscription ----------------------------------------------------------

    async def on_sub(self, sid: str, data: Any) -> None:
        requested_token = self._token_of(data)
        if requested_token is None:
            return
        key = (sid, requested_token)
        lock = self._retain_subscription_lock(key)
        try:
            async with lock:
                token, entry, _initially_missing = await self._entry_for(
                    sid, data, allow_rebuild=True
                )
                if token is None or entry is None or not self._is_connected(sid):
                    return
                await self.enter_room(sid, self._room(token))
                if not self._is_connected(sid):
                    return
                # Mirror membership only after the await-heavy join/rebuild
                # path has proved the SID is still live. A concurrent
                # disconnect can now only remove this record, never precede
                # and be undone by it.
                identity = _token_identity(token)
                self.registry.subscribe(token, sid, rebuildable=identity.rebuildable)
                if identity.plan_bound is not None:
                    # Index the mounted plan before serving, so a column
                    # republish racing this subscribe rebuilds it (the
                    # re-read below then serves that fresher generation).
                    self.registry.bind_plan(*identity.plan_bound)
                # A normal state publish can replace a just-rebuilt entry
                # while its room-wide broadcast is still completing, before
                # this SID joins. Re-read after the join: replacements before
                # this point become the direct response; replacements after
                # it reach the now-joined room even if this send goes stale.
                current_entry = self.registry.get(token)
                if current_entry is None:
                    return
                await self._send_payload(
                    sid,
                    token,
                    current_entry,
                    px=self._px_hint(data),
                    mid=self._mid_of(data),
                )
        finally:
            self._release_subscription_lock(key, lock)

    async def _send_payload(
        self,
        sid: str,
        token: str,
        entry: FigureEntry,
        *,
        px: Optional[int] = None,
        mid: Optional[str] = None,
    ) -> None:
        """Send one authoritative payload if ``entry`` is still current."""
        # Global order whenever both generation locks are needed:
        # async ``entry.lock`` first, then ``entry.sync_lock`` in the worker.
        # Synchronous view pushes take only the latter, so there is no reverse
        # edge and payload/message kernels remain off the event loop.
        async with entry.lock:
            spec, raw = await asyncio.to_thread(_build_entry_payload, entry, px)
        if not self.registry.is_current(token, entry):
            return
        envelope: dict[str, Any] = {
            "fig": token,
            "version": entry.version,
            "spec": spec,
            "buffers": _buffer_bytes(raw),
        }
        if mid is not None:
            envelope["mid"] = mid
        await self.emit(
            "payload",
            envelope,
            to=sid,
        )

    async def on_unsub(self, sid: str, data: Any) -> None:
        token = self._token_of(data)
        if token is not None:
            key = (sid, token)
            lock = self._retain_subscription_lock(key)
            try:
                async with lock:
                    try:
                        await self.leave_room(sid, self._room(token))
                    finally:
                        self.registry.unsubscribe(token, sid)
            finally:
                self._release_subscription_lock(key, lock)

    # -- interaction round-trips ----------------------------------------------

    async def on_msg(self, sid: str, data: Any) -> None:
        message_version: Optional[int] = None
        if isinstance(data, dict) and "v" in data:
            raw_version = data["v"]
            if isinstance(raw_version, bool) or not isinstance(raw_version, int):
                return
            message_version = raw_version
        token, entry, initially_missing = await self._entry_for(sid, data, allow_rebuild=True)
        if token is None or entry is None:
            return
        if initially_missing:
            # The request predates this worker's authoritative payload. The
            # shared attempt already re-primed the room; never resolve its old
            # coordinates even if another waiter rebuilt or versions match.
            return
        content = data.get("m") if isinstance(data, dict) else None
        async with entry.lock:
            if not self.registry.is_current(token, entry):
                return
            operation_version = entry.version
            if message_version is not None and message_version != operation_version:
                return
            # Kernel work off the event loop: the Rust kernels release the
            # GIL, so a slow view recompute never stalls app-plane traffic.
            # ``entry.lock`` -> ``entry.sync_lock`` is the same order used by
            # payload builds and wired append; synchronous view pushes take
            # only the latter and therefore cannot deadlock this path.
            reply = await asyncio.to_thread(_handle_entry_message, entry, content)
            if not self.registry.is_current(token, entry) or entry.version != operation_version:
                return
        if reply is None:
            return
        message, buffers = reply
        wire_buffers = _buffer_bytes(buffers)
        if len(wire_buffers) > _MAX_WIRE_ATTACHMENTS:
            # Never exceed the browser parser's attachment limit: one oversized
            # packet closes the shared websocket for the whole app. Channel
            # replies are bounded by construction, so this is a contract check.
            await self.emit(
                "err", {"fig": token, "error": "reply exceeds wire attachment limit"}, to=sid
            )
            return
        envelope: dict[str, Any] = {
            "fig": token,
            "version": operation_version,
            "message": _plain(message),
            "buffers": wire_buffers,
        }
        # Replies are mount-addressed: several charts on one page share one
        # socket, so the client tags requests with a mount id and we echo it.
        mid = self._mid_of(data)
        if mid is not None:
            envelope["mid"] = mid
        await self.emit("msg", envelope, to=sid)

    # -- server-side pushes (append/refresh fan-out) ---------------------------

    async def broadcast_message(
        self,
        token: str,
        message: dict[str, Any],
        buffers: Optional[Sequence[bytes | bytearray | memoryview]] = None,
        version: Optional[int] = None,
    ) -> None:
        """Push one channel message to every subscriber of a figure."""
        wire_buffers = _buffer_bytes(buffers)
        if len(wire_buffers) > _MAX_WIRE_ATTACHMENTS:
            # This packet goes to a room: one oversized push would close every
            # subscriber's shared websocket at once (see _MAX_WIRE_ATTACHMENTS).
            # Fail loud instead of emitting it. Append pushes also ask clients
            # to resubscribe because the figure advanced; view-state pushes
            # carry a generation stamp but do not mutate the figure payload.
            await self.emit(
                "err",
                {
                    "fig": token,
                    "error": "push exceeds wire attachment limit",
                    "resync": message.get("type") == "append" and version is not None,
                },
                room=self._room(token),
            )
            return
        envelope = {
            "fig": token,
            "message": _plain(message),
            "buffers": wire_buffers,
        }
        if version is not None:
            envelope["version"] = version
        await self.emit("msg", envelope, room=self._room(token))

    async def broadcast_payload(self, token: str, entry: FigureEntry) -> None:
        """Push a full refreshed payload (figure rebuilt) to subscribers."""
        async with entry.lock:
            spec, raw = await asyncio.to_thread(_build_entry_payload, entry)
        if not self.registry.is_current(token, entry):
            return
        await self.emit(
            "payload",
            {
                "fig": token,
                "version": entry.version,
                "spec": spec,
                "buffers": _buffer_bytes(raw),
            },
            room=self._room(token),
        )

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
    def _mid_of(data: Any) -> Optional[str]:
        """Return a validated optional mount id for addressed replies."""
        if not isinstance(data, dict):
            return None
        mid = data.get("mid")
        if not isinstance(mid, str) or len(mid) > 64:
            return None
        return mid

    def _is_connected(self, sid: str) -> bool:
        """Whether Socket.IO still owns ``sid`` in this namespace."""
        server = getattr(self, "server", None)
        manager = getattr(server, "manager", None)
        return manager is not None and manager.is_connected(sid, self.namespace)

    def _retain_subscription_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        lock = self._subscription_locks.setdefault(key, asyncio.Lock())
        self._subscription_lock_users[key] = self._subscription_lock_users.get(key, 0) + 1
        return lock

    def _release_subscription_lock(self, key: tuple[str, str], lock: asyncio.Lock) -> None:
        users = self._subscription_lock_users[key] - 1
        if users:
            self._subscription_lock_users[key] = users
            return
        self._subscription_lock_users.pop(key, None)
        if self._subscription_locks.get(key) is lock:
            self._subscription_locks.pop(key, None)

    def _start_rebuild_attempt(
        self, token: str
    ) -> asyncio.Task[tuple[Optional[FigureEntry], Optional[_RebuildFailure]]]:
        """Start and retain one shared cache-miss attempt for ``token``."""
        # Install the guard before publishing the task in ``_rebuild_attempts``.
        # A concurrent waiter can then distinguish this live attempt from one
        # invalidated by a newer canonical release/absence.
        entry, guard = self.registry.begin_rebuild(token)
        task = asyncio.create_task(self._run_rebuild_attempt(token, entry, guard))
        self._rebuild_attempts[token] = task

        def forget(
            completed: asyncio.Task[tuple[Optional[FigureEntry], Optional[_RebuildFailure]]],
        ) -> None:
            if self._rebuild_attempts.get(token) is completed:
                self._rebuild_attempts.pop(token, None)

        task.add_done_callback(forget)
        return task

    async def _run_rebuild_attempt(
        self,
        token: str,
        entry: Optional[FigureEntry],
        guard: Optional[object],
    ) -> tuple[Optional[FigureEntry], Optional[_RebuildFailure]]:
        """Build, conditionally publish, and fan out one total rebuild attempt."""
        unknown = _RebuildFailure("unknown figure token")
        if entry is not None:
            return entry, None
        if guard is None:  # defensive: a miss always receives one bounded guard
            return None, unknown

        try:
            rebuild = self._rebuild
            if rebuild is None:
                return None, unknown
            try:
                figure = await rebuild(token)
            except PlanError as exc:
                # Spec-aware failures of the data-bound tier: a stale plan
                # digest asks the client to resync (the recompiled page
                # carries the new digest); a bind mismatch names both sides
                # and is not retryable as-is.
                return None, _RebuildFailure(str(exc), resync=isinstance(exc, PlanMissError))
            except Exception:  # noqa: BLE001 - user builder code is an input boundary
                figure = None

            if figure is None:
                # A dependency-driven publish may have won while user code was
                # awaiting. Use it instead of reporting a stale rebuild failure.
                entry = self.registry.get(token)
                if entry is None:
                    return None, unknown
                return entry, None

            entry, inserted = self.registry.publish_if_missing(token, figure, guard=guard)
            if entry is None:
                return None, unknown
            if not inserted:
                return entry, None

            try:
                await self.broadcast_payload(token, entry)
            except Exception:  # noqa: BLE001 - payload build/emit is a protocol boundary
                # A failed generation must not poison later cache hits. Remove
                # only the generation this attempt inserted; if a normal
                # replacement won meanwhile, preserve and return that entry.
                if not self.registry.remove_if_current(token, entry, guard=guard):
                    current = self.registry.get(token)
                    if current is not None:
                        return current, None
                return None, _RebuildFailure("rebuild failed")

            # ``broadcast_payload`` intentionally no-ops when its generation
            # went stale. Resolve that race explicitly: a replacement wins,
            # while a concurrent release becomes a closed error and retry.
            if not self.registry.is_current(token, entry):
                current = self.registry.get(token)
                if current is None:
                    return None, unknown
                return current, None
            return entry, None
        finally:
            self.registry.finish_rebuild(token, guard)

    async def _entry_for(
        self, sid: str, data: Any, *, allow_rebuild: bool
    ) -> tuple[Optional[str], Optional[FigureEntry], bool]:
        """Resolve a message's figure token to a registry entry.

        Enforces token affinity: a state-derived figure token embeds the
        client token it was minted for, and only the connection carrying that
        same client token may touch it. Imperative (opaque) tokens have no
        embedded identity — they rely on unguessability, like the client
        token itself.
        """
        token = self._token_of(data)
        if token is None:
            return None, None, False
        identity = _token_identity(token)
        if identity.affinity_client is not None:
            session = await self.get_session(sid)
            if session.get("client_token") != identity.affinity_client:
                await self._err(sid, token, "figure belongs to another session")
                return token, None, False
        entry, rebuild_guarded = self.registry.get_with_rebuild_guard(token)
        attempt = self._rebuild_attempts.get(token)
        # A normal publish invalidates the old attempt's guard atomically with
        # installing (or re-authorizing) its entry. Requests ordered after that
        # publish must use the authoritative entry immediately rather than wait
        # forever for older user rebuild code. An entry whose guard is still
        # valid remains provisional until its rebuild fan-out completes.
        initially_missing = entry is None or (attempt is not None and rebuild_guarded)
        if (
            identity.rebuildable
            and allow_rebuild
            and self._rebuild is not None
            and initially_missing
        ):
            # The task spans builder, conditional insertion, and existing-room
            # fan-out. All requests that observed this in-flight miss share its
            # result and must drop pre-payload interactions, even when another
            # waiter inserted the entry or its version happens to match.
            # A canonical release can invalidate a hung builder while leaving
            # the token absent. Its task can no longer publish; later requests
            # must start from current state instead of joining it forever.
            if attempt is not None and entry is None and not rebuild_guarded:
                attempt = None
            if attempt is None:
                attempt = self._start_rebuild_attempt(token)
            entry, failure = await asyncio.shield(attempt)
            if failure is not None:
                await self._err(sid, token, failure.error, resync=failure.resync)
                return token, None, initially_missing
        if entry is None:
            await self._err(sid, token, "unknown figure token")
            return token, None, False
        return token, entry, initially_missing

    async def _err(
        self, sid: str, token: Optional[str], error: str, *, resync: bool = False
    ) -> None:
        envelope: dict[str, Any] = {"fig": token, "error": error}
        if resync:
            envelope["resync"] = True
        await self.emit("err", envelope, to=sid)

    async def broadcast_error(self, token: str, error: str, resync: bool = False) -> None:
        """Room-wide err frame for server-side failures with no request to
        answer (e.g. a column republish whose plan bind fails)."""
        envelope: dict[str, Any] = {"fig": token, "error": error}
        if resync:
            envelope["resync"] = True
        await self.emit("err", envelope, room=self._room(token))
