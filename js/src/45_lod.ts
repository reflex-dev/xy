import { parseColor } from "./20_theme";

// ---------------------------------------------------------------------------

const LOD_DIRECT_POINT_BUDGET = 200000;
const LOD_DRILL_EXIT_FACTOR = 1.15;
// Retired exact point windows kept per trace (T13), beyond the live drill.
// Each holds ≤ budget points of GPU buffers, so the cap bounds VRAM; the
// outgrown sweep (T11 rule) frees entries geometry can no longer revive.
const LOD_POINT_CACHE_WINDOWS = 3;
// Retained-sample zoom-out fade band (T9): full alpha while the sample's home
// window still covers ≥ HI of the view area, gone below LO (log-eased between,
// applied as composited opacity — see lodSampleViewAlpha).
const LOD_SAMPLE_FADE_COVER_HI = 1 / 4;
const LOD_SAMPLE_FADE_COVER_LO = 1 / 32;
// View-dependent LOD machinery (§5/§28) — chart-agnostic.
//
// Everything a tiered trace needs client-side, factored out of ChartView so a
// future heatmap/histogram tier reuses it instead of copy-pasting: the drill
// lifecycle (apply/refresh/dying/drop with entry+exit fades — restarting the
// entry fade per refresh, or dropping instantly, both read as flashing), the
// multi-window density-source cache, texture crossfades, and the eased
// "exposure" normalization. Functions take the owning ChartView as `view` and
// keep per-trace state on the trace's gpu record `g`; rendering stays in
// ChartView (lod calls back through view._drawDensity/_drawPoints so tests
// and future chart kinds can intercept/override the mark renderer).
// ---------------------------------------------------------------------------

function lodFade(view, start, duration = 140) {
  if (start === undefined || start === null || duration <= 0 || view._prefersReducedMotion()) {
    return 1;
  }
  const t = Math.min(1, Math.max(0, (view._now() - start) / duration));
  return t * t * (3 - 2 * t);
}

// Quantized wire (density grids as log-encoded u8, ~4x smaller): decode back
// to approximate counts so exposure normalization and re-encodes work
// unchanged. The final texture is 8-bit log anyway, so the round-trip is
// visually exact; decode is deterministic (no RNG/time).
export function lodDecodeLogU8(buf, maxVal) {
  const u8 = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  const out = new Float32Array(u8.length);
  const denom = Math.log1p(Math.max(0, maxVal || 0));
  if (denom > 0) {
    for (let i = 0; i < u8.length; i++) {
      if (u8[i] > 0) out[i] = Math.expm1((u8[i] / 255) * denom);
    }
  }
  return out;
}

export function lodCopyGrid(f32) {
  return f32.slice ? f32.slice() : new Float32Array(f32);
}

// Log tone-mapped grid upload: stable perception across renormalization, and
// the u_max swings between rebins compress logarithmically (§5/§F6).
//
// Count-only grids upload as R8 (the shader tints/LUTs them). Mean-color
// grids (LOD doc §2) pass the straight-alpha RGBA plane shipped by the
// kernel: rgb = per-cell mean point color, a = mean point alpha. The texture
// bakes the count tone curve into the alpha and stores rgb PREMULTIPLIED —
// in sRGB space, exactly like the mark shaders' outputs — so bilinear
// filtering weights color by coverage instead of dragging occupied cells
// toward transparent-black neighbors. Exposure easing re-calls this per
// norm step; rgb is re-premultiplied against the eased alpha each time.
// `filter` picks the sampling the reply asked for (spatial-exact grids ship
// "nearest"); it applies to both texture layouts.
export function lodWriteGridTexture(gl, tex, f32, w, h, maxVal, rgba = null, filter = "linear") {
  const denom = Math.log1p(Math.max(0, maxVal || 0));
  let data;
  if (rgba) {
    data = new Uint8Array(f32.length * 4);
    if (denom > 0) {
      for (let i = 0; i < f32.length; i++) {
        const c = f32[i];
        if (!(c > 0) || !Number.isFinite(c)) continue;
        const t = Math.min(1, Math.log1p(c) / denom);
        const shaped = Math.min(1, t * 1.35) * (rgba[i * 4 + 3] / 255);
        if (shaped <= 0) continue;
        const a = Math.max(1, Math.round(255 * shaped));
        data[i * 4] = Math.round(rgba[i * 4] * a / 255);
        data[i * 4 + 1] = Math.round(rgba[i * 4 + 1] * a / 255);
        data[i * 4 + 2] = Math.round(rgba[i * 4 + 2] * a / 255);
        data[i * 4 + 3] = a;
      }
    }
  } else {
    data = new Uint8Array(f32.length);
    if (denom > 0) {
      for (let i = 0; i < f32.length; i++) {
        const c = f32[i];
        if (c > 0 && Number.isFinite(c)) {
          data[i] = Math.max(1, Math.min(255, Math.round(255 * Math.log1p(c) / denom)));
        }
      }
    }
  }
  gl.bindTexture(gl.TEXTURE_2D, tex);
  const align = gl.getParameter(gl.UNPACK_ALIGNMENT);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  if (rgba) {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
  } else {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data);
  }
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, align);
  // "nearest" for a full-screen-resolution grid (exact deep-zoom detail — crisp,
  // no interpolation bleed); "linear" (default) smooths an upsampled aggregate.
  const gf = filter === "nearest" ? gl.NEAREST : gl.LINEAR;
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gf);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gf);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
}

// Treat the color scale like exposure: brighten slowly on drill-in so a
// smaller aggregate tile does not suddenly go hot, but recover faster when
// the incoming tile needs more headroom to avoid clipping.
function lodNormMax(g, nextMax) {
  if (!Number.isFinite(nextMax) || nextMax <= 0) {
    g.densityNormMax = 0;
    return 0;
  }
  const prev = Number.isFinite(g.densityNormMax) && g.densityNormMax > 0
    ? g.densityNormMax
    : nextMax;
  const norm = nextMax > prev
    ? prev * 0.3 + nextMax * 0.7
    : Math.max(nextMax, prev * 0.86);
  g.densityNormMax = norm;
  return norm;
}

function lodStartNormAnim(view, g, start, target) {
  if (!g.density || !g.density.grid || !Number.isFinite(target) || target <= 0) {
    g._densityNormAnim = null;
    return;
  }
  const ratio = Math.abs(Math.log(Math.max(start, 1e-12) / Math.max(target, 1e-12)));
  if (view._prefersReducedMotion() || ratio < 0.02) {
    g._densityNormAnim = null;
    g.density.normMax = target;
    g.densityNormMax = target;
    lodWriteGridTexture(
      view.gl, g.density.tex, g.density.grid, g.density.w, g.density.h, target,
      g.density.rgba, g.density.filter,
    );
    return;
  }
  g._densityNormAnim = {
    start,
    target,
    startedAt: view._now(),
    duration: target < start ? 420 : 260,
  };
}

function lodStepNorm(view, g) {
  const anim = g._densityNormAnim;
  const d = g.density;
  if (!anim || !d || !d.grid || !d.tex) return;
  const t = Math.min(1, Math.max(0, (view._now() - anim.startedAt) / anim.duration));
  const k = t * t * (3 - 2 * t);
  const norm = anim.start + (anim.target - anim.start) * k;
  const prev = d.normMax || 0;
  const rel = Math.abs(norm - prev) / Math.max(Math.abs(norm), Math.abs(prev), 1);
  if (rel > 0.004 || t >= 1) {
    d.normMax = norm;
    g.densityNormMax = norm;
    lodWriteGridTexture(view.gl, d.tex, d.grid, d.w, d.h, norm, d.rgba, d.filter);
  }
  if (t < 1) {
    view.draw();
    return;
  }
  d.normMax = anim.target;
  g.densityNormMax = anim.target;
  g._densityNormAnim = null;
}

