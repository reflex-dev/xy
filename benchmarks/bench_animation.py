#!/usr/bin/env python3
"""Measure keyed-update build cost, frame pacing, and bounded browser state.

This is a real-Chrome benchmark, not a CodSpeed simulation row. Run on one GL
backend at a time and keep hardware and SwiftShader results separate.
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


def _case(n: int) -> tuple[tuple[dict, bytes], tuple[dict, bytes]]:
    keys = np.arange(n, dtype=np.int64)
    x0 = np.linspace(0.0, 100.0, n, dtype=np.float64)
    y0 = np.sin(x0 * 0.12)
    order = np.roll(np.arange(n), n // 7)
    x1 = x0[order] + 0.25 * np.cos(x0[order] * 0.2)
    y1 = y0[order] + 0.3 * np.sin(x0[order] * 0.07)

    def payload(x, y, row_keys):
        chart = xy.scatter_chart(
            xy.scatter(x=x, y=y, key=row_keys, size=3),
            xy.animation(enabled=True, match="key", duration=350, easing="linear"),
            width=800,
            height=420,
        )
        return chart.figure().build_payload()

    first = payload(x0, y0, keys)
    second = payload(x1, y1, keys[order])
    first[0]["animation_capture_progress"] = 1.0
    return first, second


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))]


def measure(n: int, chrome: str) -> dict[str, object]:
    bundle = (ROOT / "python/xy/static/standalone.js").read_text(encoding="utf-8")
    first, second = _case(n)
    payloads = [
        {"spec": spec, "blob": base64.b64encode(blob).decode("ascii")}
        for spec, blob in (first, second)
    ]
    page = f"""<!doctype html><html><body><div id="chart"></div><pre id="result">pending</pre>
<script>{bundle}</script><script>
const payloads={json.dumps(payloads, separators=(",", ":"))};
const unpack=(item)=>Uint8Array.from(atob(item.blob),c=>c.charCodeAt(0));
const host=document.getElementById("chart");
const view=xy.renderStandalone(host,payloads[0].spec,unpack(payloads[0]));
const frames=[]; let prior=null; let sampling=true;
let buildMs=0; let bounded=false;
function frame(now){{if(prior!==null)frames.push(now-prior);prior=now;if(sampling)requestAnimationFrame(frame);}}
requestAnimationFrame(frame);
const keepAlive=setInterval(()=>{{}},50);
const heapBefore=performance.memory ? performance.memory.usedJSHeapSize : null;
host.addEventListener("xy:animation_end",(event)=>{{
  if(event.detail.phase!=="update")return;
  sampling=false;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{{
    const heapAfter=performance.memory ? performance.memory.usedJSHeapSize : null;
    const result={{
      update_build_ms: buildMs,
      frame_ms: frames,
      js_heap_before: heapBefore,
      js_heap_after: heapAfter,
      bounded_previous_next: bounded,
      current_traces: view.gpuTraces.length,
      retained_old_traces: view._transitionOldTraces ? view._transitionOldTraces.length : 0,
    }};
    clearInterval(keepAlive);
    document.getElementById("result").textContent=JSON.stringify(result);
  }}));
}},{{once:true}});
setTimeout(()=>{{
  const started=performance.now();
  view.updatePayload(payloads[1].spec,unpack(payloads[1]));
  buildMs=performance.now()-started;
  bounded=view.gpuTraces.length===1&&view._transitionOldTraces&&view._transitionOldTraces.length===1;
}},50);
</script></body></html>"""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "animation-benchmark.html"
        path.write_text(page, encoding="utf-8")
        gl = "hardware" if not chromium_gl_flags() else "software"
        with Browser(chrome, gl=gl, window=(1000, 650)) as browser:
            tab = browser.new_page()
            try:
                tab.navigate(path.as_uri())
                raw = tab.eval(
                    """new Promise((resolve, reject) => {
                      const deadline = performance.now() + 10000;
                      const poll = () => {
                        const text = document.getElementById("result")?.textContent;
                        if (text && text !== "pending") resolve(JSON.parse(text));
                        else if (performance.now() > deadline) reject(new Error("animation timeout"));
                        else setTimeout(poll, 25);
                      };
                      poll();
                    })""",
                    timeout_s=30,
                )
            finally:
                tab.close()
    frames = [float(value) for value in raw.pop("frame_ms")]
    before, after = raw.pop("js_heap_before"), raw.pop("js_heap_after")
    return {
        "n": n,
        **raw,
        "frames": len(frames),
        "frame_median_ms": _percentile(frames, 0.5),
        "frame_p95_ms": _percentile(frames, 0.95),
        "frame_max_ms": max(frames, default=None),
        "js_heap_delta_bytes": None if before is None or after is None else after - before,
        "packed_previous_next_bytes": len(first[1]) + len(second[1]),
        "position_scratch_bytes": n * 2 * 4,
        "gl_backend": "hardware" if not chromium_gl_flags() else "swiftshader",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="10000,100000")
    parser.add_argument("--chromium")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    chrome = find_chromium(args.chromium)
    if not chrome:
        raise SystemExit("no Chromium executable found")
    report = {
        "benchmark": "animation",
        "results": [measure(int(value), chrome) for value in args.sizes.split(",")],
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
