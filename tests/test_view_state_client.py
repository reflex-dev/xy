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
    const backBtn = view.root.querySelector('[data-xy-modebar-history="back"]');
    const fwdBtn = view.root.querySelector('[data-xy-modebar-history="forward"]');
    const buttonsExist = !!backBtn && !!fwdBtn;
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

    // Back restores the pre-gesture ranges; forward returns exactly.
    const beforeBack = ranges();
    handle.back();
    flush();
    const backRestored = JSON.stringify(ranges()) !== JSON.stringify(beforeBack);
    handle.forward();
    flush();
    const forwardRestored = JSON.stringify(ranges()) === JSON.stringify(beforeBack);

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
      buttonsExist, backDisabledAtStart, threeCommandsThreeEntries,
      backEnabledAfterZoom, wheelGestureOneEntry, backRestored, forwardRestored,
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
      && bandX.style.cursor === "ew-resize" && bandY.style.cursor === "ns-resize";

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
    document.body.setAttribute("data-xy-axisband-policy-probe", JSON.stringify({
      // y is outside both pan_axes and zoom_axes -> no band, no resize cursor.
      noBandForExcludedAxis: !view.root.querySelector('[data-xy-axis-band="y"]'),
      bandForNavigableAxis: !!view.root.querySelector('[data-xy-axis-band="x"]'),
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axisband-policy-probe-error", String((err && err.stack) || err));
  }
"""


def test_axis_band_respects_axis_policies(tmp_path: Path) -> None:
    document = _chart_html(xy.interaction_config(pan_axes=("x",), zoom_axes=("x",))).replace(
        _RENDER_CALL, _AXIS_BAND_POLICY_PROBE
    )
    result = _run(
        tmp_path, document, "data-xy-axisband-policy-probe", label="axis-band policy probe"
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
