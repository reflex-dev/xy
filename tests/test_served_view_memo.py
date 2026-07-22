"""Accepted viewport replies suppress only exact, still-live client requests.

These probes drive the production bundle in Chromium with a deterministic fake
comm.  Replies are produced by the real Python interaction kernel, including a
deep-zoom drill and its binary buffers, so the byte accounting and GPU state
checks cover the same data plane as a notebook round trip.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest

from conftest import run_browser_probe
from xy._figure import Figure
from xy._framing import encode_frame
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
_A = {"x0": 10.0, "x1": 20.0, "y0": -1.0, "y1": 1.0}
_B = {"x0": 10.0, "x1": 20.0, "y0": -0.5, "y1": 0.5}
_ROOT = Path(__file__).resolve().parents[1]


def test_memo_lifecycle_boundaries_precede_payload_and_context_rebuilds() -> None:
    """Pin invalidation order independently of the asynchronous browser probe."""
    chart_view = (_ROOT / "js/src/50_chartview.ts").read_text(encoding="utf-8")
    kernel = (_ROOT / "js/src/54_kernel.ts").read_text(encoding="utf-8")
    animation = (_ROOT / "js/src/56_animation.ts").read_text(encoding="utf-8")

    loss = chart_view[chart_view.index('this._listen(this.canvas, "webglcontextlost"') :]
    assert loss.index("this.seq += 1;") < loss.index("this._clearServedViewMemo?.();")
    assert loss.index("this._clearServedViewMemo?.();") < loss.index('"webglcontextrestored"')

    update = animation[animation.index("updatePayload(spec, buffer)") :]
    assert update.index("this._advanceViewDataGeneration?.();") < update.index("this.spec = spec;")

    append = kernel[
        kernel.index("_applyAppend(msg, buffers)") : kernel.index("_onKernelMsg(msg, buffers)")
    ]
    assert append.index("this._advanceViewDataGeneration();") < append.index("this.spec = spec;")
    assert "const VIEW_REPLY_MEMO_LIMIT = 64;" in kernel


def _fixture() -> tuple[str, dict[str, tuple[dict, list[bytes]]], dict[str, int]]:
    n = 120_000
    x = np.linspace(0.0, 100.0, n, dtype=np.float64)
    fig = Figure(width=480, height=360, padding=0)
    fig.line(x, np.sin(x))
    fig.scatter(x, np.cos(x), density=True)
    document = fig.to_html()
    assert _RENDER_CALL in document

    tier, tier_buffers = fig.decimate_view(_A["x0"], _A["x1"], 480)
    density_a1, density_a1_buffers = fig.density_view(1, **_A, w=480, h=360)
    density_a2, density_a2_buffers = fig.density_view(1, **_A, w=480, h=360)
    density_b, density_b_buffers = fig.density_view(1, **_B, w=480, h=360)
    replies = {
        "tier": ({"type": "tier_update", **tier}, tier_buffers),
        "density_a1": ({"type": "density_update", **density_a1}, density_a1_buffers),
        "density_a2": ({"type": "density_update", **density_a2}, density_a2_buffers),
        "density_b": ({"type": "density_update", **density_b}, density_b_buffers),
    }
    # A representative one-digit seq keeps complete-frame accounting exact for
    # the request probe (JSON length is identical for its one-digit seqs).
    tier_frame = encode_frame({**replies["tier"][0], "seq": 3}, tier_buffers)
    density_frame = encode_frame({**replies["density_a2"][0], "seq": 3}, density_a2_buffers)
    evidence = {
        "tier_payload_bytes": sum(map(len, tier_buffers)),
        "density_payload_bytes": sum(map(len, density_a2_buffers)),
        "duplicate_frame_bytes": len(tier_frame) + len(density_frame),
    }
    return document, replies, evidence


def _js_reply(name: str, reply: tuple[dict, list[bytes]]) -> str:
    message, buffers = reply
    value = {
        "message": message,
        "buffers": [base64.b64encode(buffer).decode("ascii") for buffer in buffers],
    }
    return f"const {name} = {json.dumps(value, separators=(',', ':'))};"


def _preamble(replies: dict[str, tuple[dict, list[bytes]]]) -> str:
    constants = "\n".join(
        [
            _js_reply("TIER", replies["tier"]),
            _js_reply("DENSITY_A1", replies["density_a1"]),
            _js_reply("DENSITY_A2", replies["density_a2"]),
            _js_reply("DENSITY_B", replies["density_b"]),
        ]
    )
    return f"""
  {constants}
  const sent = [];
  const comm = {{
    send: (message) => sent.push({{...message}}),
    onMessage: () => () => {{}},
  }};
  const view = new xy.ChartView(document.getElementById("chart"), spec, buf, comm);
  const decodeBuffers = (reply) => reply.buffers.map((encoded) => {{
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }});
  const deliver = (reply, seq) => view._onKernelMsg(
    {{...reply.message, seq}}, decodeBuffers(reply),
  );
  const requestsSince = (start) => sent.slice(start).filter(
    (message) => message.type === "view" || message.type === "density_view",
  );
  const setView = (value) => {{ view.view = view._copyView(value); }};
