from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy._figure import Figure


@pytest.fixture(autouse=True)
def _clean_figures():
    plt.close("all")
    yield
    plt.close("all")


def test_direct_rgba_payload_is_four_packed_bytes_per_mark() -> None:
    rgba = np.array([[1.0, 0.0, 0.5, 0.25], [0.0, 1.0, 0.0, 1.0]])
    fig = Figure().scatter([0, 1], [0, 1], color=rgba)

    spec, blob = fig.build_payload()

    paint = spec["traces"][0]["color"]
    column = spec["columns"][paint["buf"]]
    assert paint == {
        "mode": "direct_rgba",
        "components": 4,
        "dtype": "u8",
        "buf": paint["buf"],
        "n": 2,
    }
    assert column["len"] == 8
    packed = np.frombuffer(blob, dtype=np.uint8, count=8, offset=column["byte_offset"])
    np.testing.assert_array_equal(packed.reshape(2, 4), [[255, 0, 128, 64], [0, 255, 0, 255]])


def test_invalid_vector_style_is_atomic() -> None:
    fig = Figure().line([0, 1], [0, 1])
    before = len(fig.traces)

    with pytest.raises(ValueError, match="stroke_width array"):
        fig.scatter([0, 1], [0, 1], stroke_width=[1, 2, 3])

    assert len(fig.traces) == before


def test_matplotlib_set_alpha_gallery_bar_forms_stay_batched() -> None:
    rng = np.random.default_rng(19680801)
    values = rng.standard_normal(20)
    colors = ["green" if value > 0 else "red" for value in values]
    face_alpha = np.abs(values) / np.max(np.abs(values))
    edge_alpha = 1.0 - face_alpha

    _fig, (left, right) = plt.subplots(ncols=2)
    left.bar(np.arange(20), values, color=colors, edgecolor=colors, alpha=0.5)
    right.bar(
        np.arange(20),
        values,
        color=list(zip(colors, face_alpha, strict=True)),
        edgecolor=list(zip(colors, edge_alpha, strict=True)),
    )

    left_traces = left._build_chart(400, 400).figure().traces
    right_traces = right._build_chart(400, 400).figure().traces
    assert len(left_traces) == len(right_traces) == 1
    assert left_traces[0].style["artist_alpha"] == 0.5
    np.testing.assert_allclose(right_traces[0].color_ch.rgba[:, 3], face_alpha)
    np.testing.assert_allclose(right_traces[0].stroke_ch.rgba[:, 3], edge_alpha)


def test_scatter_vectors_and_collection_mutations_rebuild_channels() -> None:
    face = np.array([[1, 0, 0, 0.2], [0, 1, 0, 0.4], [0, 0, 1, 0.6]])
    edge = face[::-1].copy()
    _fig, ax = plt.subplots()
    collection = ax.scatter(
        [0, 1, 2],
        [0, 1, 0],
        c=face,
        edgecolors=edge,
        alpha=[0.3, 0.6, 0.9],
        linewidths=[1, 2, 3],
        s=[20, 40, 80],
    )

    collection.set_alpha([0.25, 0.5, 0.75])
    collection.set_linewidths([2, 3, 4])
    (trace,) = ax._build_chart(640, 480).figure().traces

    np.testing.assert_allclose(trace.color_ch.rgba, face)
    np.testing.assert_allclose(trace.stroke_ch.rgba, edge)
    np.testing.assert_allclose(trace.style_channels["artist_alpha"].values, [0.25, 0.5, 0.75])
    np.testing.assert_allclose(
        trace.style_channels["stroke_width"].values,
        np.array([2, 3, 4]) * ax._point_scale(),
    )


def test_scatter_face_edge_uses_buffer_free_match_fill_mode() -> None:
    _fig, ax = plt.subplots()
    ax.scatter(
        [0, 1],
        [0, 1],
        c=[[1.0, 0.0, 0.0, 0.25], [0.0, 0.0, 1.0, 0.75]],
    )
    core = ax._build_chart(320, 240).figure()
    spec, _blob = core.build_payload()
    assert spec["traces"][0]["stroke"] == {"mode": "match_fill"}


def test_bar_patch_view_updates_parent_channel_without_splitting_trace() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0, 1, 2], [1, 2, 3], color=["red", "green", "blue"])

    assert not bars.patches._cache
    assert len(bars.patches) == len(bars) == 3
    assert bars[1] is list(bars)[1]
    bars[1].set_alpha(0.4)
    bars[2].set_facecolor((1.0, 1.0, 0.0, 0.7))
    bars[0].set_linewidth(2.0)

    (trace,) = ax._build_chart(640, 480).figure().traces
    assert trace.kind == "bar"
    np.testing.assert_allclose(trace.style_channels["artist_alpha"].values, [-1.0, 0.4, -1.0])
    assert trace.color_ch.rgba[2].tolist() == pytest.approx([1.0, 1.0, 0.0, 0.7])
    np.testing.assert_allclose(trace.style_channels["stroke_width"].values, [2.0, 0.0, 0.0])


