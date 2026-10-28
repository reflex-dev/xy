"""Connected fills preserve missing samples without changing canonical rows."""

import re

import numpy as np
import pytest

from xy import interaction
from xy._figure import Figure


def _u32(spec, blob, ref):
    meta = spec["columns"][ref]
    return np.frombuffer(blob, dtype="<u4", count=meta["len"], offset=meta["byte_offset"])


@pytest.mark.parametrize("kind", ["area", "error_band"])
@pytest.mark.parametrize("column", ["x", "top", "base"])
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_area_missing_sample_ships_finite_runs(kind, column, bad):
    values = {"x": np.arange(7.0), "top": np.full(7, 3.0), "base": np.ones(7)}
    values[column][3] = bad
    fig = Figure()
    if kind == "area":
        fig.area(values["x"], values["top"], base=values["base"])
    else:
        fig.error_band(values["x"], values["base"], values["top"])
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    np.testing.assert_array_equal(_u32(spec, blob, trace["runs"]), [0, 3, 6])
    np.testing.assert_array_equal(_u32(spec, blob, trace["source_rows"]), [0, 1, 2, 4, 5, 6])
    assert fig.traces[0].n_points == 7


@pytest.mark.parametrize("curve", ["linear", "smooth"])
def test_svg_area_has_two_closed_polygons(curve):
    svg = Figure().area(np.arange(7.0), [3, 3, 3, np.nan, 3, 3, 3], base=1, curve=curve).to_svg()
    paths = re.findall(r'<path d="([^"]*)"[^>]*fill-opacity=', svg)
    assert any(path.count("M ") == 2 and path.count("Z") == 2 for path in paths)


def test_area_refine_preserves_runs_and_baseline_extrema(monkeypatch):
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 10)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 10)
    x = np.arange(1000.0)
    top = np.full(1000, 10.0)
    base = np.zeros(1000)
    top[500] = np.nan
    base[77] = 9
    fig = Figure().area(x, top, base=base)
    spec, blob = fig.build_payload()
    rows = _u32(spec, blob, spec["traces"][0]["source_rows"])
    assert 77 in rows
    update, buffers = interaction.decimate_view(fig, 0, 999, 16)
    trace = update["traces"][0]
    rows = np.frombuffer(buffers[trace["source_rows"]["buf"]], dtype="<u4")
    assert 77 in rows
    assert len(np.frombuffer(buffers[trace["runs"]["buf"]], dtype="<u4")) == 3


def test_native_area_gap_is_empty_and_finite_fill_remains():
    import xy
    from xy._raster import to_rgba

    chart = xy.area_chart(
        xy.area(
            np.arange(7.0),
            [3, 3, 3, np.nan, 3, 3, 3],
            base=1,
            color="#2563eb",
            opacity=1,
            line_width=0,
        ),
        xy.x_axis(domain=(0, 6)),
        xy.y_axis(domain=(0, 4)),
        xy.legend(show=False),
        width=600,
        height=300,
    )
    image = to_rgba(chart.figure(), scale=1)
    blue = (image[:, :, 2].astype(int) > image[:, :, 0].astype(int) + 50) & (image[:, :, 3] > 100)
    assert not blue[:, 295:305].any()
    assert blue[:, 180:190].any()


@pytest.mark.parametrize(
    ("kind", "curve"),
    [
        (kind, curve)
        for kind in ("area", "error_band")
        for curve in ("linear", "smooth", "polar", "log")
        if (kind, curve) != ("error_band", "polar")
    ],
)
@pytest.mark.parametrize("dpr", [1, 2])
def test_browser_area_gap_pixel_and_source_hover(tmp_path, kind, curve, dpr):
    import xy
    from conftest import run_browser_probe
    from xy.export import find_chromium

    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    options = {"curve": "smooth"} if curve == "smooth" and kind == "area" else {}
    mark = (
        xy.area(np.arange(7.0), [3, 3, 3, np.nan, 3, 3, 3], base=1, line_width=0, **options)
        if kind == "area"
        else xy.error_band(np.arange(7.0), np.ones(7), [3, 3, 3, np.nan, 3, 3, 3])
    )
    chart = (xy.polar_chart if curve == "polar" else xy.area_chart)(
        mark,
        xy.x_axis(domain=(0, 6)),
        xy.y_axis(type_="log", domain=(0.5, 4)) if curve == "log" else xy.y_axis(domain=(0, 4)),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=720,
        height=300,
    )
    document = chart.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.areaGapView = " + call)
    probe = """
    <script>
    try {
      const view=window.areaGapView, results=[];
      for(const width of [720,380,720]) {
        view.fluid=true;view.fluidH=true;view.root.style.width=width+'px';view._resize(width,300);
        if(view._raf)cancelAnimationFrame(view._raf);view._raf=null;view._drawNow();
        const g=view.gpuTraces[0];
        const pixels=(x,y)=>{const p=view._projectDataPoint('x','y',x,y);const rgba=new Uint8Array(4);
          view.gl.readPixels(Math.round((p[0]-view.plot.x)*view.dpr),view.canvas.height-1-Math.round((p[1]-view.plot.y)*view.dpr),1,1,view.gl.RGBA,view.gl.UNSIGNED_BYTE,rgba);return Array.from(rgba);};
        const point=view._projectDataPoint('x','y',4,3), gap=view._projectDataPoint('x','y',3,3);
        const hit=view._hoverAt(point[0]-view.plot.x,point[1]-view.plot.y);
        results.push({width,ranges:g._lineRanges,row:hit?view._localRow(hit):null,
          gapHit:view._hoverAt(gap[0]-view.plot.x,gap[1]-view.plot.y),
          gap:pixels(3,2),finite:pixels(1,2), source:Array.from(g._sourceRows),glError:view.gl.getError(),
          finiteBuffers:[g._dashX,g._dashY,g._dashBase].every(a=>Array.from(a).every(Number.isFinite))});
      }
      document.body.setAttribute('data-area-gaps',JSON.stringify(results));
    } catch(error) {document.body.setAttribute('data-area-gaps-error',String(error.stack||error));}
    </script>
    """
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "area-gaps.html",
        "data-area-gaps",
        label="area finite runs",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    for case in result:
        assert len(case["ranges"]) == 2
        assert case["source"] == [0, 1, 2, 4, 5, 6]
        assert case["row"]["index"] == case["row"]["x"] == 4
        assert case["gapHit"] is None
        assert case["finiteBuffers"] and case["glError"] == 0
        if curve != "polar":
            assert case["gap"][3] == 0
            assert case["finite"][3] > 0


