from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
from pathlib import Path
from typing import Optional, Union

import pytest

INDEX_JS = (
    "class ChartView {}\n"
    "function render() {}\n"
    "function renderStandalone() {}\n"
    "function decodeFrame() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "export { render, renderStandalone, decodeFrame, ChartView };\n"
)
STANDALONE_JS = (
    "class ChartView {}\n"
    "function render() {}\n"
    "function renderStandalone() {}\n"
    "function decodeFrame() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "window.xy = { render, renderStandalone, decodeFrame, ChartView };\n"
)
ENTRIES_JS = (
    "function render() {}\n"
    "function renderStandalone() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "// ---- exports ----\n"
)
README_MD = (
    "# xy\n\n"
    "## Stable vs. Experimental\n\n"
    "Python 3.11+ package import is documented here.\n"
    "See docs/engineering/api-examples.md for examples.\n"
    "Run make check-examples after editing example docs.\n" + ("readme padding\n" * 100)
)
API_EXAMPLES_MD = (
    "# API Examples\n\n"
    "## Chart Family Quick Reference\n\n"
    "| Chart family | Fluent API | Composition API |\n"
    "|---|---|---|\n"
    "| Heatmap | `Figure().heatmap(z, x=x, y=y)` | `xy.heatmap_chart(xy.heatmap(...))` |\n"
    "\n## Small Business Chart\n\n"
    "Revenue vs pipeline\n" + ("api examples padding\n" * 100)
)
BENCHMARK_MD = (
    "# Benchmark\n\n"
    "The docs/benchmark_ci.md numbers land in the benchmark-report artifact.\n"
    "The docs/engineering/benchmark_metrics.md regression table, scatter.json, and kernel.json "
    "land in the regression-benchmark-report artifact.\n" + ("benchmark padding\n" * 100)
)
PRODUCTION_READINESS_MD = (
    "# Production Readiness\n\n"
    "## Release-Blocking Gates\n\n"
    "`import xy` stays lightweight.\n"
    "Use `make check-artifacts` for exact artifact verification.\n"
    "Use `make check-examples` for docs and Reflex app checks.\n"
    "The sdist includes the Reflex example app, while wheels stay package-only. "
    "Docs, tests, benchmarks, scripts, and examples/reflex are sdist-only.\n"
    "Run scripts/verify_benchmark_report.py, scripts/verify_wheel.py, and "
    "scripts/verify_sdist.py before releases.\n" + ("production readiness padding\n" * 100)
)
CONTRIBUTING_MD = (
    "# Contributing\n\n"
    "## Pull Request Checklist\n\n"
    "Run make check-full, make check-sdist, make check-wheel, and "
    "make check-benchmark-report.\n"
    "Run make check-examples for README snippets, docs/engineering/api-examples.md, and "
    "the Reflex example app.\n\n"
    "## Performance Claims\n\n"
    "Claims need benchmark context.\n" + ("contributing padding\n" * 100)
)
REFLEX_README_MD = (
    "# xy Reflex Example\n\n"
    "Run python scripts/build_charts.py before reflex run.\n\n"
    "| Chart | File | What it shows |\n"
    "|---|---|---|\n"
    "| Business overview | `assets/charts/business_overview.html` | Small grouped columns |\n"
    + ("reflex readme padding\n" * 100)
)
BUSINESS_OVERVIEW_HTML = (
    "<!doctype html><html><head><title>Small business overview</title></head>"
    "<body><script>xy.renderStandalone({title: 'Small business overview'});</script>"
    "<span>Revenue</span><span>Pipeline</span>"
    + ("business html padding\n" * 100)
    + "</body></html>"
)
CI_YML = (
    "name: CI\n"
    "jobs:\n"
    "  benchmark:\n"
    "    continue-on-error: true\n"
    "    steps:\n"
    "      - run: python scripts/verify_ci_workflow.py\n"
    "      - uses: actions/upload-artifact@v4\n" + ("ci workflow padding\n" * 100)
)
CODSPEED_YML = (
    "name: CodSpeed\n"
    "jobs:\n"
    "  benchmarks:\n"
    "    steps:\n"
    "      - uses: CodSpeedHQ/action@v4\n"
    "      - run: uv pip install pytest-codspeed\n"
    "      - run: python -c 'import xy.kernels as k; assert k.BACKEND == \"native\"'\n"
    + ("codspeed workflow padding\n" * 100)
)
RELEASE_YML = (
    "name: Release\n"
    "jobs:\n"
    "  wheels:\n"
    "    steps:\n"
    "      - run: python scripts/verify_wheel.py dist/example.whl --expect-native\n"
    "  sdist:\n"
    "    steps:\n"
    "      - run: python scripts/verify_sdist.py dist/example.tar.gz\n"
    "  publish:\n"
    "    permissions:\n"
    "      id-token: write\n"
    "    steps:\n"
    "      - uses: pypa/gh-action-pypi-publish@release/v1\n" + ("release workflow padding\n" * 100)
)
DEFAULT_PKG_INFO = (
    "Metadata-Version: 2.4\n"
    "Name: xy\n"
    "Version: 0.0.1\n"
    "Requires-Python: >=3.11\n"
    "Requires-Dist: anywidget>=0.9\n"
    "Requires-Dist: numpy>=1.24\n"
)
BASELINE_JSON = '{"metrics": {"scatter.tier.100000": "direct"}}\n'


