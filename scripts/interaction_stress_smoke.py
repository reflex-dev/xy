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
import math
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_benchmark_report  # noqa: E402

WORKER_REQUIRED_TRUE = (
    "worker_created",
    "worker_rebinned",
    "x_range_changed",
    "worker_terminated",
    "worker_cleared",
    "root_removed",
    "teardown_complete",
)
WORKER_OPTIONAL_UNAVAILABLE = (
    "skipped(",
    "failed(Node.js is required",
    "failed(Playwright is not installed",
)


def _load_bench_interaction():
    sys.path.insert(0, str(ROOT / "benchmarks"))
    path = ROOT / "benchmarks" / "bench_interaction.py"
    spec = importlib.util.spec_from_file_location("_xy_bench_interaction", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: str | None, payload: dict) -> None:
    if path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _worker_errors(worker: dict, *, allow_skip: bool) -> list[str]:
    status = str(worker.get("status", ""))
    if allow_skip and status.startswith(WORKER_OPTIONAL_UNAVAILABLE):
        return []
    if status != "ok":
        return [f"status is {status!r}, expected 'ok'"]

    errors = [
        f"{field} is not true" for field in WORKER_REQUIRED_TRUE if worker.get(field) is not True
    ]
    nonblank = worker.get("nonblank_pixels")
    if (
        isinstance(nonblank, bool)
        or not isinstance(nonblank, int | float)
        or not math.isfinite(nonblank)
        or nonblank <= 0
    ):
        errors.append(f"nonblank_pixels is not positive: {nonblank!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("chromium", nargs="?", default=None)
    parser.add_argument("--chromium", dest="chromium_flag", default=None)
    parser.add_argument("--sizes", default="1e4,2.5e5")
    parser.add_argument("--reps", type=int, default=12)
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="per-scenario probe relaunches on a non-ok status (headless "
        "Chromium on shared runners has environmental failure modes a fresh "
        "launch resolves; a real regression fails every attempt)",
    )
    parser.add_argument("--json", default=None, help="write the validated JSON report here")
    parser.add_argument("--markdown", default=None, help="write the Markdown report here")
    parser.add_argument(
        "--allow-worker-skip",
        action="store_true",
        help="local-only escape hatch for an unavailable Node/Playwright worker harness; "
        "CI and make check-browser intentionally omit it",
    )
    args = parser.parse_args(argv)

    chromium = args.chromium_flag or args.chromium
    if chromium and not (Path(chromium).is_file() or shutil.which(chromium)):
        failure = {
            "kind": "interaction-browser",
            "status": f"failed(configured chromium not found: {chromium})",
            "standalone_density_worker": {"status": "not-run"},
        }
        _write_json(args.json, failure)
        print(
            f"interaction stress smoke FAILED: configured chromium not found: {chromium}",
            file=sys.stderr,
        )
        return 1
    bench_interaction = _load_bench_interaction()
    report = bench_interaction.run(
        sizes=bench_interaction._parse_sizes(args.sizes),
        reps=args.reps,
        chromium=chromium,
        retries=args.retries,
    )
    with tempfile.TemporaryDirectory() as td:
        report_path = Path(td) / "interaction.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        errors = verify_benchmark_report.validate_report(report_path, kind="interaction-browser")

    if errors:
        _write_json(args.json, report)
        if args.markdown:
            Path(args.markdown).write_text(bench_interaction.to_markdown(report), encoding="utf-8")
        print("interaction stress smoke FAILED:", file=sys.stderr)
        for error in errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  ... {len(errors) - 20} more errors", file=sys.stderr)
        # The report JSON is not kept in CI, so surface every non-ok row's
        # status here — this is the only diagnostic a failed run leaves.
        for row in report.get("rows", []):
            status = row.get("status")
            if status != "ok":
                print(f"  - scenario {row.get('scenario')!r}: status={status!r}", file=sys.stderr)
        return 1

    worker = bench_interaction.run_worker_probe(chromium=chromium)
    report["standalone_density_worker"] = worker
    _write_json(args.json, report)
    if args.markdown:
        Path(args.markdown).write_text(bench_interaction.to_markdown(report), encoding="utf-8")
    worker_status = str(worker.get("status", ""))
    worker_errors = _worker_errors(worker, allow_skip=args.allow_worker_skip)
    if worker_errors:
        print("interaction stress smoke FAILED: standalone density worker probe", file=sys.stderr)
        for error in worker_errors:
            print(f"  - {error}", file=sys.stderr)
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
    if worker_status != "ok":
        print(f"  standalone_density_worker: SKIPPED BY EXPLICIT LOCAL OPT-IN ({worker_status})")
    else:
        print(
            "  standalone_density_worker: rebinned={rebinned} worker={worker} "
            "nonblank={nonblank} terminated={terminated} teardown={teardown}".format(
                rebinned=worker.get("worker_rebinned"),
                worker=worker.get("worker_created"),
                nonblank=worker.get("nonblank_pixels"),
                terminated=worker.get("worker_terminated"),
                teardown=worker.get("teardown_complete"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
