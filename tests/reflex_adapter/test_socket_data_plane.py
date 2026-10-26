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
import threading
from types import SimpleNamespace
from typing import TypedDict

import numpy as np
import pytest
import reflex as rx
import socketio
import uvicorn
from reflex.istate.manager.memory import StateManagerMemory
from reflex_base.utils import format as reflex_format

import reflex_xy
import xy
from reflex_xy.app import wire
from reflex_xy.namespace import XYNamespace
from reflex_xy.plan import build_plan
from reflex_xy.registry import registry
from reflex_xy.state_bridge import make_rebuild_hook
from reflex_xy.tokens import build_data_token, build_plan_token, build_state_token

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


class _ObservedLock:
    """Expose the second acquisition attempt without weakening serialization."""

    def __init__(self):
        self._lock = threading.Lock()
        self._attempts_lock = threading.Lock()
        self._attempts = 0
        self.second_attempted = threading.Event()

    def __enter__(self):
        with self._attempts_lock:
            self._attempts += 1
            if self._attempts == 2:
                self.second_attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, *_exc):
        self._lock.release()


def test_payload_build_serializes_with_view_push_per_figure(_fresh_registry, monkeypatch):
    """Payload emitter state and row-mask construction cannot overlap."""
    import reflex_xy.namespace as namespace_module

    primary = _fresh_registry.publish("primary", make_figure(8), broadcast=False)
    other = _fresh_registry.publish("other", make_figure(8), broadcast=False)
    primary.sync_lock = _ObservedLock()
    payload_started = threading.Event()
    release_payload = threading.Event()
    primary_view_entered = threading.Event()
    other_view_entered = threading.Event()

    def blocked_payload(_figure, _px=None):
        payload_started.set()
        assert release_payload.wait(5.0)
        return {"buffer_layout": "split"}, []

    def primary_view(_figure):
        primary_view_entered.set()
        return {"type": "selection_rows"}, []

    def other_view(_figure):
        other_view_entered.set()
        return {"type": "state_patch"}, []

    namespace = XYNamespace(_fresh_registry)

    async def emit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(namespace_module, "_build_wire_payload", blocked_payload)
    monkeypatch.setattr(namespace, "emit", emit)

    async def main():
        tasks = []
        payload_task = asyncio.create_task(namespace._send_payload("sid", "primary", primary))
        tasks.append(payload_task)
        try:
            assert await asyncio.to_thread(payload_started.wait, 1.0)
            primary_view_task = asyncio.create_task(
                asyncio.to_thread(_fresh_registry.push_view_message, "primary", primary_view)
            )
            tasks.append(primary_view_task)
            assert await asyncio.to_thread(primary.sync_lock.second_attempted.wait, 1.0)
            assert not primary_view_entered.is_set()

            # The lock is generation-local: a different figure still builds
            # while the primary payload kernel is deliberately blocked.
            other_view_task = asyncio.create_task(
                asyncio.to_thread(_fresh_registry.push_view_message, "other", other_view)
            )
            tasks.append(other_view_task)
            await asyncio.wait_for(asyncio.shield(other_view_task), 1.0)
            assert other_view_entered.is_set()
        finally:
            release_payload.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    run(main())

    assert primary_view_entered.is_set()
    assert primary.active_operations == 0
    assert other.active_operations == 0


def test_interaction_serializes_with_view_push_per_figure(_fresh_registry, monkeypatch):
    """Interaction/drill state and caller-thread view writes cannot overlap."""
    import reflex_xy.namespace as namespace_module

    primary = _fresh_registry.publish("primary", make_figure(8), broadcast=False)
    other = _fresh_registry.publish("other", make_figure(8), broadcast=False)
    primary.sync_lock = _ObservedLock()
    interaction_started = threading.Event()
    release_interaction = threading.Event()
    primary_view_entered = threading.Event()
    other_view_entered = threading.Event()

    def blocked_interaction(_figure, _message, _buffers):
        interaction_started.set()
        assert release_interaction.wait(5.0)
        return None

    def primary_view(_figure):
        primary_view_entered.set()
        return {"type": "state_patch"}, []

    def other_view(_figure):
        other_view_entered.set()
        return {"type": "state_patch"}, []

    namespace = XYNamespace(_fresh_registry)
    monkeypatch.setattr(namespace_module, "handle_message", blocked_interaction)

    async def main():
        tasks = []
        interaction_task = asyncio.create_task(
            namespace.on_msg(
                "sid",
                {"fig": "primary", "v": primary.version, "m": {"type": "pick"}},
            )
        )
        tasks.append(interaction_task)
        try:
            assert await asyncio.to_thread(interaction_started.wait, 1.0)
            primary_view_task = asyncio.create_task(
                asyncio.to_thread(_fresh_registry.push_view_message, "primary", primary_view)
            )
            tasks.append(primary_view_task)
            assert await asyncio.to_thread(primary.sync_lock.second_attempted.wait, 1.0)
            assert not primary_view_entered.is_set()

            other_view_task = asyncio.create_task(
                asyncio.to_thread(_fresh_registry.push_view_message, "other", other_view)
            )
            tasks.append(other_view_task)
            await asyncio.wait_for(asyncio.shield(other_view_task), 1.0)
            assert other_view_entered.is_set()
        finally:
            release_interaction.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    run(main())

    assert primary_view_entered.is_set()
    assert primary.active_operations == 0
    assert other.active_operations == 0


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
        assert payload["mid"] == "m1"
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


