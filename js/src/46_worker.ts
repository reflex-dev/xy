// ---------------------------------------------------------------------------
// Standalone density re-bin worker (dossier Phase 1: worker-side compute).
//
// A kernel-less page (a `to_html` export) ships the density overview grid plus
// the recorded sample (§28: "sampled N of M"). Without a kernel, zooming used
// to stretch the overview texture. This worker re-bins that retained sample
// for the current view *off the main thread*, so standalone density charts
// refine on zoom with zero main-thread jank; the result is applied through the
// same LOD plumbing as a kernel density_update and recorded as a reduction
// badge ("zoom re-binned from sample") — never silent.
//
// Channel-bearing traces also init the worker with the sample's resolved
// straight-alpha RGBA8 point colors; each rebin then returns a mean-color
// plane alongside the counts (LOD doc §2): per cell, the alpha-weighted mean
// point color averaged in linear light — the same law as the kernel's
// bin_2d_mean_color — so a standalone zoom keeps the surface wearing the
// data's own colors while count keeps driving only the alpha.
//
// The worker script travels inside the bundle and boots from a Blob URL (the
// standalone CSP allows worker-src blob:). Environments without workers (or a
// stricter CSP) fall back to the old stretched-overview behavior.
// ---------------------------------------------------------------------------

const XY_REBIN_WORKER_SRC = `
// sRGB byte -> linear-light (0..1); built once, mirrors the kernel's table.
const LIN = new Float64Array(256);
for (let i = 0; i < 256; i++) {
  const c = i / 255;
  LIN[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
const SRGB = (v) => {
  const c = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(c * 255)));
};
const DATA = new Map();
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === "init") {
    DATA.set(m.trace, {
      x: new Float64Array(m.x),
      y: new Float64Array(m.y),
      rgba: m.rgba ? new Uint8Array(m.rgba) : null,
    });
    return;
  }
  const d = DATA.get(m.trace);
  if (!d) return;
  const w = m.w, h = m.h;
  const grid = new Float32Array(w * h);
  const sums = d.rgba ? new Float64Array(w * h * 4) : null; // aR, aG, aB, sum(a)
  const sx = w / ((m.x1 - m.x0) || 1);
  const sy = h / ((m.y1 - m.y0) || 1);
  let max = 0;
  const X = d.x, Y = d.y, C = d.rgba, n = X.length;
  for (let i = 0; i < n; i++) {
    const cx = (X[i] - m.x0) * sx;
    const cy = (Y[i] - m.y0) * sy;
    if (cx < 0 || cy < 0 || cx >= w || cy >= h) continue;
    const cell = (cy | 0) * w + (cx | 0);
    const v = ++grid[cell];
    if (v > max) max = v;
    if (sums) {
      const a = C[i * 4 + 3];
      sums[cell * 4] += a * LIN[C[i * 4]];
      sums[cell * 4 + 1] += a * LIN[C[i * 4 + 1]];
      sums[cell * 4 + 2] += a * LIN[C[i * 4 + 2]];
      sums[cell * 4 + 3] += a;
    }
  }
  let rgba = null;
  if (sums) {
    rgba = new Uint8Array(w * h * 4);
    for (let cell = 0; cell < w * h; cell++) {
      const count = grid[cell];
      const weight = sums[cell * 4 + 3];
      if (!(count > 0) || !(weight > 0)) continue;
      rgba[cell * 4] = SRGB(sums[cell * 4] / weight);
      rgba[cell * 4 + 1] = SRGB(sums[cell * 4 + 1] / weight);
      rgba[cell * 4 + 2] = SRGB(sums[cell * 4 + 2] / weight);
      rgba[cell * 4 + 3] = Math.min(255, Math.round(weight / count));
    }
  }
  self.postMessage(
    { type: "grid", seq: m.seq, trace: m.trace, w, h, max,
      x0: m.x0, x1: m.x1, y0: m.y0, y1: m.y1, grid: grid.buffer,
      rgba: rgba ? rgba.buffer : null },
    rgba ? [grid.buffer, rgba.buffer] : [grid.buffer]
  );
};
`;

export function xyCreateRebinWorker() {
  try {
    const url = URL.createObjectURL(
      new Blob([XY_REBIN_WORKER_SRC], { type: "application/javascript" })
    );
    const worker = new Worker(url);
    (worker as any)._fcUrl = url; // revoked on terminate (destroy)
    return worker;
  } catch (e) {
    return null; // no Worker/blob support: keep the stretched overview
  }
}
