"""Many-chart dashboard benchmark for fastcharts.

Single-chart performance does not predict dashboard performance: pages can fail
because the total JS/data payload is too heavy or because too many canvases
fight for startup work. This harness renders a mixed dashboard in one page and
records total chart-to-pixels time from inside headless Chromium.

Usage:
  PYTHONPATH=python .venv/bin/python benchmarks/bench_dashboard.py --chart-counts 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fastcharts_browser import (  # noqa: E402
    chart_payload,
    json_bytes,
    page_for_charts,
    run_json_probe,
)
from categories import BENCHMARK_CATEGORIES, categories_for, markdown_category_table  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

DASHBOARD_CATEGORY_IDS = (
    "many_chart_dashboards",
    "small_data_startup",
    "payload_export_size",
)
RENDER_W, RENDER_H = 420, 280


def _parse_counts(text: str) -> list[int]:
    return [int(float(part)) for part in text.split(",") if part.strip()]


def _dashboard_figures(count: int) -> list[Any]:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_dashboard.py")
    from fastcharts import Figure

    rng = np.random.default_rng(91_337)
    figures: list[Any] = []
    for i in range(count):
        kind = i % 5
        if kind == 0:
            n = 50_000
            x = np.arange(n, dtype=np.float64)
            y = np.cumsum(rng.normal(0.0, 0.05, n)).astype(np.float64, copy=False)
            figures.append(
                Figure(width=RENDER_W, height=RENDER_H, title=f"Line {i + 1}").line(
                    x, y, name="signal"
                )
            )
        elif kind == 1:
            n = 80_000
            x = rng.normal(0.0, 1.0, n).astype(np.float64, copy=False)
            y = (0.45 * x + rng.normal(0.0, 0.8, n)).astype(np.float64, copy=False)
            figures.append(
                Figure(width=RENDER_W, height=RENDER_H, title=f"Scatter {i + 1}").scatter(
                    x, y, name="points", opacity=0.65
                )
            )
        elif kind == 2:
            values = np.concatenate(
                [
                    rng.normal(-1.2, 0.45, 35_000),
                    rng.normal(1.1, 0.7, 35_000),
                ]
            ).astype(np.float64, copy=False)
            figures.append(
                Figure(width=RENDER_W, height=RENDER_H, title=f"Histogram {i + 1}").hist(
                    values, bins=160, name="distribution"
                )
            )
        elif kind == 3:
            labels = np.array([f"C{j:02d}" for j in range(36)], dtype=object)
            values = rng.random((3, len(labels))) * 100
            figures.append(
                Figure(width=RENDER_W, height=RENDER_H, title=f"Bars {i + 1}").bar(
                    labels,
                    values,
                    mode="grouped",
                    series=["A", "B", "C"],
                )
            )
        else:
            xs = np.linspace(-2.5, 2.5, 80)
            ys = np.linspace(-2.0, 2.0, 70)
            z = (
                np.sin(xs)[None, :]
                + np.cos(ys)[:, None]
                + rng.normal(0.0, 0.06, (len(ys), len(xs)))
            )
            figures.append(
                Figure(width=RENDER_W, height=RENDER_H, title=f"Heatmap {i + 1}").heatmap(
                    z, colormap="turbo"
                )
            )
    return figures


def _probe_js() -> str:
    return """
