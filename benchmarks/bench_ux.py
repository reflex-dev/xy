#!/usr/bin/env python3
"""Interactive-chart UX benchmark: load, gesture, settle — one contract per arm.

Implements the ceiling plan's measurement contract (see benchmarks/README.md
and _ux_probe.py). Every arm is a live interactive chart:

    xy          live host, kernel attached over a real WebSocket
    xy-exact    same host, density=False
    plotly      px.scatter HTML with scrollZoom enabled (all N in browser —
                that artifact IS plotly's interactive delivery)
    matplotlib  WebAgg server + mpl.js client; Zoom-tool rubber-band drags
    datashader  hvPlot/HoloViews on a Bokeh server; wheel zoom, re-datashade per view

Usage (plumbing check):
    python benchmarks/bench_ux.py --sizes 100000 --arms xy,xy-exact,plotly \
        --chrome "$CHROME" --out ux-100k.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psutil  # noqa: E402
import websocket  # noqa: E402

import _launch_interactive as interactive  # noqa: E402
import _ux_probe  # noqa: E402
from _ux_live_host import SENTINELS, make_data  # noqa: E402
from environment import collect_environment_metadata  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = Path(tempfile.gettempdir()) / "xy-ux-artifacts"
DEFAULT_SIZES = [100_000]
ARMS = ("xy", "xy-exact", "plotly", "matplotlib", "datashader")


def read_meta(host: subprocess.Popen[str], timeout_s: float = 120.0) -> str | None:
    """First META line from a host, or None if it never arrives.

    A bare readline() blocks forever when a host dies before printing or hangs
    during construction, which would stall the whole sweep on one cell.
    """
    import threading

    result: list[str] = []

    def pump() -> None:
        for line in host.stdout:  # type: ignore[union-attr]
            if line.startswith("META "):
                result.append(line.strip())
                return

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    thread.join(timeout_s)
    return result[0] if result else None


class TreePeakPoller:
    """Peak process-tree RSS of a child, sampled every 50 ms from spawn.

    A single end-of-run snapshot misses every transient (build spikes, the
    re-aggregation working set); the ceiling contract is peak, so poll from
    the moment the process exists until the probe is done.
    """

    def __init__(self, pid: int) -> None:
        import threading

        self._proc = psutil.Process(pid)
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak, interactive.tree_rss(self._proc))
            except psutil.NoSuchProcess:
                return
            self._stop.wait(0.05)

    def stop(self) -> int:
        self._stop.set()
        self._thread.join(timeout=2)
        return self.peak


PLOTLY_ARM_JS = r"""
window.__arm = {
  _gd: () => document.querySelector(".js-plotly-plot"),
  ready: function () {
    const gd = this._gd();
    return !!(gd && gd._fullLayout && gd._fullLayout.xaxis);
  },
  domain: function () {
    const fl = this._gd()._fullLayout;
    const xr = fl.xaxis.range, yr = fl.yaxis.range;
    return { x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] };
  },
  project: function (x, y) {
    const gd = this._gd();
    const fl = gd._fullLayout;
    const xr = fl.xaxis.range, yr = fl.yaxis.range;
    if (x < Math.min(...xr) || x > Math.max(...xr)) return null;
    if (y < Math.min(...yr) || y > Math.max(...yr)) return null;
    return {
      px: fl.xaxis._offset + fl.xaxis.l2p(x),
      py: fl.yaxis._offset + fl.yaxis.l2p(y),
    };
  },
  readbacks: function () {
    const gd = this._gd();
    const out = [];
    for (const canvas of gd.querySelectorAll("canvas")) {
      const gl =
        canvas.getContext("webgl2") || canvas.getContext("webgl") ||
        canvas.getContext("experimental-webgl");
      if (!gl) continue;
      gl.finish();
      const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
      if (!w || !h) continue;
      const data = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, data);
      const r = canvas.getBoundingClientRect();
      out.push({ data, w, h, topDown: false, cssW: r.width, cssH: r.height });
    }
    return out;
  },
  zoomInput: function (fx, fy, dir) {
    const gd = this._gd();
    const r = gd.getBoundingClientRect();
    const target = gd.querySelector(".nsewdrag") || gd;
    target.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true, cancelable: true,
      clientX: r.left + r.width * fx,
      clientY: r.top + r.height * fy,
      deltaY: dir > 0 ? -120 : 120,
      deltaMode: 0,
    }));
  },
};
"""


# WebAgg's client is a raster terminal: axis limits and sentinel projections
# come from the host's /state sidecar (server-side transData truth), cached by
# a poll loop.  Interaction is matplotlib's own idiom — the Zoom toolbar tool
# plus rubber-band drags — dispatched as real MouseEvents on canvas_div, which
# mpl.js forwards over its websocket for the server to act on.  One "input"
# from the engine advances a 6-step drag state machine (down, 4 moves, up),
# so the fixed wall-clock cadence drives complete successive box zooms.
WEBAGG_ARM_JS_TEMPLATE = r"""
window.__mplState = null;
(async function poll() {
  for (;;) {
    try {
      const r = await fetch("http://127.0.0.1:__STATE_PORT__/state");
      window.__mplState = await r.json();
    } catch (e) {}
    await new Promise((res) => setTimeout(res, 40));
  }
})();
window.__arm = {
  _canvas: () => {
    // mpl.js appends the raster canvas first, then the transparent rubberband
    // overlay; BOTH are pointer-events:none (events land on canvas_div), so
    // pick by DOM order, not interactivity.
    for (const c of document.querySelectorAll("canvas")) {
      const r = c.getBoundingClientRect();
      if (r.width >= 300 && r.height >= 150) return c;
    }
    return null;
  },
  _drag: { phase: 0, zoomArmed: false, lastXlim: "" },
  ready: function () {
    return !!(window.__mplState && this._canvas());
  },
  domain: function () {
    const s = window.__mplState;
    if (!s) return null;
    return {
      x0: Math.min(...s.xlim), x1: Math.max(...s.xlim),
      y0: Math.min(...s.ylim), y1: Math.max(...s.ylim),
    };
  },
  project: function (x, y) {
    // The engine only projects sentinels; match against the server's list.
    const s = window.__mplState;
    if (!s) return null;
    for (let i = 0; i < s.sentinel_px.length; i++) {
      const [sx, sy] = __SENTINELS__[i];
      if (Math.abs(sx - x) < 1e-9 && Math.abs(sy - y) < 1e-9)
        return s.sentinel_px[i] === null
          ? null
          : { px: s.sentinel_px[i][0], py: s.sentinel_px[i][1] };
    }
    return null;
  },
  readbacks: function () {
    const c = this._canvas();
    const ctx = c.getContext("2d");
    const img = ctx.getImageData(0, 0, c.width, c.height);
    const r = c.getBoundingClientRect();
    return [{ data: img.data, w: c.width, h: c.height, topDown: true,
              cssW: r.width, cssH: r.height }];
  },
  _mouse: function (type, px, py) {
    const c = this._canvas();
    const r = c.getBoundingClientRect();
    (c.parentElement || c).dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, button: 0,
      buttons: type === "mouseup" ? 0 : 1,
      clientX: r.left + px, clientY: r.top + py,
    }));
  },
  zoomInput: function (fx, fy, dir) {
    if (!this._drag.zoomArmed) {
      // mpl.js labels toolbar buttons only via their icon's alt text (its
      // classList assignment is a no-op on the read-only property, so there
      // is no usable class to select on).
      for (const b of document.querySelectorAll("button")) {
        const img = b.querySelector("img");
        if (img && /zoom to rect/i.test(img.alt || "")) {
          b.click();
          this._drag.zoomArmed = true;
          break;
        }
      }
      if (!this._drag.zoomArmed) return;
    }
    const c = this._canvas();
    const r = c.getBoundingClientRect();
    const st = window.__mplState;
    // The engine's fx,fy are data-domain fractions, but this canvas includes
    // figure margins — aim the box at the server-projected target sentinel
    // pixel instead, which the box keeps in view by construction.
    const sp = st && st.sentinel_px[0];
    const tx = sp ? sp[0] : r.width * fx;
    const ty = sp ? sp[1] : r.height * fy;
    // A drag with any corner outside the axes bbox is silently ignored by
    // the backend, so clamp the whole box inside it (measured: an
    // out-of-axes press drops the entire zoom).
    const ax = (st && st.axes_px) || [0, 0, r.width, r.height];
    const inset = 3;
    const bw = r.width * 0.22, bh = r.height * 0.22;
    const x0 = Math.max(ax[0] + inset, tx - bw);
    const y0 = Math.max(ax[1] + inset, ty - bh);
    const x1 = Math.min(ax[2] - inset, tx + bw);
    const y1 = Math.min(ax[3] - inset, ty + bh);
    const p = this._drag.phase % 6;
    if (p === 0) {
      // A human draws the next box on the frame they can SEE.  When the
      // server is still applying the previous zoom (10M redraws take
      // seconds), starting another box against stale projections compounds
      // into drift that loses the target entirely (measured at 10M: final
      // window landed at x≈5.73, far off the sentinel).  Wait for the state
      // to reflect the previous release; skipped inputs model the human
      // waiting — the server's slowness lands in settle, where it belongs.
      const xlimNow = JSON.stringify(st ? st.xlim : null);
      if (this._drag.lastXlim && xlimNow === this._drag.lastXlim) return;
      if (!sp) return; // target not projectable on the frame we can see
      this._mouse("mousedown", x0, y0);
    } else if (p < 5) {
      const f = p / 4;
      this._mouse("mousemove", x0 + (x1 - x0) * f, y0 + (y1 - y0) * f);
    } else {
      this._mouse("mouseup", x1, y1);
      this._drag.lastXlim = JSON.stringify(st ? st.xlim : null);
    }
    this._drag.phase++;
  },
};
"""


# Bokeh 3.x renders inside shadow DOM (document.querySelectorAll finds no
# canvas), but the plot view exposes everything directly: primary.el is the
# 2D raster canvas, events_el is where the UIEventBus listens, and
# frame.x_scale.compute maps data to canvas pixels.  Wheel zoom is real: the
# WheelZoomTool is `active_tools=["wheel_zoom"]` in the host, the client
# zooms its ranges instantly, and the server re-datashades per view — the
# push lands in settle exactly like xy's drill.
DATASHADER_ARM_JS = r"""
window.__arm = {
  _pv: function () {
    if (this.__pv && this.__pv.frame) return this.__pv;
    try {
      const walk = (v, d) => {
        if (!v || d > 8) return null;
        if (v.frame && v.frame.bbox && v.canvas_view) return v;
        for (const c of (v.child_views || [])) { const r = walk(c, d + 1); if (r) return r; }
        return null;
      };
      for (const rv of [...Bokeh.index.roots]) {
        const f = walk(rv, 0);
        if (f) { this.__pv = f; return f; }
      }
    } catch (e) {}
    return null;
  },
  ready: function () {
    if (typeof Bokeh === "undefined") return false;
    const pv = this._pv();
    const ok = !!(pv && pv.canvas_view && pv.canvas_view.primary &&
                  pv.canvas_view.primary.el && isFinite(pv.model.x_range.start));
    if (ok && !this.__kicked) {
      // holoviews' resample_when pipeline renders nothing until a client
      // range event arrives (server-side stream kicks never reach the
      // session document).  One wheel-in/out pair at the same anchor is
      // multiplicatively self-inverse, wakes the pipeline, and is exactly
      // what a human does to a blank plot.  Cost lands in visible-complete.
      this.__kicked = true;
      const self = this;
      setTimeout(() => self._wheel(0.5, 0.5, +1), 50);
      setTimeout(() => self._wheel(0.5, 0.5, -1), 250);
    }
    return ok;
  },
  _wheel: function (fx, fy, dir) {
    const pv = this._pv();
    if (!pv) return;
    const target = pv.canvas_view.events_el;
    const r = target.getBoundingClientRect();
    target.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true, cancelable: true, composed: true,
      clientX: r.left + r.width * fx, clientY: r.top + r.height * fy,
      deltaY: dir > 0 ? -120 : 120, deltaMode: 0,
    }));
  },
  domain: function () {
    const pv = this._pv();
    if (!pv) return null;
    const xr = pv.model.x_range, yr = pv.model.y_range;
    return {
      x0: Math.min(xr.start, xr.end), x1: Math.max(xr.start, xr.end),
      y0: Math.min(yr.start, yr.end), y1: Math.max(yr.start, yr.end),
    };
  },
  project: function (x, y) {
    const pv = this._pv();
    if (!pv) return null;
    const d = this.domain();
    if (x < d.x0 || x > d.x1 || y < d.y0 || y > d.y1) return null;
    return { px: pv.frame.x_scale.compute(x), py: pv.frame.y_scale.compute(y) };
  },
  readbacks: function () {
    const pv = this._pv();
    const el = pv.canvas_view.primary.el;
    const img = el.getContext("2d").getImageData(0, 0, el.width, el.height);
    const r = el.getBoundingClientRect();
    return [{ data: img.data, w: el.width, h: el.height, topDown: true,
              cssW: r.width || el.width, cssH: r.height || el.height }];
  },
  zoomInput: function (fx, fy, dir) {
    const pv = this._pv();
    if (!pv) return;
    const target = pv.canvas_view.events_el;
    const r = target.getBoundingClientRect();
    // Aim at the target sentinel's true canvas position when it projects;
    // the engine's fx,fy are domain fractions and this canvas has margins.
    const sp = this.project(__SENTINEL0__[0], __SENTINEL0__[1]);
    if (sp) {
      target.dispatchEvent(new WheelEvent("wheel", {
        bubbles: true, cancelable: true, composed: true,
        clientX: r.left + sp.px, clientY: r.top + sp.py,
        deltaY: dir > 0 ? -120 : 120, deltaMode: 0,
      }));
    } else {
      this._wheel(fx, fy, dir);
    }
  },
};
"""


def plotly_artifact(n: int, path: Path) -> float:
    """Build the plotly arm's chart; returns build seconds (data excluded).

    Runs in its own child process (--plotly-build-child) so the build's peak
    RSS is attributable — a 10M to_html holds the figure plus a >1 GB HTML
    string, and inline in the orchestrator that transient belongs to nobody.
    """
    import plotly.express as px

    x, y = make_data(n)
    t0 = time.perf_counter()
    fig = px.scatter(x=x, y=y, width=900, height=420)
    html = fig.to_html(include_plotlyjs=True, full_html=True, config={"scrollZoom": True})
    path.write_text(html, encoding="utf-8")
    return time.perf_counter() - t0


def drive_browser(
    url: str,
    inject_js: list[str],
    *,
    chrome: str,
    timeout_s: float,
    memory_limit_bytes: int,
    software: bool,
    shots_prefix: Path | None = None,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    """Navigate, inject the arm adapter + probe engine, await UX_BENCH title.

    Same CDP pattern as the ceiling harness's browser_once, generalized to a
    URL and post-load script injection (served pages cannot embed the probe).
    When `shots_prefix` is set, each `UX_SHOT <name>` checkpoint from the
    probe is captured as `<shots_prefix>-<name>.png` — the frame the clock
    actually stopped on, for human verification.

    When `record_dir` is set, a CDP screencast records every frame the page
    presents from navigation until the chart is rendered (visible-complete),
    each written as `NNNNNN_<offset_ms>.jpg` with the offset measured from
    navigation.  Recording stops at visible-complete: the video is the load
    race, and the gesture and settle clocks never carry screencast cost.
    """
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td) / "profile"
        command = [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--enable-precise-memory-info",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            "--force-device-scale-factor=1",
            "--window-size=1100,600",
            f"--user-data-dir={profile}",
            "about:blank",
        ]
        if software:
            command[1:1] = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        else:
            command[1:1] = ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"]
        popen = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
        )
        proc = psutil.Process(popen.pid)
        start = time.monotonic()
        peak = 0
        ws = None
        try:
            port = interactive.wait_devtools(profile, popen)
            target = None
            while time.monotonic() - start < timeout_s:
                peak = max(peak, interactive.tree_rss(proc))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    targets = json.load(r)
                # Extension pages are also type "page"; taking the first match
                # nondeterministically probes the wrong document. Bind to the
                # target whose URL is the one we navigated.
                pages = [t for t in targets if t.get("type") == "page"]
                target = next((t for t in pages if t.get("url", "").startswith(url)), None) or next(
                    (t for t in pages if not t.get("url", "").startswith("chrome")),
                    None,
                )
                if target:
                    break
                time.sleep(0.02)
            if not target:
                raise TimeoutError("Chrome page target timeout")
            ws = websocket.create_connection(
                target["webSocketDebuggerUrl"], timeout=min(30, timeout_s)
            )
            call_id = 0

            def on_event(msg: dict[str, Any]) -> None:
                """Persist screencast frames; ack so Chrome keeps sending."""
                nonlocal frame_count
                if msg.get("method") != "Page.screencastFrame":
                    return
                params = msg.get("params", {})
                offset_ms = int((time.monotonic() - nav_epoch) * 1000)
                import base64

                path = record_dir / f"{frame_count:06d}_{offset_ms}.jpg"
                path.write_bytes(base64.b64decode(params["data"]))
                frame_count += 1
                ws.send(
                    json.dumps(
                        {
                            "id": 10_000_000 + frame_count,
                            "method": "Page.screencastFrameAck",
                            "params": {"sessionId": params["sessionId"]},
                        }
                    )
                )

            def evaluate(expr: str) -> Any:
                nonlocal call_id
                call_id += 1
                ws.send(
                    json.dumps(
                        {
                            "id": call_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True},
                        }
                    )
                )
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("method"):
                        on_event(msg)
                        continue
                    if msg.get("id") == call_id:
                        return msg.get("result", {}).get("result", {}).get("value")

            def command(method: str, params: dict[str, Any]) -> dict[str, Any]:
                nonlocal call_id
                call_id += 1
                ws.send(json.dumps({"id": call_id, "method": method, "params": params}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("method"):
                        on_event(msg)
                        continue
                    if msg.get("id") == call_id:
                        return msg.get("result", {})

            def capture(name: str) -> None:
                if shots_prefix is None:
                    return
                data = command("Page.captureScreenshot", {"format": "png"}).get("data")
                if data:
                    import base64

                    path = shots_prefix.with_name(f"{shots_prefix.name}-{name}.png")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(base64.b64decode(data))

            # Arm the probe BEFORE the page exists: scripts registered here run
            # at document start, so the clock observes the page from its first
            # moment.  Post-load injection floored every fast arm's number at
            # "when the probe started looking" (measured: xy's first observed
            # frame was already complete and stable).
            command("Page.enable", {})
            for script in inject_js:
                command("Page.addScriptToEvaluateOnNewDocument", {"source": script})

            frame_count = 0
            nav_epoch = None
            if record_dir is not None:
                record_dir.mkdir(parents=True, exist_ok=True)
                command(
                    "Page.startScreencast",
                    {"format": "jpeg", "quality": 80, "everyNthFrame": 1},
                )
            nav_epoch = time.monotonic()
            command("Page.navigate", {"url": url})

            last_stage = ""
            while time.monotonic() - start < timeout_s:
                rss = interactive.tree_rss(proc)
                peak = max(peak, rss)
                if rss > memory_limit_bytes:
                    return {
                        "status": "memory_limit",
                        "browser_peak_rss_bytes": peak,
                        "stage": last_stage,
                    }
                title = evaluate("document.title") or ""
                if title.startswith("UX_BENCH "):
                    result = json.loads(title[len("UX_BENCH ") :])
                    result.update({"status": "ok", "browser_peak_rss_bytes": peak})
                    if record_dir is not None:
                        result["recorded_frames"] = frame_count
                    return result
                if title.startswith("UX_ERROR "):
                    detail = title[len("UX_ERROR ") :]
                    try:
                        parsed = json.loads(detail)
                    except ValueError:
                        parsed = {"why": detail}
                    return {
                        "status": str(parsed.get("why", "error")),
                        "browser_peak_rss_bytes": peak,
                        "detail": parsed,
                    }
                if title.startswith("UX_SHOT "):
                    name = title[len("UX_SHOT ") :].strip()
                    capture(name)
                    if name == "visible-complete" and record_dir is not None:
                        # The video is the load race: it ends the moment this
                        # arm's chart is rendered.  Stopping here also keeps
                        # screencast cost out of the gesture and settle
                        # clocks entirely -- only the load phase carries it.
                        command("Page.stopScreencast", {})
                    evaluate("window.__shotDone = true")
                elif title.startswith("UX_STAGE "):
                    last_stage = title[len("UX_STAGE ") :]
                time.sleep(0.02)
            return {
                "status": "timeout",
                "browser_peak_rss_bytes": peak,
                "stage": last_stage,
            }
        except Exception as exc:  # noqa: BLE001 — report, don't crash the sweep
            return {
                "status": f"failed({type(exc).__name__})",
                "browser_peak_rss_bytes": peak,
                "error": str(exc)[:500],
            }
        finally:
            if ws is not None:
                ws.close()
            interactive.terminate_tree(proc)
            try:
                popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                popen.kill()


def run_xy_arm(
    arm: str,
    n: int,
    *,
    chrome: str,
    timeout_s: float,
    limit: int,
    software: bool,
    shots_prefix: Path | None = None,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    """Spawn the live host, probe it, tear it down. Host tree = python pool."""
    density = "off" if arm == "xy-exact" else "auto"
    host = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "_ux_live_host.py"),
            "--n",
            str(n),
            "--density",
            density,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    poller = TreePeakPoller(host.pid)
    try:
        meta_line = read_meta(host)
        if meta_line is None:
            err = host.stderr.read()[:800] if host.poll() is not None else "no META within timeout"
            return {"status": "host_failed", "detail": err}
        meta = json.loads(meta_line[len("META ") :])
        probe = _ux_probe.engine_js({"sentinels": meta["sentinels"]})
        row = drive_browser(
            f"http://127.0.0.1:{meta['port']}/",
            [probe],
            chrome=chrome,
            timeout_s=timeout_s,
            memory_limit_bytes=limit,
            software=software,
            shots_prefix=shots_prefix,
            record_dir=record_dir,
        )
        row["mode"] = meta["mode"]
        row["python_peak_rss_bytes"] = poller.stop()
        return row
    finally:
        poller.stop()
        host.kill()
        host.wait(timeout=5)


def run_webagg_arm(
    n: int,
    *,
    chrome: str,
    timeout_s: float,
    limit: int,
    software: bool,
    shots_prefix: Path | None = None,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    """Spawn the WebAgg host, probe its real page, tear it down."""
    host = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "_ux_webagg_host.py"),
            "--n",
            str(n),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    poller = TreePeakPoller(host.pid)
    try:
        meta_line = read_meta(host)
        if meta_line is None:
            err = host.stderr.read()[:800] if host.poll() is not None else "no META within timeout"
            return {"status": "host_failed", "detail": err}
        meta = json.loads(meta_line[len("META ") :])
        # WebAgg draws on demand: give the tornado app a beat to accept.
        time.sleep(0.3)
        arm_js = WEBAGG_ARM_JS_TEMPLATE.replace("__STATE_PORT__", str(meta["state_port"])).replace(
            "__SENTINELS__", json.dumps(meta["sentinels"])
        )
        probe = _ux_probe.engine_js({"sentinels": meta["sentinels"]})
        row = drive_browser(
            f"http://127.0.0.1:{meta['port']}/",
            [arm_js, probe],
            chrome=chrome,
            timeout_s=timeout_s,
            memory_limit_bytes=limit,
            software=software,
            shots_prefix=shots_prefix,
            record_dir=record_dir,
        )
        row["mode"] = meta["mode"]
        row["python_build_ms"] = meta["build_ms"]
        row["python_peak_rss_bytes"] = poller.stop()
        return row
    finally:
        poller.stop()
        host.kill()
        host.wait(timeout=5)


def run_datashader_arm(
    n: int,
    *,
    chrome: str,
    timeout_s: float,
    limit: int,
    software: bool,
    shots_prefix: Path | None = None,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    """Spawn the hvPlot/Bokeh host, probe its page, tear it down."""
    host = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "_ux_datashader_host.py"),
            "--n",
            str(n),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    poller = TreePeakPoller(host.pid)
    try:
        meta_line = read_meta(host)
        if meta_line is None:
            err = host.stderr.read()[:800] if host.poll() is not None else "no META within timeout"
            return {"status": "host_failed", "detail": err}
        meta = json.loads(meta_line[len("META ") :])
        arm_js = DATASHADER_ARM_JS.replace("__SENTINEL0__", json.dumps(meta["sentinels"][0]))
        probe = _ux_probe.engine_js({"sentinels": meta["sentinels"]})
        row = drive_browser(
            f"http://127.0.0.1:{meta['port']}/",
            [arm_js, probe],
            chrome=chrome,
            timeout_s=timeout_s,
            memory_limit_bytes=limit,
            software=software,
            shots_prefix=shots_prefix,
            record_dir=record_dir,
        )
        row["mode"] = meta["mode"]
        row["python_build_ms"] = meta["build_ms"]
        row["python_peak_rss_bytes"] = poller.stop()
        return row
    finally:
        poller.stop()
        host.kill()
        host.wait(timeout=5)


def run_plotly_arm(
    n: int,
    *,
    chrome: str,
    timeout_s: float,
    limit: int,
    software: bool,
    shots_prefix: Path | None = None,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACTS / f"plotly-{n}.html"
    builder = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--plotly-build-child",
            "--build-n",
            str(n),
            "--build-artifact",
            str(artifact),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    build_poller = TreePeakPoller(builder.pid)
    try:
        out, err = builder.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        builder.kill()
        out, err = builder.communicate()
        build_poller.stop()
        return {"status": "build_timeout", "detail": err[-500:]}
    python_peak = build_poller.stop()
    if builder.returncode != 0:
        return {"status": "build_failed", "detail": err[-500:]}
    try:
        build_s = float(out.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"status": "build_failed", "detail": f"unparseable build output: {out[-200:]!r}"}
    probe = _ux_probe.engine_js({"sentinels": [list(s) for s in SENTINELS]})
    row = drive_browser(
        artifact.resolve().as_uri(),
        [PLOTLY_ARM_JS, probe],
        chrome=chrome,
        timeout_s=timeout_s,
        memory_limit_bytes=limit,
        software=software,
        shots_prefix=shots_prefix,
        record_dir=record_dir,
    )
    row["mode"] = "scattergl" if n > 1000 else "scatter-svg"
    row["python_build_ms"] = build_s * 1e3
    row["python_peak_rss_bytes"] = python_peak
    artifact.unlink(missing_ok=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plotly-build-child", action="store_true")
    parser.add_argument("--build-n", type=int)
    parser.add_argument("--build-artifact", type=Path)
    parser.add_argument("--sizes", default=",".join(map(str, DEFAULT_SIZES)))
    parser.add_argument("--arms", default="xy,xy-exact,plotly")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--memory-gib", type=float, default=36)
    parser.add_argument("--software", action="store_true")
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="skip the per-arm screencast (recording is on by default)",
    )
    parser.add_argument(
        "--no-grid",
        action="store_true",
        help="skip assembling the synced grid video after the sweep",
    )
    parser.add_argument("--chrome", default=os.environ.get("CHROME", interactive.CHROME))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.plotly_build_child:
        if args.build_n is None or args.build_artifact is None:
            parser.error("--plotly-build-child requires --build-n and --build-artifact")
        print(plotly_artifact(args.build_n, args.build_artifact))
        return
    if args.out is None:
        parser.error("--out is required")

    sizes = [int(v) for v in args.sizes.split(",")]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = sorted(set(arms) - set(ARMS))
    if unknown:
        parser.error(f"unknown arms: {', '.join(unknown)}")
    limit = int(args.memory_gib * 2**30)

    shots_dir = args.out.parent / (args.out.stem + "-shots")
    video_dir = args.out.parent / (args.out.stem + "-video")
    rows = []
    for n in sizes:
        for arm in arms:
            prefix = shots_dir / f"{arm}-{n}"
            rec = None if args.no_record else (video_dir / f"{arm}-{n}")
            if arm in ("xy", "xy-exact"):
                row = run_xy_arm(
                    arm,
                    n,
                    chrome=args.chrome,
                    timeout_s=args.timeout,
                    limit=limit,
                    software=args.software,
                    shots_prefix=prefix,
                    record_dir=rec,
                )
            elif arm == "plotly":
                row = run_plotly_arm(
                    n,
                    chrome=args.chrome,
                    timeout_s=args.timeout,
                    limit=limit,
                    software=args.software,
                    shots_prefix=prefix,
                    record_dir=rec,
                )
            elif arm == "matplotlib":
                row = run_webagg_arm(
                    n,
                    chrome=args.chrome,
                    timeout_s=args.timeout,
                    limit=limit,
                    software=args.software,
                    shots_prefix=prefix,
                    record_dir=rec,
                )
            elif arm == "datashader":
                row = run_datashader_arm(
                    n,
                    chrome=args.chrome,
                    timeout_s=args.timeout,
                    limit=limit,
                    software=args.software,
                    shots_prefix=prefix,
                    record_dir=rec,
                )
            else:
                row = {"status": "not_implemented"}
            row.update({"arm": arm, "n": n})
            rows.append(row)
            print(
                json.dumps(
                    {
                        "arm": arm,
                        "n": n,
                        "status": row.get("status"),
                        "mode": row.get("mode"),
                        "visible_complete_ms": row.get("visible_complete_ms"),
                        "gesture_frame_p95_ms": row.get("gesture_frame_p95_ms"),
                        "settle_ms": row.get("settle_ms"),
                        "zoom_to_final_ms": row.get("zoom_to_final_ms"),
                        "python_peak_gib": round(
                            (row.get("python_peak_rss_bytes") or 0) / 2**30, 3
                        ),
                        "browser_peak_gib": round(
                            (row.get("browser_peak_rss_bytes") or 0) / 2**30, 3
                        ),
                    }
                ),
                flush=True,
            )

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "contract": "correct(sentinels+domain) then pixel-stable; fixed-cadence inputs",
        "screencast": "off" if args.no_record else "on (uniform across arms)",
        "sizes": sizes,
        "arms": arms,
        "environment": collect_environment_metadata(chromium=args.chrome),
        "results": rows,
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not args.no_record and not args.no_grid and video_dir.exists():
        # One synced grid per size: every arm replayed against a shared clock,
        # so a moment in the video is the same moment for all of them.
        for n in sizes:
            frames = [d for d in sorted(video_dir.glob(f"*-{n}")) if not d.name.startswith("_")]
            if not frames:
                continue
            # Staging lives outside video_dir: a sibling named `_grid-{n}`
            # inside it is matched by the same `*-{n}` glob, so on a rerun it
            # would be picked up as an arm and symlinked into itself.
            staged = video_dir.parent / f"{video_dir.name}-staging-{n}"
            if staged.exists():
                for old in staged.iterdir():
                    old.unlink()
            staged.mkdir(parents=True, exist_ok=True)
            for src in frames:
                link = staged / src.name
                if not link.exists():
                    link.symlink_to(src)
            grid = args.out.parent / f"{args.out.stem}-grid-{n}.mp4"
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parent / "make_ux_grid.py"),
                        str(staged),
                        "--out",
                        str(grid),
                        "--report",
                        str(args.out),
                    ],
                    check=True,
                    capture_output=True,
                )
                print(f"grid video: {grid}", flush=True)
            except subprocess.CalledProcessError as exc:
                print(f"grid video failed for n={n}: {exc.stderr[-300:]}", flush=True)

    print(args.out)


if __name__ == "__main__":
    main()
