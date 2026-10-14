"""Malformed client messages never raise and never mutate figure state.

Wire-protocol §1: `handle_message` returns None (or a `row: null` pick reply)
for anything a hostile or racing client can send, and a dropped message
leaves drill bookkeeping, the view-state cache, and legend predicates exactly
as it found them. `tests/test_channel.py` pins the happy paths; this file is
the fuzz-shaped complement, seeded with the audit's reproductions.
"""

from __future__ import annotations

import math
from typing import Any
from unittest import mock

import numpy as np
import pytest

from xy import lod
from xy._figure import Figure
from xy.channel import ChannelCallbacks, handle_message


def _density_scatter(n: int = 5_000) -> Figure:
    rng = np.random.default_rng(7)
    return Figure().scatter(rng.uniform(0.0, 100.0, n), rng.uniform(0.0, 100.0, n), density=True)


def _snapshot(fig: Figure) -> dict[str, Any]:
    """Everything a message may durably change, in comparable form."""
    return {
        "view_state": fig.view_state(),
        "traces": [
            (
                t.drill_mode,
                t.drill_seq,
                t.shipped_sel is None,
                sorted(t.drill_history),
                t.hidden,
                sorted(t.hidden_categories),
            )
            for t in fig.traces
        ],
    }


def _recording_callbacks(fired: list[str]) -> ChannelCallbacks:
    return ChannelCallbacks(
        on_hover=lambda row: fired.append("hover"),
        on_click=lambda row: fired.append("click"),
        on_brush=lambda brush: fired.append("brush"),
        on_select=lambda sel: fired.append("select"),
        on_view_change=lambda view: fired.append("view_change"),
        on_animation_start=lambda ev: fired.append("animation_start"),
        on_animation_end=lambda ev: fired.append("animation_end"),
    )


_NON_STRING_TYPES = [["view"], {"type": "view"}, 3, 1.5, None, b"pick", ("pick",)]

# A JSON client may send an integer literal of any length; `float()` on one
# raises OverflowError, which is neither TypeError nor ValueError. 10**400 is
# the smallest convenient literal past the f64 ceiling that pytest can still
# render as a test id (`int.__repr__` refuses past 4300 digits).
_HUGE_INT = 10**400

