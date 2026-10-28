"""Missing samples preserve line topology in every payload tier."""

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy import interaction
from xy._figure import Figure
from xy.export import find_chromium


def _runs(spec, blob, trace):
    meta = spec["columns"][trace["runs"]]
    assert meta["dtype"] == "u32"
    return np.frombuffer(blob, dtype="<u4", count=meta["len"], offset=meta["byte_offset"])


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_missing_line_sample_keeps_binary_run_boundaries(bad):
    fig = Figure().line([0, 1, 2, 3, 4], [1, 9, bad, 2, 1], name="Actual")
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    assert len(spec["traces"]) == 1
    np.testing.assert_array_equal(_runs(spec, blob, trace), [0, 2, 4])
    assert trace["n_marks"] == 4
    assert fig.traces[0].n_points == 5


def test_line_gap_survives_m4_and_view_refinement(monkeypatch):
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 5)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 5)
    x = np.arange(100, dtype=float)
    y = np.sin(x)
    y[48:52] = np.nan
    fig = Figure(width=160).line(x, y)
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    assert trace["tier"] == "decimated"
    boundaries = _runs(spec, blob, trace)
    assert len(boundaries) == 3
    update, buffers = interaction.decimate_view(fig, 0, 99, 16)
    run = update["traces"][0]["runs"]
    refined = np.frombuffer(buffers[run["buf"]], dtype="<u4")
    assert len(refined) == 3
    assert refined[-1] == update["traces"][0]["x"]["len"]


@pytest.mark.parametrize(
    "x,y,expected",
    [
        ([0, 1, np.nan, 3, 4], [1, 1, 1, 1, 1], [0, 2, 4]),
        ([0, 1, 2, 3, 4], [np.nan, 1, np.nan, 1, np.nan], [0, 1, 2]),
        ([0, 1, 2], [np.nan, np.nan, np.nan], [0]),
    ],
)
def test_x_gaps_singletons_and_all_missing_are_preserved(x, y, expected):
    spec, blob = Figure().line(x, y).build_payload()
    np.testing.assert_array_equal(_runs(spec, blob, spec["traces"][0]), expected)


def test_source_rows_after_gap_point_to_exact_canonical_values():
    fig = Figure().line([0, 1, 2, 3, 4], [1, 9, np.nan, 2, 1])
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    meta = spec["columns"][trace["source_rows"]]
    rows = np.frombuffer(blob, dtype="<u4", count=meta["len"], offset=meta["byte_offset"])
    np.testing.assert_array_equal(rows, [0, 1, 3, 4])
    assert fig.pick(0, int(rows[2]))["x"] == 3


def test_appending_missing_values_rebuilds_finite_runs():
    fig = Figure().line([0, 1, 2, 3, 4], [1, 9, np.nan, 2, 1])
    fig.build_payload()
    fig.append(0, [5, 6], [np.nan, 1])
    spec, blob = fig.build_payload()
    np.testing.assert_array_equal(_runs(spec, blob, spec["traces"][0]), [0, 2, 4, 5])


def test_log_axis_rejected_sample_is_a_gap():
    chart = xy.line_chart(
        xy.line([0, 1, 2, 3, 4], [1, 2, -1, 2, 1]),
        xy.y_axis(type_="log", domain=(0.1, 10)),
    )
    spec, blob = chart.figure().build_payload()
    np.testing.assert_array_equal(_runs(spec, blob, spec["traces"][0]), [0, 2, 4])


def test_native_raster_has_empty_gap_and_retains_finite_line_ink():
    from xy._raster import to_rgba

    chart = xy.line_chart(
        xy.line(np.arange(7.0), [1, 1, 1, np.nan, 1, 1, 1], width=4),
        xy.x_axis(domain=(0, 6)),
        xy.y_axis(domain=(0, 2)),
        xy.legend(show=False),
        width=600,
        height=300,
    )
    image = to_rgba(chart.figure(), scale=1)
    blue = (image[:, :, 2].astype(int) > image[:, :, 0].astype(int) + 50) & (image[:, :, 3] > 100)
    assert not blue[:, 295:305].any()
    assert blue[:, 180:190].any()


@pytest.mark.parametrize("curve", [None, "smooth"])
def test_svg_does_not_join_missing_line_sample(curve):
    style = {} if curve is None else {"curve": curve}
    fig = Figure().line([0, 1, 2, 3, 4], [1, 9, np.nan, 2, 1], **style)
    svg = fig.to_svg()
    import re

    paths = re.findall(r'<path d="([^"]*)"[^>]*fill="none"', svg)
    assert any(path.count("M ") == 2 for path in paths)


