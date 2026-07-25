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


def test_positioned_png_keeps_figure_suptitle() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fig.suptitle("visible figure title")
    fig.subplots_adjust(top=0.85)

    pixels = np.asarray(plt.imread(BytesIO(fig._to_png())))

    assert np.any(pixels[:48, :, :3] < 200)


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
    assert annotation.style["padding"] == "13.9px"
    svg = chart.figure().to_svg()
    assert 'fill="rgba(255,0,0,0.5)"' in svg
    assert 'stroke="black"' in svg
    assert 'font-style="italic"' in svg
    target = BytesIO()
    fig.savefig(target, format="png")
    rgba = np.asarray(plt.imread(BytesIO(target.getvalue())))
    assert np.any((rgba[..., 0] > 200) & (rgba[..., 1] < 180) & (rgba[..., 2] < 180))


def test_text_preserves_mathtext_italic_span_across_all_exporters() -> None:
    fig, ax = plt.subplots()

    label = ax.text(2, 6, r"an equation: $E=mc^2$", fontsize=15)

    assert label.get_text() == "an equation: E=mc²"
    assert label._entry["kwargs"]["style"]["math_italic_ranges"] == "13:14,15:17"
    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    assert '<tspan font-style="italic">E</tspan>=' in svg
    assert '<tspan font-style="italic">mc</tspan>²' in svg
    target = BytesIO()
    fig.savefig(target, format="png")
    rgba = np.asarray(plt.imread(BytesIO(target.getvalue())))
    assert np.any(rgba[..., :3] < 0.5)


def test_text_fontdict_styles_title_labels_and_named_math_functions() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    font = {"family": "serif", "color": "darkred", "weight": "normal", "size": 16}

    ax.set_title("Damped exponential decay", fontdict=font)
    equation = ax.text(2, 0.65, r"$\cos(2 \pi t) \exp(-t)$", fontdict=font)
    ax.set_xlabel("time (s)", fontdict=font)
    ax.set_ylabel("voltage (mV)", fontdict=font)

    assert equation.get_text() == "cos(2πt)exp(\N{MINUS SIGN}t)"
    assert equation._entry["kwargs"]["style"]["math_italic_ranges"] == "5:7,13:14"
    spec, _ = ax._build_chart(*fig._panel_px()).figure().build_payload()
    assert spec["dom"]["styles"]["title"] == {
        "font-size": "22.2222px",
        "color": "darkred",
        "font-weight": "normal",
        "font-family": "serif",
    }
    for axis in ("x_axis", "y_axis"):
        style = spec[axis]["style"]
        assert style["label_size"] == pytest.approx(22.2222, rel=1e-4)
        assert style["label_color"] == "darkred"
        assert style["label_font_weight"] == "normal"
        assert style["label_font_family"] == "serif"
    svg = ax._build_chart(*fig._panel_px()).figure().to_svg()
    assert 'font-family="serif"' in svg
    assert 'font-weight="normal"' in svg
    assert 'fill="darkred"' in svg
    assert ">cos(" in svg
    assert "\\cos" not in svg and "\\exp" not in svg


def test_text_commands_umlauts_render_in_native_png_and_survive_svg() -> None:
    phrase = "Unicode: Institut für Festkörperphysik"
    deleted = "Unicode: Institut fr Festkrperphysik"

    def render(text: str) -> np.ndarray:
        fig, ax = plt.subplots()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.text(3, 2, text)
        return np.asarray(plt.imread(BytesIO(fig._to_png())))

    with_umlauts = render(phrase)
    plt.close("all")
    without_umlauts = render(deleted)
    assert not np.array_equal(with_umlauts, without_umlauts)

    fig, ax = plt.subplots()
    ax.text(3, 2, phrase)
    assert phrase in ax._build_chart(*fig._panel_px()).figure().to_svg()


def test_pie_container_values_are_defensive_and_fracs_stay_numeric() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie(np.array([2, 3, 5], dtype=np.int16))

    values = pie.values
    assert values.dtype == np.dtype(np.int16)
    assert not values.flags.writeable
    np.testing.assert_allclose(pie.fracs, [0.2, 0.3, 0.5])


def test_pie_uses_equal_aspect_hidden_axes_and_seam_covering_face_strokes() -> None:
    _fig, ax = plt.subplots()

    pie = ax.pie([2, 3, 5], startangle=90)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()

    assert ax._aspect_equal is True
    assert spec["frame_sides"] == []
    assert spec["x_axis"]["tick_label_strategy"] == "none"
    assert spec["y_axis"]["tick_label_strategy"] == "none"
    assert all(wedge._entry["kwargs"]["stroke_width"] == 0.75 for wedge in pie.wedges)
    assert all(
        wedge._entry["kwargs"]["stroke"] == wedge._entry["kwargs"]["color"] for wedge in pie.wedges
    )
    assert pie.wedges[0]._entry["pie_mid"] == pytest.approx(np.deg2rad(126))
