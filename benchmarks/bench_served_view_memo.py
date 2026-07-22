"""Measure the kernel work and exact reply bytes an accepted client memo avoids.

This is a deterministic transport accounting benchmark, not a synthetic cache
lookup microbenchmark. It serves the same decimated-line plus density-drill
window the browser lifecycle test uses and reports the two kernel round trips,
binary payload bytes, and complete XYBF frame bytes eliminated by an exact hit.

Run with::

    PYTHONPATH=python .venv/bin/python benchmarks/bench_served_view_memo.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np

from xy._figure import Figure
from xy._framing import encode_frame


def _serve(fig: Figure, *, seq: int) -> tuple[int, int, int]:
    tier, tier_buffers = fig.decimate_view(10.0, 20.0, 480)
    density, density_buffers = fig.density_view(1, 10.0, 20.0, -1.0, 1.0, 480, 360)
    tier_message = {"type": "tier_update", "seq": seq, **tier}
    density_message = {"type": "density_update", "seq": seq, **density}
    payload_bytes = sum(map(len, tier_buffers)) + sum(map(len, density_buffers))
    frame_bytes = len(encode_frame(tier_message, tier_buffers)) + len(
        encode_frame(density_message, density_buffers)
    )
    return payload_bytes, frame_bytes, sum(map(len, tier_buffers))


def run(n: int, reps: int) -> dict[str, int | float | str]:
    x = np.linspace(0.0, 100.0, n, dtype=np.float64)
    fig = Figure(width=480, height=360, padding=0)
    fig.line(x, np.sin(x))
    fig.scatter(x, np.cos(x), density=True)
    fig.build_payload(480)
    _serve(fig, seq=1)  # warm imports/allocators and establish drill state

    elapsed_ms: list[float] = []
    result = (0, 0, 0)
    for seq in range(2, reps + 2):
        start = time.perf_counter()
        result = _serve(fig, seq=seq)
        elapsed_ms.append((time.perf_counter() - start) * 1_000.0)
    payload_bytes, frame_bytes, tier_payload_bytes = result
    return {
        "scenario": "accepted_duplicate_tier_density_view",
        "n": n,
        "repetitions": reps,
        "baseline_round_trips": 2,
        "memo_hit_round_trips": 0,
        "round_trips_avoided": 2,
        "reply_payload_bytes_avoided": payload_bytes,
        "reply_xybf_bytes_avoided": frame_bytes,
        "y_only_pan_tier_payload_bytes_avoided": tier_payload_bytes,
        "kernel_service_ms_avoided_median": statistics.median(elapsed_ms),
        "kernel_service_ms_avoided_min": min(elapsed_ms),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=120_000)
    parser.add_argument("--reps", type=int, default=21)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.n <= 50_000:
        parser.error("--n must exceed the line decimation threshold (50000)")
    if args.reps <= 0:
        parser.error("--reps must be positive")
    result = run(args.n, args.reps)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