def test_sub_over_attachment_limit_ships_single_blob(_fresh_registry):
    """socket.io-parser's browser Decoder defaults to `maxAttachments: 10` and
    closes the WHOLE shared websocket ("too many attachments" -> "parse
    error") on any binary packet exceeding it — which then reconnect-loops
    the app. Buffer-heavy figures must fall back to the joined single-blob
    payload, which the wrapper's `toSpans` handles via `buffer_layout`."""

    async def main():
        xs = np.linspace(0.0, 1.0, 64)
        figure = xy.scatter_chart(
            *[xy.scatter(xs, xs * k, color=xs, size=xs) for k in (1.0, 2.0, 3.0)],
            width=640,
            height=400,
        ).figure()
        _, raw = figure.build_payload_split(640)
        assert len(raw) > 10, "premise: this figure must exceed the parser cap"
        token = registry.register(figure)
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640}, namespace="/_xy")
            payload = await collector.next(collector.payloads)
            await client.disconnect()
        assert payload["fig"] == token
        assert payload["spec"].get("buffer_layout") != "split"
        assert len(payload["buffers"]) == 1

    run(main())


@pytest.mark.parametrize(
    ("message_type", "resync"),
    [("append", True), ("selection_rows", False)],
)
def test_broadcast_over_attachment_limit_answers_err_not_msg(_fresh_registry, message_type, resync):
    """Room pushes over the parser cap fail loud without an invalid packet.

    Only append needs a payload resync: a generation-stamped view-state push
    does not itself advance the figure.
    """

    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, namespace):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640}, namespace="/_xy")
            await collector.next(collector.payloads)
            await namespace.broadcast_message(
                token, {"type": message_type}, [b"\x00" * 4] * 11, version=2
            )
            error = await collector.next(collector.errors)
            await client.disconnect()
        assert error["fig"] == token
        assert "attachment" in error["error"]
        assert error["resync"] is resync
        assert collector.messages.empty()

    run(main())


def test_msg_reply_over_attachment_limit_answers_err_not_msg(_fresh_registry, monkeypatch):
    """The `on_msg` reply guard: channel replies are bounded by construction,
    so a reply over the parser's attachment cap is a contract violation — the
    client must get an `err` envelope, never a `msg` whose packet the browser
    parser would reject (closing the shared websocket)."""

    from reflex_xy import namespace as namespace_module

    def oversized_reply(figure, message, buffers):
        return {"kind": "pick"}, [b"\x00" * 4] * 11

    monkeypatch.setattr(namespace_module, "handle_message", oversized_reply)

    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640}, namespace="/_xy")
            await collector.next(collector.payloads)
            await client.emit(
                "msg", {"fig": token, "m": {"kind": "pick"}, "mid": "m1"}, namespace="/_xy"
            )
            error = await collector.next(collector.errors)
            await client.disconnect()
        assert error["fig"] == token
        assert "attachment" in error["error"]
        assert collector.messages.empty()

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

            for seq, malformed_version in enumerate((None, True, 2.0, "2", {}, []), start=23):
                message["seq"] = seq
                await client.emit(
                    "msg",
                    {
                        "fig": token,
                        "mid": "m1",
                        "v": malformed_version,
                        "m": message,
                    },
                    namespace="/_xy",
                )
                with pytest.raises(asyncio.TimeoutError):
                    await Collector.next(collector.messages, timeout=0.1)

            message["seq"] = 21
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


def test_reply_from_replaced_generation_is_dropped(_fresh_registry, monkeypatch):
    started = threading.Event()
    resume = threading.Event()

    def slow_handle_message(figure, content, callbacks):
        started.set()
        assert resume.wait(timeout=5)
        return {"type": "pick_result", "seq": 99, "row": None}, []

    monkeypatch.setattr("reflex_xy.namespace.handle_message", slow_handle_message)

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
                    "m": {"type": "pick", "trace": 0, "index": 2, "seq": 99},
                },
                namespace="/_xy",
            )
            assert await asyncio.to_thread(started.wait, 5)
            registry.publish(token, make_figure(32))
            resume.set()

            replacement = await collector.next(collector.payloads)
            assert replacement["version"] == 2
            with pytest.raises(asyncio.TimeoutError):
                await Collector.next(collector.messages, timeout=0.15)
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


