"""The active drag tool must not disable wheel zoom or double-click reset.

Regression for the modebar Box Zoom tool (PR #198's `dragMode !== "pan"` wheel
guard): with the box-zoom tool active, wheel zoom and double-click reset both
went dead after the first box-zoom gesture. Per the pan/zoom design spec §5.5,
`default_drag_action` (and the live modebar tool) selects the *drag* gesture
only — `"zoom"` never touches the wheel or double-click reset. The one
exception is `"none"`, the modebar's escape hatch that releases page scroll
for embedded charts.
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

    const c = view.canvas;
    const rect = c.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]])
    );
    const differs = (a, b) => JSON.stringify(a) !== JSON.stringify(b);
    const home = ranges();

    // Wheel deltas apply a frame later; make frames deterministic.
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames;
        frames = [];
        for (const fn of queued) fn();
      }
    };

    // The reset lands through an animation; the guard under test is whether
    // the dblclick listener invokes it at all, so spy on the entry point.
    let resetCalls = 0;
    const realReset = view._resetView;
    view._resetView = function (...args) { resetCalls++; return realReset.apply(this, args); };

    const wheelAt = () => {
      const e = new WheelEvent("wheel", {
        deltaY: -240, clientX: cx, clientY: cy, bubbles: true, cancelable: true,
      });
      c.dispatchEvent(e);
      return e.defaultPrevented;
    };
    const dblclickAt = () => c.dispatchEvent(new MouseEvent("dblclick", {
      clientX: cx, clientY: cy, bubbles: true, cancelable: true,
    }));

    let probe;
    try {
      // The repro: activate the modebar Box Zoom tool and complete a gesture.
      view._setDragMode("zoom");
      view._zoomToBox(
        [home.x[0] + (home.x[1] - home.x[0]) * 0.25, home.y[0] + (home.y[1] - home.y[0]) * 0.25],
        [home.x[0] + (home.x[1] - home.x[0]) * 0.75, home.y[0] + (home.y[1] - home.y[0]) * 0.75],
        false,
        { source: "box_zoom", phase: "end", interactionId: 1 },
      );
      flush();
      const afterBox = ranges();
      const boxZoomApplied = differs(afterBox, home);

      // Wheel must keep zooming while the box-zoom tool is active.
      const wheelPreventedInZoomMode = wheelAt();
      flush();
      const wheelChangedView = differs(ranges(), afterBox);

      // Double click must keep resetting while the box-zoom tool is active.
      dblclickAt();
      const resetCalledInZoomMode = resetCalls === 1;
      flush();

      // `none` stays the escape hatch: the wheel passes through to the page
      // and double click does nothing.
      view._setDragMode("none");
      const before = ranges();
      const wheelPreventedInNoneMode = wheelAt();
      flush();
      const wheelChangedViewInNoneMode = differs(ranges(), before);
      dblclickAt();
      const resetCalledInNoneMode = resetCalls > 1;

      probe = {
        boxZoomApplied,
        wheelPreventedInZoomMode,
        wheelChangedView,
        resetCalledInZoomMode,
        wheelPreventedInNoneMode,
        wheelChangedViewInNoneMode,
        resetCalledInNoneMode,
      };
    } finally {
      window.requestAnimationFrame = realRaf;
    }

    document.body.setAttribute("data-xy-boxzoom-tool-probe", JSON.stringify(probe));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-boxzoom-tool-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _chart_html() -> str:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 4.0, 9.0, 16.0]),
        xy.x_axis(),
        xy.y_axis(),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_box_zoom_tool_keeps_wheel_zoom_and_double_click_reset(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _chart_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "boxzoom_tool.html",
        "data-xy-boxzoom-tool-probe",
        label="box-zoom tool wheel/reset probe",
    )

    # Precondition: the box-zoom gesture actually moved the view.
    assert result["boxZoomApplied"] is True

    # The reported bug: both must survive the box-zoom tool being active.
    assert result["wheelPreventedInZoomMode"] is True
    assert result["wheelChangedView"] is True
    assert result["resetCalledInZoomMode"] is True

    # The deliberate carve-out from PR #198 stays: `none` releases the wheel
    # to the page and ignores double click.
    assert result["wheelPreventedInNoneMode"] is False
    assert result["wheelChangedViewInNoneMode"] is False
    assert result["resetCalledInNoneMode"] is False
