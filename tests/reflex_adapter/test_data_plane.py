"""End-to-end data plane over a real websocket.

Boots the same server stack a Reflex backend uses — a real `rx.App()` served by
uvicorn, with the data plane registered through `app.register_channel(...)`
exactly as `setup(app)` does — and drives it with the real channel wire
protocol: JSON text frames `[event, data, channel]` outbound, and binary frames
carrying the columns as attachments inbound. This is the transport contract the
browser wrapper (XYChart.jsx) relies on, minus the browser: spec as JSON,
columns as native binary attachments beside it, replies mount-addressed, tokens
session-affine, registry misses rebuilt.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import sys
import threading
from types import SimpleNamespace
from typing import Any, Optional, TypedDict

import aiohttp
import numpy as np
import pytest
import reflex as rx
import uvicorn
from reflex.event_namespace import decode_channel_frame
from reflex.istate.manager.memory import StateManagerMemory
from reflex_base.registry import RegistrationContext

import reflex_xy
import xy
from reflex_xy.app import wire
from reflex_xy.data_plane import XY_PLANE, XYChannel
from reflex_xy.plan import build_plan
from reflex_xy.registry import registry
from reflex_xy.state_bridge import make_rebuild_hook
from reflex_xy.tokens import build_data_token, build_plan_token, build_state_token

CLIENT_TOKEN = "11111111-2222-4333-8444-555566667777"
OTHER_TOKEN = "99999999-8888-4777-8666-555544443333"

# Channel frames cap at this many attachments; the data plane's own guard is
# the same number (data_plane._MAX_WIRE_ATTACHMENTS takes it from reflex).
OVER_THE_CAP = 65


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
    """A real Reflex app serving the xy channel on its own event websocket.

    An App claims the registration context it is built in, so this one is built
    in a fork: the process context stays free for whatever app the rest of the
    suite builds.
    """
    with RegistrationContext.get().fork():
        app = rx.App()
    app._state_manager = StateManagerMemory()
    channel = XYChannel(registry, rebuild=rebuild)
    app.register_channel(channel)
    wire(channel)
    registry.attach_loop(asyncio.get_running_loop())

    port = free_port()
    config = uvicorn.Config(app._api, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}", channel
    finally:
        server.should_exit = True
        await task


class PlaneClient:
    """One connected websocket with the `/_xy` channel open.

    Mirrors what XYChart.jsx does through `getChannel("/_xy")`: the app's own
    event websocket, one `_open` for the channel, and every data plane frame
    arriving as `(metadata, attachments)`.
    """

    def __init__(self, session: aiohttp.ClientSession, ws: aiohttp.ClientWebSocketResponse):
        self._session = session
        self._ws = ws
        self.connected = True
        self.payloads: asyncio.Queue = asyncio.Queue()
        self.messages: asyncio.Queue = asyncio.Queue()
        self.errors: asyncio.Queue = asyncio.Queue()
        self._opened = asyncio.Event()
        self.reader_error: Optional[BaseException] = None
        self._queues = {
            "payload": self.payloads,
            "msg": self.messages,
            "err": self.errors,
        }
        self._reader = asyncio.create_task(self._read_forever())

    async def _read_forever(self) -> None:
        try:
            await self._read_frames()
        except (asyncio.CancelledError, ConnectionResetError):
            raise  # ordinary teardown
        except Exception as error:  # noqa: BLE001 - the wire is what's under test
            # A malformed frame is the failure this suite exists to catch, so
            # it must not surface as "everything timed out". Hand it to every
            # waiter instead of dying quietly with an unretrieved exception.
            self.reader_error = error
            for queue in self._queues.values():
                queue.put_nowait(error)

    async def _read_frames(self) -> None:
        with contextlib.suppress(asyncio.CancelledError, ConnectionResetError):
            async for frame in self._ws:
                if frame.type == aiohttp.WSMsgType.BINARY:
                    event, data, channel, buffers = decode_channel_frame(frame.data)
                elif frame.type == aiohttp.WSMsgType.TEXT:
                    decoded = json.loads(frame.data)
                    event = decoded[0]
                    data = decoded[1] if len(decoded) > 1 else None
                    channel = decoded[2] if len(decoded) > 2 else None
                    buffers = []
                else:
                    continue
                if event == "_ping":
                    await self._ws.send_str(json.dumps(["_pong"]))
                    continue
                if event == "_opened" and channel == XY_PLANE:
                    self._opened.set()
                    continue
                queue = self._queues.get(event) if channel == XY_PLANE else None
                if queue is not None:
                    queue.put_nowait((data, buffers))

    async def emit(self, event: str, data: Any) -> None:
        """Send one data plane message on the `/_xy` channel."""
        await self._ws.send_str(json.dumps([event, data, XY_PLANE]))

    async def open_plane(self) -> None:
        await self.emit("_open", None)
        await asyncio.wait_for(self._opened.wait(), 5.0)

    async def disconnect(self) -> None:
        if not self.connected:
            return
        self.connected = False
        self._reader.cancel()
        # Only the two outcomes teardown can legitimately produce: the
        # cancellation just requested, and a reset from the socket going away.
        # Anything else is a defect and should reach the test.
        with contextlib.suppress(asyncio.CancelledError, ConnectionResetError):
            await self._reader
        await self._ws.close()
        await self._session.close()
        if self.reader_error is not None:
            # The failure was handed to every waiter, but a test that finished
            # its assertions without reading again would never have popped it —
            # and a broken wire must not leave the suite green. Raised after the
            # socket is closed so a failing test still tears down cleanly.
            raise AssertionError("the data plane reader failed") from self.reader_error


async def connect_client(base_url: str, client_token: str = CLIENT_TOKEN) -> PlaneClient:
    """Connect the way XYChart.jsx does: the app socket, token in the query."""
    session = aiohttp.ClientSession()
    ws = await session.ws_connect(f"{base_url.replace('http', 'ws')}/_event?token={client_token}")
    client = PlaneClient(session, ws)
    await client.open_plane()
    return client


class Collector:
    """Buffers events from one client for ordered assertions.

    Every queue holds `(metadata, attachments)`: the two halves of a channel
    frame, kept apart the way the browser receives them.
    """

    def __init__(self, client: PlaneClient) -> None:
        self.payloads = client.payloads
        self.messages = client.messages
        self.errors = client.errors

    @staticmethod
    async def next(queue: asyncio.Queue, timeout: float = 5.0):
        frame = await asyncio.wait_for(queue.get(), timeout)
        if isinstance(frame, BaseException):
            raise AssertionError("the data plane reader failed") from frame
        return frame


class FakeSession:
    """A channel session for the tests that drive handlers directly.

    Registering one through `on_open` means the real transport seams (rooms,
    per-connection store, liveness) stay under test instead of being patched
    out; only the send paths are recorded.
    """

    def __init__(self, sid: str, client_token: str = CLIENT_TOKEN) -> None:
        self.sid = sid
        self.client_token = client_token
        self.data: dict[str, Any] = {}
        self.open = True
        self.rooms: set[str] = set()
        self.sent: list[tuple[str, Any, list]] = []

    def join(self, room: str) -> None:
        self.rooms.add(room)

    def leave(self, room: str) -> None:
        self.rooms.discard(room)

    async def send(self, event: str, data: Any, buffers: list) -> None:
        self.sent.append((event, data, list(buffers)))


async def open_fake_session(channel: XYChannel, sid: str, **kwargs) -> FakeSession:
    session = FakeSession(sid, **kwargs)
    await channel.on_open(session)  # type: ignore[arg-type]
    return session


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
    import reflex_xy.data_plane as data_plane_module

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

    channel = XYChannel(_fresh_registry)

    async def send(*_args, **_kwargs):
        return None

    monkeypatch.setattr(data_plane_module, "_build_wire_payload", blocked_payload)
    monkeypatch.setattr(channel, "_send", send)

    async def main():
        tasks = []
        payload_task = asyncio.create_task(channel._send_payload("sid", "primary", primary))
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
    import reflex_xy.data_plane as data_plane_module

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

    channel = XYChannel(_fresh_registry)
    monkeypatch.setattr(data_plane_module, "handle_message", blocked_interaction)

    async def main():
        tasks = []
        interaction_task = asyncio.create_task(
            channel.on_msg(
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


def test_a_broken_frame_fails_the_test_even_if_nothing_reads_it(_fresh_registry, monkeypatch):
    """The harness must not let a broken wire pass as a green run.

    Both halves have to hold: the reader has to *record* a decode failure
    rather than die quietly, and teardown has to raise it. A test that has
    finished its assertions never pops a queue again, so teardown is the last
    place the failure can be noticed — and a reader that silently stopped
    recording would make every other test in this file vacuous.

    The frame really is decoded here; only the decoder is replaced, because a
    real server cannot be made to emit a frame its own encoder would refuse.
    """

    def explode(frame):
        raise ValueError("frame did not decode")

    async def main():
        token = registry.register(make_figure(8))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)  # opened before the decoder breaks
            # Patched on this module object: the reader resolves the decoder
            # as a global here, and a dotted path would patch a second import
            # of this file rather than the one running.
            monkeypatch.setattr(sys.modules[__name__], "decode_channel_frame", explode)
            await client.emit("sub", {"fig": token, "mid": "m1"})

            # The error reaches the waiters rather than stranding them.
            with pytest.raises(AssertionError, match="reader failed"):
                await Collector.next(client.payloads)
            assert isinstance(client.reader_error, ValueError)

            # And teardown raises it too, for the test that never reads again.
            with pytest.raises(AssertionError, match="reader failed"):
                await client.disconnect()

    run(main())


def test_sub_delivers_spec_and_binary_columns(_fresh_registry):
    async def main():
        token = registry.register(make_figure(64))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640, "mid": "m1"})
            payload, buffers = await collector.next(collector.payloads)
            await client.disconnect()
        assert payload["fig"] == token
        assert payload["version"] == 1
        assert payload["mid"] == "m1"
        spec = payload["spec"]
        assert spec["buffer_layout"] == "split"
        assert len(spec["traces"]) == 1
        # Binary columns arrive as the frame's attachments, never inside the
        # envelope: no base64, no JSON numbers (§29 preserved on this transport).
        assert "buffers" not in payload
        assert all(isinstance(b, (bytes, bytearray)) for b in buffers)
        xcol = np.frombuffer(buffers[0], dtype=np.float32)
        assert len(xcol) == 64

    run(main())


def test_sub_over_attachment_limit_ships_single_blob(_fresh_registry):
    """A channel frame declares its attachment count, and Reflex refuses to
    encode or decode more than MAX_MESSAGE_BUFFERS of them. Buffer-heavy
    figures must fall back to the joined single-blob payload, which the
    wrapper's `toSpans` handles via `buffer_layout`."""

    async def main():
        xs = np.linspace(0.0, 1.0, 64)
        # Four buffers per trace (x, y, color, size): 17 traces clears the cap.
        figure = xy.scatter_chart(
            *[xy.scatter(xs, xs * k, color=xs, size=xs) for k in range(1, 18)],
            width=640,
            height=400,
        ).figure()
        _, raw = figure.build_payload_split(640)
        assert len(raw) >= OVER_THE_CAP, "premise: this figure must exceed the frame cap"
        token = registry.register(figure)
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640})
            payload, buffers = await collector.next(collector.payloads)
            await client.disconnect()
        assert payload["fig"] == token
        assert payload["spec"].get("buffer_layout") != "split"
        assert len(buffers) == 1

    run(main())


