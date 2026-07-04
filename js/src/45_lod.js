// ---------------------------------------------------------------------------

const LOD_DIRECT_POINT_BUDGET = 200000;
const LOD_DRILL_EXIT_FACTOR = 1.15;
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
  const t = Math.min(1, Math.max(0, (performance.now() - start) / duration));
  return t * t * (3 - 2 * t);
}

function lodCopyGrid(f32) {
  return f32.slice ? f32.slice() : new Float32Array(f32);
}

// Log tone-mapped grid upload (R8): stable perception across renormalization,
// and the u_max swings between rebins compress logarithmically (§5/§F6).
function lodWriteGridTexture(gl, tex, f32, w, h, maxVal) {
  const data = new Uint8Array(f32.length);
  const denom = Math.log1p(Math.max(0, maxVal || 0));
  if (denom > 0) {
    for (let i = 0; i < f32.length; i++) {
      const c = f32[i];
      if (c > 0 && Number.isFinite(c)) {
        data[i] = Math.max(1, Math.min(255, Math.round(255 * Math.log1p(c) / denom)));
      }
    }
  }
  gl.bindTexture(gl.TEXTURE_2D, tex);
  const align = gl.getParameter(gl.UNPACK_ALIGNMENT);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data);
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
    lodWriteGridTexture(view.gl, g.density.tex, g.density.grid, g.density.w, g.density.h, target);
    return;
  }
  g._densityNormAnim = {
    start,
    target,
    startedAt: performance.now(),
    duration: target < start ? 420 : 260,
  };
}

