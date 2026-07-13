import pytest

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_line_cap_and_gapcolor_mutations_fail_loudly():
    _, ax = plt.subplots()
    line = ax.plot([0, 1], [0, 1])[0]

    with pytest.raises(NotImplementedError):
        line.set_dash_capstyle("round")
    with pytest.raises(NotImplementedError):
        line.set_solid_capstyle("round")
    with pytest.raises(NotImplementedError):
        line.set_gapcolor("red")


def test_text_preserves_visible_font_alignment_and_rotation_style():
    _, ax = plt.subplots()
    text = ax.text(
        0.2,
        0.3,
        "styled",
        ha="center",
        va="top",
        fontweight="bold",
        fontfamily="serif",
        rotation=45,
        fontsize=12,
    )

    assert text._entry["kwargs"]["anchor"] == "middle"
    assert text._entry["kwargs"]["style"] == {
        "font_size": 12.0,
        "vertical_align": "top",
        "font_weight": "bold",
        "font_family": "serif",
        "rotation": 45.0,
    }


def test_annotate_preserves_arrow_bbox_alignment_rotation_and_font_style():
    _, ax = plt.subplots()
    note = ax.annotate(
        "note",
        (1, 2),
        xytext=(5, 6),
        arrowprops={"arrowstyle": "->", "color": "red"},
        bbox={"boxstyle": "round", "facecolor": "white"},
        ha="right",
        va="bottom",
        family="monospace",
        weight="bold",
        rotation=30,
        fontsize=9,
    )

    kwargs = note._entry["kwargs"]
    assert kwargs["arrowprops"] == {"arrowstyle": "->", "color": "red"}
    assert kwargs["bbox"] == {"boxstyle": "round", "facecolor": "white"}
    assert kwargs["anchor"] == "end"
    # matplotlib semantics: the text sits AT xytext (data coords), and the
    # arrowprops materialize an @arrow entry pointing back at xy.
    assert note._entry["args"][:2] == (5.0, 6.0)
    arrow = next(e for e in ax._entries if e["kind"] == "@arrow")
    assert arrow["args"] == (5.0, 6.0, 1.0, 2.0)
    assert arrow["kwargs"]["color"] == "red"
    assert kwargs["style"] == {
        "font_size": 9.0,
        "vertical_align": "bottom",
        "font_weight": "bold",
        "font_family": "monospace",
        "rotation": 30.0,
    }


def test_bar_align_edge_uses_edge_geometry_instead_of_center_approximation():
    _, ax = plt.subplots()
    bars = ax.bar([1, 3], [2, 4], width=0.5, align="edge")

    assert list(bars._entry["x"]) == [1.25, 3.25]
    assert bars._entry["kwargs"]["width"] == 0.5
    with pytest.raises(ValueError):
        ax.bar(["a"], [1], align="edge")
