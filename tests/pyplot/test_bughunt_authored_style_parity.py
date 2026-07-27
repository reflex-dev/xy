"""Focused regressions for authored bar-error and axis-label styles."""

from __future__ import annotations

import re

import pytest

import xy.pyplot as plt


def teardown_function() -> None:
    plt.close("all")


def _payload(ax):
    return ax._build_chart(640, 480).figure().build_payload()[0]


def _error_trace(ax):
    return next(trace for trace in _payload(ax)["traces"] if trace["kind"] == "errorbar")


def _label_element(svg: str, label: str) -> str:
    match = re.search(rf"<text\b[^>]*>{re.escape(label)}</text>", svg)
    assert match is not None
    return match.group()


def test_bar_direct_error_style_reaches_state_and_payload() -> None:
    _fig, ax = plt.subplots()
    options = {"linewidth": 2.25}

    bars = ax.bar(
        [0, 1],
        [2, 3],
        yerr=[0.2, 0.3],
        ecolor="tab:red",
        capsize=3,
        error_kw=options,
    )

    assert options == {"linewidth": 2.25}
    error = bars.errorbar
    assert error is not None
    assert error._artist._entry["kwargs"] == {
        "yerr": [0.2, 0.3],
        "color": "#d62728",
        "width": 2.25,
        "cap_size": 0.0,
        "opacity": 1.0,
    }
    assert error._cap_artists
    assert all(cap._entry["_mpl_line_marker_path_points"] == 6.0 for cap in error._cap_artists)

    trace = _error_trace(ax)
    assert trace["style"]["color"] == "#d62728"
    assert trace["style"]["width"] == 2.25
    assert trace["style"]["role"] == "y-errorbar"


def test_nested_error_style_wins_without_mutating_the_caller_dict() -> None:
    _fig, ax = plt.subplots()
    options = {
        "ecolor": "tab:blue",
        "capsize": 4,
        "linewidth": 2,
        "elinewidth": 5,
    }
    original = dict(options)

    bars = ax.bar(
        [0, 1],
        [2, 3],
        yerr=0.5,
        ecolor="tab:red",
        capsize=9,
        error_kw=options,
    )

    assert options == original
    error = bars.errorbar
    assert error is not None
    assert error._artist._entry["kwargs"]["color"] == "#1f77b4"
    assert error._artist._entry["kwargs"]["width"] == 5.0
    assert error._cap_artists
    assert all(cap._entry["_mpl_line_marker_path_points"] == 8.0 for cap in error._cap_artists)

    trace = _error_trace(ax)
    assert trace["style"]["color"] == "#1f77b4"
    assert trace["style"]["width"] == 5.0


def test_barh_forwards_error_color_and_elinewidth() -> None:
    _fig, ax = plt.subplots()

    bars = ax.barh(
        [0, 1],
        [2, 3],
        xerr=[0.2, 0.3],
        error_kw={"ecolor": "tab:green", "elinewidth": 3},
    )

    error = bars.errorbar
    assert error is not None
    assert error._artist._entry["kwargs"]["xerr"] == [0.2, 0.3]
    assert error._artist._entry["kwargs"]["color"] == "#2ca02c"
    assert error._artist._entry["kwargs"]["width"] == 3.0

    trace = _error_trace(ax)
    assert trace["style"]["color"] == "#2ca02c"
    assert trace["style"]["width"] == 3.0
    assert trace["style"]["role"] == "x-errorbar"


def test_bar_error_kw_rejects_options_errorbar_cannot_render() -> None:
    _fig, ax = plt.subplots()

    with pytest.raises(TypeError, match="mystery"):
        ax.bar([0], [1], yerr=0.2, error_kw={"mystery": True})


def test_bar_error_container_public_semantics_and_default_legend_label() -> None:
    _fig, ax = plt.subplots()

    bars = ax.bar([0, 1], [2, 3], yerr=[0.2, 0.3], capsize=3, label="bars")

    error = bars.errorbar
    assert error is not None
    assert ax.containers == [error, bars]
    assert error.get_label() == "_nolegend_"
    assert error.has_yerr is True
    assert error.has_xerr is False
    _handles, labels = ax.get_legend_handles_labels()
    assert labels == ["bars"]
    assert "_nolegend_" not in ax._build_chart(640, 480).figure().to_svg()


def test_bar_error_kw_keeps_an_explicit_public_container_label() -> None:
    _fig, ax = plt.subplots()

    bars = ax.bar(
        [0],
        [1],
        yerr=0.2,
        label="bars",
        error_kw={"label": "uncertainty"},
    )

    assert bars.errorbar is not None
    assert bars.errorbar.get_label() == "uncertainty"
    handles, labels = ax.get_legend_handles_labels()
    assert handles == [bars.errorbar, bars]
    assert labels == ["uncertainty", "bars"]


def test_errorbar_container_set_label_none_clears_the_public_label() -> None:
    _fig, ax = plt.subplots()
    container = ax.errorbar([0, 1], [1, 2], yerr=0.1, label="uncertainty")

    container.set_label(None)

    assert container.get_label() is None
    _handles, labels = ax.get_legend_handles_labels()
    assert labels == []


def test_numeric_axis_label_rotation_reaches_both_rendered_axes() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])

    ax.set_xlabel("Elapsed time", rotation=27)
    ax.set_ylabel("Power", rotation=-31)

    assert ax._axis_props("x")["label_angle"] == -27.0
    assert ax._axis_props("y")["label_angle"] == 31.0

    svg = ax._build_chart(640, 480).figure().to_svg()
    assert 'transform="rotate(-27 ' in _label_element(svg, "Elapsed time")
    assert 'transform="rotate(31 ' in _label_element(svg, "Power")


def test_named_axis_label_rotation_and_explicit_none_reset() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])

    ax.set_xlabel("Elapsed time", rotation="vertical")
    ax.set_ylabel("Power", rotation="horizontal")

    assert ax._axis_props("x")["label_angle"] == -90.0
    assert ax._axis_props("y")["label_angle"] == 0.0
    svg = ax._build_chart(640, 480).figure().to_svg()
    assert 'transform="rotate(-90 ' in _label_element(svg, "Elapsed time")
    assert "transform=" not in _label_element(svg, "Power")

    ax.set_xlabel("Elapsed time")
    ax.set_ylabel("Power")

    assert ax._axis_props("x")["label_angle"] == -90.0
    assert ax._axis_props("y")["label_angle"] == 0.0

    ax.set_xlabel("Elapsed time", rotation=None)
    ax.set_ylabel("Power", rotation="vertical")

    assert ax._axis_props("x")["label_angle"] == 0.0
    assert ax._axis_props("y")["label_angle"] == -90.0
    svg = ax._build_chart(640, 480).figure().to_svg()
    assert "transform=" not in _label_element(svg, "Elapsed time")
    assert 'transform="rotate(-90 ' in _label_element(svg, "Power")

    ax.set_ylabel("Power", rotation=None)

    assert ax._axis_props("y")["label_angle"] == 0.0
    svg = ax._build_chart(640, 480).figure().to_svg()
    assert "transform=" not in _label_element(svg, "Power")
