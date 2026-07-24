from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def _axis_domain(ax, which: str) -> tuple[float, float]:
    figure = ax._build_chart(640, 480).figure()
    return figure.x_range() if which == "x" else figure.y_range()


def test_categorical_variables_trajectories_keep_every_first_seen_category() -> None:
    activity = ["combing", "drinking", "feeding", "napping", "playing", "washing"]
    dog = ["happy", "happy", "happy", "happy", "bored", "bored"]
    cat = ["bored", "happy", "bored", "bored", "happy", "bored"]

    _fig, ax = plt.subplots()
    ax.plot(activity, dog, label="dog")
    ax.plot(activity, cat, label="cat")

    assert ax.get_xlim() == pytest.approx((-0.25, 5.25))
    assert ax.get_ylim() == pytest.approx((-0.05, 1.05))
    assert _axis_domain(ax, "x") == pytest.approx(ax.get_xlim())
    assert _axis_domain(ax, "y") == pytest.approx(ax.get_ylim())

    traces = ax._build_chart(640, 480).figure().traces
    np.testing.assert_allclose(traces[0].x.values, np.arange(6))
    np.testing.assert_allclose(traces[1].x.values, np.arange(6))
    np.testing.assert_allclose(traces[0].y.values, [0, 0, 0, 0, 1, 1])
    np.testing.assert_allclose(traces[1].y.values, [1, 0, 1, 1, 0, 1])


def test_categorical_scatter_and_line_autoscale_to_the_shared_category_union() -> None:
    names = ["apple", "orange", "lemon", "lime"]
    values = [10, 15, 5, 20]

    _fig, ax = plt.subplots()
    ax.scatter(names, values)
    ax.plot(list(reversed(names)), list(reversed(values)))

    assert ax.get_xlim() == pytest.approx((-0.15, 3.15))
    assert _axis_domain(ax, "x") == pytest.approx((-0.15, 3.15))
    assert ax._build_chart(640, 480).figure()._axis_categories["x"] == names


def test_bar_patch_labels_make_individual_colored_legend_entries() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar(
        ["apple", "blueberry", "cherry", "orange"],
        [40, 100, 30, 55],
        label=["red", "blue", "_red", "orange"],
        color=["tab:red", "tab:blue", "tab:red", "tab:orange"],
    )
    ax.legend(title="Fruit color")

    handles, labels = ax.get_legend_handles_labels()
    assert labels == ["red", "blue", "orange"]
    assert handles == [bars[0], bars[1], bars[3]]

    spec, _blob = ax._build_chart(640, 480).figure().build_payload()
    assert spec["traces"][0]["n_marks"] == 4
    assert [
        (trace["name"], trace["style"]["color"], trace["n_marks"]) for trace in spec["traces"][1:]
    ] == [
        ("red", "rgba(214,39,40,1)", 0),
        ("blue", "rgba(31,119,180,1)", 0),
        ("orange", "rgba(255,127,14,1)", 0),
    ]


def test_bar_patch_labels_validate_against_the_bar_count() -> None:
    _fig, ax = plt.subplots()

    with pytest.raises(ValueError, match=r"number of labels \(1\).*number of bars \(2\)"):
        ax.bar(["apple", "orange"], [1, 2], label=["only one"])


def test_barh_gallery_width_vector_remains_bar_value_geometry() -> None:
    people = ("Tom", "Dick", "Harry", "Slim", "Jim")
    performance = [5, 7, 6, 4, 9]

    _fig, ax = plt.subplots()
    ax.barh(people, performance, xerr=[0.2, 0.4, 0.3, 0.6, 0.2], align="center")

    bar_trace = ax._build_chart(640, 480).figure().traces[0]
    np.testing.assert_allclose(bar_trace.x1.values - bar_trace.x0.values, performance)
    assert ax.get_xlim() == pytest.approx((0.0, 9.45))
