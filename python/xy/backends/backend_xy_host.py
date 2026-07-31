"""Authenticated loopback browser host for Matplotlib compat figures.

This is the non-IPython counterpart of :mod:`backend_xy_widget`.  It serves
the same browser event adapter from a loopback-only HTTP server, polls a
cached SVG state, and queues browser messages for dispatch on Matplotlib's
calling thread.  Standalone HTML export intentionally does not use this host.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import weakref
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlsplit

if TYPE_CHECKING:
    from .backend_xy import FigureCanvasXY, FigureManagerXY
    from .display_list import DisplayList

_MAX_REQUEST_BYTES = 64 * 1024
_MAX_PENDING_EVENTS = 4096
_WIDGET_ESM = Path(__file__).with_name("backend_xy_widget.js")
_UI_DEFAULTS: dict[str, bool | str] = {
    "toolbar_enabled": False,
    "toolbar_mode": "",
    "toolbar_message": "",
    "toolbar_can_back": False,
    "toolbar_can_forward": False,
    "cursor": "pointer",
}


def _host_javascript() -> str:
    """Return the same-origin model used by the shared anywidget renderer."""
    return """\
import { render } from "./backend_xy_widget.js";

class LoopbackModel {
  constructor(state) {
    this.state = state;
    this.listeners = new Map();
    this.pendingSend = Promise.resolve();
  }
  get(name) { return this.state[name]; }
  on(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(callback);
  }
  off(name, callback) { this.listeners.get(name)?.delete(callback); }
  apply(next) {
    for (const [name, value] of Object.entries(next)) {
      if (this.state[name] === value) continue;
      this.state[name] = value;
      for (const callback of this.listeners.get(`change:${name}`) || []) callback();
    }
  }
  send(message) {
    const send = () =>
      fetch("./event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(message),
        cache: "no-store",
        keepalive: message?.name === "close_event",
      }).catch(() => undefined);
    this.pendingSend = this.pendingSend.then(send, send);
    return this.pendingSend;
  }
}

