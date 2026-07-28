#!/usr/bin/env python3
"""Draw the UX ladder's charts straight from a suite directory.

Two charts, same x ladder, log y, one rule: a line stops at the last size
that arm actually rendered, so where the line ends is that library's ceiling.

    python benchmarks/plot_ux.py /Users/alek/Desktop/xy-ux-suite --out-dir .

Drawn with xy itself, so an engine regression shows up in the benchmark's
own output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import xy

GIB = 2**30

STYLE: dict[str, dict[str, Any]] = {
    "xy": {"name": "XY (density, default)", "color": "#6E56CF", "width": 3.0},
    "xy-exact": {"name": "XY (density off)", "color": "#A594E8", "width": 2.5},
    "plotly": {"name": "Plotly scattergl", "color": "#B9BBC6", "width": 2.0},
    "matplotlib": {"name": "Matplotlib WebAgg", "color": "#8B8D98", "width": 2.0},
    "datashader": {"name": "Datashader (Bokeh server)", "color": "#7FB3A6", "width": 2.0},
}
ORDER = ("xy", "xy-exact", "plotly", "matplotlib", "datashader")


def label(n: int) -> str:
    return f"{n / 1_000_000:g}M" if n >= 1_000_000 else f"{n // 1000}k"


def series(
    rows: dict[tuple[str, int], dict[str, Any]], arm: str, sizes: list[int], metric: str
) -> tuple[list[float], list[float], str | None]:
    """Values up to the arm's ceiling, plus why it stopped.

    x is the row count itself, plotted on a log axis — not an evenly-spaced
    category.  The ladder is not uniform in log space (10k->100k is a decade,
    500k->1M is a third of one), so categorical spacing would distort every
    slope, and slope is what a scaling chart exists to show.
    """
    xs: list[float] = []
    values: list[float] = []
    for n in sizes:
        row = rows.get((arm, n))
        if row is None or row.get("status") != "ok":
            # A size that was never measured is not the same as one that
            # failed, but both stop the line -- so both must be labelled,
            # never left to trail off as though the ladder simply ended.
            return xs, values, (row or {}).get("status") or "not measured"
        if metric == "time":
            value = float(row["visible_complete_ms"]) / 1000.0
        else:
            value = int(row["python_peak_rss_bytes"]) / GIB
        xs.append(float(n))
        values.append(round(value, 4))
    return xs, values, None


def build(
    rows: dict[tuple[str, int], dict[str, Any]],
    sizes: list[int],
    arms: list[str],
    metric: str,
) -> xy.Chart:
    marks: list[Any] = []
    notes: list[Any] = []
    for arm in arms:
        style = STYLE[arm]
        labels, values, stopped = series(rows, arm, sizes, metric)
        if not values:
            continue
        marks.append(
            xy.line(labels, values, name=style["name"], color=style["color"], width=style["width"])
        )
        # Every measured cell is a visible dot: the reader can see exactly
        # which sizes were run rather than inferring them from line bends.
        marks.append(xy.scatter(x=labels, y=values, color=style["color"], size=6.5))
        unit = "s" if metric == "time" else " GiB"
        text = f"{values[-1]:.2f}{unit}"
        notes.append(xy.marker(labels[-1], values[-1], size=6, color=style["color"]))
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
        if stopped:
            # The failure lives at the size that caused it: a dashed
            # horizontal run from the last measurement out to the failing x,
            # ending in a red cross AT that size, so "fails at 50M" sits on
            # 50M rather than on the survivor next to it.
            fail_n = float(sizes[len(values)])
            notes.append(
                xy.line(
                    [labels[-1], fail_n],
                    [values[-1], values[-1]],
                    color="#D64545",
                    width=1.5,
                    dash="dashed",
                    opacity=0.6,
                )
            )
            notes.append(xy.marker(fail_n, values[-1], size=10, symbol="cross", color="#D64545"))
            at_edge = fail_n >= float(sizes[-1])
            # In the empty space past the cross, or -- when the cross sits at
            # the chart edge -- centered under the dashed segment, which is
            # the one region guaranteed free of survivor lines and labels.
            mid = (labels[-1] * fail_n) ** 0.5
            notes.append(
                xy.text(
                    mid if at_edge else fail_n,
                    values[-1],
                    f"fails at {label(int(fail_n))}",
                    dx=10 if at_edge else 12,
                    dy=18 if at_edge else 4,
                    color="#D64545",
                    anchor="middle" if at_edge else "start",
                )
            )

    # Linear y: the point of these charts is the *size* of the gap, and a log
    # axis compresses a 165x difference into a couple of gridlines.  Fixed
    # domains, never derived from the data, so two versions of the same chart
    # stay visually comparable.  x stays log — the ladder spans four decades
    # and a linear x would pile everything below 10M against the left edge.
    if metric == "time":
        axis = "Time to render (s)"
        ticks = [0, 2, 4, 6, 8, 10, 12, 14]
        labels_y = [f"{t:g}" for t in ticks]
        labels_y[-1] = f"{ticks[-1]:g} s"
        domain = (0.0, 14.6)
    else:
        axis = "Peak memory (GiB)"
        ticks = [0, 1, 2, 3, 4, 5]
        labels_y = [f"{t:g}" for t in ticks]
        labels_y[-1] = f"{ticks[-1]:g} GiB"
        domain = (0.0, 5.8)

    decades = [1e4, 1e5, 1e6, 1e7, 1e8]
    return xy.line_chart(
        *marks,
        *notes,
        xy.legend(show=True, loc="upper left"),
        xy.modebar(show=False),
        xy.tooltip(format={"y": ".3f"}),
        xy.x_axis(
            label="Points plotted",
            type_="log",
            domain=(8e3, 1.25e8),
            tick_values=decades,
            tick_labels=["10k", "100k", "1M", "10M", "100M"],
            style={"grid_width": 1, "grid_opacity": 1},
        ),
        xy.y_axis(
            label=axis,
            domain=domain,
            tick_values=ticks,
            tick_labels=labels_y,
            style={"grid_width": 1, "grid_opacity": 1},
        ),
        width=1000,
        height=520,
        padding=(24, 30, 52, 92),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    parser.add_argument("--arms", default="", help="comma-separated subset")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()

    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted(args.suite_dir.glob("ux-*.json")):
        for row in json.loads(path.read_text()).get("results", []):
            rows[(row["arm"], row["n"])] = row
    if not rows:
        parser.error(f"no ux-*.json under {args.suite_dir}")

    sizes = sorted({n for _, n in rows})
    wanted = [a.strip() for a in args.arms.split(",") if a.strip()] or list(ORDER)
    arms = [a for a in ORDER if a in wanted and any(a == arm for arm, _ in rows)]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for metric, stem in (("time", "render-time"), ("memory", "python-memory")):
        chart = build(rows, sizes, arms, metric)
        path = args.out_dir / f"ux-{stem}{args.suffix}.png"
        chart.to_png(str(path), scale=args.scale)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