_MALFORMED: list[dict[str, Any]] = [
    *[{"type": kind} for kind in _NON_STRING_TYPES],
    {"type": "view", "x0": 0, "x1": _HUGE_INT},
    {"type": "view", "x0": 0.0, "x1": 1.0, "px": _HUGE_INT},
    {"type": "density_view", "trace": 0, "x0": 0, "x1": _HUGE_INT, "y0": 0, "y1": 1},
    {
        "type": "density_view",
        "trace": 0,
        "x0": 0.0,
        "x1": 1.0,
        "y0": 0.0,
        "y1": 1.0,
        "w": _HUGE_INT,
    },
    {"type": "view_change", "ranges": {"x": [0, _HUGE_INT], "y": [0, 1]}},
    {"type": "view_change", "x0": 0, "x1": _HUGE_INT, "y0": 0, "y1": 1},
    {"type": "select", "x0": 0, "x1": _HUGE_INT, "y0": 0, "y1": 1},
    {"type": "select_polygon", "points": [[0, 0], [1, _HUGE_INT], [2, 2]]},
    {"type": "legend_toggle", "trace": 0, "hidden": True, "category": _HUGE_INT},
    {"type": "pick", "trace": 0, "index": _HUGE_INT},
    {"type": "click", "trace": 0, "index": _HUGE_INT},
    {"type": "view", "x0": 1e-310, "x1": 2e-310},
    {"type": "view", "x0": 0.0, "x1": 1.0, "px": [512]},
    {"type": "density_view", "trace": 0, "x0": 1e-310, "x1": 2e-310, "y0": -1.0, "y1": 1.0},
    {"type": "density_view", "trace": 0, "x0": -1.0, "x1": 1.0, "y0": 1e-320, "y1": 3e-320},
    {
        "type": "density_view",
        "trace": 0,
        "x0": 5e-324,
        "x1": 1e-323,
        "y0": -1.0,
        "y1": 1.0,
        "w": 4096,
        "h": 4096,
    },
    {"type": "density_view", "trace": 0, "x0": 0.0, "x1": 1.0, "y0": 0.0, "y1": 1.0, "w": [512]},
    {"type": "density_view", "trace": [0], "x0": 0.0, "x1": 1.0, "y0": 0.0, "y1": 1.0},
    {"type": "density_view", "trace": 0, "x0": 0.0, "x1": math.nan, "y0": 0.0, "y1": 1.0},
    {"type": "pick", "trace": 0, "index": 10**9},
    {"type": "pick", "trace": 0, "index": -1},
    {"type": "pick", "trace": 0, "index": [1]},
    {"type": "pick", "trace": [0], "index": 1},
    {"type": "pick", "trace": 0, "index": 1, "drill_seq": {"seq": 1}},
    {"type": "click", "trace": 0, "index": 10**9},
    {"type": "click", "trace": 0, "index": [1]},
    {"type": "click", "trace": 99, "index": 0},
    {"type": "legend_toggle", "trace": 0, "hidden": "yes"},
    {"type": "legend_toggle", "trace": 0, "hidden": True, "category": [1]},
    {"type": "legend_toggle", "trace": 0, "hidden": True, "category": 0},
    {"type": "view_change"},
    {"type": "view_change", "ranges": {"x": [1.0, 1.0]}},
    {"type": "view_change", "ranges": {"x": [1.0, 2.0, 3.0]}},
    {"type": "view_change", "ranges": {"x": "wide"}},
    {"type": "view_change", "ranges": {"x": [1.0, math.nan]}},
    {"type": "view_change", "ranges": {"x": [1.0, math.inf]}},
    {"type": "view_change", "x0": 0.0, "x1": 0.0, "y0": 0.0, "y1": 1.0},
    {"type": "view_change", "x0": 0.0, "x1": 1.0, "y0": "low", "y1": 1.0},
    {"type": "select"},
    {"type": "select", "x0": "left", "x1": 1.0, "y0": 0.0, "y1": 1.0},
    {"type": "select", "x0": math.nan, "x1": 1.0, "y0": 0.0, "y1": 1.0},
    {"type": "select_polygon"},
    {"type": "select_polygon", "points": "abc"},
    {"type": "select_polygon", "points": [[0.0, 1.0], [1.0]]},
    {"type": "select_polygon", "points": [[0.0, 1.0], ["a", 2.0]]},
]


@pytest.mark.parametrize("content", _MALFORMED, ids=lambda c: repr(c)[:70])
def test_malformed_message_is_dropped_without_side_effects(content: dict[str, Any]) -> None:
    fig = _density_scatter()
    fig.build_payload()
    before = _snapshot(fig)
    fired: list[str] = []

    reply = handle_message(fig, content, None, callbacks=_recording_callbacks(fired))

    # `pick` answers every well-typed miss with an empty row so the client
    # clears hover; everything else malformed is silence.
    if reply is not None:
        assert reply[0] == {"type": "pick_result", "seq": None, "row": None}
    assert fired == []
    assert _snapshot(fig) == before


@pytest.mark.parametrize("kind", _NON_STRING_TYPES, ids=lambda k: type(k).__name__)
def test_non_string_type_returns_none(kind: Any) -> None:
    # An unhashable `type` used to raise from the animation-kind membership
    # test before any other field was inspected (§1: unknown type → None).
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    fig.build_payload()
    assert handle_message(fig, {"type": kind}) is None


# -- pick/click index bounds (§2 `pick`) --------------------------------------


def _aggregate_figures() -> list[tuple[str, Figure]]:
    rng = np.random.default_rng(0)
    hist = Figure().histogram(rng.normal(size=1_000))
    hexb = Figure().hexbin(rng.normal(size=5_000), rng.normal(size=5_000), gridsize=16)
    return [("histogram", hist), ("hexbin", hexb)]