@pytest.mark.parametrize("mode", ["linear", "smooth", "step", "polar", "log"])
@pytest.mark.parametrize("dpr", [1, 2])
def test_browser_draws_separate_finite_runs_and_keeps_source_hover(tmp_path, mode, dpr):
    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    options = {"curve": "smooth"} if mode == "smooth" else {}
    if mode == "step":
        options["where"] = "post"
    chart_kind = xy.polar_chart if mode == "polar" else xy.line_chart
    chart = chart_kind(
        (xy.step if mode == "step" else xy.line)(
            np.arange(7.0), [1, 2, 1, np.nan, 1, 2, 1], **options
        ),
        xy.y_axis(type_="log") if mode == "log" else xy.y_axis(),
        xy.legend(show=False),
        width=600,
        height=300,
    )
    document = chart.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.gapView = " + call)
    probe = """
    <script>
    try {
      const view = window.gapView; view._drawNow(); view._raf = null;
      const g = view.gpuTraces[0], counts = [];
      const gl = view.gl, original = gl.drawArraysInstanced;
      gl.drawArraysInstanced = function(mode, first, vertices, instances) {
        counts.push(instances); return original.call(this, mode, first, vertices, instances);
      };
      const xr = view._axisRange(g.xAxis), yr = view._axisRange(g.yAxis);
      view._drawLine(g, view._map(g.xMeta, ...xr, g.xAxis), view._map(g.yMeta, ...yr, g.yAxis));
      gl.drawArraysInstanced = original;
      const row = view._localRow({g, trace:g.trace.id, index:3});
      const requests = []; view.comm = {send:request=>requests.push(request)};
      const point = view._projectDataPoint(g.xAxis, g.yAxis, 4, 1, view._polarGeometry());
      const rect = view.canvas.getBoundingClientRect();
      view.canvas.dispatchEvent(new PointerEvent('pointermove', {
        clientX:rect.left + point[0] - view.plot.x,
        clientY:rect.top + point[1] - view.plot.y, pointerId:1, bubbles:true
      }));
      g._transitionMatch = {pairs:[[0,0]],fallback:null};
      const interpolated = view._preparePositionInterpolation(g, g, {update:'interpolate',interpolate:['position']});
      document.body.setAttribute('data-line-gaps', JSON.stringify({
        counts, ranges:g._lineRanges, source:Array.from(g._sourceRows), row,
        requests, hovered:view._lastRow, interpolated, fallback:g._transitionMatch.fallback,
        appended:view._appendTraceInPlace(g,g.trace,view.spec,g.trace,null),
        finite:Array.from(g._dashX).every(Number.isFinite) && Array.from(g._dashY).every(Number.isFinite),
        glError:gl.getError()
      }));
    } catch(error) {document.body.setAttribute('data-line-gaps-error', String(error.stack || error));}
    </script>
    """
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "gaps.html",
        "data-line-gaps",
        label="finite line runs",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    assert len(result["ranges"]) == len(result["counts"]) == 2
    assert result["finite"]
    assert result["glError"] == 0
    assert result["source"] == [0, 1, 2, 4, 5, 6]
    assert result["row"]["index"] == 4
    assert result["row"]["x"] == 4
    assert result["hovered"]["index"] == result["requests"][-1]["index"] == 4
    assert result["hovered"]["x"] == 4
    assert not result["interpolated"] and result["fallback"] == "snap:line-gaps"
    assert not result["appended"]


def test_browser_refinement_and_home_fallback_use_their_own_source_rows(tmp_path, monkeypatch):
    import base64
    import json

    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 5)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 5)
    x = np.arange(100.0)
    y = np.ones(100)
    y[48:52] = np.nan
    fig = xy.line_chart(xy.line(x, y), xy.legend(show=False), width=600, height=300).figure()
    document = fig.to_html()
    updates, buffers = interaction.decimate_view(fig, 60, 90, 16)
    payload = json.dumps(
        {"updates": updates["traces"], "buffers": [base64.b64encode(b).decode() for b in buffers]}
    )
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.gapView = " + call)
    probe = """
    <script>
    try {
      const view=window.gapView; view._drawNow(); view._raf=null;
      const g=view.gpuTraces[0], home=g._homeDecimated;
      const payload=PAYLOAD;
      const buffers=payload.buffers.map(text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0)).buffer);
      view.view.ranges.x=[60,90]; view.view.x0=60;view.view.x1=90;
      view._onKernelMsg({type:'tier_update',seq:view.seq,traces:payload.updates},buffers);
      const refined={ranges:g._lineRanges.length,source:Array.from(g._sourceRows)};
      view.view.ranges.x=[0,99];view.view.x0=0;view.view.x1=99;view._drawNow();
      const p=view._projectDataPoint('x','y',6,1);
      const hit=view._hoverAt(p[0]-view.plot.x,p[1]-view.plot.y);
      const row=hit?view._localRow(hit):null;
      document.body.setAttribute('data-line-home',JSON.stringify({
        refined, homeRanges:home._lineRanges.length,usesHome:hit?.g===home,row,
        glError:view.gl.getError()
      }));
    } catch(error) {document.body.setAttribute('data-line-home-error',String(error.stack||error));}
    </script>
    """.replace("PAYLOAD", payload)
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "home-gaps.html",
        "data-line-home",
        label="gap refinement and home fallback",
    )
    assert result["refined"]["ranges"] == 1
    assert all(row >= 60 for row in result["refined"]["source"])
    assert result["homeRanges"] == 2 and result["usesHome"]
    assert result["row"]["index"] == 6 and result["row"]["x"] == 6
    assert result["glError"] == 0
