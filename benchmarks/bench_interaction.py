"""Browser interaction benchmark for fastcharts.

This is intentionally opt-in instead of part of the core CodSpeed suite:
headless Chromium is useful for user-visible latency, but too heavyweight and
machine-sensitive for every microbenchmark run. The benchmark measures the
actual ChartView paths for zoom, pan, hover, and box zoom, then verifies that
the canvas produced nonblank WebGL pixels.

Usage:
  PYTHONPATH=python .venv/bin/python benchmarks/bench_interaction.py --sizes 1e4,1e5,1e6
"""

from __future__ import annotations

import argparse
import json
import sys
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

INTERACTION_CATEGORY_IDS = (
    "medium_direct_scatter",
    "huge_scatter_overview",
    "interaction_smoothness",
)
RENDER_W, RENDER_H = 900, 420


def _parse_sizes(text: str) -> list[int]:
    return [int(float(part)) for part in text.split(",") if part.strip()]


def _scatter_figure(n: int) -> Any:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_interaction.py")
    from fastcharts import Figure

    rng = np.random.default_rng(70_011 + n)
    x = rng.normal(0.0, 1.0, n).astype(np.float64, copy=False)
    y = (0.58 * x + rng.normal(0.0, 0.72, n)).astype(np.float64, copy=False)
    return Figure(
        width=RENDER_W,
        height=RENDER_H,
        title=f"{n:,} point interaction probe",
        x_label="x",
        y_label="y",
    ).scatter(x, y, name="points", opacity=0.72)


def _probe_js(reps: int) -> str:
    return f"""
(() => {{
  try {{
    const payload = FC_CHARTS[0];
    const el = document.createElement("div");
    document.getElementById("root").appendChild(el);
    const view = fastcharts.renderStandalone(el, payload.spec, fcBytesFromB64(payload.b64));
    view._drawNow();
    const before = {{...view.view}};

    function measure(fn) {{
      const values = [];
      for (let i = 0; i < {reps}; i++) {{
        const t0 = performance.now();
        fn(i);
        view._drawNow();
        values.push(performance.now() - t0);
      }}
      return fcStats(values);
    }}

    const wheel = measure((i) => {{
      view._zoomAt(i % 2 ? 1.04 : 0.96, 0.5, 0.5, false);
    }});
    const pan = measure((i) => {{
      const v = view.view;
      const dx = (v.x1 - v.x0) * (i % 2 ? 0.012 : -0.012);
      view._setView({{x0: v.x0 + dx, x1: v.x1 + dx, y0: v.y0, y1: v.y1}}, {{
        animate: false,
        request: false,
      }});
    }});
    const hover = measure((i) => {{
      const r = view.canvas.getBoundingClientRect();
      const x = r.left + r.width * (0.18 + (i % 9) * 0.08);
      const y = r.top + r.height * (0.25 + (i % 7) * 0.07);
      view.canvas.dispatchEvent(new PointerEvent("pointermove", {{
        bubbles: true,
        clientX: x,
        clientY: y,
        pointerId: 1,
      }}));
    }});
    const box = measure((i) => {{
      const v = view.view;
      const x0 = v.x0 + (v.x1 - v.x0) * 0.22;
      const x1 = v.x0 + (v.x1 - v.x0) * 0.78;
      const y0 = v.y0 + (v.y1 - v.y0) * 0.22;
      const y1 = v.y0 + (v.y1 - v.y0) * 0.78;
      view._zoomToBox([x0, y0], [x1, y1], false);
      if (i % 2) view._setView(before, {{animate: false, request: false}});
    }});
    const after = {{...view.view}};
    const nonblank = fcNonblankPixels(view);
    if (nonblank <= 0) throw new Error("blank WebGL canvas");
    fcReport("FC_INTERACTION", {{
      status: "ok",
      tier: payload.spec.traces[0].tier,
      nonblank_pixels: nonblank,
      view_changed: Math.abs(after.x0 - before.x0) > 1e-9 || Math.abs(after.x1 - before.x1) > 1e-9,
      wheel_zoom: wheel,
      pan: pan,
      hover: hover,
      box_zoom: box,
    }});
  }} catch (err) {{
    fcFail("FC_INTERACTION", err);
  }}
}})();
"""


