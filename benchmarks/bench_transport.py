"""Loopback transport benchmark for the transport-neutral channel dispatcher.

This harness measures the current Reflex prototype shape (base64 buffers inside
JSON) against a benchmark-only aligned binary envelope.  The binary envelope is
deliberately *not* a production codec: it exists to establish byte, CPU, memory,
and browser request-to-next-frame baselines before the versioned public framing
contract is implemented.

Both HTTP endpoints call :func:`xy.channel.handle_message`; only their response
encoding differs.  The optional Chromium probe fetches and decodes both formats
from the same loopback server and waits for the next animation frame after each
decode.  It does not claim request-to-pixels or GPU-upload latency.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import gzip
import http.client
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from collections.abc import Callable, Iterator, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _browser import chromium_gl_flags, find_chromium  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402
from xy._figure import Figure  # noqa: E402
from xy.channel import Reply, handle_message  # noqa: E402
from xy.widget import FigureWidget  # noqa: E402

_MAGIC = b"XYBM"  # xy benchmark message -- not the future production protocol
_VERSION = 1
_HEADER = struct.Struct("<4sBBHII")
_U64 = struct.Struct("<Q")
_ALIGNMENT = 8
_CATEGORY_IDS = ("payload_export_size", "streaming_updates", "interaction_smoothness")


def _align(value: int) -> int:
    return (value + (_ALIGNMENT - 1)) & ~(_ALIGNMENT - 1)


def encode_diagnostic_frame(message: dict[str, Any], buffers: Sequence[bytes]) -> bytes:
    """Encode the benchmark-only aligned binary envelope.

    Every buffer payload begins on an eight-byte boundary.  This layout is a
    diagnostic control, not the production framing proposal: it intentionally
    has no public compatibility promise.
    """

    metadata = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
    parts: list[bytes] = [
        _HEADER.pack(_MAGIC, _VERSION, 0, 0, len(metadata), len(buffers)),
        metadata,
    ]
    prefix_size = _HEADER.size + len(metadata)
    parts.append(b"\x00" * (_align(prefix_size) - prefix_size))
    position = _align(prefix_size)
    for buffer in buffers:
        payload = bytes(buffer)
        parts.extend((_U64.pack(len(payload)), payload))
        position += _U64.size + len(payload)
        padding = _align(position) - position
        parts.append(b"\x00" * padding)
        position += padding
    return b"".join(parts)


def decode_diagnostic_frame(body: bytes) -> tuple[dict[str, Any], list[memoryview], list[int]]:
    """Decode the benchmark envelope and expose zero-copy buffer views/offsets."""

    view = memoryview(body)
    if len(view) < _HEADER.size:
        raise ValueError("truncated diagnostic frame header")
    magic, version, flags, reserved, metadata_len, buffer_count = _HEADER.unpack_from(view)
    if magic != _MAGIC or version != _VERSION or flags != 0 or reserved != 0:
        raise ValueError("unsupported diagnostic frame")
    metadata_end = _HEADER.size + metadata_len
    if metadata_end > len(view):
        raise ValueError("truncated diagnostic frame metadata")
    message = json.loads(bytes(view[_HEADER.size : metadata_end]))
    if not isinstance(message, dict):
        raise ValueError("diagnostic frame metadata must be an object")
    position = _align(metadata_end)
    buffers: list[memoryview] = []
    offsets: list[int] = []
    for _ in range(buffer_count):
        if position + _U64.size > len(view):
            raise ValueError("truncated diagnostic frame buffer length")
        (length,) = _U64.unpack_from(view, position)
        position += _U64.size
        end = position + length
        if end > len(view):
            raise ValueError("truncated diagnostic frame buffer")
        offsets.append(position)
        buffers.append(view[position:end])
        position = _align(end)
    if position != len(view):
        raise ValueError("diagnostic frame has trailing bytes")
    return message, buffers, offsets


def encode_base64_json(message: dict[str, Any], buffers: Sequence[bytes]) -> bytes:
    """Encode the current prototype representation."""

    payload = {
        "message": message,
        "buffers": [base64.b64encode(buffer).decode("ascii") for buffer in buffers],
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_base64_json(body: bytes) -> tuple[dict[str, Any], list[bytes]]:
    payload = json.loads(body)
    return payload["message"], [
        base64.b64decode(value, validate=True) for value in payload["buffers"]
    ]


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _timings_ms(fn: Callable[[], bytes], reps: int) -> tuple[float, float]:
    for _ in range(2):
        fn()
    samples = []
    for _ in range(reps):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return _percentile(samples, 0.5), _percentile(samples, 0.95)


def _peak_python_bytes(fn: Callable[[], bytes]) -> int:
    tracemalloc.start()
    try:
        fn()
        _current, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def measure_envelopes(reply: Reply, reps: int) -> list[dict[str, Any]]:
    message, reply_buffers = reply
    buffers = reply_buffers or []
    payload_bytes = sum(len(buffer) for buffer in buffers)
    rows = []
    for mode, encoder, payload_reencodes in (
        ("aligned-binary-diagnostic", encode_diagnostic_frame, 0),
        ("base64-json-prototype", encode_base64_json, 1),
    ):

        def fn(encoder: Callable[..., bytes] = encoder) -> bytes:
            return encoder(message, buffers)

        body = fn()
        p50, p95 = _timings_ms(fn, reps)
        rows.append(
            {
                "mode": mode,
                "payload_bytes": payload_bytes,
                "wire_bytes": len(body),
                "wire_to_payload_ratio": len(body) / max(1, payload_bytes),
                "gzip_bytes": len(gzip.compress(body, compresslevel=6, mtime=0)),
                "encode_p50_ms": p50,
                "encode_p95_ms": p95,
                "peak_python_bytes": _peak_python_bytes(fn),
                # Explicit format transformations, not a claim about hidden
                # interpreter/socket memcpy operations.
                "payload_reencodes": payload_reencodes,
            }
        )
    return rows


def build_density_fixture(n: int) -> tuple[Figure, dict[str, Any]]:
    rng = np.random.default_rng(42)
    x = rng.uniform(-4.0, 4.0, n)
    y = rng.normal(0.0, 1.0, n)
    fig = Figure().scatter(x, y)
    message = {
        "type": "density_view",
        "trace": 0,
        "x0": -4.0,
        "x1": 4.0,
        "y0": -4.0,
        "y1": 4.0,
        "w": 512,
        "h": 384,
        "seq": 1,
    }
    return fig, message


def dispatch(fig: Figure, message: dict[str, Any]) -> Reply:
    reply = handle_message(fig, message)
    if reply is None:
        raise RuntimeError("transport benchmark message produced no reply")
    return reply


def _binary_bytes(buffers: Any) -> int:
    if not buffers:
        return 0
    return sum(memoryview(buffer).nbytes for buffer in buffers)


def measure_append_diagnostics(n: int = 10_000) -> dict[str, Any]:
    """Make the two known append costs visible without treating them as ideals."""

    x = np.arange(n, dtype=np.float64)
    y = np.sin(x / 100.0)

    widget_fig = Figure().scatter(x, y)
    widget = FigureWidget(widget_fig)
    sent: list[tuple[dict[str, Any], Any]] = []
    widget._send = lambda msg, buffers=None: sent.append((msg, buffers))  # type: ignore[method-assign]
    widget.append(0, [float(n)], [0.0])
    binary_messages = [_binary_bytes(buffers) for _msg, buffers in sent]
    binary_messages = [size for size in binary_messages if size]

    single = Figure().scatter(x, y)
    single_msg, single_buffers = single.append(0, [float(n)], [0.0])
    multi = Figure().scatter(x, y).scatter(x + n * 2.0, y.copy())
    multi_msg, multi_buffers = multi.append(0, [float(n)], [0.0])

    def wire_bytes(message: dict[str, Any], buffers: Sequence[bytes]) -> int:
        metadata = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return len(metadata) + sum(len(buffer) for buffer in buffers)

    single_wire = wire_bytes(single_msg, single_buffers)
    multi_wire = wire_bytes(multi_msg, multi_buffers)
    return {
        "fixture_points_per_trace": n,
        "widget_messages": len(sent),
        "widget_binary_transmissions": len(binary_messages),
        "widget_binary_bytes": sum(binary_messages),
        "single_trace_append_wire_bytes": single_wire,
        "two_trace_append_wire_bytes": multi_wire,
        "extra_unaffected_trace_wire_bytes": multi_wire - single_wire,
    }


class _TransportServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        fig: Figure,
        default_message: dict[str, Any],
        browser_reps: int,
    ) -> None:
        super().__init__(address, _TransportHandler)
        self.fig = fig
        self.default_message = default_message
        self.browser_reps = browser_reps


class _TransportHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _write(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/":
            self._write(404, "text/plain", b"not found")
            return
        server = self.server
        assert isinstance(server, _TransportServer)
        body = _browser_page(server.default_message, server.browser_reps).encode("utf-8")
        self._write(200, "text/html; charset=utf-8", body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/raw", "/base64"}:
            self._write(404, "text/plain", b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            message = json.loads(self.rfile.read(length))
            server = self.server
            assert isinstance(server, _TransportServer)
            reply = dispatch(server.fig, message)
            if self.path == "/raw":
                body = encode_diagnostic_frame(reply[0], reply[1] or [])
                content_type = "application/octet-stream"
            else:
                body = encode_base64_json(reply[0], reply[1] or [])
                content_type = "application/json"
        except (TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._write(400, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
            return
        self._write(200, content_type, body)


@contextlib.contextmanager
def transport_server(
    fig: Figure, message: dict[str, Any], browser_reps: int
) -> Iterator[_TransportServer]:
    server = _TransportServer(("127.0.0.1", 0), fig, message, browser_reps)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def measure_python_loopback(
    server: _TransportServer, message: dict[str, Any], reps: int
) -> list[dict[str, Any]]:
    request_body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    rows = []
    for mode, path in (("aligned-binary-diagnostic", "/raw"), ("base64-json-prototype", "/base64")):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
        samples: list[float] = []
        response_sizes: list[int] = []
        try:
            for index in range(reps + 2):
                start = time.perf_counter_ns()
                connection.request(
                    "POST",
                    path,
                    body=request_body,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                body = response.read()
                if response.status != 200:
                    raise RuntimeError(f"loopback {path} returned HTTP {response.status}")
                if path == "/raw":
                    decode_diagnostic_frame(body)
                else:
                    decode_base64_json(body)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if index >= 2:
                    samples.append(elapsed)
                    response_sizes.append(len(body))
        finally:
            connection.close()
        rows.append(
            {
                "mode": mode,
                "response_bytes": response_sizes[0],
                "request_to_decode_p50_ms": _percentile(samples, 0.5),
                "request_to_decode_p95_ms": _percentile(samples, 0.95),
            }
        )
    return rows


def _browser_page(message: dict[str, Any], reps: int) -> str:
    message_json = json.dumps(message, separators=(",", ":"))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>TRANSPORT_PENDING</title></head>
<body><pre id="result"></pre><script>
const MESSAGE = {message_json};
const REPS = {reps};
const align8 = (n) => (n + 7) & ~7;
function percentile(values, q) {{
  const sorted = values.slice().sort((a, b) => a - b);
  return sorted[Math.max(0, Math.min(sorted.length - 1, Math.ceil(q * sorted.length) - 1))];
}}
function decodeRaw(buffer) {{
  const view = new DataView(buffer);
  if (view.byteLength < 16 || view.getUint32(0, true) !== 0x4d425958 || view.getUint8(4) !== 1)
    throw new Error('bad diagnostic frame');
  const metadataLength = view.getUint32(8, true);
  const count = view.getUint32(12, true);
  const metadata = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 16, metadataLength)));
  let position = align8(16 + metadataLength);
  const buffers = [];
  for (let i = 0; i < count; i++) {{
    const length = Number(view.getBigUint64(position, true));
    position += 8;
    if (position % 8) throw new Error('unaligned diagnostic buffer');
    buffers.push(new Uint8Array(buffer, position, length));
    position = align8(position + length);
  }}
  if (position !== buffer.byteLength) throw new Error('trailing diagnostic bytes');
  return {{metadata, buffers}};
}}
async function decodeBase64(response) {{
  const payload = await response.json();
  const buffers = payload.buffers.map((value) => {{
    const binary = atob(value);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
    return out;
  }});
  return {{metadata: payload.message, buffers}};
}}
async function runMode(mode, path) {{
  const samples = [];
  const heapDeltas = [];
  let responseBytes = 0;
  for (let i = -2; i < REPS; i++) {{
    const heapBefore = performance.memory ? performance.memory.usedJSHeapSize : null;
    const start = performance.now();
    const response = await fetch(path, {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(MESSAGE),
    }});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const contentLength = Number(response.headers.get('Content-Length') || 0);
    const decoded = mode === 'aligned-binary-diagnostic'
      ? decodeRaw(await response.arrayBuffer()) : await decodeBase64(response);
    if (!decoded.metadata || !decoded.buffers.length) throw new Error('empty decoded reply');
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const elapsed = performance.now() - start;
    const heapAfter = performance.memory ? performance.memory.usedJSHeapSize : null;
    if (i >= 0) {{
      samples.push(elapsed);
      responseBytes = contentLength;
      if (heapBefore != null && heapAfter != null) heapDeltas.push(Math.max(0, heapAfter - heapBefore));
    }}
  }}
  return {{
    mode, response_bytes: responseBytes,
    request_to_next_frame_p50_ms: percentile(samples, 0.5),
    request_to_next_frame_p95_ms: percentile(samples, 0.95),
    js_heap_delta_p95_bytes: heapDeltas.length ? percentile(heapDeltas, 0.95) : null,
  }};
}}
(async () => {{
  try {{
    const rows = [];
    rows.push(await runMode('aligned-binary-diagnostic', '/raw'));
    rows.push(await runMode('base64-json-prototype', '/base64'));
    document.getElementById('result').textContent = JSON.stringify({{status: 'ok', rows}});
    document.title = 'TRANSPORT_DONE';
  }} catch (error) {{
    document.getElementById('result').textContent = JSON.stringify({{status: 'failed', error: String(error)}});
    document.title = 'TRANSPORT_FAILED';
  }}
}})();
</script></body></html>"""


