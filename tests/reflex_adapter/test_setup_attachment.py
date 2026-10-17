"""`setup(app)` attaches per app, not per process.

The registry is a process-global cache while Apps are not: a hot reload
re-imports the app module, AppHarness builds one per test, and nothing stops
two Apps coexisting in one interpreter. These tests pin the two consequences —
`setup` must never hand an already-attached app a second channel (Reflex
rejects a duplicate channel name outright), and registry fan-out must reach
every live app rather than only the most recent one.
"""

from __future__ import annotations

import asyncio
import gc
import logging

import numpy as np
import pytest
import reflex as rx
from reflex.istate.manager.memory import StateManagerMemory
from reflex_base.registry import RegistrationContext

import xy
from reflex_xy import app as adapter_app
from reflex_xy.app import setup


def make_app():
    """A real `rx.App`.

    An App claims the registration context it is built in and refuses to share
    it, so every App after the first is built in a fork — which is exactly the
    shape this module is about: several Apps, one process.
    """
    try:
        context = RegistrationContext.get()
    except LookupError:
        app = rx.App()  # the first App in this process claims the context
    else:
        with context.fork():
            app = rx.App()
    app._state_manager = StateManagerMemory()
    return app


def make_figure(n: int = 8):
    xs = np.linspace(0.0, 1.0, n)
    return xy.scatter_chart(xy.scatter(xs, xs * 3.0), width=640, height=400).figure()


def test_setup_is_idempotent_for_one_app():
    app = make_app()
    first = setup(app)
    assert setup(app) is first
    assert list(app._channels) == [first.name]


def test_revisiting_an_app_does_not_register_a_second_channel():
    """A → B → A. Keying idempotency on "the most recent app" would build a
    second channel for A here, and `App.register_channel` raises on the
    duplicate name — turning an ordinary multi-app process into a crash."""
    app_a, app_b = make_app(), make_app()
    channel_a = setup(app_a)
    channel_b = setup(app_b)

    assert channel_a is not channel_b
    assert setup(app_a) is channel_a  # must not raise
    assert list(app_a._channels) == [channel_a.name]
    assert list(app_b._channels) == [channel_b.name]


def test_publish_fans_out_to_every_live_app(_fresh_registry, monkeypatch):
    """The second app must not silently strand the first app's subscribers."""
    registry = _fresh_registry
    app_a, app_b = make_app(), make_app()
    channel_a = setup(app_a)
    channel_b = setup(app_b)
    delivered: list[tuple[str, object]] = []

    for channel in (channel_a, channel_b):

        async def broadcast(token, entry, _channel=channel):
            delivered.append((token, _channel))

        monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        token = registry.register(make_figure())
        registry.publish(token, make_figure(12))
        await asyncio.sleep(0)  # let the scheduled fan-out task run
        await asyncio.sleep(0)
        return token

    token = asyncio.run(main())
    assert sorted(channel is channel_b for _, channel in delivered) == [False, True]
    assert {name for name, _ in delivered} == {token}


def test_a_rebuild_fans_out_to_every_live_app(monkeypatch):
    """A cache-miss rebuild in one app reaches the other app's subscribers too.

    The rebuilt generation carries a new version; a subscriber left on the old
    one would have its hover, pick and selection requests dropped as stale.
    """
    app_a, app_b = make_app(), make_app()
    channel_a, channel_b = setup(app_a), setup(app_b)
    delivered: list[tuple[object, object]] = []

    for channel in (channel_a, channel_b):

        async def broadcast(token, entry, _channel=channel):
            delivered.append((_channel, entry))

        monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def rebuild(token):
        return make_figure()

    monkeypatch.setattr(channel_a, "_rebuild", rebuild)

    async def main():
        return await channel_a._start_rebuild_attempt("evicted")

    entry, failure = asyncio.run(main())

    assert failure is None
    assert {id(channel) for channel, _ in delivered} == {id(channel_a), id(channel_b)}
    assert all(sent is entry for _, sent in delivered)


