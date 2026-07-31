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
    assert process.wait_calls == [10]
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

        def settimeout(self, timeout_s: float) -> None:
            self.timeouts.append(timeout_s)

        def send_text(self, _message: str) -> None:
            nonlocal now
            now += 4.0

        def recv_text(self) -> str:
            return json.dumps({"id": 1, "result": {"status": "ok"}})

    websocket = FakeWebSocket()
    session = object.__new__(_chromium.ChromiumSession)
    session._ws = websocket
    session._next_id = 0
    session._events = {}
    monkeypatch.setattr(_chromium.time, "monotonic", lambda: now)

    assert session._call("Page.navigate", timeout_s=5.0) == {"status": "ok"}
    assert websocket.timeouts == [pytest.approx(5.0), pytest.approx(1.0)]
