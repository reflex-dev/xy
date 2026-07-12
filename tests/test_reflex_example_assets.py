from __future__ import annotations

import ast
import html
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
# The client is split across ordered js/src parts; concatenate so a source-level
# check finds markers wherever a subsystem now lives (50 core + 51–54 mixins).
CLIENT_SOURCE = "\n".join(
    p.read_text(encoding="utf-8") for p in sorted((ROOT / "js" / "src").glob("*.js"))
)
APP_SOURCE = ROOT / "examples" / "reflex" / "reflex_xy_app" / "reflex_xy_app.py"
LIVE_SOURCE = ROOT / "examples" / "reflex" / "reflex_xy_app" / "live_drilldown.py"
CUSTOM_CHROME_ASSET = ROOT / "examples" / "reflex" / "assets" / "charts" / "custom_chrome.html"
ANNOTATED_HEATMAP_ASSET = (
    ROOT / "examples" / "reflex" / "assets" / "charts" / "annotated_heatmap.html"
)
BUSINESS_ASSET = ROOT / "examples" / "reflex" / "assets" / "charts" / "business_overview.html"
RETENTION_ASSET = ROOT / "examples" / "reflex" / "assets" / "charts" / "retention_cohort.html"
LIVE_ASSETS = [
    ROOT / "examples" / "reflex" / "assets" / "charts" / "live_drilldown_100m.html",
    ROOT / "examples" / "reflex" / "assets" / "charts" / "live_drilldown_10m.html",
]
CHART_ASSET_DIR = ROOT / "examples" / "reflex" / "assets" / "charts"
LIFECYCLE_SMOKE = ROOT / "scripts" / "reflex_lifecycle_smoke.py"
VISUAL_SMOKE = ROOT / "scripts" / "visual_regression_smoke.py"


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


