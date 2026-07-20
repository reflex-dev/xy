"""Pure-Python/numpy lossless WebP (VP8L) encoder for static export.

`encode` emits a RIFF/WEBP container holding a single VP8L chunk, using the
"simple lossless" subset of the format (RFC 9649):

- no transforms, no color cache, one meta prefix group;
- five canonical, length-limited (<=15) prefix codes built from the actual
  token histograms, in spec order: green+length (280), red, blue, alpha (256
  each), distance (40);
- pixels emitted in scan order as literals (green, red, blue, alpha), except
  runs of identical consecutive pixels, which become LZ77 distance-1 backward
  references — charts are mostly flat fills, so runs shrink output hugely.

Round-trips are bit-exact, alpha included. Like `_png.py` this stays pure
Python/numpy + stdlib: static export favors zero extra dependencies, while the
latency-first pyplot path owns the Rust encoders. The bitstream is assembled
as parallel (value, nbits) arrays and packed LSB-first (VP8L bit order) with a
vectorized pass per bit position, so chart-sized rasters encode in well under
a second instead of minutes of per-symbol Python.
"""

from __future__ import annotations

import struct

import numpy as np

_MAX_DIM = 1 << 14  # VP8L stores (dim - 1) in 14 bits
_MAX_RUN = 4096  # length prefix code 23 tops out at 4096 pixels
_GREEN_ALPHABET = 256 + 24  # literals + length prefix codes (no color cache)
_DIST_ALPHABET = 40
# Spec transmission order for the 19 code-length-code lengths (note 16 riding
# between 5 and 6 — codes whose lengths stay <=5 never reveal a wrong tail).
_CODE_LENGTH_ORDER = (17, 18, 0, 1, 2, 3, 4, 5, 16, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)


