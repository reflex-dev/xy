#!/usr/bin/env python3
"""Measure hexbin client build/upload cost and resident attribute bytes.

This benchmark isolates the browser-side stage addressed by issue #175.  The
Python/native binning pass is setup, not measurement; each repetition rebuilds
one hexbin GPU trace from the retained compact payload, draws it, synchronizes
the GL queue, and reads the driver's buffer sizes.  ``legacy_fan_bytes`` is the
exact prior layout (42 f32/cell), making the byte reduction reproducible even
after the old implementation is gone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import xy
from _browser import chromium_gl_flags, find_chromium  # ty: ignore[unresolved-import]
from _xy_browser import (  # ty: ignore[unresolved-import]
    chart_payload,
    page_for_charts,
    run_json_probe,
)

_PROBE = r"""
(async () => {
  try {
    const payload = XY_CHARTS[0];
    const bytes = xyBytesFromPayload(payload);
    const host = document.getElementById("root");
    const view = xy.renderStandalone(host, payload.spec, bytes);
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    const gl = view.gl;
    const buildMs = [], drawMs = [];
    let residentBytes = 0, cells = 0, layout = "unknown";

    const bufferBytes = (buffer) => {
      if (!buffer) return 0;
      const prior = gl.getParameter(gl.ARRAY_BUFFER_BINDING);
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      const size = gl.getBufferParameter(gl.ARRAY_BUFFER, gl.BUFFER_SIZE);
      gl.bindBuffer(gl.ARRAY_BUFFER, prior);
      return size;
    };
    const pixelStats = () => {
      const w = Math.min(96, view.canvas.width), h = Math.min(96, view.canvas.height);
      const x = Math.max(0, ((view.canvas.width - w) / 2) | 0);
      const y = Math.max(0, ((view.canvas.height - h) / 2) | 0);
      const pixels = new Uint8Array(w * h * 4);
      gl.readPixels(x, y, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      let lit = 0, hash = 2166136261;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] || pixels[i + 1] || pixels[i + 2] || pixels[i + 3]) lit++;
        hash ^= pixels[i]; hash = Math.imul(hash, 16777619);
        hash ^= pixels[i + 1]; hash = Math.imul(hash, 16777619);
        hash ^= pixels[i + 2]; hash = Math.imul(hash, 16777619);
        hash ^= pixels[i + 3]; hash = Math.imul(hash, 16777619);
      }
      return {lit, hash: hash >>> 0};
    };

    // The first construction warms the shared LUT and shader compilation.
    view._drawNow(); gl.finish();
    for (let rep = 0; rep < XY_REPS; rep++) {
      for (const g of view.gpuTraces) view._destroyTraceResources(g, new Set());
      view.gpuTraces = [];
      const started = performance.now();
      const g = view._buildTrace(bytes, payload.spec.traces[0]);
      buildMs.push(performance.now() - started);
      view.gpuTraces = [g];
      const drawStarted = performance.now();
      view._drawNow(); gl.finish();
      drawMs.push(performance.now() - drawStarted);
      const compactBuffers = [g.xBuf, g.yBuf, g.cBuf];
      const legacyBuffers = [g.x0Buf, g.x1Buf, g.x2Buf, g.y0Buf, g.y1Buf, g.y2Buf, g.cBuf];
      const compact = !!g.xBuf && !!g.yBuf && !g.x0Buf && !g.y0Buf;
      const legacy = !g.xBuf && !g.yBuf && !!g.x0Buf && !!g.y0Buf;
      layout = compact ? "compact" : (legacy ? "legacy" : "unknown");
      residentBytes = (compact ? compactBuffers : legacyBuffers).reduce(
        (total, buffer) => total + bufferBytes(buffer), 0);
      cells = payload.spec.traces[0].n_marks;
    }
    const rendered = pixelStats();
    const result = {
      cells,
      build_upload: xyStats(buildMs),
      draw_sync: xyStats(drawMs),
      resident_bytes: residentBytes,
      layout,
      nonblank_pixels: rendered.lit,
      pixel_hash: rendered.hash,
      gl_error: gl.getError(),
    };
    xyReport("XY_HEXBIN_CLIENT", result);
  } catch (err) {
    xyFail("XY_HEXBIN_CLIENT", err);
  }
})();
"""


def _payload(gridsize: int) -> tuple[dict, bytes]:
    # One input at each lattice point fills a large, deterministic fraction of
    # the occupied cells without random variation between benchmark runs.
    values = np.linspace(-4.0, 4.0, gridsize + 1, dtype=np.float64)
    x, y = np.meshgrid(values, values)
    chart = xy.hexbin_chart(
        xy.hexbin(
            x.ravel(),
            y.ravel(),
            gridsize=(gridsize, gridsize),
            range=((-4.01, 4.01), (-4.01, 4.01)),
            mincnt=1,
            opacity=0.8,
        ),
        width=900,
        height=520,
    )
    return chart.figure().build_payload()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gridsize", type=int, default=256)
    parser.add_argument("--reps", type=int, default=9)
    parser.add_argument("--chromium")
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--expect-layout", choices=("compact", "legacy", "either"), default="compact"
    )
    args = parser.parse_args()
    if args.gridsize < 8:
        parser.error("--gridsize must be >= 8")
    if args.reps < 1:
        parser.error("--reps must be >= 1")
    chrome = find_chromium(args.chromium)
    if not chrome:
        raise SystemExit("no Chromium executable found")

    spec, blob = _payload(args.gridsize)
    page = page_for_charts(
        [chart_payload("hexbin", spec, blob)],
        f"const XY_REPS = {args.reps};\n{_PROBE}",
        title="xy hexbin client benchmark",
    )
    result = run_json_probe(
        page,
        marker="XY_HEXBIN_CLIENT",
        chromium=chrome,
        timeout_s=180,
    )
    if result.get("status") != "ok":
        raise SystemExit(str(result.get("status")))
    cells = int(result["cells"])
    compact_bytes = cells * 3 * np.dtype(np.float32).itemsize
    legacy_bytes = cells * 42 * np.dtype(np.float32).itemsize
    result.update(
        {
            "gridsize": args.gridsize,
            "compact_expected_bytes": compact_bytes,
            "legacy_fan_bytes": legacy_bytes,
            "resident_reduction_x": legacy_bytes / int(result["resident_bytes"]),
            "resident_reduction_percent": 100.0
            * (legacy_bytes - int(result["resident_bytes"]))
            / legacy_bytes,
            "gl_backend": "hardware" if not chromium_gl_flags() else "swiftshader",
        }
    )
    expected_bytes = legacy_bytes if result["layout"] == "legacy" else compact_bytes
    if (
        result["layout"] == "unknown"
        or (args.expect_layout != "either" and result["layout"] != args.expect_layout)
        or int(result["resident_bytes"]) != expected_bytes
    ):
        raise SystemExit(f"unexpected hexbin GPU layout: {result}")
    text = json.dumps({"benchmark": "hexbin-client", "result": result}, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
