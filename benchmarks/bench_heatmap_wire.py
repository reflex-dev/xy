#!/usr/bin/env python3
"""Measure scalar and truecolor heatmap first-paint wire quantization.

Fixture construction is excluded. The byte oracles are exact: scalar grids
ship one byte per cell (plus at most three alignment bytes), while truecolor
grids ship one interleaved RGBA byte quartet per cell. The benchmark also
proves packed and split layouts contain identical bytes.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402


def _parse_sides(value: str) -> list[int]:
    sides = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not sides or any(side <= 0 for side in sides):
        raise argparse.ArgumentTypeError("--sides must contain positive comma-separated integers")
    return sides


def _fmt_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _fixture(kind: str, side: int) -> np.ndarray:
    cells = side * side
    if kind == "scalar":
        return np.arange(cells, dtype=np.float64).reshape(side, side)
    rgba = np.empty((side, side, 4), dtype=np.uint8)
    col = (np.arange(side, dtype=np.uint32) % 256).astype(np.uint8)
    row = ((np.arange(side, dtype=np.uint32) * 17) % 256).astype(np.uint8)
    rgba[..., 0] = col[None, :]
    rgba[..., 1] = row[:, None]
    rgba[..., 2] = 127
    rgba[..., 3] = row[:, None]
    return rgba


def _bench(kind: str, side: int, reps: int) -> dict[str, int | float | str]:
    cells = side * side
    source = _fixture(kind, side)
    start = time.perf_counter()
    mark = (
        xy.heatmap(source, domain=(0.0, float(max(1, cells - 1))))
        if kind == "scalar"
        else xy.heatmap(source)
    )
    figure = xy.heatmap_chart(mark).figure()
    construct_ms = (time.perf_counter() - start) * 1e3

    samples: list[float] = []
    spec: dict = {}
    blob = b""
    for _ in range(reps):
        start = time.perf_counter()
        spec, blob = figure.build_payload()
        samples.append((time.perf_counter() - start) * 1e3)

    heatmap = spec["traces"][0]["heatmap"]
    ref = heatmap["buf"] if kind == "scalar" else heatmap["rgba_buf"]
    column = spec["columns"][ref]
    expected_values = cells if kind == "scalar" else cells * 4
    expected_bytes = (expected_values + 3) // 4 * 4
    expected_encoding = "unit-u8" if kind == "scalar" else "rgba8"
    if (
        heatmap.get("enc") != expected_encoding
        or column.get("dtype") != "u8"
        or int(column["len"]) != expected_values
        or len(blob) != expected_bytes
    ):
        raise AssertionError(f"{kind} heatmap wire byte oracle failed")

    split_spec, buffers = figure.build_payload_split()
    split_heatmap = split_spec["traces"][0]["heatmap"]
    split_ref = split_heatmap["buf"] if kind == "scalar" else split_heatmap["rgba_buf"]
    split_column = split_spec["columns"][split_ref]
    if len(buffers) != 1 or bytes(buffers[split_column["buf"]]) != blob:
        raise AssertionError(f"{kind} packed/split wire parity failed")

    legacy_bytes = cells * (4 if kind == "scalar" else 16)
    return {
        "kind": kind,
        "side": side,
        "cells": cells,
        "construct_ms_excluded": construct_ms,
        "payload_median_ms": statistics.median(samples),
        "wire_bytes": len(blob),
        "legacy_wire_bytes": legacy_bytes,
        "reduction": legacy_bytes / len(blob),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sides", type=_parse_sides, default=_parse_sides("1000,2000"))
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args()
    if args.reps <= 0:
        parser.error("--reps must be positive")

    rows = [
        _bench(kind, side, args.reps) for side in args.sides for kind in ("scalar", "truecolor")
    ]
    print("xy heatmap first-paint wire quantization (fixture construction excluded)")
    print("| kind | grid | old wire | compact wire | reduction | payload median |")
    print("|---|---:|---:|---:|---:|---:|")
    for row in rows:
        print(
            f"| {row['kind']} | {row['side']}x{row['side']} | "
            f"{_fmt_bytes(int(row['legacy_wire_bytes']))} | "
            f"{_fmt_bytes(int(row['wire_bytes']))} | {float(row['reduction']):.1f}x | "
            f"{float(row['payload_median_ms']):.2f} ms |"
        )


if __name__ == "__main__":
    main()