def test_concurrent_registry_misses_share_one_current_rebuild(_fresh_registry, monkeypatch):
    """Same-token misses share one generation and one resync epoch."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume = asyncio.Event()
    rebuild_calls = 0
    broadcasts = []

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        started.set()
        await resume.wait()
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)

    async def main():
        data = {"fig": state_token}
        first = asyncio.create_task(namespace._entry_for("sid-1", data, allow_rebuild=True))
        await started.wait()
        second = asyncio.create_task(namespace._entry_for("sid-2", data, allow_rebuild=True))
        await asyncio.sleep(0)
        resume.set()
        results = await asyncio.gather(first, second)

        entries = [result[1] for result in results]
        assert rebuild_calls == 1
        assert entries[0] is entries[1]
        assert registry.is_current(state_token, entries[0])
        assert all(result[2] for result in results)
        assert broadcasts == [(state_token, entries[0])]
        assert namespace._rebuild_attempts == {}

    run(main())


def test_concurrent_messages_that_miss_drop_old_coordinates(_fresh_registry, monkeypatch):
    """Every request in a shared miss epoch waits for payload and retries."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume = asyncio.Event()
    rebuild_calls = 0
    handled = []

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        started.set()
        await resume.wait()
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def broadcast(token, entry):
        assert token == state_token
        assert registry.is_current(token, entry)

    def handle(figure, message, buffers):
        handled.append((figure, message, buffers))
        return None

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)
    monkeypatch.setattr("reflex_xy.namespace.handle_message", handle)

    async def main():
        first = asyncio.create_task(
            namespace.on_msg(
                "sid-1",
                {"fig": state_token, "m": {"type": "pick", "trace": 0, "index": 1}},
            )
        )
        await started.wait()
        # Version 1 also matches a fresh worker's rebuilt version. The request
        # must still drop because it was sent before that worker's payload.
        second = asyncio.create_task(
            namespace.on_msg(
                "sid-2",
                {
                    "fig": state_token,
                    "v": 1,
                    "m": {"type": "pick", "trace": 0, "index": 2},
                },
            )
        )
        await asyncio.sleep(0)
        resume.set()
        await asyncio.gather(first, second)
        await asyncio.sleep(0)

        assert rebuild_calls == 1
        assert handled == []
        assert namespace._rebuild_attempts == {}

    run(main())


def test_failed_rebuild_attempt_is_shared_then_later_request_retries(_fresh_registry, monkeypatch):
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume = asyncio.Event()
    rebuild_calls = 0
    errors = []
    broadcasts = []

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        if rebuild_calls == 1:
            started.set()
            await resume.wait()
            return None
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "_err", send_error)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)

    async def main():
        data = {"fig": state_token}
        first = asyncio.create_task(namespace._entry_for("sid-1", data, allow_rebuild=True))
        await started.wait()
        second = asyncio.create_task(namespace._entry_for("sid-2", data, allow_rebuild=True))
        await asyncio.sleep(0)
        resume.set()
        first_results = await asyncio.gather(first, second)
        await asyncio.sleep(0)

        assert rebuild_calls == 1
        assert all(result == (state_token, None, True) for result in first_results)
        assert sorted(sid for sid, _, _ in errors) == ["sid-1", "sid-2"]
        assert all(token == state_token for _, token, _ in errors)
        assert all(error == "unknown figure token" for _, _, error in errors)
        assert namespace._rebuild_attempts == {}

        retried = await namespace._entry_for("sid-3", data, allow_rebuild=True)
        await asyncio.sleep(0)
        assert rebuild_calls == 2
        assert retried[0] == state_token
        assert retried[1] is not None
        assert retried[2]
        assert registry.is_current(state_token, retried[1])
        assert broadcasts == [(state_token, retried[1])]
        assert namespace._rebuild_attempts == {}

    run(main())


