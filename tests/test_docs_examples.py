from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC_DOCS = ROOT / "spec"
API_EXAMPLES = SPEC_DOCS / "api" / "api-examples.md"
README = ROOT / "README.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
SECURITY = ROOT / "SECURITY.md"
BENCHMARK_DOC = SPEC_DOCS / "benchmarks" / "results.md"
PRODUCTION_DOC = SPEC_DOCS / "process" / "production-readiness.md"
REFLEX_SHAPED_API_DOC = SPEC_DOCS / "design" / "reflex-shaped-api.md"
EXPECTED_QUICK_REFERENCE = {
    "Line": ("xy.line_chart", "xy.line"),
    "Scatter": ("xy.scatter_chart", "xy.scatter"),
    "Area": ("xy.area_chart", "xy.area"),
    "Histogram": ("xy.histogram_chart", "xy.histogram"),
    "Bar": ("xy.bar_chart", "xy.bar"),
    "Column": ("xy.column_chart", "xy.column"),
    "Grouped bars": ('mode="grouped"', "xy.bar_chart", "xy.bar"),
    "Stacked bars": ('mode="stacked"', "xy.bar_chart", "xy.bar"),
    "Normalized bars": ('mode="normalized"', "xy.bar_chart", "xy.bar"),
    "Horizontal bars": ('orientation="horizontal"', "xy.bar_chart", "xy.bar"),
    "Heatmap": ("xy.heatmap_chart", "xy.heatmap"),
}

LOCAL_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def test_spec_local_links_resolve() -> None:
    broken: list[str] = []
    for path in sorted(SPEC_DOCS.rglob("*.md")):
        in_fence = False
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in LOCAL_MARKDOWN_LINK_RE.finditer(line):
                raw_target = match.group(1).strip()
                if raw_target.startswith("<") and raw_target.endswith(">"):
                    raw_target = raw_target[1:-1]
                target = raw_target.split(maxsplit=1)[0]
                if target.startswith(("#", "/", "http://", "https://", "mailto:")):
                    continue
                target_path = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not target_path:
                    continue
                resolved = (path.parent / target_path).resolve()
                if not resolved.is_relative_to(ROOT) or not resolved.exists():
                    broken.append(f"{path.relative_to(ROOT)}:{line_number}: {target}")
    assert not broken, "broken local spec links:\n" + "\n".join(broken)


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
    uses_pyplot_show = source.rstrip().endswith("plt.show()")
    if uses_pyplot_show:
        import xy.pyplot as pyplot

        monkeypatch.setattr(pyplot, "show", lambda *_args, **_kwargs: None)

    exec(compile(_capture_final_expression(source), str(README), "exec"), namespace)

    result = namespace.get("__example_result__")
    if uses_pyplot_show and result is None:
        result = namespace.get("fig")
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
        "`to_png(..., engine=Engine.chromium)` uses an installed Chrome, Chromium, Edge, or",
    ]
    for marker in required:
        assert marker in text


def test_readme_documents_declarative_callback_serialization_boundary() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "The composition contract we are locking is intentionally narrow and durable",
        "opaque framework objects passed to `xy.legend(...)` / `xy.tooltip(...)`",
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
        "Neutral `xy.chart(...)`",
        "`xy.tooltip(...)`, `xy.modebar(...)`, `xy.theme(...)`",
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
        assert f"xy.{mark}" in rows
        assert f"xy.{mark}_chart" in rows or mark in {"bar"}


def test_security_policy_documents_standalone_html_contract() -> None:
    text = " ".join(SECURITY.read_text(encoding="utf-8").split())
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
        "declarative `xy.chart(...children)`",
        "CSS/Tailwind hooks",
        "Reflex integration",
        "Adaptive drilldown internals",
        "Experimental",
        "Python 3.11+ package import",
        "Implemented 2D chart families",
        "native Rust kernels",
        "required compute core",
        "raises a clear error rather than degrading",
    ]
    for marker in required:
        assert marker in text


def test_contributing_documents_backend_check() -> None:
    text = " ".join(CONTRIBUTING.read_text(encoding="utf-8").split())
    required = [
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


def test_readme_documents_install_paths() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "uv add xy",
        "Published wheels contain the Python package, JavaScript client, and native Rust core",
        "End users do not need Rust, Node, npm, or a CDN",
    ]
    for marker in required:
        assert marker in text
    assert "Install/backend quick matrix" not in text


def test_readme_getting_started_includes_small_business_chart() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    required = [
        "Create a small business chart",
        "Revenue vs pipeline",
        "USD thousands",
        "xy.line(months, revenue",
        "xy.line(months, pipeline",
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
        "spec/benchmarks/metrics.md",
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
    contributing = " ".join(
        (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8").split()
    )

    for text in (readme, production, contributing):
        assert "make check-benchmark-harness" in text
    assert "environment metadata" in readme
    assert "report-schema validation" in production
    assert "regression comparison scripts" in contributing


def test_docs_name_claim_guardrail_shortcut() -> None:
    readme = " ".join(README.read_text(encoding="utf-8").split())
    production = " ".join(PRODUCTION_DOC.read_text(encoding="utf-8").split())
    contributing = " ".join(
        (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8").split()
    )

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
        "Production-facing non-browser change",
        "`make check-full`",
        "the full non-browser local gate",
        "it is not equivalent to the browser, host-integration, packaging, cross-platform, or exact-SHA release evidence",
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
    contributing = " ".join(
        (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8").split()
    )

    step_names = [
        "Browser lifecycle smoke (Chromium)",
        "Browser visual health smoke (Chromium)",
        "Reviewed visual baseline (Chromium)",
        "Browser interaction stress smoke (Chromium)",
    ]
    scripts = [
        "scripts/reflex_lifecycle_smoke.py",
        "scripts/visual_health_smoke.py",
        "scripts/visual_baseline.py",
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
        "example apps' source (FastAPI and Reflex)",
        "Wheels must stay package-only",
        "docs, tests, benchmarks, scripts, and the `examples/` apps are sdist-only",
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
