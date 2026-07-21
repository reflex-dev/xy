"""Persistent headless-Chromium session over the DevTools protocol (stdlib).

`export.html_to_png` launches a fresh Chromium per image, so batch export pays
browser startup (~1-2 s) per figure and loses to exporters that amortize it.
This module keeps ONE Chromium alive and drives it over CDP: navigate a tab to
a `file://` chart page, await the first painted frame, capture a screenshot,
close the tab, repeat. No third-party packages — the WebSocket client
(RFC 6455, client side) is implemented directly on `socket`; CDP only ever
uses text frames.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit


class ChromiumError(RuntimeError):
    pass


class _WebSocket:
    """Minimal RFC 6455 client: masked text frames out, any frames in."""

    def __init__(self, url: str, *, timeout_s: float = 30.0) -> None:
        parts = urlsplit(url)
        if parts.scheme != "ws" or parts.hostname is None:
            raise ChromiumError(f"unsupported DevTools endpoint {url!r}")
        self._sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout_s)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        self._sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {parts.hostname}:{parts.port or 80}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ChromiumError("websocket handshake: connection closed")
            response += chunk
        if b"101" not in response.split(b"\r\n", 1)[0]:
            raise ChromiumError("websocket handshake rejected")
        self._buffer = response.split(b"\r\n\r\n", 1)[1]

    def settimeout(self, timeout_s: float | None) -> None:
        self._sock.settimeout(timeout_s)

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buffer) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ChromiumError("websocket closed mid-frame")
            self._buffer += chunk
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # FIN + text opcode
        length = len(payload)
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
        self._sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

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
            if b1 & 0x80:  # masked server frame: illegal, but drain it
                mask = self._recv_exact(4)
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._recv_exact(length)))
            else:
                data = self._recv_exact(length)
            if opcode == 0x9:  # ping -> pong
                self._sock.sendall(bytes([0x8A, 0x80]) + secrets.token_bytes(4))
                continue
            if opcode == 0x8:
                raise ChromiumError("websocket closed by browser")
            if opcode in (0x1, 0x0):
                message += data
                if fin:
                    return message.decode("utf-8")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.sendall(bytes([0x88, 0x80]) + secrets.token_bytes(4))
        self._sock.close()


class ChromiumSession:
    """One headless Chromium reused across page loads and screenshots."""

    def __init__(
        self,
        executable: str,
        *,
        gl: str = "software",
        sandbox: bool = True,
        launch_timeout_s: float = 30.0,
    ) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xy-export-")
        stderr_path = Path(self._tmp.name) / "chromium-stderr.log"
        self._stderr_file = stderr_path.open("w+b")
        gl_flags = (
            ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] if gl == "software" else []
        )
        args = [
            executable,
            "--headless=new",
            "--remote-debugging-port=0",
            f"--user-data-dir={Path(self._tmp.name) / 'profile'}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            *gl_flags,
        ]
        if not sandbox:
            args.insert(2, "--no-sandbox")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=self._stderr_file)
        deadline = time.monotonic() + launch_timeout_s
        ws_url = None
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                tail = stderr_path.read_text(errors="replace")[-400:]
                raise ChromiumError(f"Chromium exited during launch: {tail}")
            m = re.search(
                r"DevTools listening on (ws://\S+)", stderr_path.read_text(errors="replace")
            )
            if m:
                ws_url = m.group(1)
                break
            time.sleep(0.05)
        if ws_url is None:
            raise ChromiumError("Chromium did not report a DevTools endpoint in time")
        self._ws = _WebSocket(ws_url)
        self._next_id = 0
        self._events: dict[tuple[Optional[str], str], list[dict[str, Any]]] = {}

    def _call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        self._next_id += 1
        call_id = self._next_id
        message: dict[str, Any] = {"id": call_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        self._ws.send_text(json.dumps(message))
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChromiumError(f"timeout waiting for {method}")
            self._ws.settimeout(remaining)
            reply = json.loads(self._ws.recv_text())
            if reply.get("id") == call_id:
                if "error" in reply:
                    raise ChromiumError(f"{method}: {reply['error']}")
                return reply.get("result", {})
            if reply.get("method"):
                self._events.setdefault((reply.get("sessionId"), reply["method"]), []).append(
                    reply.get("params", {})
                )

    def _wait_event(self, method: str, *, session_id: Optional[str], timeout_s: float) -> None:
        key = (session_id, method)
        deadline = time.monotonic() + timeout_s
        while True:
            queued = self._events.get(key)
            if queued:
                queued.pop(0)
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChromiumError(f"timeout waiting for event {method}")
            self._ws.settimeout(remaining)
            reply = json.loads(self._ws.recv_text())
            if reply.get("method"):
                self._events.setdefault((reply.get("sessionId"), reply["method"]), []).append(
                    reply.get("params", {})
                )

    def _page_session(self, html: str, timeout_s: float) -> tuple[str, str, "Path"]:
        """Open a fresh tab on `html` (written to disk) and return its ids."""
        target = self._call("Target.createTarget", {"url": "about:blank"})
        attached = self._call(
            "Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}
        )
        sid = attached["sessionId"]
        page_path = Path(self._tmp.name) / f"chart-{target['targetId'][:8]}.html"
        page_path.write_text(html, encoding="utf-8")
        self._call("Page.enable", session_id=sid, timeout_s=timeout_s)
        return target["targetId"], sid, page_path

    def _navigate_and_settle(self, sid: str, page_path: "Path", timeout_s: float) -> None:
        self._call(
            "Page.navigate", {"url": page_path.as_uri()}, session_id=sid, timeout_s=timeout_s
        )
        self._wait_event("Page.loadEventFired", session_id=sid, timeout_s=timeout_s)
        # First painted frame: the client draws via requestAnimationFrame
        # after the inline decode; two frames guarantee the paint landed.
        self._call(
            "Runtime.evaluate",
            {
                "expression": (
                    "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
                ),
                "awaitPromise": True,
            },
            session_id=sid,
            timeout_s=timeout_s,
        )

    def render_image(
        self,
        html: str,
        width: int,
        height: int,
        *,
        format: str = "png",
        scale: float = 2.0,
        quality: Optional[int] = None,
        transparent: bool = False,
        timeout_s: float = 120.0,
    ) -> bytes:
        """Load a standalone chart page in a fresh tab and screenshot it.

        `format` is a CDP screenshot format ("png", "jpeg", or "webp");
        `quality` applies to the lossy formats (0-100, encoder-defined
        default when omitted). `transparent` clears Chromium's default white
        page backdrop so alpha-capable formats keep the page's transparency."""
        if format not in ("png", "jpeg", "webp"):
            raise ChromiumError(f"unsupported screenshot format {format!r}")
        target_id, sid, page_path = self._page_session(html, timeout_s)
        try:
            self._call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": int(width),
                    "height": int(height),
                    "deviceScaleFactor": float(scale),
                    "mobile": False,
                },
                session_id=sid,
                timeout_s=timeout_s,
            )
            if transparent:
                self._call(
                    "Emulation.setDefaultBackgroundColorOverride",
                    {"color": {"r": 0, "g": 0, "b": 0, "a": 0}},
                    session_id=sid,
                    timeout_s=timeout_s,
                )
            self._navigate_and_settle(sid, page_path, timeout_s)
            params: dict[str, Any] = {
                "format": format,
                "clip": {
                    "x": 0,
                    "y": 0,
                    "width": int(width),
                    "height": int(height),
                    "scale": 1,
                },
                "captureBeyondViewport": True,
            }
            if quality is not None and format in ("jpeg", "webp"):
                params["quality"] = int(quality)
            shot = self._call("Page.captureScreenshot", params, session_id=sid, timeout_s=timeout_s)
            data = base64.b64decode(shot["data"])
            magics = {
                "png": (b"\x89PNG\r\n\x1a\n",),
                "jpeg": (b"\xff\xd8\xff",),
                "webp": (b"RIFF",),
            }
            if not any(data.startswith(m) for m in magics[format]):
                raise ChromiumError(f"screenshot output was not a {format.upper()}")
            return data
        finally:
            with contextlib.suppress(Exception):
                self._call("Target.closeTarget", {"targetId": target_id})
            page_path.unlink(missing_ok=True)

    def render_png(
        self,
        html: str,
        width: int,
        height: int,
        *,
        scale: float = 2.0,
        timeout_s: float = 120.0,
    ) -> bytes:
        """Compatibility wrapper: `render_image` with format="png"."""
        return self.render_image(html, width, height, scale=scale, timeout_s=timeout_s)

    def render_pdf(
        self,
        html: str,
        width: int,
        height: int,
        *,
        timeout_s: float = 120.0,
    ) -> bytes:
        """Print the standalone chart page to a single-page PDF.

        The page box matches the chart's CSS pixel size at the standard
        96 px/in ↔ 72 pt/in mapping. `scale` deliberately does not apply:
        PDF is resolution-independent, so device-pixel-ratio has no meaning
        here (raster layers print at the page's natural DPR)."""
        target_id, sid, page_path = self._page_session(html, timeout_s)
        try:
            self._call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": int(width),
                    "height": int(height),
                    "deviceScaleFactor": 1.0,
                    "mobile": False,
                },
                session_id=sid,
                timeout_s=timeout_s,
            )
            self._navigate_and_settle(sid, page_path, timeout_s)
            printed = self._call(
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "paperWidth": int(width) / 96.0,
                    "paperHeight": int(height) / 96.0,
                    "marginTop": 0,
                    "marginBottom": 0,
                    "marginLeft": 0,
                    "marginRight": 0,
                    "pageRanges": "1",
                    "preferCSSPageSize": False,
                },
                session_id=sid,
                timeout_s=timeout_s,
            )
            data = base64.b64decode(printed["data"])
            if not data.startswith(b"%PDF-"):
                raise ChromiumError("print output was not a PDF")
            return data
        finally:
            with contextlib.suppress(Exception):
                self._call("Target.closeTarget", {"targetId": target_id})
            page_path.unlink(missing_ok=True)

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

    def __enter__(self) -> "ChromiumSession":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
