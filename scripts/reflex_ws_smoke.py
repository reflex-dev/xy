"""End-to-end probe for the Reflex integration (reflex-integration.md §1/§2).

Drives headless Chromium at a *running* reflex-xy showcase app (see
examples/reflex: `reflex run`) and asserts the load-bearing claims of the
design:

1. ONE physical websocket to the backend carries both the app plane and the
   chart data plane (socket.io namespace multiplexing) — counted via CDP.
2. All three charts paint real pixels from binary socket payloads (screenshot
   evidence; there are no HTTP data endpoints to fall back on).
3. Deep zoom drills the 1M-point density scatter to exact points
   (density_view round-trips over the socket, §16), and hovering a drilled
   point closes the semantic loop: kernel pick -> reflex event -> state
   delta -> DOM readout.
4. Streaming: clicking "go live" grows the live trace via `append` pushes.

Usage:
    python3 scripts/reflex_ws_smoke.py [--frontend http://localhost:3100]

Stdlib only (repo CDP driver + a minimal PNG reader); needs the demo app
already serving and a Chromium binary.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from xy._chromium import ChromiumSession  # noqa: E402

CHROMIUM_CANDIDATES = [
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chromium() -> str:
    for candidate in CHROMIUM_CANDIDATES:
        path = Path(candidate)
        if path.is_dir():
            for sub in ("chrome-linux/chrome", "chrome"):
                if (path / sub).exists():
                    return str(path / sub)
            hits = sorted(path.glob("**/chrome"))
            if hits:
                return str(hits[0])
        resolved = shutil.which(candidate) if not path.is_absolute() else candidate
        if resolved and Path(resolved).exists() and not Path(resolved).is_dir():
            return resolved
    raise SystemExit("no chromium found; set --chromium")


def decode_png(data: bytes) -> tuple[int, int, int, bytearray]:
    """Minimal PNG reader (8-bit RGB/RGBA, no interlace) -> (w, h, channels, pixels)."""
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
            channels = {2: 3, 6: 4}[color]
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
        if filt == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filt == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:  # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:  # Paeth
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


def ink_fraction(png: bytes, rect: dict, dpr: float) -> float:
    """Fraction of pixels inside rect that differ from near-white."""
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
            if px[o] < 245 or px[o + 1] < 245 or px[o + 2] < 245:
                ink += 1
    return ink / total


class Probe:
    """One attached tab with Runtime/Network/Input access."""

    def __init__(self, session: ChromiumSession, url: str) -> None:
        self.s = session
        target = session._call("Target.createTarget", {"url": "about:blank"})
        self.target_id = target["targetId"]
        session._call("Target.activateTarget", {"targetId": target["targetId"]})
        attached = session._call(
            "Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}
        )
        self.sid = attached["sessionId"]
        self._call("Page.bringToFront")
        self._call("Network.enable")
        self._call("Page.enable")
        self._call("Runtime.enable")
        # NOTE: no Emulation.setDeviceMetricsOverride here — with emulation
        # active, synthetic mouseMoved events stop producing the pointermove
        # stream hover picking listens to (wheel/click still work). Headless
        # runs at its default viewport instead; rect-relative math below
        # keeps the assertions layout-independent.
        self._call("Page.navigate", {"url": url})

    def _call(self, method: str, params: dict | None = None, timeout_s: float = 60.0):
        return self.s._call(method, params, session_id=self.sid, timeout_s=timeout_s)

    def eval(self, expression: str, timeout_s: float = 30.0):
        reply = self._call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout_s=timeout_s,
        )
        if reply.get("exceptionDetails"):
            raise RuntimeError(f"page exception: {json.dumps(reply['exceptionDetails'])[:400]}")
        return reply.get("result", {}).get("value")

    def wait_for(self, expression: str, *, timeout_s: float = 60.0, label: str = "condition"):
        deadline = time.monotonic() + timeout_s
        last = None
        while time.monotonic() < deadline:
            last = self.eval(expression)
            if last:
                return last
            time.sleep(0.25)
        raise SystemExit(f"timeout waiting for {label}; last={last!r}")

    def backend_websockets(self) -> list[str]:
        """Websockets to the app backend (excludes vite's dev-mode HMR socket)."""
        self.eval("1")  # pump queued CDP events
        urls: list[str] = []
        for (sid, method), events in self.s._events.items():
            if sid == self.sid and method == "Network.webSocketCreated":
                urls.extend(e.get("url", "") for e in events)
        return [u for u in urls if "/_event" in u or "/_xy" in u]

    def sent_ws_frames(self, needle: str) -> list[str]:
        """Payloads of sent websocket frames containing `needle`."""
        self.eval("1")
        out: list[str] = []
        for (sid, method), events in self.s._events.items():
            if sid == self.sid and method == "Network.webSocketFrameSent":
                for e in events:
                    data = e.get("response", {}).get("payloadData", "")
                    if needle in data:
                        out.append(data)
        return out

    def binary_ws_frames(self) -> int:
        """Count received websocket binary frames (socket.io attachments)."""
        self.eval("1")
        return sum(
            1
            for (sid, method), events in self.s._events.items()
            if sid == self.sid and method == "Network.webSocketFrameReceived"
            for event in events
            if event.get("response", {}).get("opcode") == 2
        )

    def closed_websockets(self) -> int:
        self.eval("1")
        return sum(
            len(events)
            for (sid, method), events in self.s._events.items()
            if sid == self.sid and method == "Network.webSocketClosed"
        )

    def screenshot(self) -> bytes:
        shot = self._call(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True},
            timeout_s=60.0,
        )
        return base64.b64decode(shot["data"])

    def rect(self, element_id: str, *, page_coords: bool = False) -> dict:
        scroll = "window.scrollX, window.scrollY" if page_coords else "0, 0"
        return self.eval(
            f"(() => {{ const [sx, sy] = [{scroll}];"
            f" const r = document.getElementById('{element_id}').getBoundingClientRect();"
            " return {x: r.x + sx, y: r.y + sy, w: r.width, h: r.height}; })()"
        )

    def scroll_to(self, element_id: str) -> None:
        self.eval(
            f"document.getElementById('{element_id}')"
            ".scrollIntoView({block: 'center', behavior: 'instant'})"
        )
        time.sleep(0.3)

    def mouse(self, kind: str, x: float, y: float, **extra):
        self._call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, **extra},
        )

    def first_pick_target(self, view_id: str) -> dict | None:
        """Return a client-coordinate pixel occupied in the GPU pick buffer."""
        key = json.dumps(view_id)
        return self.eval(
            "(() => {"
            f" const v = window.__xy_views.get({key});"
            " const gl = v && v.gl;"
            " if (!v || !gl || !v.pickFbo) return null;"
            " if (v._pickDirty) v._renderPick();"
            " const w = v.canvas.width, h = v.canvas.height;"
            " const pixels = new Uint8Array(w * h * 4);"
            " gl.bindFramebuffer(gl.FRAMEBUFFER, v.pickFbo);"
            " gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);"
            " gl.bindFramebuffer(gl.FRAMEBUFFER, null);"
            " let p = -1;"
            " for (let i = 0; i < pixels.length; i += 4) {"
            "   if (pixels[i] || pixels[i + 1] || pixels[i + 2] || pixels[i + 3]) {"
            "     p = i / 4; break;"
            "   }"
            " }"
            " if (p < 0) return null;"
            " const px = p % w, py = Math.floor(p / w);"
            " const r = v.canvas.getBoundingClientRect();"
            " const dpr = v.dpr || window.devicePixelRatio || 1;"
            " const cssX = (px + 0.5) / dpr;"
            " const cssY = (h - py - 0.5) / dpr;"
            " const hit = v._pickAt(cssX, cssY);"
            " if (!hit) return null;"
            " return {x: r.left + cssX, y: r.top + cssY, trace: hit.trace,"
            "   index: hit.index};"
            " })()"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", default="http://localhost:3100")
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--screenshot", default=None, help="save the final page PNG here")
    args = parser.parse_args()

    chromium = args.chromium or find_chromium()
    print(f"chromium: {chromium}")
    failures: list[str] = []

    with ChromiumSession(chromium, gl="software", sandbox=False) as session:
        probe = Probe(session, args.frontend)

        # 1) every chart mounts a view (six live figure vars + one static Chart)
        probe.wait_for(
            "window.__xy_views && window.__xy_views.size >= 6",
            timeout_s=120.0,
            label="mounted chart views",
        )
        print("mounted views:", probe.eval("Array.from(window.__xy_views.keys()).sort()"))

        # 2) exactly one physical websocket to the backend for both planes
        time.sleep(1.5)
        ws = probe.backend_websockets()
        print(f"backend websockets: {len(ws)}")
        if len(ws) != 1:
            failures.append(f"expected exactly 1 backend websocket (shared transport), got {ws}")

        binary_frames = probe.binary_ws_frames()
        print(f"binary websocket frames received: {binary_frames}")
        if binary_frames == 0:
            failures.append("no binary socket.io attachments reached the browser")

        # 2b) the direct-Chart mount is truly static: it never subscribes. The
        #     six live sources (five figure vars + one inline() token) each sub.
        subs = probe.sent_ws_frames('"sub"')
        print(f"sub frames sent: {len(subs)}")
        if len(subs) < 6:
            failures.append(f"expected >= 6 sub frames (live sources), got {len(subs)}")

        # 3) pixels: every chart paints ink inside its rect (full-page shot,
        #    rects in page coordinates so below-the-fold charts count too)
        time.sleep(1.0)
        png = probe.screenshot()
        if args.screenshot:
            Path(args.screenshot).write_bytes(png)
            print(f"saved initial evidence to {args.screenshot}")
        checks = (("cloud", 0.02), ("hist", 0.02), ("live", 0.005), ("inline", 0.005))
        for chart_id, min_ink in checks:
            frac = ink_fraction(png, probe.rect(chart_id, page_coords=True), 1.0)
            print(f"{chart_id}: ink fraction {frac:.2%}")
            if frac < min_ink:
                failures.append(f"{chart_id} looks blank ({frac:.2%} < {min_ink:.0%})")

        # 4) deep zoom drills density -> exact points (§16 over the socket) …
        # The chart is taller than Chromium's default headless viewport.  Put
        # its interaction surface on-screen before dispatching trusted CDP
        # wheel/pointer input; off-viewport coordinates are silently ignored.
        probe.scroll_to("cloud")
        target = probe.eval(
            "(() => { const v = window.__xy_views.get('cloud');"
            " const r = v.canvas.getBoundingClientRect();"
            " const x = r.left + r.width * 0.55, y = r.top + r.height * 0.5;"
            " const hit = document.elementFromPoint(x, y);"
            " return {x, y, rect: {x: r.x, y: r.y, w: r.width, h: r.height},"
            " viewport: {w: innerWidth, h: innerHeight},"
            " hit: hit && hit.tagName, hitsCanvas: hit === v.canvas}; })()"
        )
        print(f"cloud input target: {target}")
        if not target["hitsCanvas"]:
            raise SystemExit(
                "cloud interaction precondition failed: CDP coordinates do not hit "
                f"the chart canvas (rect={target['rect']}, viewport={target['viewport']}, "
                f"target={target['hit']!r})"
            )
        cx, cy = target["x"], target["y"]
        probe.mouse("mouseMoved", cx, cy)
        for _ in range(16):
            probe.mouse("mouseWheel", cx, cy, deltaX=0, deltaY=-240)
            time.sleep(0.15)
        zoom_state = probe.eval(
            "(() => { const v = window.__xy_views.get('cloud');"
            " const g = v.gpuTraces[0]; return {view: v.view, seq: v.seq,"
            " tier: g.tier, drill: !!g.drill}; })()"
        )
        print(f"deep-zoom state: {zoom_state}")
        probe.wait_for(
            "(() => { const g = window.__xy_views.get('cloud').gpuTraces[0];"
            " return !!(g && (g.drill || g.tier !== 'density')); })()",
            timeout_s=60.0,
            label="density drill to exact points",
        )
        print("drill: density tier swapped to exact points")

        # … and hovering a drilled point closes the semantic event loop:
        # GPU pick -> socket pick round-trip -> reflex event -> state delta.
        try:
            probe.wait_for(
                "(() => { const v = window.__xy_views.get('cloud');"
                " if (!v || !v.gpuTraces[0].drill) return false;"
                " if (v._pickDirty) v._renderPick();"
                " const gl = v.gl, w = v.canvas.width, h = v.canvas.height;"
                " const pixels = new Uint8Array(w * h * 4);"
                " gl.bindFramebuffer(gl.FRAMEBUFFER, v.pickFbo);"
                " gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);"
                " gl.bindFramebuffer(gl.FRAMEBUFFER, null);"
                " return pixels.some((value) => value !== 0); })()",
                timeout_s=15.0,
                label="a drilled point in the GPU pick buffer",
            )
            point = probe.first_pick_target("cloud")
            if point is None:
                raise SystemExit("GPU pick buffer was nonempty but yielded no pickable point")
            print(f"hovering drilled GPU point: {point}")
            probe.mouse("mouseMoved", point["x"], point["y"])
            found_row = probe.wait_for(
                "(document.body.innerText.match(/x=-?[0-9.]+/) || [null])[0]",
                timeout_s=15.0,
                label="hover readout",
            )
            print(f"hover readout shows picked row: {found_row!r}")
        except SystemExit:
            failures.append("hover over drilled points never updated the reflex readout")

        # 5) streaming: click go-live, live trace vertex count must grow
        n_before = probe.eval("(window.__xy_views.get('live').gpuTraces[0] || {n: 0}).n || 0")
        probe.scroll_to("stream-btn")  # the button sits below the fold
        btn = probe.eval(
            "(() => { const b = document.getElementById('stream-btn');"
            " const r = b.getBoundingClientRect();"
            " return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()"
        )
        probe.mouse("mouseMoved", btn["x"], btn["y"])
        probe.mouse("mousePressed", btn["x"], btn["y"], button="left", buttons=1, clickCount=1)
        probe.mouse("mouseReleased", btn["x"], btn["y"], button="left", buttons=0, clickCount=1)
        probe.wait_for(
            "(() => { const g = window.__xy_views.get('live').gpuTraces[0];"
            f" return !!(g && g.n > {n_before} + 2); }})()",
            timeout_s=30.0,
            label="live trace growing via append pushes",
        )
        n_after = probe.eval("window.__xy_views.get('live').gpuTraces[0].n")
        print(f"live stream: {n_before} -> {n_after} vertices (append pushes)")

        if args.screenshot:
            Path(args.screenshot).write_bytes(probe.screenshot())
            print(f"saved {args.screenshot}")

        # 6) renderer teardown releases every resource it owns.  The React
        # wrapper's effect cleanup calls the same idempotent destroy method;
        # direct invocation keeps the assertions observable before host
        # teardown destroys the page execution context.
        teardown = probe.eval(
            "(() => { const views = Array.from(window.__xy_views?.values?.() || []);"
            " for (const view of views) view.destroy();"
            " return views.map((view) => ({"
            "   destroyed: view._destroyed === true, listeners: view._listeners.length,"
            "   worker: view._rebinWorker == null, gl: view.gl === null,"
            "   comm: view._unsubscribeComm === null, connected: view.root.isConnected"
            " })); })()"
        )
        print(f"destroyed views: {len(teardown)}")
        if len(teardown) < 6 or any(
            not item["destroyed"]
            or item["listeners"] != 0
            or not item["worker"]
            or not item["gl"]
            or not item["comm"]
            or item["connected"]
            for item in teardown
        ):
            failures.append(f"renderer teardown leaked resources: {teardown}")

        # Reflex installs pagehide/beforeunload as its host-transport teardown
        # path.  Exercise that lifecycle while the CDP target remains alive so
        # Network.webSocketClosed is observable (closing the target first drops
        # its final target-scoped Network events).
        probe.eval(
            "window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false})); true"
        )
        deadline = time.monotonic() + 15.0
        closed = 0
        while time.monotonic() < deadline:
            closed = probe.closed_websockets()
            if closed >= 1:
                break
            time.sleep(0.1)
        print(f"closed backend websockets: {closed}")
        if closed < 1:
            failures.append("backend websocket remained open after page teardown")
        session._call("Target.closeTarget", {"targetId": probe.target_id})

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("\nreflex-xy websocket smoke: all checks passed")


if __name__ == "__main__":
    main()
