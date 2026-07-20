/**
 * xy render client.
 *
 * A thin GPU render client (design dossier §32): receives a data-less spec +
 * offset-encoded f32 columns as raw binary (§29 — no JSON numbers, no parse),
 * uploads them once to WebGL2 buffers, and draws with instanced/point
 * primitives. Pan/zoom is a uniform update — it never touches data buffers (§7).
 *
 * Full scatter support:
 *  - per-point color: constant, continuous (colormap LUT), categorical (palette)
 *  - per-point size: constant or continuous (mapped to a px range)
 *  - GPU picking → exact-row hover tooltip (§7/§17 Tier-0 hover; exact values
 *    come from the kernel's f64 canonical store, §16)
 *  - Tier-2 density surface for massive scatter (§5): a kernel-binned count grid
 *    uploaded as a log-normalized R8 texture and colormapped at composite time,
 *    re-binned on zoom via a kernel round-trip (stale grid stays drawn until
 *    then, §17)
 *
 * Dependency-free: this file is the whole client. DOM is used only for chrome —
 * title, axis tick labels, legend, tooltip (§7).
 */

"use strict";

const PROTOCOL = 4;

// HTTP binary frame v1 (spec/design/wire-protocol.md §7; Python side in
// python/xy/_framing.py). The chart spec's PROTOCOL
// above versions renderer semantics; this separately versions the transport
// envelope so either layer can fail loudly without coupling their evolution.
const XY_FRAME_MAGIC = [0x58, 0x59, 0x42, 0x46]; // "XYBF"
const XY_FRAME_VERSION = 1;
const XY_FRAME_HEADER_SIZE = 24;
const XY_FRAME_ALIGNMENT = 8;
const XY_FRAME_DEFAULT_LIMITS = Object.freeze({
  maxFrameBytes: 512 * 1024 * 1024,
  maxMetadataBytes: 8 * 1024 * 1024,
  maxBuffers: 4096,
  maxBufferBytes: 256 * 1024 * 1024,
});

function xyByteSpan(value, label = "buffer") {
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  throw new TypeError(`${label} must be an ArrayBuffer or ArrayBuffer view`);
}

function xyFrameLimit(limits, name) {
  const fallback = XY_FRAME_DEFAULT_LIMITS[name];
  const value = limits && limits[name] != null ? limits[name] : fallback;
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new RangeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function xyAlign8(value) {
  return Math.ceil(value / XY_FRAME_ALIGNMENT) * XY_FRAME_ALIGNMENT;
}

function xyFrameU64(view, offset, label) {
  const value = view.getBigUint64(offset, true);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new RangeError(`${label} exceeds JavaScript's safe integer range`);
  }
  return Number(value);
}

function xyRequireZeroPadding(bytes, start, end, label) {
  if (end > bytes.byteLength) throw new RangeError(`truncated ${label} padding`);
  for (let i = start; i < end; i++) {
    if (bytes[i] !== 0) throw new RangeError(`non-zero ${label} padding`);
  }
}

/** Decode one production xy HTTP frame.
 *
 * Binary buffers are Uint8Array spans into the supplied ArrayBuffer; they are
 * not copied. Response.arrayBuffer() supplies an aligned base. Passing an
 * unaligned subview is rejected rather than silently slicing the whole frame.
 */
