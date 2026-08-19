from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from xy import _chromium


class _FakeProcess:
    def __init__(self, *, returncode: int | None = None, stall_on_wait: bool = False) -> None:
        self.returncode = returncode
        self.stall_on_wait = stall_on_wait
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.stall_on_wait and self.kill_calls == 0:
            raise subprocess.TimeoutExpired("chromium", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _track_tempdirs(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    real_temporary_directory = _chromium.tempfile.TemporaryDirectory
    paths: list[Path] = []

    def temporary_directory(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        directory = real_temporary_directory(*args, **kwargs)
        paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(_chromium.tempfile, "TemporaryDirectory", temporary_directory)
    return paths


def test_chromium_session_cleans_every_resource_when_websocket_handshake_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_paths = _track_tempdirs(monkeypatch)
    process = _FakeProcess(stall_on_wait=True)
    stderr_files = []

    def popen(_args, *, stdout, stderr):  # noqa: ANN001, ANN202
        del stdout
        stderr.write(b"DevTools listening on ws://127.0.0.1:9222/devtools/browser/test\n")
        stderr.flush()
        stderr_files.append(stderr)
        return process

    def fail_websocket(_url: str, *, timeout_s: float):  # noqa: ANN202
        assert timeout_s > 0
        raise _chromium.ChromiumError("websocket handshake failed")

    monkeypatch.setattr(_chromium.subprocess, "Popen", popen)
    monkeypatch.setattr(_chromium, "_WebSocket", fail_websocket)

    with pytest.raises(_chromium.ChromiumError, match="handshake failed"):
        _chromium.ChromiumSession("/fake/chromium")

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == [10, 10]
    assert stderr_files[0].closed
    assert len(temp_paths) == 1
    assert not temp_paths[0].exists()


def test_chromium_session_cleans_files_when_browser_exits_during_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_paths = _track_tempdirs(monkeypatch)
    process = _FakeProcess(returncode=23)
    stderr_files = []

    def popen(_args, *, stdout, stderr):  # noqa: ANN001, ANN202
        del stdout
        stderr.write(b"fatal startup failure\n")
        stderr.flush()
        stderr_files.append(stderr)
        return process

    monkeypatch.setattr(_chromium.subprocess, "Popen", popen)

    with pytest.raises(_chromium.ChromiumError, match="fatal startup failure"):
        _chromium.ChromiumSession("/fake/chromium")

    assert process.terminate_calls == 0
    assert process.kill_calls == 0
    assert process.wait_calls == [10]
    assert stderr_files[0].closed
    assert len(temp_paths) == 1
    assert not temp_paths[0].exists()


def test_chromium_session_cleans_running_browser_when_devtools_endpoint_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_paths = _track_tempdirs(monkeypatch)
    process = _FakeProcess()
    stderr_files = []
    now = 0.0

    def popen(_args, *, stdout, stderr):  # noqa: ANN001, ANN202
        del stdout
        stderr_files.append(stderr)
        return process

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(_chromium.subprocess, "Popen", popen)
    monkeypatch.setattr(_chromium.time, "monotonic", monotonic)
    monkeypatch.setattr(_chromium.time, "sleep", sleep)

    with pytest.raises(_chromium.ChromiumError, match="did not report a DevTools endpoint"):
        _chromium.ChromiumSession("/fake/chromium", launch_timeout_s=0.1)

    assert now == pytest.approx(0.1)
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert process.wait_calls == [0.0]
    assert stderr_files[0].closed
    assert len(temp_paths) == 1
    assert not temp_paths[0].exists()


def test_websocket_closes_socket_when_handshake_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.closed = False

        def settimeout(self, _timeout_s: float) -> None:
            pass

        def sendall(self, _data: bytes) -> None:
            pass

        def recv(self, _size: int) -> bytes:
            return b""

        def close(self) -> None:
            self.closed = True

    sock = FakeSocket()
    monkeypatch.setattr(_chromium.socket, "create_connection", lambda *_args, **_kwargs: sock)

    with pytest.raises(_chromium.ChromiumError, match="connection closed"):
        _chromium._WebSocket("ws://127.0.0.1:9222/devtools/browser/test")

    assert sock.closed


def test_failed_init_cleanup_uses_only_bounded_reap_grace_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_paths = _track_tempdirs(monkeypatch)
    now = 0.0
    stderr_files = []

    class DeadlineProcess(_FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            nonlocal now
            self.wait_calls.append(timeout)
            assert timeout is not None
            now += timeout
            if self.kill_calls == 0:
                raise subprocess.TimeoutExpired("chromium", timeout)
            self.returncode = -9
            return self.returncode

    process = DeadlineProcess()

    def popen(_args, *, stdout, stderr):  # noqa: ANN001, ANN202
        del stdout
        stderr.write(b"DevTools listening on ws://127.0.0.1:9222/devtools/browser/test\n")
        stderr.flush()
        stderr_files.append(stderr)
        return process

    def fail_websocket(_url: str, *, timeout_s: float):  # noqa: ANN202
        nonlocal now
        assert timeout_s == pytest.approx(5.0)
        now = 4.0
        raise _chromium.ChromiumError("websocket handshake failed")

    monkeypatch.setattr(_chromium.subprocess, "Popen", popen)
    monkeypatch.setattr(_chromium, "_WebSocket", fail_websocket)
    monkeypatch.setattr(_chromium.time, "monotonic", lambda: now)

    with pytest.raises(_chromium.ChromiumError, match="handshake failed"):
        _chromium.ChromiumSession("/fake/chromium", launch_timeout_s=5.0)

    assert now == pytest.approx(6.0)
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == [pytest.approx(1.0), pytest.approx(1.0)]
    assert stderr_files[0].closed
    assert len(temp_paths) == 1
    assert not temp_paths[0].exists()


def test_websocket_receive_deadline_bounds_incremental_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0

    class DribblingSocket:
        def __init__(self) -> None:
            self.timeout = 0.0
            self.timeouts: list[float] = []
            self.chunks = iter((b"\x81", b"\x02", b"O", b"K"))

        def settimeout(self, timeout_s: float) -> None:
            self.timeout = timeout_s
            self.timeouts.append(timeout_s)

        def recv(self, _size: int) -> bytes:
            nonlocal now
            chunk_delay = 0.49
            if self.timeout < chunk_delay:
                now += self.timeout
                raise TimeoutError("socket timed out")
            now += chunk_delay
            return next(self.chunks)

        def sendall(self, _data: bytes) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    sock = DribblingSocket()
    sock.closed = False
    websocket = object.__new__(_chromium._WebSocket)
    websocket._sock = sock
    websocket._buffer = b""
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._next_id = 0
    session._events = {}
    monkeypatch.setattr(_chromium.time, "monotonic", lambda: now)

    with pytest.raises(TimeoutError, match="timed out"):
        session._call("Runtime.evaluate", timeout_s=1.0)

    assert now == pytest.approx(1.0)
    assert sock.timeouts == pytest.approx([1.0, 1.0, 1.0, 0.51, 0.02])
    assert sock.closed
    assert session._ws is None
    with pytest.raises(_chromium.ChromiumError, match="no longer usable"):
        session._call("Runtime.evaluate", timeout_s=1.0)


def test_page_session_shares_one_timeout_across_setup_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = 0.0
    timeouts: list[tuple[str, float]] = []
    session = object.__new__(_chromium.ChromiumSession)
    session._tmp = SimpleNamespace(name=str(tmp_path))

    def monotonic() -> float:
        return now

    def call(
        method: str,
        _params=None,  # noqa: ANN001
        *,
        session_id: str | None = None,
        timeout_s: float,
    ) -> dict[str, str]:
        nonlocal now
        del session_id
        timeouts.append((method, timeout_s))
        now += 1.0
        if method == "Target.createTarget":
            return {"targetId": "target123"}
        if method == "Target.attachToTarget":
            return {"sessionId": "session123"}
        return {}

    monkeypatch.setattr(_chromium.time, "monotonic", monotonic)
    session._call = call

    target_id, session_id, page_path = session._page_session("<p>probe</p>", 5.0)

    assert (target_id, session_id) == ("target123", "session123")
    assert page_path.read_text(encoding="utf-8") == "<p>probe</p>"
    assert timeouts == [
        ("Target.createTarget", pytest.approx(5.0)),
        ("Target.attachToTarget", pytest.approx(4.0)),
        ("Page.enable", pytest.approx(3.0)),
    ]


def test_cdp_call_deadline_includes_sending_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0

    class FakeWebSocket:
        def __init__(self) -> None:
            self.timeouts: list[float] = []
            self.recv_deadlines: list[float] = []

        def settimeout(self, timeout_s: float) -> None:
            self.timeouts.append(timeout_s)

        def send_text(self, _message: str) -> None:
            nonlocal now
            now += 4.0

        def recv_text(self, *, deadline: float) -> str:
            self.recv_deadlines.append(deadline)
            return json.dumps({"id": 1, "result": {"status": "ok"}})

    websocket = FakeWebSocket()
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._next_id = 0
    session._events = {}
    monkeypatch.setattr(_chromium.time, "monotonic", lambda: now)

    assert session._call("Page.navigate", timeout_s=5.0) == {"status": "ok"}
    assert websocket.timeouts == [pytest.approx(5.0), pytest.approx(1.0)]
    assert websocket.recv_deadlines == [pytest.approx(5.0)]


def test_cdp_call_closes_and_invalidates_websocket_when_send_fails() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed = False
            self.send_calls = 0

        def settimeout(self, _timeout_s: float) -> None:
            pass

        def send_text(self, _message: str) -> None:
            self.send_calls += 1
            raise TimeoutError("partial frame")

        def abort(self) -> None:
            self.closed = True

    websocket = FakeWebSocket()
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._next_id = 0
    session._events = {}

    with pytest.raises(TimeoutError, match="partial frame"):
        session._call("Page.navigate", timeout_s=5.0)

    assert websocket.closed
    assert session._ws is None
    with pytest.raises(_chromium.ChromiumError, match="no longer usable"):
        session._call("Page.navigate", timeout_s=5.0)
    assert websocket.send_calls == 1


@pytest.mark.parametrize(
    "received, expected_exception",
    [
        pytest.param(
            _chromium.ChromiumError("websocket closed by browser"),
            _chromium.ChromiumError,
            id="closed-stream",
        ),
        pytest.param("{invalid json", json.JSONDecodeError, id="invalid-json"),
    ],
)
def test_cdp_call_invalidates_websocket_on_receive_or_decode_failure(
    received: BaseException | str,
    expected_exception: type[BaseException],
) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.aborted = False
            self.send_calls = 0

        def settimeout(self, _timeout_s: float) -> None:
            pass

        def send_text(self, _message: str) -> None:
            self.send_calls += 1

        def recv_text(self, *, deadline: float) -> str:
            assert deadline > 0
            if isinstance(received, BaseException):
                raise received
            return received

        def abort(self) -> None:
            self.aborted = True

    websocket = FakeWebSocket()
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._next_id = 0
    session._events = {}

    with pytest.raises(expected_exception):
        session._call("Page.navigate", timeout_s=5.0)

    assert websocket.aborted
    assert session._ws is None
    with pytest.raises(_chromium.ChromiumError, match="no longer usable"):
        session._call("Page.navigate", timeout_s=5.0)
    assert websocket.send_calls == 1


@pytest.mark.parametrize(
    "received, expected_exception",
    [
        pytest.param(
            _chromium.ChromiumError("websocket closed mid-frame"),
            _chromium.ChromiumError,
            id="closed-stream",
        ),
        pytest.param("{invalid json", json.JSONDecodeError, id="invalid-json"),
    ],
)
def test_cdp_event_wait_invalidates_websocket_on_receive_or_decode_failure(
    received: BaseException | str,
    expected_exception: type[BaseException],
) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.aborted = False
            self.recv_calls = 0

        def settimeout(self, _timeout_s: float) -> None:
            pass

        def recv_text(self, *, deadline: float) -> str:
            assert deadline > 0
            self.recv_calls += 1
            if isinstance(received, BaseException):
                raise received
            return received

        def abort(self) -> None:
            self.aborted = True

    websocket = FakeWebSocket()
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._events = {}

    with pytest.raises(expected_exception):
        session._wait_event("Page.loadEventFired", session_id="page", timeout_s=5.0)

    assert websocket.aborted
    assert session._ws is None
    with pytest.raises(_chromium.ChromiumError, match="no longer usable"):
        session._wait_event("Page.loadEventFired", session_id="page", timeout_s=5.0)
    assert websocket.recv_calls == 1


def test_page_session_aborts_browser_when_target_creation_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    process = _FakeProcess(stall_on_wait=True)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.aborted = False

        def abort(self) -> None:
            self.aborted = True

    websocket = FakeWebSocket()
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._proc = process
    session._next_id = 0
    session._events = {}

    def call(
        method: str,
        _params=None,  # noqa: ANN001
        *,
        session_id: str | None = None,
        timeout_s: float,
    ) -> dict[str, str]:
        nonlocal now
        del session_id
        assert method == "Target.createTarget"
        assert timeout_s == pytest.approx(5.0)
        now = 5.0
        raise _chromium.ChromiumError("timeout waiting for Target.createTarget")

    monkeypatch.setattr(_chromium.time, "monotonic", lambda: now)
    session._call = call

    with pytest.raises(_chromium.ChromiumError, match=r"Target\.createTarget"):
        session._page_session("<p>probe</p>", 5.0)

    assert websocket.aborted
    assert session._ws is None
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == [0.0, pytest.approx(1.0)]
    with pytest.raises(_chromium.ChromiumError, match="no longer usable"):
        _chromium.ChromiumSession._call(session, "Page.navigate", timeout_s=1.0)


@pytest.mark.parametrize("failure_stage", ["attach", "write", "enable"])
def test_page_session_cleans_target_and_file_after_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    now = 0.0
    calls: list[tuple[str, float]] = []
    page_path = tmp_path / "chart-target12.html"
    session = object.__new__(_chromium.ChromiumSession)
    session._tmp = SimpleNamespace(name=str(tmp_path))

    def call(
        method: str,
        _params=None,  # noqa: ANN001
        *,
        session_id: str | None = None,
        timeout_s: float,
    ) -> dict[str, str]:
        nonlocal now
        del session_id
        calls.append((method, timeout_s))
        now += 1.0
        if method == "Target.createTarget":
            return {"targetId": "target123"}
        if method == "Target.attachToTarget":
            if failure_stage == "attach":
                raise _chromium.ChromiumError("attach failed")
            return {"sessionId": "session123"}
        if method == "Page.enable" and failure_stage == "enable":
            raise _chromium.ChromiumError("enable failed")
        return {}

    real_write_text = Path.write_text

    def write_text(path: Path, data: str, *, encoding: str) -> int:
        if failure_stage == "write":
            real_write_text(path, "partial", encoding=encoding)
            raise OSError("write failed")
        return real_write_text(path, data, encoding=encoding)

    monkeypatch.setattr(_chromium.time, "monotonic", lambda: now)
    monkeypatch.setattr(Path, "write_text", write_text)
    session._call = call

    expected_error = {
        "attach": _chromium.ChromiumError,
        "write": OSError,
        "enable": _chromium.ChromiumError,
    }[failure_stage]
    with pytest.raises(expected_error):
        session._page_session("<p>probe</p>", 5.0)

    assert calls[-1][0] == "Target.closeTarget"
    assert 0.0 < calls[-1][1] <= 5.0
    assert not page_path.exists()
