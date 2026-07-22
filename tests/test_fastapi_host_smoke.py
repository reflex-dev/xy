from __future__ import annotations

import struct
import zlib

import pytest
from scripts import fastapi_host_smoke


def _png(rgb: tuple[int, int, int]) -> bytes:
    width = height = 2
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_colored_pixel_oracle_counts_saturated_mount() -> None:
    count = fastapi_host_smoke.colored_pixels(_png((255, 0, 0)), {"x": 0, "y": 0, "w": 2, "h": 2})
    assert count == 4


def test_mount_oracle_rejects_blank_browser_output() -> None:
    with pytest.raises(AssertionError, match="browser mount is blank"):
        fastapi_host_smoke.require_ink(0)
