"""Hard navigation-bound API and client-clamping contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

import xy

ROOT = Path(__file__).resolve().parents[1]


def test_explicit_axis_bounds_ship_separately_from_initial_domain() -> None:
    chart = xy.bar_chart(
        xy.bar(["A", "B", "C"], [10, 20, 30]),
        xy.y_axis(domain=(5, 25), bounds=(0, 30)),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["y_axis"]["range"] == [5.0, 25.0]
    assert spec["y_axis"]["domain"] == [5.0, 25.0]
    assert spec["y_axis"]["bounds"] == [0.0, 30.0]
    assert "bounds" not in spec["x_axis"]


def test_data_bounds_resolve_independently_of_explicit_domain() -> None:
    chart = xy.line_chart(
        xy.line([10, 20, 30], [2, 4, 8]),
        xy.x_axis(domain=(12, 18), bounds="data"),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["range"] == [12.0, 18.0]
    assert spec["x_axis"]["bounds"][0] < 10
    assert spec["x_axis"]["bounds"][1] > 30


@pytest.mark.parametrize("factory", [xy.x_axis, xy.y_axis])
def test_axis_bounds_validation(factory) -> None:
    with pytest.raises(ValueError, match="bounds"):
        factory(bounds=(2, 1))
    with pytest.raises(ValueError, match="bounds"):
        factory(bounds="everything")
    with pytest.raises(ValueError, match="positive"):
        xy.line_chart(xy.line([1, 2], [1, 2]), factory(type_="log", bounds=(-1, 10))).figure()


def test_client_clamps_pan_zoom_and_reversed_log_ranges() -> None:
    source = (ROOT / "js/src/53_interaction.ts").read_text(encoding="utf-8")

    assert "_clampAxisRange(axisId: string, lo: number, hi: number, anchorFrac = 0.5)" in source
    assert "const reverse = c1 < c0" in source
    assert "const target = this._clampView(" in source
    assert 'source: "pan_drag"' in source
    assert "opts.anchors?.[axisId] ?? 0.5" in source
