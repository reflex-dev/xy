"""Scatter benchmark: fastcharts vs popular Python charting libraries.

Measures, per library, per point count N, on identical random data:

  build_s     — construct the figure / add the scatter series
  render_s    — produce pixels where that is the library's normal static path
                (matplotlib/seaborn PNG, datashader PNG), otherwise produce the
                browser payload (Plotly/Bokeh/Altair/HoloViews HTML). For
                fastcharts, render_s is the kernel-side "prepare to render"
                cost: build the GPU-ready binary payload.
  total_s     — build + render
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
- render_s is not perfectly apples-to-apples (three different render targets);
  each cell records what it measured. The honest cross-library number is
  out_bytes and the ceiling probe.

Runs whatever libraries are installed; missing ones are reported as unavailable.

Usage:
  python benchmarks/bench_vs.py [--sizes 1e3,1e4,1e5,1e6,1e7] [--budget 45] [--out report.md]
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import time
import tracemalloc
from typing import Any, Callable

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
DPI = 100


def _rss_mb() -> float | None:
    if _PROC is None:
        return None
    return _PROC.memory_info().rss / 2**20


def _measure(build: Callable[[], Any], render: Callable[[Any], int]) -> dict:
    """Run build() then render(fig)->out_bytes, timing and memory-profiling both."""
    gc.collect()
    tracemalloc.start()
    rss0 = _rss_mb()
    t0 = time.perf_counter()
    fig = build()
    t1 = time.perf_counter()
    out_bytes = render(fig)
    t2 = time.perf_counter()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss1 = _rss_mb()
    del fig
    gc.collect()
    return {
        "build_s": t1 - t0,
        "render_s": t2 - t1,
        "total_s": t2 - t0,
        "peak_mem_mb": peak / 2**20,
        "rss_delta_mb": (rss1 - rss0) if (rss0 is not None and rss1 is not None) else None,
        "out_bytes": out_bytes,
        "status": "ok",
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
        return buf.getbuffer().nbytes

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
        return buf.getbuffer().nbytes

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
            return len(img)
        except Exception:
            html = fig.to_html(include_plotlyjs="cdn")
            return len(html.encode("utf-8"))

    return build, render


def make_bokeh_canvas(x, y):
    return _make_bokeh(x, y, output_backend="canvas")


def make_bokeh_webgl(x, y):
    return _make_bokeh(x, y, output_backend="webgl")


def _make_bokeh(x, y, output_backend: str):
    try:
        from bokeh.embed import file_html
        from bokeh.plotting import figure
        from bokeh.resources import CDN
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
        return len(html.encode("utf-8"))

    return build, render


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
        return len(html.encode("utf-8"))

    return build, render


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
            plot_width=RENDER_W,
            plot_height=RENDER_H,
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
        return buf.getbuffer().nbytes

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
        return len(html.encode("utf-8"))

    return build, render


def make_fastcharts(x, y):
    try:
        from fastcharts import Figure
    except ImportError:
        return None

    def build():
        return Figure(width=RENDER_W, height=RENDER_H).scatter(x, y)

    def render(fig):
        # The kernel-side "prepare to render" cost: encode direct f32, or bin to
        # a density grid above the threshold. The wire bytes are what crosses to
        # the GPU/browser — screen-bounded under density.
        _spec, blob = fig.build_payload()
        return len(blob)

    return build, render


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


def run(sizes: list[int], budget_s: float) -> dict:
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
            build, render = adapter
            try:
                row.update(_measure(build, render))
            except Exception as e:
                row["status"] = f"failed({type(e).__name__}: {str(e)[:80]})"
            row["pts_per_s"] = (n / row["total_s"]) if row.get("total_s") else None
            results[name].append(row)
            if row.get("total_s", 0) > budget_s:
                over_budget.add(name)  # ceiling reached; skip larger N
        del x, y
        gc.collect()

    ceilings = {}
    for name, rows in results.items():
        ok = [r["n"] for r in rows if r.get("status") == "ok"]
        ceilings[name] = max(ok) if ok else None

    return {"sizes": sizes, "budget_s": budget_s, "results": results, "ceilings": ceilings}


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

    lines += [f"## Ceiling — largest N rendered under {report['budget_s']:.0f}s budget", ""]
    lines += ["| library | max points |", "|---|---|"]
    for name, ceil in report["ceilings"].items():
        lines.append(f"| {name} | {ceil:,} |" if ceil else f"| {name} | — (unavailable) |")
    lines.append("")

    for name, rows in report["results"].items():
        if all(r.get("status") in ("unavailable", None) for r in rows):
            lines += [f"## {name}", "", "_unavailable in this environment_", ""]
            continue
        lines += [
            f"## {name}",
            "",
            "| N | build | render | total | peak mem | out bytes | pts/s | status |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            if r.get("status") != "ok":
                lines.append(f"| {r['n']:,} | | | | | | | {_fmt_status(r.get('status', '?'))} |")
                continue
            lines.append(
                f"| {r['n']:,} | {r['build_s'] * 1e3:.0f} ms | {r['render_s'] * 1e3:.0f} ms "
                f"| {r['total_s'] * 1e3:.0f} ms | {r['peak_mem_mb']:.0f} MB "
                f"| {_fmt_bytes(r['out_bytes'])} | {r['pts_per_s']:,.0f} | ok |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e3,1e4,1e5,1e6,1e7")
    ap.add_argument("--budget", type=float, default=45.0)
    ap.add_argument("--out", default=None, help="write Markdown report here")
    ap.add_argument("--json", default=None, help="write JSON results here")
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]

    report = run(sizes, args.budget)
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