def test_rebuild_broadcast_failure_removes_generation_and_later_sub_retries(
    _fresh_registry, monkeypatch
):
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    registry.subscribe(state_token, "sid-existing", rebuildable=True)
    prior = registry.publish(state_token, make_figure(8), broadcast=False)
    assert registry.bump(state_token, expected=prior).version == 2
    registry.release(state_token)

    errors = []
    broadcasts = []
    joined = []
    sent = []
    rebuild_calls = 0

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)
    namespace._set_server(
        SimpleNamespace(manager=SimpleNamespace(is_connected=lambda sid, _namespace: True))
    )

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def broadcast(token, entry):
        assert token == state_token
        assert registry.is_current(token, entry)
        broadcasts.append(entry)
        if len(broadcasts) == 1:
            raise RuntimeError("transport failed")

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    async def enter_room(sid, room):
        joined.append((sid, room))

    async def send_payload(sid, token, entry, **kwargs):
        sent.append((sid, token, entry, kwargs))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)
    monkeypatch.setattr(namespace, "_err", send_error)
    monkeypatch.setattr(namespace, "enter_room", enter_room)
    monkeypatch.setattr(namespace, "_send_payload", send_payload)

    async def main():
        await namespace.on_sub("sid-1", {"fig": state_token, "mid": "m1"})
        await asyncio.sleep(0)

        assert errors == [("sid-1", state_token, "rebuild failed")]
        assert registry.get(state_token) is None
        assert registry._evicted_versions == {state_token: 3}
        assert joined == []
        assert sent == []
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

        await namespace.on_sub("sid-2", {"fig": state_token, "mid": "m2", "px": 321})
        await asyncio.sleep(0)

        assert rebuild_calls == 2
        assert [entry.version for entry in broadcasts] == [3, 4]
        assert joined == [("sid-2", namespace._room(state_token))]
        assert len(sent) == 1
        sid, token, entry, kwargs = sent[0]
        assert (sid, token, entry.version, kwargs) == (
            "sid-2",
            state_token,
            4,
            {"px": 321, "mid": "m2"},
        )
        assert registry.is_current(state_token, entry)
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_rebuild_failure_cleanup_does_not_remove_a_concurrent_replacement(
    _fresh_registry, monkeypatch
):
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    replacement_figure = make_figure(48)
    replacement = None
    errors = []

    async def rebuild(token_str):
        assert token_str == state_token
        return make_figure(16)

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def fail_after_replacement(token, entry):
        nonlocal replacement
        assert token == state_token
        assert registry.is_current(token, entry)
        replacement = registry.publish(token, replacement_figure, broadcast=False)
        raise RuntimeError("old generation transport failed")

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", fail_after_replacement)
    monkeypatch.setattr(namespace, "_err", send_error)

    async def main():
        token, entry, initially_missing = await namespace._entry_for(
            "sid-1", {"fig": state_token}, allow_rebuild=True
        )
        await asyncio.sleep(0)

        assert token == state_token
        assert initially_missing
        assert replacement is not None
        assert entry is replacement
        assert entry.figure is replacement_figure
        assert entry.version == 2
        assert registry.is_current(state_token, entry)
        assert errors == []
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_rebuild_failure_cleanup_preserves_same_object_authoritative_publish(
    _fresh_registry, monkeypatch
):
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    registry.subscribe(state_token, "sid-existing", rebuildable=True)
    rebuilt_figure = make_figure(16)
    published = None
    errors = []
    fanouts = []
    delivered = asyncio.Event()

    async def rebuild(token_str):
        assert token_str == state_token
        return rebuilt_figure

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def fail_then_deliver_from_publish(token, entry):
        nonlocal published
        assert token == state_token
        assert entry.figure is rebuilt_figure
        fanouts.append((token, entry))
        if len(fanouts) == 1:
            # This is the rebuild-owned fan-out. A canonical publish of the
            # same object keeps the version but must schedule its own delivery
            # before this stale attempt fails.
            published = registry.publish(token, rebuilt_figure)
            assert published is entry
            raise RuntimeError("old fan-out failed")
        assert registry._rebuildable_subscribers[state_token] == {"sid-existing"}
        delivered.set()

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", fail_then_deliver_from_publish)
    monkeypatch.setattr(namespace, "_err", send_error)

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        registry.on_publish(namespace.broadcast_payload)
        token, entry, initially_missing = await namespace._entry_for(
            "sid-1", {"fig": state_token}, allow_rebuild=True
        )
        await asyncio.wait_for(delivered.wait(), timeout=1.0)

        assert token == state_token
        assert initially_missing
        assert published is not None
        assert entry is published
        assert entry.figure is rebuilt_figure
        assert entry.version == 1
        assert registry.is_current(state_token, entry)
        assert errors == []
        assert fanouts == [(state_token, entry), (state_token, entry)]
        assert registry._pending_broadcasts == set()
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_rebuild_completion_does_not_replace_a_concurrent_state_publish(
    _fresh_registry, monkeypatch
):
    """A dependency-driven publish that lands during user rebuild code wins."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume = asyncio.Event()
    rebuilt_figure = make_figure(16)
    current_figure = make_figure(48)
    broadcasts = []

    async def rebuild(token_str):
        assert token_str == state_token
        started.set()
        await resume.wait()
        return rebuilt_figure

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)

    async def main():
        pending = asyncio.create_task(
            namespace._entry_for("sid-1", {"fig": state_token}, allow_rebuild=True)
        )
        await started.wait()
        published = registry.publish(state_token, current_figure, broadcast=False)
        resume.set()
        token, entry, initially_missing = await pending

        assert token == state_token
        assert initially_missing
        assert entry is published
        assert entry.figure is current_figure
        assert registry.is_current(state_token, entry)
        assert broadcasts == []
        assert namespace._rebuild_attempts == {}

    run(main())


def test_later_requests_bypass_slow_rebuild_after_authoritative_publish(
    _fresh_registry, monkeypatch
):
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume = asyncio.Event()
    rebuild_calls = 0
    current_figure = make_figure(48)
    joined = []
    sent = []
    handled = []

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        started.set()
        await resume.wait()
        return make_figure(16)

    namespace = XYNamespace(registry, rebuild=rebuild)
    namespace._set_server(
        SimpleNamespace(manager=SimpleNamespace(is_connected=lambda sid, _namespace: True))
    )

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def enter_room(sid, room):
        joined.append((sid, room))

    async def send_payload(sid, token, entry, **kwargs):
        sent.append((sid, token, entry, kwargs))

    async def unexpected_broadcast(token, entry):
        raise AssertionError("the stale rebuild must not own authoritative fan-out")

    def handle(figure, message, buffers):
        handled.append((figure, message, buffers))
        return None

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "enter_room", enter_room)
    monkeypatch.setattr(namespace, "_send_payload", send_payload)
    monkeypatch.setattr(namespace, "broadcast_payload", unexpected_broadcast)
    monkeypatch.setattr("reflex_xy.namespace.handle_message", handle)

    async def main():
        original = asyncio.create_task(
            namespace._entry_for("sid-original", {"fig": state_token}, allow_rebuild=True)
        )
        await started.wait()
        assert registry._active_rebuild_guards

        published = registry.publish(state_token, current_figure, broadcast=False)
        assert registry._active_rebuild_guards == {}
        assert not original.done()

        message = {"type": "pick", "trace": 0, "index": 1}
        later_sub = asyncio.create_task(
            namespace.on_sub("sid-sub", {"fig": state_token, "mid": "m1", "px": 321})
        )
        later_msg = asyncio.create_task(
            namespace.on_msg(
                "sid-msg",
                {"fig": state_token, "v": published.version, "m": message},
            )
        )
        later_tasks = {later_sub, later_msg}
        _done, blocked = await asyncio.wait(later_tasks, timeout=0.5)
        blocked_at_deadline = set(blocked)
        if blocked_at_deadline:
            resume.set()
            await asyncio.gather(original, *later_tasks)
        assert not blocked_at_deadline
        await asyncio.gather(*later_tasks)

        assert joined == [("sid-sub", namespace._room(state_token))]
        assert sent == [("sid-sub", state_token, published, {"px": 321, "mid": "m1"})]
        assert handled == [(current_figure, message, None)]
        assert not original.done()

        resume.set()
        original_result = await original
        await asyncio.sleep(0)

        assert original_result == (state_token, published, True)
        assert rebuild_calls == 1
        assert registry.is_current(state_token, published)
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_rebuild_completion_does_not_resurrect_after_a_newer_release(_fresh_registry, monkeypatch):
    """An explicit canonical absence invalidates the awaited rebuild CAS."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    registry.subscribe(state_token, "sid-existing", rebuildable=True)
    prior = registry.publish(state_token, make_figure(8), broadcast=False)
    assert registry.bump(state_token, expected=prior).version == 2
    registry.release(state_token)

    started = asyncio.Event()
    resume = asyncio.Event()
    rebuild_calls = 0
    errors = []
    broadcasts = []

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        if rebuild_calls == 1:
            started.set()
            await resume.wait()
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "_err", send_error)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)

    async def main():
        data = {"fig": state_token}
        pending = asyncio.create_task(namespace._entry_for("sid-1", data, allow_rebuild=True))
        await started.wait()

        # The canonical builder evaluated to None after this rebuild began.
        # Even though the entry was already absent, this release is a newer
        # mutation and must invalidate the active compare-and-insert guard.
        registry.release(state_token)
        resume.set()
        first = await pending
        await asyncio.sleep(0)

        assert first == (state_token, None, True)
        assert errors == [("sid-1", state_token, "unknown figure token")]
        assert registry.get(state_token) is None
        assert registry._evicted_versions == {state_token: 2}
        assert broadcasts == []
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

        retried = await namespace._entry_for("sid-2", data, allow_rebuild=True)
        await asyncio.sleep(0)

        assert rebuild_calls == 2
        assert retried[0] == state_token
        assert retried[1] is not None
        assert retried[1].version == 3
        assert retried[2]
        assert registry.is_current(state_token, retried[1])
        assert broadcasts == [(state_token, retried[1])]
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_later_request_rebuilds_while_invalidated_builder_is_still_hung(
    _fresh_registry, monkeypatch
):
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume_old = asyncio.Event()
    rebuild_calls = 0

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        if rebuild_calls == 1:
            started.set()
            await resume_old.wait()
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)

    async def get_session(_sid):
        return {"client_token": CLIENT_TOKEN}

    async def broadcast(_token, _entry):
        return None

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)

    async def main():
        data = {"fig": state_token}
        old = asyncio.create_task(namespace._entry_for("sid-old", data, allow_rebuild=True))
        await started.wait()
        registry.release(state_token)
        assert not registry._active_rebuild_guards

        newer = await asyncio.wait_for(
            namespace._entry_for("sid-new", data, allow_rebuild=True), timeout=1.0
        )
        assert rebuild_calls == 2
        assert newer[1] is not None
        assert registry.is_current(state_token, newer[1])
        assert not old.done()

        resume_old.set()
        old_result = await old
        assert old_result[1] is newer[1]
        await asyncio.sleep(0)
        assert namespace._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_sub_sends_current_replacement_when_publish_lands_before_join(_fresh_registry, monkeypatch):
    """Close the rebuild-broadcast-to-room-join handoff without a payload gap."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    rebuilt_figure = make_figure(16)
    replacement_figure = make_figure(48)
    joined = []
    sent = []
    replacement = None

    async def rebuild(token_str):
        assert token_str == state_token
        return rebuilt_figure

    namespace = XYNamespace(registry, rebuild=rebuild)
    namespace._set_server(
        SimpleNamespace(manager=SimpleNamespace(is_connected=lambda sid, _namespace: True))
    )

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def broadcast(token, entry):
        nonlocal replacement
        assert token == state_token
        assert entry.figure is rebuilt_figure
        # This normal publish's room broadcast would run before the new SID
        # joins. The direct response must therefore re-read this generation.
        replacement = registry.publish(state_token, replacement_figure, broadcast=False)

    async def enter_room(sid, room):
        joined.append((sid, room))

    async def send_payload(sid, token, entry, **kwargs):
        sent.append((sid, token, entry, kwargs))

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)
    monkeypatch.setattr(namespace, "enter_room", enter_room)
    monkeypatch.setattr(namespace, "_send_payload", send_payload)

    async def main():
        await namespace.on_sub("sid-1", {"fig": state_token, "mid": "m1", "px": 321})

        assert replacement is not None
        assert joined == [("sid-1", namespace._room(state_token))]
        assert len(sent) == 1
        sid, token, entry, kwargs = sent[0]
        assert (sid, token) == ("sid-1", state_token)
        assert entry is replacement
        assert entry.figure is replacement_figure
        assert registry.is_current(state_token, entry)
        assert kwargs == {"px": 321, "mid": "m1"}

    run(main())


def test_slow_sub_does_not_restore_membership_after_disconnect(_fresh_registry, monkeypatch):
    """A disconnect concurrent with a state rebuild wins over the stale sub."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    started = asyncio.Event()
    resume = asyncio.Event()
    connected = {"sid-gone": True}
    sent_payloads = []

    async def rebuild(token_str):
        assert token_str == state_token
        started.set()
        await resume.wait()
        return make_figure(32)

    namespace = XYNamespace(registry, rebuild=rebuild)
    namespace._set_server(
        SimpleNamespace(
            manager=SimpleNamespace(is_connected=lambda sid, _namespace: connected.get(sid, False))
        )
    )

    async def get_session(sid):
        return {"client_token": CLIENT_TOKEN}

    async def enter_room(sid, room):
        raise AssertionError("disconnected SID must not re-enter a room")

    async def send_payload(*args, **kwargs):
        sent_payloads.append((args, kwargs))

    async def broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(namespace, "get_session", get_session)
    monkeypatch.setattr(namespace, "enter_room", enter_room)
    monkeypatch.setattr(namespace, "_send_payload", send_payload)
    monkeypatch.setattr(namespace, "broadcast_payload", broadcast)

    async def main():
        pending = asyncio.create_task(
            namespace.on_sub("sid-gone", {"fig": state_token, "mid": "m1"})
        )
        await started.wait()
        connected["sid-gone"] = False
        await namespace.on_disconnect("sid-gone")
        resume.set()
        await pending

        assert sent_payloads == []
        assert registry._rebuildable_subscribers == {}
        assert registry._rebuildable_tokens_by_sid == {}
        entry = registry.get(state_token)
        assert registry.sweep(now=entry.last_access + 1_000_000.0) == [state_token]
        assert registry._evicted_versions == {}
        assert namespace._subscription_locks == {}
        assert namespace._subscription_lock_users == {}

    run(main())


