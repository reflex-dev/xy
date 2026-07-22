"""Headless browser smoke for declarative/keyed data transitions."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from _protocol import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "xy" / "static"
CHROME = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "chromium",
    "google-chrome",
]


def _chrome(explicit: str | None = None) -> str:
    if explicit:
        resolved = explicit if Path(explicit).is_file() else shutil.which(explicit)
        if resolved:
            return str(resolved)
        raise RuntimeError(f"configured chromium not found: {explicit}")
    for candidate in CHROME:
        resolved = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if resolved:
            return str(resolved)
    raise RuntimeError("no chromium found")


def _payload(rows: list[tuple[float, float, int]]) -> tuple[dict, bytes]:
    blob = bytearray()
    columns: list[dict] = []

    def ship(values: list[float], dtype: str | None = None) -> int:
        offset = len(blob)
        if dtype == "u32":
            blob.extend(struct.pack(f"<{len(values)}I", *[int(v) for v in values]))
        else:
            blob.extend(struct.pack(f"<{len(values)}f", *values))
        meta = {"byte_offset": offset, "len": len(values), "offset": 0, "scale": 1}
        if dtype:
            meta["dtype"] = dtype
        columns.append(meta)
        return len(columns) - 1

    x = ship([row[0] for row in rows])
    y = ship([row[1] for row in rows])
    lo = ship([row[2] for row in rows], "u32")
    hi = ship([0 for _ in rows], "u32")
    spec = {
        "protocol": PROTOCOL_VERSION,
        "width": 360,
        "height": 240,
        "title": "animation smoke",
        "show_modebar": False,
        "x_axis": {"kind": "linear", "label": "x", "range": [0, 30]},
        "y_axis": {"kind": "linear", "label": "y", "range": [0, 30]},
        "axes": {
            "x": {"id": "x", "kind": "linear", "label": "x", "range": [0, 30]},
            "y": {"id": "y", "kind": "linear", "label": "y", "range": [0, 30]},
        },
        "animation": {
            "enabled": True,
            "delay": 0,
            "duration": 180,
            "easing": "linear",
            "match": "key",
            "enter": "scale",
            "update": "interpolate",
            "interpolate": ["position", "size", "domain"],
        },
        "traces": [
            {
                "id": 0,
                "kind": "scatter",
                "name": "points",
                "tier": "direct",
                "n_points": len(rows),
                "n_marks": len(rows),
                "x": x,
                "y": y,
                "keys": {"lo": lo, "hi": hi},
                "style": {"opacity": 0.9},
                "color": {"mode": "constant", "color": "#2563eb"},
                "size": {"mode": "constant", "size": 10},
                "x_axis": "x",
                "y_axis": "y",
            }
        ],
        "columns": columns,
        "backend": "none",
    }
    return spec, bytes(blob)


def _errorbar_payload() -> tuple[dict, bytes]:
    blob = bytearray()
    columns: list[dict] = []

    def ship(values: list[float]) -> int:
        offset = len(blob)
        blob.extend(struct.pack(f"<{len(values)}f", *values))
        columns.append({"byte_offset": offset, "len": len(values), "offset": 0, "scale": 1})
        return len(columns) - 1

    spec = {
        "protocol": PROTOCOL_VERSION,
        "width": 360,
        "height": 240,
        "title": "errorbar animation smoke",
        "show_modebar": False,
        "x_axis": {"kind": "linear", "label": "x", "range": [0, 20]},
        "y_axis": {"kind": "linear", "label": "y", "range": [0, 20]},
        "axes": {
            "x": {"id": "x", "kind": "linear", "label": "x", "range": [0, 20]},
            "y": {"id": "y", "kind": "linear", "label": "y", "range": [0, 20]},
        },
        "animation": {
            "enabled": True,
            "delay": 0,
            "duration": 180,
            "easing": "linear",
            "match": "index",
            "enter": "auto",
            "update": "interpolate",
            "interpolate": ["position", "size", "domain"],
        },
        "traces": [
            {
                "id": 0,
                "kind": "errorbar",
                "name": "errors",
                "tier": "direct",
                "n_points": 2,
                "n_marks": 2,
                "x0": ship([4, 14]),
                "x1": ship([4, 14]),
                "y0": ship([2, 7]),
                "y1": ship([8, 15]),
                "style": {"color": "#dc2626", "width": 2, "opacity": 1},
                "x_axis": "x",
                "y_axis": "y",
            }
        ],
        "columns": columns,
        "backend": "none",
    }
    return spec, bytes(blob)


def _bar_payload(rows: list[tuple[float, float, int]]) -> tuple[dict, bytes]:
    blob = bytearray()
    columns: list[dict] = []

    def ship(values: list[float], dtype: str | None = None) -> int:
        offset = len(blob)
        if dtype == "u32":
            blob.extend(struct.pack(f"<{len(values)}I", *[int(v) for v in values]))
        else:
            blob.extend(struct.pack(f"<{len(values)}f", *values))
        meta = {"byte_offset": offset, "len": len(values), "offset": 0, "scale": 1}
        if dtype:
            meta["dtype"] = dtype
        columns.append(meta)
        return len(columns) - 1

    pos = ship([row[0] for row in rows])
    value = ship([row[1] for row in rows])
    lo = ship([row[2] for row in rows], "u32")
    hi = ship([0 for _ in rows], "u32")
    spec = {
        "protocol": PROTOCOL_VERSION,
        "width": 360,
        "height": 240,
        "title": "bar animation smoke",
        "show_modebar": False,
        "x_axis": {"kind": "linear", "label": "x", "range": [0, 12]},
        "y_axis": {"kind": "linear", "label": "y", "range": [0, 12]},
        "axes": {
            "x": {"id": "x", "kind": "linear", "label": "x", "range": [0, 12]},
            "y": {"id": "y", "kind": "linear", "label": "y", "range": [0, 12]},
        },
        "animation": {
            "enabled": True,
            "delay": 0,
            "duration": 180,
            "easing": "linear",
            "match": "key",
            "enter": "grow",
            "update": "interpolate",
            "interpolate": ["position", "size", "domain"],
        },
        "traces": [
            {
                "id": 0,
                "kind": "column",
                "name": "columns",
                "tier": "direct",
                "n_points": len(rows),
                "n_marks": len(rows),
                "bar": {
                    "pos": pos,
                    "value1": value,
                    "value0_const": 0,
                    "width": 0.8,
                    "orientation": "vertical",
                },
                "keys": {"lo": lo, "hi": hi},
                "style": {"color": "#8e51ff", "opacity": 1},
                "x_axis": "x",
                "y_axis": "y",
            }
        ],
        "columns": columns,
        "backend": "none",
    }
    return spec, bytes(blob)


EXPECTED_ASSERTIONS = (
    "XY_ANIM_OK",
    "match=[[1,0],[0,1]]",
    "scratch=1",
    "ghost=1",
    "pixel=1",
    "partial=1",
    "missing=1",
    "active=1",
    "pick=1",
    "bounded=1",
    "replacement=1",
    "done=1",
    "lifecycle=1",
    "reduced=1",
    "frozen=1",
    "destroy=1",
    "errorbar=1",
    "bar=1",
    "hbar=1",
)


def _write_evidence(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _evidence(
    *,
    title: str,
    chromium: str | None,
    returncode: int | None,
    stderr: str = "",
    timed_out: bool = False,
) -> dict:
    reported = frozenset(title.split())
    missing = [assertion for assertion in EXPECTED_ASSERTIONS if assertion not in reported]
    passed = returncode == 0 and not missing
    return {
        "status": "ok" if passed else "failed",
        "title": title,
        "chromium": chromium,
        "chromium_returncode": returncode,
        "timed_out": timed_out,
        "missing_assertions": missing,
        "stderr_tail": stderr[-4000:],
        "protocol": PROTOCOL_VERSION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chromium", nargs="?", default=None)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="write compact JSON diagnostics for CI artifact retention",
    )
    args = parser.parse_args(argv)
    bundle = (STATIC / "standalone.js").read_text(encoding="utf-8")
    payloads = [
        _payload([(2, 3, 1), (12, 8, 2)]),
        _payload([(22, 18, 2), (7, 14, 1)]),
        _payload([(24, 20, 2), (9, 16, 1), (28, 5, 3)]),
        _payload([(24, 20, 2), (9, 16, 1), (29, 8, 3)]),
    ]
    encoded = [{"spec": spec, "blob": base64.b64encode(blob).decode()} for spec, blob in payloads]
    errorbar_spec, errorbar_blob = _errorbar_payload()
    encoded_errorbar = {
        "spec": errorbar_spec,
        "blob": base64.b64encode(errorbar_blob).decode(),
    }
    bar_payloads = [
        _bar_payload([(2, 4, 1), (5, 8, 2)]),
        _bar_payload([(8, 10, 2), (4, 6, 1)]),
    ]
    encoded_bars = [
        {"spec": spec, "blob": base64.b64encode(blob).decode()} for spec, blob in bar_payloads
    ]
    page = f"""<!doctype html><html><head><title>pending</title></head><body>
