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
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
FASTAPI_DIR = EXAMPLES / "fastapi"
REFLEX_DIR = EXAMPLES / "reflex"
REFLEX_PACKAGE = REFLEX_DIR / "xy_reflex_demo"
REFLEX_APP = REFLEX_PACKAGE / "xy_reflex_demo.py"
REFLEX_DATA = REFLEX_PACKAGE / "data.py"
REFLEX_CHARTS = REFLEX_PACKAGE / "charts.py"
REFLEX_STATE = REFLEX_PACKAGE / "state.py"
REFLEX_COMPONENTS = REFLEX_PACKAGE / "components.py"


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


# --- Reflex terminal data and chart builders (numpy + xy only) -------------


@pytest.fixture(scope="module")
def terminal_data_mod():
    sys.path.insert(0, str(REFLEX_DIR))
    return importlib.import_module("xy_reflex_demo.data")


@pytest.fixture(scope="module")
def terminal_charts_mod():
    sys.path.insert(0, str(REFLEX_DIR))
    return importlib.import_module("xy_reflex_demo.charts")


def _chart_payload(chart):
    source = chart if hasattr(chart, "build_payload") else chart.figure()
    return source.build_payload()


def test_terminal_market_data_is_deterministic_and_valid(terminal_data_mod) -> None:
    symbols = terminal_data_mod.instrument_symbols()
    assert len(symbols) >= 8
    assert len(symbols) == len(set(symbols))
    assert terminal_data_mod.SIMULATED_DATA_LABEL.startswith("SIMULATED DATA · AS OF ")

    first = terminal_data_mod.history("AAPL", resolution="1D", range_key="MAX")
    second = terminal_data_mod.history("AAPL", resolution="1D", range_key="MAX")
    assert 700 <= len(first.x) <= 800  # three years of weekday observations
    for field in ("x", "open", "high", "low", "close", "volume"):
        np.testing.assert_array_equal(getattr(first, field), getattr(second, field))
        assert np.isfinite(getattr(first, field)).all()

    assert np.all(first.high >= np.maximum(first.open, first.close))
    assert np.all(first.low <= np.minimum(first.open, first.close))
    assert np.all(first.high >= first.low)
    assert np.all(first.volume >= 0)
    assert str(first.x[-1]) == terminal_data_mod.AS_OF.isoformat()

    weekly = terminal_data_mod.history("AAPL", resolution="1W", range_key="1Y")
    assert 45 <= len(weekly.x) <= 54
    assert np.all(weekly.high >= np.maximum(weekly.open, weekly.close))
    assert np.all(weekly.low <= np.minimum(weekly.open, weekly.close))


def test_terminal_reference_data_and_risk_are_reproducible(terminal_data_mod) -> None:
    assert terminal_data_mod.positions() == terminal_data_mod.positions()
    assert terminal_data_mod.stories() == terminal_data_mod.stories()
    assert terminal_data_mod.calendar_events() == terminal_data_mod.calendar_events()
    assert terminal_data_mod.portfolio_summary() == terminal_data_mod.portfolio_summary()

    equity = terminal_data_mod.portfolio_equity("1Y")
    returns = terminal_data_mod.portfolio_returns("1Y")
    assert len(equity.dates) == len(equity.equity) == len(equity.pnl)
    assert len(returns) == len(equity.equity) - 1
    assert np.isfinite(equity.equity).all()
    assert np.isfinite(equity.pnl).all()
    assert np.isfinite(returns).all()
    drawdown = equity.equity / np.maximum.accumulate(equity.equity) - 1.0
    assert np.all(drawdown <= 0)

    symbols, correlation = terminal_data_mod.correlation_matrix()
    assert correlation.shape == (len(symbols), len(symbols))
    np.testing.assert_allclose(correlation, correlation.T)
    np.testing.assert_allclose(np.diag(correlation), 1.0)
    assert np.isfinite(correlation).all()

    scenarios_95 = terminal_data_mod.stress_scenarios(95)
    assert scenarios_95 == terminal_data_mod.stress_scenarios(95)
    assert scenarios_95 != terminal_data_mod.stress_scenarios(99)
    assert all(np.isfinite(scenario.pnl) for scenario in scenarios_95)


def test_terminal_security_chart_exercises_finance_layers(terminal_charts_mod) -> None:
    chart = terminal_charts_mod.security_chart(
        "AAPL",
        range_key="1Y",
        resolution="1D",
        overlays=(
            "SMA 20",
            "EMA 50",
            "Bollinger bands",
            "VWAP",
            "Anchored VWAP",
            "Volume profile",
        ),
        oscillator="RSI",
        drawing="XABCD",
    )
    spec, _ = chart.build_payload()
    assert spec["traces"][0]["kind"] == "candlestick"
    assert {trace["name"] for trace in spec["traces"][1:]} >= {
        "SMA 20",
        "EMA 50",
        "VWAP",
    }
    layer_kinds = {layer["kind"] for layer in spec["layers"]}
    assert {"bollinger_bands", "anchored_vwap", "anchored_volume_profile", "rsi"} <= layer_kinds
    assert "xabcd_pattern" in layer_kinds

    position_chart = terminal_charts_mod.security_chart(
        "AAPL", range_key="6M", drawing="Long position"
    )
    position_spec, _ = position_chart.build_payload()
    position = next(layer for layer in position_spec["layers"] if layer["kind"] == "position")
    assert position["anchors"]["entry"]["x"] < position["anchors"]["end"]["x"]

    invalid_position_chart = terminal_charts_mod.security_chart(
        "AAPL",
        range_key="6M",
        drawing="Long position",
        ticket={
            "side": "Long",
            "entry": 100.0,
            "stop": 105.0,
            "target": 115.0,
            "account_size": 100_000.0,
            "risk_percent": 1.0,
        },
    )
    invalid_position_spec, _ = invalid_position_chart.build_payload()
    assert "position" not in {layer["kind"] for layer in invalid_position_spec["layers"]}


