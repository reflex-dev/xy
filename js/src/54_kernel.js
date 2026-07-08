// ChartView <-> kernel comm: debounced density view-requests, streaming
// appends, the inbound message handler, and the deep-zoom drill lifecycle
// (§16). Split out of 50_chartview.js; augments the prototype so `this.*`
// is unchanged.

Object.assign(ChartView.prototype, {
  _scheduleViewRequest(viewOverride = this.view, opts = {}) {
    if (this._destroyed) return;
    if (!this.comm) return;
    const needsDecimated = this.spec.traces.some((t) => t.tier === "decimated");
    const needsDensity = this.gpuTraces.some((g) => g.tier === "density");
    if (!needsDecimated && !needsDensity) return;
    const seq = opts.seq ?? ++this.seq;
    const view = { ...viewOverride };
    const plotW = Math.round(this.plot.w);
    const plotH = Math.round(this.plot.h);
    if (needsDensity) {
      const now = performance.now();
      for (const g of this.gpuTraces) {
        if (g.tier !== "density") continue;
        g._lodPendingView = view;
        g._lodPendingSeq = seq;
        g._lodPendingAt = now;
      }
    }
    let delay = opts.delay ?? 120;
    if (opts.maxWait !== undefined && opts.maxWait !== null) {
      const now = performance.now();
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
          this.comm.send({
            type: "density_view", seq, trace: g.trace.id,
            x0: Math.min(view.x0, view.x1), x1: Math.max(view.x0, view.x1),
            y0: Math.min(view.y0, view.y1), y1: Math.max(view.y0, view.y1),
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
    const blob = bytesToArrayBuffer(blobRaw);
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
    const texSeen = new Set();
    for (const id of msg.affected || []) {
      const i = this.gpuTraces.findIndex((g) => g.trace.id === id);
      const ts = spec.traces.find((t) => t.id === id);
      if (i < 0 || !ts) continue;
      this._destroyTraceResources(this.gpuTraces[i], texSeen);
      this.gpuTraces[i] = this._buildTrace(blob, ts);
    }
    this.view0 = {
      x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
      y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
    };
    if (atHome) {
      this.view = { ...this.view0 };
    } else if (pinnedRight) {
      const w = this.view.x1 - this.view.x0;
      this.view = { ...this.view, x1: this.view0.x1, x0: this.view0.x1 - w };
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
        const sm = this._smoothArrays(g.trace, xArr, yArr, bArr, n);
        gl.bindBuffer(gl.ARRAY_BUFFER, g.xBuf);
        gl.bufferData(gl.ARRAY_BUFFER, sm ? sm.x : xArr, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, g.yBuf);
        gl.bufferData(gl.ARRAY_BUFFER, sm ? sm.y : yArr, gl.STATIC_DRAW);
        g.xMeta = { ...g.xMeta, offset: upd.x.offset, scale: upd.x.scale };
        g.yMeta = { ...g.yMeta, offset: upd.y.offset, scale: upd.y.scale };
        if (bArr) {
          gl.bindBuffer(gl.ARRAY_BUFFER, g.baseBuf);
          gl.bufferData(gl.ARRAY_BUFFER, sm ? sm.extra : bArr, gl.STATIC_DRAW);
          g.baseMeta = { ...g.baseMeta, offset: upd.base.offset, scale: upd.base.scale };
        }
        g.n = sm ? sm.n : n;
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
      if (!msg.row) { this.tooltip.style.display = "none"; return; }
      this._lastRow = msg.row;
      const xy = this._lastHoverXY;
      if (xy) this._renderTooltip(msg.row, xy.clientX, xy.clientY);
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

  _viewInsideRange(xRange, yRange) {
    if (!xRange || !yRange) return false;
    return this._viewInside({ x0: xRange[0], x1: xRange[1], y0: yRange[0], y1: yRange[1] });
  },
});
