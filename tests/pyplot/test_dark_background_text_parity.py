from __future__ import annotations

from io import BytesIO

import xy.pyplot as plt


def teardown_function() -> None:
    plt.close("all")
    plt.rcdefaults()


def _annotation_colors(*, explicit: bool) -> dict[str, str]:
    suffix = "explicit" if explicit else "default"
    colors = {"axes": "gold", "annotation": "cyan", "figure": "magenta"} if explicit else {}
    with plt.style.context("dark_background"):
        fig, ax = plt.subplots()
        ax.text(0.1, 0.2, f"axes {suffix}", **({"color": colors["axes"]} if explicit else {}))
        ax.annotate(
            f"annotation {suffix}",
            xy=(0.5, 0.5),
            **({"color": colors["annotation"]} if explicit else {}),
        )
        fig.text(
            0.5,
            0.9,
            f"figure {suffix}",
            **({"color": colors["figure"]} if explicit else {}),
        )
    # Materialize only after the context exits. Matplotlib snapshots the
    # active default when each Text artist is created.
    spec, _ = ax._build_chart(400, 300).figure().build_payload()
    return {
        annotation["text"]: annotation["style"]["label_color"] for annotation in spec["annotations"]
    }


def test_dark_background_defaults_all_pyplot_text_to_white() -> None:
    assert _annotation_colors(explicit=False) == {
        "axes default": "white",
        "annotation default": "white",
        "figure default": "white",
    }


def test_dark_background_keeps_explicit_text_colors() -> None:
    assert _annotation_colors(explicit=True) == {
        "axes explicit": "gold",
        "annotation explicit": "cyan",
        "figure explicit": "magenta",
    }


def _delayed_dark_suptitle(**kwargs: object) -> tuple[str, bytes]:
    with plt.style.context("dark_background"):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        fig.suptitle("visible figure title", **kwargs)

    output = BytesIO()
    fig.savefig(output, format="svg")
    return fig._suptitle_style["color"], output.getvalue()


def test_dark_background_suptitle_snapshots_default_and_none_before_export() -> None:
    for kwargs in ({}, {"color": None}):
        color, svg = _delayed_dark_suptitle(**kwargs)
        assert color == "white"
        assert b"visible figure title" in svg
        assert b'fill="white"' in svg


def test_dark_background_suptitle_keeps_explicit_color() -> None:
    color, svg = _delayed_dark_suptitle(color="gold")

    assert color == "gold"
    assert b'fill="gold"' in svg