@pytest.mark.parametrize(
    "label,fig", _aggregate_figures(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_pick_past_readout_rows_replies_null_row(label: str, fig: Figure) -> None:
    # `n_points` advertises the sample count (1000) while the readout columns
    # hold the bin rows (~27): every index in between used to IndexError out
    # of `row_dict`. The contract is `row: null`, never an exception.
    fig.build_payload()
    t = fig.traces[0]
    rows = len(t.x)
    assert rows < t.n_points, f"{label} no longer aggregates; pick another kind"
    fired: list[str] = []
    callbacks = _recording_callbacks(fired)

    for index in (rows, rows + 1, (rows + t.n_points) // 2, t.n_points - 1, t.n_points):
        reply = handle_message(fig, {"type": "pick", "trace": 0, "index": index, "seq": 4}, None)
        assert reply is not None
        assert reply[0] == {"type": "pick_result", "seq": 4, "row": None}
        assert (
            handle_message(fig, {"type": "click", "trace": 0, "index": index}, None, callbacks)
            is None
        )
    assert fired == []

    # The last readable row still resolves — the bound tightened, not vanished.
    reply = handle_message(fig, {"type": "pick", "trace": 0, "index": rows - 1}, None, callbacks)
    assert reply is not None and reply[0]["row"] is not None
    assert reply[0]["row"]["index"] == rows - 1
    assert fired == ["hover"]


def test_pick_keeps_advertised_count_bound_when_columns_are_longer() -> None:
    # Errorbar is the inverse shape: 50 points advertised over 150 segment
    # endpoints. Indices in [n_points, len(x)) stay unpickable, exactly as
    # before — the bound is the smaller of the two counts.
    fig = Figure().errorbar(np.arange(50.0), np.arange(50.0), yerr=0.1)
    fig.build_payload()
    t = fig.traces[0]
    assert len(t.x) > t.n_points
    hit = handle_message(fig, {"type": "pick", "trace": 0, "index": t.n_points - 1})
    miss = handle_message(fig, {"type": "pick", "trace": 0, "index": t.n_points})
    assert hit is not None and hit[0]["row"] is not None
    assert miss is not None and miss[0]["row"] is None


def test_pick_histogram_with_more_bins_than_samples_reads_every_bar() -> None:
    # 5 samples over 20 bars: `n_points` (5) is below the row count, and every
    # bar is a real mark — the bound is the bin rows, not the sample count.
    fig = Figure().histogram(np.array([0.5, 1.5, 4.5, 12.5, 19.5]), bins=20)
    fig.build_payload()
    t = fig.traces[0]
    assert t.kind == "histogram" and len(t.x) == 20 and t.n_points == 5
    hit = handle_message(fig, {"type": "pick", "trace": 0, "index": 15})
    miss = handle_message(fig, {"type": "pick", "trace": 0, "index": 20})
    assert hit is not None and hit[0]["row"] is not None
    assert hit[0]["row"]["index"] == 15
    assert miss is not None and miss[0]["row"] is None


def test_pick_index_error_from_lookup_still_replies_null_row(monkeypatch: Any) -> None:
    # The defensive IndexError path must answer, not drop: a silent drop
    # would leave the client's previous hover row on screen.
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    fig.build_payload()

    def _raise(self: Figure, *args: Any, **kwargs: Any) -> None:
        raise IndexError("column shorter than advertised")

    monkeypatch.setattr(Figure, "pick", _raise)
    fired: list[str] = []
    reply = handle_message(
        fig, {"type": "pick", "trace": 0, "index": 1, "seq": 9}, None, _recording_callbacks(fired)
    )
    assert reply == ({"type": "pick_result", "seq": 9, "row": None}, None)
    assert fired == []
    # `click` has no reply to carry the clear, so it stays a silent no-op.
    assert handle_message(fig, {"type": "click", "trace": 0, "index": 1}, None) is None


def test_pick_heatmap_bound_is_the_grid_not_the_edge_columns() -> None:
    # Grid marks keep only the outer edges in x/y; the readable rows are the
    # cells, so the bound must not collapse to `len(t.x) == 2`.
    fig = Figure().heatmap(np.arange(42.0).reshape(6, 7))
    fig.build_payload()
    last = handle_message(fig, {"type": "pick", "trace": 0, "index": 41})
    past = handle_message(fig, {"type": "pick", "trace": 0, "index": 42})
    assert last is not None and last[0]["row"] == {
        "trace": 0,
        "index": 41,
        "row": 5,
        "col": 6,
        "color_value": 41.0,
    }
    assert past is not None and past[0]["row"] is None


# -- density_view windows below f64 resolution (§2 `density_view`) -----------


@pytest.mark.parametrize(
    "window",
    [
        {"x0": 1e-310, "x1": 2e-310, "y0": -1.0, "y1": 1.0},
        {"x0": -1.0, "x1": 1.0, "y0": 1e-320, "y1": 3e-320},
        {"x0": 5e-324, "x1": 1e-323, "y0": -1.0, "y1": 1.0, "w": 4096, "h": 4096},
    ],
    ids=["x-subnormal", "y-subnormal", "x-min-subnormal-4k"],
)
def test_density_view_subnormal_span_is_dropped_without_drill_mutation(
    window: dict[str, float],
) -> None:
    fig = _density_scatter()
    fig.build_payload()
    before = _snapshot(fig)
    assert handle_message(fig, {"type": "density_view", "trace": 0, **window}) is None
    assert _snapshot(fig) == before


@pytest.mark.parametrize("span", [3e-308, 1e-300, 1e-200, 1e-100, 1e-20, 1e-6])
def test_density_view_tiny_normal_spans_are_served_from_the_raw_window(span: float) -> None:
    # Spans that survive `normalize_window` but out-resolve the drill ladder
    # (`extent / (pad * span)` overflows f64) must fall back to the raw view
    # window instead of raising from `aligned_window`.
    #
    # The window is anchored at 0.0, not at some mid-domain value: 50.0 has an
    # ulp of ~7e-15, so `50.0 + span` collapses back to 50.0 for every span
    # here but the last, and the message would be dropped by the zero-span
    # rule without ever reaching the ladder.
    x0, x1 = 0.0, span
    assert x1 > x0, "span must survive the addition or this case tests nothing"

    calls: list[tuple[float, ...]] = []
    original = lod.aligned_window

    def _spy(*args: float) -> tuple[float, float]:
        calls.append(args)
        return original(*args)

    fig = _density_scatter()
    fig.build_payload()
    with mock.patch.object(lod, "aligned_window", _spy):
        reply = handle_message(
            fig, {"type": "density_view", "trace": 0, "x0": x0, "x1": x1, "y0": 0.0, "y1": 100.0}
        )

    # A reply, not a drop — proof the request reached the drill path rather
    # than dying in validation, which is what made the old anchor vacuous.
    assert reply is not None
    assert calls, "aligned_window was never reached"
    entry = reply[0]["traces"][0]
    assert entry["mode"] == "points"
    assert all(math.isfinite(v) for v in (*entry["x_range"], *entry["y_range"]))
    # The shipped window still contains the requested one (containment is the
    # `aligned_window` contract, including on the pass-through fallbacks).
    assert entry["x_range"][0] <= x0 and entry["x_range"][1] >= x1


def test_normalize_window_rejects_subnormal_spans_only_when_area_is_required() -> None:
    with pytest.raises(ValueError):
        lod.normalize_window(1e-310, 2e-310, -1.0, 1.0)
    with pytest.raises(ValueError):
        lod.normalize_window(-1.0, 1.0, 1e-320, 3e-320)
    # The smallest normal span is the floor, not a rejection.
    lo_x, hi_x, _, _ = lod.normalize_window(0.0, 2.2250738585072014e-308, -1.0, 1.0)
    assert hi_x - lo_x > 0.0
    # Area-free callers (select, view_change) keep accepting anything finite.
    assert lod.normalize_window(1e-310, 2e-310, 0.0, 0.0, require_area=False) == (
        1e-310,
        2e-310,
        0.0,
        0.0,
    )


@pytest.mark.parametrize(
    "lo,hi,extent_lo,extent_hi",
    [
        # The two hardened branches, at pad=1.0: an infinite extent/span
        # quotient, and a finite one whose level still reaches 1024 (where the
        # old `extent / (1 << level)` could not build the divisor).
        (1e-310, 2e-310, -1.0, 1.0),
        (0.0, 3e-308, 0.0, 4.0),
        # Deep-but-representable ladder rungs (levels ~67 and ~865): the
        # ordinary arithmetic, kept as the surrounding coverage.
        (0.0, 1e-320, 0.0, 1e-300),
        (0.0, 1e-10, -1e250, 1e250),
    ],
)
def test_aligned_window_extreme_spans_never_raise_and_contain(
    lo: float, hi: float, extent_lo: float, extent_hi: float
) -> None:
    assert hi > lo, "span must be representable at this offset or the case is vacuous"
    for pad in (1.0, 2.0, 4.0, 8.0):
        a, b = lod.aligned_window(lo, hi, extent_lo, extent_hi, pad)
        assert math.isfinite(a) and math.isfinite(b)
        assert a <= lo and b >= hi


# -- view_change durability (§2 `view_change`, view-state.md §5.1) -----------


def test_view_change_orders_ranges_and_round_trips_into_state_patch() -> None:
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    fig.build_payload()
    seen: list[dict[str, Any]] = []
    callbacks = ChannelCallbacks(on_view_change=seen.append)

    assert (
        handle_message(
            fig,
            {"type": "view_change", "ranges": {"x": [1.5, 1.0], "y": [4.0, 2.0]}},
            None,
            callbacks,
        )
        is None
    )
    state = fig.view_state()
    assert state["ranges"]["x"] == [1.0, 1.5]
    assert state["ranges"]["y"] == [2.0, 4.0]
    assert seen[-1]["ranges"] == {"x": [1.0, 1.5], "y": [2.0, 4.0]}
    assert (seen[-1]["x0"], seen[-1]["x1"], seen[-1]["y0"], seen[-1]["y1"]) == (1.0, 1.5, 2.0, 4.0)

    # Legacy shape, flipped: same ordering rule.
    handle_message(fig, {"type": "view_change", "x0": 9.0, "x1": 3.0, "y0": 1.0, "y1": 0.0})
    assert fig.view_state()["ranges"] == {"x": [3.0, 9.0], "y": [0.0, 1.0]}

    # Whatever the cache holds must feed straight back into a state patch.
    patch = fig.state_patch_message(ranges=fig.view_state()["ranges"])
    assert patch["state"]["ranges"] == {"x": [3.0, 9.0], "y": [0.0, 1.0]}


@pytest.mark.parametrize(
    "content",
    [
        {"type": "view_change", "ranges": {"x": [1.0, 1.0], "y": [0.0, 2.0]}},
        {"type": "view_change", "x0": 1.0, "x1": 1.0, "y0": 2.0, "y1": 1.0},
        {"type": "view_change", "x0": 0.0, "x1": 1.0, "y0": 2.0, "y1": 2.0},
    ],
    ids=["ranges-zero-span", "legacy-zero-span-x", "legacy-zero-span-y"],
)
def test_view_change_zero_span_rejects_the_whole_event(content: dict[str, Any]) -> None:
    # A zero-span axis is what `Figure.state_patch_message` refuses, so the
    # cache must never hold one (view-state.md §5.1 round-trip). The whole
    # event drops — the same rule the `ranges` path already applied.
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    fig.build_payload()
    home = fig.view_state()
    seen: list[dict[str, Any]] = []
    assert handle_message(fig, content, None, ChannelCallbacks(on_view_change=seen.append)) is None
    assert fig.view_state() == home
    assert seen == []
    fig.state_patch_message(ranges=fig.view_state()["ranges"])
