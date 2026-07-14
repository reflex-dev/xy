"""Persistent headless-Chromium driver over the DevTools protocol (stdlib only).

The one-shot ``--screenshot``/``--dump-dom`` probes in ``_browser.py`` pay
browser startup (~1-2 s) inside every measurement and cap page settling with a
virtual-time budget. For staged benchmarks that is exactly the overhead we need
to exclude: this module launches ONE Chromium with ``--remote-debugging-port``
and reuses it across iterations — navigate a fresh tab to a ``file://`` page,
``Runtime.evaluate`` an async probe expression, collect structured JSON, close
the tab, repeat. Wall-clock timings, no virtual time.

No third-party packages: the WebSocket client (RFC 6455, client side) is
implemented directly on ``socket`` — text frames only, which is all CDP uses.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit


class CdpError(RuntimeError):
    pass


class _WebSocket:
    """Minimal RFC 6455 client: masked text frames out, any frames in."""

    def __init__(self, url: str, *, timeout_s: float = 30.0) -> None:
        parts = urlsplit(url)
        assert parts.scheme == "ws" and parts.hostname is not None
        self._sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout_s)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parts.hostname}:{parts.port or 80}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(handshake.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise CdpError("websocket handshake: connection closed")
            response += chunk
        status = response.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise CdpError(f"websocket handshake rejected: {status!r}")
        # Anything past the header block is the start of the first frame.
        self._buffer = response.split(b"\r\n\r\n", 1)[1]

    def settimeout(self, timeout_s: float | None) -> None:
        self._sock.settimeout(timeout_s)

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buffer) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise CdpError("websocket closed mid-frame")
            self._buffer += chunk
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        length = len(payload)
        header = bytearray([0x81])  # FIN + text opcode
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header += length.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += length.to_bytes(8, "big")
        mask = secrets.token_bytes(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        """Next complete text message (transparently answers pings)."""
        message = bytearray()
        while True:
            b0, b1 = self._recv_exact(2)
            opcode, fin = b0 & 0x0F, b0 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = int.from_bytes(self._recv_exact(2), "big")
            elif length == 127:
                length = int.from_bytes(self._recv_exact(8), "big")
            if b1 & 0x80:  # masked server frame: illegal, but read it out
                mask = self._recv_exact(4)
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._recv_exact(length)))
            else:
                data = self._recv_exact(length)
            if opcode == 0x9:  # ping -> pong
                self._sock.sendall(bytes([0x8A, 0x80]) + secrets.token_bytes(4))
                continue
            if opcode == 0x8:
                raise CdpError("websocket closed by browser")
            if opcode in (0x1, 0x0):
                message += data
                if fin:
                    return message.decode("utf-8")
                continue
            # binary/pong frames: CDP never sends these mid-conversation; skip.

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.sendall(bytes([0x88, 0x80]) + secrets.token_bytes(4))
        self._sock.close()


class Browser:
    """One headless Chromium shared across many page loads."""

    def __init__(
        self,
        chromium: str,
        *,
        gl: str = "software",
        window: tuple[int, int] = (1280, 800),
        extra_flags: list[str] | None = None,
        launch_timeout_s: float = 30.0,
    ) -> None:
        assert gl in ("software", "hardware")
        self._tmp = tempfile.TemporaryDirectory(prefix="xy-cdp-")
        stderr_path = Path(self._tmp.name) / "chromium-stderr.log"
        self._stderr_file = stderr_path.open("w+b")
        gl_flags = (
            ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] if gl == "software" else []
        )
        self._proc = subprocess.Popen(
            [
                chromium,
                "--headless=new",
                "--remote-debugging-port=0",
                f"--user-data-dir={Path(self._tmp.name) / 'profile'}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--enable-precise-memory-info",
                *gl_flags,
                f"--window-size={window[0]},{window[1]}",
                *(extra_flags or []),
            ],
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_file,
        )
        ws_url = self._wait_for_ws_url(stderr_path, launch_timeout_s)
        self._ws = _WebSocket(ws_url)
        self._next_id = 0
        # Events observed while waiting for replies, keyed by (sessionId, method).
        self._events: dict[tuple[str | None, str], list[dict[str, Any]]] = {}

    def _wait_for_ws_url(self, stderr_path: Path, timeout_s: float) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                tail = stderr_path.read_text(errors="replace")[-500:]
                raise CdpError(f"Chromium exited during launch: {tail}")
            m = re.search(
                r"DevTools listening on (ws://\S+)",
                stderr_path.read_text(errors="replace"),
            )
            if m:
                return m.group(1)
            time.sleep(0.05)
        raise CdpError("Chromium did not report a DevTools endpoint in time")

    def _call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        self._next_id += 1
        call_id = self._next_id
        message: dict[str, Any] = {"id": call_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        self._ws.settimeout(timeout_s)
        self._ws.send_text(json.dumps(message))
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"timeout waiting for {method} response")
            self._ws.settimeout(remaining)
            reply = json.loads(self._ws.recv_text())
            if reply.get("id") == call_id:  # ids are unique per connection
                if "error" in reply:
                    raise CdpError(f"{method}: {reply['error']}")
                return reply.get("result", {})
            self._dispatch_event(reply)

    def _dispatch_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method is None:
            return
        self._events.setdefault((message.get("sessionId"), method), []).append(
            message.get("params", {})
        )

    def wait_event(
        self, method: str, *, session_id: str | None, timeout_s: float
    ) -> dict[str, Any]:
        key = (session_id, method)
        deadline = time.monotonic() + timeout_s
        while True:
            queued = self._events.get(key)
            if queued:
                return queued.pop(0)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"timeout waiting for event {method}")
            self._ws.settimeout(remaining)
            self._dispatch_event(json.loads(self._ws.recv_text()))

    def new_page(self) -> "Page":
        target = self._call("Target.createTarget", {"url": "about:blank"})
        attached = self._call(
            "Target.attachToTarget",
            {"targetId": target["targetId"], "flatten": True},
        )
        page = Page(self, target["targetId"], attached["sessionId"])
        page._call("Page.enable")
        return page

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._ws.close()
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._stderr_file.close()
        self._tmp.cleanup()

    def __enter__(self) -> "Browser":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class Page:
    """One attached tab, addressed through the shared browser socket."""

    def __init__(self, browser: Browser, target_id: str, session_id: str) -> None:
        self._browser = browser
        self._target_id = target_id
        self._session_id = session_id

    def _call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        return self._browser._call(method, params, session_id=self._session_id, timeout_s=timeout_s)

    def navigate(self, url: str, *, timeout_s: float = 300.0) -> None:
        """Navigate and block until the load event (parse of the whole page)."""
        self._call("Page.navigate", {"url": url}, timeout_s=timeout_s)
        self._browser.wait_event(
            "Page.loadEventFired", session_id=self._session_id, timeout_s=timeout_s
        )

    def eval(self, expression: str, *, timeout_s: float = 300.0) -> Any:
        """Evaluate an (async) expression; JSON-serializable result by value."""
        result = self._call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "timeout": int(timeout_s * 1000),
            },
            timeout_s=timeout_s,
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("exception", {}).get("description") or details.get(
                "text", "evaluation failed"
            )
            raise CdpError(text[:800])
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._browser._call("Target.closeTarget", {"targetId": self._target_id})


def default_chromium() -> str | None:
    """Reuse the export-time discovery (env var, PATH, common installs)."""
    from xy.export import find_chromium

    return find_chromium(os.environ.get("XY_CHROMIUM"))
