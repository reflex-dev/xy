"""Pure numpy/stdlib baseline JPEG encoder for static export format parity.

Emits baseline sequential JFIF (SOI, APP0 v1.02 @ 96 DPI, DQT, SOF0, DHT,
SOS, EOI), 8-bit YCbCr at **4:4:4 sampling**: charts are line graphics, and
chroma subsampling smears one-pixel colored strokes into visible fringes, so
we spend the extra chroma bytes instead. Quantization uses the Annex K
tables scaled with the libjpeg quality curve; entropy coding uses the
Annex K Huffman tables, so size/quality at a given `quality` tracks what
users expect from libjpeg-based tooling.

Everything through bitstream assembly is vectorized: 8×8 blocks are
transformed as one (n, 8, 8) stack, run-length tokens are derived with
segmented-cumsum tricks, and the entropy stream is packed via
`np.packbits` — a per-block Python loop would dominate encode time at
chart-export sizes (an 1800×1000 canvas is ~84k blocks).

Stays numpy + stdlib on purpose (mirrors `_png.py`): the balanced static
export path must not grow an imaging dependency.
"""

from __future__ import annotations

import itertools
import struct
from typing import Optional

import numpy as np

# --- Annex K quantization tables (natural row-major order) ------------------

_QUANT_LUMA = np.array(
    [
        16, 11, 10, 16, 24, 40, 51, 61,
        12, 12, 14, 19, 26, 58, 60, 55,
        14, 13, 16, 24, 40, 57, 69, 56,
        14, 17, 22, 29, 51, 87, 80, 62,
        18, 22, 37, 56, 68, 109, 103, 77,
        24, 35, 55, 64, 81, 104, 113, 92,
        49, 64, 78, 87, 103, 121, 120, 101,
        72, 92, 95, 98, 112, 100, 103, 99,
    ],
    dtype=np.int64,
)  # fmt: skip

_QUANT_CHROMA = np.array(
    [
        17, 18, 24, 47, 99, 99, 99, 99,
        18, 21, 26, 66, 99, 99, 99, 99,
        24, 26, 56, 99, 99, 99, 99, 99,
        47, 66, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
    ],
    dtype=np.int64,
)  # fmt: skip


def _zigzag_order() -> np.ndarray:
    """Natural→zigzag index map, derived rather than typed (typo-proof).

    Anti-diagonal ``s`` is walked top-right→bottom-left when odd and reversed
    when even (T.81 Figure 5)."""
    order: list[int] = []
    for s in range(15):
        span = range(max(0, s - 7), min(s, 7) + 1)
        order.extend(i * 8 + (s - i) for i in (span if s % 2 else reversed(span)))
    return np.array(order, dtype=np.int64)


_ZIGZAG = _zigzag_order()

# --- Annex K Huffman tables (BITS length counts + HUFFVAL symbol order) -----

_DC_LUMA_BITS = bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
_DC_LUMA_VALUES = bytes(range(12))
_DC_CHROMA_BITS = bytes([0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
_DC_CHROMA_VALUES = bytes(range(12))
_AC_LUMA_BITS = bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D])
_AC_LUMA_VALUES = bytes.fromhex(
    "0102030004110512"
    "2131410613516107"
    "227114328191a108"
    "2342b1c11552d1f0"
    "2433627282090a16"
    "1718191a25262728"
    "292a343536373839"
    "3a43444546474849"
    "4a53545556575859"
    "5a63646566676869"
    "6a73747576777879"
    "7a83848586878889"
    "8a92939495969798"
    "999aa2a3a4a5a6a7"
    "a8a9aab2b3b4b5b6"
    "b7b8b9bac2c3c4c5"
    "c6c7c8c9cad2d3d4"
    "d5d6d7d8d9dae1e2"
    "e3e4e5e6e7e8e9ea"
    "f1f2f3f4f5f6f7f8"
    "f9fa"
)
_AC_CHROMA_BITS = bytes([0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77])
_AC_CHROMA_VALUES = bytes.fromhex(
    "0001020311040521"
    "3106124151076171"
    "1322328108144291"
    "a1b1c109233352f0"
    "156272d10a162434"
    "e125f11718191a26"
    "2728292a35363738"
    "393a434445464748"
    "494a535455565758"
    "595a636465666768"
    "696a737475767778"
    "797a828384858687"
    "88898a9293949596"
    "9798999aa2a3a4a5"
    "a6a7a8a9aab2b3b4"
    "b5b6b7b8b9bac2c3"
    "c4c5c6c7c8c9cad2"
    "d3d4d5d6d7d8d9da"
    "e2e3e4e5e6e7e8e9"
    "eaf2f3f4f5f6f7f8"
    "f9fa"
)


