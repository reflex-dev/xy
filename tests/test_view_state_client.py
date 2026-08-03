"""Client-side contract of the unified view-state layer (view-state.md §9).

Drives the real render client in headless Chromium via standalone HTML:
state-document round-trip, clamp equivalence between programmatic writes and
gestures, the history stack (coalescing, restore, capacity, linked writes),
rows-selection non-durability, axis-band gesture scoping, the structured
hover payload beside the compatible legacy row, kernel-message application
(state_patch / view_nav / selection_rows), and the custom tooltip mount.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'


def _chart_html(*children, **kwargs) -> str:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 4.0, 9.0, 16.0]),
        *children,
        width=kwargs.pop("width", 480),
        height=kwargs.pop("height", 360),
        **kwargs,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def _run(tmp_path: Path, document: str, attribute: str, label: str) -> dict:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    return run_browser_probe(
        chromium, document, tmp_path / f"{attribute}.html", attribute, label=label
    )


_STATE_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    const handle = view.root.xy;

    // Round-trip: apply(serialize(state)) is a no-op, exact f64 equality.
    view._zoomAt(0.5, 0.3, 0.7, false, 0);
    const zoomed = ranges();
    const snapshot = handle.state();
    handle.applyState(snapshot);
    const afterRoundTrip = ranges();
    const roundTripExact = JSON.stringify(zoomed) === JSON.stringify(afterRoundTrip);
    const snapshotHasVersion = snapshot.v === 1;
    const snapshotSelectionNull = snapshot.selection === null;

    // Patch semantics: an absent axis is left alone; explicit axes apply.
    const beforePartial = ranges();
    handle.applyState({ v: 1, ranges: { x: [1.0, 2.0] } });
    const afterPartial = ranges();
    const partialTouchedX = afterPartial.x[0] === 1.0 && afterPartial.x[1] === 2.0;
    const partialLeftYAlone = JSON.stringify(afterPartial.y) === JSON.stringify(beforePartial.y);

    // Rejections: higher v, unknown axis, unknown key, non-finite — whole
    // document rejected, nothing partially applied.
    const beforeReject = ranges();
    const rejectedVersion = handle.applyState({ v: 2, ranges: { x: [0, 1] } }) === false;
    const rejectedAxis = handle.applyState({ v: 1, ranges: { zz: [0, 1] } }) === false;
    const rejectedKey = handle.applyState({ v: 1, extra: true }) === false;
    const rejectedNaN = handle.applyState({ v: 1, ranges: { x: [0, NaN] } }) === false;
    const nothingApplied = JSON.stringify(ranges()) === JSON.stringify(beforeReject);

    // Clamp equivalence: a programmatic patch obeys the same clamp as a
    // gesture. Default zoom_limits stop zoom-out at the home window, so a
    // wider-than-home patch commits the gesture-reachable home window (to
    // float rounding: the clamp re-derives lo/hi from anchor and span).
    view._resetView(false, "reset");
    const home = ranges();
    handle.applyState({ v: 1, ranges: {
      x: [home.x[0] - 100, home.x[1] + 100],
      y: [home.y[0] - 100, home.y[1] + 100],
    }});
    const near = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
    const clamped = ranges();
    const clampedLikeGesture = view._axisIds().every((id) =>
      near(clamped[id][0], home[id][0]) && near(clamped[id][1], home[id][1]));

    // And a reachable target commits identically via gesture and via patch.
    view._zoomAt(0.5, 0.25, 0.25, false, 0);
    const gestureCommitted = ranges();
    view._resetView(false, "reset");
    handle.applyState({ v: 1, ranges: gestureCommitted });
    const patchMatchesGesture =
      JSON.stringify(ranges()) === JSON.stringify(gestureCommitted);

    document.body.setAttribute("data-xy-state-probe", JSON.stringify({
      roundTripExact, snapshotHasVersion, snapshotSelectionNull,
      partialTouchedX, partialLeftYAlone,
      rejectedVersion, rejectedAxis, rejectedKey, rejectedNaN, nothingApplied,
      clampedLikeGesture, patchMatchesGesture,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-state-probe-error", String((err && err.stack) || err));
  }
"""


def test_state_round_trip_patch_semantics_and_clamps(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _STATE_PROBE),
        "data-xy-state-probe",
        label="view-state round-trip probe",
    )
    assert result == {key: True for key in result}


