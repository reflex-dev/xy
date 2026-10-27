from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

import xy
from reflex_xy.registry import FigureRegistry


def make_figure(n: int = 16):
    xs = np.linspace(0.0, 1.0, n)
    return xy.scatter_chart(xy.scatter(xs, xs * 2.0), width=400, height=300).figure()


def test_register_release_roundtrip(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    assert token.startswith("xyfig-")
    assert registry.get(token) is not None
    registry.release(token)
    assert registry.get(token) is None
    registry.release(token)  # idempotent


def test_figure_only_helpers_reject_data_handles_and_junk(_fresh_registry):
    """A DataHandle names columns, never a figure: figure-only operations
    fail immediately instead of resolving to a room that can never exist."""
    import reflex_xy
    from reflex_xy.handles import DataHandle

    data = DataHandle("xyd1|client-token-1234|app.app.State|cloud")
    with pytest.raises(TypeError, match="DataHandle"):
        reflex_xy.release(data)
    with pytest.raises(TypeError, match="DataHandle"):
        reflex_xy.append(data, [0.0], [0.0])
    with pytest.raises(TypeError, match="int"):
        reflex_xy.release(123)  # never silently registry.release("")


def test_release_preserves_version_while_rebuildable_subscriber_remains(
    _fresh_registry,
):
    registry = _fresh_registry
    registry.subscribe("tok", "sid-1", rebuildable=True)
    first = registry.publish("tok", make_figure(), broadcast=False)
    assert registry.bump("tok", expected=first).version == 2

    registry.release("tok")
    assert registry.get("tok") is None
    assert registry._evicted_versions == {"tok": 2}

    republished = registry.publish("tok", make_figure(32), broadcast=False)
    assert republished.version == 3


def test_publish_versioning(_fresh_registry):
    registry = _fresh_registry
    fig1 = make_figure()
    entry = registry.publish("tok", fig1, broadcast=False)
    assert entry.version == 1
    # same object republished: no version bump
    assert registry.publish("tok", fig1, broadcast=False).version == 1
    # new figure object: bump
    assert registry.publish("tok", make_figure(32), broadcast=False).version == 2


def test_publish_if_missing_preserves_a_concurrent_current_generation(
    _fresh_registry,
):
    registry = _fresh_registry
    missing, guard = registry.begin_rebuild("tok")
    assert missing is None
    assert guard is not None
    current_figure = make_figure(8)
    current = registry.publish("tok", current_figure, broadcast=False)

    entry, inserted = registry.publish_if_missing("tok", make_figure(32), guard=guard)
    registry.finish_rebuild("tok", guard)

    assert not inserted
    assert entry is current
    assert entry.figure is current_figure
    assert entry.version == 1
    assert registry.is_current("tok", entry)
    assert registry._active_rebuild_guards == {}


def test_release_invalidates_an_active_rebuild_without_unbounded_revision_state(
    _fresh_registry,
):
    registry = _fresh_registry
    registry.subscribe("tok", "sid-1", rebuildable=True)
    first = registry.publish("tok", make_figure(), broadcast=False)
    assert registry.bump("tok", expected=first).version == 2
    registry.release("tok")

    missing, guard = registry.begin_rebuild("tok")
    assert missing is None
    assert guard is not None
    registry.release("tok")  # a newer canonical absence while the builder awaits

    entry, inserted = registry.publish_if_missing("tok", make_figure(32), guard=guard)
    registry.finish_rebuild("tok", guard)

    assert entry is None
    assert not inserted
    assert registry.get("tok") is None
    assert registry._evicted_versions == {"tok": 2}
    assert registry._active_rebuild_guards == {}
    assert registry.publish("tok", make_figure(32), broadcast=False).version == 3


def test_failed_rebuild_cleanup_is_identity_and_guard_checked(
    _fresh_registry,
):
    registry = _fresh_registry
    registry.subscribe("tok", "sid-1", rebuildable=True)
    missing, guard = registry.begin_rebuild("tok")
    assert missing is None
    assert guard is not None
    inserted, did_insert = registry.publish_if_missing("tok", make_figure(), guard=guard)
    assert inserted is not None
    assert did_insert
    replacement = registry.publish("tok", make_figure(32), broadcast=False)

    assert not registry.remove_if_current("tok", inserted, guard=guard)
    registry.finish_rebuild("tok", guard)
    assert registry.is_current("tok", replacement)
    assert registry._evicted_versions == {}


def test_same_object_publish_invalidates_failed_rebuild_cleanup(_fresh_registry):
    registry = _fresh_registry
    figure = make_figure()
    missing, guard = registry.begin_rebuild("tok")
    assert missing is None
    assert guard is not None
    inserted, did_insert = registry.publish_if_missing("tok", figure, guard=guard)
    assert inserted is not None
    assert did_insert
    assert registry.get_with_rebuild_guard("tok") == (inserted, True)

    authoritative = registry.publish("tok", figure, broadcast=False)

    assert authoritative is inserted
    assert registry.get_with_rebuild_guard("tok") == (inserted, False)
    assert not registry.remove_if_current("tok", inserted, guard=guard)
    registry.finish_rebuild("tok", guard)
    assert registry.is_current("tok", inserted)


def test_same_object_publish_reauthorization_schedules_without_version_bump(_fresh_registry):
    registry = _fresh_registry
    figure = make_figure()
    missing, guard = registry.begin_rebuild("tok")
    assert missing is None
    assert guard is not None
    inserted, did_insert = registry.publish_if_missing("tok", figure, guard=guard)
    assert inserted is not None
    assert did_insert
    seen = []

    async def on_publish(token, entry):
        seen.append((token, entry))

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        registry.on_publish(on_publish)

        authoritative = registry.publish("tok", figure)
        await asyncio.sleep(0)

        assert authoritative is inserted
        assert authoritative.version == 1
        assert seen == [("tok", inserted)]

    asyncio.run(main())
    registry.finish_rebuild("tok", guard)
    assert registry._active_rebuild_guards == {}


def test_failed_rebuild_cleanup_without_subscriber_drops_version(_fresh_registry):
    registry = _fresh_registry
    missing, guard = registry.begin_rebuild("tok")
    assert missing is None
    assert guard is not None
    inserted, did_insert = registry.publish_if_missing("tok", make_figure(), guard=guard)
    assert inserted is not None
    assert did_insert

    assert registry.remove_if_current("tok", inserted, guard=guard)
    registry.finish_rebuild("tok", guard)
    assert registry._evicted_versions == {}
    assert registry.publish("tok", make_figure(32), broadcast=False).version == 1


def test_publish_replacement_creates_a_consistent_generation(_fresh_registry):
    registry = _fresh_registry
    first_figure = make_figure(8)
    first = registry.publish("tok", first_figure, broadcast=False)
    second = registry.publish("tok", make_figure(32), broadcast=False)

    assert second is not first
    assert first.figure is first_figure
    assert first.version == 1
    assert second.version == 2
    assert registry.is_current("tok", second)
    assert not registry.is_current("tok", first)
    assert registry.bump("tok", expected=first) is None
    assert second.version == 2


def test_bump_records_in_place_mutation(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    assert registry.bump(token).version == 2
    assert registry.bump("missing") is None


def test_ttl_sweep(_fresh_registry):
    registry = FigureRegistry(ttl_seconds=0.0)
    token = registry.register(make_figure())
    dropped = registry.sweep(now=registry.get(token).last_access + 1.0)
    assert dropped == [token]
    assert registry.get(token) is None


def test_subscribed_rebuild_after_ttl_sweep_keeps_wire_version_monotonic(
    _fresh_registry,
):
    registry = FigureRegistry(ttl_seconds=0.0)
    registry.subscribe("tok", "sid-1", rebuildable=True)
    first = registry.publish("tok", make_figure(), broadcast=False)
    assert registry.bump("tok", expected=first).version == 2

    assert registry.sweep(now=first.last_access + 1.0) == ["tok"]
    rebuilt = registry.publish("tok", make_figure(), broadcast=False)

    assert rebuilt.version == 3


def test_opaque_sweeps_do_not_retain_version_tombstones(_fresh_registry):
    registry = FigureRegistry(ttl_seconds=0.0)
    registry.subscribe("opaque", "sid-1", rebuildable=False)
    first = registry.publish("opaque", make_figure(), broadcast=False)
    assert registry.bump("opaque", expected=first).version == 2

    assert registry.sweep(now=first.last_access + 1.0) == ["opaque"]
    assert "opaque" not in registry._evicted_versions

    # An opaque token has no automatic rebuild contract. If application code
    # explicitly reuses its string, it starts a fresh wire generation.
    assert registry.publish("opaque", make_figure(), broadcast=False).version == 1


def test_sweep_keeps_recently_touched(_fresh_registry):
    registry = FigureRegistry(ttl_seconds=1000.0)
    token = registry.register(make_figure())
    assert registry.sweep() == []
    assert registry.get(token) is not None


def test_broadcast_scheduling_from_loop_and_thread(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    seen: list[tuple[str, int]] = []

    async def on_publish(tok, entry):
        seen.append((tok, entry.version))

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        registry.on_publish(on_publish)
        # same-loop publish
        registry.publish(token, make_figure(8))
        await asyncio.sleep(0.05)
        # cross-thread publish (sync reflex handlers run in a thread pool)
        await asyncio.to_thread(registry.publish, token, make_figure(4))
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert seen == [(token, 2), (token, 3)]


def test_rapid_publishes_coalesce(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    seen: list[int] = []

    async def on_publish(tok, entry):
        seen.append(entry.version)

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        registry.on_publish(on_publish)
        # Two publishes before the loop can run the first broadcast: one
        # fan-out, carrying the latest state — never a stale intermediate.
        registry.publish(token, make_figure(8))
        registry.publish(token, make_figure(4))
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert seen == [3]


def test_broadcast_noop_before_setup(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    # No loop attached: must not raise, must not queue anything.
    registry.publish(token, make_figure(8))
    assert registry.get(token).version == 2


def test_figure_accepts_chart_or_figure(_fresh_registry):
    registry = _fresh_registry
    xs = np.linspace(0.0, 1.0, 8)
    chart = xy.scatter_chart(xy.scatter(xs, xs), width=300, height=200)
    token_from_chart = registry.register(chart.figure())
    assert registry.get(token_from_chart) is not None

    import reflex_xy

    handle = reflex_xy.register(chart)  # public API accepts the composed Chart
    assert reflex_xy.registry.get(handle.token) is not None


def test_entry_lock_serializes(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    entry = registry.get(token)
    order: list[int] = []

    async def user(i: int):
        async with entry.lock:
            order.append(i)
            await asyncio.sleep(0.01)
            order.append(i)

    async def main():
        await asyncio.gather(user(1), user(2))

    asyncio.run(main())
    assert order in ([1, 1, 2, 2], [2, 2, 1, 1])


def test_unwired_slow_append_does_not_hold_the_registry_mutex(_fresh_registry):
    registry = _fresh_registry
    started = threading.Event()
    resume = threading.Event()

    class BlockingFigure:
        def append(self, *args, **kwargs):
            started.set()
            assert resume.wait(2.0)
            return {"type": "append"}, []

    registry.publish("slow", BlockingFigure(), broadcast=False)
    replacement = make_figure()

    with ThreadPoolExecutor(max_workers=2) as pool:
        append_future = pool.submit(registry.append, "slow", [1.0], [2.0])
        assert started.wait(1.0)
        try:
            replaced = pool.submit(registry.publish, "slow", replacement, broadcast=False).result(
                timeout=0.5
            )
        finally:
            resume.set()
        append_future.result(timeout=1.0)

    current = registry.get("slow")
    assert current is replaced
    assert current.figure is replacement
    assert current.version == 2


def test_forced_sweep_skips_a_generation_with_a_blocking_headless_append(
    _fresh_registry,
):
    registry = FigureRegistry(ttl_seconds=0.0)
    started = threading.Event()
    resume = threading.Event()

    class BlockingFigure:
        def append(self, *args, **kwargs):
            started.set()
            assert resume.wait(2.0)
            return {"type": "append"}, []

    entry = registry.publish("slow", BlockingFigure(), broadcast=False)

    with ThreadPoolExecutor(max_workers=1) as pool:
        append_future = pool.submit(registry.append, "slow", [1.0], [2.0])
        assert started.wait(1.0)
        try:
            forced_now = entry.last_access + 1_000_000.0
            assert registry.sweep(now=forced_now) == []
            assert registry.is_current("slow", entry)
        finally:
            resume.set()
        append_future.result(timeout=1.0)

    assert entry.version == 2
    assert entry.active_operations == 0
    assert registry.sweep(now=entry.last_access + 1_000_000.0) == ["slow"]


def test_forced_sweep_skips_a_generation_with_a_blocking_wired_append(
    _fresh_registry,
):
    registry = FigureRegistry(ttl_seconds=0.0)
    started = threading.Event()
    resume = threading.Event()

    class BlockingFigure:
        def append(self, *args, **kwargs):
            started.set()
            assert resume.wait(2.0)
            return {"type": "append"}, []

    entry = registry.publish("slow", BlockingFigure(), broadcast=False)

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        tasks_before = asyncio.all_tasks()
        registry.append("slow", [1.0], [2.0])
        append_tasks = asyncio.all_tasks() - tasks_before
        assert len(append_tasks) == 1
        append_task = append_tasks.pop()
        assert await asyncio.to_thread(started.wait, 1.0)
        try:
            forced_now = entry.last_access + 1_000_000.0
            assert registry.sweep(now=forced_now) == []
            assert registry.is_current("slow", entry)
        finally:
            resume.set()
        await append_task

    asyncio.run(main())
    assert entry.version == 2
    assert entry.active_operations == 0
    assert registry.sweep(now=entry.last_access + 1_000_000.0) == ["slow"]


def test_unsubscribe_cleans_tombstone_only_after_last_subscriber(_fresh_registry):
    registry = FigureRegistry(ttl_seconds=0.0)
    registry.subscribe("tok", "sid-1", rebuildable=True)
    registry.subscribe("tok", "sid-1", rebuildable=True)  # idempotent
    registry.subscribe("tok", "sid-2", rebuildable=True)
    entry = registry.publish("tok", make_figure(), broadcast=False)
    assert registry.bump("tok", expected=entry).version == 2
    assert registry.sweep(now=entry.last_access + 1.0) == ["tok"]

    registry.unsubscribe("tok", "sid-1")
    registry.unsubscribe("tok", "sid-1")  # idempotent
    assert registry._evicted_versions == {"tok": 2}
    assert registry._rebuildable_subscribers == {"tok": {"sid-2"}}
    assert "sid-1" not in registry._rebuildable_tokens_by_sid

    registry.unsubscribe("tok", "sid-2")
    assert registry._evicted_versions == {}
    assert registry._rebuildable_subscribers == {}
    assert registry._rebuildable_tokens_by_sid == {}


def test_disconnect_cleans_all_tokens_and_is_idempotent(_fresh_registry):
    registry = FigureRegistry(ttl_seconds=0.0)
    registry.subscribe("shared", "sid-1", rebuildable=True)
    registry.subscribe("shared", "sid-2", rebuildable=True)
    registry.subscribe("only-sid-1", "sid-1", rebuildable=True)
    registry.subscribe("only-sid-1", "sid-1", rebuildable=True)  # idempotent

    for token in ("shared", "only-sid-1"):
        entry = registry.publish(token, make_figure(), broadcast=False)
        assert registry.sweep(now=entry.last_access + 1.0) == [token]

    registry.disconnect("sid-1")
    registry.disconnect("sid-1")  # idempotent
    assert registry._evicted_versions == {"shared": 1}
    assert registry._rebuildable_subscribers == {"shared": {"sid-2"}}
    assert registry._rebuildable_tokens_by_sid == {"sid-2": {"shared"}}

    registry.disconnect("sid-2")
    assert registry._evicted_versions == {}
    assert registry._rebuildable_subscribers == {}
    assert registry._rebuildable_tokens_by_sid == {}


@pytest.mark.parametrize("n", [1, 3])
def test_len_and_tokens(_fresh_registry, n):
    registry = _fresh_registry
    tokens = {registry.register(make_figure()) for _ in range(n)}
    assert len(registry) == n
    assert set(registry.tokens()) == tokens