def _length_prefix_lut() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(prefix code, extra-bit count, extra-bit value) for lengths 1.._MAX_RUN.

    Spec mapping: codes 0-3 are lengths 1-4; beyond that the code stores the
    two leading bits of (length - 1) and the remainder rides as extra bits.
    """
    codes = np.zeros(_MAX_RUN + 1, np.uint16)
    ebits = np.zeros(_MAX_RUN + 1, np.uint8)
    extra = np.zeros(_MAX_RUN + 1, np.uint16)
    for v in range(1, _MAX_RUN + 1):
        if v <= 4:
            codes[v] = v - 1
        else:
            d = v - 1
            hb = d.bit_length() - 1
            codes[v] = 2 * hb + ((d >> (hb - 1)) & 1)
            ebits[v] = hb - 1
            extra[v] = d & ((1 << (hb - 1)) - 1)
    return codes, ebits, extra


_LP_CODE, _LP_EBITS, _LP_EXTRA = _length_prefix_lut()


def _limited_lengths(freqs: np.ndarray, limit: int) -> np.ndarray:
    """Optimal length-limited prefix code lengths via package-merge.

    Optimal codes over all-positive frequencies are Kraft-complete, which the
    libwebp table builder requires (an under-full code is a decode error).
    Alphabets here are <=280 so the O(limit * n log n) list form is plenty.
    """
    lengths = np.zeros(freqs.size, np.uint8)
    used = np.flatnonzero(freqs)
    if used.size == 0:
        return lengths
    if used.size == 1:
        lengths[used[0]] = 1
        return lengths
    # Items are (weight, symbols-tuple); tuple compare breaks weight ties
    # deterministically, so output is stable across runs.
    leaves = sorted((int(freqs[s]), (int(s),)) for s in used)
    current = list(leaves)
    for _ in range(limit - 1):
        packages = [
            (current[i][0] + current[i + 1][0], current[i][1] + current[i + 1][1])
            for i in range(0, len(current) - 1, 2)
        ]
        current = sorted(leaves + packages)
    for _, syms in current[: 2 * (used.size - 1)]:
        for s in syms:
            lengths[s] += 1
    return lengths


def _reverse_bits(code: int, nbits: int) -> int:
    r = 0
    for _ in range(nbits):
        r = (r << 1) | (code & 1)
        code >>= 1
    return r


def _canonical_rev_codes(lengths: np.ndarray) -> np.ndarray:
    """Canonical (RFC 1951 style) codes, pre-reversed for the LSB-first stream.

    VP8L reads a prefix code most-significant-bit first while the byte stream
    fills LSB-first, so codes are written reversed — reversing here lets the
    emitters use the table directly.
    """
    codes = np.zeros(lengths.size, np.uint64)
    max_len = int(lengths.max())
    bl_count = np.bincount(lengths, minlength=max_len + 1)
    next_code = [0] * (max_len + 1)
    code = 0
    for length in range(1, max_len + 1):
        code = (code + int(bl_count[length - 1])) << 1
        next_code[length] = code
    for sym in range(lengths.size):
        n = int(lengths[sym])
        if n:
            codes[sym] = _reverse_bits(next_code[n], n)
            next_code[n] += 1
    return codes


def _write_normal_code(put, lengths: np.ndarray, alphabet_size: int) -> None:
    """Emit a prefix code via the code-length-code path.

    Code lengths go out as plain literals (no 16/17/18 repeats — the spec does
    not require them and skipping them keeps this path simple); the max-symbol
    field truncates the trailing zeros instead.
    """
    put(0, 1)  # not a simple code
    last = int(np.flatnonzero(lengths)[-1])
    emitted = lengths[: last + 1]
    cl_hist = np.bincount(emitted, minlength=19)
    cl_used = np.flatnonzero(cl_hist)
    cl_len = np.zeros(19, np.uint8)
    cl_code = np.zeros(19, np.uint64)
    if cl_used.size == 1:
        # Single-symbol code-length code: declare length 1; the decoder builds
        # a trivial 0-bit code, so the literal emissions below cost nothing.
        cl_declared = np.zeros(19, np.uint8)
        cl_declared[cl_used[0]] = 1
    else:
        cl_declared = _limited_lengths(cl_hist, 7)  # declared in 3 bits: <=7
        cl_len = cl_declared
        cl_code = _canonical_rev_codes(cl_declared)
    last_pos = max(i for i, s in enumerate(_CODE_LENGTH_ORDER) if cl_declared[s])
    num_cl = max(4, last_pos + 1)
    put(num_cl - 4, 4)
    for i in range(num_cl):
        put(int(cl_declared[_CODE_LENGTH_ORDER[i]]), 3)
    if last + 1 == alphabet_size:
        put(0, 1)  # no max-symbol field; every length is spelled out
    else:
        put(1, 1)
        val = (last + 1) - 2  # >= 0: single-symbol codes never reach here
        sel = 0
        while val >= (1 << (2 + 2 * sel)):
            sel += 1
        put(sel, 3)
        put(val, 2 + 2 * sel)
    for length in emitted:
        put(int(cl_code[length]), int(cl_len[length]))


def _write_prefix_code(put, hist: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Write one prefix-code header; return (bit length, reversed code) LUTs.

    Codes with <=2 used symbols that fit in 8 bits take the simple-code path;
    everything else goes through the code-length code. A 1-symbol code decodes
    as 0 bits per read on either path, so its emission LUT stays all-zero.
    """
    emit_len = np.zeros(hist.size, np.uint8)
    emit_code = np.zeros(hist.size, np.uint64)
    used = np.flatnonzero(hist)
    if used.size == 0:
        # Unused alphabet (distance, when nothing repeats): cheapest wellformed
        # code is the 1-symbol simple code for symbol 0.
        put(1, 1)
        put(0, 1)
        put(0, 1)
        put(0, 1)
        return emit_len, emit_code
    if used.size <= 2 and used[-1] <= 255:
        put(1, 1)  # simple code
        put(int(used.size - 1), 1)  # num_symbols - 1
        s0 = int(used[0])
        if s0 <= 1:
            put(0, 1)
            put(s0, 1)
        else:
            put(1, 1)
            put(s0, 8)
        if used.size == 2:
            put(int(used[1]), 8)
            # Canonical over lengths [1, 1]: smaller symbol gets code 0.
            emit_len[used] = 1
            emit_code[used[1]] = 1
        return emit_len, emit_code
    if used.size == 1:
        # One symbol above 255 (a green length code) cannot ride the simple
        # path; declare it through the normal path and emit 0 bits per use.
        lengths = np.zeros(hist.size, np.uint8)
        lengths[used[0]] = 1
    else:
        lengths = _limited_lengths(hist, 15)
        emit_len = lengths
        emit_code = _canonical_rev_codes(lengths)
    _write_normal_code(put, lengths, hist.size)
    return emit_len, emit_code


def _pack_lsb(values: np.ndarray, nbits: np.ndarray) -> bytes:
    """Pack (value, nbits) pairs into an LSB-first byte stream.

    Expands to one uint8 per bit and lets packbits fold them: one vectorized
    pass per bit *position* (<= ~40) instead of a Python loop per symbol.
    """
    ends = np.cumsum(nbits, dtype=np.int64)
    starts = ends - nbits
    bits = np.zeros(int(ends[-1]), np.uint8)
    for k in range(int(nbits.max())):
        m = nbits > k
        bits[starts[m] + k] = (values[m] >> np.uint64(k)) & np.uint64(1)
    return np.packbits(bits, bitorder="little").tobytes()


