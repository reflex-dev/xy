"""Minimal dependency-free PNG encoders for static export.

Two encoders share one zlib-based chunk writer:

- `png_truecolor` — RGBA8 (color type 6). Used to embed density/heatmap rasters
  in exported SVG (`_svg.py`) and as the fallback for photographic output.
- `encode` — auto-selects an **indexed-palette** PNG (color type 3 + `tRNS`)
  when the image has ≤256 distinct RGBA colors, which charts almost always do:
  one byte per pixel instead of four shrinks native-PNG exports several-fold.
  Falls back to truecolor otherwise.

Kept out of the Rust core deliberately: encoding is cheap next to rasterization
and stays pure-Python/stdlib (no `png` crate needed).
"""

from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


_SIG = b"\x89PNG\r\n\x1a\n"


def png_truecolor(w: int, h: int, rgba: bytes) -> bytes:
    """RGBA8 PNG (color type 6). `rgba` is row-major `w*h*4` bytes, top row first."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    stride = w * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(h))
    return (
        _SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    )


def _png_indexed(w: int, h: int, idx: np.ndarray, palette: np.ndarray) -> bytes:
    """Indexed PNG (color type 3). `idx` is `(h, w)` uint8 palette indices;
    `palette` is `(n, 4)` uint8 RGBA. `tRNS` carries per-entry alpha."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    plte = palette[:, :3].astype(np.uint8).tobytes()
    trns = palette[:, 3].astype(np.uint8).tobytes()
    rows = np.concatenate(
        [np.zeros((h, 1), dtype=np.uint8), idx.astype(np.uint8)], axis=1
    )  # a 0 filter byte per scanline
    out = _SIG + _chunk(b"IHDR", ihdr) + _chunk(b"PLTE", plte)
    # tRNS may omit trailing opaque (255) entries; keep it simple and always emit.
    out += _chunk(b"tRNS", trns)
    out += _chunk(b"IDAT", zlib.compress(rows.tobytes(), 9)) + _chunk(b"IEND", b"")
    return out


def encode(img: np.ndarray) -> bytes:
    """Encode an `(h, w, 4)` uint8 RGBA image, preferring an indexed palette
    (≤256 colors) for size, else truecolor."""
    if img.ndim != 3 or img.shape[2] != 4:
        raise ValueError("PNG image must be (h, w, 4) RGBA")
    h, w = img.shape[0], img.shape[1]
    flat = np.ascontiguousarray(img).reshape(-1, 4)
    # One 32-bit key per pixel for a fast unique/lookup.
    keys = flat.view(np.uint32).reshape(-1)
    palette_keys, inverse = np.unique(keys, return_inverse=True)
    if palette_keys.size <= 256:
        palette = palette_keys.view(np.uint8).reshape(-1, 4)
        idx = inverse.astype(np.uint8).reshape(h, w)
        return _png_indexed(w, h, idx, palette)
    return png_truecolor(w, h, np.ascontiguousarray(img).tobytes())
