"""Default numeric tick text must distinguish a large offset's small steps."""

from pathlib import Path

import pytest

import xy
from conftest import probe_document, run_browser_probe
from xy import _svg
from xy.export import find_chromium


@pytest.mark.parametrize("value,step", [(1e12, 200), (-1e12, 200), (1e9, 0.25), (1e-8, 1e-12)])
def test_default_numeric_step_remains_distinct(value, step):
    labels = [_svg._fmt_axis({}, value + i * step, step) for i in range(3)]
    assert len(set(labels)) == 3, labels
    for i, text in enumerate(labels):
        assert abs(float(text) - (value + i * step)) < step / 100


@pytest.mark.parametrize("y_title", [False, True])
@pytest.mark.parametrize("width", [380, 768])
@pytest.mark.parametrize("dpr", [1, 2])
def test_numeric_axis_live_export_parity(
    width: int, dpr: int, y_title: bool, tmp_path: Path, monkeypatch
):
    browser = find_chromium()
    if not browser:
        pytest.skip("Chromium unavailable")
    offset = 1e12
    chart = xy.line_chart(
        xy.line([offset, offset + 500, offset + 1000], [offset, offset + 250, offset + 500]),
        xy.x_axis(domain=(offset, offset + 1000)),
        xy.y_axis(domain=(offset, offset + 500), label="Reading" if y_title else None),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=width,
        height=360,
    )
    probe = r"""<script>try {
      const v=window.__fcProbeView;v._drawNow();
      const axes={};
      for(const id of ['x','y']) {
        const t=v._axisTicks(id),a=v._axis(id);
        axes[id]={values:t.ticks,step:t.step,labels:t.ticks.map(x=>v._axisTickText(a,x,t.step))};
      }
      const formatCases = [[1e12,200],[-1e12,200],[1e9,.25],[1e-8,1e-12]].map(([value,step])=>({
        value,step,labels:[0,1,2].map(i=>v._axisTickText({},value+i*step,step))}));
      const root=v.root.getBoundingClientRect();
      const boxes=Array.from(v.root.querySelectorAll('[data-xy-label-kind]')).map(e=>{
        const b=e.getBoundingClientRect();return {text:e.textContent,axis:e.dataset.xyAxis,kind:e.dataset.xyLabelKind,
          x:b.x-root.x,y:b.y-root.y,w:b.width,h:b.height};
      });
      document.body.setAttribute('data-numeric-axis',JSON.stringify({axes,boxes,formatCases,plot:v.plot,
        raw:v.gpuTraces.map(g=>({x:Array.from(g._cpu.x,(_,i)=>v._sourceValue(g,{channel:"x"},i)[0]),y:Array.from(g._cpu.y,(_,i)=>v._sourceValue(g,{channel:"y"},i)[0])}))}));
    }catch(e){document.body.setAttribute('data-numeric-axis-error',String(e.stack||e));}</script>"""
    result = run_browser_probe(
        browser,
        probe_document(chart, probe),
        tmp_path / "numeric.html",
        "data-numeric-axis",
        label="numeric axis precision",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    svg = chart.to_svg()
    from xy import _raster

    raster_text = []
    original_text = _raster._Cmd.text

    def capture_text(self, x, y, anchor, size, color, text, **kwargs):
        raster_text.append(str(text))
        return original_text(self, x, y, anchor, size, color, text, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", capture_text)
    assert chart.figure().to_png().startswith(b"\x89PNG")
    for sample in result["formatCases"]:
        assert sample["labels"] == [
            _svg._fmt_axis({}, sample["value"] + i * sample["step"], sample["step"])
            for i in range(3)
        ]
    for axis in result["axes"].values():
        assert len(set(axis["labels"])) == len(axis["values"]), axis
        assert axis["labels"] == [
            _svg._fmt_axis({}, value, axis["step"]) for value in axis["values"]
        ]
    for box in result["boxes"]:
        assert box["text"] in svg
        assert box["text"] in raster_text
        assert box["x"] >= -1 and box["x"] + box["w"] <= width + 1, box
        # The inherited 12px font has a 14.4px line box: up to 1.2px of
        # empty leading can extend past the compact top band, without ink loss.
        assert box["y"] >= -2 and box["y"] + box["h"] <= 362, box
    for label in (box for box in result["boxes"] if box["kind"] == "label"):
        for tick in (box for box in result["boxes"] if box["kind"] == "tick"):
            assert (
                label["x"] + label["w"] <= tick["x"]
                or tick["x"] + tick["w"] <= label["x"]
                or label["y"] + label["h"] <= tick["y"]
                or tick["y"] + tick["h"] <= label["y"]
            ), (label, tick)
    assert result["raw"][0]["x"] == [offset, offset + 500, offset + 1000]
    assert result["raw"][0]["y"] == [offset, offset + 250, offset + 500]


@pytest.mark.parametrize(
    "value,step", [(0, 0.25), (0.25, 0.25), (1000, 200), (1e6, 2e5), (1e-8, 1e-8)]
)
def test_ordinary_numeric_style_unchanged(value, step):
    assert _svg._fmt_axis({}, value, step) == _svg._fmt_linear(value, step)


def test_authored_and_other_axis_formats_are_preserved():
    assert _svg._fmt_axis({"format": ".0f"}, 1e12, 200) == "1000000000000"
    assert (
        _svg._tick_text({"tick_values": [1e12], "tick_labels": ["Authored"]}, 1e12, 200)
        == "Authored"
    )
    assert _svg._fmt_axis({"kind": "category", "categories": ["One"]}, 0, 200) == "One"
    assert _svg._fmt_axis({"kind": "time", "format": "%Y"}, 1e12, 200) == "2001"
    assert _svg._fmt_axis({"scale": "log"}, 1e12, 1) == _svg._fmt_linear(1e12, 1)
