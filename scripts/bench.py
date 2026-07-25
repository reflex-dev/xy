"""Compatibility wrapper for benchmarks/bench.py."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "benchmarks" / "bench.py"),
    run_name="__main__",
)
