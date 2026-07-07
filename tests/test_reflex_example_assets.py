from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLIENT_SOURCE = ROOT / "js" / "src" / "50_chartview.js"
APP_SOURCE = ROOT / "reflex_fastcharts_app" / "reflex_fastcharts_app" / "reflex_fastcharts_app.py"
LIVE_SOURCE = ROOT / "reflex_fastcharts_app" / "reflex_fastcharts_app" / "live_drilldown.py"
CUSTOM_CHROME_ASSET = ROOT / "reflex_fastcharts_app" / "assets" / "charts" / "custom_chrome.html"
ANNOTATED_HEATMAP_ASSET = (
    ROOT / "reflex_fastcharts_app" / "assets" / "charts" / "annotated_heatmap.html"
)
BUSINESS_ASSET = ROOT / "reflex_fastcharts_app" / "assets" / "charts" / "business_overview.html"
RETENTION_ASSET = ROOT / "reflex_fastcharts_app" / "assets" / "charts" / "retention_cohort.html"
LIVE_ASSETS = [
    ROOT / "reflex_fastcharts_app" / "assets" / "charts" / "live_drilldown_100m.html",
    ROOT / "reflex_fastcharts_app" / "assets" / "charts" / "live_drilldown_10m.html",
]
CHART_ASSET_DIR = ROOT / "reflex_fastcharts_app" / "assets" / "charts"


def _dashboard_constants() -> dict[str, Any]:
    env: dict[str, Any] = {}
    module = ast.parse(APP_SOURCE.read_text(encoding="utf-8"))
    for statement in module.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        env[target.id] = _resolve_dashboard_value(statement.value, env)
    return env


def _resolve_dashboard_value(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "strip"
        and not node.args
        and not node.keywords
    ):
        return _resolve_dashboard_value(node.func.value, env).strip()
    if isinstance(node, ast.Dict):
        return {
            _resolve_dashboard_value(key, env): _resolve_dashboard_value(value, env)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.List):
        values: list[Any] = []
        for item in node.elts:
            if isinstance(item, ast.Starred) and isinstance(item.value, ast.Name):
                values.extend(env[item.value.id])
            elif isinstance(item, ast.Name):
                values.append(env[item.id])
            else:
                values.append(_resolve_dashboard_value(item, env))
        return values
    return None


def test_live_drilldown_assets_keep_local_density_fallback() -> None:
    required = [
        "REQUEST_TIMEOUT_MS",
        "overviewData",
        "localDensityUpdate",
        "isInitialOverviewRequest",
        "initialOverviewUpdate",
        "overviewDensityArrayBuffer",
        "densityRequestPending",
        "clearStaleUpdatingStatus",
        "REQUEST_TIMEOUT_MS + 500",
    ]
    source = LIVE_SOURCE.read_text(encoding="utf-8")
    for marker in required:
        assert marker in source

    for asset in LIVE_ASSETS:
        html = asset.read_text(encoding="utf-8")
        for marker in required:
            assert marker in html
        assert "for (const cb of callbacks) cb(initial.message, initial.buffers);" in html
        assert (
            'if (!currentDrillCoversView(view, next)) statusEl.textContent = "updating";'
            not in html
        )


def test_density_update_without_traces_clears_pending_client_request() -> None:
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    assert "const densityTraces = msg.traces || [];" in source
    assert "pendingTraceIds.add(Number(msg.trace));" in source
    assert "const clearAllPending = pendingTraceIds.size === 0 && msg.stale;" in source
    assert "if (pendingTraceIds.size || clearAllPending)" in source
    assert "for (const upd of densityTraces)" in source


def test_reflex_dashboard_has_selector_and_small_business_chart() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    required = [
        "def chart_selector()",
        "def chart_section(",
        "def chart_code_drawer(",
        "def custom_chrome_panel(",
        "def custom_chrome_bridge(",
        "CHART_NAV",
        "CHART_CODE_SNIPPETS",
        "CORE_API_STATUS",
        "CUSTOM_CHROME_CHART",
        "BUSINESS_CHART",
        "RETENTION_CHART",
        "BUSINESS_CHARTS",
        "CORE_CHARTS",
        "LARGE_DATA_CHARTS",
        'chart_section("Business charts", BUSINESS_CHARTS)',
        'chart_section("Core 2D gallery", CORE_CHARTS)',
        'chart_section("Large-data demos", LARGE_DATA_CHARTS',
        "def core_api_status()",
        "Core API status",
        "Composable layers",
        "Annotations",
        "Axes and scales",
        "Interaction",
        "core-api-status",
        "Custom Reflex Chrome",
        "Business Overview",
        "Retention Cohort",
        "/charts/custom_chrome.html",
        "/charts/business_overview.html",
        "/charts/retention_cohort.html",
        "custom-chrome",
        "custom-chrome-legend",
        "custom-chrome-tooltip",
        "fastcharts-custom-chrome",
        "ANNOTATED_HEATMAP_MARKERS",
        "annotated_heatmap_panel",
        "annotated_heatmap_legend",
        "annotated_heatmap_tooltip",
        "annotated_heatmap_bridge",
        "annotated-heatmap-legend",
        "annotated-heatmap-tooltip",
        "fastcharts-annotated-heatmap",
        "chart.reflex_components()",
        "rx.el.details",
        "rx.el.summary",
        "chart_code_drawer(chart)",
        "is_live_drilldown",
        'loading="eager" if is_live_drilldown else "lazy"',
        "business-overview",
        "retention-cohort",
        "href=f\"#{chart['id']}\"",
        'loading="lazy"',
    ]
    for marker in required:
        assert marker in source
    assert 'loading="eager" if fluid else "lazy"' not in source