def _huff_lookup(bits: bytes, values: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Canonical symbol→(code, length) arrays from a BITS/HUFFVAL spec."""
    if len(values) != sum(bits):
        raise AssertionError("Huffman spec mismatch: HUFFVAL count != sum(BITS)")
    codes = np.zeros(256, dtype=np.int64)
    lens = np.zeros(256, dtype=np.int64)
    code = 0
    k = 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            codes[values[k]] = code
            lens[values[k]] = length
            code += 1
            k += 1
        code <<= 1
    return codes, lens


# Table index per token: 0 = DC luma, 1 = AC luma, 2 = DC chroma, 3 = AC chroma.
_HUFF_SPECS = (
    (_DC_LUMA_BITS, _DC_LUMA_VALUES),
    (_AC_LUMA_BITS, _AC_LUMA_VALUES),
    (_DC_CHROMA_BITS, _DC_CHROMA_VALUES),
    (_AC_CHROMA_BITS, _AC_CHROMA_VALUES),
)
_HUFF_CODES = np.stack([_huff_lookup(b, v)[0] for b, v in _HUFF_SPECS])
_HUFF_LENS = np.stack([_huff_lookup(b, v)[1] for b, v in _HUFF_SPECS])


def _dct_matrix() -> np.ndarray:
    """Orthonormal 8-point DCT-II matrix; `D @ X @ D.T` is the T.81 FDCT."""
    k = np.arange(8, dtype=np.float64)
    d = np.cos((2.0 * k[None, :] + 1.0) * k[:, None] * np.pi / 16.0) / 2.0
    d[0] = 1.0 / np.sqrt(8.0)
    return d.astype(np.float32)


_DCT = _dct_matrix()

# Magnitude-category boundaries: size k iff 2**(k-1) <= |v| < 2**k. Integer
# searchsorted keeps this exact where a float log2 could round at the edges.
_POW2 = np.int64(1) << np.arange(12, dtype=np.int64)

#: Placeholder that releases a token field's storage while its list slot lives on.
_EMPTY_I64 = np.empty(0, dtype=np.int64)


def _bit_size(magnitude: np.ndarray) -> np.ndarray:
    return np.searchsorted(_POW2, magnitude, side="right").astype(np.int64)


def _scaled_quant(base: np.ndarray, quality: int) -> np.ndarray:
    """Annex K table scaled with the libjpeg quality curve (integer math)."""
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality
    return np.clip((base * scale + 50) // 100, 1, 255)


def _component_tokens(
    coef: np.ndarray, dc_tbl: int, ac_tbl: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Huffman tokens for one component's (n, 64) zigzag coefficients.

    Returns parallel arrays (block, seq, table, symbol, amplitude, amp_bits);
    `seq` orders tokens within a block (0 = DC, 255 = EOB) so a single sort on
    (block, component, seq) later interleaves the MCU stream.
    """
    n = coef.shape[0]

    # DC is coded differentially along the component's block sequence.
    diff = np.diff(coef[:, 0], prepend=np.int64(0))
    dsize = _bit_size(np.abs(diff))
    # T.81 amplitude coding: negatives are sent as v + 2**size - 1.
    dampl = np.where(diff < 0, diff + (np.int64(1) << dsize) - 1, diff)
    dc_tok = (
        np.arange(n, dtype=np.int64),
        np.zeros(n, dtype=np.int64),
        np.full(n, dc_tbl, dtype=np.int64),
        dsize,
        dampl,
        dsize,
    )

    ac = coef[:, 1:]
    blk, pos = np.nonzero(ac)  # row-major: block-ascending, position-ascending
    last = np.full(n, -1, dtype=np.int64)
    if blk.size:
        last[blk] = pos  # row-major order → last write per block wins
        val = ac[blk, pos]
        first = np.empty(blk.size, dtype=bool)
        first[0] = True
        np.not_equal(blk[1:], blk[:-1], out=first[1:])
        prev = np.where(first, np.int64(-1), np.concatenate((pos[:1] * 0 - 1, pos[:-1])))
        run = pos - prev - 1
        zrl = run >> 4  # each 16 zeros of run becomes a ZRL (0xF0) token
        asize = _bit_size(np.abs(val))
        sym = ((run & 15) << 4) | asize
        aampl = np.where(val < 0, val + (np.int64(1) << asize) - 1, val)
        # Expand each nonzero into its ZRL prefix + the coefficient token,
        # numbering tokens within their block via a segmented cumsum: `start`
        # is the global exclusive cumsum of token counts and `base` forward-
        # fills each block's opening value, so `start - base` restarts at 0.
        tot = zrl + 1
        cum = np.cumsum(tot)
        start = cum - tot
        base = np.maximum.accumulate(np.where(first, start, 0))
        rep = np.repeat(np.arange(blk.size, dtype=np.int64), tot)
        j = np.arange(cum[-1], dtype=np.int64) - np.repeat(start, tot)
        is_zrl = j < zrl[rep]
        ac_tok = (
            blk[rep].astype(np.int64),
            1 + (start - base)[rep] + j,
            np.full(rep.size, ac_tbl, dtype=np.int64),
            np.where(is_zrl, np.int64(0xF0), sym[rep]),
            np.where(is_zrl, np.int64(0), aampl[rep]),
            np.where(is_zrl, np.int64(0), asize[rep]),
        )
    else:
        ac_tok = tuple(np.empty(0, dtype=np.int64) for _ in range(6))

    # EOB unless the block's final zigzag coefficient (AC position 62) is set.
    eob = np.flatnonzero(last != 62).astype(np.int64)
    eob_tok = (
        eob,
        np.full(eob.size, 255, dtype=np.int64),
        np.full(eob.size, ac_tbl, dtype=np.int64),
        np.zeros(eob.size, dtype=np.int64),
        np.zeros(eob.size, dtype=np.int64),
        np.zeros(eob.size, dtype=np.int64),
    )
    merged = [np.concatenate(parts) for parts in zip(dc_tok, ac_tok, eob_tok, strict=True)]
    return merged[0], merged[1], merged[2], merged[3], merged[4], merged[5]


#: Bits packed per `_pack_entropy` pass. The exploded form costs 17 bytes per
#: output *bit* (two int64 index vectors plus the bit itself), so packing a whole
#: image at once peaked at ~130 MB for a 1 MB entropy stream. Bit packing is not
#: chunk-independent — group boundaries land mid-byte — so each pass carries its
#: leftover bits into the next one, which keeps the byte stream identical.
_ENTROPY_BIT_CHUNK = 1 << 18


def _pack_entropy(chunk: np.ndarray, nbits: np.ndarray) -> bytes:
    """MSB-first bit packing of (value, bit-count) chunks, with 1-padding to a
    byte boundary and 0x00 stuffing after every 0xFF (both per T.81).

    Packed in bounded passes: token groups of at most `_ENTROPY_BIT_CHUNK` bits,
    with sub-byte remainders carried across group boundaries so the emitted bytes
    are exactly those of a single whole-image pass. Byte stuffing is per-byte
    local, so it applies per group.
    """
    total = int(nbits.sum())
    cum = np.cumsum(nbits)
    # Token index at each bit-budget boundary: a group is [t0, t1) tokens, and a
    # single token never spans groups (its bits stay contiguous, as before).
    edges = np.searchsorted(
        cum, np.arange(_ENTROPY_BIT_CHUNK, total, _ENTROPY_BIT_CHUNK), side="left"
    )
    bounds = [0, *(int(e) + 1 for e in edges), chunk.size]
    parts: list[bytes] = []
    carry = np.empty(0, dtype=np.uint8)
    for t0, t1 in itertools.pairwise(bounds):
        if t1 <= t0:
            continue
        values = chunk[t0:t1]
        widths = nbits[t0:t1]
        group_total = int(widths.sum())
        start = np.cumsum(widths) - widths
        idx = np.repeat(np.arange(values.size, dtype=np.int64), widths)
        offset = np.arange(group_total, dtype=np.int64) - np.repeat(start, widths)
        bits = ((values[idx] >> (widths[idx] - 1 - offset)) & 1).astype(np.uint8)
        if carry.size:
            bits = np.concatenate((carry, bits))
        whole = (bits.size // 8) * 8
        if t1 == chunk.size:
            # Final group: 1-pad the tail to a byte boundary (T.81).
            pad = (-bits.size) % 8
            if pad:
                bits = np.concatenate((bits, np.ones(pad, dtype=np.uint8)))
            whole = bits.size
            carry = np.empty(0, dtype=np.uint8)
        else:
            carry = bits[whole:].copy()
        stream = np.packbits(bits[:whole])
        ff = np.flatnonzero(stream == 0xFF)
        if ff.size:
            stream = np.insert(stream, ff + 1, np.uint8(0))
        parts.append(stream.tobytes())
    return b"".join(parts)


def _headers(h: int, w: int, qy_zz: np.ndarray, qc_zz: np.ndarray) -> bytes:
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x02"  # identifier + version 1.02
        + b"\x01"  # density unit: dots per inch
        + struct.pack(">HHBB", 96, 96, 0, 0)  # 96 DPI, no thumbnail
    )
    dqt = (
        b"\xff\xdb"
        + struct.pack(">H", 2 + 65 * 2)
        + b"\x00"  # 8-bit precision, table 0 (luma)
        + qy_zz.astype(np.uint8).tobytes()
        + b"\x01"  # table 1 (chroma)
        + qc_zz.astype(np.uint8).tobytes()
    )
    # 4:4:4: every component samples at 1×1 (0x11); Y quantizes with table 0,
    # Cb/Cr with table 1.
    sof0 = (
        b"\xff\xc0"
        + struct.pack(">HBHHB", 17, 8, h, w, 3)
        + bytes((1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1))
    )
    dht_payload = b"".join(
        bytes([cls_id]) + bits + values
        for cls_id, (bits, values) in zip((0x00, 0x10, 0x01, 0x11), _HUFF_SPECS, strict=True)
    )
    dht = b"\xff\xc4" + struct.pack(">H", 2 + len(dht_payload)) + dht_payload
    sos = (
        b"\xff\xda"
        + struct.pack(">HB", 12, 3)
        + bytes((1, 0x00, 2, 0x11, 3, 0x11))  # Y → tables 0/0, chroma → 1/1
        + b"\x00\x3f\x00"  # full spectral selection, no successive approx.
    )
    return b"\xff\xd8" + app0 + dqt + sof0 + dht + sos


def _gathered(fields: list[list[np.ndarray]], index: int, order: np.ndarray) -> np.ndarray:
    """One token field, concatenated across components into MCU order.

    The per-component pieces are released as they are joined, so a field costs
    one joined copy plus the gathered result rather than both plus the parts —
    each is an int64 per token, and a photographic image has millions. `parts`
    is dropped explicitly rather than left to the frame: a local stays alive
    until the function returns, so `return np.concatenate(parts)[order]` would
    hold the pieces, the join, *and* the gather at once.
    """
    parts = [f[index] for f in fields]
    for f in fields:
        f[index] = _EMPTY_I64
    joined = np.concatenate(parts)
    del parts
    gathered = joined[order]
    del joined
    return gathered


def encode(rgba: np.ndarray, *, quality: int = 90) -> bytes:
    """Encode an `(h, w, 4)` RGBA (alpha ignored) or `(h, w, 3)` RGB uint8
    image as a baseline JFIF JPEG. Deterministic for identical input."""
    if isinstance(quality, bool) or not isinstance(quality, int):
        raise ValueError(f"quality must be an int in 1..100, got {quality!r}")
    if not 1 <= quality <= 100:
        raise ValueError(f"quality must be in 1..100, got {quality}")
    if not isinstance(rgba, np.ndarray):
        raise ValueError(f"JPEG image must be a numpy array, got {type(rgba).__name__}")
    if rgba.ndim != 3 or rgba.shape[2] not in (3, 4):
        raise ValueError(f"JPEG image must be (h, w, 4) RGBA or (h, w, 3) RGB, got {rgba.shape}")
    if rgba.dtype != np.uint8:
        raise ValueError(f"JPEG image must be uint8, got {rgba.dtype}")
    h, w = rgba.shape[:2]
    if h == 0 or w == 0:
        raise ValueError("JPEG image must be non-empty")
    if h > 65535 or w > 65535:
        raise ValueError("JPEG dimensions are limited to 65535")

    # Alpha is ignored: the caller has already composited onto an opaque
    # background, so only the RGB planes carry information.
    rgb = rgba[..., :3].astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # JFIF BT.601 full-range transform. The −128 DCT level shift cancels the
    # +128 chroma offset, so Y is shifted here and Cb/Cr are left centered.
    y = 0.299 * r + 0.587 * g + 0.114 * b - 128.0
    cb = -0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 0.5 * r - 0.418688 * g - 0.081312 * b
    # The interleaved f32 source is dead once the planes exist, and it is three
    # floats per pixel — hand it back before the per-component pipeline runs.
    # (`r`/`g`/`b` are views into it, so all four references have to go.)
    del rgb, r, g, b

    qy = _scaled_quant(_QUANT_LUMA, quality)
    qc = _scaled_quant(_QUANT_CHROMA, quality)
    qy_zz = qy[_ZIGZAG]
    qc_zz = qc[_ZIGZAG]

    pad_h, pad_w = (-h) % 8, (-w) % 8
    h8, w8 = h + pad_h, w + pad_w
    fields: list[list[np.ndarray]] = []
    keys: list[np.ndarray] = []
    # Planes are released as they are consumed (one float per pixel each), so the
    # pipeline holds one component's working set instead of all three.
    planes: list[Optional[np.ndarray]] = [y, cb, cr]
    del y, cb, cr
    for comp, q_zz in enumerate((qy_zz, qc_zz, qc_zz)):
        plane = planes[comp]
        planes[comp] = None
        assert plane is not None
        # Edge replication avoids the ringing a zero/black pad would inject
        # into every border block.
        padded = np.pad(plane, ((0, pad_h), (0, pad_w)), mode="edge")
        del plane
        blocks = padded.reshape(h8 // 8, 8, w8 // 8, 8).swapaxes(1, 2).reshape(-1, 8, 8)
        del padded
        coef = _DCT @ blocks @ _DCT.T
        del blocks
        # The zigzag gather is a fresh array, so the divide, the round, and the
        # sign restore all run in place on it: same f32 operations in the same
        # order as the one-shot chain, five fewer full-size temporaries.
        scaled = coef.reshape(-1, 64)[:, _ZIGZAG]
        del coef
        scaled /= q_zz.astype(np.float32)
        # Round half away from zero: any deterministic tie rule is valid JPEG;
        # this one matches the common integer implementations. `trunc(x + ±0.5)`
        # is that rule in three in-place passes and one temporary, where
        # `sign(x) * floor(|x| + 0.5)` took four passes and four full-size
        # temporaries. It is exact, not approximate: IEEE addition is
        # sign-symmetric, so for x < 0 the sum is the exact negation of
        # `|x| + 0.5`, and truncation toward zero then matches the floor of that
        # magnitude. The ±0 cases land on ±0.0 either way and integer-cast to 0.
        bias = np.copysign(np.float32(0.5), scaled)
        scaled += bias
        del bias
        np.trunc(scaled, out=scaled)
        quant = scaled.astype(np.int64)
        del scaled
        # Exact-math AC magnitudes cap at 1020 (category 10); clamp is one-LSB
        # insurance against float rounding ever minting category 11, which the
        # baseline AC tables cannot code.
        quant[:, 1:] = np.clip(quant[:, 1:], -1023, 1023)
        dc_tbl, ac_tbl = (0, 1) if comp == 0 else (2, 3)
        toks = _component_tokens(quant, dc_tbl, ac_tbl)
        del quant
        # 4:4:4 → one block per component per MCU, so the MCU-interleaved
        # order Y, Cb, Cr is a stable sort on (block, component, in-block seq).
        keys.append(((toks[0] * 3 + comp) << 8) | toks[1])
        # Only the four emitted fields outlive the key: the block and in-block
        # sequence numbers are folded into it, and on a photographic image each
        # dropped field is an int64 per token.
        fields.append(list(toks[2:]))
        del toks

    order = np.argsort(np.concatenate(keys), kind="stable")
    keys.clear()
    tbl = _gathered(fields, 0, order)
    sym = _gathered(fields, 1, order)
    ampl = _gathered(fields, 2, order)
    abits = _gathered(fields, 3, order)
    del fields
    code = _HUFF_CODES[tbl, sym]
    clen = _HUFF_LENS[tbl, sym]
    del tbl, sym
    # Huffman code then amplitude bits, as one ≤27-bit chunk per token. Both
    # gathers are fresh arrays, so the combine runs in place.
    code <<= abits
    code |= ampl
    clen += abits
    del ampl, abits
    entropy = _pack_entropy(code, clen)
    del code, clen

    return _headers(h, w, qy_zz, qc_zz) + entropy + b"\xff\xd9"