def _lifecycle_smoke_module() -> Any:
    spec = importlib.util.spec_from_file_location("reflex_lifecycle_smoke", LIFECYCLE_SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _visual_smoke_module() -> Any:
    spec = importlib.util.spec_from_file_location("visual_regression_smoke", VISUAL_SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        'density.enc === "log-u8"',
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
    source = CLIENT_SOURCE
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
        "xy-custom-chrome",
        "ANNOTATED_HEATMAP_MARKERS",
        "annotated_heatmap_panel",
        "annotated_heatmap_legend",
        "annotated_heatmap_tooltip",
        "annotated_heatmap_bridge",
        "annotated-heatmap-legend",
        "annotated-heatmap-tooltip",
        "xy-annotated-heatmap",
        "chrome = chart.reflex_components()",
        'chrome["legend"]',
        'chrome["tooltip"]',
        "rx.el.details",
        "rx.el.summary",
        "chart_code_drawer(chart)",
        'loading="eager"',
        'loading="lazy"',
        'loading = "eager" if chart["id"] in {"business-overview", "retention-cohort"} else "lazy"',
        "business-overview",
        "retention-cohort",
        "href=f\"#{chart['id']}\"",
    ]
    for marker in required:
        assert marker in source
    assert 'loading="eager" if fluid else "lazy"' not in source
    assert "*chart.reflex_components()" not in source


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
            assert "xy" in snippet or "Figure" in snippet or "fc." in snippet


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


def test_reflex_dashboard_parent_shell_keeps_stable_iframe_contract() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    constants = _dashboard_constants()
    charts = constants["CHART_NAV"]
    special_ids = {
        constants["CUSTOM_CHROME_CHART"]["id"],
        constants["ANNOTATED_HEATMAP_CHART"]["id"],
    }

    for chart in charts:
        assert not chart["id"].endswith("-frame")
        assert not chart["id"].endswith("-frame-wrap")

    assert "id=f\"{chart['id']}-frame\"" in source
    assert "id=f\"{chart['id']}-frame-wrap\"" in source
    assert 'id="custom-chrome-frame"' in source
    assert 'id="custom-chrome-frame-wrap"' in source
    assert 'id="annotated-heatmap-frame"' in source
    assert 'id="annotated-heatmap-frame-wrap"' in source

    assert 'document.getElementById("custom-chrome-frame")' in source
    assert 'document.getElementById("custom-chrome-frame-wrap")' in source
    assert 'document.getElementById("annotated-heatmap-frame")' in source
    assert 'document.getElementById("annotated-heatmap-frame-wrap")' in source
    assert source.count('loading="eager"') >= 1
    assert 'loading="lazy"' in source
    assert "loading=loading" in source
    assert (
        'loading = "eager" if chart["id"] in {"business-overview", "retention-cohort"} else "lazy"'
        in source
    )

    generic_chart_ids = [chart["id"] for chart in charts if chart["id"] not in special_ids]
    assert generic_chart_ids
    assert "business-overview" in generic_chart_ids
    assert "retention-cohort" in generic_chart_ids
    assert "custom-chrome" not in generic_chart_ids
    assert "annotated-heatmap" not in generic_chart_ids


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
            assert "window.xyLiveDrilldown" in html
        else:
            assert "xy.renderStandalone" in html


def test_reflex_lifecycle_smoke_covers_xy_iframe_assets() -> None:
    constants = _dashboard_constants()
    lifecycle = _lifecycle_smoke_module()
    expected = {
        Path(chart["src"]).name for chart in constants["CHART_NAV"] if "plotly" not in chart["src"]
    }
    expected.add("live_drilldown_10m.html")

    assert set(lifecycle.CHART_ASSETS) == expected
    assert "plotly_colored_scatter.html" not in lifecycle.CHART_ASSETS
    assert lifecycle.CRITICAL_ASSETS == (
        "custom_chrome.html",
        "business_overview.html",
        "retention_cohort.html",
        "live_drilldown_10m.html",
        "live_drilldown_100m.html",
    )
    assert lifecycle.LIVE_CHART_ASSETS == (
        "live_drilldown_10m.html",
        "live_drilldown_100m.html",
    )
    grouped_assets = [asset for group in lifecycle.SHELL_ASSET_GROUPS for asset in group]
    assert sorted(grouped_assets) == sorted(lifecycle.CHART_ASSETS)
    assert len(grouped_assets) == len(set(grouped_assets))
    assert lifecycle.LIFECYCLE_PHASES == (
        "initial",
        "hash-navigation",
        "narrow-resize",
        "wide-resize",
        "scroll-bottom",
        "fast-scroll",
        "visibility-change",
        "context-restore",
        "restore",
    )
    assert lifecycle.SHELL_PHASES == (
        "iframe-initial",
        "iframe-remount",
        "iframe-reload",
        "iframe-hidden-reveal",
    )
    assert lifecycle.REQUIRED_RUNTIME_DOM_SLOTS == (
        "root",
        "chrome",
        "canvas",
        "labels",
        "tooltip",
    )
    assert set(lifecycle.CRITICAL_ASSETS) < set(lifecycle.CHART_ASSETS)


def test_reflex_lifecycle_smoke_exercises_iframe_remounts() -> None:
    source = LIFECYCLE_SMOKE.read_text(encoding="utf-8")
    required = [
        "iframe_lifecycle_shell.html",
        "iframe-initial",
        "iframe-remount",
        "iframe-reload",
        "iframe-hidden-reveal",
        "hidden-boot",
        "defer_probe",
        "deferProbe",
        "reloadInPlace",
        "reloadIframes",
        'url.searchParams.set("reload", "1")',
        "xy-lifecycle-parent",
        "run-probe",
        "revealHiddenBoot",
        "data-fc-shell-lifecycle",
        'viewport.textContent = ""',
        'document.dispatchEvent(new Event("visibilitychange"))',
        'window.dispatchEvent(new Event("resize"))',
        'window.dispatchEvent(new Event("scroll"))',
        "window.scrollTo(0, i % 2 ? 0 : document.body.scrollHeight)",
        'view.root.style.width = "420px"',
        'view.root.style.width = "960px"',
        "phase_names",
        "phase_count",
        "min_lit",
        "hash-navigation",
        "narrow-resize",
        "wide-resize",
        "scroll-bottom",
        "fast-scroll",
        "visibility-change",
        "context-restore",
        "WEBGL_lose_context",
        "forceContextRestore",
        "HashChangeEvent",
        "criticalTargetIds",
        "critical lifecycle coverage incomplete",
        "reports: flat.length",
        "iframe shell asset reports incomplete",
        "critical_reports",
        "critical_report_names",
        "publicDomSlots",
        "requiredRuntimeDomSlots",
        "domSlotReport",
        "data-fc-slot",
        "slot_count",
        "missing_slots",
        "unexpected_slots",
        'missing=${{missing.join(",")}}',
    ]
    for marker in required:
        assert marker in source


def test_reflex_lifecycle_smoke_rejects_shortened_child_phase_report() -> None:
    lifecycle = _lifecycle_smoke_module()
    payload = {
        "status": "ok",
        "view_count": 1,
        "phase_names": ["initial"],
        "phase_count": 1,
        "min_lit": 100,
        "labels": 4,
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-child-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="lifecycle phases incomplete"):
        lifecycle._child_result(dom, "shortened.html")


def test_reflex_lifecycle_smoke_rejects_child_without_dom_slot_probe() -> None:
    lifecycle = _lifecycle_smoke_module()
    payload = {
        "status": "ok",
        "view_count": 1,
        "phase_names": list(lifecycle.LIFECYCLE_PHASES),
        "phase_count": len(lifecycle.LIFECYCLE_PHASES),
        "min_lit": 100,
        "labels": 4,
        "slot_count": 0,
        "missing_slots": [],
        "unexpected_slots": [],
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-child-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="DOM slot probe found no public slots"):
        lifecycle._child_result(dom, "slotless.html")


def test_reflex_lifecycle_smoke_rejects_child_with_bad_dom_slots() -> None:
    lifecycle = _lifecycle_smoke_module()
    payload = {
        "status": "ok",
        "view_count": 1,
        "phase_names": list(lifecycle.LIFECYCLE_PHASES),
        "phase_count": len(lifecycle.LIFECYCLE_PHASES),
        "min_lit": 100,
        "labels": 4,
        "slot_count": 8,
        "missing_slots": ["canvas"],
        "unexpected_slots": [],
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-child-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="DOM slot probe found missing slots"):
        lifecycle._child_result(dom, "missing-slot.html")

    payload["missing_slots"] = []
    payload["unexpected_slots"] = ["plot"]
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-child-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="DOM slot probe found unexpected slots"):
        lifecycle._child_result(dom, "unexpected-slot.html")


