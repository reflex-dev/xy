"""Minimal stdlib PNG encoders for size-oriented static export.

Two encoders share one zlib-based chunk writer:

- `png_truecolor` — RGBA8 (color type 6). Used to embed density/heatmap rasters
  in exported SVG (`_svg.py`) and as the fallback for photographic output.
- `encode` — auto-selects an **indexed-palette** PNG (color type 3 + `tRNS`)
  when the image has ≤256 distinct RGBA colors, which charts almost always do:
  one byte per pixel instead of four shrinks native-PNG exports several-fold.
  Falls back to truecolor otherwise.

Both stage the filtered scanlines in a single NumPy buffer and hand that buffer
straight to zlib. The image is large (4 bytes per pixel, ×4 again at scale 2),
so every avoided intermediate is a full frame of peak RSS: building the rows as
one array instead of a list of per-row `bytes` drops two full copies (the row
objects and their join), and compressing the buffer directly drops a third
(`tobytes`).

This balanced/indexed path stays pure Python/stdlib. The separate latency-first
`xy.pyplot` path fuses rasterization with the Rust PNG encoder.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


_SIG = b"\x89PNG\r\n\x1a\n"
_COMPRESSION_LEVEL = 6
# Row-block length for the palette-index lookup. `np.unique(return_inverse=True)`
# would hand back one intp per pixel (8 bytes/px — twice the image itself) only
# to be narrowed to u8; searching the ≤256-entry palette per block writes the
# final bytes in place with a bounded temporary instead.
_INDEX_ROW_BLOCK = 64


def _filtered_rows(h: int, stride: int) -> np.ndarray:
    """An `(h, stride + 1)` scanline buffer with the per-row filter byte set to
    0 (PNG filter type "None"), ready for the pixel columns to be filled."""
    rows = np.empty((h, stride + 1), dtype=np.uint8)
    rows[:, 0] = 0
    return rows


def png_truecolor(
    w: int,
    h: int,
    rgba: bytes | bytearray | memoryview | np.ndarray,
    *,
    compression_level: int = _COMPRESSION_LEVEL,
) -> bytes:
    """RGBA8 PNG (color type 6). `rgba` is row-major `w*h*4` bytes, top row
    first.

    Any buffer works and none is copied: `bytes`/`bytearray`/`memoryview`, or a
    **C-contiguous** uint8 array (pass `np.ascontiguousarray` if that is not
    guaranteed — a strided view would be read in memory order, not row order).
    Only the first `w * h * 4` bytes are read.
    """
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    stride = w * 4
    rows = _filtered_rows(h, stride)
    rows[:, 1:] = np.frombuffer(rgba, dtype=np.uint8, count=h * stride).reshape(h, stride)
    return (
        _SIG
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(rows, compression_level))
        + _chunk(b"IEND", b"")
    )


def _png_indexed(w: int, h: int, rows: np.ndarray, palette: np.ndarray) -> bytes:
    """Indexed PNG (color type 3). `rows` is the `(h, w + 1)` filtered scanline
    buffer holding palette indices; `palette` is `(n, 4)` uint8 RGBA. `tRNS`
    carries per-entry alpha."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    plte = palette[:, :3].astype(np.uint8).tobytes()
    trns = palette[:, 3].astype(np.uint8).tobytes()
    out = _SIG + _chunk(b"IHDR", ihdr) + _chunk(b"PLTE", plte)
    # tRNS may omit trailing opaque (255) entries; keep it simple and always emit.
    out += _chunk(b"tRNS", trns)
    out += _chunk(b"IDAT", zlib.compress(rows, _COMPRESSION_LEVEL)) + _chunk(b"IEND", b"")
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
    if keys.size > 65_536:
        # Antialiased marks push most real charts past 256 colors; probing a
        # stride sample first skips the full-image unique/argsort when the
        # palette attempt is doomed. A probe over 256 colors proves the whole
        # image is too, so the truecolor result is identical either way.
        probe = keys[:: keys.size // 65_536]
        if np.unique(probe).size > 256:
            return png_truecolor(w, h, flat)
    palette_keys = np.unique(keys)
    if palette_keys.size <= 256:
        palette = palette_keys.view(np.uint8).reshape(-1, 4)
        # `searchsorted` over the sorted palette is exactly `np.unique`'s
        # inverse for values that are present (all of them, by construction),
        # written straight into the scanline buffer a row-block at a time.
        rows = _filtered_rows(h, w)
        keyed = keys.reshape(h, w)
        for start in range(0, h, _INDEX_ROW_BLOCK):
            end = start + _INDEX_ROW_BLOCK
            rows[start:end, 1:] = np.searchsorted(palette_keys, keyed[start:end]).astype(np.uint8)
        return _png_indexed(w, h, rows, palette)
    return png_truecolor(w, h, flat)
