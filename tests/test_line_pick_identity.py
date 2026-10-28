"""M4 vertex positions never replace canonical line row identities."""

import base64
import json

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy import interaction
from xy.channel import ChannelCallbacks, handle_message
from xy.export import find_chromium


def _column(spec, blob, reference):
    """Read an integer source map without passing it through f32 geometry."""
    meta = spec["columns"][reference]
    assert meta["dtype"] == "u32"
    return np.frombuffer(blob, dtype="<u4", count=meta["len"], offset=meta["byte_offset"])


@pytest.mark.parametrize("scale", ["linear", "log", "symlog"])
def test_finite_m4_source_rows_match_canonical_coordinates(monkeypatch, scale):
    """Initial and refined maps retain exact rows on every x binning scale."""
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 32)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 32)
    x = np.arange(1.0, 1001.0)
    y = np.sin(x)
    fig = xy.line_chart(xy.line(x, y), xy.x_axis(type_=scale), width=320).figure()
    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    ids = _column(spec, blob, trace["source_rows"])
    assert len(ids) == trace["n_marks"] < len(x)
    assert np.all(np.diff(ids.astype(np.int64)) > 0)
    for index in ids[:: max(1, len(ids) // 10)]:
        row = fig.pick(0, int(index))
        assert row is not None
        assert row["x"] == x[index] and row["y"] == y[index]
    for bounds in ((300, 700), (2000, 3000)):
        update, buffers = interaction.decimate_view(fig, *bounds, 16)
        entry = update["traces"][0]
        if not entry["x"]["len"]:
            assert "source_rows" not in entry
            continue
        source = entry["source_rows"]
        ids = np.frombuffer(buffers[source["buf"]], dtype="<u4", count=source["len"])
        assert len(ids) == entry["x"]["len"] == entry["y"]["len"]
        for index in ids:
            row = fig.pick(0, int(index))
            assert row is not None and row["x"] == x[index]


def test_finite_direct_line_keeps_identity_mapping_implicit():
    """Small ordinary traces avoid shipping a redundant identity array."""
    spec, _blob = xy.line_chart(xy.line([0, 1, 2], [4, 3, 5])).figure().build_payload()
    assert "source_rows" not in spec["traces"][0]


@pytest.mark.parametrize("refined", [False, True])
def test_finite_line_source_row_overflow_is_rejected_before_encoding(refined):
    """A metadata-only large trace cannot wrap canonical IDs into uint32."""
    fig = xy.line_chart(xy.line([0, 1, 2], [4, 3, 5])).figure()
    fig.traces[0].count = 1 << 32
    with pytest.raises(ValueError, match="uint32 source-row limit"):
        if refined:
            interaction.decimate_view(fig, 0, 2, 16)
        else:
            fig.build_payload()


@pytest.mark.parametrize("stage", ["initial", "refined", "home", "exact"])
def test_m4_pointer_and_keyboard_requests_resolve_exact_source_rows(tmp_path, monkeypatch, stage):
    """Real browser requests round-trip through the exact canonical dispatcher."""
    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("xy._payload.DECIMATION_THRESHOLD", 32)
    monkeypatch.setattr("xy.interaction.DECIMATION_THRESHOLD", 32)
    x = np.arange(1000.0)
    y = np.sin(x * 0.1)
    y[[77, 777]] = 9
    if stage == "exact":
        y[77], y[777] = 1e9 + 0.123456, -1e9 - 0.456789
    chart = xy.line_chart(
        xy.line("sample", "reading", data={"sample": x, "reading": y}),
        xy.tooltip(fields=["sample", "reading"], format={"reading": ".9f"}),
        xy.interaction_config(hover=True, click=True),
        xy.x_axis(domain=(0, 999)),
        xy.y_axis(domain=(-2e9, 2e9) if stage == "exact" else (-2, 12)),
        xy.modebar(show=False),
        xy.legend(show=False),
        width=320,
        height=300,
    )
    fig = chart.figure()
    document = fig.to_html()
    updates, buffers = interaction.decimate_view(fig, 600, 900, 16)
    payload = json.dumps(
        {"updates": updates["traces"], "buffers": [base64.b64encode(b).decode() for b in buffers]}
    )
    exact_reply = handle_message(fig, {"type": "pick", "trace": 0, "index": 77, "seq": 1})
    assert exact_reply is not None
    exact_reply = exact_reply[0]
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.identityView = " + call)
    probe = (
        """
    <script>
    try {
      const view=window.identityView; view._drawNow(); view._raf=null;
      const stage=STAGE, payload=PAYLOAD;
      if(stage==='refined'||stage==='home'){
        const buffers=payload.buffers.map(text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0)).buffer);
        view.view.ranges.x=[600,900];view.view.x0=600;view.view.x1=900;
        view._onKernelMsg({type:'tier_update',seq:view.seq,traces:payload.updates},buffers);
      }
      if(stage==='home'){
        view.view.ranges.x=[0,999];view.view.x0=0;view.view.x1=999;
      }
      view._drawNow();
      const requests=[];view.comm={send:message=>requests.push(message)};
      const target=stage==='home'||stage==='exact'?77:777;
      const point=view._projectDataPoint('x','y',target,stage==='exact'?1000000000.123456:9), rect=view.canvas.getBoundingClientRect();
      view.canvas.dispatchEvent(new PointerEvent('pointermove',{
        clientX:rect.left+point[0]-view.plot.x,clientY:rect.top+point[1]-view.plot.y,
        pointerId:1,bubbles:true
      }));
      const pointer={row:view._lastRow,request:requests.filter(r=>r.type==='pick').at(-1)};
      let exactRow=null, exactText=null;
      if(stage==='exact'){
        const reply=EXACT;reply.seq=pointer.request.seq;
        view._onKernelMsg(reply,[]);exactRow=view._lastRow;exactText=view.tooltip.textContent;
      }
      const picksBefore=requests.filter(r=>r.type==='pick').length;
      view.canvas.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));
      const keyboard={row:view._lastRow,request:requests.filter(r=>r.type==='pick').at(-1),
        newPicks:requests.filter(r=>r.type==='pick').length-picksBefore,announcement:view.a11yLive.textContent};
      view.canvas.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
      document.body.setAttribute('data-line-identity',JSON.stringify({
        pointer,keyboard,click:requests.filter(r=>r.type==='click').at(-1),exactRow,exactText,
        usesHome:view._hoverTarget?.g===view.gpuTraces[0]._homeDecimated,glError:view.gl.getError()
      }));
    }catch(error){document.body.setAttribute('data-line-identity-error',String(error.stack||error));}
    </script>
    """.replace("STAGE", json.dumps(stage))
        .replace("PAYLOAD", payload)
        .replace("EXACT", json.dumps(exact_reply))
    )
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "identity.html",
        "data-line-identity",
        label="canonical M4 line picks",
    )
    for action in ("pointer", "keyboard"):
        row, request = result[action]["row"], result[action]["request"]
        assert request is not None
        reply = handle_message(fig, request)
        assert reply is not None
        assert reply[0]["row"]["x"] == pytest.approx(row["x"], abs=1e-4)
        assert reply[0]["row"]["y"] == pytest.approx(row["y"], abs=1 if stage == "exact" else 1e-4)
        assert row["index"] == request["index"] == int(round(row["x"]))
        assert row["sample"] == pytest.approx(row["x"], abs=1e-4)
        assert row["reading"] == pytest.approx(row["y"], abs=1e-4)
    clicked = []
    handle_message(fig, result["click"], callbacks=ChannelCallbacks(on_click=clicked.append))
    assert clicked[0]["index"] == result["keyboard"]["row"]["index"]
    assert clicked[0]["x"] == pytest.approx(result["keyboard"]["row"]["x"], abs=1e-4)
    assert result["keyboard"]["newPicks"] == 1
    assert result["keyboard"]["row"]["index"] > result["pointer"]["row"]["index"]
    assert result["keyboard"]["announcement"].startswith("Point ")
    assert result["usesHome"] is (stage == "home")
    assert result["glError"] == 0
    if stage == "exact":
        assert result["exactRow"]["y"] == y[77]
        assert result["exactRow"]["reading"] == y[77]
        assert format(y[77], ".9f") in result["exactText"]


@pytest.mark.parametrize("field", ["x_kind", "y_kind", "index", "trace", "x", "y"])
def test_bound_line_fields_do_not_replace_core_row_metadata(tmp_path, field):
    """Reserved column names remain available to authored fields without corrupting row keys."""
    browser = find_chromium()
    if browser is None:
        pytest.skip("Chromium unavailable")
    fig = xy.line_chart(
        xy.line("category", field, data={"category": ["A", "B", "C"], field: [1, 2, 3]}),
        xy.tooltip(fields=["category", field], title="{category}: {" + field + "}"),
        xy.modebar(show=False),
        width=320,
        height=300,
    ).figure()
    document = fig.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.identityView = " + call)
    reply = handle_message(fig, {"type": "pick", "trace": 0, "index": 1, "seq": 1})
    assert reply is not None
    probe = """
    <script>
    try {
      const view=window.identityView;view._drawNow();view._raf=null;
      const row=view._localRow({g:view.gpuTraces[0],trace:0,index:1}),field=FIELD;
      const local={row,value:view._tooltipLookup(row,field),lines:view._tooltipLines(view._tooltipItems(row))};
      view._lastRow=row;view._pickSeq=1;view._onKernelMsg(REPLY,[]);
      const exact=view._lastRow;
      document.body.setAttribute('data-line-fields',JSON.stringify({local,
        exact:{row:exact,value:view._tooltipLookup(exact,field),lines:view._tooltipLines(view._tooltipItems(exact))}}));
    }catch(error){document.body.setAttribute('data-line-fields-error',String(error.stack||error));}
    </script>
    """.replace("FIELD", json.dumps(field)).replace("REPLY", json.dumps(reply[0]))
    result = run_browser_probe(
        browser,
        document.replace("</body>", probe + "</body>"),
        tmp_path / "fields.html",
        "data-line-fields",
        label="reserved line field names",
    )
    for phase in ("local", "exact"):
        row = result[phase]["row"]
        assert row["trace"] == 0 and row["index"] == 1 and row["x"] == "B" and row["y"] == 2
        assert "x_kind" not in row and row["y_kind"] == "float"
        assert result[phase]["value"][0] == 2
        assert "B: 2" in result[phase]["lines"]
        assert f"{field}: 2" in result[phase]["lines"]
