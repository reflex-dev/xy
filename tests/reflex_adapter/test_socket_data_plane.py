"""End-to-end data plane over a real websocket.

Boots the same server stack a Reflex backend uses — python-socketio
AsyncServer (with reflex's JSON config) + engine.io ASGI app mounted at
/_event under uvicorn — registers XYNamespace exactly like `setup(app)`
does, and drives it with the real socket.io client protocol. This is the
transport contract the browser wrapper (XYChart.jsx) relies on, minus the
browser: spec as JSON, columns as native binary attachments, replies
mount-addressed, tokens session-affine, registry misses rebuilt.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from types import SimpleNamespace

import numpy as np
import pytest
import socketio
import uvicorn
from reflex_base.utils import format as reflex_format
from reflex_xy.app import wire
from reflex_xy.namespace import XYNamespace
from reflex_xy.registry import registry
from reflex_xy.tokens import build_state_token

import xy

CLIENT_TOKEN = "11111111-2222-4333-8444-555566667777"
OTHER_TOKEN = "99999999-8888-4777-8666-555544443333"


def make_figure(n: int = 64):
    xs = np.linspace(0.0, 1.0, n)
    ys = xs * 3.0
    return xy.scatter_chart(xy.scatter(xs, ys), width=640, height=400).figure()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def data_plane_server(rebuild=None):
    """AsyncServer configured like reflex's (app.py _setup_state) + XYNamespace."""
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins="*",
        json=SimpleNamespace(
            dumps=staticmethod(reflex_format.json_dumps), loads=staticmethod(json.loads)
        ),
        transports=["websocket"],
        allow_upgrades=False,
    )
    namespace = XYNamespace(registry, rebuild=rebuild)
    sio.register_namespace(namespace)
    wire(namespace)
    registry.attach_loop(asyncio.get_running_loop())
    asgi = socketio.ASGIApp(sio, socketio_path="/_event")

    port = free_port()
    config = uvicorn.Config(asgi, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}", namespace
    finally:
        server.should_exit = True
        await task


async def connect_client(base_url: str, client_token: str = CLIENT_TOKEN):
    """Connect the way XYChart.jsx does: /_xy namespace, token in the query."""
    client = socketio.AsyncClient(reconnection=False)
    await client.connect(
        f"{base_url}?token={client_token}",
        socketio_path="/_event",
        namespaces=["/_xy"],
        transports=["websocket"],
    )
    return client


class Collector:
    """Buffers events from one client for ordered assertions."""

    def __init__(self, client: socketio.AsyncClient) -> None:
        self.payloads: asyncio.Queue = asyncio.Queue()
        self.messages: asyncio.Queue = asyncio.Queue()
        self.errors: asyncio.Queue = asyncio.Queue()
        client.on("payload", self.payloads.put, namespace="/_xy")
        client.on("msg", self.messages.put, namespace="/_xy")
        client.on("err", self.errors.put, namespace="/_xy")

    @staticmethod
    async def next(queue: asyncio.Queue, timeout: float = 5.0):
        return await asyncio.wait_for(queue.get(), timeout)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60.0))


def test_sub_delivers_spec_and_binary_columns(_fresh_registry):
    async def main():
        token = registry.register(make_figure(64))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640, "mid": "m1"}, namespace="/_xy")
            payload = await collector.next(collector.payloads)
            await client.disconnect()
        assert payload["fig"] == token
        assert payload["version"] == 1
        spec = payload["spec"]
        assert spec["buffer_layout"] == "split"
        assert len(spec["traces"]) == 1
        buffers = payload["buffers"]
        # Binary columns arrive as raw bytes (the JS client sees ArrayBuffers):
        # no base64, no JSON numbers (§29 preserved across this transport).
        assert all(isinstance(b, (bytes, bytearray)) for b in buffers)
        xcol = np.frombuffer(buffers[0], dtype=np.float32)
        assert len(xcol) == 64

    run(main())


def test_msg_round_trip_pick_and_select(_fresh_registry):
    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)

            # pick -> exact f64 row readout, mid echoed for mount routing
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "m": {"type": "pick", "trace": 0, "index": 3, "seq": 7},
                },
                namespace="/_xy",
            )
            reply = await collector.next(collector.messages)
            assert reply["mid"] == "m1"
            assert reply["message"]["type"] == "pick_result"
            assert reply["message"]["seq"] == 7
            row = reply["message"]["row"]
            assert row["x"] == pytest.approx(3 / 15)
            assert row["y"] == pytest.approx(3 / 15 * 3.0)

            # select -> selection mask as binary buffers
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "m": {"type": "select", "x0": 0.0, "x1": 0.5, "y0": 0.0, "y1": 3.0},
                },
                namespace="/_xy",
            )
            sel = await collector.next(collector.messages)
            assert sel["message"]["type"] == "selection"
            assert sel["message"]["total"] == 8
            assert len(sel["buffers"]) == 1

            # malformed messages are dropped silently, never crash the server
            await client.emit("msg", {"fig": token, "m": ["not", "a", "dict"]}, namespace="/_xy")
            await client.emit("msg", "garbage", namespace="/_xy")
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "m": {"type": "pick", "trace": 0, "index": 5, "seq": 8},
                },
                namespace="/_xy",
            )
            after = await collector.next(collector.messages)
            assert after["message"]["seq"] == 8
            await client.disconnect()

    run(main())


