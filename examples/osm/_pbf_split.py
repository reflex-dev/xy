"""Minimal PBF *framing* scanner — enumerate blob byte-ranges for parallel
parsing. This reads only the fixed 4-byte length prefixes and the small
`BlobHeader` protobuf (type + datasize) to walk from one blob to the next; it
never touches the compressed OSM payload. pyosmium still performs the actual
(trusted) coordinate decode on each byte range via `osmium.io.FileBuffer`.

A .osm.pbf file is a sequence of:
    [4-byte big-endian BlobHeader length][BlobHeader protobuf][Blob protobuf]
The first blob is an `OSMHeader`; the rest are `OSMData`. A byte range made of
`OSMHeader` bytes followed by any run of whole `OSMData` blobs is itself a valid
PBF stream, so it can be parsed independently in another process.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


def _read_varint(buf: memoryview, pos: int) -> tuple[int, int]:
    """Decode a protobuf base-128 varint at ``pos``; return (value, new_pos)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _blob_header_fields(bh: memoryview) -> tuple[str, int]:
    """Extract (type, datasize) from a BlobHeader protobuf (fields 1 and 3)."""
    pos = 0
    btype = ""
    datasize = -1
    n = len(bh)
    while pos < n:
        tag, pos = _read_varint(bh, pos)
        field, wire = tag >> 3, tag & 0x7
        if wire == 2:  # length-delimited
            ln, pos = _read_varint(bh, pos)
            if field == 1:  # type (string)
                btype = bytes(bh[pos : pos + ln]).decode("ascii")
            pos += ln
        elif wire == 0:  # varint
            val, pos = _read_varint(bh, pos)
            if field == 3:  # datasize
                datasize = val
        else:  # 32/64-bit — not used by BlobHeader, skip defensively
            pos += 4 if wire == 5 else 8
    if datasize < 0:
        raise ValueError("BlobHeader missing datasize")
    return btype, datasize


@dataclass
class Blob:
    start: int  # byte offset of the 4-byte length prefix
    end: int  # byte offset just past the blob body
    btype: str


def scan_blobs(mm: memoryview) -> list[Blob]:
    """Walk every blob in the mapped file, returning their byte ranges."""
    blobs: list[Blob] = []
    pos = 0
    total = len(mm)
    while pos + 4 <= total:
        (hlen,) = struct.unpack_from(">I", mm, pos)
        hstart = pos + 4
        btype, datasize = _blob_header_fields(mm[hstart : hstart + hlen])
        end = hstart + hlen + datasize
        if end > total:
            break  # truncated tail (e.g. partial download) — stop cleanly
        blobs.append(Blob(pos, end, btype))
        pos = end
    return blobs


def partition(blobs: list[Blob], n_parts: int) -> list[tuple[int, int]]:
    """Split the OSMData blobs into ``n_parts`` contiguous (start,end) byte
    ranges. The OSMHeader blob (blobs[0]) is excluded — callers prepend it."""
    data = [b for b in blobs if b.btype == "OSMData"]
    if not data:
        return []
    per = -(-len(data) // n_parts)  # ceil
    parts: list[tuple[int, int]] = []
    for i in range(0, len(data), per):
        group = data[i : i + per]
        parts.append((group[0].start, group[-1].end))
    return parts
