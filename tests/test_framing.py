from __future__ import annotations

import base64
import json
import struct
import subprocess
from pathlib import Path

import pytest

from xy.channel import (
    FRAME_ALIGNMENT,
    FRAME_HEADER_SIZE,
    FRAME_MAGIC,
    FRAME_VERSION,
    FrameDecodeError,
    FrameEncodeError,
    FrameLimits,
    decode_frame,
    encode_frame,
    encode_frame_parts,
)

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "python" / "xy" / "static" / "index.js"
HEADER = struct.Struct("<4sBBHIIQ")
U64 = struct.Struct("<Q")


def _node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(completed.stdout)


def _raw_frame(metadata: bytes, buffers: list[bytes] | None = None) -> bytes:
    buffers = buffers or []
    position = (FRAME_HEADER_SIZE + len(metadata) + 7) & ~7
    total = position
    for buffer in buffers:
        total = (total + 8 + len(buffer) + 7) & ~7
    parts = [
        HEADER.pack(
            FRAME_MAGIC,
            FRAME_VERSION,
            0,
            FRAME_HEADER_SIZE,
            len(metadata),
            len(buffers),
            total,
        ),
        metadata,
        b"\x00" * (position - FRAME_HEADER_SIZE - len(metadata)),
    ]
    for buffer in buffers:
        parts.extend((U64.pack(len(buffer)), buffer))
        position += 8 + len(buffer)
        padding = (-position) % 8
        parts.append(b"\x00" * padding)
        position += padding
    return b"".join(parts)


def test_frame_header_and_buffer_offsets_are_eight_byte_aligned() -> None:
    body = encode_frame({"type": "density_update", "label": "μ"}, [b"abc", b"", bytes(17)])
    magic, version, flags, header_size, metadata_len, count, total = HEADER.unpack_from(body)

    assert (magic, version, flags, header_size) == (
        FRAME_MAGIC,
        FRAME_VERSION,
        0,
        FRAME_HEADER_SIZE,
    )
    assert count == 3
    assert total == len(body)
    position = (FRAME_HEADER_SIZE + metadata_len + 7) & ~7
    for expected in (b"abc", b"", bytes(17)):
        (length,) = U64.unpack_from(body, position)
        position += U64.size
        assert position % FRAME_ALIGNMENT == 0
        assert body[position : position + length] == expected
        position = (position + length + 7) & ~7
    assert position == len(body)


def test_encode_parts_retain_mutable_payload_owner_until_join() -> None:
    owner = bytearray(b"payload")
    parts = encode_frame_parts({"type": "test"}, [owner])
    payload_parts = [part for part in parts if isinstance(part, memoryview)]

    assert len(payload_parts) == 1
    assert payload_parts[0].obj is owner
    owner[0] = ord("P")
    assert bytes(decode_frame(b"".join(parts)).buffers[0]) == b"Payload"


@pytest.mark.parametrize(
    "message",
    [
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": object()},
    ],
)
def test_encoder_rejects_non_strict_json(message: dict) -> None:
    with pytest.raises(FrameEncodeError, match="strict JSON"):
        encode_frame(message)


def test_encoder_rejects_noncontiguous_buffer() -> None:
    view = memoryview(bytearray(range(10)))[::2]
    with pytest.raises(FrameEncodeError, match="C-contiguous"):
        encode_frame({}, [view])


