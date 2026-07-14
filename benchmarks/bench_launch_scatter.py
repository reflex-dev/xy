#!/usr/bin/env python3
"""Repeat complete static and interactive scatter cases in fresh processes."""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _launch_interactive as interactive
import _launch_static as static
import _launch_webagg as webagg

LIBRARIES = ("xy", "plotly", "matplotlib")
DEFAULT_SIZES = [10_000, 100_000, 1_000_000, 10_000_000, 1_000_000_000]


def summarize(samples: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    successful = [row for row in samples if row.get("status") == "ok" and metric in row]
    values = [float(row[metric]) for row in successful]
    result: dict[str, Any] = {
        "attempted_runs": len(samples),
        "successful_runs": len(values),
        "statuses": [row.get("status") for row in samples],
        "samples": samples,
    }
    if values:
        result.update(
            {
                "mean_ms": statistics.fmean(values),
                "median_ms": statistics.median(values),
                "stdev_ms": statistics.stdev(values) if len(values) > 1 else None,
                "min_ms": min(values),
                "max_ms": max(values),
            }
        )
    return result


def repeated(
    runner: Callable[[], dict[str, Any]],
    *,
    repetitions: int,
    metric: str,
    stop_on_failure: bool,
) -> dict[str, Any]:
    samples = []
    for _ in range(repetitions):
        row = runner()
        samples.append(row)
        if stop_on_failure and row.get("status") != "ok":
            break
    return summarize(samples, metric)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default=",".join(map(str, DEFAULT_SIZES)))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--libraries", default=",".join(LIBRARIES))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--memory-gib", type=float, default=36)
    parser.add_argument("--software", action="store_true")
    parser.add_argument(
        "--chrome",
        default=os.environ.get("CHROME", interactive.CHROME),
        help="Chrome/Chromium executable (defaults to $CHROME or macOS Google Chrome)",
    )
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--interactive-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    interactive.CHROME = args.chrome
    static.CHROME = args.chrome
    webagg.CHROME = args.chrome
    sizes = [int(value) for value in args.sizes.split(",")]
    libraries = [value.strip() for value in args.libraries.split(",") if value.strip()]
    unknown = sorted(set(libraries) - set(LIBRARIES))
    if unknown:
        parser.error(f"unknown libraries: {', '.join(unknown)}")
    limit = int(args.memory_gib * 2**30)
    result: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "repetitions_requested": args.repetitions,
        "aggregation": "arithmetic mean of successful fresh-process runs",
        "sizes": sizes,
        "software_browser": args.software,
        "static": [],
        "interactive": [],
    }
    if not args.interactive_only:
        for n in sizes:
            for library in libraries:
                summary = repeated(
                    lambda lib=library, count=n: static.run_isolated(
                        lib, count, timeout_s=args.timeout, memory_limit_bytes=limit
                    ),
                    repetitions=args.repetitions,
                    metric="render_ms",
                    stop_on_failure=True,
                )
                summary.update({"library": library, "n": n})
                result["static"].append(summary)
                print(
                    json.dumps(
                        {
                            "suite": "static",
                            "n": n,
                            "library": library,
                            "mean_ms": summary.get("mean_ms"),
                            "statuses": summary["statuses"],
                        }
                    ),
                    flush=True,
                )
    if not args.static_only:
        interactive.ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for n in sizes:
            for library in libraries:

                def one(lib: str = library, count: int = n) -> dict[str, Any]:
                    if lib == "matplotlib":
                        return webagg.benchmark_one(
                            count,
                            timeout_s=args.timeout,
                            memory_limit_bytes=limit,
                            software=args.software,
                        )
                    artifact = (
                        interactive.ARTIFACTS / f"repeat-{lib}-{count}.html"
                        if lib != "matplotlib"
                        else None
                    )
                    row = interactive.run_isolated(
                        lib,
                        count,
                        timeout_s=args.timeout,
                        memory_limit_bytes=limit,
                        artifact=artifact,
                    )
                    if row.get("status") == "ok" and artifact is not None:
                        probe = interactive.browser_once(
                            artifact,
                            timeout_s=args.timeout,
                            memory_limit_bytes=limit,
                            software=args.software,
                        )
                        row["browser_probe"] = probe
                        if probe.get("status") == "ok":
                            row["end_to_end_ttfr_ms"] = float(row["python_render_ms"]) + float(
                                probe["ready_ms"]
                            )
                            row["browser_renderer"] = probe.get("renderer")
                        else:
                            row["status"] = "browser_" + str(probe.get("status"))
                    elif row.get("status") == "ok":
                        row["end_to_end_ttfr_ms"] = row["python_render_ms"]
                    return row

                summary = repeated(
                    one,
                    repetitions=args.repetitions,
                    metric="end_to_end_ttfr_ms",
                    stop_on_failure=True,
                )
                summary.update({"library": library, "n": n})
                result["interactive"].append(summary)
                print(
                    json.dumps(
                        {
                            "suite": "interactive",
                            "software": args.software,
                            "n": n,
                            "library": library,
                            "mean_ms": summary.get("mean_ms"),
                            "statuses": summary["statuses"],
                        }
                    ),
                    flush=True,
                )
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
