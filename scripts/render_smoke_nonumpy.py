"""Headless render smoke that needs neither numpy nor PyPI.

Builds a payload by hand (stdlib `array` + `struct`) in exactly the wire shape
`Figure.build_payload` emits, drives the pre-installed Chromium against the
standalone JS bundle, and reads back a lit-pixel count via gl.readPixels. This
verifies the *render client* — the half cargo can't touch — in a locked-down
environment. The numpy-backed `scripts/smoke_render.py` supersedes it once deps
are installable.
"""

from __future__ import annotations

import base64
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "fastcharts" / "static"
CHROMIUM_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
]


def find_chromium() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


def encode_f32(vals, offset):  # noqa: ANN001
    return array("f", [float(v - offset) for v in vals]).tobytes()


def build_payload():
    # Exercises the full scatter path: a line, a scatter with continuous color
    # + variable size, and a Tier-2 density surface — all in Figure's wire shape.
    n = 2000
    xs = [float(i) for i in range(n)]
    ys = [math.sin(i * 0.02) for i in range(n)]
    ys[1000] = 5.0

    cols = []
    blob = bytearray()

    def ship(vals, offset=None, kind="float"):
        off = ((min(vals) + max(vals)) / 2.0) if offset is None else offset
        raw = encode_f32(vals, off)
        cols.append(
            {"byte_offset": len(blob), "len": len(vals), "offset": off, "scale": 1.0, "kind": kind}
        )
        blob.extend(raw)
        return len(cols) - 1

    def ship_scalar(vals):
        raw = array("f", [float(v) for v in vals]).tobytes()
        cols.append({"byte_offset": len(blob), "len": len(vals)})
        blob.extend(raw)
        return len(cols) - 1

    # continuous color = normalized index; variable size = |sin|.
    m = n // 20
    cvals = [i / (m - 1) for i in range(m)]
    svals = [abs(math.sin(i * 0.4)) for i in range(m)]

    # A density grid (8×6) with a hotspot, hand-built.
    gw, gh = 8, 6
    grid = [0.0] * (gw * gh)
    grid[gh // 2 * gw + gw // 2] = 500.0
    for i in range(gw * gh):
        grid[i] += i % 3
    density_buf = ship_scalar(grid)

    traces = [
        {
            "id": 0,
            "kind": "line",
            "name": "sine",
            "tier": "direct",
            "n_points": n,
            "style": {"color": "#4c78a8", "width": 1.5, "opacity": 1.0},
            "x": ship(xs),
            "y": ship(ys),
        },
        {
            "id": 1,
            "kind": "scatter",
            "name": "pts",
            "tier": "direct",
            "n_points": m,
            "style": {"opacity": 0.85},
            "x": ship(xs[::20]),
            "y": ship([v + 2.0 for v in ys[::20]]),
            "color": {
                "mode": "continuous",
                "colormap": "viridis",
                "domain": [0.0, 1.0],
                "buf": ship_scalar(cvals),
            },
            "size": {"mode": "continuous", "range_px": [3.0, 16.0], "buf": ship_scalar(svals)},
        },
        {
            "id": 2,
            "kind": "scatter",
            "name": "density",
            "tier": "density",
            "n_points": 1_000_000,
            "style": {"opacity": 1.0},
            "density": {
                "buf": density_buf,
                "w": gw,
                "h": gh,
                "max": 502.0,
                "colormap": "magma",
                "x_range": [0.0, float(n)],
                "y_range": [-3.0, 8.0],
                "channels_dropped": False,
            },
        },
    ]
    spec = {
        "protocol": 2,
        "width": 800,
        "height": 400,
        "title": "nonumpy smoke",
        "x_axis": {"kind": "linear", "label": "i", "range": [0.0, float(n)]},
        "y_axis": {"kind": "linear", "label": "y", "range": [-3.0, 8.0]},
        "traces": traces,
        "columns": cols,
        "backend": "none",
    }
    return spec, bytes(blob)


def main() -> None:
    standalone = (STATIC / "standalone.js").read_text(encoding="utf-8")
    spec, blob = build_payload()
    # sanity: blob is 4 bytes per shipped f32
    assert len(blob) == sum(c["len"] for c in spec["columns"]) * 4
    struct.unpack_from("<f", blob, 0)  # decodes as little-endian f32

    page = f"""<!doctype html><html><head><meta charset=utf-8><title>pending</title></head>
<body><div id=chart></div>
<script>{standalone}</script>
<script>
const spec={json.dumps(spec)};
const bytes=Uint8Array.from(atob("{base64.b64encode(blob).decode()}"),c=>c.charCodeAt(0));
try{{
  const v=fastcharts.renderStandalone(document.getElementById("chart"),spec,bytes.buffer);
  setTimeout(()=>{{try{{
    v._drawNow();
    const gl=v.gl,w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,px=new Uint8Array(w*h*4);
    gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
    let lit=0;for(let i=3;i<px.length;i+=4)if(px[i]>8)lit++;
    const labels=document.querySelectorAll(".fastcharts div").length;
    // Picking: scan the plot for any pickable scatter point (GPU ID readback).
    let hits=0, sampleRow=null;
    for(let sx=4; sx<v.plot.w && hits<1; sx+=3){{
      for(let sy=4; sy<v.plot.h; sy+=3){{
        const hit=v._pickAt(sx,sy);
        if(hit){{hits++; sampleRow=v._localRow(hit); break;}}
      }}
    }}
    const hasXY = sampleRow && sampleRow.x!==undefined ? 1 : 0;
    // Selection: box-select the left half in data space (standalone -> local mask).
    v._selectLocal(-1e9, 1e9, -1e9, 1e9);  // select everything first
    const selAll = v._selectionCount;
    v._clearSelection();
    v._selectLocal(0, 1000, -3, 8);        // a sub-range
    const selSome = v._selectionCount;
    const active = v.gpuTraces.some(g=>g.selActive) ? 1 : 0;
    // Modebar: button row present, and its zoom controls actually move the view.
    const bar = v._modebar;
    const btns = bar ? bar.querySelectorAll("button").length : 0;
    const spanX = () => v.view.x1 - v.view.x0;
    const s0 = spanX();
    v._zoomBy(0.5);                 // zoom in -> span shrinks
    const zin = spanX() < s0 ? 1 : 0;
    v._zoomBy(2);                   // back out
    v._zoomBy(0.8,true);            // modebar path animates
    const smooth=(v._viewAnim && v._animRaf)?1:0;
    const labelStamp=performance.now();
    const labelCount=v.labels.children.length;
    v._lastLabelDraw=labelStamp;
    v._drawChrome();
    const labelThrottle=(v._lastLabelDraw===labelStamp && v.labels.children.length===labelCount)?1:0;
    const pickAt0=v._pickAt;
    let hoverPickCalls=0;
    v._pickAt=function(){{hoverPickCalls++; return pickAt0.apply(this,arguments);}};
    const rc=v.canvas.getBoundingClientRect();
    v._hover({{clientX:rc.left+v.plot.w/2,clientY:rc.top+v.plot.h/2}});
    v._pickAt=pickAt0;
    const hoverSkip=(hoverPickCalls===0 && v.tooltip.style.display==="none")?1:0;
    v._cancelViewAnimation();
    v._zoomAt(0.8,0.25,0.75,true,95); // wheel path animates around cursor
    const zanch=(v._viewAnim && v._animRaf
      && (v._viewAnim.target.x1-v._viewAnim.target.x0)<spanX())?1:0;
    const retarget0=v._viewAnim ? (v._viewAnim.target.x1-v._viewAnim.target.x0) : Infinity;
    v._zoomAt(0.8,0.25,0.75,true,95);
    const retarget=(v._viewAnim && v._animRaf
      && (v._viewAnim.target.x1-v._viewAnim.target.x0)<retarget0)?1:0;
    v._cancelViewAnimation();
    v._raf=null;
    const realRaf=window.requestAnimationFrame;
    const realCancel=window.cancelAnimationFrame;
    const rafFns=[];
    window.requestAnimationFrame=(cb)=>{{rafFns.push(cb);return rafFns.length;}};
    window.cancelAnimationFrame=()=>{{}};
    v.view={{x0:0,x1:100,y0:0,y1:100}};
    const noSnapTarget={{x0:0,x1:50,y0:0,y1:50}};
    v._setView(noSnapTarget,{{animate:true,duration:20,request:false}});
    const noSnapLast=v._viewAnim ? v._viewAnim.last : 0;
    if(rafFns[0]) rafFns[0](noSnapLast+21);
    const nosnap=(v._viewAnim && v.view.x1>noSnapTarget.x1+1e-3 && v.view.x1<100)?1:0;
    window.requestAnimationFrame=realRaf;
    window.cancelAnimationFrame=realCancel;
    v._cancelViewAnimation();
    v._raf=null;
    v.comm={{sent:[],send(m){{this.sent.push(m);}}}};
    const prefetchTarget={{x0:25,x1:125,y0:-2,y1:4}};
    const prefetchOldSeq=v.seq;
    v._setView(prefetchTarget,{{animate:true,duration:180,requestDelay:0}});
    const prefetchSeq=v.seq;
    const prefetchMsg=v.comm.sent.find(m=>m.type==="density_view");
    const prefetch=(v._viewAnim && prefetchSeq===prefetchOldSeq+1 && prefetchMsg
      && prefetchMsg.seq===prefetchSeq
      && Math.abs(prefetchMsg.x0-prefetchTarget.x0)<1e-6
      && Math.abs(prefetchMsg.x1-prefetchTarget.x1)<1e-6
      && Math.abs(prefetchMsg.y0-prefetchTarget.y0)<1e-6
      && Math.abs(prefetchMsg.y1-prefetchTarget.y1)<1e-6)?1:0;
    v._cancelViewAnimation();
    clearTimeout(v._viewTimer);
    v.comm=null;
    v.comm={{sent:[],send(m){{this.sent.push(m);}}}};
    const maxWaitTarget={{x0:50,x1:80,y0:-1,y1:1}};
    const maxWaitOldSeq=v.seq;
    v._setView(maxWaitTarget,{{animate:true,duration:180,requestDelay:1000,requestMaxWait:0}});
    const maxWaitSeq=v.seq;
    const maxWaitMsg=v.comm.sent.find(m=>m.type==="density_view");
    const maxwait=(v._viewAnim && maxWaitSeq===maxWaitOldSeq+1 && maxWaitMsg
      && maxWaitMsg.seq===maxWaitSeq && v._viewRequestBurstStart===null
      && Math.abs(maxWaitMsg.x0-maxWaitTarget.x0)<1e-6
      && Math.abs(maxWaitMsg.x1-maxWaitTarget.x1)<1e-6)?1:0;
    v._cancelViewAnimation();
    clearTimeout(v._viewTimer);
    v.comm=null;
    v._zoomToBox([10,0],[20,5]);    // box-zoom fits the rectangle
    const boxOk = (Math.abs(v.view.x0-10)<1e-6 && Math.abs(v.view.x1-20)<1e-6) ? 1 : 0;
    v.view = {{...v.view0}};
    v._setDragMode("zoom");
    const zmode = (v.dragMode==="zoom" && v.canvas.style.cursor==="crosshair") ? 1 : 0;
    v._setDragMode("pan");
    // Adaptive LOD drill-in (§5): a synthetic kernel "points" update swaps the
    // density texture for real colored markers (pickable); a density update
    // swaps back. View is parked far from other traces so picks can't collide.
    const gd=v.gpuTraces.find(g=>g.tier==="density");
    const traces0=v.gpuTraces;
    const preDensityView={{...v.view}};
    v.gpuTraces=[gd];
    v.view={{x0:0,x1:spec.x_axis.range[1],y0:-3,y1:8}};
    v._drawNow();
    const dg=v.gl,dw=dg.drawingBufferWidth,dh=dg.drawingBufferHeight,dpx=new Uint8Array(dw*dh*4);
    dg.readPixels(0,0,dw,dh,dg.RGBA,dg.UNSIGNED_BYTE,dpx);
    let dlit=0;for(let i=3;i<dpx.length;i+=4)if(dpx[i]>8)dlit++;
    const densityLit=(dlit>100)?1:0;
    v.gpuTraces=traces0;
    v.view=preDensityView;
    v._drawNow();
    const oldView={{...v.view}};
    const n3=25, xs3=new Float32Array(n3), ys3=new Float32Array(n3), cs3=new Float32Array(n3);
    const ds3=new Float32Array(n3);
    for(let i=0;i<n3;i++){{xs3[i]=(i%5-2)*1.5; ys3[i]=(Math.floor(i/5)-2)*1.5; cs3[i]=i/n3;
      ds3[i]=1-i/n3;}}
    v._hoverId=42; v._lastRow={{x:1}}; // must be invalidated by the subset swap
    v.view={{x0:0,x1:2000,y0:-3,y1:8}};
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x_range:[5000,5010],y_range:[5000,5010],
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}},
      density_val:{{buf:3}},lod_blend:0.85,density_colormap:"magma"}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer,ds3.buffer]);
    const pendingDensity0=v._drawDensity;
    const pendingPoints0=v._drawPoints;
    let pendingDensity=0, pendingPoints=0;
    v._drawDensity=function(gg,dd,op){{if(gg===gd)pendingDensity++;return pendingDensity0.call(this,gg,dd,op);}};
    v._drawPoints=function(gg,xm,ym,op){{if(gg===gd.drill)pendingPoints++;return pendingPoints0.call(this,gg,xm,ym,op);}};
    v._drawNow();
    const pending=(gd.drill && gd._drillWasInside!==true && pendingDensity>0 && pendingPoints===0)?1:0;
    v._drawDensity=pendingDensity0;
    v._drawPoints=pendingPoints0;
    v.view={{x0:5000,x1:5010,y0:5000,y1:5010}};
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x_range:[5000,5010],y_range:[5000,5010],
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}},
      density_val:{{buf:3}},lod_blend:0.85,density_colormap:"magma",drill_seq:5}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer,ds3.buffer]);
    const drilled=(gd.drill && gd.drill.n===n3 && gd.drill.colorMode===1
      && v._viewInside(gd.drill.win)===true)?1:0;
    // Color-continuous handoff: the drill carries local density + blend weight,
    // and the first arrival shows it without a tween-from-zero flash.
    const dblend=(gd.drill && gd.drill.dBuf && gd.drill.dlut
      && Math.abs(gd.drill.lodBlend-0.85)<1e-6
      && gd.drill.lodBlendShown===gd.drill.lodBlend)?1:0;
    // Staff-review invariants: subset version stored, stale hover cache
    // invalidated, stale selection masks dropped (wrong index space), and
    // palette LUTs cached (categorical drills leaked a texture per update).
    const dseq=(gd.drill && gd.drill.seq===5)?1:0;
    const hov=(v._hoverId===-1 && !v._lastRow)?1:0;
    const selIdx=new Uint32Array([0,1,2]);
    v._onKernelMsg({{type:"selection",total:3,traces:[{{id:gd.trace.id,buf:0,drill_seq:4}}]}},
      [selIdx.buffer]);
    const sstale=(gd.drill.selActive!==true)?1:0;
    v._onKernelMsg({{type:"selection",total:3,traces:[{{id:gd.trace.id,buf:0,drill_seq:5}}]}},
      [selIdx.buffer]);
    const sfresh=(gd.drill.selActive===true)?1:0;
    v._clearSelection();
    const plut=(v._paletteLut(["#112233","#445566"])===v._paletteLut(["#112233","#445566"]))?1:0;
    // Mark registry contract: all per-kind client knowledge lives in
    // MARK_KINDS (build/draw + capabilities); unknown kinds fall back to
    // scatter; lines are not point-pickable; theme refresh dispatches.
    const reg=(typeof fastcharts.MARK_KINDS==="object"
      && fastcharts.MARK_KINDS.scatter.pointPick===true && fastcharts.MARK_KINDS.scatter.retainCpu===true
      && !fastcharts.MARK_KINDS.line.pointPick
      && typeof fastcharts.MARK_KINDS.scatter.refreshColor==="function"
      && typeof fastcharts.MARK_KINDS.line.refreshColor==="function"
      && fastcharts.markOf("nonexistent")===fastcharts.MARK_KINDS.scatter)?1:0;
    // Flashing fix: a points REFRESH (already drilled) must not restart the
    // entry fade — restarting blanked the points to ~0 alpha on every kernel
    // reply while zooming inside a drilled view.
    gd._drillFadeStart=null; // entry fade settled
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x_range:[5000,5010],y_range:[5000,5010],
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}},
      density_val:{{buf:3}},lod_blend:0.7,density_colormap:"magma",drill_seq:6}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer,ds3.buffer]);
    const refresh=(gd.drill && gd.drill.seq===6 && gd._drillFadeStart===null
      && gd._drillDying!==true)?1:0;
    v._drawNow();
    const hit3=v._pickAt(v.plot.w/2, v.plot.h/2);
    const dpick=(hit3 && hit3.trace===gd.trace.id)?1:0;
    // Tiny drill-to-drill zoom-outs should not flash the broad density texture
    // while the next point subset is pending. Keep the resident drilled marks
    // for the short wait when the pending target is still under direct budget.
    const holdDensity0=v._drawDensity;
    const holdPoints0=v._drawPoints;
    let holdDensity=0, holdPoints=0;
    v._drawDensity=function(gg,dd,op){{if(gg===gd)holdDensity++;return holdDensity0.call(this,gg,dd,op);}};
    v._drawPoints=function(gg,xm,ym,op){{if(gg===gd.drill)holdPoints++;return holdPoints0.call(this,gg,xm,ym,op);}};
    v.seq+=1;
    gd._lodPendingSeq=v.seq;
    gd._lodPendingView={{x0:4980,x1:5030,y0:4980,y1:5030}};
    gd._lodPendingAt=performance.now();
    v.view={{...gd._lodPendingView}};
    v._drawNow();
    const hold=(holdPoints>0 && holdDensity===0 && gd._drillExitFadeStart==null)?1:0;
    gd._lodPendingSeq=null;
    gd._lodPendingView=null;
    gd._lodPendingAt=null;
    v._drawDensity=holdDensity0;
    v._drawPoints=holdPoints0;
    // Zoom out past the drilled window: still drilled, but now a cached
    // overview must cover the view (no blank), even if the current density
    // texture is a narrower intermediate one.
    const savedOverview={{...gd.density}};
    gd.density={{...gd.density,xRange:[5000,5010],yRange:[5000,5010]}};
    gd._shownDensity=gd.density;
    gd._densitySwitchPrev=null;
    gd._densitySwitchFadeStart=null;
    gd.densityCache=[savedOverview,gd.density];
    const drawDensity0=v._drawDensity;
    const drawPoints0=v._drawPoints;
    let zdensity=0, zpoints=0, zcovered=0, zpointsDone=0, broadfallback=0, zphase="fade";
    v._drawDensity=function(gg,dd,op){{
      if(gg===gd){{
        zdensity++;
        if(zphase==="broad" && dd===savedOverview) broadfallback=1;
        if(dd && dd.xRange[0]<=v.view.x0 && dd.xRange[1]>=v.view.x1
          && dd.yRange[0]<=v.view.y0 && dd.yRange[1]>=v.view.y1)zcovered=1;
      }}
      return drawDensity0.call(this,gg,dd,op);
    }};
    v._drawPoints=function(gg,xm,ym,op){{
      if(gg===gd.drill){{
        if(zphase==="fade") zpoints++;
        else zpointsDone++;
      }}
      return drawPoints0.call(this,gg,xm,ym,op);
    }};
    v.view={{x0:0,x1:2000,y0:-3,y1:8}};
    v._drawNow();
    const zfade=(zpoints>0 && gd._drillExitFadeStart!==undefined && gd._drillExitFadeStart!==null)?1:0;
    const zswitch=(gd._densitySwitchPrev===gd.density && gd._shownDensity===savedOverview
      && gd._densitySwitchFadeStart!==undefined && gd._densitySwitchFadeStart!==null)?1:0;
    gd._drillExitFadeStart-=121;
    gd._densitySwitchFadeStart-=141;
    zphase="done";
    zpoints=0;
    v._drawNow();
    const zswitchDone=(!gd._densitySwitchPrev && !gd._densitySwitchFadeStart)?1:0;
    const broadView={{...v.view}};
    v.view={{x0:-100,x1:3000,y0:-10,y1:20}};
    zphase="broad";
    v._drawNow();
    v.view=broadView;
    v._drawDensity=drawDensity0;
    v._drawPoints=drawPoints0;
    const zoomout=(gd.drill && v._viewInside(gd.drill.win)===false
      && gd.density && gd.density.tex && zdensity>0 && zfade===1 && zpoints===0
      && zpointsDone===0 && zcovered===1 && zswitch===1 && zswitchDone===1)?1:0;
    v.view={{x0:5000,x1:5010,y0:5000,y1:5010}};
    const grid3=new Float32Array(16).fill(1);
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"density",visible:999999,
      density:{{buf:0,w:4,h:4,max:1,x_range:[5000,5010],y_range:[5000,5010]}}}}]}},[grid3.buffer]);
    // Flashing fix: drill-out must not hard-cut the points. The drill is
    // marked dying, fades over the incoming density, and is freed only when
    // the exit fade completes.
    const dying=(gd.drill && gd._drillDying===true && gd._drillExitFadeStart!=null)?1:0;
    const dnorm=(gd.density && gd.density.max===1 && gd.density.normMax>gd.density.max)?1:0;
    gd._drillExitFadeStart-=999; // expire the exit fade
    v._drawNow();
    const dback=(!gd.drill && gd._drillDying!==true)?1:0;
    if(gd._densityNormAnim) gd._densityNormAnim.startedAt-=gd._densityNormAnim.duration+1;
    v._drawNow();
    const dnormDone=(gd.density && Math.abs(gd.density.normMax-gd.density.max)<1e-6
      && !gd._densityNormAnim)?1:0;
    v.seq=12;
    v._onKernelMsg({{type:"density_update",seq:11,traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}}}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer]);
    const staleReply=(!gd.drill)?1:0;
    v.comm={{sent:[],send(m){{this.sent.push(m);}}}};
    const oldSeq=v.seq;
    v._scheduleViewRequest();
    const queuedSeq=v.seq;
    v._onKernelMsg({{type:"density_update",seq:oldSeq,traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}}}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer]);
    clearTimeout(v._viewTimer);
    v.comm=null;
    const staleQueued=(queuedSeq===oldSeq+1 && !gd.drill)?1:0;
    const oldAnimSeq=v.seq;
    v._setView({{x0:10,x1:20,y0:10,y1:20}},{{animate:true}});
    const animSeq=v.seq;
    v._onKernelMsg({{type:"density_update",seq:oldAnimSeq,traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}}}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer]);
    v._cancelViewAnimation();
    const staleAnim=(animSeq===oldAnimSeq+1 && !gd.drill)?1:0;
    const stale=(staleReply && staleQueued && staleAnim)?1:0;
    v.view=oldView;
    v._drawNow();
    const base=`FC_OK lit=${{lit}} total=${{w*h}} labels=${{labels}} pick=${{hits}} row=${{hasXY}} selAll=${{selAll}} selSome=${{selSome}} active=${{active}} btns=${{btns}} zin=${{zin}} smooth=${{smooth}} labelThrottle=${{labelThrottle}} hoverSkip=${{hoverSkip}} zanch=${{zanch}} retarget=${{retarget}} nosnap=${{nosnap}} prefetch=${{prefetch}} maxwait=${{maxwait}} box=${{boxOk}} zmode=${{zmode}} densityLit=${{densityLit}} drill=${{drilled}} pending=${{pending}} dblend=${{dblend}} dseq=${{dseq}} hov=${{hov}} sstale=${{sstale}} sfresh=${{sfresh}} plut=${{plut}} reg=${{reg}} refresh=${{refresh}} dpick=${{dpick}} hold=${{hold}} zoomout=${{zoomout}} broad=${{broadfallback}} dying=${{dying}} dback=${{dback}} dnorm=${{dnorm}} dnormDone=${{dnormDone}} stale=${{stale}}`;
    // Responsive: 100%-by-100% chart in a 400x300 container tracks its parent;
    // growing the container must fire the ResizeObserver and re-render bigger.
    const spec2=JSON.parse(JSON.stringify(spec));
    spec2.width="100%";
    spec2.height="100%";
    const holder=document.createElement("div");
    holder.style.width="400px";
    holder.style.height="300px";
    document.body.appendChild(holder);
    const v2=fastcharts.renderStandalone(holder,spec2,bytes.buffer);
    const fluid0=(v2.fluid===true && v2.fluidH===true && v2.size.w===400 && v2.size.h===300
      && v2.root.style.width==="100%" && v2.root.style.height==="100%")?1:0;
    holder.style.width="640px";
    holder.style.height="360px";
    setTimeout(()=>{{try{{
      const grew=(v2.size.w===640 && v2.size.h===360 && v2.canvas.width===v2.plot.w*v2.dpr
        && v2.canvas.height===v2.plot.h*v2.dpr && v2.chrome.width===640*v2.dpr
        && v2.chrome.height===360*v2.dpr)?1:0;
      v2._pickAt(4,4); // exercises _renderPick -> deferred pick-FBO realloc
      const pick2=(v2._pickW===v2.canvas.width && v2._pickH===v2.canvas.height)?1:0;
      document.title=`${{base}} fluid=${{fluid0}} grew=${{grew}} pick2=${{pick2}}`;
    }}catch(e){{document.title="FC_ERROR "+e.message}}}},250);
  }}catch(e){{document.title="FC_ERROR "+e.message}}}},200);
}}catch(e){{document.title="FC_ERROR "+e.message}}
</script></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.html"
        p.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [
                find_chromium(),
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--virtual-time-budget=4000",
                "--dump-dom",
                p.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    m = re.search(r"<title>([^<]*)</title>", out.stdout)
    title = m.group(1) if m else "(none)"
    print("probe:", title)
    if not title.startswith("FC_OK"):
        print(out.stderr[-2000:], file=sys.stderr)
        raise SystemExit("render failed")
    lit = int(re.search(r"lit=(\d+)", title).group(1))
    total = int(re.search(r"total=(\d+)", title).group(1))
    labels = int(re.search(r"labels=(\d+)", title).group(1))
    pick = int(re.search(r"pick=(\d+)", title).group(1))
    rowok = int(re.search(r"row=(\d+)", title).group(1))
    sel_all = int(re.search(r"selAll=(\d+)", title).group(1))
    sel_some = int(re.search(r"selSome=(\d+)", title).group(1))
    active = int(re.search(r"active=(\d+)", title).group(1))
    btns = int(re.search(r"btns=(\d+)", title).group(1))
    zin = int(re.search(r"zin=(\d+)", title).group(1))
    smooth = int(re.search(r"smooth=(\d+)", title).group(1))
    label_throttle = int(re.search(r"labelThrottle=(\d+)", title).group(1))
    hover_skip = int(re.search(r"hoverSkip=(\d+)", title).group(1))
    zanch = int(re.search(r"zanch=(\d+)", title).group(1))
    retarget = int(re.search(r"retarget=(\d+)", title).group(1))
    nosnap = int(re.search(r"nosnap=(\d+)", title).group(1))
    prefetch = int(re.search(r"prefetch=(\d+)", title).group(1))
    maxwait = int(re.search(r"maxwait=(\d+)", title).group(1))
    box = int(re.search(r"box=(\d+)", title).group(1))
    zmode = int(re.search(r"zmode=(\d+)", title).group(1))
    fluid = int(re.search(r"fluid=(\d+)", title).group(1))
    grew = int(re.search(r"grew=(\d+)", title).group(1))
    pick2 = int(re.search(r"pick2=(\d+)", title).group(1))
    drill = int(re.search(r"drill=(\d+)", title).group(1))
    pending = int(re.search(r"pending=(\d+)", title).group(1))
    dblend = int(re.search(r"dblend=(\d+)", title).group(1))
    dseq = int(re.search(r"dseq=(\d+)", title).group(1))
    hov = int(re.search(r"hov=(\d+)", title).group(1))
    sstale = int(re.search(r"sstale=(\d+)", title).group(1))
    sfresh = int(re.search(r"sfresh=(\d+)", title).group(1))
    plut = int(re.search(r"plut=(\d+)", title).group(1))
    reg = int(re.search(r"reg=(\d+)", title).group(1))
    refresh = int(re.search(r"refresh=(\d+)", title).group(1))
    dying = int(re.search(r"dying=(\d+)", title).group(1))
    density_lit = int(re.search(r"densityLit=(\d+)", title).group(1))
    dpick = int(re.search(r"dpick=(\d+)", title).group(1))
    hold = int(re.search(r"hold=(\d+)", title).group(1))
    zoomout = int(re.search(r"zoomout=(\d+)", title).group(1))
    broad = int(re.search(r"broad=(\d+)", title).group(1))
    dback = int(re.search(r"dback=(\d+)", title).group(1))
    dnorm = int(re.search(r"dnorm=(\d+)", title).group(1))
    dnorm_done = int(re.search(r"dnormDone=(\d+)", title).group(1))
    stale = int(re.search(r"stale=(\d+)", title).group(1))
    frac = lit / max(total, 1)
    print(
        f"lit fraction: {frac:.3%}, DOM chrome nodes: {labels}, pick hits: {pick}, "
        f"row-decoded: {rowok}, select all/sub: {sel_all}/{sel_some}, mask active: {active}, "
        f"modebar btns: {btns}, zoom-in: {zin}, box-zoom: {box}, zoom-mode: {zmode}, "
        f"fluid: {fluid}, resize grew: {grew}, pick realloc: {pick2}"
    )
    # Upper bound guards "every pixel lit = blend/clear broke", not brightness:
    # the current density opacity ramp legitimately lights ~95% of the plot.
    if not (0.001 < frac < 0.985):
        raise SystemExit(f"suspicious lit fraction {frac}")
    if labels < 6:
        raise SystemExit(f"too few DOM tick labels: {labels}")
    if pick < 1:
        raise SystemExit("GPU picking found no scatter point")
    if rowok < 1:
        raise SystemExit("picked point did not decode to x/y (standalone hover)")
    if sel_all < 1:
        raise SystemExit("box-select over everything selected nothing")
    if not (0 < sel_some <= sel_all):
        raise SystemExit(f"sub-range selection implausible: {sel_some} of {sel_all}")
    if active != 1:
        raise SystemExit("selection mask did not activate")
    if btns < 5:
        raise SystemExit(f"modebar missing buttons: {btns}")
    if zin != 1:
        raise SystemExit("modebar zoom-in did not shrink the view span")
    if smooth != 1:
        raise SystemExit("animated zoom did not schedule a smooth view transition")
    if label_throttle != 1:
        raise SystemExit("animated zoom rebuilt DOM tick labels instead of throttling them")
    if hover_skip != 1:
        raise SystemExit("hover picking was not suspended during zoom animation")
    if zanch != 1:
        raise SystemExit("cursor-anchored wheel zoom did not schedule a smooth transition")
    if retarget != 1:
        raise SystemExit("repeated wheel zoom did not retarget the active smooth transition")
    if nosnap != 1:
        raise SystemExit("animated zoom snapped to its target at the nominal deadline")
    if prefetch != 1:
        raise SystemExit("animated zoom did not prefetch the target LOD view")
    if maxwait != 1:
        raise SystemExit("continuous zoom max-wait did not force a target LOD request")
    if box != 1:
        raise SystemExit("box-zoom did not fit the dragged rectangle")
    if zmode != 1:
        raise SystemExit("drag-mode toggle did not switch to box-zoom")
    if fluid != 1:
        raise SystemExit('width:"100%" chart did not track its 400px container')
    if grew != 1:
        raise SystemExit("ResizeObserver resize did not re-render at the new width")
    if pick2 != 1:
        raise SystemExit("pick FBO was not reallocated to the resized canvas")
    if drill != 1:
        raise SystemExit("density trace did not drill in to points on a points update")
    if pending != 1:
        raise SystemExit("prefetched drill points flashed before the view entered their window")
    if dblend != 1:
        raise SystemExit("drill update did not carry the local-density color blend")
    if dseq != 1:
        raise SystemExit("drill subset version (drill_seq) was not stored on the client")
    if hov != 1:
        raise SystemExit("stale hover cache survived a drilled-subset swap")
    if sstale != 1:
        raise SystemExit("selection mask from another drill_seq was applied (index-space bug)")
    if sfresh != 1:
        raise SystemExit("matching-drill_seq selection mask was not applied")
    if plut != 1:
        raise SystemExit("palette LUT not cached (GL texture leak per categorical drill)")
    if reg != 1:
        raise SystemExit("MARK_KINDS registry contract broken (capabilities/fallback)")
    if refresh != 1:
        raise SystemExit("points refresh restarted the entry fade (per-reply flash)")
    if dying != 1:
        raise SystemExit("drill-out dropped points instantly instead of fading (flash)")
    if density_lit != 1:
        raise SystemExit("density trace did not render visible pixels by itself")
    if dpick != 1:
        raise SystemExit("drilled points were not pickable (GPU pick missed)")
    if hold != 1:
        raise SystemExit("small pending drill refresh fell back to density (yellow flash)")
    if zoomout != 1:
        raise SystemExit("zoom-out past the drilled window did not fall back to the overview")
    if broad != 1:
        raise SystemExit("density fallback did not prefer the broadest cached overview")
    if dback != 1:
        raise SystemExit("density update did not drop the drill state")
    if dnorm != 1:
        raise SystemExit("density color normalization snapped to the new max instead of easing")
    if dnorm_done != 1:
        raise SystemExit("density color normalization did not settle to the true max")
    if stale != 1:
        raise SystemExit("stale density update resurrected a drilled point subset")
    print(
        "render smoke OK (no numpy): line + colored/sized scatter + density + "
        "picking + box-select + modebar/box-zoom + responsive resize + LOD drill-in"
    )


if __name__ == "__main__":
    main()
