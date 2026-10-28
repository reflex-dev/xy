"""Cartesian GPU placement must preserve offset-encoded small spans."""

import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium


@pytest.mark.parametrize("offset", [0, 1e9, 1e12])
@pytest.mark.parametrize("kind", ["line", "scatter", "area"])
@pytest.mark.parametrize("dpr", [1, 2])
def test_offset_cartesian_pixels_match_cpu_projection(tmp_path, offset, kind, dpr):
    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    x = [offset + 100, offset + 500, offset + 900]
    y = [offset + 450] * 3
    if kind == "area":
        mark = xy.area(x, y, base=[offset + 350] * 3, color="#0000ff", opacity=1, animation=False)
    elif kind == "scatter":
        mark = xy.scatter(x, y, color="#0000ff", size=8, animation=False)
    else:
        mark = xy.line(x, y, color="#0000ff", width=3, animation=False)
    chart = xy.line_chart(
        mark,
        xy.x_axis(domain=(offset, offset + 1000)),
        xy.y_axis(domain=(offset - 300, offset + 500)),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=720,
        height=360,
    )
    document = chart.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.precisionView = " + call)
    probe = """
    <script>try {
      const v=window.precisionView,results=[];
      for(const width of [720,380]) {
        v.fluid=true;v.fluidH=true;v.root.style.width=width+'px';v._resize(width,360);v._drawNow();v.gl.finish();
        const q=v._projectDataPoint('x','y',OFFSET+500,OFFSET+VALUE);
        const px=Math.round((q[0]-v.plot.x)*v.dpr),py=v.canvas.height-1-Math.round((q[1]-v.plot.y)*v.dpr);
        const rgba=new Uint8Array(4);v.gl.bindFramebuffer(v.gl.FRAMEBUFFER,null);v.gl.readPixels(px,py,1,1,v.gl.RGBA,v.gl.UNSIGNED_BYTE,rgba);
        results.push({width,rgba:Array.from(rgba),projected:q,gl:v.gl.getError()});
      }
      document.body.setAttribute('data-precision',JSON.stringify({results}));
    }catch(e){document.body.setAttribute('data-precision-error',String(e.stack||e));}</script>
    """.replace("OFFSET", str(offset)).replace("VALUE", "400" if kind == "area" else "450")
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "precision.html",
        "data-precision",
        label="offset GPU geometry",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    for sample in result["results"]:
        assert sample["gl"] == 0
        assert sample["rgba"][2] > 200 and sample["rgba"][3] > 200, sample


