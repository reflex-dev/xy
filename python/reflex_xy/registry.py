"""Per-process figure registry: tokens in Reflex state, figures in here.

The registry is deliberately NOT a distributed store (see
spec/design/reflex-integration.md §4): Reflex state is the durable,
already-distributed source of truth, and every registered figure is a
rebuildable cache of it — the same rule the dossier applies to GPU buffers
(§27). A registry miss (worker restart, reconnect landing on another node)
is recovered by re-running the figure's builder against state, not by
shipping canonical columns through Redis.

Thread model: Reflex runs async handlers on the event loop and sync handlers
in a thread pool, so registry mutation is guarded by a plain threading lock
and never awaits. Broadcast fan-out (the async part) is scheduled onto the
loop captured at setup time; see `schedule_broadcast`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from xy._figure import Figure

__all__ = ["ColumnEntry", "FigureEntry", "FigureRegistry", "registry"]

_logger = logging.getLogger("reflex_xy")

# Idle figures are swept after this long without a subscribe/message/publish.
# Deterministic (state-backed) figures rebuild transparently on the next
# subscribe, so the TTL bounds large figure/data memory, not correctness. Imperative
# `register()` figures do not come back — the sweep is their documented limit.
DEFAULT_TTL_SECONDS = 30 * 60.0
_SWEEP_INTERVAL_SECONDS = 60.0


PushBuffer = bytes | bytearray | memoryview
PushHook = Callable[[str, dict, Sequence[PushBuffer], Optional[int]], Awaitable[None]]


@dataclass
class _QueuedPush:
    """One entry-local outbound message, ordered at figure-lock time."""

    callback: PushHook
    token: str
    message: dict
    buffers: list[PushBuffer]
    version: Optional[int]
    completion: Optional[asyncio.Future[None]] = None


@dataclass
class FigureEntry:
    """One live figure and its wire bookkeeping."""

    figure: "Figure"
    token: str
    version: int = 1
    last_access: float = field(default_factory=time.monotonic)
    # Serializes kernel calls per figure; concurrent figures still
    # parallelize (the kernels release the GIL on the Rust side).
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # The unwired/headless path cannot use the asyncio lock. This lock also
    # makes synchronous message construction atomic with namespace payload/
    # interaction kernels and append mutation/version bump. Code needing both
    # locks always takes ``lock`` then ``sync_lock``; sync callers take only
    # this lock. It remains entry-local, so unrelated figures proceed.
    sync_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    # Number of registry operations currently using this exact generation.
    # The registry mutex protects this counter; the TTL sweep skips a current
    # entry while it is leased. Keeping the count on the immutable generation
    # (rather than by token) means a replacement never inherits an old
    # append's lease.
    active_operations: int = field(default=0, init=False, repr=False, compare=False)
    # Append and view-state messages become observable in the order their
    # figure work acquires ``sync_lock``. The registry mutex protects this
    # short queue bookkeeping; network fan-out starts after ``sync_lock`` is
    # released and remains entry-local.
    _push_queue: deque[_QueuedPush] = field(
        default_factory=deque, init=False, repr=False, compare=False
    )
    _push_drain_scheduled: bool = field(default=False, init=False, repr=False, compare=False)
    # Pinned entries are exempt from the TTL sweep: figures with no rebuild
    # recipe elsewhere (module-level `inline()` charts) live as long as the
    # process, or a sweep would break them permanently after idling.
    pinned: bool = False

    def touch(self) -> None:
        self.last_access = time.monotonic()


@dataclass
class ColumnEntry:
    """One registered column set (the data half of the data-bound tier).

    Column entries are pure rebuildable caches of Reflex state — the
    `@reflex_xy.data` method is the recipe — so they carry none of the
    figure entry's kernel machinery: no locks (a republish replaces the
    whole immutable generation), no pins, always sweepable.
    """

    columns: dict[str, Any]
    token: str
    version: int = 1
    last_access: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_access = time.monotonic()


class FigureRegistry:
    """token -> FigureEntry map with versioning and TTL sweep."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._entries: dict[str, FigureEntry] = {}
        # Data-bound tier: column sets published by @reflex_xy.data vars,
        # and the data-token -> {plan digest} index that lets a column
        # republish rebuild + broadcast every mounted dependent figure. The
        # index is bounded by mounted plans: entries are added when a
        # composite figure binds (namespace sub) and dropped by
        # _unbind_plan_if_unmounted_locked on every transition that can end
        # the mount — unsubscribe, disconnect, release, failed-rebuild
        # cleanup, TTL sweep, and a republish that finds it unmounted.
        self._column_entries: dict[str, ColumnEntry] = {}
        self._digests_by_data_token: dict[str, set[str]] = {}
        # A mounted client remains in its socket room when a TTL sweep evicts
        # a rebuildable figure. Retain only the evicted scalar version while
        # at least one such client is subscribed, so a state-driven rebuild on
        # this worker cannot regress its wire version. Opaque tokens and state
        # tokens with no subscribers leave no unbounded tombstones behind.
        self._evicted_versions: dict[str, int] = {}
        # Only rebuildable subscriptions need registry lifecycle state;
        # socket.io owns rooms for both token families. The inverse indexes
        # make subscribe/unsubscribe/disconnect idempotent and bounded by live
        # connections.
        self._rebuildable_subscribers: dict[str, set[str]] = {}
        self._rebuildable_tokens_by_sid: dict[str, set[str]] = {}
        # Compare-and-insert guards exist only while cache-miss builders are
        # active. A normal publish/release/sweep invalidates the token's
        # current guards, preventing an older awaited builder from
        # resurrecting state that has since changed. Unlike a revision map,
        # this structure is bounded by live rebuild attempts and is removed
        # when they finish.
        self._active_rebuild_guards: dict[str, set[object]] = {}
        self._mutex = threading.RLock()
        self._ttl = float(ttl_seconds)
        # Tokens with a broadcast scheduled but not yet started. Publishes
        # racing an un-started broadcast coalesce into it: the callback reads
        # the entry live, so subscribers always get the newest payload and
        # never a stale intermediate one.
        self._pending_broadcasts: set[str] = set()
        # Captured by setup(); lets sync-handler threads schedule async
        # broadcasts safely. None until the data plane is attached.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # async callback(token, entry) -> None wired by the namespace so
        # publishes reach subscribed clients without a module cycle.
        self._on_publish: Optional[Callable[[str, FigureEntry], Awaitable[None]]] = None
        # async callback(token, message, buffers, version) -> None for append
        # and view-state pushes — the message-shaped data-plane seam.
        self._on_push: Optional[PushHook] = None
        # async callback(token, error, resync) -> None: room-wide err frames
        # for server-side failures with no request to answer (a data
        # republish whose plan bind fails must not leave stale pixels
        # silently frozen).
        self._on_error: Optional[Callable[[str, str, bool], Awaitable[None]]] = None

    # -- wiring ------------------------------------------------------------

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on_publish(self, callback: Callable[[str, FigureEntry], Awaitable[None]]) -> None:
        self._on_publish = callback

    def on_push(
        self,
        callback: PushHook,
    ) -> None:
        self._on_push = callback

    def on_error(self, callback: Callable[[str, str, bool], Awaitable[None]]) -> None:
        self._on_error = callback

    def _schedule_error(self, token: str, error: str, *, resync: bool) -> None:
        """Fan an out-of-band failure to a figure room from any thread."""
        callback = self._on_error
        loop = self._loop
        if callback is None or loop is None:
            return

        async def _run() -> None:
            await callback(token, error, resync)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_run())
        else:
            asyncio.run_coroutine_threadsafe(_run(), loop)

    def _enqueue_push(
        self,
        entry: FigureEntry,
        token: str,
        message: dict,
        buffers: Sequence[PushBuffer],
        version: Optional[int],
        *,
        completion: Optional[asyncio.Future[None]] = None,
    ) -> tuple[bool, Optional[asyncio.AbstractEventLoop]]:
        """Queue one push and claim its drain while ``sync_lock`` is held.

        Returning the loop separately lets the caller schedule network work
        only after releasing ``sync_lock``. A later append/view write can add
        to the queue meanwhile, but it cannot schedule around the earlier
        item because the first enqueue already owns the single drain.
        """
        callback = self._on_push
        loop = self._loop
        if callback is None or loop is None:
            return False, None
        queued = _QueuedPush(callback, token, message, list(buffers), version, completion)
        with self._mutex:
            entry._push_queue.append(queued)
            if entry._push_drain_scheduled:
                return True, None
            entry._push_drain_scheduled = True
        return True, loop

    def _schedule_push_drain(self, loop: asyncio.AbstractEventLoop, entry: FigureEntry) -> None:
        """Start the one event-loop drain claimed by ``_enqueue_push``."""

        def start() -> None:
            loop.create_task(self._drain_push_queue(entry))

        loop.call_soon_threadsafe(start)

    async def _drain_push_queue(self, entry: FigureEntry) -> None:
        """Fan out one generation's prepared pushes in construction order."""
        loop = asyncio.get_running_loop()
        while True:
            with self._mutex:
                if not entry._push_queue:
                    entry._push_drain_scheduled = False
                    return
                queued = entry._push_queue.popleft()
            try:
                await queued.callback(
                    queued.token,
                    queued.message,
                    queued.buffers,
                    queued.version,
                )
            except asyncio.CancelledError:
                with self._mutex:
                    entry._push_drain_scheduled = False
                if queued.completion is not None and not queued.completion.done():
                    queued.completion.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - async transport boundary
                if queued.completion is not None and not queued.completion.done():
                    queued.completion.set_exception(exc)
                else:
                    loop.call_exception_handler(
                        {
                            "message": "reflex_xy view-state push failed",
                            "exception": exc,
                        }
                    )
            else:
                if queued.completion is not None and not queued.completion.done():
                    queued.completion.set_result(None)

    # -- core map ----------------------------------------------------------

    def get(self, token: str) -> Optional[FigureEntry]:
        with self._mutex:
            entry = self._entries.get(token)
            if entry is not None:
                entry.touch()
            return entry

    def get_with_rebuild_guard(self, token: str) -> tuple[Optional[FigureEntry], bool]:
        """Return the current entry and whether a rebuild guard remains valid.

        The snapshot is atomic so namespace requests can distinguish an entry
        provisionally inserted by the active rebuild from one authorized by a
        concurrent normal publish, which invalidates every older guard.
        """
        with self._mutex:
            entry = self._entries.get(token)
            if entry is not None:
                entry.touch()
            return entry, bool(self._active_rebuild_guards.get(token))

    def is_current(self, token: str, entry: FigureEntry) -> bool:
        """Whether ``entry`` is still the live generation for ``token``."""
        with self._mutex:
            return self._entries.get(token) is entry

    def _acquire_operation(self, token: str) -> Optional[FigureEntry]:
        """Lease and return the token's current immutable generation."""
        with self._mutex:
            entry = self._entries.get(token)
            if entry is None:
                return None
            entry.active_operations += 1
            entry.touch()
            return entry

    def _release_operation(self, entry: FigureEntry) -> None:
        """Release a generation lease acquired by ``_acquire_operation``."""
        with self._mutex:
            if entry.active_operations <= 0:
                msg = "figure entry operation lease released without acquire"
                raise RuntimeError(msg)
            entry.active_operations -= 1

    def publish(
        self, token: str, figure: "Figure", *, broadcast: bool = True, pinned: bool = False
    ) -> FigureEntry:
        """Insert or replace a figure under `token` and bump its version.

        Re-publishing the same Figure object is a no-op version-wise unless
        `figure` changed identity: state-var recomputes build a fresh figure,
        which is the signal that subscribers need a new payload.
        """
        with self._mutex:
            entry, changed, reauthorized = self._publish_locked(token, figure, pinned)
        if broadcast and (changed or reauthorized):
            # Re-publishing the identical object means nothing moved; a new
            # figure object is normally the signal subscribers need a fresh
            # payload. Re-authorizing a rebuild-owned entry is the exception:
            # its original fan-out may still fail, so the canonical publisher
            # schedules an independently coalesced delivery of the same version.
            self.schedule_broadcast(token)
        return entry

    def _publish_locked(
        self, token: str, figure: "Figure", pinned: bool
    ) -> tuple[FigureEntry, bool, bool]:
        """The mutation half of ``publish``; the registry mutex must be held.

        Returns ``(entry, changed, reauthorized)`` so callers can schedule the
        broadcast after releasing the mutex.
        """
        entry = self._entries.get(token)
        # A cache-miss rebuild inserts its entry before room fan-out. A
        # canonical same-object publish re-authorizes that provisional
        # generation without bumping its version, but must still own a
        # normal broadcast in case the rebuild-owned fan-out fails.
        reauthorized = entry is not None and bool(self._active_rebuild_guards.get(token))
        # This is a canonical dependency/application publish. Any builder
        # that began from the preceding absence must not overwrite it,
        # even if this entry is released again before that builder ends.
        self._invalidate_rebuild_guards_locked(token)
        if entry is None:
            version = self._evicted_versions.pop(token, 0) + 1
            entry = FigureEntry(figure=figure, token=token, version=version, pinned=pinned)
            self._entries[token] = entry
            changed = True
        else:
            changed = entry.figure is not figure
            if changed:
                # A replacement is a new immutable generation. In-flight
                # handlers keep a self-consistent old figure/version pair
                # instead of observing the old figure with a newly bumped
                # version. Their results are discarded by ``is_current``.
                entry = FigureEntry(
                    figure=figure,
                    token=token,
                    version=entry.version + 1,
                    pinned=entry.pinned or pinned,
                )
                self._entries[token] = entry
            else:
                entry.pinned = entry.pinned or pinned
                entry.touch()
        return entry, changed, reauthorized

    def begin_rebuild(self, token: str) -> tuple[Optional[FigureEntry], Optional[object]]:
        """Atomically return the current entry or guard this missing generation."""
        with self._mutex:
            entry = self._entries.get(token)
            if entry is not None:
                entry.touch()
                return entry, None
            guard = object()
            self._active_rebuild_guards.setdefault(token, set()).add(guard)
            return None, guard

    def finish_rebuild(self, token: str, guard: object) -> None:
        """Release one bounded rebuild guard, whether valid or invalidated."""
        with self._mutex:
            guards = self._active_rebuild_guards.get(token)
            if guards is None:
                return
            guards.discard(guard)
            if not guards:
                self._active_rebuild_guards.pop(token, None)

    def publish_if_missing(
        self,
        token: str,
        figure: "Figure",
        *,
        guard: object,
        pinned: bool = False,
    ) -> tuple[Optional[FigureEntry], bool]:
        """Conditionally insert one rebuilt generation if its guard is current.

        State builders run outside the registry mutex. A normal dependency-
        driven publish or release may therefore change ``token`` while a
        cache-miss rebuild is awaiting user code. A current entry wins; if a
        newer mutation left the token absent, the invalid guard rejects the
        stale rebuild so a later request can retry from current state.

        Returns ``(entry, inserted)``. ``entry`` is ``None`` only when a newer
        mutation invalidated ``guard`` and left the token absent. The caller
        owns fan-out for an inserted rebuild; an existing entry's original
        publisher owns its broadcast.
        """
        with self._mutex:
            entry = self._entries.get(token)
            if entry is not None:
                entry.touch()
                return entry, False
            guards = self._active_rebuild_guards.get(token)
            if guards is None or guard not in guards:
                return None, False
            version = self._evicted_versions.pop(token, 0) + 1
            entry = FigureEntry(figure=figure, token=token, version=version, pinned=pinned)
            self._entries[token] = entry
            return entry, True

    def register(self, figure: "Figure") -> str:
        """Imperative registration: mint an opaque token for a figure.

        The caller owns the lifecycle (`release`) and the figure cannot be
        rebuilt on another node — this is the dev-tier API; the durable path
        is the `@reflex_xy.figure` state var (see tokens.py).
        """
        token = f"xyfig-{uuid.uuid4().hex}"
        self.publish(token, figure, broadcast=False)
        return token

    def release(self, token: str) -> None:
        """Drop a figure while preserving live subscribers' wire continuity."""
        with self._mutex:
            self._invalidate_rebuild_guards_locked(token)
            entry = self._entries.pop(token, None)
            self._retain_removed_version_locked(token, entry)
            self._unbind_plan_if_unmounted_locked(token)

    def remove_if_current(self, token: str, expected: FigureEntry, *, guard: object) -> bool:
        """Remove ``expected`` only while its rebuild guard is still valid.

        Entry identity alone is insufficient: a normal same-object publish
        deliberately preserves the ``FigureEntry`` but invalidates ``guard``.
        This cleanup is not a new canonical mutation, so it does not invalidate
        other active rebuild guards. Version retention follows the same live-
        subscriber rule as release/sweep.
        """
        with self._mutex:
            guards = self._active_rebuild_guards.get(token)
            if guards is None or guard not in guards or self._entries.get(token) is not expected:
                return False
            del self._entries[token]
            self._retain_removed_version_locked(token, expected)
            self._unbind_plan_if_unmounted_locked(token)
            return True

    def _invalidate_rebuild_guards_locked(self, token: str) -> None:
        self._active_rebuild_guards.pop(token, None)

    def _unbind_plan_if_unmounted_locked(self, token: str) -> None:
        """Drop a composite plan token's binding once nothing serves or
        watches it (mutex held; no-op for non-plan tokens).

        This is the other half of the index invariant "bounded by mounted
        plans": ``bind_plan`` inserts on subscribe, and every transition that
        can end a mount — unsubscribe, disconnect, release, failed-rebuild
        cleanup, the TTL sweep — funnels here, so short-lived sessions cannot
        accumulate bindings that only a republish would have collected.
        """
        from .tokens import parse_plan_token

        parsed = parse_plan_token(token)
        if parsed is None:
            return
        if token in self._entries or self._rebuildable_subscribers.get(token):
            return
        digests = self._digests_by_data_token.get(parsed.data_token)
        if digests is not None:
            digests.discard(parsed.digest)
            if not digests:
                self._digests_by_data_token.pop(parsed.data_token, None)

    def _retain_removed_version_locked(self, token: str, entry: Optional[FigureEntry]) -> None:
        if self._rebuildable_subscribers.get(token):
            version = 0 if entry is None else entry.version
            prior_version = self._evicted_versions.get(token, 0)
            if version or prior_version:
                self._evicted_versions[token] = max(version, prior_version)
        else:
            self._evicted_versions.pop(token, None)

    # -- subscription lifecycle -------------------------------------------

    def subscribe(self, token: str, sid: str, rebuildable: bool) -> None:
        """Track one live socket subscription when ``token`` can rebuild.

        Socket.io remains responsible for room membership. This small mirror
        exists only to decide whether a swept version tombstone is needed.
        Repeated calls are idempotent. Passing ``rebuildable=False`` leaves
        opaque tokens untracked and clears a stale classification for the
        same SID/token pair defensively.
        """
        with self._mutex:
            if not rebuildable:
                self._unsubscribe_locked(token, sid)
                return
            self._rebuildable_subscribers.setdefault(token, set()).add(sid)
            self._rebuildable_tokens_by_sid.setdefault(sid, set()).add(token)

    def unsubscribe(self, token: str, sid: str) -> None:
        """Forget one socket subscription, idempotently."""
        with self._mutex:
            self._unsubscribe_locked(token, sid)

    def _unsubscribe_locked(self, token: str, sid: str) -> None:
        subscribers = self._rebuildable_subscribers.get(token)
        if subscribers is not None:
            subscribers.discard(sid)
            if not subscribers:
                self._rebuildable_subscribers.pop(token, None)
                self._evicted_versions.pop(token, None)
                self._unbind_plan_if_unmounted_locked(token)

        tokens = self._rebuildable_tokens_by_sid.get(sid)
        if tokens is not None:
            tokens.discard(token)
            if not tokens:
                self._rebuildable_tokens_by_sid.pop(sid, None)

    def disconnect(self, sid: str) -> None:
        """Forget all rebuildable subscriptions owned by one socket SID."""
        with self._mutex:
            tokens = self._rebuildable_tokens_by_sid.pop(sid, set())
            for token in tokens:
                subscribers = self._rebuildable_subscribers.get(token)
                if subscribers is None:
                    continue
                subscribers.discard(sid)
                if not subscribers:
                    self._rebuildable_subscribers.pop(token, None)
                    self._evicted_versions.pop(token, None)
                    self._unbind_plan_if_unmounted_locked(token)

    def tokens(self) -> list[str]:
        with self._mutex:
            return list(self._entries)

    def __len__(self) -> int:
        with self._mutex:
            return len(self._entries)

    # -- data-bound tier: column entries + plan index ------------------------

    def publish_columns(self, token: str, columns: dict[str, Any]) -> ColumnEntry:
        """Insert or replace a column set, then rebuild every mounted plan
        bound to it (fresh figures under the composite tokens, broadcast by
        the ordinary publish fan-out). Entries are immutable generations: a
        republish replaces the whole entry and bumps its version."""
        with self._mutex:
            previous = self._column_entries.get(token)
            version = 1 if previous is None else previous.version + 1
            entry = ColumnEntry(columns=columns, token=token, version=version)
            self._column_entries[token] = entry
            digests = sorted(self._digests_by_data_token.get(token, ()))
        for digest in digests:
            self._rebuild_dependent(token, digest, entry)
        return entry

    def get_columns(self, token: str) -> Optional[ColumnEntry]:
        with self._mutex:
            entry = self._column_entries.get(token)
            if entry is not None:
                entry.touch()
            return entry

    def release_columns(self, token: str) -> None:
        """Drop a column set and every dependent composite figure entry.

        The "no data right now" path (`@reflex_xy.data` returning None): the
        empty handle unmounts subscribed charts client-side, and dropping
        the dependent figure caches here keeps a later re-mount rebuilding
        from current state instead of serving pre-release columns.
        """
        from .tokens import build_plan_token

        with self._mutex:
            self._column_entries.pop(token, None)
            digests = self._digests_by_data_token.pop(token, set())
        for digest in sorted(digests):
            self.release(build_plan_token(digest, token))

    def bind_plan(self, data_token: str, digest: str) -> None:
        """Record that a mounted plan binds this data token (idempotent)."""
        with self._mutex:
            self._digests_by_data_token.setdefault(data_token, set()).add(digest)

    def _rebuild_dependent(self, data_token: str, digest: str, column_entry: ColumnEntry) -> None:
        """Re-bind one dependent plan against freshly published columns.

        ``column_entry`` is the generation this rebuild serves. Concurrent
        republishes rebuild concurrently and may complete out of order; every
        outcome below (publish, failure release + err frame) is gated on the
        generation still being current — atomically with the registry mutation
        — so an older generation that finishes late can never overwrite a
        newer one's figure or report a stale failure.
        """
        from .plan import plan_of
        from .tokens import build_plan_token, parse_token

        composite = build_plan_token(digest, data_token)
        with self._mutex:
            if self._column_entries.get(data_token) is not column_entry:
                return  # a newer generation owns this rebuild now
            mounted = composite in self._entries or bool(
                self._rebuildable_subscribers.get(composite)
            )
            if not mounted:
                # Nothing serves or watches this plan anymore: forget the
                # binding (the same invariant every unmount transition
                # enforces); a later subscribe rebuilds and re-indexes.
                self._unbind_plan_if_unmounted_locked(composite)
                return
        parsed = parse_token(data_token)
        source = (
            f"{parsed.state_full_name}.{parsed.var_name}" if parsed is not None else "the data var"
        )
        plan = plan_of(digest)
        try:
            if plan is None:
                from .plan import PlanMissError

                raise PlanMissError(digest)
            figure = plan.bind(column_entry.columns, source=source).figure()
        except Exception as exc:  # noqa: BLE001 - user data meets page structure here
            # Fail loud on both sides: the server log carries the bind error,
            # and subscribers get an err frame instead of silently frozen
            # pixels (their bounded resync retries against current state) —
            # unless a newer generation superseded this one meanwhile, in
            # which case the failure is obsolete and it owns the outcome.
            with self._mutex:
                if self._column_entries.get(data_token) is not column_entry:
                    return
                self._invalidate_rebuild_guards_locked(composite)
                removed = self._entries.pop(composite, None)
                self._retain_removed_version_locked(composite, removed)
            _logger.warning("republish of %s failed: %s", composite, exc)
            self._schedule_error(composite, str(exc), resync=True)
            return
        with self._mutex:
            if self._column_entries.get(data_token) is not column_entry:
                return  # a newer generation's figure must win; drop this one
            _, changed, reauthorized = self._publish_locked(composite, figure, False)
        if changed or reauthorized:
            self.schedule_broadcast(composite)

    # -- version bump + fan-out ---------------------------------------------

    def bump(self, token: str, *, expected: Optional[FigureEntry] = None) -> Optional[FigureEntry]:
        """Record an in-place mutation (e.g. append) without broadcast."""
        with self._mutex:
            entry = self._entries.get(token)
            if entry is None or (expected is not None and entry is not expected):
                return None
            entry.version += 1
            entry.touch()
            return entry

    def schedule_broadcast(self, token: str) -> None:
        """Fan a publish out to subscribers from any thread.

        Safe no-op before setup() (no loop yet: nobody can be subscribed
        either, because the namespace is what wires the loop).
        """
        callback = self._on_publish
        loop = self._loop
        if callback is None or loop is None:
            return
        with self._mutex:
            if token in self._pending_broadcasts:
                return  # an un-started broadcast will already ship this state
            self._pending_broadcasts.add(token)

        async def _run() -> None:
            with self._mutex:
                self._pending_broadcasts.discard(token)
                entry = self._entries.get(token)
            if entry is not None:
                await callback(token, entry)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_run())
        else:
            asyncio.run_coroutine_threadsafe(_run(), loop)

    def append(
        self,
        token: str,
        x: Any,
        y: Any,
        *,
        color: Any = None,
        size: Any = None,
        trace: int = 0,
    ) -> None:
        """Stream-append points to a figure and push the delta to subscribers.

        Callable from anywhere — background tasks, sync handlers (thread
        pool), or plain scripts. On a wired app the mutation and fan-out run
        on the serving loop under the figure's lock; unwired (tests,
        headless) the append applies synchronously and there is nobody to
        push to.
        """
        loop = self._loop
        if loop is None:
            entry = self._acquire_operation(token)
            if entry is None:
                msg = f"unknown figure token: {token!r}"
                raise KeyError(msg)
            try:
                # Serialize only this immutable generation. A publish may
                # replace it while append is running; the identity-checked
                # bump below then discards the obsolete result without
                # touching the replacement.
                with entry.sync_lock:
                    entry.figure.append(trace, x, y, color=color, size=size)
                    self.bump(token, expected=entry)
            finally:
                self._release_operation(entry)
            return

        async def _do() -> None:
            entry = self._acquire_operation(token)
            if entry is None:
                return
            try:
                async with entry.lock:
                    completion = loop.create_future()

                    def _append_and_bump() -> tuple[
                        Optional[int], bool, Optional[asyncio.AbstractEventLoop]
                    ]:
                        with entry.sync_lock:
                            message, buffers = entry.figure.append(
                                trace, x, y, color=color, size=size
                            )
                            bumped = self.bump(token, expected=entry)
                            version = None if bumped is None else bumped.version
                            if version is None:
                                return None, False, None
                            enqueued, drain_loop = self._enqueue_push(
                                entry,
                                token,
                                message,
                                list(buffers),
                                version,
                                completion=completion,
                            )
                            return version, enqueued, drain_loop

                    operation_version, enqueued, drain_loop = await asyncio.to_thread(
                        _append_and_bump
                    )
                    if operation_version is None:
                        return  # a replacement won; never mutate/bump its generation
                    if drain_loop is not None:
                        self._schedule_push_drain(drain_loop, entry)
                    if enqueued:
                        # Keep the generation lock until this append becomes
                        # observable, as before. Earlier view writes queued by
                        # ``sync_lock`` drain first; later writes follow it.
                        await completion
            finally:
                self._release_operation(entry)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_do())
        else:
            asyncio.run_coroutine_threadsafe(_do(), loop)

    def push_view_message(
        self, token: str, build: Callable[["Figure"], tuple[dict, list[bytes]]]
    ) -> None:
        """Build one kernel→client message against a figure and push it
        room-wide (spec/design/view-state.md §5.2).

        Mirrors `append`'s threading contract: callable from anywhere. The
        message is built (and its input validated — errors raise to the
        caller) in the calling thread; a wired app then fans the finished
        bytes out on the serving loop as one `msg` event. Construction and
        version capture share the generation's synchronous lock with append,
        so row-mask buffers can never describe a post-append figure while
        carrying its pre-append version. The lock is entry-local and released
        before fan-out; a view write does not mutate or advance the figure.
        """
        entry = self._acquire_operation(token)
        if entry is None:
            msg = f"unknown figure token: {token!r}"
            raise KeyError(msg)
        drain_loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            # The view write does not advance the figure, but it may carry
            # generation-specific row-mask buffers. Append mutates and bumps
            # under this same lock. Enqueueing before release makes the built
            # bytes, captured version, and observable push order one atomic
            # generation snapshot.
            with entry.sync_lock:
                message, built_buffers = build(entry.figure)
                buffers = list(built_buffers)
                operation_version = entry.version
                _enqueued, drain_loop = self._enqueue_push(
                    entry,
                    token,
                    message,
                    buffers,
                    operation_version,
                )
        finally:
            try:
                if drain_loop is not None:
                    self._schedule_push_drain(drain_loop, entry)
            finally:
                self._release_operation(entry)

    def set_view(
        self, token: str, ranges: Any, *, animate: bool = True, history: bool = True
    ) -> None:
        """Room-wide programmatic view patch; see view-state.md §5.2."""
        self.push_view_message(
            token,
            lambda fig: (
                fig.state_patch_message(ranges=ranges, animate=animate, history=history),
                [],
            ),
        )

    def reset_view(self, token: str, axes: Any = None) -> None:
        """Room-wide navigation to the home ranges."""
        self.push_view_message(token, lambda fig: (fig.view_nav_message(axes), []))

    def select(
        self,
        token: str,
        *,
        range: Any = None,
        polygon: Any = None,
        rows: Any = None,
        history: bool = True,
    ) -> None:
        """Room-wide programmatic selection (geometric or rows-resolved)."""
        if rows is not None:
            if range is not None or polygon is not None:
                msg = "pass rows= alone, or range=/polygon= without rows="
                raise ValueError(msg)
            self.push_view_message(token, lambda fig: fig.selection_rows_message(rows))
            return

        def build(fig: "Figure") -> tuple[dict, list[bytes]]:
            selection = fig._validated_state_selection(range=range, polygon=polygon)
            if selection is None:
                msg = "select() needs range=, polygon=, or rows="
                raise ValueError(msg)
            return fig.state_patch_message(selection=selection, history=history), []

        self.push_view_message(token, build)

    def clear_selection(self, token: str) -> None:
        """Room-wide selection clear."""
        self.push_view_message(token, lambda fig: (fig.state_patch_message(selection=None), []))

    # -- TTL sweep -----------------------------------------------------------

    def sweep(self, *, now: Optional[float] = None) -> list[str]:
        """Drop unpinned entries idle past the TTL; returns dropped tokens.

        Column entries sweep under the same TTL: they are state-rebuildable
        caches exactly like state-token figures (a later subscribe re-runs
        the data method), so the sweep bounds column memory, not correctness.
        """
        now = time.monotonic() if now is None else now
        dropped: list[str] = []
        with self._mutex:
            for token, entry in list(self._entries.items()):
                if (
                    not entry.pinned
                    and not entry.active_operations
                    and now - entry.last_access > self._ttl
                ):
                    self._invalidate_rebuild_guards_locked(token)
                    self._retain_removed_version_locked(token, entry)
                    del self._entries[token]
                    self._unbind_plan_if_unmounted_locked(token)
                    dropped.append(token)
            for token, column_entry in list(self._column_entries.items()):
                if now - column_entry.last_access > self._ttl:
                    del self._column_entries[token]
                    dropped.append(token)
        return dropped

    async def sweep_forever(self) -> None:
        """Lifespan task: periodic TTL sweep (backstop for leaked tabs)."""
        while True:
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
            self.sweep()


#: Process-wide registry. One per backend worker by design — see module doc.
#: Everything references this exact object; tests reset it in place.
registry: FigureRegistry = FigureRegistry()


def reset_registry_for_tests() -> FigureRegistry:
    """Reset the process registry in place (test isolation only)."""
    registry._entries.clear()
    registry._column_entries.clear()
    registry._digests_by_data_token.clear()
    registry._evicted_versions.clear()
    registry._rebuildable_subscribers.clear()
    registry._rebuildable_tokens_by_sid.clear()
    registry._active_rebuild_guards.clear()
    registry._pending_broadcasts.clear()
    registry._loop = None
    registry._on_publish = None
    registry._on_push = None
    registry._on_error = None
    registry._ttl = DEFAULT_TTL_SECONDS
    return registry


def _figure_of(chart: Any) -> "Figure":
    """Accept either a public `xy.Chart` or an internal Figure."""
    figure = getattr(chart, "figure", None)
    if callable(figure):
        return figure()
    return chart
