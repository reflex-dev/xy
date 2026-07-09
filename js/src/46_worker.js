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
// The worker script travels inside the bundle and boots from a Blob URL (the
// standalone CSP allows worker-src blob:). Environments without workers (or a
// stricter CSP) fall back to the old stretched-overview behavior.
// ---------------------------------------------------------------------------

const FC_REBIN_WORKER_SRC = `
const DATA = new Map();
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === "init") {
    DATA.set(m.trace, { x: new Float64Array(m.x), y: new Float64Array(m.y) });
    return;
  }
  const d = DATA.get(m.trace);
  if (!d) return;
  const w = m.w, h = m.h;
  const grid = new Float32Array(w * h);
  const sx = w / ((m.x1 - m.x0) || 1);
  const sy = h / ((m.y1 - m.y0) || 1);
  let max = 0;
  const X = d.x, Y = d.y, n = X.length;
  for (let i = 0; i < n; i++) {
    const cx = (X[i] - m.x0) * sx;
    const cy = (Y[i] - m.y0) * sy;
    if (cx < 0 || cy < 0 || cx >= w || cy >= h) continue;
    const v = ++grid[(cy | 0) * w + (cx | 0)];
    if (v > max) max = v;
  }
  self.postMessage(
    { type: "grid", seq: m.seq, trace: m.trace, w, h, max,
      x0: m.x0, x1: m.x1, y0: m.y0, y1: m.y1, grid: grid.buffer },
    [grid.buffer]
  );
};
`;

function fcCreateRebinWorker() {
  try {
    const url = URL.createObjectURL(
      new Blob([FC_REBIN_WORKER_SRC], { type: "application/javascript" })
    );
    const worker = new Worker(url);
    worker._fcUrl = url; // revoked on terminate (destroy)
    return worker;
  } catch (e) {
    return null; // no Worker/blob support: keep the stretched overview
  }
}