def _one_plane_fails(
    monkeypatch, channel_a, channel_b
) -> tuple[list[str], list[tuple[str, str, bool]]]:
    """Make app A's payload delivery fail while app B's succeeds.

    Returns:
        The tokens app B received, and the ``(app, token, resync)`` error
        broadcasts either app sent.
    """
    reached: list[str] = []
    errors: list[tuple[str, str, bool]] = []

    async def boom(token, entry):
        raise RuntimeError("transport failed")

    async def ok(token, entry):
        reached.append(token)

    def record(app):
        async def broadcast_error(token, error, resync=False):
            errors.append((app, token, resync))

        return broadcast_error

    monkeypatch.setattr(channel_a, "broadcast_payload", boom)
    monkeypatch.setattr(channel_b, "broadcast_payload", ok)
    monkeypatch.setattr(channel_a, "broadcast_error", record("a"))
    monkeypatch.setattr(channel_b, "broadcast_error", record("b"))
    return reached, errors


def test_one_failing_plane_does_not_swallow_the_others(_fresh_registry, monkeypatch, caplog):
    """A payload another app received is delivered; the failing app resyncs.

    Its subscribers keep the old version, whose requests are dropped as stale,
    so only a resubscribe brings them back.
    """
    registry = _fresh_registry
    app_a, app_b = make_app(), make_app()
    channel_a, channel_b = setup(app_a), setup(app_b)
    reached, errors = _one_plane_fails(monkeypatch, channel_a, channel_b)

    async def main():
        entry = registry.publish("tok", make_figure(), broadcast=False)
        await adapter_app._fan_out_payload("tok", entry)

    with caplog.at_level(logging.ERROR, logger="reflex_xy"):
        asyncio.run(main())
    assert reached == ["tok"], "the healthy plane must still have received the payload"
    assert errors == [("a", "tok", True)]
    assert [
        ("tok" in r.getMessage(), "transport failed" in str(r.exc_info)) for r in caplog.records
    ] == [(True, True)]


def test_a_failed_resync_is_only_logged(_fresh_registry, monkeypatch, caplog):
    """A resync the failing app cannot send either must not undo the delivery."""
    registry = _fresh_registry
    app_a, app_b = make_app(), make_app()
    channel_a, channel_b = setup(app_a), setup(app_b)
    reached, _ = _one_plane_fails(monkeypatch, channel_a, channel_b)

    async def resync_fails(token, error, resync=False):
        raise RuntimeError("resync failed")

    monkeypatch.setattr(channel_a, "broadcast_error", resync_fails)

    async def main():
        entry = registry.publish("tok", make_figure(), broadcast=False)
        await adapter_app._fan_out_payload("tok", entry)

    with caplog.at_level(logging.ERROR, logger="reflex_xy"):
        asyncio.run(main())
    assert reached == ["tok"]
    assert ["resync failed" in str(r.exc_info) for r in caplog.records] == [False, True]


def test_a_payload_no_plane_received_still_raises(_fresh_registry, monkeypatch):
    """With every app failing, the error surfaces as a single-plane send's does."""
    registry = _fresh_registry
    channel = setup(make_app())

    async def boom(token, entry):
        raise RuntimeError("transport failed")

    monkeypatch.setattr(channel, "broadcast_payload", boom)

    async def main():
        entry = registry.publish("tok", make_figure(), broadcast=False)
        with pytest.raises(RuntimeError, match="transport failed"):
            await adapter_app._fan_out_payload("tok", entry)

    asyncio.run(main())


def test_a_rebuild_keeps_a_generation_another_app_received(_fresh_registry, monkeypatch):
    """One app failing to receive a rebuild must not retract it from the others.

    Their subscribers already hold the rebuilt version; removing the entry
    would turn their next versioned interaction into another cache miss.
    """
    registry = _fresh_registry
    app_a, app_b = make_app(), make_app()
    channel_a, channel_b = setup(app_a), setup(app_b)
    reached, errors = _one_plane_fails(monkeypatch, channel_a, channel_b)

    async def rebuild(token):
        return make_figure()

    monkeypatch.setattr(channel_a, "_rebuild", rebuild)

    async def main():
        return await channel_a._start_rebuild_attempt("evicted")

    entry, failure = asyncio.run(main())

    assert failure is None
    assert reached == ["evicted"]
    assert errors == [("a", "evicted", True)]
    assert registry.get("evicted") is entry


def test_a_collected_app_stops_receiving_fan_out():
    """A hot reload replaces the App; the old one must not be kept alive by
    the attachment list, nor keep receiving broadcasts once collected."""
    app_a, app_b = make_app(), make_app()
    setup(app_a)
    setup(app_b)
    assert len(adapter_app._live_planes()) == 2

    del app_a
    gc.collect()

    assert len(adapter_app._live_planes()) == 1
    assert len(adapter_app._attached) == 1
