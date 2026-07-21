// ChartView <-> kernel comm: debounced density view-requests, streaming
// appends, the inbound message handler, and the deep-zoom drill lifecycle
// (§16). Split out of 50_chartview.js; augments the prototype so `this.*`
// is unchanged.

Object.assign(ChartView.prototype, {
  _scheduleViewRequest(viewOverride = this.view, opts = {}) {
    if (this._destroyed || this._glLost) return;
    if (!this.comm) {
      // Kernel-less (standalone HTML): density traces refine via the bundled
      // re-bin worker instead of a kernel round-trip.
      this._scheduleSampleRebin(viewOverride, opts);
      return;
    }
    const needsDecimated = this.spec.traces.some((t) => t.tier === "decimated");
    const needsDensity = this.gpuTraces.some((g) => g.tier === "density");
    if (!needsDecimated && !needsDensity) return;
    const seq = opts.seq ?? ++this.seq;
    const view = this._copyView(viewOverride);
    const plotW = Math.round(this.plot.w);
    const plotH = Math.round(this.plot.h);
    if (needsDensity) {
      const now = this._now();
      for (const g of this.gpuTraces) {
        if (g.tier !== "density") continue;
        g._lodPendingView = view;
        g._lodPendingSeq = seq;
        g._lodPendingAt = now;
      }
    }
    let delay = opts.delay ?? 120;
    if (opts.maxWait !== undefined && opts.maxWait !== null) {
      const now = this._now();
      if (this._viewRequestBurstStart === undefined || this._viewRequestBurstStart === null) {
        this._viewRequestBurstStart = now;
      }
      const remaining = opts.maxWait - (now - this._viewRequestBurstStart);
      delay = remaining <= 0 ? 0 : Math.min(delay, remaining);
    } else {
      this._viewRequestBurstStart = null;
    }
    clearTimeout(this._viewTimer);
    const send = () => {
      if (this._destroyed) return;
      this._viewRequestBurstStart = null;
      if (seq !== this.seq) return;
      if (needsDecimated) {
        this.comm.send({
          type: "view", seq,
          x0: Math.min(view.x0, view.x1), x1: Math.max(view.x0, view.x1), px: plotW,
        });
      }
      if (needsDensity) {
        for (const g of this.gpuTraces) {
          if (g.tier !== "density") continue;
          const [x0, x1] = this._axisRange(g.xAxis, view);
          const [y0, y1] = this._axisRange(g.yAxis, view);
          this.comm.send({
            type: "density_view", seq, trace: g.trace.id,
            x0: Math.min(x0, x1), x1: Math.max(x0, x1),
            y0: Math.min(y0, y1), y1: Math.max(y0, y1),
            w: plotW, h: plotH,
          });
        }
      }
    };
    if (delay <= 0) {
      send();
    } else {
      this._viewTimer = setTimeout(send, delay);
    }
    return seq;
  },

  // Standalone (kernel-less) density refinement. Debounced like the kernel
  // request path, then the retained §28 sample re-bins in the bundled worker —
  // off the main thread — and applies like a density_update.
  _scheduleSampleRebin(viewOverride = this.view, opts = {}) {
    if (this._destroyed || this._glLost || this._sampleRebinDisabled) return;
    const targets = (this.gpuTraces || []).filter(
      (g) => g.tier === "density" && g.sampleOverlay && g.sampleOverlay._cpu
    );
    if (!targets.length) return;
    const seq = opts.seq ?? ++this.seq;
    const view = this._copyView(viewOverride);
    clearTimeout(this._rebinTimer);
    this._rebinTimer = setTimeout(() => {
      if (this._destroyed || seq !== this.seq) return;
      for (const g of targets) this._requestSampleRebin(g, view, seq);
    }, opts.delay ?? 120);
  },

  _requestSampleRebin(g, view, seq) {
    if (!g._homeDensity) g._homeDensity = g.density;
    // The full overview grid — binned kernel-side from every source point at
    // export — has enough resolution for any view that is not zoomed in
    // *tighter* than the home extent. Re-binning the retained §28 sample only
    // adds resolution once the user zooms in; doing it on a mere pan (or a
    // zoom-out) would swap the full-data grid for a noisier sample-derived
    // grid that normalizes against a different, much smaller maximum, so the
    // density visibly jumps between the overview and the sample on the
    // slightest drag. Gate on view *span*, not position: keep (and restore)
    // the overview for pans and zoom-outs; only a real zoom-in re-bins. Spans
    // are read per axis (§9.2) so multi-axis views compare like for like.
    const [vx0, vx1] = this._axisRange(g.xAxis, view);
    const [vy0, vy1] = this._axisRange(g.yAxis, view);
    const [hx0, hx1] = this._axisRange(g.xAxis, this.view0);
    const [hy0, hy1] = this._axisRange(g.yAxis, this.view0);
    const homeSpanX = Math.max(Math.abs(hx1 - hx0), 1e-300);
    const homeSpanY = Math.max(Math.abs(hy1 - hy0), 1e-300);
    const viewSpanX = Math.abs(vx1 - vx0);
    const viewSpanY = Math.abs(vy1 - vy0);
    // 1e-6 slack absorbs float drift so a pan at home zoom never trips a re-bin.
    const notZoomedIn =
      viewSpanX >= homeSpanX * (1 - 1e-6) && viewSpanY >= homeSpanY * (1 - 1e-6);
    if (notZoomedIn) {
      if (g.density !== g._homeDensity) {
        const hd = g._homeDensity;
        this._applySampleRebinGrid(g, {
          ...hd,
          tex: this._uploadGrid(hd.grid, hd.w, hd.h, hd.normMax || hd.max || 1),
        }, false);
      }
      return;
    }
    if (this._sampleRebinDisabled) return;
    if (!this._rebinWorker) {
      this._rebinWorker = xyCreateRebinWorker();
      if (!this._rebinWorker) {
        this._sampleRebinDisabled = true; // no worker: stretched overview stays
        return;
      }
      this._rebinWorker.onmessage = (e) => this._onRebinResult(e.data);
      this._rebinInit = new Set();
    }
    if (!this._rebinInit.has(g.trace.id)) {
      // Decode the offset-encoded sample once (f64, §16); the worker keeps it.
      const cpu = g.sampleOverlay._cpu;
      const n = Math.min(cpu.x.length, cpu.y.length);
      const xs = new Float64Array(n);
      const ys = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        xs[i] = this._decodeValue(cpu.x, cpu.xMeta, i);
        ys[i] = this._decodeValue(cpu.y, cpu.yMeta, i);
      }
      this._rebinWorker.postMessage(
        { type: "init", trace: g.trace.id, x: xs.buffer, y: ys.buffer },
        [xs.buffer, ys.buffer]
      );
      this._rebinInit.add(g.trace.id);
    }
    this._rebinWorker.postMessage({
      type: "rebin", trace: g.trace.id, seq,
      x0: Math.min(vx0, vx1), x1: Math.max(vx0, vx1),
      y0: Math.min(vy0, vy1), y1: Math.max(vy0, vy1),
      w: Math.max(16, Math.min(2048, Math.round(this.plot.w))),
      h: Math.max(16, Math.min(2048, Math.round(this.plot.h))),
    });
  },

  _onRebinResult(msg) {
    if (this._destroyed || this._glLost || !msg || msg.type !== "grid" || msg.seq !== this.seq) return;
    const g = this.gpuTraces.find((t) => t.trace.id === msg.trace && t.tier === "density");
    if (!g) return;
    const grid = new Float32Array(msg.grid);
    this._applySampleRebinGrid(g, {
      w: msg.w, h: msg.h, max: msg.max, normMax: msg.max,
      colormap: g.density.colormap,
      xRange: [msg.x0, msg.x1], yRange: [msg.y0, msg.y1],
      grid,
      tex: this._uploadGrid(grid, msg.w, msg.h, msg.max || 1),
      lut: g.density.lut,
    }, true);
  },

  // Swap the density grid/texture only — unlike lodApplyDensityUpdate this
  // leaves the retained sample overlay alone (it is the re-bin source and the
  // deep-zoom point overlay). Texture lifetime stays with the LOD cache.
  _applySampleRebinGrid(g, density, rebinned) {
    g.prevDensity = g.density;
    g._densityFadeStart = this._now();
    g.densityNormMax = density.normMax || density.max;
    g.density = density;
    g._sampleRebinned = !!rebinned; // badge: recorded reduction, never silent (§28)
    lodRememberDensity(this, g, g.density);
    this._refreshReductionBadges();
    this.draw();
  },

  // Streaming append (rust-engine §5). The kernel ships a complete fresh
  // payload — screen-bounded by construction (§29), so this is O(pixels) no
  // matter how much data has accumulated — and names the traces whose data
  // changed. Only those GPU traces rebuild; everything else keeps its state.
  // Tiered traces then refine to the *current* window through the normal
  // stale-while-revalidate request path (§17).
  _applyAppend(msg, buffers) {
    const spec = msg.spec;
    const blobRaw = buffers && buffers[0];
    if (!spec || !blobRaw || !spec.traces) return;
    const blob = bytesToSpan(blobRaw);
    // Follow policy, decided against the OLD home view before it moves:
    // - at home (never zoomed, or axes reset): the chart follows its data —
    //   refit both axes to the new domain, the live-dashboard default.
    // - zoomed with the right edge pinned to the old live edge: slide the
    //   window forward at constant width (tail-follow).
    // - zoomed anywhere else: the user is inspecting history; don't move them.
    const spanEps = (lo, hi) => Math.max(Math.abs(hi - lo), 1e-300) * 1e-9;
    const ex = spanEps(this.view0.x0, this.view0.x1);
    const ey = spanEps(this.view0.y0, this.view0.y1);
    const atHome =
      Math.abs(this.view.x0 - this.view0.x0) <= ex && Math.abs(this.view.x1 - this.view0.x1) <= ex &&
      Math.abs(this.view.y0 - this.view0.y0) <= ey && Math.abs(this.view.y1 - this.view0.y1) <= ey;
    const pinnedRight = !atHome && Math.abs(this.view.x1 - this.view0.x1) <= ex;
    // Swap spec + retained payload together so GL context restore (§27)
    // rebuilds the streamed state, not the initial one.
    this.spec = spec;
    this.axes = this._normalizeAxes(spec);
    this._payload = blob;
    this.view0 = this._copyView({
      ranges: Object.fromEntries(Object.entries(this.axes).map(([id, axis]) => [id, [...axis.range]])),
    });
    if (atHome) {
      this.view = this._copyView(this.view0);
    } else if (pinnedRight) {
      const w = this.view.x1 - this.view.x0;
      this.view = this._viewFrom({ x1: this.view0.x1, x0: this.view0.x1 - w });
    }
    // Append payloads are canonical state, so retain them even while the
    // context is lost. The restore path rebuilds every affected GPU object
    // from this latest payload; attempting partial uploads to a dead context
    // would only create handles that must immediately be discarded.
    if (this._glLost || !this.gl) return;
    const texSeen = new Set();
    for (const id of msg.affected || []) {
      const i = this.gpuTraces.findIndex((g) => g.trace.id === id);
      const ts = spec.traces.find((t) => t.id === id);
      if (i < 0 || !ts) continue;
      this._destroyTraceResources(this.gpuTraces[i], texSeen);
      this.gpuTraces[i] = this._buildTrace(blob, ts);
    }
    this._pickable = this.gpuTraces.some(
      (g) => markOf(g.trace.kind).pointPick && (g.tier !== "density" || g.drill));
    if (this._pickable && !this.pickFbo) this._initPickTarget();
    this._scheduleViewRequest(this.view, { delay: 0 });
    this.draw();
  },

  _onKernelMsg(msg, buffers) {
    if (this._destroyed) return;
    if (!msg) return;
    if (this._glLost && msg.type !== "append" && msg.type !== "pick_result") return;
    if (msg.type === "tier_update") {
      if (msg.seq !== this.seq) return;
      for (const upd of msg.traces) {
        const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
        if (!g) continue;
        const gl = this.gl;
        const xArr = this._asF32(buffers[upd.x.buf]);
        const yArr = this._asF32(buffers[upd.y.buf]);
        const bArr = upd.base && g.baseBuf ? this._asF32(buffers[upd.base.buf]) : null;
        let n = Math.min(upd.x.len, upd.y.len);
        if (bArr) n = Math.min(n, upd.base.len);
        // curve:"smooth" traces re-smooth every refined window, so the curve
        // survives zoom-driven re-decimation instead of snapping to segments.
        // style.step traces likewise re-expand so the step corners survive
        // tier swaps instead of collapsing to a plain polyline.
        const sm = this._smoothArrays(g.trace, xArr, yArr, bArr, n);
        const src = sm || { x: xArr, y: yArr, n };
        const st = this._stepArrays(g.trace, src.x, src.y, src.n);
        gl.bindBuffer(gl.ARRAY_BUFFER, g.xBuf);
        gl.bufferData(gl.ARRAY_BUFFER, st ? st.x : src.x, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, g.yBuf);
        gl.bufferData(gl.ARRAY_BUFFER, st ? st.y : src.y, gl.STATIC_DRAW);
        g.xMeta = { ...g.xMeta, offset: upd.x.offset, scale: upd.x.scale };
        g.yMeta = { ...g.yMeta, offset: upd.y.offset, scale: upd.y.scale };
        g._dashX = st ? st.x : src.x;
        g._dashY = st ? st.y : src.y;
        if (bArr) {
          gl.bindBuffer(gl.ARRAY_BUFFER, g.baseBuf);
          gl.bufferData(gl.ARRAY_BUFFER, sm ? sm.extra : bArr, gl.STATIC_DRAW);
          g.baseMeta = { ...g.baseMeta, offset: upd.base.offset, scale: upd.base.scale };
        }
        g.n = st ? st.n : src.n;
      }
      this.draw();
    } else if (msg.type === "density_update") {
      if (msg.seq !== undefined && msg.seq !== this.seq) return;
      const densityTraces = msg.traces || [];
      const pendingTraceIds = new Set(densityTraces.map((upd) => Number(upd.id)));
      if (pendingTraceIds.size === 0 && msg.trace !== undefined) {
        pendingTraceIds.add(Number(msg.trace));
      }
      const clearAllPending = pendingTraceIds.size === 0 && msg.stale;
      const clearPending = (g) => {
        if (msg.seq !== undefined && g._lodPendingSeq !== msg.seq) return;
        g._lodPendingView = null;
        g._lodPendingSeq = null;
        g._lodPendingAt = null;
      };
      if (pendingTraceIds.size || clearAllPending) {
        for (const g of this.gpuTraces) {
          if (g.tier !== "density") continue;
          if (!clearAllPending && !pendingTraceIds.has(g.trace.id)) continue;
          clearPending(g);
        }
      }
      for (const upd of densityTraces) {
        const g = this.gpuTraces.find((t) => t.trace.id === upd.id && t.tier === "density");
        if (!g) continue;
        clearPending(g);
        if (upd.mode === "points") { this._applyDrill(g, upd, buffers); continue; }
        lodApplyDensityUpdate(this, g, upd, buffers);
      }
      // Drill state changes what's pickable; hover needs the FBO ready.
      this._pickable = this.gpuTraces.some(
        (t) => markOf(t.trace.kind).pointPick && (t.tier !== "density" || t.drill));
      if (this._pickable && !this.pickFbo) this._initPickTarget();
      this.draw();
    } else if (msg.type === "append") {
      this._applyAppend(msg, buffers);
    } else if (msg.type === "pick_result") {
      if (msg.seq !== undefined && msg.seq !== this._pickSeq) return;
      if (!msg.row) { this._hideTooltip(); return; }
      // The kernel returns exact values for the picked trace only. Rehydrate
      // tooltip fields sourced from sibling traces before replacing the local
      // approximate row, otherwise a rich layered tooltip visibly collapses.
      // _localRow already resolved those fields for this same hover; reuse
      // them (fields the kernel row lacks are exactly the sibling-sourced
      // ones) so _applySharedTooltipFields finds nothing missing and skips
      // its O(n) sibling scans. It stays as the mismatch fallback.
      const local = this._lastRow;
      if (local && local.trace === msg.row.trace && local.index === msg.row.index) {
        for (const [key, value] of Object.entries(local)) {
          if (msg.row[key] === undefined) msg.row[key] = value;
        }
      }
      this._applySharedTooltipFields(msg.row);
      this._lastRow = msg.row;
      // Replace the approximate f32 anchor with the exact f64 point (§16).
      if (this._tooltipAnchor
          && Number.isFinite(msg.row.x) && Number.isFinite(msg.row.y)) {
        this._tooltipAnchor.x = msg.row.x;
        this._tooltipAnchor.y = msg.row.y;
      }
      const xy = this._lastHoverXY;
      // Exact values replace the visible approximate tooltip. A keyboard
      // readout already announced its position and approximate values, so do
      // not clobber that prefix or produce a second announcement per keypress.
      if (xy) this._renderTooltip(msg.row, xy.clientX, xy.clientY, {
        announce: !this._a11yKeyboardReadout,
      });
      if (this._interactionFlag("hover")) {
        this._dispatchChartEvent("hover", {
          row: msg.row,
          trace: msg.row.trace,
          index: msg.row.index,
          exact: true,
          view: this._eventView("hover"),
        });
      }
    } else if (msg.type === "selection") {
      if (!msg.traces || !msg.traces.length) {
        for (const g of this.gpuTraces) {
          g.selActive = false;
          if (g.drill) g.drill.selActive = false;
        }
      } else {
        for (const upd of msg.traces) {
          const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
          if (!g) continue;
          // Aggregate density has no per-point marks, but a drilled view does —
          // the kernel's indices are in the drilled subset's space (§17).
          const pg = g.tier === "density" ? g.drill : g;
          if (!pg || !pg.n) continue;
          // A mask built against another subset version would highlight
          // arbitrary points — drop it; the kernel's canonical Selection is
          // still correct and a fresh drag re-syncs the visual.
          if (
            g.tier === "density" && upd.drill_seq !== undefined &&
            pg.seq !== undefined && upd.drill_seq !== pg.seq
          ) continue;
          const idx = this._asU32(buffers[upd.buf]);
          const mask = new Float32Array(pg.n);
          for (let i = 0; i < idx.length; i++) if (idx[i] < pg.n) mask[idx[i]] = 1;
          this._applySelMask(pg, mask);
        }
      }
      this._selectionCount = msg.total || 0;
      this.draw();
      if (this._interactionFlag("select", true)) {
        this._dispatchChartEvent("select", {
          total: this._selectionCount,
          view: this._eventView("select"),
        });
      }
    }
  },

  // Drill lifecycle, exit fades, and the density-source cache live in
  // 45_lod.js (chart-agnostic). These delegates keep the ChartView API
  // stable for tests and callers.
  _applyDrill(g, upd, buffers) {
    lodApplyDrill(this, g, upd, buffers);
  },

  _dropDrill(g) {
    lodDropDrill(this, g);
  },

  // Is the current view fully covered by a drilled window? A tiny epsilon
  // absorbs f32 round-trip slop so we don't flip to the overview at the exact
  // window edge right after drilling in.
  _viewInside(win) {
    if (!win) return false;
    const { x0, x1, y0, y1 } = this.view;
    const ex = Math.abs(x1 - x0) * 1e-4, ey = Math.abs(y1 - y0) * 1e-4;
    const vx0 = Math.min(x0, x1), vx1 = Math.max(x0, x1);
    const vy0 = Math.min(y0, y1), vy1 = Math.max(y0, y1);
    const wx0 = Math.min(win.x0, win.x1), wx1 = Math.max(win.x0, win.x1);
    const wy0 = Math.min(win.y0, win.y1), wy1 = Math.max(win.y0, win.y1);
    return vx0 >= wx0 - ex && vx1 <= wx1 + ex && vy0 >= wy0 - ey && vy1 <= wy1 + ey;
  },

  // Does the current view overlap `win` at all (as opposed to sit fully inside
  // it)? Used to keep the retained density sample on screen through pans and
  // zoom-outs — the points are positioned in data space and the GPU clips the
  // off-screen ones, so overlap is the right test, not containment.
  _viewOverlaps(win) {
    if (!win) return false;
    const { x0, x1, y0, y1 } = this.view;
    const vx0 = Math.min(x0, x1), vx1 = Math.max(x0, x1);
    const vy0 = Math.min(y0, y1), vy1 = Math.max(y0, y1);
    const wx0 = Math.min(win.x0, win.x1), wx1 = Math.max(win.x0, win.x1);
    const wy0 = Math.min(win.y0, win.y1), wy1 = Math.max(win.y0, win.y1);
    return vx0 <= wx1 && vx1 >= wx0 && vy0 <= wy1 && vy1 >= wy0;
  },

  _viewInsideRange(xRange, yRange) {
    if (!xRange || !yRange) return false;
    return this._viewInside({ x0: xRange[0], x1: xRange[1], y0: yRange[0], y1: yRange[1] });
  },
});
