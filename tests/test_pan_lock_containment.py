"""A pan-locked axis is contained to its home window, not frozen.

Excluding an axis from ``pan_axes`` while zoom can still navigate it must mean
"this axis never shows data outside its home extents" — not "the drag gesture
skips it". Cursor-anchored zoom is a scaling composed with a translation
(dcenter = span * (anchor - 1/2) * (1 - f)), so without a positional clamp a
zoom-in/zoom-out chain at two different cursor positions is an *exact* pan of
the locked axis: the spans cancel and only the translation survives. The fix
is containment in the shared clamp: the locked axis's window may slide inside
its home extents (so a zoomed-in view can still be dragged) but can never
extend past them, on any mutation path.

This drives the real client in headless Chromium with ``pan_axes=("x",)`` —
y is zoom-navigable but pan-locked — and asserts the containment invariant
across the wheel-chain escape, plain drag, and programmatic sets, plus the
dual guarantees: x (pan-free) still escapes home, and a zoomed-in locked axis
still drags.
"""

from __future__ import annotations

from pathlib import Path

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

    const range = (axisId) => [...view._axisRange(axisId)];
    const home = {
      x: [...view._axisRange("x", view.view0)],
      y: [...view._axisRange("y", view.view0)],
    };
    const homeSpan = {
      x: Math.abs(home.x[1] - home.x[0]),
      y: Math.abs(home.y[1] - home.y[0]),
    };
    const tol = (axisId) => homeSpan[axisId] * 1e-9;
    const insideHome = (axisId) => {
      const [lo, hi] = range(axisId);
      const lo0 = Math.min(home[axisId][0], home[axisId][1]) - tol(axisId);
      const hi0 = Math.max(home[axisId][0], home[axisId][1]) + tol(axisId);
      return Math.min(lo, hi) >= lo0 && Math.max(lo, hi) <= hi0;
    };

    const panEnds = [];
    view.root.addEventListener("xy:view_change", (e) => {
      if (e.detail.source === "pan_drag" && e.detail.phase === "end") {
        panEnds.push([...e.detail.axes]);
      }
    });

    // View events dispatch through a rAF coalescer that never fires under
    // --dump-dom virtual time; queue frames deterministically and drain them
    // after each gesture (a frame may queue the next: apply -> emit).
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    window.requestAnimationFrame = (fn) => frames.push(fn);
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames;
        frames = [];
        for (const fn of queued) fn(performance.now());
      }
    };

    // 1) The wheel-chain escape: zoom in anchored high, zoom out anchored low.
    //    The spans cancel exactly; without containment the surviving
    //    translation walks both windows upward past their home extents.
    view._zoomAt(0.5, 0.9, 0.9, false, 0);
    view._zoomAt(2.0, 0.1, 0.1, false, 0);
    const afterChain = { x: range("x"), y: range("y") };
    const chainYContained = insideHome("y");
    const chainXEscaped = !insideHome("x");

    // 2) Programmatic set beyond home on the locked axis slides back inside.
    view._resetView(false);
    const ranges = Object.fromEntries(
      view._axisIds().map((axisId) => [axisId, [...view._axisRange(axisId)]])
    );
    ranges.y = [home.y[0] + homeSpan.y, home.y[1] + homeSpan.y];
    view._setView({ ranges }, { animate: false, source: "programmatic" });
    const programmaticYContained = insideHome("y");

    // 3) Drag while zoomed in: the locked axis must MOVE (containment bounds
    //    the gesture instead of disabling it) yet stay inside home.
    view._resetView(false);
    view._zoomAt(0.25, 0.5, 0.5, false, 0);
    const zoomedY = range("y");
    const rect = view.canvas.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const pointer = (type, x, y) => {
      view.canvas.dispatchEvent(new PointerEvent(type, {
        pointerId: 1,
        clientX: x,
        clientY: y,
        bubbles: true,
        cancelable: true,
        isPrimary: true,
      }));
    };
    pointer("pointerdown", cx, cy);
    pointer("pointermove", cx, cy + 24);
    pointer("pointerup", cx, cy + 24);
    flush();
    const draggedY = range("y");
    const dragMovedLockedAxis =
      Math.abs(draggedY[0] - zoomedY[0]) > tol("y") && insideHome("y");

    // 4) Drag pinned at the edge: a huge drag clamps the locked axis flush
    //    with its home extent instead of sailing past it.
    pointer("pointerdown", cx, cy);
    pointer("pointermove", cx, cy + 5000);
    pointer("pointerup", cx, cy + 5000);
    flush();
    const pinnedY = range("y");
    const dragClampedAtHomeEdge =
      insideHome("y") &&
      Math.min(
        Math.abs(Math.max(pinnedY[0], pinnedY[1]) - Math.max(home.y[0], home.y[1])),
        Math.abs(Math.min(pinnedY[0], pinnedY[1]) - Math.min(home.y[0], home.y[1])),
      ) <= tol("y");

    // 5) The pan-free axis keeps full mobility: drag at home zoom escapes.
    view._resetView(false);
    pointer("pointerdown", cx, cy);
    pointer("pointermove", cx + 120, cy);
    pointer("pointerup", cx + 120, cy);
    flush();
    const freeXEscaped = !insideHome("x");
    const freeYStayedHome =
      Math.abs(range("y")[0] - home.y[0]) <= tol("y") &&
      Math.abs(range("y")[1] - home.y[1]) <= tol("y");

    window.requestAnimationFrame = realRaf;
    document.body.setAttribute("data-xy-containment-probe", JSON.stringify({
      home,
      afterChain,
      chainYContained,
      chainXEscaped,
      programmaticYContained,
      dragMovedLockedAxis,
      dragClampedAtHomeEdge,
      freeXEscaped,
      freeYStayedHome,
      panEndAxes: panEnds,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-containment-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _chart_html() -> str:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 4.0, 9.0, 16.0]),
        xy.x_axis(),
        xy.y_axis(),
        xy.interaction_config(pan_axes=("x",)),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_pan_locked_axis_is_contained_to_home_window(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _chart_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "pan_lock_containment.html",
        "data-xy-containment-probe",
        label="pan-lock containment probe",
    )

    # The escape chain: y (locked) is contained; x (pan-free) genuinely moved
    # past home, proving containment does not over-clamp free axes.
    assert result["chainYContained"] is True
    assert result["chainXEscaped"] is True

    # Programmatic sets ride the same clamp.
    assert result["programmaticYContained"] is True

    # Containment bounds the drag instead of disabling it: zoomed in, the
    # locked axis moves with the drag, stays inside home, and pins flush at
    # the home extent when dragged past it.
    assert result["dragMovedLockedAxis"] is True
    assert result["dragClampedAtHomeEdge"] is True

    # Free-axis behavior is unchanged: x pans past home; y at home zoom
    # cannot move at all (its window exactly fills the envelope).
    assert result["freeXEscaped"] is True
    assert result["freeYStayedHome"] is True

    # The locked axis reports in pan_drag end events when it actually moved.
    assert any("y" in axes for axes in result["panEndAxes"])