def test_limits_apply_to_encode_and_decode() -> None:
    limits = FrameLimits(
        max_frame_bytes=128,
        max_metadata_bytes=32,
        max_buffers=1,
        max_buffer_bytes=16,
    )
    with pytest.raises(FrameEncodeError, match="buffer count"):
        encode_frame({}, [b"a", b"b"], limits=limits)
    with pytest.raises(FrameEncodeError, match="buffer 0 length"):
        encode_frame({}, [bytes(17)], limits=limits)
    with pytest.raises(FrameEncodeError, match="metadata length"):
        encode_frame({"long": "x" * 40}, limits=limits)
    with pytest.raises(FrameEncodeError, match="frame length"):
        encode_frame(
            {},
            [b"a"],
            limits=FrameLimits(
                max_frame_bytes=32,
                max_metadata_bytes=8,
                max_buffers=1,
                max_buffer_bytes=8,
            ),
        )

    body = encode_frame({}, [bytes(16)])
    with pytest.raises(FrameDecodeError, match="buffer 0 length"):
        decode_frame(body, limits=FrameLimits(max_buffer_bytes=8))
    with pytest.raises(FrameDecodeError, match="frame length"):
        decode_frame(
            body,
            limits=FrameLimits(
                max_frame_bytes=len(body) - 1,
                max_metadata_bytes=32,
                max_buffers=1,
                max_buffer_bytes=16,
            ),
        )
    body = encode_frame({}, [b"a", b"b"])
    with pytest.raises(FrameDecodeError, match="buffer count"):
        decode_frame(body, limits=FrameLimits(max_buffers=1))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_frame_bytes": 0},
        {"max_buffers": True},
        {"max_metadata_bytes": 2, "max_frame_bytes": 1},
        {"max_buffer_bytes": 2, "max_frame_bytes": 1},
    ],
)
def test_frame_limits_validate(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        FrameLimits(**kwargs)


def test_decoder_rejects_every_truncation_and_trailing_byte() -> None:
    body = encode_frame({"type": "selection", "text": "hello"}, [bytes(range(32)), b"abc"])
    for cut in range(len(body)):
        with pytest.raises(FrameDecodeError):
            decode_frame(body[:cut])
    with pytest.raises(FrameDecodeError, match="declared frame length"):
        decode_frame(body + b"\x00")


@pytest.mark.parametrize(
    ("offset", "value", "match"),
    [
        (0, b"NOPE", "magic"),
        (4, b"\x02", "version"),
        (5, b"\x01", "flags"),
        (6, struct.pack("<H", 32), "header size"),
        (16, struct.pack("<Q", 1), "declared frame length"),
    ],
)
def test_decoder_rejects_corrupt_header(offset: int, value: bytes, match: str) -> None:
    body = bytearray(encode_frame({"type": "pick_result"}, [b"abc"]))
    body[offset : offset + len(value)] = value
    with pytest.raises(FrameDecodeError, match=match):
        decode_frame(body)


def test_decoder_rejects_nonzero_metadata_and_buffer_padding() -> None:
    body = bytearray(encode_frame({"a": 1}, [b"abc"]))
    (_, _, _, _, metadata_len, _, _) = HEADER.unpack_from(body)
    metadata_end = FRAME_HEADER_SIZE + metadata_len
    body[metadata_end] = 1
    with pytest.raises(FrameDecodeError, match="metadata padding"):
        decode_frame(body)

    body = bytearray(encode_frame({}, [b"abc"]))
    (_, _, _, _, metadata_len, _, _) = HEADER.unpack_from(body)
    position = (FRAME_HEADER_SIZE + metadata_len + 7) & ~7
    position += 8 + 3
    body[position] = 1
    with pytest.raises(FrameDecodeError, match="buffer 0 padding"):
        decode_frame(body)


@pytest.mark.parametrize(
    ("metadata", "match"),
    [
        (b"[]", "object"),
        (b'{"bad":NaN}', "metadata JSON"),
        (b"\xff", "metadata JSON"),
    ],
)
def test_decoder_rejects_invalid_metadata(metadata: bytes, match: str) -> None:
    with pytest.raises(FrameDecodeError, match=match):
        decode_frame(_raw_frame(metadata))


def test_javascript_decodes_python_golden_frame_without_payload_copies() -> None:
    message = {"type": "density_update", "seq": 9, "label": "東京"}
    buffers = [bytes(range(251)), b"", b"unaligned-length"]
    body = encode_frame(message, buffers)
    encoded = base64.b64encode(body).decode("ascii")
    script = f"""
      import {{ decodeFrame }} from {CLIENT.as_uri()!r};
      const source = Uint8Array.from(Buffer.from({encoded!r}, 'base64'));
      const decoded = decodeFrame(source.buffer);
      const result = {{
        message: decoded.message,
        buffers: decoded.buffers.map((value) =>
          Buffer.from(value.buffer, value.byteOffset, value.byteLength).toString('base64')),
        offsets: decoded.buffers.map((value) => value.byteOffset),
        sameBacking: decoded.buffers.every((value) => value.buffer === source.buffer),
      }};
      process.stdout.write(JSON.stringify(result));
    """

    result = _node(script)

    assert result["message"] == message
    assert [base64.b64decode(value) for value in result["buffers"]] == buffers
    assert result["sameBacking"] is True
    assert all(offset % FRAME_ALIGNMENT == 0 for offset in result["offsets"])


def test_javascript_rejects_malformed_and_unaligned_frames() -> None:
    valid = encode_frame({"type": "selection"}, [b"abc", b"def"])
    cases: list[bytes] = [valid[:cut] for cut in (0, 1, 23, 24, len(valid) - 1)]
    for offset, value in ((0, b"NOPE"), (4, b"\x02"), (5, b"\x01")):
        corrupt = bytearray(valid)
        corrupt[offset : offset + len(value)] = value
        cases.append(bytes(corrupt))
    encoded_cases = [base64.b64encode(case).decode("ascii") for case in cases]
    valid_encoded = base64.b64encode(valid).decode("ascii")
    script = f"""
      import {{ decodeFrame }} from {CLIENT.as_uri()!r};
      const cases = {json.dumps(encoded_cases)};
      const rejected = cases.map((encoded) => {{
        const source = Uint8Array.from(Buffer.from(encoded, 'base64'));
        try {{ decodeFrame(source.buffer); return false; }} catch (_error) {{ return true; }}
      }});
      const valid = Uint8Array.from(Buffer.from({valid_encoded!r}, 'base64'));
      const unalignedOwner = new Uint8Array(valid.byteLength + 1);
      unalignedOwner.set(valid, 1);
      let unalignedRejected = false;
      try {{ decodeFrame(unalignedOwner.subarray(1)); }} catch (_error) {{ unalignedRejected = true; }}
      let limitRejected = false;
      try {{ decodeFrame(valid.buffer, {{maxBuffers: 1}}); }} catch (_error) {{ limitRejected = true; }}
      process.stdout.write(JSON.stringify({{rejected, unalignedRejected, limitRejected}}));
    """

    result = _node(script)

    assert all(result["rejected"])
    assert result["unalignedRejected"] is True
    assert result["limitRejected"] is True


def test_widget_entry_no_longer_slices_binary_views() -> None:
    source = (ROOT / "js" / "src" / "60_entries.js").read_text(encoding="utf-8")
    built = CLIENT.read_text(encoding="utf-8")
    assert 'payloadBuffers(spec, model.get("buffers"))' in source
    assert "raw.map(bytesToSpan)" in source
    assert ".buffer.slice(b.byteOffset" not in source
    assert "function decodeFrame(" in built
