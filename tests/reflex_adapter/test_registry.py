from __future__ import annotations

import asyncio

import numpy as np
import pytest
from reflex_xy.registry import FigureRegistry

import xy


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


def test_publish_versioning(_fresh_registry):
    registry = _fresh_registry
    fig1 = make_figure()
    entry = registry.publish("tok", fig1, broadcast=False)
    assert entry.version == 1
    # same object republished: no version bump
    assert registry.publish("tok", fig1, broadcast=False).version == 1
    # new figure object: bump
    assert registry.publish("tok", make_figure(32), broadcast=False).version == 2


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

    token = reflex_xy.register(chart)  # public API accepts the composed Chart
    assert reflex_xy.registry.get(token) is not None


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


@pytest.mark.parametrize("n", [1, 3])
def test_len_and_tokens(_fresh_registry, n):
    registry = _fresh_registry
    tokens = {registry.register(make_figure()) for _ in range(n)}
    assert len(registry) == n
    assert set(registry.tokens()) == tokens
