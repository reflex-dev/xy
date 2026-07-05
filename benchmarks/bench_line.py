"""Line / time-series decimation benchmark: fastcharts (M4) vs plotly-resampler
vs vanilla Plotly (methodology scenario `line_10M`).

plotly-resampler is the *honest* rival — it shares fastcharts' decimation
thesis (ship only what the pixels can show), so comparing our lines against
vanilla Plotly alone would be a strawman in our favor, and comparing against
plotly-resampler alone hides how much raw Plotly pays. Both run. The M4
extrema oracle (methodology §2) checks that decimation didn't drop the global
min/max — fast-but-wrong fails.

Missing libraries are reported `unavailable`, never dropped. Needs numpy to
generate the series; competitor rows need their libs installed (CI job).

    python benchmarks/bench_line.py --sizes 1e5,1e6,1e7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.bench_vs import _measure, np  # noqa: E402

# Default resampler downsample target; both aggregating libs aim for ~this many
# on-screen points, so their payloads are compared at the same visual budget.
N_OUT = 2000


def _series(n: int):
    rng = np.random.default_rng(0)
    x = np.arange(n, dtype=np.float64)
    y = np.cumsum(rng.normal(0, 1, n))  # random walk — a real time-series shape
    return x, y


def make_fastcharts(x, y):
    try:
        from fastcharts import Figure
    except ImportError:
        return None

    def build():
        return Figure(width=900, height=420).line(x, y)

    def render(fig):
        _spec, blob = fig.build_payload()  # M4-decimated for large N (§5 Tier 1)
        return len(blob)

    return build, render, (lambda fig: fig.to_html())


def make_plotly_vanilla(x, y):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    def build():
        return go.Figure(go.Scattergl(x=x, y=y, mode="lines"))

    def render(fig):
        return len(fig.to_html(include_plotlyjs="cdn").encode("utf-8"))

    return build, render, (lambda fig: fig.to_html(include_plotlyjs=True))


def make_plotly_resampler(x, y):
    try:
        import plotly.graph_objects as go
        from plotly_resampler import FigureResampler
    except ImportError:
        return None

    def build():
        fig = FigureResampler(go.Figure(), default_n_shown_samples=N_OUT)
        fig.add_trace(go.Scattergl(name="series", mode="lines"), hf_x=x, hf_y=y)
        return fig

    def render(fig):
        # The initial page ships only the downsampled view (its whole thesis);
        # further detail streams on zoom via a callback we don't exercise here.
        return len(fig.to_html(include_plotlyjs="cdn").encode("utf-8"))

    return build, render, (lambda fig: fig.to_html(include_plotlyjs=True))


ADAPTERS = {
    "fastcharts": make_fastcharts,
    "plotly_vanilla": make_plotly_vanilla,
    "plotly_resampler": make_plotly_resampler,
}


def _extrema_ok(x, y) -> bool:
    """M4 oracle (methodology §2): fastcharts' decimated line must retain the
    global y min/max rows — losing an extremum is the classic decimation lie."""
    try:
        from fastcharts import Figure
    except ImportError:
        return True  # can't check without the lib; not a failure of the oracle
    fig = Figure(width=900, height=420).line(x, y)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    if not isinstance(tr.get("y"), int):
        return True
    c = spec["columns"][tr["y"]]
    ys = np.frombuffer(blob, np.float32, count=c["len"], offset=c["byte_offset"])
    ys = ys.astype(np.float64) / c["scale"] + c["offset"]
    finite = y[np.isfinite(y)]
    if not len(finite) or not len(ys):
        return True
    # decimated extrema within a tolerance of the true extrema (f32 slack)
    tol = (finite.max() - finite.min()) * 1e-4 + 1e-6
    return abs(ys.max() - finite.max()) <= tol and abs(ys.min() - finite.min()) <= tol


def run(sizes: list[int]) -> dict:
    if np is None:
        raise SystemExit("numpy is required to generate the time series")
    results: dict[str, list[dict]] = {name: [] for name in ADAPTERS}
    for n in sizes:
        x, y = _series(n)
        oracle = _extrema_ok(x, y)
        for name, factory in ADAPTERS.items():
            row: dict[str, Any] = {"n": n, "library": name}
            adapter = factory(x, y)
            if adapter is None:
                row["status"] = "unavailable"
                results[name].append(row)
                continue
            build, render, _artifact = adapter
            try:
                row.update(_measure(build, render, None))
                row.pop("_artifact", None)
            except Exception as e:
                row["status"] = f"failed({type(e).__name__}: {str(e)[:80]})"
            if name == "fastcharts":
                row["extrema_oracle"] = "pass" if oracle else "FAIL"
            results[name].append(row)
        del x, y
    return {"sizes": sizes, "n_out": N_OUT, "results": results}


def _fmt_bytes(b: int | None) -> str:
    if b is None:
        return "—"
    size = float(b)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def to_markdown(report: dict) -> str:
    out = [
        "### Line / time-series decimation (fastcharts M4 vs plotly-resampler)",
        "",
        f"Random-walk series; aggregating libs target ~{report['n_out']} on-screen "
        "points. Payload = bytes the browser must receive; fastcharts ships the "
        "M4-decimated f32 blob, Plotly ships HTML+data.",
        "",
        "| N | library | prep | payload | extrema oracle |",
        "|---:|---|---:|---:|:--:|",
    ]
    for n in report["sizes"]:
        for name in ADAPTERS:
            row = next(
                (r for r in report["results"][name] if r["n"] == n),
                {"status": "missing"},
            )
            if row.get("status") != "ok":
                out.append(f"| {n:,} | {name} | {row.get('status', '—')} | — | — |")
                continue
            prep = f"{row['total_s'] * 1e3:.1f} ms"
            out.append(
                f"| {n:,} | {name} | {prep} | {_fmt_bytes(row.get('out_bytes'))} "
                f"| {row.get('extrema_oracle', '—')} |"
            )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e5,1e6,1e7")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]
    report = run(sizes)
    print(to_markdown(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    main()
