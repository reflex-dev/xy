"""Headless render smoke that needs neither numpy nor PyPI.

Builds a payload by hand (stdlib `array` + `struct`) in exactly the wire shape
the internal figure's `build_payload` emits, drives the pre-installed Chromium
against the
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

from _protocol import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "xy" / "static"
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
    # Exercises the main client paths: line, area, colored/sized scatter,
    # density, compact bars, and color-mapped heatmap cells.
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
        cols.append(
            {
                "byte_offset": len(blob),
                "len": len(vals),
                "offset": 0.0,
                "scale": 1.0,
                "kind": "float",
            }
        )
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
    heat_buf = ship_scalar([0.1, 0.45, 0.7, 1.0])

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
            "kind": "area",
            "name": "area",
            "tier": "direct",
            "n_points": n,
            "style": {"color": "#0891b2", "opacity": 0.32, "line_width": 1.0, "line_opacity": 1.0},
            "x": ship(xs),
            "y": ship([v - 1.0 for v in ys]),
            "base": ship([-2.5] * n),
        },
        {
            "id": 2,
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
            "id": 3,
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
                # Recorded §28 sample (real payloads always ship one): the
                # standalone worker re-bins these rows on zoom.
                "sample": {
                    "mode": "sampled",
                    "n": len(xs[::8]),
                    "visible": 1_000_000,
                    "target": 8192,
                    "level": 0,
                    "seed": 1,
                    "x": {"col": ship(xs[::8])},
                    "y": {"col": ship([v + 1.5 for v in ys[::8]])},
                    "x_range": [0.0, float(n)],
                    "y_range": [-3.0, 8.0],
                    "style": {"opacity": 0.5},
                },
            },
        },
        {
            "id": 4,
            "kind": "bar",
            "name": "bars",
            "tier": "direct",
            "n_points": 3,
            "style": {
                "color": "#16a34a",
                "opacity": 0.85,
                "role": "bar",
                "orientation": "vertical",
            },
            "bar": {
                "orientation": "vertical",
                "value_axis": "y",
                "pos": ship([1245.0, 1395.0, 1545.0]),
                "value1": ship([5.5, 7.0, 4.5]),
                "value0_const": 0.0,
                "width": 90.0,
            },
        },
        {
            "id": 5,
            "kind": "heatmap",
            "name": "heat",
            "tier": "direct",
            "n_points": 4,
            "style": {"color": None, "opacity": 0.92, "role": "heatmap"},
            "heatmap": {
                "buf": heat_buf,
                "w": 2,
                "h": 2,
                "x_range": [100.0, 340.0],
                "y_range": [5.5, 7.5],
                "colormap": "turbo",
                "domain": [0.0, 1.0],
            },
            "color": {"mode": "continuous", "colormap": "turbo", "domain": [0.0, 1.0]},
        },
    ]
    spec = {
        "protocol": PROTOCOL_VERSION,
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

    # Mirrors xy.export._STANDALONE_CSP (this script is stdlib-only by
    # design, so the string is inlined; a test asserts they stay identical) —
    # every probe below, including the blob-URL re-bin worker, runs under the
    # same policy a real to_html export ships.
    csp = (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data:; connect-src 'none'; worker-src blob:; object-src 'none'; "
        "base-uri 'none'; form-action 'none'"
    )
    page = f"""<!doctype html><html><head><meta charset=utf-8>
