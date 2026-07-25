"""A wheel gesture must always close with a terminal "end" view event.

View events are coalesced into a single animation frame, so a gesture-end timer
that survives into the next wheel delta does not merely fire early: the apply
frame already queued behind it overwrites the pending "end" in the coalescer,
and the gesture never delivers a terminal event carrying the committed range.
Consumers that commit on "end" -- server round-trips, linked views -- then wait
on a stale "update" forever. The end timer must therefore be cancelled when the
delta is *queued*, not when it is applied a frame later.

Wall-clock timers cannot reproducibly express "a wheel delta lands 1 ms before
the 90 ms deadline", so this drives the real client in headless Chromium behind
a deterministic clock and frame queue and asserts on the consumer-visible
`xy:view_change` stream, after coalescing.
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

    // Assert on what a consumer actually receives, i.e. after coalescing.
    const events = [];
    view.root.addEventListener("xy:view_change", (e) => {
      events.push({
        phase: e.detail.phase,
        source: e.detail.source,
        interactionId: e.detail.interaction_id,
        ranges: e.detail.ranges,
      });
    });

    // The defect is an interleave, so the probe has to place a delta *between*
    // the end timer arming and its deadline. Swap in a deterministic clock and
    // frame queue for the sequence, then restore them.
    const realSetTimeout = window.setTimeout;
    const realClearTimeout = window.clearTimeout;
    const realRaf = window.requestAnimationFrame;
    let now = 0;
    let nextTimerId = 1;
    const timers = new Map();
    let frames = [];
    window.setTimeout = (fn, ms) => {
      const id = nextTimerId++;
      timers.set(id, { fn, at: now + (ms || 0) });
      return id;
    };
    window.clearTimeout = (id) => { timers.delete(id); };
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const advance = (ms) => {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= now) { timers.delete(id); timer.fn(); }
      }
    };
    // A frame may queue the next one (apply -> emit -> dispatch); drain them.
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames;
        frames = [];
        for (const fn of queued) fn();
      }
    };

    let probe;
    try {
      // 1) First delta applies and arms the 90 ms gesture-end timer.
      view._queueWheelZoom(0.8, 0.35, 0.35);
      flush();
      const armedAfterFirstDelta = timers.size > 0;
      const endsAfterFirstDelta = events.filter((e) => e.phase === "end").length;

      // 2) A second delta lands at 89 ms, one frame short of the deadline.
      advance(89);
      view._queueWheelZoom(0.8, 0.35, 0.35);

      // 3) Cross the *original* deadline while that delta is still queued. A
      //    surviving timer emits "end" here, and the apply frame behind it
      //    then overwrites that "end" in the coalescer.
      advance(11);
      const endLeakedMidGesture =
        events.filter((e) => e.phase === "end").length > endsAfterFirstDelta;

      // 4) Apply the second delta, then let the gesture settle for real.
      flush();
      advance(500);
      flush();

      const ends = events.filter((e) => e.phase === "end");
      const last = events.length ? events[events.length - 1] : null;
      probe = {
        armedAfterFirstDelta,
        endLeakedMidGesture,
        endCount: ends.length,
        eventCount: events.length,
        lastPhase: last && last.phase,
        lastSource: last && last.source,
        interactionIdCount: new Set(events.map((e) => e.interactionId)).size,
        lastRanges: last && last.ranges,
        finalRanges: Object.fromEntries(
          view._axisIds().map((id) => [id, [...view._axisRange(id)]])
        ),
      };
    } finally {
      window.setTimeout = realSetTimeout;
      window.clearTimeout = realClearTimeout;
      window.requestAnimationFrame = realRaf;
    }

    document.body.setAttribute("data-xy-wheel-end-probe", JSON.stringify(probe));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-wheel-end-probe-error",
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


def test_wheel_delta_before_deadline_still_ends_the_gesture(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _chart_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "wheel_gesture_end.html",
        "data-xy-wheel-end-probe",
        label="wheel gesture end probe",
    )

    # The probe is only meaningful if the first delta actually armed the timer.
    assert result["armedAfterFirstDelta"] is True
    assert result["eventCount"] > 0

    # No "end" while a delta is still queued: that is the event the coalescer
    # would swallow, costing the gesture its terminal event.
    assert result["endLeakedMidGesture"] is False

    # The gesture terminates exactly once, as the last thing consumers see.
    assert result["endCount"] == 1
    assert result["lastPhase"] == "end"
    assert result["lastSource"] == "wheel_zoom"

    # One gesture reports one interaction id across every phase.
    assert result["interactionIdCount"] == 1

    # The terminal event carries the *committed* range, so it must be dispatched
    # after the final delta applied, not from a range snapshot taken before it.
    assert result["lastRanges"] == result["finalRanges"]