// -- density-source cache (multi-window LOD cache, §10) ----------------------

function lodDensityArea(d) {
  return Math.abs((d.xRange[1] - d.xRange[0]) * (d.yRange[1] - d.yRange[0]));
}

function lodWindowArea(win) {
  if (!win) return 0;
  return Math.abs((win.x1 - win.x0) * (win.y1 - win.y0));
}

function lodWindowCenterInside(win, view) {
  if (!win || !view) return false;
  const cx = (view.x0 + view.x1) / 2;
  const cy = (view.y0 + view.y1) / 2;
  return (
    cx >= Math.min(win.x0, win.x1) &&
    cx <= Math.max(win.x0, win.x1) &&
    cy >= Math.min(win.y0, win.y1) &&
    cy <= Math.max(win.y0, win.y1)
  );
}

// §28 hybrid overlay, zoom-out bound (T9): the retained sample is
// representative of *its* window only. Once the view grows far past that
// window, the same ~8k points compress into a small screen region and
// overplot into a solid false cluster (the zoom-out "stuck point blob") —
// at that scale the aggregate alone is truthful. Zoom-out density replies
// intentionally ship no replacement sample (pyramid and integral-image
// servers alike, #24), so the client must bound the retained overlay itself:
// fade it with the window's share of the view area, from full alpha at
// COVER_HI down to hidden at COVER_LO. Log-eased so a continuous zoom reads
// as a linear fade; a pure function of (view, overlay), so every zoom frame
// re-derives it — no state, no extra frames to schedule. Pans and mild
// zoom-outs stay above the band and keep the hybrid "density + points" look.
//
// The band value is a *composited* opacity target, not a per-point alpha:
// mid-band the window's screen footprint has shrunk enough that many points
// land on each pixel, and alpha-compositing k overplotted layers of per-point
// alpha a reads as 1-(1-a)^k — at k≈10 even a=0.2 renders a near-opaque slab
// (the field failure that motivated this: a fading sample that never *looked*
// faded). Invert that: estimate k from the drawn count, mean point footprint,
// and the window's on-screen area, and solve a = 1-(1-band)^(1/k) so the
// stack composites to ≈band regardless of compression. k≤1 (points still
// distinguishable) degenerates to a=band exactly.
function lodSampleViewAlpha(view, s) {
  const win = s.win;
  const v = view.view;
  const viewArea = Math.abs((v.x1 - v.x0) * (v.y1 - v.y0));
  const winArea = lodWindowArea(win);
  if (!Number.isFinite(viewArea) || viewArea <= 0) return 1;
  if (!Number.isFinite(winArea) || winArea <= 0) return 0;
  const cover = winArea / viewArea;
  if (cover >= LOD_SAMPLE_FADE_COVER_HI) return 1;
  if (cover <= LOD_SAMPLE_FADE_COVER_LO) return 0;
  const band =
    Math.log(cover / LOD_SAMPLE_FADE_COVER_LO) /
    Math.log(LOD_SAMPLE_FADE_COVER_HI / LOD_SAMPLE_FADE_COVER_LO);
  // Expected overplot: drawn points × mean point footprint ÷ the window's
  // on-screen pixel area (CSS px on both sides, so dpr cancels). Continuous
  // size uses the midpoint of its pixel range — an estimate is all the
  // perceptual correction needs.
  const plot = view.plot || {};
  const fx = Math.abs(win.x1 - win.x0) / Math.max(Math.abs(v.x1 - v.x0), 1e-12);
  const fy = Math.abs(win.y1 - win.y0) / Math.max(Math.abs(v.y1 - v.y0), 1e-12);
  const winScreenArea = fx * (plot.w || 0) * fy * (plot.h || 0);
  if (!(winScreenArea > 0)) return 0;
  const dia = s.sizeMode === 1 && s.sizeRange
    ? (s.sizeRange[0] + s.sizeRange[1]) / 2
    : s.size || 4;
  const k = (s.n * Math.PI * dia * dia) / (4 * winScreenArea);
  return k > 1 ? 1 - Math.pow(1 - band, 1 / k) : band;
}

// #225 resolvability gate: a sample overlay draws only when the view it
// would describe could plausibly be points-tier — the estimated in-view
// count (the overlay's recorded window count, scaled by the view's share of
// its window) fits the direct budget. Above that, a fixed-size sample reads
// as individual data points at a zoom where real points are sub-pixel:
// sampling above the resolution of the graph misrepresents the dataset, and
// the aggregate surface — which wears the data's own colors (LOD doc §2) —
// is the truthful representation. In kernel mode the gate makes the hybrid
// look transient at most (real points ship the moment a window fits the
// budget); standalone exports keep the overlay as their only point
// representation once a zoom resolves it. Overlays without recorded counts
// (hand-built/legacy specs) keep drawing — the gate needs facts, not guesses.
function lodOverlayResolvable(view, o) {
  const meta = o.sample;
  if (!meta || !Number.isFinite(meta.visible)) return true;
  const v = view.view;
  const viewArea = Math.abs((v.x1 - v.x0) * (v.y1 - v.y0));
  const winArea = lodWindowArea(o.win);
  const share = winArea > 0 && viewArea > 0 ? Math.min(1, viewArea / winArea) : 1;
  return meta.visible * share <= LOD_DIRECT_POINT_BUDGET;
}

// §28 hybrid overlay, window pairing (T9): every sample rides the density
// window it was computed for, so the points on screen always describe the
// window being displayed. Selection mirrors lodDensityForView: the smallest
// cached window whose sample covers the whole view wins at full alpha (deep
// zoom-out lands on the overview sample — the point cloud comes back instead
// of a stale drilled cluster). Only when NO cached window covers the view
// (pan off-cache, zoom-out past home) does the best partial overlay draw,
// bounded by the T9 coverage fade so it can never read as a false cluster.
// Every candidate passes the #225 resolvability gate first: above the direct
// budget the aggregate stands alone.
export function lodSampleForView(view, g) {
  const cache = g.densityCache || (g.density ? [g.density] : []);
  let contained = null;
  let fallback = null;
  let fallbackAlpha = 0;
  const seen = new Set();
  for (const d of cache) {
    const o = d && d.overlay;
    if (!o || !o.n || !o.win || seen.has(o)) continue;
    seen.add(o);
    if (!lodOverlayResolvable(view, o)) continue;
    if (view._viewInside(o.win)) {
      if (!contained || lodWindowArea(o.win) < lodWindowArea(contained.win)) contained = o;
    } else if (view._viewOverlaps(o.win)) {
      const a = lodSampleViewAlpha(view, o);
      if (a > fallbackAlpha) { fallback = o; fallbackAlpha = a; }
    }
  }
  if (contained) return { overlay: contained, alpha: 1 };
  if (fallback && fallbackAlpha > 0) return { overlay: fallback, alpha: fallbackAlpha };
  return null;
}

function lodDensityForView(view, g) {
  const cache = g.densityCache || (g.density ? [g.density] : []);
  let best = null;
  let broadest = null;
  for (const d of cache) {
    if (!d || !d.tex) continue;
    if (!broadest || lodDensityArea(d) > lodDensityArea(broadest)) broadest = d;
    if (!view._viewInsideRange(d.xRange, d.yRange)) continue;
    if (!best || lodDensityArea(d) < lodDensityArea(best)) best = d;
  }
  return best || broadest || g.density;
}

// Finer-detail layer over the chosen backdrop (T13): when the view is not
// contained in any fine cached window, lodDensityForView falls back to the
// broadest texture — but a finer cached window usually still covers most of
// the view mid-pan/zoom, and drawing only the broad texture renders the
// frame at its blurriest exactly when the user is moving. Pick the
// smallest-area cached texture that overlaps the view meaningfully and is
// finer than the primary; the draw path paints it on top (GPU clips it to
// its window), so the region already fetched stays sharp while the request
// for the rest is in flight. Standard tile-pyramid behavior: a resolution
// seam at the window edge beats uniform blur.
const LOD_DENSITY_DETAIL_MIN_COVER = 0.05; // of the view area

