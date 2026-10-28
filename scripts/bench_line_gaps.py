"""Measure payload cost of finite, isolated-gap and fragmented line inputs."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path

import numpy as np

import xy

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--geometry-hashes", action="store_true")
args = parser.parse_args()
records = []
for n in (1_000, 100_000, 1_000_000):
    for pattern in ("finite", "one_gap", "fragmented"):
        x = np.arange(n, dtype=float)
        y = np.sin(x * 0.01)
        if pattern == "one_gap":
            y[n // 2] = np.nan
        if pattern == "fragmented":
            y[50::100] = np.nan
        fig = xy.line_chart(xy.line(x, y), width=720, height=320).figure()
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            spec, blob = fig.build_payload()
            samples.append((time.perf_counter() - start) * 1000)
        trace = spec["traces"][0]
        record = {
            "n": n,
            "pattern": pattern,
            "build_ms": samples,
            "median_ms": statistics.median(samples),
            "marks": trace["n_marks"],
            "runs": spec["columns"][trace["runs"]]["len"] - 1 if "runs" in trace else None,
            "payload_bytes": len(blob),
        }
        if args.geometry_hashes:
            geometry = hashlib.sha256()
            for channel in ("x", "y"):
                meta = spec["columns"][trace[channel]]
                geometry.update(json.dumps(meta, sort_keys=True).encode())
                start = meta["byte_offset"]
                geometry.update(blob[start : start + meta["len"] * 4])
            record["geometry_sha256"] = geometry.hexdigest()
        records.append(record)
provenance = {}
if args.geometry_hashes:
    provenance["payload_source_sha256"] = hashlib.sha256(
        (Path(xy.__file__).parent / "_payload.py").read_bytes()
    ).hexdigest()
    native_path = os.environ.get("XY_NATIVE_LIB")
    if native_path:
        provenance["native_sha256"] = hashlib.sha256(Path(native_path).read_bytes()).hexdigest()
args.output.write_text(
    json.dumps(
        {
            "xy_module": xy.__file__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scope": "Three local payload builds; no interaction/FPS/memory claim",
            "records": records,
            **provenance,
        },
        indent=2,
    )
    + "\n"
)
