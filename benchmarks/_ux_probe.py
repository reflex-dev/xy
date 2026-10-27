#!/usr/bin/env python3
"""Shared in-page UX probe: one measurement engine, per-arm adapters.

The engine implements the measurement contract from the ceiling plan:

- The clock stops only on a frame that is both **semantically correct**
  (scripted-target axis domain, planted sentinel points lit at their
  projected positions) and **pixel-stable** (full readback surface
  byte-identical for STABLE_FRAMES consecutive frames).  Stability without
  correctness would pass a stale raster while a server is still computing;
  correctness without stability would pass a frame still being painted.
- Gesture inputs are replayed on a **fixed wall-clock schedule** — the way a
  hand moves — never paced by the library's frame rate.  A slow arm receives
  inputs on time and falls behind honestly.
- Phase timings are reported as durations within one browser clock
  (`performance.now()`); Python-side build time is added by the orchestrator
  as a separate duration.  No timestamp ever crosses a clock domain.

Each arm supplies a JS adapter defining `window.__arm`:

    ready()      -> bool          chart object exists and is renderable
    domain()     -> {x0,x1,y0,y1} current data-space view, or null
    project(x,y) -> {px,py}       data coords -> CSS pixels on the readback
                                  surface (top-left origin), or null
    readbacks()  -> [{data:Uint8ClampedArray|Uint8Array RGBA, w, h,
                      topDown:bool, cssW, cssH}]
                                  full snapshot of every drawing surface;
                                  MUST force any pending draw first
    zoomInput(fx,fy,dir)          dispatch ONE real zoom input (wheel event
                                  or protocol message) at canvas fraction
                                  (fx, fy); dir>0 zooms in

The probe writes progress to `document.title`:
    'UX_STAGE {json}'  while running (load / gesture / settle)
    'UX_BENCH {json}'  terminal result
    'UX_ERROR text'    terminal failure
"""

from __future__ import annotations

import json
from typing import Any

STABLE_FRAMES = 10
LOAD_DEADLINE_MS = 30_000
SETTLE_DEADLINE_MS = 30_000
# ~1.4 s of continuous zooming at a human-plausible input cadence.  42 is a
# multiple of 6 so arms whose idiom is a rubber-band drag (6 events per box)
# end on a completed drag — a run ending mid-press would let settle start
# from an input that changed nothing, skipping the final server round trip.
GESTURE_INPUTS = 42
GESTURE_CADENCE_MS = 33
# The gesture must actually zoom: final x-span <= this fraction of home span.
ZOOM_PROOF_FRACTION = 0.5
# A sentinel is "lit" when >= this many pixels in its sample window differ
# from the surface's background reference by more than the noise threshold.
SENTINEL_MIN_LIT = 1
SENTINEL_WINDOW_CSS = 5
PIXEL_NOISE = 24