function lodDensityDetailForView(view, g, primary) {
  if (!primary) return null;
  const cache = g.densityCache || [];
  const v = view.view;
  const vx0 = Math.min(v.x0, v.x1), vx1 = Math.max(v.x0, v.x1);
  const vy0 = Math.min(v.y0, v.y1), vy1 = Math.max(v.y0, v.y1);
  const viewArea = (vx1 - vx0) * (vy1 - vy0);
  if (!(viewArea > 0)) return null;
  const primaryArea = lodDensityArea(primary);
  let best = null;
  for (const d of cache) {
    if (!d || !d.tex || d === primary || d === g._densitySwitchPrev) continue;
    if (!(lodDensityArea(d) < primaryArea)) continue;
    const wx0 = Math.min(d.xRange[0], d.xRange[1]), wx1 = Math.max(d.xRange[0], d.xRange[1]);
    const wy0 = Math.min(d.yRange[0], d.yRange[1]), wy1 = Math.max(d.yRange[0], d.yRange[1]);
    const ox = Math.min(vx1, wx1) - Math.max(vx0, wx0);
    const oy = Math.min(vy1, wy1) - Math.max(vy0, wy0);
    if (ox <= 0 || oy <= 0 || (ox * oy) / viewArea < LOD_DENSITY_DETAIL_MIN_COVER) continue;
    if (!best || lodDensityArea(d) < lodDensityArea(best)) best = d;
  }
  return best;
}

// Density-side request elision (T13): skip the density_view round-trip when
// a cached texture is already as detailed as anything the kernel could
// return for this view. Two ways to qualify, both requiring the cached
// window to CONTAIN the view:
// - screen-resolution adequacy: the texture resolves at least one texel per
//   screen pixel of the current view (zoom-outs and pan-returns inside an
//   exact-scan grid);
// - source-resolution adequacy: the texture already sits at the trace's
//   finest attainable aggregate cell size (`min_cell`, pyramid-served
//   replies) — zooming further in cannot sharpen it, so re-requesting the
//   same blur is pure wire waste (the HAR behind this: repeated ~2.7 MB
//   grids per pan/zoom step at 200-450% on a 100M scatter).
// Guards keep the exact/drill regimes reachable: the estimated in-view count
// must sit clearly above the budget (the kernel would still answer with the
// pyramid, not an exact re-bin or points), and the view must not have dived
// more than MAX_AREA_RATIO below the cached window (the area estimate
// overshoots in sparse corners; a deep dive re-requests so the kernel can
// re-decide with real counts).
const LOD_DENSITY_ELIDE_EST_FACTOR = 2; // × LOD_DIRECT_POINT_BUDGET
const LOD_DENSITY_ELIDE_MAX_AREA_RATIO = 8; // cached-window area ÷ view area

export function lodDensityCacheServes(view, g, x0, x1, y0, y1, plotW, plotH) {
  const cache = g.densityCache || (g.density ? [g.density] : []);
  const vx0 = Math.min(x0, x1), vx1 = Math.max(x0, x1);
  const vy0 = Math.min(y0, y1), vy1 = Math.max(y0, y1);
  const vSpanX = vx1 - vx0, vSpanY = vy1 - vy0;
  if (!(vSpanX > 0 && vSpanY > 0 && plotW > 0 && plotH > 0)) return false;
  const needX = vSpanX / plotW, needY = vSpanY / plotH;
  const ex = vSpanX * 1e-4, ey = vSpanY * 1e-4;
  for (const d of cache) {
    if (!d || !d.tex || !d.xRange || !d.yRange || !(d.w > 0) || !(d.h > 0)) continue;
    const wx0 = Math.min(d.xRange[0], d.xRange[1]), wx1 = Math.max(d.xRange[0], d.xRange[1]);
    const wy0 = Math.min(d.yRange[0], d.yRange[1]), wy1 = Math.max(d.yRange[0], d.yRange[1]);
    if (vx0 < wx0 - ex || vx1 > wx1 + ex || vy0 < wy0 - ey || vy1 > wy1 + ey) continue;
    const winArea = (wx1 - wx0) * (wy1 - wy0);
    if (winArea > vSpanX * vSpanY * LOD_DENSITY_ELIDE_MAX_AREA_RATIO) continue;
    const cellX = (wx1 - wx0) / d.w, cellY = (wy1 - wy0) / d.h;
    const mc = d.minCell;
    if (cellX > Math.max(needX, mc ? mc[0] : 0) * 1.001) continue;
    if (cellY > Math.max(needY, mc ? mc[1] : 0) * 1.001) continue;
    // Unknown counts never elide: the kernel must stay free to choose a
    // sharper representation (exact re-bin, points) the moment it can.
    if (!Number.isFinite(d.visible) || !(d.visible > 0)) continue;
    const est = d.visible * Math.min(1, (vSpanX * vSpanY) / winArea);
    if (est <= LOD_DIRECT_POINT_BUDGET * LOD_DENSITY_ELIDE_EST_FACTOR) continue;
    return true;
  }
  return false;
}

// The hold's density estimate, reused by retirement (T11): scale the drill
// window's known count by the target window's area to predict whether that
// window could still be answered with direct points.
function lodEstimatedVisible(d, win) {
  const drillArea = lodWindowArea(d.win);
  const winArea = lodWindowArea(win);
  if (!Number.isFinite(drillArea) || !Number.isFinite(winArea) || drillArea <= 0) return NaN;
  const baseVisible = Number.isFinite(d.visible) ? d.visible : d.n;
  if (!Number.isFinite(baseVisible) || baseVisible <= 0) return NaN;
  return baseVisible * Math.max(1, winArea / drillArea);
}

function lodHoldPendingDrill(view, g, d) {
  const pending = g._lodPendingView;
  if (!d || !pending || g._drillDying) return false;
  if (g._lodPendingSeq !== view.seq) return false;
  if (g._lodPendingAt && view._now() - g._lodPendingAt > 1200) return false;
  if (!lodWindowCenterInside(d.win, pending)) return false;
  const estimatedVisible = lodEstimatedVisible(d, pending);
  if (!Number.isFinite(estimatedVisible)) return false;
  return estimatedVisible <= LOD_DIRECT_POINT_BUDGET * LOD_DRILL_EXIT_FACTOR;
}

// Zoom-in request elision (T12): a drill that shipped its window EXACTLY
// (reduction "none" — the subset IS every point in the window) already holds
// every point of any view contained in that window, so drilling deeper needs
// no kernel round-trip. What a deeper zoom eventually needs is precision, not
// data: the shipped geometry is f32, offset-encoded around the window midpoint
// (§16), so once the view span drops below LOD_DRILL_REENCODE_SPAN of the
// window span on either axis one request goes out purely to re-center the
// encoding (at 2^-8 of the window the ~2^-24 encode quantum is still ≲0.1 px
// on a 4k-wide plot). A dying drill never elides — the kernel chose a
// different representation and the reply flow owns that transition.
const LOD_DRILL_REENCODE_SPAN = 1 / 256;

// Containment + §16 re-encode depth bound, shared by the live drill and the
// retired point-window cache (T13): an exact window answers any view it
// contains, until the zoom outgrows the f32 offset encoding.
function lodWindowServesView(win, x0, x1, y0, y1) {
  const vx0 = Math.min(x0, x1), vx1 = Math.max(x0, x1);
  const vy0 = Math.min(y0, y1), vy1 = Math.max(y0, y1);
  const wx0 = Math.min(win.x0, win.x1), wx1 = Math.max(win.x0, win.x1);
  const wy0 = Math.min(win.y0, win.y1), wy1 = Math.max(win.y0, win.y1);
  // Same edge tolerance as _viewInside: f32 round-trip slop at the window
  // boundary must not force a request right after drilling in.
  const ex = (vx1 - vx0) * 1e-4, ey = (vy1 - vy0) * 1e-4;
  if (vx0 < wx0 - ex || vx1 > wx1 + ex || vy0 < wy0 - ey || vy1 > wy1 + ey) return false;
  return (
    vx1 - vx0 >= (wx1 - wx0) * LOD_DRILL_REENCODE_SPAN &&
    vy1 - vy0 >= (wy1 - wy0) * LOD_DRILL_REENCODE_SPAN
  );
}

