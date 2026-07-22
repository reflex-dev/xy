import { ChartView } from "./50_chartview";

// Unified view state (spec/design/view-state.md): the canonical durable-state
// document, the single apply-a-state-patch implementation every writer calls,
// the client-local history stack, axis-band gesture scoping, and the
// structured hover payload. Prototype augmentation like 51-54.

// History capacity (view-state.md §4): snapshots are a handful of floats;
// the bound is for predictability, not memory.
const XY_HISTORY_CAPACITY = 64;

Object.assign(ChartView.prototype, {
  // -- durable state (§2) ----------------------------------------------------

  _initViewState() {
    this._historyPast = [];
    this._historyFuture = [];
    this._historyLastInteractionId = null;
    // Geometric selection mirror ({range}|{polygon}|{rows:true}|null): the
    // GPU masks are not serializable, so durable state tracks the *shape*
    // that produced them (§2), and rows-selections only as an opaque marker.
    this._stateSelection = null;
    this._customTooltip = null;
    // The whole public JS control surface (§5.3) — one object on the chart
    // root, identical in notebook, Reflex, and standalone HTML mounts.
    this.root.xy = {
      applyState: (patch, opts: any = {}) => this._applyStatePatch(patch, {
        source: "api",
        animate: opts.animate === true,
        history: opts.history !== false,
      }),
      state: () => this._durableState(),
      back: () => this._historyBack(),
      forward: () => this._historyForward(),
    };
  },

  _durableState() {
    const ranges = Object.fromEntries(
      this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId)]])
    );
    const sel = this._stateSelection;
    const selection = sel === null || sel === undefined
      ? null
      : sel.rows
        ? { rows: true }
        : sel.range
          ? { range: { ...sel.range } }
          : { polygon: sel.polygon.map((point) => [...point]) };
    return { v: 1, ranges, selection };
  },

  // Validate one §2 document/patch. Returns an error string or null. v:1 is
  // strict: unknown keys and unknown axis IDs are errors, not ignored —
  // forward compatibility comes from bumping v.
  _validateStatePatch(patch) {
    if (!patch || typeof patch !== "object" || Array.isArray(patch)) {
      return "state patch must be an object";
    }
    if (patch.v !== undefined && patch.v !== 1) {
      return `unsupported state version ${patch.v}`;
    }
    for (const key of Object.keys(patch)) {
      if (!["v", "ranges", "selection"].includes(key)) return `unknown key ${key}`;
    }
    if (patch.ranges !== undefined) {
      if (!patch.ranges || typeof patch.ranges !== "object" || Array.isArray(patch.ranges)) {
        return "ranges must be an object";
      }
      const declared = new Set(this._axisIds());
      for (const [axisId, range] of Object.entries(patch.ranges)) {
        if (!declared.has(axisId)) return `unknown axis ${axisId}`;
        if (!Array.isArray(range) || range.length !== 2
            || !range.every((v) => Number.isFinite(v)) || range[0] === range[1]) {
          return `invalid range for axis ${axisId}`;
        }
      }
    }
    if (patch.selection !== undefined && patch.selection !== null) {
      const sel = patch.selection;
      if (typeof sel !== "object" || Array.isArray(sel)) return "invalid selection";
      const keys = Object.keys(sel);
      if (keys.length !== 1) return "invalid selection";
      if (keys[0] === "range") {
        const r = sel.range;
        if (!r || typeof r !== "object"
            || !["x0", "x1", "y0", "y1"].every((k) => Number.isFinite(r[k]))) {
          return "invalid selection range";
        }
      } else if (keys[0] === "polygon") {
        const p = sel.polygon;
        if (!Array.isArray(p) || p.length < 3
            || !p.every((pt) => Array.isArray(pt) && pt.length === 2
              && pt.every(Number.isFinite))) {
          return "invalid selection polygon";
        }
      } else if (keys[0] === "rows") {
        // The opaque §5.1 marker round-trips through state() but cannot be
        // applied: the index set is not in the document by design.
        return "rows selections are not applicable state";
      } else {
        return "invalid selection";
      }
    }
    return null;
  },

  // The one implementation of "apply a state patch" (§3): merge-patch
  // semantics, every entry point in view-state.md is a caller. Returns
  // true when the patch was accepted (even if it was a no-op).
  _applyStatePatch(patch, opts: any = {}) {
    if (this._destroyed) return false;
    const error = this._validateStatePatch(patch);
    if (error) {
      if (typeof console !== "undefined" && console.warn) {
        console.warn(`xy: state patch rejected: ${error}`);
      }
      return false;
    }
    const source = opts.source || "api";
    // One interaction id for the whole patch, so a ranges+selection patch
    // coalesces into a single history entry.
    const interactionId = ++this._interactionSeq;
    if (patch.ranges !== undefined) {
      const ranges = Object.fromEntries(
        this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId)]])
      );
      for (const [axisId, range] of Object.entries(patch.ranges)) {
        ranges[axisId] = [Number(range[0]), Number(range[1])];
      }
      this._setView({ ranges }, {
        animate: opts.animate === true,
        source,
        phase: "end",
        interactionId,
        history: opts.history,
      });
    }
    if (patch.selection !== undefined) {
      const sel = patch.selection;
      const selOpts = { history: opts.history, interactionId, source };
      if (sel === null) {
        this._clearSelection(selOpts);
      } else if (sel.range) {
        const { x0, x1, y0, y1 } = sel.range;
        this._sendSelect([x0, y0], [x1, y1], selOpts);
      } else if (sel.polygon) {
        this._sendSelectPolygon(sel.polygon.map((point) => [...point]), selOpts);
      }
    }
    return true;
  },

  // -- history (§4) ----------------------------------------------------------

  _historyEnabled() {
    return this._interactionFlag("history", true);
  },

  // Push a snapshot of the durable state as it is RIGHT NOW (i.e. before the
  // mutation that is about to commit). Called from the §3 mutation path;
  // linked and history-sourced writes never push, and all phases of one
  // gesture (same interaction id) coalesce into one entry.
  _historyRecord(opts: any = {}) {
    if (!this._historyPast || !this._historyEnabled() || this._destroyed) return;
    if (opts.history === false) return;
    if (opts.source === "linked" || opts.source === "history") return;
    const id = opts.interactionId;
    if (id !== undefined && id !== null && id === this._historyLastInteractionId) return;
    this._historyLastInteractionId = id === undefined ? null : id;
    this._historyPast.push(this._durableState());
    if (this._historyPast.length > XY_HISTORY_CAPACITY) this._historyPast.shift();
    this._historyFuture.length = 0;
    this._updateHistoryButtons();
  },

  _historyBack() {
    if (!this._historyEnabled() || !this._historyPast.length) return false;
    const snapshot = this._historyPast.pop();
    this._historyFuture.push(this._durableState());
    this._historyApply(snapshot);
    return true;
  },

  _historyForward() {
    if (!this._historyEnabled() || !this._historyFuture.length) return false;
    const snapshot = this._historyFuture.pop();
    this._historyPast.push(this._durableState());
    this._historyApply(snapshot);
    return true;
  },

  _historyApply(snapshot) {
    // A stored snapshot mentions everything, but a rows-selection snapshot
    // carries only the opaque marker — restore the geometry it can express
    // and leave the marker out (rows-selections are non-durable, §5.1).
    const patch: any = { v: 1, ranges: snapshot.ranges };
    if (!snapshot.selection || !snapshot.selection.rows) {
      patch.selection = snapshot.selection ?? null;
    }
    this._applyStatePatch(patch, { source: "history", animate: true, history: false });
    this._historyLastInteractionId = null;
    this._updateHistoryButtons();
  },

  _updateHistoryButtons() {
    const set = (btn, enabled) => {
      if (!btn) return;
      btn.disabled = !enabled;
      btn.setAttribute("aria-disabled", String(!enabled));
      btn.style.opacity = enabled ? "" : "0.4";
    };
    set(this._historyBackBtn, this._historyPast.length > 0);
    set(this._historyForwardBtn, this._historyFuture.length > 0);
  },

  // -- kernel-initiated navigation (§8) -------------------------------------

  _navReset(axes) {
    const override = Array.isArray(axes)
      ? axes.filter((axisId) => this._axisIds().includes(axisId))
      : null;
    this._resetView(true, "reset", override);
  },

  // Kernel-resolved rows-selection (§5.1/§8): the same mask buffers the
  // selection reply ships, applied as a NON-durable selection — never in
  // history, reported in state only as the opaque marker.
  _applyRowsSelection(msg, buffers) {
    this._clearLassoOverlay();
    // A rows document replaces the whole selection. The message carries
    // buffers only for the traces it names, so deactivate every existing
    // mask first — otherwise a prior selection keeps highlighting traces
    // omitted from this document while total reports only the new rows.
    for (const g of this.gpuTraces) {
      g.selActive = false;
      if (g.drill) g.drill.selActive = false;
    }
    // The retained brush geometry (§34) belongs to the replaced selection:
    // keeping it would let a drill swap re-derive the old box/lasso mask
    // over this rows-selection.
    this._lastBrush = null;
    this._applySelectionBuffers(msg, buffers);
    this._stateSelection = { rows: true };
    this._selectionCount = msg.total || 0;
    this.draw();
    if (this._interactionFlag("select", true)) {
      this._dispatchChartEvent("select", {
        total: this._selectionCount,
        view: this._eventView("select"),
      });
    }
  },

  // -- axis-band gestures (§6) ----------------------------------------------

  _axisBandNavigable(axisId) {
    if (!this._interactionFlag("navigation", true)) return false;
    const pan = this._interactionFlag("pan", true)
      && this._axisPolicy("pan_axes").includes(axisId);
    const zoom = this._interactionFlag("zoom", true)
      && this._axisPolicy("zoom_axes").includes(axisId);
    return pan || zoom;
  },

  // The band cursor advertises the axis's actual capability (§6): a resize
  // arrow only when the axis can zoom; a pan-only axis shows a grab hand
  // instead, so the cursor never promises a zoom the policy would ignore.
  _axisBandCursor(axisId, dim) {
    const zoom = this._interactionFlag("zoom", true)
      && this._axisPolicy("zoom_axes").includes(axisId);
    if (zoom) return dim === "x" ? "ew-resize" : "ns-resize";
    return "grab";
  },

  _initAxisBands() {
    if (!this.root) return;
    this._axisBands = {};
    for (const axisId of this._axisIds()) {
      if (!this._axisBandNavigable(axisId)) continue;
      const dim = this._axisDim(axisId);
      const band = document.createElement("div");
      band.dataset.xyAxisBand = axisId;
      band.style.cssText =
        "position:absolute;z-index:2;touch-action:none;" +
        `cursor:${this._axisBandCursor(axisId, dim)};`;
      this.root.appendChild(band);
      this._axisBands[axisId] = band;
      this._bindAxisBand(band, axisId, dim);
    }
    this._layoutAxisBands();
  },

  // Band geometry: the tick-label strip plus a small gutter on the plot side
  // (§6). Secondary axes get their band on their own side, so y vs y2
  // scoping is purely geometric.
  _layoutAxisBands() {
    if (!this._axisBands) return;
    const OUT = 24; // strip breadth outside the plot box
    const IN = 6; //  gutter inside the plot box
    for (const [axisId, band] of Object.entries<any>(this._axisBands)) {
      const dim = this._axisDim(axisId);
      const side = this._axis(axisId).side;
      if (dim === "x") {
        band.style.left = `${this.plot.x}px`;
        band.style.width = `${this.plot.w}px`;
        if (side === "top") {
          band.style.top = `${Math.max(0, this.plot.y - OUT)}px`;
          band.style.height = `${OUT + IN}px`;
        } else {
          band.style.top = `${this.plot.y + this.plot.h - IN}px`;
          band.style.height = `${IN + OUT}px`;
        }
      } else {
        band.style.top = `${this.plot.y}px`;
        band.style.height = `${this.plot.h}px`;
        if (side === "right") {
          band.style.left = `${this.plot.x + this.plot.w - IN}px`;
          band.style.width = `${IN + OUT}px`;
        } else {
          band.style.left = `${Math.max(0, this.plot.x - OUT)}px`;
          band.style.width = `${OUT + IN}px`;
        }
      }
    }
  },

  // Data value at a client coordinate along one axis, clamped to the plot box.
  _axisBandValue(axisId, clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const dim = this._axisDim(axisId);
    if (dim === "x") {
      const cssX = Math.max(0, Math.min(rect.width, clientX - rect.left));
      return this._dataFromCanvas(cssX, 0, axisId, "y")[0];
    }
    const cssY = Math.max(0, Math.min(rect.height, clientY - rect.top));
    return this._dataFromCanvas(0, cssY, "x", axisId)[1];
  },

  _bindAxisBand(band, axisId, dim) {
    let drag = null;

    this._listen(band, "wheel", (e) => {
      if (!this._interactionFlag("navigation", true)) return;
      if (!this._interactionFlag("zoom", true)) return;
      if (!this._interactionFlag("wheel_zoom", true)) return;
      if (!this._axisPolicy("zoom_axes").includes(axisId)) return;
      e.preventDefault();
      const factor = Math.pow(1.0015, e.deltaY);
      const rect = this.canvas.getBoundingClientRect();
      const fx = (e.clientX - rect.left) / rect.width;
      const fy = 1 - (e.clientY - rect.top) / rect.height;
      this._queueWheelZoom(factor, fx, fy, [axisId]);
    }, { passive: false });

    this._listen(band, "pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if (!this._interactionFlag("navigation", true)) return;
      this._cancelViewAnimation();
      drag = {
        pointerId: e.pointerId,
        sx: e.clientX,
        sy: e.clientY,
        view: this._copyView(this.view),
        d0: this._axisBandValue(axisId, e.clientX, e.clientY),
        mode: null,
        interactionId: ++this._interactionSeq,
        changedAxes: [],
      };
      try { band.setPointerCapture(e.pointerId); } catch (_err) { /* synthetic event */ }
      this.tooltip.style.display = "none";
      e.preventDefault();
    });

    const canBandPan = () =>
      this._interactionFlag("pan", true) && this._axisPolicy("pan_axes").includes(axisId)
        ? true
        : this._axisContained(axisId);
    const canBandSpanZoom = () =>
      this._interactionFlag("zoom", true)
      && this._interactionFlag("box_zoom", true)
      && this._axisPolicy("zoom_axes").includes(axisId);

    this._listen(band, "pointermove", (e) => {
      if (!drag || e.pointerId !== drag.pointerId) return;
      const dx = e.clientX - drag.sx;
      const dy = e.clientY - drag.sy;
      if (!drag.mode) {
        if (Math.hypot(dx, dy) <= 3) return;
        const parallel = dim === "x" ? dx : dy;
        const perpendicular = dim === "x" ? dy : dx;
        // Drag along the band pans the axis; drag across it marks a span to
        // box-zoom, mirroring the one-axis select-x/select-y brush shapes.
        const wantPan = Math.abs(parallel) >= Math.abs(perpendicular);
        drag.mode = wantPan
          ? (canBandPan() ? "pan" : canBandSpanZoom() ? "span" : "none")
          : (canBandSpanZoom() ? "span" : canBandPan() ? "pan" : "none");
        if (drag.mode === "pan") band.style.cursor = "grabbing";
      }
      if (drag.mode === "pan") {
        const ranges = Object.fromEntries(
          this._axisIds().map((id) => [id, [...this._axisRange(id, drag.view)]])
        );
        const axis = this._axis(axisId);
        const [lo, hi] = this._axisRange(axisId, drag.view);
        const c0 = this._axisCoord(axis, lo), c1 = this._axisCoord(axis, hi);
        if (![c0, c1].every(Number.isFinite) || c0 === c1) return;
        const pixels = dim === "x" ? this.plot.w : this.plot.h;
        const deltaPx = dim === "x" ? dx : dy;
        const delta = (deltaPx / pixels) * (c1 - c0);
        const signed = dim === "x" ? -delta : delta;
        ranges[axisId] = [
          this._axisValue(axis, c0 + signed),
          this._axisValue(axis, c1 + signed),
        ];
        const changed = this._setView({ ranges }, {
          source: "pan_drag",
          phase: "update",
          interactionId: drag.interactionId,
        });
        drag.changedAxes = [...new Set([...drag.changedAxes, ...changed])];
      } else if (drag.mode === "span") {
        const rootRect = this.root.getBoundingClientRect();
        this.selRect.dataset.xyBand = "zoom";
        this.selRect.style.display = "block";
        if (dim === "x") {
          const a = Math.max(this.plot.x, Math.min(
            this.plot.x + this.plot.w,
            Math.min(drag.sx, e.clientX) - rootRect.left));
          const b = Math.max(this.plot.x, Math.min(
            this.plot.x + this.plot.w,
            Math.max(drag.sx, e.clientX) - rootRect.left));
          this.selRect.style.left = `${a}px`;
          this.selRect.style.width = `${Math.max(0, b - a)}px`;
          this.selRect.style.top = `${this.plot.y}px`;
          this.selRect.style.height = `${this.plot.h}px`;
        } else {
          const a = Math.max(this.plot.y, Math.min(
            this.plot.y + this.plot.h,
            Math.min(drag.sy, e.clientY) - rootRect.top));
          const b = Math.max(this.plot.y, Math.min(
            this.plot.y + this.plot.h,
            Math.max(drag.sy, e.clientY) - rootRect.top));
          this.selRect.style.top = `${a}px`;
          this.selRect.style.height = `${Math.max(0, b - a)}px`;
          this.selRect.style.left = `${this.plot.x}px`;
          this.selRect.style.width = `${this.plot.w}px`;
        }
      }
      e.preventDefault();
    });

    const end = (e) => {
      if (!drag || e.pointerId !== drag.pointerId) return;
      const finished = drag;
      drag = null;
      band.style.cursor = this._axisBandCursor(axisId, dim);
      if (finished.mode === "span") this.selRect.style.display = "none";
      if (e.type === "pointercancel") {
        if (this._viewMutationActive) {
          this._viewMutationActive = false;
          this._lastLabelDraw = null;
          this.draw();
        }
        return;
      }
      if (finished.mode === "pan" && finished.changedAxes.length) {
        this._emitViewChange("pan_drag", {
          axes: finished.changedAxes,
          phase: "end",
          interactionId: finished.interactionId,
        });
      } else if (finished.mode === "span") {
        const d1 = this._axisBandValue(axisId, e.clientX, e.clientY);
        const axis = this._axis(axisId);
        const a = this._axisCoord(axis, finished.d0);
        const b = this._axisCoord(axis, d1);
        // §16 precision floor, as in _zoomToBox: ignore degenerate spans.
        const minSpan = Math.max(Math.abs(a), Math.abs(b), 1e-30) * 1e-12;
        if (![a, b].every(Number.isFinite) || Math.abs(b - a) < minSpan) return;
        const [lo, hi] = this._axisRange(axisId);
        const reverse = this._axisCoord(axis, hi) < this._axisCoord(axis, lo);
        const low = Math.min(a, b), high = Math.max(a, b);
        const ranges = Object.fromEntries(
          this._axisIds().map((id) => [id, [...this._axisRange(id)]])
        );
        ranges[axisId] = [
          this._axisValue(axis, reverse ? high : low),
          this._axisValue(axis, reverse ? low : high),
        ];
        this._setView({ ranges }, {
          animate: true,
          anchors: { [axisId]: 0.5 },
          source: "box_zoom",
          phase: "end",
          interactionId: finished.interactionId,
        });
      }
    };
    this._listen(band, "pointerup", end);
    this._listen(band, "pointercancel", end);
  },

  // -- structured hover payload (§7) ----------------------------------------

  _seriesColorCss(g) {
    const c = g && g.color;
    if (!Array.isArray(c) || c.length < 3) return null;
    const channel = (v) => Math.max(0, Math.min(255, Math.round(Number(v) * 255)));
    return `rgb(${channel(c[0])}, ${channel(c[1])}, ${channel(c[2])})`;
  },

  // The §7.1 payload. cursor.px is chart-root-relative; cursor.data is keyed
  // by exact axis ID (one entry per declared axis — a chart-root pixel maps
  // to a different value on every axis, so a bare {x, y} would be ambiguous
  // with a y2 declared).
  _hoverPayload(row, hit, clientX, clientY, exact = false) {
    const rootRect = this.root.getBoundingClientRect();
    const canvasRect = this.canvas.getBoundingClientRect();
    const cssX = Math.max(0, Math.min(canvasRect.width, clientX - canvasRect.left));
    const cssY = Math.max(0, Math.min(canvasRect.height, clientY - canvasRect.top));
    const data = {};
    for (const axisId of this._axisIds()) {
      const dim = this._axisDim(axisId);
      const [x, y] = this._dataFromCanvas(
        cssX, cssY,
        dim === "x" ? axisId : "x",
        dim === "y" ? axisId : "y",
      );
      data[axisId] = dim === "x" ? x : y;
    }
    const g = hit && hit.g;
    const points = row ? [{
      trace: (g && g.trace && g.trace.name) || row.trace,
      index: row.index,
      row,
      x_axis: (g && g.xAxis) || "x",
      y_axis: (g && g.yAxis) || "y",
      color: this._seriesColorCss(g),
    }] : [];
    const payload: any = {
      active: true,
      cursor: {
        px: [clientX - rootRect.left, clientY - rootRect.top],
        data,
      },
      points,
    };
    if (exact) payload.exact = true;
    return payload;
  },

  // -- framework-owned tooltip mount (§7.2) ----------------------------------

  // Mount a caller-owned element as the tooltip content. The element rides
  // inside the built-in tooltip container, so it inherits the placement
  // logic (flip-at-edges included) and every show/hide site; the built-in
  // line rendering and box chrome are suppressed while it is mounted.
  setCustomTooltip(el) {
    if (!this.tooltip) return;
    if (!el) {
      this._customTooltip = null;
      delete this.tooltip.dataset.xyCustomTooltip;
      this.tooltip.style.background = "";
      this.tooltip.style.border = "";
      this.tooltip.style.padding = "";
      this.tooltip.replaceChildren();
      this.tooltip.style.display = "none";
      return;
    }
    this._customTooltip = el;
    this.tooltip.dataset.xyCustomTooltip = "";
    // Inline wins over the :where() slot defaults: the custom component owns
    // its own chrome, the container becomes a pure positioning shell.
    this.tooltip.style.background = "transparent";
    this.tooltip.style.border = "none";
    this.tooltip.style.padding = "0";
    el.style.display = "";
    this.tooltip.replaceChildren(el);
  },
});