@pytest.mark.parametrize("kind", ["line", "area"])
@pytest.mark.parametrize("offset", [1e9, 1e12])
@pytest.mark.parametrize("dpr", [1, 2])
def test_offset_refinement_keeps_pixel_projection(tmp_path, monkeypatch, kind, offset, dpr):
    import base64
    import json

    import numpy as np

    from xy import interaction

    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 5)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 5)
    x = offset + np.arange(1000.0)
    y = np.full(1000, offset + 450)
    y[480:520] = np.nan
    mark = (
        xy.line(x, y, color="#0000ff", width=3, animation=False)
        if kind == "line"
        else xy.area(
            x, y, base=np.full(1000, offset + 350), color="#0000ff", opacity=1, animation=False
        )
    )
    fig = xy.line_chart(
        mark,
        xy.x_axis(domain=(offset, offset + 999)),
        xy.y_axis(domain=(offset - 300, offset + 500)),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=720,
        height=360,
    ).figure()
    updates, buffers = interaction.decimate_view(fig, offset + 600, offset + 900, 32)
    payload = json.dumps(
        {"traces": updates["traces"], "buffers": [base64.b64encode(b).decode() for b in buffers]}
    )
    document = fig.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.precisionView = " + call)
    probe = (
        """<script>try {
      const v=window.precisionView,payload=PAYLOAD,results=[];
      function sample(phase,x){v._drawNow();v.gl.finish();const q=v._projectDataPoint('x','y',x,OFFSET+VALUE),rgba=new Uint8Array(4);v.gl.bindFramebuffer(v.gl.FRAMEBUFFER,null);v.gl.readPixels(Math.round((q[0]-v.plot.x)*v.dpr),v.canvas.height-1-Math.round((q[1]-v.plot.y)*v.dpr),1,1,v.gl.RGBA,v.gl.UNSIGNED_BYTE,rgba);results.push({phase,rgba:Array.from(rgba),gl:v.gl.getError()});}
      sample('home',OFFSET+200);
      v.view.ranges.x=[OFFSET+600,OFFSET+900];v.view.x0=OFFSET+600;v.view.x1=OFFSET+900;
      v._onKernelMsg({type:'tier_update',seq:v.seq,traces:payload.traces},payload.buffers.map(s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0)).buffer));sample('refined',OFFSET+750);
      v.view.ranges.x=[OFFSET,OFFSET+999];v.view.x0=OFFSET;v.view.x1=OFFSET+999;sample('fallback',OFFSET+200);
      document.body.setAttribute('data-precision',JSON.stringify({results}));
    }catch(e){document.body.setAttribute('data-precision-error',String(e.stack||e));}</script>""".replace(
            "PAYLOAD", payload
        )
        .replace("OFFSET", str(offset))
        .replace("VALUE", "400" if kind == "area" else "450")
    )
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "refine.html",
        "data-precision",
        label="offset refined GPU geometry",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    for sample in result["results"]:
        assert sample["gl"] == 0
        assert sample["rgba"][2] > 200 and sample["rgba"][3] > 200, sample


@pytest.mark.parametrize("datetime_axis", [False, True])
@pytest.mark.parametrize("dpr", [1, 2])
def test_modern_epoch_small_span_with_log_y(tmp_path, datetime_axis, dpr):
    import numpy as np

    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    epoch = 1_700_000_000_000
    raw_x = np.array([epoch + 10, epoch + 50, epoch + 90], dtype=np.int64)
    x = raw_x.astype("datetime64[ms]") if datetime_axis else raw_x
    chart = xy.scatter_chart(
        xy.scatter(x, [1, 10, 100], color="#0000ff", size=8, animation=False),
        xy.x_axis(domain=(epoch, epoch + 100)),
        xy.y_axis(type_="log", domain=(0.1, 1000)),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=720,
        height=360,
    )
    spec, _ = chart.figure().build_payload()
    assert spec["x_axis"]["kind"] == ("time" if datetime_axis else "linear")
    document = chart.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.precisionView = " + call)
    probe = """<script>try {
      const v=window.precisionView,results=[];
      for(const width of [720,380]) {
        v.fluid=true;v.fluidH=true;v.root.style.width=width+'px';v._resize(width,360);v._drawNow();v.gl.finish();
        for(const [x,y] of [[1700000000010,1],[1700000000050,10],[1700000000090,100]]) {
          const q=v._projectDataPoint('x','y',x,y),rgba=new Uint8Array(4);v.gl.bindFramebuffer(v.gl.FRAMEBUFFER,null);v.gl.readPixels(Math.round((q[0]-v.plot.x)*v.dpr),v.canvas.height-1-Math.round((q[1]-v.plot.y)*v.dpr),1,1,v.gl.RGBA,v.gl.UNSIGNED_BYTE,rgba);results.push({width,x,y,rgba:Array.from(rgba),gl:v.gl.getError()});
        }
      }
      document.body.setAttribute('data-precision',JSON.stringify({results}));
    }catch(e){document.body.setAttribute('data-precision-error',String(e.stack||e));}</script>"""
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "epoch.html",
        "data-precision",
        label="epoch x and nonlinear y",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    for sample in result["results"]:
        assert sample["gl"] == 0
        assert sample["rgba"][2] > 200 and sample["rgba"][3] > 200, sample