def engine_js(meta: dict[str, Any]) -> str:
    """The measurement engine, parametrized with run metadata.

    `meta` must carry: sentinels ([[x, y], ...] in data coords) and may carry
    overrides for the constants above (keys mirror the constant names).
    """
    cfg = {
        "stable_frames": STABLE_FRAMES,
        "load_deadline_ms": LOAD_DEADLINE_MS,
        "settle_deadline_ms": SETTLE_DEADLINE_MS,
        "gesture_inputs": GESTURE_INPUTS,
        "gesture_cadence_ms": GESTURE_CADENCE_MS,
        "zoom_proof_fraction": ZOOM_PROOF_FRACTION,
        "sentinel_min_lit": SENTINEL_MIN_LIT,
        "sentinel_window_css": SENTINEL_WINDOW_CSS,
        "pixel_noise": PIXEL_NOISE,
        **meta,
    }
    return (
        "window.__uxMeta = "
        + json.dumps(cfg)
        + ";\n"
        + r"""
(async () => {
  const M = window.__uxMeta;
  const stage = (s, extra) =>
    (document.title = "UX_STAGE " + JSON.stringify({ stage: s, ...extra }));
  const fail = (why, extra) =>
    (document.title = "UX_ERROR " + JSON.stringify({ why, ...extra }).slice(0, 700));
  // Verification screenshots: pause AFTER the clock has stopped, hand the
  // driver a named checkpoint, resume when it confirms.  The pause sits
  // outside every measured span, so timing is unaffected.  If no driver is
  // listening (manual page load), continue after a short grace.
  async function shot(name) {
    window.__shotDone = false;
    document.title = "UX_SHOT " + name;
    const start = performance.now();
    while (!window.__shotDone && performance.now() - start < 5000)
      await new Promise((r) => requestAnimationFrame(r));
  }
  try {
    // -------------------------------------------------------- arm handshake
    const t0 = performance.now();
    while (!window.__arm || !window.__arm.ready()) {
      if (performance.now() - t0 > M.load_deadline_ms) return fail("arm_never_ready");
      await new Promise((r) => requestAnimationFrame(r));
    }
    const A = window.__arm;

    // ------------------------------------------------------------- pixels
    function snapshot() {
      // Hash every surface and keep the raw planes for sentinel sampling.
      const surfaces = A.readbacks();
      let hash = 5381 >>> 0;
      let lit = 0;
      for (const s of surfaces) {
        const d = s.data;
        for (let i = 0; i < d.length; i += 4) {
          const v = (d[i] << 16) ^ (d[i + 1] << 8) ^ d[i + 2];
          if (v || d[i + 3]) lit++;
          hash = (((hash * 33) >>> 0) ^ v) >>> 0;
        }
      }
      return { surfaces, hash, lit };
    }

    function samplePx(s, px, py, out) {
      // px,py in CSS coords of the surface; convert to device rows/cols.
      const sx = s.w / (s.cssW || s.w);
      const sy = s.h / (s.cssH || s.h);
      const cx = Math.round(px * sx);
      const cyTop = Math.round(py * sy);
      const cy = s.topDown ? cyTop : s.h - 1 - cyTop;
      if (cx < 0 || cy < 0 || cx >= s.w || cy >= s.h) return;
      const i = (cy * s.w + cx) * 4;
      out.push([s.data[i], s.data[i + 1], s.data[i + 2], s.data[i + 3]]);
    }

    function background(surfaces) {
      // Reference background: the *modal* corner pixel across surfaces.  The
      // top-left corner alone is not safe -- a title, axis label or toolbar
      // can occupy it, and every sentinel would then be compared against the
      // wrong reference, silently weakening the correctness gate.
      const counts = new Map();
      for (const s of surfaces) {
        for (const [fx, fy] of [[2, 2], [s.w - 3, 2], [2, s.h - 3], [s.w - 3, s.h - 3]]) {
          const i = (fy * s.w + fx) * 4;
          const px = [s.data[i], s.data[i + 1], s.data[i + 2], s.data[i + 3]];
          const key = px.join(",");
          const seen = counts.get(key);
          counts.set(key, seen ? {px: seen.px, n: seen.n + 1} : {px: px, n: 1});
        }
      }
      let best = null;
      for (const entry of counts.values()) {
        if (!best || entry.n > best.n) best = entry;
      }
      return best ? best.px : [0, 0, 0, 0];
    }

    function sentinelsLit(snap) {
      // Every sentinel whose projection lands on a surface must be drawn.
      const bg = background(snap.surfaces);
      const R = Math.max(2, M.sentinel_window_css | 0);
      let visible = 0;
      let litCount = 0;
      const each = [];
      for (const [x, y] of M.sentinels) {
        const p = A.project(x, y);
        if (!p) { each.push("off"); continue; }
        let inAny = false;
        let hits = 0;
        for (const s of snap.surfaces) {
          if (p.px < -R || p.py < -R) continue;
          if (p.px >= (s.cssW || s.w) + R || p.py >= (s.cssH || s.h) + R) continue;
          inAny = true;
          const out = [];
          for (let dx = -R; dx <= R; dx++)
            for (let dy = -R; dy <= R; dy++) samplePx(s, p.px + dx, p.py + dy, out);
          for (const q of out) {
            const diff =
              Math.abs(q[0] - bg[0]) + Math.abs(q[1] - bg[1]) +
              Math.abs(q[2] - bg[2]) + Math.abs(q[3] - bg[3]);
            if (diff > M.pixel_noise) { hits++; break; }
          }
        }
        if (inAny) {
          visible++;
          if (hits >= M.sentinel_min_lit) { litCount++; each.push("lit"); }
          else each.push("dark");
        } else each.push("off");
      }
      return {
        visible,
        lit: litCount,
        allLit: visible > 0 && litCount === visible,
        each,
        targetLit: each[0] === "lit",
      };
    }

    // ------------------------------------------- correct-then-stable engine
    async function waitCorrectStable(checkFn, deadlineMs, phase) {
      // Stop clock: timestamp of the FIRST frame of a run of `stable_frames`
      // byte-identical frames, all of which satisfy checkFn.  Failure modes
      // are distinguished so a wrong picture is never reported as slow.
      const start = performance.now();
      let last = null;
      let stableStart = null;
      let stableCount = 0;
      let firstFrame = null;
      let firstCorrect = null;
      let everCorrect = false;
      while (performance.now() - start < deadlineMs) {
        const snap = snapshot();
        const now = performance.now();
        if (firstFrame === null && snap.lit > 0) firstFrame = now;
        const correct = checkFn(snap);
        if (correct) everCorrect = true;
        if (correct && firstCorrect === null) firstCorrect = now;
        if (last !== null && snap.hash === last.hash && correct) {
          if (stableCount === 0) stableStart = now;
          stableCount++;
          if (stableCount >= M.stable_frames)
            return {
              ok: true,
              stop_ms: stableStart,
              first_frame_ms: firstFrame,
              first_correct_ms: firstCorrect,
            };
        } else {
          stableCount = 0;
          stableStart = null;
        }
        last = snap;
        stage(phase, { t: Math.round(now - start), correct, stable: stableCount });
        await new Promise((r) => requestAnimationFrame(r));
      }
      return {
        ok: false,
        reason: everCorrect ? phase + "_unstable" : phase + "_incorrect",
        first_frame_ms: firstFrame,
        first_correct_ms: firstCorrect,
      };
    }

    // ------------------------------------------------------------ 1. LOAD
    stage("load");
    const homeCheck = (snap) => {
      const d = A.domain();
      if (!d || !isFinite(d.x0) || !isFinite(d.x1)) return false;
      return sentinelsLit(snap).allLit;
    };
    const load = await waitCorrectStable(homeCheck, M.load_deadline_ms, "render");
    if (!load.ok) return fail(load.reason, load);
    await shot("visible-complete");
    const home = A.domain();
    const homeSpan = home.x1 - home.x0;
    const result = {
      first_frame_ms: load.first_frame_ms,
      visible_complete_ms: load.stop_ms,
      render_stable: true,
    };

    // --------------------------------------------------------- 2. GESTURE
    // Inputs on a fixed wall-clock schedule, aimed at the sentinel centroid
    // (recomputed per input so the target tracks the moving view).
    stage("gesture");
    // The zoom target is sentinel[0], not the centroid: wheel zoom holds the
    // cursor's data point invariant, so the designated sentinel stays inside
    // the window at any zoom depth — a centroid of scattered points does not.
    const [cx, cy] = M.sentinels[0];
    const frames = [];
    let rafOn = true;
    let lastFrame = performance.now();
    (function frameLoop() {
      if (!rafOn) return;
      const now = performance.now();
      frames.push(now - lastFrame);
      lastFrame = now;
      requestAnimationFrame(frameLoop);
    })();

    const tFirstInput = performance.now();
    for (let i = 0; i < M.gesture_inputs; i++) {
      const target = tFirstInput + i * M.gesture_cadence_ms;
      const wait = target - performance.now();
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      // Aim at the sentinels' current on-screen position, clamped inside.
      const d = A.domain() || home;
      // Aim at the sentinels' current on-screen position.  The clamp must be
      // loose: sentinels sit at the autoscaled domain's edge in the home
      // view, and a tight clamp would zoom beside them until they leave the
      // viewport entirely.
      let fx = (cx - d.x0) / (d.x1 - d.x0);
      let fy = (cy - d.y0) / (d.y1 - d.y0);
      fx = Math.min(0.98, Math.max(0.02, fx));
      fy = 1 - Math.min(0.98, Math.max(0.02, fy));
      A.zoomInput(fx, fy, +1);
    }
    const tLastInput = performance.now();
    rafOn = false;
    frames.shift(); // first interval spans pre-gesture idle
    frames.sort((a, b) => a - b);
    const q = (p) =>
      frames.length ? frames[Math.min(frames.length - 1, Math.floor(p * frames.length))] : null;
    const refresh = Math.max(1, q(0.05) || 16.7);
    result.gesture_wall_ms = tLastInput - tFirstInput;
    result.gesture_frames = frames.length;
    result.gesture_frame_p50_ms = q(0.5);
    result.gesture_frame_p95_ms = q(0.95);
    result.gesture_frame_max_ms = frames.length ? frames[frames.length - 1] : null;
    result.gesture_achieved_fps = frames.length
      ? Math.round((1000 * frames.length) / (tLastInput - tFirstInput + 1e-9) * 10) / 10
      : null;
    result.gesture_dropped_pct = frames.length
      ? Math.round(
          (100 * frames.filter((f) => f > 1.5 * refresh).length) / frames.length * 10
        ) / 10
      : null;

    // ---------------------------------------------------------- 3. SETTLE
    stage("settle");
    const zoomCheck = (snap) => {
      // Correct after the zoom: the designated target sentinel is on screen
      // and drawn, and the domain has provably shrunk.  Other sentinels may
      // legitimately have left the window at depth.
      const d = A.domain();
      if (!d) return false;
      const spanFrac = (d.x1 - d.x0) / homeSpan;
      const s = sentinelsLit(snap);
      window.__zoomDiag = { spanFrac, ...s, domain: d };
      if (!(spanFrac <= M.zoom_proof_fraction)) return false;
      return s.targetLit;
    };
    const settle = await waitCorrectStable(zoomCheck, M.settle_deadline_ms, "settle");
    if (!settle.ok)
      return fail(settle.reason, { ...result, ...settle, diag: window.__zoomDiag });
    await shot("settle-complete");
    result.settle_ms = settle.stop_ms - tLastInput;
    result.zoom_to_final_ms = settle.stop_ms - tFirstInput;
    const fin = A.domain();
    result.final_span_fraction =
      Math.round(((fin.x1 - fin.x0) / homeSpan) * 1e4) / 1e4;

    document.title = "UX_BENCH " + JSON.stringify(result);
  } catch (e) {
    fail("exception", { e: String((e && e.stack) || e).slice(0, 400) });
  }
})();
"""
    )
