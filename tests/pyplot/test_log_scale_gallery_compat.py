"""Source-backed coverage for Matplotlib's scales/log_demo.py."""

from __future__ import annotations

import re

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _raster, _svg


def teardown_function() -> None:
    plt.close("all")


def _payload(ax):
    chart = ax._build_chart(640, 480)
    return chart.figure().build_payload()


def test_log_demo_materializes_minor_ticks_and_independent_grid_style() -> None:
    _fig, ax = plt.subplots()
    ax.semilogx(np.logspace(-2, 1, 100), np.ones(100))
    ax.grid()
    ax.grid(which="minor", color="0.9")

    spec, _blob = _payload(ax)
    x_axis = spec["axes"]["x"]

    assert x_axis["tick_values"] == [0.01, 0.1, 1.0, 10.0]
    assert len(x_axis["minor_tick_values"]) == 26
    assert x_axis["style"]["grid_color"] != x_axis["minor_style"]["grid_color"]
    assert x_axis["minor_style"]["grid_color"] == "rgb(230,230,230)"


def test_log_demo_minor_grid_and_ticks_reach_svg_and_raster() -> None:
    _fig, ax = plt.subplots()
    ax.loglog([1, 10, 100, 1000], [5, 50, 500, 5000], "o--")
    ax.grid()
    ax.grid(which="minor", color="0.9")
    spec, blob = _payload(ax)

    svg = _svg.render_svg(spec, blob)
    expected = sum(len(spec["axes"][axis_id]["minor_tick_values"]) for axis_id in ("x", "y"))
    assert len(re.findall(r'data-xy-grid="minor"', svg)) == expected
    assert len(re.findall(r'data-xy-tick="minor"', svg)) == expected

    image = _raster.render_raster(spec, blob, scale=1)
    assert image.shape == (480, 640, 4)
    # A visible light-gray minor grid adds non-white, non-major grid pixels.
    assert np.any(np.all(image[:, :, :3] == np.array([230, 230, 230]), axis=2))


def test_log_demo_base_two_keeps_explicit_labels() -> None:
    _fig, ax = plt.subplots()
    ax.bar(["L1", "L2", "L3", "RAM", "SSD"], [32, 1_000, 32_000, 16_000_000, 512_000_000])
    ax.set_yscale("log", base=2)
    ax.set_yticks([1, 2**10, 2**20, 2**30], labels=["kB", "MB", "GB", "TB"])

    spec, _blob = _payload(ax)
    y_axis = spec["axes"]["y"]
    assert y_axis["tick_values"] == [1.0, 1024.0, 1048576.0, 1073741824.0]
    assert y_axis["tick_labels"] == ["kB", "MB", "GB", "TB"]


def test_log_demo_nonpositive_mask_and_clip_diverge_in_static_scale() -> None:
    masked = _svg._Scale(
        {"kind": "linear", "scale": "log", "range": [0.1, 100], "nonpositive": "mask"},
        0,
        100,
    )
    clipped = _svg._Scale(
        {"kind": "linear", "scale": "log", "range": [0.1, 100], "nonpositive": "clip"},
        0,
        100,
    )

    assert np.isnan(masked(-1.0))
    assert np.isfinite(clipped(-1.0))
    assert clipped(-1.0) < 0


def test_log_demo_errorbar_caps_are_points_not_data_units() -> None:
    _fig, ax = plt.subplots(figsize=(6, 3))
    x = np.linspace(0.0, 2.0, 10)
    y = 10**x
    ax.set_yscale("log", nonpositive="mask")
    ax.errorbar(x, y, yerr=1.75 + 0.75 * y, fmt="o", capsize=5)

    # A 5-point cap must not expand a 0..2 data axis to roughly -5..5.
    lo, hi = ax.get_xlim()
    assert lo > -0.2
    assert hi < 2.2


def test_log_demo_constrained_suptitle_keeps_a_separate_title_row() -> None:
    fig, axes = plt.subplots(1, 2, layout="constrained", figsize=(6, 3))
    before = axes[0].get_position(original=True).height

    fig.suptitle("errorbars going negative")

    after = axes[0].get_position(original=True).height
    assert before - after == pytest.approx(0.1)
