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
    this.selLasso = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.selLasso.style.cssText =
      "position:absolute;display:none;pointer-events:none;z-index:4;overflow:visible;";
    this.selLasso.dataset.xySelectionLassoOverlay = "";
    this.selLassoPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    this.selLassoPath.dataset.xySelectionLasso = "";
    this.selLasso.appendChild(this.selLassoPath);
    this.selLassoHandles = document.createElementNS("http://www.w3.org/2000/svg", "g");
    this.selLassoHandles.dataset.xySelectionLassoHandles = "";
    this.selLasso.appendChild(this.selLassoHandles);
    this.root.appendChild(this.selLasso);
    this._lassoPolygon = null;
    let lassoHandleDrag = null;

    const moveLassoHandle = (e) => {
      if (!lassoHandleDrag || e.pointerId !== lassoHandleDrag.pointerId
          || !this._lassoPolygon) return;
      const rect = c.getBoundingClientRect();
      const cssX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const cssY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
      this._lassoPolygon[lassoHandleDrag.index] = this._dataFromCanvas(cssX, cssY);
      this._renderLassoSelection();
      e.preventDefault();
      e.stopPropagation();
    };
    this._listen(this.selLasso, "pointerdown", (e) => {
      const handle = e.target.closest?.("[data-xy-selection-lasso-handle]");
      if (!handle || !this._lassoPolygon) return;
      const index = Number(handle.dataset.xySelectionLassoHandle);
      if (!Number.isInteger(index) || !this._lassoPolygon[index]) return;
      lassoHandleDrag = {
        index,
        pointerId: e.pointerId,
        original: [...this._lassoPolygon[index]],
        handle,
      };
      handle.dataset.xyActive = "";
      this.tooltip.style.display = "none";
      try { this.selLasso.setPointerCapture(e.pointerId); } catch (_err) { /* synthetic event */ }
      e.preventDefault();
      e.stopPropagation();
    });
    this._listen(this.selLasso, "pointermove", moveLassoHandle);
    this._listen(this.selLasso, "pointerup", (e) => {
      if (!lassoHandleDrag || e.pointerId !== lassoHandleDrag.pointerId) return;
      moveLassoHandle(e);
      const handle = lassoHandleDrag.handle;
      lassoHandleDrag = null;
      delete handle.dataset.xyActive;
      if (this._lassoPolygon) this._sendSelectPolygon(this._lassoPolygon);
    });
    this._listen(this.selLasso, "pointercancel", (e) => {
      if (!lassoHandleDrag || e.pointerId !== lassoHandleDrag.pointerId) return;
      if (this._lassoPolygon) {
        this._lassoPolygon[lassoHandleDrag.index] = lassoHandleDrag.original;
      }
      delete lassoHandleDrag.handle.dataset.xyActive;
      lassoHandleDrag = null;
      if (this._lassoPolygon) this._renderLassoSelection();
      e.stopPropagation();
    });

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
    const lassoPointAt = (clientX, clientY) => {
      const r = c.getBoundingClientRect();
      const cssX = Math.max(0, Math.min(r.width, clientX - r.left));
      const cssY = Math.max(0, Math.min(r.height, clientY - r.top));
      return {
        x: r.left + cssX,
        y: r.top + cssY,
        data: this._dataFromCanvas(cssX, cssY),
      };
    };

    this._listen(c, "pointerdown", (e) => {
      this._cancelViewAnimation();
      const canPan = this._interactionFlag("pan", true);
      const canZoom = this._interactionFlag("zoom", true);
      const canNavigate = this._interactionFlag("navigation", true);
      const canBoxZoom = this._interactionFlag("box_zoom", true);
      // Shift-drag box-selects (§34); the modebar can make selection or box-zoom
      // the default plain-drag gesture; otherwise a plain drag pans.
      const canBrush = this._interactionFlag("brush", true) && this._interactionFlag("select", true);
      const selectMode = this.dragMode.startsWith("select") ? this.dragMode : null;
      const mode = (e.shiftKey || selectMode) && canBrush && this._pickable
        ? (e.shiftKey ? "select" : selectMode)
        : this.dragMode === "zoom" && canNavigate && canZoom && canBoxZoom ? "zoom" : null;
      if (mode) {
        const previousLasso = mode.startsWith("select") && this._lassoPolygon
          ? this._lassoPolygon.map((point) => [...point])
          : null;
        if (mode.startsWith("select")) this._clearLassoOverlay();
        const firstLassoPoint = mode === "select-lasso" ? lassoPointAt(e.clientX, e.clientY) : null;
        const d0 = firstLassoPoint ? firstLassoPoint.data : dataAt(e.clientX, e.clientY);
        band = {
          mode, sx: e.clientX, sy: e.clientY, d0,
          points: firstLassoPoint ? [firstLassoPoint] : null,
          previousLasso,
        };
        try { c.setPointerCapture(e.pointerId); } catch (_err) { /* synthetic event */ }
        this.tooltip.style.display = "none";
        return;
      }
      if (this.dragMode === "pan" && canNavigate && canPan) {
        drag = {
          px: e.clientX,
          py: e.clientY,
          view: this._copyView(this.view),
          moved: false,
          interactionId: ++this._interactionSeq,
          // Free pan axes plus contained zoom axes: containment bounds a
          // locked axis's motion in the clamp (it slides inside its home
          // window once zoomed in) instead of removing it from the gesture.
          axes: [...new Set([
            ...this._axisPolicy("pan_axes"),
            ...this._axisIds().filter((axisId) => this._axisContained(axisId)),
          ])],
          changedAxes: [],
        };
        try { c.setPointerCapture(e.pointerId); } catch (_err) { /* synthetic event */ }
        this.tooltip.style.display = "none";
      }
    });
    this._listen(c, "pointermove", (e) => {
      if (band) { this._updateBand(band, e); return; }
      if (drag) {
        drag.moved = true;
        const ranges = Object.fromEntries(
          this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId, drag.view)]])
        );
        for (const axisId of drag.axes) {
          const axis = this._axis(axisId);
          const [lo, hi] = this._axisRange(axisId, drag.view);
          const c0 = this._axisCoord(axis, lo), c1 = this._axisCoord(axis, hi);
          if (![c0, c1].every(Number.isFinite) || c0 === c1) continue;
          const dim = this._axisDim(axisId);
          const pixels = dim === "x" ? this.plot.w : this.plot.h;
          const deltaPx = dim === "x" ? e.clientX - drag.px : e.clientY - drag.py;
          const delta = (deltaPx / pixels) * (c1 - c0);
          const signed = dim === "x" ? -delta : delta;
          ranges[axisId] = [
            this._axisValue(axis, c0 + signed),
            this._axisValue(axis, c1 + signed),
          ];
        }
        const changedAxes = this._setView({ ranges }, {
          source: "pan_drag",
          phase: "update",
          interactionId: drag.interactionId,
        });
        drag.changedAxes = [...new Set([...drag.changedAxes, ...changedAxes])];
        return;
      }
      this._updateCrosshair(e);
      this._hover(e);
    });
    const end = (e) => {
      if (band) {
        // Pointermove is not guaranteed to run at the pointer-up coordinate.
        // Capture that final vertex before deciding whether the gesture moved;
        // a naturally closed lasso finishes near its start and therefore has
        // almost no *net* displacement despite enclosing a real area.
        if (band.mode === "select-lasso") this._updateBand(band, e);
        this.selRect.style.display = "none";
        this.selLasso.style.display = "none";
        const d1 = dataAt(e.clientX, e.clientY);
        const moved = band.mode === "select-lasso"
          ? band.points.length >= 3
          : Math.abs(e.clientX - band.sx) > 3 || Math.abs(e.clientY - band.sy) > 3;
        if (moved) {
          if (band.mode === "zoom" && this._interactionFlag("zoom", true)) {
            this._zoomToBox(band.d0, d1, true, {
              source: "box_zoom",
              phase: "end",
              interactionId: ++this._interactionSeq,
            });
          } else if (band.mode === "select-lasso") {
            if (band.points.length >= 3) {
              const editable = this._simplifyLassoPoints(band.points);
              this._sendSelectPolygon(editable.map((point) => point.data));
            } else if (band.previousLasso) {
              this._lassoPolygon = band.previousLasso;
              this._renderLassoSelection();
            }
          } else {
            let d0 = band.d0;
            if (band.mode === "select-x") {
              d0 = [band.d0[0], this.view.y0];
              d1[1] = this.view.y1;
            } else if (band.mode === "select-y") {
              d0 = [this.view.x0, band.d0[1]];
              d1[0] = this.view.x1;
            }
            this._sendSelect(d0, d1);
          }
          this._ignoreNextClick = true;
        } else if (band.previousLasso) {
          this._lassoPolygon = band.previousLasso;
          this._renderLassoSelection();
        }
        band = null;
        return;
      }
      if (drag && drag.moved) {
        this._ignoreNextClick = true;
        if (drag.changedAxes.length) this._emitViewChange("pan_drag", {
          axes: drag.changedAxes,
          phase: "end",
          interactionId: drag.interactionId,
        });
      }
      if (drag && !drag.moved) this.tooltip.style.display = "none";
      drag = null;
    };
    this._listen(c, "pointerup", end);
    this._listen(c, "pointercancel", () => {
      this.selRect.style.display = "none";
      this.selLasso.style.display = "none";
      if (band?.previousLasso) {
        this._lassoPolygon = band.previousLasso;
        this._renderLassoSelection();
      }
      band = null;
      drag = null;
    });
    this._listen(c, "pointerleave", () => {
      const hadHover = this._hoverId !== -1;
      this._hoverId = -1;
      this._hoverTarget = null;
      this._lastHoverXY = null;
      this._a11yKeyboardReadout = null;
      this._pickSeq = (this._pickSeq || 0) + 1;
      this.tooltip.style.display = "none";
      this._hideCrosshair();
      if (this._interactionFlag("hover")) {
        this._dispatchChartEvent("leave", { view: this._eventView("leave"), active: false });
      }
      // Highlight-clear only — the pick snapshot stays valid (§17).
      if (hadHover) this._drawKeepPick();
    });
    this._listen(c, "click", (e) => this._click(e));

    this._listen(c, "wheel", (e) => {
      if (!this._interactionFlag("navigation", true)) return;
      if (!this._interactionFlag("zoom", true)) return;
      if (!this._interactionFlag("wheel_zoom", true)) return;
      e.preventDefault();
      const f = Math.pow(1.0015, e.deltaY);
      const r = c.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width;
      const fy = 1 - (e.clientY - r.top) / r.height;
      this._queueWheelZoom(f, fx, fy);
    }, { passive: false });

    this._listen(c, "dblclick", () => {
      if (!this._interactionFlag("navigation", true)) return;
      if (!this._interactionFlag("double_click_reset", true)) return;
      this._resetView(true, "reset");
    });
    this._listen(c, "keydown", (e) => {
      if (e.key === "Escape" && (band || drag)) {
        this.selRect.style.display = "none";
        this.selLasso.style.display = "none";
        band = null;
        drag = null;
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    });
    this._listen(c, "keydown", (e) => this._onA11yKey(e));
  },

  _a11yPointGroups() {
    return (this.gpuTraces || []).filter((g) =>
      markOf(g.trace.kind).pointPick && g.tier !== "density" && g._cpu &&
      g._cpu.x && g._cpu.y && Math.min(g._cpu.x.length, g._cpu.y.length) > 0);
  },

  _onA11yKey(e) {
    const direction = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (direction === undefined && e.key !== "Home" && e.key !== "End" && e.key !== "Escape") {
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      const hadHover = this._hoverId !== -1;
      this.tooltip.style.display = "none";
      this._hoverId = -1;
      this._hoverTarget = null;
      this._lastHoverXY = null;
      this._a11yKeyboardReadout = null;
      // Invalidate an exact-value reply already in flight so dismissal cannot
      // reopen the tooltip. Keep _a11yPointIndex: refocusing resumes at the
      // dismissed point, and every later traversal clamps it to current data.
      this._pickSeq = (this._pickSeq || 0) + 1;
      if (this.a11yLive) this.a11yLive.textContent = "Readout closed.";
      if (hadHover && this._interactionFlag("hover")) {
        this._dispatchChartEvent("leave", { view: this._eventView("leave"), active: false });
      }
      if (hadHover) this._drawKeepPick();
      return;
    }
    e.preventDefault();
    // Match pointer hover: never expose a readout against an in-between view,
    // density handoff, or animated tier frame.
    if (this._interactionTransitionActive()) return;
    const groups = this._a11yPointGroups();
    const total = groups.reduce((sum, g) => sum + Math.min(g._cpu.x.length, g._cpu.y.length), 0);
    if (!total) return;
    // Traversal intentionally follows trace/series data order, not visual x
    // order: sorting would change source-row identity and make streamed appends
    // reorder the user's position under focus.
    let flat = Number.isInteger(this._a11yPointIndex) ? this._a11yPointIndex : -1;
    if (e.key === "Home") flat = 0;
    else if (e.key === "End") flat = total - 1;
    else if (flat < 0) flat = direction > 0 ? 0 : total - 1;
    else flat = Math.max(0, Math.min(total - 1, flat + direction));
    this._a11yPointIndex = flat;
    let offset = flat;
    let g = groups[0];
    for (const candidate of groups) {
      const n = Math.min(candidate._cpu.x.length, candidate._cpu.y.length);
      if (offset < n) { g = candidate; break; }
      offset -= n;
    }
    const hit = { trace: g.trace.id, index: offset, g };
    // Use the encoded numeric coordinates for positioning; _localRow may have
    // already converted categorical coordinates into display strings.
    const xValue = this._decodeValue(g._cpu.x, g._cpu.xMeta || g.xMeta, offset);
    const yValue = this._decodeValue(g._cpu.y, g._cpu.yMeta || g.yMeta, offset);
    const x = this._dataPx(g.xAxis || "x", xValue) - this.plot.x;
    const y = this._dataPx(g.yAxis || "y", yValue) - this.plot.y;
    const rect = this.canvas.getBoundingClientRect();
    const clientX = rect.left + Math.max(0, Math.min(rect.width, x));
    const clientY = rect.top + Math.max(0, Math.min(rect.height, y));
    this._hoverId = hit.trace * 1e9 + hit.index;
    this._hoverTarget = hit;
    this._lastHoverXY = { clientX, clientY };
    this._a11yKeyboardReadout = { flat, total };
    this._showTooltip(hit, clientX, clientY);
    this._drawKeepPick();
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
    if (band.mode === "select-lasso") {
      const previous = band.points[band.points.length - 1];
      const cssX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const cssY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
      const clientX = rect.left + cssX;
      const clientY = rect.top + cssY;
      if (band.points.length < 2048
          && Math.hypot(clientX - previous.x, clientY - previous.y) >= 3) {
        band.points.push({ x: clientX, y: clientY, data: this._dataFromCanvas(cssX, cssY) });
      }
      const points = band.points.map((point) => [
        Math.max(this.plot.x, Math.min(this.plot.x + this.plot.w, point.x - rootRect.left)),
        Math.max(this.plot.y, Math.min(this.plot.y + this.plot.h, point.y - rootRect.top)),
      ]);
      this.selLasso.style.display = "block";
      this.selLasso.style.inset = "0";
      this.selLasso.setAttribute("width", String(this.root.clientWidth));
      this.selLasso.setAttribute("height", String(this.root.clientHeight));
      this.selLassoPath.setAttribute(
        "d", points.map((point, i) => `${i ? "L" : "M"}${point[0]} ${point[1]}`).join(" ") + " Z"
      );
      return;
    }
    const x = Math.min(band.sx, e.clientX) - rootRect.left;
    const y = Math.min(band.sy, e.clientY) - rootRect.top;
    const w = Math.abs(e.clientX - band.sx);
    const h = Math.abs(e.clientY - band.sy);
    // clamp to plot area
    const px = this.plot.x, py = this.plot.y;
    const x2 = Math.min(x + w, px + this.plot.w), y2 = Math.min(y + h, py + this.plot.h);
    let cx = Math.max(x, px), cy = Math.max(y, py);
    let bx2 = x2, by2 = y2;
    if (band.mode === "select-x") { cy = py; by2 = py + this.plot.h; }
    if (band.mode === "select-y") { cx = px; bx2 = px + this.plot.w; }
    // Band paint (border/background) is a defeatable :where() default keyed on
    // data-xy-band, NOT pinned inline — otherwise a `class_names={"selection":…}`
    // utility (or `styles[selection]`) would lose to the inline style, breaking
    // the "your styles always win" contract for this one slot. Only the mode
    // discriminator and structural position/size stay inline (matches §36).
    this.selRect.dataset.xyBand = band.mode === "zoom" ? "zoom" : "select";
    this.selRect.style.display = "block";
    this.selRect.style.left = cx + "px";
    this.selRect.style.top = cy + "px";
    this.selRect.style.width = Math.max(0, bx2 - cx) + "px";
    this.selRect.style.height = Math.max(0, by2 - cy) + "px";
    void rect;
  },

  _simplifyLassoPoints(points, tolerance = 6, maxPoints = 16) {
    const source = points.filter((point) => point && Number.isFinite(point.x) && Number.isFinite(point.y));
    if (source.length > 3) {
      const first = source[0], last = source[source.length - 1];
      if (Math.hypot(first.x - last.x, first.y - last.y) <= tolerance) source.pop();
    }
    if (source.length <= 3) return source.slice();

    const distanceToSegmentSq = (point, start, end) => {
      const dx = end.x - start.x, dy = end.y - start.y;
      if (dx === 0 && dy === 0) {
        return (point.x - start.x) ** 2 + (point.y - start.y) ** 2;
      }
      const t = Math.max(0, Math.min(1,
        ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy)
      ));
      const x = start.x + t * dx, y = start.y + t * dy;
      return (point.x - x) ** 2 + (point.y - y) ** 2;
    };
    const simplifyAt = (currentTolerance) => {
      const keep = new Uint8Array(source.length);
      keep[0] = 1;
      keep[source.length - 1] = 1;
      const stack = [[0, source.length - 1]];
      const toleranceSq = currentTolerance * currentTolerance;
      while (stack.length) {
        const [start, end] = stack.pop();
        let furthest = -1, furthestDistance = toleranceSq;
        for (let i = start + 1; i < end; i++) {
          const distance = distanceToSegmentSq(source[i], source[start], source[end]);
          if (distance > furthestDistance) {
            furthest = i;
            furthestDistance = distance;
          }
        }
        if (furthest >= 0) {
          keep[furthest] = 1;
          stack.push([start, furthest], [furthest, end]);
        }
      }
      return source.filter((_point, index) => keep[index]);
    };
    let simplified = simplifyAt(tolerance);
    if (simplified.length < 3) {
      simplified = [source[0], source[Math.floor(source.length / 2)], source[source.length - 1]];
    }
    if (simplified.length > maxPoints) {
      // Raise the RDP tolerance until the handle budget is met. Unlike uniform
      // re-sampling, this continues to preserve the polygon's most significant
      // corners as the editable overlay becomes simpler.
      let low = tolerance;
      let high = Math.max(tolerance, 1);
      for (let i = 0; i < 16 && simplified.length > maxPoints; i++) {
        low = high;
        high *= 2;
        simplified = simplifyAt(high);
      }
      for (let i = 0; i < 12; i++) {
        const middle = (low + high) / 2;
        const candidate = simplifyAt(middle);
        if (candidate.length > maxPoints) low = middle;
        else {
          high = middle;
          simplified = candidate;
        }
      }
      if (simplified.length < 3) {
        simplified = [source[0], source[Math.floor(source.length / 2)], source[source.length - 1]];
      }
    }
    return simplified;
  },

  _clearLassoOverlay() {
    this._lassoPolygon = null;
    if (!this.selLasso) return;
    this.selLasso.style.display = "none";
    this.selLassoPath?.removeAttribute("d");
    this.selLassoHandles?.replaceChildren();
  },

  _renderLassoSelection() {
    const polygon = this._lassoPolygon;
    if (!this.selLasso || !this.selLassoPath || !this.selLassoHandles
        || !Array.isArray(polygon) || polygon.length < 3) return;
    const [x0, x1] = this._axisRange("x");
    const [y0, y1] = this._axisRange("y");
    const xAxis = this._axis("x"), yAxis = this._axis("y");
    const cx0 = this._axisCoord(xAxis, x0), cx1 = this._axisCoord(xAxis, x1);
    const cy0 = this._axisCoord(yAxis, y0), cy1 = this._axisCoord(yAxis, y1);
    if (![cx0, cx1, cy0, cy1].every(Number.isFinite) || cx0 === cx1 || cy0 === cy1) return;
    const points = polygon.map((point) => {
      const cx = this._axisCoord(xAxis, point[0]);
      const cy = this._axisCoord(yAxis, point[1]);
      const x = this.plot.x + ((cx - cx0) / (cx1 - cx0)) * this.plot.w;
      const y = this.plot.y + ((cy1 - cy) / (cy1 - cy0)) * this.plot.h;
      return [
        Math.max(this.plot.x, Math.min(this.plot.x + this.plot.w, x)),
        Math.max(this.plot.y, Math.min(this.plot.y + this.plot.h, y)),
      ];
    });
    if (!points.flat().every(Number.isFinite)) return;

    this.selLasso.style.display = "block";
    this.selLasso.style.inset = "0";
    this.selLasso.setAttribute("width", String(this.root.clientWidth));
    this.selLasso.setAttribute("height", String(this.root.clientHeight));
    this.selLassoPath.setAttribute(
      "d", points.map((point, index) => `${index ? "L" : "M"}${point[0]} ${point[1]}`).join(" ") + " Z"
    );
    while (this.selLassoHandles.childElementCount < points.length) {
      const handle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      handle.dataset.xySelectionLassoHandle = "";
      handle.setAttribute("r", "4");
      this.selLassoHandles.appendChild(handle);
    }
    while (this.selLassoHandles.childElementCount > points.length) {
      this.selLassoHandles.lastElementChild.remove();
    }
    [...this.selLassoHandles.children].forEach((handle, index) => {
      handle.dataset.xySelectionLassoHandle = String(index);
      handle.setAttribute("cx", String(points[index][0]));
      handle.setAttribute("cy", String(points[index][1]));
      handle.setAttribute("aria-label", `Lasso point ${index + 1}`);
    });
  },

  _sendSelect(d0, d1, opts = {}) {
    this._clearLassoOverlay();
    const x0 = Math.min(d0[0], d1[0]), x1 = Math.max(d0[0], d1[0]);
    const y0 = Math.min(d0[1], d1[1]), y1 = Math.max(d0[1], d1[1]);
    const range = { x0, x1, y0, y1 };
    // Geometric selections are durable: push like a range change (§4).
    this._historyRecord({
      source: opts.source,
      interactionId: opts.interactionId,
      history: opts.history,
    });
    this._stateSelection = { range: { ...range } };
    this._broadcastLinkedSelection({ range });
    this._dispatchChartEvent("brush", { range, view: this._eventView("brush") });
    if (this.comm) {
      this.comm.send({ type: "select", x0, x1, y0, y1 });
    } else {
      this._selectLocal(x0, x1, y0, y1); // standalone: compute from resident f32
    }
  },

  _sendSelectPolygon(points, opts = {}) {
    if (!Array.isArray(points) || points.length < 3) return;
    const polygon = points.map((point) => [point[0], point[1]]);
    if (!polygon.every((point) => point.every(Number.isFinite))) return;
    this._historyRecord({
      source: opts.source,
      interactionId: opts.interactionId,
      history: opts.history,
    });
    this._stateSelection = { polygon: polygon.map((point) => [...point]) };
    this._lassoPolygon = polygon;
    this._broadcastLinkedSelection({ polygon });
    this._renderLassoSelection();
    this._dispatchChartEvent("brush", {
      polygon,
      view: this._eventView("brush"),
    });
    if (this.comm) {
      this.comm.send({ type: "select_polygon", points: polygon });
    } else {
      this._selectLocalPolygon(polygon);
    }
  },

  _selectLocalPolygon(points, opts = {}) {
    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => point[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const inside = (x, y) => {
      let hit = false;
      for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
        const [xi, yi] = points[i], [xj, yj] = points[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    };
    let total = 0;
    for (const g of this.gpuTraces) {
      if (!g._cpu || g.tier === "density") continue;
      const cx = g._cpu.x, cy = g._cpu.y;
      const xMeta = g._cpu.xMeta || g.xMeta;
      const yMeta = g._cpu.yMeta || g.yMeta;
      const ox = xMeta.offset, sx = xMeta.scale || 1;
      const oy = yMeta.offset, sy = yMeta.scale || 1;
      const mask = new Float32Array(g.n);
      let count = 0;
      for (let i = 0; i < g.n; i++) {
        const x = cx[i] / sx + ox;
        const y = cy[i] / sy + oy;
        if (x >= minX && x <= maxX && y >= minY && y <= maxY && inside(x, y)) {
          mask[i] = 1;
          count++;
        }
      }
      this._applySelMask(g, mask);
      total += count;
    }
    this._selectionCount = total;
    this.draw();
    if (opts.dispatch !== false) {
      this._dispatchChartEvent("select", {
        total,
        polygon: points,
        view: this._eventView("select"),
      });
    }
  },

  // Standalone selection (no kernel): mask the retained CPU f32 columns (§37).
  _selectLocal(x0, x1, y0, y1, opts = {}) {
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
    if (opts.dispatch !== false) {
      this._dispatchChartEvent("select", {
        total,
        range: { x0, x1, y0, y1 },
        view: this._eventView("select"),
      });
    }
  },

  _applySelMask(g, maskF32) {
    const gl = this.gl;
    if (!g.selBuf) g.selBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, g.selBuf);
    gl.bufferData(gl.ARRAY_BUFFER, maskF32, gl.STATIC_DRAW);
    g.selActive = true;
  },

  _clearSelection(opts = {}) {
    this._clearLassoOverlay();
    // Clearing a durable selection is itself a durable-state change; linked
    // applies (dispatch: false) and no-op clears push nothing.
    if (opts.dispatch !== false && this._stateSelection !== null
        && this._stateSelection !== undefined) {
      this._historyRecord({
        source: opts.source,
        interactionId: opts.interactionId,
        history: opts.history,
      });
    }
    this._stateSelection = null;
    for (const g of this.gpuTraces) {
      g.selActive = false;
      if (g.drill) g.drill.selActive = false;
    }
    this._selectionCount = 0;
    if (opts.broadcast !== false) this._broadcastLinkedSelection({ clear: true });
    if (opts.dispatch !== false) {
      if (this._interactionFlag("select", true)) {
        if (this.comm) this.comm.send({ type: "select_clear" });
        this._dispatchChartEvent("select", { total: 0, view: this._eventView("select_clear") });
      }
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
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Chart controls");
    this._modebar = bar;
    this._modeBtns = {};
    this._modebarMoved = false;
    let setZoomMenuOpen = () => {};
    let setSelectMenuOpen = () => {};
    let setExportMenuOpen = () => {};

    const setVisible = (visible) => {
      const show = visible || this._modebarDragging || bar.contains(document.activeElement);
      bar.style.opacity = show ? "1" : "0";
      bar.style.pointerEvents = show ? "auto" : "none";
    };
    this._listen(root, "pointerenter", () => setVisible(true));
    this._listen(root, "pointerleave", () => {
      setVisible(false);
      setZoomMenuOpen(false);
      setSelectMenuOpen(false);
      setExportMenuOpen(false);
    });
    this._listen(bar, "focusin", () => setVisible(true));
    this._listen(bar, "focusout", (e) => {
      if (!bar.contains(e.relatedTarget) && !root.matches(":hover")) setVisible(false);
    });

    // One combined grip/menu control avoids a second, visually redundant dots
    // button. Click opens toolbar options and drag moves the toolbar.
    const grip = document.createElement("button");
    grip.type = "button";
    grip.title = "Click for toolbar options; drag to move";
    grip.setAttribute("aria-label", "Toolbar options");
    grip.setAttribute("aria-haspopup", "menu");
    grip.setAttribute("aria-expanded", "false");
    grip.dataset.xyModebarDragHandle = "";
    grip.dataset.xyModebarExport = "";
    grip.dataset.xyModebarExportTrigger = "";
    grip.innerHTML = this._icon("drag");
    grip.style.cssText =
      "display:flex;align-items:center;justify-content:center;pointer-events:auto;touch-action:none;";
    this._applySlot(grip, "modebar_button");
    bar.appendChild(grip);

    const DRAG_THRESHOLD_PX = 6;
    let modebarDrag = null;
    let suppressGripClickUntil = 0;
    this._listen(grip, "pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      e.stopPropagation();
      const barRect = bar.getBoundingClientRect();
      modebarDrag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        dx: e.clientX - barRect.left,
        dy: e.clientY - barRect.top,
        moved: false,
      };
      try { grip.setPointerCapture(e.pointerId); } catch (_err) { /* synthetic event */ }
      setVisible(true);
    });
    this._listen(grip, "pointermove", (e) => {
      if (!modebarDrag || e.pointerId !== modebarDrag.pointerId) return;
      const distance = Math.hypot(e.clientX - modebarDrag.startX, e.clientY - modebarDrag.startY);
      if (!modebarDrag.moved) {
        if (distance < DRAG_THRESHOLD_PX) return;
        modebarDrag.moved = true;
        this._modebarDragging = true;
        this._modebarMoved = true;
        bar.style.transition = "none";
        setZoomMenuOpen(false);
        setSelectMenuOpen(false);
        setExportMenuOpen(false);
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
        suppressGripClickUntil = performance.now() + 100;
      }
    };
    this._listen(grip, "pointerup", endModebarDrag);
    this._listen(grip, "pointercancel", endModebarDrag);
    this._listen(grip, "click", (e) => {
      e.stopPropagation();
      if (performance.now() <= suppressGripClickUntil) {
        suppressGripClickUntil = 0;
        return;
      }
      setExportMenuOpen(!this._exportMenuOpen);
    });

    const mk = (name, title, onClick, toggles) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = title;
      b.setAttribute("aria-label", title);
      if (toggles) b.setAttribute("aria-pressed", "false");
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

    const canNavigate = this._interactionFlag("navigation", true);
    const canPan = canNavigate && this._interactionFlag("pan", true);
    const canZoom = canNavigate && this._interactionFlag("zoom", true);
    const canZoomButtons = canZoom && this._interactionFlag("zoom_buttons", true);
    const canBoxZoom = canZoom && this._interactionFlag("box_zoom", true);
    const canReset = canNavigate && this._resetAxisPolicy().length > 0;
    const hasZoomMenu = canZoomButtons || canBoxZoom || canReset;
    let zoomTrigger = null;
    let zoomIndicator = null;
    this._zoomMenuButton = null;
    this._zoomMenuLabel = null;
    if (hasZoomMenu) {
      zoomTrigger = mk("zoommenu", "Zoom controls", () => {
        setZoomMenuOpen(!this._zoomMenuOpen);
      });
      this._zoomMenuButton = zoomTrigger;
      zoomTrigger.dataset.xyModebarMenuTrigger = "";
      zoomTrigger.replaceChildren();
      const zoomPercent = document.createElement("span");
      zoomPercent.dataset.xyModebarZoomPercent = "";
      zoomPercent.textContent = "100%";
      zoomTrigger.appendChild(zoomPercent);
      zoomIndicator = document.createElement("span");
      zoomIndicator.dataset.xyModebarMenuIndicator = "";
      zoomIndicator.innerHTML = this._icon("chevrondown");
      zoomTrigger.appendChild(zoomIndicator);
      this._zoomMenuLabel = zoomPercent;
      zoomTrigger.setAttribute("aria-haspopup", "menu");
      zoomTrigger.setAttribute("aria-expanded", "false");
    }
    const canSelect = this._pickable
      && this._interactionFlag("brush", true)
      && this._interactionFlag("select", true);
    let selectTrigger = null;
    let selectIndicator = null;
    let selectModeIcon = null;
    if (canSelect) {
      selectTrigger = mk("select", "Selection controls", () => {
        setSelectMenuOpen(!this._selectMenuOpen);
      });
      selectTrigger.dataset.xyModebarSelect = "";
      selectTrigger.dataset.xyModebarSelectTrigger = "";
      selectTrigger.setAttribute("aria-haspopup", "menu");
      selectTrigger.setAttribute("aria-expanded", "false");
      selectTrigger.replaceChildren();
      selectModeIcon = document.createElement("span");
      selectModeIcon.dataset.xyModebarSelectIcon = "";
      selectModeIcon.innerHTML = this._icon("select");
      selectTrigger.appendChild(selectModeIcon);
      selectIndicator = document.createElement("span");
      selectIndicator.dataset.xyModebarMenuIndicator = "";
      selectIndicator.innerHTML = this._icon("chevrondown");
      selectTrigger.appendChild(selectIndicator);
      this._selectMenuButton = selectTrigger;
      this._selectMenuIcon = selectModeIcon;
    }
    if (canPan) mk("pan", "Pan", () => this._setDragMode("pan"), "pan");
    // History navigation (view-state.md §4): client-scoped by construction —
    // the modebar and the root.xy handle are the only surfaces.
    if (canNavigate && this._historyEnabled()) {
      this._historyBackBtn = mk("historyback", "Back to previous view",
        () => this._historyBack());
      this._historyBackBtn.dataset.xyModebarHistory = "back";
      this._historyForwardBtn = mk("historyforward", "Forward to next view",
        () => this._historyForward());
      this._historyForwardBtn.dataset.xyModebarHistory = "forward";
      this._updateHistoryButtons();
    }
    let zoomMenu = null;
    if (hasZoomMenu) {
      zoomMenu = document.createElement("div");
      zoomMenu.dataset.xyModebarMenu = "";
      zoomMenu.setAttribute("role", "menu");
      zoomMenu.setAttribute("aria-label", "Zoom controls");
      zoomMenu.style.cssText =
        "position:absolute;display:none;flex-direction:column;z-index:7;pointer-events:auto;";
      bar.appendChild(zoomMenu);
    }
    const zoomMenuItems = [];
    const mkZoomItem = (name, label, onClick, toggles, separator = false) => {
      const button = document.createElement("button");
      button.type = "button";
      button.tabIndex = -1;
      button.dataset.xyModebarMenuItem = name;
      if (separator) button.dataset.xySeparator = "";
      button.setAttribute("role", "menuitem");
      button.style.cssText =
        "display:flex;align-items:center;pointer-events:auto;";
      this._applySlot(button, "modebar_button");
      const icon = document.createElement("span");
      icon.dataset.xyModebarMenuIcon = "";
      icon.innerHTML = this._icon(name);
      button.appendChild(icon);
      const text = document.createElement("span");
      text.textContent = label;
      button.appendChild(text);
      this._listen(button, "pointerdown", (e) => e.stopPropagation());
      this._listen(button, "click", (e) => {
        e.stopPropagation();
        setZoomMenuOpen(false, true);
        onClick();
      });
      zoomMenu.appendChild(button);
      zoomMenuItems.push(button);
      if (toggles) this._modeBtns[toggles] = button;
      return button;
    };

    if (hasZoomMenu) {
      if (canZoomButtons) {
        mkZoomItem("zoomin", this._actionLabel("Zoom In", this._axisPolicy("zoom_axes")),
          () => this._zoomBy(0.5, true, "zoom_in"));
        mkZoomItem("zoomout", this._actionLabel("Zoom Out", this._axisPolicy("zoom_axes")),
          () => this._zoomBy(2, true, "zoom_out"));
      }
      if (canBoxZoom) {
        mkZoomItem("zoom", this._actionLabel("Box Zoom", this._axisPolicy("zoom_axes")),
          () => this._setDragMode("zoom"), "zoom");
      }
      if (canReset) {
        mkZoomItem("reset", this._actionLabel("Reset View", this._resetAxisPolicy()),
          () => this._resetView(true, "reset"), null, canZoomButtons || canBoxZoom);
      }
    }

    const selectMenu = document.createElement("div");
    selectMenu.dataset.xyModebarMenu = "";
    selectMenu.dataset.xyModebarSelectMenu = "";
    selectMenu.setAttribute("role", "menu");
    selectMenu.setAttribute("aria-label", "Selection controls");
    selectMenu.style.cssText =
      "position:absolute;display:none;flex-direction:column;z-index:7;pointer-events:auto;";
    bar.appendChild(selectMenu);
    const selectMenuItems = [];
    const mkSelectItem = (name, label, mode) => {
      const button = document.createElement("button");
      button.type = "button";
      button.tabIndex = -1;
      button.dataset.xyModebarMenuItem = name;
      button.dataset.xyModebarSelectItem = mode;
      button.setAttribute("role", "menuitem");
      button.style.cssText = "display:flex;align-items:center;pointer-events:auto;";
      this._applySlot(button, "modebar_button");
      const icon = document.createElement("span");
      icon.dataset.xyModebarMenuIcon = "";
      icon.innerHTML = this._icon(name);
      button.appendChild(icon);
      const text = document.createElement("span");
      text.textContent = label;
      button.appendChild(text);
      this._listen(button, "pointerdown", (e) => e.stopPropagation());
      this._listen(button, "click", (e) => {
        e.stopPropagation();
        setSelectMenuOpen(false, true);
        this._setDragMode(mode);
      });
      selectMenu.appendChild(button);
      selectMenuItems.push(button);
      this._modeBtns[mode] = button;
    };
    if (canSelect) {
      mkSelectItem("select", "Box Select", "select");
      mkSelectItem("lasso", "Lasso Select", "select-lasso");
      mkSelectItem("selectx", "X Range", "select-x");
      mkSelectItem("selecty", "Y Range", "select-y");
    }

    const exportMenu = document.createElement("div");
    exportMenu.dataset.xyModebarMenu = "";
    exportMenu.dataset.xyModebarExportMenu = "";
    exportMenu.setAttribute("role", "menu");
    exportMenu.setAttribute("aria-label", "Toolbar options");
    exportMenu.style.cssText =
      "position:absolute;display:none;flex-direction:column;z-index:7;pointer-events:auto;";
    bar.appendChild(exportMenu);
    const exportMenuItems = [];
    const mkExportItem = (name, label, onClick, separator = false) => {
      const button = document.createElement("button");
      button.type = "button";
      button.tabIndex = -1;
      button.dataset.xyModebarMenuItem = name;
      button.dataset.xyModebarExportItem = name;
      if (separator) button.dataset.xySeparator = "";
      button.setAttribute("role", "menuitem");
      button.style.cssText = "display:flex;align-items:center;pointer-events:auto;";
      this._applySlot(button, "modebar_button");
      const icon = document.createElement("span");
      icon.dataset.xyModebarMenuIcon = "";
      icon.innerHTML = this._icon(name);
      button.appendChild(icon);
      const text = document.createElement("span");
      text.textContent = label;
      button.appendChild(text);
      this._listen(button, "pointerdown", (e) => e.stopPropagation());
      this._listen(button, "click", (e) => {
        e.stopPropagation();
        setExportMenuOpen(false, true);
        Promise.resolve(onClick()).catch((error) => console.error(`xy: ${label} failed`, error));
      });
      exportMenu.appendChild(button);
      exportMenuItems.push(button);
      return button;
    };
    // Declarative export config (spec.export, from xy.export_config): the
    // formats list governs menu availability and order. Only the client-safe
    // subset renders here — pdf/html entries are Python-side formats and are
    // skipped. No config keeps the historical png/svg/csv menu; an explicit
    // empty list hides the download items entirely.
    const EXPORT_ITEMS = {
      png: ["Export PNG", () => this._exportRaster("png")],
      jpeg: ["Export JPEG", () => this._exportRaster("jpeg")],
      webp: ["Export WebP", () => this._exportRaster("webp")],
      svg: ["Export SVG", () => this._exportSvg()],
      csv: ["Export CSV", () => this._exportCsv()],
    };
    const configuredFormats = Array.isArray(this._exportConfig().formats)
      ? this._exportConfig().formats
      : ["png", "svg", "csv"];
    for (const name of configuredFormats) {
      const item = EXPORT_ITEMS[name];
      if (item) mkExportItem(name, item[0], item[1]);
    }

    if (zoomTrigger) {
      setZoomMenuOpen = (open, restoreFocus = false) => {
        const show = Boolean(open);
        if (show) {
          setSelectMenuOpen(false);
          setExportMenuOpen(false);
        }
        this._zoomMenuOpen = show;
        zoomTrigger.setAttribute("aria-expanded", String(show));
        if (!show) {
          zoomMenu.style.display = "none";
          zoomIndicator.style.transform = "none";
          if (restoreFocus) zoomTrigger.focus();
          return;
        }
        zoomMenu.style.display = "flex";
        zoomMenu.style.visibility = "hidden";
        const rootRect = root.getBoundingClientRect();
        const barRect = bar.getBoundingClientRect();
        const rootLeft = barRect.left - rootRect.left;
        const rootTop = barRect.top - rootRect.top;
        const below = bar.offsetHeight + 6;
        const above = -zoomMenu.offsetHeight - 6;
        const preferredTop = barRect.bottom + 6 + zoomMenu.offsetHeight <= rootRect.bottom
          ? below
          : above;
        zoomIndicator.style.transform = preferredTop === above ? "rotate(180deg)" : "none";
        const maxLeft = root.clientWidth - rootLeft - zoomMenu.offsetWidth;
        const maxTop = root.clientHeight - rootTop - zoomMenu.offsetHeight;
        zoomMenu.style.left = `${Math.max(-rootLeft, Math.min(maxLeft, zoomTrigger.offsetLeft))}px`;
        zoomMenu.style.top = `${Math.max(-rootTop, Math.min(maxTop, preferredTop))}px`;
        zoomMenu.style.visibility = "visible";
      };
    }
    setSelectMenuOpen = (open, restoreFocus = false) => {
      if (!selectTrigger) return;
      const show = Boolean(open);
      if (show) {
        setZoomMenuOpen(false);
        setExportMenuOpen(false);
      }
      this._selectMenuOpen = show;
      selectTrigger.setAttribute("aria-expanded", String(show));
      if (!show) {
        selectMenu.style.display = "none";
        selectIndicator.style.transform = "none";
        if (restoreFocus) selectTrigger.focus();
        return;
      }
      selectMenu.style.display = "flex";
      selectMenu.style.visibility = "hidden";
      const rootRect = root.getBoundingClientRect();
      const barRect = bar.getBoundingClientRect();
      const rootLeft = barRect.left - rootRect.left;
      const rootTop = barRect.top - rootRect.top;
      const below = bar.offsetHeight + 6;
      const above = -selectMenu.offsetHeight - 6;
      const preferredTop = barRect.bottom + 6 + selectMenu.offsetHeight <= rootRect.bottom
        ? below
        : above;
      selectIndicator.style.transform = preferredTop === above ? "rotate(180deg)" : "none";
      const maxLeft = root.clientWidth - rootLeft - selectMenu.offsetWidth;
      const maxTop = root.clientHeight - rootTop - selectMenu.offsetHeight;
      selectMenu.style.left = `${Math.max(-rootLeft, Math.min(maxLeft, selectTrigger.offsetLeft))}px`;
      selectMenu.style.top = `${Math.max(-rootTop, Math.min(maxTop, preferredTop))}px`;
      selectMenu.style.visibility = "visible";
    };
    setExportMenuOpen = (open, restoreFocus = false) => {
      // export_config(formats=[]) leaves nothing to show: the grip stays a
      // pure drag handle rather than opening an empty menu.
      const show = Boolean(open) && exportMenuItems.length > 0;
      if (show) {
        setZoomMenuOpen(false);
        setSelectMenuOpen(false);
      }
      this._exportMenuOpen = show;
      grip.setAttribute("aria-expanded", String(show));
      if (!show) {
        exportMenu.style.display = "none";
        if (restoreFocus) grip.focus();
        return;
      }
      exportMenu.style.display = "flex";
      exportMenu.style.visibility = "hidden";
      const rootRect = root.getBoundingClientRect();
      const barRect = bar.getBoundingClientRect();
      const rootLeft = barRect.left - rootRect.left;
      const rootTop = barRect.top - rootRect.top;
      const below = bar.offsetHeight + 6;
      const above = -exportMenu.offsetHeight - 6;
      const preferredTop = barRect.bottom + 6 + exportMenu.offsetHeight <= rootRect.bottom
        ? below
        : above;
      const maxLeft = root.clientWidth - rootLeft - exportMenu.offsetWidth;
      const maxTop = root.clientHeight - rootTop - exportMenu.offsetHeight;
      exportMenu.style.left = `${Math.max(-rootLeft, Math.min(maxLeft, grip.offsetLeft))}px`;
      exportMenu.style.top = `${Math.max(-rootTop, Math.min(maxTop, preferredTop))}px`;
      exportMenu.style.visibility = "visible";
    };
    this._closeModebarMenu = () => {
      setZoomMenuOpen(false);
      setSelectMenuOpen(false);
      setExportMenuOpen(false);
    };
    this._listen(document, "pointerdown", (e) => {
      if (this._zoomMenuOpen && !bar.contains(e.target)) setZoomMenuOpen(false);
      if (this._selectMenuOpen && !bar.contains(e.target)) setSelectMenuOpen(false);
      if (this._exportMenuOpen && !bar.contains(e.target)) setExportMenuOpen(false);
    });
    if (zoomTrigger) {
      this._listen(zoomTrigger, "keydown", (e) => {
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        e.stopPropagation();
        setZoomMenuOpen(true);
        const index = e.key === "ArrowDown" ? 0 : zoomMenuItems.length - 1;
        zoomMenuItems[index].focus();
      });
      this._listen(zoomMenu, "keydown", (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          setZoomMenuOpen(false, true);
          return;
        }
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
        e.preventDefault();
        const current = zoomMenuItems.indexOf(document.activeElement);
        let next = e.key === "Home" ? 0 : e.key === "End" ? zoomMenuItems.length - 1 : current;
        if (e.key === "ArrowDown") next = (current + 1) % zoomMenuItems.length;
        if (e.key === "ArrowUp") next = (current - 1 + zoomMenuItems.length) % zoomMenuItems.length;
        zoomMenuItems[next].focus();
      });
    }
    if (selectTrigger) {
      this._listen(selectTrigger, "keydown", (e) => {
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        e.stopPropagation();
        setSelectMenuOpen(true);
        const index = e.key === "ArrowDown" ? 0 : selectMenuItems.length - 1;
        selectMenuItems[index].focus();
      });
      this._listen(selectMenu, "keydown", (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          setSelectMenuOpen(false, true);
          return;
        }
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
        e.preventDefault();
        const current = selectMenuItems.indexOf(document.activeElement);
        let next = e.key === "Home" ? 0 : e.key === "End" ? selectMenuItems.length - 1 : current;
        if (e.key === "ArrowDown") next = (current + 1) % selectMenuItems.length;
        if (e.key === "ArrowUp") {
          next = (current - 1 + selectMenuItems.length) % selectMenuItems.length;
        }
        selectMenuItems[next].focus();
      });
    }
    this._listen(grip, "keydown", (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      // export_config(formats=[]) (or a PDF/HTML-only list) leaves no
      // client-side items: nothing to open or focus.
      if (!exportMenuItems.length) return;
      e.preventDefault();
      e.stopPropagation();
      setExportMenuOpen(true);
      const index = e.key === "ArrowDown" ? 0 : exportMenuItems.length - 1;
      exportMenuItems[index].focus();
    });
    this._listen(exportMenu, "keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setExportMenuOpen(false, true);
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const current = exportMenuItems.indexOf(document.activeElement);
      let next = e.key === "Home" ? 0 : e.key === "End" ? exportMenuItems.length - 1 : current;
      if (e.key === "ArrowDown") next = (current + 1) % exportMenuItems.length;
      if (e.key === "ArrowUp") {
        next = (current - 1 + exportMenuItems.length) % exportMenuItems.length;
      }
      exportMenuItems[next].focus();
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
    this._closeModebarMenu?.();
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
    // lives in the defeatable :where([data-xy-slot="canvas"]) stylesheet keyed on
    // this attribute — inline cursor would beat a user's cursor-* utility class.
    if (this.canvas) this.canvas.dataset.xyDragmode = mode;
    // Active state is a class (defeatable via the stylesheet's :where rule /
    // --chart-modebar-active), not an inline background that would beat classes.
    for (const [name, btn] of Object.entries(this._modeBtns || {})) {
      btn.classList.toggle("xy-active", name === mode);
      btn.setAttribute("aria-pressed", String(name === mode));
    }
    this._zoomMenuButton?.classList.toggle("xy-active", mode === "zoom");
    this._selectMenuButton?.classList.toggle("xy-active", mode.startsWith("select"));
    const selectionMode = {
      select: ["select", "Box Select"],
      "select-lasso": ["lasso", "Lasso Select"],
      "select-x": ["selectx", "X Range"],
      "select-y": ["selecty", "Y Range"],
    }[mode];
    if (selectionMode && this._selectMenuButton && this._selectMenuIcon) {
      const [iconName, label] = selectionMode;
      this._selectMenuIcon.innerHTML = this._icon(iconName);
      this._selectMenuButton.title = `Selection controls: ${label}`;
      this._selectMenuButton.setAttribute("aria-label", `Selection controls: ${label}`);
    }
  },

  _actionLabel(action, axes) {
    const ids = Array.isArray(axes) ? axes : [...axes || []];
    if (!ids.length) return action;
    return `${action} on ${ids.join(" and ")} ${ids.length === 1 ? "axis" : "axes"}`;
  },

  _updateZoomMenuLabel() {
    if (!this._zoomMenuLabel || !this.view || !this.view0) return;
    const axisPercent = (axisId, lo, hi, homeLo, homeHi) => {
      const axis = this._axis(axisId);
      const span = Math.abs(this._axisCoord(axis, hi) - this._axisCoord(axis, lo));
      const homeSpan = Math.abs(
        this._axisCoord(axis, homeHi) - this._axisCoord(axis, homeLo)
      );
      return Number.isFinite(span) && span > 0 && Number.isFinite(homeSpan) && homeSpan > 0
        ? (homeSpan / span) * 100
        : null;
    };
    const zoomAxes = [...this._zoomAxes()];
    const percentages = zoomAxes.map((axisId) => {
      const [lo, hi] = this._axisRange(axisId);
      const [homeLo, homeHi] = this._axisRange(axisId, this.view0);
      return [axisId, axisPercent(axisId, lo, hi, homeLo, homeHi)];
    }).filter((entry) => entry[1] !== null);
    const percent = percentages[0]?.[1] ?? 100;
    const rounded = Math.round(percent);
    const exactText = percent < 1 ? "<1%" : `${rounded}%`;
    const displayText = rounded > 999 ? `${String(rounded).slice(0, 3)}…%` : exactText;
    if (this._zoomMenuLabel.dataset.xyZoomExact === exactText
        && this._zoomMenuLabel.textContent === displayText) return;
    this._zoomMenuLabel.textContent = displayText;
    this._zoomMenuLabel.dataset.xyZoomExact = exactText;
    const details = percentages.map(([axisId, value]) => `${axisId} ${Math.round(value)}%`).join(", ");
    this._zoomMenuButton.title = `Zoom controls (${details || exactText})`;
    this._zoomMenuButton.setAttribute("aria-label", `Zoom controls, ${details || exactText}`);
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
    if (this._destroyed) return [];
    const target = this._clampView(this._viewFrom(next), { anchors: opts.anchors });
    const changedAxes = this._axisIds().filter((axisId) => {
      const before = this._axisRange(axisId);
      const after = this._axisRange(axisId, target);
      return before[0] !== after[0] || before[1] !== after[1];
    });
    if (!changedAxes.length) return [];
    // History push (view-state.md §4): snapshot the pre-mutation durable
    // state once per interaction id; linked/history sources never push.
    this._historyRecord({
      source: opts.source || "programmatic",
      interactionId: opts.interactionId,
      history: opts.history,
    });
    const animate = opts.animate === true && !this._prefersReducedMotion();
    const duration = opts.duration || 180;
    if (!animate || duration <= 0) {
      this._cancelViewAnimation();
      this.view = target;
      this.draw();
      if (opts.request !== false) this._scheduleViewRequest();
      this._emitViewChange(opts.source || "programmatic", {
        axes: changedAxes,
        phase: opts.phase || "end",
        interactionId: opts.interactionId,
        broadcast: opts.broadcast,
      });
      return changedAxes;
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
      this._viewAnim.changedAxes = [...new Set([...this._viewAnim.changedAxes, ...changedAxes])];
      return changedAxes;
    }

    this._viewAnim = {
      target,
      last: now,
      tau,
      changedAxes,
    };
    const lerp = (a, b, t) => a + (b - a) * t;
    const span = (v) => Math.max(
      ...this._axisIds().map((axisId) => {
        const [lo, hi] = this._axisRange(axisId, v);
        return Math.abs(hi - lo);
      }),
      1e-12,
    );
    const closeEnough = (a, b) => {
      const tol = span(b) * 1e-4;
      return Math.max(...this._axisIds().flatMap((axisId) => {
        const ar = this._axisRange(axisId, a), br = this._axisRange(axisId, b);
        return [Math.abs(ar[0] - br[0]), Math.abs(ar[1] - br[1])];
      })) <= tol;
    };
    const step = (nowFrame) => {
      if (this._destroyed) { this._animRaf = null; return; }
      const anim = this._viewAnim;
      if (!anim) { this._animRaf = null; return; }
      const dt = Math.max(0, Math.min(64, nowFrame - anim.last));
      anim.last = nowFrame;
      const k = 1 - Math.exp(-dt / anim.tau);
      const t = closeEnough(this.view, anim.target) ? 1 : k;
      const ranges = {};
      for (const axisId of this._axisIds()) {
        const current = this._axisRange(axisId), targetRange = this._axisRange(axisId, anim.target);
        ranges[axisId] = [
          lerp(current[0], targetRange[0], t),
          lerp(current[1], targetRange[1], t),
        ];
      }
      this.view = this._copyView({ ranges });
      if (t < 1) {
        this.draw();
        this._animRaf = requestAnimationFrame(step);
      } else {
        this._animRaf = null;
        this._viewAnim = null;
        this.view = anim.target;
        this._lastLabelDraw = null;
        this.draw();
        this._emitViewChange(opts.source || "programmatic", {
          axes: anim.changedAxes,
          phase: opts.phase || "end",
          interactionId: opts.interactionId,
          broadcast: opts.broadcast,
        });
      }
    };
    this._animRaf = requestAnimationFrame(step);
    return changedAxes;
  },

  // Keep a proposed viewport wholly inside each axis's optional hard bounds.
  // Work in scale coordinates so log bounds clamp multiplicatively, while
  // preserving the range direction used by reversed axes.
  _zoomLimitForAxis(axisId) {
    if (!this._axisPolicy("zoom_axes").includes(axisId)) return [null, null];
    const configured = this.interaction?.zoom_limits;
    if (configured && typeof configured === "object" && !Array.isArray(configured)) {
      const pair = configured[axisId];
      if (Array.isArray(pair) && pair.length === 2) return pair;
    }
    return [1, null];
  },

  _clampAxisRange(axisId, lo, hi, anchorFrac = 0.5) {
    const axis = this._axis(axisId);
    let c0 = this._axisCoord(axis, lo), c1 = this._axisCoord(axis, hi);
    if (![c0, c1].every(Number.isFinite) || c0 === c1) return this._axisRange(axisId, this.view0);
    const home = this.view0?.ranges?.[axisId];
    if (home) {
      const h0 = this._axisCoord(axis, home[0]), h1 = this._axisCoord(axis, home[1]);
      const homeSpan = Math.abs(h1 - h0);
      const [minMagRaw, maxMagRaw] = this._zoomLimitForAxis(axisId);
      const minMag = Number(minMagRaw), maxMag = Number(maxMagRaw);
      const maxSpan = Number.isFinite(minMag) && minMag > 0 ? homeSpan / minMag : Infinity;
      const minSpan = Number.isFinite(maxMag) && maxMag > 0 ? homeSpan / maxMag : 0;
      const requestedSpan = Math.abs(c1 - c0);
      const limitedSpan = Math.max(minSpan, Math.min(maxSpan, requestedSpan));
      if (Number.isFinite(limitedSpan) && limitedSpan > 0 && limitedSpan !== requestedSpan) {
        const direction = c1 < c0 ? -1 : 1;
        const anchor = c0 + anchorFrac * (c1 - c0);
        c0 = anchor - anchorFrac * limitedSpan * direction;
        c1 = anchor + (1 - anchorFrac) * limitedSpan * direction;
      }
    }
    // Positional envelope: explicit axis bounds, tightened to the home window
    // when the axis is contained (§7.2). Inside the envelope the window
    // slides; a window at least as large as the envelope pins to it exactly,
    // so a contained axis at home magnification cannot move at all.
    let boundLo = -Infinity, boundHi = Infinity;
    if (Array.isArray(axis.bounds) && axis.bounds.length === 2) {
      const b0 = this._axisCoord(axis, axis.bounds[0]);
      const b1 = this._axisCoord(axis, axis.bounds[1]);
      if (![c0, c1, b0, b1].every(Number.isFinite) || b0 === b1) return [lo, hi];
      boundLo = Math.min(b0, b1);
      boundHi = Math.max(b0, b1);
    }
    if (home && this._axisContained(axisId)) {
      const h0 = this._axisCoord(axis, home[0]);
      const h1 = this._axisCoord(axis, home[1]);
      if ([h0, h1].every(Number.isFinite) && h0 !== h1) {
        boundLo = Math.max(boundLo, Math.min(h0, h1));
        boundHi = Math.min(boundHi, Math.max(h0, h1));
      }
    }
    if (!Number.isFinite(boundLo) || !Number.isFinite(boundHi) || boundHi <= boundLo) {
      return [this._axisValue(axis, c0), this._axisValue(axis, c1)];
    }
    const reverse = c1 < c0;
    let outLo = Math.min(c0, c1), outHi = Math.max(c0, c1);
    if (outHi - outLo >= boundHi - boundLo) {
      outLo = boundLo;
      outHi = boundHi;
    } else {
      const shift = Math.max(boundLo - outLo, Math.min(boundHi - outHi, 0));
      outLo += shift;
      outHi += shift;
    }
    const first = reverse ? outHi : outLo;
    const second = reverse ? outLo : outHi;
    return [this._axisValue(axis, first), this._axisValue(axis, second)];
  },

  _clampView(view, opts = {}) {
    const candidate = this._viewFrom(view, this.view0);
    const ranges = {};
    for (const axisId of this._axisIds()) {
      const [lo, hi] = this._axisRange(axisId, candidate);
      ranges[axisId] = this._clampAxisRange(axisId, lo, hi, opts.anchors?.[axisId] ?? 0.5);
    }
    return this._copyView({ ranges });
  },

  // Center-anchored zoom (f<1 in, f>1 out) — the modebar buttons; wheel is
  // cursor-anchored. Shares the §16 precision floor so we never zoom past f32.
  _zoomAxes() {
    return new Set(this._axisPolicy("zoom_axes"));
  },

  _zoomBy(f, animate = false, source = f < 1 ? "zoom_in" : "zoom_out") {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const axes = this._zoomAxes();
    const ranges = Object.fromEntries(
      this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId, base)]])
    );
    for (const axisId of axes) {
      const [lo, hi] = ranges[axisId];
      const range = this._zoomAxisRange(axisId, lo, hi, f, 0.5);
      if (range) ranges[axisId] = range;
    }
    this._setView({ ranges }, {
      animate,
      source,
      phase: "end",
      interactionId: ++this._interactionSeq,
    });
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

  _zoomAt(f, fx, fy, animate = false, duration = 120, opts = {}) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    // An axis-band gesture scopes the zoom to the hovered axis (§6 of
    // view-state.md); the policy still filters, never grants.
    const axes = Array.isArray(opts.axes)
      ? new Set(opts.axes.filter((axisId) => this._zoomAxes().has(axisId)))
      : this._zoomAxes();
    const ranges = Object.fromEntries(
      this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId, base)]])
    );
    const anchors = {};
    for (const axisId of axes) {
      const anchor = this._axisDim(axisId) === "x" ? fx : fy;
      const [lo, hi] = ranges[axisId];
      const range = this._zoomAxisRange(axisId, lo, hi, f, anchor);
      if (range) ranges[axisId] = range;
      anchors[axisId] = anchor;
    }
    return this._setView({ ranges }, {
      animate,
      duration,
      anchors,
      source: opts.source || "wheel_zoom",
      phase: opts.phase || "update",
      interactionId: opts.interactionId,
    });
  },

  _queueWheelZoom(factor, fx, fy, axesScope = null) {
    if (!Number.isFinite(factor) || factor <= 0) return;
    // A queued delta keeps the gesture open: kill the pending end timer here,
    // not in the rAF. Otherwise a wheel event landing just before the 90 ms
    // timer fires lets "end" emit — and the apply rAF, queued earlier, then
    // overwrites it in the event coalescer — while this delta is still
    // pending, so the gesture would never deliver an "end" carrying the final
    // committed range. The rAF re-arms the timer after the delta applies.
    clearTimeout(this._wheelZoomEndTimer);
    this._wheelZoomEndTimer = null;
    // A scope change (plot wheel vs an axis band, or two different bands) is
    // a different gesture: close the open one so its id is not shared.
    const scopeKey = Array.isArray(axesScope) ? axesScope.join(",") : "";
    if (this._wheelGesture && this._wheelGesture.scopeKey !== scopeKey) {
      const gesture = this._wheelGesture;
      this._wheelGesture = null;
      if (gesture.axes.size) {
        this._emitViewChange("wheel_zoom", {
          axes: [...gesture.axes],
          phase: "end",
          interactionId: gesture.interactionId,
        });
      }
    }
    if (!this._wheelGesture) {
      this._wheelGesture = {
        interactionId: ++this._interactionSeq,
        axes: new Set(),
        scopeKey,
      };
    }
    if (!this._pendingWheelZoom) {
      this._pendingWheelZoom = {
        factor: 1,
        fx,
        fy,
        interactionId: this._wheelGesture.interactionId,
        axes: [],
        axesScope,
      };
    }
    this._pendingWheelZoom.factor *= factor;
    this._pendingWheelZoom.fx = fx;
    this._pendingWheelZoom.fy = fy;
    this._pendingWheelZoom.axesScope = axesScope;
    if (this._wheelZoomRaf) return;
    this._wheelZoomRaf = requestAnimationFrame(() => {
      this._wheelZoomRaf = null;
      const pending = this._pendingWheelZoom;
      this._pendingWheelZoom = null;
      if (!pending || this._destroyed) return;
      pending.axes = this._zoomAt(pending.factor, pending.fx, pending.fy, false, 120, {
        source: "wheel_zoom",
        phase: "update",
        interactionId: pending.interactionId,
        axes: pending.axesScope || undefined,
      }) || [];
      for (const axisId of pending.axes) this._wheelGesture?.axes.add(axisId);
      clearTimeout(this._wheelZoomEndTimer);
      this._wheelZoomEndTimer = setTimeout(() => {
        const gesture = this._wheelGesture;
        this._wheelGesture = null;
        if (this._destroyed || !gesture || !gesture.axes.size) return;
        this._emitViewChange("wheel_zoom", {
          axes: [...gesture.axes],
          phase: "end",
          interactionId: gesture.interactionId,
        });
      }, 90);
    });
  },

  // Box-zoom: fit the view to the dragged data rectangle (§16 precision floor;
  // ignore degenerate drags that would collapse a span below f32 resolution).
  _zoomToBox(d0, d1, animate = false, opts = {}) {
    const axes = this._zoomAxes();
    const fractions = {};
    for (const dim of ["x", "y"]) {
      const primary = this._axis(dim);
      const [lo, hi] = this._axisRange(dim);
      const c0 = this._axisCoord(primary, lo), c1 = this._axisCoord(primary, hi);
      const first = this._axisCoord(primary, d0[dim === "x" ? 0 : 1]);
      const second = this._axisCoord(primary, d1[dim === "x" ? 0 : 1]);
      if (![c0, c1, first, second].every(Number.isFinite) || c0 === c1) return [];
      fractions[dim] = [(first - c0) / (c1 - c0), (second - c0) / (c1 - c0)];
    }
    const ranges = Object.fromEntries(
      this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId)]])
    );
    const anchors = {};
    for (const axisId of axes) {
      const axis = this._axis(axisId);
      const [lo, hi] = ranges[axisId];
      const c0 = this._axisCoord(axis, lo), c1 = this._axisCoord(axis, hi);
      const [f0, f1] = fractions[this._axisDim(axisId)];
      const a = c0 + f0 * (c1 - c0), b = c0 + f1 * (c1 - c0);
      const minSpan = Math.max(Math.abs(a), Math.abs(b), 1e-30) * 1e-12;
      if (!Number.isFinite(a) || !Number.isFinite(b) || Math.abs(b - a) < minSpan) continue;
      const reverse = c1 < c0;
      const low = Math.min(a, b), high = Math.max(a, b);
      ranges[axisId] = [
        this._axisValue(axis, reverse ? high : low),
        this._axisValue(axis, reverse ? low : high),
      ];
      anchors[axisId] = 0.5;
    }
    return this._setView({ ranges }, {
      animate,
      anchors,
      source: opts.source || "box_zoom",
      phase: opts.phase || "end",
      interactionId: opts.interactionId,
    });
  },

  _resetView(animate = true, source = "reset", axesOverride = null) {
    const ranges = Object.fromEntries(
      this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId)]])
    );
    for (const axisId of axesOverride || this._resetAxisPolicy()) {
      ranges[axisId] = [...this._axisRange(axisId, this.view0)];
    }
    return this._setView({ ranges }, {
      animate,
      source,
      phase: "end",
      interactionId: ++this._interactionSeq,
    });
  },

  // Declarative export defaults (spec.export, produced by xy.export_config).
  // The same filename/scale/background/quality semantics as the Python
  // exporters, so a chart downloads identically from either side.
  _exportConfig() {
    const config = this.spec && this.spec.export;
    return config && typeof config === "object" ? config : {};
  },

  _exportFilename(extension) {
    const configured = this._exportConfig().filename;
    if (typeof configured === "string" && configured) return `${configured}.${extension}`;
    const title = String(this.spec.title || "xy-chart")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "xy-chart";
    return `${title}.${extension}`;
  },

  _downloadExport(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  },

  _exportSvgMarkup() {
    this._drawNow?.();
    this.gl?.finish?.();
    const width = this.size.w;
    const height = this.size.h;
    const clone = this.root.cloneNode(true);
    clone.style.width = `${width}px`;
    clone.style.height = `${height}px`;
    clone.style.margin = "0";
    clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");

    // The clone is detached from its host, so inherited theme tokens and text
    // styles must be made explicit before it is serialized for SVG/PNG export.
    const computed = getComputedStyle(this.root);
    const inheritedProperties = [
      "color", "font-family", "font-size", "font-style", "font-weight",
      "letter-spacing", "line-height",
    ];
    const chartTokens = [
      "--chart-bg", "--chart-text", "--chart-grid", "--chart-axis",
      "--chart-tooltip-bg", "--chart-tooltip-text", "--chart-legend-bg",
      "--chart-badge-bg", "--chart-badge-text", "--chart-modebar-bg",
      "--chart-modebar-active", "--chart-selection", "--chart-selection-fill",
      "--chart-zoom-selection", "--chart-zoom-selection-fill", "--chart-crosshair",
      "--chart-annotation-text", "--chart-cursor", "--chart-cursor-pan",
    ];
    for (let i = 0; i < computed.length; i++) {
      const property = computed.item(i);
      if (!property.startsWith("--")) continue;
      const value = computed.getPropertyValue(property).trim();
      if (value) clone.style.setProperty(property, value);
    }
    for (const property of [...inheritedProperties, ...chartTokens]) {
      const value = computed.getPropertyValue(property).trim();
      if (value) clone.style.setProperty(property, value);
    }

    const sourceCanvases = [...this.root.querySelectorAll("canvas")];
    const clonedCanvases = [...clone.querySelectorAll("canvas")];
    for (let i = 0; i < clonedCanvases.length; i++) {
      const source = sourceCanvases[i];
      const target = clonedCanvases[i];
      if (!source || !target) continue;
      const image = document.createElement("img");
      image.setAttribute("src", source.toDataURL("image/png"));
      image.setAttribute("alt", "");
      image.setAttribute("style", target.getAttribute("style") || "");
      image.setAttribute("width", String(source.clientWidth || source.width));
      image.setAttribute("height", String(source.clientHeight || source.height));
      for (const attr of target.attributes) {
        if (attr.name.startsWith("data-")) image.setAttribute(attr.name, attr.value);
      }
      target.replaceWith(image);
    }

    clone.querySelectorAll(
      '[data-xy-slot="modebar"],[data-xy-slot="tooltip"],' +
      '[data-xy-slot="selection"],[data-xy-selection-lasso-overlay],' +
      '[data-xy-slot="crosshair_x"],[data-xy-slot="crosshair_y"]'
    ).forEach((node) => node.remove());
    const stylesheet = document.createElement("style");
    stylesheet.textContent = XY_CHROME_CSS;
    clone.prepend(stylesheet);
    const content = new XMLSerializer().serializeToString(clone);
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
      `viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">` +
      `${content}</foreignObject></svg>`;
  },

  _exportSvg() {
    const svg = this._exportSvgMarkup();
    this._downloadExport(
      new Blob([svg], { type: "image/svg+xml;charset=utf-8" }),
      this._exportFilename("svg")
    );
  },

  _exportPng() {
    return this._exportRaster("png");
  },

  _exportRaster(format) {
    const svg = this._exportSvgMarkup();
    const sourceUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    const image = new Image();
    const config = this._exportConfig();
    const mime = { png: "image/png", jpeg: "image/jpeg", webp: "image/webp" }[format];
    if (!mime) return Promise.reject(new Error(`unsupported raster export ${format}`));
    return new Promise((resolve, reject) => {
      image.onload = () => {
        const scale = Number.isFinite(config.scale) && config.scale > 0
          ? config.scale
          : Math.max(1, window.devicePixelRatio || 1);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(this.size.w * scale);
        canvas.height = Math.round(this.size.h * scale);
        const ctx = canvas.getContext("2d");
        // Background policy mirrors the Python exporters: JPEG has no alpha
        // channel so it always flattens onto the configured backdrop (default
        // white); PNG/WebP paint a backdrop only for an explicit opaque color
        // and keep transparency otherwise.
        const configured = typeof config.background === "string" &&
          config.background !== "auto" ? config.background : null;
        const transparent = configured === "transparent" || configured === "none";
        if (format === "jpeg") {
          ctx.fillStyle = configured && !transparent ? configured : "#ffffff";
          ctx.fillRect(0, 0, canvas.width, canvas.height);
        } else if (configured && !transparent) {
          ctx.fillStyle = configured;
          ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
        ctx.scale(scale, scale);
        ctx.drawImage(image, 0, 0, this.size.w, this.size.h);
        const quality = Number.isFinite(config.quality)
          ? Math.min(1, Math.max(0.01, config.quality / 100))
          : 0.9;
        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error(`${format.toUpperCase()} encoding returned no data`));
            return;
          }
          // A browser without the requested encoder returns PNG instead
          // (canvas.toBlob's specified fallback); name the download by what
          // was actually produced so the extension never lies.
          const actual = blob.type === "image/jpeg" ? "jpg"
            : blob.type === "image/webp" ? "webp"
            : "png";
          this._downloadExport(blob, this._exportFilename(actual));
          resolve();
        }, mime, format === "png" ? undefined : quality);
      };
      image.onerror = () => {
        reject(new Error("chart SVG could not be rasterized"));
      };
      image.src = sourceUrl;
    });
  },

  _exportCsvText() {
    const columns = ["trace", "name", "kind", "index", "x", "y", "x0", "x1", "y0", "y1", "value"];
    const rows = [columns];
    const clean = (value) => Number.isFinite(value) ? value : "";
    for (const g of this.gpuTraces || []) {
      const trace = g.trace || {};
      const prefix = [trace.id ?? "", trace.name ?? "", trace.kind ?? ""];
      if (g._cpuRect) {
        const r = g._cpuRect;
        const n = Math.min(r.x0.length, r.x1.length, r.y0.length, r.y1.length);
        for (let i = 0; i < n; i++) {
          rows.push([...prefix, i, "", "",
            clean(this._decodeValue(r.x0, r.x0Meta, i)),
            clean(this._decodeValue(r.x1, r.x1Meta, i)),
            clean(this._decodeValue(r.y0, r.y0Meta, i)),
            clean(this._decodeValue(r.y1, r.y1Meta, i)), ""]);
        }
        continue;
      }
      if (g.heatmap && g._cpuHeatmap) {
        const h = g.heatmap;
        for (let i = 0; i < g._cpuHeatmap.grid.length; i++) {
          const row = Math.floor(i / h.w);
          const col = i % h.w;
          const x = h.xRange[0] + (col + 0.5) * ((h.xRange[1] - h.xRange[0]) / h.w);
          const y = h.yRange[0] + (row + 0.5) * ((h.yRange[1] - h.yRange[0]) / h.h);
          const value = this._denormalizeUnit(g._cpuHeatmap.grid[i], trace.color?.domain);
          rows.push([...prefix, i, clean(x), clean(y), "", "", "", "", clean(value)]);
        }
        continue;
      }
      const cpu = g._cpu;
      if (!cpu?.x || !cpu?.y) continue;
      const n = Math.min(cpu.x.length, cpu.y.length, g.n || Infinity);
      for (let i = 0; i < n; i++) {
        rows.push([...prefix, i,
          clean(this._decodeValue(cpu.x, cpu.xMeta || g.xMeta, i)),
          clean(this._decodeValue(cpu.y, cpu.yMeta || g.yMeta, i)),
          "", "", "", "", ""]);
      }
    }
    const quote = (value) => {
      const text = String(value ?? "");
      const escaped = text.split('"').join('""');
      return text.includes(",") || text.includes('"') || text.includes("\r") || text.includes("\n")
        ? `"${escaped}"`
        : text;
    };
    return rows.map((row) => row.map(quote).join(",")).join("\r\n") + "\r\n";
  },

  _exportCsv() {
    this._downloadExport(
      new Blob([this._exportCsvText()], { type: "text/csv;charset=utf-8" }),
      this._exportFilename("csv")
    );
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
        return svg('<path d="M7 3.5 H3.5 V7 M13 3.5 H16.5 V7 ' +
          'M3.5 13 V16.5 H7 M16.5 13 V16.5 H13"/>');
      case "select":
        return svg('<path d="M7 4 H4 V7 M13 4 H16 V7 M4 13 V16 H7 ' +
          'M16 13 V16 H13"/><circle cx="7" cy="8" r="1" fill="currentColor" ' +
          'stroke="none"/><circle cx="12.5" cy="9" r="1" fill="currentColor" stroke="none"/>' +
          '<circle cx="9.5" cy="13" r="1" fill="currentColor" stroke="none"/>');
      case "lasso":
        return svg('<path d="M5 5.5 C7 3 13.5 3.5 15.5 7 C17 10 14 15.5 9 15.5 ' +
          'C4.5 15.5 2.5 11 4 7.5 Z"/><circle cx="5" cy="5.5" r="1" ' +
          'fill="currentColor" stroke="none"/><circle cx="15.5" cy="7" r="1" ' +
          'fill="currentColor" stroke="none"/><circle cx="9" cy="15.5" r="1" ' +
          'fill="currentColor" stroke="none"/>');
      case "selectx":
        return svg('<path d="M5 4 V16 M15 4 V16 M7 10 H13 ' +
          'M7 10 L9 8 M7 10 L9 12 M13 10 L11 8 M13 10 L11 12"/>');
      case "selecty":
        return svg('<path d="M4 5 H16 M4 15 H16 M10 7 V13 ' +
          'M10 7 L8 9 M10 7 L12 9 M10 13 L8 11 M10 13 L12 11"/>');
      case "chevrondown":
        return svg('<path d="M6 8 L10 12 L14 8"/>');
      case "collapse":
        return svg('<path d="M4 5 H16 M4 15 H16 M7 8 L10 11 L13 8"/>');
      case "expand":
        return svg('<path d="M4 5 H16 M4 15 H16 M7 12 L10 9 L13 12"/>');
      case "png":
        return svg('<path d="M5 2.5 H12 L15.5 6 V17.5 H5 Z"/><path d="M12 2.5 V6 H15.5"/>' +
          '<path d="M7 13 L9 10.5 L11 12 L13.5 9 V15 H7 Z"/>');
      case "jpeg":
        return svg('<path d="M5 2.5 H12 L15.5 6 V17.5 H5 Z"/><path d="M12 2.5 V6 H15.5"/>' +
          '<circle cx="8.5" cy="10" r="1.2"/><path d="M7 15 L10 12 L13.5 15 Z"/>');
      case "webp":
        return svg('<path d="M5 2.5 H12 L15.5 6 V17.5 H5 Z"/><path d="M12 2.5 V6 H15.5"/>' +
          '<path d="M7 11 C8 10 9 10 10 11 C11 12 12 12 13.5 11"/>' +
          '<path d="M7 14 C8 13 9 13 10 14 C11 15 12 15 13.5 14"/>');
      case "svg":
        return svg('<path d="M5 2.5 H12 L15.5 6 V17.5 H5 Z"/><path d="M12 2.5 V6 H15.5"/>' +
          '<path d="M7 13 L9 9 L11 14 L13.5 10"/>');
      case "csv":
        return svg('<path d="M5 2.5 H12 L15.5 6 V17.5 H5 Z"/><path d="M12 2.5 V6 H15.5"/>' +
          '<path d="M7 9 H13 M7 12 H13 M7 15 H13 M9 8 V16"/>');
      case "reset":
        return svg('<path d="M4 10 a6 6 0 1 1 1.8 4.3"/><path d="M4 6 V10 H8"/>');
      case "historyback":
        return svg('<path d="M13 4 L7 10 L13 16"/>');
      case "historyforward":
        return svg('<path d="M7 4 L13 10 L7 16"/>');
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
