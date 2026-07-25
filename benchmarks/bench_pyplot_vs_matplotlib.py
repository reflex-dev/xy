"""Steady-state ``xy.pyplot`` versus Matplotlib/Agg benchmark.

This is the apples-to-apples companion to the broader cross-library harnesses.
Every case uses the same Matplotlib-style calls, the same already-generated
NumPy arrays, and the same final 1800 x 840 PNG target.  Timings are split into:

``build_ms``
    Python API calls that construct the figure.  xy intentionally defers part
    of its work until export, so this stage is diagnostic rather than the main
    winner metric.
``render_ms``
    Remaining work needed to produce the PNG after construction.
``total_ms``
    Figure construction through completed, compressed PNG.  This is the fair
    chart-to-pixels comparison and the headline ratio.

Data generation, imports, and the first warm-up render are excluded.  The run
alternates library order to reduce drift bias and retains all raw timing
samples in its JSON artifact.

Usage:
  PYTHONPATH=python .venv/bin/python benchmarks/bench_pyplot_vs_matplotlib.py \
    --profile smoke --reps 5 --json pyplot-vs-matplotlib.json
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import math
import statistics
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

RENDER_W = 900
RENDER_H = 420
BUILD_DPI = 100
EXPORT_DPI = 200
PNG_W = RENDER_W * EXPORT_DPI // BUILD_DPI
PNG_H = RENDER_H * EXPORT_DPI // BUILD_DPI
PROFILE_NAMES = ("smoke", "standard", "huge")
TRACKED_CATEGORY_IDS = ("small_data_startup", "core_2d_chart_breadth", "static_export")


@dataclass(frozen=True)
class Case:
    family: str
    label: str
    work_units: int
    unit: str
    xy_build: Callable[[], Any]
    matplotlib_build: Callable[[], Any]


@dataclass(frozen=True)
class Adapter:
    library: str
    build: Callable[[], Any]
    render: Callable[[Any], bytes]
    close: Callable[[Any], None]


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError("renderer did not return a valid PNG")
    return struct.unpack(">II", data[16:24])


def _lit_pixels(data: bytes) -> int:
    """Count non-background pixels outside the timed region.

    Pillow is already a Matplotlib dependency.  Keeping the import local makes
    the harness fail with a useful message if a stripped benchmark environment
    omitted it.
    """

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required for the PNG nonblank oracle") from exc
    with Image.open(io.BytesIO(data)) as image:
        rgb = np.asarray(image.convert("RGB"))
    return int(np.count_nonzero(np.any(rgb < 245, axis=2)))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _summary(samples: list[dict[str, float | int]]) -> dict[str, float | int]:
    build = [float(sample["build_ms"]) for sample in samples]
    render = [float(sample["render_ms"]) for sample in samples]
    total = [float(sample["total_ms"]) for sample in samples]
    output = [int(sample["output_bytes"]) for sample in samples]
    return {
        "build_median_ms": statistics.median(build),
        "render_median_ms": statistics.median(render),
        "total_median_ms": statistics.median(total),
        "total_p95_ms": _percentile(total, 0.95),
        "output_bytes_median": int(statistics.median(output)),
    }


def _xy_render(fig: Any) -> bytes:
    out = io.BytesIO()
    fig.savefig(out, format="png")
    return out.getvalue()


def _matplotlib_render(fig: Any) -> bytes:
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=EXPORT_DPI)
    return out.getvalue()


def _xy_render_tier(fig: Any) -> str:
    """Render tier(s) the xy figure used, disclosed per §28 (never silent):
    `direct` paints every mark, `decimated` is the M4-reduced series, and
    `density` rasterizes a screen-bounded aggregate. Matplotlib always paints
    every mark, so the tier column is what keeps large-N rows honest."""
    single = fig._single()
    if single is None:
        return "unknown"
    spec, _blob = single.figure().build_payload(px_width=RENDER_W)
    tiers = sorted({trace.get("tier", "unknown") for trace in spec.get("traces", [])})
    return "+".join(tiers) if tiers else "unknown"


def _sample(adapter: Adapter) -> tuple[dict[str, float | int], bytes]:
    gc.collect()
    fig = None
    try:
        t0 = time.perf_counter_ns()
        fig = adapter.build()
        t1 = time.perf_counter_ns()
        png = adapter.render(fig)
        t2 = time.perf_counter_ns()
    finally:
        if fig is not None:
            adapter.close(fig)
    build_ms = (t1 - t0) / 1e6
    render_ms = (t2 - t1) / 1e6
    width, height = _png_dimensions(png)
    if (width, height) != (PNG_W, PNG_H):
        raise AssertionError(
            f"{adapter.library} produced {width}x{height}; expected {PNG_W}x{PNG_H}"
        )
    return (
        {
            "build_ms": build_ms,
            "render_ms": render_ms,
            "total_ms": build_ms + render_ms,
            "output_bytes": len(png),
        },
        png,
    )


def _decorate(ax: Any, title: str) -> None:
    ax.set_title(title)
    ax.set_xlabel("x")
    ax.set_ylabel("y")


def make_cases(profile: str) -> tuple[list[Case], Any, Any]:
    if np is None:
        raise SystemExit("numpy is required for benchmarks/bench_pyplot_vs_matplotlib.py")
    if profile not in PROFILE_NAMES:
        raise ValueError(f"profile must be one of {PROFILE_NAMES}, got {profile!r}")

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as matplotlib_plt

    import xy.pyplot as xy_plt
    from xy import kernels

    if kernels.BACKEND != "native":
        raise SystemExit(f"benchmark requires xy native backend, got {kernels.BACKEND!r}")

    size = {
        "smoke": {
            "line": 20_000,
            "scatter": 25_000,
            "hist": 50_000,
            "bars": 200,
            "mesh": (80, 120),
            "contour": (80, 100),
        },
        "standard": {
            "line": 200_000,
            "scatter": 200_000,
            "hist": 1_000_000,
            "bars": 1_000,
            "mesh": (200, 300),
            "contour": (150, 200),
        },
        # Sizes where interactivity actually dies in Matplotlib: xy's
        # screen-bounded tiers stay flat while Agg scales with N. The per-row
        # tier column keeps the comparison honest (§28: no silent decimation).
        "huge": {
            "line": 1_000_000,
            "scatter": 1_000_000,
            "hist": 5_000_000,
            "bars": 5_000,
            "mesh": (400, 600),
            # 250*320 cells * 12 levels stays inside the contour kernel's
            # bounded work budget (1,000,000) — the guard is the product.
            "contour": (250, 320),
        },
    }[profile]
    rng = np.random.default_rng(2026)
    cases: list[Case] = []

    def paired_build(
        draw: Callable[[Any, Any], None],
    ) -> tuple[Callable[[], Any], Callable[[], Any]]:
        def build(module: Any) -> Any:
            module.close("all")
            fig, ax = module.subplots(
                figsize=(RENDER_W / BUILD_DPI, RENDER_H / BUILD_DPI), dpi=BUILD_DPI
            )
            draw(module, ax)
            return fig

        return lambda: build(xy_plt), lambda: build(matplotlib_plt)

    line_n = int(size["line"])
    line_x = np.linspace(0.0, 40.0, line_n)
    line_y = np.sin(line_x) + 0.08 * np.cos(line_x * 11.0)

    def draw_line(_module: Any, ax: Any) -> None:
        ax.plot(line_x, line_y, color="#2563eb", linewidth=1.2)
        _decorate(ax, "line")

    xy_build, mpl_build = paired_build(draw_line)
    cases.append(Case("line", f"{line_n:,} samples", line_n, "samples", xy_build, mpl_build))

    scatter_n = int(size["scatter"])
    scatter_x = rng.normal(size=scatter_n)
    scatter_y = 0.65 * scatter_x + rng.normal(scale=0.55, size=scatter_n)

    def draw_scatter(_module: Any, ax: Any) -> None:
        ax.scatter(
            scatter_x,
            scatter_y,
            s=6,
            alpha=0.65,
            c="#7c3aed",
            edgecolors="none",
        )
        _decorate(ax, "scatter")

    xy_build, mpl_build = paired_build(draw_scatter)
    cases.append(Case("scatter", f"{scatter_n:,} points", scatter_n, "points", xy_build, mpl_build))

    hist_n = int(size["hist"])
    hist_bins = 100 if profile == "smoke" else 200
    hist_values = np.concatenate(
        [
            rng.normal(-1.2, 0.65, hist_n // 2),
            rng.normal(1.1, 0.9, hist_n - hist_n // 2),
        ]
    )

    def draw_hist(_module: Any, ax: Any) -> None:
        ax.hist(hist_values, bins=hist_bins, color="#0891b2", alpha=0.8)
        _decorate(ax, "histogram")

    xy_build, mpl_build = paired_build(draw_hist)
    cases.append(
        Case(
            "histogram",
            f"{hist_n:,} values / {hist_bins} bins",
            hist_n,
            "values",
            xy_build,
            mpl_build,
        )
    )

    bar_n = int(size["bars"])
    bar_x = np.arange(bar_n, dtype=np.float64)
    bar_y = 10.0 + 4.0 * np.sin(bar_x / 19.0) + rng.random(bar_n)

    def draw_bar(_module: Any, ax: Any) -> None:
        ax.bar(bar_x, bar_y, width=0.82, color="#f59e0b")
        _decorate(ax, "bars")

    xy_build, mpl_build = paired_build(draw_bar)
    cases.append(Case("bar", f"{bar_n:,} bars", bar_n, "bars", xy_build, mpl_build))

    mesh_rows, mesh_cols = size["mesh"]
    mesh_x = np.linspace(-3.0, 3.0, mesh_cols)
    mesh_y = np.linspace(-2.0, 2.0, mesh_rows)
    mesh_xx, mesh_yy = np.meshgrid(mesh_x, mesh_y)
    mesh_z = np.sin(mesh_xx * 1.8) * np.cos(mesh_yy * 2.4)

    def draw_mesh(_module: Any, ax: Any) -> None:
        ax.pcolormesh(mesh_x, mesh_y, mesh_z, shading="auto", cmap="viridis")
        _decorate(ax, "pcolormesh")

    xy_build, mpl_build = paired_build(draw_mesh)
    mesh_cells = int(mesh_rows * mesh_cols)
    cases.append(
        Case(
            "pcolormesh",
            f"{mesh_rows:,} x {mesh_cols:,} cells",
            mesh_cells,
            "cells",
            xy_build,
            mpl_build,
        )
    )

    contour_rows, contour_cols = size["contour"]
    contour_x = np.linspace(-3.0, 3.0, contour_cols)
    contour_y = np.linspace(-2.0, 2.0, contour_rows)
    contour_xx, contour_yy = np.meshgrid(contour_x, contour_y)
    contour_z = np.sin(contour_xx * 1.7) + np.cos(contour_yy * 2.1)
    contour_levels = 8 if profile == "smoke" else 12

    def draw_contour(_module: Any, ax: Any) -> None:
        ax.contour(contour_x, contour_y, contour_z, levels=contour_levels, cmap="plasma")
        _decorate(ax, "contour")

    xy_build, mpl_build = paired_build(draw_contour)
    contour_cells = int(contour_rows * contour_cols)
    cases.append(
        Case(
            "contour",
            f"{contour_rows:,} x {contour_cols:,} / {contour_levels} levels",
            contour_cells,
            "cells",
            xy_build,
            mpl_build,
        )
    )
    return cases, xy_plt, matplotlib_plt


def _compare(
    case: Case,
    xy_row: dict[str, Any],
    matplotlib_row: dict[str, Any],
    *,
    target_speedup: float,
) -> dict[str, Any]:
    total_speedup = matplotlib_row["total_median_ms"] / xy_row["total_median_ms"]
    return {
        "family": case.family,
        "case": case.label,
        "work_units": case.work_units,
        "unit": case.unit,
        "xy_speedup_total": total_speedup,
        "target_xy_speedup_total": target_speedup,
        "meets_target": total_speedup >= target_speedup,
        "xy_speedup_build": matplotlib_row["build_median_ms"] / xy_row["build_median_ms"],
        "xy_speedup_render": matplotlib_row["render_median_ms"] / xy_row["render_median_ms"],
        "png_size_ratio_matplotlib_over_xy": (
            matplotlib_row["output_bytes_median"] / xy_row["output_bytes_median"]
        ),
        "winner_total": "xy.pyplot" if total_speedup >= 1.0 else "matplotlib",
        "xy_render_tier": xy_row.get("render_tier", "unknown"),
    }


def run(*, profile: str, reps: int, warmups: int, target_speedup: float = 10.0) -> dict[str, Any]:
    if reps < 1:
        raise ValueError("reps must be >= 1")
    if warmups < 0:
        raise ValueError("warmups must be >= 0")
    if not math.isfinite(target_speedup) or target_speedup <= 0.0:
        raise ValueError("target_speedup must be finite and > 0")
    cases, xy_plt, matplotlib_plt = make_cases(profile)
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    for case in cases:
        adapters = {
            "xy.pyplot": Adapter("xy.pyplot", case.xy_build, _xy_render, xy_plt.close),
            "matplotlib": Adapter(
                "matplotlib", case.matplotlib_build, _matplotlib_render, matplotlib_plt.close
            ),
        }
        for _ in range(warmups):
            for library in ("xy.pyplot", "matplotlib"):
                _sample(adapters[library])

        samples: dict[str, list[dict[str, float | int]]] = {
            "xy.pyplot": [],
            "matplotlib": [],
        }
        latest_png: dict[str, bytes] = {}
        for repetition in range(reps):
            order = (
                ("xy.pyplot", "matplotlib") if repetition % 2 == 0 else ("matplotlib", "xy.pyplot")
            )
            for library in order:
                sample, png = _sample(adapters[library])
                samples[library].append(sample)
                latest_png[library] = png

        tier_fig = adapters["xy.pyplot"].build()
        try:
            xy_tier = _xy_render_tier(tier_fig)
        finally:
            adapters["xy.pyplot"].close(tier_fig)

        case_rows: dict[str, dict[str, Any]] = {}
        for library in ("xy.pyplot", "matplotlib"):
            summary = _summary(samples[library])
            lit_pixels = _lit_pixels(latest_png[library])
            if lit_pixels < 1_000:
                raise AssertionError(
                    f"{library} {case.family} PNG is blank ({lit_pixels} lit pixels)"
                )
            row = {
                "family": case.family,
                "case": case.label,
                "work_units": case.work_units,
                "unit": case.unit,
                "library": library,
                "status": "ok",
                "render_target": "png",
                "mode": "native-raster" if library == "xy.pyplot" else "agg",
                "oracle_status": "pass",
                "oracle_kind": "same-pixel-dimensions-and-nonblank",
                "png_width": PNG_W,
                "png_height": PNG_H,
                "lit_pixels": lit_pixels,
                "reps": reps,
                "samples": samples[library],
                **summary,
            }
            if library == "xy.pyplot":
                row["render_tier"] = xy_tier
            rows.append(row)
            case_rows[library] = row
        comparisons.append(
            _compare(
                case,
                case_rows["xy.pyplot"],
                case_rows["matplotlib"],
                target_speedup=target_speedup,
            )
        )

    speedups = [comparison["xy_speedup_total"] for comparison in comparisons]
    geometric_mean = math.exp(sum(math.log(value) for value in speedups) / len(speedups))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "pyplot-vs-matplotlib",
        "environment": collect_environment_metadata(),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(TRACKED_CATEGORY_IDS),
        "profile": profile,
        "reps": reps,
        "warmups": warmups,
        "pixel_target": {"width": PNG_W, "height": PNG_H, "format": "png"},
        "measurement_scope": "warmed-api-build-through-static-png",
        "rows": rows,
        "comparisons": comparisons,
        "target_xy_speedup_total": target_speedup,
        "all_targets_met": all(comparison["meets_target"] for comparison in comparisons),
        "geometric_mean_xy_speedup_total": geometric_mean,
    }


def _fmt_ms(value: float) -> str:
    return f"{value:.2f} ms" if value < 100 else f"{value:.1f} ms"


def _fmt_ratio(value: float) -> str:
    return f"{value:.2f}x"


def _fmt_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KiB", "MiB"):
        if number < 1024 or unit == "MiB":
            return f"{number:.1f} {unit}"
        number /= 1024
    raise AssertionError("unreachable")


def to_markdown(report: dict[str, Any]) -> str:
    rows = {(row["family"], row["case"], row["library"]): row for row in report["rows"]}
    lines = [
        "# xy.pyplot vs Matplotlib performance",
        "",
        f"Profile: `{report['profile']}`; repetitions: `{report['reps']}`; warm-ups: "
        f"`{report['warmups']}`; target: `{report['pixel_target']['width']} x "
        f"{report['pixel_target']['height']} PNG`.",
        "",
        "| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    for comparison in report["comparisons"]:
        key = (comparison["family"], comparison["case"])
        xy_row = rows[(*key, "xy.pyplot")]
        mpl_row = rows[(*key, "matplotlib")]
        lines.append(
            "| {family} | {case} | {tier} | {xy_total} | {mpl_total} | {speedup} | {target} | {winner} | "
            "{xy_bytes} | {mpl_bytes} |".format(
                family=comparison["family"],
                case=comparison["case"],
                tier=comparison.get("xy_render_tier", "unknown"),
                xy_total=_fmt_ms(xy_row["total_median_ms"]),
                mpl_total=_fmt_ms(mpl_row["total_median_ms"]),
                speedup=_fmt_ratio(comparison["xy_speedup_total"]),
                target="pass" if comparison["meets_target"] else "**FAIL**",
                winner=comparison["winner_total"],
                xy_bytes=_fmt_bytes(xy_row["output_bytes_median"]),
                mpl_bytes=_fmt_bytes(mpl_row["output_bytes_median"]),
            )
        )
    lines += [
        "",
        f"Geometric-mean xy total speedup: **{_fmt_ratio(report['geometric_mean_xy_speedup_total'])}**.",
        f"Per-family {_fmt_ratio(report['target_xy_speedup_total'])} target: "
        f"**{'PASS' if report['all_targets_met'] else 'FAIL'}**.",
        "",
        "Method:",
        "",
        "- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.",
        "- Both outputs are validated as nonblank PNGs with identical pixel dimensions.",
        "- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.",
        "- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.",
        "- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.",
        "- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILE_NAMES, default="smoke")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--target-speedup", type=float, default=10.0)
    parser.add_argument(
        "--require-target",
        action="store_true",
        help="exit nonzero unless every family reaches --target-speedup",
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = run(
        profile=args.profile,
        reps=args.reps,
        warmups=args.warmups,
        target_speedup=args.target_speedup,
    )
    markdown = to_markdown(report)
    print(markdown, end="")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
    return 0 if not args.require_target or report["all_targets_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
