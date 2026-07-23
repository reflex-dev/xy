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

import numpy as np
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
    # The round-trip reply is an XYBF binary frame (no base64), decoded by the
    # same seam the browser's xy.decodeFrame uses; density grids ride as raw
    # buffers beside the compact JSON metadata.
    assert drill.headers["content-type"] == "application/octet-stream"
    from xy.channel import decode_frame

    frame = decode_frame(drill.content)
    assert frame.message["type"] == "density_update"
    assert frame.message["seq"] == 1
    assert frame.buffers  # the density grid rides raw, not base64 in JSON


# --- Reflex app structure (source text, no reflex import) -------------------


def test_reflex_app_shows_every_linking_method_and_event() -> None:
    src = REFLEX_APP.read_text(encoding="utf-8")
    required = [
        "@reflex_xy.figure",  # live figure var
        "reflex_xy.chart(",  # the component
        "reflex_xy.append(",  # streaming
        "reflex_xy.inline(",  # inline() token tier
        "sparkline_chart()",  # static Chart tier passed directly
        # the FastAPI 100M drilldown, served adapter-natively (§6); both apps
        # honor the same point-count override for side-by-side comparison.
        "def drilldown_chart",
        "reflex_xy.inline(drilldown_chart())",
        "XY_LIVE_POINTS",
        # an over-RAM request streams to disk memmaps in both apps (§27).
        "MemmapF64Builder",
        "def _drilldown_data",
        "XY_LIVE_POINTS_DIR",
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
    assert "reflex_xy.XYPlugin()" in cfg
    assert 'app_name="xy_reflex_demo"' in cfg


def test_reflex_app_introspection_and_composition(tmp_path, monkeypatch) -> None:
    pytest.importorskip("reflex")
    pytest.importorskip("reflex_xy")
    # A static chart compiles a payload asset into cwd/assets/xy; keep it in tmp.
    monkeypatch.chdir(tmp_path)
    # The §6 drilldown builds its columns at import; keep the test-time build
    # cheap (same override the fastapi app test uses).
    monkeypatch.setenv("XY_LIVE_POINTS", "50000")
    sys.path.insert(0, str(REFLEX_DIR))
    module = _load(REFLEX_APP, "xy_reflex_demo_under_test")

    # The Code accordion reads live source: figure vars unwrap to their builder,
    # event handlers to their function — both include the decorator line.
    assert "@reflex_xy.figure" in module._source(module.Demo.cloud)
    assert "def cloud" in module._source(module.Demo.cloud)
    assert "def on_view" in module._source(module.Demo.on_view)
    # The page composes without error and mints inline() tokens at import.
    assert module.ORBITS_TOKEN.startswith("xyin-")
    assert module.DRILLDOWN_TOKEN.startswith("xyin-")
    assert module.DRILLDOWN_POINTS == 50000
    assert module.index() is not None


# --- over-RAM XY_LIVE_POINTS requests spill to disk memmaps (§27) ------------
# Both drilldown hosts generate a dataset over 75% of physical RAM out to disk
# via xy._ooc.MemmapF64Builder and serve the memmap-backed columns directly.
# RAM detection is stubbed per-test so the threshold is exercised with small n.


@pytest.fixture(scope="module")
def drilldown_mod():
    pytest.importorskip("starlette")
    pytest.importorskip("anywidget")  # live_drilldown imports xy.widget
    sys.path.insert(0, str(FASTAPI_DIR))
    return _load(FASTAPI_DIR / "live_drilldown.py", "xy_example_live_drilldown")


def test_mmap_threshold_is_over_75_percent_of_ram(drilldown_mod, monkeypatch) -> None:
    mod = drilldown_mod
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 1000 * mod._BYTES_PER_POINT)
    assert not mod._mmap_needed(750)  # exactly 75% — stays in RAM
    assert mod._mmap_needed(751)  # over 75% — spills to disk
    # Unknown RAM (non-POSIX sysconf): keep the pre-mmap in-RAM behavior.
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: None)
    assert not mod._mmap_needed(10**12)


