"""Standalone-export transport (§29 chunked-base64 fallback): the payload is
embedded as 3-byte-aligned base64 chunks and reassembled client-side into one
contiguous buffer. These checks are stdlib-only (no numpy / native core) since
they pin the encode helper and the emitted decoder, not any Figure."""

from __future__ import annotations

import base64

from xy import export


def _roundtrip(blob: bytes) -> bytes:
    return b"".join(base64.b64decode(c) for c in export._base64_chunks(blob))


def test_chunks_roundtrip_across_sizes() -> None:
    step = export._B64_CHUNK_BYTES
    for n in (0, 1, 2, 3, 4, 47, step - 1, step, step + 1, step + 7, 2 * step + 5):
        blob = bytes((i * 37 + n) & 0xFF for i in range(n))
        assert _roundtrip(blob) == blob, f"roundtrip mismatch at n={n}"


def test_interior_chunks_are_padding_free() -> None:
    # Every chunk but the last encodes a multiple of 3 bytes, so only the final
    # chunk may carry base64 `=` padding — this is what lets the client decode
    # each chunk independently into a contiguous region.
    blob = bytes(range(256)) * (export._B64_CHUNK_BYTES // 128)  # spans >1 chunk
    chunks = export._base64_chunks(blob)
    assert len(chunks) > 1
    for c in chunks[:-1]:
        assert "=" not in c


def test_empty_blob_yields_no_chunks() -> None:
    assert export._base64_chunks(b"") == []


def test_chunk_size_is_three_byte_aligned() -> None:
    # A non-3-aligned chunk size would inject interior padding and break the
    # independent-decode invariant above.
    assert export._B64_CHUNK_BYTES % 3 == 0


def test_decoder_snippet_defines_entry_point() -> None:
    # The inline decoder both call sites (single chart + facets) depend on.
    assert "function xyDecodeB64(chunks, total)" in export._DECODE_B64_JS
    # Prefers the native base64 decoder, keeps a browserless-safe fallback.
    assert "setFromBase64" in export._DECODE_B64_JS
    assert "atob" in export._DECODE_B64_JS