(async () => {
  try {
    const root = document.getElementById("root");
    const views = [];
    const heapBefore = performance.memory ? performance.memory.usedJSHeapSize : null;
    const t0 = performance.now();
    for (const payload of FC_CHARTS) {
      const cell = document.createElement("div");
      cell.className = "chart-cell";
      root.appendChild(cell);
      const view = fastcharts.renderStandalone(cell, payload.spec, fcBytesFromB64(payload.b64));
      view._drawNow();
      views.push(view);
    }
    await fcRaf();
    let nonblank = 0;
    for (const view of views) {
      if (fcNonblankPixels(view) > 0) nonblank++;
    }
    if (nonblank !== views.length) {
      throw new Error(`blank dashboard chart: ${nonblank}/${views.length} nonblank`);
    }
    const renderMs = performance.now() - t0;
    const navigationReadyMs = performance.now();
    const steadyRedraws = [];
    for (let i = 0; i < 12; i++) {
      const redrawStart = performance.now();
      for (const view of views) view._drawNow();
      steadyRedraws.push(performance.now() - redrawStart);
    }
    const heapAfter = performance.memory ? performance.memory.usedJSHeapSize : null;
    fcReport("FC_DASHBOARD", {
      status: "ok",
      render_ms: renderMs,
      navigation_ready_ms: navigationReadyMs,
      steady_redraw_p95_ms: fcPercentile(steadyRedraws, 95),
      js_heap_before_bytes: heapBefore,
      js_heap_bytes: heapAfter,
      js_heap_delta_bytes: heapBefore == null || heapAfter == null ? null : heapAfter - heapBefore,
      nonblank_charts: nonblank,
    });
  } catch (err) {
    fcFail("FC_DASHBOARD", err);
  }
})();
"""


def run(*, chart_counts: list[int], chromium: str | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for count in chart_counts:
        prep_start = time.perf_counter()
        figures = _dashboard_figures(count)
        payloads = []
        total_payload_bytes = 0
        for i, fig in enumerate(figures):
            spec, blob = fig.build_payload()
            total_payload_bytes += json_bytes(spec) + len(blob)
            payloads.append(chart_payload(f"chart-{i}", spec, blob))
        payload_prep_ms = (time.perf_counter() - prep_start) * 1e3
        html = page_for_charts(
            payloads,
            _probe_js(),
            title="fastcharts dashboard probe",
            body_css=(
                "html,body{margin:0;background:#fff;font-family:system-ui,sans-serif;}"
                "#root{display:grid;grid-template-columns:repeat(4,420px);gap:12px;padding:12px;}"
                ".chart-cell{width:420px;height:280px;border:1px solid #dde3ec;}"
            ),
        )
        result = run_json_probe(html, marker="FC_DASHBOARD", chromium=chromium)
        row: dict[str, Any] = {
            "scenario": f"dashboard_{count}",
            "chart_count": count,
            "benchmark_categories": [
                category["id"] for category in categories_for(DASHBOARD_CATEGORY_IDS)
            ],
            "total_payload_bytes": total_payload_bytes,
            "html_bytes": len(html.encode("utf-8")),
            "payload_prep_ms": payload_prep_ms,
            "status": result.get("status", "failed(no status)"),
        }
        if row["status"] == "ok":
            row["render_ms"] = result.get("render_ms")
            row["ms_per_chart"] = (
                result.get("render_ms") / count if result.get("render_ms") is not None else None
            )
            row["nonblank_charts"] = result.get("nonblank_charts")
            row["navigation_ready_ms"] = result.get("navigation_ready_ms")
            row["steady_redraw_p95_ms"] = result.get("steady_redraw_p95_ms")
            row["js_heap_before_bytes"] = result.get("js_heap_before_bytes")
            row["js_heap_bytes"] = result.get("js_heap_bytes")
            row["js_heap_delta_bytes"] = result.get("js_heap_delta_bytes")
        rows.append(row)

    successful_counts = [
        row["chart_count"] for row in rows if str(row.get("status", "")).startswith("ok")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dashboard-browser",
        "environment": collect_environment_metadata(chromium=chromium),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(DASHBOARD_CATEGORY_IDS),
        "attempted_chart_counts": list(chart_counts),
        "chart_count_ceiling": max(successful_counts) if successful_counts else None,
        "rows": rows,
    }


def _fmt_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _fmt_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    n = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# fastcharts many-chart dashboard benchmark",
        "",
        "## Benchmark Categories",
        "",
        *markdown_category_table(report.get("benchmark_categories", BENCHMARK_CATEGORIES)),
        "",
        "Tracked in this run: "
        + ", ".join(f"`{category['id']}`" for category in report["tracked_categories"]),
        "",
        f"Successful nonblank chart-count ceiling: `{report.get('chart_count_ceiling')}`.",
        "",
        "## Results",
        "",
        "| scenario | charts | prep | navigation ready | render | redraw p95 | JS heap | payload | html | nonblank charts | status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {scenario} | {count} | {prep} | {navigation} | {render} | {idle} | {heap} | {payload} | {html} | {nonblank} | {status} |".format(
                scenario=row["scenario"],
                count=row["chart_count"],
                prep=_fmt_ms(row.get("payload_prep_ms")),
                navigation=_fmt_ms(row.get("navigation_ready_ms")),
                render=_fmt_ms(row.get("render_ms")),
                idle=_fmt_ms(row.get("steady_redraw_p95_ms")),
                heap=_fmt_bytes(row.get("js_heap_bytes")),
                payload=_fmt_bytes(row.get("total_payload_bytes")),
                html=_fmt_bytes(row.get("html_bytes")),
                nonblank=row.get("nonblank_charts", "—"),
                status=row.get("status", "unknown"),
            )
        )
    lines += [
        "",
        "Notes:",
        "",
        "- `render` is measured inside the page from first chart decode to post-RAF WebGL readback.",
        "- The chart mix cycles through line, scatter, histogram, grouped bar, and heatmap.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chart-counts", default="10,20,50")
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--out", default=None, help="write Markdown report here")
    parser.add_argument("--json", default=None, help="write JSON report here")
    args = parser.parse_args()

    report = run(chart_counts=_parse_counts(args.chart_counts), chromium=args.chromium)
    md = to_markdown(report)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