def _load_sdist_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_sdist.py"
    spec = importlib.util.spec_from_file_location("verify_sdist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_sdist = _load_sdist_module()


def _add_file(tf: tarfile.TarFile, name: str, data: bytes = b"") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def _write_sdist(
    path: Path,
    *,
    pkg_info: Optional[str] = DEFAULT_PKG_INFO,
    omit: Optional[set[str]] = None,
    extra: Optional[dict[str, bytes]] = None,
    replacements: Optional[dict[str, Union[bytes, str]]] = None,
) -> None:
    root = "xy-0.0.1"
    omit = omit or set()
    extra = extra or {}
    replacements = replacements or {}
    with tarfile.open(path, "w:gz") as tf:
        for name in sorted(verify_sdist.REQUIRED_FILES - omit):
            data = b""
            if name == "PKG-INFO" and pkg_info is not None:
                data = pkg_info.encode("utf-8")
            if name == "PKG-INFO" and pkg_info is None:
                continue
            elif name in replacements:
                raw = replacements[name]
                data = raw.encode("utf-8") if isinstance(raw, str) else raw
            elif name == "benchmarks/baseline.json":
                data = BASELINE_JSON.encode("utf-8")
            elif name == "python/xy/static/index.js":
                data = INDEX_JS.encode("utf-8")
            elif name == "python/xy/static/standalone.js":
                data = STANDALONE_JS.encode("utf-8")
            elif name == "js/src/60_entries.js":
                data = ENTRIES_JS.encode("utf-8")
            elif name == "README.md":
                data = README_MD.encode("utf-8")
            elif name == "docs/engineering/api-examples.md":
                data = API_EXAMPLES_MD.encode("utf-8")
            elif name == "docs/engineering/benchmark.md":
                data = BENCHMARK_MD.encode("utf-8")
            elif name == "docs/engineering/production-readiness.md":
                data = PRODUCTION_READINESS_MD.encode("utf-8")
            elif name == "docs/engineering/contributing.md":
                data = CONTRIBUTING_MD.encode("utf-8")
            elif name == "examples/reflex/README.md":
                data = REFLEX_README_MD.encode("utf-8")
            elif name == "examples/reflex/assets/charts/business_overview.html":
                data = BUSINESS_OVERVIEW_HTML.encode("utf-8")
            elif name == ".github/workflows/ci.yml":
                data = CI_YML.encode("utf-8")
            elif name == ".github/workflows/codspeed.yml":
                data = CODSPEED_YML.encode("utf-8")
            elif name == ".github/workflows/release.yml":
                data = RELEASE_YML.encode("utf-8")
            _add_file(tf, f"{root}/{name}", data)
        for name, data in extra.items():
            _add_file(tf, f"{root}/{name}", data)


def test_verify_sdist_accepts_required_source_shape(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist)

    verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_accepts_normalized_metadata_spacing(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    pkg_info = DEFAULT_PKG_INFO.replace(
        "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget >= 0.9"
    ).replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy >= 1.24")
    _write_sdist(sdist, pkg_info=pkg_info)

    verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_pkg_info(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, pkg_info=None)

    with pytest.raises(AssertionError, match="PKG-INFO"):
        verify_sdist.verify_sdist(str(sdist))


@pytest.mark.parametrize(
    ("pkg_info", "match"),
    [
        (
            DEFAULT_PKG_INFO.replace("Name: xy", "Name: othercharts"),
            "Name: xy",
        ),
        (
            DEFAULT_PKG_INFO.replace("Version: 0.0.1", "Version: 0.2.0"),
            "Version: 0.0.1",
        ),
        (
            DEFAULT_PKG_INFO.replace("Requires-Python: >=3.11", "Requires-Python: >=3.10"),
            r"Requires-Python: >=3\.11",
        ),
        (
            DEFAULT_PKG_INFO.replace("Requires-Dist: anywidget>=0.9", ""),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_PKG_INFO.replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy>=1.20"),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_PKG_INFO + "Requires-Dist: reflex>=0.8\n",
            "no Reflex runtime dependency",
        ),
    ],
)
def test_verify_sdist_rejects_invalid_pkg_info(tmp_path: Path, pkg_info: str, match: str) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, pkg_info=pkg_info)

    with pytest.raises(AssertionError, match=match):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_static_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={"python/xy/static/standalone.js"})

    with pytest.raises(AssertionError, match="missing required files"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_partial_type_marker(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"python/xy/py.typed": "partial\n"})

    with pytest.raises(AssertionError, match="full-package PEP 561 marker"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_production_docs_or_tooling(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist, omit={"docs/engineering/production-readiness.md", "scripts/verify_local.py"}
    )

    with pytest.raises(AssertionError, match="production-readiness"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_benchmark_harness(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={"benchmarks/bench_vs.py", "benchmarks/environment.py"})

    with pytest.raises(AssertionError, match="benchmarks/bench_vs"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_workflow_benchmark(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={"benchmarks/bench_workflows.py"})

    with pytest.raises(AssertionError, match="benchmarks/bench_workflows"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_regression_gate_files(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        omit={
            "benchmarks/baseline.json",
            "benchmarks/bench_line.py",
            "benchmarks/bench_install.py",
            "scripts/check_regressions.py",
            "tests/test_check_regressions.py",
        },
    )

    with pytest.raises(AssertionError, match=r"benchmarks/baseline\.json"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_benchmark_baseline(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"benchmarks/baseline.json": '{"metrics": {}}'})

    with pytest.raises(AssertionError, match="non-empty metrics object"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_docs_example_guard(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={"tests/test_docs_examples.py"})

    with pytest.raises(AssertionError, match="test_docs_examples"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_reflex_example_app_files(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        omit={
            "examples/reflex/README.md",
            "examples/reflex/assets/charts/business_overview.html",
            "tests/test_reflex_example_assets.py",
        },
    )

    with pytest.raises(AssertionError, match="examples/reflex"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_stale_api_examples_doc(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={"docs/engineering/api-examples.md": "# API Examples\n" + ("padding\n" * 200)},
    )

    with pytest.raises(AssertionError, match="api-examples"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_stale_benchmark_doc(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={"docs/engineering/benchmark.md": "# Benchmark\n" + ("padding\n" * 200)},
    )

    with pytest.raises(AssertionError, match="benchmark"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_public_docs(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"README.md": "# xy\n" + ("padding\n" * 200)})

    with pytest.raises(AssertionError, match="README"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_stale_production_readiness_doc(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={
            "docs/engineering/production-readiness.md": "# Production Readiness\n"
            + ("padding\n" * 200)
        },
    )

    with pytest.raises(AssertionError, match="production-readiness"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_stale_contributing_doc(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={"docs/engineering/contributing.md": "# Contributing\n" + ("padding\n" * 200)},
    )

    with pytest.raises(AssertionError, match="contributing"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_stale_reflex_example_readme(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={"examples/reflex/README.md": "# Reflex\n" + ("padding\n" * 200)},
    )

    with pytest.raises(AssertionError, match="examples/reflex/README"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_stale_business_example_asset(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={
            "examples/reflex/assets/charts/business_overview.html": (
                "<html>" + ("padding\n" * 200) + "</html>"
            )
        },
    )

    with pytest.raises(AssertionError, match="business_overview"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_release_workflow(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={".github/workflows/release.yml"})

    with pytest.raises(AssertionError, match=r"release\.yml"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_codspeed_workflow(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={".github/workflows/codspeed.yml"})

    with pytest.raises(AssertionError, match=r"codspeed\.yml"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_codspeed_workflow(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={".github/workflows/codspeed.yml": "name: CodSpeed\n" + ("padding\n" * 200)},
    )

    with pytest.raises(AssertionError, match=r"codspeed\.yml"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_release_workflow(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(
        sdist,
        replacements={".github/workflows/release.yml": "name: Release\n" + ("padding\n" * 200)},
    )

    with pytest.raises(AssertionError, match=r"release\.yml"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_static_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"python/xy/static/index.js": "not the client"})

    with pytest.raises(AssertionError, match=r"index\.js"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_source_entry_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"js/src/60_entries.js": "not the source client"})

    with pytest.raises(AssertionError, match=r"60_entries\.js"):
        verify_sdist.verify_sdist(str(sdist))


@pytest.mark.parametrize(
    "artifact",
    [
        "python/xy/__pycache__/figure.pyc",
        "examples/reflex/.web/package.json",
        "examples/reflex/.states/state.pkl",
        "examples/reflex/reflex.lock/package.json",
    ],
)
def test_verify_sdist_rejects_generated_artifacts(tmp_path: Path, artifact: str) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, extra={artifact: b"cache"})

    with pytest.raises(AssertionError, match="generated/native artifacts"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_duplicate_file_member(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, extra={"README.md": b"duplicate"})

    with pytest.raises(AssertionError, match="duplicate file member"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_unsafe_member_paths(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    with tarfile.open(sdist, "w:gz") as tf:
        _add_file(tf, "xy-0.0.1/PKG-INFO", b"Name: xy\n")
        _add_file(tf, "xy-0.0.1/../evil.py", b"")

    with pytest.raises(AssertionError, match="unsafe tar member path"):
        verify_sdist.verify_sdist(str(sdist))
