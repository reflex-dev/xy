"""Kernel-side contract of the unified view-state layer.

spec/design/view-state.md: the §2 state-document boundary rules as enforced by
the Python message builders, the §5.1 eventually-consistent `view_state()`
cache fed by the channel dispatcher, the §5.1 rows-selection wire shape, the
shipped `on_brush`-before-`on_select` ordering for programmatic geometric
selects, and the §4 `history` interaction switch. Client-side behavior
(round-trip, clamps, the history stack itself) is probed in
test_view_state_client.py.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import xy
from xy.channel import ChannelCallbacks, handle_message


def _figure(**chart_kwargs):
    chart = xy.scatter_chart(
        xy.scatter(np.arange(10.0), np.arange(10.0)),
        **chart_kwargs,
    )
    return chart.figure()


def _dual_axis_figure():
    chart = xy.scatter_chart(
        xy.scatter(np.arange(10.0), np.arange(10.0)),
        xy.line(x=[0.0, 9.0], y=[100.0, 120.0], y_axis="y2"),
        xy.y_axis(id="y2", side="right"),
    )
    return chart.figure()


# -- state_patch construction (§2 boundary rules) ---------------------------


def test_state_patch_message_shape() -> None:
    fig = _figure()
    msg = fig.state_patch_message(ranges={"x": (0, 5)})
    assert msg == {
        "type": "state_patch",
        "state": {"v": 1, "ranges": {"x": [0.0, 5.0]}},
        "animate": True,
        "history": True,
    }


def test_state_patch_is_partial() -> None:
    # Merge-patch semantics: an absent axis is absent from the wire document,
    # not defaulted — the client leaves it alone.
    fig = _dual_axis_figure()
    msg = fig.state_patch_message(ranges={"y2": (99.0, 121.0)}, animate=False, history=False)
    assert msg["state"]["ranges"] == {"y2": [99.0, 121.0]}
    assert set(msg["state"]) == {"v", "ranges"}
    assert msg["animate"] is False
    assert msg["history"] is False


def test_state_patch_rejects_unknown_axis() -> None:
    fig = _figure()
    with pytest.raises(ValueError, match="unknown axis"):
        fig.state_patch_message(ranges={"y2": (0, 1)})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_state_patch_rejects_non_finite(bad: float) -> None:
    # Like standalone HTML export, NaN/infinity are rejected at the boundary,
    # never coerced (§2).
    fig = _figure()
    with pytest.raises(ValueError, match="finite"):
        fig.state_patch_message(ranges={"x": (0.0, bad)})


def test_state_patch_rejects_empty_range() -> None:
    fig = _figure()
    with pytest.raises(ValueError):
        fig.state_patch_message(ranges={"x": (2.0, 2.0)})
    with pytest.raises(ValueError):
        fig.state_patch_message(ranges={"x": (1.0,)})
    with pytest.raises(ValueError):
        fig.state_patch_message()


def test_state_patch_selection_forms() -> None:
    fig = _figure()
    cleared = fig.state_patch_message(selection=None)
    assert cleared["state"] == {"v": 1, "selection": None}
    sel = fig._validated_state_selection(range=(0, 4, 1, 5))
    assert sel == {"range": {"x0": 0.0, "x1": 4.0, "y0": 1.0, "y1": 5.0}}
    assert sel == fig._validated_state_selection(range={"x0": 0, "x1": 4, "y0": 1, "y1": 5})
    poly = fig._validated_state_selection(polygon=[(0, 0), (4, 0), (2, 5)])
    assert poly == {"polygon": [[0.0, 0.0], [4.0, 0.0], [2.0, 5.0]]}
    with pytest.raises(ValueError):
        fig._validated_state_selection(range=(0, 1, 2, 3), polygon=[(0, 0)] * 3)
    with pytest.raises(ValueError):
        fig._validated_state_selection(polygon=[(0, 0), (1, 1)])
    with pytest.raises(ValueError):
        fig._validated_state_selection(range=(0, math.nan, 1, 2))


# -- view_nav (§8) -----------------------------------------------------------


def test_view_nav_message() -> None:
    fig = _dual_axis_figure()
    assert fig.view_nav_message() == {"type": "view_nav", "op": "reset"}
    assert fig.view_nav_message(("y2",)) == {
        "type": "view_nav",
        "op": "reset",
        "axes": ["y2"],
    }
    with pytest.raises(ValueError):
        fig.view_nav_message(("nope",))


# -- selection_rows (§5.1) ---------------------------------------------------


def test_selection_rows_message_ships_mask_buffers() -> None:
    fig = _figure()
    msg, buffers = fig.selection_rows_message({0: [1, 3, 5]})
    assert msg["type"] == "selection_rows"
    assert msg["total"] == 3
    (entry,) = msg["traces"]
    assert entry["id"] == 0 and entry["buf"] == 0
    # Same buffers the gesture selection path ships: shipped vertex indices.
    expected = fig.to_shipped_indices(0, np.asarray([1, 3, 5]))
    assert buffers[0] == expected.tobytes()


def test_selection_rows_message_bare_array_is_trace_zero() -> None:
    fig = _figure()
    msg, _buffers = fig.selection_rows_message([2, 4])
    assert msg["traces"][0]["id"] == 0
    assert msg["total"] == 2


def test_selection_rows_message_rejects_unknown_trace() -> None:
    fig = _figure()
    with pytest.raises(ValueError, match="unknown trace"):
        fig.selection_rows_message({7: [0]})
    with pytest.raises(ValueError):
        fig.selection_rows_message(None)


@pytest.mark.parametrize(
    "bad",
    [
        [-1],  # would wrap to 4294967295 in the uint32 wire encoding
        [0, 99],  # out of range for a 10-row trace
        [0.5],  # non-integral
        [float("nan")],
        [True, False],  # boolean masks are not index lists
        ["a"],  # non-numeric
    ],
)
def test_selection_rows_message_rejects_invalid_indices(bad: list) -> None:
    fig = _figure()
    with pytest.raises(ValueError):
        fig.selection_rows_message({0: bad})


def test_selection_rows_message_dedupes_and_counts_validated_rows() -> None:
    # `total` reports validated unique canonical rows, not the raw request
    # length — [3, 3, 1] is two selected rows, shipped once each.
    fig = _figure()
    msg, buffers = fig.selection_rows_message({0: [3, 3, 1]})
    assert msg["total"] == 2
    assert msg["traces"][0]["count"] == 2
    expected = fig.to_shipped_indices(0, np.asarray([1, 3]))
    assert buffers[0] == expected.tobytes()


def test_selection_rows_message_accepts_integral_floats_and_empty() -> None:
    fig = _figure()
    msg, _buffers = fig.selection_rows_message({0: np.asarray([2.0, 4.0])})
    assert msg["total"] == 2
    msg, buffers = fig.selection_rows_message({0: []})
    assert msg["total"] == 0
    assert buffers[0] == b""


# -- view_state cache (§5.1: evented, no round-trip) -------------------------


def test_view_state_starts_at_home_ranges() -> None:
    fig = _figure()
    state = fig.view_state()
    assert state["v"] == 1
    assert state["selection"] is None
    assert set(state["ranges"]) == {"x", "y"}
    for pair in state["ranges"].values():
        assert len(pair) == 2 and all(math.isfinite(v) for v in pair)


def test_view_state_updates_from_view_events_without_callback() -> None:
    # The cache is fed by the event stream itself — registering a Python
    # callback must not be a precondition (end-phase events always ship).
    fig = _figure()
    reply = handle_message(
        fig,
        {"type": "view_change", "ranges": {"x": [2.0, 4.0]}, "source": "pan_drag", "phase": "end"},
    )
    assert reply is None
    state = fig.view_state()
    assert state["ranges"]["x"] == [2.0, 4.0]
    # Untouched axes keep their last known (home) value: merge, not replace.
    assert state["ranges"]["y"] != [2.0, 4.0]


def test_view_state_ignores_malformed_view_events() -> None:
    fig = _figure()
    home = fig.view_state()["ranges"]
    handle_message(fig, {"type": "view_change", "ranges": {"x": [1.0, math.nan]}})
    assert fig.view_state()["ranges"] == home


def test_view_state_tracks_selection_lifecycle() -> None:
    fig = _figure()
    handle_message(fig, {"type": "select", "x0": 1.0, "x1": 4.0, "y0": 1.0, "y1": 4.0})
    assert fig.view_state()["selection"] == {"range": {"x0": 1.0, "x1": 4.0, "y0": 1.0, "y1": 4.0}}
    handle_message(
        fig,
        {"type": "select_polygon", "points": [[0.0, 0.0], [5.0, 0.0], [2.0, 5.0]]},
    )
    assert fig.view_state()["selection"] == {"polygon": [[0.0, 0.0], [5.0, 0.0], [2.0, 5.0]]}
    handle_message(fig, {"type": "select_clear"})
    assert fig.view_state()["selection"] is None


def test_view_state_reports_rows_marker_not_indices() -> None:
    # §2: an arbitrary per-trace index set can be arbitrarily large; the
    # cache records only the opaque marker.
    pytest.importorskip("anywidget")
    from xy.widget import FigureWidget

    fig = _figure()
    widget = FigureWidget(fig)
    sent: list[tuple[dict, list]] = []
    widget.send = lambda msg, buffers=None: sent.append((msg, buffers))
    widget.select(rows={0: [1, 2]})
    assert fig.view_state()["selection"] == {"rows": True}
    assert sent[0][0]["type"] == "selection_rows"
    assert sent[0][1] is not None


# -- ordering invariant (§9: programmatic geometric selects) -----------------


def test_programmatic_geometric_select_orders_brush_before_select() -> None:
    # A programmatic geometric select ships the geometry to the client, which
    # resolves it exactly like a gesture — so the kernel-side ordering
    # invariant covers the programmatic path too. Probe the dispatcher.
    fig = _figure()
    order: list[str] = []
    callbacks = ChannelCallbacks(
        on_brush=lambda brush: order.append("brush"),
        on_select=lambda selection: order.append("select"),
    )
    handle_message(
        fig,
        {"type": "select", "x0": 0.0, "x1": 9.0, "y0": 0.0, "y1": 9.0},
        callbacks=callbacks,
    )
    assert order == ["brush", "select"]


# -- widget surface (§5.1) ---------------------------------------------------


def test_widget_set_view_sends_state_patch() -> None:
    pytest.importorskip("anywidget")
    from xy.widget import FigureWidget

    fig = _figure()
    widget = FigureWidget(fig)
    sent: list[dict] = []
    widget.send = lambda msg, buffers=None: sent.append(msg)
    widget.set_view({"x": (1.0, 3.0)}, animate=False, history=False)
    widget.reset_view()
    widget.select(range=(0, 1, 0, 1))
    widget.clear_selection()
    kinds = [msg["type"] for msg in sent]
    assert kinds == ["state_patch", "view_nav", "state_patch", "state_patch"]
    assert sent[0]["state"]["ranges"] == {"x": [1.0, 3.0]}
    assert sent[0]["animate"] is False and sent[0]["history"] is False
    assert sent[2]["state"]["selection"]["range"] == {
        "x0": 0.0,
        "x1": 1.0,
        "y0": 0.0,
        "y1": 1.0,
    }
    assert sent[3]["state"]["selection"] is None
    with pytest.raises(ValueError):
        widget.select()
    with pytest.raises(ValueError):
        widget.select(rows=[0], range=(0, 1, 0, 1))


def test_chart_delegates_view_state_api() -> None:
    pytest.importorskip("anywidget")
    # `select=` (the interaction switch kwarg) must not shadow the
    # programmatic `Chart.select()` method — a real instance-attribute
    # collision this test pins down.
    chart = xy.scatter_chart(xy.scatter(np.arange(4.0), np.arange(4.0)), select=True)
    widget = chart.widget()
    sent: list[dict] = []
    widget.send = lambda msg, buffers=None: sent.append(msg)
    chart.set_view({"x": (0.0, 2.0)})
    chart.reset_view(("x",))
    chart.select(range=(0, 1, 0, 1))
    chart.clear_selection()
    assert [msg["type"] for msg in sent] == [
        "state_patch",
        "view_nav",
        "state_patch",
        "state_patch",
    ]
    assert chart.figure()._interaction_spec()["select"] is True
    assert chart.view_state()["v"] == 1


# -- history switch (§4) -----------------------------------------------------


def test_interaction_history_switch_serializes() -> None:
    fig = _figure()
    assert "history" not in fig._interaction_spec()  # unset stays absent
    disabled = xy.scatter_chart(
        xy.scatter(np.arange(3.0), np.arange(3.0)),
        xy.interaction_config(history=False),
    ).figure()
    assert disabled._interaction_spec()["history"] is False
    enabled = xy.scatter_chart(
        xy.scatter(np.arange(3.0), np.arange(3.0)),
        xy.interaction_config(history=True),
    ).figure()
    assert enabled._interaction_spec()["history"] is True
