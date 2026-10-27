#!/usr/bin/env python3
"""Re-derive every published ceiling number from a bench_ceiling.py report.

Nothing in the docs should be a number somebody typed.  Point this at the raw
JSON and it prints the tables, the per-arm ceilings, and the chart value lists
in the form the docs demo consumes.

  python benchmarks/summarize_ceiling.py ceiling-results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GIB = 2**30


def label(n: int) -> str:
    if n >= 1_000_000:
        value = n / 1_000_000
        return f"{value:g}M"
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def gib(value: Any) -> float | None:
    if value in (None, 0):
        return None
    return round(int(value) / GIB, 3)


def cell(rows: dict[tuple[str, int], dict[str, Any]], arm: str, n: int) -> dict[str, Any] | None:
    return rows.get((arm, n))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--interactive-budget-ms",
        type=float,
        default=100.0,
        help="gesture p95 above this is rendering, not interacting (default 100 ms = 10 fps)",
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    results = report["results"]
    sizes: list[int] = report["method"]["sizes"]
    arms: list[str] = list(report["method"]["arms"])
    rows = {(r["arm"], r["n"]): r for r in results}

    # A headless Chrome with an empty profile already resides ~1 GiB before it
    # has drawn anything.  The n=10 row of each arm is that floor, so browser
    # memory attributable to the chart is the peak above its own arm's floor.
    floor: dict[str, float] = {}
    smallest = min(sizes)
    for arm in arms:
        base = cell(rows, arm, smallest)
        if base and base.get("browser_peak_rss_bytes"):
            floor[arm] = int(base["browser_peak_rss_bytes"]) / GIB

    # "It rendered" and "you can use it" are different ceilings, and for the
    # exact-marker arms they diverge by more than an order of magnitude.  A
    # gesture p95 above the budget is a chart that technically drew and then
    # answered a pan a second and a half later.
    budget = args.interactive_budget_ms
    print("## Ceilings\n")
    print(
        f"Interactive ceiling = largest N that renders *and* keeps gesture p95 ≤ {budget:g} ms.\n"
    )
    print("| Arm | Contract | Renders to | Interactive to | Mode | Stopped by |")
    print("| --- | --- | ---: | ---: | --- | --- |")
    ceilings: dict[str, dict[str, Any]] = {}
    for arm in arms:
        ok = [n for n in sizes if (c := cell(rows, arm, n)) and c.get("status") == "ok"]
        usable = [
            n
            for n in ok
            if (p := cell(rows, arm, n).get("gesture_p95_ms")) is not None and float(p) <= budget
        ]
        failed = [
            (n, c)
            for n in sizes
            if (c := cell(rows, arm, n)) and c.get("status") not in ("ok", "not_attempted")
        ]
        top = max(ok) if ok else None
        play = max(usable) if usable else None
        contract = report["method"]["arms"][arm]["contract"]
        stop = failed[0][1].get("status") if failed else "not reached in this ladder"
        mode = cell(rows, arm, top).get("mode") if top else "—"
        measured = top is not None and cell(rows, arm, top).get("gesture_measured") is not False
        play_text = label(play) if play else ("not measured" if not measured else "—")
        ceilings[arm] = {"renders_to": top, "interactive_to": play, "stopped_by": stop}
        print(
            f"| {arm} | {contract} | {label(top) if top else '—'} | {play_text} | {mode} | {stop} |"
        )

    print("\n## Peak memory by size (GiB)\n")
    head = " | ".join(label(n) for n in sizes)
    print(f"| Arm | Pool | {head} |")
    print("| --- | --- |" + " ---: |" * len(sizes))
    for arm in arms:
        for pool, key in (
            ("python", "python_peak_rss_bytes"),
            ("browser", "browser_peak_rss_bytes"),
        ):
            cells = []
            any_value = False
            for n in sizes:
                c = cell(rows, arm, n)
                value = gib(c.get(key)) if c else None
                if c and c.get("status") == "not_attempted":
                    cells.append("—")
                elif value is None:
                    cells.append("·")
                else:
                    any_value = True
                    cells.append(f"{value:.3f}")
            if any_value:
                print(f"| {arm} | {pool} | " + " | ".join(cells) + " |")

    if floor:
        print("\n### Browser memory above the empty-Chrome floor (GiB)\n")
        print(f"| Arm | floor | {head} |")
        print("| --- | ---: |" + " ---: |" * len(sizes))
        for arm in arms:
            if arm not in floor:
                continue
            cells = []
            for n in sizes:
                c = cell(rows, arm, n)
                raw = c.get("browser_peak_rss_bytes") if c else None
                if not raw:
                    cells.append("·")
                else:
                    cells.append(f"{int(raw) / GIB - floor[arm]:+.3f}")
            print(f"| {arm} | {floor[arm]:.3f} | " + " | ".join(cells) + " |")

    print("\n## Time until all points are visible (ttfr, s)\n")
    print("Python build + last canvas change before pixel quiescence — not first paint.\n")
    print(f"| Arm | {head} |")
    print("| --- |" + " ---: |" * len(sizes))
    for arm in arms:
        cells = []
        any_value = False
        for n in sizes:
            c = cell(rows, arm, n)
            value = c.get("ttfr_ms") if c else None
            if value is None:
                cells.append("·")
            else:
                any_value = True
                cells.append(f"{float(value) / 1e3:.3f}")
        if any_value:
            print(f"| {arm} | " + " | ".join(cells) + " |")

    print("\n## Interaction cost (gesture p95, ms)\n")
    print(f"| Arm | {head} |")
    print("| --- |" + " ---: |" * len(sizes))
    for arm in arms:
        cells = []
        any_value = False
        for n in sizes:
            c = cell(rows, arm, n)
            value = c.get("gesture_p95_ms") if c else None
            if value is None:
                cells.append("·")
            else:
                any_value = True
                cells.append(f"{float(value):.1f}")
        if any_value:
            print(f"| {arm} | " + " | ".join(cells) + " |")

    print("\n## What each arm actually rendered\n")
    print(f"| Arm | {head} |")
    print("| --- |" + " ---: |" * len(sizes))
    for arm in arms:
        cells = []
        for n in sizes:
            c = cell(rows, arm, n)
            rendered = c.get("points_rendered") if c else None
            cells.append("·" if rendered is None else f"{int(rendered):,}")
        print(f"| {arm} | " + " | ".join(cells) + " |")

    print("\n## Chart values (paste into the docs demo)\n")
    print(f"_CEILING_SIZE_LABELS = {[label(n) for n in sizes]!r}")
    for arm in arms:
        series = []
        for n in sizes:
            c = cell(rows, arm, n)
            if not c or c.get("status") != "ok":
                break
            total = int(c.get("python_peak_rss_bytes") or 0) + int(
                c.get("browser_peak_rss_bytes") or 0
            )
            series.append(round(total / GIB, 3))
        key = arm.upper().replace("-", "_")
        print(f"_{key}_PEAK_GIB = {series!r}")
    print(f"\n_CEILINGS = {json.dumps(ceilings)}")

    oracles = sorted(
        {r.get("oracle") for r in results if r.get("status") == "ok" and r.get("oracle")}
    )
    print(f"\nOracles exercised: {', '.join(oracles)}")
    git = report["environment"].get("git", {})
    dirty = " (dirty)" if git.get("dirty") else ""
    print(f"Source commit: {git.get('commit', '?')}{dirty}")
    print(f"Browser renderer: {report['method'].get('browser_renderer_requested', '?')}")


if __name__ == "__main__":
    main()