def test_terminal_landing_market_focus_uses_finance_chart(terminal_charts_mod) -> None:
    chart = terminal_charts_mod.market_focus_chart()
    spec, _ = chart.build_payload()

    assert spec["traces"][0]["kind"] == "candlestick"
    assert spec["tools"]["active"] == "forecast"
    layer_kinds = {layer["kind"] for layer in spec["layers"]}
    assert {
        "volume_bars",
        "moving_average",
        "anchored_vwap",
        "anchored_volume_profile",
        "macd",
        "position_forecast",
    } <= layer_kinds


def test_terminal_ticket_metrics_validate_long_and_short(terminal_charts_mod) -> None:
    long_metrics = terminal_charts_mod.ticket_metrics(
        {
            "side": "Long",
            "entry": 100.0,
            "stop": 95.0,
            "target": 115.0,
            "account_size": 100_000.0,
            "risk_percent": 1.0,
        }
    )
    assert long_metrics["valid"] is True
    assert long_metrics["risk_amount"] == pytest.approx(1_000.0)
    assert long_metrics["quantity"] == pytest.approx(200.0)
    assert long_metrics["risk_reward"] == pytest.approx(3.0)

    invalid = terminal_charts_mod.ticket_metrics(
        {
            "side": "Short",
            "entry": 100.0,
            "stop": 95.0,
            "target": 80.0,
            "account_size": 100_000.0,
            "risk_percent": 1.0,
        }
    )
    assert invalid["valid"] is False
    assert invalid["error"]


def test_terminal_workspace_chart_builders_emit_specs(terminal_charts_mod) -> None:
    charts = (
        terminal_charts_mod.market_focus_chart(),
        terminal_charts_mod.market_heatmap_chart(),
        terminal_charts_mod.yield_curve_chart(),
        terminal_charts_mod.market_pulse_chart(),
        terminal_charts_mod.portfolio_performance_chart(),
        terminal_charts_mod.portfolio_allocation_chart(),
        terminal_charts_mod.portfolio_contribution_chart(),
        terminal_charts_mod.portfolio_exposure_chart(),
        terminal_charts_mod.risk_distribution_chart(95),
        terminal_charts_mod.risk_correlation_chart(),
        terminal_charts_mod.risk_factor_chart(),
    )
    for chart in charts:
        spec, _ = _chart_payload(chart)
        assert spec["traces"] or spec.get("layers")
        assert spec.get("title")

    assert terminal_charts_mod.MARKET_FOCUS_CHART is not None
    assert terminal_charts_mod.MARKET_HEATMAP_CHART is not None
    assert terminal_charts_mod.YIELD_CURVE_CHART is not None
    abbreviated = terminal_charts_mod.abbreviated_spec()
    assert abbreviated["traces"][0]["kind"] == "candlestick"
    assert abbreviated["layer_count"] >= 3


# --- Reflex terminal structure (source text, no reflex import) -------------


def _terminal_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REFLEX_APP, REFLEX_STATE, REFLEX_COMPONENTS, REFLEX_CHARTS)
    )


def test_reflex_terminal_preserves_every_linking_tier_and_event() -> None:
    src = _terminal_source()
    required = [
        "class TerminalState",
        "@reflex_xy.figure",
        "reflex_xy.chart(",
        "reflex_xy.append(",
        "reflex_xy.inline(",
        "MARKET_FOCUS_CHART",
        "MARKET_HEATMAP_CHART",
        "on_hover=",
        "on_view_change=",
        "inspect.getsource",
        "@rx.event(background=True)",
        "async with self",
    ]
    for marker in required:
        assert marker in src, marker
    assert src.count("@rx.event(background=True)") == 1
    assert src.count("async def stream_quotes") == 1
    assert "_stream_generation" in src
    assert "generation != self._stream_generation" in src

    for workspace in ("Markets", "Security", "Portfolio", "Risk", "News"):
        assert workspace in src
    for command in ("MKTS", "DES", "PORT", "RISK", "NEWS", "HELP"):
        assert command in src

    # All linking tiers stay native to the adapter; no iframe/message bridge.
    assert "postMessage" not in src
    assert "rx.el.iframe" not in src
    assert "<iframe" not in src.lower()


def test_reflex_config_wires_the_xy_plugin() -> None:
    cfg = (REFLEX_DIR / "rxconfig.py").read_text(encoding="utf-8")
    assert "reflex_xy.XYPlugin()" in cfg
    assert 'app_name="xy_reflex_demo"' in cfg


def test_reflex_terminal_imports_and_composes_in_temporary_cwd(tmp_path, monkeypatch) -> None:
    pytest.importorskip("reflex")
    pytest.importorskip("reflex_xy")
    # Direct Chart payloads compile into cwd/assets/xy; keep generated files out
    # of the repository and prove the example does not depend on its launch cwd.
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(REFLEX_DIR))
    module = importlib.import_module("xy_reflex_demo.xy_reflex_demo")
    state = importlib.import_module("xy_reflex_demo.state")
    components = importlib.import_module("xy_reflex_demo.components")

    assert module.index() is not None
    assert module.app is not None
    assert state.TerminalState is not None
    assert components.YIELD_CURVE_TOKEN.startswith("xyin-")
    assert "@reflex_xy.figure" in components._source(state.TerminalState.security_figure)
    assert "def stream_quotes" in components._source(state.TerminalState.stream_quotes)
    assert (tmp_path / "assets" / "xy").is_dir()


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
