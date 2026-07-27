#!/usr/bin/env python3
"""Draw the ceiling sweep's two charts straight from its JSON report.

Peak memory and render time share one x ladder, one log y, and one rule: a
line stops at the last size that arm actually succeeded on, so where the line
ends *is* the ceiling.

  python benchmarks/plot_ceiling.py ceiling-results.json --out-dir .
  python benchmarks/plot_ceiling.py ceiling-results.json \
      --arms xy-exact,matplotlib,plotly --suffix=-exact

Charts are drawn with xy itself, so a regression in the engine shows up in
the benchmark's own output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import xy

GIB = 2**30

# Default ladder: 10 anchors the fixed-overhead floor, the rest is the
# published sweep.  10k is measured but omitted here so the requested ten
# buckets stay legible on a categorical axis.
DEFAULT_SIZES = [
    10,
    100_000,
    500_000,
    1_000_000,
    2_500_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
]

STYLE: dict[str, dict[str, Any]] = {
    "xy": {"name": "XY (density, default)", "color": "#6E56CF", "width": 3.0},
    "xy-exact": {"name": "XY (density off)", "color": "#A594E8", "width": 2.5},
    "plotly": {"name": "Plotly scattergl", "color": "#B9BBC6", "width": 2.0},
    "matplotlib": {"name": "Matplotlib WebAgg", "color": "#8B8D98", "width": 2.0},
    "datashader": {"name": "Datashader (static image)", "color": "#7FB3A6", "width": 2.0},
    "plotly-resampler": {"name": "Plotly-Resampler", "color": "#C9A227", "width": 2.0},
}


def label(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def series(
    rows: dict[tuple[str, int], dict[str, Any]], arm: str, sizes: list[int], metric: str
) -> tuple[list[str], list[float]]:
    """Values up to the arm's ceiling; the break is the point of the chart."""
    labels: list[str] = []
    values: list[float] = []
    for n in sizes:
        row = rows.get((arm, n))
        if not row or row.get("status") != "ok":
            break
        if metric == "memory":
            value = (
                int(row.get("python_peak_rss_bytes") or 0)
                + int(row.get("browser_peak_rss_bytes") or 0)
            ) / GIB
        else:
            # ttfr_ms for browser arms; the no-browser arms record only the
            # build that produces their raster.
            ms = row.get("ttfr_ms") or row.get("build_only_ms")
            if ms is None:
                break
            value = float(ms) / 1000.0
        labels.append(label(n))
        values.append(round(value, 4))
    return labels, values


def build_chart(
    rows: dict[tuple[str, int], dict[str, Any]],
    arms: list[str],
    sizes: list[int],
    metric: str,
    *,
    width: int,
    height: int,
) -> xy.Chart | None:
    marks: list[Any] = []
    ends: list[Any] = []
    notes: list[Any] = []
    top = 0.0
    for arm in arms:
        style = STYLE.get(arm, {"name": arm, "color": "#8B8D98", "width": 2.0})
        labels, values = series(rows, arm, sizes, metric)
        if not values:
            continue
        top = max(top, max(values))
        marks.append(
            xy.line(labels, values, name=style["name"], color=style["color"], width=style["width"])
        )
        ends.append(xy.marker(labels[-1], values[-1], size=7, color=style["color"]))
        unit = "GiB" if metric == "memory" else "s"
        text = f"{values[-1]:.2f} {unit}"
        # An arm that stopped short of the ladder end died; say so on the chart
        # rather than leaving a line that just trails off.
        if labels[-1] != label(sizes[-1]):
            text = f"× {text} — fails at {label(sizes[len(values)])}"  # noqa: RUF001
        notes.append(
            xy.text(
                labels[-1],
                values[-1],
                text,
                dx=-8,
                dy=-10,
                color=style["color"],
                anchor="end",
            )
        )
    if not marks:
        return None

    if metric == "memory":
        axis_label = "Peak process-tree RSS (GiB)"
        ticks = [t for t in (0.25, 0.5, 1, 2, 4, 8, 16, 32) if t <= top * 2.2]
        tick_labels = [f"{t:g}" for t in ticks]
        tick_labels[-1] = f"{ticks[-1]:g} GiB"
        # Every browser arm pays a headless-Chrome baseline before it draws
        # anything; without this line the low-N rows look like a real result.
        notes.append(xy.hline(1.0, color="#8B8D98", opacity=0.3, width=1.5))
        notes.append(
            xy.text(
                label(sizes[1]),
                0.70,
                "headless Chrome floor (~1 GiB) — every browser arm starts here",
                color="#8B8D98",
                anchor="start",
            )
        )
        domain = (0.15, max(2.0, top * 1.5))
    else:
        axis_label = "Time until every point is on screen (seconds)"
        ticks = [t for t in (0.125, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64) if t <= top * 2.2]
        tick_labels = [f"{t:g}" for t in ticks]
        tick_labels[-1] = f"{ticks[-1]:g} s"
        notes.append(xy.hline(1.0, color="#8B8D98", opacity=0.3, width=1.5))
        notes.append(xy.text(label(sizes[2]), 1.16, "1 second", color="#8B8D98", anchor="start"))
        domain = (0.1, max(2.0, top * 1.6))

    return xy.line_chart(
        *marks,
        *ends,
        *notes,
        xy.legend(show=True, loc="upper left"),
        xy.modebar(show=False),
        xy.tooltip(format={"y": ".3f"}),
        xy.x_axis(label="Points plotted", tick_label_anchor="center"),
        xy.y_axis(
            label=axis_label,
            type_="log",
            domain=domain,
            tick_values=ticks,
            tick_labels=tick_labels,
            style={"grid_width": 1, "grid_opacity": 1},
        ),
        width=width,
        height=height,
        padding=(24, 30, 52, 96),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    parser.add_argument("--arms", default="", help="comma-separated subset; default is all")
    parser.add_argument("--sizes", default="", help="comma-separated subset of the ladder")
    parser.add_argument("--suffix", default="", help="appended to output filenames")
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=520)
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()

    report = json.loads(args.report.read_text())
    rows = {(r["arm"], r["n"]): r for r in report["results"]}
    measured = report["method"]["sizes"]
    sizes = (
        [int(v) for v in args.sizes.split(",") if v.strip()]
        if args.sizes
        else [n for n in DEFAULT_SIZES if n in measured]
    )
    arms = (
        [a.strip() for a in args.arms.split(",") if a.strip()]
        if args.arms
        else list(report["method"]["arms"])
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for metric in ("memory", "time"):
        chart = build_chart(rows, arms, sizes, metric, width=args.width, height=args.height)
        if chart is None:
            print(f"{metric}: no successful rows for {arms}")
            continue
        path = args.out_dir / f"ceiling-{metric}{args.suffix}.png"
        chart.to_png(str(path), scale=args.scale)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
