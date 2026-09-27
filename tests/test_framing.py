from __future__ import annotations

import base64
import json
import re
import struct
import subprocess
from pathlib import Path

import pytest
from scripts.js_exports import missing_esm_exports

import xy
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


def test_javascript_accepts_cross_realm_array_buffer_without_copy() -> None:
    body = encode_frame({"type": "density_update", "seq": 9}, [b"databricks"])
    encoded = base64.b64encode(body).decode("ascii")
    script = f"""
      import vm from 'node:vm';
      import {{ decodeFrame }} from {CLIENT.as_uri()!r};
      const source = vm.runInNewContext('new ArrayBuffer({len(body)})');
      new Uint8Array(source).set(Buffer.from({encoded!r}, 'base64'));
      const decoded = decodeFrame(source);
      const payload = decoded.buffers[0];
      let spoofRejected = false;
      try {{
        decodeFrame({{
          [Symbol.toStringTag]: 'ArrayBuffer',
          byteLength: source.byteLength,
        }});
      }} catch (error) {{
        spoofRejected = error instanceof TypeError;
      }}
      process.stdout.write(JSON.stringify({{
        crossRealm: source instanceof ArrayBuffer === false,
        sameBacking: payload.buffer === source,
        payload: Buffer.from(
          payload.buffer,
          payload.byteOffset,
          payload.byteLength
        ).toString('utf8'),
        spoofRejected,
      }}));
    """

    result = _node(script)

    assert result == {
        "crossRealm": True,
        "sameBacking": True,
        "payload": "databricks",
        "spoofRejected": True,
    }


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


def test_javascript_column_dtypes_are_exhaustive_for_every_wire_layout() -> None:
    chart = xy.scatter_chart(
        xy.scatter(
            x=[1.0, 2.0],
            y=[3.0, 4.0],
            color=["A", "B"],
            key=["ES", "FR"],
        ),
        xy.animation(match="key"),
    )
    figure = chart.figure()
    packed_spec, packed_raw = figure.build_payload()
    split_spec, split_raw = figure.build_payload_split()
    packed_encoded = base64.b64encode(packed_raw).decode("ascii")
    split_encoded = [base64.b64encode(bytes(value)).decode("ascii") for value in split_raw]
    header_source = (ROOT / "js" / "src" / "00_header.ts").read_bytes()
    header_url = "data:text/javascript;base64," + base64.b64encode(header_source).decode("ascii")
    script = f"""
      import {{ ChartView }} from {CLIENT.as_uri()!r};
      import {{ payloadCoherent }} from {header_url!r};

      const decode = (value) => Uint8Array.from(Buffer.from(value, 'base64'));
      const packedSpec = {json.dumps(packed_spec)};
      const splitSpec = {json.dumps(split_spec)};
      const packed = decode({packed_encoded!r});
      const split = {json.dumps(split_encoded)}.map(decode);
      const columnView = ChartView.prototype._columnView;
      const names = (spec, payload) => spec.columns.map((meta, index) =>
        columnView.call(null, payload, meta, `column ${{index}}`).constructor.name);
      const capture = (fn) => {{
        try {{ fn(); return {{threw: false, message: ''}}; }}
        catch (error) {{ return {{threw: true, message: String(error && error.message)}}; }}
      }};
      const badPacked = structuredClone(packedSpec);
      badPacked.columns[0].dtype = 'f64';
      const badSplit = structuredClone(splitSpec);
      badSplit.columns[0].dtype = 'future32';

      const receiver = {{
        _asF32: ChartView.prototype._asF32,
        _asU8: ChartView.prototype._asU8,
        _asU32: ChartView.prototype._asU32,
      }};
      const updateView = ChartView.prototype._wireColumnView;
      const explicit = [
        updateView.call(receiver, packed, {{}}, 'drill x').constructor.name,
        updateView.call(receiver, packed, {{dtype: 'f32'}}, 'drill opacity').constructor.name,
        updateView.call(receiver, packed, {{dtype: 'u8'}}, 'drill color').constructor.name,
        updateView.call(receiver, packed, {{dtype: 'u32'}}, 'drill key').constructor.name,
      ];

      process.stdout.write(JSON.stringify({{
        packedNames: names(packedSpec, packed),
        splitNames: names(splitSpec, split),
        packedCoherent: payloadCoherent(packedSpec, packed),
        splitCoherent: payloadCoherent(splitSpec, split),
        packedColumnError: capture(() =>
          columnView.call(null, packed, badPacked.columns[0], 'packed column 0')),
        splitColumnError: capture(() =>
          columnView.call(null, split, badSplit.columns[0], 'split column 0')),
        packedCoherenceError: capture(() => payloadCoherent(badPacked, packed)),
        splitCoherenceError: capture(() => payloadCoherent(badSplit, split)),
        explicit,
        updateError: capture(() =>
          updateView.call(receiver, packed, {{dtype: 'i32'}}, 'drill color')),
      }}));
    """

    result = _node(script)

    expected = ["Float32Array", "Float32Array", "Uint32Array", "Uint32Array", "Uint8Array"]
    assert result["packedNames"] == expected
    assert result["splitNames"] == expected
    assert result["packedCoherent"] is True
    assert result["splitCoherent"] is True
    assert result["explicit"] == ["Float32Array", "Float32Array", "Uint8Array", "Uint32Array"]
    for key, dtype, context in (
        ("packedColumnError", "f64", "packed column 0"),
        ("splitColumnError", "future32", "split column 0"),
        ("packedCoherenceError", "f64", "column 0"),
        ("splitCoherenceError", "future32", "column 0"),
        ("updateError", "i32", "drill color"),
    ):
        error = result[key]
        assert error["threw"] is True
        assert dtype in error["message"]
        assert context in error["message"]


def test_javascript_wire_dtype_decisions_stay_centralized() -> None:
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "js" / "src").glob("*.ts"))
    }
    dtype_decision = re.compile(r"\.dtype\s*(?:===|==|!==|!=|\|\||\?\?)")

    assert "wireColumnDtype" in sources["00_header.ts"]
    for name, source in sources.items():
        if name != "00_header.ts":
            assert not dtype_decision.search(source), f"dtype interpretation escaped into {name}"
    for name in ("45_lod.ts", "50_chartview.ts", "54_kernel.ts", "56_animation.ts"):
        assert "wireColumnDtype" in sources[name]


def test_widget_entry_no_longer_slices_binary_views() -> None:
    source = (ROOT / "js" / "src" / "60_entries.ts").read_text(encoding="utf-8")
    # payloadBuffers lives in the shared header now (the append apply path in
    # 54_kernel.ts uses it too); the entry consumes it for first paint.
    header = (ROOT / "js" / "src" / "00_header.ts").read_text(encoding="utf-8")
    built = CLIENT.read_text(encoding="utf-8")
    assert 'payloadBuffers(spec, model.get("buffers"))' in source
    assert "raw.map(bytesToSpan)" in header
    for text in (source, header):
        assert ".buffer.slice(b.byteOffset" not in text
    # The built bundle is minified; its export block is what survives
    # identifier renaming.
    assert not missing_esm_exports(built, ("decodeFrame",))
