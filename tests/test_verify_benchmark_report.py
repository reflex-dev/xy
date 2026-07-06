from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_verify_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_benchmark_report.py"
    spec = importlib.util.spec_from_file_location("verify_benchmark_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_benchmark_report = _load_verify_module()
DELETE = object()


def _environment() -> dict:
    return {
        "generated_at_utc": "2026-07-04T12:00:00Z",
        "python": {"version": "3.11.9", "implementation": "CPython", "compiler": "Clang"},
        "platform": {
            "system": "Darwin",
            "release": "25.0.0",
            "version": "Darwin Kernel",
            "machine": "arm64",
            "processor": "arm",
        },
        "cpu_count": 10,
        "package_versions": {"fastcharts": "0.1.0", "numpy": "2.0.0"},
        "executables": {"node": "v22.0.0", "rustc": "rustc 1.96.1", "cargo": "cargo 1.96.1"},
        "fastcharts_backend": "native",
        "git": {"commit": "abc123", "branch": "main", "dirty": False},
    }


def _category(category_id: str = "small_data_startup") -> dict:
    return {
        "id": category_id,
        "name": "Small-data startup",
        "why": "why",
        "metrics": "TTFR",
        "harness": "benchmarks/bench_vs.py",
        "status": "tracked",
        "goal": "goal",
    }


def _write_report(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base() -> dict:
    return {"schema_version": 2, "environment": _environment()}


def _category_registry(*ids: str) -> tuple[list[dict], list[dict]]:
    categories = [_category(category_id) for category_id in ids]
    return categories, categories


def _scatter_vs_report() -> dict:
    categories, tracked = _category_registry("small_data_startup")
    row = {
        "n": 1000,
        "library": "fastcharts",
        "status": "ok",
        "build_s": 0.001,
        "render_s": 0.002,
        "total_s": 0.003,
        "peak_mem_mb": 1.0,
        "out_bytes": 8192,
        "pts_per_s": 333333.0,
    }
    return {
        **_base(),
        "sizes": [1000],
        "budget_s": 45.0,
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "results": {"fastcharts": [row]},
        "ceilings": {"fastcharts": 1000},
        "ttfr": False,
    }


def _core_2d_report() -> dict:
    categories, tracked = _category_registry("core_2d_chart_breadth", "payload_export_size")
    return {
        **_base(),
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "profile": "smoke",
        "ttfr": False,
        "ttfr_max_work_units": 50_000,
        "rows": [
            {
                "family": "bar",
                "case": "1,000 categories",
                "work_units": 1000,
                "unit": "bars",
                "library": "fastcharts",
                "status": "ok",
                "build_s": 0.001,
                "payload_s": 0.002,
                "total_s": 0.003,
                "payload_bytes": 4096,
                "peak_mem_mb": 1.0,
            },
            {
                "family": "bar",
                "case": "1,000 categories",
                "work_units": 1000,
                "unit": "bars",
                "library": "seaborn",
                "status": "ok",
                "build_s": 0.010,
                "payload_s": 0.020,
                "total_s": 0.030,
                "payload_bytes": 8192,
                "peak_mem_mb": 2.0,
                "artifact_status": "raster",
            },
        ],
        "comparisons": [
            {
                "family": "bar",
                "case": "1,000 categories",
                "work_units": 1000,
                "unit": "bars",
                "verdict": "pass",
                "seaborn_status": "ok",
                "seaborn_speedup": 10.0,
                "seaborn_payload_reduction": 2.0,
            }
        ],
    }


def _scatter_native_report() -> dict:
    categories, tracked = _category_registry("medium_direct_scatter", "huge_scatter_overview")
    return {
        **_base(),
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "rows": [
            {
                "n": 1000,
                "tier": "direct",
                "benchmark_categories": ["medium_direct_scatter"],
                "data_prep_ms": 0.1,
                "wire_bytes": 8000,
                "wire_bytes_per_point": 8.0,
                "pts_per_s": 10_000_000.0,
            }
        ],
    }


def _line_decimation_report() -> dict:
    categories, tracked = _category_registry("huge_line_time_series", "payload_export_size")
    row = {
        "n": 100_000,
        "library": "fastcharts",
        "status": "ok",
        "build_s": 0.001,
        "render_s": 0.002,
        "total_s": 0.003,
        "peak_mem_mb": 1.0,
        "out_bytes": 8192,
        "pts_per_s": 33_333_333.0,
        "extrema_oracle": "pass",
    }
    return {
        **_base(),
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "sizes": [100_000],
        "n_out": 2000,
        "results": {"fastcharts": [row]},
    }


def _install_footprint_report() -> dict:
    categories, tracked = _category_registry(
        "install_footprint_import_budget", "payload_export_size"
    )
    return {
        **_base(),
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "repeat": 5,
        "python": "3.11.9",
        "results": [
            {
                "module": "fastcharts",
                "distribution": "fastcharts",
                "version": "0.1.0",
                "cold_import_ms": 12.5,
                "import_note": None,
                "dist_bytes": 1024,
                "dist_files": 12,
                "size_note": None,
                "status": "ok",
            }
        ],
    }


def _kernel_native_report() -> dict:
    categories, tracked = _category_registry(
        "huge_line_time_series",
        "huge_scatter_overview",
        "core_2d_chart_breadth",
        "interaction_smoothness",
    )
    row = {
        "n": 1_000_000,
        "status": "ok",
        "benchmark_categories": ["huge_line_time_series", "huge_scatter_overview"],
        "encode_mpts_s": 1000.0,
        "zone_maps_mpts_s": 900.0,
        "m4_full_mpts_s": 800.0,
        "zoom_redecimate_ms": 0.5,
        "bin_2d_mpts_s": 700.0,
        "bin_2d_ms": 1.5,
        "histogram_mpts_s": 600.0,
        "histogram_ms": 2.5,
        "normalize_mpts_s": 500.0,
        "range_mpts_s": 400.0,
        "range_ms": 3.5,
        "local_density_n": 200_000,
        "local_density_mpts_s": 300.0,
        "local_density_ms": 4.5,
    }
    return {
        **_base(),
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "rows": [row],
    }


def _interaction_browser_report() -> dict:
    categories, tracked = _category_registry(
        "medium_direct_scatter",
        "huge_scatter_overview",
        "interaction_smoothness",
    )
    return {
        **_base(),
        "kind": "interaction-browser",
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "reps": 12,
        "rows": [
            {
                "scenario": "direct_scatter_interaction",
                "n": 100_000,
                "tier": "direct",
                "benchmark_categories": ["medium_direct_scatter", "interaction_smoothness"],
                "payload_bytes": 8192,
                "html_bytes": 16_384,
                "status": "ok",
                "nonblank_pixels": 128,
                "view_changed": True,
                "wheel_zoom_median_ms": 4.0,
                "wheel_zoom_p95_ms": 7.0,
                "wheel_zoom_max_ms": 9.0,
                "wheel_zoom_reps": 12,
                "pan_median_ms": 3.0,
                "pan_p95_ms": 6.0,
                "pan_max_ms": 7.0,
                "pan_reps": 12,
                "hover_median_ms": 2.0,
                "hover_p95_ms": 5.0,
                "hover_max_ms": 6.0,
                "hover_reps": 12,
                "box_zoom_median_ms": 4.0,
                "box_zoom_p95_ms": 8.0,
                "box_zoom_max_ms": 10.0,
                "box_zoom_reps": 12,
            }
        ],
    }


def _dashboard_browser_report() -> dict:
    categories, tracked = _category_registry(
        "many_chart_dashboards",
        "small_data_startup",
        "payload_export_size",
    )
    return {
        **_base(),
        "kind": "dashboard-browser",
        "benchmark_categories": categories,
        "tracked_categories": tracked,
        "rows": [
            {
                "scenario": "dashboard_20",
                "chart_count": 20,
                "benchmark_categories": [
                    "many_chart_dashboards",
                    "small_data_startup",
                    "payload_export_size",
                ],
                "total_payload_bytes": 262_144,
                "html_bytes": 524_288,
                "status": "ok",
                "render_ms": 140.0,
                "ms_per_chart": 7.0,
                "nonblank_charts": 20,
            }
        ],
    }


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (_scatter_vs_report(), "scatter-vs"),
        (_core_2d_report(), "core-2d"),
        (_scatter_native_report(), "scatter-native"),
        (_kernel_native_report(), "kernel-native"),
        (_interaction_browser_report(), "interaction-browser"),
        (_dashboard_browser_report(), "dashboard-browser"),
        (_line_decimation_report(), "line-decimation"),
        (_install_footprint_report(), "install-footprint"),
    ],
)
def test_verify_benchmark_report_accepts_known_shapes(
    tmp_path: Path, payload: dict, kind: str
) -> None:
    path = _write_report(tmp_path, payload)

    assert verify_benchmark_report.validate_report(path, kind=kind) == []
    assert verify_benchmark_report.validate_report(path, kind="auto") == []