@pytest.mark.parametrize(
    ("message_type", "resync"),
    [("append", True), ("selection_rows", False)],
)
def test_broadcast_over_attachment_limit_answers_err_not_msg(_fresh_registry, message_type, resync):
    """Room pushes over the frame cap fail loud without an unencodable frame.

    Only append needs a payload resync: a generation-stamped view-state push
    does not itself advance the figure.
    """

    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, channel):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640})
            await collector.next(collector.payloads)
            await channel.broadcast_message(
                token, {"type": message_type}, [b"\x00" * 4] * OVER_THE_CAP, version=2
            )
            error, _ = await collector.next(collector.errors)
            await client.disconnect()
        assert error["fig"] == token
        assert "attachment" in error["error"]
        assert error["resync"] is resync
        assert collector.messages.empty()

    run(main())


def test_msg_reply_over_attachment_limit_answers_err_not_msg(_fresh_registry, monkeypatch):
    """The `on_msg` reply guard: channel replies are bounded by construction,
    so a reply over the frame's attachment cap is a contract violation — the
    client must get an `err` envelope, never a `msg` frame Reflex would refuse
    to encode (silently losing the reply)."""

    from reflex_xy import data_plane as data_plane_module

    def oversized_reply(figure, message, buffers):
        return {"kind": "pick"}, [b"\x00" * 4] * OVER_THE_CAP

    monkeypatch.setattr(data_plane_module, "handle_message", oversized_reply)

    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "px": 640})
            await collector.next(collector.payloads)
            await client.emit("msg", {"fig": token, "m": {"kind": "pick"}, "mid": "m1"})
            error, _ = await collector.next(collector.errors)
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
            await client.emit("sub", {"fig": token, "mid": "m1"})
            await collector.next(collector.payloads)

            # pick -> exact f64 row readout, mid echoed for mount routing
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "m": {"type": "pick", "trace": 0, "index": 3, "seq": 7},
                },
            )
            reply, _ = await collector.next(collector.messages)
            assert reply["mid"] == "m1"
            assert reply["message"]["type"] == "pick_result"
            assert reply["message"]["seq"] == 7
            row = reply["message"]["row"]
            assert row["x"] == pytest.approx(3 / 15)
            assert row["y"] == pytest.approx(3 / 15 * 3.0)

            # select -> selection mask as binary attachments
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "m": {"type": "select", "x0": 0.0, "x1": 0.5, "y0": 0.0, "y1": 3.0},
                },
            )
            sel, mask = await collector.next(collector.messages)
            assert sel["message"]["type"] == "selection"
            assert sel["message"]["total"] == 8
            assert len(mask) == 1

            # malformed messages are dropped silently, never crash the server
            await client.emit("msg", {"fig": token, "m": ["not", "a", "dict"]})
            await client.emit("msg", "garbage")
            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "m": {"type": "pick", "trace": 0, "index": 5, "seq": 8},
                },
            )
            after, _ = await collector.next(collector.messages)
            assert after["message"]["seq"] == 8
            await client.disconnect()

    run(main())


