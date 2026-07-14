from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_EXAMPLES = ROOT / "docs" / "api-examples.md"
README = ROOT / "README.md"
BENCHMARK_DOC = ROOT / "docs" / "benchmark.md"
PRODUCTION_DOC = ROOT / "docs" / "production-readiness.md"
REFLEX_SHAPED_API_DOC = ROOT / "docs" / "design" / "reflex-shaped-api.md"
EXPECTED_QUICK_REFERENCE = {
    "Line": ("fc.line_chart", "fc.line"),
    "Scatter": ("fc.scatter_chart", "fc.scatter"),
    "Area": ("fc.area_chart", "fc.area"),
    "Histogram": ("fc.histogram_chart", "fc.histogram"),
    "Bar": ("fc.bar_chart", "fc.bar"),
    "Column": ("fc.column_chart", "fc.column"),
    "Grouped bars": ('mode="grouped"', "fc.bar_chart", "fc.bar"),
    "Stacked bars": ('mode="stacked"', "fc.bar_chart", "fc.bar"),
    "Normalized bars": ('mode="normalized"', "fc.bar_chart", "fc.bar"),
    "Horizontal bars": ('orientation="horizontal"', "fc.bar_chart", "fc.bar"),
    "Heatmap": ("fc.heatmap_chart", "fc.heatmap"),
}


def _python_examples(path: Path = API_EXAMPLES) -> list[tuple[str, str]]:
    examples: list[tuple[str, str]] = []
    heading = "intro"
    in_python = False
    code: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if in_python:
            if line == "```":
                in_python = False
                examples.append((heading, "\n".join(code)))
            else:
                code.append(line)
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif line == "```python":
            in_python = True
            code = []
    return examples


def _quick_reference_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    in_table = False
    for line in API_EXAMPLES.read_text(encoding="utf-8").splitlines():
        if line == "## Chart Family Quick Reference":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] in {"Chart family", "---"}:
            continue
        rows[cells[0]] = line
    return rows


def _capture_final_expression(source: str) -> ast.Module:
    module = ast.parse(source)
    if module.body and isinstance(module.body[-1], ast.Expr):
        module.body[-1] = ast.Assign(
            targets=[ast.Name(id="__example_result__", ctx=ast.Store())],
            value=module.body[-1].value,
        )
        ast.fix_missing_locations(module)
    return module


@pytest.mark.parametrize(("heading", "source"), _python_examples(), ids=lambda value: str(value))
def test_api_example_builds_payload(heading: str, source: str) -> None:
    namespace: dict[str, object] = {"__name__": f"xy_docs_example_{heading}"}

    exec(compile(_capture_final_expression(source), str(API_EXAMPLES), "exec"), namespace)

    result = namespace.get("__example_result__")
    assert result is not None, f"{heading} example should end with a chart expression"
    figure = result.figure() if hasattr(result, "figure") else result
    if hasattr(figure, "build_payload"):
        spec, blob = figure.build_payload()
        json.dumps(spec, allow_nan=False)
        assert spec["traces"], f"{heading} example produced no traces"
        assert isinstance(blob, bytes)
    else:
        assert hasattr(figure, "figures") and figure.figures, (
            f"{heading} example did not produce a chart"
        )
        for panel in figure.figures:
            spec, blob = panel.build_payload()
            json.dumps(spec, allow_nan=False)
            assert spec["traces"], f"{heading} example produced no traces"
            assert isinstance(blob, bytes)


