from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree

import xy.pyplot as plt


def teardown_function() -> None:
    plt.close("all")


def test_long_category_ticks_reserve_left_canvas_gutter() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    labels = [f"Question {index}" for index in range(1, 7)]
    ax.barh(labels, [10, 20, 30, 40, 50, 60])

    spec, _ = ax._build_chart(640, 480).figure().build_payload()

    assert spec["padding"][3] >= 100
    assert spec["axes"]["y"]["categories"] == labels

    output = BytesIO()
    fig.savefig(output, format="svg")
    root = ElementTree.fromstring(output.getvalue())
    question = next(
        element
        for element in root.iter()
        if element.tag.endswith("text") and "".join(element.itertext()) == "Question 1"
    )
    assert float(question.attrib["x"]) > 0


def test_short_category_ticks_keep_core_default_gutter() -> None:
    _fig, ax = plt.subplots()
    ax.barh(["A", "B"], [1, 2])

    spec, _ = ax._build_chart(640, 480).figure().build_payload()

    assert spec.get("padding") is None
