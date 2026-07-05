"""Core 2D chart benchmark: fastcharts vs Plotly.

This benchmark covers the regular 2D chart families added after the original
scatter/line wedge: histogram, area, bar variants, and heatmap. It measures the
cost a Python charting library pays before a browser can render:

  build_s        construct the figure object from already-generated arrays
  payload_s      serialize/prepare the chart payload (fastcharts binary
                 spec+blob; Plotly JSON figure)
  total_s        build + payload
  payload_bytes  chart data/spec bytes, excluding the JS runtime bundle
  html_bytes     standalone HTML bytes used for optional TTFR probing
  ttfr_ms        optional data→first-paint estimate in headless Chromium

Data generation is excluded from timings. Plotly is the only comparison here on
purpose: this harness answers "are the new fastcharts APIs up to par against the
dominant Python interactive plotting library?" The broader scatter benchmark in
`bench_vs.py` still covers matplotlib, Bokeh, Altair, Datashader, and friends.

Usage:
  PYTHONPATH=python .venv/bin/python benchmarks/bench_2d_charts.py --profile smoke --ttfr
  PYTHONPATH=python .venv/bin/python benchmarks/bench_2d_charts.py --profile standard
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _browser import first_paint_ms  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for, markdown_category_table  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

try:
    import psutil  # type: ignore

    _PROC = psutil.Process()
except Exception:
    _PROC = None

RENDER_W, RENDER_H = 900, 420
PROFILE_NAMES = ("smoke", "standard", "stress")
BENCH_2D_CATEGORY_IDS = (
    "core_2d_chart_breadth",
    "payload_export_size",
    "small_data_startup",
)


@dataclass(frozen=True)
class Case:
    family: str
    label: str
    work_units: int
    unit: str
    fastcharts_build: Callable[[], Any]
    plotly_build: Callable[[], Any] | None


def _rss_mb() -> float | None:
    if _PROC is None:
        return None
    return _PROC.memory_info().rss / 2**20


def _json_bytes(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8"))


def _measure(
    library: str,
    build: Callable[[], Any],
    payload: Callable[[Any], int],
    artifact: Callable[[Any], str],
    *,
    ttfr: bool,
    chromium: str | None,
) -> dict[str, Any]:
    gc.collect()
    tracemalloc.start()
    rss0 = _rss_mb()
    t0 = time.perf_counter()
    fig = build()
    t1 = time.perf_counter()
    payload_bytes = payload(fig)
    t2 = time.perf_counter()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss1 = _rss_mb()

    row = {
        "library": library,
        "build_s": t1 - t0,
        "payload_s": t2 - t1,
        "total_s": t2 - t0,
        "payload_bytes": payload_bytes,
        "peak_mem_mb": peak / 2**20,
        "rss_delta_mb": (rss1 - rss0) if (rss0 is not None and rss1 is not None) else None,
        "status": "ok",
    }

    try:
        html = artifact(fig)
        row["html_bytes"] = len(html.encode("utf-8"))
    except Exception as e:
        html = None
        row["artifact_status"] = f"failed({type(e).__name__}: {str(e)[:100]})"
        row["html_bytes"] = None

    if ttfr and html:
        paint_ms = first_paint_ms(html, chromium=chromium)
        row["browser_paint_ms"] = paint_ms
        row["ttfr_ms"] = row["total_s"] * 1e3 + paint_ms if paint_ms is not None else None

    del fig
    gc.collect()
    return row


def _fastcharts_payload(fig: Any) -> int:
    spec, blob = fig.build_payload()
    return _json_bytes(spec) + len(blob)


def _fastcharts_artifact(fig: Any) -> str:
    return fig.to_html()


def _plotly_payload(fig: Any) -> int:
    return len(fig.to_json().encode("utf-8"))


def _plotly_artifact(fig: Any) -> str:
    return fig.to_html(
        include_plotlyjs=True,
        full_html=True,
        config={"displaylogo": False, "responsive": False},
    )


def _plotly_or_none() -> Any | None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None
    return go


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{seconds * 1e3:.0f} ms"
    return f"{seconds:.2f} s"


def _fmt_ms(ms: float | None) -> str:
    return "—" if ms is None else f"{ms:.0f} ms"


def _fmt_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    n = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_ratio(value: float | None, suffix: str = "x") -> str:
    if value is None:
        return "—"
    if value >= 100:
        return f"{value:.0f}{suffix}"
    if value >= 10:
        return f"{value:.1f}{suffix}"
    return f"{value:.2f}{suffix}"


def _verdict(fc: dict[str, Any] | None, plotly: dict[str, Any] | None) -> str:
    if not fc or fc.get("status") != "ok":
        return "fail"
    if not plotly or plotly.get("status") != "ok":
        return "no-plotly"
    if fc.get("ttfr_ms") is not None and plotly.get("ttfr_ms") is not None:
        checks = [
            fc["ttfr_ms"] <= plotly["ttfr_ms"] * 1.10,
            fc["payload_bytes"] <= plotly["payload_bytes"] * 1.10,
        ]
        return "pass" if all(checks) else "watch"
    checks = [
        fc["total_s"] <= plotly["total_s"] * 1.10,
        fc["payload_bytes"] <= plotly["payload_bytes"] * 1.10,
    ]
    return "pass" if all(checks) else "watch"


def make_cases(profile: str) -> list[Case]:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_2d_charts.py")
    if profile not in PROFILE_NAMES:
        raise ValueError(f"profile must be one of {PROFILE_NAMES}, got {profile!r}")

    go = _plotly_or_none()
    from fastcharts import Figure

    rng = np.random.default_rng(42)
    cases: list[Case] = []

    def add_histogram(n: int, bins: int = 200) -> None:
        values = np.concatenate(
            [
                rng.normal(-1.3, 0.55, n // 2),
                rng.normal(1.2, 0.85, n - n // 2),
            ]
        ).astype(np.float64, copy=False)

        def fc():
            return Figure(width=RENDER_W, height=RENDER_H).hist(values, bins=bins)

        def pl():
            fig = go.Figure(go.Histogram(x=values, nbinsx=bins, marker_color="#2563eb"))
            fig.update_layout(width=RENDER_W, height=RENDER_H, template="plotly_white")
            return fig

        cases.append(
            Case("histogram", f"{n:,} values / {bins} bins", n, "values", fc, pl if go else None)
        )

    def add_area(n: int) -> None:
        x = np.arange(n, dtype=np.float64)
        y = 30 + np.sin(np.linspace(0, 32, n)) * 9 + np.cumsum(rng.normal(0, 0.025, n))

        def fc():
            return Figure(width=RENDER_W, height=RENDER_H).area(x, y, color="#0891b2")

        def pl():
            fig = go.Figure(
                go.Scatter(x=x, y=y, mode="lines", fill="tozeroy", line={"color": "#0891b2"})
            )
            fig.update_layout(width=RENDER_W, height=RENDER_H, template="plotly_white")
            return fig

        cases.append(Case("area", f"{n:,} samples", n, "samples", fc, pl if go else None))

    def add_bar(n: int) -> None:
        labels = np.array([f"C{i:05d}" for i in range(n)], dtype=object)
        values = (rng.random(n) * 100).astype(np.float64)

        def fc():
            return Figure(width=RENDER_W, height=RENDER_H).bar(labels, values, color="#2563eb")

        def pl():
            fig = go.Figure(go.Bar(x=labels, y=values, marker_color="#2563eb"))
            fig.update_layout(width=RENDER_W, height=RENDER_H, template="plotly_white")
            return fig

        cases.append(Case("bar", f"{n:,} categories", n, "bars", fc, pl if go else None))

    def add_grouped_bar(n: int, series_count: int = 4) -> None:
        labels = np.array([f"G{i:05d}" for i in range(n)], dtype=object)
        values = (rng.random((series_count, n)) * 100).astype(np.float64)
        names = [f"S{i + 1}" for i in range(series_count)]
        colors = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626"][:series_count]

        def fc():
            return Figure(width=RENDER_W, height=RENDER_H).bar(
                labels,
                values,
                mode="grouped",
                series=names,
                colors=colors,
            )

        def pl():
            fig = go.Figure(
                [
                    go.Bar(x=labels, y=values[i], name=names[i], marker_color=colors[i])
                    for i in range(series_count)
                ]
            )
            fig.update_layout(
                width=RENDER_W, height=RENDER_H, template="plotly_white", barmode="group"
            )
            return fig

        cases.append(
            Case(
                "grouped_bar",
                f"{n:,} categories x {series_count}",
                n * series_count,
                "bars",
                fc,
                pl if go else None,
            )
        )

    def add_stacked_bar(n: int, series_count: int = 4) -> None:
        labels = np.array([f"K{i:05d}" for i in range(n)], dtype=object)
        values = (rng.random((series_count, n)) * 100).astype(np.float64)
        names = [f"S{i + 1}" for i in range(series_count)]
        colors = ["#0f766e", "#7c3aed", "#dc2626", "#0891b2"][:series_count]

        def fc():
            return Figure(width=RENDER_W, height=RENDER_H).column(
                labels,
                values,
                mode="stacked",
                series=names,
                colors=colors,
            )

        def pl():
            fig = go.Figure(
                [
                    go.Bar(x=labels, y=values[i], name=names[i], marker_color=colors[i])
                    for i in range(series_count)
                ]
            )
            fig.update_layout(
                width=RENDER_W, height=RENDER_H, template="plotly_white", barmode="stack"
            )
            return fig

        cases.append(
            Case(
                "stacked_bar",
                f"{n:,} categories x {series_count}",
                n * series_count,
                "bars",
                fc,
                pl if go else None,
            )
        )

    def add_heatmap(rows: int, cols: int) -> None:
        x = np.array([f"D{i:03d}" for i in range(cols)], dtype=object)
        y = np.array([f"H{i:03d}" for i in range(rows)], dtype=object)
        xx = np.linspace(-2.5, 2.5, cols)
        yy = np.linspace(-2.0, 2.0, rows)
        z = (np.sin(xx)[None, :] + np.cos(yy)[:, None] + rng.normal(0, 0.08, (rows, cols))).astype(
            np.float64
        )

        def fc():
            return Figure(width=RENDER_W, height=RENDER_H).heatmap(z, x=x, y=y, colormap="turbo")

        def pl():
            fig = go.Figure(go.Heatmap(z=z, x=x, y=y, colorscale="Turbo"))
            fig.update_layout(width=RENDER_W, height=RENDER_H, template="plotly_white")
            return fig

        cells = rows * cols
        cases.append(
            Case("heatmap", f"{rows:,} x {cols:,} cells", cells, "cells", fc, pl if go else None)
        )

    if profile == "smoke":
        add_histogram(100_000)
        add_area(100_000)
        add_bar(1_000)
        add_grouped_bar(1_000)
        add_stacked_bar(1_000)
        add_heatmap(120, 120)
    elif profile == "standard":
        for n in (10_000, 100_000, 1_000_000):
            add_histogram(n)
            add_area(n)
        for n in (100, 1_000, 10_000):
            add_bar(n)
        for n in (100, 1_000):
            add_grouped_bar(n)
            add_stacked_bar(n)
        for shape in ((50, 50), (200, 200), (500, 500)):
            add_heatmap(*shape)
    else:
        for n in (100_000, 1_000_000, 5_000_000):
            add_histogram(n)
            add_area(n)
        for n in (1_000, 10_000, 50_000):
            add_bar(n)
        for n in (1_000, 10_000):
            add_grouped_bar(n)
            add_stacked_bar(n)
        for shape in ((200, 200), (500, 500), (1_000, 1_000)):
            add_heatmap(*shape)
    return cases


def run(
    *,
    profile: str,
    ttfr: bool,
    ttfr_max_work_units: int,
    chromium: str | None = None,
) -> dict[str, Any]:
    cases = make_cases(profile)
    rows: list[dict[str, Any]] = []
    for case in cases:
        for library, build in (
            ("fastcharts", case.fastcharts_build),
            ("plotly", case.plotly_build),
        ):
            row: dict[str, Any] = {
                "family": case.family,
                "case": case.label,
                "work_units": case.work_units,
                "unit": case.unit,
                "library": library,
            }
            if build is None:
                row["status"] = "unavailable"
                rows.append(row)
                continue
            should_ttfr = ttfr and case.work_units <= ttfr_max_work_units
            try:
                row.update(
                    _measure(
                        library,
                        build,
                        _fastcharts_payload if library == "fastcharts" else _plotly_payload,
                        _fastcharts_artifact if library == "fastcharts" else _plotly_artifact,
                        ttfr=should_ttfr,
                        chromium=chromium,
                    )
                )
            except Exception as e:
                row["status"] = f"failed({type(e).__name__}: {str(e)[:160]})"
            if row.get("total_s"):
                row["units_per_s"] = case.work_units / row["total_s"]
            rows.append(row)

    comparisons = []
    for case in cases:
        fc = _find_row(rows, case, "fastcharts")
        pl = _find_row(rows, case, "plotly")
        comp = {
            "family": case.family,
            "case": case.label,
            "work_units": case.work_units,
            "unit": case.unit,
            "verdict": _verdict(fc, pl),
        }
        if fc and pl and fc.get("status") == "ok" and pl.get("status") == "ok":
            comp["speedup"] = pl["total_s"] / fc["total_s"] if fc["total_s"] else None
            comp["payload_reduction"] = (
                pl["payload_bytes"] / fc["payload_bytes"] if fc["payload_bytes"] else None
            )
            if fc.get("ttfr_ms") is not None and pl.get("ttfr_ms") is not None:
                comp["ttfr_speedup"] = pl["ttfr_ms"] / fc["ttfr_ms"] if fc["ttfr_ms"] else None
        comparisons.append(comp)

    return {
        "schema_version": SCHEMA_VERSION,
        "environment": collect_environment_metadata(chromium=chromium),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(BENCH_2D_CATEGORY_IDS),
        "profile": profile,
        "ttfr": ttfr,
        "ttfr_max_work_units": ttfr_max_work_units,
        "rows": rows,
        "comparisons": comparisons,
    }


def _find_row(rows: list[dict[str, Any]], case: Case, library: str) -> dict[str, Any] | None:
    for row in rows:
        if row["family"] == case.family and row["case"] == case.label and row["library"] == library:
            return row
    return None


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Core 2D chart benchmark: fastcharts vs Plotly",
        "",
        f"Profile: `{report['profile']}`. TTFR: `{report['ttfr']}` "
        f"(cap: {report['ttfr_max_work_units']:,} work units).",
        "",
    ]
    environment = report.get("environment") or {}
    if environment:
        platform_info = environment.get("platform") or {}
        python_info = environment.get("python") or {}
        git_info = environment.get("git") or {}
        lines += [
            "## Run Environment",
            "",
            f"- generated: `{environment.get('generated_at_utc', 'unknown')}`",
            f"- python: `{python_info.get('version', 'unknown')}` "
            f"({python_info.get('implementation', 'unknown')})",
            f"- platform: `{platform_info.get('system', 'unknown')} "
            f"{platform_info.get('machine', 'unknown')}`",
            f"- git: `{git_info.get('commit', 'unknown')}` (dirty: `{git_info.get('dirty')}`)",
            "",
        ]
    try:
        import fastcharts.kernels as kernels

        lines += [f"fastcharts backend: `{kernels.BACKEND}`", ""]
    except Exception:
        pass

    lines += [
        "## Benchmark Categories",
        "",
        *markdown_category_table(report.get("benchmark_categories", BENCHMARK_CATEGORIES)),
        "",
        "Tracked in this run: "
        + ", ".join(f"`{category['id']}`" for category in report["tracked_categories"]),
        "",
        "## Summary",
        "",
        "| family | case | speedup | payload reduction | TTFR speedup | verdict |",
        "|---|---|---:|---:|---:|---|",
    ]
    for comp in report["comparisons"]:
        lines.append(
            "| {family} | {case} | {speedup} | {payload} | {ttfr} | {verdict} |".format(
                family=comp["family"],
                case=comp["case"],
                speedup=_fmt_ratio(comp.get("speedup")),
                payload=_fmt_ratio(comp.get("payload_reduction")),
                ttfr=_fmt_ratio(comp.get("ttfr_speedup")),
                verdict=comp["verdict"],
            )
        )

    lines += [
        "",
        "## Raw Rows",
        "",
        "| family | case | library | total | build | payload | payload bytes | html bytes | TTFR | peak mem | units/s | status |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        if row.get("status") != "ok":
            lines.append(
                f"| {row['family']} | {row['case']} | {row['library']} | | | | | | | | | {row.get('status', '?')} |"
            )
            continue
        lines.append(
            "| {family} | {case} | {library} | {total} | {build} | {payload} | {payload_bytes} | "
            "{html_bytes} | {ttfr} | {mem:.0f} MB | {units:,.0f} | ok |".format(
                family=row["family"],
                case=row["case"],
                library=row["library"],
                total=_fmt_time(row["total_s"]),
                build=_fmt_time(row["build_s"]),
                payload=_fmt_time(row["payload_s"]),
                payload_bytes=_fmt_bytes(row["payload_bytes"]),
                html_bytes=_fmt_bytes(row.get("html_bytes")),
                ttfr=_fmt_ms(row.get("ttfr_ms")),
                mem=row["peak_mem_mb"],
                units=row.get("units_per_s") or 0,
            )
        )
    lines += [
        "",
        "Notes:",
        "",
        "- `payload bytes` excludes the JavaScript runtime bundle: fastcharts reports spec JSON + binary blob; Plotly reports figure JSON.",
        "- `html bytes` is the standalone HTML used by the optional TTFR browser probe, with JavaScript inlined for both libraries.",
        "- Histogram compares the public chart APIs: fastcharts bins in Python before shipping rectangles; Plotly `Histogram` ships raw values for plotly.js to bin.",
        "- When TTFR is measured, the verdict is based on user-visible first paint plus payload size; raw payload-prep time remains visible for backend-kernel regressions.",
        "- Without TTFR, a `watch` verdict means Plotly matched or beat fastcharts on total payload-prep time or payload size.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILE_NAMES, default="standard")
    parser.add_argument(
        "--ttfr", action="store_true", help="run headless-Chromium first-paint probes"
    )
    parser.add_argument(
        "--ttfr-max-work-units",
        type=int,
        default=50_000,
        help="skip browser TTFR above this many values/bars/cells",
    )
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--out", default=None, help="write Markdown report here")
    parser.add_argument("--json", default=None, help="write JSON report here")
    args = parser.parse_args()

    report = run(
        profile=args.profile,
        ttfr=args.ttfr,
        ttfr_max_work_units=args.ttfr_max_work_units,
        chromium=args.chromium,
    )
    md = to_markdown(report)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