function decodeFrame(body, limits = null) {
  const bytes = xyByteSpan(body, "frame body");
  const maxFrameBytes = xyFrameLimit(limits, "maxFrameBytes");
  const maxMetadataBytes = xyFrameLimit(limits, "maxMetadataBytes");
  const maxBuffers = xyFrameLimit(limits, "maxBuffers");
  const maxBufferBytes = xyFrameLimit(limits, "maxBufferBytes");
  if (maxMetadataBytes > maxFrameBytes) {
    throw new RangeError("maxMetadataBytes cannot exceed maxFrameBytes");
  }
  if (maxBufferBytes > maxFrameBytes) {
    throw new RangeError("maxBufferBytes cannot exceed maxFrameBytes");
  }
  if (bytes.byteOffset % XY_FRAME_ALIGNMENT !== 0) {
    throw new RangeError("frame body must start on an 8-byte boundary");
  }
  if (bytes.byteLength > maxFrameBytes) {
    throw new RangeError(`frame length ${bytes.byteLength} exceeds limit ${maxFrameBytes}`);
  }
  if (bytes.byteLength < XY_FRAME_HEADER_SIZE) throw new RangeError("truncated frame header");

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let i = 0; i < XY_FRAME_MAGIC.length; i++) {
    if (view.getUint8(i) !== XY_FRAME_MAGIC[i]) throw new RangeError("invalid frame magic");
  }
  const version = view.getUint8(4);
  if (version !== XY_FRAME_VERSION) throw new RangeError(`unsupported frame version ${version}`);
  const flags = view.getUint8(5);
  if (flags !== 0) throw new RangeError(`unsupported frame flags 0x${flags.toString(16)}`);
  const headerSize = view.getUint16(6, true);
  if (headerSize !== XY_FRAME_HEADER_SIZE) {
    throw new RangeError(`unsupported frame header size ${headerSize}`);
  }
  const metadataLength = view.getUint32(8, true);
  const bufferCount = view.getUint32(12, true);
  const totalLength = xyFrameU64(view, 16, "declared frame length");
  if (totalLength !== bytes.byteLength) {
    throw new RangeError(
      `declared frame length ${totalLength} does not match body length ${bytes.byteLength}`
    );
  }
  if (metadataLength > maxMetadataBytes) {
    throw new RangeError(`metadata length ${metadataLength} exceeds limit ${maxMetadataBytes}`);
  }
  if (bufferCount > maxBuffers) {
    throw new RangeError(`buffer count ${bufferCount} exceeds limit ${maxBuffers}`);
  }

  const metadataEnd = XY_FRAME_HEADER_SIZE + metadataLength;
  if (metadataEnd > bytes.byteLength) throw new RangeError("truncated frame metadata");
  let message;
  try {
    const metadataBytes = new Uint8Array(
      bytes.buffer,
      bytes.byteOffset + XY_FRAME_HEADER_SIZE,
      metadataLength
    );
    message = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(metadataBytes));
  } catch (error) {
    throw new RangeError(`invalid frame metadata JSON: ${error}`);
  }
  if (!message || Array.isArray(message) || typeof message !== "object") {
    throw new RangeError("frame metadata must decode to an object");
  }

  let position = xyAlign8(metadataEnd);
  xyRequireZeroPadding(bytes, metadataEnd, position, "metadata");
  const buffers = [];
  for (let i = 0; i < bufferCount; i++) {
    if (position + 8 > bytes.byteLength) throw new RangeError(`truncated buffer ${i} length`);
    const bufferLength = xyFrameU64(view, position, `buffer ${i} length`);
    position += 8;
    if (bufferLength > maxBufferBytes) {
      throw new RangeError(`buffer ${i} length ${bufferLength} exceeds limit ${maxBufferBytes}`);
    }
    const end = position + bufferLength;
    if (end > bytes.byteLength) throw new RangeError(`truncated buffer ${i}`);
    const absoluteOffset = bytes.byteOffset + position;
    if (absoluteOffset % XY_FRAME_ALIGNMENT !== 0) {
      throw new RangeError(`buffer ${i} is not 8-byte aligned`);
    }
    buffers.push(new Uint8Array(bytes.buffer, absoluteOffset, bufferLength));
    const paddedEnd = xyAlign8(end);
    xyRequireZeroPadding(bytes, end, paddedEnd, `buffer ${i}`);
    position = paddedEnd;
  }
  if (position !== bytes.byteLength) {
    throw new RangeError(`frame has ${bytes.byteLength - position} trailing bytes`);
  }
  return { message, buffers, version: XY_FRAME_VERSION, byteLength: bytes.byteLength };
}