@pytest.mark.parametrize(
    ("heading", "source"), _python_examples(README), ids=lambda value: str(value)
)
def test_readme_python_example_runs(
    heading: str,
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {"__name__": f"xy_readme_example_{heading}"}

    exec(compile(_capture_final_expression(source), str(README), "exec"), namespace)

    result = namespace.get("__example_result__")
    assert result is not None, f"{heading} README example should end with an expression"
    if isinstance(result, str):
        assert "xy.renderStandalone" in result
        if "chart.html" in source:
            assert (tmp_path / "chart.html").read_text(encoding="utf-8") == result
        return
    if not hasattr(result, "figure") and not hasattr(result, "build_payload"):
        # pyplot-shim figures display like notebooks display them.
        html = result._repr_html_()
        assert html.startswith('<iframe class="xy-notebook-frame"'), (
            f"{heading} README example produced no chart"
        )
        assert 'sandbox="allow-scripts"' in html
        assert "&lt;!doctype html&gt;" in html
        assert "xy.renderStandalone" in html
        return
    figure = result.figure() if hasattr(result, "figure") else result
    assert hasattr(figure, "build_payload"), f"{heading} README example did not produce a chart"
    spec, blob = figure.build_payload()
    json.dumps(spec, allow_nan=False)
    assert spec["traces"], f"{heading} README example produced no traces"
    assert isinstance(blob, bytes)


def test_api_examples_cover_current_2d_surface() -> None:
    headings = {heading for heading, _source in _python_examples()}
    assert {
        "Small Business Chart",
        "Line",
        "Scatter",
        "Area",
        "Histogram",
        "Bar",
        "Column",
        "Grouped Bars",
        "Stacked Bars",
        "Horizontal Bars",
        "Heatmap",
        "Composition API",
    } <= headings


def test_api_examples_keep_small_business_chart_coverage() -> None:
    text = " ".join(API_EXAMPLES.read_text(encoding="utf-8").split())
    assert "ordinary charts should stay boring to build" in text
    assert "## Small Business Chart" in text
    assert "Revenue vs pipeline" in text
    assert "USD thousands" in text


def test_api_examples_document_alpha_api_stability_boundary() -> None:
    text = " ".join(API_EXAMPLES.read_text(encoding="utf-8").split())
    required = [
        "API Stability Notes",
        "one public chart-building API: the declarative composition API",
        "column-name resolution through `data=`",
        "`on_hover` / `on_select` callbacks",
        "core composition contract is now stabilizing",
        "CSS/Tailwind-friendly DOM hooks",
        "Callback payload details and future adapter packages may still evolve before 1.0",
        "`chart.figure()` as an advanced escape hatch",
        '`width="100%"`',
        "Standalone `to_html(...)` needs no browser dependency",
        '`to_png(..., engine="chromium")` needs a local Chrome/Chromium executable',
    ]
    for marker in required:
        assert marker in text


def test_readme_documents_declarative_callback_serialization_boundary() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "The composition contract we are locking is intentionally narrow and durable",
        "opaque framework objects passed to `fc.legend(...)` / `fc.tooltip(...)`",
        "without being serialized into standalone HTML",
        "Python `on_*` callbacks stay widget-side",
        "standalone HTML receives only the safe interaction flags",
    ]
    for marker in required:
        assert marker in text


def test_reflex_shaped_api_doc_tracks_locked_composition_contract() -> None:
    text = " ".join(REFLEX_SHAPED_API_DOC.read_text(encoding="utf-8").split())
    required = [
        "Compatibility Contract",
        "single public chart-building surface",
        "internal `_figure.Figure` fluent API is no longer public",
        "`Chart.figure()`",
        "`Chart.widget()`",
        "`Chart.show()`",
        "`Chart.to_html(...)`",
        "`Chart.to_png(...)`",
        "Static HTML exports with no Python/Reflex runtime",
        "No Reflex import in `xy`",
        "Neutral `fc.chart(...)`",
        "`fc.tooltip(...)`, `fc.modebar(...)`, `fc.theme(...)`",
        "`class_name`, `class_names`, and `style` props",
        "Python callbacks notebook-only",
        "Pulling full Reflex into any install path",
    ]
    for marker in required:
        assert marker in text


def test_api_examples_quick_reference_matches_current_surface() -> None:
    rows = _quick_reference_rows()
    assert set(EXPECTED_QUICK_REFERENCE) <= set(rows)
    for family, snippets in EXPECTED_QUICK_REFERENCE.items():
        row = rows[family]
        for snippet in snippets:
            assert snippet in row, f"{family} row missing {snippet!r}"