function lodStepNorm(view, g) {
  const anim = g._densityNormAnim;
  const d = g.density;
  if (!anim || !d || !d.grid || !d.tex) return;
  const t = Math.min(1, Math.max(0, (performance.now() - anim.startedAt) / anim.duration));
  const k = t * t * (3 - 2 * t);
  const norm = anim.start + (anim.target - anim.start) * k;
  const prev = d.normMax || 0;
  const rel = Math.abs(norm - prev) / Math.max(Math.abs(norm), Math.abs(prev), 1);
  if (rel > 0.004 || t >= 1) {
    d.normMax = norm;
    g.densityNormMax = norm;
    lodWriteGridTexture(view.gl, d.tex, d.grid, d.w, d.h, norm);
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
  return cx >= win.x0 && cx <= win.x1 && cy >= win.y0 && cy <= win.y1;
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

function lodHoldPendingDrill(view, g, d) {
  const pending = g._lodPendingView;
  if (!d || !pending || g._drillDying) return false;
  if (g._lodPendingSeq !== view.seq) return false;
  if (g._lodPendingAt && performance.now() - g._lodPendingAt > 1200) return false;
  if (!lodWindowCenterInside(d.win, pending)) return false;
  const drillArea = lodWindowArea(d.win);
  const pendingArea = lodWindowArea(pending);
  if (!Number.isFinite(drillArea) || !Number.isFinite(pendingArea) || drillArea <= 0) return false;
  const baseVisible = Number.isFinite(d.visible) ? d.visible : d.n;
  if (!Number.isFinite(baseVisible) || baseVisible <= 0) return false;
  const estimatedVisible = baseVisible * Math.max(1, pendingArea / drillArea);
  return estimatedVisible <= LOD_DIRECT_POINT_BUDGET * LOD_DRILL_EXIT_FACTOR;
}

function lodRememberDensity(view, g, d) {
  if (!d || !d.tex) return;
  d._stamp = ++view._densityStamp;
  if (!g.densityCache) g.densityCache = [];
  if (!g.densityCache.includes(d)) g.densityCache.push(d);
  const maxCached = 8;
  while (g.densityCache.length > maxCached) {
    let drop = -1;
    for (let i = 0; i < g.densityCache.length; i++) {
      const cand = g.densityCache[i];
      if (cand === g.density) continue;
      if (cand === g.prevDensity) continue;
      if (cand === g._densitySwitchPrev) continue;
      if (drop < 0) { drop = i; continue; }
      const dropArea = lodDensityArea(g.densityCache[drop]);
      const candArea = lodDensityArea(cand);
      if (candArea < dropArea || (candArea === dropArea && cand._stamp < g.densityCache[drop]._stamp)) {
        drop = i;
      }
    }
    if (drop < 0) break;
    const old = g.densityCache.splice(drop, 1)[0];
    if (old !== g.density && old !== g.prevDensity && old !== g._densitySwitchPrev) {
      view.gl.deleteTexture(old.tex);
    }
  }
}

// -- drill lifecycle ----------------------------------------------------------

// The kernel decided this view fits the direct budget and shipped real marks
// (channels restored). Build/refresh a direct-shaped sibling on the tiered
// trace; the tier draw uses it until the kernel switches back.
function lodApplyDrill(view, g, upd, buffers) {
  const gl = view.gl;
  const fresh = !g.drill; // transition INTO drill vs refresh of a live drill
  let d = g.drill;
  if (!d) {
    d = g.drill = { trace: g.trace, xBuf: gl.createBuffer(), yBuf: gl.createBuffer() };
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, d.xBuf);
  gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.x.buf]), gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, d.yBuf);
  gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.y.buf]), gl.STATIC_DRAW);
  d.xMeta = { offset: upd.x.offset, scale: upd.x.scale };
  d.yMeta = { offset: upd.y.offset, scale: upd.y.scale };
  d.win = { x0: upd.x_range[0], x1: upd.x_range[1], y0: upd.y_range[0], y1: upd.y_range[1] };
  d.n = Math.min(upd.x.len, upd.y.len);
  d.visible = upd.visible ?? d.n;
  d.seq = upd.drill_seq; // subset version — echoed with picks, gates selections
  d.selActive = false; // drilled subset changed; old mask indices are stale
  // The point under the cursor is a different row now; a cached tooltip for
  // the same index would silently show the old point's values (§16).
  view._hoverId = -1;
  view._lastRow = null;
  d.colorMode = 0;
  d.color = parseColor(view.root, upd.color && upd.color.color, [0.3, 0.47, 0.66, 1]);
  if (upd.color && upd.color.buf !== undefined) {
    d.colorMode = upd.color.mode === "continuous" ? 1 : 2;
    if (!d.cBuf) d.cBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.cBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.color.buf]), gl.STATIC_DRAW);
    d.lut = upd.color.mode === "continuous"
      ? view._lut(upd.color.colormap)
      : view._paletteLut(upd.color.palette);
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
  // Color-continuous handoff (§5): per-point local log-density + a blend
  // weight. Fresh at the boundary (blend≈1) the marks wear the aggregate's
  // colormap, so the texture->marks swap doesn't recolor the chart; deeper
  // zooms ship smaller blends and the native colors ease in.
  if (upd.density_val && upd.density_val.buf !== undefined) {
    if (!d.dBuf) d.dBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.dBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.density_val.buf]), gl.STATIC_DRAW);
    d.dlut = view._lut(upd.density_colormap || "viridis");
    const first = d.lodBlend === undefined;
    d.lodBlend = Math.min(1, upd.lod_blend ?? 0);
    if (first) d.lodBlendShown = d.lodBlend; // no tween-from-zero on arrival
  } else {
    d.lodBlend = 0;
  }
  // The entry fade runs ONLY on the aggregate→marks transition. Restarting it
  // on every refresh made the marks blink to ~0 alpha after each kernel
  // reply — a steady flash while zooming within a drilled view.
  if (fresh) g._drillFadeStart = performance.now();
  // A live points update revives a dying drill (hysteresis flip): cancel the
  // exit fade rather than fighting it.
  g._drillDying = false;
  g._drillExitFadeStart = null;
  g._drillWasInside = false;
}

function lodDropDrill(view, g) {
  const d = g.drill;
  if (!d) return;
  const gl = view.gl;
  for (const b of [d.xBuf, d.yBuf, d.cBuf, d.sBuf, d.selBuf, d.dBuf]) if (b) gl.deleteBuffer(b);
  g.drill = null;
  g._drillFadeStart = null;
  g._drillExitFadeStart = null;
  g._drillWasInside = false;
  g._drillDying = false;
  view._hoverId = -1; // drilled indices are dead; don't reuse a cached row
  view._lastRow = null;
}