def test_benchmark_report_summary_names_shape_and_environment() -> None:
    payload = _scatter_vs_report()

    summary = verify_benchmark_report.summarize_report(payload, kind="scatter-vs")

    assert "kind: scatter-vs" in summary
    assert "rows: 1" in summary
    assert "statuses: ok:1" in summary
    assert "libraries: fastcharts:1" in summary
    assert "benchmark_categories: 1" in summary
    assert "tracked_categories: 1" in summary
    assert "backend: native" in summary
    assert "git: abc123" in summary


def test_benchmark_report_summary_groups_status_detail_by_status_class() -> None:
    payload = _scatter_vs_report()
    skipped = dict(payload["results"]["fastcharts"][0])
    skipped["n"] = 2000
    skipped["status"] = "skipped(no playwright)"
    payload["results"]["fastcharts"].append(skipped)

    summary = verify_benchmark_report.summarize_report(payload, kind="scatter-vs")

    assert "statuses: ok:1, skipped:1" in summary


def test_verify_benchmark_report_cli_success_prints_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_report(tmp_path, _scatter_native_report())

    rc = verify_benchmark_report.main([str(path), "--kind", "scatter-native"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "benchmark report verification OK" in out
    assert "kind: scatter-native" in out
    assert "rows: 1" in out
    assert "tiers: direct:1" in out
    assert "backend: native" in out


def test_verify_benchmark_report_rejects_missing_environment(tmp_path: Path) -> None:
    payload = _scatter_vs_report()
    del payload["environment"]
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path)

    assert any("environment" in error for error in errors)


@pytest.mark.parametrize(
    ("path_parts", "value", "expected"),
    [
        (("environment", "cpu_count"), 0, "environment.cpu_count"),
        (("environment", "python", "version"), "", "python.version"),
        (("environment", "platform", "machine"), 42, "platform.machine"),
        (("environment", "package_versions", "fastcharts"), DELETE, "package_versions"),
        (("environment", "package_versions", "numpy"), 2.0, "package_versions['numpy']"),
        (("environment", "executables", "node"), DELETE, "executables"),
        (("environment", "executables", "cargo"), 123, "executables['cargo']"),
        (("environment", "fastcharts_backend"), "wasm", "fastcharts_backend"),
        (("environment", "git", "dirty"), "false", "git.dirty"),
    ],
)
def test_verify_benchmark_report_rejects_vague_environment_metadata(
    tmp_path: Path,
    path_parts: tuple[str, ...],
    value: object,
    expected: str,
) -> None:
    payload = _scatter_vs_report()
    target = payload
    for part in path_parts[:-1]:
        target = target[part]
    if value is DELETE:
        del target[path_parts[-1]]
    else:
        target[path_parts[-1]] = value
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path)

    assert any(expected in error for error in errors)