export function lodDrillServesView(g, x0, x1, y0, y1) {
  const d = g && g.drill;
  if (!d || !d.exact || !d.win || g._drillDying) return false;
  return lodWindowServesView(d.win, x0, x1, y0, y1);
}

// Geometry-only retirement (T11): an entered-then-exited drill is kept as a
// revive cache — a rapid zoom back into its window hands the exact marks
// back with no kernel round-trip — but only while a nearby view could still
// plausibly be points-tier. Once the view outgrows the window past the drill
// budget, the kernel would answer density for anything around here, so the
// retained buffers can no longer serve a revive that survives; free them
// without waiting for a reply (zooming out with no kernel attached — or a
// coalesced-away reply — must not strand a drill's GPU buffers forever).
// Never-entered drills are exempt: they are prefetches en route to their
// window, and the view being far from it is their normal transient state.
function lodDrillOutgrown(view, g, d) {
  const v = view.view;
  const estimatedVisible = lodEstimatedVisible(d, v);
  if (!Number.isFinite(estimatedVisible)) return false;
  return estimatedVisible > LOD_DIRECT_POINT_BUDGET * LOD_DRILL_EXIT_FACTOR;
}

// Every density object still reachable from the trace, so eviction never
// deletes a texture that is about to be bound. Besides the active grid, the
// previous grid, and the crossfade source, `_shownDensity` (what the tier last
// drew — it becomes the next `_densitySwitchPrev`) and `_homeDensity` (the
// standalone overview restore point) are live too. Missing `_shownDensity` here
// let its texture be evicted while still referenced; the next crossfade bound
// the freed handle → "bindTexture: attempt to use a deleted object", a dropped
// density frame, and drilled points left stranded over a stale surface.
function lodDensityPinned(g, d) {
  return d === g.density || d === g.prevDensity || d === g._densitySwitchPrev ||
    d === g._shownDensity || d === g._homeDensity;
}

function lodSameDensityWindow(a, b) {
  if (!a || !b || !a.xRange || !b.xRange || !a.yRange || !b.yRange) return false;
  const eps =
    (Math.abs(a.xRange[1] - a.xRange[0]) + Math.abs(a.yRange[1] - a.yRange[0])) * 1e-9 + 1e-300;
  return Math.abs(a.xRange[0] - b.xRange[0]) <= eps && Math.abs(a.xRange[1] - b.xRange[1]) <= eps &&
    Math.abs(a.yRange[0] - b.yRange[0]) <= eps && Math.abs(a.yRange[1] - b.yRange[1]) <= eps;
}

export function lodRememberDensity(view, g, d) {
  if (!d || !d.tex) return;
  d._stamp = ++view._densityStamp;
  if (!g.densityCache) g.densityCache = [];
  if (!g.densityCache.includes(d)) {
    // A fresh grid for a window already cached supersedes its twin: same
    // coverage, newer facts (count, resolution, min_cell) — and request
    // elision reads those facts, so a stale twin must not shadow them.
    // Pinned twins (mid-crossfade, home) stay; eviction sweeps them later.
    for (let i = g.densityCache.length - 1; i >= 0; i--) {
      const old = g.densityCache[i];
      if (old === d || lodDensityPinned(g, old) || !lodSameDensityWindow(old, d)) continue;
      g.densityCache.splice(i, 1);
      view.gl.deleteTexture(old.tex);
      if (old.overlay && old.overlay !== g.sampleOverlay) {
        view._destroySampleOverlay(old.overlay);
        old.overlay = null;
      }
    }
    g.densityCache.push(d);
  }
  const maxCached = 8;
  while (g.densityCache.length > maxCached) {
    let drop = -1;
    for (let i = 0; i < g.densityCache.length; i++) {
      const cand = g.densityCache[i];
      if (lodDensityPinned(g, cand)) continue;
      if (drop < 0) { drop = i; continue; }
      const dropArea = lodDensityArea(g.densityCache[drop]);
      const candArea = lodDensityArea(cand);
      if (candArea < dropArea || (candArea === dropArea && cand._stamp < g.densityCache[drop]._stamp)) {
        drop = i;
      }
    }
    if (drop < 0) break;
    const old = g.densityCache.splice(drop, 1)[0];
    if (!lodDensityPinned(g, old)) {
      view.gl.deleteTexture(old.tex);
      // The window's sample overlay rides its cache entry (T9 pairing) and
      // dies with it — except the home/init overlay, which the standalone
      // re-bin worker keeps as its CPU-side source.
      if (old.overlay && old.overlay !== g.sampleOverlay) {
        view._destroySampleOverlay(old.overlay);
        old.overlay = null;
      }
    }
  }
}

// -- point-window cache (T13) -------------------------------------------------
//
// Retired exact drills, LRU per trace. "Once we get points, we can render
// anything inside there without further requests": a view covered by any
// cached full-point window promotes it back to the live drill with no wire
// round-trip. The cache pairs with the kernel's padded ALIGNED windows —
// consecutive pans resolve to the same aligned bounds, so windows crossed
// once are held, and ping-pong pans/zooms across a boundary re-render from
// the cache instead of re-shipping ~all the same points.

function lodSameWindow(a, b) {
  if (!a || !b) return false;
  const eps = (Math.abs(a.x1 - a.x0) + Math.abs(a.y1 - a.y0)) * 1e-9 + 1e-300;
  return Math.abs(a.x0 - b.x0) <= eps && Math.abs(a.x1 - b.x1) <= eps &&
    Math.abs(a.y0 - b.y0) <= eps && Math.abs(a.y1 - b.y1) <= eps;
}

function lodFreeDrillBuffers(view, d) {
  const gl = view.gl;
  view._deleteVaos(d); // each drill object carries its own VAOs
  for (const b of [d.xBuf, d.yBuf, d.cBuf, d.rgbaBuf, d.sBuf, d.styleBuf,
    d.strokeBuf, d.selBuf, d.dBuf]) if (b) gl.deleteBuffer(b);
}

// Reset the trace's drill lifecycle state without touching the (moved or
// freed) drill object itself — shared by drop, retire, and promote.
function lodClearDrillState(view, g) {
  g.drill = null;
  g._drillFadeStart = null;
  g._drillExitFadeStart = null;
  g._drillWasInside = false;
  g._drillEverInside = false;
  g._drillShownAlpha = null;
  g._drillDying = false;
  g._drillDiedInsideWin = false;
  g._drillBackdropShown = 1; // next drill enters over a full backdrop (T10)
  g._drillBackdropTick = 0;
  view._hoverId = -1; // drilled indices are dead; don't reuse a cached row
  view._lastRow = null;
  // The freed drill may have been the only pickable geometry (a density-only
  // chart): retract the modebar Select trigger with the capability.
  view._updatePickable();
}

// Move the live drill into the retired-window cache. Only an exact subset can
// serve future views (Invariant L2), so anything else frees instead.
function lodRetireDrill(view, g) {
  const d = g.drill;
  if (!d) return;
  if (!d.exact || !d.win) {
    lodDropDrill(view, g);
    return;
  }
  if (!g.drillCache) g.drillCache = [];
  // A re-shipped window replaces its stale cached twin instead of duplicating.
  for (let i = g.drillCache.length - 1; i >= 0; i--) {
    if (lodSameWindow(g.drillCache[i].win, d.win)) {
      lodFreeDrillBuffers(view, g.drillCache.splice(i, 1)[0]);
    }
  }
  g.drillCache.push(d);
  while (g.drillCache.length > LOD_POINT_CACHE_WINDOWS) {
    lodFreeDrillBuffers(view, g.drillCache.shift());
  }
  lodClearDrillState(view, g);
}

