#!/usr/bin/env python3
"""Gated browser interaction smoke for core chart hardening.

The full browser interaction benchmark is still the richer report. This wrapper
runs a smoke-sized version, then validates the same budget/invariant schema so
`make check-browser` and CI catch interaction regressions: blank frames, axis
label pileups, tooltip flicker, missing crosshair chrome, missing view changes,
oversized frame color jumps, and p95 gesture regressions.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_benchmark_report  # noqa: E402


def _load_bench_interaction():
    sys.path.insert(0, str(ROOT / "benchmarks"))
    path = ROOT / "benchmarks" / "bench_interaction.py"
    spec = importlib.util.spec_from_file_location("_fastcharts_bench_interaction", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("chromium", nargs="?", default=None)
    parser.add_argument("--chromium", dest="chromium_flag", default=None)
    parser.add_argument("--sizes", default="1e4,2.5e5")
    parser.add_argument("--reps", type=int, default=12)
    parser.add_argument("--json", default=None, help="write the validated JSON report here")
    parser.add_argument("--markdown", default=None, help="write the Markdown report here")
    args = parser.parse_args(argv)

    chromium = args.chromium_flag or args.chromium
    bench_interaction = _load_bench_interaction()
    report = bench_interaction.run(
        sizes=bench_interaction._parse_sizes(args.sizes),
        reps=args.reps,
        chromium=chromium,
    )
    with tempfile.TemporaryDirectory() as td:
        report_path = Path(td) / "interaction.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        errors = verify_benchmark_report.validate_report(report_path, kind="interaction-browser")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(bench_interaction.to_markdown(report), encoding="utf-8")

    if errors:
        print("interaction stress smoke FAILED:", file=sys.stderr)
        for error in errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  ... {len(errors) - 20} more errors", file=sys.stderr)
        return 1

    print(
        "interaction stress smoke OK: "
        f"{len(report['rows'])} rows, reps={report['reps']}, "
        "budgets verified"
    )
    for row in report["rows"]:
        print(
            "  {scenario}: wheel={wheel:.1f}ms pan={pan:.1f}ms "
            "hover={hover:.1f}ms min_lit={min_lit} blank={blank} overlaps={overlaps}".format(
                scenario=row["scenario"],
                wheel=float(row["wheel_zoom_p95_ms"]),
                pan=float(row["pan_p95_ms"]),
                hover=float(row["hover_p95_ms"]),
                min_lit=row["min_interaction_lit_pixels"],
                blank=row["blank_frame_count"],
                overlaps=row["tick_label_overlap_count"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
