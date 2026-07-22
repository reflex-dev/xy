#!/usr/bin/env python3
"""Focused real-Chromium measurements for issue #176 client findings.

Measures dense style packing, append-key alternatives, and GPU pick readback.
The append alternatives are diagnostic: only an exact identity relation is a
candidate for production, regardless of its timing.

Usage:
  PYTHONPATH=python python benchmarks/bench_client_transport_quick_wins.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import xy  # noqa: E402
from _xy_browser import chart_payload, page_for_charts, run_json_probe  # noqa: E402

PROBE = r"""
(async () => {
  try {
    const payload = XY_CHARTS[0];
    const bytes = xyBytesFromPayload(payload);
    const root = document.createElement("div");
    root.style.cssText = "width:900px;height:420px";
    document.getElementById("root").appendChild(root);
    const view = xy.renderStandalone(root, payload.spec, bytes);
    view._drawNow();
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    const gl = view.gl;
    gl.finish();
    const g = view.gpuTraces[0];
    const opacity = g.trace.channels.opacity;
    const source = view._columnView(bytes, payload.spec.columns[opacity.buf]);
    const n = g.n;
    const reps = window.XY_REPS;
    const median = (values) => values.slice().sort((a, b) => a - b)[values.length >> 1];

    const legacyPack = () => {
      const values = new Float32Array(n * 4);
      for (let i = 0; i < n; i++) {
        values[i * 4] = 1;
        values[i * 4 + 1] = -1;
        values[i * 4 + 2] = -1;
        values[i * 4 + 3] = -1;
      }
      for (let i = 0; i < n; i++) values[i * 4] = source[i];
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, values, gl.STATIC_DRAW);
      gl.finish();
      gl.deleteBuffer(buffer);
      return values.byteLength;
    };
    const compactPack = () => {
      const target = {};
      view._packInstanceStyleChannels(
        target, n,
        (name) => name === "opacity" ? opacity : null,
        NaN, () => source, "stroke_width",
      );
      gl.finish();
      const result = target.styleBuf._fcBytes;
      gl.deleteBuffer(target.styleBuf);
      return result;
    };
    legacyPack(); compactPack();
    const legacyPackMs = [], compactPackMs = [];
    for (let i = 0; i < reps; i++) {
      let start = performance.now();
      const legacyBytes = legacyPack();
      legacyPackMs.push(performance.now() - start);
      start = performance.now();
      const compactBytes = compactPack();
      compactPackMs.push(performance.now() - start);
      if (legacyBytes !== n * 16 || compactBytes !== n * 4) throw Error("style byte oracle");
    }

    const appendN = Math.min(n, 200000);
    // Mirror the real append path: coordinates are f32 residuals decoded with
    // a large f64 offset. These epoch-scale values are all distinct under the
    // legacy 12-significant-digit relation. A f32 key is not: at 1.7e12 its
    // ULP is 131072, so many adjacent timestamps alias one Map entry.
    const epochBase = 1700000000000;
    const epochStep = 1024;
    const oldOffset = epochBase + 65536;
    const newOffset = epochBase + 131072;
    const oldEncoded = new Float32Array(appendN);
    const newEncoded = new Float32Array(appendN);
    const oldValues = new Float64Array(appendN);
    const newValues = new Float64Array(appendN);
    for (let i = 0; i < appendN; i++) {
      const value = epochBase + i * epochStep;
      oldEncoded[i] = value - oldOffset;
      newEncoded[i] = value - newOffset;
      oldValues[i] = oldEncoded[i] + oldOffset;
      newValues[i] = newEncoded[i] + newOffset;
    }
    const mathKey = (value) => {
      if (value === 0) return 0;
      const magnitude = Math.abs(value);
      let exponent = Math.floor(Math.log10(magnitude));
      const scale = 10 ** (11 - exponent);
      let mantissa = Math.round(magnitude * scale);
      if (mantissa >= 1e12) { mantissa = 1e11; exponent += 1; }
      return ((exponent + 400) * 2 + (value < 0 ? 1 : 0)) * 1000000000001 + mantissa;
    };
    const f32Storage = new ArrayBuffer(4);
    const f32Value = new Float32Array(f32Storage);
    const f32Bits = new Uint32Array(f32Storage);
    const f32BitsKey = (value) => {
      // SameValueZero (Map's relation) treats -0 and +0 as one identity; keep
      // that legacy behavior while testing the exact proposed f32-bit key.
      if (value === 0) return 0;
      f32Value[0] = value;
      return f32Bits[0];
    };
    const appendPass = (key) => {
      const index = new Map();
      for (let i = 0; i < appendN; i++) index.set(key(oldValues[i]), i);
      let matches = 0, exactMatches = 0;
      for (let i = 0; i < appendN; i++) {
        const oldIndex = index.get(key(newValues[i]));
        if (oldIndex !== undefined) matches++;
        if (oldIndex === i) exactMatches++;
      }
      return {
        matches,
        exact_matches: exactMatches,
        unique_old_keys: index.size,
        old_key_collisions: appendN - index.size,
      };
    };
    const keyFns = {
      string: (value) => value.toPrecision(12),
      parsed: (value) => Number(value.toPrecision(12)),
      math: mathKey,
      fround: (value) => Math.fround(value),
      f32_bits: f32BitsKey,
    };
    const append = {};
    for (const [name, key] of Object.entries(keyFns)) {
      appendPass(key);
      const samples = [];
      let pass = null;
      for (let i = 0; i < reps; i++) {
        const start = performance.now();
        pass = appendPass(key);
        samples.push(performance.now() - start);
      }
      append[name] = { median_ms: median(samples), ...pass };
    }
    const boundary = {
      shouldMatch: [8.952695812915, 8.95269581290906],
      shouldMiss: [1234567890125, 1234567890124.9973],
    };
    const relation = (key, pair) => key(pair[0]) === key(pair[1]);
    const epochDistinct = [epochBase, epochBase + epochStep];
    for (const [name, key] of Object.entries(keyFns)) {
      append[name].boundary_match = relation(key, boundary.shouldMatch);
      append[name].boundary_miss = !relation(key, boundary.shouldMiss);
      append[name].epoch_adjacent_distinct = !relation(key, epochDistinct);
    }
    // Semantic oracles are part of the benchmark: timings must never make a
    // lossy candidate look like a production win.
    if (append.string.unique_old_keys !== appendN ||
        append.string.exact_matches !== appendN ||
        !append.string.boundary_match || !append.string.boundary_miss ||
        !append.string.epoch_adjacent_distinct) {
      throw Error("legacy append-key oracle");
    }
    for (const name of ["fround", "f32_bits"]) {
      if (append[name].unique_old_keys >= appendN ||
          append[name].exact_matches >= appendN ||
          append[name].boundary_miss ||
          append[name].epoch_adjacent_distinct) {
        throw Error(`${name} rejection oracle`);
      }
    }

    // Populate the pick snapshot once, then separate stable readback cost from
    // the O(N) redraw that a dirty snapshot forces.
    const px = Math.floor(view.canvas.width / 2);
    const py = Math.floor(view.canvas.height / 2);
    view._pickDirty = true;
    view._pickAt(px / view.dpr, view.plot.h - py / view.dpr);
    const cleanPickMs = [];
    for (let i = 0; i < Math.max(50, reps * 10); i++) {
      const start = performance.now();
      view._pickAt(px / view.dpr, view.plot.h - py / view.dpr);
      cleanPickMs.push(performance.now() - start);
    }
    const dirtyPickMs = [];
    for (let i = 0; i < Math.max(5, reps); i++) {
      view._pickDirty = true;
      const start = performance.now();
      view._pickAt(px / view.dpr, view.plot.h - py / view.dpr);
      dirtyPickMs.push(performance.now() - start);
    }

    const pbo = gl.createBuffer();
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, pbo);
    gl.bufferData(gl.PIXEL_PACK_BUFFER, 4, gl.STREAM_READ);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    const pboSubmitMs = [], pboCompleteMs = [];
    let pboForcedFinishes = 0;
    const pboOut = new Uint8Array(4);
    for (let i = 0; i < Math.max(12, reps * 2); i++) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, view.pickFbo);
      gl.bindBuffer(gl.PIXEL_PACK_BUFFER, pbo);
      const start = performance.now();
      gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, 0);
      const fence = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
      gl.flush();
      pboSubmitMs.push(performance.now() - start);
      await new Promise((resolve) => setTimeout(resolve, 0));
      let status = gl.clientWaitSync(fence, gl.SYNC_FLUSH_COMMANDS_BIT, 0);
      if (status === gl.TIMEOUT_EXPIRED) {
        // A production async path would defer the tooltip and keep polling.
        // Finish here only so this bounded diagnostic can report that first-
        // task availability miss instead of hanging --dump-dom.
        pboForcedFinishes += 1;
        gl.finish();
        status = gl.CONDITION_SATISFIED;
      }
      if (status === gl.WAIT_FAILED) throw Error("PBO fence failed");
      gl.getBufferSubData(gl.PIXEL_PACK_BUFFER, 0, pboOut);
      pboCompleteMs.push(performance.now() - start);
      gl.deleteSync(fence);
      gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    }
    gl.deleteBuffer(pbo);

    xyReport("XY_CLIENT_QUICK_WINS", {
      n,
      reps,
      style: {
        legacy_bytes: n * 16,
        compact_bytes: n * 4,
        legacy_median_ms: median(legacyPackMs),
        compact_median_ms: median(compactPackMs),
      },
      append,
      append_dataset: {
        n: appendN,
        epoch_base: epochBase,
        epoch_step: epochStep,
        old_offset: oldOffset,
        new_offset: newOffset,
      },
      pick: {
        clean_sync_median_ms: median(cleanPickMs),
        dirty_sync_median_ms: median(dirtyPickMs),
        pbo_submit_median_ms: median(pboSubmitMs),
        pbo_complete_median_ms: median(pboCompleteMs),
        pbo_forced_finishes: pboForcedFinishes,
        pbo_reps: pboCompleteMs.length,
      },
      gl_error: gl.getError(),
    });
  } catch (err) {
    xyFail("XY_CLIENT_QUICK_WINS", err);
  }
})();
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=250_000)
    parser.add_argument("--reps", type=int, default=7)
    parser.add_argument("--chromium")
    args = parser.parse_args()

    x = np.linspace(0.0, 1.0, args.n, dtype=np.float64)
    opacity = np.linspace(0.2, 1.0, args.n, dtype=np.float64)
    chart = xy.scatter_chart(
        xy.scatter(x=x, y=x, opacity=opacity, density=False, size=3.0),
        width=900,
        height=420,
    ).figure()
    spec, blob = chart.build_payload()
    probe = f"window.XY_REPS = {args.reps};\n" + PROBE
    page = page_for_charts(
        [chart_payload("client-quick-wins", spec, blob)],
        probe,
        title="xy client quick wins",
    )
    result = run_json_probe(
        page,
        marker="XY_CLIENT_QUICK_WINS",
        chromium=args.chromium,
        virtual_time_ms=30_000,
        timeout_s=180,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
