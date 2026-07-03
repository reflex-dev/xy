"""Compatibility wrapper for benchmarks/bench_scatter_native.py."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "benchmarks" / "bench_scatter_native.py"),
    run_name="__main__",
)
