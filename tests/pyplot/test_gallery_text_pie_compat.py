from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def test_pie_label_preserves_integer_values_for_integer_format_codes() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([36, 24, 8, 12])

    labels = ax.pie_label(pie, "{absval:03d}\n{frac:.1%}")

    assert pie.values.dtype.kind in "iu"
    assert not pie.values.flags.writeable
    assert [label.get_text() for label in labels] == [
        "036\n45.0%",
        "024\n30.0%",
        "008\n10.0%",
        "012\n15.0%",
    ]


def test_pie_label_does_not_integer_cast_float_input() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([1.0, 2.0])

    with pytest.raises(ValueError, match="format code 'd'"):
        ax.pie_label(pie, "{absval:d}")


@pytest.mark.parametrize(
    ("distance", "rotate", "expected"),
    [
        (
            0.6,
            False,
            [
                ("middle", "center", None),
                ("middle", "center", None),
                ("middle", "center", None),
                ("middle", "center", None),
            ],
        ),
        (
            1.1,
            False,
            [
                ("start", "center", None),
                ("end", "center", None),
                ("end", "center", None),
                ("start", "center", None),
            ],
        ),
        (
            0.6,
            True,
            [
                ("middle", "center", 45.0),
                ("middle", "center", 315.0),
                ("middle", "center", 405.0),
                ("middle", "center", 315.0),
            ],
        ),
        (
            1.1,
            True,
            [
                ("start", "bottom", 45.0),
                ("end", "bottom", 315.0),
                ("end", "top", 405.0),
                ("start", "top", 315.0),
            ],
        ),
    ],
)
def test_pie_label_matches_matplotlib_radial_alignment(
    distance: float,
    rotate: bool,
    expected: list[tuple[str, str, float | None]],
) -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([1, 1, 1, 1])

    labels = ax.pie_label(pie, ["a", "b", "c", "d"], distance=distance, rotate=rotate)

    actual = [
        (
            label._entry["kwargs"]["anchor"],
            label._entry["kwargs"]["style"]["vertical_align"],
            label._entry["kwargs"]["style"].get("rotation"),
        )
        for label in labels
    ]
    for result, reference in zip(actual, expected, strict=True):
        assert result[:2] == reference[:2]
        if reference[2] is None:
            assert result[2] is None
        else:
            assert result[2] == pytest.approx(reference[2])


def test_pie_label_textprops_override_geometry_and_accept_gallery_font_styles() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([1, 2])

    labels = ax.pie_label(
        pie,
        ["one", "two"],
        distance=1.1,
        rotate=True,
        textprops={
            "ha": "center",
            "va": "center",
            "rotation": 12,
            "fontsize": "large",
            "weight": "bold",
            "style": "italic",
            "family": "serif",
        },
    )

    for label in labels:
        kwargs = label._entry["kwargs"]
        assert kwargs["anchor"] == "middle"
        assert kwargs["style"] == {
            "vertical_align": "center",
            "rotation": 12.0,
            "font_size": 12.0,
            "font_weight": "bold",
            "font_family": "serif",
            "font_style": "italic",
        }


def test_pie_label_rotation_reaches_static_svg() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([1, 1, 1, 1])
    ax.pie_label(pie, ["a", "b", "c", "d"], rotate=True)

    svg = ax._build_chart(640, 480).figure().to_svg()

    assert svg.count('transform="rotate(-45 ') == 2
    assert 'transform="rotate(-315 ' in svg


def test_text_accepts_matplotlib_style_alias_and_bbox_properties() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)

    label = ax.text(
        3,
        8,
        "boxed italics text in data coords",
        style="italic",
        bbox={"facecolor": "red", "alpha": 0.5, "pad": 10},
    )

    assert label._entry["kwargs"] == {
        "bbox": {"facecolor": "red", "alpha": 0.5, "pad": 10},
        "style": {"font_style": "italic"},
    }
    chart = ax._build_chart(*fig._panel_px())
    annotation = next(child for child in chart.children if getattr(child, "kind", None) == "text")
    assert annotation.style["font_style"] == "italic"
    assert annotation.style["background"] == "rgba(255,0,0,0.5)"
    assert annotation.style["padding"] == "13.9px 18.1px"
    svg = chart.figure().to_svg()
    assert 'fill="rgba(255,0,0,0.5)"' in svg
    assert 'stroke="black"' in svg
    assert 'font-style="italic"' in svg
    target = BytesIO()
    fig.savefig(target, format="png")
    rgba = np.asarray(plt.imread(BytesIO(target.getvalue())))
    assert np.any((rgba[..., 0] > 200) & (rgba[..., 1] < 180) & (rgba[..., 2] < 180))


def test_pie_container_values_are_defensive_and_fracs_stay_numeric() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie(np.array([2, 3, 5], dtype=np.int16))

    values = pie.values
    assert values.dtype == np.dtype(np.int16)
    assert not values.flags.writeable
    np.testing.assert_allclose(pie.fracs, [0.2, 0.3, 0.5])
