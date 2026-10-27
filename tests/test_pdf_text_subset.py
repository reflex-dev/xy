"""PDF honors the vector text subset (static-chrome parity, phase 0.1).

Before this change `_pdf._ALLOWED_ATTRS["text"]` rejected `font-style`,
`font-family`, `letter-spacing`, and `opacity`, so a PDF export of an
italic title — or any chart whose declared styling reached those
attributes — raised `ValueError`, contradicting the `SLOT_TEXT_PROPS`
contract that PDF honors the vector subset via the same markup. These
tests are that contract, executable.
"""

from __future__ import annotations

import re
import zlib

import pytest

import xy


def _content(pdf: bytes) -> bytes:
    """All content streams, decompressed where flate-encoded."""
    out = b""
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        body = stream.strip()
        try:
            out += zlib.decompress(body)
        except zlib.error:
            out += body
    return out


def _chart(**styles):
    return xy.line_chart(xy.line([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]), title="t", styles=styles)


def test_italic_title_selects_the_oblique_face() -> None:
    pdf = _chart(title={"font_style": "italic"}).to_image("pdf")
    assert pdf[:4] == b"%PDF"
    assert b"Helvetica-Oblique" in pdf


def test_bold_italic_composes_to_the_bold_oblique_face() -> None:
    pdf = _chart(title={"font_style": "italic", "font_weight": 700}).to_image("pdf")
    assert b"Helvetica-BoldOblique" in pdf


@pytest.mark.parametrize("slot", ["tick_label", "axis_title", "colorbar_tick"])
def test_italic_survives_on_every_vector_text_slot(slot) -> None:
    chart = xy.scatter_chart(
        xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0], color=[0.1, 0.5, 0.9]),
        xy.colorbar(title="c"),
        xy.x_axis(label="X"),
        styles={slot: {"font_style": "italic"}},
    )
    pdf = chart.to_image("pdf")
    assert b"Helvetica-Oblique" in pdf


def test_letter_spacing_becomes_tc_and_resets() -> None:
    pdf = _chart(tick_label={"letter_spacing": "2px"}).to_image("pdf")
    content = _content(pdf)
    assert b" Tc" in content
    # Text state persists past ET; every spaced run must reset, so the
    # count of sets equals the count of resets.
    sets = len(re.findall(rb"[0-9.]+ Tc", content)) - content.count(b"\n0 Tc")
    resets = content.count(b"\n0 Tc")
    assert sets == resets > 0


def test_text_opacity_folds_into_the_extgstate() -> None:
    # `title` is the slot whose vector emission carries `opacity` today
    # (slot_text_attrs); the axis family joins in the axis-chrome phase.
    faded = _chart(title={"opacity": 0.5}).to_image("pdf")
    assert faded[:4] == b"%PDF"
    # The declared 0.5 multiplies the paint's own 0.85 alpha: one composed
    # ExtGState, not two stacked ones.
    assert b"/ca 0.425" in faded


def test_declared_font_family_maps_to_base14_not_a_crash() -> None:
    pdf = _chart(tick_label={"font_family": "Inter, system-ui, sans-serif"}).to_image("pdf")
    assert pdf[:4] == b"%PDF"
    assert b"Helvetica" in pdf


def test_the_closed_subset_still_refuses_what_it_does_not_speak() -> None:
    # The whitelist grew deliberately; everything else keeps failing loudly
    # (the closed-subset contract that makes generator drift visible).
    from xy import _pdf

    with pytest.raises(ValueError, match="unsupported SVG feature"):
        _pdf.svg_to_pdf(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<text x="1" y="1" text-decoration="underline">t</text></svg>'
        )