<meta http-equiv="Content-Security-Policy" content="{csp}"><title>pending</title></head>
<body><div id=chart></div>
<script>{standalone}</script>
<script>
const spec={json.dumps(spec)};
const bytes=Uint8Array.from(atob("{base64.b64encode(blob).decode()}"),c=>c.charCodeAt(0));
// Exercise the legacy anywidget compatibility path: an oddly-offset view must
// copy only its own span once, then render identically. Production XYBF HTTP
// frames are 8-byte aligned and stay zero-copy.
const unalignedOwner=new Uint8Array(bytes.byteLength+1);
unalignedOwner.set(bytes,1);
const unalignedBytes=unalignedOwner.subarray(1);
try{{
  const v=xy.renderStandalone(document.getElementById("chart"),spec,unalignedBytes);
  v._sampleRebinDisabled = true; // probes below hand-feed kernel msgs
  setTimeout(()=>{{try{{
    v._drawNow();
    const gl=v.gl,w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,px=new Uint8Array(w*h*4);
    gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
    let lit=0;for(let i=3;i<px.length;i+=4)if(px[i]>8)lit++;
    const labels=document.querySelectorAll(".xy div").length;
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
    const modebarHidden = bar && bar.style.opacity === "0" && bar.style.pointerEvents === "none" ? 1 : 0;
    v.root.dispatchEvent(new PointerEvent("pointerenter", {{bubbles:true}}));
    const modebarHover = bar && bar.style.opacity === "1" && bar.style.pointerEvents === "auto" ? 1 : 0;
    const grip = bar && bar.querySelector("[data-xy-modebar-drag-handle]");
    const modebarNoCollapse = bar && !bar.hasAttribute("data-xy-collapsed")
      && !bar.querySelector("[data-xy-modebar-collapse-item]")
      && [...bar.querySelectorAll(":scope > button")]
        .every((button) => !button.hidden && button.style.display !== "none") ? 1 : 0;
    const zoomTrigger = bar && bar.querySelector("[data-xy-modebar-menu-trigger]");
    const zoomMenu = bar && bar.querySelector("[data-xy-modebar-menu]");
    const selectButton = bar && bar.querySelector("[data-xy-modebar-select]");
    const selectMenu = bar && bar.querySelector("[data-xy-modebar-select-menu]");
    const exportButton = bar && bar.querySelector("[data-xy-modebar-export]");
    const exportMenu = bar && bar.querySelector("[data-xy-modebar-export-menu]");
    const zoomPercent = zoomTrigger && zoomTrigger.querySelector("[data-xy-modebar-zoom-percent]");
    const zoomIndicator = zoomTrigger && zoomTrigger.querySelector("[data-xy-modebar-menu-indicator] svg");
    const zoomTriggerInitial = zoomPercent && zoomPercent.textContent === "100%" && zoomIndicator;
    const zoomLabelView = v._copyView(v.view);
    v.view = v._viewFrom({{x0:v.view.x0,x1:v.view.x0+(v.view.x1-v.view.x0)/4000}});
    v._updateZoomMenuLabel();
    const zoomCompact = zoomPercent && zoomPercent.textContent === "400…%"
      && zoomPercent.dataset.xyZoomExact === "400000%";
    v.view = zoomLabelView;
    v._updateZoomMenuLabel();
    if (zoomTrigger) zoomTrigger.dispatchEvent(new MouseEvent("click", {{bubbles:true}}));
    const menuOpened = zoomMenu && zoomMenu.style.display === "flex"
      && zoomTrigger.getAttribute("aria-expanded") === "true"
      && zoomMenu.querySelectorAll("[data-xy-modebar-menu-item]").length === 4;
    if (zoomMenu) zoomMenu.dispatchEvent(new KeyboardEvent("keydown", {{key:"Escape",bubbles:true}}));
    const modebarMenu = menuOpened && zoomMenu.style.display === "none"
      && zoomTrigger.getAttribute("aria-expanded") === "false" ? 1 : 0;
    const barLeft0 = bar ? parseFloat(bar.style.left) : 0;
    if (grip) {{
      const gr = grip.getBoundingClientRect();
      grip.dispatchEvent(new PointerEvent("pointerdown", {{pointerId:71,pointerType:"mouse",button:0,
        clientX:gr.left+gr.width/2,clientY:gr.top+gr.height/2,bubbles:true}}));
      grip.dispatchEvent(new PointerEvent("pointermove", {{pointerId:71,pointerType:"mouse",button:0,
        clientX:gr.left+gr.width/2+80,clientY:gr.top+gr.height/2+40,bubbles:true}}));
      grip.dispatchEvent(new PointerEvent("pointerup", {{pointerId:71,pointerType:"mouse",button:0,
        clientX:gr.left+gr.width/2+80,clientY:gr.top+gr.height/2+40,bubbles:true}}));
      grip.dispatchEvent(new MouseEvent("click", {{bubbles:true}}));
    }}
    const modebarDrag = grip && parseFloat(bar.style.left) > barLeft0 + 20
      && bar.querySelectorAll("button[hidden]").length === 0 ? 1 : 0;
    if (selectButton) selectButton.dispatchEvent(new MouseEvent("click", {{bubbles:true}}));
    const selectItems = selectMenu
      ? [...selectMenu.querySelectorAll("[data-xy-modebar-select-item]")]
      : [];
    const selectModes = selectItems.map((item) => item.dataset.xyModebarSelectItem);
    const lassoItem = selectMenu
      && selectMenu.querySelector('[data-xy-modebar-select-item="select-lasso"]');
    const selectMenuOpened = selectMenu && selectMenu.style.display === "flex"
      && selectButton.getAttribute("aria-expanded") === "true"
      && ["select", "select-lasso", "select-x", "select-y"].every((mode) => selectModes.includes(mode));
    if (lassoItem) lassoItem.dispatchEvent(new MouseEvent("click", {{bubbles:true}}));
    const modebarSelect = selectMenuOpened && v.dragMode === "select-lasso"
      && selectButton.classList.contains("xy-active")
      && lassoItem.classList.contains("xy-active") && selectMenu.style.display === "none" ? 1 : 0;
    v._sendSelectPolygon([[0,-0.4],[4,-0.4],[4,0.4],[0,0.4]]);
    const lassoHandles = v.selLassoHandles
      ? [...v.selLassoHandles.querySelectorAll("[data-xy-selection-lasso-handle]")]
      : [];
    const lassoPathBefore = v.selLassoPath.getAttribute("d");
    const lassoPointBefore = v._lassoPolygon ? [...v._lassoPolygon[0]] : null;
    const pointer = (target, type, x, y, pointerId = 72) => target.dispatchEvent(new PointerEvent(type, {{
      pointerId,pointerType:"mouse",button:0,buttons:type === "pointerup" ? 0 : 1,
      clientX:x,clientY:y,bubbles:true,cancelable:true,
    }}));
    if (lassoHandles[0]) {{
      const cr = v.canvas.getBoundingClientRect();
      const handleRect = lassoHandles[0].getBoundingClientRect();
      pointer(lassoHandles[0], "pointerdown", handleRect.left + 2, handleRect.top + 2);
      pointer(v.selLasso, "pointermove", cr.left + cr.width * 0.3, cr.top + cr.height * 0.25);
      pointer(v.selLasso, "pointerup", cr.left + cr.width * 0.3, cr.top + cr.height * 0.25);
    }}
    const shortLassoBefore = JSON.stringify(v._lassoPolygon);
    const lassoCanvasRect = v.canvas.getBoundingClientRect();
    v._setDragMode("select-lasso");
    pointer(v.canvas, "pointerdown", lassoCanvasRect.left + 30, lassoCanvasRect.top + 30, 73);
    pointer(v.canvas, "pointermove", lassoCanvasRect.left + 34, lassoCanvasRect.top + 30, 73);
    pointer(v.canvas, "pointerup", lassoCanvasRect.left + 34, lassoCanvasRect.top + 30, 73);
    const shortLassoRestored = JSON.stringify(v._lassoPolygon) === shortLassoBefore;
    const manyLassoPoints = Array.from({{length:80}}, (_value, index) => ({{
      x:100+60*Math.cos(index/80*Math.PI*2),
      y:100+40*Math.sin(index/80*Math.PI*2),
      data:[index,index],
    }}));
    const simplifiedLasso = v._simplifyLassoPoints(manyLassoPoints);
    const lassoEdit = lassoHandles.length === 4 && v.selLasso.style.display === "block"
      && lassoPointBefore && (v._lassoPolygon[0][0] !== lassoPointBefore[0]
        || v._lassoPolygon[0][1] !== lassoPointBefore[1])
      && v.selLassoPath.getAttribute("d") !== lassoPathBefore
      && v.selLassoHandles.childElementCount === 4
      && simplifiedLasso.length >= 3 && simplifiedLasso.length <= 16
      && shortLassoRestored ? 1 : 0;
    if (exportButton) exportButton.dispatchEvent(new MouseEvent("click", {{bubbles:true}}));
    const exportItems = exportMenu
      ? [...exportMenu.querySelectorAll("[data-xy-modebar-export-item]")]
        .map((item) => item.dataset.xyModebarExportItem)
      : [];
    const exportOpened = exportMenu && exportMenu.style.display === "flex"
      && exportButton.getAttribute("aria-expanded") === "true"
      && ["png", "svg", "csv"].every((format) => exportItems.includes(format));
    if (exportMenu) exportMenu.dispatchEvent(new KeyboardEvent("keydown", {{key:"Escape",bubbles:true}}));
    const previousChartBg = v.root.style.getPropertyValue("--chart-bg");
    const previousFontFamily = v.root.style.fontFamily;
    v.root.style.setProperty("--chart-bg", "#123456");
    v.root.style.fontFamily = "Smoke Export Sans, sans-serif";
    const themedExport = v._exportSvgMarkup();
    if (previousChartBg) v.root.style.setProperty("--chart-bg", previousChartBg);
    else v.root.style.removeProperty("--chart-bg");
    v.root.style.fontFamily = previousFontFamily;
    const exportThemePreserved = themedExport.includes("#123456")
      && themedExport.includes("Smoke Export Sans");
    const shortcutHintsAbsent = !v.root.querySelector("[data-xy-modebar-menu-shortcut]");
    const modebarExport = exportOpened && typeof v._exportCsvText === "function"
      && typeof v._exportSvgMarkup === "function" && typeof v._exportPng === "function"
      && exportMenu.style.display === "none"
      && exportButton.getAttribute("aria-expanded") === "false"
      && exportThemePreserved && shortcutHintsAbsent ? 1 : 0;
    v._setDragMode("pan");
    const spanX = () => v.view.x1 - v.view.x0;
    const s0 = spanX();
    v._zoomBy(0.5);                 // zoom in -> span shrinks
    const zoomTriggerIn = zoomPercent && zoomPercent.textContent === "200%";
    const zin = spanX() < s0 && zoomTriggerInitial && zoomCompact && zoomTriggerIn ? 1 : 0;
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
    const zoomAxesInteraction=v.interaction;
    const zoomAxesView={{x0:0,x1:100,y0:0,y1:100}};
    v.interaction={{...(zoomAxesInteraction||{{}}),zoom_axes:["x"]}};
    v.view={{...zoomAxesView}};
    v._zoomBy(0.5);
    const xOnlyButton=(v.view.x1-v.view.x0<100 && v.view.y0===0 && v.view.y1===100);
    v._zoomAt(0.8,0.25,0.75,false);
    const xOnlyWheel=(v.view.x1-v.view.x0<50 && v.view.y0===0 && v.view.y1===100);
    v._zoomToBox([20,10],[40,30]);
    const xOnlyBox=(Math.abs(v.view.x0-20)<1e-6 && Math.abs(v.view.x1-40)<1e-6
      && v.view.y0===0 && v.view.y1===100);
    const xonly=(xOnlyButton && xOnlyWheel && xOnlyBox)?1:0;
    v.interaction=zoomAxesInteraction;
    v.view = {{...v.view0}};
    v._setDragMode("zoom");
    const zmode = (v.dragMode==="zoom" && v.canvas.dataset.xyDragmode==="zoom") ? 1 : 0;
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
    // The earlier lasso is still retained as brush geometry (§34), so the
    // drill apply above legitimately restored a provisional mask. Clear it so
    // the stale-mask assertion below isolates the drill_seq gate.
    v._clearSelection();
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
    const reg=(typeof xy.MARK_KINDS==="object"
      && xy.MARK_KINDS.scatter.pointPick===true && xy.MARK_KINDS.scatter.retainCpu===true
      && !xy.MARK_KINDS.line.pointPick
      && typeof xy.MARK_KINDS.area.draw==="function"
      && typeof xy.MARK_KINDS.bar.draw==="function"
      && xy.MARK_KINDS.bar!==xy.MARK_KINDS.histogram
      && xy.MARK_KINDS.column===xy.MARK_KINDS.bar
      && typeof xy.MARK_KINDS.heatmap.draw==="function"
      && xy.MARK_KINDS.heatmap!==xy.MARK_KINDS.histogram
      && typeof xy.MARK_KINDS.scatter.refreshColor==="function"
      && typeof xy.MARK_KINDS.line.refreshColor==="function"
      && xy.markOf("nonexistent")===xy.MARK_KINDS.scatter)?1:0;
    // Flashing fix: a points REFRESH (already drilled) must not restart the
    // entry fade — restarting blanked the points to ~0 alpha on every kernel
    // reply while zooming inside a drilled view.
    // Also §34 continuity: a retained data-space brush must re-derive a
    // provisional mask when the refresh swaps the subset (srestore below).
    v._lastBrush={{mode:"box",x0:5000,x1:5010,y0:5000,y1:5010}};
    gd._drillFadeStart=null; gd._drillWasInside=true; gd._drillShownAlpha=1; // entry fade settled (drawn inside)
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"points",visible:n3,
      x_range:[5000,5010],y_range:[5000,5010],
      x:{{buf:0,len:n3,offset:5005,scale:1}},y:{{buf:1,len:n3,offset:5005,scale:1}},
      color:{{mode:"continuous",colormap:"viridis",buf:2}},size:{{mode:"constant",size:8}},
      density_val:{{buf:3}},lod_blend:0.7,density_colormap:"magma",drill_seq:6}}]}},
      [xs3.buffer,ys3.buffer,cs3.buffer,ds3.buffer]);
    const refresh=(gd.drill && gd.drill.seq===6 && gd._drillFadeStart===null
      && gd._drillDying!==true)?1:0;
    const srestore=(gd.drill.selActive===true)?1:0;
    v._clearSelection();
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
    // Quantized wire: a log-u8 density update stays byte-identical in the
    // CPU cache, uploads directly to R8, and is 4x smaller than f32.
    const qmax=9.0;
    const qenc=new Uint8Array(64);
    for(let i=0;i<64;i++){{const c=(i%4===0)?9:(i%7===0?1:0);
      qenc[i]=c>0?Math.max(1,Math.min(255,Math.round(255*Math.log1p(c)/Math.log1p(qmax)))):0;}}
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"density",visible:12345,
      binning:"pyramid-L2",
      density:{{buf:0,w:8,h:8,max:qmax,enc:"log-u8",x_range:[0,100],y_range:[0,100]}}}}]}},[qenc.buffer]);
    const qg=gd.density&&gd.density.encoded;
    let qok=qg instanceof Uint8Array&&qg.length===64&&!('grid' in gd.density)?1:0;
    if(qok){{
      for(let i=0;i<64;i++){{if(qg[i]!==qenc[i])qok=0;}}
    }}
    const qwire=(qok && Math.abs(gd.density.max-qmax)<1e-9)?1:0;
    // --- Rapid zoom in/out torture (drill thrash): the marks/density alphas
    // must be CONTINUOUS across window-boundary crossings, dying-drill
    // revives, and kernel replies landing mid-transition. Runs on a virtual
    // clock so the fades advance deterministically per synthetic frame.
    const realNowT=performance.now.bind(performance);
    let clockOfsT=0;
    const chartNowT=v._now.bind(v);
    v._now=()=>realNowT()+clockOfsT;
    gd._lodPendingView=null; gd._lodPendingSeq=null; gd._lodPendingAt=null;
    const gridT=new Float32Array(64).fill(2);
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"density",visible:500000,
      density:{{buf:0,w:8,h:8,max:2,x_range:[0,100],y_range:[0,100]}}}}]}},[gridT.buffer]);
    const nT=64; const xsT=new Float32Array(nT), ysT=new Float32Array(nT);
    for(let i=0;i<nT;i++){{xsT[i]=(i%8-3.5)*2; ysT[i]=(Math.floor(i/8)-3.5)*2;}}
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"points",visible:nT,
      x_range:[40,60],y_range:[40,60],
      x:{{buf:0,len:nT,offset:50,scale:1}},y:{{buf:1,len:nT,offset:50,scale:1}},
      size:{{mode:"constant",size:6}},drill_seq:9}}]}},[xsT.buffer,ysT.buffer]);
    const INV={{x0:45,x1:55,y0:45,y1:55}}, OUTV={{x0:15,x1:85,y0:15,y1:85}};
    const dpT=v._drawPoints, ddT=v._drawDensity;
    let mAlpha=0,dAlpha=0;
    v._drawPoints=function(gg,xm,ym,op){{ if(gd.drill&&gg===gd.drill) mAlpha+=(op===undefined?1:op); return dpT.call(this,gg,xm,ym,op);}};
    v._drawDensity=function(gg,dens,op){{ if(gg===gd) dAlpha+=(op===undefined?1:op); return ddT.call(this,gg,dens,op);}};
    const framesT=[];
    const stepT=(vw)=>{{ if(vw)v.view=vw; clockOfsT+=24; mAlpha=0;dAlpha=0; v._drawNow(); framesT.push([mAlpha,dAlpha]); }};
    v.view=INV; clockOfsT+=500; v._drawNow(); // settle the entry fade
    // phase 1: cross the drill-window boundary every 3 frames (72ms) — fades
    // never complete, so any restart/snap shows up as an alpha jump.
    for(let i=0;i<24;i++) stepT(Math.floor(i/3)%2? INV:OUTV);
    // phase 2: while outside, a density reply marks the drill dying; the user
    // dives straight back in. The drilled subset is still exact for the
    // window — the marks must hand back continuously, not flash to density.
    stepT(OUTV);
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"density",visible:400000,
      density:{{buf:0,w:8,h:8,max:2,x_range:[0,100],y_range:[0,100]}}}}]}},[gridT.buffer]);
    stepT(OUTV);
    const reviveBase=framesT.length;
    for(let i=0;i<6;i++) stepT(INV);
    const reviveAlive=(gd.drill && gd._drillDying!==true)?1:0;
    // the kernel's points reply lands mid-revive: refresh, never snap
    v._onKernelMsg({{type:"density_update",traces:[{{id:gd.trace.id,mode:"points",visible:nT,
      x_range:[40,60],y_range:[40,60],
      x:{{buf:0,len:nT,offset:50,scale:1}},y:{{buf:1,len:nT,offset:50,scale:1}},
      size:{{mode:"constant",size:6}},drill_seq:10}}]}},[xsT.buffer,ysT.buffer]);
    for(let i=0;i<4;i++) stepT(INV);
    let maxJump=0, minCover=Infinity;
    for(let i=1;i<framesT.length;i++){{
      maxJump=Math.max(maxJump, Math.abs(framesT[i][0]-framesT[i-1][0]));
      minCover=Math.min(minCover, framesT[i][0]+framesT[i][1]);
    }}
    let reviveDip=1;
    for(let i=reviveBase;i<framesT.length;i++) reviveDip=Math.min(reviveDip, framesT[i][0]);
    const reviveRecovers=(framesT[reviveBase+3][0] > framesT[reviveBase][0]+0.15
      && framesT[framesT.length-1][0] > 0.9)?1:0;
    clockOfsT+=1000; v._drawNow();
    const thrashEnd=(gd.drill && gd._drillDying!==true && v._viewInside(gd.drill.win)===true
      && (gd.densityCache||[]).length<=8)?1:0;
    v._drawPoints=dpT; v._drawDensity=ddT; v._now=chartNowT;
    // one 24ms step of a 120ms smoothstep moves alpha at most ~0.31; anything
    // bigger is a restart/snap. Cover: marks+density together never near-blank.
    const thrash=(maxJump<0.45 && minCover>0.25 && reviveRecovers===1 && reviveAlive===1 && thrashEnd===1)?1:0;
    v.view=oldView;
    v._drawNow();
    // Positive bars/histograms pin zero to the bottom axis. Sample the bottom
    // physical rows under a mark so a DPR/half-pixel underfill cannot slip back.
    function baselineLit(view, cssX){{
      view._drawNow();
      const gl=view.gl;
      const rows=Math.max(1,Math.ceil(view.dpr||1));
      const x=Math.max(0,Math.min(gl.drawingBufferWidth-1,Math.round(cssX*(view.dpr||1))));
      const px=new Uint8Array(rows*4);
      gl.readPixels(x,0,1,rows,gl.RGBA,gl.UNSIGNED_BYTE,px);
      let maxA=0;for(let i=3;i<px.length;i+=4)maxA=Math.max(maxA,px[i]);
      return maxA>8?1:0;
    }}
    const barSpec=JSON.parse(JSON.stringify(spec));
    barSpec.width=220; barSpec.height=170; barSpec.title="";
    barSpec.show_legend=false; barSpec.show_modebar=false;
    barSpec.x_axis={{kind:"linear",label:"",range:[1200,1600]}};
    barSpec.y_axis={{kind:"linear",label:"",range:[0,8]}};
    barSpec.traces=[spec.traces.find(t=>t.kind==="bar")];
    const holderBar=document.createElement("div");
    document.body.appendChild(holderBar);
    const vBar=xy.renderStandalone(holderBar,barSpec,bytes.buffer);
    const barBase=baselineLit(vBar,((1245-1200)/(1600-1200))*vBar.plot.w);
    vBar.destroy(); holderBar.remove();
    const hbuf=new ArrayBuffer(32);
    const hcols=[]; let hoff=0;
    function hcol(vals){{
      new Float32Array(hbuf,hoff*4,vals.length).set(vals);
      hcols.push({{byte_offset:hoff*4,len:vals.length,offset:0,scale:1,kind:"float"}});
      hoff+=vals.length;
      return hcols.length-1;
    }}
    const histSpec={{
      protocol:{PROTOCOL_VERSION},width:220,height:170,title:"",
      x_axis:{{kind:"linear",label:"",range:[-1,2]}},
      y_axis:{{kind:"linear",label:"",range:[0,8]}},
      traces:[{{id:0,kind:"histogram",name:"hist",style:{{color:"#3b82f6",opacity:1,role:"histogram"}},
        tier:"direct",n_points:10,n_marks:2,x0:hcol([-0.5,0.5]),x1:hcol([0.5,1.5]),
        y0:hcol([0,0]),y1:hcol([6,4])}}],
      columns:hcols,backend:"none",show_legend:false,show_modebar:false
    }};
    const holderHist=document.createElement("div");
    document.body.appendChild(holderHist);
    const vHist=xy.renderStandalone(holderHist,histSpec,hbuf);
    const histBase=baselineLit(vHist,((0-(-1))/(2-(-1)))*vHist.plot.w);
    vHist.destroy(); holderHist.remove();
    const expectPad=-(2*Math.max(2,Math.ceil(v.dpr||1)))/200;
    const edgepad=Math.abs(v._edgePadForValue(0,0,8,200)-expectPad)<1e-9?1:0;
    // Hostile-spec suite: the renderer must fail LOUDLY (throw / visible
    // message), never hang or silently draw garbage (§28/§33 contracts).
    const mk = () => {{ const d = document.createElement("div"); document.body.appendChild(d); return d; }};
    const throws = (fn) => {{ try {{ fn(); return false; }} catch (e) {{ return true; }} }};
    // m1: protocol mismatch -> constructor throws AND leaves a visible message
    const m1el = mk();
    const badProto = JSON.parse(JSON.stringify(spec)); badProto.protocol = 999;
    const m1 = throws(() => xy.renderStandalone(m1el, badProto, bytes.buffer))
      && m1el.textContent.indexOf("protocol mismatch") >= 0 ? 1 : 0;
    // m2: trace referencing a column index that does not exist -> throws
    const badRef = JSON.parse(JSON.stringify(spec)); badRef.traces = [badRef.traces[0]];
    badRef.traces[0] = {{...badRef.traces[0], x: 999}};
    const m2 = throws(() => xy.renderStandalone(mk(), badRef, bytes.buffer)) ? 1 : 0;
    // m3: column window outside the blob -> typed-array construction throws
    const badOff = JSON.parse(JSON.stringify(spec));
    badOff.columns[badOff.traces[0].x] = {{...badOff.columns[badOff.traces[0].x],
      byte_offset: bytes.buffer.byteLength + 64}};
    badOff.traces = [badOff.traces[0]];
    const m3 = throws(() => xy.renderStandalone(mk(), badOff, bytes.buffer)) ? 1 : 0;
    // m4: unknown kind with valid geometry -> scatter fallback renders, no throw
    const unk = JSON.parse(JSON.stringify(spec));
    unk.traces = [{{...unk.traces[0], kind: "sparkle-9000", style: {{}}}}];
    let m4 = 0;
    try {{ const uv = xy.renderStandalone(mk(), unk, bytes.buffer); uv._drawNow(); m4 = 1; }}
    catch (e) {{ m4 = 0; }}
    // m5: empty traces -> chrome-only chart, no throw
    const emp = JSON.parse(JSON.stringify(spec)); emp.traces = [];
    let m5 = 0;
    try {{ const ev = xy.renderStandalone(mk(), emp, bytes.buffer); ev._drawNow(); m5 = 1; }}
    catch (e) {{ m5 = 0; }}
    const malformed = (m1 && m2 && m3 && m4 && m5) ? 1 : 0;
    // Pixel determinism: two fresh renders of the same payload hash identically
    // (the anti-shimmer guarantee — no RNG/time may reach the render path).
    const pixhash = (view) => {{
      view._drawNow();
      const g2 = view.gl, W = g2.drawingBufferWidth, H = g2.drawingBufferHeight;
      const p2 = new Uint8Array(W * H * 4);
      g2.readPixels(0, 0, W, H, g2.RGBA, g2.UNSIGNED_BYTE, p2);
      let hsh = 0x811c9dc5;
      for (let i = 0; i < p2.length; i++) {{ hsh ^= p2[i]; hsh = (hsh * 0x01000193) >>> 0; }}
      return hsh;
    }};
    // NOTE: the standalone density re-bin worker is deliberately NOT exercised
    // here. This harness renders under Chromium `--virtual-time-budget
    // --dump-dom`; a real Web Worker runs on wall-clock, not virtual time, so a
    // pending worker message keeps the page from settling and `--dump-dom`
    // hangs to the subprocess timeout. Worker source is asserted in
    // tests/test_static_client_security.py; runtime behavior is verified
    // interactively. Every probe chart sets `_sampleRebinDisabled = true` so no
    // worker ever spawns during the smoke.
    const dv1 = xy.renderStandalone(mk(), JSON.parse(JSON.stringify(spec)), bytes.buffer);
    const dv2 = xy.renderStandalone(mk(), JSON.parse(JSON.stringify(spec)), bytes.buffer);
    if (dv1.gpuTraces) for (const gg of dv1.gpuTraces) gg._densityNormAnim = null;
    if (dv2.gpuTraces) for (const gg of dv2.gpuTraces) gg._densityNormAnim = null;
    const pixdet = pixhash(dv1) === pixhash(dv2) ? 1 : 0;
    // Split first-paint layout (§29): the same payload delivered as one
    // ArrayBuffer per column must hash pixel-identical to the packed render,
    // and a spec/transport shape disagreement must throw, never mis-render.
    const splitSpec = JSON.parse(JSON.stringify(spec));
    splitSpec.buffer_layout = "split";
    splitSpec.columns = splitSpec.columns.map((c, i) => ({{ ...c, buf: i, byte_offset: 0 }}));
    const splitBufs = spec.columns.map((c) =>
      bytes.buffer.slice(c.byte_offset, c.byte_offset + c.len * 4));
    const sv1 = new xy.ChartView(mk(), splitSpec, splitBufs, null);
    sv1._sampleRebinDisabled = true;
    if (sv1.gpuTraces) for (const gg of sv1.gpuTraces) gg._densityNormAnim = null;
    const splitPix = pixhash(sv1) === pixhash(dv1) ? 1 : 0;
    const splitLoud =
      (throws(() => new xy.ChartView(mk(), splitSpec, bytes.buffer, null)) &&
       throws(() => new xy.ChartView(mk(), JSON.parse(JSON.stringify(spec)), splitBufs, null)))
        ? 1 : 0;
    const splitbuf = (splitPix && splitLoud) ? 1 : 0;
    // Streaming append (rust-engine §5): the affected trace rebuilds from the
    // fresh payload and the view follows the data — refit when at home, hold
    // when zoomed into history, slide when pinned to the live right edge.
    const mkStream=(n,yTop)=>{{
      const sbuf=new ArrayBuffer(n*8);
      const scols=[]; let so=0;
      const scol=(vals)=>{{new Float32Array(sbuf,so*4,vals.length).set(vals);
        scols.push({{byte_offset:so*4,len:vals.length,offset:0,scale:1,kind:"float"}});
        so+=vals.length; return scols.length-1;}};
      const xs=[],ys=[];for(let i=0;i<n;i++){{xs.push(i);ys.push(i%5);}}
      ys[n-1]=yTop;
      return {{spec:{{protocol:{PROTOCOL_VERSION},width:220,height:170,title:"",show_legend:false,show_modebar:false,
        x_axis:{{kind:"linear",label:"",range:[0,n-1]}},
        y_axis:{{kind:"linear",label:"",range:[0,yTop]}},
        traces:[{{id:0,kind:"scatter",name:"s",tier:"direct",n_points:n,n_marks:n,
          style:{{opacity:0.9}},x:scol(xs),y:scol(ys),
          color:{{mode:"constant",color:"#3b82f6"}},size:{{mode:"constant",size:6}}}}],
        columns:scols,backend:"none"}},buf:sbuf}};
    }};
    const sp0=mkStream(40,4), sp1=mkStream(64,9);
    const holderS=document.createElement("div");document.body.appendChild(holderS);
    const vS=xy.renderStandalone(holderS,sp0.spec,sp0.buf);
    const g0S=vS.gpuTraces[0], n0S=g0S.n;
    vS._onKernelMsg({{type:"append",affected:[0],spec:sp1.spec}},[sp1.buf]);
    const gS=vS.gpuTraces[0];
    const okGrow=(n0S===40&&gS.n===64&&gS!==g0S)?1:0;
    const okHome=(Math.abs(vS.view.x1-63)<1e-9&&Math.abs(vS.view.y1-9)<1e-9)?1:0;
    vS._drawNow();
    vS.view={{x0:5,x1:15,y0:0,y1:9}};
    const sp2=mkStream(80,9);
    vS._onKernelMsg({{type:"append",affected:[0],spec:sp2.spec}},[sp2.buf]);
    const okHoldS=(Math.abs(vS.view.x0-5)<1e-9&&Math.abs(vS.view.x1-15)<1e-9)?1:0;
    vS.view={{x0:vS.view0.x1-10,x1:vS.view0.x1,y0:0,y1:9}};
    const sp3=mkStream(100,9);
    vS._onKernelMsg({{type:"append",affected:[0],spec:sp3.spec}},[sp3.buf]);
    const okPin=(Math.abs(vS.view.x1-99)<1e-9&&Math.abs(vS.view.x1-vS.view.x0-10)<1e-9)?1:0;
    const okPayload=(vS._payload&&vS._payload.byteLength===sp3.buf.byteLength
      &&vS.spec.traces[0].n_points===100)?1:0;
    vS._drawNow();
    vS.destroy();holderS.remove();
    const stream=(okGrow&&okHome&&okHoldS&&okPin&&okPayload)?1:0;
    // Mark styling (spec/api/styling.md#styling-the-marks): gradient fills,
    // rounded corners, and stroke borders on BOTH rect-family programs
    // (histogram uses RECT, compact bar uses BAR), plus curve:"smooth"
    // monotone-cubic densification for line/area.
    const msBuf=new ArrayBuffer(128);
    const msCols=[]; let msOff=0;
    const mscol=(vals)=>{{new Float32Array(msBuf,msOff*4,vals.length).set(vals);
      msCols.push({{byte_offset:msOff*4,len:vals.length,offset:0,scale:1,kind:"float"}});
      msOff+=vals.length; return msCols.length-1;}};
    const msFill={{space:"mark",dir:"down",stops:[[0,"rgba(37,99,235,1)"],[1,"rgba(37,99,235,0)"]]}};
    const msSpec={{protocol:{PROTOCOL_VERSION},width:200,height:160,title:"",backend:"none",
      show_legend:false,show_modebar:false,
      x_axis:{{kind:"linear",label:"",range:[0,4]}},
      y_axis:{{kind:"linear",label:"",range:[0,8]}},
      traces:[
        {{id:0,kind:"histogram",name:"a",tier:"direct",n_points:1,n_marks:1,
          style:{{color:"#2563eb",opacity:1,role:"histogram",corner_radius:40,fill:msFill}},
          x0:mscol([0.5]),x1:mscol([1.5]),y0:mscol([0]),y1:mscol([6])}},
        {{id:1,kind:"histogram",name:"b",tier:"direct",n_points:1,n_marks:1,
          style:{{color:"#2563eb",opacity:1,role:"histogram",stroke:"#ff0000",stroke_width:6,
            corner_radius:[12,0]}},
          x0:mscol([2.5]),x1:mscol([3.5]),y0:mscol([0]),y1:mscol([6])}},
        {{id:2,kind:"bar",name:"c",tier:"direct",n_points:1,n_marks:1,
          style:{{color:"#2563eb",opacity:1,corner_radius:10,fill:msFill}},
          bar:{{pos:mscol([2]),value1:mscol([7.5]),width:0.6,orientation:"vertical"}}}},
        {{id:3,kind:"scatter",name:"styled",tier:"direct",n_points:2,n_marks:2,
          style:{{opacity:1}},x:mscol([0.2,3.8]),y:mscol([7.5,7.5]),
          color:{{mode:"constant",color:"#ff0000"}},size:{{mode:"constant",size:10}},
          channels:{{opacity:{{mode:"direct",components:1,dtype:"f32",buf:mscol([1,0.2]),n:2}}}}}}
      ],columns:msCols}};
    const holderMs=document.createElement("div");document.body.appendChild(holderMs);
    const vMs=xy.renderStandalone(holderMs,msSpec,msBuf);
    let msSimpleCalls=0;
    const msDrawSimple=vMs._drawSimplePoints;
    vMs._drawSimplePoints=function(...args){{msSimpleCalls++;return msDrawSimple.call(this,...args);}};
    vMs._drawNow();
    const vstyle=(msSimpleCalls===0 && !!vMs.gpuTraces[3].styleBuf)?1:0;
    const msRead=(dx,dy)=>{{
      const g3=vMs.gl,W3=g3.drawingBufferWidth,H3=g3.drawingBufferHeight;
      const x=Math.max(0,Math.min(W3-1,Math.round(dx/4*W3)));
      const y=Math.max(0,Math.min(H3-1,Math.round(dy/8*H3)));
      const px=new Uint8Array(4);g3.readPixels(x,y,1,1,g3.RGBA,g3.UNSIGNED_BYTE,px);
      return px;
    }};
    const aTip=msRead(1,5.2), aBase=msRead(1,0.5), aCorner=msRead(0.56,5.85), aCenter=msRead(1,3);
    const mgrad=(aTip[3]>110 && aBase[3]<40 && aCenter[3]>40)?1:0;
    const mcorner=(aCorner[3]<25 && aCenter[3]>40)?1:0;
    const bMid=msRead(3,3), bEdge=msRead(2.55,3);
    const mstroke=(bEdge[0]>140 && bEdge[2]<90 && bMid[2]>140 && bMid[0]<90)?1:0;
    // corner_radius:[tip,base] — rounded value-end, square base (rect B).
    const bTipC=msRead(2.55,5.92), bBaseC=msRead(2.55,0.2);
    const mtipbase=(bTipC[3]<25 && bBaseC[3]>100 && bBaseC[0]>140)?1:0;
    const cTip=msRead(2,7.0), cBase=msRead(2,0.4), cCorner=msRead(1.73,7.35);
    const bgrad=(cTip[3]>110 && cBase[3]<25)?1:0;
    const bcorner=(cCorner[3]<25)?1:0;
    // x/y axis baselines are DOM rules in the labels overlay (above the marks
    // canvas) so filled bars/areas sit under a crisp line, not covering it.
    let axisRuleN=0;
    for (const d of vMs.labels.children){{
      if (d.style.height==="1px" || d.style.width==="1px") axisRuleN++;
    }}
    const axisontop=(axisRuleN>=2)?1:0;
    vMs.destroy();holderMs.remove();
    // Opaque --chart-bg must NOT occlude chrome-canvas shapes: the marks
    // canvas always clears transparent and the plot background + grid paint
    // on the chrome canvas below it (regression guard for 423e020).
    const occBuf=new ArrayBuffer(32); const occCols=[]; let occOff=0;
    const occcol=(vals)=>{{new Float32Array(occBuf,occOff*4,vals.length).set(vals);
      occCols.push({{byte_offset:occOff*4,len:vals.length,offset:0,scale:1,kind:"float"}});
      occOff+=vals.length; return occCols.length-1;}};
    const occSpec={{protocol:{PROTOCOL_VERSION},width:200,height:160,title:"",backend:"none",
      show_legend:false,show_modebar:false,
      dom:{{style:{{"--chart-bg":"#eaeaf2","--chart-grid":"#ffffff"}}}},
      x_axis:{{kind:"linear",label:"",range:[0,4]}},
      y_axis:{{kind:"linear",label:"",range:[0,8]}},
      traces:[{{id:0,kind:"line",name:"l",tier:"direct",n_points:2,n_marks:2,
        style:{{color:"#2563eb",width:2,opacity:1}},x:occcol([0,4]),y:occcol([1,2])}}],
      columns:occCols}};
    const holderOcc=document.createElement("div");document.body.appendChild(holderOcc);
    const vOcc=xy.renderStandalone(holderOcc,occSpec,occBuf);
    vOcc._drawNow();
    // Marks canvas: transparent where no mark is drawn (upper plot region).
    const gO=vOcc.gl,WO=gO.drawingBufferWidth,HO=gO.drawingBufferHeight;
    const oPx=new Uint8Array(4);
    gO.readPixels(Math.round(WO/2),Math.round(HO*0.9),1,1,gO.RGBA,gO.UNSIGNED_BYTE,oPx);
    // Chrome canvas below it: plot background fill plus white grid lines.
    const cctx=vOcc.chrome.getContext("2d");
    const cim=cctx.getImageData(0,0,vOcc.chrome.width,vOcc.chrome.height).data;
    let occLav=0, occGrid=0;
    for(let i=0;i<cim.length;i+=4){{
      if(cim[i+3]>200){{
        if(cim[i]>248&&cim[i+1]>248&&cim[i+2]>248) occGrid++;
        else if(Math.abs(cim[i]-234)<6&&Math.abs(cim[i+1]-234)<6&&Math.abs(cim[i+2]-242)<6) occLav++;
      }}
    }}
    const bgocc=(oPx[3]<20 && occLav>500 && occGrid>20)?1:0;
    vOcc.destroy();holderOcc.remove();
    // curve:"smooth": the GPU polyline densifies ((n-1)*16+1 verts) while the
    // hover/_cpu columns keep the 5 source rows; area smooths its base too.
    const smBuf=new ArrayBuffer(128); const smCols=[]; let smOff=0;
    const smcol=(vals)=>{{new Float32Array(smBuf,smOff*4,vals.length).set(vals);
      smCols.push({{byte_offset:smOff*4,len:vals.length,offset:0,scale:1,kind:"float"}});
      smOff+=vals.length; return smCols.length-1;}};
    const smSpec={{protocol:{PROTOCOL_VERSION},width:200,height:160,title:"",backend:"none",
      show_legend:false,show_modebar:false,
      x_axis:{{kind:"linear",label:"",range:[0,4]}},
      y_axis:{{kind:"linear",label:"",range:[0,8]}},
      traces:[
        {{id:0,kind:"line",name:"l",tier:"direct",n_points:5,n_marks:5,
          style:{{color:"#2563eb",width:2,opacity:1,curve:"smooth"}},
          x:smcol([0,1,2,3,4]),y:smcol([1,6,2,7,3])}},
        {{id:1,kind:"area",name:"ar",tier:"direct",n_points:5,n_marks:5,
          style:{{color:"#2563eb",opacity:0.4,line_width:1,line_opacity:1,curve:"smooth",fill:msFill}},
          x:smcol([0,1,2,3,4]),y:smcol([2,5,3,6,2]),base:smcol([0,0,0,0,0])}}
      ],columns:smCols}};
    const holderSm=document.createElement("div");document.body.appendChild(holderSm);
    const vSm=xy.renderStandalone(holderSm,smSpec,smBuf);
    vSm._drawNow();
    const gLn=vSm.gpuTraces[0], gAr=vSm.gpuTraces[1];
    const msmooth=(gLn.n===65 && gLn._cpu.x.length===5 && gAr.n===65 && gAr._cpu.base.length===5)?1:0;
    vSm.destroy();holderSm.remove();
    const base=`XY_OK lit=${{lit}} total=${{w*h}} labels=${{labels}} pick=${{hits}} row=${{hasXY}} selAll=${{selAll}} selSome=${{selSome}} active=${{active}} btns=${{btns}} modebarHidden=${{modebarHidden}} modebarHover=${{modebarHover}} modebarNoCollapse=${{modebarNoCollapse}} modebarMenu=${{modebarMenu}} modebarDrag=${{modebarDrag}} modebarSelect=${{modebarSelect}} lassoEdit=${{lassoEdit}} modebarExport=${{modebarExport}} zin=${{zin}} smooth=${{smooth}} labelThrottle=${{labelThrottle}} hoverSkip=${{hoverSkip}} zanch=${{zanch}} retarget=${{retarget}} nosnap=${{nosnap}} prefetch=${{prefetch}} maxwait=${{maxwait}} box=${{boxOk}} xonly=${{xonly}} zmode=${{zmode}} densityLit=${{densityLit}} drill=${{drilled}} pending=${{pending}} dblend=${{dblend}} dseq=${{dseq}} hov=${{hov}} sstale=${{sstale}} sfresh=${{sfresh}} srestore=${{srestore}} plut=${{plut}} reg=${{reg}} refresh=${{refresh}} dpick=${{dpick}} hold=${{hold}} zoomout=${{zoomout}} broad=${{broadfallback}} dying=${{dying}} dback=${{dback}} dnorm=${{dnorm}} dnormDone=${{dnormDone}} stale=${{stale}} thrash=${{thrash}} qwire=${{qwire}} stream=${{stream}} tj=${{Math.round(maxJump*100)}} td=${{Math.round(reviveDip*100)}} malformed=${{malformed}} pixdet=${{pixdet}} splitbuf=${{splitbuf}} barBase=${{barBase}} histBase=${{histBase}} edgepad=${{edgepad}} mgrad=${{mgrad}} axisontop=${{axisontop}} mtipbase=${{mtipbase}} mcorner=${{mcorner}} mstroke=${{mstroke}} bgrad=${{bgrad}} bcorner=${{bcorner}} msmooth=${{msmooth}} bgocc=${{bgocc}}`;
    const baseWithStyle=`${{base}} vstyle=${{vstyle}}`;
    // Responsive: 100%-by-100% chart in a 400x300 container tracks its parent;
    // growing the container must fire the ResizeObserver and re-render bigger.
    const spec2=JSON.parse(JSON.stringify(spec));
    spec2.width="100%";
    spec2.height="100%";
    const holder=document.createElement("div");
    holder.style.width="400px";
    holder.style.height="300px";
    document.body.appendChild(holder);
    const v2=xy.renderStandalone(holder,spec2,bytes.buffer);
    v2._sampleRebinDisabled = true;
    const fluid0=(v2.fluid===true && v2.fluidH===true && v2.size.w===400 && v2.size.h===300
      && v2.root.style.width==="100%" && v2.root.style.height==="100%")?1:0;
    holder.style.width="640px";
    holder.style.height="360px";
    setTimeout(async()=>{{try{{
      // ResizeObserver now coalesces its work into requestAnimationFrame. A
      // fixed delay can run before that frame under --virtual-time-budget, so
      // poll the public result instead of assuming a particular task order.
      const resizeDeadline=performance.now()+1000;
      while((v2.size.w!==640 || v2.size.h!==360) && performance.now()<resizeDeadline){{
        await new Promise((resolve)=>setTimeout(resolve,20));
      }}
      const grew=(v2.size.w===640 && v2.size.h===360 && v2.canvas.width===v2.plot.w*v2.dpr
        && v2.canvas.height===v2.plot.h*v2.dpr && v2.chrome.width===640*v2.dpr
        && v2.chrome.height===360*v2.dpr)?1:0;
      v2._pickAt(4,4); // exercises _renderPick -> deferred pick-FBO realloc
      const pick2=(v2._pickW===v2.canvas.width && v2._pickH===v2.canvas.height)?1:0;
      const root2=v2.root;
      v2.destroy();
      const realRaf2=window.requestAnimationFrame;
      let rafAfterDestroy=0;
      window.requestAnimationFrame=(cb)=>{{rafAfterDestroy++; return 999;}};
      v2.draw();
      window.requestAnimationFrame=realRaf2;
      v2._onKernelMsg({{type:"selection",traces:[],total:0}},[]);
      const destroyed=(v2._destroyed===true && v2.gl===null && v2.gpuTraces.length===0
        && v2._listeners.length===0 && !document.body.contains(root2) && rafAfterDestroy===0)?1:0;
      const holder3=document.createElement("div");
      document.body.appendChild(holder3);
      let onHandler=null, offCalled=0;
      const model={{
        get(k){{ return k==="spec" ? spec : bytes.buffer; }},
        send(m){{}},
        on(ev,h){{ if(ev==="msg:custom") onHandler=h; }},
        off(ev,h){{ if(ev==="msg:custom" && h===onHandler) offCalled++; }},
      }};
      const cleanup=xy.render({{model,el:holder3}});
      cleanup();
      const unsub=(offCalled===1 && holder3.querySelector(".xy")===null)?1:0;
      holder3.remove();
      (async()=>{{try{{
        // R4: force repeated loss/restore cycles. Each cycle queues draw,
        // animation, and re-bin work first so the loss handler must quiesce
        // every deferred GPU path and invalidate pre-loss replies.
        const holder4=document.createElement("div");
        document.body.appendChild(holder4);
        const v4=xy.renderStandalone(holder4,spec,bytes.buffer);
        // Compare settled frames, not the constructor's intentionally
        // transitional first density/sample handoff.
        await new Promise((resolve)=>setTimeout(resolve,180));
        for(const g of v4.gpuTraces) g._densityNormAnim=null;
        v4._drawNow();
        const ctxHashBefore=pixhash(v4);
        let rootLost=0,rootRestored=0;
        v4.root.addEventListener("xy:context_lost",()=>rootLost++);
        v4.root.addEventListener("xy:context_restored",()=>rootRestored++);
        const waitFor=(predicate,label)=>new Promise((resolve,reject)=>{{
          const deadline=performance.now()+1500;
          const poll=()=>{{
            if(predicate()){{resolve();return;}}
            if(performance.now()>=deadline){{reject(new Error(`timeout waiting for ${{label}}`));return;}}
            setTimeout(poll,20);
          }};
          poll();
        }});
        const litcount=(view)=>{{
          const gl=view.gl,w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
          const px=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
          let n=0;for(let i=0;i<px.length;i+=4)if(px[i]||px[i+1]||px[i+2]||px[i+3])n++;
          return n;
        }};
        let ctxcycles=0,ctxquiet=1,ctxpixels=1;
        const ctxhashes=[ctxHashBefore];
        for(let cycle=0;cycle<3;cycle++){{
          const ext=v4.gl.getExtension("WEBGL_lose_context");
          if(!ext){{ctxquiet=0;break;}}
          v4.draw();
          v4._pendingWheelZoom={{factor:0.99,fx:0.5,fy:0.5}};
          v4._wheelZoomRaf=requestAnimationFrame(()=>{{}});
          v4._viewAnim={{target:{{...v4.view}},last:performance.now(),tau:36}};
          v4._animRaf=requestAnimationFrame(()=>{{}});
          v4._scheduleViewRequest(v4.view,{{delay:10000}});
          const seqBeforeLoss=v4.seq;
          ext.loseContext();
          await waitFor(()=>v4._glLost===true,`loss ${{cycle+1}}`);
          v4.draw();
          if(v4._raf!==null || v4._wheelZoomRaf!==null || v4._animRaf!==null
              || v4._viewTimer!==null || v4._rebinTimer!==null
              || v4.seq<=seqBeforeLoss || v4.root.dataset.xyContextState!=="lost") ctxquiet=0;
          ext.restoreContext();
          await waitFor(()=>v4._glLost===false && v4.root.dataset.xyContextState==="ready",
            `restore ${{cycle+1}}`);
          for(const g of v4.gpuTraces) g._densityNormAnim=null;
          v4._drawNow();
          const restoredHash=pixhash(v4);
          ctxhashes.push(restoredHash);
          if(restoredHash!==ctxHashBefore) ctxpixels=0;
          ctxcycles++;
        }}
        const savedView={{...v4.view}};
        const span0=savedView.x1-savedView.x0;
        v4._zoomAt(0.9,0.5,0.5,false);
        v4._drawNow();
        const ctxpost=((v4.view.x1-v4.view.x0)<span0 && litcount(v4)>0)?1:0;
        v4._setView(savedView,{{animate:false,request:false}});
        v4._drawNow();
        const ctxloss=(ctxcycles===3 && ctxquiet===1 && ctxpixels===1 && ctxpost===1
          && rootLost===3 && rootRestored===3 && v4._contextLossCount===3
          && v4._contextRestoreCount===3 && pixhash(v4)===ctxHashBefore)?1:0;
        v4.destroy(); holder4.remove();
        // R7: a pure devicePixelRatio change (browser zoom) must re-derive
        // backing stores even though the CSS size never changed.
        const holder5=document.createElement("div");
        document.body.appendChild(holder5);
        const v5=xy.renderStandalone(holder5,spec,bytes.buffer);
        const dpr0=v5.dpr;
        Object.defineProperty(window,"devicePixelRatio",{{value:dpr0*2,configurable:true}});
        v5._onDprChange();
        const dprw=(v5.dpr===dpr0*2 && v5.canvas.width===v5.plot.w*v5.dpr
          && v5.chrome.width===v5.size.w*v5.dpr
          && String(v5._dprMq.media).indexOf(`${{dpr0*2}}dppx`)>=0)?1:0;
        Object.defineProperty(window,"devicePixelRatio",{{value:dpr0,configurable:true}});
        v5.destroy(); holder5.remove();
        document.title=`${{baseWithStyle}} fluid=${{fluid0}} grew=${{grew}} pick2=${{pick2}} destroyed=${{destroyed}} unsub=${{unsub}} ctxloss=${{ctxloss}} ctxcycles=${{ctxcycles}} ctxquiet=${{ctxquiet}} ctxpixels=${{ctxpixels}} ctxhashes=${{ctxhashes.join(",")}} ctxpost=${{ctxpost}} ctxevents=${{rootLost}}/${{rootRestored}} ctxcounts=${{v4._contextLossCount}}/${{v4._contextRestoreCount}} dprw=${{dprw}}`;
      }}catch(e){{document.title="XY_ERROR "+(e.stack||e.message)}}}})();
    }}catch(e){{document.title="XY_ERROR "+(e.stack||e.message)}}}},250);
  }}catch(e){{document.title="XY_ERROR "+(e.stack||e.message)}}}},200);
}}catch(e){{document.title="XY_ERROR "+(e.stack||e.message)}}
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
    if not title.startswith("XY_OK"):
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
    modebar_hidden = int(re.search(r"modebarHidden=(\d+)", title).group(1))
    modebar_hover = int(re.search(r"modebarHover=(\d+)", title).group(1))
    modebar_no_collapse = int(re.search(r"modebarNoCollapse=(\d+)", title).group(1))
    modebar_menu = int(re.search(r"modebarMenu=(\d+)", title).group(1))
    modebar_drag = int(re.search(r"modebarDrag=(\d+)", title).group(1))
    modebar_select = int(re.search(r"modebarSelect=(\d+)", title).group(1))
    lasso_edit = int(re.search(r"lassoEdit=(\d+)", title).group(1))
    modebar_export = int(re.search(r"modebarExport=(\d+)", title).group(1))
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
    xonly = int(re.search(r"xonly=(\d+)", title).group(1))
    zmode = int(re.search(r"zmode=(\d+)", title).group(1))
    fluid = int(re.search(r"fluid=(\d+)", title).group(1))
    grew = int(re.search(r"grew=(\d+)", title).group(1))
    pick2 = int(re.search(r"pick2=(\d+)", title).group(1))
    destroyed = int(re.search(r"destroyed=(\d+)", title).group(1))
    unsub = int(re.search(r"unsub=(\d+)", title).group(1))
    drill = int(re.search(r"drill=(\d+)", title).group(1))
    pending = int(re.search(r"pending=(\d+)", title).group(1))
    dblend = int(re.search(r"dblend=(\d+)", title).group(1))
    dseq = int(re.search(r"dseq=(\d+)", title).group(1))
    hov = int(re.search(r"hov=(\d+)", title).group(1))
    sstale = int(re.search(r"sstale=(\d+)", title).group(1))
    srestore = int(re.search(r"srestore=(\d+)", title).group(1))
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
    thrash = int(re.search(r"thrash=(\d+)", title).group(1))
    qwire = int(re.search(r"qwire=(\d+)", title).group(1))
    stream = int(re.search(r"stream=(\d+)", title).group(1))
    malformed = int(re.search(r"malformed=(\d+)", title).group(1))
    pixdet = int(re.search(r"pixdet=(\d+)", title).group(1))
    splitbuf = int(re.search(r"splitbuf=(\d+)", title).group(1))
    ctxloss = int(re.search(r"ctxloss=(\d+)", title).group(1))
    ctxcycles = int(re.search(r"ctxcycles=(\d+)", title).group(1))
    ctxquiet = int(re.search(r"ctxquiet=(\d+)", title).group(1))
    ctxpost = int(re.search(r"ctxpost=(\d+)", title).group(1))
    dprw = int(re.search(r"dprw=(\d+)", title).group(1))
    bar_base = int(re.search(r"barBase=(\d+)", title).group(1))
    hist_base = int(re.search(r"histBase=(\d+)", title).group(1))
    edgepad = int(re.search(r"edgepad=(\d+)", title).group(1))
    mark_grad = int(re.search(r"mgrad=(\d+)", title).group(1))
    axis_on_top = int(re.search(r"axisontop=(\d+)", title).group(1))
    mark_tipbase = int(re.search(r"mtipbase=(\d+)", title).group(1))
    mark_corner = int(re.search(r"mcorner=(\d+)", title).group(1))
    mark_stroke = int(re.search(r"mstroke=(\d+)", title).group(1))
    bar_grad = int(re.search(r"bgrad=(\d+)", title).group(1))
    bar_corner = int(re.search(r"bcorner=(\d+)", title).group(1))
    vector_style = int(re.search(r"vstyle=(\d+)", title).group(1))
    mark_smooth = int(re.search(r"msmooth=(\d+)", title).group(1))
    bg_occlusion = int(re.search(r"bgocc=(\d+)", title).group(1))
    frac = lit / max(total, 1)
    print(
        f"lit fraction: {frac:.3%}, DOM chrome nodes: {labels}, pick hits: {pick}, "
        f"row-decoded: {rowok}, select all/sub: {sel_all}/{sel_some}, mask active: {active}, "
        f"modebar btns: {btns}, hidden/hover/no-collapse/menu/drag/select/lasso-edit/export: "
        f"{modebar_hidden}/{modebar_hover}/{modebar_no_collapse}/{modebar_menu}/"
        f"{modebar_drag}/{modebar_select}/{lasso_edit}/{modebar_export}, "
        f"zoom-in: {zin}, box-zoom: {box}, x-only zoom: {xonly}, zoom-mode: {zmode}, "
        f"fluid: {fluid}, resize grew: {grew}, pick realloc: {pick2}, "
        f"destroyed: {destroyed}, unsub: {unsub}"
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
    if btns < 15:
        raise SystemExit(f"modebar missing buttons: {btns}")
    if modebar_hidden != 1 or modebar_hover != 1:
        raise SystemExit("modebar did not hide at rest and show on chart hover")
    if modebar_no_collapse != 1:
        raise SystemExit("modebar still exposes collapsible toolbar behavior")
    if modebar_menu != 1:
        raise SystemExit("modebar zoom dropdown did not open and close")
    if modebar_drag != 1:
        raise SystemExit("modebar drag handle did not move the toolbar")
    if modebar_select != 1:
        raise SystemExit("modebar select button did not activate selection mode")
    if lasso_edit != 1:
        raise SystemExit("completed lasso did not expose draggable editable points")
    if modebar_export != 1:
        raise SystemExit("modebar export menu did not produce PNG/SVG/CSV actions")
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
    if xonly != 1:
        raise SystemExit("x-only zoom changed the y range or failed to change x")
    if zmode != 1:
        raise SystemExit("drag-mode toggle did not switch to box-zoom")
    if fluid != 1:
        raise SystemExit('width:"100%" chart did not track its 400px container')
    if grew != 1:
        raise SystemExit("ResizeObserver resize did not re-render at the new width")
    if pick2 != 1:
        raise SystemExit("pick FBO was not reallocated to the resized canvas")
    if destroyed != 1:
        raise SystemExit("destroy() did not cleanly tear down DOM/listeners/GL state")
    if unsub != 1:
        raise SystemExit("widget render cleanup did not unsubscribe kernel messages")
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
    if srestore != 1:
        raise SystemExit(
            "retained brush did not restore a provisional mask across a drill swap (§34)"
        )
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
    if malformed != 1:
        raise SystemExit("hostile-spec suite failed (renderer must fail loudly, never hang)")
    if dprw != 1:
        raise SystemExit("devicePixelRatio change did not re-derive backing stores")
    if ctxloss != 1:
        raise SystemExit("GL context recovery did not quiesce and rebuild pixel-identically")
    if ctxcycles != 3:
        raise SystemExit(f"GL context recovery completed only {ctxcycles}/3 forced cycles")
    if ctxquiet != 1:
        raise SystemExit("GL context loss left deferred GPU work or stale replies active")
    if ctxpost != 1:
        raise SystemExit("chart was not interactive and nonblank after context restoration")
    if pixdet != 1:
        raise SystemExit("pixel determinism failed (render path must be RNG/time-free)")
    if splitbuf != 1:
        raise SystemExit(
            "split buffer layout failed (per-column first paint must render "
            "pixel-identical to packed and reject spec/transport mismatches)"
        )
    if qwire != 1:
        raise SystemExit("log-u8 density bytes were not retained compactly")
    if stream != 1:
        raise SystemExit(
            "streaming append failed (trace rebuild or follow policy: refit/hold/slide)"
        )
    if thrash != 1:
        raise SystemExit(
            "drill thrash: alpha discontinuity under rapid zoom in/out (see tj/td in title)"
        )
    if stale != 1:
        raise SystemExit("stale density update resurrected a drilled point subset")
    if bar_base != 1:
        raise SystemExit("zero-pinned bars left a lit-pixel gap above the x-axis")
    if hist_base != 1:
        raise SystemExit("zero-pinned histogram left a lit-pixel gap above the x-axis")
    if edgepad != 1:
        raise SystemExit("baseline edge pad is not DPR-aware")
    if axis_on_top != 1:
        raise SystemExit("axis baselines are not DOM rules in the overlay above the marks")
    if mark_grad != 1:
        raise SystemExit("mark-space gradient fill did not fade tip->base (rect program)")
    if mark_tipbase != 1:
        raise SystemExit("corner_radius=(tip, base) did not round only the value end")
    if mark_corner != 1:
        raise SystemExit("corner_radius left the rect corner pixel lit")
    if mark_stroke != 1:
        raise SystemExit("stroke border did not paint the rect edge in the stroke color")
    if bar_grad != 1:
        raise SystemExit("mark-space gradient fill did not fade tip->base (bar program)")
    if bar_corner != 1:
        raise SystemExit("corner_radius left the bar corner pixel lit")
    if vector_style != 1:
        raise SystemExit("vector-styled scatter incorrectly entered the simple-point shader")
    if mark_smooth != 1:
        raise SystemExit("curve:'smooth' did not densify line/area GPU geometry")
    if bg_occlusion != 1:
        raise SystemExit(
            "opaque --chart-bg occluded chrome shapes: the marks canvas must clear "
            "transparent and the plot background+grid must paint on the chrome canvas"
        )
    print(
        "render smoke OK (no numpy): line + colored/sized scatter + density + "
        "area + bars + heatmap + picking + box-select + modebar/box-zoom + "
        "responsive resize + LOD drill-in + mark styling (gradient/radius/"
        "stroke/smooth) + chrome-under-bg stacking"
    )


if __name__ == "__main__":
    main()
