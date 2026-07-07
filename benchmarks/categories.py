"""Shared benchmark category metadata.

Keep `id` values stable: CI artifacts and downstream dashboards can key off
them even as the prose names or goals evolve.
"""

from __future__ import annotations

from collections.abc import Iterable

BENCHMARK_CATEGORIES: tuple[dict[str, str], ...] = (
    {
        "id": "small_data_startup",
        "name": "Small-data startup",
        "why": "Everyday charts should feel instant; a performance library cannot only win at 10M rows.",
        "metrics": "TTFR, JS/payload size, Python overhead",
        "harness": "benchmarks/bench_vs.py --ttfr at 1k-100k; benchmarks/test_codspeed_kernels.py::test_first_payload_scatter_small",
        "status": "tracked",
        "goal": "Beat Plotly/Bokeh/Altair on first interactive paint for common charts.",
    },
    {
        "id": "install_footprint_import_budget",
        "name": "Install footprint and import budget",
        "why": "Notebook, CI, and serverless users feel package weight and cold import time before the first chart exists.",
        "metrics": "cold import time, installed distribution bytes, file count",
        "harness": "benchmarks/bench_install.py",
        "status": "tracked",
        "goal": "Keep fastcharts lightweight at import and smaller to install than broad plotting stacks.",
    },
    {
        "id": "medium_direct_scatter",
        "name": "Medium direct scatter",
        "why": "Proves exact marker rendering, hover, color, and size channels before aggregation kicks in.",
        "metrics": "FPS, TTFR, memory, bytes/point, hover latency",
        "harness": "benchmarks/bench_vs.py at 100k-200k; benchmarks/bench_interaction.py; benchmarks/test_codspeed_kernels.py::test_first_payload_scatter_medium",
        "status": "tracked",
        "goal": "Smooth exact WebGL scatter with bounded bytes/point and no JSON-number payload cliff.",
    },
    {
        "id": "huge_scatter_overview",
        "name": "Huge scatter overview",
        "why": "Proves screen-bounded rendering for datasets larger than the browser should draw point-for-point.",
        "metrics": "ingest/bin time, density payload size, peak memory, TTFR",
        "harness": "benchmarks/bench_scatter_native.py, benchmarks/bench_vs.py, benchmarks/test_codspeed_kernels.py::test_first_payload_density_large, example app assets",
        "status": "tracked",
        "goal": "Keep resident/render payload flat in N while showing truthful density summaries.",
    },
    {
        "id": "adaptive_scatter_drilldown",
        "name": "Adaptive scatter drilldown",
        "why": "The large-data claim needs a credible path from overview to exact visible points.",
        "metrics": "visible-query latency, tier-switch latency, exact-point recovery, badge accuracy",
        "harness": "benchmarks/test_codspeed_kernels.py::test_adaptive_drilldown_cycle",
        "status": "tracked",
        "goal": "Exact points when visible count is under budget; sampled/density with explicit counts otherwise.",
    },
    {
        "id": "huge_line_time_series",
        "name": "Huge line/time series",
        "why": "Common observability and finance workload; Plotly-resampler sets the bar here.",
        "metrics": "decimation time, zoom re-decimation latency, TTFR, extrema preservation",
        "harness": "benchmarks/bench.py, benchmarks/bench_native.py, benchmarks/bench_interaction.py, benchmarks/test_codspeed_kernels.py::test_decimate_view",
        "status": "tracked",
        "goal": "Screen-bounded line payloads with extrema-preserving decimation and fast zoom refresh.",
    },
    {
        "id": "many_chart_dashboards",
        "name": "Many-chart dashboards",
        "why": "Plotly-class apps often fail from total page weight and many live canvases, not one chart.",
        "metrics": "total TTFR, memory, idle CPU, chart count ceiling",
        "harness": "benchmarks/bench_dashboard.py",
        "status": "tracked",
        "goal": "Load 10-50 interactive charts with lower total memory and faster first usable dashboard than Plotly/Bokeh.",
    },
    {
        "id": "interaction_smoothness",
        "name": "Interaction smoothness",
        "why": "Users judge performance by pan/zoom/hover, not just export time.",
        "metrics": "pan/zoom FPS, wheel latency, hover latency, tooltip stability, selection latency, frame color delta",
        "harness": "benchmarks/bench_interaction.py",
        "status": "tracked",
        "goal": "Stay responsive during interaction, avoid blank/flickering frames, then refine view after interaction settles.",
    },
    {
        "id": "payload_export_size",
        "name": "Payload/export size",
        "why": "Notebooks, static HTML, docs, and dashboards pay for every byte shipped.",
        "metrics": "standalone HTML bytes, binary payload bytes, bundle bytes",
        "harness": "benchmarks/bench_vs.py, benchmarks/bench_scatter_native.py, benchmarks/test_codspeed_kernels.py::test_first_payload_density_large, benchmarks/test_codspeed_kernels.py::test_memory_report_density_medium, example app asset sizes",
        "status": "tracked",
        "goal": "Keep data payloads binary and screen-bounded where possible; warn when exact export would be huge.",
    },
    {
        "id": "core_2d_chart_breadth",
        "name": "Core 2D chart breadth",
        "why": "The library needs to stay fast beyond the scatter wedge: bars, histograms, areas, and heatmaps are everyday chart workloads.",
        "metrics": "payload-prep time, payload bytes, standalone HTML bytes, TTFR",
        "harness": "benchmarks/bench_2d_charts.py smoke/standard profiles vs Plotly and Seaborn; benchmarks/bench_interaction.py; benchmarks/test_codspeed_kernels.py core_2d payload rows",
        "status": "tracked",
        "goal": "Beat Plotly on user-visible first paint for common 2D charts while tracking Seaborn raster baselines where applicable.",
    },
)

CATEGORY_BY_ID = {category["id"]: category for category in BENCHMARK_CATEGORIES}


def categories_for(ids: Iterable[str]) -> list[dict[str, str]]:
    return [CATEGORY_BY_ID[category_id] for category_id in ids]


def markdown_category_table(
    categories: Iterable[dict[str, str]] = BENCHMARK_CATEGORIES,
) -> list[str]:
    lines = [
        "| id | category | status | primary metrics | current/planned harness | goal |",
        "|---|---|---|---|---|---|",
    ]
    for category in categories:
        lines.append(
            "| {id} | {name} | {status} | {metrics} | {harness} | {goal} |".format(**category)
        )
    return lines