@pytest.mark.parametrize("kind", ["area", "error_band"])
def test_browser_area_refinement_home_fallback_keeps_original_rows(tmp_path, monkeypatch, kind):
    import base64
    import json

    import xy
    from conftest import run_browser_probe
    from xy.export import find_chromium

    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 5)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 5)
    x = np.arange(100.0)
    y = np.full(100, 3.0)
    y[48:52] = np.nan
    mark = xy.area(x, y, base=1) if kind == "area" else xy.error_band(x, np.ones(100), y)
    fig = xy.area_chart(
        mark, xy.legend(show=False), xy.modebar(show=False), width=600, height=300
    ).figure()
    document = fig.to_html()
    updates, buffers = interaction.decimate_view(fig, 60, 90, 16)
    payload = json.dumps(
        {"updates": updates["traces"], "buffers": [base64.b64encode(b).decode() for b in buffers]}
    )
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.areaGapView = " + call)
    probe = """
    <script>
    try {
      const view=window.areaGapView;view._drawNow();view._raf=null;
      const g=view.gpuTraces[0],home=g._homeDecimated,payload=PAYLOAD;
      const buffers=payload.buffers.map(text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0)).buffer);
      view.view.ranges.x=[60,90];view.view.x0=60;view.view.x1=90;
      view._onKernelMsg({type:'tier_update',seq:view.seq,traces:payload.updates},buffers);view._drawNow();
      const refined={ranges:g._lineRanges.length,source:Array.from(g._sourceRows)};
      view.view.ranges.x=[0,99];view.view.x0=0;view.view.x1=99;view._drawNow();
      const p=view._projectDataPoint('x','y',6,3),hit=view._hoverAt(p[0]-view.plot.x,p[1]-view.plot.y);
      document.body.setAttribute('data-area-home',JSON.stringify({refined,homeRanges:home._lineRanges.length,usesHome:hit?.g===home,row:hit?view._localRow(hit):null,glError:view.gl.getError()}));
    } catch(error) {document.body.setAttribute('data-area-home-error',String(error.stack||error));}
    </script>
    """.replace("PAYLOAD", payload)
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "area-home.html",
        "data-area-home",
        label="area home fallback",
    )
    assert result["refined"]["ranges"] == 1
    assert all(row >= 60 for row in result["refined"]["source"])
    assert result["homeRanges"] == 2 and result["usesHome"]
    assert result["row"]["index"] == result["row"]["x"] == 6
    assert result["glError"] == 0


@pytest.mark.parametrize("kind", ["area", "error_band"])
def test_finite_decimated_area_keeps_base_and_thickness_extrema(monkeypatch, kind):
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 10)
    x = np.arange(10_000.0)
    top = np.full(len(x), 6.0)
    base = np.full(len(x), 5.0)
    top[70], base[70] = 10, 9
    top[75], base[75] = 1, 0
    top[77], base[77] = 9, 1  # Thickness peak is neither boundary's extremum.
    top[5001], base[5001] = 6, -9  # Baseline peak under a flat upper boundary.
    fig = Figure(width=160)
    (fig.area(x, top, base=base) if kind == "area" else fig.error_band(x, base, top))
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    meta = spec["columns"][trace["x"]]
    raw = np.frombuffer(blob, dtype="<f4", count=meta["len"], offset=meta["byte_offset"])
    emitted = raw / meta.get("scale", 1) + meta.get("offset", 0)
    assert 77 in emitted and 5001 in emitted
    np.testing.assert_array_equal(fig.traces[0].y.values, top)
    np.testing.assert_array_equal(fig.traces[0].base.values, base)


@pytest.mark.parametrize(
    "top,expected", [([np.nan, 3, np.nan, 3, np.nan], [0, 1, 2]), ([np.nan] * 5, [0])]
)
def test_filled_singletons_and_all_missing_do_not_connect(top, expected):
    fig = Figure().area(np.arange(5.0), top, base=1)
    spec, blob = fig.build_payload()
    np.testing.assert_array_equal(_u32(spec, blob, spec["traces"][0]["runs"]), expected)
    svg = fig.to_svg()
    assert "nan" not in svg.lower()


def test_log_invalid_baseline_creates_a_gap():
    import xy

    chart = xy.area_chart(
        xy.area(np.arange(7.0), np.full(7, 3.0), base=[1, 1, 1, 0, 1, 1, 1]),
        xy.y_axis(type_="log", domain=(0.1, 4)),
    )
    spec, blob = chart.figure().build_payload()
    np.testing.assert_array_equal(_u32(spec, blob, spec["traces"][0]["runs"]), [0, 3, 6])