// A density update arrived while drilled: don't drop the marks instantly
// (that hard-cuts the exit fade — a visible flash on drill-out). Mark the
// drill dying; the tier draw fades it over the incoming aggregate and frees
// it when the fade completes.
function lodMarkDrillDying(g) {
  if (!g.drill) return;
  g._drillDying = true;
  if (g._drillExitFadeStart == null) g._drillExitFadeStart = performance.now();
}

function lodDrillExitFade(view, g) {
  if (g._drillExitFadeStart === undefined || g._drillExitFadeStart === null) {
    g._drillExitFadeStart = performance.now();
  }
  const fade = lodFade(view, g._drillExitFadeStart, 120);
  if (fade >= 1) g._drillExitFadeStart = null;
  return fade;
}

// -- aggregate updates & tier drawing ----------------------------------------

// Apply a kernel "density"-mode update: new grid texture with eased exposure
// normalization, previous grid kept for the crossfade, source remembered in
// the per-trace cache.
function lodApplyDensityUpdate(view, g, upd, buffers) {
  lodMarkDrillDying(g);
  const d = upd.density;
  const grid = lodCopyGrid(view._asF32(buffers[d.buf]));
  const normStart = lodNormMax(g, d.max);
  const normMax = view._prefersReducedMotion() ? d.max : normStart;
  g.densityNormMax = normMax;
  g.prevDensity = g.density;
  g._densityFadeStart = performance.now();
  g.density = {
    w: d.w, h: d.h, max: d.max, normMax, colormap: d.colormap || g.density.colormap,
    xRange: d.x_range, yRange: d.y_range,
    grid,
    tex: view._uploadGrid(grid, d.w, d.h, normMax),
    lut: g.density.lut,
  };
  lodStartNormAnim(view, g, normMax, d.max);
  lodRememberDensity(view, g, g.density);
}

function lodDrawDensityWithFade(view, g, density, opacityScale = 1) {
  if (density !== g._shownDensity) {
    g._densitySwitchPrev = g._shownDensity;
    g._densitySwitchFadeStart = performance.now();
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

// The tier's frame: marks alone while the view sits inside a live drilled
// window; aggregate + fading marks during transitions (drill-in entry fade,
// dying drill exit fade); aggregate alone otherwise. Never blank, never a
// hard cut (§5 smooth transitions).
function lodDrawDensityTier(view, g, x0, x1, y0, y1) {
  lodStepNorm(view, g);
  const d = g.drill;
  // A dying drill always takes the exit-fade path — even with the view still
  // inside its window — so the marks→aggregate handoff is a fade, never a cut.
  const inside = d && !g._drillDying && view._viewInside(d.win);
  const density = lodDensityForView(view, g);
  if (inside) {
    g._drillWasInside = true;
    g._drillExitFadeStart = null;
    const fade = lodFade(view, g._drillFadeStart);
    if (fade < 1 && density && density.tex) {
      view._drawDensity(g, density, 1 - fade);
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1), fade);
      view.draw();
    } else {
      g._drillFadeStart = null;
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1));
    }
  } else if (density && density.tex) {
    if (lodHoldPendingDrill(view, g, d)) {
      g._drillExitFadeStart = null;
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1));
      if (view._viewAnim) view.draw();
      return;
    }
    const exitingDrill = d && g._drillWasInside;
    const exitFade = exitingDrill ? lodDrillExitFade(view, g) : 1;
    if (exitingDrill && exitFade < 1) {
      lodDrawDensityWithFade(view, g, density, exitFade);
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1), 1 - exitFade);
      view.draw();
    } else {
      if (g._drillDying) lodDropDrill(view, g); // fade done: free the buffers
      else if (exitingDrill) g._drillWasInside = false;
      lodDrawDensityWithFade(view, g, density);
    }
  } else if (d) {
    view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1));
  }
}
