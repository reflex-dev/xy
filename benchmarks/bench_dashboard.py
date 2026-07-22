"""Many-chart dashboard benchmark for xy.

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
from _xy_browser import (  # noqa: E402
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
DASHBOARD_BASE_VIRTUAL_TIME_MS = 15_000
DASHBOARD_SETTLE_VIRTUAL_TIME_MS_PER_CHART = 500
DASHBOARD_PROBE_TIMEOUT_S = 180


def _parse_counts(text: str) -> list[int]:
    return [int(float(part)) for part in text.split(",") if part.strip()]


def _dashboard_figures(count: int) -> list[Any]:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_dashboard.py")
    import xy

    rng = np.random.default_rng(91_337)
    figures: list[Any] = []
    for i in range(count):
        kind = i % 5
        if kind == 0:
            n = 50_000
            x = np.arange(n, dtype=np.float64)
            y = np.cumsum(rng.normal(0.0, 0.05, n)).astype(np.float64, copy=False)
            figures.append(
                xy.chart(
                    xy.line(x=x, y=y, name="signal"),
                    width=RENDER_W,
                    height=RENDER_H,
                    title=f"Line {i + 1}",
                ).figure()
            )
        elif kind == 1:
            n = 80_000
            x = rng.normal(0.0, 1.0, n).astype(np.float64, copy=False)
            y = (0.45 * x + rng.normal(0.0, 0.8, n)).astype(np.float64, copy=False)
            figures.append(
                xy.chart(
                    xy.scatter(x=x, y=y, name="points", opacity=0.65),
                    width=RENDER_W,
                    height=RENDER_H,
                    title=f"Scatter {i + 1}",
                ).figure()
            )
        elif kind == 2:
            values = np.concatenate(
                [
                    rng.normal(-1.2, 0.45, 35_000),
                    rng.normal(1.1, 0.7, 35_000),
                ]
            ).astype(np.float64, copy=False)
            figures.append(
                xy.chart(
                    xy.hist(values, bins=160, name="distribution"),
                    width=RENDER_W,
                    height=RENDER_H,
                    title=f"Histogram {i + 1}",
                ).figure()
            )
        elif kind == 3:
            labels = np.array([f"C{j:02d}" for j in range(36)], dtype=object)
            values = rng.random((3, len(labels))) * 100
            figures.append(
                xy.chart(
                    xy.bar(
                        labels,
                        values,
                        mode="grouped",
                        series=["A", "B", "C"],
                    ),
                    width=RENDER_W,
                    height=RENDER_H,
                    title=f"Bars {i + 1}",
                ).figure()
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
                xy.chart(
                    xy.heatmap(z, colormap="turbo"),
                    width=RENDER_W,
                    height=RENDER_H,
                    title=f"Heatmap {i + 1}",
                ).figure()
            )
    return figures


def _probe_js() -> str:
    return """
