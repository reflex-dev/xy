"""Shared plumbing for the browser smokes that drive the example apps.

`reflex_lifecycle_smoke.py` and `visual_regression_smoke.py` run the FastAPI
example (`examples/fastapi`) with `uv run` and drive headless Chromium at its
routes over the DevTools protocol. This module holds the app launcher, the
Chromium finder, a CDP page `Probe`, and a stdlib PNG reader.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FASTAPI_APP_DIR = REPO_ROOT / "examples" / "fastapi"

sys.path.insert(0, str(REPO_ROOT / "python"))

from xy._chromium import ChromiumSession  # noqa: E402

CHROMIUM_CANDIDATES = (
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def find_chromium(explicit: str | None = None) -> str:
    for candidate in ([explicit] if explicit else []) + list(CHROMIUM_CANDIDATES):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir():
            for sub in ("chrome-linux/chrome", "chrome"):
                if (path / sub).exists():
                    return str(path / sub)
            hits = sorted(path.glob("**/chrome"))
            if hits:
                return str(hits[0])
            continue
        resolved = candidate if path.is_absolute() else shutil.which(candidate)
        if resolved and Path(resolved).is_file():
            return resolved
    raise SystemExit("no chromium binary found; pass one as argv[1]")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.contextmanager
def serve_fastapi_app(*, points: int = 200_000, timeout_s: float = 60.0) -> Iterator[str]:
    """Run `examples/fastapi` with `uv run` and yield its base URL.

    `points` sets XY_LIVE_POINTS for the drilldown demo.
    """
    port = _free_port()
    env = dict(os.environ)
    env["XY_LIVE_POINTS"] = str(points)
    env["PYTHONPATH"] = str(FASTAPI_APP_DIR)
    # Build the example's own environment once (installs xy + fastapi), then
    # start uvicorn from it without re-checking dependencies on startup.
    subprocess.run(
        ["uv", "sync", "--quiet"], cwd=str(FASTAPI_APP_DIR), env=env, check=True, timeout=600
    )
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--no-sync",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(FASTAPI_APP_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                raise SystemExit(f"uvicorn exited during launch:\n{out[-1200:]}")
            try:
                with urllib.request.urlopen(f"{base_url}/healthz", timeout=1.0) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.2)
        else:
            raise SystemExit("uvicorn did not become ready in time")
        yield base_url
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()
            proc.wait()


class Probe:
    """One attached Chromium tab driven over CDP, pointed at a live URL."""

    def __init__(
        self,
        session: ChromiumSession,
        url: str,
        *,
        init_script: str | None = None,
        emulate: tuple[int, int, float] | None = None,
    ) -> None:
        self.s = session
        target = session._call("Target.createTarget", {"url": "about:blank"})
        self.target_id = target["targetId"]
        attached = session._call(
            "Target.attachToTarget", {"targetId": self.target_id, "flatten": True}
        )
        self.sid = attached["sessionId"]
        self._call("Page.enable")
        self._call("Runtime.enable")
        if emulate is not None:
            width, height, scale = emulate
            self._call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False},
            )
        if init_script is not None:
            # Runs before any page script in this frame and every subframe, so
            # the wrap installs before the chart bundle assigns `window.xy`.
            self._call("Page.addScriptToEvaluateOnNewDocument", {"source": init_script})
        self._call("Page.navigate", {"url": url})

    def _call(self, method: str, params: dict | None = None, timeout_s: float = 60.0):
        return self.s._call(method, params, session_id=self.sid, timeout_s=timeout_s)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.s._call("Target.closeTarget", {"targetId": self.target_id})

    def eval(self, expression: str, timeout_s: float = 30.0):
        reply = self._call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout_s=timeout_s,
        )
        if reply.get("exceptionDetails"):
            raise RuntimeError(f"page exception: {json.dumps(reply['exceptionDetails'])[:500]}")
        return reply.get("result", {}).get("value")

    def wait_for(self, expression: str, *, timeout_s: float = 60.0, label: str = "condition"):
        deadline = time.monotonic() + timeout_s
        last = None
        while time.monotonic() < deadline:
            last = self.eval(expression)
            if last:
                return last
            time.sleep(0.2)
        raise SystemExit(f"timeout waiting for {label}; last={last!r}")

    def screenshot(self) -> bytes:
        shot = self._call(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True},
            timeout_s=60.0,
        )
        return base64.b64decode(shot["data"])

    def rect(self, selector: str, *, page_coords: bool = False) -> dict:
        scroll = "window.scrollX, window.scrollY" if page_coords else "0, 0"
        return self.eval(
            f"(() => {{ const [sx, sy] = [{scroll}];"
            f" const el = document.querySelector({json.dumps(selector)});"
            " if (!el) return null; const r = el.getBoundingClientRect();"
            " return {x: r.x + sx, y: r.y + sy, w: r.width, h: r.height}; })()"
        )


# --- stdlib PNG reader (8-bit RGB/RGBA, no interlace) ------------------------


def decode_png(data: bytes) -> tuple[int, int, int, bytearray]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, width, height, channels, idat = 8, 0, 0, 0, b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or interlace:
                raise ValueError("unsupported PNG variant")
            channels = {0: 1, 2: 3, 6: 4}[color]
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
    raw = zlib.decompress(idat)
    stride = width * channels
    out = bytearray(width * height * channels)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        filt = raw[src]
        src += 1
        line = bytearray(raw[src : src + stride])
        src += stride
        if filt == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, channels, out


def ink_fraction(png: bytes, rect: dict, dpr: float = 1.0) -> float:
    """Fraction of pixels inside `rect` that differ from near-white."""
    width, height, channels, px = decode_png(png)
    x0 = max(0, int(rect["x"] * dpr))
    y0 = max(0, int(rect["y"] * dpr))
    x1 = min(width, int((rect["x"] + rect["w"]) * dpr))
    y1 = min(height, int((rect["y"] + rect["h"]) * dpr))
    total = max(1, (x1 - x0) * (y1 - y0))
    ink = 0
    for y in range(y0, y1):
        row = (y * width) * channels
        for x in range(x0, x1):
            o = row + x * channels
            if channels == 1:
                if px[o] < 245:
                    ink += 1
            elif px[o] < 245 or px[o + 1] < 245 or px[o + 2] < 245:
                ink += 1
    return ink / total
