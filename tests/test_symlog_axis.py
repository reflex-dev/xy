"""Native zero-inclusive long-tail axis contracts."""

import numpy as np
import pytest

import xy
from xy import _svg
from xy._figure import Figure


def test_symlog_component_emits_original_domain_and_constant() -> None:
    chart = xy.chart(
        xy.scatter(x=[0.0, 1.0, 1_000_000.0], y=[-10.0, 0.0, 10.0]),
        xy.x_axis(type_="symlog", constant=1_000.0),
    )
    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["scale"] == "symlog"
    assert spec["x_axis"]["constant"] == 1_000.0
    assert spec["x_axis"]["range"][0] <= 0.0
    assert spec["x_axis"]["range"][1] > 1_000_000.0


def test_symlog_accepts_zero_and_negative_explicit_domain() -> None:
    fig = Figure().scatter([-100.0, 0.0, 100.0], [0.0, 1.0, 2.0])
    fig.set_axis("x", type_="symlog", constant=10.0, domain=(-100.0, 100.0))
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["range"] == [-100.0, 100.0]


@pytest.mark.parametrize("constant", [0, -1, float("inf")])
def test_symlog_rejects_invalid_constant(constant: float) -> None:
    with pytest.raises(ValueError, match="constant"):
        xy.x_axis(type_="symlog", constant=constant)


def test_constant_is_rejected_for_other_scales() -> None:
    with pytest.raises(ValueError, match="only valid"):
        xy.y_axis(type_="linear", constant=1)


def test_static_symlog_scale_is_symmetric_and_zero_preserving() -> None:
    scale = _svg._Scale(
        {"kind": "linear", "scale": "symlog", "constant": 10.0, "range": [-1_000, 1_000]},
        0,
        200,
    )
    pixels = scale(np.array([-1_000.0, 0.0, 1_000.0]))
    assert pixels == pytest.approx([0.0, 100.0, 200.0])
    assert not scale.affine


def test_static_symlog_ticks_include_zero_in_original_units() -> None:
    ticks, labels, _ = _svg.axis_ticks(
        {"kind": "linear", "scale": "symlog", "constant": 100.0, "range": [0, 1_000_000]},
        600,
        True,
    )
    assert ticks == labels
    assert 0.0 in ticks
    assert max(ticks) <= 1_000_000
