"""Filled traces bind authored fields to the correct exact geometry channels."""

import base64
import json

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy import interaction
from xy.channel import ChannelCallbacks, handle_message
from xy.export import find_chromium


def _mark(kind, names, table):
    """Build either public filled-family mark using the same named channels."""
    x, top, bottom = names
    if kind == "area":
        return xy.area(x, top, base=bottom, data=table, animation=False)
    return xy.error_band(x, bottom, top, data=table, animation=False)


@pytest.mark.parametrize("kind", ["area", "error_band"])
def test_filled_named_geometry_sources_and_aliases(kind):
    """The source catalog and compatibility aliases share one family-aware mapping."""
    fig = xy.area_chart(
        _mark(
            kind,
            ("sample", "reading", "floor"),
            {"sample": [0, 1, 2], "reading": [4, 5, 6], "floor": [1, 2, 3]},
        ),
        xy.tooltip(fields=["sample", "reading", "floor"]),
    ).figure()
    spec, _ = fig.build_payload()
    assert spec["tooltip"]["aliases"] == {"sample": "x", "reading": "y", "floor": "base"}
    assert spec["tooltip"]["sources"] == {
        "sample": [{"trace": 0, "channel": "x"}],
        "reading": [{"trace": 0, "channel": "y"}],
        "floor": [{"trace": 0, "channel": "base"}],
    }


@pytest.mark.parametrize("kind", ["area", "error_band"])
def test_filled_exact_pick_contains_baseline(kind):
    """Exact lower geometry is additive only for filled-family canonical rows."""
    fig = xy.area_chart(
        _mark(
            kind,
            ("sample", "reading", "floor"),
            {"sample": [0, 1, 2], "reading": [4, 5, 6], "floor": [1, 2, 3]},
        )
    ).figure()
    reply = handle_message(fig, {"type": "pick", "trace": 0, "index": 1, "seq": 1})
    assert reply is not None
    assert reply[0]["row"]["y"] == 5
    assert reply[0]["row"]["base"] == 2
    assert reply[0]["row"]["base_kind"] == "float"
    line = xy.line_chart(xy.line([0, 1, 2], [4, 5, 6])).figure()
    line_row = line.pick(0, 1)
    assert line_row is not None and "base" not in line_row


@pytest.mark.parametrize("kind", ["area", "error_band"])
@pytest.mark.parametrize("stage", ["initial", "refined", "home"])
@pytest.mark.parametrize("dpr", [1, 2])
@pytest.mark.parametrize("columns", ["named", "reserved", "baseline"])
def test_filled_bound_fields_upgrade_to_exact_top_and_base(tmp_path, kind, stage, dpr, columns):
    """Actual pointer requests and exact replies agree across LOD and metadata collisions."""
    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    names = {
        "named": ("sample", "reading", "floor"),
        "reserved": ("trace", "index", "base_kind"),
        "baseline": ("base", "y_kind", "x_kind"),
    }[columns]
    x = np.arange(30_000.0)
    top, bottom = np.sin(x * 0.01) * 1e8, np.cos(x * 0.02) * 1e8 - 2e8
    top[[777, 20_777]] = 1e9 + 0.123456
    bottom[[777, 20_777]] = -1e9 + 0.456789
    top[14_000:16_000] = np.nan
    bottom[10_000:11_000] = np.nan
    table = dict(zip(names, (x, top, bottom), strict=True))
    fig = xy.area_chart(
        _mark(kind, names, table),
        xy.tooltip(
            fields=list(names),
            title="{" + names[0] + "}: {" + names[1] + "} / {" + names[2] + "}",
            format={name: ".9f" for name in names},
        ),
        xy.interaction_config(hover=True, click=True),
        xy.x_axis(domain=(0, 29_999)),
        xy.y_axis(domain=(-2e9, 2e9)),
        xy.modebar(show=False),
        xy.legend(show=False),
        width=720,
        height=360,
    ).figure()
    document = fig.to_html()
    update, buffers = interaction.decimate_view(fig, 20_000, 22_000, 80)
    target = 20_777 if stage == "refined" else 777
    reply = handle_message(fig, {"type": "pick", "trace": 0, "index": target, "seq": 1})
    assert reply is not None
    payload = {
        "updates": update["traces"],
        "buffers": [base64.b64encode(b).decode() for b in buffers],
    }
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.fillReadoutView = " + call)
    probe = (
        """
    <script>
    try {
      const view=window.fillReadoutView;view._drawNow();view._raf=null;
      const stage=STAGE,payload=PAYLOAD,names=NAMES,target=TARGET;
      if(stage!=='initial'){
        const buffers=payload.buffers.map(text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0)).buffer);
        view.view.ranges.x=[20000,22000];view.view.x0=20000;view.view.x1=22000;
        view._onKernelMsg({type:'tier_update',seq:view.seq,traces:payload.updates},buffers);
      }
      if(stage==='home'){view.view.ranges.x=[0,29999];view.view.x0=0;view.view.x1=29999;}
      view._drawNow();
      const requests=[];view.comm={send:message=>requests.push(message)};
      const point=view._projectDataPoint('x','y',target,1000000000.123456),rect=view.canvas.getBoundingClientRect();
      const event={clientX:rect.left+point[0]-view.plot.x,clientY:rect.top+point[1]-view.plot.y,bubbles:true};
      view.canvas.dispatchEvent(new PointerEvent('pointermove',{...event,pointerId:1}));
      const request=requests.filter(r=>r.type==='pick').at(-1),local=structuredClone(view._lastRow);
      if(!request)throw new Error('no real pointer pick');
      const reply=REPLY;reply.seq=request.seq;view._onKernelMsg(reply,[]);
      const row=view._lastRow,fields=Object.fromEntries(names.map(name=>[name,view._tooltipLookup(row,name)[0]]));
      view.canvas.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
      document.body.setAttribute('data-filled-readout',JSON.stringify({request,local,row,fields,
        text:view.tooltip.textContent,click:requests.filter(r=>r.type==='click').at(-1),
        usesHome:view._hoverTarget?.g===view.gpuTraces[0]._homeDecimated,glError:view.gl.getError()}));
    }catch(error){document.body.setAttribute('data-filled-readout-error',String(error.stack||error));}
    </script>
    """.replace("STAGE", json.dumps(stage))
        .replace("PAYLOAD", json.dumps(payload))
        .replace("NAMES", json.dumps(names))
        .replace("TARGET", str(target))
        .replace("REPLY", json.dumps(reply[0]))
    )
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "filled-readout.html",
        "data-filled-readout",
        label="filled exact geometry fields",
        extra_args=(f"--force-device-scale-factor={dpr}",),
    )
    (tmp_path / "readout.json").write_text(json.dumps(result, indent=2))
    assert result["request"]["index"] == target
    actual_reply = handle_message(fig, result["request"])
    assert actual_reply is not None and actual_reply[0]["row"] == reply[0]["row"]
    row = result["row"]
    assert row["trace"] == 0 and row["index"] == target and row["x"] == x[target]
    assert row["y"] == top[target]
    assert result["fields"][names[1]] == top[target]
    assert row["base"] == bottom[target]
    assert row["x_kind"] == row["y_kind"] == row["base_kind"] == "float"
    for name, value in zip(names, (x[target], top[target], bottom[target]), strict=True):
        assert result["fields"][name] == value
        assert format(value, ".9f") in result["text"]
    clicked = []
    handle_message(fig, result["click"], callbacks=ChannelCallbacks(on_click=clicked.append))
    assert clicked[0]["index"] == target and clicked[0]["base"] == bottom[target]
    assert result["usesHome"] is (stage == "home") and result["glError"] == 0
