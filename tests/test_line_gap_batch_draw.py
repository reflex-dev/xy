"""Packed line edges retain the finite-run renderer's actual pixels."""

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium


@pytest.mark.parametrize("mode", ["linear", "smooth", "step", "polar", "log"])
@pytest.mark.parametrize(
    "cap,dash,reveal",
    [
        ("round", None, 1),
        ("butt", "dashed", 1),
        ("square", "dashdot", 1),
        ("square", "dashdot", 0.43),
    ],
)
@pytest.mark.parametrize("dpr", [1, 2])
def test_packed_line_runs_match_fallback_pixels(tmp_path, mode, cap, dash, reveal, dpr):
    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    mark = xy.step if mode == "step" else xy.line
    options = {"curve": "smooth"} if mode == "smooth" else {}
    chart = (xy.polar_chart if mode == "polar" else xy.line_chart)(
        mark(
            np.arange(9.0),
            [1, 2, np.nan, 1, np.nan, 1, 2, 1, 2],
            width=3,
            dash=dash,
            style={"stroke-linecap": cap},
            **options,
        ),
        xy.y_axis(type_="log") if mode == "log" else xy.y_axis(),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=600,
        height=300,
    )
    document = chart.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.packedView = " + call)
    probe = """
    <script>
    try {
      const v=window.packedView;v._drawNow();v._raf=null;
      const g=v.gpuTraces[0];g._transitionReveal=REVEAL;
      const read=()=>{v._drawNow();v.gl.finish();const c=document.createElement('canvas');c.width=v.canvas.width;c.height=v.canvas.height;const ctx=c.getContext('2d');ctx.drawImage(v.canvas,0,0);return ctx.getImageData(0,0,c.width,c.height).data;};
      v._batchLineRuns=false;const before=read();
      let calls=0;const original=v.gl.drawArraysInstanced;
      v.gl.drawArraysInstanced=function(...args){calls++;return original.apply(this,args)};
      v._batchLineRuns=true;const after=read();v.gl.drawArraysInstanced=original;
      let different=0,maxDelta=0;
      for(let i=0;i<before.length;i++){const d=Math.abs(before[i]-after[i]);if(d){different++;maxDelta=Math.max(d,maxDelta);}}
      document.body.setAttribute('data-packed-runs',JSON.stringify({calls,different,maxDelta,edgeCount:g._lineEdgeStarts?.length??null,source:Array.from(g._sourceRows),glError:v.gl.getError()}));
    }catch(error){document.body.setAttribute('data-packed-runs-error',String(error.stack||error));}
    </script>
    """.replace("REVEAL", str(reveal))
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "packed.html",
        "data-packed-runs",
        label="packed finite line runs",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    assert result["calls"] == (1 if reveal == 1 else 2)
    assert result["edgeCount"] is not None
    assert result["source"] == [0, 1, 3, 5, 6, 7, 8]
    assert result["glError"] == 0
    assert result["maxDelta"] <= 1 and result["different"] <= 8


def test_packed_buffers_are_deleted_after_repeated_refinement_and_home_draw(tmp_path, monkeypatch):
    import base64
    import json

    from xy import interaction

    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 5)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 5)
    x = np.arange(100.0)
    y = np.sin(x * 0.01)
    y[5::10] = np.nan
    fig = xy.line_chart(
        xy.line(x, y, dash="dashed"),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=600,
        height=300,
    ).figure()
    document = fig.to_html()
    updates = []
    for lo, hi in ((10, 45), (60, 85)):
        message, buffers = interaction.decimate_view(fig, lo, hi, 16)
        updates.append(
            {
                "lo": lo,
                "hi": hi,
                "traces": message["traces"],
                "buffers": [base64.b64encode(b).decode() for b in buffers],
            }
        )
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.packedView = " + call)
    probe = """
    <script>
    try {
      const v=window.packedView;v._drawNow();v._raf=null;const g=v.gpuTraces[0],gl=v.gl;
      const names=['xBuf','yBuf','_lenBuf','_lineX0Buf','_lineX1Buf','_lineY0Buf','_lineY1Buf','_lineCapsBuf','_lineLen0Buf','_lineLen1Buf'];
      const seen=new Set();const collect=()=>{for(const draw of [g,g._homeDecimated])for(const name of names)if(draw?.[name])seen.add(draw[name]);};
      collect();
      for(const update of UPDATES){
        const buffers=update.buffers.map(text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0)).buffer);
        v.view.ranges.x=[update.lo,update.hi];v.view.x0=update.lo;v.view.x1=update.hi;
        v._onKernelMsg({type:'tier_update',seq:v.seq,traces:update.traces},buffers);v._drawNow();collect();
      }
      v.view.ranges.x=[0,99];v.view.x0=0;v.view.x1=99;v._drawNow();collect();
      const homeDraw=v._decimatedDrawable(g)===g._homeDecimated;
      if(v._raf)cancelAnimationFrame(v._raf);v._raf=null;
      v._destroyTraceResources(g,new Set());
      document.body.setAttribute('data-packed-lifetime',JSON.stringify({homeDraw,observed:seen.size,remaining:[...seen].filter(buffer=>gl.isBuffer(buffer)).length,contextLost:gl.isContextLost(),glError:gl.getError()}));
    }catch(error){document.body.setAttribute('data-packed-lifetime-error',String(error.stack||error));}
    </script>
    """.replace("UPDATES", json.dumps(updates))
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "lifetime.html",
        "data-packed-lifetime",
        label="packed line buffer lifetime",
    )
    assert result["homeDraw"]
    assert result["observed"] >= 25
    assert result["remaining"] == result["glError"] == 0
    assert not result["contextLost"]
