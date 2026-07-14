import io

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_directional_triangles_and_x_keep_distinct_symbols_in_payload():
    fig, ax = plt.subplots()
    for index, marker in enumerate(("^", "v", "<", ">", "+", "x")):
        ax.plot([index], [index], marker=marker, linestyle="none")

    payload, _blob = ax._build_chart(640, 480).figure().build_payload()
    symbols = [
        trace["style"]["symbol"] for trace in payload["traces"] if trace["kind"] == "scatter"
    ]
    assert symbols == [
        "triangle",
        "triangle_down",
        "triangle_left",
        "triangle_right",
        "cross",
        "x",
    ]

    for format in ("png", "svg"):
        output = io.BytesIO()
        fig.savefig(output, format=format)
        assert output.tell() > 100
