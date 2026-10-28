"""Payload-only comparison; correctness baseline bridges gaps and drops lower extrema."""

import json
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from xy._figure import Figure

records = []
for n in (1000, 100_000, 1_000_000):
    for fragmentation in ("finite", "one-gap", "every-100"):
        x = np.arange(n, dtype=float)
        top = 5 + np.sin(x * 0.005)
        base = 1 + np.cos(x * 0.009)
        if fragmentation == "one-gap":
            top[n // 2] = np.nan
        if fragmentation == "every-100":
            top[::100] = np.nan
        fig = Figure(width=720, height=300).area(x, top, base=base)
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            spec, blob = fig.build_payload()
            samples.append((time.perf_counter() - start) * 1000)
        records.append(
            {
                "rows": n,
                "fragmentation": fragmentation,
                "ms": samples,
                "median_ms": statistics.median(samples),
                "marks": spec["traces"][0]["n_marks"],
                "payload_bytes": len(blob),
                "runs": ("runs" in spec["traces"][0]),
                "canonical_top_unchanged": bool(
                    np.array_equal(fig.traces[0].y.values, top, equal_nan=True)
                ),
                "canonical_base_unchanged": bool(
                    np.array_equal(fig.traces[0].base.values, base, equal_nan=True)
                ),
            }
        )
result = {
    "source": str(Path(__import__("xy").__file__).resolve()),
    "platform": platform.platform(),
    "python": sys.version,
    "numpy": np.__version__,
    "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "measure": "payload construction only; no browser/FPS/memory-delta claim",
    "records": records,
}
Path(sys.argv[1]).write_text(json.dumps(result, indent=2))
print(json.dumps(records))