"""


def test_accepted_reply_memo_suppresses_exact_requests_and_preserves_drill(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    document, replies, evidence = _fixture()
    probe = (
        _preamble(replies)
        + f"""
  try {{
    view._drawNow(); view._raf = null;
    const A = view._viewFrom({json.dumps(_A)});
    const B = view._viewFrom({json.dumps(_B)});
    setView(A);

    // In-flight work is deliberately not a cache hit: only an accepted reply
    // may suppress a later request.  The first pair becomes stale when the
    // second request advances latest-wins seq.
    let start = sent.length;
    const seq1 = view._scheduleViewRequest(A, {{delay: 0}});
    const firstTypes = requestsSince(start).map((message) => message.type);
    start = sent.length;
    const seq2 = view._scheduleViewRequest(A, {{delay: 0}});
    const beforeAcceptedTypes = requestsSince(start).map((message) => message.type);
    deliver(TIER, seq1); deliver(DENSITY_A1, seq1);
    const staleReplyCachedNothing = view._servedViewMemo.size === 0;
    // A partial current reply may update nothing but must not mark the shared
    // tier served. The density reply is independent and may be admitted.
    deliver({{...TIER, message: {{...TIER.message, traces: []}}}}, seq2);
    deliver(DENSITY_A2, seq2);
    const partialReplyMemoEntries = view._servedViewMemo.size;
    start = sent.length;
    const seq3 = view._scheduleViewRequest(A, {{delay: 0}});
    const partialTierRetryTypes = requestsSince(start).map((message) => message.type);
    deliver(TIER, seq3);
    const acceptedMemoEntries = view._servedViewMemo.size;

    // The exact current request is now a no-op: no JSON request and therefore
    // neither binary reply crosses the transport.
    start = sent.length;
    view._scheduleViewRequest(A, {{delay: 0}});
    const exactDuplicateRequests = requestsSince(start).length;

    // A fallible apply must retire the previous key before mutating retained
    // WebGLBuffer objects. The first duplicate trace updates the live buffers;
    // the second has an invalid buffer reference and throws. Returning to A
    // must request fresh bytes rather than treating object identity as proof
    // that the old contents survived.
    const C = view._viewFrom({{x0: 20, x1: 30, y0: -1, y1: 1}});
    setView(C);
    const seqBroken = view._scheduleViewRequest(C, {{delay: 0}});
    const tierTrace = TIER.message.traces[0];
    let failedApplyThrew = false;
    try {{
      view._onKernelMsg({{
        ...TIER.message, seq: seqBroken,
        traces: [tierTrace, {{...tierTrace, x: {{...tierTrace.x, buf: 999}}}}],
      }}, decodeBuffers(TIER));
    }} catch (_err) {{
      failedApplyThrew = true;
    }}
    setView(A);
    start = sent.length;
    const seqAfterFailedApply = view._scheduleViewRequest(A, {{delay: 0}});
    const failedApplyRetryTypes = requestsSince(start).map((message) => message.type);
    deliver(TIER, seqAfterFailedApply);

    // A selection is indexed against the accepted drill_seq.  A memo hit must
    // retain that subset and its selection buffer instead of replaying/replacing
    // a cached reply under a new drill version.
    const density = view.gpuTraces.find((g) => g.trace.id === 1);
    const drillSeq = density.drill.seq;
    view._onKernelMsg({{
      type: "selection", total: 1,
      traces: [{{id: 1, count: 1, buf: 0, drill_seq: drillSeq}}],
    }}, [new Uint32Array([0]).buffer]);
    start = sent.length;
    view._scheduleViewRequest(A, {{delay: 0}});
    const selectionMemoHit = requestsSince(start).length === 0 &&
      density.drill.seq === drillSeq && density.drill.selActive === true;

    // A y-only pan leaves the line's normalized x request unchanged, so only
    // the density trace needs a round trip. Returning before that reply lands
    // reuses the still-live A state and makes B's reply stale.
    setView(B);
    start = sent.length;
    const seqB = view._scheduleViewRequest(B, {{delay: 0}});
    const yOnlyTypes = requestsSince(start).map((message) => message.type);
    setView(A);
    start = sent.length;
    view._scheduleViewRequest(A, {{delay: 0}});
    const returnToServedRequests = requestsSince(start).length;
    deliver(DENSITY_B, seqB);
    const staleRacePreservedDrill = density.drill.seq === drillSeq && density.drill.selActive;

    // Pixel dimensions are part of both keys. Returning to the accepted size
    // is safe because the different-size replies never landed.
    const plotW = view.plot.w;
    view.plot.w = plotW + 1;
    start = sent.length;
    view._scheduleViewRequest(A, {{delay: 0}});
    const resizedTypes = requestsSince(start).map((message) => message.type);
    view.plot.w = plotW;
    start = sent.length;
    view._scheduleViewRequest(A, {{delay: 0}});
    const restoredSizeRequests = requestsSince(start).length;

    // A points-mode entry is valid only while that exact drill is live. Once
    // the cross-tier lifecycle marks it dying, the density request must run
    // again even though every scalar key field is identical.
    density._drillDying = true;
    start = sent.length;
    view._scheduleViewRequest(A, {{delay: 0}});
    const dyingDrillTypes = requestsSince(start).map((message) => message.type);
    density._drillDying = false;

    // Synthetic slots exercise the hard global bound without changing any GPU
    // state; old entries and their slot index must be evicted together.
    for (let i = 0; i < 80; i++) {{
      view._rememberServedViewRequest({{slot: `synthetic:${{i}}`, key: `key:${{i}}`}}, {{i}});
    }}
    const memoBounded = view._servedViewMemo.size === 64 && view._servedViewSlots.size === 64;

    document.body.setAttribute("data-xy-view-memo", JSON.stringify({{
      firstTypes, beforeAcceptedTypes, staleReplyCachedNothing,
      partialReplyMemoEntries, partialTierRetryTypes, acceptedMemoEntries,
      exactDuplicateRequests, failedApplyThrew, failedApplyRetryTypes,
      selectionMemoHit, yOnlyTypes, returnToServedRequests,
      staleRacePreservedDrill, resizedTypes, restoredSizeRequests, dyingDrillTypes,
      memoBounded,
      duplicateAvoidedRoundTrips: 2,
      duplicateAvoidedPayloadBytes: {evidence["tier_payload_bytes"] + evidence["density_payload_bytes"]},
      duplicateAvoidedFrameBytes: {evidence["duplicate_frame_bytes"]},
      yOnlyTierPayloadBytesAvoided: {evidence["tier_payload_bytes"]},
    }}));
  }} catch (err) {{
    document.body.setAttribute("data-xy-view-memo-error", String((err && err.stack) || err));
  }}
