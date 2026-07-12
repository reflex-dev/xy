#!/usr/bin/env python3
"""Production heatmap payload and native static-PNG scaling benchmark.

Fixture construction is reported but excluded from the production timings.
The source matrix is a deterministic f64 ramp, which makes exact dimensions,
payload size, and output validity independently checkable even at ceiling
sizes where keeping a second oracle matrix would distort peak memory.
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import xy as fc  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402
from xy import _raster  # noqa: E402

RENDER_W, RENDER_H = 900, 420
CATEGORY_IDS = ("core_2d_chart_breadth", "static_export", "payload_export_size")


def _parse_sides(value: str) -> list[int]:
    sides = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not sides or any(side <= 0 for side in sides):
        raise argparse.ArgumentTypeError("--sides must contain positive comma-separated integers")
    return sides


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _fmt_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _bench_side(side: int, requested_reps: int) -> dict[str, object]:
    cells = side * side
    start = time.perf_counter()
    values = np.arange(cells, dtype=np.float64).reshape(side, side)
    fixture_ms = (time.perf_counter() - start) * 1e3

    start = time.perf_counter()
    figure = fc.heatmap_chart(
        fc.heatmap(values, domain=(0.0, float(max(1, cells - 1)))),
        width=RENDER_W,
        height=RENDER_H,
    ).figure()
    construct_ms = (time.perf_counter() - start) * 1e3

    start = time.perf_counter()
    spec, blob, borrowed = figure._build_raster_payload()
    payload_ms = (time.perf_counter() - start) * 1e3
    heatmap = spec["traces"][0]["heatmap"]
    column = spec["columns"][heatmap["buf"]]
    if (
        int(heatmap["w"]) != side
        or int(heatmap["h"]) != side
        or int(column["len"]) != cells
        or len(blob) != 0
        or len(borrowed) != 1
        or int(borrowed[0].nbytes) != cells * 8
    ):
        raise AssertionError("production heatmap payload shape/size oracle failed")

    reps = 1 if cells >= 100_000_000 else requested_reps
    samples: list[float] = []
    png = b""
    for _ in range(reps):
        start = time.perf_counter()
        rendered = _raster.render_raster(
            spec,
            blob,
            1.0,
            fast_png=True,
            borrowed=borrowed,
        )
        samples.append((time.perf_counter() - start) * 1e3)
        png = rendered if isinstance(rendered, bytes) else b""
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("native heatmap render did not produce a PNG")

    native_png_ms = statistics.median(samples)
    return {
        "side": side,
        "cells": cells,
        "benchmark_categories": [category["id"] for category in categories_for(CATEGORY_IDS)],
        "fixture_ms_excluded": fixture_ms,
        "figure_construct_ms": construct_ms,
        "payload_ms": payload_ms,
        "native_png_ms": native_png_ms,
        "source_to_native_png_ms": construct_ms + payload_ms + native_png_ms,
        "canonical_bytes": int(values.nbytes),
        "payload_bytes": len(blob),
        "borrowed_bytes": int(sum(span.nbytes for span in borrowed)),
        "native_png_bytes": len(png),
        "peak_rss_bytes": _peak_rss_bytes(),
        "reps": reps,
        "oracle_status": "pass",
        "measurement_scope": "production-heatmap-payload-and-native-png",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sides", type=_parse_sides, default=_parse_sides("512,1024,2048"))
    parser.add_argument("--reps", type=int, default=7)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.reps <= 0:
        parser.error("--reps must be positive")

    rows = []
    for side in args.sides:
        row = _bench_side(side, args.reps)
        rows.append(row)
        gc.collect()

    print("xy native heatmap — production payload and 900x420 PNG")
    print("| grid | cells | owned / borrowed | native PNG | source-to-PNG | peak RSS |")
    print("|---|---:|---:|---:|---:|---:|")
    for row in rows:
        print(
            f"| {row['side']}x{row['side']} | {row['cells']:,} | "
            f"{_fmt_bytes(int(row['payload_bytes']))} / "
            f"{_fmt_bytes(int(row['borrowed_bytes']))} | "
            f"{float(row['native_png_ms']):.2f} ms | "
            f"{float(row['source_to_native_png_ms']):.2f} ms | "
            f"{_fmt_bytes(int(row['peak_rss_bytes']))} |"
        )

    if args.json:
        report = {
            "schema_version": SCHEMA_VERSION,
            "kind": "heatmap-native",
            "measurement_scope": "production-heatmap-payload-and-native-png",
            "data_generator": "numpy-f64-ramp",
            "environment": collect_environment_metadata(xy_backend="native"),
            "benchmark_categories": list(BENCHMARK_CATEGORIES),
            "tracked_categories": categories_for(CATEGORY_IDS),
            "rows": rows,
        }
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
