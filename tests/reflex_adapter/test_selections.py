"""Server-side completion of bounded Reflex selection events."""

from __future__ import annotations

import numpy as np
import reflex_xy
from reflex_xy.registry import registry

from xy._figure import Figure


def _event(token: str, selection: dict) -> dict:
    return {"version": 1, "type": "select_end", "token": token, "selection": selection}


def test_resolve_selection_box_and_lasso(_fresh_registry):
    fig = Figure().scatter(np.arange(6.0), np.arange(6.0))
    token = registry.register(fig)

    box = reflex_xy.resolve_selection(
        _event(
            token,
            {
                "kind": "box",
                "data_bounds": {"x0": 1, "x1": 3, "y0": 0, "y1": 4},
                "total_count": 3,
            },
        )
    )
    assert box is not None
    np.testing.assert_array_equal(box.index, [1, 2, 3])

    lasso = reflex_xy.resolve_selection(
        _event(
            token,
            {
                "kind": "lasso",
                "polygon": [[-1, -1], [4, -1], [2, 4]],
                "total_count": 3,
            },
        )
    )
    assert lasso is not None
    np.testing.assert_array_equal(lasso.index, [0, 1, 2])


def test_resolve_selection_returns_none_for_clear_unknown_and_garbage(_fresh_registry):
    assert reflex_xy.resolve_selection(_event("missing", {"kind": "box"})) is None
    assert (
        reflex_xy.resolve_selection(_event("missing", {"kind": "clear", "cleared": True})) is None
    )
    assert reflex_xy.resolve_selection({}) is None
    assert reflex_xy.resolve_selection(None) is None
