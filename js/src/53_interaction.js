// ChartView interaction: pointer/drag/wheel wiring, crosshair, box + lasso
// selection, the modebar, and the animated view (pan/zoom) state machine.
// Split out of 50_chartview.js; augments the prototype so `this.*` is
// unchanged. Method bodies reference kernel-comm helpers (54) at call time.

Object.assign(ChartView.prototype, {
  _initInteraction() {
    const c = this.canvas;
    let drag = null;
    let band = null;

    // Rubber-band overlay for box-select (§34) — DOM, above the canvas.
    // border/background come from the stylesheet (--chart-selection*).
    this.selRect = document.createElement("div");
    this.selRect.style.cssText = "position:absolute;display:none;pointer-events:none;z-index:4;";
    this._applySlot(this.selRect, "selection");
    this.root.appendChild(this.selRect);

    if (this._interactionFlag("crosshair")) {
      this.crosshairX = document.createElement("div");
      this.crosshairX.style.cssText =
        "position:absolute;display:none;pointer-events:none;z-index:3;width:1px;";
      this._applySlot(this.crosshairX, "crosshair_x");
      this.root.appendChild(this.crosshairX);
      this.crosshairY = document.createElement("div");
      this.crosshairY.style.cssText =
        "position:absolute;display:none;pointer-events:none;z-index:3;height:1px;";
      this._applySlot(this.crosshairY, "crosshair_y");
      this.root.appendChild(this.crosshairY);
    }

    const dataAt = (clientX, clientY) => {
      const r = c.getBoundingClientRect();
      return this._dataFromCanvas(clientX - r.left, clientY - r.top);
    };

    this._listen(c, "pointerdown", (e) => {
      this._cancelViewAnimation();
      // Shift-drag box-selects (§34); a "zoom" modebar toggle turns a plain drag
      // into a box-zoom; otherwise a plain drag pans.
      const canBrush = this._interactionFlag("brush", true) && this._interactionFlag("select", true);
      const mode = e.shiftKey && canBrush && this._pickable ? "select"
        : this.dragMode === "zoom" ? "zoom" : null;
      if (mode) {
        band = { mode, sx: e.clientX, sy: e.clientY, d0: dataAt(e.clientX, e.clientY) };
        c.setPointerCapture(e.pointerId);
        this.tooltip.style.display = "none";
        return;
      }
      drag = { px: e.clientX, py: e.clientY, view: { ...this.view }, moved: false };
      c.setPointerCapture(e.pointerId);
      this.tooltip.style.display = "none";
    });
    this._listen(c, "pointermove", (e) => {
      if (band) { this._updateBand(band, e); return; }
      if (drag) {
        drag.moved = true;
        const { x0, x1, y0, y1 } = drag.view;
        const xa = this._axis("x");
        const ya = this._axis("y");
        const cx0 = this._axisCoord(xa, x0), cx1 = this._axisCoord(xa, x1);
        const cy0 = this._axisCoord(ya, y0), cy1 = this._axisCoord(ya, y1);
        const dx = ((e.clientX - drag.px) / this.plot.w) * (cx1 - cx0);
        const dy = ((e.clientY - drag.py) / this.plot.h) * (cy1 - cy0);
        this.view = {
          x0: this._axisValue(xa, cx0 - dx),
          x1: this._axisValue(xa, cx1 - dx),
          y0: this._axisValue(ya, cy0 + dy),
          y1: this._axisValue(ya, cy1 + dy),
        };
        this.draw();
        this._scheduleViewRequest();
        this._emitViewChange("pan");
        return;
      }
      this._updateCrosshair(e);
      this._hover(e);
    });
    const end = (e) => {
      if (band) {
        this.selRect.style.display = "none";
        const d1 = dataAt(e.clientX, e.clientY);
        const moved = Math.abs(e.clientX - band.sx) > 3 || Math.abs(e.clientY - band.sy) > 3;
        if (moved) {
          if (band.mode === "zoom") this._zoomToBox(band.d0, d1, true);
          else this._sendSelect(band.d0, d1);
          this._ignoreNextClick = true;
        }
        band = null;
        return;
      }
      if (drag && drag.moved) this._ignoreNextClick = true;
      if (drag && !drag.moved) this.tooltip.style.display = "none";
      drag = null;
    };
    this._listen(c, "pointerup", end);
    this._listen(c, "pointercancel", () => { this.selRect.style.display = "none"; band = null; drag = null; });
    this._listen(c, "pointerleave", () => {
      const hadHover = this._hoverId !== -1;
      this._hoverId = -1;
      this._hoverTarget = null;
      this.tooltip.style.display = "none";
      this._hideCrosshair();
      if (this._interactionFlag("hover")) {
        this._dispatchChartEvent("leave", { view: this._eventView("leave") });
      }
      // Highlight-clear only — the pick snapshot stays valid (§17).
      if (hadHover) this._drawKeepPick();
    });
    this._listen(c, "click", (e) => this._click(e));

    this._listen(c, "wheel", (e) => {
      e.preventDefault();
      const f = Math.pow(1.0015, e.deltaY);
      const r = c.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width;
      const fy = 1 - (e.clientY - r.top) / r.height;
      this._queueWheelZoom(f, fx, fy);
    }, { passive: false });

    this._listen(c, "dblclick", () => {
      this._clearSelection();
      this._setView(this.view0, { animate: true });
    });
  },

  _updateCrosshair(e) {
    if (!this.crosshairX || !this.crosshairY) return;
    const rect = this.canvas.getBoundingClientRect();
    const rootRect = this.root.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    if (x < 0 || x > rect.width || y < 0 || y > rect.height) {
      this._hideCrosshair();
      return;
    }
    const left = e.clientX - rootRect.left;
    const top = e.clientY - rootRect.top;
    this.crosshairX.style.display = "block";
    this.crosshairX.style.left = left + "px";
    this.crosshairX.style.top = this.plot.y + "px";
    this.crosshairX.style.height = this.plot.h + "px";
    this.crosshairY.style.display = "block";
    this.crosshairY.style.left = this.plot.x + "px";
    this.crosshairY.style.top = top + "px";
    this.crosshairY.style.width = this.plot.w + "px";
  },

  _hideCrosshair() {
    if (this.crosshairX) this.crosshairX.style.display = "none";
    if (this.crosshairY) this.crosshairY.style.display = "none";
  },

  _click(e) {
    if (this._ignoreNextClick) {
      this._ignoreNextClick = false;
      return;
    }
    if (!this._interactionFlag("click")) return;
    const rect = this.canvas.getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;
    const [x, y] = this._dataFromCanvas(cssX, cssY);
    const hit = this._pickAt(cssX, cssY) || this._hoverAt(cssX, cssY);
    const detail = {
      x,
      y,
      view: this._eventView("click"),
      row: hit && this._localRow ? this._localRow(hit) : null,
      trace: hit ? hit.trace : null,
      index: hit ? hit.index : null,
    };
    this._dispatchChartEvent("click", detail);
    if (hit && this.comm) {
      const msg = { type: "click", trace: hit.trace, index: hit.index };
      const g = hit.g;
      if (g && g.tier === "density" && g.drill && g.drill.seq !== undefined) {
        msg.drill_seq = g.drill.seq;
      }
      this.comm.send(msg);
    }
  },

  _updateBand(band, e) {
    const rect = this.canvas.getBoundingClientRect();
    const rootRect = this.root.getBoundingClientRect();
    const x = Math.min(band.sx, e.clientX) - rootRect.left;
    const y = Math.min(band.sy, e.clientY) - rootRect.top;
    const w = Math.abs(e.clientX - band.sx);
    const h = Math.abs(e.clientY - band.sy);
    // clamp to plot area
    const px = this.plot.x, py = this.plot.y;
    const x2 = Math.min(x + w, px + this.plot.w), y2 = Math.min(y + h, py + this.plot.h);
    const cx = Math.max(x, px), cy = Math.max(y, py);
    // Band paint (border/background) is a defeatable :where() default keyed on
    // data-fc-band, NOT pinned inline — otherwise a `class_names={"selection":…}`
    // utility (or `styles[selection]`) would lose to the inline style, breaking
    // the "your styles always win" contract for this one slot. Only the mode
    // discriminator and structural position/size stay inline (matches §36).
    this.selRect.dataset.fcBand = band.mode === "zoom" ? "zoom" : "select";
    this.selRect.style.display = "block";
    this.selRect.style.left = cx + "px";
    this.selRect.style.top = cy + "px";
    this.selRect.style.width = Math.max(0, x2 - cx) + "px";
    this.selRect.style.height = Math.max(0, y2 - cy) + "px";
    void rect;
  },

  _sendSelect(d0, d1) {
    const x0 = Math.min(d0[0], d1[0]), x1 = Math.max(d0[0], d1[0]);
    const y0 = Math.min(d0[1], d1[1]), y1 = Math.max(d0[1], d1[1]);
    const range = { x0, x1, y0, y1 };
    this._dispatchChartEvent("brush", { range, view: this._eventView("brush") });
    if (this.comm) {
      this.comm.send({ type: "select", x0, x1, y0, y1 });
    } else {
      this._selectLocal(x0, x1, y0, y1); // standalone: compute from resident f32
    }
  },

  // Standalone selection (no kernel): mask the retained CPU f32 columns (§37).
  _selectLocal(x0, x1, y0, y1) {
    let total = 0;
    for (const g of this.gpuTraces) {
      // _cpu only exists where the standalone entry retained copies (retainCpu).
      if (!g._cpu || g.tier === "density") continue;
      const cx = g._cpu.x, cy = g._cpu.y;
      const xMeta = g._cpu.xMeta || g.xMeta;
      const yMeta = g._cpu.yMeta || g.yMeta;
      const ox = xMeta.offset, sx = xMeta.scale || 1;
      const oy = yMeta.offset, sy = yMeta.scale || 1;
      const mask = new Float32Array(g.n);
      let cnt = 0;
      for (let i = 0; i < g.n; i++) {
        const dx = cx[i] / sx + ox, dy = cy[i] / sy + oy;
        if (dx >= x0 && dx <= x1 && dy >= y0 && dy <= y1) { mask[i] = 1; cnt++; }
      }
      this._applySelMask(g, mask);
      total += cnt;
    }
    this._selectionCount = total;
    this.draw();
    this._dispatchChartEvent("select", {
      total,
      range: { x0, x1, y0, y1 },
      view: this._eventView("select"),
    });
  },

  _applySelMask(g, maskF32) {
    const gl = this.gl;
    if (!g.selBuf) g.selBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, g.selBuf);
    gl.bufferData(gl.ARRAY_BUFFER, maskF32, gl.STATIC_DRAW);
    g.selActive = true;
  },

  _clearSelection() {
    for (const g of this.gpuTraces) {
      g.selActive = false;
      if (g.drill) g.drill.selActive = false;
    }
    this._selectionCount = 0;
    if (this._interactionFlag("select", true)) {
      if (this.comm) this.comm.send({ type: "select_clear" });
      this._dispatchChartEvent("select", { total: 0, view: this._eventView("select_clear") });
    }
  },

  _clampModebar(left, top) {
    const bar = this._modebar;
    if (!bar || !this.root) return;
    const currentLeft = left ?? (Number.parseFloat(bar.style.left) || 0);
    const currentTop = top ?? (Number.parseFloat(bar.style.top) || 0);
    const maxLeft = Math.max(0, this.root.clientWidth - bar.offsetWidth);
    const maxTop = Math.max(0, this.root.clientHeight - bar.offsetHeight);
    bar.style.left = `${Math.max(0, Math.min(maxLeft, currentLeft))}px`;
    bar.style.top = `${Math.max(0, Math.min(maxTop, currentTop))}px`;
  },

  _buildModebar(root) {
    if (this.spec.show_modebar === false) return;
    const bar = document.createElement("div");
    // The modebar is chrome, so keep it out of the way until the chart is
    // hovered (or a keyboard user focuses one of its controls). Layout +
    // visibility state stay inline; the box styling is in the stylesheet.
    bar.style.cssText =
      `position:absolute;top:${this.plot.y + 4}px;left:${this.plot.x + 4}px;z-index:6;` +
      "display:flex;opacity:0;pointer-events:none;transition:opacity .15s;";
    this._applySlot(bar, "modebar");
    this._modebar = bar;
    this._modeBtns = {};
    this._modebarCollapsed = false;
    this._modebarMoved = false;
    bar.dataset.fcCollapsed = "false";

    const setVisible = (visible) => {
      const show = visible || this._modebarDragging || bar.contains(document.activeElement);
      bar.style.opacity = show ? "1" : "0";
      bar.style.pointerEvents = show ? "auto" : "none";
    };
    this._listen(root, "pointerenter", () => setVisible(true));
    this._listen(root, "pointerleave", () => setVisible(false));
    this._listen(bar, "focusin", () => setVisible(true));
    this._listen(bar, "focusout", () => {
      if (!root.matches(":hover")) setVisible(false);
    });

    // A dedicated grip keeps button clicks distinct from toolbar movement.
    // Pointer capture lets a drag finish cleanly even if it leaves the chart;
    // the coordinates are still clamped to the chart root below.
    const grip = document.createElement("button");
    grip.type = "button";
    grip.title = "Double-click to collapse; drag to move";
    grip.setAttribute("aria-label", "Collapse toolbar");
    grip.setAttribute("aria-expanded", "true");
    grip.dataset.fcModebarDragHandle = "";
    grip.innerHTML = this._icon("drag");
    grip.style.cssText =
      "display:flex;align-items:center;justify-content:center;pointer-events:auto;touch-action:none;";
    this._applySlot(grip, "modebar_button");
    bar.appendChild(grip);

    const DOUBLE_CLICK_MS = 500;
    const DRAG_THRESHOLD_PX = 6;
    let modebarDrag = null;
    let lastGripDown = 0;
    const setCollapsed = (collapsed) => {
      this._modebarCollapsed = collapsed;
      bar.dataset.fcCollapsed = String(collapsed);
      for (const button of bar.querySelectorAll("button")) {
        if (button !== grip) {
          button.hidden = collapsed;
          button.style.display = collapsed ? "none" : "flex";
        }
      }
      grip.title = collapsed
        ? "Double-click to expand; drag to move"
        : "Double-click to collapse; drag to move";
      grip.setAttribute("aria-label", collapsed ? "Expand toolbar" : "Collapse toolbar");
      grip.setAttribute("aria-expanded", String(!collapsed));
      this._fitModebar();
    };
    const toggleModebar = () => setCollapsed(!this._modebarCollapsed);
    this._listen(grip, "pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      e.stopPropagation();
      const now = e.timeStamp || performance.now();
      const doubleClick = lastGripDown > 0 && now - lastGripDown <= DOUBLE_CLICK_MS;
      lastGripDown = doubleClick ? 0 : now;
      const barRect = bar.getBoundingClientRect();
      modebarDrag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        dx: e.clientX - barRect.left,
        dy: e.clientY - barRect.top,
        moved: false,
      };
      setVisible(true);
      if (doubleClick) toggleModebar();
    });
    this._listen(grip, "pointermove", (e) => {
      if (!modebarDrag || e.pointerId !== modebarDrag.pointerId) return;
      const distance = Math.hypot(e.clientX - modebarDrag.startX, e.clientY - modebarDrag.startY);
      if (!modebarDrag.moved) {
        if (distance < DRAG_THRESHOLD_PX) return;
        modebarDrag.moved = true;
        lastGripDown = 0;
        this._modebarDragging = true;
        this._modebarMoved = true;
        bar.style.transition = "none";
        try { grip.setPointerCapture(e.pointerId); } catch (_err) { /* synthetic event */ }
      }
      const rootRect = root.getBoundingClientRect();
      const left = e.clientX - rootRect.left - modebarDrag.dx;
      const top = e.clientY - rootRect.top - modebarDrag.dy;
      this._clampModebar(left, top);
    });
    const endModebarDrag = (e) => {
      if (!modebarDrag || e.pointerId !== modebarDrag.pointerId) return;
      const moved = modebarDrag.moved;
      const cancelled = e.type === "pointercancel";
      modebarDrag = null;
      this._modebarDragging = false;
      bar.style.transition = "opacity .15s";
      setVisible(root.matches(":hover"));
      if (moved || cancelled) {
        lastGripDown = 0;
      }
    };
    this._listen(grip, "pointerup", endModebarDrag);
    this._listen(grip, "pointercancel", endModebarDrag);
    this._listen(grip, "click", (e) => e.stopPropagation());
    this._listen(grip, "dblclick", (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
    this._listen(grip, "keydown", (e) => {
      if (e.repeat || (e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      e.stopPropagation();
      toggleModebar();
    });

    const mk = (name, title, onClick, toggles) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = title;
      b.innerHTML = this._icon(name);
      // Box/size/color are stylesheet defaults (--chart-axis); only layout +
      // interactivity stay inline so a user class can restyle the button.
      b.style.cssText =
        "display:flex;align-items:center;justify-content:center;pointer-events:auto;";
      this._applySlot(b, "modebar_button");
      this._listen(b, "pointerdown", (e) => e.stopPropagation());
      this._listen(b, "click", (e) => { e.stopPropagation(); onClick(); });
      bar.appendChild(b);
      if (toggles) this._modeBtns[toggles] = b;
      return b;
    };

    mk("zoomin", "Zoom in", () => this._zoomBy(0.5, true));
    mk("zoomout", "Zoom out", () => this._zoomBy(2, true));
    mk("pan", "Pan", () => this._setDragMode("pan"), "pan");
    mk("zoom", "Box zoom", () => this._setDragMode("zoom"), "zoom");
    mk("reset", "Reset view", () => {
      this._clearSelection();
      this._setView(this.view0, { animate: true });
    });
    root.appendChild(bar);
    this._fitModebar();
    // The pointer may already be over a chart that mounted beneath it, in
    // which case no pointerenter fires after these listeners are installed.
    setVisible(root.matches(":hover"));
    this._setDragMode(this.dragMode);
  },

  // The modebar is unusable chrome once the plot box can't contain it — in a
  // dense subplot grid the overflowing buttons alone grew scrollbars on every
  // panel. Hidden is a fit state, not removal: a fluid resize re-checks and
  // can bring the bar back. Wheel/drag zoom and pan keep working without it.
  _fitModebar() {
    const bar = this._modebar;
    if (!bar) return;
    if (!this._modebarMoved) {
      bar.style.top = `${this.plot.y + 4}px`;
      bar.style.left = `${this.plot.x + 4}px`;
    }
    bar.style.display = "flex"; // measurable before the verdict
    const fits =
      bar.offsetWidth + 8 <= this.plot.w && bar.offsetHeight + 8 <= this.plot.h;
    if (!fits) {
      bar.style.display = "none";
      return;
    }
    this._clampModebar();
  },

  _setDragMode(mode) {
    this.dragMode = mode;
    // Cursor telegraphs the gesture (grab for pan, crosshair for box-zoom) but
    // lives in the defeatable :where([data-fc-slot="canvas"]) stylesheet keyed on
    // this attribute — inline cursor would beat a user's cursor-* utility class.
    if (this.canvas) this.canvas.dataset.fcDragmode = mode;
    // Active state is a class (defeatable via the stylesheet's :where rule /
    // --chart-modebar-active), not an inline background that would beat classes.
    for (const [name, btn] of Object.entries(this._modeBtns || {})) {
      btn.classList.toggle("fc-active", name === mode);
    }
  },

  _prefersReducedMotion() {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
  },

  _cancelViewAnimation() {
    if (this._animRaf) cancelAnimationFrame(this._animRaf);
    this._animRaf = null;
    this._viewAnim = null;
  },

  _setView(next, opts = {}) {
    if (this._destroyed) return;
    const target = { x0: next.x0, x1: next.x1, y0: next.y0, y1: next.y1 };
    const animate = opts.animate === true && !this._prefersReducedMotion();
    const duration = opts.duration || 180;
    if (!animate || duration <= 0) {
      this._cancelViewAnimation();
      this.view = target;
      this.draw();
      if (opts.request !== false) this._scheduleViewRequest();
      this._emitViewChange(opts.source || "view", { broadcast: opts.broadcast });
      return;
    }

    clearTimeout(this._viewTimer);
    this.seq += 1; // invalidate in-flight LOD replies for the pre-animation view
    const request = opts.request !== false;
    const requestDelay = opts.requestDelay ?? Math.min(55, Math.max(24, duration * 0.35));
    const requestMaxWait = opts.requestMaxWait ?? 130;
    if (request) {
      this._scheduleViewRequest(target, { seq: this.seq, delay: requestDelay, maxWait: requestMaxWait });
    }
    const now = this._now();
    const tau = Math.max(18, duration / 5);
    if (this._viewAnim) {
      this._viewAnim.target = target;
      this._viewAnim.tau = tau;
      return;
    }

    this._viewAnim = {
      target,
      last: now,
      tau,
    };
    const lerp = (a, b, t) => a + (b - a) * t;
    const span = (v) => Math.max(Math.abs(v.x1 - v.x0), Math.abs(v.y1 - v.y0), 1e-12);
    const closeEnough = (a, b) => {
      const tol = span(b) * 1e-4;
      return Math.max(
        Math.abs(a.x0 - b.x0), Math.abs(a.x1 - b.x1),
        Math.abs(a.y0 - b.y0), Math.abs(a.y1 - b.y1)) <= tol;
    };
    const step = (nowFrame) => {
      if (this._destroyed) { this._animRaf = null; return; }
      const anim = this._viewAnim;
      if (!anim) { this._animRaf = null; return; }
      const dt = Math.max(0, Math.min(64, nowFrame - anim.last));
      anim.last = nowFrame;
      const k = 1 - Math.exp(-dt / anim.tau);
      const t = closeEnough(this.view, anim.target) ? 1 : k;
      this.view = {
        x0: lerp(this.view.x0, anim.target.x0, t),
        x1: lerp(this.view.x1, anim.target.x1, t),
        y0: lerp(this.view.y0, anim.target.y0, t),
        y1: lerp(this.view.y1, anim.target.y1, t),
      };
      if (t < 1) {
        this.draw();
        this._animRaf = requestAnimationFrame(step);
      } else {
        this._animRaf = null;
        this._viewAnim = null;
        this.view = anim.target;
        this._lastLabelDraw = null;
        this.draw();
        this._emitViewChange(opts.source || "view", { broadcast: opts.broadcast });
      }
    };
    this._animRaf = requestAnimationFrame(step);
  },

  // Center-anchored zoom (f<1 in, f>1 out) — the modebar buttons; wheel is
  // cursor-anchored. Shares the §16 precision floor so we never zoom past f32.
  _zoomBy(f, animate = false) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const { x0, x1, y0, y1 } = base;
    const xr = this._zoomAxisRange("x", x0, x1, f, 0.5);
    const yr = this._zoomAxisRange("y", y0, y1, f, 0.5);
    if (!xr || !yr) return;
    this._setView({ x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] }, { animate });
  },

  _zoomAxisRange(axisId, lo, hi, f, anchorFrac) {
    const axis = this._axis(axisId);
    const c0 = this._axisCoord(axis, lo);
    const c1 = this._axisCoord(axis, hi);
    if (![c0, c1].every(Number.isFinite) || c0 === c1) return null;
    const ca = c0 + anchorFrac * (c1 - c0);
    if (f < 1) {
      const minSpan = Math.max(Math.abs(ca), 1e-30) * 1e-12;
      if (Math.abs((c1 - c0) * f) < minSpan) return null;
    }
    return [
      this._axisValue(axis, ca - (ca - c0) * f),
      this._axisValue(axis, ca + (c1 - ca) * f),
    ];
  },

  _zoomAt(f, fx, fy, animate = false, duration = 120) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const { x0, x1, y0, y1 } = base;
    const xr = this._zoomAxisRange("x", x0, x1, f, fx);
    const yr = this._zoomAxisRange("y", y0, y1, f, fy);
    if (!xr || !yr) return;
    this._setView({ x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] }, { animate, duration });
  },

  _queueWheelZoom(factor, fx, fy) {
    if (!Number.isFinite(factor) || factor <= 0) return;
    if (!this._pendingWheelZoom) {
      this._pendingWheelZoom = { factor: 1, fx, fy };
    }
    this._pendingWheelZoom.factor *= factor;
    this._pendingWheelZoom.fx = fx;
    this._pendingWheelZoom.fy = fy;
    if (this._wheelZoomRaf) return;
    this._wheelZoomRaf = requestAnimationFrame(() => {
      this._wheelZoomRaf = null;
      const pending = this._pendingWheelZoom;
      this._pendingWheelZoom = null;
      if (!pending || this._destroyed) return;
      this._zoomAt(pending.factor, pending.fx, pending.fy, false);
    });
  },

  // Box-zoom: fit the view to the dragged data rectangle (§16 precision floor;
  // ignore degenerate drags that would collapse a span below f32 resolution).
  _zoomToBox(d0, d1, animate = false) {
    const xa = this._axis("x");
    const ya = this._axis("y");
    const xlo = Math.min(d0[0], d1[0]), xhi = Math.max(d0[0], d1[0]);
    const ylo = Math.min(d0[1], d1[1]), yhi = Math.max(d0[1], d1[1]);
    const cx0 = this._axisCoord(xa, xlo), cx1 = this._axisCoord(xa, xhi);
    const cy0 = this._axisCoord(ya, ylo), cy1 = this._axisCoord(ya, yhi);
    if (![cx0, cx1, cy0, cy1].every(Number.isFinite)) return;
    const minSpanX = Math.max(Math.abs(cx0), Math.abs(cx1), 1e-30) * 1e-12;
    const minSpanY = Math.max(Math.abs(cy0), Math.abs(cy1), 1e-30) * 1e-12;
    if (Math.abs(cx1 - cx0) < minSpanX || Math.abs(cy1 - cy0) < minSpanY) return;
    const xReversed = this.view.x1 < this.view.x0;
    const yReversed = this.view.y1 < this.view.y0;
    const x0 = xReversed ? xhi : xlo;
    const x1 = xReversed ? xlo : xhi;
    const y0 = yReversed ? yhi : ylo;
    const y1 = yReversed ? ylo : yhi;
    this._setView({ x0, x1, y0, y1 }, { animate });
  },

  _icon(name) {
    // Inline stroke SVGs (currentColor) — no external assets (§33 no supply chain).
    const svg = (body) =>
      `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" ` +
      `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" ` +
      `stroke-linejoin="round">${body}</svg>`;
    switch (name) {
      case "zoomin":
        return svg('<circle cx="8.5" cy="8.5" r="5.5"/><path d="M12.5 12.5 L17 17"/>' +
          '<path d="M8.5 6 V11 M6 8.5 H11"/>');
      case "zoomout":
        return svg('<circle cx="8.5" cy="8.5" r="5.5"/><path d="M12.5 12.5 L17 17"/>' +
          '<path d="M6 8.5 H11"/>');
      case "pan":
        return svg('<path d="M10 3 V17 M3 10 H17"/><path d="M10 3 L8 5 M10 3 L12 5"/>' +
          '<path d="M10 17 L8 15 M10 17 L12 15"/><path d="M3 10 L5 8 M3 10 L5 12"/>' +
          '<path d="M17 10 L15 8 M17 10 L15 12"/>');
      case "zoom":
        return svg('<rect x="3.5" y="3.5" width="13" height="13" rx="1" ' +
          'stroke-dasharray="3 2"/>');
      case "reset":
        return svg('<path d="M4 10 a6 6 0 1 1 1.8 4.3"/><path d="M4 6 V10 H8"/>');
      case "drag":
        return svg('<circle cx="7" cy="5" r=".8" fill="currentColor" stroke="none"/>' +
          '<circle cx="13" cy="5" r=".8" fill="currentColor" stroke="none"/>' +
          '<circle cx="7" cy="10" r=".8" fill="currentColor" stroke="none"/>' +
          '<circle cx="13" cy="10" r=".8" fill="currentColor" stroke="none"/>' +
          '<circle cx="7" cy="15" r=".8" fill="currentColor" stroke="none"/>' +
          '<circle cx="13" cy="15" r=".8" fill="currentColor" stroke="none"/>');
      default:
        return svg("");
    }
  },
});