"""
    )
    result = run_browser_probe(
        chromium,
        document.replace(_RENDER_CALL, probe),
        tmp_path / "served_view_memo.html",
        "data-xy-view-memo",
        label="accepted view-reply memo probe",
    )

    assert result["firstTypes"] == ["view", "density_view"]
    assert result["beforeAcceptedTypes"] == ["view", "density_view"]
    assert result["staleReplyCachedNothing"] is True
    assert result["partialReplyMemoEntries"] == 1
    assert result["partialTierRetryTypes"] == ["view"]
    assert result["acceptedMemoEntries"] == 2
    assert result["exactDuplicateRequests"] == 0
    assert result["failedApplyThrew"] is True
    assert result["failedApplyRetryTypes"] == ["view"]
    assert result["selectionMemoHit"] is True
    assert result["yOnlyTypes"] == ["density_view"]
    assert result["returnToServedRequests"] == 0
    assert result["staleRacePreservedDrill"] is True
    assert result["resizedTypes"] == ["view", "density_view"]
    assert result["restoredSizeRequests"] == 0
    assert result["dyingDrillTypes"] == ["density_view"]
    assert result["memoBounded"] is True
    assert result["duplicateAvoidedRoundTrips"] == 2
    assert result["duplicateAvoidedPayloadBytes"] == (
        evidence["tier_payload_bytes"] + evidence["density_payload_bytes"]
    )
    assert result["duplicateAvoidedFrameBytes"] == evidence["duplicate_frame_bytes"]
    assert result["yOnlyTierPayloadBytesAvoided"] == evidence["tier_payload_bytes"]


def test_density_grid_memo_requires_request_association_and_live_texture(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    n = 220_000
    x = np.linspace(0.0, 100.0, n, dtype=np.float64)
    fig = Figure(width=480, height=360, padding=0).scatter(x, np.cos(x), density=True)
    spec, _blob = fig.build_payload(480)
    x0, x1 = spec["x_axis"]["range"]
    y0, y1 = spec["y_axis"]["range"]
    update, buffers = fig.density_view(0, x0, x1, y0, y1, 480, 360)
    assert update["traces"][0]["mode"] == "density"
    reply = ({"type": "density_update", **update}, buffers)
    document = fig.to_html()
    probe = f"""
  {_js_reply("DENSITY", reply)}
  const sent = [];
  const comm = {{send: (message) => sent.push({{...message}}), onMessage: () => () => {{}}}};
  const view = new xy.ChartView(document.getElementById("chart"), spec, buf, comm);
  const decode = () => DENSITY.buffers.map((encoded) => {{
    const binary = atob(encoded), bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }});
  try {{
    view._drawNow(); view._raf = null;
    const home = view._copyView(view.view0);
    let start = sent.length;
    const seq = view._scheduleViewRequest(home, {{delay: 0}});
    const firstRequests = sent.slice(start).filter((m) => m.type === "density_view").length;
    view._onKernelMsg({{...DENSITY.message, seq}}, decode());
    const g = view.gpuTraces[0], acceptedGrid = g.density;
    const accepted = view._servedViewMemo.size === 1 && !!acceptedGrid.tex;

    start = sent.length;
    view._scheduleViewRequest(home, {{delay: 0}});
    const duplicateRequests = sent.slice(start).filter((m) => m.type === "density_view").length;
    const gridIdentityPreserved = g.density === acceptedGrid;

    // Same-seq pushed/duplicate data has no pending request metadata. It may be
    // applied for compatibility, but must retire the old key rather than make
    // an unsafe association with the current viewport.
    view._onKernelMsg({{...DENSITY.message, seq: view.seq}}, decode());
    const unsolicitedInvalidated = view._servedViewMemo.size === 0;
    start = sent.length;
    view._scheduleViewRequest(home, {{delay: 0}});
    const requestAfterUnsolicited = sent.slice(start).filter(
      (m) => m.type === "density_view",
    ).length;
    document.body.setAttribute("data-xy-density-memo", JSON.stringify({{
      firstRequests, accepted, duplicateRequests, gridIdentityPreserved,
      unsolicitedInvalidated, requestAfterUnsolicited,
    }}));
  }} catch (err) {{
    document.body.setAttribute("data-xy-density-memo-error", String((err && err.stack) || err));
  }}
