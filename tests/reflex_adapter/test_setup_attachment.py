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


def test_one_failing_plane_does_not_swallow_the_others(_fresh_registry, monkeypatch):
    registry = _fresh_registry
    app_a, app_b = make_app(), make_app()
    channel_a, channel_b = setup(app_a), setup(app_b)
    reached = []

    async def boom(token, entry):
        raise RuntimeError("transport failed")

    async def ok(token, entry):
        reached.append(token)

    monkeypatch.setattr(channel_a, "broadcast_payload", boom)
    monkeypatch.setattr(channel_b, "broadcast_payload", ok)

    async def main():
        entry = registry.publish("tok", make_figure(), broadcast=False)
        with pytest.raises(RuntimeError, match="transport failed"):
            await adapter_app._fan_out_payload("tok", entry)

    asyncio.run(main())
    assert reached == ["tok"], "the healthy plane must still have received the payload"


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
