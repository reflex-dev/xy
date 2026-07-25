"""A held drill must not freeze when its refinement never arrives (§16, T7).

The deep-zoom drill ships exact points for a zoomed-in window as a sibling of
the density trace. While a refinement request is in flight the tier "holds" the
marks (draws them over the aggregate) so a zoom does not flash — stale-while-
revalidate. The hold is meant to be transient: it ends when the reply lands and
marks the drill dying, after which the exit fade restores the aggregate.

The bug: the held branch only re-scheduled a frame while the *view was
animating*. On a settled view whose pending reply is dropped, coalesced away, or
never sent (all possible on the live-drilldown transport), nothing drove another
frame — so the held marks stayed painted on screen indefinitely and the full
point cloud never came back (the zoom-out "stuck point blob").

The fix keeps a frame scheduled while a hold is live, so the hold re-evaluates
each tick; once its pending ages past the hold window the exit fade takes over
and the aggregate returns — no kernel round-trip required.

This drives the real client in headless Chromium, forces a held state with a
stranded pending, and asserts (a) a redraw stays scheduled and (b) once the
pending goes stale the drilled marks stop being drawn.
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
    // Drill window well inside home; a hold view slightly larger but still
    // centred on it, so lodHoldPendingDrill's center-inside + budget checks pass.
    const wx0 = cx - sx * 0.05, wx1 = cx + sx * 0.05;
    const wy0 = cy - sy * 0.05, wy1 = cy + sy * 0.05;
    const hx0 = cx - sx * 0.06, hx1 = cx + sx * 0.06;
    const hy0 = cy - sy * 0.06, hy1 = cy + sy * 0.06;
    const N = 800;
    const xs = new Float32Array(N), ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = wx0 + (wx1 - wx0) * ((i * 0.6180339887) % 1);
      ys[i] = wy0 + (wy1 - wy0) * ((i * 0.3141592653) % 1);
    }
    view._applyDrill(g, {
      id: g.trace.id, mode: "points", visible: 1500, drill_seq: 1,
      x: { buf: 0, offset: 0, scale: 1, len: N },
      y: { buf: 1, offset: 0, scale: 1, len: N },
      x_range: [wx0, wx1], y_range: [wy0, wy1],
    }, [xs.buffer, ys.buffer]);

    // Enter the drill (view inside its window) and settle the entry fade so the
    // marks are fully shown — establishes _drillWasInside for the exit path.
    view.view = { x0: wx0, x1: wx1, y0: wy0, y1: wy1 };
    view._drawNow(); clk += 500; view._drawNow();

    // Zoom out just past the window into a HELD state: not inside, but a live
    // pending refinement whose window still covers the view keeps the marks.
    view.view = { x0: hx0, x1: hx1, y0: hy0, y1: hy1 };
    view._viewAnim = null;
    g._drillDying = false;
    g._lodPendingView = { x0: hx0, x1: hx1, y0: hy0, y1: hy1 };
    g._lodPendingSeq = view.seq;
    g._lodPendingAt = clk;

    // A settled held frame must still schedule a redraw so the hold can't freeze.
    let drawScheduled = 0, heldDrewMarks = false;
    const realDraw = view.draw;
    const realDP = view._drawPoints;
    view.draw = function () { drawScheduled += 1; };
    view._drawPoints = function (d) { if (d === g.drill) heldDrewMarks = true; return realDP.apply(this, arguments); };
    view._drawNow();
    view.draw = realDraw;
    view._drawPoints = realDP;

    // Strand the pending (reply never lands): after the hold window ages out the
    // marks must exit and the aggregate return, driven only by further frames.
    g._lodPendingAt = clk - 5000;
    for (let i = 0; i < 14; i++) { clk += 24; view._drawNow(); }
    clk += 500;
    let marksStillDrawn = false;
    const realDP2 = view._drawPoints;
    view._drawPoints = function (d) { if (d === g.drill) marksStillDrawn = true; return realDP2.apply(this, arguments); };
    view._drawNow();
    view._drawPoints = realDP2;

    document.body.setAttribute("data-xy-drill-probe", JSON.stringify({
      hasDensity: !!g,
      heldDrewMarks,
      heldScheduledRedraw: drawScheduled > 0,
      marksClearedAfterStranded: !marksStillDrawn,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-drill-probe-error",
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
    # regardless of point count, so the export exercises the drill lifecycle
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


def test_held_drill_does_not_freeze_on_stranded_reply(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "drill_hold_stranded.html",
        "data-xy-drill-probe",
        label="held-drill stranded-reply probe",
    )

    assert result["hasDensity"] is True
    # We are genuinely in the held branch (marks drawn over the aggregate).
    assert result["heldDrewMarks"] is True
    # The held frame keeps a redraw scheduled, so a stranded reply can't freeze
    # it — this is the regression: without the fix nothing re-armed on a settled
    # view and the marks stuck on screen forever.
    assert result["heldScheduledRedraw"] is True
    # Once the pending ages out with no reply, the marks exit and the aggregate
    # (full point cloud) returns.
    assert result["marksClearedAfterStranded"] is True