def test_reflex_lifecycle_smoke_rejects_shell_without_reload_phase() -> None:
    lifecycle = _lifecycle_smoke_module()
    payload = {
        "status": "ok",
        "phases": 4,
        "phase_names": [
            "iframe-initial",
            "iframe-remount",
            "iframe-second-remount",
            "iframe-hidden-reveal",
        ],
        "assets": len(lifecycle.CHART_ASSETS),
        "reports": len(lifecycle.CHART_ASSETS) * 4,
        "critical_assets": list(lifecycle.CRITICAL_ASSETS),
        "critical_reports": len(lifecycle.CRITICAL_ASSETS) * 4,
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-shell-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="iframe shell lifecycle phases incomplete"):
        lifecycle._shell_result(dom, len(lifecycle.CHART_ASSETS))


def test_reflex_lifecycle_smoke_rejects_missing_any_shell_asset_phase_report() -> None:
    lifecycle = _lifecycle_smoke_module()
    expected_reports = len(lifecycle.CHART_ASSETS) * len(lifecycle.SHELL_PHASES)
    expected_critical_names = [
        f"{phase}:{asset}"
        for phase in lifecycle.SHELL_PHASES
        for asset in lifecycle.CRITICAL_ASSETS
    ]
    payload = {
        "status": "ok",
        "phases": len(lifecycle.SHELL_PHASES),
        "phase_names": list(lifecycle.SHELL_PHASES),
        "assets": len(lifecycle.CHART_ASSETS),
        "reports": expected_reports - 1,
        "critical_assets": list(lifecycle.CRITICAL_ASSETS),
        "critical_reports": len(expected_critical_names),
        "critical_report_names": expected_critical_names,
        "slot_count": expected_reports,
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-shell-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="iframe shell asset reports incomplete"):
        lifecycle._shell_result(dom, len(lifecycle.CHART_ASSETS))


