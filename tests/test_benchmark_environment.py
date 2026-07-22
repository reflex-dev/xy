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
        xy_backend="native",
        package_names=("definitely-not-installed-xy-test-package",),
        now=datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
        root=tmp_path,
        command_runner=runner,
    )

    assert SCHEMA_VERSION == 2
    assert metadata["generated_at_utc"] == "2026-07-04T12:00:00Z"
    assert metadata["python"]["version"]
    assert metadata["platform"]["system"]
    assert metadata["cpu_count"] is None or metadata["cpu_count"] > 0
    assert metadata["package_versions"]["definitely-not-installed-xy-test-package"] is None
    assert metadata["xy_backend"] == "native"
    assert metadata["browser_renderer"] == "software-gl"
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
        "PYRAMID_N = 2_100_000",
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
        "test_marching_squares",
        "test_bin_2d_indices",
        "test_min_max",
        "test_sample_mask",
        "test_pyramid_build",
        "test_pyramid_count",
        "test_pyramid_compose",
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
        "test_first_payload_statistical_core_2d",
        "test_first_payload_hexbin_core_2d",
        "test_first_payload_errorbar_large",
        "test_first_payload_contour_core_2d",
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


def test_codspeed_dependency_is_declared_and_shared_by_ci_and_runbook() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "codspeed.yml").read_text(encoding="utf-8")
    runbook = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")

    assert "codspeed = [" in pyproject
    assert '"pytest-codspeed>=5,<6"' in pyproject
    assert '-e ".[dev,codspeed]"' in workflow
    assert '-e ".[dev,codspeed]"' in runbook
    assert "--codspeed" in runbook


def test_native_benchmark_reports_can_resolve_source_backend_metadata() -> None:
    """Early CI native scripts run before package install, but still need backend metadata."""
    for script_name in ("bench_scatter_native.py", "bench_native.py"):
        source = (ROOT / "benchmarks" / script_name).read_text(encoding="utf-8")
        python_path = 'sys.path.insert(0, str(ROOT / "python"))'
        assert python_path in source
        assert source.index(python_path) < source.index("from environment import")
        assert 'xy_backend="native"' in source


def test_scatter_native_exposes_reproducible_categorical_ceiling() -> None:
    source = (ROOT / "benchmarks" / "bench_scatter_native.py").read_text(encoding="utf-8")
    runbook = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
    assert "def gen_numpy_categories" in source
    assert "def _warm_production_path" in source
    assert '"--categorical-groups"' in source
    assert '"categorical_groups"' in source
    assert "--categorical-groups 24" in runbook