def run_browser_probe(
    server: _TransportServer, *, chromium: str | None, timeout_s: int = 180
) -> dict[str, Any]:
    executable = find_chromium(chromium)
    if not executable:
        return {"status": "skipped(no chromium)", "rows": []}
    url = f"http://127.0.0.1:{server.server_port}/"
    script = """
const { createRequire } = require('node:module');
const requireFromRepo = createRequire(process.env.XY_PACKAGE_JSON);
const { chromium } = requireFromRepo('playwright');
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.XY_CHROMIUM,
    headless: true,
    args: JSON.parse(process.env.XY_CHROME_ARGS || '[]'),
  });
  try {
    const page = await browser.newPage();
    await page.goto(process.env.XY_TRANSPORT_URL, {waitUntil: 'load'});
    await page.waitForFunction(
      () => document.title === 'TRANSPORT_DONE' || document.title === 'TRANSPORT_FAILED',
      null,
      {timeout: 120000},
    );
    process.stdout.write(await page.locator('#result').textContent());
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
"""
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "transport-probe.cjs"
        script_path.write_text(script, encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "XY_PACKAGE_JSON": str(Path(__file__).resolve().parents[1] / "package.json"),
                "XY_CHROMIUM": executable,
                "XY_CHROME_ARGS": json.dumps(
                    [
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--enable-precise-memory-info",
                        *chromium_gl_flags(),
                    ]
                ),
                "XY_TRANSPORT_URL": url,
            }
        )
        try:
            completed = subprocess.run(
                ["node", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"status": "failed(timeout)", "rows": []}
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "no stderr"
        )
        return {"status": f"failed(playwright: {detail})", "rows": []}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "failed(invalid result)", "rows": []}
    return result


