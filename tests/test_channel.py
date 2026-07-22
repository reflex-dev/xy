"""The transport-agnostic dispatcher contract (reflex-integration §3.1).

`tests/test_widget.py` pins the anywidget wrapper path; this file pins
`channel.handle_message` directly — return values instead of captured sends —
so any future transport (the planned Reflex adapter routes) inherits a tested
contract. Deliberately never imports `xy.widget`.
"""

from __future__ import annotations

import numpy as np
import pytest

from xy._figure import DECIMATION_THRESHOLD, Figure, Selection
from xy.channel import ChannelCallbacks, handle_message


def handle(fig, content, **cbs):
    return handle_message(fig, content, None, callbacks=ChannelCallbacks(**cbs))


def test_malformed_view_messages_return_none():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().line(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))

    assert handle(fig, None) is None
    assert handle(fig, "view") is None
    assert handle(fig, {"type": "unknown-kind"}) is None
    assert handle(fig, {"type": "view", "x0": "left", "x1": 10.0}) is None
    assert handle(fig, {"type": "view", "x0": 0.0, "x1": 10.0, "px": "wide"}) is None
    assert handle(fig, {"type": "view", "x0": 0.0, "x1": 10.0, "px": True}) is None
    assert handle(fig, {"type": "view", "x0": 10.0, "x1": 0.0}) is None


def test_valid_view_returns_tier_update():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().line(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))

    reply = handle(fig, {"type": "view", "x0": 100.0, "x1": 5_000.0, "px": 640, "seq": 3})

    assert reply is not None
    msg, buffers = reply
    assert msg["type"] == "tier_update"
    assert msg["seq"] == 3
    assert msg["traces"]
    assert buffers


def test_malformed_density_pick_and_select_return_none_without_callbacks():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    fired = []

    assert handle(fig, {"type": "density_view", "trace": "bad"}) is None
    assert handle(fig, {"type": "pick", "trace": "bad", "index": 0}) is None
    assert handle(fig, {"type": "pick", "trace": 0, "index": "bad"}) is None
    assert (
        handle(
            fig,
            {"type": "select", "x0": "left", "x1": 1.0, "y0": 0.0, "y1": 1.0},
            on_brush=fired.append,
            on_select=fired.append,
        )
        is None
    )
    assert fired == []


def test_valid_pick_replies_after_malformed_input_and_fires_hover():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    hovered = []

    assert handle(fig, {"type": "pick", "trace": "bad", "index": 0}) is None
    reply = handle(fig, {"type": "pick", "trace": 0, "index": 1, "seq": 7}, on_hover=hovered.append)

    assert reply is not None
    msg, buffers = reply
    assert buffers is None  # pick_result ships without a buffers list
    assert msg["type"] == "pick_result"
    assert msg["seq"] == 7
    assert msg["row"]["index"] == 1
    assert msg["row"]["x"] == 1.0
    assert hovered == [msg["row"]]


def test_heatmap_pick_message_replies_without_raising():
    z = np.arange(20 * 20, dtype=float).reshape(20, 20)
    fig = Figure().heatmap(z).contour(z, levels=8)
    hovered = []

    reply = handle(
        fig,
        {"type": "pick", "seq": 7, "trace": 0, "index": 250},
        on_hover=hovered.append,
    )

    assert reply is not None
    msg, buffers = reply
    assert buffers is None
    assert msg["type"] == "pick_result"
    assert msg["seq"] == 7
    assert msg["row"]["color_value"] == z.reshape(-1)[250]
    assert hovered == [msg["row"]]


def test_stale_drill_seq_pick_replies_row_none_without_hover():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    hovered = []

    reply = handle(
        fig,
        {"type": "pick", "trace": 0, "index": 1, "seq": 9, "drill_seq": 42},
        on_hover=hovered.append,
    )

    # The reply still ships (the client clears hover on the empty result),
    # but the Python callback must not fire for a dead coordinate space.
    assert reply is not None
    msg, buffers = reply
    assert msg == {"type": "pick_result", "seq": 9, "row": None}
    assert buffers is None
    assert hovered == []


def test_click_fires_callback_and_returns_none():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    clicked = []

    assert handle(fig, {"type": "click", "trace": 0, "index": 2}, on_click=clicked.append) is None
    assert clicked and clicked[0]["index"] == 2
    # Malformed click: no callback, still None.
    assert (
        handle(fig, {"type": "click", "trace": "bad", "index": 2}, on_click=clicked.append) is None
    )
    assert len(clicked) == 1


