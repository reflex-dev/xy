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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmarks._browser import chart_ready_metrics  # noqa: E402
from benchmarks.bench_vs import _measure, np  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

# Default resampler downsample target; both aggregating libs aim for ~this many
# on-screen points, so their payloads are compared at the same visual budget.
N_OUT = 2000
LINE_CATEGORY_IDS = ("huge_line_time_series", "payload_export_size")


def _series(n: int):
    rng = np.random.default_rng(0)
    x = np.arange(n, dtype=np.float64)
    y = np.cumsum(rng.normal(0, 1, n))  # random walk — a real time-series shape
    return x, y


def make_fastcharts(x, y):
    try:
        from fastcharts import chart, line
    except ImportError:
        return None

    def build():
        return chart(line(x=x, y=y), width=900, height=420).figure()

    def render(fig):
        _spec, blob = fig.build_payload(N_OUT)  # same on-screen sample budget as resampler
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
    """M4 oracle: every populated pixel bucket must retain its y min and max."""
    try:
        from fastcharts import chart, line
    except ImportError:
        return False
    fig = chart(line(x=x, y=y), width=900, height=420).figure()
    spec, blob = fig.build_payload(N_OUT)
    tr = spec["traces"][0]
    if tr.get("tier") != "decimated" or not all(isinstance(tr.get(k), int) for k in ("x", "y")):
        return False

    def decode(ref: int) -> np.ndarray:
        column = spec["columns"][ref]
        values = np.frombuffer(
            blob, np.float32, count=column["len"], offset=column["byte_offset"]
        ).astype(np.float64)
        return values / column.get("scale", 1.0) + column.get("offset", 0.0)

    xs = decode(tr["x"])
    ys = decode(tr["y"])
    finite = np.isfinite(x) & np.isfinite(y)
    if not bool(np.any(finite)):
        return len(xs) == 0
    source_x = x[finite]
    source_y = y[finite]
    x0, x1 = sorted(fig.x_range())
    span = x1 - x0
    if span <= 0 or not len(xs):
        return False

    def buckets(values: np.ndarray) -> np.ndarray:
        return np.clip(((values - x0) / span * N_OUT).astype(np.int64), 0, N_OUT - 1)

    expected_min = np.full(N_OUT, np.inf)
    expected_max = np.full(N_OUT, -np.inf)
    actual_min = np.full(N_OUT, np.inf)
    actual_max = np.full(N_OUT, -np.inf)
    np.minimum.at(expected_min, buckets(source_x), source_y)
    np.maximum.at(expected_max, buckets(source_x), source_y)
    # Re-associate encoded f32 x values with the nearest canonical row before
    # assigning buckets. A point exactly on a bucket boundary can move by an ULP
    # during wire encoding; that must not turn a correct M4 result into an oracle
    # failure in the adjacent bucket.
    positions = np.searchsorted(source_x, xs)
    right = np.clip(positions, 0, len(source_x) - 1)
    left = np.clip(positions - 1, 0, len(source_x) - 1)
    nearest = np.where(np.abs(source_x[left] - xs) <= np.abs(source_x[right] - xs), left, right)
    actual_buckets = buckets(source_x[nearest])
    np.minimum.at(actual_min, actual_buckets, ys)
    np.maximum.at(actual_max, actual_buckets, ys)
    populated = np.isfinite(expected_min)
    tol = (float(source_y.max()) - float(source_y.min())) * 1e-4 + 1e-6
    return bool(
        np.all(np.abs(actual_min[populated] - expected_min[populated]) <= tol)
        and np.all(np.abs(actual_max[populated] - expected_max[populated]) <= tol)
    )


def run(
    sizes: list[int],
    *,
    ttfr: bool = False,
    ttfr_max_n: int = 100_000,
    chromium: str | None = None,
) -> dict:
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
            build, render, artifact = adapter
            try:
                row.update(_measure(build, render, artifact if ttfr and n <= ttfr_max_n else None))
                html = row.pop("_artifact", None)
                if html:
                    browser = chart_ready_metrics(html, chromium=chromium)
                    ready = None if browser is None else browser["ready_ms"]
                    row["browser_ready_ms"] = ready
                    row["browser_fcp_ms"] = None if browser is None else browser["fcp_ms"]
                    row["browser_js_heap_bytes"] = (
                        None if browser is None else browser["js_heap_bytes"]
                    )
                    artifact_s = row.get("artifact_s")
                    row["ttfr_ms"] = (
                        (row["build_s"] + artifact_s) * 1e3 + ready
                        if ready is not None and artifact_s is not None
                        else None
                    )
            except Exception as e:
                row["status"] = f"failed({type(e).__name__}: {str(e)[:80]})"
            row["pts_per_s"] = (n / row["total_s"]) if row.get("total_s") else None
            if name == "fastcharts":
                row["extrema_oracle"] = "pass" if oracle else "FAIL"
                row["oracle_kind"] = "per-pixel-column-minmax"
            results[name].append(row)
        del x, y
    return {
        "schema_version": SCHEMA_VERSION,
        "environment": collect_environment_metadata(),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(LINE_CATEGORY_IDS),
        "sizes": sizes,
        "n_out": N_OUT,
        "ttfr": ttfr,
        "ttfr_max_n": ttfr_max_n,
        "results": results,
    }


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
        "| N | library | prep | payload | interactive TTFR | chart ready | extrema oracle |",
        "|---:|---|---:|---:|---:|---:|:--:|",
    ]
    for n in report["sizes"]:
        for name in ADAPTERS:
            row = next(
                (r for r in report["results"][name] if r["n"] == n),
                {"status": "missing"},
            )
            if row.get("status") != "ok":
                out.append(f"| {n:,} | {name} | {row.get('status', '—')} | — | — | — | — |")
                continue
            prep = f"{row['total_s'] * 1e3:.1f} ms"
            ttfr = f"{row['ttfr_ms']:.1f} ms" if row.get("ttfr_ms") is not None else "—"
            ready = (
                f"{row['browser_ready_ms']:.1f} ms"
                if row.get("browser_ready_ms") is not None
                else "—"
            )
            out.append(
                f"| {n:,} | {name} | {prep} | {_fmt_bytes(row.get('out_bytes'))} "
                f"| {ttfr} | {ready} "
                f"| {row.get('extrema_oracle', '—')} |"
            )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e5,1e6,1e7")
    ap.add_argument("--json", default=None)
    ap.add_argument("--ttfr", action="store_true")
    ap.add_argument("--ttfr-max-n", type=float, default=1e5)
    ap.add_argument("--chromium", default=None)
    args = ap.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",")]
    report = run(
        sizes,
        ttfr=args.ttfr,
        ttfr_max_n=int(args.ttfr_max_n),
        chromium=args.chromium,
    )
    print(to_markdown(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    main()
