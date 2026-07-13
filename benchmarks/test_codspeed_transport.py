"""CodSpeed microbenchmarks for the deterministic binary frame hot paths.

The real loopback HTTP/browser path stays in ``bench_transport.py``; sockets,
compression, JavaScript heap, and animation frames are wall-clock/browser
measurements and do not belong in CodSpeed simulation.  These rows isolate the
Python envelope work so codec regressions remain attributable.
"""

from __future__ import annotations

import base64
import json

import pytest

from xy.channel import decode_frame, encode_frame, encode_frame_parts

DENSITY_BYTES = 128 * 1024
DIRECT_BYTES = 800 * 1024
MESSAGE = {
    "type": "density_update",
    "seq": 17,
    "traces": [{"id": 0, "mode": "density", "w": 512, "h": 256, "buf": 0}],
}


def _base64_encode(message: dict, buffers: tuple[bytes, ...]) -> bytes:
    payload = {
        "message": message,
        "buffers": [base64.b64encode(buffer).decode("ascii") for buffer in buffers],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _base64_decode(body: bytes) -> tuple[dict, list[bytes]]:
    payload = json.loads(body)
    return payload["message"], [base64.b64decode(value) for value in payload["buffers"]]


@pytest.fixture(scope="module")
def density_case() -> tuple[dict, tuple[bytes, ...], bytes]:
    buffers = (bytes((index * 17 + 11) & 0xFF for index in range(DENSITY_BYTES)),)
    return MESSAGE, buffers, encode_frame(MESSAGE, buffers)


@pytest.fixture(scope="module")
def direct_case() -> tuple[dict, tuple[bytes, ...], bytes]:
    x = bytes((index * 29 + 7) & 0xFF for index in range(DIRECT_BYTES // 2))
    y = bytes((index * 31 + 3) & 0xFF for index in range(DIRECT_BYTES // 2))
    buffers = (x, y)
    return MESSAGE, buffers, encode_frame(MESSAGE, buffers)


def test_transport_encode_frame_density(benchmark, density_case) -> None:
    message, buffers, _body = density_case
    body = benchmark(encode_frame, message, buffers)
    assert len(body) > sum(map(len, buffers))


def test_transport_encode_frame_direct(benchmark, direct_case) -> None:
    message, buffers, _body = direct_case
    body = benchmark(encode_frame, message, buffers)
    assert len(body) > sum(map(len, buffers))


def test_transport_encode_frame_parts_direct(benchmark, direct_case) -> None:
    message, buffers, body = direct_case
    parts = benchmark(encode_frame_parts, message, buffers)
    assert sum(memoryview(part).nbytes for part in parts) == len(body)
    assert sum(isinstance(part, memoryview) for part in parts) == len(buffers)


def test_transport_decode_frame_density(benchmark, density_case) -> None:
    message, buffers, body = density_case
    decoded = benchmark(decode_frame, body)
    assert decoded.message == message
    assert [len(buffer) for buffer in decoded.buffers] == [len(buffer) for buffer in buffers]
    assert all(buffer.obj is body for buffer in decoded.buffers)


def test_transport_decode_frame_direct(benchmark, direct_case) -> None:
    message, buffers, body = direct_case
    decoded = benchmark(decode_frame, body)
    assert decoded.message == message
    assert [len(buffer) for buffer in decoded.buffers] == [len(buffer) for buffer in buffers]
    assert all(buffer.obj is body for buffer in decoded.buffers)


def test_transport_base64_encode_direct_comparator(benchmark, direct_case) -> None:
    message, buffers, _body = direct_case
    body = benchmark(_base64_encode, message, buffers)
    assert len(body) > sum(map(len, buffers))


def test_transport_base64_decode_direct_comparator(benchmark, direct_case) -> None:
    message, buffers, _body = direct_case
    body = _base64_encode(message, buffers)
    decoded_message, decoded_buffers = benchmark(_base64_decode, body)
    assert decoded_message == message
    assert [len(buffer) for buffer in decoded_buffers] == [len(buffer) for buffer in buffers]
