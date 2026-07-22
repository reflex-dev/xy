from __future__ import annotations

import numpy as np
import pytest

import xy
from xy._figure import Figure


@pytest.mark.parametrize(
    "value",
    [
        ".2f",
        ",.2f",
        "$,.0f",
        "€,.2f",
        ".1%",
        ".0f%",
        ".4f s",
        ".3f GiB",
        ",.0fK",
        "$,.0fK",
    ],
)
def test_supported_numeric_formats_survive_public_builders(value: str) -> None:
    assert xy.x_axis(format=value).format == value
    assert xy.y_axis(type_="log", format=value).format == value
    assert xy.tooltip(format={"value": value}).format == {"value": value}


def test_supported_utc_time_format_survives_axis_and_tooltip_builders() -> None:
    value = "%Y-%m-%d %H:%M:%S %b %B"

    assert xy.x_axis(type_="time", format=value).format == value
    assert xy.tooltip(format={"when": value}).format == {"when": value}

    fig = Figure()
    fig.set_axis("x", type_="time", format=value)
    fig.scatter(
        np.array(["2024-01-01T00:00:00"], dtype="datetime64[ms]"),
        [1.0],
    )
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["kind"] == "time"
    assert spec["x_axis"]["format"] == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-format",
        ".2q",
        ".21f",
        "USD .2f",
        ".2f GiB%",
        "%Y-%q",
        "%Y-%m-%d %",
    ],
)
def test_broken_formats_fail_at_public_python_boundaries(value: str) -> None:
    with pytest.raises(ValueError, match=r"supported|UTC time tokens"):
        xy.x_axis(format=value)
    with pytest.raises(ValueError, match=r"supported|UTC time tokens"):
        xy.tooltip(format={"value": value})
    with pytest.raises(ValueError, match=r"supported|UTC time tokens"):
        Figure().set_axis("x", format=value)


def test_format_kind_mismatches_fail_when_kind_is_known_or_resolved() -> None:
    with pytest.raises(ValueError, match="supported numeric format"):
        xy.x_axis(type_="linear", format="%Y-%m-%d")
    with pytest.raises(ValueError, match="UTC time tokens"):
        xy.x_axis(type_="time", format=".2f")

    category_chart = xy.scatter_chart(
        xy.scatter(x=np.array(["alpha", "beta"]), y=np.array([1.0, 2.0])),
        xy.x_axis(format=".2f"),
    )
    with pytest.raises(ValueError, match="not supported for category labels"):
        category_chart.figure().build_payload()


def test_mutated_component_formats_are_revalidated_before_payload_emission() -> None:
    axis = xy.x_axis()
    axis.format = "broken-after-construction"
    chart = xy.scatter_chart(
        xy.scatter(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0])),
        axis,
    )
    with pytest.raises(ValueError, match="not a supported"):
        chart.figure()

    tooltip = xy.tooltip(fields=["x"])
    tooltip.format = {"x": "broken-after-construction"}
    chart = xy.scatter_chart(
        xy.scatter(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0])),
        tooltip,
    )
    with pytest.raises(ValueError, match="not a supported"):
        chart.figure()
