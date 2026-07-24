from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def test_hist_patch_styles_apply_per_dataset() -> None:
    _fig, ax = plt.subplots()
    values = np.arange(18.0).reshape(6, 3)

    _counts, _edges, containers = ax.hist(
        values,
        bins=3,
        facecolor=["red", "green", "blue"],
        edgecolor=["black", "gray", "white"],
        linewidth=[1, 2, 3],
    )

    assert len(containers) == 3
    assert [entry["kwargs"]["stroke_width"] for entry in ax._entries] == [1.0, 2.0, 3.0]
    assert [entry["kwargs"]["color"] for entry in ax._entries] == [
        "red",
        "green",
        "blue",
    ]


def test_hist_fill_false_is_unfilled_and_scalar_input_is_one_dataset() -> None:
    _fig, ax = plt.subplots()

    counts, _edges, container = ax.hist(
        2.0, bins=2, fill=False, facecolor="red", edgecolor="blue", linewidth=3
    )

    assert counts.shape == (2,)
    assert len(container) == 2
    entry = ax._entries[-1]
    assert entry["kwargs"]["color"] == "transparent"
    assert entry["kwargs"]["stroke"] == "blue"
    assert entry["kwargs"]["stroke_width"] == 3.0


def test_hist_step_fill_and_linewidth_override_histtype_defaults() -> None:
    _fig, ax = plt.subplots()
    ax.hist([0, 1, 2], bins=2, histtype="step", fill=True, facecolor="green", linewidth=4)
    ax.hist([0, 1, 2], bins=2, histtype="stepfilled", fill=False, linewidth=5)

    filled, unfilled = ax._entries
    assert filled["factory"] == "area"
    assert filled["kwargs"]["color"] == "green"
    assert filled["kwargs"]["line_color"] == "#1f77b4"
    assert unfilled["factory"] == "stairs"
    assert unfilled["kwargs"]["color"] == "black"
    assert unfilled["kwargs"]["width"] == 5.0


def test_hist_dataset_style_lengths_must_match_dataset_count() -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(ValueError, match="sequence must have length 2"):
        ax.hist([[0, 1], [2, 3]], bins=2, linewidth=[1, 2, 3])


def test_errorbar_forwards_marker_size_and_linestyle_to_data_line_only() -> None:
    _fig, ax = plt.subplots()
    container = ax.errorbar(
        [0, 1],
        [1, 2],
        yerr=0.1,
        marker="o",
        markersize=8,
        linestyle="dotted",
    )

    assert container.lines[0] is not None
    assert [entry["kind"] for entry in ax._entries] == ["@mark", "line", "scatter"]
    line, markers = ax._entries[1:]
    assert line["kwargs"]["dash"]
    assert markers["kwargs"]["symbol"] == "circle"
    assert markers["kwargs"]["size"] > 8


def test_errorbar_fmt_none_accepts_marker_keywords_without_data_line() -> None:
    _fig, ax = plt.subplots()
    container = ax.errorbar([0, 1], [1, 2], yerr=0.1, fmt="none", marker="o", markersize=8)

    assert container.lines[0] is None
    assert len(ax._entries) == 1


def test_errorbar_uses_matplotlib_default_caps_width_and_limit_marker_size() -> None:
    _fig, ax = plt.subplots()
    ax.errorbar([1], [3], yerr=[0.5], lolims=True, fmt="none")

    errorbar, marker = ax._entries
    assert errorbar["kwargs"]["cap_size"] == plt.rcParams["errorbar.capsize"] == 0.0
    assert errorbar["kwargs"]["width"] == plt.rcParams["lines.linewidth"] == 1.5
    assert marker["kwargs"]["size"] == pytest.approx(
        plt.rcParams["lines.markersize"] * plt.rcParams["figure.dpi"] / 72.0
    )


def test_errorbar_limit_flags_render_directional_endpoint_markers() -> None:
    _fig, ax = plt.subplots()
    ax.errorbar(
        [1, 2],
        [3, 4],
        xerr=[0.2, 0.4],
        yerr=[0.5, 0.6],
        lolims=[True, False],
        uplims=[False, True],
        xlolims=[False, True],
        xuplims=[True, False],
        fmt="none",
    )

    marker_entries = [entry for entry in ax._entries if entry["kind"] == "scatter"]
    assert {entry["kwargs"]["symbol"] for entry in marker_entries} == {
        "triangle",
        "triangle_down",
        "triangle_left",
        "triangle_right",
    }
    points = {
        entry["kwargs"]["symbol"]: (
            np.asarray(entry["x"]).tolist(),
            np.asarray(entry["y"]).tolist(),
        )
        for entry in marker_entries
    }
    assert points["triangle"] == ([1], [3.5])
    assert points["triangle_down"] == ([2], [3.4])
    assert points["triangle_right"] == ([2.4], [4])
    assert points["triangle_left"] == ([0.8], [3])