def test_select_round_trip_includes_semantic_rows(_fresh_registry):
    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"})
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
            )
            reply, _ = await collector.next(collector.messages)
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
            await client.emit("sub", {"fig": token, "mid": "m1"})
            await collector.next(collector.payloads)
            registry.publish(token, make_figure(16))
            payload, _ = await collector.next(collector.payloads)
            assert payload["version"] == 2

            message = {"type": "pick", "trace": 0, "index": 2, "seq": 21}
            await client.emit("msg", {"fig": token, "mid": "m1", "v": 1, "m": message})
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
                )
                with pytest.raises(asyncio.TimeoutError):
                    await Collector.next(collector.messages, timeout=0.1)

            message["seq"] = 21
            await client.emit("msg", {"fig": token, "mid": "m1", "v": 2, "m": message})
            current, _ = await collector.next(collector.messages)
            assert current["message"]["seq"] == 21

            message["seq"] = 22
            await client.emit("msg", {"fig": token, "mid": "m1", "m": message})
            compatible, _ = await collector.next(collector.messages)
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

    monkeypatch.setattr("reflex_xy.data_plane.handle_message", slow_handle_message)

    async def main():
        token = registry.register(make_figure(16))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"})
            await collector.next(collector.payloads)

            await client.emit(
                "msg",
                {
                    "fig": token,
                    "mid": "m1",
                    "v": 1,
                    "m": {"type": "pick", "trace": 0, "index": 2, "seq": 99},
                },
            )
            assert await asyncio.to_thread(started.wait, 5)
            registry.publish(token, make_figure(32))
            resume.set()

            replacement, _ = await collector.next(collector.payloads)
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
            await thief.emit("sub", {"fig": state_token, "mid": "m1"})
            err, _ = await thief_collector.next(thief_collector.errors)
            assert "another session" in err["error"]

            owner = await connect_client(url, client_token=CLIENT_TOKEN)
            owner_collector = Collector(owner)
            await owner.emit("sub", {"fig": state_token, "mid": "m1"})
            payload, _ = await owner_collector.next(owner_collector.payloads)
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
            await client.emit("sub", {"fig": state_token, "mid": "m1"})
            payload, buffers = await collector.next(collector.payloads)
            assert payload["fig"] == state_token
            assert len(buffers) == 2
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

    channel = XYChannel(registry, rebuild=rebuild)

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        await open_fake_session(channel, "sid-1")
        await open_fake_session(channel, "sid-2")
        data = {"fig": state_token}
        first = asyncio.create_task(channel._entry_for("sid-1", data, allow_rebuild=True))
        await started.wait()
        second = asyncio.create_task(channel._entry_for("sid-2", data, allow_rebuild=True))
        await asyncio.sleep(0)
        resume.set()
        results = await asyncio.gather(first, second)

        entries = [result[1] for result in results]
        assert rebuild_calls == 1
        assert entries[0] is entries[1]
        assert registry.is_current(state_token, entries[0])
        assert all(result[2] for result in results)
        assert broadcasts == [(state_token, entries[0])]
        assert channel._rebuild_attempts == {}

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

    channel = XYChannel(registry, rebuild=rebuild)

    async def broadcast(token, entry):
        assert token == state_token
        assert registry.is_current(token, entry)

    def handle(figure, message, buffers):
        handled.append((figure, message, buffers))
        return None

    monkeypatch.setattr(channel, "broadcast_payload", broadcast)
    monkeypatch.setattr("reflex_xy.data_plane.handle_message", handle)

    async def main():
        await open_fake_session(channel, "sid-1")
        await open_fake_session(channel, "sid-2")
        first = asyncio.create_task(
            channel.on_msg(
                "sid-1",
                {"fig": state_token, "m": {"type": "pick", "trace": 0, "index": 1}},
            )
        )
        await started.wait()
        # Version 1 also matches a fresh worker's rebuilt version. The request
        # must still drop because it was sent before that worker's payload.
        second = asyncio.create_task(
            channel.on_msg(
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
        assert channel._rebuild_attempts == {}

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

    channel = XYChannel(registry, rebuild=rebuild)

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(channel, "_err", send_error)
    monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        for sid in ("sid-1", "sid-2", "sid-3"):
            await open_fake_session(channel, sid)
        data = {"fig": state_token}
        first = asyncio.create_task(channel._entry_for("sid-1", data, allow_rebuild=True))
        await started.wait()
        second = asyncio.create_task(channel._entry_for("sid-2", data, allow_rebuild=True))
        await asyncio.sleep(0)
        resume.set()
        first_results = await asyncio.gather(first, second)
        await asyncio.sleep(0)

        assert rebuild_calls == 1
        assert all(result == (state_token, None, True) for result in first_results)
        assert sorted(sid for sid, _, _ in errors) == ["sid-1", "sid-2"]
        assert all(token == state_token for _, token, _ in errors)
        assert all(error == "unknown figure token" for _, _, error in errors)
        assert channel._rebuild_attempts == {}

        retried = await channel._entry_for("sid-3", data, allow_rebuild=True)
        await asyncio.sleep(0)
        assert rebuild_calls == 2
        assert retried[0] == state_token
        assert retried[1] is not None
        assert retried[2]
        assert registry.is_current(state_token, retried[1])
        assert broadcasts == [(state_token, retried[1])]
        assert channel._rebuild_attempts == {}

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
    sent = []
    rebuild_calls = 0

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        return make_figure(32)

    channel = XYChannel(registry, rebuild=rebuild)

    async def broadcast(token, entry):
        assert token == state_token
        assert registry.is_current(token, entry)
        broadcasts.append(entry)
        if len(broadcasts) == 1:
            raise RuntimeError("transport failed")

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    async def send_payload(sid, token, entry, **kwargs):
        sent.append((sid, token, entry, kwargs))

    monkeypatch.setattr(channel, "broadcast_payload", broadcast)
    monkeypatch.setattr(channel, "_err", send_error)
    monkeypatch.setattr(channel, "_send_payload", send_payload)

    async def main():
        first = await open_fake_session(channel, "sid-1")
        second = await open_fake_session(channel, "sid-2")
        await channel.on_sub("sid-1", {"fig": state_token, "mid": "m1"})
        await asyncio.sleep(0)

        assert errors == [("sid-1", state_token, "rebuild failed")]
        assert registry.get(state_token) is None
        assert registry._evicted_versions == {state_token: 3}
        assert first.rooms == set()
        assert sent == []
        assert channel._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

        await channel.on_sub("sid-2", {"fig": state_token, "mid": "m2", "px": 321})
        await asyncio.sleep(0)

        assert rebuild_calls == 2
        assert [entry.version for entry in broadcasts] == [3, 4]
        assert second.rooms == {channel._room(state_token)}
        assert len(sent) == 1
        sid, token, entry, kwargs = sent[0]
        assert (sid, token, entry.version, kwargs) == (
            "sid-2",
            state_token,
            4,
            {"px": 321, "mid": "m2"},
        )
        assert registry.is_current(state_token, entry)
        assert channel._rebuild_attempts == {}
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

    channel = XYChannel(registry, rebuild=rebuild)

    async def fail_after_replacement(token, entry):
        nonlocal replacement
        assert token == state_token
        assert registry.is_current(token, entry)
        replacement = registry.publish(token, replacement_figure, broadcast=False)
        raise RuntimeError("old generation transport failed")

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    monkeypatch.setattr(channel, "broadcast_payload", fail_after_replacement)
    monkeypatch.setattr(channel, "_err", send_error)

    async def main():
        await open_fake_session(channel, "sid-1")
        token, entry, initially_missing = await channel._entry_for(
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
        assert channel._rebuild_attempts == {}
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

    channel = XYChannel(registry, rebuild=rebuild)

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

    monkeypatch.setattr(channel, "broadcast_payload", fail_then_deliver_from_publish)
    monkeypatch.setattr(channel, "_err", send_error)

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        registry.on_publish(channel.broadcast_payload)
        await open_fake_session(channel, "sid-1")
        token, entry, initially_missing = await channel._entry_for(
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
        assert channel._rebuild_attempts == {}
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

    channel = XYChannel(registry, rebuild=rebuild)

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        await open_fake_session(channel, "sid-1")
        pending = asyncio.create_task(
            channel._entry_for("sid-1", {"fig": state_token}, allow_rebuild=True)
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
        assert channel._rebuild_attempts == {}

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
    sent = []
    handled = []

    async def rebuild(token_str):
        nonlocal rebuild_calls
        assert token_str == state_token
        rebuild_calls += 1
        started.set()
        await resume.wait()
        return make_figure(16)

    channel = XYChannel(registry, rebuild=rebuild)

    async def send_payload(sid, token, entry, **kwargs):
        sent.append((sid, token, entry, kwargs))

    async def unexpected_broadcast(token, entry):
        raise AssertionError("the stale rebuild must not own authoritative fan-out")

    def handle(figure, message, buffers):
        handled.append((figure, message, buffers))
        return None

    monkeypatch.setattr(channel, "_send_payload", send_payload)
    monkeypatch.setattr(channel, "broadcast_payload", unexpected_broadcast)
    monkeypatch.setattr("reflex_xy.data_plane.handle_message", handle)

    async def main():
        await open_fake_session(channel, "sid-original")
        subscriber = await open_fake_session(channel, "sid-sub")
        await open_fake_session(channel, "sid-msg")
        original = asyncio.create_task(
            channel._entry_for("sid-original", {"fig": state_token}, allow_rebuild=True)
        )
        await started.wait()
        assert registry._active_rebuild_guards

        published = registry.publish(state_token, current_figure, broadcast=False)
        assert registry._active_rebuild_guards == {}
        assert not original.done()

        message = {"type": "pick", "trace": 0, "index": 1}
        later_sub = asyncio.create_task(
            channel.on_sub("sid-sub", {"fig": state_token, "mid": "m1", "px": 321})
        )
        later_msg = asyncio.create_task(
            channel.on_msg(
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

        assert subscriber.rooms == {channel._room(state_token)}
        assert sent == [("sid-sub", state_token, published, {"px": 321, "mid": "m1"})]
        assert handled == [(current_figure, message, None)]
        assert not original.done()

        resume.set()
        original_result = await original
        await asyncio.sleep(0)

        assert original_result == (state_token, published, True)
        assert rebuild_calls == 1
        assert registry.is_current(state_token, published)
        assert channel._rebuild_attempts == {}
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

    channel = XYChannel(registry, rebuild=rebuild)

    async def send_error(sid, token, error, resync=False):
        errors.append((sid, token, error))

    async def broadcast(token, entry):
        broadcasts.append((token, entry))

    monkeypatch.setattr(channel, "_err", send_error)
    monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        await open_fake_session(channel, "sid-1")
        await open_fake_session(channel, "sid-2")
        data = {"fig": state_token}
        pending = asyncio.create_task(channel._entry_for("sid-1", data, allow_rebuild=True))
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
        assert channel._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

        retried = await channel._entry_for("sid-2", data, allow_rebuild=True)
        await asyncio.sleep(0)

        assert rebuild_calls == 2
        assert retried[0] == state_token
        assert retried[1] is not None
        assert retried[1].version == 3
        assert retried[2]
        assert registry.is_current(state_token, retried[1])
        assert broadcasts == [(state_token, retried[1])]
        assert channel._rebuild_attempts == {}
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

    channel = XYChannel(registry, rebuild=rebuild)

    async def broadcast(_token, _entry):
        return None

    monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        await open_fake_session(channel, "sid-old")
        await open_fake_session(channel, "sid-new")
        data = {"fig": state_token}
        old = asyncio.create_task(channel._entry_for("sid-old", data, allow_rebuild=True))
        await started.wait()
        registry.release(state_token)
        assert not registry._active_rebuild_guards

        newer = await asyncio.wait_for(
            channel._entry_for("sid-new", data, allow_rebuild=True), timeout=1.0
        )
        assert rebuild_calls == 2
        assert newer[1] is not None
        assert registry.is_current(state_token, newer[1])
        assert not old.done()

        resume_old.set()
        old_result = await old
        assert old_result[1] is newer[1]
        await asyncio.sleep(0)
        assert channel._rebuild_attempts == {}
        assert registry._active_rebuild_guards == {}

    run(main())


def test_sub_sends_current_replacement_when_publish_lands_before_join(_fresh_registry, monkeypatch):
    """Close the rebuild-broadcast-to-room-join handoff without a payload gap."""
    registry = _fresh_registry
    state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
    rebuilt_figure = make_figure(16)
    replacement_figure = make_figure(48)
    sent = []
    replacement = None

    async def rebuild(token_str):
        assert token_str == state_token
        return rebuilt_figure

    channel = XYChannel(registry, rebuild=rebuild)

    async def broadcast(token, entry):
        nonlocal replacement
        assert token == state_token
        assert entry.figure is rebuilt_figure
        # This normal publish's room broadcast would run before the new SID
        # joins. The direct response must therefore re-read this generation.
        replacement = registry.publish(state_token, replacement_figure, broadcast=False)

    async def send_payload(sid, token, entry, **kwargs):
        sent.append((sid, token, entry, kwargs))

    monkeypatch.setattr(channel, "broadcast_payload", broadcast)
    monkeypatch.setattr(channel, "_send_payload", send_payload)

    async def main():
        session = await open_fake_session(channel, "sid-1")
        await channel.on_sub("sid-1", {"fig": state_token, "mid": "m1", "px": 321})

        assert replacement is not None
        assert session.rooms == {channel._room(state_token)}
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
    sent_payloads = []

    async def rebuild(token_str):
        assert token_str == state_token
        started.set()
        await resume.wait()
        return make_figure(32)

    channel = XYChannel(registry, rebuild=rebuild)

    async def send_payload(*args, **kwargs):
        sent_payloads.append((args, kwargs))

    async def broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(channel, "_send_payload", send_payload)
    monkeypatch.setattr(channel, "broadcast_payload", broadcast)

    async def main():
        session = await open_fake_session(channel, "sid-gone")
        pending = asyncio.create_task(channel.on_sub("sid-gone", {"fig": state_token, "mid": "m1"}))
        await started.wait()
        session.open = False
        await channel.on_close(session)  # type: ignore[arg-type]
        resume.set()
        await pending

        assert session.rooms == set(), "a disconnected SID must not re-enter a room"
        assert sent_payloads == []
        assert registry._rebuildable_subscribers == {}
        assert registry._rebuildable_tokens_by_sid == {}
        entry = registry.get(state_token)
        assert registry.sweep(now=entry.last_access + 1_000_000.0) == [state_token]
        assert registry._evicted_versions == {}
        assert channel._subscription_locks == {}
        assert channel._subscription_lock_users == {}

    run(main())


def test_sub_after_ttl_rebuild_fans_existing_room_before_px_reply(_fresh_registry, monkeypatch):
    """The client whose sub rebuilds a swept figure must not receive both the
    room-wide replacement and its mount-specific response. Existing room
    members receive the unaddressed rebuild at the default resolution; the
    joining mount receives exactly one addressed payload built for its px.
    """

    from reflex_xy import data_plane as data_plane_module

    build_wire_payload = data_plane_module._build_wire_payload

    def tagged_build_wire_payload(figure, px=None):
        spec, buffers = build_wire_payload(figure, px)
        return {**spec, "_test_px": px}, buffers

    monkeypatch.setattr(data_plane_module, "_build_wire_payload", tagged_build_wire_payload)
    rebuilt = []

    async def rebuild(token_str):
        rebuilt.append(token_str)
        return make_figure(32)

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(16), broadcast=False)
        async with data_plane_server(rebuild=rebuild) as (url, _):
            # Two mounts of one figure on one page: they share the tab's
            # websocket, so `mid` is the only thing separating their traffic.
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": state_token, "px": 640, "mid": "existing"})
            first, _ = await collector.next(collector.payloads)
            assert first["mid"] == "existing"
            assert first["spec"]["_test_px"] == 640

            evicted = registry.get(state_token)
            assert registry.sweep(now=evicted.last_access + 1_000_000.0) == [state_token]

            await client.emit("sub", {"fig": state_token, "px": 123, "mid": "joining"})
            room_payload, _ = await collector.next(collector.payloads)
            direct_payload, _ = await collector.next(collector.payloads)

            assert room_payload["version"] == 2
            assert "mid" not in room_payload
            assert room_payload["spec"]["_test_px"] is None
            assert direct_payload["version"] == 2
            assert direct_payload["mid"] == "joining"
            assert direct_payload["spec"]["_test_px"] == 123
            with pytest.raises(asyncio.TimeoutError):
                await Collector.next(collector.payloads, timeout=0.15)

            await client.disconnect()

        assert rebuilt == [state_token]

    run(main())


def test_a_second_tab_gets_its_own_client_token_and_no_affinity(_fresh_registry):
    """Affinity is per tab, resolved by Reflex — not by the query string.

    Reflex mints a fresh client token when a connection presents one that is
    already live, so a figure minted for the first tab is another session's as
    far as the second tab is concerned. The data plane reads the resolved
    token off the channel session and inherits that for free.
    """

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(8), broadcast=False)
        async with data_plane_server() as (url, _):
            first = await connect_client(url)
            second = await connect_client(url)  # same ?token=, new tab
            first_collector = Collector(first)
            second_collector = Collector(second)

            await first.emit("sub", {"fig": state_token, "mid": "m1"})
            payload, _ = await first_collector.next(first_collector.payloads)
            assert payload["fig"] == state_token

            await second.emit("sub", {"fig": state_token, "mid": "m1"})
            error, _ = await second_collector.next(second_collector.errors)
            assert "another session" in error["error"]

            await first.disconnect()
            await second.disconnect()

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
            # Two mounts on the page's one websocket, distinguished by `mid`.
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": state_token, "mid": "m1"})
            await client.emit("sub", {"fig": state_token, "mid": "m2"})
            first, _ = await collector.next(collector.payloads)
            second, _ = await collector.next(collector.payloads)
            assert (first["version"], second["version"]) == (1, 1)
            assert {first["mid"], second["mid"]} == {"m1", "m2"}

            registry.append(state_token, x=[2.0], y=[6.0])
            push, _ = await collector.next(collector.messages)
            assert push["version"] == 2
            evicted = registry.get(state_token)
            assert registry.sweep(now=evicted.last_access + 1_000_000.0) == [state_token]

            message = {"type": "pick", "trace": 0, "index": 2, "seq": 31}
            await client.emit("msg", {"fig": state_token, "mid": "m1", "v": 2, "m": message})
            replacement, _ = await collector.next(collector.payloads)
            assert replacement["version"] == 3
            # The request predates this worker's authoritative payload, so the
            # rebuild re-primes the room instead of answering old coordinates.
            with pytest.raises(asyncio.TimeoutError):
                await Collector.next(collector.messages, timeout=0.15)

            message["seq"] = 32
            await client.emit("msg", {"fig": state_token, "mid": "m2", "v": 3, "m": message})
            reply, _ = await collector.next(collector.messages)
            assert reply["version"] == 3
            assert reply["message"]["seq"] == 32
            await client.disconnect()

        assert rebuilt == [state_token]

    run(main())


def test_unknown_opaque_token_errors(_fresh_registry):
    async def main():
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": "xyfig-doesnotexist", "mid": "m1"})
            err, _ = await collector.next(collector.errors)
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
            await client.emit("sub", {"fig": token, "mid": "m1"})
            first, _ = await collector.next(collector.payloads)
            assert first["version"] == 1

            registry.publish(token, make_figure(48))  # e.g. a dep-driven recompute
            second, buffers = await collector.next(collector.payloads)
            assert second["version"] == 2
            assert "mid" not in second
            xcol = np.frombuffer(buffers[0], dtype=np.float32)
            assert len(xcol) == 48
            await client.disconnect()

    run(main())


def test_append_streams_to_subscribers(_fresh_registry):
    async def main():
        token = registry.register(make_figure(4))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"})
            await collector.next(collector.payloads)

            reflex_xy.append(token, x=[2.0, 3.0], y=[6.0, 9.0])
            push, _ = await collector.next(collector.messages)
            assert push["message"]["type"] == "append"
            assert push["version"] == 2
            assert push.get("mid") is None  # pushes are room-wide, not mount-addressed
            assert registry.get(token).version == 2
            assert registry.get(token).figure.traces[0].n_points == 6
            await client.disconnect()

    run(main())


def test_rows_selection_push_carries_its_figure_generation(_fresh_registry):
    async def main():
        token = registry.register(make_figure(8))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"})
            payload, _ = await collector.next(collector.payloads)

            reflex_xy.select(token, rows={0: [1, 3, 5]})
            push, buffers = await collector.next(collector.messages)
            assert push["message"]["type"] == "selection_rows"
            assert push["version"] == payload["version"] == 1
            assert push.get("mid") is None
            assert buffers
            assert registry.get(token).version == 1
            await client.disconnect()

    run(main())


def test_unsub_stops_broadcasts(_fresh_registry):
    async def main():
        token = registry.register(make_figure(8))
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": token, "mid": "m1"})
            await collector.next(collector.payloads)
            await client.emit("unsub", {"fig": token, "mid": "m1"})
            await asyncio.sleep(0.05)
            registry.publish(token, make_figure(12))
            await asyncio.sleep(0.2)
            assert collector.payloads.empty()
            await client.disconnect()

    run(main())


@pytest.mark.parametrize("departure", ["unsub", "disconnect"])
def test_subscription_departure_releases_evicted_version(_fresh_registry, departure):
    """Data plane lifecycle handlers release rebuild-version tombstones once
    the last live subscriber leaves, bounding scalar metadata after eviction.
    """

    async def main():
        state_token = build_state_token(CLIENT_TOKEN, "root.some_state", "chart")
        registry.publish(state_token, make_figure(8), broadcast=False)
        async with data_plane_server() as (url, _):
            client = await connect_client(url)
            collector = Collector(client)
            await client.emit("sub", {"fig": state_token, "mid": "m1"})
            await collector.next(collector.payloads)
            evicted = registry.get(state_token)
            assert registry.sweep(now=evicted.last_access + 1_000_000.0) == [state_token]

            if departure == "unsub":
                await client.emit("unsub", {"fig": state_token, "mid": "m1"})
                await asyncio.sleep(0.05)
            else:
                await client.disconnect()
                await asyncio.sleep(0.05)

            replacement = registry.publish(state_token, make_figure(8), broadcast=False)
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
            await client.emit("sub", {"fig": composite, "mid": "m1"})
            payload, _ = await collector.next(collector.payloads)
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
            )
            reply, _ = await collector.next(collector.messages)
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
            await client.emit("sub", {"fig": composite, "mid": "m1"})
            payload, _ = await collector.next(collector.payloads)
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
            await client.emit("sub", {"fig": scatter_fig, "mid": "m1"})
            first, _ = await collector.next(collector.payloads)
            await client.emit("sub", {"fig": line_fig, "mid": "m2"})
            second, _ = await collector.next(collector.payloads)
            assert {first["fig"], second["fig"]} == {scatter_fig, line_fig}

            # the data var recomputes (as a state delta evaluation would)
            registry.publish_columns(
                data_token,
                {"x": np.linspace(0.0, 1.0, 5), "y": np.linspace(0.0, 1.0, 5)},
            )
            refreshed = {}
            for _ in range(2):
                payload, _ = await collector.next(collector.payloads)
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
            await thief.emit("sub", {"fig": composite, "mid": "m1"})
            error, _ = await thief_collector.next(thief_collector.errors)
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
            await client.emit("sub", {"fig": composite, "mid": "m1"})
            error, _ = await collector.next(collector.errors)
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
            await client.emit("sub", {"fig": composite, "mid": "m1"})
            error, _ = await collector.next(collector.errors)
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
            await client.emit("sub", {"fig": composite, "mid": "m1"})
            await collector.next(collector.payloads)

            registry.publish_columns(data_token, {"wrong": [1.0]})
            error, _ = await collector.next(collector.errors)
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
            await client.emit("sub", {"fig": plane_data_token(), "mid": "m1"})
            error, _ = await collector.next(collector.errors)
            assert error["error"] == "unknown figure token"
            await client.disconnect()

    run(main())
