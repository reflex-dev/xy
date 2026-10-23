"""A split fill is one artist, and date units belong to a shared axis group."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize("split", ["mask", "where", "interpolate"])
def test_split_fill_removal_removes_every_polygon(temporal: bool, split: str) -> None:
    fig, ax = plt.subplots()
    x = np.arange("2026-01-01", "2026-01-08", dtype="datetime64[D]") if temporal else np.arange(7)
    options: dict[str, Any] = {}
    y = np.ones(7)
    if split == "mask":
        x = np.ma.array(x, mask=[False, False, False, True, False, False, False])
    elif split == "where":
        options["where"] = [True, True, True, False, True, True, True]
    else:
        y = np.array([-1, 1, -1, -1, -1, 1, -1])
        options.update(where=y > 0, interpolate=True)
    fill = ax.fill_between(x, y, **options)
    other = ax.axhline(0.5)
    assert len([trace for trace in fig._charts()[0].figure().traces if trace.kind == "area"]) == 2

    fill.remove()
    assert fill not in ax.collections
    assert ax._entries == [other._entry]
    ax.fill_between([0.0, 1.0], [1.0, 2.0])
    engine = fig._charts()[0].figure()
    payload, _ = engine.build_payload()
    assert payload["x_axis"]["kind"] == "linear"
    assert payload["x_axis"]["range"] == pytest.approx([-0.05, 1.05])
    assert len([trace for trace in engine.traces if trace.kind == "area"]) == 1


def test_split_fill_mutations_apply_to_the_whole_collection() -> None:
    fig, ax = plt.subplots()
    fill = ax.fill_between(range(5), [1] * 5, where=[True, True, False, True, True])
    fill.set_visible(False)
    assert all(trace.style["opacity"] == 0 for trace in fig._charts()[0].figure().traces)
    fill.set_alpha(0.4)
    fill.set_visible(True)
    fill.set_facecolor("red")
    fill.set_zorder(3)
    traces = fig._charts()[0].figure().traces
    assert len(traces) == 2
    for trace in traces:
        assert trace.style["opacity"] == 0.4
        assert trace.style["color"] == "rgba(255,0,0,1)"
    assert all(entry["_zorder"] == 3 for entry in ax._entries)


@pytest.mark.parametrize("sharex", [False, "all", "row", "col"])
@pytest.mark.parametrize("source", [0, 3])
def test_shared_date_axis_refreshes_after_add_and_remove(sharex: Any, source: int) -> None:
    fig, axes = plt.subplots(2, 2, sharex=sharex)
    for ax in axes.flat:
        ax.axhline(0.5)
    before = fig._charts()
    assert all(chart.figure().build_payload()[0]["x_axis"]["kind"] == "linear" for chart in before)
    group = (
        next(group for group in fig._share_groups(sharex, 4) if source in group)
        if sharex
        else [source]
    )
    fill = axes.flat[source].fill_between(
        np.arange("2026-01-01", "2026-01-06", dtype="datetime64[D]"),
        [1] * 5,
        where=[True, True, False, True, True],
    )
    charts = fig._charts()
    payloads = [chart.figure().build_payload()[0] for chart in charts]
    for index, (chart, payload) in enumerate(zip(charts, payloads, strict=True)):
        assert payload["x_axis"]["kind"] == ("time" if index in group else "linear")
        if index in group:
            assert payload["x_axis"]["range"] == payloads[source]["x_axis"]["range"]
        else:
            assert chart is before[index]
    assert "1.8e12" not in "".join(chart.figure().to_svg() for chart in charts)

    fill.remove()
    axes.flat[source].fill_between([0.0, 1.0], [1.0, 2.0])
    for chart in fig._charts():
        payload, _ = chart.figure().build_payload()
        assert payload["x_axis"]["kind"] == "linear"
        assert max(payload["x_axis"]["range"]) < 2


@pytest.mark.parametrize("scale", ["log", "symlog"])
def test_shared_date_inference_respects_explicit_scales(scale: str) -> None:
    fig, axes = plt.subplots(2, 1, sharex=True)
    axes[1].fill_between(np.array(["2026-01-01", "2026-01-02"], dtype="datetime64[D]"), [1, 2])
    for ax in axes:
        ax.set_xscale(scale)
    assert all(
        chart.figure().build_payload()[0]["x_axis"]["kind"] != "time" for chart in fig._charts()
    )
    for ax in axes:
        ax.set_xscale("linear")
    assert all(
        chart.figure().build_payload()[0]["x_axis"]["kind"] == "time" for chart in fig._charts()
    )


def test_subplot_shared_property_store_inherits_date_units() -> None:
    fig = plt.figure()
    top = fig.add_subplot(211)
    bottom = fig.add_subplot(212, sharex=top)
    fig._charts()
    fill = bottom.fill_between(
        np.array(["2026-01-01", "2026-01-02"], dtype="datetime64[D]"), [1, 2]
    )
    assert all(
        chart.figure().build_payload()[0]["x_axis"]["kind"] == "time" for chart in fig._charts()
    )
    fill.remove()
    assert all(
        chart.figure().build_payload()[0]["x_axis"]["kind"] == "linear" for chart in fig._charts()
    )
