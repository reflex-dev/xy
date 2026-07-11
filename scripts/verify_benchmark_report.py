#!/usr/bin/env python3
"""Verify benchmark JSON artifacts before upload or publication.

Benchmarks are part of the product story. A green run that drops environment
metadata, category IDs, or row-level status is worse than no artifact: it invites
claims that cannot be reproduced. This checker is intentionally stdlib-only so
CI can run it immediately after generating `benchmark.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 2
KNOWN_KINDS = (
    "auto",
    "scatter-vs",
    "core-2d",
    "pyplot-vs-matplotlib",
    "scatter-native",
    "kernel-native",
    "interaction-browser",
    "dashboard-browser",
    "workflow-native",
    "line-decimation",
    "install-footprint",
)
ROW_STATUSES = ("ok", "unavailable", "skipped", "failed")
COMPARISON_VERDICTS = {"pass", "watch", "fail", "no-plotly"}
INTERACTION_BUDGET_KEYS = (
    "wheel_zoom_p95_ms",
    "pan_p95_ms",
    "crosshair_p95_ms",
    "hover_p95_ms",
    "box_zoom_p95_ms",
    "brush_select_p95_ms",
)
INTERACTION_BUDGET_LIMITS_MS = {
    "wheel_zoom_p95_ms": 600.0,
    "pan_p95_ms": 300.0,
    "crosshair_p95_ms": 300.0,
    "hover_p95_ms": 350.0,
    "box_zoom_p95_ms": 300.0,
    "brush_select_p95_ms": 200.0,
}
INTERACTION_VISUAL_BUDGET_KEYS = ("max_frame_color_delta", "min_interaction_lit_pixels")
INTERACTION_VISUAL_BUDGET_LIMITS = {
    "max_frame_color_delta": 0.85,
    "min_interaction_lit_pixels": 64.0,
}
INTERACTION_REQUIRED_SCENARIOS = (
    "direct_scatter_interaction",
    "density_scatter_interaction",
    "line_120k_interaction",
    "histogram_120k_interaction",
    "bar_1200_interaction",
    "heatmap_39600_interaction",
)
INTERACTION_REQUIRED_FAMILIES = ("line", "histogram", "bar", "heatmap")
WORKFLOW_REQUIRED_SCENARIOS = {
    "ingest_numpy_f64_contiguous",
    "ingest_numpy_f32_conversion",
    "ingest_numpy_f64_noncontiguous",
    "ingest_datetime64_axis",
    "ingest_python_lists",
    "stream_line_append_1k",
    "stream_density_append_then_pyramid_rebuild",
    "log_line_autorange",
    "export_html_decimated_line",
    "export_svg_decimated_line",
    "export_png_native_decimated_line",
}
DASHBOARD_REQUIRED_COUNTS = {10, 20, 50}
DASHBOARD_MIN_LOSS_FREE_CHARTS = 10
DASHBOARD_SMOKE_BUDGETS_MS = {
    "render_ms": 5_000.0,
    "ms_per_chart": 500.0,
    "scroll_pass_ms": 5_000.0,
    "steady_redraw_p95_ms": 100.0,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _status_kind(value: Any) -> str:
    text = str(value)
    for prefix in ROW_STATUSES:
        if text == prefix or text.startswith(f"{prefix}("):
            return prefix
    return ""


def _require_keys(obj: Any, keys: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(obj, dict):
        errors.append(f"{path} must be an object")
        return
    missing = sorted(keys - set(obj))
    if missing:
        errors.append(f"{path} missing keys: {missing}")


def _require_number(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    if not _is_number(obj.get(key)):
        errors.append(f"{path}.{key} must be a finite number")


def _require_nonnegative_number(
    obj: dict[str, Any], key: str, path: str, errors: list[str]
) -> None:
    value = obj.get(key)
    if not _is_number(value):
        errors.append(f"{path}.{key} must be a finite number")
    elif value < 0:
        errors.append(f"{path}.{key} must be >= 0")


def _require_positive_number(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = obj.get(key)
    if not _is_number(value):
        errors.append(f"{path}.{key} must be a finite number")
    elif value <= 0:
        errors.append(f"{path}.{key} must be > 0")


def _require_positive_integer(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path}.{key} must be a positive integer")
    elif value <= 0:
        errors.append(f"{path}.{key} must be > 0")


def _require_nonnegative_integer(
    obj: dict[str, Any], key: str, path: str, errors: list[str]
) -> None:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path}.{key} must be a nonnegative integer")
    elif value < 0:
        errors.append(f"{path}.{key} must be >= 0")


def _require_optional_nonnegative_number(
    obj: dict[str, Any], key: str, path: str, errors: list[str]
) -> None:
    if key not in obj or obj.get(key) is None:
        return
    _require_nonnegative_number(obj, key, path, errors)


def _require_optional_positive_integer(
    obj: dict[str, Any], key: str, path: str, errors: list[str]
) -> None:
    if key not in obj or obj.get(key) is None:
        return
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path}.{key} must be a positive integer")
    elif value <= 0:
        errors.append(f"{path}.{key} must be > 0")


def _require_string_value(
    value: Any, path: str, errors: list[str], *, allow_empty: bool = False
) -> None:
    if not isinstance(value, str):
        errors.append(f"{path} must be a string")
    elif not allow_empty and not value.strip():
        errors.append(f"{path} must be a non-empty string")


def _require_optional_string_value(value: Any, path: str, errors: list[str]) -> None:
    if value is None:
        return
    _require_string_value(value, path, errors)


def _validate_string_or_none_mapping(
    value: Any, path: str, errors: list[str], *, required_keys: set[str] | None = None
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    if required_keys:
        _require_keys(value, required_keys, path, errors)
    for key, item in value.items():
        if not isinstance(key, str):
            errors.append(f"{path} keys must be strings")
            continue
        _require_optional_string_value(item, f"{path}[{key!r}]", errors)


def _validate_environment(report: dict[str, Any], errors: list[str]) -> None:
    env = report.get("environment")
    _require_keys(
        env,
        {
            "generated_at_utc",
            "python",
            "platform",
            "cpu_count",
            "package_versions",
            "executables",
            "xy_backend",
            "browser_renderer",
            "git",
        },
        "environment",
        errors,
    )
    if not isinstance(env, dict):
        return
    if not isinstance(env.get("generated_at_utc"), str) or not env["generated_at_utc"].endswith(
        "Z"
    ):
        errors.append("environment.generated_at_utc must be an ISO UTC string ending in Z")
    cpu_count = env.get("cpu_count")
    if cpu_count is not None and (
        isinstance(cpu_count, bool) or not isinstance(cpu_count, int) or cpu_count <= 0
    ):
        errors.append("environment.cpu_count must be a positive integer or null")

    python = env.get("python")
    _require_keys(python, {"version", "implementation", "compiler"}, "python", errors)
    if isinstance(python, dict):
        for key in ("version", "implementation", "compiler"):
            _require_string_value(python.get(key), f"python.{key}", errors)

    platform = env.get("platform")
    _require_keys(
        platform,
        {"system", "release", "version", "machine", "processor"},
        "platform",
        errors,
    )
    if isinstance(platform, dict):
        for key in ("system", "release", "version", "machine"):
            _require_string_value(platform.get(key), f"platform.{key}", errors)
        _require_string_value(
            platform.get("processor"), "platform.processor", errors, allow_empty=True
        )

    _validate_string_or_none_mapping(
        env.get("package_versions"),
        "environment.package_versions",
        errors,
        required_keys={"xy"},
    )
    if env.get("browser_renderer") not in {"software-gl", "hardware"}:
        errors.append("environment.browser_renderer must be 'software-gl' or 'hardware'")
    _validate_string_or_none_mapping(
        env.get("executables"),
        "environment.executables",
        errors,
        required_keys={"node", "rustc", "cargo"},
    )

    backend = env.get("xy_backend")
    if backend not in {"native", "numpy", None}:
        errors.append("environment.xy_backend must be 'native', 'numpy', or null")

    git = env.get("git")
    _require_keys(git, {"commit", "branch", "dirty"}, "git", errors)
    if isinstance(git, dict):
        _require_optional_string_value(git.get("commit"), "git.commit", errors)
        _require_optional_string_value(git.get("branch"), "git.branch", errors)
        dirty = git.get("dirty")
        if dirty is not None and not isinstance(dirty, bool):
            errors.append("git.dirty must be a boolean or null")


def _validate_categories(report: dict[str, Any], errors: list[str]) -> set[str]:
    categories = report.get("benchmark_categories")
    tracked = report.get("tracked_categories")
    if not isinstance(categories, list) or not categories:
        errors.append("benchmark_categories must be a non-empty list")
        return set()
    category_ids: set[str] = set()
    for i, category in enumerate(categories):
        path = f"benchmark_categories[{i}]"
        _require_keys(
            category,
            {"id", "name", "why", "metrics", "harness", "status", "goal"},
            path,
            errors,
        )
        if isinstance(category, dict) and isinstance(category.get("id"), str):
            if category["id"] in category_ids:
                errors.append(f"{path}.id duplicates category id {category['id']!r}")
            category_ids.add(category["id"])
    if not isinstance(tracked, list) or not tracked:
        errors.append("tracked_categories must be a non-empty list")
        return category_ids
    for i, category in enumerate(tracked):
        path = f"tracked_categories[{i}]"
        _require_keys(category, {"id", "name", "status"}, path, errors)
        if isinstance(category, dict) and category.get("id") not in category_ids:
            errors.append(f"{path}.id {category.get('id')!r} is not in benchmark_categories")
    return category_ids


def _format_identity(keys: tuple[str, ...], identity: tuple[Any, ...]) -> str:
    return ", ".join(f"{key}={value!r}" for key, value in zip(keys, identity, strict=True))


def _reject_duplicate_rows(
    rows: list[Any],
    *,
    path: str,
    keys: tuple[str, ...],
    label: str,
    errors: list[str],
) -> None:
    seen: dict[tuple[Any, ...], int] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not all(key in row for key in keys):
            continue
        identity = tuple(row[key] for key in keys)
        first = seen.get(identity)
        if first is not None:
            errors.append(
                f"{path}[{i}] duplicates {label} from {path}[{first}]: "
                f"{_format_identity(keys, identity)}"
            )
        else:
            seen[identity] = i


def _validate_common(report: Any, errors: list[str]) -> None:
    if not isinstance(report, dict):
        errors.append("report must be a JSON object")
        return
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    _validate_environment(report, errors)


def _require_native_backend(report: dict[str, Any], kind: str, errors: list[str]) -> None:
    env = report.get("environment")
    backend = env.get("xy_backend") if isinstance(env, dict) else None
    if backend != "native":
        errors.append(
            f"{kind} reports must use environment.xy_backend == 'native'; got {backend!r}"
        )


def _detect_kind(report: dict[str, Any]) -> str:
    declared = report.get("kind")
    if declared in KNOWN_KINDS[1:]:
        return str(declared)
    if "results" in report and "ceilings" in report:
        return "scatter-vs"
    if "results" in report and "n_out" in report:
        return "line-decimation"
    if "results" in report and "repeat" in report:
        return "install-footprint"
    if "rows" in report and "comparisons" in report:
        return "core-2d"
    if "rows" in report:
        rows = report.get("rows")
        if (
            isinstance(rows, list)
            and rows
            and isinstance(rows[0], dict)
            and "encode_mpts_s" in rows[0]
        ):
            return "kernel-native"
    if "rows" in report:
        return "scatter-native"
    return "unknown"


def _validate_scatter_vs(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "sizes",
            "budget_s",
            "benchmark_categories",
            "tracked_categories",
            "results",
            "ceilings",
            "ttfr",
        },
        "report",
        errors,
    )
    _validate_categories(report, errors)
    sizes = report.get("sizes")
    if not isinstance(sizes, list) or not sizes:
        errors.append("sizes must be a non-empty list")
    else:
        for i, size in enumerate(sizes):
            if not _is_number(size):
                errors.append(f"sizes[{i}] must be a finite number")
            elif size <= 0:
                errors.append(f"sizes[{i}] must be > 0")
    if not _is_number(report.get("budget_s")):
        errors.append("budget_s must be a finite number")
    elif report["budget_s"] <= 0:
        errors.append("budget_s must be > 0")
    results = report.get("results")
    if not isinstance(results, dict) or not results:
        errors.append("results must be a non-empty object")
        return
    ceilings = report.get("ceilings")
    if not isinstance(ceilings, dict):
        errors.append("ceilings must be an object")
        ceilings = {}
    if "xy" not in results:
        errors.append("results must include xy")
    for library, rows in results.items():
        if not isinstance(rows, list) or not rows:
            errors.append(f"results[{library!r}] must be a non-empty list")
            continue
        _reject_duplicate_rows(
            rows,
            path=f"results[{library!r}]",
            keys=("n",),
            label="scatter benchmark row",
            errors=errors,
        )
        if library not in ceilings:
            errors.append(f"ceilings missing library {library!r}")
        else:
            ceiling = ceilings[library]
            if ceiling is not None:
                if not _is_number(ceiling):
                    errors.append(f"ceilings[{library!r}] must be a finite number or null")
                elif ceiling < 0:
                    errors.append(f"ceilings[{library!r}] must be >= 0")
        row_sizes = {
            row.get("n") for row in rows if isinstance(row, dict) and _is_number(row.get("n"))
        }
        if isinstance(sizes, list) and row_sizes != set(sizes):
            errors.append(
                f"results[{library!r}] sizes must exactly match report.sizes; "
                f"got {sorted(row_sizes)}, expected {sorted(sizes)}"
            )
        for i, row in enumerate(rows):
            path = f"results[{library!r}][{i}]"
            _validate_scatter_vs_row(row, path, errors)
            if isinstance(row, dict) and row.get("library") != library:
                errors.append(f"{path}.library must match enclosing results key {library!r}")
        if isinstance(ceilings, dict) and library in ceilings:
            eligible = [
                row["n"]
                for row in rows
                if isinstance(row, dict)
                and _status_kind(row.get("status")) == "ok"
                and _is_number(row.get("total_s"))
                and row["total_s"] <= report["budget_s"]
            ]
            expected_ceiling = max(eligible) if eligible else None
            if ceilings[library] != expected_ceiling:
                errors.append(
                    f"ceilings[{library!r}] must be the largest successful N within budget; "
                    f"got {ceilings[library]!r}, expected {expected_ceiling!r}"
                )


def _validate_scatter_vs_row(row: Any, path: str, errors: list[str]) -> None:
    _require_keys(row, {"n", "library", "status"}, path, errors)
    if not isinstance(row, dict):
        return
    _require_positive_number(row, "n", path, errors)
    status = _status_kind(row.get("status"))
    if not status:
        errors.append(f"{path}.status has unknown value {row.get('status')!r}")
    if status == "ok":
        _require_keys(
            row,
            {"mode", "render_target", "oracle_status", "oracle_kind"},
            path,
            errors,
        )
        if row.get("mode") not in {"direct", "density", "sampled", "adaptive"}:
            errors.append(f"{path}.mode has unknown value {row.get('mode')!r}")
        _require_string_value(row.get("render_target"), f"{path}.render_target", errors)
        if row.get("oracle_status") != "pass":
            errors.append(f"{path}.oracle_status must be 'pass'")
        _require_string_value(row.get("oracle_kind"), f"{path}.oracle_kind", errors)
        if row.get("mode") == "density":
            _require_positive_integer(row, "aggregate_width", path, errors)
            _require_positive_integer(row, "aggregate_height", path, errors)
        for key in ("build_s", "render_s", "total_s", "peak_mem_mb", "out_bytes", "pts_per_s"):
            _require_nonnegative_number(row, key, path, errors)
        for key in (
            "artifact_s",
            "browser_ready_ms",
            "browser_fcp_ms",
            "browser_js_heap_bytes",
            "browser_paint_ms",
            "ttfr_ms",
        ):
            _require_optional_nonnegative_number(row, key, path, errors)


def _validate_line_decimation(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "benchmark_categories",
            "tracked_categories",
            "sizes",
            "n_out",
            "ttfr",
            "ttfr_max_n",
            "results",
        },
        "report",
        errors,
    )
    _validate_categories(report, errors)
    sizes = report.get("sizes")
    if not isinstance(sizes, list) or not sizes:
        errors.append("sizes must be a non-empty list")
    else:
        for i, size in enumerate(sizes):
            if not _is_number(size):
                errors.append(f"sizes[{i}] must be a finite number")
            elif size <= 0:
                errors.append(f"sizes[{i}] must be > 0")
    _require_positive_number(report, "n_out", "report", errors)
    if not isinstance(report.get("ttfr"), bool):
        errors.append("report.ttfr must be a boolean")
    _require_positive_number(report, "ttfr_max_n", "report", errors)
    results = report.get("results")
    if not isinstance(results, dict) or not results:
        errors.append("results must be a non-empty object")
        return
    for library, rows in results.items():
        if not isinstance(rows, list) or not rows:
            errors.append(f"results[{library!r}] must be a non-empty list")
            continue
        _reject_duplicate_rows(
            rows,
            path=f"results[{library!r}]",
            keys=("n",),
            label="line decimation row",
            errors=errors,
        )
        for i, row in enumerate(rows):
            path = f"results[{library!r}][{i}]"
            _validate_line_decimation_row(row, path, errors)
            if isinstance(row, dict) and row.get("library") != library:
                errors.append(f"{path}.library must match enclosing results key {library!r}")


def _validate_line_decimation_row(row: Any, path: str, errors: list[str]) -> None:
    _require_keys(row, {"n", "library", "status"}, path, errors)
    if not isinstance(row, dict):
        return
    _require_positive_number(row, "n", path, errors)
    status = _status_kind(row.get("status"))
    if not status:
        errors.append(f"{path}.status has unknown value {row.get('status')!r}")
    oracle = row.get("extrema_oracle")
    if oracle is not None and oracle not in {"pass", "FAIL"}:
        errors.append(f"{path}.extrema_oracle must be 'pass' or 'FAIL'")
    if status == "ok":
        for key in ("build_s", "render_s", "total_s", "peak_mem_mb", "out_bytes", "pts_per_s"):
            _require_nonnegative_number(row, key, path, errors)
        for key in (
            "artifact_s",
            "browser_ready_ms",
            "browser_fcp_ms",
            "browser_js_heap_bytes",
            "ttfr_ms",
        ):
            _require_optional_nonnegative_number(row, key, path, errors)
        if row.get("library") == "xy" and oracle != "pass":
            errors.append(f"{path}.extrema_oracle must pass for xy")
        if row.get("library") == "xy" and row.get("oracle_kind") != ("per-pixel-column-minmax"):
            errors.append(f"{path}.oracle_kind must be 'per-pixel-column-minmax' for xy")


def _validate_install_footprint(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "benchmark_categories",
            "tracked_categories",
            "repeat",
            "fresh_venv",
            "python",
            "results",
        },
        "report",
        errors,
    )
    _validate_categories(report, errors)
    _require_positive_number(report, "repeat", "report", errors)
    if not isinstance(report.get("fresh_venv"), bool):
        errors.append("report.fresh_venv must be a boolean")
    _require_string_value(report.get("python"), "python", errors)
    results = report.get("results")
    if not isinstance(results, list) or not results:
        errors.append("results must be a non-empty list")
        return
    _reject_duplicate_rows(
        results,
        path="results",
        keys=("module", "distribution"),
        label="install footprint row",
        errors=errors,
    )
    for i, row in enumerate(results):
        path = f"results[{i}]"
        _validate_install_footprint_row(row, path, errors)
        if report.get("fresh_venv") is True and isinstance(row, dict) and row.get("status") == "ok":
            for key in ("fresh_install_ms", "fresh_cold_import_ms", "fresh_site_bytes"):
                _require_nonnegative_number(row, key, path, errors)
            for key in ("fresh_site_files", "fresh_dist_count"):
                _require_positive_integer(row, key, path, errors)


def _validate_install_footprint_row(row: Any, path: str, errors: list[str]) -> None:
    _require_keys(row, {"module", "distribution", "status"}, path, errors)
    if not isinstance(row, dict):
        return
    _require_string_value(row.get("module"), f"{path}.module", errors)
    _require_string_value(row.get("distribution"), f"{path}.distribution", errors)
    _require_optional_string_value(row.get("version"), f"{path}.version", errors)
    _require_optional_string_value(row.get("import_note"), f"{path}.import_note", errors)
    _require_optional_string_value(row.get("size_note"), f"{path}.size_note", errors)
    _require_optional_nonnegative_number(row, "cold_import_ms", path, errors)
    _require_optional_nonnegative_number(row, "dist_bytes", path, errors)
    _require_optional_positive_integer(row, "dist_files", path, errors)
    _require_optional_nonnegative_number(row, "fresh_install_ms", path, errors)
    _require_optional_nonnegative_number(row, "fresh_cold_import_ms", path, errors)
    _require_optional_nonnegative_number(row, "fresh_site_bytes", path, errors)
    _require_optional_positive_integer(row, "fresh_site_files", path, errors)
    _require_optional_positive_integer(row, "fresh_dist_count", path, errors)
    _require_optional_string_value(row.get("fresh_note"), f"{path}.fresh_note", errors)
    status = _status_kind(row.get("status"))
    if not status:
        errors.append(f"{path}.status has unknown value {row.get('status')!r}")
    if status == "ok" and row.get("cold_import_ms") is None and row.get("dist_bytes") is None:
        errors.append(f"{path} ok row must include cold_import_ms or dist_bytes")


def _validate_core_2d(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "benchmark_categories",
            "tracked_categories",
            "profile",
            "ttfr",
            "ttfr_max_work_units",
            "rows",
            "comparisons",
        },
        "report",
        errors,
    )
    _validate_categories(report, errors)
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
    else:
        _reject_duplicate_rows(
            rows,
            path="rows",
            keys=("family", "case", "work_units", "unit", "library"),
            label="core 2D row",
            errors=errors,
        )
        for i, row in enumerate(rows):
            _validate_core_2d_row(row, f"rows[{i}]", errors)
    comparisons = report.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        errors.append("comparisons must be a non-empty list")
    else:
        _reject_duplicate_rows(
            comparisons,
            path="comparisons",
            keys=("family", "case", "work_units", "unit"),
            label="core 2D comparison",
            errors=errors,
        )
        for i, comparison in enumerate(comparisons):
            _validate_core_2d_comparison(comparison, f"comparisons[{i}]", errors)


def _validate_core_2d_row(row: Any, path: str, errors: list[str]) -> None:
    _require_keys(row, {"family", "case", "work_units", "unit", "library", "status"}, path, errors)
    if not isinstance(row, dict):
        return
    _require_positive_number(row, "work_units", path, errors)
    status = _status_kind(row.get("status"))
    if not status:
        errors.append(f"{path}.status has unknown value {row.get('status')!r}")
    if status == "ok":
        _require_keys(
            row,
            {"mode", "render_target", "oracle_status", "oracle_kind"},
            path,
            errors,
        )
        if row.get("mode") not in {"direct", "decimated", "density", "sampled", "adaptive"}:
            errors.append(f"{path}.mode has unknown value {row.get('mode')!r}")
        _require_string_value(row.get("render_target"), f"{path}.render_target", errors)
        if row.get("oracle_status") != "pass":
            errors.append(f"{path}.oracle_status must be 'pass'")
        _require_string_value(row.get("oracle_kind"), f"{path}.oracle_kind", errors)
        for key in ("build_s", "payload_s", "total_s", "payload_bytes", "peak_mem_mb"):
            _require_nonnegative_number(row, key, path, errors)
        for key in (
            "html_bytes",
            "artifact_s",
            "browser_ready_ms",
            "browser_fcp_ms",
            "browser_js_heap_bytes",
            "browser_paint_ms",
            "ttfr_ms",
            "units_per_s",
        ):
            _require_optional_nonnegative_number(row, key, path, errors)


def _validate_core_2d_comparison(comparison: Any, path: str, errors: list[str]) -> None:
    _require_keys(comparison, {"family", "case", "work_units", "unit", "verdict"}, path, errors)
    if not isinstance(comparison, dict):
        return
    _require_positive_number(comparison, "work_units", path, errors)
    if comparison.get("verdict") not in COMPARISON_VERDICTS:
        errors.append(f"{path}.verdict has unknown value {comparison.get('verdict')!r}")
    for key in (
        "speedup",
        "payload_reduction",
        "ttfr_speedup",
        "seaborn_speedup",
        "seaborn_payload_reduction",
        "seaborn_ttfr_speedup",
    ):
        _require_optional_nonnegative_number(comparison, key, path, errors)
    seaborn_status = comparison.get("seaborn_status")
    if seaborn_status is not None and not _status_kind(seaborn_status):
        errors.append(f"{path}.seaborn_status has unknown value {seaborn_status!r}")


def _validate_pyplot_vs_matplotlib(report: dict[str, Any], errors: list[str]) -> None:
    _require_native_backend(report, "pyplot-vs-matplotlib", errors)
    _require_keys(
        report,
        {
            "kind",
            "benchmark_categories",
            "tracked_categories",
            "profile",
            "reps",
            "warmups",
            "pixel_target",
            "measurement_scope",
            "rows",
            "comparisons",
            "target_xy_speedup_total",
            "all_targets_met",
            "geometric_mean_xy_speedup_total",
        },
        "report",
        errors,
    )
    _validate_categories(report, errors)
    _require_string_value(report.get("profile"), "report.profile", errors)
    _require_positive_integer(report, "reps", "report", errors)
    _require_nonnegative_integer(report, "warmups", "report", errors)
    if report.get("measurement_scope") != "warmed-api-build-through-static-png":
        errors.append("report.measurement_scope must be 'warmed-api-build-through-static-png'")
    _require_positive_number(report, "geometric_mean_xy_speedup_total", "report", errors)
    _require_positive_number(report, "target_xy_speedup_total", "report", errors)
    if not isinstance(report.get("all_targets_met"), bool):
        errors.append("report.all_targets_met must be a boolean")

    pixel_target = report.get("pixel_target")
    _require_keys(pixel_target, {"width", "height", "format"}, "pixel_target", errors)
    if isinstance(pixel_target, dict):
        _require_positive_integer(pixel_target, "width", "pixel_target", errors)
        _require_positive_integer(pixel_target, "height", "pixel_target", errors)
        if pixel_target.get("format") != "png":
            errors.append("pixel_target.format must be 'png'")

    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        rows = []
    else:
        _reject_duplicate_rows(
            rows,
            path="rows",
            keys=("family", "case", "library"),
            label="pyplot comparison row",
            errors=errors,
        )
        for i, row in enumerate(rows):
            _validate_pyplot_vs_matplotlib_row(
                row,
                f"rows[{i}]",
                errors,
                expected_reps=report.get("reps"),
                pixel_target=pixel_target,
            )

    comparisons = report.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        errors.append("comparisons must be a non-empty list")
        comparisons = []
    else:
        _reject_duplicate_rows(
            comparisons,
            path="comparisons",
            keys=("family", "case"),
            label="pyplot comparison",
            errors=errors,
        )
        for i, comparison in enumerate(comparisons):
            _validate_pyplot_vs_matplotlib_comparison(comparison, f"comparisons[{i}]", errors)

    if comparisons:
        expected_all_targets_met = all(
            item.get("meets_target") is True for item in comparisons if isinstance(item, dict)
        )
        if report.get("all_targets_met") != expected_all_targets_met:
            errors.append("report.all_targets_met must match comparisons[].meets_target")
        target_speedup = report.get("target_xy_speedup_total")
        for i, comparison in enumerate(comparisons):
            if not isinstance(comparison, dict):
                continue
            if comparison.get("target_xy_speedup_total") != target_speedup:
                errors.append(
                    f"comparisons[{i}].target_xy_speedup_total must match "
                    "report.target_xy_speedup_total"
                )
            speedup = comparison.get("xy_speedup_total")
            if isinstance(speedup, (int, float)) and isinstance(target_speedup, (int, float)):
                expected_meets_target = speedup >= target_speedup
                if comparison.get("meets_target") != expected_meets_target:
                    errors.append(
                        f"comparisons[{i}].meets_target must match xy_speedup_total >= target"
                    )

    case_libraries: dict[tuple[Any, Any], set[Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            key = (row.get("family"), row.get("case"))
            case_libraries.setdefault(key, set()).add(row.get("library"))
    expected_libraries = {"xy.pyplot", "matplotlib"}
    for key, libraries in case_libraries.items():
        if libraries != expected_libraries:
            errors.append(
                f"rows for family={key[0]!r}, case={key[1]!r} must contain exactly "
                f"{sorted(expected_libraries)}; got {sorted(str(value) for value in libraries)}"
            )
    comparison_cases = {
        (item.get("family"), item.get("case")) for item in comparisons if isinstance(item, dict)
    }
    if comparison_cases != set(case_libraries):
        errors.append("comparisons must cover exactly the family/case pairs present in rows")


def _validate_pyplot_vs_matplotlib_row(
    row: Any,
    path: str,
    errors: list[str],
    *,
    expected_reps: Any,
    pixel_target: Any,
) -> None:
    _require_keys(
        row,
        {
            "family",
            "case",
            "work_units",
            "unit",
            "library",
            "status",
            "render_target",
            "mode",
            "oracle_status",
            "oracle_kind",
            "png_width",
            "png_height",
            "lit_pixels",
            "reps",
            "samples",
            "build_median_ms",
            "render_median_ms",
            "total_median_ms",
            "total_p95_ms",
            "output_bytes_median",
        },
        path,
        errors,
    )
    if not isinstance(row, dict):
        return
    _require_string_value(row.get("family"), f"{path}.family", errors)
    _require_string_value(row.get("case"), f"{path}.case", errors)
    _require_string_value(row.get("unit"), f"{path}.unit", errors)
    _require_positive_number(row, "work_units", path, errors)
    if row.get("library") not in {"xy.pyplot", "matplotlib"}:
        errors.append(f"{path}.library must be 'xy.pyplot' or 'matplotlib'")
    if row.get("status") != "ok":
        errors.append(f"{path}.status must be 'ok'")
    if row.get("render_target") != "png":
        errors.append(f"{path}.render_target must be 'png'")
    expected_mode = "native-raster" if row.get("library") == "xy.pyplot" else "agg"
    if row.get("mode") != expected_mode:
        errors.append(f"{path}.mode must be {expected_mode!r}")
    if row.get("oracle_status") != "pass":
        errors.append(f"{path}.oracle_status must be 'pass'")
    if row.get("oracle_kind") != "same-pixel-dimensions-and-nonblank":
        errors.append(f"{path}.oracle_kind must be 'same-pixel-dimensions-and-nonblank'")
    for key in (
        "build_median_ms",
        "render_median_ms",
        "total_median_ms",
        "total_p95_ms",
        "output_bytes_median",
    ):
        _require_nonnegative_number(row, key, path, errors)
    for key in ("png_width", "png_height", "lit_pixels", "reps"):
        _require_positive_integer(row, key, path, errors)
    if isinstance(expected_reps, int) and row.get("reps") != expected_reps:
        errors.append(f"{path}.reps must match report.reps ({expected_reps})")
    if isinstance(pixel_target, dict):
        if row.get("png_width") != pixel_target.get("width"):
            errors.append(f"{path}.png_width must match pixel_target.width")
        if row.get("png_height") != pixel_target.get("height"):
            errors.append(f"{path}.png_height must match pixel_target.height")
    samples = row.get("samples")
    if not isinstance(samples, list) or len(samples) != expected_reps:
        errors.append(f"{path}.samples must contain exactly report.reps entries")
        return
    for i, sample in enumerate(samples):
        sample_path = f"{path}.samples[{i}]"
        _require_keys(
            sample,
            {"build_ms", "render_ms", "total_ms", "output_bytes"},
            sample_path,
            errors,
        )
        if isinstance(sample, dict):
            for key in ("build_ms", "render_ms", "total_ms", "output_bytes"):
                _require_nonnegative_number(sample, key, sample_path, errors)


def _validate_pyplot_vs_matplotlib_comparison(
    comparison: Any, path: str, errors: list[str]
) -> None:
    _require_keys(
        comparison,
        {
            "family",
            "case",
            "work_units",
            "unit",
            "xy_speedup_total",
            "target_xy_speedup_total",
            "meets_target",
            "xy_speedup_build",
            "xy_speedup_render",
            "png_size_ratio_matplotlib_over_xy",
            "winner_total",
        },
        path,
        errors,
    )
    if not isinstance(comparison, dict):
        return
    _require_positive_number(comparison, "work_units", path, errors)
    for key in (
        "xy_speedup_total",
        "xy_speedup_build",
        "xy_speedup_render",
        "png_size_ratio_matplotlib_over_xy",
        "target_xy_speedup_total",
    ):
        _require_positive_number(comparison, key, path, errors)
    if not isinstance(comparison.get("meets_target"), bool):
        errors.append(f"{path}.meets_target must be a boolean")
    if comparison.get("winner_total") not in {"xy.pyplot", "matplotlib"}:
        errors.append(f"{path}.winner_total must be 'xy.pyplot' or 'matplotlib'")


def _validate_scatter_native(report: dict[str, Any], errors: list[str]) -> None:
    _require_native_backend(report, "scatter-native", errors)
    _require_keys(
        report,
        {"measurement_scope", "benchmark_categories", "tracked_categories", "rows"},
        "report",
        errors,
    )
    scope = report.get("measurement_scope")
    if scope not in {"native-kernel-shape", "production-figure-payload"}:
        errors.append(
            "report.measurement_scope must be 'native-kernel-shape' or 'production-figure-payload'"
        )
    category_ids = _validate_categories(report, errors)
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        return
    _reject_duplicate_rows(
        rows,
        path="rows",
        keys=("n", "tier"),
        label="scatter native row",
        errors=errors,
    )
    for i, row in enumerate(rows):
        path = f"rows[{i}]"
        _require_keys(
            row,
            {
                "n",
                "tier",
                "benchmark_categories",
                "data_prep_ms",
                "wire_bytes",
                "wire_bytes_per_point",
                "pts_per_s",
            },
            path,
            errors,
        )
        if not isinstance(row, dict):
            continue
        if row.get("tier") not in {"direct", "density"}:
            errors.append(f"{path}.tier must be 'direct' or 'density'")
        _require_positive_number(row, "n", path, errors)
        for key in ("data_prep_ms", "wire_bytes", "wire_bytes_per_point", "pts_per_s"):
            _require_nonnegative_number(row, key, path, errors)
        if scope == "production-figure-payload":
            if row.get("measurement_scope") != scope:
                errors.append(f"{path}.measurement_scope must match report.measurement_scope")
            if row.get("oracle_status") != "pass":
                errors.append(f"{path}.oracle_status must be 'pass' for production payload rows")
        categories = row.get("benchmark_categories")
        if not isinstance(categories, list) or not categories:
            errors.append(f"{path}.benchmark_categories must be a non-empty list")
        elif category_ids:
            for category_id in categories:
                if category_id not in category_ids:
                    errors.append(
                        f"{path}.benchmark_categories id {category_id!r} "
                        "is not in benchmark_categories"
                    )


def _validate_kernel_native(report: dict[str, Any], errors: list[str]) -> None:
    _require_native_backend(report, "kernel-native", errors)
    _require_keys(report, {"benchmark_categories", "tracked_categories", "rows"}, "report", errors)
    category_ids = _validate_categories(report, errors)
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        return
    _reject_duplicate_rows(
        rows,
        path="rows",
        keys=("n",),
        label="native kernel row",
        errors=errors,
    )
    for i, row in enumerate(rows):
        path = f"rows[{i}]"
        _require_keys(
            row,
            {
                "n",
                "status",
                "benchmark_categories",
                "encode_mpts_s",
                "zone_maps_mpts_s",
                "m4_full_mpts_s",
                "zoom_redecimate_ms",
                "bin_2d_mpts_s",
                "bin_2d_ms",
                "histogram_mpts_s",
                "histogram_ms",
                "normalize_mpts_s",
                "range_mpts_s",
                "range_ms",
                "local_density_n",
                "local_density_mpts_s",
                "local_density_ms",
            },
            path,
            errors,
        )
        if not isinstance(row, dict):
            continue
        _require_positive_number(row, "n", path, errors)
        if row.get("status") != "ok":
            errors.append(f"{path}.status must be 'ok'")
        for key in (
            "encode_mpts_s",
            "zone_maps_mpts_s",
            "m4_full_mpts_s",
            "zoom_redecimate_ms",
            "bin_2d_mpts_s",
            "bin_2d_ms",
            "histogram_mpts_s",
            "histogram_ms",
            "normalize_mpts_s",
            "range_mpts_s",
            "range_ms",
            "local_density_n",
            "local_density_mpts_s",
            "local_density_ms",
        ):
            _require_nonnegative_number(row, key, path, errors)
        categories = row.get("benchmark_categories")
        if not isinstance(categories, list) or not categories:
            errors.append(f"{path}.benchmark_categories must be a non-empty list")
        elif category_ids:
            for category_id in categories:
                if category_id not in category_ids:
                    errors.append(
                        f"{path}.benchmark_categories id {category_id!r} "
                        "is not in benchmark_categories"
                    )


def _validate_browser_category_list(
    row: dict[str, Any],
    path: str,
    category_ids: set[str],
    errors: list[str],
) -> None:
    categories = row.get("benchmark_categories")
    if not isinstance(categories, list) or not categories:
        errors.append(f"{path}.benchmark_categories must be a non-empty list")
    elif category_ids:
        for category_id in categories:
            if category_id not in category_ids:
                errors.append(
                    f"{path}.benchmark_categories id {category_id!r} is not in benchmark_categories"
                )


def _validate_interaction_browser(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "kind",
            "measurement_scope",
            "benchmark_categories",
            "tracked_categories",
            "rows",
            "reps",
            "tooltip_sample_count",
            "interaction_budgets_ms",
            "interaction_visual_budgets",
        },
        "report",
        errors,
    )
    if report.get("kind") != "interaction-browser":
        errors.append("report.kind must be 'interaction-browser'")
    if report.get("measurement_scope") != "standalone-client-input-to-pixel-readback":
        errors.append(
            "report.measurement_scope must be 'standalone-client-input-to-pixel-readback'"
        )
    _require_positive_integer(report, "reps", "report", errors)
    declared_reps = report.get("reps") if isinstance(report.get("reps"), int) else None
    _require_positive_integer(report, "tooltip_sample_count", "report", errors)
    declared_tooltip_samples = (
        report.get("tooltip_sample_count")
        if isinstance(report.get("tooltip_sample_count"), int)
        else None
    )
    budgets = _validate_interaction_budget_block(report, errors)
    visual_budgets = _validate_interaction_visual_budget_block(report, errors)
    category_ids = _validate_categories(report, errors)
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        return
    _reject_duplicate_rows(
        rows,
        path="rows",
        keys=("scenario", "n"),
        label="interaction browser row",
        errors=errors,
    )
    for i, row in enumerate(rows):
        path = f"rows[{i}]"
        _require_keys(
            row,
            {
                "scenario",
                "n",
                "tier",
                "benchmark_categories",
                "payload_bytes",
                "html_bytes",
                "status",
            },
            path,
            errors,
        )
        if not isinstance(row, dict):
            continue
        _require_positive_number(row, "n", path, errors)
        if row.get("tier") not in {"direct", "density", "decimated"}:
            errors.append(f"{path}.tier must be 'direct', 'density', or 'decimated'")
        family = row.get("family")
        if family is not None:
            _require_string_value(family, f"{path}.family", errors)
        for key in ("payload_bytes", "html_bytes"):
            _require_nonnegative_number(row, key, path, errors)
        status = _status_kind(row.get("status"))
        if not status:
            errors.append(f"{path}.status has unknown value {row.get('status')!r}")
        _validate_browser_category_list(row, path, category_ids, errors)
        if status == "ok":
            _require_positive_number(row, "nonblank_pixels", path, errors)
            _require_positive_number(row, "min_interaction_lit_pixels", path, errors)
            _require_nonnegative_number(row, "blank_frame_count", path, errors)
            if _is_number(row.get("blank_frame_count")) and row["blank_frame_count"] != 0:
                errors.append(f"{path}.blank_frame_count must be 0")
            _require_positive_number(row, "label_count", path, errors)
            _require_nonnegative_number(row, "tick_label_overlap_count", path, errors)
            if (
                _is_number(row.get("tick_label_overlap_count"))
                and row["tick_label_overlap_count"] != 0
            ):
                errors.append(f"{path}.tick_label_overlap_count must be 0")
            _require_nonnegative_number(row, "max_frame_color_delta", path, errors)
            for metric, budget in visual_budgets.items():
                value = row.get(metric)
                if not _is_number(value):
                    continue
                if metric.startswith("max_") and value > budget:
                    errors.append(f"{path}.{metric} {value:.3g} exceeds budget {budget:.3g}")
                elif metric.startswith("min_") and value < budget:
                    errors.append(f"{path}.{metric} {value:.3g} is below budget {budget:.3g}")
            if not isinstance(row.get("view_changed"), bool):
                errors.append(f"{path}.view_changed must be a boolean")
            elif not row["view_changed"]:
                errors.append(f"{path}.view_changed must be true for an interaction probe")
            if not isinstance(row.get("crosshair_visible"), bool):
                errors.append(f"{path}.crosshair_visible must be a boolean")
            elif not row["crosshair_visible"]:
                errors.append(f"{path}.crosshair_visible must be true")
            for key in ("box_zoom_changed", "box_zoom_narrowed", "box_zoom_restored"):
                if not isinstance(row.get(key), bool):
                    errors.append(f"{path}.{key} must be a boolean")
                elif not row[key]:
                    errors.append(f"{path}.{key} must be true")
            if not isinstance(row.get("brush_select_eligible"), bool):
                errors.append(f"{path}.brush_select_eligible must be a boolean")
            _require_nonnegative_number(row, "brush_select_count", path, errors)
            if not isinstance(row.get("brush_select_cleared"), bool):
                errors.append(f"{path}.brush_select_cleared must be a boolean")
            elif not row["brush_select_cleared"]:
                errors.append(f"{path}.brush_select_cleared must be true")
            if (
                row.get("brush_select_eligible") is True
                and _is_number(row.get("brush_select_count"))
                and row["brush_select_count"] <= 0
            ):
                errors.append(
                    f"{path}.brush_select_count must be > 0 when brush_select_eligible is true"
                )
            if not isinstance(row.get("tooltip_eligible"), bool):
                errors.append(f"{path}.tooltip_eligible must be a boolean")
            if not isinstance(row.get("tooltip_stable"), bool):
                errors.append(f"{path}.tooltip_stable must be a boolean")
            elif not row["tooltip_stable"]:
                errors.append(f"{path}.tooltip_stable must be true")
            _require_nonnegative_number(row, "tooltip_visible_samples", path, errors)
            if (
                row.get("tooltip_eligible") is True
                and _is_number(row.get("tooltip_visible_samples"))
                and declared_tooltip_samples is not None
                and row["tooltip_visible_samples"] != declared_tooltip_samples
            ):
                errors.append(
                    f"{path}.tooltip_visible_samples must equal report.tooltip_sample_count "
                    f"{declared_tooltip_samples} when eligible, got "
                    f"{row['tooltip_visible_samples']!r}"
                )
            for prefix in ("wheel_zoom", "pan", "hover", "crosshair", "box_zoom", "brush_select"):
                for suffix in ("median_ms", "p95_ms", "p99_ms", "max_ms"):
                    _require_nonnegative_number(row, f"{prefix}_{suffix}", path, errors)
                reps_key = f"{prefix}_reps"
                _require_positive_integer(row, reps_key, path, errors)
                if declared_reps is not None and row.get(reps_key) != declared_reps:
                    errors.append(
                        f"{path}.{reps_key} must match report.reps "
                        f"{declared_reps}, got {row.get(reps_key)!r}"
                    )
            for metric, budget in budgets.items():
                value = row.get(metric)
                if _is_number(value) and value > budget:
                    errors.append(f"{path}.{metric} {value:.3g} ms exceeds budget {budget:.3g} ms")

    ok_rows = [
        row for row in rows if isinstance(row, dict) and _status_kind(row.get("status")) == "ok"
    ]
    ok_scenarios = {str(row.get("scenario")) for row in ok_rows}
    missing_scenarios = sorted(set(INTERACTION_REQUIRED_SCENARIOS) - ok_scenarios)
    if missing_scenarios:
        errors.append(f"interaction report missing required ok scenarios: {missing_scenarios}")
    ok_families = {
        str(row.get("family"))
        for row in ok_rows
        if isinstance(row.get("family"), str) and row.get("family")
    }
    missing_families = sorted(set(INTERACTION_REQUIRED_FAMILIES) - ok_families)
    if missing_families:
        errors.append(f"interaction report missing required ok families: {missing_families}")


def _validate_interaction_budget_block(
    report: dict[str, Any], errors: list[str]
) -> dict[str, float]:
    budgets = report.get("interaction_budgets_ms")
    if not isinstance(budgets, dict):
        errors.append("report.interaction_budgets_ms must be an object")
        return {}
    missing = [key for key in INTERACTION_BUDGET_KEYS if key not in budgets]
    if missing:
        errors.append(f"report.interaction_budgets_ms missing keys: {missing}")
    extra = sorted(set(budgets) - set(INTERACTION_BUDGET_KEYS))
    if extra:
        errors.append(f"report.interaction_budgets_ms has unknown keys: {extra}")
    valid: dict[str, float] = {}
    for key in INTERACTION_BUDGET_KEYS:
        value = budgets.get(key)
        if not _is_number(value):
            errors.append(f"report.interaction_budgets_ms.{key} must be a finite number")
        elif value <= 0:
            errors.append(f"report.interaction_budgets_ms.{key} must be > 0")
        else:
            valid[key] = float(value)
            limit = INTERACTION_BUDGET_LIMITS_MS[key]
            if value > limit:
                errors.append(
                    f"report.interaction_budgets_ms.{key} may not exceed the gate limit "
                    f"{limit:g} ms"
                )
    return valid


def _validate_interaction_visual_budget_block(
    report: dict[str, Any], errors: list[str]
) -> dict[str, float]:
    budgets = report.get("interaction_visual_budgets")
    if not isinstance(budgets, dict):
        errors.append("report.interaction_visual_budgets must be an object")
        return {}
    missing = [key for key in INTERACTION_VISUAL_BUDGET_KEYS if key not in budgets]
    if missing:
        errors.append(f"report.interaction_visual_budgets missing keys: {missing}")
    extra = sorted(set(budgets) - set(INTERACTION_VISUAL_BUDGET_KEYS))
    if extra:
        errors.append(f"report.interaction_visual_budgets has unknown keys: {extra}")
    valid: dict[str, float] = {}
    for key in INTERACTION_VISUAL_BUDGET_KEYS:
        value = budgets.get(key)
        if not _is_number(value):
            errors.append(f"report.interaction_visual_budgets.{key} must be a finite number")
        elif key.startswith("max_") and (value <= 0 or value > 1):
            errors.append(f"report.interaction_visual_budgets.{key} must be > 0 and <= 1")
        elif key.startswith("min_") and value <= 0:
            errors.append(f"report.interaction_visual_budgets.{key} must be > 0")
        else:
            valid[key] = float(value)
            limit = INTERACTION_VISUAL_BUDGET_LIMITS[key]
            if key.startswith("max_") and value > limit:
                errors.append(
                    f"report.interaction_visual_budgets.{key} may not exceed the gate limit "
                    f"{limit:g}"
                )
            elif key.startswith("min_") and value < limit:
                errors.append(
                    f"report.interaction_visual_budgets.{key} may not be below the gate floor "
                    f"{limit:g}"
                )
    return valid


def _validate_dashboard_browser(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "kind",
            "benchmark_categories",
            "tracked_categories",
            "attempted_chart_counts",
            "chart_count_ceiling",
            "visible_stable_chart_ceiling",
            "rows",
        },
        "report",
        errors,
    )
    if report.get("kind") != "dashboard-browser":
        errors.append("report.kind must be 'dashboard-browser'")
    category_ids = _validate_categories(report, errors)
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        return
    _reject_duplicate_rows(
        rows,
        path="rows",
        keys=("scenario", "chart_count"),
        label="dashboard browser row",
        errors=errors,
    )
    for i, row in enumerate(rows):
        path = f"rows[{i}]"
        _require_keys(
            row,
            {
                "scenario",
                "chart_count",
                "benchmark_categories",
                "total_payload_bytes",
                "html_bytes",
                "status",
            },
            path,
            errors,
        )
        if not isinstance(row, dict):
            continue
        _require_positive_number(row, "chart_count", path, errors)
        for key in ("total_payload_bytes", "html_bytes"):
            _require_nonnegative_number(row, key, path, errors)
        status = _status_kind(row.get("status"))
        if not status:
            errors.append(f"{path}.status has unknown value {row.get('status')!r}")
        _validate_browser_category_list(row, path, category_ids, errors)
        if status == "ok":
            _require_keys(
                row,
                {
                    "render_status",
                    "fully_nonblank",
                    "render_ms",
                    "ms_per_chart",
                    "payload_prep_ms",
                    "navigation_ready_ms",
                    "scroll_pass_ms",
                    "steady_redraw_p95_ms",
                    "steady_redraw_active_charts",
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
                },
                path,
                errors,
            )
            for key in (
                "render_ms",
                "ms_per_chart",
                "payload_prep_ms",
                "navigation_ready_ms",
                "scroll_pass_ms",
                "scroll_recovery_p95_ms",
                "steady_redraw_p95_ms",
            ):
                _require_nonnegative_number(row, key, path, errors)
            for key in (
                "steady_redraw_active_charts",
                "created_charts",
                "creation_failed_charts",
                "nonblank_charts",
                "initial_nonblank_charts",
                "scroll_nonblank_charts",
                "context_lost_events",
                "context_restored_events",
                "governed_context_lost_events",
            ):
                _require_nonnegative_integer(row, key, path, errors)
            for key in ("js_heap_before_bytes", "js_heap_bytes"):
                _require_optional_nonnegative_number(row, key, path, errors)
            delta = row.get("js_heap_delta_bytes")
            if delta is not None and not _is_number(delta):
                errors.append(f"{path}.js_heap_delta_bytes must be a finite number or null")
            _validate_dashboard_telemetry(row, path, errors)
    attempted_counts = {row.get("chart_count") for row in rows if isinstance(row, dict)}
    missing_counts = sorted(DASHBOARD_REQUIRED_COUNTS - attempted_counts)
    if missing_counts:
        errors.append(f"dashboard report missing required attempted chart counts: {missing_counts}")
    declared_attempts = report.get("attempted_chart_counts")
    if not isinstance(declared_attempts, list) or set(declared_attempts) != attempted_counts:
        errors.append("report.attempted_chart_counts must match dashboard row chart counts")
    ok_counts = {
        row.get("chart_count")
        for row in rows
        if isinstance(row, dict)
        and _status_kind(row.get("status")) == "ok"
        and row.get("fully_nonblank") is True
    }
    expected_ceiling = max(ok_counts) if ok_counts else None
    if report.get("chart_count_ceiling") != expected_ceiling:
        errors.append(
            "report.chart_count_ceiling must be the largest successful chart_count; "
            f"got {report.get('chart_count_ceiling')!r}, expected {expected_ceiling!r}"
        )
    visible_counts = {
        row.get("chart_count")
        for row in rows
        if isinstance(row, dict)
        and _status_kind(row.get("status")) == "ok"
        and row.get("render_status") in {"complete", "governed"}
    }
    expected_visible = max(visible_counts) if visible_counts else None
    if report.get("visible_stable_chart_ceiling") != expected_visible:
        errors.append(
            "report.visible_stable_chart_ceiling must be the largest complete-or-governed "
            f"chart_count; got {report.get('visible_stable_chart_ceiling')!r}, "
            f"expected {expected_visible!r}"
        )
    if not isinstance(expected_ceiling, int) or expected_ceiling < DASHBOARD_MIN_LOSS_FREE_CHARTS:
        errors.append(
            "dashboard must render at least "
            f"{DASHBOARD_MIN_LOSS_FREE_CHARTS} charts without loss or blank frames"
        )
    smoke_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("chart_count") == DASHBOARD_MIN_LOSS_FREE_CHARTS
    ]
    if len(smoke_rows) == 1:
        smoke = smoke_rows[0]
        if _status_kind(smoke.get("status")) != "ok" or smoke.get("fully_nonblank") is not True:
            errors.append(
                f"dashboard {DASHBOARD_MIN_LOSS_FREE_CHARTS}-chart smoke row must be "
                "loss-free and fully nonblank"
            )
        for metric, limit in DASHBOARD_SMOKE_BUDGETS_MS.items():
            value = smoke.get(metric)
            if _is_number(value) and value > limit:
                errors.append(
                    f"dashboard {DASHBOARD_MIN_LOSS_FREE_CHARTS}-chart {metric} "
                    f"{value:.3g} ms exceeds hard smoke budget {limit:.3g} ms"
                )


def _dashboard_id_list(
    row: dict[str, Any], key: str, path: str, expected_ids: set[str], errors: list[str]
) -> set[str]:
    value = row.get(key)
    if not isinstance(value, list):
        errors.append(f"{path}.{key} must be a list")
        return set()
    if any(not isinstance(item, str) for item in value):
        errors.append(f"{path}.{key} must contain only strings")
        return set()
    ids = set(value)
    if len(ids) != len(value):
        errors.append(f"{path}.{key} must not contain duplicate chart IDs")
    unknown = sorted(ids - expected_ids)
    if unknown:
        errors.append(f"{path}.{key} contains unknown chart IDs: {unknown}")
    return ids


def _validate_dashboard_telemetry(row: dict[str, Any], path: str, errors: list[str]) -> None:
    chart_count = row.get("chart_count")
    if isinstance(chart_count, bool) or not isinstance(chart_count, int) or chart_count <= 0:
        return
    expected_ids = {f"chart-{i}" for i in range(chart_count)}
    id_keys = (
        "creation_failure_ids",
        "initial_nonblank_chart_ids",
        "initial_blank_chart_ids",
        "scroll_nonblank_chart_ids",
        "scroll_blank_chart_ids",
        "context_lost_chart_ids",
        "context_restored_chart_ids",
        "currently_lost_chart_ids",
        "released_chart_ids",
        "evicted_chart_ids",
    )
    ids = {key: _dashboard_id_list(row, key, path, expected_ids, errors) for key in id_keys}

    count_keys = (
        "steady_redraw_active_charts",
        "created_charts",
        "creation_failed_charts",
        "nonblank_charts",
        "initial_nonblank_charts",
        "scroll_nonblank_charts",
    )
    for key in count_keys:
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > chart_count:
            errors.append(f"{path}.{key} must be <= chart_count")

    expected_pairs = (
        ("creation_failed_charts", "creation_failure_ids"),
        ("initial_nonblank_charts", "initial_nonblank_chart_ids"),
        ("scroll_nonblank_charts", "scroll_nonblank_chart_ids"),
    )
    for count_key, ids_key in expected_pairs:
        if row.get(count_key) != len(ids[ids_key]):
            errors.append(f"{path}.{count_key} must equal len({ids_key})")
    if row.get("nonblank_charts") != row.get("initial_nonblank_charts"):
        errors.append(f"{path}.nonblank_charts must equal initial_nonblank_charts")
    if row.get("created_charts") != chart_count - len(ids["creation_failure_ids"]):
        errors.append(f"{path}.created_charts must equal chart_count minus creation failures")
    if row.get("steady_redraw_active_charts") != row.get("created_charts", 0) - len(
        ids["currently_lost_chart_ids"]
    ):
        errors.append(
            f"{path}.steady_redraw_active_charts must equal created charts minus currently lost"
        )

    for prefix in ("initial", "scroll"):
        lit = ids[f"{prefix}_nonblank_chart_ids"]
        blank = ids[f"{prefix}_blank_chart_ids"]
        if lit & blank:
            errors.append(f"{path}.{prefix} nonblank and blank chart IDs must be disjoint")
        if lit | blank != expected_ids:
            errors.append(f"{path}.{prefix} chart IDs must cover every attempted chart")

    events = row.get("context_events")
    lost_event_ids: list[str] = []
    restored_event_ids: list[str] = []
    if not isinstance(events, list):
        errors.append(f"{path}.context_events must be a list")
        events = []
    for index, event in enumerate(events):
        event_path = f"{path}.context_events[{index}]"
        _require_keys(event, {"id", "type", "phase", "at_ms"}, event_path, errors)
        if not isinstance(event, dict):
            continue
        event_id = event.get("id")
        if event_id not in expected_ids:
            errors.append(f"{event_path}.id must identify an attempted chart")
        event_type = event.get("type")
        if event_type not in {"lost", "restored"}:
            errors.append(f"{event_path}.type must be 'lost' or 'restored'")
        elif isinstance(event_id, str):
            (lost_event_ids if event_type == "lost" else restored_event_ids).append(event_id)
        if event.get("phase") not in {"create", "initial", "scroll", "redraw", "report"}:
            errors.append(f"{event_path}.phase has an unknown value")
        _require_nonnegative_number(event, "at_ms", event_path, errors)

    if row.get("context_lost_events") != len(lost_event_ids):
        errors.append(f"{path}.context_lost_events must equal lost context event count")
    if row.get("context_restored_events") != len(restored_event_ids):
        errors.append(f"{path}.context_restored_events must equal restored context event count")
    if ids["context_lost_chart_ids"] != set(lost_event_ids):
        errors.append(f"{path}.context_lost_chart_ids must match context_events")
    if ids["context_restored_chart_ids"] != set(restored_event_ids):
        errors.append(f"{path}.context_restored_chart_ids must match context_events")
    known_lost_ids = (
        ids["context_lost_chart_ids"] | ids["released_chart_ids"] | ids["evicted_chart_ids"]
    )
    if not ids["currently_lost_chart_ids"] <= known_lost_ids:
        errors.append(
            f"{path}.currently_lost_chart_ids must be a subset of context-lost, "
            "released, or evicted chart IDs"
        )

    governed_lost = row.get("governed_context_lost_events")
    if (
        isinstance(governed_lost, int)
        and not isinstance(governed_lost, bool)
        and isinstance(row.get("context_lost_events"), int)
        and governed_lost > row.get("context_lost_events")
    ):
        errors.append(f"{path}.governed_context_lost_events must be <= context_lost_events")
    # Governed releases and browser evictions partition the still-lost set.
    if (
        not (ids["released_chart_ids"] | ids["evicted_chart_ids"])
        <= ids["currently_lost_chart_ids"] | ids["context_lost_chart_ids"]
    ):
        errors.append(f"{path}.released/evicted chart IDs must come from context-lost charts")

    expected_complete = (
        row.get("created_charts") == chart_count
        and row.get("initial_nonblank_charts") == chart_count
        and row.get("scroll_nonblank_charts") == chart_count
        and row.get("context_lost_events") == 0
        and not ids["currently_lost_chart_ids"]
    )
    if not isinstance(row.get("fully_nonblank"), bool):
        errors.append(f"{path}.fully_nonblank must be a boolean")
    elif row.get("fully_nonblank") != expected_complete:
        errors.append(f"{path}.fully_nonblank is inconsistent with dashboard telemetry")
    # "governed": every chart created and nonblank while visited, and every
    # context loss was a governed (recoverable) release — the dashboard is
    # fully usable above the context budget.
    expected_governed = (
        not expected_complete
        and row.get("created_charts") == chart_count
        and row.get("scroll_nonblank_charts") == chart_count
        and row.get("governed_context_lost_events") == row.get("context_lost_events")
    )
    expected_status = (
        "complete" if expected_complete else "governed" if expected_governed else "partial"
    )
    if row.get("render_status") != expected_status:
        errors.append(f"{path}.render_status must be {expected_status!r}")


def _validate_workflow_native(report: dict[str, Any], errors: list[str]) -> None:
    _require_native_backend(report, "workflow-native", errors)
    _require_keys(
        report,
        {"kind", "profile", "reps", "benchmark_categories", "tracked_categories", "rows"},
        "report",
        errors,
    )
    if report.get("kind") != "workflow-native":
        errors.append("report.kind must be 'workflow-native'")
    if report.get("profile") not in {"smoke", "standard"}:
        errors.append("report.profile must be 'smoke' or 'standard'")
    _require_positive_integer(report, "reps", "report", errors)
    category_ids = _validate_categories(report, errors)
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        return
    _reject_duplicate_rows(
        rows,
        path="rows",
        keys=("scenario",),
        label="workflow benchmark row",
        errors=errors,
    )
    for i, row in enumerate(rows):
        path = f"rows[{i}]"
        _require_keys(
            row,
            {
                "scenario",
                "family",
                "n",
                "reps",
                "median_ms",
                "p95_ms",
                "max_ms",
                "output_bytes",
                "peak_python_mb",
                "scope",
                "oracle_status",
                "benchmark_categories",
                "status",
            },
            path,
            errors,
        )
        if not isinstance(row, dict):
            continue
        _require_string_value(row.get("scenario"), f"{path}.scenario", errors)
        if row.get("family") not in {"ingestion", "streaming", "range", "export"}:
            errors.append(f"{path}.family has unknown value {row.get('family')!r}")
        _require_positive_number(row, "n", path, errors)
        _require_positive_integer(row, "reps", path, errors)
        for key in ("median_ms", "p95_ms", "max_ms", "output_bytes", "peak_python_mb"):
            _require_nonnegative_number(row, key, path, errors)
        if row.get("family") == "ingestion":
            _require_nonnegative_number(row, "ingest_copies", path, errors)
            _require_positive_number(row, "canonical_bytes", path, errors)
        _require_string_value(row.get("scope"), f"{path}.scope", errors)
        if row.get("oracle_status") != "pass":
            errors.append(f"{path}.oracle_status must be 'pass'")
        if row.get("status") != "ok":
            errors.append(f"{path}.status must be 'ok'")
        _validate_browser_category_list(row, path, category_ids, errors)
    scenarios = {
        str(row.get("scenario"))
        for row in rows
        if isinstance(row, dict) and row.get("status") == "ok"
    }
    missing = sorted(WORKFLOW_REQUIRED_SCENARIOS - scenarios)
    if missing:
        errors.append(f"workflow report missing required ok scenarios: {missing}")


def _report_rows(report: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    if kind in {"scatter-vs", "line-decimation"}:
        results = report.get("results")
        if not isinstance(results, dict):
            return []
        return [
            row
            for rows in results.values()
            if isinstance(rows, list)
            for row in rows
            if isinstance(row, dict)
        ]
    if kind == "install-footprint":
        rows = report.get("results")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    rows = report.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        text = str(value)
        counts[text] = counts.get(text, 0) + 1
    return counts


def _count_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = _status_kind(row.get("status"))
        if not status:
            continue
        counts[status] = counts.get(status, 0) + 1
    return counts


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}:{counts[key]}" for key in sorted(counts))


def summarize_report(report: dict[str, Any], *, kind: str) -> list[str]:
    """Return compact, stable summary lines for CI/local verifier output."""
    rows = _report_rows(report, kind)
    categories = report.get("benchmark_categories")
    tracked = report.get("tracked_categories")
    env = report.get("environment") if isinstance(report.get("environment"), dict) else {}
    git = env.get("git") if isinstance(env.get("git"), dict) else {}

    summary = [
        f"kind: {kind}",
        f"rows: {len(rows)}",
    ]

    status_counts = _count_statuses(rows)
    if status_counts:
        summary.append(f"statuses: {_format_counts(status_counts)}")
    tier_counts = _count_values(rows, "tier")
    if tier_counts:
        summary.append(f"tiers: {_format_counts(tier_counts)}")
    library_counts = _count_values(rows, "library")
    if library_counts:
        summary.append(f"libraries: {_format_counts(library_counts)}")

    if isinstance(categories, list):
        summary.append(f"benchmark_categories: {len(categories)}")
    if isinstance(tracked, list):
        summary.append(f"tracked_categories: {len(tracked)}")
    if env.get("xy_backend") is not None:
        summary.append(f"backend: {env['xy_backend']}")
    commit = git.get("commit")
    if isinstance(commit, str) and commit:
        suffix = " dirty" if git.get("dirty") is True else ""
        summary.append(f"git: {commit[:12]}{suffix}")
    return summary


def validate_report(path: Path, *, kind: str = "auto") -> list[str]:
    errors: list[str] = []
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read benchmark report: {exc}"]
    _validate_common(report, errors)
    if not isinstance(report, dict):
        return errors

    detected = _detect_kind(report)
    selected = detected if kind == "auto" else kind
    if selected == "scatter-vs":
        _validate_scatter_vs(report, errors)
    elif selected == "line-decimation":
        _validate_line_decimation(report, errors)
    elif selected == "install-footprint":
        _validate_install_footprint(report, errors)
    elif selected == "core-2d":
        _validate_core_2d(report, errors)
    elif selected == "pyplot-vs-matplotlib":
        _validate_pyplot_vs_matplotlib(report, errors)
    elif selected == "scatter-native":
        _validate_scatter_native(report, errors)
    elif selected == "kernel-native":
        _validate_kernel_native(report, errors)
    elif selected == "interaction-browser":
        _validate_interaction_browser(report, errors)
    elif selected == "dashboard-browser":
        _validate_dashboard_browser(report, errors)
    elif selected == "workflow-native":
        _validate_workflow_native(report, errors)
    else:
        errors.append(f"unknown benchmark report kind: {detected!r}")
    if kind != "auto" and detected != kind:
        errors.append(f"expected {kind!r} report, detected {detected!r}")
    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--kind", choices=KNOWN_KINDS, default="auto")
    args = parser.parse_args(argv)

    errors = validate_report(args.report, kind=args.kind)
    if errors:
        print(f"benchmark report verification failed for {args.report}:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"benchmark report verification OK: {args.report}")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    detected = _detect_kind(report)
    selected = detected if args.kind == "auto" else args.kind
    for line in summarize_report(report, kind=selected):
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