def test_animation_lifecycle_callbacks_are_sanitized_and_replyless():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    started = []
    ended = []

    assert (
        handle(
            fig,
            {"type": "animation_start", "phase": "enter", "ignored": object()},
            on_animation_start=started.append,
        )
        is None
    )
    assert (
        handle(
            fig,
            {"type": "animation_end", "phase": "update", "cancelled": True},
            on_animation_end=ended.append,
        )
        is None
    )

    assert started == [{"phase": "enter"}]
    assert ended == [{"phase": "update", "cancelled": True}]


def test_view_change_short_circuits_without_callback():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    views = []

    # No callback: parsed or not, nothing happens.
    assert handle(fig, {"type": "view_change", "x0": "bad"}) is None
    assert handle(fig, {"type": "view_change", "x0": 0.0, "x1": 1.0, "y0": 0.0, "y1": 1.0}) is None
    # Callback present: parsed floats + source.
    reply = handle(
        fig,
        {"type": "view_change", "x0": 0, "x1": 2, "y0": 0, "y1": 3, "source": "wheel"},
        on_view_change=views.append,
    )
    assert reply is None
    assert views == [
        {
            "ranges": {"x": [0.0, 2.0], "y": [0.0, 3.0]},
            "source": "wheel",
            "axes": [],
            "phase": "end",
            "interaction_id": None,
            "x0": 0.0,
            "x1": 2.0,
            "y0": 0.0,
            "y1": 3.0,
        }
    ]
    # Malformed with callback: dropped.
    assert handle(fig, {"type": "view_change", "x0": "bad"}, on_view_change=views.append) is None
    assert (
        handle(
            fig,
            {"type": "view_change", "x0": np.nan, "x1": 2.0, "y0": 0.0, "y1": 3.0},
            on_view_change=views.append,
        )
        is None
    )
    assert (
        handle(
            fig,
            {"type": "view_change", "x0": 2.0, "x1": 0.0, "y0": 3.0, "y1": 0.0},
            on_view_change=views.append,
        )
        is None
    )
    assert len(views) == 2
    assert views[-1] == {
        "ranges": {"x": [0.0, 2.0], "y": [0.0, 3.0]},
        "source": "view",
        "axes": [],
        "phase": "end",
        "interaction_id": None,
        "x0": 0.0,
        "x1": 2.0,
        "y0": 0.0,
        "y1": 3.0,
    }


def test_view_change_accepts_range_map_and_semantic_metadata():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    fig.set_axis("y2")
    views = []

    assert (
        handle(
            fig,
            {
                "type": "view_change",
                "ranges": {"x": [0, 2], "y": [0, 3], "y2": [95, 105]},
                "source": "wheel_zoom",
                "axes": ["x", "y2"],
                "phase": "end",
                "interaction_id": 42,
            },
            on_view_change=views.append,
        )
        is None
    )
    assert views == [
        {
            "ranges": {"x": [0.0, 2.0], "y": [0.0, 3.0], "y2": [95.0, 105.0]},
            "source": "wheel_zoom",
            "axes": ["x", "y2"],
            "phase": "end",
            "interaction_id": 42,
            "x0": 0.0,
            "x1": 2.0,
            "y0": 0.0,
            "y1": 3.0,
        }
    ]


def test_select_fires_brush_before_select_and_returns_selection_reply():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    order = []
    brush_calls = []
    select_calls = []

    reply = handle(
        fig,
        {
            "type": "select",
            "x0": 5.0,
            "x1": 2.0,
            "y0": 0.0,
            "y1": 6.0,
            "seq": "selection:7",
        },
        on_brush=lambda r: (order.append("brush"), brush_calls.append(r)),
        on_select=lambda s: (order.append("select"), select_calls.append(s)),
    )

    assert order == ["brush", "select"]
    assert brush_calls == [{"x0": 2.0, "x1": 5.0, "y0": 0.0, "y1": 6.0}]  # normalized
    np.testing.assert_array_equal(select_calls[0].index, [2, 3, 4, 5])
    assert reply is not None
    msg, buffers = reply
    assert msg["type"] == "selection"
    assert msg["seq"] == "selection:7"
    assert msg["total"] == 4
    assert buffers is not None and len(buffers) == len(msg["traces"])
    assert all(isinstance(buffer, memoryview) for buffer in buffers)
    assert all(isinstance(buffer.obj, np.ndarray) for buffer in buffers)