(async () => {
  try {
    const root = document.getElementById("root");
    const slots = [];
    const contextEvents = [];
    const creationFailureIds = [];
    let phase = "create";
    const heapBefore = performance.memory ? performance.memory.usedJSHeapSize : null;
    const t0 = performance.now();
    for (const payload of XY_CHARTS) {
      const cell = document.createElement("div");
      cell.className = "chart-cell";
      cell.dataset.chartId = payload.id;
      root.appendChild(cell);
      try {
        const view = xy.renderStandalone(cell, payload.spec, xyBytesFromPayload(payload));
        const state = {lost: false};
        view.root.addEventListener("xy:context_lost", (event) => {
          state.lost = true;
          contextEvents.push({
            id: payload.id, type: "lost", phase, at_ms: performance.now() - t0,
            governed: event.detail?.governed === true,
          });
        });
        view.root.addEventListener("xy:context_restored", () => {
          state.lost = false;
          contextEvents.push({id: payload.id, type: "restored", phase, at_ms: performance.now() - t0});
        });
        view._drawNow();
        slots.push({id: payload.id, cell, view, state});
      } catch (err) {
        creationFailureIds.push(payload.id);
        slots.push({id: payload.id, cell, view: null, state: {lost: true}});
      }
    }
    // webglcontextlost dispatches as a task, so evictions triggered by the
    // creation loop above only fire during this yield — keep phase "create"
    // until they have drained.
    await new Promise((resolve) => setTimeout(resolve, 0));
    phase = "initial";

    function contextLost(slot) {
      if (!slot.view || !slot.view.gl) return true;
      // Use ChartView's live state rather than the probe's event flag. An
      // evicted context can be rebuilt on a fresh canvas without dispatching
      // a second browser event, so an event-only flag would stay stale.
      return slot.view._glLost || slot.view.gl.isContextLost();
    }
    function nonblankPixels(slot) {
      if (contextLost(slot)) return 0;
      try {
        return xyNonblankPixels(slot.view);
      } catch (_err) {
        return 0;
      }
    }
    function sampleNonblank() {
      const lit = [];
      for (const slot of slots) if (nonblankPixels(slot) > 0) lit.push(slot.id);
      return lit;
    }
    function complement(ids) {
      const present = new Set(ids);
      return slots.filter((slot) => !present.has(slot.id)).map((slot) => slot.id);
    }

    const initialNonblankIds = sampleNonblank();
    const renderMs = performance.now() - t0;
    const navigationReadyMs = performance.now();

    phase = "scroll";
    const scrollStart = performance.now();
    const scrollNonblankIds = [];
    const scrollRecoveryMs = [];
    // Context recovery is asynchronous (IntersectionObserver delivery ->
    // restore/rebuild -> draw), so each visit settles until the chart paints
    // or a hard deadline passes. The settle time IS the user-visible
    // recovery latency for a chart scrolled back into view.
    for (const slot of slots) {
      slot.cell.scrollIntoView({block: "center", inline: "center"});
      // Model an actual visit, not only a programmatic scroll. Pointer entry
      // is the product's explicit demand signal for a governed snapshot and
      // promotes the requested chart in the context-governor LRU.
      slot.view?.root.dispatchEvent(new PointerEvent("pointerenter"));
      const arriveMs = performance.now();
      let lit = nonblankPixels(slot) > 0;
      while (!lit && performance.now() - arriveMs < 400) {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        await new Promise((resolve) => setTimeout(resolve, 0));
        lit = nonblankPixels(slot) > 0;
      }
      if (lit) {
        scrollNonblankIds.push(slot.id);
        scrollRecoveryMs.push(performance.now() - arriveMs);
      }
    }
    window.scrollTo(0, 0);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const scrollPassMs = performance.now() - scrollStart;

    phase = "redraw";
    const steadyRedraws = [];
    for (let i = 0; i < 12; i++) {
      const redrawStart = performance.now();
      for (const slot of slots) if (!contextLost(slot)) slot.view._drawNow();
      steadyRedraws.push(performance.now() - redrawStart);
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
    phase = "report";

    const heapAfter = performance.memory ? performance.memory.usedJSHeapSize : null;
    const lostEvents = contextEvents.filter((event) => event.type === "lost");
    const restoredEvents = contextEvents.filter((event) => event.type === "restored");
    const governedLostEvents = lostEvents.filter((event) => event.governed === true);
    const uniqueIds = (events) => Array.from(new Set(events.map((event) => event.id)));
    const currentlyLostIds = slots
      .filter((slot) => slot.view && contextLost(slot))
      .map((slot) => slot.id);
    const ctxState = (slot) =>
      slot.view && slot.view.canvas && slot.view.canvas.dataset
        ? slot.view.canvas.dataset.xyCtx || null
        : null;
    // End-state split (§28): "released" is a governed, recoverable release;
    // "lost" is a browser-side eviction the governor could not prevent.
    const releasedChartIds = slots.filter((slot) => ctxState(slot) === "released").map((s) => s.id);
    const evictedChartIds = slots.filter((slot) => ctxState(slot) === "lost").map((s) => s.id);
    const createdCharts = slots.length - creationFailureIds.length;
    const fullyNonblank =
      createdCharts === slots.length &&
      initialNonblankIds.length === slots.length &&
      scrollNonblankIds.length === slots.length &&
      lostEvents.length === 0 &&
      currentlyLostIds.length === 0;
    // "governed": above the context budget, but every chart was created,
    // every context loss was a governed release, and every chart proved
    // nonblank while visited — the dashboard is fully usable, off-screen
    // charts just hold no context.
    const governedHealth =
      !fullyNonblank &&
      createdCharts === slots.length &&
      scrollNonblankIds.length === slots.length &&
      governedLostEvents.length === lostEvents.length;
    xyReport("XY_DASHBOARD", {
      status: "ok",
      render_status: fullyNonblank ? "complete" : governedHealth ? "governed" : "partial",
      fully_nonblank: fullyNonblank,
      render_ms: renderMs,
      navigation_ready_ms: navigationReadyMs,
      scroll_pass_ms: scrollPassMs,
      steady_redraw_p95_ms: xyPercentile(steadyRedraws, 95),
      steady_redraw_active_charts: slots.filter((slot) => slot.view && !contextLost(slot)).length,
      js_heap_before_bytes: heapBefore,
      js_heap_bytes: heapAfter,
      js_heap_delta_bytes: heapBefore == null || heapAfter == null ? null : heapAfter - heapBefore,
      created_charts: createdCharts,
      creation_failed_charts: creationFailureIds.length,
      creation_failure_ids: creationFailureIds,
      nonblank_charts: initialNonblankIds.length,
      initial_nonblank_charts: initialNonblankIds.length,
      initial_nonblank_chart_ids: initialNonblankIds,
      initial_blank_chart_ids: complement(initialNonblankIds),
      scroll_nonblank_charts: scrollNonblankIds.length,
      scroll_nonblank_chart_ids: scrollNonblankIds,
      scroll_blank_chart_ids: complement(scrollNonblankIds),
      scroll_recovery_p95_ms: xyPercentile(scrollRecoveryMs, 95),
      governed_context_lost_events: governedLostEvents.length,
      released_chart_ids: releasedChartIds,
      evicted_chart_ids: evictedChartIds,
      context_lost_events: lostEvents.length,
      context_restored_events: restoredEvents.length,
      context_lost_chart_ids: uniqueIds(lostEvents),
      context_restored_chart_ids: uniqueIds(restoredEvents),
      currently_lost_chart_ids: currentlyLostIds,
      context_events: contextEvents,
    });
  } catch (err) {
    xyFail("XY_DASHBOARD", err);
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
            title="xy dashboard probe",
            body_css=(
                "html,body{margin:0;background:#fff;font-family:system-ui,sans-serif;}"
                "#root{display:grid;grid-template-columns:repeat(4,420px);gap:12px;padding:12px;}"
                ".chart-cell{width:420px;height:280px;border:1px solid #dde3ec;}"
            ),
        )
        # The page may spend up to 400 ms settling each scroll visit.  A fixed
        # 15-second virtual-time budget can therefore expire before a healthy
        # 50-chart page reaches xyReport, yielding the misleading
        # ``failed(no probe title)`` row seen in CI.  Scale the virtual budget
        # with the requested work while retaining a real wall-clock timeout.
        result = run_json_probe(
            html,
            marker="XY_DASHBOARD",
            chromium=chromium,
            virtual_time_ms=(
                DASHBOARD_BASE_VIRTUAL_TIME_MS + count * DASHBOARD_SETTLE_VIRTUAL_TIME_MS_PER_CHART
            ),
            timeout_s=DASHBOARD_PROBE_TIMEOUT_S,
        )
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
            metric_keys = (
                "render_status",
                "fully_nonblank",
                "render_ms",
                "navigation_ready_ms",
                "scroll_pass_ms",
                "steady_redraw_p95_ms",
                "steady_redraw_active_charts",
                "js_heap_before_bytes",
                "js_heap_bytes",
                "js_heap_delta_bytes",
                "created_charts",
                "creation_failed_charts",
                "creation_failure_ids",
                "nonblank_charts",
                "initial_nonblank_charts",
                "initial_nonblank_chart_ids",
                "initial_blank_chart_ids",
                "scroll_nonblank_charts",
                "scroll_nonblank_chart_ids",
                "scroll_blank_chart_ids",
                "scroll_recovery_p95_ms",
                "governed_context_lost_events",
                "released_chart_ids",
                "evicted_chart_ids",
                "context_lost_events",
                "context_restored_events",
                "context_lost_chart_ids",
                "context_restored_chart_ids",
                "currently_lost_chart_ids",
                "context_events",
            )
            row.update({key: result.get(key) for key in metric_keys})
            row["ms_per_chart"] = (
                result.get("render_ms") / count if result.get("render_ms") is not None else None
            )
        rows.append(row)

    successful_counts = [
        row["chart_count"]
        for row in rows
        if str(row.get("status", "")).startswith("ok") and row.get("fully_nonblank") is True
    ]
    # A "governed" row is fully usable — every chart was created and proved
    # nonblank while visited; off-screen charts hold no context by design —
    # so it raises the *visible-stable* ceiling even though it is not
    # loss-free.
    visible_stable_counts = [
        row["chart_count"]
        for row in rows
        if str(row.get("status", "")).startswith("ok")
        and row.get("render_status") in {"complete", "governed"}
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dashboard-browser",
        "environment": collect_environment_metadata(chromium=chromium),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(DASHBOARD_CATEGORY_IDS),
        "attempted_chart_counts": list(chart_counts),
        "chart_count_ceiling": max(successful_counts) if successful_counts else None,
        "visible_stable_chart_ceiling": (
            max(visible_stable_counts) if visible_stable_counts else None
        ),
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
        "# xy many-chart dashboard benchmark",
        "",
        "## Benchmark Categories",
        "",
        *markdown_category_table(report.get("benchmark_categories", BENCHMARK_CATEGORIES)),
        "",
        "Tracked in this run: "
        + ", ".join(f"`{category['id']}`" for category in report["tracked_categories"]),
        "",
        f"Stable loss-free chart-count ceiling: `{report.get('chart_count_ceiling')}`; "
        f"visible-stable ceiling (complete or governed): "
        f"`{report.get('visible_stable_chart_ceiling')}`.",
        "",
        "## Results",
        "",
        "| scenario | charts | prep | navigation ready | render | scroll pass | recovery p95 | redraw submit p95 | active | JS heap | payload | html | initial/scroll nonblank | loss(gov)/restore | health |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {scenario} | {count} | {prep} | {navigation} | {render} | {scroll} | {recovery} | {idle} | {active} | {heap} | {payload} | {html} | {nonblank}/{scroll_nonblank} | {lost}({governed})/{restored} | {health} |".format(
                scenario=row["scenario"],
                count=row["chart_count"],
                prep=_fmt_ms(row.get("payload_prep_ms")),
                navigation=_fmt_ms(row.get("navigation_ready_ms")),
                render=_fmt_ms(row.get("render_ms")),
                scroll=_fmt_ms(row.get("scroll_pass_ms")),
                recovery=_fmt_ms(row.get("scroll_recovery_p95_ms")),
                idle=_fmt_ms(row.get("steady_redraw_p95_ms")),
                active=row.get("steady_redraw_active_charts", "—"),
                heap=_fmt_bytes(row.get("js_heap_bytes")),
                payload=_fmt_bytes(row.get("total_payload_bytes")),
                html=_fmt_bytes(row.get("html_bytes")),
                nonblank=row.get("nonblank_charts", "—"),
                scroll_nonblank=row.get("scroll_nonblank_charts", "—"),
                lost=row.get("context_lost_events", "—"),
                governed=row.get("governed_context_lost_events", "—"),
                restored=row.get("context_restored_events", "—"),
                health=row.get("render_status", row.get("status", "unknown")),
            )
        )
    lines += [
        "",
        "Notes:",
        "",
        "- `render` is measured inside the page from first chart decode through a context-event task yield and WebGL readback.",
        "- `redraw submit p95` measures synchronous command submission for every currently live context; `active` states how many charts contributed.",
        "- Partial rows retain startup, heap, redraw, context-event, and scrolling metrics; they do not raise the loss-free ceiling.",
        "- Context event IDs and phases are retained in JSON so LRU eviction and restoration churn are directly observable.",
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