"""
    result = run_browser_probe(
        chromium,
        document.replace(_RENDER_CALL, probe),
        tmp_path / "served_density_grid_memo.html",
        "data-xy-density-memo",
        label="accepted density-grid memo probe",
    )
    assert result == {
        "firstRequests": 1,
        "accepted": True,
        "duplicateRequests": 0,
        "gridIdentityPreserved": True,
        "unsolicitedInvalidated": True,
        "requestAfterUnsolicited": 1,
    }


def test_payload_append_and_context_lifecycle_invalidate_memo(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    document, replies, _evidence = _fixture()
    probe = (
        _preamble(replies)
        + f"""
  (async () => {{
    try {{
      view._drawNow(); view._raf = null;
      const A = view._viewFrom({json.dumps(_A)});
      const answerCurrent = () => {{
        const seq = view.seq;
        deliver(TIER, seq); deliver(DENSITY_A2, seq);
      }};
      setView(A);
      view._scheduleViewRequest(A, {{delay: 0}});
      answerCurrent();
      const initialMemo = view._servedViewMemo.size;
      const initialGeneration = view._viewDataGeneration;

      // A full canonical replacement invalidates accepted and in-flight keys,
      // even when this fixture intentionally reuses byte-identical data.
      const fullApplied = view.updatePayload(spec, buf);
      const fullInvalidated = view._servedViewMemo.size === 0;
      setView(A);
      let start = sent.length;
      view._scheduleViewRequest(A, {{delay: 0}});
      const fullRequests = requestsSince(start).map((message) => message.type);
      answerCurrent();

      // Append has the same generation boundary and immediately refines the
      // current window after rebuilding affected traces.
      start = sent.length;
      view._applyAppend({{spec, affected: [0, 1]}}, [buf]);
      const appendRequests = requestsSince(start).map((message) => message.type);
      const appendInvalidatedBeforeReply = view._servedViewMemo.size === 0;
      answerCurrent();

      // Dispatch the production lifecycle handlers on the live WebGL chart.
      // Chromium's --virtual-time-budget does not reliably deliver an extension
      // restore event after WEBGL_lose_context, so the event itself is synthetic;
      // resource rebuild, draw validation, memo clearing, and fresh scheduling
      // are still the real ChartView paths in a real browser context.
      view._ctxVisible = false; // prevent automatic recovery racing this probe
      view.canvas.dispatchEvent(new Event("webglcontextlost", {{cancelable: true}}));
      const contextLossInvalidated = view._servedViewMemo.size === 0 && view._glLost;
      view._ctxVisible = true;
      start = sent.length;
      view.canvas.dispatchEvent(new Event("webglcontextrestored"));
      const restoreRequests = requestsSince(start).map((message) => message.type);

      document.body.setAttribute("data-xy-view-memo-lifecycle", JSON.stringify({{
        initialMemo, fullApplied, fullInvalidated, fullRequests,
        appendInvalidatedBeforeReply, appendRequests, contextLossInvalidated,
        restoreRequests, contextReady: !view._glLost,
        generationSteps: view._viewDataGeneration - initialGeneration,
      }}));
    }} catch (err) {{
      document.body.setAttribute(
        "data-xy-view-memo-lifecycle-error", String((err && err.stack) || err),
      );
    }}
  }})();
"""
    )
    result = run_browser_probe(
        chromium,
        document.replace(_RENDER_CALL, probe),
        tmp_path / "served_view_memo_lifecycle.html",
        "data-xy-view-memo-lifecycle",
        label="view-reply memo lifecycle probe",
    )

    assert result == {
        "initialMemo": 2,
        "fullApplied": True,
        "fullInvalidated": True,
        "fullRequests": ["view", "density_view"],
        "appendInvalidatedBeforeReply": True,
        "appendRequests": ["view", "density_view"],
        "contextLossInvalidated": True,
        "restoreRequests": ["view", "density_view"],
        "contextReady": True,
        "generationSteps": 2,
    }