export function lodDropPointCache(view, g) {
  for (const d of g.drillCache || []) lodFreeDrillBuffers(view, d);
  g.drillCache = null;
}

// A retired cached window that covers the view swaps back in as the live
// drill — the pan-back / zoom-ping-pong "render anything inside there" path
// (T13). Alpha-continuous like a revive: the swap hands marks over at the
// alpha currently on screen, and any active brush mask re-derives locally
// exactly as a fresh reply would (§34 continuity).
export function lodPromoteCachedDrill(view, g, x0, x1, y0, y1) {
  const cache = g.drillCache;
  if (!cache || !cache.length) return false;
  let pick = -1;
  for (let i = 0; i < cache.length; i++) {
    const e = cache[i];
    if (!e || !e.exact || !e.win || !lodWindowServesView(e.win, x0, x1, y0, y1)) continue;
    // Smallest covering window wins (mirrors lodDensityForView): tightest
    // offset encoding and the most local blend/density metadata.
    if (pick < 0 || lodWindowArea(e.win) < lodWindowArea(cache[pick].win)) pick = i;
  }
  if (pick < 0) return false;
  const e = cache.splice(pick, 1)[0];
  const shownAlpha = g.drill ? lodDrillShownAlpha(view, g) : 0;
  if (g.drill) {
    if (g._drillDying || !g.drill.exact) lodDropDrill(view, g);
    else lodRetireDrill(view, g);
  } else {
    lodClearDrillState(view, g);
  }
  g.drill = e;
  // Continuity across the swap: the promoted window's marks pick up at the
  // alpha the retired ones showed (the retired window's points are a subset/
  // superset over the same region — a restart-from-zero reads as a blink).
  g._drillShownAlpha = shownAlpha;
  lodEnterDrillContinuous(view, g);
  if (view._lastBrush && e._cpuX && e._cpuY) lodRestoreBrushMask(view, e, e._cpuX, e._cpuY);
  else e.selActive = false;
  view._updatePickable();
  view.draw();
  return true;
}

// -- drill lifecycle ----------------------------------------------------------

// The kernel decided this view fits the direct budget and shipped real marks
// (channels restored). Build/refresh a direct-shaped sibling on the tiered
// trace; the tier draw uses it until the kernel switches back.
export function lodApplyDrill(view, g, upd, buffers) {
  const gl = view.gl;
  const win = {
    x0: upd.x_range[0], x1: upd.x_range[1],
    y0: upd.y_range[0], y1: upd.y_range[1],
  };
  // A reply for a NEW window retires the old one into the point-window cache
  // (T13) instead of overwriting its buffers: the old window's points remain
  // exact for views inside it, so a pan back promotes them with no kernel
  // round-trip. The handoff is alpha-continuous below — a window-to-window
  // swap must not restart the entry fade (reads as flashing mid-pan).
  let handoff = null;
  if (g.drill && !lodSameWindow(g.drill.win, win)) {
    handoff = {
      shownAlpha: lodDrillShownAlpha(view, g),
      wasInside: g._drillWasInside,
      everInside: g._drillEverInside,
    };
    if (g._drillDying || !g.drill.exact) lodDropDrill(view, g);
    else lodRetireDrill(view, g);
  }
  const fresh = !g.drill && !handoff; // true aggregate→marks transition
  let d = g.drill;
  if (!d) {
    d = g.drill = { trace: g.trace, xBuf: gl.createBuffer(), yBuf: gl.createBuffer() };
  }
  d.trace = { ...g.trace, style: upd.style || g.trace.style || {} };
  d.xAxis = g.xAxis;
  d.yAxis = g.yAxis;
  const xs = view._asF32(buffers[upd.x.buf]);
  const ys = view._asF32(buffers[upd.y.buf]);
  gl.bindBuffer(gl.ARRAY_BUFFER, d.xBuf);
  gl.bufferData(gl.ARRAY_BUFFER, xs, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, d.yBuf);
  gl.bufferData(gl.ARRAY_BUFFER, ys, gl.STATIC_DRAW);
  d.xMeta = { offset: upd.x.offset, scale: upd.x.scale };
  d.yMeta = { offset: upd.y.offset, scale: upd.y.scale };
  d.win = win;
  d.n = Math.min(upd.x.len, upd.y.len);
  d.visible = upd.visible ?? d.n;
  // Encoded coordinates retained CPU-side (views over the reply frame, no
  // copy): a promoted cached window re-derives the brush mask from these,
  // exactly as this fresh reply does below (§34 continuity across T13 swaps).
  d._cpuX = xs;
  d._cpuY = ys;
  // The kernel's exactness claim (§28 Invariant L2): reduction "none" means
  // the subset IS every point in the window — the fact that arms T12's
  // zoom-in request elision. Anything else (or a reply that doesn't say)
  // keeps the request path live.
  d.exact = upd.reduction === "none";
  d.seq = upd.drill_seq; // subset version — echoed with picks, gates selections
  d.selActive = false; // drilled subset changed; old mask indices are stale
  // §34 selection continuity: the swapped subset invalidates the old mask
  // *indices*, but the brush geometry is still authoritative — re-derive the
  // mask from the decoded window coordinates so the highlight never blinks
  // out across a pan/zoom re-drill. The kernel's next selection reply (the
  // adapter's resync, or a fresh drag) remains the authoritative overwrite.
  lodRestoreBrushMask(view, d, xs, ys);
  // The point under the cursor is a different row now; a cached tooltip for
  // the same index would silently show the old point's values (§16).
  view._hoverId = -1;
  view._lastRow = null;
  d.colorMode = 0;
  d.color = parseColor(view.root, upd.color && upd.color.color, [0.3, 0.47, 0.66, 1]);
  if (upd.color && upd.color.buf !== undefined) {
    d.colorMode = upd.color.mode === "continuous" ? 1 :
      (upd.color.mode === "categorical" ? 2 : 3);
    const colorValues = upd.color.dtype === "u8"
      ? view._asU8(buffers[upd.color.buf])
      : view._asF32(buffers[upd.color.buf]);
    const colorBufferName = d.colorMode === 3 ? "rgbaBuf" : "cBuf";
    if (!d[colorBufferName]) d[colorBufferName] = gl.createBuffer();
    view._tagChannelBuf(d[colorBufferName], colorValues, d.colorMode === 1);
    gl.bindBuffer(gl.ARRAY_BUFFER, d[colorBufferName]);
    gl.bufferData(gl.ARRAY_BUFFER, colorValues, gl.STATIC_DRAW);
    if (d.colorMode !== 3) {
      d.lut = upd.color.mode === "continuous"
        ? view._lut(upd.color.colormap)
        : view._paletteLut(upd.color.palette);
    }
  }
  d.sizeMode = 0;
  d.size = (upd.size && upd.size.size) || 4.0;
  d.sizeRange = [2, 18];
  if (upd.size && upd.size.mode === "continuous") {
    d.sizeMode = 1;
    const sizeValues = upd.size.dtype === "u8"
      ? view._asU8(buffers[upd.size.buf])
      : view._asF32(buffers[upd.size.buf]);
    if (!d.sBuf) d.sBuf = gl.createBuffer();
    view._tagChannelBuf(d.sBuf, sizeValues, true);
    gl.bindBuffer(gl.ARRAY_BUFFER, d.sBuf);
    gl.bufferData(gl.ARRAY_BUFFER, sizeValues, gl.STATIC_DRAW);
    d.sizeRange = upd.size.range_px;
  }
  const styleChannel = (name) => upd.channels && upd.channels[name];
  const artistScalar = Number(d.trace.style && d.trace.style.artist_alpha);
  if (styleChannel("opacity") || styleChannel("artist_alpha") ||
      styleChannel("stroke_width") || styleChannel("symbol") || Number.isFinite(artistScalar)) {
    const values = new Float32Array(d.n * 4);
    for (let i = 0; i < d.n; i++) {
      values[i * 4] = 1;
      values[i * 4 + 1] = Number.isFinite(artistScalar) ? artistScalar : -1;
      values[i * 4 + 2] = -1;
      values[i * 4 + 3] = -1;
    }
    const copy = (name, component, scale = 1) => {
      const spec = styleChannel(name);
      if (!spec) return;
      const source = spec.dtype === "u8"
        ? view._asU8(buffers[spec.buf])
        : view._asF32(buffers[spec.buf]);
      const components = spec.components || 1;
      for (let i = 0; i < d.n; i++) values[i * 4 + component] = source[i * components] * scale;
    };
    copy("opacity", 0);
    copy("artist_alpha", 1);
    copy("stroke_width", 2, view.dpr);
    copy("symbol", 3);
    if (!d.styleBuf) d.styleBuf = gl.createBuffer();
    d.styleBuf._fcType = gl.FLOAT;
    gl.bindBuffer(gl.ARRAY_BUFFER, d.styleBuf);
    gl.bufferData(gl.ARRAY_BUFFER, values, gl.STATIC_DRAW);
  }
  if (upd.stroke && upd.stroke.mode === "direct_rgba") {
    const values = view._asU8(buffers[upd.stroke.buf]);
    if (!d.strokeBuf) d.strokeBuf = gl.createBuffer();
    d.strokeBuf._fcType = gl.UNSIGNED_BYTE;
    gl.bindBuffer(gl.ARRAY_BUFFER, d.strokeBuf);
    gl.bufferData(gl.ARRAY_BUFFER, values, gl.STATIC_DRAW);
  }
  view._pointMarkStyle(d, d.trace);
  // Intensity-continuous handoff (§5): per-point local log-density + a blend
  // weight. The density surface already wears the mean point color (LOD doc
  // §2), so hue is continuous by construction; fresh at the boundary
  // (blend≈1) each mark enters at its cell's count-alpha and deeper zooms
  // ship smaller blends, easing marks to native opacity.
  if (upd.density_val && upd.density_val.buf !== undefined) {
    const dvalValues = upd.density_val.dtype === "u8"
      ? view._asU8(buffers[upd.density_val.buf])
      : view._asF32(buffers[upd.density_val.buf]);
    if (!d.dBuf) d.dBuf = gl.createBuffer();
    view._tagChannelBuf(d.dBuf, dvalValues, true);
    gl.bindBuffer(gl.ARRAY_BUFFER, d.dBuf);
    gl.bufferData(gl.ARRAY_BUFFER, dvalValues, gl.STATIC_DRAW);
    const first = d.lodBlend === undefined;
    d.lodBlend = Math.min(1, upd.lod_blend ?? 0);
    // The kernel's blend weight assumes level-by-level zooms; a fast zoom
    // skips levels and the first marks land with a mostly-native weight —
    // a visible intensity pop at the texture→marks swap. The BOUNDARY is the
    // transition itself: fresh marks appear at the aggregate's count-alpha
    // (blend 1) and the tween eases them to the kernel's weight, so the swap
    // never pops regardless of how many levels the zoom skipped (§5).
    d._lodBlendNative = d.lodBlend;
    if (fresh) d.lodBlendShown = 1;
    else if (first) d.lodBlendShown = d.lodBlend; // no tween-from-zero on refresh
  } else {
    d.lodBlend = 0;
    d._lodBlendNative = 0;
  }
  // The entry fade runs ONLY on the aggregate→marks transition. Restarting it
  // on every refresh made the marks blink to ~0 alpha after each kernel
  // reply — a steady flash while zooming within a drilled view.
  if (fresh) {
    g._drillFadeStart = view._now();
    g._drillWasInside = false;
    g._drillEverInside = false;
    g._drillShownAlpha = 0;
    g._drillExitFadeStart = null;
    g._drillDying = false;
    g._drillDiedInsideWin = false;
    return;
  }
  // Window-to-window swap (the old window retired into the point cache):
  // marks continue from the alpha the retired window showed — the two windows
  // agree on every shared point, so a restart-from-zero reads as a blink.
  if (handoff) {
    g._drillWasInside = handoff.wasInside;
    g._drillEverInside = handoff.everInside;
    g._drillShownAlpha = handoff.shownAlpha;
    g._drillDying = false;
    g._drillDiedInsideWin = false;
    lodEnterDrillContinuous(view, g);
    return;
  }
  // A live points reply revives a dying/exiting drill (hysteresis flip or a
  // fast zoom back in): hand the marks back at their CURRENT alpha — neither
  // fighting the exit fade nor snapping to full.
  if (g._drillDying || g._drillExitFadeStart != null) {
    lodEnterDrillContinuous(view, g);
  }
  g._drillDying = false;
  g._drillDiedInsideWin = false;
}