def test_over_ram_request_streams_to_disk_and_data_is_identical(
    drilldown_mod, monkeypatch, tmp_path
) -> None:
    from xy._ooc import backing_path, is_memmapped

    mod = drilldown_mod
    n = 4096
    in_ram = mod.colored_scatter_data(n)
    assert not any(is_memmapped(col) for col in in_ram)

    monkeypatch.setenv("XY_LIVE_POINTS_DIR", str(tmp_path / "cols"))
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: n * mod._BYTES_PER_POINT)
    spilled = mod.colored_scatter_data(n)
    for ram_col, disk_col in zip(in_ram, spilled, strict=True):
        assert is_memmapped(disk_col)
        path = backing_path(disk_col)
        assert path is not None and Path(path).is_relative_to(tmp_path / "cols")
        # The dataset is bit-identical wherever it lands (one chunk stream).
        np.testing.assert_array_equal(np.asarray(disk_col), ram_col)


def test_over_ram_figure_serves_from_the_memmapped_columns(
    drilldown_mod, monkeypatch, tmp_path
) -> None:
    from xy._ooc import is_memmapped

    mod = drilldown_mod
    n = 50_000
    monkeypatch.setenv("XY_LIVE_POINTS_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: n * mod._BYTES_PER_POINT)
    fig = mod.colored_scatter_figure(n)

    # x/y canonical live in the store as mapped bytes, nothing RAM-resident;
    # the color/size channels kept the same disk backing (no ingest copy).
    rep = fig.store.memory_report()
    assert rep["canonical_bytes"] == 0
    assert rep["canonical_mapped_bytes"] == n * 8 * 2
    trace = fig.traces[0]
    assert is_memmapped(trace.color_ch.values)
    assert is_memmapped(trace.size_ch.values)

    # The engine answers density views straight off the files.
    x0, x1 = fig.x_range()
    y0, y1 = fig.y_range()
    update, buffers = fig.density_view(0, x0, x1, y0, y1, 256, 192)
    assert buffers

    # Out-of-core traces ride the no-rescan aggregate ladder (LOD doc Phase-3
    # item 7): a deep zoom stays a density surface with its tier recorded in
    # `binning` — never an O(N) file rescan to drill exact points — the
    # colored trace keeps its mean-color plane, and a pick without a drill
    # subset degrades to None instead of crashing.
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = (x1 - x0) * 0.005, (y1 - y0) * 0.005
    deep, deep_buffers = fig.density_view(0, cx - dx, cx + dx, cy - dy, cy + dy, 256, 192)
    deep_trace = deep["traces"][0]
    assert deep_trace["mode"] == "density"
    assert deep_trace["binning"] == "bin2d-oversized" or deep_trace["binning"].startswith("pyramid")
    assert "rgba" in deep_trace["density"]
    assert deep_buffers
    assert fig.pick(0, 0, None) is None


def test_reflex_drilldown_spills_like_fastapi_and_matches_it(
    drilldown_mod, monkeypatch, tmp_path
) -> None:
    pytest.importorskip("reflex")
    pytest.importorskip("reflex_xy")
    from xy._ooc import is_memmapped

    monkeypatch.chdir(tmp_path)  # static-tier assets stay out of the repo
    monkeypatch.setenv("XY_LIVE_POINTS", "50000")  # cheap import-time token build
    sys.path.insert(0, str(REFLEX_DIR))
    module = _load(REFLEX_APP, "xy_reflex_demo_mmap_under_test")

    # Cross-host A/B contract: the two apps generate the identical dataset…
    n = 4096
    fastapi_cols = drilldown_mod.colored_scatter_data(n)
    for fastapi_col, reflex_col in zip(fastapi_cols, module._drilldown_data(n), strict=True):
        np.testing.assert_array_equal(fastapi_col, reflex_col)

    # …and spill it to disk past the same over-75%-of-RAM threshold.
    monkeypatch.setenv("XY_LIVE_POINTS_DIR", str(tmp_path / "cols"))
    monkeypatch.setattr(module, "_total_ram_bytes", lambda: n * module._BYTES_PER_POINT)
    spilled = module._drilldown_data(n)
    for fastapi_col, disk_col in zip(fastapi_cols, spilled, strict=True):
        assert is_memmapped(disk_col)
        np.testing.assert_array_equal(np.asarray(disk_col), fastapi_col)


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
