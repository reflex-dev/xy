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
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from xy._figure import Figure

__all__ = ["FigureEntry", "FigureRegistry", "registry"]

# Idle figures are swept after this long without a subscribe/message/publish.
# Deterministic (state-backed) figures rebuild transparently on the next
# subscribe, so the TTL only bounds memory, not correctness. Imperative
# `register()` figures do not come back — the sweep is their documented limit.
DEFAULT_TTL_SECONDS = 30 * 60.0
_SWEEP_INTERVAL_SECONDS = 60.0


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
    # Pinned entries are exempt from the TTL sweep: figures with no rebuild
    # recipe elsewhere (module-level `inline()` charts) live as long as the
    # process, or a sweep would break them permanently after idling.
    pinned: bool = False

    def touch(self) -> None:
        self.last_access = time.monotonic()


class FigureRegistry:
    """token -> FigureEntry map with versioning and TTL sweep."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._entries: dict[str, FigureEntry] = {}
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
        # async callback(token, message, buffers) -> None for incremental
        # pushes (append) — same seam, message-shaped instead of payload-shaped.
        self._on_push: Optional[Callable[[str, dict, list[bytes]], Awaitable[None]]] = None

    # -- wiring ------------------------------------------------------------

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on_publish(self, callback: Callable[[str, FigureEntry], Awaitable[None]]) -> None:
        self._on_publish = callback

    def on_push(self, callback: Callable[[str, dict, list[bytes]], Awaitable[None]]) -> None:
        self._on_push = callback

    # -- core map ----------------------------------------------------------

    def get(self, token: str) -> Optional[FigureEntry]:
        with self._mutex:
            entry = self._entries.get(token)
            if entry is not None:
                entry.touch()
            return entry

    def publish(
        self, token: str, figure: "Figure", *, broadcast: bool = True, pinned: bool = False
    ) -> FigureEntry:
        """Insert or replace a figure under `token` and bump its version.

        Re-publishing the same Figure object is a no-op version-wise unless
        `figure` changed identity: state-var recomputes build a fresh figure,
        which is the signal that subscribers need a new payload.
        """
        with self._mutex:
            entry = self._entries.get(token)
            if entry is None:
                entry = FigureEntry(figure=figure, token=token, pinned=pinned)
                self._entries[token] = entry
                changed = True
            else:
                changed = entry.figure is not figure
                if changed:
                    entry.figure = figure
                    entry.version += 1
                entry.pinned = entry.pinned or pinned
                entry.touch()
        if broadcast and changed:
            # Re-publishing the identical object means nothing moved; a new
            # figure object is the signal subscribers need a fresh payload.
            self.schedule_broadcast(token)
        return entry

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
        with self._mutex:
            self._entries.pop(token, None)

    def tokens(self) -> list[str]:
        with self._mutex:
            return list(self._entries)

    def __len__(self) -> int:
        with self._mutex:
            return len(self._entries)

    # -- version bump + fan-out ---------------------------------------------

    def bump(self, token: str) -> Optional[FigureEntry]:
        """Record an in-place mutation (e.g. append) without broadcast."""
        with self._mutex:
            entry = self._entries.get(token)
            if entry is None:
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
            entry = self.get(token)
            if entry is None:
                msg = f"unknown figure token: {token!r}"
                raise KeyError(msg)
            entry.figure.append(trace, x, y, color=color, size=size)
            self.bump(token)
            return

        async def _do() -> None:
            entry = self.get(token)
            if entry is None:
                return
            async with entry.lock:
                message, buffers = await asyncio.to_thread(
                    entry.figure.append, trace, x, y, color=color, size=size
                )
                self.bump(token)
            push = self._on_push
            if push is not None:
                await push(token, message, list(buffers))

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_do())
        else:
            asyncio.run_coroutine_threadsafe(_do(), loop)

    # -- TTL sweep -----------------------------------------------------------

    def sweep(self, *, now: Optional[float] = None) -> list[str]:
        """Drop unpinned entries idle past the TTL; returns dropped tokens."""
        now = time.monotonic() if now is None else now
        dropped: list[str] = []
        with self._mutex:
            for token, entry in list(self._entries.items()):
                if not entry.pinned and now - entry.last_access > self._ttl:
                    del self._entries[token]
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
    registry._pending_broadcasts.clear()
    registry._loop = None
    registry._on_publish = None
    registry._on_push = None
    registry._ttl = DEFAULT_TTL_SECONDS
    return registry


def _figure_of(chart: Any) -> "Figure":
    """Accept either a public `xy.Chart` or an internal Figure."""
    figure = getattr(chart, "figure", None)
    if callable(figure):
        return figure()
    return chart
