"""Buffer-less mark restyle contract (issue #163)."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import xy
from xy._figure import Figure
from xy.widget import FigureWidget


def _split_bytes(figure: Figure) -> tuple[dict, list[bytes]]:
    spec, buffers = figure.build_payload_split()
    return spec, [bytes(buffer) for buffer in buffers]


def test_scatter_restyle_mutates_constants_without_changing_binary_columns() -> None:
    figure = Figure().scatter(
        np.arange(2_000.0),
        np.arange(2_000.0) ** 2,
        color="#2563eb",
        size=4.0,
    )
    before_spec, before_buffers = _split_bytes(figure)

    message = figure.restyle_message(
        0,
        {
            "fill": "#dc2626",
            "opacity": 0.35,
            "stroke": "#111827",
            "stroke-width": "2px",
        },
        size=9.0,
    )
    after_spec, after_buffers = _split_bytes(figure)

    assert message == {
        "type": "restyle",
        "trace": 0,
        "style": {
            "color": "#dc2626",
            "opacity": 0.35,
            "stroke": "#111827",
            "stroke_width": 2.0,
        },
        "size": 9.0,
    }
    assert "buffers" not in message
    assert after_buffers == before_buffers
    assert after_spec["traces"][0]["color"] == {"mode": "constant", "color": "#dc2626"}
    assert after_spec["traces"][0]["size"] == {"mode": "constant", "size": 9.0}
    assert after_spec["traces"][0]["style"]["opacity"] == 0.35
    # Only small JSON constants move; the column metadata is byte-for-byte stable.
    assert after_spec["columns"] == before_spec["columns"]


def test_line_and_area_restyle_use_existing_strict_css_compiler() -> None:
    figure = Figure().line([0, 1, 2], [1, 2, 1]).area([0, 1, 2], [0, 1, 0])
    line = figure.restyle_message(
        0,
        {"stroke": "rebeccapurple", "stroke-width": 3, "stroke-dasharray": "4 2"},
    )
    area = figure.restyle_message(
        1,
        {"fill": "linear-gradient(to top, #000 0%, transparent 100%)"},
    )

    assert line["style"] == {
        "color": "rebeccapurple",
        "width": 3.0,
        "dash": [4.0, 2.0],
    }
    assert area["style"]["fill"] == {
        "space": "mark",
        "dir": "up",
        "stops": [[0.0, "#000"], [1.0, "transparent"]],
    }


def test_restyle_rejects_geometry_and_data_driven_channel_changes() -> None:
    figure = Figure().scatter(
        np.arange(8.0),
        np.arange(8.0),
        color=np.linspace(0.0, 1.0, 8),
        size=np.arange(8.0) + 2,
    )
    before = copy.deepcopy(figure.traces[0].style)

    with pytest.raises(ValueError, match="unsupported CSS"):
        figure.restyle_message(0, {"curve": "smooth"})
    with pytest.raises(ValueError, match="color is data-driven"):
        figure.restyle_message(0, {"fill": "red"})
    with pytest.raises(ValueError, match="size is data-driven"):
        figure.restyle_message(0, {"opacity": 0.5}, size=8)
    with pytest.raises(ValueError, match="unknown trace"):
        figure.restyle_message(9, {"opacity": 0.5})
    with pytest.raises(ValueError, match="must be an integer"):
        figure.restyle_message(True, {"opacity": 0.5})
    assert figure.traces[0].style == before


def test_restyle_validation_is_transactional() -> None:
    figure = Figure().scatter([0, 1], [0, 1], color="blue", size=4)
    trace = figure.traces[0]
    before_style = copy.deepcopy(trace.style)
    before_color = trace.color_ch.constant
    before_size = trace.size_ch.constant

    with pytest.raises(ValueError, match="positive"):
        figure.restyle_message(0, {"fill": "red", "opacity": 0.2}, size=0)

    assert trace.style == before_style
    assert trace.color_ch.constant == before_color
    assert trace.size_ch.constant == before_size


def test_widget_restyle_sends_json_only_and_patches_reopen_spec() -> None:
    figure = Figure().scatter(np.arange(20.0), np.arange(20.0), color="blue", size=4)
    widget = FigureWidget(figure)
    sent: list[tuple[dict, object]] = []
    widget.send = lambda message, buffers=None: sent.append((message, buffers))
    original_buffers = widget.buffers

    widget.restyle(0, {"fill": "orange", "opacity": 0.4}, size=7)

    assert sent == [
        (
            {
                "type": "restyle",
                "trace": 0,
                "style": {"color": "orange", "opacity": 0.4},
                "size": 7.0,
            },
            None,
        )
    ]
    assert widget.buffers is original_buffers
    trace = widget.spec["traces"][0]
    assert trace["color"]["color"] == "orange"
    assert trace["size"]["size"] == 7.0
    assert trace["style"]["opacity"] == 0.4


def test_chart_restyle_delegates_to_its_live_widget() -> None:
    chart = xy.scatter_chart(xy.scatter([0, 1], [1, 2], size=3))
    widget = chart.widget()
    sent: list[dict] = []
    widget.send = lambda message, buffers=None: sent.append(message)

    chart.restyle(0, {"fill": "purple"}, size=6)

    assert sent == [
        {
            "type": "restyle",
            "trace": 0,
            "style": {"color": "purple"},
            "size": 6.0,
        }
    ]


def test_widget_restyle_patches_density_sample_reopen_state() -> None:
    rng = np.random.default_rng(163)
    figure = Figure().scatter(
        rng.normal(size=20_000),
        rng.normal(size=20_000),
        color="#2563eb",
        size=4,
        density=True,
    )
    widget = FigureWidget(figure)
    widget.send = lambda message, buffers=None: None

    widget.restyle(0, {"fill": "#dc2626"}, size=8)

    density = widget.spec["traces"][0]["density"]
    assert density["color"] == "#dc2626"
    assert density["sample"]["color"]["color"] == "#dc2626"
    assert density["sample"]["size"]["size"] == 8.0