def test_sub_after_ttl_rebuild_fans_existing_room_before_px_reply(_fresh_registry, monkeypatch):
    """The client whose sub rebuilds a swept figure must not receive both the
    room-wide replacement and its mount-specific response. Existing room
    members receive the unaddressed rebuild at the default resolution; the
    joining mount receives exactly one addressed payload built for its px.
    """

    from reflex_xy import namespace as namespace_module

    build_wire_payload = namespace_module._build_wire_payload

    def tagged_build_wire_payload(figure, px=None):
        spec, buffers = build_wire_payload(figure, px)
        return {**spec, "_test_px": px}, buffers

    monkeypatch.setattr(namespace_module, "_build_wire_payload", tagged_build_wire_payload)
    rebuilt = []

    async def rebuild(token_str):
        rebuilt.append(token_str)
        return make_figure(32)

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(16), broadcast=False)
        async with data_plane_server(rebuild=rebuild) as (url, _):
            existing = await connect_client(url)
            existing_collector = Collector(existing)
            await existing.emit(
                "sub",
                {"fig": state_token, "px": 640, "mid": "existing"},
                namespace="/_xy",
            )
            first = await existing_collector.next(existing_collector.payloads)
            assert first["mid"] == "existing"
            assert first["spec"]["_test_px"] == 640

            evicted = registry.get(state_token)
            assert registry.sweep(now=evicted.last_access + 1_000_000.0) == [state_token]

            joining = await connect_client(url)
            joining_collector = Collector(joining)
            await joining.emit(
                "sub",
                {"fig": state_token, "px": 123, "mid": "joining"},
                namespace="/_xy",
            )
            room_payload = await existing_collector.next(existing_collector.payloads)
            direct_payload = await joining_collector.next(joining_collector.payloads)

            assert room_payload["version"] == 2
            assert "mid" not in room_payload
            assert room_payload["spec"]["_test_px"] is None
            assert direct_payload["version"] == 2
            assert direct_payload["mid"] == "joining"
            assert direct_payload["spec"]["_test_px"] == 123
            with pytest.raises(asyncio.TimeoutError):
                await Collector.next(joining_collector.payloads, timeout=0.15)

            await existing.disconnect()
            await joining.disconnect()

        assert rebuilt == [state_token]

    run(main())