_LOST_POINTER_CAPTURE_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    const center = (el) => {
      const r = el.getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2];
    };
    const [x, y] = center(view.canvas);

    const realRaf = window.requestAnimationFrame;
    let frames = [];
    let ts = 0;
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 300 && (frames.length || view._viewAnim); round++) {
        const queued = frames; frames = [];
        ts += 100;
        for (const fn of queued) fn(ts);
      }
    };

    const endEvents = [];
    view.root.addEventListener("xy:view_change", (event) => {
      if (event.detail.source === "pan_drag" && event.detail.phase === "end") {
        endEvents.push(event.detail);
      }
    });
    const pointer = (target, type, pointerId, clientX, clientY, buttons) => {
      target.dispatchEvent(new PointerEvent(type, {
        pointerId,
        pointerType: "mouse",
        button: 0,
        buttons,
        clientX,
        clientY,
        bubbles: true,
        cancelable: true,
        isPrimary: true,
      }));
    };

    pointer(view.canvas, "pointerdown", 71, x, y, 1);
    pointer(view.canvas, "pointermove", 71, x + 60, y + 10, 1);
    const atBoundary = ranges();

    // Chrome's iframe sequence when the primary button is released in the
    // parent document: no pointerup in this document, then lost capture and
    // a buttonless pointermove when the cursor re-enters.
    pointer(view.canvas, "lostpointercapture", 71, x + 60, y + 10, 0);
    pointer(view.canvas, "pointermove", 71, x + 120, y + 20, 0);
    flush();
    const canvasReentryDidNotPan =
      JSON.stringify(ranges()) === JSON.stringify(atBoundary);

    // Coordinate-dependent canvas gestures cannot invent an endpoint outside
    // this document, so capture loss cancels their transient overlay/state.
    view._setDragMode("select");
    pointer(view.canvas, "pointerdown", 72, x, y, 1);
    pointer(view.canvas, "pointermove", 72, x + 50, y + 40, 1);
    const selectionWasActive = view.selRect.style.display === "block";
    pointer(view.canvas, "lostpointercapture", 72, x + 50, y + 40, 0);
    const selectionCancelled = view.root.xy.state().selection === null
      && view.selRect.style.display === "none";

    // Editable lasso handles restore the last committed vertex.
    view._sendSelectPolygon([[0, 0], [4, 0], [4, 16], [0, 16]], { history: false });
    const lassoBefore = JSON.stringify(view._lassoPolygon);
    const handle = view.selLassoHandles.children[1];
    const [hx, hy] = center(handle);
    pointer(handle, "pointerdown", 73, hx, hy, 1);
    pointer(view.selLasso, "pointermove", 73, hx + 30, hy + 20, 1);
    const lassoMoved = JSON.stringify(view._lassoPolygon) !== lassoBefore;
    pointer(view.selLasso, "lostpointercapture", 73, hx + 30, hy + 20, 0);
    const lassoRestored = JSON.stringify(view._lassoPolygon) === lassoBefore
      && !handle.hasAttribute("data-xy-active");

    // Axis-band pan owns the same finish-at-last-valid-frame policy.
    view._setDragMode("pan");
    const axisBand = view.root.querySelector('[data-xy-axis-band="x"]');
    const [ax, ay] = center(axisBand);
    pointer(axisBand, "pointerdown", 74, ax, ay, 1);
    pointer(axisBand, "pointermove", 74, ax + 45, ay, 1);
    const axisAtBoundary = ranges();
    pointer(axisBand, "lostpointercapture", 74, ax + 45, ay, 0);
    pointer(axisBand, "pointermove", 74, ax + 90, ay, 0);
    const axisReentryDidNotPan =
      JSON.stringify(ranges()) === JSON.stringify(axisAtBoundary);

    // Chrome owned by the modebar cannot remain in its dragging state either.
    view.root.dispatchEvent(new PointerEvent("pointerenter", { bubbles: true }));
    const modebar = view._modebar;
    const [mx, my] = center(modebar);
    pointer(modebar, "pointerdown", 75, mx, my, 1);
    pointer(modebar, "pointermove", 75, mx + 40, my + 20, 1);
    const modebarAtBoundary = [modebar.style.left, modebar.style.top];
    pointer(modebar, "lostpointercapture", 75, mx + 40, my + 20, 0);
    pointer(modebar, "pointermove", 75, mx + 80, my + 40, 0);
    const modebarReleased = !view._modebarDragging
      && !modebar.classList.contains("xy-dragging")
      && JSON.stringify([modebar.style.left, modebar.style.top])
        === JSON.stringify(modebarAtBoundary);

    flush();
    window.requestAnimationFrame = realRaf;

    document.body.setAttribute("data-xy-lost-capture-probe", JSON.stringify({
      canvasReentryDidNotPan,
      finalEndEmittedForBothPans: endEvents.length === 2,
      finalEndKeptInteraction: endEvents[0]?.interaction_id != null
        && endEvents[0]?.axes?.length > 0
        && endEvents[1]?.interaction_id != null
        && endEvents[1]?.axes?.length > 0,
      selectionWasActive,
      selectionCancelled,
      lassoMoved,
      lassoRestored,
      axisReentryDidNotPan,
      modebarReleased,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-lost-capture-probe-error", String((err && err.stack) || err));
  }
"""


def test_capture_loss_policy_covers_every_capture_owning_gesture(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _LOST_POINTER_CAPTURE_PROBE),
        "data-xy-lost-capture-probe",
        label="shared pointer-capture loss probe",
    )
    assert result == {key: True for key in result}


_HISTORY_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    const handle = view.root.xy;
    const depth = () => view._historyPast.length;

    // Deterministic frames for the whole probe: history restores animate,
    // and headless virtual time would otherwise finish them after the probe
    // has already read its assertions.
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    let ts = 0;
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 300 && (frames.length || view._viewAnim); round++) {
        const queued = frames; frames = [];
        ts += 100;
        for (const fn of queued) fn(ts);
      }
    };

    const home = ranges();
    const zoomTrigger = view.root.querySelector('[data-xy-modebar-menu-trigger]');
    const zoomMenu = view.root.querySelector('[data-xy-modebar-menu]');
    const historyGroup = zoomMenu?.querySelector('[data-xy-modebar-view-history]');
    const backBtn = view.root.querySelector('[data-xy-modebar-history="back"]');
    const fwdBtn = view.root.querySelector('[data-xy-modebar-history="forward"]');
    const buttonsExist = !!backBtn && !!fwdBtn;
    const buttonsGroupedInZoomMenu = !!historyGroup
      && historyGroup.contains(backBtn) && historyGroup.contains(fwdBtn)
      && !view.root.querySelector(':scope > [data-xy-modebar-history]');
    const backDisabledAtStart = !!backBtn && backBtn.disabled === true;

    // N discrete commands -> exactly N entries.
    view._zoomBy(0.5, false);
    view._zoomBy(0.5, false);
    view._zoomBy(2, false);
    flush();
    const threeCommandsThreeEntries = depth() === 3;
    const backEnabledAfterZoom = !!backBtn && backBtn.disabled === false;

    // A multi-delta wheel gesture coalesces by interaction_id into ONE entry.
    view._queueWheelZoom(0.8, 0.4, 0.4);
    flush();
    view._queueWheelZoom(0.8, 0.4, 0.4);
    flush();
    const wheelGestureOneEntry = depth() === 4;

    // Back/Next restore through the zoom menu without closing it.
    const beforeBack = ranges();
    zoomTrigger.click();
    backBtn.click();
    flush();
    const backRestored = JSON.stringify(ranges()) !== JSON.stringify(beforeBack);
    const menuStayedOpenAfterBack = zoomMenu.style.display === "flex"
      && zoomTrigger.getAttribute("aria-expanded") === "true" && !fwdBtn.disabled;
    fwdBtn.click();
    flush();
    const forwardRestored = JSON.stringify(ranges()) === JSON.stringify(beforeBack);
    const menuStayedOpenAfterNext = zoomMenu.style.display === "flex"
      && zoomTrigger.getAttribute("aria-expanded") === "true";

    // Branching from a restored view clears the now-invalid forward stack.
    backBtn.click();
    flush();
    view._zoomBy(0.5, false);
    flush();
    const forwardClearedAfterBranch = view._historyFuture.length === 0 && fwdBtn.disabled;

    // Reset is navigation, not amnesia: reset pushes, back undoes it.
    const preReset = ranges();
    view._resetView(false, "reset");
    flush();
    const resetWentHome = JSON.stringify(ranges()) === JSON.stringify(home);
    handle.back();
    flush();
    const backAfterResetRestores = JSON.stringify(ranges()) === JSON.stringify(preReset);

    // Linked applications push nothing.
    const depthBeforeLinked = depth();
    view._setView({ ranges: { x: [0.5, 1.5] } }, {
      source: "linked", phase: "end", broadcast: false });
    flush();
    const linkedPushedNothing = depth() === depthBeforeLinked;

    // history: false opts out per call.
    const depthBeforeOptOut = depth();
    handle.applyState({ v: 1, ranges: { x: [1.0, 1.8] } }, { history: false });
    flush();
    const optOutPushedNothing = depth() === depthBeforeOptOut;

    // Capacity: entries evict at 64, oldest first.
    for (let i = 0; i < 80; i++) view._zoomBy(i % 2 ? 2 : 0.5, false);
    flush();
    window.requestAnimationFrame = realRaf;
    const capacityHeld = depth() === 64;

    document.body.setAttribute("data-xy-history-probe", JSON.stringify({
      buttonsExist, buttonsGroupedInZoomMenu, backDisabledAtStart, threeCommandsThreeEntries,
      backEnabledAfterZoom, wheelGestureOneEntry, backRestored, forwardRestored,
      menuStayedOpenAfterBack, menuStayedOpenAfterNext, forwardClearedAfterBranch,
      resetWentHome, backAfterResetRestores, linkedPushedNothing,
      optOutPushedNothing, capacityHeld,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-history-probe-error", String((err && err.stack) || err));
  }
"""


def test_history_stack_contract(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _HISTORY_PROBE),
        "data-xy-history-probe",
        label="view-history probe",
    )
    assert result == {key: True for key in result}


_MODEBAR_DRAG_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view.root.dispatchEvent(new PointerEvent("pointerenter", { bubbles: true }));
    const bar = view._modebar;
    const handle = bar.querySelector('[data-xy-modebar-drag-handle]');
    const pan = bar.querySelector('[data-xy-modebar-action="pan"]');
    const sensor = getComputedStyle(bar, "::before");
    const handleStyle = getComputedStyle(handle);
    const barStyle = getComputedStyle(bar);
    const externalAffordance = handle.tagName !== "BUTTON"
      && handleStyle.width === "26px" && handleStyle.height === "28px"
      && sensor.width === "34px" && sensor.height === "40px"
      && handleStyle.backgroundColor === barStyle.backgroundColor;

    handle.style.transition = "none";
    pan.focus();
    const focusedBarRect = bar.getBoundingClientRect();
    const focusedHandleRect = handle.getBoundingClientRect();
    const handleGap = bar.dataset.xyModebarDragPeekSide === "right"
      ? focusedHandleRect.left - focusedBarRect.right
      : focusedBarRect.left - focusedHandleRect.right;
    const fourPixelGap = Math.abs(handleGap - 4) < 0.1;
    pan.blur();

    const startLeft = parseFloat(bar.style.left);
    const rect = bar.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    bar.dispatchEvent(new PointerEvent("pointerdown", {
      pointerId: 91, pointerType: "mouse", button: 0, buttons: 1,
      clientX: x, clientY: y, bubbles: true,
    }));
    bar.dispatchEvent(new PointerEvent("pointermove", {
      pointerId: 91, pointerType: "mouse", button: 0, buttons: 1,
      clientX: x + 4, clientY: y, bubbles: true,
    }));
    const thresholdHeld = Math.abs(parseFloat(bar.style.left) - startLeft) < 0.01;
    bar.dispatchEvent(new PointerEvent("pointermove", {
      pointerId: 91, pointerType: "mouse", button: 0, buttons: 1,
      clientX: x + 40, clientY: y + 20, bubbles: true,
    }));
    bar.dispatchEvent(new PointerEvent("pointerup", {
      pointerId: 91, pointerType: "mouse", button: 0, buttons: 0,
      clientX: x + 40, clientY: y + 20, bubbles: true,
    }));
    const surfaceMoved = parseFloat(bar.style.left) > startLeft + 20
      && !bar.classList.contains("xy-dragging");

    const beforeButtonGesture = parseFloat(bar.style.left);
    pan.dispatchEvent(new PointerEvent("pointerdown", {
      pointerId: 92, pointerType: "mouse", button: 0, buttons: 1,
      clientX: x, clientY: y, bubbles: true,
    }));
    pan.dispatchEvent(new PointerEvent("pointermove", {
      pointerId: 92, pointerType: "mouse", button: 0, buttons: 1,
      clientX: x + 60, clientY: y + 30, bubbles: true,
    }));
    pan.dispatchEvent(new PointerEvent("pointerup", {
      pointerId: 92, pointerType: "mouse", button: 0, buttons: 0,
      clientX: x + 60, clientY: y + 30, bubbles: true,
    }));
    const buttonStayedClickOnly = parseFloat(bar.style.left) === beforeButtonGesture;

    view._clampModebar(0, parseFloat(bar.style.top));
    const flipsRightAtLeftEdge = bar.dataset.xyModebarDragPeekSide === "right";
    view._clampModebar(view.root.clientWidth - bar.offsetWidth, parseFloat(bar.style.top));
    const flipsLeftAtRightEdge = bar.dataset.xyModebarDragPeekSide === "left";

    document.body.setAttribute("data-xy-modebar-drag-probe", JSON.stringify({
      externalAffordance, fourPixelGap, thresholdHeld, surfaceMoved,
      buttonStayedClickOnly, flipsRightAtLeftEdge, flipsLeftAtRightEdge,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-modebar-drag-probe-error", String((err && err.stack) || err));
  }
"""


def test_modebar_surface_drag_and_adaptive_external_handle(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _MODEBAR_DRAG_PROBE),
        "data-xy-modebar-drag-probe",
        label="modebar surface-drag probe",
    )
    assert result == {key: True for key in result}


_HISTORY_OFF_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view._zoomBy(0.5, false);
    document.body.setAttribute("data-xy-history-off-probe", JSON.stringify({
      noButtons: !view.root.querySelector('[data-xy-modebar-history]'),
      noSnapshots: view._historyPast.length === 0,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-history-off-probe-error", String((err && err.stack) || err));
  }
"""


def test_history_switch_disables_buttons_and_snapshots(tmp_path: Path) -> None:
    document = _chart_html(xy.interaction_config(history=False)).replace(
        _RENDER_CALL, _HISTORY_OFF_PROBE
    )
    result = _run(tmp_path, document, "data-xy-history-off-probe", label="history-off probe")
    assert result == {"noButtons": True, "noSnapshots": True}


_LASSO_DOUBLE_CLICK_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const polygon = [[0, 0], [4, 0], [4, 16], [0, 16]];
    view._sendSelectPolygon(polygon);

    // Pan-mode double-click remains a viewport reset and preserves selection.
    view._setDragMode("pan");
    view.canvas.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    const panPreservedSelection = view.root.xy.state().selection?.polygon?.length === 4;

    let clearEvents = 0;
    view.root.addEventListener("xy:select", (event) => {
      if (event.detail?.view?.source === "select_clear") clearEvents += 1;
    });
    view._setDragMode("select-lasso");

    const clickHandle = (handle, pointerId) => {
      const clientX = Number(handle.getAttribute("cx"));
      const clientY = Number(handle.getAttribute("cy"));
      handle.dispatchEvent(new PointerEvent("pointerdown", {
        pointerId, pointerType: "mouse", button: 0, buttons: 1,
        clientX, clientY, bubbles: true,
      }));
      handle.dispatchEvent(new PointerEvent("pointerup", {
        pointerId, pointerType: "mouse", button: 0, buttons: 0,
        clientX, clientY, bubbles: true,
      }));
    };

    const historyBeforeRemoval = view._historyPast.length;
    const removedPoint = [...polygon[1]];
    const removableHandle = view.selLassoHandles.children[1];
    clickHandle(removableHandle, 101);
    const singleClickDidNothing = view.root.xy.state().selection?.polygon?.length === 4
      && view._historyPast.length === historyBeforeRemoval;
    clickHandle(removableHandle, 102);
    const afterRemoval = view.root.xy.state().selection?.polygon;
    const handleRemoved = afterRemoval?.length === 3
      && !afterRemoval.some((point) =>
        point[0] === removedPoint[0] && point[1] === removedPoint[1])
      && view.selLassoHandles.childElementCount === 3;
    const removalRecordedOnce = view._historyPast.length === historyBeforeRemoval + 1;

    // Three vertices are the minimum valid polygon; removing another is a no-op.
    const historyAtMinimum = view._historyPast.length;
    const minimumHandle = view.selLassoHandles.children[0];
    clickHandle(minimumHandle, 103);
    clickHandle(minimumHandle, 104);
    const minimumPreserved = view.root.xy.state().selection?.polygon?.length === 3
      && view._historyPast.length === historyAtMinimum;

    // A click or tiny pointer jitter outside the polygon must not hide it
    // while the client waits to see whether a replacement drag begins.
    const canvasRect = view.canvas.getBoundingClientRect();
    const outsideX = canvasRect.left + 12;
    const outsideY = canvasRect.top + 12;
    view.canvas.dispatchEvent(new PointerEvent("pointerdown", {
      pointerId: 201, pointerType: "mouse", button: 0, buttons: 1,
      clientX: outsideX, clientY: outsideY, bubbles: true,
    }));
    const stayedVisibleOnPointerDown = view.selLasso.style.display === "block"
      && view._lassoPolygon?.length === 3;
    view.canvas.dispatchEvent(new PointerEvent("pointermove", {
      pointerId: 201, pointerType: "mouse", button: 0, buttons: 1,
      clientX: outsideX + 1, clientY: outsideY + 1, bubbles: true,
    }));
    const stayedVisibleThroughJitter = view.selLasso.style.display === "block"
      && view._lassoPolygon?.length === 3;
    view.canvas.dispatchEvent(new PointerEvent("pointerup", {
      pointerId: 201, pointerType: "mouse", button: 0, buttons: 0,
      clientX: outsideX + 1, clientY: outsideY + 1, bubbles: true,
    }));
    const clickPreservedLasso = view.selLasso.style.display === "block"
      && view.root.xy.state().selection?.polygon?.length === 3;

    const historyBeforeClear = view._historyPast.length;
    const realDraw = view.draw;
    let redraws = 0;
    view.draw = () => { redraws += 1; };
    view.canvas.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    view.draw = realDraw;
    const lassoClearEventEmittedOnce = clearEvents === 1;
    const lassoHistoryRecordedOnce = view._historyPast.length === historyBeforeClear + 1;

    const doubleClickClearsRangeMode = (mode, d0, d1) => {
      view._sendSelect(d0, d1, { history: false });
      view._setDragMode(mode);
      const historyBefore = view._historyPast.length;
      const clearEventsBefore = clearEvents;
      // The browser reports a double-click's second press before it emits the
      // later `dblclick` event. That press must clear every range selection
      // without starting a replacement brush.
      view.canvas.dispatchEvent(new PointerEvent("pointerdown", {
        pointerId: 300, pointerType: "mouse", button: 0, buttons: 1,
        detail: 2, clientX: outsideX, clientY: outsideY, bubbles: true,
      }));
      view.canvas.dispatchEvent(new PointerEvent("pointerup", {
        pointerId: 300, pointerType: "mouse", button: 0, buttons: 0,
        detail: 2, clientX: outsideX, clientY: outsideY, bubbles: true,
      }));
      view.canvas.dispatchEvent(new MouseEvent("dblclick", {
        detail: 2, clientX: outsideX, clientY: outsideY, bubbles: true,
      }));
      return view.root.xy.state().selection === null
        && view._historyPast.length === historyBefore + 1
        && clearEvents === clearEventsBefore + 1;
    };
    const boxModeCleared = doubleClickClearsRangeMode("select", [0, 0], [2, 4]);
    const xRangeModeCleared = doubleClickClearsRangeMode(
      "select-x", [0, view.view.y0], [2, view.view.y1]);
    const yRangeModeCleared = doubleClickClearsRangeMode(
      "select-y", [view.view.x0, 0], [view.view.x1, 4]);

    document.body.setAttribute("data-xy-lasso-dblclick-probe", JSON.stringify({
      panPreservedSelection,
      singleClickDidNothing,
      handleRemoved,
      removalRecordedOnce,
      minimumPreserved,
      stayedVisibleOnPointerDown,
      stayedVisibleThroughJitter,
      clickPreservedLasso,
      selectionCleared: view.root.xy.state().selection === null,
      overlayCleared: view._lassoPolygon === null && view.selLasso.style.display === "none",
      masksCleared: view.gpuTraces.every((trace) =>
        !trace.selActive && (!trace.drill || !trace.drill.selActive)),
      brushCleared: view._lastBrush === null,
      clearEventEmittedOnce: lassoClearEventEmittedOnce,
      historyRecordedOnce: lassoHistoryRecordedOnce,
      redrawnOnce: redraws === 1,
      boxModeCleared,
      xRangeModeCleared,
      yRangeModeCleared,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-lasso-dblclick-probe-error", String((err && err.stack) || err));
  }
"""


def test_selection_modes_double_click_clear_selection(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _LASSO_DOUBLE_CLICK_PROBE),
        "data-xy-lasso-dblclick-probe",
        label="lasso double-click clear probe",
    )
    assert result == {key: True for key in result}


_TAILWIND_LASSO_CSS = """
@layer base, components, utilities;
@layer utilities {
  .fill-slate-900 { fill: rgb(15 23 42); }
  .pointer-events-none { pointer-events: none; }
}
"""

_TAILWIND_LASSO_SLOT_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();

    // SVG paint utilities are irrelevant to the existing div band: it keeps
    // the normal selection background/border and structural pointer behavior.
    view._sendSelect([0.5, 1], [3, 12], { mode: "box", history: false });
    const boxStyle = getComputedStyle(view.selRect);
    const boxPaintStayedDefault =
      boxStyle.borderTopStyle === "solid"
      && parseFloat(boxStyle.borderTopWidth) > 0
      && boxStyle.backgroundColor !== "rgba(0, 0, 0, 0)"
      && boxStyle.backgroundColor !== "rgb(15, 23, 42)"
      && boxStyle.borderTopColor !== "rgb(244, 63, 94)";
    const boxContractStayedIntact =
      view.selRect.dataset.xySlot === "selection"
      && view.selRect.classList.contains("fill-slate-900")
      && view.selRect.classList.contains("pointer-events-none")
      && boxStyle.pointerEvents === "none"
      && view.selRect.style.display === "block";

    view._sendSelectPolygon(
      [[1, 2], [3.5, 2], [3.5, 12], [1, 12]],
      { history: false },
    );
    const path = view.selLassoPath;
    const handles = [...view.selLassoHandles.children];
    const geometry = [path, ...handles];
    const pathStyle = getComputedStyle(path);
    const handleStyles = handles.map((handle) => getComputedStyle(handle));
    const slotReachedEveryNode = geometry.every(
      (node) =>
        node.dataset.xySlot === "selection"
        && node.classList.contains("fill-slate-900")
        && node.classList.contains("pointer-events-none"),
    );
    const classPaintedFill =
      pathStyle.fill === "rgb(15, 23, 42)"
      && handleStyles.every((style) => style.fill === "rgb(15, 23, 42)");
    const explicitStylePaintedStroke =
      pathStyle.stroke === "rgb(244, 63, 94)"
      && pathStyle.strokeWidth === "3px"
      && handleStyles.every(
        (style) => style.stroke === "rgb(244, 63, 94)" && style.strokeWidth === "3px",
      );
    const pointerContractStayedIntact =
      pathStyle.pointerEvents === "none"
      && handleStyles.every((style) => style.pointerEvents === "all");

    // A common box-oriented utility (`pointer-events-none`) must not make the
    // editable lasso handles disappear from browser hit testing.
    const firstHandle = handles[0];
    const handleRect = firstHandle.getBoundingClientRect();
    const clientX = handleRect.left + handleRect.width / 2;
    const clientY = handleRect.top + handleRect.height / 2;
    const hit = document.elementFromPoint(clientX, clientY);
    const hitTargetsHandle =
      hit?.closest?.("[data-xy-selection-lasso-handle]") === firstHandle;

    const pointBeforeDrag = [...view._lassoPolygon[0]];
    firstHandle.dispatchEvent(new PointerEvent("pointerdown", {
      pointerId: 411, pointerType: "mouse", button: 0, buttons: 1,
      clientX, clientY, bubbles: true,
    }));
    view.selLasso.dispatchEvent(new PointerEvent("pointermove", {
      pointerId: 411, pointerType: "mouse", button: 0, buttons: 1,
      clientX: clientX + 18, clientY: clientY - 10, bubbles: true,
    }));
    view.selLasso.dispatchEvent(new PointerEvent("pointerup", {
      pointerId: 411, pointerType: "mouse", button: 0, buttons: 0,
      clientX: clientX + 18, clientY: clientY - 10, bubbles: true,
    }));
    const pointAfterDrag = view._lassoPolygon[0];
    const handleDragStillWorks =
      pointAfterDrag[0] !== pointBeforeDrag[0] || pointAfterDrag[1] !== pointBeforeDrag[1];

    document.body.setAttribute("data-xy-tailwind-lasso-slot-probe", JSON.stringify({
      boxPaintStayedDefault,
      boxContractStayedIntact,
      slotReachedEveryNode,
      classPaintedFill,
      explicitStylePaintedStroke,
      pointerContractStayedIntact,
      hitTargetsHandle,
      handleDragStillWorks,
      lassoReplacedBox:
        view.selRect.style.display === "none" && view.selLasso.style.display === "block",
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-tailwind-lasso-slot-probe-error", String((err && err.stack) || err));
  }
"""


def test_tailwind_selection_slot_styles_lasso_without_changing_box_behavior(
    tmp_path: Path,
) -> None:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 4.0, 9.0, 16.0]),
        class_names={"selection": "fill-slate-900 pointer-events-none"},
        styles={"selection": {"stroke": "#f43f5e", "stroke_width": 3}},
        width=480,
        height=360,
    )
    document = chart.to_html(custom_css=_TAILWIND_LASSO_CSS)
    assert _RENDER_CALL in document
    result = _run(
        tmp_path,
        document.replace(_RENDER_CALL, _TAILWIND_LASSO_SLOT_PROBE, 1),
        "data-xy-tailwind-lasso-slot-probe",
        label="Tailwind lasso selection-slot probe",
    )
    assert result == {
        "boxPaintStayedDefault": True,
        "boxContractStayedIntact": True,
        "slotReachedEveryNode": True,
        "classPaintedFill": True,
        "explicitStylePaintedStroke": True,
        "pointerContractStayedIntact": True,
        "hitTargetsHandle": True,
        "handleDragStillWorks": True,
        "lassoReplacedBox": True,
    }


# Box / x-range / y-range brushes persist like the lasso (view-state.md §2): the
# overlay stays drawn and re-projects through the real draw path, the range
# brushes drop their cross-axis borders, and the mode discriminator round-trips
# through durable state.
_SELECTION_PERSIST_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const cs = () => getComputedStyle(view.selRect);
    const w = (v) => parseFloat(v) || 0;

    // Box select stays visible with a full border and no mode in state.
    view._sendSelect([0.5, 1.0], [3.0, 12.0], { mode: "box", history: false });
    const b = cs();
    const boxVisible = view.selRect.style.display === "block"
      && view._boxSelection && view._boxSelection.mode === "box"
      && view.selRect.dataset.xyBand === "select";
    const boxAllBorders = w(b.borderTopWidth) > 0 && w(b.borderBottomWidth) > 0
      && w(b.borderLeftWidth) > 0 && w(b.borderRightWidth) > 0;
    const boxStateNoMode = view.root.xy.state().selection.range.mode === undefined;

    // Re-projects through a view change via the real _drawNow path.
    const leftBefore = view.selRect.style.left;
    view._setView({ ranges: { x: [0, 2] } },
      { animate: false, source: "test", phase: "end", history: false });
    view._drawNow();
    const boxPersistsThroughZoom = view.selRect.style.display === "block"
      && view.selRect.style.left !== leftBefore;

    // x-range: no top/bottom border, spans full plot height, mode round-trips.
    view._sendSelect([0.5, view.view.y0], [2.5, view.view.y1], { mode: "x", history: false });
    const xb = cs();
    const xRangeBand = view.selRect.dataset.xyBand === "select-x";
    const xNoHorizBorder = w(xb.borderTopWidth) === 0 && w(xb.borderBottomWidth) === 0
      && w(xb.borderLeftWidth) > 0 && w(xb.borderRightWidth) > 0;
    const xSpansHeight = Math.abs(w(view.selRect.style.top) - view.plot.y) < 1.5
      && Math.abs(w(view.selRect.style.height) - view.plot.h) < 1.5;
    const xModeInState = view.root.xy.state().selection.range.mode === "x";

    // y-range: no left/right border, spans full plot width.
    view._sendSelect([view.view.x0, 1.0], [view.view.x1, 9.0], { mode: "y", history: false });
    const yb = cs();
    const yRangeBand = view.selRect.dataset.xyBand === "select-y";
    const yNoVertBorder = w(yb.borderLeftWidth) === 0 && w(yb.borderRightWidth) === 0
      && w(yb.borderTopWidth) > 0 && w(yb.borderBottomWidth) > 0;
    const ySpansWidth = Math.abs(w(view.selRect.style.left) - view.plot.x) < 1.5
      && Math.abs(w(view.selRect.style.width) - view.plot.w) < 1.5;
    const yModeInState = view.root.xy.state().selection.range.mode === "y";

    // A lasso replaces the rectangular overlay (mutual exclusion).
    view._sendSelectPolygon([[0, 0], [2, 0], [2, 4], [0, 4]], { history: false });
    const boxClearedByLasso = view._boxSelection === null
      && view.selRect.style.display === "none"
      && view.selLasso.style.display === "block";

    // applyState round-trips an x-range brush back to select-x and clears lasso.
    view.root.xy.applyState({ v: 1,
      selection: { range: { x0: 0.5, x1: 2.5, y0: -1, y1: 5, mode: "x" } } });
    view._drawNow();
    const xModeRestored = view.selRect.dataset.xyBand === "select-x"
      && view._boxSelection && view._boxSelection.mode === "x"
      && view.selLasso.style.display === "none";
    // A bad mode value is rejected by validation.
    const badModeRejected = view.root.xy.applyState({ v: 1,
      selection: { range: { x0: 0, x1: 1, y0: 0, y1: 1, mode: "diagonal" } } }) === false;

    // Clearing hides the overlay.
    view.root.xy.applyState({ v: 1, selection: null });
    const clearedHidesOverlay = view._boxSelection === null
      && view.selRect.style.display === "none";

    document.body.setAttribute("data-xy-selection-persist-probe", JSON.stringify({
      boxVisible, boxAllBorders, boxStateNoMode, boxPersistsThroughZoom,
      xRangeBand, xNoHorizBorder, xSpansHeight, xModeInState,
      yRangeBand, yNoVertBorder, ySpansWidth, yModeInState,
      boxClearedByLasso, xModeRestored, badModeRejected, clearedHidesOverlay,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-selection-persist-probe-error", String((err && err.stack) || err));
  }
"""


def test_rectangular_selection_persists_with_range_borders(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _SELECTION_PERSIST_PROBE),
        "data-xy-selection-persist-probe",
        label="rectangular selection persistence probe",
    )
    assert result == {key: True for key in result}


def _linked_chart_html() -> str:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 4.0, 9.0, 16.0]),
        width=480,
        height=360,
    )
    fig = chart.figure()
    fig.set_interaction(link_group="probe-group", link_select=True)
    html = fig.to_html()
    assert _RENDER_CALL in html
    return html


# A selection arriving from a link-group peer must hydrate the SAME persisted
# overlay state a local gesture would, so _drawNow re-projects it — box/x/y
# range bands and lasso alike, with the other overlay cleared (Greptile P1 on
# the box-persistence PR: linked range selections left _boxSelection unset).
_LINKED_SELECTION_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const w = (v) => parseFloat(v) || 0;
    const cs = () => getComputedStyle(view.selRect);
    // Drive the real BroadcastChannel handler synchronously with the exact
    // message shape _broadcastLinkedSelection sends (source != our own).
    const link = (selection) => {
      view._linkChannel.onmessage({ data: { source: "peer", selection } });
      view._drawNow();
    };
    const hasChannel = !!view._linkChannel;

    // Linked x-range -> persisted box overlay on this peer: select-x band,
    // no top/bottom border, mode round-tripped into durable state.
    link({ range: { x0: 0.5, x1: 2.5, y0: -1, y1: 5, mode: "x" } });
    const xb = cs();
    const linkedXRange = view.selRect.style.display === "block"
      && view.selRect.dataset.xyBand === "select-x"
      && w(xb.borderTopWidth) === 0 && w(xb.borderBottomWidth) === 0
      && w(xb.borderLeftWidth) > 0 && w(xb.borderRightWidth) > 0
      && view._boxSelection && view._boxSelection.mode === "x"
      && view.root.xy.state().selection.range.mode === "x";

    // Linked polygon -> lasso shown, rectangular overlay cleared.
    link({ polygon: [[0, 0], [2, 0], [2, 4], [0, 4]] });
    const linkedPolygon = view.selLasso.style.display === "block"
      && !!view.selLassoPath.getAttribute("d")
      && view._boxSelection === null
      && view.selRect.style.display === "none";

    // Linked plain box -> box band, no mode, lasso overlay cleared.
    link({ range: { x0: -1, x1: 1, y0: -1, y1: 1 } });
    const linkedBox = view.selRect.style.display === "block"
      && view.selRect.dataset.xyBand === "select"
      && view._lassoPolygon === null
      && view.root.xy.state().selection.range.mode === undefined;

    // Linked clear -> both overlays and durable selection gone.
    link({ clear: true });
    const linkedClear = view._boxSelection === null && view._lassoPolygon === null
      && view.selRect.style.display === "none" && view.selLasso.style.display === "none"
      && view.root.xy.state().selection === null;

    document.body.setAttribute("data-xy-linked-selection-probe", JSON.stringify({
      hasChannel, linkedXRange, linkedPolygon, linkedBox, linkedClear,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-linked-selection-probe-error", String((err && err.stack) || err));
  }
"""


def test_linked_selection_hydrates_persisted_overlay(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _linked_chart_html().replace(_RENDER_CALL, _LINKED_SELECTION_PROBE),
        "data-xy-linked-selection-probe",
        label="linked selection overlay probe",
    )
    assert result == {key: True for key in result}


_REPUBLISH_STATE_PROBE = """
  const host = document.getElementById("chart");
  let view = xy.renderStandalone(host, spec, buf);
  try {
    const hydrateSelectionForRepublish = (target, selection) => {
      const applied = target._applyStatePatch(
        { v: 1, selection },
        {
          source: "republish",
          history: false,
          dispatch: false,
          broadcast: false,
        },
      );
      const localMaskApplied = applied === true
        && target._restoreSelectionLocalMask(selection, { localMask: true });
      return applied === true && localMaskApplied === true;
    };
    const selectableTrace = (target) => target.gpuTraces.find(
      (trace) => trace.trace.kind === "scatter"
        && trace.tier !== "density"
        && !trace._legendHidden
        && trace._cpu
        && trace.n > 0,
    );
    const backendIneligibleTraces = (target) => target.gpuTraces.filter(
      (trace) => trace.trace.kind !== "scatter"
        || trace.tier === "density"
        || trace._legendHidden,
    );
    const selectionMask = (target, trace = selectableTrace(target)) => {
      if (!trace?.selBuf) return [];
      const mask = new Float32Array(trace.n);
      target.gl.bindBuffer(target.gl.ARRAY_BUFFER, trace.selBuf);
      target.gl.getBufferSubData(target.gl.ARRAY_BUFFER, 0, mask);
      return [...mask];
    };
    const hasImmediateSelectionMask = (target) => {
      const trace = selectableTrace(target);
      const mask = selectionMask(target, trace);
      const backendIneligible = backendIneligibleTraces(target);
      return Boolean(
        trace
        && trace.selActive === true
        && trace.selBuf
        && target._selectionCount > 0
        && mask.some((selected) => selected === 1)
        // Lines and aggregate density are absent from backend geometric
        // selection replies, so provisional hydration must never mask them.
        && backendIneligible.length === 2
        && backendIneligible.every((candidate) => !candidate.selActive && !candidate.selBuf),
      );
    };

    view._drawNow();
    // Navigate only the secondary axis. The primary x/y aliases remain at
    // home, which is the case the old four-field wrapper check missed.
    view._setView(
      { ranges: { y2: [104, 112] } },
      { animate: false, source: "test", phase: "end", history: false },
    );
    view._sendSelect(
      [0.5, view.view.y0],
      [2.5, view.view.y1],
      { mode: "x", history: false },
    );
    const rangeState = view.root.xy.state();

    // Exercise the wrapper's unchanged-chrome updatePayload path: rebuilding
    // the traces drops their mask buffers, so silent hydration must restore a
    // provisional GPU mask immediately, before the backend can reply.
    let semanticEvents = 0;
    let broadcasts = 0;
    let commSends = 0;
    view.comm = { send: () => { commSends += 1; } };
    view.root.addEventListener("xy:brush", () => { semanticEvents += 1; });
    view.root.addEventListener("xy:select", () => { semanticEvents += 1; });
    view._broadcastLinkedSelection = () => { broadcasts += 1; };
    const updatedInPlace = view.updatePayload(spec, view._payload);
    view._transitionView = null;
    view._setView(
      { ranges: rangeState.ranges },
      { animate: false, source: "republish", phase: "end", history: false },
    );
    const inPlaceApplied = hydrateSelectionForRepublish(view, rangeState.selection);
    view._drawNow();
    const inPlaceMaskBeforeGlLoss = selectionMask(view);
    const priorGlLoss = view._glLost;
    view._glLost = true;
    const glLossHydrationGuarded =
      view._restoreSelectionLocalMask(
        rangeState.selection,
        { localMask: true },
      ) === false;
    view._glLost = priorGlLoss;
    const inPlaceRangeAndGlLossGuarded =
      updatedInPlace
      && inPlaceApplied
      && view.root.xy.state().selection?.range?.mode === "x"
      && view._boxSelection?.mode === "x"
      && hasImmediateSelectionMask(view)
      && glLossHydrationGuarded
      && JSON.stringify(selectionMask(view)) === JSON.stringify(inPlaceMaskBeforeGlLoss);
    const inPlaceRestoreStayedSilent =
      semanticEvents === 0
      && broadcasts === 0
      && commSends === 0
      && view._historyPast.length === 0;

    view.destroy();
    host.replaceChildren();
    const rangeSpec = {
      ...spec,
      title: "Republished range",
      dom: {
        ...(spec.dom || {}),
        class_name: "republished-tailwind-range",
      },
    };
    view = xy.renderStandalone(host, rangeSpec, buf);
    semanticEvents = 0;
    broadcasts = 0;
    commSends = 0;
    view.comm = { send: () => { commSends += 1; } };
    view.root.addEventListener("xy:brush", () => { semanticEvents += 1; });
    view.root.addEventListener("xy:select", () => { semanticEvents += 1; });
    view._broadcastLinkedSelection = () => { broadcasts += 1; };
    view._setView(
      { ranges: rangeState.ranges },
      { animate: false, source: "republish", phase: "end", history: false },
    );
    const rangeApplied = hydrateSelectionForRepublish(view, rangeState.selection);
    view._drawNow();
    const rangeHydrated =
      rangeApplied
      && view.root.xy.state().selection?.range?.mode === "x"
      && view._boxSelection?.mode === "x"
      && view.selRect.style.display === "block"
      && view.selRect.dataset.xyBand === "select-x"
      && hasImmediateSelectionMask(view);
    const secondaryAxisHydrated =
      JSON.stringify(view.root.xy.state().ranges.y2)
      === JSON.stringify(rangeState.ranges.y2);
    const rangeChromeChanged =
      view.root.classList.contains("republished-tailwind-range")
      && view.root.querySelector('[data-xy-slot="title"]')?.textContent
        === "Republished range";
    const rangeRestoreStayedSilent =
      semanticEvents === 0
      && broadcasts === 0
      && commSends === 0
      && view._historyPast.length === 0;

    // Repeat with lasso geometry: the replacement must own a real polygon
    // overlay and durable state immediately, before any asynchronous mask
    // response can arrive.
    view._sendSelectPolygon(
      [[0.5, 1], [2.5, 1], [2.5, 9], [0.5, 9]],
      { history: false },
    );
    const polygonState = view.root.xy.state();
    view.destroy();
    host.replaceChildren();
    const polygonSpec = {
      ...spec,
      title: "Republished polygon",
      dom: {
        ...(spec.dom || {}),
        class_name: "republished-tailwind-polygon",
      },
    };
    view = xy.renderStandalone(host, polygonSpec, buf);
    semanticEvents = 0;
    broadcasts = 0;
    commSends = 0;
    view.comm = { send: () => { commSends += 1; } };
    view.root.addEventListener("xy:brush", () => { semanticEvents += 1; });
    view.root.addEventListener("xy:select", () => { semanticEvents += 1; });
    view._broadcastLinkedSelection = () => { broadcasts += 1; };
    const polygonApplied = hydrateSelectionForRepublish(view, polygonState.selection);
    view._drawNow();
    const polygonHydrated =
      polygonApplied
      && view.root.xy.state().selection?.polygon?.length === 4
      && view._lassoPolygon?.length === 4
      && view.selLasso.style.display === "block"
      && !!view.selLassoPath.getAttribute("d")
      && view.selRect.style.display === "none"
      && hasImmediateSelectionMask(view);
    const polygonChromeChanged =
      view.root.classList.contains("republished-tailwind-polygon")
      && view.root.querySelector('[data-xy-slot="title"]')?.textContent
        === "Republished polygon";
    const polygonHydrationStayedSilent =
      semanticEvents === 0
      && broadcasts === 0
      && commSends === 0
      && view._historyPast.length === 0;

    // The tagged authoritative reply replaces, rather than combines with,
    // the provisional mask and remains silent. An ordinary reply still emits
    // the public semantic event.
    const polygonTrace = selectableTrace(view);
    const provisionalMask = selectionMask(view, polygonTrace);
    const authoritativeIndices = new Uint32Array([0]);
    view._onKernelMsg(
      {
        type: "selection",
        traces: [{ id: polygonTrace.trace.id, count: 1, buf: 0 }],
        total: 1,
        suppress_event: true,
      },
      [authoritativeIndices.buffer],
    );
    const authoritativeMask = selectionMask(view, polygonTrace);
    const authoritativeReplyOverwroteSilently =
      semanticEvents === 0
      && provisionalMask[0] === 0
      && authoritativeMask[0] === 1
      && authoritativeMask.slice(1).every((selected) => selected === 0)
      && JSON.stringify(authoritativeMask) !== JSON.stringify(provisionalMask)
      && backendIneligibleTraces(view).every(
        (candidate) => !candidate.selActive && !candidate.selBuf,
      );
    view._onKernelMsg({ type: "selection", traces: [], total: 0 }, []);
    const polygonRestoreAndRepliesCorrect =
      polygonHydrationStayedSilent
      && authoritativeReplyOverwroteSilently
      && semanticEvents === 1;

    document.body.setAttribute("data-xy-republish-state-probe", JSON.stringify({
      inPlaceRangeAndGlLossGuarded,
      inPlaceRestoreStayedSilent,
      rangeHydrated,
      secondaryAxisHydrated,
      rangeChromeChanged,
      rangeRestoreStayedSilent,
      polygonHydrated,
      polygonChromeChanged,
      polygonRestoreAndRepliesCorrect,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-republish-state-probe-error", String((err && err.stack) || err));
  }
"""


def test_republish_hydrates_all_axis_ranges_and_selection_without_echo(
    tmp_path: Path,
) -> None:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 4.0, 9.0]),
        xy.scatter([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 4.0, 9.0], density=True),
        xy.line([0.0, 1.0, 2.0, 3.0], [100.0, 106.0, 114.0, 120.0], y_axis="y2"),
        xy.y_axis(id="y2", side="right"),
        width=480,
        height=360,
    )
    document = chart.to_html()
    assert _RENDER_CALL in document
    result = _run(
        tmp_path,
        document.replace(_RENDER_CALL, _REPUBLISH_STATE_PROBE, 1),
        "data-xy-republish-state-probe",
        label="republish durable-state hydration probe",
    )
    assert result == {
        "inPlaceRangeAndGlLossGuarded": True,
        "inPlaceRestoreStayedSilent": True,
        "rangeHydrated": True,
        "secondaryAxisHydrated": True,
        "rangeChromeChanged": True,
        "rangeRestoreStayedSilent": True,
        "polygonHydrated": True,
        "polygonChromeChanged": True,
        "polygonRestoreAndRepliesCorrect": True,
    }


_ROWS_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    const handle = view.root.xy;
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    let ts = 0;
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 300 && (frames.length || view._viewAnim); round++) {
        const queued = frames; frames = [];
        ts += 100;
        for (const fn of queued) fn(ts);
      }
    };

    // Geometric select (durable) then zoom: two history entries.
    handle.applyState({ v: 1, selection: { range: { x0: 1, x1: 3, y0: 0, y1: 9 } } });
    view._zoomBy(0.5, false);
    flush();
    const depthBeforeRows = view._historyPast.length;
    const preRowsRanges = ranges();

    // A pushed rows-selection: non-durable, never enters the stack, reported
    // only as the opaque marker.
    const idx = new Uint32Array([0, 2]);
    view._onKernelMsg(
      { type: "selection_rows", traces: [{ id: 0, count: 2, buf: 0 }], total: 2 },
      [idx.buffer],
    );
    const stateAfterRows = handle.state();
    const rowsMarker = JSON.stringify(stateAfterRows.selection) === JSON.stringify({ rows: true });
    const rowsPushedNothing = view._historyPast.length === depthBeforeRows;
    const rowsCounted = view._selectionCount === 2;

    // Back after a rows-select restores the prior *geometric* state.
    handle.back();
    flush();
    window.requestAnimationFrame = realRaf;
    const backRestoredRanges = JSON.stringify(ranges()) !== JSON.stringify(preRowsRanges);
    const backSelection = handle.state().selection;
    const backSelectionGeometric = !!(backSelection && backSelection.range);

    document.body.setAttribute("data-xy-rows-probe", JSON.stringify({
      rowsMarker, rowsPushedNothing, rowsCounted,
      backRestoredRanges, backSelectionGeometric,
      hadTwoEntries: depthBeforeRows === 2,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-rows-probe-error", String((err && err.stack) || err));
  }
"""


def test_rows_selection_is_non_durable(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _ROWS_PROBE),
        "data-xy-rows-probe",
        label="rows-selection probe",
    )
    assert result == {key: True for key in result}


_ROWS_CLEAR_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const activeById = (id) => {
      const g = view.gpuTraces.find((t) => t.trace.id === id);
      return !!(g && g.selActive);
    };

    // Rows on both traces, then a document naming only trace 0: a rows
    // document replaces the whole selection, so the omitted trace's mask
    // must deactivate instead of staying highlighted (wire-protocol.md
    // `selection_rows`).
    view._onKernelMsg(
      { type: "selection_rows", total: 3, traces: [
        { id: 0, count: 2, buf: 0 }, { id: 1, count: 1, buf: 1 },
      ] },
      [new Uint32Array([0, 2]).buffer, new Uint32Array([1]).buffer],
    );
    const bothActive = activeById(0) && activeById(1);

    view._onKernelMsg(
      { type: "selection_rows", total: 1, traces: [{ id: 0, count: 1, buf: 0 }] },
      [new Uint32Array([4]).buffer],
    );
    const trace0Active = activeById(0);
    const trace1Cleared = !activeById(1);
    const countMatches = view._selectionCount === 1;

    document.body.setAttribute("data-xy-rows-clear-probe", JSON.stringify({
      bothActive, trace0Active, trace1Cleared, countMatches,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-rows-clear-probe-error", String((err && err.stack) || err));
  }
"""


def test_rows_selection_clears_omitted_traces(tmp_path: Path) -> None:
    document = _chart_html(
        xy.scatter([0.0, 1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 5.0, 7.0, 9.0]),
    ).replace(_RENDER_CALL, _ROWS_CLEAR_PROBE)
    result = _run(tmp_path, document, "data-xy-rows-clear-probe", label="rows-clear probe")
    assert result == {key: True for key in result}


_RETARGET_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    const handle = view.root.xy;
    const events = [];
    view.root.addEventListener("xy:view_change", (e) => events.push({
      source: e.detail.source,
      phase: e.detail.phase,
      interaction_id: e.detail.interaction_id,
    }));
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    let ts = 0;
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 300 && (frames.length || view._viewAnim); round++) {
        const queued = frames; frames = [];
        ts += 100;
        for (const fn of queued) fn(ts);
      }
    };

    // Two rapid animated writes: the second lands mid-flight and retargets.
    // One history entry (the pre-first state), the view settles at the
    // second target, and the settle event describes the second write
    // (view-state.md §4: coalesce into the in-flight navigation).
    const home = ranges();
    handle.applyState({ v: 1, ranges: { x: [1.0, 3.0] } }, { animate: true });
    const idFirst = view._interactionSeq;
    const midFlight = view._viewAnim !== null;
    handle.applyState({ v: 1, ranges: { x: [2.0, 4.0] } }, { animate: true });
    const idSecond = view._interactionSeq;
    flush();
    window.requestAnimationFrame = realRaf;

    const oneEntry = view._historyPast.length === 1;
    const entryIsHome = JSON.stringify(view._historyPast[0]?.ranges.x)
      === JSON.stringify(home.x);
    const settledAtSecondTarget =
      Math.abs(ranges().x[0] - 2.0) < 1e-9 && Math.abs(ranges().x[1] - 4.0) < 1e-9;
    const settle = events[events.length - 1];
    const settleIsEnd = !!settle && settle.phase === "end";
    const settleSourceApi = !!settle && settle.source === "api";
    const settleHasSecondId = !!settle && settle.interaction_id === idSecond
      && idSecond !== idFirst;

    document.body.setAttribute("data-xy-retarget-probe", JSON.stringify({
      midFlight, oneEntry, entryIsHome, settledAtSecondTarget,
      settleIsEnd, settleSourceApi, settleHasSecondId,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-retarget-probe-error", String((err && err.stack) || err));
  }
"""


def test_retargeted_animation_coalesces_history_and_metadata(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _RETARGET_PROBE),
        "data-xy-retarget-probe",
        label="retarget probe",
    )
    assert result == {key: True for key in result}


_KERNEL_MSG_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));

    // Capture emitted view events (deterministic frames).
    const events = [];
    view.root.addEventListener("xy:view_change", (e) => {
      events.push({ source: e.detail.source, ranges: e.detail.ranges });
    });
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames; frames = [];
        for (const fn of queued) fn();
      }
    };

    const home = ranges();
    view._onKernelMsg({
      type: "state_patch",
      state: { v: 1, ranges: { x: [1.0, 2.5] } },
      animate: false,
      history: true,
    }, []);
    flush();
    const patchApplied = ranges().x[0] === 1.0 && ranges().x[1] === 2.5;
    // Loop safety: an api-sourced commit reports source "api", so an
    // on_view_change -> set_view bridge can filter its own echo.
    const apiSourced = events.some((e) => e.source === "api");
    const patchPushedHistory = view._historyPast.length === 1;

    view._onKernelMsg({ type: "view_nav", op: "reset", axes: ["x"] }, []);
    // reset navigates animated; run its frames to completion.
    for (let i = 0; i < 200 && (frames.length || view._viewAnim); i++) flush();
    window.requestAnimationFrame = realRaf;
    const resetWentHome = Math.abs(ranges().x[0] - home.x[0]) < 1e-9
      && Math.abs(ranges().x[1] - home.x[1]) < 1e-9;

    document.body.setAttribute("data-xy-kernelmsg-probe", JSON.stringify({
      patchApplied, apiSourced, patchPushedHistory, resetWentHome,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-kernelmsg-probe-error", String((err && err.stack) || err));
  }
"""


def test_kernel_messages_apply_through_mutation_path(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _KERNEL_MSG_PROBE),
        "data-xy-kernelmsg-probe",
        label="kernel state-message probe",
    )
    assert result == {key: True for key in result}


_AXIS_BAND_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const ranges = () => Object.fromEntries(
      view._axisIds().map((id) => [id, [...view._axisRange(id)]]));

    const bandX = view.root.querySelector('[data-xy-axis-band="x"]');
    const bandY = view.root.querySelector('[data-xy-axis-band="y"]');
    const bandsExist = !!bandX && !!bandY;
    const cursors = bandsExist
      && getComputedStyle(bandX).cursor === "ew-resize"
      && getComputedStyle(bandY).cursor === "ns-resize";

    const realRaf = window.requestAnimationFrame;
    let frames = [];
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames; frames = [];
        for (const fn of queued) fn();
      }
    };

    // Wheel over the x band zooms only x.
    const before = ranges();
    const rect = bandX.getBoundingClientRect();
    bandX.dispatchEvent(new WheelEvent("wheel", {
      deltaY: -240,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + 2,
      bubbles: true,
      cancelable: true,
    }));
    flush();
    const after = ranges();
    const xZoomed = JSON.stringify(after.x) !== JSON.stringify(before.x);
    const yUntouched = JSON.stringify(after.y) === JSON.stringify(before.y);

    // Drag along the y band pans only y.
    view._resetView(false, "reset");
    const preDrag = ranges();
    const yRect = bandY.getBoundingClientRect();
    const startX = yRect.left + yRect.width / 2;
    const startY = yRect.top + yRect.height / 2;
    const down = new PointerEvent("pointerdown", {
      pointerId: 7, clientX: startX, clientY: startY, bubbles: true, cancelable: true,
    });
    bandY.dispatchEvent(down);
    bandY.dispatchEvent(new PointerEvent("pointermove", {
      pointerId: 7, clientX: startX, clientY: startY + 40, bubbles: true, cancelable: true,
    }));
    bandY.dispatchEvent(new PointerEvent("pointerup", {
      pointerId: 7, clientX: startX, clientY: startY + 40, bubbles: true, cancelable: true,
    }));
    flush();
    window.requestAnimationFrame = realRaf;
    const postDrag = ranges();
    const yPanned = JSON.stringify(postDrag.y) !== JSON.stringify(preDrag.y);
    const xUntouchedByDrag = JSON.stringify(postDrag.x) === JSON.stringify(preDrag.x);

    document.body.setAttribute("data-xy-axisband-probe", JSON.stringify({
      bandsExist, cursors, xZoomed, yUntouched, yPanned, xUntouchedByDrag,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axisband-probe-error", String((err && err.stack) || err));
  }
"""


def test_axis_band_gestures_scope_one_axis(tmp_path: Path) -> None:
    # Pan must escape the home window for the drag assertion, so give y a
    # roomier zoom_limits floor? No: pan at home magnification cannot move a
    # contained axis, but plain pan on a *free* axis can leave home. Default
    # config pans freely, so the drag moves y without any zoom first.
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _AXIS_BAND_PROBE),
        "data-xy-axisband-probe",
        label="axis-band gesture probe",
    )
    assert result == {key: True for key in result}


_AXIS_BAND_POLICY_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    // Config: pan_axes=("x","y"), zoom_axes=("x",). The cursor advertises
    // capability (view-state.md §6): resize only where zoom works; the
    // pan-only y band shows a grab hand, grabbing while a drag is active.
    const bandX = view.root.querySelector('[data-xy-axis-band="x"]');
    const bandY = view.root.querySelector('[data-xy-axis-band="y"]');
    const zoomableShowsResize = !!bandX && getComputedStyle(bandX).cursor === "ew-resize";
    const panOnlyShowsGrab = !!bandY && getComputedStyle(bandY).cursor === "grab";

    let grabbingDuringDrag = false;
    let grabRestoredAfterDrag = false;
    let cursorRestoredWithoutInline = false;
    if (bandY) {
      const yRect = bandY.getBoundingClientRect();
      const sx = yRect.left + yRect.width / 2;
      const sy = yRect.top + yRect.height / 2;
      const opts = (x, y) => (
        { pointerId: 9, clientX: x, clientY: y, bubbles: true, cancelable: true });
      bandY.dispatchEvent(new PointerEvent("pointerdown", opts(sx, sy)));
      bandY.dispatchEvent(new PointerEvent("pointermove", opts(sx, sy + 40)));
      grabbingDuringDrag = getComputedStyle(bandY).cursor === "grabbing";
      bandY.dispatchEvent(new PointerEvent("pointerup", opts(sx, sy + 40)));
      grabRestoredAfterDrag = getComputedStyle(bandY).cursor === "grab";
      cursorRestoredWithoutInline = bandY.style.cursor === "";
    }

    document.body.setAttribute("data-xy-axisband-policy-probe", JSON.stringify({
      zoomableShowsResize, panOnlyShowsGrab,
      grabbingDuringDrag, grabRestoredAfterDrag, cursorRestoredWithoutInline,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axisband-policy-probe-error", String((err && err.stack) || err));
  }
"""


def test_axis_band_respects_axis_policies(tmp_path: Path) -> None:
    document = _chart_html(xy.interaction_config(pan_axes=("x", "y"), zoom_axes=("x",))).replace(
        _RENDER_CALL, _AXIS_BAND_POLICY_PROBE
    )
    result = _run(
        tmp_path, document, "data-xy-axisband-policy-probe", label="axis-band policy probe"
    )
    assert result == {key: True for key in result}


_AXIS_BAND_AUTHORED_CURSOR_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const bandY = view.root.querySelector('[data-xy-axis-band="y"]');
    if (!bandY) throw new Error("missing y axis band");
    const authoredInitially = bandY.style.getPropertyValue("cursor") === "crosshair"
      && getComputedStyle(bandY).cursor === "crosshair";
    const rect = bandY.getBoundingClientRect();
    const sx = rect.left + rect.width / 2;
    const sy = rect.top + rect.height / 2;
    const dispatch = (type, pointerId, y) => bandY.dispatchEvent(new PointerEvent(type, {
      pointerId, clientX: sx, clientY: y, bubbles: true, cancelable: true,
    }));

    dispatch("pointerdown", 21, sy);
    dispatch("pointermove", 21, sy + 40);
    const grabbingDuringCancelledDrag = getComputedStyle(bandY).cursor === "grabbing";
    dispatch("pointercancel", 21, sy + 40);
    const authoredAfterCancel = bandY.style.getPropertyValue("cursor") === "crosshair"
      && getComputedStyle(bandY).cursor === "crosshair";

    dispatch("pointerdown", 22, sy);
    dispatch("pointermove", 22, sy + 40);
    const grabbingDuringCompletedDrag = getComputedStyle(bandY).cursor === "grabbing";
    dispatch("pointerup", 22, sy + 40);
    const authoredAfterPointerUp = bandY.style.getPropertyValue("cursor") === "crosshair"
      && getComputedStyle(bandY).cursor === "crosshair";

    // Overlapping pointers: a second finger lands mid-pan and lifts first.
    // Snapshotting the authored cursor per-gesture captured the controller's
    // own `grabbing` here and replayed it back as author intent, latching the
    // cursor permanently — a later well-formed drag did not heal it either.
    dispatch("pointerdown", 31, sy);
    dispatch("pointermove", 31, sy + 40);
    dispatch("pointerdown", 32, sy);
    dispatch("pointerup", 32, sy + 40);
    dispatch("pointerup", 31, sy + 40);
    const authoredAfterOverlappingPointers =
      bandY.style.getPropertyValue("cursor") === "crosshair"
      && getComputedStyle(bandY).cursor === "crosshair";

    dispatch("pointerdown", 33, sy);
    dispatch("pointermove", 33, sy + 40);
    dispatch("pointerup", 33, sy + 40);
    const authoredAfterRecoveryDrag = bandY.style.getPropertyValue("cursor") === "crosshair"
      && getComputedStyle(bandY).cursor === "crosshair";

    document.body.setAttribute("data-xy-axisband-authored-cursor-probe", JSON.stringify({
      authoredInitially,
      grabbingDuringCancelledDrag,
      authoredAfterCancel,
      grabbingDuringCompletedDrag,
      authoredAfterPointerUp,
      authoredAfterOverlappingPointers,
      authoredAfterRecoveryDrag,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axisband-authored-cursor-probe-error", String((err && err.stack) || err));
  }
"""


def test_axis_band_restores_authored_cursor_after_drag(tmp_path: Path) -> None:
    document = _chart_html(
        xy.interaction_config(pan_axes=("x", "y"), zoom_axes=("x",)),
        styles={"axis_band": {"cursor": "crosshair"}},
    ).replace(_RENDER_CALL, _AXIS_BAND_AUTHORED_CURSOR_PROBE)
    result = _run(
        tmp_path,
        document,
        "data-xy-axisband-authored-cursor-probe",
        label="axis-band authored cursor restore probe",
    )
    assert result == {
        "authoredInitially": True,
        "grabbingDuringCancelledDrag": True,
        "authoredAfterCancel": True,
        "grabbingDuringCompletedDrag": True,
        "authoredAfterPointerUp": True,
        "authoredAfterOverlappingPointers": True,
        "authoredAfterRecoveryDrag": True,
    }


_AXIS_BAND_EXCLUDED_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    document.body.setAttribute("data-xy-axisband-excluded-probe", JSON.stringify({
      // y is outside both pan_axes and zoom_axes -> no band at all.
      noBandForExcludedAxis: !view.root.querySelector('[data-xy-axis-band="y"]'),
      bandForNavigableAxis: !!view.root.querySelector('[data-xy-axis-band="x"]'),
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axisband-excluded-probe-error", String((err && err.stack) || err));
  }
"""


def test_axis_band_absent_for_excluded_axis(tmp_path: Path) -> None:
    document = _chart_html(xy.interaction_config(pan_axes=("x",), zoom_axes=("x",))).replace(
        _RENDER_CALL, _AXIS_BAND_EXCLUDED_PROBE
    )
    result = _run(
        tmp_path, document, "data-xy-axisband-excluded-probe", label="axis-band excluded probe"
    )
    assert result == {"noBandForExcludedAxis": True, "bandForNavigableAxis": True}


_HOVER_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    let hoverDetail = null;
    let leaveDetail = null;
    view.root.addEventListener("xy:hover", (e) => { hoverDetail = e.detail; });
    view.root.addEventListener("xy:leave", (e) => { leaveDetail = e.detail; });

    // Keyboard traversal drives the same _showTooltip path as pointer hover,
    // deterministically (no headless pointer-position flakiness).
    view.canvas.dispatchEvent(new KeyboardEvent("keydown", {
      key: "ArrowRight", bubbles: true, cancelable: true,
    }));
    const d = hoverDetail || {};
    const row = d.row || {};
    // Legacy compatibility: handlers reading row["x"] keep working.
    const rowSubscriptable = Number.isFinite(Number(row.x)) && Number.isFinite(Number(row.y));
    const legacyKeys = "trace" in d && "index" in d && !!d.view;
    const payloadActive = d.active === true;
    const cursorPx = Array.isArray(d.cursor && d.cursor.px) && d.cursor.px.length === 2
      && d.cursor.px.every(Number.isFinite);
    const cursorDataPerAxis = !!d.cursor
      && JSON.stringify(Object.keys(d.cursor.data).sort())
        === JSON.stringify(view._axisIds().sort())
      && Object.values(d.cursor.data).every(Number.isFinite);
    const point = (d.points || [])[0] || {};
    const pointBindings = point.x_axis === "x" && point.y_axis === "y"
      && point.row === d.row && typeof point.color === "string";

    view.canvas.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape", bubbles: true, cancelable: true,
    }));
    const leaveInactive = !!leaveDetail && leaveDetail.active === false;

    document.body.setAttribute("data-xy-hover-probe", JSON.stringify({
      rowSubscriptable, legacyKeys, payloadActive, cursorPx,
      cursorDataPerAxis, pointBindings, leaveInactive,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-hover-probe-error", String((err && err.stack) || err));
  }
"""


def test_hover_payload_is_additive_and_axis_keyed(tmp_path: Path) -> None:
    document = _chart_html(xy.interaction_config(hover=True)).replace(_RENDER_CALL, _HOVER_PROBE)
    result = _run(tmp_path, document, "data-xy-hover-probe", label="hover payload probe")
    assert result == {key: True for key in result}


_MISSED_LEAVE_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    let leaveDetail = null;
    view.root.addEventListener("xy:leave", (e) => { leaveDetail = e.detail; });

    // Establish a *pointer* hover (sets _lastHoverXY, unlike keyboard
    // traversal) by scanning the canvas with pointermoves until a mark hits.
    const c = view.canvas;
    const r = c.getBoundingClientRect();
    const hoverAt = () => {
      for (let y = 10; y < r.height - 10; y += 4) {
        for (let x = 10; x < r.width - 10; x += 4) {
          c.dispatchEvent(new PointerEvent("pointermove", {
            clientX: r.left + x, clientY: r.top + y, bubbles: true, cancelable: true,
          }));
          if (view._hoverId !== -1) return true;
        }
      }
      return false;
    };
    const hovered = hoverAt();
    const tooltipShown = view.tooltip.style.display === "block";

    // A pointerover inside the chart root must NOT clear a live hover.
    c.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
    const insideKept = view._hoverId !== -1 && view.tooltip.style.display === "block";

    // The missed-leave shape (real-browser scroll or hit-test churn skips the
    // canvas pointerleave): the pointer next surfaces OUTSIDE the root, with
    // no canvas pointerleave ever fired. The document-level backstop must run
    // the same exit path.
    document.body.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
    const cleared = view._hoverId === -1 && view._lastHoverXY === null;
    const tooltipHidden = view.tooltip.style.display === "none";
    const leaveDispatched = !!leaveDetail && leaveDetail.active === false;

    // Keyboard readouts are not pointer-owned: the backstop must leave them
    // alone while the mouse roams the page.
    c.dispatchEvent(new KeyboardEvent("keydown", {
      key: "ArrowRight", bubbles: true, cancelable: true,
    }));
    const keyboardShown = view.tooltip.style.display === "block";
    document.body.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
    const keyboardKept = view.tooltip.style.display === "block";

    document.body.setAttribute("data-xy-missed-leave-probe", JSON.stringify({
      hovered, tooltipShown, insideKept,
      cleared, tooltipHidden, leaveDispatched,
      keyboardShown, keyboardKept,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-missed-leave-probe-error", String((err && err.stack) || err));
  }
"""


def test_missed_canvas_leave_backstop_clears_pointer_hover(tmp_path: Path) -> None:
    document = _chart_html(xy.interaction_config(hover=True)).replace(
        _RENDER_CALL, _MISSED_LEAVE_PROBE
    )
    result = _run(tmp_path, document, "data-xy-missed-leave-probe", label="missed-leave probe")
    assert result == {key: True for key in result}


_TOOLTIP_MOUNT_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const custom = document.createElement("div");
    custom.textContent = "CUSTOM";
    view.setCustomTooltip(custom);

    view.canvas.dispatchEvent(new KeyboardEvent("keydown", {
      key: "ArrowRight", bubbles: true, cancelable: true,
    }));
    const mounted = view.tooltip.contains(custom);
    const shown = view.tooltip.style.display === "block";
    // Built-in line rendering suppressed: content is exactly the mount.
    const builtinSuppressed = view.tooltip.childNodes.length === 1
      && view.tooltip.textContent === "CUSTOM";
    const positioned = view.tooltip.style.left !== "" && view.tooltip.style.top !== "";

    document.body.setAttribute("data-xy-tooltipmount-probe", JSON.stringify({
      mounted, shown, builtinSuppressed, positioned,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-tooltipmount-probe-error", String((err && err.stack) || err));
  }
"""


def test_custom_tooltip_mount_owns_content_and_placement(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _TOOLTIP_MOUNT_PROBE),
        "data-xy-tooltipmount-probe",
        label="custom tooltip mount probe",
    )
    assert result == {key: True for key in result}
