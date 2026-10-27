#!/usr/bin/env python3
"""Re-derive the UX ladder's tables from a directory of bench_ux reports.

Point it at the suite output directory; it reads every `ux-*.json`, so a
partial ladder summarizes cleanly while the rest is still running.

    python benchmarks/summarize_ux.py /Users/alek/Desktop/xy-ux-suite
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GIB = 2**30
ARM_ORDER = ("xy", "xy-exact", "plotly", "matplotlib", "datashader")


def label(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    return f"{n // 1000}k"


def table(
    title: str,
    note: str,
    rows: dict[tuple[str, int], dict[str, Any]],
    sizes: list[int],
    arms: list[str],
    render: Any,
) -> None:
    print(f"\n## {title}\n")
    if note:
        print(f"{note}\n")
    head = " | ".join(label(n) for n in sizes)
    print(f"| Arm | {head} |")
    print("| --- |" + " ---: |" * len(sizes))
    for arm in arms:
        cells = []
        for n in sizes:
            row = rows.get((arm, n))
            if row is None:
                cells.append("·")
            elif row.get("status") != "ok":
                # A failure is a result: name it rather than blanking it.
                cells.append(f"✕ {row['status'].replace('_', ' ')}")
            else:
                cells.append(render(row))
        print(f"| {arm} | " + " | ".join(cells) + " |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite_dir", type=Path)
    args = parser.parse_args()

    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted(args.suite_dir.glob("ux-*.json")):
        for row in json.loads(path.read_text()).get("results", []):
            rows[(row["arm"], row["n"])] = row
    if not rows:
        parser.error(f"no ux-*.json under {args.suite_dir}")

    sizes = sorted({n for _, n in rows})
    arms = [a for a in ARM_ORDER if any(a == arm for arm, _ in rows)]

    def secs(key: str) -> Any:
        def render(row: dict[str, Any]) -> str:
            value = row.get(key)
            return "·" if value is None else f"{float(value) / 1000:.3f}"

        return render

    def ms(key: str) -> Any:
        def render(row: dict[str, Any]) -> str:
            value = row.get(key)
            return "·" if value is None else f"{float(value):.1f}"

        return render

    def gib(*keys: str) -> Any:
        def render(row: dict[str, Any]) -> str:
            total = sum(int(row.get(k) or 0) for k in keys)
            return "·" if total == 0 else f"{total / GIB:.2f}"

        return render

    table(
        "Time to render (s)",
        "Navigation to every point correct-and-stable on screen.",
        rows,
        sizes,
        arms,
        secs("visible_complete_ms"),
    )
    table(
        "Peak memory, Python + browser (GiB)",
        "Both process trees, polled from spawn. A headless-Chrome floor of "
        "~1.0 GiB is included and never subtracted — read each arm against "
        "its own smallest size.",
        rows,
        sizes,
        arms,
        gib("python_peak_rss_bytes", "browser_peak_rss_bytes"),
    )
    table(
        "Peak memory, Python only (GiB)",
        "No browser floor, so this column is directly comparable across arms.",
        rows,
        sizes,
        arms,
        gib("python_peak_rss_bytes"),
    )
    table(
        "Frame time during zoom, p95 (ms)",
        "95% of animation frames completed at least this fast while the scripted gesture ran.",
        rows,
        sizes,
        arms,
        ms("gesture_frame_p95_ms"),
    )
    table(
        "Settle after the gesture (ms)",
        "Last input to correct-and-stable again — where deferred work is charged.",
        rows,
        sizes,
        arms,
        ms("settle_ms"),
    )
    table(
        "Zoom to final view (s)",
        "First input to the correct final frame, measured end to end.",
        rows,
        sizes,
        arms,
        secs("zoom_to_final_ms"),
    )

    print("\n## Ceilings\n")
    print("| Arm | Renders to | Interactive to (p95 ≤ 100 ms) | Stopped by |")
    print("| --- | ---: | ---: | --- |")
    for arm in arms:
        ok = [n for n in sizes if rows.get((arm, n), {}).get("status") == "ok"]
        usable = [
            n
            for n in ok
            if (p := rows[(arm, n)].get("gesture_frame_p95_ms")) is not None and float(p) <= 100
        ]
        failed = [
            (n, rows[(arm, n)])
            for n in sizes
            if (arm, n) in rows and rows[(arm, n)].get("status") != "ok"
        ]
        stop = failed[0][1]["status"] if failed else "not reached in this ladder"
        print(
            f"| {arm} | {label(max(ok)) if ok else '—'} "
            f"| {label(max(usable)) if usable else '—'} | {stop} |"
        )

    modes = {
        arm: {label(n): rows[(arm, n)].get("mode") for n in sizes if (arm, n) in rows}
        for arm in arms
    }
    print("\n## Render mode per size\n")
    for arm in arms:
        seen = {}
        for size_label, mode in modes[arm].items():
            seen.setdefault(mode, []).append(size_label)
        parts = [f"{mode}: {', '.join(v)}" for mode, v in seen.items() if mode]
        print(f"- **{arm}** — {' · '.join(parts)}")


if __name__ == "__main__":
    main()