def test_verify_benchmark_report_rejects_missing_category_registry(tmp_path: Path) -> None:
    payload = _scatter_vs_report()
    payload["benchmark_categories"] = []
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path)

    assert any("benchmark_categories" in error for error in errors)


@pytest.mark.parametrize(
    ("payload", "kind"),
    [(_core_2d_report(), "core-2d"), (_scatter_native_report(), "scatter-native")],
)
def test_verify_benchmark_report_rejects_missing_category_registry_for_all_json_reports(
    tmp_path: Path, payload: dict, kind: str
) -> None:
    del payload["tracked_categories"]
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind=kind)

    assert any("tracked_categories" in error for error in errors)


def test_verify_benchmark_report_rejects_unknown_row_category(tmp_path: Path) -> None:
    payload = _scatter_native_report()
    payload["rows"][0]["benchmark_categories"] = ["not_registered"]
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="scatter-native")

    assert any("not_registered" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_category_ids(tmp_path: Path) -> None:
    payload = _core_2d_report()
    payload["benchmark_categories"].append(dict(payload["benchmark_categories"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="core-2d")

    assert any("duplicates category id" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_scatter_vs_rows(tmp_path: Path) -> None:
    payload = _scatter_vs_report()
    payload["results"]["fastcharts"].append(dict(payload["results"]["fastcharts"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="scatter-vs")

    assert any("duplicates scatter benchmark row" in error for error in errors)
    assert any("n=1000" in error for error in errors)


def test_verify_benchmark_report_rejects_scatter_vs_bucket_mismatch(tmp_path: Path) -> None:
    payload = _scatter_vs_report()
    payload["results"]["fastcharts"][0]["library"] = "plotly"
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="scatter-vs")

    assert any("must match enclosing results key 'fastcharts'" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_core_2d_rows(tmp_path: Path) -> None:
    payload = _core_2d_report()
    payload["rows"].append(dict(payload["rows"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="core-2d")

    assert any("duplicates core 2D row" in error for error in errors)
    assert any("library='fastcharts'" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_core_2d_comparisons(
    tmp_path: Path,
) -> None:
    payload = _core_2d_report()
    payload["comparisons"].append(dict(payload["comparisons"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="core-2d")

    assert any("duplicates core 2D comparison" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_scatter_native_rows(tmp_path: Path) -> None:
    payload = _scatter_native_report()
    payload["rows"].append(dict(payload["rows"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="scatter-native")

    assert any("duplicates scatter native row" in error for error in errors)
    assert any("tier='direct'" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_kernel_native_rows(tmp_path: Path) -> None:
    payload = _kernel_native_report()
    payload["rows"].append(dict(payload["rows"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="kernel-native")

    assert any("duplicates native kernel row" in error for error in errors)
    assert any("n=1000000" in error for error in errors)


def test_verify_benchmark_report_rejects_unknown_kernel_native_row_category(
    tmp_path: Path,
) -> None:
    payload = _kernel_native_report()
    payload["rows"][0]["benchmark_categories"] = ["not_registered"]
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="kernel-native")

    assert any("not_registered" in error for error in errors)


def test_verify_benchmark_report_rejects_failed_fastcharts_line_oracle(
    tmp_path: Path,
) -> None:
    payload = _line_decimation_report()
    payload["results"]["fastcharts"][0]["extrema_oracle"] = "FAIL"
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="line-decimation")

    assert any("extrema_oracle must pass" in error for error in errors)


def test_verify_benchmark_report_rejects_duplicate_install_rows(tmp_path: Path) -> None:
    payload = _install_footprint_report()
    payload["results"].append(dict(payload["results"][0]))
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="install-footprint")

    assert any("duplicates install footprint row" in error for error in errors)
    assert any("module='fastcharts'" in error for error in errors)


def test_verify_benchmark_report_rejects_ok_row_missing_metrics(tmp_path: Path) -> None:
    payload = _core_2d_report()
    del payload["rows"][0]["payload_bytes"]
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="core-2d")

    assert any("payload_bytes" in error for error in errors)


def test_verify_benchmark_report_rejects_nan_metrics(tmp_path: Path) -> None:
    payload = _core_2d_report()
    payload["rows"][0]["total_s"] = float("nan")
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="core-2d")

    assert any("rows[0].total_s must be a finite number" in error for error in errors)


def test_verify_benchmark_report_rejects_infinite_optional_metrics(tmp_path: Path) -> None:
    payload = _scatter_vs_report()
    payload["results"]["fastcharts"][0]["ttfr_ms"] = float("inf")
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="scatter-vs")

    assert any("ttfr_ms must be a finite number" in error for error in errors)


def test_verify_benchmark_report_rejects_negative_metrics(tmp_path: Path) -> None:
    payload = _core_2d_report()
    payload["rows"][0]["payload_bytes"] = -1
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="core-2d")

    assert any("rows[0].payload_bytes must be >= 0" in error for error in errors)


def test_verify_benchmark_report_rejects_non_positive_work_size(tmp_path: Path) -> None:
    payload = _scatter_vs_report()
    payload["sizes"] = [0]
    path = _write_report(tmp_path, payload)

    errors = verify_benchmark_report.validate_report(path, kind="scatter-vs")

    assert any("sizes[0] must be > 0" in error for error in errors)


def test_verify_benchmark_report_rejects_kind_mismatch(tmp_path: Path) -> None:
    path = _write_report(tmp_path, _scatter_native_report())

    errors = verify_benchmark_report.validate_report(path, kind="scatter-vs")

    assert any("expected 'scatter-vs'" in error for error in errors)
