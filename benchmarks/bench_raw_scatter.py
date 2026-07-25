"""Raw-point scatter benchmark with per-stage timings (persistent browser).

The library-vs-library "raw points" comparison counts every stage from a warm
Python API call to validated pixels — but a one-shot Chromium launch buries the
interesting stages under ~2 s of browser startup, and a single end-to-end
number cannot say whether the next ceiling is transport, decode, GPU upload,
or draw. This harness answers that:

- ONE Chromium (``_cdp.Browser``) is reused across all sizes/reps; startup is
  reported once, outside the measurements.
- Every N runs in DIRECT mode (``density=False`` — §28's loud opt-out), so all
  N points take the raw WebGL path; no density/decimation substitution.
- Stages are measured separately: Python payload build, base64 chunking, HTML
  compose+write, browser navigate+parse, base64 decode, scene build + buffer
  upload, synchronized first draw (``gl.finish``; GPU-timer draw time when
  ``EXT_disjoint_timer_query_webgl2`` exists), pixel readback.
- Validation is raw-mode strict: the uploaded column length must equal N and
  the center readback must contain non-blank pixels.

Usage:
  uv run python benchmarks/bench_raw_scatter.py --sizes 1e6,10e6,25e6
  uv run python benchmarks/bench_raw_scatter.py --gl hardware --sizes 25e6,50e6
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cdp import Browser, default_chromium  # noqa: E402

VIEW_W, VIEW_H = 900, 420

_PROBE = """
window.__probe = (async () => {
  const el = document.getElementById("chart");
  const t0 = performance.now();
  const buf = xyDecodeB64(__xyChunks, __XY_TOTAL);
  __xyChunks.length = 0;
  const t1 = performance.now();
  const view = xy.renderStandalone(el, __XY_SPEC, buf);
  const t2 = performance.now();
  const gl = view.gl;
  const ext = gl.getExtension("EXT_disjoint_timer_query_webgl2");
  let query = null;
  if (ext) { query = gl.createQuery(); gl.beginQuery(ext.TIME_ELAPSED_EXT, query); }
  view._drawNow();
  if (ext) gl.endQuery(ext.TIME_ELAPSED_EXT);
  gl.finish();
  const t3 = performance.now();
  const w = Math.min(64, view.canvas.width), h = Math.min(64, view.canvas.height);
  const px = new Uint8Array(w * h * 4);
  gl.readPixels(((view.canvas.width - w) / 2) | 0, ((view.canvas.height - h) / 2) | 0,
                w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const t4 = performance.now();
  let nonblank = 0;
  for (let i = 0; i < px.length; i += 4)
    if (px[i] || px[i + 1] || px[i + 2] || px[i + 3]) nonblank++;
  let gpuDrawMs = null;
  if (ext && query) {
    for (let tries = 0; tries < 200; tries++) {
      await new Promise(r => setTimeout(r, 5));
      if (gl.getQueryParameter(query, gl.QUERY_RESULT_AVAILABLE)) {
        if (!gl.getParameter(ext.GPU_DISJOINT_EXT))
          gpuDrawMs = gl.getQueryParameter(query, gl.QUERY_RESULT) / 1e6;
        break;
      }
    }
  }
  const g = view.gpuTraces[0];
  return {
    rows: __XY_SPEC.columns[g.trace.kind === "scatter" ? g.trace.x : 0].len,
    tier: g.tier || "direct",
    decode_ms: +(t1 - t0).toFixed(1),
    build_upload_ms: +(t2 - t1).toFixed(1),
    draw_sync_ms: +(t3 - t2).toFixed(1),
    readback_ms: +(t4 - t3).toFixed(1),
    gpu_draw_ms: gpuDrawMs == null ? null : +gpuDrawMs.toFixed(1),
    nonblank,
    heap_mb: performance.memory ? +(performance.memory.usedJSHeapSize / 2**20).toFixed(0) : null,
  };
})();
"""


def build_page(n: int, seed: int) -> tuple[str, dict[str, float]]:
    """Standalone-style page for N direct-mode points + Python-stage timings."""
    import numpy as np

    import xy
    from xy import export

    rng = np.random.default_rng(seed)
    # Shared-data methodology: generation is excluded from every timing.
    x = rng.uniform(0.0, 1.0, n)
    y = rng.uniform(0.0, 1.0, n)

    stages: dict[str, float] = {}
    t0 = time.perf_counter()
    with warnings.catch_warnings():
        # density=False above the soft ceiling warns by design (§28); the
        # raw-mode benchmark opts in knowingly, once, not once per size.
        warnings.simplefilter("ignore", RuntimeWarning)
        fig = xy.scatter_chart(
            xy.scatter(x=x, y=y, size=1.0, opacity=0.15, density=False),
            width=VIEW_W,
            height=VIEW_H,
        ).figure()
        spec, blob = fig.build_payload()
    stages["payload_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    chunks = export._base64_chunks(blob)
    stages["b64_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    chunk_scripts = "\n".join(f"<script>__xyChunks.push({json.dumps(c)});</script>" for c in chunks)
    client_js = export._javascript_for_inline_script(export._bundled_js("standalone"))
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>raw scatter {n}</title>
<style>html,body{{margin:0;background:#fff;}}#chart{{width:{VIEW_W}px;height:{VIEW_H}px;}}</style>
</head><body>
<div id="chart"></div>
<script>{client_js}</script>
<script>var __xyChunks = [];</script>
{chunk_scripts}
<script>
{export._DECODE_B64_JS}
var __XY_SPEC = {export._json_for_inline_script(spec)};
var __XY_TOTAL = {len(blob)};
{_PROBE}
</script>
</body></html>"""
    stages["compose_ms"] = (time.perf_counter() - t0) * 1000
    stages["payload_mb"] = len(blob) / 2**20
    return html, stages


def run_case(browser: Browser, workdir: Path, n: int, seed: int) -> dict[str, object]:
    html, stages = build_page(n, seed)
    page_path = workdir / f"raw-{n}.html"
    t0 = time.perf_counter()
    page_path.write_text(html, encoding="utf-8")
    stages["write_ms"] = (time.perf_counter() - t0) * 1000

    page = browser.new_page()
    try:
        t0 = time.perf_counter()
        page.navigate(page_path.as_uri(), timeout_s=600.0)
        stages["navigate_ms"] = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        result = page.eval("window.__probe", timeout_s=600.0)
        stages["probe_wall_ms"] = (time.perf_counter() - t0) * 1000
    finally:
        page.close()
        page_path.unlink(missing_ok=True)

    result = dict(result or {})
    ok = result.get("rows") == n and (result.get("nonblank") or 0) > 0
    browser_ms = sum(
        result.get(k) or 0.0
        for k in ("decode_ms", "build_upload_ms", "draw_sync_ms", "readback_ms")
    )
    python_ms = sum(stages[k] for k in ("payload_ms", "b64_ms", "compose_ms", "write_ms"))
    return {
        "n": n,
        "validated": ok,
        **{k: round(v, 1) for k, v in stages.items()},
        **result,
        "python_total_ms": round(python_ms, 1),
        "browser_total_ms": round(browser_ms, 1),
        "end_to_end_ms": round(python_ms + stages["navigate_ms"] + browser_ms, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sizes", default="1e6,5e6,10e6,25e6")
    parser.add_argument("--gl", choices=("software", "hardware"), default="software")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="emit one JSON line per size")
    args = parser.parse_args()
    sizes = [int(float(s)) for s in args.sizes.split(",") if s.strip()]

    chromium = default_chromium()
    if chromium is None:
        print("no chromium found (set $XY_CHROMIUM)", file=sys.stderr)
        return 2

    t0 = time.perf_counter()
    with (
        Browser(chromium, gl=args.gl, window=(VIEW_W, VIEW_H)) as browser,
        TemporaryDirectory(prefix="xy-raw-bench-") as td,
    ):
        print(
            f"# chromium={chromium} gl={args.gl} "
            f"startup={time.perf_counter() - t0:.2f}s (excluded from rows)"
        )
        header = (
            f"{'N':>12} {'ok':>3} {'MB':>7} {'python':>8} {'navigate':>9} {'decode':>7} "
            f"{'upload':>7} {'draw':>7} {'gpu':>7} {'read':>6} {'total':>8}"
        )
        if not args.json:
            print(header)
        for n in sizes:
            row = run_case(browser, Path(td), n, args.seed)
            if args.json:
                print(json.dumps(row))
                continue
            gpu = row.get("gpu_draw_ms")
            print(
                f"{row['n']:>12,} {'y' if row['validated'] else 'N':>3} "
                f"{row['payload_mb']:>7.1f} {row['python_total_ms']:>8.1f} "
                f"{row['navigate_ms']:>9.1f} {row['decode_ms']:>7.1f} "
                f"{row['build_upload_ms']:>7.1f} {row['draw_sync_ms']:>7.1f} "
                f"{'n/a' if gpu is None else gpu:>7} {row['readback_ms']:>6.1f} "
                f"{row['end_to_end_ms']:>8.1f}"
            )
            if not row["validated"]:
                print(f"# VALIDATION FAILED at N={n}: {row}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
