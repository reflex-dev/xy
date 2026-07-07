from __future__ import annotations

import ast
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.categories import CATEGORY_BY_ID
from benchmarks.environment import SCHEMA_VERSION, collect_environment_metadata

ROOT = Path(__file__).resolve().parents[1]


def test_collect_environment_metadata_is_machine_readable(tmp_path: Path) -> None:
    def runner(command: Sequence[str], cwd: Path | None, timeout_s: float) -> str | None:
        del timeout_s
        command_tuple = tuple(command)
        if command_tuple == ("node", "--version"):
            return "v20.11.1"
        if command_tuple == ("rustc", "--version"):
            return "rustc 1.96.1"
        if command_tuple == ("cargo", "--version"):
            return "cargo 1.96.1"
        if command_tuple == ("/Applications/Chromium", "--version"):
            return "Chromium 126.0.0"
        if command_tuple == ("git", "rev-parse", "HEAD") and cwd == tmp_path:
            return "abc123"
        if command_tuple == ("git", "rev-parse", "--abbrev-ref", "HEAD") and cwd == tmp_path:
            return "main"
        if command_tuple == ("git", "status", "--porcelain") and cwd == tmp_path:
            return " M benchmarks/environment.py"
        return None

    metadata = collect_environment_metadata(
        chromium="/Applications/Chromium",
        package_names=("definitely-not-installed-fastcharts-test-package",),
        now=datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
        root=tmp_path,
        command_runner=runner,
    )

    assert SCHEMA_VERSION == 2
    assert metadata["generated_at_utc"] == "2026-07-04T12:00:00Z"
    assert metadata["python"]["version"]
    assert metadata["platform"]["system"]
    assert metadata["cpu_count"] is None or metadata["cpu_count"] > 0
    assert metadata["package_versions"]["definitely-not-installed-fastcharts-test-package"] is None
    assert metadata["executables"] == {
        "node": "v20.11.1",
        "rustc": "rustc 1.96.1",
        "cargo": "cargo 1.96.1",
        "chromium": "Chromium 126.0.0",
    }
    assert metadata["git"] == {"commit": "abc123", "branch": "main", "dirty": True}


def test_codspeed_suite_covers_native_core_hardening_workloads() -> None:
    source = (ROOT / "benchmarks" / "test_codspeed_kernels.py").read_text(encoding="utf-8")
    required_markers = [
        "SMALL_N = 10_000",
        "MEDIUM_N = 100_000",
        "N = LARGE_N = 1_000_000",
        "HIST_N = 100_000",
        "AREA_N = 100_000",
        "BAR_N = 1_000",
        "HEATMAP_W, HEATMAP_H = 160, 120",
        "require_native_backend",
        'k.BACKEND == "native"',
    ]
    for marker in required_markers:
        assert marker in source

    module = ast.parse(source)
    functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    required_benchmarks = {
        "test_zone_maps",
        "test_encode_f32",
        "test_m4_indices_full",
        "test_m4_indices_zoom",
        "test_bin_2d",
        "test_histogram_uniform",
        "test_normalize_f32",
        "test_range_indices",
        "test_first_payload_scatter_small",
        "test_first_payload_scatter_medium",
        "test_first_payload_line_large",
        "test_first_payload_density_large",
        "test_memory_report_density_medium",
        "test_first_payload_histogram_core_2d",
        "test_first_payload_area_core_2d",
        "test_first_payload_bar_core_2d",
        "test_first_payload_heatmap_core_2d",
        "test_first_payload_composed_layered_core_2d",
        "test_build_payload",
        "test_decimate_view",
        "test_adaptive_drilldown_cycle",
    }
    missing = sorted(required_benchmarks - set(functions))
    assert missing == []

    for name in sorted(required_benchmarks):
        args = {arg.arg for arg in functions[name].args.args}
        assert "benchmark" in args, f"{name} must be timed by pytest-codspeed"


def test_native_benchmark_reports_can_resolve_source_backend_metadata() -> None:
    """Early CI native scripts run before package install, but still need backend metadata."""
    for script_name in ("bench_scatter_native.py", "bench_native.py"):
        source = (ROOT / "benchmarks" / script_name).read_text(encoding="utf-8")
        python_path = 'sys.path.insert(0, str(ROOT / "python"))'
        assert python_path in source
        assert source.index(python_path) < source.index("from environment import")


def test_interaction_browser_gates_cover_scatter_and_core_chart_families() -> None:
    smoke = (ROOT / "scripts" / "interaction_stress_smoke.py").read_text(encoding="utf-8")
    bench = (ROOT / "benchmarks" / "bench_interaction.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'parser.add_argument("--sizes", default="1e4,2.5e5")' in smoke
    assert "--sizes 1e4,2.5e5 --reps 8" in workflow
    required_markers = [
        "_core_interaction_figures",
        "line_120k_interaction",
        "histogram_120k_interaction",
        "bar_1200_interaction",
        "heatmap_39600_interaction",
        '"family": "line"',
        '"family": "histogram"',
        '"family": "bar"',
        '"family": "heatmap"',
        "interaction regressions are not scatter-only",
    ]
    for marker in required_markers:
        assert marker in bench


def test_benchmark_categories_track_core_hardening_metrics() -> None:
    medium_scatter_metrics = CATEGORY_BY_ID["medium_direct_scatter"]["metrics"]
    interaction_metrics = CATEGORY_BY_ID["interaction_smoothness"]["metrics"]

    assert "memory" in medium_scatter_metrics
    assert "bytes/point" in medium_scatter_metrics
    assert "tooltip stability" in interaction_metrics
    assert "frame color delta" in interaction_metrics
