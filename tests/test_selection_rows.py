"""Canonical, bounded row projections for semantic selection events."""

from __future__ import annotations

import json

import numpy as np

from xy._figure import Figure, Selection
from xy.channel import (
    SELECTION_EVENT_ID_LIMIT,
    SELECTION_EVENT_ROW_LIMIT,
    handle_message,
)


def test_selection_rows_match_pick_shape_and_are_deterministic():
    fig = Figure()
    fig.scatter([10.0, 11.0, 12.0], [20.0, 21.0, 22.0], color=["a", "b", "a"])
    fig.scatter([30.0, 31.0], [40.0, 41.0], size=[2.0, 3.0])
    selection = Selection(
        fig,
        {
            1: np.array([1, 0], dtype=np.uint32),
            0: np.array([2, 0], dtype=np.uint32),
        },
    )

    rows = selection.rows()

    assert [(row["trace"], row["index"]) for row in rows] == [(0, 0), (0, 2), (1, 0), (1, 1)]
    assert rows[0] == fig.pick(0, 0)
    assert rows[-1] == fig.pick(1, 1)
    assert rows[0]["color_category"] == "a"
    assert isinstance(rows[-1]["size_value"], float)
    assert selection.rows(2) == rows[:2]
    json.dumps(rows, allow_nan=False)


def test_selection_rows_normalize_nan_and_preserve_axis_kinds():
    fig = Figure().scatter(
        np.array([np.nan, 1.0]),
        np.array([2.0, 3.0]),
        color=np.array([np.nan, 4.0]),
    )
    rows = Selection(fig, {0: np.array([0, 1], dtype=np.uint32)}).rows()

    assert rows[0]["x"] is None
    assert rows[0]["color_value"] is None
    assert rows[0]["x_kind"] == fig.traces[0].x.kind
    assert rows[1] == fig.pick(0, 0)  # shipped row zero maps to canonical row one
    json.dumps(rows, allow_nan=False)


def test_enriched_selection_reply_is_bounded_and_json_safe():
    n = SELECTION_EVENT_ID_LIMIT + 1
    values = np.arange(n, dtype=np.float64)
    fig = Figure().scatter(values, values)

    reply = handle_message(
        fig,
        {
            "type": "select",
            "x0": -1,
            "x1": n,
            "y0": -1,
            "y1": n,
            "include_rows": True,
        },
    )

    assert reply is not None
    message, _ = reply
    assert message["version"] == 1
    assert message["kind"] == "box"
    assert message["mode"] == "replace"
    assert message["bounds"] == {"x0": -1.0, "x1": float(n), "y0": -1.0, "y1": float(n)}
    assert message["total"] == n
    assert len(message["rows"]) == SELECTION_EVENT_ROW_LIMIT
    assert sum(len(group["ids"]) for group in message["canonical_row_ids"]) == (
        SELECTION_EVENT_ID_LIMIT
    )
    assert message["truncated"] is True
    json.dumps(message, allow_nan=False)


def test_polygon_clear_and_legacy_selection_reply_shapes():
    fig = Figure().scatter([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    polygon = [[-1, -1], [3, -1], [1, 2]]

    enriched_reply = handle_message(
        fig, {"type": "select_polygon", "points": polygon, "include_rows": "yes"}
    )
    assert enriched_reply is not None
    enriched, _ = enriched_reply
    assert enriched["kind"] == "lasso"
    assert enriched["polygon"] == [[-1.0, -1.0], [3.0, -1.0], [1.0, 2.0]]
    assert enriched["rows"]

    cleared_reply = handle_message(fig, {"type": "select_clear", "include_rows": True})
    assert cleared_reply is not None
    cleared, buffers = cleared_reply
    assert buffers is None
    assert cleared == {
        "type": "selection",
        "traces": [],
        "total": 0,
        "version": 1,
        "kind": "clear",
        "mode": "replace",
        "canonical_row_ids": [],
        "rows": [],
        "truncated": False,
    }

    legacy_reply = handle_message(fig, {"type": "select", "x0": -1, "x1": 3, "y0": -1, "y1": 3})
    assert legacy_reply is not None
    legacy, _ = legacy_reply
    assert set(legacy) == {"type", "traces", "total"}


def test_capped_ids_are_the_smallest_and_sorted():
    """The cap is applied before boxing, and picks the same ids as before.

    The reply keeps at most `SELECTION_EVENT_ID_LIMIT` canonical ids, and they
    are the numerically smallest ones in ascending order — the shape a
    `sorted(...)[:limit]` over the whole selection produced. That form
    materialized a Python int per *selected* row (~40 bytes each) just to throw
    almost all of them away, so the cap now runs on the array first; this pins
    that the answer did not move.
    """
    n = 5 * SELECTION_EVENT_ID_LIMIT
    values = np.arange(n, dtype=np.float64)
    fig = Figure().scatter(values, values)

    reply = handle_message(
        fig,
        {"type": "select", "x0": -1, "x1": n, "y0": -1, "y1": n, "include_rows": True},
    )
    assert reply is not None
    message, _ = reply
    (group,) = message["canonical_row_ids"]
    ids = group["ids"]
    assert ids == list(range(SELECTION_EVENT_ID_LIMIT))
    assert all(isinstance(v, int) for v in ids)
    assert message["truncated"] is True
    json.dumps(message, allow_nan=False)


def test_id_budget_is_shared_across_traces_in_trace_order():
    """A trace that exhausts the budget leaves later traces with none."""
    half = SELECTION_EVENT_ID_LIMIT
    a = np.arange(half, dtype=np.float64)
    fig = Figure()
    fig.scatter(a, a)
    fig.scatter(a, a)

    reply = handle_message(
        fig,
        {
            "type": "select",
            "x0": -1,
            "x1": half,
            "y0": -1,
            "y1": half,
            "include_rows": True,
        },
    )
    assert reply is not None
    message, _ = reply
    counts = [len(group["ids"]) for group in message["canonical_row_ids"]]
    assert sum(counts) == SELECTION_EVENT_ID_LIMIT
    assert counts[0] == SELECTION_EVENT_ID_LIMIT
    assert message["truncated"] is True


def test_uncapped_selection_reports_every_id_untruncated():
    values = np.arange(8, dtype=np.float64)
    fig = Figure().scatter(values, values)
    reply = handle_message(
        fig, {"type": "select", "x0": -1, "x1": 9, "y0": -1, "y1": 9, "include_rows": True}
    )
    assert reply is not None
    message, _ = reply
    (group,) = message["canonical_row_ids"]
    assert group["ids"] == list(range(8))
    assert message["truncated"] is False