<div id="chart"></div><script>{bundle}</script><script>
const payloads={json.dumps(encoded)};
const errorbarPayload={json.dumps(encoded_errorbar)};
const barPayloads={json.dumps(encoded_bars)};
const unpack=(item)=>Uint8Array.from(atob(item.blob),c=>c.charCodeAt(0));
const host=document.getElementById("chart");
let starts=0,ends=0;
host.addEventListener("xy:animation_start",()=>starts++);
host.addEventListener("xy:animation_end",()=>ends++);
try{{
  let fakeNow=0;
  xy.ChartView.prototype._now=function(){{fakeNow+=500;return fakeNow;}};
  const autoHost=document.createElement("div");document.body.appendChild(autoHost);
  const autoSpec=JSON.parse(JSON.stringify(payloads[0].spec));
  autoSpec.animation.enabled="auto";
  const autoView=xy.renderStandalone(autoHost,autoSpec,unpack(payloads[0]));
  const reduced=!autoView._dataAnim;
  autoView.destroy();autoHost.remove();
  const destroyHost=document.createElement("div");document.body.appendChild(destroyHost);
  let destroyStarts=0,destroyEnds=0,destroyCancelled=false;
  destroyHost.addEventListener("xy:animation_start",()=>destroyStarts++);
  destroyHost.addEventListener("xy:animation_end",(event)=>{{
    destroyEnds++;destroyCancelled=event.detail.cancelled===true;
  }});
  const destroyView=xy.renderStandalone(destroyHost,payloads[0].spec,unpack(payloads[0]));
  destroyView.destroy();destroyHost.remove();
  const destroyBalanced=destroyStarts===1&&destroyEnds===1&&destroyCancelled;
  const errorbarHost=document.createElement("div");document.body.appendChild(errorbarHost);
  const errorbarView=xy.renderStandalone(errorbarHost,errorbarPayload.spec,unpack(errorbarPayload));
  const errorbarTrace=errorbarView.gpuTraces[0];
  errorbarView._setTransitionVisual(errorbarTrace,"enter",0.5,errorbarView._resolvedAnimation(errorbarTrace.trace));
  errorbarView._drawNow();
  const errorbarGrow=errorbarTrace._transitionScale===0.5
    &&errorbarView.gl.getError()===errorbarView.gl.NO_ERROR;
  errorbarView.destroy();errorbarHost.remove();
  const barHost=document.createElement("div");document.body.appendChild(barHost);
  const barView=xy.renderStandalone(barHost,barPayloads[0].spec,unpack(barPayloads[0]));
  barView.updatePayload(barPayloads[1].spec,unpack(barPayloads[1]));
  if(barView._dataAnimRaf)cancelAnimationFrame(barView._dataAnimRaf);
  barView._dataAnimRaf=null;
  const barTrace=barView.gpuTraces[0];
  barView._setTransitionVisual(barTrace,"update",0.5,barView._resolvedAnimation(barTrace.trace));
  barView._drawNow();
  const barAlphaNear=(x,y)=>{{
    const px=Math.round(x/12*barView.canvas.width);
    const py=Math.round(y/12*barView.canvas.height);
    const rgba=new Uint8Array(7*7*4);
    barView.gl.readPixels(Math.max(0,px-3),Math.max(0,py-3),7,7,barView.gl.RGBA,barView.gl.UNSIGNED_BYTE,rgba);
    let alpha=0;for(let i=3;i<rgba.length;i+=4)alpha=Math.max(alpha,rgba[i]);
    return alpha;
  }};
  const barInterpolates=barTrace._transitionPositionInterpolated===true
    &&JSON.stringify(Array.from(barTrace._transitionPrevPosValues))==="[5,2]"
    &&JSON.stringify(Array.from(barTrace._transitionPrevValue1Values))==="[8,4]"
    &&barTrace._transitionPositionProgress===0.5
    &&barAlphaNear(6.5,8.5)>64
    &&barAlphaNear(5,7)<16
    &&barAlphaNear(8,9)<16
    &&barView._transitionOldTraces[0]._transitionOpacity===0
    &&barView.gl.getError()===barView.gl.NO_ERROR;
  barView.destroy();barHost.remove();
  const hbarHost=document.createElement("div");document.body.appendChild(hbarHost);
  const hbarOld=JSON.parse(JSON.stringify(barPayloads[0].spec));
  const hbarNext=JSON.parse(JSON.stringify(barPayloads[1].spec));
  hbarOld.traces[0].kind="bar";hbarOld.traces[0].bar.orientation="horizontal";
  hbarNext.traces[0].kind="bar";hbarNext.traces[0].bar.orientation="horizontal";
  const hbarView=xy.renderStandalone(hbarHost,hbarOld,unpack(barPayloads[0]));
  hbarView.updatePayload(hbarNext,unpack(barPayloads[1]));
  if(hbarView._dataAnimRaf)cancelAnimationFrame(hbarView._dataAnimRaf);
  hbarView._dataAnimRaf=null;
  const hbarTrace=hbarView.gpuTraces[0];
  hbarView._setTransitionVisual(hbarTrace,"update",0.5,hbarView._resolvedAnimation(hbarTrace.trace));
  hbarView._drawNow();
  const horizontalBarInterpolates=hbarTrace._transitionPositionInterpolated===true
    &&hbarTrace._transitionPositionProgress===0.5
    &&hbarView.gl.getError()===hbarView.gl.NO_ERROR;
  hbarView.destroy();hbarHost.remove();
  const frozenRun=()=>{{
    const frozenHost=document.createElement("div");document.body.appendChild(frozenHost);
    let frozenStarts=0,frozenEnds=0;
    frozenHost.addEventListener("xy:animation_start",()=>frozenStarts++);
    frozenHost.addEventListener("xy:animation_end",()=>frozenEnds++);
    const frozenSpec=JSON.parse(JSON.stringify(payloads[0].spec));
    frozenSpec.animation_capture_progress=0.5;
    const frozenView=xy.renderStandalone(frozenHost,frozenSpec,unpack(payloads[0]));
    frozenView._drawNow();
    const frozenTrace=frozenView.gpuTraces[0];
    const pixels=new Uint8Array(frozenView.canvas.width*frozenView.canvas.height*4);
    frozenView.gl.readPixels(0,0,frozenView.canvas.width,frozenView.canvas.height,
      frozenView.gl.RGBA,frozenView.gl.UNSIGNED_BYTE,pixels);
    let hash=2166136261,lit=0;
    for(let i=0;i<pixels.length;i++){{
      hash=Math.imul(hash^pixels[i],16777619)>>>0;
      if((i&3)===3&&pixels[i]>0)lit++;
    }}
    const fixedProgress=Math.abs(frozenTrace._transitionScale-0.5)<0.01
      &&!frozenView._dataAnim&&frozenView._dataAnimRaf==null
      &&frozenView.gl.getError()===frozenView.gl.NO_ERROR&&lit>0;
    frozenView.destroy();frozenHost.remove();
    return {{ok:fixedProgress&&frozenStarts===0&&frozenEnds===0,hash}};
  }};
  const frozenA=frozenRun(),frozenB=frozenRun();
  const frozen=frozenA.ok&&frozenB.ok&&frozenA.hash===frozenB.hash;
  const missingHost=document.createElement("div");document.body.appendChild(missingHost);
  const missingView=xy.renderStandalone(missingHost,payloads[0].spec,unpack(payloads[0]));
  const missingSpec=JSON.parse(JSON.stringify(payloads[1].spec));
  delete missingSpec.traces[0].keys;
  missingView.updatePayload(missingSpec,unpack(payloads[1]));
  const missingRecorded=missingView.gpuTraces[0].trace.animation_fallback==="index:missing-keys"
    &&missingView.root.dataset.xyAnimationFallback==="index:missing-keys";
  missingView.destroy();missingHost.remove();
  const view=xy.renderStandalone(host,payloads[0].spec,unpack(payloads[0]));
  setTimeout(()=>{{
    view.updatePayload(payloads[1].spec,unpack(payloads[1]));
    const match=JSON.stringify(view.gpuTraces[0]._transitionMatch.pairs);
    const scratch=!!view.gpuTraces[0]._transitionPrevXBuf;
    const active=!!view._dataAnim&&view._transitionOldTraces.length===1;
    const ghostFree=view.gpuTraces[0]._transitionPositionInterpolated===true
      &&(view.gpuTraces[0]._transitionOpacity??1)===1
      &&view._transitionOldTraces[0]._transitionOpacity===0;
    if(view._dataAnimRaf)cancelAnimationFrame(view._dataAnimRaf);
    view._dataAnimRaf=null;
    const moving=view.gpuTraces[0];
    view._setTransitionVisual(moving,"update",0.5,view._resolvedAnimation(moving.trace));
    view._drawNow();
    const alphaNear=(x,y)=>{{
      const px=Math.round(x/30*view.canvas.width);
      const py=Math.round(y/30*view.canvas.height);
      const rgba=new Uint8Array(7*7*4);
      view.gl.readPixels(Math.max(0,px-3),Math.max(0,py-3),7,7,view.gl.RGBA,view.gl.UNSIGNED_BYTE,rgba);
      let alpha=0;for(let i=3;i<rgba.length;i+=4)alpha=Math.max(alpha,rgba[i]);
      return alpha;
    }};
    const pixelClean=alphaNear(17,13)>64&&alphaNear(4.5,8.5)>64
      &&alphaNear(12,8)<16&&alphaNear(2,3)<16;
    view._renderPick();
    const pickable=!view._interactionTransitionActive()&&!view._pickDirty;
    view.updatePayload(payloads[2].spec,unpack(payloads[2]));
    const partial=view.gpuTraces[0]._transitionPositionInterpolated===true
      &&!!view.gpuTraces[0]._transitionPrevXBuf
      &&view.gpuTraces[0]._transitionMatch.pairs.length===2
      &&view.gpuTraces[0].n===3
      &&view._transitionOldTraces[0]._transitionOpacity===0
      &&!view.gpuTraces[0].trace.animation_fallback;
    const obsoleteOld=view._transitionOldTraces[0];
    const replacementSource=view.gpuTraces[0];
    view.updatePayload(payloads[3].spec,unpack(payloads[3]));
    const replacement=view._transitionOldTraces[0]===replacementSource
      &&view.gpuTraces[0]!==replacementSource
      &&obsoleteOld.xBuf===null&&obsoleteOld._cpu===null;
    const bounded=view.gpuTraces.length===1&&view._transitionOldTraces.length===1;
    if(view._dataAnimRaf) cancelAnimationFrame(view._dataAnimRaf);
    view._dataAnimRaf=null;
    for(const trace of view.gpuTraces)view._clearTransitionVisual(trace);
    view._finishDataAnimation("update");
    setTimeout(()=>{{
      const done=!view._dataAnim&&!view._transitionOldTraces
        && !view.gpuTraces[0]._transitionPrevXBuf;
      const lifecycle=starts===ends&&starts>=4;
      document.title=`XY_ANIM_OK match=${{match}} scratch=${{+scratch}} ghost=${{+ghostFree}} pixel=${{+pixelClean}} partial=${{+partial}} missing=${{+missingRecorded}} active=${{+active}} pick=${{+pickable}} bounded=${{+bounded}} replacement=${{+replacement}} done=${{+done}} lifecycle=${{+lifecycle}} reduced=${{+reduced}} frozen=${{+frozen}} destroy=${{+destroyBalanced}} errorbar=${{+errorbarGrow}} bar=${{+barInterpolates}} hbar=${{+horizontalBarInterpolates}} events=${{starts}}/${{ends}}`;
    }},80);
  }},80);
}}catch(error){{document.title="XY_ANIM_ERROR "+(error.stack||error.message)}}
</script></body></html>"""
    try:
        executable = _chrome(args.chromium)
    except RuntimeError as exc:
        title = f"XY_ANIM_ERROR {exc}"
        evidence = _evidence(title=title, chromium=args.chromium, returncode=None)
        if args.evidence is not None:
            _write_evidence(args.evidence, evidence)
        print(title)
        return 1

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "animation.html"
        path.write_text(page, encoding="utf-8")
        command = [
            executable,
            "--headless=new",
            "--no-sandbox",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--force-prefers-reduced-motion=reduce",
            "--virtual-time-budget=1400",
            "--dump-dom",
            path.as_uri(),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            title = "XY_ANIM_ERROR browser timeout after 60s"
            evidence = _evidence(
                title=title,
                chromium=executable,
                returncode=None,
                stderr=stderr,
                timed_out=True,
            )
            if args.evidence is not None:
                _write_evidence(args.evidence, evidence)
            print(title)
            if stderr:
                print(stderr[-2000:])
            return 1
        except OSError as exc:
            title = f"XY_ANIM_ERROR browser startup failed: {exc}"
            evidence = _evidence(title=title, chromium=executable, returncode=None)
            if args.evidence is not None:
                _write_evidence(args.evidence, evidence)
            print(title)
            return 1
    title_match = re.search(r"<title>([^<]+)</title>", result.stdout)
    title = title_match.group(1) if title_match else "(none)"
    evidence = _evidence(
        title=title,
        chromium=executable,
        returncode=result.returncode,
        stderr=result.stderr,
    )
    if args.evidence is not None:
        _write_evidence(args.evidence, evidence)
    print(title)
    if evidence["status"] != "ok":
        print(result.stderr[-2000:])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
