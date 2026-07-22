#!/usr/bin/env python3
"""Measure density exposure frames, upload count, and compact cache memory.

This is a real-Chrome benchmark.  It compares the shipped uniform-only draw
path with a JavaScript simulation of the removed CPU f32->log-u8 requantization
loop.  The comparison isolates browser work; neither arm includes payload
construction, transport, or density binning.
"""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
from pathlib import Path

import numpy as np

import xy
from _browser import chromium_gl_flags, find_chromium  # ty: ignore[unresolved-import]
from _cdp import Browser  # ty: ignore[unresolved-import]

ROOT = Path(__file__).resolve().parent.parent


def _payload(points: int) -> tuple[dict, bytes]:
    rng = np.random.default_rng(166)
    left = points // 2
    x = np.r_[rng.normal(-1.0, 0.45, left), rng.normal(1.2, 0.72, points - left)]
    y = np.r_[rng.normal(0.75, 0.5, left), rng.normal(-0.65, 0.38, points - left)]
    return (
        xy.scatter_chart(
            xy.scatter(x=x, y=y, density=True),
            width=900,
            height=540,
        )
        .figure()
        .build_payload()
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def measure(points: int, frames: int, chrome: str) -> dict[str, object]:
    bundle = (ROOT / "python/xy/static/standalone.js").read_text(encoding="utf-8")
    spec, blob = _payload(points)
    payload = base64.b64encode(blob).decode("ascii")
    page = f"""<!doctype html><html><body><div id="chart"></div>
<script>{bundle}</script><script>
const spec={json.dumps(spec, separators=(",", ":"))};
const buf=Uint8Array.from(atob("{payload}"),c=>c.charCodeAt(0));
window.xyDensityBench=xy.renderStandalone(document.getElementById("chart"),spec,buf);
</script></body></html>"""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "density-normalization-benchmark.html"
        path.write_text(page, encoding="utf-8")
        gl = "hardware" if not chromium_gl_flags() else "software"
        with Browser(chrome, gl=gl, window=(1100, 700)) as browser:
            tab = browser.new_page()
            try:
                tab.navigate(path.as_uri())
                raw = tab.eval(
                    f"""(async () => {{
                      const view=window.xyDensityBench;
                      const g=view.gpuTraces.find(trace=>trace.tier==="density");
                      const homeDensity=g.density;
                      const home=view.view0;
                      const cx=(home.x0+home.x1)/2, cy=(home.y0+home.y1)/2;
                      const sx=home.x1-home.x0, sy=home.y1-home.y0;
                      const rebinSeq=++view.seq;
                      const realUploadDensityGrid=view._uploadDensityGrid;
                      let uploadedSource=null;
                      view._uploadDensityGrid=(bytes,w,h)=>{{
                        uploadedSource=bytes.slice();
                        return realUploadDensityGrid.call(view,bytes,w,h);
                      }};
                      view._requestSampleRebin(g,{{
                        x0:cx-sx*0.25,x1:cx+sx*0.25,
                        y0:cy-sy*0.25,y1:cy+sy*0.25,
                      }},rebinSeq);
                      await new Promise((resolve,reject)=>{{
                        const deadline=performance.now()+5000;
                        const poll=()=>{{
                          if(g._sampleRebinned&&g.density!==homeDensity) resolve();
                          else if(performance.now()>=deadline) reject(new Error("worker rebin timeout"));
                          else setTimeout(poll,10);
                        }};
                        poll();
                      }});
                      view._uploadDensityGrid=realUploadDensityGrid;
                      const density=g.density;
                      const workerCompact=uploadedSource instanceof Uint8Array
                        && !("encoded" in density) && !("grid" in density)
                        && uploadedSource.byteLength===density.w*density.h;
                      g.sampleOverlay=null;
                      g.drill=null;
                      g.prevDensity=null;
                      g._densitySwitchPrev=null;
                      g._densitySwitchFadeStart=null;
                      g._shownDensity=density;
                      g._densityNormAnim=null;
                      if(view._raf) cancelAnimationFrame(view._raf);
                      view._raf=null;
                      view._drawNow(); view.gl.finish();

                      const encoded=uploadedSource;
                      const sourceMax=density.max;
                      const sourceLog=Math.log1p(sourceMax);
                      const startNorm=Math.expm1(sourceLog/0.45);
                      const duration=420;
                      const frameCount={frames};
                      const norms=new Float64Array(frameCount);
                      for(let frame=0;frame<frameCount;frame++){{
                        const t=frameCount===1?1:frame/(frameCount-1);
                        const smooth=t*t*(3-2*t);
                        norms[frame]=startNorm+(sourceMax-startNorm)*smooth;
                      }}

                      // Removed path: decoded f32 counts retained in the cache,
                      // then a grid-sized allocation + log loop every frame.
                      const counts=new Float32Array(encoded.length);
                      for(let i=0;i<encoded.length;i++){{
                        if(encoded[i]) counts[i]=Math.expm1(encoded[i]/255*sourceLog);
                      }}
                      const legacyOnce=()=>{{
                        const scratch=new Uint8Array(counts.length);
                        const denom=Math.log1p(norms[0]);
                        for(let i=0;i<counts.length;i++){{
                          const count=counts[i];
                          if(count>0&&Number.isFinite(count)){{
                            scratch[i]=Math.max(1,Math.min(255,
                              Math.round(255*Math.log1p(count)/denom)));
                          }}
                        }}
                        return scratch;
                      }};
                      for(let warm=0;warm<3;warm++) legacyOnce();
                      let checksum=0;
                      const legacyStarted=performance.now();
                      for(let frame=0;frame<frameCount;frame++){{
                        const scratch=new Uint8Array(counts.length);
                        const denom=Math.log1p(norms[frame]);
                        for(let i=0;i<counts.length;i++){{
                          const count=counts[i];
                          if(count>0&&Number.isFinite(count)){{
                            scratch[i]=Math.max(1,Math.min(255,
                              Math.round(255*Math.log1p(count)/denom)));
                          }}
                        }}
                        checksum=(checksum+scratch[(frame*997)%scratch.length])>>>0;
                      }}
                      const legacyMs=performance.now()-legacyStarted;

                      // Warm varying normalization values as well as the
                      // settled scale=1 constructor frame. This keeps lazy
                      // shader/driver setup outside the measured frame set.
                      for(let warm=0;warm<8;warm++){{
                        density.normMax=norms[(warm*7919)%frameCount];
                        view._drawNow(); view.gl.finish();
                      }}
                      const gl=view.gl;
                      const realTexImage2D=gl.texImage2D.bind(gl);
                      let texImageCalls=0;
                      gl.texImage2D=(...args)=>{{texImageCalls++;return realTexImage2D(...args);}};
                      const realNow=view._now;
                      const realDraw=view.draw;
                      let clock=0;
                      view._now=()=>clock;
                      view.draw=()=>{{}};
                      density.normMax=startNorm;
                      g.densityNormMax=startNorm;
                      g._densityNormAnim={{
                        start:startNorm,target:sourceMax,startedAt:0,duration,
                      }};
                      const frameMs=[];
                      for(let frame=0;frame<frameCount;frame++){{
                        clock=frameCount===1?duration:duration*frame/(frameCount-1);
                        const started=performance.now();
                        view._drawNow(); gl.finish();
                        frameMs.push(performance.now()-started);
                      }}
                      view._now=realNow;
                      view.draw=realDraw;
                      gl.texImage2D=realTexImage2D;
                      return {{
                        grid_width:density.w,
                        grid_height:density.h,
                        grid_cells:density.w*density.h,
                        frames:frameCount,
                        frame_ms:frameMs,
                        tex_image_2d_calls:texImageCalls,
                        cpu_cache_bytes:g.densityCacheBytes,
                        former_f32_cache_bytes:g.densityCache.reduce(
                          (total,item)=>total+item.w*item.h*4,0),
                        legacy_requantize_total_ms:legacyMs,
                        legacy_requantize_per_frame_ms:legacyMs/frameCount,
                        legacy_checksum:checksum,
                        animation_completed:g._densityNormAnim===null,
                        worker_result_compact:workerCompact,
                        worker_result_bytes:encoded.byteLength,
                      }};
                    }})()""",
                    timeout_s=120,
                )
            finally:
                tab.close()
    frame_ms = [float(value) for value in raw.pop("frame_ms")]
    return {
        "points": points,
        **raw,
        "frame_median_ms": _percentile(frame_ms, 0.5),
        "frame_p95_ms": _percentile(frame_ms, 0.95),
        "frame_max_ms": max(frame_ms, default=None),
        "gl_backend": "hardware" if not chromium_gl_flags() else "swiftshader",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=500_000)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--chromium")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.points <= 0 or args.frames <= 0:
        raise SystemExit("--points and --frames must be positive")
    chrome = find_chromium(args.chromium)
    if not chrome:
        raise SystemExit("no Chromium executable found")
    report = {
        "benchmark": "density-normalization",
        "result": measure(args.points, args.frames, chrome),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
