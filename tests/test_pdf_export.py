"""Native PDF export (_pdf.py): structural validity (xref/trailer), vector
fidelity (text as text, shapes as paths, rasters as image XObjects, gradients
as axial shadings), the closed-subset drift guard, and determinism."""

from __future__ import annotations

import base64
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import numpy as np
import pytest

import xy
from xy._figure import Figure
from xy._pdf import svg_to_pdf


def _basic_figure() -> Figure:
    x = np.linspace(0.0, 10.0, 40)
    fig = Figure(title="combo", x_label="time", y_label="value")
    fig.scatter(x, np.cos(x), name="pts")
    fig.line(x, np.sin(x), name="ln")
    fig.bar(["a", "b", "c"], [1.0, 3.0, 2.0], name="bars")
    return fig


def _objects(pdf: bytes) -> dict[int, bytes]:
    """Every `N 0 obj ... endobj` body keyed by object number."""
    return {
        int(m.group(1)): m.group(2)
        for m in re.finditer(rb"(\d+) 0 obj\n(.*?)\nendobj\n", pdf, re.S)
    }


def _stream(obj: bytes) -> bytes:
    head, _, rest = obj.partition(b"stream\n")
    assert b"/FlateDecode" in head
    return zlib.decompress(rest.rsplit(b"\nendstream", 1)[0])


def _content(pdf: bytes) -> bytes:
    objs = _objects(pdf)
    page = next(body for body in objs.values() if re.search(rb"/Type /Page(?!s)", body))
    match = re.search(rb"/Contents (\d+) 0 R", page)
    assert match is not None
    return _stream(objs[int(match.group(1))])


def _xref_offsets(pdf: bytes) -> dict[int, int]:
    """Parse the xref table, verifying each offset points at `N 0 obj`."""
    startxref = int(pdf[pdf.rindex(b"startxref") + len(b"startxref") :].split()[0])
    header = re.match(rb"xref\n0 (\d+)\n", pdf[startxref:])
    assert header is not None, "startxref must point at the xref keyword"
    size = int(header.group(1))
    table = pdf[startxref + header.end() : startxref + header.end() + 20 * size]
    assert table[:20] == b"0000000000 65535 f \n"
    offsets: dict[int, int] = {}
    for num in range(1, size):
        entry = table[20 * num : 20 * num + 20]
        assert entry[10:11] == b" " and entry[16:18] == b" n", entry
        offset = int(entry[:10])
        assert pdf[offset:].startswith(f"{num} 0 obj".encode()), (
            f"xref offset for object {num} is not byte-accurate"
        )
        offsets[num] = offset
    return offsets


def test_pdf_structure_xref_and_trailer() -> None:
    pdf = svg_to_pdf(_basic_figure().to_svg())
    assert pdf.startswith(b"%PDF-1.")
    assert len(re.findall(rb"/Type /Page(?![s])", pdf)) == 1  # single page
    # 900x420 px at 0.75 pt/px.
    assert b"/MediaBox [0 0 675 315]" in pdf

    offsets = _xref_offsets(pdf)
    root_match = re.search(rb"trailer\n<< /Size \d+ /Root (\d+) 0 R >>", pdf)
    assert root_match is not None
    root_num = int(root_match.group(1))
    catalog = pdf[offsets[root_num] : offsets[root_num] + 120]
    assert b"/Type /Catalog" in catalog  # /Root resolves


def test_pdf_content_is_vector_text_and_paths() -> None:
    svg = _basic_figure().to_svg()
    pdf = svg_to_pdf(svg)
    content = _content(pdf)

    # Text stays text: BT/ET blocks with Tj strings using the Helvetica family.
    assert b"BT" in content and b"ET" in content
    assert b"/BaseFont /Helvetica" in pdf
    root = ET.fromstring(svg)
    tick_labels = [
        el.text
        for el in root.iter()
        if el.tag.endswith("text") and el.get("text-anchor") == "end" and el.text
    ]
    assert tick_labels, "figure should carry y tick labels"
    assert any(f"({label}) Tj".encode() in content for label in tick_labels)

    # Vector shapes, not one big image: path construction + paint operators.
    for op in (b" re\n", b" m\n", b" l\n", b"\nf\n", b"\nS\n", b"W n"):
        assert op in content, f"missing content-stream op {op!r}"
    assert b"/Subtype /Image" not in pdf  # nothing was rasterized


