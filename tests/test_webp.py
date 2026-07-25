"""Lossless WebP (VP8L) encoder tests: exact round-trips via Pillow's libwebp
decoder (the reference implementation), container framing, and input
validation."""

from __future__ import annotations

import struct
from io import BytesIO

import numpy as np
import pytest

from xy import _webp

Image = pytest.importorskip("PIL.Image")


def _decode(data: bytes) -> np.ndarray:
    return np.array(Image.open(BytesIO(data)).convert("RGBA"))


def _assert_roundtrip(img: np.ndarray) -> bytes:
    out = _webp.encode(img)
    expected = img
    if img.shape[2] == 3:
        expected = np.concatenate([img, np.full((*img.shape[:2], 1), 255, np.uint8)], axis=2)
    np.testing.assert_array_equal(_decode(out), expected)
    return out


def _chart_like(h: int = 200, w: int = 300) -> np.ndarray:
    """Flat background + gridlines + a couple of line series."""
    img = np.full((h, w, 4), 255, np.uint8)
    img[:, :, :3] = 250
    img[::25, :, :3] = 220
    img[:, ::25, :3] = 220
    x = np.arange(w)
    y = (h / 2 + (h / 3) * np.sin(x / 17)).astype(np.int64).clip(1, h - 2)
    img[y, x] = (31, 119, 180, 255)
    img[y + 1, x] = (100, 150, 200, 255)  # a soft "antialiased" fringe
    y2 = (h / 2 + (h / 4) * np.cos(x / 29)).astype(np.int64).clip(0, h - 1)
    img[y2, x] = (255, 127, 14, 255)
    return img


def test_roundtrip_1x1():
    _assert_roundtrip(np.array([[[10, 20, 30, 255]]], np.uint8))


def test_roundtrip_2x3_distinct():
    img = np.arange(2 * 3 * 4, dtype=np.uint8).reshape(2, 3, 4) * 7
    img[:, :, 3] = 255
    _assert_roundtrip(img)


def test_roundtrip_single_color():
    # One-symbol prefix codes for every channel, plus long distance-1 runs.
    img = np.full((64, 64, 4), (12, 200, 34, 255), np.uint8)
    _assert_roundtrip(img)


def test_roundtrip_checkerboard():
    yy, xx = np.mgrid[0:32, 0:32]
    img = np.where(
        ((yy + xx) % 2 == 0)[..., None],
        np.array([255, 0, 0, 255], np.uint8),
        np.array([0, 0, 255, 255], np.uint8),
    ).astype(np.uint8)
    _assert_roundtrip(img)


def test_roundtrip_gradient():
    img = np.zeros((40, 300, 4), np.uint8)
    img[:, :, 0] = np.linspace(0, 255, 300, dtype=np.uint8)
    img[:, :, 1] = np.linspace(255, 0, 300, dtype=np.uint8)
    img[:, :, 2] = 128
    img[:, :, 3] = 255
    _assert_roundtrip(img)


def test_roundtrip_noise():
    rng = np.random.default_rng(42)
    _assert_roundtrip(rng.integers(0, 256, (50, 50, 4), dtype=np.uint8))


def test_roundtrip_alpha_gradient():
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, (30, 60, 4), dtype=np.uint8)
    img[:, :, 3] = np.linspace(0, 255, 60, dtype=np.uint8)  # alpha must survive
    _assert_roundtrip(img)


def test_roundtrip_chart_like():
    _assert_roundtrip(_chart_like())


def test_rgb_input_treated_as_opaque():
    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, (20, 20, 3), dtype=np.uint8)
    decoded = _decode(_webp.encode(img))
    np.testing.assert_array_equal(decoded[:, :, :3], img)
    assert (decoded[:, :, 3] == 255).all()


def test_riff_container_framing():
    out = _webp.encode(_chart_like(40, 30))
    assert out[:4] == b"RIFF"
    assert struct.unpack("<I", out[4:8])[0] == len(out) - 8
    assert out[8:16] == b"WEBPVP8L"
    payload = struct.unpack("<I", out[16:20])[0]
    # The chunk size excludes the pad byte; the file always ends even-aligned.
    assert len(out) == 20 + payload + (payload & 1)
    assert len(out) % 2 == 0


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((1, 16385, 4), np.uint8),  # width over the 14-bit limit
        np.zeros((16385, 1, 4), np.uint8),
        np.zeros((0, 5, 4), np.uint8),  # zero-sized
        np.zeros((5, 0, 4), np.uint8),
        np.zeros((4, 4, 4), np.float32),  # wrong dtype
        np.zeros((4, 4), np.uint8),  # wrong rank
        np.zeros((4, 4, 2), np.uint8),  # wrong channel count
    ],
)
def test_invalid_input_raises(bad):
    with pytest.raises(ValueError):
        _webp.encode(bad)


def test_deterministic():
    rng = np.random.default_rng(11)
    img = rng.integers(0, 256, (33, 47, 4), dtype=np.uint8)
    assert _webp.encode(img) == _webp.encode(img)


def test_single_color_compresses():
    img = np.full((256, 256, 4), (10, 30, 200, 255), np.uint8)
    out = _assert_roundtrip(img)
    assert len(out) < 5000  # 256 KiB raw; runs + Huffman crush it