def test_interaction_after_ttl_rebuild_receives_new_payload(_fresh_registry):
    rebuilt = []

    async def rebuild(token_str):
        rebuilt.append(token_str)
        return make_figure(32)

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(16), broadcast=False)
        async with data_plane_server(rebuild=rebuild) as (url, _):
            first_client = await connect_client(url)
            second_client = await connect_client(url)
            first_collector = Collector(first_client)
            second_collector = Collector(second_client)
            await first_client.emit("sub", {"fig": state_token, "mid": "m1"}, namespace="/_xy")
            await second_client.emit("sub", {"fig": state_token, "mid": "m2"}, namespace="/_xy")
            assert (await first_collector.next(first_collector.payloads))["version"] == 1
            assert (await second_collector.next(second_collector.payloads))["version"] == 1

            registry.append(state_token, x=[2.0], y=[6.0])
            assert (await first_collector.next(first_collector.messages))["version"] == 2
            assert (await second_collector.next(second_collector.messages))["version"] == 2
            evicted = registry.get(state_token)
            assert registry.sweep(now=evicted.last_access + 1_000_000.0) == [state_token]

            message = {"type": "pick", "trace": 0, "index": 2, "seq": 31}
            await first_client.emit(
                "msg",
                {"fig": state_token, "mid": "m1", "v": 2, "m": message},
                namespace="/_xy",
            )
            first_replacement = await first_collector.next(first_collector.payloads)
            second_replacement = await second_collector.next(second_collector.payloads)
            assert first_replacement["version"] == 3
            assert second_replacement["version"] == 3
            with pytest.raises(asyncio.TimeoutError):
                await Collector.next(first_collector.messages, timeout=0.15)

            message["seq"] = 32
            await second_client.emit(
                "msg",
                {"fig": state_token, "mid": "m2", "v": 3, "m": message},
                namespace="/_xy",
            )
            reply = await second_collector.next(second_collector.messages)
            assert reply["version"] == 3
            assert reply["message"]["seq"] == 32
            await first_client.disconnect()
            await second_client.disconnect()

        assert rebuilt == [state_token]

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
            assert "mid" not in second
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
            assert push["version"] == 2
            assert push.get("mid") is None  # pushes are room-wide, not mount-addressed
            assert registry.get(token).version == 2
            assert registry.get(token).figure.traces[0].n_points == 6
            await client.disconnect()

    run(main())


