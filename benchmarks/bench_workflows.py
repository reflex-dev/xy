"""Workflow benchmarks for ingestion, streaming updates, and static export.

These paths are public and performance-sensitive, but are not native-kernel
microbenchmarks. Each row excludes deterministic fixture construction, times a
complete public operation, and records the output bytes it produced.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xy as fc  # noqa: E402
from _browser import find_chromium  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402
from xy import kernels as k  # noqa: E402
from xy._figure import Figure  # noqa: E402  (harness oracles/annotations only)
from xy.interaction import _ensure_pyramid  # noqa: E402

WORKFLOW_CATEGORY_IDS = ("input_ingestion", "streaming_updates", "log_autorange", "static_export")


def _require_oracle(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _png_oracle(_fig: Figure, value: Any) -> None:
    _require_oracle(
        isinstance(value, bytes) and value.startswith(b"\x89PNG\r\n\x1a\n"),
        "invalid PNG export",
    )


def _output_bytes(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], dict):
        message, buffers = value
        return len(json.dumps(message, separators=(",", ":"), default=str).encode("utf-8")) + sum(
            len(buffer) for buffer in buffers
        )
    return 0


def _measure(
    *,
    scenario: str,
    family: str,
    n: int,
    setup: Callable[[], Any],
    operation: Callable[[Any], Any],
    reps: int,
    category_ids: tuple[str, ...],
    scope: str,
    oracle: Callable[[Any, Any], None],
) -> dict[str, Any]:
    values: list[float] = []
    output_bytes = 0
    last_result = None
    for _ in range(reps):
        state = setup()
        t0 = time.perf_counter()
        result = operation(state)
        last_result = result
        values.append((time.perf_counter() - t0) * 1e3)
        oracle(state, result)
        output_bytes = _output_bytes(result)

    state = setup()
    tracemalloc.start()
    try:
        operation(state)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(np.ceil(0.95 * len(ordered))) - 1))
    row = {
        "scenario": scenario,
        "family": family,
        "n": n,
        "reps": reps,
        "median_ms": statistics.median(values),
        "p95_ms": ordered[p95_index],
        "max_ms": max(values),
        "output_bytes": output_bytes,
        "peak_python_mb": peak / 2**20,
        "scope": scope,
        "oracle_status": "pass",
        "benchmark_categories": [category["id"] for category in categories_for(category_ids)],
        "status": "ok",
    }
    if family == "ingestion" and isinstance(last_result, Figure):
        report = last_result.store.memory_report()
        row["ingest_copies"] = sum(int(column["ingest_copies"]) for column in report["columns"])
        row["canonical_bytes"] = int(report["canonical_bytes"])
    return row


def _ingestion_rows(n: int, reps: int) -> list[dict[str, Any]]:
    x64 = np.arange(n, dtype=np.float64)
    y64 = np.sin(x64 * 0.001)
    x32 = x64.astype(np.float32)
    y32 = y64.astype(np.float32)
    noncontiguous = np.arange(n * 2, dtype=np.float64)[::2]
    datetimes = np.datetime64("2026-01-01T00:00:00", "ms") + np.arange(n).astype("timedelta64[ms]")
    cases: list[tuple[str, Any, Any]] = [
        ("numpy_f64_contiguous", x64, y64),
        ("numpy_f32_conversion", x32, y32),
        ("numpy_f64_noncontiguous", noncontiguous, y64),
        ("datetime64_axis", datetimes, y64),
        ("python_lists", x64.tolist(), y64.tolist()),
    ]
    try:
        import pyarrow as pa

        cases.append(("arrow_f64_zero_copy", pa.array(x64), pa.array(y64)))
        with_nulls = pa.array(x64, mask=(np.arange(n) % 97 == 0))
        cases.append(("arrow_f64_with_nulls", with_nulls, pa.array(y64)))
    except ImportError:
        pass
    try:
        import pandas as pd

        cases.append(("pandas_series_f64", pd.Series(x64), pd.Series(y64)))
    except ImportError:
        pass

    rows = []
    for name, x, y in cases:
        expected_copies = {
            "numpy_f64_contiguous": 0,
            "numpy_f32_conversion": 2,
            "numpy_f64_noncontiguous": 1,
            "datetime64_axis": 1,
            "arrow_f64_zero_copy": 0,
            "arrow_f64_with_nulls": 2,
        }.get(name)

        def ingestion_oracle(
            _state: Any,
            fig: Figure,
            expected=expected_copies,
            scenario_name=name,
        ) -> None:
            if len(fig.traces) != 1 or fig.traces[0].n_points != n:
                raise AssertionError(f"ingestion changed row count for {scenario_name}")
            if expected is not None:
                report = fig.store.memory_report()
                copies = sum(int(column["ingest_copies"]) for column in report["columns"])
                if copies != expected:
                    raise AssertionError(
                        f"{scenario_name} copy oracle failed: observed {copies}, expected {expected}"
                    )

        rows.append(
            _measure(
                scenario=f"ingest_{name}",
                family="ingestion",
                n=n,
                setup=lambda x=x, y=y: (x, y),
                operation=lambda state: fc.chart(fc.line(x=state[0], y=state[1])).figure(),
                reps=reps,
                category_ids=("input_ingestion",),
                scope="public-figure-ingest",
                oracle=ingestion_oracle,
            )
        )
    return rows


def _streaming_rows(base_n: int, reps: int) -> list[dict[str, Any]]:
    x = np.arange(base_n, dtype=np.float64)
    y = np.sin(x * 0.001)
    batch_n = 1_000
    tail_x = np.arange(base_n, base_n + batch_n, dtype=np.float64)
    tail_y = np.sin(tail_x * 0.001)

    def line_setup() -> Figure:
        fig = fc.chart(fc.line(x=x, y=y)).figure()
        fig.build_payload()
        return fig

    rows = [
        _measure(
            scenario="stream_line_append_1k",
            family="streaming",
            n=base_n,
            setup=line_setup,
            operation=lambda fig: fig.append(0, tail_x, tail_y),
            reps=reps,
            category_ids=("streaming_updates", "huge_line_time_series"),
            scope="public-append-refresh-payload",
            oracle=lambda fig, _result: _require_oracle(
                fig.traces[0].n_points == base_n + batch_n,
                "line append row-count oracle failed",
            ),
        )
    ]

    pyramid_n = 2_100_000
    rng = np.random.default_rng(81)
    sx = rng.uniform(0.0, 100.0, pyramid_n).astype(np.float64, copy=False)
    sy = rng.uniform(0.0, 100.0, pyramid_n).astype(np.float64, copy=False)
    append_x = np.array([50.0] * batch_n, dtype=np.float64)
    append_y = np.linspace(45.0, 55.0, batch_n, dtype=np.float64)

    def density_setup() -> Figure:
        fig = fc.chart(fc.scatter(x=sx, y=sy, density=True)).figure()
        fig.build_payload()
        assert _ensure_pyramid(fig.traces[0]) is not None
        return fig

    def append_and_update(fig: Figure) -> tuple[dict[str, Any], list[bytes]]:
        old_handle = fig.traces[0]._pyr_handle
        fig.append(0, append_x, append_y)
        if fig.traces[0]._pyr_handle != old_handle:
            raise AssertionError("stable-domain append replaced the native pyramid")
        update, buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 512, 384)
        trace = update["traces"][0]
        if not str(trace.get("binning", "")).startswith("pyramid-L"):
            raise AssertionError(f"expected rebuilt pyramid path, got {trace.get('binning')!r}")
        if int(trace.get("visible", -1)) != pyramid_n + batch_n:
            raise AssertionError(
                f"density append count oracle failed: {trace.get('visible')} != {pyramid_n + batch_n}"
            )
        return update, buffers

    rows.append(
        _measure(
            scenario="stream_density_append_1k_incremental_pyramid",
            family="streaming",
            n=pyramid_n,
            setup=density_setup,
            operation=append_and_update,
            reps=max(1, min(reps, 3)),
            category_ids=("streaming_updates", "huge_scatter_overview"),
            scope="append-incremental-pyramid-and-refresh",
            oracle=lambda _fig, result: _require_oracle(
                result[0]["traces"][0]["mode"] == "density",
                "density append did not remain density",
            ),
        )
    )
    return rows


def _log_autorange_rows(n: int, reps: int) -> list[dict[str, Any]]:
    x = np.arange(n, dtype=np.float64)
    y = np.exp(np.linspace(-8.0, 8.0, n, dtype=np.float64))
    y[::97] *= -1.0
    y[::211] = np.nan
    positive = y[np.isfinite(y) & (y > 0.0)]

    def setup() -> Figure:
        return Figure().line(x, y).set_axis("y", type_="log")

    def oracle(_fig: Figure, value: tuple[float, float]) -> None:
        lo, hi = value
        _require_oracle(lo > 0.0 and hi > 0.0, "log autorange returned a non-positive domain")
        _require_oracle(lo <= float(np.min(positive)), "log autorange clipped the positive minimum")
        _require_oracle(hi >= float(np.max(positive)), "log autorange clipped the positive maximum")

    return [
        _measure(
            scenario="log_line_autorange",
            family="range",
            n=n,
            setup=setup,
            operation=lambda fig: fig.y_range(),
            reps=reps,
            category_ids=("log_autorange", "huge_line_time_series"),
            scope="public-log-autorange-zone-stats",
            oracle=oracle,
        )
    ]


def _export_rows(n: int, reps: int, chromium: str | None) -> list[dict[str, Any]]:
    x = np.arange(n, dtype=np.float64)
    y = np.sin(x * 0.002) + np.cos(x * 0.0003)

    def figure() -> Figure:
        return fc.chart(fc.line(x=x, y=y), width=900, height=420).figure()

    rows = []
    for scenario, operation, oracle in (
        (
            "export_html_decimated_line",
            lambda fig: fig.to_html(),
            lambda _fig, value: _require_oracle(
                isinstance(value, str) and "xy.renderStandalone" in value,
                "invalid standalone HTML export",
            ),
        ),
        (
            "export_svg_decimated_line",
            lambda fig: fig.to_svg(),
            lambda _fig, value: _require_oracle(
                isinstance(value, str) and "<svg" in value,
                "invalid SVG export",
            ),
        ),
        (
            "export_png_native_decimated_line",
            lambda fig: fig.to_png(engine=fc.Engine.default),
            _png_oracle,
        ),
    ):
        rows.append(
            _measure(
                scenario=scenario,
                family="export",
                n=n,
                setup=figure,
                operation=operation,
                reps=reps,
                category_ids=("static_export", "payload_export_size"),
                scope="public-static-export",
                oracle=oracle,
            )
        )
    if chromium:
        previous_browser = os.environ.get("XY_BROWSER")
        os.environ["XY_BROWSER"] = chromium
        try:
            rows.append(
                _measure(
                    scenario="export_png_chromium_decimated_line",
                    family="export",
                    n=n,
                    setup=figure,
                    operation=lambda fig: fig.to_png(engine=fc.Engine.chromium),
                    reps=1,
                    category_ids=("static_export", "payload_export_size"),
                    scope="public-chromium-png-export",
                    oracle=_png_oracle,
                )
            )
        finally:
            if previous_browser is None:
                os.environ.pop("XY_BROWSER", None)
            else:
                os.environ["XY_BROWSER"] = previous_browser
    return rows


def run(*, profile: str, reps: int, chromium: str | None = None) -> dict[str, Any]:
    if k.BACKEND != "native":
        raise RuntimeError(f"workflow benchmarks require native backend, got {k.BACKEND!r}")
    if profile not in {"smoke", "standard"}:
        raise ValueError("profile must be 'smoke' or 'standard'")
    ingest_n = 10_000 if profile == "smoke" else 100_000
    stream_n = 100_000 if profile == "smoke" else 1_000_000
    export_n = 10_000 if profile == "smoke" else 1_000_000
    rows = [
        *_ingestion_rows(ingest_n, reps),
        *_streaming_rows(stream_n, reps),
        *_log_autorange_rows(stream_n, reps),
        *_export_rows(export_n, reps, chromium),
    ]
    environment = collect_environment_metadata(chromium=chromium, xy_backend=k.BACKEND)
    if chromium:
        # The opt-in Chromium row forces SwiftShader independently of benchmark flags.
        environment["browser_renderer"] = "software-gl"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "workflow-native",
        "profile": profile,
        "reps": reps,
        "environment": environment,
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(WORKFLOW_CATEGORY_IDS),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("smoke", "standard"), default="standard")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    chromium = find_chromium(args.chromium) if args.chromium is not None else None
    report = run(profile=args.profile, reps=args.reps, chromium=chromium)
    for row in report["rows"]:
        print(
            f"{row['scenario']}: median={row['median_ms']:.2f} ms "
            f"p95={row['p95_ms']:.2f} ms output={row['output_bytes']:,} B"
        )
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
