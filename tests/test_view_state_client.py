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

import numpy as np
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


_RESTYLE_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const g = view.gpuTraces[0];
    const xBuffer = g.xBuf;
    const yBuffer = g.yBuf;
    const payload = view._payload;
    const beforeColumns = JSON.stringify(view.spec.columns);

    view._onKernelMsg({
      type: "restyle", trace: 0,
      style: { color: "#ef4444", opacity: 0.35, stroke: "#111827", stroke_width: 2 },
      size: 9,
    }, []);
    const applied = g.trace.style.color === "#ef4444"
      && g.trace.style.opacity === 0.35 && g.size === 9 && g.pointStrokeWidth === 2;
    const buffersReused = g.xBuf === xBuffer && g.yBuf === yBuffer
      && view.gl.isBuffer(xBuffer) && view.gl.isBuffer(yBuffer);
    const payloadReused = view._payload === payload
      && JSON.stringify(view.spec.columns) === beforeColumns;
    const specPersisted = view.spec.traces[0].style.color === "#ef4444"
      && view.spec.traces[0].size.size === 9;

    const beforeMalformed = JSON.stringify(g.trace.style);
    const structuralRejected = view._applyRestyle({
      type: "restyle", trace: 0, style: { curve: "smooth" },
    }) === false && JSON.stringify(g.trace.style) === beforeMalformed;
    const badSizeRejected = view._applyRestyle({
      type: "restyle", trace: 0, style: {}, size: -1,
    }) === false && g.size === 9;

    // A real WebGL context-loss event takes the same early path. The patch
    // must still land in retained spec so restore rebuilds from it.
    view._glLost = true;
    const acceptedWhileLost = view._applyRestyle({
      type: "restyle", trace: 0, style: { opacity: 0.2 },
    }) === true && view.spec.traces[0].style.opacity === 0.2;
    view._glLost = false;

    document.body.setAttribute("data-xy-restyle-probe", JSON.stringify({
      applied, buffersReused, payloadReused, specPersisted,
      structuralRejected, badSizeRejected, acceptedWhileLost,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-restyle-probe-error", String((err && err.stack) || err));
  }
"""


def test_restyle_message_updates_constants_without_gpu_reupload(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _RESTYLE_PROBE),
        "data-xy-restyle-probe",
        label="buffer-less restyle probe",
    )
    assert result == {key: True for key in result}


_DENSITY_RESTYLE_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const g = view.gpuTraces[0];
    const texture = g.density.tex;
    const sampleX = g.sampleOverlay && g.sampleOverlay.xBuf;
    view._onKernelMsg({
      type: "restyle", trace: 0,
      style: { color: "#00ff00", opacity: 0.4 }, size: 7,
    }, []);
    const aggregateUpdated = g.trace.style.opacity === 0.4
      && Math.abs(g.density.color[0]) < 1e-6
      && Math.abs(g.density.color[1] - 1) < 1e-6
      && Math.abs(g.density.color[2]) < 1e-6;
    const sampleUpdated = !g.sampleOverlay || (
      g.sampleOverlay.trace.style.color === "#00ff00" && g.sampleOverlay.size === 7);
    const resourcesReused = g.density.tex === texture && view.gl.isTexture(texture)
      && (!sampleX || (g.sampleOverlay.xBuf === sampleX && view.gl.isBuffer(sampleX)));
    const retainedSpecUpdated = view.spec.traces[0].density.color === "#00ff00"
      && view.spec.traces[0].style.opacity === 0.4;
    document.body.setAttribute("data-xy-density-restyle-probe", JSON.stringify({
      aggregateUpdated, sampleUpdated, resourcesReused, retainedSpecUpdated,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-density-restyle-probe-error", String((err && err.stack) || err));
  }
"""


def test_density_restyle_updates_cached_tiers_without_rebuild(tmp_path: Path) -> None:
    rng = np.random.default_rng(163)
    chart = xy.scatter_chart(
        xy.scatter(
            rng.normal(size=20_000),
            rng.normal(size=20_000),
            color="#2563eb",
            size=4,
            density=True,
        ),
        width=480,
        height=360,
    )
    result = _run(
        tmp_path,
        chart.to_html().replace(_RENDER_CALL, _DENSITY_RESTYLE_PROBE),
        "data-xy-density-restyle-probe",
        label="density restyle lifecycle probe",
    )
    assert result == {key: True for key in result}


_COLUMN_CACHE_PROBE = """
  try {
    const cache = new Map();
    const firstSpec = { buffer_layout: "split", columns: [
      { buf: 0, byte_offset: 0, len: 4, hash: "h:x" },
      { buf: 1, byte_offset: 0, len: 4, hash: "h:y1" },
    ]};
    const x = new Uint8Array([1, 2, 3, 4]);
    const y1 = new Uint8Array([5, 6, 7, 8]);
    const first = xy.resolveColumnBuffers(firstSpec, [x, y1], ["h:x", "h:y1"], cache);
    const oldX = first[0];

    const secondSpec = { buffer_layout: "split", columns: [
      { buf: 0, byte_offset: 0, len: 4, hash: "h:x" },
      { buf: 1, byte_offset: 0, len: 4, hash: "h:y2" },
      { buf: 2, byte_offset: 0, len: 4, hash: "h:x" },
    ]};
    const y2 = new Uint8Array([9, 10, 11, 12]);
    const second = xy.resolveColumnBuffers(secondSpec, [y2], ["h:y2"], cache);
    const unchangedResolved = second[0] === oldX && second[2] === oldX;
    const changedResolved = second[1][0] === 9 && second[1][3] === 12;
    const boundedToCurrent = cache.size === 2 && cache.has("h:x") && cache.has("h:y2");

    const keysBeforeFailure = JSON.stringify([...cache.keys()].sort());
    let missingRejected = false;
    try {
      xy.resolveColumnBuffers(
        { buffer_layout: "split", columns: [
          { buf: 0, byte_offset: 0, len: 4, hash: "h:missing" },
        ]},
        [],
        [],
        cache,
      );
    } catch (_err) {
      missingRejected = true;
    }
    const failureTransactional = missingRejected
      && JSON.stringify([...cache.keys()].sort()) === keysBeforeFailure;

    let duplicateRejected = false;
    try {
      xy.resolveColumnBuffers(firstSpec, [x, x], ["h:x", "h:x"], cache);
    } catch (_err) {
      duplicateRejected = true;
    }
    const malformedTransactional = duplicateRejected
      && JSON.stringify([...cache.keys()].sort()) === keysBeforeFailure;

    document.body.setAttribute("data-xy-column-cache-probe", JSON.stringify({
      unchangedResolved, changedResolved, boundedToCurrent,
      failureTransactional, malformedTransactional,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-column-cache-probe-error", String((err && err.stack) || err));
  }
"""


def test_content_addressed_manifest_reconstructs_sparse_payloads(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _COLUMN_CACHE_PROBE),
        "data-xy-column-cache-probe",
        label="content-addressed column manifest probe",
    )
    assert result == {key: True for key in result}


_GPU_COLUMN_CACHE_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const old = view.gpuTraces[0];
    const oldX = old.xBuf;
    const oldY = old.yBuf;
    const cachePopulated = view._gpuColumnCache.size >= 2;
    const updated = view.updatePayload(structuredClone(view.spec), view._payload) === true;
    const fresh = view.gpuTraces[0];
    const gpuBuffersReused = fresh.xBuf === oldX && fresh.yBuf === oldY
      && view.gl.isBuffer(oldX) && view.gl.isBuffer(oldY);
    const refsBalanced = [...view._gpuColumnCache.values()].every((entry) => entry.refs === 1);

    const decimatedHost = document.body.appendChild(document.createElement("div"));
    const decimatedSpec = structuredClone(spec);
    decimatedSpec.traces[0].tier = "decimated";
    const decimated = xy.renderStandalone(decimatedHost, decimatedSpec, buf);
    const mutableTierExcluded = decimated._gpuColumnCache.size === 0;
    decimated.destroy();

    view._destroyGlResources();
    const teardownCleared = view._gpuColumnCache.size === 0
      && !view.gl.isBuffer(oldX) && !view.gl.isBuffer(oldY);
    document.body.setAttribute("data-xy-gpu-column-cache-probe", JSON.stringify({
      cachePopulated, updated, gpuBuffersReused, refsBalanced,
      mutableTierExcluded, teardownCleared,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-gpu-column-cache-probe-error", String((err && err.stack) || err));
  }
"""


def test_unchanged_direct_columns_reuse_gpu_buffers_and_balance_lifetime(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _chart_html().replace(_RENDER_CALL, _GPU_COLUMN_CACHE_PROBE),
        "data-xy-gpu-column-cache-probe",
        label="GPU column cache lifecycle probe",
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
    // Config: pan_axes=("x","y"), zoom_axes=("x",). The cursor advertises
    // capability (view-state.md §6): resize only where zoom works; the
    // pan-only y band shows a grab hand, grabbing while a drag is active.
    const bandX = view.root.querySelector('[data-xy-axis-band="x"]');
    const bandY = view.root.querySelector('[data-xy-axis-band="y"]');
    const zoomableShowsResize = !!bandX && bandX.style.cursor === "ew-resize";
    const panOnlyShowsGrab = !!bandY && bandY.style.cursor === "grab";

    let grabbingDuringDrag = false;
    let grabRestoredAfterDrag = false;
    if (bandY) {
      const yRect = bandY.getBoundingClientRect();
      const sx = yRect.left + yRect.width / 2;
      const sy = yRect.top + yRect.height / 2;
      const opts = (x, y) => (
        { pointerId: 9, clientX: x, clientY: y, bubbles: true, cancelable: true });
      bandY.dispatchEvent(new PointerEvent("pointerdown", opts(sx, sy)));
      bandY.dispatchEvent(new PointerEvent("pointermove", opts(sx, sy + 40)));
      grabbingDuringDrag = bandY.style.cursor === "grabbing";
      bandY.dispatchEvent(new PointerEvent("pointerup", opts(sx, sy + 40)));
      grabRestoredAfterDrag = bandY.style.cursor === "grab";
    }

    document.body.setAttribute("data-xy-axisband-policy-probe", JSON.stringify({
      zoomableShowsResize, panOnlyShowsGrab,
      grabbingDuringDrag, grabRestoredAfterDrag,
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
