"""Static regressions for Matplotlib's line and collection color defaults."""

from __future__ import annotations

import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def test_fill_family_has_an_independent_patch_cycle_from_plot() -> None:
    _fig, ax = plt.subplots()
    ax.set_prop_cycle(color=["magenta", "cyan"])

    first_line = ax.plot([0, 1], [0, 1])[0]
    first_fill = ax.fill_between([0, 1], [0, 1])
    second_fill = ax.fill_between([0, 1], [1, 2])
    second_line = ax.plot([0, 1], [2, 3])[0]

    assert first_line.get_color() == "magenta"
    assert first_fill._entry["kwargs"]["color"] == "magenta"
    assert second_fill._entry["kwargs"]["color"] == "cyan"
    assert second_line.get_color() == "cyan"


def test_fill_and_fill_betweenx_share_the_patch_cycle() -> None:
    _fig, ax = plt.subplots()
    ax.set_prop_cycle(color=["red", "blue"])

    polygon = ax.fill([0, 1, 0], [0, 0, 1])[0]
    band = ax.fill_betweenx([0, 1], [0, 0], [1, 1])

    assert polygon._entry["kwargs"]["color"] == "red"
    assert band._entry["kwargs"]["color"] == "blue"


def test_broken_barh_uses_patch_facecolor_without_advancing_cycles() -> None:
    fig, ax = plt.subplots()
    collections = [ax.broken_barh([(index, 0.75)], (index, 0.5)) for index in range(3)]

    assert [collection._entry["kwargs"]["color"] for collection in collections] == [
        "#1f77b4",
        "#1f77b4",
        "#1f77b4",
    ]
    assert ax.plot([0, 1], [0, 1])[0].get_color() == "#1f77b4"
    assert ax.fill_between([0, 1], [0, 1])._entry["kwargs"]["color"] == "#1f77b4"

    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    assert 'fill="#1f77b4"' in svg


def test_hlines_vlines_use_lines_color_without_advancing_or_overriding_explicit_color() -> None:
    fig, ax = plt.subplots()
    vertical = ax.vlines([0.25], [0], [1])
    explicit = ax.hlines([0.5], [0], [1], colors="red")
    horizontal = ax.hlines([0.75], [0], [1])

    assert vertical._entry["kwargs"]["color"] == "#1f77b4"
    assert explicit._entry["kwargs"]["color"] == "red"
    assert horizontal._entry["kwargs"]["color"] == "#1f77b4"
    assert ax.plot([0, 1], [0, 1])[0].get_color() == "#1f77b4"

    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    assert 'stroke="#1f77b4"' in svg
    assert 'stroke="red"' in svg
