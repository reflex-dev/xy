import { parseColor } from "./20_theme";

// ---------------------------------------------------------------------------

const LOD_DIRECT_POINT_BUDGET = 200000;
const LOD_DRILL_EXIT_FACTOR = 1.15;
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
export function lodWriteGridTexture(gl, tex, f32, w, h, maxVal, rgba = null) {
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
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
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
      view.gl, g.density.tex, g.density.grid, g.density.w, g.density.h, target, g.density.rgba,
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
    lodWriteGridTexture(view.gl, d.tex, d.grid, d.w, d.h, norm, d.rgba);
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

// §28 hybrid overlay, window pairing (T9): every sample rides the density
// window it was computed for, so the points on screen always describe the
// window being displayed. Selection mirrors lodDensityForView: the smallest
// cached window whose sample covers the whole view wins at full alpha (deep
// zoom-out lands on the overview sample — the point cloud comes back instead
// of a stale drilled cluster). Only when NO cached window covers the view
// (pan off-cache, zoom-out past home) does the best partial overlay draw,
// bounded by the T9 coverage fade so it can never read as a false cluster.
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

export function lodRememberDensity(view, g, d) {
  if (!d || !d.tex) return;
  d._stamp = ++view._densityStamp;
  if (!g.densityCache) g.densityCache = [];
  if (!g.densityCache.includes(d)) g.densityCache.push(d);
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

// -- drill lifecycle ----------------------------------------------------------

// The kernel decided this view fits the direct budget and shipped real marks
// (channels restored). Build/refresh a direct-shaped sibling on the tiered
// trace; the tier draw uses it until the kernel switches back.
export function lodApplyDrill(view, g, upd, buffers) {
  const gl = view.gl;
  const fresh = !g.drill; // transition INTO drill vs refresh of a live drill
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
  d.win = { x0: upd.x_range[0], x1: upd.x_range[1], y0: upd.y_range[0], y1: upd.y_range[1] };
  d.n = Math.min(upd.x.len, upd.y.len);
  d.visible = upd.visible ?? d.n;
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
    d[colorBufferName]._fcType = colorValues instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
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
    if (!d.sBuf) d.sBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.sBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.size.buf]), gl.STATIC_DRAW);
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
    if (!d.dBuf) d.dBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.dBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.density_val.buf]), gl.STATIC_DRAW);
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
  const gl = view.gl;
  view._deleteVaos(d); // the drill sibling carries its own VAOs
  for (const b of [d.xBuf, d.yBuf, d.cBuf, d.rgbaBuf, d.sBuf, d.styleBuf,
    d.strokeBuf, d.selBuf, d.dBuf]) if (b) gl.deleteBuffer(b);
  g.drill = null;
  g._drillFadeStart = null;
  g._drillExitFadeStart = null;
  g._drillWasInside = false;
  g._drillEverInside = false;
  g._drillShownAlpha = null;
  g._drillDying = false;
  g._drillDiedInsideWin = false;
  view._hoverId = -1; // drilled indices are dead; don't reuse a cached row
  view._lastRow = null;
  // The freed drill may have been the only pickable geometry (a density-only
  // chart): retract the modebar Select trigger with the capability.
  view._updatePickable();
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
  // Mean point color plane (LOD doc §2): copied, not viewed — exposure
  // easing re-reads it on every norm step, after the wire buffer may be gone.
  const rgba = d.rgba !== undefined ? new Uint8Array(view._asU8(buffers[d.rgba])) : null;
  const normStart = lodNormMax(g, d.max);
  const normMax = view._prefersReducedMotion() ? d.max : normStart;
  g.densityNormMax = normMax;
  g.prevDensity = g.density;
  g._densityFadeStart = view._now();
  g.density = {
    w: d.w, h: d.h, max: d.max, normMax, colormap: d.colormap || g.density.colormap,
    color: d.color ? parseColor(view.root, d.color, [0.3, 0.47, 0.66, 1]) : g.density.color,
    xRange: d.x_range, yRange: d.y_range,
    grid,
    rgba,
    tex: view._uploadGrid(grid, d.w, d.h, normMax, rgba),
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
}

// The tier's frame: the aggregate texture is the CONTINUOUS BACKDROP at every
// state (T10) — marks draw over it while the view sits inside a live drilled
// window, fade over it during transitions (drill-in entry fade, dying drill
// exit fade, stale-while-revalidate hold), and it stands alone otherwise.
// Never blank, never a hard cut (§5 smooth transitions): the background of a
// drilled frame and a density frame is the same texture, so every drill
// transition is a marks-layer fade, not a full-frame swap. (Previously marks
// "owned the frame" once their entry fade completed — the backdrop flipped to
// the blank chart background, and interleaved density/points replies during a
// continuous zoom flashed green-texture ⇄ points-on-blank, the live-drilldown
// flicker.)
export function lodDrawDensityTier(view, g, x0, x1, y0, y1) {
  lodStepNorm(view, g);
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
    if (density && density.tex) lodDrawDensityWithFade(view, g, density);
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
      // engaging mid-fade must not snap.
      lodEnterDrillContinuous(view, g);
      const fade = lodFade(view, g._drillFadeStart);
      g._drillShownAlpha = fade;
      lodDrawDensityWithFade(view, g, density);
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
      lodDrawDensityWithFade(view, g, density);
      drawMarks(1 - exitFade);
      view.draw();
    } else {
      if (g._drillDying) lodDropDrill(view, g); // fade done: free the buffers
      else if (exitingDrill) g._drillWasInside = false;
      // Geometry-only retirement (T11): an entered drill whose exit has
      // completed frees its buffers once the view outgrows its window past
      // the drill budget — no kernel reply required, and it must run on the
      // completion frame itself (a settled view schedules no further frames).
      // A dying drill was just dropped above; a never-entered prefetch is
      // exempt (its window is simply ahead of the view).
      if (g.drill && g._drillEverInside && lodDrillOutgrown(view, g, d)) {
        lodDropDrill(view, g);
      }
      lodDrawDensityWithFade(view, g, density);
      view._drawDensitySample(g, x0, x1, y0, y1);
    }
  } else if (d) {
    drawMarks(1);
  }
}