def test_reflex_lifecycle_smoke_rejects_missing_critical_asset_phase_pair() -> None:
    lifecycle = _lifecycle_smoke_module()
    expected_names = [
        f"{phase}:{asset}"
        for phase in lifecycle.SHELL_PHASES
        for asset in lifecycle.CRITICAL_ASSETS
    ]
    critical_names = list(expected_names)
    critical_names[-1] = critical_names[0]
    payload = {
        "status": "ok",
        "phases": len(lifecycle.SHELL_PHASES),
        "phase_names": list(lifecycle.SHELL_PHASES),
        "assets": len(lifecycle.CHART_ASSETS),
        "reports": len(lifecycle.CHART_ASSETS) * len(lifecycle.SHELL_PHASES),
        "critical_assets": list(lifecycle.CRITICAL_ASSETS),
        "critical_reports": len(expected_names),
        "critical_report_names": critical_names,
        "slot_count": len(lifecycle.CHART_ASSETS) * len(lifecycle.SHELL_PHASES),
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    dom = f'<html><body data-fc-shell-lifecycle="{encoded}"></body></html>'

    with pytest.raises(SystemExit, match="critical asset phase coverage incomplete"):
        lifecycle._shell_result(dom, len(lifecycle.CHART_ASSETS))


def test_visual_regression_smoke_covers_flaky_dashboard_assets() -> None:
    constants = _dashboard_constants()
    visual = _visual_smoke_module()
    assert [name for name, _factory in visual.CASES] == [
        "scatter",
        "line_area",
        "grouped_bar",
        "histogram",
        "heatmap_annotations",
        "composed_dual_axis",
        "axes_scales_stress",
        "custom_chrome",
        "adaptive_density",
    ]
    expected_assets = {
        Path(chart["src"]).name for chart in constants["CHART_NAV"] if "plotly" not in chart["src"]
    }
    expected_assets.add("live_drilldown_10m.html")
    assert set(visual.ASSET_CASES) == expected_assets
    assert len(visual.ASSET_CASES) == len(set(visual.ASSET_CASES))
    assert "plotly_colored_scatter.html" not in visual.ASSET_CASES
    for asset in visual.ASSET_CASES:
        assert (CHART_ASSET_DIR / asset).is_file()
    assert [name for name, _asset, _ids in visual.CHROME_SHELL_CASES] == [
        "custom_chrome_reflex_shell",
        "annotated_heatmap_reflex_shell",
    ]
    shell_assets = [asset for _name, asset, _ids in visual.CHROME_SHELL_CASES]
    assert shell_assets == ["custom_chrome.html", "annotated_heatmap.html"]
    required_ids = {
        required_id for _name, _asset, ids in visual.CHROME_SHELL_CASES for required_id in ids
    }
    assert {
        "custom-chrome-frame",
        "custom-chrome-legend",
        "custom-chrome-tooltip",
        "annotated-heatmap-frame",
        "annotated-heatmap-legend",
        "annotated-heatmap-tooltip",
    } <= required_ids


def test_visual_regression_smoke_checks_layout_regions_not_just_blankness() -> None:
    source = VISUAL_SMOKE.read_text(encoding="utf-8")
    required = [
        "_assert_layout_regions",
        "_active_plot_cells",
        '"title"',
        '"plot"',
        '"x-axis"',
        '"y-axis"',
        "region is too empty",
        "region lost dark text/chrome",
        "chart collapsed in plot region",
        "plot region has too little colored chart data",
        "asset=True",
        "runner-specific",
        "x_axis_box = (0.08, 0.70, 0.94, 0.99)",
        '"x-axis": (700, 250 if asset else 40)',
        "CHROME_SHELL_CASES",
        "data-fc-custom-chrome-shell",
        "_write_chrome_shell",
        "_assert_chrome_shell_dom",
        "custom chrome shell missing nodes",
        "custom chrome shell hidden nodes",
    ]
    for marker in required:
        assert marker in source


def test_custom_chrome_chart_asset_disables_builtin_chrome() -> None:
    html = CUSTOM_CHROME_ASSET.read_text(encoding="utf-8")
    assert "xy.renderStandalone" in html
    assert "Custom Reflex legend + tooltip" in html
    assert "xy-custom-chrome" in html
    assert "window.__xyCustomChromeView" in html
    assert 'addEventListener("pointermove"' in html
    assert "_localRow(hit)" in html
    assert '"show_legend":false' in html
    assert '"show_tooltip":false' in html


def test_annotated_heatmap_uses_reflex_custom_chrome_bridge() -> None:
    html = ANNOTATED_HEATMAP_ASSET.read_text(encoding="utf-8")
    assert "xy.renderStandalone" in html
    assert "Annotated risk heatmap" in html
    assert "xy-annotated-heatmap" in html
    assert "window.__xyAnnotatedHeatmapView" in html
    assert 'addEventListener("pointermove"' in html
    assert "_localRow(hit)" in html
    assert '"show_legend":false' in html
    assert '"show_tooltip":false' in html
    assert '"risk_score"' in html
    assert '"72%"' in html
    assert '"96%"' in html


def test_small_business_chart_asset_exists() -> None:
    html = BUSINESS_ASSET.read_text(encoding="utf-8")
    assert "xy.renderStandalone" in html
    assert "Small business overview" in html
    assert "Revenue" in html
    assert "Pipeline" in html


def test_small_retention_cohort_asset_exists() -> None:
    html = RETENTION_ASSET.read_text(encoding="utf-8")
    assert "xy.renderStandalone" in html
    assert "Small retention cohort" in html
    assert "signup cohort" in html
    assert "retention" in html
