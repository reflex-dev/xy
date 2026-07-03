"""Three-way scatter benchmark: fastcharts vs Plotly vs matplotlib.

Measures, per library, per point count N, on identical random data:

  build_s     — construct the figure / add the scatter series
  render_s    — produce pixels (matplotlib: savefig PNG; plotly: kaleido to_image
                if available, else to_html; fastcharts: build the GPU-ready
                binary payload — the kernel-side "prepare to render" cost)
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
- matplotlib and plotly-SVG are CPU raster/vector and grow cost ∝ N. plotly
  Scattergl is WebGL (its fast path). fastcharts ships a screen-bounded payload:
  direct f32 up to the density threshold, then a fixed-size density grid — so
  its wire bytes go *flat* while the others grow. That crossover is the point.
- render_s is not perfectly apples-to-apples (three different render targets);
  each cell records what it measured. The honest cross-library number is
  out_bytes and the ceiling probe.

Runs whatever libraries are installed; missing ones are reported as unavailable.

Usage:
  python scripts/bench_vs.py [--sizes 1e3,1e4,1e5,1e6,1e7] [--budget 45] [--out report.md]
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import time
import tracemalloc
from typing import Any, Callable, Optional

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

try:
    import psutil  # type: ignore

    _PROC = psutil.Process()
except Exception:  # noqa: BLE001
    _PROC = None

RENDER_W, RENDER_H = 900, 420
DPI = 100


def _rss_mb() -> Optional[float]:
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


def make_matplotlib(x, y):  # noqa: ANN001
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


def make_plotly_gl(x, y):  # noqa: ANN001
    return _make_plotly(x, y, gl=True)


def make_plotly_svg(x, y):  # noqa: ANN001
    return _make_plotly(x, y, gl=False)


def _make_plotly(x, y, gl: bool):  # noqa: ANN001
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
        except Exception:  # noqa: BLE001
            html = fig.to_html(include_plotlyjs="cdn")
            return len(html.encode("utf-8"))

    return build, render


def make_fastcharts(x, y):  # noqa: ANN001
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
    "matplotlib": make_matplotlib,
    "plotly_gl": make_plotly_gl,
    "plotly_svg": make_plotly_svg,
    "fastcharts": make_fastcharts,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(sizes: list[int], budget_s: float) -> dict:
    if np is None:
        raise SystemExit(
            "numpy is required to run the comparison (data generation). "
            "Install it, or run scripts/bench_scatter_native.py for the "
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
            except Exception as e:  # noqa: BLE001 — a lib OOMing/erroring is a data point
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


def _fmt_bytes(b: Optional[int]) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def to_markdown(report: dict) -> str:
    lines = ["# Scatter benchmark: fastcharts vs Plotly vs matplotlib", ""]
    env = []
    try:
        import fastcharts.kernels as k

        env.append(f"fastcharts backend: `{k.BACKEND}`")
    except Exception:  # noqa: BLE001
        pass
    if _PROC is not None:
        env.append("RSS via psutil")
    if env:
        lines += [", ".join(env), ""]

    lines += ["## Ceiling — largest N rendered under "
              f"{report['budget_s']:.0f}s budget", ""]
    lines += ["| library | max points |", "|---|---|"]
    for name, ceil in report["ceilings"].items():
        lines.append(f"| {name} | {ceil:,} |" if ceil else f"| {name} | — (unavailable) |")
    lines.append("")

    for name, rows in report["results"].items():
        if all(r.get("status") in ("unavailable", None) for r in rows):
            lines += [f"## {name}", "", "_unavailable in this environment_", ""]
            continue
        lines += [f"## {name}", "",
                  "| N | build | render | total | peak mem | out bytes | pts/s | status |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r.get("status") != "ok":
                lines.append(f"| {r['n']:,} | | | | | | | {r.get('status', '?')} |")
                continue
            lines.append(
                f"| {r['n']:,} | {r['build_s']*1e3:.0f} ms | {r['render_s']*1e3:.0f} ms "
                f"| {r['total_s']*1e3:.0f} ms | {r['peak_mem_mb']:.0f} MB "
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
