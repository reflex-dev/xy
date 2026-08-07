"""Matplotlib tick-mark and tick-label sides remain independent."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import pytest

import xy
import xy.pyplot as plt
from xy import _raster, _svg
from xy.config import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[2]
TICK_COLOR = "#123456"
TICK_RGBA = (18, 52, 86, 255)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    plt.close("all")
    yield
    plt.close("all")


def _anscombe_tick_figure():
    fig, ax = plt.subplots(figsize=(3.2, 2.4), dpi=100)
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xticks([0.0, 1.0])
    ax.set_yticks([0.0, 1.0])
    ax.tick_params(
        direction="in",
        top=True,
        right=True,
        length=8,
        width=2,
        color=TICK_COLOR,
    )
    return fig, ax


def _both_label_sides_figure():
    fig, ax = plt.subplots(figsize=(3.2, 2.4), dpi=100)
    ax.plot([0.0, 1.0], [0.0, 1.0])
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xticks([0.0, 1.0], ["x-zero", "x-one"])
    ax.set_yticks([0.0, 1.0], ["y-zero", "y-one"])
    ax.tick_params(labeltop=True, labelright=True)
    return fig, ax


def _rounded_segment(points) -> tuple[tuple[float, float], tuple[float, float]]:
    return tuple((round(float(x), 2), round(float(y), 2)) for x, y in points)


def _expected_tick_segments(
    plot: dict[str, float], length: float
) -> set[tuple[tuple[float, float], ...]]:
    left = plot["x"]
    right = left + plot["w"]
    top = plot["y"]
    bottom = top + plot["h"]
    return {
        ((left, top), (left, top + length)),
        ((right, top), (right, top + length)),
        ((left, bottom - length), (left, bottom)),
        ((right, bottom - length), (right, bottom)),
        ((left, top), (left + length, top)),
        ((left, bottom), (left + length, bottom)),
        ((right - length, top), (right, top)),
        ((right - length, bottom), (right, bottom)),
    }


def test_tick_params_ships_both_tick_sides_without_moving_default_labels() -> None:
    _fig, ax = _anscombe_tick_figure()

    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    assert spec["x_axis"]["tick_sides"] == ["bottom", "top"]
    assert spec["y_axis"]["tick_sides"] == ["left", "right"]
    assert spec["x_axis"]["side"] == "bottom"
    assert spec["y_axis"]["side"] == "left"
    assert spec["x_axis"]["style"]["tick_direction"] == "in"
    assert spec["y_axis"]["style"]["tick_direction"] == "in"

    # Matplotlib's mark-side and label-side switches are independent: moving
    # the marks to the top does not move an explicitly retained bottom label.
    ax.tick_params(
        axis="x",
        bottom=False,
        top=True,
        labelbottom=True,
        labeltop=False,
    )
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    assert spec["x_axis"]["tick_sides"] == ["top"]
    assert spec["x_axis"]["side"] == "bottom"


def test_axis_component_validates_and_canonicalizes_tick_sides() -> None:
    assert xy.x_axis(tick_sides=("top", "bottom", "top")).tick_sides == [
        "bottom",
        "top",
    ]
    assert xy.y_axis(tick_sides=()).tick_sides == []
    with pytest.raises(ValueError, match="tick_sides"):
        xy.x_axis(tick_sides=("left",))


def test_tick_sides_bump_wire_protocol_and_client_in_lockstep() -> None:
    _fig, ax = _anscombe_tick_figure()
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    header = (ROOT / "js" / "src" / "00_header.ts").read_text(encoding="utf-8")
    client = (ROOT / "js" / "src" / "50_chartview.ts").read_text(encoding="utf-8")

    assert spec["x_axis"]["tick_sides"] == ["bottom", "top"]
    assert spec["protocol"] == PROTOCOL_VERSION == 13
    assert f"PROTOCOL = {PROTOCOL_VERSION};" in header
    # The point is that the client reads PROTOCOL from the header, not the exact
    # spelling of the import list — which grows whenever the header gains another
    # shared constant (it now also exports TRACE_GPU_BUFFERS).
    assert "PROTOCOL" in client.split(' from "./00_header";', 1)[0]
    assert "spec.protocol !== PROTOCOL" in client


def test_axis_component_validates_and_canonicalizes_tick_label_sides() -> None:
    assert xy.x_axis(tick_label_sides=("top", "bottom", "top")).tick_label_sides == [
        "bottom",
        "top",
    ]
    assert xy.y_axis(tick_label_sides=()).tick_label_sides == []
    with pytest.raises(ValueError, match="tick_label_sides"):
        xy.x_axis(tick_label_sides=("left",))


def test_tick_params_adds_opposite_labels_without_moving_axis_or_tick_marks() -> None:
    _fig, ax = _both_label_sides_figure()
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()

    assert spec["x_axis"]["tick_label_sides"] == ["bottom", "top"]
    assert spec["y_axis"]["tick_label_sides"] == ["left", "right"]
    assert spec["x_axis"]["side"] == "bottom"
    assert spec["y_axis"]["side"] == "left"
    assert "tick_sides" not in spec["x_axis"]
    assert "tick_sides" not in spec["y_axis"]

    ax.tick_params(axis="x", labelbottom=False)
    ax.tick_params(axis="y", labelleft=False)
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    assert spec["x_axis"]["tick_label_sides"] == ["top"]
    assert spec["y_axis"]["tick_label_sides"] == ["right"]
    assert spec["x_axis"]["side"] == "bottom"
    assert spec["y_axis"]["side"] == "left"

    ax.tick_params(axis="x", labeltop=False)
    ax.tick_params(axis="y", labelright=False)
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    assert spec["x_axis"]["tick_label_sides"] == []
    assert spec["y_axis"]["tick_label_sides"] == []
    assert spec["x_axis"]["tick_label_strategy"] == "off"
    assert spec["y_axis"]["tick_label_strategy"] == "off"


def test_shared_inner_panel_keeps_label_side_visibility_local() -> None:
    fig, axes = plt.subplots(2, 2, sharex=True, sharey=True)
    for index, ax in enumerate(axes.flat):
        ax.plot([0.0, 1.0], [float(index), float(index + 1)])

    figures = [chart.figure() for chart in fig._charts()]
    assert figures[1].axis_options["x"]["tick_label_sides"] == []
    assert figures[1].axis_options["y"]["tick_label_sides"] == []
    assert figures[1].axis_options["x"]["tick_label_strategy"] == "off"
    assert figures[1].axis_options["y"]["tick_label_strategy"] == "off"

    axes[0, 1].tick_params(labeltop=True, labelright=True)
    figures = [chart.figure() for chart in fig._charts()]
    assert figures[1].axis_options["x"]["tick_label_sides"] == ["top"]
    assert figures[1].axis_options["y"]["tick_label_sides"] == ["right"]
    assert figures[1].axis_options["x"]["tick_label_strategy"] is None
    assert figures[1].axis_options["y"]["tick_label_strategy"] is None
    assert figures[0].axis_options["x"]["tick_label_sides"] == []
    assert figures[0].axis_options["y"]["tick_label_sides"] is None


def test_svg_draws_inward_ticks_on_all_four_requested_sides() -> None:
    fig, ax = _anscombe_tick_figure()
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    plot = _svg.layout(spec)[3]

    output = io.BytesIO()
    fig.savefig(output, format="svg", dpi=100)
    root = ET.fromstring(output.getvalue())
    actual = {
        _rounded_segment(
            (
                (node.attrib["x1"], node.attrib["y1"]),
                (node.attrib["x2"], node.attrib["y2"]),
            )
        )
        for node in root.iter()
        if node.tag.endswith("line") and node.attrib.get("stroke") == TICK_COLOR
    }
    length = float(spec["x_axis"]["style"]["tick_length"])
    assert actual == {
        _rounded_segment(segment) for segment in _expected_tick_segments(plot, length)
    }


def test_png_display_list_draws_inward_ticks_on_all_four_requested_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fig, ax = _anscombe_tick_figure()
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    plot = _raster.layout(spec)[3]
    actual: set[tuple[tuple[float, float], ...]] = set()
    original = _raster._Cmd.stroke

    def record(self, points, width, color, closed=False, dash=None, cap="round"):
        if color == TICK_RGBA and width == pytest.approx(2 * 100 / 72):
            actual.add(_rounded_segment(points))
        return original(self, points, width, color, closed, dash, cap)

    monkeypatch.setattr(_raster._Cmd, "stroke", record)
    output = io.BytesIO()
    fig.savefig(output, format="png", dpi=100)
    assert output.getvalue().startswith(b"\x89PNG")
    length = float(spec["x_axis"]["style"]["tick_length"])
    assert actual == {
        _rounded_segment(segment) for segment in _expected_tick_segments(plot, length)
    }


def test_svg_draws_tick_labels_on_both_requested_sides() -> None:
    fig, ax = _both_label_sides_figure()
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    plot = _svg.layout(spec)[3]
    output = io.BytesIO()
    fig.savefig(output, format="svg", dpi=100)
    root = ET.fromstring(output.getvalue())

    positions: dict[str, list[tuple[float, float]]] = {}
    for node in root.iter():
        if not node.tag.endswith("text"):
            continue
        value = "".join(node.itertext())
        if value in {"x-zero", "x-one", "y-zero", "y-one"}:
            positions.setdefault(value, []).append(
                (float(node.attrib["x"]), float(node.attrib["y"]))
            )
    assert set(positions) == {"x-zero", "x-one", "y-zero", "y-one"}
    assert all(len(positions[value]) == 2 for value in positions)
    assert min(y for _x, y in positions["x-zero"]) < plot["y"]
    assert max(y for _x, y in positions["x-zero"]) > plot["y"] + plot["h"]
    assert min(x for x, _y in positions["y-zero"]) < plot["x"]
    assert max(x for x, _y in positions["y-zero"]) > plot["x"] + plot["w"]


def test_png_display_list_draws_tick_labels_on_both_requested_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fig, ax = _both_label_sides_figure()
    spec, _buffers = ax._build_chart(320, 240).figure().build_payload_split()
    plot = _raster.layout(spec)[3]
    positions: dict[str, list[tuple[float, float]]] = {}
    original = _raster._Cmd.text

    def record(self, x, y, anchor, size, color, value, **kwargs):
        if value in {"x-zero", "x-one", "y-zero", "y-one"}:
            positions.setdefault(value, []).append((float(x), float(y)))
        return original(self, x, y, anchor, size, color, value, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", record)
    output = io.BytesIO()
    fig.savefig(output, format="png", dpi=100)
    assert output.getvalue().startswith(b"\x89PNG")
    assert set(positions) == {"x-zero", "x-one", "y-zero", "y-one"}
    assert all(len(positions[value]) == 2 for value in positions)
    assert min(y for _x, y in positions["x-zero"]) < plot["y"]
    assert max(y for _x, y in positions["x-zero"]) > plot["y"] + plot["h"]
    assert min(x for x, _y in positions["y-zero"]) < plot["x"]
    assert max(x for x, _y in positions["y-zero"]) > plot["x"] + plot["w"]


def test_browser_source_consumes_tick_sides_for_every_axis_path() -> None:
    source = (ROOT / "js" / "src" / "50_chartview.ts").read_text(encoding="utf-8")
    assert "_axisTickSides(axis)" in source
    assert "Array.isArray(axis && axis.tick_sides)" in source
    assert source.count("for (const side of this._axisTickSides(") == 4
    assert "_axisTickLabelSides(axis)" in source
    assert "Array.isArray(axis && axis.tick_label_sides)" in source
    assert source.count("for (const side of this._axisTickLabelSides(") == 4
    assert "_axisDefaultSide(axis)" in source
    assert 'return id === "y" ? "left" : "right";' in source