def test_interaction_browser_gates_cover_scatter_and_core_chart_families() -> None:
    smoke = (ROOT / "scripts" / "interaction_stress_smoke.py").read_text(encoding="utf-8")
    bench = (ROOT / "benchmarks" / "bench_interaction.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'parser.add_argument("--sizes", default="1e4,2.5e5")' in smoke
    assert "--sizes 1e4,2.5e5 --reps 24" in workflow
    required_markers = [
        "_core_interaction_figures",
        "line_120k_interaction",
        "histogram_120k_interaction",
        "bar_1200_interaction",
        "heatmap_39600_interaction",
        "run_worker_probe",
        "omits Chromium's virtual-time flag",
        "WORKER_PROBE_TIMEOUT_S = 60",
        '"family": "line"',
        '"family": "histogram"',
        '"family": "bar"',
        '"family": "heatmap"',
        "interaction regressions are not scatter-only",
    ]
    for marker in required_markers:
        assert marker in bench
    assert 'startswith("skipped(")' in smoke


def test_interaction_benchmark_completes_gpu_warmup_before_timing() -> None:
    bench = (ROOT / "benchmarks" / "bench_interaction.py").read_text(encoding="utf-8")
    warm_start = bench.index("// Warm shader compilation")
    timing_start = bench.index("let viewChanged = false", warm_start)
    settle_start = bench.index("function settlePixels()", timing_start)
    settle_end = bench.index("function measure(", settle_start)

    assert "settlePixels();" in bench[warm_start:timing_start]
    assert "cancelAnimationFrame(view._raf);" in bench[settle_start:settle_end]
    assert "gl.readPixels(" in bench[settle_start:settle_end]


def test_dashboard_benchmark_reports_eviction_and_scroll_telemetry() -> None:
    bench = (ROOT / "benchmarks" / "bench_dashboard.py").read_text(encoding="utf-8")

    for marker in (
        'addEventListener("webglcontextlost"',
        'addEventListener("webglcontextrestored"',
        "scrollIntoView",
        "context_lost_chart_ids",
        "context_restored_chart_ids",
        "initial_nonblank_chart_ids",
        "scroll_nonblank_chart_ids",
        "scroll_recovery_p95_ms",
        "governed_context_lost_events",
        "released_chart_ids",
        'render_status: fullyNonblank ? "complete" : governedHealth ? "governed" : "partial"',
    ):
        assert marker in bench
    assert "blank dashboard chart" not in bench
    assert "slot.state.lost ||" not in bench
    assert "slot.view._glLost || slot.view.gl.isContextLost()" in bench

    # webglcontextlost dispatches as a task, so the probe must yield before
    # leaving the "create" phase or creation-loop evictions get mislabeled
    # with whatever phase is current when the queued events finally fire.
    creation_loop = bench.index('addEventListener("webglcontextlost"')
    first_yield = bench.index(
        "await new Promise((resolve) => setTimeout(resolve, 0));", creation_loop
    )
    phase_initial = bench.index('phase = "initial";', creation_loop)
    assert first_yield < phase_initial


def test_context_governor_reserves_pending_restores() -> None:
    """Concurrent visibility callbacks must count restores before their
    asynchronous ``webglcontextrestored`` events acquire the contexts."""
    client = (ROOT / "js" / "src" / "50_chartview.ts").read_text(encoding="utf-8")

    assert "view._ctxPendingReservation" in client
    constructor = client[client.index("  constructor(") : client.index("  _listen<")]
    assert 'this.root.textContent = "xy: WebGL2 unavailable in this browser.";' in constructor
    init_gl = client[
        client.index("  _initGl(buffer: PayloadBuffers) {") : client.index("  _buildTrace(")
    ]
    assert "WebGL2 unavailable in this browser" not in init_gl
    recover = client.index("  _recoverContext() {")
    reserve = client.index("XY_CONTEXT_GOVERNOR.reserve(this);", recover)
    restore = client.index("ext.restoreContext();", recover)
    assert reserve < restore

    snapshot = client[client.index("_snapshotBeforeRelease()") : recover]
    draw = snapshot.index("this._drawNow();")
    finish = snapshot.index("gl.finish();")
    read = snapshot.index("gl.readPixels(")
    assert draw < finish < read
    assert "drawImage(this.canvas" not in snapshot
    release_start = client.index("  _releaseContext() {")
    release_end = client.index("  _snapshotBeforeRelease() {", release_start + 1)
    release = client[release_start:release_end]
    assert release.index("this._snapshotBeforeRelease();") < release.index("ext.loseContext();")

    # A native browser eviction can happen while a chart is already visible
    # (for example when other tabs consume Chrome's process-wide GL budget).
    # It must not wait for an IntersectionObserver transition that may never
    # arrive, while governed releases should remain snapshot/demand driven.
    loss_handler = client[
        client.index('this._listen(this.canvas, "webglcontextlost"') : client.index(
            'this._listen(this.canvas, "webglcontextrestored"'
        )
    ]
    assert "!governedRelease && this._ctxVisible && documentVisible" in loss_handler
    assert 'this.canvas.dataset.xyCtx === "lost"' in loss_handler
    assert "this._recoverContext();" in loss_handler

    visibility_start = client.index("  _armContextVisibilityWatch() {")
    visibility_watch = client[
        visibility_start : client.index("  _resize(cssW: number, cssH: number)", visibility_start)
    ]
    assert 'this._listen(document, "visibilitychange"' in visibility_watch
    assert 'document.visibilityState === "hidden"' in visibility_watch
    assert "XY_CONTEXT_GOVERNOR.scheduleHiddenReleases();" in visibility_watch
    assert "XY_CONTEXT_GOVERNOR.cancelHiddenReleases();" in visibility_watch
    hidden_release = client[: client.index("// Initial visibility estimate")]
    assert "const channel = new MessageChannel();" in hidden_release
    assert "channel.port2.postMessage(null);" in hidden_release
    assert "view._releaseContext();" in hidden_release
    assert 'document.visibilityState === "visible"' in visibility_watch
    assert "this._recoverContext();" in visibility_watch

    # Recovery is transactional: a freshly created context must paint its
    # real mark programs successfully before the snapshot is dropped or the
    # canvas advertises itself as live. Transient process-wide pressure stays
    # retryable instead of surfacing a null-log pick-shader exception.
    restored_start = client.index('this._listen(this.canvas, "webglcontextrestored"')
    restored = client[restored_start:release_start]
    assert restored.index("this._drawNow();") < restored.index(
        'this.canvas.dataset.xyCtx = "live";'
    )
    assert restored.index('this._assertContextFrameReady("restore");') < restored.index(
        'this.canvas.dataset.xyCtx = "live";'
    )
    assert restored.index('this.canvas.dataset.xyCtx = "live";') < restored.index(
        "this._dropContextSnapshot();"
    )
    assert 'includes("shader compile: null")' in restored
    assert "this._scheduleContextRecovery();" in restored

    pick_start = client.index("  _pickAt(cssX: number, cssY: number) {")
    pick = client[pick_start : client.index("  _decodeValue(", pick_start)]
    assert "this.gl.isContextLost()" in pick
    assert "if (!this.gl || this.gl.isContextLost()) return null;" in pick


def test_triangle_mesh_resource_cleanup_deletes_every_coordinate_buffer() -> None:
    client = (ROOT / "js" / "src" / "50_chartview.ts").read_text(encoding="utf-8")
    cleanup = client[
        client.index("_destroyTraceResources(g: GpuTrace, texSeen: Set<WebGLTexture>)") :
    ]
    cleanup = cleanup[: cleanup.index("_destroyGlResources()")]
    for name in ("x0Buf", "x1Buf", "x2Buf", "y0Buf", "y1Buf", "y2Buf"):
        assert f'"{name}"' in cleanup


def test_benchmark_categories_track_core_hardening_metrics() -> None:
    medium_scatter_metrics = CATEGORY_BY_ID["medium_direct_scatter"]["metrics"]
    interaction_metrics = CATEGORY_BY_ID["interaction_smoothness"]["metrics"]
    log_metrics = CATEGORY_BY_ID["log_autorange"]["metrics"]

    assert "memory" in medium_scatter_metrics
    assert "bytes/point" in medium_scatter_metrics
    assert "tooltip stability" in interaction_metrics
    assert "frame color delta" in interaction_metrics
    assert "positive-domain correctness" in log_metrics
