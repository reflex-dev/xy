"""Widget comm boundary hardening.

These tests exercise the Python message handler headlessly. Rendering coverage
lives in the JS smoke test; here we only assert malformed browser messages do
not escape as exceptions or emit partial state.
"""

from __future__ import annotations

import numpy as np

from fastcharts._figure import DECIMATION_THRESHOLD, Figure
from fastcharts.widget import FigureWidget


def _capturing_widget(fig: Figure, **kwargs):
    widget = FigureWidget(fig, **kwargs)
    sent = []
    widget.send = lambda content, buffers=None: sent.append((content, buffers))
    return widget, sent


def test_widget_drops_malformed_view_messages():
    n = DECIMATION_THRESHOLD + 1
    fig = Figure().line(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))
    widget, sent = _capturing_widget(fig)

    widget._on_custom_msg(None, None, None)
    widget._on_custom_msg(None, {"type": "view", "x0": "left", "x1": 10.0}, None)
    widget._on_custom_msg(None, {"type": "view", "x0": 0.0, "x1": 10.0, "px": "wide"}, None)
    widget._on_custom_msg(None, {"type": "view", "x0": 0.0, "x1": 10.0, "px": True}, None)
    widget._on_custom_msg(None, {"type": "view", "x0": 10.0, "x1": 0.0}, None)

    assert sent == []


def test_widget_drops_malformed_density_pick_and_select_messages():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    select_calls = []
    brush_calls = []
    widget, sent = _capturing_widget(
        fig,
        on_brush=brush_calls.append,
        on_select=select_calls.append,
    )

    widget._on_custom_msg(None, {"type": "density_view", "trace": "bad"}, None)
    widget._on_custom_msg(None, {"type": "pick", "trace": "bad", "index": 0}, None)
    widget._on_custom_msg(None, {"type": "pick", "trace": 0, "index": "bad"}, None)
    widget._on_custom_msg(
        None, {"type": "select", "x0": "left", "x1": 1.0, "y0": 0.0, "y1": 1.0}, None
    )

    assert sent == []
    assert brush_calls == []
    assert select_calls == []


def test_widget_still_emits_valid_pick_results_after_malformed_messages():
    fig = Figure().scatter(np.arange(3.0), np.arange(3.0))
    widget, sent = _capturing_widget(fig)

    widget._on_custom_msg(None, {"type": "pick", "trace": "bad", "index": 0}, None)
    widget._on_custom_msg(None, {"type": "pick", "trace": 0, "index": 1, "seq": 7}, None)

    assert len(sent) == 1
    content, buffers = sent[0]
    assert buffers is None
    assert content["type"] == "pick_result"
    assert content["seq"] == 7
    assert content["row"]["index"] == 1
    assert content["row"]["x"] == 1.0


def test_widget_emits_brush_range_before_selection_callback():
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    brush_calls = []
    select_calls = []
    widget, sent = _capturing_widget(
        fig,
        on_brush=brush_calls.append,
        on_select=select_calls.append,
    )

    widget._on_custom_msg(
        None,
        {"type": "select", "x0": 5.0, "x1": 2.0, "y0": 0.0, "y1": 6.0},
        None,
    )

    assert brush_calls == [{"x0": 2.0, "x1": 5.0, "y0": 0.0, "y1": 6.0}]
    assert len(select_calls) == 1
    np.testing.assert_array_equal(select_calls[0].index, [2, 3, 4, 5])
    assert len(sent) == 1
    content, buffers = sent[0]
    assert content["type"] == "selection"
    assert content["total"] == 4
    assert buffers is not None