def test_select_callback_mutation_cannot_rewrite_outgoing_attachment() -> None:
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    callback_rows = []

    def mutate_selection(selection: Selection) -> None:
        callback_rows.append(selection.index.copy())
        selection.per_trace[0][:] = 9

    reply = handle(
        fig,
        {"type": "select", "x0": 2.0, "x1": 5.0, "y0": 0.0, "y1": 6.0},
        on_select=mutate_selection,
    )

    assert reply is not None
    message, buffers = reply
    assert message["total"] == 4
    assert buffers is not None
    np.testing.assert_array_equal(callback_rows[0], [2, 3, 4, 5])
    np.testing.assert_array_equal(np.frombuffer(buffers[0], dtype=np.uint32), [2, 3, 4, 5])


def test_select_without_callback_borrows_mask_owner(monkeypatch) -> None:
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    canonical = np.asarray([2, 3, 4, 5], dtype=np.uint32)
    monkeypatch.setattr(fig, "select_range", lambda *_args: {0: canonical})

    reply = handle(fig, {"type": "select", "x0": 2.0, "x1": 5.0, "y0": 0.0, "y1": 6.0})

    assert reply is not None
    _message, buffers = reply
    assert buffers is not None
    assert buffers[0].obj is canonical


def test_lasso_select_returns_only_points_inside_polygon():
    fig = Figure().scatter(
        np.array([0.0, 1.0, 2.0, 1.0, 4.0]),
        np.array([0.0, 0.5, 0.0, 2.0, 4.0]),
    )
    brush_calls = []
    select_calls = []
    polygon = [[-0.5, -0.5], [2.5, -0.5], [1.0, 1.5]]

    reply = handle(
        fig,
        {"type": "select_polygon", "points": polygon},
        on_brush=brush_calls.append,
        on_select=select_calls.append,
    )

    assert brush_calls == [{"polygon": polygon}]
    np.testing.assert_array_equal(select_calls[0].index, [0, 1, 2])
    assert reply is not None
    msg, buffers = reply
    assert msg["type"] == "selection" and msg["total"] == 3
    np.testing.assert_array_equal(np.frombuffer(buffers[0], dtype=np.uint32), [0, 1, 2])


@pytest.mark.parametrize(
    "points",
    [None, [], [[0, 0], [1, 1]], [[0, 0], [1, 0], [float("nan"), 1]], [[0, 0, 2]]],
)
def test_malformed_lasso_selection_is_dropped(points):
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    assert handle(fig, {"type": "select_polygon", "points": points}) is None


def test_select_wire_mask_is_shipped_space_selection_is_canonical():
    x = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    y = np.array([0.0, 1.0, 2.0, np.nan, 4.0])
    fig = Figure().scatter(x, y)
    select_calls = []

    reply = handle(
        fig,
        {"type": "select", "x0": 1.5, "x1": 4.5, "y0": 1.5, "y1": 4.5},
        on_select=select_calls.append,
    )

    assert reply is not None
    msg, buffers = reply
    # Canonical rows 2 and 4 are selected (rows 1 and 3 carry NaN).
    np.testing.assert_array_equal(select_calls[0].index, [2, 4])
    # The wire mask speaks shipped-vertex positions: NaN rows were dropped at
    # ship time, so canonical rows [0, 2, 4] became shipped [0, 1, 2].
    wire = np.frombuffer(buffers[0], dtype=np.uint32)
    np.testing.assert_array_equal(wire, [1, 2])
    assert isinstance(buffers[0], memoryview)
    assert msg["traces"][0]["count"] == 2


def test_select_clear_returns_empty_selection_and_fires_callback():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    select_calls = []

    reply = handle(fig, {"type": "select_clear"}, on_select=select_calls.append)

    assert reply == ({"type": "selection", "traces": [], "total": 0}, None)
    assert len(select_calls) == 1
    assert isinstance(select_calls[0], Selection)
    assert len(select_calls[0]) == 0


def test_select_clear_echoes_request_identity():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))

    reply = handle(fig, {"type": "select_clear", "seq": "selection:9"})

    assert reply == (
        {"type": "selection", "traces": [], "total": 0, "seq": "selection:9"},
        None,
    )


def test_buffers_argument_is_accepted_and_ignored():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))

    reply = handle_message(fig, {"type": "pick", "trace": 0, "index": 0}, [b"ignored"])

    assert reply is not None
    assert reply[0]["row"]["index"] == 0


def test_callback_exceptions_propagate():
    """'Never raises' covers client-supplied data, not user-callback bugs."""
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))

    def boom(_row):
        raise RuntimeError("user callback bug")

    with pytest.raises(RuntimeError, match="user callback bug"):
        handle(fig, {"type": "pick", "trace": 0, "index": 1}, on_hover=boom)
