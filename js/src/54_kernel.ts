import { payloadBuffers } from "./00_header";
import { buildLutData } from "./10_colormaps";
import { parseColor } from "./20_theme";
import {
  lodAggregateStands, lodAggregateStepWindow, lodApplyDensityUpdate, lodApplyDrill,
  lodDrillServesView, lodDropDrill, lodPromoteCachedDrill, lodRememberDensity,
} from "./45_lod";
import { xyCreateRebinWorker } from "./46_worker";
import { ChartView } from "./50_chartview";

// ChartView <-> kernel comm: debounced density view-requests, streaming
// appends, the inbound message handler, and the deep-zoom drill lifecycle
// (§16). Split out of 50_chartview.js; augments the prototype so `this.*`
// is unchanged.

Object.assign(ChartView.prototype, {
  _scheduleViewRequest(viewOverride = this.view, opts: any = {}) {
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
        // Zoom-in request elision (T12/T13): a view contained in an exact
        // window already on the GPU — the live drill, or a retired cached
        // point window promoted back — is answered locally, so this trace
        // goes neither pending nor on the wire. The seq bump above stands, so
        // an in-flight reply for an older, wider view dies stale instead of
        // yanking the exact marks out from under the view it can't improve.
        const plan = this._drillServesView(g, view) ? null : this._densityRequestPlan(g, view);
        if (!plan) {
          g._lodPendingView = null;
          g._lodPendingSeq = null;
          g._lodPendingAt = null;
          continue;
        }
        // Duplicate of the request already in flight (identical window and
        // screen): keep waiting on ITS seq instead of arming a new one that
        // would kill the incoming reply just to resend the same window —
        // the "constantly re-requesting the same points" loop (#225 notes).
        const dup = this._densityRequestDup(g, plan.win, plotW, plotH, now);
        if (dup) {
          g._lodPendingView = view;
          g._lodPendingSeq = dup.seq;
          g._lodPendingAt = dup.sentAt;
          continue;
        }
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
        const sendNow = this._now();
        for (const g of this.gpuTraces) {
          if (g.tier !== "density") continue;
          // T12/T13 re-check at actual send time: a drill that landed during
          // the debounce — or a reply that moved the view back out of the
          // points band with its step already covered — elides the request
          // it made unnecessary; a drill that died during it re-arms the
          // request the schedule-time check skipped.
          const plan = this._drillServesView(g, view) ? null : this._densityRequestPlan(g, view);
          if (!plan) {
            if (g._lodPendingSeq === seq) {
              g._lodPendingView = null;
              g._lodPendingSeq = null;
              g._lodPendingAt = null;
            }
            continue;
          }
          // Identical-request suppression (T13): the same window at the same
          // screen size is either already answered (nothing to refresh — the
          // reply is deterministic for unchanged data; a data change rebuilds
          // this GPU record and clears the memo) or still in flight (its
          // reply was adopted as this trace's pending marker above).
          const dup = this._densityRequestDup(g, plan.win, plotW, plotH, sendNow);
          if (dup) {
            if (dup.answered && g._lodPendingSeq === seq) {
              g._lodPendingView = null;
              g._lodPendingSeq = null;
              g._lodPendingAt = null;
            }
            continue;
          }
          const win = plan.win;
          this.comm.send({
            type: "density_view", seq, trace: g.trace.id,
            x0: win[0], x1: win[1], y0: win[2], y1: win[3],
            w: plotW, h: plotH,
          });
          // A ladder-step request's reply is the one density reply allowed
          // to repaint a covered view (lodApplyDensityUpdate).
          if (plan.step) g._stepReqWin = win;
          g._lastDensityReq = { win, w: plotW, h: plotH, seq, sentAt: sendNow, answered: false };
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

  // Same request within half an output texel per edge: gesture-end and
  // settle produce windows differing by sub-pixel amounts (field HAR: 0.03%
  // shifts back-to-back), and a grid shifted below half a texel is visually
  // identical — re-shipping it is pure wire waste.
  _densityRequestSame(last, win, plotW, plotH) {
    if (!last || last.w !== plotW || last.h !== plotH) return false;
    const tx = (win[1] - win[0]) / plotW / 2;
    const ty = (win[3] - win[2]) / plotH / 2;
    return Math.abs(last.win[0] - win[0]) <= tx && Math.abs(last.win[1] - win[1]) <= tx &&
      Math.abs(last.win[2] - win[2]) <= ty && Math.abs(last.win[3] - win[3]) <= ty;
  },

  // The last density_view actually sent for this GPU record, when a new
  // request would be its (sub-texel) twin: either already answered (the
  // reply is deterministic for unchanged data, so there is nothing to
  // refresh) or still in flight (bounded by the same 1200ms window as the T8
  // pending hold, so a lost reply can never suppress refresh forever). The
  // memo lives on the GPU record — a rebuild (append, payload update, context
  // restore) starts it fresh, so data changes are never suppressed.
  _densityRequestDup(g, win, plotW, plotH, now) {
    const last = g._lastDensityReq;
    if (!last || !this._densityRequestSame(last, win, plotW, plotH)) return null;
    if (last.answered) return last;
    return now - last.sentAt < 1200 ? last : null;
  },

  // What (if anything) this trace should ask the kernel for at `view`
  // (T13, revised): inside the points band, the RAW VIEW window — the
  // kernel decides the tier there, and its density replies land as facts
  // only; while the aggregate stands, the next LADDER STEP window when
  // every covering texture is coarser than the view's step (a quantized
  // aligned window, so pans resolve to the same request), else nothing.
  // Drill/point-cache service is the caller's earlier check.
  _densityRequestPlan(g, view) {
    const [x0, x1] = this._axisRange(g.xAxis, view);
    const [y0, y1] = this._axisRange(g.yAxis, view);
    if (!lodAggregateStands(this, g, x0, x1, y0, y1)) {
      return {
        win: [Math.min(x0, x1), Math.max(x0, x1), Math.min(y0, y1), Math.max(y0, y1)],
        step: false,
      };
    }
    const win = lodAggregateStepWindow(this, g, x0, x1, y0, y1);
    return win ? { win, step: true } : null;
  },

  // A reply whose seq lost the global race can still be current in substance:
  // duplicate-suppressed requests leave their traces waiting on the ORIGINAL
  // request's seq (T13 — identical window and screen). Accept it only when
  // every trace it updates is still waiting on exactly this seq AND that seq
  // names the trace's last actually-SENT request — a pending marker can
  // outlive a debounce-cancelled send, and a reply matching such a phantom
  // request is stale, not suppressed-current (T5).
  _densityReplyCurrent(msg) {
    const ids = (msg.traces || []).map((u) => Number(u.id));
    if (!ids.length && msg.trace !== undefined) ids.push(Number(msg.trace));
    if (!ids.length) return false;
    return ids.every((id) => {
      const g = this.gpuTraces.find((t) => t.trace.id === id && t.tier === "density");
      return g && g._lodPendingSeq === msg.seq &&
        g._lastDensityReq && g._lastDensityReq.seq === msg.seq;
    });
  },

  // Standalone (kernel-less) density refinement. Debounced like the kernel
  // request path, then the retained §28 sample re-bins in the bundled worker —
  // off the main thread — and applies like a density_update.
  _scheduleSampleRebin(viewOverride = this.view, opts: any = {}) {
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
          tex: this._uploadGrid(
            hd.grid, hd.w, hd.h, hd.normMax || hd.max || 1, hd.rgba, hd.filter,
            this._fillOpacity(g.trace.style),
          ),
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
      // Decode the offset-encoded sample once (f64, §16); the worker keeps it,
      // along with the sample's resolved point colors so re-binned grids keep
      // the mean-color surface (LOD doc §2).
      const cpu = g.sampleOverlay._cpu;
      const n = Math.min(cpu.x.length, cpu.y.length);
      const xs = new Float64Array(n);
      const ys = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        xs[i] = this._decodeValue(cpu.x, cpu.xMeta, i);
        ys[i] = this._decodeValue(cpu.y, cpu.yMeta, i);
      }
      const rgba = this._sampleBinColors(g, n);
      this._rebinWorker.postMessage(
        {
          type: "init", trace: g.trace.id, x: xs.buffer, y: ys.buffer,
          rgba: rgba ? rgba.buffer : null,
        },
        rgba ? [xs.buffer, ys.buffer, rgba.buffer] : [xs.buffer, ys.buffer]
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

  // Straight-alpha RGBA8 per retained-sample point, resolved from the
  // overlay's shipped channel exactly as the point shader draws it — the
  // worker's mean-color source (LOD doc §2). Constant-color traces return
  // null: their count-only grid is tinted by the draw path instead.
  _sampleBinColors(g, n) {
    const overlay = g.sampleOverlay;
    const cpu = overlay && overlay._cpu;
    const spec = overlay && overlay.trace && overlay.trace.color;
    if (!cpu || !spec || spec.mode === "constant" || spec.mode === "match_fill") return null;
    if (spec.mode === "direct_rgba" && cpu.rgba) {
      return new Uint8Array(cpu.rgba.subarray(0, n * 4));
    }
    if (!cpu.color) return null;
    const out = new Uint8Array(n * 4);
    if (spec.mode === "continuous") {
      const lut = buildLutData(spec.colormap);
      for (let i = 0; i < n; i++) {
        const at = Math.round(Math.max(0, Math.min(1, cpu.color[i])) * 255) * 4;
        out[i * 4] = lut[at];
        out[i * 4 + 1] = lut[at + 1];
        out[i * 4 + 2] = lut[at + 2];
        out[i * 4 + 3] = 255;
      }
      return out;
    }
    if (spec.mode === "categorical" && Array.isArray(spec.palette) && spec.palette.length) {
      const palette = spec.palette.map((c) => parseColor(this.root, c, [0, 0, 0, 1]));
      for (let i = 0; i < n; i++) {
        const p = palette[Math.round(cpu.color[i]) % palette.length];
        out[i * 4] = Math.round(p[0] * 255);
        out[i * 4 + 1] = Math.round(p[1] * 255);
        out[i * 4 + 2] = Math.round(p[2] * 255);
        out[i * 4 + 3] = Math.round(p[3] * 255);
      }
      return out;
    }
    return null;
  },

  _onRebinResult(msg) {
    if (this._destroyed || this._glLost || !msg || msg.type !== "grid" || msg.seq !== this.seq) return;
    const g = this.gpuTraces.find((t) => t.trace.id === msg.trace && t.tier === "density");
    if (!g) return;
    const grid = new Float32Array(msg.grid);
    const rgba = msg.rgba ? new Uint8Array(msg.rgba) : null;
    this._applySampleRebinGrid(g, {
      w: msg.w, h: msg.h, max: msg.max, normMax: msg.max,
      colormap: g.density.colormap,
      xRange: [msg.x0, msg.x1], yRange: [msg.y0, msg.y1],
      grid,
      rgba,
      tex: this._uploadGrid(
        grid, msg.w, msg.h, msg.max || 1, rgba, "linear",
        this._fillOpacity(g.trace.style),
      ),
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
  // stale-while-revalidate request path (§17). The payload arrives in
  // whichever layout the spec declares — split (per-column buffers, the
  // current kernel) or a legacy packed blob from an older saved state.
  _applyAppend(msg, buffers) {
    const spec = msg.spec;
    if (!spec || !spec.traces) return;
    const raw = spec.buffer_layout === "split" ? buffers : buffers && buffers[0];
    if (raw == null) return;
    const payload = payloadBuffers(spec, raw);
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
    const nextHome = {
      x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
      y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
    };
    let nextView = { ...this.view };
    if (atHome) {
      nextView = { ...nextHome };
    } else if (pinnedRight) {
      const w = this.view.x1 - this.view.x0;
      nextView = { ...this.view, x1: nextHome.x1, x0: nextHome.x1 - w };
    }
    const animated = !!spec.animation || spec.traces.some((trace) => !!trace.animation);
    if (animated && !this._glLost && this.gl && this.updatePayload(spec, payload)) {
      // updatePayload owns previous/next GPU lifetime and matching. Preserve
      // append's follow policy instead of always animating to the new home
      // domain (history inspection must remain stationary).
      if (this._transitionView) this._transitionView.to = { ...nextView };
      else this.view = { ...nextView };
      this._scheduleViewRequest(nextView, { delay: 0 });
      return;
    }
    // Swap spec + retained payload together so GL context restore (§27)
    // rebuilds the streamed state, not the initial one.
    this.spec = spec;
    this.axes = this._normalizeAxes(spec);
    this._payload = payload;
    this.view0 = this._copyView({
      ranges: Object.fromEntries(Object.entries(this.axes).map(([id, axis]: any) => [id, [...axis.range]])),
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
      this.gpuTraces[i] = this._buildTrace(payload, ts);
    }
    // Rebuilt entries lost their transient legend-toggle fields; re-apply
    // from the view-held state (interaction spec §10).
    this._reapplyLegendVisibility();
    this._updatePickable();
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
      if (msg.seq !== undefined && msg.seq !== this.seq && !this._densityReplyCurrent(msg)) return;
      const densityTraces = msg.traces || [];
      const pendingTraceIds = new Set(densityTraces.map((upd) => Number(upd.id)));
      if (pendingTraceIds.size === 0 && msg.trace !== undefined) {
        pendingTraceIds.add(Number(msg.trace));
      }
      const clearAllPending = pendingTraceIds.size === 0 && msg.stale;
      const clearPending = (g) => {
        if (msg.seq !== undefined && g._lodPendingSeq !== msg.seq) return;
        // The identical-request memo (T13): this window is now answered, so a
        // later request for the same window and screen sends nothing.
        if (g._lastDensityReq && g._lastDensityReq.seq === msg.seq) {
          g._lastDensityReq.answered = true;
        }
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
        // Filter-state guard (interaction spec §10 / §34): a reply computed
        // under a different hidden-category set than the client's current
        // one would render a stale predicate's aggregate. The toggle that
        // changed the set already scheduled a fresh request.
        const ti = this.gpuTraces.indexOf(g);
        const want = Array.from(
          (this._legendOffCats && this._legendOffCats.get(ti)) || []
        ).sort((a: any, b: any) => a - b);
        const got = (upd.filter && upd.filter.hidden_categories) || [];
        if (want.join(",") !== got.join(",")) continue;
        if (upd.mode === "points") { this._applyDrill(g, upd, buffers); continue; }
        lodApplyDensityUpdate(this, g, upd, buffers);
      }
      // Drill state changes what's pickable; hover needs the FBO ready.
      this._updatePickable();
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
        const detail = {
          row: msg.row,
          trace: msg.row.trace,
          index: msg.row.index,
          exact: true,
          view: this._eventView("hover"),
        };
        // §7.1 payload on the exact re-dispatch too, when the cursor is
        // still known (the two-stage upgrade keeps `exact: true`).
        if (xy) {
          Object.assign(detail, this._hoverPayload(
            msg.row, this._hoverTarget, xy.clientX, xy.clientY, true,
          ));
        }
        this._dispatchChartEvent("hover", detail);
      }
    } else if (msg.type === "selection") {
      // Enriched replies echo the brush geometry (channel.py include_rows):
      // adopt it so a view that never saw the drag (republish restore) can
      // still re-derive masks across later drill swaps (§34).
      if (msg.bounds) this._lastBrush = { mode: "box", ...msg.bounds };
      else if (msg.polygon) this._lastBrush = { mode: "poly", points: msg.polygon };
      if (!msg.traces || !msg.traces.length) this._lastBrush = null;
      this._applySelectionBuffers(msg, buffers);
      this._selectionCount = msg.total || 0;
      this.draw();
      if (this._interactionFlag("select", true)) {
        this._dispatchChartEvent("select", {
          total: this._selectionCount,
          view: this._eventView("select"),
        });
      }
    } else if (msg.type === "state_patch") {
      // Programmatic write (view-state.md §8): the same §3 mutation path a
      // gesture takes, tagged source "api" so bridges can filter their echo.
      this._applyStatePatch(msg.state, {
        source: "api",
        animate: msg.animate === true,
        history: msg.history !== false,
      });
    } else if (msg.type === "view_nav") {
      if (msg.op === "reset") this._navReset(msg.axes);
    } else if (msg.type === "selection_rows") {
      this._applyRowsSelection(msg, buffers);
    }
  },

  // Shared mask application for kernel "selection" replies and pushed
  // "selection_rows" messages — both carry the same per-trace index buffers.
  _applySelectionBuffers(msg, buffers) {
    if (!msg.traces || !msg.traces.length) {
      for (const g of this.gpuTraces) {
        g.selActive = false;
        if (g.drill) g.drill.selActive = false;
      }
      return;
    }
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
      // Category-filtered buffers (interaction spec §10) draw a subset: the
      // kernel's shipped-space indices land on their filtered positions.
      const inv = pg._visInv;
      for (let i = 0; i < idx.length; i++) {
        const j = inv ? (idx[i] < inv.length ? inv[idx[i]] : -1) : idx[i];
        if (j >= 0 && j < pg.n) mask[j] = 1;
      }
      this._applySelMask(pg, mask);
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

  // Can `view` be answered locally with no kernel round-trip? True for an
  // exact (reduction "none"), non-dying live drill whose window contains the
  // view's per-axis ranges (T12), and — failing that — for any retired cached
  // point window that does, which is promoted back to the live drill on the
  // spot (T13). Both only until the zoom outgrows the §16 f32 encode
  // precision.
  _drillServesView(g, view) {
    if (!g) return false;
    const [x0, x1] = this._axisRange(g.xAxis, view);
    const [y0, y1] = this._axisRange(g.yAxis, view);
    if (lodDrillServesView(g, x0, x1, y0, y1)) return true;
    return lodPromoteCachedDrill(this, g, x0, x1, y0, y1);
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