def run_benchmark(
    *,
    n: int,
    reps: int,
    browser_reps: int,
    chromium: str | None,
) -> dict[str, Any]:
    fig, message = build_density_fixture(n)
    reply = dispatch(fig, message)
    envelopes = measure_envelopes(reply, reps)
    with transport_server(fig, message, browser_reps) as server:
        python_loopback = measure_python_loopback(server, message, reps)
        browser = run_browser_probe(server, chromium=chromium)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "transport-loopback",
        "measurement_scope": "loopback-channel-transport-diagnostic",
        "frame_status": "benchmark-only; not a production protocol",
        "environment": collect_environment_metadata(
            chromium=find_chromium(chromium),
            xy_backend="native",
        ),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(_CATEGORY_IDS),
        "configuration": {"n": n, "reps": reps, "browser_reps": browser_reps},
        "envelopes": envelopes,
        "python_loopback": python_loopback,
        "browser": browser,
        "append_diagnostics": measure_append_diagnostics(),
    }


def _print_report(report: dict[str, Any]) -> None:
    print("xy loopback transport diagnostic")
    print("\n| envelope | raw bytes | gzip bytes | encode p50 | Python HTTP+decode p95 |")
    print("|---|---:|---:|---:|---:|")
    loopback = {row["mode"]: row for row in report["python_loopback"]}
    for row in report["envelopes"]:
        http_row = loopback[row["mode"]]
        print(
            f"| {row['mode']} | {row['wire_bytes']:,} | {row['gzip_bytes']:,} "
            f"| {row['encode_p50_ms']:.3f} ms | {http_row['request_to_decode_p95_ms']:.3f} ms |"
        )
    browser = report["browser"]
    print(f"\nbrowser: {browser['status']}")
    for row in browser.get("rows", []):
        print(
            f"  {row['mode']}: request→next-frame p50 "
            f"{row['request_to_next_frame_p50_ms']:.3f} ms, p95 "
            f"{row['request_to_next_frame_p95_ms']:.3f} ms"
        )
    append = report["append_diagnostics"]
    print(
        "append diagnostics: "
        f"{append['widget_binary_transmissions']} widget binary transmissions; "
        f"{append['extra_unaffected_trace_wire_bytes']:,} extra bytes from an unaffected trace"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=lambda value: int(float(value)), default=1_000_000)
    parser.add_argument("--reps", type=int, default=15)
    parser.add_argument("--browser-reps", type=int, default=12)
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--require-browser", action="store_true")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    if args.n < 250_000:
        parser.error("--n must be >=250000 so the fixture uses density transport")
    if args.reps < 1 or args.browser_reps < 1:
        parser.error("--reps and --browser-reps must be positive")
    report = run_benchmark(
        n=args.n,
        reps=args.reps,
        browser_reps=args.browser_reps,
        chromium=args.chromium,
    )
    _print_report(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.require_browser and report["browser"]["status"] != "ok":
        raise SystemExit(f"browser transport probe failed: {report['browser']['status']}")


if __name__ == "__main__":
    main()
