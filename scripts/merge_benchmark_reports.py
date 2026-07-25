#!/usr/bin/env python3
"""Merge independently measured cross-library benchmark reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.bench_vs import to_markdown


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)
    if not isinstance(report, dict):
        raise SystemExit(f"{path} is not a JSON object")
    return report


def merge(paths: list[Path], expected_libraries: list[str]) -> dict[str, Any]:
    if not paths:
        raise SystemExit("no partial benchmark reports were found")

    reports = [_load(path) for path in paths]
    first = reports[0]
    for key in (
        "schema_version",
        "sizes",
        "budget_s",
        "benchmark_categories",
        "tracked_categories",
        "ttfr",
    ):
        if any(report.get(key) != first.get(key) for report in reports[1:]):
            raise SystemExit(f"partial reports disagree on {key!r}")

    results: dict[str, list[dict[str, Any]]] = {}
    for report, path in zip(reports, paths, strict=True):
        partial = report.get("results")
        if not isinstance(partial, dict) or not partial:
            raise SystemExit(f"{path} has no benchmark results")
        for library, rows in partial.items():
            if library in results:
                raise SystemExit(f"library {library!r} appears in more than one partial report")
            if not isinstance(rows, list) or not rows:
                raise SystemExit(f"{path} has no rows for library {library!r}")
            results[library] = rows

    missing = [library for library in expected_libraries if library not in results]
    unexpected = [library for library in results if library not in expected_libraries]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise SystemExit("partial report library mismatch (" + "; ".join(details) + ")")

    ordered_results = {library: results[library] for library in expected_libraries}
    environment_report = next(
        (report for report in reports if "xy" in report.get("results", {})),
        first,
    )
    budget = float(first["budget_s"])
    ceilings = {
        library: max(
            (
                row["n"]
                for row in rows
                if str(row.get("status", "")).startswith("ok")
                and isinstance(row.get("total_s"), (int, float))
                and row["total_s"] <= budget
            ),
            default=None,
        )
        for library, rows in ordered_results.items()
    }

    return {
        "schema_version": first["schema_version"],
        # Competitor-only jobs deliberately avoid installing xy and Rust. Use
        # the native partial as the canonical benchmark environment regardless
        # of artifact download order.
        "environment": environment_report["environment"],
        "libraries": expected_libraries,
        "sizes": first["sizes"],
        "budget_s": first["budget_s"],
        "benchmark_categories": first["benchmark_categories"],
        "tracked_categories": first["tracked_categories"],
        "results": ordered_results,
        "ceilings": ceilings,
        "ttfr": first["ttfr"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts", nargs="+", type=Path, required=True)
    parser.add_argument("--expected-libraries", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    expected = [item for item in args.expected_libraries.split(",") if item]
    report = merge(args.parts, expected)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    args.out_md.write_text(to_markdown(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
