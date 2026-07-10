"""Benchmark harness (§12) — run every phase, report per mode, never let the
happy path stand in for the whole (§2).

Usage: python benchmarks/bench.py [--sizes 1e5,1e6,1e7]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xy as fc
from categories import categories_for  # noqa: E402
from xy import kernels as k

BENCH_CATEGORY_IDS = ("huge_line_time_series", "payload_export_size")


def timeit(fn, *args, repeat: int = 3):
    best = float("inf")
    result = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        result = fn(*args)
        best = min(best, time.perf_counter() - t0)
    return best, result


def bench_size(n: int) -> dict:
    rng = np.random.default_rng(42)
    x = np.arange(n, dtype=np.float64)
    y = rng.normal(0.0, 1.0, n)

    row: dict = {
        "n": n,
        "backend": k.BACKEND,
        "benchmark_categories": [category["id"] for category in categories_for(BENCH_CATEGORY_IDS)],
    }

    t, _ = timeit(k.zone_maps, x)
    row["zone_maps_mpts_s"] = n / t / 1e6

    t, _ = timeit(k.encode_f32, y, 0.0, 1.0)
    row["encode_f32_mpts_s"] = n / t / 1e6

    t, idx = timeit(k.m4_indices, x, y, 0.0, float(n), 2048)
    row["m4_mpts_s"] = n / t / 1e6
    row["m4_out_points"] = len(idx)

    # End-to-end first paint: figure build → payload bytes on the wire.
    fig = fc.chart(fc.line(x=x, y=y)).figure()
    t, (_spec, blob) = timeit(fig.build_payload, 2048, repeat=1)
    row["payload_build_s"] = t
    row["payload_bytes"] = len(blob)
    row["payload_bytes_per_point"] = len(blob) / n
    row["canonical_bytes_per_point"] = fig.store.memory_report()["canonical_bytes"] / n

    # Zoom interaction: kernel-side re-decimation of a 1% window (§17 budget:
    # 100-300 ms non-blocking; measure the compute part).
    x0, x1 = n * 0.495, n * 0.505
    t, _ = timeit(fig.decimate_view, x0, x1, 2048)
    row["zoom_redecimate_ms"] = t * 1e3
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e5,1e6,1e7")
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]

    print(f"backend: {k.BACKEND}")
    rows = [bench_size(n) for n in sizes]
    for r in rows:
        print(json.dumps(r))

    print("\n| points | zone maps | encode f32 | M4 | wire B/pt | zoom re-decimate |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['n']:,} | {r['zone_maps_mpts_s']:.0f} Mpt/s "
            f"| {r['encode_f32_mpts_s']:.0f} Mpt/s | {r['m4_mpts_s']:.0f} Mpt/s "
            f"| {r['payload_bytes_per_point']:.3f} | {r['zoom_redecimate_ms']:.1f} ms |"
        )


if __name__ == "__main__":
    main()