def test_rows_selection_push_carries_its_figure_generation(_fresh_registry):
    import reflex_xy

    async def main():
        token = registry.register(make_figure(8))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"}, namespace="/_xy")
            payload = await collector.next(collector.payloads)

            reflex_xy.select(token, rows={0: [1, 3, 5]})
            push = await collector.next(collector.messages)
            assert push["message"]["type"] == "selection_rows"
            assert push["version"] == payload["version"] == 1
            assert push.get("mid") is None
            assert push["buffers"]
            assert registry.get(token).version == 1
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


@pytest.mark.parametrize("departure", ["unsub", "disconnect"])
def test_subscription_departure_releases_evicted_version(_fresh_registry, departure):
    """Namespace lifecycle handlers release rebuild-version tombstones once
    the last live subscriber leaves, bounding scalar metadata after eviction.
    """

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(8), broadcast=False)
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": state_token, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)
            evicted = registry.get(state_token)
            assert registry.sweep(now=evicted.last_access + 1_000_000.0) == [state_token]

            if departure == "unsub":
                await client.emit("unsub", {"fig": state_token, "mid": "m1"}, namespace="/_xy")
                await asyncio.sleep(0.05)
            else:
                await client.disconnect()
                await asyncio.sleep(0.05)

            replacement = registry.publish(state_token, make_figure(8), broadcast=False)
            if client.connected:
                await client.disconnect()
        assert replacement.version == 1

    run(main())


# -- the data-bound (plan) tier over the same wire ---------------------------
#
# Composite figure identity xyp1|<digest>|<xyd1 token>: rooms, versioning,
# mid addressing, and the attachment-cap logic are reused unchanged — the
# composite token is just another `fig` string to everything below the
# subscribe path.


class PlaneSchema(TypedDict):
    x: np.ndarray
    y: np.ndarray


class PlaneData(rx.State):
    n: int = 24

    @reflex_xy.data
    def table(self) -> PlaneSchema:
        xs = np.linspace(0.0, 1.0, self.n)
        return {"x": xs, "y": xs * 2.0}


def make_plane_app():
    return SimpleNamespace(state_manager=StateManagerMemory())


def plane_plan():
    return build_plan("scatter_chart", (xy.scatter("x", "y"),), {})


def plane_data_token(client_token: str = CLIENT_TOKEN) -> str:
    return build_data_token(client_token, PlaneData.get_full_name(), "table")


def test_composite_sub_serves_bound_payload_and_interactions(_fresh_registry):
    """sub/msg on a composite token: plan lookup + column resolve + bind,
    then the ordinary payload/pick machinery."""
    app = make_plane_app()

    async def main():
        plan = plane_plan()
        data_token = plane_data_token()
        composite = build_plan_token(plan.digest, data_token)
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": composite, "mid": "m1"}, namespace="/_xy")
            payload = await collector.next(collector.payloads)
            assert payload["fig"] == composite
            assert payload["spec"]["traces"][0]["n_points"] == 24
            # interactions round-trip against the bound figure
            await client.emit(
                "msg",
                {
                    "fig": composite,
                    "v": payload["version"],
                    "mid": "m1",
                    "m": {"type": "pick", "trace": 0, "index": 3, "seq": "pick:1"},
                },
                namespace="/_xy",
            )
            reply = await collector.next(collector.messages)
            assert reply["message"]["type"] == "pick_result"
            await client.disconnect()
        # both halves are cached now: columns and the bound figure
        assert registry.get_columns(data_token) is not None
        assert registry.get(composite) is not None

    run(main())