def _flatten_probe_metrics(row: dict[str, Any], result: dict[str, Any]) -> None:
    row["status"] = result.get("status", "failed(no status)")
    if row["status"] != "ok":
        return
    row["tier"] = result.get("tier")
    row["nonblank_pixels"] = result.get("nonblank_pixels")
    row["view_changed"] = bool(result.get("view_changed"))
    for name in ("wheel_zoom", "pan", "hover", "box_zoom"):
        stats = result.get(name) or {}
        row[f"{name}_median_ms"] = stats.get("median_ms")
        row[f"{name}_p95_ms"] = stats.get("p95_ms")
        row[f"{name}_max_ms"] = stats.get("max_ms")
        row[f"{name}_reps"] = stats.get("reps")


def run(*, sizes: list[int], reps: int, chromium: str | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for n in sizes:
        fig = _scatter_figure(n)
        spec, blob = fig.build_payload()
        tier = spec["traces"][0]["tier"]
        category_ids = (
            ("medium_direct_scatter", "interaction_smoothness")
            if tier == "direct"
            else ("huge_scatter_overview", "interaction_smoothness")
        )
        row: dict[str, Any] = {
            "scenario": f"{tier}_scatter_interaction",
            "n": n,
            "tier": tier,
            "benchmark_categories": [
                category["id"] for category in categories_for(category_ids)
            ],
            "payload_bytes": json_bytes(spec) + len(blob),
        }
        html = page_for_charts(
            [chart_payload("interaction", spec, blob)],
            _probe_js(reps),
            title="fastcharts interaction probe",
        )
        row["html_bytes"] = len(html.encode("utf-8"))
        result = run_json_probe(html, marker="FC_INTERACTION", chromium=chromium)
        _flatten_probe_metrics(row, result)
        rows.append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "interaction-browser",
        "environment": collect_environment_metadata(chromium=chromium),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(INTERACTION_CATEGORY_IDS),
        "reps": reps,
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
        "# fastcharts browser interaction benchmark",
        "",
        f"Repetitions per gesture: `{report['reps']}`.",
        "",
        "## Benchmark Categories",
        "",
        *markdown_category_table(report.get("benchmark_categories", BENCHMARK_CATEGORIES)),
        "",
        "Tracked in this run: "
        + ", ".join(f"`{category['id']}`" for category in report["tracked_categories"]),
        "",
        "## Results",
        "",
        "| scenario | points | tier | payload | wheel p95 | pan p95 | hover p95 | box p95 | nonblank | status |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {scenario} | {n:,} | {tier} | {payload} | {wheel} | {pan} | {hover} | {box} | {nonblank} | {status} |".format(
                scenario=row["scenario"],
                n=row["n"],
                tier=row.get("tier", "—"),
                payload=_fmt_bytes(row.get("payload_bytes")),
                wheel=_fmt_ms(row.get("wheel_zoom_p95_ms")),
                pan=_fmt_ms(row.get("pan_p95_ms")),
                hover=_fmt_ms(row.get("hover_p95_ms")),
                box=_fmt_ms(row.get("box_zoom_p95_ms")),
                nonblank=row.get("nonblank_pixels", "—"),
                status=row.get("status", "unknown"),
            )
        )
    lines += [
        "",
        "Notes:",
        "",
        "- Times are in-page `performance.now()` deltas through `ChartView` methods plus an immediate draw.",
        "- `nonblank` is a WebGL readback sanity check from the chart canvas center.",
        "- The density rows measure client interaction over the current density surface; backend drilldown switching is tracked separately in CodSpeed.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="1e4,1e5,1e6")
    parser.add_argument("--reps", type=int, default=12)
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--out", default=None, help="write Markdown report here")
    parser.add_argument("--json", default=None, help="write JSON report here")
    args = parser.parse_args()

    report = run(sizes=_parse_sizes(args.sizes), reps=args.reps, chromium=args.chromium)
    md = to_markdown(report)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