def encode(rgba: np.ndarray) -> bytes:
    """Encode an `(h, w, 4)` uint8 RGBA image (or `(h, w, 3)`, treated as
    opaque) as a lossless WebP. Alpha survives bit-exact."""
    if not isinstance(rgba, np.ndarray) or rgba.dtype != np.uint8:
        raise ValueError("WebP image must be a uint8 numpy array")
    if rgba.ndim != 3 or rgba.shape[2] not in (3, 4):
        raise ValueError("WebP image must be (h, w, 4) RGBA or (h, w, 3) RGB")
    h, w = int(rgba.shape[0]), int(rgba.shape[1])
    if not (1 <= w <= _MAX_DIM and 1 <= h <= _MAX_DIM):
        raise ValueError(f"WebP dimensions must be 1..{_MAX_DIM}, got {w}x{h}")
    if rgba.shape[2] == 3:
        rgba = np.concatenate([rgba, np.full((h, w, 1), 255, np.uint8)], axis=2)
    flat = np.ascontiguousarray(rgba).reshape(-1, 4)
    alpha_used = bool((flat[:, 3] != 255).any())

    # --- tokenize: one literal per run of identical pixels, the remainder as
    # distance-1 backward references chunked to the 4096-pixel length cap.
    keys = flat.view(np.uint32).ravel()
    change = np.flatnonzero(keys[:-1] != keys[1:])
    starts = np.empty(change.size + 1, np.int64)
    starts[0] = 0
    starts[1:] = change + 1
    seg_len = np.diff(np.append(starts, keys.size))
    rem = seg_len - 1
    kfull = rem // _MAX_RUN
    tail = rem % _MAX_RUN
    nref = kfull + (tail > 0)
    n_ref = int(nref.sum())
    if n_ref:
        seg_of = np.repeat(np.arange(starts.size), nref)
        rank = np.arange(n_ref) - np.repeat(np.cumsum(nref) - nref, nref)
        run = np.where(rank < kfull[seg_of], _MAX_RUN, tail[seg_of])
        ref_sym = (256 + _LP_CODE[run]).astype(np.int64)
    else:
        run = ref_sym = np.zeros(0, np.int64)

    lit = flat[starts]
    g_hist = np.bincount(lit[:, 1], minlength=_GREEN_ALPHABET)
    if n_ref:
        g_hist += np.bincount(ref_sym, minlength=_GREEN_ALPHABET)
    d_hist = np.zeros(_DIST_ALPHABET, np.int64)
    # Distance 1 maps to neighbor code 2 (offset (1, 0)), whose prefix code is
    # 1 with zero extra bits — the only distance symbol this encoder emits.
    d_hist[1] = n_ref

    # --- header + the five prefix-code descriptions (spec order).
    head_vals: list[int] = []
    head_bits: list[int] = []

    def put(v: int, n: int) -> None:
        head_vals.append(v)
        head_bits.append(n)

    put(0x2F, 8)  # VP8L signature
    put(w - 1, 14)
    put(h - 1, 14)
    put(1 if alpha_used else 0, 1)
    put(0, 3)  # version
    put(0, 1)  # no transforms
    put(0, 1)  # no color cache
    put(0, 1)  # no meta prefix image: one code group for the whole image
    g_len, g_code = _write_prefix_code(put, g_hist)
    r_len, r_code = _write_prefix_code(put, np.bincount(lit[:, 0], minlength=256))
    b_len, b_code = _write_prefix_code(put, np.bincount(lit[:, 2], minlength=256))
    a_len, a_code = _write_prefix_code(put, np.bincount(lit[:, 3], minlength=256))
    d_len, d_code = _write_prefix_code(put, d_hist)

    # --- token stream as (value, nbits) entries: two per literal (green+red,
    # blue+alpha packed pairwise, <=30 bits each) and one per reference
    # (length code + extra bits + distance code, <=40 bits).
    per_seg = 2 + nref
    offsets = np.cumsum(per_seg) - per_seg
    ev = np.zeros(int(per_seg.sum()), np.uint64)
    eb = np.zeros(ev.size, np.uint8)
    gi, ri, bi, ai = lit[:, 1], lit[:, 0], lit[:, 2], lit[:, 3]
    ev[offsets] = g_code[gi] | (r_code[ri] << g_len[gi].astype(np.uint64))
    eb[offsets] = g_len[gi] + r_len[ri]
    ev[offsets + 1] = b_code[bi] | (a_code[ai] << b_len[bi].astype(np.uint64))
    eb[offsets + 1] = b_len[bi] + a_len[ai]
    if n_ref:
        pos = offsets[seg_of] + 2 + rank
        shift = g_len[ref_sym].astype(np.uint64)
        ev[pos] = (
            g_code[ref_sym]
            | (_LP_EXTRA[run].astype(np.uint64) << shift)
            | (d_code[1] << (shift + _LP_EBITS[run]))
        )
        eb[pos] = g_len[ref_sym] + _LP_EBITS[run] + d_len[1]

    payload = _pack_lsb(
        np.concatenate([np.asarray(head_vals, np.uint64), ev]),
        np.concatenate([np.asarray(head_bits, np.uint8), eb]),
    )
    chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        chunk += b"\x00"  # RIFF chunks are even-aligned; pad byte is unsized
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