def test_composite_rebuild_reads_session_state(_fresh_registry):
    """The data half is rebuilt through the state bridge (mutated session
    state, not defaults) when neither half is cached."""
    app = make_plane_app()
    token_obj = rx.BaseStateToken(ident=CLIENT_TOKEN, cls=rx.State)

    async def main():
        async with app.state_manager.modify_state(token_obj) as root:
            sub = await root.get_state(PlaneData)
            sub.n = 7
        plan = plane_plan()
        composite = build_plan_token(plan.digest, plane_data_token())
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": composite, "mid": "m1"}, namespace="/_xy")
            payload = await collector.next(collector.payloads)
            assert payload["spec"]["traces"][0]["n_points"] == 7
            await client.disconnect()

    run(main())


def test_column_republish_fans_out_to_every_dependent_plan(_fresh_registry):
    """One data var, two mounted plans: a republish rebuilds and broadcasts
    both composite figures."""
    app = make_plane_app()

    async def main():
        scatter_plan = plane_plan()
        line_plan = build_plan("line_chart", (xy.line("x", "y"),), {})
        data_token = plane_data_token()
        scatter_fig = build_plan_token(scatter_plan.digest, data_token)
        line_fig = build_plan_token(line_plan.digest, data_token)
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": scatter_fig, "mid": "m1"}, namespace="/_xy")
            first = await collector.next(collector.payloads)
            await client.emit("sub", {"fig": line_fig, "mid": "m2"}, namespace="/_xy")
            second = await collector.next(collector.payloads)
            assert {first["fig"], second["fig"]} == {scatter_fig, line_fig}

            # the data var recomputes (as a state delta evaluation would)
            registry.publish_columns(
                data_token,
                {"x": np.linspace(0.0, 1.0, 5), "y": np.linspace(0.0, 1.0, 5)},
            )
            refreshed = {}
            for _ in range(2):
                payload = await collector.next(collector.payloads)
                refreshed[payload["fig"]] = payload["spec"]["traces"][0]["n_points"]
            assert refreshed == {scatter_fig: 5, line_fig: 5}
            await client.disconnect()

    run(main())


def test_composite_affinity_uses_the_embedded_data_client(_fresh_registry):
    app = make_plane_app()

    async def main():
        plan = plane_plan()
        composite = build_plan_token(plan.digest, plane_data_token(CLIENT_TOKEN))
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            thief = await connect_client(url, client_token=OTHER_TOKEN)
            thief_collector = Collector(thief)
            await thief.emit("sub", {"fig": composite, "mid": "m1"}, namespace="/_xy")
            error = await thief_collector.next(thief_collector.errors)
            assert "another session" in error["error"]
            await thief.disconnect()

    run(main())


def test_plan_miss_answers_err_resync_naming_the_digest(_fresh_registry):
    """Hot-reload drift: a subscriber holding a stale digest is asked to
    resync (the recompiled page carries the new digest)."""
    app = make_plane_app()

    async def main():
        composite = build_plan_token("feedfacefeedfacefeed", plane_data_token())
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": composite, "mid": "m1"}, namespace="/_xy")
            error = await collector.next(collector.errors)
            assert "feedfacefeedfacefeed" in error["error"]
            assert error["resync"] is True
            await client.disconnect()

    run(main())


def test_bind_mismatch_answers_err_without_resync(_fresh_registry):
    """An untyped data var producing the wrong columns: the err frame names
    both sides and does not ask for a pointless resync."""

    class MismatchData(rx.State):
        @reflex_xy.data
        def rows(self):
            return {"only": [1.0, 2.0]}

    app = make_plane_app()

    async def main():
        plan = plane_plan()
        data_token = build_data_token(CLIENT_TOKEN, MismatchData.get_full_name(), "rows")
        composite = build_plan_token(plan.digest, data_token)
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": composite, "mid": "m1"}, namespace="/_xy")
            error = await collector.next(collector.errors)
            assert "plan binds" in error["error"]
            assert "'x'" in error["error"]
            assert error.get("resync") is None
            await client.disconnect()

    run(main())


def test_republish_bind_failure_broadcasts_err_and_releases(_fresh_registry):
    """A republish whose columns stop satisfying a mounted plan must not
    freeze subscribers silently: the composite entry is released and the
    room gets an err frame asking for a bounded resync."""
    app = make_plane_app()

    async def main():
        plan = plane_plan()
        data_token = plane_data_token()
        composite = build_plan_token(plan.digest, data_token)
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": composite, "mid": "m1"}, namespace="/_xy")
            await collector.next(collector.payloads)

            registry.publish_columns(data_token, {"wrong": [1.0]})
            error = await collector.next(collector.errors)
            assert "plan binds" in error["error"]
            assert error["resync"] is True
            assert registry.get(composite) is None
            await client.disconnect()

    run(main())


def test_bare_data_token_is_not_a_figure(_fresh_registry):
    """A raw xyd1 token names columns, never a figure: closed, no rebuild."""
    app = make_plane_app()

    async def main():
        async with data_plane_server(rebuild=make_rebuild_hook(app)) as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": plane_data_token(), "mid": "m1"}, namespace="/_xy")
            error = await collector.next(collector.errors)
            assert error["error"] == "unknown figure token"
            await client.disconnect()

    run(main())
