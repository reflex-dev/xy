"""Zooming inside an exact drill window must not re-request points (T12).

Once a drill reply has shipped its window EXACTLY (`reduction: "none"` — the
subset IS every point in the window), any view contained in that window is
already answered by the marks on the GPU: the smaller window's points are a
subset of the shipped ones. Drilling deeper must therefore elide the
`density_view` round-trip entirely (LOD doc §5 T12) — no pending markers, no
wire message — while still bumping `seq` so an in-flight reply for an older,
wider view dies stale instead of yanking exact marks out from under the view.

The elision has exactly three re-arm conditions, each asserted here:
- the view leaves the drill window (any edge);
- the zoom outgrows the §16 f32 offset encoding — view span below 1/256 of
  the window span re-requests purely to re-center the encoding;
- the drill stops being an exact live subset (dying, or a reply that did not
  claim `reduction: "none"`).

This drives the real client in headless Chromium with a captured comm, applies
a drill for a known window, and inspects exactly which view requests reach the
wire.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    view._sampleRebinDisabled = true;
    const g = view.gpuTraces.find((t) => t.tier === "density");

    const v0 = view.view0;
    const cx = (v0.x0 + v0.x1) / 2, cy = (v0.y0 + v0.y1) / 2;
    const sx = v0.x1 - v0.x0, sy = v0.y1 - v0.y0;
    // Drill window: the central 10% of home, shipped exactly.
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const N = 800;
    const xs = new Float32Array(N), ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
    }
    view._applyDrill(g, {
      id: g.trace.id, mode: "points", visible: N, reduction: "none", drill_seq: 1,
      x: { buf: 0, offset: 0, scale: 1, len: N },
      y: { buf: 1, offset: 0, scale: 1, len: N },
      x_range: [wx0, wx1], y_range: [wy0, wy1],
    }, [xs.buffer, ys.buffer]);
    const drillMarkedExact = g.drill.exact === true;

    // Kernel-connected from here on: capture what would go on the wire.
    const sent = [];
    view.comm = { send: (m) => sent.push(m) };
    const densitySent = () => sent.filter((m) => m.type === "density_view").length;
    const request = (x0, x1, y0, y1) => {
      const before = densitySent();
      view._scheduleViewRequest(view._viewFrom({ x0, x1, y0, y1 }), { delay: 0 });
      return densitySent() - before;
    };

    // 1) Zooming IN inside the exact window: every point of the smaller view
    // is already on the GPU — no request, pending cleared, seq still bumped
    // (a stale in-flight reply must die rather than replace exact marks).
    const seqBefore = view.seq;
    g._lodPendingView = { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    const zoomInElided = request(
      cx - sx * 0.02, cx + sx * 0.02, cy - sy * 0.02, cy + sy * 0.02) === 0;
    const zoomInClearedPending = g._lodPendingView === null;
    const zoomInBumpedSeq = view.seq === seqBefore + 1;

    // 1b) The window itself (containment up to the edge epsilon) also elides.
    const fullWindowElided = request(wx0, wx1, wy0, wy1) === 0;

    // 2) Leaving the window (pan past an edge) re-arms the request.
    const outsideRequested = request(
      wx0 + sx * 0.03, wx1 + sx * 0.03, wy0, wy1) === 1;

    // 3) Deep zoom past the §16 re-encode bound (view span < window/256):
    // the request goes out purely to re-center the f32 offset encoding.
    const deep = (wx1 - wx0) / 1024;
    const deepZoomRequested = request(
      cx - deep / 2, cx + deep / 2, cy - deep / 2, cy + deep / 2) === 1;

    // 4) A dying drill never elides — the kernel chose a different
    // representation and the reply flow owns that transition.
    g._drillDying = true;
    const dyingRequested = request(
      cx - sx * 0.02, cx + sx * 0.02, cy - sy * 0.02, cy + sy * 0.02) === 1;
    g._drillDying = false;

    // 5) A subset that did not claim reduction "none" never arms the elision.
    g.drill.exact = false;
    const nonExactRequested = request(
      cx - sx * 0.02, cx + sx * 0.02, cy - sy * 0.02, cy + sy * 0.02) === 1;

    document.body.setAttribute("data-xy-elide-probe", JSON.stringify({
      hasDensity: !!g,
      drillMarkedExact,
      zoomInElided,
      zoomInClearedPending,
      zoomInBumpedSeq,
      fullWindowElided,
      outsideRequested,
      deepZoomRequested,
      dyingRequested,
      nonExactRequested,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-elide-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _density_html() -> str:
    rng = np.random.default_rng(0)
    n = 60_000
    x = rng.normal(0.0, 1.0, n)
    y = rng.normal(0.0, 1.0, n)
    # density=True forces the density tier (the drill is a sibling of it),
    # regardless of point count, so the export exercises the request path
    # deterministically and cheaply.
    chart = xy.scatter_chart(
        xy.scatter(x, y, density=True),
        xy.x_axis(),
        xy.y_axis(),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_zoom_in_within_exact_drill_sends_no_request(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "drill_zoomin_elide.html",
        "data-xy-elide-probe",
        label="drill zoom-in request-elision probe",
    )

    assert result["hasDensity"] is True
    # The reply's reduction "none" claim is what arms the elision.
    assert result["drillMarkedExact"] is True
    # Zooming in within the exact window: no wire request, no pending marker,
    # but seq still advances so stale in-flight replies are dropped.
    assert result["zoomInElided"] is True
    assert result["zoomInClearedPending"] is True
    assert result["zoomInBumpedSeq"] is True
    assert result["fullWindowElided"] is True
    # Each re-arm condition still requests: leaving the window, outzooming the
    # f32 encoding (§16 re-centering), a dying drill, a non-exact subset.
    assert result["outsideRequested"] is True
    assert result["deepZoomRequested"] is True
    assert result["dyingRequested"] is True
    assert result["nonExactRequested"] is True