def test_api_examples_quick_reference_covers_registered_composition_marks() -> None:
    from xy.components import _MARK_APPLIERS  # noqa: PLC2701 - docs sync guard.

    rows = "\n".join(_quick_reference_rows().values())
    for mark in sorted(_MARK_APPLIERS):
        assert f"fc.{mark}" in rows
        assert f"fc.{mark}_chart" in rows or mark in {"bar"}


def test_readme_documents_standalone_html_security_contract() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "Standalone HTML Safety And CSP",
        "Content-Security-Policy",
        "inline scripts",
        "application wrapper that serves the",
        "JavaScript bundle separately",
        "titles, axis labels, trace names, legends, series names, and categories",
        "non-finite JSON metadata is rejected",
    ]
    for marker in required:
        assert marker in text


def test_readme_documents_stability_and_backend_contract() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "Stable vs. Experimental",
        "Stable enough to build on today",
        "Still experimental and expected to change before 1.0",
        "| Surface | Current status | Notes |",
        "Stable alpha",
        "Composition API",
        "single public chart-building API",
        "Stabilizing alpha",
        "declarative `fc.chart(...children)`",
        "CSS/Tailwind hooks",
        "Reflex integration",
        "Adaptive drilldown internals",
        "Experimental",
        "Python 3.11+ package import",
        "Implemented 2D chart families",
        "native Rust kernels",
        "required compute core",
        "raises a clear error rather than degrading",
        "Check the active backend",
        "is intentionally lightweight",
        "does not import NumPy or load the native core",
        "xy.kernels",
        "print(k.BACKEND)",
        "`BACKEND` is always `native`",
        "raises `ImportError` with remediation",
    ]
    for marker in required:
        assert marker in text


def test_readme_documents_install_backend_matrix() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "Install/backend quick matrix",
        "| Path | Command | Toolchain needed | Result |",
        "Published wheel",
        "`pip install xy`",
        "none",
        "`native` on supported platform wheels",
        "Source with Rust",
        '`uv pip install -e ".[dev]"`',
        "Platform/build with no native core",
        "clear `ImportError` on first compute, naming supported platforms",
        "Rust is required from source",
    ]
    for marker in required:
        assert marker in text


def test_readme_getting_started_includes_small_business_chart() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "Create a small business chart",
        "Revenue vs pipeline",
        "USD thousands",
        "fc.line(months, revenue",
        "fc.line(months, pipeline",
    ]
    for marker in required:
        assert marker in text


def test_readme_architecture_diagram_covers_major_boundaries() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "```mermaid",
        "Python kernel / app process",
        "User APIs",
        "ColumnStore",
        "rollback checkpoints",
        "Compute core",
        "native Rust C ABI",
        "(required; no fallback)",
        "Payload builder",
        "Browser / notebook frontend",
        "WebGL2 renderer",
        "DOM chrome",
        "Interaction layer",
        "Adaptive large-data loop",
        "direct, decimated",
        "density, adaptive",
        "spec JSON + typed buffers",
        "no JSON number arrays",
        "new screen-bounded payload",
    ]
    for marker in required:
        assert marker in text


def test_benchmark_docs_name_ci_report_artifacts() -> None:
    text = " ".join(BENCHMARK_DOC.read_text(encoding="utf-8").split())
    required = [
        "benchmark-report",
        "regression-benchmark-report",
        "docs/benchmark_ci.md",
        "docs/benchmark_metrics.md",
        "scatter.json",
        "kernel.json",
        "compact summary",
        "row count",
        "statuses/tiers",
    ]
    for marker in required:
        assert marker in text


def test_benchmark_docs_include_copyable_claim_taxonomy() -> None:
    text = " ".join(BENCHMARK_DOC.read_text(encoding="utf-8").split())
    required = [
        "Copyable claim taxonomy",
        "Use these shapes when turning benchmark rows into README text",
        "Payload/prep comparison",
        "Browser first paint",
        "Large scatter overview",
        "Line decimation",
        "Install/import footprint",
        "chart type, workload, mode, backend, metric, and render target",
        "it is not drawing 100M exact markers",
    ]
    for marker in required:
        assert marker in text