// Provisional selection mask for a freshly shipped drill subset, derived
// locally from the retained data-space brush (box or lasso). Exact for range
// predicates — the same containment test the kernel runs (§34 Tier A) — so
// the eventual kernel mask is a no-op overwrite, not a correction.
function lodRestoreBrushMask(view, d, xs, ys) {
  const b = view._lastBrush;
  if (!b || !d.n) return;
  const ox = d.xMeta.offset, sx = d.xMeta.scale || 1;
  const oy = d.yMeta.offset, sy = d.yMeta.scale || 1;
  const mask = new Float32Array(d.n);
  if (b.mode === "box") {
    for (let i = 0; i < d.n; i++) {
      const x = xs[i] / sx + ox, y = ys[i] / sy + oy;
      if (x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1) mask[i] = 1;
    }
  } else if (b.mode === "poly" && Array.isArray(b.points) && b.points.length >= 3) {
    const pts = b.points;
    for (let i = 0; i < d.n; i++) {
      const x = xs[i] / sx + ox, y = ys[i] / sy + oy;
      let hit = false;
      for (let a = 0, z = pts.length - 1; a < pts.length; z = a++) {
        const [xa, ya] = pts[a], [xz, yz] = pts[z];
        if ((ya > y) !== (yz > y) && x < ((xz - xa) * (y - ya)) / (yz - ya) + xa) hit = !hit;
      }
      if (hit) mask[i] = 1;
    }
  } else {
    return;
  }
  view._applySelMask(d, mask);
}

export function lodDropDrill(view, g) {
  const d = g.drill;
  if (!d) return;
  lodFreeDrillBuffers(view, d);
  lodClearDrillState(view, g);
}

// A density update arrived while drilled: don't drop the marks instantly
// (that hard-cuts the exit fade — a visible flash on drill-out). Mark the
// drill dying; the tier draw fades it over the incoming aggregate and frees
// it when the fade completes. Records whether the view was inside the drill
// window at death: if it was, the kernel explicitly chose density FOR this
// view (forced density / data change) and the revive path must not override
// it; if it wasn't, a fast zoom back in may revive the still-exact subset.
function lodMarkDrillDying(view, g) {
  if (!g.drill) return;
  g._drillDying = true;
  g._drillDiedInsideWin = view._viewInside(g.drill.win);
  // Seed the exit clock continuously with the currently shown alpha —
  // marks that had already faded out must not claim to be fully visible.
  lodBeginDrillExitContinuous(view, g);
}

function lodDrillExitFade(view, g) {
  if (g._drillExitFadeStart === undefined || g._drillExitFadeStart === null) {
    g._drillExitFadeStart = view._now();
  }
  const fade = lodFade(view, g._drillExitFadeStart, LOD_EXIT_FADE_MS);
  if (fade >= 1) g._drillExitFadeStart = null;
  return fade;
}

