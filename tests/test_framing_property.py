from __future__ import annotations

import base64
import json
import struct
import subprocess
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from xy.channel import FrameDecodeError, decode_frame, encode_frame

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "python" / "xy" / "static" / "index.js"
HEADER = struct.Struct("<4sBBHIIQ")
U64 = struct.Struct("<Q")


JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    st.text(max_size=32),
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=16), children, max_size=5),
    ),
    max_leaves=20,
)


@settings(max_examples=100, deadline=None)
@given(
    message=st.dictionaries(st.text(max_size=16), JSON_VALUES, max_size=8),
    buffers=st.lists(st.binary(max_size=256), max_size=8),
)
def test_python_frame_round_trip_is_zero_copy(message: dict, buffers: list[bytes]) -> None:
    body = encode_frame(message, buffers)

    decoded = decode_frame(body)

    assert decoded.message == message
    assert [bytes(buffer) for buffer in decoded.buffers] == buffers
    assert all(buffer.obj is body for buffer in decoded.buffers)


def _align(value: int) -> int:
    return (value + 7) & ~7


def _frame_positions(body: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    _magic, _version, _flags, _header_size, metadata_len, count, _total = HEADER.unpack_from(body)
    metadata_end = 24 + metadata_len
    position = _align(metadata_end)
    buffers: list[tuple[int, int, int, int]] = []
    for _index in range(count):
        length_position = position
        (length,) = U64.unpack_from(body, length_position)
        start = length_position + U64.size
        end = start + length
        padded_end = _align(end)
        buffers.append((length_position, start, end, padded_end))
        position = padded_end
    return metadata_end, _align(metadata_end), buffers


def _mutations(body: bytes, selector: int, xor_value: int) -> dict[str, bytes]:
    metadata_end, metadata_padded_end, buffers = _frame_positions(body)
    _magic, version, _flags, header_size, metadata_len, count, _total = HEADER.unpack_from(body)

    def changed(offset: int, value: bytes) -> bytes:
        mutated = bytearray(body)
        mutated[offset : offset + len(value)] = value
        return bytes(mutated)

    metadata_byte = 24 + selector % metadata_len
    metadata_mutation = bytearray(body)
    metadata_mutation[metadata_byte] ^= xor_value
    metadata_padding = bytearray(body)
    assert metadata_padded_end > metadata_end
    metadata_padding[metadata_end] = xor_value
    first_length, _first_start, first_end, _first_padded_end = buffers[0]
    (first_size,) = U64.unpack_from(body, first_length)
    last_length, _last_start, last_end, last_padded_end = buffers[-1]
    assert last_padded_end > last_end
    buffer_padding = bytearray(body)
    buffer_padding[last_end] = xor_value

    return {
        "header_magic": changed(0, bytes([body[0] ^ xor_value])),
        "header_version": changed(4, bytes([(version + 1) & 0xFF])),
        "header_flags": changed(5, b"\x01"),
        "header_size": changed(6, struct.pack("<H", header_size + 8)),
        "metadata_length": changed(8, struct.pack("<I", metadata_len + 1)),
        "buffer_count": changed(12, struct.pack("<I", count + 1)),
        "total_length": changed(16, struct.pack("<Q", len(body) + 1)),
        "metadata": bytes(metadata_mutation),
        "metadata_padding": bytes(metadata_padding),
        "buffer_length": changed(first_length, struct.pack("<Q", first_size + 1)),
        "buffer_padding": bytes(buffer_padding),
        "truncation": body[:first_end],
    }


def _python_decode_result(body: bytes) -> dict:
    try:
        decoded = decode_frame(body)
    except FrameDecodeError:
        return {"ok": False}
    return {
        "ok": True,
        "message": decoded.message,
        "buffers": [base64.b64encode(buffer).decode("ascii") for buffer in decoded.buffers],
    }


def _javascript_decode_results(bodies: list[bytes]) -> list[dict]:
    encoded = [base64.b64encode(body).decode("ascii") for body in bodies]
    script = f"""
      import {{ decodeFrame }} from {CLIENT.as_uri()!r};
      const results = {json.dumps(encoded)}.map((encoded) => {{
        const source = Uint8Array.from(Buffer.from(encoded, "base64"));
        try {{
          const decoded = decodeFrame(source.buffer);
          return {{
            ok: true,
            message: decoded.message,
            buffers: decoded.buffers.map((value) =>
              Buffer.from(value.buffer, value.byteOffset, value.byteLength).toString("base64")),
          }};
        }} catch (_error) {{
          return {{ok: false}};
        }}
      }});
      process.stdout.write(JSON.stringify(results));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(completed.stdout)


def _javascript_number_model(value: object) -> object:
    """Normalize JSON numbers to JavaScript's one IEEE-754 number domain."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return [_javascript_number_model(item) for item in value]
    if isinstance(value, dict):
        return {key: _javascript_number_model(item) for key, item in value.items()}
    raise TypeError(f"value outside the JSON data model: {type(value).__name__}")


@settings(max_examples=20, deadline=None)
@given(
    value=JSON_VALUES,
    payload=st.binary(max_size=64),
    selector=st.integers(min_value=0, max_value=4096),
    xor_value=st.integers(min_value=1, max_value=255),
)
def test_structural_byte_mutations_reject_or_preserve_python_javascript_parity(
    value: object, payload: bytes, selector: int, xor_value: int
) -> None:
    message = {"type": "mutation_probe", "value": value, "padding_probe": "x"}
    body = encode_frame(message, [payload, b"abc"])
    metadata_end, metadata_padded_end, _buffers = _frame_positions(body)
    while metadata_end == metadata_padded_end:
        message["padding_probe"] += "x"
        body = encode_frame(message, [payload, b"abc"])
        metadata_end, metadata_padded_end, _buffers = _frame_positions(body)

    mutations = _mutations(body, selector, xor_value)
    python_results = [_python_decode_result(case) for case in mutations.values()]
    javascript_results = _javascript_decode_results(list(mutations.values()))

    assert len(javascript_results) == len(python_results)
    for name, python_result, javascript_result in zip(
        mutations, python_results, javascript_results, strict=True
    ):
        assert javascript_result["ok"] is python_result["ok"], name
        if python_result["ok"]:
            assert _javascript_number_model(javascript_result["message"]) == (
                _javascript_number_model(python_result["message"])
            ), name
            assert javascript_result["buffers"] == python_result["buffers"], name
