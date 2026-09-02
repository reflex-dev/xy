"""Text safety of the static exports.

XML 1.0 §2.2 forbids the C0 controls other than tab/newline/CR, the surrogate
range and U+FFFE/U+FFFF, and no character reference can smuggle them in. A
legend name or tick label carrying one used to produce SVG that no parser
accepts and a PDF export that refused the document, while the HTML and PNG
paths (not XML) succeeded — the same chart exported in two of four formats.
`xy._svg.escape` is the single choke point every raw text sink routes through,
and it now drops those code points (spec/api/export.md §2). These tests pin the
rule at the helper, at the two original repros, and across the whole C0 table.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zlib

import numpy as np
import pytest

import xy
from xy._svg import _escape_attr, escape

#: Every code point XML 1.0 cannot carry, as `Char` excludes them.
XML_ILLEGAL = (
    [chr(c) for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)]
    + ["￾", "￿"]
    + ["\ud800", "\udfff"]  # lone surrogates
)

#: Neighbours the rule must NOT touch: the three legal controls, DEL, the C1
#: range, no-break space (not `isprintable`, so it takes the slow path), the
#: replacement character and an astral code point.
XML_LEGAL_EDGE = ["\t", "\n", "\r", "\x7f", "\x80", "\x9f", "\xa0", "�", "\U0001f600"]


def _ident(ch: str) -> str:
    return f"U+{ord(ch):04X}"


def _texts(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return ["".join(node.itertext()) for node in root.iter() if node.tag.endswith("text")]


def _pdf_content(pdf: bytes) -> bytes:
    objs = {
        int(m.group(1)): m.group(2)
        for m in re.finditer(rb"(\d+) 0 obj\n(.*?)\nendobj\n", pdf, re.S)
    }
    page = next(body for body in objs.values() if re.search(rb"/Type /Page(?!s)", body))
    match = re.search(rb"/Contents (\d+) 0 R", page)
    assert match is not None
    stream = objs[int(match.group(1))].partition(b"stream\n")[2]
    return zlib.decompress(stream.rsplit(b"\nendstream", 1)[0])


@pytest.mark.parametrize("ch", XML_ILLEGAL, ids=_ident)
def test_escape_drops_every_xml_illegal_code_point(ch: str) -> None:
    assert escape(f"a{ch}b") == "ab"
    assert escape(ch) == ""
    # Attribute values share the rule, on top of quoting.
    assert _escape_attr(f'a{ch}"b') == "a&quot;b"


@pytest.mark.parametrize("ch", XML_LEGAL_EDGE, ids=_ident)
def test_escape_keeps_every_legal_neighbour(ch: str) -> None:
    assert escape(f"a{ch}b") == f"a{ch}b"


def test_escape_still_escapes_markup_around_dropped_characters() -> None:
    assert escape("\x01&\x02<\x03>\x04") == "&amp;&lt;&gt;"
    assert escape("") == ""
    # Dropping happens before escaping, so nothing can reassemble markup.
    assert escape("&\x01amp;") == "&amp;amp;"
    # The result is always well-formed character data (the parser's own
    # line-end normalisation turns the kept `\r` into `\n`; XML 1.0 §2.11).
    hostile = "".join(XML_ILLEGAL + XML_LEGAL_EDGE) + "<&>"
    parsed = "".join(ET.fromstring(f"<t>{escape(hostile)}</t>").itertext())
    assert parsed == ("".join(XML_LEGAL_EDGE) + "<&>").replace("\r", "\n")


def test_legend_name_with_a_control_character_exports_well_formed_svg() -> None:
    # The original repro: `to_svg` produced a document `ET.fromstring` rejected.
    xs = np.linspace(0.0, 6.0, 50)
    chart = xy.line_chart(xy.line(xs, np.sin(xs), name="a\x01b"), width=400, height=300)
    texts = _texts(chart.to_svg())  # parses
    assert "ab" in texts, texts
    assert not any("\x01" in t for t in texts)


def test_bar_category_with_an_escape_character_exports_pdf() -> None:
    # The original repro: the PDF writer refused the SVG as unparsable XML.
    chart = xy.bar_chart(xy.bar(["a\x1bz", "b"], [1, 2]), width=400, height=300)
    pdf = chart.to_image("pdf")
    assert pdf.startswith(b"%PDF-1.")
    assert b"(az) Tj" in _pdf_content(pdf)


@pytest.mark.parametrize("ch", XML_ILLEGAL, ids=_ident)
def test_every_illegal_code_point_round_trips_through_to_svg(ch: str) -> None:
    # The whole table through a real chart, hitting the legend-name, tick-label
    # (categorical bar) and title sinks at once.
    chart = xy.bar_chart(
        xy.bar([f"c{ch}1", "c2"], [1.0, 2.0], name=f"s{ch}n"),
        width=400,
        height=300,
        title=f"t{ch}t",
    )
    texts = _texts(chart.to_svg())
    assert "c1" in texts, texts
    # The title word-wrapper splits on Python whitespace, which includes the
    # VT/FF/FS/GS/RS/US controls, so those reach the sink as a space; either
    # way the document parses and the control character is gone.
    assert "tt" in texts or "t t" in texts, texts
    assert all(ch not in t for t in texts)


def test_html_and_png_paths_are_unchanged_by_the_rule() -> None:
    # HTML carries the code point JSON-escaped (it is not XML and never
    # failed); the raster path never saw the helper at all. Both still export.
    xs = np.linspace(0.0, 6.0, 50)
    chart = xy.line_chart(xy.line(xs, np.sin(xs), name="a\x01b"), width=400, height=300)
    assert "a\\u0001b" in chart.to_html()
    assert chart.to_image("png").startswith(b"\x89PNG\r\n\x1a\n")
