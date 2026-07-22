"""Tests for the example apps: examples/fastapi and examples/reflex.

The core checks run on the framework-neutral ``charts.py`` builders and on
source text, so they need neither reflex nor fastapi. The framework-specific
checks skip when the extra is not importable.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
FASTAPI_DIR = EXAMPLES / "fastapi"
REFLEX_DIR = EXAMPLES / "reflex"
REFLEX_APP = REFLEX_DIR / "xy_reflex_demo" / "xy_reflex_demo.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- no committed static HTML -----------------------------------------------


def test_examples_commit_no_static_chart_html() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "examples/reflex", "examples/fastapi"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    html = [p for p in tracked if p.endswith(".html")]
    assert html == [], f"the example apps must not commit static chart HTML: {html}"
    assert not (REFLEX_DIR / "assets" / "charts").exists()


# --- framework-neutral gallery builders (numpy + xy only) -------------------


@pytest.fixture(scope="module")
def charts_mod():
    sys.path.insert(0, str(FASTAPI_DIR))
    return _load(FASTAPI_DIR / "charts.py", "xy_example_charts")


def test_gallery_ids_are_unique_and_wellformed(charts_mod) -> None:
    ids = [info.id for info in charts_mod.GALLERY]
    assert ids, "gallery is empty"
    assert len(ids) == len(set(ids)), "duplicate chart ids"
    for info in charts_mod.GALLERY:
        assert info.id == info.id.lower()
        assert " " not in info.id
        assert info.title.strip() and info.subtitle.strip()
        assert callable(info.builder)
    assert {info.id: info for info in charts_mod.GALLERY} == charts_mod.BY_ID


def test_gallery_builders_render_standalone_and_introspect(charts_mod) -> None:
    # Introspection must work for every builder (it feeds the Code accordion)…
    for info in charts_mod.GALLERY:
        src = inspect.getsource(info.builder)
        assert src.strip().startswith("def "), info.id
    # …and a representative, quick-to-build subset renders standalone HTML.
    for chart_id in ("business-overview", "line-walk", "composed-layers", "annotated-heatmap"):
        html = charts_mod.BY_ID[chart_id].builder().to_html()
        assert "renderStandalone" in html, chart_id
        assert "var xy=" in html, chart_id  # minified IIFE namespace (window.xy)


# --- FastAPI app routes (needs fastapi + httpx) -----------------------------


def test_fastapi_app_serves_live_charts_and_code() -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    os.environ["XY_LIVE_POINTS"] = "50000"  # keep the drilldown build cheap
    sys.path.insert(0, str(FASTAPI_DIR))
    app_mod = _load(FASTAPI_DIR / "app.py", "xy_example_fastapi_app")
    client = TestClient(app_mod.app)

    index = client.get("/")
    assert index.status_code == 200
    assert "<details>" in index.text  # code accordions
    assert "/chart/line-walk" in index.text  # gallery iframe

    chart = client.get("/chart/line-walk")
    assert chart.status_code == 200
    assert "renderStandalone" in chart.text
    assert client.get("/chart/does-not-exist").status_code == 404

    code = client.get("/code/line-walk")
    assert code.status_code == 200
    assert "def line_walk" in code.text  # live source, not a saved string

    assert client.get("/healthz").status_code == 200
    assert client.get("/drilldown").status_code == 200

    drill = client.post(
        "/api/xy/drilldown",
        json={
            "type": "density_view",
            "trace": 0,
            "x0": -1,
            "x1": 1,
            "y0": -1,
            "y1": 1,
            "w": 128,
            "h": 96,
            "seq": 1,
            "client_id": "t",
        },
    )
    assert drill.status_code == 200
    assert "density_update" in drill.text


# --- Reflex app structure (source text, no reflex import) -------------------


def test_reflex_app_shows_every_linking_method_and_event() -> None:
    src = REFLEX_APP.read_text(encoding="utf-8")
    required = [
        "@reflex_xy.figure",  # live figure var
        "reflex_xy.chart(",  # the component
        "reflex_xy.append(",  # streaming
        "reflex_xy.inline(",  # inline() token tier
        "sparkline_chart()",  # static Chart tier passed directly
        "on_point_hover=",
        "on_point_click=",
        "on_select_end=",
        "on_view_change=",
        # click/hover are off by default, so on_point_click needs them enabled.
        "interaction_config(hover=True, click=True)",
        "inspect.getsource",  # introspected code accordions
        "def code_accordion",
    ]
    for marker in required:
        assert marker in src, marker
    # The showcase links charts natively, without iframe or postMessage bridges.
    assert "postMessage" not in src
    assert "/charts/" not in src
    assert "iframe" not in src.lower()


def test_reflex_config_wires_the_xy_plugin() -> None:
    cfg = (REFLEX_DIR / "rxconfig.py").read_text(encoding="utf-8")
    assert "rx.plugins.RadixThemesPlugin()" in cfg
    assert "reflex_xy.XYPlugin()" in cfg
    assert 'app_name="xy_reflex_demo"' in cfg


def test_reflex_app_introspection_and_composition(tmp_path, monkeypatch) -> None:
    pytest.importorskip("reflex")
    pytest.importorskip("reflex_xy")
    # A static chart compiles a payload asset into cwd/assets/xy; keep it in tmp.
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(REFLEX_DIR))
    module = _load(REFLEX_APP, "xy_reflex_demo_under_test")

    # The Code accordion reads live source: figure vars unwrap to their builder,
    # event handlers to their function — both include the decorator line.
    assert "@reflex_xy.figure" in module._source(module.Demo.cloud)
    assert "def cloud" in module._source(module.Demo.cloud)
    assert "def on_view" in module._source(module.Demo.on_view)
    # The page composes without error and mints an inline() token at import.
    assert module.ORBITS_TOKEN.startswith("xyin-")
    assert module.index() is not None


# --- retargeted browser smokes: import cleanly, pure helpers unit-tested -----


@pytest.fixture(scope="module")
def lifecycle_mod():
    return _load(ROOT / "scripts" / "reflex_lifecycle_smoke.py", "reflex_lifecycle_smoke")


@pytest.fixture(scope="module")
def visual_mod():
    return _load(ROOT / "scripts" / "visual_regression_smoke.py", "visual_regression_smoke")


def test_smokes_cover_the_whole_gallery(lifecycle_mod, visual_mod, charts_mod) -> None:
    gallery_ids = tuple(info.id for info in charts_mod.GALLERY)
    assert gallery_ids == lifecycle_mod.GALLERY_IDS
    assert gallery_ids == visual_mod.GALLERY_IDS
    assert lifecycle_mod.DRILLDOWN_PATH == "/drilldown"
    assert visual_mod.DRILLDOWN_PATH == "/drilldown"


def test_lifecycle_phases_and_dom_slots() -> None:
    mod = _load(ROOT / "scripts" / "reflex_lifecycle_smoke.py", "reflex_lifecycle_smoke")
    assert mod.LIFECYCLE_PHASES[0] == "initial"
    assert mod.LIFECYCLE_PHASES[-1] == "restore"
    assert "context-restore" in mod.LIFECYCLE_PHASES
    assert set(mod.REQUIRED_RUNTIME_DOM_SLOTS) == {"root", "chrome", "canvas", "labels"}


def test_lifecycle_check_report_accepts_good_and_rejects_regressions(lifecycle_mod) -> None:
    phases = list(lifecycle_mod.LIFECYCLE_PHASES)

    def result(**over):
        base = {
            "phase_names": phases,
            "min_lit": 5000,
            "dom_slots": {"missing": [], "unexpected": []},
            "destroyed": False,
            "title": "t",
        }
        base.update(over)
        return base

    good = {"view_count": 1, "phase_names": phases, "results": [result()]}
    assert lifecycle_mod._check_report(good, "ok") == 5000

    for bad in (
        {"view_count": 0, "phase_names": phases, "results": []},
        {"view_count": 1, "phase_names": phases[:-1], "results": [result()]},
        {"view_count": 1, "phase_names": phases, "results": [result(min_lit=0)]},
        {"view_count": 1, "phase_names": phases, "results": [result(destroyed=True)]},
        {
            "view_count": 1,
            "phase_names": phases,
            "results": [result(dom_slots={"missing": ["canvas"], "unexpected": []})],
        },
    ):
        with pytest.raises(SystemExit):
            lifecycle_mod._check_report(bad, "bad")


def test_visual_smoke_viewport_and_helpers(visual_mod) -> None:
    assert (visual_mod.VIEW_W, visual_mod.VIEW_H) == (900, 470)
    assert len(visual_mod.PLOT_BOX) == 4
    assert "data-xy-label-kind='tick'" in visual_mod._OVERLAP_EXPR