def test_ten_thousand_differently_styled_bars_are_one_trace() -> None:
    n = 10_000
    rgba = np.empty((n, 4), dtype=np.float64)
    rgba[:, 0] = np.linspace(0.0, 1.0, n)
    rgba[:, 1] = 0.25
    rgba[:, 2] = 1.0 - rgba[:, 0]
    rgba[:, 3] = np.linspace(0.1, 1.0, n)
    fig = Figure().bar(np.arange(n), np.ones(n), color=rgba)

    spec, _blob = fig.build_payload()

    assert len(spec["traces"]) == 1
    paint = spec["traces"][0]["color"]
    assert spec["columns"][paint["buf"]]["len"] == n * 4


def test_streaming_scatter_appends_geometry_and_style_tails_atomically() -> None:
    face = np.array([[1.0, 0.0, 0.0, 0.2], [0.0, 1.0, 0.0, 0.4]])
    edge = face[::-1].copy()
    fig = Figure().scatter(
        [0, 1],
        [0, 1],
        color=face,
        stroke=edge,
        opacity=[0.5, 0.6],
        _artist_alpha=[0.2, 0.8],
        stroke_width=[1.0, 2.0],
        symbol=["circle", "square"],
    )

    fig.append(
        0,
        [2],
        [0],
        color=[[0.0, 0.0, 1.0, 0.6]],
        stroke=[[1.0, 1.0, 0.0, 0.7]],
        opacity=[0.7],
        alpha=[0.9],
        stroke_width=[3.0],
        symbol=["diamond"],
    )
    trace = fig.traces[0]
    assert trace.n_points == 3
    np.testing.assert_allclose(trace.color_ch.rgba[-1], [0.0, 0.0, 1.0, 0.6])
    np.testing.assert_allclose(trace.stroke_ch.rgba[-1], [1.0, 1.0, 0.0, 0.7])
    np.testing.assert_allclose(trace.style_channels["opacity"].values, [0.5, 0.6, 0.7])
    np.testing.assert_array_equal(trace.style_channels["symbol"].values, [0, 1, 2])

    before = trace.n_points
    with pytest.raises(ValueError, match="stroke_width array"):
        fig.append(
            0,
            [3],
            [1],
            color=[[1.0, 0.0, 1.0, 1.0]],
            stroke=[[0.0, 0.0, 0.0, 1.0]],
            opacity=[0.5],
            alpha=[0.5],
            stroke_width=[1.0, 2.0],
            symbol=["circle"],
        )
    assert trace.n_points == before


def test_segments_and_triangle_mesh_ship_direct_instance_styles() -> None:
    rgba = np.array([[1.0, 0.0, 0.0, 0.25], [0.0, 0.0, 1.0, 0.75]])
    fig = Figure().segments(
        [0, 1],
        [0, 0],
        [1, 2],
        [1, 1],
        color=rgba,
        opacity=[0.4, 0.8],
        width=[1.0, 3.0],
    )
    spec, _blob = fig.build_payload()
    segment = spec["traces"][0]
    assert segment["color"]["mode"] == "direct_rgba"
    assert set(segment["channels"]) == {"opacity", "width"}
    assert segment["style"]["opacity"] == 1.0

    mesh = Figure().triangle_mesh(
        [0, 1],
        [0, 0],
        [1, 2],
        [0, 0],
        [0.5, 1.5],
        [1, 1],
        color=rgba,
        stroke=rgba[::-1],
        opacity=[0.5, 1.0],
        stroke_width=[1.0, 2.0],
    )
    mesh_spec, _blob = mesh.build_payload()
    triangle = mesh_spec["traces"][0]
    assert triangle["color"]["mode"] == triangle["stroke"]["mode"] == "direct_rgba"
    assert set(triangle["channels"]) == {"opacity", "stroke_width"}
    assert triangle["style"]["opacity"] == 1.0


def test_multiseries_bar_styles_require_series_item_shapes_atomically() -> None:
    rgba = np.ones((2, 3, 4), dtype=np.float64)
    rgba[0, :, 0] = [0.2, 0.4, 0.6]
    rgba[1, :, 2] = [0.3, 0.5, 0.7]
    fig = Figure().bar(
        [0, 1, 2],
        [[1, 2, 3], [3, 2, 1]],
        color=rgba,
        opacity=[[0.2, 0.4, 0.6], [0.3, 0.5, 0.7]],
        stroke_width=[[1, 2, 3], [3, 2, 1]],
    )
    assert len(fig.traces) == 2
    assert all(trace.color_ch.mode == "direct_rgba" for trace in fig.traces)
    assert all(trace.style["opacity"] == 1.0 for trace in fig.traces)

    before = len(fig.traces)
    with pytest.raises(ValueError, match="numeric paint must have shape"):
        fig.bar([0, 1, 2], [[1, 2, 3], [3, 2, 1]], color=np.ones((3, 4)))
    assert len(fig.traces) == before
