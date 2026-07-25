"""A full-payload update re-homes to the new data, so a grown range expands.

Section 4 of the reflex-xy showcase links two charts: zooming the overview's x
range recomputes a *detail* histogram of only the points in view, and pushes it
as a full ``payload`` (reflex-integration.md §4, "state-driven rebuild"). The
client applies that in place via ``ChartView.updatePayload``.

Zooming the overview *out* grows the detail: more points in view means taller
bins, so the recomputed histogram's count axis spans a larger range than the
window it replaces. ``updatePayload`` must re-home the view to the incoming
spec's own axis ranges — exactly as a fresh mount would — rather than clamp the
new window to the previous, smaller home span. If it clamps, the taller bars
overflow the stale window and the plot paints as a solid clipped block (the
reported bug: the right chart goes solid on zoom-out while zoom-in is fine,
because zoom-in only ever *shrinks* the range and so never trips the clamp).

This drives the real client in headless Chromium: it renders a small-count
histogram, then feeds ``updatePayload`` a genuine large-count histogram payload
and reads back the resulting home/view. The count axis must follow the new data
up, not stay pinned to the old home.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

# The initial (small) payload rides in through the normal standalone render; the
# larger recomputed payload is injected here and applied via updatePayload, the
# same call XYChart.jsx's `onPayload` makes for a state-driven rebuild.
_PROBE_BODY = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    const b64ToBytes = (b64) => {
      const bin = atob(b64);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    };
    // Home the view established from the small payload (the window a zoomed-in
    // overview would have produced).
    const homeBefore = { y0: view.view0.y0, y1: view.view0.y1 };
    // Apply the larger recomputed payload — the linked overview zooming out.
    const applied = view.updatePayload(LARGE_SPEC, b64ToBytes(LARGE_B64));
    view._drawNow();
    const homeAfter = { y0: view.view0.y0, y1: view.view0.y1 };
    const viewAfter = { y0: view.view.y0, y1: view.view.y1 };
    document.body.setAttribute("data-xy-rehome-probe", JSON.stringify({
      applied,
      homeBefore,
      homeAfter,
      viewAfter,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-rehome-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _histogram_chart(values: np.ndarray) -> xy.Chart:
    return xy.histogram_chart(
        xy.histogram(values, bins=48, color="#7c3aed"),
        xy.x_axis(label="value in view"),
        width=480,
        height=360,
    )


def test_payload_update_rehomes_to_grown_range(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    # Small count axis (few points) vs a much taller one (many points): a
    # zoom-out on the linked overview turns the first into the second.
    small = _histogram_chart(np.random.default_rng(0).normal(0.0, 1.0, 200))
    large = _histogram_chart(np.random.default_rng(1).normal(0.0, 1.0, 60_000))

    small_spec, _ = small.figure().build_payload()
    large_spec, large_buf = large.figure().build_payload()
    small_y1 = small_spec["y_axis"]["range"][1]
    large_y1 = large_spec["y_axis"]["range"][1]
    # The scenario only bites when the range genuinely grows across the update.
    assert large_y1 > small_y1 * 100

    preamble = (
        f"const LARGE_SPEC = {json.dumps(large_spec)};\n"
        f'const LARGE_B64 = "{base64.b64encode(large_buf).decode("ascii")}";\n'
    )
    document = small.to_html().replace(_RENDER_CALL, preamble + _PROBE_BODY)

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "payload_rehome.html",
        "data-xy-rehome-probe",
        label="payload re-home probe",
    )

    assert result["applied"] is True
    # Before the update the home is the small payload's count axis.
    assert result["homeBefore"]["y1"] == pytest.approx(small_y1, rel=1e-3)
    # After a full-payload update the home re-fits to the new (taller) data:
    # the count axis follows it up instead of staying pinned to the old home.
    assert result["homeAfter"]["y1"] == pytest.approx(large_y1, rel=1e-3)
    assert result["homeAfter"]["y0"] == pytest.approx(0.0, abs=1e-6)
    # The displayed view tracks the new home (no animation configured), so the
    # bars fit the window rather than overflowing it into a solid block.
    assert result["viewAfter"]["y1"] == pytest.approx(large_y1, rel=1e-3)
    # Guard the exact regression: a clamp to the old home caps the window *span*
    # to the previous ~small_y1 tall home (the bug left a thin sliver floating
    # mid-range, painting solid), whereas re-homing spans the full new range.
    span_after = result["viewAfter"]["y1"] - result["viewAfter"]["y0"]
    assert span_after == pytest.approx(large_y1, rel=1e-3)
    assert span_after > small_y1 * 100