// -- alpha-continuous hand-offs (rapid zoom in/out) ---------------------------
//
// Entering, exiting, re-entering, and reviving the marks state must all
// continue from the marks alpha CURRENTLY on screen. Restarting a fade at an
// endpoint on every boundary crossing is exactly what rapid zoom in/out does
// to a naive fade pair — and it reads as flicker. smoothstep is ~linear
// mid-range, so mirroring t linearly is visually exact at these durations.

const LOD_ENTRY_FADE_MS = 140;
const LOD_EXIT_FADE_MS = 120;

// Exact inverse of smoothstep (s(t) = 3t^2 - 2t^3) via the trisection
// identity — a linear approximation compounds visible error at the fade
// ends when clocks hand off repeatedly under rapid zoom thrash.
function lodFadeInvert(alpha) {
  const a = Math.min(1, Math.max(0, alpha));
  return 0.5 - Math.sin(Math.asin(1 - 2 * a) / 3);
}

function lodDrillShownAlpha(view, g) {
  if (g._drillExitFadeStart != null) {
    return 1 - lodFade(view, g._drillExitFadeStart, LOD_EXIT_FADE_MS);
  }
  if (g._drillFadeStart != null) {
    return lodFade(view, g._drillFadeStart, LOD_ENTRY_FADE_MS);
  }
  // No clock running: the alpha the tier draw last put on screen (kept
  // explicitly — inferring it from other flags loses the memory across
  // apply/refresh hand-offs).
  if (g._drillShownAlpha != null) return g._drillShownAlpha;
  return g._drillWasInside ? 1 : 0;
}

// Switch to the entry (fade-in) clock, seeded so it starts at the shown alpha.
function lodEnterDrillContinuous(view, g) {
  // A revived/held drill eases back to its native intensity (the exit ramp
  // below may have retargeted the blend at the aggregate's count-alpha).
  if (g.drill && g.drill.dBuf && g.drill._lodBlendNative !== undefined) {
    g.drill.lodBlend = g.drill._lodBlendNative;
  }
  const alpha = lodDrillShownAlpha(view, g);
  g._drillShownAlpha = alpha;
  g._drillExitFadeStart = null;
  g._drillFadeStart =
    alpha >= 1 ? null : view._now() - LOD_ENTRY_FADE_MS * lodFadeInvert(alpha);
}

// Switch to the exit (fade-out) clock, seeded the same way.
function lodBeginDrillExitContinuous(view, g) {
  // Exit re-intensity (§5): dying/exiting marks converge to the aggregate's
  // local count-alpha as they fade, so they melt INTO the texture instead of
  // a differently-weighted cluster blinking out over it (hue already matches
  // — the texture wears the mean point color). The blend tween (τ=90ms) does
  // the easing; revives restore the native weight.
  if (g.drill && g.drill.dBuf) g.drill.lodBlend = 1;
  if (g._drillExitFadeStart != null) return; // already exiting — keep its clock
  const alpha = lodDrillShownAlpha(view, g);
  g._drillShownAlpha = alpha;
  g._drillFadeStart = null;
  g._drillExitFadeStart = view._now() - LOD_EXIT_FADE_MS * lodFadeInvert(1 - alpha);
}

// -- aggregate updates & tier drawing ----------------------------------------

// Apply a kernel "density"-mode update: new grid texture with eased exposure
// normalization, previous grid kept for the crossfade, source remembered in
// the per-trace cache.
export function lodApplyDensityUpdate(view, g, upd, buffers) {
  lodMarkDrillDying(view, g);
  const d = upd.density;
  const grid = d.enc === "log-u8"
    ? lodDecodeLogU8(buffers[d.buf], d.max)
    : lodCopyGrid(view._asF32(buffers[d.buf]));
  // Mean point color plane (LOD doc §2), copied because exposure easing
  // re-reads it on every norm step, after the wire buffer may be gone.
  const rgba = d.rgba !== undefined ? new Uint8Array(view._asU8(buffers[d.rgba])) : null;
  const normStart = lodNormMax(g, d.max);
  const normMax = view._prefersReducedMotion() ? d.max : normStart;
  g.densityNormMax = normMax;
  g.prevDensity = g.density;
  g._densityFadeStart = view._now();
  const filter = d.filter || "linear";
  g.density = {
    w: d.w, h: d.h, max: d.max, normMax, colormap: d.colormap || g.density.colormap,
    color: d.color ? parseColor(view.root, d.color, [0.3, 0.47, 0.66, 1]) : g.density.color,
    xRange: d.x_range, yRange: d.y_range,
    // Request-elision facts (T13): the window's point count, and — for
    // pyramid-served replies — the finest cell size this trace's aggregate
    // tier can attain, so lodDensityCacheServes knows when this texture is
    // already as sharp as a re-request could be.
    visible: upd.visible,
    minCell: Array.isArray(d.min_cell) ? d.min_cell : null,
    grid,
    rgba,
    filter,
    tex: view._uploadGrid(grid, d.w, d.h, normMax, rgba, filter),
    lut: g.density.lut,
  };
  // Exact scans include a view-specific sample and replace the overlay.
  // Pyramid responses intentionally omit one until tile-aware sampling lands;
  // preserve the retained deterministic sample in that case so the hybrid
  // overlay does not disappear after the first pan/zoom (#24). The draw path
  // already clips it to its recorded window.
  if (Object.prototype.hasOwnProperty.call(d, "sample")) {
    view._applyDensitySample(g, d.sample, buffers);
  }
  lodStartNormAnim(view, g, normMax, d.max);
  lodRememberDensity(view, g, g.density);
}

function lodDrawDensityWithFade(view, g, density, opacityScale = 1) {
  if (density !== g._shownDensity) {
    // Reversing a crossfade mid-flight (rapid alternation across two cached
    // windows) swaps the roles with a mirrored clock so both textures keep
    // their current alpha instead of popping to the endpoints.
    if (density === g._densitySwitchPrev && g._densitySwitchFadeStart != null) {
      const f = lodFade(view, g._densitySwitchFadeStart, 140);
      g._densitySwitchFadeStart = view._now() - 140 * lodFadeInvert(1 - f);
    } else {
      g._densitySwitchFadeStart = view._now();
    }
    g._densitySwitchPrev = g._shownDensity;
    g._shownDensity = density;
  }
  const prev = g._densitySwitchPrev;
  const fade = prev && prev.tex ? lodFade(view, g._densitySwitchFadeStart, 140) : 1;
  if (fade < 1) {
    view._drawDensity(g, prev, (1 - fade) * opacityScale);
    view._drawDensity(g, density, fade * opacityScale);
    lodDrawDensityDetail(view, g, density, opacityScale);
    view.draw();
    return;
  }
  if (fade >= 1) {
    if (g.prevDensity === g._densitySwitchPrev) g.prevDensity = null;
    g._densitySwitchPrev = null;
    g._densitySwitchFadeStart = null;
    if (density === g.density) g._densityFadeStart = null;
  }
  view._drawDensity(g, density, opacityScale);
  lodDrawDensityDetail(view, g, density, opacityScale);
}

// The finer-detail layer rides every backdrop draw (T13): painted after the
// primary (and after both crossfade layers) so the sharpest fetched region
// stays on top while the rest of the view shows the broad context.
function lodDrawDensityDetail(view, g, density, opacityScale) {
  const detail = lodDensityDetailForView(view, g, density);
  if (detail && detail.tex) view._drawDensity(g, detail, opacityScale);
}

