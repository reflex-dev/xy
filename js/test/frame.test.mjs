import assert from "node:assert/strict";
import test from "node:test";

import { __testing, decodeFrame } from "../../python/xy/static/index.js";

const MAGIC = [0x58, 0x59, 0x42, 0x46];
const ALIGNMENT = 8;

function align8(value) {
  return Math.ceil(value / ALIGNMENT) * ALIGNMENT;
}

function encodeFrame(message, payloads = []) {
  const metadata = new TextEncoder().encode(JSON.stringify(message));
  let length = align8(__testing.XY_FRAME_HEADER_SIZE + metadata.byteLength);
  for (const payload of payloads) length = align8(length + 8 + payload.byteLength);
  const frame = new ArrayBuffer(length);
  const bytes = new Uint8Array(frame);
  const view = new DataView(frame);
  MAGIC.forEach((byte, index) => view.setUint8(index, byte));
  view.setUint8(4, __testing.XY_FRAME_VERSION);
  view.setUint8(5, 0);
  view.setUint16(6, __testing.XY_FRAME_HEADER_SIZE, true);
  view.setUint32(8, metadata.byteLength, true);
  view.setUint32(12, payloads.length, true);
  view.setBigUint64(16, BigInt(length), true);
  bytes.set(metadata, __testing.XY_FRAME_HEADER_SIZE);
  let offset = align8(__testing.XY_FRAME_HEADER_SIZE + metadata.byteLength);
  for (const payload of payloads) {
    view.setBigUint64(offset, BigInt(payload.byteLength), true);
    offset += 8;
    bytes.set(payload, offset);
    offset = align8(offset + payload.byteLength);
  }
  return frame;
}

function mutate(frame, callback) {
  const copy = frame.slice(0);
  callback(new Uint8Array(copy), new DataView(copy));
  return copy;
}

test("frame decoder returns aligned zero-copy payload spans", () => {
  const frame = encodeFrame(
    { type: "tier_update", seq: 7 },
    [Uint8Array.of(1, 2, 3), Uint8Array.of(9, 8, 7, 6)]
  );

  const decoded = decodeFrame(frame);

  assert.deepEqual(decoded.message, { type: "tier_update", seq: 7 });
  assert.equal(decoded.version, 1);
  assert.equal(decoded.byteLength, frame.byteLength);
  assert.deepEqual([...decoded.buffers[0]], [1, 2, 3]);
  assert.deepEqual([...decoded.buffers[1]], [9, 8, 7, 6]);
  assert.equal(decoded.buffers[0].buffer, frame);
  assert.equal(decoded.buffers[0].byteOffset % ALIGNMENT, 0);
  assert.equal(decoded.buffers[1].byteOffset % ALIGNMENT, 0);
});

test("frame decoder enforces explicit resource limits", () => {
  const frame = encodeFrame({ type: "append" }, [Uint8Array.of(1, 2, 3, 4)]);

  assert.throws(
    () => decodeFrame(frame, {
      maxFrameBytes: frame.byteLength - 1,
      maxMetadataBytes: frame.byteLength - 1,
      maxBufferBytes: frame.byteLength - 1,
    }),
    /frame length .* exceeds limit/
  );
  assert.throws(
    () => decodeFrame(frame, { maxMetadataBytes: 2 }),
    /metadata length .* exceeds limit/
  );
  assert.throws(
    () => decodeFrame(frame, { maxBuffers: 1, maxBufferBytes: 3 }),
    /buffer 0 length .* exceeds limit/
  );
  assert.throws(
    () => decodeFrame(frame, { maxFrameBytes: 64, maxMetadataBytes: 65 }),
    /maxMetadataBytes cannot exceed maxFrameBytes/
  );
});

test("malformed frame controls fail closed at every envelope boundary", () => {
  const frame = encodeFrame({ ok: true }, [Uint8Array.of(4, 5, 6)]);
  const cases = [
    [mutate(frame, (bytes) => { bytes[0] = 0; }), /invalid frame magic/],
    [mutate(frame, (_bytes, view) => { view.setUint8(4, 99); }), /unsupported frame version 99/],
    [mutate(frame, (_bytes, view) => { view.setUint8(5, 1); }), /unsupported frame flags/],
    [mutate(frame, (_bytes, view) => { view.setUint16(6, 16, true); }), /unsupported frame header size/],
    [mutate(frame, (_bytes, view) => { view.setBigUint64(16, 24n, true); }), /declared frame length/],
    [mutate(frame, (bytes) => { bytes[35] = 1; }), /non-zero metadata padding/],
  ];
  for (const [broken, expected] of cases) assert.throws(() => decodeFrame(broken), expected);

  const unalignedBacking = new Uint8Array(frame.byteLength + 1);
  unalignedBacking.set(new Uint8Array(frame), 1);
  assert.throws(
    () => decodeFrame(new Uint8Array(unalignedBacking.buffer, 1, frame.byteLength)),
    /must start on an 8-byte boundary/
  );
  assert.throws(() => decodeFrame("not binary"), /must be an ArrayBuffer/);
});

test("malformed metadata and trailing bytes are rejected", () => {
  const scalar = encodeFrame(17);
  assert.throws(() => decodeFrame(scalar), /metadata must decode to an object/);

  const invalidJson = encodeFrame({ x: 1 });
  const jsonBytes = new Uint8Array(invalidJson);
  jsonBytes[__testing.XY_FRAME_HEADER_SIZE] = 0xff;
  assert.throws(() => decodeFrame(invalidJson), /invalid frame metadata JSON/);

  const withTrailing = new Uint8Array(encodeFrame({ x: 1 }).byteLength + 8);
  withTrailing.set(new Uint8Array(encodeFrame({ x: 1 })));
  new DataView(withTrailing.buffer).setBigUint64(16, BigInt(withTrailing.byteLength), true);
  assert.throws(() => decodeFrame(withTrailing), /trailing bytes/);
});
