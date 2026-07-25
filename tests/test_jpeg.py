"""Baseline JPEG encoder (`xy._jpeg`) — Pillow is the decode oracle."""

from __future__ import annotations

import io

import numpy as np
import pytest

from xy import _jpeg

Image = pytest.importorskip("PIL.Image")


def chart_rgb(h: int = 240, w: int = 320) -> np.ndarray:
    """Synthetic chart-like image: flat background, gridlines, dark axis
    lines, a color gradient region, and an antialiased-ish sine stroke."""
    img = np.full((h, w, 3), 250, dtype=np.float64)
    img[::40, :] = 230  # gridlines
    img[:, ::40] = 230
    gh0, gh1 = h // 6, h // 2
    gw0, gw1 = w // 5, w - w // 8
    ramp_x = np.linspace(60, 220, gw1 - gw0)
    ramp_y = np.linspace(40, 200, gh1 - gh0)
    img[gh0:gh1, gw0:gw1, 0] = ramp_x[None, :]
    img[gh0:gh1, gw0:gw1, 1] = ramp_y[:, None]
    img[gh0:gh1, gw0:gw1, 2] = 90
    yy = np.arange(h, dtype=np.float64)[:, None]
    xx = np.arange(w, dtype=np.float64)[None, :]
    center = h * 0.65 + h * 0.22 * np.sin(xx / w * 4 * np.pi)
    cov = np.clip(1.5 - np.abs(yy - center), 0.0, 1.0)[..., None]  # soft edges
    img = img * (1 - cov) + np.array([30.0, 60.0, 180.0]) * cov
    img[:, 24:26] = 40  # y axis
    img[h - 26 : h - 24, :] = 40  # x axis
    return np.round(img).astype(np.uint8)


def with_alpha(rgb: np.ndarray, alpha: int | np.ndarray = 255) -> np.ndarray:
    a = np.broadcast_to(np.asarray(alpha, dtype=np.uint8), rgb.shape[:2])
    return np.dstack([rgb, a])


def decode(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"))


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return float(10 * np.log10(255.0**2 / mse))


def iter_markers(data: bytes) -> list[tuple[int, bytes]]:
    """Parse marker segments up to (and including) SOS."""
    assert data[:2] == b"\xff\xd8", "must start with SOI"
    segments = []
    i = 2
    while i < len(data):
        assert data[i] == 0xFF, f"expected marker at byte {i}"
        marker = data[i + 1]
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        segments.append((marker, data[i + 4 : i + 2 + length]))
        i += 2 + length
        if marker == 0xDA:  # entropy-coded data follows; stop walking
            break
    return segments


@pytest.mark.parametrize(
    "size",
    [(1, 1), (3, 5), (17, 9), (16, 100), (40, 100), (64, 80)],
    ids=lambda s: f"{s[0]}x{s[1]}",
)
def test_pil_decodes_mode_and_size(size):
    h, w = size
    img = chart_rgb(240, 320)[:h, :w]
    data = _jpeg.encode(with_alpha(img))
    with Image.open(io.BytesIO(data)) as im:
        assert im.size == (w, h)
        assert im.mode == "RGB"


def test_flat_pixel_roundtrip():
    img = np.full((1, 1, 4), 100, dtype=np.uint8)
    img[..., 3] = 255
    out = decode(_jpeg.encode(img))
    assert out.shape == (1, 1, 3)
    assert np.all(np.abs(out.astype(int) - 100) <= 3)


def test_psnr_at_quality_90():
    img = chart_rgb()
    out = decode(_jpeg.encode(with_alpha(img), quality=90))
    assert psnr(img, out) >= 30.0


def test_quality_ordering():
    img = chart_rgb()
    lo = _jpeg.encode(with_alpha(img), quality=30)
    hi = _jpeg.encode(with_alpha(img), quality=95)
    assert psnr(img, decode(hi)) > psnr(img, decode(lo))
    assert len(hi) > len(lo)


def test_alpha_ignored():
    img = chart_rgb(64, 80)
    rng = np.random.default_rng(42)
    noisy_alpha = rng.integers(0, 256, size=(64, 80), dtype=np.uint8)
    assert _jpeg.encode(with_alpha(img, noisy_alpha)) == _jpeg.encode(with_alpha(img))


def test_rgb_input_matches_rgba():
    img = chart_rgb(48, 56)
    assert _jpeg.encode(img) == _jpeg.encode(with_alpha(img))


@pytest.mark.parametrize("quality", [0, 101, True, 3.5], ids=repr)
def test_invalid_quality(quality):
    img = with_alpha(chart_rgb(8, 8))
    with pytest.raises(ValueError, match="quality"):
        _jpeg.encode(img, quality=quality)


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((8, 8, 2), dtype=np.uint8),  # not RGB/RGBA
        np.zeros((8, 8), dtype=np.uint8),  # missing channel axis
        np.zeros((8, 8, 4), dtype=np.float64),  # wrong dtype
        np.zeros((0, 8, 4), dtype=np.uint8),  # empty
        [[[0, 0, 0, 255]]],  # not an ndarray
    ],
    ids=["chans", "ndim", "dtype", "empty", "list"],
)
def test_invalid_image(bad):
    with pytest.raises(ValueError):
        _jpeg.encode(bad)


def test_deterministic():
    img = with_alpha(chart_rgb(96, 120))
    assert _jpeg.encode(img) == _jpeg.encode(img)


def test_extreme_blocks_at_quality_100():
    # Pixel-level checkerboard maximizes high-frequency DCT energy; must
    # still decode after quantization at quality=100 (all-ones tables).
    grid = ((np.arange(16)[:, None] + np.arange(16)[None, :]) % 2) * 255
    img = np.repeat(grid.astype(np.uint8)[..., None], 3, axis=2)
    out = decode(_jpeg.encode(img, quality=100))
    assert out.shape == (16, 16, 3)


def test_marker_structure():
    data = _jpeg.encode(with_alpha(chart_rgb(40, 52)))
    assert data[:2] == b"\xff\xd8"
    assert data[-2:] == b"\xff\xd9"
    segments = iter_markers(data)
    sof0 = [payload for marker, payload in segments if marker == 0xC0]
    assert len(sof0) == 1
    payload = sof0[0]
    assert payload[0] == 8  # bit precision
    assert int.from_bytes(payload[1:3], "big") == 40  # height
    assert int.from_bytes(payload[3:5], "big") == 52  # width
    assert payload[5] == 3  # components
    for c in range(3):
        assert payload[6 + 3 * c + 1] == 0x11  # 4:4:4 sampling factors
    # And the rest of the required marker set is present, in order.
    markers = [m for m, _ in segments]
    assert markers.index(0xE0) < markers.index(0xDB) < markers.index(0xC0)
    assert markers.index(0xC4) < markers.index(0xDA)
    assert markers[0] == 0xE0 and segments[0][1][:5] == b"JFIF\x00"
