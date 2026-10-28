"""Self-extracting standalone export (`compress=True`, §29 static-export row):
the embedded client and data ride as base64-of-gzip chunks and are inflated
in-browser via DecompressionStream. These pin the embedded loader, the
exact-bytes Python-side roundtrip of every compressed chunk, deterministic
output (pinned gzip mtime), and that the default output is untouched."""

from __future__ import annotations

import base64
import gzip
import json
import re

import pytest

import xy
from xy import export
from xy._figure import Figure


def _fig() -> Figure:
    return Figure(title="modes").line([0.0, 1.0, 2.0], [1.0, 2.0, 0.5])


def _pushed_chunks(doc: str, var: str) -> bytes:
    return b"".join(
        base64.b64decode(m.group(1))
        for m in re.finditer(rf'{re.escape(var)}\.push\("([^"]*)"\);', doc)
    )


def test_compress_roundtrips_client_and_data_bytes() -> None:
    fig = _fig()
    _, blob = fig.build_payload()
    doc = fig.to_html(compress=True)
    assert gzip.decompress(_pushed_chunks(doc, "__xyClient")).decode("utf-8") == export._bundled_js(
        "standalone"
    )
    assert gzip.decompress(_pushed_chunks(doc, "__xyChunks")) == bytes(blob)


def test_compress_embeds_the_inflate_loader_and_feature_check() -> None:
    doc = _fig().to_html(compress=True)
    assert "function xyInflate(buf)" in doc
    assert "DecompressionStream" in doc
    # Unsupported browsers get a plain-text notice via textContent, not markup.
    assert export._COMPRESS_UNSUPPORTED_JS in doc
    # The compressed export must actually be smaller than the plain one.
    assert len(doc) < len(_fig().to_html())


def test_compress_is_deterministic() -> None:
    fig = _fig()
    assert fig.to_html(compress=True) == fig.to_html(compress=True)


def test_compress_rejects_non_bool() -> None:
    with pytest.raises(ValueError, match="compress"):
        _fig().to_html(compress="yes")  # type: ignore[arg-type]


def test_default_output_carries_no_loader_and_pinned_csp() -> None:
    doc = _fig().to_html()
    assert "xyInflate" not in doc
    assert "__xyClient" not in doc
    assert f'content="{export._STANDALONE_CSP}"' in doc


# -- facet grid parity --------------------------------------------------------


def _grid():
    data = {
        "x": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        "y": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        "g": ["a", "a", "a", "b", "b", "b"],
    }
    return xy.facet_chart(xy.line(x="x", y="y"), by="g", data=data).figure()


def test_facet_compress_roundtrips_every_panel() -> None:
    grid = _grid()
    doc = grid.to_html(compress=True)
    chunk_lists = re.findall(r'"chunks":(\[[^\]]*\])', doc)
    assert len(chunk_lists) == len(grid.figures)
    for raw, fig in zip(chunk_lists, grid.figures, strict=True):
        _, blob = fig.build_payload(px_width=grid.panel_width)
        joined = b"".join(base64.b64decode(c) for c in json.loads(raw))
        assert gzip.decompress(joined) == bytes(blob)
    assert "function xyInflate(buf)" in doc
    assert gzip.decompress(_pushed_chunks(doc, "__xyClient")).decode("utf-8") == export._bundled_js(
        "standalone"
    )
