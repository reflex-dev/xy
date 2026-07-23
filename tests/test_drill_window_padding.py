"""Padded aligned drill windows + drill-subset history (LOD doc T13, #225).

A points-tier reply ships the largest ALIGNED window around the view whose
exact count still fits the budget: bounds snap outward to a power-of-two grid
over the trace's extent (`lod.aligned_window`), so consecutive pans resolve to
the SAME window and the client's point-window cache can key, dedupe, and
reuse full-point buffers by dimension. The raw view window is the floor —
never a subset, never over budget — and the §16 offset encoding re-centers on
the shipped window, so its span is hard-capped relative to the view
(DRILL_PAD_SPAN_CAP) to keep deep zooms inside the client's re-encode ladder.
"""

from __future__ import annotations

import numpy as np
import pytest

from xy import lod
from xy._figure import Figure
from xy.config import DRILL_PAD_SPAN_CAP, SCATTER_DENSITY_THRESHOLD


def _uniform_fig(n: int, seed: int = 3) -> tuple[Figure, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    return Figure().scatter(x, y, density=True), x, y


def test_aligned_window_contains_input_and_is_pan_stable() -> None:
    # Containment is the contract (client request elision needs it), even for
    # windows panned past the data extent where nothing lives.
    lo, hi = lod.aligned_window(-3.0, 5.0, 0.0, 100.0, 2.0)
    assert lo <= -3.0 and hi >= 5.0
    # Same span bucket, different pan positions inside one block: identical
    # aligned bounds — this is what makes cached windows reusable/dedupable.
    a = lod.aligned_window(10.0, 14.0, 0.0, 128.0, 2.0)
    b = lod.aligned_window(10.5, 14.5, 0.0, 128.0, 2.0)
    assert a == b
    # Bounds land on the extent's power-of-two grid.
    span = 14.0 - 10.0
    level = int(np.ceil(np.log2(128.0 / (2.0 * span))))
    block = 128.0 / (1 << level)
    assert a[0] / block == pytest.approx(round(a[0] / block))
    assert a[1] / block == pytest.approx(round(a[1] / block))


def test_aligned_window_degenerate_inputs_pass_through() -> None:
    assert lod.aligned_window(3.0, 3.0, 0.0, 10.0, 2.0) == (3.0, 3.0)  # zero span
    assert lod.aligned_window(1.0, 2.0, 5.0, 5.0, 2.0) == (1.0, 2.0)  # zero extent
    assert lod.aligned_window(1.0, 2.0, 0.0, np.inf, 2.0) == (1.0, 2.0)
    # pad*span >= extent: the whole extent (unioned with the window so a view
    # sticking past the data stays contained).
    assert lod.aligned_window(1.0, 9.0, 0.0, 10.0, 4.0) == (0.0, 10.0)
    assert lod.aligned_window(-2.0, 9.0, 0.0, 10.0, 4.0) == (-2.0, 10.0)


def test_drill_ships_padded_aligned_window_within_budget() -> None:
    fig, x, y = _uniform_fig(SCATTER_DENSITY_THRESHOLD + 300_000)
    upd, _ = fig.density_view(0, 40.0, 44.0, 40.0, 44.0, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "points" and tr["reduction"] == "none"
    (wx0, wx1), (wy0, wy1) = tr["x_range"], tr["y_range"]
    # Contains the view, wider than it, still under budget.
    assert wx0 <= 40.0 and wx1 >= 44.0 and wy0 <= 40.0 and wy1 >= 44.0
    assert (wx1 - wx0) > 4.0 and (wy1 - wy0) > 4.0
    assert tr["visible"] <= SCATTER_DENSITY_THRESHOLD
    # visible counts the SHIPPED window exactly.
    inwin = int(np.sum((x >= wx0) & (x <= wx1) & (y >= wy0) & (y <= wy1)))
    assert tr["visible"] == inwin
    # §16: offsets re-center on the SHIPPED window's midpoint, and the span
    # cap keeps the padded window inside the client's re-encode ladder.
    assert tr["x"]["offset"] == pytest.approx((wx0 + wx1) / 2.0)
    assert (wx1 - wx0) <= 4.0 * DRILL_PAD_SPAN_CAP
    assert (wy1 - wy0) <= 4.0 * DRILL_PAD_SPAN_CAP


def test_padded_windows_are_identical_across_pans() -> None:
    fig, _, _ = _uniform_fig(SCATTER_DENSITY_THRESHOLD + 300_000)
    upd_a, _ = fig.density_view(0, 40.0, 44.0, 40.0, 44.0, 512, 384)
    upd_b, _ = fig.density_view(0, 40.7, 44.7, 39.5, 43.5, 512, 384)
    tr_a, tr_b = upd_a["traces"][0], upd_b["traces"][0]
    assert tr_a["mode"] == tr_b["mode"] == "points"
    # A small pan inside the same aligned blocks resolves to the SAME shipped
    # window — the client-side cache dedupes it, the wire carries it once.
    assert tr_a["x_range"] == tr_b["x_range"]
    assert tr_a["y_range"] == tr_b["y_range"]


def test_padding_falls_back_to_view_window_when_over_budget() -> None:
    # A view centered on the extent midpoint straddles a grid line at every
    # candidate level, so ANY aligned superset roughly doubles the count; with
    # the view's own count near the budget, every ladder rung is over budget
    # and the raw view window ships, exactly as before padding existed.
    n = 1_000_000
    rng = np.random.default_rng(5)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, density=True)
    # view count ~= n * (a/100)^2 targeted at ~0.95 * budget, centered at 50.
    a = 100.0 * float(np.sqrt(0.95 * SCATTER_DENSITY_THRESHOLD / n))
    upd, _ = fig.density_view(0, 50.0 - a / 2, 50.0 + a / 2, 50.0 - a / 2, 50.0 + a / 2, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "points"
    assert tr["x_range"] == [50.0 - a / 2, 50.0 + a / 2]
    assert tr["y_range"] == [50.0 - a / 2, 50.0 + a / 2]
    assert tr["visible"] <= SCATTER_DENSITY_THRESHOLD


def test_nonlinear_axis_skips_padding() -> None:
    # Raw-space alignment mis-sizes log windows near zero; nonlinear-axis
    # traces keep today's exact-view drill (recorded contract, LOD doc T13).
    n = SCATTER_DENSITY_THRESHOLD + 100_000
    rng = np.random.default_rng(9)
    x = rng.uniform(1.0, 1000.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, density=True)
    fig.set_axis("x", type_="log")
    upd, _ = fig.density_view(0, 10.0, 20.0, 40.0, 60.0, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "points"
    assert tr["x_range"] == [10.0, 20.0]
    assert tr["y_range"] == [40.0, 60.0]


def test_padded_span_cap_guards_f32_reencode_ladder() -> None:
    # A tiny dataset fits any window under the budget, so only the span cap
    # stops a microscopic view from shipping the whole extent — whose midpoint
    # offset would leave the client's §16 re-encode requests unable to ever
    # improve precision.
    n = 50_000
    rng = np.random.default_rng(13)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, density=True)
    upd, _ = fig.density_view(0, 50.0, 50.001, 50.0, 50.001, 512, 384)
    tr = upd["traces"][0]
    assert tr["mode"] == "points"
    (wx0, wx1), (wy0, wy1) = tr["x_range"], tr["y_range"]
    assert wx0 <= 50.0 and wx1 >= 50.001
    assert (wx1 - wx0) <= 0.001 * DRILL_PAD_SPAN_CAP
    assert (wy1 - wy0) <= 0.001 * DRILL_PAD_SPAN_CAP


def test_append_clears_drill_history() -> None:
    n = SCATTER_DENSITY_THRESHOLD + 50_000
    rng = np.random.default_rng(17)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, density=True)
    upd, _ = fig.density_view(0, 10.0, 16.0, 10.0, 16.0, 512, 384)
    seq = upd["traces"][0]["drill_seq"]
    assert fig.pick(0, 0, drill_seq=seq) is not None
    fig.append(0, np.asarray([1.0]), np.asarray([1.0]))
    # Remembered subsets were computed against the pre-append canonical state;
    # a stale-seq pick must die rather than translate (§16 exact-or-nothing).
    assert fig.traces[0].drill_history == {}
    assert fig.pick(0, 0, drill_seq=seq) is None