def test_docs_name_benchmark_harness_shortcut() -> None:
    readme = " ".join(README.read_text(encoding="utf-8").split())
    production = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "docs" / "contributing.md").read_text(encoding="utf-8").split())

    for text in (readme, production, contributing):
        assert "make check-benchmark-harness" in text
    assert "environment metadata" in readme
    assert "report-schema validation" in production
    assert "regression comparison scripts" in contributing


def test_docs_name_claim_guardrail_shortcut() -> None:
    readme = " ".join(README.read_text(encoding="utf-8").split())
    production = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "docs" / "contributing.md").read_text(encoding="utf-8").split())

    for text in (readme, production, contributing):
        assert "make check-claims" in text
        assert "make check-docs" in text
    assert "Claim guardrails" in production
    assert (
        "Public docs and package metadata avoid broad, unqualified performance claims" in production
    )
    assert "README/API docs, example snippets, or public benchmark wording" in production
    assert "public-facing text" in readme


def test_production_docs_include_focused_gate_matrix() -> None:
    text = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    required = [
        "Changed surface",
        "Focused gate",
        "README/API prose, examples, public benchmark wording",
        "`make check-docs`",
        "Public validation, error messages, builder rollback, LOD/drill mutation boundaries, chart/widget caching",
        "`make check-errors`",
        "Public exports, lazy import mappings, component factories, public annotations",
        "`make check-api`",
        "Import-time budget, `xy.__init__`, dependency boundaries, widget/export/backend import boundaries",
        "`make check-import`",
        "Standalone HTML export, path writes, user text, tooltips, legends, browser DOM insertion",
        "`make check-security`",
        "Benchmark harness code, environment metadata, report schema, regressions",
        "`make check-benchmark-harness`",
        "CI/release workflows, artifact upload/download, no-Rust clear-error jobs",
        "`make check-ci`",
        "Source distributions and wheels",
        "`make check-sdist` and `make check-wheel`",
        "Production-facing PR",
        "`make check-full`",
    ]
    for marker in required:
        assert marker in text


def test_production_docs_name_ci_workflow_gate_shortcut() -> None:
    text = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    required = [
        "CI/release workflows",
        "Hard gates, non-blocking benchmarks",
        "trusted publishing",
        "`make check-ci`",
        "benchmark artifact upload/download",
        "no-Rust clear-error jobs",
    ]
    for marker in required:
        assert marker in text


def test_docs_name_split_browser_hardening_gates() -> None:
    readme = " ".join(README.read_text(encoding="utf-8").split())
    production = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "docs" / "contributing.md").read_text(encoding="utf-8").split())

    step_names = [
        "Browser lifecycle smoke (Chromium)",
        "Browser visual regression smoke (Chromium)",
        "Browser interaction stress smoke (Chromium)",
    ]
    scripts = [
        "scripts/reflex_lifecycle_smoke.py",
        "scripts/visual_regression_smoke.py",
        "scripts/interaction_stress_smoke.py",
    ]
    for text in (readme, production, contributing):
        assert "make check-browser" in text
        for step_name in step_names:
            assert step_name in text
    for text in (production, contributing):
        for script in scripts:
            assert script in text


def test_production_docs_define_sdist_wheel_boundary() -> None:
    text = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    required = [
        "Source distributions include the release support surface",
        "Reflex example app source plus generated chart assets",
        "Wheels must stay package-only",
        "docs, tests, benchmarks, scripts, and `examples/reflex/` are sdist-only",
        "Platform wheel contains package-only files",
        "No-toolchain wheel contains package-only files",
    ]
    for marker in required:
        assert marker in text


def test_production_docs_capture_html_export_dom_text_contract() -> None:
    text = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    required = [
        "HTML export safety",
        "Inline JSON/script escaping, atomic path writes, hostile user strings, and browser client text-node insertion",
        "`make check-security`",
        "The browser client inserts user-facing text with `textContent` or text nodes",
        "HTML parser sinks such as `innerHTML` are reserved for fixed internal icons",
        "not titles, labels, legends, categories, or tooltips",
    ]
    for marker in required:
        assert marker in text
