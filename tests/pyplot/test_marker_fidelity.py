import io

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_matplotlib_marker_family_keeps_distinct_symbols_in_payload():
    fig, ax = plt.subplots()
    markers = ("o", ".", ",", "x", "+", "v", "^", "<", ">", "s", "d", "D", "P", "X")
    for index, marker in enumerate(markers):
        ax.plot([index], [index], marker=marker, linestyle="none")

    payload, _blob = ax._build_chart(640, 480).figure().build_payload()
    symbols = [
        trace["style"].get("symbol", "circle")
        for trace in payload["traces"]
        if trace["kind"] == "scatter"
    ]
    assert symbols == [
        "circle",
        "point",
        "pixel",
        "x_line",
        "plus_line",
        "triangle_down",
        "triangle",
        "triangle_left",
        "triangle_right",
        "square",
        "thin_diamond",
        "diamond",
        "cross",
        "x",
    ]

    for format in ("png", "svg"):
        output = io.BytesIO()
        fig.savefig(output, format=format)
        assert output.tell() > 100