def test_heatmap_embeds_matching_image_xobject() -> None:
    rng = np.random.default_rng(2)
    fig = Figure()
    fig.heatmap(rng.random((8, 6)))
    svg = fig.to_svg()
    pdf = svg_to_pdf(svg)

    root = ET.fromstring(svg)
    image = next(el for el in root.iter() if el.tag.endswith("image"))
    png = base64.b64decode(image.get("href").split(",", 1)[1])
    w, h = struct.unpack(">II", png[16:24])

    dims = [
        (int(m.group(1)), int(m.group(2)))
        for m in re.finditer(
            rb"/Subtype /Image /Width (\d+) /Height (\d+) /ColorSpace /DeviceRGB", pdf
        )
    ]
    assert (w, h) in dims, f"no /DeviceRGB image XObject with {w}x{h}, found {dims}"
    assert b"/Interpolate false" in pdf  # pixelated rendering intent


def test_gradient_becomes_axial_shading() -> None:
    x = np.linspace(0.0, 10.0, 30)
    fig = Figure()
    fig.area(x, np.abs(np.sin(x)) + 0.1, fill="linear-gradient(currentColor, transparent)")
    svg = fig.to_svg()
    if "linearGradient" not in svg:
        pytest.skip("generator emitted no gradient for this figure")
    pdf = svg_to_pdf(svg)
    assert b"/ShadingType 2" in pdf or b"/ShadingType 3" in pdf
    assert b"/SMask << /S /Luminosity" in pdf  # transparent stop -> soft mask
    assert b" sh" in _content(pdf)  # painted inside the geometry's clip
    assert b"W n" in _content(pdf)


def test_unsupported_svg_features_raise() -> None:
    ns = 'xmlns="http://www.w3.org/2000/svg"'
    with pytest.raises(ValueError, match="unsupported SVG feature"):
        svg_to_pdf(f'<svg {ns} width="100" height="50"><foreignObject/></svg>')
    # Attribute drift on a known element fails loudly too.
    with pytest.raises(ValueError, match="unsupported SVG feature"):
        svg_to_pdf(
            f'<svg {ns} width="100" height="50">'
            '<rect x="0" y="0" width="10" height="10" filter="url(#b)"/></svg>'
        )
    # ...as does a path command outside the generator's subset.
    with pytest.raises(ValueError, match="unsupported SVG feature"):
        svg_to_pdf(f'<svg {ns} width="100" height="50"><path d="M 0 0 Q 5 5 10 0"/></svg>')


def test_pdf_output_is_deterministic() -> None:
    svg = _basic_figure().to_svg()
    assert svg_to_pdf(svg) == svg_to_pdf(svg)

    rng = np.random.default_rng(3)
    fig = Figure()
    fig.heatmap(rng.random((6, 5)))
    heatmap_svg = fig.to_svg()
    assert svg_to_pdf(heatmap_svg) == svg_to_pdf(heatmap_svg)


def test_facet_grid_converts_with_clipped_panels() -> None:
    x = np.linspace(0.0, 10.0, 50)
    data = {
        "x": np.tile(x, 3),
        "y": np.concatenate([np.sin(x), np.cos(x), np.sin(2 * x)]),
        "g": np.repeat(["a", "b", "c"], 50),
    }
    chart = xy.facet_chart(xy.line(x="x", y="y"), by="g", cols=2, title="grid", data=data)
    svg = chart.to_svg()
    panels = svg.count("<svg") - 1  # nested panel viewports
    assert panels > 1

    content = _content(svg_to_pdf(svg))
    # Each panel viewport becomes a translated group clipped to its bounds.
    translated = re.findall(rb"\n1 0 0 1 [\d.]+ [\d.]+ cm\n", content)
    assert len(translated) == panels
    assert content.count(b"W n") >= panels


def test_round_trip_via_external_oracle(tmp_path: Path) -> None:
    pdf = svg_to_pdf(_basic_figure().to_svg())
    path = tmp_path / "figure.pdf"
    path.write_bytes(pdf)
    qpdf = shutil.which("qpdf")
    mutool = shutil.which("mutool")
    pdftoppm = shutil.which("pdftoppm")
    if qpdf:
        proc = subprocess.run([qpdf, "--check", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    elif mutool:
        out = tmp_path / "page.png"
        proc = subprocess.run(
            [mutool, "draw", "-o", str(out), str(path), "1"], capture_output=True, text=True
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert out.exists() and out.stat().st_size > 0
    elif pdftoppm:
        proc = subprocess.run(
            [pdftoppm, "-png", "-r", "72", str(path), str(tmp_path / "page")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert list(tmp_path.glob("page*.png"))
    else:
        pytest.skip("no external PDF oracle (qpdf/mutool/pdftoppm) on PATH")
