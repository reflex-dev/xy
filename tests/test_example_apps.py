"""Tests for the example apps: examples/fastapi and examples/reflex.

The core checks run on the framework-neutral ``charts.py`` builders and on
source text, so they need neither reflex nor fastapi. The framework-specific
checks skip when the extra is not importable.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
FASTAPI_DIR = EXAMPLES / "fastapi"
REFLEX_DIR = EXAMPLES / "reflex"
REFLEX_APP = REFLEX_DIR / "xy_reflex_demo" / "xy_reflex_demo.py"
BOND_DIR = EXAMPLES / "bond"
BOND_APP = BOND_DIR / "xy_bond_intro" / "xy_bond_intro.py"


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
        ["git", "ls-files", "examples/reflex", "examples/fastapi", "examples/bond"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    html = [p for p in tracked if p.endswith(".html")]
    assert html == [], f"the example apps must not commit static chart HTML: {html}"
    assert not (REFLEX_DIR / "assets" / "charts").exists()
    assert not (BOND_DIR / "assets" / "charts").exists()


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
        "@reflex_xy.data",  # data-bound columns (§1/§4/§8/§9)
        "data=Demo.cloud",  # composed chart bound to a data var (§1)
        "reflex_xy.scatter_chart(",  # flat data-bound factory (§8)
        "rx.cond(Demo.split",  # conditional chart rendering (§9)
        "rx.foreach(",  # chart-per-handle rendering (§9)
        "data=rx.cond(",  # conditional data source under one fixed plan (§10)
        "list[DataHandle[SensorCols]]",  # the typed handle collection (R7)
        "@reflex_xy.figure",  # escape hatch: chart structure from state (§2)
        "reflex_xy.chart(",  # the component / composed factory
        "reflex_xy.append(",  # streaming
        "reflex_xy.inline(",  # inline() token tier
        'data={"t": t',  # static tier: concrete columns -> payload asset (§5)
        "legend_series_chart()",  # static Chart tier passed directly (§7)
        # the FastAPI 100M drilldown, served adapter-natively (§6); both apps
        # honor the same point-count override for side-by-side comparison.
        "def drilldown_chart",
        "reflex_xy.inline(drilldown_chart())",
        "XY_LIVE_POINTS",
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

    # The Code accordion reads live source: figure/data vars unwrap to their
    # builder, event handlers to their function — both include the decorator.
    assert "@reflex_xy.data" in module._source(module.Demo.cloud)
    assert "def cloud" in module._source(module.Demo.cloud)
    assert "@reflex_xy.figure" in module._source(module.Demo.histogram)
    assert "def on_view" in module._source(module.Demo.on_view)
    assert "@reflex_xy.data" in module._source(module.Demo.bound_cloud)
    # The page composes without error and mints inline() handles at import.
    assert module.ORBITS.token.startswith("xyin-")
    assert module.DRILLDOWN.token.startswith("xyin-")
    assert module.DRILLDOWN_POINTS == 50000
    assert module.index() is not None
    # The /kinds page: all 20 data-bound kind plans compile (zero-row under
    # the structural probe), the composite kinds build on the static tier,
    # and one data var legally carries mixed-length plus 2-D columns.
    kinds_page = module.kinds()
    assert kinds_page is not None
    assert "kind-funnel" in str(kinds_page)
    columns = module._kind_columns()
    assert columns["grid"].ndim == 2
    assert len(columns["edges"]) == len(columns["counts"]) + 1
    assert columns["funnel_stage"].tolist() == ["Visit", "Signup", "Activate", "Pay"]
    assert len(columns["funnel_stage"]) == len(columns["funnel_value"])


# --- Reflex app: the 007 gun-barrel intro (examples/bond) --------------------
# The geometry is pure numpy, so the interesting invariants — constant row
# counts, stable row identity, a clean loop — are testable without reflex, a
# browser, or a server. Those three are what the engine's index-matched
# interpolation actually depends on, so they are pinned here rather than left to
# look right in a screenshot.


def _bond_module(name: str):
    """Import a bond example module by package path.

    ``charts.py`` and the app use relative imports, so they cannot be loaded as
    detached files the way the framework-neutral ``charts.py`` of the fastapi
    example can.
    """
    if str(BOND_DIR) not in sys.path:
        sys.path.insert(0, str(BOND_DIR))
    return importlib.import_module(f"xy_bond_intro.{name}")


@pytest.fixture(scope="module")
def bond_scene():
    return _bond_module("scene")


def test_bond_row_counts_are_constant_across_the_whole_cycle(bond_scene) -> None:
    """The contract `match="index"` interpolation rests on.

    A layer that changed length between frames would fall back to snapping
    (js/src/56_animation.ts records `snap:layout-mismatch`), and the sequence
    would stutter instead of tween.
    """
    times = [i * bond_scene.CYCLE / 64 for i in range(64)]
    shapes = [
        {name: len(col) for name, col in bond_scene.frame_columns(t, points=8_000).items()}
        for t in times
    ]
    assert all(shape == shapes[0] for shape in shapes[1:])
    # Every layer ships x, y and a shade, all float32 (no JSON numbers, §29).
    first = bond_scene.frame_columns(0.0, points=8_000)
    assert set(first) == {
        f"{layer}_{axis}"
        for layer in ("wash", "rifle", "ring", "fig", "flash", "blood")
        for axis in ("x", "y", "c")
    }
    assert all(col.dtype == "float32" for col in first.values())


def test_bond_frames_are_a_pure_function_of_the_clock(bond_scene) -> None:
    """The adapter re-runs a data method to rebuild columns on a fresh worker.

    If a frame depended on anything but the clock, that rebuild would hand back
    a different scene than the one the browser is mid-tween on.
    """
    import numpy as np

    for t in (0.0, 3.7, 7.42, 11.9):
        a = bond_scene.frame_columns(t, points=8_000)
        b = bond_scene.frame_columns(t, points=8_000)
        for name in a:
            np.testing.assert_array_equal(a[name], b[name], err_msg=name)
    # The cycle wraps rather than running off the end of the timeline.
    for name, col in bond_scene.frame_columns(bond_scene.CYCLE + 1.25, points=8_000).items():
        np.testing.assert_array_equal(col, bond_scene.frame_columns(1.25, points=8_000)[name])


def test_bond_loop_seam_has_nothing_visible_to_tween(bond_scene) -> None:
    """The last frame of the cycle and the first must agree.

    Interpolation makes a discontinuity here *worse* than a snap: the blood
    would streak back up the frame and the barrel dot would fly across it. The
    fade beat exists to close that seam, so it is pinned.
    """
    import numpy as np

    end = bond_scene.frame_columns(bond_scene.CYCLE - 1e-6, points=8_000)
    start = bond_scene.frame_columns(0.0, points=8_000)
    # Anything still lit at the seam has to be in the same place.
    for layer in ("wash", "rifle", "ring", "flash", "blood"):
        lit = np.maximum(end[f"{layer}_c"], start[f"{layer}_c"]) > 0.02
        for axis in ("x", "y"):
            drift = np.abs(end[f"{layer}_{axis}"][lit] - start[f"{layer}_{axis}"][lit])
            assert drift.max(initial=0.0) < 0.05, f"{layer}_{axis} jumps at the loop seam"
    # The blood is fully faded out by then, which is what licenses its depth
    # snapping back to zero.
    assert end["blood_c"].max() < 0.02


def test_bond_scene_stays_inside_the_stage_or_is_deliberately_parked(bond_scene) -> None:
    """Rows are parked outside the pinned domain, never smeared across it."""
    lo_x, hi_x = bond_scene.WORLD_X
    lo_y, hi_y = bond_scene.WORLD_Y
    for t in (0.0, 4.0, 7.5, 9.0, 14.0):
        columns = bond_scene.frame_columns(t, points=8_000)
        for layer in ("wash", "rifle", "ring", "fig", "flash"):
            xs, ys = columns[f"{layer}_x"], columns[f"{layer}_y"]
            assert xs.min() >= lo_x - 0.9 and xs.max() <= hi_x + 0.9, (layer, t)
            assert ys.min() >= lo_y - 2.0 and ys.max() <= hi_y + 2.0, (layer, t)
        # Before the bleed the blood waits *above* the frame, not inside it.
        if t < bond_scene.BEATS["bleed"][0]:
            assert columns["blood_y"].min() > hi_y


def test_bond_beats_tile_the_cycle_in_order(bond_scene) -> None:
    beats = bond_scene.BEATS
    for name, (start, end) in beats.items():
        assert 0.0 <= start < end <= bond_scene.CYCLE, name
    assert beats["open"][0] == 0.0
    assert beats["fade"][1] == bond_scene.CYCLE
    # The shot lands inside the aim beat's follow-through and starts the bleed.
    assert beats["aim"][1] <= beats["fire"][0] < beats["fire"][1]
    assert beats["bleed"][0] < beats["fire"][1]
    assert bond_scene.beat_label(0.1) == "open"
    assert bond_scene.beat_label(beats["fire"][0] + 0.01) == "fire"


def test_bond_stage_aspect_matches_the_world(bond_scene) -> None:
    """A circle only renders round if the plot rect carries this ratio."""
    lo_x, hi_x = bond_scene.WORLD_X
    lo_y, hi_y = bond_scene.WORLD_Y
    assert pytest.approx((hi_x - lo_x) / (hi_y - lo_y)) == bond_scene.WORLD_ASPECT


def test_bond_plan_is_scatter_only_and_pinned(bond_scene) -> None:
    """Every mark interpolates, and nothing can rescale the stage.

    `line` cannot draw a closed ring (it spans each column's min/max, filling
    the disc), and `triangle_mesh` is not one of the kinds
    `_preparePositionInterpolation` handles — so scatter is the only kind that
    both draws the scene and tweens.
    """
    charts = _bond_module("charts")
    columns = bond_scene.frame_columns(4.0, points=8_000)
    figure = charts.gun_barrel_chart(height=200, data=columns).figure()
    assert [trace.kind for trace in figure.traces] == ["scatter"] * 6
    # Density binning would dissolve the silhouette into a heatmap, so every
    # layer pins it off explicitly rather than relying on staying under the auto
    # threshold. Checked at the largest budget the UI offers too, so raising it
    # cannot quietly turn the artwork into a heatmap.
    assert all(trace.force_density is False for trace in figure.traces)
    assert not any(trace.use_density() for trace in figure.traces)
    biggest = charts.gun_barrel_chart(
        height=200, data=bond_scene.frame_columns(4.0, points=400_000)
    ).figure()
    assert not any(trace.use_density() for trace in biggest.traces)
    assert figure.animation_options["match"] == "index"
    assert figure.animation_options["update"] == "interpolate"
    assert figure.animation_options["duration"] == charts.FRAME_MS
    assert "position" in figure.animation_options["interpolate"]
    # The flip-book branch is the same plan with the tween off — same marks,
    # same row counts, only the update policy differs.
    off = charts.gun_barrel_chart(height=200, interpolate=False, data=columns).figure()
    assert off.animation_options["update"] == "none"
    assert [trace.kind for trace in off.traces] == [trace.kind for trace in figure.traces]
    assert [trace.n_points for trace in off.traces] == [trace.n_points for trace in figure.traces]


def test_bond_frame_renders_pixels_standalone(bond_scene) -> None:
    """One frame, no server: the plan paints, and the barrel is where it should be.

    `to_png` is the same path the README's stills come from, so this is the
    render guarantee behind the compile guarantee.
    """
    charts = _bond_module("charts")
    columns = bond_scene.frame_columns(4.2, points=40_000)
    height = 240
    png = charts.gun_barrel_chart(height=height, data=columns).to_png(scale=1.0)
    assert png.startswith(b"\x89PNG")
    width, png_height = struct.unpack(">II", png[16:24])
    assert png_height == height
    assert width == round(height * bond_scene.WORLD_ASPECT)


def test_bond_app_uses_the_data_bound_tier(bond_scene) -> None:
    src = BOND_APP.read_text(encoding="utf-8")
    for marker in (
        "@reflex_xy.data",  # columns only; the plan never moves
        "def scene(self) -> SceneCols",  # the R7 compile-time schema channel
        "reflex_xy.chart(",
        "data=Intro.scene",
        "gun_barrel_marks(",  # the one plan, shared with the still renderer
        "rx.cond(Intro.interpolate",  # both animation policies compile
        "background=True",  # the clock
        "time.monotonic() - self.clock",  # wall-anchored, never accumulated
        "on_animation_end=Intro.frame_rendered",  # the browser paces publishing
        "rx.match(",  # one compiled plan per tween duration
        "inspect.getsource",  # introspected code accordions
        "aspect_ratio=",  # the barrel stays round
        "XY_BOND_POINTS",
    ):
        assert marker in src, marker
    # Native linking, no iframe or postMessage bridge, and no committed HTML.
    assert "postMessage" not in src
    assert "iframe" not in src.lower()
    # The scene and plan modules must stay framework-neutral.
    scene_src = (BOND_DIR / "xy_bond_intro" / "scene.py").read_text(encoding="utf-8")
    assert "import reflex" not in scene_src
    assert "import xy" not in scene_src
    charts_src = (BOND_DIR / "xy_bond_intro" / "charts.py").read_text(encoding="utf-8")
    assert "import reflex" not in charts_src


def test_bond_config_wires_the_xy_plugin() -> None:
    cfg = (BOND_DIR / "rxconfig.py").read_text(encoding="utf-8")
    assert "reflex_xy.XYPlugin()" in cfg
    assert 'app_name="xy_bond_intro"' in cfg


def test_bond_page_composes_and_validates_its_plan(tmp_path, monkeypatch) -> None:
    pytest.importorskip("reflex")
    pytest.importorskip("reflex_xy")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XY_BOND_POINTS", "8000")
    module = _bond_module("xy_bond_intro")
    # Composing the page compiles both cond branches' plans, which is where the
    # marks' column names are checked against SceneCols.
    assert module.index() is not None
    assert "@reflex_xy.data" in module._source(module.Intro.scene)
    assert "def scene" in module._source(module.Intro.scene)
    assert "async def play" in module._source(module.Intro.play)
    # The UI menus may only offer counts the scene can actually build.
    for count in module.POINT_CHOICES.values():
        assert count >= 2_000
    # Untrusted select/slider payloads are resolved against the menus, not used.
    assert module._choice("nonsense", module.POINT_CHOICES, 8_000) == 8_000
    assert module._clamped_seconds([1e9]) == module.CYCLE
    assert module._clamped_seconds("not a list") == 0.0
    assert module._clamped_seconds([float("nan")]) == 0.0


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