async function state(generation = null) {
  const query = generation === null ? "" : `?generation=${encodeURIComponent(generation)}`;
  const response = await fetch(`./state${query}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`XY host state failed: ${response.status}`);
  return response.json();
}

const model = new LoopbackModel(await state());
const cleanup = render({ model, el: document.getElementById("mount") });
let stopped = false;
let pollHandle = null;

async function poll() {
  if (stopped) return;
  try {
    model.apply(await state(model.get("generation")));
  } catch {
    // The Python process or figure may have closed. Keep the last frame visible.
  }
  if (!stopped) pollHandle = setTimeout(poll, 50);
}

function stop() {
  if (stopped) return;
  stopped = true;
  if (pollHandle !== null) clearTimeout(pollHandle);
  cleanup();
}

window.addEventListener("pagehide", stop, { once: true });
poll();
"""


def _host_html(title: str) -> bytes:
    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{safe_title}</title>"
        "<style>html,body{margin:0}#mount{display:block}</style>"
        '</head><body><div id="mount"></div>'
        '<script type="module" src="./host.js"></script>'
        "</body></html>\n"
    ).encode()


class LoopbackHost:
    """One loopback-only, token-authenticated live FigureCanvas host."""

    def __init__(self, manager: FigureManagerXY) -> None:
        self._manager_ref = weakref.ref(manager)
        self._title = f"XY figure {manager.num}"
        self._token = secrets.token_hex(32)
        self._prefix = f"/{self._token}/"
        self._events: queue.Queue[Mapping[str, Any]] = queue.Queue(maxsize=_MAX_PENDING_EVENTS)
        self._lock = threading.Lock()
        self._closed = False
        self._state: dict[str, Any] = {
            "svg": "",
            "width": 1.0,
            "height": 1.0,
            "generation": 0,
            "timer_interval": 0,
            **_UI_DEFAULTS,
        }
        host = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "XYLoopback/1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _headers(self, status: int, content_type: str, length: int) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; script-src 'self'; connect-src 'self'; "
                    "style-src 'unsafe-inline'; img-src 'self' data:",
                )
                self.end_headers()

            def _send(self, status: int, content_type: str, body: bytes = b"") -> None:
                self._headers(status, content_type, len(body))
                if body:
                    self.wfile.write(body)

            def _endpoint(self) -> str | None:
                path = urlsplit(self.path).path
                if not path.startswith(host._prefix):
                    return None
                endpoint = path[len(host._prefix) :]
                allowed = {"", "host.js", "backend_xy_widget.js", "state", "event"}
                return endpoint if endpoint in allowed else None

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                endpoint = self._endpoint()
                if endpoint is None:
                    self._send(404, "text/plain; charset=utf-8")
                elif endpoint == "":
                    self._send(
                        200,
                        "text/html; charset=utf-8",
                        _host_html(host._title),
                    )
                elif endpoint == "host.js":
                    self._send(
                        200,
                        "text/javascript; charset=utf-8",
                        _host_javascript().encode(),
                    )
                elif endpoint == "backend_xy_widget.js":
                    self._send(
                        200,
                        "text/javascript; charset=utf-8",
                        _WIDGET_ESM.read_bytes(),
                    )
                elif endpoint == "state":
                    query = parse_qs(urlsplit(self.path).query)
                    try:
                        generation = int(query.get("generation", [""])[0])
                    except ValueError:
                        generation = None
                    self._send(
                        200,
                        "application/json",
                        json.dumps(
                            host.snapshot(since_generation=generation),
                            separators=(",", ":"),
                        ).encode(),
                    )
                else:
                    self._send(405, "text/plain; charset=utf-8")

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if self._endpoint() != "event":
                    self._send(404, "text/plain; charset=utf-8")
                    return
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
                if content_type.strip().lower() != "application/json":
                    self._send(415, "text/plain; charset=utf-8")
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self._send(400, "text/plain; charset=utf-8")
                    return
                if length < 0 or length > _MAX_REQUEST_BYTES:
                    self._send(413, "text/plain; charset=utf-8")
                    return
                try:
                    value = json.loads(self.rfile.read(length))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._send(400, "text/plain; charset=utf-8")
                    return
                if not isinstance(value, Mapping):
                    self._send(400, "text/plain; charset=utf-8")
                    return
                try:
                    host._events.put_nowait(value)
                except queue.Full:
                    self._send(503, "text/plain; charset=utf-8")
                    return
                self._send(202, "application/json")

            def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                self._send(405, "text/plain; charset=utf-8")

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="xy-matplotlib-loopback",
            daemon=True,
        )
        self._thread.start()

    @property
    def url(self) -> str:
        """Return the unguessable URL for this figure's live browser page."""
        return f"http://127.0.0.1:{self._server.server_port}{self._prefix}"

    @property
    def closed(self) -> bool:
        return self._closed

    def refresh(
        self,
        display_list: DisplayList,
        *,
        generation: int,
        timer_interval: int,
        ui_state: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish a main-thread render snapshot for HTTP polling clients."""
        with self._lock:
            self._state.update(
                svg=display_list.to_svg(),
                width=max(1.0, float(display_list.width)),
                height=max(1.0, float(display_list.height)),
                generation=max(0, int(generation)),
                timer_interval=max(0, int(timer_interval)),
            )
            if ui_state is not None:
                self._state.update(self._normalize_ui_state(ui_state))

    @staticmethod
    def _normalize_ui_state(state: Mapping[str, Any]) -> dict[str, bool | str]:
        return {
            "toolbar_enabled": bool(state.get("toolbar_enabled", False)),
            "toolbar_mode": str(state.get("toolbar_mode", "")),
            "toolbar_message": str(state.get("toolbar_message", "")),
            "toolbar_can_back": bool(state.get("toolbar_can_back", False)),
            "toolbar_can_forward": bool(state.get("toolbar_can_forward", False)),
            "cursor": str(state.get("cursor", "pointer")),
        }

    def refresh_ui(self, state: Mapping[str, Any]) -> None:
        """Publish browser chrome state without serializing another frame."""
        with self._lock:
            self._state.update(self._normalize_ui_state(state))

    def refresh_timer(self, interval: int) -> None:
        """Publish timer-heartbeat state without serializing another frame."""
        with self._lock:
            self._state["timer_interval"] = max(0, int(interval))

    def snapshot(self, *, since_generation: int | None = None) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        if state["generation"] == since_generation:
            state.pop("svg")
            state.pop("width")
            state.pop("height")
        return state

    def pump(self) -> int:
        """Dispatch queued browser messages on Matplotlib's calling thread."""
        manager = self._manager_ref()
        if manager is None or self._closed:
            return 0
        canvas = cast("FigureCanvasXY", manager.canvas)
        delivered = 0
        while True:
            try:
                message = self._events.get_nowait()
            except queue.Empty:
                break
            widget = canvas.widget
            widget._on_custom_msg(widget, message, [])
            delivered += 1
            if self._closed:
                break
        return delivered

    def close(self) -> None:
        """Stop accepting events and release the loopback port and thread."""
        if self._closed:
            return
        self._closed = True
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


__all__ = ["LoopbackHost"]
