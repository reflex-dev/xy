#!/usr/bin/env python3
"""Matplotlib WebAgg host for the UX benchmark.

Serves the real WebAgg page (matplotlib's own tornado app + mpl.js client) and
a tiny CORS-enabled sidecar with the ground truth the in-page probe cannot
know — the client is a dumb raster terminal, so axis limits and sentinel
pixel positions come from the server's own transforms:

    GET /state -> {"xlim", "ylim", "sentinel_px": [[px,py]|null, ...],
                   "w", "h"}   (top-left CSS pixel origin, dpr=1)

Interaction is the backend's own: the probe clicks the Zoom toolbar tool and
performs rubber-band drags; the server zooms and pushes a fresh raster —
matplotlib's idiomatic path, not a synthetic API call.

Prints META {"port", "state_port", "n", "sentinels", "build_ms"} then serves.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from _ux_live_host import SENTINELS, make_data

WIDTH = 900
HEIGHT = 420
DPI = 100
STATE_TIMEOUT_S = 10


def call_on_ioloop(loop: Any, callback: Callable[[], dict]) -> dict:
    """Run a figure-state read on WebAgg's owner thread."""
    result: concurrent.futures.Future[dict] = concurrent.futures.Future()

    def invoke() -> None:
        try:
            result.set_result(callback())
        except BaseException as exc:
            result.set_exception(exc)

    loop.add_callback(invoke)
    return result.result(timeout=STATE_TIMEOUT_S)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, required=True)
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("WebAgg")
    matplotlib.rcParams["webagg.address"] = "127.0.0.1"
    # WebAgg binds inside ``initialize`` and retains that socket.  Let its
    # built-in retry loop choose an available port, then report the port it
    # actually bound; probing a free port and releasing it first is racy.
    matplotlib.rcParams["webagg.port_retries"] = 50
    matplotlib.rcParams["webagg.open_in_browser"] = False
    import matplotlib.pyplot as plt
    import tornado.ioloop
    from matplotlib.backends.backend_webagg import WebAggApplication

    x, y = make_data(args.n)
    t0 = time.perf_counter()
    fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
    ax.scatter(x, y)
    build_ms = (time.perf_counter() - t0) * 1e3
    WebAggApplication.initialize()
    port = WebAggApplication.port
    webagg_loop = tornado.ioloop.IOLoop.instance()

    def state() -> dict:
        # transData: data -> display px, origin bottom-left; the canvas is
        # top-left, dpr is forced to 1, so flip y against the figure height.
        h_px = fig.bbox.height
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        pts = []
        for sx, sy in SENTINELS:
            if not (min(xlim) <= sx <= max(xlim) and min(ylim) <= sy <= max(ylim)):
                pts.append(None)
                continue
            px, py = ax.transData.transform((sx, sy))
            pts.append([float(px), float(h_px - py)])
        # Axes bbox in top-left CSS px: a zoom drag with a corner outside it
        # is silently ignored by the backend, so the client must clamp.
        bb = ax.bbox
        return {
            "xlim": list(xlim),
            "ylim": list(ylim),
            "sentinel_px": pts,
            "w": float(fig.bbox.width),
            "h": float(h_px),
            "axes_px": [
                float(bb.x0),
                float(h_px - bb.y1),
                float(bb.x1),
                float(h_px - bb.y0),
            ],
        }

    class StateHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server contract
            # WebAgg mutates axes state on its Tornado loop.  Marshal the
            # snapshot there instead of reading the figure concurrently from
            # this ThreadingHTTPServer worker.
            body = json.dumps(call_on_ioloop(webagg_loop, state)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # quiet
            del args

    state_server = ThreadingHTTPServer(("127.0.0.1", 0), StateHandler)
    state_port = state_server.server_address[1]
    threading.Thread(target=state_server.serve_forever, daemon=True).start()

    print(
        "META "
        + json.dumps(
            {
                "port": port,
                "state_port": state_port,
                "n": args.n,
                "sentinels": [list(s) for s in SENTINELS],
                "build_ms": build_ms,
                "mode": "webagg-exact",
            }
        ),
        flush=True,
    )
    plt.show()


if __name__ == "__main__":
    main()
