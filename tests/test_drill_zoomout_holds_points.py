"""Zoom-out keeps the drilled points until the fresh reply lands (T5/T8).

Zooming out of a drilled window used to exit-fade the exact marks the moment
the view left the window, even though a refresh for the new view was already
in flight — the frame dropped to a coarser cached texture plus the
home/initial overview sample, then transitioned AGAIN when the reply landed
(the zoom-out "flash of the initial view", live-drilldown field report). The
old hold (`lodHoldPendingDrill`) only engaged when the pending view could
still be points-tier (estimated visible within the drill budget), so every
real zoom-out took the double transition.

The hold now engages for any FRESH pending refresh whose view still overlaps
the drill window: the exact marks are the previous zoom level's content, and
they stay painted (over the aggregate backdrop) until the reply retires them
— a density reply marks the drill dying and the exit fade runs over the fresh
texture — or until the T8 age-out releases a stranded pending.

This drives the real client in headless Chromium: it drills into a window,
zooms out far past the drill budget with a fresh pending, and asserts the
marks are still drawn; then it delivers the density reply and asserts the
marks exit; finally it re-creates the held state and strands the pending to
assert the T8 age-out still releases the hold with no reply at all.
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
    // Deterministic virtual clock so fades advance per synthetic frame.
    let clk = 100000;
    view._now = () => clk;
    g._densityNormAnim = null;

    const v0 = view.view0;
    const cx = (v0.x0 + v0.x1) / 2, cy = (v0.y0 + v0.y1) / 2;
    const sx = v0.x1 - v0.x0, sy = v0.y1 - v0.y0;
    // Drill window well inside home; the zoom-out view is 6x linearly (36x by
    // area), and the drill claims a visible count near the budget so the
    // estimated visible for the zoom-out (~180k x 36) is far PAST the budget:
    // the pre-fix hold refused this state and exit-faded the marks.
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const ox0 = cx - sx * 0.3, ox1 = cx + sx * 0.3;
    const oy0 = cy - sy * 0.3, oy1 = cy + sy * 0.3;
    const N = 800;
    const xs = new Float32Array(N), ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
    }
    view._applyDrill(g, {
      id: g.trace.id, mode: "points", visible: 180000, drill_seq: 1,
      x: { buf: 0, offset: 0, scale: 1, len: N },
      y: { buf: 1, offset: 0, scale: 1, len: N },
      x_range: [wx0, wx1], y_range: [wy0, wy1],
    }, [xs.buffer, ys.buffer]);

    // Enter the drill and settle the entry fade so the marks are fully shown.
    view.view = { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    view._drawNow(); clk += 500; view._drawNow();

    const marksDrawn = () => {
      let drawn = false;
      const real = view._drawPoints;
      view._drawPoints = function (d) { if (d === g.drill) drawn = true; return real.apply(this, arguments); };
      view._drawNow();
      view._drawPoints = real;
      return drawn;
    };
    const densityDrawn = () => {
      let drawn = false;
      const real = view._drawDensity;
      view._drawDensity = function (gg) { if (gg === g) drawn = true; return real.apply(this, arguments); };
      view._drawNow();
      view._drawDensity = real;
      return drawn;
    };

    // Zoom OUT far past the drill budget with a fresh pending refresh, as
    // _scheduleViewRequest arms on every view change.
    const outView = { x0: ox0, x1: ox1, y0: oy0, y1: oy1 };
    view.view = { ...outView };
    view._viewAnim = null;
    g._lodPendingView = { ...outView };
    g._lodPendingSeq = view.seq;
    g._lodPendingAt = clk;
    const heldMarks = marksDrawn();
    const heldBackdrop = densityDrawn();
    const notDying = g._drillDying !== true;

    // The reply lands: a density update for the zoomed-out window. The drill
    // dies through its exit fade over the fresh texture and frees.
    const gw = 4, gh = 4;
    const grid = new Float32Array(gw * gh).fill(3);
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 6000000,
        density: {
          buf: 0, w: gw, h: gh, max: 3,
          x_range: [ox0, ox1], y_range: [oy0, oy1],
        },
      }],
    }, [grid.buffer]);
    const dyingAfterReply = g._drillDying === true;
    for (let i = 0; i < 14; i++) { clk += 24; view._drawNow(); }
    clk += 500; view._drawNow();
    const marksClearedAfterReply = !marksDrawn();
    const drillFreed = !g.drill;

    // Re-create the held state and STRAND the pending: the T8 age-out must
    // still release the hold with no reply at all.
    view.view = { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    view._applyDrill(g, {
      id: g.trace.id, mode: "points", visible: 180000, drill_seq: 2,
      x: { buf: 0, offset: 0, scale: 1, len: N },
      y: { buf: 1, offset: 0, scale: 1, len: N },
      x_range: [wx0, wx1], y_range: [wy0, wy1],
    }, [xs.buffer, ys.buffer]);
    view._drawNow(); clk += 500; view._drawNow();
    view.view = { ...outView };
    view._viewAnim = null;
    g._lodPendingView = { ...outView };
    g._lodPendingSeq = view.seq;
    g._lodPendingAt = clk;
    const heldAgain = marksDrawn();
    g._lodPendingAt = clk - 5000;
    for (let i = 0; i < 14; i++) { clk += 24; view._drawNow(); }
    clk += 500; view._drawNow();
    const marksClearedAfterStranded = !marksDrawn();

    document.body.setAttribute("data-xy-drill-hold-probe", JSON.stringify({
      hasDensity: !!g,
      heldMarks, heldBackdrop, notDying,
      dyingAfterReply, marksClearedAfterReply, drillFreed,
      heldAgain, marksClearedAfterStranded,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-drill-hold-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _density_html() -> str:
    rng = np.random.default_rng(0)
    n = 60_000
    x = rng.normal(0.0, 1.0, n)
    y = rng.normal(0.0, 1.0, n)
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


def test_zoomout_holds_drilled_points_until_reply(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "drill_zoomout_hold.html",
        "data-xy-drill-hold-probe",
        label="zoom-out drill-hold probe",
    )

    assert result["hasDensity"] is True
    # Far past the budget with a fresh pending: the marks hold — the pre-fix
    # client exit-faded them here and flashed the overview while loading.
    assert result["heldMarks"] is True
    # The aggregate backdrop stays painted under the held marks (T1/T10).
    assert result["heldBackdrop"] is True
    assert result["notDying"] is True
    # The reply retires the hold through the normal dying exit fade (T2)...
    assert result["dyingAfterReply"] is True
    assert result["marksClearedAfterReply"] is True
    assert result["drillFreed"] is True
    # ...and a stranded pending still ages out with no reply at all (T8).
    assert result["heldAgain"] is True
    assert result["marksClearedAfterStranded"] is True
