from __future__ import annotations

import http.client
import json

import numpy as np
import pytest
from benchmarks import bench_transport

from xy._figure import Figure


def test_diagnostic_frame_round_trip_is_aligned_and_zero_copy() -> None:
    source = [b"abc", bytes(range(17)), b""]
    body = bench_transport.encode_diagnostic_frame({"type": "density_update", "seq": 7}, source)

    message, buffers, offsets = bench_transport.decode_diagnostic_frame(body)

    assert message == {"seq": 7, "type": "density_update"}
    assert [bytes(buffer) for buffer in buffers] == source
    assert all(offset % 8 == 0 for offset in offsets)
    assert all(buffer.obj is body for buffer in buffers)


@pytest.mark.parametrize("cut", [0, 1, 15, 16, 23])
def test_diagnostic_frame_rejects_truncation(cut: int) -> None:
    body = bench_transport.encode_diagnostic_frame({"type": "selection"}, [b"12345678"])
    with pytest.raises(ValueError, match="truncated"):
        bench_transport.decode_diagnostic_frame(body[:cut])


def test_base64_json_round_trip() -> None:
    body = bench_transport.encode_base64_json({"type": "selection"}, [b"abc", b"def"])
    message, buffers = bench_transport.decode_base64_json(body)
    assert message == {"type": "selection"}
    assert buffers == [b"abc", b"def"]


def test_loopback_endpoints_share_channel_dispatcher_reply() -> None:
    fig = Figure().scatter(np.arange(10.0), np.arange(10.0))
    message = {"type": "select", "x0": 2.0, "x1": 5.0, "y0": 0.0, "y1": 9.0}
    expected_message, expected_buffers = bench_transport.dispatch(fig, message)
    request_body = json.dumps(message).encode("utf-8")

    with bench_transport.transport_server(fig, message, browser_reps=1) as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request(
                "POST",
                "/raw",
                body=request_body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            raw_body = response.read()
            assert response.status == 200

            connection.request(
                "POST",
                "/base64",
                body=request_body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            base64_body = response.read()
            assert response.status == 200
        finally:
            connection.close()

    raw_message, raw_buffers, offsets = bench_transport.decode_diagnostic_frame(raw_body)
    base64_message, base64_buffers = bench_transport.decode_base64_json(base64_body)
    assert raw_message == base64_message == expected_message
    assert [bytes(buffer) for buffer in raw_buffers] == base64_buffers == expected_buffers
    assert all(offset % 8 == 0 for offset in offsets)


def test_append_diagnostics_expose_duplicate_and_unaffected_costs() -> None:
    diagnostics = bench_transport.measure_append_diagnostics(n=32)

    assert diagnostics["widget_messages"] >= diagnostics["widget_binary_transmissions"] >= 1
    assert diagnostics["widget_binary_bytes"] > 0
    assert (
        diagnostics["two_trace_append_wire_bytes"] > diagnostics["single_trace_append_wire_bytes"]
    )
    assert diagnostics["extra_unaffected_trace_wire_bytes"] > 0


def test_envelope_metrics_separate_raw_and_compressed_bytes() -> None:
    reply = ({"type": "selection", "total": 10}, [bytes(range(256)) * 4])

    rows = bench_transport.measure_envelopes(reply, reps=1)

    assert {row["mode"] for row in rows} == {
        "aligned-binary-diagnostic",
        "base64-json-prototype",
    }
    assert all(row["wire_bytes"] > 0 and row["gzip_bytes"] > 0 for row in rows)
    raw = next(row for row in rows if row["mode"] == "aligned-binary-diagnostic")
    base64_row = next(row for row in rows if row["mode"] == "base64-json-prototype")
    assert raw["payload_reencodes"] == 0
    assert base64_row["payload_reencodes"] == 1
    assert raw["wire_bytes"] < base64_row["wire_bytes"]
