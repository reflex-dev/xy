"""Versioned binary HTTP framing for xy's transport-neutral channel.

The frame keeps JSON metadata small and carries numerical data as aligned raw
buffers.  Decoding returns memoryviews into the received body: adapters can pass
those spans to a socket/ASGI response or the browser without base64 or per-buffer
copies.  The monolithic :func:`encode_frame` convenience performs exactly one
final body assembly; :func:`encode_frame_parts` exposes scatter/gather parts for
servers that can stream bytes-like segments directly.

Wire layout, little-endian (version 1):

    0   char[4] magic = "XYBF"
    4   u8      version = 1
    5   u8      flags = 0
    6   u16     header_size = 24
    8   u32     metadata_length
    12  u32     buffer_count
    16  u64     total_frame_length
    24  bytes   UTF-8 JSON metadata object
        zero padding to an 8-byte boundary
        repeat buffer_count times:
          u64   buffer_length
          bytes buffer (starts at an 8-byte boundary)
          zero padding to an 8-byte boundary

Unknown versions/flags fail closed.  Limits are checked by both encoders and
the decoder; an HTTP adapter must additionally reject an oversized
``Content-Length`` before reading the request body into memory.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FRAME_MAGIC = b"XYBF"
FRAME_VERSION = 1
FRAME_ALIGNMENT = 8
FRAME_HEADER_SIZE = 24

_HEADER = struct.Struct("<4sBBHIIQ")
_BUFFER_LENGTH = struct.Struct("<Q")
_ZERO_PAD = b"\x00" * (FRAME_ALIGNMENT - 1)


class FrameError(ValueError):
    """Base class for binary frame failures."""


class FrameEncodeError(FrameError):
    """The requested metadata/buffers cannot be encoded safely."""


class FrameDecodeError(FrameError):
    """A received frame is malformed, unsupported, or over budget."""


@dataclass(frozen=True)
class FrameLimits:
    """Resource limits for one frame.

    Defaults permit xy's bounded direct/LOD payloads and large composed charts
    while preventing unbounded counts or lengths.  Internet-facing adapters
    should normally choose smaller application-specific limits.
    """

    max_frame_bytes: int = 512 * 1024 * 1024
    max_metadata_bytes: int = 8 * 1024 * 1024
    max_buffers: int = 4096
    max_buffer_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_frame_bytes",
            "max_metadata_bytes",
            "max_buffers",
            "max_buffer_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_metadata_bytes > self.max_frame_bytes:
            raise ValueError("max_metadata_bytes cannot exceed max_frame_bytes")
        if self.max_buffer_bytes > self.max_frame_bytes:
            raise ValueError("max_buffer_bytes cannot exceed max_frame_bytes")


DEFAULT_FRAME_LIMITS = FrameLimits()


@dataclass(frozen=True)
class DecodedFrame:
    """Decoded metadata plus zero-copy views into the original frame body."""

    message: dict[str, Any]
    buffers: tuple[memoryview, ...]


def _align(value: int) -> int:
    return (value + (FRAME_ALIGNMENT - 1)) & ~(FRAME_ALIGNMENT - 1)


def _byte_view(value: Any, *, label: str, error_type: type[FrameError]) -> memoryview:
    try:
        view = memoryview(value)
    except TypeError as exc:
        raise error_type(f"{label} must support the contiguous buffer protocol") from exc
    if not view.c_contiguous:
        raise error_type(f"{label} must be C-contiguous")
    try:
        return view.cast("B")
    except TypeError as exc:
        raise error_type(f"{label} cannot be viewed as bytes") from exc


def _encode_metadata(message: Mapping[str, Any], limits: FrameLimits) -> bytes:
    if not isinstance(message, Mapping):
        raise FrameEncodeError("frame metadata must be a mapping")
    try:
        metadata = json.dumps(
            dict(message),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise FrameEncodeError(f"frame metadata is not strict JSON: {exc}") from exc
    if len(metadata) > limits.max_metadata_bytes:
        raise FrameEncodeError(
            f"metadata length {len(metadata)} exceeds limit {limits.max_metadata_bytes}"
        )
    return metadata


def encode_frame_parts(
    message: Mapping[str, Any],
    buffers: Sequence[Any] = (),
    *,
    limits: FrameLimits = DEFAULT_FRAME_LIMITS,
) -> tuple[bytes | memoryview, ...]:
    """Return header/metadata/buffer segments without copying buffer payloads.

    The caller must keep mutable buffer owners unchanged until every segment has
    been consumed by the transport.
    """

    metadata = _encode_metadata(message, limits)
    try:
        buffer_count = len(buffers)
    except TypeError as exc:
        raise FrameEncodeError("buffers must be a sized sequence") from exc
    if buffer_count > limits.max_buffers:
        raise FrameEncodeError(f"buffer count {buffer_count} exceeds limit {limits.max_buffers}")

    views: list[memoryview] = []
    total = _align(FRAME_HEADER_SIZE + len(metadata))
    if total > limits.max_frame_bytes:
        raise FrameEncodeError(f"frame length {total} exceeds limit {limits.max_frame_bytes}")
    for index, buffer in enumerate(buffers):
        view = _byte_view(buffer, label=f"buffer {index}", error_type=FrameEncodeError)
        if len(view) > limits.max_buffer_bytes:
            raise FrameEncodeError(
                f"buffer {index} length {len(view)} exceeds limit {limits.max_buffer_bytes}"
            )
        total = _align(total + _BUFFER_LENGTH.size + len(view))
        if total > limits.max_frame_bytes:
            raise FrameEncodeError(f"frame length {total} exceeds limit {limits.max_frame_bytes}")
        views.append(view)

    header = _HEADER.pack(
        FRAME_MAGIC,
        FRAME_VERSION,
        0,
        FRAME_HEADER_SIZE,
        len(metadata),
        buffer_count,
        total,
    )
    metadata_padding = _align(FRAME_HEADER_SIZE + len(metadata)) - (
        FRAME_HEADER_SIZE + len(metadata)
    )
    parts: list[bytes | memoryview] = [header, metadata]
    if metadata_padding:
        parts.append(_ZERO_PAD[:metadata_padding])

    position = _align(FRAME_HEADER_SIZE + len(metadata))
    for view in views:
        parts.extend((_BUFFER_LENGTH.pack(len(view)), view))
        position += _BUFFER_LENGTH.size + len(view)
        padding = _align(position) - position
        if padding:
            parts.append(_ZERO_PAD[:padding])
            position += padding
    return tuple(parts)


def encode_frame(
    message: Mapping[str, Any],
    buffers: Sequence[Any] = (),
    *,
    limits: FrameLimits = DEFAULT_FRAME_LIMITS,
) -> bytes:
    """Encode one owned frame body with a single final assembly copy."""

    return b"".join(encode_frame_parts(message, buffers, limits=limits))


def _require_zero_padding(view: memoryview, start: int, end: int, label: str) -> None:
    if end > len(view):
        raise FrameDecodeError(f"truncated {label} padding")
    if any(view[start:end]):
        raise FrameDecodeError(f"non-zero {label} padding")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def decode_frame(
    body: Any,
    *,
    limits: FrameLimits = DEFAULT_FRAME_LIMITS,
) -> DecodedFrame:
    """Validate and decode one frame without copying its binary buffers."""

    view = _byte_view(body, label="frame body", error_type=FrameDecodeError)
    if len(view) > limits.max_frame_bytes:
        raise FrameDecodeError(f"frame length {len(view)} exceeds limit {limits.max_frame_bytes}")
    if len(view) < FRAME_HEADER_SIZE:
        raise FrameDecodeError("truncated frame header")

    magic, version, flags, header_size, metadata_len, buffer_count, total_len = _HEADER.unpack_from(
        view
    )
    if magic != FRAME_MAGIC:
        raise FrameDecodeError("invalid frame magic")
    if version != FRAME_VERSION:
        raise FrameDecodeError(f"unsupported frame version {version}")
    if flags != 0:
        raise FrameDecodeError(f"unsupported frame flags 0x{flags:02x}")
    if header_size != FRAME_HEADER_SIZE:
        raise FrameDecodeError(f"unsupported frame header size {header_size}")
    if total_len != len(view):
        raise FrameDecodeError(
            f"declared frame length {total_len} does not match body length {len(view)}"
        )
    if metadata_len > limits.max_metadata_bytes:
        raise FrameDecodeError(
            f"metadata length {metadata_len} exceeds limit {limits.max_metadata_bytes}"
        )
    if buffer_count > limits.max_buffers:
        raise FrameDecodeError(f"buffer count {buffer_count} exceeds limit {limits.max_buffers}")

    metadata_end = FRAME_HEADER_SIZE + metadata_len
    if metadata_end > len(view):
        raise FrameDecodeError("truncated frame metadata")
    try:
        metadata_text = bytes(view[FRAME_HEADER_SIZE:metadata_end]).decode("utf-8", "strict")
        message = json.loads(metadata_text, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise FrameDecodeError(f"invalid frame metadata JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise FrameDecodeError("frame metadata must decode to an object")

    position = _align(metadata_end)
    _require_zero_padding(view, metadata_end, position, "metadata")
    decoded: list[memoryview] = []
    for index in range(buffer_count):
        if position + _BUFFER_LENGTH.size > len(view):
            raise FrameDecodeError(f"truncated buffer {index} length")
        (buffer_len,) = _BUFFER_LENGTH.unpack_from(view, position)
        position += _BUFFER_LENGTH.size
        if buffer_len > limits.max_buffer_bytes:
            raise FrameDecodeError(
                f"buffer {index} length {buffer_len} exceeds limit {limits.max_buffer_bytes}"
            )
        end = position + buffer_len
        if end > len(view):
            raise FrameDecodeError(f"truncated buffer {index}")
        decoded.append(view[position:end])
        padded_end = _align(end)
        _require_zero_padding(view, end, padded_end, f"buffer {index}")
        position = padded_end
    if position != len(view):
        raise FrameDecodeError(f"frame has {len(view) - position} trailing bytes")
    return DecodedFrame(message=message, buffers=tuple(decoded))


__all__ = [
    "DEFAULT_FRAME_LIMITS",
    "FRAME_ALIGNMENT",
    "FRAME_HEADER_SIZE",
    "FRAME_MAGIC",
    "FRAME_VERSION",
    "DecodedFrame",
    "FrameDecodeError",
    "FrameEncodeError",
    "FrameError",
    "FrameLimits",
    "decode_frame",
    "encode_frame",
    "encode_frame_parts",
]