def test_reflex_dashboard_groups_small_and_large_examples() -> None:
    constants = _dashboard_constants()

    assert [chart["id"] for chart in constants["BUSINESS_CHARTS"]] == [
        "custom-chrome",
        "business-overview",
        "retention-cohort",
    ]
    assert "live-drilldown" not in {chart["id"] for chart in constants["BUSINESS_CHARTS"]}
    assert "live-drilldown" in {chart["id"] for chart in constants["LARGE_DATA_CHARTS"]}
    business_count = len(constants["BUSINESS_CHARTS"])
    assert constants["CHART_NAV"][:business_count] == constants["BUSINESS_CHARTS"]
    assert (
        constants["CHART_NAV"][business_count : business_count + len(constants["CORE_CHARTS"])]
        == constants["CORE_CHARTS"]
    )


def test_reflex_dashboard_has_code_snippets_for_every_chart() -> None:
    constants = _dashboard_constants()
    chart_ids = {chart["id"] for chart in constants["CHART_NAV"]}
    snippets = constants["CHART_CODE_SNIPPETS"]

    assert set(snippets) == chart_ids
    for chart_id, snippet in snippets.items():
        assert isinstance(snippet, str)
        assert snippet.strip()
        assert (
            "Figure" in snippet
            or "fc.chart" in snippet
            or "Plotly" in snippet
            or "live_drilldown" in snippet
        )
        if chart_id != "plotly-scatter":
            assert "fastcharts" in snippet or "Figure" in snippet or "fc." in snippet


def test_reflex_dashboard_chart_nav_is_unique_and_asset_backed() -> None:
    constants = _dashboard_constants()
    charts = constants["CHART_NAV"]
    assert charts

    ids = [chart["id"] for chart in charts]
    titles = [chart["title"] for chart in charts]
    srcs = [chart["src"] for chart in charts]
    assert len(ids) == len(set(ids))
    assert len(titles) == len(set(titles))
    assert len(srcs) == len(set(srcs))

    for chart in charts:
        assert set(chart) == {"id", "title", "subtitle", "src", "stat"}
        assert chart["id"] == chart["id"].lower()
        assert " " not in chart["id"]
        assert chart["src"].startswith("/charts/")
        assert (CHART_ASSET_DIR / Path(chart["src"]).name).is_file()
        assert chart["title"].strip()
        assert chart["subtitle"].strip()
        assert chart["stat"].strip()


def test_reflex_dashboard_nav_covers_all_chart_definitions() -> None:
    constants = _dashboard_constants()
    nav_srcs = {chart["src"] for chart in constants["CHART_NAV"]}
    defined_srcs = {
        value["src"]
        for name, value in constants.items()
        if name.endswith("_CHART") and isinstance(value, dict)
    }
    defined_srcs.update(chart["src"] for chart in constants["COMPARISON_CHARTS"])

    assert nav_srcs == defined_srcs


def test_reflex_dashboard_nav_assets_are_renderable_html() -> None:
    constants = _dashboard_constants()
    for chart in constants["CHART_NAV"]:
        html = (CHART_ASSET_DIR / Path(chart["src"]).name).read_text(encoding="utf-8")
        assert "<html" in html.lower()
        if chart["title"].startswith("Plotly"):
            assert "Plotly.newPlot" in html
        elif "live_drilldown" in chart["src"]:
            assert "window.fastchartsLiveDrilldown" in html
        else:
            assert "fastcharts.renderStandalone" in html


def test_custom_chrome_chart_asset_disables_builtin_chrome() -> None:
    html = CUSTOM_CHROME_ASSET.read_text(encoding="utf-8")
    assert "fastcharts.renderStandalone" in html
    assert "Custom Reflex legend + tooltip" in html
    assert "fastcharts-custom-chrome" in html
    assert "window.__fastchartsCustomChromeView" in html
    assert 'addEventListener("pointermove"' in html
    assert "_localRow(hit)" in html
    assert '"show_legend":false' in html
    assert '"show_tooltip":false' in html


def test_annotated_heatmap_uses_reflex_custom_chrome_bridge() -> None:
    html = ANNOTATED_HEATMAP_ASSET.read_text(encoding="utf-8")
    assert "fastcharts.renderStandalone" in html
    assert "Annotated risk heatmap" in html
    assert "fastcharts-annotated-heatmap" in html
    assert "window.__fastchartsAnnotatedHeatmapView" in html
    assert 'addEventListener("pointermove"' in html
    assert "_localRow(hit)" in html
    assert '"show_legend":false' in html
    assert '"show_tooltip":false' in html
    assert '"risk_score"' in html


def test_small_business_chart_asset_exists() -> None:
    html = BUSINESS_ASSET.read_text(encoding="utf-8")
    assert "fastcharts.renderStandalone" in html
    assert "Small business overview" in html
    assert "Revenue" in html
    assert "Pipeline" in html


def test_small_retention_cohort_asset_exists() -> None:
    html = RETENTION_ASSET.read_text(encoding="utf-8")
    assert "fastcharts.renderStandalone" in html
    assert "Small retention cohort" in html
    assert "signup cohort" in html
    assert "retention" in html
