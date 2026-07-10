"""Scatter benchmark: fastcharts vs popular Python charting libraries.

Measures, per library, per point count N, on identical random data:

  build_s     — construct the figure / add the scatter series
  render_s    — produce pixels where that is the library's normal static path
                (matplotlib/seaborn PNG, datashader PNG), otherwise produce the
                browser payload (Plotly/Bokeh/Altair/HoloViews HTML). For
                fastcharts, render_s is the kernel-side "prepare to render"
                cost: build the GPU-ready binary payload.
  total_s     — build + render
  ttfr_ms     — interactive build + HTML serialization + chart-ready time;
                rendered libs (fastcharts, Plotly-HTML, Bokeh, Altair, hvPlot)
                are loaded in headless Chromium and measured to a visible chart
                surface after two animation frames; raster libs (matplotlib/seaborn/
                datashader/Plotly-kaleido) already produced pixels at render, so
                TTFR = total. This is the only cross-library "how fast to actual
                pixels" number — serialize time and byte counts are not pixels.
  peak_mem_mb — Python-side peak allocation during build+render (tracemalloc);
                RSS delta too when psutil is present
  out_bytes   — PNG bytes / HTML bytes / fastcharts wire bytes
  pts_per_s   — N / total_s
  status      — ok | failed(reason) | skipped(over budget)

Then a **ceiling probe**: the largest N each library renders under a wall-clock
budget without erroring — the "how many points can it actually draw" number.

Design notes / fairness:
- Data generation is excluded from every timing (shared arrays).
- matplotlib/seaborn and SVG/HTML-spec libraries grow cost ∝ N. WebGL-backed
  browser libraries still generally ship/hold per-point buffers. Datashader and
  fastcharts exercise the screen-bounded density path; fastcharts additionally
  reports the binary transport cost that crosses to the browser/GPU.
- Static render rows are target-scoped (binary spec, HTML, or PNG) and must not
  be turned into cross-target speedup claims. Each successful row records mode,
  target, and oracle; interactive TTFR uses a separate build+HTML+chart-ready path.

Runs whatever libraries are installed; missing ones are reported as unavailable.

Usage:
  python benchmarks/bench_vs.py [--sizes 1e3,1e4,1e5,1e6,1e7] [--budget 45] [--out report.md]
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _browser import chart_ready_metrics  # noqa: E402
from categories import (  # noqa: E402
    BENCHMARK_CATEGORIES,
    categories_for,
    markdown_category_table,
)
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
DENSITY_W, DENSITY_H = 512, 384
DPI = 100
BENCH_VS_CATEGORY_IDS = (
    "small_data_startup",
    "medium_direct_scatter",
    "huge_scatter_overview",
    "payload_export_size",
)


def _rss_mb() -> float | None:
    if _PROC is None:
        return None
    return _PROC.memory_info().rss / 2**20


def _measure(
    build: Callable[[], Any],
    render: Callable[[Any], int],
    artifact_fn: Callable[[Any], str] | None = None,
) -> dict:
    """Run build() then render(fig)->out_bytes, timing and memory-profiling both.

    Timing and memory come from two separate passes. tracemalloc captures a
    Python stack trace on every malloc/free while active — real overhead that
    scales with allocation *count*, not size. Tracing during the timed pass
    would not inflate every library's total_s uniformly: it would penalize
    allocation-heavy libraries (matplotlib/Plotly building thousands of small
    Python objects) far more than fastcharts, which does a handful of large
    NumPy/native buffer operations. So the first pass times build+render with
    no tracer active; a second, untimed pass on a fresh build measures peak
    allocation.

    RSS (resident set) is measured around the *timed* pass, not the tracemalloc
    pass: it is an OS-level number unaffected by whether tracemalloc is tracing,
    and measuring it around a second pass would understate it — freed arenas
    from the first pass are typically not returned to the OS, so the second
    pass's "before" baseline is already elevated, collapsing a real ~170 MB
    resident-growth story down to a few MB of noise. Caught by comparing this
    run's numbers against the previous one before publishing them.

    If `artifact_fn` is given (browser-rendered libraries), capture the page HTML
    from the timed pass's figure — untimed — so the TTFR stage can paint it.
    Raster libraries (PNG) leave it None: their render already produced pixels."""
    gc.collect()
    rss0 = _rss_mb()
    t0 = time.perf_counter()
    fig = build()
    t1 = time.perf_counter()
    render_result = render(fig)
    t2 = time.perf_counter()
    if isinstance(render_result, dict):
        out_bytes = int(render_result["out_bytes"])
        render_metadata = {k: v for k, v in render_result.items() if k != "out_bytes"}
    else:
        out_bytes = int(render_result)
        render_metadata = {}
    rss1 = _rss_mb()
    artifact = None
    artifact_s = None
    if artifact_fn is not None:
        try:
            ta0 = time.perf_counter()
            artifact = artifact_fn(fig)
            artifact_s = time.perf_counter() - ta0
        except Exception:  # artifact for TTFR is best-effort, never fails a row
            artifact = None
    del fig
    gc.collect()

    gc.collect()
    tracemalloc.start()
    fig2 = build()
    render(fig2)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del fig2
    gc.collect()

    return {
        "build_s": t1 - t0,
        "render_s": t2 - t1,
        "total_s": t2 - t0,
        "peak_mem_mb": peak / 2**20,
        "rss_delta_mb": (rss1 - rss0) if (rss0 is not None and rss1 is not None) else None,
        "out_bytes": out_bytes,
        "artifact_s": artifact_s,
        "_artifact": artifact,  # HTML for browser libs, else None (raster)
        "status": "ok",
        **render_metadata,
    }


# ---------------------------------------------------------------------------
# Library adapters — each returns (build, render) or None if unavailable.
# ---------------------------------------------------------------------------


def make_matplotlib(x, y):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    def build():
        fig, ax = plt.subplots(figsize=(RENDER_W / DPI, RENDER_H / DPI), dpi=DPI)
        ax.scatter(x, y, s=4, linewidths=0)
        return (fig, ax, plt)

    def render(state):
        fig, _ax, plt = state
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return {
            "out_bytes": buf.getbuffer().nbytes,
            "mode": "direct",
            "render_target": "png-agg",
            "oracle_status": "pass",
            "oracle_kind": "raw-row-count",
        }

    return build, render


def make_seaborn(x, y):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        return None

    def build():
        fig, ax = plt.subplots(figsize=(RENDER_W / DPI, RENDER_H / DPI), dpi=DPI)
        sns.scatterplot(x=x, y=y, s=16, linewidth=0, legend=False, ax=ax)
        return (fig, ax, plt)

    def render(state):
        fig, _ax, plt = state
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return {
            "out_bytes": buf.getbuffer().nbytes,
            "mode": "direct",
            "render_target": "png-agg",
            "oracle_status": "pass",
            "oracle_kind": "raw-row-count",
        }

    return build, render


def make_plotly_gl(x, y):
    return _make_plotly(x, y, gl=True)


def make_plotly_svg(x, y):
    return _make_plotly(x, y, gl=False)


def _make_plotly(x, y, gl: bool):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    trace_cls = go.Scattergl if gl else go.Scatter

    def build():
        fig = go.Figure(trace_cls(x=x, y=y, mode="markers", marker={"size": 4}))
        fig.update_layout(width=RENDER_W, height=RENDER_H)
        return fig

    def render(fig):
        # Prefer real pixels via kaleido; fall back to HTML bytes (still the
        # payload a browser must parse — plotly embeds data as JSON).
        try:
            img = fig.to_image(format="png")  # kaleido
            return {
                "out_bytes": len(img),
                "mode": "direct",
                "render_target": "png-kaleido",
                "oracle_status": "pass",
                "oracle_kind": "raw-row-count",
            }
        except Exception:
            html = fig.to_html(include_plotlyjs="cdn")
            return {
                "out_bytes": len(html.encode("utf-8")),
                "mode": "direct",
                "render_target": "html-cdn-fallback",
                "oracle_status": "pass",
                "oracle_kind": "raw-row-count",
            }

    # TTFR is the interactive browser path: plotly.js inlined (no CDN), painted.
    def artifact(fig):
        return fig.to_html(include_plotlyjs=True)

    return build, render, artifact


def make_bokeh_canvas(x, y):
    return _make_bokeh(x, y, output_backend="canvas")


def make_bokeh_webgl(x, y):
    return _make_bokeh(x, y, output_backend="webgl")


def _make_bokeh(x, y, output_backend: str):
    try:
        from bokeh.embed import file_html
        from bokeh.plotting import figure
        from bokeh.resources import CDN, INLINE
    except ImportError:
        return None

    def build():
        plot = figure(
            width=RENDER_W,
            height=RENDER_H,
            output_backend=output_backend,
            toolbar_location=None,
        )
        plot.scatter(x=x, y=y, size=4, line_alpha=0.0, fill_alpha=0.8)
        return plot

    def render(plot):
        html = file_html(plot, CDN, f"bokeh-{output_backend}-benchmark")
        return {
            "out_bytes": len(html.encode("utf-8")),
            "mode": "direct",
            "render_target": f"html-bokeh-{output_backend}",
            "oracle_status": "pass",
            "oracle_kind": "raw-row-count",
        }

    # TTFR: BokehJS inlined so the browser paint excludes CDN fetch.
    def artifact(plot):
        return file_html(plot, INLINE, f"bokeh-{output_backend}-ttfr")

    return build, render, artifact


def make_altair(x, y):
    try:
        import altair as alt
        import pandas as pd
    except ImportError:
        return None

    alt.data_transformers.disable_max_rows()

    def build():
        df = pd.DataFrame({"x": x, "y": y})
        return (
            alt.Chart(df)
            .mark_point(size=16, opacity=0.8)
            .encode(x="x:Q", y="y:Q")
            .properties(width=RENDER_W, height=RENDER_H)
        )

    def render(chart):
        html = chart.to_html()
        return {
            "out_bytes": len(html.encode("utf-8")),
            "mode": "direct",
            "render_target": "html-vega",
            "oracle_status": "pass",
            "oracle_kind": "raw-row-count",
        }

    return build, render, (lambda chart: chart.to_html())


def make_datashader(x, y):
    try:
        import datashader as ds
        import datashader.transfer_functions as tf
        import pandas as pd
    except ImportError:
        return None

    def build():
        df = pd.DataFrame({"x": x, "y": y})
        canvas = ds.Canvas(
            plot_width=DENSITY_W,
            plot_height=DENSITY_H,
            x_range=_padded_range(x),
            y_range=_padded_range(y),
        )
        return df, canvas

    def render(state):
        df, canvas = state
        agg = canvas.points(df, "x", "y")
        image = tf.shade(agg, how="linear")
        buf = io.BytesIO()
        image.to_pil().save(buf, format="PNG")
        count = int(agg.sum().item())
        if count != len(x):
            raise AssertionError(f"datashader count oracle failed: {count} != {len(x)}")
        return {
            "out_bytes": buf.getbuffer().nbytes,
            "mode": "density",
            "render_target": "png-datashader",
            "oracle_status": "pass",
            "oracle_kind": "count-conservation",
            "aggregate_width": DENSITY_W,
            "aggregate_height": DENSITY_H,
        }

    return build, render


def make_hvplot_bokeh(x, y):
    try:
        import holoviews as hv
        import hvplot.pandas  # noqa: F401
        import pandas as pd
        from bokeh.embed import file_html
        from bokeh.resources import CDN
    except ImportError:
        return None

    hv.extension("bokeh", logo=False)

    def build():
        df = pd.DataFrame({"x": x, "y": y})
        return df.hvplot.scatter(
            x="x",
            y="y",
            width=RENDER_W,
            height=RENDER_H,
            size=4,
            alpha=0.8,
        )

    def render(obj):
        state = hv.renderer("bokeh").get_plot(obj).state
        html = file_html(state, CDN, "hvplot-bokeh-benchmark")
        return {
            "out_bytes": len(html.encode("utf-8")),
            "mode": "direct",
            "render_target": "html-hvplot-bokeh",
            "oracle_status": "pass",
            "oracle_kind": "raw-row-count",
        }

    def artifact(obj):
        from bokeh.resources import INLINE

        state = hv.renderer("bokeh").get_plot(obj).state
        return file_html(state, INLINE, "hvplot-bokeh-ttfr")

    return build, render, artifact


def make_fastcharts(x, y):
    try:
        from fastcharts import scatter, scatter_chart
    except ImportError:
        return None

    def build():
        return scatter_chart(scatter(x=x, y=y), width=RENDER_W, height=RENDER_H).figure()

    def render(fig):
        # The kernel-side "prepare to render" cost: encode direct f32, or bin to
        # a density grid above the threshold. The wire bytes are what crosses to
        # the GPU/browser — screen-bounded under density.
        spec, blob = fig.build_payload()
        trace = spec["traces"][0]
        mode = trace["tier"]
        if mode == "density":
            density = trace["density"]
            column = spec["columns"][density["buf"]]
            grid = np.frombuffer(
                blob,
                dtype=np.float32,
                count=column["len"],
                offset=column["byte_offset"],
            )
            actual = int(round(float(grid.sum())))
            expected = int(trace["visible"])
            if actual != expected:
                raise AssertionError(f"fastcharts count oracle failed: {actual} != {expected}")
            oracle_kind = "count-conservation"
            aggregate_width = int(density["w"])
            aggregate_height = int(density["h"])
        else:
            expected = len(x)
            if trace.get("n_marks") != expected:
                raise AssertionError(
                    f"fastcharts direct-row oracle failed: {trace.get('n_marks')} != {expected}"
                )
            oracle_kind = "raw-row-count"
            aggregate_width = None
            aggregate_height = None
        return {
            "out_bytes": len(blob) + len(json.dumps(spec, separators=(",", ":")).encode()),
            "mode": mode,
            "render_target": "binary-spec",
            "oracle_status": "pass",
            "oracle_kind": oracle_kind,
            "aggregate_width": aggregate_width,
            "aggregate_height": aggregate_height,
        }

    # TTFR: the standalone-export path (payload base64'd into HTML, decoded and
    # WebGL-drawn in the browser). The widget path is faster still (binary comm,
    # no base64) — this is the conservative, uniformly-measured artifact.
    def artifact(fig):
        return fig.to_html()

    return build, render, artifact


ADAPTERS = {
    "fastcharts": make_fastcharts,
    "matplotlib": make_matplotlib,
    "seaborn": make_seaborn,
    "plotly_gl": make_plotly_gl,
    "plotly_svg": make_plotly_svg,
    "bokeh_canvas": make_bokeh_canvas,
    "bokeh_webgl": make_bokeh_webgl,
    "altair": make_altair,
    "datashader": make_datashader,
    "hvplot_bokeh": make_hvplot_bokeh,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(
    sizes: list[int],
    budget_s: float,
    *,
    ttfr: bool = False,
    ttfr_max_n: int | None = None,
    chromium: str | None = None,
) -> dict:
    if np is None:
        raise SystemExit(
            "numpy is required to run the comparison (data generation). "
            "Install it, or run benchmarks/bench_scatter_native.py for the "
            "fastcharts-only arm with no dependencies."
        )
    rng = np.random.default_rng(0)
    results: dict[str, list[dict]] = {name: [] for name in ADAPTERS}
    over_budget: set[str] = set()

    for n in sizes:
        x = rng.normal(0, 1, n)
        y = x * 0.5 + rng.normal(0, 0.6, n)
        for name, factory in ADAPTERS.items():
            row: dict[str, Any] = {"n": n, "library": name}
            if name in over_budget:
                row["status"] = "skipped(over budget)"
                results[name].append(row)
                continue
            adapter = factory(x, y)
            if adapter is None:
                row["status"] = "unavailable"
                results[name].append(row)
                continue
            build, render, artifact_fn = _normalize(adapter)
            try:
                row.update(_measure(build, render, artifact_fn if ttfr else None))
            except Exception as e:
                row["status"] = f"failed({type(e).__name__}: {str(e)[:80]})"
            row["pts_per_s"] = (n / row["total_s"]) if row.get("total_s") else None
            # Time to first render: browser paint for HTML artifacts; the render
            # itself for raster libs (PNG already = pixels). §17 makes this the
            # metric that matters — bytes and serialize time don't equal pixels.
            if ttfr and row.get("status") == "ok" and (ttfr_max_n is None or n <= ttfr_max_n):
                html = row.pop("_artifact", None)
                if html:
                    browser = chart_ready_metrics(html, chromium=chromium)
                    ready = None if browser is None else browser["ready_ms"]
                    row["browser_ready_ms"] = ready
                    row["browser_fcp_ms"] = None if browser is None else browser["fcp_ms"]
                    row["browser_js_heap_bytes"] = (
                        None if browser is None else browser["js_heap_bytes"]
                    )
                    row["browser_paint_ms"] = ready  # schema-v2 compatibility
                    artifact_s = row.get("artifact_s")
                    row["ttfr_ms"] = (
                        (row["build_s"] + artifact_s) * 1e3 + ready
                        if ready is not None and artifact_s is not None
                        else None
                    )
                else:  # raster: build+render already produced pixels
                    row["ttfr_ms"] = row["total_s"] * 1e3
            row.pop("_artifact", None)
            results[name].append(row)
            if row.get("total_s", 0) > budget_s:
                over_budget.add(name)  # ceiling reached; skip larger N
        del x, y
        gc.collect()

    ceilings = {}
    for name, rows in results.items():
        ok = [
            r["n"]
            for r in rows
            if r.get("status") == "ok" and r.get("total_s", float("inf")) <= budget_s
        ]
        ceilings[name] = max(ok) if ok else None

    return {
        "schema_version": SCHEMA_VERSION,
        "environment": collect_environment_metadata(chromium=chromium),
        "sizes": sizes,
        "budget_s": budget_s,
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(BENCH_VS_CATEGORY_IDS),
        "results": results,
        "ceilings": ceilings,
        "ttfr": ttfr,
    }


def _normalize(adapter: Any) -> tuple[Callable, Callable, Callable | None]:
    """Adapters return (build, render) or (build, render, artifact_fn)."""
    if len(adapter) == 3:
        return adapter
    build, render = adapter
    return build, render, None


def _fmt_bytes(b: int | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _padded_range(values) -> tuple[float, float]:
    lo = float(np.nanmin(values))
    hi = float(np.nanmax(values))
    if not np.isfinite(lo) or not np.isfinite(hi):
        return (0.0, 1.0)
    if lo == hi:
        pad = abs(lo) * 0.05 or 0.5
        return (lo - pad, hi + pad)
    pad = (hi - lo) * 0.03
    return (lo - pad, hi + pad)


def _fmt_status(status: object) -> str:
    return str(status).replace("|", "/").replace("\n", " ")


def to_markdown(report: dict) -> str:
    lines = ["# Scatter benchmark: fastcharts vs Python charting libraries", ""]
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
    env = []
    try:
        import fastcharts.kernels as k

        env.append(f"fastcharts backend: `{k.BACKEND}`")
    except Exception:
        pass
    if _PROC is not None:
        env.append("RSS via psutil")
    if env:
        lines += [", ".join(env), ""]

    lines += [
        "## Tracked benchmark categories",
        "",
    ]
    lines += markdown_category_table(report.get("benchmark_categories", BENCHMARK_CATEGORIES))
    lines += [
        "",
        "This run currently exercises: "
        + ", ".join(f"`{category['id']}`" for category in report["tracked_categories"])
        + ".",
        "",
        "Mode labels should stay explicit in benchmark interpretation: `direct`, "
        "`decimated`, `density`, `sampled`, or `adaptive`. A 10M density result "
        "is not the same claim as 10M individually styled markers.",
        "",
    ]

    lines += [f"## Ceiling — largest N rendered under {report['budget_s']:.0f}s budget", ""]
    lines += ["| library | max points |", "|---|---|"]
    for name, ceil in report["ceilings"].items():
        lines.append(f"| {name} | {ceil:,} |" if ceil else f"| {name} | — (unavailable) |")
    lines.append("")

    ttfr = report.get("ttfr")
    if ttfr:
        # Cross-library time-to-first-render: build → data in memory → pixels.
        # Browser libs include headless-Chromium first-contentful-paint; raster
        # libs (PNG) count build+render, which already produced pixels.
        lines += [
            "## Time to first render (data → pixels)",
            "",
            "Browser libraries include build + interactive HTML serialization + "
            "headless-Chromium chart-ready time (JS inlined, no CDN). Raster "
            "libraries report their independent PNG path.",
            "",
            "| library | N | interactive TTFR | browser chart-ready |",
            "|---|---|---|---|",
        ]
        for name, rows in report["results"].items():
            for r in rows:
                if r.get("ttfr_ms") is None:
                    continue
                paint = r.get("browser_paint_ms")
                paint_s = f"{paint:.0f} ms" if paint is not None else "— (raster)"
                lines.append(f"| {name} | {r['n']:,} | {r['ttfr_ms']:.0f} ms | {paint_s} |")
        lines.append("")

    for name, rows in report["results"].items():
        if all(r.get("status") in ("unavailable", None) for r in rows):
            lines += [f"## {name}", "", "_unavailable in this environment_", ""]
            continue
        lines += [
            f"## {name}",
            "",
            "| N | mode | target | build | render | total | TTFR | peak mem | out bytes | oracle | pts/s | status |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            if r.get("status") != "ok":
                lines.append(
                    f"| {r['n']:,} | | | | | | | | | | | {_fmt_status(r.get('status', '?'))} |"
                )
                continue
            ttfr_ms = r.get("ttfr_ms")
            ttfr_s = f"{ttfr_ms:.0f} ms" if ttfr_ms is not None else "—"
            lines.append(
                f"| {r['n']:,} | {r.get('mode', '—')} | {r.get('render_target', '—')} "
                f"| {r['build_s'] * 1e3:.0f} ms | {r['render_s'] * 1e3:.0f} ms "
                f"| {r['total_s'] * 1e3:.0f} ms | {ttfr_s} | {r['peak_mem_mb']:.0f} MB "
                f"| {_fmt_bytes(r['out_bytes'])} | {r.get('oracle_status', '—')} "
                f"| {r['pts_per_s']:,.0f} | ok |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e3,1e4,1e5,1e6,1e7")
    ap.add_argument("--budget", type=float, default=45.0)
    ap.add_argument("--out", default=None, help="write Markdown report here")
    ap.add_argument("--json", default=None, help="write JSON results here")
    ap.add_argument(
        "--ttfr", action="store_true", help="measure time-to-first-render in headless Chromium"
    )
    ap.add_argument(
        "--ttfr-max-n", type=float, default=1e5, help="cap N for the (slow) browser-paint pass"
    )
    ap.add_argument("--chromium", default=None, help="path to a Chromium/Chrome binary")
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]

    report = run(
        sizes,
        args.budget,
        ttfr=args.ttfr,
        ttfr_max_n=int(args.ttfr_max_n),
        chromium=args.chromium,
    )
    md = to_markdown(report)
    print(md)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    main()