// The drilled frame's backdrop opacity, eased continuously (T10). The
// aggregate texture stays painted through every transition — entry fade,
// hold, exit fade, revive — and retires once a drill is settled inside its
// window: the marks are exact for that window, and a mean-color wash under
// exact points reads as data. Retirement eases out gently after the entry
// fade lands and eases back fast when the drill exits, holds, or dies, so
// zoom-outs never blank (T1) and interleaved replies never flash. Time-based
// exponential decay, same shape as the lod_blend tween; reduced motion snaps.
function lodDrillBackdropScale(view, g, target) {
  let shown = g._drillBackdropShown;
  if (shown === undefined || shown === null) shown = 1;
  if (Math.abs(shown - target) <= 0.005 || view._prefersReducedMotion()) {
    g._drillBackdropShown = target;
    g._drillBackdropTick = 0;
    return target;
  }
  const now = view._now();
  const dt = g._drillBackdropTick ? Math.min(100, now - g._drillBackdropTick) : 16;
  g._drillBackdropTick = now;
  const tau = target > shown ? 45 : 80;
  shown += (target - shown) * (1 - Math.exp(-dt / tau));
  g._drillBackdropShown = shown;
  view.draw(); // keep the retire/restore animating on settled views
  return shown;
}

// The tier's frame: the aggregate texture is the continuous backdrop through
// every transitional drill state (T10) — marks fade over it entering, held,
// dying, and exiting — and it stands alone otherwise, so a representation
// change is a marks-layer fade over a stable frame, never a blank or a hard
// cut (§5). Once a drill is settled inside its window the backdrop retires
// (lodDrillBackdropScale above): the marks are exact, and the §28 aggregate
// context returns the instant the view leaves the window or a refinement
// goes pending.
export function lodDrawDensityTier(view, g, x0, x1, y0, y1) {
  lodStepNorm(view, g);
  // Retired point windows obey the same geometry-only discipline as the live
  // drill (T11, via T13): once the view outgrows a cached window past the
  // drill budget, no nearby view could be served by it, so its GPU buffers
  // free on this frame — §27's rebuildable-cache rule, no kernel reply needed.
  if (g.drillCache) {
    for (let i = g.drillCache.length - 1; i >= 0; i--) {
      if (lodDrillOutgrown(view, g, g.drillCache[i])) {
        lodFreeDrillBuffers(view, g.drillCache.splice(i, 1)[0]);
      }
    }
    if (!g.drillCache.length) g.drillCache = null;
  }
  const d = g.drill;
  // Rapid zoom out→in revive: a dying drill whose window still covers the
  // view is exact for it (the subset IS every point in that window). Cancel
  // the death and hand the marks back alpha-continuously instead of flashing
  // the aggregate while the kernel's points reply round-trips. (Hover picks
  // against the stale drill_seq are dropped, not wrong — §16 exact-or-nothing
  // holds; the pending reply re-arms them.)
  if (d && g._drillDying && !g._drillDiedInsideWin && view._viewInside(d.win)) {
    g._drillDying = false;
    lodEnterDrillContinuous(view, g);
    g._drillWasInside = true;
  }
  const inside = d && !g._drillDying && view._viewInside(d.win);
  const density = lodDensityForView(view, g);
  const drawMarks = (alpha) => view._drawPoints(
    d,
    view._map(d.xMeta, x0, x1, d.xAxis),
    view._map(d.yMeta, y0, y1, d.yAxis),
    alpha
  );
  if (inside) {
    // Boundary re-entry — or entry with an exit fade mid-flight — continues
    // from the marks alpha currently on screen; never a snap to full.
    if (!g._drillWasInside || g._drillExitFadeStart != null) lodEnterDrillContinuous(view, g);
    g._drillWasInside = true;
    g._drillEverInside = true; // arms geometry-only retirement (T11)
    g._drillExitFadeStart = null;
    const fade = lodFade(view, g._drillFadeStart);
    g._drillShownAlpha = fade;
    // Settled (entry fade landed): the marks are exact — retire the backdrop.
    // Refreshes inside a settled drill keep it retired (no per-reply flash).
    const backdrop = lodDrillBackdropScale(view, g, fade >= 1 ? 0 : 1);
    if (density && density.tex && backdrop > 0.004) {
      lodDrawDensityWithFade(view, g, density, backdrop);
    }
    if (fade < 1) {
      drawMarks(fade);
      view.draw();
    } else {
      g._drillFadeStart = null;
      drawMarks(1);
    }
  } else if (density && density.tex) {
    if (lodHoldPendingDrill(view, g, d)) {
      // Held marks continue their own entry fade over the backdrop — a hold
      // engaging mid-fade must not snap. The backdrop eases back in if the
      // settled drill had retired it (the view has left the exact window).
      lodEnterDrillContinuous(view, g);
      const fade = lodFade(view, g._drillFadeStart);
      g._drillShownAlpha = fade;
      lodDrawDensityWithFade(view, g, density, lodDrillBackdropScale(view, g, 1));
      if (fade < 1) {
        drawMarks(fade);
      } else {
        g._drillFadeStart = null;
        drawMarks(1);
      }
      // A hold is transient — it lives only until the pending refinement lands.
      // Keep a frame scheduled so the hold re-evaluates every tick: if that
      // reply never arrives (dropped as stale, coalesced away, or never sent on
      // the live-drilldown transport) `_lodPendingAt` ages past the hold window
      // and lodHoldPendingDrill lets go on a later frame, so the exit fade below
      // restores the aggregate instead of the held marks freezing on screen
      // forever (the zoom-out "stuck point blob"). Previously this only re-armed
      // while the view was animating, so a *settled* view whose pending reply
      // was stranded had nothing to drive it out of the hold.
      view.draw();
      return;
    }
    const exitingDrill = d && g._drillWasInside;
    // Continuity in the other direction: exiting while the entry fade is
    // still mid-flight starts the exit clock at the current alpha.
    if (exitingDrill) lodBeginDrillExitContinuous(view, g);
    const exitFade = exitingDrill ? lodDrillExitFade(view, g) : 1;
    if (d) g._drillShownAlpha = exitingDrill && exitFade < 1 ? 1 - exitFade : 0;
    if (exitingDrill && exitFade < 1) {
      // A retired backdrop (settled drill) eases back in under the exiting
      // marks — the fast restore keeps the frame from ever reading blank.
      lodDrawDensityWithFade(view, g, density, lodDrillBackdropScale(view, g, 1));
      drawMarks(1 - exitFade);
      view.draw();
    } else {
      if (g._drillDying) {
        // Fade done. A subset that died OUTSIDE its window is still exact for
        // it — the kernel chose density for a view the window doesn't cover —
        // so it retires into the point cache (T13) and a zoom back in
        // promotes it with no round-trip. Dying INSIDE means the kernel chose
        // density FOR this window's own views (forced density / data change):
        // its points-tier claim is void, free the buffers.
        if (d.exact && !g._drillDiedInsideWin) lodRetireDrill(view, g);
        else lodDropDrill(view, g);
      } else if (exitingDrill) {
        g._drillWasInside = false;
      }
      // Geometry-only retirement (T11): an entered drill whose exit has
      // completed frees its buffers once the view outgrows its window past
      // the drill budget — no kernel reply required, and it must run on the
      // completion frame itself (a settled view schedules no further frames).
      // A dying drill was just handled above; a never-entered prefetch is
      // exempt (its window is simply ahead of the view).
      if (g.drill && g._drillEverInside && lodDrillOutgrown(view, g, d)) {
        lodDropDrill(view, g);
      }
      // Ease toward full while a (retired) drill lingers; without one the
      // aggregate owns the frame outright.
      const backdrop = g.drill ? lodDrillBackdropScale(view, g, 1) : 1;
      if (!g.drill) {
        g._drillBackdropShown = 1;
        g._drillBackdropTick = 0;
      }
      lodDrawDensityWithFade(view, g, density, backdrop);
      view._drawDensitySample(g, x0, x1, y0, y1);
    }
  } else if (d) {
    drawMarks(1);
  }
}
