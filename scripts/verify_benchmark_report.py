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
    "scatter-native",
    "kernel-native",
    "interaction-browser",
    "dashboard-browser",
    "line-decimation",
    "install-footprint",
)
ROW_STATUSES = ("ok", "unavailable", "skipped", "failed")
COMPARISON_VERDICTS = {"pass", "watch", "fail", "no-plotly"}


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
            "fastcharts_backend",
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
        required_keys={"fastcharts"},
    )
    _validate_string_or_none_mapping(
        env.get("executables"),
        "environment.executables",
        errors,
        required_keys={"node", "rustc", "cargo"},
    )

    backend = env.get("fastcharts_backend")
    if backend not in {"native", "numpy", None}:
        errors.append("environment.fastcharts_backend must be 'native', 'numpy', or null")

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


def _detect_kind(report: dict[str, Any]) -> str:
    declared = report.get("kind")
    if declared in {"interaction-browser", "dashboard-browser"}:
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
        for i, row in enumerate(rows):
            path = f"results[{library!r}][{i}]"
            _validate_scatter_vs_row(row, path, errors)
            if isinstance(row, dict) and row.get("library") != library:
                errors.append(f"{path}.library must match enclosing results key {library!r}")


def _validate_scatter_vs_row(row: Any, path: str, errors: list[str]) -> None:
    _require_keys(row, {"n", "library", "status"}, path, errors)
    if not isinstance(row, dict):
        return
    _require_positive_number(row, "n", path, errors)
    status = _status_kind(row.get("status"))
    if not status:
        errors.append(f"{path}.status has unknown value {row.get('status')!r}")
    if status == "ok":
        for key in ("build_s", "render_s", "total_s", "peak_mem_mb", "out_bytes", "pts_per_s"):
            _require_nonnegative_number(row, key, path, errors)
        for key in ("browser_paint_ms", "ttfr_ms"):
            _require_optional_nonnegative_number(row, key, path, errors)


def _validate_line_decimation(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "benchmark_categories",
            "tracked_categories",
            "sizes",
            "n_out",
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
        if row.get("library") == "fastcharts" and oracle != "pass":
            errors.append(f"{path}.extrema_oracle must pass for fastcharts")


def _validate_install_footprint(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {
            "benchmark_categories",
            "tracked_categories",
            "repeat",
            "python",
            "results",
        },
        "report",
        errors,
    )
    _validate_categories(report, errors)
    _require_positive_number(report, "repeat", "report", errors)
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
        _validate_install_footprint_row(row, f"results[{i}]", errors)


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
        for key in ("build_s", "payload_s", "total_s", "payload_bytes", "peak_mem_mb"):
            _require_nonnegative_number(row, key, path, errors)
        for key in ("html_bytes", "browser_paint_ms", "ttfr_ms", "units_per_s"):
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


def _validate_scatter_native(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(report, {"benchmark_categories", "tracked_categories", "rows"}, "report", errors)
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
                    f"{path}.benchmark_categories id {category_id!r} "
                    "is not in benchmark_categories"
                )


def _validate_interaction_browser(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {"kind", "benchmark_categories", "tracked_categories", "rows", "reps"},
        "report",
        errors,
    )
    if report.get("kind") != "interaction-browser":
        errors.append("report.kind must be 'interaction-browser'")
    _require_positive_number(report, "reps", "report", errors)
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
        if row.get("tier") not in {"direct", "density"}:
            errors.append(f"{path}.tier must be 'direct' or 'density'")
        for key in ("payload_bytes", "html_bytes"):
            _require_nonnegative_number(row, key, path, errors)
        status = _status_kind(row.get("status"))
        if not status:
            errors.append(f"{path}.status has unknown value {row.get('status')!r}")
        _validate_browser_category_list(row, path, category_ids, errors)
        if status == "ok":
            _require_positive_number(row, "nonblank_pixels", path, errors)
            if not isinstance(row.get("view_changed"), bool):
                errors.append(f"{path}.view_changed must be a boolean")
            for prefix in ("wheel_zoom", "pan", "hover", "box_zoom"):
                for suffix in ("median_ms", "p95_ms", "max_ms"):
                    _require_nonnegative_number(row, f"{prefix}_{suffix}", path, errors)
                _require_positive_number(row, f"{prefix}_reps", path, errors)


def _validate_dashboard_browser(report: dict[str, Any], errors: list[str]) -> None:
    _require_keys(
        report,
        {"kind", "benchmark_categories", "tracked_categories", "rows"},
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
            for key in ("render_ms", "ms_per_chart"):
                _require_nonnegative_number(row, key, path, errors)
            _require_positive_number(row, "nonblank_charts", path, errors)


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
    if env.get("fastcharts_backend") is not None:
        summary.append(f"backend: {env['fastcharts_backend']}")
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
    elif selected == "scatter-native":
        _validate_scatter_native(report, errors)
    elif selected == "kernel-native":
        _validate_kernel_native(report, errors)
    elif selected == "interaction-browser":
        _validate_interaction_browser(report, errors)
    elif selected == "dashboard-browser":
        _validate_dashboard_browser(report, errors)
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
