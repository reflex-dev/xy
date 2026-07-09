"""Benchmark regression gate + doc auto-generation, stdlib only.

Compares a fresh benchmark run against a committed baseline
(`benchmarks/baseline.json`) and flags regressions. Two classes of metric,
because they behave very differently in CI:

- **Deterministic** (wire-payload bytes, bytes/point, tier decision): pure
  functions of N and the grid — byte-identical on every machine. Gated **hard**
  with a hair of tolerance; a regression here is always a real one (the
  screen-bounded-payload invariant broke), so CI fails.
- **Timing** (kernel Mpt/s, prep ms): vary wildly across shared runners. A 2x
  move is advisory; a 4x move is a hard catastrophic-regression gate. This
  leaves room for shared-runner noise while still catching deleted fast paths,
  accidental quadratic work, and other changes too large to wave away.

The baseline stores only *measured values*; the gate policy lives here
(classified by metric-id suffix) so re-blessing is a values-only diff.

    # after a bench run wrote scatter.json / kernel.json:
    python scripts/check_regressions.py --scatter scatter.json --kernel kernel.json
    python scripts/check_regressions.py ... --update-baseline   # re-bless
    python scripts/check_regressions.py ... --emit-md out.md     # regenerate table
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "benchmarks" / "baseline.json"


def _report_rows(report: Any) -> list:
    """Return benchmark rows from either legacy list JSON or schema-v2 report JSON."""
    if report is None:
        return []
    if isinstance(report, list):
        return report
    if isinstance(report, dict):
        rows = report.get("rows", [])
        return rows if isinstance(rows, list) else []
    return []


def flatten(scatter: list | dict | None, kernel: dict | None) -> dict:
    """Both bench JSONs -> a flat {metric_id: value} map."""
    out: dict[str, object] = {}
    for r in _report_rows(scatter):
        n = r["n"]
        out[f"scatter.tier.{n}"] = r["tier"]
        out[f"scatter.wire_bytes.{n}"] = r["wire_bytes"]
        out[f"scatter.wire_bytes_per_point.{n}"] = round(r["wire_bytes_per_point"], 4)
    for r in _report_rows(kernel):
        n = r["n"]
        for k, v in r.items():
            if k == "n" or not isinstance(v, (int, float)):
                continue
            out[f"kernel.{k}.{n}"] = v
    return out


def policy(metric_id: str) -> tuple[str, str, float]:
    """(cmp, gate, tol) for a metric id, by suffix. cmp in max|min|equals.

    Deterministic metrics (tier, wire bytes) gate hard; timing metrics
    (throughput Mpt/s, elapsed ms) gate advisory with a 2x band."""
    if ".tier." in metric_id:
        return "equals", "hard", 0.0
    if "wire_bytes" in metric_id:  # bytes and bytes_per_point: env-independent
        return "max", "hard", 0.02
    if "_mpts_s." in metric_id:  # throughput: higher is better
        return "min", "advisory", 0.5
    if "_ms." in metric_id:  # elapsed: lower is better
        return "max", "advisory", 1.0
    return "min", "advisory", 0.5


def regressed(cmp: str, base, cur, tol: float) -> bool:
    if cmp == "equals":
        return cur != base
    if base in (None, 0):
        return False
    if cmp == "max":
        return cur > base * (1.0 + tol)
    if cmp == "min":
        return cur < base * (1.0 - tol)
    return False


def catastrophic_timing_regression(metric_id: str, base, cur) -> bool:
    """True only for timing movement too large to attribute to CI noise."""
    if base in (None, 0) or not isinstance(base, (int, float)):
        return False
    if not isinstance(cur, (int, float)):
        return False
    if "_mpts_s." in metric_id:
        return cur < base * 0.25
    if "_ms." in metric_id:
        return cur > base * 4.0
    return False


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scatter", default=None, help="bench_scatter_native.py --json output")
    ap.add_argument("--kernel", default=None, help="bench_native.py --json output")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--emit-md", default=None, help="write a current-metrics markdown table here")
    args = ap.parse_args()

    scatter = json.loads(Path(args.scatter).read_text()) if args.scatter else None
    kernel = json.loads(Path(args.kernel).read_text()) if args.kernel else None
    if (
        isinstance(scatter, dict)
        and scatter.get("measurement_scope") != "production-figure-payload"
    ):
        raise SystemExit(
            "scatter regression input must use benchmarks/bench_scatter_native.py --production"
        )
    current = flatten(scatter, kernel)
    if not current:
        raise SystemExit("no metrics: pass --scatter and/or --kernel")

    if args.update_baseline:
        BASELINE.write_text(
            json.dumps({"metrics": dict(sorted(current.items()))}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"baseline re-blessed: {len(current)} metrics -> {BASELINE.relative_to(ROOT)}")
        return

    if not BASELINE.exists():
        raise SystemExit(f"no baseline at {BASELINE}; seed one with --update-baseline")
    base = json.loads(BASELINE.read_text())["metrics"]

    hard, advisory, rows = [], [], []
    for mid in sorted(set(base) | set(current)):
        if mid not in base:
            rows.append((mid, "—", _fmt(current[mid]), "new"))
            continue
        if mid not in current:
            rows.append((mid, _fmt(base[mid]), "—", "missing"))
            hard.append((mid, base[mid], "missing"))
            continue
        cmp, gate, tol = policy(mid)
        b, c = base[mid], current[mid]
        if regressed(cmp, b, c, tol):
            catastrophic = catastrophic_timing_regression(mid, b, c)
            is_hard = gate == "hard" or catastrophic
            (hard if is_hard else advisory).append((mid, b, c))
            rows.append((mid, _fmt(b), _fmt(c), "REGRESS" if is_hard else "warn"))
        else:
            rows.append((mid, _fmt(b), _fmt(c), "ok"))

    print("### Benchmark regression check\n")
    print("| metric | baseline | current | status |")
    print("|---|---:|---:|:--:|")
    for mid, b, c, st in rows:
        print(f"| {mid} | {b} | {c} | {st} |")
    print()

    if advisory:
        print(f"::warning::{len(advisory)} advisory timing regression(s) (>2x slower):")
        for mid, b, c in advisory:
            print(f"  - {mid}: {_fmt(b)} -> {_fmt(c)}")

    if args.emit_md:
        lines = [
            "### Auto-generated benchmark metrics",
            "",
            "Regenerated from the CI benchmark run; do not hand-edit.",
            "",
            "| metric | value |",
            "|---|---:|",
            *[f"| {mid} | {_fmt(current[mid])} |" for mid in sorted(current)],
        ]
        Path(args.emit_md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    if hard:
        print(f"\n{len(hard)} HARD regression(s):")
        for mid, b, c in hard:
            print(f"  ✗ {mid}: baseline {_fmt(b)} -> current {_fmt(c)}")
        raise SystemExit(1)
    print(
        f"OK: {len(current)} metrics, no hard regressions"
        f"{f', {len(advisory)} advisory' if advisory else ''}."
    )


if __name__ == "__main__":
    main()
