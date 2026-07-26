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


# --- entropy packer: the chunk-boundary carry (`_ENTROPY_BIT_CHUNK`) ---------
#
# `_pack_entropy` packs the bitstream in bounded passes, which means group
# boundaries land mid-byte and each pass has to carry its leftover bits into the
# next one. Nothing in the image-level tests above reaches that code: their
# entropy streams are orders of magnitude shorter than one group, so the carry
# would stay dead while every large export silently corrupted. These tests pin
# the contract directly, against a bit-by-bit statement of the T.81 rule.
#
# What they deliberately do NOT pin is *where* the splits land: packing is a
# concatenation with carries, so any grouping of the same tokens emits the same
# bytes. Moving a split point by a token is a refactor, and these tests are
# expected to stay green through one; dropping the carry, padding a non-final
# group, or skipping its byte stuffing are the failures they exist to catch
# (each was checked by mutating the implementation).


def reference_pack(chunk: np.ndarray, nbits: np.ndarray) -> bytes:
    """T.81 entropy packing written as the obvious Python loop.

    MSB-first per token, 1-padded to a byte boundary, 0x00 stuffed after every
    0xFF. Deliberately naive: it is the oracle, so it must be readable rather
    than fast, and it must not share structure with the implementation.
    """
    bits: list[int] = []
    for value, width in zip(chunk.tolist(), nbits.tolist(), strict=True):
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)
    while len(bits) % 8:
        bits.append(1)
    out = bytearray()
    for start in range(0, len(bits), 8):
        byte = 0
        for bit in bits[start : start + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
        if byte == 0xFF:
            out.append(0x00)
    return bytes(out)


def token_stream(total_bits: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Random (value, width) tokens covering at least `total_bits` bits.

    Widths span 1..27 — the real range, a Huffman code of up to 16 bits plus up
    to 11 amplitude bits — so group boundaries fall at every possible offset
    within a token rather than at a fixed stride.
    """
    rng = np.random.default_rng(seed)
    widths = rng.integers(1, 28, size=total_bits // 14 + 8).astype(np.int64)
    keep = int(np.searchsorted(np.cumsum(widths), total_bits)) + 1
    widths = widths[: min(keep, widths.size)]
    values = (rng.integers(0, 1 << 30, size=widths.size).astype(np.int64)) & (
        (np.int64(1) << widths) - 1
    )
    return values, widths


@pytest.mark.parametrize("group_bits", [8, 9, 64, 97, 1024])
def test_entropy_packer_carries_across_group_boundaries(monkeypatch, group_bits):
    """Tiny groups make every pass end mid-byte, in every alignment."""
    monkeypatch.setattr(_jpeg, "_ENTROPY_BIT_CHUNK", group_bits)
    values, widths = token_stream(6 * 1024, seed=group_bits)
    assert int(widths.sum()) > 4 * group_bits  # several boundaries, not one
    assert _jpeg._pack_entropy(values, widths) == reference_pack(values, widths)


def test_entropy_packer_is_transparent_at_the_production_group_size():
    """The shipped `_ENTROPY_BIT_CHUNK`, over a stream that crosses it twice."""
    values, widths = token_stream(3 * _jpeg._ENTROPY_BIT_CHUNK, seed=11)
    assert int(widths.sum()) > 2 * _jpeg._ENTROPY_BIT_CHUNK
    assert _jpeg._pack_entropy(values, widths) == reference_pack(values, widths)


@pytest.mark.parametrize(
    "values,widths",
    [
        ([], []),  # no tokens at all
        ([1], [1]),  # a single sub-byte token: pure padding path
        ([0xFF], [8]),  # exactly one byte, and it needs stuffing
        ([0xFF, 0xFF], [8, 8]),  # consecutive stuffed bytes
        ([0x7FFFFFF], [27]),  # the widest real token
    ],
)
def test_entropy_packer_degenerate_streams(values, widths):
    v = np.asarray(values, dtype=np.int64)
    w = np.asarray(widths, dtype=np.int64)
    assert _jpeg._pack_entropy(v, w) == reference_pack(v, w)


def test_entropy_packer_stuffing_survives_a_boundary(monkeypatch):
    """A 0xFF byte formed from bits that straddle two passes still stuffs."""
    monkeypatch.setattr(_jpeg, "_ENTROPY_BIT_CHUNK", 5)
    # 5-bit groups, all-ones: every byte is 0xFF and no byte is group-aligned.
    v = np.full(8, 0b11111, dtype=np.int64)
    w = np.full(8, 5, dtype=np.int64)
    packed = _jpeg._pack_entropy(v, w)
    assert packed == reference_pack(v, w)
    assert packed.count(b"\xff\x00") == packed.count(b"\xff")  # every FF stuffed


def test_large_image_entropy_matches_a_single_pass(monkeypatch):
    """End-to-end: chunking changes nothing on a real token distribution.

    Noise maximizes nonzero AC coefficients, so this image's entropy stream
    crosses the production group size many times — unlike every other image in
    this file. Encoding it again with the packer forced into one pass is the
    strongest available statement that the carry is exact.
    """
    rng = np.random.default_rng(5)
    img = rng.integers(0, 256, (320, 400, 4), dtype=np.uint8)
    chunked = _jpeg.encode(img, quality=90)
    monkeypatch.setattr(_jpeg, "_ENTROPY_BIT_CHUNK", 1 << 62)
    assert _jpeg.encode(img, quality=90) == chunked
    # ...and the stream really was long enough to exercise several groups.
    assert len(chunked) * 8 > 4 * (1 << 18)


# --- narrow token widths and the YCbCr band size -----------------------------
#
# The token pipeline carries every field at its natural width (uint8 symbols,
# int16 amplitudes, int32 block indices) rather than as int64. That is only
# sound because the coefficient range is bounded, and only invisible because
# the RGB->YCbCr band size cannot change the arithmetic. Both are pinned here.


def test_quantized_coefficients_fit_int16():
    """|DCT coefficient| <= 1024 for any 8-bit input, so int16 is exact.

    `_DCT` is orthonormal, so the 2-D transform preserves the Frobenius norm:
    no coefficient can exceed the norm of a level-shifted 8x8 block, which is
    at most sqrt(64) * 128 = 1024. Quantizers are >= 1, so quantization only
    shrinks it. This is the invariant the int16 coefficient buffer rests on.
    """
    d = _jpeg._DCT.astype(np.float64)
    np.testing.assert_allclose(d @ d.T, np.eye(8), atol=1e-6)

    rng = np.random.default_rng(0)
    extremes = [
        np.full((8, 8), -128.0),  # maximal negative DC
        np.full((8, 8), 127.0),  # maximal positive DC
        (((np.arange(8)[:, None] + np.arange(8)[None, :]) % 2) * 255.0) - 128.0,
        np.where(np.arange(64).reshape(8, 8) % 2, 127.0, -128.0),
        *(rng.integers(0, 256, (8, 8)).astype(np.float64) - 128.0 for _ in range(64)),
    ]
    blocks = np.stack(extremes).astype(np.float32)
    coef = _jpeg._DCT @ blocks @ _jpeg._DCT.T
    assert np.abs(coef).max() <= 1024.0
    assert np.iinfo(np.int16).min < -1024 and np.iinfo(np.int16).max > 1024


def test_token_fields_keep_their_narrow_widths():
    """Token arrays are byte/short-wide; widening them silently costs ~4x."""
    rng = np.random.default_rng(3)
    coef = np.zeros((64, 64), dtype=np.int16)
    coef[:, 0] = rng.integers(-1024, 1025, 64)
    coef[:, 1:] = rng.integers(-3, 4, (64, 63))
    block, seq, table, symbol, ampl, abits = _jpeg._component_tokens(coef, 0, 1)
    assert block.dtype == np.int32
    assert seq.dtype == np.uint8
    assert table.dtype == np.uint8
    assert symbol.dtype == np.uint8
    assert ampl.dtype == np.int16
    assert abits.dtype == np.uint8
    # The Huffman tables are gathered once per token, so they are narrow too.
    assert _jpeg._HUFF_CODES.dtype == np.int32
    assert _jpeg._HUFF_LENS.dtype == np.uint8
    # Sequence numbers must stay inside uint8: 0 = DC, 255 = EOB, AC between.
    assert seq.max() <= 255 and (seq[table == 0] == 0).all()


@pytest.mark.parametrize("band_px", [1, 2, 7, 64, 1 << 12, 1 << 30])
def test_ycbcr_band_size_is_transparent(monkeypatch, band_px):
    """Row banding is elementwise, so the band size cannot move a byte."""
    img = with_alpha(chart_rgb(53, 67))
    monkeypatch.setattr(_jpeg, "_YCBCR_PIXEL_CHUNK", 1 << 30)
    one_shot = _jpeg.encode(img, quality=90)
    monkeypatch.setattr(_jpeg, "_YCBCR_PIXEL_CHUNK", band_px)
    assert _jpeg.encode(img, quality=90) == one_shot


def test_dc_differential_survives_maximal_swings():
    """Alternating black/white 8x8 blocks maximize the DC differential.

    At quality 100 every quantizer is 1, so this is the widest DC difference
    the encoder can ever see — the case that decides whether int16 coefficient
    and amplitude buffers are wide enough.
    """
    blk = (np.arange(128)[:, None] // 8 + np.arange(128)[None, :] // 8) % 2
    img = with_alpha(np.repeat((blk * 255).astype(np.uint8)[..., None], 3, axis=2))
    out = decode(_jpeg.encode(img, quality=100))
    assert out.shape == (128, 128, 3)
    # Corners are flat 8x8 fills, so they survive quantization near-exactly.
    assert out[:4, :4].mean() < 40 and out[:4, 8:12].mean() > 215
