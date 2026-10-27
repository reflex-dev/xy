"""Matplotlib 3.11 axis/tick APIs exercised by the upstream gallery."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._axes import _locator_tick_values


def test_set_ticklabels_matches_fixed_locator_and_empty_label_semantics() -> None:
    _fig, ax = plt.subplots()
    ax.set_xticks([0, 1, 2])

    labels = ax.set_xticklabels(["zero", "one", "two"], color="tab:red", fontsize=12, rotation=30)

    assert [label.get_text() for label in labels] == ["zero", "one", "two"]
    assert ax._axis_props("x")["tick_labels"] == ["zero", "one", "two"]
    assert ax._axis_props("x")["tick_label_angle"] == 30.0
    assert ax._axis_props("x")["style"]["tick_label_color"] == "#d62728"
    assert ax._axis_props("x")["style"]["tick_label_size"] == pytest.approx(12 * 100 / 72)

    with pytest.raises(ValueError, match="FixedLocator locations"):
        ax.set_xticklabels(["too", "short"])

    tick_positions = list(ax._axis_props("x")["tick_values"])
    hidden = ax.set_xticklabels([])
    assert [label.get_text() for label in hidden] == ["", "", ""]
    assert ax._axis_props("x")["tick_values"] == tick_positions
    assert ax._axis_props("x")["tick_label_strategy"] == "off"


def test_set_yticklabels_without_fixed_ticks_uses_current_static_tick_set() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 4])
    current = ax.get_yticks()

    labels = ax.set_yticklabels(["low", "high"])

    assert len(labels) == len(current)
    assert [label.get_text() for label in labels[:2]] == ["low", "high"]
    assert all(label.get_text() == "" for label in labels[2:])
    assert ax.get_yticks() == pytest.approx(current)


def test_axis_proxy_grid_targets_only_its_dimension_and_minor_is_accepted() -> None:
    _fig, ax = plt.subplots()

    ax.xaxis.grid(True, color="tab:red", linewidth=2)
    assert ax._axis_props("x")["style"]["grid_color"] == "#d62728"
    assert ax._axis_props("x")["style"]["grid_width"] == 2.0
    assert ax._axis_props("y")["style"]["grid_color"] == "transparent"

    ax.yaxis.grid(True, color="tab:blue")
    assert ax._axis_props("x")["style"]["grid_color"] == "#d62728"
    assert ax._axis_props("y")["style"]["grid_color"] == "#1f77b4"

    ax.xaxis.grid(False)
    assert ax._axis_props("x")["style"]["grid_color"] == "transparent"
    assert ax._axis_props("y")["style"]["grid_color"] == "#1f77b4"

    ax.xaxis.grid(which="minor", color="0.9")
    assert ax._axis_props("x")["minor_style"]["grid_color"] == "rgb(230,230,230)"
    assert ax._axis_props("y")["style"]["grid_color"] == "#1f77b4"


def test_axis_proxy_set_tick_params_matches_dollar_ticks_source_idiom() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1500])
    ax.yaxis.set_major_formatter("${x:1.2f}")

    ax.yaxis.set_tick_params(
        which="major",
        labelcolor="green",
        labelleft=False,
        labelright=True,
    )

    assert "tick_label_color" not in ax._axis_props("x")["style"]
    assert ax._axis_props("y")["style"]["tick_label_color"] == "green"
    assert ax._tick_label_sides["y"] == {"labelleft": False, "labelright": True}
    formatter = ax.yaxis.get_major_formatter()
    assert isinstance(formatter, plt.StrMethodFormatter)
    assert formatter(1234.5) == "$1234.50"
    spec, _buffers = ax._build_chart(640, 480).figure().build_payload_split()
    labels = spec["y_axis"]["tick_labels"]
    assert labels
    assert all(label.startswith("$") for label in labels)


def test_axis_proxy_set_tick_params_styles_minor_and_rejects_reset() -> None:
    _fig, ax = plt.subplots()

    ax.yaxis.set_tick_params(which="minor", color="green", length=4, width=2)
    assert ax._axis_props("y")["minor_style"]["tick_color"] == "green"
    assert ax._axis_props("y")["minor_style"]["tick_length"] == pytest.approx(4 * 100 / 72)
    assert ax._axis_props("y")["minor_style"]["tick_width"] == pytest.approx(2 * 100 / 72)
    with pytest.raises(NotImplementedError, match="reset=True"):
        ax.yaxis.set_tick_params(reset=True)


def test_tick_params_side_flags_and_xtick_rotation_mode() -> None:
    _fig, ax = plt.subplots()
    default_x_length = ax._axis_props("x")["style"]["tick_length"]
    default_y_length = ax._axis_props("y")["style"]["tick_length"]

    ax.tick_params(left=False, bottom=False, labelbottom=False)

    assert ax._axis_props("x")["style"]["tick_length"] == 0.0
    assert ax._axis_props("y")["style"]["tick_length"] == 0.0
    assert ax._axis_props("x")["tick_label_strategy"] == "off"
    assert ax._axis_props("y").get("tick_label_strategy") is None

    ax.tick_params(axis="x", bottom=True, rotation=45, rotation_mode="xtick")
    assert ax._axis_props("x")["style"]["tick_length"] == default_x_length
    assert ax._axis_props("y")["style"]["tick_length"] == 0.0
    assert default_y_length > 0
    assert ax._axis_props("x")["tick_label_angle"] == 45.0
    assert ax._axis_props("x")["tick_label_anchor"] == "end"
    assert ax.get_xticklabels()[0].get_rotation_mode() == "xtick"
    assert ax.get_xticklabels()[0].get_rotation() == 45.0
    spec, _blob = ax._build_chart(640, 480).figure().build_payload()
    assert spec["x_axis"]["tick_label_angle"] == -45.0

    ax.tick_params(axis="x", rotation=-45, rotation_mode="xtick")
    assert ax._axis_props("x")["tick_label_anchor"] == "start"
    assert ax.get_xticklabels()[0].get_rotation() == -45.0
    spec, _blob = ax._build_chart(640, 480).figure().build_payload()
    assert spec["x_axis"]["tick_label_angle"] == 45.0

    with pytest.raises(ValueError, match="rotation_mode"):
        ax.tick_params(axis="x", rotation_mode="sideways")


def test_tick_label_horizontal_alignment_and_large_padding_are_axis_wide() -> None:
    _fig, ax = plt.subplots()
    ax.set_yticks([0, 1], labels=["short", "a much longer label"])

    assert ax.get_yticklabels()[0].get_horizontalalignment() == "right"
    for label in ax.get_yticklabels():
        label.set_horizontalalignment("left")
    ax.tick_params("y", pad=70)

    assert ax._axis_props("y")["tick_label_anchor"] == "start"
    assert ax.get_yticklabels()[0].get_horizontalalignment() == "left"
    assert ax._axis_props("y")["style"]["tick_padding"] == pytest.approx(70 * 100 / 72)


def test_tick_params_minor_aliases_and_auto_minor_positions() -> None:
    _fig, ax = plt.subplots()
    ax.set_xlim(0, 10)
    ax.xaxis.set_major_locator(plt.FixedLocator([0, 5, 10]))
    ax.xaxis.set_minor_locator(plt.AutoMinorLocator(5))
    ax.tick_params(
        axis="x",
        which="minor",
        size=4,
        width=2,
        labelsize="small",
        tick1On=False,
        tick2On=False,
    )

    spec, _blob = ax._build_chart(640, 480).figure().build_payload()

    assert spec["x_axis"]["minor_tick_values"] == pytest.approx([1, 2, 3, 4, 6, 7, 8, 9])
    assert spec["x_axis"]["minor_style"]["tick_length"] == 0.0
    assert spec["x_axis"]["minor_style"]["tick_width"] == pytest.approx(2 * 100 / 72)
    assert spec["x_axis"]["minor_style"]["tick_label_size"] == pytest.approx(8.5 * 100 / 72)


def test_minorticks_on_and_off_install_and_clear_the_default_locator() -> None:
    _fig, ax = plt.subplots()
    ax.set_xlim(0, 10)
    ax.xaxis.set_major_locator(plt.FixedLocator([0, 5, 10]))

    ax.minorticks_on()
    enabled, _blob = ax._build_chart(640, 480).figure().build_payload()
    assert enabled["x_axis"]["minor_tick_values"] == pytest.approx([1, 2, 3, 4, 6, 7, 8, 9])

    ax.minorticks_off()
    disabled, _blob = ax._build_chart(640, 480).figure().build_payload()
    assert disabled["x_axis"].get("minor_tick_values") == []


def test_labeled_minor_ticks_promote_without_restoring_hidden_tick_lines() -> None:
    _fig, ax = plt.subplots()
    ax.set_xlim(0, 4)
    ax.xaxis.set_major_locator(plt.FixedLocator([0, 2, 4]))
    ax.xaxis.set_major_formatter(plt.NullFormatter())
    ax.xaxis.set_minor_locator(plt.FixedLocator([1, 3]))
    ax.xaxis.set_minor_formatter(plt.FixedFormatter(["one", "three"]))
    ax.tick_params(axis="x", which="minor", tick1On=False, tick2On=False)

    spec, _blob = ax._build_chart(640, 480).figure().build_payload()

    assert spec["x_axis"]["tick_values"] == [1.0, 3.0]
    assert spec["x_axis"]["tick_labels"] == ["one", "three"]
    assert spec["x_axis"]["style"]["tick_length"] == 0.0


def test_axis_tick_and_label_positions_remain_independent() -> None:
    _fig, ax = plt.subplots()
    ax.xaxis.set_ticks_position("bottom")
    ax.xaxis.set_label_position("top")
    ax.yaxis.set_ticks_position("right")
    ax.yaxis.set_label_position("left")

    assert ax._axis_props("x")["side"] == "top"
    assert ax._axis_props("x")["tick_sides"] == ["bottom"]
    assert ax._axis_props("x")["tick_label_sides"] == ["bottom"]
    assert ax._axis_props("y")["side"] == "left"
    assert ax._axis_props("y")["tick_sides"] == ["right"]
    assert ax._axis_props("y")["tick_label_sides"] == ["right"]


def test_plot_data_mapping_resolves_structured_array_fields() -> None:
    data = np.asarray(
        [
            (np.datetime64("2020-01-01"), 10.0),
            (np.datetime64("2020-01-02"), 12.0),
        ],
        dtype=[("date", "datetime64[D]"), ("value", "f8")],
    )
    _fig, ax = plt.subplots()

    (line,) = ax.plot("date", "value", data=data)

    np.testing.assert_array_equal(line.get_xdata(), data["date"])
    np.testing.assert_array_equal(line.get_ydata(), data["value"])


class _ForeignDateLocator:
    __module__ = "matplotlib.dates"

    def tick_values(self, lo: datetime, hi: datetime) -> np.ndarray:
        assert isinstance(lo, datetime)
        assert isinstance(hi, datetime)
        epoch = datetime(1970, 1, 1)
        return np.asarray(
            [
                (lo - epoch).total_seconds() / 86_400,
                (hi - epoch).total_seconds() / 86_400,
            ]
        )


class _ForeignDateFormatter:
    __module__ = "matplotlib.dates"

    def __call__(self, value: float, position: int | None = None) -> str:
        return f"{position}:{value:g}"

    def format_ticks(self, values: np.ndarray) -> list[str]:
        assert np.max(np.abs(values)) < 100_000  # Matplotlib epoch days, not xy milliseconds.
        return [f"day {value:.1f}" for value in values]


def test_foreign_matplotlib_date_tickers_bridge_days_and_engine_milliseconds() -> None:
    _fig, ax = plt.subplots()
    ax.plot(
        np.asarray(["2020-01-01", "2020-01-03"], dtype="datetime64[D]"),
        [1, 2],
    )
    locator = _ForeignDateLocator()
    formatter = _ForeignDateFormatter()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    spec, _blob = ax._build_chart(640, 480).figure().build_payload()

    assert ax.xaxis.get_major_formatter() is formatter
    assert all(abs(value) > 1_000_000_000_000 for value in spec["x_axis"]["tick_values"])
    assert spec["x_axis"]["tick_labels"][0].startswith("day ")


def test_foreign_date_locator_ignores_unrepresentable_datetime_limits() -> None:
    values = _locator_tick_values(
        _ForeignDateLocator(),
        -1e30,
        1e30,
        datetime_axis=True,
    )

    assert values.size == 0


def test_named_annotation_accepts_relative_fontsize() -> None:
    _fig, ax = plt.subplots()

    annotation = ax.annotate(text="note", xy=(0, 0), fontsize="small")

    assert annotation._entry["kwargs"]["style"]["font_size"] == pytest.approx(8.5)
