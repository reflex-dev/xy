"""A lost GL context comes back to the user's zoom, not the home view (#156).

Switching browser tabs backgrounds the page and a busy GPU LRU-evicts the
chart's WebGL context; scrolling a many-chart page has the context governor
release it on purpose. Either way ``webglcontextlost`` fires and the retained
spec + payload rebuild the *same* context on restore. The reported bug: after
that round trip every chart snapped back to its home position, discarding the
user's pan/zoom, because the loss handler reset ``this.view`` to ``this.view0``.

The settled view is still valid across the loss (the payload is unchanged), so
the handler must preserve it — an in-flight navigation snaps to its resting
target first, since a mid-flight interpolation frame is not a view the user
settled on. This drives the real client in headless Chromium: it zooms to a
known window, fires a genuine ``webglcontextlost``, and reads the view the
recovery path re-requests back.
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
    const range = (axis, v) => [...view._axisRange(axis, v)];
    const home = { x: range("x", view.view0), y: range("y", view.view0) };

    // Zoom to a specific interior window — the state the user settled on.
    view._setView(
      { ranges: { x: [1.0, 3.0], y: [2.0, 8.0] } },
      { animate: false, source: "programmatic" },
    );
    const zoomed = { x: range("x"), y: range("y") };

    // A real browser eviction / driver reset. preventDefault-based recovery is
    // opted in by the client; the handler runs synchronously off the event.
    const lostEvent = new Event("webglcontextlost", { cancelable: true });
    view.canvas.dispatchEvent(lostEvent);
    const afterLoss = { x: range("x"), y: range("y") };

    // Second scenario: context loss *during* an active domain transition, whose
    // resting target the kernel follow path stores as a FLAT {x0,x1,y0,y1}
    // object with no `ranges` map (54_kernel.ts). The loss handler must read it
    // through `_axisRange` (shape-normalizing) rather than `_copyView` alone, or
    // the flat target degrades to each axis's home range. Re-arm the handler
    // (the synthetic loss left `_glLost` set), stage a flat interior target as
    // the in-flight transition's resting view, and lose the context again.
    view._glLost = false;
    view.canvas.dataset.xyCtx = "live";
    const flatTarget = { x0: 1.5, x1: 2.5, y0: 3.0, y1: 9.0 };
    view._transitionView = { from: { ...view.view }, to: flatTarget };
    const lostEvent2 = new Event("webglcontextlost", { cancelable: true });
    view.canvas.dispatchEvent(lostEvent2);
    const afterFlatLoss = { x: range("x"), y: range("y") };

    document.body.setAttribute("data-xy-ctxloss-probe", JSON.stringify({
      home,
      zoomed,
      afterLoss,
      flatTarget,
      afterFlatLoss,
      glLost: view._glLost === true,
      lossPrevented: lostEvent.defaultPrevented === true,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-ctxloss-probe-error",
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


def test_context_loss_preserves_the_zoomed_view(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _chart_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "context_loss_view.html",
        "data-xy-ctxloss-probe",
        label="context-loss view-preservation probe",
    )

    # The client opts into restoration, and the loss is registered.
    assert result["lossPrevented"] is True
    assert result["glLost"] is True

    # Sanity: the zoom actually moved off home, so a reset-to-home regression is
    # observable rather than trivially satisfied.
    home, zoomed, after = result["home"], result["zoomed"], result["afterLoss"]
    assert zoomed["x"] != pytest.approx(home["x"], rel=1e-6)
    assert zoomed["y"] != pytest.approx(home["y"], rel=1e-6)

    # The fix: the loss handler keeps the settled view (what the recovery path
    # re-requests and redraws), instead of snapping back to view0.
    assert after["x"] == pytest.approx(zoomed["x"], rel=1e-9)
    assert after["y"] == pytest.approx(zoomed["y"], rel=1e-9)
    assert after["x"] != pytest.approx(home["x"], rel=1e-6)

    # Losing the context mid-domain-transition preserves the transition's
    # resting target even when that target is a flat {x0,x1,y0,y1} (the kernel
    # follow shape) — reading it through `_axisRange` keeps the coordinates
    # instead of degrading each axis to its home range.
    flat, after_flat = result["flatTarget"], result["afterFlatLoss"]
    assert after_flat["x"] == pytest.approx([flat["x0"], flat["x1"]], rel=1e-9)
    assert after_flat["y"] == pytest.approx([flat["y0"], flat["y1"]], rel=1e-9)
    assert after_flat["x"] != pytest.approx(home["x"], rel=1e-6)