def test_select_round_trip_includes_semantic_rows(_fresh_registry):
    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "v": 1,
                    "m": {
                        "type": "select",
                        "x0": 0.0,
                        "x1": 0.5,
                        "y0": 0.0,
                        "y1": 3.0,
                        "include_rows": True,
                    },
                },
                namespace="/_xy",
            )
            reply = await collector.next(collector.messages)
            await client.disconnect()
        message = reply["message"]
        assert message["version"] == 1
        assert message["kind"] == "box"
        assert message["rows"][0]["index"] == 0
        assert message["canonical_row_ids"][0]["ids"] == list(range(8))

    run(main())


def test_stale_message_versions_are_dropped(_fresh_registry):
    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)
            registry.publish(token, make_figure(16))
            payload = await collector.next(collector.payloads)
            assert payload["version"] == 2

            message = {"type": "pick", "trace": 0, "index": 2, "seq": 21}
            await client.emit(
                "msg", {"fig": token, "mid": "m1", "v": 1, "m": message}, namespace="/_xy"
            )
            with pytest.raises(asyncio.TimeoutError):
                await Collector.next(collector.messages, timeout=0.15)

            await client.emit(
                "msg", {"fig": token, "mid": "m1", "v": 2, "m": message}, namespace="/_xy"
            )
            current = await collector.next(collector.messages)
            assert current["message"]["seq"] == 21

            message["seq"] = 22
            await client.emit("msg", {"fig": token, "mid": "m1", "m": message}, namespace="/_xy")
            compatible = await collector.next(collector.messages)
            assert compatible["message"]["seq"] == 22
            await client.disconnect()

    run(main())


def test_state_token_affinity_enforced(_fresh_registry):
    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(8), broadcast=False)
        async with data_plane_server() as (url, _):
            # A connection carrying a DIFFERENT reflex client token must not
            # be able to subscribe to this figure.
            thief = await connect_client(url, client_token=OTHER_TOKEN)
            thief_collector = Collector(thief)
            await thief.emit("sub", {"fig": state_token, "mid": "m1"}, namespace="/_xy")
            err = await thief_collector.next(thief_collector.errors)
            assert "another session" in err["error"]

            owner = await connect_client(url, client_token=CLIENT_TOKEN)
            owner_collector = Collector(owner)
            await owner.emit("sub", {"fig": state_token, "mid": "m1"}, namespace="/_xy")
            payload = await owner_collector.next(owner_collector.payloads)
            assert payload["fig"] == state_token
            await thief.disconnect()
            await owner.disconnect()

    run(main())


def test_registry_miss_rebuilds_from_hook(_fresh_registry):
    """The reconnect-lands-on-a-fresh-node path: no figure, hook rebuilds."""
    rebuilt = []

    async def rebuild(token_str):
        rebuilt.append(token_str)
        return make_figure(32)

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        # NOTE: never registered — the registry misses on first sub.
        async with data_plane_server(rebuild=rebuild) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": state_token, "mid": "m1"}, namespace="/_xy")
            payload = await collector.next(collector.payloads)
            assert payload["fig"] == state_token
            assert len(payload["buffers"]) == 2
            await client.disconnect()
        assert rebuilt == [state_token]
        assert registry.get(state_token) is not None

    run(main())


def test_unknown_opaque_token_errors(_fresh_registry):
    async def main():
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": "xyfig-doesnotexist", "mid": "m1"}, namespace="/_xy")
            err = await collector.next(collector.errors)
            assert err["error"] == "unknown figure token"
            await client.disconnect()

    run(main())


def test_publish_broadcasts_to_subscribers(_fresh_registry):
    """State-driven rebuild: publish() pushes a fresh payload to the room."""

    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            first = await collector.next(collector.payloads)
            assert first["version"] == 1

            registry.publish(token, make_figure(48))  # e.g. a dep-driven recompute
            second = await collector.next(collector.payloads)
            assert second["version"] == 2
            xcol = np.frombuffer(second["buffers"][0], dtype=np.float32)
            assert len(xcol) == 48
            await client.disconnect()

    run(main())


def test_append_streams_to_subscribers(_fresh_registry):
    import reflex_xy

    async def main():
        token = registry.register(make_figure(4))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)

            reflex_xy.append(token, x=[2.0, 3.0], y=[6.0, 9.0])
            push = await collector.next(collector.messages)
            assert push["message"]["type"] == "append"
            assert push.get("mid") is None  # pushes are room-wide, not mount-addressed
            assert registry.get(token).version == 2
            assert registry.get(token).figure.traces[0].n_points == 6
            await client.disconnect()

    run(main())


def test_unsub_stops_broadcasts(_fresh_registry):
    async def main():
        token = registry.register(make_figure(8))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)
            await client.emit("unsub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            await asyncio.sleep(0.05)
            registry.publish(token, make_figure(12))
            await asyncio.sleep(0.2)
            assert collector.payloads.empty()
            await client.disconnect()

    run(main())
