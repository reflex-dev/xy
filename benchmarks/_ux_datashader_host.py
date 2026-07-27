#!/usr/bin/env python3
"""Datashader host for the UX benchmark: hvPlot/HoloViews on a Bokeh server.

This is datashader's *interactive* deployment — the bare `Canvas.points`
raster has no pan/zoom and is not what the benchmark measures. Every view
change re-aggregates server-side; below `resample_when` visible rows the plot
switches to raw Bokeh points, which is how this arm meets the "zoom reaches
every point" bar.

Prints META {"port", "n", "sentinels", "build_ms", "mode"} then serves.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
import urllib.request

from _ux_live_host import SENTINELS, make_data

WIDTH = 900
HEIGHT = 420
# Match xy's direct-draw budget so the raw-points switch happens at a
# comparable depth to xy's drill-in (§5 / config.SCATTER_DENSITY_THRESHOLD).
RESAMPLE_WHEN = 200_000


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, required=True)
    args = parser.parse_args()

    import holoviews as hv
    import hvplot.pandas  # noqa: F401 — registers the .hvplot accessor
    import pandas as pd
    import panel as pn

    x, y = make_data(args.n)
    frame = pd.DataFrame({"x": x, "y": y})

    t0 = time.perf_counter()
    plot = frame.hvplot.scatter(
        x="x",
        y="y",
        datashade=True,
        resample_when=RESAMPLE_WHEN,
        width=WIDTH,
        height=HEIGHT,
    ).opts(active_tools=["wheel_zoom"])
    app = pn.panel(plot)
    build_ms = (time.perf_counter() - t0) * 1e3

    # holoviews 1.23 quirk (measured): with `resample_when` neither branch
    # evaluates until a range event fires, so the served page is blank until
    # the first interaction.  Wake the streams from a daemon thread after the
    # session connects — the practical workaround a real deployment needs;
    # its cost lands inside visible-complete, where it belongs.
    dmaps = plot.traverse(lambda o: o, [hv.DynamicMap])
    xr = (float(x.min()), float(x.max()))
    yr = (float(y.min()), float(y.max()))

    def _kick_loop() -> None:
        import time as _time

        for _ in range(10):
            _time.sleep(1.0)
            for dm in dmaps:
                for s in dm.streams:
                    try:
                        if isinstance(s, hv.streams.RangeXY):
                            s.event(x_range=xr, y_range=yr)
                        elif isinstance(s, hv.streams.PlotSize):
                            s.event(width=WIDTH, height=HEIGHT)
                        else:
                            s.event()
                    except Exception:  # noqa: BLE001 — best-effort, per stream
                        pass

    import threading

    threading.Thread(target=_kick_loop, daemon=True).start()

    port = free_port()
    # Bokeh's websocket origin allowlist defaults to localhost:<port>, which
    # rejects the same page served as 127.0.0.1:<port> with a 403.
    server = pn.serve(
        app,
        port=port,
        address="127.0.0.1",
        websocket_origin=[f"127.0.0.1:{port}", f"localhost:{port}"],
        show=False,
        threaded=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    print(
        "META "
        + json.dumps(
            {
                "port": port,
                "n": args.n,
                "sentinels": [list(s) for s in SENTINELS],
                "build_ms": build_ms,
                "mode": "datashade+resample",
            }
        ),
        flush=True,
    )
    server.join()


if __name__ == "__main__":
    main()
